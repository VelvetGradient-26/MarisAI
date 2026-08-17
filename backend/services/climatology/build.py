"""Fit a per-cell, per-day-of-year percentile climatology.

Fit and apply are two functions
-------------------------------
`fit_percentiles` reads a record and returns thresholds; `apply_percentiles`
takes thresholds and scores an observation. Never one function that does both.
This is the same rule `machine_learning/` states for every fit/apply pair and
`forecasting/climatology.py` states for its own: a threshold fitted over the
period it is later evaluated on leaks that period into the *definition of the
event*, not merely into a feature. Splitting them makes fitting on the wrong
rows take deliberate effort.

Two constructions here are load-bearing and both are wrong in the obvious
implementation:

**The day-of-year index is leap-adjusted.** `pandas`' `dayofyear` puts 1 March
at 60 in a common year and 61 in a leap year, so pooling raw day-of-year across
30 years silently mixes samples one day apart in a common year with samples two
days apart in a leap year — and worse, aligns March with late February. Every
date here is mapped to a fixed 1..366 index in which 29 February is 60 and
1 March is *always* 61. The cost is that index 60 pools only leap years, which
is why it is filled from its neighbours rather than left thin.

**The window wraps the year.** 1 January's +/-5 day window has to reach back
into the previous December. A non-wrapping window makes the two ends of the year
disagree with each other by construction, and the discontinuity lands exactly on
the date the northern hemisphere is coldest and the southern hemisphere is
warmest.
"""

from __future__ import annotations

import warnings
from datetime import date, datetime

import numpy as np
import pandas as pd
import xarray as xr

DAYS_IN_YEAR = 366

# The WMO standard 30-year reference period. Stated as a constant rather than
# defaulted inline so a rebuild on a different window is a visible edit — the
# baseline period is the single biggest determinant of what counts as an
# extreme, and a climatology whose window nobody can name is not usable
# evidence.
DEFAULT_BASELINE_START = 1991
DEFAULT_BASELINE_END = 2020

# +/-5 days, i.e. an 11-day pooling window. With 30 years that is 330 samples
# per estimate, which is the standard construction for a daily percentile
# climatology and what Hobday et al. use. `forecasting/climatology.py` pools
# +/-15 days for the opposite reason — it has ~2.2 years of record and a bare
# day-of-year mean there would be an average of two samples.
DEFAULT_WINDOW_DAYS = 5

# What gets computed. p90 is the marine-heatwave threshold; p10 is its cold-spell
# mirror; the mean is kept because an anomaly is the more common question and
# recomputing it from a second source would be a second answer.
PERCENTILES = (10, 90)

# **The completeness requirement is per estimate, not per year**, and that is a
# correction rather than a preference. The OISST aggregate is genuinely gappy in
# the early record — 1993 carries 163 days against 1991's 365, verified as the
# archive's own content and not a transport failure (see `oisst.verify_span`) —
# so a per-year floor would reject a real 30-year baseline forever.
#
# A day-of-year percentile does not care which years its samples came from; it
# cares how many there are. With a +/-5 day window over 30 complete years an
# estimate draws on 330 samples, so this floor is comfortably below a healthy
# build while still catching a record too thin to fit a 90th percentile at all.
MIN_SAMPLES_PER_ESTIMATE = 100


class ClimatologyBuildError(RuntimeError):
    """The record cannot support the climatology being asked for."""


def day_index(when: pd.DatetimeIndex | pd.Series) -> np.ndarray:
    """Leap-adjusted day-of-year in 1..366, where 60 is always 29 February.

    In a common year every date from 1 March onward is shifted up by one, so a
    given index means the same point in the seasonal cycle in every year.
    """
    stamps = pd.DatetimeIndex(when)
    # `np.asarray` rather than `.to_numpy()`: pandas 3 returns a bare ndarray
    # from `is_leap_year` and an Index from `dayofyear`, so only one of the two
    # has the method.
    doy = np.asarray(stamps.dayofyear, dtype="int64")
    is_leap = np.asarray(stamps.is_leap_year, dtype=bool)
    past_february = doy >= 60
    # Common year, on or after 1 March (raw doy 60): shift to 61+.
    return np.where(~is_leap & past_february, doy + 1, doy)


def window_indices(index: int, window_days: int) -> np.ndarray:
    """The circular +/-window day indices around `index`, in 1..366."""
    offsets = np.arange(-window_days, window_days + 1)
    return ((index - 1 + offsets) % DAYS_IN_YEAR) + 1


def fit_percentiles(
    record: xr.DataArray,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    percentiles: tuple[int, ...] = PERCENTILES,
) -> xr.Dataset:
    """Per-cell, per-day-of-year percentiles and mean over a daily record.

    `record` is `(time, latitude, longitude)`. The caller is responsible for
    having restricted it to the baseline period — that is the point of the
    split, and `build_climatology` is the function that does so.
    """
    if not isinstance(record, xr.DataArray):
        # A Dataset gets a long way in before failing on `.values` being a
        # bound method, and the resulting AttributeError names neither problem.
        raise ClimatologyBuildError(
            "fit_percentiles takes a DataArray; select the variable first"
        )
    if "time" not in record.dims:
        raise ClimatologyBuildError("record must carry a `time` dimension")

    stamps = pd.DatetimeIndex(record["time"].values)
    indices = day_index(stamps)
    values = record.values  # (time, lat, lon)

    shape = (DAYS_IN_YEAR, values.shape[1], values.shape[2])
    outputs = {f"p{p}": np.full(shape, np.nan, dtype="float32") for p in percentiles}
    outputs["mean"] = np.full(shape, np.nan, dtype="float32")
    counts = np.zeros(DAYS_IN_YEAR, dtype="int32")

    # Group once rather than searching the record per day: 366 boolean scans
    # over a 30-year index is cheap, but 366 * 11 of them is not.
    by_index: dict[int, np.ndarray] = {}
    for position, idx in enumerate(indices):
        by_index.setdefault(int(idx), []).append(position)
    by_index = {k: np.asarray(v) for k, v in by_index.items()}

    for target in range(1, DAYS_IN_YEAR + 1):
        positions = np.concatenate(
            [by_index[i] for i in window_indices(target, window_days) if i in by_index]
            or [np.empty(0, dtype="int64")]
        )
        counts[target - 1] = positions.size
        if positions.size == 0:
            continue
        window = values[positions]
        # nan-aware throughout: land and ice-masked cells are NaN in OISST, and
        # a cell that is NaN for the whole window must stay NaN rather than
        # becoming 0.
        # An all-NaN column is the *expected* case over land, not an anomaly, so
        # its warning is suppressed rather than left to fire once per day-of-year
        # per build. The `all_nan` mask below is what actually handles it.
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            all_nan = np.all(np.isnan(window), axis=0)
            for p in percentiles:
                estimate = np.nanpercentile(window, p, axis=0)
                outputs[f"p{p}"][target - 1] = np.where(all_nan, np.nan, estimate)
            mean = np.nanmean(window, axis=0)
            outputs["mean"][target - 1] = np.where(all_nan, np.nan, mean)

    result = xr.Dataset(
        {
            name: (("dayofyear", "latitude", "longitude"), array)
            for name, array in outputs.items()
        },
        coords={
            "dayofyear": np.arange(1, DAYS_IN_YEAR + 1, dtype="int32"),
            "latitude": record["latitude"].values,
            "longitude": record["longitude"].values,
        },
    )
    result["samples"] = ("dayofyear", counts)
    result["samples"].attrs["long_name"] = (
        "observations pooled per day-of-year estimate; index 60 (29 February) "
        "draws on leap years only and is correspondingly thin"
    )
    result.attrs["window_days"] = window_days
    result.attrs["percentiles"] = list(percentiles)
    return result


def apply_percentiles(
    observation: xr.DataArray,
    climatology: xr.Dataset,
    *,
    when: date | datetime | None = None,
) -> xr.Dataset:
    """Score an observed field against a fitted climatology.

    Returns `anomaly` (observation minus the climatological mean) and
    `exceedance` (observation minus p90, positive where the field is above its
    seasonal 90th percentile). Both are the observation's own grid; the
    climatology is selected to the observation's day and must already share the
    grid, which `build_climatology` guarantees by construction.
    """
    stamp = when
    if stamp is None:
        stamp = pd.Timestamp(observation["time"].values.ravel()[0]).to_pydatetime()
    index = int(day_index(pd.DatetimeIndex([pd.Timestamp(stamp)]))[0])
    slice_ = climatology.sel(dayofyear=index)

    if slice_["latitude"].size != observation["latitude"].size:
        raise ClimatologyBuildError(
            "observation and climatology are on different grids; regrid before "
            "applying rather than letting xarray align and silently drop cells"
        )

    return xr.Dataset(
        {
            "anomaly": observation - slice_["mean"].values,
            "exceedance": observation - slice_["p90"].values,
        }
    )


def build_climatology(
    record: xr.Dataset,
    *,
    variable: str,
    baseline_start: int = DEFAULT_BASELINE_START,
    baseline_end: int = DEFAULT_BASELINE_END,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_samples: int = MIN_SAMPLES_PER_ESTIMATE,
) -> xr.Dataset:
    """Restrict a record to the baseline period, then fit.

    The restriction lives here, not in `fit_percentiles`, so that a caller who
    wants to fit on a deliberately different span (a test, a sensitivity check)
    can do so without this function's opinion, and a caller who does not think
    about it at all gets the standard window.
    """
    if variable not in record:
        raise ClimatologyBuildError(
            f"{variable!r} is not in the record (have: {', '.join(map(str, record.data_vars))})"
        )

    stamps = pd.DatetimeIndex(record["time"].values)
    years = stamps.year.to_numpy()
    inside = (years >= baseline_start) & (years <= baseline_end)
    if not inside.any():
        raise ClimatologyBuildError(
            f"record covers {years.min()}-{years.max()}, which does not overlap "
            f"the {baseline_start}-{baseline_end} baseline"
        )

    covered = sorted(set(years[inside].tolist()))
    missing = [y for y in range(baseline_start, baseline_end + 1) if y not in covered]
    if missing:
        raise ClimatologyBuildError(
            f"baseline {baseline_start}-{baseline_end} is missing {len(missing)} "
            f"year(s): {missing[:5]}{'...' if len(missing) > 5 else ''}. A "
            "percentile fitted on a partial baseline is not the baseline it "
            "claims to be."
        )

    fitted = fit_percentiles(
        record[variable].isel(time=np.flatnonzero(inside)),
        window_days=window_days,
    )
    # The floor that actually protects the artifact. Checked after fitting
    # because `samples` is what the fit measured, and a count derived
    # separately here would be a second answer to the same question.
    thin = int((fitted["samples"].values < min_samples).sum())
    if thin:
        worst = int(fitted["samples"].values.min())
        raise ClimatologyBuildError(
            f"{thin} of {DAYS_IN_YEAR} day-of-year estimates draw on fewer than "
            f"{min_samples} samples (thinnest: {worst}). The record "
            "is too sparse for a percentile at this window width — widen the "
            "window or extend the baseline rather than shipping it."
        )

    days_used = int(inside.sum())
    expected_days = (date(baseline_end, 12, 31) - date(baseline_start, 1, 1)).days + 1
    fitted.attrs.update(
        {
            "min_samples_per_estimate": min_samples,
            "variable": variable,
            "baseline_start": baseline_start,
            "baseline_end": baseline_end,
            "baseline_years": len(covered),
            # Stated rather than implied. The OISST archive is gappy in the
            # early 1990s, so a "1991-2020 baseline" is not 10,957 days, and a
            # reader comparing two builds needs to see which record each had.
            "baseline_days_used": days_used,
            "baseline_days_in_period": expected_days,
            "baseline_completeness": round(days_used / expected_days, 4),
            "source": "NOAA OISST v2.1 (ncdcOisst21Agg_LonPM180) via CoastWatch ERDDAP",
            "units": str(record[variable].attrs.get("units", "")),
        }
    )
    return fitted
