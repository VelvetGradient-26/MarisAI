"""services/tides.py (sihtodo.md item 6's get_tide_level tool), over
INCOIS's TEWS tide-gauge feed.

No network: `httpx.AsyncClient` is patched onto a `MockTransport`, the same
convention `test_download_gebco.py` uses. The module's own docstring records
the live browser session (2026-08-27) that found this feed, the year+1900
timestamp quirk, and the TLS workaround, none of which these unit tests
re-verify against the live host — they pin the code's *handling* of that
already-understood shape.
"""

from __future__ import annotations

import httpx
import pytest

from services import tides

# Captured once, before any test patches `tides.httpx.AsyncClient` — see the
# identical note in tests/test_literature.py: that attribute lives on the
# shared `httpx` module, so re-reading it after a first patch would chain
# fakes together instead of reaching each test's own mock transport.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

_STATIONS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<stations>
<station status="Reporting"><latitude>13.1</latitude><longitude>80.3</longitude>
<date>2026-Aug-27 05:26</date><statname>chenn</statname><country>India</country>
<owner>INCOIS</owner><colorClass>GREEN</colorClass><statrealName>Chennai</statrealName></station>
<station status="Not Reporting"><latitude>17.6833</latitude><longitude>83.2833</longitude>
<date>2026-Aug-20 01:00</date><statname>vish</statname><country>India</country>
<owner>INCOIS</owner><colorClass>GREY</colorClass><statrealName>Visakhapatnam</statrealName></station>
</stations>"""


def _encode_time(year: int, month: int, day: int, hour: int, minute: int) -> float:
    """Inverse of `tides._decode_timestamp`: build the wrong-by-1900-years
    raw value the real feed sends, from a real intended date."""
    from datetime import datetime, timezone

    wrong_year_dt = datetime(year - 1900, month, day, hour, minute, tzinfo=timezone.utc)
    return wrong_year_dt.timestamp() * 1000


def _series_json(points: list[tuple[int, int, int, int, int, float]]) -> list[dict]:
    return [{"data": [[_encode_time(*p[:5]), p[5]] for p in points]}]


def _install(monkeypatch: pytest.MonkeyPatch, stations_xml: str, series_by_station: dict[str, list]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "TideStations.xml" in url:
            return httpx.Response(200, text=stations_xml)
        for station, body in series_by_station.items():
            if f"/{station}_1.json" in url:
                return httpx.Response(200, json=body)
        return httpx.Response(200, json=[{"data": []}])

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(tides.httpx, "AsyncClient", patched)
    tides._cache = None  # each test starts with a cold station-list cache


@pytest.mark.asyncio
async def test_decode_timestamp_reproduces_the_encoder_exactly():
    from datetime import datetime, timezone

    raw = _encode_time(2026, 8, 27, 5, 12)
    decoded = tides._decode_timestamp(raw)
    assert decoded == datetime(2026, 8, 27, 5, 12, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_nearest_reporting_station_returns_latest_reading_and_trend(
    monkeypatch: pytest.MonkeyPatch,
):
    series = _series_json(
        [
            (2026, 8, 27, 4, 40, 1.00),
            (2026, 8, 27, 5, 10, 1.20),
            (2026, 8, 27, 5, 12, 1.25),
        ]
    )
    _install(monkeypatch, _STATIONS_XML, {"CHENNAI": series})

    result = await tides.nearest_station(13.08, 80.27, 200)

    assert result["available"] is True
    assert result["station"] == "Chennai"
    assert result["water_level_m"] == 1.25
    assert result["trend"] == "rising"
    assert result["last_reported"] == "2026-08-27T05:12:00+00:00"
    assert result["stale"] is False


@pytest.mark.asyncio
async def test_falling_trend_is_detected(monkeypatch: pytest.MonkeyPatch):
    series = _series_json(
        [
            (2026, 8, 27, 4, 40, 1.50),
            (2026, 8, 27, 5, 10, 1.20),
            (2026, 8, 27, 5, 12, 1.10),
        ]
    )
    _install(monkeypatch, _STATIONS_XML, {"CHENNAI": series})

    result = await tides.nearest_station(13.08, 80.27, 200)

    assert result["trend"] == "falling"


@pytest.mark.asyncio
async def test_a_small_wobble_reads_as_steady_not_rising_or_falling(
    monkeypatch: pytest.MonkeyPatch,
):
    series = _series_json(
        [
            (2026, 8, 27, 4, 40, 1.20),
            (2026, 8, 27, 5, 10, 1.21),
            (2026, 8, 27, 5, 12, 1.22),
        ]
    )
    _install(monkeypatch, _STATIONS_XML, {"CHENNAI": series})

    result = await tides.nearest_station(13.08, 80.27, 200)

    assert result["trend"] == "steady"


@pytest.mark.asyncio
async def test_a_stale_reading_is_flagged_even_though_status_says_reporting(
    monkeypatch: pytest.MonkeyPatch,
):
    series = _series_json([(2026, 8, 27, 1, 0, 0.80)])  # hours old by "now"
    _install(monkeypatch, _STATIONS_XML, {"CHENNAI": series})

    result = await tides.nearest_station(13.08, 80.27, 200)

    assert result["available"] is True
    assert result["stale"] is True
    assert "hours old" in result["note"]


@pytest.mark.asyncio
async def test_nothing_within_radius_is_a_plain_unavailable_answer(
    monkeypatch: pytest.MonkeyPatch,
):
    _install(monkeypatch, _STATIONS_XML, {})

    result = await tides.nearest_station(-10.0, -150.0, 200)

    assert result == {
        "available": False,
        "reason": "No INCOIS tide-gauge station is within 200 km of this point.",
    }


@pytest.mark.asyncio
async def test_a_not_reporting_station_is_reported_rather_than_ignored(
    monkeypatch: pytest.MonkeyPatch,
):
    _install(monkeypatch, _STATIONS_XML, {})

    result = await tides.nearest_station(17.68, 83.28, 50)

    assert result["available"] is False
    assert result["station"] == "Visakhapatnam"
    assert "not currently reporting" in result["reason"]


@pytest.mark.asyncio
async def test_reporting_beats_a_closer_not_reporting_station(monkeypatch: pytest.MonkeyPatch):
    """Both stations are within radius of a point equidistant-ish to both —
    the Reporting one (Chennai) must win even if Visakhapatnam were nearer,
    since a real reading beats a dead gauge."""
    xml = _STATIONS_XML  # Chennai (Reporting) and Visakhapatnam (Not Reporting)
    series = _series_json([(2026, 8, 27, 5, 0, 1.0)])
    _install(monkeypatch, xml, {"CHENNAI": series})

    # A point far from both, but within the generous radius of both.
    result = await tides.nearest_station(15.0, 82.0, 500)

    assert result["available"] is True
    assert result["station"] == "Chennai"


@pytest.mark.asyncio
async def test_an_empty_series_for_a_reporting_station_is_a_feed_gap_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
):
    _install(monkeypatch, _STATIONS_XML, {"CHENNAI": [{"data": []}]})

    result = await tides.nearest_station(13.08, 80.27, 200)

    assert result["available"] is False
    assert "feed gap" in result["reason"]


@pytest.mark.asyncio
async def test_station_list_fetch_failure_raises_tide_error(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(tides.httpx, "AsyncClient", patched)
    tides._cache = None

    with pytest.raises(tides.TideError, match="could not be reached"):
        await tides.nearest_station(13.08, 80.27, 200)


@pytest.mark.asyncio
async def test_malformed_station_xml_raises_tide_error(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<not><valid")

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(tides.httpx, "AsyncClient", patched)
    tides._cache = None

    with pytest.raises(tides.TideError, match="not valid XML"):
        await tides.nearest_station(13.08, 80.27, 200)


@pytest.mark.asyncio
async def test_station_list_is_cached_between_calls(monkeypatch: pytest.MonkeyPatch):
    calls = {"stations": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "TideStations.xml" in str(request.url):
            calls["stations"] += 1
            return httpx.Response(200, text=_STATIONS_XML)
        return httpx.Response(200, json=[{"data": []}])

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(tides.httpx, "AsyncClient", patched)
    tides._cache = None

    await tides.nearest_station(13.08, 80.27, 200)
    await tides.nearest_station(13.08, 80.27, 200)

    assert calls["stations"] == 1
