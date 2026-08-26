"""Crossref-backed scientific literature search.

No network: `_get` is monkeypatched directly, the same convention
`test_cyclones.py` uses for GDACS. See `services/literature.py`'s module
docstring for the real Crossref response this shape was verified against
live on 2026-08-26.
"""

from __future__ import annotations

import httpx
import pytest

from services import literature


def _crossref_item(**overrides) -> dict:
    item = {
        "title": ["Arabian Sea Cyclogenesis and Sea Surface Temperature Variability"],
        "author": [{"given": "Sreenandha J", "family": "Nandha"}],
        "published": {"date-parts": [[2026, 8, 5]]},
        "container-title": ["ESSOAr"],
        "DOI": "10.22541/essoar.15007064/v1",
        "URL": "https://doi.org/10.22541/essoar.15007064/v1",
        "abstract": "<jats:p>The Arabian Sea has warmed at a fast rate.</jats:p>",
    }
    item.update(overrides)
    return item


@pytest.mark.asyncio
async def test_results_carry_title_authors_date_and_clean_abstract(monkeypatch):
    async def fake_get(client, params):
        return {"message": {"items": [_crossref_item()]}}

    monkeypatch.setattr(literature, "_get", fake_get)

    result = await literature.search("arabian sea warming")

    assert result["result_count"] == 1
    entry = result["results"][0]
    assert entry["title"] == "Arabian Sea Cyclogenesis and Sea Surface Temperature Variability"
    assert entry["authors"] == ["Sreenandha J Nandha"]
    assert entry["published_date"] == "2026-08-05"
    assert entry["venue"] == "ESSOAr"
    assert entry["doi"] == "10.22541/essoar.15007064/v1"
    assert "<jats:p>" not in entry["abstract_snippet"]
    assert "warmed" in entry["abstract_snippet"]


@pytest.mark.asyncio
async def test_a_missing_abstract_is_none_not_empty_string(monkeypatch):
    async def fake_get(client, params):
        return {"message": {"items": [_crossref_item(abstract=None)]}}

    monkeypatch.setattr(literature, "_get", fake_get)

    result = await literature.search("arabian sea warming")

    assert result["results"][0]["abstract_snippet"] is None


@pytest.mark.asyncio
async def test_a_single_year_date_is_not_zero_padded_into_nonsense(monkeypatch):
    """[2026] alone (no month/day) must render as "2026", not "2026-00-00"."""

    async def fake_get(client, params):
        return {"message": {"items": [_crossref_item(published={"date-parts": [[2026]]})]}}

    monkeypatch.setattr(literature, "_get", fake_get)

    result = await literature.search("anything")

    assert result["results"][0]["published_date"] == "2026"


@pytest.mark.asyncio
async def test_no_results_is_a_real_answer_not_an_error(monkeypatch):
    async def fake_get(client, params):
        return {"message": {"items": []}}

    monkeypatch.setattr(literature, "_get", fake_get)

    result = await literature.search("a query nobody has published on")

    assert result["result_count"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_a_crossref_failure_raises_literature_error(monkeypatch):
    async def fake_get(client, params):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(literature, "_get", fake_get)

    with pytest.raises(literature.LiteratureError):
        await literature.search("anything")


@pytest.mark.asyncio
async def test_an_empty_query_is_rejected():
    with pytest.raises(literature.LiteratureError):
        await literature.search("   ")
