"""Persisted chat sessions.

**This is the first feature in the codebase to actually use the database.**
`app/models/core` and `app/models/observations` are migrated but unread; the
convention everywhere else is an in-code registry, and CLAUDE.md says to adopt
the schema only when a feature genuinely needs persistence. A conversation that
must survive a page reload is that case — there is nowhere else for it to live.

**On `client_id`, and what it is not.** Authentication was removed from this
codebase, so there are no users to own a session. `client_id` is a UUID the
browser generates and keeps in localStorage. It scopes a person's own history
on their own machine; it is **not** access control. Anyone who learns a
client_id could read those conversations. That is an accepted limit of a
no-auth deployment, not an oversight — if sign-in returns, this column is what
becomes a real foreign key to a user.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class ChatSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        # Every listing is "this browser's sessions, newest first", so the
        # index carries the sort column rather than leaving it to a sort node.
        Index("ix_sessions_client_id_updated_at", "client_id", "updated_at"),
        {"schema": "chat"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Derived from the opening question rather than asked for, so a session is
    # identifiable in a list without the user naming it.
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="New chat")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.seq",
    )


class ChatMessage(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_session_id_seq", "session_id", "seq"),
        {"schema": "chat"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Ordering is by `seq`, never by `created_at`, and that is load-bearing.
    # `created_at` defaults to `now()`, which in Postgres is *transaction start
    # time* — so a question and its answer, written in one transaction, carry
    # an identical timestamp. Ordering on it returned the assistant's reply
    # before the question that prompted it, which then went into the prompt
    # that way. An identity column is monotonic per insert and cannot tie.
    seq: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), nullable=False, unique=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat.sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Provenance, stored so a reopened conversation still shows which data
    # calls produced which answer. Without this a reloaded session would render
    # bare paragraphs and quietly lose the property the feature is built on.
    observations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    sources: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    unsupported_numbers: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session = relationship("ChatSession", back_populates="messages")
