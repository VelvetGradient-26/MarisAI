"""Inference: turn a (variable, point, horizon) request into a forecast with
an interval, drivers and a trend.

The critical property is that this module builds features with **the same
function the trainer used**, from the same config, and then reindexes them to
the exact column order recorded in `feature_columns.json`. Train/serve skew —
a feature computed slightly differently at inference, or columns in a
different order — produces predictions that are wrong in a way no test on the
training set can catch, and it is the single most common way a working model
becomes a broken product.

Loaded models are cached for the process lifetime. They are a few hundred KB
and change only when a training run rewrites them, so the alternative would be
unpickling a forest on every request.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from forecasting import ForecastingError
from forecasting.config import ForecastingConfig, get_config
from forecasting.feature_engineering import build_features
from forecasting.history import (
    HistoryRequest,
    HistorySeries,
    ProviderUnavailableError,
    fetch,
)
from forecasting.model_store import ModelArtifact, load
from forecasting.preprocessing import TIMESTAMP, clean
from forecasting.registry import fetch_codes, resolve, validate_horizon
from forecasting.shap_explainer import (
    ExplainerError,
    FeatureContribution,
    ShapExplainer,
    summarise_drivers,
)
from forecasting.trainer import decode_prediction
from forecasting.uncertainty import Interval, ResidualQuantiles, interval_from_quantiles
from services.download.models import Resolution

logger = logging.getLogger(__name__)


class PredictionError(ForecastingError):
    """A forecast could not be produced."""


# --------------------------------------------------------------------------
# Model cache
# --------------------------------------------------------------------------

_cache: dict[tuple[str, int, str], tuple[ModelArtifact, ShapExplainer | None]] = {}
_cache_lock = threading.Lock()


def _load_cached(
    variable: str, horizon: int, root: Path | None
) -> tuple[ModelArtifact, ShapExplainer | None]:
    key = (variable, horizon, str(root or ""))
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached

    artifact = load(variable, horizon, root)

    explainer: ShapExplainer | None = None
    try:
        explainer = ShapExplainer(artifact.model, artifact.feature_columns)
    except ExplainerError as exc:
        # A forecast without an explanation is still a forecast. Degrade, and
        # let the response say the explanation is missing rather than 500.
        logger.warning(f"explanations unavailable for {variable} h{horizon}: {exc}")

    with _cache_lock:
        _cache[key] = (artifact, explainer)
    return artifact, explainer


def clear_model_cache() -> None:
    """Drop cached models — call after retraining in a long-lived process."""
    with _cache_lock:
        _cache.clear()


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------


@dataclass
class Forecast:
    """One prediction and everything that justifies it."""

    variable: str
    label: str
    unit: str
    latitude: float
    longitude: float
    horizon: int
    target_time: datetime
    prediction: float
    interval: Interval
    trend: str
    trend_delta: float
    last_observed: float | None
    last_observed_time: datetime | None
    drivers: list[FeatureContribution] = field(default_factory=list)
    model: str = "LightGBM"
    model_version: str = "unknown"
    trained_at: str | None = None
    evaluation: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    data_quality: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "variable": self.variable,
            "label": self.label,
            "unit": self.unit,
            "latitude": round(self.latitude, 4),
            "longitude": round(self.longitude, 4),
            "forecast_horizon": self.horizon,
            "target_time": self.target_time.isoformat(),
            "prediction": round(self.prediction, 4),
            "confidence_interval": self.interval.as_dict(),
            "trend": self.trend,
            "trend_delta": round(self.trend_delta, 4),
            "last_observed": (
                round(self.last_observed, 4) if self.last_observed is not None else None
            ),
            "last_observed_time": (
                self.last_observed_time.isoformat() if self.last_observed_time else None
            ),
            "top_features": [driver.as_dict() for driver in self.drivers],
            "top_feature_labels": summarise_drivers(self.drivers),
            "model": self.model,
            "model_version": self.model_version,
            "trained_at": self.trained_at,
            "evaluation": self.evaluation,
            "history": self.history,
            "data_quality": self.data_quality,
            "sources": self.sources,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------
# Trend
# --------------------------------------------------------------------------


def classify_trend(
    prediction: float, last_observed: float | None, noise: float, *, circular: bool = False
) -> tuple[str, float]:
    """Rising / falling / stable, judged against the model's own error scale.

    The threshold is half the model's typical residual, not a fixed epsilon.
    A 0.2 degC move is meaningful for SST and invisible for air temperature,
    and a model whose RMSE is 0.5 has no business calling a 0.2 change a
    trend. Below that, the honest answer is "stable" — which is a statement
    about the forecast's resolution, not about the ocean being still.
    """
    if last_observed is None or not np.isfinite(last_observed):
        return "unknown", 0.0

    delta = prediction - last_observed
    if circular:
        delta = (delta + 180.0) % 360.0 - 180.0

    threshold = max(abs(noise) * 0.5, 1e-9)
    if delta > threshold:
        return "Increasing", float(delta)
    if delta < -threshold:
        return "Decreasing", float(delta)
    return "Stable", float(delta)


# --------------------------------------------------------------------------
# Prediction
# --------------------------------------------------------------------------


def _align_features(row: pd.DataFrame, artifact: ModelArtifact) -> pd.DataFrame:
    """Reindex an inference row onto the trained column order.

    `reindex` rather than a subset selection: a feature the trainer had and
    this row lacks becomes NaN, which LightGBM handles natively by routing it
    down the missing-value branch. Silently passing a differently-ordered
    frame would instead map every column onto the wrong split threshold and
    produce confident nonsense.
    """
    missing = [c for c in artifact.feature_columns if c not in row.columns]
    if missing:
        logger.warning(
            f"{len(missing)} trained features absent at inference "
            f"(first: {missing[:3]}) — filled as missing"
        )
    return row.reindex(columns=artifact.feature_columns)


async def predict(
    variable_key: str,
    latitude: float,
    longitude: float,
    horizon: int,
    *,
    history_window: int | None = None,
    config: ForecastingConfig | None = None,
    root: Path | None = None,
    top_k: int = 5,
    include_history: bool = True,
) -> Forecast:
    """Produce a forecast for one variable at one point.

    `history_window` is how many days of context to return alongside the
    forecast (for the chart); the feature lookback is added on top of it
    internally, so a caller asking for 30 days gets 30 days of chart and a
    model that still sees its full 30-day rolling window.
    """
    config = config or get_config()
    variable = resolve(variable_key, config)
    validate_horizon(horizon, config)

    artifact, explainer = _load_cached(variable_key, horizon, root)

    features_config = config.features_for(variable_key)
    training = config.training_for(variable_key)
    resolution = Resolution(training.resolution)

    window = history_window or 90
    window = min(window, config.defaults.max_history_days)
    lookback = window + features_config.max_lookback_days + 5

    codes = fetch_codes(variable)
    end = datetime.now(UTC).date()

    async def _fetch(with_codes: tuple[str, ...]) -> HistorySeries:
        return await fetch(
            HistoryRequest(
                codes=with_codes,
                latitude=latitude,
                longitude=longitude,
                start_date=end - timedelta(days=lookback),
                end_date=end,
                resolution=resolution,
            )
        )

    degraded: list[str] = []
    try:
        series: HistorySeries = await _fetch(codes)
    except ProviderUnavailableError:
        # `ocean_depth` is a *static* feature from a separate provider (GEBCO
        # via ERDDAP), and that provider goes down independently of the ocean
        # models. Letting a bathymetry 503 take out every forecast at every
        # point would be a poor trade for one constant column, so retry
        # without it: LightGBM routes the now-missing feature down its
        # missing-value branch, and `_align_features` already reinstates the
        # column as NaN so the trained column order still lines up.
        #
        # Only the static code is droppable. A covariate failing is a real
        # loss of signal and stays fatal.
        reduced = tuple(code for code in codes if code != "ocean_depth")
        if reduced == codes:
            raise
        logger.warning("bathymetry unavailable; forecasting without ocean_depth")
        series = await _fetch(reduced)
        degraded.append(
            "Bathymetry was unavailable, so ocean depth was omitted from this "
            "forecast's inputs. Accuracy may be slightly reduced."
        )

    value_columns = [code for code in codes if code in series.frame.columns]
    cleaned, quality = clean(
        series.frame,
        value_columns,
        resolution=resolution,
        outliers=config.outliers_for(variable_key),
    )

    # No target: this is the inference path, and the last row is the one to
    # score. Building it through the same function as training is what keeps
    # the two in step.
    matrix = build_features(
        cleaned,
        variable,
        features_config,
        latitude=series.latitude,
        longitude=series.longitude,
        horizon=None,
    )

    if matrix.frame.empty:
        raise PredictionError(
            f"no usable rows to forecast {variable.label} at "
            f"{latitude:.3f}, {longitude:.3f}"
        )

    row = matrix.frame.iloc[[-1]]
    aligned = _align_features(row, artifact)

    last_row = cleaned.iloc[-1]
    last_observed = (
        float(last_row[variable.code])
        if variable.code in cleaned.columns and pd.notna(last_row[variable.code])
        else None
    )

    # A delta model predicts the *change* from the latest observation, so it
    # has nothing to add that change to if the latest observation is missing.
    # Near-real-time products do publish all-NaN trailing timesteps, so this is
    # a real condition, not a theoretical one — and inventing an anchor would
    # produce a confident forecast built on a number nobody measured.
    mode = str(artifact.metadata.get("target_mode", "level"))
    if mode == "delta" and last_observed is None:
        raise PredictionError(
            f"the most recent {variable.label} observation at "
            f"{latitude:.3f}, {longitude:.3f} is missing, and this model "
            f"forecasts the change from it. No forecast can be anchored."
        )

    try:
        raw = np.asarray(artifact.model.predict(aligned), dtype="float64")
    except Exception as exc:  # noqa: BLE001 - lightgbm raises varied types
        raise PredictionError(f"model inference failed: {exc}") from exc

    decoded = decode_prediction(
        raw,
        np.array([last_observed if last_observed is not None else 0.0]),
        mode=mode,
        log_transform=bool(artifact.metadata.get("log_transform")),
        circular=bool(artifact.metadata.get("circular")),
    )
    prediction = _apply_bounds(float(decoded[0]), variable.valid_min, variable.valid_max)

    quantiles_payload = artifact.metadata.get("residual_quantiles")
    if not quantiles_payload:
        raise PredictionError(
            f"model for {variable_key} h{horizon} has no residual quantiles stored; "
            f"retrain it so a confidence interval can be reported"
        )
    interval = interval_from_quantiles(
        prediction,
        ResidualQuantiles.from_dict(quantiles_payload),
        valid_min=variable.valid_min,
        valid_max=variable.valid_max,
    )

    evaluation = artifact.metrics.get("validation", {}).get("metrics", {})
    noise = float(evaluation.get("rmse") or 0.0)
    trend, delta = classify_trend(
        prediction, last_observed, noise, circular=variable.circular
    )

    drivers: list[FeatureContribution] = []
    notes: list[str] = list(degraded)
    if explainer is not None:
        try:
            drivers, _ = explainer.explain_row(aligned, top_k=top_k)
        except ExplainerError as exc:
            notes.append(f"Feature attribution unavailable for this prediction: {exc}")
    else:
        notes.append("Feature attribution is unavailable for this model.")

    if quality.unfilled.get(variable.code):
        notes.append(
            f"{quality.unfilled[variable.code]} recent observations of "
            f"{variable.label} were missing and could not be interpolated; the "
            f"forecast uses the surrounding data."
        )

    target_time = pd.to_datetime(cleaned[TIMESTAMP].iloc[-1]) + _step(resolution) * horizon

    history_points: list[dict[str, Any]] = []
    if include_history:
        recent = cleaned.tail(window)
        history_points = [
            {"t": pd.Timestamp(t).isoformat(), "v": round(float(v), 4)}
            for t, v in zip(recent[TIMESTAMP], recent[variable.code], strict=True)
            if pd.notna(v)
        ]

    return Forecast(
        variable=variable_key,
        label=variable.label,
        unit=variable.unit,
        latitude=series.latitude,
        longitude=series.longitude,
        horizon=horizon,
        target_time=target_time.to_pydatetime(),
        prediction=prediction,
        interval=interval,
        trend=trend,
        trend_delta=delta,
        last_observed=last_observed,
        last_observed_time=pd.to_datetime(cleaned[TIMESTAMP].iloc[-1]).to_pydatetime(),
        drivers=drivers,
        model=str(artifact.metadata.get("model_type", "LightGBM")),
        model_version=artifact.version,
        trained_at=artifact.metadata.get("trained_at"),
        evaluation={
            "MAE": evaluation.get("mae"),
            "RMSE": evaluation.get("rmse"),
            "MAPE": evaluation.get("mape"),
            "R2": evaluation.get("r2"),
            "directional_accuracy": evaluation.get("directional_accuracy"),
            "skill_score": evaluation.get("skill_score"),
            "validation": "rolling-origin cross-validation",
            "training_rows": artifact.metadata.get("training_rows"),
        },
        history=history_points,
        data_quality=quality.as_dict(),
        sources=series.sources,
        notes=notes,
    )


def _apply_bounds(value: float, minimum: float | None, maximum: float | None) -> float:
    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _step(resolution: Resolution) -> pd.Timedelta:
    return {
        Resolution.hourly: pd.Timedelta(hours=1),
        Resolution.daily: pd.Timedelta(days=1),
        Resolution.weekly: pd.Timedelta(weeks=1),
        Resolution.monthly: pd.Timedelta(days=30),
    }[resolution]


async def predict_many(
    variable_key: str,
    latitude: float,
    longitude: float,
    horizons: list[int],
    **kwargs: Any,
) -> list[Forecast]:
    """Several horizons at one point — the dashboard's forecast curve.

    Sequential, not gathered: each call hits the same history cache entry, so
    the first fetch populates it and the rest are near-instant. Running them
    concurrently would instead fire N identical upstream requests before any
    of them had a chance to populate the cache.
    """
    results = []
    for horizon in horizons:
        results.append(
            await predict(variable_key, latitude, longitude, horizon, **kwargs)
        )
    return results
