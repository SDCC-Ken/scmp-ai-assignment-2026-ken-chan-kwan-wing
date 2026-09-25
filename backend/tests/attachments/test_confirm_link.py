"""Attachments are linked to the request on Confirm (create / update), via the draft state."""

from fastapi.testclient import TestClient

from app.chat.state import ConversationState, load_state
from app.db.models import Attachment, Conversation
from app.db.session import Database
from app.domain.enums import RequestType
from tests.attachments.helpers import PDF, PNG, upload_ok
from tests.chat.helpers import (
    FULL_LEAVE,
    VALID_CLAIM,
    Chat,
    RecordingAdapter,
    ScriptedLLM,
    cancel_turn,
    card_of,
    claim_turn,
    leave_turn,
    ui_of,
    update_turn,
)


def put_ids_in_state(db: Database, conversation_id: int, ids: list[int]) -> None:
    """Stand-in for the document-reading step, which will fill ``attachment_ids`` itself."""
    with db.session_factory() as s:
        conv = s.get(Conversation, conversation_id)
        assert conv is not None
        raw = dict(conv.state_json or {})
        raw["attachment_ids"] = ids
        conv.state_json = raw
        s.commit()


def linked(db: Database, attachment_id: int) -> tuple[RequestType | None, int | None]:
    with db.session_factory() as s:
        row = s.get(Attachment, attachment_id)
        assert row is not None
        return row.request_type, row.request_id


def test_state_defaults_and_old_stored_state_still_loads() -> None:
    assert ConversationState().attachment_ids == []
    old = load_state({"state_version": 3, "awaiting": None}, None)  # no attachment_ids key
    assert old.attachment_ids == [] and old.state_version == 3


def test_leave_confirm_links_the_file_and_only_hr_can_then_download(
    cathy: TestClient,
    hr: TestClient,
    finance: TestClient,
    amy: TestClient,
    chat: Chat,
    llm: ScriptedLLM,
    seeded: Database,
) -> None:
    note = upload_ok(cathy, chat.id, PDF, filename="clinic-note.pdf")
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave"))
    put_ids_in_state(seeded, chat.id, [note["id"]])
    url = f"/api/attachments/{note['id']}"
    assert hr.get(url).status_code == 404  # not linked yet: staged files are private

    result = ui_of(chat.act(card["card_id"]))
    assert result["outcome"] == "submitted"
    assert linked(seeded, note["id"]) == (RequestType.LEAVE, result["request_id"])

    assert hr.get(url).status_code == 200
    assert hr.get(url).content == PDF
    assert finance.get(url).status_code == 404
    assert amy.get(url).status_code == 404
    assert cathy.get(url).status_code == 200


def test_claim_confirm_links_the_file_and_only_finance_can_then_download(
    cathy: TestClient,
    hr: TestClient,
    finance: TestClient,
    chat: Chat,
    llm: ScriptedLLM,
    seeded: Database,
) -> None:
    receipt = upload_ok(cathy, chat.id, PNG + b"receipt", filename="taxi.png")
    llm.push(claim_turn(**VALID_CLAIM))
    card = card_of(chat.say("taxi claim"))
    put_ids_in_state(seeded, chat.id, [receipt["id"]])
    result = ui_of(chat.act(card["card_id"]))
    assert linked(seeded, receipt["id"]) == (RequestType.CLAIM, result["request_id"])
    url = f"/api/attachments/{receipt['id']}"
    assert finance.get(url).status_code == 200
    assert hr.get(url).status_code == 404


def test_ids_that_are_not_the_owners_are_not_linked(
    cathy: TestClient,
    amy: TestClient,
    chat: Chat,
    llm: ScriptedLLM,
    seeded: Database,
) -> None:
    mine = upload_ok(cathy, chat.id)["id"]
    theirs = upload_ok(amy, Chat(amy).id)["id"]
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave"))
    put_ids_in_state(seeded, chat.id, [mine, theirs, 424242])
    chat.act(card["card_id"])
    assert linked(seeded, mine)[0] == RequestType.LEAVE
    assert linked(seeded, theirs) == (None, None)


def test_a_failed_submission_keeps_the_link_but_approvers_still_cannot_open_the_file(
    cathy: TestClient,
    hr: TestClient,
    chat: Chat,
    llm: ScriptedLLM,
    adapter: RecordingAdapter,
    seeded: Database,
) -> None:
    note = upload_ok(cathy, chat.id, PDF)["id"]
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave"))
    put_ids_in_state(seeded, chat.id, [note])
    adapter.fail_next()
    response = chat.act(card["card_id"])
    assert response["warning_code"] == "submission_failed"
    assert linked(seeded, note)[0] == RequestType.LEAVE
    assert hr.get(f"/api/attachments/{note}").status_code == 404  # never submitted

    retry = card_of(response)
    chat.act(retry["card_id"])  # retry succeeds
    assert hr.get(f"/api/attachments/{note}").status_code == 200


def test_the_draft_state_is_cleared_after_confirm_and_discard(
    cathy: TestClient, chat: Chat, llm: ScriptedLLM, seeded: Database
) -> None:
    a = upload_ok(cathy, chat.id)["id"]
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave"))
    put_ids_in_state(seeded, chat.id, [a])
    chat.act(card["card_id"], "discard")
    with seeded.session_factory() as s:
        conv = s.get(Conversation, chat.id)
        assert conv is not None
        assert load_state(conv.state_json, None).attachment_ids == []
    assert linked(seeded, a) == (None, None)  # discarding links nothing


def test_update_confirm_links_new_files(
    cathy: TestClient,
    hr: TestClient,
    chat: Chat,
    llm: ScriptedLLM,
    seeded: Database,
) -> None:
    llm.push(leave_turn(**FULL_LEAVE))
    created = ui_of(chat.act(card_of(chat.say("annual leave"))["card_id"]))
    request_id = created["request_id"]
    note = upload_ok(cathy, chat.id, PDF)["id"]

    llm.push(
        update_turn(
            request_id=request_id, request_type=RequestType.LEAVE, leave={"end_date": "2026-10-08"}
        )
    )
    card = card_of(chat.say("extend to the 8th"))
    assert card["action"] == "update"
    put_ids_in_state(seeded, chat.id, [note])
    chat.act(card["card_id"])
    assert linked(seeded, note) == (RequestType.LEAVE, request_id)
    assert hr.get(f"/api/attachments/{note}").status_code == 200


def test_a_file_stays_linked_after_the_request_is_cancelled(
    cathy: TestClient, chat: Chat, llm: ScriptedLLM, seeded: Database
) -> None:
    note = upload_ok(cathy, chat.id, PDF)["id"]
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave"))
    put_ids_in_state(seeded, chat.id, [note])
    request_id = ui_of(chat.act(card["card_id"]))["request_id"]
    llm.push(cancel_turn(request_id=request_id, request_type=RequestType.LEAVE))
    cancel = card_of(chat.say("cancel it"))
    assert ui_of(chat.act(cancel["card_id"]))["outcome"] == "cancelled"
    assert linked(seeded, note) == (RequestType.LEAVE, request_id)


def test_confirm_without_files_is_unchanged(chat: Chat, llm: ScriptedLLM, seeded: Database) -> None:
    llm.push(leave_turn(**FULL_LEAVE))
    card = card_of(chat.say("annual leave"))
    assert ui_of(chat.act(card["card_id"]))["outcome"] == "submitted"
