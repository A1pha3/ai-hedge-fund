"""Authentication service — business logic for auth operations."""

import calendar
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.backend.auth.constants import (
    AccountLockedError,
    ADMIN_ROLES,
    ADMIN_USERNAME,
    ForbiddenError,
    InvalidCredentialsError,
    InvalidTokenError,
    PASSWORD_PATTERN,
    PASSWORD_RULES,
    ROLE_MEMBER,
    VALID_ROLES,
    WeakPasswordError,
    WRITE_ROLES,
)
from app.backend.auth.utils import (
    create_access_token,
    create_reset_token,
    decode_token,
    generate_invitation_code,
    hash_password,
    verify_password,
)
from app.backend.models.user import InvitationCode, User

# Brute-force protection constants
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime (no tzinfo).

    SQLite stores datetime without timezone info, so we use naive UTC
    throughout to avoid 'can't compare offset-naive and offset-aware
    datetimes' TypeError.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _validate_password(password: str) -> None:
    """Validate password meets complexity requirements."""
    if not PASSWORD_PATTERN.match(password):
        raise WeakPasswordError(PASSWORD_RULES)


class AuthService:
    """Handles authentication business logic."""

    def __init__(self, db: Session):
        self.db = db

    # ---- Login / Register ----

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

        token = create_access_token(
            {
                "sub": user.username,
                "role": user.role,
                "tv": user.token_version,  # Token version for invalidation
            }
        )
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": self._serialize_user(user),
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

        if invite.is_revoked:
            raise ValueError("邀请码已被撤销")

        if invite.expires_at and invite.expires_at < _utcnow():
            raise ValueError("邀请码已过期")

        # Check username uniqueness
        existing = self.db.query(User).filter(User.username == username).first()
        if existing:
            raise ValueError("用户名已被注册")

        # Determine role: use invite's role_to_assign, or default to member
        assigned_role = invite.role_to_assign or ROLE_MEMBER
        if assigned_role not in VALID_ROLES:
            assigned_role = ROLE_MEMBER
        # Normalize legacy "user" to "member"
        if assigned_role == "user":
            assigned_role = ROLE_MEMBER

        # Create user
        new_user = User(
            username=username,
            password_hash=hash_password(password),
            role=assigned_role,
            is_active=True,
        )
        self.db.add(new_user)
        self.db.flush()  # Get the new user's ID

        # Mark invitation code as used
        invite.is_used = True
        invite.used_by = new_user.id
        self.db.commit()

        return self._serialize_user(new_user)

    # ---- Password Management ----

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

        return create_reset_token(user.username, token_version=user.token_version or 0)

    def reset_password(self, token: str, new_password: str) -> None:
        """Reset password using a reset token."""
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

        token_version = payload.get("tv")
        if token_version is not None and token_version != (user.token_version or 0):
            raise InvalidTokenError("重置令牌已使用或已过期")

        # Single-use check
        token_iat = payload.get("iat", 0)
        if user.updated_at:
            last_update_ts = calendar.timegm(user.updated_at.timetuple())
            if token_iat < last_update_ts:
                raise InvalidTokenError("重置令牌已使用或已过期")

        _validate_password(new_password)
        user.password_hash = hash_password(new_password)
        user.token_version = (user.token_version or 0) + 1
        self.db.commit()

    def get_user_info(self, user: User) -> dict:
        """Return serialized user info."""
        return self._serialize_user(user)

    # ---- Invite Management (Admin) ----

    def generate_invite(
        self,
        admin: User,
        role_to_assign: str = ROLE_MEMBER,
        expires_days: int | None = 7,
    ) -> dict:
        """Generate a new invitation code. Admin only."""
        if admin.role not in ADMIN_ROLES:
            raise ForbiddenError("权限不足，仅管理员可生成邀请码")

        # Validate role_to_assign
        if role_to_assign not in VALID_ROLES:
            raise ValueError(f"无效的角色: {role_to_assign}")
        # Prevent assigning admin role via invite
        if role_to_assign == "admin":
            raise ValueError("不能通过邀请码分配管理员角色")

        expires_at = None
        if expires_days is not None and expires_days > 0:
            expires_at = _utcnow() + timedelta(days=expires_days)

        code = generate_invitation_code()
        invite = InvitationCode(
            code=code,
            created_by=admin.id,
            role_to_assign=role_to_assign,
            expires_at=expires_at,
        )
        self.db.add(invite)
        self.db.commit()
        self.db.refresh(invite)
        return self._serialize_invite(invite)

    def list_invites(
        self,
        admin: User,
        include_revoked: bool = False,
        include_used: bool = True,
    ) -> list[dict]:
        """List all invitation codes. Admin only."""
        if admin.role not in ADMIN_ROLES:
            raise ForbiddenError("权限不足，仅管理员可查看邀请码")

        query = self.db.query(InvitationCode)
        if not include_revoked:
            query = query.filter(InvitationCode.revoked_at.is_(None))
        if not include_used:
            query = query.filter(InvitationCode.is_used == False)  # noqa: E712
        invites = query.order_by(InvitationCode.created_at.desc()).all()
        return [self._serialize_invite(inv) for inv in invites]

    def revoke_invite(self, admin: User, code: str) -> dict:
        """Revoke an invitation code. Admin only."""
        if admin.role not in ADMIN_ROLES:
            raise ForbiddenError("权限不足，仅管理员可撤销邀请码")

        invite = self.db.query(InvitationCode).filter(InvitationCode.code == code).first()
        if invite is None:
            raise ValueError("邀请码不存在")

        if invite.is_used:
            raise ValueError("邀请码已被使用，无法撤销")

        if invite.is_revoked:
            raise ValueError("邀请码已被撤销")

        invite.revoked_at = _utcnow()
        invite.revoked_by = admin.id
        self.db.commit()
        self.db.refresh(invite)
        return self._serialize_invite(invite)

    def redeem_invite(self, code: str, username: str, password: str) -> dict:
        """Redeem an invitation code to create a new user.

        This is the public-facing registration endpoint. Validates the invite
        code, creates the user with the assigned role, and marks the invite as used.
        """
        _validate_password(password)

        invite = self.db.query(InvitationCode).filter(InvitationCode.code == code).first()
        if invite is None:
            raise ValueError("邀请码不存在")
        if invite.is_used:
            raise ValueError("邀请码已被使用")
        if invite.is_revoked:
            raise ValueError("邀请码已被撤销")
        if invite.expires_at and invite.expires_at < _utcnow():
            raise ValueError("邀请码已过期")

        existing = self.db.query(User).filter(User.username == username).first()
        if existing:
            raise ValueError("用户名已被注册")

        assigned_role = invite.role_to_assign or ROLE_MEMBER
        if assigned_role not in VALID_ROLES:
            assigned_role = ROLE_MEMBER
        if assigned_role == "user":
            assigned_role = ROLE_MEMBER

        new_user = User(
            username=username,
            password_hash=hash_password(password),
            role=assigned_role,
            is_active=True,
        )
        self.db.add(new_user)
        self.db.flush()

        invite.is_used = True
        invite.used_by = new_user.id
        self.db.commit()
        return self._serialize_user(new_user)

    # ---- Session Revocation (Admin) ----

    def revoke_session(self, admin: User, user_id: int) -> dict:
        """Revoke all active sessions for a user by incrementing token_version.

        Admin only. The user's existing JWT will fail token_version validation
        on next request, forcing re-authentication.
        """
        if admin.role not in ADMIN_ROLES:
            raise ForbiddenError("权限不足，仅管理员可强制下线")

        target = self.db.query(User).filter(User.id == user_id).first()
        if target is None:
            raise ValueError("用户不存在")

        if target.id == admin.id:
            raise ValueError("不能撤销自己的会话")

        old_tv = target.token_version or 0
        target.token_version = old_tv + 1
        self.db.commit()

        return {
            "user_id": target.id,
            "username": target.username,
            "message": f"已强制下线用户 {target.username}，其所有现有会话已失效",
        }

    # ---- User Role Management (Admin) ----

    def list_users(self, admin: User) -> list[dict]:
        """List all users. Admin only."""
        if admin.role not in ADMIN_ROLES:
            raise ForbiddenError("权限不足")

        users = self.db.query(User).order_by(User.id).all()
        return [self._serialize_user(u) for u in users]

    def update_user_role(self, admin: User, user_id: int, new_role: str) -> dict:
        """Update a user's role. Admin only."""
        if admin.role not in ADMIN_ROLES:
            raise ForbiddenError("权限不足")

        if new_role not in VALID_ROLES:
            raise ValueError(f"无效的角色: {new_role}")

        target = self.db.query(User).filter(User.id == user_id).first()
        if target is None:
            raise ValueError("用户不存在")

        if target.id == admin.id:
            raise ValueError("不能修改自己的角色")

        if target.role == "admin" and new_role != "admin":
            raise ValueError("不能降级管理员角色")

        target.role = new_role
        target.token_version = (target.token_version or 0) + 1  # Force re-login
        self.db.commit()
        return self._serialize_user(target)

    # ---- Permission Helpers ----

    @staticmethod
    def has_write_access(user: User) -> bool:
        """Check if user has write access (admin or member)."""
        return user.role in WRITE_ROLES

    @staticmethod
    def is_admin(user: User) -> bool:
        """Check if user has admin role."""
        return user.role in ADMIN_ROLES

    # ---- Serialization ----

    def _serialize_user(self, user: User) -> dict:
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        }

    def _serialize_invite(self, invite: InvitationCode) -> dict:
        used_by_user = None
        if invite.used_by:
            user = self.db.query(User).filter(User.id == invite.used_by).first()
            if user:
                used_by_user = {"id": user.id, "username": user.username}

        revoked_by_user = None
        if invite.revoked_by:
            user = self.db.query(User).filter(User.id == invite.revoked_by).first()
            if user:
                revoked_by_user = {"id": user.id, "username": user.username}

        return {
            "id": invite.id,
            "code": invite.code,
            "is_used": invite.is_used,
            "is_revoked": invite.is_revoked,
            "role_to_assign": invite.role_to_assign or ROLE_MEMBER,
            "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
            "created_at": invite.created_at.isoformat() if invite.created_at else None,
            "used_by": used_by_user,
            "revoked_at": invite.revoked_at.isoformat() if invite.revoked_at else None,
            "revoked_by": revoked_by_user,
        }
