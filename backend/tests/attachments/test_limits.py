"""Size limit (5 MB), streaming (an oversized body is not read to the end) and staging limit."""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Attachment
from app.db.session import Database
from tests.attachments.helpers import MB, PDF, PNG, asgi_upload, multipart_body, padded, upload
from tests.chat.helpers import Chat
from tests.conftest import COOKIE_NAME

LIMIT = 5 * MB


def attachment_count(db: Database) -> int:
    with db.session_factory() as s:
        return s.scalar(select(func.count()).select_from(Attachment)) or 0


def leftovers(upload_dir: Path) -> list[Path]:
    return [p for p in upload_dir.rglob("*") if p.is_file()] if upload_dir.exists() else []


def test_exactly_the_limit_is_accepted(cathy: TestClient, chat: Chat) -> None:
    data = padded(PNG, LIMIT)
    response = upload(cathy, chat.id, data)
    assert response.status_code == 201, response.text
    assert response.json()["attachment"]["size_bytes"] == LIMIT


def test_one_byte_over_the_limit_is_413_and_nothing_is_kept(
    cathy: TestClient, chat: Chat, seeded: Database, upload_dir: Path
) -> None:
    response = upload(cathy, chat.id, padded(PNG, LIMIT + 1))
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]
    assert attachment_count(seeded) == 0
    assert leftovers(upload_dir) == []


def test_limit_follows_the_setting(att_app: FastAPI, chat: Chat, cathy: TestClient) -> None:
    att_app.state.settings.max_upload_mb = 1
    assert upload(cathy, chat.id, padded(PNG, MB)).status_code == 201
    assert upload(cathy, chat.id, padded(PNG, MB + 1)).status_code == 413


def test_oversized_chunked_body_is_not_read_to_the_end(
    att_app: FastAPI, cathy: TestClient, chat: Chat, upload_dir: Path
) -> None:
    piece = 64 * 1024
    head, _, tail = multipart_body(b"")
    body = padded(PNG, 10 * MB)
    chunks = [head] + [body[i : i + piece] for i in range(0, len(body), piece)] + [tail]
    result = asgi_upload(att_app, chat.id, cathy.cookies.get(COOKIE_NAME), chunks)
    assert result.status == 413
    # stops right after the 5 MB mark (80 chunks of 64 KiB) instead of reading all 10 MB
    assert result.consumed <= LIMIT // piece + 4, (result.consumed, len(chunks))
    assert leftovers(upload_dir) == []


def test_declared_huge_content_length_is_refused_without_reading_the_body(
    att_app: FastAPI, cathy: TestClient, chat: Chat
) -> None:
    head, _, _ = multipart_body(b"")
    result = asgi_upload(
        att_app, chat.id, cathy.cookies.get(COOKIE_NAME), [head], content_length=50 * MB
    )
    assert result.status == 413
    assert result.consumed == 0


def test_wrong_signature_stops_the_upload_early(
    att_app: FastAPI, cathy: TestClient, chat: Chat, upload_dir: Path
) -> None:
    piece = 64 * 1024
    head, _, tail = multipart_body(b"", filename="x.png")
    body = b"<html>" + b"a" * (4 * MB)
    chunks = [head] + [body[i : i + piece] for i in range(0, len(body), piece)] + [tail]
    result = asgi_upload(att_app, chat.id, cathy.cookies.get(COOKIE_NAME), chunks)
    assert result.status == 415
    assert result.consumed < 5  # refused after the first kilobyte, not after 4 MB
    assert leftovers(upload_dir) == []


def test_chunked_streaming_in_tiny_pieces_stores_the_exact_bytes(
    att_app: FastAPI, cathy: TestClient, chat: Chat, upload_dir: Path
) -> None:
    payload = padded(PDF, 300_000)
    head, _, tail = multipart_body(b"", filename="sick note.pdf", content_type="application/pdf")
    stream = head + payload + tail
    chunks = [stream[i : i + 7] for i in range(0, len(stream), 7)]  # splits every boundary
    result = asgi_upload(att_app, chat.id, cathy.cookies.get(COOKIE_NAME), chunks)
    assert result.status == 201, result.body
    (stored,) = leftovers(upload_dir)
    assert stored.read_bytes() == payload
    detail = cathy.get(f"/api/chat/conversations/{chat.id}").json()
    assert detail["messages"] == []  # staged only
    info = json.loads(result.body)["attachment"]
    assert info["filename"] == "sick note.pdf"
    assert info["size_bytes"] == len(payload)


def test_eleventh_staged_upload_is_422(
    cathy: TestClient, chat: Chat, seeded: Database, upload_dir: Path
) -> None:
    for _ in range(10):
        assert upload(cathy, chat.id, PNG).status_code == 201
    response = upload(cathy, chat.id, PNG)
    assert response.status_code == 422
    assert "Too many" in response.json()["detail"]
    assert attachment_count(seeded) == 10
    assert len(leftovers(upload_dir)) == 10
    # the limit is per conversation
    assert upload(cathy, Chat(cathy).id, PNG).status_code == 201
