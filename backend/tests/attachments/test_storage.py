"""On-disk layout, permissions, hashing, filename sanitisation and failure cleanup."""

import hashlib
import re
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Attachment
from app.db.session import Database
from app.services.attachments import (
    DEFAULT_FILENAME,
    MAX_FILENAME_CHARS,
    AttachmentNotFound,
    content_disposition,
    read_attachment_bytes,
    resolve_storage_path,
    sanitize_filename,
    store_chunks,
)
from tests.attachments.helpers import PNG, upload, upload_ok
from tests.chat.helpers import Chat

LAYOUT = re.compile(r"^\d{4}/\d{2}/[0-9a-f]{32}\.png$")


def files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_layout_permissions_and_hash(
    cathy: TestClient, chat: Chat, seeded: Database, upload_dir: Path
) -> None:
    data = PNG + b"unique payload"
    info = upload_ok(cathy, chat.id, data, filename="Receipt 1.png")
    with seeded.session_factory() as s:
        row = s.get(Attachment, info["id"])
        assert row is not None
        assert LAYOUT.match(row.storage_path), row.storage_path
        assert row.sha256 == hashlib.sha256(data).hexdigest()
        assert row.size_bytes == len(data)
        assert row.original_filename == "Receipt 1.png"
        assert row.content_type == "image/png"
        assert row.request_type is None and row.request_id is None and row.message_id is None
        assert row.extraction_json is None
        stored = upload_dir / row.storage_path
    assert stored.read_bytes() == data
    assert mode(stored) == 0o600
    assert mode(stored.parent) == 0o700  # <mm>
    assert mode(stored.parent.parent) == 0o700  # <yyyy>
    assert mode(upload_dir) == 0o700
    # the stored name never contains the client's name
    assert "Receipt" not in stored.name
    assert files_under(upload_dir) == [stored]  # no temp file left behind


def test_response_shape(cathy: TestClient, chat: Chat) -> None:
    info = upload_ok(cathy, chat.id, filename="a.png")
    assert set(info) == {"id", "filename", "content_type", "size_bytes", "url", "created_at"}
    assert info["url"] == f"/api/attachments/{info['id']}"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", info["created_at"])


def test_every_upload_gets_its_own_random_name(cathy: TestClient, chat: Chat) -> None:
    a = upload_ok(cathy, chat.id)
    b = upload_ok(cathy, chat.id)
    assert a["id"] != b["id"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("receipt.png", "receipt.png"),
        ("../../etc/passwd", "passwd"),
        ("/etc/passwd", "passwd"),
        ("C:\\Windows\\System32\\evil.png", "evil.png"),
        ("..\\..\\secret.png", "secret.png"),
        ("a\x00b.png", "ab.png"),
        ("evil\u202egnp.exe", "evilgnp.exe"),
        ("line\nbreak\ttab.png", "line break tab.png"),
        ("  many    spaces   .png  ", "many spaces .png"),
        ("..", DEFAULT_FILENAME),
        (".", DEFAULT_FILENAME),
        ("", DEFAULT_FILENAME),
        ("   ", DEFAULT_FILENAME),
        (None, DEFAULT_FILENAME),
        ("folder/", DEFAULT_FILENAME),
        ("\u202e\u200b\x07", DEFAULT_FILENAME),
        ("收據 receipt.png", "收據 receipt.png"),
        ("Café résumé.pdf", "Café résumé.pdf"),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_very_long_names_are_capped_and_keep_their_extension() -> None:
    name = sanitize_filename("x" * 500 + ".pdf")
    assert len(name) == MAX_FILENAME_CHARS and name.endswith(".pdf")
    assert len(sanitize_filename("y" * 500)) == MAX_FILENAME_CHARS
    assert len(sanitize_filename("字" * 500 + ".png")) == MAX_FILENAME_CHARS


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "..\\..\\evil.png",
        "a\x00.png",
        "x" * 400 + ".png",
        "收據.png",
        "%2e%2e%2fetc%2fpasswd",
        "....//....//x.png",
    ],
)
def test_hostile_names_cannot_escape_the_upload_dir(
    cathy: TestClient, chat: Chat, tmp_path: Path, upload_dir: Path, name: str
) -> None:
    response = upload(cathy, chat.id, PNG, name, "image/png")
    assert response.status_code == 201, response.text
    assert len(response.json()["attachment"]["filename"]) <= MAX_FILENAME_CHARS
    inside = files_under(upload_dir)
    assert len(inside) == 1 and LAYOUT.match(str(inside[0].relative_to(upload_dir)))
    outside = [p for p in tmp_path.rglob("*") if p.is_file() and upload_dir not in p.parents]
    assert outside == []  # nothing was created anywhere else under the sandbox root


def test_resolve_storage_path_refuses_escapes(upload_dir: Path) -> None:
    upload_dir.mkdir()
    for bad in ["../outside.png", "/etc/passwd", "2026/../../x"]:
        with pytest.raises(AttachmentNotFound):
            resolve_storage_path(upload_dir, bad)
    assert (
        resolve_storage_path(upload_dir, "2026/09/a.png") == upload_dir.resolve() / "2026/09/a.png"
    )


def test_content_disposition_is_ascii_safe_and_encodes_the_real_name() -> None:
    header = content_disposition("收據 “x”.pdf")
    assert header.startswith('inline; filename="')
    head, _, star = header.partition("; filename*=")
    assert head.isascii() and star.startswith("UTF-8''")
    assert "%E6%94%B6%E6%93%9A" in star and '"' not in star
    plain = content_disposition('a"b\r\nSet-Cookie: x.png')
    assert "\r" not in plain and "\n" not in plain
    assert plain.count('"') == 2  # only the two quotes around the ASCII fallback
    assert content_disposition("收據.png").startswith('inline; filename="attachment.png";')
    assert content_disposition("report 2026.pdf").startswith('inline; filename="report 2026.pdf";')


# ---- failure cleanup --------------------------------------------------------------------------
def test_file_is_removed_when_the_insert_fails(
    seeded: Database, upload_dir: Path, session: Session
) -> None:
    with seeded.session_factory() as s:
        with pytest.raises(IntegrityError):  # owner 9999 does not exist: FK violation on commit
            store_chunks(
                s,
                [PNG],
                owner_id=9999,
                conversation_id=9999,
                filename="x.png",
                declared_type="image/png",
                upload_dir=upload_dir,
                max_bytes=1024,
            )
        assert s.scalars(select(Attachment)).all() == []
    assert files_under(upload_dir) == []  # neither the final file nor the temp file


def test_file_is_removed_when_commit_raises(
    seeded: Database, upload_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with seeded.session_factory() as s:

        def boom() -> None:
            raise SQLAlchemyError("disk full")

        monkeypatch.setattr(s, "commit", boom)
        with pytest.raises(SQLAlchemyError):
            store_chunks(
                s,
                [PNG],
                owner_id=1,
                conversation_id=1,
                filename="x.png",
                declared_type=None,
                upload_dir=upload_dir,
                max_bytes=1024,
            )
    assert files_under(upload_dir) == []


def test_refused_upload_leaves_no_temp_file(seeded: Database, upload_dir: Path) -> None:
    with seeded.session_factory() as s:
        for chunks in ([b"<html>" * 300], [b""], [PNG + b"x" * 5000]):
            with pytest.raises(Exception):  # noqa: B017  (415 / 422 / 413 variants)
                store_chunks(
                    s,
                    chunks,
                    owner_id=1,
                    conversation_id=1,
                    filename="x",
                    declared_type=None,
                    upload_dir=upload_dir,
                    max_bytes=1024,
                )
    assert files_under(upload_dir) == []


def test_read_attachment_bytes_checks_the_owner(
    cathy: TestClient, chat: Chat, seeded: Database, upload_dir: Path
) -> None:
    info = upload_ok(cathy, chat.id, PNG + b"zz")
    with seeded.session_factory() as s:
        row = s.get(Attachment, info["id"])
        assert row is not None
        att, data = read_attachment_bytes(s, upload_dir, info["id"], row.owner_user_id)
        assert data == PNG + b"zz" and att.id == info["id"]
        with pytest.raises(AttachmentNotFound):
            read_attachment_bytes(s, upload_dir, info["id"], row.owner_user_id + 1)
        with pytest.raises(AttachmentNotFound):
            read_attachment_bytes(s, upload_dir, 12345, row.owner_user_id)
        (upload_dir / row.storage_path).unlink()
        with pytest.raises(AttachmentNotFound):
            read_attachment_bytes(s, upload_dir, info["id"], row.owner_user_id)
