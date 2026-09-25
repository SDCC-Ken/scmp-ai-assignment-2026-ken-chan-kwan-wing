"""What a decision leaves behind: the audit row and the notifications (A-12..A-14)."""

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AuditEvent, Notification
from app.db.session import Database
from app.domain.enums import RequestType
from app.services.audit import create_notification
from tests.approvals.conftest import CATHY, EVA, HELEN, decide
from tests.conftest import get_user

NOTE = "Zebra-note-with-unique-text: enjoy the trip."


def decision_audit(db: Database, entity: str, request_id: int, event_type: str) -> AuditEvent:
    with db.session_factory() as s:
        return s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == entity,
                AuditEvent.entity_id == request_id,
                AuditEvent.event_type == event_type,
            )
        ).one()


def notifications(db: Database, email: str) -> list[Notification]:
    user = get_user(db, email)
    with db.session_factory() as s:
        return list(
            s.scalars(
                select(Notification)
                .where(Notification.recipient_user_id == user.id)
                .order_by(Notification.id)
            )
        )


# ---- audit (A-12) --------------------------------------------------------------------------
def test_approving_a_leave_writes_one_audit_row_with_the_numbers(
    seeded: Database, cathy: TestClient
) -> None:
    """A-12"""
    assert decide(cathy, "leave", 1, "approve", NOTE).status_code == 200
    event = decision_audit(seeded, "leave_request", 1, "request.approved")
    assert event.actor_user_id == get_user(seeded, CATHY).id
    assert (event.from_status, event.to_status) == ("pending_approval", "approved")
    assert event.metadata_json == {
        "note_present": True,
        "over_limit": False,
        "snapshot": {
            "kind": "leave_balance",
            "leave_type": "annual",
            "year": 2026,
            "entitled": "15.0",
            "approved": "1.5",
            "pending_other": "0.0",
            "requested": "4.0",
            "remaining_after": "9.5",
        },
        "team_overlap_count": 1,
        "employee_id": get_user(seeded, "amy.lau@example.com").id,
    }
    with seeded.session_factory() as s:  # exactly one decision row for the request
        rows = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "leave_request",
                AuditEvent.entity_id == 1,
                AuditEvent.event_type.in_(["request.approved", "request.rejected"]),
            )
        ).all()
        assert len(rows) == 1


def test_rejecting_an_over_budget_claim_audits_the_budget_snapshot(
    seeded: Database, eva: TestClient
) -> None:
    """A-12"""
    assert decide(eva, "claim", 2, "reject").status_code == 200
    event = decision_audit(seeded, "claim_request", 2, "request.rejected")
    assert event.actor_user_id == get_user(seeded, EVA).id
    assert (event.from_status, event.to_status) == ("pending_approval", "rejected")
    assert event.metadata_json == {
        "note_present": False,
        "over_limit": True,
        "snapshot": {
            "kind": "department_budget",
            "department": "HR",
            "year": 2026,
            "currency": "HKD",
            "limit": "30000.00",
            "approved": "22141.05",
            "pending_other": "0.00",
            "requested": "9800.00",
            "remaining_after": "-1941.05",
        },
        "employee_id": get_user(seeded, "daniel.wong@example.com").id,
    }


def test_over_balance_leave_is_flagged_in_the_audit(seeded: Database, helen: TestClient) -> None:
    """A-12"""
    assert decide(helen, "leave", 2, "approve").status_code == 200
    metadata = decision_audit(seeded, "leave_request", 2, "request.approved").metadata_json
    assert metadata["over_limit"] is True and metadata["team_overlap_count"] == 0
    assert metadata["snapshot"]["remaining_after"] == "-1.0"


def test_the_note_text_is_never_in_the_audit_metadata(seeded: Database, cathy: TestClient) -> None:
    """A-12: only ``note_present``; the text lives on the request."""
    decide(cathy, "leave", 1, "reject", NOTE)
    event = decision_audit(seeded, "leave_request", 1, "request.rejected")
    assert "Zebra" not in json.dumps(event.metadata_json)
    assert event.metadata_json["note_present"] is True
    assert "reviewer_note" not in event.metadata_json and "note" not in event.metadata_json


def test_no_note_means_note_present_false(seeded: Database, cathy: TestClient) -> None:
    """A-12"""
    decide(cathy, "leave", 1, "approve", "   ")
    event = decision_audit(seeded, "leave_request", 1, "request.approved")
    assert event.metadata_json["note_present"] is False


def test_audit_time_matches_the_reviewed_time(seeded: Database, cathy: TestClient) -> None:
    """A-12"""
    body = decide(cathy, "leave", 1, "approve").json()
    event = decision_audit(seeded, "leave_request", 1, "request.approved")
    stamp = event.created_at.replace(tzinfo=event.created_at.tzinfo or UTC)
    assert stamp.strftime("%Y-%m-%dT%H:%M:%SZ") == body["reviewed_at"]
    assert stamp <= datetime.now(UTC)


# ---- notifications created (A-13, A-14) ----------------------------------------------------
def test_the_requester_is_notified_of_the_decision(seeded: Database, cathy: TestClient) -> None:
    """A-13"""
    before = len(notifications(seeded, "amy.lau@example.com"))
    decide(cathy, "leave", 1, "approve", NOTE)
    rows = notifications(seeded, "amy.lau@example.com")
    assert len(rows) == before + 1
    new = rows[-1]
    assert (new.event_type, new.request_type, new.request_id) == (
        "request.approved",
        RequestType.LEAVE,
        1,
    )
    assert new.read_at is None


def test_a_rejection_notifies_with_the_rejected_event(seeded: Database, eva: TestClient) -> None:
    """A-13"""
    decide(eva, "claim", 1, "reject")
    assert notifications(seeded, "amy.lau@example.com")[-1].event_type == "request.rejected"


def test_the_approvers_own_new_request_notifications_are_marked_read(
    seeded: Database, cathy: TestClient, helen: TestClient
) -> None:
    """A-14: Cathy's unread ``request.submitted`` for leave 1 is read after she decides;
    Helen's for leave 2 is untouched."""
    submitted = [n for n in notifications(seeded, CATHY) if n.event_type == "request.submitted"]
    assert [n.read_at for n in submitted] == [None]
    decide(cathy, "leave", 1, "approve")
    submitted = [n for n in notifications(seeded, CATHY) if n.event_type == "request.submitted"]
    assert all(n.read_at is not None for n in submitted)
    (helens,) = [n for n in notifications(seeded, HELEN) if n.event_type == "request.submitted"]
    assert helens.read_at is None


def test_updated_notifications_of_that_request_are_marked_read_too(
    seeded: Database, cathy: TestClient
) -> None:
    """A-14: ``request.updated`` for the request and a submitted one for another request."""
    cathy_user = get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        create_notification(
            s,
            recipient_user_id=cathy_user.id,
            event_type="request.updated",
            request_type=RequestType.LEAVE,
            request_id=1,
        )
        create_notification(
            s,
            recipient_user_id=cathy_user.id,
            event_type="request.submitted",
            request_type=RequestType.LEAVE,
            request_id=2,  # another request: must stay unread
        )
        s.commit()
    decide(cathy, "leave", 1, "reject", "no")
    by_key = {(n.event_type, n.request_id): n.read_at for n in notifications(seeded, CATHY)}
    assert by_key[("request.updated", 1)] is not None
    assert by_key[("request.submitted", 1)] is not None
    assert by_key[("request.submitted", 2)] is None


def test_notifications_are_not_created_when_the_decision_is_refused(
    seeded: Database, cathy: TestClient
) -> None:
    """A-13"""
    before = len(notifications(seeded, "amy.lau@example.com"))
    decide(cathy, "leave", 1, "approve")
    decide(cathy, "leave", 1, "reject")  # 409
    assert len(notifications(seeded, "amy.lau@example.com")) == before + 1
