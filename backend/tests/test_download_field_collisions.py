"""Two providers may use the same upstream field name for different quantities.

Copernicus does, twice: `thetao` is surface temperature in the physics product
and a depth-resolved profile in `..._thetao_depth`, and `so` is surface
salinity in the physics product and a profile in `..._so_depth`. Merging those
datasets raw raised

    MergeError: conflicting values for variable 'thetao'

which took out *every* request pairing `water_temperature` with
`sea_surface_temperature` — a legal selection in the downloader UI and the
configured covariate set for `water_temperature` in the forecasting engine.

These tests pin both halves: that the registry's collisions are known, and
that a merge across them produces two distinct, correctly-sourced columns
rather than raising or silently taking one provider's values for both.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from services.download import catalog
from services.download.cleaning import build_dataframe, qualify
from services.download.models import Resolution
from services.download.registry import VARIABLE_REGISTRY, resolve_variables

# The surface value and the at-depth value, deliberately far apart so a merge
# that collapsed them onto one another could not pass by coincidence.
SURFACE_TEMPERATURE = 28.5
DEPTH_TEMPERATURE = 4.2
SURFACE_SALINITY = 35.1
DEPTH_SALINITY = 34.6


def _point_dataset(field: str, value: float, times: pd.DatetimeIndex) -> xr.Dataset:
    """A single-point series in the shape `build_dataframe` receives."""
    return xr.Dataset(
        {field: ("time", np.full(len(times), value, dtype="float64"))},
        coords={"time": times, "latitude": 15.0, "longitude": 65.0},
    )


def _fetched(pairs: list[tuple[str, str, float]], times: pd.DatetimeIndex) -> dict:
    return {
        provider: (catalog.get(provider), _point_dataset(field, value, times))
        for provider, field, value in pairs
    }


def test_the_registry_still_has_exactly_the_known_collisions() -> None:
    """A new collision must fail here rather than at a user's request.

    Namespacing means a third provider reusing `thetao` is handled, but a
    *new* collision is still worth surfacing: it usually means two variables
    are closer to duplicates than intended.
    """
    by_field: dict[str, set[str]] = defaultdict(set)
    for info in VARIABLE_REGISTRY.values():
        if info.source_field is not None and info.provider is not None:
            by_field[info.source_field].add(info.provider)

    collisions = {field: sorted(p) for field, p in by_field.items() if len(p) > 1}
    assert collisions == {
        "so": ["copernicus_physics", "copernicus_so_depth"],
        "thetao": ["copernicus_physics", "copernicus_thetao_depth"],
    }


@pytest.mark.parametrize(
    ("surface_code", "depth_code", "field", "surface_value", "depth_value"),
    [
        (
            "sea_surface_temperature",
            "water_temperature",
            "thetao",
            SURFACE_TEMPERATURE,
            DEPTH_TEMPERATURE,
        ),
        (
            "sea_surface_salinity",
            "water_salinity",
            "so",
            SURFACE_SALINITY,
            DEPTH_SALINITY,
        ),
    ],
)
def test_a_surface_and_depth_pair_merges_into_two_distinct_columns(
    surface_code: str,
    depth_code: str,
    field: str,
    surface_value: float,
    depth_value: float,
) -> None:
    """The regression: this raised MergeError before providers were namespaced."""
    times = pd.date_range("2026-01-01", periods=5, freq="D")
    variables = resolve_variables([surface_code, depth_code])
    surface_provider = variables[surface_code].provider
    depth_provider = variables[depth_code].provider
    assert surface_provider != depth_provider

    frame = build_dataframe(
        fetched=_fetched(
            [
                (surface_provider, field, surface_value),
                (depth_provider, field, depth_value),
            ],
            times,
        ),
        variables=variables,
        resolution=Resolution.daily,
        start_date=date(2026, 1, 1),
    )

    assert {surface_code, depth_code} <= set(frame.columns)
    # Each column carries its own provider's value: the whole point is that
    # one did not overwrite the other.
    assert frame[surface_code].unique().tolist() == [surface_value]
    assert frame[depth_code].unique().tolist() == [depth_value]


def test_qualified_names_are_distinct_per_provider() -> None:
    assert qualify("copernicus_physics", "thetao") != qualify(
        "copernicus_thetao_depth", "thetao"
    )


def test_a_derived_variable_reads_its_own_providers_fields() -> None:
    """Derivations name raw fields too, so they need qualifying identically.

    `current_speed` is hypot(uo, vo) from the physics product. If the
    derivation looked up bare `uo`/`vo` it would raise KeyError against the
    namespaced merge — this is what catches that half of the change.
    """
    times = pd.date_range("2026-01-01", periods=4, freq="D")
    variables = resolve_variables(["current_speed"])
    provider = variables["current_speed"].provider

    dataset = xr.Dataset(
        {
            "uo": ("time", np.full(len(times), 3.0)),
            "vo": ("time", np.full(len(times), 4.0)),
        },
        coords={"time": times, "latitude": 15.0, "longitude": 65.0},
    )

    frame = build_dataframe(
        fetched={provider: (catalog.get(provider), dataset)},
        variables=variables,
        resolution=Resolution.daily,
        start_date=date(2026, 1, 1),
    )

    # hypot(3, 4) == 5, so a wrong-field lookup cannot pass silently.
    assert frame["current_speed"].unique().tolist() == [5.0]
