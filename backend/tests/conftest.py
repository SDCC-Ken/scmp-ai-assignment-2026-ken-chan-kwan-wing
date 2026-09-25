"""Shared fixtures. Everything is offline; Settings never read the real repo .env."""

import os
import tempfile
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

# app.main builds a module-level ``app`` (and caches get_settings) at import time. Pin the
# environment first so importing it never depends on the developer's real ../.env.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DB_AUTO_SEED"] = "false"
os.environ["JWT_SECRET_KEY"] = "import-time-test-secret-" + "i" * 32
# A test that resets the demo data must never touch a real ./data/uploads folder.
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="scmp-test-uploads-")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import User
from app.db.session import Database, get_db
from app.main import create_app
from app.seed import seed_demo_data

SEED_TODAY = date(2026, 9, 25)
TEST_SECRET = "unit-test-secret-" + "k" * 48
COOKIE_NAME = "scmp_session"
ORIGIN = "http://localhost:9180"
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "sqlite:///:memory:",
        "jwt_secret_key": TEST_SECRET,
        "db_auto_seed": False,
        "cors_origins": ["http://localhost:9180"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def db() -> Iterator[Database]:
    database = Database("sqlite:///:memory:")
    database.init_db()
    yield database
    database.dispose()


@pytest.fixture
def session(db: Database) -> Iterator[Session]:
    with db.session_factory() as s:
        yield s


@pytest.fixture
def seeded(db: Database) -> Database:
    with db.session_factory() as s:
        seed_demo_data(s, today=SEED_TODAY)
    return db


@pytest.fixture
def seeded_session(seeded: Database) -> Iterator[Session]:
    with seeded.session_factory() as s:
        yield s


@pytest.fixture
def app_factory(seeded: Database) -> Callable[..., FastAPI]:
    def factory(**setting_overrides: Any) -> FastAPI:
        app = create_app(make_settings(**setting_overrides), database=seeded)

        def override_get_db() -> Iterator[Session]:
            with seeded.session_factory() as s:
                yield s

        app.dependency_overrides[get_db] = override_get_db
        return app

    return factory


@pytest.fixture
def app(app_factory: Callable[..., FastAPI]) -> FastAPI:
    return app_factory()


@pytest.fixture
def raw_client(app: FastAPI) -> Iterator[TestClient]:
    """Cookie-jar client that sends no CSRF header (use it to test the CSRF defence)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Like a browser SPA: keeps cookies and sends ``X-Requested-With`` on every request."""
    with TestClient(app, headers=CSRF_HEADERS) as c:
        yield c


def login(client: TestClient, email: str) -> str:
    """Log in (the session cookie lands in the client's jar) and return the JWT from the jar.

    The token is never in the body; tests read it from the cookie only to forge/tamper.
    """
    response = client.post(
        "/api/auth/mock-google/login", json={"email": email}, headers=CSRF_HEADERS
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(COOKIE_NAME)
    assert token
    return token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_user(db: Database, email: str) -> User:
    with db.session_factory() as s:
        user = s.query(User).filter(User.email == email).one()
        s.expunge(user)
        return user
