"""Historical time series for the dashboard's analytics charts.

Most point series come from Open-Meteo: its marine model and the ERA5 archive
are both free, fast enough to sit behind an interactive chart, and cover the
ranges the dashboard offers.

**Coverage differs sharply by variable and is not negotiable.** Probing the
live API established that the marine model carries waves and currents from
about 2022, sea level from 2023 and SST only from 2024, while the ERA5
archive reaches back to 1940. So a variable declares its own `coverage_start`
and the API refuses (rather than silently truncates) a range it cannot serve
— the same contract `services/download/catalog.py` uses for provider
coverage, and the reason the UI can offer "10 years" on wind but not on SST.

Chlorophyll, salinity and ocean heat content come from Copernicus instead,
through `copernicus_series` — slower (8-13s uncached) but real. They are daily
means, so the hourly ranges are not offered for them.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

import httpx

from services.dashboard import copernicus_series

MARINE_API_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"

SOURCE_LABEL = "Open-Meteo (marine model / ERA5 reanalysis)"
SOURCE_URL = "https://open-meteo.com/"

_TIMEOUT = httpx.Timeout(45.0)

# Open-Meteo's free tier rate-limits, and this dashboard mounts up to ten
# charts that each fire on view plus again on every range change. Caching the
# responses keeps a normal session well inside the allowance and makes range
# switching instant; without it, heavy use returns 429 and blanks the grid.
_RESPONSE_TTL = timedelta(minutes=10)
_RESPONSE_CACHE_MAX = 128

_response_cache: dict[tuple, tuple[datetime, dict[str, Any]]] = {}
_response_lock = threading.Lock()

Resolution = Literal["hourly", "daily"]


def _cached_response(key: tuple) -> dict[str, Any] | None:
    with _response_lock:
        entry = _response_cache.get(key)
        if entry is None:
            return None
        stored_at, payload = entry
        if datetime.now(timezone.utc) - stored_at > _RESPONSE_TTL:
            _response_cache.pop(key, None)
            return None
        return payload


def _store_response(key: tuple, payload: dict[str, Any]) -> None:
    with _response_lock:
        _response_cache[key] = (datetime.now(timezone.utc), payload)
        if len(_response_cache) > _RESPONSE_CACHE_MAX:
            oldest = min(_response_cache, key=lambda k: _response_cache[k][0])
            _response_cache.pop(oldest, None)


class TrendsError(RuntimeError):
    """A trend series could not be produced."""


@dataclass(frozen=True)
class TrendSpec:
    key: str
    label: str
    unit: str
    # Which upstream answers for this field: two Open-Meteo models, or the
    # Copernicus zarr stores via `copernicus_series`.
    api: Literal["marine", "archive", "copernicus"]
    hourly_param: str | None
    daily_param: str | None
    coverage_start: date | None
    available: bool = True
    unavailable_reason: str | None = None
    # Charts where the peak matters more than the average (waves, wind) are
    # aggregated as a daily maximum; the rest as a daily mean.
    daily_aggregate: Literal["mean", "max"] = "mean"


_MARINE_START_WAVES = date(2022, 1, 1)
_MARINE_START_SEALEVEL = date(2023, 1, 1)
_MARINE_START_SST = date(2024, 1, 1)
# ERA5 via Open-Meteo's archive endpoint.
_ARCHIVE_START = date(1940, 1, 1)


TRENDS: dict[str, TrendSpec] = {
    spec.key: spec
    for spec in (
        TrendSpec(
            key="sea_surface_temperature",
            label="Sea Surface Temperature",
            unit="°C",
            api="marine",
            hourly_param="sea_surface_temperature",
            daily_param="sea_surface_temperature_mean",
            coverage_start=_MARINE_START_SST,
        ),
        TrendSpec(
            key="wave_height",
            label="Wave Height",
            unit="m",
            api="marine",
            hourly_param="wave_height",
            daily_param="wave_height_max",
            coverage_start=_MARINE_START_WAVES,
            daily_aggregate="max",
        ),
        TrendSpec(
            key="ocean_current_velocity",
            label="Current Velocity",
            unit="km/h",
            api="marine",
            hourly_param="ocean_current_velocity",
            daily_param=None,
            coverage_start=_MARINE_START_WAVES,
        ),
        TrendSpec(
            key="sea_level_height_msl",
            label="Sea Level (MSL)",
            unit="m",
            api="marine",
            hourly_param="sea_level_height_msl",
            daily_param=None,
            coverage_start=_MARINE_START_SEALEVEL,
        ),
        TrendSpec(
            key="wind_speed_10m",
            label="Wind Speed",
            unit="km/h",
            api="archive",
            hourly_param="wind_speed_10m",
            daily_param="wind_speed_10m_max",
            coverage_start=_ARCHIVE_START,
            daily_aggregate="max",
        ),
        TrendSpec(
            key="air_temperature",
            label="Air Temperature",
            unit="°C",
            api="archive",
            hourly_param="temperature_2m",
            daily_param="temperature_2m_mean",
            coverage_start=_ARCHIVE_START,
        ),
        TrendSpec(
            key="surface_pressure",
            label="Surface Pressure",
            unit="hPa",
            api="archive",
            hourly_param="pressure_msl",
            daily_param="pressure_msl_mean",
            coverage_start=_ARCHIVE_START,
        ),
        # --- Copernicus-backed, daily only (see `copernicus_series`) --------
        # These were briefly declared unavailable on the assumption that no
        # point source was fast enough. Measuring proved otherwise: a 1-year
        # daily series costs 8-13s, which a cache makes perfectly usable.
        TrendSpec(
            key="chlorophyll_a",
            label="Chlorophyll-a",
            unit="mg/m³",
            api="copernicus",
            hourly_param=None,
            daily_param="chl",
            coverage_start=copernicus_series.SERIES["chlorophyll_a"].coverage_start,
        ),
        TrendSpec(
            key="sea_surface_salinity",
            label="Sea Surface Salinity",
            unit="PSU",
            api="copernicus",
            hourly_param=None,
            daily_param="so",
            coverage_start=copernicus_series.SERIES["sea_surface_salinity"].coverage_start,
        ),
        TrendSpec(
            key="ocean_heat_content",
            label="Ocean Heat Content",
            unit="GJ/m²",
            api="copernicus",
            hourly_param=None,
            daily_param="thetao",
            coverage_start=copernicus_series.SERIES["ocean_heat_content"].coverage_start,
        ),
    )
}


# The ranges the UI offers, with the resolution each is served at. Hourly
# beyond a month would be tens of thousands of points for a chart a few
# hundred pixels wide.
RANGES: dict[str, dict[str, Any]] = {
    "24h": {"label": "24 Hours", "days": 1, "resolution": "hourly"},
    "7d": {"label": "7 Days", "days": 7, "resolution": "hourly"},
    "30d": {"label": "30 Days", "days": 30, "resolution": "daily"},
    "6mo": {"label": "6 Months", "days": 182, "resolution": "daily"},
    "1y": {"label": "1 Year", "days": 365, "resolution": "daily"},
    "5y": {"label": "5 Years", "days": 1826, "resolution": "daily"},
    "10y": {"label": "10 Years", "days": 3652, "resolution": "daily"},
}


def _serves_range(spec: TrendSpec, range_key: str, start: date) -> bool:
    if spec.coverage_start is None or start < spec.coverage_start:
        return False
    # The Copernicus products here are daily means, so an hourly range would
    # plot one or two points and call it a chart.
    if spec.api == "copernicus" and RANGES[range_key]["resolution"] == "hourly":
        return range_key != "24h"
    return True


def catalog() -> list[dict[str, Any]]:
    """What can be charted, over what span — drives the chart UI's controls."""
    today = datetime.now(timezone.utc).date()
    entries = []
    for spec in TRENDS.values():
        supported = []
        if spec.available and spec.coverage_start is not None:
            for key, window in RANGES.items():
                start = today - timedelta(days=window["days"])
                if _serves_range(spec, key, start):
                    supported.append(key)
        entries.append(
            {
                "key": spec.key,
                "label": spec.label,
                "unit": spec.unit,
                "available": spec.available,
                "unavailable_reason": spec.unavailable_reason,
                "coverage_start": spec.coverage_start.isoformat()
                if spec.coverage_start
                else None,
                "supported_ranges": supported,
            }
        )
    return entries


def _resolve_window(range_key: str, spec: TrendSpec) -> tuple[date, date, Resolution]:
    window = RANGES.get(range_key)
    if window is None:
        raise TrendsError(
            f"Unknown range {range_key!r}. Expected one of: {', '.join(RANGES)}"
        )

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=window["days"])

    if spec.coverage_start is not None and start < spec.coverage_start:
        raise TrendsError(
            f"{spec.label} only goes back to {spec.coverage_start.isoformat()}; "
            f"the {window['label']} range starts {start.isoformat()}."
        )
    if not _serves_range(spec, range_key, start):
        raise TrendsError(
            f"{spec.label} is a daily product; the {window['label']} range is "
            f"too short to plot from it."
        )
    return start, today, window["resolution"]


def _endpoint(spec: TrendSpec, start: date) -> str:
    if spec.api == "marine":
        return MARINE_API_URL
    # The archive endpoint carries ERA5 but lags ~5 days; the forecast
    # endpoint covers the recent window the archive has not caught up to.
    recent_cutoff = datetime.now(timezone.utc).date() - timedelta(days=10)
    return FORECAST_API_URL if start >= recent_cutoff else ARCHIVE_API_URL


async def _copernicus_series(
    spec: TrendSpec,
    latitude: float,
    longitude: float,
    range_key: str,
    start: date,
    end: date,
) -> dict[str, Any]:
    """Chart payload for a Copernicus-backed variable.

    Always daily: these are daily-mean products, and `_serves_range` already
    refuses the ranges too short to plot from them.
    """
    try:
        points = await copernicus_series.series(spec.key, latitude, longitude, start, end)
    except copernicus_series.CopernicusSeriesError as exc:
        raise TrendsError(str(exc)) from exc

    detail = "surface"
    if spec.key == "ocean_heat_content":
        detail = f"integrated 0-{copernicus_series.OHC_REFERENCE_DEPTH_M:.0f} m"

    return {
        "variable": spec.key,
        "label": spec.label,
        "unit": spec.unit,
        "range": range_key,
        "resolution": "daily",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "latitude": latitude,
        "longitude": longitude,
        "points": points,
        "statistics": _statistics(points),
        "source": f"{copernicus_series.SOURCE_LABEL} — {spec.daily_param} ({detail})",
        "source_url": copernicus_series.SOURCE_URL,
    }


async def series(
    variable: str,
    latitude: float,
    longitude: float,
    range_key: str = "7d",
) -> dict[str, Any]:
    """One variable's series at a point over a named range."""
    spec = TRENDS.get(variable)
    if spec is None:
        raise TrendsError(
            f"Unknown variable {variable!r}. Expected one of: {', '.join(TRENDS)}"
        )
    if not spec.available:
        raise TrendsError(spec.unavailable_reason or f"{spec.label} is not available")

    start, end, resolution = _resolve_window(range_key, spec)

    if spec.api == "copernicus":
        return await _copernicus_series(spec, latitude, longitude, range_key, start, end)

    parameter = spec.hourly_param if resolution == "hourly" else spec.daily_param
    # Currents and sea level have no daily aggregate upstream; request hourly
    # and reduce here rather than dropping the range.
    reduce_locally = False
    if parameter is None:
        parameter = spec.hourly_param
        reduce_locally = resolution == "daily"
        if parameter is None:
            raise TrendsError(f"{spec.label} has no series parameter configured")

    upstream_resolution: Resolution = "hourly" if reduce_locally else resolution
    params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "UTC",
        upstream_resolution: parameter,
    }

    url = _endpoint(spec, start)
    cache_key = (url, tuple(sorted(params.items())))

    payload = _cached_response(cache_key)
    if payload is None:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            # 429 is the one users will actually hit, and "upstream request
            # failed (Client error '429 Too Many Requests')" tells them
            # nothing about what to do.
            if exc.response.status_code == 429:
                raise TrendsError(
                    f"{spec.label}: the weather data provider is rate-limiting "
                    f"requests right now. This clears on its own — retry in a minute."
                ) from exc
            raise TrendsError(f"{spec.label}: upstream request failed ({exc})") from exc
        except httpx.HTTPError as exc:
            raise TrendsError(f"{spec.label}: upstream request failed ({exc})") from exc

        _store_response(cache_key, payload)

    if isinstance(payload, dict) and payload.get("error"):
        raise TrendsError(f"{spec.label}: {payload.get('reason', 'upstream error')}")

    block = payload.get(upstream_resolution) or {}
    times = block.get("time") or []
    values = block.get(parameter) or []

    points = [
        {"t": time, "v": value}
        for time, value in zip(times, values)
        if value is not None
    ]

    if reduce_locally:
        points = _to_daily(points, spec.daily_aggregate)

    return {
        "variable": spec.key,
        "label": spec.label,
        "unit": spec.unit,
        "range": range_key,
        "resolution": resolution,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "latitude": payload.get("latitude", latitude),
        "longitude": payload.get("longitude", longitude),
        "points": points,
        "statistics": _statistics(points),
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
    }


def _to_daily(points: list[dict[str, Any]], aggregate: str) -> list[dict[str, Any]]:
    """Collapse hourly points to one per day."""
    buckets: dict[str, list[float]] = {}
    for point in points:
        day = str(point["t"])[:10]
        buckets.setdefault(day, []).append(float(point["v"]))

    reduced = []
    for day in sorted(buckets):
        values = buckets[day]
        value = max(values) if aggregate == "max" else sum(values) / len(values)
        reduced.append({"t": day, "v": round(value, 4)})
    return reduced


def _statistics(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Summary the chart header shows, plus the change across the window."""
    if not points:
        return None
    values = [float(point["v"]) for point in points]
    first, last = values[0], values[-1]
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(sum(values) / len(values), 4),
        "first": round(first, 4),
        "last": round(last, 4),
        "change": round(last - first, 4),
        "change_pct": round((last - first) / abs(first) * 100, 2) if first else None,
    }


async def multi_series(
    variables: list[str],
    latitude: float,
    longitude: float,
    range_key: str = "7d",
) -> dict[str, Any]:
    """Several variables at once, so the chart grid is one round trip.

    A variable that fails takes its own slot down with an error string and
    leaves the others intact — one unavailable chart should not blank the grid.
    """
    async def one(variable: str) -> tuple[str, Any]:
        try:
            return variable, await series(variable, latitude, longitude, range_key)
        except TrendsError as exc:
            return variable, {"variable": variable, "error": str(exc), "points": []}

    results = await asyncio.gather(*(one(variable) for variable in variables))
    return {
        "range": range_key,
        "latitude": latitude,
        "longitude": longitude,
        "series": dict(results),
    }
