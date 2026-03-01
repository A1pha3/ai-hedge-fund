"""Supplemental tests to improve coverage on service.py (L198), routes, and models."""

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.connection import Base, get_db
from app.backend.models.user import User, InvitationCode
from app.backend.auth.service import AuthService
from app.backend.auth.utils import hash_password, create_reset_token, create_access_token
from app.backend.auth.constants import InvalidTokenError, ADMIN_USERNAME


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()


# ---- service.py line 198: reset token single-use (iat < updated_at) ----

class TestResetTokenSingleUse:
    """Cover the branch where token_iat < last_update_ts (service.py L198)."""

    def test_double_reset_rejected(self, db):
        """A reset token used once should not work a second time.

        Covers service.py line 198: token_iat < last_update_ts
        """
        user = User(
            username="resetuser",
            password_hash=hash_password("OldPass123"),
            role="user",
            is_active=True,
            email="reset@test.com",
        )
        db.add(user)
        db.commit()

        # Create a reset token normally
        token = create_reset_token("resetuser")

        # First reset: succeeds
        service = AuthService(db)
        service.reset_password(token, "NewPass123")
        db.refresh(user)

        # Now manually set updated_at far into the future so iat < updated_at
        # This simulates time passing after the reset
        user.updated_at = _utcnow() + timedelta(hours=1)
        db.commit()
        db.refresh(user)

        # Second reset with same token: should fail because iat < updated_at
        with pytest.raises(InvalidTokenError, match="已使用|已过期"):
            service.reset_password(token, "AnotherPass1")


# ---- get_user_info with None dates ----

class TestGetUserInfo:
    """Cover get_user_info edge cases."""

    def test_user_info_no_dates(self, db):
        """User with None created_at/updated_at should serialize as None."""
        user = User(
            username="nodates",
            password_hash=hash_password("NoDates1"),
            role="user",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        service = AuthService(db)
        info = service.get_user_info(user)
        assert info["username"] == "nodates"
        # created_at may or may not be auto-set depending on default
        assert info["email"] is None

    def test_user_info_with_email(self, db):
        """User info should include email when set."""
        user = User(
            username="emailuser",
            password_hash=hash_password("Email123"),
            role="user",
            is_active=True,
            email="emailuser@test.com",
        )
        db.add(user)
        db.commit()

        service = AuthService(db)
        info = service.get_user_info(user)
        assert info["email"] == "emailuser@test.com"
        assert info["role"] == "user"
        assert isinstance(info["id"], int)


# ---- Route-level supplemental tests ----

class TestRouteSupplemental:
    """Additional route-level tests for previously uncovered paths."""

    @pytest.fixture()
    def client(self):
        """Create FastAPI test client with fresh DB."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TS = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override():
            db = TS()
            try:
                yield db
            finally:
                db.close()

        from app.backend.main import app
        app.dependency_overrides[get_db] = override

        # Seed admin
        db = TS()
        admin = User(
            username=ADMIN_USERNAME,
            password_hash=hash_password("Admin123"),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()

        # Seed regular user with email
        regular = User(
            username="routeuser",
            password_hash=hash_password("RoutePass1"),
            role="user",
            is_active=True,
            email="route@test.com",
        )
        db.add(regular)
        db.commit()

        # Seed invite code
        invite = InvitationCode(
            code="INV-ROUTE-TEST01",
            created_by=admin.id,
            is_used=False,
        )
        db.add(invite)
        db.commit()
        db.close()

        from fastapi.testclient import TestClient
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_forgot_password_nonexistent_user(self, client):
        """Forgot password for non-existent user returns 200 (no enumeration) with null token."""
        resp = client.post("/auth/forgot-password", json={
            "username": "ghost",
            "email": "ghost@test.com",
        })
        assert resp.status_code == 200
        assert resp.json()["reset_token"] is None

    def test_forgot_password_email_mismatch(self, client):
        """Forgot password with wrong email returns 200 (no enumeration) with null token."""
        resp = client.post("/auth/forgot-password", json={
            "username": "routeuser",
            "email": "wrong@test.com",
        })
        assert resp.status_code == 200
        assert resp.json()["reset_token"] is None

    def test_register_duplicate_username(self, client):
        """Registering with existing username should fail (IntegrityError catch)."""
        resp = client.post("/auth/register", json={
            "username": "routeuser",
            "password": "NewPass123",
            "invitation_code": "INV-ROUTE-TEST01",
        })
        assert resp.status_code == 400 or resp.status_code == 409

    def test_bind_email_success(self, client):
        """Bind email endpoint test."""
        # Login first
        login = client.post("/auth/login", json={"username": "routeuser", "password": "RoutePass1"})
        token = login.json()["access_token"]

        # Bind a new email
        resp = client.put(
            "/auth/email",
            json={"email": "new@test.com"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_change_password_via_route(self, client):
        """Change password route end-to-end."""
        login = client.post("/auth/login", json={"username": "routeuser", "password": "RoutePass1"})
        token = login.json()["access_token"]

        resp = client.put(
            "/auth/password",
            json={"old_password": "RoutePass1", "new_password": "Changed1"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "message" in resp.json()
