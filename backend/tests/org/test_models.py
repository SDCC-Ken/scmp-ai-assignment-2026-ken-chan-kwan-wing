"""Phase 3 tables and constraints (bare tables, no seed)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ClaimRequest, Department, LeaveEntitlement, LeaveRequest, User
from app.db.session import Database
from app.domain.enums import ClaimType, LeaveType, RequestStatus, UserRole
from tests.org.helpers import add_department, add_leave, add_user, entitle

S = RequestStatus


def test_a_rejected_request_without_a_note_is_now_valid(session: Session) -> None:
    """The Phase 3 change: the reviewer note is optional, also for a rejection."""
    amy = add_user(session, "Amy Lau")
    cathy = add_user(session, "Cathy Ng", UserRole.HR_APPROVER)
    leave = add_leave(session, amy, "2026-10-05", status=S.REJECTED, approver=cathy)
    claim = ClaimRequest(
        employee_id=amy.id,
        claim_type=ClaimType.MEAL,
        amount=Decimal("10.00"),
        receipt_date=date(2026, 9, 1),
        status=S.REJECTED,
        approver_user_id=cathy.id,
        reviewed_by_user_id=cathy.id,
        reviewed_at=leave.reviewed_at,
    )
    session.add(claim)
    session.commit()  # no IntegrityError
    assert leave.reviewer_note is None and claim.reviewer_note is None


def test_the_reject_needs_note_check_no_longer_exists(db: Database) -> None:
    with db.engine.connect() as conn:
        ddl = " ".join(
            conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE name IN ('leave_requests', 'claim_requests')"
                )
            ).scalars()
        )
    assert "reject_needs_note" not in ddl
    assert "review_needs_reviewer" in ddl  # a decision still needs reviewer and time


def test_a_decided_request_still_needs_reviewer_and_time(session: Session) -> None:
    amy = add_user(session, "Amy Lau")
    session.add(
        LeaveRequest(
            employee_id=amy.id,
            leave_type=LeaveType.ANNUAL,
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 5),
            calendar_days=Decimal("1"),
            working_days=Decimal("1"),
            status=S.APPROVED,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_foreign_keys_on_the_new_columns_are_enforced(session: Session) -> None:
    amy = add_user(session, "Amy Lau")
    session.commit()
    for column in ("department_id", "leave_approver_user_id", "claim_approver_user_id"):
        session.execute(text(f"UPDATE users SET {column} = NULL"))
        with pytest.raises(IntegrityError):
            session.execute(text(f"UPDATE users SET {column} = 999 WHERE id = {amy.id}"))
        session.rollback()
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO leave_entitlements (user_id, year, leave_type, entitled_days) "
                "VALUES (999, 2026, 'annual', 150)"
            )
        )
    session.rollback()
    with pytest.raises(IntegrityError):
        add_leave(session, amy, "2026-10-05", status=S.PENDING_APPROVAL).approver_user_id = 999
        session.flush()
    session.rollback()
    claim = ClaimRequest(
        employee_id=amy.id,
        claim_type=ClaimType.MEAL,
        amount=Decimal("1.00"),
        receipt_date=date(2026, 9, 1),
        approver_user_id=999,
    )
    session.add(claim)
    with pytest.raises(IntegrityError):
        session.commit()


def test_the_approver_columns_are_nullable_and_default_to_none(session: Session) -> None:
    amy = add_user(session, "Amy Lau")
    leave = add_leave(session, amy, "2026-10-05", status=S.DRAFT)
    assert amy.leave_approver_user_id is None and amy.claim_approver_user_id is None
    assert amy.department_id is None and amy.job_title is None and leave.approver_user_id is None


def test_department_name_is_unique_and_the_limit_not_negative(session: Session) -> None:
    add_department(session, "IT")
    session.add(Department(name="IT", claim_limit_amount=Decimal("1.00")))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(Department(name="HR", claim_limit_amount=Decimal("-1.00")))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(Department(name="Finance", claim_limit_amount=Decimal("0.00")))
    session.commit()  # zero is allowed


def test_the_department_limit_is_exact_money(session: Session) -> None:
    dept = add_department(session, "IT", "60000.10")
    session.commit()
    session.expire_all()
    assert session.get(Department, dept.id).claim_limit_amount == Decimal("60000.10")
    raw = session.execute(text("SELECT claim_limit_amount FROM departments")).scalar()
    assert raw == 6000010  # integer minor units, never a float


def test_entitlements_are_unique_per_user_year_and_type(session: Session) -> None:
    amy = add_user(session, "Amy Lau")
    session.commit()
    entitle(session, amy, 2026, LeaveType.ANNUAL, "15")
    entitle(session, amy, 2026, LeaveType.SICK, "10")  # another type: fine
    entitle(session, amy, 2027, LeaveType.ANNUAL, "15")  # another year: fine
    with pytest.raises(IntegrityError):
        entitle(session, amy, 2026, LeaveType.ANNUAL, "20")
    session.rollback()


def test_entitlements_only_for_annual_and_sick_and_not_negative(session: Session) -> None:
    amy = add_user(session, "Amy Lau")
    session.commit()
    for bad_type in (LeaveType.PERSONAL, LeaveType.UNPAID):
        with pytest.raises(IntegrityError):
            entitle(session, amy, 2026, bad_type, "5")
        session.rollback()
    with pytest.raises(IntegrityError):
        entitle(session, amy, 2026, LeaveType.ANNUAL, "-1")
    session.rollback()
    entitle(session, amy, 2026, LeaveType.ANNUAL, "0")  # zero is allowed


def test_entitled_days_keep_half_days_exactly(session: Session) -> None:
    amy = add_user(session, "Amy Lau")
    row = entitle(session, amy, 2026, LeaveType.ANNUAL, "12.5")
    session.commit()
    session.expire_all()
    assert session.get(LeaveEntitlement, row.id).entitled_days == Decimal("12.5")
    assert session.execute(text("SELECT entitled_days FROM leave_entitlements")).scalar() == 125


def test_user_shape_helpers(session: Session) -> None:
    hr = add_department(session, "HR")
    helen = add_user(session, "Helen Yeung", UserRole.HR_APPROVER, hr)
    eva = add_user(session, "Eva Cheung", UserRole.FINANCE_APPROVER)
    daniel = add_user(session, "Daniel Wong", UserRole.EMPLOYEE, hr, leave_approver=helen)
    assert (daniel.can_request, daniel.approves) == (True, None)
    assert (helen.can_request, helen.approves) == (False, "leave")
    assert (eva.can_request, eva.approves) == (False, "claim")
    claim_only = add_user(session, "Claire Ho", claim_approver=eva)
    assert claim_only.can_request is True  # at least ONE approver is enough


def test_new_indexes_exist(db: Database) -> None:
    inspector = inspect(db.engine)

    def columns(table: str) -> list[list[str]]:
        return [ix["column_names"] for ix in inspector.get_indexes(table)]

    assert ["approver_user_id", "status"] in columns("leave_requests")
    assert ["approver_user_id", "status"] in columns("claim_requests")
    assert ["department_id"] in columns("users")
    uniques = [u["column_names"] for u in inspector.get_unique_constraints("leave_entitlements")]
    assert ["user_id", "year", "leave_type"] in uniques
    assert ["name"] in [u["column_names"] for u in inspector.get_unique_constraints("departments")]


def test_user_department_relationship_loads(session: Session) -> None:
    it = add_department(session, "IT")
    amy = add_user(session, "Amy Lau", department=it)
    session.commit()
    session.expire_all()
    assert session.get(User, amy.id).department.name == "IT"
