"""scripts/compare_against_eddy_atlas.py: the matching/scoring logic and the
atlas file reader, checked without touching the network or a real atlas file.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from scripts.compare_against_eddy_atlas import (
    MATCH_GATE_KM,
    _compare_polarity,
    _haversine_km,
    _load_atlas_day,
    _match,
    _Point,
)


def test_a_close_pair_matches():
    ours = [_Point(10.0, 60.0, 50.0)]
    atlas = [_Point(10.01, 60.01, 45.0)]
    matches = _match(ours, atlas, MATCH_GATE_KM)
    assert matches == {0: 0}


def test_a_far_pair_does_not_match():
    ours = [_Point(10.0, 60.0, 50.0)]
    atlas = [_Point(-10.0, 60.0, 50.0)]  # ~2200 km away
    matches = _match(ours, atlas, MATCH_GATE_KM)
    assert matches == {}


def test_optimal_assignment_is_order_independent():
    """The same textbook case `test_eddy_tracking.py` pins for the live
    tracker's matcher — reimplemented here, so pinned here too."""
    from services.eddy_tracking import KM_PER_DEGREE

    def km_lon(km: float) -> float:
        return km / KM_PER_DEGREE

    a = _Point(0.0, km_lon(1.0), 50.0)
    b = _Point(0.0, km_lon(3.0), 50.0)
    atlas_1 = _Point(0.0, km_lon(0.0), 50.0)
    atlas_2 = _Point(0.0, km_lon(100.0), 50.0)

    forward = _match([a, b], [atlas_1, atlas_2], gate_km=150.0)
    assert forward == {0: 0, 1: 1}

    backward = _match([b, a], [atlas_1, atlas_2], gate_km=150.0)
    assert backward == {0: 1, 1: 0}


def test_compare_polarity_reports_recall_and_match_rate():
    ours = [_Point(10.0, 60.0, 50.0), _Point(20.0, 70.0, 60.0)]
    atlas = [_Point(10.01, 60.01, 45.0)]  # matches only the first

    result = _compare_polarity(ours, atlas)

    assert result["our_count"] == 2
    assert result["atlas_count"] == 1
    assert result["matched"] == 1
    assert result["recall_vs_atlas"] == 1.0  # the one atlas eddy was found
    assert result["our_match_rate"] == 0.5  # only one of our two matched
    assert result["median_position_error_km"] is not None
    assert result["median_radius_ratio_ours_over_atlas"] == pytest.approx(50.0 / 45.0, rel=1e-3)


def test_compare_polarity_handles_no_atlas_observations():
    result = _compare_polarity([_Point(10.0, 60.0, 50.0)], [])
    assert result["recall_vs_atlas"] is None
    assert result["our_match_rate"] == 0.0


def test_haversine_matches_a_known_distance():
    # London to Paris, ~344 km great-circle.
    d = _haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert d == pytest.approx(344, abs=5)


def _write_atlas_file(path: Path, *, times: list[date], lats, lons, radii) -> None:
    epoch = np.datetime64("1950-01-01")
    days = np.array([(np.datetime64(t) - epoch) / np.timedelta64(1, "D") for t in times], dtype="float64")
    dataset = xr.Dataset(
        {
            "time": ("obs", days),
            "latitude": ("obs", np.asarray(lats, dtype="float64")),
            "longitude": ("obs", np.asarray(lons, dtype="float64")),
            "speed_radius": ("obs", np.asarray(radii, dtype="float64")),
        }
    )
    dataset["time"].attrs["units"] = "days since 1950-01-01 00:00:00 UTC"
    dataset.to_netcdf(path)


def test_load_atlas_day_selects_only_the_target_date(tmp_path):
    path = tmp_path / "atlas.nc"
    _write_atlas_file(
        path,
        times=[date(2020, 6, 14), date(2020, 6, 15), date(2020, 6, 15), date(2020, 6, 16)],
        lats=[1.0, 2.0, 3.0, 4.0],
        lons=[10.0, 20.0, 30.0, 40.0],
        radii=[50_000.0, 60_000.0, 70_000.0, 80_000.0],
    )

    points = _load_atlas_day(path, date(2020, 6, 15), bbox=None)

    assert len(points) == 2
    assert {round(p.longitude) for p in points} == {20, 30}
    # metres -> km.
    assert {p.radius_km for p in points} == {60.0, 70.0}


def test_load_atlas_day_wraps_longitude_to_pm180(tmp_path):
    """AVISO's own stated coverage is "0deg to 360deg" — a raw 270deg point
    has to read back as -90, matching every bbox/grid convention elsewhere
    in this codebase."""
    path = tmp_path / "atlas.nc"
    _write_atlas_file(
        path, times=[date(2020, 1, 1)], lats=[10.0], lons=[270.0], radii=[50_000.0]
    )

    points = _load_atlas_day(path, date(2020, 1, 1), bbox=None)

    assert len(points) == 1
    assert points[0].longitude == pytest.approx(-90.0)


def test_load_atlas_day_applies_the_bbox(tmp_path):
    path = tmp_path / "atlas.nc"
    _write_atlas_file(
        path,
        times=[date(2020, 1, 1), date(2020, 1, 1)],
        lats=[10.0, 50.0],
        lons=[60.0, 60.0],
        radii=[50_000.0, 50_000.0],
    )

    points = _load_atlas_day(path, date(2020, 1, 1), bbox=(0.0, 30.0, 20.0, 90.0))

    assert len(points) == 1
    assert points[0].latitude == 10.0


def test_load_atlas_day_returns_empty_for_an_uncovered_date(tmp_path):
    path = tmp_path / "atlas.nc"
    _write_atlas_file(path, times=[date(2020, 1, 1)], lats=[10.0], lons=[60.0], radii=[50_000.0])

    assert _load_atlas_day(path, date(1999, 1, 1), bbox=None) == []
