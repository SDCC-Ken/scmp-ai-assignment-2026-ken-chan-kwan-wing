"""Persistence helpers for conversations: state compare-and-swap, messages and card states."""

from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Integer, func, select, update
from sqlalchemy.orm import Session

from app.chat.policy import TITLE_MAX_CHARS
from app.chat.state import ConversationState, dump_state
from app.db.models import Conversation, ConversationMessage
from app.domain.clock import utcnow
from app.domain.enums import SenderType
from app.schemas.chat import AttachmentInfo, ConfirmationCard, Message, TraceStep, UiCard

_UI = TypeAdapter(UiCard)
_TRACE = TypeAdapter(list[TraceStep])
NEW_CHAT_TITLE = "New chat"


def cas_save_state(
    session: Session, conversation_id: int, expected_version: int, new_state: ConversationState
) -> bool:
    """Atomically replace ``state_json`` only if ``state_version`` is still ``expected_version``.

    The UPDATE takes SQLite's write lock, so two concurrent confirms cannot both win: the loser
    sees rowcount 0. ``new_state.state_version`` becomes ``expected_version + 1``.
    """
    new_state.state_version = expected_version + 1
    current = func.coalesce(
        func.json_extract(Conversation.state_json, "$.state_version", type_=Integer),
        0,
        type_=Integer,
    )
    result = session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id, current == expected_version)
        .values(
            state_json=dump_state(new_state),
            active_request_type=new_state.active_request_type,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def add_message(
    session: Session,
    conversation_id: int,
    sender: SenderType,
    content: str,
    *,
    ui: UiCard | None = None,
    trace: list[TraceStep] | None = None,
) -> ConversationMessage:
    metadata: dict[str, Any] | None = None
    if sender == SenderType.ASSISTANT:
        metadata = {
            "ui": ui.model_dump(mode="json") if ui is not None else None,
            "trace": [t.model_dump(mode="json") for t in trace] if trace else None,
        }
    row = ConversationMessage(
        conversation_id=conversation_id,
        sender_type=sender,
        content=content,
        ui_metadata_json=metadata,
    )
    session.add(row)
    session.flush()
    return row


def find_card_message(
    session: Session, conversation_id: int, card_id: str
) -> ConversationMessage | None:
    rows = session.scalars(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.sender_type == SenderType.ASSISTANT,
        )
        .order_by(ConversationMessage.id.desc())
    )
    for row in rows:
        ui = (row.ui_metadata_json or {}).get("ui")
        if (
            isinstance(ui, dict)
            and ui.get("type") == "confirmation_card"
            and (ui.get("card_id") == card_id)
        ):
            return row
    return None


def set_card_state(session: Session, conversation_id: int, card_id: str, state: str) -> bool:
    """Update the stored card (used / superseded / discarded) so reopening shows it correctly."""
    row = find_card_message(session, conversation_id, card_id)
    if row is None:
        return False
    metadata = dict(row.ui_metadata_json or {})
    ui = dict(metadata["ui"])
    ui["state"] = state
    metadata["ui"] = ui
    row.ui_metadata_json = metadata  # new object so the JSON column is marked dirty
    return True


def stored_card(session: Session, conversation_id: int, card_id: str) -> ConfirmationCard | None:
    row = find_card_message(session, conversation_id, card_id)
    if row is None:
        return None
    try:
        card = _UI.validate_python((row.ui_metadata_json or {}).get("ui"))
    except ValidationError:
        return None
    return card if isinstance(card, ConfirmationCard) else None


def message_out(
    row: ConversationMessage, attachments: list[AttachmentInfo] | None = None
) -> Message:
    """Serialise a stored message; legacy / unreadable ``ui_metadata_json`` yields no card.

    ``attachments`` are the files of a user message (empty list otherwise)."""
    meta = row.ui_metadata_json if isinstance(row.ui_metadata_json, dict) else {}
    ui: UiCard | None = None
    trace: list[TraceStep] | None = None
    if row.sender_type == SenderType.ASSISTANT:
        raw_ui = meta.get("ui")
        if isinstance(raw_ui, dict):
            try:
                ui = _UI.validate_python(raw_ui)
            except ValidationError:
                ui = None
        raw_trace = meta.get("trace")
        if isinstance(raw_trace, list):
            try:
                trace = _TRACE.validate_python(raw_trace)
            except ValidationError:
                trace = None
    return Message(
        id=row.id,
        sender_type=row.sender_type.value,
        content=row.content,
        created_at=row.created_at,
        ui=ui,
        trace=trace,
        attachments=attachments or [],
    )


def make_title(first_user_message: str | None) -> str:
    """First user message, whitespace collapsed, at most 60 characters."""
    if not first_user_message or not first_user_message.strip():
        return NEW_CHAT_TITLE
    text = " ".join(first_user_message.split())
    return text if len(text) <= TITLE_MAX_CHARS else text[: TITLE_MAX_CHARS - 1].rstrip() + "…"
