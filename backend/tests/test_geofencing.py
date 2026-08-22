"""services/geofencing.py: pure local geometry, no network involved."""

from __future__ import annotations

from services import geofencing


def test_a_coastal_point_is_inside_the_india_eez():
    # Just offshore Chennai.
    result = geofencing.check(13.1, 81.2)
    assert result["india_eez"]["inside"] is True


def test_a_point_far_offshore_is_outside_the_india_eez():
    # Mid Arabian Sea, well past 200 nm from the coast.
    result = geofencing.check(12.0, 60.0)
    assert result["india_eez"]["inside"] is False


def test_palk_strait_flags_imbl_proximity():
    result = geofencing.check(9.28, 79.3)
    assert result["india_sri_lanka_imbl"]["near"] is True
    assert result["india_sri_lanka_imbl"]["distance_km"] < geofencing.PROXIMITY_THRESHOLD_KM


def test_a_point_far_from_the_boundary_does_not_flag_imbl():
    result = geofencing.check(15.0, 92.0)  # Bay of Bengal, near Myanmar
    assert result["india_sri_lanka_imbl"]["near"] is False


def test_a_point_inside_a_protected_area_is_reported():
    result = geofencing.check(9.05, 79.05)  # Gulf of Mannar Marine National Park centre
    names = [area["name"] for area in result["nearby_protected_areas"]]
    assert "Gulf of Mannar Marine National Park" in names
    inside = next(a for a in result["nearby_protected_areas"] if a["name"] == "Gulf of Mannar Marine National Park")
    assert inside["inside"] is True


def test_every_response_carries_the_accuracy_caveat():
    result = geofencing.check(0.0, 0.0)
    assert result["note"] == geofencing.ACCURACY_NOTE
