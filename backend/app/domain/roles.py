"""Role resolution and access rules (pure functions)."""

from collections.abc import Iterable
from typing import Protocol

from app.domain.enums import RequestType, UserRole


class UserLike(Protocol):
    id: int
    email: str
    role: UserRole
    is_active: bool


class RequestLike(Protocol):
    request_type: RequestType
    employee_id: int
    approver_user_id: int | None


_APPROVER_BY_TYPE: dict[RequestType, UserRole] = {
    RequestType.LEAVE: UserRole.HR_APPROVER,
    RequestType.CLAIM: UserRole.FINANCE_APPROVER,
}


def required_approver_role(request_type: RequestType) -> UserRole:
    """leave -> hr_approver, claim -> finance_approver."""
    return _APPROVER_BY_TYPE[RequestType(request_type)]


def can_review(user: UserLike, request_type: RequestType) -> bool:
    """Role check only: the matching approver role, active. Employees never review.

    Phase 3 adds the assignment check (``can_decide``): the role alone is not enough.
    """
    if not user.is_active:
        return False
    return user.role == required_approver_role(request_type)


def can_decide(user: UserLike, request: RequestLike) -> bool:
    """May ``user`` approve or reject this request (status is checked by the state machine)?

    The user must be active, have the matching approver role, be the approver assigned to this
    request (``approver_user_id``) and not be the request's own employee.
    """
    return (
        can_review(user, request.request_type)
        and request.approver_user_id == user.id
        and request.employee_id != user.id
    )


def can_view_request(user: UserLike, request: RequestLike) -> bool:
    """A user sees their own requests, and an approver also those assigned to them."""
    if not user.is_active:
        return False
    if request.employee_id == user.id:
        return True
    return can_review(user, request.request_type) and request.approver_user_id == user.id


def resolve_role[U: UserLike](email: str, users: Iterable[U]) -> U | None:
    """Return the active user with this e-mail (case-insensitive), or None.

    The returned object carries the role (``.role``); inactive users never resolve.
    """
    wanted = email.strip().casefold()
    for user in users:
        if user.is_active and user.email.strip().casefold() == wanted:
            return user
    return None
