"""Ocean heat content, one series per layer.

0-700 m was the only layer offered, and it is the wrong one for most marine
questions: cyclone intensification and marine heatwaves live in the top ~100 m,
which 600 m of near-constant deep water underneath averages away. The tests here
pin that the shallow layers actually resolve that signal and that adding them
did not rename the layer everything already refers to.
"""

from __future__ import annotations

import numpy as np
import pytest

from services.dashboard import copernicus_series, trends


def test_the_reference_layer_keeps_its_bare_key():
    """Renaming `ocean_heat_content` to `..._700m` would break every stored
    chart selection for no gain, so the reference depth keeps the bare key and
    only the new layers are suffixed."""
    assert copernicus_series.ohc_key(700.0) == "ocean_heat_content"
    assert copernicus_series.ohc_key(50.0) == "ocean_heat_content_50m"
    assert "ocean_heat_content" in copernicus_series.SERIES
    assert "ocean_heat_content" in trends.TRENDS


def test_every_layer_is_chartable():
    for depth in copernicus_series.OHC_LAYERS_M:
        key = copernicus_series.ohc_key(depth)
        assert copernicus_series.SERIES[key].maximum_depth == depth
        assert copernicus_series.SERIES[key].mode == "ohc"
        spec = trends.TRENDS[key]
        assert spec.api == "copernicus"
        assert spec.unit == "GJ/m²"


def test_the_catalog_offers_the_shallow_layers_daily_only():
    """These are daily products, so the hourly ranges would plot one or two
    points and call it a chart."""
    entries = {entry["key"]: entry for entry in trends.catalog()}
    supported = entries["ocean_heat_content_50m"]["supported_ranges"]
    assert "24h" not in supported
    assert "1y" in supported


def test_the_integral_closes_the_column_at_the_surface():
    """The shallowest model level is ~0.494 m, so integrating the levels as they
    come leaves the top half-metre out — negligible against 700 m, about 1% of a
    50 m layer, which is the scale of signal those layers exist to show."""
    depths = np.array([0.494, 10.0, 20.0])
    profile = np.array([20.0, 20.0, 20.0])

    value = copernicus_series._integrate_heat_content(profile, depths)

    # An isothermal 20 °C column integrates to rho*cp*T*H over the full 0-20 m,
    # not over 0.494-20 m.
    expected = 1025.0 * 3985.0 * 20.0 * 20.0 / 1e9
    assert value == pytest.approx(expected, rel=1e-9)


def test_a_shallow_layer_resolves_warming_the_reference_depth_averages_away():
    """The whole argument for the shallow layers, as arithmetic.

    A 2 °C warming confined to the top 50 m moves the 0-50 m series by its full
    amount and the 0-700 m series by a fourteenth of it.
    """
    depths = np.concatenate([np.linspace(0.5, 50.0, 20), np.linspace(60.0, 700.0, 40)])
    baseline = np.where(depths <= 50.0, 25.0, 8.0)
    warmed = np.where(depths <= 50.0, 27.0, 8.0)

    shallow = depths <= 50.0
    shallow_change = copernicus_series._integrate_heat_content(
        warmed[shallow], depths[shallow]
    ) - copernicus_series._integrate_heat_content(baseline[shallow], depths[shallow])
    deep_change = copernicus_series._integrate_heat_content(
        warmed, depths
    ) - copernicus_series._integrate_heat_content(baseline, depths)

    # Nearly the same absolute change in joules — the heat went into the same
    # water. Not exactly, because the trapezoid segment spanning the 50 m step
    # picks up a little of it; that is a property of the synthetic step profile,
    # not of the integral.
    assert shallow_change == pytest.approx(deep_change, rel=0.15)

    # But as a *fraction* of the series it is plotted against, the shallow layer
    # shows it and the reference layer does not.
    shallow_base = copernicus_series._integrate_heat_content(baseline[shallow], depths[shallow])
    deep_base = copernicus_series._integrate_heat_content(baseline, depths)
    assert shallow_change / shallow_base > 0.07
    assert deep_change / deep_base < 0.02


def test_a_column_too_thin_to_integrate_returns_none_rather_than_zero():
    """Below the seafloor the model is NaN. One valid level is not a column, and
    reporting 0 GJ/m² for it would be a false reading, not a neutral one."""
    assert copernicus_series._integrate_heat_content(
        np.array([20.0, np.nan, np.nan]), np.array([0.5, 10.0, 20.0])
    ) is None
