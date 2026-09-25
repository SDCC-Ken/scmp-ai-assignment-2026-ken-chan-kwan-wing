"""Endpoints about the signed-in user (mounted under /api/me)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import require_requester
from app.db.models import User
from app.db.session import get_db
from app.domain.clock import today_hk
from app.schemas.org import BalanceLine, BalancesResponse
from app.services.balances import leave_balances_for_user

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/balances", response_model=BalancesResponse)
def my_balances(
    user: User = Depends(require_requester), db: Session = Depends(get_db)
) -> BalancesResponse:
    """The caller's annual and sick leave balance for the current Hong Kong calendar year.

    Approved leave is deducted (counted in the year of its start date); pending leave is shown
    separately. Personal and unpaid leave have no balance. Users without an approver (no
    requests, no balance) get 403 from ``require_requester``.
    """
    year = today_hk().year
    return BalancesResponse(
        year=year,
        leave=[BalanceLine.from_balance(b) for b in leave_balances_for_user(db, user.id, year)],
    )
