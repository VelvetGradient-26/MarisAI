"""Validation and scoring.

**Never a random split.** These series are strongly autocorrelated: adjacent
days are nearly the same measurement. A shuffled 80/20 puts a point's Tuesday
in training and its Wednesday in test, and reports skill that will not survive
contact with an actual forecast. Every splitter here is chronological, and
every one leaves an embargo gap the width of the forecast horizon — because
predicting t+h from features at t means a training row within h days of the
test window shares its target period.

The evaluator also produces the material two other modules need:

* the **out-of-sample residuals**, which is what `uncertainty.py` bootstraps
  to get a prediction interval that is calibrated against real forecast error
  rather than in-sample fit;
* the **diagnostic arrays** (prediction-vs-actual, residuals, error histogram)
  the spec asks to plot, emitted as JSON-ready data rather than images so the
  frontend can render them in its own theme.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from forecasting import ForecastingError
from forecasting.config import ValidationConfig

logger = logging.getLogger(__name__)


class EvaluationError(ForecastingError):
    """The series could not be validated — too short for the requested folds."""


# --------------------------------------------------------------------------
# Splitters
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Split:
    """One fold: positional indices into the frame that produced it."""

    name: str
    train: np.ndarray
    test: np.ndarray

    def __repr__(self) -> str:  # keeps fold logs readable
        return f"Split({self.name!r}, train={len(self.train)}, test={len(self.test)})"


def rolling_origin_splits(
    timestamps: pd.Series,
    *,
    n_splits: int = 5,
    horizon_steps: int = 7,
    embargo_steps: int | None = None,
    min_train_fraction: float = 0.4,
) -> Iterator[Split]:
    """Expanding-window splits over time, with an embargo gap.

    Fold k trains on everything up to a cutoff and tests on the window after
    it, with `embargo_steps` dropped in between. The gap defaults to the
    forecast horizon, which is the smallest value that actually separates the
    two: a training row at cutoff - 1 has its label at cutoff - 1 + h, inside
    the test period.

    Expanding rather than sliding, because these histories are short (a few
    hundred daily rows per point) and discarding the earliest data to hold the
    window fixed costs more than the non-stationarity it would buy back.
    """
    stamps = pd.to_datetime(pd.Series(timestamps).reset_index(drop=True))
    if stamps.empty:
        raise EvaluationError("cannot split an empty series")

    gap = horizon_steps if embargo_steps is None else embargo_steps
    total = len(stamps)

    first_cutoff = int(total * min_train_fraction)
    if first_cutoff <= gap:
        raise EvaluationError(
            f"series of {total} rows is too short for {n_splits} folds with a "
            f"{gap}-step embargo — need at least {int((gap + 1) / min_train_fraction)} rows."
        )

    # Cutoff positions spread evenly from the first cutoff to the end, one per
    # fold, each fold testing the stretch up to the next cutoff.
    edges = np.linspace(first_cutoff, total, n_splits + 1).astype(int)

    produced = 0
    for fold in range(n_splits):
        cutoff, test_end = int(edges[fold]), int(edges[fold + 1])
        train_end = cutoff - gap
        if train_end <= 0 or test_end <= cutoff:
            continue
        train = np.arange(0, train_end)
        test = np.arange(cutoff, test_end)
        if len(train) == 0 or len(test) == 0:
            continue
        produced += 1
        yield Split(
            name=f"fold{fold + 1}_{stamps.iloc[cutoff].date()}_{stamps.iloc[test_end - 1].date()}",
            train=train,
            test=test,
        )

    if produced == 0:
        raise EvaluationError(
            f"no usable folds from {total} rows with a {gap}-step embargo"
        )


def chronological_split(
    timestamps: pd.Series, train_fraction: float = 0.8, embargo_steps: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """A single train/holdout cut by time, with the same embargo discipline.

    Used for the final fit's honest holdout, where rolling-origin CV has
    already chosen the model and one clean number is wanted.
    """
    total = len(timestamps)
    cutoff = int(total * train_fraction)
    train_end = max(1, cutoff - embargo_steps)
    return np.arange(0, train_end), np.arange(cutoff, total)


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def _circular_error(actual: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """Signed difference on a compass, wrapped into (-180, 180].

    Without this a forecast of 5 deg against an actual of 355 scores as a
    350-degree miss instead of the 10-degree one it is, and every direction
    variable's MAE becomes meaningless.
    """
    return np.asarray((predicted - actual + 180.0) % 360.0 - 180.0, dtype="float64")


def compute_metrics(
    actual: Sequence[float] | np.ndarray,
    predicted: Sequence[float] | np.ndarray,
    *,
    circular: bool = False,
    baseline: Sequence[float] | np.ndarray | None = None,
) -> dict[str, float | None]:
    """MAE, RMSE, MAPE, R2 and directional accuracy.

    `baseline` is the persistence forecast (the last observed value) when the
    caller has it. The skill score against persistence is the number that
    actually says whether the model is worth running: an RMSE of 0.4 degC on
    SST sounds good until persistence scores 0.38.
    """
    # Bound to fresh names rather than reassigning the parameters: the inputs
    # are typed as a sequence *or* an array, and rebinding them to arrays makes
    # every later operation ambiguous to a type checker for no gain.
    truth = np.asarray(actual, dtype="float64")
    forecast = np.asarray(predicted, dtype="float64")

    valid = np.isfinite(truth) & np.isfinite(forecast)
    if valid.sum() == 0:
        raise EvaluationError("no finite prediction/actual pairs to score")
    truth, forecast = truth[valid], forecast[valid]

    error = _circular_error(truth, forecast) if circular else forecast - truth

    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(error**2)))

    # MAPE is undefined at zero and explodes near it. Reported as None rather
    # than as a large number when the series comes near zero, because a MAPE
    # of 4e6 on a current component that crossed zero is not a measurement.
    denominator = np.abs(truth)
    usable = denominator > 1e-6
    mape: float | None = None
    if usable.sum() >= max(5, int(0.5 * len(truth))) and not circular:
        mape = float(np.mean(np.abs(error[usable] / denominator[usable])) * 100.0)

    # R2 against the mean of the actuals. Meaningless for a circular variable
    # (there is no linear variance to explain), so it is withheld there.
    r2: float | None = None
    if not circular:
        variance = float(np.sum((truth - truth.mean()) ** 2))
        r2 = float(1.0 - np.sum(error**2) / variance) if variance > 0 else None

    metrics: dict[str, float | None] = {
        "mae": round(mae, 5),
        "rmse": round(rmse, 5),
        "mape": round(mape, 3) if mape is not None else None,
        "r2": round(r2, 5) if r2 is not None else None,
        "n": int(len(truth)),
    }

    metrics["directional_accuracy"] = _directional_accuracy(truth, forecast, baseline)

    if baseline is not None:
        base = np.asarray(baseline, dtype="float64")[valid]
        base_error = _circular_error(truth, base) if circular else base - truth
        base_rmse = float(np.sqrt(np.mean(base_error**2)))
        metrics["persistence_rmse"] = round(base_rmse, 5)
        # Positive means better than persistence; 0 means equal; negative
        # means the model is worse than doing nothing.
        metrics["skill_score"] = (
            round(1.0 - (rmse**2) / (base_rmse**2), 5) if base_rmse > 0 else None
        )

    return metrics


def _directional_accuracy(
    actual: np.ndarray, predicted: np.ndarray, baseline: np.ndarray | Sequence[float] | None
) -> float | None:
    """Fraction of steps whose direction of change was called correctly.

    Measured against the *last observed value* when a baseline is supplied —
    "will it rise or fall from where it is now" is the question a user
    actually asks. Without a baseline it falls back to step-to-step change
    within the test window, which answers a subtly different question and is
    noted as such in the docs.
    """
    if baseline is not None:
        base = np.asarray(baseline, dtype="float64")
        if len(base) != len(actual):
            return None
        actual_direction = np.sign(actual - base)
        predicted_direction = np.sign(predicted - base)
    else:
        if len(actual) < 2:
            return None
        actual_direction = np.sign(np.diff(actual))
        predicted_direction = np.sign(np.diff(predicted))

    # Flat steps are excluded rather than counted as correct: with a coarse
    # field, "no change" would otherwise inflate the score toward 1.
    moving = actual_direction != 0
    if moving.sum() == 0:
        return None
    return round(float(np.mean(actual_direction[moving] == predicted_direction[moving])), 5)


# --------------------------------------------------------------------------
# Cross-validation
# --------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Everything a training run learned about how good the model is."""

    metrics: dict[str, float | None]
    folds: list[dict[str, Any]] = field(default_factory=list)
    # Out-of-sample residuals (predicted - actual), pooled across folds. The
    # input to the bootstrap interval, and the reason CV runs even when the
    # caller only wants a model.
    residuals: np.ndarray = field(default_factory=lambda: np.array([]))
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics,
            "folds": self.folds,
            "diagnostics": self.diagnostics,
        }


FitPredict = Callable[[pd.DataFrame, pd.Series, pd.DataFrame], np.ndarray]


def cross_validate(
    features: pd.DataFrame,
    target: pd.Series,
    timestamps: pd.Series,
    fit_predict: FitPredict,
    *,
    horizon_steps: int,
    config: ValidationConfig | None = None,
    circular: bool = False,
    persistence: pd.Series | None = None,
) -> ValidationResult:
    """Rolling-origin CV, returning pooled metrics, per-fold metrics and residuals.

    `fit_predict` is passed `(X_train, y_train, X_test)` and returns test
    predictions. Keeping the model behind a callable is what lets the same
    harness score LightGBM and the Prophet baseline without knowing anything
    about either.
    """
    config = config or ValidationConfig()

    splits = list(
        rolling_origin_splits(
            timestamps,
            n_splits=config.n_splits,
            horizon_steps=horizon_steps,
            embargo_steps=config.embargo_days,
            min_train_fraction=config.min_train_fraction,
        )
    )

    all_actual: list[np.ndarray] = []
    all_predicted: list[np.ndarray] = []
    all_baseline: list[np.ndarray] = []
    all_timestamps: list[np.ndarray] = []
    folds: list[dict[str, Any]] = []

    for split in splits:
        X_train = features.iloc[split.train]
        y_train = target.iloc[split.train]
        X_test = features.iloc[split.test]
        y_test = target.iloc[split.test]

        try:
            predicted = np.asarray(fit_predict(X_train, y_train, X_test), dtype="float64")
        except Exception as exc:  # noqa: BLE001 - one bad fold must not kill the run
            logger.warning(f"fold {split.name} failed to fit: {exc}")
            continue

        base = (
            persistence.iloc[split.test].to_numpy(dtype="float64")
            if persistence is not None
            else None
        )

        try:
            fold_metrics = compute_metrics(
                y_test.to_numpy(dtype="float64"), predicted, circular=circular, baseline=base
            )
        except EvaluationError:
            continue

        folds.append({"fold": split.name, "train_rows": len(split.train), **fold_metrics})
        all_actual.append(y_test.to_numpy(dtype="float64"))
        all_predicted.append(predicted)
        all_timestamps.append(
            pd.to_datetime(timestamps.iloc[split.test]).astype("int64").to_numpy() // 10**9
        )
        if base is not None:
            all_baseline.append(base)

    if not folds:
        raise EvaluationError("every cross-validation fold failed to produce a score")

    actual = np.concatenate(all_actual)
    predicted = np.concatenate(all_predicted)
    baseline = np.concatenate(all_baseline) if all_baseline else None

    metrics = compute_metrics(actual, predicted, circular=circular, baseline=baseline)
    residuals = (
        _circular_error(actual, predicted) if circular else predicted - actual
    )
    finite = np.isfinite(residuals)

    return ValidationResult(
        metrics=metrics,
        folds=folds,
        residuals=residuals[finite],
        diagnostics=build_diagnostics(
            actual, predicted, np.concatenate(all_timestamps), circular=circular
        ),
    )


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------


def build_diagnostics(
    actual: np.ndarray,
    predicted: np.ndarray,
    timestamps: np.ndarray | None = None,
    *,
    circular: bool = False,
    max_points: int = 500,
    bins: int = 30,
) -> dict[str, Any]:
    """JSON-ready arrays for the three plots the spec asks for.

    Data, not images. The dashboard renders in the viewer's theme with
    Recharts, so shipping a matplotlib PNG from the API would be both larger
    and permanently the wrong colour. `scripts/train_forecasting.py` does
    render PNGs from exactly this data, for the offline report.

    Scatter points are thinned to `max_points` by even stride rather than at
    random, so the sample stays chronologically representative and the payload
    stays a few tens of KB.
    """
    actual = np.asarray(actual, dtype="float64")
    predicted = np.asarray(predicted, dtype="float64")
    residuals = _circular_error(actual, predicted) if circular else predicted - actual

    stride = max(1, len(actual) // max_points)
    sample = slice(None, None, stride)

    scatter = [
        {"actual": round(float(a), 4), "predicted": round(float(p), 4)}
        for a, p in zip(actual[sample], predicted[sample], strict=True)
    ]

    residual_series = []
    if timestamps is not None:
        stamps = np.asarray(timestamps)[sample]
        residual_series = [
            {"t": int(t), "residual": round(float(r), 4)}
            for t, r in zip(stamps, residuals[sample], strict=True)
        ]

    finite = residuals[np.isfinite(residuals)]
    histogram: list[dict[str, float]] = []
    if finite.size:
        counts, edges = np.histogram(finite, bins=bins)
        histogram = [
            {
                "bin_start": round(float(edges[i]), 4),
                "bin_end": round(float(edges[i + 1]), 4),
                "count": int(counts[i]),
            }
            for i in range(len(counts))
        ]

    return {
        "prediction_vs_actual": scatter,
        "residuals": residual_series,
        "error_distribution": histogram,
        "residual_summary": {
            "mean": round(float(np.mean(finite)), 5) if finite.size else None,
            "std": round(float(np.std(finite)), 5) if finite.size else None,
            "p05": round(float(np.percentile(finite, 5)), 5) if finite.size else None,
            "p95": round(float(np.percentile(finite, 95)), 5) if finite.size else None,
        },
    }
