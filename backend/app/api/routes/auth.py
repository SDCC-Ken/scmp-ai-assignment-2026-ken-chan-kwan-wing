"""Mock Google SSO and session endpoints (mounted under /api/auth)."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.tokens import create_access_token
from app.db.models import User
from app.db.session import get_db
from app.domain.enums import UserRole
from app.schemas.auth import LoginRequest, TokenResponse, UserPublic
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

_ROLE_ORDER = {UserRole.EMPLOYEE: 0, UserRole.HR_APPROVER: 1, UserRole.FINANCE_APPROVER: 2}


def _require_mock_sso(request: Request) -> None:
    if not request.app.state.settings.mock_sso_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@router.get("/mock-users", response_model=list[UserPublic])
def list_mock_users(
    _: None = Depends(_require_mock_sso), db: Session = Depends(get_db)
) -> list[User]:
    """Active fictional seed users: employees, then HR approver, then Finance approver."""
    users = db.scalars(select(User).where(User.is_active.is_(True))).all()
    return sorted(users, key=lambda u: (_ROLE_ORDER[u.role], u.id))


@router.post("/mock-google/login", response_model=TokenResponse)
def mock_google_login(
    body: LoginRequest,
    request: Request,
    _: None = Depends(_require_mock_sso),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Sign in as a seeded user without a password (mock Google SSO).

    Every failure looks the same (401 "Invalid credentials") except an inactive account
    (403). Audit rows never contain tokens.
    """
    user = db.scalar(select(User).where(func.lower(User.email) == body.email))
    if user is None:
        record_audit(
            db,
            entity_type="user",
            entity_id=None,
            event_type="auth.login_failed",
            metadata={"reason": "unknown_user"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        record_audit(
            db,
            entity_type="user",
            entity_id=user.id,
            event_type="auth.login_failed",
            metadata={"reason": "inactive"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    settings = request.app.state.settings
    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
        secret=request.app.state.jwt_secret,
        issuer=settings.jwt_issuer,
        expires_minutes=settings.jwt_expire_minutes,
    )
    record_audit(
        db,
        entity_type="user",
        entity_id=user.id,
        event_type="auth.login",
        actor_user_id=user.id,
    )
    db.commit()
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        user=UserPublic.model_validate(user),
    )


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)) -> User:
    """The signed-in user, freshly loaded from the database."""
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    """Record the logout in the audit trail.

    Tokens are stateless (no server-side session or deny-list), so the client discards
    its token; it simply expires at ``exp``.
    """
    record_audit(
        db,
        entity_type="user",
        entity_id=user.id,
        event_type="auth.logout",
        actor_user_id=user.id,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
