"""GET/POST /api/notifications: list, read, read-all and text composition (A-16..A-20)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.models import LeaveRequest
from app.db.session import Database
from app.domain.enums import RequestStatus, RequestType
from app.services.audit import create_notification
from tests.approvals.conftest import AMY, BEN, CATHY, DANIEL, EVA, HELEN, decide
from tests.conftest import get_user

LEAVE, CLAIM = RequestType.LEAVE, RequestType.CLAIM
BASE = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def add(
    db: Database, email: str, event: str, rtype: RequestType, rid: int, minutes: int = 0
) -> None:
    user = get_user(db, email)
    with db.session_factory() as s:
        create_notification(
            s,
            recipient_user_id=user.id,
            event_type=event,
            request_type=rtype,
            request_id=rid,
            created_at=BASE + timedelta(minutes=minutes),
        )
        s.commit()


def items(client: TestClient, **params: object) -> list[dict]:
    response = client.get("/api/notifications", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


# ---- the seed's rows (A-16) ----------------------------------------------------------------
def test_seed_notifications_compose_correctly(
    ben: TestClient, cathy: TestClient, helen: TestClient, eva: TestClient
) -> None:
    """A-16: every seeded row reads well; the approver's link exists only for pending items."""
    body = ben.get("/api/notifications").json()
    assert body["unread_count"] == 2
    assert [(n["title"], n["body"], n["link"]) for n in body["items"]] == [
        (
            "Your leave request #4 was rejected",
            "Rejected by Cathy Ng. Note: Team is short-staffed that week; "
            "please pick another date.",
            None,
        ),
        (
            "Your claim #4 was rejected",
            "Rejected by Eva Cheung. Note: Receipt is missing the vendor name; "
            "please resubmit with a full receipt.",
            None,
        ),
    ]
    assert [n["read_at"] for n in body["items"]] == [None, None]

    body = cathy.get("/api/notifications").json()
    assert body["unread_count"] == 1
    assert [(n["event_type"], n["title"], n["link"]) for n in body["items"]] == [
        ("request.submitted", "New leave request from Amy Lau", "/approvals/leave/1"),
        ("request.approved", "Your leave request #3 was approved", None),
        ("request.approved", "Your claim #3 was approved", None),
    ]
    assert (
        body["items"][0]["body"]
        == "Annual leave, Fri 2026-10-09 to Wed 2026-10-14 (4 working days)"
    )
    assert body["items"][1]["body"].startswith(
        "Approved by Helen Yeung. Note: Approved. Please hand over"
    )
    assert body["items"][1]["read_at"] is not None

    (helen_item,) = helen.get("/api/notifications").json()["items"]
    assert helen_item["title"] == "New leave request from Daniel Wong"
    assert helen_item["link"] == "/approvals/leave/2" and helen_item["request_id"] == 2

    eva_items = eva.get("/api/notifications").json()["items"]
    assert [(n["title"], n["link"]) for n in eva_items] == [
        ("New claim from Amy Lau", "/approvals/claim/1"),
        ("New claim from Daniel Wong", "/approvals/claim/2"),
    ]
    assert eva_items[0]["body"] == "Travel claim, HKD 268.50, receipt 2026-09-22"


def test_item_shape_and_no_email_addresses(cathy: TestClient, amy: TestClient) -> None:
    """A-16: exact keys, plain text, no e-mail address, no attachments."""
    response = cathy.get("/api/notifications")
    assert set(response.json()) == {"items", "unread_count"}
    assert set(response.json()["items"][0]) == {
        "id",
        "event_type",
        "title",
        "body",
        "request_type",
        "request_id",
        "read_at",
        "created_at",
        "link",
    }
    assert "@" not in response.text and "attachment" not in response.text.lower()
    assert amy.get("/api/notifications").json() == {"items": [], "unread_count": 0}


# ---- list order, limit, unread count (A-17) ------------------------------------------------
def test_newest_first_default_limit_and_bounds(seeded: Database, amy: TestClient) -> None:
    """A-17: default 20, 1..50 accepted, anything else 422; unread_count covers all rows."""
    for i in range(25):
        add(seeded, AMY, "request.approved", LEAVE, 1, minutes=i)
    listed = items(amy)
    assert len(listed) == 20
    stamps = [n["created_at"] for n in listed]
    assert stamps == sorted(stamps, reverse=True)
    assert listed[0]["created_at"] == "2026-09-01T03:24:00Z"
    assert len(items(amy, limit=1)) == 1 and len(items(amy, limit=50)) == 25
    assert amy.get("/api/notifications", params={"limit": 5}).json()["unread_count"] == 25
    for bad in (0, 51, -1, "abc"):
        assert amy.get("/api/notifications", params={"limit": bad}).status_code == 422


def test_equal_timestamps_are_ordered_by_id_descending(seeded: Database, amy: TestClient) -> None:
    """A-17"""
    add(seeded, AMY, "request.approved", LEAVE, 1)
    add(seeded, AMY, "request.rejected", LEAVE, 1)
    assert [n["event_type"] for n in items(amy)] == ["request.rejected", "request.approved"]


# ---- read, read-all (A-18) -----------------------------------------------------------------
def test_mark_one_read_is_idempotent(seeded: Database, cathy: TestClient) -> None:
    """A-18"""
    first = items(cathy)[0]
    assert first["read_at"] is None
    assert cathy.post(f"/api/notifications/{first['id']}/read").status_code == 204
    after = items(cathy)[0]
    assert after["read_at"] is not None
    assert cathy.get("/api/notifications").json()["unread_count"] == 0
    assert cathy.post(f"/api/notifications/{first['id']}/read").status_code == 204
    assert items(cathy)[0]["read_at"] == after["read_at"]  # the first read time is kept


def test_someone_elses_or_unknown_id_is_404(cathy: TestClient, helen: TestClient) -> None:
    """A-18: one body; the other person's notification stays unread."""
    theirs = items(helen)[0]["id"]
    for nid in (theirs, 99999):
        response = cathy.post(f"/api/notifications/{nid}/read")
        assert response.status_code == 404
        assert response.json() == {"detail": "Notification not found"}
    assert items(helen)[0]["read_at"] is None


def test_read_all_only_touches_the_callers_rows(
    seeded: Database, cathy: TestClient, helen: TestClient, eva: TestClient
) -> None:
    """A-18"""
    assert eva.post("/api/notifications/read-all").status_code == 204
    assert eva.get("/api/notifications").json()["unread_count"] == 0
    assert all(n["read_at"] is not None for n in items(eva))
    assert helen.get("/api/notifications").json()["unread_count"] == 1
    assert cathy.get("/api/notifications").json()["unread_count"] == 1
    assert eva.post("/api/notifications/read-all").status_code == 204  # nothing left: still 204


def test_users_only_ever_see_their_own_notifications(
    amy: TestClient, ben: TestClient, daniel: TestClient
) -> None:
    """A-18"""
    assert items(amy) == [] and items(daniel) == []
    assert len(items(ben)) == 2


def test_unauthenticated_and_csrf(anon: TestClient, cathy: TestClient) -> None:
    """A-18"""
    assert anon.get("/api/notifications").status_code == 401
    assert anon.post("/api/notifications/1/read").status_code == 401
    assert anon.post("/api/notifications/read-all").status_code == 401
    cathy.headers.pop("X-Requested-With")
    assert cathy.post("/api/notifications/read-all").status_code == 403
    assert cathy.post("/api/notifications/1/read").status_code == 403
    assert cathy.get("/api/notifications").status_code == 200  # reads need no header


# ---- composition and links (A-19) ----------------------------------------------------------
def test_titles_and_bodies_for_every_event_type(seeded: Database, cathy: TestClient) -> None:
    """A-19: leave 1 (Amy, pending, Cathy assigned); the newest notification is first."""
    for minute, event in enumerate(
        ["request.updated", "request.cancelled", "request.approved", "request.rejected"]
    ):
        add(seeded, CATHY, event, LEAVE, 1, minutes=minute + 100_000)
    by_event = {
        n["event_type"]: n
        for n in items(cathy)
        if n["request_type"] == "leave" and n["request_id"] == 1
    }
    summary = "Annual leave, Fri 2026-10-09 to Wed 2026-10-14 (4 working days)"
    assert (by_event["request.updated"]["title"], by_event["request.updated"]["body"]) == (
        "Amy Lau changed leave request #1",
        summary,
    )
    assert (by_event["request.cancelled"]["title"], by_event["request.cancelled"]["body"]) == (
        "Amy Lau cancelled leave request #1",
        summary,
    )
    # a pending request has no reviewer yet: neutral decision text, no note
    assert by_event["request.approved"]["title"] == "Your leave request #1 was approved"
    assert by_event["request.approved"]["body"] == "Approved."
    assert by_event["request.rejected"]["title"] == "Your leave request #1 was rejected"
    assert by_event["request.rejected"]["body"] == "Rejected."


def test_claim_titles(seeded: Database, eva: TestClient) -> None:
    """A-19"""
    add(seeded, EVA, "request.updated", CLAIM, 1, minutes=100_000)
    add(seeded, EVA, "request.cancelled", CLAIM, 1, minutes=100_001)
    titles = [n["title"] for n in items(eva)][:2]
    assert titles == ["Amy Lau cancelled claim #1", "Amy Lau changed claim #1"]


def test_decision_notification_carries_the_approvers_name_and_note(
    amy: TestClient, cathy: TestClient, eva: TestClient
) -> None:
    """A-19: written when the decision is made; note only when present."""
    decide(cathy, "leave", 1, "approve", "Have a good one.")
    decide(eva, "claim", 1, "reject")
    listed = items(amy)
    by_title = {n["title"]: n["body"] for n in listed}
    assert by_title["Your leave request #1 was approved"] == (
        "Approved by Cathy Ng. Note: Have a good one."
    )
    assert by_title["Your claim #1 was rejected"] == "Rejected by Eva Cheung."
    assert all(n["link"] is None for n in listed)  # requesters get a dialog, not a link


def test_link_only_for_the_assigned_approver_while_pending(
    seeded: Database, cathy: TestClient, helen: TestClient, amy: TestClient
) -> None:
    """A-19"""
    add(seeded, HELEN, "request.submitted", LEAVE, 1)  # Helen is NOT assigned to leave 1
    add(seeded, AMY, "request.submitted", LEAVE, 1)  # the requester is not the approver
    assert [n["link"] for n in items(cathy) if n["request_id"] == 1] == ["/approvals/leave/1"]
    assert [n["link"] for n in items(helen) if n["request_id"] == 1] == [None]
    assert [n["link"] for n in items(amy)] == [None]
    decide(cathy, "leave", 1, "approve")  # decided: the link disappears
    assert [n["link"] for n in items(cathy) if n["request_id"] == 1] == [None]


def test_link_is_null_once_the_request_is_cancelled(seeded: Database, cathy: TestClient) -> None:
    """A-19"""
    with seeded.session_factory() as s:
        s.get(LeaveRequest, 1).status = RequestStatus.CANCELLED
        s.commit()
    add(seeded, CATHY, "request.cancelled", LEAVE, 1, minutes=100_000)
    assert all(n["link"] is None for n in items(cathy) if n["request_id"] == 1)


def test_wrong_role_never_gets_a_link_even_if_assigned(
    seeded: Database, daniel: TestClient
) -> None:
    """A-19: Daniel (an HR officer, employee role) holds a stray notification for leave 1;
    ``can_decide`` refuses him, so no link."""
    add(seeded, DANIEL, "request.submitted", LEAVE, 1)
    assert [n["link"] for n in items(daniel)] == [None]


def test_unknown_and_legacy_event_types_get_a_neutral_title(
    seeded: Database, amy: TestClient
) -> None:
    """A-20"""
    add(seeded, AMY, "request.reminder", LEAVE, 1)
    add(seeded, AMY, "something_old", CLAIM, 2, minutes=1)
    (claim_item, leave_item) = items(amy)
    assert (leave_item["title"], leave_item["body"]) == ("Update on leave request #1", "")
    assert (claim_item["title"], claim_item["body"]) == ("Update on claim #2", "")
    assert leave_item["event_type"] == "request.reminder"


@pytest.mark.parametrize("email", [AMY, BEN, CATHY, DANIEL, HELEN, EVA])
def test_every_users_list_is_plain_text_without_email(
    email: str, client_as, seeded: Database
) -> None:
    """A-20"""
    client = client_as(email)
    for n in items(client):
        assert "@" not in n["title"] + n["body"]
        assert n["title"] and isinstance(n["body"], str)
