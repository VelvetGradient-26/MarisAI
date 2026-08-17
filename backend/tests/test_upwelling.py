"""Tests for coastal upwelling detection.

The hemisphere test is the one that matters most. Ekman transport is 90 degrees
to the right of the wind in the north and to the left in the south, so a
detector that hard-codes one rotation is correct in one hemisphere and
confidently wrong in the other — the identical failure `services/eddies.py`
records for eddy polarity, in a field that still looks entirely plausible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.interpolate import RegularGridInterpolator

from services import sst_anomaly, upwelling
from services.vector_source import VectorSnapshot


def _snapshot(lat, lon, u, v, *, key="test", stamp=None) -> VectorSnapshot:
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    u = np.asarray(u, dtype="float64")
    v = np.asarray(v, dtype="float64")

    def interp(values):
        return RegularGridInterpolator(
            (lat, lon), values, method="nearest", bounds_error=False, fill_value=None
        )

    return VectorSnapshot(
        key=key,
        lat=lat,
        lon=lon,
        u=u,
        v=v,
        u_interp=interp(u),
        v_interp=interp(v),
        lon_min=float(lon[0]),
        timestamp=stamp or datetime(2026, 8, 17, tzinfo=UTC),
    )


def _coast(lat, lon, *, land_columns):
    """An ocean mask with land in the given columns — a north-south coastline.

    `land_columns=slice(-3, None)` puts land at the *high* longitudes, i.e. to
    the east, with open ocean to the west. That is an **eastern boundary**
    (California, Peru, Namibia, Somalia) and the offshore normal points west.
    Getting this backwards is easy and the resulting field is entirely
    plausible — it simply reports every upwelling coast as downwelling."""
    ocean_u = np.full((len(lat), len(lon)), 0.1)
    ocean_v = np.full((len(lat), len(lon)), 0.1)
    ocean_u[:, land_columns] = np.nan
    ocean_v[:, land_columns] = np.nan
    return ocean_u, ocean_v


class TestPhysics:
    def test_stress_grows_with_the_square_of_speed(self):
        """`tau = rho Cd |U| U` — doubling the wind quadruples the stress."""
        one_east, _ = upwelling.wind_stress(np.array([5.0]), np.array([0.0]))
        two_east, _ = upwelling.wind_stress(np.array([10.0]), np.array([0.0]))
        assert two_east[0] == pytest.approx(4.0 * one_east[0])

    def test_coriolis_is_blanked_at_the_equator(self):
        f = upwelling.coriolis(np.array([-30.0, -2.0, 0.0, 2.0, 30.0]))
        assert np.isfinite(f[0]) and np.isfinite(f[4])
        assert np.isnan(f[1]) and np.isnan(f[2]) and np.isnan(f[3])

    def test_coriolis_changes_sign_across_the_equator(self):
        f = upwelling.coriolis(np.array([-30.0, 30.0]))
        assert f[0] < 0 < f[1]

    def test_transport_is_ninety_degrees_right_of_the_stress_in_the_north(self):
        """A northward stress at 30N drives transport to the east."""
        f = upwelling.coriolis(np.array([30.0]))
        east, north = upwelling.ekman_transport(
            np.array([[0.0]]), np.array([[0.1]]), f
        )
        assert east[0, 0] > 0
        assert north[0, 0] == pytest.approx(0.0)

    def test_transport_is_ninety_degrees_left_of_the_stress_in_the_south(self):
        """The same northward stress at 30S drives transport to the *west*.

        This is the hemisphere asymmetry, and it falls out of the sign of f
        rather than from a latitude branch."""
        f = upwelling.coriolis(np.array([-30.0]))
        east, north = upwelling.ekman_transport(
            np.array([[0.0]]), np.array([[0.1]]), f
        )
        assert east[0, 0] < 0


class TestNormal:
    def test_points_from_land_into_water(self):
        """Land in the western columns means offshore is east."""
        ocean = np.ones((6, 10), dtype=bool)
        ocean[:, :3] = False
        dx = np.full(6, 25_000.0)
        east, north, confidence = upwelling.offshore_normal(ocean, dx, 25_000.0, False)
        # Just seaward of the coast, the normal points east and barely north.
        assert east[3, 4] > 0.9
        assert abs(north[3, 4]) < 0.2
        assert confidence[3, 4] > upwelling.MIN_COASTLINE_CONFIDENCE

    def test_flips_when_the_land_is_on_the_other_side(self):
        ocean = np.ones((6, 10), dtype=bool)
        ocean[:, 7:] = False
        dx = np.full(6, 25_000.0)
        east, _, _ = upwelling.offshore_normal(ocean, dx, 25_000.0, False)
        assert east[3, 5] < -0.9

    def test_open_ocean_has_no_confidence(self):
        """Nothing to point away from, so the normal is meaningless and must not
        be invented."""
        ocean = np.ones((8, 8), dtype=bool)
        dx = np.full(8, 25_000.0)
        _, _, confidence = upwelling.offshore_normal(ocean, dx, 25_000.0, False)
        assert float(confidence.max()) == 0.0


class TestDetect:
    def test_an_equatorward_wind_upwells_on_an_eastern_boundary(self):
        """The canonical case: land to the east, wind blowing toward the
        equator (southward at 30N) — as off California, Peru, Namibia and
        Somalia. Transport is offshore and the index must be positive."""
        lat = np.arange(20.0, 40.0, 2.0)
        lon = np.arange(-130.0, -110.0, 2.0)
        u, v = _coast(lat, lon, land_columns=slice(-3, None))
        currents = _snapshot(lat, lon, u, v)
        wind = _snapshot(
            lat, lon, np.zeros((len(lat), len(lon))), np.full((len(lat), len(lon)), -8.0)
        )

        field = upwelling.detect(wind, currents)
        scored = field.index[np.isfinite(field.index)]
        assert scored.size > 0
        assert float(np.nanmean(field.index)) > 0

    def test_the_same_wind_downwells_when_it_reverses(self):
        lat = np.arange(20.0, 40.0, 2.0)
        lon = np.arange(-130.0, -110.0, 2.0)
        u, v = _coast(lat, lon, land_columns=slice(-3, None))
        currents = _snapshot(lat, lon, u, v)
        wind = _snapshot(
            lat, lon, np.zeros((len(lat), len(lon))), np.full((len(lat), len(lon)), 8.0)
        )
        field = upwelling.detect(wind, currents)
        assert float(np.nanmean(field.index)) < 0

    def test_the_southern_hemisphere_reverses_too(self):
        """Identical geometry and identical wind, mirrored in latitude, must
        give the opposite sign. A hard-coded rotation passes the northern test
        and fails only here."""
        lon = np.arange(-130.0, -110.0, 2.0)
        north_lat = np.arange(20.0, 40.0, 2.0)
        south_lat = np.arange(-38.0, -18.0, 2.0)

        def run(lat):
            u, v = _coast(lat, lon, land_columns=slice(-3, None))
            wind = _snapshot(
                lat, lon, np.zeros((len(lat), len(lon))), np.full((len(lat), len(lon)), -8.0)
            )
            return float(np.nanmean(upwelling.detect(wind, _snapshot(lat, lon, u, v)).index))

        assert run(north_lat) > 0
        assert run(south_lat) < 0

    def test_the_equatorial_band_is_excluded(self):
        lat = np.arange(-4.0, 4.0, 1.0)
        lon = np.arange(-130.0, -110.0, 2.0)
        u, v = _coast(lat, lon, land_columns=slice(-3, None))
        wind = _snapshot(
            lat, lon, np.zeros((len(lat), len(lon))), np.full((len(lat), len(lon)), -8.0)
        )
        field = upwelling.detect(wind, _snapshot(lat, lon, u, v))
        assert not np.isfinite(field.index).any()
        assert field.coverage()["coastal_cells"] == 0
        assert "unavailable_reason" in field.coverage()

    def test_open_ocean_cells_are_not_scored(self):
        """The index is per metre of coastline. Mid-ocean there is no coastline
        to be per metre of."""
        lat = np.arange(20.0, 40.0, 2.0)
        lon = np.arange(-160.0, -110.0, 2.0)
        u, v = _coast(lat, lon, land_columns=slice(-2, None))
        wind = _snapshot(
            lat, lon, np.zeros((len(lat), len(lon))), np.full((len(lat), len(lon)), -8.0)
        )
        field = upwelling.detect(wind, _snapshot(lat, lon, u, v))
        # The far side of the basin is many cells from land.
        assert not np.isfinite(field.index[:, 0]).any()

    def test_land_cells_are_not_scored(self):
        lat = np.arange(20.0, 40.0, 2.0)
        lon = np.arange(-130.0, -110.0, 2.0)
        u, v = _coast(lat, lon, land_columns=slice(-3, None))
        wind = _snapshot(
            lat, lon, np.zeros((len(lat), len(lon))), np.full((len(lat), len(lon)), -8.0)
        )
        field = upwelling.detect(wind, _snapshot(lat, lon, u, v))
        assert not np.isfinite(field.index[:, -1]).any()

    def test_calm_wind_gives_a_zero_index_not_a_missing_one(self):
        """No wind is a real answer — the coast is neither upwelling nor
        downwelling — and must not read as 'no data'."""
        lat = np.arange(20.0, 40.0, 2.0)
        lon = np.arange(-130.0, -110.0, 2.0)
        u, v = _coast(lat, lon, land_columns=slice(-3, None))
        wind = _snapshot(
            lat, lon, np.zeros((len(lat), len(lon))), np.zeros((len(lat), len(lon)))
        )
        field = upwelling.detect(wind, _snapshot(lat, lon, u, v))
        scored = field.index[np.isfinite(field.index)]
        assert scored.size > 0
        assert np.allclose(scored, 0.0)

    def test_the_timestamp_is_the_stalest_input(self):
        """A composite is only as current as its oldest term — the same rule
        `services/drift.py` records for the drift field."""
        lat = np.arange(20.0, 40.0, 2.0)
        lon = np.arange(-130.0, -110.0, 2.0)
        u, v = _coast(lat, lon, land_columns=slice(-3, None))
        old = datetime(2026, 8, 16, tzinfo=UTC)
        wind = _snapshot(
            lat,
            lon,
            np.zeros((len(lat), len(lon))),
            np.full((len(lat), len(lon)), -8.0),
            stamp=old,
        )
        field = upwelling.detect(wind, _snapshot(lat, lon, u, v))
        assert field.timestamp == old

    def test_a_field_with_no_ocean_is_refused(self):
        lat = np.arange(20.0, 30.0, 2.0)
        lon = np.arange(-130.0, -120.0, 2.0)
        nan = np.full((len(lat), len(lon)), np.nan)
        wind = _snapshot(lat, lon, np.zeros_like(nan), np.zeros_like(nan))
        with pytest.raises(upwelling.UpwellingError, match="no ocean cells"):
            upwelling.detect(wind, _snapshot(lat, lon, nan, nan))


def _sst(lat, lon, anomaly, *, cold=None, stamp=None):
    """An SST anomaly field on its own, coarser grid.

    Given at a *different* resolution from the currents grid on purpose: OISST
    is 1 degree and the physics grid is 0.25, so every real corroboration goes
    through a resample and a test on a shared grid would never exercise it.
    """
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    anomaly = np.broadcast_to(np.asarray(anomaly, dtype="float32"), (lat.size, lon.size))
    if cold is None:
        # Below the seasonal p10 exactly when the anomaly is strongly negative,
        # which is what a real percentile climatology mostly does.
        cold = np.where(anomaly <= -1.0, -0.5, 0.5)
    return sst_anomaly.SstAnomalyField(
        anomaly=np.array(anomaly, dtype="float32"),
        cold_exceedance=np.broadcast_to(
            np.asarray(cold, dtype="float32"), (lat.size, lon.size)
        ).astype("float32"),
        latitude=lat,
        longitude=lon,
        timestamp=stamp or datetime(2026, 8, 10, tzinfo=UTC),
        baseline=(1991, 2020),
        source=sst_anomaly.OISST_RECORD,
    )


def _favourable_case(sst=None):
    """The canonical eastern-boundary case from TestDetect, plus an SST field."""
    lat = np.arange(20.0, 40.0, 2.0)
    lon = np.arange(-130.0, -110.0, 2.0)
    u, v = _coast(lat, lon, land_columns=slice(-3, None))
    wind = _snapshot(
        lat, lon, np.zeros((len(lat), len(lon))), np.full((len(lat), len(lon)), -8.0)
    )
    return upwelling.detect(wind, _snapshot(lat, lon, u, v), sst)


class TestCorroboration:
    """The SST half. Every assertion here is about keeping two claims separable:
    the wind index is an index whether or not the water agrees, and 'we could not
    look' must never render as 'we looked and found nothing'."""

    def test_the_index_is_identical_with_and_without_sst(self):
        """Corroboration adds a claim; it must never edit or filter the one the
        detector already made."""
        bare = _favourable_case()
        corroborated = _favourable_case(
            _sst(np.arange(15.0, 45.0, 1.0), np.arange(-135.0, -105.0, 1.0), -2.0)
        )
        np.testing.assert_array_equal(bare.index, corroborated.index)

    def test_cold_water_under_a_favourable_wind_is_confirmed(self):
        field = _favourable_case(
            _sst(np.arange(15.0, 45.0, 1.0), np.arange(-135.0, -105.0, 1.0), -2.0)
        )
        summary = field.corroboration()
        assert summary["available"]
        assert summary["favourable_cells_with_sst"] > 0
        assert summary["corroborated_cells"] == summary["favourable_cells_with_sst"]
        assert summary["below_p10_cells"] == summary["corroborated_cells"]

    def test_warm_water_under_a_favourable_wind_is_wind_only(self):
        """A real reading, not a missing one — the wind can be favourable before
        the water has responded, or while stratification suppresses it."""
        field = _favourable_case(
            _sst(np.arange(15.0, 45.0, 1.0), np.arange(-135.0, -105.0, 1.0), 0.4)
        )
        summary = field.corroboration()
        assert summary["available"]
        assert summary["corroborated_cells"] == 0
        assert summary["favourable_cells_with_sst"] > 0
        rows, columns = np.nonzero(np.isfinite(field.index))
        assert field.state_at(int(rows[0]), int(columns[0])) == "wind_only"

    def test_a_mild_cool_anomaly_is_the_weaker_tier(self):
        """Between the hand-chosen threshold and the seasonal p10, so it is
        `cool_anomaly` and is not reported as the strong claim."""
        field = _favourable_case(
            _sst(
                np.arange(15.0, 45.0, 1.0),
                np.arange(-135.0, -105.0, 1.0),
                -0.8,
                cold=0.5,
            )
        )
        rows, columns = np.nonzero(np.isfinite(field.index))
        assert field.state_at(int(rows[0]), int(columns[0])) == "cool_anomaly"
        assert field.corroboration()["below_p10_cells"] == 0

    def test_a_downwelling_coast_is_not_applicable_not_refuted(self):
        """A warm surface does not corroborate downwelling the way a cold one
        corroborates upwelling, so the test simply does not apply."""
        lat = np.arange(20.0, 40.0, 2.0)
        lon = np.arange(-130.0, -110.0, 2.0)
        u, v = _coast(lat, lon, land_columns=slice(-3, None))
        wind = _snapshot(
            lat, lon, np.zeros((len(lat), len(lon))), np.full((len(lat), len(lon)), 8.0)
        )
        field = upwelling.detect(
            wind,
            _snapshot(lat, lon, u, v),
            _sst(np.arange(15.0, 45.0, 1.0), np.arange(-135.0, -105.0, 1.0), -2.0),
        )
        rows, columns = np.nonzero(np.isfinite(field.index))
        assert field.state_at(int(rows[0]), int(columns[0])) == "not_applicable"
        assert field.corroboration()["corroborated_cells"] == 0

    def test_water_outside_the_sst_grid_is_unavailable_not_uncorroborated(self):
        """The distinction the whole block exists for. A coast OISST does not
        cover is neither confirmed nor refuted, and it must not enter the
        denominator of the corroborated fraction."""
        field = _favourable_case(
            # An SST field on the other side of the planet.
            _sst(np.arange(15.0, 45.0, 1.0), np.arange(20.0, 50.0, 1.0), -2.0)
        )
        summary = field.corroboration()
        assert summary["available"]
        assert summary["favourable_cells"] > 0
        assert summary["favourable_cells_with_sst"] == 0
        assert summary["corroborated_fraction"] is None
        rows, columns = np.nonzero(np.isfinite(field.index))
        assert field.state_at(int(rows[0]), int(columns[0])) == "sst_unavailable"

    def test_no_sst_at_all_says_so(self):
        summary = _favourable_case().corroboration()
        assert summary["available"] is False
        assert "climatology" in summary["unavailable_reason"]

    def test_stale_sst_is_refused_with_its_age(self):
        """OISST's own lag is a week or more, so this is a cap on staleness
        beyond that, not a promise of simultaneity."""
        old = datetime(2026, 8, 17, tzinfo=UTC) - timedelta(
            days=upwelling.MAX_SST_LAG_DAYS + 5
        )
        field = _favourable_case(
            _sst(
                np.arange(15.0, 45.0, 1.0),
                np.arange(-135.0, -105.0, 1.0),
                -2.0,
                stamp=old,
            )
        )
        summary = field.corroboration()
        assert summary["available"] is False
        assert "days older" in summary["unavailable_reason"]

    def test_the_lag_is_published_rather_than_folded_into_one_stamp(self):
        """`services/drift.py` reports the stalest of its terms because they are
        the same quantity. These are two different observations, so hiding the
        gap inside one timestamp would assert simultaneity that does not hold."""
        field = _favourable_case(
            _sst(np.arange(15.0, 45.0, 1.0), np.arange(-135.0, -105.0, 1.0), -2.0)
        )
        assert field.timestamp == datetime(2026, 8, 17, tzinfo=UTC)
        assert field.sst_timestamp == datetime(2026, 8, 10, tzinfo=UTC)
        assert field.corroboration()["lag_hours"] == pytest.approx(168.0)

    def test_cells_carry_the_state_and_a_null_anomaly_never_a_zero(self):
        field = _favourable_case(
            _sst(np.arange(15.0, 45.0, 1.0), np.arange(20.0, 50.0, 1.0), -2.0)
        )
        rows, columns = np.nonzero(np.isfinite(field.index))
        row, column = int(rows[0]), int(columns[0])
        # `cells()` reads the module cache, so the per-cell shape is asserted
        # through the same construction it uses.
        assert field.state_at(row, column) == "sst_unavailable"
        assert not np.isfinite(field.sst_anomaly[row, column])

    def test_the_control_fraction_rides_along_as_the_base_rate(self):
        """A corroborated fraction with no base rate beside it is unreadable.

        Measured on the live field 2026-08-17, cool water is nearly as common
        under downwelling-favourable wind (17.2%) as under favourable wind
        (19.9%) — so a reader given only the second number would take a weak
        coincidence for a confirmed mechanism. The control is computed here so
        it cannot be forgotten at the call site.
        """
        lat = np.arange(20.0, 40.0, 2.0)
        lon = np.arange(-130.0, -110.0, 2.0)
        u, v = _coast(lat, lon, land_columns=slice(-3, None))
        # Wind reversed halfway up the coast, so both regimes are present in one
        # field and the control has cells to count.
        wind_v = np.full((len(lat), len(lon)), -8.0)
        wind_v[: len(lat) // 2] = 8.0
        wind = _snapshot(lat, lon, np.zeros((len(lat), len(lon))), wind_v)
        field = upwelling.detect(
            wind,
            _snapshot(lat, lon, u, v),
            _sst(np.arange(15.0, 45.0, 1.0), np.arange(-135.0, -105.0, 1.0), -2.0),
        )
        summary = field.corroboration()
        assert summary["control_cells"] > 0
        # Uniformly cold water: every regime is "cool", which is exactly the
        # case the control exists to expose.
        assert summary["control_cool_fraction"] == 1.0
        assert summary["corroborated_fraction"] == 1.0

    def test_an_sst_field_newer_than_the_wind_is_still_bounded(self):
        """The gap can go negative — the wind blend lagged the currents by 1.3
        days on 2026-08-17, so a fresher SST field than the wind is a real
        state. A bare `>` on the signed lag would wave through an SST field
        arbitrarily far in the *future* of the wind."""
        ahead = datetime(2026, 8, 17, tzinfo=UTC) + timedelta(
            days=upwelling.MAX_SST_LAG_DAYS + 5
        )
        field = _favourable_case(
            _sst(
                np.arange(15.0, 45.0, 1.0),
                np.arange(-135.0, -105.0, 1.0),
                -2.0,
                stamp=ahead,
            )
        )
        summary = field.corroboration()
        assert summary["available"] is False
        assert "newer than the wind" in summary["unavailable_reason"]

    def test_a_modest_negative_lag_is_accepted(self):
        """1.3 days ahead is the measured normal case, not an error."""
        ahead = datetime(2026, 8, 17, tzinfo=UTC) + timedelta(days=1, hours=8)
        field = _favourable_case(
            _sst(
                np.arange(15.0, 45.0, 1.0),
                np.arange(-135.0, -105.0, 1.0),
                -2.0,
                stamp=ahead,
            )
        )
        assert field.corroboration()["available"] is True
