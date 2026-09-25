"""Engine factory, SQLite safety pragmas, ``init_db`` and the ``get_db`` dependency."""

import logging
from collections.abc import Iterator
from functools import cached_property
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import Engine, create_engine, event, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base

logger = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 5000

# Bump when a change cannot be applied additively (see app.db.migrate). Phase 3 = 3: it removed
# the "reject needs a note" CHECK and added the organisation tables, which SQLite cannot do in
# place, so a database created earlier must be recreated.
SCHEMA_VERSION = 3
SCHEMA_VERSION_KEY = "schema_version"
SCHEMA_RESET_MESSAGE = (
    "This database was created before Phase 3. Recreate it: docker compose down -v, "
    "or python -m app.cli seed --reset --yes"
)


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


def stored_schema_version(engine: Engine) -> int | None:
    """The ``schema_version`` stored in the database, or None when missing / unreadable."""
    if not inspect(engine).has_table("schema_meta"):
        return None
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT value FROM schema_meta WHERE key = :key"), {"key": SCHEMA_VERSION_KEY}
        ).scalar()
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def schema_problem(engine: Engine) -> str | None:
    """Why this existing database cannot be used as is (None = fine or brand new).

    An empty file is fine. A database that already has the application's tables but a lower or
    missing ``schema_version`` predates Phase 3 and needs to be recreated.
    """
    tables = set(inspect(engine).get_table_names())
    if not tables:
        return None
    version = stored_schema_version(engine)
    if version is None and "users" not in tables:
        return None  # not one of ours (nothing to protect); create_all just adds our tables
    if version is None or version < SCHEMA_VERSION:
        return SCHEMA_RESET_MESSAGE
    return None


def _stamp_schema_version(engine: Engine) -> None:
    from app.db.models import SchemaMeta

    with Session(engine) as session:
        row = session.scalar(select(SchemaMeta).where(SchemaMeta.key == SCHEMA_VERSION_KEY))
        if row is None:
            session.add(SchemaMeta(key=SCHEMA_VERSION_KEY, value=str(SCHEMA_VERSION)))
        elif row.value != str(SCHEMA_VERSION):
            row.value = str(SCHEMA_VERSION)
        session.commit()


def init_db(engine: Engine) -> str | None:
    """Create missing tables, then add missing nullable columns/indexes to existing ones.

    Returns None on success. A database from before Phase 3 is NOT touched: the reason (an
    instruction for the operator) is logged as one clear ERROR and returned, and the caller
    keeps running so the API can still boot and explain (503). There is no Alembic in this PoC:
    ``sync_schema`` only keeps a current-version database working when a later change is purely
    additive. See ``app.db.migrate``.
    """
    from app.db import models  # noqa: F401  (register models on Base.metadata)
    from app.db.migrate import sync_schema

    problem = schema_problem(engine)
    if problem is not None:
        logger.error(problem)
        return problem
    Base.metadata.create_all(engine)
    sync_schema(engine)
    _stamp_schema_version(engine)
    return None


def drop_all(engine: Engine) -> None:
    from app.db import models  # noqa: F401

    Base.metadata.drop_all(engine)


class Database:
    """Lazy holder for the engine and session factory (nothing touches disk until used)."""

    def __init__(self, url: str) -> None:
        self.url = url
        # Set by init_db(): why the file cannot be used (an operator instruction) or None.
        self.schema_error: str | None = None

    @cached_property
    def engine(self) -> Engine:
        return create_db_engine(self.url)

    @cached_property
    def session_factory(self) -> sessionmaker[Session]:
        return sessionmaker(self.engine, expire_on_commit=False)

    def init_db(self) -> str | None:
        self.schema_error = init_db(self.engine)
        return self.schema_error

    def dispose(self) -> None:
        if "engine" in self.__dict__:
            self.engine.dispose()


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    database: Database = request.app.state.database
    if database.schema_error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=database.schema_error
        )
    session = database.session_factory()
    try:
        yield session
    finally:
        session.close()
