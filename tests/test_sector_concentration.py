"""Tests for sector concentration guard and run_explain feature."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


def test_check_sector_concentration_at_cap_warns() -> None:
    """v3 (2026-08-16): 同行业 >= 3 只即警示 — 与选股 sector cap=3 对齐。

    旧 ratio>0.4 语义在 cap=3 生效时永不触发 (4/10 才达阈值, cap 已挡在 3),
    是死代码; 新语义在触及上限 (3/10 = 30% 单一行业敞口) 时即披露。
    """
    from src.main import _check_sector_concentration

    class _MockItem:
        def __init__(self, industry_sw: str) -> None:
            self.industry_sw = industry_sw

    top_results = [
        _MockItem("银行"),
        _MockItem("银行"),
        _MockItem("银行"),
        _MockItem("电子"),
        _MockItem("医药"),
        _MockItem("汽车"),
        _MockItem("化工"),
    ]
    warnings = _check_sector_concentration(top_results)
    assert len(warnings) == 1
    assert "银行" in warnings[0]
    assert "3/7" in warnings[0]


def test_check_sector_concentration_below_threshold_silent() -> None:
    """每行业 <3 只时不警示 (多样化组合)."""
    from src.main import _check_sector_concentration

    class _MockItem:
        def __init__(self, industry_sw: str) -> None:
            self.industry_sw = industry_sw

    top_results = [
        _MockItem("银行"),
        _MockItem("银行"),
        _MockItem("电子"),
        _MockItem("医药"),
        _MockItem("汽车"),
        _MockItem("化工"),
        _MockItem("地产"),
    ]
    assert _check_sector_concentration(top_results) == []


def test_check_sector_concentration_relaxed_cap_disclosed() -> None:
    """pool 不足放宽 cap 时 >3 只同行业 → 计数如实入警示文案."""
    from src.main import _check_sector_concentration

    class _MockItem:
        def __init__(self, industry_sw: str) -> None:
            self.industry_sw = industry_sw

    top_results = [_MockItem("银行") for _ in range(5)] + [_MockItem("电子")]
    warnings = _check_sector_concentration(top_results)
    assert len(warnings) == 1
    assert "5/6" in warnings[0]


def test_check_sector_concentration_empty_industry_skipped() -> None:
    """Items with empty industry_sw should be skipped (not treated as a single bucket)."""
    from src.main import _check_sector_concentration

    class _MockItem:
        def __init__(self, industry_sw: str) -> None:
            self.industry_sw = industry_sw

    top_results = [_MockItem(""), _MockItem(""), _MockItem(""), _MockItem("")]
    assert _check_sector_concentration(top_results) == []


def test_run_explain_finds_ticker_in_latest_report(tmp_path: Path, capsys) -> None:
    """run_explain should locate the most recent report and print the breakdown."""
    from src.main import run_explain

    report = {
        "date": "20260601",
        "market_state": {
            "state_type": "trend",
            "position_scale": 0.8,
            "regime_gate_level": "normal",
        },
        "recommendations": [
            {
                "ticker": "000001",
                "name": "平安银行",
                "industry_sw": "银行",
                "score_b": 0.42,
                "decision": "watch",
                "strategy_signals": {
                    "trend": {"direction": 1, "confidence": 75.0, "completeness": 1.0},
                    "mean_reversion": {"direction": 0, "confidence": 0.0, "completeness": 0.0},
                },
                "arbitration_applied": ["consensus_bonus"],
            }
        ],
    }

    with tempfile.TemporaryDirectory() as td:
        # Monkey-patch the reports dir
        import src.main

        orig = getattr(src.main, "_REPORT_DIR", None)
        reports_dir = Path(td)
        (reports_dir / "auto_screening_20260601.json").write_text(json.dumps(report))
        # Patch by overriding the function's path lookup
        # run_explain uses a hard-coded relative path; we'll inject via mocking
        from unittest.mock import patch

        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.glob", return_value=[reports_dir / "auto_screening_20260601.json"]), patch("pathlib.Path.open", reports_dir.joinpath("auto_screening_20260601.json").open):
            result = run_explain("000001")

    assert result == 0
    captured = capsys.readouterr()
    assert "000001" in captured.out
    assert "平安银行" in captured.out
    assert "银行" in captured.out
    assert "trend" in captured.out


def test_run_explain_ticker_not_found(tmp_path: Path, capsys) -> None:
    """run_explain should return 1 with a helpful message when ticker isn't in recommendations."""
    from src.main import run_explain

    report = {
        "date": "20260601",
        "market_state": {},
        "recommendations": [
            {"ticker": "000001", "name": "A", "industry_sw": "X", "score_b": 0.1, "decision": "neutral", "strategy_signals": {}},
        ],
    }

    with tempfile.TemporaryDirectory() as td:
        reports_dir = Path(td)
        (reports_dir / "auto_screening_20260601.json").write_text(json.dumps(report))
        from unittest.mock import patch

        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.glob", return_value=[reports_dir / "auto_screening_20260601.json"]):
            result = run_explain("999999")

    assert result == 1
    captured = capsys.readouterr()
    assert "999999" in captured.out or "未找到" in captured.out
