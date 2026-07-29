"""Shared temporal features: climatological anomalies, lags, rolling statistics.

The single most important property of this module is that **nothing here may
look forward in time**. Every function computes, for row at time t, a value
that depended only on data available at or before t. Lags shift backwards,
rolling windows are trailing and closed on the left, and climatologies are
fitted on the training period alone and then applied.

The doc's validation section is built around leakage-free splitting; that only
holds if the features themselves are leakage-free, which is where it is
actually easy to get wrong. A rolling mean centred on t, or a climatology
fitted over the full record including the test years, silently leaks the
future into training and inflates every metric downstream.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Cyclical time encoding
# --------------------------------------------------------------------------


def cyclical_time_features(dates: pd.Series) -> pd.DataFrame:
    """sin/cos encodings of day-of-year and month.

    Raw integers put an artificial discontinuity between 31 December and
    1 January, which for a strongly seasonal, monsoon-driven system is exactly
    the wrong inductive bias. sin/cos wrap smoothly.
    """
    dates = pd.to_datetime(dates)
    day_of_year = dates.dt.dayofyear.astype("float64")
    month = dates.dt.month.astype("float64")

    # 366 keeps leap years on the same circle rather than overshooting 2*pi.
    doy_angle = 2.0 * np.pi * day_of_year / 366.0
    month_angle = 2.0 * np.pi * (month - 1.0) / 12.0

    return pd.DataFrame(
        {
            "doy_sin": np.sin(doy_angle),
            "doy_cos": np.cos(doy_angle),
            "month_sin": np.sin(month_angle),
            "month_cos": np.cos(month_angle),
        },
        index=dates.index,
    )


def monsoon_phase(dates: pd.Series) -> pd.Series:
    """Indian monsoon phase as a categorical feature.

    The northern Indian Ocean's productivity cycle is monsoon-driven: the
    southwest monsoon upwelling season and the northeast monsoon convective
    mixing season have different bloom and fish-aggregation regimes, and a
    smooth day-of-year encoding alone does not capture that they are
    qualitatively different states.
    """
    month = pd.to_datetime(dates).dt.month
    phase = pd.Series("pre_monsoon", index=month.index, dtype="object")
    phase[month.isin((6, 7, 8, 9))] = "southwest_monsoon"
    phase[month.isin((10, 11))] = "post_monsoon"
    phase[month.isin((12, 1, 2))] = "northeast_monsoon"
    phase[month.isin((3, 4, 5))] = "pre_monsoon"
    return phase.astype("category")


# --------------------------------------------------------------------------
# Climatology & anomalies
# --------------------------------------------------------------------------


def fit_climatology(
    frame: pd.DataFrame,
    value_columns: Sequence[str],
    group_columns: Sequence[str] = ("latitude", "longitude"),
    period: str = "month",
) -> pd.DataFrame:
    """Per-cell, per-season mean and standard deviation of each value column.

    **Fit this on training rows only.** Passing the whole dataset is the
    classic way to leak the test period's mean into training features.

    ``period`` is ``"month"`` or ``"dayofyear"``; monthly is the right
    granularity unless there are many years of daily data, since a
    per-day-of-year mean over a handful of years is mostly noise.
    """
    frame = frame.copy()
    frame[period] = _period_index(frame["date"], period)
    keys = list(group_columns) + [period]

    aggregated = frame.groupby(keys, observed=True)[list(value_columns)].agg(["mean", "std"])
    aggregated.columns = [f"{col}_clim_{stat}" for col, stat in aggregated.columns]
    return aggregated.reset_index()


def apply_climatology(
    frame: pd.DataFrame,
    climatology: pd.DataFrame,
    value_columns: Sequence[str],
    group_columns: Sequence[str] = ("latitude", "longitude"),
    period: str = "month",
) -> pd.DataFrame:
    """Join a fitted climatology and derive anomalies and standardised anomalies.

    For each column ``x`` this adds ``x_anomaly`` (value minus the local
    seasonal mean) and ``x_zanomaly`` (that anomaly divided by the local
    seasonal standard deviation). The z-form is what makes a threshold
    comparable across regimes — an absolute chlorophyll cutoff that is extreme
    in the open ocean is unremarkable in a coastal upwelling zone, which is
    precisely why the doc rejects a single global cutoff.
    """
    frame = frame.copy()
    frame[period] = _period_index(frame["date"], period)
    keys = list(group_columns) + [period]

    merged = frame.merge(climatology, on=keys, how="left")

    for column in value_columns:
        mean_col = f"{column}_clim_mean"
        std_col = f"{column}_clim_std"
        if mean_col not in merged.columns:
            continue
        merged[f"{column}_anomaly"] = merged[column] - merged[mean_col]
        # Guard against a zero/absent standard deviation (a cell observed once
        # in the training period) producing an infinite z-score.
        std = merged[std_col].replace(0.0, np.nan)
        merged[f"{column}_zanomaly"] = merged[f"{column}_anomaly"] / std

    return merged.drop(columns=[period])


def _period_index(dates: pd.Series, period: str) -> pd.Series:
    dates = pd.to_datetime(dates)
    if period == "month":
        return dates.dt.month
    if period == "dayofyear":
        return dates.dt.dayofyear
    raise ValueError(f"unsupported climatology period {period!r}")


# --------------------------------------------------------------------------
# Lags & rolling statistics
# --------------------------------------------------------------------------


def add_lag_features(
    frame: pd.DataFrame,
    value_columns: Sequence[str],
    lags: Iterable[int],
    group_columns: Sequence[str] = ("latitude", "longitude"),
    date_column: str = "date",
    freq_days: int = 1,
) -> pd.DataFrame:
    """Add ``{column}_lag{n}`` columns, shifted ``n`` days backwards per cell.

    Shifting is done on the *date*, not on row position, so gaps in a cell's
    time series produce NaN rather than silently pulling in whatever record
    happens to be adjacent in the frame. ``freq_days`` is the cadence of the
    series (1 for daily fields, ~30 for monthly), used to translate a lag in
    days into a number of steps.
    """
    frame = frame.sort_values(list(group_columns) + [date_column]).copy()
    grouped = frame.groupby(list(group_columns), observed=True, sort=False)

    for lag_days in lags:
        steps = max(1, round(lag_days / freq_days))
        for column in value_columns:
            frame[f"{column}_lag{lag_days}"] = grouped[column].shift(steps)

    return frame


def add_rolling_features(
    frame: pd.DataFrame,
    value_columns: Sequence[str],
    windows: Iterable[int],
    group_columns: Sequence[str] = ("latitude", "longitude"),
    date_column: str = "date",
    freq_days: int = 1,
    statistics: Sequence[str] = ("mean", "std"),
) -> pd.DataFrame:
    """Add trailing rolling statistics per cell.

    The window is shifted by one step before aggregating, so the value at time
    t summarises strictly *earlier* observations and never includes t itself.
    """
    frame = frame.sort_values(list(group_columns) + [date_column]).copy()
    grouped = frame.groupby(list(group_columns), observed=True, sort=False)

    for window_days in windows:
        steps = max(2, round(window_days / freq_days))
        for column in value_columns:
            shifted = grouped[column].shift(1)
            roller = shifted.groupby(
                [frame[col] for col in group_columns], observed=True, sort=False
            ).rolling(steps, min_periods=max(2, steps // 2))
            for statistic in statistics:
                values = getattr(roller, statistic)().reset_index(
                    level=list(range(len(group_columns))), drop=True
                )
                frame[f"{column}_roll{window_days}_{statistic}"] = values

    return frame


def add_difference_features(
    frame: pd.DataFrame,
    value_columns: Sequence[str],
    group_columns: Sequence[str] = ("latitude", "longitude"),
    date_column: str = "date",
    order: int = 2,
) -> pd.DataFrame:
    """Add first and (optionally) second differences per cell.

    Blooms are as much about rate-of-change as absolute level: chlorophyll
    climbing steeply from a low base is a developing bloom, the same value
    while flat is not (doc 3.4, "bloom growth rate").
    """
    frame = frame.sort_values(list(group_columns) + [date_column]).copy()
    grouped = frame.groupby(list(group_columns), observed=True, sort=False)

    for column in value_columns:
        first = grouped[column].diff()
        frame[f"{column}_delta"] = first
        if order >= 2:
            frame[f"{column}_accel"] = frame.groupby(
                list(group_columns), observed=True, sort=False
            )[f"{column}_delta"].diff()

    return frame
