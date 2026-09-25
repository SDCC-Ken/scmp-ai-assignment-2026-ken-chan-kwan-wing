"""Phase 3-C in the chat: leave balance on the card, "check my balance", and approver awareness.

Offline and deterministic (scripted LLM, the seed, no network). Seed numbers used here (2026,
today = Fri 2026-09-25): Amy annual 15 entitled, 1.5 approved, 4 pending (13.5 left), sick 10;
Ben annual 18 / 2 approved, sick 10 / 1 approved; Daniel annual 15 / 10 approved / 6 pending
(5 left); Cathy annual 15 / 2 approved. Amy and Ben are approved by Cathy, Cathy and Daniel by
Helen, everybody's claims by Eva.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db.models import ClaimRequest, LeaveEntitlement, LeaveRequest, Notification, User
from app.db.session import Database
from app.domain.enums import LeaveType, RequestType
from app.llm.fake import FakeLLMProvider
from app.llm.schemas import Intent
from app.main import create_app
from tests.chat.conftest import AMY, BEN, CATHY
from tests.chat.helpers import (
    FULL_LEAVE,
    VALID_CLAIM,
    Chat,
    RecordingAdapter,
    ScriptedLLM,
    card_of,
    claim_turn,
    d,
    details_leave,
    leave_turn,
    simple_turn,
    status_turn,
    text_of,
    ui_of,
    update_turn,
)
from tests.conftest import CSRF_HEADERS, login, make_settings

DANIEL = "daniel.wong@example.com"
HELEN = "helen.yeung@example.com"
EVA = "eva.cheung@example.com"
TAIL = "(pending requests are not counted)"


def as_user(app: FastAPI, email: str) -> Chat:
    client = TestClient(app, headers=CSRF_HEADERS)
    login(client, email)
    return Chat(client)


def info_of(card: dict[str, Any]) -> list[dict[str, str]]:
    return card["info"]


def leave_card(chat: Chat, llm: ScriptedLLM, **fields: Any) -> dict[str, Any]:
    llm.push(leave_turn(**fields))
    return card_of(chat.say("please book it"))


def set_user(db: Database, email: str, **fields: object) -> None:
    with db.session_factory() as s:
        row = s.scalars(select(User).where(User.email == email)).one()
        for key, value in fields.items():
            setattr(row, key, value)
        s.commit()


def drop_entitlements(db: Database, email: str, leave_type: LeaveType | None = None) -> None:
    with db.session_factory() as s:
        uid = s.scalars(select(User.id).where(User.email == email)).one()
        stmt = delete(LeaveEntitlement).where(LeaveEntitlement.user_id == uid)
        if leave_type is not None:
            stmt = stmt.where(LeaveEntitlement.leave_type == leave_type)
        s.execute(stmt)
        s.commit()


def count(db: Database, model: type) -> int:
    with db.session_factory() as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


# ---- balance lines on the leave card ----
def test_annual_leave_card_shows_the_balance_before_and_after(chat_app: FastAPI, llm: ScriptedLLM):
    amy = as_user(chat_app, AMY)
    card = leave_card(
        amy,
        llm,
        leave_type="annual",
        start_date=d("2026-11-02"),
        end_date=d("2026-11-04"),
    )
    assert info_of(card) == [
        {
            "label": "Annual leave 2026",
            "value": (
                f"15 days entitled, 1.5 used, 13.5 left; 10.5 left after this request {TAIL}"
            ),
            "tone": "info",
        }
    ]
    assert card["warnings"] == []
    assert card["confirm_label"] == "Submit"


def test_only_approved_leave_is_deducted_pending_is_not(chat_app: FastAPI, llm: ScriptedLLM):
    """Amy has 4 pending annual days (L1); the card must not deduct them (13.5 - 3 = 10.5)."""
    card = leave_card(
        as_user(chat_app, AMY),
        llm,
        leave_type="annual",
        start_date=d("2026-11-02"),
        end_date=d("2026-11-04"),
    )
    assert "10.5 left after this request" in info_of(card)[0]["value"]
    assert "6.5 left" not in info_of(card)[0]["value"]


def test_sick_leave_card_has_a_sick_balance_line(chat_app: FastAPI, llm: ScriptedLLM):
    card = leave_card(
        as_user(chat_app, BEN),
        llm,
        leave_type="sick",
        start_date=d("2026-09-24"),
        end_date=d("2026-09-24"),
    )
    assert info_of(card) == [
        {
            "label": "Sick leave 2026",
            "value": f"10 days entitled, 1 used, 9 left; 8 left after this request {TAIL}",
            "tone": "info",
        }
    ]


@pytest.mark.parametrize("leave_type", ["personal", "unpaid"])
def test_personal_and_unpaid_leave_have_no_balance_line(
    chat_app: FastAPI, llm: ScriptedLLM, leave_type: str
):
    card = leave_card(
        as_user(chat_app, AMY),
        llm,
        leave_type=leave_type,
        start_date=d("2026-11-02"),
        end_date=d("2026-11-02"),
    )
    assert info_of(card) == []


def test_going_over_the_balance_adds_a_warning_line_but_never_blocks(
    chat_app: FastAPI, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
):
    """Daniel has 5 annual days left; Mon 2 Nov to Tue 10 Nov ending in the morning is 6.5 days."""
    daniel = as_user(chat_app, DANIEL)
    card = leave_card(
        daniel,
        llm,
        leave_type="annual",
        start_date=d("2026-11-02"),
        end_date=d("2026-11-10"),
        end_day_part="am",
    )
    assert "6.5" in next(f["value"] for f in card["fields"] if f["key"] == "working_days")
    assert info_of(card) == [
        {
            "label": "Annual leave 2026",
            "value": (f"15 days entitled, 10 used, 5 left; none left after this request {TAIL}"),
            "tone": "info",
        },
        {
            "label": "Over your balance",
            "value": (
                "This is 1.5 days over your annual leave balance. "
                "Your approver will see this and decide."
            ),
            "tone": "warning",
        },
    ]
    assert card["state"] == "open" and card["confirm_label"] == "Submit"
    result = ui_of(daniel.act(card["card_id"]))  # Confirm still works
    assert result["outcome"] == "submitted"
    assert count(seeded, LeaveRequest) == 11


def test_exactly_using_the_remaining_days_is_not_over_the_balance(
    chat_app: FastAPI, llm: ScriptedLLM
):
    """5 days left, 5 working days requested: zero left, no warning (the boundary)."""
    card = leave_card(
        as_user(chat_app, DANIEL),
        llm,
        leave_type="annual",
        start_date=d("2026-11-02"),
        end_date=d("2026-11-06"),
    )
    assert [line["tone"] for line in info_of(card)] == ["info"]
    assert "5 left; 0 left after this request" in info_of(card)[0]["value"]


def test_one_day_over_says_1_day_not_1_days(chat_app: FastAPI, llm: ScriptedLLM):
    card = leave_card(
        as_user(chat_app, DANIEL),
        llm,
        leave_type="annual",
        start_date=d("2026-11-02"),
        end_date=d("2026-11-09"),
    )
    assert info_of(card)[1]["value"].startswith("This is 1 day over your annual leave balance.")


def test_the_balance_year_follows_the_start_date(chat_app: FastAPI, llm: ScriptedLLM):
    amy = as_user(chat_app, AMY)
    # Starts in 2027 (15 entitled, none used): the 2027 line, whatever the end date
    card = leave_card(
        amy,
        llm,
        leave_type="annual",
        start_date=d("2027-01-04"),
        end_date=d("2027-01-05"),
    )
    assert info_of(card)[0]["label"] == "Annual leave 2027"
    assert info_of(card)[0]["value"].startswith("15 days entitled, 0 used, 15 left; 13 left")
    # Starts on 30 Dec 2026 and ends in 2027: counted in 2026 (no splitting)
    llm.push(leave_turn(leave_type="annual", start_date=d("2026-12-30"), end_date=d("2027-01-05")))
    card = card_of(amy.say("another one"))
    assert info_of(card)[0]["label"] == "Annual leave 2026"
    assert info_of(card)[0]["value"].startswith("15 days entitled, 1.5 used, 13.5 left; ")


def test_a_missing_entitlement_is_said_not_invented(
    chat_app: FastAPI, llm: ScriptedLLM, seeded: Database
):
    drop_entitlements(seeded, AMY, LeaveType.ANNUAL)
    amy = as_user(chat_app, AMY)
    card = leave_card(
        amy,
        llm,
        leave_type="annual",
        start_date=d("2026-11-02"),
        end_date=d("2026-11-04"),
    )
    assert info_of(card) == [
        {
            "label": "Annual leave 2026",
            "value": "No leave balance is set up for this leave type",
            "tone": "info",
        }
    ]
    assert card["warnings"] == [] and card["state"] == "open"
    # sick still has its entitlement
    llm.push(leave_turn(leave_type="sick", start_date=d("2026-11-02"), end_date=d("2026-11-02")))
    assert info_of(card_of(amy.say("sick then")))[0]["label"] == "Sick leave 2026"


def test_the_update_card_shows_the_balance_after_the_change(chat_app: FastAPI, llm: ScriptedLLM):
    """Amy's pending L1 is 2026-10-09 to 14 (4 days). Cut it to 9 to 12 Oct = 2 working days."""
    amy = as_user(chat_app, AMY)
    llm.push(
        update_turn(
            request_id=1,
            request_type=RequestType.LEAVE,
            leave={"end_date": d("2026-10-12")},
        )
    )
    card = card_of(amy.say("shorten my leave #1 to end on 12 Oct"))
    assert card["action"] == "update" and card["request_id"] == 1
    assert info_of(card) == [
        {
            "label": "Annual leave 2026",
            "value": f"15 days entitled, 1.5 used, 13.5 left; 11.5 left after this request {TAIL}",
            "tone": "info",
        }
    ]


def test_changing_the_type_on_an_update_moves_the_balance_line(chat_app: FastAPI, llm: ScriptedLLM):
    amy = as_user(chat_app, AMY)
    llm.push(
        update_turn(request_id=1, request_type=RequestType.LEAVE, leave={"leave_type": "personal"})
    )
    assert info_of(card_of(amy.say("make leave #1 personal"))) == []


def test_claim_cards_get_no_balance_line(chat_app: FastAPI, llm: ScriptedLLM):
    llm.push(claim_turn(**VALID_CLAIM))
    card = card_of(as_user(chat_app, AMY).say("claim 120 travel"))
    assert card["request_type"] == "claim" and info_of(card) == []


def test_a_draft_without_all_fields_has_no_card_and_no_info(chat_app: FastAPI, llm: ScriptedLLM):
    llm.push(leave_turn(leave_type="annual"))
    response = as_user(chat_app, AMY).say("annual leave")
    assert response["assistant_messages"][-1]["ui"] is None


def test_the_info_survives_a_reload_of_the_conversation(chat_app: FastAPI, llm: ScriptedLLM):
    amy = as_user(chat_app, AMY)
    leave_card(amy, llm, leave_type="annual", start_date=d("2026-11-02"), end_date=d("2026-11-04"))
    stored = [m["ui"] for m in amy.detail()["messages"] if m["ui"]]
    assert stored[-1]["info"][0]["label"] == "Annual leave 2026"


# ---- "how many annual leave days do I have left?" ----
def test_check_balance_answers_with_a_balance_card_and_deterministic_text(
    chat_app: FastAPI, llm: ScriptedLLM
):
    amy = as_user(chat_app, AMY)
    llm.push(simple_turn(Intent.CHECK_BALANCE))
    response = amy.say("how many annual leave days do I have left?")
    assert ui_of(response) == {
        "type": "balance_card",
        "year": 2026,
        "lines": [
            {
                "leave_type": "annual",
                "entitled_days": 15.0,
                "approved_days": 1.5,
                "pending_days": 4.0,
                "remaining_days": 13.5,
            },
            {
                "leave_type": "sick",
                "entitled_days": 10.0,
                "approved_days": 0.0,
                "pending_days": 0.0,
                "remaining_days": 10.0,
            },
        ],
    }
    assert text_of(response) == (
        "Here is your leave balance for 2026. Annual leave: 15 days entitled, 1.5 used, "
        "13.5 left (4 days pending, not counted). Sick leave: 10 days entitled, 0 used, "
        "10 left."
    )
    assert response["warning_code"] is None
    trace = response["assistant_messages"][-1]["trace"]
    assert [t["step"] for t in trace][-2:] == ["status", "respond"]


def test_check_balance_uses_only_the_signed_in_users_numbers(chat_app: FastAPI, llm: ScriptedLLM):
    llm.push(simple_turn(Intent.CHECK_BALANCE))
    daniel = ui_of(as_user(chat_app, DANIEL).say("my balance"))
    annual = daniel["lines"][0]
    assert (annual["entitled_days"], annual["approved_days"], annual["pending_days"]) == (
        15.0,
        10.0,
        6.0,
    )
    assert annual["remaining_days"] == 5.0
    assert daniel["lines"][1]["entitled_days"] == 12.0  # Daniel's sick entitlement
    llm.push(simple_turn(Intent.CHECK_BALANCE))
    ben = ui_of(as_user(chat_app, BEN).say("my balance"))
    assert [line["entitled_days"] for line in ben["lines"]] == [18.0, 10.0]


def test_check_balance_with_a_message_about_someone_else_still_shows_only_your_own(
    chat_app: FastAPI, llm: ScriptedLLM
):
    llm.push(simple_turn(Intent.CHECK_BALANCE))
    response = as_user(chat_app, AMY).say("what is Ben's leave balance?")
    assert [line["entitled_days"] for line in ui_of(response)["lines"]] == [15.0, 10.0]  # Amy's


def test_check_balance_without_any_entitlement_says_so_and_has_no_card(
    chat_app: FastAPI, llm: ScriptedLLM, seeded: Database
):
    drop_entitlements(seeded, AMY)
    llm.push(simple_turn(Intent.CHECK_BALANCE))
    response = as_user(chat_app, AMY).say("leave balance")
    assert text_of(response) == "No leave balance is set up for you yet."
    assert ui_of(response) is None


def test_check_balance_with_only_one_entitlement_lists_only_that_type(
    chat_app: FastAPI, llm: ScriptedLLM, seeded: Database
):
    drop_entitlements(seeded, AMY, LeaveType.SICK)
    llm.push(simple_turn(Intent.CHECK_BALANCE))
    lines = ui_of(as_user(chat_app, AMY).say("leave balance"))["lines"]
    assert [line["leave_type"] for line in lines] == ["annual"]


def test_check_balance_does_not_disturb_an_open_draft_or_card(chat_app: FastAPI, llm: ScriptedLLM):
    amy = as_user(chat_app, AMY)
    card = leave_card(
        amy, llm, leave_type="annual", start_date=d("2026-11-02"), end_date=d("2026-11-04")
    )
    llm.push(simple_turn(Intent.CHECK_BALANCE))
    response = amy.say("how many annual leave days do I have left?")
    assert ui_of(response)["type"] == "balance_card"
    assert response["conversation"]["has_pending_card"] is True
    result = ui_of(amy.act(card["card_id"]))  # the earlier card still confirms
    assert result["outcome"] == "submitted"


def test_check_balance_never_needs_the_model_to_say_a_number(chat_app: FastAPI, llm: ScriptedLLM):
    """Even if the model returns rationale or a follow-up with numbers, they are not shown."""
    llm.push(
        simple_turn(
            Intent.CHECK_BALANCE,
            rationale="you have 99 days",
            followup_question="You have 99 days left.",
        )
    )
    response = as_user(chat_app, AMY).say("how many days do I have")
    assert "99" not in text_of(response) and "99" not in str(ui_of(response))


def test_check_balance_with_the_fake_provider_end_to_end(
    seeded: Database, adapter: RecordingAdapter
):
    app = create_app(
        make_settings(), database=seeded, llm_provider=FakeLLMProvider(), submission_adapter=adapter
    )
    amy = as_user(app, AMY)
    for phrase in (
        "how many annual leave days do I have left",
        "leave balance",
        "how much sick leave do I have",
        "remaining leave",
    ):
        response = amy.say(phrase)
        assert ui_of(response)["type"] == "balance_card", phrase


# ---- approver awareness: refuse up front, no draft, no card ----
def test_no_leave_approver_refuses_up_front_with_no_draft_and_no_card(
    chat_app: FastAPI, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
):
    set_user(seeded, AMY, leave_approver_user_id=None)
    amy = as_user(chat_app, AMY)
    llm.push(leave_turn(**FULL_LEAVE))
    response = amy.say("annual leave 5-7 Oct")
    assert text_of(response) == (
        "I can't file a leave request for you yet: no approver is configured for you (this is "
        "outside the PoC scope). Please contact HR."
    )
    assert ui_of(response) is None
    assert response["conversation"]["has_pending_card"] is False
    assert response["conversation"]["active_request_type"] is None  # no draft was started
    assert response["warning_code"] is None
    assert count(seeded, LeaveRequest) == 10 and adapter.calls == []
    # the claim side still works: Amy has a claim approver
    llm.push(claim_turn(**VALID_CLAIM))
    assert card_of(amy.say("claim 120 travel"))["request_type"] == "claim"


def test_no_claim_approver_refuses_claims_and_names_finance(
    chat_app: FastAPI, llm: ScriptedLLM, seeded: Database
):
    set_user(seeded, AMY, claim_approver_user_id=None)
    amy = as_user(chat_app, AMY)
    llm.push(claim_turn(**VALID_CLAIM))
    response = amy.say("claim 120 travel")
    assert text_of(response) == (
        "I can't file a claim for you yet: no approver is configured for you (this is outside "
        "the PoC scope). Please contact Finance."
    )
    assert ui_of(response) is None and response["conversation"]["active_request_type"] is None
    assert count(seeded, ClaimRequest) == 10
    llm.push(leave_turn(**FULL_LEAVE))  # leave still works
    assert card_of(amy.say("annual leave 5-7 Oct"))["request_type"] == "leave"


def test_the_refusal_keeps_the_users_other_open_draft(
    chat_app: FastAPI, llm: ScriptedLLM, seeded: Database
):
    """Refused new claim: the unfinished leave draft and its card are left alone."""
    amy = as_user(chat_app, AMY)
    card = leave_card(
        amy, llm, leave_type="annual", start_date=d("2026-11-02"), end_date=d("2026-11-04")
    )
    set_user(seeded, AMY, claim_approver_user_id=None)
    llm.push(claim_turn(**VALID_CLAIM))
    response = amy.say("claim 120 travel")
    assert "no approver is configured" in text_of(response)
    assert response["conversation"]["has_pending_card"] is True
    assert response["conversation"]["active_request_type"] == "leave"
    assert ui_of(amy.act(card["card_id"]))["outcome"] == "submitted"


def test_details_for_an_existing_draft_are_not_blocked_by_the_up_front_check(
    chat_app: FastAPI, llm: ScriptedLLM
):
    amy = as_user(chat_app, AMY)
    llm.push(leave_turn(leave_type="annual", start_date=d("2026-11-02")))
    assert "just one day" in text_of(amy.say("annual leave on 2 Nov"))
    llm.push(details_leave(end_date=d("2026-11-03")))
    assert card_of(amy.say("until 3 Nov"))["action"] == "create"


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"is_active": False}, "no longer active"),  # Cathy (Amy's leave approver)
    ],
)
def test_an_inactive_approver_is_refused_up_front_with_the_reason(
    chat_app: FastAPI, llm: ScriptedLLM, seeded: Database, change: dict, fragment: str
):
    set_user(seeded, CATHY, **change)
    llm.push(leave_turn(**FULL_LEAVE))
    response = as_user(chat_app, AMY).say("annual leave 5-7 Oct")
    text = text_of(response)
    assert text.startswith("I can't file a leave request for you yet.") and fragment in text
    assert "@" not in text  # never an e-mail address
    assert ui_of(response) is None


def test_the_confirm_time_check_is_still_the_second_guard(
    chat_app: FastAPI, llm: ScriptedLLM, seeded: Database
):
    amy = as_user(chat_app, AMY)
    card = leave_card(amy, llm, **FULL_LEAVE)
    set_user(seeded, AMY, leave_approver_user_id=None)
    done = amy.act(card["card_id"])
    assert "No approver is configured for your leave requests" in text_of(done)
    assert count(seeded, LeaveRequest) == 10


def test_users_without_any_approver_still_get_no_chat_at_all(chat_app: FastAPI):
    """Helen and Eva (no approvers in the seed) are stopped by the API before any assistant work."""
    for email in (HELEN, EVA):
        client = TestClient(chat_app, headers=CSRF_HEADERS)
        login(client, email)
        assert client.post("/api/chat/conversations").status_code == 403


# ---- the result names the approver ----
@pytest.mark.parametrize(
    ("email", "approver"),
    [(AMY, "Cathy Ng"), (BEN, "Cathy Ng"), (DANIEL, "Helen Yeung"), (CATHY, "Helen Yeung")],
)
def test_the_leave_result_names_the_assigned_approver(
    chat_app: FastAPI, llm: ScriptedLLM, email: str, approver: str
):
    chat = as_user(chat_app, email)
    card = leave_card(chat, llm, **FULL_LEAVE)
    done = chat.act(card["card_id"])
    text = text_of(done)
    assert text.endswith(f"and is now waiting for approval by {approver}.")
    assert text.startswith("Done. Your leave request #")
    assert "@" not in text  # names only


def test_the_claim_result_names_eva(chat_app: FastAPI, llm: ScriptedLLM):
    chat = as_user(chat_app, AMY)
    llm.push(claim_turn(**VALID_CLAIM))
    card = card_of(chat.say("claim 120 travel"))
    text = text_of(chat.act(card["card_id"]))
    assert "submitted to the offline" in text  # the recording adapter is not ReqRes
    assert text.endswith("and is now waiting for approval by Eva Cheung.")


def test_a_retry_after_a_failed_submission_names_the_approver_too(
    chat_app: FastAPI, llm: ScriptedLLM, adapter: RecordingAdapter
):
    chat = as_user(chat_app, AMY)
    adapter.fail_next()
    card = leave_card(chat, llm, **FULL_LEAVE)
    failed = chat.act(card["card_id"])
    assert "waiting for approval" not in text_of(failed, 0)
    retry = chat.detail()["messages"][-1]["ui"]
    assert retry["action"] == "retry"
    done = chat.act(retry["card_id"])
    assert text_of(done).endswith("waiting for approval by Cathy Ng.")


def test_the_approver_follows_a_changed_configuration(
    chat_app: FastAPI, llm: ScriptedLLM, seeded: Database
):
    with seeded.session_factory() as s:
        helen = s.scalars(select(User.id).where(User.email == HELEN)).one()
    set_user(seeded, AMY, leave_approver_user_id=helen)
    chat = as_user(chat_app, AMY)
    card = leave_card(chat, llm, **FULL_LEAVE)
    assert text_of(chat.act(card["card_id"])).endswith("approval by Helen Yeung.")
    with seeded.session_factory() as s:  # and only that person is notified
        recipients = s.scalars(
            select(Notification.recipient_user_id).order_by(Notification.id.desc())
        ).first()
        assert recipients == helen


# ---- status cards carry the approver's name ----
def test_status_card_items_carry_the_approver_name(chat_app: FastAPI, llm: ScriptedLLM):
    amy = as_user(chat_app, AMY)
    llm.push(status_turn())
    ui = ui_of(amy.say("my requests"))
    assert ui["type"] == "status_card" and ui["requests"]
    by_type = {(r["request_type"], r["id"]): r["approver_name"] for r in ui["requests"]}
    leave_names = {name for (kind, _), name in by_type.items() if kind == "leave"}
    claim_names = {name for (kind, _), name in by_type.items() if kind == "claim"}
    assert leave_names == {"Cathy Ng"} and claim_names == {"Eva Cheung"}
    assert "@" not in str(ui)  # display names only, never an e-mail address


def test_status_card_approver_name_is_null_when_unassigned(
    chat_app: FastAPI, llm: ScriptedLLM, seeded: Database
):
    with seeded.session_factory() as s:
        s.get(LeaveRequest, 1).approver_user_id = None
        s.commit()
    llm.push(status_turn(request_type=RequestType.LEAVE, request_id=1))
    ui = ui_of(as_user(chat_app, AMY).say("status of leave 1"))
    assert ui["requests"][0]["id"] == 1 and ui["requests"][0]["approver_name"] is None
