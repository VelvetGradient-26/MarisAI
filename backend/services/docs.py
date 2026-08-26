"""Search over MarisAI's own documentation, for the assistant's
`get_documentation` tool (self-knowledge about the platform, not ocean data).

The docs chapters are React/TSX source under
`frontend/src/pages/docs/chapters/`, not markdown, and this process has no JS
runtime to render them. `data/docs_index.json` is therefore a plain-text
export produced by `frontend/scripts/export-docs-index.ts` — the same
chapters the in-app docs search (`chapters/searchIndex.tsx`) already indexes,
run once as a build step rather than requiring Node here. It is a committed,
generated file: regenerate it with `cd frontend && npm run export-docs`
after editing any chapter. Nothing here fails the backend if the export is
stale or missing — the tool degrades to "no chapters matched" rather than
breaking chat startup, since documentation lookup is not load-bearing the
way an ocean-data provider is.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_INDEX_PATH = Path(__file__).resolve().parent.parent / "data" / "docs_index.json"

# A body match counts for less than a title/group match — the same tie-break
# the in-app search box's own `titleMatch` ranking uses (searchIndex.tsx),
# applied here as a numeric weight rather than a boolean sort key because a
# tool result also needs a score to cut off at `limit`.
_TITLE_WEIGHT = 5

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class DocChapter:
    id: str
    label: str
    title: str
    group: str
    url: str
    text: str


_cache: list[DocChapter] | None = None


def _load() -> list[DocChapter]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        raw = json.loads(_INDEX_PATH.read_text())
        _cache = [DocChapter(**entry) for entry in raw]
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning(f"docs index unavailable ({exc}); get_documentation will find no chapters")
        _cache = []
    return _cache


def _words(text: str) -> set[str]:
    # len >= 3 drops connective noise ("is", "to", "of") without a hand-kept
    # stopword list that would need to track chapter prose forever.
    return {w for w in _WORD.findall(text.lower()) if len(w) >= 3}


def _snippet(text: str, query_words: set[str], radius: int = 220) -> str:
    """An excerpt around the earliest query-word match, not the chapter start.

    The chapter's opening sentence is usually a general framing line, not the
    part that answers a specific question — same reasoning as the in-app
    search box's own `snippetAround` (searchIndex.tsx), independently applied
    here since this runs in a different language and cannot import that one.
    """
    lowered = text.lower()
    index = -1
    for word in query_words:
        found = lowered.find(word)
        if found != -1 and (index == -1 or found < index):
            index = found
    if index == -1:
        return text[: 2 * radius].strip() + ("…" if len(text) > 2 * radius else "")
    start = max(0, index - radius // 2)
    end = min(len(text), index + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def search(query: str, limit: int = 3) -> list[dict[str, str]]:
    """Rank documentation chapters by word overlap with `query`.

    Word-overlap rather than a plain substring match: a chat tool receives a
    natural-language question ("how do I read the map colours"), and a real
    question rarely appears verbatim inside a chapter's own prose the way a
    search-box phrase can be typed to.
    """
    chapters = _load()
    query_words = _words(query)
    if not chapters or not query_words:
        return []

    scored: list[tuple[int, DocChapter]] = []
    for chapter in chapters:
        title_words = _words(f"{chapter.label} {chapter.title} {chapter.group}")
        body_words = _words(chapter.text)
        score = _TITLE_WEIGHT * len(query_words & title_words) + len(query_words & body_words)
        if score > 0:
            scored.append((score, chapter))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "chapter": chapter.label,
            "group": chapter.group,
            "url": chapter.url,
            "snippet": _snippet(chapter.text, query_words),
        }
        for _, chapter in scored[:limit]
    ]
