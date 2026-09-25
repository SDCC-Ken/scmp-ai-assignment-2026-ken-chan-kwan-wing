"""schema_version: a fresh database is stamped, a pre-Phase-3 file is detected and left alone."""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.db.session import (
    SCHEMA_RESET_MESSAGE,
    SCHEMA_VERSION,
    Database,
    create_db_engine,
    init_db,
    schema_problem,
    stored_schema_version,
)
from app.main import create_app
from tests.conftest import CSRF_HEADERS, make_settings
from tests.test_migrate import make_old_database


def test_the_message_tells_the_operator_what_to_do() -> None:
    assert SCHEMA_RESET_MESSAGE == (
        "This database was created before Phase 3. Recreate it: docker compose down -v, "
        "or python -m app.cli seed --reset --yes"
    )
    assert SCHEMA_VERSION == 3


def test_a_fresh_database_boots_and_is_stamped(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'new.db'}")
    assert schema_problem(engine) is None  # an empty file is fine
    assert init_db(engine) is None
    assert stored_schema_version(engine) == SCHEMA_VERSION
    assert init_db(engine) is None  # running it again changes nothing
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT key, value FROM schema_meta")).all()
    assert [tuple(r) for r in rows] == [("schema_version", str(SCHEMA_VERSION))]
    engine.dispose()


def test_database_object_reports_no_error_for_a_fresh_file(db: Database) -> None:
    assert db.schema_error is None and db.init_db() is None


def test_an_old_database_is_detected_logged_once_and_left_untouched(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine = create_db_engine(make_old_database(tmp_path / "old.db"))
    tables_before = set(inspect(engine).get_table_names())
    assert stored_schema_version(engine) is None
    assert schema_problem(engine) == SCHEMA_RESET_MESSAGE

    with caplog.at_level(logging.ERROR, logger="app.db.session"):
        assert init_db(engine) == SCHEMA_RESET_MESSAGE
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert [r.getMessage() for r in errors] == [SCHEMA_RESET_MESSAGE]

    assert set(inspect(engine).get_table_names()) == tables_before  # no table was created
    assert "department_id" not in {c["name"] for c in inspect(engine).get_columns("users")}
    assert "approver_user_id" not in {
        c["name"] for c in inspect(engine).get_columns("leave_requests")
    }
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM leave_requests")).scalar() == 1
    engine.dispose()


def test_a_lower_recorded_version_is_also_refused(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'v2.db'}")
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'"))
    assert stored_schema_version(engine) == 2
    assert schema_problem(engine) == SCHEMA_RESET_MESSAGE
    assert init_db(engine) == SCHEMA_RESET_MESSAGE
    engine.dispose()


def test_a_newer_recorded_version_is_not_refused(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'v9.db'}")
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE schema_meta SET value = '9' WHERE key = 'schema_version'"))
    assert schema_problem(engine) is None
    engine.dispose()


def test_database_remembers_the_error_after_init(tmp_path: Path) -> None:
    db = Database(make_old_database(tmp_path / "old.db"))
    assert db.init_db() == SCHEMA_RESET_MESSAGE
    assert db.schema_error == SCHEMA_RESET_MESSAGE
    db.dispose()


def test_the_api_boots_on_an_old_database_and_answers_503_with_the_instruction(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    url = make_old_database(tmp_path / "boot.db")
    app = create_app(make_settings(database_url=url, db_auto_seed=True), database=Database(url))
    with caplog.at_level(logging.ERROR):
        with TestClient(app, headers=CSRF_HEADERS) as client:
            assert client.get("/health").status_code == 200  # the API itself is up
            for response in (
                client.get("/api/auth/mock-users"),
                client.get("/api/auth/me"),
                client.get("/api/me/balances"),
                client.get("/api/chat/conversations"),
            ):
                assert response.status_code == 503, response.text
                assert response.json() == {"detail": SCHEMA_RESET_MESSAGE}
    assert "seeding failed" not in caplog.text  # auto-seed is skipped, not attempted


def test_a_fresh_database_boots_normally_through_the_api() -> None:
    db = Database("sqlite:///:memory:")
    with TestClient(create_app(make_settings(db_auto_seed=True), database=db)) as client:
        assert client.get("/api/auth/mock-users").status_code == 200
    assert db.schema_error is None


def test_reset_repairs_an_old_database(tmp_path: Path) -> None:
    """The documented remedy: ``seed --reset --yes`` recreates it at the current version."""
    from app import cli

    url = make_old_database(tmp_path / "fix.db")
    assert cli.main(["seed", "--reset", "--yes"], database=Database(url)) == 0
    engine = create_db_engine(url)
    assert stored_schema_version(engine) == SCHEMA_VERSION
    assert schema_problem(engine) is None
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 6
    engine.dispose()
