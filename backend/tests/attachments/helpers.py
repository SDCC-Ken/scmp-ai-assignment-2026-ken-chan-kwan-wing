"""Sample file bytes and small wrappers for the attachment tests (offline, deterministic)."""

import asyncio
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.attachments import sniff_content_type

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x01" * 40
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 40
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 40
HEIF = b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heic" + b"\x00" * 40
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"

HTML = b"<!doctype html><html><body><script>alert(1)</script></body></html>"
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>'
EXE = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 60
ZIP = b"PK\x03\x04" + b"\x00" * 60
GIF = b"GIF89a" + b"\x00" * 40

MB = 1024 * 1024


def padded(header: bytes, size: int) -> bytes:
    """``header`` followed by zero bytes up to exactly ``size`` bytes."""
    return header + b"\x00" * (size - len(header))


def upload(
    client: TestClient,
    conversation_id: int,
    data: bytes,
    filename: str = "receipt.png",
    content_type: str | None = "auto",
    field: str = "file",
) -> Any:
    if content_type == "auto":  # declare what the bytes really are (like a well-behaved browser)
        content_type = sniff_content_type(data) or "application/octet-stream"
    files = {field: (filename, data, content_type)} if content_type else {field: (filename, data)}
    return client.post(f"/api/chat/conversations/{conversation_id}/attachments", files=files)


def upload_ok(client: TestClient, conversation_id: int, data: bytes = PNG, **kw: Any) -> dict:
    response = upload(client, conversation_id, data, **kw)
    assert response.status_code == 201, response.text
    return response.json()["attachment"]


def multipart_body(
    data: bytes, filename: str = "big.png", content_type: str = "image/png", boundary: str = "BND"
) -> tuple[bytes, bytes, bytes]:
    """(head, data, tail) of a one-file multipart body, so tests can stream it in pieces."""
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head, data, tail


class AsgiResult:
    def __init__(self, status: int, body: bytes, consumed: int) -> None:
        self.status = status
        self.body = body
        self.consumed = consumed  # body messages the server pulled from the client


def asgi_upload(
    app: FastAPI,
    conversation_id: int,
    cookie: str,
    chunks: Iterator[bytes] | list[bytes],
    *,
    content_length: int | None = None,
    boundary: str = "BND",
) -> AsgiResult:
    """POST a multipart body straight to the ASGI app with no Content-Length (chunked) unless
    ``content_length`` is given, counting how many body chunks the server actually reads."""
    pieces = list(chunks)
    consumed = 0
    sent: list[dict[str, Any]] = []
    index = 0

    async def receive() -> dict[str, Any]:
        nonlocal consumed, index
        if index < len(pieces):
            piece = pieces[index]
            index += 1
            consumed += 1
            return {"type": "http.request", "body": piece, "more_body": index < len(pieces)}
        await asyncio.sleep(3600)  # the client has nothing more; never reached when refused
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    headers = [
        (b"host", b"testserver"),
        (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
        (b"x-requested-with", b"XMLHttpRequest"),
        (b"cookie", f"scmp_session={cookie}".encode()),
    ]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": f"/api/chat/conversations/{conversation_id}/attachments",
        "raw_path": f"/api/chat/conversations/{conversation_id}/attachments".encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }

    async def run() -> None:
        await asyncio.wait_for(app(scope, receive, send), timeout=30)

    asyncio.run(run())
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return AsgiResult(status, body, consumed)
