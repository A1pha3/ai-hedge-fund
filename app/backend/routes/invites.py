"""Invitation code management routes — CRUD for invites (admin) + public redeem."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from app.backend.database.connection import get_db
from app.backend.auth.dependencies import get_current_user, require_admin
from app.backend.auth.service import AuthService
from app.backend.auth.constants import (
    AuthError,
    ForbiddenError,
    ROLE_MEMBER,
    ROLE_VIEWER,
    VALID_ROLES,
)
from app.backend.models.user import User

router = APIRouter(prefix="/invites", tags=["invites"])


# ---- Request / Response Schemas ----

class CreateInviteRequest(BaseModel):
    """Request body for generating a new invitation code."""
    role_to_assign: str = Field(default=ROLE_MEMBER, description="Role to assign when code is redeemed")
    expires_days: Optional[int] = Field(default=7, description="Days until expiry (null = no expiry)")


class RedeemInviteRequest(BaseModel):
    """Request body for redeeming an invitation code (public registration)."""
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=8, max_length=128)


class InviteResponse(BaseModel):
    """Serialized invitation code."""
    id: int
    code: str
    is_used: bool
    is_revoked: bool
    role_to_assign: str
    expires_at: Optional[str] = None
    created_at: Optional[str] = None
    used_by: Optional[dict] = None
    revoked_at: Optional[str] = None
    revoked_by: Optional[dict] = None


class UserResponse(BaseModel):
    """Serialized user info returned after redeem."""
    id: int
    username: str
    email: Optional[str] = None
    role: str
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MessageResponse(BaseModel):
    message: str


class RevokeSessionResponse(BaseModel):
    user_id: int
    username: str
    message: str


class UserRoleUpdateRequest(BaseModel):
    role: str = Field(..., description="New role: admin, member, or viewer")


# ---- Admin-only Endpoints ----

@router.post("/", response_model=InviteResponse, status_code=201)
async def create_invite(
    request: CreateInviteRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Generate a new invitation code. Admin only.

    The generated code can be redeemed to create a new user with the specified role.
    """
    service = AuthService(db)
    try:
        return service.generate_invite(
            admin=admin,
            role_to_assign=request.role_to_assign,
            expires_days=request.expires_days,
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=list[InviteResponse])
async def list_invites(
    include_revoked: bool = Query(default=False, description="Include revoked invites"),
    include_used: bool = Query(default=True, description="Include used invites"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all invitation codes. Admin only."""
    service = AuthService(db)
    try:
        return service.list_invites(
            admin=admin,
            include_revoked=include_revoked,
            include_used=include_used,
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/{code}", response_model=InviteResponse)
async def revoke_invite(
    code: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Revoke an invitation code. Admin only.

    Only unused, non-expired codes can be revoked. Revoked codes cannot be redeemed.
    """
    service = AuthService(db)
    try:
        return service.revoke_invite(admin=admin, code=code)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- Public Endpoint ----

@router.post("/{code}/redeem", response_model=UserResponse, status_code=201)
async def redeem_invite(
    code: str,
    request: RedeemInviteRequest,
    db: Session = Depends(get_db),
):
    """Redeem an invitation code to register a new user.

    This is a public endpoint (no auth required). The invitation code must be
    valid, unused, unrevoked, and not expired.
    """
    service = AuthService(db)
    try:
        return service.redeem_invite(
            code=code,
            username=request.username,
            password=request.password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- Admin User Management ----

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users. Admin only."""
    service = AuthService(db)
    try:
        return service.list_users(admin=admin)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/users/{user_id}/revoke-session", response_model=RevokeSessionResponse)
async def revoke_user_session(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Force logout a user by invalidating all their sessions. Admin only.

    Increments the user's token_version, causing all existing JWTs to fail validation.
    The user will need to re-authenticate.
    """
    service = AuthService(db)
    try:
        return service.revoke_session(admin=admin, user_id=user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: int,
    request: UserRoleUpdateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update a user's role. Admin only.

    Changing a user's role also forces them to re-login (token_version incremented).
    Cannot downgrade admin role or modify own role.
    """
    service = AuthService(db)
    try:
        return service.update_user_role(admin=admin, user_id=user_id, new_role=request.role)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
