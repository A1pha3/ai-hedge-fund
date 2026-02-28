"""Constants and custom exceptions for the auth module."""

import os
import re

# ---- Constants ----

ADMIN_USERNAME = os.getenv("AUTH_ADMIN_USERNAME", "einstein")

# Password complexity: >= 8 chars, at least one uppercase, one lowercase, one digit
PASSWORD_MIN_LENGTH = 8
PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")
PASSWORD_RULES = "密码至少 8 位，需包含大写字母、小写字母和数字"

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
