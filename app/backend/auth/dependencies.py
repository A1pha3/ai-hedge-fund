"""FastAPI authentication dependencies (middleware)."""

import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.backend.database.connection import get_db
from app.backend.models.user import User
from app.backend.auth.utils import decode_token
from app.backend.auth.constants import ADMIN_USERNAME

# Optional: disable auth for development
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").lower() == "true"

security = HTTPBearer(auto_error=False)


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
    if AUTH_DISABLED:
        mock_user = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if mock_user:
            return mock_user
        # Fallback: find any admin user
        any_admin = db.query(User).filter(User.role == "admin").first()
        if any_admin:
            return any_admin
        # Last resort: create a transient mock user (not persisted, id=-1 avoids FK collision)
        mock = User(id=-1, username="dev", role="admin", is_active=True)
        return mock

    if credentials is None:
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = credentials.credentials
    payload = decode_token(token)

    if payload is None:
        raise HTTPException(status_code=401, detail="无效的认证令牌")

    username: str | None = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=401, detail="无效的认证令牌")

    # Reject reset tokens used as access tokens
    if payload.get("type") == "reset":
        raise HTTPException(status_code=401, detail="无效的认证令牌")

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")

    # Check token version — reject tokens issued before password change
    token_version = payload.get("tv", 0)
    if token_version != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="认证令牌已失效，请重新登录")

    # Check account lock
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=423, detail="账户已锁定，请稍后重试")

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require admin role."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="权限不足")
    return current_user
