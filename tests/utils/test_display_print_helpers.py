"""Characterization tests for src/utils/display_print_helpers.py.

The module has 6 pure formatting functions used across display paths with zero
direct test coverage. These tests cover the 3 simplest pure functions; the
build_*_table_rows helpers (colorama-formatted) are deferred.
"""
from __future__ import annotations

import json

from src.utils.display_print_helpers import (
    find_portfolio_manager_reasoning,
    stringify_reasoning,
    wrap_output_text,
)


class TestStringifyReasoning:
    def test_string_passthrough(self) -> None:
        assert stringify_reasoning("hello") == "hello"

    def test_dict_to_json(self) -> None:
        result = stringify_reasoning({"a": 1})
        assert json.loads(result) == {"a": 1}

    def test_dict_json_is_indented(self) -> None:
        """Dicts are serialized with indent=2."""
        result = stringify_reasoning({"key": "value"})
        assert '\n' in result  # indented multiline

    def test_int_to_string(self) -> None:
        assert stringify_reasoning(42) == "42"

    def test_list_to_string(self) -> None:
        assert stringify_reasoning([1, 2]) == "[1, 2]"

    def test_none_to_string(self) -> None:
        assert stringify_reasoning(None) == "None"


class TestWrapOutputText:
    def test_empty_returns_empty(self) -> None:
        assert wrap_output_text("") == ""

    def test_none_returns_empty(self) -> None:
        assert wrap_output_text(None) == ""

    def test_short_text_single_line(self) -> None:
        assert wrap_output_text("short text") == "short text"

    def test_long_text_wraps_at_default_60(self) -> None:
        long_text = "word " * 30  # 150 chars, 30 words
        result = wrap_output_text(long_text)
        lines = result.split("\n")
        assert len(lines) > 1
        # each line should be <= 60 chars (except possibly the last partial)
        for line in lines:
            assert len(line) <= 60

    def test_custom_max_line_length(self) -> None:
        result = wrap_output_text("aaa bbb ccc", max_line_length=5)
        lines = result.split("\n")
        # with max_line_length=5, "aaa" (3) fits, "bbb" makes 7 > 5 → new line
        assert len(lines) >= 2

    def test_single_long_word_not_split(self) -> None:
        """A single word longer than max_line_length stays on its own line."""
        result = wrap_output_text("supercalifragilistic", max_line_length=5)
        assert "supercalifragilistic" in result


class TestFindPortfolioManagerReasoning:
    def test_returns_first_reasoning(self) -> None:
        decisions = {"AAPL": {"action": "BUY", "reasoning": "strong fundamentals"}}
        assert find_portfolio_manager_reasoning(decisions) == "strong fundamentals"

    def test_returns_none_when_no_reasoning(self) -> None:
        decisions = {"AAPL": {"action": "BUY"}}
        assert find_portfolio_manager_reasoning(decisions) is None

    def test_returns_none_for_empty_decisions(self) -> None:
        assert find_portfolio_manager_reasoning({}) is None

    def test_skips_empty_reasoning_finds_next(self) -> None:
        decisions = {
            "AAPL": {"action": "BUY", "reasoning": ""},
            "MSFT": {"action": "HOLD", "reasoning": "wait for dip"},
        }
        assert find_portfolio_manager_reasoning(decisions) == "wait for dip"

    def test_falsy_reasoning_skipped(self) -> None:
        """reasoning=0 or reasoning=None is falsy → skipped."""
        decisions = {"AAPL": {"reasoning": None}, "MSFT": {"reasoning": "found"}}
        assert find_portfolio_manager_reasoning(decisions) == "found"
