"""Sending a message that references staged uploads (POST .../messages with attachment_ids)."""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.chat.turn_input import ChatTurnDeps
from app.db.models import Attachment, ConversationMessage
from app.db.session import Database
from app.llm.schemas import DocumentExtraction, Intent
from app.services.attachments import count_staged
from tests.attachments.helpers import PDF, PNG, upload_ok
from tests.chat.helpers import Chat, ScriptedLLM, leave_turn, simple_turn


def send(chat: Chat, content: str = "", ids: list[int] | None = None) -> Any:
    body: dict[str, Any] = {"content": content}
    if ids is not None:
        body["attachment_ids"] = ids
    return chat.client.post(f"/api/chat/conversations/{chat.id}/messages", json=body)


def message_count(db: Database, chat: Chat) -> int:
    with db.session_factory() as s:
        return len(
            s.scalars(
                select(ConversationMessage).where(ConversationMessage.conversation_id == chat.id)
            ).all()
        )


def test_file_only_message_reaches_the_provider_with_the_neutral_instruction(
    cathy: TestClient, chat: Chat, llm: ScriptedLLM
) -> None:
    info = upload_ok(cathy, chat.id, filename="receipt.png")
    llm.push(
        simple_turn(
            Intent.UNCLEAR, documents=[DocumentExtraction(doc_type="unreadable", readable=False)]
        )
    )
    response = send(chat, "", [info["id"]])
    assert response.status_code == 200, response.text
    body = response.json()
    assert llm.calls[0][0] == "The user attached a document with no message."
    assert [a.id for a in llm.attachments_seen[0]] == [info["id"]]
    assert llm.attachments_seen[0][0].data == PNG  # the stored bytes, not a copy of the name
    assert body["user_message"]["content"] == ""
    assert body["user_message"]["attachments"] == [info]
    assert "could not read" in body["assistant_messages"][0]["content"]
    assert body["assistant_messages"][0]["attachments"] == []
    assert body["warning_code"] is None
    assert body["conversation"]["has_pending_card"] is False


def test_whitespace_only_text_counts_as_empty(
    chat: Chat, cathy: TestClient, llm: ScriptedLLM
) -> None:
    info = upload_ok(cathy, chat.id)
    llm.push(simple_turn(Intent.UNCLEAR))
    response = send(chat, "   \n ", [info["id"]])
    assert response.status_code == 200
    assert llm.calls[0][0] == "The user attached a document with no message."


def test_text_with_a_file_passes_both_to_the_provider(
    cathy: TestClient, chat: Chat, llm: ScriptedLLM
) -> None:
    info = upload_ok(cathy, chat.id, PDF, filename="note.pdf")
    llm.push(leave_turn(leave_type="sick", start_date="2026-09-22", end_date="2026-09-23"))
    response = send(chat, "sick leave 22 and 23 Sep, note attached", [info["id"]])
    assert response.status_code == 200
    body = response.json()
    assert body["user_message"]["attachments"][0]["filename"] == "note.pdf"
    assert body["assistant_messages"][0]["ui"]["type"] == "confirmation_card"
    assert len(llm.calls) == 1
    assert llm.calls[0][0] == "sick leave 22 and 23 Sep, note attached"
    assert [a.id for a in llm.attachments_seen[0]] == [info["id"]]


def test_empty_message_without_files_is_still_422(chat: Chat, seeded: Database) -> None:
    for body in ({"content": ""}, {"content": "   "}, {"content": "", "attachment_ids": []}, {}):
        r = chat.client.post(f"/api/chat/conversations/{chat.id}/messages", json=body)
        assert r.status_code == 422, body
    assert message_count(seeded, chat) == 0


def test_over_long_text_is_still_422_with_files(cathy: TestClient, chat: Chat) -> None:
    info = upload_ok(cathy, chat.id)
    assert send(chat, "x" * 1001, [info["id"]]).status_code == 422
    assert send(chat, "x" * 1000, [info["id"]]).status_code == 200


def test_one_to_three_files_ok_and_a_fourth_is_rejected(
    cathy: TestClient, chat: Chat, seeded: Database
) -> None:
    ids = [upload_ok(cathy, chat.id, filename=f"f{i}.png")["id"] for i in range(4)]
    too_many = send(chat, "here", ids)
    assert too_many.status_code == 422
    assert message_count(seeded, chat) == 0  # nothing saved
    three = send(chat, "", ids[:3])
    assert three.status_code == 200
    assert [a["filename"] for a in three.json()["user_message"]["attachments"]] == [
        "f0.png",
        "f1.png",
        "f2.png",
    ]
    assert send(chat, "", ids[3:]).status_code == 200  # the fourth file, in its own message


def test_limit_follows_the_setting(att_app: FastAPI, cathy: TestClient, chat: Chat) -> None:
    att_app.state.settings.max_attachments_per_message = 1
    a, b = (upload_ok(cathy, chat.id)["id"] for _ in range(2))
    assert send(chat, "", [a, b]).status_code == 422
    assert send(chat, "", [a]).status_code == 200


def test_files_are_attached_to_the_user_message_and_no_longer_staged(
    cathy: TestClient, chat: Chat, seeded: Database
) -> None:
    info = upload_ok(cathy, chat.id)
    body = send(chat, "", [info["id"]]).json()
    with seeded.session_factory() as s:
        row = s.get(Attachment, info["id"])
        assert row is not None and row.message_id == body["user_message"]["id"]
        assert count_staged(s, chat.id) == 0


def test_invalid_ids_are_rejected_and_nothing_is_saved(
    cathy: TestClient, amy: TestClient, chat: Chat, amy_chat: Chat, seeded: Database
) -> None:
    mine = upload_ok(cathy, chat.id)["id"]
    theirs = upload_ok(amy, amy_chat.id)["id"]
    other_conversation = upload_ok(cathy, Chat(cathy).id)["id"]
    already = upload_ok(cathy, chat.id)["id"]
    assert send(chat, "", [already]).status_code == 200
    before = message_count(seeded, chat)

    for ids in ([theirs], [other_conversation], [already], [99999], [mine, theirs], [mine, mine]):
        response = send(chat, "hello", ids)
        assert response.status_code == 422, (ids, response.text)
    assert message_count(seeded, chat) == before
    # the valid one was not consumed by the failed attempts
    assert send(chat, "", [mine]).status_code == 200
    # the other user's file is untouched
    with seeded.session_factory() as s:
        row = s.get(Attachment, theirs)
        assert row is not None and row.message_id is None


def test_error_body_does_not_reveal_other_users_files(
    cathy: TestClient, amy: TestClient, chat: Chat, amy_chat: Chat
) -> None:
    theirs = upload_ok(amy, amy_chat.id)["id"]
    unknown = send(chat, "x", [424242]).json()
    foreign = send(chat, "x", [theirs]).json()
    assert unknown == foreign


def test_messages_without_attachment_ids_behave_as_before(chat: Chat, llm: ScriptedLLM) -> None:
    llm.push(simple_turn(Intent.HELP))
    body = chat.say("hello")
    assert body["user_message"]["attachments"] == []
    assert body["assistant_messages"][0]["attachments"] == []


def test_get_conversation_lists_attachments_on_user_messages(cathy: TestClient, chat: Chat) -> None:
    a = upload_ok(cathy, chat.id, filename="a.png")
    b = upload_ok(cathy, chat.id, PDF, filename="b.pdf")
    send(chat, "", [a["id"], b["id"]])
    messages = chat.detail()["messages"]
    assert messages[0]["sender_type"] == "user"
    assert messages[0]["attachments"] == [a, b]
    assert messages[1]["sender_type"] == "assistant" and messages[1]["attachments"] == []


def test_title_falls_back_to_the_first_attachment_name(
    cathy: TestClient, chat: Chat, llm: ScriptedLLM
) -> None:
    info = upload_ok(cathy, chat.id, filename="clinic-note.pdf", data=PDF)
    body = send(chat, "", [info["id"]]).json()
    assert body["conversation"]["title"] == "Attachment: clinic-note.pdf"
    listed = cathy.get("/api/chat/conversations").json()["items"]
    assert [c["title"] for c in listed if c["id"] == chat.id] == ["Attachment: clinic-note.pdf"]
    assert chat.detail()["conversation"]["title"] == "Attachment: clinic-note.pdf"


def test_title_is_capped_at_60_characters(cathy: TestClient, chat: Chat) -> None:
    info = upload_ok(cathy, chat.id, filename="very-long-" + "name-" * 20 + ".png")
    title = send(chat, "", [info["id"]]).json()["conversation"]["title"]
    assert title.startswith("Attachment: very-long-") and len(title) <= 60


def test_typed_text_wins_over_the_attachment_for_the_title(
    cathy: TestClient, chat: Chat, llm: ScriptedLLM
) -> None:
    info = upload_ok(cathy, chat.id, filename="n.png")
    llm.push(simple_turn(Intent.UNCLEAR))
    body = send(chat, "please look at this", [info["id"]]).json()
    assert body["conversation"]["title"] == "please look at this"


def test_a_later_file_only_message_does_not_change_the_title(
    cathy: TestClient, chat: Chat, llm: ScriptedLLM
) -> None:
    llm.push(simple_turn(Intent.UNCLEAR))
    chat.say("first words")
    info = upload_ok(cathy, chat.id)
    assert send(chat, "", [info["id"]]).json()["conversation"]["title"] == "first words"


def test_the_turn_input_carries_the_file_bytes(
    cathy: TestClient, chat: Chat, llm: ScriptedLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.chat.service as service

    seen: list[ChatTurnDeps] = []
    real = service.run_turn

    def spy(deps: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(deps)
        return real(deps, *args, **kwargs)

    monkeypatch.setattr(service, "run_turn", spy)
    data = PNG + b"turn input"
    info = upload_ok(cathy, chat.id, data, filename="r.png")
    llm.push(simple_turn(Intent.UNCLEAR))
    assert send(chat, "what is this?", [info["id"]]).status_code == 200
    (deps,) = seen
    (item,) = deps.attachments
    assert (item.id, item.filename, item.content_type, item.size_bytes) == (
        info["id"],
        "r.png",
        "image/png",
        len(data),
    )
    assert item.data == data


def test_unknown_or_foreign_conversation_is_404(
    amy: TestClient, amy_chat: Chat, chat: Chat
) -> None:
    assert send(chat.__class__(amy, chat.id), "hi", []).status_code == 404
