"""Point time series from Copernicus Marine, for the charts Open-Meteo cannot serve.

Chlorophyll, salinity and ocean heat content have no fast public point API, so
this module goes to the Copernicus zarr stores directly. It exists because the
alternative was declaring three charts permanently unavailable — which was the
wrong call: a measured 1-year daily series costs 8-13s here, slow for a chart
but perfectly workable behind a cache.

Two things make that cost bearable:

  * **`arco-time-series`, not `arco-geo-series`.** This is the "one bounded
    area, many timesteps" access pattern, which is exactly what that service
    is chunked for (see CLAUDE.md). Using the geo-series store here would be
    the same mistake in reverse as using time-series for a global snapshot.
  * **A process-local cache with a TTL.** Panning back and forth between
    ranges, or two people looking at the same place, must not re-pay 13s.

Ocean heat content is *derived*, not fetched: OHC = rho * cp * integral(T dz)
over the top 700m, the standard reference depth for upper-ocean heat content.
No provider publishes it, which is why it was previously declared impossible.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Literal

import numpy as np
from loguru import logger

from app.core.config import settings
from services.download.providers.copernicus import (
    BGC_PFT_DATASET_ID,
    SO_DEPTH_DATASET_ID,
    THETAO_DEPTH_DATASET_ID,
)

SOURCE_LABEL = "Copernicus Marine Service"
SOURCE_URL = "https://marine.copernicus.eu/"

# Seawater constants for the heat-content integral. Reference values for the
# upper ocean; OHC is conventionally quoted against 0 degrees C, which is what
# integrating raw Celsius temperatures gives.
_SEAWATER_DENSITY = 1025.0      # kg/m^3
_SEAWATER_HEAT_CAPACITY = 3985.0  # J/(kg*K)

# The standard reference depth for "upper ocean heat content".
OHC_REFERENCE_DEPTH_M = 700.0

# A degree of padding around the requested point. The grid is 0.083deg
# (physics) or 0.25deg (BGC), so a window this size always contains at least
# one cell without pulling a meaningful amount of extra data.
_POINT_PAD_DEG = 0.15

# How long a fetched series stays usable. These are daily products; within an
# hour the answer cannot have changed.
_CACHE_TTL = timedelta(hours=1)

# Requests are keyed on coordinates rounded to this many decimals, so tiny
# cursor differences share one cached series rather than each costing 13s.
_KEY_DECIMALS = 2


class CopernicusSeriesError(RuntimeError):
    """A Copernicus point series could not be produced."""


@dataclass(frozen=True)
class SeriesSpec:
    """One chartable Copernicus variable."""

    key: str
    dataset_id: str
    variables: tuple[str, ...]
    unit: str
    coverage_start: date
    # Surface fields take the shallowest level; `ohc` integrates over depth.
    mode: Literal["surface", "ohc"] = "surface"
    maximum_depth: float | None = 1.0
    decimals: int = 4


SERIES: dict[str, SeriesSpec] = {
    spec.key: spec
    for spec in (
        SeriesSpec(
            key="chlorophyll_a",
            dataset_id=BGC_PFT_DATASET_ID,
            variables=("chl",),
            unit="mg/m³",
            # The BGC analysis-forecast suite starts here.
            coverage_start=date(2021, 11, 1),
        ),
        SeriesSpec(
            key="sea_surface_salinity",
            # The *daily* depth-resolved salinity product. The hourly physics
            # dataset also carries `so`, but an hourly fetch across a year is
            # 8,760 steps to draw 365 points.
            dataset_id=SO_DEPTH_DATASET_ID,
            variables=("so",),
            unit="PSU",
            coverage_start=date(2022, 6, 1),
            decimals=3,
        ),
        SeriesSpec(
            key="ocean_heat_content",
            dataset_id=THETAO_DEPTH_DATASET_ID,
            variables=("thetao",),
            unit="GJ/m²",
            coverage_start=date(2022, 6, 1),
            mode="ohc",
            maximum_depth=OHC_REFERENCE_DEPTH_M,
            decimals=2,
        ),
    )
}


@dataclass
class _Entry:
    points: list[dict[str, Any]]
    stored_at: datetime


_cache: dict[tuple, _Entry] = {}
_lock = threading.Lock()

# One Copernicus fetch at a time. Ten charts mounting together would otherwise
# open ten concurrent zarr sessions and make every one of them slower.
_fetch_semaphore = asyncio.Semaphore(2)


def _cache_key(spec: SeriesSpec, latitude: float, longitude: float, start: date, end: date) -> tuple:
    return (
        spec.key,
        round(latitude, _KEY_DECIMALS),
        round(longitude, _KEY_DECIMALS),
        start.isoformat(),
        end.isoformat(),
    )


def _cached(key: tuple) -> list[dict[str, Any]] | None:
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if datetime.now(timezone.utc) - entry.stored_at > _CACHE_TTL:
            _cache.pop(key, None)
            return None
        return entry.points


def _store(key: tuple, points: list[dict[str, Any]]) -> None:
    with _lock:
        _cache[key] = _Entry(points=points, stored_at=datetime.now(timezone.utc))
        # Unbounded growth would be a slow leak across many locations; this is
        # a display cache, so evicting the oldest is fine.
        if len(_cache) > 64:
            oldest = min(_cache, key=lambda k: _cache[k].stored_at)
            _cache.pop(oldest, None)


def _integrate_heat_content(
    temperatures: np.ndarray, depths: np.ndarray
) -> float | None:
    """OHC in GJ/m² from a temperature profile.

    Trapezoidal integration over the model's own (unevenly spaced) levels.
    Levels below the seafloor are NaN, so the integral runs over the valid
    part of the column and returns None if that is too thin to be meaningful.
    """
    valid = np.isfinite(temperatures)
    if valid.sum() < 2:
        return None

    profile = temperatures[valid]
    levels = depths[valid]
    joules = _SEAWATER_DENSITY * _SEAWATER_HEAT_CAPACITY * np.trapezoid(profile, levels)
    return float(joules / 1e9)


def _load_series(
    spec: SeriesSpec, latitude: float, longitude: float, start: date, end: date
) -> list[dict[str, Any]]:
    import copernicusmarine

    kwargs: dict[str, Any] = {
        "dataset_id": spec.dataset_id,
        "variables": list(spec.variables),
        "minimum_longitude": longitude - _POINT_PAD_DEG,
        "maximum_longitude": longitude + _POINT_PAD_DEG,
        "minimum_latitude": latitude - _POINT_PAD_DEG,
        "maximum_latitude": latitude + _POINT_PAD_DEG,
        "start_datetime": start.isoformat(),
        "end_datetime": end.isoformat(),
        "username": settings.COPERNICUS_USERNAME,
        "password": settings.COPERNICUS_PASSWORD,
        # One place, many timesteps — the time-series chunking.
        "service": "arco-time-series",
    }
    if spec.maximum_depth is not None:
        kwargs["maximum_depth"] = spec.maximum_depth

    dataset = copernicusmarine.open_dataset(**kwargs)
    field = dataset[spec.variables[0]]

    # Nearest grid cell to the requested point, rather than the corner of the
    # padded window.
    field = field.sel(latitude=latitude, longitude=longitude, method="nearest")

    times = [str(value)[:10] for value in np.atleast_1d(field.time.values)]

    if spec.mode == "ohc":
        depths = np.asarray(dataset.depth.values, dtype=float)
        values_2d = np.atleast_2d(field.load().values)
        # Guard the axis order: a single-timestep request can come back
        # transposed relative to the many-timestep case.
        if values_2d.shape[0] != len(times) and values_2d.shape[-1] == len(times):
            values_2d = values_2d.T
        series = [_integrate_heat_content(row, depths) for row in values_2d]
    else:
        if "depth" in field.dims:
            field = field.isel(depth=0)
        series = [
            float(value) if np.isfinite(value) else None
            for value in np.atleast_1d(field.load().values)
        ]

    points = [
        {"t": time, "v": round(value, spec.decimals)}
        for time, value in zip(times, series)
        if value is not None and np.isfinite(value)
    ]
    if not points:
        raise CopernicusSeriesError(
            "The model has no valid values at this location — it may be land, "
            "or below the seafloor for the requested depth range."
        )
    return points


async def series(
    variable: str, latitude: float, longitude: float, start: date, end: date
) -> list[dict[str, Any]]:
    """Daily points for one variable at one point, cached."""
    spec = SERIES.get(variable)
    if spec is None:
        raise CopernicusSeriesError(f"Unknown Copernicus series {variable!r}")

    if start < spec.coverage_start:
        raise CopernicusSeriesError(
            f"{variable} only goes back to {spec.coverage_start.isoformat()}"
        )

    key = _cache_key(spec, latitude, longitude, start, end)
    hit = _cached(key)
    if hit is not None:
        return hit

    async with _fetch_semaphore:
        # Re-check: a concurrent request for the same key may have filled the
        # cache while this one waited for the semaphore.
        hit = _cached(key)
        if hit is not None:
            return hit

        try:
            points = await asyncio.to_thread(
                _load_series, spec, latitude, longitude, start, end
            )
        except CopernicusSeriesError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as a clean error
            logger.opt(exception=True).warning(f"Copernicus series {variable} failed")
            raise CopernicusSeriesError(
                f"Copernicus did not return a series for {variable}: {exc}"
            ) from exc

    _store(key, points)
    return points
