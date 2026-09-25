"""Persistent conversation state (``conversations.state_json``).

Holds the draft the user is filling in (slots), an optional link to the existing request being
edited, and the one open confirmation card. Everything is plain JSON so a conversation can be
reopened later and continue exactly where it stopped.
"""

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.domain.enums import ClaimType, DayPart, LeaveType, RequestType

CardAction = Literal["create", "update", "cancel", "retry"]
CardState = Literal["open", "used", "superseded", "discarded"]


class LeaveSlots(BaseModel):
    leave_type: LeaveType | None = None
    start_date: date | None = None
    end_date: date | None = None
    start_day_part: DayPart | None = None
    end_day_part: DayPart | None = None

    def is_empty(self) -> bool:
        return all(v is None for v in self.model_dump().values())


class ClaimSlots(BaseModel):
    claim_type: ClaimType | None = None
    # Kept as an exact Decimal (JSON string) so "12.345" is remembered and rejected, not rounded.
    amount: Decimal | None = None
    currency: str | None = None
    receipt_date: date | None = None

    def is_empty(self) -> bool:
        return all(v is None for v in self.model_dump().values())


class PendingCard(BaseModel):
    card_id: str
    action: CardAction
    request_type: RequestType
    request_id: int | None = None
    payload_hash: str
    state: CardState = "open"


class HeldDocument(BaseModel):
    """A readable document that arrived while a draft of the OTHER type was open.

    The assistant asked which request the user wants; the extraction waits here (no bytes) so the
    answer can use it without another upload. Dropped as soon as the user carries on with the
    open draft or uploads something new.
    """

    attachment_id: int
    filename: str
    extraction: dict[str, Any]


class InboxItem(BaseModel):
    """One entry of a bell-inbox snapshot (see ``app.chat.inbox``)."""

    kind: Literal["approval", "notice"]
    request_type: RequestType
    request_id: int
    notification_id: int | None = None  # kind "notice": the notification this item stands for


class InboxState(BaseModel):
    """The queue of an "Items to handle" conversation, stored with the conversation.

    ``index`` is the position (0-based) of the item whose card is shown, or was shown last
    (-1 before the first card); ``open_card_id`` is the newest card still waiting for an answer.
    Independent of the confirmation-card ``pending_card`` and of the draft: normal chat keeps
    working while an inbox card is open.
    """

    title: str
    items: list[InboxItem]
    index: int = -1
    open_card_id: str | None = None
    handled: int = 0  # approved, rejected or acknowledged
    skipped: int = 0
    already_handled: int = 0  # dropped because it was handled elsewhere or no longer applies
    finished: bool = False


class ConversationState(BaseModel):
    active_request_type: RequestType | None = None
    leave: LeaveSlots = Field(default_factory=LeaveSlots)
    claim: ClaimSlots = Field(default_factory=ClaimSlots)
    editing_request_id: int | None = None
    # Values of the request being edited before any change (normalised strings, for diffs).
    original: dict[str, str | None] | None = None
    awaiting: str | None = None  # field the assistant last asked for
    # Uploaded documents that belong to the draft; linked to the request on Confirm so approvers
    # can open them. Filled by the document-reading step (empty for older stored states).
    attachment_ids: list[int] = Field(default_factory=list)
    # Which draft fields were read from a document: ``{field: attachment_id}`` (card tags).
    sources: dict[str, int] = Field(default_factory=dict)
    # Fields where the user's value differs from the document: ``{field: document value}``
    # (normalised). Shown as card warnings for as long as the two still differ.
    doc_conflicts: dict[str, str] = Field(default_factory=dict)
    # Fields a document should have carried but did not (or unreadable): ``{field: file name}``.
    # The follow-up question names the file. Removed as soon as the field is filled.
    doc_unread: dict[str, str] = Field(default_factory=dict)
    doc_days_advised: float | None = None  # "3 days of rest" when no last day could be read
    doc_warnings: list[str] = Field(default_factory=list)  # e.g. the name on the document differs
    held_document: HeldDocument | None = None
    pending_card: PendingCard | None = None
    inbox: InboxState | None = (
        None  # only in "Items to handle" conversations (optional, legacy-safe)
    )
    state_version: int = 0

    def has_draft(self) -> bool:
        return not (self.leave.is_empty() and self.claim.is_empty()) or (
            self.editing_request_id is not None
        )

    def open_card(self) -> PendingCard | None:
        card = self.pending_card
        return card if card is not None and card.state == "open" else None

    def open_inbox_card_id(self) -> str | None:
        return self.inbox.open_card_id if self.inbox is not None else None

    def reset_draft(self) -> None:
        self.active_request_type = None
        self.leave = LeaveSlots()
        self.claim = ClaimSlots()
        self.editing_request_id = None
        self.original = None
        self.awaiting = None
        self.attachment_ids = []
        self.sources = {}
        self.doc_conflicts = {}
        self.doc_unread = {}
        self.doc_days_advised = None
        self.doc_warnings = []


def load_state(
    raw: dict[str, Any] | None, active_request_type: RequestType | None
) -> ConversationState:
    """Parse ``state_json``; NULL or unreadable content yields an empty state (never raises)."""
    if raw:
        try:
            return ConversationState.model_validate(raw)
        except ValidationError:
            pass
    return ConversationState(active_request_type=active_request_type)


def dump_state(state: ConversationState) -> dict[str, Any]:
    return state.model_dump(mode="json")


def amount_text(amount: Decimal | None) -> str | None:
    """``120`` and ``120.00`` compare equal: quantise to 2 dp unless there are more decimals."""
    if amount is None:
        return None
    if amount.is_finite() and amount.as_tuple().exponent >= -2:  # type: ignore[operator]
        return format(amount.quantize(Decimal("0.01")), "f")
    return format(amount, "f")


def normalised_values(state: ConversationState, request_type: RequestType) -> dict[str, str | None]:
    """The slots as comparable strings with defaults applied (day parts full, currency HKD)."""
    if request_type is RequestType.LEAVE:
        s = state.leave
        return {
            "leave_type": s.leave_type.value if s.leave_type else None,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "start_day_part": (s.start_day_part or DayPart.FULL).value,
            "end_day_part": (s.end_day_part or DayPart.FULL).value,
        }
    c = state.claim
    return {
        "claim_type": c.claim_type.value if c.claim_type else None,
        "amount": amount_text(c.amount),
        "currency": (c.currency or "HKD").upper(),
        "receipt_date": c.receipt_date.isoformat() if c.receipt_date else None,
    }


def payload_hash(action: str, request_id: int | None, values: dict[str, str | None]) -> str:
    blob = json.dumps({"a": action, "r": request_id, "v": values}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
