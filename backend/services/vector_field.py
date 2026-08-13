"""Encoding a gridded U/V field as one RGBA texture for the GPU particle layer.

The particle engine in `frontend/src/features/map/vectorField/` advects points
client-side, so it needs the *whole* field as a single texture rather than as
tiles: there is no z/x/y here and no render-on-demand path. Wind has done this
since the layer was built; currents and the forecast vector grids do it too, and
this module is what they share so the encoding contract exists in one place.

**The contract this module owns.** `shaders.ts`'s `fieldUV()` turns a particle's
lon/lat into a texture coordinate, and it can only be right if it agrees with
the encoder about three things:

* **R = u, G = v, A = coverage**, each channel normalised over the field's own
  min/max, which travel beside the texture in the layer's meta. B is unused.
* **Row 0 is north.** The array's row 0 is the *southernmost* latitude, so the
  image is flipped vertically before encoding.
* **The texture's geographic edges are the field's outer cell edges** — first
  centre minus half a cell, last centre plus half a cell — and they are
  reported in the meta rather than assumed.

That third point is the one that bites. The wind shader originally hardcoded
`u = (lon+180)/360, v = (90-lat)/180`, which is exactly right for the wind
product and wrong for everything else: Copernicus's global physics grid (the
currents source) runs **latitude -80 to 90**, not -90 to 90. Hardcoding the
global frame would have stretched every particle's sampling latitude by 5.6%
and advected the whole ocean with the wrong water — silently, since the field
still covers the screen and still animates. Bounds are data, so they are
carried as data.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy.interpolate import RegularGridInterpolator


@dataclass(frozen=True)
class FieldTexture:
    """An encoded field, plus everything the shader needs to sample it."""

    png: bytes
    u_min: float
    u_max: float
    v_min: float
    v_max: float
    # Outer cell edges, degrees. Named for compass direction rather than
    # min/max because the shader consumes them as a frame, not as a range.
    lon_west: float
    lon_east: float
    lat_south: float
    lat_north: float

    def bounds(self) -> dict[str, float]:
        return {
            "lon_west": self.lon_west,
            "lon_east": self.lon_east,
            "lat_south": self.lat_south,
            "lat_north": self.lat_north,
        }


def build_interpolator(
    lat: np.ndarray, lon: np.ndarray, grid: np.ndarray
) -> RegularGridInterpolator:
    """Bilinear point sampling with the longitude seam closed at the high end.

    The grid's own longitude axis covers `[lon[0], lon[0]+360)`, so a query
    right at the seam needs one wrap column appended. Queries *below* `lon[0]`
    (which exist whenever the axis does not start exactly at -180) are folded
    in by `wrap_longitude` at the call site rather than by a second wrap column
    — the same split `copernicus_wind` has always used.
    """
    lon_wrapped = np.append(lon, lon[0] + 360.0)
    grid_wrapped = np.concatenate([grid, grid[:, :1]], axis=1)
    return RegularGridInterpolator(
        (lat, lon_wrapped), grid_wrapped, method="linear", bounds_error=False, fill_value=np.nan
    )


def wrap_longitude(longitude: float, lon_min: float) -> float:
    return lon_min + (longitude - lon_min) % 360.0


def block_mean(values: np.ndarray, factor: int) -> np.ndarray:
    """Block-average by `factor`, cropping any trailing partial block.

    Cropping rather than requiring divisibility, because real grids are not
    tidy: the wind product is 1440x2880 and divides evenly, but Copernicus's
    physics grid is **2041** latitudes — an odd number, which made the previous
    reshape-based downsample raise on any even factor. The crop is at most
    `factor-1` cells off one edge, and `axis_after_block_mean` reports the
    axis that survives, so the texture's declared bounds stay exact instead of
    silently describing rows that were dropped.
    """
    if factor <= 1:
        return values
    rows = (values.shape[0] // factor) * factor
    cols = (values.shape[1] // factor) * factor
    cropped = values[:rows, :cols]
    reshaped = cropped.reshape(rows // factor, factor, cols // factor, factor)
    with np.errstate(invalid="ignore"):
        # nanmean, so a block straddling a coastline keeps the water in it
        # rather than being erased by the land cell beside it.
        return np.nanmean(reshaped, axis=(1, 3))


def axis_after_block_mean(axis: np.ndarray, factor: int) -> np.ndarray:
    """The coordinate axis `block_mean` leaves behind: block centres."""
    if factor <= 1:
        return axis
    count = (axis.size // factor) * factor
    return axis[:count].reshape(count // factor, factor).mean(axis=1)


def _edges(axis: np.ndarray) -> tuple[float, float]:
    """Outer cell edges of a regular ascending axis of cell centres."""
    if axis.size < 2:
        return float(axis[0]), float(axis[0])
    spacing = float(axis[1] - axis[0])
    return float(axis[0]) - spacing / 2.0, float(axis[-1]) + spacing / 2.0


def encode(
    u: np.ndarray,
    v: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    *,
    downsample: int = 1,
) -> FieldTexture:
    """One U/V field as an RGBA PNG plus its sampling frame.

    `downsample` exists because the particle system samples with GPU bilinear
    filtering regardless, so native resolution buys nothing visually and costs
    the client a much larger download on every layer activation.
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)

    # Normalise orientation before anything else, so `_edges` and the flip
    # below can both assume an ascending axis. Copernicus ascends; a product
    # that descends would otherwise encode upside down and read as a field
    # advecting the ocean the wrong way, which is not obviously wrong on sight.
    if lat.size > 1 and lat[0] > lat[-1]:
        lat, u, v = lat[::-1], u[::-1, :], v[::-1, :]

    u_small = block_mean(u, downsample)
    v_small = block_mean(v, downsample)
    lat_small = axis_after_block_mean(lat, downsample)
    lon_small = axis_after_block_mean(lon, downsample)

    valid = np.isfinite(u_small) & np.isfinite(v_small)
    if not valid.any():
        raise ValueError("vector field has no valid cells")

    u_min, u_max = float(np.nanmin(u_small)), float(np.nanmax(u_small))
    v_min, v_max = float(np.nanmin(v_small)), float(np.nanmax(v_small))

    def normalize(values: np.ndarray, low: float, high: float) -> np.ndarray:
        span = high - low if high > low else 1.0
        return np.clip((values - low) / span, 0.0, 1.0)

    red = np.nan_to_num(normalize(u_small, u_min, u_max), nan=0.0) * 255
    green = np.nan_to_num(normalize(v_small, v_min, v_max), nan=0.0) * 255
    blue = np.zeros_like(red)
    alpha = np.where(valid, 255, 0)

    rgba = np.dstack([red, green, blue, alpha]).astype(np.uint8)
    buffer = io.BytesIO()
    # flipud: array row 0 is the southernmost latitude; texture row 0 is
    # conventionally the top, so this is what makes north "up" in the texture
    # and lets the shader's v run straight down from lat_north.
    Image.fromarray(np.flipud(rgba), mode="RGBA").save(buffer, format="PNG")

    lon_west, lon_east = _edges(lon_small)
    lat_south, lat_north = _edges(lat_small)

    return FieldTexture(
        png=buffer.getvalue(),
        u_min=u_min,
        u_max=u_max,
        v_min=v_min,
        v_max=v_max,
        lon_west=lon_west,
        lon_east=lon_east,
        lat_south=lat_south,
        lat_north=lat_north,
    )
