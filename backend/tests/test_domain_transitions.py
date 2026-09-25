from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product

import pytest

from app.domain.enums import RequestStatus as S
from app.domain.enums import RequestType, UserRole
from app.domain.errors import InvalidTransitionError, NotAuthorizedError, ReviewNoteRequiredError
from app.domain.transitions import (
    TERMINAL_STATUSES,
    TRANSITIONS,
    apply_transition,
    assert_transition,
    can_transition,
)

ALLOWED = {
    (S.DRAFT, S.PENDING_APPROVAL),
    (S.DRAFT, S.SUBMISSION_FAILED),
    (S.DRAFT, S.CANCELLED),
    (S.SUBMISSION_FAILED, S.PENDING_APPROVAL),
    (S.SUBMISSION_FAILED, S.CANCELLED),
    (S.PENDING_APPROVAL, S.APPROVED),
    (S.PENDING_APPROVAL, S.REJECTED),
}
NOW = datetime(2026, 9, 25, 4, 0, tzinfo=UTC)


@dataclass
class U:
    id: int
    role: UserRole
    is_active: bool = True
    email: str = "x@example.com"


@dataclass
class Req:
    request_type: RequestType
    employee_id: int = 1
    status: S = S.DRAFT
    submitted_at: datetime | None = None
    reviewed_by_user_id: int | None = None
    reviewed_at: datetime | None = None
    reviewer_note: str | None = None
    updated_at: datetime = NOW


HR, FIN, EMP = U(4, UserRole.HR_APPROVER), U(5, UserRole.FINANCE_APPROVER), U(1, UserRole.EMPLOYEE)


@pytest.mark.parametrize(("src", "dst"), sorted(ALLOWED))
def test_every_allowed_edge(src: S, dst: S) -> None:
    assert can_transition(src, dst)
    assert_transition(src, dst)


@pytest.mark.parametrize(("src", "dst"), sorted(set(product(S, S)) - ALLOWED))
def test_every_disallowed_edge(src: S, dst: S) -> None:
    assert not can_transition(src, dst)
    with pytest.raises(InvalidTransitionError):
        assert_transition(src, dst)


def test_terminal_states() -> None:
    assert TERMINAL_STATUSES == {S.APPROVED, S.REJECTED, S.CANCELLED}
    for status in TERMINAL_STATUSES:
        assert TRANSITIONS[status] == frozenset()


def test_submit_sets_submitted_at_once() -> None:
    req = Req(RequestType.LEAVE)
    result = apply_transition(req, S.SUBMISSION_FAILED, now=NOW)
    assert (result.from_status, result.to_status) == (S.DRAFT, S.SUBMISSION_FAILED)
    assert req.submitted_at is None
    apply_transition(req, S.PENDING_APPROVAL, now=NOW)
    assert req.submitted_at == NOW and req.status is S.PENDING_APPROVAL


@pytest.mark.parametrize(("rtype", "approver"), [(RequestType.LEAVE, HR), (RequestType.CLAIM, FIN)])
def test_approve_and_reject_by_correct_role(rtype: RequestType, approver: U) -> None:
    req = Req(rtype, status=S.PENDING_APPROVAL)
    result = apply_transition(req, S.APPROVED, actor=approver, note=" ok ", now=NOW)
    assert result.to_status is S.APPROVED
    assert (req.reviewed_by_user_id, req.reviewed_at, req.reviewer_note) == (approver.id, NOW, "ok")

    req = Req(rtype, status=S.PENDING_APPROVAL)
    apply_transition(req, S.REJECTED, actor=approver, note="Not eligible", now=NOW)
    assert req.status is S.REJECTED and req.reviewer_note == "Not eligible"


@pytest.mark.parametrize("note", [None, "", "   "])
def test_reject_needs_note(note: str | None) -> None:
    req = Req(RequestType.LEAVE, status=S.PENDING_APPROVAL)
    with pytest.raises(ReviewNoteRequiredError):
        apply_transition(req, S.REJECTED, actor=HR, note=note)
    assert req.status is S.PENDING_APPROVAL and req.reviewed_by_user_id is None


def test_wrong_role_or_missing_actor_cannot_review() -> None:
    for actor in (EMP, FIN, None, U(4, UserRole.HR_APPROVER, is_active=False)):
        req = Req(RequestType.LEAVE, status=S.PENDING_APPROVAL)
        with pytest.raises(NotAuthorizedError):
            apply_transition(req, S.APPROVED, actor=actor)
        assert req.status is S.PENDING_APPROVAL


def test_self_approval_blocked() -> None:
    hr_own_leave = Req(RequestType.LEAVE, employee_id=HR.id, status=S.PENDING_APPROVAL)
    with pytest.raises(NotAuthorizedError, match="own"):
        apply_transition(hr_own_leave, S.APPROVED, actor=HR)
    fin_own_claim = Req(RequestType.CLAIM, employee_id=FIN.id, status=S.PENDING_APPROVAL)
    with pytest.raises(NotAuthorizedError):
        apply_transition(fin_own_claim, S.REJECTED, actor=FIN, note="no")


def test_terminal_request_cannot_change() -> None:
    req = Req(RequestType.LEAVE, status=S.APPROVED)
    with pytest.raises(InvalidTransitionError):
        apply_transition(req, S.REJECTED, actor=HR, note="late")
    assert req.status is S.APPROVED
