from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PublicHoliday
from app.domain.enums import HolidaySource
from app.services.holidays import (
    HolidayFetchError,
    fetch_1823_ics,
    is_working_day,
    latest_stamp,
    load_holidays,
    parse_ics,
    upsert_holidays,
)

ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20260101\r\nDTEND;VALUE=DATE:20260102\r\n"
    "DTSTAMP:20260515T061504Z\r\nSUMMARY:The first day of January\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20260217\r\nDTEND;VALUE=DATE:20260218\r\n"
    "DTSTAMP:20250516T063710Z\r\nSUMMARY:Lunar New Year’s Day\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261001\r\nDTEND;VALUE=DATE:20261002\r\n"
    "DTSTAMP:20260515T061504Z\r\nSUMMARY:The National Day\\, folded \r\n and escaped\\; ok\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART:20261225T000000Z\r\nDTSTAMP:20260101T000000Z\r\n"
    "SUMMARY:Christmas Day\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20270201\r\nDTEND;VALUE=DATE:20270204\r\n"
    "SUMMARY:Multi-day break\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def test_parse_ics_handles_folding_escapes_quotes_and_forms() -> None:
    events = {e.holiday_date: e for e in parse_ics(ICS)}
    assert events[date(2026, 2, 17)].name == "Lunar New Year's Day"
    assert events[date(2026, 10, 1)].name == "The National Day, folded and escaped; ok"
    assert events[date(2026, 12, 25)].name == "Christmas Day"  # DTSTART as date-time
    assert events[date(2026, 1, 1)].dtstamp == datetime(2026, 5, 15, 6, 15, 4, tzinfo=UTC)
    # multi-day event expands to one row per day (exclusive DTEND)
    assert [d for d in events if d.year == 2027] == [
        date(2027, 2, 1),
        date(2027, 2, 2),
        date(2027, 2, 3),
    ]
    assert list(events) == sorted(events)


def test_latest_stamp() -> None:
    assert latest_stamp(parse_ics(ICS)) == datetime(2026, 5, 15, 6, 15, 4, tzinfo=UTC)
    assert latest_stamp([]) is None


def test_parse_accepts_lf_only_and_ignores_incomplete_events() -> None:
    text = (
        "BEGIN:VEVENT\nSUMMARY:No date\nEND:VEVENT\n"
        "BEGIN:VEVENT\nDTSTART:20260501\nSUMMARY:Labour\nEND:VEVENT\n"
    )
    assert [(e.holiday_date, e.name) for e in parse_ics(text)] == [(date(2026, 5, 1), "Labour")]


def test_bundled_snapshot_parses_and_has_17_per_year() -> None:
    path = Path(__file__).resolve().parents[1] / "app" / "data" / "hk_public_holidays_1823.ics"
    events = parse_ics(path.read_text(encoding="utf-8"))
    per_year = {y: sum(e.holiday_date.year == y for e in events) for y in (2026, 2027)}
    assert per_year == {2026: 17, 2027: 17}
    assert any("Lunar New Year's Day" == e.name for e in events)  # curly apostrophe normalised


def test_upsert_is_idempotent_and_updates_changes(session: Session) -> None:
    events = parse_ics(ICS)
    stamp = latest_stamp(events)
    first = upsert_holidays(session, events, HolidaySource.SEED_2026, stamp)
    session.commit()
    assert (first.inserted, first.updated, first.unchanged) == (7, 0, 0)
    again = upsert_holidays(session, events, HolidaySource.SEED_2026, stamp)
    session.commit()
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 7)
    assert len(session.scalars(select(PublicHoliday)).all()) == 7

    newer = upsert_holidays(
        session, events, HolidaySource.ICS_1823, datetime(2026, 9, 1, tzinfo=UTC)
    )
    session.commit()
    assert (newer.inserted, newer.updated) == (0, 7)
    assert {h.source for h in session.scalars(select(PublicHoliday))} == {HolidaySource.ICS_1823}


def test_upsert_collapses_duplicate_dates(session: Session) -> None:
    events = parse_ics(ICS) + parse_ics(ICS)
    result = upsert_holidays(session, events, HolidaySource.ICS_1823, None)
    assert result.inserted == 7


def test_load_holidays_range_and_working_day(session: Session) -> None:
    upsert_holidays(session, parse_ics(ICS), HolidaySource.ICS_1823, None)
    got = load_holidays(session, date(2026, 1, 1), date(2026, 12, 31))
    assert date(2026, 10, 1) in got and date(2027, 2, 1) not in got
    assert not is_working_day(date(2026, 10, 1), got)
    assert is_working_day(date(2026, 10, 2), got)
    assert not is_working_day(date(2026, 10, 3), got)  # Saturday


def test_fetch_uses_client_and_returns_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://www.1823.gov.hk/common/ical/en.ics"
        return httpx.Response(200, text=ICS)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert "BEGIN:VCALENDAR" in fetch_1823_ics(client)


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(503),
        lambda r: httpx.Response(200, text="<html>not a calendar</html>"),
        lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("timeout")),
    ],
)
def test_fetch_errors_are_clear(handler) -> None:
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HolidayFetchError):
            fetch_1823_ics(client)
