"""Bloom labelling for the HAB early-warning model (approach doc 3.1, 3.5).

The framing decision that shapes everything downstream: **forecast, then
threshold** — not direct binary classification.

The model predicts chlorophyll at t+3/t+5/t+7 and a bloom is declared when the
forecast exceeds a locally- and seasonally-calibrated percentile. This buys
three things a straight yes/no classifier cannot:

1. A continuous, explainable risk score (a chlorophyll trajectory plus a
   distance above the local normal) instead of an opaque label.
2. A threshold that can be re-tuned per region, season, or agency risk
   appetite *without retraining the model*.
3. Honesty about what the label is. A fixed global chlorophyll cutoff is not
   physically meaningful across regimes — 1 mg/m3 is an extreme anomaly in
   the open Arabian Sea and an ordinary Tuesday in a coastal upwelling zone.

Label strength is tracked explicitly. What this pipeline produces is a **weak
label**: satellite/model chlorophyll exceeding a high local percentile is a
proxy for a bloom, not a verified one, and it says nothing about whether that
bloom is toxic. Strong labels (in-situ cell counts and toxin assays from
HABSOS/NCCOS/HAEDAT, or INCOIS advisories for the Indian coast) would enter
through the same interface with ``label_strength='strong'``, and the toxicity
classifier of the doc's Stage 2 sits on top of those. That data is not openly
queryable for this coastline, so Stage 2 is deliberately not implemented here
rather than faked.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_HORIZONS = (3, 5, 7)
DEFAULT_PERCENTILE = 90.0


class LabelError(RuntimeError):
    """Raised when bloom labels cannot be constructed."""


def fit_bloom_thresholds(
    frame: pd.DataFrame,
    value_column: str = "chl",
    percentile: float = DEFAULT_PERCENTILE,
    group_columns: tuple[str, ...] = ("latitude", "longitude"),
    seasonal: bool = True,
    min_observations: int = 24,
) -> pd.DataFrame:
    """Per-cell (and optionally per-season) chlorophyll bloom threshold.

    **Fit on training rows only.** A threshold fitted over the full record
    encodes the test period's own distribution into the label definition,
    which is leakage of an especially confusing kind: it corrupts the target,
    not just a feature.

    Cells with fewer than ``min_observations`` samples in a group fall back to
    the cell's all-season threshold, and then to a global one — a percentile
    estimated from a handful of points is noise, and would define blooms
    somewhere they never occur.
    """
    if value_column not in frame.columns:
        raise LabelError(f"{value_column!r} is not in the frame")

    working = frame.dropna(subset=[value_column]).copy()
    if working.empty:
        raise LabelError(f"no non-null {value_column} values to fit thresholds on")

    global_threshold = float(np.nanpercentile(working[value_column], percentile))

    keys = list(group_columns)
    if seasonal:
        working["season"] = _season(working["date"])
        keys.append("season")

    grouped = working.groupby(keys, observed=True)[value_column]
    thresholds = grouped.agg(
        threshold=lambda s: np.nanpercentile(s, percentile), n="count"
    ).reset_index()

    # Cell-level fallback (all seasons pooled) for sparse groups.
    cell_level = (
        working.groupby(list(group_columns), observed=True)[value_column]
        .agg(cell_threshold=lambda s: np.nanpercentile(s, percentile), cell_n="count")
        .reset_index()
    )
    thresholds = thresholds.merge(cell_level, on=list(group_columns), how="left")

    sparse = thresholds["n"] < min_observations
    thresholds.loc[sparse, "threshold"] = thresholds.loc[sparse, "cell_threshold"]
    thresholds["threshold"] = thresholds["threshold"].fillna(global_threshold)

    thresholds.attrs["global_threshold"] = global_threshold
    thresholds.attrs["percentile"] = percentile
    return thresholds.drop(columns=["cell_threshold", "cell_n"])


def apply_bloom_thresholds(
    frame: pd.DataFrame,
    thresholds: pd.DataFrame,
    value_column: str = "chl",
    group_columns: tuple[str, ...] = ("latitude", "longitude"),
    seasonal: bool = True,
) -> pd.DataFrame:
    """Attach the fitted threshold and a concurrent ``is_bloom`` flag."""
    working = frame.copy()
    keys = list(group_columns)
    if seasonal:
        working["season"] = _season(working["date"])
        keys.append("season")

    merged = working.merge(thresholds, on=keys, how="left")
    fallback = thresholds.attrs.get("global_threshold", np.nan)
    merged["threshold"] = merged["threshold"].fillna(fallback)

    merged["is_bloom"] = (merged[value_column] >= merged["threshold"]).astype("Int8")
    merged.loc[merged[value_column].isna(), "is_bloom"] = pd.NA

    # How far above the local normal — the severity signal behind the score.
    merged["bloom_exceedance"] = merged[value_column] - merged["threshold"]
    return merged.drop(columns=["n"], errors="ignore")


def add_forecast_labels(
    frame: pd.DataFrame,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    group_columns: tuple[str, ...] = ("latitude", "longitude"),
    date_column: str = "date",
    value_column: str = "chl",
) -> pd.DataFrame:
    """Add ``bloom_t{h}`` and ``chl_t{h}`` targets for each horizon.

    These are **forward** shifts — the only forward-looking operation in the
    codebase, and correct here because they are the target, not a feature.
    Row at time t carries the bloom state at t+h, which is exactly the
    question the product asks.

    Shifting is done per cell on a date-sorted frame; a cell with a gap in its
    series produces NaN rather than silently borrowing a label from whatever
    date happens to sit adjacent in the frame.
    """
    working = frame.sort_values(list(group_columns) + [date_column]).copy()
    grouped = working.groupby(list(group_columns), observed=True, sort=False)

    for horizon in horizons:
        working[f"chl_t{horizon}"] = grouped[value_column].shift(-horizon)
        working[f"threshold_t{horizon}"] = grouped["threshold"].shift(-horizon)
        label = (
            working[f"chl_t{horizon}"] >= working[f"threshold_t{horizon}"]
        ).astype("Int8")
        label[working[f"chl_t{horizon}"].isna()] = pd.NA
        working[f"bloom_t{horizon}"] = label

    return working


def _season(dates: pd.Series) -> pd.Series:
    """Monsoon-phase season, the meaningful seasonal unit in this basin."""
    month = pd.to_datetime(dates).dt.month
    season = pd.Series("pre_monsoon", index=month.index, dtype="object")
    season[month.isin((6, 7, 8, 9))] = "southwest_monsoon"
    season[month.isin((10, 11))] = "post_monsoon"
    season[month.isin((12, 1, 2))] = "northeast_monsoon"
    return season


def summarise(frame: pd.DataFrame, horizons: tuple[int, ...] = DEFAULT_HORIZONS) -> pd.DataFrame:
    """Positive-class rate per horizon.

    The doc's EDA plan insists this be quantified with real numbers before the
    imbalance strategy is chosen, rather than assumed to be "a few percent".
    """
    rows = []
    for horizon in horizons:
        column = f"bloom_t{horizon}"
        if column not in frame.columns:
            continue
        values = frame[column].dropna()
        rows.append(
            {
                "horizon_days": horizon,
                "n_labelled": len(values),
                "n_bloom": int(values.sum()),
                "bloom_rate": float(values.mean()) if len(values) else float("nan"),
            }
        )
    return pd.DataFrame(rows)
