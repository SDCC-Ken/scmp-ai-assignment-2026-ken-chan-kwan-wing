"""Fixtures for the approver / notification tests (offline, deterministic).

The seed (``tests.conftest.SEED_TODAY``) has these approver-relevant rows:

* leave 1 Amy (IT), pending, assigned to Cathy: 4 working days, overlaps Ben's approved leave;
* leave 2 Daniel (HR), pending, assigned to Helen: over his annual balance (10 approved + 6);
* claim 1 Amy, pending, assigned to Eva: fine; claim 2 Daniel (HR), pending: over HR's limit.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models import Attachment, Conversation
from app.db.session import Database
from app.domain.enums import RequestType
from app.main import create_app
from tests.chat.helpers import TODAY, RecordingAdapter, ScriptedLLM
from tests.conftest import CSRF_HEADERS, get_user, login, make_settings

AMY = "amy.lau@example.com"
BEN = "ben.chow@example.com"
CATHY = "cathy.ng@example.com"
DANIEL = "daniel.wong@example.com"
HELEN = "helen.yeung@example.com"
EVA = "eva.cheung@example.com"

LEAVE = "leave"
CLAIM = "claim"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


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
def ap_app(
    seeded: Database, llm: ScriptedLLM, adapter: RecordingAdapter, upload_dir: Path
) -> FastAPI:
    return create_app(
        make_settings(upload_dir=str(upload_dir)),
        database=seeded,
        llm_provider=llm,
        submission_adapter=adapter,
    )


@pytest.fixture
def client_as(ap_app: FastAPI) -> Iterator[Callable[[str | None], TestClient]]:
    """``client_as(email)``: a logged-in browser-like client (``None`` = not signed in)."""
    opened: list[TestClient] = []

    def make(email: str | None) -> TestClient:
        client = TestClient(ap_app, headers=CSRF_HEADERS)
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


def decide(
    client: TestClient, rtype: str, request_id: int, decision: str, note: Any = "__omit__"
) -> Any:
    body: dict[str, Any] = {"decision": decision}
    if note != "__omit__":
        body["note"] = note
    return client.post(f"/api/approvals/{rtype}/{request_id}/decision", json=body)


def add_attachment(
    db: Database,
    upload_dir: Path,
    owner_email: str,
    rtype: RequestType,
    request_id: int,
    name: str = "receipt.png",
) -> int:
    """A real PNG file on disk plus its row, linked to the request; returns the attachment id."""
    owner = get_user(db, owner_email)
    with db.session_factory() as s:
        conversation = s.query(Conversation).filter(Conversation.user_id == owner.id).first()
        assert conversation is not None
        row = Attachment(
            owner_user_id=owner.id,
            conversation_id=conversation.id,
            request_type=rtype,
            request_id=request_id,
            original_filename=name,
            content_type="image/png",
            size_bytes=len(PNG_BYTES),
            sha256="0" * 64,
            storage_path=f"2026/09/{name}",
        )
        s.add(row)
        s.commit()
        attachment_id = row.id
    target = upload_dir / "2026" / "09" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PNG_BYTES)
    return attachment_id
