"""Tests for _print_cache_hit_summary (O-1: 缓存命中率可观测性)."""

from io import StringIO
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Import helper — main.py is large so we import just the function under test.
# ---------------------------------------------------------------------------
from src.main import _print_cache_hit_summary


class TestPrintCacheHitSummary:
    """O-1: --auto CLI 底部缓存命中率摘要行。"""

    def test_high_hit_rate_shows_green(self, capsys: pytest.CaptureFixture[str]) -> None:
        """命中率 >= 50% 时应正常输出包含百分比的行。"""
        stats = {
            "batch_calls": 2,
            "batch_failures": 0,
            "single_ticker_calls": 100,
            "single_ticker_cache_hits": 80,
        }
        _print_cache_hit_summary(stats)
        output = capsys.readouterr().out
        assert "Cache:" in output
        # effective_hit_rate = 80 / (2 + 100) * 100 ≈ 78%
        assert "78% hit" in output
        assert "80 cached" in output
        assert "102 requests" in output

    def test_zero_requests_no_division_by_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """total_requests = 0 时不崩溃，输出 0%。"""
        stats = {
            "batch_calls": 0,
            "batch_failures": 0,
            "single_ticker_calls": 0,
            "single_ticker_cache_hits": 0,
        }
        _print_cache_hit_summary(stats)
        output = capsys.readouterr().out
        assert "0% hit" in output
        assert "0 cached / 0 requests" in output

    def test_no_cache_hits_shows_zero_percent(self, capsys: pytest.CaptureFixture[str]) -> None:
        """无缓存命中时显示 0%。"""
        stats = {
            "batch_calls": 5,
            "batch_failures": 1,
            "single_ticker_calls": 200,
            "single_ticker_cache_hits": 0,
        }
        _print_cache_hit_summary(stats)
        output = capsys.readouterr().out
        assert "0% hit" in output
        assert "0 cached / 205 requests" in output
        assert "5 calls (1 failures)" in output

    def test_missing_keys_default_to_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """缺少 key 时不崩溃，使用默认值 0。"""
        _print_cache_hit_summary({})
        output = capsys.readouterr().out
        assert "0% hit" in output

    def test_batch_failure_count_shown(self, capsys: pytest.CaptureFixture[str]) -> None:
        """有 batch failure 时应在输出中显示。"""
        stats = {
            "batch_calls": 3,
            "batch_failures": 1,
            "single_ticker_calls": 50,
            "single_ticker_cache_hits": 10,
        }
        _print_cache_hit_summary(stats)
        output = capsys.readouterr().out
        assert "1 failures" in output
        assert "3 calls" in output

    def test_all_from_cache_shows_100_percent(self, capsys: pytest.CaptureFixture[str]) -> None:
        """所有 single ticker 请求都命中缓存。"""
        stats = {
            "batch_calls": 1,
            "batch_failures": 0,
            "single_ticker_calls": 100,
            "single_ticker_cache_hits": 100,
        }
        _print_cache_hit_summary(stats)
        output = capsys.readouterr().out
        assert "99%" in output  # 100 / 101 * 100 ≈ 99%
        assert "100 cached / 101 requests" in output
