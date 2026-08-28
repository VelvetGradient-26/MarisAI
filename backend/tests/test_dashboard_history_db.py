"""KPI ring buffer persistence.

Runs against the real Postgres in `DATABASE_URL` and skips when there isn't
one — same convention as `test_chat_store.py`, and for the same reason: the
history module is written to degrade rather than fail without a database, so
a developer with no Postgres must still get a green suite. Every test cleans
up the rows it writes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from services.dashboard import history

pytestmark = pytest.mark.skipif(
    not history.enabled(), reason="DATABASE_URL is not configured"
)


@pytest.fixture(autouse=True)
async def fresh_engine():
    """Same fix test_chat_store.py's own fixture documents: asyncpg binds a
    connection to the event loop that opened it, and pytest-asyncio gives each
    test its own loop."""
    history.reset()
    yield
    history.reset()

    from app.database import session as db_session

    if db_session._async_engine is not None:
        await db_session._async_engine.dispose()
        db_session._async_engine = None
        db_session._AsyncSessionLocal = None


@pytest.fixture
def key() -> str:
    return f"test:{uuid.uuid4().hex}"


async def _cleanup(test_key: str) -> None:
    from app.models.dashboard import KpiHistoryPoint

    async with history._session_factory()() as db:
        await db.execute(delete(KpiHistoryPoint).where(KpiHistoryPoint.key == test_key))
        await db.commit()


@pytest.mark.asyncio
async def test_record_persists_in_the_background(key):
    """`record()` is sync, but with a running loop and a configured database it
    still schedules a real write — this is the property the whole feature is
    for: the KPI history is not just held in this process's memory."""
    now = datetime.now(timezone.utc)
    history.record(key, 1.0, now=now)
    # `record()` only *schedules* the write via `loop.create_task`; give it a
    # tick to actually run before checking the database.
    await _drain()

    try:
        from app.models.dashboard import KpiHistoryPoint

        async with history._session_factory()() as db:
            rows = (
                await db.execute(
                    select(KpiHistoryPoint.value).where(KpiHistoryPoint.key == key)
                )
            ).scalars().all()
        assert rows == [1.0]
    finally:
        await _cleanup(key)


@pytest.mark.asyncio
async def test_hydrate_from_db_reloads_after_a_simulated_restart(key):
    """The actual point of this feature: a fresh process (simulated here by
    `history.reset()`, which clears only the in-process buffer) picks the
    sparkline back up from the database rather than starting empty."""
    now = datetime.now(timezone.utc)
    history.record(key, 10.0, now=now)
    history.record(key, 12.0, now=now + history.MIN_SAMPLE_INTERVAL)
    await _drain()

    try:
        history.reset()  # simulates a restart: in-process buffer is gone
        assert history.series(key) == []

        await history.hydrate_from_db()

        points = history.series(key)
        assert [p["v"] for p in points] == [10.0, 12.0]
    finally:
        await _cleanup(key)


@pytest.mark.asyncio
async def test_hydrate_from_db_does_not_clobber_fresher_in_process_data(key):
    """A key the in-process buffer already has data for is left alone — this
    is what keeps a hydrate call racing an early `record()` from overwriting
    it with an older persisted reading."""
    try:
        # Also persists in the background (a running loop and DATABASE_URL
        # are both present here) — cleaned up below regardless.
        history.record(key, 99.0)

        await history.hydrate_from_db()

        assert [p["v"] for p in history.series(key)] == [99.0]
    finally:
        await _drain()
        await _cleanup(key)


@pytest.mark.asyncio
async def test_prune_db_keeps_only_the_newest_max_points(key):
    """Without this the table grows one row per key per sample forever —
    it exists to keep the persisted table the same bounded window the
    in-process ring buffer already enforces, not an unbounded log."""
    from app.models.dashboard import KpiHistoryPoint

    start = datetime.now(timezone.utc)
    extra = 10
    async with history._session_factory()() as db:
        for index in range(history.MAX_POINTS + extra):
            db.add(
                KpiHistoryPoint(
                    key=key,
                    value=float(index),
                    recorded_at=start + timedelta(minutes=index),
                )
            )
        await db.commit()

    try:
        await history.prune_db()

        async with history._session_factory()() as db:
            rows = (
                await db.execute(
                    select(KpiHistoryPoint.value)
                    .where(KpiHistoryPoint.key == key)
                    .order_by(KpiHistoryPoint.recorded_at)
                )
            ).scalars().all()
        assert len(rows) == history.MAX_POINTS
        # The oldest `extra` rows are the ones pruned, not the newest.
        assert rows[0] == float(extra)
        assert rows[-1] == float(history.MAX_POINTS + extra - 1)
    finally:
        await _cleanup(key)


async def _drain() -> None:
    """Give the event loop enough real time to run a `loop.create_task(...)`
    scheduled by a sync caller — it does a real asyncpg round trip, so a bare
    `asyncio.sleep(0)` is not reliably enough to let it finish."""
    import asyncio

    await asyncio.sleep(0.2)
