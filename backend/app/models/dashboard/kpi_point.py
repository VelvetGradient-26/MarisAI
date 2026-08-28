"""Persisted samples for `services/dashboard/history.py`'s KPI ring buffer.

The in-process ring buffer (a `dict[str, deque]`) stays the read path — the
dashboard is polled every few minutes and a sparkline read should not cost a
database round trip. This table exists only so a restart does not lose the
last ~24h of every card's trend: `record()` still appends to the in-process
buffer synchronously and, when `DATABASE_URL` is configured, also fires a
background insert here; `hydrate_from_db()` reloads the buffer from these rows
once at boot. See `services/dashboard/history.py` for the full design.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class KpiHistoryPoint(Base):
    __tablename__ = "points"
    __table_args__ = (
        Index("ix_points_key_recorded_at", "key", "recorded_at"),
        {"schema": "dashboard"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # e.g. "sea_surface_temperature" (a KPI card) or "health:copernicus_sst"
    # (health.py's per-provider score) — the same string `series()`/`record()`
    # are already keyed on.
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    # The caller-supplied sample moment, not row-insert time — tests and the
    # backfill/prune logic both need to reason about *when the reading was
    # taken*, which can differ from when the background write lands.
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
