"""Live AIS vessel feed (aisstream.io).

Unlike every other service here, this one is *push*, not pull: aisstream.io
delivers a websocket firehose of AIS broadcasts, so the module owns a
long-lived background task that keeps an in-memory picture of "where is
every vessel right now" which requests then read from. There is no upstream
endpoint to query per-request — the socket is the only way in, and the key
must stay server-side.

This is deliberately distinct from `gfw.py`, which proxies *aggregate*
30-day vessel presence as heatmap PNGs. That answers "where do ships
generally go"; this answers "which named ship is at this spot right now".

Two AIS message types are merged into one record per vessel, because
neither is sufficient alone:
  - PositionReport (every few seconds): position, speed, course, heading,
    navigational status.
  - ShipStaticData (every ~6 minutes): name, IMO, call sign, destination,
    hull dimensions, draught, ETA.
A vessel is therefore usually visible with a position long before its static
details arrive, and the API surfaces whatever is known so far rather than
withholding a vessel until it is complete.

Degradation is deliberate: with no API key, or with the socket down, the
store is simply empty and the endpoint returns an empty collection. A live
socket is never a prerequisite for the map working.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

import websockets

from app.core.config import settings

logger = logging.getLogger(__name__)

AIS_STREAM_URL = "wss://stream.aisstream.io/v0/stream"

# Whole globe. aisstream requires an explicit bounding box; the viewport
# filter happens on our side at query time, so the subscription itself stays
# global rather than being re-negotiated every time the user pans.
_WORLD_BBOX = [[[-90.0, -180.0], [90.0, 180.0]]]

# A vessel disappears from the store this long after its last broadcast.
# AIS transmit intervals run from ~2s (fast-moving) to ~3min (at anchor),
# so this is generously past even a slow anchored vessel's cycle — long
# enough not to blink out mid-voyage, short enough that the map is not
# showing ghosts of ships that left hours ago.
STALE_AFTER_SECONDS = 30 * 60

# Hard ceiling on retained vessels, as a memory guard for an unbounded
# firehose. When exceeded, the oldest broadcasts are dropped first.
MAX_VESSELS = 60_000

_RECONNECT_MIN_SECONDS = 2
_RECONNECT_MAX_SECONDS = 60


class AisError(RuntimeError):
    pass


# --- AIS enumerations (ITU-R M.1371) --------------------------------------
# Codes are transmitted as bare integers; these render them as the words a
# user would expect to read in a vessel popup.

_NAV_STATUS = {
    0: "Under way using engine",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way sailing",
    11: "Towing astern",
    12: "Pushing ahead or towing alongside",
    14: "AIS-SART / MOB / EPIRB",
    15: "Undefined",
}

# Ship type is a 0-99 code where most meaning lives in the tens digit.
_SHIP_TYPE_EXACT = {
    30: "Fishing",
    31: "Towing",
    32: "Towing (large)",
    33: "Dredging or underwater ops",
    34: "Diving ops",
    35: "Military ops",
    36: "Sailing",
    37: "Pleasure craft",
    50: "Pilot vessel",
    51: "Search and rescue",
    52: "Tug",
    53: "Port tender",
    54: "Anti-pollution",
    55: "Law enforcement",
    58: "Medical transport",
    59: "Non-combatant",
}
_SHIP_TYPE_DECADE = {
    2: "Wing in ground",
    4: "High-speed craft",
    6: "Passenger",
    7: "Cargo",
    8: "Tanker",
    9: "Other",
}


def _nav_status_label(code: int | None) -> str | None:
    if code is None:
        return None
    return _NAV_STATUS.get(code, f"Unknown ({code})")


def _ship_type_label(code: int | None) -> str | None:
    if code is None or code == 0:
        return None
    if code in _SHIP_TYPE_EXACT:
        return _SHIP_TYPE_EXACT[code]
    decade = _SHIP_TYPE_DECADE.get(code // 10)
    return decade or f"Unknown ({code})"


# --- Vessel record ---------------------------------------------------------


@dataclass
class Vessel:
    """One vessel's latest known state, merged across message types.

    Every field except `mmsi` is optional: a vessel enters the store the
    moment its first position arrives, and fills in as more of its
    broadcasts land.
    """

    mmsi: int
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    # Speed over ground (knots) and course over ground (degrees true).
    sog: float | None = None
    cog: float | None = None
    # Heading is where the bow points, which differs from course when a
    # vessel is set by wind or current — kept separate rather than merged.
    heading: float | None = None
    nav_status: str | None = None
    # Static data, absent until a ShipStaticData message arrives.
    ship_type: str | None = None
    call_sign: str | None = None
    imo: int | None = None
    destination: str | None = None
    length_m: float | None = None
    beam_m: float | None = None
    draught_m: float | None = None
    eta: str | None = None
    # Monotonic clock, for staleness only — never serialised.
    last_seen: float = field(default_factory=time.monotonic)
    # Wall-clock ISO timestamp of the last broadcast, for display.
    last_report: str | None = None

    def as_feature(self) -> dict[str, Any]:
        """GeoJSON Feature. Null-valued properties are stripped so the client
        can treat "key absent" as "not broadcast" without also special-casing
        nulls."""
        properties = {
            "mmsi": self.mmsi,
            "name": self.name,
            "sog": self.sog,
            "cog": self.cog,
            "heading": self.heading,
            "nav_status": self.nav_status,
            "ship_type": self.ship_type,
            "call_sign": self.call_sign,
            "imo": self.imo,
            "destination": self.destination,
            "length_m": self.length_m,
            "beam_m": self.beam_m,
            "draught_m": self.draught_m,
            "eta": self.eta,
            "last_report": self.last_report,
        }
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.longitude, self.latitude]},
            "properties": {k: v for k, v in properties.items() if v is not None},
        }


# MMSI -> latest state. Mutated only from the ingest task and read from
# request handlers; both run on the same event loop and neither awaits
# mid-mutation, so no lock is needed.
_vessels: dict[int, Vessel] = {}

_task: asyncio.Task[None] | None = None
_connected = False
_messages_seen = 0


# --- Message parsing -------------------------------------------------------
# AIS reserves specific values to mean "not available". Passing those through
# would put a vessel at 102.3 knots on a course of 360 degrees, so each is
# mapped to None at the boundary rather than being sanitised later.


def _clean_sog(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    # 102.3 is the AIS "speed not available" sentinel.
    return None if value >= 102.3 else float(value)


def _clean_cog(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    # 360 means "not available"; anything above is malformed.
    return None if value >= 360 else float(value)


def _clean_heading(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    # 511 is the AIS "heading not available" sentinel.
    return None if value >= 511 else float(value)


def _clean_text(value: Any) -> str | None:
    """AIS pads text fields to fixed width with spaces and, on some
    transmitters, '@'. Both are padding, not content."""
    if not isinstance(value, str):
        return None
    cleaned = value.replace("@", " ").strip()
    return cleaned or None


def _clean_positive(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _format_eta(eta: Any) -> str | None:
    """AIS ETA is month/day/hour/minute with no year, and all-zero when not
    set. Rendered as a bare 'DD MMM HH:MM' rather than invented into a full
    date, since the year genuinely is not transmitted."""
    if not isinstance(eta, dict):
        return None
    month, day = eta.get("Month"), eta.get("Day")
    hour, minute = eta.get("Hour"), eta.get("Minute")
    if not month or not day:
        return None
    # Hour 24 / minute 60 are the "not available" sentinels.
    if not isinstance(hour, int) or hour > 23:
        hour = 0
    if not isinstance(minute, int) or minute > 59:
        minute = 0
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    if not (1 <= month <= 12):
        return None
    return f"{day:02d} {months[month - 1]} {hour:02d}:{minute:02d}"


def _vessel_for(mmsi: int) -> Vessel:
    vessel = _vessels.get(mmsi)
    if vessel is None:
        vessel = Vessel(mmsi=mmsi)
        _vessels[mmsi] = vessel
    return vessel


def _apply_message(payload: dict[str, Any]) -> None:
    message_type = payload.get("MessageType")
    metadata = payload.get("MetaData") or {}
    body = (payload.get("Message") or {}).get(message_type) or {}

    mmsi = metadata.get("MMSI")
    if not isinstance(mmsi, int):
        return

    vessel = _vessel_for(mmsi)
    vessel.last_seen = time.monotonic()
    if isinstance(metadata.get("time_utc"), str):
        vessel.last_report = metadata["time_utc"]

    # Present on both message types, so a vessel usually has a name from its
    # very first broadcast rather than only once static data arrives.
    name = _clean_text(metadata.get("ShipName"))
    if name:
        vessel.name = name

    if message_type == "PositionReport":
        lat, lon = body.get("Latitude"), body.get("Longitude")
        if _valid_position(lat, lon):
            vessel.latitude, vessel.longitude = float(lat), float(lon)
        vessel.sog = _clean_sog(body.get("Sog"))
        vessel.cog = _clean_cog(body.get("Cog"))
        vessel.heading = _clean_heading(body.get("TrueHeading"))
        status = body.get("NavigationalStatus")
        vessel.nav_status = _nav_status_label(status if isinstance(status, int) else None)

    elif message_type == "ShipStaticData":
        vessel.call_sign = _clean_text(body.get("CallSign"))
        vessel.destination = _clean_text(body.get("Destination"))
        vessel.ship_type = _ship_type_label(body.get("Type"))
        imo = body.get("ImoNumber")
        # 0 is "no IMO assigned", common on small craft.
        vessel.imo = imo if isinstance(imo, int) and imo > 0 else None
        vessel.draught_m = _clean_positive(body.get("MaximumStaticDraught"))
        vessel.eta = _format_eta(body.get("Eta"))
        # Dimensions are distances from the AIS antenna to bow/stern/port/
        # starboard, so the hull is A+B long and C+D wide.
        dims = body.get("Dimension") or {}
        length = (dims.get("A") or 0) + (dims.get("B") or 0)
        beam = (dims.get("C") or 0) + (dims.get("D") or 0)
        vessel.length_m = _clean_positive(length)
        vessel.beam_m = _clean_positive(beam)
        # A static-data broadcast carries no position of its own; fall back
        # to the metadata fix so a vessel first seen this way still maps.
        if vessel.latitude is None:
            lat, lon = metadata.get("latitude"), metadata.get("longitude")
            if _valid_position(lat, lon):
                vessel.latitude, vessel.longitude = float(lat), float(lon)


def _valid_position(lat: Any, lon: Any) -> bool:
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    if math.isnan(lat) or math.isnan(lon):
        return False
    # 91/181 are the AIS "position not available" sentinels; they also fall
    # outside these bounds, so one check covers both.
    return -90 <= lat <= 90 and -180 <= lon <= 180


# --- Store maintenance -----------------------------------------------------


def _evict_stale() -> None:
    cutoff = time.monotonic() - STALE_AFTER_SECONDS
    stale = [mmsi for mmsi, v in _vessels.items() if v.last_seen < cutoff]
    for mmsi in stale:
        del _vessels[mmsi]

    # Memory guard: if the feed is denser than expected, keep the most
    # recently heard vessels and drop the rest.
    overflow = len(_vessels) - MAX_VESSELS
    if overflow > 0:
        oldest = sorted(_vessels.items(), key=lambda kv: kv[1].last_seen)[:overflow]
        for mmsi, _ in oldest:
            del _vessels[mmsi]


# --- Ingest task -----------------------------------------------------------


async def _consume() -> None:
    """One websocket session: subscribe, then fold messages into the store
    until the connection drops."""
    global _connected, _messages_seen

    async with websockets.connect(AIS_STREAM_URL, ping_interval=20, ping_timeout=20) as socket:
        await socket.send(
            json.dumps(
                {
                    "APIKey": settings.AISSTREAM_API_KEY,
                    "BoundingBoxes": _WORLD_BBOX,
                    "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
                }
            )
        )
        _connected = True
        logger.info("AIS stream connected")

        last_evict = time.monotonic()
        async for raw in socket:
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue

            # aisstream reports a bad key or malformed subscription as a
            # normal message, not a socket error — without this the task
            # would reconnect-loop forever against a key that cannot work.
            if "error" in payload:
                raise AisError(str(payload["error"]))

            _apply_message(payload)
            _messages_seen += 1

            now = time.monotonic()
            if now - last_evict > 60:
                _evict_stale()
                last_evict = now


async def _run() -> None:
    """Supervises `_consume`, reconnecting with exponential backoff.

    An auth failure is fatal and stops the loop: retrying a rejected key
    just burns the connection quota and buries the real cause in log noise.
    """
    global _connected
    backoff = _RECONNECT_MIN_SECONDS

    while True:
        try:
            await _consume()
            backoff = _RECONNECT_MIN_SECONDS
        except asyncio.CancelledError:
            raise
        except AisError as exc:
            _connected = False
            logger.error("AIS stream rejected the subscription, not retrying: %s", exc)
            return
        except Exception as exc:  # noqa: BLE001 - any transport failure is retryable
            _connected = False
            logger.warning("AIS stream dropped (%s); reconnecting in %ss", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)
        else:
            _connected = False


def start() -> None:
    """Begins ingestion. A no-op without an API key, so the app starts
    normally in a checkout that has no aisstream credentials."""
    global _task
    if not settings.AISSTREAM_API_KEY:
        logger.info("AISSTREAM_API_KEY not set — live vessel layer will be empty")
        return
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_run())


async def stop() -> None:
    global _task, _connected
    if _task is None:
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None
    _connected = False


# --- Query -----------------------------------------------------------------


def vessels_in_bbox(
    west: float, south: float, east: float, north: float, limit: int
) -> dict[str, Any]:
    """GeoJSON FeatureCollection of currently-known vessels inside a bbox.

    Handles a viewport crossing the antimeridian, where west > east and the
    longitude test becomes a union of two ranges rather than one interval.
    When more vessels match than `limit`, the most recently heard win, so
    zooming out thins the picture rather than truncating it to one corner.
    """
    crosses_antimeridian = west > east

    matches = []
    for vessel in _vessels.values():
        lat, lon = vessel.latitude, vessel.longitude
        if lat is None or lon is None:
            continue
        if not (south <= lat <= north):
            continue
        if crosses_antimeridian:
            if not (lon >= west or lon <= east):
                continue
        elif not (west <= lon <= east):
            continue
        matches.append(vessel)

    total = len(matches)
    if total > limit:
        matches.sort(key=lambda v: v.last_seen, reverse=True)
        matches = matches[:limit]

    return {
        "type": "FeatureCollection",
        "features": [v.as_feature() for v in matches],
        # Lets the client say "showing 500 of 3,200 in view" rather than
        # implying the thinned set is everything there is.
        "total_in_view": total,
        "returned": len(matches),
        "connected": _connected,
    }


def status() -> dict[str, Any]:
    return {
        "connected": _connected,
        "configured": bool(settings.AISSTREAM_API_KEY),
        "tracked_vessels": len(_vessels),
        "messages_seen": _messages_seen,
    }
