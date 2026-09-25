"""GET /api/approvals: access matrix, scoping, flags and ordering (ids A-01..A-04)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.session import Database
from app.domain.enums import LeaveType, RequestStatus, RequestType
from tests.approvals.conftest import CATHY, HELEN, add_attachment, decide
from tests.conftest import get_user
from tests.org.helpers import add_leave

S = RequestStatus


def ids(response) -> list[tuple[str, int]]:
    return [(i["request_type"], i["id"]) for i in response.json()["items"]]


# ---- access matrix (A-01) ------------------------------------------------------------------
@pytest.mark.parametrize("who", ["amy", "ben", "daniel"])
def test_employees_have_no_queue(who: str, request: pytest.FixtureRequest) -> None:
    """A-01: employees (even Daniel, an HR officer) are refused."""
    client: TestClient = request.getfixturevalue(who)
    assert client.get("/api/approvals").status_code == 403
    assert client.get("/api/approvals/leave/1").status_code == 403
    assert (
        client.post("/api/approvals/leave/1/decision", json={"decision": "approve"}).status_code
        == 403
    )


def test_unauthenticated_is_401(anon: TestClient) -> None:
    """A-01"""
    assert anon.get("/api/approvals").status_code == 401
    assert anon.get("/api/approvals/leave/1").status_code == 401
    assert (
        anon.post("/api/approvals/leave/1/decision", json={"decision": "approve"}).status_code
        == 401
    )


def test_each_approver_sees_only_their_own_queue(
    cathy: TestClient, helen: TestClient, eva: TestClient
) -> None:
    """A-02: per-user assignment, not per-role; each queue holds one request type only."""
    assert ids(cathy.get("/api/approvals")) == [("leave", 1)]  # Amy's
    assert ids(helen.get("/api/approvals")) == [("leave", 2)]  # Daniel's
    assert ids(eva.get("/api/approvals")) == [("claim", 2), ("claim", 1)]  # all pending claims
    assert cathy.get("/api/approvals").json()["count"] == 1
    assert eva.get("/api/approvals").json()["count"] == 2


def test_helen_queue_can_be_empty_and_decided_items_disappear(
    cathy: TestClient, eva: TestClient
) -> None:
    """A-02: after a decision the request leaves the approver's list."""
    assert decide(cathy, "leave", 1, "approve").status_code == 200
    assert cathy.get("/api/approvals").json() == {"items": [], "count": 0}
    assert decide(eva, "claim", 1, "reject").status_code == 200
    assert ids(eva.get("/api/approvals")) == [("claim", 2)]


def test_only_pending_requests_appear(seeded: Database, cathy: TestClient) -> None:
    """A-02: draft, failed, cancelled, approved and rejected requests of Cathy's IT staff stay
    out of her queue (Ben has an old rejected one, Amy old approved ones)."""
    amy, cathy_user = get_user(seeded, "amy.lau@example.com"), get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        for status in (S.DRAFT, S.SUBMISSION_FAILED, S.CANCELLED, S.APPROVED, S.REJECTED):
            add_leave(s, amy, "2026-11-02", status=status, approver=cathy_user)
        s.commit()
    assert ids(cathy.get("/api/approvals")) == [("leave", 1)]


def test_a_request_assigned_to_someone_else_is_not_listed(
    seeded: Database, cathy: TestClient
) -> None:
    """A-02: Ben's pending leave assigned to Helen (not Cathy) is invisible to Cathy."""
    ben, helen = get_user(seeded, "ben.chow@example.com"), get_user(seeded, HELEN)
    with seeded.session_factory() as s:
        add_leave(s, ben, "2026-11-02", status=S.PENDING_APPROVAL, approver=helen)
        s.commit()
    assert ids(cathy.get("/api/approvals")) == [("leave", 1)]


def test_own_request_is_never_in_the_queue(seeded: Database, cathy: TestClient) -> None:
    """A-02: a (bad-data) request assigned to its own employee is not listed."""
    me = get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        add_leave(s, me, "2026-11-02", status=S.PENDING_APPROVAL, approver=me)
        s.commit()
    assert ids(cathy.get("/api/approvals")) == [("leave", 1)]


# ---- shape, flags, ordering (A-03) ---------------------------------------------------------
def test_list_item_shape_and_flags_for_the_seed_showcase(
    cathy: TestClient, helen: TestClient, eva: TestClient
) -> None:
    """A-03: exact ApprovalListItem shape; team overlap on Amy's leave, over-limit on Daniel's
    leave and claim, no e-mail addresses anywhere."""
    response = cathy.get("/api/approvals")
    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert item == {
        "request_type": "leave",
        "id": 1,
        "employee": {"id": 1, "display_name": "Amy Lau", "department": "IT"},
        "summary": "Annual leave, Fri 2026-10-09 to Wed 2026-10-14 (4 working days)",
        "submitted_at": "2026-09-24T03:00:00Z",
        "flags": {"over_limit": False, "team_overlap_count": 1, "has_attachments": False},
    }
    assert "@" not in response.text

    (leave2,) = helen.get("/api/approvals").json()["items"]
    assert leave2["employee"] == {"id": 4, "display_name": "Daniel Wong", "department": "HR"}
    assert leave2["summary"] == "Annual leave, Mon 2026-10-05 to Mon 2026-10-12 (6 working days)"
    assert leave2["flags"] == {
        "over_limit": True,
        "team_overlap_count": 0,
        "has_attachments": False,
    }

    claim2, claim1 = eva.get("/api/approvals").json()["items"]
    assert claim2["summary"] == "Training claim, HKD 9,800.00, receipt 2026-09-20"
    assert claim2["flags"]["over_limit"] is True  # HR: 22,141.05 approved + 9,800.00 > 30,000.00
    assert claim1["summary"] == "Travel claim, HKD 268.50, receipt 2026-09-22"
    assert claim1["flags"] == {
        "over_limit": False,
        "team_overlap_count": 0,
        "has_attachments": False,
    }


def test_claims_are_ordered_oldest_submitted_first(eva: TestClient) -> None:
    """A-03: claim 2 was submitted on 2026-09-21, claim 1 on 2026-09-23 (id order differs)."""
    items = eva.get("/api/approvals").json()["items"]
    assert [i["submitted_at"] for i in items] == ["2026-09-21T03:02:00Z", "2026-09-23T03:00:00Z"]


def test_leave_ordering_uses_submission_time_then_id(seeded: Database, cathy: TestClient) -> None:
    """A-03"""
    amy, cathy_user = get_user(seeded, "amy.lau@example.com"), get_user(seeded, CATHY)
    early = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    with seeded.session_factory() as s:
        a = add_leave(s, amy, "2026-11-02", status=S.PENDING_APPROVAL, approver=cathy_user)
        b = add_leave(s, amy, "2026-11-04", status=S.PENDING_APPROVAL, approver=cathy_user)
        a.submitted_at = early + timedelta(days=1)
        b.submitted_at = early
        s.commit()
        a_id, b_id = a.id, b.id
    assert ids(cathy.get("/api/approvals")) == [("leave", b_id), ("leave", a_id), ("leave", 1)]


def test_has_attachments_flag(seeded: Database, upload_dir, cathy: TestClient) -> None:
    """A-04"""
    add_attachment(seeded, upload_dir, "amy.lau@example.com", RequestType.LEAVE, 1)
    (item,) = cathy.get("/api/approvals").json()["items"]
    assert item["flags"]["has_attachments"] is True


def test_over_limit_flag_for_sick_and_personal_leave(seeded: Database, cathy: TestClient) -> None:
    """A-04: sick over its 10 days is flagged; personal leave has no balance and no flag."""
    amy, cathy_user = get_user(seeded, "amy.lau@example.com"), get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        sick = add_leave(
            s, amy, "2026-11-02", status=S.PENDING_APPROVAL, approver=cathy_user,
            leave_type=LeaveType.SICK, days="11",
        )  # fmt: skip
        personal = add_leave(
            s, amy, "2026-11-03", status=S.PENDING_APPROVAL, approver=cathy_user,
            leave_type=LeaveType.PERSONAL, days="30",
        )  # fmt: skip
        s.commit()
        sick_id, personal_id = sick.id, personal.id
    flags = {i["id"]: i["flags"]["over_limit"] for i in cathy.get("/api/approvals").json()["items"]}
    assert flags[sick_id] is True
    assert flags[personal_id] is False
    assert flags[1] is False


def test_queues_cover_the_configured_requesters(
    seeded: Database, cathy: TestClient, helen: TestClient
) -> None:
    """A-02: Cathy also gets Ben's leave; Helen gets Cathy's own leave (Cathy is a requester
    too) and Daniel's, never Cathy's IT queue."""
    ben, cathy_user, helen_user = (
        get_user(seeded, "ben.chow@example.com"),
        get_user(seeded, CATHY),
        get_user(seeded, HELEN),
    )
    with seeded.session_factory() as s:
        b = add_leave(s, ben, "2026-11-02", status=S.PENDING_APPROVAL, approver=cathy_user)
        c = add_leave(s, cathy_user, "2026-11-03", status=S.PENDING_APPROVAL, approver=helen_user)
        s.commit()
        b_id, c_id = b.id, c.id
    assert {i["id"] for i in cathy.get("/api/approvals").json()["items"]} == {1, b_id}
    assert {i["id"] for i in helen.get("/api/approvals").json()["items"]} == {2, c_id}
    names = {i["employee"]["display_name"] for i in helen.get("/api/approvals").json()["items"]}
    assert names == {"Daniel Wong", "Cathy Ng"}
