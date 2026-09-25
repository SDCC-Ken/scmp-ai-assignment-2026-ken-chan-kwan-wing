"""Organisation CLI: show-org, set-entitlement, set-claim-limit, set-approvers and their errors."""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app import cli
from app.db.models import Department, LeaveEntitlement, User
from app.db.session import Database
from app.domain.enums import LeaveType
from tests.test_migrate import make_old_database

AMY = "amy.lau@example.com"
BEN = "ben.chow@example.com"
CATHY = "cathy.ng@example.com"
DANIEL = "daniel.wong@example.com"
HELEN = "helen.yeung@example.com"
EVA = "eva.cheung@example.com"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(f"sqlite:///{tmp_path / 'org.db'}")
    assert run(["seed"], database) == 0
    yield database
    database.dispose()


def run(argv: list[str], database: Database) -> int:
    database.__dict__.pop("engine", None)  # main() disposes the engine
    database.__dict__.pop("session_factory", None)
    return cli.main(argv, database=database)


def user(database: Database, email: str) -> User:
    with database.session_factory() as s:
        row = s.scalars(select(User).where(User.email == email)).one()
        s.expunge(row)
        return row


def entitlement(database: Database, email: str, year: int, kind: LeaveType) -> Decimal | None:
    with database.session_factory() as s:
        return s.scalar(
            select(LeaveEntitlement.entitled_days)
            .join(User, User.id == LeaveEntitlement.user_id)
            .where(User.email == email, LeaveEntitlement.year == year)
            .where(LeaveEntitlement.leave_type == kind)
        )


# ---- show-org --------------------------------------------------------------------------------


def test_show_org_prints_departments_users_and_entitlements(
    db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert run(["show-org"], db) == 0
    out = capsys.readouterr().out
    assert "Departments" in out and "60,000.00" in out and "30,000.00" in out
    assert "Amy Lau" in out and "HR Business Partner (IT)" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("Amy Lau") and "@" in ln)
    assert "IT" in line and "Cathy Ng" in line and "Eva Cheung" in line
    helen = next(ln for ln in out.splitlines() if ln.startswith("Helen Yeung") and "@" in ln)
    assert helen.count("none") == 2  # no approvers configured
    assert "Leave entitlements 2026" in out and "Leave entitlements 2027" in out
    ben = [ln for ln in out.splitlines() if ln.startswith("Ben Chow") and "@" not in ln]
    assert ben and all("18" in ln for ln in ben)  # Ben has 18 annual days


def test_show_org_on_an_empty_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = Database(f"sqlite:///{tmp_path / 'empty.db'}")
    assert run(["show-org"], empty) == 0
    assert "Leave entitlements: none" in capsys.readouterr().out
    empty.dispose()


# ---- set-entitlement -------------------------------------------------------------------------


def test_set_entitlement_updates_an_existing_row(
    db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    args = ["set-entitlement", "--email", AMY, "--year", "2026", "--type", "annual", "--days"]
    assert run([*args, "20"], db) == 0
    assert "20.0 days" in capsys.readouterr().out
    assert entitlement(db, AMY, 2026, LeaveType.ANNUAL) == Decimal("20.0")
    assert entitlement(db, AMY, 2027, LeaveType.ANNUAL) == Decimal("15.0")  # other year untouched
    assert entitlement(db, AMY, 2026, LeaveType.SICK) == Decimal("10.0")  # other type untouched


def test_set_entitlement_creates_a_row_and_accepts_half_days_and_case(db: Database) -> None:
    assert entitlement(db, HELEN, 2026, LeaveType.SICK) is None
    args = ["set-entitlement", "--email", HELEN.upper(), "--year", "2026", "--type", "sick"]
    assert run([*args, "--days", "7.5"], db) == 0
    assert entitlement(db, HELEN, 2026, LeaveType.SICK) == Decimal("7.5")
    assert run([*args, "--days", "0"], db) == 0  # zero is allowed
    assert entitlement(db, HELEN, 2026, LeaveType.SICK) == Decimal("0.0")


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (
            ["--email", "nobody@example.com", "--year", "2026", "--type", "annual", "--days", "5"],
            "No user",
        ),
        (["--email", AMY, "--year", "2026", "--type", "annual", "--days", "-1"], "zero or more"),
        (["--email", AMY, "--year", "2026", "--type", "annual", "--days", "abc"], "not a number"),
        (["--email", AMY, "--year", "2026", "--type", "annual", "--days", "2.3"], "0.5 steps"),
        (["--email", AMY, "--year", "2026", "--type", "annual", "--days", "NaN"], "zero or more"),
        (["--email", AMY, "--year", "1999", "--type", "annual", "--days", "5"], "between 2000"),
    ],
)
def test_set_entitlement_errors_change_nothing(
    db: Database, capsys: pytest.CaptureFixture[str], extra: list[str], message: str
) -> None:
    capsys.readouterr()
    assert run(["set-entitlement", *extra], db) == 1
    assert message in capsys.readouterr().err
    assert entitlement(db, AMY, 2026, LeaveType.ANNUAL) == Decimal("15.0")


def test_set_entitlement_only_annual_or_sick(db: Database) -> None:
    args = ["set-entitlement", "--email", AMY, "--year", "2026", "--days", "5"]
    with pytest.raises(SystemExit):  # argparse rejects it before anything runs
        run([*args, "--type", "personal"], db)
    with pytest.raises(SystemExit):
        run(args, db)  # --type is required


# ---- set-claim-limit -------------------------------------------------------------------------


def limit(database: Database, name: str) -> Decimal:
    with database.session_factory() as s:
        return s.scalars(select(Department).where(Department.name == name)).one().claim_limit_amount


def test_set_claim_limit(db: Database, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert run(["set-claim-limit", "--department", "hr", "--amount", "45,000.50"], db) == 0
    assert "HKD 45,000.50" in capsys.readouterr().out
    assert limit(db, "HR") == Decimal("45000.50")
    assert limit(db, "IT") == Decimal("60000.00")


@pytest.mark.parametrize(
    ("department", "amount", "message"),
    [
        ("Legal", "100", "No department named 'Legal' (known: Finance, HR, IT)"),
        ("HR", "-5", "zero or more"),
        ("HR", "12.345", "at most 2 decimal places"),
        ("HR", "lots", "not an amount"),
        ("HR", "1" * 13, "too large"),
    ],
)
def test_set_claim_limit_errors_change_nothing(
    db: Database,
    capsys: pytest.CaptureFixture[str],
    department: str,
    amount: str,
    message: str,
) -> None:
    capsys.readouterr()
    assert run(["set-claim-limit", "--department", department, "--amount", amount], db) == 1
    assert message in capsys.readouterr().err
    assert limit(db, "HR") == Decimal("30000.00")


# ---- set-approvers ---------------------------------------------------------------------------


def approvers(database: Database, email: str) -> tuple[str | None, str | None]:
    with database.session_factory() as s:
        row = s.scalars(select(User).where(User.email == email)).one()
        find = lambda uid: s.get(User, uid).email if uid else None  # noqa: E731
        return find(row.leave_approver_user_id), find(row.claim_approver_user_id)


def test_set_approvers_changes_one_or_both(
    db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert run(["set-approvers", "--email", AMY, "--leave-approver", HELEN], db) == 0
    assert approvers(db, AMY) == (HELEN, EVA)  # the claim approver is untouched
    assert "leave approver = Helen Yeung, claim approver = Eva Cheung" in capsys.readouterr().out
    both = ["--leave-approver", CATHY.upper(), "--claim-approver", EVA]
    assert run(["set-approvers", "--email", AMY, *both], db) == 0
    assert approvers(db, AMY) == (CATHY, EVA)


def test_set_approvers_none_removes_an_approver(db: Database) -> None:
    assert run(["set-approvers", "--email", DANIEL, "--claim-approver", "None"], db) == 0
    assert approvers(db, DANIEL) == (HELEN, None)
    assert user(db, DANIEL).can_request is True  # one approver is enough
    assert run(["set-approvers", "--email", DANIEL, "--leave-approver", "none"], db) == 0
    assert user(db, DANIEL).can_request is False  # now Daniel has no chat


def test_giving_helen_and_eva_approvers_later_is_a_data_change(db: Database) -> None:
    both = ["--leave-approver", CATHY, "--claim-approver", EVA]
    assert run(["set-approvers", "--email", HELEN, *both], db) == 0
    assert user(db, HELEN).can_request is True


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--email", "nobody@example.com", "--leave-approver", CATHY], "No user"),
        (["--email", AMY, "--leave-approver", "nobody@example.com"], "No user"),
        (["--email", AMY], "Give --leave-approver and/or --claim-approver"),
        (["--email", CATHY, "--leave-approver", CATHY], "own leave approver"),
        (["--email", EVA, "--claim-approver", EVA], "own claim approver"),
        (["--email", AMY, "--leave-approver", EVA], "must be hr_approver"),
        (["--email", AMY, "--claim-approver", CATHY], "must be finance_approver"),
        (["--email", AMY, "--leave-approver", BEN], "must be hr_approver"),
    ],
)
def test_set_approvers_validation_errors_change_nothing(
    db: Database, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    capsys.readouterr()
    assert run(["set-approvers", *args], db) == 1
    assert message in capsys.readouterr().err
    assert approvers(db, AMY) == (CATHY, EVA)


def test_an_invalid_second_value_changes_neither(db: Database) -> None:
    args = ["--email", AMY, "--leave-approver", HELEN, "--claim-approver", CATHY]
    assert run(["set-approvers", *args], db) == 1  # the claim approver has the wrong role
    assert approvers(db, AMY) == (CATHY, EVA)  # so the valid leave change was not applied either


def test_an_inactive_approver_is_refused(db: Database, capsys: pytest.CaptureFixture[str]) -> None:
    with db.session_factory() as s:
        s.scalars(select(User).where(User.email == HELEN)).one().is_active = False
        s.commit()
    capsys.readouterr()
    assert run(["set-approvers", "--email", AMY, "--leave-approver", HELEN], db) == 1
    assert "inactive" in capsys.readouterr().err
    assert approvers(db, AMY) == (CATHY, EVA)


# ---- an old database -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["show-org"],
        ["set-claim-limit", "--department", "IT", "--amount", "1"],
        ["init-db"],
        ["seed"],
    ],
)
def test_commands_on_a_pre_phase_3_database_print_the_recreate_instruction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    old = Database(make_old_database(tmp_path / "old.db"))
    assert run(argv, old) == 1
    err = capsys.readouterr().err
    assert "created before Phase 3" in err and "seed --reset --yes" in err
    old.dispose()
