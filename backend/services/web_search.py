"""General web search, via Tavily.

sihtodo.md item 4 ("controlled internet tools") names `web_search` as one of
three internet tools this codebase had none of. It exists for the guide's own
example question — "why is the Arabian Sea unusually warm this week?" — which
no live-measurement tool in this codebase can answer: MarisAI's own
specialists report *what* the ocean is doing (an SST anomaly), not *why*, and
"why" for a recent, unusual event routinely lives in this week's reporting,
not in any dataset this platform holds.

**Tavily, gated on `TAVILY_API_KEY`, and genuinely unverified against a live
key** — unlike every other external integration in this codebase, which is
probed live before being trusted (see `services/cyclones.py`,
`services/severe_weather.py`, `services/literature.py` beside this one). No
Tavily account exists in this environment. The request/response shape below
is implemented against Tavily's documented REST contract (a JSON POST
carrying `api_key`/`query`, a `results` list of
`title`/`url`/`content`/`published_date`) rather than against a real
response, and should be re-verified with a live key before this tool is
trusted the way the rest of this codebase's integrations are — the same
caveat this codebase already states for the untested-against-real-Gemini
glossary guardrail.

**Chosen over a keyless alternative because none of the keyless options is
actually general web search.** DuckDuckGo's public endpoint is an "instant
answer" API (infobox-shaped, not ranked web results) and its HTML search page
has no documented API and blocks scripted access — neither is a real fit.
Wikipedia's API is keyless and reliable but is an encyclopedia, not a search
of current reporting, and cannot answer "this week" questions at all. A
paid/keyed general-purpose search API is the only category of thing that
actually answers the guide's example question, which is why this module —
unlike `services/literature.py` beside it — needs a credential at all.

**Degrades to a clear "not configured" tool error, not a crash.** Same
pattern as `AISSTREAM_API_KEY`/`GFW_TOKEN`: an unset key must not take down
the assistant, so `search()` raises `WebSearchError` (caught by
`services/chat/tools.py`'s generic tool wrapper) rather than the model ever
seeing a stack trace.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
_TIMEOUT = httpx.Timeout(20.0)


class WebSearchError(RuntimeError):
    """Web search is not configured, or the provider could not be reached."""


async def _post(client: httpx.AsyncClient, payload: dict[str, Any]) -> Any:
    response = await client.post(TAVILY_URL, json=payload)
    response.raise_for_status()
    return response.json()


def _summarize(item: dict[str, Any]) -> dict[str, Any]:
    url = item.get("url") or ""
    return {
        "title": item.get("title"),
        "url": url,
        "snippet": item.get("content"),
        "published_date": item.get("published_date"),
        "source": urlparse(url).hostname or "web",
    }


async def search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Web results for `query`, with title/url/snippet/date provenance.

    Never raises for "nothing found" — an empty result list is a real answer.
    Raises `WebSearchError` when no API key is configured or the provider
    could not be reached; both are tool-layer failures the model should be
    told about plainly, not silently substituted with a guess.
    """
    query = (query or "").strip()
    if not query:
        raise WebSearchError("A search query is required.")
    if not settings.TAVILY_API_KEY:
        raise WebSearchError(
            "Web search is not configured. Set TAVILY_API_KEY in the backend "
            "environment to enable it."
        )

    payload = {
        "api_key": settings.TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "topic": "general",
        "max_results": max(1, min(max_results, 10)),
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            data = await _post(client, payload)
    except httpx.HTTPStatusError as exc:
        raise WebSearchError(
            f"The web search provider returned {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning(f"Tavily search request failed: {exc}")
        raise WebSearchError(f"The web search provider could not be reached: {exc}") from exc

    results = [_summarize(item) for item in data.get("results") or []]

    return {
        "query": query,
        "results": results,
        "result_count": len(results),
        "source": "Tavily web search",
        "note": (
            "General web results, not MarisAI's own measurements — name the "
            "source and date when relaying anything from these."
            if results
            else "No web results found for this query."
        ),
    }
