"""Copernicus Marine sea surface temperature: cache + point lookup + tile render.

Data flow: `refresh_sst_cache()` pulls one global timestep of `thetao`
(potential temperature) at ~0.494m depth from
`cmems_mod_glo_phy_anfc_0.083deg_PT1H-m` (the analysis-forecast product behind
`GLOBAL_ANALYSISFORECAST_PHY_001_024`) and holds it in memory as a plain numpy
grid (~35MB) — small enough that the whole globe is cached, so no per-tile
network fetch is needed. `render_tile`/`get_point` only ever read that cache.

Not falling back to NOAA GHRSST when Copernicus is unreachable (Phase 1 scope
decision) — a failed refresh just leaves the previous, still-real, correctly
timestamped cache in place. `CopernicusSstError` is only raised when no cache
has ever been populated at all.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import numpy as np
from loguru import logger
from PIL import Image
from scipy.interpolate import RegularGridInterpolator
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from services.colormaps import SST_COLORMAP

DATASET_ID = "cmems_mod_glo_phy_anfc_0.083deg_PT1H-m"
VARIABLE = "thetao"
DEPTH_M = 0.494
# The dataset's actual single depth level is 0.49402499198913574 — a padded
# range is needed because an exact-equal bound falls just short of it in
# floating point and copernicusmarine rejects a request with zero overlap.
_DEPTH_MIN, _DEPTH_MAX = 0.49, 0.5
SOURCE_LABEL = "Copernicus Marine Service (GLOBAL_ANALYSISFORECAST_PHY_001_024)"

TILE_SIZE = 256
_MIN_C, _MAX_C = -2.0, 35.0


class CopernicusSstError(RuntimeError):
    pass


@dataclass
class _SstCache:
    interpolator: RegularGridInterpolator
    timestamp: datetime


_cache: _SstCache | None = None
_refresh_lock = asyncio.Lock()


def _build_interpolator(lat: np.ndarray, lon: np.ndarray, grid: np.ndarray) -> RegularGridInterpolator:
    """Wraps the longitude axis (periodic) so sampling right at the
    antimeridian doesn't fall just outside the source grid's last column and
    render as a spurious no-data seam."""
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
        # Explicit, not a default: this dataset publishes two zarr services —
        # "arco-time-series" (fine lat/lon chunks, huge time chunks — built
        # for a single point across all time) and "arco-geo-series" (huge
        # lat/lon chunks, one timestep per chunk — built for exactly what we
        # need, a full global grid at one instant). open_dataset() silently
        # picked the point-optimized one by default; loading one global
        # timestep through it touched ~35k tiny-spatial/huge-time chunks and
        # took 10+ minutes. Forcing "arco-geo-series" here loads the same
        # single timestep in ~12s.
        service="arco-geo-series",
    )
    # Nearest timestep at/before now — never pick a forecast step and label it
    # as "current".
    past = ds.sel(time=slice(None, now.replace(tzinfo=None)))
    da = past.thetao.isel(time=-1, depth=0).load()

    timestamp = datetime.fromisoformat(str(da.time.values)[:19]).replace(tzinfo=timezone.utc)
    lat = da.latitude.values.astype(np.float64)
    lon = da.longitude.values.astype(np.float64)
    grid = da.values.astype(np.float64)
    return lat, lon, grid, timestamp


async def refresh_sst_cache() -> None:
    global _cache
    async with _refresh_lock:
        try:
            lat, lon, grid, timestamp = await asyncio.to_thread(_fetch_latest_grid)
        except Exception as exc:  # noqa: BLE001 - keep stale cache on any failure
            logger.warning(f"SST refresh failed, keeping previous cache if any: {exc}")
            return

        interpolator = _build_interpolator(lat, lon, grid)
        _cache = _SstCache(interpolator=interpolator, timestamp=timestamp)
        render_tile.cache_clear()
        logger.info(f"SST cache refreshed: timestep {timestamp.isoformat()}")


def _require_cache() -> _SstCache:
    if _cache is None:
        raise CopernicusSstError("SST data not yet available — initial fetch still in progress or failed")
    return _cache


def get_meta() -> dict[str, Any]:
    cache = _require_cache()
    return {
        "timestamp": cache.timestamp.isoformat(),
        "source": SOURCE_LABEL,
        "depth_m": DEPTH_M,
        "unit": "°C",
        "min": _MIN_C,
        "max": _MAX_C,
    }


def get_point(latitude: float, longitude: float) -> dict[str, Any]:
    cache = _require_cache()
    # RegularGridInterpolator's longitude axis runs [-180, 180] (see
    # _build_interpolator's wrap point) — queries are already in that range.
    value = float(cache.interpolator([[latitude, longitude]])[0])
    is_nan = np.isnan(value)
    return {
        "temperature_c": None if is_nan else round(value, 2),
        "is_land_or_no_data": bool(is_nan),
        "timestamp": cache.timestamp.isoformat(),
        "source": SOURCE_LABEL,
        "depth_m": DEPTH_M,
    }


def _tile_lonlat(z: int, x: int, y: int) -> tuple[np.ndarray, np.ndarray]:
    n = 2**z
    px = np.arange(TILE_SIZE, dtype=np.float64)
    lon = (x + (px + 0.5) / TILE_SIZE) / n * 360.0 - 180.0
    y_frac = (y + (px + 0.5) / TILE_SIZE) / n
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y_frac))))
    return lon, lat


@lru_cache(maxsize=2048)
def render_tile(z: int, x: int, y: int, timestamp_key: str) -> bytes:
    cache = _require_cache()
    lon, lat = _tile_lonlat(z, x, y)
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    points = np.stack([lat_grid.ravel(), lon_grid.ravel()], axis=-1)
    values = cache.interpolator(points).reshape(TILE_SIZE, TILE_SIZE)

    rgb = np.nan_to_num(SST_COLORMAP(values), nan=0.0).astype(np.uint8)
    alpha = np.where(np.isnan(values), 0, 255).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])

    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


_EMPTY_TILE = io.BytesIO()
Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(_EMPTY_TILE, format="PNG")
_EMPTY_TILE_BYTES = _EMPTY_TILE.getvalue()


def render_tile_or_placeholder(z: int, x: int, y: int) -> bytes:
    """Router-facing entry point: never raises, so a not-yet-loaded cache or
    render error shows as an empty tile rather than a broken map."""
    if _cache is None:
        return _EMPTY_TILE_BYTES
    try:
        return render_tile(z, x, y, _cache.timestamp.isoformat())
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"SST tile render failed for {z}/{x}/{y}: {exc}")
        return _EMPTY_TILE_BYTES
