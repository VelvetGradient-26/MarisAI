"""Scientific literature search, via Crossref.

sihtodo.md item 4 ("controlled internet tools") names `search_scientific_literature`
as one of three internet tools this codebase had none of — the guide's example
question ("why is the Arabian Sea unusually warm this week?") is exactly the
shape of question that benefits from grounding the assistant's own synthesis
in published research rather than general knowledge.

**Crossref, not Semantic Scholar.** Semantic Scholar's Graph API
(`api.semanticscholar.org/graph/v1/paper/search`) is the more commonly used
academic-search API and was tried first, but a live probe on 2026-08-26
returned 429 (rate-limited) on the very first unauthenticated request and
again after a 20s wait — its public tier is shared across every caller
worldwide with no key. Crossref (`api.crossref.org/works`) is the DOI
registration agency's own search API: also keyless, no rate limit observed in
the same session, and it is the metadata source of record for every
DOI-bearing scholarly work — not narrower AI/CS-heavy coverage the way
Semantic Scholar's index is. Probed live 2026-08-26 with
`query=arabian+sea+sea+surface+temperature+warming`: real, current results (a
2026-08-05 preprint on Arabian Sea cyclogenesis and SST trends among them),
each carrying title, author(s), a publication date, DOI, container-title
(journal/venue) and, for many records, an abstract.

**No API key, and none is added.** Crossref's public API is unauthenticated.
A `mailto` parameter for its documented "polite pool" (a courtesy that raises
rate-limit priority) was considered and skipped — the only value available to
fill it is the deployment operator's own email address, and this module has
no business sending a person's address to a third party on every literature
search. The plain pool's limits have not been a problem in probing.

**Not every result carries an abstract.** Crossref indexes bibliographic
metadata for the whole scholarly record, including works whose publisher
never submitted abstract text — `abstract_snippet` is `None` in that case,
stated rather than guessed at.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CROSSREF_URL = "https://api.crossref.org/works"
_TIMEOUT = httpx.Timeout(20.0)
_USER_AGENT = "MarisAI-OceanAssistant/1.0 (literature search tool)"

_SELECT_FIELDS = (
    "title,author,published,published-print,published-online,DOI,"
    "container-title,abstract,URL"
)


class LiteratureError(RuntimeError):
    """Crossref could not be reached, or answered with something unusable."""


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_abstract(raw: str | None) -> str | None:
    """Crossref returns JATS-tagged XML fragments (`<jats:p>...</jats:p>`) for
    an abstract; a chat answer needs the text, not the markup."""
    if not raw:
        return None
    text = _TAG_RE.sub("", raw).strip()
    return text or None


def _format_date(date_parts: list[int]) -> str | None:
    if not date_parts:
        return None
    parts = [str(date_parts[0])]
    parts.extend(f"{part:02d}" for part in date_parts[1:])
    return "-".join(parts)


async def _get(client: httpx.AsyncClient, params: dict[str, Any]) -> Any:
    response = await client.get(CROSSREF_URL, params=params, headers={"User-Agent": _USER_AGENT})
    response.raise_for_status()
    return response.json()


def _summarize(item: dict[str, Any]) -> dict[str, Any]:
    authors = [
        " ".join(part for part in (author.get("given"), author.get("family")) if part)
        for author in item.get("author") or []
    ]
    published = (
        item.get("published")
        or item.get("published-print")
        or item.get("published-online")
        or {}
    )
    date_parts = (published.get("date-parts") or [[]])[0]
    titles = item.get("title") or []
    return {
        "title": titles[0] if titles else None,
        "authors": [a for a in authors if a],
        "published_date": _format_date(date_parts),
        "venue": (item.get("container-title") or [None])[0],
        "doi": item.get("DOI"),
        "url": item.get("URL"),
        "abstract_snippet": _clean_abstract(item.get("abstract")),
        "source": "Crossref",
    }


async def search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Scholarly works matching `query`, ranked by Crossref's own relevance score.

    Never raises for "nothing found" — an empty result list is a real answer.
    Only an unreachable Crossref raises `LiteratureError`.
    """
    query = (query or "").strip()
    if not query:
        raise LiteratureError("A search query is required.")

    params = {
        "query": query,
        "rows": max(1, min(max_results, 10)),
        "select": _SELECT_FIELDS,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            data = await _get(client, params)
    except httpx.HTTPStatusError as exc:
        raise LiteratureError(
            f"Crossref returned {exc.response.status_code} for {query!r}"
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning(f"Crossref request failed: {exc}")
        raise LiteratureError(f"Crossref could not be reached: {exc}") from exc

    items = (data.get("message") or {}).get("items") or []
    results = [_summarize(item) for item in items]

    return {
        "query": query,
        "results": results,
        "result_count": len(results),
        "source": "Crossref (scholarly metadata registry, https://www.crossref.org)",
        "note": (
            "Bibliographic metadata, not full text. abstract_snippet is null "
            "when the publisher did not submit one to Crossref."
            if results
            else "No matching scholarly works found."
        ),
    }
