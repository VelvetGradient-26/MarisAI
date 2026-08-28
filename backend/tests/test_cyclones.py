"""GDACS-backed active-cyclone tracking.

No network is touched: `cyclones._get` is monkeypatched directly, the same
convention `test_edna.py` uses for OBIS.
"""

from __future__ import annotations

import pytest

from services import cyclones


def _feature(
    eventtype: str = "TC",
    iscurrent: str = "true",
    eventname: str = "MICHAUNG-23",
    lat: float = 13.5,
    lon: float = 80.3,
    max_wind_kmh: float = 111.1,
    category: str = "Tropical Storm (maximum wind speed of 111 km/h)",
    country: str = "India",
) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "eventtype": eventtype,
            "eventname": eventname,
            "iscurrent": iscurrent,
            "alertlevel": "Orange",
            "severitydata": {"severity": max_wind_kmh, "severitytext": category},
            "affectedcountries": [{"countryname": country}],
            "fromdate": "2023-12-03T00:00:00",
            "todate": "2023-12-04T18:00:00",
            "datemodified": "2023-12-05T00:00:00",
            "source": "JTWC",
            "url": {"report": "https://www.gdacs.org/report.aspx?eventid=1"},
        },
    }


def _install(monkeypatch, features: list[dict]):
    cyclones._cache.clear()

    async def fake_get(client, params):
        return {"type": "FeatureCollection", "features": features}

    monkeypatch.setattr(cyclones, "_get", fake_get)


@pytest.mark.asyncio
async def test_only_current_tropical_cyclones_are_counted(monkeypatch):
    """GDACS's `eventtypes` query param does not reliably filter server-side
    (measured 2026-08-24) — every caller must filter client-side instead."""
    _install(
        monkeypatch,
        [
            _feature(),
            _feature(eventtype="FL"),  # a flood, mixed in despite the TC filter
            _feature(iscurrent="false", eventname="OLDSTORM-20"),  # no longer active
        ],
    )

    payload = await cyclones.get_active_cyclones()

    assert payload["count"] == 1
    assert payload["cyclones"][0]["name"] == "Michaung"


@pytest.mark.asyncio
async def test_the_storm_name_drops_its_year_suffix(monkeypatch):
    _install(monkeypatch, [_feature(eventname="BIPARJOY-23")])
    payload = await cyclones.get_active_cyclones()
    assert payload["cyclones"][0]["name"] == "Biparjoy"


@pytest.mark.asyncio
async def test_check_point_ranks_by_distance(monkeypatch):
    _install(
        monkeypatch,
        [
            _feature(eventname="FAR-24", lat=0.0, lon=0.0),
            _feature(eventname="NEAR-24", lat=13.6, lon=80.4),
        ],
    )

    result = await cyclones.check_point(13.5, 80.3, radius_km=500.0)

    assert result["active_cyclones_worldwide"] == 2
    assert result["nearest"]["name"] == "Near"
    assert result["within_watch_radius"] is True


@pytest.mark.asyncio
async def test_a_distant_storm_is_not_within_the_watch_radius(monkeypatch):
    _install(monkeypatch, [_feature(eventname="FAR-24", lat=0.0, lon=0.0)])

    result = await cyclones.check_point(13.5, 80.3, radius_km=500.0)

    assert result["nearest"]["name"] == "Far"
    assert result["within_watch_radius"] is False


@pytest.mark.asyncio
async def test_no_active_cyclones_is_a_real_answer_not_an_error(monkeypatch):
    _install(monkeypatch, [])

    result = await cyclones.check_point(13.5, 80.3)

    assert result["active_cyclones_worldwide"] == 0
    assert result["nearest"] is None
    assert result["within_watch_radius"] is False


@pytest.mark.asyncio
async def test_a_gdacs_failure_raises_cyclone_error(monkeypatch):
    import httpx

    cyclones._cache.clear()

    async def fake_get(client, params):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(cyclones, "_get", fake_get)

    with pytest.raises(cyclones.CycloneError):
        await cyclones.get_active_cyclones()


@pytest.mark.asyncio
async def test_the_active_list_is_cached(monkeypatch):
    calls = 0

    cyclones._cache.clear()

    async def fake_get(client, params):
        nonlocal calls
        calls += 1
        return {"type": "FeatureCollection", "features": [_feature()]}

    monkeypatch.setattr(cyclones, "_get", fake_get)

    await cyclones.get_active_cyclones()
    await cyclones.get_active_cyclones()

    assert calls == 1
