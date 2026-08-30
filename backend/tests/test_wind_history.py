"""Tests for the trailing wind-transport history.

No spatial matching problem here, unlike eddy tracking: the grid is fixed
and cell identity is free. What actually needs proving is the arithmetic
(mean transport, not mean wind), the coverage gate (refusing to call two
samples an hour apart a "3-day mean"), and idempotency across repeated or
stale ticks — the same contract `eddy_tracking.update` and
`heatwave_tracking.advance` both already keep.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.interpolate import RegularGridInterpolator

from services import upwelling, wind_history
from services.vector_source import VectorSnapshot


@pytest.fixture(autouse=True)
def _reset():
    wind_history.reset()
    yield
    wind_history.reset()


def _snapshot(u_value: float, v_value: float, *, stamp: datetime) -> VectorSnapshot:
    """A uniform wind field on *exactly* the history grid's own coordinates,
    so resampling in `record` is an identity operation and the recorded
    transport can be checked against a hand-computed value with no
    interpolation error to account for."""
    lat = wind_history._GRID_LAT
    lon = wind_history._GRID_LON
    u = np.full((len(lat), len(lon)), u_value)
    v = np.full((len(lat), len(lon)), v_value)

    def interp(values):
        return RegularGridInterpolator((lat, lon), values, method="nearest", bounds_error=False, fill_value=None)

    return VectorSnapshot(
        key="test", lat=lat, lon=lon, u=u, v=v, u_interp=interp(u), v_interp=interp(v),
        lon_min=float(lon[0]), timestamp=stamp,
    )


def _expected_transport(u_value: float, v_value: float, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The same formula `wind_history.record` uses, computed by hand for one
    known uniform wind — the independent check that it is not just internally
    self-consistent."""
    u = np.full((len(lat), len(wind_history._GRID_LON)), u_value)
    v = np.full((len(lat), len(wind_history._GRID_LON)), v_value)
    tau_east, tau_north = upwelling.wind_stress(u, v)
    f = upwelling.coriolis(lat)
    return upwelling.ekman_transport(tau_east, tau_north, f)


class TestRecordAndMean:
    def test_no_mean_before_any_record(self):
        assert wind_history.trailing_mean(3.0) is None

    def test_a_single_sample_is_not_a_mean(self):
        wind_history.record(_snapshot(5.0, 0.0, stamp=datetime(2026, 8, 20, tzinfo=UTC)))
        assert wind_history.trailing_mean(3.0) is None

    def test_two_samples_average_their_transport_not_their_wind(self):
        """A hand-computed check against `upwelling`'s own formula, not just
        against this module's own arithmetic repeated."""
        t1 = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        wind_history.record(_snapshot(8.0, 0.0, stamp=t1))
        wind_history.record(_snapshot(2.0, 0.0, stamp=t2))

        mean = wind_history.trailing_mean(1.0)
        assert mean is not None
        assert mean.samples == 2

        lat = wind_history._GRID_LAT
        e1, n1 = _expected_transport(8.0, 0.0, lat)
        e2, n2 = _expected_transport(2.0, 0.0, lat)
        expected_east = (e1 + e2) / 2.0
        expected_north = (n1 + n2) / 2.0

        # Averaging stress (nonlinear in wind speed) must differ from
        # computing stress off the averaged wind (5.0 m/s) — otherwise this
        # module would just be a slower way to average `u`/`v`, the exact
        # thing its own docstring says not to do. With v=0 throughout, the
        # nonlinearity shows up in `m_north` (`tau_east ~ |u| * u`), not
        # `m_east` (`tau_north` is identically 0 when v is).
        stress_of_mean_wind_e, stress_of_mean_wind_n = _expected_transport(5.0, 0.0, lat)
        finite_n = np.isfinite(expected_north) & np.isfinite(stress_of_mean_wind_n)
        assert not np.allclose(expected_north[finite_n], stress_of_mean_wind_n[finite_n])

        finite = np.isfinite(expected_east) & np.isfinite(mean.m_east)
        assert finite.any()
        np.testing.assert_allclose(mean.m_east[finite], expected_east[finite], rtol=1e-4)
        np.testing.assert_allclose(mean.m_north[finite], expected_north[finite], rtol=1e-4, atol=1e-8)

    def test_coverage_gate_refuses_a_window_it_does_not_span(self):
        """Two samples an hour apart cannot support a 3-day mean — the same
        honesty `run_days_censored` gives the heatwave field."""
        t1 = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
        wind_history.record(_snapshot(5.0, 0.0, stamp=t1))
        wind_history.record(_snapshot(5.0, 0.0, stamp=t2))

        assert wind_history.trailing_mean(3.0) is None

    def test_a_stale_or_repeated_timestamp_is_ignored(self):
        t1 = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
        wind_history.record(_snapshot(5.0, 0.0, stamp=t1))
        wind_history.record(_snapshot(999.0, 0.0, stamp=t1))  # same timestamp
        wind_history.record(_snapshot(999.0, 0.0, stamp=t1 - timedelta(hours=1)))  # older

        t2 = t1 + timedelta(hours=18)  # >= half of the 1-day window below
        wind_history.record(_snapshot(5.0, 0.0, stamp=t2))
        mean = wind_history.trailing_mean(1.0)
        assert mean is not None
        assert mean.samples == 2  # not 4

    def test_reset_clears_everything(self):
        wind_history.record(_snapshot(5.0, 0.0, stamp=datetime(2026, 8, 20, tzinfo=UTC)))
        wind_history.reset()
        assert not wind_history.is_available()
        assert wind_history.trailing_mean(1.0) is None

    def test_describe_reports_real_coverage(self):
        t1 = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
        t2 = t1 + timedelta(days=2)
        wind_history.record(_snapshot(5.0, 0.0, stamp=t1))
        wind_history.record(_snapshot(3.0, 0.0, stamp=t2))

        mean = wind_history.trailing_mean(2.0)
        assert mean is not None
        description = mean.describe()
        assert description["samples"] == 2
        assert description["requested_window_days"] == 2.0
        assert description["actual_span_days"] == pytest.approx(2.0, abs=1e-6)
        assert description["oldest"] == t1.isoformat()
        assert description["newest"] == t2.isoformat()
