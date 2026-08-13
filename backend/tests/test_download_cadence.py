"""Mixing providers of different cadence must aggregate, never sample.

Every provider here is fetched at its own native cadence — Copernicus physics
is hourly, waves 3-hourly, biogeochemistry and the depth-resolved products
daily — and a single request routinely spans several of them. `sea_surface_
temperature`'s configured covariates alone reach into an hourly product and a
daily one.

The failure this file pins is silent by construction. `xr.merge(join="inner")`
on the time axis keeps the *coarse* provider's timestamps, so an hourly field
joined against a daily one survives as its 00:00 sample: a plausible number,
in the right units, in every row, that is an instantaneous reading standing in
for a 24-hour mean. Nothing raises, nothing is NaN, and the error is
systematic rather than noisy — on a diurnally-varying field, 00:00 is not the
mean, and every row is wrong in the same direction.

The second half is ordering. `current_speed` is `hypot(uo, vo)`, so the mean
of hourly speeds and the speed of mean hourly components are different
quantities; a day of currents rotating through a full circle averages to
roughly zero components while never actually going slack. Derivations must run
on native samples, before any aggregation.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from services.download import catalog
from services.download.cleaning import build_dataframe
from services.download.models import Resolution
from services.download.registry import resolve_variables

HOURLY_PROVIDER = catalog.PROVIDER_COPERNICUS_PHYSICS
DAILY_PROVIDER = catalog.PROVIDER_COPERNICUS_THETAO_DEPTH


def _series(fields: dict[str, np.ndarray], times: pd.DatetimeIndex) -> xr.Dataset:
    """A single-point series in the shape `build_dataframe` receives."""
    return xr.Dataset(
        {name: ("time", values) for name, values in fields.items()},
        coords={"time": times, "latitude": 15.0, "longitude": 65.0},
    )


def test_an_hourly_field_joined_against_a_daily_one_is_a_daily_mean() -> None:
    """The regression: this returned each day's 00:00 value, not its mean."""
    days = 4
    hours = pd.date_range("2026-01-01", periods=24 * days, freq="h")
    # A clean diurnal cycle around 20 degC. Its daily mean is exactly 20.0
    # while its 00:00 sample is exactly 20.0 + amplitude, so the two readings
    # of "the day's temperature" cannot be confused for one another.
    amplitude = 3.0
    curve = 20.0 + amplitude * np.cos(2 * np.pi * np.arange(24 * days) / 24)

    variables = resolve_variables(["sea_surface_temperature", "water_temperature"])
    frame = build_dataframe(
        fetched={
            HOURLY_PROVIDER: (catalog.get(HOURLY_PROVIDER), _series({"thetao": curve}, hours)),
            DAILY_PROVIDER: (
                catalog.get(DAILY_PROVIDER),
                _series(
                    {"thetao": np.full(days, 4.2)},
                    pd.date_range("2026-01-01", periods=days, freq="D"),
                ),
            ),
        },
        variables=variables,
        resolution=Resolution.daily,
        start_date=date(2026, 1, 1),
    )

    assert len(frame) == days
    assert frame["sea_surface_temperature"].tolist() == pytest.approx([20.0] * days, abs=1e-9)
    # The coarse provider is untouched, and it is what set the output cadence.
    assert frame["water_temperature"].unique().tolist() == [4.2]


def test_a_derivation_runs_before_aggregation() -> None:
    """Speed is the mean of hourly speeds, not the speed of mean components.

    A guard rather than a regression: the ordering was already correct before
    aggregation moved ahead of the merge, and this is what stops that move
    from quietly taking derivations with it. The current here holds a constant
    1 m/s while rotating once through the day, so the components average to ~0
    and a deriving-after-aggregating implementation reports a still ocean.
    """
    hours = pd.date_range("2026-01-01", periods=24, freq="h")
    angle = 2 * np.pi * np.arange(24) / 24

    variables = resolve_variables(["current_speed"])
    frame = build_dataframe(
        fetched={
            HOURLY_PROVIDER: (
                catalog.get(HOURLY_PROVIDER),
                _series({"uo": np.cos(angle), "vo": np.sin(angle)}, hours),
            )
        },
        variables=variables,
        resolution=Resolution.daily,
        start_date=date(2026, 1, 1),
    )

    assert frame["current_speed"].tolist() == pytest.approx([1.0], abs=1e-9)


def test_hourly_resolution_still_returns_every_timestep() -> None:
    """Aggregation is opt-in via the requested resolution, not implicit."""
    hours = pd.date_range("2026-01-01", periods=48, freq="h")
    variables = resolve_variables(["sea_surface_temperature"])

    frame = build_dataframe(
        fetched={
            HOURLY_PROVIDER: (
                catalog.get(HOURLY_PROVIDER),
                _series({"thetao": np.arange(48, dtype="float64")}, hours),
            )
        },
        variables=variables,
        resolution=Resolution.hourly,
        start_date=date(2026, 1, 1),
    )

    assert len(frame) == 48
    assert frame["sea_surface_temperature"].tolist() == pytest.approx(np.arange(48).tolist())


def test_a_gap_in_the_fine_provider_averages_what_is_there() -> None:
    """Partial coverage is a mean over the samples present, not a NaN day.

    Copernicus near-real-time products do carry gaps, and a day that lost six
    hours to one is still a usable day — but a day that lost all of them must
    not be reported as a number.
    """
    hours = pd.date_range("2026-01-01", periods=48, freq="h")
    values = np.concatenate([np.full(24, 10.0), np.full(24, np.nan)])
    values[:6] = np.nan  # first day partially missing

    variables = resolve_variables(["sea_surface_temperature"])
    frame = build_dataframe(
        fetched={
            HOURLY_PROVIDER: (catalog.get(HOURLY_PROVIDER), _series({"thetao": values}, hours))
        },
        variables=variables,
        resolution=Resolution.daily,
        start_date=date(2026, 1, 1),
    )

    # Day one keeps its 18 good hours; day two is all-NaN and is dropped
    # rather than filled.
    assert frame["sea_surface_temperature"].tolist() == pytest.approx([10.0])
