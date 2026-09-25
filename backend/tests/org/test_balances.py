"""Leave balances, department claim budgets and team overlap (counting rules in the docs)."""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Department, User
from app.domain.enums import LeaveType, RequestStatus, UserRole
from app.services.balances import (
    department_budget,
    leave_balance,
    leave_balance_after,
    leave_balances_for_user,
    team_overlap,
)
from tests.org.helpers import (
    add_claim,
    add_department,
    add_leave,
    add_user,
    entitle,
)

S = RequestStatus
PEND = S.PENDING_APPROVAL
ANNUAL, SICK, PERSONAL, UNPAID = (
    LeaveType.ANNUAL,
    LeaveType.SICK,
    LeaveType.PERSONAL,
    LeaveType.UNPAID,
)
D = Decimal


@pytest.fixture
def amy(session: Session) -> User:
    user = add_user(session, "Amy Lau")
    entitle(session, user, 2026, ANNUAL, "15")
    entitle(session, user, 2026, SICK, "10")
    return user


# ---- leave_balance ---------------------------------------------------------------------------


def test_no_leave_no_deduction(session: Session, amy: User) -> None:
    balance = leave_balance(session, amy.id, 2026, ANNUAL)
    assert (balance.entitled_days, balance.approved_days) == (D("15"), D("0"))
    assert (balance.pending_days, balance.remaining_days) == (D("0"), D("15"))
    assert (balance.user_id, balance.year, balance.leave_type) == (amy.id, 2026, ANNUAL)


def test_only_approved_leave_is_deducted_and_pending_is_shown_separately(
    session: Session, amy: User
) -> None:
    add_leave(session, amy, "2026-03-02", "2026-03-04", days="3", status=S.APPROVED)
    add_leave(session, amy, "2026-05-04", "2026-05-05", days="2", status=PEND)
    for status in (S.REJECTED, S.CANCELLED, S.DRAFT, S.SUBMISSION_FAILED):
        add_leave(session, amy, "2026-06-01", "2026-06-05", days="5", status=status)
    balance = leave_balance(session, amy.id, 2026, ANNUAL)
    assert balance.approved_days == D("3")
    assert balance.pending_days == D("2")
    assert balance.remaining_days == D("12")  # entitled - approved; pending is NOT deducted


def test_half_days_are_exact(session: Session, amy: User) -> None:
    add_leave(session, amy, "2026-03-02", days="0.5", status=S.APPROVED)
    add_leave(session, amy, "2026-03-09", "2026-03-11", days="2.5", status=S.APPROVED)
    add_leave(session, amy, "2026-04-06", days="0.5", status=PEND)
    balance = leave_balance(session, amy.id, 2026, ANNUAL)
    assert (balance.approved_days, balance.pending_days) == (D("3.0"), D("0.5"))
    assert balance.remaining_days == D("12.0")
    assert isinstance(balance.remaining_days, Decimal)


def test_sick_and_annual_are_counted_separately(session: Session, amy: User) -> None:
    add_leave(session, amy, "2026-03-02", days="2", status=S.APPROVED, leave_type=SICK)
    add_leave(session, amy, "2026-03-09", days="4", status=S.APPROVED, leave_type=ANNUAL)
    assert leave_balance(session, amy.id, 2026, SICK).remaining_days == D("8")
    assert leave_balance(session, amy.id, 2026, ANNUAL).remaining_days == D("11")


def test_leave_counts_in_the_year_of_its_start_date(session: Session, amy: User) -> None:
    entitle(session, amy, 2027, ANNUAL, "15")
    # starts on 2026-12-30 and runs into 2027: all of it counts in 2026 (no splitting)
    add_leave(session, amy, "2026-12-30", "2027-01-05", days="4", status=S.APPROVED)
    add_leave(session, amy, "2027-01-04", days="1", status=S.APPROVED)
    assert leave_balance(session, amy.id, 2026, ANNUAL).approved_days == D("4")
    assert leave_balance(session, amy.id, 2027, ANNUAL).approved_days == D("1")
    # first and last day of the year are inside the year
    add_leave(session, amy, "2026-01-01", days="1", status=S.APPROVED)
    add_leave(session, amy, "2026-12-31", days="1", status=S.APPROVED)
    assert leave_balance(session, amy.id, 2026, ANNUAL).approved_days == D("6")


def test_other_users_are_not_counted(session: Session, amy: User) -> None:
    ben = add_user(session, "Ben Chow")
    add_leave(session, ben, "2026-03-02", days="5", status=S.APPROVED)
    assert leave_balance(session, amy.id, 2026, ANNUAL).approved_days == D("0")


def test_personal_and_unpaid_have_no_balance(session: Session, amy: User) -> None:
    add_leave(session, amy, "2026-03-02", days="1", leave_type=PERSONAL)
    assert leave_balance(session, amy.id, 2026, PERSONAL) is None
    assert leave_balance(session, amy.id, 2026, UNPAID) is None
    assert leave_balance_after(session, amy.id, 2026, PERSONAL, D("1")) is None
    assert leave_balance(session, amy.id, 2026, "personal") is None  # plain strings work


def test_no_entitlement_means_no_balance(session: Session, amy: User) -> None:
    assert leave_balance(session, amy.id, 2028, ANNUAL) is None  # no row for that year
    ben = add_user(session, "Ben Chow")
    assert leave_balance(session, ben.id, 2026, SICK) is None
    assert leave_balance_after(session, ben.id, 2026, ANNUAL, D("1")) is None
    assert leave_balances_for_user(session, ben.id, 2026) == []


def test_the_remaining_days_can_go_negative(session: Session, amy: User) -> None:
    add_leave(session, amy, "2026-03-02", days="16", status=S.APPROVED)
    assert leave_balance(session, amy.id, 2026, ANNUAL).remaining_days == D("-1")


def test_balances_for_user_lists_annual_then_sick(session: Session, amy: User) -> None:
    lines = leave_balances_for_user(session, amy.id, 2026)
    assert [(b.leave_type, b.entitled_days) for b in lines] == [(ANNUAL, D("15")), (SICK, D("10"))]
    entitle(session, add_user(session, "Ben Chow"), 2026, SICK, "12")
    only_sick = leave_balances_for_user(
        session, session.query(User).filter_by(email="ben.chow@example.com").one().id, 2026
    )
    assert [b.leave_type for b in only_sick] == [SICK]


def test_balances_are_frozen_dataclasses(session: Session, amy: User) -> None:
    balance = leave_balance(session, amy.id, 2026, ANNUAL)
    with pytest.raises(AttributeError):
        balance.remaining_days = D("99")  # type: ignore[misc]


# ---- leave_balance_after ---------------------------------------------------------------------


def test_balance_after_a_request(session: Session, amy: User) -> None:
    add_leave(session, amy, "2026-03-02", "2026-03-04", days="3", status=S.APPROVED)
    add_leave(session, amy, "2026-04-06", days="1", status=PEND)
    after = leave_balance_after(session, amy.id, 2026, ANNUAL, D("2.5"))
    assert after.entitled_days == D("15") and after.approved_days == D("3")
    assert after.requested_days == D("2.5")
    assert after.remaining_after_days == D("9.5")
    assert after.pending_other_days == D("1")  # shown, not deducted
    assert after.over_limit is False


def test_over_limit_flag_boundaries(session: Session, amy: User) -> None:
    add_leave(session, amy, "2026-03-02", days="10", status=S.APPROVED)  # 5 left
    exactly = leave_balance_after(session, amy.id, 2026, ANNUAL, D("5"))
    assert exactly.remaining_after_days == D("0") and exactly.over_limit is False
    over = leave_balance_after(session, amy.id, 2026, ANNUAL, D("5.5"))
    assert over.remaining_after_days == D("-0.5") and over.over_limit is True


def test_exclude_request_id_leaves_the_request_itself_out(session: Session, amy: User) -> None:
    pending = add_leave(session, amy, "2026-04-06", "2026-04-08", days="3", status=PEND)
    other = add_leave(session, amy, "2026-05-04", days="1", status=PEND)
    add_leave(session, amy, "2026-03-02", days="2", status=S.APPROVED)
    with_self = leave_balance_after(session, amy.id, 2026, ANNUAL, pending.working_days)
    assert with_self.pending_other_days == D("4")  # both pending requests
    without = leave_balance_after(
        session, amy.id, 2026, ANNUAL, pending.working_days, exclude_request_id=pending.id
    )
    assert without.pending_other_days == D("1")  # only the other one
    assert without.remaining_after_days == D("10")  # 15 - 2 approved - 3 requested
    assert other.id != pending.id


def test_exclude_request_id_also_skips_an_approved_request_being_reviewed(
    session: Session, amy: User
) -> None:
    approved = add_leave(session, amy, "2026-03-02", days="3", status=S.APPROVED)
    after = leave_balance_after(
        session, amy.id, 2026, ANNUAL, D("3"), exclude_request_id=approved.id
    )
    assert after.approved_days == D("0") and after.remaining_after_days == D("12")


# ---- department_budget -----------------------------------------------------------------------


@pytest.fixture
def it(session: Session) -> Department:
    return add_department(session, "IT", "1000.00")


def test_department_budget_counts_approved_claims_by_receipt_year(
    session: Session, it: Department
) -> None:
    amy = add_user(session, "Amy Lau", department=it)
    ben = add_user(session, "Ben Chow", department=it)
    add_claim(session, amy, "100.50", "2026-01-15", status=S.APPROVED)
    add_claim(session, ben, "200.25", "2026-12-31", status=S.APPROVED)
    add_claim(session, ben, "999.00", "2025-12-31", status=S.APPROVED)  # other year
    add_claim(session, ben, "888.00", "2027-01-01", status=S.APPROVED)  # other year
    add_claim(session, amy, "50.00", "2026-06-01", status=PEND)
    for status in (S.REJECTED, S.CANCELLED, S.DRAFT, S.SUBMISSION_FAILED):
        add_claim(session, amy, "777.00", "2026-06-01", status=status)
    budget = department_budget(session, it.id, 2026)
    assert budget.department == "IT" and budget.year == 2026 and budget.currency == "HKD"
    assert budget.limit_amount == D("1000.00")
    assert budget.approved_amount == D("300.75")
    assert budget.pending_other_amount == D("50.00")
    assert budget.remaining_amount == D("699.25")
    assert isinstance(budget.approved_amount, Decimal)


def test_another_department_is_not_counted(session: Session, it: Department) -> None:
    hr = add_department(session, "HR", "500.00")
    amy = add_user(session, "Amy Lau", department=it)
    cathy = add_user(session, "Cathy Ng", UserRole.HR_APPROVER, hr)
    nobody = add_user(session, "Nina Poon")  # no department at all
    add_claim(session, amy, "100.00", "2026-02-01")
    add_claim(session, cathy, "400.00", "2026-02-01")
    add_claim(session, nobody, "300.00", "2026-02-01")
    assert department_budget(session, it.id, 2026).approved_amount == D("100.00")
    assert department_budget(session, hr.id, 2026).approved_amount == D("400.00")


def test_budget_after_and_the_over_limit_boundary(session: Session, it: Department) -> None:
    amy = add_user(session, "Amy Lau", department=it)
    add_claim(session, amy, "900.00", "2026-02-01")
    budget = department_budget(session, it.id, 2026)
    exactly = budget.budget_after(D("100.00"))
    assert exactly.remaining_after_amount == D("0.00") and exactly.over_limit is False
    over = budget.budget_after(D("100.01"))
    assert over.remaining_after_amount == D("-0.01") and over.over_limit is True
    assert (over.department, over.year, over.limit_amount) == ("IT", 2026, D("1000.00"))
    assert (over.approved_amount, over.requested_amount) == (D("900.00"), D("100.01"))
    assert over.currency == "HKD"


def test_budget_exclude_request_id(session: Session, it: Department) -> None:
    amy = add_user(session, "Amy Lau", department=it)
    mine = add_claim(session, amy, "300.00", "2026-02-01", status=PEND)
    add_claim(session, amy, "100.00", "2026-02-02", status=PEND)
    add_claim(session, amy, "50.00", "2026-02-03", status=S.APPROVED)
    assert department_budget(session, it.id, 2026).pending_other_amount == D("400.00")
    budget = department_budget(session, it.id, 2026, exclude_request_id=mine.id)
    assert budget.pending_other_amount == D("100.00")
    assert budget.approved_amount == D("50.00")
    approved_id = session.query(type(mine)).filter_by(status=S.APPROVED).one().id
    assert department_budget(session, it.id, 2026, approved_id).approved_amount == D("0.00")


def test_unknown_department_has_no_budget(session: Session) -> None:
    assert department_budget(session, 12345, 2026) is None


def test_an_empty_department_has_a_full_budget(session: Session, it: Department) -> None:
    budget = department_budget(session, it.id, 2026)
    assert (budget.approved_amount, budget.pending_other_amount) == (D("0.00"), D("0.00"))
    assert budget.budget_after(D("0.00")).remaining_after_amount == D("1000.00")


# ---- team_overlap ----------------------------------------------------------------------------


@pytest.fixture
def team(session: Session, it: Department) -> dict[str, User]:
    hr = add_department(session, "HR")
    return {
        "amy": add_user(session, "Amy Lau", department=it),
        "ben": add_user(session, "Ben Chow", department=it),
        "carl": add_user(session, "Carl Sze", department=it),
        "cathy": add_user(session, "Cathy Ng", UserRole.HR_APPROVER, hr),
    }


def test_approved_and_pending_colleague_leave_overlaps(
    session: Session, team: dict[str, User]
) -> None:
    mine = add_leave(session, team["amy"], "2026-10-05", "2026-10-09", days="5", status=PEND)
    add_leave(session, team["ben"], "2026-10-06", days="1", status=S.APPROVED)
    add_leave(
        session,
        team["carl"],
        "2026-10-08",
        "2026-10-09",
        days="2",
        status=PEND,
        leave_type=SICK,
    )
    result = team_overlap(session, mine)
    assert [(o.employee, o.status, o.leave_type, o.working_days) for o in result] == [
        ("Ben Chow", S.APPROVED, ANNUAL, D("1")),
        ("Carl Sze", PEND, SICK, D("2")),
    ]
    assert result[0].start_date.isoformat() == "2026-10-06" == result[0].end_date.isoformat()
    assert result[0].employee_id == team["ben"].id


def test_cancelled_rejected_draft_and_failed_do_not_count(
    session: Session, team: dict[str, User]
) -> None:
    mine = add_leave(session, team["amy"], "2026-10-05", "2026-10-09", days="5", status=PEND)
    for status in (S.CANCELLED, S.REJECTED, S.DRAFT, S.SUBMISSION_FAILED):
        add_leave(session, team["ben"], "2026-10-06", days="1", status=status)
    assert team_overlap(session, mine) == []


def test_other_department_and_the_requester_are_excluded(
    session: Session, team: dict[str, User]
) -> None:
    mine = add_leave(session, team["amy"], "2026-10-05", days="1", status=PEND)
    add_leave(session, team["cathy"], "2026-10-05", days="1", status=S.APPROVED)  # HR, not IT
    add_leave(session, team["amy"], "2026-10-05", days="1", status=S.APPROVED)  # her own other one
    assert team_overlap(session, mine) == []


def test_partial_overlaps_and_the_edges(session: Session, team: dict[str, User]) -> None:
    mine = add_leave(session, team["amy"], "2026-10-05", "2026-10-09", days="5", status=PEND)
    add_leave(
        session, team["ben"], "2026-10-01", "2026-10-05", days="3", status=S.APPROVED
    )  # ends on my first day
    add_leave(
        session, team["carl"], "2026-10-09", "2026-10-15", days="5", status=S.APPROVED
    )  # starts on my last day
    assert [o.employee for o in team_overlap(session, mine)] == ["Ben Chow", "Carl Sze"]
    # one day before / after: no overlap
    session.query(type(mine)).filter(type(mine).employee_id == team["ben"].id).delete()
    add_leave(session, team["ben"], "2026-10-01", "2026-10-04", days="2", status=S.APPROVED)
    add_leave(session, team["ben"], "2026-10-10", "2026-10-12", days="1", status=S.APPROVED)
    assert [o.employee for o in team_overlap(session, mine)] == ["Carl Sze"]


def test_a_colleague_leave_that_spans_the_whole_request_overlaps(
    session: Session, team: dict[str, User]
) -> None:
    mine = add_leave(session, team["amy"], "2026-10-07", days="1", status=PEND)
    add_leave(session, team["ben"], "2026-09-28", "2026-10-16", days="14", status=S.APPROVED)
    assert [o.employee for o in team_overlap(session, mine)] == ["Ben Chow"]


def test_inactive_colleagues_are_ignored_and_no_department_means_no_team(
    session: Session, team: dict[str, User]
) -> None:
    mine = add_leave(session, team["amy"], "2026-10-05", days="1", status=PEND)
    add_leave(session, team["ben"], "2026-10-05", days="1", status=S.APPROVED)
    team["ben"].is_active = False
    assert team_overlap(session, mine) == []
    loner = add_user(session, "Lena Tse")
    loner_leave = add_leave(session, loner, "2026-10-05", days="1", status=PEND)
    assert team_overlap(session, loner_leave) == []
