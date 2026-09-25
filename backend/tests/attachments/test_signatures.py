"""File type validation by real signature (magic bytes), not by name or client content type."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.attachments import sniff_content_type
from tests.attachments.helpers import (
    EXE,
    GIF,
    HEIC,
    HEIF,
    HTML,
    JPEG,
    PDF,
    PNG,
    SVG,
    WEBP,
    ZIP,
    upload,
)
from tests.chat.helpers import Chat
from tests.inbox.helpers import strip_capabilities


def stored_files(upload_dir: Path) -> list[Path]:
    return [p for p in upload_dir.rglob("*") if p.is_file()] if upload_dir.exists() else []


@pytest.mark.parametrize(
    ("data", "content_type", "declared"),
    [
        (JPEG, "image/jpeg", "image/jpeg"),
        (PNG, "image/png", "image/png"),
        (WEBP, "image/webp", "image/webp"),
        (HEIC, "image/heic", "image/heic"),
        (HEIF, "image/heif", "image/heif"),
        (PDF, "application/pdf", "application/pdf"),
    ],
)
def test_each_allowed_type_is_accepted(
    cathy: TestClient, chat: Chat, data: bytes, content_type: str, declared: str
) -> None:
    response = upload(cathy, chat.id, data, "file.bin", declared)
    assert response.status_code == 201, response.text
    info = response.json()["attachment"]
    assert info["content_type"] == content_type
    assert info["size_bytes"] == len(data)


@pytest.mark.parametrize(
    "brand", [b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heif", b"heim"]
)
def test_heif_family_brands(brand: bytes) -> None:
    head = b"\x00\x00\x00\x18ftyp" + brand + b"\x00" * 16
    assert sniff_content_type(head) in {"image/heic", "image/heif"}


def test_avif_and_unknown_iso_brands_are_not_accepted() -> None:
    assert sniff_content_type(b"\x00\x00\x00\x18ftypavif" + b"\x00" * 16) is None
    assert sniff_content_type(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16) is None


def test_pdf_signature_may_follow_a_little_junk() -> None:
    assert sniff_content_type(b"\n\n  " + PDF) == "application/pdf"


@pytest.mark.parametrize(
    ("label", "data"),
    [
        ("html", HTML),
        ("svg", SVG),
        ("exe", EXE),
        ("zip", ZIP),
        ("gif", GIF),
        ("text", b"just some text, not an image"),
    ],
)
def test_other_content_is_refused_even_when_dressed_up_as_an_image(
    cathy: TestClient, chat: Chat, upload_dir: Path, label: str, data: bytes
) -> None:
    for name, declared in [("evil.png", "image/png"), ("evil.pdf", "application/pdf")]:
        response = upload(cathy, chat.id, data, name, declared)
        assert response.status_code == 415, (label, response.text)
    # no declared type at all: still refused by content
    assert upload(cathy, chat.id, data, "x.jpg", "application/octet-stream").status_code == 415
    assert stored_files(upload_dir) == []


@pytest.mark.parametrize("declared", ["image/svg+xml", "text/html", "application/zip"])
def test_a_declared_type_outside_the_allowed_set_is_refused_even_for_valid_bytes(
    cathy: TestClient, chat: Chat, declared: str
) -> None:
    assert upload(cathy, chat.id, PNG, "x.png", declared).status_code == 415


@pytest.mark.parametrize("data", [b"\xff\xd8", b"\x89PNG\r\n", b"RIFF\x00\x00\x00\x00WEB", b"%PD"])
def test_truncated_headers_are_refused(cathy: TestClient, chat: Chat, data: bytes) -> None:
    assert upload(cathy, chat.id, data, "cut.png", "image/png").status_code == 415


def test_empty_file_is_422(cathy: TestClient, chat: Chat) -> None:
    assert upload(cathy, chat.id, b"", "empty.png", "image/png").status_code == 422


@pytest.mark.parametrize(
    ("data", "declared"),
    [(PNG, "image/jpeg"), (JPEG, "application/pdf"), (PDF, "image/png"), (WEBP, "image/heic")],
)
def test_declared_type_that_contradicts_the_bytes_is_415(
    cathy: TestClient, chat: Chat, data: bytes, declared: str
) -> None:
    response = upload(cathy, chat.id, data, "x.bin", declared)
    assert response.status_code == 415
    assert "match" in response.json()["detail"]


@pytest.mark.parametrize("declared", ["application/octet-stream", "", "image/jpg", None])
def test_generic_or_aliased_declared_types_are_fine(
    cathy: TestClient, chat: Chat, declared: str | None
) -> None:
    data = JPEG
    response = upload(cathy, chat.id, data, "photo.jpeg", declared)
    assert response.status_code == 201, response.text
    assert response.json()["attachment"]["content_type"] == "image/jpeg"


def test_heic_and_heif_names_are_interchangeable(cathy: TestClient, chat: Chat) -> None:
    assert upload(cathy, chat.id, HEIC, "a.heic", "image/heif").status_code == 201
    assert upload(cathy, chat.id, HEIF, "b.heif", "image/heic").status_code == 201


def test_extension_and_name_never_decide_the_type_or_the_stored_extension(
    cathy: TestClient, chat: Chat, upload_dir: Path
) -> None:
    response = upload(cathy, chat.id, PNG, "notes.exe", "image/png")
    assert response.status_code == 201
    assert response.json()["attachment"]["content_type"] == "image/png"
    (stored,) = stored_files(upload_dir)
    assert stored.suffix == ".png"


def test_missing_field_or_wrong_body_is_422(cathy: TestClient, chat: Chat) -> None:
    assert upload(cathy, chat.id, PNG, field="document").status_code == 422
    url = f"/api/chat/conversations/{chat.id}/attachments"
    assert cathy.post(url, json={"file": "x"}).status_code == 422
    assert cathy.post(url).status_code == 422
    garbled = cathy.post(
        url, content=b"not multipart", headers={"Content-Type": "multipart/form-data; boundary=zz"}
    )
    assert garbled.status_code == 422


def test_second_file_part_is_422(cathy: TestClient, chat: Chat, upload_dir: Path) -> None:
    response = cathy.post(
        f"/api/chat/conversations/{chat.id}/attachments",
        files=[("file", ("a.png", PNG, "image/png")), ("file", ("b.png", PNG, "image/png"))],
    )
    assert response.status_code == 422
    assert stored_files(upload_dir) == []
    assert list((upload_dir / ".incoming").glob("*")) == []


def test_role_ownership_and_auth(
    cathy: TestClient, amy: TestClient, hr: TestClient, anon: TestClient, chat: Chat, seeded
) -> None:
    # Helen decides a queue, so she may use the chat (bell inbox) but the conversation is not
    # hers; a user who neither files nor approves is refused outright.
    assert upload(hr, chat.id, PNG).status_code == 404
    strip_capabilities(seeded, "helen.yeung@example.com")
    assert upload(hr, chat.id, PNG).status_code == 403
    assert upload(anon, chat.id, PNG).status_code == 401
    assert upload(amy, chat.id, PNG).status_code == 404  # someone else's conversation
    assert upload(cathy, 99999, PNG).status_code == 404


def test_csrf_header_is_required(att_app, chat: Chat) -> None:  # type: ignore[no-untyped-def]
    with TestClient(att_app) as raw:  # no X-Requested-With
        from tests.conftest import login

        login(raw, "cathy.ng@example.com")
        response = raw.post(
            f"/api/chat/conversations/{chat.id}/attachments",
            files={"file": ("a.png", PNG, "image/png")},
            headers={"X-Requested-With": ""},
        )
        assert response.status_code == 403
