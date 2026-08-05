"""Bootstrap prediction intervals.

A point forecast without an interval invites the reader to treat it as fact.
For an ocean variable driven by a chaotic system that is not a stylistic
complaint — "SST will be 29.4 degC in 30 days" and "29.4, 95% CI 27.8-31.0"
support completely different decisions.

Two methods, both genuine bootstraps, with different cost/meaning tradeoffs:

``residual_bootstrap`` (default)
    Resample the model's **out-of-sample** residuals from rolling-origin CV
    and add them to the point prediction. The interval it produces is
    calibrated against error the model actually made on data it had not seen,
    at the horizon in question, which is the quantity a user cares about.
    Costs nothing at inference: the residual quantiles are computed once at
    training time and stored in the model's metadata.

``bagged_bootstrap``
    Fit N models on bootstrap resamples of the training set and take the
    spread of their predictions. Captures *model* uncertainty (how much the
    fit itself depends on which rows it saw) but **not** irreducible noise, so
    it is systematically narrower and should not be read as a forecast
    interval on its own. Offered because it is the honest way to answer "how
    stable is this model", and N-times the training cost.

The default is residual bootstrap because the alternative flatters the model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from forecasting import ForecastingError
from forecasting.config import UncertaintyConfig

logger = logging.getLogger(__name__)


class UncertaintyError(ForecastingError):
    """An interval could not be produced."""


@dataclass(frozen=True)
class Interval:
    """A prediction interval and the evidence behind it."""

    lower: float
    upper: float
    confidence_level: float
    method: str
    # How many residuals the quantiles were estimated from. Small numbers mean
    # a wide, unstable interval, and the API reports it rather than hiding it.
    n_residuals: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "lower": round(self.lower, 4),
            "upper": round(self.upper, 4),
            "confidence_level": self.confidence_level,
            "method": self.method,
            "n_residuals": self.n_residuals,
        }


@dataclass(frozen=True)
class ResidualQuantiles:
    """Pre-computed offsets from the point prediction, stored with the model.

    Computed once at training time from the CV residuals, so inference adds
    two floats rather than 500 resamples. This is the whole reason the
    residual bootstrap is the cheap option at serve time despite being the
    statistically honest one.
    """

    lower_offset: float
    upper_offset: float
    confidence_level: float
    n_residuals: int
    # Kept for reporting: a large |bias| means the model is systematically
    # over- or under-shooting, which the interval will carry but which is
    # worth seeing on its own.
    bias: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "lower_offset": round(self.lower_offset, 5),
            "upper_offset": round(self.upper_offset, 5),
            "confidence_level": self.confidence_level,
            "n_residuals": self.n_residuals,
            "bias": round(self.bias, 5),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResidualQuantiles:
        return cls(
            lower_offset=float(payload["lower_offset"]),
            upper_offset=float(payload["upper_offset"]),
            confidence_level=float(payload["confidence_level"]),
            n_residuals=int(payload["n_residuals"]),
            bias=float(payload.get("bias", 0.0)),
        )


# Below this many residuals the empirical quantiles are noise, and a bootstrap
# of them is confidently-presented noise. The caller is told to widen using a
# normal approximation instead, which at least degrades predictably.
_MIN_RESIDUALS = 20


def fit_residual_quantiles(
    residuals: np.ndarray, config: UncertaintyConfig | None = None
) -> ResidualQuantiles:
    """Bootstrap the residual distribution's tail quantiles.

    Resampling with replacement, rather than reading the raw percentiles off
    the residuals directly, is what makes this a bootstrap: it accounts for
    the fact that the quantile *estimate* is itself uncertain when there are
    only a few hundred residuals, and produces a slightly wider, more honest
    interval than the naive percentile would.
    """
    config = config or UncertaintyConfig()
    residuals = np.asarray(residuals, dtype="float64")
    residuals = residuals[np.isfinite(residuals)]

    if residuals.size == 0:
        raise UncertaintyError("no residuals available to build an interval from")

    alpha = 1.0 - config.confidence_level
    lower_percentile = 100.0 * (alpha / 2.0)
    upper_percentile = 100.0 * (1.0 - alpha / 2.0)

    if residuals.size < _MIN_RESIDUALS:
        # Too few to resample meaningfully. A normal approximation about the
        # residual mean is cruder but does not pretend to know the tail shape.
        logger.warning(
            f"only {residuals.size} residuals — falling back to a normal "
            f"approximation for the prediction interval"
        )
        spread = float(np.std(residuals, ddof=1)) if residuals.size > 1 else 0.0
        z = 1.959963985 if abs(config.confidence_level - 0.95) < 1e-9 else _normal_z(
            config.confidence_level
        )
        mean = float(np.mean(residuals))
        return ResidualQuantiles(
            lower_offset=mean - z * spread,
            upper_offset=mean + z * spread,
            confidence_level=config.confidence_level,
            n_residuals=int(residuals.size),
            bias=mean,
        )

    rng = np.random.default_rng(config.random_seed)
    # Each bootstrap replicate is a full-size resample; the quantile of
    # interest is computed within each, and the mean of those quantiles is the
    # bootstrap estimate.
    replicates = rng.choice(
        residuals, size=(config.n_bootstrap, residuals.size), replace=True
    )
    lower = float(np.mean(np.percentile(replicates, lower_percentile, axis=1)))
    upper = float(np.mean(np.percentile(replicates, upper_percentile, axis=1)))

    return ResidualQuantiles(
        lower_offset=lower,
        upper_offset=upper,
        confidence_level=config.confidence_level,
        n_residuals=int(residuals.size),
        bias=float(np.mean(residuals)),
    )


def _normal_z(confidence_level: float) -> float:
    """Two-sided normal critical value, without pulling in scipy.stats.

    Acklam's inverse-normal approximation; accurate to ~1e-9 over the range
    that matters here, which is far beyond what a 30-residual fallback
    deserves.
    """
    from math import erf, sqrt

    # Bisection on the CDF is more than fast enough for a value computed once
    # per model, and avoids transcribing a rational approximation.
    target = 1.0 - (1.0 - confidence_level) / 2.0
    low, high = 0.0, 10.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if 0.5 * (1.0 + erf(mid / sqrt(2.0))) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def interval_from_quantiles(
    prediction: float,
    quantiles: ResidualQuantiles,
    *,
    valid_min: float | None = None,
    valid_max: float | None = None,
) -> Interval:
    """Apply stored residual offsets to a point prediction.

    Residuals are defined as `predicted - actual`, so recovering the actual
    means *subtracting* them: the upper residual quantile (the model's biggest
    over-prediction) maps to the interval's **lower** bound. Getting this
    backwards produces an interval that is correct in width and inverted in
    skew, which is close to invisible on a symmetric distribution and quite
    wrong on chlorophyll.
    """
    lower = prediction - quantiles.upper_offset
    upper = prediction - quantiles.lower_offset

    # Physical bounds clamp the interval, not just the point estimate: a 95%
    # lower bound of -3 mg/m3 of chlorophyll is not a statement about the
    # ocean.
    if valid_min is not None:
        lower = max(lower, valid_min)
        upper = max(upper, valid_min)
    if valid_max is not None:
        lower = min(lower, valid_max)
        upper = min(upper, valid_max)

    return Interval(
        lower=float(min(lower, upper)),
        upper=float(max(lower, upper)),
        confidence_level=quantiles.confidence_level,
        method="residual_bootstrap",
        n_residuals=quantiles.n_residuals,
    )


def bagged_interval(
    predictions: np.ndarray,
    config: UncertaintyConfig | None = None,
    *,
    valid_min: float | None = None,
    valid_max: float | None = None,
) -> Interval:
    """Interval from the spread of an ensemble's predictions.

    Reports `method="bagged_bootstrap"` so a consumer can tell it apart from
    the residual interval — they are not the same quantity, and averaging or
    comparing them directly would be a category error.
    """
    config = config or UncertaintyConfig()
    predictions = np.asarray(predictions, dtype="float64")
    predictions = predictions[np.isfinite(predictions)]
    if predictions.size < 2:
        raise UncertaintyError("need at least two ensemble predictions for a spread")

    alpha = 1.0 - config.confidence_level
    lower = float(np.percentile(predictions, 100.0 * alpha / 2.0))
    upper = float(np.percentile(predictions, 100.0 * (1.0 - alpha / 2.0)))

    if valid_min is not None:
        lower, upper = max(lower, valid_min), max(upper, valid_min)
    if valid_max is not None:
        lower, upper = min(lower, valid_max), min(upper, valid_max)

    return Interval(
        lower=lower,
        upper=upper,
        confidence_level=config.confidence_level,
        method="bagged_bootstrap",
        n_residuals=int(predictions.size),
    )
