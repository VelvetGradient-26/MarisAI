"""The dedicated-thread fetch runner and the on-disk last-good cache."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone

import numpy as np
import pytest

from app.core import copernicus_io, disk_cache
from services import copernicus_sst


def test_a_hung_fetch_times_out_without_starving_the_default_executor():
    release = threading.Event()

    async def scenario():
        started = time.monotonic()
        with pytest.raises(copernicus_io.CopernicusFetchTimeout):
            await copernicus_io.run_fetch("hung", release.wait, timeout=0.2)
        assert time.monotonic() - started < 2

        # The abandoned read still holds its key, so the next tick skips
        # rather than stacking a second zombie behind it...
        with pytest.raises(copernicus_io.CopernicusFetchBusy):
            await copernicus_io.run_fetch("hung", lambda: None, timeout=0.2)

        # ...while ordinary to_thread work (tile rendering) is unaffected.
        assert await asyncio.wait_for(asyncio.to_thread(lambda: 42), timeout=1) == 42

    try:
        asyncio.run(scenario())
    finally:
        release.set()

    deadline = time.monotonic() + 2
    while copernicus_io.is_in_flight("hung") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not copernicus_io.is_in_flight("hung")


def test_run_fetch_returns_results_and_propagates_errors():
    async def scenario():
        assert await copernicus_io.run_fetch("ok", lambda: 7) == 7
        with pytest.raises(ValueError):
            await copernicus_io.run_fetch("boom", _raise)

    asyncio.run(scenario())


def _raise():
    raise ValueError("upstream said no")


def test_disk_cache_round_trips_and_replaces_atomically():
    grid = np.arange(12, dtype=np.float32).reshape(3, 4)
    assert disk_cache.save("field", {"grid": grid}, {"timestamp": "t1"})
    assert disk_cache.save("field", {"grid": grid + 1}, {"timestamp": "t2"})

    arrays, meta = disk_cache.load("field")
    assert meta == {"timestamp": "t2"}
    np.testing.assert_array_equal(arrays["grid"], grid + 1)
    # No temp files left behind next to the one canonical file.
    assert [p.name for p in disk_cache.CACHE_DIR.iterdir()] == ["field.npz"]


def test_a_failed_write_keeps_the_previous_copy(monkeypatch):
    good = np.ones((2, 2), dtype=np.float32)
    assert disk_cache.save("field", {"grid": good}, {"timestamp": "good"})

    # The read-back check fails: the new file must never replace the old one.
    real_load = disk_cache.load
    monkeypatch.setattr(disk_cache, "load", lambda key, path=None: None if path else real_load(key))
    assert not disk_cache.save("field", {"grid": good * 5}, {"timestamp": "bad"})
    monkeypatch.setattr(disk_cache, "load", real_load)

    arrays, meta = disk_cache.load("field")
    assert meta == {"timestamp": "good"}
    np.testing.assert_array_equal(arrays["grid"], good)
    assert [p.name for p in disk_cache.CACHE_DIR.iterdir()] == ["field.npz"]


def test_sst_refresh_persists_and_a_restart_restores_with_its_real_age(monkeypatch):
    lat = np.linspace(-80, 80, 5)
    lon = np.linspace(-180, 175, 8)
    grid = np.full((5, 8), 20.0, dtype=np.float32)
    stamp = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(copernicus_sst, "_fetch_latest_grid", lambda: (lat, lon, grid, stamp))
    monkeypatch.setattr(copernicus_sst, "_cache", None)

    asyncio.run(copernicus_sst.refresh_sst_cache())
    fetched_at = copernicus_sst._cache.fetched_at
    assert copernicus_sst.get_meta()["from_disk_cache"] is False

    # A "restart": memory is empty, the file is not.
    monkeypatch.setattr(copernicus_sst, "_cache", None)
    restored_at = asyncio.run(copernicus_sst.restore_from_disk())

    assert restored_at == fetched_at
    meta = copernicus_sst.get_meta()
    assert meta["from_disk_cache"] is True
    assert meta["timestamp"] == stamp.isoformat()
    assert meta["fetched_at"] == fetched_at.isoformat()
    assert copernicus_sst.get_point(0.0, 0.0)["temperature_c"] == 20.0


def test_restore_never_replaces_a_fresher_in_memory_cache(monkeypatch):
    lat = np.linspace(-80, 80, 5)
    lon = np.linspace(-180, 175, 8)
    old = datetime(2026, 9, 15, tzinfo=timezone.utc)
    disk_cache.save(
        "sst",
        {"lat": lat, "lon": lon, "grid": np.full((5, 8), 1.0, dtype=np.float32)},
        {"timestamp": old.isoformat(), "fetched_at": old.isoformat()},
    )
    new = datetime(2026, 9, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(
        copernicus_sst,
        "_fetch_latest_grid",
        lambda: (lat, lon, np.full((5, 8), 9.0, dtype=np.float32), new),
    )
    monkeypatch.setattr(copernicus_sst, "_cache", None)
    asyncio.run(copernicus_sst.refresh_sst_cache())

    asyncio.run(copernicus_sst.restore_from_disk())
    assert copernicus_sst.get_point(0.0, 0.0)["temperature_c"] == 9.0
    assert copernicus_sst.get_meta()["from_disk_cache"] is False
