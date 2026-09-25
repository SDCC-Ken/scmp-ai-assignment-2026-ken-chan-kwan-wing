"""Notification endpoints (mounted under /api/notifications): the caller's own bell only."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.notifications import NotificationList
from app.services import notifications as service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
def list_notifications(
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationList:
    """Newest first, with the caller's total unread count."""
    return service.list_notifications(db, user, limit)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    service.mark_all_read(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def read_one(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Idempotent. Someone else's (or an unknown) id answers 404."""
    if not service.mark_read(db, user, notification_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
