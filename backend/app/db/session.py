"""Engine factory, SQLite safety pragmas, ``init_db`` and the ``get_db`` dependency."""

import logging
from collections.abc import Iterator
from functools import cached_property
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base

logger = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 5000


def _is_memory(database: str | None) -> bool:
    return database in (None, "", ":memory:") or bool(
        database and database.startswith("file::memory:")
    )


def _set_sqlite_pragmas(dbapi_connection: Any, in_memory: bool) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA synchronous=NORMAL")
        if not in_memory:
            cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def create_db_engine(url: str) -> Engine:
    """Create a SQLite engine with safety pragmas applied on every connection."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        raise ValueError("Only SQLite database URLs are supported")
    in_memory = _is_memory(parsed.database)
    kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
    if in_memory:
        kwargs["poolclass"] = StaticPool  # one shared connection so :memory: survives sessions
    else:
        Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        _set_sqlite_pragmas(dbapi_connection, in_memory)

    return engine


def init_db(engine: Engine) -> None:
    """Create all tables that do not exist yet (no migrations in this PoC)."""
    from app.db import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    from app.db import models  # noqa: F401

    Base.metadata.drop_all(engine)


class Database:
    """Lazy holder for the engine and session factory (nothing touches disk until used)."""

    def __init__(self, url: str) -> None:
        self.url = url

    @cached_property
    def engine(self) -> Engine:
        return create_db_engine(self.url)

    @cached_property
    def session_factory(self) -> sessionmaker[Session]:
        return sessionmaker(self.engine, expire_on_commit=False)

    def init_db(self) -> None:
        init_db(self.engine)

    def dispose(self) -> None:
        if "engine" in self.__dict__:
            self.engine.dispose()


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    database: Database = request.app.state.database
    session = database.session_factory()
    try:
        yield session
    finally:
        session.close()
