"""Schemas for the organisation data shown to the signed-in user (balances)."""

from pydantic import BaseModel

from app.domain.enums import LeaveType
from app.services.balances import LeaveBalance


class BalanceLine(BaseModel):
    """One leave type. Days are JSON numbers in 0.5 steps."""

    leave_type: LeaveType
    entitled_days: float
    approved_days: float
    pending_days: float
    remaining_days: float

    @classmethod
    def from_balance(cls, balance: LeaveBalance) -> "BalanceLine":
        return cls(
            leave_type=balance.leave_type,
            entitled_days=float(balance.entitled_days),
            approved_days=float(balance.approved_days),
            pending_days=float(balance.pending_days),
            remaining_days=float(balance.remaining_days),
        )


class BalancesResponse(BaseModel):
    year: int
    leave: list[BalanceLine]
