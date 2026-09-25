from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.clock import today_hk
from app.domain.enums import ClaimType, DayPart, LeaveType
from app.schemas.drafts import ClaimDraft, LeaveDraft

EMAIL = "amy.lau@example.com"


def test_leave_draft_defaults_to_full_days() -> None:
    d = LeaveDraft(employee_email=EMAIL, leave_type="annual", start_date="2026-10-05",
                   end_date="2026-10-06")  # fmt: skip
    assert d.start_day_part is DayPart.FULL and d.end_day_part is DayPart.FULL
    assert d.leave_type is LeaveType.ANNUAL


def test_leave_draft_half_day() -> None:
    d = LeaveDraft(employee_email=EMAIL, leave_type="sick", start_date="2026-10-05",
                   end_date="2026-10-05", start_day_part="am", end_day_part="am")  # fmt: skip
    assert d.start_day_part is DayPart.AM


@pytest.mark.parametrize(
    "extra",
    [
        {"end_date": "2026-10-04"},  # before start
        {"start_day_part": "am"},  # single day, mismatched parts
        {"end_date": "2026-10-06", "start_day_part": "am"},
        {"end_date": "2026-10-06", "end_day_part": "pm"},
    ],
)
def test_leave_draft_rejects_bad_dates_or_parts(extra: dict) -> None:
    data = {"employee_email": EMAIL, "leave_type": "annual", "start_date": "2026-10-05",
            "end_date": "2026-10-05"} | extra  # fmt: skip
    with pytest.raises(ValidationError):
        LeaveDraft(**data)


def test_leave_draft_rejects_bad_email_and_type() -> None:
    with pytest.raises(ValidationError):
        LeaveDraft(employee_email="not-an-email", leave_type="annual", start_date="2026-10-05",
                   end_date="2026-10-05")  # fmt: skip
    with pytest.raises(ValidationError):
        LeaveDraft(employee_email=EMAIL, leave_type="sabbatical", start_date="2026-10-05",
                   end_date="2026-10-05")  # fmt: skip


def test_claim_draft_ok() -> None:
    d = ClaimDraft(employee_email=EMAIL, claim_type="meal", amount="12.30",
                   receipt_date=today_hk())  # fmt: skip
    assert d.amount == Decimal("12.30") and d.currency == "HKD"
    assert d.claim_type is ClaimType.MEAL


@pytest.mark.parametrize("amount", ["0", "-5", "12.345", "abc"])
def test_claim_draft_rejects_bad_amounts(amount: str) -> None:
    with pytest.raises(ValidationError):
        ClaimDraft(employee_email=EMAIL, claim_type="meal", amount=amount,
                   receipt_date=today_hk())  # fmt: skip


def test_claim_draft_rejects_future_receipt_and_other_currency() -> None:
    with pytest.raises(ValidationError, match="future"):
        ClaimDraft(employee_email=EMAIL, claim_type="meal", amount="1",
                   receipt_date=today_hk() + timedelta(days=1))  # fmt: skip
    with pytest.raises(ValidationError):
        ClaimDraft(employee_email=EMAIL, claim_type="meal", amount="1", currency="USD",
                   receipt_date=today_hk())  # fmt: skip
