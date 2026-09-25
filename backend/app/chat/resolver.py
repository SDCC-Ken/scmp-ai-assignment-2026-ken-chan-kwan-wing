"""Resolve which existing request the user means (update / cancel). Own requests only."""

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.chat.policy import EDITABLE_STATUSES
from app.db.models import LeaveRequest
from app.domain.enums import RequestStatus, RequestType
from app.llm.schemas import RequestRef
from app.services.requests import Req, own_requests, status_label, summary_text

_STOPWORDS = frozenset(
    "the my a an leave claim request requests starting start ending end on for of from to that "
    "one last latest recent next this please i want would like it me and with amount".split()
)


@dataclass(frozen=True)
class Resolved:
    request: Req


@dataclass(frozen=True)
class Unresolved:
    message: str


def noun(request_type: RequestType) -> str:
    return "leave request" if request_type == RequestType.LEAVE else "claim"


def describe(req: Req) -> str:
    return f"#{req.id} {summary_text(req)} - {status_label(req.status)}"


def _date_words(day: date) -> set[str]:
    return {
        day.isoformat(),
        str(day.day),
        f"{day.day:02d}",
        f"{day:%b}".lower(),
        f"{day:%B}".lower(),
        f"{day:%a}".lower(),
        f"{day:%A}".lower(),
        str(day.year),
        str(day.month),
    }


def _haystack(req: Req) -> set[str]:
    words = {req.request_type.value, req.status.value, *status_label(req.status).lower().split()}
    if isinstance(req, LeaveRequest):
        words.add(req.leave_type.value)
        words |= _date_words(req.start_date) | _date_words(req.end_date)
    else:
        words.add(req.claim_type.value)
        words |= {format(req.amount, "f"), str(req.amount.to_integral_value())}
        words |= _date_words(req.receipt_date)
    return words


def _hint_tokens(hint: str | None) -> list[str]:
    if not hint:
        return []
    tokens = re.findall(r"[a-z0-9.\-]+", hint.lower())
    return [t for t in tokens if t not in _STOPWORDS]


def _best_match(pool: list[Req], tokens: list[str]) -> Req | None:
    """The single request whose fields match the most hint words (None on a tie / no match)."""
    if not tokens:
        return None
    scored = sorted(
        ((sum(1 for t in tokens if t in _haystack(r)), r) for r in pool),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]


def not_editable_message(req: Req, verb: str) -> str:
    text = (
        f"{noun(req.request_type).capitalize()} #{req.id} is {status_label(req.status)}, so it "
        f"can't be {'cancelled' if verb == 'cancel' else 'changed'} any more. Only requests "
        "that have not been reviewed yet can be edited or cancelled."
    )
    if req.status == RequestStatus.REJECTED and req.reviewer_note:
        text += f" Reviewer note: {req.reviewer_note}"
    return text


def resolve_target(
    session: Session, employee_id: int, ref: RequestRef | None, verb: str
) -> Resolved | Unresolved:
    """``verb`` is ``"change"`` or ``"cancel"`` (only used in wording)."""
    ref_id = ref.request_id if ref else None
    ref_type = ref.request_type if ref else None

    if ref_id is not None:
        matches = own_requests(session, employee_id, request_type=ref_type, request_id=ref_id)
        if not matches:
            return Unresolved(
                f"I couldn't find a request with id {ref_id} among your requests. "
                "Ask me to show your requests to see their ids."
            )
        if len(matches) > 1:
            return Unresolved(
                f"There is both a leave request and a claim with id {ref_id}. Which one do you "
                "mean: the leave request or the claim?"
            )
        req = matches[0]
        if req.status not in EDITABLE_STATUSES:
            return Unresolved(not_editable_message(req, verb))
        return Resolved(req)

    pool = own_requests(session, employee_id, request_type=ref_type)
    if not pool:
        kind = {"leave": "leave requests", "claim": "claims"}.get(
            ref_type.value if ref_type else "", "requests"
        )
        return Unresolved(f"You don't have any {kind} yet, so there is nothing to {verb}.")

    hinted = _best_match(pool, _hint_tokens(ref.hint if ref else None))
    if hinted is not None:
        if hinted.status not in EDITABLE_STATUSES:
            return Unresolved(not_editable_message(hinted, verb))
        return Resolved(hinted)

    editable = [r for r in pool if r.status in EDITABLE_STATUSES]
    if len(editable) == 1:
        return Resolved(editable[0])
    if not editable:
        lines = "; ".join(describe(r) for r in pool[:5])
        return Unresolved(
            f"None of your requests can be {'cancelled' if verb == 'cancel' else 'changed'}: "
            f"approved, rejected and cancelled requests are final. Your latest: {lines}."
        )
    lines = "; ".join(describe(r) for r in editable[:10])
    return Unresolved(
        f"Which request do you mean? You can still {verb} these: {lines}. "
        "Tell me the id, for example #" + str(editable[0].id) + "."
    )
