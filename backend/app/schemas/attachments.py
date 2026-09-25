"""Attachment API shapes (see docs/chat-api-contract.md, "Attachments (Phase 2b)")."""

from pydantic import BaseModel

from app.schemas.chat import AttachmentInfo


class AttachmentResponse(BaseModel):
    attachment: AttachmentInfo


__all__ = ["AttachmentInfo", "AttachmentResponse"]
