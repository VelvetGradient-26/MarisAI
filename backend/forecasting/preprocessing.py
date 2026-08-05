"""Cleaning, gap filling and outlier handling, between the history adapter and
the feature builder.

Three rules shape this module.

**Never silently discard a row.** A time series with rows removed is a
different series: every lag and rolling window steps over the hole and quietly
reads a value from further back than it claims to. Gaps are filled, or left as
NaN and *reported*, but the cadence stays regular.

**Never invent a long stretch of data.** Linear interpolation across two days
of missing chlorophyll is reasonable; across two months it is fabrication, and
this platform's stated rule is that a fabricated ocean reading is worse than
an absent one. `max_gap_steps` bounds it, and anything longer stays NaN — those
rows then cannot serve as training targets, which is the honest outcome.

**Outliers are neutralised, not deleted.** A spike is replaced with NaN and
refilled like any other gap, so the row survives with its timestamp intact.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from forecasting import ForecastingError
from forecasting.config import OutlierConfig
from services.download.models import Resolution

logger = logging.getLogger(__name__)

TIMESTAMP = "timestamp"

_FREQ: dict[Resolution, str] = {
    Resolution.hourly: "h",
    Resolution.daily: "D",
    Resolution.weekly: "W",
    Resolution.monthly: "MS",
}

# Steps of interpolation allowed across a gap, per cadence. Roughly a week of
# real time either way: long enough to bridge the routine holes in a satellite
# product, short enough that a genuine outage stays visible as missing.
_MAX_GAP_STEPS: dict[Resolution, int] = {
    Resolution.hourly: 168,
    Resolution.daily: 7,
    Resolution.weekly: 2,
    Resolution.monthly: 1,
}


class PreprocessingError(ForecastingError):
    """The series could not be made usable — too short, or entirely empty."""


@dataclass
class QualityReport:
    """What cleaning actually did. Surfaced in training metadata and in the
    API response, because "the model saw 640 rows, 11% of them interpolated"
    is a materially different claim from "the model saw 640 observations"."""

    rows: int = 0
    rows_added_by_regularisation: int = 0
    missing_before: dict[str, int] = field(default_factory=dict)
    filled: dict[str, int] = field(default_factory=dict)
    outliers_replaced: dict[str, int] = field(default_factory=dict)
    unfilled: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        total_filled = sum(self.filled.values())
        return {
            "rows": self.rows,
            "rows_added_by_regularisation": self.rows_added_by_regularisation,
            "missing_before": self.missing_before,
            "filled": self.filled,
            "outliers_replaced": self.outliers_replaced,
            "unfilled": self.unfilled,
            "interpolated_fraction": (
                round(total_filled / (self.rows * max(1, len(self.filled))), 4)
                if self.rows
                else 0.0
            ),
        }


# --------------------------------------------------------------------------
# Regularisation
# --------------------------------------------------------------------------


def regularise(
    frame: pd.DataFrame, resolution: Resolution, report: QualityReport
) -> pd.DataFrame:
    """Reindex onto a complete, evenly spaced time axis.

    This runs *before* anything else and is the step that makes lags mean what
    they say. A provider that skips a day hands back a frame where row t-1 is
    two days earlier, so `lag1` would silently become `lag2` for that stretch.
    Reindexing surfaces the hole as NaN instead, where the gap-filling policy
    below can make an explicit decision about it.
    """
    if frame.empty:
        raise PreprocessingError("cannot preprocess an empty series")

    frame = frame.sort_values(TIMESTAMP).drop_duplicates(subset=[TIMESTAMP])
    frame = frame.set_index(TIMESTAMP)

    full_index = pd.date_range(
        start=frame.index.min(), end=frame.index.max(), freq=_FREQ[resolution]
    )
    before = len(frame)
    frame = frame.reindex(full_index)
    report.rows_added_by_regularisation = len(frame) - before

    frame.index.name = TIMESTAMP
    return frame.reset_index()


# --------------------------------------------------------------------------
# Outliers
# --------------------------------------------------------------------------


def _hampel_mask(series: pd.Series, window: int, threshold: float) -> pd.Series:
    """Hampel filter: deviation from a rolling *median* in units of a rolling MAD.

    The default because it is the only one of the three that is robust to the
    thing it is detecting. A rolling mean and standard deviation are both
    dragged toward a spike, so a large enough outlier raises the fence above
    itself and escapes — precisely the case that matters. The median and MAD
    are not.

    The window is centred, which is legitimate here: this is data *cleaning*
    applied to the observed record before any target is constructed, not a
    feature. No cleaned value is ever used to predict an earlier timestamp.
    """
    rolling = series.rolling(window, center=True, min_periods=max(3, window // 3))
    median = rolling.median()
    # 1.4826 scales the median absolute deviation to be a consistent estimator
    # of the standard deviation for normally distributed data, so `threshold`
    # keeps its familiar "number of sigma" meaning.
    mad = 1.4826 * (series - median).abs().rolling(
        window, center=True, min_periods=max(3, window // 3)
    ).median()

    deviation = (series - median).abs()

    # A local MAD of exactly zero is common and means two opposite things, so
    # neither naive handling works:
    #
    #   * a stuck sensor or repeated fill value — every departure IS an outlier;
    #   * a smooth field that simply sits on its own rolling median — where
    #     departures are the ordinary signal.
    #
    # Measured on real Copernicus SST, the second case is the common one: 74 of
    # 367 daily values had zero local MAD purely because the series is smooth.
    # Flagging on any deviation there condemned 18% of a clean series as
    # outliers, and no threshold fixed it because the branch never consulted
    # the threshold. Falling back to the *global* MAD separates the two: it is
    # meaningful for a smooth series (so small wiggles pass) and is itself zero
    # for a genuinely flat one (so a spike in a stuck run still flags).
    global_mad = float(1.4826 * (series - series.median()).abs().median())
    scale = mad.fillna(global_mad).to_numpy()
    scale = np.where(scale > 0, scale, global_mad)

    flagged = np.where(
        scale > 0,
        deviation.to_numpy() > threshold * scale,
        # Both scales collapsed: the series is constant, so anything that is
        # not the constant is the outlier.
        deviation.to_numpy() > 0,
    )
    return pd.Series(flagged, index=series.index).fillna(False)


def _iqr_mask(series: pd.Series, threshold: float) -> pd.Series:
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    spread = q3 - q1
    if not np.isfinite(spread) or spread == 0:
        return pd.Series(False, index=series.index)
    return (series < q1 - threshold * spread) | (series > q3 + threshold * spread)


def _zscore_mask(series: pd.Series, threshold: float) -> pd.Series:
    std = series.std()
    if not np.isfinite(std) or std == 0:
        return pd.Series(False, index=series.index)
    return (series - series.mean()).abs() > threshold * std


def detect_outliers(
    series: pd.Series, config: OutlierConfig
) -> pd.Series:
    """Boolean mask of values to neutralise. Never mutates its input."""
    values = pd.to_numeric(series, errors="coerce")
    if config.method == "none" or values.notna().sum() < 5:
        return pd.Series(False, index=series.index)
    if config.method == "hampel":
        mask = _hampel_mask(values, config.window, config.threshold)
    elif config.method == "iqr":
        mask = _iqr_mask(values, config.threshold)
    else:
        mask = _zscore_mask(values, config.threshold)
    return mask.fillna(False) & values.notna()


# --------------------------------------------------------------------------
# Gap filling
# --------------------------------------------------------------------------

FillStrategy = Literal["interpolate_then_ffill", "ffill_then_interpolate"]


def fill_gaps(
    series: pd.Series,
    *,
    max_gap_steps: int,
    strategy: FillStrategy = "interpolate_then_ffill",
) -> pd.Series:
    """Fill interior gaps up to `max_gap_steps`, leaving longer ones NaN.

    The default order is interpolate-then-forward-fill, which is the one that
    does what both halves are for. Running a forward fill *first* converts
    every interior gap into a flat run of the last observed value, after which
    linear interpolation has nothing left to interpolate — the two steps do
    not compose in that order, they cancel. Interpolating first bridges
    interior gaps on a straight line (right for a smooth geophysical field),
    and the forward/backward fill then handles only the leading and trailing
    edges, which interpolation cannot reach.

    `ffill_then_interpolate` is kept because it is occasionally the correct
    choice — a cumulative or step-like field, where carrying the last value is
    more truthful than sloping between two.
    """
    values = pd.to_numeric(series, errors="coerce")
    if values.notna().sum() == 0:
        return values

    if strategy == "ffill_then_interpolate":
        filled = values.ffill(limit=max_gap_steps)
        filled = filled.interpolate(method="linear", limit=max_gap_steps, limit_area="inside")
    else:
        filled = values.interpolate(method="linear", limit=max_gap_steps, limit_area="inside")

    # Edge handling, restricted to the leading and trailing runs of NaN.
    #
    # The restriction is the whole point. `ffill`/`bfill` have no "outside
    # only" mode, so applying them to the full series lets them chew into
    # interior gaps that interpolation had *deliberately* refused: a 20-step
    # hole with a 7-step allowance ends up fully filled by 7 interpolated +
    # 7 forward + 7 backward, which is exactly the fabrication `max_gap_steps`
    # exists to prevent.
    first, last = values.first_valid_index(), values.last_valid_index()
    if first is not None:
        head = filled.loc[:first]
        filled.loc[:first] = head.bfill(limit=max_gap_steps)
    if last is not None:
        tail = filled.loc[last:]
        filled.loc[last:] = tail.ffill(limit=max_gap_steps)

    return filled


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


def clean(
    frame: pd.DataFrame,
    value_columns: Sequence[str],
    *,
    resolution: Resolution = Resolution.daily,
    outliers: OutlierConfig | None = None,
    fill_strategy: FillStrategy = "interpolate_then_ffill",
    max_gap_steps: int | None = None,
) -> tuple[pd.DataFrame, QualityReport]:
    """Regularise -> neutralise outliers -> fill gaps, reporting each stage.

    Returns the cleaned frame and a `QualityReport`. Columns not in
    `value_columns` (latitude, longitude, and any static passthrough) are
    carried through and edge-filled, since they are constant for a point
    series and a NaN in them would poison every feature row.
    """
    outliers = outliers or OutlierConfig()
    limit = max_gap_steps if max_gap_steps is not None else _MAX_GAP_STEPS[resolution]

    report = QualityReport()
    frame = regularise(frame, resolution, report)
    report.rows = len(frame)

    present = [column for column in value_columns if column in frame.columns]
    if not present:
        raise PreprocessingError(
            f"none of the requested columns {list(value_columns)} are in the series "
            f"(have: {[c for c in frame.columns if c != TIMESTAMP]})"
        )

    for column in present:
        original = pd.to_numeric(frame[column], errors="coerce")
        report.missing_before[column] = int(original.isna().sum())

        mask = detect_outliers(original, outliers)
        report.outliers_replaced[column] = int(mask.sum())
        neutralised = original.mask(mask)

        filled = fill_gaps(
            neutralised, max_gap_steps=limit, strategy=fill_strategy
        )
        report.filled[column] = int((neutralised.isna() & filled.notna()).sum())
        report.unfilled[column] = int(filled.isna().sum())
        frame[column] = filled

    # Static/positional columns: constant down a point series, so a plain
    # ffill+bfill is exact rather than an approximation.
    for column in frame.columns:
        if column == TIMESTAMP or column in present:
            continue
        if pd.api.types.is_numeric_dtype(frame[column]):
            frame[column] = frame[column].ffill().bfill()

    unfilled_total = sum(report.unfilled.values())
    if unfilled_total:
        logger.info(
            f"{unfilled_total} values remain missing after filling "
            f"(gaps longer than {limit} steps are left as NaN by design)"
        )
    return frame, report
