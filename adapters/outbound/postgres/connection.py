"""
PostgreSQL / SQLite Connection & Session Management
=====================================================
Phase 1: Uses SQLite (aiosqlite) — zero infrastructure required.
Production: Switch DATABASE_URL to postgresql+asyncpg://...

Never imported by core domain code.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from configs.settings import get_settings
from adapters.outbound.postgres.schema import Base

settings = get_settings()

# SQLite doesn't support connection pool settings
_is_sqlite = settings.database_url.startswith("sqlite")

_engine_kwargs: dict = {
    "echo": settings.database_echo,
}
if not _is_sqlite:
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20

# SQLite needs check_same_thread=False for async
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(settings.database_url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def create_tables() -> None:
    """Create all tables. Called once at application startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():  # type: ignore[return]
    """
    FastAPI dependency that yields a database session per request.
    Rolls back on exception; commits on success.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
