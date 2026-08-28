"""Potential Fishing Zone screening: "where near here looks favourable".

`services/predictions.py::habitat_point` already answers "how suitable is
species X here" from a trained model. This answers a different question —
"which nearby cells look best right now" — which is what the PS2 example
query ("where is the nearest Potential Fishing Zone today?") actually asks,
and it needs to scan many candidate points rather than score one.

**This is a heuristic screening aid, not a validated PFZ model**, and every
response says so — the same posture `services/eddies.py` and
`services/upwelling.py` take toward their own detectors. INCOIS's own
operational PFZ advisories are built from validated chlorophyll-front and
SST-front detection tuned against known catch data; this composes the two
raw fields with a documented, simple rule (chlorophyll above the local
sample's own median, inside a favourable SST band) so it stays fast enough
to run inside one chat turn and honest about being a proxy.

**Why this can run inside a chat turn at all.** Both fields it reads are
already resident, cached, global grids —
`services.copernicus_sst.get_point` and
`services.copernicus_chlorophyll.get_point` — so scanning a few dozen
candidate cells costs a few dozen array lookups, not a few dozen network
fetches.
"""

from __future__ import annotations

from math import cos, radians
from typing import Any

from services import copernicus_chlorophyll, copernicus_sst

# Tuna and other pelagic species are generally found in this band; this is a
# broad screening range, not a species-specific niche.
_FAVOURABLE_SST_MIN_C = 24.0
_FAVOURABLE_SST_MAX_C = 30.0

# Degrees between candidate cells. ~0.5deg (~55km) is coarser than the
# 0.25deg chlorophyll grid so neighbouring candidates are not near-duplicates
# of each other, and fine enough that a 100km radius still yields a useful
# handful of cells.
_STEP_DEG = 0.5

TOP_N = 5


def _candidate_grid(latitude: float, longitude: float, radius_km: float) -> list[tuple[float, float]]:
    lat_span = radius_km / 111.0
    lon_span = radius_km / (111.0 * max(cos(radians(latitude)), 0.1))

    points: list[tuple[float, float]] = []
    lat = -lat_span
    while lat <= lat_span + 1e-9:
        lon = -lon_span
        while lon <= lon_span + 1e-9:
            distance_km = ((lat * 111.0) ** 2 + (lon * 111.0 * cos(radians(latitude))) ** 2) ** 0.5
            if distance_km <= radius_km:
                points.append((latitude + lat, longitude + lon))
            lon += _STEP_DEG
        lat += _STEP_DEG
    return points


def find_zones(latitude: float, longitude: float, radius_km: float = 100.0) -> dict[str, Any]:
    if not copernicus_chlorophyll.is_available():
        return {
            "available": False,
            "reason": "Chlorophyll data is not yet available (initial fetch still in progress or failed).",
        }
    if not copernicus_sst.is_available():
        return {
            "available": False,
            "reason": "SST data is not yet available (initial fetch still in progress or failed).",
        }

    candidates = []
    for lat, lon in _candidate_grid(latitude, longitude, radius_km):
        chl = copernicus_chlorophyll.get_point(lat, lon)
        sst = copernicus_sst.get_point(lat, lon)
        if chl["is_land_or_no_data"] or sst["is_land_or_no_data"]:
            continue
        candidates.append(
            {
                "latitude": round(lat, 3),
                "longitude": round(lon, 3),
                "chlorophyll_mg_m3": chl["chlorophyll_mg_m3"],
                "sst_c": sst["temperature_c"],
            }
        )

    if not candidates:
        return {
            "available": True,
            "candidates_scanned": 0,
            "zones": [],
            "note": "No open-ocean cells with data were found in this radius.",
        }

    chl_values = sorted(c["chlorophyll_mg_m3"] for c in candidates)
    median_chl = chl_values[len(chl_values) // 2]

    scored = []
    for c in candidates:
        favourable_sst = _FAVOURABLE_SST_MIN_C <= c["sst_c"] <= _FAVOURABLE_SST_MAX_C
        chl_above_median = c["chlorophyll_mg_m3"] >= median_chl
        score = int(chl_above_median) + int(favourable_sst)
        reasons = []
        if chl_above_median:
            reasons.append(f"chlorophyll {c['chlorophyll_mg_m3']} mg/m3 is above the local median {round(median_chl, 4)}")
        if favourable_sst:
            reasons.append(f"SST {c['sst_c']}°C is inside the {_FAVOURABLE_SST_MIN_C}-{_FAVOURABLE_SST_MAX_C}°C screening band")
        scored.append({**c, "score": score, "reasons": reasons})

    scored.sort(key=lambda c: (-c["score"], -c["chlorophyll_mg_m3"]))
    top = scored[:TOP_N]

    return {
        "available": True,
        "candidates_scanned": len(candidates),
        "zones": top,
        "method": (
            "Heuristic screening: chlorophyll above the local sample's own "
            "median plus SST inside a broad pelagic-favourable band. This is "
            "not a validated PFZ model or an official advisory."
        ),
        "sst_source": copernicus_sst.SOURCE_LABEL,
        "chlorophyll_source": copernicus_chlorophyll.SOURCE_LABEL,
        "chlorophyll_stale": copernicus_chlorophyll.is_stale(),
    }
