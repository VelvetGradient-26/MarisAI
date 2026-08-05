"""SHAP explanations: which features moved *this* prediction, and by how much.

Two properties make SHAP the right tool here rather than LightGBM's built-in
`feature_importances_`:

* **It is per-prediction.** Gain-based importance is one global ranking for
  the whole model — it can say "day-of-year matters for SST" but never "this
  forecast is high because the last 30 days ran warm". The spec asks for the
  drivers of a specific number, which is a local question.
* **It is signed and additive.** Contributions sum to the prediction minus the
  base value, so "lag7 pushed it up 0.4 degC" is literally true rather than a
  ranking metaphor.

For tree models the exact TreeSHAP algorithm runs in polynomial time on the
tree structure, so this costs about a millisecond for one row — cheap enough
to compute on every request rather than caching.

Raw feature names (`sst_roll30_mean`) are translated into readable ones
("30-day average") on the way out, because the explanation is a user-facing
product surface, not a debugging aid.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from forecasting import ForecastingError
from services.download.registry import VARIABLE_REGISTRY

logger = logging.getLogger(__name__)


class ExplainerError(ForecastingError):
    """SHAP values could not be produced for this model/row."""


@dataclass(frozen=True)
class FeatureContribution:
    """One feature's signed push on a single prediction."""

    feature: str
    label: str
    value: float | None
    contribution: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "label": self.label,
            "value": round(self.value, 4) if self.value is not None else None,
            "contribution": round(self.contribution, 5),
            "direction": "increases" if self.contribution >= 0 else "decreases",
        }


# --------------------------------------------------------------------------
# Human-readable feature names
# --------------------------------------------------------------------------

_STATIC_LABELS = {
    "latitude": "Latitude",
    "longitude": "Longitude",
    "abs_latitude": "Distance from equator",
    "ocean_depth": "Ocean depth",
    "basin": "Ocean basin",
    "distance_to_coast_km": "Distance to coast",
    "month": "Month",
    "day": "Day of month",
    "week": "Week of year",
    "day_of_year": "Day of year",
    "quarter": "Quarter",
    "day_of_week": "Day of week",
    "doy_sin": "Seasonality (annual cycle)",
    "doy_cos": "Seasonality (annual cycle)",
    "month_sin": "Seasonality (monthly cycle)",
    "month_cos": "Seasonality (monthly cycle)",
}

_STATISTIC_LABELS = {
    "mean": "average",
    "std": "variability",
    "min": "minimum",
    "max": "maximum",
}


def _variable_label(code: str) -> str:
    info = VARIABLE_REGISTRY.get(code)
    return info.label if info else code.replace("_", " ").title()


def humanise(feature: str) -> str:
    """Turn an engineered column name into something a reader can act on.

    Falls back to a de-underscored title rather than raising: a new feature
    family should show up as slightly clumsy prose, never as a crash inside an
    explanation.
    """
    if feature in _STATIC_LABELS:
        return _STATIC_LABELS[feature]

    match = re.match(r"^(?P<code>.+?)_lag(?P<n>\d+)$", feature)
    if match:
        return f"{_variable_label(match['code'])} {match['n']} steps ago"

    match = re.match(
        r"^(?P<code>.+?)_roll(?P<w>\d+)_(?P<stat>mean|std|min|max)$", feature
    )
    if match:
        statistic = _STATISTIC_LABELS[match["stat"]]
        return f"{_variable_label(match['code'])} {match['w']}-step {statistic}"

    match = re.match(r"^(?P<code>.+?)_trend(?P<w>\d+)$", feature)
    if match:
        return f"{_variable_label(match['code'])} {match['w']}-step trend"

    if feature.endswith("_diff1"):
        return f"{_variable_label(feature[:-6])} change since last step"
    if feature.endswith("_pct_change"):
        return f"{_variable_label(feature[:-11])} percentage change"
    if feature.endswith("_sin") or feature.endswith("_cos"):
        return f"{_variable_label(feature[:-4])} direction"

    return _variable_label(feature)


# --------------------------------------------------------------------------
# Explainer
# --------------------------------------------------------------------------


class ShapExplainer:
    """A TreeSHAP explainer bound to one trained booster.

    Constructed lazily by the predictor and cached alongside the model, since
    building the explainer walks the whole forest and is the expensive part —
    scoring a single row afterwards is not.
    """

    def __init__(self, model: Any, feature_columns: Sequence[str]) -> None:
        self.feature_columns = list(feature_columns)
        try:
            import shap
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ExplainerError(
                "shap is not installed; explanations are unavailable"
            ) from exc

        try:
            self._explainer = shap.TreeExplainer(model)
        except Exception as exc:  # noqa: BLE001 - shap raises a variety of types
            raise ExplainerError(f"could not build a SHAP explainer: {exc}") from exc

    def explain_row(
        self, row: pd.DataFrame, top_k: int = 5
    ) -> tuple[list[FeatureContribution], float]:
        """Top-k drivers of one prediction, plus the model's base value.

        Ranked by absolute contribution — the question is "what moved this
        number", and a large negative push is exactly as much of an
        explanation as a large positive one.
        """
        if len(row) != 1:
            raise ExplainerError(f"expected exactly one row to explain, got {len(row)}")

        try:
            values = self._explainer.shap_values(row[self.feature_columns])
        except Exception as exc:  # noqa: BLE001
            raise ExplainerError(f"SHAP evaluation failed: {exc}") from exc

        contributions = np.asarray(values, dtype="float64").reshape(-1)
        if contributions.size != len(self.feature_columns):
            raise ExplainerError(
                f"SHAP returned {contributions.size} values for "
                f"{len(self.feature_columns)} features"
            )

        base_value = float(np.asarray(self._explainer.expected_value).reshape(-1)[0])

        order = np.argsort(np.abs(contributions))[::-1][:top_k]
        result = []
        for index in order:
            name = self.feature_columns[index]
            raw = row.iloc[0].get(name)
            result.append(
                FeatureContribution(
                    feature=name,
                    label=humanise(name),
                    value=None if raw is None or pd.isna(raw) else float(raw),
                    contribution=float(contributions[index]),
                )
            )
        return result, base_value

    def global_importance(
        self, frame: pd.DataFrame, top_k: int = 15
    ) -> list[dict[str, Any]]:
        """Mean |SHAP| across many rows — the model-level ranking.

        Computed at training time over the validation rows and stored in
        `metrics.json`, so the dashboard's importance chart does not have to
        re-derive it per request.
        """
        try:
            values = self._explainer.shap_values(frame[self.feature_columns])
        except Exception as exc:  # noqa: BLE001
            raise ExplainerError(f"SHAP evaluation failed: {exc}") from exc

        matrix = np.asarray(values, dtype="float64")
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        importance = np.abs(matrix).mean(axis=0)

        order = np.argsort(importance)[::-1][:top_k]
        return [
            {
                "feature": self.feature_columns[index],
                "label": humanise(self.feature_columns[index]),
                "importance": round(float(importance[index]), 6),
            }
            for index in order
        ]


def summarise_drivers(contributions: Sequence[FeatureContribution]) -> list[str]:
    """Deduplicated, human-readable driver names for a text summary.

    Several columns often describe the same underlying story — `doy_sin` and
    `doy_cos` are both "seasonality", three lags of SST are all "recent SST".
    Listing them separately makes an explanation look padded and buries the
    variety, so identical labels collapse while keeping their rank order.
    """
    seen: list[str] = []
    for contribution in contributions:
        if contribution.label not in seen:
            seen.append(contribution.label)
    return seen
