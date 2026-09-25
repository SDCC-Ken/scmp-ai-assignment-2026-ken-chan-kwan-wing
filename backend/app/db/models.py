"""SQLAlchemy models. Persistence only: business rules live in ``app.domain``.

Polymorphic references (deliberately NO foreign key, because one column points at either
``leave_requests`` or ``claim_requests`` depending on a type column):

* ``external_submissions.request_type`` + ``request_id``
* ``notifications.request_type`` + ``request_id``
* ``audit_events.entity_type`` + ``entity_id``
* ``attachments.request_type`` + ``request_id`` (NULL until the file is linked to a request)

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
    UniqueConstraint,
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


# A decided request must say who decided and when. The reviewer note is OPTIONAL for both
# approve and reject (Phase 3: the earlier "reject needs a note" CHECK was removed).
_REVIEW_CHECK = (
    "status NOT IN ('approved', 'rejected') "
    "OR (reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)"
)


class SchemaMeta(Base):
    """Key/value bookkeeping for the schema itself. ``schema_version`` is written by
    ``init_db`` for a new database and checked at start-up (see ``app.db.session``)."""

    __tablename__ = "schema_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(64))


class Department(Base):
    """A department. ``claim_limit_amount`` is the yearly claim budget shown to approvers
    (HKD, shown but never blocking)."""

    __tablename__ = "departments"
    __table_args__ = (CheckConstraint("claim_limit_amount >= 0", name="claim_limit_not_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    claim_limit_amount: Mapped[Decimal] = mapped_column(ScaledDecimal(2))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    """A person. ``leave_approver_user_id`` / ``claim_approver_user_id`` say who decides this
    user's requests (one approver per user and request type, NULL = none configured)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_subject: Mapped[str] = mapped_column(String(128), unique=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(enum_col(UserRole, "role"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), nullable=True, index=True
    )
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    leave_approver_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    claim_approver_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    department: Mapped[Department | None] = relationship(lazy="joined")

    @property
    def can_request(self) -> bool:
        """May file requests / use the chat: at least one approver is configured."""
        return self.leave_approver_user_id is not None or self.claim_approver_user_id is not None

    @property
    def approves(self) -> str | None:
        """Which queue this user decides: ``leave`` (HR approver), ``claim`` (Finance) or None."""
        if self.role == UserRole.HR_APPROVER:
            return "leave"
        if self.role == UserRole.FINANCE_APPROVER:
            return "claim"
        return None


class LeaveEntitlement(Base):
    """Yearly leave entitlement of one user for ``annual`` or ``sick`` leave (half-day steps)."""

    __tablename__ = "leave_entitlements"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "year", "leave_type", name="uq_leave_entitlements_user_year_type"
        ),
        CheckConstraint("entitled_days >= 0", name="entitled_days_not_negative"),
        CheckConstraint("leave_type IN ('annual', 'sick')", name="type_annual_or_sick"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    leave_type: Mapped[LeaveType] = mapped_column(enum_col(LeaveType, "leave_type"))
    entitled_days: Mapped[Decimal] = mapped_column(ScaledDecimal(1))


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
    # Serialised ``app.chat.state.ConversationState`` (slots, pending card, version counter).
    # NULL for conversations created before Phase 2 (treated as an empty state).
    state_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
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


class Attachment(Base):
    """An uploaded image / PDF kept on disk under ``UPLOAD_DIR`` (never a blob in SQLite).

    ``storage_path`` is generated by the server and relative to ``UPLOAD_DIR``;
    ``original_filename`` is only a sanitised display name. A file is *staged* while
    ``message_id`` is NULL, then belongs to a user message, and is finally linked to the
    request created from the draft (``request_type`` + ``request_id``, polymorphic, no FK).
    ``extraction_json`` is filled by the document-reading step.
    """

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("(request_type IS NULL) = (request_id IS NULL)", name="request_link_pair"),
        Index("ix_attachments_conversation_id", "conversation_id"),
        Index("ix_attachments_owner_user_id", "owner_user_id"),
        Index("ix_attachments_request", "request_type", "request_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id"), nullable=True
    )
    request_type: Mapped[RequestType | None] = mapped_column(
        enum_col(RequestType, "request_type"), nullable=True
    )
    request_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(255))
    extraction_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="date_order"),
        CheckConstraint("working_days > 0", name="working_days_positive"),
        CheckConstraint("calendar_days > 0", name="calendar_days_positive"),
        CheckConstraint("required_approver_role = 'hr_approver'", name="approver_is_hr"),
        CheckConstraint(_REVIEW_CHECK, name="review_needs_reviewer"),
        Index("ix_leave_requests_employee_id_status", "employee_id", "status"),
        Index("ix_leave_requests_approver_user_id_status", "approver_user_id", "status"),
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
    # The assigned approver, copied from users.leave_approver_user_id when the request is created.
    approver_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Conversation in which the request was confirmed (NULL for seeded / pre-Phase-2 rows).
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ClaimRequest(Base):
    __tablename__ = "claim_requests"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("required_approver_role = 'finance_approver'", name="approver_is_finance"),
        CheckConstraint(_REVIEW_CHECK, name="review_needs_reviewer"),
        Index("ix_claim_requests_employee_id_status", "employee_id", "status"),
        Index("ix_claim_requests_approver_user_id_status", "approver_user_id", "status"),
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
    # The assigned approver, copied from users.claim_approver_user_id when the request is created.
    approver_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Conversation in which the request was confirmed (NULL for seeded / pre-Phase-2 rows).
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
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
    # Exactly the body handed to the submission adapter (proof of what left the system).
    request_payload_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
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
