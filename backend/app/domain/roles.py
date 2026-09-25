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


_APPROVER_BY_TYPE: dict[RequestType, UserRole] = {
    RequestType.LEAVE: UserRole.HR_APPROVER,
    RequestType.CLAIM: UserRole.FINANCE_APPROVER,
}


def required_approver_role(request_type: RequestType) -> UserRole:
    """leave -> hr_approver, claim -> finance_approver."""
    return _APPROVER_BY_TYPE[RequestType(request_type)]


def can_review(user: UserLike, request_type: RequestType) -> bool:
    """Only the matching approver role may approve/reject; employees never; inactive never."""
    if not user.is_active:
        return False
    return user.role == required_approver_role(request_type)


def can_view_request(user: UserLike, request: RequestLike) -> bool:
    """Employees see only their own requests; approvers see only their request type."""
    if not user.is_active:
        return False
    if user.role == UserRole.EMPLOYEE:
        return request.employee_id == user.id
    return can_review(user, request.request_type)


def resolve_role[U: UserLike](email: str, users: Iterable[U]) -> U | None:
    """Return the active user with this e-mail (case-insensitive), or None.

    The returned object carries the role (``.role``); inactive users never resolve.
    """
    wanted = email.strip().casefold()
    for user in users:
        if user.is_active and user.email.strip().casefold() == wanted:
            return user
    return None
