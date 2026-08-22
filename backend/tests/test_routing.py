"""services/routing.py: candidate-route comparison and geofence rejection.

`services.openmeteo.get_realtime_ocean_conditions` is monkeypatched at the
module `routing.py` imports it into (`from services.openmeteo import
get_realtime_ocean_conditions`), so the patch target is `routing.get_realtime_ocean_conditions`.
"""

from __future__ import annotations

import pytest

from services import routing


def _conditions(wave_height_m: float | None):
    async def fake(*, latitude: float, longitude: float):
        return {
            "current": {"wave_height": wave_height_m, "wind_speed": 10.0},
            "units": {"wind_speed": "km/h"},
        }

    return fake


@pytest.mark.asyncio
async def test_prefers_the_lower_hazard_candidate(monkeypatch):
    """Every route samples the same live provider — what should differ is
    only the *values* a real hazard field would produce along each path.

    Route geometry (`_offset_route`) is pinned to three distinct, identifiable
    waypoint sets so the hazard function can key off coordinates deterministic-
    ally, rather than relying on call ordering across nested `asyncio.gather`
    calls — which is not something this test should have to assume about.
    """

    def fixed_route(start, end, side):
        if side == 0.0:
            return [(1.0, 1.0)] * routing.WAYPOINTS_PER_ROUTE  # direct: calm
        if side == 1.0:
            return [(2.0, 2.0)] * routing.WAYPOINTS_PER_ROUTE  # offset_north: rough
        return [(3.0, 3.0)] * routing.WAYPOINTS_PER_ROUTE  # offset_south: calm

    monkeypatch.setattr(routing, "_offset_route", fixed_route)

    async def by_coordinate(*, latitude: float, longitude: float):
        height = 3.5 if latitude == 2.0 else 0.5
        return {"current": {"wave_height": height, "wind_speed": 10.0}, "units": {"wind_speed": "km/h"}}

    monkeypatch.setattr(routing, "get_realtime_ocean_conditions", by_coordinate)

    result = await routing.plan_route(10.0, 75.0, 10.5, 75.5)

    assert result["chosen_route"] != "offset_north"
    assert result["chosen_route_hazard"] == "calm"


@pytest.mark.asyncio
async def test_a_single_calm_route_is_chosen_and_labelled_calm(monkeypatch):
    monkeypatch.setattr(routing, "get_realtime_ocean_conditions", _conditions(0.5))

    result = await routing.plan_route(10.0, 75.0, 10.5, 75.5)

    assert result["chosen_route_hazard"] == "calm"
    assert result["distance_km"] > 0
    for route in result["routes"]:
        assert route["blocked_reason"] is None


@pytest.mark.asyncio
async def test_a_route_crossing_the_imbl_is_flagged(monkeypatch):
    monkeypatch.setattr(routing, "get_realtime_ocean_conditions", _conditions(0.5))

    # Both ends sit either side of the Palk Strait / Gulf of Mannar IMBL.
    result = await routing.plan_route(9.9, 78.5, 9.3, 79.9)

    assert all(route["blocked_reason"] is not None for route in result["routes"])


@pytest.mark.asyncio
async def test_a_missing_waypoint_sample_does_not_fail_the_route(monkeypatch):
    async def failing(*, latitude: float, longitude: float):
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr(routing, "get_realtime_ocean_conditions", failing)

    result = await routing.plan_route(10.0, 75.0, 10.5, 75.5)

    assert result["chosen_route_hazard"] == "unknown"
    for route in result["routes"]:
        assert all("error" in w for w in route["waypoints"])
