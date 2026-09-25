"""Test doubles and small helpers for the chat tests (no network, no real LLM)."""

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from app.domain.enums import ClaimType, DayPart, LeaveType, RequestStatus, RequestType
from app.integrations.base import (
    ClaimSubmissionPayload,
    LeaveSubmissionPayload,
    SubmissionResult,
)
from app.llm.schemas import (
    AgentTurn,
    AttachmentInput,
    ClaimFields,
    Intent,
    LeaveFields,
    LLMContext,
    RequestRef,
    StatusQuery,
)

TODAY = date(2026, 9, 25)  # a Friday; Hong Kong "today" in every chat test


class ScriptedLLM:
    """Returns queued ``AgentTurn`` objects (or raises queued exceptions), records every call."""

    name = "scripted"
    model = "scripted"

    def __init__(self) -> None:
        self.queue: list[AgentTurn | Exception] = []
        self.calls: list[tuple[str, LLMContext]] = []
        self.attachments_seen: list[list[AttachmentInput]] = []  # files of each call (may be [])
        self.on_call: Callable[[], None] | None = None

    def push(self, *items: AgentTurn | Exception) -> None:
        self.queue.extend(items)

    def analyse(
        self,
        user_message: str,
        context: LLMContext,
        attachments: Sequence[AttachmentInput] = (),
    ) -> AgentTurn:
        self.calls.append((user_message, context))
        self.attachments_seen.append(list(attachments))
        if self.on_call is not None:
            self.on_call()
        if not self.queue:
            raise AssertionError("ScriptedLLM queue is empty: the test did not expect an LLM call")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RecordingAdapter:
    """A ``SubmissionAdapter`` that records payloads and can be told to fail."""

    provider = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []  # (kind, wire body)
        self.payloads: list[LeaveSubmissionPayload | ClaimSubmissionPayload] = []
        self.failures: list[SubmissionResult] = []
        self.on_call: Callable[[], None] | None = None
        self._counter = 100

    def fail_next(self, http_status: int = 503, error: str = "Service unavailable") -> None:
        self.failures.append(
            SubmissionResult(ok=False, http_status=http_status, error_message=error)
        )

    def _result(self) -> SubmissionResult:
        if self.on_call is not None:
            self.on_call()
        if self.failures:
            return self.failures.pop(0)
        self._counter += 1
        ref = str(self._counter)
        return SubmissionResult(
            ok=True,
            http_status=201,
            external_reference_id=ref,
            response_summary={"id": ref, "createdAt": "2026-09-25T03:00:00.000Z"},
        )

    def submit_leave(self, payload: LeaveSubmissionPayload) -> SubmissionResult:
        self.payloads.append(payload)
        self.calls.append(("leave", payload.to_wire()))
        return self._result()

    def submit_claim(self, payload: ClaimSubmissionPayload) -> SubmissionResult:
        self.payloads.append(payload)
        self.calls.append(("claim", payload.to_wire()))
        return self._result()


# ---- AgentTurn builders -------------------------------------------------------------------------
def d(text: str) -> date:
    return date.fromisoformat(text)


def leave_turn(intent: Intent = Intent.CREATE_LEAVE, **fields: Any) -> AgentTurn:
    return AgentTurn(
        intent=intent,
        request_type=RequestType.LEAVE,
        leave=LeaveFields(**fields),
        confidence=0.9,
    )


def details_leave(**fields: Any) -> AgentTurn:
    return leave_turn(Intent.PROVIDE_DETAILS, **fields)


def claim_turn(intent: Intent = Intent.CREATE_CLAIM, **fields: Any) -> AgentTurn:
    return AgentTurn(
        intent=intent,
        request_type=RequestType.CLAIM,
        claim=ClaimFields(**fields),
        confidence=0.9,
    )


def details_claim(**fields: Any) -> AgentTurn:
    return claim_turn(Intent.PROVIDE_DETAILS, **fields)


def update_turn(
    *,
    request_id: int | None = None,
    request_type: RequestType | None = None,
    hint: str | None = None,
    leave: dict[str, Any] | None = None,
    claim: dict[str, Any] | None = None,
) -> AgentTurn:
    return AgentTurn(
        intent=Intent.UPDATE_REQUEST,
        request_type=request_type,
        target=RequestRef(request_id=request_id, request_type=request_type, hint=hint),
        leave=LeaveFields(**leave) if leave else None,
        claim=ClaimFields(**claim) if claim else None,
        confidence=0.9,
    )


def cancel_turn(
    *,
    request_id: int | None = None,
    request_type: RequestType | None = None,
    hint: str | None = None,
) -> AgentTurn:
    return AgentTurn(
        intent=Intent.CANCEL_REQUEST,
        request_type=request_type,
        target=RequestRef(request_id=request_id, request_type=request_type, hint=hint),
        confidence=0.9,
    )


def status_turn(
    *,
    request_type: RequestType | None = None,
    request_id: int | None = None,
    status: RequestStatus | None = None,
) -> AgentTurn:
    return AgentTurn(
        intent=Intent.CHECK_STATUS,
        request_type=request_type,
        status_query=StatusQuery(request_type=request_type, request_id=request_id, status=status),
        confidence=0.9,
    )


def simple_turn(intent: Intent, **kw: Any) -> AgentTurn:
    return AgentTurn(intent=intent, confidence=0.9, **kw)


FULL_LEAVE = {
    "leave_type": LeaveType.ANNUAL,
    "start_date": d("2026-10-05"),
    "end_date": d("2026-10-07"),
}
VALID_CLAIM = {
    "claim_type": ClaimType.TRAVEL,
    "amount": 120.0,
    "receipt_date": d("2026-09-20"),
}
PM = DayPart.PM
AM = DayPart.AM


# ---- HTTP wrapper ----------------------------------------------------------------------------
class Chat:
    """Thin wrapper around one conversation on a logged-in ``TestClient``."""

    def __init__(self, client: TestClient, conversation_id: int | None = None) -> None:
        self.client = client
        if conversation_id is None:
            response = client.post("/api/chat/conversations")
            assert response.status_code == 201, response.text
            conversation_id = response.json()["id"]
        self.id = conversation_id

    def say_raw(self, text: str) -> Any:
        return self.client.post(
            f"/api/chat/conversations/{self.id}/messages", json={"content": text}
        )

    def say(self, text: str) -> dict[str, Any]:
        response = self.say_raw(text)
        assert response.status_code == 200, response.text
        return response.json()

    def act_raw(self, card_id: str, action: str = "confirm") -> Any:
        return self.client.post(
            f"/api/chat/conversations/{self.id}/actions",
            json={"card_id": card_id, "action": action},
        )

    def act(self, card_id: str, action: str = "confirm") -> dict[str, Any]:
        response = self.act_raw(card_id, action)
        assert response.status_code == 200, response.text
        return response.json()

    def detail(self) -> dict[str, Any]:
        response = self.client.get(f"/api/chat/conversations/{self.id}")
        assert response.status_code == 200, response.text
        return response.json()


def ui_of(response: dict[str, Any], index: int = -1) -> dict[str, Any] | None:
    return response["assistant_messages"][index]["ui"]


def text_of(response: dict[str, Any], index: int = -1) -> str:
    return response["assistant_messages"][index]["content"]


def card_of(response: dict[str, Any]) -> dict[str, Any]:
    ui = ui_of(response)
    assert ui is not None and ui["type"] == "confirmation_card", response
    return ui


def field_values(card: dict[str, Any]) -> dict[str, str]:
    return {f["key"]: f["value"] for f in card["fields"]}


# ---- seed ids (deterministic order in app/seed.py; verified in test_seed_id_assumptions) -----
AMY_PENDING_LEAVE = 1  # L1, Amy, pending_approval
AMY_PENDING_CLAIM = 1  # C1, Amy, pending_approval
CATHY_APPROVED_LEAVE = 3  # L3
CATHY_APPROVED_CLAIM = 3  # C3
BEN_REJECTED_LEAVE = 4  # L4, reviewer note "Team is short-staffed..."
BEN_REJECTED_CLAIM = 4  # C4


def submit_leave(chat: Chat, llm: ScriptedLLM, **fields: Any) -> int:
    """Create + confirm a leave through the chat and return the new request id."""
    llm.push(leave_turn(**(fields or FULL_LEAVE)))
    card = card_of(chat.say("create leave"))
    result = ui_of(chat.act(card["card_id"]))
    assert result["type"] == "result_card" and result["outcome"] == "submitted", result
    return int(result["request_id"])


def submit_claim(chat: Chat, llm: ScriptedLLM, **fields: Any) -> int:
    llm.push(claim_turn(**(fields or VALID_CLAIM)))
    card = card_of(chat.say("create claim"))
    result = ui_of(chat.act(card["card_id"]))
    assert result["type"] == "result_card" and result["outcome"] == "submitted", result
    return int(result["request_id"])
