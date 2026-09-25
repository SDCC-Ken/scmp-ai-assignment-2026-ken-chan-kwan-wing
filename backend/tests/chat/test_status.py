"""STATUS: asking about own requests in the chat (ids in docs/test-cases.md)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.db.models import ClaimRequest
from app.db.session import Database
from app.domain.enums import ClaimType, RequestStatus, RequestType
from tests.chat.helpers import (
    AMY_PENDING_LEAVE,
    BEN_REJECTED_CLAIM,
    BEN_REJECTED_LEAVE,
    Chat,
    ScriptedLLM,
    status_turn,
    submit_leave,
    text_of,
    ui_of,
)
from tests.conftest import get_user

LEAVE = RequestType.LEAVE
CLAIM = RequestType.CLAIM


def test_status_by_type_lists_only_own_requests(amy_chat: Chat, llm: ScriptedLLM) -> None:
    """SS-01: Amy has 4 leaves (L1, L5, L8, L10) in the seed; nobody else's appear."""
    llm.push(status_turn(request_type=LEAVE))
    resp = amy_chat.say("show my leave requests")
    card = ui_of(resp)
    assert card["type"] == "status_card" and card["empty"] is False
    assert {r["request_type"] for r in card["requests"]} == {"leave"}
    assert len(card["requests"]) == 4
    assert AMY_PENDING_LEAVE in {r["id"] for r in card["requests"]}
    assert "Here are your 4 most recent leave requests." in text_of(resp)
    trace = resp["assistant_messages"][0]["trace"]
    assert any(t["step"] == "status" for t in trace)


def test_status_by_id(amy_chat: Chat, llm: ScriptedLLM) -> None:
    """SS-02"""
    llm.push(status_turn(request_type=LEAVE, request_id=AMY_PENDING_LEAVE))
    resp = amy_chat.say(f"what is the status of leave #{AMY_PENDING_LEAVE}?")
    card = ui_of(resp)
    assert [r["id"] for r in card["requests"]] == [AMY_PENDING_LEAVE]
    item = card["requests"][0]
    assert item["status"] == "pending_approval" and item["status_label"] == "Pending approval"
    assert item["summary"].startswith("Annual leave, ")
    assert item["submitted_at"].endswith("Z") and item["reviewed_at"] is None
    assert item["external_reference_id"] == "mock-ref-leave-0001"
    assert "Pending approval" in text_of(resp)


def test_status_filter_by_status(amy_chat: Chat, llm: ScriptedLLM) -> None:
    """SS-03"""
    llm.push(status_turn(status=RequestStatus.PENDING_APPROVAL))
    card = ui_of(amy_chat.say("what is still pending?"))
    assert {(r["request_type"], r["status"]) for r in card["requests"]} == {
        ("leave", "pending_approval"),
        ("claim", "pending_approval"),
    }


def test_status_none_found(chat: Chat, llm: ScriptedLLM) -> None:
    """SS-04: Cathy has no rejected requests."""
    llm.push(status_turn(status=RequestStatus.REJECTED))
    resp = chat.say("any rejected requests?")
    assert ui_of(resp) == {"type": "status_card", "requests": [], "empty": True}
    assert "You don't have any requests with status Rejected." in text_of(resp)


def test_status_of_another_employees_id_is_refused(chat: Chat, llm: ScriptedLLM) -> None:
    """SS-05: Amy's leave id looks nonexistent to Cathy."""
    llm.push(status_turn(request_type=LEAVE, request_id=AMY_PENDING_LEAVE))
    resp = chat.say(f"status of leave #{AMY_PENDING_LEAVE}")
    assert ui_of(resp)["empty"] is True
    assert f"couldn't find a request with id {AMY_PENDING_LEAVE}" in text_of(resp)
    assert "Amy" not in text_of(resp) and "Annual" not in text_of(resp)


def test_rejected_request_shows_the_reviewer_note(ben_chat: Chat, llm: ScriptedLLM) -> None:
    """SS-06"""
    llm.push(status_turn(request_type=LEAVE, request_id=BEN_REJECTED_LEAVE))
    resp = ben_chat.say("why was my leave rejected?")
    item = ui_of(resp)["requests"][0]
    assert item["status"] == "rejected"
    assert item["reviewer_note"] == "Team is short-staffed that week; please pick another date."
    assert item["reviewed_at"] is not None
    assert "reviewer note: Team is short-staffed" in text_of(resp)
    llm.push(status_turn(request_type=CLAIM, request_id=BEN_REJECTED_CLAIM))
    item = ui_of(ben_chat.say("and my claim?"))["requests"][0]
    assert item["reviewer_note"].startswith("Receipt is missing the vendor name")


def test_status_shows_only_the_ten_most_recent(
    chat: Chat, llm: ScriptedLLM, seeded: Database
) -> None:
    """SS-07: Cathy has 3 seeded claims; add 12 more, the card shows the newest 10."""
    user = get_user(seeded, "cathy.ng@example.com")
    base = datetime(2026, 9, 20, tzinfo=UTC)
    with seeded.session_factory() as s:
        for i in range(12):
            s.add(
                ClaimRequest(
                    employee_id=user.id,
                    claim_type=ClaimType.MEAL,
                    amount=Decimal(f"{i + 1}.00"),
                    currency="HKD",
                    receipt_date=date(2026, 9, 1) + timedelta(days=i),
                    status=RequestStatus.PENDING_APPROVAL,
                    created_at=base + timedelta(hours=i),
                )
            )
        s.commit()
    llm.push(status_turn(request_type=CLAIM))
    resp = chat.say("show my claims")
    items = ui_of(resp)["requests"]
    assert len(items) == 10
    amounts = [i["summary"] for i in items]
    assert "HKD 12.00" in amounts[0] and "HKD 3.00" in amounts[-1]  # newest first
    assert "Here are your 10 most recent claims." in text_of(resp)


def test_status_includes_a_newly_submitted_request_with_its_reference(
    chat: Chat, llm: ScriptedLLM
) -> None:
    """SS-08"""
    rid = submit_leave(chat, llm)
    llm.push(status_turn(request_type=LEAVE, request_id=rid))
    item = ui_of(chat.say("status?"))["requests"][0]
    assert item["status"] == "pending_approval" and item["external_reference_id"] == "101"
    assert item["summary"] == "Annual leave, Mon 2026-10-05 to Wed 2026-10-07 (3 working days)"
