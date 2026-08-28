"""A short rolling history of KPI values, so the cards can show real sparklines.

The KPI sources are all "latest snapshot" products — none of them can answer
"what was the global mean SST six hours ago", and the point time-series APIs
behind `trends.py` are per-location, not global. So a sparkline on a *global*
KPI has no upstream to read from.

Rather than draw a decorative line, this keeps an in-process ring buffer of
the values actually observed while the server has been running. The honest
consequences, which the API reports rather than hides:

  * A freshly started server has no history, so `points` is short or empty and
    the card shows "collecting history" instead of a flat line.
  * History does not survive a restart. It is a display aid, not a record —
    anything durable belongs in a database, and this codebase deliberately
    keeps its registries in-process (see CLAUDE.md).

Samples are throttled so that a dashboard polling every five minutes does not
fill the buffer with near-identical readings from one model timestep.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

# One sample per interval at most. The fastest KPI source refreshes hourly, so
# sampling more often than this records the same number repeatedly.
MIN_SAMPLE_INTERVAL = timedelta(minutes=15)

# ~24 hours at the sample interval above. A sparkline is a few dozen pixels
# wide; more points would be invisible and more memory.
MAX_POINTS = 96

_lock = threading.Lock()
_series: dict[str, deque[tuple[datetime, float]]] = {}
_last_sample: dict[str, datetime] = {}


def record(key: str, value: float | None, *, now: datetime | None = None) -> None:
    """Append a KPI reading, subject to the throttle. Non-numeric values are ignored."""
    if value is None or not isinstance(value, (int, float)):
        return

    moment = now or datetime.now(timezone.utc)
    with _lock:
        previous = _last_sample.get(key)
        if previous is not None and moment - previous < MIN_SAMPLE_INTERVAL:
            return

        bucket = _series.setdefault(key, deque(maxlen=MAX_POINTS))
        bucket.append((moment, float(value)))
        _last_sample[key] = moment


def series(key: str) -> list[dict[str, Any]]:
    """Recorded points for one KPI, oldest first."""
    with _lock:
        bucket = _series.get(key)
        if not bucket:
            return []
        return [{"t": moment.isoformat(), "v": value} for moment, value in bucket]


def trend(key: str) -> dict[str, Any] | None:
    """Change across the recorded window.

    Returns None with fewer than two points — a single reading is a value, not
    a trend, and reporting 0% change from it would be a claim we cannot make.
    """
    with _lock:
        bucket = _series.get(key)
        if not bucket or len(bucket) < 2:
            return None
        first_time, first_value = bucket[0]
        last_time, last_value = bucket[-1]

    change = last_value - first_value
    return {
        "change": round(change, 4),
        "change_pct": round(change / abs(first_value) * 100, 2) if first_value else None,
        "direction": "up" if change > 0 else "down" if change < 0 else "flat",
        "window_start": first_time.isoformat(),
        "window_end": last_time.isoformat(),
        "points": len(bucket),
    }


def reset() -> None:
    """Drop all history. Used by tests."""
    with _lock:
        _series.clear()
        _last_sample.clear()
