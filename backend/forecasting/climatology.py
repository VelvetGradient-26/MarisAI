"""A day-of-year climatology baseline, fitted per location.

Why this exists
---------------
The engine has always scored against **persistence** (the last observed
value), and that is the right baseline at short horizons on an autocorrelated
ocean series. It is the *wrong* baseline for the finding that motivated this
module: skill against persistence tends to *rise* with horizon on several
variables here. That is exactly the signature you would get from a model
learning nothing but the seasonal cycle, because persistence decays with
horizon while a seasonal cycle does not. Without a climatology baseline the
two explanations are indistinguishable, and the more interesting one is
unsupported.

A model that beats persistence at h=30 but loses to climatology has not
learned to forecast; it has learned what month it is.

Fit and apply are two functions
-------------------------------
Deliberately, and for the same reason `machine_learning/` splits every such
pair: a climatology fitted over the full record leaks the evaluation period
into the *baseline's* definition, which flatters the baseline and understates
the model. Fitting on the wrong rows has to take deliberate effort. Every
caller here fits on a CV fold's training rows only.

Why a window and not a bare day-of-year mean
--------------------------------------------
These series are ~2.2 years long, so a bare (location, day-of-year) mean is an
average of two samples and is mostly noise — it would be a strawman baseline
that the model beats for the wrong reason. A +/-15 day circular window pools
roughly 60 samples per estimate, which is the standard construction and is
what makes this a baseline worth losing to. The window is the one knob and it
is reported in the paper.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DAYS_IN_YEAR = 366
DEFAULT_WINDOW_DAYS = 15
EARTH_RADIUS_KM = 6371.0


@dataclass
class Climatology:
    """A fitted per-location seasonal cycle.

    `curves` maps a location key to a length-366 array indexed by day-of-year
    minus one. `centroids` records where each location is, so an *unseen*
    location can fall back to the nearest fitted one — which is what the
    leave-one-site-out experiment needs, and is the honest spatial analogue of
    what the global model does when it scores a coordinate it never saw.
    """

    curves: dict[object, np.ndarray] = field(default_factory=dict)
    centroids: dict[object, tuple[float, float]] = field(default_factory=dict)
    global_curve: np.ndarray | None = None
    circular: bool = False
    window_days: int = DEFAULT_WINDOW_DAYS

    @property
    def locations(self) -> int:
        return len(self.curves)


def _day_of_year(timestamps: pd.Series) -> np.ndarray:
    return pd.to_datetime(timestamps).dt.dayofyear.to_numpy(dtype="int64")


def _circular_window_mask(window_days: int) -> np.ndarray:
    """A (366, 366) boolean mask: which days fall within the window of each day.

    Built once and reused for every location. Circular, so 31 December is a
    neighbour of 1 January — a window that clipped at the year boundary would
    give every December and January estimate a truncated, biased sample.
    """
    days = np.arange(DAYS_IN_YEAR)
    separation = np.abs(days[:, None] - days[None, :])
    wrapped = np.minimum(separation, DAYS_IN_YEAR - separation)
    return wrapped <= window_days


def _mean(values: np.ndarray, circular: bool) -> float:
    """Arithmetic mean, or the circular mean for a bearing in degrees."""
    if not circular:
        return float(np.mean(values))
    radians = np.deg2rad(values)
    angle = np.arctan2(np.mean(np.sin(radians)), np.mean(np.cos(radians)))
    return float(np.rad2deg(angle) % 360.0)


def _curve_for(
    doy: np.ndarray, values: np.ndarray, mask: np.ndarray, circular: bool
) -> np.ndarray:
    """One location's 366-day cycle, NaN on days the window could not fill."""
    curve = np.full(DAYS_IN_YEAR, np.nan, dtype="float64")
    # doy is 1-based; index the mask 0-based.
    observed = doy - 1
    for day in range(DAYS_IN_YEAR):
        selected = values[mask[day][observed]]
        if selected.size:
            curve[day] = _mean(selected, circular)
    return curve


def fit_climatology(
    timestamps: pd.Series,
    values: pd.Series | np.ndarray,
    groups: pd.Series,
    *,
    latitudes: pd.Series | None = None,
    longitudes: pd.Series | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    circular: bool = False,
) -> Climatology:
    """Fit a per-location day-of-year climatology on **training rows only**.

    `groups` identifies the location each row belongs to. `latitudes` and
    `longitudes` are optional and only needed if the climatology will later be
    applied to a location it was not fitted on.
    """
    values = np.asarray(values, dtype="float64")
    doy = _day_of_year(timestamps)
    group_values = np.asarray(groups)

    finite = np.isfinite(values)
    if finite.sum() == 0:
        raise ValueError("no finite values to fit a climatology on")

    mask = _circular_window_mask(window_days)

    curves: dict[object, np.ndarray] = {}
    centroids: dict[object, tuple[float, float]] = {}
    for key in pd.unique(group_values[finite]):
        selected = finite & (group_values == key)
        if selected.sum() == 0:
            continue
        curves[key] = _curve_for(doy[selected], values[selected], mask, circular)
        if latitudes is not None and longitudes is not None:
            centroids[key] = (
                float(np.asarray(latitudes)[selected][0]),
                float(np.asarray(longitudes)[selected][0]),
            )

    return Climatology(
        curves=curves,
        centroids=centroids,
        global_curve=_curve_for(doy[finite], values[finite], mask, circular),
        circular=circular,
        window_days=window_days,
    )


def _nearest_fitted(
    climatology: Climatology, latitude: float, longitude: float
) -> object | None:
    """The fitted location closest on the sphere, or None if none are located.

    Great-circle rather than planar: the training points span every basin, and
    a degree of longitude at 60S is half a degree at the equator.
    """
    if not climatology.centroids:
        return None
    lat1 = np.deg2rad(latitude)
    lon1 = np.deg2rad(longitude)
    best_key, best_distance = None, np.inf
    for key, (lat2, lon2) in climatology.centroids.items():
        lat2r, lon2r = np.deg2rad(lat2), np.deg2rad(lon2)
        haversine = (
            np.sin((lat2r - lat1) / 2) ** 2
            + np.cos(lat1) * np.cos(lat2r) * np.sin((lon2r - lon1) / 2) ** 2
        )
        distance = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(haversine, 0, 1)))
        if distance < best_distance:
            best_key, best_distance = key, distance
    return best_key


def apply_climatology(
    climatology: Climatology,
    timestamps: pd.Series,
    groups: pd.Series,
    *,
    latitudes: pd.Series | None = None,
    longitudes: pd.Series | None = None,
) -> np.ndarray:
    """Predict from a fitted climatology. Never refits — that is the point.

    Resolution order per row: the row's own location, then the nearest fitted
    location (unseen sites, i.e. leave-one-site-out), then the pooled global
    curve. A NaN day in a chosen curve falls through the same order, so a
    location with a coverage gap still gets an answer rather than a hole that
    would quietly shrink the scored sample.
    """
    doy = _day_of_year(timestamps) - 1
    group_values = np.asarray(groups)
    out = np.full(len(doy), np.nan, dtype="float64")

    resolved: dict[object, np.ndarray | None] = {}
    for key in pd.unique(group_values):
        curve = climatology.curves.get(key)
        if curve is None and latitudes is not None and longitudes is not None:
            index = int(np.argmax(group_values == key))
            fallback = _nearest_fitted(
                climatology,
                float(np.asarray(latitudes)[index]),
                float(np.asarray(longitudes)[index]),
            )
            curve = climatology.curves.get(fallback) if fallback is not None else None
        resolved[key] = curve

    for key, curve in resolved.items():
        selected = group_values == key
        if curve is not None:
            out[selected] = curve[doy[selected]]

    if climatology.global_curve is not None:
        missing = ~np.isfinite(out)
        if missing.any():
            out[missing] = climatology.global_curve[doy[missing]]

    return out
