"""Small helpers for the inbox tests (and for tests that need a user with no chat access)."""

from typing import Any

from fastapi.testclient import TestClient

from app.db.models import User
from app.db.session import Database
from app.domain.enums import UserRole


def strip_capabilities(db: Database, email: str) -> None:
    """Make ``email`` a plain employee with no approver configured: it neither files requests
    nor decides a queue, so the chat API refuses it (the gate reads the database live)."""
    with db.session_factory() as s:
        user = s.query(User).filter_by(email=email).one()
        user.role = UserRole.EMPLOYEE
        user.leave_approver_user_id = None
        user.claim_approver_user_id = None
        s.commit()


def open_inbox(client: TestClient) -> Any:
    return client.post("/api/chat/inbox")


def inbox_cards(response_json: dict[str, Any]) -> list[dict[str, Any]]:
    """The inbox cards of a response body (``assistant_messages`` of an open or a turn)."""
    return [
        m["ui"]
        for m in response_json["assistant_messages"]
        if m.get("ui") and m["ui"]["type"] == "inbox_card"
    ]


def texts(response_json: dict[str, Any]) -> list[str]:
    return [m["content"] for m in response_json["assistant_messages"]]


def act(
    client: TestClient,
    conversation_id: int,
    card_id: str,
    action: str,
    **extra: Any,
) -> Any:
    body = {"card_id": card_id, "action": action, **extra}
    return client.post(f"/api/chat/conversations/{conversation_id}/actions", json=body)
