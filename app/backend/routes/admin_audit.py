"""Admin audit log and session revoke API (Feature 2.5).

Endpoints:
  GET  /admin/audit-log?since=YYYY-MM-DD&limit=N    — list recent admin / security events
  POST /admin/revoke-session/{user_id}              — increment user.token_version to invalidate all JWTs
  GET  /admin/users                                  — list all users (admin only)
  POST /admin/users/{user_id}/toggle-active          — activate / deactivate a user

The audit log is a process-local ring buffer (deque, max 1000 events) since
the project does not yet have a persistent audit_log table. This is
intentional for the first iteration — the design doc (auth_design.md §7)
calls out "log 审计" as P6 hardening, and a persistent audit log is a
follow-up to that work.

Session revoke uses the existing token_version mechanism: incrementing
``user.token_version`` invalidates every JWT previously issued for that
user, forcing them to re-authenticate.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import require_admin
from app.backend.database.connection import get_db
from app.backend.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# In-memory ring buffer of recent admin / security events. Bounded so a
# long-running process does not leak memory.
_MAX_AUDIT_EVENTS = 1000
_audit_lock = threading.Lock()
_audit_buffer: deque[dict[str, Any]] = deque(maxlen=_MAX_AUDIT_EVENTS)


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _record_audit_event(
    *,
    actor: User,
    action: str,
    target_user_id: int | None = None,
    target_username: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append an event to the in-memory audit ring buffer.

    Returns the recorded event so the caller can include it in the response
    body (useful for tests that want to assert against the freshest entry).
    """
    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": _now_naive_utc().isoformat() + "Z",
        "actor_id": actor.id,
        "actor_username": actor.username,
        "action": action,
        "target_user_id": target_user_id,
        "target_username": target_username,
        "details": details or {},
    }
    with _audit_lock:
        _audit_buffer.append(event)
    logger.info(
        "admin_audit action=%s actor=%s target_user_id=%s",
        action,
        actor.username,
        target_user_id,
    )
    return event


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_id: str
    timestamp: str
    actor_id: int
    actor_username: str
    action: str
    target_user_id: int | None = None
    target_username: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    events: list[AuditEventResponse]
    total_count: int
    returned_count: int
    since: str | None = None
    limit: int


class RevokeSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    username: str
    previous_token_version: int
    new_token_version: int
    event: AuditEventResponse


class AdminUserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str | None
    role: str
    is_active: bool
    token_version: int
    created_at: str | None
    updated_at: str | None


class AdminUserListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    users: list[AdminUserSummary]
    total: int


class ToggleActiveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    username: str
    is_active: bool
    event: AuditEventResponse


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/audit-log", response_model=AuditLogResponse)
async def get_audit_log(
    since: str | None = Query(None, description="Filter events after this ISO timestamp (YYYY-MM-DD or full ISO)"),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    _admin: User = Depends(require_admin),
) -> AuditLogResponse:
    """Return the in-memory audit log, newest first.

    The buffer is bounded to 1000 events. ``since`` is a soft filter —
    pass an ISO date or datetime to drop events that are older.
    """
    cutoff: datetime | None = None
    if since:
        # Accept either YYYY-MM-DD or full ISO timestamps
        try:
            if "T" in since:
                cutoff = datetime.fromisoformat(since.replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                cutoff = datetime.strptime(since, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid 'since' value: {exc}") from exc

    with _audit_lock:
        snapshot = list(_audit_buffer)

    filtered: list[dict[str, Any]] = []
    for event in snapshot:
        ts = event.get("timestamp", "")
        if cutoff is not None and ts:
            try:
                event_dt = datetime.fromisoformat(ts.rstrip("Z"))
                if event_dt < cutoff:
                    continue
            except ValueError:
                # If we can't parse, include the event rather than silently drop
                pass
        filtered.append(event)
    # Newest first
    filtered.reverse()
    truncated = filtered[:limit]

    return AuditLogResponse(
        events=[AuditEventResponse(**e) for e in truncated],
        total_count=len(filtered),
        returned_count=len(truncated),
        since=since,
        limit=limit,
    )


@router.post("/revoke-session/{user_id}", response_model=RevokeSessionResponse)
async def revoke_user_session(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> RevokeSessionResponse:
    """Invalidate all active JWT tokens for the given user by incrementing
    ``user.token_version``. The user will be forced to re-authenticate.

    Admins cannot revoke their own session via this endpoint to avoid
    self-lockout.
    """
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="无法撤销当前管理员自己的会话,请联系其他管理员")

    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")

    previous = target.token_version or 0
    target.token_version = previous + 1
    db.add(target)
    db.commit()
    db.refresh(target)

    event = _record_audit_event(
        actor=admin,
        action="revoke_session",
        target_user_id=target.id,
        target_username=target.username,
        details={
            "previous_token_version": previous,
            "new_token_version": target.token_version,
        },
    )
    return RevokeSessionResponse(
        user_id=target.id,
        username=target.username,
        previous_token_version=previous,
        new_token_version=target.token_version or 0,
        event=AuditEventResponse(**event),
    )


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AdminUserListResponse:
    """List every user account (admin only). Used by the admin console
    dashboard to render the user table.
    """
    users = db.query(User).order_by(User.id.asc()).all()
    summaries = [
        AdminUserSummary(
            id=u.id,
            username=u.username,
            email=u.email,
            role=u.role,
            is_active=u.is_active,
            token_version=u.token_version or 0,
            created_at=u.created_at.isoformat() if u.created_at else None,
            updated_at=u.updated_at.isoformat() if u.updated_at else None,
        )
        for u in users
    ]
    return AdminUserListResponse(users=summaries, total=len(summaries))


@router.post("/users/{user_id}/toggle-active", response_model=ToggleActiveResponse)
async def toggle_user_active(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ToggleActiveResponse:
    """Flip ``is_active`` for a user. Deactivated users cannot log in.
    Reactivating restores login but does not require re-authentication
    for already-issued tokens (the caller can chain ``/revoke-session``
    to invalidate any outstanding JWTs).
    """
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="无法对当前管理员自己执行此操作")

    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")

    target.is_active = not bool(target.is_active)
    db.add(target)
    db.commit()
    db.refresh(target)

    event = _record_audit_event(
        actor=admin,
        action="toggle_user_active",
        target_user_id=target.id,
        target_username=target.username,
        details={"is_active": target.is_active},
    )
    return ToggleActiveResponse(
        user_id=target.id,
        username=target.username,
        is_active=bool(target.is_active),
        event=AuditEventResponse(**event),
    )


# ---------------------------------------------------------------------------
# Internal helpers (exposed for tests only)
# ---------------------------------------------------------------------------


def _reset_audit_buffer_for_tests() -> None:
    """Test-only helper to clear the ring buffer between test cases."""
    with _audit_lock:
        _audit_buffer.clear()


def _audit_buffer_size() -> int:
    """Test-only helper to inspect the buffer length."""
    with _audit_lock:
        return len(_audit_buffer)
