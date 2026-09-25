"""Small display helpers shared by cards, follow-ups and status text (plain text only)."""

from datetime import date
from decimal import Decimal

from app.domain.enums import DayPart

DAY_PART_LABELS = {
    DayPart.FULL: "full day",
    DayPart.AM: "morning only",
    DayPart.PM: "afternoon only",
}


def fmt_date(value: date) -> str:
    """``Mon 2026-10-05``."""
    return f"{value:%a} {value.isoformat()}"


def fmt_days(value: Decimal) -> str:
    """``2.5`` / ``3`` (no trailing zeros)."""
    return format(value.normalize(), "f")


def fmt_money(value: Decimal, currency: str = "HKD") -> str:
    return f"{currency} {value:,.2f}"


def fmt_date_with_part(value: date, part: DayPart) -> str:
    text = fmt_date(value)
    return text if part == DayPart.FULL else f"{text} ({DAY_PART_LABELS[part]})"


def plural(count: int | Decimal, singular: str, plural_form: str | None = None) -> str:
    word = singular if count == 1 else (plural_form or singular + "s")
    return f"{fmt_days(count) if isinstance(count, Decimal) else count} {word}"
