"""Marine heatwaves, to the Hobday definition — the platform's second detector.

What makes this different from the SST anomaly already on the dashboard
------------------------------------------------------------------------
`services/crw.py` reports where SST sits against a climatology of **means**.
That is an anomaly, and an anomaly is not an event: +1.5 degC in a place that
routinely swings 4 degC is unremarkable, and +1.5 degC where the seasonal range
is 0.5 degC is extraordinary. Hobday et al. (2016) define a marine heatwave as
SST above the **seasonally-varying 90th percentile** for **at least five
consecutive days**, which is a statement about the local distribution rather
than the local mean, and which no mean-based climatology can express.

Both halves of that definition are load-bearing and each is easy to drop:

* **The percentile** comes from `services/climatology/` — the whole reason that
  package exists. TODO.md records that even the one variable with a baseline did
  not have the *right* baseline.
* **The five days** is what separates an event from a warm afternoon. A detector
  that flags today's field against today's threshold reports weather, calls it a
  heatwave, and will light up a large fraction of the ocean on any given day.
  `detect` therefore takes a *stack* of consecutive daily fields, not a
  snapshot, and refuses to guess when it is handed too few.

Categories follow Hobday's own scale, which is defined by multiples of the gap
between the climatological mean and the 90th percentile: 1x-2x moderate, 2x-3x
strong, 3x-4x severe, 4x+ extreme. That construction is why `mean` is stored
beside `p90` — a category cannot be computed from the threshold alone.

Masking is inherited, not reinvented
------------------------------------
`services/crw.py` records three maskings found empirically, and two apply here
unchanged. Aggregate statistics are taken over **60S-60N**: polar ice-margin
cells carry anomalies above +15 degC because the climatology expects ice and
summer retreat leaves water, and they tripled the global mean. The per-cell
field is *not* masked — a heatwave in the Barents Sea is real and the map should
draw it — only the headline numbers are, and the response says so.

What this deliberately does not do
----------------------------------
It does not track events between refreshes, exactly as `services/eddies.py` does
not track eddies. A marine heatwave has a duration, an onset date and a
cumulative intensity, and all three require holding identity across days; that
is the same frame-to-frame assignment problem, with the same failure mode of
presenting a matcher's artefact as an observation. What is reported here is
"this cell is in its Nth consecutive day above threshold *within the window
examined*", which is a bounded claim the data supports.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr
from loguru import logger

from services import field_sampling
from services.climatology import build as climatology_build
from services.climatology import oisst
from services.climatology import store as climatology_store

# Hobday's minimum duration. Five days is the published definition, not a knob —
# it is exposed as a constant so the response can state it, not so it can be
# tuned down until something shows up.
MIN_DURATION_DAYS = 5

# Category boundaries as multiples of (p90 - mean). Hobday et al. 2018.
CATEGORY_NAMES = ("none", "moderate", "strong", "severe", "extreme")

# Aggregates only. See the module docstring and `services/crw.py`.
AGGREGATE_LATITUDE_LIMIT = 60.0

# How many days of record `detect` wants. Enough to establish MIN_DURATION_DAYS
# and to report a run length that means something, without pretending to know an
# event's true onset — a cell at the window's edge may have been in heatwave for
# far longer, and `run_days_censored` says so.
WINDOW_DAYS = 30

METHOD = (
    "Hobday et al. marine heatwave definition: SST above the seasonally-varying "
    "90th percentile for at least 5 consecutive days"
)

LIMITS = (
    "Detection only — events are not tracked between refreshes, so no heatwave "
    "here has an onset date, a duration or a cumulative intensity.",
    f"Run lengths are censored at the {WINDOW_DAYS}-day window examined: a cell "
    "in heatwave on the window's first day may have been so for much longer.",
    "Aggregate statistics cover 60S-60N. Polar ice-margin cells carry anomalies "
    "above +15 degC because the climatology expects ice, and including them "
    "triples the global mean. The per-cell field is unmasked.",
    "The threshold is a 1991-2020 baseline. A warming ocean means a fixed "
    "baseline reports more heatwave over time by construction; that is the "
    "intended reading, not a drift in the detector.",
)


class HeatwaveError(RuntimeError):
    """Marine heatwave detection is unavailable.

    Distinct from `ClimatologyNotBuilt`, which is the more specific and more
    actionable case: the climatology was never built. Both become a 503 with the
    reason, never a fabricated field.
    """


@dataclass(frozen=True)
class HeatwaveField:
    """One pass over one window of daily fields."""

    # (lat, lon) int8: index into CATEGORY_NAMES, 0 where there is no heatwave.
    category: np.ndarray
    # (lat, lon) float32: SST minus the day's p90, degC. NaN off-coverage.
    exceedance: np.ndarray
    # (lat, lon) int16: consecutive days above p90 ending on the latest day.
    run_days: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    timestamp: datetime
    computed_at: datetime
    baseline: tuple[int, int]
    window_days: int

    def coverage(self) -> dict[str, Any]:
        """Headline statistics, over 60S-60N only."""
        inside = np.abs(self.latitude) <= AGGREGATE_LATITUDE_LIMIT
        category = self.category[inside]
        ocean = np.isfinite(self.exceedance[inside])
        ocean_cells = int(ocean.sum())
        if ocean_cells == 0:
            return {
                "ocean_cells": 0,
                "heatwave_fraction": None,
                "unavailable_reason": "no ocean cells inside 60S-60N in this field",
            }

        in_heatwave = (category > 0) & ocean
        by_category = {
            name: int(((category == index) & ocean).sum())
            for index, name in enumerate(CATEGORY_NAMES)
            if index > 0
        }
        return {
            "ocean_cells": ocean_cells,
            "cells_in_heatwave": int(in_heatwave.sum()),
            "heatwave_fraction": round(float(in_heatwave.sum() / ocean_cells), 5),
            "by_category": by_category,
            "latitude_band_deg": [-AGGREGATE_LATITUDE_LIMIT, AGGREGATE_LATITUDE_LIMIT],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "computed_at": self.computed_at.isoformat(),
            "method": METHOD,
            "min_duration_days": MIN_DURATION_DAYS,
            "baseline": {"start": self.baseline[0], "end": self.baseline[1]},
            "window_days": self.window_days,
            "categories": list(CATEGORY_NAMES),
            "coverage": self.coverage(),
            "limits": list(LIMITS),
        }


def _trailing_run_length(above: np.ndarray) -> np.ndarray:
    """Consecutive True values ending at the last day, per cell.

    `above` is (time, lat, lon). Walks backward from the most recent day and
    stops each cell at its first False — vectorised, because the alternative is
    a per-cell Python loop over a 180x360 grid and this module is meant to be
    cheap enough to compute on demand.
    """
    reversed_ = above[::-1]
    # cumprod over a boolean is 1 until the first zero, then 0 forever after,
    # which is exactly "consecutive from the end".
    return np.cumprod(reversed_, axis=0).sum(axis=0).astype("int16")


def detect(
    record: xr.DataArray,
    climatology: xr.Dataset,
    *,
    min_duration_days: int = MIN_DURATION_DAYS,
) -> HeatwaveField:
    """Detect marine heatwaves in a window of consecutive daily SST fields.

    Pure: a record and a climatology in, a field out. No fetching, no cache, no
    clock — the same shape as `services/eddies.py::detect`, and for the same
    reason: it makes the science testable without a network.
    """
    if "time" not in record.dims:
        raise HeatwaveError("record must carry a `time` dimension")

    days = record.sizes["time"]
    if days < min_duration_days:
        # Refusing is the point. With fewer days than the definition requires,
        # any answer would be reporting a warm day as an event.
        raise HeatwaveError(
            f"a {min_duration_days}-day definition needs at least "
            f"{min_duration_days} consecutive daily fields; got {days}"
        )

    if record.sizes["latitude"] != climatology.sizes["latitude"]:
        raise HeatwaveError(
            "record and climatology are on different grids; regrid before "
            "detecting rather than letting xarray align and drop cells"
        )

    stamps = pd.DatetimeIndex(record["time"].values)
    indices = climatology_build.day_index(stamps)

    # The threshold varies per day, so it is gathered per day rather than taken
    # from the latest — over a 30-day window in spring the seasonal p90 moves
    # measurably, and using one day's threshold for the whole window would bias
    # the run length in whichever direction the season is going.
    p90 = climatology["p90"].values[indices - 1]
    mean = climatology["mean"].values[indices - 1]
    values = record.values

    above = values > p90
    run_days = _trailing_run_length(above)

    latest = values[-1]
    latest_p90 = p90[-1]
    latest_mean = mean[-1]
    exceedance = (latest - latest_p90).astype("float32")

    # Hobday's category scale: multiples of the mean-to-p90 gap. Where that gap
    # is zero or undefined the category is undefined too, not "extreme" —
    # dividing by it would make a degenerate cell the most alarming one on the
    # map.
    gap = latest_p90 - latest_mean
    with np.errstate(divide="ignore", invalid="ignore"):
        multiple = np.where(gap > 0, (latest - latest_mean) / gap, np.nan)

    qualifies = (run_days >= min_duration_days) & np.isfinite(exceedance) & (exceedance > 0)
    category = np.zeros(latest.shape, dtype="int8")
    for index in (1, 2, 3, 4):
        lower = index
        upper = index + 1
        band = qualifies & np.isfinite(multiple) & (multiple >= lower)
        if index < 4:
            band &= multiple < upper
        category[band] = index

    return HeatwaveField(
        category=category,
        exceedance=np.where(np.isfinite(latest), exceedance, np.nan).astype("float32"),
        run_days=run_days,
        latitude=np.asarray(record["latitude"].values, dtype="float64"),
        longitude=np.asarray(record["longitude"].values, dtype="float64"),
        timestamp=stamps[-1].to_pydatetime().replace(tzinfo=UTC),
        computed_at=datetime.now(UTC),
        baseline=(
            int(climatology.attrs.get("baseline_start", 0)),
            int(climatology.attrs.get("baseline_end", 0)),
        ),
        window_days=days,
    )


# --------------------------------------------------------------------- cache

_cache: HeatwaveField | None = None
_lock = threading.Lock()


def _cached_field(field: HeatwaveField | None = None) -> HeatwaveField | None:
    """Read or replace the cached detection. Separate from the fetch so tests
    can drive `detect` without touching the network."""
    global _cache
    with _lock:
        if field is not None:
            _cache = field
        return _cache


def at_point(
    latitude: float, longitude: float, field: HeatwaveField | None = None
) -> dict[str, Any]:
    """The heatwave state at one coordinate, for the point brief.

    Returns a row even where there is no heatwave — `services/eddies.py::nearest`
    records why: an absence is an answer, and a missing row reads as "nothing
    anywhere". Over land it says so rather than reporting category 0, which
    would imply the water there is merely unremarkable.
    """
    resolved = field or _cached_field()
    if resolved is None:
        raise HeatwaveError(
            "no marine heatwave field has been computed yet — the climatology "
            "or the recent SST record is not loaded"
        )

    row = int(np.abs(resolved.latitude - latitude).argmin())
    # Longitudes are compared on the circle: a point at 179.9 is next to -179.9,
    # and a plain argmin over the difference puts it half a planet away.
    delta = np.abs((resolved.longitude - longitude + 180.0) % 360.0 - 180.0)
    column = int(delta.argmin())

    exceedance = float(resolved.exceedance[row, column])
    if not np.isfinite(exceedance):
        return {
            "latitude": float(resolved.latitude[row]),
            "longitude": float(resolved.longitude[column]),
            "available": False,
            "unavailable_reason": (
                "no sea-surface temperature at this cell — it is land, ice, or "
                "outside the record's coverage"
            ),
        }

    index = int(resolved.category[row, column])
    return {
        "latitude": float(resolved.latitude[row]),
        "longitude": float(resolved.longitude[column]),
        "available": True,
        "category": CATEGORY_NAMES[index],
        "in_heatwave": index > 0,
        "exceedance_c": round(exceedance, 3),
        "run_days": int(resolved.run_days[row, column]),
        "run_days_censored": bool(resolved.run_days[row, column] >= resolved.window_days),
        "timestamp": resolved.timestamp.isoformat(),
        "baseline": {"start": resolved.baseline[0], "end": resolved.baseline[1]},
        "note": (
            "Marine heatwave state against a 1991-2020 daily 90th-percentile "
            "baseline. Not tracked between refreshes, so this carries no onset "
            "date or total duration."
        ),
    }


def is_available() -> bool:
    """Whether a field is loaded. Drives the three-way ready/warming/unavailable
    the dashboard uses, rather than letting a cold start look like a failure."""
    return _cached_field() is not None


def climatology_available(variable: str = "sea_surface_temperature") -> bool:
    return variable in climatology_store.available()


def logged_summary(field: HeatwaveField) -> str:
    coverage = field.coverage()
    fraction = coverage.get("heatwave_fraction")
    return (
        f"marine heatwave detection at {field.timestamp.isoformat()}: "
        f"{coverage.get('cells_in_heatwave', 0)} of {coverage.get('ocean_cells', 0)} "
        f"ocean cells (60S-60N) in heatwave"
        + (f", {fraction:.1%}" if fraction is not None else "")
    )


def log_detection(field: HeatwaveField) -> None:
    logger.info(logged_summary(field))


# ------------------------------------------------------------------- refresh

# OISST is a daily product published with about a day's lag, so refreshing more
# often than that re-fetches a field that cannot have changed. Twelve hours
# gives two chances to pick up each day's publication without polling.
REFRESH_INTERVAL_HOURS = 12

_refreshing = threading.Lock()


def is_refreshing() -> bool:
    """Whether a refresh is in flight, so a cold start renders as `warming`
    rather than as `unavailable` — the dashboard's three-way rule."""
    return _refreshing.locked()


async def refresh_cache(variable: str = "sea_surface_temperature") -> None:
    """Fetch the recent OISST tail and recompute the field.

    Never raises: this runs as a fire-and-forget scheduler task, where an
    escaping exception is swallowed by asyncio and leaves the cache empty
    forever while every endpoint 503s with nothing logged. That failure has
    already happened twice in this codebase (`copernicus_wind`,
    `vector_source`), and the mitigation is this log line.
    """
    if _refreshing.locked():
        logger.debug("marine heatwave refresh already in flight; skipping")
        return

    with _refreshing:
        try:
            climatology = climatology_store.load(variable)
        except climatology_store.ClimatologyNotBuilt as exc:
            # Not an error to shout about on every boot: the climatology is an
            # offline artifact and a fresh clone will not have one until it is
            # built. The endpoint says the same thing to a caller.
            logger.info(f"marine heatwaves unavailable: {exc}")
            return

        try:
            resolution = float(climatology.attrs.get("resolution_deg", 1.0))
            # `fetch_recent`, not a date range ending today. **OISST publishes
            # with a lag** — coverage ended 2026-08-01 when checked on
            # 2026-08-17 — and a griddap request running past the dataset's end
            # answers 404, which is indistinguishable by status code from the
            # reload 404 this module retries. Asking by date therefore burned
            # five attempts and ~8 minutes of backoff on every refresh, for a
            # reason no amount of retrying could fix. `last` lets the dataset
            # name its own end.
            record = await oisst.fetch_recent(
                WINDOW_DAYS + 5, resolution_deg=resolution
            )
            # The detection is numpy over a resident grid — small, but it is
            # still CPU on the event loop, and this runs on the server's loop at
            # boot. Same rule as `ocean_state.py` and the grid builder.
            field = await asyncio.to_thread(detect, record["sst"], climatology)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            logger.warning(f"marine heatwave refresh failed: {exc}")
            return

        _cached_field(field)
        log_detection(field)


def current_field() -> HeatwaveField:
    """The cached field, or a clear reason there is none.

    503, not 502: this reads a cache *this* server warms and an artifact this
    project builds, so an unavailable answer is ours to explain — the same split
    `services/eddies.py` draws against the OBIS call beside it.
    """
    field = _cached_field()
    if field is None:
        if not climatology_available():
            raise HeatwaveError(
                "no sea-surface temperature climatology has been built — run "
                "`python scripts/build_climatology.py` (about 25 minutes)"
            )
        raise HeatwaveError(
            "the marine heatwave field has not been computed yet; the recent "
            "sea-surface temperature record is still loading"
        )
    return field


def cells(field: HeatwaveField | None = None) -> dict[str, Any]:
    """Cells currently in a marine heatwave, as drawable rectangles.

    Only cells with a category, deliberately: the interesting output is sparse
    (a few percent of the ocean on a typical day) and sending 40,000 mostly-zero
    cells to draw nothing would be most of the payload for none of the picture.
    The map's blankness is then meaningful in the same way the eDNA layer's is —
    which is why `coverage` rides along, so the UI can say how much ocean was
    examined rather than leaving "empty" to be read as "not loaded".
    """
    resolved = field or _cached_field()
    if resolved is None:
        raise HeatwaveError(
            "no marine heatwave field has been computed yet — the climatology "
            "or the recent sea-surface temperature record is not loaded"
        )

    south, north = field_sampling.cell_edges(resolved.latitude)
    west, east = field_sampling.cell_edges(resolved.longitude)
    rows, columns = np.nonzero(resolved.category > 0)

    return {
        **resolved.as_dict(),
        "cells": [
            {
                "west": round(float(west[column]), 4),
                "south": round(float(south[row]), 4),
                "east": round(float(east[column]), 4),
                "north": round(float(north[row]), 4),
                "category": CATEGORY_NAMES[int(resolved.category[row, column])],
                "category_index": int(resolved.category[row, column]),
                "exceedance_c": round(float(resolved.exceedance[row, column]), 3),
                "run_days": int(resolved.run_days[row, column]),
            }
            for row, column in zip(rows.tolist(), columns.tolist(), strict=True)
        ],
    }
