"""The Marine Data Fusion Layer: regrid, QC, and serve one shared feature store.

Both problem statements read ocean state through this module, so they see an
identical view of it (approach doc sections 2.2 and 5). Raw products arrive on
different grids — physics at 1/12 degree, biogeochemistry at 1/4, bathymetry
at 15 arc-seconds — and are brought onto one common grid here, once, rather
than in each problem's notebook.

Two access shapes are supported, because the two problems genuinely need
different ones:

``build_gridded_frame``
    The full (latitude, longitude, date) cube as a tidy frame. What the HAB
    forecast trains on, and what produces a gridded risk raster.
``sample_at_points``
    Ocean state at scattered observation points. What the habitat SDM needs,
    since occurrence records are points, not a grid — materialising the whole
    cube to read 8,000 cells from it would be wasteful.

Both paths share the same regridding and QC code, so a feature means the same
thing whichever way it was obtained. That is the "train/serve parity" the doc
asks for, enforced by construction rather than by discipline.
"""

from __future__ import annotations


import numpy as np
import pandas as pd
import xarray as xr

from marine_ml import config
from marine_ml.features import geometry


class FusionError(RuntimeError):
    """Raised when inputs cannot be fused onto a common grid."""


# --------------------------------------------------------------------------
# Common grid
# --------------------------------------------------------------------------


def common_grid(
    region: config.Region = config.DEFAULT_REGION,
    resolution: float = config.GRID_RESOLUTION,
) -> tuple[np.ndarray, np.ndarray]:
    """Target latitude/longitude vectors for ``region`` at ``resolution``.

    Cell centres are snapped to multiples of the resolution so that two
    regions built at the same resolution share cell boundaries exactly — a
    prerequisite for the feature store being reusable across problems.
    """
    first_lat = np.ceil(region.south / resolution) * resolution
    first_lon = np.ceil(region.west / resolution) * resolution
    latitudes = np.arange(first_lat, region.north + resolution / 2, resolution)
    longitudes = np.arange(first_lon, region.east + resolution / 2, resolution)
    if latitudes.size == 0 or longitudes.size == 0:
        raise FusionError(f"{region.name} is smaller than one {resolution} degree cell")
    return latitudes, longitudes


def regrid(
    dataset: xr.Dataset,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    method: str = "linear",
) -> xr.Dataset:
    """Interpolate ``dataset`` onto the common grid.

    Linear interpolation is right for the *downsampling* direction this is
    normally used in (1/12 degree physics onto a 1/4 degree grid) and stays
    honest in the other: it will not invent structure finer than the source.
    Land stays NaN — no interpolation across a coastline.
    """
    lat_name = _dim_named(dataset, "lat")
    lon_name = _dim_named(dataset, "lon")
    return dataset.interp(
        {lat_name: latitudes, lon_name: longitudes},
        method=method,
        kwargs={"bounds_error": False},
    )


def _dim_named(dataset: xr.Dataset | xr.DataArray, prefix: str) -> str:
    match = next((d for d in dataset.dims if str(d).lower().startswith(prefix)), None)
    if match is None:
        raise FusionError(f"no {prefix}* dimension in {list(dataset.dims)}")
    return str(match)


# --------------------------------------------------------------------------
# Derived state (shared by both problems)
# --------------------------------------------------------------------------


def add_derived_fields(dataset: xr.Dataset) -> xr.Dataset:
    """Attach the shared physics-derived fields to a gridded dataset.

    Fronts, eddies and current speed are needed by both problem statements, so
    they are computed once here on the common grid rather than twice, slightly
    differently, in two pipelines.
    """
    result = dataset.copy()

    if "thetao" in result:
        result["sst_gradient"] = geometry.gradient_magnitude(result["thetao"])
    if "chl" in result:
        # log-space, because chlorophyll spans orders of magnitude and a
        # gradient in raw units just tracks the local mean.
        result["chl_gradient"] = geometry.gradient_magnitude(np.log1p(result["chl"]))
    if {"uo", "vo"} <= set(result.data_vars):
        result["current_speed"] = geometry.current_speed(result["uo"], result["vo"])
        result["okubo_weiss"] = geometry.okubo_weiss(result["uo"], result["vo"])
        result["relative_vorticity"] = geometry.relative_vorticity(result["uo"], result["vo"])
        if "time" in result.dims and result.sizes["time"] > 1:
            result["eddy_kinetic_energy"] = geometry.eddy_kinetic_energy(
                result["uo"], result["vo"]
            )

    # Wind-driven upwelling, when observed stress is available. Two physically
    # distinct mechanisms, both needed: coastal Ekman transport explains the
    # nearshore upwelling band, Ekman pumping from stress curl explains the
    # open-ocean upwelling the Findlater Jet drives well offshore of it.
    if {"eastward_stress", "northward_stress"} <= set(result.data_vars):
        result["wind_stress_magnitude"] = np.sqrt(
            result["eastward_stress"] ** 2 + result["northward_stress"] ** 2
        )
        result["upwelling_index"] = geometry.upwelling_index_from_stress(
            result["eastward_stress"], result["northward_stress"]
        )
    if "stress_curl" in result.data_vars:
        result["ekman_pumping"] = geometry.ekman_pumping(result["stress_curl"])
    if {"eastward_wind", "northward_wind"} <= set(result.data_vars):
        result["wind_speed"] = np.sqrt(
            result["eastward_wind"] ** 2 + result["northward_wind"] ** 2
        )

    return result


def add_static_fields(
    dataset: xr.Dataset,
    bathymetry: xr.Dataset,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
) -> xr.Dataset:
    """Attach depth, seafloor slope and distance-to-coast on the common grid."""
    result = dataset.copy()

    depth = regrid(bathymetry[["depth"]], latitudes, longitudes)["depth"]
    result["depth"] = depth
    result["seafloor_slope"] = geometry.gradient_magnitude(depth, per_metre=False)

    # Land is where the relief grid is at or above sea level. Derived from
    # elevation rather than from a NaN in the ocean fields, so a genuine data
    # gap over water is not mistaken for a coastline.
    elevation = regrid(bathymetry[["elevation"]], latitudes, longitudes)["elevation"]
    land_mask = elevation >= 0
    result["distance_to_coast"] = geometry.distance_to_coast(land_mask)

    return result


# --------------------------------------------------------------------------
# Gridded frame
# --------------------------------------------------------------------------


def build_gridded_frame(
    physics: xr.Dataset,
    bgc: xr.Dataset,
    bathymetry: xr.Dataset,
    region: config.Region = config.DEFAULT_REGION,
    resolution: float = config.GRID_RESOLUTION,
    drop_land: bool = True,
    wind: xr.Dataset | None = None,
) -> pd.DataFrame:
    """Fuse the sources into one tidy (latitude, longitude, date) frame.

    ``wind`` is optional — the habitat pipeline runs on monthly means and does
    not use it, and omitting it must not change the meaning of any other
    column. When present it contributes observed wind stress plus the two
    upwelling mechanisms derived from it.

    A ``data_quality`` column records the fraction of core ocean variables
    actually present at each row. The doc is explicit that this must be a
    *feature*, not something silently imputed away: a prediction standing on
    three gap-filled inputs should be able to say so, and the model can learn
    to condition its confidence on it.
    """
    latitudes, longitudes = common_grid(region, resolution)

    physics_grid = regrid(physics, latitudes, longitudes)
    bgc_grid = regrid(bgc, latitudes, longitudes)

    grids = [physics_grid, bgc_grid]
    if wind is not None:
        grids.append(regrid(wind, latitudes, longitudes))

    merged = xr.merge(grids, compat="override", join="inner")
    if "time" not in merged.dims:
        raise FusionError("expected a time dimension after merging physics and bgc")

    # An inner join silently truncates to the shortest input. A half-finished
    # wind fetch would therefore shrink the whole feature store to the wind
    # window and still look like a successful build — the model would train on
    # a fraction of the intended record with nothing to indicate it.
    #
    # The reference is physics-and-biogeochemistry overlap, which defines the
    # ocean-state record we intend to model; an optional covariate is not
    # allowed to shorten it.
    core_steps = len(
        np.intersect1d(physics_grid["time"].values, bgc_grid["time"].values)
    )
    if merged.sizes["time"] == 0:
        raise FusionError(
            "no overlapping timesteps between the input datasets — check that "
            "every source covers the requested window"
        )
    if merged.sizes["time"] < core_steps:
        raise FusionError(
            f"merging dropped {core_steps - merged.sizes['time']} of "
            f"{core_steps} timesteps. An optional covariate (wind?) covers a "
            "shorter period than physics/bgc — re-fetch it for the full "
            "window, or pass wind=None to build without it."
        )

    merged = add_derived_fields(merged)
    merged = add_static_fields(merged, bathymetry, latitudes, longitudes)

    lat_name = _dim_named(merged, "lat")
    lon_name = _dim_named(merged, "lon")

    frame = merged.to_dataframe().reset_index()
    frame = frame.rename(
        columns={lat_name: "latitude", lon_name: "longitude", "time": "date"}
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()

    core = [c for c in ("thetao", "so", "chl", "uo", "vo") if c in frame.columns]
    if core:
        frame["data_quality"] = frame[core].notna().mean(axis=1)

    if drop_land:
        # A row with no ocean variable at all is land or outside coverage;
        # keeping it would just be a hole in every downstream feature.
        ocean = frame[core].notna().any(axis=1) if core else pd.Series(True, index=frame.index)
        frame = frame[ocean]

    keep = [c for c in frame.columns if c not in ("depth_bnds", "depth")] + (
        ["depth"] if "depth" in frame.columns else []
    )
    return frame[keep].reset_index(drop=True)


# --------------------------------------------------------------------------
# Point sampling
# --------------------------------------------------------------------------


def sample_at_points(
    points: pd.DataFrame,
    physics: xr.Dataset,
    bgc: xr.Dataset,
    bathymetry: xr.Dataset,
    region: config.Region = config.DEFAULT_REGION,
    resolution: float = config.GRID_RESOLUTION,
    date_column: str = "observation_date",
) -> pd.DataFrame:
    """Ocean state at scattered (latitude, longitude, date) observations.

    Every point is snapped to the same common grid the gridded path uses, and
    derived fields are computed on that grid *before* sampling — not from the
    sampled values afterwards. That ordering matters: a spatial gradient or an
    Okubo-Weiss parameter is a property of the field's neighbourhood and
    simply cannot be recovered from an isolated point, so computing it after
    sampling would silently produce a different (wrong) feature than the
    gridded path produces under the same name.
    """
    if points.empty:
        raise FusionError("no points to sample")

    latitudes, longitudes = common_grid(region, resolution)
    physics_grid = regrid(physics, latitudes, longitudes)
    bgc_grid = regrid(bgc, latitudes, longitudes)

    merged = xr.merge([physics_grid, bgc_grid], compat="override", join="inner")
    merged = add_derived_fields(merged)
    merged = add_static_fields(merged, bathymetry, latitudes, longitudes)

    lat_name = _dim_named(merged, "lat")
    lon_name = _dim_named(merged, "lon")

    points = points.reset_index(drop=True)
    dates = pd.to_datetime(points[date_column]).dt.normalize()

    selector = {
        lat_name: xr.DataArray(points["latitude"].to_numpy(), dims="point"),
        lon_name: xr.DataArray(points["longitude"].to_numpy(), dims="point"),
    }
    static_only = {name for name in merged.data_vars if "time" not in merged[name].dims}

    time_varying = merged[[n for n in merged.data_vars if n not in static_only]]
    static = merged[list(static_only)]

    sampled_static = static.sel(**selector, method="nearest")
    sampled_time = time_varying.sel(
        **selector,
        time=xr.DataArray(dates.to_numpy().astype("datetime64[ns]"), dims="point"),
        method="nearest",
    )

    result = points.copy()
    for name in sampled_time.data_vars:
        # ravel, not squeeze: squeeze collapses a single-point request to a
        # 0-d array, which is not assignable as a column.
        result[str(name)] = np.ravel(np.asarray(sampled_time[name].values))
    for name in sampled_static.data_vars:
        result[str(name)] = np.ravel(np.asarray(sampled_static[name].values))

    # Snapped grid cell, so downstream grouping (climatology, spatial blocks)
    # keys on the cell rather than on the raw coordinate, which would make
    # every point its own group.
    result["grid_latitude"] = np.round(result["latitude"] / resolution) * resolution
    result["grid_longitude"] = np.round(result["longitude"] / resolution) * resolution

    core = [c for c in ("thetao", "so", "chl", "uo", "vo") if c in result.columns]
    if core:
        result["data_quality"] = result[core].notna().mean(axis=1)

    return result


# --------------------------------------------------------------------------
# Feature store persistence
# --------------------------------------------------------------------------


# Coordinate columns stay float64. Everything downstream groups on them —
# climatology, spatial blocks, per-cell lags — and float32 rounding could make
# two rows of the same grid cell compare unequal, silently splitting a cell
# into two groups. The measurement columns have no such role.
_KEEP_FLOAT64 = ("latitude", "longitude", "grid_latitude", "grid_longitude")


def compact_dtypes(frame: pd.DataFrame) -> pd.DataFrame:
    """Shrink numeric columns to the smallest dtype that still fits.

    Two separate problems, both found by measurement rather than inspection:

    **Memory.** A 6-year daily feature table is ~3.9M rows x ~150 columns,
    which is ~4.7 GB at float64 for one copy — and scikit-learn's
    ColumnTransformer plus LightGBM each make more. On a 9 GB machine that is
    an OOM kill with no traceback. float32 carries ~7 significant digits;
    these are geophysical measurements good to 3-4 digits at best, so the
    precision lost is far below the measurement error already present.

    **Extension dtypes.** A single pandas nullable column (``Int8``) makes
    ColumnTransformer fall back to ``object`` for the *entire* concatenated
    matrix, which is both far larger and far slower than the float32 it
    should be. Nullable integers therefore become float32, where the missing
    values land as NaN — which LightGBM handles natively anyway.
    """
    for column in frame.columns:
        if column in _KEEP_FLOAT64:
            continue
        dtype = frame[column].dtype
        if dtype == "float64":
            frame[column] = frame[column].astype("float32")
        elif dtype == "int64":
            frame[column] = frame[column].astype("int32")
        elif (
            isinstance(dtype, pd.api.extensions.ExtensionDtype)
            and not isinstance(dtype, pd.CategoricalDtype)
            and (
                pd.api.types.is_integer_dtype(dtype)
                or pd.api.types.is_bool_dtype(dtype)
            )
        ):
            # Nullable Int8/Int64/boolean -> float32, preserving NA as NaN.
            # The dtype test must be *numeric*, not merely "is an extension
            # dtype": pandas 3 backs plain strings with Arrow, so a blanket
            # extension check also catches every text column and tries to
            # parse it as a number.
            frame[column] = frame[column].astype("float32")
    return frame


def write_feature_store(frame: pd.DataFrame, name: str) -> None:
    """Persist a built feature table under ``name`` in the shared store."""
    config.ensure_directories()
    path = config.FEATURE_STORE_DIR / f"{name}.parquet"
    compact_dtypes(frame).to_parquet(path, index=False)


def read_feature_store(name: str) -> pd.DataFrame:
    path = config.FEATURE_STORE_DIR / f"{name}.parquet"
    if not path.exists():
        raise FusionError(
            f"feature store {name!r} has not been built yet (expected {path}). "
            "Run the matching build_features step first."
        )
    # Downcast on read too, so stores written before this existed do not
    # reintroduce the memory blowup.
    return compact_dtypes(pd.read_parquet(path))


def feature_store_exists(name: str) -> bool:
    return (config.FEATURE_STORE_DIR / f"{name}.parquet").exists()
