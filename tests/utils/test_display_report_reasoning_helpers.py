"""Characterization tests for display_report_helpers + display_reasoning_helpers.

Both modules render markdown from dicts but had zero direct test coverage.
Tests cover the pure dict→list[str] helpers (the complex multi-Callable
orchestrators like build_trading_report_lines are deferred).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.utils.display_reasoning_helpers import (
    build_reasoning_dict_section,
    build_reasoning_fallback_table,
    build_reasoning_signal_section,
)
from src.utils.display_report_helpers import build_trading_report_path


class TestBuildTradingReportPath:
    def test_single_ticker(self) -> None:
        path = build_trading_report_path(Path("/reports"), ["000001"], datetime(2026, 6, 15, 12, 0, 0))
        assert path == Path("/reports/000001_20260615_120000.md")

    def test_three_tickers_joined(self) -> None:
        path = build_trading_report_path(Path("r"), ["a", "b", "c"], datetime(2026, 1, 1))
        assert "a_b_c_20260101_000000.md" in str(path)

    def test_more_than_three_adds_etc_suffix(self) -> None:
        path = build_trading_report_path(Path("r"), ["a", "b", "c", "d"], datetime(2026, 1, 1))
        assert "a_b_c_etc4_" in str(path)

    def test_many_tickers_etc_count(self) -> None:
        path = build_trading_report_path(Path("r"), ["x"] * 7, datetime(2026, 1, 1))
        assert "x_x_x_etc7_" in str(path)


class TestBuildReasoningSignalSection:
    def test_bullish_signal_with_emoji(self) -> None:
        lines = build_reasoning_signal_section("趋势", {"signal": "bullish", "confidence": 80, "details": "strong uptrend"})
        joined = "\n".join(lines)
        assert "📈" in joined
        assert "BULLISH" in joined
        assert "置信度: 80%" in joined
        assert "strong uptrend" in joined

    def test_bearish_signal(self) -> None:
        lines = build_reasoning_signal_section("RSI", {"signal": "bearish"})
        assert any("📉" in line for line in lines)

    def test_neutral_signal(self) -> None:
        lines = build_reasoning_signal_section("Volume", {"signal": "neutral"})
        assert any("⚖️" in line for line in lines)

    def test_unknown_signal_default_emoji(self) -> None:
        lines = build_reasoning_signal_section("X", {"signal": "confused"})
        assert any("❓" in line for line in lines)

    def test_no_confidence_omits_line(self) -> None:
        lines = build_reasoning_signal_section("X", {"signal": "bullish"})
        assert not any("置信度" in line for line in lines)

    def test_metrics_table_rendered(self) -> None:
        lines = build_reasoning_signal_section("X", {"signal": "bullish", "metrics": {"rsi": 65.5}})
        joined = "\n".join(lines)
        assert "Rsi" in joined or "RSI" in joined
        assert "65.5000" in joined


class TestBuildReasoningDictSection:
    def test_renders_key_value_table(self) -> None:
        lines = build_reasoning_dict_section("测试", {"pe_ratio": 25.5, "name": "AAPL"})
        joined = "\n".join(lines)
        assert "Pe Ratio" in joined
        assert "25.5000" in joined
        assert "AAPL" in joined

    def test_none_value_shows_na(self) -> None:
        lines = build_reasoning_dict_section("X", {"field": None})
        assert any("N/A" in line for line in lines)

    def test_title_from_section_param(self) -> None:
        lines = build_reasoning_dict_section("My Section", {"k": 1})
        assert any("My Section" in line for line in lines)


class TestBuildReasoningFallbackTable:
    def test_scalar_values(self) -> None:
        lines = build_reasoning_fallback_table({"a": 1, "b": "hello"})
        joined = "\n".join(lines)
        assert "| a | 1 |" in joined
        assert "| b | hello |" in joined

    def test_dict_value_json_serialized(self) -> None:
        lines = build_reasoning_fallback_table({"nested": {"x": 1}})
        joined = "\n".join(lines)
        assert json.dumps({"x": 1}, ensure_ascii=False) in joined

    def test_list_value_json_serialized(self) -> None:
        lines = build_reasoning_fallback_table({"items": [1, 2, 3]})
        joined = "\n".join(lines)
        assert "[1, 2, 3]" in joined

    def test_none_value_stringified(self) -> None:
        lines = build_reasoning_fallback_table({"x": None})
        joined = "\n".join(lines)
        assert "| x | None |" in joined
