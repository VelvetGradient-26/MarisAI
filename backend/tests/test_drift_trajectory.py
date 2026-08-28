"""services/drift_trajectory.py: RK4 ensemble integration + source fallback.

No network is touched: `_fetch_live_field` and `_ml_grid_field` are
monkeypatched to serve synthetic fields, the same convention `test_routing.py`
uses for its own live-fetch seams. `_error_bounds_for_horizon` is also
monkeypatched to `None` in the pure-integrator tests, so the assertions are
about the RK4 scheme itself rather than incidentally about real trained
models' residual quantiles (which do get exercised for real by
`test_reads_real_residual_quantiles_when_present`, the one test that touches
the actual `models/forecasting/` artifacts already on disk in this repo).
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
import xarray as xr
from scipy.interpolate import RegularGridInterpolator

from services import drift_trajectory


@pytest.fixture(autouse=True)
def _clear_ml_grid_sampler_cache():
    """`_cached_sampler` is a module-level `lru_cache` — without this, a grid
    monkeypatched by one test would keep answering a later test that
    monkeypatches a different one."""
    drift_trajectory.clear_cache()
    yield
    drift_trajectory.clear_cache()


def _constant_live_field(u_value: float, v_value: float) -> drift_trajectory._LiveField:
    """A `_LiveField` that returns exactly (u_value, v_value) everywhere and
    at every time — `fill_value` is the constant itself, not NaN, so this
    never triggers the fallback path unless a test wants it to."""
    axis = np.array([-1.0e7, 1.0e7])
    lat = np.array([-90.0, 90.0])
    lon = np.array([-180.0, 180.0])
    u_grid = np.full((2, 2, 2), u_value)
    v_grid = np.full((2, 2, 2), v_value)
    return drift_trajectory._LiveField(
        u_interp=RegularGridInterpolator((axis, lat, lon), u_grid, bounds_error=False, fill_value=u_value),
        v_interp=RegularGridInterpolator((axis, lat, lon), v_grid, bounds_error=False, fill_value=v_value),
        t0=datetime(2020, 1, 1, tzinfo=UTC),
    )


def _install_live_fields(monkeypatch, current, stokes):
    async def fake_fetch_live_field(label, *_args, **_kwargs):
        return {"current": current, "stokes_drift": stokes}[label]

    monkeypatch.setattr(drift_trajectory, "_fetch_live_field", fake_fetch_live_field)


def _disable_measured_error_bounds(monkeypatch):
    """No field-error perturbation, so a test's own displacement arithmetic
    does not have to also reproduce real residual-quantile numbers."""
    monkeypatch.setattr(drift_trajectory, "_error_bounds_for_horizon", lambda variable, horizon_hours: None)


def _synthetic_ml_field(value: float) -> xr.DataArray:
    lat = np.linspace(-89.5, 89.5, 10)
    lon = np.linspace(-179.5, 179.5, 10)
    return xr.DataArray(
        np.full((10, 10), value),
        dims=("latitude", "longitude"),
        coords={"latitude": lat, "longitude": lon},
    )


@pytest.mark.asyncio
async def test_uniform_eastward_current_drifts_in_a_straight_line(monkeypatch):
    """A constant current with no meridional component leaves latitude (and
    therefore the metres-per-degree-longitude scale factor) unchanged for the
    whole run, so RK4 integrates a genuinely constant derivative — exact, not
    approximate. This is the "known analytic drift" check the plan calls for."""
    u0 = 0.5  # m/s eastward
    _install_live_fields(monkeypatch, _constant_live_field(u0, 0.0), _constant_live_field(0.0, 0.0))
    _disable_measured_error_bounds(monkeypatch)

    horizon_hours = 12.0
    result = await drift_trajectory.plan_trajectory(
        10.0, 70.0, alpha=0.0, preset_used=False,
        horizon_hours=horizon_hours, n_members=drift_trajectory.MIN_MEMBERS,
        start_position_uncertainty_km=0.0,
        rng=np.random.default_rng(0),
    )

    expected_lon_drift = (u0 * horizon_hours * 3600.0) / drift_trajectory._meters_per_deg_lon(np.array([10.0]))[0]
    final = result["median_track"][-1]
    assert final["lat"] == pytest.approx(10.0, abs=1e-6)
    assert final["lon"] == pytest.approx(70.0 + expected_lon_drift, abs=1e-3)
    assert result["provenance"] == {
        "current": "live_forecast",
        "stokes": "live_forecast",
        "wind_leeway": "not requested (alpha=0)",
    }
    assert result["degraded_terms"] == []


@pytest.mark.asyncio
async def test_water_only_never_touches_wind_grids(monkeypatch):
    """alpha=0 must skip wind I/O entirely, not just zero its contribution —
    a request for `_ml_grid_field("wind_u", ...)` here is a test failure."""
    _install_live_fields(monkeypatch, _constant_live_field(0.1, 0.0), _constant_live_field(0.0, 0.0))
    _disable_measured_error_bounds(monkeypatch)

    def _fail_if_called(variable, horizon_days):
        if variable.startswith("wind"):
            raise AssertionError("wind grid requested for an alpha=0 request")
        return _synthetic_ml_field(0.0)

    monkeypatch.setattr(drift_trajectory, "_ml_grid_field", _fail_if_called)

    result = await drift_trajectory.plan_trajectory(
        10.0, 70.0, alpha=0.0, preset_used=True,
        horizon_hours=6.0, n_members=drift_trajectory.MIN_MEMBERS,
        rng=np.random.default_rng(1),
    )
    assert all(m["alpha_used"] == 0.0 for m in result["members"])
    assert result["provenance"]["wind_leeway"] == "not requested (alpha=0)"


@pytest.mark.asyncio
async def test_live_current_failure_falls_back_to_ml_grid_and_reports_it(monkeypatch):
    async def fake_fetch_live_field(label, *_args, **_kwargs):
        return None  # both live fetches "fail"

    monkeypatch.setattr(drift_trajectory, "_fetch_live_field", fake_fetch_live_field)
    monkeypatch.setattr(drift_trajectory, "_ml_grid_field", lambda variable, horizon_days: _synthetic_ml_field(0.2))
    _disable_measured_error_bounds(monkeypatch)

    result = await drift_trajectory.plan_trajectory(
        10.0, 70.0, alpha=0.0, preset_used=False,
        horizon_hours=6.0, n_members=drift_trajectory.MIN_MEMBERS,
        rng=np.random.default_rng(2),
    )

    assert result["provenance"]["current"] == "ml_grid_1deg_daily"
    assert result["provenance"]["stokes"] == "last_observed_nowcast_advected"
    assert any("current" in note for note in result["degraded_terms"])


@pytest.mark.asyncio
async def test_no_current_source_at_all_raises(monkeypatch):
    async def fake_fetch_live_field(label, *_args, **_kwargs):
        return None

    monkeypatch.setattr(drift_trajectory, "_fetch_live_field", fake_fetch_live_field)
    monkeypatch.setattr(drift_trajectory, "_ml_grid_field", lambda variable, horizon_days: None)

    with pytest.raises(drift_trajectory.DriftTrajectoryError):
        await drift_trajectory.plan_trajectory(
            10.0, 70.0, alpha=0.0, preset_used=False, horizon_hours=6.0, rng=np.random.default_rng(3)
        )


@pytest.mark.asyncio
async def test_start_position_uncertainty_spreads_the_ensemble(monkeypatch):
    _install_live_fields(monkeypatch, _constant_live_field(0.1, 0.0), _constant_live_field(0.0, 0.0))
    _disable_measured_error_bounds(monkeypatch)

    result = await drift_trajectory.plan_trajectory(
        10.0, 70.0, alpha=0.0, preset_used=False,
        horizon_hours=6.0, n_members=50,
        start_position_uncertainty_km=5.0,
        rng=np.random.default_rng(4),
    )
    start_lats = [m["track"][0]["lat"] for m in result["members"]]
    assert np.std(start_lats) > 0.0  # a real spread, not every member on the same point


@pytest.mark.asyncio
async def test_named_preset_jitters_alpha_but_explicit_alpha_does_not(monkeypatch):
    _install_live_fields(monkeypatch, _constant_live_field(0.1, 0.0), _constant_live_field(0.0, 0.0))
    _disable_measured_error_bounds(monkeypatch)
    monkeypatch.setattr(drift_trajectory, "_ml_grid_field", lambda variable, horizon_days: _synthetic_ml_field(0.0))

    preset_result = await drift_trajectory.plan_trajectory(
        10.0, 70.0, alpha=0.06, preset_used=True,
        horizon_hours=3.0, n_members=50,
        rng=np.random.default_rng(5),
    )
    explicit_result = await drift_trajectory.plan_trajectory(
        10.0, 70.0, alpha=0.06, preset_used=False,
        horizon_hours=3.0, n_members=50,
        rng=np.random.default_rng(5),
    )
    preset_alphas = {m["alpha_used"] for m in preset_result["members"]}
    explicit_alphas = {m["alpha_used"] for m in explicit_result["members"]}
    assert len(preset_alphas) > 1  # jittered
    assert explicit_alphas == {0.06}  # not jittered


def test_reads_real_residual_quantiles_when_present():
    """The one test against the real, already-trained artifacts in
    `models/forecasting/` — confirms `_error_bounds_for_horizon` actually
    reaches `forecasting.model_store.describe` and gets real numbers back,
    not just that the mocked path works."""
    bounds = drift_trajectory._error_bounds_for_horizon("current_u", horizon_hours=24.0)
    assert bounds is not None
    lower, upper = bounds
    assert lower < 0 < upper


def test_ml_grid_bracket_endpoints_and_interior():
    assert drift_trajectory._ml_grid_bracket(0.0) == (0, 0, 0.0)
    assert drift_trajectory._ml_grid_bracket(24.0 * 30) == (7, 30, 1.0)
    lo, hi, fraction = drift_trajectory._ml_grid_bracket(48.0)  # 2 days: between h1 and h3
    assert (lo, hi) == (1, 3)
    assert 0.0 < fraction < 1.0
