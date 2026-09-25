"""Backend validation of a draft (never the LLM).

Pipeline order: slot types (enums, exact decimals) -> cheap structural checks on the fields
that are present -> missing fields -> Pydantic draft (``LeaveDraft`` / ``ClaimDraft``) ->
working-day calculation -> Phase 3 business rules (``app.chat.policy.BUSINESS_RULES``, empty
today). Every failure becomes a deterministic follow-up that names the field and the problem.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.chat.policy import CLAIM_CURRENCY, CLAIM_MAX_DECIMALS, RuleContext, first_violation
from app.chat.state import ClaimSlots, LeaveSlots
from app.db.models import PublicHoliday
from app.domain.clock import today_hk
from app.domain.enums import ClaimType, DayPart, LeaveType, RequestType
from app.domain.errors import LeaveCalculationError
from app.domain.leave import LeaveDays, calculate_leave_days
from app.schemas.drafts import ClaimDraft, LeaveDraft
from app.services.holidays import load_holidays

LEAVE_REQUIRED = ("leave_type", "start_date", "end_date")
CLAIM_REQUIRED = ("claim_type", "amount", "receipt_date")
FIELD_LABELS = {
    "leave_type": "Leave type",
    "start_date": "Start date",
    "end_date": "End date",
    "start_day_part": "Start day part",
    "end_day_part": "End day part",
    "claim_type": "Claim type",
    "amount": "Amount",
    "currency": "Currency",
    "receipt_date": "Receipt date",
}


@dataclass(frozen=True)
class Missing:
    field: str


@dataclass(frozen=True)
class Problem:
    field: str
    message: str


@dataclass(frozen=True)
class ValidLeave:
    draft: LeaveDraft
    days: LeaveDays
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidClaim:
    draft: ClaimDraft
    warnings: list[str] = field(default_factory=list)


Outcome = Missing | Problem | ValidLeave | ValidClaim


def normalise_leave_slots(slots: LeaveSlots) -> LeaveSlots:
    """Deterministic, obviously-safe completions of the day parts.

    * single day with only one part given -> the other part mirrors it
    * a morning-only or afternoon-only start with no end date -> a single half day
      (a half day can only be a single day, so no end-date question is needed)
    """
    s = slots.model_copy()
    if s.start_date and not s.end_date and s.start_day_part in (DayPart.AM, DayPart.PM):
        s.end_date = s.start_date
        s.end_day_part = s.start_day_part
    if s.start_date and s.end_date and s.start_date == s.end_date:
        if s.start_day_part and not s.end_day_part:
            s.end_day_part = s.start_day_part
        elif s.end_day_part and not s.start_day_part:
            s.start_day_part = s.end_day_part
    return s


def _labelled_missing(present: dict[str, object], order: tuple[str, ...]) -> Missing | None:
    for name in order:
        if present.get(name) is None:
            return Missing(name)
    return None


def _day_part_problem(s: LeaveSlots) -> Problem | None:
    assert s.start_date and s.end_date
    start_part, end_part = s.start_day_part or DayPart.FULL, s.end_day_part or DayPart.FULL
    if s.start_date == s.end_date:
        if start_part != end_part:
            return Problem(
                "start_day_part",
                f"For a single day ({s.start_date.isoformat()}) the start and end day part must "
                "match. Do you want the full day, the morning only or the afternoon only?",
            )
        return None
    if start_part == DayPart.AM:
        return Problem(
            "start_day_part",
            "A leave over several days cannot start with a morning-only day. Should the first "
            "day be a full day or the afternoon only?",
        )
    if end_part == DayPart.PM:
        return Problem(
            "end_day_part",
            "A leave over several days cannot end with an afternoon-only day. Should the last "
            "day be a full day or the morning only?",
        )
    return None


def _holiday_names(session: Session, start: date, end: date) -> list[str]:
    rows = session.execute(
        select(PublicHoliday.holiday_date, PublicHoliday.name)
        .where(PublicHoliday.holiday_date >= start, PublicHoliday.holiday_date <= end)
        .order_by(PublicHoliday.holiday_date)
    ).all()
    return [f"{name} on {day.isoformat()}" for day, name in rows]


def _missing_holiday_years(session: Session, start: date, end: date) -> list[int]:
    missing: list[int] = []
    for year in range(start.year, end.year + 1):
        count = session.scalar(
            select(func.count(PublicHoliday.id)).where(
                PublicHoliday.holiday_date >= date(year, 1, 1),
                PublicHoliday.holiday_date <= date(year, 12, 31),
            )
        )
        if not count:
            missing.append(year)
    return missing


def _pydantic_problem(exc: ValidationError, labels: dict[str, str]) -> Problem:
    err = exc.errors()[0]
    loc = str(err["loc"][0]) if err["loc"] else "request"
    label = labels.get(loc, loc.replace("_", " ").capitalize())
    kind = str(err["type"])
    if "decimal" in kind or "digits" in kind:
        return Problem(loc, f"{label} is too large or has too many decimals. Please give it again.")
    text = str(err["msg"]).removeprefix("Value error, ")
    return Problem(loc, f"{label} is not valid ({text}). Please give it again.")


def validate_leave(
    session: Session,
    slots: LeaveSlots,
    *,
    employee_id: int,
    employee_email: str,
    today: date | None = None,
    editing_request_id: int | None = None,
) -> Outcome:
    today = today or today_hk()
    s = normalise_leave_slots(slots)

    if s.start_date and s.end_date and s.end_date < s.start_date:
        return Problem(
            "end_date",
            f"End date {s.end_date.isoformat()} is before the start date "
            f"{s.start_date.isoformat()}. Which end date do you want?",
        )
    if (m := _labelled_missing(s.model_dump(), LEAVE_REQUIRED)) is not None:
        return m
    assert s.leave_type and s.start_date and s.end_date  # narrowed by the missing check
    if (p := _day_part_problem(s)) is not None:
        return p

    try:
        draft = LeaveDraft(
            employee_email=employee_email,
            leave_type=s.leave_type,
            start_date=s.start_date,
            end_date=s.end_date,
            start_day_part=s.start_day_part or DayPart.FULL,
            end_day_part=s.end_day_part or DayPart.FULL,
        )
    except ValidationError as exc:
        return _pydantic_problem(exc, FIELD_LABELS)

    holidays = load_holidays(session, draft.start_date, draft.end_date)
    try:
        days = calculate_leave_days(
            draft.start_date,
            draft.end_date,
            draft.start_day_part,
            draft.end_day_part,
            holidays,
        )
    except LeaveCalculationError:
        span = (
            draft.start_date.isoformat()
            if draft.start_date == draft.end_date
            else f"{draft.start_date.isoformat()} to {draft.end_date.isoformat()}"
        )
        names = _holiday_names(session, draft.start_date, draft.end_date)
        why = "only weekends" + (f" and public holidays ({'; '.join(names)})" if names else "")
        return Problem(
            "start_date",
            f"{span} covers {why}, so it contains no working day to take as leave. "
            "Which working dates do you want?",
        )

    violation = first_violation(
        RuleContext(
            session=session,
            employee_id=employee_id,
            request_type=RequestType.LEAVE,
            draft=draft,
            today=today,
            days=days,
            editing_request_id=editing_request_id,
        )
    )
    if violation is not None:
        return Problem(violation.field, violation.message)

    warnings = [
        f"No public-holiday data for {year}; only weekends were excluded from the working days"
        for year in _missing_holiday_years(session, draft.start_date, draft.end_date)
    ]
    return ValidLeave(draft=draft, days=days, warnings=warnings)


def _amount_problem(amount: Decimal) -> Problem | None:
    if not amount.is_finite():
        return Problem("amount", "That amount is not a number. How much is the claim, in HKD?")
    if amount <= 0:
        return Problem(
            "amount",
            f"The amount {format(amount, 'f')} must be greater than 0. "
            "How much is the claim, in HKD?",
        )
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -CLAIM_MAX_DECIMALS:
        return Problem(
            "amount",
            f"The amount {format(amount, 'f')} has more than {CLAIM_MAX_DECIMALS} decimal "
            "places. What is the exact amount in HKD (at most 2 decimals)?",
        )
    return None


def validate_claim(
    session: Session,
    slots: ClaimSlots,
    *,
    employee_id: int,
    employee_email: str,
    today: date | None = None,
    editing_request_id: int | None = None,
) -> Outcome:
    today = today or today_hk()

    if slots.amount is not None and (p := _amount_problem(slots.amount)) is not None:
        return p
    currency = (slots.currency or CLAIM_CURRENCY).strip().upper()
    if currency != CLAIM_CURRENCY:
        return Problem(
            "currency",
            f"Claims are accepted in {CLAIM_CURRENCY} only, and you mentioned {currency}. "
            "What is the amount in HKD?",
        )
    if slots.receipt_date is not None and slots.receipt_date > today:
        return Problem(
            "receipt_date",
            f"The receipt date {slots.receipt_date.isoformat()} is in the future. "
            "What is the date on the receipt?",
        )
    if (m := _labelled_missing(slots.model_dump(), CLAIM_REQUIRED)) is not None:
        return m
    assert slots.claim_type and slots.amount is not None and slots.receipt_date

    try:
        draft = ClaimDraft(
            employee_email=employee_email,
            claim_type=slots.claim_type,
            amount=slots.amount,
            currency=CLAIM_CURRENCY,
            receipt_date=slots.receipt_date,
        )
    except ValidationError as exc:
        return _pydantic_problem(exc, FIELD_LABELS)

    violation = first_violation(
        RuleContext(
            session=session,
            employee_id=employee_id,
            request_type=RequestType.CLAIM,
            draft=draft,
            today=today,
            amount=draft.amount,
            editing_request_id=editing_request_id,
        )
    )
    if violation is not None:
        return Problem(violation.field, violation.message)
    return ValidClaim(draft=draft)


def to_decimal(value: float | int | str) -> Decimal | None:
    """LLM ``amount`` (float) -> exact Decimal through its shortest repr (12.3, not 12.3000...01).

    Returns None when it is not a finite number (NaN / infinity). More than 2 decimals is NOT
    rounded here: the value is kept so that validation can tell the user.
    """

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def coerce_enum[E: (LeaveType, ClaimType, DayPart)](enum_cls: type[E], value: object) -> E | None:
    try:
        return enum_cls(value)
    except ValueError:
        return None
