"""Reusable FastAPI auth dependencies.

The user, role and ``is_active`` flag are ALWAYS re-read from the database. The role claim
inside the token is informational only, so demoting or deactivating a user takes effect on
their very next request.
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.tokens import TokenError, decode_access_token
from app.db.models import User
from app.db.session import get_db
from app.domain.enums import UserRole

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise _unauthorized()
    settings = request.app.state.settings
    try:
        claims = decode_access_token(
            credentials.credentials,
            secret=request.app.state.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except TokenError:
        raise _unauthorized() from None
    user = db.get(User, claims.user_id)
    if user is None:
        raise _unauthorized()
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
    return user


def require_roles(*roles: UserRole) -> Callable[..., User]:
    """Dependency factory: 403 unless the current user's (DB) role is one of ``roles``."""
    allowed = frozenset(UserRole(r) for r in roles)

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return dependency
