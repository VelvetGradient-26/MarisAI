"""Feature construction. One builder, every variable.

**The invariant this module exists to hold: nothing here looks forward in time
except `add_forecast_target`.** Every lag shifts backwards, every rolling
window is trailing and closed before the current step, every trend is fitted
on data already observed. There is exactly one forward shift in this package
and it constructs the label, never a feature — the same discipline
`machine_learning/` keeps, and `tests/test_forecasting.py` enforces it by
scanning this file for `shift(-` outside that function.

It matters more than it looks. Leakage-free validation is worthless if the
features themselves leak: a rolling mean centred on t, or a "current" covariate
read at the target timestamp rather than the feature timestamp, produces a
model with a beautiful backtest and no forecasting ability at all.

The builder is variable-agnostic. It is told which column is the target, which
are covariates, and which are static, and it emits the same feature families
for all of them. Nothing branches on a variable's name.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from forecasting import ForecastingError
from forecasting.config import FeatureConfig, VariableConfig
from forecasting.preprocessing import TIMESTAMP

TARGET = "__target__"
# The value at feature time that a delta target is measured from, and that
# inference adds the model's output back onto. Carried as a column rather than
# recomputed, so training and serving cannot disagree about what the anchor was.
TARGET_ANCHOR = "__anchor__"

# Columns that are inputs to the model but not derived from a series.
STATIC_COLUMNS = ("latitude", "longitude", "ocean_depth")


class FeatureError(ForecastingError):
    """The frame could not produce a usable feature matrix."""


# --------------------------------------------------------------------------
# Neighbour features — interface only
# --------------------------------------------------------------------------


@runtime_checkable
class NeighbourFeatureProvider(Protocol):
    """Spatial context around a point: the surrounding cells' mean, the local
    variance, an upstream/gradient term.

    Declared and wired but **not implemented**, because the history adapter
    serves a single point and there is no neighbourhood to average over yet.
    Implementing it later means a class satisfying this Protocol plus a config
    key — the call site in `build_features` already exists and already handles
    the null case, so no other module changes.

    An implementation must obey the same rule as everything else here: values
    for row t may depend only on observations at or before t.
    """

    def neighbour_features(
        self, frame: pd.DataFrame, latitude: float, longitude: float, columns: Sequence[str]
    ) -> pd.DataFrame:
        """Return a frame indexed like `frame`, with one column per feature."""
        ...


class NullNeighbourProvider:
    """The default: no spatial context available, so no columns.

    Returning an empty frame rather than zeros is deliberate. Zero-filled
    neighbour features would be indistinguishable to the model from a real
    measurement of zero local variance, and would appear in SHAP output as
    genuine drivers with no signal behind them.
    """

    def neighbour_features(
        self, frame: pd.DataFrame, latitude: float, longitude: float, columns: Sequence[str]
    ) -> pd.DataFrame:
        return pd.DataFrame(index=frame.index)


# --------------------------------------------------------------------------
# Static features
# --------------------------------------------------------------------------

# Coarse basin labels. Encoded as an integer code (LightGBM handles it as a
# categorical) so a global model can learn that the Arabian Sea and the North
# Sea behave differently at the same latitude.
_BASINS = (
    "arctic",
    "north_atlantic",
    "south_atlantic",
    "north_pacific",
    "south_pacific",
    "north_indian",
    "south_indian",
    "southern_ocean",
    "mediterranean",
)
_BASIN_CODE = {name: index for index, name in enumerate(_BASINS)}


def basin_label(latitude: float, longitude: float) -> str:
    """Which ocean basin a coordinate falls in.

    Boundaries are the conventional oceanographic ones, simplified to what a
    tree can actually use: the 60S Southern Ocean limit, the 66.5N Arctic
    circle, and the Atlantic/Indian/Pacific meridional splits at 20E, 147E and
    the Americas. Approximate by construction — its job is to give the model a
    regime handle, not to settle a cartographic dispute.
    """
    if latitude <= -60:
        return "southern_ocean"
    if latitude >= 66.5:
        return "arctic"
    if 30 <= latitude <= 46 and -6 <= longitude <= 42:
        return "mediterranean"

    # Atlantic: west of 20E and east of the Americas.
    if -70 <= longitude < 20 or longitude >= 290:
        return "north_atlantic" if latitude >= 0 else "south_atlantic"
    # Indian: 20E to 147E in the south, 20E to ~100E in the north.
    if 20 <= longitude < 147:
        if latitude >= 0 and longitude < 100:
            return "north_indian"
        if latitude < 0:
            return "south_indian"
    return "north_pacific" if latitude >= 0 else "south_pacific"


def basin_code(latitude: float, longitude: float) -> int:
    return _BASIN_CODE[basin_label(latitude, longitude)]


def distance_to_coast_km(latitude: float, longitude: float) -> float | None:
    """Kilometres to the nearest coastline.

    **Not implemented** — listed in the spec as a future static feature. It
    needs a coastline geometry or a distance raster, neither of which the
    backend currently carries, and `shapely`/`pyproj` alone will not conjure
    one. Returns None, and `build_features` omits the column entirely rather
    than emitting a placeholder that SHAP would happily rank.
    """
    return None


def add_static_features(
    frame: pd.DataFrame, latitude: float, longitude: float
) -> pd.DataFrame:
    """Position and terrain. Constant down a point series, but essential:
    these are what let one global model score a coordinate it never saw."""
    frame = frame.copy()
    frame["latitude"] = latitude
    frame["longitude"] = longitude
    # Absolute latitude carries the "distance from the equator" signal
    # directly, which a tree would otherwise need several splits to express.
    frame["abs_latitude"] = abs(latitude)
    frame["basin"] = basin_code(latitude, longitude)

    distance = distance_to_coast_km(latitude, longitude)
    if distance is not None:
        frame["distance_to_coast_km"] = distance
    return frame


# --------------------------------------------------------------------------
# Calendar features
# --------------------------------------------------------------------------


def add_calendar_features(frame: pd.DataFrame, *, cyclical: bool = True) -> pd.DataFrame:
    """Month, day, week, day-of-year, quarter, plus sin/cos encodings.

    The raw integers and the cyclic pair are both emitted, because they carry
    different things. A tree splits happily on `month <= 6`; what it cannot do
    is learn that 31 December and 1 January are adjacent, which is exactly
    where a seasonal ocean signal wraps. sin/cos closes that seam.
    """
    frame = frame.copy()
    stamps = pd.to_datetime(frame[TIMESTAMP])

    frame["month"] = stamps.dt.month.astype("int16")
    frame["day"] = stamps.dt.day.astype("int16")
    frame["week"] = stamps.dt.isocalendar().week.astype("int16")
    frame["day_of_year"] = stamps.dt.dayofyear.astype("int16")
    frame["quarter"] = stamps.dt.quarter.astype("int16")
    frame["day_of_week"] = stamps.dt.dayofweek.astype("int16")

    if cyclical:
        # 366 rather than 365 keeps leap years on the same circle instead of
        # overshooting 2*pi and putting 31 December at a slightly different
        # angle depending on the year.
        doy_angle = 2.0 * np.pi * frame["day_of_year"].astype("float64") / 366.0
        month_angle = 2.0 * np.pi * (frame["month"].astype("float64") - 1.0) / 12.0
        frame["doy_sin"] = np.sin(doy_angle)
        frame["doy_cos"] = np.cos(doy_angle)
        frame["month_sin"] = np.sin(month_angle)
        frame["month_cos"] = np.cos(month_angle)

    return frame


# --------------------------------------------------------------------------
# Series features — all trailing
# --------------------------------------------------------------------------


def add_lag_features(
    frame: pd.DataFrame, columns: Sequence[str], lags: Sequence[int]
) -> pd.DataFrame:
    """`{column}_lag{n}`: the value n steps ago.

    Positive shifts only. The frame is already regularised onto a complete
    time axis by `preprocessing.regularise`, so a positional shift and a
    temporal one are the same thing here — which is the reason regularisation
    is not optional.
    """
    frame = frame.copy()
    for column in columns:
        for lag in lags:
            frame[f"{column}_lag{lag}"] = frame[column].shift(lag)
    return frame


def add_rolling_features(
    frame: pd.DataFrame,
    columns: Sequence[str],
    windows: Sequence[int],
    statistics: Sequence[str],
) -> pd.DataFrame:
    """Trailing rolling statistics over the window ending at the current step.

    The window is closed *at* t, inclusive, not at t-1. That is safe precisely
    because the forecast horizon is always >= 1 (`add_forecast_target`
    enforces it): everything up to and including t is observed by the time a
    t+h prediction is made, so a window ending at t uses nothing unavailable
    at inference. Ending it at t-1 instead would silently throw away the most
    recent observation and make every model behave like an h+1 model.

    This is the boundary the whole no-leakage claim rests on, so it is worth
    stating exactly: a horizon of 0 would make these windows leak, which is
    why 0 is rejected rather than merely discouraged.
    """
    frame = frame.copy()
    for column in columns:
        for window in windows:
            roller = frame[column].rolling(window, min_periods=max(2, window // 2))
            for statistic in statistics:
                frame[f"{column}_roll{window}_{statistic}"] = getattr(roller, statistic)()
    return frame


def add_difference_features(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """First difference and percentage change.

    Level and rate are different signals: chlorophyll at 2 mg/m3 climbing
    steeply is a developing bloom, the same value while flat is not.
    """
    frame = frame.copy()
    for column in columns:
        frame[f"{column}_diff1"] = frame[column].diff()
        # Guard the denominator: pct_change on a field that legitimately
        # crosses zero (current components, sea level anomaly) produces
        # infinities that LightGBM will not accept.
        previous = frame[column].shift(1)
        change = (frame[column] - previous) / previous.replace(0.0, np.nan)
        frame[f"{column}_pct_change"] = change.replace([np.inf, -np.inf], np.nan)
    return frame


def add_trend_features(
    frame: pd.DataFrame, columns: Sequence[str], windows: Sequence[int]
) -> pd.DataFrame:
    """Slope of a least-squares line over the trailing `window` steps.

    Computed in closed form rather than with `.apply(polyfit)`, which is
    ~100x slower over a long series: for evenly spaced x the slope reduces to
    cov(x, y) / var(x), and var(x) is a constant for a fixed window.
    """
    frame = frame.copy()
    for window in windows:
        positions = np.arange(window, dtype="float64")
        centred = positions - positions.mean()
        denominator = float((centred**2).sum())
        for column in columns:
            slope = frame[column].rolling(window, min_periods=window).apply(
                lambda values, c=centred, d=denominator: float(
                    np.dot(values - values.mean(), c) / d
                ),
                raw=True,
            )
            frame[f"{column}_trend{window}"] = slope
    return frame


def add_circular_features(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """sin/cos of a compass bearing, for direction variables.

    A model fed raw degrees learns that 359 and 1 are 358 apart. They are two
    apart. Every lag of a circular column gets the same treatment, since the
    lags inherit the discontinuity.
    """
    frame = frame.copy()
    for column in columns:
        if column not in frame.columns:
            continue
        radians = np.radians(pd.to_numeric(frame[column], errors="coerce"))
        frame[f"{column}_sin"] = np.sin(radians)
        frame[f"{column}_cos"] = np.cos(radians)
    return frame


# --------------------------------------------------------------------------
# The target — the one forward shift
# --------------------------------------------------------------------------


def add_forecast_target(
    frame: pd.DataFrame, column: str, horizon: int
) -> pd.DataFrame:
    """Attach the value `horizon` steps *ahead* as the supervised target.

    This is the only forward shift in the package. Everything else is trailing
    by construction, and a test asserts that no other function in this module
    contains a negative shift. Keeping the count at exactly one is what makes
    the leakage question answerable by inspection rather than by argument.

    The last `horizon` rows get a NaN target — their future has not happened
    yet — and are dropped from training but are precisely the rows inference
    scores.

    A horizon of 0 is rejected. It is not a forecast, and it would invalidate
    the rolling windows, which are closed at t on the assumption that t is
    already observed when the prediction is made.
    """
    if horizon < 1:
        raise FeatureError(
            f"forecast horizon must be >= 1 step, got {horizon}. A zero horizon "
            "is a nowcast, not a forecast, and would make the trailing features "
            "leak the target."
        )
    frame = frame.copy()
    frame[TARGET] = frame[column].shift(-horizon)
    # The anchor is the value at feature time — the persistence forecast. It is
    # emitted alongside the target for every variable, whether or not the
    # trainer is configured to use a delta target, because the evaluator needs
    # it to score the model against persistence either way.
    frame[TARGET_ANCHOR] = frame[column]
    return frame


# --------------------------------------------------------------------------
# Builder
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureMatrix:
    """A built feature set, plus everything needed to rebuild it identically."""

    frame: pd.DataFrame
    feature_columns: list[str]
    target_column: str
    categorical_columns: list[str]

    @property
    def X(self) -> pd.DataFrame:  # noqa: N802 - conventional in ML code
        return self.frame[self.feature_columns]

    @property
    def y(self) -> pd.Series:
        return self.frame[self.target_column]


def build_features(
    frame: pd.DataFrame,
    variable: VariableConfig,
    features: FeatureConfig,
    *,
    latitude: float,
    longitude: float,
    horizon: int | None = None,
    covariates: Sequence[str] | None = None,
    neighbours: NeighbourFeatureProvider | None = None,
) -> FeatureMatrix:
    """Build the full feature matrix for one point series.

    `horizon=None` builds features without a target — the inference path,
    where the last row is the one to score. Passing a horizon adds the target
    column and is the training path.

    The same function serves both on purpose: a separate inference-time
    feature builder is how train/serve skew gets in, and it is invisible until
    the predictions are quietly wrong.
    """
    target_column = variable.code
    if target_column not in frame.columns:
        raise FeatureError(
            f"target column {target_column!r} is not in the series "
            f"(have: {sorted(c for c in frame.columns if c != TIMESTAMP)})"
        )

    covariate_columns = [
        column for column in (covariates or variable.covariates) if column in frame.columns
    ]
    # Static columns arrive as ordinary columns from the history fetch
    # (ocean_depth is a time-invariant provider), so they must be excluded from
    # the series treatment — lagging a constant produces 20 identical columns.
    series_columns = [
        column
        for column in [target_column, *covariate_columns]
        if column not in STATIC_COLUMNS
    ]

    built = frame.copy()

    # Circular encodings come first so the sin/cos columns are themselves
    # lagged and rolled below, rather than only the raw degrees.
    circular_columns: list[str] = []
    if variable.circular and target_column in series_columns:
        built = add_circular_features(built, [target_column])
        circular_columns = [f"{target_column}_sin", f"{target_column}_cos"]

    lagged_columns = [*series_columns, *circular_columns]

    if features.lags:
        built = add_lag_features(built, lagged_columns, features.lags)
    if features.rolling_windows and features.rolling_statistics:
        built = add_rolling_features(
            built, lagged_columns, features.rolling_windows, features.rolling_statistics
        )
    if features.differences:
        built = add_difference_features(built, series_columns)
    if features.trend_windows:
        built = add_trend_features(built, series_columns, features.trend_windows)
    if features.calendar:
        built = add_calendar_features(built, cyclical=features.cyclical)
    if features.static:
        built = add_static_features(built, latitude, longitude)

    provider = neighbours or NullNeighbourProvider()
    neighbour_frame = provider.neighbour_features(built, latitude, longitude, series_columns)
    if not neighbour_frame.empty:
        built = pd.concat([built, neighbour_frame], axis=1)

    if horizon is not None:
        built = add_forecast_target(built, target_column, horizon)

    # The target's *current* value stays in the feature set. It is observed at
    # t and the target is at t+h with h >= 1, so it is available at inference
    # and is not leakage — it is the persistence signal, which for a
    # short-horizon geophysical forecast is the single strongest feature there
    # is. Dropping it out of caution would mean shipping a model beaten by
    # "tomorrow looks like today".
    #
    # A circular variable is the one exception: its raw degrees are excluded in
    # favour of the sin/cos pair added above, since 359 and 1 are adjacent on
    # the compass and two units apart in the column.
    excluded = {TIMESTAMP, TARGET, TARGET_ANCHOR}
    if variable.circular:
        excluded.add(target_column)
    feature_columns = [
        column
        for column in built.columns
        if column not in excluded and pd.api.types.is_numeric_dtype(built[column])
    ]

    categorical_columns = [column for column in ("basin",) if column in feature_columns]

    if not feature_columns:
        raise FeatureError(f"no usable features were produced for {target_column!r}")

    return FeatureMatrix(
        frame=built,
        feature_columns=feature_columns,
        target_column=TARGET if horizon is not None else target_column,
        categorical_columns=categorical_columns,
    )
