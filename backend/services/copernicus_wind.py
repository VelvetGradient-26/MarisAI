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
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

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
    # The timestep the data describes. Distinct from `fetched_at`: this
    # product routinely publishes a step many hours behind real time, so
    # judging provider health on it reports a working feed as down.
    timestamp: datetime
    fetched_at: datetime


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


# This near-real-time L4 product reserves a time-index slot for the most
# recent hour(s) before its gap-filling pipeline has actually populated them
# — the timestep exists (copernicusmarine picks it fine, no error) but every
# value in it is NaN, alongside a "currently being updated" warning from the
# library. Confirmed live: at time of writing, the latest 24 straight hourly
# timesteps were 0.0% valid, with real data only resuming at the 25th step
# back — a sustained gap, not a one-off blip. Unconditionally taking time=-1
# (the previous behavior) picks one of these empty placeholders whenever a
# refresh happens to land inside that window — the fetch itself doesn't fail,
# so nothing catches it, but the resulting grid is entirely no-data. Walking
# backward to the newest timestep that actually has real data avoids that.
_MAX_LOOKBACK_STEPS = 30
_MIN_VALID_FRACTION = 0.1

# Small open-ocean boxes used to *screen* timesteps before paying for a global
# load. Two, in different basins, so a partially-written timestep is not
# discarded because one region happened to be empty. They must be open ocean:
# this is an ocean-surface wind product, so a box over land is NaN in every
# timestep and would screen everything out.
_PROBE_BOXES = (
    (-5.0, 5.0, -150.0, -140.0),  # equatorial Pacific
    (30.0, 40.0, -40.0, -30.0),  # North Atlantic
)


def _candidate_times(now: datetime) -> list[Any]:
    """Newest-first timestamps that plausibly carry data.

    **Why this exists.** The walk-back below used to call `.load()` on a full
    global grid at every step purely to compute a validity fraction — ~15s of
    transfer for a field that is 100% NaN and thrown away. Against the 24-hour
    empty window this product routinely publishes, that was ~2.5 minutes before
    the first usable timestep and ~10 minutes before giving up, during which
    the wind layer and every wind-dependent panel read as unavailable.

    **Why the service differs from the one below.** Striding `arco-geo-series`
    does not help and was measured: a 20x-decimated read of one timestep took
    16.0s against 14.8s for the full field, because geo-series stores one huge
    lat/lon chunk per timestep and the whole chunk must be fetched to
    decompress. `arco-time-series` has the opposite chunking — fine spatially,
    huge in time — so a small box across many timesteps is one cheap read:
    measured at 3.8s for 30 timesteps, versus 15s per timestep.

    This is a screen, not the criterion. `_fetch_latest_grid` still verifies
    the real global validity fraction on the full field before accepting a
    timestep, so a wrong guess here can only cost an extra load, never admit an
    empty grid.
    """
    import copernicusmarine

    seen: dict[Any, float] = {}
    for min_lat, max_lat, min_lon, max_lon in _PROBE_BOXES:
        probe = copernicusmarine.open_dataset(
            dataset_id=DATASET_ID,
            variables=["eastward_wind"],
            minimum_latitude=min_lat,
            maximum_latitude=max_lat,
            minimum_longitude=min_lon,
            maximum_longitude=max_lon,
            username=settings.COPERNICUS_USERNAME,
            password=settings.COPERNICUS_PASSWORD,
            service="arco-time-series",
        )
        window = probe.eastward_wind.sel(time=slice(None, now.replace(tzinfo=None))).isel(
            time=slice(-_MAX_LOOKBACK_STEPS, None)
        )
        block = window.load()
        fractions = np.isfinite(block.values).reshape(block.shape[0], -1).mean(axis=1)
        for stamp, fraction in zip(block.time.values, fractions, strict=True):
            # Best score across boxes: valid in *either* basin is a candidate.
            seen[stamp] = max(seen.get(stamp, 0.0), float(fraction))

    candidates = [stamp for stamp, fraction in seen.items() if fraction > 0.0]
    candidates.sort(reverse=True)
    return candidates


# retry_if_not_exception_type(CopernicusWindError): a real network/auth
# failure on open_dataset()/.load() is worth 3 attempts with backoff, but
# CopernicusWindError here means the lookback already scanned
# _MAX_LOOKBACK_STEPS real timesteps and confirmed none had data — retrying
# that verdict 3 more times would just triple a multi-minute scan for an
# answer that isn't going to change within seconds.
@retry(
    retry=retry_if_not_exception_type(CopernicusWindError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
)
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

    candidates = _candidate_times(now)
    if not candidates:
        raise CopernicusWindError(
            f"No usable wind timestep found in the last {_MAX_LOOKBACK_STEPS} hours "
            "— all appear to still be backfilling upstream"
        )

    for stamp in candidates:
        u_da = past.eastward_wind.sel(time=stamp).load()
        # The screen only says "some data somewhere". This is the real
        # criterion, on the actual field being cached.
        valid_fraction = float(np.isfinite(u_da.values).mean())
        if valid_fraction >= _MIN_VALID_FRACTION:
            v_da = past.northward_wind.sel(time=stamp).load()
            timestamp = datetime.fromisoformat(str(u_da.time.values)[:19]).replace(tzinfo=timezone.utc)
            lat = u_da.latitude.values.astype(np.float64)
            lon = u_da.longitude.values.astype(np.float64)
            u = u_da.values.astype(np.float64)
            v = v_da.values.astype(np.float64)
            return lat, lon, u, v, timestamp
        logger.warning(
            f"Wind timestep {str(u_da.time.values)[:19]} passed the probe but is "
            f"only {valid_fraction:.1%} valid globally — trying an earlier timestep"
        )

    raise CopernicusWindError(
        f"No usable wind timestep found in the last {_MAX_LOOKBACK_STEPS} hours "
        "— all appear to still be backfilling upstream"
    )


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
        # Everything here — fetch, interpolator build, PNG encode — is inside
        # one try/except. Previously only the fetch was guarded, so a failure
        # in _build_interpolator/_encode_field_png (e.g. a grid shape that
        # doesn't split evenly into the encoder's downsample blocks, or an
        # all-NaN slice) escaped uncaught out of a fire-and-forget asyncio
        # task/scheduler job: asyncio just logs "exception was never
        # retrieved" and drops it, _cache stays None forever, and every wind
        # endpoint 502s/503s permanently with nothing actionable in the logs.
        try:
            lat, lon, u, v, timestamp = await asyncio.to_thread(_fetch_latest_grid)
            u_interp = _build_interpolator(lat, lon, u)
            v_interp = _build_interpolator(lat, lon, v)
            field_png, u_min, u_max, v_min, v_max = await asyncio.to_thread(_encode_field_png, u, v)
        except Exception:  # noqa: BLE001 - keep stale cache on any failure
            logger.opt(exception=True).warning("Wind refresh failed, keeping previous cache if any")
            return

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
            fetched_at=datetime.now(timezone.utc),
        )
        logger.info(f"Wind cache refreshed: timestep {timestamp.isoformat()}")


def _require_cache() -> _WindCache:
    if _cache is None:
        raise CopernicusWindError("Wind data not yet available — initial fetch still in progress or failed")
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


def get_meta() -> dict[str, Any]:
    cache = _require_cache()
    return {
        "timestamp": cache.timestamp.isoformat(),
        "fetched_at": cache.fetched_at.isoformat(),
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
