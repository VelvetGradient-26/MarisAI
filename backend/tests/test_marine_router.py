"""routers/marine.py: thin-router checks for `GET /api/ocean/drift/trajectory`.

Same shape as `test_tools_router.py`: mount the router alone on a bare
FastAPI app, monkeypatch the service call the router holds a reference to,
assert on status code and payload. No network touched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import marine
from services.drift_trajectory import DriftTrajectoryError


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(marine.router)
    return TestClient(app)


def test_trajectory_endpoint_returns_the_service_payload(monkeypatch, client):
    async def fake_plan_trajectory(lat, lon, alpha, preset_used, **kwargs):
        return {"start": {"lat": lat, "lon": lon}, "leeway_alpha": alpha, "preset_used": preset_used}

    monkeypatch.setattr(marine.drift_trajectory, "plan_trajectory", fake_plan_trajectory)

    response = client.get(
        "/api/ocean/drift/trajectory", params={"lat": 10.0, "lon": 75.0, "preset": "life_raft"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["start"] == {"lat": 10.0, "lon": 75.0}
    assert body["preset_used"] is True


def test_bad_preset_is_422_not_502(client):
    response = client.get(
        "/api/ocean/drift/trajectory", params={"lat": 10.0, "lon": 75.0, "preset": "not-a-real-preset"}
    )
    assert response.status_code == 422


def test_start_time_too_far_in_the_past_is_422(client):
    stale = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    response = client.get(
        "/api/ocean/drift/trajectory", params={"lat": 10.0, "lon": 75.0, "start_time": stale}
    )
    assert response.status_code == 422


def test_a_future_start_time_is_422(client):
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    response = client.get(
        "/api/ocean/drift/trajectory", params={"lat": 10.0, "lon": 75.0, "start_time": future}
    )
    assert response.status_code == 422


def test_service_failure_is_502(monkeypatch, client):
    async def fake_plan_trajectory(*_args, **_kwargs):
        raise DriftTrajectoryError("nothing available")

    monkeypatch.setattr(marine.drift_trajectory, "plan_trajectory", fake_plan_trajectory)

    response = client.get("/api/ocean/drift/trajectory", params={"lat": 10.0, "lon": 75.0})
    assert response.status_code == 502


def test_horizon_and_member_bounds_are_enforced(client):
    too_long = client.get(
        "/api/ocean/drift/trajectory", params={"lat": 10.0, "lon": 75.0, "horizon_hours": 200}
    )
    assert too_long.status_code == 422

    too_many_members = client.get(
        "/api/ocean/drift/trajectory", params={"lat": 10.0, "lon": 75.0, "members": 1000}
    )
    assert too_many_members.status_code == 422
