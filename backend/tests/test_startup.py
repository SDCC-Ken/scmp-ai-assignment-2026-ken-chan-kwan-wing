import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.tokens import resolve_jwt_secret
from app.db.models import User
from app.db.session import Database
from app.main import create_app, startup_database
from tests.conftest import make_settings


def user_count(db: Database) -> int:
    with db.session_factory() as s:
        return s.scalar(select(func.count(User.id))) or 0


def test_lifespan_creates_tables_and_seeds_when_enabled() -> None:
    db = Database("sqlite:///:memory:")
    app = create_app(make_settings(db_auto_seed=True), database=db)
    with TestClient(app) as client:
        assert user_count(db) == 6
        assert len(client.get("/api/auth/mock-users").json()) == 6


def test_lifespan_does_not_seed_when_disabled() -> None:
    db = Database("sqlite:///:memory:")
    with TestClient(create_app(make_settings(db_auto_seed=False), database=db)):
        assert user_count(db) == 0


def test_auto_seed_skips_when_users_exist(seeded: Database) -> None:
    before = user_count(seeded)
    startup_database(seeded, make_settings(db_auto_seed=True))
    assert user_count(seeded) == before


def test_seed_failure_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("seed exploded")

    monkeypatch.setattr("app.main.seed_demo_data", boom)
    db = Database("sqlite:///:memory:")
    with caplog.at_level(logging.ERROR):
        with TestClient(create_app(make_settings(db_auto_seed=True), database=db)) as client:
            assert client.get("/health").status_code == 200
    assert "seeding failed" in caplog.text


def test_db_init_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    class BrokenDb(Database):
        def init_db(self) -> None:
            raise RuntimeError("disk full")

    with caplog.at_level(logging.ERROR):
        with TestClient(create_app(make_settings(), database=BrokenDb("sqlite:///:memory:"))) as c:
            assert c.get("/health").status_code == 200
    assert "initialisation failed" in caplog.text


def test_empty_secret_outside_production_generates_random_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = make_settings(jwt_secret_key="", app_env="development")
    with caplog.at_level(logging.WARNING):
        first, second = resolve_jwt_secret(settings), resolve_jwt_secret(settings)
    assert len(first) >= 32 and first != second
    assert "JWT_SECRET_KEY is empty" in caplog.text
    assert first not in caplog.text and second not in caplog.text


def test_production_requires_strong_secret() -> None:
    for secret in ("", "short-secret"):
        with pytest.raises(RuntimeError, match="32"):
            create_app(
                make_settings(app_env="production", jwt_secret_key=secret),
                database=Database("sqlite:///:memory:"),
            )
    strong = "s" * 32
    app = create_app(
        make_settings(app_env="production", jwt_secret_key=strong),
        database=Database("sqlite:///:memory:"),
    )
    assert app.state.jwt_secret == strong


def test_configured_secret_is_used_in_development() -> None:
    assert resolve_jwt_secret(make_settings(jwt_secret_key="dev-secret")) == "dev-secret"
