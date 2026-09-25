"""Notification API shapes (see docs/phase3-approval-design.md, sections 4 and 5)."""

from pydantic import BaseModel

from app.domain.enums import RequestType
from app.schemas.chat import IsoZ


class NotificationItem(BaseModel):
    id: int
    event_type: str
    title: str
    body: str
    request_type: RequestType
    request_id: int
    read_at: IsoZ | None
    created_at: IsoZ
    link: str | None = None  # /approvals/{type}/{id} for the assigned approver while pending


class NotificationList(BaseModel):
    items: list[NotificationItem]
    unread_count: int
