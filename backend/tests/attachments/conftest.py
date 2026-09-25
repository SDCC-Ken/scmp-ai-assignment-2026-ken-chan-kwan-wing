"""Fixtures for the attachment tests: temporary UPLOAD_DIR, scripted LLM, several users."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.session import Database
from app.main import create_app
from tests.chat.helpers import TODAY, Chat, RecordingAdapter, ScriptedLLM
from tests.conftest import CSRF_HEADERS, login, make_settings

CATHY = "cathy.ng@example.com"
AMY = "amy.lau@example.com"
HR = "helen.yeung@example.com"  # the HR approver of Cathy and Daniel
FINANCE = "eva.cheung@example.com"


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.domain.clock.today_hk", lambda: TODAY)
    monkeypatch.setattr("app.schemas.drafts.today_hk", lambda: TODAY)


@pytest.fixture
def upload_dir(tmp_path: Path) -> Path:
    return tmp_path / "uploads"


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def adapter() -> RecordingAdapter:
    return RecordingAdapter()


@pytest.fixture
def att_app(
    seeded: Database, llm: ScriptedLLM, adapter: RecordingAdapter, upload_dir: Path
) -> FastAPI:
    return create_app(
        make_settings(upload_dir=str(upload_dir)),
        database=seeded,
        llm_provider=llm,
        submission_adapter=adapter,
    )


def _client(app: FastAPI, email: str | None) -> Iterator[TestClient]:
    with TestClient(app, headers=CSRF_HEADERS) as client:
        if email:
            login(client, email)
        yield client


@pytest.fixture
def cathy(att_app: FastAPI) -> Iterator[TestClient]:
    yield from _client(att_app, CATHY)


@pytest.fixture
def amy(att_app: FastAPI) -> Iterator[TestClient]:
    yield from _client(att_app, AMY)


@pytest.fixture
def hr(att_app: FastAPI) -> Iterator[TestClient]:
    yield from _client(att_app, HR)


@pytest.fixture
def finance(att_app: FastAPI) -> Iterator[TestClient]:
    yield from _client(att_app, FINANCE)


@pytest.fixture
def anon(att_app: FastAPI) -> Iterator[TestClient]:
    yield from _client(att_app, None)


@pytest.fixture
def chat(cathy: TestClient) -> Chat:
    return Chat(cathy)


@pytest.fixture
def amy_chat(amy: TestClient) -> Chat:
    return Chat(amy)
