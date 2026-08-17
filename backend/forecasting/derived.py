"""Bearings derived from forecast components, rather than forecast directly.

The problem
-----------
`current_direction` and `wind_direction` are degrees on 0-360, where 359 and 1
are two degrees apart. Everything *downstream* of the trained model has handled
that since 2026-08-13 — sin/cos resampling recombined with `atan2`, a signed
veer wrapped to [-180, 180) for the map's `change` mode, a cyclic colour ramp on
the true 0-360 domain.

**The model itself was still linear**, and that is the half this module closes.
With `target_mode: delta` the target is the *change* in degrees, so a 5 degree
veer across north trains as **-355**. Every such crossing teaches the model an
enormous excursion that never happened, and the damage is invisible: the model
still fits, still scores, still produces bearings in range.

The fix
-------
Forecast the **components** and derive the angle, which is what
`current_u`/`current_v` and `wind_u`/`wind_v` already do — and precisely why the
currents *particle* layer was never affected while the raster direction layer
was. A direction is then a view over two linear forecasts rather than a model of
its own.

The conventions are imported, not restated
------------------------------------------
`services/download/cleaning.py` already defines how each bearing is built from
its components, and the two conventions are **180 degrees apart**:

* `current_direction` is `direction_to` — where the water flows *toward*.
* `wind_direction` is `direction_from` — where the wind blows *from*.

Deriving a forecast with the wrong one produces a field that is entirely
plausible and exactly backwards, so this module calls the same functions the
downloader uses on observations. A second copy of that formula is the single
most dangerous duplication available here.

`wave_direction` stays trained, and that asymmetry is deliberate
-----------------------------------------------------------------
There are no wave components in `services/download/registry.py` — the provider
serves a bearing and nothing to decompose it into. So one direction variable is
derived and another is not. That is stated in the catalog rather than hidden,
because a user comparing two direction forecasts is entitled to know that one of
them still carries the linear-target flaw described above.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from services.download.cleaning import _derive_direction_from, _derive_direction_to


@dataclass(frozen=True)
class DerivedSpec:
    """How one bearing is assembled from two component forecasts."""

    east: str
    north: str
    # "direction_to" (currents) or "direction_from" (wind). Named rather than
    # boolean so the wrong one cannot be selected by a stray `not`.
    convention: str

    @property
    def components(self) -> tuple[str, str]:
        return (self.east, self.north)


DERIVED: dict[str, DerivedSpec] = {
    "current_direction": DerivedSpec(
        east="current_u", north="current_v", convention="direction_to"
    ),
    "wind_direction": DerivedSpec(
        east="wind_u", north="wind_v", convention="direction_from"
    ),
}


def is_derived(variable: str) -> bool:
    return variable in DERIVED


def spec_for(variable: str) -> DerivedSpec | None:
    return DERIVED.get(variable)


def combine_array(east: np.ndarray, north: np.ndarray, convention: str) -> np.ndarray:
    """Bearings from component arrays of any shape.

    **The single place either path computes an angle.** Both the point forecast
    and the grid go through here, and here goes through `cleaning.py`'s own
    derivations rather than reimplementing `atan2` — so an observed
    `current_direction`, a point forecast and a grid cell cannot end up in three
    different conventions. Those functions take an `xarray.Dataset`, hence the
    wrapper; a second copy of the formula would be far worse than a wrapper, and
    a first draft of the grid path proved it by growing one.
    """
    import xarray as xr

    east = np.asarray(east, dtype="float64")
    dims = tuple(f"d{i}" for i in range(east.ndim))
    dataset = xr.Dataset(
        {"u": (dims, east), "v": (dims, np.asarray(north, dtype="float64"))}
    )
    if convention == "direction_to":
        return np.asarray(_derive_direction_to(dataset, "u", "v").values)
    if convention == "direction_from":
        return np.asarray(_derive_direction_from(dataset, "u", "v").values)
    raise ValueError(f"unknown direction convention {convention!r}")


def combine(east: float, north: float, convention: str) -> float:
    """One bearing from one pair of components."""
    return float(combine_array(np.asarray([east]), np.asarray([north]), convention)[0])


def combine_uncertainty(
    east: float, north: float, east_sigma: float, north_sigma: float
) -> float:
    """First-order angular uncertainty, in degrees, for a bearing from components.

    Standard propagation through `atan2`:

        sigma_theta = sqrt(v^2 sigma_u^2 + u^2 sigma_v^2) / (u^2 + v^2)

    in radians. The convention does not enter — `direction_to` and
    `direction_from` differ by a rotation and a reflection, neither of which
    changes the *width* of the interval.

    **The linearisation fails at low speed, and that is a property of the
    quantity rather than a defect here.** As `u^2 + v^2` goes to zero the
    denominator does too and the uncertainty diverges, because the direction of
    a vanishing vector is genuinely undefined — slack water has no heading. The
    caller is expected to surface that as a full-circle interval rather than
    clamping it to something narrow and confident.
    """
    speed_squared = east * east + north * north
    if speed_squared <= 0.0:
        return 180.0
    radians = float(
        np.sqrt(north * north * east_sigma**2 + east * east * north_sigma**2)
        / speed_squared
    )
    return min(float(np.degrees(radians)), 180.0)


def derive_grid(east_grid, north_grid, variable: str):
    """A bearing grid from two component grids, cell by cell.

    No fetch and no inference: the components' grids already hold the forecast
    and the anchor, and a direction is a pointwise function of them. That is the
    whole economy of the derived approach — `current_direction`'s grid costs
    seconds instead of the ~25 minutes a scored grid takes.

    The output keeps the component grids' shape (`forecast` and `anchor` over
    horizon/lat/lon) so `services/forecast_tiles.py` reads it unchanged, and its
    display bounds are the **geometric** 0-360 rather than percentiles of the
    data. Running percentiles round a circle is what produced the shipped
    `display_max: 400` this codebase already had to correct once.
    """
    import xarray as xr

    spec = DERIVED[variable]
    if east_grid.sizes != north_grid.sizes:
        raise ValueError(
            f"{spec.east} and {spec.north} grids differ in shape "
            f"({dict(east_grid.sizes)} vs {dict(north_grid.sizes)}); rebuild "
            "both before deriving"
        )

    derived_grid = xr.Dataset(
        {
            "forecast": (
                east_grid["forecast"].dims,
                combine_array(
                    east_grid["forecast"].values,
                    north_grid["forecast"].values,
                    spec.convention,
                ).astype("float32"),
            ),
            "anchor": (
                east_grid["anchor"].dims,
                combine_array(
                    east_grid["anchor"].values,
                    north_grid["anchor"].values,
                    spec.convention,
                ).astype("float32"),
            ),
        },
        coords=east_grid.coords,
    )
    derived_grid.attrs.update(
        {
            **{k: v for k, v in east_grid.attrs.items() if k not in {"variable", "label", "unit"}},
            "variable": variable,
            "derived_from": f"{spec.east},{spec.north}",
            "direction_convention": spec.convention,
            # Geometric, not percentile — see the docstring.
            "display_min": 0.0,
            "display_max": 360.0,
            "change_scale": 180.0,
            "model": "derived from component forecasts",
        }
    )
    return derived_grid
