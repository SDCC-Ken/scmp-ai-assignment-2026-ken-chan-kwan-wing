"""Changing the organisation data (entitlements, claim limits, approvers) from the CLI.

There is no admin UI in the PoC (see docs/limits-and-routing.md); these functions validate a
change and apply it in the caller's session (the caller commits). ``OrgAdminError`` messages are
written for the person at the terminal.
"""

from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Department, LeaveEntitlement, User
from app.domain.enums import LeaveType, RequestType, UserRole
from app.domain.roles import required_approver_role

ENTITLEMENT_TYPES = (LeaveType.ANNUAL, LeaveType.SICK)
_HALF = Decimal("0.5")


class OrgAdminError(ValueError):
    """The requested change is invalid (unknown name, wrong role, bad number, ...)."""


def parse_days(text: str) -> Decimal:
    """Entitled days: zero or more, in half-day steps."""
    try:
        days = Decimal(text.strip())
    except InvalidOperation:
        raise OrgAdminError(f"'{text}' is not a number of days.") from None
    if not days.is_finite() or days < 0:
        raise OrgAdminError("Days must be zero or more.")
    if days % _HALF != 0:
        raise OrgAdminError("Days must be a whole or half number (0.5 steps).")
    return days.quantize(Decimal("0.1"))


def parse_amount(text: str) -> Decimal:
    """A money amount in HKD: zero or more, at most 2 decimals, at most 12 digits."""
    try:
        amount = Decimal(text.strip().replace(",", ""))
    except InvalidOperation:
        raise OrgAdminError(f"'{text}' is not an amount.") from None
    if not amount.is_finite() or amount < 0:
        raise OrgAdminError("The amount must be zero or more.")
    if amount != amount.quantize(Decimal("0.01")):
        raise OrgAdminError("The amount can have at most 2 decimal places.")
    if len(amount.as_tuple().digits) > 12:
        raise OrgAdminError("The amount is too large (at most 12 digits).")
    return amount.quantize(Decimal("0.01"))


def find_user(session: Session, email: str) -> User:
    user = session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if user is None:
        raise OrgAdminError(f"No user with e-mail {email}. Run 'show-org' to list the users.")
    return user


def find_department(session: Session, name: str) -> Department:
    department = session.scalar(
        select(Department).where(func.lower(Department.name) == name.strip().lower())
    )
    if department is None:
        known = ", ".join(session.scalars(select(Department.name).order_by(Department.name)))
        raise OrgAdminError(f"No department named '{name}' (known: {known or 'none'}).")
    return department


def set_entitlement(
    session: Session, *, email: str, year: int, leave_type: str, days: Decimal
) -> tuple[User, LeaveEntitlement]:
    if not 2000 <= year <= 2100:
        raise OrgAdminError("The year must be between 2000 and 2100.")
    try:
        kind = LeaveType(leave_type)
    except ValueError:
        kind = None
    if kind not in ENTITLEMENT_TYPES:
        raise OrgAdminError("Only annual and sick leave have an entitlement (--type annual|sick).")
    user = find_user(session, email)
    row = session.scalar(
        select(LeaveEntitlement).where(
            LeaveEntitlement.user_id == user.id,
            LeaveEntitlement.year == year,
            LeaveEntitlement.leave_type == kind,
        )
    )
    if row is None:
        row = LeaveEntitlement(user_id=user.id, year=year, leave_type=kind, entitled_days=days)
        session.add(row)
    else:
        row.entitled_days = days
    session.flush()
    return user, row


def set_claim_limit(session: Session, *, department: str, amount: Decimal) -> Department:
    row = find_department(session, department)
    row.claim_limit_amount = amount
    session.flush()
    return row


def _approver_for(session: Session, user: User, email: str, request_type: RequestType) -> User:
    approver = find_user(session, email)
    label = f"{request_type.value} approver"
    if approver.id == user.id:
        raise OrgAdminError(f"{user.display_name} cannot be their own {label}.")
    if not approver.is_active:
        raise OrgAdminError(f"{approver.display_name} is inactive and cannot be a {label}.")
    needed: UserRole = required_approver_role(request_type)
    if approver.role != needed:
        raise OrgAdminError(
            f"{approver.display_name} has the role {approver.role.value}; a {request_type.value} "
            f"approver must be {needed.value}."
        )
    return approver


def set_approvers(
    session: Session,
    *,
    email: str,
    leave_approver: str | None = None,
    claim_approver: str | None = None,
) -> User:
    """Set (or, with ``none``, clear) the leave and/or claim approver of one user.

    A value of ``None`` leaves that approver as it is; the text ``none`` (any case) removes it.
    All checks run before anything changes, so a bad value changes nothing.
    """
    if leave_approver is None and claim_approver is None:
        raise OrgAdminError("Give --leave-approver and/or --claim-approver (an e-mail or 'none').")
    user = find_user(session, email)
    changes: dict[str, int | None] = {}
    for value, request_type, column in (
        (leave_approver, RequestType.LEAVE, "leave_approver_user_id"),
        (claim_approver, RequestType.CLAIM, "claim_approver_user_id"),
    ):
        if value is None:
            continue
        if value.strip().lower() == "none":
            changes[column] = None
        else:
            changes[column] = _approver_for(session, user, value, request_type).id
    for column, approver_id in changes.items():
        setattr(user, column, approver_id)
    session.flush()
    return user


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [
        max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)
    ]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in rows]
    return lines


def _days(value: Decimal) -> str:
    return f"{value:.1f}".removesuffix(".0")


def show_org(session: Session) -> str:
    """A readable text report of departments, users with their approvers, and entitlements."""
    departments = session.scalars(select(Department).order_by(Department.id)).all()
    users = session.scalars(select(User).order_by(User.id)).all()
    names = {u.id: u.display_name for u in users}
    out = ["Departments (yearly claim limit, HKD)"]
    out += _table(
        ["Department", "Claim limit"],
        [[d.name, f"{d.claim_limit_amount:,.2f}"] for d in departments],
    )
    out += ["", "Users (approvers are per user; 'none' = not configured, no chat)"]
    out += _table(
        [
            "Name",
            "E-mail",
            "Department",
            "Role",
            "Title",
            "Leave approver",
            "Claim approver",
            "Active",
        ],
        [
            [
                u.display_name,
                u.email,
                u.department.name if u.department else "-",
                u.role.value,
                u.job_title or "-",
                names.get(u.leave_approver_user_id, "none"),
                names.get(u.claim_approver_user_id, "none"),
                "yes" if u.is_active else "no",
            ]
            for u in users
        ],
    )
    entitlements = session.scalars(
        select(LeaveEntitlement).order_by(
            LeaveEntitlement.year, LeaveEntitlement.user_id, LeaveEntitlement.leave_type
        )
    ).all()
    by_key: dict[tuple[int, int], dict[str, Decimal]] = {}
    for e in entitlements:
        by_key.setdefault((e.year, e.user_id), {})[e.leave_type.value] = e.entitled_days
    for year in sorted({y for y, _ in by_key}):
        out += ["", f"Leave entitlements {year} (days)"]
        out += _table(
            ["Name", "Annual", "Sick"],
            [
                [
                    names[uid],
                    _days(days["annual"]) if "annual" in days else "-",
                    _days(days["sick"]) if "sick" in days else "-",
                ]
                for (y, uid), days in by_key.items()
                if y == year
            ],
        )
    if not entitlements:
        out += ["", "Leave entitlements: none"]
    return "\n".join(out)
