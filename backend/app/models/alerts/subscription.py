"""Proactive alert watches (sihtodo.md item 8).

**`client_id` scopes, a confirmed email and a signed token gate delivery —
two different jobs, not one.** `client_id` follows the same convention
`app/models/chat/session.py` established: a browser-generated UUID, not
access control, used so "my watches" can be listed without a login. But a
watch carries a *delivery target* an email address the row can be made to
send mail to — CLAUDE.md's own note on this (recorded when this feature was
first designed and then dropped, before being rebuilt here) is explicit that
`client_id` alone is not enough for that: creating a watch only opens it
(`confirmed_at IS NULL`), and it never sends an alert until the recipient
proves they control the mailbox by following a signed confirm link
(`services/watch_tokens.py`, independent of `client_id`). The same signed-
token scheme, not `client_id`, gates unsubscribing too — someone reading the
alert email on a different device must be able to stop it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class AlertSubscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_client_id", "client_id"),
        {"schema": "alerts"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # A human label for the point, e.g. "Near Kochi" — not geocoded, just
    # what the subscriber typed, so the alert email can say what it's about.
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # Cyclone watch radius only — severe-weather/bloom checks are polygon/
    # cell membership at the point, not radius-based.
    radius_km: Mapped[float] = mapped_column(Float, nullable=False, default=200.0)

    # NULL until the double opt-in confirm link is followed. Never notified
    # while NULL — see services/watch_alerts.py's own query.
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # A dedup key — the sorted, comma-joined set of currently-active alert
    # ids affecting this point. An email is sent only when this changes, so
    # an ongoing, unchanged alert does not re-notify every evaluation tick.
    # See services/watch_alerts.py::evaluate_and_notify.
    last_alert_signature: Mapped[str | None] = mapped_column(String, nullable=True)
