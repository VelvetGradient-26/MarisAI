"""Active tropical cyclone tracking, from GDACS.

PS2's own example queries name "any lightning or cyclone alerts in my area",
and nothing in the platform answered the cyclone half before this — the
threshold rules in `services/dashboard/alerts.py` run over SST/wave/bloom
fields, and there is no cyclone-track source anywhere else in the codebase.

**IMD does not publish a machine-readable cyclone-track feed.** Its CAP alert
feed (`services/severe_weather.py`) is real and live, but verified 2026-08-24
against five major cyclone landfalls (Biparjoy, Michaung, Tauktae, Remal,
Dana) it reports every one of them only as a rainfall/heat event — never as a
tracked storm with a position, category or forecast cone. RSMC New Delhi
(`rsmcnewdelhi.imd.gov.in`), the actual issuing authority for North Indian
Ocean cyclone bulletins, publishes PDF bulletins only.

**GDACS (Global Disaster Alert and Coordination System) is the fallback TODO.md
named, and it is a genuinely good one**: `gdacs.org/gdacsapi` is free, needs no
key, and aggregates JTWC's (and other RSMCs') tropical cyclone warnings into a
single global GeoJSON feed, refreshed on the warning centre's own bulletin
cadence. Verified live against `country=India` history: it correctly carries
Biparjoy-23, Michaung-23, Remal-24, Dana-24, Fengal-24, Montha-25 and others,
each sourced from JTWC.

**The `eventtypes=TC` query parameter does not reliably filter server-side**
— measured 2026-08-24, a request with `eventtypes=TC` still returned floods,
earthquakes, droughts, volcanoes and wildfires alongside cyclones. Every
caller here filters on `properties.eventtype == "TC"` itself rather than
trusting the query string.

**This is proximity to the storm's last reported position, not an
intersection with its forecast track or wind-radius cone — verified live
2026-08-28 that this is a latency blocker, not merely "more calls than one
per check" as originally assumed.** GDACS's own event detail
(`geteventdata`) does link to real per-storm geometry resources — confirmed
against the then-active SAUDEL-26 (`eventid=1001305`,
`https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype=TC&eventid=1001305&episodeid=39`,
which returned in ~30-40s): `properties.url.geometry` points at
`api/polygons/getgeometry?eventtype=TC&eventid=...&episodeid=...`, and
`properties.impacts[].resource` links `buffer74`/`buffer39` wind-speed-buffer
exports and a `getepisodedata` call per historical episode. **All three of
those sub-resource endpoints failed to respond at all within 120 seconds**,
tried directly (`curl`, not this module's own client) — while
`geteventlist`/`geteventdata` themselves reliably return, just slowly
(~20-40s). A per-storm fetch at that latency cannot go in a live request
path at all — this is not "one call per storm is more expensive than one
call per check", it is "one call per storm may never return" — so a keyless
account is not what blocks this, unlike WDPA/AVISO+.

The path that would actually work is the one `services/forecast_warm.py` and
`services/eddy_tracking.py` already establish for a slow upstream: fetch on a
schedule, into a cache, decoupled from any request — periodically resolve
`getgeometry` for every currently-`iscurrent` storm (rarely more than a
handful) and cache whatever comes back, with `check_point` reading that cache
opportunistically and falling back to today's circle for a storm with no
cached polygon yet (or a fetch that never completed). Not built here because
the response shape was never actually seen — every attempt to fetch it
timed out — and parsing a shape no one has actually observed would be
guessing at a wire format, the opposite of how every other provider
integration in this codebase was verified.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GDACS_EVENTLIST_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
_TIMEOUT = httpx.Timeout(20.0)

EARTH_RADIUS_KM = 6371.0088

# A coarse "worth mentioning" radius. Large tropical cyclones' gale-force
# (34kt) wind field routinely extends 300-400km from the centre; this errs
# wide because the alternative — a tight radius that misses an approaching
# storm — is the more dangerous failure for a "should I go out" question.
DEFAULT_WATCH_RADIUS_KM = 500.0


class CycloneError(RuntimeError):
    """GDACS could not be reached, or answered with something unusable."""


@dataclass
class _Entry:
    payload: dict[str, Any]
    stored_at: datetime


# One key ("active"), since this is a single global list rather than a
# per-point query — same shape as `services/dashboard`'s single-value caches,
# simpler than `services/edna.py`'s per-parameter cache since there is only
# one thing to cache here.
_CACHE_TTL = timedelta(minutes=15)
_cache: dict[str, _Entry] = {}
_lock = threading.Lock()


def _cached(key: str) -> dict[str, Any] | None:
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if datetime.now(timezone.utc) - entry.stored_at > _CACHE_TTL:
            _cache.pop(key, None)
            return None
        return entry.payload


def _store(key: str, payload: dict[str, Any]) -> None:
    with _lock:
        _cache[key] = _Entry(payload=payload, stored_at=datetime.now(timezone.utc))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


async def _get(client: httpx.AsyncClient, params: dict[str, Any]) -> Any:
    response = await client.get(GDACS_EVENTLIST_URL, params=params)
    response.raise_for_status()
    return response.json()


def _clean_name(raw: str) -> str:
    """"MICHAUNG-23" -> "Michaung" — GDACS suffixes every name with a 2-digit
    year to disambiguate storms across seasons; a chat answer doesn't need it
    and title-casing an all-caps name reads as a name rather than a shout."""
    base = raw.rsplit("-", 1)[0] if len(raw) > 3 and raw[-3] == "-" else raw
    return base.title() if base else "Unnamed system"


def _storm_summary(feature: dict[str, Any]) -> dict[str, Any] | None:
    props = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    severity = props.get("severitydata") or {}
    countries = [
        entry.get("countryname")
        for entry in props.get("affectedcountries") or []
        if entry.get("countryname")
    ]
    return {
        "name": _clean_name(props.get("eventname") or props.get("name") or ""),
        "latitude": coordinates[1],
        "longitude": coordinates[0],
        "alert_level": props.get("alertlevel"),
        "max_wind_kmh": severity.get("severity"),
        "category": severity.get("severitytext"),
        "affected_countries": countries,
        "active_since": props.get("fromdate"),
        "forecast_until": props.get("todate"),
        "last_updated": props.get("datemodified"),
        "source": props.get("source") or "JTWC",
        "report_url": (props.get("url") or {}).get("report"),
    }


async def get_active_cyclones() -> dict[str, Any]:
    """Every tropical cyclone GDACS currently reports as active, worldwide.

    Not filtered to the North Indian Ocean — a fisherman asking this question
    could be anywhere the platform is used, and an empty Bay of Bengal is not
    the same claim as "there are no active cyclones anywhere right now".
    """
    cached = _cached("active")
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            data = await _get(client, {"eventtypes": "TC"})
    except httpx.HTTPStatusError as exc:
        raise CycloneError(
            f"GDACS returned {exc.response.status_code} for the active-cyclone list"
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning(f"GDACS cyclone list request failed: {exc}")
        raise CycloneError(f"GDACS could not be reached: {exc}") from exc

    cyclones: list[dict[str, Any]] = []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        if props.get("eventtype") != "TC":
            continue
        if str(props.get("iscurrent")).lower() != "true":
            continue
        summary = _storm_summary(feature)
        if summary is not None:
            cyclones.append(summary)

    payload = {
        "cyclones": cyclones,
        "count": len(cyclones),
        "source": (
            "GDACS (Global Disaster Alert and Coordination System), aggregating "
            "JTWC and national tropical cyclone warning centres"
        ),
        "note": (
            "Each position is the storm's most recently reported fix, not a "
            "live track — GDACS updates on the warning centre's own bulletin "
            "cadence (typically every 6h)."
        ),
    }
    _store("active", payload)
    return payload


async def check_point(
    latitude: float, longitude: float, radius_km: float = DEFAULT_WATCH_RADIUS_KM
) -> dict[str, Any]:
    """The nearest currently-active cyclone to a point, and a coarse proximity flag.

    Never raises for "no active cyclones" — that is a real, useful answer.
    Only a failed GDACS fetch raises `CycloneError`.
    """
    active = (await get_active_cyclones())["cyclones"]

    ranked: list[dict[str, Any]] = []
    for storm in active:
        distance_km = _haversine_km(latitude, longitude, storm["latitude"], storm["longitude"])
        ranked.append({**storm, "distance_km": round(distance_km, 1)})
    ranked.sort(key=lambda entry: entry["distance_km"])

    nearest = ranked[0] if ranked else None
    within_watch_radius = nearest is not None and nearest["distance_km"] <= radius_km

    return {
        "active_cyclones_worldwide": len(active),
        "nearest": nearest,
        "within_watch_radius": within_watch_radius,
        "watch_radius_km": radius_km,
        "note": (
            "Distance to the storm's last reported position only — not an "
            "intersection with its forecast track or wind-radius cone. A storm "
            "further than this radius can still be forecast to approach; treat "
            "this as a coarse screen, not a warning, and prefer an official "
            "bulletin before acting on it."
        ),
    }
