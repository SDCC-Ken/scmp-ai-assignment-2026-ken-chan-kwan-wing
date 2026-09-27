"""Local-only controls for resetting the isolated presentation fixture."""

from hmac import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.seed import ensure_presentation_approval_demo_data

router = APIRouter(prefix="/presentation", tags=["presentation"])


@router.post("/reset-approval-demo")
def reset_approval_demo(
    request: Request,
    token: str | None = Header(default=None, alias="X-Presentation-Reset"),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Recreate only Robin and Mia's dedicated live-demo Leave request."""
    expected = request.app.state.settings.presentation_reset_token.get_secret_value()
    if not expected or not compare_digest(token or "", expected):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return {"reset": ensure_presentation_approval_demo_data(db, reset=True)}
