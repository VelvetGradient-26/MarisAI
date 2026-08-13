"""Copernicus Marine surface currents: cache + point lookup + field texture.

The ocean counterpart to `copernicus_wind`, and deliberately the *same* dataset
`copernicus_sst` already uses — `cmems_mod_glo_phy_anfc_0.083deg_PT1H-m` carries
`thetao`, `so`, `uo`, `vo` and `zos` on one singleton surface level, so the
currents field costs a second fetch of a product this codebase already knows how
to open quickly (`arco-geo-series`, the whole globe at one instant) rather than
a new integration with its own failure modes.

Three things differ from wind and are worth knowing before editing:

* **The grid is not the global frame.** This product runs latitude **-80 to 90**.
  The wind product covers the full -90 to 90, and the particle shader used to
  assume that of every field. Bounds now travel in the meta (see
  `services/vector_field`), and the shader treats a particle below 80degS as
  off-field and respawns it, rather than sampling the -80 row and advecting the
  Southern Ocean with Antarctic coastal water.
* **Currents are an order of magnitude slower than wind** — a typical open-ocean
  0.1-0.4 m/s against wind's 5-10 m/s — so the legend tops out at 2 m/s and the
  layer asks the particle engine for its own visual speed scale. At wind's
  scale these particles would read as stationary.
* **No candidate-timestep scan.** Wind needs one because its L4 product
  routinely publishes a day of all-NaN placeholder steps; this analysis product
  does not, which is why `copernicus_sst` takes the latest past step outright.
  A bounded walk-back is still here, because "the latest timestep exists" and
  "the latest timestep has data" are different claims and this codebase has been
  caught by that difference before — but it validates on the field it is already
  loading rather than paying for a separate probe.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from loguru import logger
from scipy.interpolate import RegularGridInterpolator
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from services import vector_field
from services.copernicus_sst import _DEPTH_MAX, _DEPTH_MIN, DATASET_ID

SOURCE_LABEL = "Copernicus Marine Service (GLOBAL_ANALYSISFORECAST_PHY_001_024)"
U_VARIABLE = "uo"
V_VARIABLE = "vo"

UNIT = "m/s"
# Legend top. Open ocean sits at 0.1-0.4 m/s; the western boundary currents —
# Gulf Stream, Kuroshio, Agulhas — are the reason the scale has to reach 2.
SPEED_MAX_LEGEND = 2.0

# 0.083deg native is 2041x4320. /3 -> 680x1440, matching the wind texture's
# 720x1440 on the wire for the same reason: the particle system samples with
# GPU bilinear filtering, so native resolution buys nothing visually and costs
# the client megabytes on every layer activation. 2041 does not divide by 3 —
# `vector_field.block_mean` crops the odd row and reports the axis that
# survives, so the declared bounds stay exact.
_DOWNSAMPLE = 3

# How far back to look for a timestep that actually carries data. Short,
# unlike wind's 30: this is an analysis product rather than a gap-filled L4
# blend, so the first step is expected to work and each step costs a global
# load.
_MAX_LOOKBACK_STEPS = 4
_MIN_VALID_FRACTION = 0.1

_COMPASS_LABELS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


class CopernicusCurrentsError(RuntimeError):
    pass


@dataclass
class _CurrentsCache:
    u_interp: RegularGridInterpolator
    v_interp: RegularGridInterpolator
    lon_min: float
    texture: vector_field.FieldTexture
    # The timestep the data describes, distinct from `fetched_at` — same
    # reasoning as the wind cache: judging provider health on publication lag
    # reports a working feed as down.
    timestamp: datetime
    fetched_at: datetime


_cache: _CurrentsCache | None = None
_refresh_lock = asyncio.Lock()


@retry(
    retry=retry_if_not_exception_type(CopernicusCurrentsError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
)
def _fetch_latest_grid() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, datetime]:
    import copernicusmarine

    now = datetime.now(UTC)
    dataset = copernicusmarine.open_dataset(
        dataset_id=DATASET_ID,
        variables=[U_VARIABLE, V_VARIABLE],
        # The same server-side depth bound `copernicus_sst` passes. This
        # product's surface level is a singleton, so it is cheap insurance
        # here rather than the order-of-magnitude fix it is on the 50-level
        # reanalysis products — but it costs nothing and keeps the two
        # call sites reading identically.
        minimum_depth=_DEPTH_MIN,
        maximum_depth=_DEPTH_MAX,
        username=settings.COPERNICUS_USERNAME,
        password=settings.COPERNICUS_PASSWORD,
        # Explicit, and load-bearing: this dataset publishes a point-optimised
        # "arco-time-series" service that `open_dataset` picks by default and
        # that takes many minutes for one global timestep. See copernicus_sst.
        service="arco-geo-series",
    )
    past = dataset.sel(time=slice(None, now.replace(tzinfo=None)))

    for step in range(1, _MAX_LOOKBACK_STEPS + 1):
        u_da = past[U_VARIABLE].isel(time=-step, depth=0).load()
        valid_fraction = float(np.isfinite(u_da.values).mean())
        if valid_fraction < _MIN_VALID_FRACTION:
            logger.warning(
                f"Currents timestep {str(u_da.time.values)[:19]} is only "
                f"{valid_fraction:.1%} valid — trying an earlier timestep"
            )
            continue

        v_da = past[V_VARIABLE].isel(time=-step, depth=0).load()
        timestamp = datetime.fromisoformat(str(u_da.time.values)[:19]).replace(
            tzinfo=UTC
        )
        return (
            u_da.latitude.values.astype(np.float64),
            u_da.longitude.values.astype(np.float64),
            u_da.values.astype(np.float64),
            v_da.values.astype(np.float64),
            timestamp,
        )

    raise CopernicusCurrentsError(
        f"No usable currents timestep in the last {_MAX_LOOKBACK_STEPS} hours "
        "— all appear to still be backfilling upstream"
    )


async def refresh_currents_cache() -> None:
    global _cache
    async with _refresh_lock:
        # One try/except around fetch *and* encode, for the reason
        # copernicus_wind documents at length: this runs as a fire-and-forget
        # scheduler task, so an exception escaping the encode step is swallowed
        # by asyncio, the cache stays None forever, and every currents endpoint
        # 503s permanently with nothing actionable logged.
        try:
            lat, lon, u, v, timestamp = await asyncio.to_thread(_fetch_latest_grid)
            u_interp = vector_field.build_interpolator(lat, lon, u)
            v_interp = vector_field.build_interpolator(lat, lon, v)
            texture = await asyncio.to_thread(
                vector_field.encode, u, v, lat, lon, downsample=_DOWNSAMPLE
            )
        except Exception:  # noqa: BLE001 - keep stale cache on any failure
            logger.opt(exception=True).warning(
                "Currents refresh failed, keeping previous cache if any"
            )
            return

        _cache = _CurrentsCache(
            u_interp=u_interp,
            v_interp=v_interp,
            lon_min=float(lon[0]),
            texture=texture,
            timestamp=timestamp,
            fetched_at=datetime.now(UTC),
        )
        logger.info(f"Currents cache refreshed: timestep {timestamp.isoformat()}")


def _require_cache() -> _CurrentsCache:
    if _cache is None:
        raise CopernicusCurrentsError(
            "Currents data not yet available — initial fetch still in progress or failed"
        )
    return _cache


def is_refreshing() -> bool:
    """Whether a refresh is in flight, derived from the existing lock rather
    than a second flag. Lets a caller tell "still warming up" from "failed"."""
    return _refresh_lock.locked()


def is_available() -> bool:
    return _cache is not None


def get_meta() -> dict[str, Any]:
    cache = _require_cache()
    return {
        "timestamp": cache.timestamp.isoformat(),
        "fetched_at": cache.fetched_at.isoformat(),
        "source": SOURCE_LABEL,
        "unit": UNIT,
        "speed_max_legend": SPEED_MAX_LEGEND,
        "u_min": cache.texture.u_min,
        "u_max": cache.texture.u_max,
        "v_min": cache.texture.v_min,
        "v_max": cache.texture.v_max,
        **cache.texture.bounds(),
    }


def _compass_label(direction_toward_deg: float) -> str:
    return _COMPASS_LABELS[round(direction_toward_deg / 45) % 8]


def get_point(latitude: float, longitude: float) -> dict[str, Any]:
    cache = _require_cache()
    lon_query = vector_field.wrap_longitude(longitude, cache.lon_min)
    u = float(cache.u_interp([[latitude, lon_query]])[0])
    v = float(cache.v_interp([[latitude, lon_query]])[0])

    if np.isnan(u) or np.isnan(v):
        return {
            "speed_ms": None,
            "direction_toward_deg": None,
            "direction_compass": None,
            "u_ms": None,
            "v_ms": None,
            "is_land_or_no_data": True,
            "timestamp": cache.timestamp.isoformat(),
            "source": SOURCE_LABEL,
        }

    # Oceanographic convention, and the opposite of wind's: a current is named
    # for the direction it flows *toward*, a wind for the direction it blows
    # *from*. A northward current (u=0, v=1) is a "north" / 0deg current, where
    # the same vector as wind would be reported as 180deg ("from the south").
    # Reusing wind's formula here would have every arrow backwards, so the
    # field name says which convention this is rather than leaving it to be
    # inferred from a bare "direction_deg".
    direction_toward = (90.0 - math.degrees(math.atan2(v, u))) % 360.0

    return {
        "speed_ms": round(math.hypot(u, v), 3),
        "direction_toward_deg": round(direction_toward, 1),
        "direction_compass": _compass_label(direction_toward),
        "u_ms": round(u, 3),
        "v_ms": round(v, 3),
        "is_land_or_no_data": False,
        "timestamp": cache.timestamp.isoformat(),
        "source": SOURCE_LABEL,
    }


def get_field_png() -> bytes:
    return _require_cache().texture.png
