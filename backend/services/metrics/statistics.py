"""Descriptive statistics for the metric page's KPI strip.

The rule the whole module is built around, inherited from the dashboard: **a
statistic that cannot be computed is reported absent, never as zero.** A
365-day change is genuinely impossible for a product whose record started
eight months ago. Rendering that as "0.00" would be a false claim that the
ocean did not change; rendering it as "needs 365 days, record starts
2024-06-13" is the truth and tells the reader what to do about it.

Every entry therefore carries `available` and, when false, an
`unavailable_reason` — the same contract `services/dashboard/summary.py` uses
for KPI cards, so the frontend renders both through one component.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from forecasting.preprocessing import TIMESTAMP
from services.metrics import MetricsError
from services.metrics.series import load_frame

logger = logging.getLogger(__name__)

# Below this a distribution statistic is describing noise. Skewness and
# kurtosis in particular are unstable on small samples — the textbook guidance
# is that they need hundreds of observations to mean anything, and reporting a
# kurtosis from 20 points would dress a coin flip as a measurement.
_MIN_DISTRIBUTION_SAMPLES = 30


@dataclass(frozen=True)
class Statistic:
    """One KPI. Absent statistics say why rather than showing a number."""

    key: str
    label: str
    value: float | None
    unit: str
    available: bool = True
    unavailable_reason: str | None = None
    # Free-text qualifier shown under the value ("over 365 days",
    # "vs 2024-08-04"), so a number is never presented without its window.
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": round(self.value, 4) if self.value is not None else None,
            "unit": self.unit,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "detail": self.detail,
        }


def _absent(key: str, label: str, unit: str, reason: str) -> Statistic:
    return Statistic(
        key=key, label=label, value=None, unit=unit,
        available=False, unavailable_reason=reason,
    )


def _change_over(
    series: pd.Series,
    stamps: pd.Series,
    days: int,
    *,
    key: str,
    label: str,
    unit: str,
) -> Statistic:
    """Change between the latest value and the one `days` ago.

    Compared against the *nearest observation at or before* the target date
    rather than the row `days` positions back. Those differ whenever the
    series has gaps, and using position would silently compare against
    whatever happens to be that many rows earlier — a 30-day change measured
    across 47 real days.
    """
    if series.empty:
        return _absent(key, label, unit, "no observations in the record")

    latest_time = stamps.iloc[-1]
    target = latest_time - pd.Timedelta(days=days)
    earliest_time = stamps.iloc[0]

    if target < earliest_time:
        span = (latest_time - earliest_time).days
        return _absent(
            key, label, unit,
            f"needs {days} days of record; only {span} available "
            f"(data begins {earliest_time.date()})",
        )

    prior = series[stamps <= target]
    if prior.empty or not np.isfinite(prior.iloc[-1]):
        return _absent(key, label, unit, f"no observation near {target.date()}")

    delta = float(series.iloc[-1] - prior.iloc[-1])
    return Statistic(
        key=key, label=label, value=delta, unit=unit,
        detail=f"vs {target.date()}",
    )


def compute(frame: pd.DataFrame, column: str, unit: str) -> list[Statistic]:
    """The KPI strip for one cleaned series."""
    stamps = pd.to_datetime(frame[TIMESTAMP]).reset_index(drop=True)
    values = pd.to_numeric(frame[column], errors="coerce").reset_index(drop=True)

    finite = values[np.isfinite(values)]
    if finite.empty:
        raise MetricsError("the record contains no usable observations")

    current = float(values.dropna().iloc[-1])
    count = int(finite.size)

    statistics: list[Statistic] = [
        Statistic("current", "Current", current, unit,
                  detail=f"as of {stamps.iloc[-1].date()}"),
        Statistic("mean", "Average", float(finite.mean()), unit,
                  detail=f"over {count} observations"),
        Statistic("median", "Median", float(finite.median()), unit),
        Statistic("min", "Minimum", float(finite.min()), unit,
                  detail=str(stamps[values == finite.min()].iloc[0].date())
                  if (values == finite.min()).any() else None),
        Statistic("max", "Maximum", float(finite.max()), unit,
                  detail=str(stamps[values == finite.max()].iloc[0].date())
                  if (values == finite.max()).any() else None),
        # Sample standard deviation (ddof=1), not population: this is a sample
        # of a continuing process, not the whole of it.
        Statistic("std", "Std deviation", float(finite.std(ddof=1)) if count > 1 else None,
                  unit, available=count > 1,
                  unavailable_reason=None if count > 1 else "needs at least 2 observations"),
        Statistic("variance", "Variance", float(finite.var(ddof=1)) if count > 1 else None,
                  f"{unit}²", available=count > 1,
                  unavailable_reason=None if count > 1 else "needs at least 2 observations"),
    ]

    # Where the current value sits in its own historical distribution — the
    # single most useful number on the strip, because it turns "28.3 °C" into
    # "warmer than 94% of the record".
    percentile = float((finite <= current).mean() * 100.0)
    statistics.append(
        Statistic("percentile", "Percentile", percentile, "%",
                  detail="of the loaded record")
    )

    statistics.append(
        _change_over(values, stamps, 30, key="change_30d", label="30-day change", unit=unit)
    )
    statistics.append(
        _change_over(values, stamps, 365, key="change_365d", label="365-day change", unit=unit)
    )

    if count >= _MIN_DISTRIBUTION_SAMPLES:
        statistics.append(
            Statistic("skewness", "Skewness", float(finite.skew()), "",
                      detail="0 is symmetric")
        )
        statistics.append(
            # pandas returns *excess* kurtosis (normal = 0), which is the
            # convention worth stating since the raw form (normal = 3) is also
            # common and the two differ by exactly 3.
            Statistic("kurtosis", "Kurtosis", float(finite.kurtosis()), "",
                      detail="excess; 0 is normal")
        )
    else:
        reason = (
            f"needs {_MIN_DISTRIBUTION_SAMPLES} observations, have {count} — "
            f"a shape statistic from fewer is noise"
        )
        statistics.append(_absent("skewness", "Skewness", "", reason))
        statistics.append(_absent("kurtosis", "Kurtosis", "", reason))

    return statistics


async def build(
    variable_key: str,
    latitude: float,
    longitude: float,
    *,
    range_key: str | None = None,
    days: int | None = None,
) -> dict[str, Any]:
    """Fetch, clean and summarise one variable at one point."""
    frame, variable, extra = await load_frame(
        variable_key, latitude, longitude, range_key=range_key, days=days
    )
    history = extra["series"]

    statistics = compute(frame, variable.code, variable.unit)
    stamps = pd.to_datetime(frame[TIMESTAMP])

    return {
        "variable": variable_key,
        "label": variable.label,
        "unit": variable.unit,
        "category": variable.category,
        "latitude": round(history.latitude, 4),
        "longitude": round(history.longitude, 4),
        "start": stamps.min().date().isoformat(),
        "end": stamps.max().date().isoformat(),
        "observation_count": int(pd.to_numeric(frame[variable.code], errors="coerce").notna().sum()),
        "statistics": [statistic.as_dict() for statistic in statistics],
        "coverage_start": _iso(history.coverage.get(variable.code)),
        "sources": history.sources,
        "quality": extra["quality"],
    }


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None
