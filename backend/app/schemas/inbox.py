"""Inbox card shape (see docs/inbox-design.md). The ``detail`` of an approval card is exactly the
``ApprovalDetail`` of ``GET /api/approvals/{type}/{id}``."""

from typing import Literal

from pydantic import BaseModel

from app.domain.enums import RequestType
from app.schemas.approvals import ApprovalDetail

InboxAction = Literal["approve", "reject", "skip", "acknowledge"]


class InboxPosition(BaseModel):
    index: int  # 1-based position in the snapshot (skipped-silently items leave a gap)
    total: int  # all items of the snapshot


class InboxNotice(BaseModel):
    title: str
    body: str


class InboxCard(BaseModel):
    type: Literal["inbox_card"] = "inbox_card"
    card_id: str
    kind: Literal["approval", "notice"]
    position: InboxPosition
    title: str
    request_type: RequestType | None = None
    request_id: int | None = None
    detail: ApprovalDetail | None = None  # kind "approval"
    notice: InboxNotice | None = None  # kind "notice"
    actions: list[InboxAction]
    state: Literal["open", "done", "skipped", "stale"] = "open"
    outcome: Literal["approved", "rejected", "acknowledged"] | None = None
