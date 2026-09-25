"""Attachment endpoints. Contract: docs/chat-api-contract.md, "Attachments (Phase 2b)".

* ``POST /api/chat/conversations/{id}/attachments``: employee uploads one file (streamed).
* ``GET /api/attachments/{id}``: the owner, or the approver role that reviews the linked request.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from python_multipart.multipart import MultipartParser, parse_options_header
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_chat_access
from app.db.models import Attachment, Conversation, User
from app.db.session import get_db
from app.schemas.attachments import AttachmentResponse
from app.services.attachments import (
    AttachmentError,
    AttachmentNotFound,
    InvalidUpload,
    UploadTooLarge,
    UploadWriter,
    can_download,
    content_disposition,
    ensure_can_stage,
    resolve_storage_path,
    save_upload,
    to_info,
)

logger = logging.getLogger(__name__)

upload_router = APIRouter(prefix="/chat", tags=["attachments"])
download_router = APIRouter(prefix="/attachments", tags=["attachments"])
ChatUser = Depends(require_chat_access)  # may file requests or decide a queue (Phase 3 inbox)

# The multipart envelope (boundaries, part headers, small extra fields) may add a little to the
# file itself; anything beyond this is refused without reading further.
ENVELOPE_ALLOWANCE = 64 * 1024
FILE_FIELD = "file"


def _http(exc: AttachmentError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


class _MultipartFile:
    """Feeds request-body chunks to python-multipart and streams the ``file`` part into an
    ``UploadWriter`` (nothing is buffered beyond one chunk; a refusal stops the parsing)."""

    def __init__(self, boundary: bytes, writer: UploadWriter) -> None:
        self.writer = writer
        self.filename: str | None = None
        self.part_content_type: str | None = None
        self.file_parts = 0
        self._header_name = b""
        self._header_value = b""
        self._headers: dict[bytes, bytes] = {}
        self._in_file = False
        self.parser = MultipartParser(
            boundary,
            {
                "on_part_begin": self._part_begin,
                "on_header_field": self._header_field,
                "on_header_value": self._header_value_cb,
                "on_header_end": self._header_end,
                "on_headers_finished": self._headers_finished,
                "on_part_data": self._part_data,
            },
        )

    def _part_begin(self) -> None:
        self._headers = {}
        self._header_name = b""
        self._header_value = b""
        self._in_file = False

    def _header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def _header_value_cb(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def _header_end(self) -> None:
        self._headers[self._header_name.lower()] = self._header_value
        self._header_name = b""
        self._header_value = b""

    def _headers_finished(self) -> None:
        disposition = self._headers.get(b"content-disposition", b"")
        _, params = parse_options_header(disposition)
        if params.get(b"name") != FILE_FIELD.encode():
            return
        self.file_parts += 1
        if self.file_parts > 1:
            raise InvalidUpload("Send exactly one file per request.")
        self._in_file = True
        raw_name = params.get(b"filename")
        self.filename = raw_name.decode("utf-8", "replace") if raw_name else None
        declared = self._headers.get(b"content-type")
        self.part_content_type = declared.decode("latin-1") if declared else None
        self.writer.declare(self.part_content_type)

    def _part_data(self, data: bytes, start: int, end: int) -> None:
        if self._in_file:
            self.writer.write(data[start:end])

    def feed(self, chunk: bytes) -> None:
        self.parser.write(chunk)


def _multipart_boundary(request: Request) -> bytes:
    content_type, params = parse_options_header(request.headers.get("content-type", ""))
    boundary = params.get(b"boundary")
    if content_type != b"multipart/form-data" or not boundary:
        raise InvalidUpload("Send the file as multipart/form-data in the field 'file'.")
    return boundary


async def read_upload(
    request: Request, writer: UploadWriter, max_bytes: int
) -> tuple[str | None, str | None]:
    """Stream the request body into ``writer``; returns ``(filename, part content type)``.

    Stops reading at the first refusal (too large, wrong signature, malformed).
    """
    cap = max_bytes + ENVELOPE_ALLOWANCE
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > cap:
        raise UploadTooLarge(f"The file is too large (maximum {max_bytes // (1024 * 1024)} MB).")
    reader = _MultipartFile(_multipart_boundary(request), writer)
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > cap:
                raise UploadTooLarge(
                    f"The file is too large (maximum {max_bytes // (1024 * 1024)} MB)."
                )
            reader.feed(chunk)
        reader.parser.finalize()
    except AttachmentError:
        raise
    except Exception as exc:  # malformed multipart (python-multipart raises its own errors)
        if isinstance(exc, (SQLAlchemyError, OSError)):
            raise
        raise InvalidUpload("The upload could not be read as multipart/form-data.") from None
    if reader.file_parts == 0:
        raise InvalidUpload("The form field 'file' is missing.")
    return reader.filename, reader.part_content_type


def _owned_conversation(db: Session, user: User, conversation_id: int) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conv


def _precheck(db: Session, user: User, conversation_id: int) -> None:
    _owned_conversation(db, user, conversation_id)
    try:
        ensure_can_stage(db, conversation_id)
    except AttachmentError as exc:
        raise _http(exc) from None


@upload_router.post(
    "/conversations/{conversation_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    conversation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = ChatUser,
) -> Any:
    settings = request.app.state.settings
    try:
        # Cheap refusals first, before a single body byte is read.
        await run_in_threadpool(_precheck, db, user, conversation_id)
        writer = UploadWriter(settings.upload_dir, settings.max_upload_bytes)
        try:
            filename, declared = await read_upload(request, writer, settings.max_upload_bytes)
            staged = writer.finish()
            attachment = await run_in_threadpool(
                _save,
                db,
                staged,
                user.id,
                conversation_id,
                filename,
                settings.upload_dir,
            )
        finally:
            writer.abort()  # removes the temp file unless it was moved into place
    except AttachmentError as exc:
        raise _http(exc) from None
    except SQLAlchemyError:
        logger.exception("Database error while storing an upload")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "The database is temporarily unavailable. Please try again."},
        )
    except OSError:
        logger.exception("Could not write an upload to disk")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "The file could not be stored. Please try again."},
        )
    return AttachmentResponse(attachment=to_info(attachment))


def _save(
    db: Session,
    staged: Any,
    owner_id: int,
    conversation_id: int,
    filename: str | None,
    upload_dir: str,
) -> Attachment:
    return save_upload(
        db,
        staged,
        owner_id=owner_id,
        conversation_id=conversation_id,
        filename=filename,
        upload_dir=upload_dir,
    )


_NOT_FOUND_BODY = {"detail": "Attachment not found"}


def _attachment_not_found() -> JSONResponse:
    # One identical response for every refusal, so ids cannot be probed.
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=_NOT_FOUND_BODY)


@download_router.get("/{attachment_id}", response_model=None)
def download_attachment(
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or not can_download(db, user, attachment):
        return _attachment_not_found()
    settings = request.app.state.settings
    try:
        path = resolve_storage_path(settings.upload_dir, attachment.storage_path)
    except AttachmentNotFound:
        return _attachment_not_found()
    if not path.is_file():
        logger.warning("Stored file of attachment %s is missing on disk", attachment.id)
        return _attachment_not_found()
    return FileResponse(
        path,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": content_disposition(attachment.original_filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "sandbox",
        },
    )


__all__: list[str] = ["download_router", "upload_router"]
