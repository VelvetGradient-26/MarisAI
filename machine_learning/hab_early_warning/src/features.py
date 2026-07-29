"""HAB feature engineering (approach doc 3.4).

Everything here is strictly backward-looking. The targets in ``labels.py``
shift forward; the features must not, and the split between the two files is
deliberate so that the one forward shift in the codebase is easy to find and
audit.

The features that carry the physics:

* **Bloom growth rate** — first and second differences of chlorophyll. A
  bloom is a trajectory, not a level: chlorophyll climbing steeply off a low
  base is a developing bloom, the same value while flat is not.
* **Standardised anomalies** — value minus the local seasonal mean, over the
  local seasonal standard deviation. This is what makes "elevated" mean the
  same thing in a coastal upwelling zone and the open ocean.
* **Upwelling index** — Bakun-style, from wind stress. The nutrient-injection
  mechanism that precedes many coastal blooms.
* **Nutrient ratios** — N:P and N:Si departures from the Redfield ratio, a
  proxy for which phytoplankton functional group is favoured. Silicate
  depletion relative to nitrogen shifts the advantage from diatoms toward
  the flagellates that dominate harmful blooms, so this ratio carries
  information the raw concentrations do not.
* **Stratification proxy** — shallow, warm, strongly-stratified water retains
  a bloom near the surface instead of mixing it away.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from marine_ml.features import temporal

# Redfield ratios: the canonical C:N:P:Si stoichiometry of marine plankton.
REDFIELD_N_TO_P = 16.0
REDFIELD_N_TO_SI = 1.0

LAG_DAYS = (3, 7, 14, 30)
ROLLING_WINDOWS = (7, 14, 30)

# Columns excluded from model input: the targets, the label machinery, and
# raw identifiers. `chl` itself stays in — the current level is legitimate
# input to forecasting the future level. `threshold` and `bloom_exceedance`
# must not: they are derived from the label definition, and `is_bloom` at
# time t is fair game as a feature while `bloom_t{h}` is the answer.
EXCLUDED_PREFIXES = ("bloom_t", "chl_t", "threshold_t")
EXCLUDED = {
    "latitude", "longitude", "date", "season", "threshold",
    "bloom_exceedance", "region",
}


class FeatureError(RuntimeError):
    """Raised when HAB features cannot be built."""


def build_features(
    frame: pd.DataFrame,
    lags: tuple[int, ...] = LAG_DAYS,
    windows: tuple[int, ...] = ROLLING_WINDOWS,
) -> pd.DataFrame:
    """Derive the full backward-looking HAB feature set from a gridded frame."""
    working = frame.sort_values(["latitude", "longitude", "date"]).copy()

    working = _add_nutrient_ratios(working)
    working = _add_stratification(working)
    working = _add_upwelling(working)

    # Upwelling is lagged deliberately: nutrient injection precedes the bloom
    # it feeds by days to weeks, so the concurrent value is the wrong question
    # and the lagged one is the whole point of having wind at all.
    lag_columns = [
        c
        for c in ("chl", "thetao", "no3", "po4", "si", "nppv", "mlotst",
                  "upwelling_index", "ekman_pumping", "wind_stress_magnitude")
        if c in working.columns
    ]
    working = temporal.add_lag_features(working, lag_columns, lags, freq_days=1)

    roll_columns = [
        c
        for c in ("chl", "thetao", "current_speed", "upwelling_index",
                  "ekman_pumping", "wind_speed")
        if c in working.columns
    ]
    working = temporal.add_rolling_features(working, roll_columns, windows, freq_days=1)

    diff_columns = [c for c in ("chl", "thetao") if c in working.columns]
    working = temporal.add_difference_features(working, diff_columns)

    cyclical = temporal.cyclical_time_features(working["date"])
    working = pd.concat(
        [working.reset_index(drop=True), cyclical.reset_index(drop=True)], axis=1
    )
    working["monsoon_phase"] = temporal.monsoon_phase(working["date"])

    return working


def _add_nutrient_ratios(frame: pd.DataFrame) -> pd.DataFrame:
    """N:P and N:Si ratios and their departures from Redfield stoichiometry."""
    result = frame.copy()
    if {"no3", "po4"} <= set(result.columns):
        # Guard the denominator: phosphate goes to ~0 in depleted surface
        # water, and an unguarded ratio would produce infinities exactly
        # where the signal is most interesting.
        po4 = result["po4"].where(result["po4"] > 1e-6)
        result["n_to_p"] = result["no3"] / po4
        result["n_to_p_anomaly"] = result["n_to_p"] - REDFIELD_N_TO_P
    if {"no3", "si"} <= set(result.columns):
        si = result["si"].where(result["si"] > 1e-6)
        result["n_to_si"] = result["no3"] / si
        result["n_to_si_anomaly"] = result["n_to_si"] - REDFIELD_N_TO_SI
    return result


def _add_stratification(frame: pd.DataFrame) -> pd.DataFrame:
    """Stratification proxies from mixed layer depth and temperature."""
    result = frame.copy()
    if "mlotst" in result.columns:
        # Shallow mixed layer => strong stratification => bloom retention.
        result["stratification_index"] = 1.0 / (1.0 + result["mlotst"])
        result["log_mld"] = np.log1p(result["mlotst"].clip(lower=0))
        if "thetao" in result.columns:
            # Warm water over a shallow mixed layer is the strongest
            # retention signal; the product captures the interaction that
            # neither term expresses alone.
            result["warm_shallow_index"] = result["thetao"] / (1.0 + result["mlotst"])
    return result


def _add_upwelling(frame: pd.DataFrame) -> pd.DataFrame:
    """Wind-driven upwelling features.

    The real Bakun index and Ekman pumping are computed in the fusion layer
    from **observed** scatterometer wind stress, so this function only derives
    the interaction terms on top of them.

    The surface-current proxy below is a fallback for frames built without
    wind (the habitat pipeline's monthly means). It is a genuine proxy, not an
    equivalent: meridional current is the *result* of Ekman transport among
    other things, not the forcing, so it conflates the driver with everything
    else moving the water.
    """
    result = frame.copy()

    if "upwelling_index" in result.columns:
        # Upwelling only injects nutrients where the water column is shallow
        # enough for the pumped water to reach the euphotic zone, so the
        # interaction with mixed-layer depth carries more signal than either
        # term alone.
        if "mlotst" in result.columns:
            result["upwelling_x_stratification"] = result["upwelling_index"] / (
                1.0 + result["mlotst"]
            )
        # Upwelling-favourable only; downwelling is a different regime rather
        # than "negative upwelling", and separating them lets the model treat
        # them as such.
        result["upwelling_favourable"] = result["upwelling_index"].clip(lower=0)
    elif "vo" in result.columns:
        result["upwelling_proxy"] = -result["vo"]
        if "current_speed" in result.columns:
            result["upwelling_intensity"] = (
                result["upwelling_proxy"] * result["current_speed"]
            )

    return result


def add_anomalies(
    frame: pd.DataFrame,
    climatology: pd.DataFrame,
    columns: tuple[str, ...] = ("chl", "thetao"),
) -> pd.DataFrame:
    """Attach climatological anomalies from a climatology fitted on training rows."""
    present = [c for c in columns if c in frame.columns]
    return temporal.apply_climatology(frame, climatology, present)


def add_marine_heatwave_flag(
    frame: pd.DataFrame,
    percentile: float = 90.0,
    min_duration_days: int = 5,
) -> pd.DataFrame:
    """Hobday-style marine heatwave flag: SST above the local seasonal 90th
    percentile for at least 5 consecutive days.

    The duration requirement is the part that matters — a single warm day is
    weather, five consecutive is an event with ecological consequences, and
    the doc names the Hobday definition specifically for this reason.
    """
    if "thetao_zanomaly" not in frame.columns:
        return frame

    from scipy.stats import norm

    working = frame.sort_values(["latitude", "longitude", "date"]).copy()
    # Working in standardised-anomaly space keeps the threshold local and
    # seasonal without fitting a separate percentile surface: the z-score
    # cutting off the requested percentile of a standard normal is the
    # equivalent threshold (1.2816 at the 90th).
    threshold = float(norm.ppf(percentile / 100.0))
    hot = (working["thetao_zanomaly"] >= threshold).fillna(False)

    cell = [working["latitude"], working["longitude"]]
    # Run length of consecutive hot days per cell: cumulative count of cool
    # days gives each hot run a distinct id, then a cumulative sum within
    # (cell, run) numbers the days inside it.
    run_id = (~hot).groupby(cell, observed=True, sort=False).cumsum()
    run_length = hot.groupby(cell + [run_id], observed=True, sort=False).cumsum()

    working["marine_heatwave"] = ((run_length >= min_duration_days) & hot).astype(int)
    working["hot_run_length"] = run_length.where(hot, 0).astype(int)
    return working


def feature_columns(frame: pd.DataFrame, horizons: tuple[int, ...]) -> list[str]:
    """Model input columns — everything except targets, label machinery and ids."""
    columns = []
    for name in frame.columns:
        if name in EXCLUDED or name.startswith(EXCLUDED_PREFIXES):
            continue
        series = frame[name]
        if pd.api.types.is_numeric_dtype(series) or isinstance(
            series.dtype, pd.CategoricalDtype
        ):
            columns.append(name)
    return columns


def drop_unusable_rows_all_horizons(
    frame: pd.DataFrame,
    columns: list[str],
    horizons: tuple[int, ...],
    min_coverage: float = 0.6,
) -> pd.DataFrame:
    """Rows usable for *every* horizon, filtered in one pass.

    One shared row set across horizons: it makes the horizons directly
    comparable, and it means the big table is copied once rather than once per
    horizon (see ``train.run``).
    """
    labelled = pd.Series(True, index=frame.index)
    for horizon in horizons:
        labelled &= frame[f"bloom_t{horizon}"].notna()

    coverage = frame[columns].notna().mean(axis=1)
    return frame[labelled & (coverage >= min_coverage)].reset_index(drop=True)


def drop_unusable_rows(
    frame: pd.DataFrame, columns: list[str], target: str, min_coverage: float = 0.6
) -> pd.DataFrame:
    """Drop rows with no label, or with mostly-missing features.

    The first ``max(lags)`` days of every cell's series have no lag features
    and the last ``horizon`` days have no label; both are removed here rather
    than being fed to the model as structured missingness.
    """
    working = frame[frame[target].notna()]
    coverage = working[columns].notna().mean(axis=1)
    return working[coverage >= min_coverage].reset_index(drop=True)
