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
    # 先验行动态派生 (旧断言硬编码 n=1458, court 重建刷新先验后漂移失效)
    assert f"先验（n={_PRIOR.n}）" in text
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


# ---------------------------------------------------------------------------
# R77 Op1: 衰减判定统计硬化 (聚类 CI + n≥30 判定门 + 保守单侧)
# ---------------------------------------------------------------------------

from scripts.review_v2_forward_evidence import (  # noqa: E402
    DECISION_MIN_N,
    cluster_ci90,
)
from src.screening.offensive.known_distributions import (  # noqa: E402
    KNOWN_DISTRIBUTIONS,
)

_PRIOR = KNOWN_DISTRIBUTIONS[("btst_breakout", 10)]


def _zero_cost_trade(net_return: float, signal_date: str, seq: int) -> dict:
    """零成本合成 trade — closed_trade_net_return 恰等于 net_return。"""
    return {
        "trade_id": f"t{seq}",
        "ticker": "600487",
        "setup": "btst_breakout",
        "signal_date": signal_date,
        "raw_entry_price": 10.0,
        "quantity": 1,
        "entry_commission": 0.0,
        "entry_tax": 0.0,
        "entry_slippage": 0.0,
        "raw_exit_price": 10.0 * (1.0 + net_return),
        "exit_commission": 0.0,
        "exit_tax": 0.0,
        "exit_slippage": 0.0,
    }


def _trades_world(nets: list[float], dates: list[str]) -> list[dict]:
    assert len(nets) == len(dates)
    return [_zero_cost_trade(r, d, i) for i, (r, d) in enumerate(zip(nets, dates))]


def _health() -> dict:
    return {"latest_valuation": None, "state_counts": {}}


def test_cluster_ci90_bounds_contain_mean() -> None:
    rets = [0.01, -0.02, 0.03, 0.05, -0.01, 0.02, -0.03, 0.04]
    days = ["20260814"] * 4 + ["20260815"] * 4
    lo, hi = cluster_ci90(rets, days)
    mean = sum(rets) / len(rets)
    assert lo <= mean <= hi


def test_cluster_ci90_insufficient_days_returns_none() -> None:
    assert cluster_ci90([0.01], ["20260814"]) is None
    assert cluster_ci90([0.01, 0.02], ["20260814", "20260814"]) is None


def test_true_decay_world_fires_case_filing() -> None:
    """n=40 恒定深负 → CI90 上界必低于先验期望 → 立案判定语 (判定门之上)。"""
    nets = [-0.05] * 40
    dates = [f"202608{d:02d}" for d in range(1, 9) for _ in range(5)]
    assert len({*dates}) == 8
    text = build_report(_trades_world(nets, dates), [], {}, _health(), since="2026-08-14")
    assert stats_hold(text, n=40)
    assert "立案复查 edge 衰减" in text
    assert DECISION_MIN_N == 30


def stats_hold(text: str, *, n: int) -> bool:  # noqa: E303 — 可读性辅助
    return f"n={n}" in text


def test_noise_world_small_n_no_verdict() -> None:
    """n=15 点估计越出先验 CI → 旧逻辑会假告警; 新逻辑只披露不判定 (RED→GREEN 核心)。"""
    # 点估计 -2% < prior.ci_low (≈ -1.30%) — 旧判定语必输出「需立案复查」
    assert -0.02 < _PRIOR.ci_low
    nets = [-0.02] * 15
    dates = [f"202608{d:02d}" for d in range(1, 4) for _ in range(5)]
    text = build_report(_trades_world(nets, dates), [], {}, _health(), since="2026-08-14")
    # 判定语 (箭头+警告行) 不出现; 收尾「复查判据」说明行的措辞不算判定
    assert "→ ⚠️" not in text
    assert "只披露不判定" in text


def test_consistent_world_no_false_alarm() -> None:
    """n=40 均值≈先验期望、CI 覆盖 → 「edge 未衰减」而非告警。"""
    up = _PRIOR.expected_return + 0.08
    down = _PRIOR.expected_return - 0.08
    nets = [up, down] * 20  # 均值恰 = 先验期望
    dates = [f"202608{d:02d}" for d in range(1, 9) for _ in range(5)]
    text = build_report(_trades_world(nets, dates), [], {}, _health(), since="2026-08-14")
    assert "edge 未衰减" in text
    assert "→ ⚠️" not in text


def test_decay_verdict_deterministic() -> None:
    nets = [-0.05, 0.02, -0.03, 0.04] * 10
    dates = [f"202608{d:02d}" for d in range(1, 6) for _ in range(8)]
    trades = _trades_world(nets, dates)
    a = build_report(trades, [], {}, _health(), since="2026-08-14")
    b = build_report(trades, [], {}, _health(), since="2026-08-14")
    assert a == b


# ---------------------------------------------------------------------------
# R77 Op2: 反事实 panel 口径一致性 (gross → net 单一实现转换 + 口径披露)
# ---------------------------------------------------------------------------

def test_counterfactual_groups_converted_to_net() -> None:
    """gross 小正 (panel 原值 +0.3%/+0.4%) → 扣 ROUNDTRIP_COST 后为负。

    RED (旧代码): 通过组胜率 100% / 期望 +0.35% (乐观偏置);
    GREEN: 胜率 0% / 期望 -0.30% — 与先验/第一节同净口径。
    """
    panel = [
        {"ticker": "600001", "signal_date": "20260815", "block_reason": "", "realized": True, "return_t10": 0.3},
        {"ticker": "600002", "signal_date": "20260815", "block_reason": "", "realized": True, "return_t10": 0.4},
    ]
    text = build_report([], panel, {}, _health(), since="2026-08-14")
    assert "期望 -0.30%" in text
    assert "期望 +0.35%" not in text
    assert "胜率 0.0%" in text


def test_counterfactual_regime_subset_converted_to_net() -> None:
    """regime 拦截子集同转换: gross -12.0% → net -12.65%。"""
    panel = [
        {"ticker": "600001", "signal_date": "20260815", "block_reason": "regime_gate_halt", "realized": True, "return_t10": -12.0},
    ]
    text = build_report([], panel, {}, _health(), since="2026-08-14")
    assert "期望 -12.65%" in text
    assert "期望 -12.00%" not in text


def test_counterfactual_discloses_cost_basis_and_exit_leg() -> None:
    """口径披露行: gross 来源 + 扣费基准 + live ledger T+10 开盘退出腿差异。"""
    panel = [
        {"ticker": "600001", "signal_date": "20260815", "block_reason": "", "realized": True, "return_t10": 8.0},
    ]
    text = build_report([], panel, {}, _health(), since="2026-08-14")
    assert "口径" in text
    assert "0.65%" in text
    assert "T+10 开盘退出" in text
