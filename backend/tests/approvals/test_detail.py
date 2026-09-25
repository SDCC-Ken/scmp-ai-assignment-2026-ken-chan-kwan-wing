"""GET /api/approvals/{type}/{id}: contents, limits, warnings, 404 cases (A-05..A-07)."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.db.session import Database
from app.domain.enums import DayPart, LeaveType, RequestStatus, RequestType
from tests.approvals.conftest import CATHY, HELEN, add_attachment
from tests.conftest import get_user
from tests.org.helpers import add_claim, add_leave

S = RequestStatus
NOT_FOUND = {"detail": "Request not found"}


# ---- contents (A-05) -----------------------------------------------------------------------
def test_leave_detail_matches_the_seed_numbers(cathy: TestClient) -> None:
    """A-05: exact shape; balance excludes the request itself; team overlap shows Ben."""
    response = cathy.get("/api/approvals/leave/1")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "request": {
            "request_type": "leave",
            "id": 1,
            "status": "pending_approval",
            "submitted_at": "2026-09-24T03:00:00Z",
            "employee": {"id": 1, "display_name": "Amy Lau", "department": "IT"},
            "fields": [
                {"key": "leave_type", "label": "Leave type", "value": "Annual"},
                {"key": "start_date", "label": "Start", "value": "Fri 2026-10-09"},
                {"key": "end_date", "label": "End", "value": "Wed 2026-10-14"},
                {"key": "working_days", "label": "Working days", "value": "4"},
            ],
            "attachments": [],
            "external_reference_id": "mock-ref-leave-0001",
        },
        "limits": {
            "leave_balance": {
                "leave_type": "annual",
                "year": 2026,
                "entitled_days": 15.0,
                "approved_days": 1.5,
                "pending_other_days": 0.0,
                "requested_days": 4.0,
                "remaining_after_days": 9.5,
                "over_limit": False,
            },
            "department_budget": None,
        },
        "team_overlap": [
            {
                "employee": "Ben Chow",
                "leave_type": "annual",
                "start_date": "2026-10-12",
                "end_date": "2026-10-13",
                "status": "approved",
                "working_days": 2.0,
            }
        ],
        "warnings": [],
    }
    assert "@" not in response.text  # never the employee's e-mail


def test_over_balance_leave_warns_but_is_still_shown(helen: TestClient) -> None:
    """A-05: Daniel has 10 approved days of 15 and asks for 6: over by 1 day."""
    body = helen.get("/api/approvals/leave/2").json()
    balance = body["limits"]["leave_balance"]
    assert (balance["entitled_days"], balance["approved_days"], balance["requested_days"]) == (
        15.0,
        10.0,
        6.0,
    )
    assert balance["remaining_after_days"] == -1.0 and balance["over_limit"] is True
    assert body["warnings"] == ["Over the annual leave balance by 1 day. You decide."]
    assert body["team_overlap"] == []


def test_over_budget_claim_detail(eva: TestClient) -> None:
    """A-05: HR budget 30,000.00, 22,141.05 approved, 9,800.00 requested."""
    body = eva.get("/api/approvals/claim/2").json()
    assert body["request"]["fields"] == [
        {"key": "claim_type", "label": "Claim type", "value": "Training"},
        {"key": "amount", "label": "Amount", "value": "HKD 9,800.00"},
        {"key": "receipt_date", "label": "Receipt date", "value": "Sun 2026-09-20"},
    ]
    assert body["limits"] == {
        "leave_balance": None,
        "department_budget": {
            "department": "HR",
            "year": 2026,
            "limit_amount": "30000.00",
            "approved_amount": "22141.05",
            "pending_other_amount": "0.00",
            "requested_amount": "9800.00",
            "remaining_after_amount": "-1941.05",
            "over_limit": True,
            "currency": "HKD",
        },
    }
    assert body["team_overlap"] == []
    assert body["warnings"] == [
        "This claim takes HR over its annual claim limit by HKD 1,941.05. You decide."
    ]


def test_claim_within_budget_has_no_warning_and_counts_other_pending(
    seeded: Database, eva: TestClient
) -> None:
    """A-05: another pending IT claim shows as ``pending_other``, not deducted."""
    ben, eva_user = (
        get_user(seeded, "ben.chow@example.com"),
        get_user(seeded, "eva.cheung@example.com"),
    )
    with seeded.session_factory() as s:
        add_claim(s, ben, "300.00", "2026-09-10", status=S.PENDING_APPROVAL, approver=eva_user)
        s.commit()
    budget = eva.get("/api/approvals/claim/1").json()["limits"]["department_budget"]
    assert budget["pending_other_amount"] == "300.00"
    assert budget["requested_amount"] == "268.50"
    assert budget["approved_amount"] == "2644.90"
    assert budget["remaining_after_amount"] == "57086.60"  # 60000 - 2644.90 - 268.50
    assert budget["over_limit"] is False
    assert eva.get("/api/approvals/claim/1").json()["warnings"] == []


def test_personal_and_unpaid_leave_have_no_balance(seeded: Database, cathy: TestClient) -> None:
    """A-05: leave_balance is null and there is no over-limit warning, however long."""
    amy, cathy_user = get_user(seeded, "amy.lau@example.com"), get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        personal = add_leave(
            s, amy, "2026-11-02", "2026-11-13", status=S.PENDING_APPROVAL, approver=cathy_user,
            leave_type=LeaveType.PERSONAL, days="10",
        )  # fmt: skip
        unpaid = add_leave(
            s, amy, "2026-12-01", status=S.PENDING_APPROVAL, approver=cathy_user,
            leave_type=LeaveType.UNPAID, days="1",
        )  # fmt: skip
        s.commit()
        pid, uid = personal.id, unpaid.id
    for rid in (pid, uid):
        body = cathy.get(f"/api/approvals/leave/{rid}").json()
        assert body["limits"] == {"leave_balance": None, "department_budget": None}
        assert body["warnings"] == []


def test_sick_leave_over_the_balance_warns_with_the_type(
    seeded: Database, cathy: TestClient
) -> None:
    """A-05"""
    amy, cathy_user = get_user(seeded, "amy.lau@example.com"), get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        sick = add_leave(
            s, amy, "2026-11-02", status=S.PENDING_APPROVAL, approver=cathy_user,
            leave_type=LeaveType.SICK, days="11.5",
        )  # fmt: skip
        s.commit()
        rid = sick.id
    body = cathy.get(f"/api/approvals/leave/{rid}").json()
    assert body["warnings"] == ["Over the sick leave balance by 1.5 days. You decide."]
    assert body["limits"]["leave_balance"]["leave_type"] == "sick"


def test_half_day_parts_are_shown_like_the_chat_card(seeded: Database, cathy: TestClient) -> None:
    """A-05: day parts and working days use the confirmation-card wording."""
    amy, cathy_user = get_user(seeded, "amy.lau@example.com"), get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        row = add_leave(
            s, amy, "2026-11-02", status=S.PENDING_APPROVAL, approver=cathy_user, days="0.5"
        )
        row.start_day_part = DayPart.PM
        row.end_day_part = DayPart.PM
        s.commit()
        rid = row.id
    fields = {
        f["key"]: f["value"]
        for f in cathy.get(f"/api/approvals/leave/{rid}").json()["request"]["fields"]
    }
    assert fields["start_date"] == "Mon 2026-11-02 (afternoon only)"
    assert fields["working_days"] == "0.5"


def test_attachments_are_listed_with_download_urls(
    seeded: Database, upload_dir: Path, cathy: TestClient
) -> None:
    """A-05: AttachmentInfo with url; the approver can open each one."""
    first = add_attachment(seeded, upload_dir, "amy.lau@example.com", RequestType.LEAVE, 1, "a.png")
    second = add_attachment(
        seeded, upload_dir, "amy.lau@example.com", RequestType.LEAVE, 1, "b.png"
    )
    files = cathy.get("/api/approvals/leave/1").json()["request"]["attachments"]
    assert [f["id"] for f in files] == [first, second]
    assert files[0]["url"] == f"/api/attachments/{first}"
    assert files[0]["filename"] == "a.png" and files[0]["content_type"] == "image/png"
    assert files[0]["size_bytes"] > 0 and files[0]["created_at"].endswith("Z")
    assert cathy.get(files[0]["url"]).status_code == 200


def test_team_overlap_counts_pending_colleagues_but_not_other_departments(
    seeded: Database, cathy: TestClient
) -> None:
    """A-06: a pending IT colleague's leave counts; an HR colleague's does not."""
    ben, cathy_user, daniel, helen_user = (
        get_user(seeded, "ben.chow@example.com"),
        get_user(seeded, CATHY),
        get_user(seeded, "daniel.wong@example.com"),
        get_user(seeded, HELEN),
    )
    with seeded.session_factory() as s:
        add_leave(s, ben, "2026-10-09", status=S.PENDING_APPROVAL, approver=cathy_user)
        add_leave(s, daniel, "2026-10-09", status=S.PENDING_APPROVAL, approver=helen_user)
        s.commit()
    overlap = cathy.get("/api/approvals/leave/1").json()["team_overlap"]
    assert [(o["employee"], o["status"], o["start_date"]) for o in overlap] == [
        ("Ben Chow", "pending_approval", "2026-10-09"),
        ("Ben Chow", "approved", "2026-10-12"),
    ]
    (item,) = [i for i in cathy.get("/api/approvals").json()["items"] if i["id"] == 1]
    assert item["flags"]["team_overlap_count"] == 2


# ---- 404 cases (A-07) ----------------------------------------------------------------------
def test_not_found_cases_share_one_body(
    seeded: Database, cathy: TestClient, helen: TestClient, eva: TestClient
) -> None:
    """A-07: unknown id, not assigned, wrong type, unknown type: identical 404."""
    responses = [
        cathy.get("/api/approvals/leave/9999"),  # unknown id
        cathy.get("/api/approvals/leave/2"),  # Daniel's, assigned to Helen
        helen.get("/api/approvals/leave/1"),  # Amy's, assigned to Cathy
        cathy.get("/api/approvals/claim/1"),  # wrong queue type for an HR approver
        eva.get("/api/approvals/leave/1"),  # wrong queue type for the Finance approver
        cathy.get("/api/approvals/travel/1"),  # unknown type
        eva.get("/api/approvals/claim/9999"),
    ]
    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json() == NOT_FOUND


def test_not_pending_is_404_for_detail(seeded: Database, cathy: TestClient) -> None:
    """A-07: draft / decided / cancelled requests of the assigned approver are not inspectable."""
    amy, cathy_user = get_user(seeded, "amy.lau@example.com"), get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        rows = [
            add_leave(s, amy, "2026-11-02", status=status, approver=cathy_user)
            for status in (S.DRAFT, S.APPROVED, S.REJECTED, S.CANCELLED, S.SUBMISSION_FAILED)
        ]
        s.commit()
        rids = [r.id for r in rows]
    for rid in rids:
        response = cathy.get(f"/api/approvals/leave/{rid}")
        assert response.status_code == 404 and response.json() == NOT_FOUND


def test_own_request_is_not_inspectable(seeded: Database, cathy: TestClient) -> None:
    """A-07: a request assigned to its own employee looks nonexistent."""
    me = get_user(seeded, CATHY)
    with seeded.session_factory() as s:
        row = add_leave(s, me, "2026-11-02", status=S.PENDING_APPROVAL, approver=me)
        s.commit()
        rid = row.id
    assert cathy.get(f"/api/approvals/leave/{rid}").status_code == 404
