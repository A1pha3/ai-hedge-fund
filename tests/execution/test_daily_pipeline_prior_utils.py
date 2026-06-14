"""Unit tests for src/execution/daily_pipeline_prior_utils.py

Typed accessors that safely extract float/int from historical prior dicts,
returning None on missing or invalid values.
"""

from __future__ import annotations

import pytest

from src.execution.daily_pipeline_prior_utils import (
    historical_prior_float,
    historical_prior_int,
)

# ---------------------------------------------------------------------------
# historical_prior_float
# ---------------------------------------------------------------------------


def test_historical_prior_float_missing_key_returns_none() -> None:
    assert historical_prior_float({"a": 1.0}, "missing") is None


def test_historical_prior_float_none_value_returns_none() -> None:
    assert historical_prior_float({"a": None}, "a") is None


def test_historical_prior_float_valid_float() -> None:
    assert historical_prior_float({"a": 3.14}, "a") == 3.14


def test_historical_prior_float_coerces_int_string() -> None:
    assert historical_prior_float({"a": "42"}, "a") == 42.0


def test_historical_prior_float_coerces_numeric_string() -> None:
    assert historical_prior_float({"a": "3.5"}, "a") == 3.5


def test_historical_prior_float_invalid_string_returns_none() -> None:
    assert historical_prior_float({"a": "not_a_number"}, "a") is None


def test_historical_prior_float_list_value_returns_none() -> None:
    assert historical_prior_float({"a": [1, 2]}, "a") is None


# ---------------------------------------------------------------------------
# historical_prior_int
# ---------------------------------------------------------------------------


def test_historical_prior_int_missing_key_returns_none() -> None:
    assert historical_prior_int({"a": 1}, "missing") is None


def test_historical_prior_int_none_value_returns_none() -> None:
    assert historical_prior_int({"a": None}, "a") is None


def test_historical_prior_int_valid_int() -> None:
    assert historical_prior_int({"a": 7}, "a") == 7


def test_historical_prior_int_coerces_string() -> None:
    assert historical_prior_int({"a": "5"}, "a") == 5


def test_historical_prior_int_truncates_float() -> None:
    """int(3.9) → 3 (truncation, not rounding)."""
    assert historical_prior_int({"a": 3.9}, "a") == 3


def test_historical_prior_int_invalid_string_returns_none() -> None:
    assert historical_prior_int({"a": "abc"}, "a") is None


def test_historical_prior_int_dict_value_returns_none() -> None:
    assert historical_prior_int({"a": {"x": 1}}, "a") is None
