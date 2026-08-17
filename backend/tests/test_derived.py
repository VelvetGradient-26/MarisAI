"""Tests for bearings derived from component forecasts.

Two failure modes here are silent and produce entirely plausible maps: using the
wrong convention (the field is exactly backwards, still in range, still smooth),
and letting the grid path grow its own copy of the formula (the two agree today
and drift apart on the next edit). Both are pinned.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import xarray as xr

from forecasting import derived


class TestConventions:
    @pytest.mark.parametrize(
        ("u", "v", "expected"),
        [(1, 0, 90), (0, 1, 0), (-1, 0, 270), (0, -1, 180), (1, 1, 45)],
    )
    def test_currents_report_where_the_water_goes(self, u, v, expected):
        assert derived.combine(u, v, "direction_to") == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("u", "v", "expected"),
        [(1, 0, 270), (0, 1, 180), (-1, 0, 90), (0, -1, 0), (1, 1, 225)],
    )
    def test_wind_reports_where_it_comes_from(self, u, v, expected):
        assert derived.combine(u, v, "direction_from") == pytest.approx(expected)

    def test_the_two_conventions_are_half_a_turn_apart(self):
        """Reusing one for the other gives a field that is backwards and
        completely plausible — the reason the convention is named, not a flag."""
        for u, v in [(1, 0), (0.3, -1.2), (-2, 5)]:
            to = derived.combine(u, v, "direction_to")
            frm = derived.combine(u, v, "direction_from")
            assert (to + 180.0) % 360.0 == pytest.approx(frm)

    def test_an_unknown_convention_is_refused(self):
        with pytest.raises(ValueError, match="convention"):
            derived.combine(1.0, 0.0, "direction_sideways")


class TestUncertainty:
    def test_a_faster_vector_has_a_tighter_bearing(self):
        """The same absolute component error is a smaller angle when the vector
        is longer. This is the whole reason the interval is propagated rather
        than copied from a component."""
        fast = derived.combine_uncertainty(10.0, 0.0, 1.0, 1.0)
        slow = derived.combine_uncertainty(1.0, 0.0, 1.0, 1.0)
        assert fast < slow

    def test_matches_the_closed_form(self):
        u, v, su, sv = 3.0, 4.0, 0.5, 0.25
        expected = math.degrees(
            math.sqrt(v * v * su**2 + u * u * sv**2) / (u * u + v * v)
        )
        assert derived.combine_uncertainty(u, v, su, sv) == pytest.approx(expected)

    def test_a_vanishing_vector_gives_the_whole_circle(self):
        """Slack water has no heading. Clamping this to something narrow would
        be the most confident wrong number the engine could produce."""
        assert derived.combine_uncertainty(0.0, 0.0, 0.5, 0.5) == 180.0
        assert derived.combine_uncertainty(1e-9, 1e-9, 0.5, 0.5) == 180.0

    def test_is_never_wider_than_the_circle(self):
        assert derived.combine_uncertainty(0.01, 0.0, 5.0, 5.0) <= 180.0


class TestGrid:
    @staticmethod
    def _component(values: np.ndarray, variable: str) -> xr.Dataset:
        return xr.Dataset(
            {
                "forecast": (("horizon", "latitude", "longitude"), values),
                "anchor": (("horizon", "latitude", "longitude"), values),
            },
            coords={
                "horizon": [1],
                "latitude": [0.0, 1.0],
                "longitude": [0.0, 1.0],
            },
            attrs={"variable": variable, "label": "x", "unit": "m/s", "model": "LightGBM"},
        )

    def test_the_grid_agrees_with_the_point_path_exactly(self):
        """The property `test_grid_matches_the_point_path` protects for scored
        variables, asserted here for derived ones — and it is exact rather than
        approximate, because both paths call the same function."""
        u = np.array([[[1.0, 0.0], [-1.0, 0.4]]])
        v = np.array([[[0.0, 1.0], [0.0, -1.7]]])
        grid = derived.derive_grid(
            self._component(u, "current_u"), self._component(v, "current_v"),
            "current_direction",
        )
        for row in range(2):
            for column in range(2):
                point = derived.combine(
                    u[0, row, column], v[0, row, column], "direction_to"
                )
                assert grid["forecast"].values[0, row, column] == pytest.approx(point)

    def test_display_bounds_are_geometric_not_percentiles(self):
        """Percentiles round a circle are what produced the shipped
        `display_max: 400` this codebase already had to correct once."""
        u = np.array([[[1.0, 0.5], [0.2, 0.4]]])
        v = np.array([[[0.1, 0.6], [0.3, 0.2]]])
        grid = derived.derive_grid(
            self._component(u, "current_u"), self._component(v, "current_v"),
            "current_direction",
        )
        assert grid.attrs["display_min"] == 0.0
        assert grid.attrs["display_max"] == 360.0

    def test_nan_propagates_from_either_component(self):
        """Land in one component is land in the bearing. A cell with only one
        component would otherwise get a confident direction from half a vector."""
        u = np.array([[[1.0, np.nan], [1.0, 1.0]]])
        v = np.array([[[0.0, 0.0], [np.nan, 1.0]]])
        grid = derived.derive_grid(
            self._component(u, "current_u"), self._component(v, "current_v"),
            "current_direction",
        )
        out = grid["forecast"].values[0]
        assert np.isnan(out[0, 1]) and np.isnan(out[1, 0])
        assert np.isfinite(out[0, 0]) and np.isfinite(out[1, 1])

    def test_mismatched_grids_are_refused(self):
        u = self._component(np.zeros((1, 2, 2)), "current_u")
        v = xr.Dataset(
            {
                "forecast": (("horizon", "latitude", "longitude"), np.zeros((1, 3, 2))),
                "anchor": (("horizon", "latitude", "longitude"), np.zeros((1, 3, 2))),
            },
            coords={"horizon": [1], "latitude": [0.0, 1.0, 2.0], "longitude": [0.0, 1.0]},
        )
        with pytest.raises(ValueError, match="differ in shape"):
            derived.derive_grid(u, v, "current_direction")

    def test_it_records_what_it_was_derived_from(self):
        """A grid that cannot say where it came from is one nobody can audit."""
        u = self._component(np.ones((1, 2, 2)), "current_u")
        v = self._component(np.ones((1, 2, 2)), "current_v")
        grid = derived.derive_grid(u, v, "current_direction")
        assert grid.attrs["derived_from"] == "current_u,current_v"
        assert grid.attrs["direction_convention"] == "direction_to"


class TestRegistry:
    def test_wave_direction_is_not_derived(self):
        """No wave components exist in the download registry, so it stays
        trained — and that asymmetry has to be visible rather than assumed."""
        assert not derived.is_derived("wave_direction")
        assert derived.is_derived("current_direction")
        assert derived.is_derived("wind_direction")

    def test_every_derived_variable_names_real_components(self):
        from services.download.registry import VARIABLE_REGISTRY

        for name, spec in derived.DERIVED.items():
            assert name in VARIABLE_REGISTRY
            for component in spec.components:
                assert component in VARIABLE_REGISTRY, f"{name} -> {component}"
