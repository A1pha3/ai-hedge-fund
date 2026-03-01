"""Tests for FastAPI auth dependencies (get_current_user, require_admin)."""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.connection import Base, get_db
from app.backend.models.user import User
from app.backend.auth.dependencies import get_current_user, require_admin
from app.backend.auth.utils import hash_password, create_access_token, create_reset_token


@pytest.fixture()
def dep_app():
    """Create a minimal FastAPI app to test dependencies."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
    app.dependency_overrides[get_db] = override_get_db

    # Test endpoints using the dependencies
    @app.get("/test-auth")
    async def test_auth(user: User = Depends(get_current_user)):
        return {"username": user.username, "role": user.role}

    @app.get("/test-admin")
    async def test_admin(user: User = Depends(require_admin)):
        return {"username": user.username, "role": user.role}

    # Seed users
    db = TestSession()
    admin = User(
        username="einstein",
        password_hash=hash_password("Admin123"),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()

    regular = User(
        username="regular",
        password_hash=hash_password("Regu1234"),
        role="user",
        is_active=True,
    )
    db.add(regular)
    db.commit()

    inactive = User(
        username="disabled",
        password_hash=hash_password("Disabled1"),
        role="user",
        is_active=False,
    )
    db.add(inactive)
    db.commit()
    db.close()

    yield app


@pytest.fixture()
def client(dep_app):
    return TestClient(dep_app)


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- get_current_user ----

class TestGetCurrentUser:
    """Tests for the get_current_user dependency."""

    def test_valid_token(self, client):
        token = create_access_token({"sub": "regular", "role": "user", "tv": 0})
        resp = client.get("/test-auth", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["username"] == "regular"

    def test_no_token(self, client):
        resp = client.get("/test-auth")
        assert resp.status_code == 401
        assert "未提供" in resp.json()["detail"]

    def test_invalid_token(self, client):
        resp = client.get("/test-auth", headers=auth_header("invalid.jwt.token"))
        assert resp.status_code == 401
        assert "无效" in resp.json()["detail"]

    def test_reset_token_rejected(self, client):
        """Reset tokens should not be accepted as access tokens."""
        token = create_reset_token("regular")
        resp = client.get("/test-auth", headers=auth_header(token))
        assert resp.status_code == 401

    def test_wrong_token_version(self, client, dep_app):
        """Token with stale token_version should be rejected."""
        # Create token with tv=99 but user has tv=0
        token = create_access_token({"sub": "regular", "role": "user", "tv": 99})
        resp = client.get("/test-auth", headers=auth_header(token))
        assert resp.status_code == 401
        assert "失效" in resp.json()["detail"]

    def test_inactive_user_rejected(self, client):
        """Inactive user should be rejected."""
        token = create_access_token({"sub": "disabled", "role": "user", "tv": 0})
        resp = client.get("/test-auth", headers=auth_header(token))
        assert resp.status_code == 401
        assert "禁用" in resp.json()["detail"]

    def test_nonexistent_user(self, client):
        """Token for deleted user should fail."""
        token = create_access_token({"sub": "ghost", "role": "user", "tv": 0})
        resp = client.get("/test-auth", headers=auth_header(token))
        assert resp.status_code == 401

    def test_token_without_sub(self, client):
        """Token missing 'sub' claim should fail."""
        token = create_access_token({"role": "user"})
        resp = client.get("/test-auth", headers=auth_header(token))
        assert resp.status_code == 401


# ---- require_admin ----

class TestRequireAdmin:
    """Tests for the require_admin dependency."""

    def test_admin_access(self, client):
        token = create_access_token({"sub": "einstein", "role": "admin", "tv": 0})
        resp = client.get("/test-admin", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_regular_user_rejected(self, client):
        token = create_access_token({"sub": "regular", "role": "user", "tv": 0})
        resp = client.get("/test-admin", headers=auth_header(token))
        assert resp.status_code == 403
        assert "权限" in resp.json()["detail"]

    def test_no_token_401(self, client):
        resp = client.get("/test-admin")
        assert resp.status_code == 401


# ---- Locked account ----

class TestLockedAccount:
    """Test locked account rejection in get_current_user."""

    def test_locked_user_rejected(self, dep_app):
        """A user whose locked_until is in the future should get 423."""
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

        # Create a locked user
        db = TS()
        from datetime import timedelta
        locked_user = User(
            username="locked_guy",
            password_hash=hash_password("Lock1234"),
            role="user",
            is_active=True,
            locked_until=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15),
        )
        db.add(locked_user)
        db.commit()
        db.close()

        app = FastAPI()
        app.dependency_overrides[get_db] = override

        @app.get("/locked-test")
        async def locked_endpoint(user: User = Depends(get_current_user)):
            return {"username": user.username}

        client = TestClient(app)
        token = create_access_token({"sub": "locked_guy", "role": "user", "tv": 0})
        resp = client.get("/locked-test", headers=auth_header(token))
        assert resp.status_code == 423
        assert "锁定" in resp.json()["detail"]


# ---- AUTH_DISABLED ----

class TestAuthDisabled:
    """Tests for AUTH_DISABLED=true (development bypass)."""

    def test_auth_disabled_returns_admin(self):
        """With AUTH_DISABLED=true, get_current_user returns admin without token."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TS = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        # Seed admin
        db = TS()
        admin = User(username="einstein", password_hash=hash_password("Admin123"), role="admin", is_active=True)
        db.add(admin)
        db.commit()
        db.close()

        def override():
            db = TS()
            try:
                yield db
            finally:
                db.close()

        app = FastAPI()
        app.dependency_overrides[get_db] = override

        @app.get("/disabled-test")
        async def disabled_endpoint(user: User = Depends(get_current_user)):
            return {"username": user.username, "role": user.role}

        with patch("app.backend.auth.dependencies.AUTH_DISABLED", True):
            client = TestClient(app)
            resp = client.get("/disabled-test")
            assert resp.status_code == 200
            assert resp.json()["username"] == "einstein"
            assert resp.json()["role"] == "admin"

    def test_auth_disabled_fallback_any_admin(self):
        """With AUTH_DISABLED=true and no 'einstein', falls back to any admin."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TS = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        db = TS()
        other_admin = User(username="otheradmin", password_hash=hash_password("Admin123"), role="admin", is_active=True)
        db.add(other_admin)
        db.commit()
        db.close()

        def override():
            db = TS()
            try:
                yield db
            finally:
                db.close()

        app = FastAPI()
        app.dependency_overrides[get_db] = override

        @app.get("/disabled-test2")
        async def disabled_endpoint2(user: User = Depends(get_current_user)):
            return {"username": user.username}

        with patch("app.backend.auth.dependencies.AUTH_DISABLED", True):
            client = TestClient(app)
            resp = client.get("/disabled-test2")
            assert resp.status_code == 200
            assert resp.json()["username"] == "otheradmin"

    def test_auth_disabled_no_users_mock(self):
        """With AUTH_DISABLED=true and empty DB, returns transient mock user with id=-1."""
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

        app = FastAPI()
        app.dependency_overrides[get_db] = override

        @app.get("/disabled-test3")
        async def disabled_endpoint3(user: User = Depends(get_current_user)):
            return {"username": user.username, "id": user.id}

        with patch("app.backend.auth.dependencies.AUTH_DISABLED", True):
            client = TestClient(app)
            resp = client.get("/disabled-test3")
            assert resp.status_code == 200
            assert resp.json()["username"] == "dev"
            assert resp.json()["id"] == -1
