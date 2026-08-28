"""The forecast cache pre-warmer.

What matters here is not that it warms — that is one `predict` call — but that
it *cannot take the server down*. It runs on the scheduler at boot and every
four hours, sweeping every trained variable against live upstream providers,
which is exactly the shape of job that turns one flaky provider into a failed
startup. Every test below is a "keeps going" property.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from forecasting import ForecastingError
from services import forecast_warm


@dataclass
class _Entry:
    """Enough of a `VariableEntry` for the sweep to make its decisions."""

    key: str
    trained_horizons: list[int]


@pytest.fixture(autouse=True)
def _one_point(monkeypatch):
    monkeypatch.setattr(forecast_warm, "WARM_POINTS", ((15.0, 65.0),))
    monkeypatch.setattr(forecast_warm, "_last_result", None)


def _catalog(entries):
    return lambda *args, **kwargs: entries


def _records(calls):
    async def _predict(key, lat, lon, horizon, **kwargs):
        calls.append((key, lat, lon, horizon))
        return object()

    return _predict


@pytest.mark.asyncio
async def test_untrained_variables_are_skipped_not_attempted(monkeypatch):
    """An untrained variable has no model to load, so asking for one would be
    a guaranteed failure logged as though something were wrong."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        forecast_warm,
        "catalog",
        _catalog([_Entry("trained", [1, 7]), _Entry("untrained", [])]),
    )
    monkeypatch.setattr(forecast_warm, "predict", _records(calls))

    result = await forecast_warm.refresh_cache()

    assert [call[0] for call in calls] == ["trained"]
    assert result.warmed == 1
    assert result.skipped == 1
    assert result.failed == 0


@pytest.mark.asyncio
async def test_it_warms_the_horizon_the_hero_asks_for(monkeypatch):
    """`MetricHero` requests 7 days when trained and the first trained horizon
    otherwise. Warming a horizon the page never requests would fill the cache
    and leave the page just as slow."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        forecast_warm,
        "catalog",
        _catalog([_Entry("has_seven", [1, 7, 30]), _Entry("no_seven", [3, 30])]),
    )
    monkeypatch.setattr(forecast_warm, "predict", _records(calls))

    await forecast_warm.refresh_cache()

    assert [(call[0], call[3]) for call in calls] == [("has_seven", 7), ("no_seven", 3)]


@pytest.mark.asyncio
async def test_one_failing_variable_does_not_abandon_the_rest(monkeypatch):
    """The failure this guards against is a sweep that dies on the first bad
    provider and silently leaves thirty variables cold."""
    calls: list[tuple] = []

    async def _predict(key, lat, lon, horizon, **kwargs):
        if key == "broken":
            raise ForecastingError("provider unavailable")
        calls.append((key, horizon))
        return object()

    monkeypatch.setattr(
        forecast_warm,
        "catalog",
        _catalog([_Entry("a", [7]), _Entry("broken", [7]), _Entry("b", [7])]),
    )
    monkeypatch.setattr(forecast_warm, "predict", _predict)

    result = await forecast_warm.refresh_cache()

    assert [call[0] for call in calls] == ["a", "b"]
    assert result.warmed == 2
    assert result.failed == 1


@pytest.mark.asyncio
async def test_an_unexpected_exception_is_contained(monkeypatch):
    """Not every upstream failure arrives as a `ForecastingError` — an httpx
    or zarr error can surface raw, and on the scheduler that would be an
    unhandled task exception rather than a slow page."""
    monkeypatch.setattr(forecast_warm, "catalog", _catalog([_Entry("a", [7])]))

    async def _boom(*args, **kwargs):
        raise ValueError("something upstream exploded")

    monkeypatch.setattr(forecast_warm, "predict", _boom)

    result = await forecast_warm.refresh_cache()

    assert result.failed == 1
    assert result.warmed == 0


@pytest.mark.asyncio
async def test_a_broken_catalog_does_not_raise(monkeypatch):
    """The catalog reads the model directory. A deploy with no models at all
    is a real state (the artifacts are not in git) and must not fail boot."""

    def _explode(*args, **kwargs):
        raise RuntimeError("no model directory")

    monkeypatch.setattr(forecast_warm, "catalog", _explode)

    result = await forecast_warm.refresh_cache()

    assert result.warmed == 0
    assert result.failed == 0


@pytest.mark.asyncio
async def test_overlapping_sweeps_do_not_double_fetch(monkeypatch):
    """The boot-time call and the first interval tick can overlap while a slow
    first sweep is still running. Two concurrent sweeps would issue every
    upstream fetch twice, against the providers this exists to go easy on."""
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def _predict(key, lat, lon, horizon, **kwargs):
        calls.append(key)
        started.set()
        await release.wait()
        return object()

    monkeypatch.setattr(forecast_warm, "catalog", _catalog([_Entry("a", [7])]))
    monkeypatch.setattr(forecast_warm, "predict", _predict)

    first = asyncio.create_task(forecast_warm.refresh_cache())
    await started.wait()

    assert forecast_warm.is_warming() is True
    # The second tick arrives mid-sweep and must decline rather than queue.
    await forecast_warm.refresh_cache()

    release.set()
    await first

    assert calls == ["a"]
    assert forecast_warm.is_warming() is False
