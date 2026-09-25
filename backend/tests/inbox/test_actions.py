"""IN-07..IN-18: approve, reject, skip, acknowledge, stale items, reopen and the normal chat."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import (
    AuditEvent,
    ClaimRequest,
    Conversation,
    LeaveRequest,
    Notification,
)
from app.db.session import Database
from app.domain.enums import RequestStatus
from app.llm.schemas import Intent
from tests.chat.helpers import RecordingAdapter, ScriptedLLM, simple_turn
from tests.conftest import get_user
from tests.inbox.conftest import AMY, CATHY, start_inbox
from tests.inbox.helpers import act, inbox_cards, texts

CLOSED_ONE = "All done. You handled 1 item."


def _first(client: TestClient) -> tuple[int, dict[str, Any]]:
    body = start_inbox(client)
    return body["conversation"]["id"], inbox_cards(body)[0]


def _audit(db: Database, entity: str, entity_id: int) -> list[AuditEvent]:
    with db.session_factory() as s:
        rows = s.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.entity_type == entity,
                AuditEvent.entity_id == entity_id,
                AuditEvent.event_type.in_(["request.approved", "request.rejected"]),
            )
            .order_by(AuditEvent.id)
        ).all()
        for r in rows:
            s.expunge(r)
        return list(rows)


# ---- approve and reject --------------------------------------------------------------------------
def test_approve_needs_confirmed_true(cathy: TestClient, seeded: Database) -> None:
    """IN-08: a missing or false ``confirmed`` is 422 and nothing changes."""
    conv_id, card = _first(cathy)
    for extra in ({}, {"confirmed": False}, {"confirmed": None}):
        response = act(cathy, conv_id, card["card_id"], "approve", **extra)
        assert response.status_code == 422, response.text
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, 1).status == RequestStatus.PENDING_APPROVAL
    assert _audit(seeded, "leave_request", 1) == []
    # the card is still open: the same card can be confirmed afterwards
    assert act(cathy, conv_id, card["card_id"], "approve", confirmed=True).status_code == 200


def test_approve_records_the_decision_like_the_approvals_screen(
    cathy: TestClient, amy: TestClient, seeded: Database
) -> None:
    """IN-09: status, reviewer, note (trimmed), audit (via=inbox), notifications, balances."""
    balance_before = amy.get("/api/me/balances").json()["leave"][0]
    conv_id, card = _first(cathy)
    response = act(
        cathy, conv_id, card["card_id"], "approve", confirmed=True, note="  Have a good trip  "
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert texts(body) == ["You approved leave request #1 from Amy Lau.", CLOSED_ONE]
    assert body["user_message"] is None and body["warning_code"] is None
    assert inbox_cards(body) == []

    cathy_id = get_user(seeded, CATHY).id
    with seeded.session_factory() as s:
        row = s.get(LeaveRequest, 1)
        assert row.status == RequestStatus.APPROVED
        assert row.reviewed_by_user_id == cathy_id and row.reviewed_at is not None
        assert row.reviewer_note == "Have a good trip"
        notice = s.scalars(
            select(Notification).where(
                Notification.request_id == 1, Notification.event_type == "request.approved"
            )
        ).one()
        assert notice.recipient_user_id == get_user(seeded, AMY).id and notice.read_at is None
        submitted = s.scalars(
            select(Notification).where(
                Notification.recipient_user_id == cathy_id,
                Notification.request_id == 1,
                Notification.event_type == "request.submitted",
            )
        ).one()
        assert submitted.read_at is not None  # the approver's own new-request notice is read
    (event,) = _audit(seeded, "leave_request", 1)
    assert event.event_type == "request.approved" and event.actor_user_id == cathy_id
    assert (event.from_status, event.to_status) == ("pending_approval", "approved")
    assert event.metadata_json["via"] == "inbox"
    assert event.metadata_json["note_present"] is True
    assert "Have a good trip" not in str(event.metadata_json)  # the note text is never audited
    balance_after = amy.get("/api/me/balances").json()["leave"][0]
    assert balance_after["approved_days"] == balance_before["approved_days"] + 4.0


def test_reject_records_a_rejection_with_the_same_effects(
    cathy: TestClient, amy: TestClient, seeded: Database
) -> None:
    """IN-09"""
    balance_before = amy.get("/api/me/balances").json()["leave"][0]
    conv_id, card = _first(cathy)
    body = act(cathy, conv_id, card["card_id"], "reject", confirmed=True, note="Busy week").json()
    assert texts(body)[0] == "You rejected leave request #1 from Amy Lau."
    with seeded.session_factory() as s:
        row = s.get(LeaveRequest, 1)
        assert row.status == RequestStatus.REJECTED and row.reviewer_note == "Busy week"
        assert s.scalars(
            select(Notification).where(
                Notification.request_id == 1, Notification.event_type == "request.rejected"
            )
        ).one()
    (event,) = _audit(seeded, "leave_request", 1)
    assert event.event_type == "request.rejected" and event.metadata_json["via"] == "inbox"
    after = amy.get("/api/me/balances").json()["leave"][0]
    assert after["approved_days"] == balance_before["approved_days"]  # a rejection deducts nothing
    assert after["remaining_days"] == balance_before["remaining_days"]
    assert after["pending_days"] == balance_before["pending_days"] - 4.0  # it just leaves pending


def test_the_inbox_audit_differs_from_the_approvals_endpoint_only_by_via(
    eva: TestClient, seeded: Database
) -> None:
    """IN-09: same metadata keys, numbers and snapshot as ``POST /api/approvals/.../decision``;
    the only addition is ``via``."""
    conv_id, card = _first(eva)  # claim 2 (the oldest)
    assert card["request_id"] == 2
    act(eva, conv_id, card["card_id"], "approve", confirmed=True, note="ok")
    assert (
        eva.post(
            "/api/approvals/claim/1/decision", json={"decision": "approve", "note": "ok"}
        ).status_code
        == 200
    )
    (via_inbox,) = _audit(seeded, "claim_request", 2)
    (via_screen,) = _audit(seeded, "claim_request", 1)
    assert set(via_inbox.metadata_json) == set(via_screen.metadata_json) | {"via"}
    assert "via" not in via_screen.metadata_json
    assert set(via_inbox.metadata_json["snapshot"]) == set(via_screen.metadata_json["snapshot"])
    assert via_inbox.actor_user_id == via_screen.actor_user_id
    assert via_inbox.entity_type == via_screen.entity_type == "claim_request"


@pytest.mark.parametrize(
    ("note", "stored"), [(None, None), ("", None), ("   ", None), (" x ", "x")]
)
def test_the_note_is_optional_trimmed_and_empty_becomes_none(
    cathy: TestClient, seeded: Database, note: str | None, stored: str | None
) -> None:
    """IN-10"""
    conv_id, card = _first(cathy)
    extra: dict[str, Any] = {} if note is None else {"note": note}
    assert (
        act(cathy, conv_id, card["card_id"], "approve", confirmed=True, **extra).status_code == 200
    )
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, 1).reviewer_note == stored
    (event,) = _audit(seeded, "leave_request", 1)
    assert event.metadata_json["note_present"] is (stored is not None)


def test_a_note_of_500_characters_is_fine_and_501_is_422(
    cathy: TestClient, seeded: Database
) -> None:
    """IN-10"""
    conv_id, card = _first(cathy)
    too_long = act(cathy, conv_id, card["card_id"], "approve", confirmed=True, note="n" * 501)
    assert too_long.status_code == 422
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, 1).status == RequestStatus.PENDING_APPROVAL
    padded = " " + "n" * 500 + "  "  # trailing spaces do not count
    assert (
        act(cathy, conv_id, card["card_id"], "approve", confirmed=True, note=padded).status_code
        == 200
    )
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, 1).reviewer_note == "n" * 500


def test_the_mock_api_is_never_called_by_a_decision(
    cathy: TestClient, adapter: RecordingAdapter
) -> None:
    conv_id, card = _first(cathy)
    act(cathy, conv_id, card["card_id"], "approve", confirmed=True)
    assert adapter.calls == []


# ---- skip and acknowledge ----------------------------------------------------------------------
def test_skip_changes_nothing_and_the_item_comes_back_next_time(
    cathy: TestClient, seeded: Database
) -> None:
    """IN-11"""
    conv_id, card = _first(cathy)
    response = act(cathy, conv_id, card["card_id"], "skip")
    assert response.status_code == 200
    assert texts(response.json()) == [
        "Skipped leave request #1 from Amy Lau. It stays in your bell and in Approvals.",
        "All done. You handled 0 items and skipped 1. Skipped items stay in your bell and in "
        "Approvals.",
    ]
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, 1).status == RequestStatus.PENDING_APPROVAL
        assert (
            s.scalar(
                select(Notification.read_at).where(
                    Notification.recipient_user_id == get_user(seeded, CATHY).id,
                    Notification.event_type == "request.submitted",
                )
            )
            is None
        )
    assert _audit(seeded, "leave_request", 1) == []
    assert cathy.get("/api/notifications").json()["unread_count"] == 1
    again = start_inbox(cathy)  # a new conversation with the same item
    assert inbox_cards(again)[0]["request_id"] == 1
    assert again["conversation"]["id"] != conv_id


def test_acknowledge_marks_the_notice_read(ben: TestClient, seeded: Database) -> None:
    """IN-12: Ben's two unread rejections, one by one."""
    conv_id, first = _first(ben)
    assert ben.get("/api/notifications").json()["unread_count"] == 2
    response = act(ben, conv_id, first["card_id"], "acknowledge")
    assert response.status_code == 200
    body = response.json()
    assert texts(body)[0] == "Got it. I marked that notice as read."
    second = inbox_cards(body)[0]
    assert second["kind"] == "notice" and second["position"] == {"index": 2, "total": 2}
    assert ben.get("/api/notifications").json()["unread_count"] == 1
    done = act(ben, conv_id, second["card_id"], "acknowledge").json()
    assert texts(done)[-1] == "All done. You handled 2 items."
    assert ben.get("/api/notifications").json()["unread_count"] == 0
    assert ben.post("/api/chat/inbox").json() == {"empty": True, "unread_count": 0}


def test_skipping_a_notice_keeps_it_unread(ben: TestClient) -> None:
    """IN-11, IN-12"""
    conv_id, first = _first(ben)
    body = act(ben, conv_id, first["card_id"], "skip").json()
    assert texts(body)[0] == "Skipped. It stays unread in your bell."
    assert ben.get("/api/notifications").json()["unread_count"] == 2


def test_a_summary_with_handled_and_skipped_items(eva: TestClient, seeded: Database) -> None:
    """IN-13: Eva approves the first claim and skips the second."""
    conv_id, first = _first(eva)
    second = inbox_cards(act(eva, conv_id, first["card_id"], "approve", confirmed=True).json())[0]
    assert second["title"] == "Claim #1 from Amy Lau"
    done = act(eva, conv_id, second["card_id"], "skip").json()
    assert texts(done)[-1] == (
        "All done. You handled 1 item and skipped 1. Skipped items stay in your bell and in "
        "Approvals."
    )
    with seeded.session_factory() as s:
        assert s.get(ClaimRequest, 2).status == RequestStatus.APPROVED
        assert s.get(ClaimRequest, 1).status == RequestStatus.PENDING_APPROVAL
    assert (
        eva.post("/api/chat/inbox")
        .json()["assistant_messages"][0]["content"]
        .startswith("You have 1 item to handle.")
    )


# ---- invalid buttons ---------------------------------------------------------------------------
def test_actions_that_do_not_fit_the_card_kind_are_422(cathy: TestClient, ben: TestClient) -> None:
    """IN-14"""
    c_conv, approval = _first(cathy)
    assert act(cathy, c_conv, approval["card_id"], "acknowledge").status_code == 422
    b_conv, notice = _first(ben)
    for action in ("approve", "reject"):
        assert act(ben, b_conv, notice["card_id"], action, confirmed=True).status_code == 422
    assert ben.get("/api/notifications").json()["unread_count"] == 2


def test_a_wrong_card_id_is_409(cathy: TestClient) -> None:
    """IN-14"""
    conv_id, _ = _first(cathy)
    assert act(cathy, conv_id, "i_deadbeef", "approve", confirmed=True).status_code == 409
    # confirm / discard are for confirmation cards only
    conv_id2, card = _first(cathy)
    assert act(cathy, conv_id2, card["card_id"], "confirm").status_code == 409
    assert act(cathy, conv_id2, card["card_id"], "discard").status_code == 409


def test_a_card_that_was_used_or_is_not_the_newest_is_409(eva: TestClient) -> None:
    """IN-14: the same card twice, and an older card once the next one is shown."""
    conv_id, first = _first(eva)
    ok = act(eva, conv_id, first["card_id"], "skip")
    assert ok.status_code == 200
    for action in ("skip", "approve"):
        again = act(eva, conv_id, first["card_id"], action, confirmed=True)
        assert again.status_code == 409 and again.json()["warning_code"] == "stale_card"
    with_second = inbox_cards(ok.json())[0]
    assert act(eva, conv_id, with_second["card_id"], "skip").status_code == 200
    # everything is over: no card is open any more
    assert act(eva, conv_id, with_second["card_id"], "skip").status_code == 409


def test_someone_elses_conversation_is_404(cathy: TestClient, amy: TestClient) -> None:
    """IN-14"""
    conv_id, card = _first(cathy)
    assert act(amy, conv_id, card["card_id"], "approve", confirmed=True).status_code == 404
    assert amy.get(f"/api/chat/conversations/{conv_id}").status_code == 404
    with_no_csrf = cathy.post(
        f"/api/chat/conversations/{conv_id}/actions",
        json={"card_id": card["card_id"], "action": "skip"},
        headers={"X-Requested-With": ""},
    )
    assert with_no_csrf.status_code == 403


def test_bad_bodies_are_422(cathy: TestClient) -> None:
    conv_id, card = _first(cathy)
    url = f"/api/chat/conversations/{conv_id}/actions"
    assert (
        cathy.post(url, json={"card_id": card["card_id"], "action": "explode"}).status_code == 422
    )
    body = {"card_id": card["card_id"], "action": "approve", "confirmed": "yes", "note": 5}
    assert cathy.post(url, json=body).status_code == 422


# ---- items handled elsewhere in the meantime ---------------------------------------------------
def test_an_item_decided_elsewhere_becomes_a_stale_card_and_the_next_item_follows(
    eva: TestClient, seeded: Database
) -> None:
    """IN-15: claim 2 is decided on the approvals screen while its card is open."""
    conv_id, first = _first(eva)
    assert first["request_id"] == 2
    assert (
        eva.post(
            "/api/approvals/claim/2/decision", json={"decision": "reject", "note": "first"}
        ).status_code
        == 200
    )
    response = act(eva, conv_id, first["card_id"], "approve", confirmed=True)
    assert response.status_code == 200 and response.json()["warning_code"] is None
    body = response.json()
    assert texts(body)[0] == "That request was already handled."
    nxt = inbox_cards(body)[0]
    assert nxt["request_id"] == 1 and nxt["position"] == {"index": 2, "total": 2}
    with seeded.session_factory() as s:  # the first decision stands; no second audit row
        row = s.get(ClaimRequest, 2)
        assert row.status == RequestStatus.REJECTED and row.reviewer_note == "first"
    assert len(_audit(seeded, "claim_request", 2)) == 1
    stored = eva.get(f"/api/chat/conversations/{conv_id}").json()["messages"]
    old = [m["ui"] for m in stored if m["ui"] and m["ui"]["card_id"] == first["card_id"]][0]
    assert old["state"] == "stale" and old["outcome"] is None
    done = act(eva, conv_id, nxt["card_id"], "skip").json()
    assert texts(done)[-1].startswith("All done. You handled 0 items and skipped 1. 1 item was")


def test_a_cancelled_request_makes_its_card_stale(cathy: TestClient, seeded: Database) -> None:
    """IN-15"""
    conv_id, card = _first(cathy)
    with seeded.session_factory() as s:
        s.get(LeaveRequest, 1).status = RequestStatus.CANCELLED
        s.commit()
    body = act(cathy, conv_id, card["card_id"], "reject", confirmed=True, note="x").json()
    assert texts(body) == [
        "That request was already handled.",
        "All done. You handled 0 items. 1 item was already handled elsewhere.",
    ]
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, 1).status == RequestStatus.CANCELLED
    assert _audit(seeded, "leave_request", 1) == []


def test_items_that_no_longer_apply_are_skipped_silently_before_they_are_shown(
    eva: TestClient, seeded: Database
) -> None:
    """IN-16: claim 1 is decided elsewhere while claim 2's card is open: after claim 2 is
    handled, claim 1 is dropped without a card and counted as already handled."""
    conv_id, first = _first(eva)
    assert (
        eva.post("/api/approvals/claim/1/decision", json={"decision": "approve"}).status_code == 200
    )
    body = act(eva, conv_id, first["card_id"], "approve", confirmed=True).json()
    assert texts(body) == [
        "You approved claim #2 from Daniel Wong.",
        "All done. You handled 1 item. 1 item was already handled elsewhere.",
    ]
    assert inbox_cards(body) == []


def test_a_notice_read_elsewhere_is_dropped_silently(ben: TestClient) -> None:
    """IN-16"""
    conv_id, first = _first(ben)
    assert ben.post("/api/notifications/read-all").status_code == 204
    body = act(ben, conv_id, first["card_id"], "acknowledge").json()
    assert inbox_cards(body) == []
    assert texts(body)[-1] == "All done. You handled 1 item. 1 item was already handled elsewhere."


def test_position_numbers_keep_the_snapshot_positions_when_an_item_is_dropped(
    cathy: TestClient, seeded: Database
) -> None:
    """IN-16: [approval, notice, notice]; the middle notice is read elsewhere, so the last one
    is shown as 3 of 3 (the numbers follow the snapshot, they are not renumbered)."""
    with seeded.session_factory() as s:
        rows = s.scalars(
            select(Notification)
            .where(Notification.recipient_user_id == get_user(seeded, CATHY).id)
            .order_by(Notification.created_at)
        ).all()
        decisions = [r for r in rows if r.event_type == "request.approved"]
        for r in decisions:
            r.read_at = None
        ids = [r.id for r in decisions]  # oldest first: claim 3, then leave 3
        s.commit()
    conv_id, first = _first(cathy)
    assert first["position"] == {"index": 1, "total": 3}
    assert cathy.post(f"/api/notifications/{ids[0]}/read").status_code == 204
    body = act(cathy, conv_id, first["card_id"], "approve", confirmed=True).json()
    last = inbox_cards(body)[0]
    assert last["kind"] == "notice" and last["position"] == {"index": 3, "total": 3}
    assert last["title"] == "Your leave request #3 was approved"
    done = act(cathy, conv_id, last["card_id"], "acknowledge").json()
    assert texts(done)[-1] == "All done. You handled 2 items. 1 item was already handled elsewhere."


# ---- reopen, badges and the normal chat --------------------------------------------------------
def test_reopening_shows_the_states_and_restores_the_open_card(eva: TestClient) -> None:
    """IN-17"""
    conv_id, first = _first(eva)
    second = inbox_cards(act(eva, conv_id, first["card_id"], "skip").json())[0]
    detail = eva.get(f"/api/chat/conversations/{conv_id}").json()
    cards = [m["ui"] for m in detail["messages"] if m["ui"]]
    assert [(c["request_id"], c["state"]) for c in cards] == [(2, "skipped"), (1, "open")]
    assert cards[1]["card_id"] == second["card_id"]
    assert detail["conversation"]["has_pending_card"] is True
    assert detail["conversation"]["title"] == "Items to handle (2)"
    approved = act(eva, conv_id, second["card_id"], "approve", confirmed=True).json()
    assert approved["conversation"]["has_pending_card"] is False
    detail = eva.get(f"/api/chat/conversations/{conv_id}").json()
    cards = [m["ui"] for m in detail["messages"] if m["ui"]]
    assert [(c["state"], c["outcome"]) for c in cards] == [("skipped", None), ("done", "approved")]
    assert detail["messages"][-1]["content"].startswith("All done.")


def test_typing_in_an_inbox_conversation_uses_the_normal_chat(
    cathy: TestClient, llm: ScriptedLLM, seeded: Database
) -> None:
    """IN-18: an open inbox card does not block the chat, and the chat does not close the card."""
    conv_id, card = _first(cathy)
    llm.push(simple_turn(Intent.HELP))
    response = cathy.post(f"/api/chat/conversations/{conv_id}/messages", json={"content": "help"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_message"]["content"] == "help" and body["assistant_messages"]
    assert body["conversation"]["has_pending_card"] is True
    assert body["conversation"]["title"] == "Items to handle (1)"
    done = act(cathy, conv_id, card["card_id"], "approve", confirmed=True)
    assert done.status_code == 200 and texts(done.json())[-1] == CLOSED_ONE
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, 1).status == RequestStatus.APPROVED
        assert s.get(Conversation, conv_id).state_json["inbox"]["finished"] is True


def test_a_chat_message_between_the_cards_does_not_break_the_next_action(
    eva: TestClient, llm: ScriptedLLM
) -> None:
    """IN-18: the chat bumps the state version; the next inbox action still works."""
    conv_id, first = _first(eva)
    llm.push(simple_turn(Intent.HELP))
    second = inbox_cards(act(eva, conv_id, first["card_id"], "skip").json())[0]
    assert (
        eva.post(
            f"/api/chat/conversations/{conv_id}/messages", json={"content": "hello"}
        ).status_code
        == 200
    )
    assert act(eva, conv_id, second["card_id"], "skip").status_code == 200


def test_the_seed_users_other_conversations_are_untouched(amy: TestClient) -> None:
    """IN-06: an empty inbox for Amy neither creates nor changes a conversation."""
    before = amy.get("/api/chat/conversations").json()
    assert amy.post("/api/chat/inbox").status_code == 200
    assert amy.get("/api/chat/conversations").json() == before
