"""Authentication API routes — login, register, password management."""

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional

from app.backend.database.connection import get_db
from app.backend.auth.dependencies import get_current_user
from app.backend.auth.service import AuthService
from app.backend.auth.constants import (
    AuthError, InvalidCredentialsError, AccountLockedError,
    ForbiddenError, InvalidTokenError, WeakPasswordError,
    PASSWORD_MIN_LENGTH,
)
from app.backend.models.user import User

# Dev mode: return reset token in response (no email system).
# Set AUTH_SHOW_RESET_TOKEN=false in production.
SHOW_RESET_TOKEN = os.getenv("AUTH_SHOW_RESET_TOKEN", "true").lower() == "true"

router = APIRouter(prefix="/auth", tags=["auth"])


# ---- Request Schemas ----

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=128)
    invitation_code: str = Field(..., min_length=8, max_length=32)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=128)


class BindEmailRequest(BaseModel):
    email: str = Field(..., pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class ForgotPasswordRequest(BaseModel):
    username: str
    email: str = Field(..., pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=128)


# ---- Response Schemas ----

class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    role: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_token: Optional[str] = None  # Only populated in dev mode (no email system)


class MessageResponse(BaseModel):
    message: str


# ---- Routes ----

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """User login — returns JWT access token."""
    service = AuthService(db)
    try:
        result = service.login(request.username, request.password)
        return result
    except AccountLockedError as e:
        raise HTTPException(status_code=423, detail=str(e))
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """User registration — requires valid invitation code."""
    service = AuthService(db)
    try:
        result = service.register(request.username, request.password, request.invitation_code)
        return result
    except WeakPasswordError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except IntegrityError:
        raise HTTPException(status_code=400, detail="用户名已被注册")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current authenticated user info."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        role=current_user.role,
        created_at=current_user.created_at.isoformat() if current_user.created_at else None,
        updated_at=current_user.updated_at.isoformat() if current_user.updated_at else None,
    )


@router.put("/password", response_model=MessageResponse)
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change password for current user. Admin must use CLI."""
    service = AuthService(db)
    try:
        service.change_password(current_user, request.old_password, request.new_password)
        return {"message": "密码修改成功"}
    except ForbiddenError:
        raise HTTPException(status_code=403, detail="管理员密码只能通过 CLI 修改")
    except WeakPasswordError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except InvalidCredentialsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/email", response_model=MessageResponse)
async def bind_email(
    request: BindEmailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bind or update email address for current user."""
    service = AuthService(db)
    try:
        service.bind_email(current_user, request.email)
        return {"message": "邮箱绑定成功"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Initiate password reset. Returns reset token directly since no email system is configured."""
    service = AuthService(db)
    reset_token = service.forgot_password(request.username, request.email)

    if reset_token:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Password reset token generated for {request.username}")

    # Since no email system is configured, return the token directly
    # In production with email, set AUTH_SHOW_RESET_TOKEN=false
    # Always return the same message text to prevent user enumeration
    return {
        "message": "如果用户名和邮箱匹配，已生成密码重置令牌",
        "reset_token": reset_token if SHOW_RESET_TOKEN else None,
    }


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password using a reset token."""
    service = AuthService(db)
    try:
        service.reset_password(request.token, request.new_password)
        return {"message": "密码重置成功，请使用新密码登录"}
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except WeakPasswordError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (InvalidTokenError, AuthError) as e:
        raise HTTPException(status_code=400, detail=str(e))
