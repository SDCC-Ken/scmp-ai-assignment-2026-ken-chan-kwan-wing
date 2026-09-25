"""CREATE CLAIM: success flows, then failures and follow-ups (ids in docs/test-cases.md)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import AuditEvent, ClaimRequest, ExternalSubmission, Notification, User
from app.db.session import Database
from app.domain.enums import ClaimType, RequestStatus, UserRole
from app.llm.schemas import AgentTurn, ClaimFields, Intent
from tests.chat.helpers import (
    TODAY,
    VALID_CLAIM,
    Chat,
    RecordingAdapter,
    ScriptedLLM,
    card_of,
    claim_turn,
    d,
    details_claim,
    field_values,
    text_of,
    ui_of,
)
from tests.conftest import get_user

CATHY = "cathy.ng@example.com"


def claims_of(db: Database, email: str) -> list[ClaimRequest]:
    user = get_user(db, email)
    with db.session_factory() as s:
        return list(
            s.scalars(
                select(ClaimRequest)
                .where(ClaimRequest.employee_id == user.id)
                .order_by(ClaimRequest.id)
            )
        )


# ---- success -------------------------------------------------------------------------------------
def test_valid_claim_confirm_saves_everything(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """CC-01"""
    baseline = len(claims_of(seeded, CATHY))
    llm.push(claim_turn(**VALID_CLAIM))
    card = card_of(chat.say("taxi HKD 120 on 20 Sep"))
    values = field_values(card)
    assert values == {
        "employee_email": CATHY,
        "claim_type": "Travel",
        "amount": "HKD 120.00",
        "receipt_date": "Sun 2026-09-20",
    }
    assert card["confirm_label"] == "Submit" and adapter.calls == []

    done = chat.act(card["card_id"])
    assert ui_of(done)["outcome"] == "submitted"
    claims = claims_of(seeded, CATHY)
    assert len(claims) == baseline + 1
    row = claims[-1]
    assert row.status == RequestStatus.PENDING_APPROVAL and row.submitted_at is not None
    assert row.amount == Decimal("120.00") and row.currency == "HKD"
    assert row.conversation_id == chat.id

    with seeded.session_factory() as s:
        events = s.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_type == "claim_request", AuditEvent.entity_id == row.id)
            .order_by(AuditEvent.id)
        ).all()
        assert [e.event_type for e in events] == [
            "request.created",
            "request.confirmed",
            "submission.succeeded",
        ]
        sub = s.scalars(
            select(ExternalSubmission).where(
                ExternalSubmission.request_id == row.id, ExternalSubmission.request_type == "claim"
            )
        ).one()
        assert sub.request_payload_json == {
            "email": CATHY,
            "claim_type": "Travel",
            "amount": 120.0,
            "receipt_date": "2026-09-20",
        }
        finance_ids = set(s.scalars(select(User.id).where(User.role == UserRole.FINANCE_APPROVER)))
        notes = s.scalars(
            select(Notification).where(
                Notification.request_id == row.id, Notification.request_type == "claim"
            )
        ).all()
        assert {n.recipient_user_id for n in notes} == finance_ids


def test_two_decimal_amount(chat: Chat, llm: ScriptedLLM, seeded: Database) -> None:
    """CC-02: 12.3 (float) becomes exactly 12.30; 12.34 stays 12.34."""
    llm.push(claim_turn(claim_type=ClaimType.MEAL, amount=12.3, receipt_date=d("2026-09-24")))
    assert field_values(card_of(chat.say("lunch 12.3")))["amount"] == "HKD 12.30"
    llm.push(details_claim(amount=12.34))
    card = card_of(chat.say("sorry 12.34"))
    assert field_values(card)["amount"] == "HKD 12.34"
    chat.act(card["card_id"])
    assert claims_of(seeded, CATHY)[-1].amount == Decimal("12.34")


def test_amount_of_exactly_50000_is_accepted_until_phase_3(chat: Chat, llm: ScriptedLLM) -> None:
    """CC-03: no cap in Phase 2."""
    llm.push(claim_turn(claim_type=ClaimType.EQUIPMENT, amount=50000.0, receipt_date=TODAY))
    assert field_values(card_of(chat.say("laptop 50000")))["amount"] == "HKD 50,000.00"
    llm.push(details_claim(amount=1_000_000.0))
    assert field_values(card_of(chat.say("no, a million")))["amount"] == "HKD 1,000,000.00"


def test_receipt_today_and_old_receipts_are_accepted(chat: Chat, llm: ScriptedLLM) -> None:
    """CC-04 / CC-05: receipt today, and 90 or 200 days ago (age limits are Phase 3)."""
    for days_ago in (0, 90, 200):
        llm.push(
            claim_turn(
                claim_type=ClaimType.TRAINING,
                amount=99.0,
                receipt_date=TODAY - timedelta(days=days_ago),
            )
        )
        card = card_of(chat.say(f"claim from {days_ago} days ago"))
        assert card["action"] == "create"


# ---- failures / follow-ups ----------------------------------------------------------------------
@pytest.mark.parametrize("amount", [0.0, -5.0])
def test_zero_or_negative_amount(chat: Chat, llm: ScriptedLLM, amount: float) -> None:
    """CF-01"""
    llm.push(claim_turn(claim_type=ClaimType.MEAL, amount=amount, receipt_date=TODAY))
    resp = chat.say("claim")
    assert ui_of(resp) is None
    assert "must be greater than 0" in text_of(resp)
    llm.push(details_claim(amount=25.5))
    assert card_of(chat.say("25.5"))["action"] == "create"


def test_more_than_two_decimals_is_rejected_not_rounded(chat: Chat, llm: ScriptedLLM) -> None:
    """CF-02"""
    llm.push(claim_turn(claim_type=ClaimType.MEAL, amount=12.345, receipt_date=TODAY))
    resp = chat.say("lunch 12.345")
    assert ui_of(resp) is None
    assert "12.345 has more than 2 decimal places" in text_of(resp)
    llm.push(details_claim(amount=12.35))
    assert field_values(card_of(chat.say("12.35")))["amount"] == "HKD 12.35"


def test_non_hkd_currency_is_rejected(chat: Chat, llm: ScriptedLLM) -> None:
    """CF-03"""
    llm.push(
        claim_turn(claim_type=ClaimType.TRAVEL, amount=100.0, currency="USD", receipt_date=TODAY)
    )
    resp = chat.say("taxi USD 100")
    assert ui_of(resp) is None
    assert "HKD only" in text_of(resp) and "USD" in text_of(resp)
    llm.push(details_claim(amount=780.0, currency="HKD"))
    assert field_values(card_of(chat.say("HKD 780")))["amount"] == "HKD 780.00"


def test_future_receipt_date_is_rejected(chat: Chat, llm: ScriptedLLM) -> None:
    """CF-04"""
    llm.push(
        claim_turn(claim_type=ClaimType.MEAL, amount=40.0, receipt_date=TODAY + timedelta(days=1))
    )
    resp = chat.say("dinner tomorrow")
    assert ui_of(resp) is None
    assert "2026-09-26 is in the future" in text_of(resp)


def test_missing_fields_are_asked_one_at_a_time(chat: Chat, llm: ScriptedLLM) -> None:
    """CF-05"""
    llm.push(claim_turn())
    assert "What type of claim" in text_of(chat.say("I want to claim"))
    llm.push(details_claim(claim_type=ClaimType.OTHER))
    assert "How much" in text_of(chat.say("other"))
    llm.push(details_claim(amount=75.0))
    assert "date on the receipt" in text_of(chat.say("75"))
    llm.push(details_claim(receipt_date=d("2026-09-01")))
    assert card_of(chat.say("1 Sep"))["request_type"] == "claim"


def test_unknown_claim_type_lists_the_supported_types(chat: Chat, llm: ScriptedLLM) -> None:
    """CF-06"""
    llm.push(
        AgentTurn(
            intent=Intent.CREATE_CLAIM,
            claim=ClaimFields(amount=30.0, receipt_date=TODAY),
            confidence=0.8,
        )
    )
    resp = chat.say("claim for my gym membership")
    assert ui_of(resp) is None
    assert "travel, meal, equipment, training or other" in text_of(resp)


def test_nonfinite_amount_from_the_model_is_not_stored(chat: Chat, llm: ScriptedLLM) -> None:
    """CF-07"""
    llm.push(
        AgentTurn(
            intent=Intent.CREATE_CLAIM,
            claim=ClaimFields(claim_type=ClaimType.MEAL, amount=float("nan"), receipt_date=TODAY),
            confidence=0.8,
        )
    )
    resp = chat.say("claim lots")
    assert "couldn't read that amount" in text_of(resp)
    assert "How much" in text_of(resp)


def test_ambiguous_amount_is_not_merged(chat: Chat, llm: ScriptedLLM) -> None:
    """CF-08"""
    llm.push(
        AgentTurn(
            intent=Intent.CREATE_CLAIM,
            claim=ClaimFields(claim_type=ClaimType.MEAL, amount=15.0, receipt_date=TODAY),
            ambiguities=["amount: '15' could be 15 or 1500 cents"],
            confidence=0.9,
        )
    )
    resp = chat.say("lunch 15")
    assert ui_of(resp) is None
    assert "1500 cents" in text_of(resp)
    llm.push(details_claim(amount=15.0))
    card = card_of(chat.say("HKD 15"))
    assert field_values(card)["claim_type"] == "Meal"  # the unambiguous fields were kept


def test_amount_is_limited_to_12_digits_in_total(chat: Chat, llm: ScriptedLLM) -> None:
    """CF-09: ClaimDraft allows max_digits=12 with 2 decimals, i.e. up to 9,999,999,999.99."""
    llm.push(claim_turn(claim_type=ClaimType.OTHER, amount=1e12, receipt_date=TODAY))
    resp = chat.say("a trillion")
    assert ui_of(resp) is None
    assert text_of(resp) == "Amount is too large or has too many decimals. Please give it again."
    llm.push(details_claim(amount=9_999_999_999.99))
    assert field_values(card_of(chat.say("ten billion minus a cent")))["amount"] == (
        "HKD 9,999,999,999.99"
    )
