"""Tests for the forecasting engine.

No network. Every test builds a synthetic series, so the suite runs in
seconds and its failures mean a code defect rather than a provider outage.
The one thing that genuinely cannot be tested offline — that the history
adapter agrees with the download providers — is covered by the fact that it
*is* the download providers, called through their own catalog.

The leakage tests are the load-bearing ones. Everything else here checks that
a function does what it says; those check that the engine cannot quietly start
scoring itself on information it would not have at inference time, which is
the failure mode that produces a confident, useless model.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from forecasting import feature_engineering as fe
from forecasting.api import _raise_for
from forecasting.config import (
    ConfigError,
    FeatureConfig,
    ForecastingConfig,
    OutlierConfig,
    UncertaintyConfig,
    VariableConfig,
    load_config,
)
from forecasting.evaluator import (
    EvaluationError,
    build_diagnostics,
    compute_metrics,
    rolling_origin_splits,
)
from forecasting.feature_engineering import (
    TARGET,
    TARGET_ANCHOR,
    FeatureError,
    add_forecast_target,
    add_lag_features,
    add_rolling_features,
    basin_label,
    build_features,
)
from forecasting.model_store import (
    ARTIFACT_VERSION,
    ModelNotTrainedError,
    ModelStoreError,
    list_trained,
    load,
    save,
)
from forecasting.preprocessing import (
    TIMESTAMP,
    QualityReport,
    clean,
    detect_outliers,
    fill_gaps,
    regularise,
)
from forecasting.registry import UnknownVariableError, UnsupportedHorizonError, validate_horizon
from forecasting.registry import resolve as resolve_variable
from forecasting.trainer import decode_prediction, encode_target
from forecasting.uncertainty import (
    ResidualQuantiles,
    UncertaintyError,
    bagged_interval,
    fit_residual_quantiles,
    interval_from_quantiles,
)
from services.download.models import Resolution

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def series() -> pd.DataFrame:
    """A year of daily data with a seasonal cycle plus noise."""
    dates = pd.date_range("2024-01-01", periods=400, freq="D")
    rng = np.random.default_rng(0)
    seasonal = 28.0 + 3.0 * np.sin(2 * np.pi * np.arange(400) / 365.25)
    return pd.DataFrame(
        {
            TIMESTAMP: dates,
            "sea_surface_temperature": seasonal + rng.normal(0, 0.3, 400),
            "wind_speed": 6.0 + rng.normal(0, 1.0, 400),
            "ocean_depth": 2100.0,
            "latitude": 15.0,
            "longitude": 65.0,
        }
    )


@pytest.fixture
def sst_variable() -> VariableConfig:
    return VariableConfig(
        code="sea_surface_temperature",
        covariates=["wind_speed"],
        valid_min=-2.0,
        valid_max=40.0,
    )


# --------------------------------------------------------------------------
# Leakage — the tests that matter most
# --------------------------------------------------------------------------


def test_only_one_forward_shift_exists_in_the_package():
    """No feature may look forward. Exactly one function may.

    A source scan rather than a behavioural check, because the property being
    protected is structural: it must stay true for features nobody has written
    yet. If this fails, either a new feature is reaching into the future or
    the target construction moved — both need a human decision, not a fix.
    """
    source = Path(fe.__file__).read_text()
    lines = source.splitlines()

    offenders = []
    inside_target_fn = False
    for number, line in enumerate(lines, start=1):
        if re.match(r"^def add_forecast_target\b", line):
            inside_target_fn = True
        elif re.match(r"^(def |class )", line):
            inside_target_fn = False
        # Match a negative shift in code, not in prose.
        is_forward_shift = re.search(r"\.shift\(\s*-", line) and not line.strip().startswith("#")
        if is_forward_shift and not inside_target_fn:
            offenders.append(f"line {number}: {line.strip()}")

    assert not offenders, (
        "forward shift found outside add_forecast_target — this is a leak:\n"
        + "\n".join(offenders)
    )


def test_target_is_the_future_value(series, sst_variable):
    matrix = build_features(
        series, sst_variable, FeatureConfig(), latitude=15.0, longitude=65.0, horizon=7
    )
    raw = series["sea_surface_temperature"].to_numpy()
    target = matrix.frame[TARGET].to_numpy()

    # Row i's target is the observation 7 steps later.
    assert np.allclose(raw[7:], target[:-7], equal_nan=False)
    # The last `horizon` rows have no future yet.
    assert np.isnan(target[-7:]).all()


def test_anchor_is_the_present_value(series, sst_variable):
    matrix = build_features(
        series, sst_variable, FeatureConfig(), latitude=15.0, longitude=65.0, horizon=3
    )
    assert np.allclose(
        matrix.frame[TARGET_ANCHOR].to_numpy(),
        series["sea_surface_temperature"].to_numpy(),
    )


def test_lag_features_look_backwards_only(series):
    frame = add_lag_features(series, ["sea_surface_temperature"], [1, 5])
    raw = series["sea_surface_temperature"].to_numpy()
    assert np.allclose(frame["sea_surface_temperature_lag1"].to_numpy()[1:], raw[:-1])
    assert np.allclose(frame["sea_surface_temperature_lag5"].to_numpy()[5:], raw[:-5])
    assert np.isnan(frame["sea_surface_temperature_lag5"].to_numpy()[:5]).all()


def test_rolling_window_never_includes_the_future(series):
    frame = add_rolling_features(series, ["sea_surface_temperature"], [5], ["mean"])
    raw = series["sea_surface_temperature"]
    # The window at row i covers rows i-4..i inclusive, and nothing later.
    expected = raw.iloc[6:11].mean()
    assert frame["sea_surface_temperature_roll5_mean"].iloc[10] == pytest.approx(expected)


def test_no_feature_perfectly_predicts_the_target(series, sst_variable):
    """A correlation of 1.0 with the target means a column leaked."""
    matrix = build_features(
        series, sst_variable, FeatureConfig(), latitude=15.0, longitude=65.0, horizon=7
    )
    usable = matrix.frame.dropna(subset=[TARGET])
    correlations = usable[matrix.feature_columns].corrwith(usable[TARGET]).abs()
    worst = correlations.dropna().max()
    assert worst < 0.999, f"a feature correlates {worst} with the target"


def test_zero_horizon_is_rejected(series):
    with pytest.raises(FeatureError, match="must be >= 1"):
        add_forecast_target(series, "sea_surface_temperature", 0)


def test_rolling_origin_splits_respect_the_embargo():
    timestamps = pd.Series(pd.date_range("2024-01-01", periods=400, freq="D"))
    for split in rolling_origin_splits(
        timestamps, n_splits=4, horizon_steps=7, min_train_fraction=0.4
    ):
        # No training row may fall within the embargo of the test window.
        assert split.train.max() < split.test.min() - 7
        assert len(np.intersect1d(split.train, split.test)) == 0


def test_rolling_origin_splits_are_chronological():
    timestamps = pd.Series(pd.date_range("2024-01-01", periods=300, freq="D"))
    splits = list(rolling_origin_splits(timestamps, n_splits=3, horizon_steps=3))
    assert len(splits) >= 2
    for split in splits:
        assert split.train.max() < split.test.min()
    # Training sets expand.
    sizes = [len(split.train) for split in splits]
    assert sizes == sorted(sizes)


def test_rolling_origin_rejects_a_series_that_is_too_short():
    timestamps = pd.Series(pd.date_range("2024-01-01", periods=10, freq="D"))
    with pytest.raises(EvaluationError):
        list(rolling_origin_splits(timestamps, n_splits=5, horizon_steps=30))


# --------------------------------------------------------------------------
# Preprocessing
# --------------------------------------------------------------------------


def test_regularise_restores_missing_timestamps():
    frame = pd.DataFrame(
        {
            TIMESTAMP: pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-06"]),
            "value": [1.0, 2.0, 6.0],
        }
    )
    report = QualityReport()
    result = regularise(frame, Resolution.daily, report)

    assert len(result) == 6
    assert report.rows_added_by_regularisation == 3
    # The hole is now visible as NaN instead of silently shifting the lags.
    assert result["value"].isna().sum() == 3


def test_cleaning_never_drops_rows():
    frame = pd.DataFrame(
        {
            TIMESTAMP: pd.date_range("2024-01-01", periods=50, freq="D"),
            "value": [float(i) for i in range(50)],
        }
    )
    frame.loc[10:12, "value"] = np.nan
    cleaned, report = clean(frame, ["value"], resolution=Resolution.daily)

    assert len(cleaned) == 50
    assert report.filled["value"] == 3
    assert cleaned["value"].isna().sum() == 0


def test_long_gaps_are_left_unfilled_rather_than_invented():
    values = pd.Series([1.0] * 5 + [np.nan] * 20 + [2.0] * 5)
    filled = fill_gaps(values, max_gap_steps=7)
    # Some edge filling happens, but the middle of a 20-step hole must not be
    # fabricated from a 7-step allowance.
    assert filled.isna().sum() > 0


def test_hampel_catches_a_local_spike_that_a_global_zscore_misses():
    """The case that decided the default.

    A seasonal series has a large *global* spread, so a spike that is glaring
    against its neighbours sits well inside three global standard deviations.
    A z-score filter, which compares against the whole series, cannot see it;
    the Hampel filter, which compares against a local median, can.
    """
    index = np.arange(300)
    rng = np.random.default_rng(1)
    seasonal = 20.0 + 10.0 * np.sin(2 * np.pi * index / 365.25)
    values = pd.Series(seasonal + rng.normal(0, 0.2, 300))
    # +4 against neighbours that vary by ~0.2, but only ~0.6 global sigma.
    values.iloc[150] += 4.0

    hampel = detect_outliers(values, OutlierConfig(method="hampel", threshold=3.0))
    zscore = detect_outliers(values, OutlierConfig(method="zscore", threshold=3.0))

    assert bool(hampel.iloc[150]), "hampel must flag a locally extreme value"
    assert not bool(zscore.iloc[150]), "the global z-score should miss it"


def test_outliers_are_replaced_not_dropped():
    frame = pd.DataFrame(
        {
            TIMESTAMP: pd.date_range("2024-01-01", periods=60, freq="D"),
            "value": [20.0] * 60,
        }
    )
    frame.loc[30, "value"] = 500.0
    cleaned, report = clean(frame, ["value"], outliers=OutlierConfig(method="hampel"))

    assert len(cleaned) == 60
    assert report.outliers_replaced["value"] == 1
    assert cleaned.loc[30, "value"] != 500.0


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------


def test_calendar_and_cyclical_features_are_present(series, sst_variable):
    matrix = build_features(
        series, sst_variable, FeatureConfig(), latitude=15.0, longitude=65.0, horizon=1
    )
    for column in ("month", "day", "week", "day_of_year", "quarter",
                   "doy_sin", "doy_cos", "month_sin", "month_cos"):
        assert column in matrix.feature_columns, f"{column} missing"


def test_cyclical_encoding_wraps_the_year(series, sst_variable):
    matrix = build_features(
        series, sst_variable, FeatureConfig(), latitude=15.0, longitude=65.0, horizon=1
    )
    frame = matrix.frame
    december = frame[frame[TIMESTAMP] == pd.Timestamp("2024-12-31")].iloc[0]
    january = frame[frame[TIMESTAMP] == pd.Timestamp("2024-01-01")].iloc[0]
    distance = np.hypot(
        december["doy_sin"] - january["doy_sin"],
        december["doy_cos"] - january["doy_cos"],
    )
    assert distance < 0.05, "31 Dec and 1 Jan must be adjacent on the circle"


def test_static_features_carry_position(series, sst_variable):
    matrix = build_features(
        series, sst_variable, FeatureConfig(), latitude=-33.0, longitude=18.0, horizon=1
    )
    assert matrix.frame["latitude"].iloc[0] == -33.0
    assert matrix.frame["abs_latitude"].iloc[0] == 33.0
    assert "basin" in matrix.categorical_columns


def test_circular_variable_uses_sin_cos_not_degrees(series):
    frame = series.rename(columns={"sea_surface_temperature": "wind_direction"})
    frame["wind_direction"] = np.linspace(0, 359, len(frame))
    variable = VariableConfig(code="wind_direction", covariates=[], circular=True)

    matrix = build_features(
        frame, variable, FeatureConfig(), latitude=15.0, longitude=65.0, horizon=1
    )
    assert "wind_direction" not in matrix.feature_columns
    assert "wind_direction_sin" in matrix.feature_columns
    assert "wind_direction_cos" in matrix.feature_columns


def test_missing_target_column_is_a_clear_error(series):
    variable = VariableConfig(code="nonexistent_variable", covariates=[])
    with pytest.raises(FeatureError, match="not in the series"):
        build_features(
            series, variable, FeatureConfig(), latitude=0.0, longitude=0.0, horizon=1
        )


@pytest.mark.parametrize(
    "latitude,longitude,expected",
    [
        (15.0, 65.0, "north_indian"),
        (-30.0, 80.0, "south_indian"),
        (36.0, -70.0, "north_atlantic"),
        (33.0, 140.0, "north_pacific"),
        (-70.0, 0.0, "southern_ocean"),
        (75.0, 0.0, "arctic"),
        (38.0, 15.0, "mediterranean"),
    ],
)
def test_basin_labels(latitude, longitude, expected):
    assert basin_label(latitude, longitude) == expected


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def test_metrics_on_a_perfect_forecast():
    actual = np.array([1.0, 2.0, 3.0, 4.0])
    metrics = compute_metrics(actual, actual)
    assert metrics["mae"] == 0.0
    assert metrics["rmse"] == 0.0
    assert metrics["r2"] == 1.0


def test_metrics_match_hand_computed_values():
    actual = np.array([10.0, 20.0, 30.0])
    predicted = np.array([12.0, 18.0, 33.0])
    metrics = compute_metrics(actual, predicted)
    # Metrics are rounded to 5 decimals on the way out, so compare absolutely.
    assert metrics["mae"] == pytest.approx((2 + 2 + 3) / 3, abs=1e-5)
    assert metrics["rmse"] == pytest.approx(np.sqrt((4 + 4 + 9) / 3), abs=1e-5)


def test_circular_error_wraps_around_north():
    actual = np.array([355.0, 5.0])
    predicted = np.array([5.0, 355.0])
    linear = compute_metrics(actual, predicted)
    circular = compute_metrics(actual, predicted, circular=True)
    assert linear["mae"] == pytest.approx(350.0)
    assert circular["mae"] == pytest.approx(10.0)


def test_skill_score_signals_which_side_of_persistence_a_model_falls():
    actual = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    persistence = np.array([10.5, 11.5, 12.5, 13.5, 14.5])  # off by 0.5

    worse = compute_metrics(actual, actual + 2.0, baseline=persistence)
    better = compute_metrics(actual, actual + 0.1, baseline=persistence)

    assert worse["skill_score"] < 0
    assert better["skill_score"] > 0


def test_skill_score_is_withheld_against_a_perfect_baseline():
    """Division by a zero baseline RMSE has no defensible value, so it is
    reported as absent rather than as infinity or zero."""
    actual = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    metrics = compute_metrics(actual, actual + 1.0, baseline=actual)
    assert metrics["skill_score"] is None


def test_mape_is_withheld_near_zero():
    actual = np.array([0.0, 0.0, 0.0, 1e-9, 0.0])
    predicted = np.array([0.1, 0.1, 0.1, 0.1, 0.1])
    metrics = compute_metrics(actual, predicted)
    assert metrics["mape"] is None


def test_diagnostics_produce_plottable_arrays():
    rng = np.random.default_rng(3)
    actual = rng.normal(20, 2, 300)
    predicted = actual + rng.normal(0, 0.5, 300)
    diagnostics = build_diagnostics(actual, predicted)

    assert diagnostics["prediction_vs_actual"]
    assert diagnostics["error_distribution"]
    assert diagnostics["residual_summary"]["std"] > 0
    assert set(diagnostics["prediction_vs_actual"][0]) == {"actual", "predicted"}


# --------------------------------------------------------------------------
# Target encoding
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["delta", "level"])
@pytest.mark.parametrize("log_transform", [False, True])
def test_encode_decode_round_trips(mode, log_transform):
    target = np.array([10.0, 20.0, 5.0, 30.0])
    anchor = np.array([9.0, 22.0, 6.0, 25.0])

    encoded = encode_target(
        target, anchor, mode=mode, log_transform=log_transform, circular=False
    )
    decoded = decode_prediction(
        encoded, anchor, mode=mode, log_transform=log_transform, circular=False
    )
    assert np.allclose(decoded, target)


def test_circular_delta_round_trips_across_north():
    target = np.array([5.0, 350.0])
    anchor = np.array([355.0, 10.0])
    encoded = encode_target(target, anchor, mode="delta", log_transform=False, circular=True)
    # A 10-degree veer, not a 350-degree one.
    assert np.allclose(np.abs(encoded), [10.0, 20.0])
    decoded = decode_prediction(
        encoded, anchor, mode="delta", log_transform=False, circular=True
    )
    assert np.allclose(decoded, target)


def test_delta_target_makes_persistence_the_zero_prediction():
    """The property that made delta targets worth switching to."""
    anchor = np.array([20.0, 21.0, 19.5])
    encoded = encode_target(
        anchor, anchor, mode="delta", log_transform=False, circular=False
    )
    assert np.allclose(encoded, 0.0)
    assert np.allclose(
        decode_prediction(
            np.zeros(3), anchor, mode="delta", log_transform=False, circular=False
        ),
        anchor,
    )


# --------------------------------------------------------------------------
# Uncertainty
# --------------------------------------------------------------------------


def test_interval_brackets_the_prediction():
    rng = np.random.default_rng(4)
    residuals = rng.normal(0, 1.0, 500)
    quantiles = fit_residual_quantiles(residuals, UncertaintyConfig(n_bootstrap=100))
    interval = interval_from_quantiles(25.0, quantiles)

    assert interval.lower < 25.0 < interval.upper
    # ~95% of a unit normal lies within +-1.96.
    assert 3.0 < (interval.upper - interval.lower) < 5.0


def test_interval_skews_the_correct_way_for_a_biased_model():
    """Residual is predicted - actual, so over-prediction lowers the interval."""
    residuals = np.full(200, 2.0)  # the model always predicts 2 too high
    quantiles = fit_residual_quantiles(residuals, UncertaintyConfig(n_bootstrap=50))
    interval = interval_from_quantiles(30.0, quantiles)
    assert interval.upper < 30.0 + 1e-6
    assert interval.lower == pytest.approx(28.0, abs=0.01)


def test_interval_respects_physical_bounds():
    residuals = np.random.default_rng(5).normal(0, 5.0, 200)
    quantiles = fit_residual_quantiles(residuals, UncertaintyConfig(n_bootstrap=50))
    interval = interval_from_quantiles(1.0, quantiles, valid_min=0.0)
    assert interval.lower >= 0.0


def test_too_few_residuals_falls_back_rather_than_fabricating():
    quantiles = fit_residual_quantiles(np.array([0.1, -0.2, 0.05]))
    assert quantiles.n_residuals == 3
    assert np.isfinite(quantiles.lower_offset)


def test_empty_residuals_is_an_error_not_a_zero_width_interval():
    with pytest.raises(UncertaintyError):
        fit_residual_quantiles(np.array([]))


def test_bagged_interval_reports_its_own_method():
    predictions = np.random.default_rng(6).normal(10, 1, 100)
    interval = bagged_interval(predictions)
    assert interval.method == "bagged_bootstrap"
    assert interval.lower < interval.upper


def test_residual_quantiles_survive_a_json_round_trip():
    original = fit_residual_quantiles(
        np.random.default_rng(7).normal(0, 1, 300), UncertaintyConfig(n_bootstrap=50)
    )
    restored = ResidualQuantiles.from_dict(original.as_dict())
    assert restored.lower_offset == pytest.approx(original.lower_offset, abs=1e-4)
    assert restored.confidence_level == original.confidence_level


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


def test_shipped_config_is_valid():
    config = load_config()
    assert config.variables
    assert config.defaults.training.points


def test_every_configured_variable_resolves_to_a_real_provider():
    """The check that keeps 'config-only extension' honest."""
    from services.download.registry import VARIABLE_REGISTRY

    config = load_config()
    for key, variable in config.variables.items():
        info = VARIABLE_REGISTRY.get(variable.code)
        assert info is not None, f"{key} names an unknown code"
        assert info.available, f"{key} names a code with no provider"


def test_config_rejects_an_unknown_variable_code():
    with pytest.raises(ValueError, match="not in the download registry"):
        ForecastingConfig.model_validate(
            {"variables": {"turbidity": {"code": "turbidity"}}}
        )


def test_config_rejects_a_variable_with_no_provider():
    # `ammonium` is in the registry but has available=False.
    with pytest.raises(ValueError, match="no provider yet"):
        ForecastingConfig.model_validate(
            {"variables": {"ammonium": {"code": "ammonium"}}}
        )


def test_config_rejects_a_self_referencing_covariate():
    with pytest.raises(ValueError, match="lists itself"):
        ForecastingConfig.model_validate(
            {
                "variables": {
                    "sst": {
                        "code": "sea_surface_temperature",
                        "covariates": ["sea_surface_temperature"],
                    }
                }
            }
        )


def test_variables_inherit_defaults():
    config = ForecastingConfig.model_validate(
        {
            "defaults": {"horizons": [1, 5]},
            "variables": {"sst": {"code": "sea_surface_temperature"}},
        }
    )
    assert config.horizons_for("sst") == [1, 5]
    assert config.features_for("sst").lags == FeatureConfig().lags


def test_a_variable_can_override_defaults():
    config = ForecastingConfig.model_validate(
        {
            "defaults": {"horizons": [1, 5]},
            "variables": {
                "sst": {"code": "sea_surface_temperature", "horizons": [30]}
            },
        }
    )
    assert config.horizons_for("sst") == [30]


def test_max_lookback_covers_every_window():
    features = FeatureConfig(lags=[1, 60], rolling_windows=[7], trend_windows=[90])
    assert features.max_lookback_days == 90


def test_missing_config_file_is_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_malformed_config_file_is_a_clear_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("variables: [this, is, a, list]")
    with pytest.raises(ConfigError):
        load_config(path)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_unknown_variable_names_the_alternatives():
    with pytest.raises(UnknownVariableError, match="Forecastable variables"):
        resolve_variable("not_a_variable")


def test_a_fetchable_but_unconfigured_variable_says_so():
    config = ForecastingConfig.model_validate({"variables": {}})
    with pytest.raises(UnknownVariableError, match="not configured for forecasting"):
        resolve_variable("sea_surface_temperature", config)


def test_supported_but_untrained_horizons_are_accepted_by_validation():
    """90 days is supported-but-untrained: it must not 422."""
    assert validate_horizon(90) == 90


def test_unsupported_horizon_is_rejected():
    with pytest.raises(UnsupportedHorizonError):
        validate_horizon(45)


# --------------------------------------------------------------------------
# Model store
# --------------------------------------------------------------------------


class _StubModel:
    def predict(self, X):
        return np.zeros(len(X))


def test_model_store_round_trip(tmp_path):
    save(
        variable="sea_surface_temperature",
        horizon=7,
        model=_StubModel(),
        feature_columns=["a", "b"],
        categorical_columns=["b"],
        metadata={"version": "1.0.0", "trained_at": "2026-01-01"},
        metrics={"validation": {"metrics": {"mae": 0.5}}},
        root=tmp_path,
    )

    artifact = load("sea_surface_temperature", 7, root=tmp_path)
    assert artifact.feature_columns == ["a", "b"]
    assert artifact.categorical_columns == ["b"]
    assert artifact.metrics["validation"]["metrics"]["mae"] == 0.5
    assert artifact.horizon == 7


def test_model_store_writes_all_four_files(tmp_path):
    save(
        variable="v", horizon=1, model=_StubModel(),
        feature_columns=["a"], categorical_columns=[],
        metadata={}, metrics={}, root=tmp_path,
    )
    directory = tmp_path / "v" / "h1"
    for name in ("model.pkl", "metadata.json", "metrics.json", "feature_columns.json"):
        assert (directory / name).exists(), f"{name} missing"


def test_loading_an_untrained_model_explains_how_to_train_it(tmp_path):
    with pytest.raises(ModelNotTrainedError, match="train_forecasting.py"):
        load("sea_surface_temperature", 7, root=tmp_path)


def test_artifact_version_mismatch_is_refused(tmp_path):
    save(
        variable="v", horizon=1, model=_StubModel(),
        feature_columns=["a"], categorical_columns=[],
        metadata={}, metrics={}, root=tmp_path,
    )
    path = tmp_path / "v" / "h1" / "metadata.json"
    import json

    payload = json.loads(path.read_text())
    payload["artifact_version"] = ARTIFACT_VERSION + 99
    path.write_text(json.dumps(payload))

    with pytest.raises(ModelStoreError, match="Retrain"):
        load("v", 1, root=tmp_path)


def test_list_trained_reports_horizons(tmp_path):
    for horizon in (1, 7, 30):
        save(
            variable="sst", horizon=horizon, model=_StubModel(),
            feature_columns=["a"], categorical_columns=[],
            metadata={}, metrics={}, root=tmp_path,
        )
    assert list_trained(tmp_path) == {"sst": [1, 7, 30]}


def test_saving_twice_replaces_rather_than_merges(tmp_path):
    save(
        variable="v", horizon=1, model=_StubModel(),
        feature_columns=["a", "b", "c"], categorical_columns=[],
        metadata={"run": "first"}, metrics={}, root=tmp_path,
    )
    save(
        variable="v", horizon=1, model=_StubModel(),
        feature_columns=["a"], categorical_columns=[],
        metadata={"run": "second"}, metrics={}, root=tmp_path,
    )
    artifact = load("v", 1, root=tmp_path)
    assert artifact.feature_columns == ["a"]
    assert artifact.metadata["run"] == "second"


# --------------------------------------------------------------------------
# History caching
# --------------------------------------------------------------------------


def test_the_same_window_is_one_cache_entry_regardless_of_coordinate_noise():
    """Coordinates are rounded into the cache key, since two points 0.001 deg
    apart resolve to the same model cell."""
    from forecasting.history import HistoryRequest

    base = {
        "codes": ("sea_surface_temperature",),
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 6, 1),
    }
    assert (
        HistoryRequest(latitude=15.0, longitude=65.0, **base).cache_key()
        == HistoryRequest(latitude=15.00001, longitude=65.00001, **base).cache_key()
    )
    assert (
        HistoryRequest(latitude=15.0, longitude=65.0, **base).cache_key()
        != HistoryRequest(latitude=16.0, longitude=65.0, **base).cache_key()
    )


def test_every_horizon_of_a_variable_requests_one_shared_window(monkeypatch):
    """The property that keeps training from refetching every point per horizon.

    Padding the fetch window by the *current* horizon instead of the largest
    configured one shifts the start date each pass, changes the cache key, and
    silently refetches all 24 points once per horizon — which is most of a
    training run's cost, since the fetch dominates.

    Asserted on the cache keys the trainer actually produces, not on the
    arithmetic, so the test still catches a regression if the expression moves.
    """
    import asyncio

    from forecasting import trainer as trainer_module
    from forecasting.history import HistorySeries

    config = load_config()
    key = "sea_surface_temperature"
    horizons = config.horizons_for(key)
    assert len(horizons) > 1, "this test needs a variable with several horizons"

    seen: list[str] = []

    async def recording_fetch(request, use_cache=True):
        seen.append(request.cache_key())
        # Enough rows to clear min_rows_per_point, so the caller proceeds.
        stamps = pd.date_range(request.start_date, request.end_date, freq="D")
        rng = np.random.default_rng(0)
        frame = pd.DataFrame(
            {
                TIMESTAMP: stamps,
                "sea_surface_temperature": 28.0 + rng.normal(0, 0.3, len(stamps)),
                "air_temperature": 27.0 + rng.normal(0, 0.5, len(stamps)),
                "wind_speed": 6.0 + rng.normal(0, 1.0, len(stamps)),
                "sea_surface_salinity": 35.0 + rng.normal(0, 0.1, len(stamps)),
                "ocean_depth": 2000.0,
                "latitude": 15.0,
                "longitude": 65.0,
            }
        )
        return HistorySeries(
            frame=frame, latitude=15.0, longitude=65.0,
            resolution=request.resolution, coverage={}, sources=["stub"],
        )

    monkeypatch.setattr(trainer_module, "fetch", recording_fetch)

    for horizon in horizons:
        asyncio.run(
            trainer_module._point_features(
                config.variables[key], config, key, 15.0, 65.0, horizon,
                config.training_for(key).history_days,
                Resolution(config.training_for(key).resolution),
            )
        )

    assert len(seen) == len(horizons)
    assert len(set(seen)) == 1, (
        f"each horizon requested a different window ({len(set(seen))} distinct "
        f"cache keys for {len(horizons)} horizons) — training will refetch "
        f"every point once per horizon"
    )


# --------------------------------------------------------------------------
# Retry classification
# --------------------------------------------------------------------------


def _wrapped(status: int) -> Exception:
    """A provider error wrapping an HTTP status, as the adapters raise them."""
    import httpx

    request = httpx.Request("GET", "https://example.invalid/")
    cause = httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(status, request=request)
    )
    try:
        raise RuntimeError("provider failed") from cause
    except RuntimeError as exc:
        return exc


@pytest.mark.parametrize("status", [400, 403, 410, 422])
def test_permanent_client_errors_are_not_retried(status):
    """The bug this classification exists to prevent.

    An upstream dataset answering 404 on every request was retried three times
    with backoff, adding ~8s to *every* forecast — turning a warm 6s response
    into 14.5s — for a dataset that was not going to reappear between attempt
    one and attempt three.
    """
    from forecasting.history import is_retryable

    assert not is_retryable(_wrapped(status))


def test_a_404_is_retried_exactly_once():
    """404 is the one ambiguous code, and the budget is what keeps it cheap.

    ERDDAP answers 404 "Currently unknown datasetID" while *reloading* a
    dataset, indistinguishably from one that was removed — both NOAA_DHW and
    GEBCO_2020 were observed 404ing for ~100s before returning to 200. So the
    first attempt retries, and every later one does not: a reload window
    recovers, while a genuinely dead dataset costs one 2s backoff rather than
    the 8s that the rule above exists to prevent.
    """
    from forecasting.history import is_retryable

    assert is_retryable(_wrapped(404), 0)
    assert not is_retryable(_wrapped(404), 1)
    assert not is_retryable(_wrapped(404), 2)


@pytest.mark.parametrize("status", [400, 403, 410, 422])
def test_the_404_budget_does_not_leak_into_other_client_errors(status):
    """A 400 stays permanent on attempt zero — only 404 is ambiguous."""
    from forecasting.history import is_retryable

    assert not is_retryable(_wrapped(status), 0)


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_transient_failures_are_retried(status):
    from forecasting.history import is_retryable

    assert is_retryable(_wrapped(status))


def test_a_timeout_is_retryable():
    import httpx

    from forecasting.history import is_retryable

    assert is_retryable(httpx.ReadTimeout("slow"))


def test_an_unrecognised_failure_is_assumed_transient():
    """One wasted attempt costs less than abandoning a real blip."""
    from forecasting.history import is_retryable

    assert is_retryable(RuntimeError("something unfamiliar"))


# --------------------------------------------------------------------------
# Error taxonomy
# --------------------------------------------------------------------------


def test_a_provider_outage_is_not_reported_as_a_bad_coordinate():
    """A GEBCO 503 and a point over land need opposite advice.

    Both used to surface as 404 "no data — the point may be over land", which
    sends a user to check coordinates that were never wrong.
    """
    from forecasting.history import HistoryError, ProviderUnavailableError

    assert issubclass(ProviderUnavailableError, HistoryError)

    with pytest.raises(HTTPException) as caught:
        _raise_for(ProviderUnavailableError("GEBCO returned status 503"))
    assert caught.value.status_code == 503
    assert caught.value.headers.get("Retry-After")

    with pytest.raises(HTTPException) as caught:
        _raise_for(HistoryError("No historical data — the point may be over land"))
    assert caught.value.status_code == 404


def test_an_untrained_model_is_a_404_that_says_how_to_train_it():
    with pytest.raises(HTTPException) as caught:
        _raise_for(ModelNotTrainedError("no trained model for 'x'. Train it with: ..."))
    assert caught.value.status_code == 404
    assert "Train it with" in caught.value.detail


def test_an_unsupported_horizon_is_422_not_404():
    with pytest.raises(HTTPException) as caught:
        _raise_for(UnsupportedHorizonError("Horizon 45 is not supported"))
    assert caught.value.status_code == 422


# --------------------------------------------------------------------------
# End-to-end on synthetic data (no network)
# --------------------------------------------------------------------------


def test_a_model_trains_and_beats_persistence_on_a_predictable_series():
    """A signal a tree should be able to learn, as a sanity check on the
    whole feature -> encode -> fit -> decode path."""
    from lightgbm import LGBMRegressor

    steps = 800
    index = np.arange(steps)
    rng = np.random.default_rng(11)
    # Strong annual cycle plus mild noise: the seasonal component is
    # predictable, so a model with calendar features must beat persistence.
    values = 20.0 + 6.0 * np.sin(2 * np.pi * index / 365.25) + rng.normal(0, 0.4, steps)

    frame = pd.DataFrame(
        {
            TIMESTAMP: pd.date_range("2023-01-01", periods=steps, freq="D"),
            "sea_surface_temperature": values,
            "ocean_depth": 1500.0,
        }
    )
    variable = VariableConfig(code="sea_surface_temperature", covariates=[])
    matrix = build_features(
        frame, variable, FeatureConfig(), latitude=10.0, longitude=70.0, horizon=7
    )
    usable = matrix.frame.dropna(subset=[TARGET, TARGET_ANCHOR])

    split = int(len(usable) * 0.7)
    train_rows, test_rows = usable.iloc[:split], usable.iloc[split + 7:]

    anchor_train = train_rows[TARGET_ANCHOR].to_numpy()
    anchor_test = test_rows[TARGET_ANCHOR].to_numpy()

    model = LGBMRegressor(n_estimators=200, learning_rate=0.05, verbosity=-1)
    model.fit(
        train_rows[matrix.feature_columns],
        encode_target(
            train_rows[TARGET].to_numpy(), anchor_train,
            mode="delta", log_transform=False, circular=False,
        ),
    )
    predicted = decode_prediction(
        model.predict(test_rows[matrix.feature_columns]), anchor_test,
        mode="delta", log_transform=False, circular=False,
    )

    metrics = compute_metrics(
        test_rows[TARGET].to_numpy(), predicted, baseline=anchor_test
    )
    assert metrics["skill_score"] > 0, (
        f"model must beat persistence on a strongly seasonal series, "
        f"got skill={metrics['skill_score']}"
    )
    assert metrics["r2"] > 0.8
