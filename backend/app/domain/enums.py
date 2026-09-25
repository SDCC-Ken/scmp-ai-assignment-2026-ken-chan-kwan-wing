"""String enums shared by the domain, the DB models and the API schemas."""

from enum import StrEnum


class UserRole(StrEnum):
    EMPLOYEE = "employee"
    HR_APPROVER = "hr_approver"
    FINANCE_APPROVER = "finance_approver"


class RequestType(StrEnum):
    LEAVE = "leave"
    CLAIM = "claim"


class RequestStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    SUBMISSION_FAILED = "submission_failed"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LeaveType(StrEnum):
    ANNUAL = "annual"
    SICK = "sick"
    PERSONAL = "personal"
    UNPAID = "unpaid"


class ClaimType(StrEnum):
    TRAVEL = "travel"
    MEAL = "meal"
    EQUIPMENT = "equipment"
    TRAINING = "training"
    OTHER = "other"


class DayPart(StrEnum):
    FULL = "full"
    AM = "am"
    PM = "pm"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class SenderType(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SubmissionStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class HolidaySource(StrEnum):
    SEED_2026 = "seed_2026"
    ICS_1823 = "1823_ics"
