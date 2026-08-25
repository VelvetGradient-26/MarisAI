"""services/climatology/copernicus_reanalysis.py: depth resolution and
coarsening, checked without touching the network.

`copernicusmarine.open_dataset` is monkeypatched at the point this module
calls it (inside `_open_lazy`, imported lazily the same way
`services/copernicus_sst.py` and `services/download/providers/copernicus.py`
both do) — a synthetic lazy (dask-backed) xarray Dataset stands in for what
the real service would return.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from services.climatology import copernicus_reanalysis as cr


def _synthetic_dataset(*, with_depth: bool = True, n_days: int = 5) -> xr.Dataset:
    lat = np.linspace(-2.0, 2.0, 24)  # 4 deg span / 1 deg target -> factor 4-ish at 1/12 native...
    lon = np.linspace(-2.0, 2.0, 24)
    times = pd.date_range("2010-01-01", periods=n_days, freq="D")
    rng = np.random.default_rng(0)

    if with_depth:
        depth = np.array([0.494, 1.54, 2.65])
        values = rng.normal(20.0, 1.0, size=(n_days, depth.size, lat.size, lon.size)).astype("float64")
        data = xr.DataArray(
            values,
            dims=("time", "depth", "latitude", "longitude"),
            coords={"time": times, "depth": depth, "latitude": lat, "longitude": lon},
        )
    else:
        values = rng.normal(20.0, 1.0, size=(n_days, lat.size, lon.size)).astype("float64")
        data = xr.DataArray(
            values,
            dims=("time", "latitude", "longitude"),
            coords={"time": times, "latitude": lat, "longitude": lon},
        )

    return xr.Dataset({cr.VARIABLE: data.chunk({"time": 1})})


def test_resolve_depth_takes_the_surface_level_and_drops_the_coord():
    dataset = _synthetic_dataset(with_depth=True)
    resolved = cr._resolve_depth(dataset)
    assert "depth" not in resolved.dims
    assert "depth" not in resolved.coords
    # The surface level (index 0, 0.494 m) is what a `minimum_depth`/
    # `maximum_depth` server-side bound of [0, 1] actually returns — this
    # just has to pick it consistently, not re-derive the bound.
    np.testing.assert_array_equal(
        resolved[cr.VARIABLE].values, dataset[cr.VARIABLE].isel(depth=0).values
    )


def test_resolve_depth_is_a_noop_without_a_depth_dim():
    dataset = _synthetic_dataset(with_depth=False)
    resolved = cr._resolve_depth(dataset)
    xr.testing.assert_identical(resolved, dataset)


def test_coarsen_block_averages_by_the_resolution_ratio():
    dataset = _synthetic_dataset(with_depth=False)
    # Native spacing here is 4/24 = 1/6 deg (not the real dataset's 1/12, but
    # `_coarsen` only cares about the ratio) — monkeypatch-free by computing
    # the factor directly rather than trusting the module constant.
    native = 4.0 / 24.0
    factor = 3
    resolution_deg = native * factor

    import services.climatology.copernicus_reanalysis as cr_mod

    original_spacing = cr_mod.NATIVE_SPACING_DEG
    cr_mod.NATIVE_SPACING_DEG = native
    try:
        coarsened = cr_mod._coarsen(dataset, resolution_deg)
    finally:
        cr_mod.NATIVE_SPACING_DEG = original_spacing

    assert coarsened.sizes["latitude"] == dataset.sizes["latitude"] // factor
    assert coarsened.sizes["longitude"] == dataset.sizes["longitude"] // factor
    # A block mean must fall strictly within the range of the values it
    # averaged — the cheapest possible check that this reduced rather than,
    # say, silently resampled by nearest-neighbour.
    assert float(coarsened[cr.VARIABLE].min()) >= float(dataset[cr.VARIABLE].min())
    assert float(coarsened[cr.VARIABLE].max()) <= float(dataset[cr.VARIABLE].max())


def test_coarsen_is_a_noop_at_native_resolution():
    dataset = _synthetic_dataset(with_depth=False)
    coarsened = cr._coarsen(dataset, cr.NATIVE_SPACING_DEG)
    assert coarsened.sizes == dataset.sizes


def test_stride_for_rejects_a_finer_than_native_request():
    with pytest.raises(cr.CopernicusReanalysisError):
        cr.stride_for(cr.NATIVE_SPACING_DEG / 2)


@pytest.mark.asyncio
async def test_fetch_range_raises_on_an_empty_response(monkeypatch):
    def fake_open_lazy(start: date, end: date):
        return _synthetic_dataset(with_depth=True, n_days=0)

    monkeypatch.setattr(cr, "_open_lazy", fake_open_lazy)

    with pytest.raises(cr.CopernicusReanalysisError):
        await cr.fetch_range(date(2010, 1, 1), date(2010, 1, 5))


@pytest.mark.asyncio
async def test_fetch_range_returns_a_loaded_surface_only_dataset(monkeypatch):
    def fake_open_lazy(start: date, end: date):
        return _synthetic_dataset(with_depth=True, n_days=5)

    monkeypatch.setattr(cr, "_open_lazy", fake_open_lazy)

    result = await cr.fetch_range(date(2010, 1, 1), date(2010, 1, 5), resolution_deg=cr.NATIVE_SPACING_DEG)

    assert "depth" not in result.dims
    assert result.sizes["time"] == 5
    # `.load()`'d, not still dask-backed — a caller doing 366 fancy-index
    # lookups per day-of-year (`build.fit_percentiles`) on a lazy array would
    # re-read every chunk per lookup, the exact trap `build_climatology.py`'s
    # own docstring names for the OISST path.
    assert isinstance(result[cr.VARIABLE].data, np.ndarray)


@pytest.mark.asyncio
async def test_a_provider_failure_is_wrapped(monkeypatch):
    def fake_open_lazy(start: date, end: date):
        raise RuntimeError("copernicusmarine could not authenticate")

    monkeypatch.setattr(cr, "_open_lazy", fake_open_lazy)

    with pytest.raises(cr.CopernicusReanalysisError):
        await cr.fetch_range(date(2010, 1, 1), date(2010, 1, 5))
