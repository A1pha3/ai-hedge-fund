"""Password hashing + JWT token utilities for authentication."""

import logging
import os
import secrets
import string
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError

logger = logging.getLogger(__name__)
_PRODUCTION_ENV_VALUES = {"prod", "production"}
_DEV_SECRET_KEY = secrets.token_urlsafe(32)
_dev_secret_warning_emitted = False


def is_production_environment() -> bool:
    """Return True when the backend is running in a production-like environment."""
    for env_var in ("APP_ENV", "ENV", "ENVIRONMENT", "FASTAPI_ENV"):
        value = os.getenv(env_var)
        if value and value.strip().lower() in _PRODUCTION_ENV_VALUES:
            return True
    return False


def get_secret_key() -> str:
    """Resolve the JWT signing key for the current environment."""
    global _dev_secret_warning_emitted

    configured_secret = os.getenv("AUTH_SECRET_KEY")
    if configured_secret:
        return configured_secret

    if is_production_environment():
        raise RuntimeError("AUTH_SECRET_KEY must be set in production environments")

    if not _dev_secret_warning_emitted:
        logger.warning("AUTH_SECRET_KEY not set — using an ephemeral development secret")
        _dev_secret_warning_emitted = True

    return _DEV_SECRET_KEY


ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("AUTH_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours
RESET_TOKEN_EXPIRE_MINUTES = 60  # 1 hour for password reset tokens


def hash_password(plain_password: str) -> str:
    """Generate bcrypt hash for a plaintext password."""
    password_bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token.

    Args:
        data: Token payload, typically {"sub": username, "role": role}
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT string
    """
    to_encode = data.copy()
    now = datetime.now(tz=timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, get_secret_key(), algorithm=ALGORITHM)


def create_reset_token(username: str) -> str:
    """Create a one-time password reset token (short-lived)."""
    return create_access_token(
        data={"sub": username, "type": "reset"},
        expires_delta=timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
    )


def decode_token(token: str) -> dict | None:
    """Decode and validate a JWT token. Returns payload or None on failure."""
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def generate_invitation_code() -> str:
    """Generate a random invitation code like INV-XXXXXXXXXXXX."""
    chars = string.ascii_uppercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(12))
    return f"INV-{random_part}"
