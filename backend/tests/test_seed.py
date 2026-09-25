import re
from collections import Counter
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    AuditEvent,
    ClaimRequest,
    Conversation,
    ExternalSubmission,
    Feedback,
    LeaveRequest,
    Notification,
    PublicHoliday,
    User,
)
from app.db.session import Database
from app.domain.enums import (
    DayPart,
    HolidaySource,
    RequestStatus,
    RequestType,
    SubmissionStatus,
    UserRole,
)
from app.domain.leave import calculate_leave_days
from app.domain.transitions import can_transition
from app.seed import seed_demo_data, table_counts
from tests.conftest import SEED_TODAY


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_exact_counts(seeded_session: Session) -> None:
    assert table_counts(seeded_session) == {
        "audit_events": 15,
        "claim_requests": 10,
        "conversation_messages": 9,
        "conversations": 3,
        "external_submissions": 21,
        "feedback": 2,
        "leave_requests": 10,
        "notifications": 6,
        "public_holidays": 34,
        "users": 5,
    }
    assert set(table_counts(seeded_session)) == set(Base.metadata.tables)


def test_users(seeded_session: Session) -> None:
    users = seeded_session.scalars(select(User).order_by(User.id)).all()
    roles = Counter(u.role for u in users)
    assert roles == {UserRole.EMPLOYEE: 3, UserRole.HR_APPROVER: 1, UserRole.FINANCE_APPROVER: 1}
    assert all(u.is_active for u in users)
    assert all(u.email.endswith("@example.com") for u in users)
    assert all(re.fullmatch(r"mock-google-sub-\d{3}", u.google_subject) for u in users)
    assert [u.role for u in users[:3]] == [UserRole.EMPLOYEE] * 3


def test_leave_status_mix_and_review_fields(seeded_session: Session) -> None:
    leaves = seeded_session.scalars(select(LeaveRequest).order_by(LeaveRequest.id)).all()
    hr = seeded_session.scalars(select(User).where(User.role == UserRole.HR_APPROVER)).one()
    assert len(leaves) == 10
    statuses = Counter(x.status for x in leaves)
    assert statuses[RequestStatus.PENDING_APPROVAL] == 2
    assert statuses[RequestStatus.REJECTED] <= 2
    assert statuses[RequestStatus.APPROVED] + statuses[RequestStatus.REJECTED] == 8
    pending = [x for x in leaves if x.status is RequestStatus.PENDING_APPROVAL]
    assert all(x.start_date > SEED_TODAY for x in pending)
    for x in leaves:
        assert x.required_approver_role is UserRole.HR_APPROVER
        assert x.submitted_at is not None
        if x.status in (RequestStatus.APPROVED, RequestStatus.REJECTED):
            assert x.reviewed_by_user_id == hr.id and x.reviewed_at > x.submitted_at
        if x.status is RequestStatus.REJECTED:
            assert x.reviewer_note
    history = leaves[4:]
    assert all(x.end_date < SEED_TODAY for x in history)
    assert sum(x.status is RequestStatus.REJECTED for x in history) <= 1


def test_half_day_leave_rows_have_correct_days(seeded_session: Session) -> None:
    leaves = seeded_session.scalars(select(LeaveRequest)).all()
    holidays = set(seeded_session.scalars(select(PublicHoliday.holiday_date)))
    single_am = [x for x in leaves if x.start_date == x.end_date and x.start_day_part is DayPart.AM]
    multi_pm = [x for x in leaves if x.start_date != x.end_date and x.start_day_part is DayPart.PM]
    assert single_am and multi_pm
    assert single_am[0].working_days == Decimal("0.5")
    assert multi_pm[0].working_days % 1 == Decimal("0.5")
    for x in leaves:
        expected = calculate_leave_days(
            x.start_date, x.end_date, x.start_day_part, x.end_day_part, holidays
        )
        assert (x.calendar_days, x.working_days) == (expected.calendar_days, expected.working_days)
    assert any(x.working_days < x.calendar_days for x in leaves)  # weekends were skipped


def test_claims(seeded_session: Session) -> None:
    claims = seeded_session.scalars(select(ClaimRequest).order_by(ClaimRequest.id)).all()
    fin = seeded_session.scalars(select(User).where(User.role == UserRole.FINANCE_APPROVER)).one()
    assert len(claims) == 10
    assert Counter(c.status for c in claims)[RequestStatus.PENDING_APPROVAL] == 2
    for c in claims:
        assert c.currency == "HKD" and c.amount > 0
        assert c.required_approver_role is UserRole.FINANCE_APPROVER
        assert c.receipt_date < SEED_TODAY and c.submitted_at is not None
        if c.status in (RequestStatus.APPROVED, RequestStatus.REJECTED):
            assert c.reviewed_by_user_id == fin.id
        if c.status is RequestStatus.REJECTED:
            assert c.reviewer_note
    assert sum(c.status is RequestStatus.REJECTED for c in claims[4:]) <= 1
    assert all(c.amount == c.amount.quantize(Decimal("0.01")) for c in claims)


def test_audit_transitions_all_legal_and_cover_key_events(seeded_session: Session) -> None:
    events = seeded_session.scalars(select(AuditEvent)).all()
    assert 12 <= len(events) <= 16
    for e in events:
        if e.from_status is None and e.to_status is None:
            continue
        if e.from_status is None:
            assert e.to_status == RequestStatus.DRAFT  # creation
            continue
        assert can_transition(RequestStatus(e.from_status), RequestStatus(e.to_status)), (
            e.event_type
        )
    types = {e.event_type for e in events}
    assert {
        "request.created",
        "request.confirmed",
        "submission.succeeded",
        "submission.failed",
        "request.approved",
        "request.rejected",
    } <= types


def test_failed_submission_then_retry(seeded_session: Session) -> None:
    failed = seeded_session.scalars(
        select(ExternalSubmission).where(ExternalSubmission.status == SubmissionStatus.FAILED)
    ).all()
    assert len(failed) == 1 and failed[0].http_status in (429, 500)
    row = failed[0]
    claim = seeded_session.get(ClaimRequest, row.request_id)
    assert row.request_type is RequestType.CLAIM
    assert claim.status is RequestStatus.PENDING_APPROVAL
    later = seeded_session.scalars(
        select(ExternalSubmission).where(
            ExternalSubmission.request_id == row.request_id,
            ExternalSubmission.request_type == RequestType.CLAIM,
            ExternalSubmission.status == SubmissionStatus.SUCCESS,
        )
    ).one()
    assert later.submitted_at > row.submitted_at


def test_external_submissions_are_fake(seeded_session: Session) -> None:
    rows = seeded_session.scalars(select(ExternalSubmission)).all()
    assert all(r.provider == "reqres" for r in rows)
    ok = [r for r in rows if r.status is SubmissionStatus.SUCCESS]
    assert len(ok) == 20
    assert all(r.external_reference_id.startswith("mock-ref-") for r in ok)
    assert all(r.response_summary_json["note"] == "fictional seed data" for r in ok)


def test_polymorphic_references_point_at_real_rows(seeded_session: Session) -> None:
    ids = {
        RequestType.LEAVE: set(seeded_session.scalars(select(LeaveRequest.id))),
        RequestType.CLAIM: set(seeded_session.scalars(select(ClaimRequest.id))),
    }
    for row in seeded_session.scalars(select(ExternalSubmission)):
        assert row.request_id in ids[row.request_type]
    for n in seeded_session.scalars(select(Notification)):
        assert n.request_id in ids[n.request_type]
    for e in seeded_session.scalars(select(AuditEvent)):
        kind = RequestType.LEAVE if e.entity_type == "leave_request" else RequestType.CLAIM
        assert e.entity_id in ids[kind]


def test_conversations_notifications_feedback(seeded_session: Session) -> None:
    convs = seeded_session.scalars(select(Conversation)).all()
    assert len(convs) == 3
    assert all(2 <= len(c.messages) <= 5 for c in convs)
    assert {c.messages[0].sender_type.value for c in convs} == {"user"}
    assert any(m.ui_metadata_json for c in convs for m in c.messages)
    assert {c.active_request_type for c in convs} >= {RequestType.CLAIM, RequestType.LEAVE}
    assert count(seeded_session, Notification) == 6
    hr = seeded_session.scalars(select(User).where(User.role == UserRole.HR_APPROVER)).one()
    hr_notes = seeded_session.scalars(
        select(Notification).where(Notification.recipient_user_id == hr.id)
    ).all()
    assert len(hr_notes) == 2 and all(n.read_at is None for n in hr_notes)
    ratings = [f.rating for f in seeded_session.scalars(select(Feedback))]
    assert len(ratings) == 2 and all(1 <= r <= 5 for r in ratings)


def test_holidays_2026_and_2027(seeded_session: Session) -> None:
    rows = seeded_session.scalars(select(PublicHoliday)).all()
    by_year = Counter(h.holiday_date.year for h in rows)
    assert by_year == {2026: 17, 2027: 17}
    assert all(h.source is HolidaySource.SEED_2026 for h in rows)
    assert {h.source_updated_at.date() for h in rows} == {date(2026, 5, 15)}
    national = seeded_session.scalars(
        select(PublicHoliday).where(PublicHoliday.holiday_date == date(2026, 10, 1))
    ).one()
    assert "National Day" in national.name


def test_seed_is_idempotent(seeded: Database) -> None:
    with seeded.session_factory() as s:
        before = table_counts(s)
        result = seed_demo_data(s, today=SEED_TODAY)
        assert result.seeded is False
        assert table_counts(s) == before


def test_seed_is_deterministic_for_a_given_today() -> None:
    def snapshot() -> list[tuple]:
        db = Database("sqlite:///:memory:")
        db.init_db()
        with db.session_factory() as s:
            seed_demo_data(s, today=SEED_TODAY)
            rows = [
                (x.start_date, x.end_date, x.working_days, x.status)
                for x in s.scalars(select(LeaveRequest).order_by(LeaveRequest.id))
            ]
            rows += [
                (c.amount, c.receipt_date, c.status)
                for c in s.scalars(select(ClaimRequest).order_by(ClaimRequest.id))
            ]
        db.dispose()
        return rows

    assert snapshot() == snapshot()


def test_no_real_looking_data(seeded_session: Session) -> None:
    text_blobs: list[str] = []
    for user in seeded_session.scalars(select(User)):
        text_blobs += [user.email, user.display_name, user.google_subject]
    for model in (LeaveRequest, ClaimRequest):
        text_blobs += [r.reviewer_note or "" for r in seeded_session.scalars(select(model))]
    for c in seeded_session.scalars(select(Conversation)):
        text_blobs += [m.content for m in c.messages]
    joined = "\n".join(text_blobs).lower()
    assert "scmp.com" not in joined and "@gmail" not in joined
    for user in seeded_session.scalars(select(User)):
        assert re.fullmatch(r"[a-z]+\.[a-z]+@example\.com", user.email)
    for r in seeded_session.scalars(select(ExternalSubmission)):
        assert "token" not in str(r.response_summary_json).lower()


def test_seed_works_when_no_holidays_cover_the_year() -> None:
    db = Database("sqlite:///:memory:")
    db.init_db()
    with db.session_factory() as s:
        assert seed_demo_data(s, today=date(2030, 3, 15)).seeded
        assert count(s, LeaveRequest) == 10
    db.dispose()
