"""Static bathymetry / seafloor slope — a spatial covariate for both problems.

Served from NOAA ERDDAP's ``etopo180`` griddap endpoint: the same global
relief grid GEBCO publishes, reachable over plain HTTP with the bounding box
in the URL and no account required, which makes it the practical access path
for a one-off static layer.

ERDDAP returns *altitude* (positive up, so the ocean is negative). Everything
downstream wants depth as a positive number of metres, so the conversion
happens here, once, rather than in each consumer.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import requests
import xarray as xr

from marine_ml import config

_TIMEOUT_SECONDS = 300


class BathymetryError(RuntimeError):
    """Raised when bathymetry cannot be fetched or read."""


def _cache_path(region: config.Region) -> Path:
    return config.GEBCO_RAW_DIR / f"bathymetry_{region.name}.nc"


def fetch_bathymetry(
    region: config.Region = config.DEFAULT_REGION,
    refresh: bool = False,
) -> xr.Dataset:
    """Download the relief grid for ``region``.

    Returns a dataset with ``depth`` (metres, positive down, NaN over land)
    and ``elevation`` (metres, positive up, as served).
    """
    config.ensure_directories()
    cached = _cache_path(region)

    if not cached.exists() or refresh:
        url = (
            f"{config.BATHYMETRY_URL}?altitude"
            f"[({region.south}):1:({region.north})]"
            f"[({region.west}):1:({region.east})]"
        )
        try:
            response = requests.get(url, timeout=_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise BathymetryError(f"bathymetry request failed: {exc}") from exc
        if not response.ok:
            raise BathymetryError(
                f"bathymetry request returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
        cached.write_bytes(response.content)

    try:
        ds = xr.open_dataset(cached)
    except Exception as exc:
        # A truncated/HTML error body cached as .nc would fail here; make the
        # fix obvious rather than surfacing a raw netCDF parse error.
        raise BathymetryError(
            f"could not read cached bathymetry at {cached} ({exc}). "
            "Delete the file or pass refresh=True to re-download."
        ) from exc

    elevation = ds["altitude"]
    depth = xr.where(elevation < 0, -elevation, np.nan)
    depth.attrs.update(units="m", long_name="ocean depth (positive down)")

    return xr.Dataset(
        {"depth": depth, "elevation": elevation},
        attrs={"marine_ml_source": "NOAA ERDDAP etopo180", "marine_ml_region": region.name},
    )


def seafloor_slope(depth: xr.DataArray) -> xr.DataArray:
    """Seafloor slope magnitude, in metres of depth change per grid cell.

    Computed from the depth field with a centred difference. Used as a
    habitat covariate (shelf breaks and steep slopes concentrate fish) and,
    in the HAB pipeline, as part of the coastal/nearshore characterisation.
    """
    lat_dim, lon_dim = _spatial_dims(depth)
    d_lat = depth.differentiate(lat_dim)
    d_lon = depth.differentiate(lon_dim)
    slope = np.sqrt(d_lat**2 + d_lon**2)
    slope.attrs.update(units="m/degree", long_name="seafloor slope magnitude")
    return slope


def _spatial_dims(array: xr.DataArray) -> tuple[str, str]:
    lat = next((d for d in array.dims if str(d).lower().startswith("lat")), None)
    lon = next((d for d in array.dims if str(d).lower().startswith("lon")), None)
    if lat is None or lon is None:
        raise BathymetryError(f"expected latitude/longitude dims, got {array.dims}")
    return str(lat), str(lon)
