"""In-app notifications: list, mark read, and compose the text at read time.

A row only stores who, which event and which request. ``title``, ``body`` and ``link`` are
composed when the list is read, from the row and the current request, so the text never goes
stale and never carries attachments or e-mail addresses (plain text only).

``link`` is set only for the approver the request is assigned to, and only while the request is
still pending; requesters (and everyone else) get ``None`` and open a dialog instead.
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import Notification, User
from app.domain.clock import utcnow
from app.domain.enums import RequestStatus, RequestType
from app.domain.roles import can_decide
from app.schemas.notifications import NotificationItem, NotificationList
from app.services.requests import MODELS, Req, summary_text

NOUN = {RequestType.LEAVE: "leave request", RequestType.CLAIM: "claim"}
DECISION_WORD = {"request.approved": "Approved", "request.rejected": "Rejected"}


def _name(session: Session, user_id: int | None) -> str | None:
    user = session.get(User, user_id) if user_id is not None else None
    return user.display_name if user is not None else None


def compose(session: Session, viewer: User, row: Notification) -> NotificationItem:
    """The API item for ``row`` as seen by its recipient ``viewer``."""
    rtype = RequestType(row.request_type)
    noun = NOUN[rtype]
    req: Req | None = session.get(MODELS[rtype], row.request_id)
    ref = f"{noun} #{row.request_id}"
    event = row.event_type
    title = f"Update on {ref}"  # unknown / legacy event types stay neutral
    body = ""

    if req is not None:
        who = _name(session, req.employee_id) or "A colleague"
        if event == "request.submitted":
            title, body = f"New {noun} from {who}", summary_text(req)
        elif event == "request.updated":
            title, body = f"{who} changed {ref}", summary_text(req)
        elif event == "request.cancelled":
            title, body = f"{who} cancelled {ref}", summary_text(req)
        elif event in DECISION_WORD:
            word = DECISION_WORD[event]
            title = f"Your {ref} was {word.lower()}"
            reviewer = _name(session, req.reviewed_by_user_id)
            body = f"{word} by {reviewer}." if reviewer else f"{word}."
            if req.reviewer_note:
                body += f" Note: {req.reviewer_note}"
    elif event in DECISION_WORD:
        title = f"Your {ref} was {DECISION_WORD[event].lower()}"

    link = None
    if req is not None and req.status == RequestStatus.PENDING_APPROVAL and can_decide(viewer, req):
        link = f"/approvals/{rtype.value}/{req.id}"
    return NotificationItem(
        id=row.id,
        event_type=event,
        title=title,
        body=body,
        request_type=rtype,
        request_id=row.request_id,
        read_at=row.read_at,
        created_at=row.created_at,
        link=link,
    )


def unread_count(session: Session, user: User) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.recipient_user_id == user.id, Notification.read_at.is_(None))
        )
        or 0
    )


def list_notifications(session: Session, user: User, limit: int) -> NotificationList:
    """The caller's newest notifications; ``unread_count`` covers all of them, not just the page."""
    rows = session.scalars(
        select(Notification)
        .where(Notification.recipient_user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    ).all()
    return NotificationList(
        items=[compose(session, user, r) for r in rows], unread_count=unread_count(session, user)
    )


def mark_read(session: Session, user: User, notification_id: int) -> bool:
    """Mark the caller's notification read (idempotent: an already read one keeps its time).

    False when the id does not exist or belongs to someone else (the route answers 404).
    """
    row = session.get(Notification, notification_id)
    if row is None or row.recipient_user_id != user.id:
        return False
    if row.read_at is None:
        session.execute(
            update(Notification)
            .where(Notification.id == row.id, Notification.read_at.is_(None))
            .values(read_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        session.commit()
    return True


def mark_all_read(session: Session, user: User) -> int:
    result = session.execute(
        update(Notification)
        .where(Notification.recipient_user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0)
