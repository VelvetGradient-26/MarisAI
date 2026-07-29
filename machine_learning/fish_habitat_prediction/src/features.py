"""Habitat feature engineering (approach doc 4.4).

Takes the labelled presence/background table, samples shared ocean state at
each point through the fusion layer, and derives the habitat-specific
features on top.

The ones that carry real ecological content, and why:

* **Frontal strength** — the learned version of INCOIS's operational PFZ
  heuristic, which is essentially a hand-tuned SST-front detector. Fronts
  concentrate prey, so fish concentrate at them.
* **Prey-availability lag** — chlorophyll one to two months earlier, not
  concurrent. A phytoplankton bloom takes weeks to propagate up the food
  chain to anything a fishing vessel would target; the concurrent value is
  the wrong question.
* **Thermal-niche membership** — where the local temperature sits within the
  species' own observed thermal range, fitted on training presences only.
* **Bathymetric context** — depth, seafloor slope and distance to coast:
  shelf breaks and slopes are persistent aggregation features.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from marine_ml import config, fusion
from marine_ml.features import temporal

# Ocean state sampled from the fusion layer and used directly as features.
BASE_FEATURES = [
    "thetao", "so", "uo", "vo", "zos", "mlotst",
    "chl", "no3", "po4", "si", "o2", "nppv",
    "sst_gradient", "chl_gradient", "current_speed",
    "okubo_weiss", "relative_vorticity", "eddy_kinetic_energy",
    "depth", "seafloor_slope", "distance_to_coast",
]

# Columns that must never reach the model: identifiers, raw coordinates and
# the label itself. Latitude/longitude are excluded deliberately — with
# spatially clustered presences a tree model will happily memorise "presence
# lives at 12.3N, 74.8E" and score beautifully under random CV while learning
# no ecology at all. Spatial structure enters through environment and
# bathymetry, not through raw position.
EXCLUDED = {
    "presence", "latitude", "longitude", "observation_date", "date",
    "scientific_name", "species", "event_date", "basis_of_record",
    "dataset_id", "institution_code", "individual_count",
    "grid_latitude", "grid_longitude", "region",
}

# Species-dependent features. These are added by `apply_thermal_niche` *after*
# the base feature table is built, so `feature_columns` cannot discover them by
# inspecting the frame — it would be called before they exist and silently
# return a column list without them.
#
# That is not hypothetical: it is exactly the bug that made every species
# produce an identical suitability surface, because with `species_key` also
# excluded the model had no species-dependent input at all and was really one
# pooled model wearing five labels. Naming them explicitly is what stops the
# ordering of two function calls from silently changing what the model sees.
#
# `species_key` itself is a legitimate categorical feature, not an identifier
# to strip: one model with species as an input is the tabular analogue of the
# approach doc's "shared encoder with species-specific output heads", letting
# species with few records borrow strength from the shared environmental
# response instead of training five separate small models.
THERMAL_FEATURES = ("thermal_position", "thermal_distance", "in_thermal_range")
SPECIES_FEATURE = "species_key"


class FeatureError(RuntimeError):
    """Raised when features cannot be built."""


def build_features(
    table: pd.DataFrame,
    physics: xr.Dataset,
    bgc: xr.Dataset,
    bathymetry: xr.Dataset,
    region: config.Region = config.DEFAULT_REGION,
    resolution: float = config.GRID_RESOLUTION,
) -> pd.DataFrame:
    """Sample ocean state at each labelled point and derive habitat features."""
    sampled = fusion.sample_at_points(
        table, physics, bgc, bathymetry, region=region, resolution=resolution
    )
    sampled["date"] = pd.to_datetime(sampled["observation_date"]).dt.normalize()

    sampled = _add_prey_lag(sampled, physics, bgc, bathymetry, region, resolution)
    sampled = _add_bathymetric_context(sampled)

    cyclical = temporal.cyclical_time_features(sampled["date"])
    sampled = pd.concat(
        [sampled.reset_index(drop=True), cyclical.reset_index(drop=True)], axis=1
    )
    sampled["monsoon_phase"] = temporal.monsoon_phase(sampled["date"])
    # Categorical so the preprocessor one-hots it rather than treating the
    # species name as an unusable string column.
    if SPECIES_FEATURE in sampled.columns:
        sampled[SPECIES_FEATURE] = sampled[SPECIES_FEATURE].astype("category")

    return sampled


def _add_prey_lag(
    frame: pd.DataFrame,
    physics: xr.Dataset,
    bgc: xr.Dataset,
    bathymetry: xr.Dataset,
    region: config.Region,
    resolution: float,
    lag_days: tuple[int, ...] = (30, 60),
) -> pd.DataFrame:
    """Chlorophyll and SST at earlier dates — the trophic-transfer delay.

    Implemented by re-sampling the same fields at a shifted date rather than
    by shifting rows, because these are scattered points with irregular dates:
    there is no per-cell time series to shift along.
    """
    result = frame.copy()
    for lag in lag_days:
        shifted = frame[["latitude", "longitude"]].copy()
        shifted["observation_date"] = pd.to_datetime(frame["date"]) - pd.Timedelta(days=lag)

        sampled = fusion.sample_at_points(
            shifted, physics, bgc, bathymetry, region=region, resolution=resolution
        )
        for column in ("chl", "thetao", "nppv"):
            if column in sampled.columns:
                result[f"{column}_lag{lag}"] = sampled[column].to_numpy()

    if "chl" in result.columns and "chl_lag30" in result.columns:
        # Whether the prey base was building or collapsing, not just its level.
        result["chl_trend_30d"] = result["chl"] - result["chl_lag30"]
    return result


def _add_bathymetric_context(frame: pd.DataFrame) -> pd.DataFrame:
    """Shelf/slope/oceanic depth bucket and log-depth.

    Depth spans four orders of magnitude and its ecological effect is
    strongly non-linear near the shelf break (~200 m), so the log transform
    and an explicit bucket both help — a linear baseline cannot discover that
    break on its own.
    """
    result = frame.copy()
    if "depth" not in result.columns:
        return result

    depth = result["depth"]
    result["log_depth"] = np.log1p(depth.clip(lower=0))
    result["depth_bucket"] = pd.cut(
        depth,
        bins=[-np.inf, 50, 200, 1000, 3000, np.inf],
        labels=["nearshore", "shelf", "slope", "deep", "abyssal"],
    ).astype("category")
    return result


def fit_thermal_niche(
    frame: pd.DataFrame,
    temperature_column: str = "thetao",
    lower_quantile: float = 0.05,
    upper_quantile: float = 0.95,
) -> pd.DataFrame:
    """Per-species thermal tolerance window, from **training presences only**.

    Returns one row per species with the quantile bounds. Fitting this on the
    full dataset would leak held-out conditions into a training feature, so
    the fit and the application are separate calls.
    """
    presences = frame[frame["presence"] == 1]
    if presences.empty:
        raise FeatureError("no presences available to fit a thermal niche")

    niche = (
        presences.groupby("species_key", observed=True)[temperature_column]
        .agg(
            thermal_low=lambda s: s.quantile(lower_quantile),
            thermal_high=lambda s: s.quantile(upper_quantile),
            thermal_optimum="median",
        )
        .reset_index()
    )
    return niche


def apply_thermal_niche(
    frame: pd.DataFrame,
    niche: pd.DataFrame,
    temperature_column: str = "thetao",
) -> pd.DataFrame:
    """Attach thermal-niche membership features from a fitted niche table.

    ``thermal_position`` places the local temperature on a 0-1 scale across
    the species' range (values outside 0-1 mean outside its observed range),
    and ``thermal_distance`` is the absolute departure from its optimum.
    """
    merged = frame.merge(niche, on="species_key", how="left")

    span = (merged["thermal_high"] - merged["thermal_low"]).replace(0, np.nan)
    merged["thermal_position"] = (merged[temperature_column] - merged["thermal_low"]) / span
    merged["thermal_distance"] = (merged[temperature_column] - merged["thermal_optimum"]).abs()
    merged["in_thermal_range"] = (
        (merged[temperature_column] >= merged["thermal_low"])
        & (merged[temperature_column] <= merged["thermal_high"])
    ).astype(int)

    return merged.drop(columns=["thermal_low", "thermal_high", "thermal_optimum"])


def feature_columns(frame: pd.DataFrame) -> list[str]:
    """Model input columns: everything numeric or categorical except the
    excluded identifiers and the label.

    The species-dependent columns are appended by name whether or not they are
    present on ``frame`` yet, because this is routinely called *before*
    ``apply_thermal_niche`` has added them. Discovering columns purely by
    inspection made the returned list depend on call order, and silently
    produced a model with no species input at all.
    """
    columns = []
    for name in frame.columns:
        if name in EXCLUDED or name in THERMAL_FEATURES:
            continue
        series = frame[name]
        if pd.api.types.is_numeric_dtype(series) or isinstance(
            series.dtype, pd.CategoricalDtype
        ):
            columns.append(name)

    if SPECIES_FEATURE in frame.columns and SPECIES_FEATURE not in columns:
        columns.append(SPECIES_FEATURE)
    columns.extend(THERMAL_FEATURES)
    return columns


def drop_unusable_rows(
    frame: pd.DataFrame, columns: list[str], min_coverage: float = 0.5
) -> pd.DataFrame:
    """Drop rows whose features are mostly missing.

    A point on land, or outside the environmental coverage, produces a row of
    NaNs. LightGBM would happily train on it by routing every missing value
    down one branch — so these are removed explicitly rather than left for the
    model to absorb.

    Scores coverage over the columns that exist *now*: this is called before
    the per-fold thermal-niche features are attached, and those are derived
    from `thetao`, which is already counted.
    """
    present = [c for c in columns if c in frame.columns]
    coverage = frame[present].notna().mean(axis=1)
    return frame[coverage >= min_coverage].reset_index(drop=True)
