"""The combined drift field.

The properties worth pinning here are the ones that fail *silently* — a drift
field with a sign error still animates, at a plausible speed, in the wrong
direction, and a leeway term summed as a bearing rather than as components
still produces a number for every cell.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from services import drift, vector_field
from services.vector_source import VectorSnapshot


def _snapshot(key, lat, lon, u, v, timestamp):
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    return VectorSnapshot(
        key=key,
        lat=lat,
        lon=lon,
        u=u,
        v=v,
        u_interp=vector_field.build_interpolator(lat, lon, u),
        v_interp=vector_field.build_interpolator(lat, lon, v),
        lon_min=float(lon[0]),
        timestamp=timestamp,
    )


@pytest.fixture
def stamps():
    from datetime import UTC, datetime

    return (
        datetime(2026, 8, 14, 12, tzinfo=UTC),
        datetime(2026, 8, 14, 9, tzinfo=UTC),
        datetime(2026, 8, 14, 6, tzinfo=UTC),
    )


def test_resolve_alpha_prefers_the_named_object_over_a_raw_number():
    # A client that sent a preset asked for whatever this codebase believes that
    # object's coefficient is, not for a number it happened to also send.
    assert drift.resolve_alpha(0.99, "person_in_water") == 0.035
    assert drift.resolve_alpha(None, "water_only") == 0.0
    assert drift.resolve_alpha(0.02, None) == 0.02
    assert drift.resolve_alpha(None, None) == 0.0


def test_resolve_alpha_rejects_a_coefficient_nothing_floats_at():
    with pytest.raises(drift.DriftError):
        drift.resolve_alpha(0.9, None)
    with pytest.raises(drift.DriftError):
        drift.resolve_alpha(-0.1, None)
    with pytest.raises(drift.DriftError):
        drift.resolve_alpha(None, "spaceship")


def test_the_water_terms_are_summed_as_components(monkeypatch, stamps):
    """Current and Stokes drift add as vectors, not as speeds.

    The case chosen is the one where the two conventions disagree most: two
    equal fields at right angles. Summed as components the result is
    sqrt(2) at 45 degrees; summed as speeds it would be 2, and summed as
    bearings it would be a right angle away from either.
    """
    lat = np.array([-1.0, 0.0, 1.0])
    lon = np.array([-1.0, 0.0, 1.0])
    ones = np.ones((3, 3))
    zeros = np.zeros((3, 3))

    currents = _snapshot("currents", lat, lon, ones, zeros, stamps[0])   # due east
    stokes = _snapshot("stokes_drift", lat, lon, zeros, ones, stamps[1])  # due north
    wind = _snapshot("wind", lat, lon, zeros, zeros, stamps[2])

    monkeypatch.setattr(drift.copernicus_currents, "snapshot", lambda: currents)
    monkeypatch.setattr(drift.stokes_drift, "snapshot", lambda: stokes)
    monkeypatch.setattr(drift.copernicus_wind, "snapshot", lambda: wind)

    composed = drift._build_composed()

    assert np.allclose(composed.water_u, 1.0)
    assert np.allclose(composed.water_v, 1.0)
    assert math.isclose(
        math.hypot(composed.water_u[1, 1], composed.water_v[1, 1]), math.sqrt(2.0)
    )


def test_leeway_scales_only_the_wind_term(monkeypatch, stamps):
    lat = np.array([-1.0, 0.0, 1.0])
    lon = np.array([-1.0, 0.0, 1.0])
    ones = np.ones((3, 3))
    zeros = np.zeros((3, 3))

    currents = _snapshot("currents", lat, lon, ones * 0.5, zeros, stamps[0])
    stokes = _snapshot("stokes_drift", lat, lon, ones * 0.1, zeros, stamps[1])
    wind = _snapshot("wind", lat, lon, ones * 10.0, zeros, stamps[2])

    monkeypatch.setattr(drift.copernicus_currents, "snapshot", lambda: currents)
    monkeypatch.setattr(drift.stokes_drift, "snapshot", lambda: stokes)
    monkeypatch.setattr(drift.copernicus_wind, "snapshot", lambda: wind)

    composed = drift._build_composed()

    # Water alone.
    assert np.allclose(composed.water_u, 0.6)
    # A 10 m/s wind at 3.5% adds 0.35 m/s — more than half the water term, which
    # is exactly why alpha cannot be a constant baked into the field.
    total = composed.water_u + 0.035 * composed.wind_u
    assert np.allclose(total, 0.95)


def test_a_cold_upstream_names_which_field_is_missing(monkeypatch):
    from services.vector_source import VectorSourceError

    def cold():
        raise VectorSourceError("not yet available")

    monkeypatch.setattr(drift.copernicus_currents, "snapshot", cold)

    with pytest.raises(drift.DriftError) as excinfo:
        drift._build_composed()
    # "a field is missing" is not actionable; "the surface currents field" is.
    assert "surface currents" in str(excinfo.value)


def test_coverage_is_the_intersection_not_the_union(monkeypatch, stamps):
    """A cell with current but no Stokes drift stays empty.

    The tempting alternative — treat missing Stokes as zero — is not neutral:
    Stokes drift is largest in exactly the high-sea-state water where the wave
    product is most likely to be masked, so the substituted zero would bias the
    field low precisely where it matters most.
    """
    lat = np.array([-1.0, 0.0, 1.0])
    lon = np.array([-1.0, 0.0, 1.0])
    currents_u = np.ones((3, 3))
    stokes_u = np.ones((3, 3))
    stokes_u[0, 0] = np.nan
    zeros = np.zeros((3, 3))

    monkeypatch.setattr(
        drift.copernicus_currents,
        "snapshot",
        lambda: _snapshot("currents", lat, lon, currents_u, zeros, stamps[0]),
    )
    monkeypatch.setattr(
        drift.stokes_drift,
        "snapshot",
        lambda: _snapshot("stokes_drift", lat, lon, stokes_u, zeros, stamps[1]),
    )
    monkeypatch.setattr(
        drift.copernicus_wind,
        "snapshot",
        lambda: _snapshot("wind", lat, lon, zeros, zeros, stamps[2]),
    )

    composed = drift._build_composed()
    assert np.isnan(composed.water_u[0, 0])
    assert np.isfinite(composed.water_u[1, 1])


def test_the_reported_timestamp_is_the_stalest_term(monkeypatch, stamps):
    """A composite is only as current as its oldest input.

    Reporting the newest would overstate freshness by however far the wind blend
    lags — which is routinely hours, and is invisible to a reader looking at one
    timestamp.
    """
    lat = np.array([-1.0, 0.0, 1.0])
    lon = np.array([-1.0, 0.0, 1.0])
    ones = np.ones((3, 3))

    monkeypatch.setattr(
        drift.copernicus_currents,
        "snapshot",
        lambda: _snapshot("currents", lat, lon, ones, ones, stamps[0]),
    )
    monkeypatch.setattr(
        drift.stokes_drift,
        "snapshot",
        lambda: _snapshot("stokes_drift", lat, lon, ones, ones, stamps[1]),
    )
    monkeypatch.setattr(
        drift.copernicus_wind,
        "snapshot",
        lambda: _snapshot("wind", lat, lon, ones, ones, stamps[2]),
    )

    drift._composed = drift._build_composed()
    drift._textures.clear()
    try:
        meta = drift.get_meta(0.0)
        assert meta["timestamp"] == min(stamps).isoformat()
        assert set(meta["component_timestamps"]) == {"currents", "stokes_drift", "wind"}
        assert meta["direction_convention"] == "toward"
    finally:
        drift._composed = None
        drift._textures.clear()


def test_wind_components_are_reconstructed_from_the_from_convention():
    """A wind reported as "from the north" must push water southward.

    The one place in this module where a sign error is invisible: the field
    would still animate at the right speed, in the reverse direction, over a
    plausible-looking ocean.
    """
    class _FakeWind:
        @staticmethod
        def get_point(lat, lon):
            return {
                "speed_ms": 10.0,
                # Wind FROM the north.
                "direction_from_deg": 0.0,
                "is_land_or_no_data": False,
                "timestamp": "2026-08-14T06:00:00+00:00",
            }

    class _Still:
        @staticmethod
        def get_point(lat, lon):
            return {
                "speed_ms": 0.0,
                "u_ms": 0.0,
                "v_ms": 0.0,
                "direction_toward_deg": 0.0,
                "is_land_or_no_data": False,
                "timestamp": "2026-08-14T12:00:00+00:00",
            }

    import services.drift as module

    original = (module.copernicus_currents, module.stokes_drift, module.copernicus_wind)
    module.copernicus_currents = _Still
    module.stokes_drift = _Still
    module.copernicus_wind = _FakeWind
    try:
        point = module.get_point(10.0, 75.0, alpha=0.035)
    finally:
        module.copernicus_currents, module.stokes_drift, module.copernicus_wind = original

    # 3.5% of 10 m/s, carried southward: v is negative, u is ~0.
    assert point["terms"]["wind_leeway"]["v_ms"] == pytest.approx(-10.0, abs=1e-6)
    assert point["terms"]["wind_leeway"]["u_ms"] == pytest.approx(0.0, abs=1e-6)
    assert point["speed_ms"] == pytest.approx(0.35, abs=1e-6)
    # Toward the south.
    assert point["direction_toward_deg"] == pytest.approx(180.0, abs=0.1)
    assert point["direction_compass"] == "S"


def test_a_point_answers_from_the_water_terms_when_wind_is_cold():
    """Leeway at alpha=0 contributes nothing, so its absence must not blank a
    point the water terms can answer."""

    class _Water:
        @staticmethod
        def get_point(lat, lon):
            return {
                "speed_ms": 0.5,
                "u_ms": 0.5,
                "v_ms": 0.0,
                "is_land_or_no_data": False,
                "timestamp": "2026-08-14T12:00:00+00:00",
            }

    class _Cold:
        @staticmethod
        def get_point(lat, lon):
            from services.vector_source import VectorSourceError

            raise VectorSourceError("wind data not yet available")

    import services.drift as module

    original = (module.copernicus_currents, module.stokes_drift, module.copernicus_wind)
    module.copernicus_currents = _Water
    module.stokes_drift = _Water
    module.copernicus_wind = _Cold
    try:
        point = module.get_point(10.0, 75.0, alpha=0.0)
    finally:
        module.copernicus_currents, module.stokes_drift, module.copernicus_wind = original

    assert point["is_land_or_no_data"] is False
    assert point["speed_ms"] == pytest.approx(1.0)
    assert "wind" in point["degraded_reason"]
