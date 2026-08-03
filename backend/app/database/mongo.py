"""MongoDB Atlas connection.

This is the only database the app actually connects to. The SQLAlchemy schema
next door in `session.py` / `app/models/` is real and migrated but unqueried —
identity and per-user state live here instead, because the free Atlas tier
needs no server to babysit.

Lazily initialized like `session.py`, so importing this module never opens a
socket and the app still boots with no MONGODB_URI configured (auth routes then
fail with a clean 503 rather than the process dying at import).
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

USERS = "users"
SAVED_LOCATIONS = "saved_locations"
DOWNLOAD_HISTORY = "download_history"

_client: AsyncMongoClient | None = None


class MongoUnavailableError(RuntimeError):
    """Mongo isn't configured or can't be reached — surfaced as a 503, never
    as a raw pymongo traceback."""


def _get_client() -> AsyncMongoClient:
    global _client
    if _client is None:
        from app.core.config import settings

        if not settings.MONGODB_URI:
            raise MongoUnavailableError(
                "MONGODB_URI is not configured — set it in backend/.env"
            )
        _client = AsyncMongoClient(
            settings.MONGODB_URI,
            # Atlas M0 (free tier) caps the cluster at 500 connections. A
            # single API process needs nowhere near that, and an unbounded
            # pool is the classic way to exhaust it.
            maxPoolSize=10,
            serverSelectionTimeoutMS=5000,
            tz_aware=True,
        )
    return _client


def get_database() -> AsyncDatabase:
    from app.core.config import settings

    return _get_client()[settings.MONGODB_DB_NAME]


async def get_mongo_db() -> AsyncDatabase:
    """FastAPI dependency. The client pools connections internally, so this
    hands back the same database handle rather than opening anything."""
    return get_database()


async def ensure_indexes() -> None:
    """Called once at startup. `create_index` is idempotent, so this is safe
    to re-run on every boot."""
    db = get_database()

    # googleSub is Google's stable per-user subject claim — the real identity
    # key. Unique so a race between two concurrent first-time sign-ins can't
    # produce two accounts for one person.
    await db[USERS].create_index([("googleSub", ASCENDING)], unique=True)
    await db[USERS].create_index([("email", ASCENDING)])

    # Both per-user lists are always read newest-first for one userId.
    await db[SAVED_LOCATIONS].create_index([("userId", ASCENDING), ("createdAt", DESCENDING)])
    await db[DOWNLOAD_HISTORY].create_index([("userId", ASCENDING), ("requestedAt", DESCENDING)])


async def close_mongo() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
