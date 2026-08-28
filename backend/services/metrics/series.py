"""Point history for any forecastable variable, ready to plot.

Thin over `forecasting.history`, which already handles the hard parts: it
resolves a variable through the download registry, clamps the window to what
the provider actually covers, retries and times out per provider, and caches
the result. This module adds the two things a chart needs and a model does
not — a regular time axis, and a point count a browser can draw.

**Decimation is min/max paired, not stride sampling.** Taking every Nth point
of a 100k-point series drops the extremes, so a marine heatwave spike that
lasted three days can vanish entirely from a ten-year view. That is a silent
falsification of the record, and this platform's rule is that a missing value
is better than a wrong one. Pairing the minimum and maximum of each bucket
preserves the visual envelope exactly: the rendered line still touches every
peak and trough, at a fraction of the points.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from forecasting.config import get_config
from forecasting.history import HistoryRequest, fetch
from forecasting.preprocessing import TIMESTAMP, clean
from forecasting.registry import resolve
from services.download.models import Resolution
from services.metrics import MetricsError

logger = logging.getLogger(__name__)

# What the frontend may ask for. Beyond this a browser is drawing more points
# than it has pixels, and the payload costs more than the detail is worth.
MAX_POINTS_LIMIT = 20_000
DEFAULT_MAX_POINTS = 4_000

# Named windows the UI offers. Kept here rather than in the router so the
# catalog endpoint and the series endpoint cannot disagree about what "1y"
# means.
RANGES: dict[str, int] = {
    "24h": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "6mo": 182,
    "1y": 365,
    "5y": 1826,
    "10y": 3652,
}


@dataclass(frozen=True)
class MetricSeries:
    """A plottable series plus the provenance the UI has to display."""

    variable: str
    label: str
    unit: str
    latitude: float
    longitude: float
    resolution: str
    start: date
    end: date
    points: list[dict[str, Any]]
    # Rows the provider actually returned, before decimation. The UI says
    # "12,483 observations, drawn as 4,000" rather than implying the chart is
    # the whole record.
    observation_count: int
    decimated: bool
    coverage_start: date | None
    sources: list[str]
    quality: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "variable": self.variable,
            "label": self.label,
            "unit": self.unit,
            "latitude": round(self.latitude, 4),
            "longitude": round(self.longitude, 4),
            "resolution": self.resolution,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "points": self.points,
            "observation_count": self.observation_count,
            "rendered_count": len(self.points),
            "decimated": self.decimated,
            "coverage_start": self.coverage_start.isoformat() if self.coverage_start else None,
            "sources": self.sources,
            "quality": self.quality,
        }


def decimate(frame: pd.DataFrame, column: str, max_points: int) -> pd.DataFrame:
    """Reduce to at most `max_points` rows while keeping every extreme.

    Buckets the series into `max_points / 2` equal spans and keeps the minimum
    and maximum of each, in their original time order. The result draws as the
    same envelope: peaks and troughs survive, only the redundant points along
    a smooth stretch are dropped.

    Returned in timestamp order, because uPlot requires a monotonically
    increasing x series and will render nothing at all if given one that
    jumps backwards.
    """
    if len(frame) <= max_points or max_points < 4:
        return frame

    bucket_count = max_points // 2
    # `searchsorted`-style bucketing on position rather than time: the frame is
    # already regularised onto an even axis by `clean`, so positional buckets
    # are time buckets, and this avoids a groupby over a datetime index.
    edges = np.linspace(0, len(frame), bucket_count + 1).astype(int)
    values = frame[column].to_numpy(dtype="float64")

    keep: list[int] = []
    for start, stop in zip(edges[:-1], edges[1:], strict=True):
        if stop <= start:
            continue
        window = values[start:stop]
        finite = np.isfinite(window)
        if not finite.any():
            # An all-NaN bucket still has to contribute a point, or a genuine
            # gap in the record would close up and the chart would imply
            # continuous coverage across it.
            keep.append(start)
            continue
        offsets = np.flatnonzero(finite)
        low = offsets[np.argmin(window[offsets])]
        high = offsets[np.argmax(window[offsets])]
        keep.extend({start + int(low), start + int(high)})

    return frame.iloc[sorted(set(keep))]


def _resolve_window(range_key: str | None, days: int | None) -> int:
    if days is not None:
        if days < 1:
            raise MetricsError("days must be at least 1")
        return min(days, RANGES["10y"])
    if range_key is None:
        return RANGES["1y"]
    window = RANGES.get(range_key)
    if window is None:
        raise MetricsError(
            f"Unknown range {range_key!r}. Expected one of: {', '.join(RANGES)}"
        )
    return window


async def load_frame(
    variable_key: str,
    latitude: float,
    longitude: float,
    *,
    range_key: str | None = None,
    days: int | None = None,
) -> tuple[pd.DataFrame, Any, dict[str, Any]]:
    """Fetch and clean the raw series. Shared by `build` and `statistics.py`.

    Returns the cleaned frame, the variable's config entry, and the quality
    report, so a caller computing statistics does not have to re-fetch what a
    caller drawing a chart already has (both hit the same history cache
    anyway, but this avoids the redundant clean).
    """
    config = get_config()
    variable = resolve(variable_key, config)

    window_days = _resolve_window(range_key, days)
    resolution = Resolution(config.training_for(variable_key).resolution)

    end = datetime.now(UTC).date()
    series = await fetch(
        HistoryRequest(
            codes=(variable.code,),
            latitude=latitude,
            longitude=longitude,
            start_date=end - timedelta(days=window_days),
            end_date=end,
            resolution=resolution,
        )
    )

    frame, quality = clean(
        series.frame,
        [variable.code],
        resolution=resolution,
        outliers=config.outliers_for(variable_key),
    )
    return frame, variable, {"quality": quality.as_dict(), "series": series}


async def build(
    variable_key: str,
    latitude: float,
    longitude: float,
    *,
    range_key: str | None = None,
    days: int | None = None,
    max_points: int = DEFAULT_MAX_POINTS,
) -> MetricSeries:
    """A decimated, plottable history for one variable at one point."""
    max_points = max(4, min(max_points, MAX_POINTS_LIMIT))

    frame, variable, extra = await load_frame(
        variable_key, latitude, longitude, range_key=range_key, days=days
    )
    history = extra["series"]

    observation_count = int(frame[variable.code].notna().sum())
    if observation_count == 0:
        raise MetricsError(
            f"No {variable.label} observations at {latitude:.3f}, {longitude:.3f} "
            f"in the requested window."
        )

    reduced = decimate(frame, variable.code, max_points)

    # Epoch seconds, not ISO strings: uPlot takes a numeric x axis, and a
    # 20k-point payload of ISO timestamps is roughly four times the bytes for
    # data the client would immediately parse back to numbers anyway.
    stamps = reduced[TIMESTAMP].astype("int64").to_numpy() // 10**9
    values = reduced[variable.code].to_numpy(dtype="float64")

    points = [
        {"t": int(stamp), "v": round(float(value), 4)}
        for stamp, value in zip(stamps, values, strict=True)
        if np.isfinite(value)
    ]

    return MetricSeries(
        variable=variable_key,
        label=variable.label,
        unit=variable.unit,
        latitude=history.latitude,
        longitude=history.longitude,
        resolution=history.resolution.value,
        start=pd.Timestamp(frame[TIMESTAMP].min()).date(),
        end=pd.Timestamp(frame[TIMESTAMP].max()).date(),
        points=points,
        observation_count=observation_count,
        decimated=len(reduced) < len(frame),
        coverage_start=history.coverage.get(variable.code),
        sources=history.sources,
        quality=extra["quality"],
    )
