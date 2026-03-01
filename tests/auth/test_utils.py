"""Tests for auth utility functions: password hashing, JWT tokens, invitation codes."""

import time
from datetime import timedelta

import pytest

from app.backend.auth.utils import (
    hash_password,
    verify_password,
    create_access_token,
    create_reset_token,
    decode_token,
    generate_invitation_code,
)


# ---- Password Hashing ----

class TestPasswordHashing:
    """Tests for hash_password() and verify_password()."""

    def test_hash_password_returns_bcrypt_hash(self):
        hashed = hash_password("MyP@ssw0rd")
        assert hashed.startswith("$2b$")
        assert len(hashed) == 60

    def test_verify_password_correct(self):
        password = "SecureP4ss!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_wrong(self):
        hashed = hash_password("CorrectPass1")
        assert verify_password("WrongPass1", hashed) is False

    def test_verify_password_empty_string(self):
        hashed = hash_password("Something1")
        assert verify_password("", hashed) is False

    def test_hash_password_unique_per_call(self):
        """bcrypt should produce different hashes due to random salt."""
        h1 = hash_password("SamePass1")
        h2 = hash_password("SamePass1")
        assert h1 != h2  # Different salts
        # Both should still verify
        assert verify_password("SamePass1", h1) is True
        assert verify_password("SamePass1", h2) is True

    def test_verify_password_invalid_hash_returns_false(self):
        """verify_password should catch exceptions from malformed hashes."""
        assert verify_password("anything", "not-a-valid-hash") is False

    def test_hash_password_unicode(self):
        """Test hashing unicode passwords (Chinese characters)."""
        password = "密码Test123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True
        assert verify_password("WrongUnicode密码", hashed) is False


# ---- JWT Tokens ----

class TestJWTTokens:
    """Tests for create_access_token(), decode_token(), create_reset_token()."""

    def test_create_and_decode_access_token(self):
        token = create_access_token({"sub": "testuser", "role": "user", "tv": 0})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"
        assert payload["role"] == "user"
        assert payload["tv"] == 0
        assert "exp" in payload
        assert "iat" in payload

    def test_access_token_default_expiry(self):
        """Token should be valid for ~24 hours by default."""
        token = create_access_token({"sub": "user1"})
        payload = decode_token(token)
        assert payload is not None
        exp = payload["exp"]
        iat = payload["iat"]
        # Should be approximately 1440 minutes (24 hours)
        delta = exp - iat
        assert 1430 * 60 <= delta <= 1450 * 60

    def test_access_token_custom_expiry(self):
        token = create_access_token({"sub": "user1"}, expires_delta=timedelta(minutes=30))
        payload = decode_token(token)
        assert payload is not None
        delta = payload["exp"] - payload["iat"]
        assert 29 * 60 <= delta <= 31 * 60

    def test_decode_token_invalid_string(self):
        assert decode_token("not.a.valid.token") is None

    def test_decode_token_empty_string(self):
        assert decode_token("") is None

    def test_decode_token_tampered(self):
        """Modifying token payload should invalidate signature."""
        token = create_access_token({"sub": "user1"})
        # Tamper with the token by changing a character
        parts = token.split(".")
        tampered = parts[0] + "." + parts[1] + "X." + parts[2]
        assert decode_token(tampered) is None

    def test_create_reset_token(self):
        token = create_reset_token("testuser")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"
        assert payload["type"] == "reset"

    def test_reset_token_has_shorter_expiry(self):
        """Reset tokens should expire in ~60 minutes."""
        token = create_reset_token("testuser")
        payload = decode_token(token)
        assert payload is not None
        delta = payload["exp"] - payload["iat"]
        assert 59 * 60 <= delta <= 61 * 60

    def test_token_preserves_custom_data(self):
        token = create_access_token({"sub": "admin", "role": "admin", "tv": 5, "custom": "data"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["custom"] == "data"
        assert payload["tv"] == 5


# ---- Invitation Code Generation ----

class TestInvitationCodeGeneration:
    """Tests for generate_invitation_code()."""

    def test_invitation_code_format(self):
        code = generate_invitation_code()
        assert code.startswith("INV-")
        assert len(code) == 16  # "INV-" + 12 chars

    def test_invitation_code_characters(self):
        """Code should only contain uppercase letters and digits after prefix."""
        code = generate_invitation_code()
        random_part = code[4:]
        assert random_part.isalnum()
        assert random_part == random_part.upper()

    def test_invitation_codes_unique(self):
        """Multiple calls should produce different codes (probabilistically)."""
        codes = {generate_invitation_code() for _ in range(100)}
        assert len(codes) == 100  # Extremely unlikely to have collisions
