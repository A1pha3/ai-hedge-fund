"""Tests for auth utility functions: password hashing, JWT tokens, invitation codes."""

import time
from datetime import timedelta

import pytest

from app.backend.auth.utils import (
    create_access_token,
    create_reset_token,
    decode_token,
    generate_invitation_code,
    get_cors_origins,
    hash_password,
    resolve_admin_bootstrap_password,
    should_auto_init_admin,
    should_show_reset_token,
    verify_password,
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

    def test_decode_token_warns_on_tampered_signature(self, caplog):
        """c299/F5: bad-signature token must be REJECTED (None) AND logged at WARNING.

        The auth path is fail-closed but ``decode_token`` silently swallowed
        JWTError — no audit trail distinguishing benign-expired from attack-probe
        (invalid signature). On a money-acting app's auth surface, the operator
        needs the invalid-signature storm visible in logs (forgery detection).
        Consistent with existing auth-event logging (routes/auth.py:176 logs
        reset-token generation). No decision change (still None → 401).
        """
        import logging

        token = create_access_token({"sub": "user1"})
        parts = token.split(".")
        tampered = parts[0] + "." + parts[1] + "X." + parts[2]
        with caplog.at_level(logging.WARNING):
            result = decode_token(tampered)
        assert result is None  # fail-closed (unchanged)
        assert any(r.levelno == logging.WARNING and "decode failed" in r.message.lower() for r in caplog.records), f"tampered-signature token must log WARNING for attack detection; " f"got {[r.message for r in caplog.records]}"

    def test_decode_token_logs_info_not_warning_on_expired(self, caplog):
        """An expired token is BENIGN (user re-login) — must NOT warn (cry wolf).

        Differential: expired=INFO, invalid-sig=WARNING. Still rejected (None).
        Uses ExpiredSignatureError (subclass of JWTError) caught first.
        """
        import logging

        expired = create_access_token({"sub": "user1"}, expires_delta=timedelta(seconds=-10))
        with caplog.at_level(logging.INFO):
            result = decode_token(expired)
        assert result is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("decode failed" in r.message.lower() for r in warnings), f"expired token is benign — must NOT warn; got warnings={[r.message for r in warnings]}"
        # must emit an INFO (benign) — not silent, not WARNING
        assert any(r.levelno == logging.INFO and "expired" in r.message.lower() for r in caplog.records), f"expired token must log an INFO message (benign, not silent); " f"got {[r.message for r in caplog.records]}"

    def test_create_reset_token(self):
        token = create_reset_token("testuser")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"
        assert payload["type"] == "reset"

    def test_create_reset_token_preserves_token_version_when_provided(self):
        token = create_reset_token("testuser", token_version=7)
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"
        assert payload["type"] == "reset"
        assert payload["tv"] == 7

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

    def test_create_access_token_requires_secret_in_production(self, monkeypatch):
        monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
        monkeypatch.setenv("APP_ENV", "production")

        with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
            create_access_token({"sub": "prod-user"})


class TestEnvironmentGuards:
    """Tests for production-sensitive auth helper decisions."""

    def test_should_show_reset_token_defaults_to_true_in_dev(self, monkeypatch):
        monkeypatch.delenv("AUTH_SHOW_RESET_TOKEN", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        assert should_show_reset_token() is True

    def test_should_show_reset_token_defaults_to_false_in_production(self, monkeypatch):
        monkeypatch.delenv("AUTH_SHOW_RESET_TOKEN", raising=False)
        monkeypatch.setenv("APP_ENV", "production")
        assert should_show_reset_token() is False

    def test_should_show_reset_token_ignores_true_in_production(self, monkeypatch):
        monkeypatch.setenv("AUTH_SHOW_RESET_TOKEN", "true")
        monkeypatch.setenv("APP_ENV", "production")
        assert should_show_reset_token() is False

    def test_should_auto_init_admin_defaults_to_false_in_production(self, monkeypatch):
        monkeypatch.delenv("AUTH_AUTO_INIT_ADMIN", raising=False)
        monkeypatch.setenv("APP_ENV", "production")
        assert should_auto_init_admin() is False

    def test_resolve_admin_bootstrap_password_requires_explicit_prod_value(self, monkeypatch):
        monkeypatch.delenv("AUTH_ADMIN_DEFAULT_PASSWORD", raising=False)
        monkeypatch.setenv("APP_ENV", "production")
        assert resolve_admin_bootstrap_password() is None

    def test_get_cors_origins_defaults_to_local_dev_origins(self, monkeypatch):
        monkeypatch.delenv("BACKEND_CORS_ORIGINS", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        assert get_cors_origins() == ["http://localhost:5173", "http://127.0.0.1:5173"]

    def test_get_cors_origins_defaults_to_empty_in_production(self, monkeypatch):
        monkeypatch.delenv("BACKEND_CORS_ORIGINS", raising=False)
        monkeypatch.setenv("APP_ENV", "production")
        assert get_cors_origins() == []

    def test_get_cors_origins_parses_explicit_list(self, monkeypatch):
        monkeypatch.setenv("BACKEND_CORS_ORIGINS", "https://app.example.com, https://admin.example.com ")
        assert get_cors_origins() == ["https://app.example.com", "https://admin.example.com"]


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
