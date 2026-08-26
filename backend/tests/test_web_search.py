"""Tavily-backed web search.

No network: `_post` is monkeypatched directly, the same convention
`test_cyclones.py` uses for `_get`. `services/web_search.py`'s module
docstring states plainly that this shape is unverified against a real
Tavily response — no key exists in this environment — so these tests pin
the parsing contract, not a live provider's actual behaviour.
"""

from __future__ import annotations

import httpx
import pytest

from services import web_search


@pytest.mark.asyncio
async def test_missing_api_key_raises_a_clear_error(monkeypatch):
    monkeypatch.setattr(web_search.settings, "TAVILY_API_KEY", "")

    with pytest.raises(web_search.WebSearchError, match="not configured"):
        await web_search.search("arabian sea warming")


@pytest.mark.asyncio
async def test_results_carry_title_url_snippet_and_date(monkeypatch):
    monkeypatch.setattr(web_search.settings, "TAVILY_API_KEY", "test-key")

    async def fake_post(client, payload):
        assert payload["query"] == "arabian sea warming"
        assert payload["api_key"] == "test-key"
        return {
            "results": [
                {
                    "title": "Arabian Sea sees unusual warmth",
                    "url": "https://news.example.com/arabian-sea",
                    "content": "Sea surface temperatures are running high...",
                    "published_date": "2026-08-20",
                }
            ]
        }

    monkeypatch.setattr(web_search, "_post", fake_post)

    result = await web_search.search("arabian sea warming")

    assert result["result_count"] == 1
    entry = result["results"][0]
    assert entry["title"] == "Arabian Sea sees unusual warmth"
    assert entry["url"] == "https://news.example.com/arabian-sea"
    assert entry["published_date"] == "2026-08-20"
    assert entry["source"] == "news.example.com"


@pytest.mark.asyncio
async def test_no_results_is_a_real_answer_not_an_error(monkeypatch):
    monkeypatch.setattr(web_search.settings, "TAVILY_API_KEY", "test-key")

    async def fake_post(client, payload):
        return {"results": []}

    monkeypatch.setattr(web_search, "_post", fake_post)

    result = await web_search.search("a query with truly nothing")

    assert result["result_count"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_a_provider_failure_raises_web_search_error(monkeypatch):
    monkeypatch.setattr(web_search.settings, "TAVILY_API_KEY", "test-key")

    async def fake_post(client, payload):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(web_search, "_post", fake_post)

    with pytest.raises(web_search.WebSearchError):
        await web_search.search("anything")


@pytest.mark.asyncio
async def test_an_empty_query_is_rejected(monkeypatch):
    monkeypatch.setattr(web_search.settings, "TAVILY_API_KEY", "test-key")

    with pytest.raises(web_search.WebSearchError):
        await web_search.search("   ")
