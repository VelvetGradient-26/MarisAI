"""Proximity checks against maritime boundaries and protected areas.

A curated, in-code registry: India's EEZ (mainland and the Andaman & Nicobar
Islands, each its own zone), the India-Sri Lanka International Maritime
Boundary Line (IMBL), and a hand-picked list of named Marine Protected Areas.
Same convention as `services/ports.py`'s port list and
`services/download/registry.py`: static configuration belongs in code, not a
database table, and pure local computation means this works even when every
external provider is down — `check()` touches no network at all, ever.

**The EEZ polygons and the IMBL are now real, sourced geometry — this was a
hand-sketched approximation until 2026-08-24.** Both come from Marine Regions
(marineregions.org, the standard maritime-boundary gazetteer), fetched live
via its public WFS:

- **EEZ**: `MarineRegions:eez`, MRGID 8480 ("Indian Exclusive Economic Zone")
  and MRGID 8333 ("Indian Exclusive Economic Zone (Andaman and Nicobar
  Islands)") — two separate zones in Marine Regions' own data, not a
  modelling choice made here. Simplified from ~54,700 / ~6,500 vertices to
  ~1,510 / ~26 (`shapely.simplify`, tolerance 0.05°, `preserve_topology=True`)
  for a coordinate file that stays a few hundred KB rather than several MB;
  measured area distortion is +0.28% (mainland) and -0.01% (Andaman &
  Nicobar) — negligible next to a chat answer's actual precision needs.
  Stored in `geo_data/india_eez.json`, loaded once at import.
- **IMBL**: `MarineRegions:eez_boundaries`, the four segments tagged
  `line_type="Treaty"` between Sri Lanka and India (line IDs 1306/1307/1310/
  1311) — these *are* the 1974 Palk Strait Agreement and 1976 extension
  coordinates, not a public-description sketch. Small enough (25 points) to
  keep as a literal below, ordered north-to-south: the Bay of Bengal
  extension north of Sri Lanka, through Palk Strait, down the Gulf of Mannar,
  to the short final segment near the India-Sri Lanka-Maldives tripoint.

**One finding from switching to the real polygon is worth stating rather than
quietly absorbing**: a point right around Rameswaram/Adam's Bridge
(~79.2-79.4°E, 9.16-9.33°N) reads as **outside** the mainland EEZ polygon,
because Marine Regions' `eez` layer carries an interior exclusion there —
land/shoal, the same kind of hole the layer cuts for every river delta and
near-shore island along the coast (817 such holes nationwide; this module
keeps the 137 with area >= 0.0005 deg^2 and drops the rest as too small to
matter for a point check). The old hand-sketched polygon had no concept of
an interior exclusion at all and called every nearshore point "inside the
EEZ" uniformly. This is not evidence of a different legal regime for Palk
Strait specifically — most of the strait's open water tests `True` — it is
one real, mapped exclusion at one real place, which is exactly the kind of
detail a 17-point coastline sketch structurally cannot represent. Either way,
`india_sri_lanka_imbl`'s distance-to-boundary answer is unaffected by which
side of this particular hole a point falls on.

**Marine Protected Areas remain a hand-curated list, not WDPA
(protectedplanet.net).** Its API needs a registered key
(`api.protectedplanet.net/v3/...` returns 401 unauthenticated, checked
2026-08-24) and its bulk shapefile release is not a plain scriptable download
either. Expanded here with five more well-documented sites (each verified
against its own published coordinates) rather than left at the original four
— including, notably, the first Andaman & Nicobar entries, since the
registry previously had zero island coverage to go with its zero island EEZ
coverage. Still a small box around each site's published centre, not a
surveyed footprint; a real WDPA integration is the next step and needs that
key.

Good enough to demo "am I near the Sri Lanka boundary" or "is this inside
India's EEZ" at real-boundary accuracy; not a substitute for an official
chart before anyone actually sails on it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, MultiPolygon, Point, Polygon

EARTH_RADIUS_KM = 6371.0088

# Cells within this distance of a boundary are flagged as "near" rather than
# merely "outside" — the useful warning for a vessel, not a binary in/out.
PROXIMITY_THRESHOLD_KM = 20.0

ACCURACY_NOTE = (
    "EEZ and boundary geometry are from Marine Regions (marineregions.org) and "
    "the 1974/1976 India-Sri Lanka treaty line. Marine Protected Areas remain a "
    "hand-curated list of named sites, not WDPA (its API needs a registered "
    "key) — each is a small box around its published centre, not a surveyed "
    "footprint. Do not use any of this for actual navigation."
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


# --------------------------------------------------------------------------
# India's EEZ zones — real geometry, see the module docstring.
# --------------------------------------------------------------------------

_GEO_DATA_DIR = Path(__file__).parent / "geo_data"


def _polygon_from_zone(zone: list[dict[str, Any]]) -> Polygon | MultiPolygon:
    """`zone` is a list of `{"exterior": [...], "holes": [[...], ...]}`
    entries — a real multipolygon, not a flat list of outer rings, because
    the source data's interior rings (land/shoal exclusions) are real and
    dropping them would misrepresent water as excluded EEZ or vice versa.
    """
    polygons = [Polygon(entry["exterior"], entry["holes"]) for entry in zone]
    return polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)


with (_GEO_DATA_DIR / "india_eez.json").open() as _eez_file:
    _EEZ_DATA: dict[str, Any] = json.load(_eez_file)

INDIA_EEZ_MAINLAND = _polygon_from_zone(_EEZ_DATA["mainland"])
INDIA_EEZ_ANDAMAN_NICOBAR = _polygon_from_zone(_EEZ_DATA["andaman_and_nicobar"])
EEZ_SOURCE = _EEZ_DATA["source"]


# --------------------------------------------------------------------------
# India-Sri Lanka International Maritime Boundary Line — the treaty coordinates.
# --------------------------------------------------------------------------
IMBL_INDIA_SRI_LANKA = LineString(
    [
        (83.36667, 11.44333),
        (82.40667, 11.26667),
        (81.93333, 11.045),
        (81.04167, 10.695),
        (80.76667, 10.55),
        (80.15833, 10.14),
        (80.08333, 10.09667),
        (80.05, 10.08333),
        (79.58333, 9.95),
        (79.37667, 9.66917),
        (79.51167, 9.36333),
        (79.53333, 9.21667),
        (79.53333, 9.1),
        (79.52167, 9.0),
        (79.48833, 8.89667),
        (79.30333, 8.66667),
        (79.21667, 8.62),
        (79.07833, 8.52),
        (78.92333, 8.37),
        (78.895, 8.20333),
        (78.76167, 7.58833),
        (78.64667, 7.35),
        (78.20333, 6.51333),
        (77.845, 5.89833),
        (77.17667, 5.0),
        (77.02333, 4.79),
    ]
)

IMBL_SOURCE = (
    "Marine Regions (marineregions.org) eez_boundaries, line_type=Treaty, "
    "line IDs 1306/1307/1310/1311 — the 1974 Palk Strait Agreement and 1976 "
    "extension coordinates between India and Sri Lanka, fetched via WFS 2026-08-24."
)


# --------------------------------------------------------------------------
# Marine Protected Areas — small boxes around each site's published centre.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProtectedArea:
    name: str
    state: str
    polygon: Polygon


def _box(lat: float, lon: float, half_deg: float) -> Polygon:
    return Polygon(
        [
            (lon - half_deg, lat - half_deg),
            (lon + half_deg, lat - half_deg),
            (lon + half_deg, lat + half_deg),
            (lon - half_deg, lat + half_deg),
        ]
    )


PROTECTED_AREAS: list[ProtectedArea] = [
    ProtectedArea("Gulf of Mannar Marine National Park", "Tamil Nadu", _box(9.05, 79.05, 0.20)),
    ProtectedArea("Gulf of Kutch Marine National Park", "Gujarat", _box(22.45, 69.30, 0.25)),
    ProtectedArea("Malvan Marine Sanctuary", "Maharashtra", _box(16.03, 73.46, 0.08)),
    ProtectedArea("Gahirmatha Marine Sanctuary", "Odisha", _box(20.70, 87.00, 0.20)),
    # Added 2026-08-24, verified against each site's own Wikipedia infobox
    # coordinates — the first island coverage this registry has ever had,
    # matching the EEZ fix above rather than leaving Andaman & Nicobar
    # represented in one and not the other.
    ProtectedArea(
        "Mahatma Gandhi Marine National Park", "Andaman and Nicobar Islands", _box(11.53, 92.60, 0.15)
    ),
    ProtectedArea(
        "Rani Jhansi Marine National Park", "Andaman and Nicobar Islands", _box(11.783, 92.667, 0.15)
    ),
    ProtectedArea("Bhitarkanika National Park", "Odisha", _box(20.750, 87.000, 0.12)),
    ProtectedArea("Sundarbans National Park", "West Bengal", _box(21.838, 88.885, 0.30)),
    ProtectedArea(
        "Point Calimere Wildlife and Bird Sanctuary", "Tamil Nadu", _box(10.31, 79.86, 0.05)
    ),
]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def check(latitude: float, longitude: float) -> dict[str, Any]:
    """Everything this registry knows about one coordinate.

    Never raises: this is pure local geometry, so there is no failure mode
    to report other than "the point does not fall near anything registered."
    """
    point = Point(longitude, latitude)

    # `covers` rather than `contains`: a point exactly on a polygon's own
    # boundary ring must read as inside, not fall into the gap `contains`
    # leaves on its own edge.
    inside_mainland = INDIA_EEZ_MAINLAND.covers(point)
    inside_andaman = INDIA_EEZ_ANDAMAN_NICOBAR.covers(point)
    if inside_mainland:
        eez_zone, eez_distance_km, eez_nearest_zone = "mainland", 0.0, "mainland"
    elif inside_andaman:
        eez_zone, eez_distance_km, eez_nearest_zone = "andaman_and_nicobar", 0.0, "andaman_and_nicobar"
    else:
        eez_zone = None
        # `.boundary` rather than `.exterior`: both zones carry interior
        # holes (land/shoal exclusions, see the module docstring), and a
        # point just outside one of those holes is nearer an interior ring
        # than the outer coastline — `.exterior` alone would overstate the
        # distance for exactly the nearshore points this is most asked
        # about. The two zones are checked separately and the nearer one
        # reported, mirroring `nearest_point` below for the IMBL.
        mainland_pt = INDIA_EEZ_MAINLAND.boundary.interpolate(INDIA_EEZ_MAINLAND.boundary.project(point))
        andaman_pt = INDIA_EEZ_ANDAMAN_NICOBAR.boundary.interpolate(INDIA_EEZ_ANDAMAN_NICOBAR.boundary.project(point))
        mainland_km = _haversine_km(latitude, longitude, mainland_pt.y, mainland_pt.x)
        andaman_km = _haversine_km(latitude, longitude, andaman_pt.y, andaman_pt.x)
        if mainland_km <= andaman_km:
            eez_distance_km, eez_nearest_zone = mainland_km, "mainland"
        else:
            eez_distance_km, eez_nearest_zone = andaman_km, "andaman_and_nicobar"

    nearest_on_imbl = IMBL_INDIA_SRI_LANKA.interpolate(IMBL_INDIA_SRI_LANKA.project(point))
    imbl_distance_km = _haversine_km(latitude, longitude, nearest_on_imbl.y, nearest_on_imbl.x)

    areas: list[dict[str, Any]] = []
    for area in PROTECTED_AREAS:
        inside = area.polygon.covers(point)
        nearest = area.polygon.exterior.interpolate(area.polygon.exterior.project(point))
        distance_km = 0.0 if inside else _haversine_km(latitude, longitude, nearest.y, nearest.x)
        if inside or distance_km <= PROXIMITY_THRESHOLD_KM:
            min_lon, min_lat, max_lon, max_lat = area.polygon.bounds
            areas.append(
                {
                    "name": area.name,
                    "state": area.state,
                    "inside": inside,
                    "distance_km": round(distance_km, 1),
                    # Every entry here is a hand-drawn box (see `_box()`), so its
                    # bounds *are* its real geometry — not a simplification —
                    # which is what lets a caller draw it directly rather than
                    # re-deriving a shape from a name and a centre point.
                    "bounds": {
                        "south": round(min_lat, 4),
                        "west": round(min_lon, 4),
                        "north": round(max_lat, 4),
                        "east": round(max_lon, 4),
                    },
                }
            )
    areas.sort(key=lambda entry: entry["distance_km"])

    return {
        "india_eez": {
            "inside": eez_zone is not None,
            "zone": eez_zone,
            "distance_km": round(eez_distance_km, 1),
            "near": eez_distance_km <= PROXIMITY_THRESHOLD_KM,
            "proximity_threshold_km": PROXIMITY_THRESHOLD_KM,
            # Which zone `distance_km` is measured to — always the zone
            # itself when inside; the nearer of the two when outside, since
            # they are geographically far apart (mainland/Lakshadweep vs.
            # Andaman & Nicobar) and only one is ever the relevant one.
            "nearest_zone": eez_nearest_zone,
            "coverage": (
                "Mainland India (including Lakshadweep's surrounding waters, "
                "which fall inside the mainland zone) and the Andaman & Nicobar "
                "Islands, as two separate EEZ zones."
            ),
            "source": EEZ_SOURCE,
        },
        "india_sri_lanka_imbl": {
            "distance_km": round(imbl_distance_km, 1),
            "near": imbl_distance_km <= PROXIMITY_THRESHOLD_KM,
            "proximity_threshold_km": PROXIMITY_THRESHOLD_KM,
            "source": IMBL_SOURCE,
            # The actual nearest point on the treaty line, not just its
            # distance — added so a caller can draw the segment from the query
            # point to the boundary rather than only stating a number.
            "nearest_point": {
                "latitude": round(nearest_on_imbl.y, 4),
                "longitude": round(nearest_on_imbl.x, 4),
            },
        },
        "nearby_protected_areas": areas,
        "note": ACCURACY_NOTE,
    }
