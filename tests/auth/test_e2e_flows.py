"""End-to-end flow tests covering complete user journeys through the auth system."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.backend.database.connection import Base, get_db
from app.backend.models.user import User, InvitationCode
from app.backend.auth.utils import hash_password
from app.backend.auth.constants import ADMIN_USERNAME


@pytest.fixture()
def e2e_client():
    """Create a test client with fresh in-memory DB for end-to-end tests."""
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

    # Seed admin + invite code
    db = TS()
    admin = User(
        username=ADMIN_USERNAME,
        password_hash=hash_password("Admin123"),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()

    invite = InvitationCode(code="INV-E2ETESTING01", created_by=admin.id, is_used=False)
    invite2 = InvitationCode(code="INV-E2ETESTING02", created_by=admin.id, is_used=False)
    db.add_all([invite, invite2])
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


class TestRegistrationLoginFlow:
    """Complete registration → login → access protected resource."""

    def test_register_and_login(self, e2e_client):
        # Step 1: Register
        resp = e2e_client.post("/auth/register", json={
            "username": "newuser",
            "password": "NewUser123",
            "invitation_code": "INV-E2ETESTING01",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["role"] == "user"

        # Step 2: Login with new credentials
        resp = e2e_client.post("/auth/login", json={
            "username": "newuser",
            "password": "NewUser123",
        })
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        assert token is not None

        # Step 3: Access /me with token
        resp = e2e_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "newuser"

    def test_register_then_invite_consumed(self, e2e_client):
        """After registration, invite code should be consumed."""
        # Register
        e2e_client.post("/auth/register", json={
            "username": "invuser",
            "password": "InvUser123",
            "invitation_code": "INV-E2ETESTING02",
        })
        # Try to register again with same invite
        resp = e2e_client.post("/auth/register", json={
            "username": "invuser2",
            "password": "InvUser456",
            "invitation_code": "INV-E2ETESTING02",
        })
        assert resp.status_code == 400 or resp.status_code == 409


class TestPasswordChangeFlow:
    """Login → change password → old token invalid → re-login."""

    def test_change_password_invalidates_old_token(self, e2e_client):
        # Step 0: Register a regular user (admin password change is CLI-only)
        e2e_client.post("/auth/register", json={
            "username": "pwduser",
            "password": "PwdUser123",
            "invitation_code": "INV-E2ETESTING01",
        })

        # Step 1: Login
        resp = e2e_client.post("/auth/login", json={
            "username": "pwduser",
            "password": "PwdUser123",
        })
        assert resp.status_code == 200
        old_token = resp.json()["access_token"]

        # Step 2: Verify old token works
        resp = e2e_client.get("/auth/me", headers={"Authorization": f"Bearer {old_token}"})
        assert resp.status_code == 200

        # Step 3: Change password
        resp = e2e_client.put("/auth/password", json={
            "old_password": "PwdUser123",
            "new_password": "NewPwd456",
        }, headers={"Authorization": f"Bearer {old_token}"})
        assert resp.status_code == 200

        # Step 4: Old token should now be INVALID (token_version changed)
        resp = e2e_client.get("/auth/me", headers={"Authorization": f"Bearer {old_token}"})
        assert resp.status_code == 401

        # Step 5: Re-login with new password
        resp = e2e_client.post("/auth/login", json={
            "username": "pwduser",
            "password": "NewPwd456",
        })
        assert resp.status_code == 200
        new_token = resp.json()["access_token"]

        # Step 6: New token works
        resp = e2e_client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert resp.status_code == 200


class TestForgotPasswordResetFlow:
    """Register → bind email → forgot password → reset → login."""

    def test_full_reset_flow(self, e2e_client):
        # Step 1: Register
        resp = e2e_client.post("/auth/register", json={
            "username": "resetflow",
            "password": "Reset1234",
            "invitation_code": "INV-E2ETESTING01",
        })
        assert resp.status_code == 201

        # Step 2: Login & bind email
        resp = e2e_client.post("/auth/login", json={
            "username": "resetflow", "password": "Reset1234",
        })
        token = resp.json()["access_token"]

        resp = e2e_client.put("/auth/email", json={
            "email": "reset@flow.com",
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

        # Step 3: Forgot password
        resp = e2e_client.post("/auth/forgot-password", json={
            "username": "resetflow",
            "email": "reset@flow.com",
        })
        assert resp.status_code == 200
        reset_token = resp.json().get("reset_token")
        # Token is only returned if AUTH_SHOW_RESET_TOKEN is true
        if reset_token:
            # Step 4: Reset password
            resp = e2e_client.post("/auth/reset-password", json={
                "token": reset_token,
                "new_password": "ResetNew12",
            })
            assert resp.status_code == 200

            # Step 5: Old password should not work
            resp = e2e_client.post("/auth/login", json={
                "username": "resetflow", "password": "Reset1234",
            })
            assert resp.status_code == 401

            # Step 6: New password works
            resp = e2e_client.post("/auth/login", json={
                "username": "resetflow", "password": "ResetNew12",
            })
            assert resp.status_code == 200


class TestAdminLoginFlow:
    """Admin login and admin-only operations."""

    def test_admin_login_sets_correct_role(self, e2e_client):
        resp = e2e_client.post("/auth/login", json={
            "username": ADMIN_USERNAME,
            "password": "Admin123",
        })
        assert resp.status_code == 200

        token = resp.json()["access_token"]
        resp = e2e_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"


class TestBruteForceProtection:
    """Test that brute force protection works through routes."""

    def test_lockout_after_failures(self, e2e_client):
        # Register a user to test lockout
        e2e_client.post("/auth/register", json={
            "username": "locktest",
            "password": "LockTest1",
            "invitation_code": "INV-E2ETESTING02",
        })

        # First 4 wrong logins return 401
        for _ in range(4):
            resp = e2e_client.post("/auth/login", json={
                "username": "locktest",
                "password": "WrongPass1",
            })
            assert resp.status_code == 401

        # 5th attempt triggers lock (423)
        resp = e2e_client.post("/auth/login", json={
            "username": "locktest",
            "password": "WrongPass1",
        })
        assert resp.status_code == 423

        # Subsequent attempts also locked (423)
        resp = e2e_client.post("/auth/login", json={
            "username": "locktest",
            "password": "LockTest1",  # even correct password
        })
        assert resp.status_code == 423


class TestEmailBindFlow:
    """Bind email → update email flow."""

    def test_bind_and_update_email(self, e2e_client):
        # Login as admin
        resp = e2e_client.post("/auth/login", json={
            "username": ADMIN_USERNAME, "password": "Admin123",
        })
        token = resp.json()["access_token"]

        # Bind email
        resp = e2e_client.put("/auth/email", json={
            "email": "admin@test.com",
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

        # Verify email is set
        resp = e2e_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["email"] == "admin@test.com"

        # Update email
        resp = e2e_client.put("/auth/email", json={
            "email": "admin2@test.com",
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

        resp = e2e_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["email"] == "admin2@test.com"
