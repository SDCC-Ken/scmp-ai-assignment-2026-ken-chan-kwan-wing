"""CREATE LEAVE: success flows, then failures and follow-ups (test ids in docs/test-cases.md)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import (
    AuditEvent,
    ExternalSubmission,
    LeaveRequest,
    Notification,
    User,
)
from app.db.session import Database
from app.domain.enums import DayPart, LeaveType, RequestStatus, UserRole
from app.llm.schemas import AgentTurn, Intent, LeaveFields
from tests.chat.helpers import (
    AM,
    FULL_LEAVE,
    PM,
    TODAY,
    Chat,
    RecordingAdapter,
    ScriptedLLM,
    card_of,
    d,
    details_leave,
    field_values,
    leave_turn,
    text_of,
    ui_of,
)
from tests.conftest import get_user


def leaves_of(db: Database, email: str) -> list[LeaveRequest]:
    user = get_user(db, email)
    with db.session_factory() as s:
        return list(
            s.scalars(
                select(LeaveRequest)
                .where(LeaveRequest.employee_id == user.id)
                .order_by(LeaveRequest.id)
            )
        )


def latest_leave(db: Database, email: str) -> LeaveRequest:
    return leaves_of(db, email)[-1]


# ---- success -------------------------------------------------------------------------------------
def test_full_day_leave_confirm_saves_everything(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """LC-01"""
    llm.push(leave_turn(**FULL_LEAVE))
    resp = chat.say("Annual leave 5 to 7 Oct")
    card = card_of(resp)
    assert card["action"] == "create" and card["state"] == "open"
    assert card["confirm_label"] == "Submit"
    values = field_values(card)
    assert values["leave_type"] == "Annual"
    assert values["working_days"] == "3"
    assert values["employee_email"] == "cathy.ng@example.com"
    assert adapter.calls == []  # nothing is submitted before Confirm
    baseline = len(leaves_of(seeded, "cathy.ng@example.com"))

    done = chat.act(card["card_id"])
    result = ui_of(done)
    assert result["type"] == "result_card" and result["outcome"] == "submitted"
    assert result["status"] == "pending_approval"
    assert result["external_reference_id"] == "101"
    assert (
        "fake" in result["message"] and "ReqRes" in result["message"]
    )  # never presented as ReqRes
    assert "reference 101" in result["message"]

    assert len(leaves_of(seeded, "cathy.ng@example.com")) == baseline + 1
    row = latest_leave(seeded, "cathy.ng@example.com")
    assert row.status == RequestStatus.PENDING_APPROVAL
    assert row.submitted_at is not None
    assert (row.start_date, row.end_date) == (d("2026-10-05"), d("2026-10-07"))
    assert row.working_days == Decimal("3.0") and row.calendar_days == Decimal("3.0")
    assert row.conversation_id == chat.id

    with seeded.session_factory() as s:
        events = s.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_type == "leave_request", AuditEvent.entity_id == row.id)
            .order_by(AuditEvent.id)
        ).all()
        assert [e.event_type for e in events] == [
            "request.created",
            "request.confirmed",
            "submission.succeeded",
        ]
        assert (events[2].from_status, events[2].to_status) == ("draft", "pending_approval")
        sub = s.scalars(
            select(ExternalSubmission).where(
                ExternalSubmission.request_id == row.id, ExternalSubmission.request_type == "leave"
            )
        ).one()
        assert sub.status.value == "success" and sub.http_status == 201
        assert sub.external_reference_id == "101" and sub.provider == "fake"
        assert sub.request_payload_json == {
            "email": "cathy.ng@example.com",
            "leave_type": "Annual",
            "start_date": "2026-10-05",
            "end_date": "2026-10-07",
        }
        notes = s.scalars(
            select(Notification).where(
                Notification.request_id == row.id, Notification.request_type == "leave"
            )
        ).all()
        # Phase 3: only the assigned approver (Helen) is told, not every HR approver.
        helen = s.scalars(select(User).where(User.email == "helen.yeung@example.com")).one()
        assert [n.recipient_user_id for n in notes] == [helen.id]
        assert {n.event_type for n in notes} == {"request.submitted"}
        assert (
            row.approver_user_id == helen.id and row.required_approver_role == UserRole.HR_APPROVER
        )


def test_half_day_morning(chat: Chat, llm: ScriptedLLM, seeded: Database) -> None:
    """LC-02"""
    llm.push(
        leave_turn(
            leave_type=LeaveType.PERSONAL,
            start_date=d("2026-10-06"),
            end_date=d("2026-10-06"),
            start_day_part=AM,
            end_day_part=AM,
        )
    )
    card = card_of(chat.say("Tuesday morning off please"))
    values = field_values(card)
    assert values["working_days"] == "0.5"
    assert values["start_date"] == "Tue 2026-10-06 (morning only)"
    chat.act(card["card_id"])
    row = latest_leave(seeded, "cathy.ng@example.com")
    assert (row.start_day_part, row.end_day_part) == (DayPart.AM, DayPart.AM)
    assert row.working_days == Decimal("0.5")


def test_single_day_half_day_mirrors_the_other_part(chat: Chat, llm: ScriptedLLM) -> None:
    """LC-02b: the LLM gave only start_day_part for a one-day leave."""
    llm.push(
        leave_turn(
            leave_type=LeaveType.PERSONAL,
            start_date=d("2026-10-06"),
            end_date=d("2026-10-06"),
            start_day_part=PM,
        )
    )
    values = field_values(card_of(chat.say("Tuesday afternoon")))
    assert values["working_days"] == "0.5"
    assert values["end_date"] == "Tue 2026-10-06 (afternoon only)"


def test_multi_day_pm_start_am_end(chat: Chat, llm: ScriptedLLM, seeded: Database) -> None:
    """LC-03"""
    llm.push(
        leave_turn(
            leave_type=LeaveType.ANNUAL,
            start_date=d("2026-10-05"),
            end_date=d("2026-10-07"),
            start_day_part=PM,
            end_day_part=AM,
        )
    )
    card = card_of(chat.say("from Monday afternoon until Wednesday lunch"))
    assert field_values(card)["working_days"] == "2"  # 0.5 + 1 + 0.5
    chat.act(card["card_id"])
    row = latest_leave(seeded, "cathy.ng@example.com")
    assert (row.start_day_part, row.end_day_part) == (DayPart.PM, DayPart.AM)
    assert row.working_days == Decimal("2.0") and row.calendar_days == Decimal("2.0")


def test_range_over_weekend_and_national_day(
    chat: Chat, llm: ScriptedLLM, seeded: Database
) -> None:
    """LC-04: Tue 29 Sep .. Mon 5 Oct 2026 skips Sat/Sun and Thu 1 Oct (National Day) = 4 days."""
    llm.push(
        leave_turn(
            leave_type=LeaveType.ANNUAL, start_date=d("2026-09-29"), end_date=d("2026-10-05")
        )
    )
    card = card_of(chat.say("29 Sep to 5 Oct"))
    assert field_values(card)["working_days"] == "4"
    assert card["warnings"] == []
    chat.act(card["card_id"])
    row = latest_leave(seeded, "cathy.ng@example.com")
    assert row.working_days == Decimal("4.0") and row.calendar_days == Decimal("7.0")


def test_sick_leave_back_dated_three_days(chat: Chat, llm: ScriptedLLM, seeded: Database) -> None:
    """LC-05: back-dated leave is accepted (limits are Phase 3 business rules)."""
    llm.push(
        leave_turn(leave_type=LeaveType.SICK, start_date=d("2026-09-22"), end_date=d("2026-09-22"))
    )
    card = card_of(chat.say("I was sick on Tuesday"))
    chat.act(card["card_id"])
    assert latest_leave(seeded, "cathy.ng@example.com").leave_type == LeaveType.SICK


@pytest.mark.parametrize("days_back", [3, 8, 200])
def test_sick_leave_may_start_on_any_past_date(
    chat: Chat, llm: ScriptedLLM, days_back: int
) -> None:
    """LC-06: sick leave can be back-dated by any number of days (no limit was asked for)."""
    start = TODAY - timedelta(days=days_back)
    while start.weekday() >= 5:  # keep the range on a working day
        start -= timedelta(days=1)
    llm.push(leave_turn(leave_type=LeaveType.SICK, start_date=start, end_date=start))
    assert card_of(chat.say("I was ill"))["action"] == "create"


def test_leave_starting_today_is_accepted_for_every_type(chat: Chat, llm: ScriptedLLM) -> None:
    """LC-07: today (Friday 2026-09-25) is not "in the past"."""
    for leave_type in (LeaveType.ANNUAL, LeaveType.PERSONAL, LeaveType.UNPAID):
        llm.push(leave_turn(leave_type=leave_type, start_date=TODAY, end_date=TODAY))
        assert card_of(chat.say("leave from today"))["action"] == "create"


# ---- failures / follow-ups ----------------------------------------------------------------------
@pytest.mark.parametrize("leave_type", [LeaveType.ANNUAL, LeaveType.PERSONAL, LeaveType.UNPAID])
def test_past_start_is_rejected_except_for_sick_leave(
    chat: Chat, llm: ScriptedLLM, leave_type: LeaveType
) -> None:
    """LF-00: business rule no_past_leave_except_sick."""
    llm.push(
        leave_turn(leave_type=leave_type, start_date=d("2026-08-03"), end_date=d("2026-08-04"))
    )
    resp = chat.say("leave 3-4 Aug")
    assert ui_of(resp) is None
    assert text_of(resp) == (
        f"{leave_type.value.title()} leave cannot start in the past (today is Fri 2026-09-25). "
        "Which start date do you want? Sick leave can be back-dated."
    )
    # fixing the start date (and the end date) produces the card
    llm.push(details_leave(start_date=d("2026-10-05"), end_date=d("2026-10-06")))
    assert card_of(chat.say("5 to 6 Oct"))["action"] == "create"


def test_changing_the_type_to_sick_lifts_the_past_date_error(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-00b"""
    llm.push(
        leave_turn(
            leave_type=LeaveType.ANNUAL, start_date=d("2026-09-21"), end_date=d("2026-09-22")
        )
    )
    assert ui_of(chat.say("annual leave 21-22 Sep")) is None
    llm.push(details_leave(leave_type=LeaveType.SICK))
    assert card_of(chat.say("it was sick leave"))["action"] == "create"


def test_end_before_start_asks_for_the_end_date(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-01"""
    llm.push(
        leave_turn(
            leave_type=LeaveType.ANNUAL, start_date=d("2026-10-05"), end_date=d("2026-10-01")
        )
    )
    resp = chat.say("leave from 5 Oct to 1 Oct")
    assert ui_of(resp) is None
    assert text_of(resp) == (
        "End date 2026-10-01 is before the start date 2026-10-05. Which end date do you want?"
    )
    # the user fixes it; the wrong end date is replaced and a card appears
    llm.push(details_leave(end_date=d("2026-10-07")))
    card = card_of(chat.say("7 Oct"))
    assert field_values(card)["working_days"] == "3"


def test_weekend_only_range_is_rejected(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-02"""
    llm.push(
        leave_turn(
            leave_type=LeaveType.PERSONAL, start_date=d("2026-10-03"), end_date=d("2026-10-04")
        )
    )
    resp = chat.say("Saturday and Sunday off")
    assert ui_of(resp) is None
    assert "2026-10-03 to 2026-10-04" in text_of(resp)
    assert "no working day" in text_of(resp)


def test_holiday_only_range_names_the_holiday(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-03"""
    llm.push(
        leave_turn(
            leave_type=LeaveType.ANNUAL, start_date=d("2026-10-01"), end_date=d("2026-10-01")
        )
    )
    resp = chat.say("1 October off")
    assert ui_of(resp) is None
    assert "National Day on 2026-10-01" in text_of(resp)


@pytest.mark.parametrize(
    ("fields", "field_name"),
    [
        (
            {"start_date": d("2026-10-05"), "end_date": d("2026-10-06"), "start_day_part": AM},
            "morning-only day",
        ),
        (
            {"start_date": d("2026-10-05"), "end_date": d("2026-10-06"), "end_day_part": PM},
            "afternoon-only day",
        ),
        (
            {
                "start_date": d("2026-10-05"),
                "end_date": d("2026-10-05"),
                "start_day_part": AM,
                "end_day_part": PM,
            },
            "must match",
        ),
    ],
    ids=["multi-day-am-start", "multi-day-pm-end", "single-day-mismatch"],
)
def test_invalid_half_day_combination(
    chat: Chat, llm: ScriptedLLM, fields: dict, field_name: str
) -> None:
    """LF-04"""
    llm.push(leave_turn(leave_type=LeaveType.ANNUAL, **fields))
    resp = chat.say("some half day thing")
    assert ui_of(resp) is None
    assert field_name in text_of(resp)


def test_missing_fields_are_asked_one_at_a_time(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-05"""
    llm.push(leave_turn())
    assert "Which type of leave" in text_of(chat.say("I want to take some leave"))
    llm.push(details_leave(leave_type=LeaveType.SICK))
    assert "first day" in text_of(chat.say("sick"))
    llm.push(details_leave(start_date=d("2026-10-06")))
    assert "Is Tue 2026-10-06 just one day" in text_of(chat.say("6 Oct"))
    llm.push(details_leave(end_date=d("2026-10-06")))
    resp = chat.say("6 Oct again")
    card = card_of(resp)
    assert field_values(card)["working_days"] == "1"
    assert chat.detail()["conversation"]["has_pending_card"] is True


def test_unknown_leave_type_lists_the_supported_types(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-06: the LLM could not map "maternity" to a type."""
    llm.push(
        AgentTurn(
            intent=Intent.CREATE_LEAVE,
            leave=LeaveFields(start_date=d("2026-10-05"), end_date=d("2026-10-06")),
            ambiguities=[],
            confidence=0.8,
        )
    )
    resp = chat.say("maternity leave 5-6 Oct")
    assert ui_of(resp) is None
    assert "annual, sick, personal or unpaid" in text_of(resp)


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_invalid_enum_value_from_the_model_is_ignored_and_explained(
    chat: Chat, llm: ScriptedLLM
) -> None:
    """LF-06b: defence in depth if a provider hands over an unvalidated string."""
    bad = AgentTurn.model_construct(
        intent=Intent.CREATE_LEAVE,
        request_type=None,
        leave=LeaveFields.model_construct(
            leave_type="maternity", start_date=d("2026-10-05"), end_date=d("2026-10-06")
        ),
        claim=None,
        target=None,
        status_query=None,
        ambiguities=[],
        followup_question=None,
        confidence=0.9,
        rationale=None,
    )
    llm.push(bad)
    resp = chat.say("maternity leave")
    assert ui_of(resp) is None
    assert 'I don\'t offer "maternity" as a leave type' in text_of(resp)


def test_year_without_holiday_data_adds_a_warning(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-07"""
    llm.push(
        leave_turn(
            leave_type=LeaveType.ANNUAL, start_date=d("2028-01-10"), end_date=d("2028-01-12")
        )
    )
    card = card_of(chat.say("annual leave 10-12 Jan 2028"))
    assert card["warnings"] == [
        "No public-holiday data for 2028; only weekends were excluded from the working days"
    ]
    assert field_values(card)["working_days"] == "3"


def test_ambiguity_from_the_llm_asks_and_shows_no_card(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-08"""
    llm.push(
        AgentTurn(
            intent=Intent.CREATE_LEAVE,
            leave=LeaveFields(
                leave_type=LeaveType.ANNUAL, start_date=d("2026-10-02"), end_date=d("2026-10-05")
            ),
            ambiguities=["start_date: 'next Friday' could be 2026-10-02 or 2026-10-09"],
            confidence=0.9,
        )
    )
    resp = chat.say("annual leave from next Friday until Monday")
    assert ui_of(resp) is None
    assert "Before I go on I need to check" in text_of(resp)
    assert "next Friday" in text_of(resp)
    # only the unambiguous fields were merged: the start date was held back
    llm.push(details_leave(start_date=d("2026-10-02")))
    resp = chat.say("the 2nd")
    values = field_values(card_of(resp))
    assert values["leave_type"] == "Annual" and values["end_date"] == "Mon 2026-10-05"


def test_ambiguity_naming_no_field_holds_back_everything(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-08b"""
    llm.push(
        AgentTurn(
            intent=Intent.CREATE_LEAVE,
            leave=LeaveFields(leave_type=LeaveType.SICK, start_date=d("2026-10-06")),
            ambiguities=["The request is vague"],
            confidence=0.9,
        )
    )
    chat.say("some time off")
    llm.push(details_leave())
    # nothing was merged, so the first missing field is asked again
    assert "Which type of leave" in text_of(chat.say("hm"))


def test_low_confidence_asks_for_clarification_without_changes(
    chat: Chat, llm: ScriptedLLM
) -> None:
    """LF-09"""
    llm.push(AgentTurn(intent=Intent.CREATE_LEAVE, leave=LeaveFields(**FULL_LEAVE), confidence=0.3))
    resp = chat.say("mumble")
    assert ui_of(resp) is None
    assert "not sure I understood" in text_of(resp)
    assert chat.detail()["conversation"]["active_request_type"] is None


def test_someone_elses_email_is_refused(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """LF-10: the employee e-mail always comes from the signed-in user."""
    llm.push(leave_turn(**FULL_LEAVE))
    resp = chat.say("Submit annual leave 5-7 Oct for bob@example.com")
    assert ui_of(resp) is None
    assert "only act for the signed-in user" in text_of(resp)
    assert adapter.calls == []
    assert chat.detail()["conversation"]["has_pending_card"] is False


def test_llm_followup_wording_is_used_only_when_it_passes_sanity_checks(
    chat: Chat, llm: ScriptedLLM
) -> None:
    """LF-11"""
    good = leave_turn(leave_type=LeaveType.ANNUAL)
    good.followup_question = "Which day does your annual leave begin?"
    llm.push(good)
    assert text_of(chat.say("annual leave")) == "Which day does your annual leave begin?"

    bad = details_leave()
    bad.followup_question = "<b>Which day</b> does it begin? see http://x.example"
    llm.push(bad)
    assert "first day of your leave" in text_of(chat.say("hm"))

    wrong_field = details_leave()
    wrong_field.followup_question = "How much is the claim in HKD?"
    llm.push(wrong_field)
    assert "first day of your leave" in text_of(chat.say("hm again"))


def test_new_draft_of_the_other_type_drops_the_old_one(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-12"""
    llm.push(leave_turn(leave_type=LeaveType.ANNUAL))
    chat.say("annual leave")
    from tests.chat.helpers import claim_turn

    llm.push(claim_turn(claim_type=None))
    resp = chat.say("actually I want to make a claim")
    assert "I set aside your unfinished leave application." in text_of(resp)
    assert chat.detail()["conversation"]["active_request_type"] == "claim"


def test_provide_details_without_a_draft_asks_leave_or_claim(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-13"""
    llm.push(AgentTurn(intent=Intent.PROVIDE_DETAILS, confidence=0.9))
    assert "leave application or a staff claim" in text_of(chat.say("next Monday"))


def test_both_leave_and_claim_mentioned_handles_the_first(chat: Chat, llm: ScriptedLLM) -> None:
    """LF-14"""
    from app.llm.schemas import ClaimFields

    llm.push(
        AgentTurn(
            intent=Intent.CREATE_LEAVE,
            leave=LeaveFields(**FULL_LEAVE),
            claim=ClaimFields(amount=50.0),
            confidence=0.9,
        )
    )
    resp = chat.say("leave 5-7 Oct and also claim 50")
    assert card_of(resp)["request_type"] == "leave"
    assert "I'll do the leave application first" in text_of(resp)


def test_typing_yes_only_reminds_to_press_the_button(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter
) -> None:
    """LF-15"""
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave 5-7 Oct"))
    resp = chat.say("yes")
    assert 'press the "Submit" button' in text_of(resp)
    assert ui_of(resp) is None
    assert adapter.calls == []
    assert llm.queue == [] and len(llm.calls) == 1  # no LLM call for a bare "yes"
    assert chat.detail()["conversation"]["has_pending_card"] is True
    assert chat.detail()["messages"][1]["ui"]["state"] == "open"
    assert card["state"] == "open"


# ---- single date: "just one day, or until another date?" ---------------------------------------
ONE_DAY_QUESTION = (
    "Is Tue 2026-10-06 just one day, or do you want leave until another date? "
    "(Reply 'just one day' or give the end date.)"
)


def start_only(chat: Chat, llm: ScriptedLLM) -> None:
    llm.push(leave_turn(leave_type=LeaveType.ANNUAL, start_date=d("2026-10-06")))
    resp = chat.say("annual leave on Tuesday 6 Oct")
    assert ui_of(resp) is None and text_of(resp) == ONE_DAY_QUESTION


@pytest.mark.parametrize(
    "reply",
    [
        "just one day",
        "Just one day.",
        "YES",
        "One day only!",
        "only that day",
        "single day",
        "same day",
        "that day only",
        "1 day",
    ],
)
def test_single_date_then_just_one_day_gives_a_one_day_card(
    chat: Chat, llm: ScriptedLLM, reply: str
) -> None:
    """LS-01: the backend reads the reply even when the LLM extracted nothing."""
    start_only(chat, llm)
    llm.push(details_leave())  # the LLM did not set end_date
    card = card_of(chat.say(reply))
    values = field_values(card)
    assert values["start_date"] == "Tue 2026-10-06" and values["end_date"] == "Tue 2026-10-06"
    assert values["working_days"] == "1"


def test_just_one_day_is_read_even_if_the_llm_misclassifies_the_reply(
    chat: Chat, llm: ScriptedLLM
) -> None:
    """LS-01b"""
    start_only(chat, llm)
    llm.push(AgentTurn(intent=Intent.UNCLEAR, confidence=0.2))
    assert field_values(card_of(chat.say("just one day")))["end_date"] == "Tue 2026-10-06"


def test_single_date_then_an_explicit_end_date_gives_a_range(chat: Chat, llm: ScriptedLLM) -> None:
    """LS-02"""
    start_only(chat, llm)
    llm.push(details_leave(end_date=d("2026-10-08")))
    values = field_values(card_of(chat.say("until Thursday")))
    assert values["end_date"] == "Thu 2026-10-08" and values["working_days"] == "3"


def test_an_llm_end_date_wins_over_the_one_day_phrase(chat: Chat, llm: ScriptedLLM) -> None:
    """LS-02b"""
    start_only(chat, llm)
    llm.push(details_leave(end_date=d("2026-10-07")))
    assert field_values(card_of(chat.say("just one day, no wait, until the 7th")))["end_date"] == (
        "Wed 2026-10-07"
    )


def test_single_date_then_nonsense_asks_again(chat: Chat, llm: ScriptedLLM) -> None:
    """LS-03"""
    start_only(chat, llm)
    llm.push(details_leave())
    assert text_of(chat.say("hmm let me think")) == ONE_DAY_QUESTION
    llm.push(AgentTurn(intent=Intent.UNCLEAR, confidence=0.2))
    assert text_of(chat.say("asdf qwer")) == ONE_DAY_QUESTION
    # a one-day phrase only counts while that question is open
    llm.push(details_leave())
    assert card_of(chat.say("just one day"))["action"] == "create"


def test_one_day_phrase_without_the_question_open_does_nothing_special(
    chat: Chat, llm: ScriptedLLM
) -> None:
    """LS-03b: no start date yet, so "yes" is not read as a one-day answer."""
    llm.push(leave_turn(leave_type=LeaveType.ANNUAL))
    chat.say("annual leave")
    llm.push(details_leave())
    assert "first day" in text_of(chat.say("yes"))


@pytest.mark.parametrize("part", [AM, PM])
def test_single_date_with_a_half_day_part_asks_no_extra_question(
    chat: Chat, llm: ScriptedLLM, part: DayPart
) -> None:
    """LS-04: a morning/afternoon-only single date already implies one day."""
    llm.push(
        leave_turn(leave_type=LeaveType.PERSONAL, start_date=d("2026-10-06"), start_day_part=part)
    )
    card = card_of(chat.say("Tuesday half day"))
    values = field_values(card)
    assert values["working_days"] == "0.5"
    label = "morning only" if part == AM else "afternoon only"
    assert values["end_date"] == f"Tue 2026-10-06 ({label})"
