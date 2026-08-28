"""Persistent per-cell identity for marine heatwaves — the half
`services/heatwaves.py` deliberately left out.

`heatwaves.detect` stays a pure, window-censored snapshot on purpose: given
one `WINDOW_DAYS`-day stack of daily fields, it reports "this cell is in its
Nth consecutive day above threshold *within the window examined*", and
nothing here changes that — it is what makes `tests/test_heatwaves.py` able
to drive the science with synthetic fields and no network, the same reason
`services/eddies.py::detect` stays pure over a currents snapshot.

**The actual gap turned out simpler than the eddy-tracking analogy in
TODO.md suggested.** An eddy moves between frames, so `eddy_tracking.py`
solves a real assignment problem (which blob in frame 2 is which blob from
frame 1) via a KD-tree-gated, connected-components, `linear_sum_assignment`
matcher. A heatwave cell does not move: the grid is the same grid every
refresh, so cell `(row, col)` *is* its own identity for free — there is
nothing to match. The actual limitation was that `detect` only ever looks at
whatever window it was just handed, so a run older than `WINDOW_DAYS` is
reported as 30 days old forever, never more, no matter how much longer it
has actually run.

**The fix is a day-by-day persistent fold, not a matcher.** `advance()` walks
the same daily stack `heatwaves.refresh_cache` already fetched, one calendar
day at a time, and folds each new day into state that survives across
refreshes: a run's true onset date, its true duration (uncapped by any
window), its cumulative intensity (degree-days of exceedance summed over the
run), and the peak category it reached. Called from `refresh_cache` with the
exact `record`/`climatology` already in hand, so tracking costs no second
OISST fetch. It shares `heatwaves.detect`'s own per-day arithmetic
(`services/heatwave_common.py`'s `day_state`/`categorize`) rather than
recomputing the Hobday formula a second way — this module imports from
`heatwave_common`, never from `heatwaves` itself, precisely so `heatwaves.py`
can import *this* module (to call `advance` from `refresh_cache`) without a
cycle.

**What is honest about this, and what still is not.** A run's `onset_date`
is exact for any run that began after this process's tracker was first
initialised — the tracker watched it start. A run that was *already* active
on the very first day this tracker ever processed cannot know whether it
started earlier still; `possibly_started_earlier` says so on exactly that
case, the same honesty `run_days_censored` gave the old window-only field,
just narrowed from "recurring every `WINDOW_DAYS`" to "once, at boot".
**State does not survive a restart** — an in-process dict of arrays, the
same limitation `eddy_tracking.py` and `services/dashboard/history.py`'s KPI
ring buffer both already carry, and for the same reason: there is no
upstream that can answer "how long has this cell really been in heatwave"
for this to fall back to, and a database record implies a durability
guarantee a computed, re-derivable-from-history series does not need to make.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr
from loguru import logger

from services.climatology import build as climatology_build
from services.heatwave_common import CATEGORY_NAMES, MIN_DURATION_DAYS, categorize, day_state


def _epoch_days(stamps: pd.DatetimeIndex) -> np.ndarray:
    """Calendar day as a plain monotonic integer (days since the Unix epoch)
    — not a proleptic-Gregorian ordinal, just something that compares and
    round-trips to an ISO date, since nothing here needs calendar arithmetic
    beyond "is this day newer than the last one processed"."""
    return stamps.normalize().values.astype("datetime64[D]").astype(np.int64)


def ordinal_to_iso(day_ordinal: int) -> str:
    return str(np.datetime64(int(day_ordinal), "D"))


def _grids_match(a: np.ndarray, b: np.ndarray) -> bool:
    return a.shape == b.shape and bool(np.allclose(a, b))


@dataclass
class _State:
    latitude: np.ndarray
    longitude: np.ndarray
    run_days: np.ndarray  # int32, true persistent count (not window-censored)
    onset_ordinal: np.ndarray  # int64, epoch-day the current run began; 0 = not in a run
    cumulative_c_days: np.ndarray  # float32, degree-days of exceedance over the current run
    peak_category: np.ndarray  # int8, index into CATEGORY_NAMES; highest reached this run
    last_processed_ordinal: int = 0  # 0 = never processed
    tracking_started_ordinal: int = 0  # 0 = not yet initialised


_state: _State | None = None
_lock = threading.Lock()


def _fresh_state(latitude: np.ndarray, longitude: np.ndarray) -> _State:
    shape = (len(latitude), len(longitude))
    return _State(
        latitude=latitude,
        longitude=longitude,
        run_days=np.zeros(shape, dtype="int32"),
        onset_ordinal=np.zeros(shape, dtype="int64"),
        cumulative_c_days=np.zeros(shape, dtype="float32"),
        peak_category=np.zeros(shape, dtype="int8"),
    )


def advance(record: xr.DataArray, climatology: xr.Dataset) -> None:
    """Fold every calendar day in `record` newer than the last one already
    processed into persistent per-cell state.

    Idempotent: a `record` carrying no day newer than what has already been
    folded in is a no-op, so calling this once per `heatwaves.refresh_cache`
    tick — whether or not OISST actually published a new day since the last
    tick — never double-counts a day. Robust to a gap of missed refreshes up
    to `record`'s own window (currently `heatwaves.WINDOW_DAYS + 5` days): any
    unprocessed day still inside the newly fetched window is folded in, in
    chronological order, on the next successful call.

    A grid change (the climatology rebuilt at a different resolution) resets
    all tracked state rather than trying to reproject it — logged, since that
    silently re-censors every run's onset date back to "unknown until now".
    """
    if "time" not in record.dims:
        raise ValueError("record must carry a `time` dimension")

    stamps = pd.DatetimeIndex(record["time"].values)
    epoch_day = _epoch_days(stamps)
    doy = climatology_build.day_index(stamps)
    p90_all = climatology["p90"].values[doy - 1]
    mean_all = climatology["mean"].values[doy - 1]
    values_all = record.values

    lats = np.asarray(record["latitude"].values, dtype="float64")
    lons = np.asarray(record["longitude"].values, dtype="float64")

    global _state
    with _lock:
        state = _state
        if state is None:
            state = _fresh_state(lats, lons)
        elif not _grids_match(state.latitude, lats) or not _grids_match(state.longitude, lons):
            logger.warning(
                "heatwave tracking grid changed (climatology rebuilt at a new "
                "resolution?) — resetting all tracked onset/duration state"
            )
            state = _fresh_state(lats, lons)

        new_days = [
            i
            for i in range(len(epoch_day))
            if state.last_processed_ordinal == 0 or epoch_day[i] > state.last_processed_ordinal
        ]
        if not new_days:
            _state = state
            return

        if state.tracking_started_ordinal == 0:
            state.tracking_started_ordinal = int(epoch_day[new_days[0]])

        for i in new_days:
            above = values_all[i] > p90_all[i]
            exceedance, multiple = day_state(values_all[i], p90_all[i], mean_all[i])

            starting = above & (state.run_days == 0)
            new_run_days = np.where(above, state.run_days + 1, 0).astype("int32")
            qualifies = above & (new_run_days >= MIN_DURATION_DAYS)
            category_today = categorize(multiple, qualifies)

            state.onset_ordinal = np.where(
                starting, epoch_day[i], np.where(above, state.onset_ordinal, 0)
            ).astype("int64")
            # `exceedance` is only finite and positive where `above` is true
            # (an off-coverage cell is NaN in `values_all`, and NaN > p90 is
            # False), so this never folds a NaN or a non-exceeding day in.
            state.cumulative_c_days = np.where(
                above, state.cumulative_c_days + exceedance, 0.0
            ).astype("float32")
            state.peak_category = np.where(
                above, np.maximum(state.peak_category, category_today), 0
            ).astype("int8")
            state.run_days = new_run_days
            state.last_processed_ordinal = int(epoch_day[i])

        _state = state


def is_available() -> bool:
    with _lock:
        return _state is not None


def snapshot(latitude: float, longitude: float) -> dict[str, Any]:
    """The tracked state at the nearest cell to one coordinate.

    Meant to be merged into `heatwaves.at_point`'s response as a `tracked`
    sub-object, not called standalone against a point that might be land or
    off-coverage — the caller already knows that; this only ever reports
    "not in a run" or a run's true onset/duration/intensity/peak.
    """
    with _lock:
        state = _state
    if state is None:
        return {
            "available": False,
            "unavailable_reason": "no tracked heatwave history yet — the server has not completed a refresh",
        }

    row = int(np.abs(state.latitude - latitude).argmin())
    # Longitudes compared on the circle, same fix `heatwaves.at_point` and
    # `services/eddies.py` both already needed: a point at 179.9 is next to
    # -179.9, and a plain argmin over the raw difference puts it half a
    # planet away.
    delta = np.abs((state.longitude - longitude + 180.0) % 360.0 - 180.0)
    column = int(delta.argmin())

    run_days = int(state.run_days[row, column])
    tracking_since = ordinal_to_iso(state.tracking_started_ordinal)
    if run_days == 0:
        return {
            "available": True,
            "in_heatwave": False,
            "run_days": 0,
            "onset_date": None,
            "peak_category": CATEGORY_NAMES[0],
            "cumulative_intensity_c_days": None,
            "possibly_started_earlier": False,
            "tracking_since": tracking_since,
        }

    onset_ordinal = int(state.onset_ordinal[row, column])
    return {
        "available": True,
        "in_heatwave": True,
        "run_days": run_days,
        "onset_date": ordinal_to_iso(onset_ordinal),
        "peak_category": CATEGORY_NAMES[int(state.peak_category[row, column])],
        "cumulative_intensity_c_days": round(float(state.cumulative_c_days[row, column]), 2),
        "possibly_started_earlier": onset_ordinal == state.tracking_started_ordinal,
        "tracking_since": tracking_since,
    }


def tracked_arrays(latitude: np.ndarray, longitude: np.ndarray) -> dict[str, Any] | None:
    """The tracked arrays in bulk, for `heatwaves.cells()` to index directly
    rather than doing a nearest-cell lookup per rectangle. `None` when no
    tracking has run yet, or — defensively, should never actually happen
    since both are fed from the same climatology grid — the caller's grid
    does not match the tracker's own.
    """
    with _lock:
        state = _state
    if state is None or not _grids_match(state.latitude, latitude) or not _grids_match(state.longitude, longitude):
        return None
    return {
        "run_days": state.run_days,
        "onset_ordinal": state.onset_ordinal,
        "cumulative_c_days": state.cumulative_c_days,
        "peak_category": state.peak_category,
        "tracking_started_ordinal": state.tracking_started_ordinal,
    }
