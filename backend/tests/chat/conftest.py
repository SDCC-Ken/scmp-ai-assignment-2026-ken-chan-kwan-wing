"""Fixtures for the chat tests: frozen Hong Kong date, scripted LLM, recording adapter."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.session import Database
from app.main import create_app
from tests.chat.helpers import TODAY, Chat, RecordingAdapter, ScriptedLLM
from tests.conftest import CSRF_HEADERS, login, make_settings

CATHY = "cathy.ng@example.com"  # employee with NO editable requests in the seed
AMY = "amy.lau@example.com"  # employee with pending seed requests (used as "someone else")
BEN = "ben.chow@example.com"
HR = "helen.yeung@example.com"  # the HR approver of Cathy and Daniel
FINANCE = "eva.cheung@example.com"


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze Hong Kong "today" (the chat service and ``ClaimDraft`` both read it)."""
    monkeypatch.setattr("app.domain.clock.today_hk", lambda: TODAY)
    monkeypatch.setattr("app.schemas.drafts.today_hk", lambda: TODAY)


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def adapter() -> RecordingAdapter:
    return RecordingAdapter()


@pytest.fixture
def chat_app(seeded: Database, llm: ScriptedLLM, adapter: RecordingAdapter) -> FastAPI:
    return create_app(
        make_settings(), database=seeded, llm_provider=llm, submission_adapter=adapter
    )


def _client(app: FastAPI, email: str) -> Iterator[TestClient]:
    with TestClient(app, headers=CSRF_HEADERS) as client:
        login(client, email)
        yield client


@pytest.fixture
def cathy(chat_app: FastAPI) -> Iterator[TestClient]:
    yield from _client(chat_app, CATHY)


@pytest.fixture
def amy(chat_app: FastAPI) -> Iterator[TestClient]:
    yield from _client(chat_app, AMY)


@pytest.fixture
def ben(chat_app: FastAPI) -> Iterator[TestClient]:
    yield from _client(chat_app, BEN)


@pytest.fixture
def hr(chat_app: FastAPI) -> Iterator[TestClient]:
    yield from _client(chat_app, HR)


@pytest.fixture
def finance(chat_app: FastAPI) -> Iterator[TestClient]:
    yield from _client(chat_app, FINANCE)


@pytest.fixture
def chat(cathy: TestClient) -> Chat:
    return Chat(cathy)


@pytest.fixture
def amy_chat(amy: TestClient) -> Chat:
    return Chat(amy)


@pytest.fixture
def ben_chat(ben: TestClient) -> Chat:
    return Chat(ben)
