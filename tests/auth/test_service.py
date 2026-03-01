"""Tests for AuthService — core authentication business logic."""

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.backend.auth.service import AuthService, _utcnow, _validate_password
from app.backend.auth.constants import (
    ADMIN_USERNAME,
    InvalidCredentialsError,
    AccountLockedError,
    ForbiddenError,
    InvalidTokenError,
    WeakPasswordError,
)
from app.backend.auth.utils import hash_password, verify_password, decode_token, create_reset_token
from app.backend.models.user import User, InvitationCode


# ---- _utcnow helper ----

class TestUtcNow:
    """Tests for the _utcnow() helper."""

    def test_returns_naive_datetime(self):
        now = _utcnow()
        assert now.tzinfo is None, "Should return naive (no tzinfo) datetime"

    def test_is_approximately_now(self):
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        now = _utcnow()
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        assert before <= now <= after


# ---- _validate_password ----

class TestValidatePassword:
    """Tests for password validation helper."""

    def test_valid_password_no_exception(self):
        _validate_password("ValidP4ss")  # Should not raise

    def test_weak_password_raises(self):
        with pytest.raises(WeakPasswordError):
            _validate_password("weak")

    def test_no_uppercase_raises(self):
        with pytest.raises(WeakPasswordError):
            _validate_password("lowercase1")

    def test_no_digit_raises(self):
        with pytest.raises(WeakPasswordError):
            _validate_password("NoDigitHere")

    def test_no_lowercase_raises(self):
        with pytest.raises(WeakPasswordError):
            _validate_password("NOLOWER12")


# ---- Login ----

class TestLogin:
    """Tests for AuthService.login()."""

    def test_login_success(self, db_session, regular_user):
        service = AuthService(db_session)
        result = service.login("testuser", "Test1234")
        assert "access_token" in result
        assert result["token_type"] == "bearer"
        assert result["user"]["username"] == "testuser"
        assert result["user"]["role"] == "user"
        assert result["user"]["email"] == "test@example.com"

    def test_login_wrong_password(self, db_session, regular_user):
        service = AuthService(db_session)
        with pytest.raises(InvalidCredentialsError):
            service.login("testuser", "WrongPass1")

    def test_login_nonexistent_user(self, db_session):
        service = AuthService(db_session)
        with pytest.raises(InvalidCredentialsError):
            service.login("nobody", "Whatever1")

    def test_login_inactive_user(self, db_session, inactive_user):
        service = AuthService(db_session)
        with pytest.raises(InvalidCredentialsError):
            service.login("inactive", "Pass1234")

    def test_login_resets_attempts_on_success(self, db_session, regular_user):
        service = AuthService(db_session)
        # Fail a few times
        for _ in range(3):
            with pytest.raises(InvalidCredentialsError):
                service.login("testuser", "Wrong")
        # Now succeed
        result = service.login("testuser", "Test1234")
        assert result is not None
        # Check attempts reset
        user = db_session.query(User).filter(User.username == "testuser").first()
        assert user.login_attempts == 0

    def test_login_increments_failed_attempts(self, db_session, regular_user):
        service = AuthService(db_session)
        with pytest.raises(InvalidCredentialsError):
            service.login("testuser", "Wrong")
        user = db_session.query(User).filter(User.username == "testuser").first()
        assert user.login_attempts == 1

    def test_login_token_contains_version(self, db_session, regular_user):
        service = AuthService(db_session)
        result = service.login("testuser", "Test1234")
        payload = decode_token(result["access_token"])
        assert payload is not None
        assert payload["tv"] == 0  # Default token_version

    def test_login_returns_updated_at(self, db_session, regular_user):
        service = AuthService(db_session)
        result = service.login("testuser", "Test1234")
        # updated_at may be None or a string
        assert "updated_at" in result["user"]


# ---- Brute-force lockout ----

class TestBruteForceLockout:
    """Tests for account locking after repeated failed logins."""

    def test_lock_after_max_attempts(self, db_session, regular_user):
        service = AuthService(db_session)
        # Fail MAX_LOGIN_ATTEMPTS times (default 5)
        for i in range(4):
            with pytest.raises(InvalidCredentialsError):
                service.login("testuser", "Wrong")
        # 5th attempt should trigger lock
        with pytest.raises(AccountLockedError):
            service.login("testuser", "Wrong")
        # Now even correct password should fail
        with pytest.raises(AccountLockedError):
            service.login("testuser", "Test1234")

    def test_locked_account_message(self, db_session, regular_user):
        service = AuthService(db_session)
        for i in range(4):
            with pytest.raises(InvalidCredentialsError):
                service.login("testuser", "Wrong")
        with pytest.raises(AccountLockedError, match="锁定"):
            service.login("testuser", "Wrong")


# ---- Register ----

class TestRegister:
    """Tests for AuthService.register()."""

    def test_register_success(self, db_session, valid_invite):
        service = AuthService(db_session)
        result = service.register("newuser", "NewPass1234", valid_invite.code)
        assert result["username"] == "newuser"
        assert result["role"] == "user"
        # Verify user in DB
        user = db_session.query(User).filter(User.username == "newuser").first()
        assert user is not None
        assert user.is_active is True
        # Verify invite marked as used
        invite = db_session.query(InvitationCode).filter(InvitationCode.code == valid_invite.code).first()
        assert invite.is_used is True
        assert invite.used_by == user.id

    def test_register_invalid_invite(self, db_session):
        service = AuthService(db_session)
        with pytest.raises(ValueError, match="邀请码"):
            service.register("newuser", "NewPass1234", "INVALID-CODE")

    def test_register_used_invite(self, db_session, used_invite):
        service = AuthService(db_session)
        with pytest.raises(ValueError, match="邀请码"):
            service.register("newuser2", "NewPass1234", used_invite.code)

    def test_register_duplicate_username(self, db_session, regular_user, valid_invite):
        service = AuthService(db_session)
        with pytest.raises(ValueError, match="已被注册"):
            service.register("testuser", "NewPass1234", valid_invite.code)

    def test_register_weak_password(self, db_session, valid_invite):
        service = AuthService(db_session)
        with pytest.raises(WeakPasswordError):
            service.register("newuser", "weak", valid_invite.code)


# ---- Change Password ----

class TestChangePassword:
    """Tests for AuthService.change_password()."""

    def test_change_password_success(self, db_session, regular_user):
        service = AuthService(db_session)
        service.change_password(regular_user, "Test1234", "NewPass456")
        assert verify_password("NewPass456", regular_user.password_hash) is True

    def test_change_password_increments_token_version(self, db_session, regular_user):
        service = AuthService(db_session)
        old_version = regular_user.token_version
        service.change_password(regular_user, "Test1234", "NewPass456")
        assert regular_user.token_version == old_version + 1

    def test_change_password_wrong_old_password(self, db_session, regular_user):
        service = AuthService(db_session)
        with pytest.raises(InvalidCredentialsError, match="旧密码"):
            service.change_password(regular_user, "WrongOld1", "NewPass456")

    def test_change_password_weak_new_password(self, db_session, regular_user):
        service = AuthService(db_session)
        with pytest.raises(WeakPasswordError):
            service.change_password(regular_user, "Test1234", "weak")

    def test_change_password_admin_blocked(self, db_session, admin_user):
        service = AuthService(db_session)
        with pytest.raises(ForbiddenError, match="CLI"):
            service.change_password(admin_user, "Admin123", "NewAdmin456")


# ---- Bind Email ----

class TestBindEmail:
    """Tests for AuthService.bind_email()."""

    def test_bind_email_success(self, db_session, admin_user):
        service = AuthService(db_session)
        service.bind_email(admin_user, "admin@example.com")
        assert admin_user.email == "admin@example.com"

    def test_bind_email_duplicate(self, db_session, regular_user, admin_user):
        service = AuthService(db_session)
        with pytest.raises(ValueError, match="已被其他用户"):
            service.bind_email(admin_user, "test@example.com")  # regular_user's email

    def test_bind_email_update_own(self, db_session, regular_user):
        """User can update their own email to a new one."""
        service = AuthService(db_session)
        service.bind_email(regular_user, "newemail@example.com")
        assert regular_user.email == "newemail@example.com"


# ---- Forgot Password ----

class TestForgotPassword:
    """Tests for AuthService.forgot_password()."""

    def test_forgot_password_success(self, db_session, regular_user):
        service = AuthService(db_session)
        token = service.forgot_password("testuser", "test@example.com")
        assert token is not None

    def test_forgot_password_wrong_email(self, db_session, regular_user):
        service = AuthService(db_session)
        token = service.forgot_password("testuser", "wrong@example.com")
        assert token is None

    def test_forgot_password_nonexistent_user(self, db_session):
        service = AuthService(db_session)
        token = service.forgot_password("nobody", "nobody@example.com")
        assert token is None

    def test_forgot_password_inactive_user(self, db_session, inactive_user):
        service = AuthService(db_session)
        token = service.forgot_password("inactive", "test@example.com")
        assert token is None

    def test_forgot_password_admin_blocked(self, db_session, admin_user):
        """Admin shouldn't get reset token (must use CLI)."""
        service = AuthService(db_session)
        admin_user.email = "admin@example.com"
        db_session.commit()
        token = service.forgot_password(ADMIN_USERNAME, "admin@example.com")
        assert token is None

    def test_forgot_password_returns_valid_jwt(self, db_session, regular_user):
        service = AuthService(db_session)
        token = service.forgot_password("testuser", "test@example.com")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"
        assert payload["type"] == "reset"


# ---- Reset Password ----

class TestResetPassword:
    """Tests for AuthService.reset_password()."""

    def test_reset_password_success(self, db_session, regular_user):
        service = AuthService(db_session)
        token = create_reset_token("testuser")
        service.reset_password(token, "ResetPass1")
        assert verify_password("ResetPass1", regular_user.password_hash) is True

    def test_reset_password_increments_token_version(self, db_session, regular_user):
        service = AuthService(db_session)
        old_version = regular_user.token_version
        token = create_reset_token("testuser")
        service.reset_password(token, "ResetPass1")
        assert regular_user.token_version == old_version + 1

    def test_reset_password_invalid_token(self, db_session):
        service = AuthService(db_session)
        with pytest.raises(InvalidTokenError):
            service.reset_password("invalid.token.here", "ResetPass1")

    def test_reset_password_non_reset_token(self, db_session, regular_user):
        """Access tokens should not work as reset tokens."""
        from app.backend.auth.utils import create_access_token
        token = create_access_token({"sub": "testuser", "role": "user"})
        service = AuthService(db_session)
        with pytest.raises(InvalidTokenError, match="无效的重置令牌"):
            service.reset_password(token, "ResetPass1")

    def test_reset_password_admin_blocked(self, db_session, admin_user):
        service = AuthService(db_session)
        token = create_reset_token(ADMIN_USERNAME)
        with pytest.raises(ForbiddenError, match="CLI"):
            service.reset_password(token, "ResetPass1")

    def test_reset_password_weak_password(self, db_session, regular_user):
        service = AuthService(db_session)
        token = create_reset_token("testuser")
        with pytest.raises(WeakPasswordError):
            service.reset_password(token, "weak")

    def test_reset_password_nonexistent_user(self, db_session):
        service = AuthService(db_session)
        token = create_reset_token("ghost")
        with pytest.raises(InvalidTokenError, match="用户不存在"):
            service.reset_password(token, "ResetPass1")


# ---- Get User Info ----

class TestGetUserInfo:
    """Tests for AuthService.get_user_info()."""

    def test_returns_correct_fields(self, db_session, regular_user):
        service = AuthService(db_session)
        info = service.get_user_info(regular_user)
        assert info["id"] == regular_user.id
        assert info["username"] == "testuser"
        assert info["email"] == "test@example.com"
        assert info["role"] == "user"
        assert "created_at" in info
        assert "updated_at" in info
