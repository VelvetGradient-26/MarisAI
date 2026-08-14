"""The unified training pipeline. One implementation, every variable.

    history -> clean -> features -> rolling-origin CV -> final fit ->
    residual quantiles -> SHAP importance -> artifact

Nothing in this module branches on which variable it is training. The
differences between forecasting sea surface temperature and forecasting
chlorophyll are entirely expressed as config: a log transform, a different
covariate list, physical bounds, a shorter history where the product's
coverage demands it. That is what makes `--variable turbidity` work the day
someone adds a turbidity provider, with no code change here.

**A model is global, not per-location.** One LightGBM per (variable, horizon)
is fitted across every training point at once, with latitude, longitude,
ocean depth and basin as features. That is what lets it score an arbitrary
coordinate a user clicks on, rather than only the two dozen points it saw.
The alternative — a model per point — would be more accurate at those points
and useless everywhere else.

Prophet appears only as a **benchmark**. It is never saved and never served;
its job is to answer "is the tree actually beating a trend-plus-seasonality
fit?" during training, and to say so in `metrics.json`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from forecasting import ForecastingError
from forecasting.config import (
    BaselineConfig,
    ForecastingConfig,
    ModelConfig,
    VariableConfig,
    get_config,
)
from forecasting.evaluator import EvaluationError, cross_validate
from forecasting.feature_engineering import TARGET, TARGET_ANCHOR, build_features
from forecasting.history import HistoryError, HistoryRequest, fetch
from forecasting.preprocessing import TIMESTAMP, clean
from forecasting.registry import fetch_codes, resolve
from forecasting.shap_explainer import ExplainerError, ShapExplainer
from forecasting.uncertainty import fit_residual_quantiles
from services.download.models import Resolution

if TYPE_CHECKING:  # heavy import, only needed for the annotation
    from lightgbm import LGBMRegressor

logger = logging.getLogger(__name__)

MODEL_VERSION = "1.0.0"


class TrainingError(ForecastingError):
    """Training could not produce a usable model."""


@dataclass
class TrainingReport:
    """The outcome of one (variable, horizon) training run."""

    variable: str
    horizon: int
    rows: int
    points_used: list[str] = field(default_factory=list)
    points_skipped: list[dict[str, str]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    artifact_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "variable": self.variable,
            "horizon": self.horizon,
            "rows": self.rows,
            "points_used": self.points_used,
            "points_skipped": self.points_skipped,
            "metrics": self.metrics,
            "duration_seconds": round(self.duration_seconds, 2),
            "artifact_path": self.artifact_path,
        }


# --------------------------------------------------------------------------
# Model construction
# --------------------------------------------------------------------------


def build_model(config: ModelConfig) -> LGBMRegressor:
    """A configured LightGBM regressor.

    Isolated in one function so the "future hook" for ConvLSTM/TFT is a
    dispatch on `config.kind` here and nowhere else — the rest of the pipeline
    only requires something with `fit`/`predict`.
    """
    if config.kind != "lightgbm":
        raise TrainingError(f"unsupported model kind {config.kind!r}")

    from lightgbm import LGBMRegressor

    return LGBMRegressor(**config.to_lightgbm_params())


# --------------------------------------------------------------------------
# Target transform
# --------------------------------------------------------------------------


def _forward_transform(values: Any, log_transform: bool) -> np.ndarray:
    if not log_transform:
        return np.asarray(values, dtype="float64")
    # log1p, not log: these fields are non-negative and genuinely reach zero
    # (precipitation on a dry day), where log is undefined.
    return np.asarray(
        np.log1p(np.clip(np.asarray(values, dtype="float64"), 0.0, None)), dtype="float64"
    )


def _inverse_transform(values: Any, log_transform: bool) -> np.ndarray:
    values = np.asarray(values, dtype="float64")
    return np.asarray(np.expm1(values), dtype="float64") if log_transform else values


def encode_target(
    target_level: np.ndarray,
    anchor: np.ndarray,
    *,
    mode: str,
    log_transform: bool,
    circular: bool,
) -> np.ndarray:
    """What the model regresses on, from the observed future value.

    Paired with `decode_prediction`, which must invert it exactly. They are
    two functions rather than one flag threaded through the pipeline so that
    getting them out of step requires editing both — the same fit/apply
    discipline `machine_learning/` uses for climatologies.
    """
    if mode == "level":
        return _forward_transform(target_level, log_transform)

    if circular:
        # Signed angular change, wrapped into (-180, 180]. A raw subtraction
        # would make a 2-degree veer across north look like a 358-degree
        # reversal and teach the model nonsense.
        wrapped = (
            np.asarray(target_level, dtype="float64")
            - np.asarray(anchor, dtype="float64")
            + 180.0
        ) % 360.0 - 180.0
        return np.asarray(wrapped, dtype="float64")

    # For a log-transformed field the difference is taken in log space, so the
    # model learns a *ratio* of change rather than an absolute one. That is the
    # right scale for a field spanning three orders of magnitude: a 0.5 mg/m3
    # rise means something very different in a gyre than in an upwelling.
    return np.asarray(
        _forward_transform(target_level, log_transform)
        - _forward_transform(anchor, log_transform),
        dtype="float64",
    )


def decode_prediction(
    raw: np.ndarray,
    anchor: np.ndarray,
    *,
    mode: str,
    log_transform: bool,
    circular: bool,
) -> np.ndarray:
    """Turn the model's output back into a value in the variable's own units."""
    raw = np.asarray(raw, dtype="float64")
    anchor = np.asarray(anchor, dtype="float64")

    if mode == "level":
        return _inverse_transform(raw, log_transform)

    if circular:
        return np.asarray((anchor + raw) % 360.0, dtype="float64")

    return _inverse_transform(_forward_transform(anchor, log_transform) + raw, log_transform)


# --------------------------------------------------------------------------
# Dataset assembly
# --------------------------------------------------------------------------


async def _point_features(
    variable: VariableConfig,
    config: ForecastingConfig,
    key: str,
    latitude: float,
    longitude: float,
    horizon: int,
    history_days: int,
    resolution: Resolution,
    as_of: date | None = None,
) -> pd.DataFrame | None:
    """Build one location's feature rows, or None if its history is unusable."""
    codes = fetch_codes(variable)
    features_config = config.features_for(key)
    training = config.training_for(key)

    # `as_of` pins the snapshot the window is measured back from. Production
    # training leaves it None and gets "now", which is what a shipped model
    # wants. An offline experiment pins it so the window — and therefore the
    # history cache key — is identical across reruns on different days;
    # without it every rerun refetches two years from twenty-four points and
    # scores a slightly different dataset, which makes two runs incomparable.
    end = as_of or datetime.now(UTC).date()
    # The extra lookback is what keeps the earliest usable row from having a
    # third of its features NaN — see FeatureConfig.max_lookback_days.
    #
    # Padded by the *largest* configured horizon rather than this call's, so
    # every horizon of a variable requests an identical window and therefore
    # hits the same cache entry. Using `horizon` here shifted the start date
    # per horizon, which changed the cache key each time and silently re-fetched
    # all 24 points four times over — the fetch dominates a training run, so
    # that was most of its cost. A slightly longer window is free: the target
    # is constructed by shifting inside the frame, so the extra rows only ever
    # add training data.
    pad = max(config.horizons_for(key) or [horizon])
    start = end - timedelta(days=history_days + features_config.max_lookback_days + pad)

    series = await fetch(
        HistoryRequest(
            codes=codes,
            latitude=latitude,
            longitude=longitude,
            start_date=start,
            end_date=end,
            resolution=resolution,
        )
    )

    value_columns = [code for code in codes if code in series.frame.columns]
    cleaned, quality = clean(
        series.frame,
        value_columns,
        resolution=resolution,
        outliers=config.outliers_for(key),
    )

    if len(cleaned) < training.min_rows_per_point:
        logger.info(
            f"{key} @ {latitude},{longitude}: {len(cleaned)} rows < "
            f"{training.min_rows_per_point} required, skipping"
        )
        return None

    matrix = build_features(
        cleaned,
        variable,
        features_config,
        latitude=series.latitude,
        longitude=series.longitude,
        horizon=horizon,
    )

    frame = matrix.frame
    frame = frame.dropna(subset=[TARGET])
    if frame.empty:
        return None

    frame = frame.copy()
    frame.attrs["feature_columns"] = matrix.feature_columns
    frame.attrs["categorical_columns"] = matrix.categorical_columns
    frame.attrs["quality"] = quality.as_dict()
    return frame


async def assemble_training_set(
    key: str,
    horizon: int,
    config: ForecastingConfig | None = None,
    *,
    points: list[tuple[str, float, float]] | None = None,
    as_of: date | None = None,
) -> tuple[pd.DataFrame, list[str], list[str], list[str], list[dict[str, str]]]:
    """Fetch and featurise every training point, concatenated into one frame.

    A point whose history is too short, missing, or over land is skipped with
    a recorded reason rather than failing the run — coverage genuinely varies
    by variable and location, and losing one of twenty-four locations is not a
    reason to ship no model. Losing *all* of them is, and that raises.
    """
    config = config or get_config()
    variable = resolve(key, config)
    training = config.training_for(key)

    locations = points or [
        (point.name, point.latitude, point.longitude) for point in training.points
    ]
    if not locations:
        raise TrainingError(
            f"no training points configured for {key!r} — add them under "
            f"`defaults.training.points` in forecasting.yaml"
        )

    resolution = Resolution(training.resolution)

    async def one(
        name: str, latitude: float, longitude: float
    ) -> tuple[str, pd.DataFrame | None, str | None]:
        try:
            frame = await _point_features(
                variable, config, key, latitude, longitude, horizon,
                training.history_days, resolution, as_of,
            )
            return name, frame, None
        except (HistoryError, ForecastingError) as exc:
            return name, None, str(exc)

    # Sequential rather than gathered: every one of these is an upstream
    # Copernicus/Open-Meteo fetch, and twenty-four concurrent multi-year
    # requests is a good way to get rate-limited off the free tiers this
    # platform runs on. The disk cache makes the second run fast anyway.
    results = []
    for name, latitude, longitude in locations:
        results.append(await one(name, latitude, longitude))

    frames, used, skipped = [], [], []
    for name, frame, error in results:
        if frame is None:
            skipped.append({"point": name, "reason": error or "insufficient history"})
            continue
        frames.append(frame)
        used.append(name)

    if not frames:
        raise TrainingError(
            f"no usable training data for {key!r} at horizon {horizon} from any of "
            f"{len(locations)} points. First reasons: "
            f"{'; '.join(item['reason'] for item in skipped[:2])}"
        )

    feature_columns = frames[0].attrs["feature_columns"]
    categorical_columns = frames[0].attrs["categorical_columns"]

    combined = pd.concat(frames, ignore_index=True)
    # Sorting by time across all points is what makes rolling-origin CV
    # meaningful on a pooled multi-location frame: a fold's cutoff then
    # separates *dates*, so no location's future leaks into another's past.
    combined = combined.sort_values(TIMESTAMP).reset_index(drop=True)

    if len(combined) < config.training_for(key).min_total_rows:
        raise TrainingError(
            f"only {len(combined)} training rows for {key!r} h{horizon}, "
            f"below the configured minimum of {config.training_for(key).min_total_rows}. "
            f"A model fitted on this little data would be confidently wrong."
        )

    return combined, feature_columns, categorical_columns, used, skipped


# --------------------------------------------------------------------------
# Prophet benchmark
# --------------------------------------------------------------------------


def run_prophet_baseline(
    frame: pd.DataFrame, target_column: str, horizon: int, config: BaselineConfig
) -> dict[str, Any]:
    """Fit Prophet on the pooled series and score it the same way.

    Returns a dict with `available: False` and a reason when prophet is not
    installed, rather than raising — a missing optional benchmark must never
    fail a training run, and this codebase's rule is to state why something is
    absent instead of omitting it silently.
    """
    if not config.enabled:
        return {"available": False, "reason": "baseline disabled in configuration"}

    try:
        from prophet import Prophet
    except ImportError:
        return {
            "available": False,
            "reason": "prophet is not installed (`uv add prophet`); LightGBM "
            "metrics stand on their own, but no trend/seasonality comparison "
            "was made",
        }

    from forecasting.evaluator import chronological_split, compute_metrics

    # Prophet takes a univariate series, so the pooled multi-point frame is
    # collapsed to a daily mean. That makes it a genuinely weaker benchmark
    # than the tree, which is the point of a *sanity* baseline: if LightGBM
    # cannot beat this, something is wrong with the features.
    series = (
        frame.groupby(TIMESTAMP)[target_column]
        .mean()
        .reset_index()
        .rename(columns={TIMESTAMP: "ds", target_column: "y"})
    )

    train_index, test_index = chronological_split(series["ds"], 0.8, horizon)
    if len(test_index) < 5:
        return {"available": False, "reason": "series too short for a baseline split"}

    try:
        model = Prophet(
            yearly_seasonality=config.yearly_seasonality,
            weekly_seasonality=config.weekly_seasonality,
            daily_seasonality=config.daily_seasonality,
        )
        model.fit(series.iloc[train_index])
        forecast = model.predict(series.iloc[test_index][["ds"]])
        metrics = compute_metrics(
            series.iloc[test_index]["y"].to_numpy(), forecast["yhat"].to_numpy()
        )
    except Exception as exc:  # noqa: BLE001 - prophet/cmdstan raise widely
        return {"available": False, "reason": f"prophet baseline failed: {exc}"}

    return {"available": True, "model": "Prophet", "metrics": metrics}


# --------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------


async def train(
    key: str,
    horizon: int,
    config: ForecastingConfig | None = None,
    *,
    root: Path | None = None,
    save_artifact: bool = True,
    points: list[tuple[str, float, float]] | None = None,
) -> TrainingReport:
    """Train, validate and persist one (variable, horizon) model."""
    started = time.perf_counter()
    config = config or get_config()
    variable = resolve(key, config)

    frame, feature_columns, categorical_columns, used, skipped = await assemble_training_set(
        key, horizon, config, points=points
    )

    model_config = config.model_for(key)
    validation_config = config.defaults.validation

    mode = config.target_mode_for(key)

    X = frame[feature_columns]
    y_raw = frame[TARGET]
    # The persistence forecast: the variable's value at feature time. It is
    # both the delta target's anchor and the baseline every metric is scored
    # against, which is not a coincidence — a delta model that outputs zero
    # *is* persistence.
    anchor = frame[TARGET_ANCHOR]

    y = pd.Series(
        encode_target(
            y_raw.to_numpy(dtype="float64"),
            anchor.to_numpy(dtype="float64"),
            mode=mode,
            log_transform=variable.log_transform,
            circular=variable.circular,
        ),
        index=y_raw.index,
    )

    def fit_predict(
        X_train: pd.DataFrame, y_train: pd.Series, X_test: pd.DataFrame
    ) -> np.ndarray:
        model = build_model(model_config)
        model.fit(
            X_train,
            # y_train arrives as the raw future level (the evaluator scores in
            # real units), so it is re-encoded here against its own rows'
            # anchors rather than reusing `y` — the fold's indices are what
            # tie a target to the right anchor.
            encode_target(
                y_train.to_numpy(dtype="float64"),
                anchor.loc[y_train.index].to_numpy(dtype="float64"),
                mode=mode,
                log_transform=variable.log_transform,
                circular=variable.circular,
            ),
            categorical_feature=[c for c in categorical_columns if c in X_train.columns],
        )
        return decode_prediction(
            np.asarray(model.predict(X_test), dtype="float64"),
            anchor.loc[X_test.index].to_numpy(dtype="float64"),
            mode=mode,
            log_transform=variable.log_transform,
            circular=variable.circular,
        )

    # CV scores on the *original* scale, not the log scale: an RMSE in log
    # space is not a number anyone can act on, and the interval derived from
    # these residuals has to live in the units the API reports.
    try:
        validation = cross_validate(
            X,
            y_raw,
            frame[TIMESTAMP],
            fit_predict,
            horizon_steps=horizon,
            config=validation_config,
            circular=variable.circular,
            persistence=anchor,
        )
    except EvaluationError as exc:
        raise TrainingError(
            f"could not validate {key!r} h{horizon}: {exc}"
        ) from exc

    # Final fit on everything. The CV above is what the reported metrics come
    # from; this is the model that ships, and it legitimately sees all the
    # data because its score was already established out-of-sample.
    final_model = build_model(model_config)
    final_model.fit(
        X, y, categorical_feature=[c for c in categorical_columns if c in X.columns]
    )

    quantiles = fit_residual_quantiles(validation.residuals, config.defaults.uncertainty)

    importance: list[dict[str, Any]] = []
    try:
        explainer = ShapExplainer(final_model, feature_columns)
        # Sampled: exact TreeSHAP over 10k rows x 100 features is seconds of
        # work for a ranking that stabilises long before then.
        sample = X.sample(min(len(X), 500), random_state=42)
        importance = explainer.global_importance(sample)
    except ExplainerError as exc:
        logger.warning(f"global SHAP importance unavailable for {key} h{horizon}: {exc}")

    baseline = run_prophet_baseline(
        frame, variable.code, horizon, config.defaults.baseline
    )

    duration = time.perf_counter() - started

    metadata = {
        "version": MODEL_VERSION,
        "label": variable.label,
        "unit": variable.unit,
        "category": variable.category,
        "model_type": "LightGBM",
        "model_params": model_config.to_lightgbm_params(),
        "covariates": list(variable.covariates),
        # Persisted, not re-read from config at serve time: a model fitted on
        # deltas and decoded as a level would produce a number near zero and
        # look like a broken sensor. The artifact has to carry how to invert
        # its own output.
        "target_mode": mode,
        "log_transform": variable.log_transform,
        "circular": variable.circular,
        "valid_min": variable.valid_min,
        "valid_max": variable.valid_max,
        "resolution": config.training_for(key).resolution,
        "trained_at": datetime.now(UTC).isoformat(),
        "training_started": (
            pd.to_datetime(frame[TIMESTAMP].min()).date().isoformat()
        ),
        "training_ended": pd.to_datetime(frame[TIMESTAMP].max()).date().isoformat(),
        "training_rows": int(len(frame)),
        "training_points": used,
        "skipped_points": skipped,
        "feature_count": len(feature_columns),
        "training_duration_seconds": round(duration, 2),
        "residual_quantiles": quantiles.as_dict(),
    }

    metrics = {
        "validation": validation.as_dict(),
        "feature_importance": importance,
        "baseline": baseline,
    }

    artifact_path = None
    if save_artifact:
        from forecasting import model_store

        artifact_path = str(
            model_store.save(
                variable=key,
                horizon=horizon,
                model=final_model,
                feature_columns=feature_columns,
                categorical_columns=categorical_columns,
                metadata=metadata,
                metrics=metrics,
                root=root,
            )
        )

    return TrainingReport(
        variable=key,
        horizon=horizon,
        rows=len(frame),
        points_used=used,
        points_skipped=skipped,
        metrics=validation.metrics,
        duration_seconds=duration,
        artifact_path=artifact_path,
    )


async def train_variable(
    key: str,
    horizons: list[int] | None = None,
    config: ForecastingConfig | None = None,
    *,
    root: Path | None = None,
) -> list[TrainingReport]:
    """Train every configured horizon for one variable.

    Horizons run sequentially and share the history cache, so the second and
    later horizons cost the fit only — the fetch, which dominates, happens
    once. That sharing depends on `_point_features` padding its window by the
    variable's largest horizon rather than the current one; pad by the current
    horizon and each pass silently requests a different window, misses the
    cache, and refetches every point.
    """
    config = config or get_config()
    resolve(key, config)
    targets = horizons or config.horizons_for(key)

    reports = []
    for horizon in targets:
        try:
            report = await train(key, horizon, config, root=root)
            logger.info(
                f"trained {key} h{horizon}: MAE={report.metrics.get('mae')} "
                f"RMSE={report.metrics.get('rmse')} in {report.duration_seconds:.1f}s"
            )
            reports.append(report)
        except ForecastingError as exc:
            logger.error(f"training {key} h{horizon} failed: {exc}")
            reports.append(
                TrainingReport(
                    variable=key, horizon=horizon, rows=0,
                    metrics={"error": str(exc)},
                )
            )
    return reports
