"""Who approves a user's requests (Phase 3: one configured approver per user and type).

The approver lives on the user (``users.leave_approver_user_id`` / ``claim_approver_user_id``)
and is copied onto the request when it is created. Departments play no part in routing.
"""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from app.db.models import User
from app.domain.enums import RequestType
from app.domain.roles import required_approver_role


class ApproverProblemReason(StrEnum):
    NOT_CONFIGURED = "not_configured"
    INACTIVE = "inactive"
    IS_REQUESTER = "is_requester"
    WRONG_ROLE = "wrong_role"


@dataclass(frozen=True)
class ApproverProblem:
    """Why no valid approver could be resolved (``message`` is safe to show to the user)."""

    reason: ApproverProblemReason
    request_type: RequestType
    message: str


_TEAM = {RequestType.LEAVE: "HR", RequestType.CLAIM: "Finance"}
_NOUN = {RequestType.LEAVE: "leave requests", RequestType.CLAIM: "claims"}


def configured_approver_id(user: User, request_type: RequestType) -> int | None:
    if RequestType(request_type) == RequestType.LEAVE:
        return user.leave_approver_user_id
    return user.claim_approver_user_id


def resolve_approver(
    session: Session, user: User, request_type: RequestType
) -> User | ApproverProblem:
    """The active approver configured for ``user`` and ``request_type``, or the problem."""
    request_type = RequestType(request_type)
    team, noun = _TEAM[request_type], _NOUN[request_type]

    def problem(reason: ApproverProblemReason, message: str) -> ApproverProblem:
        return ApproverProblem(reason, request_type, message)

    approver_id = configured_approver_id(user, request_type)
    approver = session.get(User, approver_id) if approver_id is not None else None
    if approver is None:
        return problem(
            ApproverProblemReason.NOT_CONFIGURED,
            f"No approver is configured for your {noun} yet (this is out of the PoC scope). "
            f"Please contact {team}.",
        )
    if approver.id == user.id:
        return problem(
            ApproverProblemReason.IS_REQUESTER,
            f"Your {noun} are set to be approved by yourself, which is not allowed. "
            f"Please contact {team}.",
        )
    if not approver.is_active:
        return problem(
            ApproverProblemReason.INACTIVE,
            f"Your {noun} approver's account is no longer active. Please contact {team}.",
        )
    if approver.role != required_approver_role(request_type):
        return problem(
            ApproverProblemReason.WRONG_ROLE,
            f"The approver configured for your {noun} is not a {team} approver. "
            f"Please contact {team}.",
        )
    return approver
