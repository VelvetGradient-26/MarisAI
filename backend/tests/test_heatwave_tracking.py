"""Tests for persistent per-cell marine-heatwave identity.

Unlike eddy tracking, there is no matching problem here — the grid is the
same grid every call — so what actually needs proving is simpler and
different: state folds in day-by-day correctly, survives across separate
`advance()` calls (simulating separate scheduler ticks), resets cleanly when
a run ends, and is honest about what it cannot know (a run already active on
the very first day ever processed).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from services import heatwave_tracking
from services.climatology import build as climatology_build


@pytest.fixture(autouse=True)
def _reset_tracker():
    heatwave_tracking._state = None
    yield
    heatwave_tracking._state = None


def _climatology(lats, lons, *, mean=20.0, p90=22.0) -> xr.Dataset:
    shape = (climatology_build.DAYS_IN_YEAR, len(lats), len(lons))
    return xr.Dataset(
        {
            "p90": (("dayofyear", "latitude", "longitude"), np.full(shape, p90, "float32")),
            "mean": (("dayofyear", "latitude", "longitude"), np.full(shape, mean, "float32")),
        },
        coords={
            "dayofyear": np.arange(1, climatology_build.DAYS_IN_YEAR + 1),
            "latitude": list(lats),
            "longitude": list(lons),
        },
        attrs={"baseline_start": 1991, "baseline_end": 2020},
    )


def _record(values, lats, lons, *, start="2026-06-01") -> xr.DataArray:
    array = np.asarray(values, dtype="float32")
    times = pd.date_range(start, periods=array.shape[0], freq="D")
    return xr.DataArray(
        array,
        dims=("time", "latitude", "longitude"),
        coords={"time": times, "latitude": list(lats), "longitude": list(lons)},
    )


class TestColdStart:
    def test_no_state_before_the_first_advance(self):
        snap = heatwave_tracking.snapshot(0.0, 0.0)
        assert snap["available"] is False

    def test_a_run_already_active_on_day_one_is_flagged_possibly_earlier(self):
        """The tracker only ever saw the tail of a run that may have started
        long before it was ever asked to look."""
        lats, lons = (0.0,), (0.0,)
        values = np.full((5, 1, 1), 25.0)  # hot for the whole cold-start window
        heatwave_tracking.advance(_record(values, lats, lons), _climatology(lats, lons))

        snap = heatwave_tracking.snapshot(0.0, 0.0)
        assert snap["available"] is True
        assert snap["in_heatwave"] is True
        assert snap["run_days"] == 5
        assert snap["possibly_started_earlier"] is True
        assert snap["onset_date"] == "2026-06-01"

    def test_a_cold_cell_reports_no_run(self):
        lats, lons = (0.0,), (0.0,)
        values = np.full((5, 1, 1), 19.0)
        heatwave_tracking.advance(_record(values, lats, lons), _climatology(lats, lons))

        snap = heatwave_tracking.snapshot(0.0, 0.0)
        assert snap["in_heatwave"] is False
        assert snap["run_days"] == 0
        assert snap["onset_date"] is None


class TestAcrossRefreshes:
    def test_a_run_that_starts_after_tracking_began_has_an_exact_onset(self):
        """The tracker watched this one start, so there is nothing to be
        unsure about — unlike the cold-start case above."""
        lats, lons = (0.0,), (0.0,)
        climatology = _climatology(lats, lons)

        # First tick: five cool days. No run yet.
        heatwave_tracking.advance(
            _record(np.full((5, 1, 1), 19.0), lats, lons, start="2026-06-01"), climatology
        )
        # Second tick: the fetch window slides forward and brings two new hot
        # days (2026-06-06 and 2026-06-07) alongside five already-processed
        # ones — `advance` must fold in only the two new days, not re-run the
        # five it already has.
        heatwave_tracking.advance(
            _record(np.full((7, 1, 1), 25.0), lats, lons, start="2026-06-01"), climatology
        )

        snap = heatwave_tracking.snapshot(0.0, 0.0)
        assert snap["in_heatwave"] is True
        assert snap["run_days"] == 2
        assert snap["onset_date"] == "2026-06-06"
        assert snap["possibly_started_earlier"] is False

    def test_true_duration_is_not_capped_at_the_fetch_window(self):
        """The whole point: a run outlives any single `WINDOW_DAYS` fetch."""
        lats, lons = (0.0,), (0.0,)
        climatology = _climatology(lats, lons)

        # Three separate ticks of ten hot days each, sliding windows that all
        # overlap — the same shape `oisst.fetch_recent`'s trailing window
        # produces every refresh.
        heatwave_tracking.advance(
            _record(np.full((10, 1, 1), 25.0), lats, lons, start="2026-06-01"), climatology
        )
        heatwave_tracking.advance(
            _record(np.full((10, 1, 1), 25.0), lats, lons, start="2026-06-05"), climatology
        )
        heatwave_tracking.advance(
            _record(np.full((10, 1, 1), 25.0), lats, lons, start="2026-06-09"), climatology
        )

        snap = heatwave_tracking.snapshot(0.0, 0.0)
        # 2026-06-01 through 2026-06-18 inclusive = 18 days, far past any
        # single 10-day fetch.
        assert snap["run_days"] == 18
        assert snap["onset_date"] == "2026-06-01"

    def test_a_repeated_window_with_no_new_day_is_a_no_op(self):
        lats, lons = (0.0,), (0.0,)
        climatology = _climatology(lats, lons)
        record = _record(np.full((10, 1, 1), 25.0), lats, lons, start="2026-06-01")

        heatwave_tracking.advance(record, climatology)
        first = heatwave_tracking.snapshot(0.0, 0.0)
        heatwave_tracking.advance(record, climatology)  # identical window again
        second = heatwave_tracking.snapshot(0.0, 0.0)

        assert first == second

    def test_a_run_ending_resets_onset_and_duration(self):
        lats, lons = (0.0,), (0.0,)
        climatology = _climatology(lats, lons)

        heatwave_tracking.advance(
            _record(np.full((10, 1, 1), 25.0), lats, lons, start="2026-06-01"), climatology
        )
        assert heatwave_tracking.snapshot(0.0, 0.0)["run_days"] == 10

        # Next tick: the cell has cooled back off.
        heatwave_tracking.advance(
            _record(np.full((3, 1, 1), 19.0), lats, lons, start="2026-06-11"), climatology
        )
        snap = heatwave_tracking.snapshot(0.0, 0.0)
        assert snap["in_heatwave"] is False
        assert snap["run_days"] == 0
        assert snap["onset_date"] is None
        assert snap["cumulative_intensity_c_days"] is None

    def test_cumulative_intensity_sums_daily_exceedance_over_the_run(self):
        lats, lons = (0.0,), (0.0,)
        # p90=22, so 25 degC is 3 degC of exceedance every day.
        climatology = _climatology(lats, lons, mean=20.0, p90=22.0)
        heatwave_tracking.advance(
            _record(np.full((4, 1, 1), 25.0), lats, lons, start="2026-06-01"), climatology
        )
        snap = heatwave_tracking.snapshot(0.0, 0.0)
        assert snap["cumulative_intensity_c_days"] == pytest.approx(12.0, abs=1e-3)

    def test_peak_category_holds_the_highest_reached_not_just_the_latest_day(self):
        lats, lons = (0.0,), (0.0,)
        climatology = _climatology(lats, lons, mean=20.0, p90=22.0)
        values = np.full((10, 1, 1), 30.0)  # extreme (5x the gap) for 5 days ...
        values[5:] = 22.5  # ... then moderate (1.25x) for the rest
        heatwave_tracking.advance(_record(values, lats, lons, start="2026-06-01"), climatology)

        snap = heatwave_tracking.snapshot(0.0, 0.0)
        assert snap["in_heatwave"] is True
        assert snap["peak_category"] == "extreme"


class TestLongitudeWraparound:
    def test_matched_on_the_circle(self):
        lats, lons = (0.0,), (0.0, 179.5)
        values = np.full((5, 1, 2), 19.0)
        values[:, 0, 1] = 25.0
        heatwave_tracking.advance(
            _record(values, lats, lons, start="2026-06-01"), _climatology(lats, lons)
        )
        snap = heatwave_tracking.snapshot(0.0, -179.9)
        assert snap["in_heatwave"] is True


class TestGridChange:
    def test_a_changed_grid_resets_state_rather_than_erroring(self):
        heatwave_tracking.advance(
            _record(np.full((5, 1, 1), 25.0), (0.0,), (0.0,), start="2026-06-01"),
            _climatology((0.0,), (0.0,)),
        )
        assert heatwave_tracking.snapshot(0.0, 0.0)["run_days"] == 5

        # A different grid entirely (climatology rebuilt at a new resolution).
        heatwave_tracking.advance(
            _record(np.full((3, 2, 1), 19.0), (0.0, 1.0), (0.0,), start="2026-06-06"),
            _climatology((0.0, 1.0), (0.0,)),
        )
        snap = heatwave_tracking.snapshot(0.0, 0.0)
        assert snap["available"] is True
        assert snap["run_days"] == 0
