"""scripts/compare_against_drifter_tracks.py: the GDP query/segment-extraction
and scoring logic, checked without touching the network or a real reanalysis
fetch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from scripts.compare_against_drifter_tracks import (
    CONTAINMENT_PERCENTILES,
    _aggregate,
    _build_gdp_url,
    _DrifterFix,
    _DrifterSegment,
    _extract_segments,
    _haversine_km,
    _parse_fixes,
    _score_segment,
    _still_drogued,
    _trim_to_segment_hours,
)


def test_haversine_known_distance():
    # London to Paris, ~344 km great-circle.
    distance = _haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert distance == pytest.approx(343.6, abs=1.0)


def test_haversine_same_point_is_zero():
    assert _haversine_km(10.0, 60.0, 10.0, 60.0) == pytest.approx(0.0, abs=1e-9)


def test_build_gdp_url_encodes_operators_but_not_equals():
    url = _build_gdp_url(
        (5.0, 50.0, 25.0, 80.0),
        datetime(2020, 6, 1, tzinfo=UTC),
        datetime(2020, 6, 2, tzinfo=UTC),
    )
    assert "time%3E=2020-06-01T00:00:00Z" in url
    assert "time%3C=2020-06-02T00:00:00Z" in url
    assert "latitude%3E=5.0" in url
    assert "latitude%3C=25.0" in url
    assert "longitude%3E=50.0" in url
    assert "longitude%3C=80.0" in url
    assert "ID,latitude,longitude,time,drogue_lost_date" in url


def test_parse_fixes_handles_missing_and_present_drogue_lost_date():
    rows = [
        {"ID": 123.0, "latitude": "10.0", "longitude": "60.0", "time": "2020-06-01T00:00:00Z",
         "drogue_lost_date": None},
        {"ID": "300234065410630", "latitude": "9.0", "longitude": "61.0", "time": "2020-06-01T06:00:00Z",
         "drogue_lost_date": "2020-07-01T00:00:00Z"},
    ]
    fixes = _parse_fixes(rows)
    assert fixes[0].drifter_id == "123"
    assert fixes[0].drogue_lost_date is None
    assert fixes[1].drifter_id == "300234065410630"
    assert fixes[1].drogue_lost_date == datetime(2020, 7, 1, tzinfo=UTC)


def test_still_drogued_true_when_never_lost():
    fix = _DrifterFix("1", datetime(2020, 6, 1, tzinfo=UTC), 0.0, 0.0, drogue_lost_date=None)
    assert _still_drogued(fix)


def test_still_drogued_false_after_loss_date():
    lost = datetime(2020, 6, 15, tzinfo=UTC)
    before = _DrifterFix("1", datetime(2020, 6, 1, tzinfo=UTC), 0.0, 0.0, drogue_lost_date=lost)
    after = _DrifterFix("1", datetime(2020, 6, 20, tzinfo=UTC), 0.0, 0.0, drogue_lost_date=lost)
    assert _still_drogued(before)
    assert not _still_drogued(after)


def _fix(hour: int, drogue_lost_date=None) -> _DrifterFix:
    return _DrifterFix(
        "1", datetime(2020, 6, 1, tzinfo=UTC) + timedelta(hours=hour),
        10.0, 60.0, drogue_lost_date,
    )


def test_extract_segments_keeps_a_long_enough_contiguous_run():
    fixes = [_fix(h) for h in (0, 6, 12, 18, 24, 30)]  # 30h contiguous
    segments = _extract_segments(fixes, min_hours=24.0)
    assert len(segments) == 1
    assert segments[0].duration_hours == pytest.approx(30.0)


def test_extract_segments_rejects_a_run_shorter_than_min_hours():
    fixes = [_fix(h) for h in (0, 6, 12)]  # 12h contiguous
    assert _extract_segments(fixes, min_hours=24.0) == []


def test_extract_segments_splits_on_a_real_gap():
    fixes = [_fix(h) for h in (0, 6, 12, 30, 36, 42)]  # a real 18h gap after hour 12
    segments = _extract_segments(fixes, min_hours=12.0)
    assert len(segments) == 2
    assert segments[0].duration_hours == pytest.approx(12.0)
    assert segments[1].duration_hours == pytest.approx(12.0)


def test_extract_segments_stops_at_drogue_loss():
    lost = datetime(2020, 6, 1, tzinfo=UTC) + timedelta(hours=18)
    fixes = [_fix(h, drogue_lost_date=lost) for h in (0, 6, 12, 18, 24, 30)]
    segments = _extract_segments(fixes, min_hours=12.0)
    assert len(segments) == 1
    assert segments[0].duration_hours == pytest.approx(12.0)  # only hours 0-12 are still drogued


def test_trim_to_segment_hours_drops_fixes_beyond_the_limit():
    segment = _DrifterSegment("1", [_fix(h) for h in (0, 6, 12, 18, 24, 30)])
    trimmed = _trim_to_segment_hours(segment, segment_hours=12.0)
    assert [f.time.hour for f in trimmed.fixes] == [0, 6, 12]


def _synthetic_result(median_track: list[dict], members: list[dict]) -> dict:
    return {"median_track": median_track, "members": members, "degraded_terms": []}


def test_score_segment_zero_error_when_real_fix_matches_the_median_exactly():
    segment = _DrifterSegment("1", [
        _DrifterFix("1", datetime(2020, 6, 1, tzinfo=UTC), 10.0, 60.0, None),
        _DrifterFix("1", datetime(2020, 6, 1, 6, tzinfo=UTC), 10.5, 60.5, None),
    ])
    result = _synthetic_result(
        median_track=[{"lat": 10.0, "lon": 60.0, "hour": 0.0}, {"lat": 10.5, "lon": 60.5, "hour": 6.0}],
        members=[
            {"track": [{"lat": 10.0, "lon": 60.0, "hour": 0.0}, {"lat": 10.5, "lon": 60.5, "hour": 6.0}]},
            {"track": [{"lat": 10.0, "lon": 60.0, "hour": 0.0}, {"lat": 10.6, "lon": 60.6, "hour": 6.0}]},
        ],
    )
    rows = _score_segment(segment, result)
    assert len(rows) == 1
    assert rows[0]["lead_hours"] == 6
    assert rows[0]["position_error_km"] == pytest.approx(0.0, abs=1e-6)
    assert all(rows[0]["contained"].values())  # zero error is inside any nonnegative envelope


def test_score_segment_a_far_real_fix_is_not_contained():
    segment = _DrifterSegment("1", [
        _DrifterFix("1", datetime(2020, 6, 1, tzinfo=UTC), 10.0, 60.0, None),
        _DrifterFix("1", datetime(2020, 6, 1, 6, tzinfo=UTC), 30.0, 60.0, None),  # ~2200km from the median
    ])
    result = _synthetic_result(
        median_track=[{"lat": 10.0, "lon": 60.0, "hour": 0.0}, {"lat": 10.0, "lon": 60.0, "hour": 6.0}],
        members=[
            {"track": [{"lat": 10.0, "lon": 60.0, "hour": 0.0}, {"lat": 10.01, "lon": 60.0, "hour": 6.0}]},
            {"track": [{"lat": 10.0, "lon": 60.0, "hour": 0.0}, {"lat": 9.99, "lon": 60.0, "hour": 6.0}]},
        ],
    )
    rows = _score_segment(segment, result)
    assert rows[0]["position_error_km"] > 2000.0
    assert not any(rows[0]["contained"].values())  # far outside a ~1km ensemble spread


def test_score_segment_skips_a_fix_with_no_matching_lead_hour():
    """The report step is hourly; a fix that doesn't land on a reported hour
    (shouldn't happen for real 6-hourly GDP data, but defensive) is skipped
    rather than scored against the wrong point."""
    segment = _DrifterSegment("1", [
        _DrifterFix("1", datetime(2020, 6, 1, tzinfo=UTC), 10.0, 60.0, None),
        _DrifterFix("1", datetime(2020, 6, 1, 6, tzinfo=UTC), 10.0, 60.0, None),
    ])
    result = _synthetic_result(
        median_track=[{"lat": 10.0, "lon": 60.0, "hour": 0.0}],  # no hour=6 entry
        members=[{"track": [{"lat": 10.0, "lon": 60.0, "hour": 0.0}]}],
    )
    assert _score_segment(segment, result) == []


def test_aggregate_empty_rows():
    summary = _aggregate([])
    assert summary["n_scored_points"] == 0
    assert summary["overall_median_position_error_km"] is None


def test_aggregate_computes_median_and_containment_rate():
    rows = [
        {"lead_hours": 6, "position_error_km": 1.0, "contained": {p: True for p in CONTAINMENT_PERCENTILES}},
        {"lead_hours": 6, "position_error_km": 3.0, "contained": {p: False for p in CONTAINMENT_PERCENTILES}},
        {"lead_hours": 12, "position_error_km": 5.0, "contained": {p: True for p in CONTAINMENT_PERCENTILES}},
    ]
    summary = _aggregate(rows)
    assert summary["n_scored_points"] == 3
    assert summary["overall_median_position_error_km"] == pytest.approx(3.0)
    assert summary["overall_containment_rate"]["p50"] == pytest.approx(2 / 3, abs=5e-4)  # rounded to 3dp
    assert summary["by_lead_hours"][6]["n"] == 2
    assert summary["by_lead_hours"][12]["n"] == 1
