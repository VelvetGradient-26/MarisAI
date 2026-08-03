"""GEBCO bathymetry provider for the Universal Ocean Data Downloader.

`services/bathymetry.py` already reads GEBCO, but only ever one point at a
time (a WMS `GetFeatureInfo` call per pixel) — that is right for the map's
depth-at-cursor readout and useless for filling a bbox. This module goes at
the same grid through ERDDAP's `griddap` instead, which subsets server-side
and returns the whole rectangle in one response.

Bathymetry is the only *time-invariant* variable in the downloader. It is
fetched as a plain `(latitude, longitude)` Dataset with no time dim at all;
`cleaning.py` broadcasts it across whatever time axis the other providers
bring, and supplies one when it is the only thing requested.
"""

from __future__ import annotations

import io
import math
from datetime import date
from typing import Any

import httpx
import numpy as np
import pandas as pd
import xarray as xr

ERDDAP_URL = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/GEBCO_2020.csv"

# GEBCO's native grid is 15 arc-seconds.
NATIVE_SPACING_DEG = 1.0 / 240.0

# Points to aim for after striding. GEBCO at native resolution is far finer
# than any ocean product here — a 4x4 degree box is ~920,000 native cells
# (~36MB of CSV) to carry a field that gets nearest-matched onto a 0.083 or
# 0.25 degree grid anyway. Striding down to ~40,000 keeps the response about
# 1.5MB and ~1.5s while staying finer than every grid it merges with.
_TARGET_POINTS = 40_000

# What limits.py sizes a bathymetry request on. Not the native spacing: the
# stride below adapts, and this is the resolution a large request lands at.
GRID_SPACING_DEG = 0.05

_TIMEOUT = httpx.Timeout(120.0)


class GebcoDownloadError(RuntimeError):
    """GEBCO/ERDDAP request failed — surfaced as a clean provider error."""


def choose_stride(west: float, south: float, east: float, north: float) -> int:
    """Pick a griddap stride keeping the response near `_TARGET_POINTS`.

    Small areas (including the widened window behind a point request) come
    back at full native resolution; only large boxes get thinned.
    """
    lat_cells = max(1.0, (north - south) / NATIVE_SPACING_DEG)
    lon_cells = max(1.0, (east - west) / NATIVE_SPACING_DEG)
    stride = math.ceil(math.sqrt(lat_cells * lon_cells / _TARGET_POINTS))
    return max(1, stride)


def _parse_csv(text: str) -> xr.Dataset:
    # griddap CSV is a header row, then a *units* row, then the data.
    frame = pd.read_csv(io.StringIO(text), skiprows=[1])
    missing = {"latitude", "longitude", "elevation"} - set(frame.columns)
    if missing:
        raise GebcoDownloadError(f"GEBCO response is missing column(s): {', '.join(sorted(missing))}")

    frame = frame.dropna(subset=["latitude", "longitude"])
    if frame.empty:
        raise GebcoDownloadError("GEBCO returned no cells for the requested area")

    # GEBCO is a continuous terrain model: positive elevation is land. Depth
    # is only defined below sea level, so land becomes NaN rather than a
    # negative depth — the same distinction services/bathymetry.py draws with
    # its `depth_m` / `is_land` pair.
    elevation = frame["elevation"].astype("float64")
    frame["ocean_depth"] = np.where(elevation < 0, -elevation, np.nan)

    grid = (
        frame.drop_duplicates(subset=["latitude", "longitude"])
        .set_index(["latitude", "longitude"])["ocean_depth"]
        .to_xarray()
    )
    return grid.to_dataset(name="ocean_depth")


async def fetch(
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    **_ignored: Any,
) -> xr.Dataset:
    """Fetch ocean depth over a bbox as a time-invariant gridded Dataset.

    Accepts and ignores the date/field arguments every provider is called
    with — depth does not vary over the request's date range, and `ocean_depth`
    is the only field this provider serves.
    """
    stride = choose_stride(west, south, east, north)
    query = (
        f"elevation[({south}):{stride}:({north})][({west}):{stride}:({east})]"
    )

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await client.get(f"{ERDDAP_URL}?{query}")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # ERDDAP puts its real complaint in the body, not the status line.
            raise GebcoDownloadError(
                f"GEBCO returned status {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise GebcoDownloadError(f"GEBCO request failed: {exc}") from exc

    return _parse_csv(response.text)
