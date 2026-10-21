"""Cache headers on map tiles (routers/tiles.py).

nginx keeps a shared tile cache in front of the backend and honours these
headers, so a rendered tile is served to every visitor without re-rendering,
while a placeholder drawn before the data has loaded is never cached.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import tiles as tiles_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(tiles_router.router)
    return TestClient(app)


def test_a_rendered_sst_tile_is_cacheable(monkeypatch):
    monkeypatch.setattr(tiles_router.copernicus_sst, "render_tile_for_response", lambda z, x, y: (b"png", True))
    response = _client().get("/api/tiles/sst/3/5/3.png")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"


def test_a_placeholder_sst_tile_is_never_cached(monkeypatch):
    monkeypatch.setattr(tiles_router.copernicus_sst, "render_tile_for_response", lambda z, x, y: (b"png", False))
    response = _client().get("/api/tiles/sst/3/5/3.png")
    assert response.headers["cache-control"] == "no-store"


def test_a_gfw_tile_is_cacheable(monkeypatch):
    async def fake_fetch(dataset, z, x, y):
        return b"png"

    monkeypatch.setattr(tiles_router, "fetch_tile", fake_fetch)
    response = _client().get("/api/tiles/gfw/fishing-effort/3/5/3.png")
    assert response.headers["cache-control"] == "public, max-age=3600"
