"""services/pfz.py: the heuristic PFZ scan over the cached SST/chlorophyll grids.

Both caches are monkeypatched at the module level `pfz.py` calls them at
(`copernicus_sst.get_point`, `copernicus_chlorophyll.get_point`), not at
`pfz`'s own import site — `pfz.py` calls `copernicus_sst.get_point(...)`
through the module reference, so a patch at the module attribute is what the
real call site sees.
"""

from __future__ import annotations

import pytest

from services import copernicus_chlorophyll, copernicus_sst, pfz


def test_degrades_honestly_when_chlorophyll_cache_is_cold(monkeypatch):
    monkeypatch.setattr(copernicus_chlorophyll, "is_available", lambda: False)
    monkeypatch.setattr(copernicus_sst, "is_available", lambda: True)

    result = pfz.find_zones(9.9, 76.2)

    assert result["available"] is False
    assert "chlorophyll" in result["reason"].lower()


def test_degrades_honestly_when_sst_cache_is_cold(monkeypatch):
    monkeypatch.setattr(copernicus_chlorophyll, "is_available", lambda: True)
    monkeypatch.setattr(copernicus_sst, "is_available", lambda: False)

    result = pfz.find_zones(9.9, 76.2)

    assert result["available"] is False
    assert "sst" in result["reason"].lower()


def _grid_point(chl_by_cell: dict, sst_by_cell: dict):
    def chl(lat, lon):
        key = (round(lat, 3), round(lon, 3))
        value = chl_by_cell.get(key)
        return {
            "chlorophyll_mg_m3": value,
            "is_land_or_no_data": value is None,
            "timestamp": "2026-08-22T00:00:00+00:00",
            "source": "test",
        }

    def sst(lat, lon):
        key = (round(lat, 3), round(lon, 3))
        value = sst_by_cell.get(key)
        return {
            "temperature_c": value,
            "is_land_or_no_data": value is None,
            "timestamp": "2026-08-22T00:00:00+00:00",
            "source": "test",
        }

    return chl, sst


def test_ranks_a_high_chlorophyll_favourable_sst_cell_first(monkeypatch):
    monkeypatch.setattr(copernicus_chlorophyll, "is_available", lambda: True)
    monkeypatch.setattr(copernicus_sst, "is_available", lambda: True)

    # Fix the candidate grid to exactly two cells, so this test is about the
    # ranking rule, not `_candidate_grid`'s own geometry.
    good = (10.0, 76.0)
    bad = (10.0, 75.0)
    monkeypatch.setattr(pfz, "_candidate_grid", lambda lat, lon, radius_km: [good, bad])

    chl_by_cell = {good: 3.0, bad: 0.1}
    sst_by_cell = {good: 27.0, bad: 27.0}
    chl_fn, sst_fn = _grid_point(chl_by_cell, sst_by_cell)
    monkeypatch.setattr(copernicus_chlorophyll, "get_point", lambda lat, lon: chl_fn(lat, lon))
    monkeypatch.setattr(copernicus_sst, "get_point", lambda lat, lon: sst_fn(lat, lon))
    monkeypatch.setattr(copernicus_chlorophyll, "is_stale", lambda: False)
    monkeypatch.setattr(copernicus_chlorophyll, "SOURCE_LABEL", "test-chl")
    monkeypatch.setattr(copernicus_sst, "SOURCE_LABEL", "test-sst")

    result = pfz.find_zones(10.0, 75.5, radius_km=120)

    assert result["available"] is True
    assert result["zones"], "expected at least one ranked candidate"
    top = result["zones"][0]
    assert (top["latitude"], top["longitude"]) == good


def test_land_or_no_data_cells_are_excluded(monkeypatch):
    monkeypatch.setattr(copernicus_chlorophyll, "is_available", lambda: True)
    monkeypatch.setattr(copernicus_sst, "is_available", lambda: True)
    monkeypatch.setattr(copernicus_chlorophyll, "get_point", lambda lat, lon: {
        "chlorophyll_mg_m3": None, "is_land_or_no_data": True,
        "timestamp": "t", "source": "test",
    })
    monkeypatch.setattr(copernicus_sst, "get_point", lambda lat, lon: {
        "temperature_c": None, "is_land_or_no_data": True,
        "timestamp": "t", "source": "test",
    })

    result = pfz.find_zones(10.0, 75.5, radius_km=50)

    assert result["available"] is True
    assert result["candidates_scanned"] == 0
    assert result["zones"] == []


def _install_cells(monkeypatch, cells: dict):
    """cells: {(lat, lon): (chlorophyll, sst)}; the candidate grid is exactly these."""
    monkeypatch.setattr(copernicus_chlorophyll, "is_available", lambda: True)
    monkeypatch.setattr(copernicus_sst, "is_available", lambda: True)
    monkeypatch.setattr(pfz, "_candidate_grid", lambda lat, lon, radius_km: list(cells))
    chl_fn, sst_fn = _grid_point({k: v[0] for k, v in cells.items()}, {k: v[1] for k, v in cells.items()})
    monkeypatch.setattr(copernicus_chlorophyll, "get_point", lambda lat, lon: chl_fn(lat, lon))
    monkeypatch.setattr(copernicus_sst, "get_point", lambda lat, lon: sst_fn(lat, lon))
    monkeypatch.setattr(copernicus_chlorophyll, "is_stale", lambda: False)


def test_each_zone_reports_its_distance(monkeypatch):
    _install_cells(monkeypatch, {(10.0, 76.0): (1.0, 27.0)})
    result = pfz.find_zones(10.0, 75.5, radius_km=120)
    # 0.5 deg of longitude at 10N: 111.195 km x cos(10 deg) x 0.5 = 54.75 km
    assert result["zones"][0]["distance_km"] == pytest.approx(54.75, abs=0.1)


def test_zones_rank_nearer_first_within_a_score(monkeypatch):
    near, far, poor = (10.0, 75.6), (10.0, 76.4), (10.0, 75.2)
    _install_cells(monkeypatch, {near: (1.0, 27.0), far: (3.0, 27.0), poor: (0.1, 20.0)})
    result = pfz.find_zones(10.0, 75.5, radius_km=120)
    assert [(z["latitude"], z["longitude"]) for z in result["zones"][:2]] == [near, far]
    assert (result["nearest_full_match"]["latitude"], result["nearest_full_match"]["longitude"]) == near


def test_nearest_full_match_is_none_when_no_cell_scores_two(monkeypatch):
    _install_cells(monkeypatch, {(10.0, 75.6): (1.0, 20.0), (10.0, 76.4): (3.0, 33.0)})
    result = pfz.find_zones(10.0, 75.5, radius_km=120)
    assert result["nearest_full_match"] is None
