"""Authentication service — business logic for auth operations."""

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.backend.models.user import User, InvitationCode
from app.backend.auth.utils import hash_password, verify_password, create_access_token, create_reset_token, decode_token
from app.backend.auth.constants import ADMIN_USERNAME, PASSWORD_PATTERN, PASSWORD_RULES, InvalidCredentialsError, AccountLockedError, ForbiddenError, InvalidTokenError, WeakPasswordError

# Brute-force protection constants
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_password(password: str) -> None:
    """Validate password meets complexity requirements."""
    if not PASSWORD_PATTERN.match(password):
        raise WeakPasswordError(PASSWORD_RULES)


class AuthService:
    """Handles authentication business logic."""

    def __init__(self, db: Session):
        self.db = db

    def login(self, username: str, password: str) -> dict:
        """Authenticate user and return JWT token + user info."""
        user = self.db.query(User).filter(User.username == username).first()

        if user is None:
            raise InvalidCredentialsError("用户名或密码错误")

        if not user.is_active:
            raise InvalidCredentialsError("用户名或密码错误")

        # Check account lock
        if user.locked_until and user.locked_until > _utcnow():
            remaining = (user.locked_until - _utcnow()).seconds // 60 + 1
            raise AccountLockedError(f"账户已锁定，请 {remaining} 分钟后重试")

        # Verify password
        if not verify_password(password, user.password_hash):
            user.login_attempts = (user.login_attempts or 0) + 1
            if user.login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.locked_until = _utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                user.login_attempts = 0
                self.db.commit()
                raise AccountLockedError(f"登录失败次数过多，账户已锁定 {LOCKOUT_MINUTES} 分钟")
            self.db.commit()
            raise InvalidCredentialsError("用户名或密码错误")

        # Login success — reset attempts
        user.login_attempts = 0
        user.locked_until = None
        self.db.commit()

        token = create_access_token({
            "sub": user.username,
            "role": user.role,
            "tv": user.token_version,  # Token version for invalidation
        })
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None,
            },
        }

    def register(self, username: str, password: str, invitation_code: str) -> dict:
        """Register a new user with an invitation code.

        Raises ValueError with specific messages.
        """
        _validate_password(password)

        # Validate invitation code
        invite = self.db.query(InvitationCode).filter(InvitationCode.code == invitation_code).first()
        if invite is None or invite.is_used:
            raise ValueError("邀请码无效或已被使用")

        if invite.expires_at and invite.expires_at < _utcnow():
            raise ValueError("邀请码已过期")

        # Check username uniqueness
        existing = self.db.query(User).filter(User.username == username).first()
        if existing:
            raise ValueError("用户名已被注册")

        # Create user
        new_user = User(
            username=username,
            password_hash=hash_password(password),
            role="user",
            is_active=True,
        )
        self.db.add(new_user)
        self.db.flush()  # Get the new user's ID

        # Mark invitation code as used
        invite.is_used = True
        invite.used_by = new_user.id
        self.db.commit()

        return {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "role": new_user.role,
            "created_at": new_user.created_at.isoformat() if new_user.created_at else None,
            "updated_at": new_user.updated_at.isoformat() if new_user.updated_at else None,
        }

    def change_password(self, user: User, old_password: str, new_password: str) -> None:
        """Change password for a regular user.

        Admin must use CLI to change password.
        """
        if user.username == ADMIN_USERNAME:
            raise ForbiddenError("管理员密码只能通过 CLI 修改")

        if not verify_password(old_password, user.password_hash):
            raise InvalidCredentialsError("旧密码错误")

        _validate_password(new_password)
        user.password_hash = hash_password(new_password)
        user.token_version = (user.token_version or 0) + 1  # Invalidate existing JWTs
        self.db.commit()

    def bind_email(self, user: User, email: str) -> None:
        """Bind or update email address for a user."""
        # Check email uniqueness
        existing = self.db.query(User).filter(User.email == email, User.id != user.id).first()
        if existing:
            raise ValueError("该邮箱已被其他用户绑定")

        user.email = email
        self.db.commit()

    def forgot_password(self, username: str, email: str) -> str | None:
        """Initiate password reset. Returns reset token if credentials match."""
        user = self.db.query(User).filter(User.username == username, User.email == email).first()
        if user is None or not user.is_active:
            return None

        if user.username == ADMIN_USERNAME:
            return None

        return create_reset_token(user.username)

    def reset_password(self, token: str, new_password: str) -> None:
        """Reset password using a reset token.

        The token is effectively single-use: after a successful reset,
        token_version increments. If the same token is reused, the
        iat (issued-at) check prevents re-use because the token was
        issued before the password change.
        """
        payload = decode_token(token)
        if payload is None:
            raise InvalidTokenError("重置令牌无效或已过期")

        if payload.get("type") != "reset":
            raise InvalidTokenError("无效的重置令牌")

        username = payload.get("sub")
        user = self.db.query(User).filter(User.username == username).first()
        if user is None or not user.is_active:
            raise InvalidTokenError("用户不存在")

        if user.username == ADMIN_USERNAME:
            raise ForbiddenError("管理员密码只能通过 CLI 修改")

        # Single-use check: if the token was issued before the last password change,
        # it means this (or another) reset token was already used.
        token_iat = payload.get("iat", 0)
        if user.updated_at:
            # Convert updated_at to timestamp for comparison
            import calendar
            last_update_ts = calendar.timegm(user.updated_at.timetuple())
            if token_iat < last_update_ts:
                raise InvalidTokenError("重置令牌已使用或已过期")

        _validate_password(new_password)
        user.password_hash = hash_password(new_password)
        user.token_version = (user.token_version or 0) + 1  # Invalidate existing JWTs
        self.db.commit()

    def get_user_info(self, user: User) -> dict:
        """Return serialized user info."""
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        }
