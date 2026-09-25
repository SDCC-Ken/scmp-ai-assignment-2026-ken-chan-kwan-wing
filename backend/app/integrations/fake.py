"""In-process fake submission adapter for offline development and tests.

This is NOT the ReqRes integration. It makes no network calls; it must never be presented as
the assignment's required ``POST https://reqres.in/api/users`` integration. Use
``SUBMISSION_PROVIDER=reqres`` (the default) for the real hosted mock API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.integrations.base import (
    ClaimSubmissionPayload,
    LeaveSubmissionPayload,
    SubmissionResult,
)

Payload = LeaveSubmissionPayload | ClaimSubmissionPayload


@dataclass(frozen=True)
class FakeCall:
    """One recorded submission: the payload model and the exact wire body ``to_wire()``."""

    kind: str  # "leave" | "claim"
    payload: Payload
    body: dict[str, Any]


class FakeSubmissionAdapter:
    provider = "fake"

    def __init__(self) -> None:
        self.calls: list[FakeCall] = []  # every submission received, in order
        self._counter = 0
        self._fail_next = 0  # remaining forced failures (counted)
        self._next_failure: SubmissionResult | None = None
        self._persistent_failure: SubmissionResult | None = None

    # -- configuration ---------------------------------------------------------------------
    def fail_with(self, http_status: int | None, message: str) -> None:
        """Fail EVERY submission until ``succeed()`` is called."""
        self._persistent_failure = SubmissionResult(
            ok=False, http_status=http_status, error_message=message
        )

    def fail_next(
        self, n: int = 1, http_status: int | None = 503, message: str = "Fake submission failure"
    ) -> None:
        """Fail the next ``n`` submissions, then succeed again."""
        self._fail_next = n
        self._next_failure = SubmissionResult(
            ok=False, http_status=http_status, error_message=message
        )

    def raise_timeout(self, n: int = 1) -> None:
        """Simulate a timeout for the next ``n`` submissions.

        Like the real adapter this returns a failed result (no exception): ``http_status`` is
        None and the message says the request timed out.
        """
        self.fail_next(n, http_status=None, message="Fake submission timed out")

    def succeed(self) -> None:
        """Clear every configured failure."""
        self._fail_next = 0
        self._next_failure = None
        self._persistent_failure = None

    # -- SubmissionAdapter -----------------------------------------------------------------
    def submit_leave(self, payload: LeaveSubmissionPayload) -> SubmissionResult:
        return self._handle("leave", payload)

    def submit_claim(self, payload: ClaimSubmissionPayload) -> SubmissionResult:
        return self._handle("claim", payload)

    def _handle(self, kind: str, payload: Payload) -> SubmissionResult:
        self.calls.append(FakeCall(kind=kind, payload=payload, body=payload.to_wire()))
        if self._fail_next > 0 and self._next_failure is not None:
            self._fail_next -= 1
            return self._next_failure.model_copy()
        if self._persistent_failure is not None:
            return self._persistent_failure.model_copy()
        self._counter += 1
        ref = f"fake-{self._counter}"
        return SubmissionResult(
            ok=True,
            http_status=201,
            external_reference_id=ref,
            response_summary={"id": ref},
        )
