"""Phase 3-C: dates the user never stated, HKD wording, and the new ``check_balance`` intent.

All offline. The Ollama provider runs against ``httpx.MockTransport`` with a model that
misbehaves the way the live gemma4 run did: it fills today's date when the user gave none.
"""

import json
from datetime import date
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.llm.currency import mentions_dollars, normalise_currency, says_hkd, says_usd
from app.llm.dates import claim_dates, drop_unstated_dates, leave_dates, mentions_a_date
from app.llm.gemini import RESPONSE_SCHEMA, WireTurn
from app.llm.ollama import OllamaProvider
from app.llm.prompts import SYSTEM_PROMPT, build_ollama_system_prompt
from app.llm.schemas import AgentTurn, ClaimFields, Intent, LeaveFields, LLMContext
from app.llm.structured import build_flat_schema, correct_currency, parse_flat_turn

TODAY = date(2026, 9, 25)  # Friday


def ctx(**kw: Any) -> LLMContext:
    base: dict[str, Any] = {"today": TODAY, "weekday": "Friday", "user_display_name": "Amy Lau"}
    base.update(kw)
    return LLMContext(**base)


def flat(**kw: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "intent": "unclear",
        "request_type": "",
        "leave_type": "",
        "start_date": "",
        "end_date": "",
        "start_day_part": "",
        "end_day_part": "",
        "claim_type": "",
        "amount": "",
        "currency": "",
        "receipt_date": "",
        "target_request_id": 0,
        "confidence": 0.9,
    }
    data.update(kw)
    return data


def ollama(reply: dict[str, Any]) -> OllamaProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps(reply)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    settings = Settings(_env_file=None, ollama_base_url="http://ollama.test:11434")
    return OllamaProvider(settings, transport=httpx.MockTransport(handler))


# ---- what counts as "the user stated a date" ----
@pytest.mark.parametrize(
    "text",
    [
        "claim HKD 65 on 2026-09-22",
        "taxi 22/9",
        "taxi 22-9-2026",
        "taxi 22.9.2026",
        "claim for 22 Sep",
        "claim for 22nd of September",
        "claim for Sep 22",
        "claim for September 22nd",
        "lunch yesterday",
        "lunch today",
        "taxi last night",
        "leave tomorrow",
        "leave the day after tomorrow",
        "leave next monday",
        "leave on Friday",
        "leave next week",
        "leave this weekend",
        "the 5th",
        "the 22nd please",
        "extend it by 2 days",
        "take 3 days off",
        "extend it by a day",
        "taxi 3 days ago",
        "taxi a week ago",
        "昨日搭的士",
        "今日請假",
        "請假 10月5日",
        "請假下星期一",
        "5號請假",
    ],
)
def test_date_expressions_are_recognised(text: str) -> None:
    assert mentions_a_date(text), text


@pytest.mark.parametrize(
    "text",
    [
        "Claim HKD 180 for a taxi",
        "claim $65.5 lunch",
        "taxi HKD 12.50",
        "I want annual leave",
        "I want to take a day off",
        "make it sick leave",
        "yes",
        "just one day",
        "may I claim a taxi",
        "reimburse 300 dollars for a keyboard",
        "",
        None,
    ],
)
def test_messages_without_a_date_are_recognised(text: str | None) -> None:
    assert not mentions_a_date(text), text


# ---- dropping a date the user did not state ----
def test_receipt_date_is_dropped_when_the_message_states_none() -> None:
    fields = ClaimFields(claim_type="travel", amount=180, currency="HKD", receipt_date=TODAY)
    cleaned, dropped = drop_unstated_dates(fields, "Claim HKD 180 for a taxi")
    assert dropped == ["receipt_date"]
    assert isinstance(cleaned, ClaimFields)
    assert cleaned.receipt_date is None
    assert cleaned.amount == 180 and cleaned.claim_type is not None  # everything else stays


def test_leave_dates_are_dropped_when_the_message_states_none() -> None:
    fields = LeaveFields(leave_type="annual", start_date=TODAY, end_date=TODAY)
    cleaned, dropped = drop_unstated_dates(fields, "I need annual leave")
    assert dropped == ["start_date", "end_date"]
    assert isinstance(cleaned, LeaveFields) and cleaned.leave_type is not None
    assert cleaned.start_date is None and cleaned.end_date is None


def test_an_object_with_nothing_left_becomes_none() -> None:
    fields = LeaveFields(start_date=TODAY, end_date=TODAY)
    assert drop_unstated_dates(fields, "hello there") == (None, ["start_date", "end_date"])
    assert drop_unstated_dates(None, "hello there") == (None, [])


def test_a_stated_date_is_kept_and_a_date_the_draft_already_holds_is_not_invented() -> None:
    fields = ClaimFields(amount=10, receipt_date=date(2026, 9, 22))
    assert drop_unstated_dates(fields, "taxi on 22 Sep") == (fields, [])
    assert drop_unstated_dates(fields, "yes", known={date(2026, 9, 22)}) == (fields, [])
    _, dropped = drop_unstated_dates(fields, "yes", known={date(2026, 9, 1)})
    assert dropped == ["receipt_date"]


def test_known_dates_helpers() -> None:
    assert leave_dates(LeaveFields(start_date=TODAY)) == {TODAY}
    assert leave_dates(None) == set()
    assert claim_dates(ClaimFields(receipt_date=TODAY)) == {TODAY}
    assert claim_dates(None) == set()


# ---- the Ollama provider: the real prompt wording from the live check ----
def test_ollama_taxi_without_a_date_does_not_keep_todays_date() -> None:
    """Live finding: gemma4 answered receipt_date = today for this exact message."""
    model = ollama(
        flat(
            intent="create_claim",
            request_type="claim",
            claim_type="travel",
            amount="180",
            currency="HKD",
            receipt_date=TODAY.isoformat(),
        )
    )
    turn = model.analyse("Claim HKD 180 for a taxi", ctx())
    assert turn.intent is Intent.CREATE_CLAIM
    assert turn.claim is not None
    assert turn.claim.amount == 180 and turn.claim.currency == "HKD"
    assert (
        turn.claim.receipt_date is None
    )  # the backend will ask "What is the date on the receipt?"


@pytest.mark.parametrize(
    ("message", "given", "kept"),
    [
        ("claim $65.5 lunch on 2026-09-22", "2026-09-22", date(2026, 9, 22)),
        ("Claim HKD 65 for a taxi yesterday", "2026-09-24", date(2026, 9, 24)),
        ("Claim HKD 65 for a taxi on 22 Sep", "2026-09-22", date(2026, 9, 22)),
        ("taxi HKD 65 last Friday", "2026-09-18", date(2026, 9, 18)),
    ],
)
def test_ollama_keeps_a_stated_receipt_date(message: str, given: str, kept: date) -> None:
    model = ollama(
        flat(
            intent="create_claim",
            request_type="claim",
            claim_type="meal",
            amount="65",
            receipt_date=given,
        )
    )
    turn = model.analyse(message, ctx())
    assert turn.claim is not None and turn.claim.receipt_date == kept


def test_ollama_never_keeps_invented_leave_dates() -> None:
    model = ollama(
        flat(
            intent="create_leave",
            request_type="leave",
            leave_type="annual",
            start_date=TODAY.isoformat(),
            end_date=TODAY.isoformat(),
        )
    )
    turn = model.analyse("I would like some annual leave", ctx())
    assert turn.leave is not None and turn.leave.leave_type is not None
    assert turn.leave.start_date is None and turn.leave.end_date is None


def test_ollama_keeps_the_leave_dates_of_a_real_request() -> None:
    model = ollama(
        flat(
            intent="create_leave",
            request_type="leave",
            leave_type="annual",
            start_date="2026-10-12",
            end_date="2026-10-14",
        )
    )
    turn = model.analyse("annual leave 2026-10-12 to 2026-10-14", ctx())
    assert turn.leave is not None
    assert (turn.leave.start_date, turn.leave.end_date) == (date(2026, 10, 12), date(2026, 10, 14))


def test_ollama_one_day_reply_keeps_the_drafts_own_start_date() -> None:
    """A reply with no date: end = the draft's own start date is a repeated, not invented, value."""
    model = ollama(
        flat(
            intent="provide_details",
            request_type="leave",
            end_date="2026-10-05",
        )
    )
    context = ctx(
        active_request_type="leave",
        awaiting="end_date",
        current_leave=LeaveFields(leave_type="annual", start_date=date(2026, 10, 5)),
    )
    turn = model.analyse("only that day please", context)
    assert turn.leave is not None and turn.leave.end_date == date(2026, 10, 5)


# ---- HKD wording ----
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$", "HKD"),
        ("HK$", "HKD"),
        ("hk$", "HKD"),
        ("HKD$", "HKD"),
        ("hkd", "HKD"),
        ("dollars", "HKD"),
        ("Dollar", "HKD"),
        ("HK dollars", "HKD"),
        ("  hk   dollar ", "HKD"),
        ("Hong Kong dollars", "HKD"),
        ("USD", "USD"),
        ("US$", "USD"),
        ("us dollars", "USD"),
        ("US Dollar", "USD"),
        ("eur", "EUR"),
        ("RMB", "CNY"),
        ("", None),
        ("   ", None),
        (None, None),
        (True, None),
    ],
)
def test_currency_wording(raw: Any, expected: str | None) -> None:
    assert normalise_currency(raw) == expected


def test_currency_message_helpers() -> None:
    assert says_usd("claim USD 50") and says_usd("US$50") and says_usd("50 US dollars")
    assert not says_usd("claim $50") and not says_usd("HK$50")
    assert says_hkd("HK$50") and says_hkd("HK dollars") and says_hkd("hkd 50")
    assert not says_hkd("claim $50")
    assert mentions_dollars("$65.5") and mentions_dollars("65 dollars")
    assert not mentions_dollars("HKD 65")


def _claim_turn(currency: str) -> AgentTurn:
    return parse_flat_turn(
        json.dumps(
            flat(intent="create_claim", request_type="claim", amount="65.5", currency=currency)
        )
    )


@pytest.mark.parametrize(
    ("message", "model_says", "expected"),
    [
        ("lunch $65.5", "USD", "HKD"),
        ("lunch HK$65.5", "USD", "HKD"),
        ("lunch HKD$65.5", "USD", "HKD"),
        ("lunch 65.5 dollars", "USD", "HKD"),
        ("lunch 65.5 HK dollars", "USD", "HKD"),
        ("lunch $65.5", "", None),  # no currency at all: the backend defaults to HKD
        ("lunch USD 65.5", "HKD", "USD"),
        ("lunch US$65.5", "HKD", "USD"),
        ("lunch 65.5 US dollars", "HKD", "USD"),
        ("lunch 65.5 US dollars", "USD", "USD"),
        ("lunch 65.5 eur", "EUR", "EUR"),
        ("lunch HKD 65.5", "HKD", "HKD"),
    ],
)
def test_currency_guard_for_text_turns(message: str, model_says: str, expected: str | None) -> None:
    assert correct_currency(_claim_turn(model_says), message).claim.currency == expected  # type: ignore[union-attr]


def test_the_flat_parser_reads_dollar_words_as_hkd_and_us_dollars_as_usd() -> None:
    assert _claim_turn("HK$").claim.currency == "HKD"  # type: ignore[union-attr]
    assert _claim_turn("HKD$").claim.currency == "HKD"  # type: ignore[union-attr]
    assert _claim_turn("$").claim.currency == "HKD"  # type: ignore[union-attr]
    assert _claim_turn("HK dollars").claim.currency == "HKD"  # type: ignore[union-attr]
    assert _claim_turn("US dollars").claim.currency == "USD"  # type: ignore[union-attr]
    assert _claim_turn("US$").claim.currency == "USD"  # type: ignore[union-attr]


def test_ollama_lunch_with_a_dollar_sign_is_hkd() -> None:
    """Live check wording: "claim $65.5 lunch on 2026-09-22" (small models answer USD)."""
    model = ollama(
        flat(
            intent="create_claim",
            request_type="claim",
            claim_type="meal",
            amount="65.5",
            currency="USD",
            receipt_date="2026-09-22",
        )
    )
    turn = model.analyse("claim $65.5 lunch on 2026-09-22", ctx())
    assert turn.claim is not None
    assert turn.claim.currency == "HKD" and turn.claim.receipt_date == date(2026, 9, 22)


# ---- the check_balance intent is known to both providers ----
def test_check_balance_is_an_intent_and_never_an_approval_action() -> None:
    assert Intent.CHECK_BALANCE.value == "check_balance"
    assert not {i.value for i in Intent} & {"approve", "reject"}


def test_the_gemini_wire_schema_mirrors_the_new_intent() -> None:
    assert set(WireTurn.model_fields) == set(AgentTurn.model_fields)
    assert "check_balance" in RESPONSE_SCHEMA["properties"]["intent"]["enum"]
    assert set(RESPONSE_SCHEMA["properties"]["intent"]["enum"]) == {i.value for i in Intent}


def test_the_ollama_flat_schema_lists_the_new_intent() -> None:
    enum = build_flat_schema(0)["properties"]["intent"]["enum"]
    assert "check_balance" in enum and set(enum) == {i.value for i in Intent}


def test_both_prompts_explain_check_balance_and_no_default_dates() -> None:
    gemini = SYSTEM_PROMPT
    ollama_prompt = build_ollama_system_prompt(False)
    for prompt in (gemini, ollama_prompt):
        assert "check_balance" in prompt
        assert "leave days do I have left" in prompt or "leave days they have" in prompt
        assert "NEVER use today's date" in prompt
        assert "HK dollars" in prompt
        assert "US dollars" in prompt
    assert "state a number yourself" in gemini  # the model never words numbers
    assert "Claim HKD 180 for a taxi" in ollama_prompt
    assert len(ollama_prompt) < 6000  # the compact prompt stays compact


def test_a_check_balance_reply_round_trips_through_both_parsers() -> None:
    flat_turn = parse_flat_turn(json.dumps(flat(intent="check_balance")))
    assert flat_turn.intent is Intent.CHECK_BALANCE
    assert flat_turn.leave is None and flat_turn.claim is None and flat_turn.target is None
    wire = WireTurn.model_validate({"intent": "check_balance"})
    assert AgentTurn.model_validate(wire.model_dump()).intent is Intent.CHECK_BALANCE
