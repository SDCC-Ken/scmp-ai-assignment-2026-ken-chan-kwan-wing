"""A decision and the rest of the system: balances, budgets, chat, attachments (A-21..A-24)."""

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.models import LeaveRequest
from app.db.session import Database
from app.domain.enums import LeaveType, RequestStatus, RequestType
from app.services.balances import department_budget, leave_balance
from tests.approvals.conftest import AMY, add_attachment, decide
from tests.chat.helpers import (
    Chat,
    ScriptedLLM,
    cancel_turn,
    d,
    status_turn,
    text_of,
    ui_of,
    update_turn,
)
from tests.conftest import get_user

LEAVE, CLAIM = RequestType.LEAVE, RequestType.CLAIM


def annual(db: Database) -> tuple[Decimal, Decimal, Decimal]:
    """(approved, pending, remaining) annual days of Amy for 2026."""
    amy = get_user(db, AMY)
    with db.session_factory() as s:
        line = leave_balance(s, amy.id, 2026, LeaveType.ANNUAL)
        assert line is not None
        return line.approved_days, line.pending_days, line.remaining_days


def it_budget(db: Database) -> tuple[Decimal, Decimal]:
    """(approved, pending_other) amount of the IT department for 2026."""
    amy = get_user(db, AMY)
    with db.session_factory() as s:
        budget = department_budget(s, amy.department_id, 2026)
        assert budget is not None
        return budget.approved_amount, budget.pending_other_amount


# ---- balances and budgets (A-21) -----------------------------------------------------------
def test_approving_leave_deducts_the_days_and_rejecting_does_not(
    seeded: Database, cathy: TestClient
) -> None:
    """A-21: Amy has 1.5 approved and 4 pending (leave 1) before any decision."""
    assert annual(seeded) == (Decimal("1.5"), Decimal("4.0"), Decimal("13.5"))
    assert decide(cathy, "leave", 1, "approve").status_code == 200
    assert annual(seeded) == (Decimal("5.5"), Decimal("0.0"), Decimal("9.5"))


def test_rejecting_leave_leaves_the_balance_unchanged(seeded: Database, cathy: TestClient) -> None:
    """A-21"""
    assert decide(cathy, "leave", 1, "reject", "Team is short-staffed.").status_code == 200
    assert annual(seeded) == (Decimal("1.5"), Decimal("0.0"), Decimal("13.5"))  # pending drops out


def test_my_balances_endpoint_reflects_the_decision(
    seeded: Database,
    amy: TestClient,
    cathy: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-21: the employee's own balance screen after the approval."""
    monkeypatch.setattr("app.api.routes.me.today_hk", lambda: d("2026-09-25"))
    before = {b["leave_type"]: b for b in amy.get("/api/me/balances").json()["leave"]}
    assert before["annual"]["approved_days"] == 1.5 and before["annual"]["pending_days"] == 4.0
    decide(cathy, "leave", 1, "approve")
    after = {b["leave_type"]: b for b in amy.get("/api/me/balances").json()["leave"]}
    assert after["annual"]["approved_days"] == 5.5
    assert after["annual"]["pending_days"] == 0.0
    assert after["annual"]["remaining_days"] == 9.5
    assert after["sick"] == before["sick"]  # other types are untouched


def test_approving_a_claim_uses_up_the_department_budget(seeded: Database, eva: TestClient) -> None:
    """A-21: IT has 2,644.90 approved; Amy's claim of 268.50 is pending until decided."""
    assert it_budget(seeded) == (Decimal("2644.90"), Decimal("268.50"))
    assert decide(eva, "claim", 1, "approve").status_code == 200
    assert it_budget(seeded) == (Decimal("2913.40"), Decimal("0.00"))  # 2644.90 + 268.50


def test_rejecting_a_claim_leaves_the_department_budget_unchanged(
    seeded: Database, eva: TestClient
) -> None:
    """A-21"""
    assert decide(eva, "claim", 1, "reject", "No receipt.").status_code == 200
    assert it_budget(seeded) == (Decimal("2644.90"), Decimal("0.00"))  # only pending drops out


def test_an_approved_claim_over_the_limit_is_shown_as_over_for_the_next_one(
    seeded: Database, eva: TestClient
) -> None:
    """A-21: HR is at 22,141.05 of 30,000.00; approving Daniel's 9,800.00 claim takes the
    department to 31,941.05, and that is visible to the approver afterwards in the numbers."""
    daniel = get_user(seeded, "daniel.wong@example.com")
    assert decide(eva, "claim", 2, "approve").status_code == 200
    with seeded.session_factory() as s:
        budget = department_budget(s, daniel.department_id, 2026)
        assert budget.approved_amount == Decimal("31941.05")
        assert budget.remaining_amount == Decimal("-1941.05")


# ---- chat (A-22, A-23) ---------------------------------------------------------------------
def test_the_status_card_shows_the_reviewer_note_of_a_rejected_request(
    amy: TestClient, cathy: TestClient, llm: ScriptedLLM
) -> None:
    """A-22: the note typed by the approver reaches the requester's chat status card."""
    note = "Please pick another week; the team is short-staffed."
    assert decide(cathy, "leave", 1, "reject", note).status_code == 200
    llm.push(status_turn(request_type=LEAVE, request_id=1))
    response = Chat(amy).say("what happened to my leave?")
    item = ui_of(response)["requests"][0]
    assert item["status"] == "rejected" and item["status_label"] == "Rejected"
    assert item["reviewer_note"] == note
    assert item["reviewed_at"] is not None
    assert f"reviewer note: {note}" in text_of(response)


def test_an_approval_without_a_note_shows_no_note(
    amy: TestClient, cathy: TestClient, llm: ScriptedLLM
) -> None:
    """A-22"""
    decide(cathy, "leave", 1, "approve")
    llm.push(status_turn(request_type=LEAVE, request_id=1))
    item = ui_of(Chat(amy).say("status of my leave"))["requests"][0]
    assert item["status"] == "approved" and item["reviewer_note"] is None


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_the_employee_can_no_longer_cancel_a_decided_request(
    decision: str, seeded: Database, amy: TestClient, cathy: TestClient, llm: ScriptedLLM
) -> None:
    """A-23"""
    decide(cathy, "leave", 1, decision, "Decided.")
    llm.push(cancel_turn(request_id=1, request_type=LEAVE))
    response = Chat(amy).say("cancel my leave #1")
    assert ui_of(response) is None  # no confirmation card
    assert "can't be cancelled any more" in text_of(response)
    with seeded.session_factory() as s:
        assert (
            s.get(LeaveRequest, 1).status.value
            == {"approve": "approved", "reject": "rejected"}[decision]
        )


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_the_employee_can_no_longer_edit_a_decided_request(
    decision: str, seeded: Database, amy: TestClient, cathy: TestClient, llm: ScriptedLLM
) -> None:
    """A-23"""
    decide(cathy, "leave", 1, decision)
    llm.push(update_turn(request_id=1, request_type=LEAVE, leave={"end_date": d("2026-10-16")}))
    response = Chat(amy).say("extend my leave to the 16th")
    assert ui_of(response) is None
    assert "can't be changed any more" in text_of(response)
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, 1).end_date == d("2026-10-14")


def test_the_reviewer_note_is_repeated_when_a_rejected_request_is_edited(
    amy: TestClient, cathy: TestClient, llm: ScriptedLLM
) -> None:
    """A-23"""
    decide(cathy, "leave", 1, "reject", "Not this week.")
    llm.push(cancel_turn(request_id=1, request_type=LEAVE))
    response = Chat(amy).say("cancel it")
    assert "Reviewer note: Not this week." in text_of(response)


def test_a_decided_claim_is_final_for_the_employee_too(
    amy: TestClient, eva: TestClient, llm: ScriptedLLM
) -> None:
    """A-23"""
    decide(eva, "claim", 1, "approve")
    llm.push(cancel_turn(request_id=1, request_type=CLAIM))
    response = Chat(amy).say("cancel my claim #1")
    assert ui_of(response) is None and "can't be cancelled any more" in text_of(response)


# ---- attachments (A-24) --------------------------------------------------------------------
def test_the_approver_can_open_the_files_while_pending_and_after_the_decision(
    seeded: Database,
    upload_dir: Path,
    amy: TestClient,
    ben: TestClient,
    cathy: TestClient,
    helen: TestClient,
    eva: TestClient,
    anon: TestClient,
) -> None:
    """A-24: today's ``can_download`` rule (unchanged): the owner always; the ASSIGNED approver
    of the matching type while the request is submitted (pending, approved or rejected)."""
    file_id = add_attachment(seeded, upload_dir, AMY, LEAVE, 1)
    url = f"/api/attachments/{file_id}"

    def statuses() -> dict[str, int]:
        return {
            "owner": amy.get(url).status_code,
            "assigned": cathy.get(url).status_code,
            "other_hr": helen.get(url).status_code,
            "finance": eva.get(url).status_code,
            "employee": ben.get(url).status_code,
            "anon": anon.get(url).status_code,
        }

    expected_open = {
        "owner": 200,
        "assigned": 200,
        "other_hr": 404,
        "finance": 404,
        "employee": 404,
        "anon": 401,
    }
    assert statuses() == expected_open  # pending
    assert decide(cathy, "leave", 1, "approve").status_code == 200
    assert statuses() == expected_open  # approved: the assigned approver still opens it
    assert cathy.get("/api/approvals/leave/1").status_code == 404  # ...but not the detail page


def test_files_of_a_rejected_request_stay_downloadable_for_the_approver(
    seeded: Database, upload_dir: Path, cathy: TestClient
) -> None:
    """A-24"""
    file_id = add_attachment(seeded, upload_dir, AMY, LEAVE, 1)
    decide(cathy, "leave", 1, "reject", "No.")
    assert cathy.get(f"/api/attachments/{file_id}").status_code == 200


def test_files_of_a_cancelled_request_are_not_available_to_the_approver(
    seeded: Database, upload_dir: Path, amy: TestClient, cathy: TestClient
) -> None:
    """A-24: cancelled is not a submitted-and-kept status; only the owner keeps access."""
    file_id = add_attachment(seeded, upload_dir, AMY, LEAVE, 1)
    with seeded.session_factory() as s:
        s.get(LeaveRequest, 1).status = RequestStatus.CANCELLED
        s.commit()
    assert cathy.get(f"/api/attachments/{file_id}").status_code == 404
    assert amy.get(f"/api/attachments/{file_id}").status_code == 200
