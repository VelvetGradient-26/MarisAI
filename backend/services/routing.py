"""Hazard-aware route planning: A* search over a live grid.

**This replaced a three-candidate comparison** (direct line vs. two lateral
offsets) that could never do what a real router does — route *around* a
headland, a Marine Protected Area, or the India-Sri Lanka boundary, because
none of its three fixed shapes could bend around an obstacle. This is a real
grid search: land, the IMBL and MPAs are excluded from the search graph
outright (a path cannot be routed through them, not merely flagged after the
fact), and the surviving graph is weighted by live wave height so the router
prefers calmer water when a calmer detour exists.

**Two live sources feed the graph, at two different resolutions on purpose:**

- **Land mask**: `services.download.providers.gebco.fetch()` — the same
  Ifremer ERDDAP `griddap` bathymetry the Universal Ocean Data Downloader
  uses, not `services/bathymetry.py`'s single-point WMS lookup, because this
  needs a whole rectangle in one request. It auto-strides to keep the
  response near 40,000 cells regardless of the requested box, so a routing
  bbox a few degrees across still resolves to sub-kilometre spacing — far
  finer than the search grid itself. **Land avoidance is checked at this
  fine resolution along every candidate edge, including its midpoint**, not
  just at the coarser search grid's own nodes; two water nodes on either
  side of a peninsula are not proof the straight line between them is water.
- **Hazard**: live wave height (and wind speed) from Open-Meteo's marine and
  weather "current" endpoints, batched — up to 100 coordinates in one
  request (comma-joined lat/lon lists, the same limit
  `services/download/providers/openmeteo.py` found for its own batching) —
  fetched only for the search grid's own water nodes, which is a small
  fraction of the fine land-mask grid's cell count.

**The search grid trades resolution for request volume, and that trade is
tunable but not free.** `GRID_DIVISIONS` nodes along the bounding box's
longer side is enough to route around a real headland while keeping the
Open-Meteo call count to a handful of batches (seconds, not tens of
seconds) — a materially finer grid would resolve smaller coastal features
but cost proportionally more live requests inside one chat turn's latency
budget.

**Waypoints are still linearly interpolated in lat/lon for bbox/heading math**
(`_interpolate`), not a true geodesic — fine at the coastal/fishing-vessel
route lengths this is built for. **No vessel profile** (speed, fuel range,
draft) is an input; every route is still scored on wave hazard alone.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx
import numpy as np
from shapely.geometry import LineString

from services import geofencing
from services.download.providers.gebco import GebcoDownloadError
from services.download.providers.gebco import fetch as fetch_bathymetry

logger = logging.getLogger(__name__)

MARINE_API_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"
_POINTS_PER_REQUEST = 100
_MAX_CONCURRENCY = 4
_TIMEOUT = httpx.Timeout(30.0)

# Nodes along the bounding box's longer side. 8-connected, so this bounds the
# graph at roughly GRID_DIVISIONS^2 nodes before land/geofence exclusion.
GRID_DIVISIONS = 22
MIN_CELL_DEG = 0.03
MAX_CELL_DEG = 0.4

# The search bbox pads beyond the start/end points so the router has room to
# bend around something — a fraction of the direct span, floored and capped
# so a short hop still gets a usable margin and a long one doesn't balloon
# the grid.
_MARGIN_FRACTION = 0.20
_MIN_MARGIN_DEG = 0.25
_MAX_MARGIN_DEG = 1.5

# How far (in grid cells) start/end may reach to join the search graph.
# Doubled on retry if nothing connects, up to the cap.
_CONNECT_RADIUS_CELLS = 2.0
_MAX_CONNECT_RADIUS_CELLS = 8.0

# Waypoints returned to the caller are simplified to this tolerance (degrees)
# so a long path reads as its real turn points, not every grid step.
_SIMPLIFY_TOLERANCE_DEG = 0.01

_WAVE_CAUTION_M = 1.5
_WAVE_HAZARD_M = 2.5

EARTH_RADIUS_KM = 6371.0088

_START_KEY = "start"
_END_KEY = "end"


class RoutingError(RuntimeError):
    """The route could not be planned — a real failure, not "no path found
    because the ocean is calm everywhere"."""


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def _interpolate(lat1: float, lon1: float, lat2: float, lon2: float, fraction: float) -> tuple[float, float]:
    """A straight lat/lon interpolation, not a true great-circle slerp.

    Fine at the route lengths a coastal/fishing-vessel query implies (tens to
    a few hundred km) — the distortion a linear lerp introduces versus a
    geodesic only matters at ocean-basin scale.
    """
    return (lat1 + (lat2 - lat1) * fraction, lon1 + (lon2 - lon1) * fraction)


def _hazard_level(wave_height_m: float | None) -> str:
    if wave_height_m is None:
        return "unknown"
    if wave_height_m >= _WAVE_HAZARD_M:
        return "hazardous"
    if wave_height_m >= _WAVE_CAUTION_M:
        return "caution"
    return "calm"


# --------------------------------------------------------------------------
# Bounding box and search grid
# --------------------------------------------------------------------------


def _search_bbox(
    start: tuple[float, float], end: tuple[float, float]
) -> tuple[float, float, float, float]:
    """(west, south, east, north) — the direct span plus a margin to bend into."""
    lat1, lon1 = start
    lat2, lon2 = end
    lat_span = abs(lat2 - lat1)
    lon_span = abs(lon2 - lon1)
    margin_lat = min(max(lat_span * _MARGIN_FRACTION, _MIN_MARGIN_DEG), _MAX_MARGIN_DEG)
    margin_lon = min(max(lon_span * _MARGIN_FRACTION, _MIN_MARGIN_DEG), _MAX_MARGIN_DEG)
    south = max(min(lat1, lat2) - margin_lat, -90.0)
    north = min(max(lat1, lat2) + margin_lat, 90.0)
    west = max(min(lon1, lon2) - margin_lon, -180.0)
    east = min(max(lon1, lon2) + margin_lon, 180.0)
    return west, south, east, north


def _grid_spacing_deg(west: float, south: float, east: float, north: float) -> float:
    span = max(north - south, east - west)
    return min(max(span / GRID_DIVISIONS, MIN_CELL_DEG), MAX_CELL_DEG)


def _nearest_index(sorted_values: np.ndarray, value: float) -> int:
    """Index of the closest entry in a sorted 1-D array — binary search, not
    a linear scan, since this runs for every grid node and edge sample."""
    idx = int(np.searchsorted(sorted_values, value))
    if idx <= 0:
        return 0
    if idx >= len(sorted_values):
        return len(sorted_values) - 1
    before, after = sorted_values[idx - 1], sorted_values[idx]
    return idx - 1 if (value - before) <= (after - value) else idx


@dataclass
class _DepthGrid:
    """The fine GEBCO land mask — sub-kilometre spacing regardless of the
    coarser search grid's own resolution."""

    lats: np.ndarray
    lons: np.ndarray
    depth: np.ndarray  # 2-D [lat, lon]; NaN is land.

    def is_water(self, lat: float, lon: float) -> bool:
        if not (self.lats[0] <= lat <= self.lats[-1] and self.lons[0] <= lon <= self.lons[-1]):
            # Off the fetched box entirely (can happen right at a start/end
            # point on the box edge) — unknown-but-passable rather than
            # blocking a point the caller explicitly asked to route from.
            return True
        i = _nearest_index(self.lats, lat)
        j = _nearest_index(self.lons, lon)
        value = self.depth[i, j]
        return bool(not np.isnan(value))

    def segment_is_water(
        self, a: tuple[float, float], b: tuple[float, float], samples: int = 4, *, skip_first: bool = False
    ) -> bool:
        """Every sampled point along `a`-`b` must be water. Two water
        *nodes* either side of a peninsula do not prove the straight edge
        between them is water — this is what actually finds the headland.

        `skip_first` exists for connecting the user's own start/end point:
        that coordinate is trusted as navigable by design (a real harbour
        routinely sits exactly on a coarse mask's land/water boundary), so
        only the rest of the segment — not the point itself — has to test
        as water.
        """
        start_step = 1 if skip_first else 0
        for step in range(start_step, samples + 1):
            fraction = step / samples
            lat, lon = _interpolate(a[0], a[1], b[0], b[1], fraction)
            if not self.is_water(lat, lon):
                return False
        return True


async def _fetch_depth_grid(west: float, south: float, east: float, north: float) -> _DepthGrid:
    try:
        dataset = await fetch_bathymetry(west=west, south=south, east=east, north=north)
    except GebcoDownloadError as exc:
        raise RoutingError(f"Could not load bathymetry to avoid land: {exc}") from exc

    dataset = dataset.sortby("latitude").sortby("longitude")
    return _DepthGrid(
        lats=dataset["latitude"].values,
        lons=dataset["longitude"].values,
        depth=dataset["ocean_depth"].values,
    )


# --------------------------------------------------------------------------
# Live hazard (wave height, wind speed) at the search grid's water nodes
# --------------------------------------------------------------------------


@dataclass
class _Hazard:
    wave_height_m: float | None = None
    wind_speed: float | None = None
    wind_speed_unit: str | None = None


async def _fetch_hazard_batch(
    client: httpx.AsyncClient, points: list[tuple[float, float]]
) -> list[_Hazard]:
    lat_param = ",".join(f"{lat:.4f}" for lat, _ in points)
    lon_param = ",".join(f"{lon:.4f}" for _, lon in points)

    async def marine() -> Any:
        response = await client.get(
            MARINE_API_URL,
            params={
                "latitude": lat_param,
                "longitude": lon_param,
                "current": "wave_height",
                "cell_selection": "sea",
            },
        )
        response.raise_for_status()
        return response.json()

    async def weather() -> Any:
        response = await client.get(
            FORECAST_API_URL,
            params={
                "latitude": lat_param,
                "longitude": lon_param,
                "current": "wind_speed_10m",
                "cell_selection": "sea",
            },
        )
        response.raise_for_status()
        return response.json()

    marine_payload, weather_payload = await asyncio.gather(marine(), weather())
    # A single-point request answers with one object instead of a list —
    # every batch here has >= 1 point, but never assume the shape blindly.
    marine_list = marine_payload if isinstance(marine_payload, list) else [marine_payload]
    weather_list = weather_payload if isinstance(weather_payload, list) else [weather_payload]

    hazards = []
    for i in range(len(points)):
        marine_entry = marine_list[i] if i < len(marine_list) else {}
        weather_entry = weather_list[i] if i < len(weather_list) else {}
        hazards.append(
            _Hazard(
                wave_height_m=(marine_entry.get("current") or {}).get("wave_height"),
                wind_speed=(weather_entry.get("current") or {}).get("wind_speed_10m"),
                wind_speed_unit=(weather_entry.get("current_units") or {}).get("wind_speed_10m"),
            )
        )
    return hazards


async def _fetch_hazard_grid(points: list[tuple[float, float]]) -> dict[tuple[float, float], _Hazard]:
    """Wave height/wind speed for every point, batched and rate-limited.

    Never raises: a failed batch leaves those points with unknown hazard
    (cost falls back to distance-only for them) rather than failing the
    whole route over one bad request to a free API — the same "a missing
    sample must not fail the route" rule the old per-waypoint version had.
    """
    if not points:
        return {}

    unique_points = list(dict.fromkeys(points))
    chunks = [
        unique_points[i : i + _POINTS_PER_REQUEST] for i in range(0, len(unique_points), _POINTS_PER_REQUEST)
    ]
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    result: dict[tuple[float, float], _Hazard] = {}

    async def run(chunk: list[tuple[float, float]]) -> None:
        async with semaphore:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                try:
                    hazards = await _fetch_hazard_batch(client, chunk)
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning(f"routing hazard batch failed: {exc}")
                    return
            for point, hazard in zip(chunk, hazards, strict=True):
                result[point] = hazard

    await asyncio.gather(*(run(chunk) for chunk in chunks))
    return result


# --------------------------------------------------------------------------
# Graph construction and A*
# --------------------------------------------------------------------------


@dataclass
class _Node:
    lat: float
    lon: float
    hazard: _Hazard = field(default_factory=_Hazard)


def _edge_cost(a: _Node, b: _Node) -> float:
    distance_km = _haversine_km(a.lat, a.lon, b.lat, b.lon)
    waves = [h for h in (a.hazard.wave_height_m, b.hazard.wave_height_m) if h is not None]
    # Unknown hazard is treated as neutral (factor 1x) rather than penalised
    # or treated as calm — a missing sample is not evidence either way.
    factor = 1.0 + (sum(waves) / len(waves) if waves else 0.0)
    return distance_km * factor


def _is_geofence_excluded(lat: float, lon: float) -> bool:
    check = geofencing.check(lat, lon)
    if check["india_sri_lanka_imbl"]["near"]:
        return True
    return any(area["inside"] for area in check["nearby_protected_areas"])


def _astar(
    start_key: Any, end_key: Any, nodes: dict[Any, _Node], adjacency: dict[Any, list[tuple[Any, float]]]
) -> list[Any] | None:
    """Standard A* with a haversine heuristic.

    Admissible because every edge cost is `distance_km * (1 + hazard)` with
    hazard >= 0 — straight-line distance to the goal is always a lower bound
    on the true remaining cost, so the search never overestimates and the
    result is optimal, not merely plausible.
    """
    goal = nodes[end_key]

    def heuristic(key: Any) -> float:
        node = nodes[key]
        return _haversine_km(node.lat, node.lon, goal.lat, goal.lon)

    open_heap: list[tuple[float, int, Any]] = [(heuristic(start_key), 0, start_key)]
    came_from: dict[Any, Any] = {}
    best_cost: dict[Any, float] = {start_key: 0.0}
    counter = 1  # tie-breaker so the heap never has to compare `_Node`s

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current == end_key:
            path = [current]
            while path[-1] in came_from:
                path.append(came_from[path[-1]])
            path.reverse()
            return path

        for neighbor_key, cost in adjacency.get(current, []):
            tentative = best_cost[current] + cost
            if tentative < best_cost.get(neighbor_key, float("inf")):
                best_cost[neighbor_key] = tentative
                came_from[neighbor_key] = current
                heapq.heappush(open_heap, (tentative + heuristic(neighbor_key), counter, neighbor_key))
                counter += 1

    return None


async def _connect_endpoint(
    label: str,
    key: Any,
    point: tuple[float, float],
    nodes: dict[Any, _Node],
    adjacency: dict[Any, list[tuple[Any, float]]],
    depth_grid: _DepthGrid,
    spacing: float,
) -> None:
    """Wire one of the user's exact start/end points into the grid.

    Not snapped onto the nearest grid node — connected to every nearby grid
    node the straight line to it doesn't cross land, so a harbour the coarse
    grid's own cell happens to classify as land (a real risk right at the
    coastline) never blocks the very question being asked. The search radius
    doubles until something connects or the cap is hit.
    """
    node = nodes[key]
    radius_cells = _CONNECT_RADIUS_CELLS
    connected = False
    while radius_cells <= _MAX_CONNECT_RADIUS_CELLS and not connected:
        radius_deg = radius_cells * spacing
        for grid_key, grid_node in list(nodes.items()):
            if grid_key == key:
                continue
            if max(abs(grid_node.lat - point[0]), abs(grid_node.lon - point[1])) > radius_deg:
                continue
            if not depth_grid.segment_is_water(point, (grid_node.lat, grid_node.lon), skip_first=True):
                continue
            cost = _edge_cost(node, grid_node)
            adjacency[key].append((grid_key, cost))
            adjacency[grid_key].append((key, cost))
            connected = True
        if not connected:
            radius_cells *= 2

    if not connected:
        raise RoutingError(
            f"Could not connect the {label} point to open water on the search "
            "grid — it may be too enclosed (a narrow inlet or harbour) for "
            "this grid's resolution."
        )


def _simplify_path(path_nodes: list[_Node]) -> list[_Node]:
    """Collapse a long run of near-collinear grid steps to its real turn
    points, so the response reads as a route rather than a dump of every
    cell the search happened to visit."""
    if len(path_nodes) <= 2:
        return path_nodes

    line = LineString([(node.lon, node.lat) for node in path_nodes])
    simplified = line.simplify(_SIMPLIFY_TOLERANCE_DEG, preserve_topology=False)
    by_coord = {(node.lon, node.lat): node for node in path_nodes}
    kept = [by_coord[coord] for coord in simplified.coords if coord in by_coord]
    # `simplify` can perturb a coordinate off its original float value in a
    # way the dict lookup above misses; falling back to the unsimplified
    # path is safe (just more waypoints than ideal), never wrong.
    return kept if len(kept) >= 2 else path_nodes


def _waypoint_dict(node: _Node) -> dict[str, Any]:
    return {
        "latitude": round(node.lat, 5),
        "longitude": round(node.lon, 5),
        "wave_height_m": node.hazard.wave_height_m,
        "wind_speed": node.hazard.wind_speed,
        "wind_speed_unit": node.hazard.wind_speed_unit,
    }


async def plan_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> dict[str, Any]:
    """The lowest-hazard path between two points, found by A* search over a
    live grid — not a comparison of a few fixed shapes.

    Raises `RoutingError` when a route genuinely cannot be planned (no
    bathymetry, no path exists, or an endpoint cannot reach open water). A
    long or hazardous route is not an error; a route that cannot be computed
    at all is.
    """
    start = (start_latitude, start_longitude)
    end = (end_latitude, end_longitude)
    great_circle_km = _haversine_km(*start, *end)

    west, south, east, north = _search_bbox(start, end)
    spacing = _grid_spacing_deg(west, south, east, north)
    depth_grid = await _fetch_depth_grid(west, south, east, north)

    lat_count = max(2, round((north - south) / spacing) + 1)
    lon_count = max(2, round((east - west) / spacing) + 1)
    grid_lats = np.linspace(south, north, lat_count)
    grid_lons = np.linspace(west, east, lon_count)

    # (row, col) -> _Node, water and not geofence-excluded only. Excluding
    # the IMBL/an MPA here means the search graph structurally cannot route
    # through one — not a flag checked after the fact.
    nodes: dict[Any, _Node] = {}
    for i, lat in enumerate(grid_lats):
        for j, lon in enumerate(grid_lons):
            lat_f, lon_f = float(lat), float(lon)
            if not depth_grid.is_water(lat_f, lon_f):
                continue
            if _is_geofence_excluded(lat_f, lon_f):
                continue
            nodes[(int(i), int(j))] = _Node(lat=lat_f, lon=lon_f)

    if not nodes:
        raise RoutingError(
            "No navigable water was found in the search area — it may be entirely "
            "land, inside a Marine Protected Area, or too close to the India-Sri "
            "Lanka boundary."
        )

    hazards = await _fetch_hazard_grid([(node.lat, node.lon) for node in nodes.values()])
    for node in nodes.values():
        hazard = hazards.get((node.lat, node.lon))
        if hazard is not None:
            node.hazard = hazard

    neighbor_offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    adjacency: dict[Any, list[tuple[Any, float]]] = {key: [] for key in nodes}
    for (i, j), node in nodes.items():
        for di, dj in neighbor_offsets:
            neighbor_key = (i + di, j + dj)
            neighbor = nodes.get(neighbor_key)
            if neighbor is None:
                continue
            if not depth_grid.segment_is_water((node.lat, node.lon), (neighbor.lat, neighbor.lon)):
                continue
            adjacency[(i, j)].append((neighbor_key, _edge_cost(node, neighbor)))

    nodes[_START_KEY] = _Node(lat=start[0], lon=start[1])
    nodes[_END_KEY] = _Node(lat=end[0], lon=end[1])
    endpoint_hazards = await _fetch_hazard_grid([start, end])
    if start in endpoint_hazards:
        nodes[_START_KEY].hazard = endpoint_hazards[start]
    if end in endpoint_hazards:
        nodes[_END_KEY].hazard = endpoint_hazards[end]
    adjacency[_START_KEY] = []
    adjacency[_END_KEY] = []

    await _connect_endpoint(_START_KEY, _START_KEY, start, nodes, adjacency, depth_grid, spacing)
    await _connect_endpoint(_END_KEY, _END_KEY, end, nodes, adjacency, depth_grid, spacing)

    path_keys = _astar(_START_KEY, _END_KEY, nodes, adjacency)
    if path_keys is None:
        raise RoutingError(
            "No hazard-free path was found between these points within the search "
            "area — they may be separated by land, or the direct corridor is "
            "entirely inside an excluded zone."
        )

    path_nodes = [nodes[key] for key in path_keys]
    simplified = _simplify_path(path_nodes)

    path_distance_km = sum(
        _haversine_km(a.lat, a.lon, b.lat, b.lon)
        for a, b in zip(path_nodes, path_nodes[1:], strict=False)  # consecutive pairs, deliberately unequal length
    )
    waves = [n.hazard.wave_height_m for n in path_nodes if n.hazard.wave_height_m is not None]
    max_wave = max(waves) if waves else None

    return {
        "distance_km": round(path_distance_km, 1),
        "great_circle_km": round(great_circle_km, 1),
        "waypoints": [_waypoint_dict(node) for node in simplified],
        "max_wave_height_m": max_wave,
        "hazard_level": _hazard_level(max_wave),
        "search_grid_nodes": len(nodes) - 2,  # excluding the start/end keys
        "search_grid_spacing_deg": round(spacing, 3),
        "note": (
            "A* search over a live grid: land, the India-Sri Lanka boundary and "
            "Marine Protected Areas are excluded from the search graph outright, "
            "so this path structurally cannot cross any of them, weighted by live "
            "wave height so a calmer detour is preferred when one exists. "
            "distance_km is the found route's length; great_circle_km is the "
            "direct distance for comparison. Not a substitute for an official "
            "chart or a vessel-specific passage plan — see services/routing.py "
            "for the resolution/latency tradeoffs of the search grid."
        ),
    }
