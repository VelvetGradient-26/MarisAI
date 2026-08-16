"""Eddy detection.

Every property pinned here fails *silently* in production: a detector with the
polarity convention inverted still returns a plausible number of plausible
features at plausible positions, and so does one whose centroid arithmetic
cannot cross the dateline. The only way to assert that what comes out is what
went in is to put a known vortex in and look for it.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest

from services import eddies, vector_field
from services.vector_source import VectorSnapshot

TIMESTAMP = datetime(2026, 8, 15, 12, tzinfo=UTC)


def _snapshot(lat, lon, u, v, timestamp=TIMESTAMP):
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    return VectorSnapshot(
        key="currents",
        lat=lat,
        lon=lon,
        u=u,
        v=v,
        u_interp=vector_field.build_interpolator(lat, lon, u),
        v_interp=vector_field.build_interpolator(lat, lon, v),
        lon_min=float(lon[0]),
        timestamp=timestamp,
    )


def _grid(lat_range=(10.0, 40.0), lon_range=(50.0, 90.0), step=0.25):
    lat = np.arange(lat_range[0], lat_range[1], step)
    lon = np.arange(lon_range[0], lon_range[1], step)
    return lat, lon


def _vortex(lat, lon, *, centre_lat, centre_lon, radius_km, peak_ms, sign):
    """A solid-body core with a decaying skirt — a Rankine-ish vortex.

    `sign` is the sense of rotation in the mathematical convention: +1 is
    counter-clockwise seen from above, which is cyclonic in the northern
    hemisphere and anticyclonic in the southern.
    """
    mesh_lat, mesh_lon = np.meshgrid(lat, lon, indexing="ij")
    metres_per_degree = eddies.EARTH_RADIUS_M * math.pi / 180.0
    dy = (mesh_lat - centre_lat) * metres_per_degree
    dx = (mesh_lon - centre_lon) * metres_per_degree * math.cos(math.radians(centre_lat))
    distance = np.hypot(dx, dy)

    core = radius_km * 1000.0
    # Speed rises linearly to the core radius then falls off, so the interior is
    # rotation-dominated (W < 0) and the exterior is strain-dominated.
    speed = np.where(
        distance <= core,
        peak_ms * distance / core,
        peak_ms * np.exp(-(distance - core) / core),
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        unit_x = np.where(distance > 0, dx / distance, 0.0)
        unit_y = np.where(distance > 0, dy / distance, 0.0)
    # Tangential: rotate the radial unit vector by 90 degrees.
    u = -sign * speed * unit_y
    v = sign * speed * unit_x
    return u, v


# ------------------------------------------------------------- the maths


def test_okubo_weiss_is_negative_inside_a_vortex_and_positive_in_pure_shear():
    lat, lon = _grid()
    u, v = _vortex(lat, lon, centre_lat=25.0, centre_lon=70.0, radius_km=80.0, peak_ms=0.6, sign=1)
    w, vorticity = eddies.okubo_weiss(u, v, lat, lon)

    centre_row = int(np.argmin(np.abs(lat - 25.0)))
    centre_col = int(np.argmin(np.abs(lon - 70.0)))
    assert w[centre_row, centre_col] < 0
    assert vorticity[centre_row, centre_col] > 0

    # A pure zonal shear flow has strain and no net rotation beating it, so W
    # must come out positive everywhere — the case the threshold must reject.
    shear_u = np.tile((lat - lat.mean())[:, None], (1, lon.size)) * 1e-5
    shear_v = np.zeros_like(shear_u)
    shear_w, _ = eddies.okubo_weiss(shear_u, shear_v, lat, lon)
    assert np.nanmin(shear_w[2:-2, 2:-2]) >= 0


def test_vorticity_sign_follows_the_sense_of_rotation():
    lat, lon = _grid()
    clockwise = _vortex(
        lat, lon, centre_lat=25.0, centre_lon=70.0, radius_km=80.0, peak_ms=0.6, sign=-1
    )
    _, vorticity = eddies.okubo_weiss(*clockwise, lat, lon)
    centre = (int(np.argmin(np.abs(lat - 25.0))), int(np.argmin(np.abs(lon - 70.0))))
    assert vorticity[centre] < 0


# -------------------------------------------------------------- detection


def test_a_northern_counter_clockwise_vortex_is_cyclonic():
    lat, lon = _grid()
    u, v = _vortex(lat, lon, centre_lat=25.0, centre_lon=70.0, radius_km=90.0, peak_ms=0.6, sign=1)
    detection = eddies.detect(_snapshot(lat, lon, u, v))

    assert len(detection.eddies) >= 1
    found = detection.eddies[0]
    assert found.polarity == "cyclonic"
    assert found.latitude == pytest.approx(25.0, abs=0.5)
    assert found.longitude == pytest.approx(70.0, abs=0.5)


def test_the_same_rotation_is_anticyclonic_in_the_southern_hemisphere():
    """The convention, and the reason it is not `sign(vorticity)`.

    Cyclonic means rotating with the planet. An identical counter-clockwise
    vortex is cyclonic at 25N and anticyclonic at 25S, so a detector that read
    polarity off the sign of vorticity alone would be right in one hemisphere
    and confidently wrong in the other.
    """
    lat, lon = _grid(lat_range=(-40.0, -10.0))
    u, v = _vortex(lat, lon, centre_lat=-25.0, centre_lon=70.0, radius_km=90.0, peak_ms=0.6, sign=1)
    detection = eddies.detect(_snapshot(lat, lon, u, v))

    assert len(detection.eddies) >= 1
    assert detection.eddies[0].polarity == "anticyclonic"


def test_reported_radius_tracks_the_vortex_that_was_put_in():
    """Not an exact match, and it should not be.

    The reported radius is the equivalent radius of the region where rotation
    beats strain, which is a fraction of the radius of the vortex it came from —
    the test is that a bigger eddy reads bigger, and that both land in the
    mesoscale range rather than at the filter's floor.
    """
    lat, lon = _grid(lon_range=(50.0, 120.0))
    small_u, small_v = _vortex(
        lat, lon, centre_lat=25.0, centre_lon=70.0, radius_km=70.0, peak_ms=0.6, sign=1
    )
    large_u, large_v = _vortex(
        lat, lon, centre_lat=25.0, centre_lon=70.0, radius_km=150.0, peak_ms=0.6, sign=1
    )

    small = eddies.detect(_snapshot(lat, lon, small_u, small_v)).eddies[0]
    large = eddies.detect(_snapshot(lat, lon, large_u, large_v)).eddies[0]

    assert large.radius_km > small.radius_km
    assert eddies.MIN_RADIUS_KM <= small.radius_km <= eddies.MAX_RADIUS_KM
    assert eddies.MIN_RADIUS_KM <= large.radius_km <= eddies.MAX_RADIUS_KM


def test_two_separated_vortices_are_two_eddies_with_opposite_polarity():
    lat, lon = _grid(lon_range=(50.0, 110.0))
    left = _vortex(lat, lon, centre_lat=25.0, centre_lon=62.0, radius_km=90.0, peak_ms=0.6, sign=1)
    right = _vortex(lat, lon, centre_lat=25.0, centre_lon=98.0, radius_km=90.0, peak_ms=0.6, sign=-1)
    u = left[0] + right[0]
    v = left[1] + right[1]

    detection = eddies.detect(_snapshot(lat, lon, u, v))
    polarities = {eddy.polarity for eddy in detection.eddies}
    assert len(detection.eddies) >= 2
    assert polarities == {"cyclonic", "anticyclonic"}


def test_the_equatorial_band_is_excluded_rather_than_labelled():
    """f goes to zero at the equator, so polarity there is a coin flip."""
    lat = np.arange(-20.0, 20.0, 0.25)
    lon = np.arange(50.0, 90.0, 0.25)
    on_equator = _vortex(
        lat, lon, centre_lat=0.0, centre_lon=62.0, radius_km=90.0, peak_ms=0.6, sign=1
    )
    off_equator = _vortex(
        lat, lon, centre_lat=15.0, centre_lon=80.0, radius_km=90.0, peak_ms=0.6, sign=1
    )
    u = on_equator[0] + off_equator[0]
    v = on_equator[1] + off_equator[1]

    detection = eddies.detect(_snapshot(lat, lon, u, v))
    # The one at 15N is found; the one on the equator is not reported at all,
    # rather than reported with a polarity that means nothing there.
    assert any(eddy.latitude == pytest.approx(15.0, abs=1.0) for eddy in detection.eddies)
    assert all(abs(eddy.latitude) >= eddies.EQUATORIAL_BAND_DEG for eddy in detection.eddies)

    # And a grid that is *entirely* inside the band has nothing to say, which is
    # an error rather than an empty list — "no eddies here" would be a claim.
    narrow = np.arange(-4.0, 4.0, 0.25)
    with pytest.raises(eddies.EddyError):
        eddies.detect(_snapshot(narrow, lon, u[: narrow.size], v[: narrow.size]))


def test_a_uniform_field_raises_rather_than_returning_nothing():
    """Zero variance means the threshold is undefined, which is a different
    answer from "no eddies here" and must not be dressed as one."""
    lat, lon = _grid()
    u = np.full((lat.size, lon.size), 0.3)
    v = np.zeros_like(u)
    with pytest.raises(eddies.EddyError):
        eddies.detect(_snapshot(lat, lon, u, v))


# -------------------------------------------------------------- the seam


def test_a_vortex_on_the_dateline_is_one_eddy_at_the_dateline():
    """The seam, in both places it bites.

    `ndimage.label` sees a flat array, so a feature straddling the antimeridian
    arrives as two components at opposite edges; and an arithmetic mean of +179
    and -179 is 0, which relocates a Pacific eddy to the Gulf of Guinea.
    """
    lat = np.arange(10.0, 40.0, 0.25)
    lon = np.arange(-180.0, 180.0, 0.25)  # global, so the grid is periodic

    mesh_lat, mesh_lon = np.meshgrid(lat, lon, indexing="ij")
    # Build the vortex in a shifted frame so it sits on the dateline without
    # the helper having to wrap.
    shifted = (mesh_lon + 360.0) % 360.0  # 0..360, dateline at 180
    metres_per_degree = eddies.EARTH_RADIUS_M * math.pi / 180.0
    dy = (mesh_lat - 25.0) * metres_per_degree
    dx = (shifted - 180.0) * metres_per_degree * math.cos(math.radians(25.0))
    distance = np.hypot(dx, dy)
    core = 90_000.0
    speed = np.where(distance <= core, 0.6 * distance / core, 0.6 * np.exp(-(distance - core) / core))
    with np.errstate(invalid="ignore", divide="ignore"):
        u = -speed * np.where(distance > 0, dy / distance, 0.0)
        v = speed * np.where(distance > 0, dx / distance, 0.0)

    detection = eddies.detect(_snapshot(lat, lon, u, v))
    assert len(detection.eddies) == 1
    found = detection.eddies[0]
    assert abs(found.longitude) == pytest.approx(180.0, abs=1.0)
    assert found.latitude == pytest.approx(25.0, abs=0.5)


def test_a_bbox_across_the_antimeridian_is_a_real_request():
    eddy = eddies.Eddy(
        latitude=25.0,
        longitude=179.0,
        polarity="cyclonic",
        radius_km=90.0,
        area_km2=25_000.0,
        vorticity=1e-5,
        max_speed=0.6,
        mean_speed=0.3,
        cells=50,
    )
    assert eddies._in_bbox(eddy, (10.0, 170.0, 40.0, -170.0))
    assert not eddies._in_bbox(eddy, (10.0, -170.0, 40.0, 170.0))
    assert not eddies._in_bbox(eddy, (30.0, 170.0, 40.0, -170.0))


def test_white_noise_produces_only_floor_sized_features():
    """The method's known weakness, pinned rather than wished away.

    The threshold is relative to the variance of the field, so a field with no
    structure at all still has cells below −0.2σ and the detector *will* return
    something. What must hold is that nothing large survives: noise cannot
    manufacture a 200 km eddy, so a big detection is evidence of real structure
    even though a small one may not be.
    """
    lat, lon = _grid()
    rng = np.random.default_rng(0)
    u = rng.normal(0, 0.2, (lat.size, lon.size))
    v = rng.normal(0, 0.2, (lat.size, lon.size))

    detection = eddies.detect(_snapshot(lat, lon, u, v))
    assert all(eddy.radius_km < 60 for eddy in detection.eddies)


def test_nearest_reports_inside_and_distance(monkeypatch):
    """The brief's question, which is not the map's.

    "Is this coordinate in an eddy" needs the distance reported either way — a
    point 400 km from the nearest feature is a real answer, and omitting the row
    would read as "no eddies anywhere".
    """
    lat, lon = _grid()
    u, v = _vortex(lat, lon, centre_lat=25.0, centre_lon=70.0, radius_km=90.0, peak_ms=0.6, sign=1)
    detection = eddies.detect(_snapshot(lat, lon, u, v))
    monkeypatch.setattr(eddies, "_current_detection", lambda: detection)

    inside = eddies.nearest(25.0, 70.0)
    assert inside is not None
    assert inside["inside"] is True
    assert inside["distance_km"] < 30

    # Far east of the vortex, still on the same grid.
    outside = eddies.nearest(25.0, 88.0)
    assert outside is not None
    assert outside["inside"] is False
    # ~18 degrees of longitude at 25N is roughly 1,800 km.
    assert 1500 < outside["distance_km"] < 2000


def test_nearest_is_none_when_nothing_was_detected(monkeypatch):
    """Distinct from "the detector is cold", which raises instead."""
    empty = eddies.Detection(
        eddies=(),
        timestamp=TIMESTAMP,
        computed_at=TIMESTAMP,
        threshold=-1.0,
        sigma_w=5.0,
        grid_spacing_deg=0.25,
        min_resolvable_radius_km=eddies.MIN_RADIUS_KM,
    )
    monkeypatch.setattr(eddies, "_current_detection", lambda: empty)
    assert eddies.nearest(25.0, 70.0) is None


def test_land_holes_do_not_produce_features():
    """NaN cells must not become a detection — the mask has to survive the
    derivative stencil, and a NaN comparison is False, not True."""
    lat, lon = _grid()
    u, v = _vortex(lat, lon, centre_lat=25.0, centre_lon=70.0, radius_km=90.0, peak_ms=0.6, sign=1)
    u = u.copy()
    v = v.copy()
    u[:20, :20] = np.nan
    v[:20, :20] = np.nan

    detection = eddies.detect(_snapshot(lat, lon, u, v))
    for eddy in detection.eddies:
        assert eddy.latitude > lat[20] or eddy.longitude > lon[20]
