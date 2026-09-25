from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    ClaimRequest,
    ConversationMessage,
    Feedback,
    LeaveRequest,
    PublicHoliday,
    User,
)
from app.db.session import Database, create_db_engine
from app.domain.enums import (
    ClaimType,
    HolidaySource,
    LeaveType,
    RequestStatus,
    SenderType,
    UserRole,
)


def add_user(session: Session, n: int = 1, role: UserRole = UserRole.EMPLOYEE, **kw) -> User:
    user = User(
        google_subject=kw.pop("google_subject", f"mock-google-sub-{n:03d}"),
        email=kw.pop("email", f"user{n}@example.com"),
        display_name="Test User",
        role=role,
        **kw,
    )
    session.add(user)
    session.commit()
    return user


def test_pragmas_applied_in_memory(session: Session) -> None:
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
    assert session.execute(text("PRAGMA busy_timeout")).scalar() == 5000
    assert session.execute(text("PRAGMA synchronous")).scalar() == 1  # NORMAL


def test_file_db_uses_wal_and_creates_parent_dir(tmp_path) -> None:
    path = tmp_path / "nested" / "dir" / "app.db"
    engine = create_db_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    assert path.parent.is_dir()
    engine.dispose()


def test_non_sqlite_url_rejected() -> None:
    with pytest.raises(ValueError):
        create_db_engine("postgresql://u:p@localhost/db")


def test_foreign_keys_enforced(session: Session) -> None:
    session.add(
        LeaveRequest(
            employee_id=999,
            leave_type=LeaveType.ANNUAL,
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 5),
            calendar_days=Decimal("1"),
            working_days=Decimal("1"),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_unique_email_and_google_subject(session: Session) -> None:
    add_user(session, 1)
    session.add(
        User(google_subject="other", email="user1@example.com", display_name="X", role="employee")
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(
        User(
            google_subject="mock-google-sub-001",
            email="another@example.com",
            display_name="X",
            role="employee",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_check_constraints_reject_bad_enum_values(session: Session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO users (google_subject, email, display_name, role, is_active, "
                "created_at) VALUES ('g', 'a@example.com', 'A', :role, 1, '2026-01-01')"
            ),
            {"role": "admin"},
        )
    session.rollback()
    user = add_user(session)
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO claim_requests (employee_id, claim_type, amount, currency, "
                "receipt_date, status, required_approver_role, created_at, updated_at) "
                "VALUES (:e, 'travel', 100, 'HKD', '2026-01-01', :status, 'finance_approver', "
                "'2026-01-01', '2026-01-01')"
            ),
            {"e": user.id, "status": "on_hold"},
        )


def test_approver_role_and_review_checks(session: Session) -> None:
    user = add_user(session)
    base = {
        "employee_id": user.id,
        "claim_type": ClaimType.MEAL,
        "amount": Decimal("10.00"),
        "receipt_date": date(2026, 1, 1),
    }
    session.add(ClaimRequest(**base, required_approver_role=UserRole.HR_APPROVER))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(ClaimRequest(**base, status=RequestStatus.REJECTED))  # no reviewer note
    with pytest.raises(IntegrityError):
        session.commit()


def test_claim_amount_must_be_positive(session: Session) -> None:
    user = add_user(session)
    session.add(
        ClaimRequest(
            employee_id=user.id,
            claim_type=ClaimType.MEAL,
            amount=Decimal("0.00"),
            receipt_date=date(2026, 1, 1),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_feedback_rating_range(session: Session) -> None:
    user = add_user(session)
    for bad in (0, 6):
        session.add(Feedback(user_id=user.id, rating=bad))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    for good in (1, 5):
        session.add(Feedback(user_id=user.id, rating=good))
    session.commit()


def test_decimal_round_trip_is_exact(session: Session) -> None:
    user = add_user(session)
    amounts = [Decimal("12.30"), Decimal("0.01"), Decimal("999999.99"), Decimal("1250.00")]
    for amount in amounts:
        session.add(
            ClaimRequest(
                employee_id=user.id,
                claim_type=ClaimType.OTHER,
                amount=amount,
                receipt_date=date(2026, 1, 1),
            )
        )
    session.commit()
    session.expire_all()
    stored = [c.amount for c in session.query(ClaimRequest).order_by(ClaimRequest.id)]
    assert stored == amounts
    assert all(isinstance(a, Decimal) for a in stored)
    assert str(stored[0]) == "12.30"
    # stored as integer minor units, never a float
    raw = session.execute(text("SELECT amount, typeof(amount) FROM claim_requests")).first()
    assert raw == (1230, "integer")


def test_money_rejects_float_and_extra_precision(session: Session) -> None:
    user = add_user(session)
    for bad in (12.3, Decimal("12.345")):
        session.add(
            ClaimRequest(
                employee_id=user.id,
                claim_type=ClaimType.OTHER,
                amount=bad,
                receipt_date=date(2026, 1, 1),
            )
        )
        with pytest.raises(StatementError):
            session.commit()
        session.rollback()


def test_half_day_counts_round_trip(session: Session) -> None:
    user = add_user(session)
    session.add(
        LeaveRequest(
            employee_id=user.id,
            leave_type=LeaveType.ANNUAL,
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 5),
            start_day_part="am",
            end_day_part="am",
            calendar_days=Decimal("0.5"),
            working_days=Decimal("0.5"),
        )
    )
    session.commit()
    session.expire_all()
    leave = session.query(LeaveRequest).one()
    assert leave.working_days == Decimal("0.5")
    assert leave.status is RequestStatus.DRAFT
    assert leave.required_approver_role is UserRole.HR_APPROVER


def test_timestamps_are_tz_aware_utc(session: Session) -> None:
    user = add_user(session)
    hk = timezone(timedelta(hours=8))
    moment = datetime(2026, 9, 25, 10, 30, tzinfo=hk)
    session.add(AuditEvent(actor_user_id=user.id, entity_type="user", entity_id=user.id,
                           event_type="x", created_at=moment))  # fmt: skip
    session.commit()
    session.expire_all()
    stored = session.query(AuditEvent).one().created_at
    assert stored.tzinfo is not None and stored.utcoffset() == timedelta(0)
    assert stored == moment
    assert stored.hour == 2  # 10:30 HKT == 02:30 UTC
    assert user.created_at.tzinfo is UTC


def test_naive_datetime_rejected(session: Session) -> None:
    user = add_user(session)
    session.add(AuditEvent(actor_user_id=user.id, entity_type="user", entity_id=user.id,
                           event_type="x", created_at=datetime(2026, 1, 1)))  # fmt: skip
    with pytest.raises(StatementError, match="Naive datetime"):
        session.commit()


def test_public_holiday_date_unique(session: Session) -> None:
    for _ in range(2):
        session.add(
            PublicHoliday(
                holiday_date=date(2026, 10, 1), name="National Day", source=HolidaySource.SEED_2026
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()


def test_polymorphic_columns_have_no_foreign_keys(db: Database) -> None:
    from app.db.models import ExternalSubmission, Notification

    for model in (ExternalSubmission, Notification, AuditEvent):
        targets = {fk.parent.name for fk in model.__table__.foreign_keys}
        assert not targets & {"request_id", "entity_id"}


def test_expected_indexes_exist(db: Database) -> None:
    from sqlalchemy import inspect

    inspector = inspect(db.engine)

    def index_columns(table: str) -> list[list[str]]:
        return [ix["column_names"] for ix in inspector.get_indexes(table)]

    assert ["employee_id", "status"] in index_columns("leave_requests")
    assert ["employee_id", "status"] in index_columns("claim_requests")
    assert ["recipient_user_id", "read_at"] in index_columns("notifications")
    assert ["entity_type", "entity_id"] in index_columns("audit_events")
    assert ["conversation_id"] in index_columns("conversation_messages")
    uniques = [u["column_names"] for u in inspector.get_unique_constraints("users")]
    assert ["email"] in uniques and ["google_subject"] in uniques
    assert ["holiday_date"] in [
        u["column_names"] for u in inspector.get_unique_constraints("public_holidays")
    ]


def test_message_json_metadata_nullable_and_round_trips(session: Session) -> None:
    from app.db.models import Conversation

    user = add_user(session)
    conv = Conversation(user_id=user.id)
    session.add(conv)
    session.flush()
    session.add_all(
        [
            ConversationMessage(conversation_id=conv.id, sender_type=SenderType.USER, content="hi"),
            ConversationMessage(
                conversation_id=conv.id,
                sender_type=SenderType.ASSISTANT,
                content="hello",
                ui_metadata_json={"type": "follow_up", "missing_fields": ["end_date"]},
            ),
        ]
    )
    session.commit()
    session.expire_all()
    first, second = conv.messages
    assert first.ui_metadata_json is None
    assert second.ui_metadata_json["missing_fields"] == ["end_date"]
