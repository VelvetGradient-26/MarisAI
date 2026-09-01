"""Copernicus Marine chlorophyll-a: cache + point lookup.

Built for one caller: `services/pfz.py` needs chlorophyll at a small grid of
candidate points inside one chat turn, and that only stays fast if the read
is a cached in-memory lookup rather than a network fetch per candidate — the
same reasoning `services/copernicus_sst.py` and `services/copernicus_currents.py`
already document.

**Global, not regional, and that is a deliberate deviation from the
"cheapest access pattern" rule elsewhere in this codebase.** The BGC-PFT
product is natively 0.25deg (681 x 1440 globally, -80..90 latitude, same
footprint as the currents cache) — a global `chl` timestep is under 4MB,
comparable to keeping the whole planet's SST resident. Regionally bounding
it would save nothing worth the extra code path.

Verified live 2026-08-22: `arco-geo-series` + a server-side depth bound
(surface only, out of 50 levels) fetches one global timestep of
`cmems_mod_glo_bgc-pft_anfc_0.25deg_P1D-m` in ~8.6s — the same "geo-series
for a global snapshot" pattern as SST, and the same depth-bounding rule
`machine_learning/` and the forecast grid builder both document (unbounded,
this is the 50-level product that turns a 60s fetch into tens of minutes).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from loguru import logger
from scipy.interpolate import RegularGridInterpolator
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

DATASET_ID = "cmems_mod_glo_bgc-pft_anfc_0.25deg_P1D-m"
VARIABLE = "chl"
DEPTH_M = 0.494
_DEPTH_MIN, _DEPTH_MAX = 0.49, 0.5
SOURCE_LABEL = "Copernicus Marine Service (GLOBAL_ANALYSISFORECAST_BGC_001_028)"

# Same "currently being updated" hazard `copernicus_wind.py` documents for its
# NRT product: walk back a few days rather than trusting the newest index
# entry is actually populated.
_MAX_LOOKBACK_DAYS = 5


class CopernicusChlorophyllError(RuntimeError):
    pass


@dataclass
class _ChlCache:
    interpolator: RegularGridInterpolator
    timestamp: datetime
    fetched_at: datetime


_cache: _ChlCache | None = None
_refresh_lock = asyncio.Lock()


def _build_interpolator(lat: np.ndarray, lon: np.ndarray, grid: np.ndarray) -> RegularGridInterpolator:
    lon_wrapped = np.append(lon, lon[0] + 360.0)
    grid_wrapped = np.concatenate([grid, grid[:, :1]], axis=1)
    return RegularGridInterpolator(
        (lat, lon_wrapped), grid_wrapped, method="linear", bounds_error=False, fill_value=np.nan
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _fetch_latest_grid() -> tuple[np.ndarray, np.ndarray, np.ndarray, datetime]:
    import copernicusmarine

    now = datetime.now(timezone.utc)
    ds = copernicusmarine.open_dataset(
        dataset_id=DATASET_ID,
        variables=[VARIABLE],
        minimum_depth=_DEPTH_MIN,
        maximum_depth=_DEPTH_MAX,
        username=settings.COPERNICUS_USERNAME,
        password=settings.COPERNICUS_PASSWORD,
        service="arco-geo-series",
    )
    try:
        past = ds.sel(time=slice(None, now.replace(tzinfo=None)))
        times = past.time.values

        for offset in range(_MAX_LOOKBACK_DAYS):
            if offset >= len(times):
                break
            da = past.chl.isel(time=-1 - offset, depth=0).load()
            if np.isfinite(da.values).any():
                timestamp = datetime.fromisoformat(str(da.time.values)[:19]).replace(tzinfo=timezone.utc)
                lat = da.latitude.values.astype(np.float64)
                lon = da.longitude.values.astype(np.float64)
                grid = da.values.astype(np.float32)
                return lat, lon, grid, timestamp

        raise CopernicusChlorophyllError(
            f"No populated chlorophyll timestep in the last {_MAX_LOOKBACK_DAYS} days"
        )
    finally:
        # See the matching comment in copernicus_sst.py — never left open.
        ds.close()


async def refresh_chlorophyll_cache() -> None:
    global _cache
    async with _refresh_lock:
        try:
            lat, lon, grid, timestamp = await asyncio.to_thread(_fetch_latest_grid)
            interpolator = _build_interpolator(lat, lon, grid)
        except Exception:  # noqa: BLE001 - keep stale cache on any failure
            logger.opt(exception=True).warning(
                "Chlorophyll refresh failed, keeping previous cache if any"
            )
            return

        _cache = _ChlCache(
            interpolator=interpolator,
            timestamp=timestamp,
            fetched_at=datetime.now(timezone.utc),
        )
        logger.info(f"Chlorophyll cache refreshed: timestep {timestamp.isoformat()}")


def _require_cache() -> _ChlCache:
    if _cache is None:
        raise CopernicusChlorophyllError(
            "Chlorophyll data not yet available — initial fetch still in progress or failed"
        )
    return _cache


def is_refreshing() -> bool:
    return _refresh_lock.locked()


def is_available() -> bool:
    return _cache is not None


def is_stale(max_age: timedelta = timedelta(hours=48)) -> bool:
    """Whether the cached timestep is old enough to caveat, not fail on.

    Daily products with normal publication lag routinely sit a day or two
    behind `fetched_at` — same "the lag is published, not folded into one
    timestamp" reasoning as `services/upwelling.py`. Callers (the PFZ tool)
    should say "as of <date>" rather than pretend it's live.
    """
    cache = _require_cache()
    return datetime.now(timezone.utc) - cache.timestamp > max_age


def get_point(latitude: float, longitude: float) -> dict[str, Any]:
    cache = _require_cache()
    value = float(cache.interpolator([[latitude, longitude]])[0])
    is_nan = np.isnan(value)
    return {
        "chlorophyll_mg_m3": None if is_nan else round(value, 4),
        "is_land_or_no_data": bool(is_nan),
        "timestamp": cache.timestamp.isoformat(),
        "source": SOURCE_LABEL,
        "depth_m": DEPTH_M,
    }
