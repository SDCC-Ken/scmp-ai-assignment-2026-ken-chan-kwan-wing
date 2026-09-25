"""POST /api/approvals/{type}/{id}/decision: outcomes, validation, errors (A-08..A-11)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AuditEvent, ClaimRequest, LeaveRequest, Notification
from app.db.session import Database
from app.domain.enums import RequestStatus
from app.services import approvals as service
from tests.approvals.conftest import CATHY, decide
from tests.conftest import get_user
from tests.org.helpers import add_leave

S = RequestStatus
NOT_FOUND = {"detail": "Request not found"}


def leave(db: Database, request_id: int = 1) -> LeaveRequest:
    with db.session_factory() as s:
        row = s.get(LeaveRequest, request_id)
        s.expunge(row)
        return row


def claim(db: Database, request_id: int = 1) -> ClaimRequest:
    with db.session_factory() as s:
        row = s.get(ClaimRequest, request_id)
        s.expunge(row)
        return row


def audit_rows(db: Database, entity: str, request_id: int, prefix: str = "request.") -> list:
    with db.session_factory() as s:
        return list(
            s.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.entity_type == entity,
                    AuditEvent.entity_id == request_id,
                    AuditEvent.event_type.startswith(prefix),
                )
                .order_by(AuditEvent.id)
            )
        )


# ---- outcomes (A-08) -----------------------------------------------------------------------
def test_approve_leave_with_a_note(seeded: Database, cathy: TestClient) -> None:
    """A-08"""
    response = decide(cathy, "leave", 1, "approve", "Enjoy the trip.")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"request_type", "id", "status", "reviewed_at"}
    assert (body["request_type"], body["id"], body["status"]) == ("leave", 1, "approved")
    assert body["reviewed_at"].endswith("Z")
    row = leave(seeded)
    assert row.status == S.APPROVED
    assert row.reviewed_by_user_id == get_user(seeded, CATHY).id
    assert row.reviewed_at is not None and row.reviewer_note == "Enjoy the trip."


def test_reject_claim_with_a_note(seeded: Database, eva: TestClient) -> None:
    """A-08"""
    response = decide(eva, "claim", 2, "reject", "Over the training budget.")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    row = claim(seeded, 2)
    assert row.status == S.REJECTED and row.reviewer_note == "Over the training budget."
    assert row.reviewed_by_user_id == get_user(seeded, "eva.cheung@example.com").id


@pytest.mark.parametrize("decision, status", [("approve", "approved"), ("reject", "rejected")])
def test_the_note_is_optional_for_both_decisions(
    decision: str, status: str, seeded: Database, cathy: TestClient
) -> None:
    """A-08: no note key, or an explicit null."""
    assert decide(cathy, "leave", 1, decision).json()["status"] == status
    assert leave(seeded).reviewer_note is None
    other = decide(cathy, "leave", 1, decision, None)
    assert other.status_code == 409  # already decided; the null note was valid input


def test_reject_without_a_note_with_null(seeded: Database, cathy: TestClient) -> None:
    """A-08"""
    assert decide(cathy, "leave", 1, "reject", None).status_code == 200
    assert leave(seeded).status == S.REJECTED and leave(seeded).reviewer_note is None


@pytest.mark.parametrize(
    "sent, stored",
    [("  Looks fine.  ", "Looks fine."), ("", None), ("   \n\t ", None), ("x" * 500, "x" * 500)],
)
def test_note_is_trimmed_and_empty_becomes_null(
    sent: str, stored: str | None, seeded: Database, cathy: TestClient
) -> None:
    """A-08"""
    assert decide(cathy, "leave", 1, "approve", sent).status_code == 200
    assert leave(seeded).reviewer_note == stored


def test_a_note_of_501_characters_is_refused(seeded: Database, cathy: TestClient) -> None:
    """A-09: 422 and nothing changes."""
    response = decide(cathy, "leave", 1, "approve", "x" * 501)
    assert response.status_code == 422
    assert leave(seeded).status == S.PENDING_APPROVAL


def test_trailing_spaces_do_not_count_towards_the_limit(
    seeded: Database, cathy: TestClient
) -> None:
    """A-09: 500 real characters plus padding is accepted (the note is trimmed first)."""
    assert decide(cathy, "leave", 1, "approve", "  " + "y" * 500 + "  ").status_code == 200
    assert leave(seeded).reviewer_note == "y" * 500


@pytest.mark.parametrize("bad", ["maybe", "APPROVE", "", None, 1, True, ["approve"]])
def test_an_invalid_decision_is_422(bad: object, seeded: Database, cathy: TestClient) -> None:
    """A-09"""
    response = cathy.post("/api/approvals/leave/1/decision", json={"decision": bad})
    assert response.status_code == 422
    assert leave(seeded).status == S.PENDING_APPROVAL


def test_missing_body_fields_and_bad_note_types_are_422(cathy: TestClient) -> None:
    """A-09"""
    url = "/api/approvals/leave/1/decision"
    assert cathy.post(url, json={}).status_code == 422
    assert cathy.post(url, json={"note": "hi"}).status_code == 422
    assert cathy.post(url, json={"decision": "approve", "note": 5}).status_code == 422
    assert cathy.post(url, json={"decision": "approve", "note": ["x"]}).status_code == 422
    assert cathy.post(url, content=b"not json").status_code == 422


def test_a_post_without_the_csrf_header_is_refused(seeded: Database, cathy: TestClient) -> None:
    """A-09: same CSRF rule as every other POST."""
    cathy.headers.pop("X-Requested-With")
    response = cathy.post("/api/approvals/leave/1/decision", json={"decision": "approve"})
    assert response.status_code == 403 and response.json() == {"detail": "CSRF check failed"}
    assert leave(seeded).status == S.PENDING_APPROVAL


# ---- errors (A-10) -------------------------------------------------------------------------
def test_a_second_decision_is_409_and_keeps_the_first(seeded: Database, cathy: TestClient) -> None:
    """A-10"""
    assert decide(cathy, "leave", 1, "approve", "first").status_code == 200
    second = decide(cathy, "leave", 1, "reject", "second")
    assert second.status_code == 409
    row = leave(seeded)
    assert row.status == S.APPROVED and row.reviewer_note == "first"
    assert len(audit_rows(seeded, "leave_request", 1, "request.approved")) == 1
    assert audit_rows(seeded, "leave_request", 1, "request.rejected") == []


def test_a_cancelled_request_can_no_longer_be_decided(seeded: Database, cathy: TestClient) -> None:
    """A-10: the requester cancelled meanwhile: assigned to the caller but no longer pending."""
    with seeded.session_factory() as s:
        s.get(LeaveRequest, 1).status = S.CANCELLED
        s.commit()
    assert decide(cathy, "leave", 1, "approve").status_code == 409
    assert leave(seeded).status == S.CANCELLED


def test_not_found_cases_share_one_body(
    cathy: TestClient, helen: TestClient, eva: TestClient
) -> None:
    """A-10: unknown id, not assigned, wrong queue type, unknown type."""
    for response in [
        decide(cathy, "leave", 9999, "approve"),
        decide(cathy, "leave", 2, "approve"),  # Daniel's, assigned to Helen
        decide(helen, "leave", 1, "approve"),  # Amy's, assigned to Cathy
        decide(cathy, "claim", 1, "approve"),  # a claim, but Cathy decides leave
        decide(eva, "leave", 1, "approve"),  # a leave, but Eva decides claims
        decide(cathy, "travel", 1, "approve"),
    ]:
        assert response.status_code == 404 and response.json() == NOT_FOUND


def test_wrong_role_is_403(amy: TestClient, ben: TestClient, seeded: Database) -> None:
    """A-10: employees cannot decide, not even their own request."""
    assert decide(amy, "leave", 1, "approve").status_code == 403
    assert decide(ben, "leave", 1, "approve").status_code == 403
    assert leave(seeded).status == S.PENDING_APPROVAL


def test_self_approval_is_impossible(seeded: Database, cathy: TestClient) -> None:
    """A-10: a (bad-data) request assigned to its own employee cannot be decided by them."""
    me = get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        row = add_leave(s, me, "2026-11-02", status=S.PENDING_APPROVAL, approver=me)
        s.commit()
        rid = row.id
    response = decide(cathy, "leave", rid, "approve")
    assert response.status_code == 404
    assert leave(seeded, rid).status == S.PENDING_APPROVAL
    assert audit_rows(seeded, "leave_request", rid) == []


def test_over_the_limit_requests_can_still_be_approved(
    seeded: Database, helen: TestClient, eva: TestClient
) -> None:
    """A-11: limits are shown, never blocking."""
    assert decide(helen, "leave", 2, "approve", "Approved over balance.").status_code == 200
    assert leave(seeded, 2).status == S.APPROVED
    assert decide(eva, "claim", 2, "approve").status_code == 200
    assert claim(seeded, 2).status == S.APPROVED


def test_a_failure_while_writing_rolls_everything_back(
    seeded: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-11: the status change, audit row and notifications are one transaction."""

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit store down")

    monkeypatch.setattr(service, "record_audit", boom)
    cathy_user = get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        before = s.query(Notification).count()
    with seeded.session_factory() as s, pytest.raises(RuntimeError):
        service.decide(s, cathy_user, service.parse_request_type("leave"), 1, "approve", "n")
    assert leave(seeded).status == S.PENDING_APPROVAL
    assert leave(seeded).reviewer_note is None and leave(seeded).reviewed_at is None
    with seeded.session_factory() as s:
        assert s.query(Notification).count() == before


def test_no_audit_row_is_created_for_refused_decisions(seeded: Database, cathy: TestClient) -> None:
    """A-11"""
    decide(cathy, "leave", 2, "approve")  # 404
    decide(cathy, "leave", 1, "maybe")  # 422
    decide(cathy, "leave", 1, "approve", "x" * 501)  # 422
    assert audit_rows(seeded, "leave_request", 1, "request.approved") == []
    assert audit_rows(seeded, "leave_request", 1, "request.rejected") == []
    assert audit_rows(seeded, "leave_request", 2, "request.approved") == []
