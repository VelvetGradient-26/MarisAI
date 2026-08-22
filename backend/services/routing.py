"""Safe-route planning: pick the lowest-hazard of a few candidate routes.

**Not a pathfinder.** A real grid-search router (A*/Dijkstra over a hazard
raster) is deferred — see the plan's "Deferred" section. This compares the
direct great-circle route against two laterally-offset alternatives, scores
each by the worst wave/wind conditions along its sampled waypoints using the
platform's existing `services.openmeteo.get_realtime_ocean_conditions`, and
also rejects any candidate that crosses the India-Sri Lanka IMBL or enters a
Marine Protected Area via `services.geofencing`. Good enough to demo "route B
is calmer than the direct line and doesn't cross the boundary" credibly,
which is the PS2 ask; not a substitute for real passage planning.

Every waypoint is a live Open-Meteo call, so this is deliberately kept to a
handful of routes and a handful of waypoints each — the caller (the chat
agent) is inside one turn's latency budget.
"""

from __future__ import annotations

import asyncio
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from typing import Any

from services import geofencing
from services.openmeteo import get_realtime_ocean_conditions

WAYPOINTS_PER_ROUTE = 5
# Perpendicular offset applied at the route's midpoint to build the two
# alternative candidates, in degrees (~55 km at the equator).
_OFFSET_DEG = 0.5

# Wave height bands (metres), roughly the small-craft advisory conventions
# used elsewhere in this codebase's alert thresholds.
_WAVE_CAUTION_M = 1.5
_WAVE_HAZARD_M = 2.5


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(a))


def _interpolate(lat1: float, lon1: float, lat2: float, lon2: float, fraction: float) -> tuple[float, float]:
    """A straight lat/lon interpolation, not a true great-circle slerp.

    Fine at the route lengths a coastal/fishing-vessel query implies (tens to
    a few hundred km) — the distortion a linear lerp introduces versus a
    geodesic only matters at ocean-basin scale.
    """
    return (lat1 + (lat2 - lat1) * fraction, lon1 + (lon2 - lon1) * fraction)


def _offset_route(
    start: tuple[float, float], end: tuple[float, float], side: float
) -> list[tuple[float, float]]:
    """Waypoints for the direct route (`side=0`) or a laterally-offset one."""
    lat1, lon1 = start
    lat2, lon2 = end
    bearing = atan2(
        sin(radians(lon2 - lon1)) * cos(radians(lat2)),
        cos(radians(lat1)) * sin(radians(lat2))
        - sin(radians(lat1)) * cos(radians(lat2)) * cos(radians(lon2 - lon1)),
    )
    # Perpendicular to the route's bearing.
    perp = bearing + radians(90)
    dlat = side * _OFFSET_DEG * cos(perp)
    dlon = side * _OFFSET_DEG * sin(perp) / max(cos(radians((lat1 + lat2) / 2)), 0.1)

    points = []
    for i in range(WAYPOINTS_PER_ROUTE):
        fraction = i / (WAYPOINTS_PER_ROUTE - 1)
        lat, lon = _interpolate(lat1, lon1, lat2, lon2, fraction)
        # The offset is strongest at the midpoint and tapers to zero at both
        # ends, so every candidate route still starts and ends at the
        # requested points.
        taper = sin(fraction * 3.14159265)
        points.append((lat + dlat * taper, lon + dlon * taper))
    return points


def _crosses_geofence(waypoints: list[tuple[float, float]]) -> str | None:
    for lat, lon in waypoints:
        check = geofencing.check(lat, lon)
        if check["india_sri_lanka_imbl"]["near"]:
            return "crosses near the India-Sri Lanka maritime boundary (IMBL)"
        for area in check["nearby_protected_areas"]:
            if area["inside"]:
                return f"enters {area['name']} ({area['state']})"
    return None


async def _sample_waypoint(lat: float, lon: float) -> dict[str, Any]:
    try:
        conditions = await get_realtime_ocean_conditions(latitude=lat, longitude=lon)
    except Exception as exc:  # noqa: BLE001 - one bad sample must not fail the route
        return {"latitude": lat, "longitude": lon, "error": str(exc)[:200]}

    current = conditions.get("current", {})
    return {
        "latitude": lat,
        "longitude": lon,
        "wave_height_m": current.get("wave_height"),
        "wind_speed": current.get("wind_speed"),
        "wind_speed_unit": conditions.get("units", {}).get("wind_speed"),
    }


def _hazard_level(wave_height_m: float | None) -> str:
    if wave_height_m is None:
        return "unknown"
    if wave_height_m >= _WAVE_HAZARD_M:
        return "hazardous"
    if wave_height_m >= _WAVE_CAUTION_M:
        return "caution"
    return "calm"


async def plan_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> dict[str, Any]:
    start = (start_latitude, start_longitude)
    end = (end_latitude, end_longitude)
    distance_km = _haversine_km(*start, *end)

    candidate_routes = {
        "direct": _offset_route(start, end, side=0.0),
        "offset_north": _offset_route(start, end, side=1.0),
        "offset_south": _offset_route(start, end, side=-1.0),
    }

    sampled = await asyncio.gather(
        *[
            asyncio.gather(*[_sample_waypoint(lat, lon) for lat, lon in waypoints])
            for waypoints in candidate_routes.values()
        ]
    )

    evaluated = []
    for (name, waypoints), waypoint_samples in zip(candidate_routes.items(), sampled, strict=True):
        blocked_reason = _crosses_geofence(waypoints)
        waves = [w["wave_height_m"] for w in waypoint_samples if w.get("wave_height_m") is not None]
        max_wave = max(waves) if waves else None
        evaluated.append(
            {
                "name": name,
                "waypoints": waypoint_samples,
                "max_wave_height_m": max_wave,
                "hazard_level": _hazard_level(max_wave),
                "blocked_reason": blocked_reason,
            }
        )

    eligible = [r for r in evaluated if r["blocked_reason"] is None]
    # Sort unavailable-wave-data routes last: `None` cannot be compared to a
    # float, and a route with no data is not evidence it is safer.
    ranking_pool = eligible or evaluated
    chosen = min(
        ranking_pool,
        key=lambda r: (r["max_wave_height_m"] is None, r["max_wave_height_m"] or 0.0),
    )

    return {
        "distance_km": round(distance_km, 1),
        "chosen_route": chosen["name"],
        "chosen_route_hazard": chosen["hazard_level"],
        "routes": evaluated,
        "note": (
            "Compares a direct route against two lateral alternatives using "
            "live wave/wind samples along each; this is not a full pathfinder "
            "over a hazard grid, and geofence checks use the approximate "
            "boundaries in services/geofencing.py."
        ),
    }
