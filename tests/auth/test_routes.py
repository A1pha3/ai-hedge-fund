"""Integration tests for auth API routes using FastAPI TestClient."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.connection import Base, get_db
from app.backend.models.user import User, InvitationCode
from app.backend.routes.auth import router
from app.backend.auth.utils import hash_password, generate_invitation_code, create_access_token, create_reset_token


# ---- Fixtures ----

@pytest.fixture()
def test_app():
    """Create a FastAPI test app with an in-memory database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # Share single connection for in-memory DB
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_get_db

    # Seed admin user
    db = TestSession()
    admin = User(
        username="einstein",
        password_hash=hash_password("Admin123"),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()

    # Seed regular user
    regular = User(
        username="testuser",
        password_hash=hash_password("Test1234"),
        email="test@example.com",
        role="user",
        is_active=True,
    )
    db.add(regular)
    db.commit()

    # Seed valid invitation code
    invite = InvitationCode(
        code="INV-VALIDTEST01",
        created_by=admin.id,
        is_used=False,
    )
    db.add(invite)
    db.commit()
    db.close()

    yield app, TestSession

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def client(test_app):
    app, _ = test_app
    return TestClient(app)


@pytest.fixture()
def auth_token(client):
    """Get a valid auth token for testuser."""
    resp = client.post("/auth/login", json={"username": "testuser", "password": "Test1234"})
    return resp.json()["access_token"]


@pytest.fixture()
def admin_token(client):
    """Get a valid auth token for admin."""
    resp = client.post("/auth/login", json={"username": "einstein", "password": "Admin123"})
    return resp.json()["access_token"]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- POST /auth/login ----

class TestLoginRoute:
    """Integration tests for the login endpoint."""

    def test_login_success(self, client):
        resp = client.post("/auth/login", json={"username": "testuser", "password": "Test1234"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == "testuser"

    def test_login_wrong_password(self, client):
        resp = client.post("/auth/login", json={"username": "testuser", "password": "WrongOne1"})
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/auth/login", json={"username": "nobody", "password": "Whatever1"})
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/auth/login", json={"username": "testuser"})
        assert resp.status_code == 422  # Pydantic validation

    def test_login_lockout(self, client):
        """After 5 failed attempts, account should lock."""
        for _ in range(5):
            client.post("/auth/login", json={"username": "testuser", "password": "Wrong"})
        # 6th attempt (correct password) should give 423
        resp = client.post("/auth/login", json={"username": "testuser", "password": "Test1234"})
        assert resp.status_code == 423


# ---- POST /auth/register ----

class TestRegisterRoute:
    """Integration tests for the register endpoint."""

    def test_register_success(self, client):
        resp = client.post("/auth/register", json={
            "username": "newuser",
            "password": "NewPass1234",
            "invitation_code": "INV-VALIDTEST01",
        })
        assert resp.status_code == 201
        assert resp.json()["username"] == "newuser"
        assert resp.json()["role"] == "user"

    def test_register_invalid_invite(self, client):
        resp = client.post("/auth/register", json={
            "username": "newuser2",
            "password": "NewPass1234",
            "invitation_code": "INV-DOESNTEXIST",
        })
        assert resp.status_code == 400

    def test_register_weak_password(self, client):
        resp = client.post("/auth/register", json={
            "username": "weakuser",
            "password": "weak",
            "invitation_code": "INV-VALIDTEST01",
        })
        # Either 422 from Pydantic (min_length) or from WeakPasswordError
        assert resp.status_code == 422

    def test_register_duplicate_username(self, client):
        resp = client.post("/auth/register", json={
            "username": "testuser",
            "password": "NewPass1234",
            "invitation_code": "INV-VALIDTEST01",
        })
        assert resp.status_code == 400

    def test_register_username_validation(self, client):
        """Username should match ^[a-zA-Z0-9_]+$ pattern."""
        resp = client.post("/auth/register", json={
            "username": "bad user!",
            "password": "NewPass1234",
            "invitation_code": "INV-VALIDTEST01",
        })
        assert resp.status_code == 422  # Pydantic pattern validation


# ---- GET /auth/me ----

class TestMeRoute:
    """Tests for the /auth/me endpoint."""

    def test_me_authenticated(self, client, auth_token):
        resp = client.get("/auth/me", headers=auth_header(auth_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"
        assert data["role"] == "user"
        assert "updated_at" in data

    def test_me_no_token(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_invalid_token(self, client):
        resp = client.get("/auth/me", headers=auth_header("invalid.token.here"))
        assert resp.status_code == 401


# ---- PUT /auth/password ----

class TestChangePasswordRoute:
    """Tests for the password change endpoint."""

    def test_change_password_success(self, client, auth_token):
        resp = client.put("/auth/password", json={
            "old_password": "Test1234",
            "new_password": "NewPass456",
        }, headers=auth_header(auth_token))
        assert resp.status_code == 200
        assert "成功" in resp.json()["message"]

    def test_change_password_wrong_old(self, client, auth_token):
        resp = client.put("/auth/password", json={
            "old_password": "WrongOld1",
            "new_password": "NewPass456",
        }, headers=auth_header(auth_token))
        assert resp.status_code == 400

    def test_change_password_weak_new(self, client, auth_token):
        resp = client.put("/auth/password", json={
            "old_password": "Test1234",
            "new_password": "weak",
        }, headers=auth_header(auth_token))
        assert resp.status_code == 422

    def test_change_password_no_auth(self, client):
        resp = client.put("/auth/password", json={
            "old_password": "Test1234",
            "new_password": "NewPass456",
        })
        assert resp.status_code == 401

    def test_change_password_admin_blocked(self, client, admin_token):
        resp = client.put("/auth/password", json={
            "old_password": "Admin123",
            "new_password": "NewAdmin456",
        }, headers=auth_header(admin_token))
        assert resp.status_code == 403


# ---- PUT /auth/email ----

class TestBindEmailRoute:
    """Tests for the email binding endpoint."""

    def test_bind_email_success(self, client, admin_token):
        resp = client.put("/auth/email", json={
            "email": "admin@hedge.fund",
        }, headers=auth_header(admin_token))
        assert resp.status_code == 200

    def test_bind_email_invalid_format(self, client, auth_token):
        resp = client.put("/auth/email", json={
            "email": "not-an-email",
        }, headers=auth_header(auth_token))
        assert resp.status_code == 422

    def test_bind_email_no_auth(self, client):
        resp = client.put("/auth/email", json={"email": "a@b.com"})
        assert resp.status_code == 401


# ---- POST /auth/forgot-password ----

class TestForgotPasswordRoute:
    """Tests for the forgot-password endpoint."""

    def test_forgot_password_valid(self, client):
        resp = client.post("/auth/forgot-password", json={
            "username": "testuser",
            "email": "test@example.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        # In dev mode (default), reset_token should be present
        assert data.get("reset_token") is not None

    def test_forgot_password_wrong_email(self, client):
        resp = client.post("/auth/forgot-password", json={
            "username": "testuser",
            "email": "wrong@example.com",
        })
        assert resp.status_code == 200  # Always 200 to prevent enumeration
        data = resp.json()
        assert "message" in data
        assert data.get("reset_token") is None

    def test_forgot_password_consistent_message(self, client):
        """Both valid and invalid should return the same message text."""
        valid = client.post("/auth/forgot-password", json={
            "username": "testuser",
            "email": "test@example.com",
        })
        invalid = client.post("/auth/forgot-password", json={
            "username": "nobody",
            "email": "nobody@example.com",
        })
        assert valid.json()["message"] == invalid.json()["message"]


# ---- POST /auth/reset-password ----

class TestResetPasswordRoute:
    """Tests for the reset-password endpoint."""

    def test_reset_password_success(self, client):
        # First get a reset token
        resp = client.post("/auth/forgot-password", json={
            "username": "testuser",
            "email": "test@example.com",
        })
        reset_token = resp.json()["reset_token"]

        # Reset password
        resp = client.post("/auth/reset-password", json={
            "token": reset_token,
            "new_password": "ResetPass1",
        })
        assert resp.status_code == 200
        assert "成功" in resp.json()["message"]

        # Verify login with new password works
        resp = client.post("/auth/login", json={
            "username": "testuser",
            "password": "ResetPass1",
        })
        assert resp.status_code == 200

    def test_reset_password_invalid_token(self, client):
        resp = client.post("/auth/reset-password", json={
            "token": "invalid.token",
            "new_password": "ResetPass1",
        })
        assert resp.status_code == 400

    def test_reset_password_weak_new_password(self, client):
        # Get valid token
        resp = client.post("/auth/forgot-password", json={
            "username": "testuser",
            "email": "test@example.com",
        })
        reset_token = resp.json()["reset_token"]

        resp = client.post("/auth/reset-password", json={
            "token": reset_token,
            "new_password": "weak",
        })
        assert resp.status_code == 422
