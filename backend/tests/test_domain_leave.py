from datetime import date
from decimal import Decimal

import pytest

from app.domain.enums import DayPart
from app.domain.errors import LeaveCalculationError
from app.domain.leave import calculate_leave_days, is_working_day

FULL, AM, PM = DayPart.FULL, DayPart.AM, DayPart.PM
D = Decimal
NATIONAL_DAY = date(2026, 10, 1)  # Thursday
HOLIDAYS = {NATIONAL_DAY, date(2026, 10, 19)}


def test_single_full_day() -> None:
    r = calculate_leave_days(date(2026, 10, 5), date(2026, 10, 5))
    assert (r.calendar_days, r.working_days) == (D(1), D(1))


@pytest.mark.parametrize("part", [AM, PM])
def test_single_half_day(part: DayPart) -> None:
    r = calculate_leave_days(date(2026, 10, 5), date(2026, 10, 5), part, part)
    assert (r.calendar_days, r.working_days) == (D("0.5"), D("0.5"))


def test_multi_day_pm_start_am_end() -> None:
    # Mon pm (0.5) + Tue (1) + Wed am (0.5)
    r = calculate_leave_days(date(2026, 10, 5), date(2026, 10, 7), PM, AM)
    assert (r.calendar_days, r.working_days) == (D(2), D(2))


def test_weekend_is_skipped_for_working_days_only() -> None:
    # Fri 2 Oct .. Mon 5 Oct: 4 calendar days, 2 working days
    r = calculate_leave_days(date(2026, 10, 2), date(2026, 10, 5))
    assert (r.calendar_days, r.working_days) == (D(4), D(2))


def test_pm_start_on_friday_across_weekend_to_monday_am() -> None:
    r = calculate_leave_days(date(2026, 10, 2), date(2026, 10, 5), PM, AM)
    assert (r.calendar_days, r.working_days) == (D(3), D(1))


def test_public_holiday_is_skipped() -> None:
    # Wed 30 Sep .. Fri 2 Oct with National Day (Thu 1 Oct) in the middle
    r = calculate_leave_days(date(2026, 9, 30), date(2026, 10, 2), holidays=HOLIDAYS)
    assert (r.calendar_days, r.working_days) == (D(3), D(2))


def test_half_day_on_holiday_or_weekend_counts_zero_and_errors_alone() -> None:
    with pytest.raises(LeaveCalculationError, match="no working days"):
        calculate_leave_days(NATIONAL_DAY, NATIONAL_DAY, AM, AM, HOLIDAYS)
    with pytest.raises(LeaveCalculationError, match="no working days"):
        calculate_leave_days(date(2026, 10, 3), date(2026, 10, 3), PM, PM)  # Saturday


def test_half_day_on_holiday_inside_range_counts_zero() -> None:
    # Thu 1 Oct (holiday) pm start .. Fri 2 Oct: only Friday counts
    r = calculate_leave_days(NATIONAL_DAY, date(2026, 10, 2), PM, FULL, HOLIDAYS)
    assert (r.calendar_days, r.working_days) == (D("1.5"), D(1))


def test_only_weekend_and_holidays_is_zero_working_days_error() -> None:
    with pytest.raises(LeaveCalculationError):
        calculate_leave_days(date(2026, 10, 3), date(2026, 10, 4))
    with pytest.raises(LeaveCalculationError):
        calculate_leave_days(NATIONAL_DAY, NATIONAL_DAY, holidays=HOLIDAYS)


def test_end_before_start() -> None:
    with pytest.raises(LeaveCalculationError, match="before"):
        calculate_leave_days(date(2026, 10, 6), date(2026, 10, 5))


@pytest.mark.parametrize(
    ("start_part", "end_part"),
    [(AM, PM), (PM, FULL), (FULL, AM), (AM, FULL)],
)
def test_single_day_needs_same_parts(start_part: DayPart, end_part: DayPart) -> None:
    with pytest.raises(LeaveCalculationError):
        calculate_leave_days(date(2026, 10, 5), date(2026, 10, 5), start_part, end_part)


@pytest.mark.parametrize(("start_part", "end_part"), [(AM, FULL), (AM, AM), (FULL, PM), (PM, PM)])
def test_multi_day_invalid_part_combinations(start_part: DayPart, end_part: DayPart) -> None:
    with pytest.raises(LeaveCalculationError):
        calculate_leave_days(date(2026, 10, 5), date(2026, 10, 6), start_part, end_part)


def test_year_boundary() -> None:
    hol = {date(2026, 12, 25), date(2026, 12, 26), date(2027, 1, 1)}
    # Thu 31 Dec 2026 .. Mon 4 Jan 2027: Thu, (Fri 1 Jan holiday), Mon -> 2 working days
    r = calculate_leave_days(date(2026, 12, 31), date(2027, 1, 4), holidays=hol)
    assert (r.calendar_days, r.working_days) == (D(5), D(2))


def test_results_are_decimals_in_half_steps() -> None:
    r = calculate_leave_days(date(2026, 10, 5), date(2026, 10, 9), PM, AM)
    assert isinstance(r.working_days, Decimal) and r.working_days % D("0.5") == 0
    assert r.working_days == D(4)


def test_is_working_day() -> None:
    assert is_working_day(date(2026, 9, 25), HOLIDAYS)
    assert not is_working_day(NATIONAL_DAY, HOLIDAYS)
    assert not is_working_day(date(2026, 9, 26), HOLIDAYS)
