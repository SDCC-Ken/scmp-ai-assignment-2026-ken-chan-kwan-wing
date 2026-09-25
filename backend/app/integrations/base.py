"""Submission adapter interface + the ONLY fields that may leave the system.

INTEGRATOR-OWNED CONTRACT for Phase 2. The payload models define exactly what is sent to
the ReqRes mock API (``POST https://reqres.in/api/users``): see ``to_wire()`` on each
payload for the exact JSON. Everything else (day parts, working days, currency, statuses,
ids) stays in SQLite. ReqRes currently needs NO API key (Ken confirmed and a live call
succeeded on 2026-09-25); send ``x-api-key`` only when REQRES_API_KEY is configured.
Sample response: ``{"id": "123", "createdAt": "..."}`` (plus echoed fields and ``_meta``,
which must be ignored).
"""

from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from app.domain.enums import ClaimType, LeaveType


class LeaveSubmissionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_email: str
    leave_type: LeaveType
    start_date: date
    end_date: date

    def to_wire(self) -> dict[str, Any]:
        """The exact JSON body of the assignment's Leave Submission API (note `email`, and
        the title-cased leave type shown in the spec, e.g. "Annual")."""
        return {
            "email": self.employee_email,
            "leave_type": self.leave_type.value.title(),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
        }


class ClaimSubmissionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_email: str
    claim_type: ClaimType
    amount: Decimal
    receipt_date: date

    def to_wire(self) -> dict[str, Any]:
        """The exact JSON body for a Staff Claim (same endpoint, claim parameters instead of
        leave parameters). `amount` is a JSON number."""
        return {
            "email": self.employee_email,
            "claim_type": self.claim_type.value.title(),
            "amount": float(self.amount),
            "receipt_date": self.receipt_date.isoformat(),
        }


class SubmissionResult(BaseModel):
    """Outcome of one submission attempt; never contains secrets."""

    ok: bool
    http_status: int | None = None
    external_reference_id: str | None = None  # e.g. ReqRes "id"
    response_summary: dict[str, Any] = {}  # small allow-listed subset (id, createdAt)
    error_message: str | None = None  # short, user-safe (no keys, no raw bodies)


class SubmissionAdapter(Protocol):
    provider: str  # "reqres" | "fake"

    def submit_leave(self, payload: LeaveSubmissionPayload) -> SubmissionResult: ...

    def submit_claim(self, payload: ClaimSubmissionPayload) -> SubmissionResult: ...
