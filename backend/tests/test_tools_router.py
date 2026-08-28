"""routers/tools.py: thin-router checks over the five previously chat-only
services (pfz, geofencing, routing, cyclones, severe_weather), plus the
later sihtodo.md item 4 additions (web_search, fetch_webpage, literature).

Same shape as `test_dashboard.py`'s router tests: mount the router alone on a
bare FastAPI app, monkeypatch the service call the router itself holds a
reference to (not the origin module — the router imported the function by
name, so that is the reference the endpoint actually calls), and assert on
status code and payload. No network is touched by any test here.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import tools as tools_router
from services.cyclones import CycloneError
from services.routing import RoutingError
from services.severe_weather import SevereWeatherError


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(tools_router.router)
    return TestClient(app)


# --------------------------------------------------------------------------
# PFZ — never raises, so this is a pure passthrough check.
# --------------------------------------------------------------------------


def test_pfz_endpoint_returns_the_service_payload(monkeypatch, client):
    monkeypatch.setattr(
        tools_router.pfz,
        "find_zones",
        lambda lat, lon, radius_km: {"available": True, "lat": lat, "lon": lon, "radius_km": radius_km},
    )

    response = client.get("/api/ocean/pfz", params={"lat": 9.9, "lon": 76.2, "radius_km": 50})

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"available": True, "lat": 9.9, "lon": 76.2, "radius_km": 50}


def test_pfz_endpoint_rejects_an_out_of_range_radius(client):
    response = client.get("/api/ocean/pfz", params={"lat": 9.9, "lon": 76.2, "radius_km": 5000})
    assert response.status_code == 422


def test_pfz_endpoint_rejects_an_out_of_range_latitude(client):
    response = client.get("/api/ocean/pfz", params={"lat": 190, "lon": 76.2})
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Geofence — never raises either.
# --------------------------------------------------------------------------


def test_geofence_endpoint_returns_the_service_payload(monkeypatch, client):
    monkeypatch.setattr(
        tools_router.geofencing,
        "check",
        lambda lat, lon: {"india_eez": {"inside": True, "zone": "mainland"}},
    )

    response = client.get("/api/ocean/geofence", params={"lat": 13.1, "lon": 81.2})

    assert response.status_code == 200
    assert response.json()["india_eez"]["zone"] == "mainland"


# --------------------------------------------------------------------------
# Route — live fetch on every call, so failures map to 502.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_endpoint_returns_the_plan_on_success(monkeypatch, client):
    async def fake_plan_route(start_lat, start_lon, end_lat, end_lon):
        return {"distance_km": 12.3, "waypoints": [{"latitude": start_lat, "longitude": start_lon}]}

    monkeypatch.setattr(tools_router, "plan_route", fake_plan_route)

    response = client.get(
        "/api/ocean/route",
        params={"start_lat": 10.0, "start_lon": 75.0, "end_lat": 10.3, "end_lon": 75.3},
    )

    assert response.status_code == 200
    assert response.json()["distance_km"] == 12.3


def test_route_endpoint_maps_routing_error_to_502(monkeypatch, client):
    async def fake_plan_route(*args, **kwargs):
        raise RoutingError("no navigable water was found")

    monkeypatch.setattr(tools_router, "plan_route", fake_plan_route)

    response = client.get(
        "/api/ocean/route",
        params={"start_lat": 10.0, "start_lon": 75.0, "end_lat": 10.3, "end_lon": 75.3},
    )

    assert response.status_code == 502
    assert "no navigable water" in response.json()["detail"]


# --------------------------------------------------------------------------
# Cyclones — live GDACS fetch on every call.
# --------------------------------------------------------------------------


def test_cyclones_endpoint_returns_the_active_list(monkeypatch, client):
    async def fake_get_active_cyclones():
        return {"cyclones": [], "count": 0}

    monkeypatch.setattr(tools_router, "get_active_cyclones", fake_get_active_cyclones)

    response = client.get("/api/ocean/cyclones")

    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_cyclones_endpoint_maps_cyclone_error_to_502(monkeypatch, client):
    async def fake_get_active_cyclones():
        raise CycloneError("GDACS could not be reached")

    monkeypatch.setattr(tools_router, "get_active_cyclones", fake_get_active_cyclones)

    response = client.get("/api/ocean/cyclones")

    assert response.status_code == 502


def test_cyclones_point_endpoint_returns_the_nearest_storm(monkeypatch, client):
    async def fake_check_point(lat, lon, radius_km):
        return {"active_cyclones_worldwide": 1, "nearest": {"name": "Test"}, "within_watch_radius": True}

    monkeypatch.setattr(tools_router, "cyclone_check_point", fake_check_point)

    response = client.get("/api/ocean/cyclones/point", params={"lat": 13.5, "lon": 80.3})

    assert response.status_code == 200
    assert response.json()["nearest"]["name"] == "Test"


def test_cyclones_point_endpoint_rejects_an_out_of_range_radius(client):
    response = client.get(
        "/api/ocean/cyclones/point", params={"lat": 13.5, "lon": 80.3, "radius_km": 1}
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Severe weather — live IMD CAP feed fetch on every call.
# --------------------------------------------------------------------------


def test_severe_weather_endpoint_returns_active_alerts(monkeypatch, client):
    async def fake_get_active_alerts():
        return {"alerts": [], "count": 0}

    monkeypatch.setattr(tools_router, "get_severe_weather_alerts", fake_get_active_alerts)

    response = client.get("/api/ocean/severe-weather")

    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_severe_weather_endpoint_maps_error_to_502(monkeypatch, client):
    async def fake_get_active_alerts():
        raise SevereWeatherError("the IMD alert feed could not be reached")

    monkeypatch.setattr(tools_router, "get_severe_weather_alerts", fake_get_active_alerts)

    response = client.get("/api/ocean/severe-weather")

    assert response.status_code == 502


def test_severe_weather_point_endpoint_returns_covering_alerts(monkeypatch, client):
    async def fake_check_point(lat, lon):
        return {"alerts": [{"event": "Thunderstorm"}], "count": 1, "active_nationwide": 3}

    monkeypatch.setattr(tools_router, "severe_weather_check_point", fake_check_point)

    response = client.get("/api/ocean/severe-weather/point", params={"lat": 13.1, "lon": 81.2})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["active_nationwide"] == 3


# --------------------------------------------------------------------------
# Risk — never raises (see services/marine_risk.py), so a pure passthrough
# check like PFZ/geofence rather than an error-mapping one.
# --------------------------------------------------------------------------


def test_risk_endpoint_returns_the_service_payload(monkeypatch, client):
    async def fake_assess(lat, lon):
        return {"latitude": lat, "longitude": lon, "risk_level": "low", "reasons": []}

    monkeypatch.setattr(tools_router, "assess_marine_risk", fake_assess)

    response = client.get("/api/ocean/risk", params={"lat": 9.9, "lon": 76.2})

    assert response.status_code == 200
    assert response.json()["risk_level"] == "low"


def test_risk_endpoint_rejects_an_out_of_range_latitude(client):
    response = client.get("/api/ocean/risk", params={"lat": 190, "lon": 76.2})
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Search / fetch-page / literature (sihtodo.md item 4) — all three depend on
# a live upstream call on every request, so failures map to 502, same as
# routing/cyclones/severe-weather above.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_endpoint_returns_the_service_payload(monkeypatch, client):
    async def fake_search(query, max_results):
        return {"query": query, "results": [], "result_count": 0, "source": "Tavily web search"}

    monkeypatch.setattr(tools_router, "run_web_search", fake_search)

    response = client.get("/api/ocean/search", params={"q": "arabian sea warming"})

    assert response.status_code == 200
    assert response.json()["query"] == "arabian sea warming"


def test_search_endpoint_maps_web_search_error_to_502(monkeypatch, client):
    from services.web_search import WebSearchError

    async def fake_search(*args, **kwargs):
        raise WebSearchError("Web search is not configured (set TAVILY_API_KEY in backend/.env).")

    monkeypatch.setattr(tools_router, "run_web_search", fake_search)

    response = client.get("/api/ocean/search", params={"q": "x"})

    assert response.status_code == 502
    assert "TAVILY_API_KEY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_fetch_page_endpoint_returns_the_service_payload(monkeypatch, client):
    async def fake_fetch(url):
        return {"url": url, "title": "A page", "text": "hello", "truncated": False, "source": url}

    monkeypatch.setattr(tools_router, "fetch_webpage_content", fake_fetch)

    response = client.get("/api/ocean/fetch-page", params={"url": "https://example.org/"})

    assert response.status_code == 200
    assert response.json()["title"] == "A page"


def test_fetch_page_endpoint_maps_a_disallowed_url_to_422(monkeypatch, client):
    from services.webpage import WebpageError

    async def fake_fetch(url):
        raise WebpageError(f"Host 'internal' resolves to a non-public address (10.0.0.1); refusing to fetch.")

    monkeypatch.setattr(tools_router, "fetch_webpage_content", fake_fetch)

    response = client.get("/api/ocean/fetch-page", params={"url": "http://internal/"})

    assert response.status_code == 422


def test_fetch_page_endpoint_maps_a_live_fetch_failure_to_502(monkeypatch, client):
    from services.webpage import WebpageError

    async def fake_fetch(url):
        raise WebpageError("Fetching https://example.org/ failed with status 500.")

    monkeypatch.setattr(tools_router, "fetch_webpage_content", fake_fetch)

    response = client.get("/api/ocean/fetch-page", params={"url": "https://example.org/"})

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_literature_endpoint_returns_the_service_payload(monkeypatch, client):
    async def fake_search(query, max_results):
        return {"query": query, "results": [], "result_count": 0, "source": "CrossRef (api.crossref.org)"}

    monkeypatch.setattr(tools_router, "run_literature_search", fake_search)

    response = client.get("/api/ocean/literature", params={"q": "oil sardine habitat"})

    assert response.status_code == 200
    assert response.json()["source"] == "CrossRef (api.crossref.org)"


def test_literature_endpoint_maps_literature_error_to_502(monkeypatch, client):
    from services.literature import LiteratureError

    async def fake_search(*args, **kwargs):
        raise LiteratureError("CrossRef search failed (503): Service Unavailable")

    monkeypatch.setattr(tools_router, "run_literature_search", fake_search)

    response = client.get("/api/ocean/literature", params={"q": "x"})

    assert response.status_code == 502


# --------------------------------------------------------------------------
# Tide (sihtodo.md item 6) — a live feed fetch on every call, so failures
# map to 502; "no station nearby"/"not reporting" are ordinary 200 answers.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tide_endpoint_returns_the_service_payload(monkeypatch, client):
    async def fake_nearest(lat, lon, radius_km):
        return {"available": True, "station": "Chennai", "water_level_m": 1.2}

    monkeypatch.setattr(tools_router, "get_nearest_tide_station", fake_nearest)

    response = client.get("/api/ocean/tide", params={"lat": 13.08, "lon": 80.27})

    assert response.status_code == 200
    assert response.json()["station"] == "Chennai"


@pytest.mark.asyncio
async def test_tide_endpoint_passes_through_an_unavailable_answer(monkeypatch, client):
    async def fake_nearest(lat, lon, radius_km):
        return {"available": False, "reason": "No INCOIS tide-gauge station is within 200 km."}

    monkeypatch.setattr(tools_router, "get_nearest_tide_station", fake_nearest)

    response = client.get("/api/ocean/tide", params={"lat": -10, "lon": -150})

    assert response.status_code == 200
    assert response.json()["available"] is False


def test_tide_endpoint_maps_tide_error_to_502(monkeypatch, client):
    from services.tides import TideError

    async def fake_nearest(*args, **kwargs):
        raise TideError("The INCOIS tide-station list could not be reached: timeout")

    monkeypatch.setattr(tools_router, "get_nearest_tide_station", fake_nearest)

    response = client.get("/api/ocean/tide", params={"lat": 13.08, "lon": 80.27})

    assert response.status_code == 502


def test_tide_endpoint_rejects_an_out_of_range_radius(client):
    response = client.get("/api/ocean/tide", params={"lat": 13.08, "lon": 80.27, "radius_km": 5000})
    assert response.status_code == 422
