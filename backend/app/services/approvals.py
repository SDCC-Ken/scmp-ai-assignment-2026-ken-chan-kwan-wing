"""The approver's side of a request: queue, inspection with limits, and the decision.

* Visibility is exactly "``pending_approval`` and assigned to this approver" (per user, not per
  role); the type must match the approver's queue (HR: leave, Finance: claims). Anything else
  looks nonexistent (``ApprovalNotFound``, the route answers 404).
* Limits are context, never a gate: an over-limit request can still be approved, and the
  approver is told so ("You decide.").
* ``decide`` re-uses the domain rules (``can_decide`` through ``apply_transition``) and claims the
  request with ONE conditional UPDATE (``WHERE status = 'pending_approval'``), so exactly one of
  two concurrent decisions wins; the loser gets ``ApprovalConflict`` (409). The status change,
  the audit row and the notifications are written in the same transaction.
* The reviewer note is stored on the request only; the audit metadata records ``note_present``.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.chat import cards as card_builders
from app.chat.format import fmt_money, plural
from app.db.models import Attachment, LeaveRequest, Notification, User
from app.domain.enums import RequestStatus, RequestType
from app.domain.errors import InvalidTransitionError, NotAuthorizedError
from app.domain.transitions import apply_transition
from app.schemas.approvals import (
    ApprovalDetail,
    ApprovalFlags,
    ApprovalList,
    ApprovalListItem,
    ApprovalRequestView,
    DecisionResponse,
    DepartmentBudgetView,
    DetailField,
    EmployeeRef,
    LeaveBalanceView,
    Limits,
    TeamOverlapView,
)
from app.services.attachments import to_info
from app.services.audit import create_notification, record_audit
from app.services.balances import (
    BudgetAfter,
    LeaveBalanceAfter,
    TeamOverlapEntry,
    department_budget,
    leave_balance_after,
    team_overlap,
)
from app.services.requests import (
    MODELS,
    Req,
    entity_type,
    latest_external_reference,
    request_values,
    summary_text,
)

PENDING = RequestStatus.PENDING_APPROVAL
# The approver's own "new / changed request" notifications are read once they have decided.
APPROVER_NOTIFICATION_EVENTS = ("request.submitted", "request.updated")
DECISION_STATUS = {"approve": RequestStatus.APPROVED, "reject": RequestStatus.REJECTED}
DECISION_EVENT = {"approve": "request.approved", "reject": "request.rejected"}


class ApprovalNotFound(Exception):
    """Unknown, not assigned to the caller, or not in the caller's queue (route: 404)."""


class ApprovalConflict(Exception):
    """The request is no longer pending, or another decision won the race (route: 409)."""


class ApprovalForbidden(Exception):
    """The domain refused the actor (for example a self-assigned request; route: 403)."""


def queue_type(user: User) -> RequestType | None:
    """The request type this user decides: HR approver leave, Finance approver claims."""
    return RequestType(user.approves) if user.approves else None


def parse_request_type(value: str) -> RequestType | None:
    try:
        return RequestType(value)
    except ValueError:
        return None


# ---- lookups ------------------------------------------------------------------------------
def _assigned(session: Session, approver: User, request_type: RequestType, request_id: int) -> Req:
    """The request when it is of the caller's queue type and assigned to the caller (any status).

    Own requests never count as assigned (no self-approval, even for inconsistent data).
    """
    if queue_type(approver) != request_type:
        raise ApprovalNotFound
    req = session.get(MODELS[request_type], request_id)
    if req is None or req.approver_user_id != approver.id or req.employee_id == approver.id:
        raise ApprovalNotFound
    return req


def pending_queue(session: Session, approver: User) -> list[Req]:
    """The caller's pending requests, oldest submitted first."""
    rtype = queue_type(approver)
    if rtype is None:
        return []
    model = MODELS[rtype]
    return list(
        session.scalars(
            select(model)
            .where(
                model.status == PENDING,
                model.approver_user_id == approver.id,
                model.employee_id != approver.id,
            )
            .order_by(model.submitted_at, model.id)
        )
    )


# ---- limit context ------------------------------------------------------------------------
@dataclass(frozen=True)
class LimitContext:
    balance: LeaveBalanceAfter | None
    budget: BudgetAfter | None
    overlap: list[TeamOverlapEntry]

    @property
    def over_limit(self) -> bool:
        return bool(
            (self.balance and self.balance.over_limit) or (self.budget and self.budget.over_limit)
        )


def limit_context(session: Session, req: Req) -> LimitContext:
    """Balance or department budget the approver sees for ``req`` (the request itself is
    excluded from the totals and reported as "requested"), plus the team overlap for leave."""
    if isinstance(req, LeaveRequest):
        balance = leave_balance_after(
            session,
            req.employee_id,
            req.start_date.year,
            req.leave_type,
            req.working_days,
            exclude_request_id=req.id,
        )
        return LimitContext(balance, None, team_overlap(session, req))
    employee = session.get(User, req.employee_id)
    budget = None
    if employee is not None and employee.department_id is not None:
        position = department_budget(
            session, employee.department_id, req.receipt_date.year, exclude_request_id=req.id
        )
        budget = position.budget_after(req.amount) if position is not None else None
    return LimitContext(None, budget, [])


def warnings_for(ctx: LimitContext) -> list[str]:
    out: list[str] = []
    if ctx.balance is not None and ctx.balance.over_limit:
        over = -ctx.balance.remaining_after_days
        out.append(
            f"Over the {ctx.balance.leave_type.value} leave balance by "
            f"{plural(over, 'day')}. You decide."
        )
    if ctx.budget is not None and ctx.budget.over_limit:
        over = -ctx.budget.remaining_after_amount
        out.append(
            f"This claim takes {ctx.budget.department} over its annual claim limit by "
            f"{fmt_money(over, ctx.budget.currency)}. You decide."
        )
    return out


# ---- read models --------------------------------------------------------------------------
def _employee_ref(session: Session, employee_id: int) -> EmployeeRef:
    user = session.get(User, employee_id)
    if user is None:  # unreachable (foreign key), but never crash a queue over it
        return EmployeeRef(id=employee_id, display_name="Unknown employee")
    return EmployeeRef(
        id=user.id,
        display_name=user.display_name,
        department=user.department.name if user.department else None,
    )


def _attachments(session: Session, req: Req) -> list[Attachment]:
    return list(
        session.scalars(
            select(Attachment)
            .where(Attachment.request_type == req.request_type, Attachment.request_id == req.id)
            .order_by(Attachment.id)
        )
    )


def list_queue(session: Session, approver: User) -> ApprovalList:
    items: list[ApprovalListItem] = []
    for req in pending_queue(session, approver):
        ctx = limit_context(session, req)
        has_files = (
            session.scalar(
                select(func.count())
                .select_from(Attachment)
                .where(Attachment.request_type == req.request_type, Attachment.request_id == req.id)
            )
            or 0
        ) > 0
        items.append(
            ApprovalListItem(
                request_type=req.request_type,
                id=req.id,
                employee=_employee_ref(session, req.employee_id),
                summary=summary_text(req),
                submitted_at=req.submitted_at,
                flags=ApprovalFlags(
                    over_limit=ctx.over_limit,
                    team_overlap_count=len(ctx.overlap),
                    has_attachments=has_files,
                ),
            )
        )
    return ApprovalList(items=items, count=len(items))


def _detail_fields(req: Req) -> list[DetailField]:
    """Same labels and values as the chat confirmation card (never the e-mail address)."""
    values = request_values(req)
    shown = card_builders.display_values(
        req.request_type, values, working_days=values.get("working_days")
    )
    card = card_builders.build_card(
        action="create", request_type=req.request_type, request_id=req.id, new=shown
    )
    return [DetailField(key=f.key, label=f.label, value=f.value) for f in card.fields]


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _balance_view(b: LeaveBalanceAfter) -> LeaveBalanceView:
    return LeaveBalanceView(
        leave_type=b.leave_type,
        year=b.year,
        entitled_days=float(b.entitled_days),
        approved_days=float(b.approved_days),
        pending_other_days=float(b.pending_other_days),
        requested_days=float(b.requested_days),
        remaining_after_days=float(b.remaining_after_days),
        over_limit=b.over_limit,
    )


def _budget_view(b: BudgetAfter) -> DepartmentBudgetView:
    return DepartmentBudgetView(
        department=b.department,
        year=b.year,
        limit_amount=_money(b.limit_amount),
        approved_amount=_money(b.approved_amount),
        pending_other_amount=_money(b.pending_other_amount),
        requested_amount=_money(b.requested_amount),
        remaining_after_amount=_money(b.remaining_after_amount),
        over_limit=b.over_limit,
        currency=b.currency,
    )


def get_detail(
    session: Session, approver: User, request_type: RequestType, request_id: int
) -> ApprovalDetail:
    """Everything the approver needs to decide. 404 unless pending and assigned to the caller."""
    req = _assigned(session, approver, request_type, request_id)
    if req.status != PENDING:
        raise ApprovalNotFound
    ctx = limit_context(session, req)
    return ApprovalDetail(
        request=ApprovalRequestView(
            request_type=req.request_type,
            id=req.id,
            status=req.status,
            submitted_at=req.submitted_at,
            employee=_employee_ref(session, req.employee_id),
            fields=_detail_fields(req),
            attachments=[to_info(a) for a in _attachments(session, req)],
            external_reference_id=latest_external_reference(session, req),
        ),
        limits=Limits(
            leave_balance=_balance_view(ctx.balance) if ctx.balance else None,
            department_budget=_budget_view(ctx.budget) if ctx.budget else None,
        ),
        team_overlap=[
            TeamOverlapView(
                employee=o.employee,
                leave_type=o.leave_type,
                start_date=o.start_date.isoformat(),
                end_date=o.end_date.isoformat(),
                status=o.status,
                working_days=float(o.working_days),
            )
            for o in ctx.overlap
        ],
        warnings=warnings_for(ctx),
    )


# ---- the decision -------------------------------------------------------------------------
@dataclass
class _Snapshot:
    """A detached copy of the request that satisfies the domain's ``TransitionableRequest``.

    ``apply_transition`` validates the rules and computes the new values on this copy; the
    real row is then changed by one conditional UPDATE (see ``decide``)."""

    request_type: RequestType
    employee_id: int
    approver_user_id: int | None
    status: RequestStatus
    submitted_at: datetime | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    reviewer_note: str | None
    updated_at: datetime


def audit_snapshot(ctx: LimitContext) -> dict[str, Any] | None:
    """The numbers the approver saw (Decimals become strings in the audit writer)."""
    if ctx.balance is not None:
        b = ctx.balance
        return {
            "kind": "leave_balance",
            "leave_type": b.leave_type.value,
            "year": b.year,
            "entitled": b.entitled_days,
            "approved": b.approved_days,
            "pending_other": b.pending_other_days,
            "requested": b.requested_days,
            "remaining_after": b.remaining_after_days,
        }
    if ctx.budget is not None:
        c = ctx.budget
        return {
            "kind": "department_budget",
            "department": c.department,
            "year": c.year,
            "currency": c.currency,
            "limit": c.limit_amount,
            "approved": c.approved_amount,
            "pending_other": c.pending_other_amount,
            "requested": c.requested_amount,
            "remaining_after": c.remaining_after_amount,
        }
    return None


def decide(
    session: Session,
    approver: User,
    request_type: RequestType,
    request_id: int,
    decision: str,
    note: str | None,
) -> DecisionResponse:
    """Approve or reject. Commits on success; nothing is written on any error.

    ``note`` must already be trimmed (empty -> None, see ``DecisionBody``).
    """
    req = _assigned(session, approver, request_type, request_id)
    if req.status != PENDING:
        raise ApprovalConflict
    ctx = limit_context(session, req)
    target = DECISION_STATUS[decision]
    snap = _Snapshot(
        request_type=req.request_type,
        employee_id=req.employee_id,
        approver_user_id=req.approver_user_id,
        status=req.status,
        submitted_at=req.submitted_at,
        reviewed_by_user_id=req.reviewed_by_user_id,
        reviewed_at=req.reviewed_at,
        reviewer_note=req.reviewer_note,
        updated_at=req.updated_at,
    )
    try:
        transition = apply_transition(snap, target, actor=approver, note=note)
    except InvalidTransitionError:
        raise ApprovalConflict from None
    except NotAuthorizedError as exc:
        raise ApprovalForbidden(str(exc)) from None
    assert snap.reviewed_at is not None

    model = MODELS[request_type]
    try:
        claimed = session.execute(
            update(model)
            .where(
                model.id == req.id,
                model.status == PENDING,
                model.approver_user_id == approver.id,
            )
            .values(
                status=target,
                reviewed_by_user_id=approver.id,
                reviewed_at=snap.reviewed_at,
                reviewer_note=snap.reviewer_note,
                updated_at=snap.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:  # somebody else decided (or cancelled) it first
            session.rollback()
            raise ApprovalConflict
        metadata: dict[str, Any] = {
            "note_present": snap.reviewer_note is not None,
            "over_limit": ctx.over_limit,
            "snapshot": audit_snapshot(ctx),
            "employee_id": req.employee_id,
        }
        if request_type == RequestType.LEAVE:
            metadata["team_overlap_count"] = len(ctx.overlap)
        record_audit(
            session,
            entity_type=entity_type(request_type),
            entity_id=req.id,
            event_type=DECISION_EVENT[decision],
            actor_user_id=approver.id,
            from_status=transition.from_status,
            to_status=transition.to_status,
            metadata=metadata,
            created_at=snap.reviewed_at,
        )
        create_notification(
            session,
            recipient_user_id=req.employee_id,
            event_type=DECISION_EVENT[decision],
            request_type=request_type,
            request_id=req.id,
            created_at=snap.reviewed_at,
        )
        session.execute(
            update(Notification)
            .where(
                Notification.recipient_user_id == approver.id,
                Notification.request_type == request_type,
                Notification.request_id == req.id,
                Notification.event_type.in_(APPROVER_NOTIFICATION_EVENTS),
                Notification.read_at.is_(None),
            )
            .values(read_at=snap.reviewed_at)
            .execution_options(synchronize_session=False)
        )
        session.commit()
    except BaseException:
        session.rollback()
        raise
    session.expire(req)
    return DecisionResponse(
        request_type=request_type, id=req.id, status=target, reviewed_at=snap.reviewed_at
    )


__all__ = [
    "ApprovalConflict",
    "ApprovalForbidden",
    "ApprovalNotFound",
    "decide",
    "get_detail",
    "list_queue",
    "parse_request_type",
    "queue_type",
]
