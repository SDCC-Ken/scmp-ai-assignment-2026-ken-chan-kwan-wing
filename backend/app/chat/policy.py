"""Tunable constants and the Phase 3 business-rule extension point.

Phase 2 enforces STRUCTURAL validity (it is what makes a request meaningful):

* enums / types, ``end_date >= start_date``, valid half-day part combinations
* at least one working day (weekend-only / holiday-only ranges are errors)
* claim amount > 0 with at most 2 decimals (more is rejected, never rounded), HKD only,
  receipt date not in the future (``ClaimDraft``)
* ownership and the status state machine for update / cancel

plus exactly one business rule, ``no_past_leave_except_sick`` (registered below). Every other
business rule (maximum length, overlap with other leave, leave balance, claim caps, receipt age,
duplicate claims, ...) is deliberately NOT implemented yet: Ken schedules them for Phase 3.
They plug in here without touching the agent or the workflow:

    from app.chat.policy import BUSINESS_RULES, RuleContext, Violation

    def no_leave_over_60_days(ctx: RuleContext) -> Violation | None:
        if ctx.request_type is RequestType.LEAVE and ctx.days and ctx.days.calendar_days > 60:
            return Violation("end_date", "Leave can cover at most 60 calendar days. ...")
        return None

    BUSINESS_RULES.append(no_leave_over_60_days)

Every rule runs after the structural checks (and again when the user presses Confirm, because
the world may have changed). The FIRST violation becomes a deterministic follow-up question and
no confirmation card is shown until the user fixes it. The registry ships with the single
rule ``no_past_leave_except_sick``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.chat.format import fmt_date
from app.db.models import LeaveRequest
from app.domain.enums import LeaveType, RequestStatus, RequestType
from app.domain.leave import LeaveDays
from app.schemas.drafts import ClaimDraft, LeaveDraft

# --- structural limits (documented in backend/README.md) -------------------------------------
CLAIM_MAX_DECIMALS = 2
CLAIM_CURRENCY = "HKD"

# Statuses in which an employee may still change or cancel a request (not yet reviewed).
EDITABLE_STATUSES = frozenset(
    {RequestStatus.DRAFT, RequestStatus.SUBMISSION_FAILED, RequestStatus.PENDING_APPROVAL}
)
# Statuses that can be (re)submitted to the mock API.
RETRYABLE_STATUSES = frozenset({RequestStatus.DRAFT, RequestStatus.SUBMISSION_FAILED})

# --- LLM / conversation handling -------------------------------------------------------------
LLM_MIN_CONFIDENCE = 0.5  # below this (or with ambiguities) no card is shown
FOLLOWUP_MAX_CHARS = 240  # an LLM-worded question longer than this is ignored
HISTORY_MESSAGES = 8  # recent messages sent to the LLM as context
HISTORY_MESSAGE_CHARS = 500
OPEN_REQUESTS_LIMIT = 10  # of THIS user's editable requests, given to the LLM
STATUS_LIST_LIMIT = 10  # most recent requests in a status card
TITLE_MAX_CHARS = 60


# --- Phase 3 extension point -----------------------------------------------------------------
@dataclass(frozen=True)
class RuleContext:
    """Everything a business rule may look at (already structurally valid)."""

    session: Session
    employee_id: int
    request_type: RequestType
    draft: LeaveDraft | ClaimDraft
    today: date
    days: LeaveDays | None = None  # leave only: calendar / working days
    amount: Decimal | None = None  # claim only
    editing_request_id: int | None = None  # exclude this request from overlap / duplicate checks


@dataclass(frozen=True)
class Violation:
    """A user-facing rule violation: the field to fix and a complete follow-up sentence."""

    field: str
    message: str


Rule = Callable[[RuleContext], "Violation | Sequence[Violation] | None"]


def no_past_leave_except_sick(ctx: RuleContext) -> Violation | None:
    """Only sick leave may start in the past (any number of days back).

    Annual, personal and unpaid leave must start today or later (Hong Kong date). When an
    existing request is being edited the rule applies only if its start date or leave type is
    changed, so shortening or extending an already-started leave is not blocked by its old
    start date.
    """
    draft = ctx.draft
    if not isinstance(draft, LeaveDraft):
        return None
    if draft.leave_type == LeaveType.SICK or draft.start_date >= ctx.today:
        return None
    if ctx.editing_request_id is not None:
        stored = ctx.session.get(LeaveRequest, ctx.editing_request_id)
        if (
            stored is not None
            and stored.start_date == draft.start_date
            and stored.leave_type == draft.leave_type
        ):
            return None
    return Violation(
        "start_date",
        f"{draft.leave_type.value.title()} leave cannot start in the past (today is "
        f"{fmt_date(ctx.today)}). Which start date do you want? Sick leave can be back-dated.",
    )


BUSINESS_RULES: list[Rule] = [no_past_leave_except_sick]


def first_violation(ctx: RuleContext, rules: Sequence[Rule] | None = None) -> Violation | None:
    """Run the registered rules in order and return the first violation (None = all pass)."""
    for rule in BUSINESS_RULES if rules is None else rules:
        result = rule(ctx)
        if result is None:
            continue
        if isinstance(result, Violation):
            return result
        for violation in result:
            return violation
    return None
