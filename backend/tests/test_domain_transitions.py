from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product

import pytest

from app.domain.enums import RequestStatus as S
from app.domain.enums import RequestType, UserRole
from app.domain.errors import InvalidTransitionError, NotAuthorizedError
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
    (S.PENDING_APPROVAL, S.CANCELLED),
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
    approver_user_id: int | None = None
    status: S = S.DRAFT
    submitted_at: datetime | None = None
    reviewed_by_user_id: int | None = None
    reviewed_at: datetime | None = None
    reviewer_note: str | None = None
    updated_at: datetime = NOW


HR, FIN, EMP = U(4, UserRole.HR_APPROVER), U(5, UserRole.FINANCE_APPROVER), U(1, UserRole.EMPLOYEE)
OTHER_HR = U(6, UserRole.HR_APPROVER)  # an HR approver who is NOT assigned to the request


def pending(rtype: RequestType, approver: U | None, **kw) -> Req:  # type: ignore[no-untyped-def]
    return Req(
        rtype, status=S.PENDING_APPROVAL, approver_user_id=approver.id if approver else None, **kw
    )


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
def test_approve_and_reject_by_the_assigned_approver(rtype: RequestType, approver: U) -> None:
    req = pending(rtype, approver)
    result = apply_transition(req, S.APPROVED, actor=approver, note=" ok ", now=NOW)
    assert result.to_status is S.APPROVED
    assert (req.reviewed_by_user_id, req.reviewed_at, req.reviewer_note) == (approver.id, NOW, "ok")

    req = pending(rtype, approver)
    apply_transition(req, S.REJECTED, actor=approver, note="Not eligible", now=NOW)
    assert req.status is S.REJECTED and req.reviewer_note == "Not eligible"


@pytest.mark.parametrize("target", [S.APPROVED, S.REJECTED])
@pytest.mark.parametrize("note", [None, "", "   "])
def test_the_reviewer_note_is_optional_for_approve_and_reject(target: S, note: str | None) -> None:
    """Phase 3: rejecting no longer needs a note (the old rule is gone)."""
    req = pending(RequestType.LEAVE, HR)
    apply_transition(req, target, actor=HR, note=note, now=NOW)
    assert req.status is target and req.reviewer_note is None
    assert (req.reviewed_by_user_id, req.reviewed_at) == (HR.id, NOW)


@pytest.mark.parametrize("target", [S.APPROVED, S.REJECTED])
def test_only_the_assigned_approver_can_decide(target: S) -> None:
    for actor in (OTHER_HR, EMP, FIN, None, U(4, UserRole.HR_APPROVER, is_active=False)):
        req = pending(RequestType.LEAVE, HR)
        with pytest.raises(NotAuthorizedError):
            apply_transition(req, target, actor=actor)
        assert req.status is S.PENDING_APPROVAL and req.reviewed_by_user_id is None


def test_a_request_without_an_assigned_approver_cannot_be_decided() -> None:
    req = pending(RequestType.LEAVE, None)
    with pytest.raises(NotAuthorizedError):
        apply_transition(req, S.APPROVED, actor=HR)
    assert req.status is S.PENDING_APPROVAL


def test_the_assigned_approver_needs_the_matching_role() -> None:
    """A claim assigned to an HR approver (bad data) still cannot be decided by them."""
    req = pending(RequestType.CLAIM, HR)
    with pytest.raises(NotAuthorizedError):
        apply_transition(req, S.APPROVED, actor=HR)
    assert req.status is S.PENDING_APPROVAL


def test_self_approval_blocked_even_when_assigned() -> None:
    hr_own_leave = pending(RequestType.LEAVE, HR, employee_id=HR.id)
    with pytest.raises(NotAuthorizedError, match="own"):
        apply_transition(hr_own_leave, S.APPROVED, actor=HR)
    fin_own_claim = pending(RequestType.CLAIM, FIN, employee_id=FIN.id)
    with pytest.raises(NotAuthorizedError, match="own"):
        apply_transition(fin_own_claim, S.REJECTED, actor=FIN)


@pytest.mark.parametrize("status", [S.DRAFT, S.SUBMISSION_FAILED, S.CANCELLED, S.APPROVED])
@pytest.mark.parametrize("target", [S.APPROVED, S.REJECTED])
def test_only_pending_approval_can_be_decided(status: S, target: S) -> None:
    req = Req(RequestType.LEAVE, status=status, approver_user_id=HR.id)
    with pytest.raises(InvalidTransitionError):
        apply_transition(req, target, actor=HR)
    assert req.status is status


def test_terminal_request_cannot_change() -> None:
    req = Req(RequestType.LEAVE, status=S.APPROVED, approver_user_id=HR.id)
    with pytest.raises(InvalidTransitionError):
        apply_transition(req, S.REJECTED, actor=HR, note="late")
    assert req.status is S.APPROVED


def test_owner_can_cancel_pending_request() -> None:
    req = Req(RequestType.LEAVE, employee_id=EMP.id, status=S.PENDING_APPROVAL)
    result = apply_transition(req, S.CANCELLED, actor=EMP, now=NOW)
    assert (result.from_status, result.to_status) == (S.PENDING_APPROVAL, S.CANCELLED)
    assert req.status is S.CANCELLED and req.reviewed_by_user_id is None


@pytest.mark.parametrize("actor", [None, HR, FIN, U(9, UserRole.EMPLOYEE)])
def test_only_the_owner_can_cancel_a_pending_request(actor: U | None) -> None:
    req = Req(RequestType.CLAIM, employee_id=EMP.id, status=S.PENDING_APPROVAL)
    with pytest.raises(NotAuthorizedError):
        apply_transition(req, S.CANCELLED, actor=actor)
    assert req.status is S.PENDING_APPROVAL


@pytest.mark.parametrize("status", [S.DRAFT, S.SUBMISSION_FAILED])
def test_unsubmitted_request_cancels_by_owner_or_system_but_never_by_others(status: S) -> None:
    for actor in (EMP, None):
        req = Req(RequestType.LEAVE, employee_id=EMP.id, status=status)
        apply_transition(req, S.CANCELLED, actor=actor)
        assert req.status is S.CANCELLED
    req = Req(RequestType.LEAVE, employee_id=EMP.id, status=status)
    with pytest.raises(NotAuthorizedError):
        apply_transition(req, S.CANCELLED, actor=HR)
    assert req.status is status


@pytest.mark.parametrize("status", [S.APPROVED, S.REJECTED, S.CANCELLED])
def test_final_requests_cannot_be_cancelled(status: S) -> None:
    req = Req(RequestType.LEAVE, employee_id=EMP.id, status=status)
    with pytest.raises(InvalidTransitionError):
        apply_transition(req, S.CANCELLED, actor=EMP)
    assert req.status is status
