"""routers/watch.py: thin-router checks — mount the router alone on a bare
FastAPI app, monkeypatch the service call the router itself holds a
reference to, assert on status code and payload. Same shape as
`test_tools_router.py`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import watch as watch_router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(watch_router.router)
    return TestClient(app)


def test_create_endpoint_returns_the_service_payload(monkeypatch, client):
    async def fake_create(client_id, email, label, lat, lon, radius_km):
        return {"status": "pending_confirmation"}

    monkeypatch.setattr(watch_router, "create", fake_create)

    response = client.post(
        "/api/v1/watch",
        json={
            "client_id": "test-client-00000001",
            "email": "watcher@example.org",
            "label": "Near Kochi",
            "latitude": 9.9,
            "longitude": 76.2,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "pending_confirmation"}


def test_create_endpoint_rejects_a_label_with_a_newline(client):
    response = client.post(
        "/api/v1/watch",
        json={
            "client_id": "test-client-00000001",
            "email": "watcher@example.org",
            "label": "Near Kochi\r\nBcc: someone@else.org",
            "latitude": 9.9,
            "longitude": 76.2,
        },
    )

    assert response.status_code == 422


def test_create_endpoint_maps_watch_error_to_502(monkeypatch, client):
    from services.watch_alerts import WatchError

    async def fake_create(*args, **kwargs):
        raise WatchError("Alert watches need a database, which is not configured on this server.")

    monkeypatch.setattr(watch_router, "create", fake_create)

    response = client.post(
        "/api/v1/watch",
        json={
            "client_id": "test-client-00000001",
            "email": "watcher@example.org",
            "label": "Near Kochi",
            "latitude": 9.9,
            "longitude": 76.2,
        },
    )

    assert response.status_code == 502


def test_create_endpoint_rejects_an_out_of_range_latitude(client):
    response = client.post(
        "/api/v1/watch",
        json={
            "client_id": "test-client-00000001",
            "email": "watcher@example.org",
            "label": "Near Kochi",
            "latitude": 190,
            "longitude": 76.2,
        },
    )

    assert response.status_code == 422


def test_confirm_endpoint_returns_confirmed_on_success(monkeypatch, client):
    async def fake_confirm(token):
        return True

    monkeypatch.setattr(watch_router, "confirm", fake_confirm)

    response = client.get("/api/v1/watch/confirm", params={"token": "sometoken"})

    assert response.status_code == 200
    assert response.json() == {"status": "confirmed"}


def test_confirm_endpoint_returns_400_on_an_invalid_token(monkeypatch, client):
    async def fake_confirm(token):
        return False

    monkeypatch.setattr(watch_router, "confirm", fake_confirm)

    response = client.get("/api/v1/watch/confirm", params={"token": "bad"})

    assert response.status_code == 400


def test_unsubscribe_endpoint_returns_unsubscribed_on_success(monkeypatch, client):
    async def fake_unsubscribe(token):
        return True

    monkeypatch.setattr(watch_router, "unsubscribe", fake_unsubscribe)

    response = client.get("/api/v1/watch/unsubscribe", params={"token": "sometoken"})

    assert response.status_code == 200
    assert response.json() == {"status": "unsubscribed"}


def test_unsubscribe_endpoint_returns_400_on_an_invalid_token(monkeypatch, client):
    async def fake_unsubscribe(token):
        return False

    monkeypatch.setattr(watch_router, "unsubscribe", fake_unsubscribe)

    response = client.get("/api/v1/watch/unsubscribe", params={"token": "bad"})

    assert response.status_code == 400


def test_list_endpoint_returns_the_service_payload(monkeypatch, client):
    async def fake_list(client_id):
        return [{"id": "x", "label": "Near Kochi", "confirmed": True}]

    monkeypatch.setattr(watch_router, "list_for_client", fake_list)

    response = client.get("/api/v1/watch", params={"client_id": "test-client-00000001"})

    assert response.status_code == 200
    assert response.json() == {"watches": [{"id": "x", "label": "Near Kochi", "confirmed": True}]}


def test_create_endpoint_is_rate_limited(monkeypatch, client):
    async def fake_create(client_id, email, label, lat, lon, radius_km):
        return {"status": "pending_confirmation"}

    monkeypatch.setattr(watch_router, "create", fake_create)
    monkeypatch.setattr(watch_router, "_CREATE_LIMITER", watch_router.RateLimiter(limit=1, window_seconds=3600))

    payload = {
        "client_id": "test-client-00000001",
        "email": "watcher@example.org",
        "label": "Near Kochi",
        "latitude": 9.9,
        "longitude": 76.2,
    }
    first = client.post("/api/v1/watch", json=payload)
    second = client.post("/api/v1/watch", json=payload)

    assert first.status_code == 200
    assert second.status_code == 429
