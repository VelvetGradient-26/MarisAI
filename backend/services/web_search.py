"""General web search, via Tavily.

sihtodo.md item 4 asks for a controlled-internet tool so the assistant can
answer a question like "why is the Arabian Sea unusually warm this week" —
something no MarisAI service can measure, because it needs today's news and
commentary, not another ocean field. This module is deliberately not a
scrape: it calls a real search API with an issued key, the same shape every
other credentialed integration in this codebase already takes
(`services/gfw.py`'s `GFW_TOKEN`, `services/ais.py`'s `AISSTREAM_API_KEY`).

**No genuinely keyless full web search API exists**, unlike CrossRef
(`services/literature.py`) — this was checked before picking a provider.
DuckDuckGo's only unauthenticated endpoint is its Instant Answer API, which
returns a single abstract (typically a Wikipedia snippet) rather than a
ranked result list, and its HTML results page is a scrape target, not an
API — the same "HTML only, not a machine-readable feed" distinction
CLAUDE.md's Indian-sources survey already draws for INCOIS/MOSDAC, and
scraping was ruled out there for the same reason it is here. Tavily was
chosen over Bing/Brave/SerpAPI because it is built for LLM tool-calling
specifically: results come back as clean `{title, url, content}` records
with no HTML to strip, which matches this codebase's existing preference
(CrossRef, GDACS, IMD's CAP feed) for a provider that hands back structured
data rather than a page to parse.

**Not verified against a live Tavily response** — no `TAVILY_API_KEY` is
provisioned in this environment. Verified instead: the request shape against
Tavily's documented API contract, and the response parsing against a
recorded fixture shaped like Tavily's documented response
(`tests/test_web_search.py`). The same caveat this codebase already states
for the Gemini-dependent glossary check applies here — confirm against a
live key before relying on this in front of a judge.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.tavily.com/search"
_TIMEOUT = httpx.Timeout(15.0)


class WebSearchError(RuntimeError):
    """Web search is not configured, or Tavily could not be reached."""


async def search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Run a web search and return a provenance-preserving result list.

    Every result keeps its title, url and a snippet — per sihtodo.md item 4's
    own requirement that a retrieved fact stay traceable to where it came
    from, the same discipline `services/chat/agent.py`'s grounding check
    already enforces for MarisAI's own tools. `published_date` is included
    when Tavily reports one, `None` otherwise — never guessed.
    """
    if not settings.TAVILY_API_KEY:
        raise WebSearchError(
            "Web search is not configured (set TAVILY_API_KEY in backend/.env)."
        )

    max_results = max(1, min(int(max_results), 10))
    payload = {
        "api_key": settings.TAVILY_API_KEY,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(_SEARCH_URL, json=payload)
    except httpx.HTTPError as exc:
        raise WebSearchError(f"Web search could not be reached: {exc}") from exc

    if response.status_code == 401:
        raise WebSearchError("Web search rejected the configured TAVILY_API_KEY.")
    if response.status_code == 429:
        raise WebSearchError("Web search is rate-limited right now; try again shortly.")
    if response.status_code >= 400:
        raise WebSearchError(
            f"Web search request failed ({response.status_code}): {response.text[:200]}"
        )

    body = response.json()
    results = [
        {
            "title": item.get("title") or "(untitled)",
            "url": item.get("url"),
            "snippet": (item.get("content") or "")[:800],
            "published_date": item.get("published_date"),
        }
        for item in body.get("results", [])
    ]

    return {
        "query": query,
        "results": results,
        "result_count": len(results),
        "source": "Tavily web search",
    }
