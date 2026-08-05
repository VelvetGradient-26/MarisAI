"""Tests for the GEBCO bathymetry provider.

No network. The fetch is exercised through a stub transport, so a failure
here means a code defect rather than an ERDDAP outage.

Both tests below encode a bug that actually shipped. The provider pointed at
NOAA CoastWatch's `GEBCO_2020`, which the server retired: it answers 404 for
that id while staying up, so every bathymetry download failed and every
forecast paid ~8s of doomed retries before degrading without `ocean_depth`.
Moving to Ifremer's `gebco2021` fixed the id and exposed the second defect —
Ifremer's fronting Tomcat rejects an unencoded `[` in a query string with a
400 before ERDDAP sees it, which NOAA's server had tolerated.
"""

from __future__ import annotations

import httpx
import numpy as np
import pytest

from services.download.providers import gebco

# One header row, one units row, then data — the griddap CSV shape.
_CSV = """latitude,longitude,elevation
degrees_north,degrees_east,m
10.0,87.0,-3477
10.0,87.2,-3499
10.2,87.0,25
10.2,87.2,-3429
"""


class _Recorder:
    """Captures the request URL and replays a canned griddap response."""

    def __init__(self) -> None:
        self.url: httpx.URL | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.url = request.url
        return httpx.Response(200, text=_CSV)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(rec.handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(gebco.httpx, "AsyncClient", patched)
    return rec


@pytest.mark.asyncio
async def test_subscript_brackets_are_percent_encoded(recorder: _Recorder) -> None:
    """A bare `[` in the query is a 400 from Ifremer's Tomcat, not a 200.

    Asserted on the raw URL rather than the parsed query, because the whole
    failure was about what went out on the wire.
    """
    await gebco.fetch(west=85.0, south=8.0, east=89.0, north=12.0)

    assert recorder.url is not None
    raw = str(recorder.url)
    assert "[" not in raw and "]" not in raw
    assert "%5B" in raw and "%5D" in raw

    # The selector must still be a well-formed griddap subscript: latitude
    # is subscripted before longitude, and each carries the same stride.
    stride = gebco.choose_stride(85.0, 8.0, 89.0, 12.0)
    assert f"elevation%5B(8.0):{stride}:(12.0)%5D%5B(85.0):{stride}:(89.0)%5D" in raw


@pytest.mark.asyncio
async def test_the_retired_dataset_id_is_not_requested(recorder: _Recorder) -> None:
    """`GEBCO_2020` is gone; requesting it is a permanent 404."""
    await gebco.fetch(west=85.0, south=8.0, east=89.0, north=12.0)

    assert recorder.url is not None
    assert "GEBCO_2020" not in str(recorder.url)
    assert "gebco2021" in str(recorder.url)


@pytest.mark.asyncio
async def test_land_becomes_nan_rather_than_a_negative_depth(recorder: _Recorder) -> None:
    """Positive elevation is land, where depth is undefined — never -25 m."""
    result = await gebco.fetch(west=87.0, south=10.0, east=87.2, north=10.2)
    depth = result["ocean_depth"]

    assert float(depth.sel(latitude=10.0, longitude=87.0)) == pytest.approx(3477.0)
    assert bool(np.isnan(depth.sel(latitude=10.2, longitude=87.0)))
    assert float(depth.min()) > 0.0
