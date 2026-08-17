"""Tests for coastal upwelling detection.

The hemisphere test is the one that matters most. Ekman transport is 90 degrees
to the right of the wind in the north and to the left in the south, so a
detector that hard-codes one rotation is correct in one hemisphere and
confidently wrong in the other — the identical failure `services/eddies.py`
records for eddy polarity, in a field that still looks entirely plausible.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from scipy.interpolate import RegularGridInterpolator

from services import upwelling
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
