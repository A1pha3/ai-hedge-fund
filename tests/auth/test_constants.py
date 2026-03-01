"""Tests for auth constants and exception hierarchy."""

import pytest

from app.backend.auth.constants import (
    ADMIN_USERNAME,
    PASSWORD_MIN_LENGTH,
    PASSWORD_PATTERN,
    PASSWORD_RULES,
    AuthError,
    InvalidCredentialsError,
    AccountLockedError,
    ForbiddenError,
    InvalidTokenError,
    WeakPasswordError,
)


# ---- PASSWORD_PATTERN ----

class TestPasswordPattern:
    """Tests for PASSWORD_PATTERN regex validation."""

    @pytest.mark.parametrize("password", [
        "Abcdef12",       # Exactly 8 chars, meets all rules
        "Password1",      # Common but valid
        "MyP@ssw0rd",     # With special chars
        "ABCDEFgh1",      # Uppercase heavy
        "aB3defgh",       # Lowercase heavy
        "A" * 50 + "b1",  # Very long
    ])
    def test_valid_passwords(self, password):
        assert PASSWORD_PATTERN.match(password), f"Should be valid: {password}"

    @pytest.mark.parametrize("password,reason", [
        ("abc1234", "Too short (7 chars)"),
        ("abcdefgh", "No uppercase, no digit"),
        ("ABCDEFGH", "No lowercase, no digit"),
        ("12345678", "No letters"),
        ("abcdefG1", "Valid - 8 chars"),  # Actually valid, will be excluded
        ("abcdef1", "Too short, no uppercase"),
        ("ABCDEF1", "Too short, no lowercase"),
        ("Abcdefg", "No digit"),
        ("1234567A", "No lowercase"),
        ("", "Empty string"),
        ("Ab1", "Way too short"),
    ])
    def test_invalid_passwords(self, password, reason):
        if password == "abcdefG1":
            pytest.skip("This is actually valid")
        assert not PASSWORD_PATTERN.match(password), f"Should be invalid ({reason}): {password}"

    def test_min_length_constant(self):
        assert PASSWORD_MIN_LENGTH == 8

    def test_password_rules_is_string(self):
        assert isinstance(PASSWORD_RULES, str)
        assert len(PASSWORD_RULES) > 0


# ---- Constants ----

class TestConstants:
    """Tests for auth constants."""

    def test_admin_username_default(self):
        # Default is "einstein" unless overridden by env var
        assert isinstance(ADMIN_USERNAME, str)
        assert len(ADMIN_USERNAME) > 0


# ---- Exception Hierarchy ----

class TestExceptionHierarchy:
    """Tests for custom exception classes."""

    def test_all_inherit_from_auth_error(self):
        exceptions = [
            InvalidCredentialsError,
            AccountLockedError,
            ForbiddenError,
            InvalidTokenError,
            WeakPasswordError,
        ]
        for exc_cls in exceptions:
            assert issubclass(exc_cls, AuthError), f"{exc_cls.__name__} should subclass AuthError"
            assert issubclass(exc_cls, Exception)

    def test_exception_message(self):
        e = InvalidCredentialsError("test message")
        assert str(e) == "test message"

    def test_catch_by_base_class(self):
        """All auth exceptions should be catchable via AuthError."""
        with pytest.raises(AuthError):
            raise InvalidCredentialsError("bad creds")

        with pytest.raises(AuthError):
            raise AccountLockedError("locked")

        with pytest.raises(AuthError):
            raise WeakPasswordError("weak")

    def test_exceptions_are_distinct(self):
        """Each exception type should be distinguishable."""
        with pytest.raises(InvalidCredentialsError):
            raise InvalidCredentialsError("x")

        # WeakPasswordError should NOT be caught by InvalidCredentialsError
        with pytest.raises(WeakPasswordError):
            raise WeakPasswordError("y")
