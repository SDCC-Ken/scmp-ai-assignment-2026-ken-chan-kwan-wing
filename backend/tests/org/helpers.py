"""Builders for a tiny fictional organisation (bare tables, no seed) used by the org tests."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import ClaimRequest, Department, LeaveEntitlement, LeaveRequest, User
from app.domain.clock import utcnow
from app.domain.enums import (
    ClaimType,
    LeaveType,
    RequestStatus,
    UserRole,
)

S = RequestStatus
DECIDED = (S.APPROVED, S.REJECTED)


def add_department(session: Session, name: str = "IT", limit: str = "1000.00") -> Department:
    row = Department(name=name, claim_limit_amount=Decimal(limit))
    session.add(row)
    session.flush()
    return row


def add_user(
    session: Session,
    name: str,
    role: UserRole = UserRole.EMPLOYEE,
    department: Department | None = None,
    *,
    active: bool = True,
    leave_approver: User | None = None,
    claim_approver: User | None = None,
) -> User:
    first, last = name.lower().split()
    n = session.query(User).count() + 1
    row = User(
        google_subject=f"mock-google-sub-{n:03d}",
        email=f"{first}.{last}@example.com",
        display_name=name,
        role=role,
        is_active=active,
        department_id=department.id if department else None,
        leave_approver_user_id=leave_approver.id if leave_approver else None,
        claim_approver_user_id=claim_approver.id if claim_approver else None,
    )
    session.add(row)
    session.flush()
    return row


def entitle(
    session: Session, user: User, year: int, leave_type: LeaveType, days: str
) -> LeaveEntitlement:
    row = LeaveEntitlement(
        user_id=user.id, year=year, leave_type=leave_type, entitled_days=Decimal(days)
    )
    session.add(row)
    session.flush()
    return row


def add_leave(
    session: Session,
    user: User,
    start: str,
    end: str | None = None,
    *,
    status: RequestStatus = S.APPROVED,
    leave_type: LeaveType = LeaveType.ANNUAL,
    days: str = "1",
    approver: User | None = None,
) -> LeaveRequest:
    row = LeaveRequest(
        employee_id=user.id,
        leave_type=leave_type,
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end or start),
        calendar_days=Decimal(days),
        working_days=Decimal(days),
        status=status,
        approver_user_id=approver.id if approver else None,
        submitted_at=utcnow() if status != S.DRAFT else None,
        reviewed_by_user_id=(approver or user).id if status in DECIDED else None,
        reviewed_at=utcnow() if status in DECIDED else None,
    )
    session.add(row)
    session.flush()
    return row


def add_claim(
    session: Session,
    user: User,
    amount: str,
    receipt: str,
    *,
    status: RequestStatus = S.APPROVED,
    approver: User | None = None,
) -> ClaimRequest:
    row = ClaimRequest(
        employee_id=user.id,
        claim_type=ClaimType.MEAL,
        amount=Decimal(amount),
        receipt_date=date.fromisoformat(receipt),
        status=status,
        approver_user_id=approver.id if approver else None,
        submitted_at=utcnow() if status != S.DRAFT else None,
        reviewed_by_user_id=(approver or user).id if status in DECIDED else None,
        reviewed_at=utcnow() if status in DECIDED else None,
    )
    session.add(row)
    session.flush()
    return row
