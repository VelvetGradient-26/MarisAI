"""Tests for the gridded percentile climatology.

The two constructions worth pinning are the ones that fail *silently*: a
day-of-year index that drifts by a day across leap years still produces a
plausible seasonal curve, and a pooling window that does not wrap the year still
produces a threshold everywhere — it is just discontinuous on 1 January.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from services import field_sampling
from services.climatology import build as build_lib
from services.climatology import oisst, store


def _record(years: range, *, lats=(-0.5, 0.5), lons=(-179.5, 179.5), seed=0) -> xr.Dataset:
    """A synthetic daily record on a tiny global-width grid."""
    times = pd.date_range(f"{years.start}-01-01", f"{years.stop - 1}-12-31", freq="D")
    rng = np.random.default_rng(seed)
    values = rng.normal(20.0, 1.0, size=(times.size, len(lats), len(lons)))
    return xr.Dataset(
        {"sst": (("time", "latitude", "longitude"), values.astype("float32"))},
        coords={"time": times, "latitude": list(lats), "longitude": list(lons)},
    )


class TestDayIndex:
    def test_first_of_march_is_61_in_every_year(self):
        """The whole point of the leap adjustment.

        `pandas` gives 1 March dayofyear 60 in a common year and 61 in a leap
        year. Pooling on the raw value mixes 1 March with 29 February and shifts
        the entire second half of every common year by a day.
        """
        common = build_lib.day_index(pd.DatetimeIndex([date(2021, 3, 1)]))[0]
        leap = build_lib.day_index(pd.DatetimeIndex([date(2020, 3, 1)]))[0]
        assert common == leap == 61

    def test_29_february_is_60_and_nothing_else_is(self):
        assert build_lib.day_index(pd.DatetimeIndex([date(2020, 2, 29)]))[0] == 60
        # 28 February is 59 in both kinds of year.
        assert build_lib.day_index(pd.DatetimeIndex([date(2020, 2, 28)]))[0] == 59
        assert build_lib.day_index(pd.DatetimeIndex([date(2021, 2, 28)]))[0] == 59

    def test_the_year_ends_at_366_in_a_leap_year_and_366_in_a_common_one(self):
        """31 December is the last index either way, which is what makes the
        circular window symmetric."""
        assert build_lib.day_index(pd.DatetimeIndex([date(2020, 12, 31)]))[0] == 366
        assert build_lib.day_index(pd.DatetimeIndex([date(2021, 12, 31)]))[0] == 366

    def test_dates_before_march_are_untouched(self):
        for day in (1, 31, 59):
            stamp = pd.Timestamp("2021-01-01") + pd.Timedelta(days=day - 1)
            assert build_lib.day_index(pd.DatetimeIndex([stamp]))[0] == day


class TestWindow:
    def test_wraps_across_new_year(self):
        """1 January must reach back into December, or the two ends of the year
        are fitted from disjoint samples and disagree by construction."""
        window = build_lib.window_indices(1, 5)
        assert set(window) == {362, 363, 364, 365, 366, 1, 2, 3, 4, 5, 6}

    def test_wraps_across_year_end(self):
        window = build_lib.window_indices(366, 5)
        assert set(window) == {361, 362, 363, 364, 365, 366, 1, 2, 3, 4, 5}

    def test_is_symmetric_in_the_middle(self):
        assert list(build_lib.window_indices(200, 2)) == [198, 199, 200, 201, 202]


class TestFit:
    def test_reproduces_a_hand_computed_percentile(self):
        """The arithmetic, checked against numpy on exactly the rows the window
        should have pooled."""
        record = _record(range(1991, 1996))
        fitted = build_lib.fit_percentiles(record["sst"], window_days=5)

        target = 100
        wanted = set(build_lib.window_indices(target, 5).tolist())
        indices = build_lib.day_index(pd.DatetimeIndex(record["time"].values))
        rows = np.flatnonzero(np.isin(indices, list(wanted)))
        expected = np.nanpercentile(record["sst"].values[rows, 0, 0], 90)

        assert fitted["p90"].sel(dayofyear=target).values[0, 0] == pytest.approx(
            expected, rel=1e-5
        )

    def test_p10_is_below_p90_everywhere(self):
        fitted = build_lib.fit_percentiles(_record(range(1991, 1996))["sst"])
        assert bool((fitted["p10"] <= fitted["p90"]).all())

    def test_an_all_nan_cell_stays_nan(self):
        """Land must not become 0. `nanpercentile` over an all-NaN column warns
        and returns NaN; the guard is there so it cannot become a fill value."""
        record = _record(range(1991, 1996))
        record["sst"][:, 0, 0] = np.nan
        fitted = build_lib.fit_percentiles(record["sst"])
        assert bool(np.isnan(fitted["p90"].values[:, 0, 0]).all())
        assert bool(np.isfinite(fitted["p90"].values[:, 1, 1]).all())

    def test_sample_counts_are_recorded(self):
        """A thin estimate has to be visible. Index 60 is leap-years-only, and a
        reader has no other way to know that."""
        fitted = build_lib.fit_percentiles(_record(range(1991, 1996))["sst"], window_days=5)
        counts = fitted["samples"].values
        assert counts[59] < counts[0]  # 29 February, versus a normal day
        assert counts[0] > 0

    def test_covers_every_day_of_the_year(self):
        fitted = build_lib.fit_percentiles(_record(range(1991, 1996))["sst"])
        assert fitted.sizes["dayofyear"] == 366


class TestBuild:
    def test_rejects_a_partial_baseline(self):
        """A percentile fitted on 12 of 30 years is not the baseline it claims
        to be, and the failure is otherwise invisible in the output."""
        record = _record(range(1991, 2003))
        with pytest.raises(build_lib.ClimatologyBuildError, match="missing"):
            build_lib.build_climatology(
                record, variable="sst", baseline_start=1991, baseline_end=2020
            )

    def test_rejects_a_record_that_does_not_overlap(self):
        record = _record(range(1991, 1996))
        with pytest.raises(build_lib.ClimatologyBuildError, match="does not overlap"):
            build_lib.build_climatology(
                record, variable="sst", baseline_start=2010, baseline_end=2014
            )

    def test_records_the_baseline_it_used(self):
        record = _record(range(1991, 1996))
        fitted = build_lib.build_climatology(
            record, variable="sst", baseline_start=1991, baseline_end=1995, min_samples=50
        )
        assert fitted.attrs["baseline_start"] == 1991
        assert fitted.attrs["baseline_end"] == 1995
        assert fitted.attrs["baseline_years"] == 5

    def test_ignores_rows_outside_the_baseline(self):
        """The fit/apply split only helps if the fit actually restricts."""
        record = _record(range(1991, 1997))
        record["sst"].values[-365:] = 100.0  # an absurd final year
        fitted = build_lib.build_climatology(
            record, variable="sst", baseline_start=1991, baseline_end=1995, min_samples=50
        )
        assert float(fitted["p90"].max()) < 30.0


class TestApply:
    def test_anomaly_and_exceedance_use_the_right_day(self):
        record = _record(range(1991, 1996))
        fitted = build_lib.build_climatology(
            record, variable="sst", baseline_start=1991, baseline_end=1995, min_samples=50
        )
        observation = record["sst"].isel(time=0) + 5.0
        scored = build_lib.apply_percentiles(
            observation, fitted, when=date(2026, 3, 1)
        )
        day = fitted.sel(dayofyear=61)
        assert scored["anomaly"].values == pytest.approx(
            (observation - day["mean"].values).values
        )
        assert bool((scored["exceedance"] > 0).all())

    def test_refuses_a_mismatched_grid(self):
        """Letting xarray align would drop the non-matching cells silently."""
        record = _record(range(1991, 1996))
        fitted = build_lib.build_climatology(
            record, variable="sst", baseline_start=1991, baseline_end=1995, min_samples=50
        )
        other = _record(range(1991, 1992), lats=(-0.5, 0.0, 0.5))["sst"].isel(time=0)
        with pytest.raises(build_lib.ClimatologyBuildError, match="different grids"):
            build_lib.apply_percentiles(other, fitted, when=date(2026, 3, 1))


class TestServing:
    def test_field_sampling_reads_a_slice_unchanged(self):
        """The output shape exists to be served by the existing sampler. If this
        breaks, the tile renderer needs a second code path."""
        record = _record(range(1991, 1996))
        fitted = build_lib.build_climatology(
            record, variable="sst", baseline_start=1991, baseline_end=1995, min_samples=50
        )
        sampler = field_sampling.build_sampler(fitted["p90"].sel(dayofyear=61))
        out = sampler(np.array([-90.0, 0.0, 90.0]), np.array([0.0]))
        assert out.shape == (1, 3)
        assert np.isfinite(out).all()

    def test_the_output_grid_is_recognised_as_global(self):
        """A regional grid must not be wrapped and a global one must be. The
        climatology is global, so this asserts the wrap is applied."""
        record = _record(range(1991, 1996))
        fitted = build_lib.build_climatology(
            record, variable="sst", baseline_start=1991, baseline_end=1995, min_samples=50
        )
        assert field_sampling.is_globally_periodic(fitted["longitude"].values)

    def test_store_round_trip(self, tmp_path):
        record = _record(range(1991, 1996))
        fitted = build_lib.build_climatology(
            record, variable="sst", baseline_start=1991, baseline_end=1995, min_samples=50
        )
        store.save(fitted, "sea_surface_temperature", root=tmp_path)
        assert store.available(root=tmp_path) == ["sea_surface_temperature"]
        reloaded = store.load("sea_surface_temperature", root=tmp_path)
        assert reloaded.attrs["baseline_start"] == 1991

    def test_missing_climatology_is_its_own_error(self, tmp_path):
        """Not a FileNotFoundError: the caller's correct response is a 503 with
        the build command, never a 500 and never a substituted number."""
        with pytest.raises(store.ClimatologyNotBuilt, match="build_climatology"):
            store.load("sea_surface_temperature", root=tmp_path)


class TestOisst:
    def test_query_is_percent_encoded(self):
        """`providers/gebco.py` records a fronting Tomcat 400ing on a bare `[`."""
        query = oisst.build_query(date(1991, 1, 1), date(1991, 12, 31), 4)
        assert "[" not in query and "]" not in query
        assert "%5B" in query and "%5D" in query

    def test_query_selects_the_whole_globe_and_the_surface(self):
        query = oisst.build_query(date(1991, 1, 1), date(1991, 12, 31), 4)
        assert "(-89.875)" in query and "(89.875)" in query
        assert "(-179.875)" in query and "(179.875)" in query
        assert "(0.0):1:(0.0)" in query  # the singleton zlev

    def test_stride_matches_the_native_grid(self):
        assert oisst.stride_for(1.0) == 4
        assert oisst.stride_for(0.25) == 1
        with pytest.raises(oisst.OisstError, match="finer"):
            oisst.stride_for(0.1)

    def test_404_retries_once_and_400_never(self):
        """Same policy as `forecasting/history.is_retryable`, and for the same
        measured reason: ERDDAP answers 404 while reloading a dataset."""
        assert oisst._retryable(404, 1) is True
        assert oisst._retryable(404, 2) is False
        assert oisst._retryable(503, 2) is True
        assert oisst._retryable(400, 1) is False

    def test_backoff_is_minutes_and_capped(self):
        """A first draft retried on 2s/4s and lost a whole year's fetch inside
        six seconds, to a host that was serving the identical URL twenty
        minutes earlier. CoastWatch flaps on the ~100s scale, so a policy
        tighter than the flap cannot outlast one."""
        first = [oisst.backoff_for(1) for _ in range(50)]
        assert min(first) >= 40.0  # a minute, minus jitter
        assert max(oisst.backoff_for(9) for _ in range(50)) <= (
            oisst._BACKOFF_CEILING_SECONDS * 1.25 + 1e-6
        )
        # Monotone in expectation, so a long outage waits longer each time.
        assert sum(first) / 50 < sum(oisst.backoff_for(3) for _ in range(50)) / 50


class TestSampleFloor:
    """The guard that replaced a wrong one.

    A per-year completeness check was written first, on the belief that short
    years meant truncated responses. They do not — the OISST aggregate is
    genuinely gappy (1993 carries 163 days against 1991's 365, reproducibly), so
    a per-year floor would reject a real baseline forever. The requirement that
    actually protects a percentile is how many samples stand behind each
    estimate.
    """

    def test_the_default_floor_rejects_a_five_year_record(self):
        record = _record(range(1991, 1996))
        with pytest.raises(build_lib.ClimatologyBuildError, match="samples"):
            build_lib.build_climatology(
                record, variable="sst", baseline_start=1991, baseline_end=1995
            )

    def test_a_gappy_year_is_accepted_when_the_samples_are_there(self):
        """Half of 1993's days removed, mimicking the real archive. The build
        must still succeed — the gaps are the data."""
        record = _record(range(1991, 1996))
        stamps = pd.DatetimeIndex(record["time"].values)
        keep = ~((stamps.year == 1993) & (stamps.dayofyear % 2 == 0))
        record = record.isel(time=np.flatnonzero(keep))
        fitted = build_lib.build_climatology(
            record, variable="sst", baseline_start=1991, baseline_end=1995, min_samples=40
        )
        assert fitted.attrs["baseline_completeness"] < 1.0
        assert fitted.attrs["baseline_years"] == 5

    def test_completeness_is_recorded_on_the_artifact(self):
        """A '1991-2020 baseline' built on a gappy archive is not 10,957 days,
        and a reader comparing two builds needs to see which record each had."""
        record = _record(range(1991, 1996))
        fitted = build_lib.build_climatology(
            record, variable="sst", baseline_start=1991, baseline_end=1995, min_samples=50
        )
        assert fitted.attrs["baseline_days_used"] == 1826
        assert fitted.attrs["baseline_days_in_period"] == 1826
        assert fitted.attrs["baseline_completeness"] == 1.0
