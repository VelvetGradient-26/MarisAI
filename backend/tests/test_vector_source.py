"""The generic live vector field: conventions, depth snapping, honest absence.

`copernicus_wind` and `copernicus_currents` were two copies of the same 250
lines, and Stokes drift plus currents-at-depth would have made four. What that
generalisation must not lose is the part that differs per field — and every one
of those differences fails silently, by drawing a plausible ocean that is wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from scipy.interpolate import RegularGridInterpolator

from services import currents_depth, stokes_drift, vector_field, vector_source
from services.copernicus_currents import SPEC as CURRENTS_SPEC
from services.vector_source import VectorSource, VectorSourceError, VectorSourceSpec


def _interp(value: float) -> RegularGridInterpolator:
    return RegularGridInterpolator(
        (np.array([-1.0, 1.0]), np.array([-1.0, 1.0])),
        np.full((2, 2), value),
        bounds_error=False,
        fill_value=np.nan,
    )


def _texture(u: float, v: float) -> vector_field.FieldTexture:
    """A real encoded texture, not a stub: `meta()` reads its bounds and its
    u/v range, and those are exactly the values the shader decodes with."""
    lat = np.linspace(-80.0, 89.0, 8)
    lon = np.linspace(-180.0, 179.0, 16)
    return vector_field.encode(
        np.full((8, 16), u), np.full((8, 16), v), lat, lon, downsample=1
    )


def _warm(source: VectorSource, u: float, v: float, depth: float | None = None) -> None:
    """Install a cache without touching the network."""
    source._cache = vector_source._Cache(
        u_interp=_interp(u),
        v_interp=_interp(v),
        lon_min=-1.0,
        texture=_texture(u, v),
        timestamp=datetime(2026, 8, 13, tzinfo=UTC),
        fetched_at=datetime(2026, 8, 13, tzinfo=UTC),
        depth_m=depth,
    )


def _spec(convention: str) -> VectorSourceSpec:
    return VectorSourceSpec(
        key="test",
        dataset_id="test",
        u_field="u",
        v_field="v",
        source_label="test",
        unit="m/s",
        speed_max_legend=2.0,
        convention=convention,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------
# Direction conventions
# --------------------------------------------------------------------------


def test_a_toward_field_names_where_the_water_goes():
    """Northward flow (u=0, v=+1) is a *north* current, 0 degrees."""
    source = VectorSource(_spec("toward"))
    _warm(source, u=0.0, v=1.0)

    point = source.point(0.0, 0.0)

    assert point["direction_toward_deg"] == pytest.approx(0.0)
    assert point["direction_compass"] == "N"
    assert "direction_from_deg" not in point


def test_a_from_field_names_where_the_wind_came_from():
    """The same vector as wind is 180 degrees — a *southerly*, blowing from the
    south. Reusing the currents formula here would draw every arrow backwards
    and look entirely plausible, which is why the convention is declared and the
    field is named for it rather than being a bare `direction_deg`."""
    source = VectorSource(_spec("from"))
    _warm(source, u=0.0, v=1.0)

    point = source.point(0.0, 0.0)

    assert point["direction_from_deg"] == pytest.approx(180.0)
    assert point["direction_compass"] == "S"
    assert "direction_toward_deg" not in point


def test_the_two_conventions_are_exactly_opposite():
    toward = VectorSource(_spec("toward"))
    away = VectorSource(_spec("from"))
    _warm(toward, u=0.7, v=-0.3)
    _warm(away, u=0.7, v=-0.3)

    a = toward.point(0.0, 0.0)["direction_toward_deg"]
    b = away.point(0.0, 0.0)["direction_from_deg"]

    assert (b - a) % 360 == pytest.approx(180.0)


def test_the_shipped_fields_use_the_conventions_their_science_requires():
    """Currents and Stokes drift are transports — named for where the water
    goes. Wind is named for where it comes from. Pinned because the two are 180
    degrees apart and a wrong one is invisible on screen."""
    assert CURRENTS_SPEC.convention == "toward"
    assert stokes_drift.SPEC.convention == "toward"


# --------------------------------------------------------------------------
# Absence
# --------------------------------------------------------------------------


def test_land_is_reported_as_no_data_rather_than_as_slack_water():
    """A NaN must never become 0 m/s. Zero velocity is a real reading — slack
    water — and the map has no way to tell the two apart afterwards."""
    source = VectorSource(_spec("toward"))
    source._cache = vector_source._Cache(
        u_interp=_interp(np.nan),
        v_interp=_interp(np.nan),
        lon_min=-1.0,
        texture=_texture(0.0, 0.0),
        timestamp=datetime(2026, 8, 13, tzinfo=UTC),
        fetched_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    point = source.point(0.0, 0.0)

    assert point["is_land_or_no_data"] is True
    assert point["speed_ms"] is None
    assert point["direction_toward_deg"] is None


def test_an_empty_cache_raises_the_fields_own_error_type():
    """So a thin router can map one service's failure to one status code."""

    class OwnError(VectorSourceError):
        pass

    source = VectorSource(
        VectorSourceSpec(
            key="test",
            dataset_id="test",
            u_field="u",
            v_field="v",
            source_label="test",
            unit="m/s",
            speed_max_legend=1.0,
            convention="toward",
            error_type=OwnError,
        )
    )

    with pytest.raises(OwnError, match="not yet available"):
        source.point(0.0, 0.0)


# --------------------------------------------------------------------------
# Depth
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(0.0, 0.0), (30.0, 50.0), (180.0, 200.0), (900.0, 1000.0), (5000.0, 1000.0)],
)
def test_a_requested_depth_snaps_to_an_offered_level(requested, expected):
    assert currents_depth.resolve_depth(requested) == expected


def test_the_model_level_that_answered_is_reported_not_rounded_away():
    """200 m resolves to the model's 186.13 m. A user told "200 m" when the
    answer came from 186 m has been given a number the product does not carry."""
    source = currents_depth._sources[200.0]
    _warm(source, u=0.1, v=0.0, depth=186.13)

    meta = source.meta()

    assert meta["depth_m"] == pytest.approx(186.13)
    assert meta["requested_depth_m"] == 200.0


def test_an_unfetched_level_says_why_rather_than_vanishing():
    """Same rule as the dashboard: "still warming", "failed" and "does not
    exist" are three different answers and must not look alike."""
    entries = {entry["depth_m"]: entry for entry in currents_depth.catalog()}

    assert set(entries) == set(currents_depth.DEPTH_LADDER)
    for entry in entries.values():
        assert entry["available"] or entry["unavailable_reason"]


def test_every_offered_level_shares_one_legend_scale():
    """The point of a depth selector is comparing levels. A legend that rescaled
    per level would make that comparison meaningless."""
    maxima = {entry["speed_max_legend"] for entry in currents_depth.catalog()}

    assert maxima == {currents_depth.SPEED_MAX_LEGEND}
