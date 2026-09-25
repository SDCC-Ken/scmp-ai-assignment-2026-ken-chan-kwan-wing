"""Chat API shapes (see docs/chat-api-contract.md). Timestamps are ISO-8601 UTC ending in ``Z``."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

from app.domain.enums import RequestType


def iso_z(value: datetime) -> str:
    """UTC timestamp with second precision and a trailing ``Z`` (naive values are taken as UTC)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


IsoZ = Annotated[datetime, PlainSerializer(iso_z, return_type=str)]

TraceStepName = Literal[
    "understand", "documents", "merge", "validate", "decide", "submit", "status", "respond"
]
WarningCode = Literal["llm_unavailable", "llm_invalid_output", "submission_failed", "stale_card"]


class TraceStep(BaseModel):
    step: TraceStepName
    label: str
    detail: str = ""
    ok: bool = True
    duration_ms: int = 0


class AttachmentInfo(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    url: str  # /api/attachments/{id}
    created_at: IsoZ


class CardField(BaseModel):
    key: str
    label: str
    value: str
    old_value: str | None = None
    source: Literal["document"] | None = None  # the value was read from an attachment


class CardInfoLine(BaseModel):
    """An informational line on a confirmation card (for example the leave balance). Unlike
    ``warnings`` it may be neutral (``info``) and never blocks Confirm."""

    label: str
    value: str
    tone: Literal["info", "warning"] = "info"


class ConfirmationCard(BaseModel):
    type: Literal["confirmation_card"] = "confirmation_card"
    card_id: str
    action: Literal["create", "update", "cancel", "retry"]
    request_type: RequestType
    request_id: int | None = None
    title: str
    fields: list[CardField]
    warnings: list[str] = Field(default_factory=list)
    info: list[CardInfoLine] = Field(default_factory=list)  # e.g. the leave balance (leave only)
    state: Literal["open", "used", "superseded", "discarded"] = "open"
    confirm_label: Literal["Submit", "Save changes", "Cancel request", "Retry"]
    attachments: list[AttachmentInfo] = Field(default_factory=list)  # linked on Confirm


class StatusItem(BaseModel):
    request_type: RequestType
    id: int
    status: str
    status_label: str
    summary: str
    submitted_at: IsoZ | None = None
    reviewed_at: IsoZ | None = None
    reviewer_note: str | None = None
    external_reference_id: str | None = None
    approver_name: str | None = None  # display name only (never the e-mail); None when unassigned


class StatusCard(BaseModel):
    type: Literal["status_card"] = "status_card"
    requests: list[StatusItem]
    empty: bool = False


class ResultCard(BaseModel):
    type: Literal["result_card"] = "result_card"
    outcome: Literal["submitted", "updated", "cancelled", "failed"]
    request_type: RequestType
    request_id: int
    status: str
    status_label: str
    message: str
    external_reference_id: str | None = None


class BalanceLine(BaseModel):
    """One leave type of the signed-in user's balance (days in 0.5 steps)."""

    leave_type: Literal["annual", "sick"]
    entitled_days: float
    approved_days: float
    pending_days: float  # pending requests are shown, never deducted
    remaining_days: float  # entitled - approved (may be negative)


class BalanceCard(BaseModel):
    type: Literal["balance_card"] = "balance_card"
    year: int  # calendar year in Hong Kong
    lines: list[BalanceLine]


UiCard = Annotated[
    ConfirmationCard | StatusCard | ResultCard | BalanceCard, Field(discriminator="type")
]


class Message(BaseModel):
    id: int
    sender_type: Literal["user", "assistant", "system"]
    content: str
    created_at: IsoZ
    ui: UiCard | None = None
    trace: list[TraceStep] | None = None
    attachments: list[AttachmentInfo] = Field(default_factory=list)  # user messages only


class ConversationSummary(BaseModel):
    id: int
    title: str
    status: Literal["active", "closed"]
    active_request_type: RequestType | None = None
    has_pending_card: bool = False
    created_at: IsoZ
    updated_at: IsoZ


class ConversationList(BaseModel):
    items: list[ConversationSummary]


class ConversationDetail(BaseModel):
    conversation: ConversationSummary
    messages: list[Message]


class TurnResponse(BaseModel):
    conversation: ConversationSummary
    user_message: Message | None = None
    assistant_messages: list[Message]
    warning_code: WarningCode | None = None


class MessageBody(BaseModel):
    # The upper bound comes from settings.chat_max_message_chars and is enforced in the route
    # (422), so it can be configured without changing this schema.
    # May be empty when at least one attachment is sent (checked in the route). Bounds come
    # from settings (chat_max_message_chars, max_attachments_per_message) and give a 422.
    content: str = ""
    attachment_ids: list[int] = Field(default_factory=list)


class ActionBody(BaseModel):
    card_id: str = Field(min_length=1, max_length=64)
    action: Literal["confirm", "discard"]


STATUS_LABELS = {
    "draft": "Draft",
    "pending_approval": "Pending approval",
    "submission_failed": "Submission failed",
    "approved": "Approved",
    "rejected": "Rejected",
    "cancelled": "Cancelled",
}
