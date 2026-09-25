"""Shapes shared by the chat, approvals and inbox schemas (here to avoid import cycles)."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, PlainSerializer


def iso_z(value: datetime) -> str:
    """UTC timestamp with second precision and a trailing ``Z`` (naive values are taken as UTC)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


IsoZ = Annotated[datetime, PlainSerializer(iso_z, return_type=str)]


class AttachmentInfo(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    url: str  # /api/attachments/{id}
    created_at: IsoZ
