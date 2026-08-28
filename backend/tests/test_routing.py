"""services/routing.py: A* over a live grid.

No network is touched: `routing.fetch_bathymetry` and `routing._fetch_hazard_grid`
are monkeypatched to serve synthetic data, the same convention other
external-source tests in this suite use. `services.geofencing.check` is left
real — it is pure local geometry (no network), so tests that care about MPA/
IMBL exclusion use real registry coordinates (Malvan Marine Sanctuary) rather
than faking a second geofencing implementation.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from services import geofencing, routing


def _install_bathymetry(monkeypatch, is_land):
    """`is_land(lat, lon) -> bool` decides the synthetic land/water mask.
    Resolution is fixed and fine enough to resolve anything this test suite
    needs, independent of the real GEBCO auto-strider."""

    async def fake_fetch(*, west: float, south: float, east: float, north: float, **_ignored):
        lats = np.linspace(south, north, 120)
        lons = np.linspace(west, east, 120)
        depth = np.array([[np.nan if is_land(lat, lon) else 20.0 for lon in lons] for lat in lats])
        return xr.Dataset(
            {"ocean_depth": (("latitude", "longitude"), depth)},
            coords={"latitude": lats, "longitude": lons},
        )

    monkeypatch.setattr(routing, "fetch_bathymetry", fake_fetch)


def _install_bathymetry_with_depth(monkeypatch, depth_fn):
    """Like `_install_bathymetry`, but `depth_fn(lat, lon) -> float | None`
    controls the actual depth value (`None` for land), for tests that need a
    shoal rather than a binary land/water mask."""

    async def fake_fetch(*, west: float, south: float, east: float, north: float, **_ignored):
        lats = np.linspace(south, north, 120)
        lons = np.linspace(west, east, 120)
        depth = np.array(
            [[np.nan if depth_fn(lat, lon) is None else depth_fn(lat, lon) for lon in lons] for lat in lats]
        )
        return xr.Dataset(
            {"ocean_depth": (("latitude", "longitude"), depth)},
            coords={"latitude": lats, "longitude": lons},
        )

    monkeypatch.setattr(routing, "fetch_bathymetry", fake_fetch)


def _install_hazard(monkeypatch, wave_height_fn=lambda lat, lon: 0.5):
    async def fake_hazard_grid(points):
        return {
            point: routing._Hazard(wave_height_m=wave_height_fn(*point), wind_speed=10.0, wind_speed_unit="km/h")
            for point in points
        }

    monkeypatch.setattr(routing, "_fetch_hazard_grid", fake_hazard_grid)


@pytest.mark.asyncio
async def test_finds_a_path_over_open_water(monkeypatch):
    _install_bathymetry(monkeypatch, is_land=lambda lat, lon: False)
    _install_hazard(monkeypatch)

    result = await routing.plan_route(10.0, 75.0, 10.3, 75.3)

    assert result["distance_km"] > 0
    assert result["hazard_level"] == "calm"
    assert len(result["waypoints"]) >= 2
    assert result["waypoints"][0]["latitude"] == pytest.approx(10.0, abs=1e-6)
    assert result["waypoints"][-1]["latitude"] == pytest.approx(10.3, abs=1e-6)
    # Open water, no obstacle: the found path should not need much of a detour.
    assert result["distance_km"] < result["great_circle_km"] * 1.2


@pytest.mark.asyncio
async def test_routes_around_a_land_barrier(monkeypatch):
    """A strip of land directly between start and end forces a real detour —
    this is the "route around a headland" claim, checked structurally rather
    than assumed. The gap is placed relative to the *actual* search bbox
    (`_search_bbox`), not a guessed coordinate — the margin logic is a
    fraction-with-floor-and-cap, and a gap placed outside the real box tests
    nothing."""
    start, end = (10.0, 75.0), (10.0, 76.0)
    _, _, _, north = routing._search_bbox(start, end)
    gap_above = north - 0.03  # just inside the box's northern edge

    def is_land(lat: float, lon: float) -> bool:
        # A north-south wall at the midpoint longitude, gapped only right at
        # the top of the search box.
        return abs(lon - 75.5) < 0.05 and lat < gap_above

    _install_bathymetry(monkeypatch, is_land)
    _install_hazard(monkeypatch)

    result = await routing.plan_route(*start, *end)

    for waypoint in result["waypoints"]:
        assert not is_land(waypoint["latitude"], waypoint["longitude"])
    # A detour around a wall is necessarily longer than the direct line.
    assert result["distance_km"] > result["great_circle_km"]


@pytest.mark.asyncio
async def test_a_fully_landlocked_area_raises(monkeypatch):
    _install_bathymetry(monkeypatch, is_land=lambda lat, lon: True)
    _install_hazard(monkeypatch)

    with pytest.raises(routing.RoutingError):
        await routing.plan_route(10.0, 75.0, 10.3, 75.3)


@pytest.mark.asyncio
async def test_an_endpoint_it_cannot_reach_open_water_from_raises(monkeypatch):
    """The start point is trusted as navigable by design (see
    `_DepthGrid.segment_is_water`'s `skip_first`), but it still has to be
    able to *reach* the grid — a lake of land around it on every side, wider
    than the max connect radius, is a real failure to report."""

    def is_land(lat: float, lon: float) -> bool:
        return abs(lat - 10.0) < 0.9 and abs(lon - 75.0) < 0.9 and not (lat == 10.0 and lon == 75.0)

    _install_bathymetry(monkeypatch, is_land)
    _install_hazard(monkeypatch)

    with pytest.raises(routing.RoutingError, match="connect the start point"):
        await routing.plan_route(10.0, 75.0, 12.0, 77.0)


@pytest.mark.asyncio
async def test_a_marine_protected_area_is_never_entered(monkeypatch):
    """Real geofencing data (Malvan Marine Sanctuary), synthetic open water —
    the MPA sits directly on the straight line between start and end, so a
    structural exclusion (not a post-hoc flag) is the only way this passes."""
    _install_bathymetry(monkeypatch, is_land=lambda lat, lon: False)
    _install_hazard(monkeypatch)

    result = await routing.plan_route(16.15, 73.40, 15.90, 73.40)

    for waypoint in result["waypoints"]:
        check = geofencing.check(waypoint["latitude"], waypoint["longitude"])
        assert not any(area["inside"] for area in check["nearby_protected_areas"])
        assert not check["india_sri_lanka_imbl"]["near"]
    assert result["distance_km"] > result["great_circle_km"]


@pytest.mark.asyncio
async def test_a_route_crossing_the_imbl_corridor_has_no_path(monkeypatch):
    """Both ends sit either side of the real, treaty-sourced IMBL (Palk
    Strait / Gulf of Mannar) with no room in the search box to go around Sri
    Lanka entirely — a real router correctly reports no path exists rather
    than crossing the boundary, which is what "the search graph structurally
    excludes it" has to mean when there is no legal detour available."""
    _install_bathymetry(monkeypatch, is_land=lambda lat, lon: False)
    _install_hazard(monkeypatch)

    with pytest.raises(routing.RoutingError, match="No hazard-free path"):
        await routing.plan_route(9.3, 78.9, 9.3, 79.6)


@pytest.mark.asyncio
async def test_prefers_the_lower_hazard_path(monkeypatch):
    """A band of high wave height across most of the box, gapped only near
    its northern edge, should push the chosen path through the gap rather
    than straight across. Checked on `max_wave_height_m` (computed from the
    real, unsimplified path) rather than the returned waypoints — those are
    geometrically simplified for display and can skip the exact node a
    path threaded a gap through without that being evidence of anything."""
    start, end = (10.0, 75.0), (10.0, 76.0)
    _, _, _, north = routing._search_bbox(start, end)
    gap_above = north - 0.03

    _install_bathymetry(monkeypatch, is_land=lambda lat, lon: False)

    def wave_height(lat: float, lon: float) -> float:
        in_band = 75.35 < lon < 75.65
        near_gap = lat > gap_above
        return 0.2 if (not in_band or near_gap) else 8.0

    _install_hazard(monkeypatch, wave_height)

    result = await routing.plan_route(*start, *end)

    assert result["max_wave_height_m"] < 8.0


@pytest.mark.asyncio
async def test_a_hazard_fetch_failure_still_returns_a_route(monkeypatch):
    """A missing sample must not fail the route — the same rule the old
    per-waypoint version had, now applied to a batched fetch instead."""
    _install_bathymetry(monkeypatch, is_land=lambda lat, lon: False)

    async def failing_hazard_grid(points):
        return {}

    monkeypatch.setattr(routing, "_fetch_hazard_grid", failing_hazard_grid)

    result = await routing.plan_route(10.0, 75.0, 10.3, 75.3)

    assert result["distance_km"] > 0
    assert result["hazard_level"] == "unknown"
    assert result["max_wave_height_m"] is None


@pytest.mark.asyncio
async def test_a_bathymetry_failure_raises(monkeypatch):
    async def failing_fetch(*, west, south, east, north, **_ignored):
        raise routing.GebcoDownloadError("ERDDAP unreachable")

    monkeypatch.setattr(routing, "fetch_bathymetry", failing_fetch)

    with pytest.raises(routing.RoutingError):
        await routing.plan_route(10.0, 75.0, 10.3, 75.3)


class TestVesselProfile:
    """Draft, speed and fuel range: all optional, all independent (see
    `plan_route`'s own docstring on why speed/fuel range never steer the
    search — only draft does, by excluding graph nodes/edges outright)."""

    @pytest.mark.asyncio
    async def test_no_vessel_profile_leaves_routing_unchanged(self, monkeypatch):
        _install_bathymetry(monkeypatch, is_land=lambda lat, lon: False)
        _install_hazard(monkeypatch)

        result = await routing.plan_route(10.0, 75.0, 10.3, 75.3)

        assert result["vessel_profile"] == {
            "draft_m": None,
            "speed_kmh": None,
            "fuel_range_km": None,
        }

    @pytest.mark.asyncio
    async def test_draft_forces_a_detour_around_a_shoal(self, monkeypatch):
        """A shoal (water, but too shallow for this draft) directly on the
        straight line must force the same kind of detour a land barrier
        does — draft exclusion has to be structural, not a post-hoc flag."""
        start, end = (10.0, 75.0), (10.0, 76.0)
        _, _, _, north = routing._search_bbox(start, end)
        gap_above = north - 0.03

        def depth(lat: float, lon: float) -> float:
            in_shoal_band = abs(lon - 75.5) < 0.05 and lat < gap_above
            return 3.0 if in_shoal_band else 20.0  # 3 m: too shallow for a 6 m draft

        _install_bathymetry_with_depth(monkeypatch, depth)
        _install_hazard(monkeypatch)

        result = await routing.plan_route(*start, *end, vessel_draft_m=6.0)

        for waypoint in result["waypoints"]:
            assert depth(waypoint["latitude"], waypoint["longitude"]) > 6.0
        assert result["distance_km"] > result["great_circle_km"]
        assert result["vessel_profile"]["draft_m"] == 6.0

    @pytest.mark.asyncio
    async def test_draft_too_deep_for_any_water_here_raises(self, monkeypatch):
        _install_bathymetry_with_depth(monkeypatch, lambda lat, lon: 5.0)
        _install_hazard(monkeypatch)

        with pytest.raises(routing.RoutingError, match="draft"):
            await routing.plan_route(10.0, 75.0, 10.3, 75.3, vessel_draft_m=10.0)

    @pytest.mark.asyncio
    async def test_a_draft_within_the_available_depth_does_not_detour(self, monkeypatch):
        """Uniform 20 m water and a 6 m draft: nothing should be excluded, so
        the route is the same direct path an unconstrained vessel would get."""
        _install_bathymetry(monkeypatch, is_land=lambda lat, lon: False)
        _install_hazard(monkeypatch)

        result = await routing.plan_route(10.0, 75.0, 10.3, 75.3, vessel_draft_m=6.0)

        assert result["distance_km"] < result["great_circle_km"] * 1.2

    @pytest.mark.asyncio
    async def test_speed_gives_an_estimated_duration_without_changing_the_route(self, monkeypatch):
        _install_bathymetry(monkeypatch, is_land=lambda lat, lon: False)
        _install_hazard(monkeypatch)

        unconstrained = await routing.plan_route(10.0, 75.0, 10.3, 75.3)
        result = await routing.plan_route(10.0, 75.0, 10.3, 75.3, vessel_speed_kmh=20.0)

        assert result["distance_km"] == unconstrained["distance_km"]
        assert result["vessel_profile"]["estimated_duration_hours"] == pytest.approx(
            result["distance_km"] / 20.0
        )

    @pytest.mark.asyncio
    async def test_fuel_range_shorter_than_the_route_is_flagged(self, monkeypatch):
        _install_bathymetry(monkeypatch, is_land=lambda lat, lon: False)
        _install_hazard(monkeypatch)

        result = await routing.plan_route(10.0, 75.0, 10.3, 75.3, vessel_fuel_range_km=1.0)

        assert result["vessel_profile"]["within_fuel_range"] is False
        assert result["vessel_profile"]["fuel_range_exceeded_by_km"] == pytest.approx(
            result["distance_km"] - 1.0
        )

    @pytest.mark.asyncio
    async def test_fuel_range_longer_than_the_route_is_not_flagged(self, monkeypatch):
        _install_bathymetry(monkeypatch, is_land=lambda lat, lon: False)
        _install_hazard(monkeypatch)

        result = await routing.plan_route(10.0, 75.0, 10.3, 75.3, vessel_fuel_range_km=10_000.0)

        assert result["vessel_profile"]["within_fuel_range"] is True
        assert "fuel_range_exceeded_by_km" not in result["vessel_profile"]
