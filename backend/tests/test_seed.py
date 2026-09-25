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
    Department,
    ExternalSubmission,
    Feedback,
    LeaveEntitlement,
    LeaveRequest,
    Notification,
    PublicHoliday,
    User,
)
from app.db.session import Database
from app.domain.enums import (
    DayPart,
    HolidaySource,
    LeaveType,
    RequestStatus,
    RequestType,
    SubmissionStatus,
    UserRole,
)
from app.domain.leave import calculate_leave_days
from app.domain.transitions import can_transition
from app.seed import seed_demo_data, table_counts
from app.services.balances import (
    department_budget,
    leave_balance,
    leave_balance_after,
    team_overlap,
)
from tests.conftest import SEED_TODAY


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_exact_counts(seeded_session: Session) -> None:
    assert table_counts(seeded_session) == {
        "attachments": 0,  # nothing is uploaded in the seed
        "audit_events": 15,
        "claim_requests": 10,
        "conversation_messages": 9,
        "conversations": 3,
        "departments": 3,
        "external_submissions": 21,
        "feedback": 2,
        "leave_entitlements": 16,  # 4 requesters x 2 years x annual/sick
        "leave_requests": 10,
        "notifications": 8,
        "public_holidays": 34,
        "schema_meta": 1,
        "users": 6,
    }
    assert set(table_counts(seeded_session)) == set(Base.metadata.tables)


def by_email(session: Session) -> dict[str, User]:
    return {u.email.split(".")[0]: u for u in session.scalars(select(User))}


def test_users(seeded_session: Session) -> None:
    users = seeded_session.scalars(select(User).order_by(User.id)).all()
    assert [u.display_name for u in users] == [
        "Amy Lau",
        "Ben Chow",
        "Cathy Ng",
        "Daniel Wong",
        "Helen Yeung",
        "Eva Cheung",
    ]
    roles = Counter(u.role for u in users)
    assert roles == {UserRole.EMPLOYEE: 3, UserRole.HR_APPROVER: 2, UserRole.FINANCE_APPROVER: 1}
    assert all(u.is_active for u in users)
    assert all(u.email.endswith("@example.com") for u in users)
    assert all(re.fullmatch(r"mock-google-sub-\d{3}", u.google_subject) for u in users)


def test_departments_titles_and_approvers(seeded_session: Session) -> None:
    people = by_email(seeded_session)
    assert {k: (u.department.name, u.role.value, u.job_title) for k, u in people.items()} == {
        "amy": ("IT", "employee", "Software Engineer"),
        "ben": ("IT", "employee", "Software Engineer"),
        "cathy": ("HR", "hr_approver", "HR Business Partner (IT)"),
        "daniel": ("HR", "employee", "HR Officer"),
        "helen": ("HR", "hr_approver", "HR Manager"),
        "eva": ("Finance", "finance_approver", "Finance Manager"),
    }
    routing = {
        k: (
            u.leave_approver_user_id and seeded_session.get(User, u.leave_approver_user_id).email,
            u.claim_approver_user_id and seeded_session.get(User, u.claim_approver_user_id).email,
        )
        for k, u in people.items()
    }
    cathy, helen, eva = (people[k].email for k in ("cathy", "helen", "eva"))
    assert routing == {
        "amy": (cathy, eva),
        "ben": (cathy, eva),
        "cathy": (helen, eva),
        "daniel": (helen, eva),
        "helen": (None, None),  # out of the PoC scope: no chat for Helen and Eva
        "eva": (None, None),
    }
    assert {k for k, u in people.items() if u.can_request} == {"amy", "ben", "cathy", "daniel"}
    assert {k: u.approves for k, u in people.items() if u.approves} == {
        "cathy": "leave",
        "helen": "leave",
        "eva": "claim",
    }


def test_department_limits_and_entitlements(seeded_session: Session) -> None:
    limits = {d.name: d.claim_limit_amount for d in seeded_session.scalars(select(Department))}
    assert limits == {
        "IT": Decimal("60000.00"),
        "HR": Decimal("30000.00"),
        "Finance": Decimal("30000.00"),
    }
    people = by_email(seeded_session)
    rows = {
        (k, e.year, e.leave_type.value): e.entitled_days
        for e in seeded_session.scalars(select(LeaveEntitlement))
        for k, u in people.items()
        if u.id == e.user_id
    }
    assert {y for _, y, _ in rows} == {2026, 2027}
    for year in (2026, 2027):
        assert rows[("amy", year, "annual")] == Decimal("15.0")
        assert rows[("amy", year, "sick")] == Decimal("10.0")
        assert rows[("ben", year, "annual")] == Decimal("18.0")
        assert rows[("daniel", year, "sick")] == Decimal("12.0")
        assert rows[("cathy", year, "annual")] == Decimal("15.0")
    assert not {k for k, _, _ in rows} & {"helen", "eva"}  # they file nothing in the PoC


def test_leave_status_mix_and_review_fields(seeded_session: Session) -> None:
    leaves = seeded_session.scalars(select(LeaveRequest).order_by(LeaveRequest.id)).all()
    requesters = {u.id for u in by_email(seeded_session).values() if u.can_request}
    assert len(leaves) == 10
    statuses = Counter(x.status for x in leaves)
    assert statuses[RequestStatus.PENDING_APPROVAL] == 2
    assert statuses[RequestStatus.REJECTED] <= 2
    assert statuses[RequestStatus.APPROVED] + statuses[RequestStatus.REJECTED] == 8
    pending = [x for x in leaves if x.status is RequestStatus.PENDING_APPROVAL]
    assert all(x.start_date > SEED_TODAY for x in pending)
    for x in leaves:
        assert x.employee_id in requesters  # only the four requesters file anything
        assert x.required_approver_role is UserRole.HR_APPROVER
        assert x.approver_user_id is not None and x.approver_user_id != x.employee_id
        assert x.submitted_at is not None
        if x.status in (RequestStatus.APPROVED, RequestStatus.REJECTED):
            assert x.reviewed_by_user_id == x.approver_user_id and x.reviewed_at > x.submitted_at
        if x.status is RequestStatus.REJECTED:
            assert x.reviewer_note  # the seed rejections have one; the note is optional in general
    assert any(
        x.status is RequestStatus.APPROVED and not x.reviewer_note for x in leaves
    )  # optional note
    history = leaves[4:8] + leaves[9:]
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
    fin = by_email(seeded_session)["eva"]
    requesters = {u.id for u in by_email(seeded_session).values() if u.can_request}
    assert len(claims) == 10
    assert Counter(c.status for c in claims)[RequestStatus.PENDING_APPROVAL] == 2
    for c in claims:
        assert c.currency == "HKD" and c.amount > 0
        assert c.required_approver_role is UserRole.FINANCE_APPROVER
        assert c.receipt_date < SEED_TODAY and c.submitted_at is not None
        assert c.employee_id in requesters and c.approver_user_id == fin.id
        if c.status in (RequestStatus.APPROVED, RequestStatus.REJECTED):
            assert c.reviewed_by_user_id == c.approver_user_id == fin.id
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


def test_audit_decisions_are_by_the_assigned_approver(seeded_session: Session) -> None:
    decisions = seeded_session.scalars(
        select(AuditEvent).where(
            AuditEvent.event_type.in_(["request.approved", "request.rejected"])
        )
    ).all()
    assert len(decisions) == 2
    for e in decisions:
        model = LeaveRequest if e.entity_type == "leave_request" else ClaimRequest
        assert e.actor_user_id == seeded_session.get(model, e.entity_id).approver_user_id


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
    assert count(seeded_session, Notification) == 8
    ratings = [f.rating for f in seeded_session.scalars(select(Feedback))]
    assert len(ratings) == 2 and all(1 <= r <= 5 for r in ratings)


def test_notifications_match_pending_and_decided_requests(seeded_session: Session) -> None:
    leaves = {r.id: r for r in seeded_session.scalars(select(LeaveRequest))}
    claims = {r.id: r for r in seeded_session.scalars(select(ClaimRequest))}
    notes = seeded_session.scalars(select(Notification)).all()
    for n in notes:
        req = (leaves if n.request_type is RequestType.LEAVE else claims)[n.request_id]
        if n.event_type == "request.submitted":
            # pending items notify the ASSIGNED approver only, unread
            assert req.status is RequestStatus.PENDING_APPROVAL
            assert n.recipient_user_id == req.approver_user_id and n.read_at is None
        else:
            # decided items notify the requester
            assert n.event_type == f"request.{req.status.value}"
            assert n.recipient_user_id == req.employee_id
    pending = [
        r
        for r in [*leaves.values(), *claims.values()]
        if r.status is RequestStatus.PENDING_APPROVAL
    ]
    submitted = [n for n in notes if n.event_type == "request.submitted"]
    assert len(submitted) == len(pending) == 4
    people = by_email(seeded_session)
    per_recipient = Counter(n.recipient_user_id for n in submitted)
    assert per_recipient == {
        people["cathy"].id: 1,  # Amy's leave
        people["helen"].id: 1,  # Daniel's leave
        people["eva"].id: 2,  # both claims
    }


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


def test_showcase_pending_requests_use_the_new_features(seeded_session: Session) -> None:
    """The pending items demonstrate the Phase 3 behaviour, measured with the real services."""
    year = SEED_TODAY.year
    people = by_email(seeded_session)
    leaves = {
        x.employee_id: x
        for x in seeded_session.scalars(
            select(LeaveRequest).where(LeaveRequest.status == RequestStatus.PENDING_APPROVAL)
        )
    }
    # 1. Amy's pending IT leave overlaps a colleague's APPROVED leave in the same department
    amy_leave = leaves[people["amy"].id]
    overlap = team_overlap(seeded_session, amy_leave)
    assert [(o.employee, o.status) for o in overlap] == [("Ben Chow", RequestStatus.APPROVED)]
    # 2. Daniel's pending annual leave is above his annual balance (shown, not blocking)
    daniel_leave = leaves[people["daniel"].id]
    assert daniel_leave.leave_type is LeaveType.ANNUAL
    after = leave_balance_after(
        seeded_session,
        people["daniel"].id,
        year,
        LeaveType.ANNUAL,
        daniel_leave.working_days,
        exclude_request_id=daniel_leave.id,
    )
    assert after is not None and after.over_limit and after.remaining_after_days < 0
    assert (
        leave_balance(seeded_session, people["daniel"].id, year, LeaveType.ANNUAL).remaining_days
        > 0
    )
    # 3. a pending claim pushes its department above the claim limit
    pending_claims = seeded_session.scalars(
        select(ClaimRequest).where(ClaimRequest.status == RequestStatus.PENDING_APPROVAL)
    ).all()
    over = []
    for claim in pending_claims:
        employee = seeded_session.get(User, claim.employee_id)
        budget = department_budget(
            seeded_session, employee.department_id, claim.receipt_date.year, claim.id
        )
        if budget.budget_after(claim.amount).over_limit:
            over.append((employee.department.name, claim.id))
    assert [dept for dept, _ in over] == ["HR"]
    # ...while nothing else is over: Amy's own pending claim and every other balance are fine
    for claim in pending_claims:
        employee = seeded_session.get(User, claim.employee_id)
        if employee.department.name == "IT":
            budget = department_budget(seeded_session, employee.department_id, year, claim.id)
            assert not budget.budget_after(claim.amount).over_limit


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
        assert count(s, LeaveRequest) == 10  # no entitlement rows needed to seed later years
    db.dispose()
