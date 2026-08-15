"""Tests for scripts/review_v2_forward_evidence.py — 纯计算核契约."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.review_v2_forward_evidence import (  # noqa: E402
    _slice_stats,
    build_report,
    closed_trade_net_return,
)


def _trade(**overrides) -> dict:
    base = dict(
        trade_id="t1",
        ticker="600487",
        setup="btst_breakout",
        signal_date="2026-08-14",
        raw_entry_price=10.0,
        quantity=1000,
        entry_commission=3.0,
        entry_tax=0.0,
        entry_slippage=30.0,
        raw_exit_price=11.0,
        exit_commission=3.3,
        exit_tax=5.5,
        exit_slippage=33.0,
    )
    base.update(overrides)
    return base


def test_closed_trade_net_return_includes_all_costs() -> None:
    # 买入总成本 = 10.0*1000 + 3 + 0 + 30 = 10033
    # 卖出净回收 = 11.0*1000 - 3.3 - 5.5 - 33 = 10958.2
    # 净收益 = (10958.2 - 10033) / 10033 ≈ +9.22%
    ret = closed_trade_net_return(_trade())
    assert abs(ret - (10958.2 - 10033.0) / 10033.0) < 1e-12


def test_slice_stats_empty_returns_none() -> None:
    assert _slice_stats([]) is None


def test_slice_stats_math_and_low_confidence() -> None:
    stats = _slice_stats([0.10, -0.05, 0.20, -0.10])
    assert stats is not None
    assert stats.n == 4
    assert stats.winrate == 0.5
    assert abs(stats.expected_return - 0.0375) < 1e-12
    assert abs(stats.avg_gain - 0.15) < 1e-12
    assert abs(stats.avg_loss - (-0.075)) < 1e-12
    assert stats.low_confidence  # n=4 < 10


def test_build_report_handles_empty_evidence_gracefully() -> None:
    text = build_report([], [], [], {"latest_valuation": None, "state_counts": {}}, since="2026-08-14")
    assert "尚无已平仓交易" in text
    assert "无已实现样本" in text
    assert "无估值记录" in text


def test_build_report_compares_forward_with_frozen_prior() -> None:
    trades = [_trade(trade_id=f"t{i}", signal_date="2026-08-14") for i in range(12)]
    text = build_report(
        trades,
        [],
        {"20260814": {"600487"}},
        {"latest_valuation": {"trade_date": "2026-08-28", "nav": 1_010_000, "peak": 1_020_000, "drawdown": -0.0098}, "state_counts": {"closed": 12}},
        since="2026-08-14",
    )
    assert "btst_breakout" in text
    assert "先验（n=1458）" in text
    assert "CI" in text
    # 双信号子集: 600487 在 20260814 的 Top-N 里 → 全部 12 笔进子集
    assert "双信号子集" in text
    assert "n=12" in text
    assert "净值 1,010,000" in text


def test_build_report_panel_counterfactual_groups() -> None:
    panel = [
        {"ticker": "600001", "signal_date": "20260815", "block_reason": "regime_gate_halt", "realized": True, "return_t10": -12.0},
        {"ticker": "600002", "signal_date": "20260815", "block_reason": "", "realized": True, "return_t10": 8.0},
        {"ticker": "600003", "signal_date": "20260701", "block_reason": "regime_gate_halt", "realized": True, "return_t10": -30.0},  # 窗口外
    ]
    text = build_report([], panel, {}, {"latest_valuation": None, "state_counts": {}}, since="2026-08-14")
    assert "被挡组" in text
    assert "通过组" in text
    assert "regime 闸拦截子集" in text
    # 窗口外样本不进入统计: 被挡组只有 -12.0 一个 → n=1
    assert "n=1" in text
