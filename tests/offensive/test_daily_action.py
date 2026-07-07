"""--daily-action 测试 + paper_tracker 测试。"""

from __future__ import annotations

import json
from pathlib import Path

from src.screening.offensive.paper_tracker import PaperTracker
from src.screening.offensive.known_distributions import get_known_distribution
from src.screening.offensive.kelly import compute_kelly_size

# ---- paper_tracker ----


def test_paper_tracker_state_initializes(tmp_path):
    t = PaperTracker(journal_dir=tmp_path)
    assert t.state.nav == 1.0
    assert t.state.drawdown_pct == 0.0


def test_paper_tracker_update_pnl(tmp_path):
    t = PaperTracker(journal_dir=tmp_path)
    t.update_pnl(+0.05)
    assert abs(t.state.nav - 1.05) < 1e-9
    assert t.state.drawdown_pct == 0.0  # 新高, 无回撤
    t.update_pnl(-0.03)
    assert abs(t.state.nav - 1.0185) < 1e-5
    assert t.state.drawdown_pct < 0  # 有回撤


def test_paper_tracker_drawdown_action(tmp_path):
    t = PaperTracker(journal_dir=tmp_path)
    assert t.drawdown_action() == "normal"
    # 模拟 -16% 回撤
    t.update_pnl(-0.16)
    assert t.drawdown_action() == "decrease"
    # 模拟 -22% 回撤
    t2 = PaperTracker(journal_dir=tmp_path)
    t2.update_pnl(-0.22)
    assert t2.drawdown_action() == "liquidate"


def test_paper_tracker_record_buy(tmp_path):
    t = PaperTracker(journal_dir=tmp_path)
    t.record_buy("20260707", "300502", "btst_breakout", 10, 50.0, 0.05, 46.0, 45.0, "跌破45")
    assert t.state.open_positions == 1
    journal = tmp_path / "journal.jsonl"
    assert journal.exists()
    lines = journal.read_text().strip().split("\n")
    assert len(lines) == 1
    assert "BUY" in lines[0]


def test_paper_tracker_state_persists(tmp_path):
    t1 = PaperTracker(journal_dir=tmp_path)
    t1.update_pnl(+0.05)
    # 新实例读同一个 path → 应恢复 state
    t2 = PaperTracker(journal_dir=tmp_path)
    assert abs(t2.state.nav - 1.05) < 1e-9


# ---- known_distributions ----


def test_btst_t10_distribution_exists():
    dist = get_known_distribution("btst_breakout", 10)
    assert dist is not None
    assert dist.n == 5374
    assert dist.convexity_ratio > 1.0
    assert dist.winrate > 0.5
    assert abs(dist.expected_return - 0.0257) < 0.001


def test_unknown_setup_returns_none():
    assert get_known_distribution("nonexistent_setup", 10) is None


def test_btst_t10_kelly_positive():
    """BTST T+10 的已知分布 → Kelly + positive (正 edge)。"""
    dist = get_known_distribution("btst_breakout", 10)
    kelly = compute_kelly_size(dist, max_pct=0.10)
    assert kelly.position_pct > 0  # 正 edge → 正仓位
    assert kelly.capped is False or kelly.position_pct == 0.10  # half-Kelly < 10% 或 cap
