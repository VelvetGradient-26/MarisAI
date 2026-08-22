"""Proximity checks against maritime boundaries and protected areas.

A curated, in-code registry of reference geometries — the India EEZ (mainland
coastal waters only), the India-Sri Lanka International Maritime Boundary
Line (IMBL) through Palk Strait / Gulf of Mannar, and a handful of named
Marine Protected Areas. Same convention as `services/ports.py`'s port list
and `services/download/registry.py`: static configuration belongs in code,
not a database table, and pure local computation means this works even when
every external provider is down.

**These are approximate, illustrative geometries, not survey-grade nautical
charts.** The EEZ polygon is a coastline sketch offset seaward by a fixed
degree margin (not a true geodesic buffer), the IMBL is hand-placed from
public descriptions of the 1974/1976 India-Sri Lanka agreements rather than
the treaty's own coordinates, and it covers mainland coastal waters only —
the Andaman & Nicobar and Lakshadweep EEZs are not represented. Every
response says so, the same "coverage is genuinely uneven, say so" convention
`services/predictions.py` and `services/eddies.py` already follow. Good
enough to demo "am I near the Sri Lanka boundary" or "is this inside India's
EEZ" at the accuracy a chat answer needs; not a substitute for an official
chart before anyone actually sails on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Any

from shapely.geometry import LineString, Point, Polygon

EARTH_RADIUS_KM = 6371.0088

# Cells within this distance of a boundary are flagged as "near" rather than
# merely "outside" — the useful warning for a vessel, not a binary in/out.
PROXIMITY_THRESHOLD_KM = 20.0

ACCURACY_NOTE = (
    "Reference geometry only, hand-sketched from public descriptions — not a "
    "surveyed nautical chart. Do not use for actual navigation."
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


# --------------------------------------------------------------------------
# India EEZ (mainland coastal waters) — coastline sketch offset seaward.
# --------------------------------------------------------------------------
#
# Ordered north-to-south down the west coast, then south-to-north up the
# east coast: Gujarat/Pakistan border (Sir Creek) -> Kanyakumari -> the
# Bangladesh border near the Hooghly mouth. Each point is projected outward
# along the vector from a rough central-India reference point, which
# approximates "seaward" well enough for a peninsula without needing a real
# coastline dataset.
_COASTLINE: list[tuple[float, float]] = [
    (23.9, 68.2),   # Sir Creek, Gujarat-Pakistan border
    (22.5, 69.0),   # Kandla / Kutch
    (21.6, 69.6),   # Porbandar
    (20.7, 70.9),   # Diu
    (19.0, 72.8),   # Mumbai
    (17.0, 73.3),   # Ratnagiri
    (15.3, 73.8),   # Goa
    (12.9, 74.8),   # Mangalore
    (9.9, 76.2),    # Kochi
    (8.1, 77.5),    # Kanyakumari
    (8.8, 78.2),    # Tuticorin
    (9.3, 79.3),    # Rameswaram
    (13.1, 80.3),   # Chennai
    (17.7, 83.3),   # Visakhapatnam
    (19.8, 85.9),   # Puri
    (20.3, 86.7),   # Paradip
    (21.6, 88.9),   # Hooghly mouth, Bangladesh border
]

_CENTRAL_INDIA = (22.5, 79.0)
_EEZ_MARGIN_DEG = 4.5  # ~500 km, generously past the 200 nm (~370 km) limit


def _offshore_point(lat: float, lon: float) -> tuple[float, float]:
    dlat, dlon = lat - _CENTRAL_INDIA[0], lon - _CENTRAL_INDIA[1]
    length = sqrt(dlat**2 + dlon**2) or 1.0
    return (
        lat + dlat / length * _EEZ_MARGIN_DEG,
        lon + dlon / length * _EEZ_MARGIN_DEG,
    )


def _build_eez_polygon() -> Polygon:
    offshore = [_offshore_point(lat, lon) for lat, lon in _COASTLINE]
    ring = [(lon, lat) for lat, lon in _COASTLINE] + [
        (lon, lat) for lat, lon in reversed(offshore)
    ]
    return Polygon(ring)


INDIA_EEZ_MAINLAND = _build_eez_polygon()


# --------------------------------------------------------------------------
# India-Sri Lanka International Maritime Boundary Line
# --------------------------------------------------------------------------
#
# Hand-placed through Palk Strait and the Gulf of Mannar from public
# descriptions of the boundary agreements — not the treaty's own surveyed
# coordinates. This is the real-world case the feature exists for: straying
# across it is a well-known hazard for fishing vessels from both countries.
IMBL_INDIA_SRI_LANKA = LineString(
    [
        (80.13, 10.05),
        (79.87, 9.99),
        (79.52, 9.71),
        (79.19, 9.22),
        (78.88, 8.90),
        (78.22, 8.67),
        (77.70, 8.35),
    ]
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

    # `covers` rather than `contains`: a point exactly on the boundary ring
    # (a harbour sitting right on the coastline sketch) must read as inside,
    # not fall into the gap `contains` leaves on its own edge.
    inside_eez = INDIA_EEZ_MAINLAND.covers(point)

    nearest_on_imbl = IMBL_INDIA_SRI_LANKA.interpolate(
        IMBL_INDIA_SRI_LANKA.project(point)
    )
    imbl_distance_km = _haversine_km(latitude, longitude, nearest_on_imbl.y, nearest_on_imbl.x)

    areas: list[dict[str, Any]] = []
    for area in PROTECTED_AREAS:
        inside = area.polygon.covers(point)
        nearest = area.polygon.exterior.interpolate(area.polygon.exterior.project(point))
        distance_km = 0.0 if inside else _haversine_km(latitude, longitude, nearest.y, nearest.x)
        if inside or distance_km <= PROXIMITY_THRESHOLD_KM:
            areas.append(
                {
                    "name": area.name,
                    "state": area.state,
                    "inside": inside,
                    "distance_km": round(distance_km, 1),
                }
            )
    areas.sort(key=lambda entry: entry["distance_km"])

    return {
        "india_eez": {
            "inside": inside_eez,
            "coverage": "mainland coastal waters only, not Andaman & Nicobar or Lakshadweep",
        },
        "india_sri_lanka_imbl": {
            "distance_km": round(imbl_distance_km, 1),
            "near": imbl_distance_km <= PROXIMITY_THRESHOLD_KM,
            "proximity_threshold_km": PROXIMITY_THRESHOLD_KM,
        },
        "nearby_protected_areas": areas,
        "note": ACCURACY_NOTE,
    }
