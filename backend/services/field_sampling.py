"""Resampling a holed geographic grid onto tile pixels, without eating the coast.

Extracted from `forecast_tiles` so `predictions.py` can use the same thing
rather than a second copy: both render raster tiles from a NetCDF grid that is
NaN over land, and both had the same defect. Nothing here knows what it is
painting — it takes a `DataArray` on `latitude`/`longitude` and returns values
on a pixel grid.

Two hazards live here, and each one is silent in a different way.

**A hole poisons a bilinear read.** Any pixel whose four surrounding cells
include one land cell comes back NaN, so the painted ocean erodes by up to a
full cell and its edge is forced onto the grid's own axis-aligned steps. On the
1-degree forecast grid that was ~110 km of staircase and **3,609 of
chlorophyll's 42,499 ocean cells (8.5%) erased** — the coastal band those layers
are most about. So coverage is carried as its own 0/1 field: `values` is
nearest-filled across the gaps to keep coastal cells finite, `coverage` is
interpolated the same way and thresholded at 0.5. The edge then lands halfway
between the last ocean cell centre and the first land cell centre — the correct
nearest-cell footprint — along the bilinear 0.5 contour, which cuts diagonally,
so the staircase becomes a chamfer and the edge stays crisp. Feathering the
alpha instead was rejected: over a near-black basemap a soft edge reads as haze,
not as land.

Nothing is invented beyond one cell. The fill only ever reaches the first ring,
because bilinear weights vanish past it, and everywhere it goes further coverage
is already 0 and the pixel is transparent.

**Longitude periodicity is a property of the grid, not of the renderer**, which
is why `build_sampler` measures it rather than taking it on faith. A global
cell-centred grid (-179.5..179.5 at 1 degree) leaves half a cell hanging off
each edge of the map and needs a wrap column on *both* ends — wrapping one end
moves the seam rather than closing it, which is how this was originally found.
But the ML prediction grids are **regional** (habitat spans 55..95 degE, bloom
risk 68..78), and wrapping those would splice the Bay of Bengal onto the Arabian
Sea coast: a seam repaired on one grid becomes fabricated data on another. The
span test is what makes one helper safe for both.

**Angular fields must not be averaged as numbers.** A direction on 0-360 has
359 and 1 as neighbours, and their linear mean is 180 — the exact opposite
heading. `build_sampler(..., angular=True)` interpolates sine and cosine
separately and recombines with `atan2`, which is the only correct way to smooth
a heading. See `angular_difference` for the matching subtraction.
"""

from __future__ import annotations

import math

from dataclasses import dataclass

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import distance_transform_edt

# A grid counts as globally periodic when its cells cover 360 degrees to within
# this much. Generous because it only has to separate "spans the planet" from
# "spans a basin" — the narrowest global grid here is 0.083 degrees, the widest
# regional one 40.
_PERIODIC_TOLERANCE_DEG = 1e-6


@dataclass(frozen=True)
class Sampler:
    """A field prepared for smooth resampling: values and coverage separately.

    `angular` fields carry sine and cosine interpolators instead of one value
    interpolator, and recombine to degrees in [0, 360). See the module docstring.
    """

    coverage: RegularGridInterpolator
    values: RegularGridInterpolator | None = None
    sin: RegularGridInterpolator | None = None
    cos: RegularGridInterpolator | None = None

    @property
    def angular(self) -> bool:
        return self.sin is not None

    def __call__(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        """The field on a tile's pixel-centre axes, as (y, x), NaN off-coverage."""
        lon_grid, lat_grid = np.meshgrid(lon, lat)
        points = np.stack([lat_grid.ravel(), lon_grid.ravel()], axis=-1)
        shape = (lat.size, lon.size)

        if self.sin is not None and self.cos is not None:
            degrees = np.degrees(
                np.arctan2(self.sin(points).reshape(shape), self.cos(points).reshape(shape))
            )
            values = np.mod(degrees, 360.0)
        else:
            assert self.values is not None  # one of the two branches always exists
            values = self.values(points).reshape(shape)

        covered = self.coverage(points).reshape(shape) >= 0.5
        return np.where(covered, values, np.nan)


def is_globally_periodic(longitudes: np.ndarray) -> bool:
    """Whether this longitude axis wraps the planet, cells included.

    Measured from the cell *edges*, not the centres: a global 1-degree grid runs
    -179.5..179.5, whose centres span 359 degrees while its cells span 360.
    """
    if longitudes.size < 2:
        return False
    spacing = float(np.abs(np.diff(longitudes)).mean())
    span = float(longitudes[-1] - longitudes[0]) + spacing
    return span >= 360.0 - _PERIODIC_TOLERANCE_DEG


def angular_difference(later: np.ndarray, earlier: np.ndarray) -> np.ndarray:
    """`later - earlier` for headings, wrapped to [-180, 180).

    A 5-degree veer across north is +5, not -355. Plain subtraction is what made
    the forecast map's `change` mode clamp such a veer to the cold end of a
    diverging ramp that only reaches +/-80.
    """
    return (np.asarray(later) - np.asarray(earlier) + 180.0) % 360.0 - 180.0


def build_sampler(field: xr.DataArray, *, angular: bool = False) -> Sampler:
    """Prepare `field` for smooth resampling. See the module docstring."""
    lat = np.asarray(field["latitude"].values, dtype=np.float64)
    lon = np.asarray(field["longitude"].values, dtype=np.float64)
    grid = np.asarray(field.values, dtype=np.float64)

    covered = np.isfinite(grid)
    if covered.any():
        # Nearest valid cell for every hole, in one pass. `distance_transform_edt`
        # measures distance *into* the zero region, so it is handed the holes.
        _, (rows, cols) = distance_transform_edt(~covered, return_indices=True)
        filled = grid[rows, cols]
    else:
        filled = np.zeros_like(grid)

    # Sine/cosine are built from the *filled* grid for the same reason values
    # are: a NaN in either component poisons the recombined angle identically.
    planes = (
        {"sin": np.sin(np.radians(filled)), "cos": np.cos(np.radians(filled))}
        if angular
        else {"values": filled}
    )
    coverage = covered.astype(np.float64)

    axis = lon
    if is_globally_periodic(lon):
        axis = np.concatenate([[lon[-1] - 360.0], lon, [lon[0] + 360.0]])
        planes = {name: _wrap(plane) for name, plane in planes.items()}
        coverage = _wrap(coverage)

    def interpolator(values: np.ndarray) -> RegularGridInterpolator:
        return RegularGridInterpolator(
            (lat, axis), values, method="linear", bounds_error=False, fill_value=np.nan
        )

    return Sampler(
        coverage=interpolator(coverage),
        **{name: interpolator(plane) for name, plane in planes.items()},
    )


def _wrap(plane: np.ndarray) -> np.ndarray:
    """One column of padding at each end, taken from the opposite edge."""
    return np.concatenate([plane[:, -1:], plane, plane[:, :1]], axis=1)


# --------------------------------------------------------------- grid geometry
#
# These three were `services/eddies.py`'s privates until `services/upwelling.py`
# needed the identical arithmetic. They live here rather than being copied
# because a duplicated derivative stencil is the kind of thing that drifts
# silently: two detectors disagreeing about what a metre is would still produce
# plausible fields, and the seam handling below is exactly the part that is easy
# to get subtly different.

EARTH_RADIUS_M = 6_371_000.0


def cell_spacing_m(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, float]:
    """Metres per grid step: dx varies with latitude, dy does not."""
    dlat = math.radians(float(np.abs(np.diff(lat)).mean()))
    dlon = math.radians(float(np.abs(np.diff(lon)).mean()))
    dy = EARTH_RADIUS_M * dlat
    dx = EARTH_RADIUS_M * dlon * np.cos(np.radians(lat))
    # A pole row has dx = 0 and would divide by zero. Callers cut the polar caps
    # anyway; this only keeps the arithmetic finite.
    dx = np.where(np.abs(dx) < 1.0, np.nan, dx)
    return dx, dy


def d_dx(values: np.ndarray, dx: np.ndarray, periodic: bool) -> np.ndarray:
    """Centred difference along longitude, closing the seam when global."""
    if periodic:
        forward = np.roll(values, -1, axis=1)
        backward = np.roll(values, 1, axis=1)
        return (forward - backward) / (2.0 * dx[:, None])
    return np.gradient(values, axis=1) / dx[:, None]


def d_dy(values: np.ndarray, dy: float) -> np.ndarray:
    """Centred difference along latitude. Never periodic — the poles are ends."""
    return np.gradient(values, axis=0) / dy


def cell_edges(centres: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Half a step either side of each cell centre.

    Grids here are cell-*centred*, so a polygon drawn from centre to centre is
    offset by half a step and lands visibly beside the basemap's coastline. Same
    centre-versus-edge distinction `is_globally_periodic` measures, and the
    reason it is shared: two detectors drawing cells half a step apart would
    both look plausible.
    """
    step = float(np.abs(np.diff(centres)).mean()) if centres.size > 1 else 1.0
    return centres - step / 2.0, centres + step / 2.0
