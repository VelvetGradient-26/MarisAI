"""Tests for marine heatwave detection.

Every failure mode pinned here produces a *plausible* map. A detector that drops
the five-day clause still paints a heatwave field; one that uses the latest day's
threshold for the whole window still reports run lengths; one that treats a
degenerate mean-to-p90 gap as a huge multiple still colours cells, and colours
them the most alarming shade it has. None of it raises.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from services import heatwaves
from services.climatology import build as climatology_build


def _climatology(lats, lons, *, mean=20.0, p90=22.0) -> xr.Dataset:
    shape = (climatology_build.DAYS_IN_YEAR, len(lats), len(lons))
    return xr.Dataset(
        {
            "p90": (("dayofyear", "latitude", "longitude"), np.full(shape, p90, "float32")),
            "p10": (("dayofyear", "latitude", "longitude"), np.full(shape, 18.0, "float32")),
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
    """`values` is (time, lat, lon)."""
    array = np.asarray(values, dtype="float32")
    times = pd.date_range(start, periods=array.shape[0], freq="D")
    return xr.DataArray(
        array,
        dims=("time", "latitude", "longitude"),
        coords={"time": times, "latitude": list(lats), "longitude": list(lons)},
    )


class TestDuration:
    def test_refuses_a_window_shorter_than_the_definition(self):
        """The five-day clause is what separates an event from a warm day. With
        fewer fields than that, any answer misreports weather as an event."""
        lats, lons = (0.0,), (0.0,)
        record = _record(np.full((4, 1, 1), 25.0), lats, lons)
        with pytest.raises(heatwaves.HeatwaveError, match="5 consecutive"):
            heatwaves.detect(record, _climatology(lats, lons))

    def test_four_days_above_threshold_is_not_a_heatwave(self):
        """The cell is hot on the latest day and has been for four days. That is
        precisely the case a snapshot detector gets wrong."""
        lats, lons = (0.0,), (0.0,)
        values = np.full((10, 1, 1), 19.0)
        values[-4:] = 25.0
        field = heatwaves.detect(_record(values, lats, lons), _climatology(lats, lons))
        assert field.run_days[0, 0] == 4
        assert field.category[0, 0] == 0

    def test_five_days_above_threshold_is_a_heatwave(self):
        lats, lons = (0.0,), (0.0,)
        values = np.full((10, 1, 1), 19.0)
        values[-5:] = 25.0
        field = heatwaves.detect(_record(values, lats, lons), _climatology(lats, lons))
        assert field.run_days[0, 0] == 5
        assert field.category[0, 0] > 0

    def test_a_run_broken_yesterday_does_not_count(self):
        """Only a run *ending on the latest day* is a current heatwave. A
        cumulative count would report a fortnight-old event as live."""
        lats, lons = (0.0,), (0.0,)
        values = np.full((20, 1, 1), 25.0)
        values[-2] = 19.0
        field = heatwaves.detect(_record(values, lats, lons), _climatology(lats, lons))
        assert field.run_days[0, 0] == 1
        assert field.category[0, 0] == 0

    def test_run_length_is_censored_at_the_window(self):
        lats, lons = (0.0,), (0.0,)
        field = heatwaves.detect(
            _record(np.full((30, 1, 1), 25.0), lats, lons), _climatology(lats, lons)
        )
        assert field.run_days[0, 0] == 30
        point = heatwaves.at_point(0.0, 0.0, field=field)
        assert point["run_days_censored"] is True


class TestCategories:
    @pytest.mark.parametrize(
        ("sst", "expected"),
        [
            (22.5, "moderate"),  # 1.25x the 2 degC gap
            (24.5, "strong"),  # 2.25x
            (26.5, "severe"),  # 3.25x
            (30.0, "extreme"),  # 5x
        ],
    )
    def test_hobday_scale(self, sst, expected):
        """Categories are multiples of (p90 - mean), not of the exceedance."""
        lats, lons = (0.0,), (0.0,)
        field = heatwaves.detect(
            _record(np.full((10, 1, 1), sst), lats, lons),
            _climatology(lats, lons, mean=20.0, p90=22.0),
        )
        assert heatwaves.CATEGORY_NAMES[field.category[0, 0]] == expected

    def test_extreme_is_open_ended(self):
        lats, lons = (0.0,), (0.0,)
        field = heatwaves.detect(
            _record(np.full((10, 1, 1), 100.0), lats, lons), _climatology(lats, lons)
        )
        assert heatwaves.CATEGORY_NAMES[field.category[0, 0]] == "extreme"

    def test_a_degenerate_gap_is_uncategorised_not_extreme(self):
        """Where p90 == mean the multiple is a division by zero. Treating that
        as a large number makes the most featureless cell on the map the most
        alarming one."""
        lats, lons = (0.0,), (0.0,)
        field = heatwaves.detect(
            _record(np.full((10, 1, 1), 25.0), lats, lons),
            _climatology(lats, lons, mean=22.0, p90=22.0),
        )
        assert field.category[0, 0] == 0


class TestThresholdVariesByDay:
    def test_each_day_is_compared_against_its_own_threshold(self):
        """A 30-day window in spring crosses a moving seasonal threshold. Using
        the latest day's p90 for the whole window biases run length in whichever
        direction the season is going."""
        lats, lons = (0.0,), (0.0,)
        climatology = _climatology(lats, lons)
        # Day-of-year varying threshold: high early in the window, low later.
        p90 = climatology["p90"].values.copy()
        start = climatology_build.day_index(pd.DatetimeIndex(["2026-06-01"]))[0]
        p90[start - 1 : start + 4] = 30.0  # first five days: unreachable
        climatology["p90"] = (("dayofyear", "latitude", "longitude"), p90)

        values = np.full((10, 1, 1), 25.0)
        field = heatwaves.detect(_record(values, lats, lons), climatology)
        # Only the last five days clear their own threshold.
        assert field.run_days[0, 0] == 5


class TestCoverage:
    def test_aggregates_exclude_the_poles(self):
        """`services/crw.py` measured ice-margin cells tripling the global mean.
        The per-cell field keeps them; the headline number must not."""
        lats = (-75.0, 0.0, 75.0)
        lons = (0.0,)
        field = heatwaves.detect(
            _record(np.full((10, 3, 1), 25.0), lats, lons), _climatology(lats, lons)
        )
        # All three cells are in heatwave in the field ...
        assert (field.category > 0).sum() == 3
        # ... but only the equatorial one is counted.
        coverage = field.coverage()
        assert coverage["ocean_cells"] == 1
        assert coverage["cells_in_heatwave"] == 1

    def test_land_is_not_counted_as_ocean(self):
        lats, lons = (0.0, 1.0), (0.0,)
        values = np.full((10, 2, 1), 25.0)
        values[:, 1, 0] = np.nan
        field = heatwaves.detect(_record(values, lats, lons), _climatology(lats, lons))
        assert field.coverage()["ocean_cells"] == 1

    def test_an_empty_band_reports_a_reason_not_a_zero(self):
        """The codebase's rule: never substitute a number for missing data."""
        lats, lons = (-80.0, 80.0), (0.0,)
        field = heatwaves.detect(
            _record(np.full((10, 2, 1), 25.0), lats, lons), _climatology(lats, lons)
        )
        coverage = field.coverage()
        assert coverage["heatwave_fraction"] is None
        assert "unavailable_reason" in coverage


class TestAtPoint:
    def test_reports_an_absence_rather_than_omitting_the_row(self):
        lats, lons = (0.0,), (0.0,)
        field = heatwaves.detect(
            _record(np.full((10, 1, 1), 19.0), lats, lons), _climatology(lats, lons)
        )
        point = heatwaves.at_point(0.0, 0.0, field=field)
        assert point["available"] is True
        assert point["in_heatwave"] is False
        assert point["category"] == "none"

    def test_land_says_so_rather_than_reporting_category_none(self):
        """'none' over land would imply the water there is unremarkable."""
        lats, lons = (0.0,), (0.0,)
        values = np.full((10, 1, 1), np.nan)
        field = heatwaves.detect(_record(values, lats, lons), _climatology(lats, lons))
        point = heatwaves.at_point(0.0, 0.0, field=field)
        assert point["available"] is False
        assert "land" in point["unavailable_reason"]

    def test_longitude_is_matched_on_the_circle(self):
        """179.9 is next to -179.9. A plain argmin over the difference puts it
        half a planet away — the same seam bug `services/eddies.py` closes in
        three places."""
        lats = (0.0,)
        # No cell near -179.9 on the western side, so the nearest cell on the
        # circle is +179.5 (0.6 deg away) while a linear argmin picks 0.0
        # (179.9 deg away) because it measures the long way round.
        lons = (0.0, 179.5)
        values = np.full((10, 1, 2), 19.0)
        values[:, 0, 1] = 25.0  # hot cell at +179.5
        field = heatwaves.detect(_record(values, lats, lons), _climatology(lats, lons))
        point = heatwaves.at_point(0.0, -179.9, field=field)
        assert point["longitude"] == 179.5
        assert point["in_heatwave"] is True

    def test_without_a_field_it_refuses(self):
        heatwaves._cache = None
        with pytest.raises(heatwaves.HeatwaveError, match="no marine heatwave field"):
            heatwaves.at_point(0.0, 0.0)


class TestGuards:
    def test_mismatched_grids_are_refused(self):
        record = _record(np.full((10, 1, 1), 25.0), (0.0,), (0.0,))
        with pytest.raises(heatwaves.HeatwaveError, match="different grids"):
            heatwaves.detect(record, _climatology((0.0, 1.0), (0.0,)))

    def test_a_record_without_time_is_refused(self):
        array = xr.DataArray(
            np.zeros((1, 1)),
            dims=("latitude", "longitude"),
            coords={"latitude": [0.0], "longitude": [0.0]},
        )
        with pytest.raises(heatwaves.HeatwaveError, match="time"):
            heatwaves.detect(array, _climatology((0.0,), (0.0,)))


class TestTrailingRun:
    def test_counts_only_from_the_end(self):
        above = np.array([[[True]], [[False]], [[True]], [[True]]])
        assert heatwaves._trailing_run_length(above)[0, 0] == 2

    def test_all_false_is_zero(self):
        above = np.zeros((5, 1, 1), dtype=bool)
        assert heatwaves._trailing_run_length(above)[0, 0] == 0

    def test_all_true_is_the_window(self):
        above = np.ones((7, 1, 1), dtype=bool)
        assert heatwaves._trailing_run_length(above)[0, 0] == 7
