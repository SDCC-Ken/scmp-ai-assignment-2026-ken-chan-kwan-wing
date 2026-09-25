"""CANCEL (delete) of leave and claims: success and failure (ids in docs/test-cases.md)."""

from sqlalchemy import select

from app.db.models import AuditEvent, ClaimRequest, LeaveRequest
from app.db.session import Database
from app.domain.enums import RequestStatus, RequestType
from tests.chat.helpers import (
    AMY_PENDING_LEAVE,
    BEN_REJECTED_CLAIM,
    BEN_REJECTED_LEAVE,
    CATHY_APPROVED_CLAIM,
    CATHY_APPROVED_LEAVE,
    Chat,
    RecordingAdapter,
    ScriptedLLM,
    cancel_turn,
    card_of,
    d,
    leave_turn,
    submit_claim,
    submit_leave,
    text_of,
    ui_of,
)

LEAVE = RequestType.LEAVE
CLAIM = RequestType.CLAIM


def status_of(db: Database, model: type, request_id: int) -> RequestStatus:
    with db.session_factory() as s:
        return s.get(model, request_id).status


def audit_types(db: Database, entity: str, request_id: int) -> list[str]:
    with db.session_factory() as s:
        return [
            e.event_type
            for e in s.scalars(
                select(AuditEvent)
                .where(AuditEvent.entity_type == entity, AuditEvent.entity_id == request_id)
                .order_by(AuditEvent.id)
            )
        ]


# ---- success -------------------------------------------------------------------------------------
def test_cancel_a_pending_leave(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """XC-01"""
    rid = submit_leave(chat, llm)
    llm.push(cancel_turn(request_id=rid, request_type=LEAVE))
    card = card_of(chat.say(f"cancel leave #{rid}"))
    assert card["action"] == "cancel" and card["request_id"] == rid
    assert card["confirm_label"] == "Cancel request"
    assert {f["key"]: f["value"] for f in card["fields"]}["status"] == "Pending approval"
    assert status_of(seeded, LeaveRequest, rid) == RequestStatus.PENDING_APPROVAL  # not yet

    done = chat.act(card["card_id"])
    result = ui_of(done)
    assert result["outcome"] == "cancelled" and result["status"] == "cancelled"
    assert status_of(seeded, LeaveRequest, rid) == RequestStatus.CANCELLED
    assert len(adapter.calls) == 1  # only the original submission: cancel is local
    assert audit_types(seeded, "leave_request", rid)[-1] == "request.cancelled"
    with seeded.session_factory() as s:
        event = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == rid, AuditEvent.event_type == "request.cancelled"
            )
        ).one()
        assert (event.from_status, event.to_status) == ("pending_approval", "cancelled")
        assert event.actor_user_id is not None


def test_cancel_a_pending_claim(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """XC-02"""
    rid = submit_claim(chat, llm)
    llm.push(cancel_turn(request_id=rid, request_type=CLAIM))
    done = chat.act(card_of(chat.say(f"cancel claim #{rid}"))["card_id"])
    assert ui_of(done)["outcome"] == "cancelled"
    assert status_of(seeded, ClaimRequest, rid) == RequestStatus.CANCELLED
    assert len(adapter.calls) == 1


def test_cancel_a_submission_failed_request_makes_no_external_call(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """XC-03"""
    adapter.fail_next()
    llm.push(leave_turn(leave_type="annual", start_date=d("2026-10-05"), end_date=d("2026-10-06")))
    failed = chat.act(card_of(chat.say("annual leave"))["card_id"])
    rid = ui_of(failed, 0)["request_id"]
    retry_card = failed["assistant_messages"][1]["ui"]
    assert retry_card["action"] == "retry"
    llm.push(cancel_turn(request_id=rid, request_type=LEAVE))
    card = card_of(chat.say("forget it, cancel"))
    assert card["action"] == "cancel"
    done = chat.act(card["card_id"])
    assert ui_of(done)["outcome"] == "cancelled"
    assert status_of(seeded, LeaveRequest, rid) == RequestStatus.CANCELLED
    assert len(adapter.calls) == 1  # the failed attempt only
    # the superseded retry card is shown as such when the conversation is reopened
    states = {
        m["ui"]["card_id"]: m["ui"]["state"]
        for m in chat.detail()["messages"]
        if m["ui"] and m["ui"]["type"] == "confirmation_card"
    }
    assert states[retry_card["card_id"]] == "superseded"


def test_cancel_target_is_inferred_and_hinted(chat: Chat, llm: ScriptedLLM) -> None:
    """XC-04: a single editable request needs no id; with two, a hint picks one."""
    first = submit_leave(chat, llm)
    llm.push(cancel_turn())
    assert card_of(chat.say("cancel my leave"))["request_id"] == first
    second = submit_claim(chat, llm)
    llm.push(cancel_turn(request_type=CLAIM, hint="the travel claim"))
    assert card_of(chat.say("cancel my travel claim"))["request_id"] == second


def test_discard_leaves_everything_unchanged(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """XC-05"""
    rid = submit_leave(chat, llm)
    llm.push(cancel_turn(request_id=rid, request_type=LEAVE))
    card = card_of(chat.say("cancel it"))
    done = chat.act(card["card_id"], "discard")
    assert "nothing was cancelled" in text_of(done).lower()
    assert done["assistant_messages"][0]["ui"] is None
    assert status_of(seeded, LeaveRequest, rid) == RequestStatus.PENDING_APPROVAL
    assert len(adapter.calls) == 1
    assert "request.cancelled" not in audit_types(seeded, "leave_request", rid)
    assert chat.detail()["conversation"]["has_pending_card"] is False
    assert chat.act_raw(card["card_id"]).status_code == 409  # the card is closed for good
    states = [
        m["ui"]["state"]
        for m in chat.detail()["messages"]
        if m["ui"] and m["ui"]["type"] == "confirmation_card" and m["ui"]["action"] == "cancel"
    ]
    assert states == ["discarded"]


# ---- failures ------------------------------------------------------------------------------------
def test_approved_request_cannot_be_cancelled(chat: Chat, llm: ScriptedLLM) -> None:
    """XF-01"""
    llm.push(cancel_turn(request_id=CATHY_APPROVED_LEAVE, request_type=LEAVE))
    resp = chat.say("cancel my approved leave")
    assert ui_of(resp) is None
    assert "Approved" in text_of(resp) and "can't be cancelled" in text_of(resp)
    llm.push(cancel_turn(request_id=CATHY_APPROVED_CLAIM, request_type=CLAIM))
    assert "can't be cancelled" in text_of(chat.say("cancel my approved claim"))


def test_rejected_request_cannot_be_cancelled(ben_chat: Chat, llm: ScriptedLLM) -> None:
    """XF-02"""
    llm.push(cancel_turn(request_id=BEN_REJECTED_LEAVE, request_type=LEAVE))
    resp = ben_chat.say("cancel my rejected leave")
    assert "Rejected" in text_of(resp) and "can't be cancelled" in text_of(resp)
    llm.push(cancel_turn(request_id=BEN_REJECTED_CLAIM, request_type=CLAIM))
    assert "can't be cancelled" in text_of(ben_chat.say("cancel my rejected claim"))


def test_already_cancelled_request(chat: Chat, llm: ScriptedLLM, seeded: Database) -> None:
    """XF-03"""
    rid = submit_leave(chat, llm)
    llm.push(cancel_turn(request_id=rid, request_type=LEAVE))
    chat.act(card_of(chat.say("cancel it"))["card_id"])
    llm.push(cancel_turn(request_id=rid, request_type=LEAVE))
    resp = chat.say("cancel it again")
    assert ui_of(resp) is None
    assert "Cancelled" in text_of(resp) and "can't be cancelled" in text_of(resp)


def test_another_employees_request_cannot_be_cancelled(
    chat: Chat, llm: ScriptedLLM, seeded: Database
) -> None:
    """XF-04"""
    llm.push(cancel_turn(request_id=AMY_PENDING_LEAVE, request_type=LEAVE))
    resp = chat.say(f"cancel leave #{AMY_PENDING_LEAVE}")
    assert ui_of(resp) is None
    assert f"couldn't find a request with id {AMY_PENDING_LEAVE}" in text_of(resp)
    assert status_of(seeded, LeaveRequest, AMY_PENDING_LEAVE) == RequestStatus.PENDING_APPROVAL


def test_nonexistent_request_id(chat: Chat, llm: ScriptedLLM) -> None:
    """XF-05"""
    llm.push(cancel_turn(request_id=424242))
    assert "couldn't find a request with id 424242" in text_of(chat.say("cancel 424242"))


def test_cancel_when_only_final_requests_exist(chat: Chat, llm: ScriptedLLM) -> None:
    """XF-06: Cathy only has approved requests in the seed."""
    llm.push(cancel_turn(request_type=LEAVE, hint="the leave in December"))
    resp = chat.say("cancel my december leave")
    assert ui_of(resp) is None
    assert "None of your requests can be cancelled" in text_of(resp)


def test_ambiguous_cancel_target_lists_candidates(amy_chat: Chat, llm: ScriptedLLM) -> None:
    """XF-07: Amy has a pending leave and a pending claim in the seed."""
    llm.push(cancel_turn())
    resp = amy_chat.say("cancel my request")
    assert ui_of(resp) is None
    assert "Which request do you mean?" in text_of(resp)


def test_cancel_confirmation_after_the_request_became_final(
    chat: Chat, llm: ScriptedLLM, seeded: Database
) -> None:
    """XF-08: an approver rejects it between the card and the Confirm click."""
    from datetime import UTC, datetime

    rid = submit_leave(chat, llm)
    llm.push(cancel_turn(request_id=rid, request_type=LEAVE))
    card = card_of(chat.say("cancel it"))
    with seeded.session_factory() as s:
        row = s.get(LeaveRequest, rid)
        row.status = RequestStatus.REJECTED
        row.reviewed_by_user_id = 4
        row.reviewed_at = datetime.now(UTC)
        row.reviewer_note = "No"
        s.commit()
    resp = chat.act(card["card_id"])
    assert "Rejected" in text_of(resp) and "can't be cancelled" in text_of(resp)
    assert status_of(seeded, LeaveRequest, rid) == RequestStatus.REJECTED
