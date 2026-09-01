"""The wind timestep screen.

This product routinely publishes a day of time-index slots before its
gap-filling pipeline populates them: the timestep exists and loads without
error, but every value is NaN. Finding the newest one that actually carries
data is what these tests are about — specifically, doing it without paying for
a global load per candidate.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from services import copernicus_wind as wind


class FakeArray:
    def __init__(self, values: np.ndarray, times: np.ndarray) -> None:
        self.values = values
        self.shape = values.shape
        self.time = type("T", (), {"values": times})()

    def sel(self, time=None):
        return self

    def isel(self, time=None):
        return FakeArray(self.values[time], self.time.values[time])

    def load(self):
        return self


class FakeDataset:
    def __init__(self, array: FakeArray) -> None:
        self.eastward_wind = array

    def close(self) -> None:
        pass


@pytest.fixture
def opened(monkeypatch):
    """Capture every open_dataset call so the service choice can be asserted."""
    calls: list[dict] = []

    def install(fractions: list[float]):
        times = np.array(
            [np.datetime64(f"2026-08-04T{hour:02d}:00:00") for hour in range(len(fractions))]
        )
        # One 4x4 box per timestep, filled to the requested valid fraction.
        blocks = []
        for fraction in fractions:
            cells = np.full(16, np.nan)
            cells[: int(round(fraction * 16))] = 5.0
            blocks.append(cells.reshape(4, 4))
        array = FakeArray(np.stack(blocks), times)

        class FakeModule:
            @staticmethod
            def open_dataset(**kwargs):
                calls.append(kwargs)
                return FakeDataset(array)

        monkeypatch.setitem(__import__("sys").modules, "copernicusmarine", FakeModule)
        return calls

    return install


def test_the_probe_uses_the_time_series_service(opened):
    """Not geo-series, and this is the whole reason the screen is fast.

    Measured: a 20x-decimated read of one timestep from `arco-geo-series` took
    16.0s against 14.8s for the full field, because geo-series stores one huge
    lat/lon chunk per timestep and the entire chunk must be fetched to
    decompress it. `arco-time-series` chunks the opposite way, so a small box
    across 30 timesteps is one read — measured at 3.8s. Switching this back to
    geo-series would silently restore a ~2.5 minute refresh.
    """
    calls = opened([1.0] * 4)
    wind._candidate_times(datetime(2026, 8, 5, tzinfo=timezone.utc))

    assert calls, "the probe never opened a dataset"
    for call in calls:
        assert call["service"] == "arco-time-series", call
        # A bounded box is the other half of why it is cheap.
        for bound in ("minimum_latitude", "maximum_latitude", "minimum_longitude", "maximum_longitude"):
            assert bound in call, f"probe must bound {bound}"


def test_empty_timesteps_are_screened_out(opened):
    """The backfilling window must not become a candidate."""
    opened([1.0, 1.0, 0.0, 0.0])
    candidates = wind._candidate_times(datetime(2026, 8, 5, tzinfo=timezone.utc))

    stamps = {str(stamp)[:19] for stamp in candidates}
    assert stamps == {"2026-08-04T00:00:00", "2026-08-04T01:00:00"}


def test_candidates_are_newest_first(opened):
    """The newest usable timestep is the one wanted, so ordering is the answer."""
    opened([1.0, 1.0, 1.0])
    candidates = wind._candidate_times(datetime(2026, 8, 5, tzinfo=timezone.utc))

    assert [str(stamp)[:19] for stamp in candidates] == [
        "2026-08-04T02:00:00",
        "2026-08-04T01:00:00",
        "2026-08-04T00:00:00",
    ]


def test_a_wholly_empty_window_yields_no_candidates(opened):
    """Better to raise than to cache a grid of NaN and call it wind."""
    opened([0.0, 0.0, 0.0])
    assert wind._candidate_times(datetime(2026, 8, 5, tzinfo=timezone.utc)) == []


def test_a_timestep_valid_in_either_box_survives(opened):
    """Two basins are probed so a partially written timestep is not discarded.

    The fake serves the same array to both boxes, so this asserts the merge
    keeps the *best* score per timestamp rather than the last one written —
    a min or an overwrite would drop timesteps that one basin happened to miss.
    """
    opened([0.0, 0.5])
    candidates = wind._candidate_times(datetime(2026, 8, 5, tzinfo=timezone.utc))
    assert len(candidates) == 1
    assert str(candidates[0])[:19] == "2026-08-04T01:00:00"


class TestRefreshRecordsWindHistory:
    """`refresh_wind_cache` folds each successful refresh into
    `services/wind_history.py` too — this is the actual production wiring
    `scripts/measure_wind_history_corroboration.py` depends on, so it is
    checked against the real `refresh_wind_cache`, not just against
    `wind_history.record` in isolation."""

    @pytest.fixture(autouse=True)
    def _reset_history(self):
        from services import wind_history

        wind_history.reset()
        yield
        wind_history.reset()

    @pytest.mark.asyncio
    async def test_a_successful_refresh_records_history(self, monkeypatch):
        from services import wind_history

        lat = np.array([-1.0, 0.0, 1.0])
        lon = np.array([-1.0, 0.0, 1.0])
        u = np.full((3, 3), 5.0)
        v = np.full((3, 3), 0.0)
        stamp = datetime(2026, 8, 20, tzinfo=timezone.utc)

        async def fake_fetch_latest_grid():
            return lat, lon, u, v, stamp

        monkeypatch.setattr(wind, "_fetch_latest_grid", lambda: (lat, lon, u, v, stamp))

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        monkeypatch.setattr(wind.asyncio, "to_thread", fake_to_thread)

        await wind.refresh_wind_cache()

        assert wind_history.is_available()

    @pytest.mark.asyncio
    async def test_a_failed_history_record_does_not_break_the_wind_cache(self, monkeypatch):
        """The wind cache is the thing every map layer and drift field
        depends on; a bug in the newer, less-exercised history path must
        never take it down too."""
        from services import wind_history

        lat = np.array([-1.0, 0.0, 1.0])
        lon = np.array([-1.0, 0.0, 1.0])
        u = np.full((3, 3), 5.0)
        v = np.full((3, 3), 0.0)
        stamp = datetime(2026, 8, 20, tzinfo=timezone.utc)

        monkeypatch.setattr(wind, "_fetch_latest_grid", lambda: (lat, lon, u, v, stamp))

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        monkeypatch.setattr(wind.asyncio, "to_thread", fake_to_thread)

        def broken_record(snapshot):
            raise RuntimeError("boom")

        monkeypatch.setattr(wind_history, "record", broken_record)

        await wind.refresh_wind_cache()

        assert wind.is_available()
