"""Tests for the climatology baseline.

Every way this breaks is silent. A leaking climatology still returns numbers,
still looks seasonal, and simply reports a baseline that is better than it
should be — which would make the model look worse and the paper's central
comparison wrong in the safe-sounding direction. A circular mean applied with
an arithmetic formula still returns a bearing. So the properties are asserted
rather than eyeballed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forecasting.climatology import (
    DAYS_IN_YEAR,
    apply_climatology,
    fit_climatology,
)


def _series(days: int = 730, sites: int = 3, amplitude: float = 5.0, offset: float = 20.0):
    """Three sites on a pure annual cycle, each shifted by a known constant."""
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    rows = []
    for index in range(sites):
        doy = dates.dayofyear.to_numpy()
        values = offset + 10 * index + amplitude * np.sin(2 * np.pi * doy / 365.25)
        rows.append(
            pd.DataFrame(
                {
                    "timestamp": dates,
                    "value": values,
                    "site": f"site_{index}",
                    "latitude": 10.0 * index,
                    "longitude": 20.0 * index,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def test_recovers_a_known_seasonal_cycle_per_site():
    frame = _series()
    fitted = fit_climatology(
        frame["timestamp"], frame["value"], frame["site"],
        latitudes=frame["latitude"], longitudes=frame["longitude"],
    )
    predicted = apply_climatology(fitted, frame["timestamp"], frame["site"])

    # A +/-15 day window smooths a sinusoid slightly, so this is a tolerance on
    # a known systematic effect, not a fudge factor.
    assert np.nanmax(np.abs(predicted - frame["value"].to_numpy())) < 0.35
    assert fitted.locations == 3


def test_each_site_keeps_its_own_offset():
    """A pooled climatology would give all three sites the middle curve."""
    frame = _series()
    fitted = fit_climatology(
        frame["timestamp"], frame["value"], frame["site"],
        latitudes=frame["latitude"], longitudes=frame["longitude"],
    )
    means = {
        site: float(np.nanmean(curve)) for site, curve in fitted.curves.items()
    }
    assert means["site_1"] - means["site_0"] == pytest.approx(10.0, abs=0.5)
    assert means["site_2"] - means["site_1"] == pytest.approx(10.0, abs=0.5)


def test_fit_does_not_see_the_rows_it_is_applied_to():
    """The leakage guard: a fit on early rows must not encode later ones.

    The second year is shifted by a large constant. A climatology fitted on
    year one only cannot know about it, so its error on year two must be
    approximately that shift. If fit and apply were ever collapsed into one
    pass over all rows, this error would collapse toward zero.
    """
    frame = _series(days=730, sites=1)
    late = frame["timestamp"] >= "2025-01-01"
    frame.loc[late, "value"] = frame.loc[late, "value"] + 30.0

    train, test = frame[~late], frame[late]
    fitted = fit_climatology(
        train["timestamp"], train["value"], train["site"],
        latitudes=train["latitude"], longitudes=train["longitude"],
    )
    predicted = apply_climatology(fitted, test["timestamp"], test["site"])

    error = float(np.nanmean(test["value"].to_numpy() - predicted))
    assert error == pytest.approx(30.0, abs=1.0)


def test_unseen_site_falls_back_to_the_nearest_fitted_one():
    """What leave-one-site-out relies on: a held-out location still scores."""
    frame = _series(sites=3)
    train = frame[frame["site"] != "site_2"]
    test = frame[frame["site"] == "site_2"]

    fitted = fit_climatology(
        train["timestamp"], train["value"], train["site"],
        latitudes=train["latitude"], longitudes=train["longitude"],
    )
    predicted = apply_climatology(
        fitted, test["timestamp"], test["site"],
        latitudes=test["latitude"], longitudes=test["longitude"],
    )

    assert np.isfinite(predicted).all()
    # site_2 is nearest to site_1, which sits 10 units below it by construction.
    assert float(np.nanmean(test["value"].to_numpy() - predicted)) == pytest.approx(
        10.0, abs=1.0
    )


def test_the_window_wraps_across_the_year_boundary():
    """31 December and 1 January are neighbours, not opposite ends."""
    dates = pd.date_range("2024-01-01", periods=730, freq="D")
    frame = pd.DataFrame(
        {
            "timestamp": dates,
            # Constant, so any window that sampled the wrong days still
            # returns the same number -- what is asserted here is coverage:
            # no day of the year may be left unfilled.
            "value": 15.0,
            "site": "only",
        }
    )
    fitted = fit_climatology(frame["timestamp"], frame["value"], frame["site"])
    curve = fitted.curves["only"]
    assert np.isfinite(curve[:DAYS_IN_YEAR - 1]).all()
    assert curve[0] == pytest.approx(15.0)
    assert curve[364] == pytest.approx(15.0)


def test_circular_variables_use_a_circular_mean():
    """359 deg and 1 deg average to 0, not to 180."""
    dates = pd.date_range("2024-01-01", periods=400, freq="D")
    values = np.where(np.arange(400) % 2 == 0, 359.0, 1.0)
    frame = pd.DataFrame({"timestamp": dates, "value": values, "site": "only"})

    circular = fit_climatology(
        frame["timestamp"], frame["value"], frame["site"], circular=True
    )
    linear = fit_climatology(
        frame["timestamp"], frame["value"], frame["site"], circular=False
    )

    predicted = apply_climatology(circular, frame["timestamp"], frame["site"])
    wrapped = (predicted + 180.0) % 360.0 - 180.0
    assert np.nanmax(np.abs(wrapped)) < 5.0

    # The linear fit is the failure being guarded against: it lands near 180,
    # exactly opposite the truth.
    assert float(np.nanmean(linear.curves["only"])) == pytest.approx(180.0, abs=5.0)


def test_one_site_s_gap_is_filled_from_the_others():
    """A day this site never saw, but another did, still gets an answer."""
    frame = _series(days=400, sites=2)
    # Punch a two-month hole in site_0 only.
    hole = (frame["site"] == "site_0") & (
        frame["timestamp"].between("2024-03-01", "2024-04-30")
    )
    frame = frame[~hole]

    fitted = fit_climatology(
        frame["timestamp"], frame["value"], frame["site"],
        latitudes=frame["latitude"], longitudes=frame["longitude"],
    )
    spring = pd.Series(pd.date_range("2024-03-10", periods=20, freq="D"))
    predicted = apply_climatology(fitted, spring, pd.Series(["site_0"] * 20))

    # site_0's own curve is empty there, so these come from the pooled curve.
    assert np.isfinite(predicted).all()


def test_a_day_no_site_ever_observed_returns_nan_rather_than_a_guess():
    """The sample shrinks visibly instead of being filled with invention.

    `compute_metrics` reports `climatology_n` beside the score, so a baseline
    that could only answer for part of the test set is scored on that part and
    says so. Substituting the annual mean here would quietly make the
    climatology look better on exactly the days it knows least about.
    """
    frame = _series(days=200, sites=2)
    fitted = fit_climatology(
        frame["timestamp"], frame["value"], frame["site"],
        latitudes=frame["latitude"], longitudes=frame["longitude"],
    )
    # The 200-day record starts in January, so November is unobserved
    # everywhere.
    winter = pd.Series(pd.date_range("2024-11-01", periods=30, freq="D"))
    predicted = apply_climatology(fitted, winter, pd.Series(["site_0"] * 30))
    assert not np.isfinite(predicted).any()


def test_no_finite_values_is_an_error_not_a_flat_line():
    frame = _series(days=100, sites=1)
    frame["value"] = np.nan
    with pytest.raises(ValueError):
        fit_climatology(frame["timestamp"], frame["value"], frame["site"])
