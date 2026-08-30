"""paper_tracker 结算基座 — 错锚回退与陈旧披露回归 (R71 Op3, 对抗审查收口)。

钉死 (全 hermetic, 数值断言非对称):
- 错锚回退 (DEFECT-1): close_matured last-resort (execution + close-to-close 双
  None, 典型: price_loader 空帧) 此前用 fetch_actual_returns(from_date=批次最早
  buy_date) 的 ret_pct 给每个仓位记 P&L — 非最早仓位得到别的持仓窗口的收益
  (PoC: 真实 -5% 记成 +30%)。修复 = 按本仓位 buy_date 重锚; 本位锚也无 day_N →
  诚实跳过 (停牌/数据未成熟保持仓), 不再写错窗 P&L。
- 陈旧披露 (DEFECT-2): 无到期仓早退路径此前不重置 last_closed_positions,
  复用 tracker 的渲染消费方 (daily_action.py closed_positions) 会重复披露
  上一批平仓。修复 = 早退时重置 []。
- 正确锚路径数值不变: 批次最早仓位 (锚正确) 的 P&L 与既有 close-to-close
  last-resort 口径逐位一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC))

from src.screening.offensive.paper_tracker import PaperTracker  # noqa: E402


def _fetcher_rows(closes_by_date: dict[str, float]) -> list[dict]:
    """[(YYYYMMDD, close)] → fetcher 原始行 (升序)。"""
    return [
        {"time": f"{d[:4]}-{d[4:6]}-{d[6:]}", "close": c}
        for d, c in sorted(closes_by_date.items())
    ]


def _june_world() -> tuple[dict[str, list[dict]], dict[str, float]]:
    """双仓位世界: A buy 20260601 (批次锚=它), B buy 20260608。

    A: 收盘 100 → 20260611 起 110 (批次锚与本位锚同窗, P&L 恒 +10%)。
    B: 收盘 100 (≤0607) → 130 (0608..0617) → 123.5 (≥0618)。
       批次锚 (0601) day_10 = 0611 close 130 → +30% (错);
       本位锚 (0608) day_10 = 0618 close 123.5 → -5% (真实持仓窗)。
    """
    days = [f"202606{d:02d}" for d in range(1, 29)]

    def close_of(ticker: str, d: str) -> float:
        if ticker == "000001":
            return 110.0 if d >= "20260611" else 100.0
        if d >= "20260618":
            return 123.5
        if d >= "20260608":
            return 130.0
        return 100.0

    raw = {
        t: _fetcher_rows({d: close_of(t, d) for d in days})
        for t in ("000001", "000002")
    }
    entries = {"000001": 100.0, "000002": 130.0}
    return raw, entries


_EMPTY_LOADER = lambda ticker, as_of: pd.DataFrame()  # noqa: E731 — loader 故障语义


def _make_tracker(tmp_path: Path) -> PaperTracker:
    tr = PaperTracker(journal_dir=tmp_path)
    tr.record_buy("20260601", "000001", "btst_breakout", 10, 100.0,
                  0.10, 85.0, 92.0, "x")
    tr.record_buy("20260608", "000002", "btst_breakout", 10, 130.0,
                  0.10, 85.0, 92.0, "x")
    return tr


def test_last_resort_uses_per_position_anchor(tmp_path):
    """DEFECT-1 RED→GREEN: 非最早仓位的 last-resort P&L 必须来自本仓位持仓窗。"""
    tr = _make_tracker(tmp_path)
    raw, entries = _june_world()
    fetcher = lambda t, s, e: raw.get(t, [])  # noqa: E731

    closed = tr.close_matured(as_of="20260630",
                              use_data_fetcher=fetcher, price_loader=_EMPTY_LOADER)
    by_ticker = {c["ticker"]: c for c in closed}
    assert set(by_ticker) == {"000001", "000002"}
    # A 是批次锚自身 — 两条路径同值 (回归锚)
    assert by_ticker["000001"]["realized_pnl"] == pytest.approx(0.10, abs=1e-9)
    # B 修复前: +0.30 (批次最早日锚, 错窗); 修复后: -0.05 (本位锚, 真实持仓窗)
    assert by_ticker["000002"]["realized_pnl"] == pytest.approx(-0.05, abs=1e-9)


def test_last_resort_honest_skip_when_position_anchor_missing(tmp_path):
    """本位锚无 day_10 (停牌/数据未成熟) → 诚实跳过, 不写错窗 P&L。

    B 的数据 20260610 截止 (本位锚 0608 不足 11 行) — 批次锚 (0601) 窗内
    却仍有 day_10。修复前: 用批次锚数据结算 (错窗); 修复后: 跳过保持仓。
    """
    tr = _make_tracker(tmp_path)
    raw, _ = _june_world()
    truncated = {t: [r for r in rows if r["time"] <= "2026-06-10"]
                 for t, rows in raw.items()}
    fetcher = lambda t, s, e: truncated.get(t, [])  # noqa: E731

    closed = tr.close_matured(as_of="20260630",
                              use_data_fetcher=fetcher, price_loader=_EMPTY_LOADER)
    by_ticker = {c["ticker"]: c for c in closed}
    # A 的本位锚窗 (0601..0611) 也被截 → 同样诚实跳过
    assert by_ticker.get("000001") is None
    assert by_ticker.get("000002") is None
    assert tr.state.open_positions == 2  # 两仓都保留, 等数据成熟


def test_rerun_resets_last_closed_positions(tmp_path):
    """DEFECT-2: 幂等重跑无平仓 → last_closed_positions 必须清空而非保留上一批。"""
    tr = _make_tracker(tmp_path)
    raw, _ = _june_world()
    fetcher = lambda t, s, e: raw.get(t, [])  # noqa: E731

    closed1 = tr.close_matured(as_of="20260630",
                               use_data_fetcher=fetcher, price_loader=_EMPTY_LOADER)
    assert len(closed1) == 2
    assert len(tr.last_closed_positions) == 2

    closed2 = tr.close_matured(as_of="20260630",
                               use_data_fetcher=fetcher, price_loader=_EMPTY_LOADER)
    assert closed2 == []
    assert tr.last_closed_positions == [], \
        "早退路径必须重置披露缓存, 否则渲染消费方重复披露上一批平仓"


def test_close_to_close_primary_path_unchanged(tmp_path):
    """正确锚路径数值不变: price_loader 有数据时 close-to-close 主回退口径不动。

    close-to-close 口径: close[buy_date] → close[buy_date+10 行], 无滑点。
    B: 130 (0608) → 123.5 (0618) → -5%; A: 100 (0601) → 110 (0611) → +10%。
    """
    tr = _make_tracker(tmp_path)
    raw, entries = _june_world()
    fetcher = lambda t, s, e: raw.get(t, [])  # noqa: E731

    days = sorted({r["time"] for r in raw["000001"]})

    def loader(ticker: str, as_of: str) -> pd.DataFrame:
        rows = [r for r in raw.get(ticker, []) if r["time"] in days]
        return pd.DataFrame({
            "date": pd.to_datetime([r["time"] for r in rows]),
            "close": [r["close"] for r in rows],
        })

    closed = tr.close_matured(as_of="20260630",
                              use_data_fetcher=fetcher, price_loader=loader)
    by_ticker = {c["ticker"]: c for c in closed}
    assert by_ticker["000002"]["realized_pnl"] == pytest.approx(-0.05, abs=1e-9)
    assert by_ticker["000001"]["realized_pnl"] == pytest.approx(0.10, abs=1e-9)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
