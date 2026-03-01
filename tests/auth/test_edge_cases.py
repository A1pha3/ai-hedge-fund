"""Edge case and security tests for the auth system."""

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.connection import Base
from app.backend.models.user import User, InvitationCode
from app.backend.auth.service import AuthService, _utcnow
from app.backend.auth.utils import (
    hash_password,
    verify_password,
    create_access_token,
    create_reset_token,
    decode_token,
    generate_invitation_code,
)
from app.backend.auth.constants import (
    InvalidCredentialsError,
    AccountLockedError,
    InvalidTokenError,
    WeakPasswordError,
)


@pytest.fixture()
def db_session():
    """In-memory DB with StaticPool for edge case tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def user_with_email(db_session):
    """User with email for forgot-password tests."""
    user = User(
        username="edgeuser",
        password_hash=hash_password("Edge1234"),
        email="edge@example.com",
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ---- Token Version ----

class TestTokenVersion:
    """Test token version invalidation mechanism."""

    def test_password_change_invalidates_old_token(self, db_session, user_with_email):
        service = AuthService(db_session)
        # Login and get token
        result = service.login("edgeuser", "Edge1234")
        old_token = result["access_token"]
        old_payload = decode_token(old_token)

        # Change password
        service.change_password(user_with_email, "Edge1234", "NewEdge456")

        # Old token's tv should not match new token_version
        new_user = db_session.query(User).filter(User.username == "edgeuser").first()
        assert old_payload["tv"] != new_user.token_version

    def test_login_after_password_change(self, db_session, user_with_email):
        service = AuthService(db_session)
        service.change_password(user_with_email, "Edge1234", "NewEdge456")

        # Old password should fail
        with pytest.raises(InvalidCredentialsError):
            service.login("edgeuser", "Edge1234")

        # New password should work
        result = service.login("edgeuser", "NewEdge456")
        assert result["access_token"] is not None


# ---- Reset Token Security ----

class TestResetTokenSecurity:
    """Tests for reset token edge cases."""

    def test_access_token_rejected_as_reset_token(self, db_session, user_with_email):
        """Access tokens should NOT be accepted for password reset."""
        service = AuthService(db_session)
        access_token = create_access_token({"sub": "edgeuser", "role": "user"})
        with pytest.raises(InvalidTokenError, match="无效的重置令牌"):
            service.reset_password(access_token, "NewPass456")

    def test_reset_token_for_nonexistent_user(self, db_session):
        """Reset token for non-existent user should fail."""
        service = AuthService(db_session)
        token = create_reset_token("ghostuser")
        with pytest.raises(InvalidTokenError, match="用户不存在"):
            service.reset_password(token, "NewPass456")

    def test_expired_invite_rejected(self, db_session):
        """Expired invitation code should be rejected."""
        # Create admin for the invite
        admin = User(username="admin2", password_hash=hash_password("Admin123"), role="admin", is_active=True)
        db_session.add(admin)
        db_session.flush()

        # Create expired invite
        invite = InvitationCode(
            code="INV-EXPIRED00001",
            created_by=admin.id,
            is_used=False,
            expires_at=_utcnow() - timedelta(hours=1),
        )
        db_session.add(invite)
        db_session.commit()

        service = AuthService(db_session)
        with pytest.raises(ValueError, match="过期"):
            service.register("newuser", "NewPass1234", "INV-EXPIRED00001")


# ---- Password Edge Cases ----

class TestPasswordEdgeCases:
    """Edge cases for password handling."""

    def test_password_exactly_min_length(self):
        """8-char password with all requirements should work."""
        password = "Abcdef1x"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_very_long_password(self):
        """bcrypt truncates at 72 bytes — verify behavior with long passwords."""
        password = "A" * 70 + "b1"  # 72 chars, last char is '1'
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_password_with_special_characters(self):
        password = "P@$$w0rd!#%^&*()"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_password_with_spaces(self):
        password = "My Pass 1A"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_password_with_unicode(self):
        password = "密码Pāss1"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True


# ---- Brute Force Edge Cases ----

class TestBruteForceEdgeCases:
    """Edge cases for brute-force protection."""

    def test_attempts_reset_after_successful_login(self, db_session, user_with_email):
        service = AuthService(db_session)
        # Fail 3 times
        for _ in range(3):
            with pytest.raises(InvalidCredentialsError):
                service.login("edgeuser", "Wrong")

        # Successful login
        service.login("edgeuser", "Edge1234")

        # Fail 4 more times — should not lock (attempts were reset)
        for _ in range(4):
            with pytest.raises(InvalidCredentialsError):
                service.login("edgeuser", "Wrong")

        # 5th fail after reset should trigger lock
        with pytest.raises(AccountLockedError):
            service.login("edgeuser", "Wrong")


# ---- Invitation Code Edge Cases ----

class TestInvitationCodeEdgeCases:
    """Edge cases for invitation code handling."""

    def test_invite_marked_used_after_registration(self, db_session):
        """After a user registers, the invitation code should be marked as used."""
        admin = User(username="admin3", password_hash=hash_password("Admin123"), role="admin", is_active=True)
        db_session.add(admin)
        db_session.flush()

        invite = InvitationCode(code="INV-ONEUSE123456", created_by=admin.id, is_used=False)
        db_session.add(invite)
        db_session.commit()

        service = AuthService(db_session)
        service.register("oneuse_user", "ValidPass1", "INV-ONEUSE123456")

        # Invite should be used
        invite_db = db_session.query(InvitationCode).filter(InvitationCode.code == "INV-ONEUSE123456").first()
        assert invite_db.is_used is True

        # Second registration with same code should fail
        with pytest.raises(ValueError, match="邀请码"):
            service.register("another_user", "ValidPass1", "INV-ONEUSE123456")


# ---- User Model Edge Cases ----

class TestUserModelEdgeCases:
    """Edge cases for User model defaults."""

    def test_user_defaults(self, db_session):
        user = User(
            username="defaults",
            password_hash=hash_password("Default1"),
            role="user",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        assert user.login_attempts == 0
        assert user.locked_until is None
        assert user.token_version == 0
        assert user.email is None

    def test_user_repr(self, db_session):
        user = User(
            username="reprtest",
            password_hash=hash_password("Repr1234"),
            role="admin",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        repr_str = repr(user)
        assert "reprtest" in repr_str
        assert "admin" in repr_str


# ---- DateTime Consistency ----

class TestDateTimeConsistency:
    """Verify naive UTC datetime handling."""

    def test_utcnow_is_naive(self):
        now = _utcnow()
        assert now.tzinfo is None

    def test_locked_until_comparable_with_utcnow(self, db_session, user_with_email):
        """locked_until should be comparable with _utcnow() (both naive)."""
        user_with_email.locked_until = _utcnow() + timedelta(minutes=15)
        db_session.commit()
        db_session.refresh(user_with_email)

        # Should not raise TypeError — both are naive datetime
        assert user_with_email.locked_until > _utcnow()
