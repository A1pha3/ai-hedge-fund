"""Constants and custom exceptions for the auth module."""

import os
import re

# ---- Constants ----

ADMIN_USERNAME = os.getenv("AUTH_ADMIN_USERNAME", "einstein")

# Password complexity: >= 8 chars, at least one uppercase, one lowercase, one digit
PASSWORD_MIN_LENGTH = 8
PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")
PASSWORD_RULES = "密码至少 8 位，需包含大写字母、小写字母和数字"

# ---- Role Definitions ----
# Permission hierarchy: admin > member > viewer
# - admin:  full access + user/invite management
# - member: can create/modify resources (flows, runs, etc.)
# - viewer: read-only access
# Legacy "user" role is treated as "member" for backward compatibility.

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_VIEWER = "viewer"
ROLE_USER_LEGACY = "user"  # backward compat — treated as member

VALID_ROLES = {ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER, ROLE_USER_LEGACY}

# Roles that have write access (create/modify/delete resources)
WRITE_ROLES = {ROLE_ADMIN, ROLE_MEMBER, ROLE_USER_LEGACY}

# Roles that have admin-level access (user management, invite management)
ADMIN_ROLES = {ROLE_ADMIN}

# ---- Custom Exceptions ----


class AuthError(Exception):
    """Base exception for authentication errors."""
    pass


class InvalidCredentialsError(AuthError):
    """Raised when login credentials are invalid."""
    pass


class AccountLockedError(AuthError):
    """Raised when account is locked due to failed login attempts."""
    pass


class ForbiddenError(AuthError):
    """Raised when user lacks permission for an action."""
    pass


class InvalidTokenError(AuthError):
    """Raised when a token is invalid or expired."""
    pass


class WeakPasswordError(AuthError):
    """Raised when password does not meet complexity requirements."""
    pass
