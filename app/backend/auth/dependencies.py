"""FastAPI authentication dependencies (middleware)."""

import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.backend.auth.constants import ADMIN_USERNAME
from app.backend.auth.utils import decode_token, is_production_environment
from app.backend.database.connection import get_db
from app.backend.models.user import User

# Optional: disable auth for development
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").lower() == "true"

security = HTTPBearer(auto_error=False)


def _auth_disabled_enabled() -> bool:
    if not AUTH_DISABLED:
        return False
    if is_production_environment():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AUTH_DISABLED cannot be used in production")
    return True


def _resolve_dev_user(db: Session) -> User:
    mock_user = db.query(User).filter(User.username == ADMIN_USERNAME).first()
    if mock_user:
        return mock_user

    any_admin = db.query(User).filter(User.role == "admin").first()
    if any_admin:
        return any_admin

    return User(id=-1, username="dev", role="admin", is_active=True)


def _require_payload(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("sub") is None or payload.get("type") == "reset":
        raise HTTPException(status_code=401, detail="无效的认证令牌")

    return payload


def _validate_user_from_payload(payload: dict, db: Session) -> User:
    username = payload["sub"]
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")

    token_version = payload.get("tv", 0)
    if token_version != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="认证令牌已失效，请重新登录")

    if user.locked_until and user.locked_until > datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(status_code=423, detail="账户已锁定，请稍后重试")

    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Extract and validate current user from JWT access token.

    Validation flow:
    1. Decode JWT → extract username
    2. Query database → confirm user exists and is active
    3. Check account lock status (anti brute-force)
    """
    # If auth is disabled, return a mock admin user for development
    if _auth_disabled_enabled():
        return _resolve_dev_user(db)

    payload = _require_payload(credentials)
    return _validate_user_from_payload(payload, db)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require admin role."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="权限不足")
    return current_user
