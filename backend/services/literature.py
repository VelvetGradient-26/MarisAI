"""Scientific literature search, via CrossRef.

sihtodo.md item 4's `search_scientific_literature` tool. CrossRef is the
metadata registry every DOI-issuing publisher deposits into, and its
`/works` search endpoint is genuinely keyless — `CROSSREF_MAILTO` (optional,
`app/core/config.py`) only opts into CrossRef's documented "polite pool" for
a better rate limit, it is not an API key and its absence never blocks a
request. CLAUDE.md's own fisheries-data survey already vetted CrossRef-shaped
registries as real, structured, drop-in APIs (its "Tier 1" table) — this is
the same class of source applied to literature instead of occurrences.

**Verified live 2026-08-27**: `https://api.crossref.org/works?query=arabian+
sea+warming&filter=type:journal-article&select=DOI,title,author,
container-title,issued,URL` returned 200 with real journal-article records
(e.g. DOI 10.1029/2018gl081631, "Strong Intensification of the Arabian Sea
Oxygen Minimum Zone...", Geophysical Research Letters, 2019) — not a fixture.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_WORKS_URL = "https://api.crossref.org/works"
_TIMEOUT = httpx.Timeout(15.0)
_SELECT_FIELDS = "DOI,title,author,container-title,issued,URL,abstract"


class LiteratureError(RuntimeError):
    """CrossRef could not be reached or answered with nothing usable."""


def _authors(item: dict[str, Any]) -> list[str]:
    names = []
    for author in item.get("author") or []:
        parts = [author.get("given"), author.get("family")]
        name = " ".join(p for p in parts if p)
        if name:
            names.append(name)
    return names


def _issued_date(item: dict[str, Any]) -> str | None:
    parts = (item.get("issued") or {}).get("date-parts") or []
    if not parts or not parts[0]:
        return None
    # CrossRef reports date-parts at whatever precision the publisher gave —
    # a year alone, or year/month, or a full date. Join what is actually
    # present rather than padding a guessed month/day onto a year-only record.
    return "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts[0]))


async def search_literature(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search published scientific literature for `query`.

    Restricted to `type:journal-article` — CrossRef also indexes peer-review
    reports, book chapters and dataset records under the same endpoint, and a
    tuna-habitat question is better served by an actual paper than by a
    referee report about one (see the module's live-verification note).
    """
    max_results = max(1, min(int(max_results), 10))
    params = {
        "query": query,
        "rows": max_results,
        "filter": "type:journal-article",
        "select": _SELECT_FIELDS,
    }
    if settings.CROSSREF_MAILTO:
        params["mailto"] = settings.CROSSREF_MAILTO

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(_WORKS_URL, params=params)
    except httpx.HTTPError as exc:
        raise LiteratureError(f"CrossRef could not be reached: {exc}") from exc

    if response.status_code >= 400:
        raise LiteratureError(
            f"CrossRef search failed ({response.status_code}): {response.text[:200]}"
        )

    body = response.json()
    items = ((body.get("message") or {}).get("items")) or []

    results = []
    for item in items:
        titles = item.get("title") or []
        results.append(
            {
                "title": titles[0] if titles else "(untitled)",
                "authors": _authors(item),
                "journal": (item.get("container-title") or [None])[0],
                "published": _issued_date(item),
                "doi": item.get("DOI"),
                "url": item.get("URL"),
            }
        )

    return {
        "query": query,
        "results": results,
        "result_count": len(results),
        "source": "CrossRef (api.crossref.org)",
    }
