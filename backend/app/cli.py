"""Command line tools: ``uv run python -m app.cli <command>``.

Commands: ``init-db``, ``seed [--reset --yes]``,
``import-holidays [--year YYYY ...] [--file PATH | --url URL]``.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from app.config import get_settings
from app.db.session import Database, drop_all
from app.domain.enums import HolidaySource
from app.seed import seed_demo_data
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
    return parser


def cmd_init_db(database: Database) -> int:
    database.init_db()
    print("Tables are up to date.")
    return 0


def cmd_seed(database: Database, *, reset: bool, yes: bool) -> int:
    if reset and not yes:
        print("Refusing to reset: --reset drops every table. Re-run with --reset --yes.")
        return 2
    if reset:
        drop_all(database.engine)
    database.init_db()
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
    database.init_db()
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
        return cmd_import_holidays(database, years=args.year, file=args.file, url=args.url)
    finally:
        database.dispose()


if __name__ == "__main__":
    sys.exit(main())
