"""Hong Kong public holidays: 1823 iCal parsing, idempotent upsert, fetch and lookups."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PublicHoliday
from app.domain.enums import HolidaySource
from app.domain.leave import is_working_day

__all__ = [
    "HOLIDAYS_1823_URL",
    "HolidayEvent",
    "HolidayFetchError",
    "UpsertResult",
    "fetch_1823_ics",
    "is_working_day",
    "latest_stamp",
    "load_holidays",
    "parse_ics",
    "upsert_holidays",
]

HOLIDAYS_1823_URL = "https://www.1823.gov.hk/common/ical/en.ics"
FETCH_TIMEOUT_SECONDS = 15.0

_QUOTE_MAP = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


class HolidayFetchError(RuntimeError):
    """The holiday feed could not be downloaded or is not an iCalendar document."""


@dataclass(frozen=True)
class HolidayEvent:
    holiday_date: date
    name: str
    dtstamp: datetime | None = None


@dataclass(frozen=True)
class UpsertResult:
    inserted: int
    updated: int
    unchanged: int


def _unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with space/tab continues the previous one."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    """Undo iCal TEXT escapes (backslash-n, -comma, -semicolon, -backslash); normalise quotes."""
    out = re.sub(r"\\([nN,;\\])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)
    return " ".join(out.translate(_QUOTE_MAP).split())


def _parse_date(value: str) -> date:
    return datetime.strptime(value.strip()[:8], "%Y%m%d").date()


def _parse_stamp(value: str) -> datetime | None:
    value = value.strip()
    try:
        if "T" in value:
            return datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_ics(text: str) -> list[HolidayEvent]:
    """Parse VEVENTs into one ``HolidayEvent`` per holiday date, sorted by date.

    Handles folded lines, ``DTSTART;VALUE=DATE:YYYYMMDD`` (or a date-time), escaped
    SUMMARY text and curly apostrophes (normalised to ``'``). A multi-day event
    (exclusive DTEND more than a day later) is expanded to one row per day.
    """
    events: dict[date, HolidayEvent] = {}
    current: dict[str, str] | None = None
    for line in _unfold(text):
        if line.strip() == "BEGIN:VEVENT":
            current = {}
        elif line.strip() == "END:VEVENT":
            if current is not None and "DTSTART" in current and "SUMMARY" in current:
                start = _parse_date(current["DTSTART"])
                end = _parse_date(current["DTEND"]) if "DTEND" in current else start
                stamp = _parse_stamp(current["DTSTAMP"]) if "DTSTAMP" in current else None
                name = _unescape(current["SUMMARY"])
                day = start
                while day <= start or day < end:
                    events[day] = HolidayEvent(day, name, stamp)
                    day += timedelta(days=1)
            current = None
        elif current is not None and ":" in line:
            key_part, _, value = line.partition(":")
            current[key_part.split(";", 1)[0].upper()] = value
    return sorted(events.values(), key=lambda e: e.holiday_date)


def latest_stamp(events: list[HolidayEvent]) -> datetime | None:
    stamps = [e.dtstamp for e in events if e.dtstamp is not None]
    return max(stamps) if stamps else None


def upsert_holidays(
    session: Session,
    events: list[HolidayEvent],
    source: HolidaySource,
    source_updated_at: datetime | None,
) -> UpsertResult:
    """Insert or update by ``holiday_date``; running it twice changes nothing (caller commits)."""
    source = HolidaySource(source)
    unique = {e.holiday_date: e for e in events}
    existing = {
        h.holiday_date: h
        for h in session.scalars(
            select(PublicHoliday).where(PublicHoliday.holiday_date.in_(list(unique)))
        )
    }
    inserted = updated = unchanged = 0
    for day, event in unique.items():
        row = existing.get(day)
        if row is None:
            session.add(
                PublicHoliday(
                    holiday_date=day,
                    name=event.name,
                    source=source,
                    source_updated_at=source_updated_at,
                )
            )
            inserted += 1
        elif (row.name, row.source, row.source_updated_at) != (
            event.name,
            source,
            source_updated_at,
        ):
            row.name = event.name
            row.source = source
            row.source_updated_at = source_updated_at
            updated += 1
        else:
            unchanged += 1
    session.flush()
    return UpsertResult(inserted, updated, unchanged)


def fetch_1823_ics(client: httpx.Client | None = None, url: str = HOLIDAYS_1823_URL) -> str:
    """Download the iCal feed. Raises ``HolidayFetchError`` with a clear message."""
    owns_client = client is None
    client = client or httpx.Client(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True)
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HolidayFetchError(f"Holiday feed returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise HolidayFetchError(f"Could not download the holiday feed: {exc}") from exc
    finally:
        if owns_client:
            client.close()
    text = response.text
    if "BEGIN:VCALENDAR" not in text:
        raise HolidayFetchError("The holiday feed is not an iCalendar document")
    return text


def load_holidays(session: Session, start: date, end: date) -> set[date]:
    """Holiday dates in ``[start, end]`` inclusive."""
    return set(
        session.scalars(
            select(PublicHoliday.holiday_date).where(
                PublicHoliday.holiday_date >= start, PublicHoliday.holiday_date <= end
            )
        )
    )
