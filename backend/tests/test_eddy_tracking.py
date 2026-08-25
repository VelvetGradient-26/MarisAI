"""Frame-to-frame identity assignment, checked against controlled synthetic
scenarios rather than against how plausible the resulting tracks look —
exactly the distinction `services/eddy_tracking.py`'s own docstring draws.

No network and no real detection: `Eddy`/`Detection` are plain dataclasses
(see `services/eddies.py`), so a scenario is just a hand-built sequence of
them fed straight into `eddy_tracking.update()`.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from services import eddy_tracking
from services.eddies import Detection, Eddy

T0 = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.fixture(autouse=True)
def _reset_tracking_state():
    """Module-level state, reset between tests the same way the cache-backed
    services in this suite reset their module dicts."""
    eddy_tracking._tracks.clear()
    eddy_tracking._last_processed_timestamp = None
    eddy_tracking._track_counter = itertools.count(1)
    yield
    eddy_tracking._tracks.clear()
    eddy_tracking._last_processed_timestamp = None
    eddy_tracking._track_counter = itertools.count(1)


def _eddy(lat: float, lon: float, *, polarity: str = "cyclonic", radius_km: float = 50.0) -> Eddy:
    return Eddy(
        latitude=lat,
        longitude=lon,
        polarity=polarity,
        radius_km=radius_km,
        area_km2=3.14159 * radius_km**2,
        vorticity=1e-5,
        max_speed=0.5,
        mean_speed=0.3,
        cells=12,
    )


def _detection(eddies: list[Eddy], *, timestamp: datetime, grid_spacing_deg: float = 0.25) -> Detection:
    return Detection(
        eddies=tuple(eddies),
        timestamp=timestamp,
        computed_at=timestamp,
        threshold=-1e-10,
        sigma_w=1e-10,
        grid_spacing_deg=grid_spacing_deg,
        min_resolvable_radius_km=40.0,
    )


def test_a_single_eddy_is_tracked_across_frames():
    # A slow eastward drift of ~0.02deg/hour (~2.2 km/h) — well inside the
    # gate, the shape a real, continuously-tracked eddy should take.
    eddy_tracking.update(_detection([_eddy(10.0, 60.00)], timestamp=T0))
    eddy_tracking.update(_detection([_eddy(10.0, 60.02)], timestamp=T0 + HOUR))
    eddy_tracking.update(_detection([_eddy(10.0, 60.04)], timestamp=T0 + 2 * HOUR))

    tracks = eddy_tracking.get_tracks()["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["hits"] == 3
    assert tracks[0]["age_hours"] == pytest.approx(2.0)


def test_a_missed_frame_does_not_break_the_track():
    eddy_tracking.update(_detection([_eddy(10.0, 60.00)], timestamp=T0))
    eddy_tracking.update(_detection([], timestamp=T0 + HOUR))  # dropped below threshold this frame
    eddy_tracking.update(_detection([_eddy(10.0, 60.03)], timestamp=T0 + 2 * HOUR))

    tracks = eddy_tracking.get_tracks()["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["hits"] == 2  # the missed frame contributed no fix
    assert tracks[0]["last_seen"] == (T0 + 2 * HOUR).isoformat()


def test_a_track_is_retired_after_too_many_misses():
    eddy_tracking.update(_detection([_eddy(10.0, 60.00)], timestamp=T0))
    # MAX_MISSES consecutive empty frames, then one more to trigger retirement.
    for i in range(1, eddy_tracking.MAX_MISSES + 2):
        eddy_tracking.update(_detection([], timestamp=T0 + i * HOUR))

    assert eddy_tracking.get_tracks()["active_tracks"] == 0

    # A new detection nearby, after retirement, must start a fresh identity —
    # not resurrect the old one after it was genuinely given up on.
    eddy_tracking.update(
        _detection([_eddy(10.0, 60.00)], timestamp=T0 + (eddy_tracking.MAX_MISSES + 3) * HOUR)
    )
    tracks = eddy_tracking.get_tracks()["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["hits"] == 1


def test_polarity_never_flips_mid_track():
    """An anticyclonic eddy appearing exactly where a cyclonic one just was
    is a different feature, physically — polarity is a hard partition on
    matching, not a tie-breaker."""
    eddy_tracking.update(_detection([_eddy(10.0, 60.0, polarity="cyclonic")], timestamp=T0))
    eddy_tracking.update(_detection([_eddy(10.0, 60.0, polarity="anticyclonic")], timestamp=T0 + HOUR))

    tracks = eddy_tracking.get_tracks()["tracks"]
    polarities = {t["polarity"] for t in tracks}
    assert polarities == {"cyclonic", "anticyclonic"}
    for track in tracks:
        assert track["hits"] == 1  # each is its own, unmatched track


def test_optimal_assignment_is_not_order_dependent():
    """The textbook case where independent-greedy (each track claims its own
    nearest candidate, in whatever order it happens to process tracks)
    disagrees with the globally optimal assignment.

    All four points sit on the equator (lat=0), so longitude offsets convert
    to km via `KM_PER_DEGREE` exactly. E1=0km, E2=100km, A=1km, B=3km:
    track A sits 1km from E1 and 99km from E2; track B sits 3km from E1 and
    97km from E2. Both tracks' own nearest is E1, but the optimal assignment
    gives E1 to A (marginally closer) and forces B onto the expensive E2 —
    total cost 98, against 102 for the reverse. Greedy that happens to
    process B first would give B its own nearest (E1) and strand A on the
    99km jump: exactly the "flickering identity" failure this module's
    docstring names. `_match` is checked in both track orderings to confirm
    it never depends on iteration order, because it solves the whole
    ambiguous cluster at once rather than track-by-track.
    """
    from services.eddy_tracking import KM_PER_DEGREE, Track, _fix_from, _match

    def km_lon(km: float) -> float:
        return km / KM_PER_DEGREE

    track_a = Track(track_id="A", polarity="cyclonic", history=[_fix_from(_eddy(0.0, km_lon(1.0)), T0)])
    track_b = Track(track_id="B", polarity="cyclonic", history=[_fix_from(_eddy(0.0, km_lon(3.0)), T0)])
    eddy_1 = _eddy(0.0, km_lon(0.0))
    eddy_2 = _eddy(0.0, km_lon(100.0))

    matches_a_first = _match([track_a, track_b], [eddy_1, eddy_2], gate_km=150.0)
    assert matches_a_first == {0: 0, 1: 1}  # A -> E1, B -> E2

    matches_b_first = _match([track_b, track_a], [eddy_1, eddy_2], gate_km=150.0)
    assert matches_b_first == {0: 1, 1: 0}  # (B, A) order: B -> E2, A -> E1 — same real pairing


def test_a_repeated_timestamp_is_idempotent():
    detection = _detection([_eddy(10.0, 60.0)], timestamp=T0)
    eddy_tracking.update(detection)
    eddy_tracking.update(detection)  # same snapshot, e.g. polled twice before the next refresh

    tracks = eddy_tracking.get_tracks()["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["hits"] == 1


def test_track_ids_are_stable_and_polarity_prefixed():
    eddy_tracking.update(
        _detection(
            [_eddy(10.0, 60.0, polarity="cyclonic"), _eddy(-10.0, 60.0, polarity="anticyclonic")],
            timestamp=T0,
        )
    )
    eddy_tracking.update(
        _detection(
            [_eddy(10.0, 60.01, polarity="cyclonic"), _eddy(-10.0, 60.01, polarity="anticyclonic")],
            timestamp=T0 + HOUR,
        )
    )

    tracks = {t["polarity"]: t for t in eddy_tracking.get_tracks()["tracks"]}
    assert tracks["cyclonic"]["track_id"].startswith("C")
    assert tracks["anticyclonic"]["track_id"].startswith("A")
    assert tracks["cyclonic"]["hits"] == 2
    assert tracks["anticyclonic"]["hits"] == 2


def test_get_tracks_filters_by_polarity_bbox_and_age():
    eddy_tracking.update(
        _detection(
            [_eddy(10.0, 60.0, polarity="cyclonic"), _eddy(-10.0, 100.0, polarity="anticyclonic")],
            timestamp=T0,
        )
    )
    eddy_tracking.update(
        _detection(
            [_eddy(10.0, 60.01, polarity="cyclonic"), _eddy(-10.0, 100.01, polarity="anticyclonic")],
            timestamp=T0 + HOUR,
        )
    )

    only_cyclonic = eddy_tracking.get_tracks(polarity="cyclonic")["tracks"]
    assert len(only_cyclonic) == 1
    assert only_cyclonic[0]["polarity"] == "cyclonic"

    only_near_first = eddy_tracking.get_tracks(bbox=(5.0, 55.0, 15.0, 65.0))["tracks"]
    assert len(only_near_first) == 1
    assert only_near_first[0]["polarity"] == "cyclonic"

    aged_out = eddy_tracking.get_tracks(min_age_hours=2.0)["tracks"]
    assert aged_out == []


def test_get_track_returns_full_path_or_none():
    eddy_tracking.update(_detection([_eddy(10.0, 60.0)], timestamp=T0))
    tracks = eddy_tracking.get_tracks()["tracks"]
    track_id = tracks[0]["track_id"]

    full = eddy_tracking.get_track(track_id)
    assert full is not None
    assert len(full["path"]) == 1
    assert eddy_tracking.get_track("does-not-exist") is None


@pytest.mark.asyncio
async def test_refresh_degrades_quietly_when_the_detector_has_no_data(monkeypatch):
    from services.eddies import EddyError

    def raise_eddy_error():
        raise EddyError("currents cache cold")

    monkeypatch.setattr(eddy_tracking, "current_detection", raise_eddy_error)

    await eddy_tracking.refresh()  # must not raise

    assert eddy_tracking.get_tracks()["active_tracks"] == 0
