"""NOAA NDBC real-time buoy observations.

The dashboard's live feed needs *observations* — something measured by an
instrument in the water minutes ago — to sit alongside the model fields the
rest of the platform serves. NDBC publishes one file holding the newest
report from every station it operates, which is exactly one HTTP request for
the whole global network rather than one per buoy.

Cached and refreshed on a schedule like `copernicus_sst.py`: the upstream file
is rewritten every few minutes, and a dashboard polling once a minute must not
turn into a poll of NOAA once a minute.

No credentials — the feed is public.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

LATEST_OBS_URL = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"
REALTIME_URL_TEMPLATE = "https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"

SOURCE_LABEL = "NOAA National Data Buoy Center"
SOURCE_URL = "https://www.ndbc.noaa.gov/"

_RAW_FEED_TIMEOUT = httpx.Timeout(10.0)
# Header rows plus a handful of the station's own most recent reports — this
# is provenance, not a chart, so a short excerpt proves the feed is real
# without turning the response into another observation cache.
_RAW_FEED_LINES = 15

# The feed is a fixed-width table whose every row carries all 22 columns,
# missing values included (as "MM"), so a plain split is safe and a short row
# means a malformed line rather than an absent field.
_EXPECTED_FIELDS = 22
_MISSING = "MM"

_TIMEOUT = httpx.Timeout(30.0)

# NDBC rewrites the file every ~10 minutes; individual stations report on
# their own cadence (hourly is common). Refreshing faster than this would
# re-download an identical file.
REFRESH_INTERVAL_MINUTES = 10

# A report older than this is stale enough that showing it as "live" would
# misrepresent it — buoys go offline for maintenance and keep their last row
# in the file. Six hours keeps hourly-reporting stations while dropping the
# genuinely dead ones.
_MAX_AGE_HOURS = 6


class NdbcError(RuntimeError):
    """NDBC feed unavailable or unparseable."""


@dataclass(frozen=True)
class BuoyObservation:
    station_id: str
    latitude: float
    longitude: float
    observed_at: datetime
    wind_direction_deg: float | None
    wind_speed_ms: float | None
    wind_gust_ms: float | None
    wave_height_m: float | None
    dominant_wave_period_s: float | None
    mean_wave_direction_deg: float | None
    pressure_hpa: float | None
    air_temperature_c: float | None
    water_temperature_c: float | None
    dewpoint_c: float | None
    visibility_nmi: float | None

    @property
    def relative_humidity_pct(self) -> float | None:
        """Derived from air temperature and dewpoint (Magnus).

        NDBC reports dewpoint, not RH, but the dashboard's live-feed card
        asks for humidity and the two are related by a closed form — this is
        a unit conversion, not an estimate.
        """
        if self.air_temperature_c is None or self.dewpoint_c is None:
            return None
        t, td = self.air_temperature_c, self.dewpoint_c
        numerator = math.exp((17.625 * td) / (243.04 + td))
        denominator = math.exp((17.625 * t) / (243.04 + t))
        if denominator == 0:
            return None
        return round(min(100.0, max(0.0, 100.0 * numerator / denominator)), 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "station_id": self.station_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "observed_at": self.observed_at.isoformat(),
            "wind_direction_deg": self.wind_direction_deg,
            "wind_speed_ms": self.wind_speed_ms,
            "wind_gust_ms": self.wind_gust_ms,
            "wave_height_m": self.wave_height_m,
            "dominant_wave_period_s": self.dominant_wave_period_s,
            "mean_wave_direction_deg": self.mean_wave_direction_deg,
            "pressure_hpa": self.pressure_hpa,
            "air_temperature_c": self.air_temperature_c,
            "water_temperature_c": self.water_temperature_c,
            "dewpoint_c": self.dewpoint_c,
            "relative_humidity_pct": self.relative_humidity_pct,
            "visibility_nmi": self.visibility_nmi,
        }


@dataclass
class _NdbcCache:
    observations: list[BuoyObservation]
    fetched_at: datetime
    latency_ms: float


_cache: _NdbcCache | None = None
_refresh_lock = asyncio.Lock()


def _number(token: str) -> float | None:
    if token == _MISSING:
        return None
    try:
        return float(token)
    except ValueError:
        return None


def _parse_row(line: str) -> BuoyObservation | None:
    fields = line.split()
    if len(fields) != _EXPECTED_FIELDS:
        return None

    latitude = _number(fields[1])
    longitude = _number(fields[2])
    if latitude is None or longitude is None:
        return None

    try:
        observed_at = datetime(
            int(fields[3]), int(fields[4]), int(fields[5]),
            int(fields[6]), int(fields[7]),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None

    return BuoyObservation(
        station_id=fields[0],
        latitude=latitude,
        longitude=longitude,
        observed_at=observed_at,
        wind_direction_deg=_number(fields[8]),
        wind_speed_ms=_number(fields[9]),
        wind_gust_ms=_number(fields[10]),
        wave_height_m=_number(fields[11]),
        dominant_wave_period_s=_number(fields[12]),
        mean_wave_direction_deg=_number(fields[14]),
        pressure_hpa=_number(fields[15]),
        air_temperature_c=_number(fields[17]),
        water_temperature_c=_number(fields[18]),
        dewpoint_c=_number(fields[19]),
        visibility_nmi=_number(fields[20]),
    )


def parse_latest_obs(text: str) -> list[BuoyObservation]:
    """Parse the feed body. Comment rows (`#`) carry the header and units."""
    observations = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        observation = _parse_row(line)
        if observation is not None:
            observations.append(observation)
    return observations


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=15))
def _fetch() -> tuple[list[BuoyObservation], float]:
    started = datetime.now(timezone.utc)
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        response = client.get(LATEST_OBS_URL)
        response.raise_for_status()
        text = response.text
    latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    observations = parse_latest_obs(text)
    if not observations:
        raise NdbcError("NDBC feed returned no parseable observations")
    return observations, latency_ms


async def refresh_cache() -> None:
    """Replace the cache. Keeps the previous one on any failure."""
    global _cache
    async with _refresh_lock:
        try:
            observations, latency_ms = await asyncio.to_thread(_fetch)
        except Exception:  # noqa: BLE001 - a bad fetch must not drop good data
            logger.opt(exception=True).warning("NDBC refresh failed, keeping previous cache if any")
            return

        _cache = _NdbcCache(
            observations=observations,
            fetched_at=datetime.now(timezone.utc),
            latency_ms=latency_ms,
        )
        logger.info(f"NDBC cache refreshed: {len(observations)} stations")


def _require_cache() -> _NdbcCache:
    if _cache is None:
        raise NdbcError("Buoy observations not yet available — initial fetch in progress or failed")
    return _cache


def is_refreshing() -> bool:
    """Whether a refresh is in flight right now.

    Reuses the existing refresh lock rather than tracking a second flag: the
    lock is held for exactly the duration of a fetch, so it already is the
    answer. Lets the dashboard tell "still warming up" apart from "failed",
    which are very different things to show a user.
    """
    return _refresh_lock.locked()


def is_available() -> bool:
    return _cache is not None


def health() -> dict[str, Any]:
    """Provider status for the dashboard's data-source panel."""
    if _cache is None:
        return {"connected": False, "latency_ms": None, "last_sync": None, "records": 0}
    return {
        "connected": True,
        "latency_ms": round(_cache.latency_ms),
        "last_sync": _cache.fetched_at.isoformat(),
        "records": len(_cache.observations),
    }


def _is_fresh(observation: BuoyObservation, now: datetime) -> bool:
    return (now - observation.observed_at).total_seconds() <= _MAX_AGE_HOURS * 3600


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def latest(
    limit: int = 8,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[dict[str, Any]]:
    """Freshest buoy reports, optionally the ones nearest a point.

    Stations reporting neither water temperature nor wave height are dropped:
    the live-feed card is built around those two, and a row of dashes is not
    an observation worth showing.
    """
    cache = _require_cache()
    now = datetime.now(timezone.utc)

    candidates = [
        observation
        for observation in cache.observations
        if _is_fresh(observation, now)
        and (observation.water_temperature_c is not None or observation.wave_height_m is not None)
    ]

    if latitude is not None and longitude is not None:
        ranked = sorted(
            candidates,
            key=lambda o: _haversine_km(latitude, longitude, o.latitude, o.longitude),
        )
        selected = ranked[:limit]
        return [
            {
                **observation.to_dict(),
                "distance_km": round(
                    _haversine_km(latitude, longitude, observation.latitude, observation.longitude), 1
                ),
            }
            for observation in selected
        ]

    ranked = sorted(candidates, key=lambda o: o.observed_at, reverse=True)
    return [observation.to_dict() for observation in ranked[:limit]]


def station(station_id: str) -> dict[str, Any]:
    """One station's latest observation, looked up by id.

    Same fields `latest()` already returns per row — there is no richer
    per-station record sitting unused, the list view already carries the full
    shape — just found by id rather than filtered/limited/distance-sorted.
    """
    cache = _require_cache()
    needle = station_id.strip().upper()
    for observation in cache.observations:
        if observation.station_id.upper() == needle:
            now = datetime.now(timezone.utc)
            return {**observation.to_dict(), "is_fresh": _is_fresh(observation, now)}
    raise NdbcError(f"No current observation for station {station_id}")


class _RawFeedNotPublished(Exception):
    """This station has no `realtime2` file — a 404, not a transient failure.

    Not every station in `latest_obs.txt` is NDBC's own: some rows relay a
    partner network's buoy, which never gets a `realtime2/<id>.txt` file at
    all. That is routine, not an outage, so it must not retry (a 404 will not
    become a 200) and must not read like one to whoever opens the page.
    """


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_not_exception_type(_RawFeedNotPublished),
)
def _fetch_raw_feed(url: str) -> str:
    with httpx.Client(timeout=_RAW_FEED_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
        if response.status_code == 404:
            raise _RawFeedNotPublished(url)
        response.raise_for_status()
        return response.text


async def raw_feed(station_id: str) -> dict[str, Any]:
    """A short excerpt of the station's own live text feed, fetched live.

    Proof this is a real instrument reporting real numbers, not a fixed demo
    value — `latest_obs.txt` alone gives a plausible-looking row, but nothing
    a user could independently check. NDBC also publishes this same station's
    recent reports as its own small text file; fetched on demand rather than
    cached, because a detail page is opened rarely enough that a live fetch
    of one ~2-15KB file, only when asked, is cheaper than a second resident
    cache nobody looks at most of the time.
    """
    url = REALTIME_URL_TEMPLATE.format(station_id=station_id.strip().upper())
    try:
        text = await asyncio.to_thread(_fetch_raw_feed, url)
    except _RawFeedNotPublished as exc:
        raise NdbcError(f"Station {station_id} does not publish a live feed file.") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced as a service error, not a raw traceback
        logger.warning(f"NDBC raw feed fetch failed for station {station_id}: {exc}")
        raise NdbcError(f"Could not fetch the live feed for station {station_id} right now.") from exc

    lines = [line for line in text.splitlines() if line.strip()]
    return {
        "url": url,
        "lines": lines[:_RAW_FEED_LINES],
        "total_lines": len(lines),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def meta() -> dict[str, Any]:
    cache = _require_cache()
    return {
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
        "fetched_at": cache.fetched_at.isoformat(),
        "station_count": len(cache.observations),
    }
