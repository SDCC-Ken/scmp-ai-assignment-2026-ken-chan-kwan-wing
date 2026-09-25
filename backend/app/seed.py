"""Fictional demo data. Deterministic for a given ``today``; a no-op when users exist.

Everything here is invented (``@example.com`` addresses, made-up names, short notes). It
contains no real SCMP, employee, HR or financial data. Requests reviewed long ago have an
``external_submissions`` row but no audit rows: the audit trail is populated for a
representative subset (see ``_seed_audit``) so the demo stays small.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    ClaimRequest,
    Conversation,
    ConversationMessage,
    Feedback,
    LeaveRequest,
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
from app.services.audit import create_notification, record_audit, record_external_submission
from app.services.holidays import latest_stamp, parse_ics, upsert_holidays

BUNDLED_ICS = Path(__file__).parent / "data" / "hk_public_holidays_1823.ics"
SEED_HOLIDAY_YEARS = frozenset({2026, 2027})

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


def _seed_holidays(session: Session) -> set[date]:
    events = parse_ics(BUNDLED_ICS.read_text(encoding="utf-8"))
    stamp = latest_stamp(events)
    wanted = [e for e in events if e.holiday_date.year in SEED_HOLIDAY_YEARS]
    upsert_holidays(session, wanted, HolidaySource.SEED_2026, stamp)
    return {e.holiday_date for e in wanted}


def _seed_users(session: Session) -> dict[str, User]:
    rows = [
        ("amy", "Amy Lau", UserRole.EMPLOYEE),
        ("ben", "Ben Chow", UserRole.EMPLOYEE),
        ("cathy", "Cathy Ng", UserRole.EMPLOYEE),
        ("hr", "Daniel Wong", UserRole.HR_APPROVER),
        ("finance", "Eva Cheung", UserRole.FINANCE_APPROVER),
    ]
    users: dict[str, User] = {}
    for index, (key, name, role) in enumerate(rows, start=1):
        first, last = name.lower().split()
        users[key] = User(
            google_subject=f"mock-google-sub-{index:03d}",
            email=f"{first}.{last}@example.com",
            display_name=name,
            role=role,
            is_active=True,
            created_at=datetime(2026, 1, 5, 2, 0, tzinfo=UTC),
        )
    session.add_all(users.values())
    session.flush()
    return users


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

    s1 = _next_wd(today + timedelta(days=14), hol)
    s2 = _next_wd(today + timedelta(days=8), hol)
    s3 = _next_wd(today + timedelta(days=20), hol)
    s4 = _next_wd(today + timedelta(days=3), hol)
    s5 = _prev_wd(today - timedelta(days=40), hol)
    s6 = _prev_wd(today - timedelta(days=33), hol)
    base7 = today - timedelta(days=56)
    s7 = base7 - timedelta(days=(base7.weekday() - 3) % 7)  # the Thursday on/before
    s8 = _prev_wd(today - timedelta(days=70), hol)
    s9 = _prev_wd(today - timedelta(days=90), hol)
    s10 = _prev_wd(today - timedelta(days=100), hol)
    return [
        _Leave(
            "L1",
            "amy",
            LeaveType.ANNUAL,
            s1,
            _next_wd(s1 + timedelta(days=3), hol),
            S.PENDING_APPROVAL,
            _at(today, -1),
        ),
        _Leave(
            "L2",
            "ben",
            LeaveType.PERSONAL,
            s2,
            s2,
            S.PENDING_APPROVAL,
            _at(today, -2),
            start_part=DayPart.AM,
            end_part=DayPart.AM,
        ),
        _Leave(
            "L3",
            "cathy",
            LeaveType.ANNUAL,
            s3,
            _next_wd(s3 + timedelta(days=1), hol),
            S.APPROVED,
            _at(today, -11),
            reviewed=_at(today, -10, 6),
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
        hist("L5", "amy", LeaveType.ANNUAL, s5, _next_wd(s5 + timedelta(days=3), hol)),
        hist("L6", "ben", LeaveType.SICK, s6, s6),
        hist("L7", "cathy", LeaveType.ANNUAL, s7, s7 + timedelta(days=4), start_part=DayPart.PM),
        hist("L8", "amy", LeaveType.PERSONAL, s8, s8, start_part=DayPart.PM, end_part=DayPart.PM),
        hist(
            "L9",
            "ben",
            LeaveType.ANNUAL,
            s9,
            _next_wd(s9 + timedelta(days=2), hol),
            end_part=DayPart.AM,
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
        _Claim(
            "C2",
            "ben",
            ClaimType.MEAL,
            Decimal("86.00"),
            today - timedelta(days=5),
            S.PENDING_APPROVAL,
            _at(today, -4, 3, 2),
        ),
        _Claim(
            "C3",
            "cathy",
            ClaimType.EQUIPMENT,
            Decimal("1250.00"),
            today - timedelta(days=14),
            S.APPROVED,
            _at(today, -12),
            reviewed=_at(today, -11, 6),
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


def _seed_requests(
    session: Session, users: dict[str, User], today: date, hol: set[date]
) -> tuple[dict[str, LeaveRequest], dict[str, ClaimRequest]]:
    leaves: dict[str, LeaveRequest] = {}
    for spec in _leave_specs(today, hol):
        days = calculate_leave_days(spec.start, spec.end, spec.start_part, spec.end_part, hol)
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
            required_approver_role=UserRole.HR_APPROVER,
            submitted_at=spec.submitted,
            reviewed_by_user_id=users["hr"].id if spec.reviewed else None,
            reviewed_at=spec.reviewed,
            reviewer_note=spec.note,
            created_at=spec.submitted - timedelta(minutes=10),
            updated_at=spec.reviewed or spec.submitted,
        )
    claims: dict[str, ClaimRequest] = {}
    for cspec in _claim_specs(today):
        claims[cspec.key] = ClaimRequest(
            employee_id=users[cspec.employee].id,
            claim_type=cspec.claim_type,
            amount=cspec.amount,
            currency="HKD",
            receipt_date=cspec.receipt,
            status=cspec.status,
            required_approver_role=UserRole.FINANCE_APPROVER,
            submitted_at=cspec.submitted,
            reviewed_by_user_id=users["finance"].id if cspec.reviewed else None,
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
    """One fake success per submitted request, plus a 429 failure before C2's retry."""
    for request in [*leaves.values(), *claims.values()]:
        if request.request_type is RequestType.CLAIM and request is claims["C2"]:
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
    """15 events for four showcase requests (L1, C2 with a 429 retry, L3 approved, C4 rejected)."""

    def flow(entity_type: str, req: Any, owner: User, *, failed_first: bool = False) -> None:
        eid, sub = req.id, req.submitted_at
        common = {"entity_type": entity_type, "entity_id": eid}
        record_audit(
            session,
            **common,
            event_type="request.created",
            actor_user_id=owner.id,
            to_status=S.DRAFT,
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

    flow("leave_request", leaves["L1"], users["amy"])
    flow("claim_request", claims["C2"], users["ben"], failed_first=True)
    flow("leave_request", leaves["L3"], users["cathy"])
    record_audit(
        session,
        entity_type="leave_request",
        entity_id=leaves["L3"].id,
        event_type="request.approved",
        actor_user_id=users["hr"].id,
        from_status=S.PENDING_APPROVAL,
        to_status=S.APPROVED,
        created_at=leaves["L3"].reviewed_at,
    )
    flow("claim_request", claims["C4"], users["ben"])
    record_audit(
        session,
        entity_type="claim_request",
        entity_id=claims["C4"].id,
        event_type="request.rejected",
        actor_user_id=users["finance"].id,
        from_status=S.PENDING_APPROVAL,
        to_status=S.REJECTED,
        metadata={"reviewer_note": claims["C4"].reviewer_note},
        created_at=claims["C4"].reviewed_at,
    )


def _seed_notifications(
    session: Session,
    users: dict[str, User],
    leaves: dict[str, LeaveRequest],
    claims: dict[str, ClaimRequest],
) -> None:
    for key in ("L1", "L2"):
        create_notification(
            session,
            recipient_user_id=users["hr"].id,
            event_type="request.pending_approval",
            request_type=RequestType.LEAVE,
            request_id=leaves[key].id,
            created_at=leaves[key].submitted_at,
        )
    for key in ("C1", "C2"):
        create_notification(
            session,
            recipient_user_id=users["finance"].id,
            event_type="request.pending_approval",
            request_type=RequestType.CLAIM,
            request_id=claims[key].id,
            created_at=claims[key].submitted_at,
        )
    l3 = leaves["L3"]
    create_notification(
        session,
        recipient_user_id=users["cathy"].id,
        event_type="request.approved",
        request_type=RequestType.LEAVE,
        request_id=l3.id,
        created_at=l3.reviewed_at,
        read_at=l3.reviewed_at + timedelta(hours=2),
    )
    c4 = claims["C4"]
    create_notification(
        session,
        recipient_user_id=users["ben"].id,
        event_type="request.rejected",
        request_type=RequestType.CLAIM,
        request_id=c4.id,
        created_at=c4.reviewed_at,
    )


def _seed_conversations(
    session: Session,
    users: dict[str, User],
    leaves: dict[str, LeaveRequest],
    claims: dict[str, ClaimRequest],
    today: date,
) -> list[Conversation]:
    l1, c2 = leaves["L1"], claims["C2"]
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
                    "Here is what I understood. Please confirm to submit to HR.",
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
                    "Submitted. Your request is now pending HR approval.",
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
                (SenderType.USER, f"It was {c2.receipt_date:%d %b}.", None),
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
    users = _seed_users(session)
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


def table_counts(session: Session) -> dict[str, int]:
    from app.db.base import Base

    return {
        name: session.scalar(select(func.count()).select_from(table)) or 0
        for name, table in sorted(Base.metadata.tables.items())
    }
