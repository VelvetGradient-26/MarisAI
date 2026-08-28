"""The whole-globe fetch must bound how many chunks it materialises at once.

Why this is a test and not a comment: the bound is one call (`_bounded_load`)
standing where the obvious code is `.load()`, and every future edit to this
function will be tempted to write the obvious thing. The failure it prevents is
not an exception — it is a process that quietly needs several GB more than the
machine has, which shows up as swapping or an OOM kill on the deployment target
rather than as a red test.

`_coarsen` already strides before materialising, and its docstring used to say
that kept the peak at "roughly one chunk". That is true per dask *task* and
false per *process*: the threaded scheduler defaults to one worker per core, and
`grid_history` fetches every provider concurrently on top of that. Measured on
an 8-core / 8 GB machine, one variable's grid build peaked at ~3.0 GB.
"""

from __future__ import annotations

import dask
import numpy as np
import pytest
import xarray as xr

from services.download.providers import copernicus


def _lazy_global(timesteps: int = 6) -> xr.Dataset:
    """A chunked dataset shaped like arco-geo-series: one chunk per timestep."""
    data = np.zeros((timesteps, 40, 80), dtype="float64")
    dataset = xr.Dataset(
        {"thetao": (("time", "latitude", "longitude"), data)},
        coords={
            "time": np.arange(timesteps),
            "latitude": np.linspace(-80, 80, 40),
            "longitude": np.linspace(-180, 175, 80),
        },
    )
    return dataset.chunk({"time": 1})


def test_bounded_load_caps_the_workers_dask_is_given():
    seen: dict[str, object] = {}

    original = xr.Dataset.load

    def spy(self, **kwargs):
        seen["num_workers"] = dask.config.get("num_workers", None)
        seen["scheduler"] = dask.config.get("scheduler", None)
        return original(self, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(xr.Dataset, "load", spy)
        copernicus._bounded_load(_lazy_global())

    assert seen["scheduler"] == "threads"
    assert seen["num_workers"] == copernicus._GLOBAL_LOAD_THREADS


def test_the_bound_is_small_enough_to_stay_under_the_s3_connection_pool():
    """botocore's default pool is 10 and `copernicusmarine` never raises it.

    Two providers are fetched concurrently for a typical variable (its own
    dataset plus a covariate's), so the per-provider bound has to leave room
    for that. If this ever needs to rise, raise the pool first — otherwise the
    extra threads discard and re-handshake connections, which is what the
    original 8-wide fetch was doing.
    """
    assert copernicus._GLOBAL_LOAD_THREADS * 2 <= 10


def test_the_bound_is_scoped_and_does_not_leak_to_the_rest_of_the_process():
    """Bbox fetches and the ML pipelines share this process-wide config.

    Setting `num_workers` globally would throttle the downloader's small
    fetches too, for no benefit — they are nowhere near this size.
    """
    before = dask.config.get("num_workers", None)
    copernicus._bounded_load(_lazy_global())
    assert dask.config.get("num_workers", None) == before


def test_bounded_load_returns_the_same_values_as_a_plain_load():
    """The bound is a scheduling constraint, not a data transformation."""
    lazy = _lazy_global()
    lazy["thetao"] = lazy.thetao + xr.DataArray(
        np.arange(6, dtype="float64"), dims="time", coords={"time": lazy.time}
    )

    bounded = copernicus._bounded_load(lazy.copy(deep=False))
    plain = lazy.copy(deep=False).load()

    xr.testing.assert_identical(bounded, plain)
