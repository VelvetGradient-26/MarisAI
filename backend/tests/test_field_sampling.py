"""The shared resampler: coastlines, longitude periodicity, and bearings.

Three defects live here, and what they have in common is that every one of them
renders. A poisoned coastline is a plausible map with less ocean on it; a wrap
column spliced onto a regional grid is a plausible map of somewhere else; a
bearing averaged as a number is a plausible arrow pointing the wrong way. None
of them raises, so nothing but a test notices.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from services.field_sampling import (
    angular_difference,
    build_sampler,
    is_globally_periodic,
)


def _field(values: np.ndarray, latitudes: np.ndarray, longitudes: np.ndarray) -> xr.DataArray:
    return xr.DataArray(
        values,
        coords={"latitude": latitudes, "longitude": longitudes},
        dims=("latitude", "longitude"),
    )


def _global_grid(spacing: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Cell *centred*, like the forecast grids: -179.5..179.5 at 1 degree."""
    half = spacing / 2.0
    return (
        np.arange(-90.0 + half, 90.0, spacing),
        np.arange(-180.0 + half, 180.0, spacing),
    )


# --------------------------------------------------------------------------
# Coastlines
# --------------------------------------------------------------------------


def test_a_cell_next_to_a_gap_keeps_its_own_value():
    """The erosion bug, at its smallest. A bilinear read of a NaN-holed array
    returns NaN for anything touching the hole, so the cell beside a coast — the
    coastal water these layers exist to show — came back empty."""
    latitudes = np.array([0.0, 1.0, 2.0])
    longitudes = np.array([10.0, 11.0, 12.0])
    values = np.full((3, 3), 5.0)
    values[:, 2] = np.nan  # land in the eastern column
    field = _field(values, latitudes, longitudes)

    sampled = build_sampler(field)(longitudes, latitudes)

    # The middle column touches the hole and must survive at its own value.
    assert sampled[1, 1] == pytest.approx(5.0)
    # The land column stays absent — filling values must not paint over it.
    assert np.isnan(sampled[1, 2])

    # The erosion is *between* cells, not at their centres: a cell centre has
    # bilinear weights (1, 0, 0, 0), so even the old path returned its value
    # untouched. What vanished was every pixel in the strip between the last
    # ocean cell and the first land cell — which at tile resolution is most of
    # the pixels there are.
    strip_lon = np.array([11.25])
    strip_lat = np.array([1.0])
    assert np.isfinite(build_sampler(field)(strip_lon, strip_lat)[0, 0])

    poisoned = field.interp(
        latitude=xr.DataArray(strip_lat, dims="y"),
        longitude=xr.DataArray(strip_lon, dims="x"),
        method="linear",
        kwargs={"bounds_error": False, "fill_value": np.nan},
    ).values
    assert np.isnan(poisoned[0, 0]), "the old path must still demonstrate the defect"


def test_covered_cell_centres_sample_to_their_own_value_exactly():
    """`point()` answers nearest-cell while the tile answers interpolated, and
    the two must agree where a cell centre is the sample. An 0.0 tolerance,
    because anything else means the fill leaked into covered water."""
    latitudes, longitudes = _global_grid(spacing=10.0)
    rng = np.random.default_rng(0)
    values = rng.normal(size=(latitudes.size, longitudes.size))
    values[:3, :3] = np.nan
    field = _field(values, latitudes, longitudes)

    sampled = build_sampler(field)(longitudes, latitudes)

    covered = np.isfinite(values)
    assert np.array_equal(np.isfinite(sampled), covered)
    assert np.abs(sampled[covered] - values[covered]).max() == 0.0


# --------------------------------------------------------------------------
# Longitude periodicity
# --------------------------------------------------------------------------


def test_a_global_cell_centred_grid_is_periodic_and_a_regional_one_is_not():
    _, global_longitudes = _global_grid()
    assert is_globally_periodic(global_longitudes)

    # The habitat export's real extent. Wrapping this would splice 95degE onto
    # 55degE — a fabricated coastline, not a repaired seam.
    assert not is_globally_periodic(np.arange(55.0, 95.25, 0.25))


def test_a_regional_grid_is_not_wrapped_across_its_own_edges():
    latitudes = np.array([0.0, 1.0])
    longitudes = np.array([55.0, 56.0, 57.0])
    # Distinct values per column, so a wrap would be visible as the wrong one.
    field = _field(np.tile(np.array([1.0, 2.0, 9.0]), (2, 1)), latitudes, longitudes)

    sampler = build_sampler(field)

    # Just outside the western edge: off-grid, so absent — *not* the value from
    # the far side of the basin.
    outside = sampler(np.array([54.0]), np.array([0.5]))
    assert np.isnan(outside[0, 0])


def test_a_global_grid_has_no_gap_at_either_end_of_the_map():
    """Cell-centred grids leave half a cell hanging off each edge, so the wrap
    goes on both. Wrapping one end only moves the seam — which is how this was
    originally found, by a test that passed at the dateline and failed at -180."""
    latitudes, longitudes = _global_grid()
    field = _field(np.ones((latitudes.size, longitudes.size)), latitudes, longitudes)

    sampler = build_sampler(field)
    for edge in (-179.99, 179.99):
        sampled = sampler(np.array([edge]), np.array([0.0]))
        assert np.isfinite(sampled[0, 0]), f"no-data seam at longitude {edge}"


# --------------------------------------------------------------------------
# Bearings
# --------------------------------------------------------------------------


def test_averaging_two_headings_across_north_does_not_point_south():
    """The whole reason `angular` exists. 359 and 1 are two degrees apart; their
    arithmetic mean is 180, the exact opposite heading, and it renders."""
    latitudes = np.array([0.0, 1.0])
    longitudes = np.array([10.0, 11.0])
    field = _field(np.tile(np.array([359.0, 1.0]), (2, 1)), latitudes, longitudes)

    midpoint = np.array([10.5]), np.array([0.5])
    linear = build_sampler(field)(*midpoint)[0, 0]
    angular = build_sampler(field, angular=True)(*midpoint)[0, 0]

    assert linear == pytest.approx(180.0), "the defect must still be reproducible"
    # 0 and 360 are the same heading, so accept either representation.
    assert min(angular, 360.0 - angular) == pytest.approx(0.0, abs=1e-6)


def test_an_angular_sampler_stays_inside_the_bearing_domain():
    latitudes, longitudes = _global_grid(spacing=10.0)
    rng = np.random.default_rng(1)
    values = rng.uniform(0.0, 360.0, size=(latitudes.size, longitudes.size))
    field = _field(values, latitudes, longitudes)

    sampled = build_sampler(field, angular=True)(longitudes + 3.0, latitudes)

    finite = sampled[np.isfinite(sampled)]
    assert finite.min() >= 0.0
    assert finite.max() < 360.0


@pytest.mark.parametrize(
    ("later", "earlier", "expected"),
    [
        (5.0, 355.0, 10.0),  # a small veer clockwise across north
        (355.0, 5.0, -10.0),  # and the same veer back
        (10.0, 5.0, 5.0),  # nowhere near the wrap, unchanged
        # Half a turn is genuinely ambiguous — +180 and -180 are the same
        # rotation — and the modulo resolves it to the negative end. Pinned
        # so the choice is deliberate rather than incidental.
        (180.0, 0.0, -180.0),
    ],
)
def test_angular_difference_wraps_to_a_signed_half_turn(later, earlier, expected):
    assert angular_difference(later, earlier) == pytest.approx(expected)


def test_angular_difference_never_exceeds_half_a_turn():
    """What the `change` layer depends on: a veer must never be reported as
    -355, which on a diverging ramp clamps to the far cold end."""
    rng = np.random.default_rng(2)
    later = rng.uniform(0.0, 360.0, size=1000)
    earlier = rng.uniform(0.0, 360.0, size=1000)

    difference = angular_difference(later, earlier)

    assert difference.min() >= -180.0 - 1e-9
    assert difference.max() < 180.0 + 1e-9
