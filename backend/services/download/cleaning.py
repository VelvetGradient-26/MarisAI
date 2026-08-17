"""Turns raw provider xarray Datasets into one tidy, analysis-ready pandas
DataFrame — the spec's "Data Cleaning" + "DataFrame Builder" stages combined,
since both operate on the same in-memory object with no intermediate format.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import xarray as xr

from services.download.catalog import ProviderSpec
from services.download.models import Resolution
from services.download.registry import VariableInfo

_RESAMPLE_RULE: dict[Resolution, str | None] = {
    Resolution.hourly: None,
    Resolution.daily: "D",
    Resolution.weekly: "W",
    Resolution.monthly: "MS",
}


def _choose_base(fetched: dict[str, tuple[ProviderSpec, xr.Dataset]]) -> str:
    """Pick the provider whose grid every other provider is resampled onto.

    The finest time-varying grid wins. Nearest-matching a coarse field onto a
    fine grid repeats values, which is lossless; doing it the other way
    discards cells outright. Bathymetry is excluded unless it is all there is,
    since it has no time axis to anchor the merge.
    """
    time_varying = {k: v for k, v in fetched.items() if v[0].time_varying}
    candidates = time_varying or fetched
    return min(candidates, key=lambda k: (candidates[k][0].grid_spacing_deg, k))


# Separator between a provider key and an upstream field name in the merged
# dataset. Two characters that no Copernicus/ERDDAP/Open-Meteo field uses, so
# `_qualify` is unambiguous and reversible.
_FIELD_SEP = "::"


def qualify(provider: str, field: str) -> str:
    """The merged dataset's name for `field` as served by `provider`.

    Provider datasets are namespaced before merging because an upstream name
    is only unique *within* a product, not across them. Copernicus reuses
    `thetao` for surface temperature in the physics product and for a
    depth-resolved profile in `..._thetao_depth`, and `so` likewise for
    salinity. Merging those raw raised
    `MergeError: conflicting values for variable 'thetao'` and took out every
    request pairing `water_temperature` with `sea_surface_temperature` (or
    `water_salinity` with `sea_surface_salinity`) — legal selections in both
    the downloader and the forecasting engine's covariates.

    Namespacing makes the collision structurally impossible rather than
    relying on no two providers ever choosing the same name. Do not "simplify"
    this back to a bare merge.
    """
    return f"{provider}{_FIELD_SEP}{field}"


def _merge_provider_datasets(resolved: dict[str, tuple[ProviderSpec, xr.Dataset]]) -> xr.Dataset:
    """Combine whichever providers were fetched onto one shared grid and time
    axis.

    The `join="inner"` on time means a request mixing providers of different
    cadence lands on their shared timestamps: waves are 3-hourly and
    biogeochemistry daily, so pairing either with an hourly physics variable
    yields 3-hourly or daily rows rather than hourly rows mostly full of gaps.

    **What the intersection must not be asked to do is aggregate.** Left to
    itself it keeps the coarse provider's timestamps and takes the fine
    provider's *instantaneous* value at each — an hourly wind field paired
    with a daily one becomes one 00:00 sample standing in for the day, not a
    24-hour mean, and Jensen's inequality guarantees the difference is biased
    rather than merely noisy on anything non-linear downstream. `build_dataframe`
    therefore aggregates each provider to the requested cadence *before* it
    gets here, so by the time the join runs the axes already agree and the
    intersection only drops genuinely uncovered periods.

    Data variables arrive qualified by provider (see `qualify`); coords are
    left alone, since those are what the merge aligns on.
    """
    assert resolved, "at least one provider dataset is required"

    base_key = _choose_base(resolved)
    base = resolved[base_key][1]
    others = [ds for key, (_, ds) in resolved.items() if key != base_key]
    if not others:
        return base

    if "latitude" in base.dims:
        # Bbox mode: each grid is a full lat/lon raster, but at differing
        # native resolutions (0.083deg through 0.25deg) — they won't share
        # exact grid points. Resample the others onto the base grid via
        # nearest-neighbor, consistent with Phase 1's "Interpolation: Nearest"
        # default, so every row has one shared lat/lon.
        aligned = [
            ds.reindex(latitude=base["latitude"], longitude=base["longitude"], method="nearest")
            for ds in others
        ]
    else:
        # Point mode: latitude/longitude are already scalar coords (each
        # provider's own nearest grid cell to the requested point, resolved
        # before this function is called) — providers' nearest cells can
        # differ slightly since their grids differ, so there's nothing to
        # align. Keep the base's resolved point as canonical, merge on time.
        aligned = [ds.drop_vars(["latitude", "longitude"], errors="ignore") for ds in others]

    # A time-invariant provider (bathymetry) has no time dim, so the inner
    # join has nothing to intersect for it — xarray broadcasts it across the
    # merged time axis, which is exactly the wanted "same depth at every
    # timestamp" behaviour.
    return xr.merge([base, *aligned], join="inner")


def _derive_speed(ds: xr.Dataset, u_field: str, v_field: str) -> xr.DataArray:
    return np.hypot(ds[u_field], ds[v_field])


def _derive_direction_from(ds: xr.Dataset, u_field: str, v_field: str) -> xr.DataArray:
    # Meteorological "from" convention (a north wind blows FROM the north) —
    # same formula as copernicus_wind.get_point, used for the live map.
    return (270 - np.degrees(np.arctan2(ds[v_field], ds[u_field]))) % 360


def _derive_direction_to(ds: xr.Dataset, u_field: str, v_field: str) -> xr.DataArray:
    """Oceanographic convention for currents: the direction the water flows TOWARD.

    **This used to return a mathematical angle, not a compass bearing**, and the
    two disagree everywhere except the 45-degree diagonal. `atan2(v, u)` measures
    counter-clockwise from *east*; a bearing measures clockwise from *north*, so
    the conversion is `90 - angle`, a reflection as well as a rotation. Without
    it, water flowing due east was reported as 0 degrees (north) and water
    flowing due north as 90 degrees (east) — plausible numbers, in range, wrong.

    Measured against the live map's own formula
    (`services/vector_source.py`, `services/drift.py`, both
    `(90 - degrees(atan2(v, u))) % 360`):

        flow      downloader (old)   live layer
        east            0                90
        north          90                 0
        west          180               270
        south         270               180
        north-east     45                45   <- the one that matched

    The sibling `_derive_direction_from` was never affected: `270 - angle` is
    `(90 - angle) + 180`, i.e. the correct bearing plus the half turn that makes
    it a "from", so wind agreed with the live field all along. That asymmetry is
    why this survived — the two derivations sit three lines apart and only one
    of them was wrong.
    """
    return (90 - np.degrees(np.arctan2(ds[v_field], ds[u_field]))) % 360


# Poole & Atkins' relation between Secchi disc depth and the diffuse
# attenuation coefficient. The constant is an empirical average — clarity
# reported this way is an estimate derived from Kd, not an independent
# measurement, which is why `diffuse_attenuation` stays available raw.
_SECCHI_COEFFICIENT = 1.7


def _derive_secchi_depth(ds: xr.Dataset, kd_field: str) -> xr.DataArray:
    kd = ds[kd_field]
    # Kd is strictly positive in the model output; guard anyway so a zero or
    # fill-value cell becomes NaN rather than an infinite clarity.
    return xr.where(kd > 0, _SECCHI_COEFFICIENT / kd, np.nan)


_DERIVATIONS = {
    "speed": _derive_speed,
    "direction_from": _derive_direction_from,
    "direction_to": _derive_direction_to,
    "secchi_depth": _derive_secchi_depth,
}


def _resolve_codes(
    fetched: dict[str, tuple[ProviderSpec, xr.Dataset]],
    variables: dict[str, VariableInfo],
) -> dict[str, tuple[ProviderSpec, xr.Dataset]]:
    """Turn each provider's raw fields into the registry codes it serves.

    Done per provider, before any merge or resample, for two reasons:

    * **A derivation is non-linear and must run at native cadence.**
      `current_speed` is `hypot(uo, vo)`; the mean of hourly speeds is not the
      speed of the mean hourly components, and only the first is what the
      variable means. Deriving after aggregation would quietly report a
      slack-water day as calmer than it was. Every derivation's inputs come
      from one provider, so there is nothing cross-provider to wait for.
    * A provider's raw field names are only unique within its own product, so
      resolving inside it removes the collision instead of managing it.

    Output variables are still `qualify`-namespaced, because the *codes* then
    travel through the same merge and a future registry could legitimately
    serve one code from two providers.
    """
    resolved: dict[str, tuple[ProviderSpec, xr.Dataset]] = {}
    for key, (spec, ds) in fetched.items():
        codes = xr.Dataset(coords=ds.coords)
        for code, info in variables.items():
            if info.provider != key:
                continue
            if info.source_field is not None:
                codes[qualify(key, code)] = ds[info.source_field]
            elif info.derived_from is not None and info.derivation is not None:
                codes[qualify(key, code)] = _DERIVATIONS[info.derivation](
                    ds, *info.derived_from
                )
        resolved[key] = (spec, codes)

    # A provider fetched but contributing no requested code would otherwise be
    # eligible to become the merge's base grid on the strength of its spacing
    # alone, and drag every other provider onto a grid nothing was asked for.
    contributing = {k: v for k, v in resolved.items() if v[1].data_vars}
    return contributing or resolved


def _aggregate_time(ds: xr.Dataset, rule: str | None) -> xr.Dataset:
    """Bin one provider onto the requested cadence, at its own native cadence.

    `mean` skips NaN, so a cell with partial coverage across the bin averages
    what it has and a cell with none stays NaN — the same contract the
    post-merge aggregation had. A provider already at or coarser than the rule
    is unchanged in value (each bin holds one sample), so this is safe to apply
    uniformly rather than only to the fine ones.
    """
    if rule is None or "time" not in ds.dims:
        return ds
    return ds.resample(time=rule).mean(keep_attrs=True)


def build_dataframe(
    *,
    fetched: dict[str, tuple[ProviderSpec, xr.Dataset]],
    variables: dict[str, VariableInfo],
    resolution: Resolution,
    start_date: date,
) -> pd.DataFrame:
    rule = _RESAMPLE_RULE[resolution]

    # Codes first, then cadence, then the merge. The order is the whole point:
    # aggregating before the join is what stops a fine provider being sampled
    # instantaneously by a coarse one's timestamps, and resolving codes before
    # aggregating is what keeps a non-linear derivation on native samples.
    resolved = {
        key: (spec, _aggregate_time(ds, rule))
        for key, (spec, ds) in _resolve_codes(fetched, variables).items()
    }
    merged = _merge_provider_datasets(resolved)

    output = xr.Dataset(coords=merged.coords)
    for code, info in variables.items():
        name = qualify(info.provider, code)
        if name in merged:
            output[code] = merged[name]

    # Bathymetry on its own has no time axis anywhere in the merge. Rather
    # than emit a frame whose shape differs from every other request's, give
    # it the requested start date: the value is time-invariant, so one
    # timestamp represents the whole range exactly.
    if "time" not in output.coords:
        output = output.expand_dims(time=[pd.Timestamp(start_date)])

    df = output.to_dataframe().reset_index()
    df = df.drop(columns=["depth"], errors="ignore")
    df = df.rename(columns={"time": "timestamp"})

    value_columns = [c for c in variables if c in df.columns]

    # A bbox naturally includes land / no-coverage cells — drop rows where
    # every requested variable is NaN there, but keep partial-NaN rows as-is
    # (fill values replaced with NaN is a cleaning requirement, not a mandate
    # to discard rows outright).
    df = df.dropna(how="all", subset=value_columns)
    df = df.drop_duplicates(subset=["timestamp", "latitude", "longitude"])
    # Upcast to float64 before rounding: rounding a float32 to 4 decimals
    # still leaves it stored in float32's binary representation, which prints
    # with ~10 digits of noise once serialized (e.g. 28.9955 -> 28.9955005646)
    # unless it's promoted to float64 first.
    df[value_columns] = df[value_columns].astype("float64").round(4)
    df["latitude"] = df["latitude"].astype("float64").round(6)
    df["longitude"] = df["longitude"].astype("float64").round(6)

    # No resample here: `_aggregate_time` already put every provider on `rule`
    # before the merge. Re-running it would be a no-op mean over single-row
    # groups, and having two places that could define the cadence is how the
    # pre-merge one silently stops mattering.
    df = df.sort_values(["timestamp", "latitude", "longitude"]).reset_index(drop=True)
    return df[["timestamp", "latitude", "longitude", *value_columns]]
