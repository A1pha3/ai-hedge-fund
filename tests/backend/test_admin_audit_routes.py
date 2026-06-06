from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.auth.dependencies import get_current_user
from app.backend.database.connection import Base, get_db
from app.backend.models.user import User
from app.backend.routes import admin_audit
from app.backend.routes.admin_audit import router as admin_audit_router


def _admin_user() -> SimpleNamespace:
    return SimpleNamespace(id=1, username="root", role="admin", is_active=True)


def _build_client(db_session) -> TestClient:
    def _override_user() -> SimpleNamespace:
        return _admin_user()

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    app = FastAPI()
    app.include_router(admin_audit_router)
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


@pytest.fixture
def fresh_db():
    admin_audit._reset_audit_buffer_for_tests()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = test_session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        admin_audit._reset_audit_buffer_for_tests()


def test_list_users_returns_empty_when_no_users(fresh_db) -> None:
    client = _build_client(fresh_db)
    response = client.get("/admin/users")
    assert response.status_code == 200
    payload = response.json()
    assert payload["users"] == []
    assert payload["total"] == 0


def test_list_users_returns_existing_accounts(fresh_db) -> None:
    fresh_db.add(User(id=1, username="root", password_hash="x", role="admin", is_active=True))
    fresh_db.add(User(id=2, username="alice", password_hash="x", role="member", is_active=True))
    fresh_db.add(User(id=3, username="bob", password_hash="x", role="viewer", is_active=False))
    fresh_db.commit()

    client = _build_client(fresh_db)
    response = client.get("/admin/users")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert [u["username"] for u in payload["users"]] == ["root", "alice", "bob"]
    assert payload["users"][2]["is_active"] is False


def test_revoke_session_increments_token_version_and_records_audit(fresh_db) -> None:
    target = User(id=42, username="alice", password_hash="x", role="member", is_active=True, token_version=3)
    fresh_db.add(target)
    fresh_db.commit()

    client = _build_client(fresh_db)
    response = client.post("/admin/revoke-session/42")
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == 42
    assert payload["username"] == "alice"
    assert payload["previous_token_version"] == 3
    assert payload["new_token_version"] == 4
    # Audit event is returned inline
    event = payload["event"]
    assert event["action"] == "revoke_session"
    assert event["target_username"] == "alice"
    assert event["details"]["new_token_version"] == 4


def test_revoke_session_rejects_self(fresh_db) -> None:
    """Admins cannot revoke their own session (avoids self-lockout)."""
    fresh_db.add(User(id=1, username="root", password_hash="x", role="admin", is_active=True))
    fresh_db.commit()

    client = _build_client(fresh_db)
    response = client.post("/admin/revoke-session/1")
    assert response.status_code == 400
    assert "无法撤销" in response.json()["detail"]


def test_revoke_session_404_when_user_missing(fresh_db) -> None:
    client = _build_client(fresh_db)
    response = client.post("/admin/revoke-session/999")
    assert response.status_code == 404
    assert "999" in response.json()["detail"]


def test_toggle_active_flips_user_state(fresh_db) -> None:
    target = User(id=10, username="alice", password_hash="x", role="member", is_active=True)
    fresh_db.add(target)
    fresh_db.commit()

    client = _build_client(fresh_db)
    response = client.post("/admin/users/10/toggle-active")
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_active"] is False

    # Toggle back
    response2 = client.post("/admin/users/10/toggle-active")
    assert response2.status_code == 200
    assert response2.json()["is_active"] is True


def test_toggle_active_rejects_self(fresh_db) -> None:
    fresh_db.add(User(id=1, username="root", password_hash="x", role="admin", is_active=True))
    fresh_db.commit()
    client = _build_client(fresh_db)
    response = client.post("/admin/users/1/toggle-active")
    assert response.status_code == 400


def test_audit_log_returns_recorded_events_newest_first(fresh_db) -> None:
    target = User(id=2, username="bob", password_hash="x", role="member", is_active=True)
    fresh_db.add(target)
    fresh_db.commit()

    client = _build_client(fresh_db)
    # Trigger two events
    r1 = client.post("/admin/revoke-session/2")
    r2 = client.post("/admin/users/2/toggle-active")
    assert r1.status_code == 200
    assert r2.status_code == 200

    response = client.get("/admin/audit-log")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 2
    # Newest first
    assert payload["events"][0]["action"] == "toggle_user_active"
    assert payload["events"][1]["action"] == "revoke_session"


def test_audit_log_limit_truncates(fresh_db) -> None:
    target = User(id=2, username="bob", password_hash="x", role="member", is_active=True)
    fresh_db.add(target)
    fresh_db.commit()

    client = _build_client(fresh_db)
    for _ in range(5):
        client.post("/admin/users/2/toggle-active")
    response = client.get("/admin/audit-log?limit=3")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 5
    assert payload["returned_count"] == 3


def test_audit_log_since_filter(fresh_db) -> None:
    target = User(id=2, username="bob", password_hash="x", role="member", is_active=True)
    fresh_db.add(target)
    fresh_db.commit()
    client = _build_client(fresh_db)

    client.post("/admin/users/2/toggle-active")

    # Future timestamp: should return 0 events
    response = client.get("/admin/audit-log?since=2099-01-01")
    assert response.status_code == 200
    assert response.json()["total_count"] == 0

    # Past timestamp: should return all events
    response = client.get("/admin/audit-log?since=2020-01-01")
    assert response.status_code == 200
    assert response.json()["total_count"] >= 1


def test_audit_log_invalid_since_returns_400(fresh_db) -> None:
    client = _build_client(fresh_db)
    response = client.get("/admin/audit-log?since=not-a-date")
    assert response.status_code == 400


def test_audit_buffer_is_bounded(fresh_db) -> None:
    """Pushing more than 1000 events should keep only the latest."""
    target = User(id=2, username="bob", password_hash="x", role="member", is_active=True)
    fresh_db.add(target)
    fresh_db.commit()
    client = _build_client(fresh_db)
    for _ in range(1005):
        client.post("/admin/users/2/toggle-active")
    assert admin_audit._audit_buffer_size() <= 1000
