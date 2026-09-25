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


def _extract_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str:
    """The JWT from ``Authorization: Bearer`` (wins when present) or the session cookie."""
    if credentials is not None:
        token = credentials.credentials
    else:
        token = request.cookies.get(request.app.state.settings.auth_cookie_name, "")
    if not token:
        raise _unauthorized()
    return token


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(request, credentials)
    settings = request.app.state.settings
    try:
        claims = decode_access_token(
            token,
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


def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """Like ``get_current_user`` but ``None`` for a missing/invalid credential or an inactive
    account (used by the idempotent logout)."""
    try:
        return get_current_user(request, credentials, db)
    except HTTPException as exc:
        if exc.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            return None
        raise


REQUESTER_FORBIDDEN_DETAIL = (
    "This account cannot file requests: no approver is configured for it yet "
    "(out of the PoC scope). Please contact HR or Finance."
)


def user_can_request(user: User) -> bool:
    """True when at least one approver (leave or claim) is configured for the user."""
    return user.can_request


def require_requester(user: User = Depends(get_current_user)) -> User:
    """403 unless the user can file requests (has an approver configured), whatever their role.

    Phase 3: Cathy (HR approver) and Daniel (HR officer) may use the chat like Amy and Ben;
    Helen and Eva have no approver configured, so they get a clear 403 instead.
    """
    if not user_can_request(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=REQUESTER_FORBIDDEN_DETAIL
        )
    return user


def require_chat_access(user: User = Depends(get_current_user)) -> User:
    """403 unless the user may use the chat: can file requests (has an approver configured) OR
    decides one of the approval queues (``approves`` is set), so Helen and Eva can use the bell
    inbox. Filing a request still needs an approver (the assistant refuses politely without one).
    """
    if user_can_request(user) or user.approves is not None:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=REQUESTER_FORBIDDEN_DETAIL)


def require_roles(*roles: UserRole) -> Callable[..., User]:
    """Dependency factory: 403 unless the current user's (DB) role is one of ``roles``.

    Phase 3 special case: the ``employee`` role in a gate means the *requester capability*
    (``require_requester``), because approvers such as Cathy also file requests. So
    ``require_roles(UserRole.EMPLOYEE)`` lets in every user with an approver configured, and
    nobody else; any other role in ``roles`` still matches by role as before.
    """
    allowed = frozenset(UserRole(r) for r in roles)
    by_role = allowed - {UserRole.EMPLOYEE}
    requesters = UserRole.EMPLOYEE in allowed

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role in by_role:
            return user
        if requesters:
            return require_requester(user)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    return dependency
