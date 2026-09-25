"""The bell inbox: "handle everything waiting for me, one by one" (docs/inbox-design.md).

``open_inbox`` snapshots what needs the caller's attention and starts a NEW conversation that
shows it one card at a time; ``act`` handles the buttons of such a card.

* The queue is stored in the conversation state (``ConversationState.inbox``); no table.
* Approve and Reject call ``services.approvals.decide``: the very function behind
  ``POST /api/approvals/{type}/{id}/decision`` (assigned approver, still pending, one winner,
  audit, requester notification), with ``via="inbox"`` added to the audit metadata. The LLM is
  never involved.
* Every item is re-validated right before it is shown, so an item handled elsewhere in the
  meantime is skipped silently (and counted as "already handled").
* A card is claimed with a compare-and-swap on the conversation state BEFORE anything else
  happens, so a double click (or two tabs) has exactly one winner; the other gets 409.
"""

import logging
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.actions import StaleCardError
from app.chat.format import plural
from app.chat.state import ConversationState, InboxItem, InboxState, dump_state, load_state
from app.chat.store import (
    add_message,
    cas_save_state,
    make_title,
    set_inbox_card_state,
)
from app.db.models import Conversation, ConversationMessage, Notification, User
from app.domain import clock
from app.domain.enums import ConversationStatus, RequestType, SenderType
from app.schemas.inbox import InboxCard, InboxNotice, InboxPosition
from app.services import approvals, notifications
from app.services.requests import MODELS

logger = logging.getLogger(__name__)

APPROVAL_ACTIONS = ("approve", "reject", "skip")
NOTICE_ACTIONS = ("acknowledge", "skip")
APPROVER_EVENTS = frozenset({"request.submitted", "request.updated", "request.cancelled"})
COVERED_EVENTS = ("request.submitted", "request.updated")  # covered by the approval card
DECISION_EVENTS = frozenset({"request.approved", "request.rejected"})
DECIDED_TEXT = {"approve": "approved", "reject": "rejected"}
_RETRIES = 3

INTRO_TEXT = "You have {n} to handle. Let's go through them one by one."
STALE_TEXT = "That request was already handled."
STALE_NOTICE_TEXT = "That notice is no longer available."


class InboxActionInvalid(Exception):
    """A card button that cannot be used as sent (wrong action for the card, missing
    ``confirmed``): the API answers 422."""


class InboxConflict(Exception):
    """The conversation kept changing while the result was being recorded (HTTP 409)."""


def new_inbox_card_id() -> str:
    return "i_" + secrets.token_hex(4)


# ---- what is in the queue -----------------------------------------------------------------------
def _notice_applies(session: Session, user: User, row: Notification) -> bool:
    """Does this unread notification still make sense for its recipient?

    The request must exist; approver events must concern a request assigned to the caller (not
    their own); decision events must concern the caller's own request.
    """
    if row.recipient_user_id != user.id:
        return False
    req = session.get(MODELS[RequestType(row.request_type)], row.request_id)
    if req is None:
        return False
    if row.event_type in APPROVER_EVENTS:
        return req.approver_user_id == user.id and req.employee_id != user.id
    if row.event_type in DECISION_EVENTS:
        return req.employee_id == user.id
    return True  # unknown / legacy event: shown with the neutral text of the bell


def snapshot_items(session: Session, user: User) -> list[InboxItem]:
    """Approvals first (oldest submitted first), then the other unread notices (oldest first)."""
    items: list[InboxItem] = []
    covered: set[tuple[RequestType, int]] = set()
    for req in approvals.pending_queue(session, user):
        items.append(InboxItem(kind="approval", request_type=req.request_type, request_id=req.id))
        covered.add((req.request_type, req.id))
    rows = session.scalars(
        select(Notification)
        .where(Notification.recipient_user_id == user.id, Notification.read_at.is_(None))
        .order_by(Notification.created_at, Notification.id)
    )
    for row in rows:
        rtype = RequestType(row.request_type)
        if row.event_type in COVERED_EVENTS and (rtype, row.request_id) in covered:
            continue  # the approval card covers it; deciding marks it read
        if not _notice_applies(session, user, row):
            continue
        items.append(
            InboxItem(
                kind="notice", request_type=rtype, request_id=row.request_id, notification_id=row.id
            )
        )
    return items


def _label(session: Session, item: InboxItem) -> str:
    """``leave request #1 from Amy Lau`` (``claim #2 from ...``); never an e-mail address."""
    noun = notifications.NOUN[item.request_type]
    req = session.get(MODELS[item.request_type], item.request_id)
    owner = session.get(User, req.employee_id) if req is not None else None
    who = f" from {owner.display_name}" if owner is not None else ""
    return f"{noun} #{item.request_id}{who}"


def _upper_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _build_card(session: Session, user: User, inbox: InboxState, index: int) -> InboxCard | None:
    """The card for ``inbox.items[index]``, or ``None`` when it no longer applies (re-validated)."""
    item = inbox.items[index]
    position = InboxPosition(index=index + 1, total=len(inbox.items))
    if item.kind == "approval":
        try:
            detail = approvals.get_detail(session, user, item.request_type, item.request_id)
        except approvals.ApprovalNotFound:
            return None
        return InboxCard(
            card_id=new_inbox_card_id(),
            kind="approval",
            position=position,
            title=_upper_first(_label(session, item)),
            request_type=item.request_type,
            request_id=item.request_id,
            detail=detail,
            actions=list(APPROVAL_ACTIONS),  # type: ignore[arg-type]
        )
    row = (
        session.get(Notification, item.notification_id, populate_existing=True)
        if item.notification_id is not None
        else None
    )
    if row is None or row.read_at is not None or not _notice_applies(session, user, row):
        return None
    shown = notifications.compose(session, user, row)
    return InboxCard(
        card_id=new_inbox_card_id(),
        kind="notice",
        position=position,
        title=shown.title,
        request_type=item.request_type,
        request_id=item.request_id,
        notice=InboxNotice(title=shown.title, body=shown.body),
        actions=list(NOTICE_ACTIONS),  # type: ignore[arg-type]
    )


def _next_card(
    session: Session, user: User, inbox: InboxState, start: int
) -> tuple[InboxCard | None, int, int]:
    """First still-valid card from ``start`` on: ``(card, its index, how many were dropped)``."""
    dropped = 0
    for index in range(start, len(inbox.items)):
        card = _build_card(session, user, inbox, index)
        if card is not None:
            return card, index, dropped
        dropped += 1
    return None, len(inbox.items), dropped


def _card_message(session: Session, conversation_id: int, card: InboxCard) -> ConversationMessage:
    return add_message(
        session,
        conversation_id,
        SenderType.ASSISTANT,
        f"Item {card.position.index} of {card.position.total}",
        ui=card,
    )


# ---- opening the inbox --------------------------------------------------------------------------
@dataclass
class Opened:
    conversation: Conversation
    messages: list[ConversationMessage]


def open_inbox(session: Session, user: User) -> Opened | int:
    """A NEW conversation with the intro and the first card, or the caller's real unread count
    when nothing needs handling (no conversation is created then)."""
    items = snapshot_items(session, user)
    inbox = InboxState(title=make_title(f"Items to handle ({len(items)})"), items=items)
    card, index, dropped = _next_card(session, user, inbox, 0)
    if card is None:
        return notifications.unread_count(session, user)
    inbox.already_handled += dropped
    inbox.index = index
    inbox.open_card_id = card.card_id

    conv = Conversation(user_id=user.id, status=ConversationStatus.ACTIVE)
    session.add(conv)
    session.flush()
    intro = add_message(
        session,
        conv.id,
        SenderType.ASSISTANT,
        INTRO_TEXT.format(n=plural(len(items), "item")),
    )
    first = _card_message(session, conv.id, card)
    conv.state_json = dump_state(ConversationState(inbox=inbox))
    session.commit()
    return Opened(conversation=conv, messages=[intro, first])


# ---- acting on a card ---------------------------------------------------------------------------
def _closing_text(inbox: InboxState) -> str:
    text = f"All done. You handled {plural(inbox.handled, 'item')}"
    if inbox.skipped:
        text += f" and skipped {inbox.skipped}"
    text += "."
    if inbox.already_handled:
        verb = "was" if inbox.already_handled == 1 else "were"
        text += f" {plural(inbox.already_handled, 'item')} {verb} already handled elsewhere."
    if inbox.skipped:
        text += " Skipped items stay in your bell and in Approvals."
    return text


def _reopen(session: Session, conv: Conversation, card_id: str) -> None:
    """Best effort after an unexpected failure: give the claimed card back so it can be retried."""
    try:
        session.rollback()
        session.refresh(conv)
        state = load_state(conv.state_json, conv.active_request_type)
        if state.inbox is not None and state.inbox.open_card_id is None:
            new = state.model_copy(deep=True)
            assert new.inbox is not None
            new.inbox.open_card_id = card_id
            if cas_save_state(session, conv.id, state.state_version, new):
                session.commit()
                return
        session.rollback()
    except Exception:  # never mask the original error
        logger.exception("Could not reopen an inbox card after a failure")
        session.rollback()


def act(
    session: Session,
    user: User,
    conv: Conversation,
    card_id: str,
    action: str,
    note: str | None,
    confirmed: bool | None,
) -> list[ConversationMessage]:
    """Handle approve / reject / skip / acknowledge on the newest open inbox card.

    Returns the new assistant messages: a short result, then the next card or the closing
    message. Raises ``StaleCardError`` (409) when the card is not the newest open one (or lost a
    race), ``InboxActionInvalid`` (422) for a wrong action or a missing ``confirmed``.
    """
    state = load_state(conv.state_json, conv.active_request_type)
    inbox = state.inbox
    if (
        inbox is None
        or inbox.open_card_id is None
        or inbox.open_card_id != card_id
        or not 0 <= inbox.index < len(inbox.items)
    ):
        raise StaleCardError("This card is no longer active.")
    item = inbox.items[inbox.index]
    allowed = APPROVAL_ACTIONS if item.kind == "approval" else NOTICE_ACTIONS
    if action not in allowed:
        raise InboxActionInvalid(f"'{action}' is not available for this card.")
    if action in DECIDED_TEXT and confirmed is not True:
        raise InboxActionInvalid("Approve and Reject need confirmed=true (a second click).")
    label = _label(session, item)

    # 1. Claim the card: from here on nobody else can act on it.
    claimed = state.model_copy(deep=True)
    assert claimed.inbox is not None
    claimed.inbox.open_card_id = None
    if not cas_save_state(session, conv.id, state.state_version, claimed):
        session.rollback()
        raise StaleCardError("The conversation changed; this card is no longer active.")
    session.commit()

    # 2. Do the work (each function commits its own short transaction).
    stale = False
    try:
        if action in DECIDED_TEXT:
            try:
                approvals.decide(
                    session, user, item.request_type, item.request_id, action, note, via="inbox"
                )
            except (
                approvals.ApprovalNotFound,
                approvals.ApprovalConflict,
                approvals.ApprovalForbidden,
            ):
                session.rollback()
                stale = True
        elif action == "acknowledge":
            assert item.notification_id is not None
            stale = not notifications.mark_read(session, user, item.notification_id)
    except Exception:
        _reopen(session, conv, card_id)
        raise

    if stale:
        card_state, outcome = "stale", None
        text = STALE_TEXT if item.kind == "approval" else STALE_NOTICE_TEXT
    elif action == "skip":
        card_state, outcome = "skipped", None
        text = (
            f"Skipped {label}. It stays in your bell and in Approvals."
            if item.kind == "approval"
            else "Skipped. It stays unread in your bell."
        )
    elif action == "acknowledge":
        card_state, outcome = "done", "acknowledged"
        text = "Got it. I marked that notice as read."
    else:
        card_state, outcome = "done", DECIDED_TEXT[action]
        text = f"You {DECIDED_TEXT[action]} {label}."

    # 3. Record the result and show the next item (retried if a chat message bumped the version).
    for _ in range(_RETRIES):
        session.refresh(conv)
        current = load_state(conv.state_json, conv.active_request_type)
        if current.inbox is None or current.inbox.open_card_id is not None:
            raise StaleCardError("The conversation changed; this card is no longer active.")
        new = current.model_copy(deep=True)
        nb = new.inbox
        assert nb is not None
        if stale:
            nb.already_handled += 1
        elif action == "skip":
            nb.skipped += 1
        else:
            nb.handled += 1
        set_inbox_card_state(session, conv.id, card_id, card_state, outcome)
        messages = [add_message(session, conv.id, SenderType.ASSISTANT, text)]
        next_card, next_index, dropped = _next_card(session, user, nb, nb.index + 1)
        nb.already_handled += dropped
        if next_card is not None:
            nb.index = next_index
            nb.open_card_id = next_card.card_id
            messages.append(_card_message(session, conv.id, next_card))
        else:
            nb.finished = True
            messages.append(add_message(session, conv.id, SenderType.ASSISTANT, _closing_text(nb)))
        if cas_save_state(session, conv.id, current.state_version, new):
            conv.updated_at = clock.utcnow()
            session.commit()
            return messages
        session.rollback()
    raise InboxConflict


__all__ = [
    "InboxActionInvalid",
    "InboxConflict",
    "Opened",
    "act",
    "open_inbox",
    "snapshot_items",
]
