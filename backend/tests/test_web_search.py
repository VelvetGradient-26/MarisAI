"""services/web_search.py (sihtodo.md item 4's web_search tool), via Tavily.

No network: `httpx.AsyncClient` is patched onto a `MockTransport`, the same
convention `test_download_gebco.py` uses. `TAVILY_API_KEY` is set/cleared per
test via monkeypatch rather than relying on `backend/.env`.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from services import web_search

# Captured once, before any test patches `web_search.httpx.AsyncClient` — see
# the identical note in tests/test_literature.py: that attribute lives on the
# shared `httpx` module, so re-reading it after a first patch would chain
# fakes together instead of reaching each test's own mock transport.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


class _Recorder:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.request: httpx.Request | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.request = request
        return self.response


def _install(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> _Recorder:
    rec = _Recorder(response)

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(rec.handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(web_search.httpx, "AsyncClient", patched)
    return rec


@pytest.mark.asyncio
async def test_raises_when_not_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TAVILY_API_KEY", "")
    with pytest.raises(web_search.WebSearchError, match="not configured"):
        await web_search.search("arabian sea warming")


@pytest.mark.asyncio
async def test_a_successful_search_maps_every_field(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TAVILY_API_KEY", "test-key")
    body = {
        "query": "arabian sea warming",
        "results": [
            {
                "title": "Arabian Sea marine heatwave",
                "url": "https://example.org/article",
                "content": "The Arabian Sea has seen unusually warm water this week.",
                "published_date": "2026-08-20",
                "score": 0.9,
            }
        ],
    }
    rec = _install(monkeypatch, httpx.Response(200, json=body))

    result = await web_search.search("arabian sea warming", max_results=3)

    assert rec.request is not None
    assert rec.request.url.host == "api.tavily.com"
    sent = rec.request.read()
    assert b'"api_key": "test-key"' in sent or b'"api_key":"test-key"' in sent

    assert result["result_count"] == 1
    assert result["results"][0] == {
        "title": "Arabian Sea marine heatwave",
        "url": "https://example.org/article",
        "snippet": "The Arabian Sea has seen unusually warm water this week.",
        "published_date": "2026-08-20",
    }


@pytest.mark.asyncio
async def test_missing_title_and_date_degrade_rather_than_crash(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TAVILY_API_KEY", "test-key")
    body = {"results": [{"url": "https://example.org/x", "content": "some text"}]}
    _install(monkeypatch, httpx.Response(200, json=body))

    result = await web_search.search("x")

    assert result["results"][0]["title"] == "(untitled)"
    assert result["results"][0]["published_date"] is None


@pytest.mark.asyncio
async def test_max_results_is_clamped_to_ten(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TAVILY_API_KEY", "test-key")
    rec = _install(monkeypatch, httpx.Response(200, json={"results": []}))

    await web_search.search("x", max_results=99)

    import json

    sent = json.loads(rec.request.read())
    assert sent["max_results"] == 10


@pytest.mark.asyncio
async def test_a_bad_key_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TAVILY_API_KEY", "wrong-key")
    _install(monkeypatch, httpx.Response(401, text="Unauthorized"))

    with pytest.raises(web_search.WebSearchError, match="rejected"):
        await web_search.search("x")


@pytest.mark.asyncio
async def test_rate_limit_raises_a_distinct_message(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TAVILY_API_KEY", "test-key")
    _install(monkeypatch, httpx.Response(429, text="Too Many Requests"))

    with pytest.raises(web_search.WebSearchError, match="rate-limited"):
        await web_search.search("x")
