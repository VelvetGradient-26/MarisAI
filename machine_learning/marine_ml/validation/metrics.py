"""Skill, calibration and extrapolation metrics for both problem statements.

The doc asks for different primary metrics per problem, and the reasons
matter:

* **HAB** — PR-AUC, not ROC-AUC. Blooms are a low-single-digit-percent
  positive class, and ROC-AUC is dominated by the enormous true-negative pool,
  so it looks flattering while the model is useless at the operating point
  anyone would actually alert on. Plus Brier score and a reliability curve,
  because the product surfaces a confidence number rather than a bare label.
* **Fish habitat** — AUC, the True Skill Statistic, and the continuous Boyce
  index. Boyce is the one that matters for presence-only data: it needs no
  true absences, which is exactly the situation OBIS leaves us in.
* **Both** — MESS, to flag where a prediction is extrapolation rather than
  interpolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
)


# --------------------------------------------------------------------------
# Threshold-based skill
# --------------------------------------------------------------------------


def true_skill_statistic(
    y_true: np.ndarray, y_score: np.ndarray, threshold: float
) -> float:
    """TSS = sensitivity + specificity - 1.

    Ranges -1 to 1; 0 is no better than chance. Standard in the ecological
    SDM literature and, unlike raw accuracy, not fooled by class imbalance.
    """
    y_true = np.asarray(y_true).astype(bool)
    predicted = np.asarray(y_score) >= threshold

    true_positive = np.sum(predicted & y_true)
    false_negative = np.sum(~predicted & y_true)
    true_negative = np.sum(~predicted & ~y_true)
    false_positive = np.sum(predicted & ~y_true)

    sensitivity = _safe_ratio(true_positive, true_positive + false_negative)
    specificity = _safe_ratio(true_negative, true_negative + false_positive)
    return float(sensitivity + specificity - 1.0)


def max_tss_threshold(y_true: np.ndarray, y_score: np.ndarray) -> tuple[float, float]:
    """Threshold maximising TSS, and the TSS there.

    The conventional way to pick an operating point for a presence/background
    model, rather than defaulting to 0.5 — which is meaningless when the
    class balance is an artefact of how many background points were drawn.
    """
    y_true = np.asarray(y_true).astype(bool)
    y_score = np.asarray(y_score, dtype=float)

    candidates = np.unique(np.quantile(y_score, np.linspace(0.0, 1.0, 201)))
    scores = [(true_skill_statistic(y_true, y_score, t), t) for t in candidates]
    best_tss, best_threshold = max(scores)
    return float(best_threshold), float(best_tss)


def f1_at_threshold(y_true: np.ndarray, y_score: np.ndarray, threshold: float) -> float:
    y_true = np.asarray(y_true).astype(bool)
    predicted = np.asarray(y_score) >= threshold
    true_positive = np.sum(predicted & y_true)
    precision = _safe_ratio(true_positive, np.sum(predicted))
    recall = _safe_ratio(true_positive, np.sum(y_true))
    return float(_safe_ratio(2 * precision * recall, precision + recall))


def precision_recall_at_threshold(
    y_true: np.ndarray, y_score: np.ndarray, threshold: float
) -> tuple[float, float]:
    y_true = np.asarray(y_true).astype(bool)
    predicted = np.asarray(y_score) >= threshold
    true_positive = np.sum(predicted & y_true)
    return (
        float(_safe_ratio(true_positive, np.sum(predicted))),
        float(_safe_ratio(true_positive, np.sum(y_true))),
    )


def threshold_for_recall(
    y_true: np.ndarray, y_score: np.ndarray, target_recall: float = 0.8
) -> float:
    """Lowest-alarm threshold that still catches ``target_recall`` of events.

    An operational early-warning system is specified by the recall a coastal
    agency demands, not by an abstract optimum: missing blooms is far more
    costly than a false alarm, so the threshold is chosen to hit a recall
    floor and the resulting false-alarm rate is reported honestly.
    """
    precision, recall, thresholds = precision_recall_curve(
        np.asarray(y_true).astype(int), np.asarray(y_score, dtype=float)
    )
    # precision_recall_curve returns len(thresholds) == len(recall) - 1.
    viable = np.flatnonzero(recall[:-1] >= target_recall)
    if viable.size == 0:
        return float(np.min(thresholds)) if thresholds.size else 0.0
    return float(thresholds[viable[-1]])


def false_alarm_rate(
    y_true: np.ndarray, y_score: np.ndarray, threshold: float
) -> float:
    """Fraction of alarms that were not events — what erodes operator trust."""
    y_true = np.asarray(y_true).astype(bool)
    predicted = np.asarray(y_score) >= threshold
    return float(_safe_ratio(np.sum(predicted & ~y_true), np.sum(predicted)))


def _safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


# --------------------------------------------------------------------------
# Presence-only skill: the continuous Boyce index
# --------------------------------------------------------------------------


def boyce_index(
    presence_scores: np.ndarray,
    background_scores: np.ndarray,
    n_windows: int = 100,
    window_fraction: float = 0.1,
) -> float:
    """Continuous Boyce index — Spearman rho between predicted-to-expected
    ratio and suitability, over a moving window.

    Requires no true absences, which is the entire point: OBIS gives
    presences and a background, never a verified absence. A well-calibrated
    habitat model puts monotonically more presences than background in
    successively higher suitability bins, giving an index near 1. Near 0
    means predictions are no better than the background distribution;
    negative means they are inverted.
    """
    presence_scores = np.asarray(presence_scores, dtype=float)
    presence_scores = presence_scores[np.isfinite(presence_scores)]
    background_scores = np.asarray(background_scores, dtype=float)
    background_scores = background_scores[np.isfinite(background_scores)]

    if presence_scores.size == 0 or background_scores.size == 0:
        return float("nan")

    low = min(presence_scores.min(), background_scores.min())
    high = max(presence_scores.max(), background_scores.max())
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return float("nan")

    width = (high - low) * window_fraction
    starts = np.linspace(low, high - width, n_windows)

    midpoints: list[float] = []
    ratios: list[float] = []
    for start in starts:
        stop = start + width
        presence_fraction = np.mean(
            (presence_scores >= start) & (presence_scores <= stop)
        )
        background_fraction = np.mean(
            (background_scores >= start) & (background_scores <= stop)
        )
        # Windows with no background have an undefined expectation; skipping
        # them is the standard treatment, inventing a ratio there is not.
        if background_fraction <= 0:
            continue
        midpoints.append(start + width / 2.0)
        ratios.append(presence_fraction / background_fraction)

    if len(ratios) < 3:
        return float("nan")

    from scipy.stats import spearmanr

    rho = spearmanr(midpoints, ratios).statistic
    return float(rho) if np.isfinite(rho) else float("nan")


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------


def reliability_curve(
    y_true: np.ndarray, y_score: np.ndarray, n_bins: int = 10
) -> pd.DataFrame:
    """Observed event frequency against predicted probability, per bin.

    A model can rank perfectly (great AUC) and still be badly calibrated. If
    the product tells a coastal agency "70% chance of a bloom", that number
    has to mean something, so this is reported alongside the ranking metrics.
    """
    y_true = np.asarray(y_true).astype(float)
    y_score = np.asarray(y_score, dtype=float)

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    index = np.clip(np.digitize(y_score, bins) - 1, 0, n_bins - 1)

    rows = []
    for b in range(n_bins):
        mask = index == b
        if not mask.any():
            continue
        rows.append(
            {
                "bin_lower": bins[b],
                "bin_upper": bins[b + 1],
                "n": int(mask.sum()),
                "mean_predicted": float(y_score[mask].mean()),
                "observed_frequency": float(y_true[mask].mean()),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Extrapolation
# --------------------------------------------------------------------------


def mess(
    training: pd.DataFrame, projection: pd.DataFrame, columns: list[str] | None = None
) -> pd.Series:
    """Multivariate Environmental Similarity Surface (Elith et al. 2010).

    For each projection row, how similar its environment is to the training
    envelope, as a percentage. **Negative values mean extrapolation** — at
    least one variable falls outside the range the model ever saw, so its
    prediction there is an extension of a fitted curve into unobserved
    conditions rather than a interpolation among examples.

    Matters directly for climate-driven range shift: a habitat model trained
    on 2000-2013 SST asked about a marine heatwave is extrapolating, and the
    product should say so rather than quietly returning a confident number.
    """
    columns = columns or [
        c for c in projection.columns if pd.api.types.is_numeric_dtype(projection[c])
    ]

    similarity = pd.DataFrame(index=projection.index)
    for column in columns:
        if column not in training.columns:
            continue
        reference = training[column].to_numpy(dtype=float)
        reference = reference[np.isfinite(reference)]
        if reference.size == 0:
            continue

        values = projection[column].to_numpy(dtype=float)
        low, high = reference.min(), reference.max()
        spread = high - low
        if spread <= 0:
            continue

        # Percentage of training values below each projection value.
        percentile = (
            np.searchsorted(np.sort(reference), values, side="left")
            / reference.size
            * 100.0
        )

        column_similarity = np.where(
            percentile == 0,
            (values - low) / spread * 100.0,
            np.where(
                percentile < 50,
                2.0 * percentile,
                np.where(
                    percentile < 100,
                    2.0 * (100.0 - percentile),
                    (high - values) / spread * 100.0,
                ),
            ),
        )
        similarity[column] = column_similarity

    if similarity.empty:
        return pd.Series(np.nan, index=projection.index, name="mess")

    # The most dissimilar variable governs — one variable out of range is
    # enough to make the whole prediction an extrapolation.
    return similarity.min(axis=1).rename("mess")


# --------------------------------------------------------------------------
# Report bundles
# --------------------------------------------------------------------------


@dataclass
class ClassificationReport:
    """Skill summary for one fold or one held-out period."""

    name: str
    n: int
    n_positive: int
    roc_auc: float
    pr_auc: float
    brier: float
    tss: float
    tss_threshold: float
    precision: float
    recall: float
    f1: float
    boyce: float = float("nan")
    extras: dict = field(default_factory=dict)

    def as_row(self) -> dict:
        row = {
            "split": self.name,
            "n": self.n,
            "n_positive": self.n_positive,
            "positive_rate": self.n_positive / self.n if self.n else float("nan"),
            "roc_auc": self.roc_auc,
            "pr_auc": self.pr_auc,
            "brier": self.brier,
            "tss": self.tss,
            "tss_threshold": self.tss_threshold,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "boyce": self.boyce,
        }
        row.update(self.extras)
        return row


def evaluate_classification(
    y_true: np.ndarray,
    y_score: np.ndarray,
    name: str = "holdout",
    compute_boyce: bool = False,
) -> ClassificationReport:
    """Full skill bundle for a binary problem with probabilistic scores."""
    y_true = np.asarray(y_true).astype(int)
    y_score = np.asarray(y_score, dtype=float)

    n_positive = int(y_true.sum())
    # A fold with one class present has no defined ranking metric; NaN is the
    # honest answer, and averaging over folds must then skip it.
    single_class = n_positive == 0 or n_positive == len(y_true)

    roc = float("nan") if single_class else float(roc_auc_score(y_true, y_score))
    pr = float("nan") if single_class else float(average_precision_score(y_true, y_score))
    threshold, tss = (
        (float("nan"), float("nan")) if single_class else max_tss_threshold(y_true, y_score)
    )
    precision, recall = (
        (float("nan"), float("nan"))
        if single_class
        else precision_recall_at_threshold(y_true, y_score, threshold)
    )

    boyce = float("nan")
    if compute_boyce and not single_class:
        boyce = boyce_index(y_score[y_true == 1], y_score[y_true == 0])

    return ClassificationReport(
        name=name,
        n=len(y_true),
        n_positive=n_positive,
        roc_auc=roc,
        pr_auc=pr,
        brier=float(brier_score_loss(y_true, np.clip(y_score, 0, 1)))
        if not single_class
        else float("nan"),
        tss=tss,
        tss_threshold=threshold,
        precision=precision,
        recall=recall,
        f1=float("nan") if single_class else f1_at_threshold(y_true, y_score, threshold),
        boyce=boyce,
    )


def summarise_folds(reports: list[ClassificationReport]) -> pd.DataFrame:
    """Per-fold rows plus a mean row, skipping folds that had a single class."""
    frame = pd.DataFrame([report.as_row() for report in reports])
    if frame.empty:
        return frame
    numeric = frame.select_dtypes(include="number").mean(skipna=True)
    mean_row = {"split": "MEAN", **numeric.to_dict()}
    return pd.concat([frame, pd.DataFrame([mean_row])], ignore_index=True)
