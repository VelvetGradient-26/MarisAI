"""Skip database-backed tests when Postgres is configured but not running.

The guard these tests used (`store.enabled()`) only asks whether
DATABASE_URL is *set*. A developer whose backend/.env points at a local
Postgres that is not currently up got a wall of "connection refused"
failures instead of skips. This asks whether the server actually answers.
"""

from __future__ import annotations

import socket
from functools import lru_cache
from urllib.parse import urlsplit

import pytest

from app.core.config import settings


@lru_cache(maxsize=1)
def database_reachable() -> bool:
    if not settings.DATABASE_URL:
        return False
    parts = urlsplit(settings.DATABASE_URL.replace("+psycopg2", "").replace("+asyncpg", ""))
    try:
        with socket.create_connection((parts.hostname or "localhost", parts.port or 5432), timeout=2):
            return True
    except OSError:
        return False


requires_database = pytest.mark.skipif(
    not database_reachable(), reason="DATABASE_URL not set, or Postgres is not reachable"
)
