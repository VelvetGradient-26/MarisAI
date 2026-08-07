"""Progress reporting wired through the real `run_download`.

`test_download_progress.py` covers the reporter's arithmetic in isolation. What
matters here is the wiring, and specifically the property the whole feature
rests on: **each provider must move the bar as it lands, not all of them at the
end.** Providers are gathered concurrently and finish at very different times
(ERDDAP in a couple of seconds, a wide Copernicus window in tens of seconds), so
reporting after the `gather` would tick 0 → 100 in one step at exactly the
moment the information stopped being worth anything.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import date

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from services.download import catalog, progress
from services.download import service as download_service
from services.download.models import (
    DownloadRequest,
    OutputFormat,
    PointArea,
    Resolution,
)
from services.download.progress import ProgressReporter

# Two variables served by two different providers, so a request resolves to a
# genuinely concurrent fetch rather than a single one.
VARIABLE_A = "sea_surface_temperature"
VARIABLE_B = "ocean_depth"


@pytest.fixture(autouse=True)
def _clean_registry():
    progress.clear()
    yield
    progress.clear()


def _dataset(field: str, time_varying: bool) -> xr.Dataset:
    """A tiny gridded series in the shape a real provider returns.

    latitude/longitude are real dimensions rather than scalars because
    `run_download` narrows a point request with `.sel(..., method="nearest")`,
    which needs an index to search.
    """
    lats = np.array([14.9, 15.0, 15.1])
    lons = np.array([64.9, 65.0, 65.1])

    if not time_varying:
        values = np.full((lats.size, lons.size), -3200.0)
        return xr.Dataset(
            {field: (("latitude", "longitude"), values)},
            coords={"latitude": lats, "longitude": lons},
        )

    times = pd.date_range("2024-01-01", periods=6, freq="D")
    values = np.broadcast_to(
        np.linspace(27.0, 28.0, times.size)[:, None, None],
        (times.size, lats.size, lons.size),
    ).copy()
    return xr.Dataset(
        {field: (("time", "latitude", "longitude"), values)},
        coords={"time": times, "latitude": lats, "longitude": lons},
    )


def _staggered_catalog(monkeypatch, order: list[str], gate: dict[str, asyncio.Event]):
    """Replace each provider's `fetch` with one that waits on its own gate.

    Gating rather than sleeping: the test then controls completion *order*
    deterministically instead of racing the scheduler, which is the difference
    between this test proving something and it flaking in CI.
    """
    real_get = catalog.get

    def fake_get(key: str):
        spec = real_get(key)

        async def fetch(*, fields, **_kwargs):
            await gate[spec.key].wait()
            field = fields[0]
            return _dataset(field, spec.time_varying)

        return dataclasses.replace(spec, fetch=fetch)

    monkeypatch.setattr(download_service.catalog, "get", fake_get)
    return order


@pytest.mark.asyncio
async def test_each_provider_moves_the_bar_as_it_lands(monkeypatch):
    request = DownloadRequest(
        area=PointArea(type="point", lat=15.0, lon=65.0),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 6),
        resolution=Resolution.daily,
        variables=[VARIABLE_A, VARIABLE_B],
        format=OutputFormat.csv,
        request_id="req",
    )

    from services.download.registry import resolve_variables

    provider_keys = sorted(
        {info.provider for info in resolve_variables(request.variables).values() if info.provider}
    )
    assert len(provider_keys) == 2, "this test needs two distinct providers to be meaningful"

    gate = {key: asyncio.Event() for key in provider_keys}
    _staggered_catalog(monkeypatch, provider_keys, gate)

    reporter = ProgressReporter("req")
    task = asyncio.create_task(download_service.run_download(request, reporter))

    # Nothing has landed: the bar must not have entered the fetch's share yet.
    await asyncio.sleep(0)
    first = progress.snapshot("req")
    assert first is not None
    assert first["providers_done"] == 0

    # Release one provider only.
    gate[provider_keys[0]].set()
    for _ in range(50):
        await asyncio.sleep(0)
        if progress.snapshot("req")["providers_done"] == 1:
            break
    midway = progress.snapshot("req")

    assert midway["providers_done"] == 1, (
        "one provider finished but the bar did not move — progress is being "
        "reported after the gather rather than per provider"
    )
    assert 0.0 < midway["fraction"] < 1.0

    gate[provider_keys[1]].set()
    result = await task

    assert result.filename.endswith(".csv")
    assert result.content


@pytest.mark.asyncio
async def test_a_download_without_a_request_id_still_runs(monkeypatch):
    """Progress is an observer. A request that carries no id must behave
    identically and leave nothing behind."""
    request = DownloadRequest(
        area=PointArea(type="point", lat=15.0, lon=65.0),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 6),
        resolution=Resolution.daily,
        variables=[VARIABLE_A],
        format=OutputFormat.csv,
    )
    assert request.request_id is None

    from services.download.registry import resolve_variables

    provider_keys = sorted(
        {info.provider for info in resolve_variables(request.variables).values() if info.provider}
    )
    gate = {key: asyncio.Event() for key in provider_keys}
    for event in gate.values():
        event.set()
    _staggered_catalog(monkeypatch, provider_keys, gate)

    result = await download_service.run_download(request)

    assert result.content
    assert progress.active_count() == 0
