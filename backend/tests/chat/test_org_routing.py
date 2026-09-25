"""Phase 3 routing in the chat: the approver is stored on the request and is the only one told."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import ClaimRequest, LeaveRequest, Notification, User
from app.db.session import Database
from app.domain.enums import RequestStatus, RequestType, UserRole
from tests.chat.conftest import AMY, BEN, CATHY
from tests.chat.helpers import (
    FULL_LEAVE,
    VALID_CLAIM,
    Chat,
    RecordingAdapter,
    ScriptedLLM,
    cancel_turn,
    card_of,
    claim_turn,
    d,
    leave_turn,
    submit_claim,
    submit_leave,
    text_of,
    ui_of,
    update_turn,
)
from tests.conftest import CSRF_HEADERS, login

DANIEL = "daniel.wong@example.com"
HELEN = "helen.yeung@example.com"
EVA = "eva.cheung@example.com"


def user_id(db: Database, email: str) -> int:
    with db.session_factory() as s:
        return s.scalars(select(User.id).where(User.email == email)).one()


def set_approvers(db: Database, email: str, **fields: object) -> None:
    with db.session_factory() as s:
        row = s.scalars(select(User).where(User.email == email)).one()
        for key, value in fields.items():
            setattr(row, key, value)
        s.commit()


def notes_for(db: Database, request_type: RequestType, request_id: int) -> list[Notification]:
    with db.session_factory() as s:
        return list(
            s.scalars(
                select(Notification)
                .where(Notification.request_type == request_type)
                .where(Notification.request_id == request_id)
                .order_by(Notification.id)
            )
        )


def count(db: Database, model: type) -> int:
    with db.session_factory() as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


def as_user(chat_app, email: str) -> TestClient:  # type: ignore[no-untyped-def]

    client = TestClient(chat_app, headers=CSRF_HEADERS)
    login(client, email)
    return client


# ---- the approver is stored and copied onto the request -----------------------------------------


@pytest.mark.parametrize(
    ("requester", "approver"),
    [(AMY, CATHY), (BEN, CATHY), (DANIEL, HELEN), (CATHY, HELEN)],
)
def test_a_new_leave_is_assigned_to_the_configured_approver(
    chat_app,  # type: ignore[no-untyped-def]
    llm: ScriptedLLM,
    seeded: Database,
    requester: str,
    approver: str,
) -> None:
    rid = submit_leave(Chat(as_user(chat_app, requester)), llm)
    with seeded.session_factory() as s:
        row = s.get(LeaveRequest, rid)
        assert row.approver_user_id == user_id(seeded, approver)
        assert row.required_approver_role is UserRole.HR_APPROVER
        assert row.status is RequestStatus.PENDING_APPROVAL


def test_a_new_claim_is_assigned_to_eva(chat_app, llm: ScriptedLLM, seeded: Database) -> None:  # type: ignore[no-untyped-def]
    rid = submit_claim(Chat(as_user(chat_app, AMY)), llm)
    with seeded.session_factory() as s:
        row = s.get(ClaimRequest, rid)
        assert row.approver_user_id == user_id(seeded, EVA)
        assert row.required_approver_role is UserRole.FINANCE_APPROVER


def test_the_approver_follows_the_requesters_own_configuration(
    chat_app,
    llm: ScriptedLLM,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    """Routing is per user, not per department: change Amy's approver and the next leave follows."""
    set_approvers(seeded, AMY, leave_approver_user_id=user_id(seeded, HELEN))
    rid = submit_leave(Chat(as_user(chat_app, AMY)), llm)
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, rid).approver_user_id == user_id(seeded, HELEN)


# ---- notifications go to the assigned approver only ---------------------------------------------


def test_submission_notifies_only_the_assigned_approver(
    chat_app,
    llm: ScriptedLLM,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    rid = submit_leave(Chat(as_user(chat_app, AMY)), llm)
    notes = notes_for(seeded, RequestType.LEAVE, rid)
    assert [(n.recipient_user_id, n.event_type) for n in notes] == [
        (user_id(seeded, CATHY), "request.submitted")  # Cathy only; Helen is also HR but not told
    ]
    assert all(n.read_at is None for n in notes)


def test_claim_submission_notifies_eva_only(
    chat_app,
    llm: ScriptedLLM,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    rid = submit_claim(Chat(as_user(chat_app, BEN)), llm)
    notes = notes_for(seeded, RequestType.CLAIM, rid)
    assert [(n.recipient_user_id, n.event_type) for n in notes] == [
        (user_id(seeded, EVA), "request.submitted")
    ]


def test_a_failed_submission_notifies_nobody_until_the_retry_succeeds(
    chat_app,
    llm: ScriptedLLM,
    adapter: RecordingAdapter,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    chat = Chat(as_user(chat_app, AMY))
    adapter.fail_next()
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave 5-7 Oct"))
    failed = ui_of(chat.act(card["card_id"]), 0)
    assert failed["outcome"] == "failed"
    rid = failed["request_id"]
    assert notes_for(seeded, RequestType.LEAVE, rid) == []
    with seeded.session_factory() as s:
        assert s.get(LeaveRequest, rid).approver_user_id == user_id(seeded, CATHY)  # already set
    retry = ui_of(
        chat.detail()["messages"][-1] and {"assistant_messages": chat.detail()["messages"]}
    )
    chat.act(retry["card_id"])
    notes = notes_for(seeded, RequestType.LEAVE, rid)
    assert [(n.recipient_user_id, n.event_type) for n in notes] == [
        (user_id(seeded, CATHY), "request.submitted")
    ]


def test_changing_a_pending_request_notifies_the_assigned_approver(
    chat_app,
    llm: ScriptedLLM,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    chat = Chat(as_user(chat_app, AMY))
    rid = submit_leave(chat, llm)
    llm.push(
        update_turn(
            request_id=rid, request_type=RequestType.LEAVE, leave={"end_date": d("2026-10-08")}
        )
    )
    chat.act(card_of(chat.say(f"make leave #{rid} end on 8 Oct"))["card_id"])
    notes = notes_for(seeded, RequestType.LEAVE, rid)
    assert [(n.recipient_user_id, n.event_type) for n in notes] == [
        (user_id(seeded, CATHY), "request.submitted"),
        (user_id(seeded, CATHY), "request.updated"),
    ]
    assert {n.request_id for n in notes} == {rid}


def test_cancelling_a_pending_request_notifies_the_assigned_approver(
    chat_app,
    llm: ScriptedLLM,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    chat = Chat(as_user(chat_app, AMY))
    rid = submit_claim(chat, llm)
    llm.push(cancel_turn(request_id=rid, request_type=RequestType.CLAIM))
    chat.act(card_of(chat.say(f"cancel claim #{rid}"))["card_id"])
    notes = notes_for(seeded, RequestType.CLAIM, rid)
    assert [(n.recipient_user_id, n.event_type) for n in notes] == [
        (user_id(seeded, EVA), "request.submitted"),
        (user_id(seeded, EVA), "request.cancelled"),
    ]
    with seeded.session_factory() as s:
        assert s.get(ClaimRequest, rid).status is RequestStatus.CANCELLED


def test_cancelling_a_request_that_was_never_submitted_tells_nobody(
    chat_app,
    llm: ScriptedLLM,
    adapter: RecordingAdapter,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    chat = Chat(as_user(chat_app, AMY))
    adapter.fail_next()
    llm.push(claim_turn(**VALID_CLAIM))
    rid = ui_of(chat.act(card_of(chat.say("claim 120 travel"))["card_id"]), 0)["request_id"]
    llm.push(cancel_turn(request_id=rid, request_type=RequestType.CLAIM))
    chat.act(card_of(chat.say(f"cancel claim #{rid}"))["card_id"])
    assert notes_for(seeded, RequestType.CLAIM, rid) == []


# ---- no valid approver: nothing is saved --------------------------------------------------------


def _confirm_without_valid_approver(
    chat_app,
    llm: ScriptedLLM,
    adapter: RecordingAdapter,
    seeded: Database,  # type: ignore[no-untyped-def]
    prepare: Callable[[], None],
    model: type,
    turn: Callable[[], object],
) -> tuple[Chat, dict, str]:
    chat = Chat(as_user(chat_app, AMY))
    llm.push(turn())  # type: ignore[arg-type]
    card = card_of(chat.say("please file it"))
    rows, notes = count(seeded, model), count(seeded, Notification)
    prepare()  # the configuration changes between the card and the Confirm
    done = chat.act(card["card_id"])
    assert count(seeded, model) == rows  # nothing was saved
    assert count(seeded, Notification) == notes and adapter.calls == []  # nothing sent or notified
    return chat, done, text_of(done)


def test_confirming_a_leave_when_no_leave_approver_is_configured_saves_nothing(
    chat_app,
    llm: ScriptedLLM,
    adapter: RecordingAdapter,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    chat, done, text = _confirm_without_valid_approver(
        chat_app,
        llm,
        adapter,
        seeded,
        lambda: set_approvers(seeded, AMY, leave_approver_user_id=None),
        LeaveRequest,
        lambda: leave_turn(**FULL_LEAVE),
    )
    assert "No approver is configured for your leave requests" in text
    assert "out of the PoC scope" in text and "contact HR" in text
    assert ui_of(done) is None  # no result card: nothing was submitted
    assert done["warning_code"] is None
    # the chat still works, and the claim side still has its approver
    llm.push(claim_turn(**VALID_CLAIM))
    assert card_of(chat.say("claim 120 travel"))["action"] == "create"


def test_confirming_a_claim_when_no_claim_approver_is_configured_saves_nothing(
    chat_app,
    llm: ScriptedLLM,
    adapter: RecordingAdapter,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    _, _, text = _confirm_without_valid_approver(
        chat_app,
        llm,
        adapter,
        seeded,
        lambda: set_approvers(seeded, AMY, claim_approver_user_id=None),
        ClaimRequest,
        lambda: claim_turn(**VALID_CLAIM),
    )
    assert "No approver is configured for your claims" in text and "contact Finance" in text


def test_an_inactive_approver_saves_nothing_and_says_why(
    chat_app,
    llm: ScriptedLLM,
    adapter: RecordingAdapter,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    def deactivate() -> None:
        set_approvers(seeded, CATHY, is_active=False)

    _, _, text = _confirm_without_valid_approver(
        chat_app, llm, adapter, seeded, deactivate, LeaveRequest, lambda: leave_turn(**FULL_LEAVE)
    )
    assert "no longer active" in text


def test_the_card_can_no_longer_be_confirmed_after_the_refusal(
    chat_app,
    llm: ScriptedLLM,
    adapter: RecordingAdapter,
    seeded: Database,  # type: ignore[no-untyped-def]
) -> None:
    chat = Chat(as_user(chat_app, AMY))
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave 5-7 Oct"))
    set_approvers(seeded, AMY, leave_approver_user_id=None)
    chat.act(card["card_id"])
    assert chat.act_raw(card["card_id"]).status_code == 409  # used up: no accidental second try
    assert count(seeded, LeaveRequest) == 10  # only the seeded leave requests
