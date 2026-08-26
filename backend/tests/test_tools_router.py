"""routers/tools.py: thin-router checks over the five previously chat-only
services (pfz, geofencing, routing, cyclones, severe_weather).

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
