"""Mock Google SSO and session endpoints (mounted under /api/auth)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_optional_user
from app.auth.tokens import create_access_token
from app.db.models import User
from app.db.session import get_db
from app.domain.enums import UserRole
from app.schemas.auth import LoginRequest, LoginResponse, UserPublic
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
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


def _cookie_attributes(request: Request) -> dict[str, object]:
    """Shared by set and clear so the browser treats them as the same cookie."""
    return {
        "path": "/",  # host-only: no Domain attribute
        "httponly": True,
        "samesite": "Lax",
        "secure": request.app.state.settings.cookie_secure,
    }


@router.post("/mock-google/login", response_model=LoginResponse)
def mock_google_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    _: None = Depends(_require_mock_sso),
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Sign in as a seeded user without a password (mock Google SSO).

    The JWT is set as an httpOnly cookie and is never part of the response body.

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
    expires_in = settings.jwt_expire_minutes * 60
    response.set_cookie(
        settings.auth_cookie_name, token, max_age=expires_in, **_cookie_attributes(request)
    )
    return LoginResponse(expires_in=expires_in, user=UserPublic.model_validate(user))


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)) -> User:
    """The signed-in user, freshly loaded from the database."""
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> Response:
    """Clear the session cookie and, when a valid user is signed in, record the logout.

    Idempotent: with no/invalid credentials it still returns 204 and clears the cookie, and
    writes no audit row (there is no user to attribute it to). Tokens are stateless (no
    server-side session or deny-list), so a token copied elsewhere simply expires at ``exp``.
    """
    if user is not None:
        record_audit(
            db,
            entity_type="user",
            entity_id=user.id,
            event_type="auth.logout",
            actor_user_id=user.id,
        )
        db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    # Same name/path/attributes as at login, Max-Age=0 and an expiry in the past.
    response.set_cookie(
        request.app.state.settings.auth_cookie_name,
        "",
        max_age=0,
        expires=_EPOCH,
        **_cookie_attributes(request),
    )
    return response
