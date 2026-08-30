"""A drift trajectory forecast — an ensemble corridor, not a line.

`services/drift.py` ships the combined *field* (current + Stokes drift + a
leeway fraction of wind), but every particle in it advects against a single
snapshot: correct for an animated streamline, wrong for "where will this
object be in 48 hours," which needs a time-indexed stack and an integrator
(see TODO.md's "Drift: the field ships, the trajectory does not").

**Per-term forecast source, verified live 2026-08-28**
(`scripts/probe_forecast_timesteps.py`), not assumed:

* **Current + Stokes drift**: a single `arco-time-series` fetch (the access
  pattern `services/download/providers/copernicus.py` already proves for
  "bounded area, many timesteps") against the same `GLOBAL_ANALYSISFORECAST_*`
  products `services/copernicus_currents.py`/`services/stokes_drift.py`
  already use for the live nowcast. The live probe found **100%-valid
  forecast data out to +224h (currents) and +225h (Stokes)** for a ~6deg bbox
  — far past this module's 96h ceiling, so the live path covers the whole
  requested horizon in the ordinary case. Falls back per-point (never
  per-request) to the coarse ML forecast grids
  (`models/forecasting/_grids/current_u.nc`/`current_v.nc`, 1deg, daily
  horizons) wherever the live interpolator returns NaN — outside the fetched
  bbox, outside its fetched time window, or if the live fetch failed
  outright. Stokes has **no** ML fallback (no wave-vector model is trained —
  `forecasting/config/forecasting.yaml` only has scalar wave height/period/
  direction) — a Stokes gap falls back to the last-observed nowcast
  (`services/stokes_drift.snapshot()`), resampled at the member's *current*
  position every step, not frozen at the start point.
* **Wind leeway**: the live wind field
  (`WIND_GLO_PHY_L4_NRT_012_004`) is an L4 *observation* blend with no
  forecast timesteps at all — confirmed via
  `services/download/catalog.py`'s provider specs (physics/waves are
  `GLOBAL_ANALYSISFORECAST_*`; wind is not). The **only** forecast source for
  wind is the ML `wind_u`/`wind_v` grids. Skipped entirely when
  `alpha == 0` (water_only) — no wind I/O happens at all for that case.

**The integrator** is RK4 in lat/lon, vectorized across the whole ensemble
(every member shares the same clock, so one call per RK stage evaluates all
members at once) — curvature under-resolution is exactly the failure mode
TODO.md names for a cruder scheme, and vectorizing makes member count nearly
free.

**The ensemble is the feature, not a decoration** (TODO.md: "state the
uncertainty or do not ship it — a single deterministic track reads as a
prediction of where the object is"). What is perturbed, and where each
magnitude comes from:

* Current/wind field error: real, CV-measured `residual_quantiles` already
  written to each ML model's `metadata.json`
  (`forecasting.model_store.describe`, JSON-only — no LightGBM import, no
  unpickling), interpolated between the h1/h3 artifacts by the requested
  horizon. A real measured error scale, reused for a different central
  estimate (the live fetch) than it was measured on (the ML model) — stated
  here, not hidden.
* Stokes field error: **no measured quantity exists** for this term (no
  trained wave-vector model) — each member draws an honestly-labeled,
  uncalibrated multiplicative factor.
* Leeway alpha: perturbed only when a *named preset* was used, never for an
  explicit numeric alpha (which is an assertion of a known coefficient).
* Start position: a per-member Gaussian offset, frozen for the whole track.

Never zero-filled: a term with no source anywhere for a given member/step is
dropped for that step (current/stokes) or the member is frozen at its last
valid position rather than advected on fabricated motion (see `_advect`).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator

from forecasting import ForecastingError
from forecasting.model_store import describe as describe_model
from services import field_sampling, stokes_drift
from services.download.providers import copernicus as copernicus_provider
from services.forecast_tiles import ForecastTileError, _grid_dir, _load_grid

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

METERS_PER_DEG_LAT = 111_320.0

DT_SECONDS = 1_200.0  # 20 minutes
DEFAULT_HORIZON_HOURS = 48.0
MIN_HORIZON_HOURS = 6.0
MAX_HORIZON_HOURS = 96.0
MAX_START_LOOKBACK_HOURS = 12.0

DEFAULT_N_MEMBERS = 100
MIN_MEMBERS = 20
MAX_MEMBERS = 200

DEFAULT_START_POSITION_UNCERTAINTY_KM = 1.0
MAX_START_POSITION_UNCERTAINTY_KM = 50.0

# Sizes the live-fetch bounding box. Below `drift.SPEED_MAX_LEGEND`'s 2.5,
# which is peak *instantaneous* boundary-current speed, not a sustained 48h
# figure a drifting object realistically holds.
_BOX_SPEED_CEILING_MS = 2.0
_BOX_MARGIN_DEG = 1.0
_BOX_MAX_HALF_WIDTH_DEG = 5.0

_ALPHA_JITTER_RELATIVE_STD = 0.25
_STOKES_FACTOR_RANGE = (0.7, 1.3)

# The ML forecasting engine's trained horizons, plus the implicit day-0
# "anchor" (today's real observation) a lead time is bracketed between.
_ML_GRID_HORIZON_DAYS = (0, 1, 3, 7, 30)

# Every hour reported back, out of the DT_SECONDS-resolution integration —
# fine enough to look smooth, coarse enough not to ship 144 points per member.
_REPORT_STEP = max(1, round(3600.0 / DT_SECONDS))


class DriftTrajectoryError(RuntimeError):
    """A drift trajectory could not be planned at all. Raised only when
    nothing — live or fallback — can supply the current term; a partial
    degradation of one term is reported in the result, never raised."""


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------


def _meters_per_deg_lon(lat_deg: np.ndarray) -> np.ndarray:
    return METERS_PER_DEG_LAT * np.cos(np.radians(lat_deg))


def _half_width_deg(horizon_hours: float) -> float:
    meters = _BOX_SPEED_CEILING_MS * horizon_hours * 3600.0
    return min(_BOX_MAX_HALF_WIDTH_DEG, meters / METERS_PER_DEG_LAT + _BOX_MARGIN_DEG)


# --------------------------------------------------------------------------
# Live forecast fetch -> a (time, lat, lon) interpolator
# --------------------------------------------------------------------------


@dataclass
class _LiveField:
    u_interp: RegularGridInterpolator
    v_interp: RegularGridInterpolator
    t0: datetime  # the interpolator's time axis is seconds-since-t0


def _build_live_field(dataset: xr.Dataset, u_field: str, v_field: str) -> _LiveField | None:
    """Turn a fetched `(time, latitude, longitude)` dataset into a `_LiveField`
    time/lat/lon interpolator, or `None` if the dataset has no timesteps.

    Split out of `_fetch_live_field` (which still does the network fetch and
    decides what "no data" means for the live path) so a caller that already
    has a dataset in hand — `scripts/compare_against_drifter_tracks.py`,
    substituting a historical reanalysis fetch for the live one — can build
    the same interpolator without duplicating this construction. Raises
    nothing; an empty dataset is a normal case for both callers, handled
    differently by each (this one falls back, the validation script excludes
    the segment).
    """
    dataset = dataset.transpose("time", "latitude", "longitude")
    times = dataset["time"].values
    if times.size == 0:
        return None

    t0 = datetime.fromisoformat(str(times[0])[:19]).replace(tzinfo=UTC)
    t_seconds = np.array(
        [
            (datetime.fromisoformat(str(t)[:19]).replace(tzinfo=UTC) - t0).total_seconds()
            for t in times
        ]
    )
    lat = dataset["latitude"].values.astype(np.float64)
    lon = dataset["longitude"].values.astype(np.float64)

    def _interp(field: str) -> RegularGridInterpolator:
        values = dataset[field].values.astype(np.float64)
        return RegularGridInterpolator(
            (t_seconds, lat, lon), values, method="linear", bounds_error=False, fill_value=np.nan
        )

    return _LiveField(u_interp=_interp(u_field), v_interp=_interp(v_field), t0=t0)


async def _fetch_live_field(
    label: str,
    dataset_id: str,
    u_field: str,
    v_field: str,
    depth_mode: str,
    center_lat: float,
    center_lon: float,
    half_width_deg: float,
    start_time: datetime,
    horizon_hours: float,
) -> _LiveField | None:
    """Best-effort: returns None (and logs) rather than raising. Both terms
    this backs have a fallback, so a live-fetch failure degrades, it does
    not fail the request."""
    try:
        dataset = await copernicus_provider.fetch(
            dataset_id=dataset_id,
            fields=[u_field, v_field],
            west=center_lon - half_width_deg,
            east=center_lon + half_width_deg,
            south=center_lat - half_width_deg,
            north=center_lat + half_width_deg,
            start_date=(start_time - timedelta(hours=6)).date(),
            end_date=(start_time + timedelta(hours=horizon_hours + 6)).date(),
            depth_mode=depth_mode,
        )
    except Exception:  # noqa: BLE001 - any upstream failure degrades to the fallback path
        logger.warning(f"{label} live forecast fetch failed, will fall back", exc_info=True)
        return None

    field = _build_live_field(dataset, u_field, v_field)
    if field is None:
        logger.warning(f"{label} live forecast fetch returned no timesteps, will fall back")
    return field


def _sample_live(field: _LiveField, at_time: datetime, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t_seconds = (at_time - field.t0).total_seconds()
    points = np.column_stack([np.full(lat.shape, t_seconds), lat, lon])
    return field.u_interp(points), field.v_interp(points)


# --------------------------------------------------------------------------
# ML forecast grids -> the wind term, and the current/Stokes fallback
# --------------------------------------------------------------------------


def _ml_grid_bracket(lead_hours: float) -> tuple[int, int, float]:
    """(lower_horizon_days, upper_horizon_days, blend_fraction)."""
    lead_days = max(0.0, lead_hours / 24.0)
    days = _ML_GRID_HORIZON_DAYS
    if lead_days <= days[0]:
        return days[0], days[0], 0.0
    if lead_days >= days[-1]:
        return days[-2], days[-1], 1.0
    for lo, hi in zip(days, days[1:]):
        if lo <= lead_days <= hi:
            span = hi - lo
            return lo, hi, (lead_days - lo) / span if span else 0.0
    return days[-2], days[-1], 1.0  # unreachable


def _ml_grid_field(variable: str, horizon_days: int):
    try:
        grid = _load_grid(variable, str(_grid_dir()))
    except ForecastTileError:
        return None
    if horizon_days == 0:
        return grid["anchor"]
    if horizon_days not in [int(h) for h in grid.horizon.values]:
        return None
    return grid["forecast"].sel(horizon=horizon_days)


@lru_cache(maxsize=32)
def _cached_sampler(variable: str, horizon_days: int) -> field_sampling.Sampler | None:
    """`build_sampler` runs a `distance_transform_edt` over the whole grid and
    is not free — an RK4 integration calls this up to ~4x per stage (u/v times
    up to two brackets) and there are ~576 stages in a 96h/20min run, so an
    uncached rebuild here was the actual hot path, not the fetch. The
    underlying grid changes on a 12-hourly rebuild schedule, so caching by
    (variable, horizon_days) for the process lifetime is safe; `horizon_days`
    is a small closed set (0, 1, 3, 7, 30), so this cache never grows large."""
    field = _ml_grid_field(variable, horizon_days)
    return field_sampling.build_sampler(field) if field is not None else None


def _ml_grid_component(variable: str, lead_hours: float, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    lo_days, hi_days, fraction = _ml_grid_bracket(lead_hours)
    points = np.column_stack([lat, lon])

    def _sample(horizon_days: int) -> np.ndarray | None:
        sampler = _cached_sampler(variable, horizon_days)
        if sampler is None:
            return None
        covered = sampler.coverage(points) >= 0.5
        assert sampler.values is not None
        return np.where(covered, sampler.values(points), np.nan)

    lo_values = _sample(lo_days)
    if lo_values is None:
        return np.full(lat.shape, np.nan)
    if hi_days == lo_days:
        return lo_values
    hi_values = _sample(hi_days)
    if hi_values is None:
        return lo_values
    return lo_values * (1 - fraction) + hi_values * fraction


def _ml_grid_velocity(
    u_variable: str, v_variable: str, lead_hours: float, lat: np.ndarray, lon: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    return (
        _ml_grid_component(u_variable, lead_hours, lat, lon),
        _ml_grid_component(v_variable, lead_hours, lat, lon),
    )


def _ml_grid_available(variable: str) -> bool:
    return _ml_grid_field(variable, 0) is not None


def clear_cache() -> None:
    """Drop cached samplers. Call after a scheduled forecast-grid rebuild —
    see `services/forecast_tiles.py::refresh_grids`, which calls this
    alongside its own `clear_cache()` so the wind-leeway/current-fallback
    path picks up a rebuilt grid instead of serving `_cached_sampler`'s
    stale one indefinitely."""
    _cached_sampler.cache_clear()


# --------------------------------------------------------------------------
# Measured forecast error, for the ensemble's field-error perturbation
# --------------------------------------------------------------------------


def _residual_bounds(variable: str, horizon: int) -> tuple[float, float] | None:
    try:
        description = describe_model(variable, horizon)
    except ForecastingError:
        return None
    quantiles = description.metadata.get("residual_quantiles")
    if not quantiles:
        return None
    return float(quantiles["lower_offset"]), float(quantiles["upper_offset"])


def _error_bounds_for_horizon(variable: str, horizon_hours: float) -> tuple[float, float] | None:
    """h1/h3 residual quantiles, interpolated by the trajectory's total
    horizon — a real measured error scale for a different central estimate
    (the live forecast, or a longer ML horizon) than it was measured on."""
    horizon_days = horizon_hours / 24.0
    q1 = _residual_bounds(variable, 1)
    q3 = _residual_bounds(variable, 3)
    if q1 is None and q3 is None:
        return None
    if q3 is None:
        return q1
    if q1 is None:
        return q3
    fraction = min(1.0, max(0.0, (horizon_days - 1.0) / 2.0))
    return (
        q1[0] + (q3[0] - q1[0]) * fraction,
        q1[1] + (q3[1] - q1[1]) * fraction,
    )


# --------------------------------------------------------------------------
# The ensemble integration
# --------------------------------------------------------------------------


@dataclass
class _Sources:
    live_current: _LiveField | None
    live_stokes: _LiveField | None
    wind_available: bool


def _stokes_last_observed(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Stokes drift at the member's *current* position, held at its last-
    observed value — resampled every step, never frozen at the start point.
    Same global nowcast interpolator `services/drift.py` reads."""
    try:
        snapshot = stokes_drift.snapshot()
    except Exception:  # noqa: BLE001 - stokes_drift raises its own error type
        return np.full(lat.shape, np.nan), np.full(lat.shape, np.nan)
    # Same wrap formula as `vector_field.wrap_longitude`, vectorized.
    lon_wrapped = snapshot.lon_min + (lon - snapshot.lon_min) % 360.0
    points = np.column_stack([lat, lon_wrapped])
    return snapshot.u_interp(points), snapshot.v_interp(points)


def _combined_velocity(
    at_time: datetime,
    lat: np.ndarray,
    lon: np.ndarray,
    *,
    sources: _Sources,
    lead_hours: float,
    current_bias: tuple[np.ndarray, np.ndarray],
    stokes_factor: np.ndarray,
    alpha: np.ndarray,
    wind_bias: tuple[np.ndarray, np.ndarray],
    flags: dict[str, np.ndarray],
    allow_present_day_fallback: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    n = lat.shape[0]

    # --- current ---
    if sources.live_current is not None:
        cur_u, cur_v = _sample_live(sources.live_current, at_time, lat, lon)
    else:
        cur_u, cur_v = np.full(n, np.nan), np.full(n, np.nan)
    missing = np.isnan(cur_u)
    if missing.any():
        if allow_present_day_fallback:
            flags["current_fell_back"] |= missing
            fb_u, fb_v = _ml_grid_velocity("current_u", "current_v", lead_hours, lat, lon)
            cur_u = np.where(missing, fb_u, cur_u)
            cur_v = np.where(missing, fb_v, cur_v)
        else:
            flags["current_fallback_disabled"] |= missing
    still_missing = np.isnan(cur_u)
    if still_missing.any():
        flags["current_lost"] |= still_missing
    cur_u = np.where(still_missing, 0.0, cur_u + current_bias[0])
    cur_v = np.where(still_missing, 0.0, cur_v + current_bias[1])

    # --- Stokes drift ---
    if sources.live_stokes is not None:
        stk_u, stk_v = _sample_live(sources.live_stokes, at_time, lat, lon)
    else:
        stk_u, stk_v = np.full(n, np.nan), np.full(n, np.nan)
    missing = np.isnan(stk_u)
    if missing.any():
        if allow_present_day_fallback:
            flags["stokes_fell_back"] |= missing
            fb_u, fb_v = _stokes_last_observed(lat, lon)
            stk_u = np.where(missing, fb_u, stk_u)
            stk_v = np.where(missing, fb_v, stk_v)
        else:
            flags["stokes_fallback_disabled"] |= missing
    still_missing = np.isnan(stk_u)
    if still_missing.any():
        flags["stokes_lost"] |= still_missing
    stk_u = np.where(still_missing, 0.0, stk_u * stokes_factor)
    stk_v = np.where(still_missing, 0.0, stk_v * stokes_factor)

    # --- wind leeway ---
    wind_u = np.zeros(n)
    wind_v = np.zeros(n)
    if sources.wind_available and np.any(alpha > 0.0):
        raw_u, raw_v = _ml_grid_velocity("wind_u", "wind_v", lead_hours, lat, lon)
        missing = np.isnan(raw_u)
        if missing.any():
            flags["wind_lost"] |= missing
        wind_u = np.where(missing, 0.0, raw_u + wind_bias[0]) * alpha
        wind_v = np.where(missing, 0.0, raw_v + wind_bias[1]) * alpha

    return cur_u + stk_u + wind_u, cur_v + stk_v + wind_v


def _rk4_step(
    at_time: datetime,
    lat: np.ndarray,
    lon: np.ndarray,
    dt: float,
    **velocity_kwargs: Any,
) -> tuple[np.ndarray, np.ndarray]:
    def f(t: datetime, la: np.ndarray, lo: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        u, v = _combined_velocity(t, la, lo, **velocity_kwargs)
        dlat_dt = v / METERS_PER_DEG_LAT
        dlon_dt = u / _meters_per_deg_lon(la)
        return dlat_dt, dlon_dt

    half = timedelta(seconds=dt / 2)
    full = timedelta(seconds=dt)

    k1_lat, k1_lon = f(at_time, lat, lon)
    k2_lat, k2_lon = f(at_time + half, lat + dt / 2 * k1_lat, lon + dt / 2 * k1_lon)
    k3_lat, k3_lon = f(at_time + half, lat + dt / 2 * k2_lat, lon + dt / 2 * k2_lon)
    k4_lat, k4_lon = f(at_time + full, lat + dt * k3_lat, lon + dt * k3_lon)

    new_lat = lat + dt / 6 * (k1_lat + 2 * k2_lat + 2 * k3_lat + k4_lat)
    new_lon = lon + dt / 6 * (k1_lon + 2 * k2_lon + 2 * k3_lon + k4_lon)
    return new_lat, new_lon


def _degraded_terms(flags: dict[str, np.ndarray], n_members: int) -> list[str]:
    notes = []
    if flags["current_fell_back"].any():
        notes.append(
            f"current: {int(flags['current_fell_back'].sum())}/{n_members} members used the "
            "coarse ML forecast grid for at least one step (outside the live-fetched region "
            "or window)"
        )
    if flags["current_lost"].any():
        notes.append(
            f"current: {int(flags['current_lost'].sum())}/{n_members} members lost current "
            "coverage entirely for at least one step and were held stationary there"
        )
    if flags["current_fallback_disabled"].any():
        notes.append(
            f"current: {int(flags['current_fallback_disabled'].sum())}/{n_members} members "
            "would have needed the present-day ML-grid fallback but allow_present_day_fallback="
            "False — held stationary there instead of silently substituting today's data"
        )
    if flags["stokes_fell_back"].any():
        notes.append(
            f"stokes: {int(flags['stokes_fell_back'].sum())}/{n_members} members used the "
            "last-observed nowcast for at least one step (no live forecast timestep there)"
        )
    if flags["stokes_lost"].any():
        notes.append(
            f"stokes: {int(flags['stokes_lost'].sum())}/{n_members} members had no Stokes "
            "data at all for at least one step (dropped, not zero-filled)"
        )
    if flags["stokes_fallback_disabled"].any():
        notes.append(
            f"stokes: {int(flags['stokes_fallback_disabled'].sum())}/{n_members} members "
            "would have needed the present-day nowcast fallback but allow_present_day_fallback="
            "False — held stationary there instead of silently substituting today's data"
        )
    if flags["wind_lost"].any():
        notes.append(
            f"wind leeway: {int(flags['wind_lost'].sum())}/{n_members} members had no wind "
            "forecast grid coverage for at least one step (dropped for that step)"
        )
    return notes


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


async def plan_trajectory(
    start_lat: float,
    start_lon: float,
    alpha: float,
    preset_used: bool,
    *,
    start_time: datetime | None = None,
    horizon_hours: float = DEFAULT_HORIZON_HOURS,
    n_members: int = DEFAULT_N_MEMBERS,
    start_position_uncertainty_km: float = DEFAULT_START_POSITION_UNCERTAINTY_KM,
    rng: np.random.Generator | None = None,
    allow_present_day_fallback: bool = True,
) -> dict[str, Any]:
    """An ensemble drift trajectory: perturbed start position, leeway and
    field error, integrated with RK4 against the best available forecast
    source per term. See the module docstring for the source/fallback design.

    Raises `DriftTrajectoryError` only when the current term has no source at
    all, live or fallback — every partial degradation is reported in the
    result's `degraded_terms` instead.

    `allow_present_day_fallback` (default `True`, unchanged behavior for
    every existing caller): when a live/historical current or Stokes source
    has a gap, the ordinary fallback reads *today's* operational ML grid or
    nowcast — correct for the live forecast this function normally serves,
    wrong for a historical replay (`scripts/compare_against_drifter_tracks.py`),
    which sets this `False` so a gap is reported in `degraded_terms` instead
    of silently substituting present-day data into a past integration.

    The live fetch (network-bound) runs here, awaited directly; the ensemble
    integration (CPU-bound: RK4 over every member, no `await` in it) runs in
    a worker thread — same rule `forecast_tiles.py`'s grid cell loop and
    `copernicus_sst.py` already follow, so a several-hundred-member request
    never stalls the rest of the API for the duration of its own math.
    """
    resolved_start = start_time or datetime.now(UTC)
    horizon_hours = min(MAX_HORIZON_HOURS, max(MIN_HORIZON_HOURS, horizon_hours))
    n_members = min(MAX_MEMBERS, max(MIN_MEMBERS, n_members))

    half_width = _half_width_deg(horizon_hours)
    live_current, live_stokes = await asyncio.gather(
        _fetch_live_field(
            "current",
            copernicus_provider.PHYSICS_DATASET_ID,
            "uo",
            "vo",
            copernicus_provider.DEPTH_SURFACE,
            start_lat,
            start_lon,
            half_width,
            resolved_start,
            horizon_hours,
        ),
        _fetch_live_field(
            "stokes_drift",
            copernicus_provider.WAVES_DATASET_ID,
            "VSDX",
            "VSDY",
            copernicus_provider.DEPTH_NONE,
            start_lat,
            start_lon,
            half_width,
            resolved_start,
            horizon_hours,
        ),
    )

    return await asyncio.to_thread(
        _run_ensemble,
        start_lat,
        start_lon,
        alpha,
        preset_used,
        resolved_start,
        horizon_hours,
        n_members,
        start_position_uncertainty_km,
        live_current,
        live_stokes,
        rng or np.random.default_rng(),
        allow_present_day_fallback=allow_present_day_fallback,
    )


def _run_ensemble(
    start_lat: float,
    start_lon: float,
    alpha: float,
    preset_used: bool,
    resolved_start: datetime,
    horizon_hours: float,
    n_members: int,
    start_position_uncertainty_km: float,
    live_current: _LiveField | None,
    live_stokes: _LiveField | None,
    rng: np.random.Generator,
    *,
    allow_present_day_fallback: bool = True,
) -> dict[str, Any]:
    """The synchronous, CPU-bound half of `plan_trajectory` — draws, RK4
    integration, and result assembly. Runs off the event loop; see that
    function's docstring."""
    wind_available = alpha > 0.0 and _ml_grid_available("wind_u") and _ml_grid_available("wind_v")
    if live_current is None and not _ml_grid_available("current_u"):
        raise DriftTrajectoryError(
            "the current term has no source: the live forecast fetch failed and no ML "
            "forecast grid for current_u is built"
        )

    sources = _Sources(live_current=live_current, live_stokes=live_stokes, wind_available=wind_available)

    # --- per-member draws, once, frozen for the whole track ---
    lat_offset_km = rng.normal(0.0, start_position_uncertainty_km, n_members)
    lon_offset_km = rng.normal(0.0, start_position_uncertainty_km, n_members)
    lat0 = start_lat + lat_offset_km / METERS_PER_DEG_LAT * 1000.0
    lon0 = start_lon + lon_offset_km / _meters_per_deg_lon(np.full(n_members, start_lat)) * 1000.0

    current_bound = _error_bounds_for_horizon("current_u", horizon_hours)
    current_bound_v = _error_bounds_for_horizon("current_v", horizon_hours)
    current_bias_u = (
        rng.uniform(current_bound[0], current_bound[1], n_members) if current_bound else np.zeros(n_members)
    )
    current_bias_v = (
        rng.uniform(current_bound_v[0], current_bound_v[1], n_members)
        if current_bound_v
        else np.zeros(n_members)
    )

    wind_bound_u = _error_bounds_for_horizon("wind_u", horizon_hours)
    wind_bound_v = _error_bounds_for_horizon("wind_v", horizon_hours)
    wind_bias_u = rng.uniform(wind_bound_u[0], wind_bound_u[1], n_members) if wind_bound_u else np.zeros(n_members)
    wind_bias_v = rng.uniform(wind_bound_v[0], wind_bound_v[1], n_members) if wind_bound_v else np.zeros(n_members)

    stokes_factor = rng.uniform(*_STOKES_FACTOR_RANGE, n_members)

    if preset_used:
        alpha_members = np.clip(alpha * (1.0 + rng.normal(0.0, _ALPHA_JITTER_RELATIVE_STD, n_members)), 0.0, None)
    else:
        alpha_members = np.full(n_members, alpha)

    # --- integrate ---
    n_steps = max(1, round(horizon_hours * 3600.0 / DT_SECONDS))
    lat, lon = lat0.copy(), lon0.copy()
    at_time = resolved_start
    flags = {
        key: np.zeros(n_members, dtype=bool)
        for key in (
            "current_fell_back",
            "current_lost",
            "current_fallback_disabled",
            "stokes_fell_back",
            "stokes_lost",
            "stokes_fallback_disabled",
            "wind_lost",
        )
    }
    history_lat = [lat.copy()]
    history_lon = [lon.copy()]
    history_hours = [0.0]

    for step in range(1, n_steps + 1):
        lead_hours = (step - 1) * DT_SECONDS / 3600.0
        lat, lon = _rk4_step(
            at_time,
            lat,
            lon,
            DT_SECONDS,
            sources=sources,
            lead_hours=lead_hours,
            current_bias=(current_bias_u, current_bias_v),
            stokes_factor=stokes_factor,
            alpha=alpha_members,
            wind_bias=(wind_bias_u, wind_bias_v),
            flags=flags,
            allow_present_day_fallback=allow_present_day_fallback,
        )
        at_time = at_time + timedelta(seconds=DT_SECONDS)
        if step % _REPORT_STEP == 0 or step == n_steps:
            history_lat.append(lat.copy())
            history_lon.append(lon.copy())
            history_hours.append(step * DT_SECONDS / 3600.0)

    lat_track = np.stack(history_lat)  # (n_reports, n_members)
    lon_track = np.stack(history_lon)
    median_lat = np.nanmedian(lat_track, axis=1)
    median_lon = np.nanmedian(lon_track, axis=1)

    members = [
        {
            "track": [
                {"lat": round(float(lat_track[t, m]), 4), "lon": round(float(lon_track[t, m]), 4), "hour": history_hours[t]}
                for t in range(len(history_hours))
            ],
            "alpha_used": round(float(alpha_members[m]), 4),
        }
        for m in range(n_members)
    ]
    median_track = [
        {"lat": round(float(median_lat[t]), 4), "lon": round(float(median_lon[t]), 4), "hour": history_hours[t]}
        for t in range(len(history_hours))
    ]

    provenance = {
        "current": "live_forecast" if live_current is not None else "ml_grid_1deg_daily",
        "stokes": "live_forecast" if live_stokes is not None else "last_observed_nowcast_advected",
        "wind_leeway": "ml_grid_1deg_daily" if wind_available else ("not requested (alpha=0)" if alpha == 0.0 else "unavailable"),
    }

    return {
        "start": {"lat": start_lat, "lon": start_lon, "time": resolved_start.isoformat()},
        "horizon_hours": horizon_hours,
        "n_members": n_members,
        "leeway_alpha": alpha,
        "median_track": median_track,
        "members": members,
        "provenance": provenance,
        "degraded_terms": _degraded_terms(flags, n_members),
        "note": (
            f"A probability envelope from a {n_members}-member ensemble over perturbed start "
            "position, leeway and field error — not a prediction of where the object is. See "
            "provenance for which source backed each term."
        ),
    }
