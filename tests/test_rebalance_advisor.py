"""P1-12 组合再平衡建议 — 单元测试 (≥12)。

覆盖:
  1. 完美对齐 → 全 hold (空 actions)
  2. 单标的超配 → 1 条 sell (优先级 1)
  3. 单标的低配 → 1 条 buy / add
  4. 多标的混合 → 多条 actions
  5. 行业集中度超限 → 强制 sell (优先级 1)
  6. 偏离阈值生效 (drift_threshold)
  7. 最小交易金额过滤 (min_trade_amount)
  8. 优先级判定 (1 / 2 / 3)
  9. 持仓为空 → 空列表
 10. delta 计算正确性
 11. CLI smoke test (--rebalance)
 12. Web 端点 smoke test (/api/portfolio/rebalance)
 13. portfolio_value=0 / NaN → 空列表
 14. format_rebalance_actions 渲染基本字段
 15. RebalanceAction.to_dict 圆环
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.portfolio.rebalance_advisor import (
    compute_rebalance_actions,
    DEFAULT_DRIFT_THRESHOLD,
    DEFAULT_MIN_TRADE_AMOUNT,
    format_rebalance_actions,
    INDUSTRY_HARD_LIMIT,
    RebalanceAction,
    SINGLE_NAME_HARD_LIMIT,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _make_position(ticker: str, name: str, sector: str, current_value: float, target_weight: float) -> dict:
    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "current_value": current_value,
        "target_weight": target_weight,
    }


# ===========================================================================
# 1. 完美对齐
# ===========================================================================


def test_aligned_portfolio_yields_no_actions() -> None:
    """所有持仓在阈值内,actions 全为空 (hold 不入列)。"""
    portfolio_value = 1_000_000.0
    positions = [
        _make_position("000001", "平安银行", "银行", 100_000.0, 0.10),
        _make_position("300750", "宁德时代", "新能源", 100_000.0, 0.10),
        # 注: target_weight 设为 12% 略低于 15% 硬限制, 避免被硬约束触发
        _make_position("600519", "贵州茅台", "白酒", 120_000.0, 0.12),
    ]
    actions = compute_rebalance_actions(positions, portfolio_value)
    assert actions == []


# ===========================================================================
# 2. 单标的超配 (普通漂移, 非硬限制)
# ===========================================================================


def test_single_position_over_target_generates_trim() -> None:
    """单标的超配 8% (低于 SINGLE_NAME_HARD_LIMIT=15%), 生成 trim。"""
    portfolio_value = 1_000_000.0
    positions = [
        _make_position("000001", "平安银行", "银行", 130_000.0, 0.05),  # 当前 13% → 目标 5% (差 -8%)
    ]
    actions = compute_rebalance_actions(positions, portfolio_value)
    assert len(actions) == 1
    a = actions[0]
    assert a.ticker == "000001"
    assert a.action == "trim"
    # |delta| = 8% < strong_drift_threshold (10%) → 优先级 3
    assert a.priority == 3
    assert a.delta_amount < 0
    assert abs(a.delta_amount - (-80_000.0)) < 1.0


# ===========================================================================
# 3. 单标的低配
# ===========================================================================


def test_single_position_under_target_generates_add() -> None:
    """单标的低配 6%, 生成 add (优先级 3)。"""
    portfolio_value = 1_000_000.0
    positions = [
        _make_position("000001", "平安银行", "银行", 40_000.0, 0.10),  # 当前 4% → 目标 10%
    ]
    actions = compute_rebalance_actions(positions, portfolio_value)
    assert len(actions) == 1
    a = actions[0]
    assert a.action == "add"
    assert a.delta_amount > 0
    assert abs(a.delta_amount - 60_000.0) < 1.0


# ===========================================================================
# 4. 多标的混合
# ===========================================================================


def test_mixed_portfolio_generates_multiple_actions() -> None:
    """多标的混合超配/低配/对齐, 输出按优先级排序。"""
    portfolio_value = 1_000_000.0
    positions = [
        _make_position("600519", "贵州茅台", "白酒", 250_000.0, 0.10),  # 超配 15% → trim 强烈
        _make_position("000001", "平安银行", "银行", 30_000.0, 0.10),  # 低配 7% → add 弱
        _make_position("300750", "宁德时代", "新能源", 100_000.0, 0.10),  # 对齐
    ]
    actions = compute_rebalance_actions(positions, portfolio_value)
    tickers = [a.ticker for a in actions]
    assert "600519" in tickers
    assert "000001" in tickers
    assert "300750" not in tickers  # 对齐 → hold
    # 优先级排序: 茅台 |delta|=15% 优先级 2, 平安 7% 优先级 3
    assert actions[0].ticker == "600519"


# ===========================================================================
# 5. 行业集中度超限 → 强制 sell
# ===========================================================================


def test_industry_over_hard_limit_triggers_forced_sell() -> None:
    """同行业 3 只累计 30%, 超过 25% 硬限制, 强制减仓最重一只 (单标的均 < 15% 硬限)。"""
    portfolio_value = 1_000_000.0
    positions = [
        _make_position("600519", "贵州茅台", "白酒", 130_000.0, 0.10),  # 13% — 未超单标的硬限
        _make_position("000858", "五粮液", "白酒", 100_000.0, 0.08),  # 10%
        _make_position("600809", "山西汾酒", "白酒", 70_000.0, 0.07),  # 7%
        # 累计白酒 = 30%, 超 25%
    ]
    actions = compute_rebalance_actions(positions, portfolio_value)
    forced = [a for a in actions if a.priority == 1]
    assert len(forced) >= 1
    # 最重的茅台被强制减仓
    assert forced[0].ticker == "600519"
    assert forced[0].action == "sell"
    assert "白酒" in forced[0].reason
    # 减仓后该标的的目标 <= 之前
    assert forced[0].target_weight < forced[0].current_weight


def test_single_name_trim_decrements_sector_no_sibling_overtrim() -> None:
    """R147: priority-1 single-name trim must decrement the sector aggregate so a
    sibling in the same over-limit sector isn't over-trimmed. Before the fix: A
    (20%) was trimmed to 15% but ``sector_weights`` stayed at the pre-trim 30%, so
    sibling B (10%) was trimmed by the STALE excess (30%-25%=5%) → needless ~50k
    liquidation, even though A's 20%→15% trim had already brought the sector to
    exactly the 25% industry limit (15%+10%). Real over-selling of shares."""
    portfolio_value = 1_000_000.0
    positions = [
        _make_position("A", "A", "白酒", 200_000.0, 0.20),  # 20% > 15% single-name limit
        _make_position("B", "B", "白酒", 100_000.0, 0.10),  # 10%; sector = 30% > 25%
    ]
    actions = compute_rebalance_actions(positions, portfolio_value)
    sells = {a.ticker for a in actions if a.action == "sell"}
    # A must be trimmed (single-name 20% > 15%)
    assert "A" in sells
    # B must NOT be trimmed — A's 20%→15% trim already brought sector to 15%+10%=25% (at limit)
    assert "B" not in sells


def test_single_name_trim_then_residual_sector_still_over_trims_sibling() -> None:
    """R147 companion: when A's single-name trim does NOT fully clear the sector
    over-limit, the sibling B must still be trimmed by the RESIDUAL (post-A-trim)
    excess — not skipped, not over-trimmed. A=20%→15%, B=12%, sector 32%→27% after
    A → residual 2% over 25% → B trimmed by 2% (to 10%)."""
    portfolio_value = 1_000_000.0
    positions = [
        _make_position("A", "A", "白酒", 200_000.0, 0.20),  # 20% > 15% single-name
        _make_position("B", "B", "白酒", 120_000.0, 0.12),  # 12%; sector = 32% > 25%
    ]
    actions = compute_rebalance_actions(positions, portfolio_value)
    b_action = next((a for a in actions if a.ticker == "B" and a.action == "sell"), None)
    # A's trim: 20%→15%, sector now 15%+12%=27%, residual over 25% = 2% → B 12%→10%
    assert b_action is not None
    assert b_action.target_weight == pytest.approx(0.10, abs=1e-6)


# ===========================================================================
# 6. drift_threshold 生效
# ===========================================================================


def test_drift_threshold_filters_small_deviations() -> None:
    """drift_threshold=0.10 时, |delta|=6% 应被过滤。"""
    portfolio_value = 1_000_000.0
    positions = [
        _make_position("000001", "平安银行", "银行", 40_000.0, 0.10),  # delta=+6%
    ]
    # 默认 5% 阈值: 应有 add
    actions_default = compute_rebalance_actions(positions, portfolio_value)
    assert len(actions_default) == 1

    # 10% 阈值: 应被过滤
    actions_loose = compute_rebalance_actions(positions, portfolio_value, drift_threshold=0.10)
    assert actions_loose == []


# ===========================================================================
# 7. 最小交易金额过滤
# ===========================================================================


def test_min_trade_amount_filters_tiny_adjustments() -> None:
    """delta_amount 小于 min_trade_amount → hold (不入列)。"""
    portfolio_value = 1_000_000.0
    # delta = +6% → 60,000 元
    pos1 = _make_position("000001", "平安银行", "银行", 40_000.0, 0.10)
    actions = compute_rebalance_actions([pos1], portfolio_value, min_trade_amount=100_000.0)
    # 60,000 < 100,000 → 过滤
    assert actions == []

    # 30,000 阈值则保留
    actions2 = compute_rebalance_actions([pos1], portfolio_value, min_trade_amount=30_000.0)
    assert len(actions2) == 1


# ===========================================================================
# 8. 优先级判定
# ===========================================================================


def test_priority_assignment() -> None:
    """|delta| >= strong_drift_threshold → 优先级 2; 否则优先级 3。"""
    portfolio_value = 1_000_000.0
    positions = [
        _make_position("AAA", "强偏离", "X", 50_000.0, 0.20),  # +15% delta → 优先级 2
        _make_position("BBB", "弱偏离", "Y", 60_000.0, 0.13),  # +7% delta → 优先级 3
    ]
    actions = compute_rebalance_actions(positions, portfolio_value, strong_drift_threshold=0.10)
    by_ticker = {a.ticker: a for a in actions}
    assert by_ticker["AAA"].priority == 2
    assert by_ticker["BBB"].priority == 3


# ===========================================================================
# 9. 持仓为空 → 空列表
# ===========================================================================


def test_empty_positions_returns_empty_list() -> None:
    actions = compute_rebalance_actions([], 1_000_000.0)
    assert actions == []


# ===========================================================================
# 10. delta 计算
# ===========================================================================


def test_delta_calculation_basics() -> None:
    """delta_weight == target - current, delta_amount == delta_weight * pv。"""
    pv = 1_000_000.0
    positions = [_make_position("X", "x", "S", 30_000.0, 0.10)]  # current=3%, target=10%
    actions = compute_rebalance_actions(positions, pv)
    assert len(actions) == 1
    a = actions[0]
    assert abs(a.current_weight - 0.03) < 1e-6
    assert abs(a.target_weight - 0.10) < 1e-6
    assert abs(a.delta_weight - 0.07) < 1e-6
    assert abs(a.delta_amount - 70_000.0) < 1e-3


# ===========================================================================
# 11. CLI smoke test
# ===========================================================================


def test_cli_rebalance_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--rebalance 加上 --positions-path 提供测试持仓, 应以退出码 0 结束。"""
    monkeypatch.chdir(tmp_path)

    positions_payload = [
        {"ticker": "000001", "name": "平安银行", "sector": "银行", "current_value": 100_000.0, "target_weight": 0.10},
        {"ticker": "600519", "name": "贵州茅台", "sector": "白酒", "current_value": 250_000.0, "target_weight": 0.10},
    ]
    positions_file = tmp_path / "positions.json"
    positions_file.write_text(json.dumps({"portfolio_value": 1_000_000.0, "positions": positions_payload}), encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.main",
            "--rebalance",
            f"--positions-path={positions_file}",
            "--drift-threshold=0.05",
        ],
        cwd=str(repo_root),
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    combined = result.stdout + result.stderr
    assert "再平衡" in combined or "rebalance" in combined.lower()


# ===========================================================================
# 12. Web 端点 smoke test
# ===========================================================================


def test_web_endpoint_smoke() -> None:
    """POST /api/portfolio/rebalance 应正确返回 RebalanceResponse。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.risk_metrics import router as risk_router

    app = FastAPI()
    app.include_router(risk_router, prefix="/api")
    client = TestClient(app)

    payload = {
        "portfolio_value": 1_000_000.0,
        "positions": [
            {"ticker": "000001", "name": "平安银行", "sector": "银行", "current_value": 100_000.0, "target_weight": 0.10},
            {"ticker": "600519", "name": "贵州茅台", "sector": "白酒", "current_value": 250_000.0, "target_weight": 0.10},
        ],
        "drift_threshold": 0.05,
    }
    resp = client.post("/api/portfolio/rebalance", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "actions" in data
    assert "portfolio_value" in data
    # 茅台 15% 超配应入列
    tickers = [a["ticker"] for a in data["actions"]]
    assert "600519" in tickers


# ===========================================================================
# 13. portfolio_value=0 / NaN → 空列表
# ===========================================================================


def test_zero_portfolio_value_returns_empty() -> None:
    pos = [_make_position("X", "x", "S", 50_000.0, 0.10)]
    assert compute_rebalance_actions(pos, 0.0) == []
    assert compute_rebalance_actions(pos, float("nan")) == []
    assert compute_rebalance_actions(pos, -100.0) == []


# ===========================================================================
# 14. format_rebalance_actions
# ===========================================================================


def test_format_rebalance_actions_basic() -> None:
    pv = 1_000_000.0
    actions = [
        RebalanceAction(
            ticker="600519",
            name="贵州茅台",
            action="trim",
            sector="白酒",
            current_weight=0.25,
            target_weight=0.10,
            delta_weight=-0.15,
            delta_amount=-150_000.0,
            reason="严重超配 15%",
            priority=2,
        )
    ]
    text = format_rebalance_actions(actions, pv, date_label="2026-06-07")
    assert "组合再平衡建议" in text
    assert "2026-06-07" in text
    assert "600519" in text
    assert "贵州茅台" in text
    assert "¥1,000,000" in text
    assert "严重超配" in text


def test_format_rebalance_actions_empty() -> None:
    text = format_rebalance_actions([], 1_000_000.0)
    assert "无再平衡建议" in text or "对齐" in text


# ===========================================================================
# 15. RebalanceAction.to_dict
# ===========================================================================


def test_rebalance_action_to_dict_roundtrip() -> None:
    a = RebalanceAction(
        ticker="X",
        name="x",
        action="buy",
        sector="S",
        current_weight=0.0,
        target_weight=0.05,
        delta_weight=0.05,
        delta_amount=50_000.0,
        reason="新开仓位 (目标 5.0%)",
        priority=2,
    )
    d = a.to_dict()
    assert d["ticker"] == "X"
    assert d["action"] == "buy"
    assert d["priority"] == 2
    assert d["delta_amount"] == 50_000.0


# ===========================================================================
# 16. 行业硬约束: 单只本行业内最重者被减仓
# ===========================================================================


def test_industry_hard_limit_only_trims_heaviest() -> None:
    """行业超限时, 只减仓本行业最重的一只 (不连锁清仓)。"""
    portfolio_value = 1_000_000.0
    positions = [
        _make_position("A1", "x", "白酒", 150_000.0, 0.10),  # 15%, 最重
        _make_position("A2", "y", "白酒", 120_000.0, 0.10),  # 12%
        _make_position("A3", "z", "白酒", 80_000.0, 0.10),  # 8%
        # 累计 35%
    ]
    actions = compute_rebalance_actions(positions, portfolio_value)
    forced = [a for a in actions if a.priority == 1 and "行业" in a.reason]
    # 应该只 trim 一只 (最重 A1)
    assert len(forced) == 1
    assert forced[0].ticker == "A1"


# ===========================================================================
# 17. 优先级 1 单标的超 single_name_hard_limit
# ===========================================================================


def test_single_name_hard_limit_triggers_priority_1() -> None:
    """单标的超 15% 硬限制, 强制减仓到上限。"""
    pv = 1_000_000.0
    positions = [_make_position("X", "x", "S", 200_000.0, 0.10)]  # 当前 20%, 超过 15%
    actions = compute_rebalance_actions(positions, pv)
    forced = [a for a in actions if a.priority == 1]
    assert len(forced) == 1
    assert forced[0].action == "sell"
    assert forced[0].target_weight == SINGLE_NAME_HARD_LIMIT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
