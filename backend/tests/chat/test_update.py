"""UPDATE (edit) of leave and claims: success and failure (ids in docs/test-cases.md)."""

from decimal import Decimal

from sqlalchemy import select

from app.db.models import AuditEvent, ClaimRequest, ExternalSubmission, LeaveRequest
from app.db.session import Database
from app.domain.enums import DayPart, LeaveType, RequestStatus, RequestType
from app.llm.schemas import AgentTurn, Intent, LeaveFields
from tests.chat.helpers import (
    AM,
    AMY_PENDING_LEAVE,
    BEN_REJECTED_LEAVE,
    CATHY_APPROVED_LEAVE,
    FULL_LEAVE,
    Chat,
    RecordingAdapter,
    ScriptedLLM,
    card_of,
    d,
    details_leave,
    leave_turn,
    submit_claim,
    submit_leave,
    text_of,
    ui_of,
    update_turn,
)

LEAVE = RequestType.LEAVE
CLAIM = RequestType.CLAIM


def leave_row(db: Database, request_id: int) -> LeaveRequest:
    with db.session_factory() as s:
        row = s.get(LeaveRequest, request_id)
        assert row is not None
        return row


def claim_row(db: Database, request_id: int) -> ClaimRequest:
    with db.session_factory() as s:
        row = s.get(ClaimRequest, request_id)
        assert row is not None
        return row


def submissions(db: Database, rtype: str, request_id: int) -> list[ExternalSubmission]:
    with db.session_factory() as s:
        return list(
            s.scalars(
                select(ExternalSubmission)
                .where(
                    ExternalSubmission.request_type == rtype,
                    ExternalSubmission.request_id == request_id,
                )
                .order_by(ExternalSubmission.id)
            )
        )


def events(db: Database, entity: str, request_id: int) -> list[AuditEvent]:
    with db.session_factory() as s:
        return list(
            s.scalars(
                select(AuditEvent)
                .where(AuditEvent.entity_type == entity, AuditEvent.entity_id == request_id)
                .order_by(AuditEvent.id)
            )
        )


# ---- success -------------------------------------------------------------------------------------
def test_change_end_date_of_a_pending_leave(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """UC-01"""
    rid = submit_leave(chat, llm)
    llm.push(update_turn(request_id=rid, request_type=LEAVE, leave={"end_date": d("2026-10-08")}))
    resp = chat.say(f"make leave #{rid} end on 8 Oct")
    card = card_of(resp)
    assert card["action"] == "update" and card["request_id"] == rid
    assert card["confirm_label"] == "Save changes"
    fields = {f["key"]: f for f in card["fields"]}
    assert fields["end_date"]["value"] == "Thu 2026-10-08"
    assert fields["end_date"]["old_value"] == "Wed 2026-10-07"
    assert fields["working_days"]["value"] == "4" and fields["working_days"]["old_value"] == "3"
    assert fields["leave_type"]["old_value"] is None  # unchanged fields carry no old value
    # nothing changes before Confirm
    assert leave_row(seeded, rid).end_date == d("2026-10-07") and len(adapter.calls) == 1

    done = chat.act(card["card_id"])
    result = ui_of(done)
    assert result["outcome"] == "updated" and result["status"] == "pending_approval"
    row = leave_row(seeded, rid)
    assert row.end_date == d("2026-10-08") and row.working_days == Decimal("4.0")
    assert row.status == RequestStatus.PENDING_APPROVAL
    # re-submitted (ReqRes has no update endpoint): a second POST with the new dates
    assert len(adapter.calls) == 2
    assert adapter.calls[1][1] == {
        "email": "cathy.ng@example.com",
        "leave_type": "Annual",
        "start_date": "2026-10-05",
        "end_date": "2026-10-08",
    }
    subs = submissions(seeded, "leave", rid)
    assert [s.status.value for s in subs] == ["success", "success"]
    assert subs[1].request_payload_json["end_date"] == "2026-10-08"
    updated = [e for e in events(seeded, "leave_request", rid) if e.event_type == "request.updated"]
    assert len(updated) == 1
    changes = updated[0].metadata_json["changes"]
    assert changes["end_date"] == {"from": "2026-10-07", "to": "2026-10-08"}
    assert changes["working_days"] == {"from": "3", "to": "4"}
    assert "leave_type" not in changes


def test_target_is_inferred_when_only_one_request_can_be_edited(
    chat: Chat, llm: ScriptedLLM, seeded: Database
) -> None:
    """UC-01b: no id given; Cathy has exactly one editable request."""
    rid = submit_leave(chat, llm)
    llm.push(update_turn(leave={"end_date": d("2026-10-06")}))
    card = card_of(chat.say("shorten my leave to end on the 6th"))
    assert card["request_id"] == rid
    chat.act(card["card_id"])
    assert leave_row(seeded, rid).end_date == d("2026-10-06")


def test_target_resolved_by_a_date_hint(chat: Chat, llm: ScriptedLLM) -> None:
    """UC-01c: two editable requests; the hint picks the one starting 5 Oct."""
    first = submit_leave(chat, llm)
    submit_leave(
        chat,
        llm,
        leave_type=LeaveType.SICK,
        start_date=d("2026-11-02"),
        end_date=d("2026-11-03"),
    )
    llm.push(
        update_turn(
            request_type=LEAVE, hint="the leave starting 5 Oct", leave={"end_date": d("2026-10-06")}
        )
    )
    card = card_of(chat.say("change the leave starting 5 Oct to end 6 Oct"))
    assert card["request_id"] == first


def test_change_the_half_day_part(chat: Chat, llm: ScriptedLLM, seeded: Database) -> None:
    """UC-02"""
    rid = submit_leave(
        chat,
        llm,
        leave_type=LeaveType.PERSONAL,
        start_date=d("2026-10-06"),
        end_date=d("2026-10-06"),
    )
    llm.push(
        update_turn(
            request_id=rid,
            request_type=LEAVE,
            leave={"start_day_part": AM, "end_day_part": AM},
        )
    )
    card = card_of(chat.say("make it morning only"))
    fields = {f["key"]: f for f in card["fields"]}
    assert fields["start_date"]["value"] == "Tue 2026-10-06 (morning only)"
    assert fields["start_date"]["old_value"] == "Tue 2026-10-06"
    assert fields["working_days"]["value"] == "0.5" and fields["working_days"]["old_value"] == "1"
    chat.act(card["card_id"])
    row = leave_row(seeded, rid)
    assert (row.start_day_part, row.end_day_part) == (DayPart.AM, DayPart.AM)
    assert row.working_days == Decimal("0.5")


def test_change_the_amount_of_a_pending_claim(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """UC-03"""
    rid = submit_claim(chat, llm)
    llm.push(update_turn(request_id=rid, request_type=CLAIM, claim={"amount": 150.0}))
    card = card_of(chat.say(f"claim #{rid} should be 150"))
    fields = {f["key"]: f for f in card["fields"]}
    assert (
        fields["amount"]["value"] == "HKD 150.00" and fields["amount"]["old_value"] == "HKD 120.00"
    )
    chat.act(card["card_id"])
    assert claim_row(seeded, rid).amount == Decimal("150.00")
    assert adapter.calls[-1][1]["amount"] == 150.0 and len(adapter.calls) == 2


def test_same_value_is_not_a_change(chat: Chat, llm: ScriptedLLM) -> None:
    """UC-03b: 120 vs 120.00 compares equal, so the assistant asks what to change."""
    rid = submit_claim(chat, llm)
    llm.push(update_turn(request_id=rid, request_type=CLAIM, claim={"amount": 120.0}))
    resp = chat.say("set it to 120")
    assert ui_of(resp) is None
    assert "What would you like to change?" in text_of(resp)


def test_edit_a_failed_submission_then_retry_succeeds(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """UC-04: first submit fails, the edit fails again (new values kept), then Retry works."""
    adapter.fail_next(503, "Service unavailable")
    llm.push(
        leave_turn(
            **{
                "leave_type": LeaveType.ANNUAL,
                "start_date": d("2026-10-05"),
                "end_date": d("2026-10-07"),
            }
        )
    )
    card = card_of(chat.say("annual leave"))
    failed = chat.act(card["card_id"])
    rid = ui_of(failed, 0)["request_id"]
    assert leave_row(seeded, rid).status == RequestStatus.SUBMISSION_FAILED

    adapter.fail_next(500, "Boom")
    llm.push(update_turn(request_id=rid, request_type=LEAVE, leave={"end_date": d("2026-10-06")}))
    card = card_of(chat.say("shorten it"))
    assert card["action"] == "update"
    again = chat.act(card["card_id"])
    assert again["warning_code"] == "submission_failed"
    assert ui_of(again, 0)["outcome"] == "failed"
    retry = card_of({"assistant_messages": [again["assistant_messages"][1]]})
    assert retry["action"] == "retry"
    row = leave_row(seeded, rid)
    assert row.status == RequestStatus.SUBMISSION_FAILED  # still failed, but with the NEW values
    assert row.end_date == d("2026-10-06")

    done = chat.act(retry["card_id"])
    assert ui_of(done)["outcome"] == "submitted"
    row = leave_row(seeded, rid)
    assert row.status == RequestStatus.PENDING_APPROVAL and row.submitted_at is not None
    statuses = [s.status.value for s in submissions(seeded, "leave", rid)]
    assert statuses == ["failed", "failed", "success"]
    assert adapter.calls[-1][1]["end_date"] == "2026-10-06"


def test_edit_a_failed_submission_that_now_succeeds(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """UC-05"""
    adapter.fail_next()
    llm.push(
        leave_turn(
            **{
                "leave_type": LeaveType.ANNUAL,
                "start_date": d("2026-10-05"),
                "end_date": d("2026-10-07"),
            }
        )
    )
    failed = chat.act(card_of(chat.say("annual leave"))["card_id"])
    rid = ui_of(failed, 0)["request_id"]
    llm.push(update_turn(request_id=rid, request_type=LEAVE, leave={"end_date": d("2026-10-06")}))
    done = chat.act(card_of(chat.say("shorten it"))["card_id"])
    assert ui_of(done)["outcome"] == "updated" and ui_of(done)["status"] == "pending_approval"
    row = leave_row(seeded, rid)
    assert row.status == RequestStatus.PENDING_APPROVAL and row.end_date == d("2026-10-06")


def test_update_of_a_failed_request_without_changes_offers_retry(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter
) -> None:
    """UC-05b"""
    adapter.fail_next()
    llm.push(
        leave_turn(
            **{
                "leave_type": LeaveType.ANNUAL,
                "start_date": d("2026-10-05"),
                "end_date": d("2026-10-07"),
            }
        )
    )
    failed = chat.act(card_of(chat.say("annual leave"))["card_id"])
    rid = ui_of(failed, 0)["request_id"]
    chat.say("(discard the retry card first)") if False else None
    llm.push(update_turn(request_id=rid, request_type=LEAVE))
    resp = chat.say(f"retry #{rid}")
    card = card_of(resp)
    assert card["action"] == "retry" and card["request_id"] == rid


def test_edit_can_be_continued_in_several_messages(
    chat: Chat, llm: ScriptedLLM, seeded: Database
) -> None:
    """UC-06: update_request without details, then provide_details, then another change."""
    rid = submit_leave(chat, llm)
    llm.push(update_turn(request_id=rid, request_type=LEAVE))
    assert "What would you like to change?" in text_of(chat.say(f"I need to change leave #{rid}"))
    llm.push(details_leave(end_date=d("2026-10-09")))
    first = card_of(chat.say("end on the 9th"))
    llm.push(details_leave(end_date=d("2026-10-08")))
    second = card_of(chat.say("no, the 8th"))
    assert second["card_id"] != first["card_id"]
    assert {f["key"]: f["old_value"] for f in second["fields"]}["end_date"] == "Wed 2026-10-07"
    detail = chat.detail()
    states = {
        m["ui"]["card_id"]: m["ui"]["state"]
        for m in detail["messages"]
        if m["ui"] and m["ui"]["type"] == "confirmation_card"
    }
    assert states[first["card_id"]] == "superseded" and states[second["card_id"]] == "open"
    chat.act(second["card_id"])
    assert leave_row(seeded, rid).end_date == d("2026-10-08")


# ---- failures ------------------------------------------------------------------------------------
def test_approved_request_cannot_be_edited(chat: Chat, llm: ScriptedLLM) -> None:
    """UF-01"""
    llm.push(
        update_turn(
            request_id=CATHY_APPROVED_LEAVE, request_type=LEAVE, leave={"end_date": d("2026-10-30")}
        )
    )
    resp = chat.say(f"change leave #{CATHY_APPROVED_LEAVE}")
    assert ui_of(resp) is None
    assert "Approved" in text_of(resp) and "can't be changed" in text_of(resp)


def test_rejected_request_cannot_be_edited(ben_chat: Chat, llm: ScriptedLLM) -> None:
    """UF-02"""
    llm.push(
        update_turn(
            request_id=BEN_REJECTED_LEAVE, request_type=LEAVE, leave={"end_date": d("2026-10-30")}
        )
    )
    resp = ben_chat.say("change my rejected leave")
    assert "Rejected" in text_of(resp) and "short-staffed" in text_of(resp)


def test_cancelled_request_cannot_be_edited(chat: Chat, llm: ScriptedLLM) -> None:
    """UF-03"""
    rid = submit_leave(chat, llm)
    from tests.chat.helpers import cancel_turn

    llm.push(cancel_turn(request_id=rid, request_type=LEAVE))
    chat.act(card_of(chat.say("cancel it"))["card_id"])
    llm.push(update_turn(request_id=rid, request_type=LEAVE, leave={"end_date": d("2026-10-09")}))
    resp = chat.say("actually extend it")
    assert "Cancelled" in text_of(resp) and "can't be changed" in text_of(resp)


def test_another_employees_request_looks_nonexistent(chat: Chat, llm: ScriptedLLM) -> None:
    """UF-04"""
    llm.push(
        update_turn(
            request_id=AMY_PENDING_LEAVE, request_type=LEAVE, leave={"end_date": d("2026-10-30")}
        )
    )
    resp = chat.say(f"change leave #{AMY_PENDING_LEAVE}")
    assert ui_of(resp) is None
    assert f"couldn't find a request with id {AMY_PENDING_LEAVE}" in text_of(resp)
    assert "Amy" not in text_of(resp)


def test_nonexistent_request_id(chat: Chat, llm: ScriptedLLM) -> None:
    """UF-05"""
    llm.push(update_turn(request_id=9999, request_type=LEAVE, leave={"end_date": d("2026-10-30")}))
    assert "couldn't find a request with id 9999" in text_of(chat.say("change leave 9999"))


def test_invalid_edit_is_explained_and_can_be_fixed(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """UF-06: end date before the start date."""
    rid = submit_leave(chat, llm)
    llm.push(update_turn(request_id=rid, request_type=LEAVE, leave={"end_date": d("2026-10-01")}))
    resp = chat.say("end on 1 Oct")
    assert ui_of(resp) is None
    assert "End date 2026-10-01 is before the start date 2026-10-05" in text_of(resp)
    assert leave_row(seeded, rid).end_date == d("2026-10-07") and len(adapter.calls) == 1
    llm.push(details_leave(end_date=d("2026-10-06")))
    card = card_of(chat.say("ok the 6th"))
    assert card["action"] == "update"


def test_adapter_failure_during_amendment_leaves_the_original_intact(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """UF-07"""
    rid = submit_leave(chat, llm)
    llm.push(update_turn(request_id=rid, request_type=LEAVE, leave={"end_date": d("2026-10-08")}))
    card = card_of(chat.say("extend to the 8th"))
    adapter.fail_next(502, "Bad gateway")
    resp = chat.act(card["card_id"])
    assert resp["warning_code"] == "submission_failed"
    assert "nothing was changed" in text_of(resp, 0)
    assert ui_of(resp, 0)["outcome"] == "failed"
    row = leave_row(seeded, rid)
    assert row.end_date == d("2026-10-07") and row.working_days == Decimal("3.0")
    assert row.status == RequestStatus.PENDING_APPROVAL
    assert not [
        e for e in events(seeded, "leave_request", rid) if e.event_type == "request.updated"
    ]
    assert [s.status.value for s in submissions(seeded, "leave", rid)] == ["success", "failed"]
    # a fresh, working update card is offered again
    again = card_of({"assistant_messages": [resp["assistant_messages"][1]]})
    assert again["action"] == "update" and again["card_id"] != card["card_id"]
    assert {f["key"]: f["value"] for f in again["fields"]}["end_date"] == "Thu 2026-10-08"
    done = chat.act(again["card_id"])
    assert ui_of(done)["outcome"] == "updated"
    assert leave_row(seeded, rid).end_date == d("2026-10-08")


def test_update_with_no_change_specified_asks_what_to_change(chat: Chat, llm: ScriptedLLM) -> None:
    """UF-08"""
    rid = submit_leave(chat, llm)
    llm.push(update_turn(request_id=rid, request_type=LEAVE))
    resp = chat.say("I want to change my leave")
    assert ui_of(resp) is None
    assert "What would you like to change?" in text_of(resp)
    assert "Annual leave" in text_of(resp)


def test_ambiguous_target_lists_the_candidates(amy_chat: Chat, llm: ScriptedLLM) -> None:
    """UF-09: Amy has a pending leave and a pending claim in the seed."""
    llm.push(update_turn())
    resp = amy_chat.say("change my request")
    assert ui_of(resp) is None
    assert "Which request do you mean?" in text_of(resp)
    assert "#1 Annual leave" in text_of(resp) and "Travel claim" in text_of(resp)


def test_update_request_intent_with_only_final_requests_explains(
    chat: Chat, llm: ScriptedLLM
) -> None:
    """UF-10: Cathy only has approved requests in the seed."""
    llm.push(update_turn(request_type=LEAVE))
    resp = chat.say("change my leave")
    assert "None of your requests can be changed" in text_of(resp)


def test_edit_that_becomes_final_meanwhile_is_not_applied(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """UF-11: an approver reviews the request between the card and the Confirm click."""
    rid = submit_leave(chat, llm)
    llm.push(update_turn(request_id=rid, request_type=LEAVE, leave={"end_date": d("2026-10-08")}))
    card = card_of(chat.say("extend"))
    with seeded.session_factory() as s:
        row = s.get(LeaveRequest, rid)
        row.status = RequestStatus.APPROVED
        row.reviewed_by_user_id = 4
        from datetime import UTC, datetime

        row.reviewed_at = datetime.now(UTC)
        s.commit()
    resp = chat.act(card["card_id"])
    assert "can't be changed" in text_of(resp)
    assert leave_row(seeded, rid).end_date == d("2026-10-07")
    assert len(adapter.calls) == 1


def test_switching_to_a_new_draft_while_editing_sets_the_edit_aside(
    chat: Chat, llm: ScriptedLLM
) -> None:
    """UF-12"""
    rid = submit_leave(chat, llm)
    llm.push(update_turn(request_id=rid, request_type=LEAVE))
    chat.say("change it")
    llm.push(
        AgentTurn(
            intent=Intent.CREATE_LEAVE,
            request_type=LEAVE,
            leave=LeaveFields(
                leave_type=LeaveType.SICK, start_date=d("2026-11-02"), end_date=d("2026-11-02")
            ),
            confidence=0.9,
        )
    )
    resp = chat.say("new sick leave on 2 Nov")
    assert f"I set aside your changes to leave request #{rid}." in text_of(resp)
    assert card_of(resp)["action"] == "create"


def test_details_sent_while_a_retry_card_is_open_start_an_edit_of_that_request(
    chat: Chat, llm: ScriptedLLM, adapter: RecordingAdapter, seeded: Database
) -> None:
    """UC-07"""
    adapter.fail_next()
    llm.push(leave_turn(**FULL_LEAVE))
    failed = chat.act(card_of(chat.say("annual leave"))["card_id"])
    rid = ui_of(failed, 0)["request_id"]
    retry = failed["assistant_messages"][1]["ui"]
    llm.push(details_leave(end_date=d("2026-10-06")))
    card = card_of(chat.say("make it end on the 6th"))
    assert card["action"] == "update" and card["request_id"] == rid
    assert {f["key"]: f["old_value"] for f in card["fields"]}["end_date"] == "Wed 2026-10-07"
    states = {
        m["ui"]["card_id"]: m["ui"]["state"]
        for m in chat.detail()["messages"]
        if m["ui"] and m["ui"]["type"] == "confirmation_card"
    }
    assert states[retry["card_id"]] == "superseded"
    done = chat.act(card["card_id"])
    assert ui_of(done)["outcome"] == "updated"
    assert leave_row(seeded, rid).end_date == d("2026-10-06")


def test_details_sent_while_a_cancel_card_is_open_do_not_change_anything(
    chat: Chat, llm: ScriptedLLM, seeded: Database
) -> None:
    """UC-08"""
    from tests.chat.helpers import cancel_turn

    rid = submit_leave(chat, llm)
    llm.push(cancel_turn(request_id=rid, request_type=LEAVE))
    card = card_of(chat.say("cancel it"))
    llm.push(details_leave(end_date=d("2026-10-06")))
    resp = chat.say("or just end on the 6th")
    assert "cancellation card waiting for leave request" in text_of(resp)
    assert chat.detail()["conversation"]["has_pending_card"] is True
    assert leave_row(seeded, rid).end_date == d("2026-10-07")
    assert chat.act(card["card_id"])["assistant_messages"][0]["ui"]["outcome"] == "cancelled"
