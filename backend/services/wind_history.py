"""A trailing multi-day mean of wind-driven Ekman transport, for testing
whether upwelling corroboration improves against an *integrated* wind rather
than an instantaneous one.

Why this exists
----------------
`services/sst_anomaly.py` and `services/upwelling.py`'s own docstrings both
record two already-tried, already-failed levers for widening the
upwelling/SST corroboration contrast (closing OISST's latency gap; fitting
the baseline on the product being scored) and land on the same diagnosis:
**the wind and SST snapshots on both sides of the control are instantaneous**,
and upwelling responds to wind integrated over days, not to a single hourly
reading. This module is the one untried lever TODO.md pointed at — a rolling
history the index can be computed against instead of the latest timestep
alone.

**Averaged transport, not averaged wind.** Wind stress is `tau ~ |U| * U` —
quadratic and directional — so averaging raw `u`/`v` vectors first and only
then computing stress can cancel real forcing that a fluctuating-but-strong
wind actually applied (two hours of equal-and-opposite gusts average to zero
wind, not to zero stress). Averaging the Ekman transport that
`services/upwelling.py` already computes from each hourly snapshot is the
physically defensible version of "wind integrated over days", and is the
only reason this module imports `upwelling`'s own `wind_stress`/`coriolis`/
`ekman_transport` rather than recomputing the formula a second way.

**Stored on a fixed 1-degree grid, not the wind product's own ~0.25-degree
one.** This is genuinely a resolution trade, made explicit rather than
buried in a downsample constant: an hourly sample at the wind product's own
resolution is ~8 MB for the transport pair, and keeping several days of
those would cost hundreds of MB resident for a signal this is already
smoothing over days. 1 degree is the same resolution `services/climatology/`
already fits OISST at and this codebase already resamples onto finer grids
via `field_sampling.build_sampler` (see `services/upwelling.py::_resample_scalar`,
reused here) — an averaging product does not need to keep the wind field's
own native resolution to be a fair test of "does a multi-day mean help".

**State does not survive a restart** — an in-process ring buffer, the same
limitation and the same reason `services/eddy_tracking.py` and
`services/dashboard/history.py`'s KPI buffer both already carry: there is no
upstream that can answer "what was the wind six hours ago" for this to fall
back to.
"""

from __future__ import annotations

import threading
import warnings
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import xarray as xr

from services import field_sampling
from services.vector_source import VectorSnapshot

# The grid history samples are resampled onto and stored at — see the module
# docstring for why this is coarser than the wind product's own resolution.
_GRID_RESOLUTION_DEG = 1.0
_GRID_LAT = np.arange(-89.5, 90.0, _GRID_RESOLUTION_DEG)
_GRID_LON = np.arange(-179.5, 180.0, _GRID_RESOLUTION_DEG)

# How long a sample is kept at all. Set above the longest window this is
# meant to be tested at (a few days) so `trailing_mean` can be asked for a
# shorter window without the record side needing to change; not set much
# higher, since each sample is real resident memory.
RETAIN_DAYS = 4.0

# Wind refreshes hourly (`main.py::WIND_REFRESH_INTERVAL_HOURS`); a small
# margin over `RETAIN_DAYS` at that cadence bounds the deque without a second
# time-based prune on every read.
_MAX_SAMPLES = int(RETAIN_DAYS * 24) + 6

# `trailing_mean` refuses to average a window it does not actually have
# coverage for — a "3-day mean" built from two samples an hour apart because
# the buffer only just started filling would be a misleading label on a
# near-instantaneous reading. Requires the collected samples to span at
# least this fraction of the requested window.
MIN_COVERAGE_FRACTION = 0.5


@dataclass(frozen=True)
class _Sample:
    timestamp: datetime
    m_east: np.ndarray
    m_north: np.ndarray


@dataclass(frozen=True)
class MeanTransport:
    """A trailing average of Ekman transport, on the fixed history grid."""

    latitude: np.ndarray
    longitude: np.ndarray
    m_east: np.ndarray
    m_north: np.ndarray
    window_days: float
    samples: int
    span_days: float
    oldest: datetime
    newest: datetime

    def describe(self) -> dict[str, Any]:
        return {
            "requested_window_days": self.window_days,
            "actual_span_days": round(self.span_days, 2),
            "samples": self.samples,
            "oldest": self.oldest.isoformat(),
            "newest": self.newest.isoformat(),
        }


_samples: deque[_Sample] = deque(maxlen=_MAX_SAMPLES)
_lock = threading.Lock()


def reset() -> None:
    """Drop all history. Used by tests."""
    with _lock:
        _samples.clear()


def is_available() -> bool:
    with _lock:
        return len(_samples) > 0


def record(wind: VectorSnapshot) -> None:
    """Fold one wind snapshot into the history, resampled onto the fixed grid.

    Idempotent on a repeated or stale timestamp, the same contract
    `eddy_tracking.update` and `heatwave_tracking.advance` both already keep:
    calling this once per `copernicus_wind.refresh_wind_cache` tick — whether
    or not the underlying product actually published a new timestep since —
    never double-counts a sample.
    """
    # Imported here, not at module load: `upwelling` does not import this
    # module, so this would not be a cycle either way, but keeping the
    # dependency one-directional and explicit matches how
    # `heatwave_tracking.py` avoids importing `heatwaves.py`.
    from services.upwelling import coriolis, ekman_transport, wind_stress

    lat = np.asarray(wind.lat, dtype="float64")
    lon = np.asarray(wind.lon, dtype="float64")
    tau_east, tau_north = wind_stress(np.asarray(wind.u), np.asarray(wind.v))
    f = coriolis(lat)
    m_east, m_north = ekman_transport(tau_east, tau_north, f)

    field_east = xr.DataArray(m_east, dims=("latitude", "longitude"), coords={"latitude": lat, "longitude": lon})
    field_north = xr.DataArray(m_north, dims=("latitude", "longitude"), coords={"latitude": lat, "longitude": lon})
    sampler_east = field_sampling.build_sampler(field_east)
    sampler_north = field_sampling.build_sampler(field_north)

    origin = float(lon[0])
    query_lon = origin + (_GRID_LON - origin) % 360.0
    grid_east = sampler_east(query_lon, _GRID_LAT).astype("float32")
    grid_north = sampler_north(query_lon, _GRID_LAT).astype("float32")

    with _lock:
        if _samples and wind.timestamp <= _samples[-1].timestamp:
            return
        _samples.append(_Sample(timestamp=wind.timestamp, m_east=grid_east, m_north=grid_north))


def trailing_mean(window_days: float) -> MeanTransport | None:
    """The mean transport over the trailing `window_days`, or `None` with no
    reason string — same "degrade the caller rather than raise" contract
    `heatwaves.sst_anomaly_field()` follows, since a caller here is always
    *adding* a claim (a windowed corroboration arm) to something that already
    has an instantaneous answer.
    """
    with _lock:
        if not _samples:
            return None
        newest = _samples[-1].timestamp
        cutoff = newest.timestamp() - window_days * 86400.0
        selected = [s for s in _samples if s.timestamp.timestamp() >= cutoff]

    if len(selected) < 2:
        return None
    oldest = selected[0].timestamp
    span_days = (newest - oldest).total_seconds() / 86400.0
    if span_days < window_days * MIN_COVERAGE_FRACTION:
        return None

    stacked_east = np.stack([s.m_east for s in selected])
    stacked_north = np.stack([s.m_north for s in selected])
    # The equatorial band is NaN in every sample (`upwelling.coriolis` blanks
    # it, since Ekman transport diverges as f -> 0) — an expected all-NaN
    # slice there, not a real "no data" surprise, so the warning is silenced
    # rather than left to look like something went wrong.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean_east = np.nanmean(stacked_east, axis=0).astype("float32")
        mean_north = np.nanmean(stacked_north, axis=0).astype("float32")
    return MeanTransport(
        latitude=_GRID_LAT,
        longitude=_GRID_LON,
        m_east=mean_east,
        m_north=mean_north,
        window_days=window_days,
        samples=len(selected),
        span_days=span_days,
        oldest=oldest,
        newest=newest,
    )
