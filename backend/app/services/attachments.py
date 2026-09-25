"""Attachment storage: validation by real file signature, safe on-disk layout and access rules.

Files live under ``UPLOAD_DIR`` (the Docker volume in this PoC), never as blobs in SQLite and
never on their way to ReqRes. Everything about a name or type comes from the file *content*:

* the type is sniffed from the magic bytes (the extension and the client's content type are
  never trusted; a declared type that contradicts the bytes is refused);
* the stored name is ``<yyyy>/<mm>/<uuid4hex>.<ext>`` with the extension taken from the sniffed
  type, so a user-controlled name cannot influence the path;
* the user's file name is kept only for display, after sanitising.

The upload is streamed (``UploadWriter``): at most ``max_bytes`` are read, so an oversized body
is refused without being read to the end.
"""

import hashlib
import logging
import os
import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import Attachment, ClaimRequest, LeaveRequest, User
from app.domain.clock import utcnow
from app.domain.enums import RequestStatus, RequestType, UserRole
from app.schemas.chat import AttachmentInfo

logger = logging.getLogger(__name__)

MAX_STAGED_PER_CONVERSATION = 10
STAGED_MAX_AGE = timedelta(hours=24)
MAX_FILENAME_CHARS = 120
DEFAULT_FILENAME = "attachment"
SNIFF_BYTES = 1024  # PDFs may start with a little junk before ``%PDF-``
INCOMING_DIR = ".incoming"  # temp files, inside UPLOAD_DIR so os.replace stays on one volume

ALLOWED_TYPES: dict[str, str] = {  # content type -> extension
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "application/pdf": "pdf",
}
# Client-declared types accepted as an alias of an allowed one.
_DECLARED_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
    "application/x-pdf": "application/pdf",
}
# Declared types that carry no information (browsers send them for HEIC / unknown files).
_GENERIC_DECLARED = frozenset({"", "application/octet-stream", "binary/octet-stream"})
_HEIC_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs"})
_HEIF_BRANDS = frozenset({b"mif1", b"msf1", b"heif"})

# Requests that an approver may open the files of: submitted (not draft / failed / cancelled).
APPROVER_VISIBLE_STATUSES = frozenset(
    {RequestStatus.PENDING_APPROVAL, RequestStatus.APPROVED, RequestStatus.REJECTED}
)
APPROVER_REQUEST_TYPE = {
    UserRole.HR_APPROVER: RequestType.LEAVE,
    UserRole.FINANCE_APPROVER: RequestType.CLAIM,
}


# ---- errors ----------------------------------------------------------------------------------
class AttachmentError(Exception):
    """A refused upload / attachment; ``status_code`` is the HTTP status to answer with."""

    status_code = 422

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class InvalidUpload(AttachmentError):
    status_code = 422


class UploadTooLarge(AttachmentError):
    status_code = 413


class UnsupportedFileType(AttachmentError):
    status_code = 415


class AttachmentNotFound(AttachmentError):
    status_code = 404


# ---- signature sniffing -----------------------------------------------------------------------
def sniff_content_type(head: bytes) -> str | None:
    """The allowed content type the leading bytes prove, or ``None``."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and len(head) >= 12:
        brand = head[8:12]
        if brand in _HEIC_BRANDS:
            return "image/heic"
        if brand in _HEIF_BRANDS:
            return "image/heif"
    if b"%PDF-" in head[:SNIFF_BYTES]:
        return "application/pdf"
    return None


def _canonical_declared(declared: str | None) -> str | None:
    """Normalise the client's content type; ``None`` means "no usable claim"."""
    value = (declared or "").split(";", 1)[0].strip().lower()
    value = _DECLARED_ALIASES.get(value, value)
    if value in _GENERIC_DECLARED:
        return None
    return value


def _declared_matches(declared: str, sniffed: str) -> bool:
    if declared == sniffed:
        return True
    # HEIC and HEIF are one container family; clients use the two names interchangeably.
    return {declared, sniffed} <= {"image/heic", "image/heif"}


# ---- names ------------------------------------------------------------------------------------
_WS = re.compile(r"\s+")


def sanitize_filename(name: str | None) -> str:
    """A display-only file name: no path, control / bidi-override characters, at most 120 chars."""
    text = (name or "").replace("\x00", "")
    text = re.split(r"[\\/]", text)[-1]  # drop every directory part (either separator)
    text = unicodedata.normalize("NFC", text)
    text = _WS.sub(" ", text)  # tabs / newlines become spaces before other controls are dropped
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    text = _WS.sub(" ", text).strip(" .")
    if not text:
        return DEFAULT_FILENAME
    if len(text) > MAX_FILENAME_CHARS:
        stem, dot, ext = text.rpartition(".")
        if dot and 0 < len(ext) <= 10 and stem:
            text = stem[: MAX_FILENAME_CHARS - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            text = text[:MAX_FILENAME_CHARS].rstrip(" .")
    return text or DEFAULT_FILENAME


def content_disposition(filename: str) -> str:
    """``inline`` header with an ASCII-safe ``filename`` and a percent-encoded ``filename*``."""
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename.encode("ascii", "ignore").decode())
    stem, dot, tail = ascii_name.strip().rpartition(".")
    if not dot:
        stem, tail = tail, ""
    ext = dot + tail
    if not re.search(r"[A-Za-z0-9]", stem):  # nothing meaningful survived (e.g. a CJK name)
        stem = DEFAULT_FILENAME
    ascii_name = stem + ext
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


# ---- storage layout ---------------------------------------------------------------------------
def upload_root(upload_dir: str | Path) -> Path:
    return Path(upload_dir).expanduser().resolve()


def _ensure_private_dir(path: Path) -> None:
    """Create ``path`` and any missing parents with mode 0700 (umask-proof)."""
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)


def resolve_storage_path(upload_dir: str | Path, storage_path: str) -> Path:
    """Absolute path of a stored file; refuses anything that would leave ``UPLOAD_DIR``."""
    root = upload_root(upload_dir)
    candidate = (root / storage_path).resolve()
    if not candidate.is_relative_to(root):
        raise AttachmentNotFound("Attachment not found")
    return candidate


def _unlink_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove an upload file that is no longer needed")


# ---- streaming writer -------------------------------------------------------------------------
@dataclass(frozen=True)
class StagedUpload:
    """A fully received, validated file waiting in the temp area."""

    tmp_path: Path
    size_bytes: int
    sha256: str
    content_type: str

    @property
    def extension(self) -> str:
        return ALLOWED_TYPES[self.content_type]


class UploadWriter:
    """Receives an upload chunk by chunk into a private temp file.

    ``write`` raises ``UploadTooLarge`` as soon as the running size passes ``max_bytes`` (so the
    caller can stop reading the request body) and ``UnsupportedFileType`` as soon as the first
    ``SNIFF_BYTES`` prove the signature is not an allowed one. Bytes are only put on disk after
    the signature check passed. ``finish`` returns the validated ``StagedUpload``.
    """

    def __init__(
        self, upload_dir: str | Path, max_bytes: int, declared_type: str | None = None
    ) -> None:
        self._root = upload_root(upload_dir)
        self._max = max_bytes
        self._declared: str | None = None
        self.declare(declared_type)
        self._size = 0
        self._sha = hashlib.sha256()
        self._head = bytearray()
        self._content_type: str | None = None
        self._fd: int | None = None
        self._tmp: Path | None = None

    def declare(self, declared_type: str | None) -> None:
        """Record the client's claimed type; a claim outside the allowed set is refused now."""
        declared = _canonical_declared(declared_type)
        if declared is not None and declared not in ALLOWED_TYPES:
            raise UnsupportedFileType(
                "Unsupported file. Only JPEG, PNG, WEBP, HEIC/HEIF images and PDF are accepted."
            )
        self._declared = declared

    @property
    def bytes_received(self) -> int:
        return self._size

    def _open_temp(self) -> None:
        incoming = self._root / INCOMING_DIR
        _ensure_private_dir(incoming)
        self._tmp = incoming / f"{uuid.uuid4().hex}.part"
        self._fd = os.open(self._tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

    def _check_signature(self) -> None:
        sniffed = sniff_content_type(bytes(self._head))
        if sniffed is None:
            raise UnsupportedFileType(
                "Unsupported file. Only JPEG, PNG, WEBP, HEIC/HEIF images and PDF are accepted."
            )
        if self._declared is not None and not _declared_matches(self._declared, sniffed):
            raise UnsupportedFileType("The file content does not match its declared type.")
        self._content_type = sniffed
        self._open_temp()
        self._write_all(bytes(self._head))
        self._head.clear()

    def _write_all(self, data: bytes) -> None:
        assert self._fd is not None
        view = memoryview(data)
        while view:
            written = os.write(self._fd, view)
            view = view[written:]

    def write(self, chunk: bytes) -> None:
        if not chunk:
            return
        try:
            self._size += len(chunk)
            if self._size > self._max:
                raise UploadTooLarge(
                    f"The file is too large (maximum {self._max // (1024 * 1024)} MB)."
                )
            self._sha.update(chunk)
            if self._content_type is None:
                self._head.extend(chunk)
                if len(self._head) >= SNIFF_BYTES:
                    self._check_signature()
            else:
                self._write_all(chunk)
        except BaseException:
            self.abort()
            raise

    def finish(self) -> StagedUpload:
        try:
            if self._size == 0:
                raise InvalidUpload("The file is empty.")
            if self._content_type is None:
                self._check_signature()
            assert self._fd is not None and self._tmp is not None and self._content_type
            os.close(self._fd)
            self._fd = None
            return StagedUpload(self._tmp, self._size, self._sha.hexdigest(), self._content_type)
        except BaseException:
            self.abort()
            raise

    def abort(self) -> None:
        """Drop the temp file (safe to call repeatedly and after ``finish`` moved it)."""
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        _unlink_quietly(self._tmp)


# ---- database operations ----------------------------------------------------------------------
def to_info(att: Attachment) -> AttachmentInfo:
    return AttachmentInfo(
        id=att.id,
        filename=att.original_filename,
        content_type=att.content_type,
        size_bytes=att.size_bytes,
        url=f"/api/attachments/{att.id}",
        created_at=att.created_at,
    )


def staged_filter(conversation_id: int) -> Any:
    return (
        Attachment.conversation_id == conversation_id,
        Attachment.message_id.is_(None),
        Attachment.request_id.is_(None),
    )


def count_staged(session: Session, conversation_id: int) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(Attachment).where(*staged_filter(conversation_id))
        )
        or 0
    )


def ensure_can_stage(session: Session, conversation_id: int) -> None:
    if count_staged(session, conversation_id) >= MAX_STAGED_PER_CONVERSATION:
        raise InvalidUpload(
            f"Too many files are waiting in this conversation (maximum "
            f"{MAX_STAGED_PER_CONVERSATION}). Send your message with them first."
        )


def save_upload(
    session: Session,
    staged: StagedUpload,
    *,
    owner_id: int,
    conversation_id: int,
    filename: str | None,
    upload_dir: str | Path,
    now: datetime | None = None,
) -> Attachment:
    """Move the validated temp file to its final place and insert the row.

    The move is an atomic ``os.replace``; if the insert fails, the file is removed again.
    """
    ensure_can_stage(session, conversation_id)
    moment = now or utcnow()
    root = upload_root(upload_dir)
    relative = f"{moment:%Y}/{moment:%m}/{uuid.uuid4().hex}.{staged.extension}"
    destination = root / relative
    _ensure_private_dir(destination.parent)
    os.replace(staged.tmp_path, destination)
    os.chmod(destination, 0o600)
    try:
        attachment = Attachment(
            owner_user_id=owner_id,
            conversation_id=conversation_id,
            original_filename=sanitize_filename(filename),
            content_type=staged.content_type,
            size_bytes=staged.size_bytes,
            sha256=staged.sha256,
            storage_path=relative,
            created_at=moment,
        )
        session.add(attachment)
        session.commit()
    except BaseException:
        session.rollback()
        _unlink_quietly(destination)
        raise
    return attachment


def store_chunks(
    session: Session,
    chunks: Iterable[bytes],
    *,
    owner_id: int,
    conversation_id: int,
    filename: str | None,
    declared_type: str | None,
    upload_dir: str | Path,
    max_bytes: int,
) -> Attachment:
    """Synchronous convenience wrapper around ``UploadWriter`` + ``save_upload``."""
    writer = UploadWriter(upload_dir, max_bytes, declared_type)
    try:
        for chunk in chunks:
            writer.write(chunk)
        staged = writer.finish()
        return save_upload(
            session,
            staged,
            owner_id=owner_id,
            conversation_id=conversation_id,
            filename=filename,
            upload_dir=upload_dir,
        )
    finally:
        writer.abort()  # a no-op after a successful move


def load_staged(
    session: Session, owner_id: int, conversation_id: int, attachment_ids: list[int]
) -> list[Attachment]:
    """The caller's staged uploads of this conversation, or ``InvalidUpload`` (one message for
    every failure, so nothing is revealed about other users' files)."""
    if len(set(attachment_ids)) != len(attachment_ids):
        raise InvalidUpload("The same file was listed more than once.")
    if not attachment_ids:
        return []
    rows = session.scalars(
        select(Attachment).where(
            Attachment.id.in_(attachment_ids),
            Attachment.owner_user_id == owner_id,
            *staged_filter(conversation_id),
        )
    ).all()
    if len(rows) != len(attachment_ids):
        raise InvalidUpload(
            "One of the attachments is not available for this message. Upload it again."
        )
    by_id = {row.id: row for row in rows}
    return [by_id[i] for i in attachment_ids]


def attach_to_message(session: Session, attachments: list[Attachment], message_id: int) -> None:
    """Claim staged uploads for a message (atomic: a file can only be attached once)."""
    if not attachments:
        return
    result = session.execute(
        update(Attachment)
        .where(Attachment.id.in_([a.id for a in attachments]), Attachment.message_id.is_(None))
        .values(message_id=message_id)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != len(attachments):
        session.rollback()
        raise InvalidUpload("One of the attachments was already used. Upload it again.")
    for attachment in attachments:
        attachment.message_id = message_id


def attachments_by_message(
    session: Session, message_ids: list[int]
) -> dict[int, list[AttachmentInfo]]:
    if not message_ids:
        return {}
    rows = session.scalars(
        select(Attachment).where(Attachment.message_id.in_(message_ids)).order_by(Attachment.id)
    ).all()
    grouped: dict[int, list[AttachmentInfo]] = {}
    for row in rows:
        assert row.message_id is not None
        grouped.setdefault(row.message_id, []).append(to_info(row))
    return grouped


def link_to_request(
    session: Session,
    attachment_ids: Iterable[int],
    request_type: RequestType,
    request_id: int,
    owner_id: int,
) -> int:
    """Link the owner's attachments to a request so approvers can open them.

    Idempotent; ids that do not exist or belong to someone else are ignored, and a file that is
    already linked to a *different* request keeps that link. Does not commit. Returns the
    number of attachments now linked to this request.
    """
    ids = sorted(set(attachment_ids))
    if not ids:
        return 0
    rows = session.scalars(
        select(Attachment).where(Attachment.id.in_(ids), Attachment.owner_user_id == owner_id)
    ).all()
    linked = 0
    for row in rows:
        if row.request_id is None:
            row.request_type = request_type
            row.request_id = request_id
        if row.request_type == request_type and row.request_id == request_id:
            linked += 1
    session.flush()
    return linked


def read_attachment_bytes(
    session: Session, upload_dir: str | Path, attachment_id: int, owner_id: int
) -> tuple[Attachment, bytes]:
    """Load a file for the LLM step; only its owner may (``AttachmentNotFound`` otherwise)."""
    attachment = session.get(Attachment, attachment_id)
    if attachment is None or attachment.owner_user_id != owner_id:
        raise AttachmentNotFound("Attachment not found")
    try:
        return attachment, resolve_storage_path(upload_dir, attachment.storage_path).read_bytes()
    except OSError:
        logger.warning("Stored file of attachment %s is missing or unreadable", attachment.id)
        raise AttachmentNotFound("Attachment not found") from None


def can_download(session: Session, user: User, attachment: Attachment) -> bool:
    """The owner always; an approver only for a submitted request of the type their role
    reviews (HR: leave, Finance: claim) that is assigned to them (Phase 3). Everyone else: no."""
    if attachment.owner_user_id == user.id:
        return True
    reviewed = APPROVER_REQUEST_TYPE.get(user.role)
    if reviewed is None or attachment.request_type != reviewed or attachment.request_id is None:
        return False
    model = LeaveRequest if reviewed == RequestType.LEAVE else ClaimRequest
    request = session.get(model, attachment.request_id)
    return (
        request is not None
        and request.status in APPROVER_VISIBLE_STATUSES
        and request.approver_user_id == user.id
    )


def cleanup_staged_uploads(
    session: Session,
    upload_dir: str | Path,
    *,
    older_than: timedelta = STAGED_MAX_AGE,
    now: datetime | None = None,
) -> int:
    """Delete staged (never attached, never linked) uploads older than ``older_than``.

    Not scheduled anywhere in the PoC; call it from a cron / startup hook when needed.
    Returns the number of removed attachments.
    """
    cutoff = (now or utcnow()) - older_than
    rows = session.scalars(
        select(Attachment).where(
            Attachment.message_id.is_(None),
            Attachment.request_id.is_(None),
            Attachment.created_at < cutoff,
        )
    ).all()
    for row in rows:
        try:
            _unlink_quietly(resolve_storage_path(upload_dir, row.storage_path))
        except AttachmentNotFound:
            logger.warning("Skipping file removal for attachment %s (bad path)", row.id)
        session.delete(row)
    session.commit()
    _remove_stale_temp_files(upload_dir, cutoff)
    return len(rows)


def _remove_stale_temp_files(upload_dir: str | Path, cutoff: datetime) -> None:
    """Temp files of uploads that died mid-way (process crash) are older than any real upload."""
    incoming = upload_root(upload_dir) / INCOMING_DIR
    if not incoming.is_dir():
        return
    for path in incoming.glob("*.part"):
        try:
            if path.stat().st_mtime < cutoff.timestamp():
                path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not inspect a stale upload temp file")
