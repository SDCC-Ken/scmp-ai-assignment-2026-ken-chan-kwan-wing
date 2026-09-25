# ruff: noqa: E501
"""Additive schema sync (app.db.migrate) on a pre-Phase-2 file, and how the API treats an old file.

``sync_schema`` still adds missing nullable columns (used for later additive changes), but since
Phase 3 ``init_db`` refuses to touch a database without ``schema_version`` 3 (see
tests/org/test_schema_version.py); the sync tests below therefore call it directly.
"""

import logging
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, MetaData, String, Table, inspect, text

from app.db.base import Base
from app.db.migrate import sync_schema
from app.db.models import ClaimRequest, Conversation, LeaveRequest
from app.db.session import Database, create_db_engine
from app.main import create_app
from tests.chat.helpers import ScriptedLLM
from tests.conftest import CSRF_HEADERS, make_settings

# The schema as it was BEFORE Phase 2 (only the tables Phase 2 changes, plus `users`, which they
# reference). CHECK constraints are left out; the point is which COLUMNS exist.
OLD_DDL = [
    """CREATE TABLE users (
        id INTEGER NOT NULL, google_subject VARCHAR(128) NOT NULL, email VARCHAR(254) NOT NULL,
        display_name VARCHAR(120) NOT NULL, role VARCHAR(16) NOT NULL,
        is_active BOOLEAN DEFAULT '1' NOT NULL, created_at DATETIME NOT NULL,
        CONSTRAINT pk_users PRIMARY KEY (id),
        CONSTRAINT uq_users_google_subject UNIQUE (google_subject),
        CONSTRAINT uq_users_email UNIQUE (email))""",
    """CREATE TABLE conversations (
        id INTEGER NOT NULL, user_id INTEGER NOT NULL, status VARCHAR(6) NOT NULL,
        active_request_type VARCHAR(5), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        CONSTRAINT pk_conversations PRIMARY KEY (id),
        CONSTRAINT fk_conversations_user_id_users FOREIGN KEY(user_id) REFERENCES users (id))""",
    "CREATE INDEX ix_conversations_user_id ON conversations (user_id)",
    """CREATE TABLE conversation_messages (
        id INTEGER NOT NULL, conversation_id INTEGER NOT NULL, sender_type VARCHAR(9) NOT NULL,
        content TEXT NOT NULL, ui_metadata_json JSON, created_at DATETIME NOT NULL,
        CONSTRAINT pk_conversation_messages PRIMARY KEY (id),
        CONSTRAINT fk_conversation_messages_conversation_id_conversations
            FOREIGN KEY(conversation_id) REFERENCES conversations (id))""",
    "CREATE INDEX ix_conversation_messages_conversation_id ON conversation_messages (conversation_id)",
    """CREATE TABLE leave_requests (
        id INTEGER NOT NULL, employee_id INTEGER NOT NULL, leave_type VARCHAR(8) NOT NULL,
        start_date DATE NOT NULL, end_date DATE NOT NULL, start_day_part VARCHAR(4) NOT NULL,
        end_day_part VARCHAR(4) NOT NULL, calendar_days BIGINT NOT NULL, working_days BIGINT NOT NULL,
        status VARCHAR(17) NOT NULL, required_approver_role VARCHAR(16) NOT NULL,
        submitted_at DATETIME, reviewed_by_user_id INTEGER, reviewed_at DATETIME,
        reviewer_note TEXT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        CONSTRAINT pk_leave_requests PRIMARY KEY (id),
        CONSTRAINT fk_leave_requests_employee_id_users FOREIGN KEY(employee_id) REFERENCES users (id))""",
    "CREATE INDEX ix_leave_requests_employee_id_status ON leave_requests (employee_id, status)",
    """CREATE TABLE claim_requests (
        id INTEGER NOT NULL, employee_id INTEGER NOT NULL, claim_type VARCHAR(9) NOT NULL,
        amount BIGINT NOT NULL, currency VARCHAR(3) DEFAULT 'HKD' NOT NULL, receipt_date DATE NOT NULL,
        status VARCHAR(17) NOT NULL, required_approver_role VARCHAR(16) NOT NULL,
        submitted_at DATETIME, reviewed_by_user_id INTEGER, reviewed_at DATETIME,
        reviewer_note TEXT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        CONSTRAINT pk_claim_requests PRIMARY KEY (id),
        CONSTRAINT fk_claim_requests_employee_id_users FOREIGN KEY(employee_id) REFERENCES users (id))""",
    "CREATE INDEX ix_claim_requests_employee_id_status ON claim_requests (employee_id, status)",
    """CREATE TABLE external_submissions (
        id INTEGER NOT NULL, request_type VARCHAR(5) NOT NULL, request_id INTEGER NOT NULL,
        provider VARCHAR(32) NOT NULL, status VARCHAR(7) NOT NULL, http_status INTEGER,
        external_reference_id VARCHAR(128), response_summary_json JSON NOT NULL, error_message TEXT,
        submitted_at DATETIME NOT NULL, CONSTRAINT pk_external_submissions PRIMARY KEY (id))""",
    "CREATE INDEX ix_external_submissions_request ON external_submissions (request_type, request_id)",
]
OLD_ROWS = [
    "INSERT INTO users VALUES (1, 'old-sub-1', 'old.user@example.com', 'Old User', 'employee', 1, '2026-01-05 02:00:00')",
    "INSERT INTO conversations VALUES (1, 1, 'active', 'leave', '2026-09-01 03:00:00', '2026-09-01 03:05:00')",
    """INSERT INTO conversation_messages VALUES
        (1, 1, 'user', 'I want annual leave in October', NULL, '2026-09-01 03:00:00'),
        (2, 1, 'assistant', 'Which dates?', '{"type": "follow_up", "missing_fields": ["start_date"]}', '2026-09-01 03:00:05')""",
    """INSERT INTO leave_requests VALUES (1, 1, 'annual', '2026-10-05', '2026-10-07', 'full', 'full',
        30, 30, 'pending_approval', 'hr_approver', '2026-09-01 03:10:00', NULL, NULL, NULL,
        '2026-09-01 03:09:00', '2026-09-01 03:10:00')""",
    """INSERT INTO claim_requests VALUES (1, 1, 'travel', 12050, 'HKD', '2026-08-30',
        'pending_approval', 'finance_approver', '2026-09-01 03:12:00', NULL, NULL, NULL,
        '2026-09-01 03:11:00', '2026-09-01 03:12:00')""",
    """INSERT INTO external_submissions VALUES (1, 'leave', 1, 'reqres', 'success', 201, '55',
        '{"id": "55"}', NULL, '2026-09-01 03:10:00')""",
]
NEW_COLUMNS = {
    "conversations": "state_json",
    "leave_requests": "conversation_id",
    "claim_requests": "conversation_id",
    "external_submissions": "request_payload_json",
}


def make_old_database(path: Path) -> str:
    url = f"sqlite:///{path}"
    engine = create_db_engine(url)
    with engine.begin() as conn:
        for statement in [*OLD_DDL, *OLD_ROWS]:
            conn.execute(text(statement))
    engine.dispose()
    return url


def sync_old_database(engine) -> None:  # type: ignore[no-untyped-def]
    """What init_db does for a current-version file: create missing tables, add columns."""
    Base.metadata.create_all(engine)
    sync_schema(engine)


def columns(engine, table: str) -> set[str]:  # type: ignore[no-untyped-def]
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_old_database_gains_the_new_columns_and_keeps_its_rows(tmp_path: Path) -> None:
    """MG-01"""
    url = make_old_database(tmp_path / "old.db")
    engine = create_db_engine(url)
    for table, column in NEW_COLUMNS.items():
        assert column not in columns(engine, table)

    sync_old_database(engine)  # create_all (new tables) + sync_schema (new columns)

    for table, column in NEW_COLUMNS.items():
        assert column in columns(engine, table)
    index_names = {
        ix["name"]
        for t in ("leave_requests", "claim_requests")
        for ix in inspect(engine).get_indexes(t)
    }
    assert {"ix_leave_requests_conversation_id", "ix_claim_requests_conversation_id"} <= index_names
    with engine.connect() as conn:
        assert conn.execute(text("SELECT email FROM users")).scalars().all() == [
            "old.user@example.com"
        ]
        assert conn.execute(
            text("SELECT content FROM conversation_messages ORDER BY id")
        ).scalars().all() == [
            "I want annual leave in October",
            "Which dates?",
        ]
        leave = conn.execute(
            text("SELECT working_days, status, conversation_id FROM leave_requests")
        ).one()
        assert tuple(leave) == (30, "pending_approval", None)
        claim = conn.execute(text("SELECT amount, conversation_id FROM claim_requests")).one()
        assert tuple(claim) == (12050, None)
        sub = conn.execute(
            text("SELECT external_reference_id, request_payload_json FROM external_submissions")
        ).one()
        assert tuple(sub) == ("55", None)
        assert conn.execute(text("SELECT state_json FROM conversations")).scalar() is None
        # the new nullable FK column really references conversations
        fks = conn.execute(text("PRAGMA foreign_key_list(leave_requests)")).all()
        assert any(row[2] == "conversations" and row[3] == "conversation_id" for row in fks)
    engine.dispose()


def test_orm_reads_old_rows_after_the_sync(tmp_path: Path) -> None:
    """MG-02"""
    db = Database(make_old_database(tmp_path / "old.db"))
    sync_old_database(db.engine)
    with db.session_factory() as s:
        leave = s.get(LeaveRequest, 1)
        assert leave is not None and leave.conversation_id is None
        assert leave.working_days == Decimal("3.0")
        assert s.get(ClaimRequest, 1).conversation_id is None
        assert s.get(Conversation, 1).state_json is None
    db.dispose()


def test_sync_is_idempotent_and_reports_what_it_did(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """MG-03"""
    engine = create_db_engine(make_old_database(tmp_path / "old.db"))
    Base.metadata.create_all(engine)  # what init_db does first
    with caplog.at_level(logging.INFO, logger="app.db.migrate"):
        first = sync_schema(engine)
    added = set(first.added_columns)
    assert {f"{t}.{c}" for t, c in NEW_COLUMNS.items()} <= added  # the Phase 2 columns
    assert {"leave_requests.approver_user_id", "users.department_id"} <= added  # and Phase 3's
    assert first.refused == [] and first.changed
    assert "added column leave_requests.conversation_id" in caplog.text
    second = sync_schema(engine)
    assert not second.changed and second.refused == []
    engine.dispose()


def test_fresh_database_needs_no_changes() -> None:
    """MG-04"""
    db = Database("sqlite:///:memory:")
    db.init_db()
    assert not sync_schema(db.engine).changed
    db.dispose()


def test_non_additive_changes_are_refused_with_a_clear_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """MG-05: NOT NULL without a default and UNIQUE columns cannot be added safely."""
    engine = create_db_engine(f"sqlite:///{tmp_path}/widgets.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name VARCHAR(20))"))
        conn.execute(text("INSERT INTO widgets (name) VALUES ('kept')"))
    metadata = MetaData()
    Table(
        "widgets",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(20)),
        Column("note", String(20), nullable=True),  # additive
        Column("colour", String(20), nullable=False, server_default="red"),  # additive (default)
        Column("required", String(20), nullable=False),  # refused
        Column("code", String(20), nullable=True, unique=True),  # refused
    )
    with caplog.at_level(logging.ERROR, logger="app.db.migrate"):
        report = sync_schema(engine, metadata)
    assert sorted(report.added_columns) == ["widgets.colour", "widgets.note"]
    assert len(report.refused) == 2
    assert "widgets.required" in caplog.text and "NOT NULL without a server default" in caplog.text
    assert "widgets.code" in caplog.text and "unique" in caplog.text
    assert columns(engine, "widgets") == {"id", "name", "note", "colour"}
    with engine.connect() as conn:
        assert tuple(conn.execute(text("SELECT name, colour FROM widgets")).one()) == (
            "kept",
            "red",
        )
    engine.dispose()


def test_sync_never_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """MG-06"""

    def broken(_engine):  # type: ignore[no-untyped-def]
        raise RuntimeError("inspector exploded")

    monkeypatch.setattr("app.db.migrate.inspect", broken)
    db = Database("sqlite:///:memory:")
    with caplog.at_level(logging.ERROR, logger="app.db.migrate"):
        report = sync_schema(db.engine)
    assert not report.changed and "Schema sync failed unexpectedly" in caplog.text
    db.dispose()


def test_an_existing_pre_phase_3_database_boots_but_is_left_alone_with_a_clear_503(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """MG-07: an older file is neither crashed on nor modified: one clear ERROR at start-up and a
    503 with the same instruction from every endpoint that needs the database."""
    url = make_old_database(tmp_path / "boot.db")
    engine = create_db_engine(url)
    tables_before = set(inspect(engine).get_table_names())
    user_columns_before = columns(engine, "users")
    engine.dispose()

    db = Database(url)
    app = create_app(
        make_settings(database_url=url, db_auto_seed=True), database=db, llm_provider=ScriptedLLM()
    )
    with caplog.at_level(logging.ERROR, logger="app.db.session"):
        with TestClient(app, headers=CSRF_HEADERS) as client:
            assert client.get("/health").status_code == 200
            for response in (
                client.get("/api/auth/mock-users"),
                client.post("/api/auth/mock-google/login", json={"email": "old.user@example.com"}),
            ):
                assert response.status_code == 503
                detail = response.json()["detail"]
                assert "created before Phase 3" in detail
                assert "docker compose down -v" in detail and "seed --reset --yes" in detail
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "created before Phase 3" in errors[0].getMessage()

    engine = create_db_engine(url)
    assert set(inspect(engine).get_table_names()) == tables_before  # nothing was created
    assert columns(engine, "users") == user_columns_before  # nor altered
    with engine.connect() as conn:  # and the old rows are all still there
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM leave_requests")).scalar() == 1
    engine.dispose()
