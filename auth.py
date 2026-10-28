
"""LawNexa authentication utilities.

Uses bcrypt password hashing and signed JWT access tokens.
Production deployments must provide a strong SECRET_KEY environment variable.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext


ALGORITHM = "HS256"
try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
except ValueError as exc:
    raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be a positive integer.") from exc

if ACCESS_TOKEN_EXPIRE_MINUTES < 1 or ACCESS_TOKEN_EXPIRE_MINUTES > 525600:
    raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 525600.")

_IS_PRODUCTION = (
    os.getenv("ENVIRONMENT", "").strip().lower() in {"production", "staging"}
    or os.getenv("RENDER", "").strip().lower() == "true"
)

SECRET_KEY = os.getenv("SECRET_KEY", "").strip()

if _IS_PRODUCTION and (
    not SECRET_KEY
    or SECRET_KEY.startswith("<")
    or any(marker in SECRET_KEY.lower() for marker in ("replace-me", "replace_with", "change_me", "placeholder"))
):
    raise RuntimeError("Set a unique, non-placeholder SECRET_KEY in deployed environments.")

if not SECRET_KEY:
    if _IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY must be configured in production."
        )
    # Local development only. Tokens expire when this process restarts.
    SECRET_KEY = secrets.token_urlsafe(48)

if _IS_PRODUCTION and len(SECRET_KEY) < 32:
    raise RuntimeError(
        "Production SECRET_KEY must be at least 32 characters."
    )


_password_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


def get_password_hash(password: str) -> str:
    """Return a secure bcrypt hash for a password."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must not be empty.")

    # bcrypt supports passwords up to 72 UTF-8 bytes.
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password is too long for bcrypt (maximum 72 bytes).")

    return _password_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a supported bcrypt hash."""
    if not isinstance(plain_password, str):
        return False
    if len(plain_password.encode("utf-8")) > 72:
        return False
    if not isinstance(hashed_password, str) or not hashed_password:
        return False

    try:
        return _password_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT with an expiry timestamp."""
    if not isinstance(data, dict) or not data:
        raise ValueError("Token data must be a non-empty dictionary.")

    payload = data.copy()
    now = datetime.now(timezone.utc)
    payload["iat"] = now
    payload["exp"] = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Validate a JWT signature and expiry; return None if invalid."""
    if not isinstance(token, str) or not token.strip():
        return None

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        if not payload.get("sub"):
            return None
        return payload
    except (JWTError, ValueError, TypeError):
        return None
