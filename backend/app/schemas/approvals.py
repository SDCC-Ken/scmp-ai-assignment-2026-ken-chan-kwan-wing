"""Approver API shapes (see docs/phase3-approval-design.md, section 5).

Days are JSON numbers (0.5 steps); money is a string with two decimals so no precision is lost.
Nothing here carries the employee's e-mail address.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import LeaveType, RequestStatus, RequestType
from app.schemas.chat import AttachmentInfo, IsoZ

NOTE_MAX_CHARS = 500


class EmployeeRef(BaseModel):
    id: int
    display_name: str
    department: str | None = None


class ApprovalFlags(BaseModel):
    over_limit: bool
    team_overlap_count: int
    has_attachments: bool


class ApprovalListItem(BaseModel):
    request_type: RequestType
    id: int
    employee: EmployeeRef
    summary: str
    submitted_at: IsoZ | None
    flags: ApprovalFlags


class ApprovalList(BaseModel):
    items: list[ApprovalListItem]
    count: int


class DetailField(BaseModel):
    key: str
    label: str
    value: str


class ApprovalRequestView(BaseModel):
    request_type: RequestType
    id: int
    status: RequestStatus
    submitted_at: IsoZ | None
    employee: EmployeeRef
    fields: list[DetailField]
    attachments: list[AttachmentInfo]
    external_reference_id: str | None = None


class LeaveBalanceView(BaseModel):
    leave_type: LeaveType
    year: int
    entitled_days: float
    approved_days: float
    pending_other_days: float
    requested_days: float
    remaining_after_days: float
    over_limit: bool


class DepartmentBudgetView(BaseModel):
    department: str
    year: int
    limit_amount: str
    approved_amount: str
    pending_other_amount: str
    requested_amount: str
    remaining_after_amount: str
    over_limit: bool
    currency: str


class Limits(BaseModel):
    leave_balance: LeaveBalanceView | None = None
    department_budget: DepartmentBudgetView | None = None


class TeamOverlapView(BaseModel):
    employee: str
    leave_type: LeaveType
    start_date: str
    end_date: str
    status: RequestStatus
    working_days: float


class ApprovalDetail(BaseModel):
    request: ApprovalRequestView
    limits: Limits
    team_overlap: list[TeamOverlapView]
    warnings: list[str]


class DecisionBody(BaseModel):
    """``note`` is optional for both decisions: trimmed, empty becomes ``None``, max 500."""

    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None)

    @field_validator("note")
    @classmethod
    def _clean_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > NOTE_MAX_CHARS:
            raise ValueError(f"The note can be at most {NOTE_MAX_CHARS} characters.")
        return value


class DecisionResponse(BaseModel):
    request_type: RequestType
    id: int
    status: RequestStatus
    reviewed_at: IsoZ
