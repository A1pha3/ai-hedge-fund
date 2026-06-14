"""Characterization tests for src/utils/env_helpers.py.

These 6 centralized env-var parsing utilities are used 100+ times across the
codebase (get_env_float alone has 104 call sites) yet had zero direct test
coverage. Tests lock down the parse + fallback contract for each.
"""
from __future__ import annotations

import pytest

from src.utils.env_helpers import (
    get_env_csv_list,
    get_env_csv_set,
    get_env_flag,
    get_env_float,
    get_env_int,
    get_env_mode,
)

# ---------------------------------------------------------------------------
# get_env_float
# ---------------------------------------------------------------------------


class TestGetEnvFloat:
    def test_unset_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EH_FLOAT", raising=False)
        assert get_env_float("EH_FLOAT", 3.14) == 3.14

    def test_valid_float_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_FLOAT", "2.5")
        assert get_env_float("EH_FLOAT", 0.0) == 2.5

    def test_integer_string_parsed_as_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_FLOAT", "10")
        assert get_env_float("EH_FLOAT", 0.0) == 10.0

    def test_negative_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_FLOAT", "-0.5")
        assert get_env_float("EH_FLOAT", 0.0) == -0.5

    def test_invalid_value_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_FLOAT", "abc")
        assert get_env_float("EH_FLOAT", 9.9) == 9.9

    def test_empty_string_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_FLOAT", "")
        assert get_env_float("EH_FLOAT", 1.5) == 1.5


# ---------------------------------------------------------------------------
# get_env_int
# ---------------------------------------------------------------------------


class TestGetEnvInt:
    def test_unset_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EH_INT", raising=False)
        assert get_env_int("EH_INT", 42) == 42

    def test_valid_int_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_INT", "100")
        assert get_env_int("EH_INT", 0) == 100

    def test_negative_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_INT", "-5")
        assert get_env_int("EH_INT", 0) == -5

    def test_float_string_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """int('2.5') raises ValueError → default."""
        monkeypatch.setenv("EH_INT", "2.5")
        assert get_env_int("EH_INT", 7) == 7

    def test_invalid_value_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_INT", "abc")
        assert get_env_int("EH_INT", 7) == 7


# ---------------------------------------------------------------------------
# get_env_csv_set
# ---------------------------------------------------------------------------


class TestGetEnvCsvSet:
    def test_unset_returns_default_split(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EH_CSV", raising=False)
        assert get_env_csv_set("EH_CSV", "a,b") == {"a", "b"}

    def test_basic_split(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_CSV", "x,y,z")
        assert get_env_csv_set("EH_CSV", "") == {"x", "y", "z"}

    def test_whitespace_trimmed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_CSV", " a , b , c ")
        assert get_env_csv_set("EH_CSV", "") == {"a", "b", "c"}

    def test_empty_entries_filtered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_CSV", "a,,b,")
        assert get_env_csv_set("EH_CSV", "") == {"a", "b"}

    def test_returns_set_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_CSV", "a")
        result = get_env_csv_set("EH_CSV", "")
        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# get_env_csv_list
# ---------------------------------------------------------------------------


class TestGetEnvCsvList:
    def test_unset_returns_default_split(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EH_CSVL", raising=False)
        assert get_env_csv_list("EH_CSVL", "a,b") == ["a", "b"]

    def test_order_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_CSVL", "c,b,a")
        assert get_env_csv_list("EH_CSVL", "") == ["c", "b", "a"]

    def test_whitespace_trimmed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_CSVL", " a , b ")
        assert get_env_csv_list("EH_CSVL", "") == ["a", "b"]

    def test_empty_entries_filtered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_CSVL", "a,,b,")
        assert get_env_csv_list("EH_CSVL", "") == ["a", "b"]

    def test_returns_list_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_CSVL", "a")
        result = get_env_csv_list("EH_CSVL", "")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# get_env_flag
# ---------------------------------------------------------------------------


class TestGetEnvFlag:
    @pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "True", "yes", "YES", "on", "ON"])
    def test_truthy_values(self, truthy: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_FLAG", truthy)
        assert get_env_flag("EH_FLAG") is True

    @pytest.mark.parametrize("falsy", ["0", "false", "FALSE", "no", "off", "", "random"])
    def test_falsy_values(self, falsy: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_FLAG", falsy)
        assert get_env_flag("EH_FLAG") is False

    def test_unset_returns_default_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EH_FLAG", raising=False)
        assert get_env_flag("EH_FLAG") is False

    def test_unset_returns_default_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EH_FLAG", raising=False)
        assert get_env_flag("EH_FLAG", default=True) is True


# ---------------------------------------------------------------------------
# get_env_mode
# ---------------------------------------------------------------------------


class TestGetEnvMode:
    def test_unset_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EH_MODE", raising=False)
        assert get_env_mode("EH_MODE", "off") == "off"

    def test_value_lowered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_MODE", "ENFORCE")
        assert get_env_mode("EH_MODE", "off") == "enforce"

    def test_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_MODE", "  warn  ")
        assert get_env_mode("EH_MODE", "off") == "warn"

    def test_empty_string_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EH_MODE", "")
        assert get_env_mode("EH_MODE", "off") == "off"
