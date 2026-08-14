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


# --------------------------------------------------------------------------
# The hang guard
# --------------------------------------------------------------------------


def test_a_provider_that_goes_silent_is_abandoned_rather_than_waited_on(monkeypatch):
    """The failure that cost 11 hours on 2026-08-14.

    A `--all` build completed 9 of 13 providers and then stopped: 41 sockets to
    Copernicus in CLOSE_WAIT, the remote having closed them, the client waiting
    on dead sockets. Nothing raised, nothing logged, the process stayed alive.
    An error can be retried; silence cannot be noticed, which is why a timeout
    is a different guarantee from a retry and why both paths need one.
    """
    import asyncio

    monkeypatch.setattr(grid_history, "_FETCH_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(grid_history, "_FETCH_ATTEMPTS", 2)
    monkeypatch.setattr(grid_history, "_RETRY_BACKOFF_SECONDS", 0.0)

    async def _never_returns(*_args, **_kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(grid_history, "_fetch_provider", _never_returns)

    async def _run():
        return await grid_history._fetch_with_timeout(
            PROVIDER, grid_history.catalog.get(PROVIDER), ["uo"], _request()
        )

    with pytest.raises(grid_history.GridHistoryError, match="stopped responding"):
        asyncio.run(asyncio.wait_for(_run(), timeout=10))


def test_a_provider_that_recovers_on_the_second_attempt_is_not_failed(monkeypatch):
    """One retry, because a transient stall is common and a whole-globe refetch
    is expensive enough that giving up on the first is the wrong trade."""
    import asyncio

    monkeypatch.setattr(grid_history, "_FETCH_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(grid_history, "_FETCH_ATTEMPTS", 2)
    monkeypatch.setattr(grid_history, "_RETRY_BACKOFF_SECONDS", 0.0)

    calls = {"n": 0}

    async def _slow_then_fine(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(3600)
        return _dataset(["uo"])

    monkeypatch.setattr(grid_history, "_fetch_provider", _slow_then_fine)

    async def _run():
        return await grid_history._fetch_with_timeout(
            PROVIDER, grid_history.catalog.get(PROVIDER), ["uo"], _request()
        )

    result = asyncio.run(asyncio.wait_for(_run(), timeout=10))

    assert calls["n"] == 2
    assert set(result.data_vars) == {"uo"}


def test_warming_holds_one_provider_at_a_time(monkeypatch):
    """Why `warm` exists rather than reusing `fetch_stack`.

    `fetch_stack` returns a stack holding every provider's dataset at once,
    because a build needs them together to slice a cell. Warming does not — each
    is written to disk and then useless in memory. Doing it through `fetch_stack`
    reached 13 GB resident on an 8 GB machine, and the concurrency limit does not
    help: it bounds how many are *fetching*, not how many stay alive after.
    """
    import asyncio

    live: list[str] = []
    peak = {"n": 0}

    async def _fetch(provider_key, _spec, fields, _request):
        live.append(provider_key)
        peak["n"] = max(peak["n"], len(live))
        await asyncio.sleep(0)
        live.remove(provider_key)
        return _dataset(list(fields))

    monkeypatch.setattr(grid_history, "_fetch_with_timeout", _fetch)

    warmed = asyncio.run(
        grid_history.warm(
            GridRequest(
                codes=("sea_surface_temperature", "significant_wave_height", "ocean_depth"),
                start_date=date(2026, 6, 29),
                end_date=date(2026, 8, 13),
                resolution_deg=1.0,
            )
        )
    )

    assert len(warmed) > 1, "the test needs several providers to be meaningful"
    assert peak["n"] == 1, f"{peak['n']} providers were alive at once; warming must hold one"


def test_a_provider_that_fails_to_warm_does_not_fail_the_run(monkeypatch):
    """Warming is an optimisation. The real build fetches and reports properly on
    whatever is missing, so a failure here must degrade to a log line."""
    import asyncio

    async def _explode(provider_key, _spec, _fields, _request):
        if provider_key == "gebco":
            raise RuntimeError("ERDDAP is flapping")
        return _dataset(["thetao"])

    monkeypatch.setattr(grid_history, "_fetch_with_timeout", _explode)

    warmed = asyncio.run(
        grid_history.warm(
            GridRequest(
                codes=("sea_surface_temperature", "ocean_depth"),
                start_date=date(2026, 6, 29),
                end_date=date(2026, 8, 13),
                resolution_deg=1.0,
            )
        )
    )

    assert "gebco" not in warmed
    assert "copernicus_physics" in warmed
