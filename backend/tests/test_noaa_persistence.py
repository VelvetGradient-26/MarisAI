"""NOAA-backed layers survive a restart during a NOAA outage.

CoastWatch's ERDDAP flaps (404s on datasets that exist), and both the marine
heatwave field and Coral Reef Watch were memory-only: a restart while it was
down left both layers 503 until NOAA answered again. Seen live on 21 Oct
2026 after a redeploy. Each now saves its last good result to the disk cache
and restores it on the first refresh of a process, before any network call.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import numpy as np

from services import crw, heatwaves


def _field() -> heatwaves.HeatwaveField:
    shape = (2, 3)
    return heatwaves.HeatwaveField(
        category=np.ones(shape, dtype="int8"),
        exceedance=np.full(shape, 0.7, dtype="float32"),
        run_days=np.full(shape, 6, dtype="int16"),
        latitude=np.array([0.0, 1.0]),
        longitude=np.array([10.0, 11.0, 12.0]),
        timestamp=datetime(2026, 10, 5, 12, tzinfo=UTC),
        computed_at=datetime(2026, 10, 19, 15, tzinfo=UTC),
        baseline=(1991, 2020),
        window_days=30,
        anomaly=np.full(shape, 1.2, dtype="float32"),
        cold_exceedance=np.full(shape, 2.0, dtype="float32"),
    )


def test_a_heatwave_field_is_restored_when_noaa_is_down(monkeypatch):
    saved = _field()
    assert heatwaves.save_to_disk(saved) is True
    monkeypatch.setattr(heatwaves, "_cache", None)

    async def noaa_down(*args, **kwargs):
        raise RuntimeError("404 from CoastWatch")

    monkeypatch.setattr(heatwaves.climatology_store, "load", lambda variable: object())
    monkeypatch.setattr(heatwaves.oisst, "fetch_recent", noaa_down)

    asyncio.run(heatwaves.refresh_cache())

    restored = heatwaves.current_field()
    assert restored.timestamp == saved.timestamp
    assert restored.baseline == (1991, 2020)
    np.testing.assert_array_equal(restored.run_days, saved.run_days)


def test_crw_is_restored_when_noaa_is_down(monkeypatch):
    grid = np.zeros((2, 3))
    saved = crw._CrwCache(
        latitudes=np.array([0.0, 1.0]), longitudes=np.array([10.0, 11.0, 12.0]),
        dhw=grid + 4.5, anomaly=grid + 1.0, hotspot=grid, baa=grid + 2, seaice=grid,
        timestamp=datetime(2026, 10, 18, 12, tzinfo=UTC),
        fetched_at=datetime(2026, 10, 19, 15, tzinfo=UTC), latency_ms=900.0,
    )
    assert crw.save_to_disk(saved) is True
    monkeypatch.setattr(crw, "_cache", None)

    def noaa_down():
        raise RuntimeError("404 from CoastWatch")

    monkeypatch.setattr(crw, "_load", noaa_down)

    asyncio.run(crw.refresh_cache())

    assert crw.is_available()
    assert crw._cache.timestamp == saved.timestamp
    np.testing.assert_array_equal(crw._cache.dhw, saved.dhw)


def test_an_empty_layer_is_retried_but_a_loaded_one_is_left_alone(monkeypatch):
    calls = []

    async def fake_refresh():
        calls.append("crw")

    monkeypatch.setattr(crw, "refresh_cache", fake_refresh)
    monkeypatch.setattr(crw, "_cache", None)
    asyncio.run(crw.refresh_if_empty())
    monkeypatch.setattr(crw, "_cache", object())
    asyncio.run(crw.refresh_if_empty())
    assert calls == ["crw"]

    hw_calls = []

    async def fake_hw_refresh():
        hw_calls.append("heatwaves")

    monkeypatch.setattr(heatwaves, "refresh_cache", fake_hw_refresh)
    monkeypatch.setattr(heatwaves, "_cache", None)
    asyncio.run(heatwaves.refresh_if_empty())
    monkeypatch.setattr(heatwaves, "_cache", _field())
    asyncio.run(heatwaves.refresh_if_empty())
    assert hw_calls == ["heatwaves"]
