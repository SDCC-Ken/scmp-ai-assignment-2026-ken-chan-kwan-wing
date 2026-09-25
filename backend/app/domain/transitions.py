"""Request status state machine shared by leave and claim requests."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.clock import utcnow
from app.domain.enums import RequestStatus as S
from app.domain.enums import RequestType
from app.domain.errors import InvalidTransitionError, NotAuthorizedError
from app.domain.roles import UserLike, can_decide

TRANSITIONS: dict[S, frozenset[S]] = {
    S.DRAFT: frozenset({S.PENDING_APPROVAL, S.SUBMISSION_FAILED, S.CANCELLED}),
    S.SUBMISSION_FAILED: frozenset({S.PENDING_APPROVAL, S.CANCELLED}),
    S.PENDING_APPROVAL: frozenset({S.APPROVED, S.REJECTED, S.CANCELLED}),
    S.APPROVED: frozenset(),
    S.REJECTED: frozenset(),
    S.CANCELLED: frozenset(),
}
TERMINAL_STATUSES = frozenset(s for s, targets in TRANSITIONS.items() if not targets)


class TransitionableRequest(Protocol):
    request_type: RequestType
    employee_id: int
    approver_user_id: int | None
    status: S
    submitted_at: datetime | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    reviewer_note: str | None
    updated_at: datetime


@dataclass(frozen=True)
class TransitionResult:
    """Audit-event fields describing an applied transition."""

    from_status: S
    to_status: S


def can_transition(from_status: S, to_status: S) -> bool:
    return S(to_status) in TRANSITIONS[S(from_status)]


def assert_transition(from_status: S, to_status: S) -> None:
    if not can_transition(from_status, to_status):
        raise InvalidTransitionError(str(from_status), str(to_status))


def apply_transition(
    request: TransitionableRequest,
    to_status: S,
    *,
    actor: UserLike | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> TransitionResult:
    """Validate and apply a status change in place; return (from_status, to_status).

    * Approve/reject need the request's assigned approver (``approver_user_id``): an active user
      with the matching approver role who is not the request's own employee (no
      self-approval). Only a ``pending_approval`` request can be decided (the state machine).
      The reviewer note is optional for both.
    * Cancelling a request that is already ``pending_approval`` (not yet reviewed) needs the
      request's own employee as actor. Cancelling a ``draft`` / ``submission_failed`` request
      accepts no actor (system), but an actor that is given must be the owner.
    * Moving to ``pending_approval`` stamps ``submitted_at`` (first time only).
    Nothing is mutated when a rule is violated.
    """
    to_status = S(to_status)
    from_status = S(request.status)
    assert_transition(from_status, to_status)
    now = now or utcnow()
    clean_note = note.strip() if note and note.strip() else None

    if to_status in (S.APPROVED, S.REJECTED):
        if actor is None or not can_decide(actor, request):
            if actor is not None and actor.id == request.employee_id:
                raise NotAuthorizedError("Reviewers cannot review their own requests")
            raise NotAuthorizedError("Only the assigned approver may decide this request")
        request.reviewed_by_user_id = actor.id
        request.reviewed_at = now
        request.reviewer_note = clean_note
    elif to_status == S.CANCELLED:
        if from_status == S.PENDING_APPROVAL and actor is None:
            raise NotAuthorizedError("Only the requester can cancel a pending request")
        if actor is not None and actor.id != request.employee_id:
            raise NotAuthorizedError("Only the requester can cancel this request")
    elif to_status == S.PENDING_APPROVAL and request.submitted_at is None:
        request.submitted_at = now

    request.status = to_status
    request.updated_at = now
    return TransitionResult(from_status=from_status, to_status=to_status)
