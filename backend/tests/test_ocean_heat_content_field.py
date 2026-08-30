"""Tests for the ocean heat content *field* (a regional grid build), as
distinct from `tests/test_ocean_heat_content.py`'s point series.

Two halves: `_integrate_layer` (the vectorised vertical integral,
`scripts/build_ocean_heat_content_grid.py`) is checked against known
profiles by hand; `services/ocean_heat_content_field.py`'s read side is
checked against a small synthetic NetCDF file written to a temp path, no
network and no real Copernicus grid involved.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
import xarray as xr

from scripts.build_ocean_heat_content_grid import _integrate_layer
from services import ocean_heat_content_field as ohc_field
from services.dashboard.copernicus_series import OHC_LAYERS_M, ohc_key


@pytest.fixture(autouse=True)
def _reset_cache():
    ohc_field.reload()
    yield
    ohc_field.reload()


class TestIntegrateLayer:
    def test_a_uniform_column_integrates_to_density_times_capacity_times_temperature_times_depth(self):
        """The simplest closed form: a constant-temperature column from 0 to
        `max_depth` integrates to `rho * cp * T * max_depth` exactly."""
        depths = np.array([0.0, 100.0, 200.0])
        temps = np.full((3, 1, 1), 10.0)

        layer = _integrate_layer(temps, depths, 200.0)

        rho, cp = 1025.0, 3985.0
        expected_joules = rho * cp * 10.0 * 200.0
        assert layer[0, 0] == pytest.approx(expected_joules / 1e9, rel=1e-6)

    def test_stops_at_the_seafloor_rather_than_assuming_max_depth(self):
        """One cell's column ends at 100 m (NaN below); the 200 m layer must
        integrate only the real 0-100 m it has, not silently extend to 200."""
        depths = np.array([0.0, 100.0, 200.0])
        temps = np.array([[[10.0]], [[10.0]], [[np.nan]]])

        shallow_only = _integrate_layer(temps, depths, 200.0)
        deep_column = _integrate_layer(np.full((3, 1, 1), 10.0), depths, 200.0)

        assert np.isfinite(shallow_only[0, 0])
        assert shallow_only[0, 0] < deep_column[0, 0]

    def test_land_is_nan_not_zero(self):
        depths = np.array([0.0, 100.0])
        temps = np.full((2, 1, 1), np.nan)

        layer = _integrate_layer(temps, depths, 100.0)

        assert not np.isfinite(layer[0, 0])

    def test_shallower_layers_are_smaller_for_the_same_warm_column(self):
        depths = np.array([0.0, 50.0, 100.0, 200.0])
        temps = np.full((4, 2, 2), 15.0)

        shallow = _integrate_layer(temps, depths, 50.0)
        deep = _integrate_layer(temps, depths, 200.0)

        assert np.all(shallow < deep)


def _write_grid(path, *, lat, lon, values_by_depth, timestamp, built_at):
    data_vars = {
        ohc_key(depth): (("latitude", "longitude"), np.asarray(values, dtype="float32"))
        for depth, values in values_by_depth.items()
    }
    dataset = xr.Dataset(
        data_vars,
        coords={"latitude": np.asarray(lat), "longitude": np.asarray(lon)},
        attrs={"timestamp": timestamp.isoformat(), "built_at": built_at.isoformat()},
    )
    dataset.to_netcdf(path)


class TestField:
    def test_unavailable_before_any_build(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ohc_field, "GRID_PATH", tmp_path / "missing.nc")
        assert ohc_field.is_available() is False
        with pytest.raises(ohc_field.OceanHeatContentFieldError):
            ohc_field.summary()

    def test_at_point_reads_every_layer(self, monkeypatch, tmp_path):
        path = tmp_path / "ohc.nc"
        lat, lon = [10.0, 15.0], [60.0, 70.0]
        _write_grid(
            path,
            lat=lat,
            lon=lon,
            values_by_depth={depth: np.full((2, 2), float(depth)) for depth in OHC_LAYERS_M},
            timestamp=datetime(2026, 8, 20, tzinfo=UTC),
            built_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
        monkeypatch.setattr(ohc_field, "GRID_PATH", path)

        point = ohc_field.at_point(10.0, 60.0)

        assert point["available"] is True
        for depth in OHC_LAYERS_M:
            assert point[ohc_key(depth)] == pytest.approx(depth)

    def test_at_point_outside_the_region_says_so(self, monkeypatch, tmp_path):
        path = tmp_path / "ohc.nc"
        _write_grid(
            path,
            lat=[10.0], lon=[60.0],
            values_by_depth={depth: [[1.0]] for depth in OHC_LAYERS_M},
            timestamp=datetime(2026, 8, 20, tzinfo=UTC),
            built_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
        monkeypatch.setattr(ohc_field, "GRID_PATH", path)

        point = ohc_field.at_point(60.0, 60.0)  # far outside 5S-25N

        assert point["available"] is False
        assert "region" in point["unavailable_reason"]

    def test_cells_only_sends_finite_values(self, monkeypatch, tmp_path):
        path = tmp_path / "ohc.nc"
        lat, lon = [10.0, 11.0], [60.0]
        values = {depth: np.array([[1.0], [np.nan]]) for depth in OHC_LAYERS_M}
        _write_grid(
            path, lat=lat, lon=lon, values_by_depth=values,
            timestamp=datetime(2026, 8, 20, tzinfo=UTC), built_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
        monkeypatch.setattr(ohc_field, "GRID_PATH", path)

        payload = ohc_field.cells(OHC_LAYERS_M[-1])

        assert len(payload["cells"]) == 1
        assert payload["cells"][0]["value"] == 1.0

    def test_reload_picks_up_a_new_build(self, monkeypatch, tmp_path):
        path = tmp_path / "ohc.nc"
        _write_grid(
            path, lat=[10.0], lon=[60.0],
            values_by_depth={depth: [[1.0]] for depth in OHC_LAYERS_M},
            timestamp=datetime(2026, 8, 20, tzinfo=UTC), built_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
        monkeypatch.setattr(ohc_field, "GRID_PATH", path)
        first = ohc_field.at_point(10.0, 60.0)

        _write_grid(
            path, lat=[10.0], lon=[60.0],
            values_by_depth={depth: [[2.0]] for depth in OHC_LAYERS_M},
            timestamp=datetime(2026, 8, 22, tzinfo=UTC), built_at=datetime(2026, 8, 23, tzinfo=UTC),
        )
        ohc_field.reload()
        second = ohc_field.at_point(10.0, 60.0)

        assert first[ohc_key(OHC_LAYERS_M[-1])] == 1.0
        assert second[ohc_key(OHC_LAYERS_M[-1])] == 2.0
