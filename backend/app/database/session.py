"""Async engine + session factory with pooling, health checks and graceful shutdown."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.logging import get_logger
from app.database.base import Base

logger = get_logger("database")


class DatabaseUnavailableError(RuntimeError):
    """The database could not be reached (or the pool is exhausted). Mapped to HTTP 503."""


class Database:
    def __init__(self, url: str, *, pool_size: int = 10, max_overflow: int = 5, pool_timeout: float = 10, echo: bool = False) -> None:
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        kwargs: dict[str, object] = {"echo": echo, "pool_pre_ping": not self.is_sqlite}
        if self.is_sqlite:
            memory = url.rstrip("/").endswith(":memory:") or url in ("sqlite+aiosqlite://", "sqlite+aiosqlite:///")
            if memory:
                kwargs["poolclass"] = StaticPool  # one shared in-memory database per engine
            else:
                path = url.split(":///", 1)[-1]
                if path and not path.startswith(":"):
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        else:
            kwargs.update(pool_size=pool_size, max_overflow=max_overflow, pool_timeout=pool_timeout, pool_recycle=1800)
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        if self.is_sqlite:
            @event.listens_for(self.engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001, ANN202
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.healthy = True
        self._write_lock = asyncio.Lock() if self.is_sqlite else None  # SQLite allows one writer at a time

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """A transaction: committed on success, rolled back on error. Connectivity errors -> DatabaseUnavailableError."""
        try:
            if self._write_lock is not None:
                async with self._write_lock:
                    async with self.sessionmaker() as s, s.begin():
                        yield s
            else:
                async with self.sessionmaker() as s, s.begin():
                    yield s
            self.healthy = True
        except (OSError, asyncio.TimeoutError) as exc:
            self.healthy = False
            raise DatabaseUnavailableError("The database is unavailable.") from exc
        except SQLAlchemyError as exc:
            if _is_connectivity(exc):
                self.healthy = False
                raise DatabaseUnavailableError("The database is unavailable.") from exc
            raise

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def ping(self, timeout: float = 3.0) -> bool:
        try:
            async with asyncio.timeout(timeout):
                async with self.engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            self.healthy = True
            return True
        except Exception:  # noqa: BLE001
            self.healthy = False
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()


def _is_connectivity(exc: SQLAlchemyError) -> bool:
    from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, TimeoutError as PoolTimeout

    if isinstance(exc, (PoolTimeout, InterfaceError)):
        return True
    if isinstance(exc, (OperationalError, DBAPIError)) and getattr(exc, "connection_invalidated", False):
        return True
    text_ = str(exc).lower()
    return isinstance(exc, OperationalError) and any(k in text_ for k in ("connect", "closed", "timeout", "refused"))
