"""A short rolling history of KPI values, so the cards can show real sparklines.

The KPI sources are all "latest snapshot" products — none of them can answer
"what was the global mean SST six hours ago", and the point time-series APIs
behind `trends.py` are per-location, not global. So a sparkline on a *global*
KPI has no upstream to read from.

Rather than draw a decorative line, this keeps an in-process ring buffer of
the values actually observed while the server has been running. The honest
consequence the API still reports rather than hides: a freshly started server
that has not yet rehydrated (see below) shows "collecting history" instead of
a flat line.

**Persisted, not just in-process — but the ring buffer stays the read path.**
The dashboard is polled every few minutes (`summary.py`, `health.py`); a
sparkline read should not cost a database round trip on that hot path, so
`series()`/`trend()` are unchanged, plain, synchronous reads of `_series`.
Durability is layered on top, following `app/models/chat/session.py` /
`services/chat/store.py`'s "degrade rather than fail" shape:

  * `record()` still appends to the in-process buffer synchronously exactly as
    before, then — only when `DATABASE_URL` is configured, and only when
    there is a running event loop to schedule onto — fires a background
    insert (`_persist`) into `dashboard.points`. A missing DB, or a plain sync
    caller with no loop (as in this module's own unit tests), just skips the
    write; the in-process behaviour nothing else here depends on is unaffected.
  * `hydrate_from_db()` runs once at boot (see `main.py`'s `lifespan`) and
    reloads `_series`/`_last_sample` from the persisted rows, so a restart
    picks the sparkline up where it left off instead of starting empty.
  * `prune_db()` runs on a schedule (`main.py`) and deletes rows beyond
    `MAX_POINTS` per key — the table is a durability backstop for the same
    bounded window the ring buffer already keeps, not an unbounded audit log.

Samples are throttled so that a dashboard polling every five minutes does not
fill the buffer with near-identical readings from one model timestep.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.models.dashboard import KpiHistoryPoint

logger = logging.getLogger(__name__)

# One sample per interval at most. The fastest KPI source refreshes hourly, so
# sampling more often than this records the same number repeatedly.
MIN_SAMPLE_INTERVAL = timedelta(minutes=15)

# ~24 hours at the sample interval above. A sparkline is a few dozen pixels
# wide; more points would be invisible and more memory (and, now, more rows).
MAX_POINTS = 96

_lock = threading.Lock()
_series: dict[str, deque[tuple[datetime, float]]] = {}
_last_sample: dict[str, datetime] = {}


def enabled() -> bool:
    return bool(settings.DATABASE_URL)


def _session_factory():
    from app.database.session import get_async_session_factory

    return get_async_session_factory()


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

    if not enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (a sync script, or this module's own unit tests) —
        # the in-process buffer above already has the reading; there is just
        # nowhere to schedule the background write onto.
        return
    loop.create_task(_persist(key, float(value), moment))


async def _persist(key: str, value: float, moment: datetime) -> None:
    try:
        async with _session_factory()() as db:
            db.add(KpiHistoryPoint(key=key, value=value, recorded_at=moment))
            await db.commit()
    except SQLAlchemyError:
        logger.exception("could not persist a KPI history point; the in-process buffer still has it")


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
    """Drop all in-process history. Used by tests. Does not touch the database."""
    with _lock:
        _series.clear()
        _last_sample.clear()


async def hydrate_from_db() -> None:
    """Reload `_series`/`_last_sample` from persisted rows. Call once at boot.

    Only fills keys the in-process buffer does not already have data for —
    on a real boot that is every key, but this keeps a second accidental call
    (or a call racing an early `record()`) from clobbering fresher in-process
    readings with older persisted ones.
    """
    if not enabled():
        return
    try:
        async with _session_factory()() as db:
            rows = (
                await db.execute(
                    select(KpiHistoryPoint.key, KpiHistoryPoint.value, KpiHistoryPoint.recorded_at)
                    .order_by(KpiHistoryPoint.key, KpiHistoryPoint.recorded_at)
                )
            ).all()
    except SQLAlchemyError:
        logger.exception("could not hydrate KPI history from the database; starting empty")
        return

    with _lock:
        # Snapshotted once, before the loop below starts populating `_series`
        # itself — checking the live dict mid-loop would treat this hydrate
        # call's own first row for a key as "already has data" and skip every
        # row after it for that same key.
        already_had_data = set(_series.keys())
        for key, value, moment in rows:
            if key in already_had_data:
                continue  # already has in-process data — do not overwrite it
            bucket = _series.setdefault(key, deque(maxlen=MAX_POINTS))
            bucket.append((moment, value))
        for key, bucket in _series.items():
            if bucket:
                _last_sample[key] = bucket[-1][0]


async def prune_db() -> None:
    """Delete persisted rows beyond `MAX_POINTS` per key.

    The table is a durability backstop for the same bounded window the
    in-process ring buffer already keeps, not an unbounded log — without this
    it grows forever at one row per key per `MIN_SAMPLE_INTERVAL`.
    """
    if not enabled():
        return
    try:
        async with _session_factory()() as db:
            ranked = (
                select(
                    KpiHistoryPoint.id,
                    func.row_number()
                    .over(
                        partition_by=KpiHistoryPoint.key,
                        order_by=KpiHistoryPoint.recorded_at.desc(),
                    )
                    .label("rn"),
                )
            ).subquery()
            stale_ids = select(ranked.c.id).where(ranked.c.rn > MAX_POINTS)
            await db.execute(delete(KpiHistoryPoint).where(KpiHistoryPoint.id.in_(stale_ids)))
            await db.commit()
    except SQLAlchemyError:
        logger.exception("could not prune KPI history")
