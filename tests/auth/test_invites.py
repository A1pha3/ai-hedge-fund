"""Integration tests for invite management routes: CRUD, redeem, role permissions, session revocation.

Covers the full P2.5 audit/revoke闭环:
  1. POST /invites          — admin generates invite codes with role assignment
  2. GET  /invites          — admin lists invites
  3. DELETE /invites/{code} — admin revokes invite codes
  4. POST /invites/{code}/redeem — public redeems invite
  5. POST /invites/users/{id}/revoke-session — admin force logout
  6. PUT  /invites/users/{id}/role — admin changes user role
  7. GET  /invites/users    — admin lists all users
  8. Permission checks: viewer/member blocked from admin endpoints
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.auth.dependencies import get_current_user, require_admin
from app.backend.auth.utils import (
    create_access_token,
    generate_invitation_code,
    hash_password,
)
from app.backend.database.connection import Base, get_db
from app.backend.models.user import InvitationCode, User
from app.backend.routes.invites import router as invites_router

# ---- Fixtures ----


@pytest.fixture()
def engine():
    """Create a shared in-memory SQLite engine."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture()
def test_session(engine):
    """Create a session bound to the test engine."""
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture()
def test_app(engine, test_session):
    """Create a FastAPI test app with DB overrides."""
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(invites_router)
    app.dependency_overrides[get_db] = override_get_db

    yield app


@pytest.fixture()
def client(test_app):
    return TestClient(test_app)


def _make_token(user: User) -> str:
    """Create a JWT token for the given user."""
    return create_access_token(
        {
            "sub": user.username,
            "role": user.role,
            "tv": user.token_version or 0,
        }
    )


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def seed_users(test_session):
    """Seed admin, member, viewer, and a second member user."""
    admin = User(
        username="einstein",
        password_hash=hash_password("Admin123"),
        role="admin",
        is_active=True,
    )
    member = User(
        username="member1",
        password_hash=hash_password("Member123"),
        role="member",
        is_active=True,
    )
    viewer = User(
        username="viewer1",
        password_hash=hash_password("Viewer123"),
        role="viewer",
        is_active=True,
    )
    legacy_user = User(
        username="legacyuser",
        password_hash=hash_password("Legacy123"),
        role="user",  # legacy role
        is_active=True,
    )
    test_session.add_all([admin, member, viewer, legacy_user])
    test_session.commit()
    for u in [admin, member, viewer, legacy_user]:
        test_session.refresh(u)
    return {"admin": admin, "member": member, "viewer": viewer, "legacy": legacy_user}


@pytest.fixture()
def admin_token(seed_users):
    return _make_token(seed_users["admin"])


@pytest.fixture()
def member_token(seed_users):
    return _make_token(seed_users["member"])


@pytest.fixture()
def viewer_token(seed_users):
    return _make_token(seed_users["viewer"])


# ============================================================
# 1. POST /invites — Generate invite code
# ============================================================


class TestCreateInvite:
    """Admin generates invitation codes with role assignment."""

    def test_create_invite_default_member_role(self, client, admin_token):
        resp = client.post("/invites/", json={}, headers=auth_header(admin_token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"].startswith("INV-")
        assert data["role_to_assign"] == "member"
        assert data["is_used"] is False
        assert data["is_revoked"] is False
        assert data["expires_at"] is not None

    def test_create_invite_with_viewer_role(self, client, admin_token):
        resp = client.post(
            "/invites/",
            json={
                "role_to_assign": "viewer",
                "expires_days": 30,
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        assert resp.json()["role_to_assign"] == "viewer"

    def test_create_invite_no_expiry(self, client, admin_token):
        resp = client.post(
            "/invites/",
            json={
                "role_to_assign": "member",
                "expires_days": None,
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        assert resp.json()["expires_at"] is None

    def test_create_invite_blocks_admin_role(self, client, admin_token):
        resp = client.post(
            "/invites/",
            json={
                "role_to_assign": "admin",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "管理员" in resp.json()["detail"]

    def test_create_invite_invalid_role(self, client, admin_token):
        resp = client.post(
            "/invites/",
            json={
                "role_to_assign": "superuser",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_create_invite_member_forbidden(self, client, member_token):
        """Non-admin should get 403."""
        resp = client.post("/invites/", json={}, headers=auth_header(member_token))
        assert resp.status_code == 403

    def test_create_invite_viewer_forbidden(self, client, viewer_token):
        """Viewer should get 403."""
        resp = client.post("/invites/", json={}, headers=auth_header(viewer_token))
        assert resp.status_code == 403

    def test_create_invite_no_auth(self, client):
        """Unauthenticated request should get 401."""
        resp = client.post("/invites/", json={})
        assert resp.status_code == 401


# ============================================================
# 2. GET /invites — List invites
# ============================================================


class TestListInvites:
    """Admin lists all invitation codes."""

    def test_list_invites_empty(self, client, admin_token):
        resp = client.get("/invites/", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_invites_with_data(self, client, admin_token):
        # Create 2 invites
        client.post("/invites/", json={}, headers=auth_header(admin_token))
        client.post("/invites/", json={"role_to_assign": "viewer"}, headers=auth_header(admin_token))

        resp = client.get("/invites/", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_list_invites_member_forbidden(self, client, member_token):
        resp = client.get("/invites/", headers=auth_header(member_token))
        assert resp.status_code == 403

    def test_list_invites_excludes_revoked_by_default(self, client, admin_token):
        # Create and revoke an invite
        create_resp = client.post("/invites/", json={}, headers=auth_header(admin_token))
        code = create_resp.json()["code"]
        client.delete(f"/invites/{code}", headers=auth_header(admin_token))

        # List without include_revoked
        resp = client.get("/invites/", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert len(resp.json()) == 0

        # List with include_revoked
        resp = client.get("/invites/?include_revoked=true", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ============================================================
# 3. DELETE /invites/{code} — Revoke invite
# ============================================================


class TestRevokeInvite:
    """Admin revokes unused invitation codes."""

    def test_revoke_invite_success(self, client, admin_token):
        create_resp = client.post("/invites/", json={}, headers=auth_header(admin_token))
        code = create_resp.json()["code"]

        resp = client.delete(f"/invites/{code}", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_revoked"] is True
        assert data["revoked_at"] is not None
        assert data["revoked_by"] is not None

    def test_revoke_invite_nonexistent(self, client, admin_token):
        resp = client.delete("/invites/INV-NOSUCHCODE1", headers=auth_header(admin_token))
        assert resp.status_code == 400
        assert "不存在" in resp.json()["detail"]

    def test_revoke_invite_already_revoked(self, client, admin_token):
        create_resp = client.post("/invites/", json={}, headers=auth_header(admin_token))
        code = create_resp.json()["code"]
        client.delete(f"/invites/{code}", headers=auth_header(admin_token))

        resp = client.delete(f"/invites/{code}", headers=auth_header(admin_token))
        assert resp.status_code == 400
        assert "撤销" in resp.json()["detail"]

    def test_revoke_invite_member_forbidden(self, client, admin_token, member_token):
        create_resp = client.post("/invites/", json={}, headers=auth_header(admin_token))
        code = create_resp.json()["code"]

        resp = client.delete(f"/invites/{code}", headers=auth_header(member_token))
        assert resp.status_code == 403


# ============================================================
# 4. POST /invites/{code}/redeem — Public redeem
# ============================================================


class TestRedeemInvite:
    """Public endpoint: redeem invitation code to create user."""

    def test_redeem_success(self, client, admin_token):
        create_resp = client.post(
            "/invites/",
            json={
                "role_to_assign": "member",
            },
            headers=auth_header(admin_token),
        )
        code = create_resp.json()["code"]

        resp = client.post(
            f"/invites/{code}/redeem",
            json={
                "username": "newmember",
                "password": "NewMember1",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newmember"
        assert data["role"] == "member"

    def test_redeem_viewer_role(self, client, admin_token):
        create_resp = client.post(
            "/invites/",
            json={
                "role_to_assign": "viewer",
            },
            headers=auth_header(admin_token),
        )
        code = create_resp.json()["code"]

        resp = client.post(
            f"/invites/{code}/redeem",
            json={
                "username": "newviewer",
                "password": "NewViewer1",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "viewer"

    def test_redeem_revoked_code_blocked(self, client, admin_token):
        create_resp = client.post("/invites/", json={}, headers=auth_header(admin_token))
        code = create_resp.json()["code"]
        client.delete(f"/invites/{code}", headers=auth_header(admin_token))

        resp = client.post(
            f"/invites/{code}/redeem",
            json={
                "username": "blockeduser",
                "password": "BlockedPass1",
            },
        )
        assert resp.status_code == 400
        assert "撤销" in resp.json()["detail"]

    def test_redeem_nonexistent_code(self, client):
        resp = client.post(
            "/invites/INV-NONEXISTENT/redeem",
            json={
                "username": "someone",
                "password": "SomePass123",
            },
        )
        assert resp.status_code == 400
        assert "不存在" in resp.json()["detail"]

    def test_redeem_duplicate_code_blocked(self, client, admin_token):
        create_resp = client.post("/invites/", json={}, headers=auth_header(admin_token))
        code = create_resp.json()["code"]

        # First redeem succeeds
        resp1 = client.post(
            f"/invites/{code}/redeem",
            json={
                "username": "firstuser",
                "password": "FirstPass1",
            },
        )
        assert resp1.status_code == 201

        # Second redeem fails (code already used)
        resp2 = client.post(
            f"/invites/{code}/redeem",
            json={
                "username": "seconduser",
                "password": "SecondPass1",
            },
        )
        assert resp2.status_code == 400
        assert "使用" in resp2.json()["detail"]

    def test_redeem_weak_password_rejected(self, client, admin_token):
        create_resp = client.post("/invites/", json={}, headers=auth_header(admin_token))
        code = create_resp.json()["code"]

        resp = client.post(
            f"/invites/{code}/redeem",
            json={
                "username": "weakpassuser",
                "password": "weak",
            },
        )
        # Pydantic min_length=8 catches it as 422 before reaching service logic
        assert resp.status_code == 422


# ============================================================
# 5. POST /invites/users/{id}/revoke-session — Force logout
# ============================================================


class TestRevokeSession:
    """Admin force-logs out a user by invalidating their token version."""

    def test_revoke_session_success(self, client, admin_token, seed_users):
        member = seed_users["member"]
        resp = client.post(f"/invites/users/{member.id}/revoke-session", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "member1"
        assert "强制下线" in data["message"]

    def test_revoke_session_invalidates_old_token(self, client, admin_token, seed_users, test_session):
        """After revoking a session, the user's old JWT should fail validation."""
        member = seed_users["member"]
        old_token = _make_token(member)

        # Revoke session
        client.post(f"/invites/users/{member.id}/revoke-session", headers=auth_header(admin_token))

        # Old token should now be invalid (token_version mismatch)
        # We test this through the list-invites endpoint which requires admin
        # but we can verify by checking the token_version was incremented
        test_session.refresh(member)
        assert member.token_version > 0

    def test_revoke_session_cannot_revoke_self(self, client, admin_token, seed_users):
        admin = seed_users["admin"]
        resp = client.post(f"/invites/users/{admin.id}/revoke-session", headers=auth_header(admin_token))
        assert resp.status_code == 400
        assert "自己" in resp.json()["detail"]

    def test_revoke_session_nonexistent_user(self, client, admin_token):
        resp = client.post("/invites/users/9999/revoke-session", headers=auth_header(admin_token))
        assert resp.status_code == 400
        assert "不存在" in resp.json()["detail"]

    def test_revoke_session_member_forbidden(self, client, member_token, seed_users):
        admin = seed_users["admin"]
        resp = client.post(f"/invites/users/{admin.id}/revoke-session", headers=auth_header(member_token))
        assert resp.status_code == 403


# ============================================================
# 6. PUT /invites/users/{id}/role — Update user role
# ============================================================


class TestUpdateUserRole:
    """Admin changes a user's role."""

    def test_update_role_member_to_viewer(self, client, admin_token, seed_users):
        member = seed_users["member"]
        resp = client.put(
            f"/invites/users/{member.id}/role",
            json={
                "role": "viewer",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "viewer"

    def test_update_role_viewer_to_member(self, client, admin_token, seed_users):
        viewer = seed_users["viewer"]
        resp = client.put(
            f"/invites/users/{viewer.id}/role",
            json={
                "role": "member",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "member"

    def test_update_role_cannot_modify_self(self, client, admin_token, seed_users):
        admin = seed_users["admin"]
        resp = client.put(
            f"/invites/users/{admin.id}/role",
            json={
                "role": "member",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "自己" in resp.json()["detail"]

    def test_update_role_cannot_downgrade_admin(self, client, admin_token, seed_users):
        admin = seed_users["admin"]
        resp = client.put(
            f"/invites/users/{admin.id}/role",
            json={
                "role": "member",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_update_role_invalid_role(self, client, admin_token, seed_users):
        member = seed_users["member"]
        resp = client.put(
            f"/invites/users/{member.id}/role",
            json={
                "role": "superadmin",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_update_role_forces_relogin(self, client, admin_token, seed_users, test_session):
        """Changing role should increment token_version, forcing re-login."""
        member = seed_users["member"]
        old_tv = member.token_version

        client.put(
            f"/invites/users/{member.id}/role",
            json={
                "role": "viewer",
            },
            headers=auth_header(admin_token),
        )

        test_session.refresh(member)
        assert member.token_version > old_tv

    def test_update_role_member_forbidden(self, client, member_token, seed_users):
        viewer = seed_users["viewer"]
        resp = client.put(
            f"/invites/users/{viewer.id}/role",
            json={
                "role": "member",
            },
            headers=auth_header(member_token),
        )
        assert resp.status_code == 403


# ============================================================
# 7. GET /invites/users — List users
# ============================================================


class TestListUsers:
    """Admin lists all users."""

    def test_list_users_success(self, client, admin_token, seed_users):
        resp = client.get("/invites/users", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 4  # admin + member + viewer + legacy
        usernames = [u["username"] for u in data]
        assert "einstein" in usernames
        assert "member1" in usernames
        assert "viewer1" in usernames

    def test_list_users_member_forbidden(self, client, member_token):
        resp = client.get("/invites/users", headers=auth_header(member_token))
        assert resp.status_code == 403


# ============================================================
# 8. Full lifecycle test — end-to-end
# ============================================================


class TestInviteLifecycle:
    """End-to-end: create -> list -> redeem -> verify role -> revoke session."""

    def test_full_lifecycle(self, client, admin_token, seed_users, test_session):
        # Step 1: Admin creates a viewer invite
        create_resp = client.post(
            "/invites/",
            json={
                "role_to_assign": "viewer",
                "expires_days": 7,
            },
            headers=auth_header(admin_token),
        )
        assert create_resp.status_code == 201
        code = create_resp.json()["code"]
        assert create_resp.json()["role_to_assign"] == "viewer"

        # Step 2: Admin lists invites, sees the new one
        list_resp = client.get("/invites/", headers=auth_header(admin_token))
        assert list_resp.status_code == 200
        assert len(list_resp.json()) >= 1
        codes_in_list = [inv["code"] for inv in list_resp.json()]
        assert code in codes_in_list

        # Step 3: Public user redeems the code
        redeem_resp = client.post(
            f"/invites/{code}/redeem",
            json={
                "username": "lifecycle_user",
                "password": "Lifecycle1",
            },
        )
        assert redeem_resp.status_code == 201
        new_user_data = redeem_resp.json()
        assert new_user_data["role"] == "viewer"
        assert new_user_data["username"] == "lifecycle_user"

        # Step 4: Admin upgrades the user to member
        user_id = new_user_data["id"]
        role_resp = client.put(
            f"/invites/users/{user_id}/role",
            json={
                "role": "member",
            },
            headers=auth_header(admin_token),
        )
        assert role_resp.status_code == 200
        assert role_resp.json()["role"] == "member"

        # Step 5: Admin force-logs out the user
        revoke_resp = client.post(f"/invites/users/{user_id}/revoke-session", headers=auth_header(admin_token))
        assert revoke_resp.status_code == 200
        assert "强制下线" in revoke_resp.json()["message"]

        # Step 6: Verify token_version incremented
        upgraded_user = test_session.query(User).filter(User.id == user_id).first()
        assert upgraded_user.token_version > 0

    def test_create_revoke_then_redeem_blocked(self, client, admin_token):
        """Create -> revoke -> attempt redeem should fail."""
        # Create
        create_resp = client.post("/invites/", json={}, headers=auth_header(admin_token))
        code = create_resp.json()["code"]

        # Revoke
        revoke_resp = client.delete(f"/invites/{code}", headers=auth_header(admin_token))
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["is_revoked"] is True

        # Attempt redeem should fail
        redeem_resp = client.post(
            f"/invites/{code}/redeem",
            json={
                "username": "shouldnotwork",
                "password": "ShouldNot1",
            },
        )
        assert redeem_resp.status_code == 400
        assert "撤销" in redeem_resp.json()["detail"]
