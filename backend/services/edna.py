"""Where the ocean has been sampled *molecularly*, from OBIS.

Environmental DNA is not a new data source for this codebase — it is a facet of
one it already calls. OBIS tags every record whose dataset carries the Darwin
Core `DNADerivedData` extension, and `hasextensions=DNADerivedData` is a filter
on the same `/v3/statistics`, `/v3/checklist`, `/v3/dataset` and
`/v3/occurrence/grid` endpoints `biodiversity.py` already uses. So this module
adds no integration; it adds a *question* the platform could not previously ask.

**The map this produces is mostly empty, and that emptiness is the finding.**
Measured against the live API on 2026-08-16: 44,548,350 eDNA-flagged records
worldwide, and on the finest grid this module reports (precision 5, ~0.044 deg
cells) they occupy **1,475 cells on the entire planet** — 27,286 km2, or
**0.0075% of the ocean surface**. The molecular survey of the world ocean is
smaller than Belgium. Every other layer in this app is a field — SST, currents,
forecast grids — defined everywhere. This one is defined almost nowhere, and a
reader who has only ever seen the fields needs telling that the blank is real.

**The distribution is why the scale is logarithmic, and why that is not a
cosmetic choice.** In the same measurement the busiest precision-4 cell held
4,353,873 records and the quietest held 1 — better than six orders of magnitude
inside one layer. On a linear ramp the planet renders black with a single bright
pixel off Sydney, where the Australian Microbiome program has sequenced harder
than anywhere else on Earth. `scale` therefore rides with the response, the same
way `display_min`/`display_max` live in a forecast grid file, so the renderer and
the legend cannot disagree about what a colour means.

Three things this module refuses to let a caller assume:

**A detection is not a presence.** eDNA is shed material, not an animal. It
drifts on the same currents this platform renders, degrades over hours to days,
and is read through a PCR primer that amplifies some taxa far better than
others — then matched against a reference database that simply does not contain
most marine species. So a name here means "this sequence was recovered and
assigned", which is a claim about the water and the laboratory, not a sighting.

**An absence means even less than it does in OBIS.** `biodiversity.py` already
says absence is not evidence of absence for presence-only records. Here the
chain is longer: the organism must have shed DNA, the DNA must have survived to
the sampler, the primer must have amplified it, and a reference sequence must
have existed to name it. A gap can break at any of four links.

**Read counts are not abundance.** These records carry `organismQuantity` in
DNA sequence reads, which is the one quantitative field conventional occurrence
records lack — and it is a quantity of *sequences*, scaling with primer affinity,
copy number and cycle count as much as with biomass. It is not reported as an
abundance anywhere in this payload, and `records` throughout means
taxon-detections, not samples: one deeply sequenced water bottle can outweigh an
entire survey.
"""

from __future__ import annotations

import asyncio
import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from loguru import logger

API_ROOT = "https://api.obis.org/v3"
SOURCE_LABEL = "OBIS records carrying the Darwin Core DNADerivedData extension"
SOURCE_URL = "https://obis.org/"

# The OBIS filter that defines this whole module. A dataset carries the
# extension when it publishes sequence provenance alongside the occurrence, so
# this selects molecular records rather than a taxon or a method keyword.
_EXTENSION = "DNADerivedData"

_TIMEOUT = httpx.Timeout(60.0)

# Ray-finned fishes, the same taxon id `biodiversity.py` uses, so "fish" means
# the same thing on both sides of the eDNA/conventional split.
_FISH_TAXON_ID = 10194

# OBIS's grid precisions are GEOHASH levels, and geohash cells are not square
# at every level — each level adds five bits, split alternately between
# longitude and latitude, so odd levels come out square and even ones come out
# twice as wide as they are tall. Measured against the live API on 2026-08-16
# (global, no bbox), lon x lat, with the payload each level returns:
#   p=1   45.0     x 45.0        25 cells    3.4 KB
#   p=2   11.25    x  5.625     136 cells     22 KB
#   p=3    1.40625 x  1.40625   482 cells     91 KB
#   p=4    0.35156 x  0.17578  1006 cells    213 KB
#   p=5    0.04395 x  0.04395  1475 cells    348 KB
# An earlier version of this module derived the cell size from a single formula
# and reported 0.703125 deg at p=4 — wrong by 2x in one axis and 4x in the
# other, in a field the frontend legend quotes. Cell extents are therefore read
# off the returned polygons (`_bounds_of`) and the nominal size is derived the
# way geohash actually works, below.
#
# The whole planet is a small payload at every level, which is the point: there
# is no viewport-tiling problem to solve because there is barely any data.
MIN_PRECISION = 1
MAX_PRECISION = 5
DEFAULT_PRECISION = 3

# The precision the headline coverage figure is always computed at, whatever
# the caller asked to *draw*.
#
# "What fraction of the ocean has been sampled" has no single answer on a grid:
# a coarse cell credits one water bottle with everything around it. Measured
# live on 2026-08-16, the same 44.5M records cover 23.1% of the ocean at
# precision 2 and 0.0075% at precision 5 — a 3,000x swing produced entirely by
# cell size. Since the map draws a coarser grid when zoomed out, quoting the
# displayed grid's figure would show the most flattering number in the default
# view and shrink it as the reader looked closer, which is precisely backwards.
# The finest available grid is the least wrong estimate, so it is the only one
# reported as a headline.
REFERENCE_PRECISION = MAX_PRECISION


def cell_dimensions_deg(precision: int) -> tuple[float, float]:
    """Nominal (longitude, latitude) extent of a geohash cell at this precision.

    Five bits per level, longitude taking the first of each pair — which is why
    even levels are wide rectangles and odd levels are square.
    """
    bits = 5 * precision
    lon_bits = (bits + 1) // 2
    lat_bits = bits // 2
    return 360.0 / (2**lon_bits), 180.0 / (2**lat_bits)


# Surface area of the world ocean, for the one comparison that makes the
# coverage number mean something. A percentage of "the globe" would silently
# count continents as unsampled ocean.
OCEAN_AREA_KM2 = 361_900_000.0
EARTH_RADIUS_KM = 6371.0088

# OBIS publishes on a release cadence of weeks and this is a whole-planet
# aggregate, so a long cache costs nothing in freshness. It is also what keeps
# a map pan from re-issuing a 5-second upstream call.
_CACHE_TTL = timedelta(hours=24)
_POINT_CACHE_TTL = timedelta(hours=6)
_CACHE_MAX = 64
_KEY_DECIMALS = 2

# Species listed in a point checklist. As in `biodiversity.py`, the full list is
# an export rather than a page.
_CHECKLIST_LIMIT = 25
_DATASET_LIMIT = 5

DETECTION_NOTE = (
    "eDNA is shed genetic material, not an organism. It drifts on currents, degrades over "
    "hours to days, is amplified through primers that favour some taxa over others, and is "
    "named only if a reference sequence exists. A detection means a sequence was recovered "
    "and assigned here — not that the animal was here, and not that it was here now."
)

ABSENCE_NOTE = (
    "Absence means less here than in conventional records. For a taxon to be missing it is "
    "enough that it shed no DNA, that the DNA degraded before sampling, that the primer did "
    "not amplify it, or that no reference sequence exists to name it. Nothing in this "
    "response is evidence that a species is not present."
)

READS_NOTE = (
    "Record counts are taxon-detections, not samples or individuals. One deeply sequenced "
    "water sample yields thousands of records; a broad survey with shallow sequencing yields "
    "few. Where these datasets report a quantity it is in DNA sequence reads, which scale "
    "with primer affinity and PCR cycles as much as with biomass — it is not abundance."
)


class EdnaError(RuntimeError):
    """OBIS could not be queried, or answered with nothing usable."""


@dataclass
class _Entry:
    payload: dict[str, Any]
    stored_at: datetime
    ttl: timedelta


_cache: dict[tuple, _Entry] = {}
_lock = threading.Lock()


def _cached(key: tuple) -> dict[str, Any] | None:
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if datetime.now(timezone.utc) - entry.stored_at > entry.ttl:
            _cache.pop(key, None)
            return None
        return entry.payload


def _store(key: tuple, payload: dict[str, Any], ttl: timedelta) -> None:
    with _lock:
        _cache[key] = _Entry(payload=payload, stored_at=datetime.now(timezone.utc), ttl=ttl)
        if len(_cache) > _CACHE_MAX:
            oldest = min(_cache, key=lambda k: _cache[k].stored_at)
            _cache.pop(oldest, None)


async def _get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
    response = await client.get(f"{API_ROOT}{path}", params=params)
    response.raise_for_status()
    return response.json()


def _wkt_box(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> str:
    corners = [
        (min_lon, min_lat),
        (max_lon, min_lat),
        (max_lon, max_lat),
        (min_lon, max_lat),
        (min_lon, min_lat),
    ]
    return "POLYGON((" + ", ".join(f"{lon:.4f} {lat:.4f}" for lon, lat in corners) + "))"


def _cell_area_km2(min_lat: float, max_lat: float, lon_span_deg: float) -> float:
    """Area of one grid cell on a sphere.

    A latitude band, not a rectangle: `R^2 * dlon * (sin(lat2) - sin(lat1))`.
    Treating cells as equal-area is the obvious shortcut and it inflates polar
    coverage badly — a 0.7 deg cell at 70 degN is a third the area of one at the
    equator, and the high-latitude programs are exactly where a lot of this
    sampling happens.
    """
    band = math.sin(math.radians(max_lat)) - math.sin(math.radians(min_lat))
    return (EARTH_RADIUS_KM**2) * math.radians(lon_span_deg) * abs(band)


def _bounds_of(feature: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """West, south, east, north of a grid cell polygon.

    OBIS returns each cell as a closed five-vertex ring rather than a bbox, so
    the extent is taken from the coordinates instead of being derived from the
    precision — a cell at the edge of a requested geometry can be clipped, and
    reconstructing it from the nominal cell size would then draw it wrong.
    """
    geometry = feature.get("geometry") or {}
    if geometry.get("type") != "Polygon":
        return None
    rings = geometry.get("coordinates") or []
    if not rings or not rings[0]:
        return None
    lons = [float(point[0]) for point in rings[0]]
    lats = [float(point[1]) for point in rings[0]]
    return min(lons), min(lats), max(lons), max(lats)


async def coverage(
    precision: int = DEFAULT_PRECISION,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Gridded eDNA sampling effort — one upstream call.

    `bbox` is (south, west, north, east) and is optional because the global
    payload is small enough not to need one; it exists so a caller looking at a
    region does not have to filter a planet client-side.
    """
    if not MIN_PRECISION <= precision <= MAX_PRECISION:
        raise EdnaError(
            f"precision must be between {MIN_PRECISION} and {MAX_PRECISION}; got {precision}"
        )

    key = ("coverage", precision, bbox)
    hit = _cached(key)
    if hit is not None:
        return hit

    params: dict[str, Any] = {"hasextensions": _EXTENSION}
    if bbox is not None:
        south, west, north, east = bbox
        params["geometry"] = _wkt_box(west, south, east, north)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            grid = await _get(client, f"/occurrence/grid/{precision}", params)
    except httpx.HTTPStatusError as exc:
        raise EdnaError(
            f"OBIS returned {exc.response.status_code} for the eDNA coverage grid"
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning(f"OBIS eDNA grid request failed: {exc}")
        raise EdnaError(f"OBIS could not be reached: {exc}") from exc

    cells: list[dict[str, Any]] = []
    total_records = 0
    sampled_area_km2 = 0.0

    for feature in (grid or {}).get("features") or []:
        bounds = _bounds_of(feature)
        if bounds is None:
            continue
        west, south, east, north = bounds
        records = int((feature.get("properties") or {}).get("n") or 0)
        if records <= 0:
            continue
        area = _cell_area_km2(south, north, east - west)
        total_records += records
        sampled_area_km2 += area
        cells.append(
            {
                "west": round(west, 6),
                "south": round(south, 6),
                "east": round(east, 6),
                "north": round(north, 6),
                "records": records,
                "area_km2": round(area),
                # Records per unit area, because cells are not equal-area and
                # two raw counts at different latitudes are not comparable —
                # the same reason `biodiversity.py` quotes per 1000 km2.
                "records_per_1000_km2": round(records / area * 1000, 1) if area else None,
            }
        )

    counts = [cell["records"] for cell in cells]
    max_records = max(counts) if counts else 0
    min_records = min(counts) if counts else 0

    cell_lon_deg, cell_lat_deg = cell_dimensions_deg(precision)

    payload: dict[str, Any] = {
        "precision": precision,
        "cell_lon_deg": cell_lon_deg,
        "cell_lat_deg": cell_lat_deg,
        "bbox": list(bbox) if bbox is not None else None,
        "occupied_cells": len(cells),
        "records": total_records,
        # The headline, and the reason this layer exists. An upper bound by
        # construction: a cell counts as sampled on a single record, and a
        # record is one detection in one bottle of water — not a survey of the
        # ~5,000 km2 the cell actually covers.
        "sampled_area_km2": round(sampled_area_km2),
        # Deliberately absent for a bbox request rather than computed: the area
        # sampled inside a small box over the area of the whole ocean is a
        # ratio between two unrelated things, and it renders as a plausible
        # near-zero percentage instead of as the nonsense it is.
        "sampled_fraction_of_ocean": (
            round(sampled_area_km2 / OCEAN_AREA_KM2, 6) if bbox is None else None
        ),
        "ocean_area_km2": OCEAN_AREA_KM2,
        # The figure a UI should quote — see REFERENCE_PRECISION. Filled in
        # below for a global request; None for a bbox, which has no honest
        # global fraction to report.
        "reference_coverage": None,
        # Carried so the renderer and the legend cannot disagree about what a
        # colour means, the same contract the forecast grids hold. Logarithmic
        # is not a preference: the occupied cells span six orders of magnitude,
        # and a linear ramp paints the planet black around one bright pixel.
        "scale": {
            "type": "log10",
            "min_records": min_records,
            "max_records": max_records,
        },
        "detection_note": DETECTION_NOTE,
        "absence_note": ABSENCE_NOTE,
        "counting_note": READS_NOTE,
        "limits": [
            "Sampling effort, not biodiversity and not detection probability — a bright cell "
            "is a place someone sequenced hard, most often near a marine institute.",
            "A cell is drawn if it holds one record; the coloured area is a ceiling on what "
            "was actually sampled, never a claim the cell was surveyed.",
            "Counts are taxon-detections. A microbial 16S dataset returns thousands of "
            "records per sample and a fish survey a handful, so the two are not comparable "
            "on this scale.",
            "OBIS holds the eDNA studies that were published to OBIS. National programmes "
            "and sequence archives that never flowed here are absent rather than zero.",
            "Sampled area depends entirely on cell size — the same records cover 23% of the "
            "ocean on a 11.25 deg grid and 0.0075% on a 0.04 deg one. `reference_coverage` is "
            "the finest-grid figure and is the only one worth quoting; this level's own "
            "`sampled_area_km2` describes what is drawn, not what was sampled.",
        ],
        "cells": cells,
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }

    if bbox is None:
        if precision == REFERENCE_PRECISION:
            payload["reference_coverage"] = {
                "precision": precision,
                "occupied_cells": len(cells),
                "sampled_area_km2": payload["sampled_area_km2"],
                "sampled_fraction_of_ocean": payload["sampled_fraction_of_ocean"],
            }
        else:
            # One extra upstream call, cached for 24 hours like every other
            # precision — so this costs one request a day, not one per pan. It
            # cannot recurse: the call below takes the branch above.
            try:
                reference = await coverage(precision=REFERENCE_PRECISION)
            except EdnaError as exc:
                # A missing headline is not worth failing the layer for. The
                # cells are already assembled and are what gets drawn; the UI
                # renders no percentage rather than the displayed grid's.
                logger.warning(f"eDNA reference coverage unavailable: {exc}")
            else:
                payload["reference_coverage"] = {
                    "precision": REFERENCE_PRECISION,
                    "occupied_cells": reference["occupied_cells"],
                    "sampled_area_km2": reference["sampled_area_km2"],
                    "sampled_fraction_of_ocean": reference["sampled_fraction_of_ocean"],
                }

    _store(key, payload, _CACHE_TTL)
    return payload


def _species_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "scientific_name": record.get("scientificName"),
        "rank": record.get("taxonRank"),
        "records": record.get("records"),
        "kingdom": record.get("kingdom"),
        "phylum": record.get("phylum"),
        "class": record.get("class"),
        "family": record.get("family"),
    }


def _dataset_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": record.get("title"),
        "records": record.get("records"),
        "url": record.get("url"),
    }


async def at_point(
    latitude: float,
    longitude: float,
    radius_deg: float = 0.5,
    limit: int = _CHECKLIST_LIMIT,
) -> dict[str, Any]:
    """Molecular sampling in a box around one point, against the conventional total.

    The conventional count is fetched deliberately rather than being left to the
    caller. On its own "1,240 eDNA records here" is unreadable — a number that
    large sounds like saturation and is routinely a single sequencing run. Beside
    the box's total it becomes the thing worth knowing: what share of what is
    known about this water came from a sequencer rather than from a net.
    """
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise EdnaError(f"coordinate out of range: {latitude}, {longitude}")
    if not 0.0 < radius_deg <= 5.0:
        raise EdnaError(f"radius must be between 0 and 5 degrees; got {radius_deg}")

    key = ("point", round(latitude, _KEY_DECIMALS), round(longitude, _KEY_DECIMALS), radius_deg, limit)
    hit = _cached(key)
    if hit is not None:
        return hit

    min_lat = max(latitude - radius_deg, -90.0)
    max_lat = min(latitude + radius_deg, 90.0)
    min_lon = max(longitude - radius_deg, -180.0)
    max_lon = min(longitude + radius_deg, 180.0)
    geometry = _wkt_box(min_lon, min_lat, max_lon, max_lat)

    molecular = {"hasextensions": _EXTENSION, "geometry": geometry}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            edna_stats, all_stats, fish_stats, checklist, datasets = await asyncio.gather(
                _get(client, "/statistics", dict(molecular)),
                _get(client, "/statistics", {"geometry": geometry}),
                _get(client, "/statistics", {**molecular, "taxonid": _FISH_TAXON_ID}),
                _get(client, "/checklist", {**molecular, "size": limit}),
                _get(client, "/dataset", {**molecular, "size": _DATASET_LIMIT}),
            )
    except httpx.HTTPStatusError as exc:
        raise EdnaError(f"OBIS returned {exc.response.status_code} for this area") from exc
    except httpx.HTTPError as exc:
        logger.warning(f"OBIS eDNA point request failed: {exc}")
        raise EdnaError(f"OBIS could not be reached: {exc}") from exc

    edna_records = int((edna_stats or {}).get("records") or 0)
    all_records = int((all_stats or {}).get("records") or 0)
    year_range = (edna_stats or {}).get("yearrange") or []

    results = ((checklist or {}).get("results") or [])[:limit]
    dataset_results = ((datasets or {}).get("results") or [])[:_DATASET_LIMIT]

    payload: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "search_box": {
            "min_longitude": round(min_lon, 4),
            "min_latitude": round(min_lat, 4),
            "max_longitude": round(max_lon, 4),
            "max_latitude": round(max_lat, 4),
            "radius_deg": radius_deg,
        },
        "totals": {
            "edna_records": edna_records,
            "edna_species": int((edna_stats or {}).get("species") or 0),
            "edna_datasets": int((edna_stats or {}).get("datasets") or 0),
            "edna_fish_species": int((fish_stats or {}).get("species") or 0),
            "all_records": all_records,
            # The share of what is recorded here that is molecular. None rather
            # than 0 when the box is empty: "0% molecular" reads as a finding
            # about the sampling method, when the truth is nobody sampled here
            # at all.
            "molecular_share": (
                round(edna_records / all_records, 4) if all_records else None
            ),
            "first_year": year_range[0] if len(year_range) == 2 else None,
            "last_year": year_range[1] if len(year_range) == 2 else None,
        },
        "species": [_species_row(entry) for entry in results],
        "species_truncated": int((checklist or {}).get("total") or 0) > len(results),
        "datasets": [_dataset_row(entry) for entry in dataset_results],
        "datasets_total": int((datasets or {}).get("total") or 0),
        "detection_note": DETECTION_NOTE,
        "absence_note": ABSENCE_NOTE,
        "counting_note": READS_NOTE,
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
    }

    if edna_records == 0:
        # Distinguished from a failure, and further distinguished from "no eDNA
        # here" — the overwhelmingly common case is water nobody has ever put a
        # sequencer near, which the coverage grid makes visible at a glance.
        payload["empty_reason"] = (
            "No molecular records in this box. Almost all of the ocean has never been "
            "sampled for eDNA — this describes where sequencing has happened, not what "
            "lives here."
            if all_records == 0
            else (
                f"No molecular records in this box, though OBIS holds {all_records:,} "
                "conventional records here. This water has been surveyed, but not sequenced."
            )
        )

    _store(key, payload, _POINT_CACHE_TTL)
    return payload
