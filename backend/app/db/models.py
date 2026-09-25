"""SQLAlchemy models. Persistence only: business rules live in ``app.domain``.

Polymorphic references (deliberately NO foreign key, because one column points at either
``leave_requests`` or ``claim_requests`` depending on a type column):

* ``external_submissions.request_type`` + ``request_id``
* ``notifications.request_type`` + ``request_id``
* ``audit_events.entity_type`` + ``entity_id``

The service layer (``app.services.references``) validates these before writing.

Money and day counts are exact ``Decimal`` values (see ``app.db.types.ScaledDecimal``);
all timestamps are timezone-aware UTC.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import ScaledDecimal, UTCDateTime
from app.domain.clock import utcnow
from app.domain.enums import (
    ClaimType,
    ConversationStatus,
    DayPart,
    HolidaySource,
    LeaveType,
    RequestStatus,
    RequestType,
    SenderType,
    SubmissionStatus,
    UserRole,
)


def enum_col(enum_cls: type[StrEnum], name: str) -> Enum:
    """VARCHAR + CHECK constraint (no native enum); stores the enum *values*."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(m.value) for m in enum_cls),
        values_callable=lambda cls: [m.value for m in cls],
    )


_REVIEW_CHECKS = (
    "status != 'rejected' OR reviewer_note IS NOT NULL",
    "status NOT IN ('approved', 'rejected') "
    "OR (reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_subject: Mapped[str] = mapped_column(String(128), unique=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(enum_col(UserRole, "role"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[ConversationStatus] = mapped_column(
        enum_col(ConversationStatus, "status"), default=ConversationStatus.ACTIVE
    )
    active_request_type: Mapped[RequestType | None] = mapped_column(
        enum_col(RequestType, "active_request_type"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        order_by="ConversationMessage.id",
        cascade="all, delete-orphan",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_type: Mapped[SenderType] = mapped_column(enum_col(SenderType, "sender_type"))
    content: Mapped[str] = mapped_column(Text)
    ui_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="date_order"),
        CheckConstraint("working_days > 0", name="working_days_positive"),
        CheckConstraint("calendar_days > 0", name="calendar_days_positive"),
        CheckConstraint("required_approver_role = 'hr_approver'", name="approver_is_hr"),
        CheckConstraint(_REVIEW_CHECKS[0], name="reject_needs_note"),
        CheckConstraint(_REVIEW_CHECKS[1], name="review_needs_reviewer"),
        Index("ix_leave_requests_employee_id_status", "employee_id", "status"),
    )
    request_type: ClassVar[RequestType] = RequestType.LEAVE

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    leave_type: Mapped[LeaveType] = mapped_column(enum_col(LeaveType, "leave_type"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    start_day_part: Mapped[DayPart] = mapped_column(
        enum_col(DayPart, "start_day_part"), default=DayPart.FULL
    )
    end_day_part: Mapped[DayPart] = mapped_column(
        enum_col(DayPart, "end_day_part"), default=DayPart.FULL
    )
    calendar_days: Mapped[Decimal] = mapped_column(ScaledDecimal(1))
    working_days: Mapped[Decimal] = mapped_column(ScaledDecimal(1))
    status: Mapped[RequestStatus] = mapped_column(
        enum_col(RequestStatus, "status"), default=RequestStatus.DRAFT
    )
    required_approver_role: Mapped[UserRole] = mapped_column(
        enum_col(UserRole, "required_approver_role"), default=UserRole.HR_APPROVER
    )
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ClaimRequest(Base):
    __tablename__ = "claim_requests"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("required_approver_role = 'finance_approver'", name="approver_is_finance"),
        CheckConstraint(_REVIEW_CHECKS[0], name="reject_needs_note"),
        CheckConstraint(_REVIEW_CHECKS[1], name="review_needs_reviewer"),
        Index("ix_claim_requests_employee_id_status", "employee_id", "status"),
    )
    request_type: ClassVar[RequestType] = RequestType.CLAIM

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    claim_type: Mapped[ClaimType] = mapped_column(enum_col(ClaimType, "claim_type"))
    amount: Mapped[Decimal] = mapped_column(ScaledDecimal(2))
    currency: Mapped[str] = mapped_column(String(3), default="HKD", server_default="HKD")
    receipt_date: Mapped[date] = mapped_column(Date)
    status: Mapped[RequestStatus] = mapped_column(
        enum_col(RequestStatus, "status"), default=RequestStatus.DRAFT
    )
    required_approver_role: Mapped[UserRole] = mapped_column(
        enum_col(UserRole, "required_approver_role"), default=UserRole.FINANCE_APPROVER
    )
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ExternalSubmission(Base):
    """One attempt to send a request to the mock API. ``request_id`` is polymorphic (no FK)."""

    __tablename__ = "external_submissions"
    __table_args__ = (Index("ix_external_submissions_request", "request_type", "request_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_type: Mapped[RequestType] = mapped_column(enum_col(RequestType, "request_type"))
    request_id: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32), default="reqres")
    status: Mapped[SubmissionStatus] = mapped_column(enum_col(SubmissionStatus, "status"))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Notification(Base):
    """In-app notification. ``request_id`` is polymorphic (no FK)."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_recipient_user_id_read_at", "recipient_user_id", "read_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    request_type: Mapped[RequestType] = mapped_column(enum_col(RequestType, "request_type"))
    request_id: Mapped[int] = mapped_column(Integer)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditEvent(Base):
    """Append-only audit trail. ``entity_id`` is polymorphic (no FK) and NULL for events that
    have no entity (e.g. a login attempt for an unknown e-mail); ``actor_user_id`` is NULL
    for failed logins and system actions."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PublicHoliday(Base):
    __tablename__ = "public_holidays"

    id: Mapped[int] = mapped_column(primary_key=True)
    holiday_date: Mapped[date] = mapped_column(Date, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[HolidaySource] = mapped_column(enum_col(HolidaySource, "source"))
    source_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
