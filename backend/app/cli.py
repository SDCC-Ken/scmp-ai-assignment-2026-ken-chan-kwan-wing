"""Command line tools: ``uv run python -m app.cli <command>``.

Commands: ``init-db``, ``seed [--reset --yes]``,
``import-holidays [--year YYYY ...] [--file PATH | --url URL]``, and the Phase 3 organisation
tools (no admin UI in the PoC): ``show-org``, ``set-entitlement``, ``set-claim-limit``,
``set-approvers``. In Docker: ``docker compose exec api python -m app.cli <command>``.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.db.session import Database, drop_all
from app.domain.enums import HolidaySource
from app.seed import seed_demo_data
from app.services import org_admin
from app.services.holidays import (
    HOLIDAYS_1823_URL,
    HolidayFetchError,
    fetch_1823_ics,
    latest_stamp,
    parse_ics,
    upsert_holidays,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create missing tables")

    seed = sub.add_parser("seed", help="load fictional demo data (no-op if users exist)")
    seed.add_argument("--reset", action="store_true", help="DROP ALL TABLES first")
    seed.add_argument("--yes", action="store_true", help="confirm --reset")

    imp = sub.add_parser("import-holidays", help="import public holidays from an iCal feed")
    imp.add_argument("--year", type=int, nargs="+", metavar="YYYY", help="only these years")
    source = imp.add_mutually_exclusive_group()
    source.add_argument("--file", type=Path, help="read a local .ics file instead of fetching")
    source.add_argument("--url", default=HOLIDAYS_1823_URL, help="feed URL (default: 1823.gov.hk)")

    sub.add_parser("show-org", help="print departments, users, approvers and entitlements")

    ent = sub.add_parser("set-entitlement", help="set a user's annual/sick days for a year")
    ent.add_argument("--email", required=True)
    ent.add_argument("--year", type=int, required=True)
    ent.add_argument("--type", required=True, choices=["annual", "sick"], dest="leave_type")
    ent.add_argument("--days", required=True, help="days, in 0.5 steps (for example 12 or 12.5)")

    limit = sub.add_parser("set-claim-limit", help="set a department's yearly claim limit (HKD)")
    limit.add_argument("--department", required=True)
    limit.add_argument("--amount", required=True, help="HKD, at most 2 decimals")

    appr = sub.add_parser("set-approvers", help="set who approves a user's leave and/or claims")
    appr.add_argument("--email", required=True)
    appr.add_argument("--leave-approver", metavar="EMAIL|none", help="an hr_approver, or none")
    appr.add_argument("--claim-approver", metavar="EMAIL|none", help="a finance_approver, or none")
    return parser


def _check_schema(database: Database) -> int | None:
    """Create/verify the tables; a pre-Phase-3 file gets the recreate instruction (exit 1)."""
    problem = database.init_db()
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return 1
    return None


def cmd_init_db(database: Database) -> int:
    if (failed := _check_schema(database)) is not None:
        return failed
    print("Tables are up to date.")
    return 0


def cmd_seed(database: Database, *, reset: bool, yes: bool) -> int:
    if reset and not yes:
        print("Refusing to reset: --reset drops every table. Re-run with --reset --yes.")
        return 2
    if reset:
        drop_all(database.engine)
    if (failed := _check_schema(database)) is not None:
        return failed
    with database.session_factory() as session:
        result = seed_demo_data(session)
        if not result.seeded:
            print("Users already exist; nothing seeded (use --reset --yes to start over).")
            return 0
        counts = result.counts
    print("Seeded fictional demo data:")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


def _org_command(database: Database, action: Callable[[Session], str]) -> int:
    """Run one organisation change/report in a session; print the result or the error."""
    if (failed := _check_schema(database)) is not None:
        return failed
    with database.session_factory() as session:
        try:
            message = action(session)
            session.commit()
        except org_admin.OrgAdminError as exc:
            session.rollback()
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    print(message)
    return 0


def cmd_show_org(database: Database) -> int:
    return _org_command(database, org_admin.show_org)


def cmd_set_entitlement(
    database: Database, *, email: str, year: int, leave_type: str, days: str
) -> int:
    def action(session: Session) -> str:
        user, row = org_admin.set_entitlement(
            session,
            email=email,
            year=year,
            leave_type=leave_type,
            days=org_admin.parse_days(days),
        )
        return (
            f"{user.display_name}: {row.leave_type.value} leave entitlement {row.year} "
            f"is now {row.entitled_days} days."
        )

    return _org_command(database, action)


def cmd_set_claim_limit(database: Database, *, department: str, amount: str) -> int:
    def action(session: Session) -> str:
        row = org_admin.set_claim_limit(
            session, department=department, amount=org_admin.parse_amount(amount)
        )
        return f"{row.name}: yearly claim limit is now HKD {row.claim_limit_amount:,.2f}."

    return _org_command(database, action)


def cmd_set_approvers(
    database: Database, *, email: str, leave_approver: str | None, claim_approver: str | None
) -> int:
    def action(session: Session) -> str:
        user = org_admin.set_approvers(
            session, email=email, leave_approver=leave_approver, claim_approver=claim_approver
        )
        names = {u.id: u.display_name for u in session.scalars(select(User))}
        return (
            f"{user.display_name}: leave approver = "
            f"{names.get(user.leave_approver_user_id, 'none')}, claim approver = "
            f"{names.get(user.claim_approver_user_id, 'none')}."
        )

    return _org_command(database, action)


def cmd_import_holidays(
    database: Database, *, years: Sequence[int] | None, file: Path | None, url: str
) -> int:
    try:
        text = file.read_text(encoding="utf-8") if file else fetch_1823_ics(url=url)
    except (OSError, HolidayFetchError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    events = parse_ics(text)
    if not events:
        print("Error: no holiday events found in the feed.", file=sys.stderr)
        return 1
    available = sorted({e.holiday_date.year for e in events})
    if years:
        missing = sorted(set(years) - set(available))
        if missing:
            print(
                f"Error: year(s) {', '.join(map(str, missing))} not in the feed "
                f"(feed covers {available[0]}-{available[-1]}). 1823 publishes about 3 years "
                "ahead; try again once the official calendar is released.",
                file=sys.stderr,
            )
            return 1
        selected = [e for e in events if e.holiday_date.year in set(years)]
    else:
        selected = events
    if (failed := _check_schema(database)) is not None:
        return failed
    with database.session_factory() as session:
        result = upsert_holidays(session, selected, HolidaySource.ICS_1823, latest_stamp(events))
        session.commit()
    print(
        f"Holidays: {result.inserted} inserted, {result.updated} updated, "
        f"{result.unchanged} unchanged (years {sorted({e.holiday_date.year for e in selected})})."
    )
    return 0


def main(argv: Sequence[str] | None = None, *, database: Database | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = database or Database(get_settings().database_url)
    try:
        if args.command == "init-db":
            return cmd_init_db(database)
        if args.command == "seed":
            return cmd_seed(database, reset=args.reset, yes=args.yes)
        if args.command == "show-org":
            return cmd_show_org(database)
        if args.command == "set-entitlement":
            return cmd_set_entitlement(
                database,
                email=args.email,
                year=args.year,
                leave_type=args.leave_type,
                days=args.days,
            )
        if args.command == "set-claim-limit":
            return cmd_set_claim_limit(database, department=args.department, amount=args.amount)
        if args.command == "set-approvers":
            return cmd_set_approvers(
                database,
                email=args.email,
                leave_approver=args.leave_approver,
                claim_approver=args.claim_approver,
            )
        return cmd_import_holidays(database, years=args.year, file=args.file, url=args.url)
    finally:
        database.dispose()


if __name__ == "__main__":
    sys.exit(main())
