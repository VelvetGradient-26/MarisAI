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


def _merge_provider_datasets(fetched: dict[str, tuple[ProviderSpec, xr.Dataset]]) -> xr.Dataset:
    """Combine whichever providers were fetched onto one shared grid and time
    axis.

    The `join="inner"` on time means a request mixing providers of different
    cadence lands on their shared timestamps: waves are 3-hourly and
    biogeochemistry daily, so pairing either with an hourly physics variable
    yields 3-hourly or daily rows rather than hourly rows mostly full of gaps.

    Data variables come out qualified by provider (see `qualify`); coords are
    left alone, since those are what the merge aligns on.
    """
    assert fetched, "at least one provider dataset is required"

    namespaced = {
        key: ds.rename({name: qualify(key, str(name)) for name in ds.data_vars})
        for key, (_, ds) in fetched.items()
    }

    base_key = _choose_base(fetched)
    base = namespaced[base_key]
    others = [ds for key, ds in namespaced.items() if key != base_key]
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
    # Oceanographic convention for currents: direction the water flows TOWARD.
    return np.degrees(np.arctan2(ds[v_field], ds[u_field])) % 360


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


def build_dataframe(
    *,
    fetched: dict[str, tuple[ProviderSpec, xr.Dataset]],
    variables: dict[str, VariableInfo],
    resolution: Resolution,
    start_date: date,
) -> pd.DataFrame:
    merged = _merge_provider_datasets(fetched)

    output = xr.Dataset(coords=merged.coords)
    for code, info in variables.items():
        # Both a source field and a derivation's inputs are named in the
        # provider's own vocabulary, so both need qualifying by the provider
        # that served them.
        if info.source_field is not None:
            output[code] = merged[qualify(info.provider, info.source_field)]
        elif info.derived_from is not None and info.derivation is not None:
            fields = [qualify(info.provider, name) for name in info.derived_from]
            output[code] = _DERIVATIONS[info.derivation](merged, *fields)

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

    rule = _RESAMPLE_RULE[resolution]
    if rule is not None:
        df = (
            df.set_index("timestamp")
            .groupby(["latitude", "longitude", pd.Grouper(freq=rule)])[value_columns]
            .mean()
            .round(4)
            .reset_index()
        )

    df = df.sort_values(["timestamp", "latitude", "longitude"]).reset_index(drop=True)
    return df[["timestamp", "latitude", "longitude", *value_columns]]
