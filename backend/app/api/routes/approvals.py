"""Approver endpoints (mounted under /api/approvals). Contract:
docs/phase3-approval-design.md, section 5.

* HR approvers work the leave queue and the Finance approver the claim queue, each limited to
  the requests assigned to them; other users get 403.
* 404 (one identical body) for a request that does not exist, is not assigned to the caller, is
  of the other type, or (detail only) is no longer pending; 409 when it was decided meanwhile.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.domain.enums import RequestType
from app.schemas.approvals import ApprovalDetail, ApprovalList, DecisionBody, DecisionResponse
from app.services import approvals as service
from app.services.approvals import ApprovalConflict, ApprovalForbidden, ApprovalNotFound

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approvals", tags=["approvals"])

NOT_FOUND_DETAIL = "Request not found"
CONFLICT_DETAIL = "This request was already decided or is no longer pending approval."
FORBIDDEN_DETAIL = "Only an approver can use the approval queue."


def require_approver(user: User = Depends(get_current_user)) -> User:
    """403 unless the user decides one of the queues (``approves`` is leave or claim)."""
    if user.approves is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN_DETAIL)
    return user


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)


def _request_type(value: str) -> RequestType:
    rtype = service.parse_request_type(value)
    if rtype is None:
        raise _not_found()
    return rtype


@router.get("", response_model=ApprovalList)
def list_approvals(
    user: User = Depends(require_approver), db: Session = Depends(get_db)
) -> ApprovalList:
    """The caller's pending requests, oldest submitted first."""
    return service.list_queue(db, user)


@router.get("/{request_type}/{request_id}", response_model=ApprovalDetail)
def approval_detail(
    request_type: str,
    request_id: int,
    user: User = Depends(require_approver),
    db: Session = Depends(get_db),
) -> ApprovalDetail:
    rtype = _request_type(request_type)
    try:
        return service.get_detail(db, user, rtype, request_id)
    except ApprovalNotFound:
        raise _not_found() from None


@router.post("/{request_type}/{request_id}/decision", response_model=DecisionResponse)
def decide(
    request_type: str,
    request_id: int,
    body: DecisionBody,
    user: User = Depends(require_approver),
    db: Session = Depends(get_db),
) -> DecisionResponse | JSONResponse:
    rtype = _request_type(request_type)
    try:
        return service.decide(db, user, rtype, request_id, body.decision, body.note)
    except ApprovalNotFound:
        raise _not_found() from None
    except ApprovalConflict:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CONFLICT_DETAIL) from None
    except ApprovalForbidden as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from None
    except SQLAlchemyError:
        logger.exception("Database error while recording a decision")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "The database is temporarily unavailable. Please try again."},
        )
