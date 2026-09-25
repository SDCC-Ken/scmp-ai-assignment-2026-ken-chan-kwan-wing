from dataclasses import dataclass
from itertools import product

import pytest

from app.domain.enums import RequestType, UserRole
from app.domain.roles import can_review, can_view_request, required_approver_role, resolve_role


@dataclass
class U:
    id: int
    email: str
    role: UserRole
    is_active: bool = True


@dataclass
class Req:
    request_type: RequestType
    employee_id: int


EMP = U(1, "amy.lau@example.com", UserRole.EMPLOYEE)
OTHER = U(2, "ben.chow@example.com", UserRole.EMPLOYEE)
HR = U(4, "daniel.wong@example.com", UserRole.HR_APPROVER)
FIN = U(5, "eva.cheung@example.com", UserRole.FINANCE_APPROVER)


def test_required_approver_role() -> None:
    assert required_approver_role(RequestType.LEAVE) is UserRole.HR_APPROVER
    assert required_approver_role(RequestType.CLAIM) is UserRole.FINANCE_APPROVER


@pytest.mark.parametrize(
    ("user", "request_type", "expected"),
    [
        (EMP, RequestType.LEAVE, False),
        (EMP, RequestType.CLAIM, False),
        (HR, RequestType.LEAVE, True),
        (HR, RequestType.CLAIM, False),
        (FIN, RequestType.LEAVE, False),
        (FIN, RequestType.CLAIM, True),
    ],
)
def test_can_review_matrix(user: U, request_type: RequestType, expected: bool) -> None:
    assert can_review(user, request_type) is expected


@pytest.mark.parametrize("request_type", list(RequestType))
def test_inactive_user_never_reviews_or_views(request_type: RequestType) -> None:
    for role in UserRole:
        inactive = U(9, "x@example.com", role, is_active=False)
        assert can_review(inactive, request_type) is False
        assert can_view_request(inactive, Req(request_type, 9)) is False


def test_can_view_request() -> None:
    leave, claim = Req(RequestType.LEAVE, EMP.id), Req(RequestType.CLAIM, EMP.id)
    assert can_view_request(EMP, leave) and can_view_request(EMP, claim)
    assert not can_view_request(OTHER, leave) and not can_view_request(OTHER, claim)
    assert can_view_request(HR, leave) and not can_view_request(HR, claim)
    assert can_view_request(FIN, claim) and not can_view_request(FIN, leave)


def test_resolve_role_is_case_insensitive_and_active_only() -> None:
    users = [EMP, HR, U(7, "gone@example.com", UserRole.EMPLOYEE, is_active=False)]
    assert resolve_role("  Daniel.Wong@EXAMPLE.com ", users) is HR
    assert resolve_role("AMY.LAU@example.com", users).role is UserRole.EMPLOYEE
    assert resolve_role("gone@example.com", users) is None
    assert resolve_role("nobody@example.com", users) is None


def test_matrix_covers_all_roles_and_types() -> None:
    assert len(list(product(UserRole, RequestType))) == 6
