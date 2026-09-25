"""Read-side helpers for the employee's own leave / claim requests (no commits here)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.format import fmt_date_with_part, fmt_days, fmt_money, plural
from app.chat.state import ClaimSlots, ConversationState, LeaveSlots, normalised_values
from app.db.models import ClaimRequest, ExternalSubmission, LeaveRequest
from app.domain.enums import DayPart, RequestStatus, RequestType, SubmissionStatus
from app.llm.schemas import RequestBrief
from app.schemas.chat import STATUS_LABELS

Req = LeaveRequest | ClaimRequest

MODELS: dict[RequestType, type[LeaveRequest] | type[ClaimRequest]] = {
    RequestType.LEAVE: LeaveRequest,
    RequestType.CLAIM: ClaimRequest,
}


def status_label(status: RequestStatus | str) -> str:
    return STATUS_LABELS[RequestStatus(status).value]


def get_own_request(
    session: Session, employee_id: int, request_type: RequestType, request_id: int
) -> Req | None:
    """The request only when it belongs to ``employee_id`` (others' ids look nonexistent)."""
    row = session.get(MODELS[request_type], request_id)
    return row if row is not None and row.employee_id == employee_id else None


def own_requests(
    session: Session,
    employee_id: int,
    *,
    request_type: RequestType | None = None,
    request_id: int | None = None,
    statuses: frozenset[RequestStatus] | set[RequestStatus] | None = None,
    limit: int | None = None,
) -> list[Req]:
    """The employee's requests, newest first (both types merged), optionally filtered."""
    rows: list[Req] = []
    for rtype, model in MODELS.items():
        if request_type is not None and rtype != request_type:
            continue
        query = select(model).where(model.employee_id == employee_id)
        if request_id is not None:
            query = query.where(model.id == request_id)
        if statuses is not None:
            query = query.where(model.status.in_(list(statuses)))
        query = query.order_by(model.created_at.desc(), model.id.desc())
        if limit is not None:
            query = query.limit(limit)
        rows.extend(session.scalars(query))
    rows.sort(key=lambda r: (r.created_at, r.id), reverse=True)
    return rows[:limit] if limit is not None else rows


def summary_text(req: Req) -> str:
    """``Annual leave, Mon 2026-10-05 to Wed 2026-10-07 (2.5 working days)``."""
    if isinstance(req, LeaveRequest):
        first = fmt_date_with_part(req.start_date, DayPart(req.start_day_part))
        if req.start_date == req.end_date:
            span = first
        else:
            span = f"{first} to {fmt_date_with_part(req.end_date, DayPart(req.end_day_part))}"
        days = plural(req.working_days, "working day")
        return f"{req.leave_type.value.title()} leave, {span} ({days})"
    return (
        f"{req.claim_type.value.title()} claim, {fmt_money(req.amount, req.currency)}, "
        f"receipt {req.receipt_date.isoformat()}"
    )


def brief(req: Req) -> RequestBrief:
    if isinstance(req, LeaveRequest):
        text = f"{req.leave_type.value} {req.start_date.isoformat()}..{req.end_date.isoformat()}"
        if DayPart(req.start_day_part) != DayPart.FULL or DayPart(req.end_day_part) != DayPart.FULL:
            text += f" ({fmt_days(req.working_days)} working days)"
    else:
        text = f"{req.claim_type.value} {fmt_money(req.amount, req.currency)} " + (
            req.receipt_date.isoformat()
        )
    return RequestBrief(id=req.id, request_type=req.request_type, status=req.status, summary=text)


def slots_from_request(req: Req) -> LeaveSlots | ClaimSlots:
    if isinstance(req, LeaveRequest):
        return LeaveSlots(
            leave_type=req.leave_type,
            start_date=req.start_date,
            end_date=req.end_date,
            start_day_part=DayPart(req.start_day_part),
            end_day_part=DayPart(req.end_day_part),
        )
    return ClaimSlots(
        claim_type=req.claim_type,
        amount=req.amount,
        currency=req.currency,
        receipt_date=req.receipt_date,
    )


def latest_external_reference(session: Session, req: Req) -> str | None:
    """Reference id of the newest successful mock-API submission of this request."""
    return session.scalar(
        select(ExternalSubmission.external_reference_id)
        .where(
            ExternalSubmission.request_type == req.request_type,
            ExternalSubmission.request_id == req.id,
            ExternalSubmission.status == SubmissionStatus.SUCCESS,
        )
        .order_by(ExternalSubmission.id.desc())
        .limit(1)
    )


def entity_type(request_type: RequestType) -> str:
    return f"{request_type.value}_request"


def request_metadata(req: Req) -> dict[str, Any]:
    return {"request_type": req.request_type.value, "request_id": req.id}


def request_values(req: Req) -> dict[str, str | None]:
    """Normalised field values of a stored request (same keys/format as the draft slots),
    plus ``working_days`` for leave. Used for diffs and for card display."""
    tmp = ConversationState(active_request_type=req.request_type)
    slots = slots_from_request(req)
    if isinstance(slots, LeaveSlots):
        tmp.leave = slots
    else:
        tmp.claim = slots
    values = normalised_values(tmp, req.request_type)
    if isinstance(req, LeaveRequest):
        values["working_days"] = fmt_days(req.working_days)
    return values
