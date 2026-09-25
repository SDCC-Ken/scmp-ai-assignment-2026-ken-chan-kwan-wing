"""Fixtures for the bell-inbox tests (offline, deterministic).

Seed facts used here (``tests.conftest.SEED_TODAY``): Cathy has leave 1 (Amy, 4 working days)
pending; Helen has leave 2 (Daniel); Eva has claims 2 (Daniel, submitted 2026-09-21) and 1 (Amy,
2026-09-23); Ben has two unread rejection notices (claim 4, then leave 4); Amy and Daniel have no
notifications; Cathy's other two notifications are read.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.session import Database
from app.main import create_app
from app.seed import seed_demo_data
from tests.chat.helpers import TODAY, RecordingAdapter, ScriptedLLM
from tests.conftest import CSRF_HEADERS, SEED_TODAY, login, make_settings

AMY = "amy.lau@example.com"
BEN = "ben.chow@example.com"
CATHY = "cathy.ng@example.com"
DANIEL = "daniel.wong@example.com"
HELEN = "helen.yeung@example.com"
EVA = "eva.cheung@example.com"


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.domain.clock.today_hk", lambda: TODAY)
    monkeypatch.setattr("app.schemas.drafts.today_hk", lambda: TODAY)


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def adapter() -> RecordingAdapter:
    return RecordingAdapter()


@pytest.fixture
def upload_dir(tmp_path: Path) -> Path:
    return tmp_path / "uploads"


@pytest.fixture
def in_app(
    seeded: Database, llm: ScriptedLLM, adapter: RecordingAdapter, upload_dir: Path
) -> FastAPI:
    return create_app(
        make_settings(upload_dir=str(upload_dir)),
        database=seeded,
        llm_provider=llm,
        submission_adapter=adapter,
    )


@pytest.fixture
def client_as(in_app: FastAPI) -> Iterator[Callable[[str | None], TestClient]]:
    """``client_as(email)``: a logged-in browser-like client (``None`` = not signed in)."""
    opened: list[TestClient] = []

    def make(email: str | None) -> TestClient:
        client = TestClient(in_app, headers=CSRF_HEADERS)
        client.__enter__()
        opened.append(client)
        if email:
            login(client, email)
        return client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def amy(client_as: Callable[[str | None], TestClient]) -> TestClient:
    return client_as(AMY)


@pytest.fixture
def ben(client_as: Callable[[str | None], TestClient]) -> TestClient:
    return client_as(BEN)


@pytest.fixture
def cathy(client_as: Callable[[str | None], TestClient]) -> TestClient:
    return client_as(CATHY)


@pytest.fixture
def daniel(client_as: Callable[[str | None], TestClient]) -> TestClient:
    return client_as(DANIEL)


@pytest.fixture
def helen(client_as: Callable[[str | None], TestClient]) -> TestClient:
    return client_as(HELEN)


@pytest.fixture
def eva(client_as: Callable[[str | None], TestClient]) -> TestClient:
    return client_as(EVA)


@pytest.fixture
def anon(client_as: Callable[[str | None], TestClient]) -> TestClient:
    return client_as(None)


@pytest.fixture
def file_db(tmp_path: Path) -> Iterator[Database]:
    """A real file database (two connections can interleave), seeded like the shared one."""
    database = Database(f"sqlite:///{tmp_path / 'inbox.db'}")
    database.init_db()
    with database.session_factory() as s:
        seed_demo_data(s, today=SEED_TODAY)
    yield database
    database.dispose()


def start_inbox(client: TestClient) -> dict[str, Any]:
    """Open the inbox (must have items) and return the 201 body."""
    response = client.post("/api/chat/inbox")
    assert response.status_code == 201, response.text
    return response.json()
