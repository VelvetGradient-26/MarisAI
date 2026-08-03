"""Turns raw provider xarray Datasets into one tidy, analysis-ready pandas
DataFrame — the spec's "Data Cleaning" + "DataFrame Builder" stages combined,
since both operate on the same in-memory object with no intermediate format.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from services.download.models import Resolution
from services.download.registry import VariableInfo

_RESAMPLE_RULE: dict[Resolution, str | None] = {
    Resolution.hourly: None,
    Resolution.daily: "D",
    Resolution.weekly: "W",
    Resolution.monthly: "MS",
}


def _merge_provider_datasets(
    physics_ds: xr.Dataset | None,
    wind_ds: xr.Dataset | None,
    waves_ds: xr.Dataset | None = None,
) -> xr.Dataset:
    """Combine whichever providers were fetched onto one shared grid and time
    axis, with the first present one (physics, when requested) canonical.

    The `join="inner"` on time means a request mixing providers of different
    cadence lands on their shared timestamps: waves are 3-hourly, so pairing
    a wave variable with an hourly physics one yields 3-hourly rows rather
    than hourly rows two-thirds full of gaps. That is the existing
    physics/wind behaviour, now with a third provider under it.
    """
    present = [ds for ds in (physics_ds, wind_ds, waves_ds) if ds is not None]
    assert present, "at least one provider dataset is required"

    base, *others = present
    if not others:
        return base

    if "latitude" in base.dims:
        # Bbox mode: each grid is a full lat/lon raster, but at differing
        # native resolutions (physics and waves 0.083deg, wind 0.125deg) —
        # they won't share exact grid points. Resample the others onto the
        # base grid via nearest-neighbor, consistent with Phase 1's
        # "Interpolation: Nearest" default, so every row has one shared
        # lat/lon.
        aligned = [
            ds.reindex(
                latitude=base["latitude"], longitude=base["longitude"], method="nearest"
            )
            for ds in others
        ]
    else:
        # Point mode: latitude/longitude are already scalar coords (each
        # provider's own nearest grid cell to the requested point, resolved
        # before this function is called) — providers' nearest cells can
        # differ slightly since their grids differ, so there's nothing to
        # align. Keep the base's resolved point as canonical, merge on time.
        aligned = [ds.drop_vars(["latitude", "longitude"], errors="ignore") for ds in others]

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


_DERIVATIONS = {
    "speed": _derive_speed,
    "direction_from": _derive_direction_from,
    "direction_to": _derive_direction_to,
}


def build_dataframe(
    *,
    physics_ds: xr.Dataset | None,
    wind_ds: xr.Dataset | None,
    waves_ds: xr.Dataset | None = None,
    variables: dict[str, VariableInfo],
    resolution: Resolution,
) -> pd.DataFrame:
    merged = _merge_provider_datasets(physics_ds, wind_ds, waves_ds)

    output = xr.Dataset(coords=merged.coords)
    for code, info in variables.items():
        if info.source_field is not None:
            output[code] = merged[info.source_field]
        elif info.derived_from is not None and info.derivation is not None:
            u_field, v_field = info.derived_from
            output[code] = _DERIVATIONS[info.derivation](merged, u_field, v_field)

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
