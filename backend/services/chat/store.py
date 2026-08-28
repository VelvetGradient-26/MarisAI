"""Persistence for chat sessions.

**Degrades rather than fails.** `DATABASE_URL` is optional everywhere else in
this codebase — nothing else reads the database at all — so a deployment
without one must still be able to hold a conversation. Every function here
returns `None`/empty when persistence is unavailable, and `agent.answer` falls
back to the client-supplied history. The chat works either way; only the
"reopen a previous chat" half needs a database.

That is also why failures are logged and swallowed rather than raised. A
Postgres hiccup should cost the transcript, not the answer the user asked for.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.models.chat import ChatMessage, ChatSession

logger = logging.getLogger(__name__)

# Messages (not turns — a turn is two rows) replayed into the prompt when a
# session is resumed. The window lives here rather than at the API edge because
# the transcript is now the authority: the browser no longer decides what the
# model remembers.
HISTORY_MESSAGES = 20

# How much of the opening question becomes the session's title.
_TITLE_LENGTH = 80


def enabled() -> bool:
    return bool(settings.DATABASE_URL)


def _session_factory():
    from app.database.session import get_async_session_factory

    return get_async_session_factory()


def title_from(question: str) -> str:
    text = " ".join(question.split())
    if len(text) <= _TITLE_LENGTH:
        return text or "New chat"
    return text[: _TITLE_LENGTH - 1].rstrip() + "…"


async def ensure_session(
    session_id: str | None, client_id: str, question: str
) -> uuid.UUID | None:
    """Resolve an existing session or open a new one.

    A `session_id` that does not belong to this `client_id` is treated as
    absent and a fresh session is opened, rather than raising. Guessing another
    browser's id should not be a way to append to its transcript, and a 403
    here would only tell the guesser they had guessed right.
    """
    if not enabled():
        return None

    try:
        async with _session_factory()() as db:
            if session_id:
                try:
                    candidate = uuid.UUID(session_id)
                except ValueError:
                    candidate = None
                if candidate is not None:
                    found = await db.scalar(
                        select(ChatSession.id).where(
                            ChatSession.id == candidate,
                            ChatSession.client_id == client_id,
                        )
                    )
                    if found is not None:
                        return found

            created = ChatSession(client_id=client_id, title=title_from(question))
            db.add(created)
            await db.commit()
            return created.id
    except SQLAlchemyError:
        logger.exception("could not open a chat session; continuing without persistence")
        return None


async def history(session_id: uuid.UUID | None) -> list[dict[str, str]]:
    """The stored transcript, oldest-first, bounded to the replay window."""
    if not enabled() or session_id is None:
        return []
    try:
        async with _session_factory()() as db:
            rows = (
                await db.execute(
                    select(ChatMessage.role, ChatMessage.content)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.seq.desc())
                    .limit(HISTORY_MESSAGES)
                )
            ).all()
        return [{"role": role, "content": content} for role, content in reversed(rows)]
    except SQLAlchemyError:
        logger.exception("could not read chat history; continuing without it")
        return []


async def record(
    session_id: uuid.UUID | None,
    question: str,
    reply: dict[str, Any],
) -> None:
    """Append the question and its answer, and bump the session's timestamp."""
    if not enabled() or session_id is None:
        return
    try:
        async with _session_factory()() as db:
            db.add(
                ChatMessage(session_id=session_id, role="user", content=question)
            )
            db.add(
                ChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content=reply.get("answer", ""),
                    observations=reply.get("observations"),
                    sources=reply.get("sources"),
                    grounded=reply.get("grounded"),
                    unsupported_numbers=reply.get("unsupported_numbers"),
                )
            )
            # Ordering in the sidebar is by recency of use, not of creation.
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id == session_id)
                .values(updated_at=func.now())
            )
            await db.commit()
    except SQLAlchemyError:
        logger.exception("could not persist the chat turn; the answer still stands")


async def list_sessions(client_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if not enabled():
        return []
    try:
        async with _session_factory()() as db:
            rows = (
                await db.execute(
                    select(ChatSession)
                    .where(ChatSession.client_id == client_id)
                    .order_by(ChatSession.updated_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        return [
            {
                "id": str(row.id),
                "title": row.title,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]
    except SQLAlchemyError:
        logger.exception("could not list chat sessions")
        return []


async def transcript(session_id: str, client_id: str) -> list[dict[str, Any]] | None:
    """Full stored messages for one session, or None if it is not this client's."""
    if not enabled():
        return None
    try:
        candidate = uuid.UUID(session_id)
    except ValueError:
        return None
    try:
        async with _session_factory()() as db:
            owned = await db.scalar(
                select(ChatSession.id).where(
                    ChatSession.id == candidate, ChatSession.client_id == client_id
                )
            )
            if owned is None:
                return None
            rows = (
                await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == candidate)
                    .order_by(ChatMessage.seq)
                )
            ).scalars().all()
        return [
            {
                "role": row.role,
                "content": row.content,
                "observations": row.observations or [],
                "sources": row.sources or [],
                "grounded": row.grounded if row.grounded is not None else True,
                "unsupported_numbers": row.unsupported_numbers or [],
            }
            for row in rows
        ]
    except SQLAlchemyError:
        logger.exception("could not read chat transcript")
        return None


async def remove(session_id: str, client_id: str) -> bool:
    if not enabled():
        return False
    try:
        candidate = uuid.UUID(session_id)
    except ValueError:
        return False
    try:
        async with _session_factory()() as db:
            result = await db.execute(
                delete(ChatSession).where(
                    ChatSession.id == candidate, ChatSession.client_id == client_id
                )
            )
            await db.commit()
            return bool(result.rowcount)
    except SQLAlchemyError:
        logger.exception("could not delete chat session")
        return False
