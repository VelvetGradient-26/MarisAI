"""services/marine_risk.py: the fixed rule table, not the live services it
composes (those are covered by their own test files). Each of the four live
checks is monkeypatched independently — same shape as test_tools_router.py —
so each test isolates exactly one rule. `geofencing.check` is pure local
geometry and is exercised for real using coordinates test_geofencing.py
already verified, rather than faked, to catch a real integration break.
"""

from __future__ import annotations

from services import marine_risk

_CLEAR_CONDITIONS = {"current": {"wave_height": 0.4, "wind_speed": 10.0}}
_NO_SEVERE_WEATHER = {"alerts": [], "count": 0, "active_nationwide": 0}
_NO_CYCLONE = {
    "active_cyclones_worldwide": 0,
    "nearest": None,
    "within_watch_radius": False,
    "watch_radius_km": 500.0,
}
# Mid Arabian Sea, well outside every boundary/MPA in the registry (see
# test_geofencing.py::test_a_point_far_offshore_is_outside_the_india_eez).
_FAR_OFFSHORE = (12.0, 60.0)


def _patch_all_clear(monkeypatch):
    async def conditions(lat, lon):
        return _CLEAR_CONDITIONS

    async def severe(lat, lon):
        return _NO_SEVERE_WEATHER

    async def cyclone(lat, lon, radius_km=500.0):
        return _NO_CYCLONE

    monkeypatch.setattr(marine_risk.openmeteo, "get_realtime_ocean_conditions", conditions)
    monkeypatch.setattr(marine_risk.severe_weather, "check_point", severe)
    monkeypatch.setattr(marine_risk.cyclones, "check_point", cyclone)


async def test_low_risk_when_every_check_is_clear(monkeypatch):
    _patch_all_clear(monkeypatch)

    result = await marine_risk.assess(*_FAR_OFFSHORE)

    assert result["risk_level"] == "low"
    assert result["could_not_verify"] == []
    assert len(result["checked"]) == 4


async def test_hazardous_waves_escalate_to_high(monkeypatch):
    _patch_all_clear(monkeypatch)

    async def hazardous_conditions(lat, lon):
        return {"current": {"wave_height": 3.0, "wind_speed": 10.0}}

    monkeypatch.setattr(marine_risk.openmeteo, "get_realtime_ocean_conditions", hazardous_conditions)

    result = await marine_risk.assess(*_FAR_OFFSHORE)

    assert result["risk_level"] == "high"
    assert any("wave height" in reason for reason in result["reasons"])


async def test_caution_waves_escalate_to_moderate_only(monkeypatch):
    _patch_all_clear(monkeypatch)

    async def caution_conditions(lat, lon):
        return {"current": {"wave_height": 1.8, "wind_speed": 10.0}}

    monkeypatch.setattr(marine_risk.openmeteo, "get_realtime_ocean_conditions", caution_conditions)

    result = await marine_risk.assess(*_FAR_OFFSHORE)

    assert result["risk_level"] == "moderate"


async def test_severe_imd_alert_escalates_to_high(monkeypatch):
    _patch_all_clear(monkeypatch)

    async def severe(lat, lon):
        return {
            "alerts": [{"event": "Heavy Rain", "severity": "Severe"}],
            "count": 1,
            "active_nationwide": 1,
        }

    monkeypatch.setattr(marine_risk.severe_weather, "check_point", severe)

    result = await marine_risk.assess(*_FAR_OFFSHORE)

    assert result["risk_level"] == "high"
    assert any("IMD alert" in reason for reason in result["reasons"])


async def test_minor_imd_alert_still_escalates_to_moderate(monkeypatch):
    """Any active alert covering this exact point is never nothing, even at
    IMD's lowest severity tier."""
    _patch_all_clear(monkeypatch)

    async def severe(lat, lon):
        return {
            "alerts": [{"event": "Thunderstorm", "severity": "Minor"}],
            "count": 1,
            "active_nationwide": 1,
        }

    monkeypatch.setattr(marine_risk.severe_weather, "check_point", severe)

    result = await marine_risk.assess(*_FAR_OFFSHORE)

    assert result["risk_level"] == "moderate"


async def test_nearby_active_cyclone_escalates_to_extreme(monkeypatch):
    _patch_all_clear(monkeypatch)

    async def cyclone(lat, lon, radius_km=500.0):
        return {
            "active_cyclones_worldwide": 1,
            "nearest": {"name": "Test", "distance_km": 120.0},
            "within_watch_radius": True,
            "watch_radius_km": 500.0,
        }

    monkeypatch.setattr(marine_risk.cyclones, "check_point", cyclone)

    result = await marine_risk.assess(*_FAR_OFFSHORE)

    assert result["risk_level"] == "extreme"
    assert any("cyclone" in reason.lower() for reason in result["reasons"])


async def test_a_distant_cyclone_outside_the_watch_radius_does_not_escalate(monkeypatch):
    _patch_all_clear(monkeypatch)

    async def cyclone(lat, lon, radius_km=500.0):
        return {
            "active_cyclones_worldwide": 1,
            "nearest": {"name": "Test", "distance_km": 4000.0},
            "within_watch_radius": False,
            "watch_radius_km": 500.0,
        }

    monkeypatch.setattr(marine_risk.cyclones, "check_point", cyclone)

    result = await marine_risk.assess(*_FAR_OFFSHORE)

    assert result["risk_level"] == "low"


async def test_imbl_proximity_escalates_to_moderate_using_real_geofencing(monkeypatch):
    _patch_all_clear(monkeypatch)

    # Palk Strait — real, unfaked geofencing.check() flags this as near the
    # India-Sri Lanka boundary (see test_geofencing.py::test_palk_strait_flags_imbl_proximity).
    result = await marine_risk.assess(9.6, 79.4)

    assert result["risk_level"] == "moderate"
    assert any("India-Sri Lanka" in reason for reason in result["reasons"])


async def test_a_failed_check_is_recorded_but_never_escalates_the_verdict(monkeypatch):
    _patch_all_clear(monkeypatch)

    async def broken_conditions(lat, lon):
        raise marine_risk.openmeteo.OpenMeteoError("upstream timed out")

    monkeypatch.setattr(marine_risk.openmeteo, "get_realtime_ocean_conditions", broken_conditions)

    result = await marine_risk.assess(*_FAR_OFFSHORE)

    assert result["risk_level"] == "low"
    assert len(result["could_not_verify"]) == 1
    assert "current sea/weather conditions" in result["could_not_verify"][0]
    assert "current sea/weather conditions" not in result["checked"]
    assert result["conditions"] is None


async def test_the_worst_check_wins_not_the_last_one(monkeypatch):
    """A calm-sea reading arriving after a cyclone hit must not walk the
    verdict back down — escalation only ever goes up."""
    _patch_all_clear(monkeypatch)

    async def cyclone(lat, lon, radius_km=500.0):
        return {
            "active_cyclones_worldwide": 1,
            "nearest": {"name": "Test", "distance_km": 50.0},
            "within_watch_radius": True,
            "watch_radius_km": 500.0,
        }

    monkeypatch.setattr(marine_risk.cyclones, "check_point", cyclone)

    result = await marine_risk.assess(*_FAR_OFFSHORE)

    assert result["risk_level"] == "extreme"


async def test_every_response_carries_the_fixed_rule_note(monkeypatch):
    _patch_all_clear(monkeypatch)

    result = await marine_risk.assess(*_FAR_OFFSHORE)

    assert "fixed rule table" in result["note"]
    assert "not a substitute" in result["note"].lower()
