"""The grid fetch cache, whose only symptom when wrong is that a build is slow.

Nothing here fails loudly. A cache that misses still produces a correct grid —
it just refetches a whole-globe product, which was measured at 35 minutes for
the physics dataset. Across a 26-variable build that difference is most of a
day, and there is no error anywhere to notice it by.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest
import xarray as xr

from forecasting import grid_history
from forecasting.grid_history import GridRequest


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(grid_history, "CACHE_DIR", tmp_path / "grid")
    return tmp_path / "grid"


def _dataset(fields: list[str]) -> xr.Dataset:
    return xr.Dataset(
        {name: (("latitude", "longitude"), np.full((2, 2), float(index)))
         for index, name in enumerate(fields)},
        coords={"latitude": [0.0, 1.0], "longitude": [10.0, 11.0]},
    )


def _request() -> GridRequest:
    return GridRequest(
        codes=("sea_surface_temperature",),
        start_date=date(2026, 6, 29),
        end_date=date(2026, 8, 13),
        resolution_deg=1.0,
    )


PROVIDER = "copernicus_physics"
TTL = timedelta(hours=6)


def _put(fields: list[str], request: GridRequest, stride: int = 12) -> None:
    key = grid_history._cache_key(PROVIDER, fields, request, stride)
    grid_history._cache_put(key, _dataset(fields))


def test_an_exact_field_match_is_a_hit():
    request = _request()
    _put(["uo", "zos"], request)

    cached = grid_history._cache_get(PROVIDER, ["uo", "zos"], request, 12, TTL)

    assert cached is not None
    assert set(cached.data_vars) == {"uo", "zos"}


def test_a_wider_cached_fetch_serves_a_narrower_request():
    """The fix. `current_u` wants (uo, zos) and `current_v` wants (vo, zos); on a
    field-keyed cache the second misses and repeats a 35-minute global fetch."""
    request = _request()
    _put(["uo", "vo", "zos", "thetao"], request)

    cached = grid_history._cache_get(PROVIDER, ["vo", "zos"], request, 12, TTL)

    assert cached is not None
    # Subset on the way out: the caller asked for two fields and must not have
    # to know it was handed a slice of something wider.
    assert set(cached.data_vars) == {"vo", "zos"}


def test_a_narrower_cached_fetch_does_not_serve_a_wider_request():
    request = _request()
    _put(["uo"], request)

    assert grid_history._cache_get(PROVIDER, ["uo", "zos"], request, 12, TTL) is None


def test_a_different_window_is_never_reused():
    """Scope still separates entries. Serving one window's data for another is
    the failure the cache key exists to prevent, and it would be invisible."""
    _put(["uo", "zos"], _request())

    other = GridRequest(
        codes=("sea_surface_temperature",),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 1),
        resolution_deg=1.0,
    )
    assert grid_history._cache_get(PROVIDER, ["uo"], other, 12, TTL) is None


def test_a_different_stride_is_never_reused():
    request = _request()
    _put(["uo", "zos"], request, stride=12)

    assert grid_history._cache_get(PROVIDER, ["uo"], request, 8, TTL) is None


def test_a_stale_entry_is_not_served():
    request = _request()
    _put(["uo", "vo", "zos"], request)

    assert grid_history._cache_get(PROVIDER, ["uo"], request, 12, timedelta(seconds=0)) is None


def test_a_corrupt_entry_is_discarded_rather_than_raising():
    request = _request()
    _put(["uo", "zos"], request)
    key = grid_history._cache_key(PROVIDER, ["uo", "zos"], request, 12)
    (grid_history.CACHE_DIR / f"{key}.nc").write_bytes(b"not a netcdf file")

    assert grid_history._cache_get(PROVIDER, ["uo", "zos"], request, 12, TTL) is None
    assert not (grid_history.CACHE_DIR / f"{key}.nc").exists()
