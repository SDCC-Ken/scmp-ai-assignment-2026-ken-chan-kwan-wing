"""JWT (HS256) creation and verification. Never log tokens or the secret."""

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt

from app.config import Settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
MIN_PRODUCTION_SECRET_LENGTH = 32
REQUIRED_CLAIMS = ["sub", "email", "role", "iss", "iat", "exp", "jti"]
CLOCK_SKEW_SECONDS = 5


class TokenError(Exception):
    """The bearer token is missing claims, expired, tampered with, or otherwise invalid."""


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    email: str
    role: str  # informational only: authorisation always re-reads the user from the DB
    jti: str


def resolve_jwt_secret(settings: Settings) -> str:
    """Return the signing secret for this process.

    * production: a secret of at least 32 characters is mandatory (raises RuntimeError).
    * otherwise: an empty secret becomes a random per-process secret (tokens reset on
      restart) and a warning is logged. The secret itself is never logged.
    """
    secret = settings.jwt_secret_key.get_secret_value()
    if settings.is_production:
        if len(secret) < MIN_PRODUCTION_SECRET_LENGTH:
            raise RuntimeError(
                f"JWT_SECRET_KEY must be at least {MIN_PRODUCTION_SECRET_LENGTH} characters "
                "when APP_ENV=production"
            )
        return secret
    if not secret:
        logger.warning(
            "JWT_SECRET_KEY is empty: using a random per-process secret; "
            "tokens become invalid when the API restarts."
        )
        return secrets.token_hex(32)
    return secret


def create_access_token(
    *,
    user_id: int,
    email: str,
    role: str,
    secret: str,
    issuer: str,
    expires_minutes: int,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": str(role),
        "iss": issuer,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, *, secret: str, issuer: str) -> TokenClaims:
    """Verify signature, ``exp``, ``iss`` and required claims; only HS256 is accepted
    (``alg: none`` and every other algorithm are rejected)."""
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            issuer=issuer,
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": REQUIRED_CLAIMS},
        )
        return TokenClaims(
            user_id=int(claims["sub"]),
            email=str(claims["email"]),
            role=str(claims["role"]),
            jti=str(claims["jti"]),
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise TokenError("Invalid or expired token") from exc
