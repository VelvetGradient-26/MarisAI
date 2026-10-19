"""services/geofencing.py: pure local geometry, no network involved.

Test coordinates are checked against the real Marine Regions geometry
(verified 2026-08-24), not against the old hand-sketched polygon — a few
values here differ from what an eyeballed sketch would have produced. See
the module docstring for the Palk Strait finding.
"""

from __future__ import annotations

from services import geofencing


def test_a_coastal_point_is_inside_the_india_mainland_eez():
    # Just offshore Chennai.
    result = geofencing.check(13.1, 81.2)
    assert result["india_eez"]["inside"] is True
    assert result["india_eez"]["zone"] == "mainland"


def test_lakshadweeps_waters_fall_inside_the_mainland_zone():
    # Marine Regions does not carry a separate Lakshadweep EEZ record — its
    # waters are already part of the mainland zone's polygon.
    result = geofencing.check(10.55, 72.50)  # offshore near Kavaratti
    assert result["india_eez"]["inside"] is True
    assert result["india_eez"]["zone"] == "mainland"


def test_a_point_off_port_blair_is_inside_the_andaman_and_nicobar_eez():
    result = geofencing.check(11.5, 93.0)
    assert result["india_eez"]["inside"] is True
    assert result["india_eez"]["zone"] == "andaman_and_nicobar"


def test_a_point_far_offshore_is_outside_the_india_eez():
    # Mid Arabian Sea, well past 200 nm from the coast.
    result = geofencing.check(12.0, 60.0)
    assert result["india_eez"]["inside"] is False
    assert result["india_eez"]["zone"] is None
    assert result["india_eez"]["distance_km"] > geofencing.PROXIMITY_THRESHOLD_KM
    assert result["india_eez"]["near"] is False


def test_a_point_just_outside_the_eez_gets_a_real_distance():
    """Found live: asked "how far is 8.5N 76.9E (Thiruvananthapuram's own
    coordinate) from the EEZ", `check()` used to report only `inside: False`
    with no distance at all for the EEZ — unlike `india_sri_lanka_imbl` and
    `nearby_protected_areas`, which already computed one the same way. The
    specialist correctly refused to invent a number rather than hallucinate
    one, but told the user to go run their own GIS calculation for a
    question this tool exists to answer. A point sitting right on the coast
    should be a couple of km out, not "uncomputable"."""
    result = geofencing.check(8.5, 76.9)
    assert result["india_eez"]["inside"] is False
    assert 0 < result["india_eez"]["distance_km"] < 10
    assert result["india_eez"]["near"] is True
    assert result["india_eez"]["nearest_zone"] == "mainland"


def test_eez_nearest_point_is_present_when_outside_and_none_when_inside():
    """The distance fix above still left the map blind: live-verified
    2026-09-09, asking to plot this exact point on a map got "the current
    toolset can't produce a ready-made map for you — open Google Maps..."
    even though `india_sri_lanka_imbl`/`nearby_protected_areas` have drawn
    their own geometry on the chat mini-map for a while
    (`frontend/api/chatGeometry.ts::geofenceFeatures`) — `india_eez` was the
    one case in `check_geofence` with a real distance but no point to draw a
    line to. `nearest_point` is only meaningful outside the EEZ; inside, the
    coordinate isn't near a boundary in the sense this field means."""
    outside = geofencing.check(8.5, 76.9)
    point = outside["india_eez"]["nearest_point"]
    assert point is not None
    assert 7 < point["latitude"] < 9
    assert 76 < point["longitude"] < 78

    inside = geofencing.check(13.1, 81.2)
    assert inside["india_eez"]["nearest_point"] is None


def test_a_real_local_exclusion_near_rameswaram_reads_as_outside_the_eez():
    """Marine Regions' `eez` layer cuts a real interior exclusion (land/shoal,
    the same kind it cuts for every river delta and near-shore island along
    the coast) right around Rameswaram/Adam's Bridge — a hole a 17-point
    hand sketch had no way to represent. Most of Palk Strait's open water is
    *not* excluded (see the next test); this one coordinate is."""
    result = geofencing.check(9.28, 79.3)
    assert result["india_eez"]["inside"] is False


def test_palk_strait_flags_imbl_proximity():
    result = geofencing.check(9.6, 79.4)
    assert result["india_eez"]["inside"] is True, "most of Palk Strait's open water is inside the EEZ"
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


def test_an_andaman_marine_park_is_reported():
    # Mahatma Gandhi Marine National Park, Wandoor.
    result = geofencing.check(11.53, 92.60)
    names = [area["name"] for area in result["nearby_protected_areas"]]
    assert "Mahatma Gandhi Marine National Park" in names


def test_every_response_carries_the_accuracy_caveat():
    result = geofencing.check(0.0, 0.0)
    assert result["note"] == geofencing.ACCURACY_NOTE


def test_a_nearby_protected_area_carries_its_own_drawable_bounds():
    """Added so the frontend can draw the matched MPA as a box directly,
    rather than re-deriving a shape from just a name and a distance."""
    result = geofencing.check(9.05, 79.05)  # Gulf of Mannar Marine National Park centre
    area = next(a for a in result["nearby_protected_areas"] if a["name"] == "Gulf of Mannar Marine National Park")
    bounds = area["bounds"]
    assert bounds["west"] < 79.05 < bounds["east"]
    assert bounds["south"] < 9.05 < bounds["north"]


def test_the_imbl_result_carries_the_actual_nearest_point():
    result = geofencing.check(9.6, 79.4)
    nearest = result["india_sri_lanka_imbl"]["nearest_point"]
    # The nearest point on the treaty line must itself be closer to the query
    # point than the line's own endpoints are — a weak but real sanity check
    # that this is a genuine projection, not a hardcoded coordinate.
    from services.geofencing import _haversine_km

    endpoint_distance = min(
        _haversine_km(9.6, 79.4, 11.44333, 83.36667),
        _haversine_km(9.6, 79.4, 4.79, 77.02333),
    )
    reported_distance = _haversine_km(9.6, 79.4, nearest["latitude"], nearest["longitude"])
    assert reported_distance <= endpoint_distance


def test_boundaries_are_seaward_lines_not_coastline():
    collection = geofencing.boundaries()
    kinds = {feature["properties"]["kind"] for feature in collection["features"]}
    assert {"treaty", "eez_limit", "median_line", "protected_area_outline"} <= kinds
    # The coastal line types are what would trace the shore; they must not ship.
    line_types = {feature["properties"].get("line_type") for feature in collection["features"]}
    assert "Straight baseline" not in line_types
    assert "Connection line" not in line_types
    assert sum(k == "protected_area_outline" for k in (f["properties"]["kind"] for f in collection["features"])) == len(
        geofencing.PROTECTED_AREAS
    )


def test_segment_crossing_imbl_is_restricted():
    # Straight across Palk Strait, India to Sri Lanka.
    assert geofencing.segment_restricted((9.6, 79.2), (9.6, 80.0))


def test_segment_far_offshore_is_not_restricted():
    assert not geofencing.segment_restricted((12.0, 60.0), (12.0, 60.5))
