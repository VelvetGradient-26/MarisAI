"""The process-wide HDF5 lock (app/core/netcdf_lock.py) and the reads it must cover."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from app.core.netcdf_lock import NETCDF_LOCK
from services.climatology import oisst


def test_nested_acquire_does_not_deadlock():
    # _derive_grid_from_components holds the lock while calling code that may
    # take it again; a plain Lock would hang this thread forever.
    with NETCDF_LOCK:
        reacquired = NETCDF_LOCK.acquire(timeout=1)
        if reacquired:
            NETCDF_LOCK.release()
    assert reacquired


@pytest.fixture
def small_oisst_bytes() -> bytes:
    dataset = xr.Dataset(
        {"sst": (("time", "zlev", "latitude", "longitude"), np.ones((3, 1, 2, 2), dtype="float32"))},
        coords={
            "time": pd.date_range("2026-10-01", periods=3, freq="D"),
            "zlev": [0.0],
            "latitude": [10.0, 11.0],
            "longitude": [70.0, 71.0],
        },
    )
    return dataset.to_netcdf()


async def test_fetch_recent_returns_a_loaded_dataset(monkeypatch, small_oisst_bytes):
    # A lazily opened dataset would do its HDF5 reads later, outside the lock.
    async def fake_get(url: str) -> bytes:
        return small_oisst_bytes

    monkeypatch.setattr(oisst, "_get", fake_get)
    dataset = await oisst.fetch_recent(3)
    assert all(dataset[name].variable._in_memory for name in dataset.data_vars)
