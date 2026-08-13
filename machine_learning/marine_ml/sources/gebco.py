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

import time
from pathlib import Path

import numpy as np
import requests
import xarray as xr

from marine_ml import config

_TIMEOUT_SECONDS = 300


class BathymetryError(RuntimeError):
    """Raised when bathymetry cannot be fetched or read."""


# etopo180 is served on a 1 arc-minute grid. Needed to turn a requested output
# resolution into a griddap stride, since griddap strides in grid cells rather
# than degrees.
_NATIVE_SPACING_DEG = 1.0 / 60.0


def _stride_for(resolution: float | None) -> int:
    """Griddap stride that lands the result near ``resolution`` degrees.

    ``None`` means stride 1 — full native resolution, the historic behaviour
    every regional call still gets.

    This exists because the request is *global* for the worldwide habitat
    build, and at stride 1 that is 21,600 x 10,800 = 233M cells (~930 MB in one
    HTTP response), which ERDDAP will refuse long before the network does. At
    0.25 degrees the same box is a ~1 MB response.
    """
    if resolution is None:
        return 1
    return max(1, int(round(resolution / _NATIVE_SPACING_DEG)))


# Transient ERDDAP conditions. 503 and 504 are the server saying "not now";
# 404 is included deliberately and is the non-obvious one — ERDDAP unloads a
# dataset while reloading it and answers 404 "Currently unknown datasetID"
# meanwhile, indistinguishably from a dataset that was really removed. The
# backend records the same behaviour on this host at length
# (`backend/forecasting/history.py::is_retryable`), and one 503 here was
# observed on 2026-08-10.
_RETRYABLE_STATUS = frozenset({404, 408, 425, 429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3


def _get_with_retry(url: str) -> bytes:
    """Fetch ``url``, retrying the conditions that can actually recover.

    Worth the code here specifically because the global request is the
    expensive one: a whole-planet grid lost to a single flap costs the caller
    the entire fetch, and this host flaps. A permanent failure still fails —
    it just costs two backoffs first.
    """
    delay = 2.0
    last: str = "no attempt made"
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last = f"request failed: {exc}"
        else:
            if response.ok:
                return response.content
            last = (
                f"returned HTTP {response.status_code}: {response.text[:200]}"
            )
            if response.status_code not in _RETRYABLE_STATUS:
                break
        if attempt < _MAX_ATTEMPTS:
            time.sleep(delay)
            delay *= 2

    raise BathymetryError(f"bathymetry request {last}")


def _cache_path(region: config.Region, stride: int = 1) -> Path:
    # The stride is part of the file's identity: a strided file and a native
    # one cover the same box and must not be served for one another.
    suffix = "" if stride == 1 else f"_s{stride}"
    return config.GEBCO_RAW_DIR / f"bathymetry_{region.name}{suffix}.nc"


def fetch_bathymetry(
    region: config.Region = config.DEFAULT_REGION,
    refresh: bool = False,
    resolution: float | None = None,
) -> xr.Dataset:
    """Download the relief grid for ``region``.

    Returns a dataset with ``depth`` (metres, positive down, NaN over land)
    and ``elevation`` (metres, positive up, as served).

    ``resolution`` (degrees) thins the request server-side; leave it None for
    native 1 arc-minute. Pass ``config.GRID_RESOLUTION`` for a region large
    enough that the native grid is not a sane HTTP response — see
    `_stride_for`. Regional callers should keep the default so their existing
    caches and model features are unchanged.
    """
    config.ensure_directories()
    stride = _stride_for(resolution)
    cached = _cache_path(region, stride)

    if not cached.exists() or refresh:
        url = (
            f"{config.BATHYMETRY_URL}?altitude"
            f"[({region.south}):{stride}:({region.north})]"
            f"[({region.west}):{stride}:({region.east})]"
        )
        cached.write_bytes(_get_with_retry(url))

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
        attrs={
            "marine_ml_source": "NOAA ERDDAP etopo180",
            "marine_ml_region": region.name,
            "marine_ml_stride": stride,
            "marine_ml_spacing_deg": f"{_NATIVE_SPACING_DEG * stride:g}",
        },
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
