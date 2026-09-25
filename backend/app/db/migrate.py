"""Additive schema sync for existing SQLite files (no Alembic in this PoC).

``Base.metadata.create_all`` only creates *missing tables*. A Docker volume that already holds a
database from an earlier phase would therefore never receive columns added later, and the API
would fail on the first query that names them. ``sync_schema`` runs right after ``create_all``
and, for tables that already exist, adds what the models declare but the file lacks:

* columns: only when SQLite can add them safely, i.e. NULLABLE (or with a server default) and
  neither primary key nor unique. ``ALTER TABLE ... ADD COLUMN`` keeps every existing row.
* indexes: non-unique or unique indexes declared on the models whose columns all exist.

This runs only for a database that already carries the current ``schema_version`` (see
``app.db.session.init_db``). A database created before Phase 3 is never passed here: Phase 3
removed a CHECK constraint and added organisation tables/FK columns, which SQLite cannot do in
place, so that database is left untouched and reported with a "recreate it" instruction instead
of being half-migrated.

Anything that cannot be done additively (a NOT NULL column without a default, a new unique
column, a changed type, a dropped column) is *refused*: a clear error is logged and the rest of
the sync carries on. Nothing here ever raises into application start-up.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import Column, Engine, MetaData, Table, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateIndex

from app.db.base import Base

logger = logging.getLogger(__name__)


@dataclass
class SyncReport:
    added_columns: list[str] = field(default_factory=list)  # "table.column"
    added_indexes: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)  # human-readable reasons

    @property
    def changed(self) -> bool:
        return bool(self.added_columns or self.added_indexes)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _refusal_reason(column: Column) -> str | None:
    """Why ``column`` cannot be added with ``ALTER TABLE ADD COLUMN`` (None = it can)."""
    if column.primary_key:
        return "it is a primary key"
    if column.unique:
        return "it is unique"
    if not column.nullable and column.server_default is None:
        return "it is NOT NULL without a server default (existing rows would violate it)"
    return None


def _column_ddl(engine: Engine, table: Table, column: Column) -> str:
    parts = [
        f"ALTER TABLE {_quote(table.name)} ADD COLUMN {_quote(column.name)}",
        column.type.compile(dialect=engine.dialect),
    ]
    if column.server_default is not None:
        default_text = getattr(column.server_default.arg, "text", column.server_default.arg)
        parts.append(f"DEFAULT {default_text}")
    if not column.nullable:
        parts.append("NOT NULL")
    for fk in column.foreign_keys:
        target = fk.column
        parts.append(f"REFERENCES {_quote(target.table.name)} ({_quote(target.name)})")
    return " ".join(parts)


def sync_schema(engine: Engine, metadata: MetaData | None = None) -> SyncReport:
    """Add missing nullable columns and indexes to existing tables; never raises.

    ``metadata`` defaults to the application's models (a parameter only so tests can use their
    own tables).
    """
    report = SyncReport()
    try:
        inspector = inspect(engine)
        for table in (metadata or Base.metadata).sorted_tables:
            if not inspector.has_table(table.name):
                continue  # create_all makes new tables with everything on them
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                label = f"{table.name}.{column.name}"
                reason = _refusal_reason(column)
                if reason is not None:
                    message = f"Cannot add column {label} additively: {reason}"
                    logger.error("Schema sync refused: %s", message)
                    report.refused.append(message)
                    continue
                try:
                    with engine.begin() as conn:
                        conn.execute(text(_column_ddl(engine, table, column)))
                except SQLAlchemyError:
                    message = f"Adding column {label} failed"
                    logger.exception("Schema sync failed: %s", message)
                    report.refused.append(message)
                    continue
                existing.add(column.name)
                report.added_columns.append(label)
                logger.info("Schema sync: added column %s", label)

            present_indexes = {ix["name"] for ix in inspect(engine).get_indexes(table.name)}
            for index in sorted(table.indexes, key=lambda i: i.name or ""):
                if index.name in present_indexes:
                    continue
                if not all(c.name in existing for c in index.columns):
                    continue  # its column was refused above
                try:
                    with engine.begin() as conn:
                        conn.execute(CreateIndex(index))
                except SQLAlchemyError:
                    message = f"Adding index {index.name} failed"
                    logger.exception("Schema sync failed: %s", message)
                    report.refused.append(message)
                    continue
                report.added_indexes.append(str(index.name))
                logger.info("Schema sync: added index %s", index.name)
    except Exception:  # never let a schema-sync bug stop the API from starting
        logger.exception("Schema sync failed unexpectedly; continuing without it")
    return report
