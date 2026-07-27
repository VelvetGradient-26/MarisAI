from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

# Lazy initialization to avoid issues with config loading
_engine = None
_async_engine = None
_SessionLocal = None
_AsyncSessionLocal = None


def _get_sync_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return database_url


def _get_async_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql+"):
        scheme, rest = database_url.split("://", 1)
        return f"postgresql+asyncpg://{rest}"
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    return database_url


def _get_engine():
    global _engine
    if _engine is None:
        from app.core.config import settings
        _engine = create_engine(
            _get_sync_database_url(settings.DATABASE_URL),
            echo=True,
            future=True,
        )
    return _engine


def _get_async_engine():
    global _async_engine
    if _async_engine is None:
        from app.core.config import settings
        _async_engine = create_async_engine(
            _get_async_database_url(settings.DATABASE_URL),
            echo=True,
            future=True,
        )
    return _async_engine


def _get_session_local():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=_get_engine(),
            autoflush=False,
            autocommit=False,
        )
    return _SessionLocal


def _get_async_session_local():
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            bind=_get_async_engine(),
            class_=AsyncSession,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _AsyncSessionLocal


def get_db():
    db = _get_session_local()()
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    async with _get_async_session_local()() as session:
        yield session


def get_async_session_factory():
    return _get_async_session_local()
