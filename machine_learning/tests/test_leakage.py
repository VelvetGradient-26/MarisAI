"""Tests for the properties that make the reported metrics trustworthy.

These are not tests of model quality — they are tests that the pipeline cannot
quietly cheat. Every one of them corresponds to a specific way this kind of
system reports skill it does not have:

* a "lag" feature that actually reads the future,
* a rolling window that includes the current timestep,
* a CV split whose train and test periods overlap or abut without an embargo,
* a spatial fold whose held-out points sit next to training points,
* a climatology or bloom threshold fitted on data the model is later scored on.

Run with:  PYTHONPATH=. .venv/bin/python -m pytest tests/ -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from marine_ml.features import temporal
from marine_ml.validation import metrics, splits


@pytest.fixture
def grid_frame() -> pd.DataFrame:
    """Two cells, 60 consecutive days, a strictly increasing value per cell.

    Monotonic values make time-direction errors impossible to miss: if a
    "backward" feature ever exceeds the current value, it read the future.
    """
    dates = pd.date_range("2021-01-01", periods=60, freq="D")
    rows = []
    for cell, (lat, lon) in enumerate([(10.0, 70.0), (12.0, 72.0)]):
        for step, date in enumerate(dates):
            rows.append(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "date": date,
                    "chl": float(step + 100 * cell),
                }
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Temporal features must never read forward
# --------------------------------------------------------------------------


def test_lag_features_look_backwards(grid_frame):
    result = temporal.add_lag_features(grid_frame, ["chl"], [3], freq_days=1)
    for _, cell in result.groupby(["latitude", "longitude"]):
        cell = cell.sort_values("date")
        expected = cell["chl"].shift(3)
        pd.testing.assert_series_equal(
            cell["chl_lag3"], expected, check_names=False
        )
        # And never exceeds the present value on a monotonic series.
        assert (cell["chl_lag3"].dropna() < cell["chl"][3:]).all()


def test_lag_features_do_not_cross_cells(grid_frame):
    """A cell's lag must come from its own history, not its neighbour's."""
    result = temporal.add_lag_features(grid_frame, ["chl"], [3], freq_days=1)
    for _, cell in result.groupby(["latitude", "longitude"]):
        cell = cell.sort_values("date")
        # First three rows of every cell have no history of their own.
        assert cell["chl_lag3"].head(3).isna().all()


def test_rolling_features_exclude_current_timestep(grid_frame):
    result = temporal.add_rolling_features(
        grid_frame, ["chl"], [7], freq_days=1, statistics=("mean",)
    )
    for _, cell in result.groupby(["latitude", "longitude"]):
        cell = cell.sort_values("date")
        rolled = cell["chl_roll7_mean"].dropna()
        current = cell["chl"].loc[rolled.index]
        # On a strictly increasing series, a trailing mean that excluded the
        # current value must be strictly below it.
        assert (rolled < current).all()


def test_difference_features_are_backward(grid_frame):
    result = temporal.add_difference_features(grid_frame, ["chl"])
    for _, cell in result.groupby(["latitude", "longitude"]):
        cell = cell.sort_values("date")
        # The first row of a cell has no predecessor of its own to difference
        # against — it must be NaN, not a value borrowed from another cell.
        assert pd.isna(cell["chl_delta"].iloc[0])
        # Increment is 1 per day within a cell, after the first row.
        assert np.allclose(cell["chl_delta"].dropna(), 1.0)


def test_cyclical_encoding_wraps_at_year_end():
    """31 Dec and 1 Jan must be neighbours, not opposite ends of a range."""
    dates = pd.Series(pd.to_datetime(["2021-12-31", "2022-01-01", "2021-07-01"]))
    encoded = temporal.cyclical_time_features(dates)

    def distance(a: int, b: int) -> float:
        return float(
            np.hypot(
                encoded["doy_sin"].iloc[a] - encoded["doy_sin"].iloc[b],
                encoded["doy_cos"].iloc[a] - encoded["doy_cos"].iloc[b],
            )
        )

    assert distance(0, 1) < 0.1          # new-year neighbours
    assert distance(0, 2) > distance(0, 1)  # midyear is far away


# --------------------------------------------------------------------------
# Climatology must be fit-then-apply, not fitted on everything
# --------------------------------------------------------------------------


def test_climatology_fitted_on_training_only_does_not_see_test(grid_frame):
    """The fitted mean must be the training rows' mean, not everyone's.

    Split mid-January so the January group straddles the boundary — if the fit
    leaked, its January mean would move toward the later, larger values.
    """
    cutoff = pd.Timestamp("2021-01-16")
    train = grid_frame[grid_frame["date"] < cutoff]

    climatology = temporal.fit_climatology(train, ["chl"])
    full_climatology = temporal.fit_climatology(grid_frame, ["chl"])

    january = climatology[climatology["month"] == 1].set_index(["latitude", "longitude"])
    january_full = full_climatology[full_climatology["month"] == 1].set_index(
        ["latitude", "longitude"]
    )

    expected = (
        train[train["date"].dt.month == 1]
        .groupby(["latitude", "longitude"])["chl"]
        .mean()
    )
    # Matches the training-only mean exactly ...
    pd.testing.assert_series_equal(
        january["chl_clim_mean"], expected, check_names=False
    )
    # ... and is strictly below the leaked all-rows mean, since the excluded
    # second half of January carries larger values.
    assert (january["chl_clim_mean"] < january_full["chl_clim_mean"]).all()


def test_anomalies_are_zero_mean_on_the_fitting_period(grid_frame):
    climatology = temporal.fit_climatology(grid_frame, ["chl"])
    applied = temporal.apply_climatology(grid_frame, climatology, ["chl"])
    assert abs(float(applied["chl_anomaly"].mean())) < 1e-9


# --------------------------------------------------------------------------
# Splitters
# --------------------------------------------------------------------------


def test_rolling_origin_train_always_precedes_test_with_a_gap(grid_frame):
    horizon = 7
    folds = list(
        splits.rolling_origin_splits(
            grid_frame["date"], n_splits=3, horizon_days=horizon
        )
    )
    assert folds, "expected at least one fold"

    dates = pd.to_datetime(grid_frame["date"]).reset_index(drop=True)
    for fold in folds:
        train_max = dates.iloc[fold.train].max()
        test_min = dates.iloc[fold.test].min()
        assert train_max < test_min
        assert (test_min - train_max) >= pd.Timedelta(days=horizon)


def test_rolling_origin_folds_do_not_overlap(grid_frame):
    for fold in splits.rolling_origin_splits(grid_frame["date"], n_splits=3):
        assert not set(fold.train) & set(fold.test)


def test_spatial_blocks_hold_out_whole_blocks():
    rng = np.random.default_rng(0)
    latitude = pd.Series(rng.uniform(0, 20, 2000))
    longitude = pd.Series(rng.uniform(60, 90, 2000))
    block_degrees = 3.0

    for fold in splits.spatial_block_splits(
        latitude, longitude, n_splits=4, block_degrees=block_degrees
    ):
        def blocks(index):
            return set(
                zip(
                    np.floor(latitude.iloc[index] / block_degrees).astype(int),
                    np.floor(longitude.iloc[index] / block_degrees).astype(int),
                )
            )

        # No block may appear on both sides of the split.
        assert not blocks(fold.train) & blocks(fold.test)


def test_chronological_split_is_ordered_and_partitions(grid_frame):
    train, validation, test = splits.chronological_split(grid_frame["date"])
    assert (train.astype(int) + validation.astype(int) + test.astype(int) == 1).all()

    dates = pd.to_datetime(grid_frame["date"]).reset_index(drop=True)
    assert dates[train].max() <= dates[validation].min()
    assert dates[validation].max() <= dates[test].min()


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def test_boyce_index_is_high_for_a_good_model_and_low_for_noise():
    rng = np.random.default_rng(1)
    presence = rng.beta(5, 2, 500)      # concentrated at high suitability
    background = rng.beta(2, 5, 5000)   # concentrated at low
    assert metrics.boyce_index(presence, background) > 0.7

    noise_presence = rng.uniform(0, 1, 500)
    noise_background = rng.uniform(0, 1, 5000)
    assert abs(metrics.boyce_index(noise_presence, noise_background)) < 0.6


def test_tss_is_zero_for_a_constant_predictor():
    y = np.array([1, 0, 1, 0, 1, 0])
    scores = np.full(6, 0.5)
    assert metrics.true_skill_statistic(y, scores, 0.5) == pytest.approx(0.0)


def test_mess_is_negative_outside_the_training_envelope():
    training = pd.DataFrame({"sst": np.linspace(20, 30, 200)})
    projection = pd.DataFrame({"sst": [25.0, 35.0, 10.0]})
    similarity = metrics.mess(training, projection)

    assert similarity.iloc[0] > 0     # inside the envelope
    assert similarity.iloc[1] < 0     # above it -> extrapolating
    assert similarity.iloc[2] < 0     # below it -> extrapolating


def test_evaluate_classification_returns_nan_for_single_class_folds():
    y = np.zeros(50, dtype=int)
    scores = np.random.default_rng(0).uniform(0, 1, 50)
    report = metrics.evaluate_classification(y, scores)
    # Silently returning 0.5 or 0.0 here would poison every fold average.
    assert np.isnan(report.roc_auc)
    assert np.isnan(report.pr_auc)


def test_threshold_for_recall_achieves_the_requested_recall():
    rng = np.random.default_rng(2)
    y = rng.binomial(1, 0.1, 3000)
    scores = np.clip(0.1 + 0.6 * y + rng.normal(0, 0.2, 3000), 0, 1)

    threshold = metrics.threshold_for_recall(y, scores, target_recall=0.8)
    _, recall = metrics.precision_recall_at_threshold(y, scores, threshold)
    assert recall >= 0.8


# --------------------------------------------------------------------------
# Wind-driven upwelling physics
# --------------------------------------------------------------------------


def _stress_field(tau_x_value: float, tau_y_value: float) -> tuple:
    """Uniform stress field on a small northern-hemisphere grid."""
    import xarray as xr

    lats = np.array([10.0, 15.0, 20.0])
    lons = np.array([70.0, 72.0, 74.0])
    shape = (len(lats), len(lons))
    coords = {"latitude": lats, "longitude": lons}
    dims = ("latitude", "longitude")
    tau_x = xr.DataArray(np.full(shape, tau_x_value), coords=coords, dims=dims)
    tau_y = xr.DataArray(np.full(shape, tau_y_value), coords=coords, dims=dims)
    return tau_x, tau_y


def test_upwelling_index_sign_matches_the_physics():
    """On a north-south coast, southward wind stress upwells (NH).

    Positive index means offshore Ekman transport. With coast_angle_deg=0 the
    alongshore component is tau_y, and f > 0 north of the equator, so the sign
    of the index follows the sign of tau_y.
    """
    from marine_ml.features import geometry

    northward_tau_x, northward_tau_y = _stress_field(0.0, 0.1)
    southward_tau_x, southward_tau_y = _stress_field(0.0, -0.1)

    up = geometry.upwelling_index_from_stress(northward_tau_x, northward_tau_y)
    down = geometry.upwelling_index_from_stress(southward_tau_x, southward_tau_y)

    assert float(up.mean()) > 0      # upwelling-favourable
    assert float(down.mean()) < 0    # downwelling-favourable


def test_upwelling_index_is_masked_at_the_equator():
    """f -> 0 at the equator, so the index must be NaN there, not infinite."""
    import xarray as xr
    from marine_ml.features import geometry

    lats = np.array([-1.0, 0.0, 1.0, 15.0])
    lons = np.array([70.0])
    coords = {"latitude": lats, "longitude": lons}
    dims = ("latitude", "longitude")
    tau = xr.DataArray(np.full((4, 1), 0.1), coords=coords, dims=dims)

    index = geometry.upwelling_index_from_stress(tau, tau)
    values = index.values.ravel()
    assert np.isnan(values[:3]).all()      # equatorial band masked
    assert np.isfinite(values[3])          # 15N is fine
    assert not np.isinf(values).any()


def test_ekman_pumping_sign_matches_the_physics():
    """Positive stress curl upwells in the northern hemisphere."""
    import xarray as xr
    from marine_ml.features import geometry

    coords = {"latitude": np.array([10.0, 20.0]), "longitude": np.array([70.0])}
    dims = ("latitude", "longitude")
    positive_curl = xr.DataArray(np.full((2, 1), 1e-6), coords=coords, dims=dims)
    negative_curl = xr.DataArray(np.full((2, 1), -1e-6), coords=coords, dims=dims)

    assert float(geometry.ekman_pumping(positive_curl).mean()) > 0
    assert float(geometry.ekman_pumping(negative_curl).mean()) < 0


def test_stress_based_and_bulk_formula_indices_agree_in_sign():
    """The two upwelling_index entry points must not disagree directionally.

    They differ in magnitude (one assumes a drag coefficient), but a wind that
    upwells must not become a wind that downwells just because stress was
    derived rather than observed.
    """
    from marine_ml.features import geometry

    wind_u, wind_v = _stress_field(0.0, 8.0)  # southerly wind, 8 m/s
    from_wind = geometry.upwelling_index(wind_u, wind_v)

    tau_x, tau_y = geometry.wind_stress(wind_u, wind_v)
    from_stress = geometry.upwelling_index_from_stress(tau_x, tau_y)

    assert np.sign(float(from_wind.mean())) == np.sign(float(from_stress.mean()))
    # Same code path once stress exists, so these must match exactly.
    assert np.allclose(from_wind.values, from_stress.values, equal_nan=True)


def test_training_stride_drops_whole_days_not_cells(grid_frame):
    """Striding must keep complete spatial fields, and must not touch dates
    outside its own selection rule."""
    from hab_early_warning.src.train import _strided

    strided = _strided(grid_frame, stride=2)

    # Every retained date keeps all of its cells.
    per_date = strided.groupby("date").size()
    assert (per_date == grid_frame.groupby("date").size().max()).all()

    # Roughly half the dates survive, and the rule is deterministic.
    kept = set(strided["date"].unique())
    assert 0.4 < len(kept) / grid_frame["date"].nunique() < 0.6
    assert _strided(grid_frame, stride=2)["date"].equals(strided["date"])

    # stride=1 is a no-op.
    assert len(_strided(grid_frame, stride=1)) == len(grid_frame)


# --------------------------------------------------------------------------
# Fusion must not silently lose timesteps
# --------------------------------------------------------------------------


def _synthetic_sources(n_days: int, wind_days: int | None = None):
    """Minimal physics/bgc/bathymetry/wind datasets on a tiny grid."""
    import xarray as xr

    lats = np.array([10.0, 10.25, 10.5])
    lons = np.array([70.0, 70.25, 70.5])
    times = pd.date_range("2020-01-01", periods=n_days, freq="D")
    shape = (n_days, len(lats), len(lons))
    coords = {"time": times, "latitude": lats, "longitude": lons}
    dims = ("time", "latitude", "longitude")

    def field(value):
        return xr.DataArray(np.full(shape, value), coords=coords, dims=dims)

    physics = xr.Dataset(
        {n: field(v) for n, v in
         [("thetao", 28.0), ("so", 35.0), ("uo", 0.1), ("vo", 0.1),
          ("zos", 0.5), ("mlotst", 20.0)]}
    )
    bgc = xr.Dataset(
        {n: field(v) for n, v in
         [("chl", 0.2), ("no3", 1.0), ("po4", 0.1), ("si", 2.0),
          ("o2", 200.0), ("nppv", 10.0)]}
    )

    bathy_coords = {"latitude": lats, "longitude": lons}
    bathymetry = xr.Dataset(
        {
            "depth": xr.DataArray(np.full((3, 3), 1000.0), coords=bathy_coords,
                                  dims=("latitude", "longitude")),
            "elevation": xr.DataArray(np.full((3, 3), -1000.0), coords=bathy_coords,
                                      dims=("latitude", "longitude")),
        }
    )

    wind = None
    if wind_days is not None:
        wtimes = times[:wind_days]
        wshape = (wind_days, len(lats), len(lons))
        wcoords = {"time": wtimes, "latitude": lats, "longitude": lons}
        wind = xr.Dataset(
            {n: xr.DataArray(np.full(wshape, v), coords=wcoords, dims=dims)
             for n, v in [("eastward_stress", 0.05), ("northward_stress", 0.05),
                          ("stress_curl", 1e-7), ("eastward_wind", 5.0),
                          ("northward_wind", 5.0)]}
        )
    return physics, bgc, bathymetry, wind


def test_fusion_rejects_a_covariate_that_would_truncate_the_record():
    """A short wind fetch must fail loudly, not silently shrink the store."""
    from marine_ml import config, fusion

    region = config.Region("test", west=69.9, east=70.6, south=9.9, north=10.6)
    physics, bgc, bathymetry, wind = _synthetic_sources(n_days=30, wind_days=10)

    with pytest.raises(fusion.FusionError, match="dropped"):
        fusion.build_gridded_frame(
            physics, bgc, bathymetry, region=region, resolution=0.25, wind=wind
        )


def test_fusion_accepts_matching_windows_and_omitted_wind():
    from marine_ml import config, fusion

    region = config.Region("test", west=69.9, east=70.6, south=9.9, north=10.6)
    physics, bgc, bathymetry, wind = _synthetic_sources(n_days=30, wind_days=30)

    with_wind = fusion.build_gridded_frame(
        physics, bgc, bathymetry, region=region, resolution=0.25, wind=wind
    )
    assert "upwelling_index" in with_wind.columns
    assert "ekman_pumping" in with_wind.columns

    without_wind = fusion.build_gridded_frame(
        physics, bgc, bathymetry, region=region, resolution=0.25
    )
    assert "upwelling_index" not in without_wind.columns
    # Omitting an optional covariate must not change the row count.
    assert len(with_wind) == len(without_wind)
