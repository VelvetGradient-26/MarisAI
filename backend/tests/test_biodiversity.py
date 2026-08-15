"""OBIS biodiversity at a point.

Nothing here calls OBIS. What is worth pinning is local: the geometry sent, the
bias disclosure, and the distinction between "no records" and "failed" — which
is the same rule the dashboard holds everywhere and is easier to get wrong here,
because an empty box is the *normal* answer over most of the ocean.
"""

from __future__ import annotations

import asyncio

import pytest

from services import biodiversity


def test_the_search_box_is_clamped_at_the_poles():
    # A box straddling the pole is not a box. Latitude clamps rather than wraps.
    min_lon, min_lat, max_lon, max_lat = biodiversity._box(89.8, 0.0, 0.5)
    assert max_lat == 90.0
    assert min_lat == pytest.approx(89.3)


def test_the_geometry_is_a_closed_polygon():
    wkt = biodiversity._wkt(75.0, 9.5, 76.0, 10.5)
    assert wkt.startswith("POLYGON((") and wkt.endswith("))")
    corners = wkt[len("POLYGON((") : -2].split(", ")
    # Five points, first equal to last — an unclosed ring is rejected upstream.
    assert len(corners) == 5
    assert corners[0] == corners[-1]


def test_box_area_shrinks_toward_the_poles():
    """A fixed-degree box is a different area at different latitudes, which is
    exactly why the response quotes an area and a per-area density rather than a
    bare count that cannot be compared between two latitudes."""
    tropical = biodiversity._box_area_km2(75.0, 9.5, 76.0, 10.5)
    polar = biodiversity._box_area_km2(75.0, 69.5, 76.0, 70.5)
    assert polar < tropical / 2


def test_a_report_carries_the_bias_note(monkeypatch):
    """The note is a required field, not small print.

    These counts measure survey effort; the habitat model in the same product
    exists partly to correct that bias, and printing an uncorrected headline
    without saying so would be indefensible.
    """
    async def fake_get(client, path, params):
        if path == "/statistics":
            if params.get("taxonid"):
                return {"records": 279, "species": 117, "taxa": 122, "datasets": 7}
            return {
                "records": 1168,
                "species": 202,
                "taxa": 891,
                "datasets": 27,
                "yearrange": [1852, 2025],
            }
        return {
            "total": 891,
            "results": [
                {"scientificName": "Megalops cyprinoides", "taxonRank": "Species", "records": 14},
                {"scientificName": "Echeneis naucrates", "taxonRank": "Species", "records": 8},
            ],
        }

    monkeypatch.setattr(biodiversity, "_get", fake_get)
    biodiversity._cache.clear()

    report = asyncio.run(biodiversity.at_point(10.0, 75.0))

    assert "SURVEY EFFORT" in report["bias_note"]
    assert report["totals"]["records"] == 1168
    assert report["totals"]["fish_species"] == 117
    assert report["totals"]["first_year"] == 1852
    assert report["totals"]["records_per_1000_km2"] > 0
    # Truncated, and it says so — 891 taxa are not being served as a page.
    assert report["species_truncated"] is True
    assert len(report["species"]) == 2
    assert "empty_reason" not in report


def test_an_empty_box_is_an_answer_not_a_failure(monkeypatch):
    """Most of the open ocean has never been sampled. Reporting that as an
    error, or as "no life here", inverts what the data says."""
    async def fake_get(client, path, params):
        if path == "/statistics":
            return {"records": 0, "species": 0, "taxa": 0, "datasets": 0}
        return {"total": 0, "results": []}

    monkeypatch.setattr(biodiversity, "_get", fake_get)
    biodiversity._cache.clear()

    report = asyncio.run(biodiversity.at_point(-40.0, -140.0))

    assert report["totals"]["records"] == 0
    assert "never been sampled" in report["empty_reason"]
    assert report["species"] == []


def test_an_out_of_range_request_is_refused_before_a_network_call():
    with pytest.raises(biodiversity.BiodiversityError):
        asyncio.run(biodiversity.at_point(100.0, 0.0))
    with pytest.raises(biodiversity.BiodiversityError):
        asyncio.run(biodiversity.at_point(0.0, 0.0, radius_deg=20.0))


def test_repeated_requests_for_the_same_place_hit_the_cache(monkeypatch):
    calls = {"n": 0}

    async def fake_get(client, path, params):
        calls["n"] += 1
        if path == "/statistics":
            return {"records": 5, "species": 3, "taxa": 3, "datasets": 1}
        return {"total": 3, "results": []}

    monkeypatch.setattr(biodiversity, "_get", fake_get)
    biodiversity._cache.clear()

    asyncio.run(biodiversity.at_point(10.0, 75.0))
    first = calls["n"]
    # Three calls per report: statistics, fish statistics, checklist.
    assert first == 3

    asyncio.run(biodiversity.at_point(10.001, 75.001))
    # Rounded to two decimals, so a cursor nudge is the same place.
    assert calls["n"] == first
