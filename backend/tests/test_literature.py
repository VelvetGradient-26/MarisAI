"""services/literature.py (sihtodo.md item 4's search_scientific_literature
tool), via CrossRef.

No network here — `httpx.AsyncClient` is patched onto a `MockTransport`,
same convention as `test_download_gebco.py`. The module's own docstring
records the separate live probe against the real `api.crossref.org` that
established this shape works before these unit tests were written.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from services import literature

# Captured once, before any test patches `literature.httpx.AsyncClient` — that
# attribute lives on the shared `httpx` module (`literature.httpx` *is*
# `httpx`), so re-reading `httpx.AsyncClient` inside `_install` after a first
# patch would capture the previous test's fake client as "real", chaining
# fakes together silently instead of reaching the mock transport.
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

    monkeypatch.setattr(literature.httpx, "AsyncClient", patched)
    return rec


def _crossref_body(items: list[dict]) -> dict:
    return {"status": "ok", "message": {"items": items}}


@pytest.mark.asyncio
async def test_maps_every_field_of_a_full_record(monkeypatch: pytest.MonkeyPatch):
    item = {
        "DOI": "10.1029/2018gl081631",
        "title": ["Strong Intensification of the Arabian Sea Oxygen Minimum Zone"],
        "author": [
            {"given": "Z.", "family": "Lachkar"},
            {"given": "M.", "family": "Lévy"},
        ],
        "container-title": ["Geophysical Research Letters"],
        "issued": {"date-parts": [[2019, 5]]},
        "URL": "https://doi.org/10.1029/2018gl081631",
    }
    _install(monkeypatch, httpx.Response(200, json=_crossref_body([item])))

    result = await literature.search_literature("arabian sea warming")

    assert result["result_count"] == 1
    paper = result["results"][0]
    assert paper["title"] == "Strong Intensification of the Arabian Sea Oxygen Minimum Zone"
    assert paper["authors"] == ["Z. Lachkar", "M. Lévy"]
    assert paper["journal"] == "Geophysical Research Letters"
    assert paper["published"] == "2019-05"
    assert paper["doi"] == "10.1029/2018gl081631"
    assert paper["url"] == "https://doi.org/10.1029/2018gl081631"


@pytest.mark.asyncio
async def test_a_year_only_record_is_not_padded_with_a_guessed_month(
    monkeypatch: pytest.MonkeyPatch,
):
    item = {"DOI": "x", "title": ["t"], "issued": {"date-parts": [[2020]]}}
    _install(monkeypatch, httpx.Response(200, json=_crossref_body([item])))

    result = await literature.search_literature("x")

    assert result["results"][0]["published"] == "2020"


@pytest.mark.asyncio
async def test_missing_title_authors_and_journal_degrade_rather_than_crash(
    monkeypatch: pytest.MonkeyPatch,
):
    item = {"DOI": "x"}
    _install(monkeypatch, httpx.Response(200, json=_crossref_body([item])))

    result = await literature.search_literature("x")

    paper = result["results"][0]
    assert paper["title"] == "(untitled)"
    assert paper["authors"] == []
    assert paper["journal"] is None
    assert paper["published"] is None


@pytest.mark.asyncio
async def test_request_filters_to_journal_articles_only(monkeypatch: pytest.MonkeyPatch):
    rec = _install(monkeypatch, httpx.Response(200, json=_crossref_body([])))

    await literature.search_literature("x", max_results=3)

    assert rec.request is not None
    params = dict(rec.request.url.params)
    assert params["filter"] == "type:journal-article"
    assert params["rows"] == "3"


@pytest.mark.asyncio
async def test_mailto_is_only_sent_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "CROSSREF_MAILTO", "")
    rec = _install(monkeypatch, httpx.Response(200, json=_crossref_body([])))
    await literature.search_literature("x")
    assert "mailto" not in dict(rec.request.url.params)

    monkeypatch.setattr(settings, "CROSSREF_MAILTO", "team@marisai.example")
    rec2 = _install(monkeypatch, httpx.Response(200, json=_crossref_body([])))
    await literature.search_literature("x")
    assert dict(rec2.request.url.params)["mailto"] == "team@marisai.example"


@pytest.mark.asyncio
async def test_upstream_failure_raises_a_literature_error(monkeypatch: pytest.MonkeyPatch):
    _install(monkeypatch, httpx.Response(503, text="Service Unavailable"))

    with pytest.raises(literature.LiteratureError, match="503"):
        await literature.search_literature("x")


@pytest.mark.asyncio
async def test_max_results_is_clamped_to_ten(monkeypatch: pytest.MonkeyPatch):
    rec = _install(monkeypatch, httpx.Response(200, json=_crossref_body([])))

    await literature.search_literature("x", max_results=500)

    assert dict(rec.request.url.params)["rows"] == "10"
