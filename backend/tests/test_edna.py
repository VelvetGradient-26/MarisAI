"""eDNA sampling coverage from OBIS.

Nothing here calls OBIS. What is pinned is the set of properties that fail
*silently* — a coverage map with any of these wrong still renders a plausible
scattering of violet cells over a plausible ocean:

  * the cell geometry, which the frontend legend quotes and which was wrong in
    the first draft of this module (a single formula, where OBIS actually
    returns geohash cells that are twice as wide as they are tall at even
    precisions);
  * the area arithmetic, where treating cells as equal-area inflates exactly
    the high-latitude programmes that do a lot of this sampling;
  * and the empty cases, where "nobody has sequenced this water" and "OBIS is
    down" and "this water was surveyed but never sequenced" are three different
    answers that must not collapse into one another.
"""

from __future__ import annotations

import asyncio

import pytest

from services import edna

# Longitude x latitude extents read off the polygons the live API returned on
# 2026-08-16, one grid request per precision. These are the ground truth the
# derivation has to reproduce: geohash adds five bits per level, longitude
# taking the first of each pair, so odd levels are square and even levels are
# wide rectangles. A formula that "looks right" and is off by 2x in one axis is
# invisible on a map and wrong in the legend.
MEASURED_CELL_DIMS = {
    1: (45.0, 45.0),
    2: (11.25, 5.625),
    3: (1.40625, 1.40625),
    4: (0.3515625, 0.17578125),
    5: (0.0439453125, 0.0439453125),
}


@pytest.mark.parametrize("precision,expected", sorted(MEASURED_CELL_DIMS.items()))
def test_cell_dimensions_match_what_obis_returns(precision, expected):
    lon_deg, lat_deg = edna.cell_dimensions_deg(precision)
    assert (lon_deg, lat_deg) == pytest.approx(expected)


def test_even_precisions_are_not_square():
    """The property the first draft got wrong, stated on its own.

    If this ever starts passing by accident because both axes were made equal,
    the legend goes back to quoting a cell size that is nothing like the cell
    drawn on the map.
    """
    lon_deg, lat_deg = edna.cell_dimensions_deg(4)
    assert lon_deg == pytest.approx(2 * lat_deg)


def test_bounds_come_from_the_polygon_not_the_precision():
    """A cell clipped by a requested geometry keeps its real extent.

    Reconstructing a cell from the nominal size would draw a clipped cell at
    full width, painting water that was never in the response.
    """
    feature = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[150.0, -35.0], [151.0, -35.0], [151.0, -34.5], [150.0, -34.5], [150.0, -35.0]]
            ],
        }
    }
    assert edna._bounds_of(feature) == (150.0, -35.0, 151.0, -34.5)


def test_a_non_polygon_cell_is_skipped_rather_than_guessed():
    assert edna._bounds_of({"geometry": {"type": "Point", "coordinates": [1.0, 2.0]}}) is None
    assert edna._bounds_of({}) is None


def test_cell_area_shrinks_toward_the_poles():
    """Cells are latitude bands, not rectangles.

    A 0.7 deg cell at 70 degN covers roughly a third of the area of one at the
    equator. Treating them as equal would credit the polar programmes — which
    are a real share of this dataset — with several times the ocean they cover,
    directly inflating the headline coverage figure.
    """
    equatorial = edna._cell_area_km2(0.0, 0.703125, 0.703125)
    polar = edna._cell_area_km2(69.6, 70.3, 0.703125)
    assert polar < equatorial / 2


def _grid_response(cells):
    return {
        "features": [
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [west, south],
                            [east, south],
                            [east, north],
                            [west, north],
                            [west, south],
                        ]
                    ],
                },
                "properties": {"n": n},
            }
            for west, south, east, north, n in cells
        ]
    }


def _coverage(monkeypatch, cells, precision=3):
    async def fake_get(client, path, params):
        # Either the grid being drawn or the fixed reference grid the headline
        # figure is always measured on.
        assert path in (
            f"/occurrence/grid/{precision}",
            f"/occurrence/grid/{edna.REFERENCE_PRECISION}",
        )
        # The filter that defines this whole module. Losing it turns the layer
        # into a map of all OBIS sampling, which looks similar and means
        # something completely different.
        assert params["hasextensions"] == "DNADerivedData"
        return _grid_response(cells)

    monkeypatch.setattr(edna, "_get", fake_get)
    edna._cache.clear()
    return asyncio.run(edna.coverage(precision=precision))


def test_coverage_sums_area_and_reports_it_against_the_ocean(monkeypatch):
    payload = _coverage(
        monkeypatch,
        [
            (150.0, -35.0, 151.40625, -33.59375, 4_353_873),
            (72.0, 15.0, 73.40625, 16.40625, 1),
        ],
    )

    assert payload["occupied_cells"] == 2
    assert payload["records"] == 4_353_874
    assert payload["sampled_area_km2"] == sum(cell["area_km2"] for cell in payload["cells"])
    # The headline is a fraction of the *ocean*, not of the globe — counting
    # continents as unsampled ocean would quietly halve it.
    assert payload["ocean_area_km2"] == edna.OCEAN_AREA_KM2
    assert 0.0 < payload["sampled_fraction_of_ocean"] < 1.0


def test_the_headline_fraction_is_measured_on_the_finest_grid(monkeypatch):
    """The number a reader sees must not depend on how far they zoomed out.

    Cell size dominates this figure: measured live, the same 44.5M records
    cover 23.1% of the ocean at precision 2 and 0.0075% at precision 5. The map
    draws a coarser grid when zoomed out, so quoting the drawn grid would show
    the most flattering number in the default view and shrink it as the reader
    looked closer.
    """
    seen = []

    async def fake_get(client, path, params):
        seen.append(path)
        if path.endswith(str(edna.REFERENCE_PRECISION)):
            # A fine grid: one small cell.
            return _grid_response([(150.0, -35.0, 150.04394, -34.95606, 12)])
        # A coarse grid: the same records over a far larger cell.
        return _grid_response([(146.25, -39.375, 157.5, -33.75, 12)])

    monkeypatch.setattr(edna, "_get", fake_get)
    edna._cache.clear()
    payload = asyncio.run(edna.coverage(precision=2))

    reference = payload["reference_coverage"]
    assert reference is not None
    assert reference["precision"] == edna.REFERENCE_PRECISION
    # The drawn grid's own area is far larger, and is exactly what must not be
    # quoted as coverage.
    assert reference["sampled_area_km2"] < payload["sampled_area_km2"]
    assert (
        reference["sampled_fraction_of_ocean"] < payload["sampled_fraction_of_ocean"]
    )
    assert seen == ["/occurrence/grid/2", f"/occurrence/grid/{edna.REFERENCE_PRECISION}"]


def test_the_reference_grid_does_not_recurse(monkeypatch):
    calls = []

    async def fake_get(client, path, params):
        calls.append(path)
        return _grid_response([(150.0, -35.0, 150.04394, -34.95606, 12)])

    monkeypatch.setattr(edna, "_get", fake_get)
    edna._cache.clear()
    payload = asyncio.run(edna.coverage(precision=edna.REFERENCE_PRECISION))
    assert len(calls) == 1
    assert payload["reference_coverage"]["precision"] == edna.REFERENCE_PRECISION


def test_a_missing_reference_does_not_fail_the_layer(monkeypatch):
    """The cells are what gets drawn; the headline is a caption on them. Losing
    the caption is not worth losing the map."""

    async def fake_get(client, path, params):
        if path.endswith(str(edna.REFERENCE_PRECISION)):
            raise edna.EdnaError("upstream refused the fine grid")
        return _grid_response([(146.25, -39.375, 157.5, -33.75, 12)])

    monkeypatch.setattr(edna, "_get", fake_get)
    edna._cache.clear()
    payload = asyncio.run(edna.coverage(precision=2))
    assert payload["reference_coverage"] is None
    assert payload["occupied_cells"] == 1


def test_a_bbox_request_reports_no_whole_ocean_fraction(monkeypatch):
    """Sampled area inside a small box over the area of the whole ocean is a
    ratio between two unrelated things — and it renders as a plausible tiny
    percentage rather than as the nonsense it is."""

    async def fake_get(client, path, params):
        assert "geometry" in params
        return _grid_response([(72.0, 15.0, 73.40625, 16.40625, 40)])

    monkeypatch.setattr(edna, "_get", fake_get)
    edna._cache.clear()
    payload = asyncio.run(edna.coverage(precision=3, bbox=(5.0, 40.0, 30.0, 100.0)))
    assert payload["sampled_fraction_of_ocean"] is None
    assert payload["reference_coverage"] is None
    # The cells themselves are still real and still drawn.
    assert payload["occupied_cells"] == 1


def test_empty_cells_are_dropped_rather_than_drawn(monkeypatch):
    """A zero-record cell painted at the ramp's bottom colour asserts a sample
    that never happened — on this layer specifically, since the whole point is
    which water has been touched at all."""
    payload = _coverage(
        monkeypatch,
        [
            (150.0, -35.0, 151.40625, -33.59375, 12),
            (10.0, 10.0, 11.40625, 11.40625, 0),
        ],
    )
    assert payload["occupied_cells"] == 1
    assert all(cell["records"] > 0 for cell in payload["cells"])


def test_the_scale_rides_with_the_response(monkeypatch):
    """The renderer and the legend must not be able to disagree about what a
    colour means — the same contract the forecast grid files hold."""
    payload = _coverage(
        monkeypatch,
        [
            (150.0, -35.0, 151.40625, -33.59375, 4_353_873),
            (72.0, 15.0, 73.40625, 16.40625, 1),
        ],
    )
    assert payload["scale"]["min_records"] == 1
    assert payload["scale"]["max_records"] == 4_353_873
    # Logarithmic is not a styling preference here: these two cells differ by
    # more than six orders of magnitude and a linear ramp renders the smaller
    # one as black.
    assert payload["scale"]["type"] == "log10"


def test_coverage_carries_every_caveat(monkeypatch):
    payload = _coverage(monkeypatch, [(150.0, -35.0, 151.40625, -33.59375, 12)])
    assert payload["detection_note"] and payload["absence_note"] and payload["counting_note"]
    assert payload["limits"]


def test_an_out_of_range_precision_is_rejected():
    with pytest.raises(edna.EdnaError):
        asyncio.run(edna.coverage(precision=9))


def test_coverage_is_cached(monkeypatch):
    calls = []

    async def fake_get(client, path, params):
        calls.append(path)
        return _grid_response([(150.0, -35.0, 151.40625, -33.59375, 12)])

    monkeypatch.setattr(edna, "_get", fake_get)
    edna._cache.clear()

    # The drawn grid plus the reference grid the headline is measured on.
    asyncio.run(edna.coverage(precision=3))
    assert calls == ["/occurrence/grid/3", f"/occurrence/grid/{edna.REFERENCE_PRECISION}"]

    # A repeat is free.
    asyncio.run(edna.coverage(precision=3))
    assert len(calls) == 2

    # A different precision is a different question — but the reference grid is
    # cached like any other, so the extra headline call happens once a day
    # rather than once per zoom.
    asyncio.run(edna.coverage(precision=4))
    assert calls[-1] == "/occurrence/grid/4"
    assert len(calls) == 3


def _point(monkeypatch, *, edna_records, all_records, species=(), datasets=()):
    async def fake_get(client, path, params):
        molecular = params.get("hasextensions") == "DNADerivedData"
        if path == "/statistics":
            if not molecular:
                return {"records": all_records, "species": 40, "taxa": 44, "datasets": 9}
            if params.get("taxonid"):
                return {"records": 11, "species": 8, "taxa": 9, "datasets": 2}
            return {
                "records": edna_records,
                "species": len(species),
                "taxa": len(species),
                "datasets": len(datasets),
                "yearrange": [2012, 2024] if edna_records else [None, None],
            }
        if path == "/checklist":
            assert molecular
            return {
                "total": len(species),
                "results": [{"scientificName": name, "records": 3} for name in species],
            }
        assert path == "/dataset" and molecular
        return {
            "total": len(datasets),
            "results": [{"title": title, "records": 10} for title in datasets],
        }

    monkeypatch.setattr(edna, "_get", fake_get)
    edna._cache.clear()
    return asyncio.run(edna.at_point(-33.9, 151.2))


def test_molecular_share_is_reported_against_the_conventional_total(monkeypatch):
    """The number that makes the eDNA count readable.

    "8,814,299 molecular records here" sounds like saturation and is one
    sequencing programme. Beside the box's total it becomes the real finding:
    what share of what is known about this water came from a sequencer.
    """
    payload = _point(
        monkeypatch,
        edna_records=8_814_299,
        all_records=10_233_740,
        species=("Candidatus Pelagibacter", "Syndiniales"),
        datasets=("Australian Microbiome 16S",),
    )
    assert payload["totals"]["molecular_share"] == pytest.approx(0.8613, abs=1e-4)
    assert payload["totals"]["edna_records"] == 8_814_299
    assert len(payload["species"]) == 2
    assert payload["datasets"][0]["title"] == "Australian Microbiome 16S"


def test_an_unsampled_box_has_no_share_rather_than_zero(monkeypatch):
    """`0% molecular` reads as a finding about method choice. The truth is that
    nobody sampled the box at all, which is a statement about a missing
    denominator, so the field is absent rather than zero."""
    payload = _point(monkeypatch, edna_records=0, all_records=0)
    assert payload["totals"]["molecular_share"] is None
    assert "never been sampled" in payload["empty_reason"]


def test_surveyed_but_not_sequenced_is_its_own_answer(monkeypatch):
    """The Arabian Sea case, measured live: 205 conventional records and zero
    molecular ones. That is a different statement from untouched water, and it
    is the one a reader most needs — it says the gap is the method, not the
    effort."""
    payload = _point(monkeypatch, edna_records=0, all_records=205)
    assert payload["totals"]["molecular_share"] == 0.0
    assert "not sequenced" in payload["empty_reason"]
    assert "205" in payload["empty_reason"]


def test_a_point_report_carries_every_caveat(monkeypatch):
    payload = _point(monkeypatch, edna_records=12, all_records=100, species=("Sardina pilchardus",))
    assert payload["detection_note"] and payload["absence_note"] and payload["counting_note"]


def test_the_point_geometry_is_a_closed_polygon():
    wkt = edna._wkt_box(75.0, 9.5, 76.0, 10.5)
    assert wkt.startswith("POLYGON((") and wkt.endswith("))")
    corners = wkt[len("POLYGON((") : -2].split(", ")
    assert len(corners) == 5 and corners[0] == corners[-1]


def test_an_out_of_range_coordinate_is_rejected():
    with pytest.raises(edna.EdnaError):
        asyncio.run(edna.at_point(120.0, 0.0))
