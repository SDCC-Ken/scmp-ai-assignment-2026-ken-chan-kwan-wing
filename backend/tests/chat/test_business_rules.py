"""The Phase 3 extension point (app.chat.policy) and the one rule registered today."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.chat import policy
from app.chat.policy import RuleContext, Violation, first_violation
from app.db.models import LeaveRequest
from app.db.session import Database
from app.domain.enums import ClaimType, LeaveType, RequestStatus, RequestType
from tests.chat.helpers import (
    FULL_LEAVE,
    TODAY,
    VALID_CLAIM,
    Chat,
    RecordingAdapter,
    ScriptedLLM,
    card_of,
    claim_turn,
    d,
    details_claim,
    details_leave,
    field_values,
    leave_turn,
    submit_claim,
    submit_leave,
    text_of,
    ui_of,
    update_turn,
)
from tests.conftest import get_user

LEAVE = RequestType.LEAVE


def test_default_registry_has_exactly_the_past_leave_rule() -> None:
    """BR-01"""
    assert [rule.__name__ for rule in policy.BUSINESS_RULES] == ["no_past_leave_except_sick"]


def test_first_violation_runs_rules_in_order_and_accepts_lists(session) -> None:  # type: ignore[no-untyped-def]
    """BR-02"""
    ctx = RuleContext(
        session=session,
        employee_id=1,
        request_type=LEAVE,
        draft=None,  # type: ignore[arg-type]
        today=TODAY,
    )
    first, second = Violation("a", "first"), Violation("b", "second")
    assert first_violation(ctx, rules=[]) is None
    assert first_violation(ctx, rules=[lambda _c: None, lambda _c: [first, second]]) == first
    assert first_violation(ctx, rules=[lambda _c: second, lambda _c: first]) == second
    assert first_violation(ctx, rules=[lambda _c: []]) is None


def test_a_registered_rule_is_enforced_as_a_follow_up(
    chat: Chat, llm: ScriptedLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BR-03: Phase 3 plugs a rule in and the agent asks the user to fix it."""

    def cap_1000(ctx: RuleContext) -> Violation | None:
        if ctx.amount is not None and ctx.amount > 1000:
            return Violation(
                "amount", "Claims above HKD 1000 need approval first. Which amount is it?"
            )
        return None

    monkeypatch.setattr(policy, "BUSINESS_RULES", [*policy.BUSINESS_RULES, cap_1000])
    llm.push(claim_turn(claim_type=ClaimType.EQUIPMENT, amount=1500.0, receipt_date=TODAY))
    resp = chat.say("monitor 1500")
    assert ui_of(resp) is None
    assert text_of(resp) == "Claims above HKD 1000 need approval first. Which amount is it?"
    llm.push(details_claim(amount=900.0))
    assert card_of(chat.say("900"))["action"] == "create"


def test_a_registered_rule_runs_again_at_confirm(
    chat: Chat,
    llm: ScriptedLLM,
    adapter: RecordingAdapter,
    seeded: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BR-04: the world may have changed between the card and the click."""
    blocked = {"on": False}

    def closed_period(ctx: RuleContext) -> Violation | None:
        if blocked["on"]:
            return Violation("start_date", "Leave in that period is now closed. Which start date?")
        return None

    monkeypatch.setattr(policy, "BUSINESS_RULES", [*policy.BUSINESS_RULES, closed_period])
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave"))
    with seeded.session_factory() as s:
        before = len(list(s.scalars(select(LeaveRequest))))
    blocked["on"] = True
    resp = chat.act(card["card_id"])
    assert "I re-checked before saving and something changed." in text_of(resp)
    assert "Leave in that period is now closed" in text_of(resp)
    assert adapter.calls == []
    with seeded.session_factory() as s:
        assert len(list(s.scalars(select(LeaveRequest)))) == before
    detail = chat.detail()
    assert detail["conversation"]["has_pending_card"] is False
    assert detail["messages"][1]["ui"]["state"] == "superseded"
    # the draft survived, so fixing the start date brings the card back
    blocked["on"] = False
    llm.push(details_leave())
    assert card_of(chat.say("keep the same dates"))["action"] == "create"


def test_nothing_else_is_enforced_yet(chat: Chat, llm: ScriptedLLM, seeded: Database) -> None:
    """BR-05: overlap, length, balance, caps, receipt age and duplicates are Phase 3 rules."""
    # overlap: the same dates twice, both submitted
    first = submit_leave(chat, llm)
    second = submit_leave(chat, llm)
    assert first != second
    # a very long leave (over 60 days) and one ending more than a year ahead
    llm.push(
        leave_turn(
            leave_type=LeaveType.UNPAID, start_date=d("2026-10-05"), end_date=d("2027-03-31")
        )
    )
    assert card_of(chat.say("unpaid leave until March"))["action"] == "create"
    llm.push(
        leave_turn(
            leave_type=LeaveType.ANNUAL, start_date=d("2028-10-02"), end_date=d("2028-10-06")
        )
    )
    assert card_of(chat.say("annual leave in 2028"))["action"] == "create"
    # claims: duplicate, huge amount, old receipt
    one = submit_claim(chat, llm)
    two = submit_claim(chat, llm)  # identical to the first
    assert one != two
    llm.push(
        claim_turn(
            claim_type=ClaimType.OTHER,
            amount=1_234_567.89,
            receipt_date=TODAY - timedelta(days=400),
        )
    )
    values = field_values(card_of(chat.say("big old claim")))
    assert values["amount"] == "HKD 1,234,567.89"


def test_empty_registry_accepts_past_annual_leave(
    chat: Chat, llm: ScriptedLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BR-06: with no rules registered, structural validity is all that is checked."""
    monkeypatch.setattr(policy, "BUSINESS_RULES", [])
    llm.push(
        leave_turn(
            leave_type=LeaveType.ANNUAL, start_date=d("2026-08-03"), end_date=d("2026-08-04")
        )
    )
    assert card_of(chat.say("annual leave in August"))["action"] == "create"


def test_rule_is_named_in_the_follow_up_for_sick_vs_others(chat: Chat, llm: ScriptedLLM) -> None:
    """BR-07: the message says today's date and that sick leave can be back-dated."""
    llm.push(
        leave_turn(
            leave_type=LeaveType.UNPAID, start_date=TODAY - timedelta(days=1), end_date=TODAY
        )
    )
    assert text_of(chat.say("unpaid leave from yesterday")) == (
        "Unpaid leave cannot start in the past (today is Fri 2026-09-25). "
        "Which start date do you want? Sick leave can be back-dated."
    )


# ---- update: the past-start rule only bites when the start date or the type changes -------------
@pytest.fixture
def started_annual(seeded: Database) -> int:
    """A pending ANNUAL leave that started four days ago (created before the rule existed)."""
    user = get_user(seeded, "cathy.ng@example.com")
    with seeded.session_factory() as s:
        row = LeaveRequest(
            employee_id=user.id,
            leave_type=LeaveType.ANNUAL,
            start_date=d("2026-09-21"),
            end_date=d("2026-09-30"),
            calendar_days=Decimal("10.0"),
            working_days=Decimal("8.0"),
            status=RequestStatus.PENDING_APPROVAL,
        )
        s.add(row)
        s.commit()
        return row.id


def test_extending_an_already_started_leave_is_allowed(
    chat: Chat, llm: ScriptedLLM, started_annual: int, seeded: Database
) -> None:
    """BR-08"""
    llm.push(
        update_turn(
            request_id=started_annual, request_type=LEAVE, leave={"end_date": d("2026-10-02")}
        )
    )
    card = card_of(chat.say("extend my leave to 2 Oct"))
    assert card["action"] == "update"
    assert {f["key"]: f["old_value"] for f in card["fields"]}["end_date"] == "Wed 2026-09-30"
    chat.act(card["card_id"])
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, started_annual).end_date == d("2026-10-02")


def test_moving_the_start_date_into_the_past_is_rejected(
    chat: Chat, llm: ScriptedLLM, started_annual: int
) -> None:
    """BR-09"""
    llm.push(
        update_turn(
            request_id=started_annual, request_type=LEAVE, leave={"start_date": d("2026-09-22")}
        )
    )
    resp = chat.say("start on the 22nd instead")
    assert ui_of(resp) is None
    assert "Annual leave cannot start in the past" in text_of(resp)
    llm.push(details_leave())  # nothing new: the same problem is repeated
    assert "cannot start in the past" in text_of(chat.say("hm"))


def test_changing_the_type_of_a_started_leave_is_checked(
    chat: Chat, llm: ScriptedLLM, started_annual: int, seeded: Database
) -> None:
    """BR-10: annual -> personal stays invalid, annual -> sick is fine."""
    llm.push(
        update_turn(
            request_id=started_annual, request_type=LEAVE, leave={"leave_type": LeaveType.PERSONAL}
        )
    )
    assert "Personal leave cannot start in the past" in text_of(chat.say("make it personal"))
    llm.push(
        update_turn(
            request_id=started_annual, request_type=LEAVE, leave={"leave_type": LeaveType.SICK}
        )
    )
    card = card_of(chat.say("actually it was sick leave"))
    assert {f["key"]: f["value"] for f in card["fields"]}["leave_type"] == "Sick"
    chat.act(card["card_id"])
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, started_annual).leave_type == LeaveType.SICK


def test_sick_leave_in_the_past_can_be_edited_but_not_turned_into_annual(
    chat: Chat, llm: ScriptedLLM, seeded: Database
) -> None:
    """BR-11"""
    rid = submit_leave(
        chat, llm, leave_type=LeaveType.SICK, start_date=d("2026-09-21"), end_date=d("2026-09-22")
    )
    llm.push(update_turn(request_id=rid, request_type=LEAVE, leave={"end_date": d("2026-09-23")}))
    assert card_of(chat.say("one more day"))["action"] == "update"
    llm.push(
        update_turn(request_id=rid, request_type=LEAVE, leave={"leave_type": LeaveType.ANNUAL})
    )
    assert "Annual leave cannot start in the past" in text_of(chat.say("make it annual"))


def test_the_leave_rule_ignores_claims(chat: Chat, llm: ScriptedLLM) -> None:
    """BR-12"""
    assert submit_claim(chat, llm, **VALID_CLAIM)
