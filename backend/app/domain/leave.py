"""Leave day calculation with half-day support (pure)."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.domain.enums import DayPart
from app.domain.errors import LeaveCalculationError

ONE = Decimal("1")
HALF = Decimal("0.5")


def is_working_day(day: date, holidays: Collection[date]) -> bool:
    """Mon-Fri and not a public holiday."""
    return day.weekday() < 5 and day not in holidays


@dataclass(frozen=True)
class LeaveDays:
    calendar_days: Decimal
    working_days: Decimal


def validate_day_parts(
    start_date: date, end_date: date, start_day_part: DayPart, end_day_part: DayPart
) -> None:
    """Structural rules (no holiday data needed).

    * end_date >= start_date
    * single day: start part == end part (full = 1 day, am/pm = 0.5)
    * multi day: start part in {full, pm}, end part in {full, am}
    """
    start_day_part, end_day_part = DayPart(start_day_part), DayPart(end_day_part)
    if end_date < start_date:
        raise LeaveCalculationError("end_date must not be before start_date")
    if start_date == end_date:
        if start_day_part != end_day_part:
            raise LeaveCalculationError(
                "A single-day leave needs the same day part at the start and the end"
            )
        return
    if start_day_part == DayPart.AM:
        raise LeaveCalculationError("A multi-day leave cannot start in the morning half only")
    if end_day_part == DayPart.PM:
        raise LeaveCalculationError("A multi-day leave cannot end in the afternoon half only")


def calculate_leave_days(
    start_date: date,
    end_date: date,
    start_day_part: DayPart = DayPart.FULL,
    end_day_part: DayPart = DayPart.FULL,
    holidays: Collection[date] = (),
) -> LeaveDays:
    """Working days (Mon-Fri minus public holidays) and calendar days, in 0.5 steps.

    A half-day on a weekend/holiday counts 0 working days. A request covering zero
    working days is rejected.
    """
    start_day_part, end_day_part = DayPart(start_day_part), DayPart(end_day_part)
    validate_day_parts(start_date, end_date, start_day_part, end_day_part)

    def weight(day: date) -> Decimal:
        if day == start_date and start_date == end_date:
            return ONE if start_day_part == DayPart.FULL else HALF
        if day == start_date and start_day_part == DayPart.PM:
            return HALF
        if day == end_date and end_day_part == DayPart.AM:
            return HALF
        return ONE

    calendar = Decimal(0)
    working = Decimal(0)
    day = start_date
    while day <= end_date:
        w = weight(day)
        calendar += w
        if is_working_day(day, holidays):
            working += w
        day += timedelta(days=1)

    if working == 0:
        raise LeaveCalculationError("The selected dates contain no working days")
    return LeaveDays(calendar_days=calendar, working_days=working)
