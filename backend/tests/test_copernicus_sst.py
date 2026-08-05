"""The SST cache's memory shape, and the statistics read back out of it.

This module exists because `copernicus_sst` is one of the two largest resident
objects in the process — a global 0.083deg field — and the two properties that
keep it that size are both easy to undo by accident while making an unrelated
change.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

import services.copernicus_sst as sst

LAT = np.linspace(-80.0, 90.0, 401).astype(np.float64)
LON = np.linspace(-180.0, 179.0, 800).astype(np.float64)


def _grid(seed: int = 0) -> np.ndarray:
    """A synthetic global field with land (NaN) punched through it."""
    rng = np.random.default_rng(seed)
    field = rng.random((LAT.size, LON.size)) * 30.0 - 2.0
    field[rng.random(field.shape) < 0.3] = np.nan
    return field.astype(np.float32)


@pytest.fixture
def cache(monkeypatch):
    field = _grid()
    entry = sst._SstCache(
        interpolator=sst._build_interpolator(LAT, LON, field),
        timestamp=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        latitudes=LAT,
        longitudes=LON,
    )
    monkeypatch.setattr(sst, "_cache", entry)
    return entry, field


def test_the_cached_field_stays_float32(cache):
    """float64 stores nothing this product measured and doubles ~35MB.

    Asserted on the interpolator's own array rather than on what was handed in,
    because SciPy is free to cast on construction and silently give the memory
    back — which would make the saving invisible until something profiled it.
    """
    entry, _ = cache
    assert entry.interpolator.values.dtype == np.float32


def test_the_grid_is_not_a_second_copy(cache):
    """The whole point of the property: one array, not two.

    A plain `grid: np.ndarray` field alongside the interpolator is the obvious
    way to write this and costs a full duplicate of the field. `.base` catches
    that — a view carries one, a fresh allocation does not.
    """
    entry, _ = cache
    assert entry.grid.base is not None, "grid is an allocation, not a view into the interpolator"
    assert np.shares_memory(entry.grid, entry.interpolator.values)


def test_the_grid_drops_the_antimeridian_duplicate(cache):
    """`_build_interpolator` appends a wrapped copy of the first column.

    Reading the interpolator's array back without slicing it off would count
    one column of ocean twice in every global statistic.
    """
    entry, field = cache
    assert entry.grid.shape == field.shape
    np.testing.assert_array_equal(entry.grid, field)


def test_global_stats_matches_a_float64_reference(cache):
    """float32 must not move the reported numbers at the precision published.

    The reference is computed the way the cache used to store it — a separate
    float64 array — so this fails if the narrowing ever costs real precision
    rather than just memory.
    """
    _, field = cache
    reference = field.astype(np.float64)
    valid = np.isfinite(reference)
    weights = np.broadcast_to(np.cos(np.radians(LAT))[:, None], reference.shape)
    expected = float(np.average(reference[valid], weights=weights[valid]))

    stats = sst.global_stats()
    assert stats["mean_c"] == pytest.approx(expected, abs=5e-4)
    assert stats["valid_cells"] == int(valid.sum())
    assert stats["min_c"] == pytest.approx(float(reference[valid].min()), abs=0.01)
    assert stats["max_c"] == pytest.approx(float(reference[valid].max()), abs=0.01)


def test_global_stats_weights_by_area(cache):
    """cos(latitude) weighting is load-bearing, not decorative.

    On an equal-angle grid a polar cell covers ~1/11th the area of an equatorial
    one. A uniform field is the clean way to catch a dropped weight: the correct
    weighted mean is exactly the field's value regardless of the weighting, so
    instead the test tilts the field by latitude, where an unweighted mean lands
    measurably colder.
    """
    warm_south = np.tile(np.linspace(30.0, 0.0, LAT.size)[:, None], (1, LON.size))
    field = warm_south.astype(np.float32)
    sst._cache = sst._SstCache(
        interpolator=sst._build_interpolator(LAT, LON, field),
        timestamp=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        latitudes=LAT,
        longitudes=LON,
    )

    weights = np.cos(np.radians(LAT))
    expected = float(np.average(warm_south[:, 0], weights=weights))
    unweighted = float(warm_south.mean())

    stats = sst.global_stats()
    assert stats["mean_c"] == pytest.approx(expected, abs=1e-3)
    assert stats["mean_c"] != pytest.approx(unweighted, abs=1e-3)
