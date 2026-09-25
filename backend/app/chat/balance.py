"""Leave-balance wording for the chat (Phase 3): card info lines and the "check my balance" answer.

Everything here is deterministic backend text built from ``app.services.balances``; the LLM only
recognises the intent and never words or calculates a number. Balances are shown, never blocking:
a request may go over the entitlement and the approver decides.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.chat.format import fmt_days, plural
from app.domain.enums import LeaveType
from app.schemas.chat import BalanceCard, BalanceLine, CardInfoLine
from app.services.balances import (
    BALANCE_LEAVE_TYPES,
    LeaveBalance,
    leave_balance_after,
    leave_balances_for_user,
)

NO_BALANCE_TEXT = "No leave balance is set up for you yet."
NO_BALANCE_FOR_TYPE = "No leave balance is set up for this leave type"
_PENDING_NOTE = "(pending requests are not counted)"


def _label(leave_type: LeaveType) -> str:
    return "annual leave" if leave_type == LeaveType.ANNUAL else "sick leave"


def leave_card_info(
    session: Session,
    user_id: int,
    leave_type: LeaveType,
    start_date: date,
    working_days: Decimal,
    editing_request_id: int | None = None,
) -> list[CardInfoLine]:
    """Info lines for a leave confirmation card, by the year of the START date.

    Only annual and sick leave have a balance. ``editing_request_id`` leaves the request being
    changed out of the totals (it is the "requested" amount instead). Over the balance adds a
    warning line; nothing here blocks Confirm.
    """
    if leave_type not in BALANCE_LEAVE_TYPES:
        return []
    year = start_date.year
    label = f"{_label(leave_type).capitalize()} {year}"
    after = leave_balance_after(
        session, user_id, year, leave_type, working_days, exclude_request_id=editing_request_id
    )
    if after is None:
        return [CardInfoLine(label=label, value=NO_BALANCE_FOR_TYPE, tone="info")]
    left = after.entitled_days - after.approved_days
    left_after = (
        f"{fmt_days(after.remaining_after_days)} left after this request"
        if after.remaining_after_days >= 0
        else "none left after this request"
    )
    lines = [
        CardInfoLine(
            label=label,
            value=(
                f"{plural(after.entitled_days, 'day')} entitled, {fmt_days(after.approved_days)} "
                f"used, {fmt_days(left)} left; {left_after} {_PENDING_NOTE}"
            ),
            tone="info",
        )
    ]
    if after.over_limit:
        over = -after.remaining_after_days
        lines.append(
            CardInfoLine(
                label="Over your balance",
                value=(
                    f"This is {plural(over, 'day')} over your {_label(leave_type)} balance. "
                    "Your approver will see this and decide."
                ),
                tone="warning",
            )
        )
    return lines


def _line(balance: LeaveBalance) -> BalanceLine:
    return BalanceLine(
        leave_type=balance.leave_type.value,  # type: ignore[arg-type]
        entitled_days=float(balance.entitled_days),
        approved_days=float(balance.approved_days),
        pending_days=float(balance.pending_days),
        remaining_days=float(balance.remaining_days),
    )


def balance_reply(session: Session, user_id: int, year: int) -> tuple[str, BalanceCard | None]:
    """The deterministic answer to "how many leave days do I have left?" for ``year``.

    No entitlement at all: the fixed sentence and no card."""
    balances = leave_balances_for_user(session, user_id, year)
    if not balances:
        return NO_BALANCE_TEXT, None
    parts = []
    for b in balances:
        pending = (
            f" ({plural(b.pending_days, 'day')} pending, not counted)" if b.pending_days else ""
        )
        parts.append(
            f"{_label(b.leave_type).capitalize()}: {plural(b.entitled_days, 'day')} entitled, "
            f"{fmt_days(b.approved_days)} used, {fmt_days(b.remaining_days)} left{pending}."
        )
    text = f"Here is your leave balance for {year}. " + " ".join(parts)
    return text, BalanceCard(year=year, lines=[_line(b) for b in balances])
