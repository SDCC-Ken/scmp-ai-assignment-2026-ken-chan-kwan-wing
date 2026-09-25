"""IN-01..IN-06: who may open the inbox, what is in the queue, and what the first turn shows."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Conversation, ConversationMessage, LeaveRequest, Notification
from app.db.session import Database
from app.domain.clock import utcnow
from app.domain.enums import RequestStatus, RequestType
from tests.chat.helpers import RecordingAdapter
from tests.conftest import get_user, login
from tests.inbox.conftest import BEN, CATHY, DANIEL, start_inbox
from tests.inbox.helpers import act, inbox_cards, strip_capabilities, texts


# ---- access ----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("who", "status"),
    [("cathy", 201), ("helen", 201), ("eva", 201), ("amy", 200), ("daniel", 200), ("ben", 201)],
)
def test_everybody_in_the_seed_may_open_the_inbox(
    who: str, status: int, request: pytest.FixtureRequest
) -> None:
    """IN-01: requesters and approvers alike (Helen and Eva have no approver but decide a queue)."""
    client: TestClient = request.getfixturevalue(who)
    assert client.post("/api/chat/inbox").status_code == status


def test_a_user_with_neither_capability_gets_403(ben: TestClient, seeded: Database) -> None:
    """IN-01: no approver configured and no queue to decide: 403, as for the rest of the chat."""
    strip_capabilities(seeded, BEN)
    response = ben.post("/api/chat/inbox")
    assert response.status_code == 403
    assert "no approver is configured" in response.json()["detail"]


def test_unauthenticated_is_401(anon: TestClient) -> None:
    assert anon.post("/api/chat/inbox").status_code == 401


def test_the_csrf_header_is_required(in_app) -> None:  # type: ignore[no-untyped-def]
    with TestClient(in_app) as raw:  # no X-Requested-With
        login(raw, CATHY)
        assert raw.post("/api/chat/inbox", headers={"X-Requested-With": ""}).status_code == 403


def test_approvers_can_upload_to_their_own_inbox_conversation(helen: TestClient) -> None:
    """IN-01: the attachments upload uses the same chat access rule."""
    conv_id = start_inbox(helen)["conversation"]["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 40
    response = helen.post(
        f"/api/chat/conversations/{conv_id}/attachments",
        files={"file": ("a.png", png, "image/png")},
    )
    assert response.status_code == 201, response.text


# ---- empty inbox -----------------------------------------------------------------------------
@pytest.mark.parametrize("who", ["amy", "daniel"])
def test_nothing_to_handle_is_an_empty_200_and_creates_no_conversation(
    who: str, request: pytest.FixtureRequest
) -> None:
    """IN-02"""
    client: TestClient = request.getfixturevalue(who)
    before = client.get("/api/chat/conversations").json()
    response = client.post("/api/chat/inbox")
    assert response.status_code == 200
    assert response.json() == {"empty": True, "unread_count": 0}
    assert client.get("/api/chat/conversations").json() == before


def test_only_notifications_that_no_longer_make_sense_are_empty_with_the_real_count(
    daniel: TestClient, seeded: Database
) -> None:
    """IN-02: a legacy row for a request that is gone (or one that is not the user's) is not
    actionable: the inbox is empty but reports the real unread count."""
    with seeded.session_factory() as s:
        daniel_id = get_user(seeded, DANIEL).id
        amy_leave = 1  # Amy's request: a decision notice for it does not belong to Daniel
        s.add(
            Notification(
                recipient_user_id=daniel_id,
                event_type="request.approved",
                request_type=RequestType.LEAVE,
                request_id=9999,
            )
        )
        s.add(
            Notification(
                recipient_user_id=daniel_id,
                event_type="request.approved",
                request_type=RequestType.LEAVE,
                request_id=amy_leave,
            )
        )
        s.commit()
    response = daniel.post("/api/chat/inbox")
    assert response.status_code == 200
    assert response.json() == {"empty": True, "unread_count": 2}
    assert daniel.get("/api/notifications").json()["unread_count"] == 2  # the bell is unchanged


# ---- queue composition -----------------------------------------------------------------------
def test_cathys_queue_is_amys_leave(cathy: TestClient) -> None:
    """IN-03"""
    body = start_inbox(cathy)
    card = inbox_cards(body)[0]
    assert card["kind"] == "approval" and card["title"] == "Leave request #1 from Amy Lau"
    assert (card["request_type"], card["request_id"]) == ("leave", 1)
    assert card["position"] == {"index": 1, "total": 1}
    assert card["actions"] == ["approve", "reject", "skip"]
    assert card["state"] == "open" and card["outcome"] is None and card["notice"] is None
    assert card["card_id"].startswith("i_")
    # the submitted notification of that request is covered by the approval card: no notice
    assert len(inbox_cards(body)) == 1


def test_helens_queue_is_daniels_leave(helen: TestClient) -> None:
    """IN-03"""
    card = inbox_cards(start_inbox(helen))[0]
    assert card["title"] == "Leave request #2 from Daniel Wong"
    assert card["position"] == {"index": 1, "total": 1}


def test_evas_queue_is_two_claims_oldest_submitted_first(eva: TestClient) -> None:
    """IN-03, IN-04: claim 2 (submitted 21 Sep) before claim 1 (23 Sep); position counts all."""
    body = start_inbox(eva)
    conv_id = body["conversation"]["id"]
    assert body["conversation"]["title"] == "Items to handle (2)"
    first = inbox_cards(body)[0]
    assert first["title"] == "Claim #2 from Daniel Wong"
    assert first["position"] == {"index": 1, "total": 2}
    done = eva.post(
        f"/api/chat/conversations/{conv_id}/actions",
        json={"card_id": first["card_id"], "action": "skip"},
    ).json()
    second = inbox_cards(done)[0]
    assert second["title"] == "Claim #1 from Amy Lau"
    assert second["position"] == {"index": 2, "total": 2}


def test_bens_queue_is_his_two_unread_decisions_oldest_first(ben: TestClient) -> None:
    """IN-05: notices come in created order; the composed title and body are the bell's."""
    body = start_inbox(ben)
    conv_id = body["conversation"]["id"]
    first = inbox_cards(body)[0]
    assert first["kind"] == "notice" and first["actions"] == ["acknowledge", "skip"]
    assert first["title"] == "Your claim #4 was rejected"
    assert first["notice"]["title"] == first["title"]
    assert first["notice"]["body"].startswith("Rejected by ")
    assert first["detail"] is None and first["position"] == {"index": 1, "total": 2}
    assert (first["request_type"], first["request_id"]) == ("claim", 4)
    nxt = ben.post(
        f"/api/chat/conversations/{conv_id}/actions",
        json={"card_id": first["card_id"], "action": "skip"},
    ).json()
    assert inbox_cards(nxt)[0]["title"] == "Your leave request #4 was rejected"


def test_amy_gets_the_decision_notice_after_cathy_decides(
    cathy: TestClient, amy: TestClient
) -> None:
    """IN-05"""
    assert amy.post("/api/chat/inbox").status_code == 200  # nothing yet
    body = start_inbox(cathy)
    cathy.post(
        f"/api/chat/conversations/{body['conversation']['id']}/actions",
        json={
            "card_id": inbox_cards(body)[0]["card_id"],
            "action": "approve",
            "confirmed": True,
            "note": "Enjoy",
        },
    )
    amy_body = start_inbox(amy)
    card = inbox_cards(amy_body)[0]
    assert card["kind"] == "notice" and card["title"] == "Your leave request #1 was approved"
    assert card["notice"]["body"] == "Approved by Cathy Ng. Note: Enjoy"


def test_submitted_and_updated_notifications_of_a_pending_request_are_one_approval_card(
    cathy: TestClient, seeded: Database
) -> None:
    """IN-04: unread submitted + updated rows of a request in the queue add no extra notices."""
    cathy_id = get_user(seeded, CATHY).id
    with seeded.session_factory() as s:
        for _ in range(2):
            s.add(
                Notification(
                    recipient_user_id=cathy_id,
                    event_type="request.updated",
                    request_type=RequestType.LEAVE,
                    request_id=1,
                    created_at=utcnow(),
                )
            )
        s.commit()
    body = start_inbox(cathy)
    assert body["conversation"]["title"] == "Items to handle (1)"
    assert [c["kind"] for c in inbox_cards(body)] == ["approval"]


def test_a_cancelled_request_is_a_notice_not_an_approval(
    cathy: TestClient, seeded: Database
) -> None:
    """IN-04: once the request is no longer pending it has no approval card: both unread rows
    ("new request" and "cancelled") are plain notices, oldest first, as in the bell."""
    cathy_id = get_user(seeded, CATHY).id
    with seeded.session_factory() as s:
        s.get(LeaveRequest, 1).status = RequestStatus.CANCELLED
        s.add(
            Notification(
                recipient_user_id=cathy_id,
                event_type="request.cancelled",
                request_type=RequestType.LEAVE,
                request_id=1,
                created_at=utcnow(),
            )
        )
        s.commit()
    body = start_inbox(cathy)
    conv_id = body["conversation"]["id"]
    assert body["conversation"]["title"] == "Items to handle (2)"
    first = inbox_cards(body)[0]
    assert (first["kind"], first["title"]) == ("notice", "New leave request from Amy Lau")
    second = act(cathy, conv_id, first["card_id"], "skip").json()
    assert [(c["kind"], c["title"]) for c in inbox_cards(second)] == [
        ("notice", "Amy Lau cancelled leave request #1")
    ]


# ---- the snapshot -----------------------------------------------------------------------------
def test_every_call_creates_a_new_conversation(cathy: TestClient, seeded: Database) -> None:
    """IN-06"""
    one = start_inbox(cathy)
    two = start_inbox(cathy)
    assert one["conversation"]["id"] != two["conversation"]["id"]
    ids = [c["id"] for c in cathy.get("/api/chat/conversations").json()["items"]]
    assert ids[:2] == [two["conversation"]["id"], one["conversation"]["id"]]  # newest first
    assert len(ids) == len(set(ids))


def test_the_first_turn_is_an_intro_then_the_first_card(cathy: TestClient) -> None:
    """IN-06: intro text, an InboxCard message with no trace, a conversation ready to reopen."""
    body = start_inbox(cathy)
    assert body["empty"] is False and body["warning_code"] is None
    intro, first = body["assistant_messages"]
    assert intro["content"] == "You have 1 item to handle. Let's go through them one by one."
    assert intro["ui"] is None and intro["trace"] is None
    assert first["ui"]["type"] == "inbox_card" and first["trace"] is None
    assert first["content"] == "Item 1 of 1"
    conv = body["conversation"]
    assert conv["title"] == "Items to handle (1)" and conv["has_pending_card"] is True
    assert conv["status"] == "active" and conv["active_request_type"] is None
    assert [m["sender_type"] for m in body["assistant_messages"]] == ["assistant", "assistant"]


def test_the_intro_counts_all_items(eva: TestClient) -> None:
    body = start_inbox(eva)
    assert body["assistant_messages"][0]["content"].startswith("You have 2 items to handle.")


def test_the_approval_detail_is_exactly_the_approvals_detail(
    cathy: TestClient, helen: TestClient, eva: TestClient
) -> None:
    """IN-07: same shape and values as GET /api/approvals/{type}/{id}."""
    for client, rtype, rid in ((cathy, "leave", 1), (helen, "leave", 2), (eva, "claim", 2)):
        card = inbox_cards(start_inbox(client))[0]
        expected = client.get(f"/api/approvals/{rtype}/{rid}").json()
        assert card["detail"] == expected
        assert set(card["detail"]) == {"request", "limits", "team_overlap", "warnings"}


def test_the_queue_is_stored_with_the_conversation_and_survives_a_reopen(
    cathy: TestClient, seeded: Database
) -> None:
    """IN-06: no new table; the queue lives in ``state_json`` and the card is restored."""
    body = start_inbox(cathy)
    conv_id = body["conversation"]["id"]
    with seeded.session_factory() as s:
        state = s.get(Conversation, conv_id).state_json
        assert state["inbox"]["items"] == [
            {"kind": "approval", "request_type": "leave", "request_id": 1, "notification_id": None}
        ]
        assert state["inbox"]["open_card_id"] == inbox_cards(body)[0]["card_id"]
        assert s.scalar(
            select(ConversationMessage.id).where(ConversationMessage.conversation_id == conv_id)
        )
    reopened = cathy.get(f"/api/chat/conversations/{conv_id}").json()
    assert reopened["conversation"]["has_pending_card"] is True
    assert texts({"assistant_messages": reopened["messages"]})[1] == "Item 1 of 1"
    assert reopened["messages"][1]["ui"] == body["assistant_messages"][1]["ui"]


def test_opening_the_inbox_changes_nothing_else(
    cathy: TestClient, seeded: Database, adapter: RecordingAdapter
) -> None:
    """IN-06: reading the queue never decides, notifies or calls the mock API."""
    start_inbox(cathy)
    assert adapter.calls == []
    assert cathy.get("/api/notifications").json()["unread_count"] == 1
    assert cathy.get("/api/approvals").json()["count"] == 1
