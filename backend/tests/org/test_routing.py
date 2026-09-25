"""resolve_approver: the configured approver, or exactly why there is none."""

import pytest
from sqlalchemy.orm import Session

from app.db.models import User
from app.domain.enums import RequestType, UserRole
from app.services.routing import (
    ApproverProblem,
    ApproverProblemReason,
    configured_approver_id,
    resolve_approver,
)
from tests.org.helpers import add_department, add_user

LEAVE, CLAIM = RequestType.LEAVE, RequestType.CLAIM
R = ApproverProblemReason


def org(session: Session) -> dict[str, User]:
    hr = add_department(session, "HR")
    it = add_department(session, "IT")
    cathy = add_user(session, "Cathy Ng", UserRole.HR_APPROVER, hr)
    eva = add_user(session, "Eva Cheung", UserRole.FINANCE_APPROVER)
    amy = add_user(session, "Amy Lau", department=it, leave_approver=cathy, claim_approver=eva)
    return {"cathy": cathy, "eva": eva, "amy": amy}


def test_the_configured_approver_is_returned_for_each_type(session: Session) -> None:
    people = org(session)
    assert resolve_approver(session, people["amy"], LEAVE) is people["cathy"]
    assert resolve_approver(session, people["amy"], CLAIM) is people["eva"]


def test_department_plays_no_part_in_routing(session: Session) -> None:
    """The approver is per user: Amy (IT) is approved by Cathy who sits in HR."""
    people = org(session)
    approver = resolve_approver(session, people["amy"], LEAVE)
    assert isinstance(approver, User) and approver.department.name == "HR"
    assert people["amy"].department.name == "IT"


def test_not_configured(session: Session) -> None:
    people = org(session)
    for user in (people["cathy"], people["eva"]):  # Helen/Eva style: nothing configured
        for rtype in (LEAVE, CLAIM):
            problem = resolve_approver(session, user, rtype)
            assert isinstance(problem, ApproverProblem)
            assert problem.reason is R.NOT_CONFIGURED and problem.request_type is rtype
    only_leave = add_user(session, "Ben Chow", leave_approver=people["cathy"])
    assert isinstance(resolve_approver(session, only_leave, LEAVE), User)
    assert resolve_approver(session, only_leave, CLAIM).reason is R.NOT_CONFIGURED


def test_the_message_explains_and_names_the_team(session: Session) -> None:
    people = org(session)
    leave = resolve_approver(session, people["cathy"], LEAVE)
    claim = resolve_approver(session, people["cathy"], CLAIM)
    assert "out of the PoC scope" in leave.message and "HR" in leave.message
    assert "Finance" in claim.message and "claims" in claim.message


def test_the_configured_approver_row_is_missing_counts_as_not_configured(
    session: Session,
) -> None:
    people = org(session)
    amy = people["amy"]
    amy.leave_approver_user_id = 9999  # a dangling id, never written to the database
    session.expunge(amy)
    assert resolve_approver(session, amy, LEAVE).reason is R.NOT_CONFIGURED


def test_inactive_approver(session: Session) -> None:
    people = org(session)
    people["cathy"].is_active = False
    problem = resolve_approver(session, people["amy"], LEAVE)
    assert isinstance(problem, ApproverProblem) and problem.reason is R.INACTIVE
    assert isinstance(resolve_approver(session, people["amy"], CLAIM), User)  # claims unaffected


def test_approver_is_the_requester(session: Session) -> None:
    people = org(session)
    people["cathy"].leave_approver_user_id = people["cathy"].id
    problem = resolve_approver(session, people["cathy"], LEAVE)
    assert problem.reason is R.IS_REQUESTER and "yourself" in problem.message


@pytest.mark.parametrize(
    ("rtype", "wrong"),
    [(LEAVE, "eva"), (CLAIM, "cathy"), (LEAVE, "amy"), (CLAIM, "amy")],
)
def test_approver_with_the_wrong_role(session: Session, rtype: RequestType, wrong: str) -> None:
    people = org(session)
    ben = add_user(session, "Ben Chow")
    if rtype is LEAVE:
        ben.leave_approver_user_id = people[wrong].id
    else:
        ben.claim_approver_user_id = people[wrong].id
    problem = resolve_approver(session, ben, rtype)
    assert isinstance(problem, ApproverProblem) and problem.reason is R.WRONG_ROLE


def test_the_check_order_is_requester_then_inactive_then_role(session: Session) -> None:
    people = org(session)
    eva = people["eva"]
    eva.is_active = False
    eva.claim_approver_user_id = eva.id
    assert resolve_approver(session, eva, CLAIM).reason is R.IS_REQUESTER


def test_configured_approver_id(session: Session) -> None:
    people = org(session)
    assert configured_approver_id(people["amy"], LEAVE) == people["cathy"].id
    assert configured_approver_id(people["amy"], CLAIM) == people["eva"].id
    assert configured_approver_id(people["cathy"], LEAVE) is None
