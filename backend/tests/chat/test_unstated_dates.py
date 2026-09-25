"""Fix A: a date the user never stated is not accepted (the live Ollama run filled today's date).

Fix B: a bare ``$``, ``HK$``, ``HKD$``, "dollars" and "HK dollars" are HKD; USD, ``US$`` and "US
dollars" are still rejected with the existing follow-up.

The guard in the backend merge is switched on for these tests with ``llm.trust_dates = False``
(the scripted double is trusted by default so the older tests can use dates from the script).
The provider-level guard has its own tests in ``tests/llm/test_llm_dates_currency.py``.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat.state import ConversationState, load_state
from app.db.models import ClaimRequest, Conversation
from app.db.session import Database
from app.llm.fake import FakeLLMProvider
from app.main import create_app
from tests.attachments.helpers import PNG, upload_ok
from tests.chat.conftest import AMY
from tests.chat.helpers import (
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
    text_of,
    ui_of,
)
from tests.chat.test_documents import receipt, receipt_turn, say_files
from tests.conftest import CSRF_HEADERS, login, make_settings

TODAY = d("2026-09-25")
ASK_DATE = "What is the date on the receipt?"


@pytest.fixture
def strict_llm(llm: ScriptedLLM) -> ScriptedLLM:
    llm.trust_dates = False  # the backend checks the dates against the user's words
    return llm


def as_user(app: FastAPI, email: str) -> Chat:
    client = TestClient(app, headers=CSRF_HEADERS)
    login(client, email)
    return Chat(client)


def state_of(seeded: Database, chat: Chat) -> ConversationState:
    with seeded.session_factory() as s:
        row = s.get(Conversation, chat.id)
        return load_state(row.state_json, row.active_request_type)


# ---- claims ----
def test_a_taxi_claim_without_a_date_asks_for_the_receipt_date(
    amy_chat: Chat, strict_llm: ScriptedLLM, seeded: Database
):
    """The real prompt wording of the live check. The model 'helpfully' returned today's date."""
    strict_llm.push(
        claim_turn(claim_type="travel", amount=180.0, currency="HKD", receipt_date=TODAY)
    )
    response = amy_chat.say("Claim HKD 180 for a taxi")
    assert text_of(response) == ASK_DATE
    assert ui_of(response) is None  # no card
    state = state_of(seeded, amy_chat)
    assert state.claim.receipt_date is None  # today was NOT stored
    assert str(state.claim.amount) == "180.0" and state.awaiting == "receipt_date"
    trace = response["assistant_messages"][-1]["trace"]
    merge = next(t for t in trace if t["step"] == "merge")
    assert "ignored a date you did not state (receipt_date)" in merge["detail"]


def test_the_answer_to_the_date_question_then_completes_the_card(
    amy_chat: Chat, strict_llm: ScriptedLLM
):
    strict_llm.push(
        claim_turn(claim_type="travel", amount=180.0, currency="HKD", receipt_date=TODAY)
    )
    assert text_of(amy_chat.say("Claim HKD 180 for a taxi")) == ASK_DATE
    strict_llm.push(details_claim(receipt_date=d("2026-09-24")))
    card = card_of(amy_chat.say("yesterday"))
    assert field_values(card)["receipt_date"] == "Thu 2026-09-24"
    assert field_values(card)["amount"] == "HKD 180.00"


@pytest.mark.parametrize(
    ("message", "given", "shown"),
    [
        ("Claim HKD 180 for a taxi yesterday", d("2026-09-24"), "Thu 2026-09-24"),
        ("Claim HKD 180 for a taxi today", TODAY, "Fri 2026-09-25"),
        ("Claim HKD 180 for a taxi on 22 Sep", d("2026-09-22"), "Tue 2026-09-22"),
        ("Claim HKD 180 for a taxi on 2026-09-22", d("2026-09-22"), "Tue 2026-09-22"),
        ("Claim HKD 180 for a taxi last Friday", d("2026-09-18"), "Fri 2026-09-18"),
        ("Claim HKD 180 for a taxi on 22/9", d("2026-09-22"), "Tue 2026-09-22"),
        ("HKD 180 taxi, 昨日", d("2026-09-24"), "Thu 2026-09-24"),
    ],
)
def test_a_stated_receipt_date_is_accepted(
    amy_chat: Chat, strict_llm: ScriptedLLM, message: str, given: Any, shown: str
):
    strict_llm.push(claim_turn(claim_type="travel", amount=180.0, receipt_date=given))
    card = card_of(amy_chat.say(message))
    assert field_values(card)["receipt_date"] == shown


def test_lunch_with_a_dollar_sign_and_an_iso_date_is_a_complete_hkd_claim(
    amy_chat: Chat, strict_llm: ScriptedLLM
):
    strict_llm.push(
        claim_turn(claim_type="meal", amount=65.5, currency="$", receipt_date=d("2026-09-22"))
    )
    card = card_of(amy_chat.say("claim $65.5 lunch on 2026-09-22"))
    assert field_values(card)["amount"] == "HKD 65.50"
    assert field_values(card)["receipt_date"] == "Tue 2026-09-22"


def test_an_invented_date_is_dropped_even_when_the_amount_is_in_the_same_message(
    amy_chat: Chat, strict_llm: ScriptedLLM, seeded: Database, adapter: RecordingAdapter
):
    strict_llm.push(claim_turn(claim_type="meal", amount=45.0, receipt_date=TODAY))
    response = amy_chat.say("lunch HKD 45")
    assert text_of(response) == ASK_DATE
    with seeded.session_factory() as s:
        assert s.query(ClaimRequest).count() == 10 and adapter.calls == []


def test_a_date_already_in_the_draft_is_not_treated_as_invented(
    amy_chat: Chat, strict_llm: ScriptedLLM
):
    """A model that repeats the draft's date on an unrelated reply keeps the value."""
    strict_llm.push(claim_turn(claim_type="meal", amount=45.0, receipt_date=d("2026-09-22")))
    assert card_of(amy_chat.say("lunch HKD 45 on 22 Sep"))["fields"]
    strict_llm.push(details_claim(amount=50.0, receipt_date=d("2026-09-22")))
    card = card_of(amy_chat.say("make it HKD 50"))
    assert field_values(card)["amount"] == "HKD 50.00"
    assert field_values(card)["receipt_date"] == "Tue 2026-09-22"


def test_a_model_that_changes_the_date_without_being_asked_does_not_win(
    amy_chat: Chat, strict_llm: ScriptedLLM
):
    strict_llm.push(claim_turn(claim_type="meal", amount=45.0, receipt_date=d("2026-09-22")))
    card_of(amy_chat.say("lunch HKD 45 on 22 Sep"))
    strict_llm.push(details_claim(amount=50.0, receipt_date=TODAY))  # a guess: today
    card = card_of(amy_chat.say("make it HKD 50"))
    assert field_values(card)["receipt_date"] == "Tue 2026-09-22"  # the user's date stays


# ---- leave ----
def test_leave_dates_the_user_never_gave_are_asked_not_assumed(
    amy_chat: Chat, strict_llm: ScriptedLLM, seeded: Database
):
    strict_llm.push(leave_turn(leave_type="annual", start_date=TODAY, end_date=TODAY))
    response = amy_chat.say("I would like some annual leave")
    assert "first day of your leave" in text_of(response)
    assert ui_of(response) is None
    state = state_of(seeded, amy_chat)
    assert state.leave.leave_type is not None
    assert state.leave.start_date is None and state.leave.end_date is None


def test_a_stated_leave_range_is_accepted(amy_chat: Chat, strict_llm: ScriptedLLM):
    strict_llm.push(
        leave_turn(leave_type="annual", start_date=d("2026-10-12"), end_date=d("2026-10-14"))
    )
    card = card_of(amy_chat.say("annual leave 2026-10-12 to 2026-10-14"))
    assert field_values(card)["start_date"] == "Mon 2026-10-12"
    assert field_values(card)["end_date"] == "Wed 2026-10-14"


def test_a_leave_start_date_stated_alone_still_asks_for_the_end_not_the_start(
    amy_chat: Chat, strict_llm: ScriptedLLM
):
    strict_llm.push(leave_turn(leave_type="annual", start_date=d("2026-10-12")))
    assert "just one day" in text_of(amy_chat.say("annual leave from Monday 12 Oct"))


def test_the_one_day_reply_needs_no_new_date_words(amy_chat: Chat, strict_llm: ScriptedLLM):
    strict_llm.push(leave_turn(leave_type="annual", start_date=d("2026-10-12")))
    amy_chat.say("annual leave from 12 Oct")
    # A model that answers "only that day please" with end = start: a repeated draft value.
    strict_llm.push(details_leave(end_date=d("2026-10-12")))
    card = card_of(amy_chat.say("only that day please"))
    assert field_values(card)["end_date"] == "Mon 2026-10-12"


def test_an_invented_end_date_after_a_stated_start_is_asked_not_kept(
    amy_chat: Chat, strict_llm: ScriptedLLM
):
    """A reply that states no date (and is not a "just one day" answer) cannot supply the end
    date, even if the model produces one."""
    strict_llm.push(leave_turn(leave_type="annual", start_date=d("2026-10-12")))
    amy_chat.say("annual leave starting 12 Oct")
    strict_llm.push(details_leave(end_date=d("2026-10-30")))  # invented
    response = amy_chat.say("hmm let me think")
    assert ui_of(response) is None
    assert "just one day" in text_of(response)


# ---- documents keep working ----
@pytest.fixture
def doc_app(seeded: Database, strict_llm: ScriptedLLM, adapter: RecordingAdapter, tmp_path: Path):
    return create_app(
        make_settings(upload_dir=str(tmp_path / "uploads")),
        database=seeded,
        llm_provider=strict_llm,
        submission_adapter=adapter,
    )


def test_a_date_read_from_a_receipt_is_accepted_without_any_typed_date(
    doc_app: FastAPI, strict_llm: ScriptedLLM
):
    chat = as_user(doc_app, AMY)
    file_id = int(upload_ok(chat.client, chat.id, PNG + b"receipt", filename="receipt.png")["id"])
    # The model copied the document's date to the top level AND the message says no date.
    turn = receipt_turn().model_copy(
        update={
            "claim": claim_turn(claim_type="meal", amount=83.6, receipt_date=d("2026-09-20")).claim
        }
    )
    strict_llm.push(turn)
    card = card_of(say_files(chat, "please claim this", file_id))
    assert field_values(card)["receipt_date"] == "Sun 2026-09-20"
    assert card["fields"][-1]["source"] == "document"


def test_a_typed_guess_next_to_a_receipt_is_replaced_by_the_documents_date(
    doc_app: FastAPI, strict_llm: ScriptedLLM
):
    chat = as_user(doc_app, AMY)
    file_id = int(upload_ok(chat.client, chat.id, PNG + b"receipt", filename="receipt.png")["id"])
    turn = receipt_turn(receipt(receipt_date=d("2026-09-20"))).model_copy(
        update={"claim": claim_turn(amount=83.6, receipt_date=TODAY).claim}  # today = invented
    )
    strict_llm.push(turn)
    card = card_of(say_files(chat, "please claim this", file_id))
    assert field_values(card)["receipt_date"] == "Sun 2026-09-20"
    assert card["warnings"] == []  # nothing typed, so no "you gave X but the document shows Y"


def test_a_receipt_without_a_date_still_asks_for_it_by_name(
    doc_app: FastAPI, strict_llm: ScriptedLLM
):
    chat = as_user(doc_app, AMY)
    file_id = int(upload_ok(chat.client, chat.id, PNG + b"receipt", filename="receipt.png")["id"])
    turn = receipt_turn(receipt(receipt_date=None, unreadable_fields=["receipt_date"]))
    turn = turn.model_copy(update={"claim": claim_turn(amount=83.6, receipt_date=TODAY).claim})
    strict_llm.push(turn)
    response = say_files(chat, "please claim this", file_id)
    assert "could not read the receipt date on receipt.png" in text_of(response)
    assert ui_of(response) is None


# ---- Fix B: currency ----
@pytest.mark.parametrize("written", ["$", "HK$", "HKD$", "dollars", "HK dollars", "hkd", "HKD"])
def test_dollar_wordings_are_hkd_all_the_way_to_the_request(
    amy_chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, written: str
):
    llm.push(
        claim_turn(claim_type="meal", amount=65.5, currency=written, receipt_date=d("2026-09-22"))
    )
    card = card_of(amy_chat.say("claim lunch on 22 Sep"))
    assert field_values(card)["amount"] == "HKD 65.50"
    result = ui_of(amy_chat.act(card["card_id"]))
    assert result["outcome"] == "submitted"
    assert adapter.calls[0][1]["amount"] == 65.5


@pytest.mark.parametrize("written", ["USD", "US$", "US dollars", "us dollar", "usd$"])
def test_us_dollars_are_still_rejected_with_the_existing_follow_up(
    amy_chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, written: str
):
    llm.push(
        claim_turn(claim_type="meal", amount=50.0, currency=written, receipt_date=d("2026-09-22"))
    )
    response = amy_chat.say("claim lunch on 22 Sep")
    assert text_of(response) == (
        "Claims are accepted in HKD only, and you mentioned USD. What is the amount in HKD?"
    )
    assert ui_of(response) is None and adapter.calls == []


def test_another_explicit_currency_is_rejected_by_its_code(amy_chat: Chat, llm: ScriptedLLM):
    llm.push(
        claim_turn(claim_type="meal", amount=50.0, currency="eur", receipt_date=d("2026-09-22"))
    )
    assert "you mentioned EUR" in text_of(amy_chat.say("claim lunch on 22 Sep"))


def test_after_a_rejected_currency_an_hkd_amount_completes_the_claim(
    amy_chat: Chat, llm: ScriptedLLM
):
    llm.push(
        claim_turn(claim_type="meal", amount=50.0, currency="US$", receipt_date=d("2026-09-22"))
    )
    assert "HKD only" in text_of(amy_chat.say("claim lunch US$50 on 22 Sep"))
    llm.push(details_claim(amount=390.0, currency="HK$"))
    card = card_of(amy_chat.say("HK$390"))
    assert field_values(card)["amount"] == "HKD 390.00"


def test_the_fake_provider_end_to_end_taxi_without_a_date_and_dollar_words(
    seeded: Database, adapter: RecordingAdapter
):
    """No script at all: the real rule-based provider and the real graph."""
    app = create_app(
        make_settings(), database=seeded, llm_provider=FakeLLMProvider(), submission_adapter=adapter
    )
    client = as_user(app, AMY).client
    chat = Chat(client)
    assert text_of(chat.say("Claim HKD 180 for a taxi")) == ASK_DATE
    card = card_of(chat.say("yesterday"))
    assert field_values(card)["receipt_date"] == "Thu 2026-09-24"
    chat2 = Chat(client)
    card = card_of(chat2.say("claim 80 HK dollars for lunch on 2026-09-22"))
    assert field_values(card)["amount"] == "HKD 80.00"
    chat3 = Chat(client)
    response = chat3.say("claim 50 US dollars for a hotel on 2026-09-22")
    assert "you mentioned USD" in text_of(response)
