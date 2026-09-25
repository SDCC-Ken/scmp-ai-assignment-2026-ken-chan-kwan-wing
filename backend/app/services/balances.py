"""Leave balances, department claim budgets and team overlap (Phase 3, shown but never blocking).

Counting rules (see docs/limits-and-routing.md):

* only APPROVED requests are deducted; PENDING_APPROVAL ones are reported separately;
* leave counts in the calendar year of its ``start_date`` (no cross-year splitting), claims in
  the calendar year of their ``receipt_date``;
* only ``annual`` and ``sick`` leave have an entitlement (``personal`` / ``unpaid`` have none);
* ``exclude_request_id`` leaves the request being judged out of every total (it is the
  "requested" amount instead), so a pending request is never counted twice.

Day counts are ``Decimal`` in 0.5 steps and money is ``Decimal`` with 2 places. The results are
small frozen dataclasses; nothing here commits or mutates.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ClaimRequest, Department, LeaveEntitlement, LeaveRequest, User
from app.domain.enums import LeaveType, RequestStatus

BALANCE_LEAVE_TYPES: tuple[LeaveType, ...] = (LeaveType.ANNUAL, LeaveType.SICK)
ZERO_DAYS = Decimal("0.0")
ZERO_MONEY = Decimal("0.00")
CURRENCY = "HKD"


def _year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


@dataclass(frozen=True)
class LeaveBalance:
    """One line of "my balance" (``remaining = entitled - approved``; may be negative)."""

    user_id: int
    year: int
    leave_type: LeaveType
    entitled_days: Decimal
    approved_days: Decimal
    pending_days: Decimal
    remaining_days: Decimal


@dataclass(frozen=True)
class LeaveBalanceAfter:
    """The balance as an approver sees it for one specific request."""

    user_id: int
    year: int
    leave_type: LeaveType
    entitled_days: Decimal
    approved_days: Decimal
    pending_other_days: Decimal  # other pending requests, not deducted
    requested_days: Decimal
    remaining_after_days: Decimal  # entitled - approved - requested
    over_limit: bool


@dataclass(frozen=True)
class BudgetAfter:
    department_id: int
    department: str
    year: int
    limit_amount: Decimal
    approved_amount: Decimal
    pending_other_amount: Decimal
    requested_amount: Decimal
    remaining_after_amount: Decimal  # limit - approved - requested
    over_limit: bool
    currency: str = CURRENCY


@dataclass(frozen=True)
class DepartmentBudget:
    department_id: int
    department: str
    year: int
    limit_amount: Decimal
    approved_amount: Decimal
    pending_other_amount: Decimal
    currency: str = CURRENCY

    @property
    def remaining_amount(self) -> Decimal:
        return self.limit_amount - self.approved_amount

    def budget_after(self, requested_amount: Decimal) -> BudgetAfter:
        remaining_after = self.limit_amount - self.approved_amount - requested_amount
        return BudgetAfter(
            department_id=self.department_id,
            department=self.department,
            year=self.year,
            limit_amount=self.limit_amount,
            approved_amount=self.approved_amount,
            pending_other_amount=self.pending_other_amount,
            requested_amount=requested_amount,
            remaining_after_amount=remaining_after,
            over_limit=remaining_after < 0,
            currency=self.currency,
        )


@dataclass(frozen=True)
class TeamOverlapEntry:
    employee_id: int
    employee: str  # display name
    leave_type: LeaveType
    start_date: date
    end_date: date
    status: RequestStatus
    working_days: Decimal


def _entitled_days(
    session: Session, user_id: int, year: int, leave_type: LeaveType | str
) -> Decimal | None:
    leave_type = LeaveType(leave_type)
    if leave_type not in BALANCE_LEAVE_TYPES:
        return None
    return session.scalar(
        select(LeaveEntitlement.entitled_days).where(
            LeaveEntitlement.user_id == user_id,
            LeaveEntitlement.year == year,
            LeaveEntitlement.leave_type == leave_type,
        )
    )


def _leave_days(
    session: Session,
    user_id: int,
    year: int,
    leave_type: LeaveType,
    status: RequestStatus,
    exclude_request_id: int | None,
) -> Decimal:
    first, last = _year_bounds(year)
    query = select(LeaveRequest.working_days).where(
        LeaveRequest.employee_id == user_id,
        LeaveRequest.leave_type == leave_type,
        LeaveRequest.status == status,
        LeaveRequest.start_date >= first,
        LeaveRequest.start_date <= last,
    )
    if exclude_request_id is not None:
        query = query.where(LeaveRequest.id != exclude_request_id)
    return sum(session.scalars(query), ZERO_DAYS)


def leave_balance(
    session: Session, user_id: int, year: int, leave_type: LeaveType | str
) -> LeaveBalance | None:
    """None for personal/unpaid leave or when the user has no entitlement for that year/type."""
    leave_type = LeaveType(leave_type)
    entitled = _entitled_days(session, user_id, year, leave_type)
    if entitled is None:
        return None
    approved = _leave_days(session, user_id, year, leave_type, RequestStatus.APPROVED, None)
    pending = _leave_days(session, user_id, year, leave_type, RequestStatus.PENDING_APPROVAL, None)
    return LeaveBalance(
        user_id=user_id,
        year=year,
        leave_type=leave_type,
        entitled_days=entitled,
        approved_days=approved,
        pending_days=pending,
        remaining_days=entitled - approved,
    )


def leave_balances_for_user(session: Session, user_id: int, year: int) -> list[LeaveBalance]:
    """Annual then sick, only the types the user has an entitlement for in ``year``."""
    lines = (leave_balance(session, user_id, year, t) for t in BALANCE_LEAVE_TYPES)
    return [line for line in lines if line is not None]


def leave_balance_after(
    session: Session,
    user_id: int,
    year: int,
    leave_type: LeaveType | str,
    requested_days: Decimal,
    exclude_request_id: int | None = None,
) -> LeaveBalanceAfter | None:
    """The balance after granting ``requested_days`` (None when there is no balance to show)."""
    leave_type = LeaveType(leave_type)
    entitled = _entitled_days(session, user_id, year, leave_type)
    if entitled is None:
        return None
    approved = _leave_days(
        session, user_id, year, leave_type, RequestStatus.APPROVED, exclude_request_id
    )
    pending_other = _leave_days(
        session, user_id, year, leave_type, RequestStatus.PENDING_APPROVAL, exclude_request_id
    )
    remaining_after = entitled - approved - requested_days
    return LeaveBalanceAfter(
        user_id=user_id,
        year=year,
        leave_type=leave_type,
        entitled_days=entitled,
        approved_days=approved,
        pending_other_days=pending_other,
        requested_days=requested_days,
        remaining_after_days=remaining_after,
        over_limit=remaining_after < 0,
    )


def _claim_amount(
    session: Session,
    department_id: int,
    year: int,
    status: RequestStatus,
    exclude_request_id: int | None,
) -> Decimal:
    first, last = _year_bounds(year)
    query = (
        select(ClaimRequest.amount)
        .join(User, User.id == ClaimRequest.employee_id)
        .where(
            User.department_id == department_id,
            ClaimRequest.status == status,
            ClaimRequest.receipt_date >= first,
            ClaimRequest.receipt_date <= last,
        )
    )
    if exclude_request_id is not None:
        query = query.where(ClaimRequest.id != exclude_request_id)
    return sum(session.scalars(query), ZERO_MONEY)


def department_budget(
    session: Session, department_id: int, year: int, exclude_request_id: int | None = None
) -> DepartmentBudget | None:
    """The department's yearly claim budget position (None when the department is unknown)."""
    department = session.get(Department, department_id)
    if department is None:
        return None
    return DepartmentBudget(
        department_id=department.id,
        department=department.name,
        year=year,
        limit_amount=department.claim_limit_amount,
        approved_amount=_claim_amount(
            session, department_id, year, RequestStatus.APPROVED, exclude_request_id
        ),
        pending_other_amount=_claim_amount(
            session, department_id, year, RequestStatus.PENDING_APPROVAL, exclude_request_id
        ),
    )


def team_overlap(session: Session, request: LeaveRequest) -> list[TeamOverlapEntry]:
    """Active colleagues of the requester's department (the requester excluded) whose APPROVED
    or PENDING leave shares at least one calendar day with ``request``. Oldest start first."""
    requester = session.get(User, request.employee_id)
    if requester is None or requester.department_id is None:
        return []
    rows = session.execute(
        select(LeaveRequest, User.display_name)
        .join(User, User.id == LeaveRequest.employee_id)
        .where(
            User.department_id == requester.department_id,
            User.id != requester.id,
            User.is_active.is_(True),
            LeaveRequest.status.in_([RequestStatus.APPROVED, RequestStatus.PENDING_APPROVAL]),
            LeaveRequest.start_date <= request.end_date,
            LeaveRequest.end_date >= request.start_date,
        )
        .order_by(LeaveRequest.start_date, LeaveRequest.id)
    )
    return [
        TeamOverlapEntry(
            employee_id=leave.employee_id,
            employee=name,
            leave_type=leave.leave_type,
            start_date=leave.start_date,
            end_date=leave.end_date,
            status=leave.status,
            working_days=leave.working_days,
        )
        for leave, name in rows
    ]
