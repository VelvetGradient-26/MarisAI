"""Copernicus Marine surface wind: cache + point lookup + global field texture.

Data flow: `refresh_wind_cache()` pulls one global timestep of
`eastward_wind`/`northward_wind` from `cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H`
(the product behind `WIND_GLO_PHY_L4_NRT_012_004` — a gap-filled L4 blend of
scatterometer and model wind, not the ocean-physics product used for SST, which
carries currents rather than true atmospheric wind) and holds it in memory as
plain numpy grids (~16.5MB each for u/v). Unlike SST's per-request tile
rendering, the GPU particle layer needs the *whole* vector field as a single
texture (particles are advected client-side, not colored per-tile), so
`render_field_png()` runs once per refresh and its bytes are cached directly —
there's no z/x/y here, no render-on-demand path.

Not falling back to another source when Copernicus is unreachable (Phase 1
scope decision, same as SST) — a failed refresh just leaves the previous,
still-real, correctly timestamped cache in place. `CopernicusWindError` is only
raised when no cache has ever been populated at all.
"""

from __future__ import annotations

import asyncio
import io
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
from loguru import logger
from PIL import Image
from scipy.interpolate import RegularGridInterpolator
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

DATASET_ID = "cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H"
SOURCE_LABEL = "Copernicus Marine Service (WIND_GLO_PHY_L4_NRT_012_004)"

UNIT = "m/s"
# Spec's top bucket is "25+ m/s -> purple", open-ended — used by the legend,
# not a hard clamp on real values.
SPEED_MAX_LEGEND = 25.0

# Downsample factor applied before encoding the field texture: a particle
# system samples with GPU bilinear filtering regardless, so native 0.125deg
# resolution (1440x2880) buys nothing visually here and just makes the
# texture slower to download/sample. /2 -> 720x1440, still a clean 4x oversample
# vs. the coarsest world-view particle density.
_DOWNSAMPLE = 2

_COMPASS_LABELS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# Standard Beaufort scale, thresholds in m/s (upper bound of each force).
_BEAUFORT_THRESHOLDS: list[tuple[float, int, str]] = [
    (0.5, 0, "Calm"),
    (1.5, 1, "Light Air"),
    (3.3, 2, "Light Breeze"),
    (5.4, 3, "Gentle Breeze"),
    (7.9, 4, "Moderate Breeze"),
    (10.7, 5, "Fresh Breeze"),
    (13.8, 6, "Strong Breeze"),
    (17.1, 7, "Near Gale"),
    (20.7, 8, "Gale"),
    (24.4, 9, "Strong Gale"),
    (28.4, 10, "Storm"),
    (32.6, 11, "Violent Storm"),
]


class CopernicusWindError(RuntimeError):
    pass


@dataclass
class _WindCache:
    u_interp: RegularGridInterpolator
    v_interp: RegularGridInterpolator
    lon_min: float
    u_min: float
    u_max: float
    v_min: float
    v_max: float
    field_png: bytes
    timestamp: datetime


_cache: _WindCache | None = None
_refresh_lock = asyncio.Lock()


def _build_interpolator(lat: np.ndarray, lon: np.ndarray, grid: np.ndarray) -> RegularGridInterpolator:
    """Same antimeridian-wrap trick as copernicus_sst._build_interpolator: the
    grid's own longitude axis only covers [lon[0], lon[0]+360), so a query
    right at the seam needs one extra wrap column appended at the high end.

    Unlike SST (whose grid happens to start exactly at -180, matching the API's
    query bound), this dataset's longitude axis starts at -179.9375 — so
    queries in [-180, -179.9375) fall *below* lon[0] too. Appending a wrap
    column only fixes the high side; `get_point` also has to fold the query
    longitude into [lon[0], lon[0]+360) via modulo before calling this
    interpolator, or that low sliver would wrongly read as no-data.
    """
    lon_wrapped = np.append(lon, lon[0] + 360.0)
    grid_wrapped = np.concatenate([grid, grid[:, :1]], axis=1)
    return RegularGridInterpolator(
        (lat, lon_wrapped), grid_wrapped, method="linear", bounds_error=False, fill_value=np.nan
    )


def _wrap_longitude(longitude: float, lon_min: float) -> float:
    return lon_min + (longitude - lon_min) % 360.0


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _fetch_latest_grid() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, datetime]:
    import copernicusmarine

    now = datetime.now(timezone.utc)
    ds = copernicusmarine.open_dataset(
        dataset_id=DATASET_ID,
        variables=["eastward_wind", "northward_wind"],
        username=settings.COPERNICUS_USERNAME,
        password=settings.COPERNICUS_PASSWORD,
        # Explicit, not a default — same lesson as copernicus_sst.py: this
        # dataset also publishes a point-optimized "arco-time-series" service
        # (tiny lat/lon chunks, huge time chunks) as the one open_dataset()
        # picks by default. Forcing "arco-geo-series" (huge lat/lon chunks,
        # one timestep per chunk) is what makes a full-grid single-timestep
        # load take ~27s instead of many minutes.
        service="arco-geo-series",
    )
    past = ds.sel(time=slice(None, now.replace(tzinfo=None)))
    u_da = past.eastward_wind.isel(time=-1).load()
    v_da = past.northward_wind.isel(time=-1).load()

    timestamp = datetime.fromisoformat(str(u_da.time.values)[:19]).replace(tzinfo=timezone.utc)
    lat = u_da.latitude.values.astype(np.float64)
    lon = u_da.longitude.values.astype(np.float64)
    u = u_da.values.astype(np.float64)
    v = v_da.values.astype(np.float64)
    return lat, lon, u, v, timestamp


def _block_mean_downsample(grid: np.ndarray, factor: int) -> np.ndarray:
    h, w = grid.shape
    reshaped = grid.reshape(h // factor, factor, w // factor, factor)
    with np.errstate(invalid="ignore"):
        return np.nanmean(reshaped, axis=(1, 3))


def _encode_field_png(u: np.ndarray, v: np.ndarray) -> tuple[bytes, float, float, float, float]:
    u_small = _block_mean_downsample(u, _DOWNSAMPLE)
    v_small = _block_mean_downsample(v, _DOWNSAMPLE)

    valid = ~(np.isnan(u_small) | np.isnan(v_small))
    u_min, u_max = float(np.nanmin(u_small)), float(np.nanmax(u_small))
    v_min, v_max = float(np.nanmin(v_small)), float(np.nanmax(v_small))

    def normalize(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
        span = hi - lo if hi > lo else 1.0
        return np.clip((values - lo) / span, 0.0, 1.0)

    r = np.nan_to_num(normalize(u_small, u_min, u_max), nan=0.0) * 255
    g = np.nan_to_num(normalize(v_small, v_min, v_max), nan=0.0) * 255
    b = np.zeros_like(r)  # reserved for future generalization (e.g. precomputed speed)
    a = np.where(valid, 255, 0)

    rgba = np.dstack([r, g, b, a]).astype(np.uint8)
    buf = io.BytesIO()
    # flipud: row 0 of the array is latitude[0] (-90, south pole); PNG/texture
    # row 0 is conventionally the top, so this keeps north "up" in the texture.
    Image.fromarray(np.flipud(rgba), mode="RGBA").save(buf, format="PNG")
    return buf.getvalue(), u_min, u_max, v_min, v_max


async def refresh_wind_cache() -> None:
    global _cache
    async with _refresh_lock:
        try:
            lat, lon, u, v, timestamp = await asyncio.to_thread(_fetch_latest_grid)
        except Exception as exc:  # noqa: BLE001 - keep stale cache on any failure
            logger.warning(f"Wind refresh failed, keeping previous cache if any: {exc}")
            return

        u_interp = _build_interpolator(lat, lon, u)
        v_interp = _build_interpolator(lat, lon, v)
        field_png, u_min, u_max, v_min, v_max = await asyncio.to_thread(_encode_field_png, u, v)

        _cache = _WindCache(
            u_interp=u_interp,
            v_interp=v_interp,
            lon_min=float(lon[0]),
            u_min=u_min,
            u_max=u_max,
            v_min=v_min,
            v_max=v_max,
            field_png=field_png,
            timestamp=timestamp,
        )
        logger.info(f"Wind cache refreshed: timestep {timestamp.isoformat()}")


def _require_cache() -> _WindCache:
    if _cache is None:
        raise CopernicusWindError("Wind data not yet available — initial fetch still in progress or failed")
    return _cache


def get_meta() -> dict[str, Any]:
    cache = _require_cache()
    return {
        "timestamp": cache.timestamp.isoformat(),
        "source": SOURCE_LABEL,
        "unit": UNIT,
        "speed_max_legend": SPEED_MAX_LEGEND,
        "u_min": cache.u_min,
        "u_max": cache.u_max,
        "v_min": cache.v_min,
        "v_max": cache.v_max,
    }


def _beaufort(speed_ms: float) -> dict[str, Any]:
    for threshold, force, label in _BEAUFORT_THRESHOLDS:
        if speed_ms <= threshold:
            return {"force": force, "label": label}
    return {"force": 12, "label": "Hurricane"}


def _compass_label(direction_from_deg: float) -> str:
    index = round(direction_from_deg / 45) % 8
    return _COMPASS_LABELS[index]


def get_point(latitude: float, longitude: float) -> dict[str, Any]:
    cache = _require_cache()
    lon_query = _wrap_longitude(longitude, cache.lon_min)
    u = float(cache.u_interp([[latitude, lon_query]])[0])
    v = float(cache.v_interp([[latitude, lon_query]])[0])
    is_nan = np.isnan(u) or np.isnan(v)

    if is_nan:
        return {
            "speed_ms": None,
            "direction_from_deg": None,
            "direction_compass": None,
            "beaufort": None,
            "is_land_or_no_data": True,
            "timestamp": cache.timestamp.isoformat(),
            "source": SOURCE_LABEL,
        }

    speed = math.hypot(u, v)
    # Meteorological "from" convention: a north wind blows FROM the north
    # (air moving southward). Verified against known cases, e.g. u=-1,v=0
    # (air moving due west) -> 90 deg (wind "from the East").
    direction_from = (270 - math.degrees(math.atan2(v, u))) % 360

    return {
        "speed_ms": round(speed, 2),
        "direction_from_deg": round(direction_from, 1),
        "direction_compass": _compass_label(direction_from),
        "beaufort": _beaufort(speed),
        "is_land_or_no_data": False,
        "timestamp": cache.timestamp.isoformat(),
        "source": SOURCE_LABEL,
    }


def get_field_png() -> bytes:
    cache = _require_cache()
    return cache.field_png
