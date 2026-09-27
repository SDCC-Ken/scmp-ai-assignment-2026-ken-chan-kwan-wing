"""Fictional demo data. Deterministic for a given ``today``; a no-op when users exist.

Everything here is invented (``@example.com`` addresses, made-up names, short notes). It
contains no real SCMP, employee, HR or financial data. Requests reviewed long ago have an
``external_submissions`` row but no audit rows: the audit trail is populated for a
representative subset (see ``_seed_audit``) so the demo stays small.

Phase 3 organisation (see docs/limits-and-routing.md): three departments with a claim limit,
six users with a department, a job title and one configured approver per request type, and
leave entitlements for this year and next. The pending requests are chosen to show the new
features: a team overlap, a leave above the annual balance and a claim above its department's
limit.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Attachment,
    AuditEvent,
    ClaimRequest,
    Conversation,
    ConversationMessage,
    Department,
    ExternalSubmission,
    Feedback,
    LeaveEntitlement,
    LeaveRequest,
    Notification,
    User,
)
from app.domain.clock import today_hk
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
from app.domain.leave import calculate_leave_days, is_working_day
from app.domain.roles import required_approver_role
from app.services.audit import create_notification, record_audit, record_external_submission
from app.services.holidays import latest_stamp, parse_ics, upsert_holidays
from app.services.routing import ApproverProblem, resolve_approver

BUNDLED_ICS = Path(__file__).parent / "data" / "hk_public_holidays_1823.ics"
SEED_HOLIDAY_YEARS = frozenset({2026, 2027})

# This is deliberately separate from the ordinary seed fixtures.  The presentation can be
# replayed against a long-lived local database, so it needs one known, pending request that
# no earlier live-demo run can have changed.
PRESENTATION_CANCEL_START = date(2026, 11, 10)
PRESENTATION_CANCEL_END = date(2026, 11, 12)
PRESENTATION_APPROVE_START = date(2026, 12, 9)
PRESENTATION_APPROVE_END = date(2026, 12, 11)
PRESENTATION_REJECT_START = date(2026, 12, 16)
PRESENTATION_REJECT_END = date(2026, 12, 17)
PRESENTATION_EMPLOYEE_EMAIL = "presentation.employee@example.com"
PRESENTATION_APPROVER_EMAIL = "presentation.approver@example.com"

S = RequestStatus


@dataclass
class SeedResult:
    seeded: bool
    counts: dict[str, int] = field(default_factory=dict)


def _at(today: date, days: int, hour: int = 3, minute: int = 0) -> datetime:
    """UTC datetime ``days`` from ``today`` at hour:minute."""
    base = datetime(today.year, today.month, today.day, tzinfo=UTC)
    return base + timedelta(days=days, hours=hour, minutes=minute)


def _next_wd(day: date, holidays: set[date]) -> date:
    while not is_working_day(day, holidays):
        day += timedelta(days=1)
    return day


def _prev_wd(day: date, holidays: set[date]) -> date:
    while not is_working_day(day, holidays):
        day -= timedelta(days=1)
    return day


def _span_end(start: date, working_days: int, holidays: set[date]) -> date:
    """The last day of a leave that starts on ``start`` (a working day) and covers exactly
    ``working_days`` full working days."""
    end, counted = start, 1
    while counted < working_days:
        end += timedelta(days=1)
        if is_working_day(end, holidays):
            counted += 1
    return end


def _seed_holidays(session: Session) -> set[date]:
    events = parse_ics(BUNDLED_ICS.read_text(encoding="utf-8"))
    stamp = latest_stamp(events)
    wanted = [e for e in events if e.holiday_date.year in SEED_HOLIDAY_YEARS]
    upsert_holidays(session, wanted, HolidaySource.SEED_2026, stamp)
    return {e.holiday_date for e in wanted}


# (key, name, department, role, job title, leave approver key, claim approver key)
_USERS: list[tuple[str, str, str, UserRole, str, str | None, str | None]] = [
    ("amy", "Amy Lau", "IT", UserRole.EMPLOYEE, "Software Engineer", "cathy", "eva"),
    ("ben", "Ben Chow", "IT", UserRole.EMPLOYEE, "Software Engineer", "cathy", "eva"),
    ("cathy", "Cathy Ng", "HR", UserRole.HR_APPROVER, "HR Business Partner (IT)", "helen", "eva"),
    ("daniel", "Daniel Wong", "HR", UserRole.EMPLOYEE, "HR Officer", "helen", "eva"),
    ("helen", "Helen Yeung", "HR", UserRole.HR_APPROVER, "HR Manager", None, None),
    ("eva", "Eva Cheung", "Finance", UserRole.FINANCE_APPROVER, "Finance Manager", None, None),
]
_DEPARTMENTS = {
    "IT": Decimal("60000.00"),
    "HR": Decimal("30000.00"),
    "Finance": Decimal("30000.00"),
}
# key -> (annual, sick); Helen and Eva get no entitlement (they file nothing in the PoC).
_ENTITLEMENTS = {
    "amy": (Decimal("15"), Decimal("10")),
    "ben": (Decimal("18"), Decimal("10")),
    "cathy": (Decimal("15"), Decimal("10")),
    "daniel": (Decimal("15"), Decimal("12")),
}


def _seed_departments(session: Session) -> dict[str, Department]:
    departments = {
        name: Department(
            name=name,
            claim_limit_amount=limit,
            created_at=datetime(2026, 1, 5, 2, 0, tzinfo=UTC),
        )
        for name, limit in _DEPARTMENTS.items()
    }
    session.add_all(departments.values())
    session.flush()
    return departments


def _seed_users(session: Session, departments: dict[str, Department]) -> dict[str, User]:
    users: dict[str, User] = {}
    for index, (key, name, dept, role, title, _leave, _claim) in enumerate(_USERS, start=1):
        first, last = name.lower().split()
        users[key] = User(
            google_subject=f"mock-google-sub-{index:03d}",
            email=f"{first}.{last}@example.com",
            display_name=name,
            role=role,
            is_active=True,
            department_id=departments[dept].id,
            job_title=title,
            created_at=datetime(2026, 1, 5, 2, 0, tzinfo=UTC),
        )
    session.add_all(users.values())
    session.flush()
    for key, _name, _dept, _role, _title, leave_key, claim_key in _USERS:  # needs the ids
        users[key].leave_approver_user_id = users[leave_key].id if leave_key else None
        users[key].claim_approver_user_id = users[claim_key].id if claim_key else None
    session.flush()
    return users


def _seed_entitlements(session: Session, users: dict[str, User], today: date) -> None:
    """Annual and sick days for this year and next (the Phase 3 defaults; see the docs)."""
    for key, (annual, sick) in _ENTITLEMENTS.items():
        for year in (today.year, today.year + 1):
            for leave_type, days in ((LeaveType.ANNUAL, annual), (LeaveType.SICK, sick)):
                session.add(
                    LeaveEntitlement(
                        user_id=users[key].id, year=year, leave_type=leave_type, entitled_days=days
                    )
                )
    session.flush()


@dataclass
class _Leave:
    key: str
    employee: str
    leave_type: LeaveType
    start: date
    end: date
    status: RequestStatus
    submitted: datetime
    start_part: DayPart = DayPart.FULL
    end_part: DayPart = DayPart.FULL
    reviewed: datetime | None = None
    note: str | None = None


@dataclass
class _Claim:
    key: str
    employee: str
    claim_type: ClaimType
    amount: Decimal
    receipt: date
    status: RequestStatus
    submitted: datetime
    reviewed: datetime | None = None
    note: str | None = None


def _leave_specs(today: date, hol: set[date]) -> list[_Leave]:
    def hist(
        key: str, employee: str, ltype: LeaveType, start: date, end: date, **kw: Any
    ) -> _Leave:
        submitted = _at(today, (start - today).days - 14)
        return _Leave(
            key,
            employee,
            ltype,
            start,
            end,
            kw.pop("status", S.APPROVED),
            submitted,
            reviewed=submitted + timedelta(days=1, hours=3),
            **kw,
        )

    s1 = _next_wd(today + timedelta(days=14), hol)  # Amy: pending, overlaps Ben's approved leave
    s2 = _next_wd(today + timedelta(days=8), hol)  # Daniel: pending, above his annual balance
    s3 = _next_wd(today + timedelta(days=20), hol)
    s4 = _next_wd(today + timedelta(days=3), hol)
    s5 = _prev_wd(today - timedelta(days=40), hol)
    s6 = _prev_wd(today - timedelta(days=33), hol)
    s8 = _prev_wd(today - timedelta(days=70), hol)
    s9 = _prev_wd(today - timedelta(days=90), hol)
    s10 = _prev_wd(today - timedelta(days=100), hol)
    s11 = _next_wd(s1 + timedelta(days=1), hol)  # Ben: approved, inside Amy's pending dates
    return [
        _Leave(
            "L1",
            "amy",
            LeaveType.ANNUAL,
            s1,
            _span_end(s1, 4, hol),
            S.PENDING_APPROVAL,
            _at(today, -1),
        ),
        _Leave(
            "L2",
            "daniel",
            LeaveType.ANNUAL,
            s2,
            _span_end(s2, 6, hol),  # 10 approved days (L7) + 6 requested > 15 entitled
            S.PENDING_APPROVAL,
            _at(today, -2),
        ),
        _Leave(
            "L3",
            "cathy",
            LeaveType.ANNUAL,
            s3,
            _span_end(s3, 2, hol),
            S.APPROVED,
            _at(today, -11),
            reviewed=_at(today, -10, 6),
            note="Approved. Please hand over your open cases before you go.",
        ),
        _Leave(
            "L4",
            "ben",
            LeaveType.UNPAID,
            s4,
            _next_wd(s4 + timedelta(days=1), hol),
            S.REJECTED,
            _at(today, -4),
            reviewed=_at(today, -2, 6),
            note="Team is short-staffed that week; please pick another date.",
        ),
        hist(
            "L5",
            "amy",
            LeaveType.ANNUAL,
            s5,
            _next_wd(s5 + timedelta(days=3), hol),
            start_part=DayPart.PM,
            note="Enjoy your break.",
        ),
        hist("L6", "ben", LeaveType.SICK, s6, s6),
        hist("L7", "daniel", LeaveType.ANNUAL, s9, _span_end(s9, 10, hol)),
        hist("L8", "amy", LeaveType.PERSONAL, s8, s8, start_part=DayPart.AM, end_part=DayPart.AM),
        _Leave(
            "L9",
            "ben",
            LeaveType.ANNUAL,
            s11,
            _span_end(s11, 2, hol),
            S.APPROVED,
            _at(today, -6),
            reviewed=_at(today, -5, 6),
        ),
        hist(
            "L10",
            "amy",
            LeaveType.UNPAID,
            s10,
            s10,
            status=S.REJECTED,
            note="Insufficient notice given for the requested date.",
        ),
    ]


def _claim_specs(today: date) -> list[_Claim]:
    def hist(key: str, employee: str, ctype: ClaimType, amount: str, age: int, **kw: Any) -> _Claim:
        receipt = today - timedelta(days=age)
        submitted = _at(today, -age + 2)
        return _Claim(
            key,
            employee,
            ctype,
            Decimal(amount),
            receipt,
            kw.pop("status", S.APPROVED),
            submitted,
            reviewed=submitted + timedelta(days=1, hours=3),
            **kw,
        )

    return [
        _Claim(
            "C1",
            "amy",
            ClaimType.TRAVEL,
            Decimal("268.50"),
            today - timedelta(days=3),
            S.PENDING_APPROVAL,
            _at(today, -2),
        ),
        # HR has 22,141.05 approved this year against a 30,000.00 limit: this pushes it over.
        _Claim(
            "C2",
            "daniel",
            ClaimType.TRAINING,
            Decimal("9800.00"),
            today - timedelta(days=5),
            S.PENDING_APPROVAL,
            _at(today, -4, 3, 2),
        ),
        _Claim(
            "C3",
            "cathy",
            ClaimType.TRAINING,
            Decimal("21500.00"),
            today - timedelta(days=14),
            S.APPROVED,
            _at(today, -12),
            reviewed=_at(today, -11, 6),
            note="Approved within the training plan.",
        ),
        _Claim(
            "C4",
            "ben",
            ClaimType.TRAINING,
            Decimal("3800.00"),
            today - timedelta(days=20),
            S.REJECTED,
            _at(today, -9),
            reviewed=_at(today, -8, 6),
            note="Receipt is missing the vendor name; please resubmit with a full receipt.",
        ),
        hist("C5", "amy", ClaimType.MEAL, "45.90", 45),
        hist("C6", "cathy", ClaimType.TRAVEL, "512.30", 60),
        hist("C7", "ben", ClaimType.OTHER, "199.00", 75),
        hist("C8", "amy", ClaimType.TRAINING, "2400.00", 95),
        hist("C9", "cathy", ClaimType.MEAL, "128.75", 110),
        hist(
            "C10",
            "ben",
            ClaimType.EQUIPMENT,
            "899.99",
            130,
            status=S.REJECTED,
            note="Duplicate of an earlier claim.",
        ),
    ]


def _approver_of(session: Session, user: User, request_type: RequestType) -> User:
    approver = resolve_approver(session, user, request_type)
    if isinstance(approver, ApproverProblem):  # a seed bug, never user input
        raise RuntimeError(f"Seed data has no valid {request_type.value} approver: {approver}")
    return approver


def _seed_requests(
    session: Session, users: dict[str, User], today: date, hol: set[date]
) -> tuple[dict[str, LeaveRequest], dict[str, ClaimRequest]]:
    leaves: dict[str, LeaveRequest] = {}
    for spec in _leave_specs(today, hol):
        days = calculate_leave_days(spec.start, spec.end, spec.start_part, spec.end_part, hol)
        approver = _approver_of(session, users[spec.employee], RequestType.LEAVE)
        leaves[spec.key] = LeaveRequest(
            employee_id=users[spec.employee].id,
            leave_type=spec.leave_type,
            start_date=spec.start,
            end_date=spec.end,
            start_day_part=spec.start_part,
            end_day_part=spec.end_part,
            calendar_days=days.calendar_days,
            working_days=days.working_days,
            status=spec.status,
            required_approver_role=required_approver_role(RequestType.LEAVE),
            approver_user_id=approver.id,
            submitted_at=spec.submitted,
            reviewed_by_user_id=approver.id if spec.reviewed else None,
            reviewed_at=spec.reviewed,
            reviewer_note=spec.note,
            created_at=spec.submitted - timedelta(minutes=10),
            updated_at=spec.reviewed or spec.submitted,
        )
    claims: dict[str, ClaimRequest] = {}
    for cspec in _claim_specs(today):
        approver = _approver_of(session, users[cspec.employee], RequestType.CLAIM)
        claims[cspec.key] = ClaimRequest(
            employee_id=users[cspec.employee].id,
            claim_type=cspec.claim_type,
            amount=cspec.amount,
            currency="HKD",
            receipt_date=cspec.receipt,
            status=cspec.status,
            required_approver_role=required_approver_role(RequestType.CLAIM),
            approver_user_id=approver.id,
            submitted_at=cspec.submitted,
            reviewed_by_user_id=approver.id if cspec.reviewed else None,
            reviewed_at=cspec.reviewed,
            reviewer_note=cspec.note,
            created_at=cspec.submitted - timedelta(minutes=10),
            updated_at=cspec.reviewed or cspec.submitted,
        )
    session.add_all([*leaves.values(), *claims.values()])
    session.flush()
    return leaves, claims


def _seed_submissions(
    session: Session, leaves: dict[str, LeaveRequest], claims: dict[str, ClaimRequest]
) -> None:
    """One fake success per submitted request, plus a 429 failure before C1's retry."""
    for request in [*leaves.values(), *claims.values()]:
        if request.request_type is RequestType.CLAIM and request is claims["C1"]:
            record_external_submission(
                session,
                request_type=RequestType.CLAIM,
                request_id=request.id,
                status=SubmissionStatus.FAILED,
                http_status=429,
                response_summary={"note": "fictional seed data"},
                error_message="Too Many Requests (simulated)",
                submitted_at=request.submitted_at - timedelta(minutes=2),
            )
        ref = f"mock-ref-{request.request_type.value}-{request.id:04d}"
        record_external_submission(
            session,
            request_type=request.request_type,
            request_id=request.id,
            status=SubmissionStatus.SUCCESS,
            http_status=201,
            external_reference_id=ref,
            response_summary={"id": ref, "note": "fictional seed data"},
            submitted_at=request.submitted_at,
        )


def _seed_audit(
    session: Session,
    users: dict[str, User],
    leaves: dict[str, LeaveRequest],
    claims: dict[str, ClaimRequest],
) -> None:
    """15 events for four showcase requests (L1, C1 with a 429 retry, L3 approved, C4 rejected)."""

    def flow(entity_type: str, req: Any, owner: User, *, failed_first: bool = False) -> None:
        eid, sub = req.id, req.submitted_at
        common = {"entity_type": entity_type, "entity_id": eid}
        record_audit(
            session,
            **common,
            event_type="request.created",
            actor_user_id=owner.id,
            to_status=S.DRAFT,
            metadata={"approver_user_id": req.approver_user_id},
            created_at=sub - timedelta(minutes=10),
        )
        record_audit(
            session,
            **common,
            event_type="request.confirmed",
            actor_user_id=owner.id,
            metadata={"confirmed_by": "employee"},
            created_at=sub - timedelta(minutes=5),
        )
        if failed_first:
            record_audit(
                session,
                **common,
                event_type="submission.failed",
                actor_user_id=None,
                from_status=S.DRAFT,
                to_status=S.SUBMISSION_FAILED,
                metadata={"http_status": 429, "attempt": 1},
                created_at=sub - timedelta(minutes=2),
            )
            record_audit(
                session,
                **common,
                event_type="submission.succeeded",
                actor_user_id=None,
                from_status=S.SUBMISSION_FAILED,
                to_status=S.PENDING_APPROVAL,
                metadata={"http_status": 201, "attempt": 2},
                created_at=sub,
            )
        else:
            record_audit(
                session,
                **common,
                event_type="submission.succeeded",
                actor_user_id=None,
                from_status=S.DRAFT,
                to_status=S.PENDING_APPROVAL,
                metadata={"http_status": 201, "attempt": 1},
                created_at=sub,
            )

    def decision(entity_type: str, req: Any, event_type: str, to_status: RequestStatus) -> None:
        record_audit(
            session,
            entity_type=entity_type,
            entity_id=req.id,
            event_type=event_type,
            actor_user_id=req.reviewed_by_user_id,
            from_status=S.PENDING_APPROVAL,
            to_status=to_status,
            metadata={"note_present": bool(req.reviewer_note)},
            created_at=req.reviewed_at,
        )

    flow("leave_request", leaves["L1"], users["amy"])
    flow("claim_request", claims["C1"], users["amy"], failed_first=True)
    flow("leave_request", leaves["L3"], users["ben"])
    decision("leave_request", leaves["L3"], "request.approved", S.APPROVED)
    flow("claim_request", claims["C4"], users["ben"])
    decision("claim_request", claims["C4"], "request.rejected", S.REJECTED)


def _seed_notifications(
    session: Session,
    users: dict[str, User],
    leaves: dict[str, LeaveRequest],
    claims: dict[str, ClaimRequest],
) -> None:
    """Pending requests notify their assigned approver; recent decisions notify the requester."""
    for req in [*leaves.values(), *claims.values()]:
        if req.status is S.PENDING_APPROVAL:
            create_notification(
                session,
                recipient_user_id=req.approver_user_id,
                event_type="request.submitted",
                request_type=req.request_type,
                request_id=req.id,
                created_at=req.submitted_at,
            )
    for key, group in (("L3", leaves), ("L4", leaves), ("C3", claims), ("C4", claims)):
        req = group[key]
        approved = req.status is S.APPROVED
        create_notification(
            session,
            recipient_user_id=req.employee_id,
            event_type="request.approved" if approved else "request.rejected",
            request_type=req.request_type,
            request_id=req.id,
            created_at=req.reviewed_at,
            read_at=req.reviewed_at + timedelta(hours=2) if approved else None,
        )


def _seed_conversations(
    session: Session,
    users: dict[str, User],
    leaves: dict[str, LeaveRequest],
    claims: dict[str, ClaimRequest],
    today: date,
) -> list[Conversation]:
    l1 = leaves["L1"]
    receipt = today - timedelta(days=5)
    start = _at(today, -1, 2, 40)

    def msgs(base: datetime, items: list[tuple[SenderType, str, dict[str, Any] | None]]):
        return [
            ConversationMessage(
                sender_type=sender,
                content=text,
                ui_metadata_json=meta,
                created_at=base + timedelta(minutes=i),
            )
            for i, (sender, text, meta) in enumerate(items)
        ]

    conv1 = Conversation(
        user_id=users["amy"].id,
        status=ConversationStatus.CLOSED,
        active_request_type=None,
        created_at=start,
        updated_at=start + timedelta(minutes=3),
        messages=msgs(
            start,
            [
                (
                    SenderType.USER,
                    f"I'd like annual leave from {l1.start_date:%d %b} to {l1.end_date:%d %b}.",
                    None,
                ),
                (
                    SenderType.ASSISTANT,
                    "Here is what I understood. Please confirm to submit it to your approver.",
                    {
                        "type": "confirmation",
                        "request_type": "leave",
                        "fields": {
                            "leave_type": "annual",
                            "start_date": l1.start_date.isoformat(),
                            "end_date": l1.end_date.isoformat(),
                        },
                    },
                ),
                (SenderType.USER, "Yes, confirm.", None),
                (
                    SenderType.ASSISTANT,
                    "Submitted. Your request is now pending approval by Cathy Ng.",
                    {
                        "type": "submission_result",
                        "request_type": "leave",
                        "request_id": l1.id,
                        "status": "pending_approval",
                    },
                ),
            ],
        ),
    )
    cstart = _at(today, -4, 2, 50)
    conv2 = Conversation(
        user_id=users["ben"].id,
        status=ConversationStatus.ACTIVE,
        active_request_type=RequestType.CLAIM,
        created_at=cstart,
        updated_at=cstart + timedelta(minutes=2),
        messages=msgs(
            cstart,
            [
                (SenderType.USER, "I want to claim 86.00 for a team lunch.", None),
                (
                    SenderType.ASSISTANT,
                    "Thanks. What is the receipt date?",
                    {
                        "type": "follow_up",
                        "request_type": "claim",
                        "missing_fields": ["receipt_date"],
                    },
                ),
                (SenderType.USER, f"It was {receipt:%d %b}.", None),
            ],
        ),
    )
    hstart = _at(today, -1, 5, 0)
    conv3 = Conversation(
        user_id=users["cathy"].id,
        status=ConversationStatus.ACTIVE,
        active_request_type=RequestType.LEAVE,
        created_at=hstart,
        updated_at=hstart + timedelta(minutes=1),
        messages=msgs(
            hstart,
            [
                (SenderType.USER, "Can I take a half day off?", None),
                (
                    SenderType.ASSISTANT,
                    "Sure. Which date, and morning or afternoon?",
                    {
                        "type": "follow_up",
                        "request_type": "leave",
                        "missing_fields": ["start_date", "start_day_part"],
                    },
                ),
            ],
        ),
    )
    session.add_all([conv1, conv2, conv3])
    session.flush()
    return [conv1, conv2, conv3]


def seed_demo_data(session: Session, today: date | None = None) -> SeedResult:
    """Load holidays, users, requests, audit trail, conversations, notifications, feedback.

    Idempotent: returns ``SeedResult(seeded=False)`` without changes when any user exists.
    Commits on success; on error the caller should roll back.
    """
    if session.scalar(select(func.count(User.id))):
        return SeedResult(seeded=False)
    today = today or today_hk()

    holidays = _seed_holidays(session)
    departments = _seed_departments(session)
    users = _seed_users(session, departments)
    _seed_entitlements(session, users, today)
    leaves, claims = _seed_requests(session, users, today, holidays)
    _seed_submissions(session, leaves, claims)
    _seed_audit(session, users, leaves, claims)
    _seed_notifications(session, users, leaves, claims)
    conversations = _seed_conversations(session, users, leaves, claims, today)
    session.add_all(
        [
            Feedback(
                user_id=users["amy"].id,
                conversation_id=conversations[0].id,
                rating=5,
                comment="Quick and easy.",
                created_at=_at(today, -1, 3, 10),
            ),
            Feedback(
                user_id=users["ben"].id,
                conversation_id=None,
                rating=4,
                comment="Helpful. Would like claim status updates.",
                created_at=_at(today, -3, 4, 0),
            ),
        ]
    )
    session.commit()
    return SeedResult(seeded=True, counts=table_counts(session))


def ensure_presentation_cancel_demo_data(session: Session) -> bool:
    """Add the one stable fictional leave used by the replayable cancellation demo.

    ``seed_demo_data`` intentionally makes no changes once a database has users.  That is
    normally useful, but it means a persisted presentation database needs this small,
    idempotent fixture added separately.  It is never recreated after the presenter cancels it:
    a later replay receives a fresh pending row with the same distinctive dates.
    """
    daniel = session.scalar(select(User).where(User.email == "daniel.wong@example.com"))
    if daniel is None:
        return False
    existing = session.scalar(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == daniel.id,
            LeaveRequest.leave_type == LeaveType.ANNUAL,
            LeaveRequest.start_date == PRESENTATION_CANCEL_START,
            LeaveRequest.end_date == PRESENTATION_CANCEL_END,
            LeaveRequest.status == RequestStatus.PENDING_APPROVAL,
        )
    )
    if existing is not None:
        return False

    approver = _approver_of(session, daniel, RequestType.LEAVE)
    now = datetime.now(UTC)
    session.add(
        LeaveRequest(
            employee_id=daniel.id,
            leave_type=LeaveType.ANNUAL,
            start_date=PRESENTATION_CANCEL_START,
            end_date=PRESENTATION_CANCEL_END,
            start_day_part=DayPart.FULL,
            end_day_part=DayPart.FULL,
            calendar_days=Decimal("3"),
            working_days=Decimal("3"),
            status=RequestStatus.PENDING_APPROVAL,
            required_approver_role=required_approver_role(RequestType.LEAVE),
            approver_user_id=approver.id,
            submitted_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
    return True


def ensure_presentation_approval_demo_data(session: Session, *, reset: bool = False) -> bool:
    """Replace old Scene 03 fixtures with one isolated bell-to-decision journey.

    The dedicated employee and reviewer have no other pending work.  Thus the bell opens exactly
    one request in the live walkthrough, without skipping unrelated ordinary demo data.  Legacy
    Cathy/Amy/Ben presentation records are removed by their distinctive dates only.
    """
    it = session.scalar(select(Department).where(Department.name == "IT"))
    hr = session.scalar(select(Department).where(Department.name == "HR"))
    if it is None or hr is None:
        return False

    changed = False
    legacy_people = session.scalars(
        select(User.id).where(User.email.in_(("amy.lau@example.com", "ben.chow@example.com")))
    ).all()
    legacy_ids = session.scalars(
        select(LeaveRequest.id).where(
            LeaveRequest.employee_id.in_(legacy_people),
            LeaveRequest.start_date.in_((PRESENTATION_APPROVE_START, PRESENTATION_REJECT_START)),
        )
    ).all()
    if legacy_ids:
        session.execute(
            delete(Notification).where(
                Notification.request_type == RequestType.LEAVE,
                Notification.request_id.in_(legacy_ids),
            )
        )
        session.execute(
            delete(AuditEvent).where(
                AuditEvent.entity_type == RequestType.LEAVE.value,
                AuditEvent.entity_id.in_(legacy_ids),
            )
        )
        session.execute(
            delete(ExternalSubmission).where(
                ExternalSubmission.request_type == RequestType.LEAVE,
                ExternalSubmission.request_id.in_(legacy_ids),
            )
        )
        session.execute(delete(LeaveRequest).where(LeaveRequest.id.in_(legacy_ids)))
        changed = True

    approver = session.scalar(select(User).where(User.email == PRESENTATION_APPROVER_EMAIL))
    if approver is None:
        approver = User(
            google_subject="mock-presentation-reviewer-001",
            email=PRESENTATION_APPROVER_EMAIL,
            display_name="Robin Ho",
            role=UserRole.HR_APPROVER,
            is_active=True,
            department_id=hr.id,
            job_title="Presentation HR Reviewer",
        )
        session.add(approver)
        changed = True
    employee = session.scalar(select(User).where(User.email == PRESENTATION_EMPLOYEE_EMAIL))
    if employee is None:
        employee = User(
            google_subject="mock-presentation-employee-001",
            email=PRESENTATION_EMPLOYEE_EMAIL,
            display_name="Mia Chan",
            role=UserRole.EMPLOYEE,
            is_active=True,
            department_id=it.id,
            job_title="Presentation Employee",
        )
        session.add(employee)
        changed = True
    session.flush()
    if employee.leave_approver_user_id != approver.id:
        employee.leave_approver_user_id = approver.id
        changed = True

    for year in (PRESENTATION_APPROVE_START.year, PRESENTATION_APPROVE_START.year + 1):
        entitlement = session.scalar(
            select(LeaveEntitlement).where(
                LeaveEntitlement.user_id == employee.id,
                LeaveEntitlement.year == year,
                LeaveEntitlement.leave_type == LeaveType.ANNUAL,
            )
        )
        if entitlement is None:
            session.add(
                LeaveEntitlement(
                    user_id=employee.id,
                    year=year,
                    leave_type=LeaveType.ANNUAL,
                    entitled_days=Decimal("15"),
                )
            )
            changed = True

    fixture_ids = session.scalars(
        select(LeaveRequest.id).where(
            LeaveRequest.employee_id == employee.id,
            LeaveRequest.start_date == PRESENTATION_APPROVE_START,
            LeaveRequest.end_date == PRESENTATION_APPROVE_END,
        )
    ).all()
    if reset and fixture_ids:
        session.execute(
            delete(Notification).where(
                Notification.request_type == RequestType.LEAVE,
                Notification.request_id.in_(fixture_ids),
            )
        )
        session.execute(
            delete(AuditEvent).where(
                AuditEvent.entity_type == RequestType.LEAVE.value,
                AuditEvent.entity_id.in_(fixture_ids),
            )
        )
        session.execute(
            delete(ExternalSubmission).where(
                ExternalSubmission.request_type == RequestType.LEAVE,
                ExternalSubmission.request_id.in_(fixture_ids),
            )
        )
        session.execute(delete(LeaveRequest).where(LeaveRequest.id.in_(fixture_ids)))
        fixture_ids = []
        changed = True

    # Bell clicks deliberately create conversations.  A replay must therefore clear only the
    # conversations owned by the two dedicated presentation identities, otherwise a later
    # replay shows old inbox chats alongside the one controlled fixture.  No ordinary demo
    # users or their history are touched.
    if reset:
        presentation_conversation_ids = session.scalars(
            select(Conversation.id).where(Conversation.user_id.in_((approver.id, employee.id)))
        ).all()
        if presentation_conversation_ids:
            session.execute(
                delete(Attachment).where(
                    Attachment.conversation_id.in_(presentation_conversation_ids)
                )
            )
            session.execute(
                delete(Feedback).where(Feedback.conversation_id.in_(presentation_conversation_ids))
            )
            session.execute(
                delete(ConversationMessage).where(
                    ConversationMessage.conversation_id.in_(presentation_conversation_ids)
                )
            )
            session.execute(
                delete(Conversation).where(Conversation.id.in_(presentation_conversation_ids))
            )
            changed = True

    existing = session.scalar(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee.id,
            LeaveRequest.leave_type == LeaveType.ANNUAL,
            LeaveRequest.start_date == PRESENTATION_APPROVE_START,
            LeaveRequest.end_date == PRESENTATION_APPROVE_END,
            LeaveRequest.status == RequestStatus.PENDING_APPROVAL,
        )
    )
    if not fixture_ids and existing is None:
        now = datetime.now(UTC)
        session.add(
            LeaveRequest(
                employee_id=employee.id,
                leave_type=LeaveType.ANNUAL,
                start_date=PRESENTATION_APPROVE_START,
                end_date=PRESENTATION_APPROVE_END,
                start_day_part=DayPart.FULL,
                end_day_part=DayPart.FULL,
                calendar_days=Decimal("3"),
                working_days=Decimal("3"),
                status=RequestStatus.PENDING_APPROVAL,
                required_approver_role=required_approver_role(RequestType.LEAVE),
                approver_user_id=approver.id,
                submitted_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        changed = True
    if changed:
        session.commit()
    return changed


def table_counts(session: Session) -> dict[str, int]:
    from app.db.base import Base

    return {
        name: session.scalar(select(func.count()).select_from(table)) or 0
        for name, table in sorted(Base.metadata.tables.items())
    }
