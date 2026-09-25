"""Validated draft inputs the later (LLM extraction) phase fills in.

Kept apart from the DB models. ``start_day_part`` / ``end_day_part`` are the two optional
fields the extractor sets to apply half-day leave; both default to ``full``.
"""

from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.domain.clock import today_hk
from app.domain.enums import ClaimType, DayPart, LeaveType
from app.domain.errors import LeaveCalculationError
from app.domain.leave import validate_day_parts


class LeaveDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    employee_email: EmailStr
    leave_type: LeaveType
    start_date: date
    end_date: date
    start_day_part: DayPart = DayPart.FULL
    end_day_part: DayPart = DayPart.FULL

    @model_validator(mode="after")
    def _check_dates_and_parts(self) -> Self:
        try:
            validate_day_parts(
                self.start_date, self.end_date, self.start_day_part, self.end_day_part
            )
        except LeaveCalculationError as exc:
            raise ValueError(str(exc)) from exc
        return self


class ClaimDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    employee_email: EmailStr
    claim_type: ClaimType
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: Literal["HKD"] = "HKD"
    receipt_date: date

    @field_validator("receipt_date")
    @classmethod
    def _not_in_future(cls, value: date) -> date:
        if value > today_hk():
            raise ValueError("receipt_date must not be in the future")
        return value
