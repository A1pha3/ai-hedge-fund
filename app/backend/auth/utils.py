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
_DEV_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
_DEV_ADMIN_DEFAULT_PASSWORD = "Hedge@2026!"


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


def should_show_reset_token(configured_value: str | None = None) -> bool:
    """Return whether reset tokens may be included in API responses."""
    value = configured_value if configured_value is not None else os.getenv("AUTH_SHOW_RESET_TOKEN")
    if value is None:
        return not is_production_environment()

    enabled = value.strip().lower() == "true"
    if enabled and is_production_environment():
        logger.warning("AUTH_SHOW_RESET_TOKEN=true ignored in production")
        return False
    return enabled


def should_auto_init_admin(configured_value: str | None = None) -> bool:
    """Return whether the backend may auto-create the bootstrap admin user."""
    value = configured_value if configured_value is not None else os.getenv("AUTH_AUTO_INIT_ADMIN")
    if value is None:
        return not is_production_environment()
    return value.strip().lower() == "true"


def resolve_admin_bootstrap_password(configured_value: str | None = None) -> str | None:
    """Return the password to use for bootstrap admin creation, if allowed."""
    password = configured_value if configured_value is not None else os.getenv("AUTH_ADMIN_DEFAULT_PASSWORD")
    if password:
        return password
    if is_production_environment():
        return None
    return _DEV_ADMIN_DEFAULT_PASSWORD


def get_cors_origins(configured_value: str | None = None) -> list[str]:
    """Return allowed CORS origins for the backend."""
    value = configured_value if configured_value is not None else os.getenv("BACKEND_CORS_ORIGINS")
    if value is None:
        return [] if is_production_environment() else list(_DEV_CORS_ORIGINS)

    origins = [origin.strip() for origin in value.split(",") if origin.strip()]
    return origins


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
