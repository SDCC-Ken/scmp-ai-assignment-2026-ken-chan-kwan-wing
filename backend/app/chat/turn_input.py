"""Turn input for messages that carry attachments.

``app.agent.graph.TurnDeps`` is owned by the agent graph. ``ChatTurnDeps`` extends it with the
message's attachments (bytes already loaded) so the document-reading step can use
``deps.attachments`` without changing how the service builds a turn. The current graph ignores
the field.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.agent.graph import TurnDeps
from app.db.models import Attachment
from app.services.attachments import resolve_storage_path

logger = logging.getLogger(__name__)


@dataclass
class AttachmentInput:
    """One uploaded document handed to a turn. ``data`` is ``None`` if the file is unreadable."""

    id: int
    filename: str
    content_type: str
    size_bytes: int
    data: bytes | None = None


@dataclass
class ChatTurnDeps(TurnDeps):
    attachments: list[AttachmentInput] = field(default_factory=list)


def build_attachment_inputs(
    attachments: list[Attachment], upload_dir: str | Path
) -> list[AttachmentInput]:
    inputs: list[AttachmentInput] = []
    for row in attachments:
        data: bytes | None
        try:
            data = resolve_storage_path(upload_dir, row.storage_path).read_bytes()
        except Exception:
            logger.warning("Stored file of attachment %s is missing or unreadable", row.id)
            data = None
        inputs.append(
            AttachmentInput(
                id=row.id,
                filename=row.original_filename,
                content_type=row.content_type,
                size_bytes=row.size_bytes,
                data=data,
            )
        )
    return inputs
