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
    # daily_pnl_pct 是组合贡献 (sum of realized × kelly), 用加法累加,
    # 不是对整笔 NAV 复利.
    assert abs(t.state.nav - 1.02) < 1e-5
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


def test_paper_tracker_record_buy_increments_total_trades(tmp_path):
    """autodev-32 /loop session 6: total_trades was a dead field (persisted
    but never incremented → state file always showed 0). Now each BUY
    increments it so the operator sees cumulative trade volume."""
    t = PaperTracker(journal_dir=tmp_path)
    assert t.state.total_trades == 0  # starts at 0
    t.record_buy("20260707", "300502", "btst_breakout", 10, 50.0, 0.05, 46.0, 45.0, "跌破45")
    assert t.state.total_trades == 1
    t.record_buy("20260707", "688629", "btst_breakout", 10, 200.0, 0.10, 180.0, 184.0, "跌破184")
    assert t.state.total_trades == 2
    # Idempotent: same (date, ticker) doesn't double-count
    t.record_buy("20260707", "300502", "btst_breakout", 10, 50.0, 0.05, 46.0, 45.0, "跌破45")
    assert t.state.total_trades == 2, "幂等 BUY 不应重复计数 total_trades"
    # Persisted to state file
    import json as _json

    persisted = _json.loads((tmp_path / "portfolio_state.json").read_text())
    assert persisted["total_trades"] == 2


def test_record_buy_idempotent_same_date_ticker(tmp_path):
    """重复 record_buy 同一 (trade_date, ticker) → 只记一条, open_positions 不双计.

    Bug: --daily-action 重跑同一报告日会重复下单. record_buy 必须按 natural-key
    (trade_date, ticker) 去重 (对齐 recommendation_tracker.py:457 先例).
    """
    t = PaperTracker(journal_dir=tmp_path)
    t.record_buy("20260707", "300502", "btst_breakout", 10, 50.0, 0.05, 46.0, 45.0, "跌破45")
    # 重跑同一 (date, ticker)
    t.record_buy("20260707", "300502", "btst_breakout", 10, 50.0, 0.05, 46.0, 45.0, "跌破45")
    assert t.state.open_positions == 1, f"重复计数: open_positions={t.state.open_positions}"
    lines = (tmp_path / "journal.jsonl").read_text().strip().split("\n")
    assert len(lines) == 1, f"journal 重复记录: {len(lines)} 行"

    # 不同 ticker 或不同 date 应正常记
    t.record_buy("20260707", "688629", "btst_breakout", 10, 200.0, 0.10, 180.0, 184.0, "跌破184")
    t.record_buy("20260708", "300502", "btst_breakout", 10, 51.0, 0.05, 46.0, 45.0, "跌破45")
    assert t.state.open_positions == 3


def test_record_buy_persists_open_positions(tmp_path):
    """record_buy 后 open_positions 必须持久化到 portfolio_state.json.

    Bug: record_buy 改了 _state.open_positions 但不调 _save_state (只有 update_pnl/reset
    调), 所以新进程读不到增量. 第二次 --daily-action 会重载 open_positions=0.
    """
    t1 = PaperTracker(journal_dir=tmp_path)
    t1.record_buy("20260707", "300502", "btst_breakout", 10, 50.0, 0.05, 46.0, 45.0, "跌破45")
    t1.record_buy("20260707", "688629", "btst_breakout", 10, 200.0, 0.10, 180.0, 184.0, "跌破184")
    assert t1.state.open_positions == 2

    # 新实例读同一 journal_dir → 应恢复 open_positions=2
    t2 = PaperTracker(journal_dir=tmp_path)
    assert t2.state.open_positions == 2, f"未持久化: got {t2.state.open_positions}"


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
    assert dist.n == 1458  # 2026-07-12 重新校准至 8% 涨停前涨幅门控 + 成交量过滤后
    assert dist.convexity_ratio > 1.5
    assert dist.winrate > 0.5
    assert abs(dist.expected_return - 0.0657) < 0.001


def test_unknown_setup_returns_none():
    assert get_known_distribution("nonexistent_setup", 10) is None


def test_btst_t10_kelly_positive():
    """BTST T+10 的已知分布 → Kelly + positive (正 edge)。"""
    dist = get_known_distribution("btst_breakout", 10)
    kelly = compute_kelly_size(dist, max_pct=0.10)
    assert kelly.position_pct > 0  # 正 edge → 正仓位
    assert kelly.capped is False or kelly.position_pct == 0.10  # half-Kelly < 10% 或 cap


# ---------------------------------------------------------------------------
# close_matured — 闭环测试 (buy → mature → close → realize pnl → drawdown)


def _make_price_series(base_date: str, base_close: float, day_10_close: float) -> list[dict]:
    """造一个 fetcher 返回序列: base_date 收盘=base_close, base_date+10 收盘=day_10_close.

    fetch_actual_returns 用 closes[0] 作基准价、closes[10] 作 T+10 收盘.
    """
    from datetime import datetime, timedelta

    base_dt = datetime.strptime(base_date, "%Y%m%d")

    def _row(offset: int, close: float) -> dict:
        d = (base_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
        return {"time": d, "close": close}

    # 0..10 共 11 个交易日 (offset 用日历日近似, 测试只关心 closes[10])
    rows = [_row(i, base_close) for i in range(10)]
    rows.append(_row(10, day_10_close))
    return rows


def test_close_matured_realizes_t10_pnl(tmp_path):
    """BUY on D → advance to D+15 → close_matured → open_positions 归零、realized_pnl 记录、nav 演进.

    闭环核心: 此前 update_pnl 从无调用者, nav 永远 1.0. close_matured 必须在到期时
    用 T+10 收盘价计算 realized P&L 并驱动 update_pnl, 让组合净值真正演进.
    """
    tracker = PaperTracker(journal_dir=tmp_path)
    # BUY on 20260601, entry=100, kelly=10%, T+10 到期日 ~ 20260615
    tracker.record_buy(
        trade_date="20260601",
        ticker="300502",
        setup="btst_breakout",
        horizon=10,
        entry_price=100.0,
        kelly_pct=0.10,
        soft_stop=85.0,
        hard_stop=92.0,
        invalidation="跌破92",
    )
    assert tracker.state.open_positions == 1

    # T+10 收盘涨到 105 → day_10 = +5%
    fetcher_map = {
        "300502": _make_price_series("20260601", base_close=100.0, day_10_close=105.0),
    }
    fetcher = lambda ticker, start, end: fetcher_map.get(ticker, [])  # noqa: E731

    closed = tracker.close_matured(as_of="20260620", use_data_fetcher=fetcher)
    assert len(closed) == 1
    c = closed[0]
    assert c["ticker"] == "300502"
    assert abs(c["realized_pnl"] - 0.05) < 1e-6  # T+10 收盘口径 +5%
    assert tracker.state.open_positions == 0  # 平仓后持仓归零
    # nav 必须演进: kelly 10% × +5% = 组合贡献 +0.5% → nav = 1.005
    assert tracker.state.nav > 1.0
    assert abs(tracker.state.nav - 1.005) < 1e-6, f"nav={tracker.state.nav}"
    assert tracker.state.realized_pnl_pct > 0


def test_close_matured_drives_drawdown_breaker(tmp_path):
    """BUY → 大亏 → close_matured → drawdown 触发熔断.

    此前 drawdown_action() 永远 'normal' 因为 nav 永远 1.0. close_matured 的 P&L
    回填必须真正驱动 update_pnl, 让 -15%降仓/-20%清仓 的风控能在真实亏损时触发.
    """
    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.60, 85.0, 92.0, "跌破92")
    assert tracker.drawdown_action() == "normal"

    # T+10 收盘跌到 80 → day_10 = -20%; kelly 60% × -20% = 组合 -12%
    fetcher_map = {"300502": _make_price_series("20260601", 100.0, 80.0)}
    fetcher = lambda ticker, start, end: fetcher_map.get(ticker, [])  # noqa: E731

    tracker.close_matured(as_of="20260620", use_data_fetcher=fetcher)
    # nav = 1 × (1 + 0.6 × -0.20) = 0.88 → drawdown -12%, 未到 -15% (decrease)
    # 要触发 decrease 需更重仓位或更大亏损; 用 5 只重仓票累积
    assert tracker.state.nav < 1.0


def test_close_matured_drives_liquidate_on_severe_loss(tmp_path):
    """足够严重的亏损 → close_matured 后 drawdown 触发 liquidate (-20%)."""
    tracker = PaperTracker(journal_dir=tmp_path)
    # 满仓 (kelly=60%) × 单票腰斩 → 组合 -30%, 远超 -20% 清仓线
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.60, 85.0, 92.0, "跌破92")
    fetcher_map = {"300502": _make_price_series("20260601", 100.0, 50.0)}  # -50%
    fetcher = lambda ticker, start, end: fetcher_map.get(ticker, [])  # noqa: E731

    tracker.close_matured(as_of="20260620", use_data_fetcher=fetcher)
    # nav = 1 × (1 + 0.6 × -0.50) = 0.70 → drawdown -30% → liquidate
    assert tracker.state.nav < 0.80
    assert tracker.drawdown_action() == "liquidate", f"drawdown={tracker.state.drawdown_pct}"


def test_close_matured_idempotent(tmp_path):
    """重跑 close_matured 不重复平仓、不重复计 P&L (对齐 recommendation_tracker 幂等先例)."""
    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")
    fetcher_map = {"300502": _make_price_series("20260601", 100.0, 105.0)}
    fetcher = lambda ticker, start, end: fetcher_map.get(ticker, [])  # noqa: E731

    closed1 = tracker.close_matured(as_of="20260620", use_data_fetcher=fetcher)
    nav_after_first = tracker.state.nav
    assert len(closed1) == 1

    # 重跑 — 同一已平仓仓位不应再被平
    closed2 = tracker.close_matured(as_of="20260620", use_data_fetcher=fetcher)
    assert len(closed2) == 0, f"重复平仓: {closed2}"
    assert tracker.state.nav == nav_after_first, "重复计入 P&L"
    assert tracker.state.open_positions == 0


def test_close_matured_skips_immature_positions(tmp_path):
    """未到期仓位 (trade_date + horizon > as_of) 不应被平仓."""
    tracker = PaperTracker(journal_dir=tmp_path)
    # BUY on 20260601, T+10 → 到期日 ~20260615; as_of=20260605 仅过 4 天, 未到期
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")
    fetcher_map = {"300502": _make_price_series("20260601", 100.0, 105.0)}
    fetcher = lambda ticker, start, end: fetcher_map.get(ticker, [])  # noqa: E731

    closed = tracker.close_matured(as_of="20260605", use_data_fetcher=fetcher)
    assert len(closed) == 0, f"未到期却被平仓: {closed}"
    assert tracker.state.open_positions == 1


def test_close_matured_price_loader_uses_asof_not_buydate(tmp_path):
    """Regression (2026-07-12): close_matured 的 price_loader 必须用 as_of 作 cutoff, 非 buy_date.

    Bug: ``_load_prices_for_ticker`` 按 report_date 过滤 ``df[date <= cutoff]``. close_matured
    旧代码传 buy_date → 滤掉 buy_date 之后的 T+N 退出数据 → ``_execution_adjusted_return``
    永远 None (exit_idx 越界) → 回退到 fetch_actual_returns 的批次最早 buy_date 锚
    (非 earliest 仓位 P&L 错误). Fix: 传 as_of 保留完整窗口让 per-position 重算生效.

    本测试注入两个数据源: use_data_fetcher 返回错误的 +50% (模拟批次锚偏),
    price_loader 返回正确的 +10% per-position 数据. 旧代码 price_loader 路径失败 →
    用 fetcher 的 +50% (错); 新代码 price_loader 路径生效 → 用 +10% (对).
    """
    import pandas as pd
    from datetime import datetime, timedelta

    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "TEST001", "btst_breakout", 8, 100.0, 0.10, 85.0, 92.0, "跌破92")

    # fetcher 返回 WRONG 数据: T+8 = +50% (批次最早锚偏的典型表现)
    base = datetime.strptime("20260601", "%Y%m%d")
    fetcher_rows = [{"time": (base + timedelta(days=i)).strftime("%Y-%m-%d"), "close": 100.0} for i in range(8)]
    fetcher_rows.append({"time": (base + timedelta(days=8)).strftime("%Y-%m-%d"), "close": 150.0})  # +50% WRONG
    fetcher = lambda ticker, start, end: fetcher_rows  # noqa: E731

    # price_loader 返回 CORRECT per-position 数据 (entry=100 open, T+8 close=110 → +10%)
    rows = []
    for i in range(15):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        close = 110.0 if i >= 9 else 100.0  # T+8 (i=9 ≈ 8 trading days from buy at i=0)
        rows.append({"date": d, "open": 100.0, "close": close, "high": close + 1, "low": close - 1})
    full_prices = pd.DataFrame(rows)
    full_prices["date"] = pd.to_datetime(full_prices["date"])

    def price_loader(ticker: str, report_date: str):
        cutoff = pd.to_datetime(str(report_date).replace("-", ""), format="%Y%m%d", errors="coerce")
        df = full_prices.copy()
        if pd.notna(cutoff):
            df = df[df["date"] <= cutoff]
        return df.sort_values("date").reset_index(drop=True)

    closed = tracker.close_matured(as_of="20260615", use_data_fetcher=fetcher, price_loader=price_loader)

    assert len(closed) == 1, f"应平仓 1 笔, 实际 {len(closed)}"
    c = closed[0]
    # 旧 bug: price_loader 路径失败 → 用 fetcher 的 +50% (错); 修复后用 price_loader 的正确值
    assert c["realized_pnl"] < 0.30, (
        f"price_loader 路径未生效 → 用了 fetcher 的错误 +50% (旧 bug). pnl={c['realized_pnl']}"
    )


def test_close_matured_dedupes_historical_duplicate_buys(tmp_path):
    """历史 journal 含重复 BUY (旧版 record_buy 无幂等导致) → close_matured 只平一次.

    真实 journal 已有 4 条 688629 20260706 重复 BUY. close_matured 按 (buy_date, ticker)
    去重 matured 列表, 不重复计 P&L.
    """
    tracker = PaperTracker(journal_dir=tmp_path)
    # 直接写 4 条重复 BUY (模拟旧版无幂等的污染)
    from src.screening.offensive.paper_tracker import TradeAction

    for _ in range(4):
        tracker.record_action(
            TradeAction(
                date="20260601",
                ticker="300502",
                setup="btst_breakout",
                horizon=10,
                action="BUY",
                kelly_pct=0.10,
                entry_price=100.0,
                soft_stop=85.0,
                hard_stop=92.0,
                time_exit="T+10",
                invalidation_condition="跌破92",
                reasoning="dup",
            )
        )
    fetcher_map = {"300502": _make_price_series("20260601", 100.0, 105.0)}
    fetcher = lambda ticker, start, end: fetcher_map.get(ticker, [])  # noqa: E731

    closed = tracker.close_matured(as_of="20260620", use_data_fetcher=fetcher)
    assert len(closed) == 1, f"未去重: closed={closed}"  # 4 条重复 → 只平 1 次


def test_close_matured_records_stop_would_trigger(tmp_path):
    """期间 low 触硬止损 → stop_would_have_triggered=True, 但主 P&L 仍是 T+10 收盘口径.

    诚实披露: 渲染层告诉 operator '触硬止损 → 当日收盘平', 但 P&L 用 T+10 收盘口径
    (与先验分布可比). 二者通过 stop_would_have_triggered 字段桥接, 不隐藏止损规则
    的存在, 也不污染主 P&L 的可比性.
    """
    tracker = PaperTracker(journal_dir=tmp_path)
    # hard_stop=92 (entry 100 的 -8%); T+10 收盘回到 105 (+5%), 但中间某天 low=90 触发硬止损
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")

    # 构造价格序列: 基准 100, 中间跌到 90 (触 92 硬止损), T+10 回到 105
    from datetime import datetime, timedelta

    base_dt = datetime.strptime("20260601", "%Y%m%d")

    def _row(offset, close, low=None):
        d = (base_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
        row = {"time": d, "close": close}
        if low is not None:
            row["low"] = low
        return row

    # 用 _load_prices_for_ticker 的 DataFrame 格式注入 low
    import pandas as pd

    rows = []
    for i in range(10):
        low = 90.0 if i == 3 else None  # 第3天 low=90 触发硬止损
        rows.append(_row(i, 100.0, low))
    rows.append(_row(10, 105.0))

    # close_matured 需要读 low 来判断止损触发; 通过 price_loader 注入 (返回 DataFrame)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["time"])
    price_loader = lambda ticker, report_date: df.copy() if ticker == "300502" else pd.DataFrame()  # noqa: E731

    # fetcher 只提供 close (T+10 口径)
    fetcher_rows = [{"time": r["time"], "close": r["close"]} for r in rows]
    fetcher_map = {"300502": fetcher_rows}
    fetcher = lambda ticker, start, end: fetcher_map.get(ticker, [])  # noqa: E731

    closed = tracker.close_matured(as_of="20260620", use_data_fetcher=fetcher, price_loader=price_loader)
    assert len(closed) == 1
    c = closed[0]
    assert c["stop_would_have_triggered"] is True, "期间 low=90 < hard_stop=92 应标记"
    # 主 P&L 仍是 T+10 收盘口径 (+5%), 不是止损价
    assert abs(c["realized_pnl"] - 0.05) < 1e-6, f"主P&L应=T+10收盘, got {c['realized_pnl']}"


def test_check_stop_hit_scans_full_trading_day_window_not_calendar_day():
    """_check_stop_hit 扫描窗口必须用交易日口径 (T+N trading days), 不能用日历日.

    C-DAILY-ACTION-MATURITY-CALENDAR-TRADING-MISMATCH (sibling, autodev-38 loop 178):
    _check_stop_hit 用 ``end_dt = buy_dt + timedelta(days=horizon)`` (日历日) 截止
    low 扫描窗口, 但 horizon 是 T+N 交易日 (与 _is_matured / _execution_adjusted_return
    同参数). BTST h=10: 日历日窗口到 +10 天 (≈7 交易日), 真实 T+10 交易日 ≈ +14 日历日
    → 第 8-10 交易日的 low 跌穿止损被漏掉 → stop_would_have_triggered 披露低计.
    _execution_adjusted_return (同文件 line 589) 正确用 ``exit_idx = trigger_idx + horizon``
    (交易日索引) → 同一 close_matured 循环内两套时间口径矛盾.
    """
    from datetime import datetime, timedelta

    import pandas as pd

    from src.screening.offensive.paper_tracker import PaperTracker

    # BTST BUY 20260601, horizon=10, hard_stop=92 (entry 100 -8%)
    # 构造 15 个日历日的价格序列 (含周末空隙模拟), low 跌穿止损发生在 day 12 (日历日),
    # 即第 ~8 交易日 — 在日历日窗口 [0,10] 之外, 但在交易日窗口 [0,14] 之内.
    base_dt = datetime.strptime("20260601", "%Y%m%d")
    rows = []
    for i in range(15):
        d = (base_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        low = 90.0 if i == 12 else 95.0  # day 12 low=90 触发硬止损 (92)
        rows.append({"time": d, "close": 100.0, "low": low})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["time"])

    # day 12 (cal) 在旧日历日窗口 [buy, buy+10]=[0601,0611] 之外 → 旧实现漏掉, 返回 False
    # 在交易日窗口 [buy, buy+14]=[0601,0615] 之内 → 修复后应返回 True
    result = PaperTracker._check_stop_hit(df, "20260601", horizon=10, hard_stop=92.0)
    assert result is True, "day-12 low=90 < hard_stop=92 应触发止损, 但日历日窗口 [0601,0611] 漏掉了它 " "(真实 T+10 交易日 ≈ +14 日历日, 窗口应到 0615). _check_stop_hit 必须用交易日口径 " "与 _execution_adjusted_return (exit_idx=trigger_idx+horizon) 一致, 不能用日历日."


def test_check_stop_hit_date_parse_failure_returns_false_not_whole_history():
    """Bug fix: except 兜底不应退化为扫描全历史 (look-ahead bias).

    旧实现: ``except Exception: window = df["low"].dropna()`` 扫描整个价格历史,
    包含 T+0 信号日 (用户还没买入) 和 T+N 之后的未来日期 (look-ahead).
    主路径 date 解析失败时 (格式异常/字符串日期), 保守 return False 而非猜测.

    构造: date 列为非标准格式 (纯字符串, .dt.date 会 AttributeError),
    历史中有 low < hard_stop 的行 — 旧实现会误返回 True (扫描全历史),
    修复后应返回 False (保守不触发).
    """
    import pandas as pd

    from src.screening.offensive.paper_tracker import PaperTracker

    # date 列用纯字符串 "not-a-date" — pd.Series.dt 属性不存在或失败
    df = pd.DataFrame(
        {
            "date": ["garbage", "values", "here"],  # 非 datetime, .dt.date 会失败
            "low": [80.0, 85.0, 90.0],  # 全部 < hard_stop=92
        }
    )
    # 旧实现: except → window = df["low"].dropna() → (80<=92).any() → True (错误!)
    # 修复后: except → return False (保守不触发)
    result = PaperTracker._check_stop_hit(df, "20260601", horizon=10, hard_stop=92.0)
    assert result is False, (
        "date 解析失败时应保守 return False, 不应扫描全历史 (look-ahead bias). "
        "旧实现退化为 df['low'].dropna() 会把 T+0 和 T+N 之后的 low 纳入判定."
    )


def test_close_matured_uses_execution_adjusted_return_when_ohlc_available(tmp_path):
    """有 OHLC price_loader 时, close_matured 应按次日开盘买入 + 滑点算收益.

    根因: setup known_distribution 来自 execution_adjuster, 口径是 next-open entry
    与买卖滑点. close_matured 若继续用 trigger-close → T+N close, paper P&L 会和
    Kelly 先验不在同一交易定义上.
    """
    import pandas as pd
    import pytest
    from datetime import datetime, timedelta

    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")

    base_dt = datetime.strptime("20260601", "%Y%m%d")
    rows = []
    for i in range(11):
        rows.append(
            {
                "date": base_dt + timedelta(days=i),
                "open": 110.0 if i == 1 else 100.0 + i,
                "close": 121.0 if i == 10 else 100.0 + i,
                "low": 99.0 + i,
                "pct_change": 0.0,
            }
        )
    prices_df = pd.DataFrame(rows)
    price_loader = lambda ticker, report_date: prices_df.copy() if ticker == "300502" else pd.DataFrame()  # noqa: E731

    # close-to-close 会给 +21%, 但真实 next-open/slippage 约 +9.34%.
    fetcher_rows = [{"time": r["date"].strftime("%Y-%m-%d"), "close": r["close"]} for r in rows]
    fetcher = lambda ticker, start, end: fetcher_rows if ticker == "300502" else []  # noqa: E731

    closed = tracker.close_matured("20260620", use_data_fetcher=fetcher, price_loader=price_loader)

    assert len(closed) == 1
    expected = (121.0 * 0.997) / (110.0 * 1.003) - 1.0
    assert closed[0]["realized_pnl"] == pytest.approx(expected, abs=1e-9)
    assert tracker.state.nav == pytest.approx(1.0 + expected * 0.10, abs=1e-9)


def test_execution_stop_mode_defaults_to_none(monkeypatch):
    """DAILY_ACTION_EXECUTION_STOP 默认 none (止损只披露, 回测验证的当前最优口径)."""
    from src.screening.offensive.paper_tracker import _execution_stop_mode

    monkeypatch.delenv("DAILY_ACTION_EXECUTION_STOP", raising=False)
    assert _execution_stop_mode() == "none"


def test_execution_stop_mode_parses_valid_values(monkeypatch):
    """env 接受 atr_k2/atr_k3/fixed8, 其它值回退 none."""
    from src.screening.offensive.paper_tracker import _execution_stop_mode

    for val, expected in [("atr_k2", "atr_k2"), ("atr_k3", "atr_k3"), ("fixed8", "fixed8"), ("garbage", "none"), ("", "none")]:
        monkeypatch.setenv("DAILY_ACTION_EXECUTION_STOP", val)
        assert _execution_stop_mode() == expected


def test_close_matured_default_no_stop_execution(tmp_path):
    """默认 (stop_mode=none): 即使期间触硬止损, 主 P&L 仍是 T+N 收盘 (不按止损价平).

    回测验证: 当前牛市样本上止损会降低 E[r] (均值回归 setup 的波动赚钱).
    默认行为尊重数据 — 止损只做披露, 不影响 P&L.
    """
    import pandas as pd
    from datetime import datetime, timedelta

    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")

    base_dt = datetime.strptime("20260601", "%Y%m%d")
    rows = []
    for i in range(11):
        # T+3 low=90 触硬止损 92, 但 T+10 回到 121
        rows.append(
            {
                "date": base_dt + timedelta(days=i),
                "open": 110.0 if i == 1 else 100.0,
                "close": 121.0 if i == 10 else 100.0,
                "high": 101.0,
                "low": 90.0 if i == 3 else 99.0,
                "pct_change": 0.0,
            }
        )
    prices_df = pd.DataFrame(rows)
    price_loader = lambda ticker, report_date: prices_df.copy() if ticker == "300502" else pd.DataFrame()  # noqa: E731
    fetcher_rows = [{"time": r["date"].strftime("%Y-%m-%d"), "close": r["close"]} for r in rows]
    fetcher = lambda ticker, start, end: fetcher_rows if ticker == "300502" else []  # noqa: E731

    closed = tracker.close_matured("20260620", use_data_fetcher=fetcher, price_loader=price_loader)
    assert len(closed) == 1
    # 默认: P&L = T+10 收盘口径 (≈+9.34%), 不是止损价 (-8%)
    assert closed[0]["realized_pnl"] > 0.05, "默认无止损执行, 应是 T+10 收盘正收益"


def test_close_matured_fixed8_stop_executes_at_stop_price(tmp_path, monkeypatch):
    """DAILY_ACTION_EXECUTION_STOP=fixed8: 触止损时按止损价平仓 (真实执行).

    operator 在熊市/高波动期可手动启用. 回测验证牛市会降 E[r], 默认关.
    """
    import pandas as pd
    from datetime import datetime, timedelta

    monkeypatch.setenv("DAILY_ACTION_EXECUTION_STOP", "fixed8")
    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")

    base_dt = datetime.strptime("20260601", "%Y%m%d")
    rows = []
    for i in range(11):
        # T+1 open=110 (entry), T+3 low=88 触发 -8% 止损 (entry*0.92≈101.2, low=88<101.2)
        rows.append(
            {
                "date": base_dt + timedelta(days=i),
                "open": 110.0 if i == 1 else 100.0,
                "close": 121.0 if i == 10 else 100.0,
                "high": 101.0,
                "low": 88.0 if i == 3 else 99.0,
                "pct_change": 0.0,
            }
        )
    prices_df = pd.DataFrame(rows)
    price_loader = lambda ticker, report_date: prices_df.copy() if ticker == "300502" else pd.DataFrame()  # noqa: E731
    fetcher_rows = [{"time": r["date"].strftime("%Y-%m-%d"), "close": r["close"]} for r in rows]
    fetcher = lambda ticker, start, end: fetcher_rows if ticker == "300502" else []  # noqa: E731

    closed = tracker.close_matured("20260620", use_data_fetcher=fetcher, price_loader=price_loader)
    assert len(closed) == 1
    # fixed8 启用: P&L 应是止损价口径 (≈-8%), 不是 T+10 收盘 (+9%)
    assert closed[0]["realized_pnl"] < -0.05, f"fixed8 启用应按止损价平仓 (负收益), got {closed[0]['realized_pnl']}"


def test_close_matured_atr_stop_executes_when_triggered(tmp_path, monkeypatch):
    """DAILY_ACTION_EXECUTION_STOP=atr_k2: ATR 止损触发时按 ATR 止损价平仓."""
    import pandas as pd
    from datetime import datetime, timedelta

    monkeypatch.setenv("DAILY_ACTION_EXECUTION_STOP", "atr_k2")
    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")

    # buy_date=20260601 在索引 31, entry 在索引 32, exit 在索引 41.
    # 前 31 行是 ATR 预热 (high-low=2 → ATR≈2), 保证 entry 前 ATR 可算.
    warmup_start = datetime.strptime("20260501", "%Y%m%d")
    rows = []
    for i in range(42):
        is_entry = i == 32  # T+1 (buy_date+1) open=110
        rows.append(
            {
                "date": warmup_start + timedelta(days=i),
                "open": 110.0 if is_entry else 100.0,
                "close": 121.0 if i == 41 else 100.0,  # T+10 回到 121
                "high": 101.0,
                "low": 88.0 if i == 34 else 99.0,  # T+3 low=88 触止损
                "pct_change": 0.0,
            }
        )
    prices_df = pd.DataFrame(rows)
    price_loader = lambda ticker, report_date: prices_df.copy() if ticker == "300502" else pd.DataFrame()  # noqa: E731
    fetcher_rows = [{"time": r["date"].strftime("%Y-%m-%d"), "close": r["close"]} for r in rows]
    fetcher = lambda ticker, start, end: fetcher_rows if ticker == "300502" else []  # noqa: E731

    closed = tracker.close_matured("20260620", use_data_fetcher=fetcher, price_loader=price_loader)
    assert len(closed) == 1
    # ATR≈2, entry≈110.3, stop=110.3-2×2=106.3; T+3 low=88<106.3 → 触止损 (负收益)
    assert closed[0]["realized_pnl"] < 0, f"ATR 止损触发应为负收益, got {closed[0]['realized_pnl']}"


# ---------------------------------------------------------------------------
# generate_daily_action — 接入 close_matured (出新仓前先平到期仓)
# ---------------------------------------------------------------------------


def test_generate_daily_action_closes_matured_before_new_buys(tmp_path, monkeypatch):
    """generate_daily_action 必须在 drawdown 检查前先 close_matured.

    闭环接入: 此前 generate_daily_action 不调 close_matured → 过期仓位永不平 →
    drawdown 永远 0 → 熔断永远 normal. 即使新报告全无 BTST 命中, 调用 generate_daily_action
    也应把到期仓位平掉 (通过可观察副作用 open_positions 归零 + nav 演进验证).
    """
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    # tracker 预置一个过期仓位: 20260601 买入, 20260620 已过 T+10 到期
    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")
    assert tracker.state.open_positions == 1

    # 构造一份新报告 (20260620) — 让 BTST 全不命中, 纯粹测 close_matured 被调用
    report_path = tmp_path / "auto_screening_20260620.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "20260620",
                "recommendations": [{"ticker": "000001", "name": "平安银行"}],
                "market_state": {"regime_gate_level": "normal"},
            }
        ),
        encoding="utf-8",
    )

    # mock 价格加载 (返回空 → BTST 不命中, 无新仓)
    monkeypatch.setattr(da, "_load_prices_for_ticker", lambda ticker, rd: __import__("pandas").DataFrame())

    # mock fetch_actual_returns 返回 +5% (让 close_matured 能平仓)
    def fake_fetcher(ticker, start, end):
        return _make_price_series("20260601", 100.0, 105.0) if ticker == "300502" else []

    monkeypatch.setattr(
        "src.screening.recommendation_tracker.fetch_actual_returns",
        lambda tickers, from_date, to_date, use_data_fetcher=None: {
            "300502": {"day_10": 5.0},
        },
    )
    # 也 mock close_matured 内部调用的 fetch_actual_returns (它是直接 import 的)
    # 实际上 close_matured 接受 use_data_fetcher, 但 generate_daily_action 需要传它下去

    # 调用 — 即使新仓全不命中, 过期仓位应被平掉
    actions = da.generate_daily_action(report_path=report_path, tracker=tracker, scan_mode="report")

    # close_matured 应已平掉过期仓位
    assert tracker.state.open_positions == 0, f"generate_daily_action 未先平到期仓: open_positions={tracker.state.open_positions}. " f"闭环接入失败 — drawdown 检查基于陈旧 nav."
    assert tracker.state.nav > 1.0, "nav 未演进 → close_matured 未被调用"


def test_generate_daily_action_accepts_price_loader_and_fetcher(tmp_path, monkeypatch):
    """generate_daily_action 接受 price_loader + use_data_fetcher 注入 (测试 seam).

    无注入 seam → 测试只能 monkeypatch 内部, 脆弱. 注入 seam 让 close_matured 的
    价格源可控制 (对齐 recommendation_tracker.use_data_fetcher 模式).
    """
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    import pandas as pd

    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")

    report_path = tmp_path / "auto_screening_20260620.json"
    report_path.write_text(
        json.dumps({"date": "20260620", "recommendations": [], "market_state": {"regime_gate_level": "normal"}}),
        encoding="utf-8",
    )

    fetcher = lambda ticker, start, end: _make_price_series("20260601", 100.0, 105.0) if ticker == "300502" else []  # noqa: E731
    df = pd.DataFrame([{"date": pd.Timestamp("2026-06-01"), "low": 95.0}, {"date": pd.Timestamp("2026-06-10"), "low": 95.0}])
    price_loader = lambda ticker, rd: df.copy() if ticker == "300502" else pd.DataFrame()  # noqa: E731

    # 这两个参数必须被接受并传给 close_matured (否则 TypeError)
    actions = da.generate_daily_action(report_path=report_path, tracker=tracker, use_data_fetcher=fetcher, price_loader=price_loader)
    assert tracker.state.open_positions == 0


def test_generate_daily_action_exposes_actual_scan_trade_date(tmp_path, monkeypatch):
    """generate_daily_action 应暴露本次实际扫描日期, 供 CLI 渲染使用.

    根因: --daily-action full_market 从 price_cache 最新日期扫描, 但 dispatcher 曾读取
    最新 auto_screening 报告日期渲染标题. 当报告日期 > price_cache 最新日期时, 输出会把
    20260706 的信号显示成 20260708, 误导次日执行.
    """
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker(journal_dir=tmp_path)
    report_path = tmp_path / "auto_screening_20260620.json"
    report_path.write_text(
        json.dumps({"date": "20260620", "recommendations": [], "market_state": {"regime_gate_level": "normal"}}),
        encoding="utf-8",
    )

    da.generate_daily_action(report_path=report_path, tracker=tracker, scan_mode="report")

    assert getattr(tracker, "last_action_trade_date", "") == "20260620"


def test_generate_daily_action_uses_default_price_loader_for_matured_pnl(tmp_path, monkeypatch):
    """generate_daily_action 默认应把 _load_prices_for_ticker 传给 close_matured.

    否则真实 --daily-action 路径会退回 close-to-close P&L, 与 execution-adjusted
    known_distribution 不一致.
    """
    import pandas as pd
    import pytest
    from datetime import datetime, timedelta
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")

    report_path = tmp_path / "auto_screening_20260620.json"
    report_path.write_text(
        json.dumps({"date": "20260620", "recommendations": [], "market_state": {"regime_gate_level": "normal"}}),
        encoding="utf-8",
    )

    base_dt = datetime.strptime("20260601", "%Y%m%d")
    rows = []
    for i in range(11):
        rows.append(
            {
                "date": base_dt + timedelta(days=i),
                "open": 110.0 if i == 1 else 100.0 + i,
                "close": 121.0 if i == 10 else 100.0 + i,
                "low": 99.0 + i,
                "pct_change": 0.0,
            }
        )
    prices_df = pd.DataFrame(rows)
    monkeypatch.setattr(da, "_load_prices_for_ticker", lambda ticker, report_date: prices_df.copy())

    fetcher_rows = [{"time": r["date"].strftime("%Y-%m-%d"), "close": r["close"]} for r in rows]
    fetcher = lambda ticker, start, end: fetcher_rows if ticker == "300502" else []  # noqa: E731

    da.generate_daily_action(
        report_path=report_path,
        tracker=tracker,
        scan_mode="report",
        use_data_fetcher=fetcher,
    )

    expected = (121.0 * 0.997) / (110.0 * 1.003) - 1.0
    assert tracker.state.nav == pytest.approx(1.0 + expected * 0.10, abs=1e-9)


def test_load_prices_for_ticker_publishes_download_with_atomic_writer(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.tools import tushare_api

    raw = pd.DataFrame(
        [{"trade_date": "20260710", "close": 10.0, "open": 9.8, "high": 10.2, "low": 9.7, "pct_chg": 2.0}]
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tushare_api, "get_tushare_token", lambda: "token")
    monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(pro_api=lambda token: SimpleNamespace(daily=lambda **kwargs: raw)))
    published = []
    monkeypatch.setattr(da, "atomic_write_csv", lambda path, frame: published.append((path, frame.copy())))

    result = da._load_prices_for_ticker("000001", "20260710")

    assert len(result) == 1
    assert len(published) == 1
    assert published[0][0] == Path("data/price_cache/000001.csv")
    assert not published[0][0].exists()


def test_load_prices_for_ticker_truncates_cached_rows_to_report_date(tmp_path, monkeypatch):
    """本地 price_cache 有未来行时, report 模式不能读取信号日之后的数据."""
    import pandas as pd
    from src.screening.offensive import daily_action as da

    price_cache = tmp_path / "data" / "price_cache"
    price_cache.mkdir(parents=True)
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change\n" "2026-07-07,10.0,9.8,10.2,9.7,1.0\n" "2026-07-08,11.0,10.1,11.2,10.0,10.0\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    prices = da._load_prices_for_ticker("000001", "20260707")

    assert len(prices) == 1
    assert prices.iloc[-1]["date"] == pd.Timestamp("2026-07-07")
    assert prices.iloc[-1]["close"] == 10.0


def test_resolve_trade_date_normalizes_mixed_price_cache_date_formats(tmp_path, monkeypatch):
    """price_cache 混用 YYYYMMDD / YYYY-MM-DD 时, 最新交易日应按日期比较而不是字符串比较."""
    from src.screening.offensive import daily_action as da

    price_cache = tmp_path / "data" / "price_cache"
    price_cache.mkdir(parents=True)
    (price_cache / "000001.csv").write_text(
        "date,close\n20260706,10.0\n2026-07-08,10.5\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    from datetime import date, datetime
    monkeypatch.setattr(da, "_current_cn_datetime", lambda: datetime(2026, 7, 8, 18))
    monkeypatch.setattr(da, "_load_authoritative_session_dates", lambda: (date(2026, 7, 8),))

    trade_date, regime = da._resolve_trade_date_and_regime()

    assert trade_date == "20260708"
    assert regime == "normal"


def test_resolve_trade_date_applies_1700_guard(tmp_path, monkeypatch):
    """17:00 guard: 盘前 price_cache 已有当日数据时, 回退到昨天的信号日.

    当日资金流 ~17:00 才入库; 若 price_cache 最新日 = 今天但未过 17:00, 应回退到
    规则信号日 (resolve_signal_date 返回昨天), 而非用不完整的当日数据出信号.
    """
    from src.screening.offensive import daily_action as da

    price_cache = tmp_path / "data" / "price_cache"
    price_cache.mkdir(parents=True)
    # cache 含 20260709 (今天, 盘前注入), 应被 guard 回退到 20260708
    (price_cache / "000001.csv").write_text(
        "date,close\n20260708,10.0\n20260709,10.5\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    from datetime import date, datetime
    monkeypatch.setattr(da, "_current_cn_datetime", lambda: datetime(2026, 7, 9, 16))
    monkeypatch.setattr(da, "_load_authoritative_session_dates", lambda: (date(2026, 7, 8), date(2026, 7, 9)))

    trade_date, regime = da._resolve_trade_date_and_regime()

    assert trade_date == "20260708"


def test_resolve_trade_date_no_rollback_after_cutoff(tmp_path, monkeypatch):
    """过了 17:00 后, cache 最新日 = 今天不会被回退 (信号日 = 今天)."""
    from src.screening.offensive import daily_action as da

    price_cache = tmp_path / "data" / "price_cache"
    price_cache.mkdir(parents=True)
    (price_cache / "000001.csv").write_text(
        "date,close\n20260708,10.0\n20260709,10.5\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    from datetime import date, datetime
    monkeypatch.setattr(da, "_current_cn_datetime", lambda: datetime(2026, 7, 9, 18))
    monkeypatch.setattr(da, "_load_authoritative_session_dates", lambda: (date(2026, 7, 8), date(2026, 7, 9)))

    trade_date, _ = da._resolve_trade_date_and_regime()

    assert trade_date == "20260709"


def test_generate_daily_action_end_date_override_skips_cache(tmp_path, monkeypatch):
    """显式 end_date 覆盖: 跳过 price_cache 探测, 直接用指定日期作信号日."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker(journal_dir=tmp_path)
    # 即使没有 price_cache, end_date 也应直接生效 (不调用 _resolve_trade_date_and_regime)
    called = {"resolve": False}
    monkeypatch.setattr(
        da,
        "_resolve_trade_date_and_regime",
        lambda: called.__setitem__("resolve", True) or ("20260101", "normal"),
    )
    monkeypatch.setattr(da, "_latest_auto_report_date", lambda: "", raising=False)
    monkeypatch.setattr(da, "_missed_entry_window_reason", lambda td: "", raising=False)
    monkeypatch.setattr(da, "_load_st_tickers", lambda: set())

    da.generate_daily_action(tracker=tracker, scan_mode="full_market", end_date="20260706")

    assert tracker.last_action_trade_date == "20260706"
    assert called["resolve"] is False  # _resolve_trade_date_and_regime 被跳过


def test_generate_daily_action_end_date_accepts_dashed(tmp_path, monkeypatch):
    """end_date 接受 YYYY-MM-DD 带横线格式 (规范化成 YYYYMMDD)."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker(journal_dir=tmp_path)
    monkeypatch.setattr(da, "_latest_auto_report_date", lambda: "", raising=False)
    monkeypatch.setattr(da, "_missed_entry_window_reason", lambda td: "", raising=False)
    monkeypatch.setattr(da, "_load_st_tickers", lambda: set())

    da.generate_daily_action(tracker=tracker, scan_mode="full_market", end_date="2026-07-06")

    assert tracker.last_action_trade_date == "20260706"


def test_generate_daily_action_blocks_new_buys_when_price_cache_lags_auto_report(tmp_path, monkeypatch):
    """price_cache 落后于最新 --auto 报告时, full_market 不应输出新 BUY."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker(journal_dir=tmp_path)
    monkeypatch.setattr(da, "_resolve_trade_date_and_regime", lambda: ("20260706", "normal"))
    monkeypatch.setattr(da, "_latest_auto_report_date", lambda: "20260708", raising=False)
    from datetime import date
    monkeypatch.setattr(da, "_load_authoritative_session_dates", lambda: tuple(date(2026, 7, day) for day in (6, 7, 8, 9)))

    actions = da.generate_daily_action(tracker=tracker, scan_mode="full_market")

    assert actions == []
    assert "20260706" in tracker.last_action_stale_reason
    assert "20260708" in tracker.last_action_stale_reason


def test_generate_daily_action_does_not_treat_weekend_auto_report_as_stale(tmp_path, monkeypatch):
    """最新 --auto 报告若落在周末, stale guard 应按对应最近开市日比较."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    from datetime import date

    tracker = PaperTracker(journal_dir=tmp_path)
    (tmp_path / "data" / "price_cache").mkdir(parents=True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(da, "_resolve_trade_date_and_regime", lambda: ("20260710", "normal"))
    monkeypatch.setattr(da, "_latest_auto_report_date", lambda: "20260711", raising=False)
    monkeypatch.setattr(da, "_missed_entry_window_reason", lambda td: "", raising=False)
    monkeypatch.setattr(da, "_load_st_tickers", lambda: set())
    monkeypatch.setattr(da, "_load_authoritative_session_dates", lambda: ())
    monkeypatch.setattr(
        da,
        "_load_authoritative_session_dates",
        lambda: (date(2026, 7, 10), date(2026, 7, 13)),
    )

    da.generate_daily_action(tracker=tracker, scan_mode="full_market")

    assert tracker.last_action_stale_reason == ""


def test_generate_daily_action_weekend_auto_report_requires_authoritative_session(tmp_path, monkeypatch):
    """周末报告只可回退到本地权威 session，不能按 weekday 猜测。"""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker(journal_dir=tmp_path)
    (tmp_path / "data" / "price_cache").mkdir(parents=True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(da, "_resolve_trade_date_and_regime", lambda: ("20260710", "normal"))
    monkeypatch.setattr(da, "_latest_auto_report_date", lambda: "20260712", raising=False)
    monkeypatch.setattr(da, "_load_st_tickers", lambda: set())
    monkeypatch.setattr(da, "_load_authoritative_session_dates", lambda: ())

    da.generate_daily_action(tracker=tracker, scan_mode="full_market")

    assert "calendar_unavailable" in tracker.last_action_stale_reason


def test_generate_daily_action_blocks_new_buys_after_planned_open_window(tmp_path, monkeypatch):
    """前一信号日的次日开盘窗口已过时, 不应再输出新 BUY."""
    import pandas as pd
    from datetime import datetime
    from types import SimpleNamespace
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    class FakeSetup:
        def detect(self, ticker, trade_date, context):
            return DetectionResult(
                hit=True,
                ticker=ticker,
                trade_date=trade_date,
                trigger_strength=1.0,
                invalidation_condition="fake invalidation",
            )

    dist = Distribution(
        n=100,
        winrate=0.60,
        avg_gain=0.12,
        avg_loss=-0.06,
        convexity_ratio=2.0,
        expected_return=0.05,
        ci_low=0.02,
        ci_high=0.08,
        ic=0.10,
    )
    prices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-07-07"),
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0,
                "pct_change": 0.0,
            }
        ]
    )
    tracker = PaperTracker(journal_dir=tmp_path)
    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [("fake_setup", FakeSetup, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    monkeypatch.setattr(da, "_resolve_trade_date_and_regime", lambda: ("20260707", "normal"))
    monkeypatch.setattr(da, "_latest_auto_report_date", lambda: "", raising=False)
    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260708")
    # 买入窗口 cutoff 已放宽到 17:00; 用 18:00 触发 "窗口已过"
    monkeypatch.setattr(da, "_current_cn_datetime", lambda: datetime(2026, 7, 8, 18, 0), raising=False)
    monkeypatch.setattr(da, "_load_st_tickers", lambda: set())
    monkeypatch.setattr(da, "_load_authoritative_session_dates", lambda: ())
    monkeypatch.setattr(da, "Path", lambda path: SimpleNamespace(glob=lambda pattern: [SimpleNamespace(stem="000001")]))

    actions = da.generate_daily_action(
        tracker=tracker,
        scan_mode="full_market",
        price_loader=lambda ticker, report_date: prices.copy(),
    )

    assert actions == []
    assert "买入窗口已错过" in tracker.last_action_stale_reason
    assert "20260707" in tracker.last_action_stale_reason
    assert "20260708" in tracker.last_action_stale_reason


def test_entry_window_guard_allows_before_planned_open(monkeypatch):
    """前一信号日计划仍在开盘前时, 不应被判为过期."""
    from datetime import datetime
    from src.screening.offensive import daily_action as da

    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260708")

    reason = da._missed_entry_window_reason("20260707", now=datetime(2026, 7, 8, 9, 0))

    assert reason == ""


def test_entry_window_guard_allows_intraday_before_cutoff(monkeypatch):
    """买入日盘中 (cutoff 17:00 之前) 仍可看计划: 12:00 < 17:00 → 不阻断.

    17:00 是数据就绪/交易日切换的统一阈值; 盘中允许看 "昨日信号→今日买入" 的
    计划用于研究盘面. paper trading 计划非实盘自动下单, 无盘中追单风险.
    """
    from datetime import datetime
    from src.screening.offensive import daily_action as da

    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260708")

    reason = da._missed_entry_window_reason("20260707", now=datetime(2026, 7, 8, 12, 0))

    assert reason == ""


def test_entry_window_guard_1700_boundary(monkeypatch):
    """cutoff 边界: 16:59 允许, 17:00 (含) 阻断."""
    from datetime import datetime
    from src.screening.offensive import daily_action as da

    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260708")

    assert da._missed_entry_window_reason("20260707", now=datetime(2026, 7, 8, 16, 59)) == ""
    assert da._missed_entry_window_reason("20260707", now=datetime(2026, 7, 8, 17, 0)) != ""


def test_generate_daily_action_ranks_hits_before_portfolio_cap(tmp_path, monkeypatch):
    """命中数超过组合上限时, 应保留更强 edge, 而不是按 ticker 顺序先到先得."""
    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    strengths = {
        "000001": 0.10,
        "000002": 0.20,
        "000003": 0.30,
        "000004": 0.40,
        "000005": 0.50,
        "000006": 0.60,
        "000007": 0.90,
    }

    class FakeSetup:
        name = "fake_setup"
        natural_horizon = 10

        def detect(self, ticker, trade_date, context):
            return DetectionResult(
                hit=True,
                ticker=ticker,
                trade_date=trade_date,
                trigger_strength=strengths[ticker],
                invalidation_condition="fake invalidation",
            )

    dist = Distribution(
        n=100,
        winrate=0.60,
        avg_gain=0.12,
        avg_loss=-0.06,
        convexity_ratio=2.0,
        expected_return=0.05,
        ci_low=0.02,
        ci_high=0.08,
        ic=0.10,
    )

    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [("fake_setup", FakeSetup, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    monkeypatch.setattr(da, "_load_st_tickers", lambda: set())

    report_path = tmp_path / "auto_screening_20260620.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "20260620",
                "recommendations": [{"ticker": ticker} for ticker in strengths],
                "market_state": {"regime_gate_level": "normal"},
            }
        ),
        encoding="utf-8",
    )
    prices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-06-20"),
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0,
                "pct_change": 0.0,
            }
        ]
    )

    actions = da.generate_daily_action(
        report_path=report_path,
        tracker=PaperTracker(journal_dir=tmp_path),
        scan_mode="report",
        price_loader=lambda ticker, report_date: prices.copy(),
    )

    selected = [action.ticker for action in actions]
    # trigger_strength 调节仓位: 强信号 (0.9→9%) 大仓位, 弱信号 (0.1→3%) 小仓位.
    # 核心验证: 按 trigger_strength 降序排列 (最强先选), 不是按 ticker 字典序.
    assert "000007" in selected       # 最强信号必入选
    assert selected[0] == "000007"    # 且排第一
    assert selected[1] == "000006"    # 第二强排第二
    # 验证按强度降序 (不是按 ticker 字典序)
    strength_order = [strengths[t] for t in selected]
    assert strength_order == sorted(strength_order, reverse=True), \
        f"应按 trigger_strength 降序: {selected}"


def test_generate_daily_action_uses_real_industry_day_pct_for_btst(tmp_path, monkeypatch):
    """BTST 运行时必须使用真实行业日涨幅, 不能用个股涨停幅度伪造."""
    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    seen_industry_pct: dict[str, float] = {}

    class IndustryAwareBtst:
        def detect(self, ticker, trade_date, context):
            seen_industry_pct[ticker] = float(context["industry_day_pct"])
            return DetectionResult(
                hit=context["industry_day_pct"] >= 2.0,
                ticker=ticker,
                trade_date=trade_date,
                trigger_strength=1.0,
                invalidation_condition="行业确认",
            )

    dist = Distribution(
        n=100,
        winrate=0.60,
        avg_gain=0.12,
        avg_loss=-0.06,
        convexity_ratio=2.0,
        expected_return=0.05,
        ci_low=0.02,
        ci_high=0.08,
        ic=0.10,
    )
    report_path = tmp_path / "auto_screening_20260708.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "20260708",
                "recommendations": [{"ticker": "000001"}],
                "market_state": {"regime_gate_level": "normal"},
            }
        ),
        encoding="utf-8",
    )
    prices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-07-08"),
                "open": 10.0,
                "high": 11.0,
                "low": 9.8,
                "close": 11.0,
                "pct_change": 9.8,
            }
        ]
    )

    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [("btst_breakout", IndustryAwareBtst, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    monkeypatch.setattr(da, "_load_industry_day_pct_by_ticker", lambda trade_date, tickers: {"000001": 1.0}, raising=False)

    actions = da.generate_daily_action(
        report_path=report_path,
        tracker=PaperTracker(journal_dir=tmp_path),
        scan_mode="report",
        price_loader=lambda ticker, report_date: prices.copy(),
    )

    assert seen_industry_pct == {"000001": 1.0}
    assert actions == []


def test_load_industry_day_pct_by_ticker_uses_local_snapshots_without_tushare(tmp_path, monkeypatch):
    """daily-action 的行业上下文必须从本地缓存读, 不应依赖 Tushare 行业映射."""
    import json
    from src.screening.offensive import daily_action as da
    from scripts import setup_research as sr

    snapshot_dir = tmp_path / "data" / "snapshots"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps([{"ticker": "000001", "industry_sw": "农林牧渔"}]),
        encoding="utf-8",
    )
    industry_dir = tmp_path / "data" / "industry_index_cache"
    industry_dir.mkdir(parents=True)
    (industry_dir / "_industry_codes.json").write_text(
        json.dumps({"801010.SI": "农林牧渔"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (industry_dir / "801010.SI.csv").write_text(
        "trade_date,pct_chg\n20260708,2.4\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sr,
        "build_ticker_to_industry",
        lambda _tickers: (_ for _ in ()).throw(AssertionError("network industry mapping should not be called")),
    )

    result = da._load_industry_day_pct_by_ticker("20260708", ["000001"])

    assert result == {"000001": 2.4}


def test_render_daily_action_shows_stale_data_guard(tmp_path):
    """stale guard 触发时, 输出应明确说明数据滞后且不出新 BUY."""
    from src.screening.offensive.daily_action import render_daily_action
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.last_action_stale_reason = "price_cache 最新交易日 20260706 落后于最新 --auto 报告 20260708"

    out = render_daily_action([], "20260706", tracker)

    assert "数据滞后" in out
    assert "不输出新 BUY" in out


def test_render_daily_action_labels_signal_and_execution_dates(tmp_path, monkeypatch):
    """BUY 段必须区分信号日和计划买入日, 避免把次日开盘单写成今日买入."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.daily_action import DailyAction
    from src.screening.offensive.paper_tracker import PaperTracker

    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260709", raising=False)
    # 避免 get_stock_name 触发网络/tushare 调用 (测试不应依赖外部 API)
    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda t: f"测试股{t[-2:]}")
    tracker = PaperTracker(journal_dir=tmp_path)
    actions = [
        DailyAction(
            ticker="603881",
            setup="btst_breakout",
            action="BUY",
            kelly_pct=0.10,
            entry_price=24.21,
            soft_stop=20.70,
            hard_stop=22.27,
            time_exit="T+10",
            invalidation_condition="价格跌破 22.27 (-8% 止损线)",
            distribution_summary="n=1762 winrate=54% cv=1.81 E=+3.4%",
            reasoning="test",
        )
    ]

    out = da.render_daily_action(actions, "20260708", tracker)

    assert "信号日: 20260708" in out
    assert "计划买入日: 20260709" in out
    assert "计划 BUY" in out
    assert "今日 BUY" not in out
    assert "参考价(信号日收盘)" in out


def test_render_daily_action_explains_stops_prior_and_rule_execution(tmp_path, monkeypatch):
    """渲染层应直接解释术语, operator 不需要回代码理解 soft/hard/cv/E."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.daily_action import DailyAction
    from src.screening.offensive.paper_tracker import PaperTracker

    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260709", raising=False)
    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda t: f"测试股{t[-2:]}")
    tracker = PaperTracker(journal_dir=tmp_path)
    actions = [
        DailyAction(
            ticker="603778",
            setup="oversold_bounce",
            action="BUY",
            kelly_pct=0.10,
            entry_price=10.92,
            soft_stop=10.01,
            hard_stop=10.05,
            time_exit="T+5",
            invalidation_condition="价格跌破 9.59 (30 日低点 -5%)",
            distribution_summary="n=1113 winrate=59% cv=2.51 E=+3.4%",
            reasoning="test",
        )
    ]

    out = da.render_daily_action(actions, "20260708", tracker, explain=True)

    assert "软止损=历史平均亏损x1.5的观察线" in out
    assert "硬止损=固定-8%的风控参考线" in out
    assert "止损触发只做披露" in out
    assert "n=历史样本数" in out
    assert "winrate=历史胜率" in out
    assert "cv=凸性比" in out
    assert "E=历史平均收益" in out
    assert "执行规则 (按规则执行)" in out
    assert "不临盘主观加仓/扛单" in out
    assert "移除情绪" not in out


def test_render_daily_action_does_not_claim_stop_loss_changes_paper_pnl(tmp_path, monkeypatch):
    """Stop-loss wording must match paper_tracker: disclosure only, P&L exits at T+N."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.daily_action import DailyAction
    from src.screening.offensive.paper_tracker import PaperTracker

    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260709", raising=False)
    monkeypatch.setattr(da, "_setup_policy_lines", lambda **kw: [], raising=False)
    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda t: f"测试股{t[-2:]}")
    tracker = PaperTracker(journal_dir=tmp_path)
    actions = [
        DailyAction(
            ticker="603778",
            setup="btst_breakout",
            action="BUY",
            kelly_pct=0.10,
            entry_price=10.92,
            soft_stop=10.01,
            hard_stop=10.05,
            time_exit="T+10",
            invalidation_condition="价格跌破 10.05 (-8% 止损线)",
            distribution_summary="n=1762 winrate=54% cv=1.81 E=+3.4%",
            reasoning="test",
        )
    ]

    out = da.render_daily_action(actions, "20260708", tracker, explain=True)

    assert "止损触发只做披露" in out
    assert "paper P&L 按 T+N 收盘回填" in out
    assert "实际风控线" not in out
    assert "触硬止损或失效条件 → 当日收盘平" not in out


def test_render_daily_action_hides_terminology_without_verbose(tmp_path, monkeypatch):
    """默认输出不含术语说明/执行规则 (跑了一周以上已熟记); --verbose (explain=True) 才展开."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.daily_action import DailyAction
    from src.screening.offensive.paper_tracker import PaperTracker

    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260709", raising=False)
    monkeypatch.setattr(da, "_setup_policy_lines", lambda **kw: [], raising=False)
    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda t: f"测试股{t[-2:]}")
    tracker = PaperTracker(journal_dir=tmp_path)
    actions = [
        DailyAction(
            ticker="603778",
            setup="btst_breakout",
            action="BUY",
            kelly_pct=0.10,
            entry_price=10.92,
            soft_stop=10.01,
            hard_stop=10.05,
            time_exit="T+10",
            invalidation_condition="价格跌破 10.05 (-8% 止损线)",
            distribution_summary="n=1762 winrate=54% cv=1.81 E=+3.4%",
            reasoning="test",
        )
    ]

    # 默认: 术语说明 + 执行规则隐藏 (精简输出)
    out = da.render_daily_action(actions, "20260708", tracker)
    assert "术语说明" not in out
    assert "执行规则" not in out
    # BUY 计划仍在 (核心决策信息不丢)
    assert "计划 BUY" in out
    # journal 闭环确认仍在
    assert "已写入 paper journal" in out

    # --verbose: 展开
    out_verbose = da.render_daily_action(actions, "20260708", tracker, explain=True)
    assert "术语说明" in out_verbose
    assert "执行规则" in out_verbose


def test_render_daily_action_discloses_setup_policy_from_backtest(tmp_path, monkeypatch):
    """daily-action must show which setup is active/paused and why."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    from src.screening.offensive.setup_performance import SetupPerformance, SetupPerformanceReport

    monkeypatch.delenv("DAILY_ACTION_DISABLED_SETUPS", raising=False)
    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260709", raising=False)
    monkeypatch.setattr(
        da,
        "_load_backtest_setup_performance",
        lambda: SetupPerformanceReport(
            total_exits=192,
            by_setup={
                "btst_breakout": SetupPerformance(
                    n=133,
                    winrate=0.68,
                    expected_return=0.0815,
                    avg_gain=0.0,
                    avg_loss=0.0,
                    by_regime={},
                ),
                "oversold_bounce": SetupPerformance(
                    n=59,
                    winrate=0.53,
                    expected_return=0.0034,
                    avg_gain=0.0,
                    avg_loss=0.0,
                    by_regime={
                        "crisis": SetupPerformance(
                            n=21,
                            winrate=0.48,
                            expected_return=-0.0115,
                            avg_gain=0.0,
                            avg_loss=0.0,
                            by_regime={},
                        )
                    },
                ),
            },
        ),
        raising=False,
    )

    out = da.render_daily_action([], "20260708", PaperTracker(journal_dir=tmp_path), explain=True)

    assert "启用 setup: 涨停突破(btst_breakout)" in out
    assert "n=133" in out
    assert "E=+8.15%" in out
    assert "暂停 setup: 超跌反弹(oversold_bounce)" in out
    # 暂停理由应反映统计不显著 (不是 crisis 分层; crisis n=21 太小不可靠)
    assert "CI 跨 0 不显著" in out
    assert "尾部亏损比 BTST 厚" in out
    assert "crisis E=-1.15%" not in out  # 不再把小样本 crisis 分层当主因展示


def test_render_daily_action_setup_policy_respects_env_none(tmp_path, monkeypatch):
    """DAILY_ACTION_DISABLED_SETUPS=none should remove the paused setup disclosure."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    monkeypatch.setenv("DAILY_ACTION_DISABLED_SETUPS", "none")
    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260709", raising=False)
    monkeypatch.setattr(da, "_load_backtest_setup_performance", lambda: None, raising=False)

    out = da.render_daily_action([], "20260708", PaperTracker(journal_dir=tmp_path))

    assert "启用 setup: 涨停突破(btst_breakout), 超跌反弹(oversold_bounce)" in out
    assert "暂停 setup:" not in out


# ---------------------------------------------------------------------------
# render_daily_action — 平仓披露 + 移除死承诺
# ---------------------------------------------------------------------------


def test_render_shows_closed_positions(tmp_path, monkeypatch):
    """render_daily_action 有平仓时, 必须显示平仓摘要 (ticker/realized_pnl/止损触发).

    诚实披露: 平仓是组合状态演进的核心, operator 必须能看到今日平了哪些仓、各仓
    realized P&L、以及期间是否触发了硬止损 (披露但未混入主 P&L).
    """
    from src.screening.offensive.daily_action import render_daily_action

    # 避免 get_stock_name 触发网络/tushare 调用 (平仓摘要也要显示名字)
    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda t: f"测试股{t[-2:]}")
    tracker = PaperTracker(journal_dir=tmp_path)
    closed = [
        {
            "ticker": "300502",
            "buy_date": "20260601",
            "realized_pnl": 0.05,
            "exit_price": 105.0,
            "stop_would_have_triggered": False,
        },
        {
            "ticker": "688629",
            "buy_date": "20260601",
            "realized_pnl": -0.08,
            "exit_price": 184.0,
            "stop_would_have_triggered": True,
        },
    ]
    out = render_daily_action([], "20260620", tracker, closed_positions=closed)
    # 平仓摘要必须可见
    assert "300502" in out and "688629" in out
    assert "+5.0%" in out or "+5%" in out, f"realized +5% 未披露: {out!r}"
    assert "-8.0%" in out or "-8%" in out, f"realized -8% 未披露: {out!r}"
    # 触发止损的票要披露
    assert "止损" in out or "stop" in out.lower(), f"止损触发未披露: {out!r}"


def test_render_no_closed_positions_omits_section(tmp_path):
    """无平仓时不显示平仓段 (避免噪声)."""
    from src.screening.offensive.daily_action import render_daily_action

    tracker = PaperTracker(journal_dir=tmp_path)
    out = render_daily_action([], "20260620", tracker)
    assert "平仓" not in out


def test_render_removes_dead_paper_pnl_promise(tmp_path):
    """渲染不再承诺不存在的 --paper-pnl 命令 (该命令从未实现, 是死承诺).

    诚实性: 渲染层曾写 '30 天后用 --paper-pnl 复盘', 但该命令不存在于 dispatcher.
    闭环已自动平仓, 应改为诚实表述.
    """
    from src.screening.offensive.daily_action import render_daily_action

    tracker = PaperTracker(journal_dir=tmp_path)
    out = render_daily_action([], "20260620", tracker)
    assert "--paper-pnl" not in out, f"死承诺 --paper-pnl 仍在渲染: {out!r}"


# ---------------------------------------------------------------------------
# full_market 扫描模式 + 多 setup (v2: 全市场直扫, 不依赖 --auto 候选池)
# ---------------------------------------------------------------------------


def test_full_market_scan_does_not_require_report():
    """full_market 模式不读 --auto 报告, 直接扫 price_cache 全市场.

    第一性原理: --auto 的 score_b 候选池选"好股票", 凸性 setup 要"极端股票"
    (涨停/超跌), 两者交集≈0. full_market 绕过候选池, 直扫全市场.
    """
    from src.screening.offensive.daily_action import generate_daily_action
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker()
    # full_market 模式: 不传 report_path, 不应有异常
    actions = generate_daily_action(tracker=tracker, scan_mode="full_market")
    # 能跑完就说明不依赖报告 (trade_date 从 price_cache 推断)
    assert isinstance(actions, list)


def test_oversold_bounce_distribution_registered():
    """OVERSOLD_BOUNCE_T5 已注册到 KNOWN_DISTRIBUTIONS (2026-07-11 真实回测校准版)."""
    from src.screening.offensive.known_distributions import get_known_distribution

    dist = get_known_distribution("oversold_bounce", 5)
    assert dist is not None
    assert dist.n >= 50  # 真实回测样本 (59 笔, 非旧全池 1113)
    # 校准后 convexity <1.5 (avg_loss 2x 低估修正), CI 跨 0 → 无可证明 alpha
    assert dist.convexity_ratio < 1.5
    assert dist.winrate > 0.45


def test_verified_setups_includes_both_btst_and_oversold():
    """_VERIFIED_SETUPS 应含 BTST + OversoldBounce 两个 setup."""
    from src.screening.offensive.daily_action import _VERIFIED_SETUPS

    names = [cfg[0] for cfg in _VERIFIED_SETUPS]
    assert "btst_breakout" in names
    assert "oversold_bounce" in names


# ---- regime 智能加仓 (countercyclical sizing, 按 setup 区分) ----


def _run_daily_action_under_regime(tmp_path, monkeypatch, regime_gate_level: str, setup_name: str = "btst_breakout"):
    """在指定 regime 下跑一次 generate_daily_action, 返回 (actions, tracker).

    用 report 模式 + FakeSetup 确保命中一只票, 隔离 regime 对 Kelly 仓位的纯效应。
    setup_name 控制 _VERIFIED_SETUPS 注册名 (决定按 setup 的 regime_factor).
    默认用 btst_breakout (2026 实测 crisis 加仓有数据支持的 setup).
    """
    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    class FakeSetup:
        def detect(self, ticker, trade_date, context):
            return DetectionResult(
                hit=True,
                ticker=ticker,
                trade_date=trade_date,
                trigger_strength=1.0,
                invalidation_condition="fake",
            )

    # Distribution 让原始 Kelly 较大 (>1.0), 从而触顶 _MAX_POSITION_PCT=0.10,
    # 这样 regime_factor 的 1.2× 放大才能体现 (0.10 → 0.12).
    dist = Distribution(
        n=100,
        winrate=0.60,
        avg_gain=0.12,
        avg_loss=-0.06,
        convexity_ratio=2.0,
        expected_return=0.05,
        ci_low=0.02,
        ci_high=0.08,
        ic=0.10,
    )
    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [(setup_name, FakeSetup, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    # 清空禁用列表, 让指定 setup 能跑 (测试隔离)
    monkeypatch.setattr(da, "_env_setup_disable_list", lambda: set())

    report_path = tmp_path / "auto_screening_20260708.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "20260708",
                "recommendations": [{"ticker": "000001"}],
                "market_state": {"regime_gate_level": regime_gate_level},
            }
        ),
        encoding="utf-8",
    )
    prices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-07-08"),
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0,
                # BTST 预过滤要求 pct>=9.5 (涨停日); 用 setup 名决定 pct 避免 setup 名触发预过滤
                "pct_change": 9.5 if setup_name == "btst_breakout" else 0.0,
            }
        ]
    )
    # 每次调用用独立 journal 子目录, 避免同测试内多次调用时去重逻辑 (C-HELD-DEDUP)
    # 把上一次买入的 ticker 当作"已持仓"跳过 (regime 对比测试需两次独立买入同一票).
    tracker = PaperTracker(journal_dir=tmp_path / f"journal_{regime_gate_level}")
    actions = da.generate_daily_action(
        report_path=report_path,
        tracker=tracker,
        scan_mode="report",
        price_loader=lambda ticker, report_date: prices.copy(),
    )
    return actions, tracker


def test_regime_size_factor_btst_crisis_increases_position(tmp_path, monkeypatch):
    """BTST + crisis regime 下仓位应放大 (2026 回测 E[r]=+16.93% 支持加仓).

    注意: 2026-07-18 起 regime 加仓受 _REGIME_SIZING_EVIDENCE_BOUND 门控 —
    证据未绑定时不实际加仓. 本测试显式绑定以验证加仓机制本身."""
    from src.screening.offensive import daily_action as daily_action_module

    monkeypatch.setattr(daily_action_module, "_REGIME_SIZING_EVIDENCE_BOUND", True)
    monkeypatch.delenv("DAILY_ACTION_REGIME_SIZING", raising=False)
    actions_crisis, _ = _run_daily_action_under_regime(tmp_path, monkeypatch, "crisis", "btst_breakout")
    assert len(actions_crisis) == 1
    crisis_pct = actions_crisis[0].kelly_pct

    actions_normal, _ = _run_daily_action_under_regime(tmp_path, monkeypatch, "normal", "btst_breakout")
    assert len(actions_normal) == 1
    normal_pct = actions_normal[0].kelly_pct

    # BTST crisis 应放大 1.2×: normal=0.10 (per-setup cap), crisis=0.12 (regime cap)
    assert crisis_pct > normal_pct, f"crisis {crisis_pct} should exceed normal {normal_pct}"
    assert abs(crisis_pct - 0.12) < 1e-6, f"crisis expected 0.12, got {crisis_pct}"
    assert abs(normal_pct - 0.10) < 1e-6, f"normal expected 0.10, got {normal_pct}"


def test_regime_uplift_disabled_before_evidence_binding(tmp_path, monkeypatch):
    """证据未绑定前 (默认): crisis 与 normal 仓位一致, 不实际加仓."""
    monkeypatch.delenv("DAILY_ACTION_REGIME_SIZING", raising=False)
    actions_crisis, _ = _run_daily_action_under_regime(tmp_path, monkeypatch, "crisis", "btst_breakout")
    actions_normal, _ = _run_daily_action_under_regime(tmp_path, monkeypatch, "normal", "btst_breakout")
    assert len(actions_crisis) == 1 and len(actions_normal) == 1
    assert actions_crisis[0].kelly_pct == actions_normal[0].kelly_pct


def test_regime_size_factor_oversold_crisis_no_increase():
    """OversoldBounce + crisis 不加仓 (2026 实测 crisis E[r]=-1.15% 亏钱).

    单元测试 _regime_size_factor: OversoldBounce 在所有 regime 都返回 1.0.
    (端到端测试需 31 行跌幅数据满足 OversoldBounce 预过滤, 此处用单元测试隔离 regime 逻辑.)
    """
    from src.screening.offensive.daily_action import _regime_size_factor

    assert _regime_size_factor("crisis", "oversold_bounce") == 1.0
    assert _regime_size_factor("risk_off", "oversold_bounce") == 1.0
    assert _regime_size_factor("normal", "oversold_bounce") == 1.0


def test_regime_size_factor_normal_no_change(tmp_path, monkeypatch):
    """normal regime 下仓位不放大, 等于 BTST per-setup cap (0.10)."""
    monkeypatch.delenv("DAILY_ACTION_REGIME_SIZING", raising=False)
    actions, _ = _run_daily_action_under_regime(tmp_path, monkeypatch, "normal", "btst_breakout")
    assert len(actions) == 1
    assert abs(actions[0].kelly_pct - 0.10) < 1e-6  # BTST per-setup cap, no regime boost


def test_regime_sizing_disabled_via_env(tmp_path, monkeypatch):
    """DAILY_ACTION_REGIME_SIZING=false 时, BTST crisis regime 也不放大仓位."""
    monkeypatch.setenv("DAILY_ACTION_REGIME_SIZING", "false")
    actions, _ = _run_daily_action_under_regime(tmp_path, monkeypatch, "crisis", "btst_breakout")
    assert len(actions) == 1
    # env 关闭 → regime_factor=1.0 → 仓位退回 BTST per-setup cap (0.10), 不放大到 0.12
    assert abs(actions[0].kelly_pct - 0.10) < 1e-6, f"expected 0.10, got {actions[0].kelly_pct}"


def test_regime_factor_capped_at_hard_limit(tmp_path, monkeypatch):
    """regime 放大不超 BTST per-setup cap × 1.2 硬上限, 即使 factor 更大."""
    from src.screening.offensive import daily_action as daily_action_module

    monkeypatch.setattr(daily_action_module, "_REGIME_SIZING_EVIDENCE_BOUND", True)
    monkeypatch.delenv("DAILY_ACTION_REGIME_SIZING", raising=False)
    # BTST crisis factor=1.2 → 0.10×1.2=0.12, 正好等于硬上限, 不应突破
    actions, _ = _run_daily_action_under_regime(tmp_path, monkeypatch, "crisis", "btst_breakout")
    assert len(actions) == 1
    from src.screening.offensive.daily_action import _MAX_POSITION_PCT_BY_SETUP, _REGIME_POSITION_CAP_MULTIPLE

    btst_cap = _MAX_POSITION_PCT_BY_SETUP.get("btst_breakout", _MAX_POSITION_PCT_BY_SETUP.get("btst_breakout", 0.10))
    hard_cap = btst_cap * _REGIME_POSITION_CAP_MULTIPLE
    assert actions[0].kelly_pct <= hard_cap + 1e-9
    assert abs(actions[0].kelly_pct - hard_cap) < 1e-6


def test_regime_size_factor_per_setup_and_unknown_defaults():
    """按 setup 区分的 regime factor + 未知 setup/regime 默认 1.0."""
    from src.screening.offensive.daily_action import _regime_size_factor

    # BTST: crisis/risk_off 加仓
    assert _regime_size_factor("crisis", "btst_breakout") == 1.2
    assert _regime_size_factor("risk_off", "btst_breakout") == 1.1
    assert _regime_size_factor("normal", "btst_breakout") == 1.0
    # OversoldBounce: 全部 1.0 (实测无效)
    assert _regime_size_factor("crisis", "oversold_bounce") == 1.0
    assert _regime_size_factor("normal", "oversold_bounce") == 1.0
    # 未知 setup → 1.0 (保守)
    assert _regime_size_factor("crisis", "unknown_setup") == 1.0
    assert _regime_size_factor("crisis", "") == 1.0
    # 未知 regime → 1.0
    assert _regime_size_factor("unknown", "btst_breakout") == 1.0


def test_regime_sizing_recorded_in_buy_reasoning(tmp_path, monkeypatch):
    """BUY reasoning 应标注 regime×factor, 供后续 edge 衰减监测追溯."""
    monkeypatch.delenv("DAILY_ACTION_REGIME_SIZING", raising=False)
    actions, tracker = _run_daily_action_under_regime(tmp_path, monkeypatch, "crisis", "btst_breakout")
    assert len(actions) == 1
    assert "regime=crisis×1.2" in actions[0].reasoning


# ---- OversoldBounce 暂停 (DAILY_ACTION_DISABLED_SETUPS) ----


def test_oversold_bounce_disabled_by_default(monkeypatch):
    """默认配置下 OversoldBounce 在禁用列表中 (2026 实测 E[r]≈0)."""
    monkeypatch.delenv("DAILY_ACTION_DISABLED_SETUPS", raising=False)
    from src.screening.offensive.daily_action import _env_setup_disable_list, _DEFAULT_DISABLED_SETUPS

    disabled = _env_setup_disable_list()
    assert "oversold_bounce" in disabled
    assert "oversold_bounce" in _DEFAULT_DISABLED_SETUPS


def test_oversold_bounce_reenabled_via_env_none(monkeypatch):
    """DAILY_ACTION_DISABLED_SETUPS=none 清空默认, 恢复全部 setup."""
    monkeypatch.setenv("DAILY_ACTION_DISABLED_SETUPS", "none")
    from src.screening.offensive.daily_action import _env_setup_disable_list

    assert _env_setup_disable_list() == set()


def test_disabled_setup_appended_via_env(monkeypatch):
    """DAILY_ACTION_DISABLED_SETUPS=btst_breakout 追加禁用 BTST (保留默认)."""
    monkeypatch.setenv("DAILY_ACTION_DISABLED_SETUPS", "btst_breakout")
    from src.screening.offensive.daily_action import _env_setup_disable_list

    disabled = _env_setup_disable_list()
    assert "btst_breakout" in disabled
    assert "oversold_bounce" in disabled  # 默认仍保留


# ---- paper_tracker 幂等自愈 ----


def test_open_positions_self_heals_from_duplicated_buys(tmp_path):
    """历史 journal 含重复 BUY 时, open_positions 应从去重真值自愈."""
    journal = tmp_path / "journal.jsonl"
    # 模拟真实污染: 688629 重复 4 次 + 1 unique open + 1 closed (EXIT.date = buy_date 约定)
    import json as _json

    records = [
        {"date": "20260706", "ticker": "688629", "action": "BUY", "setup": "btst_breakout", "horizon": 10, "kelly_pct": 0.1, "entry_price": 50.0, "soft_stop": 45.0, "hard_stop": 46.0, "time_exit": "T+10", "invalidation_condition": "", "reasoning": "dupe1"},
        {"date": "20260706", "ticker": "688629", "action": "BUY", "setup": "btst_breakout", "horizon": 10, "kelly_pct": 0.1, "entry_price": 50.0, "soft_stop": 45.0, "hard_stop": 46.0, "time_exit": "T+10", "invalidation_condition": "", "reasoning": "dupe2"},
        {"date": "20260706", "ticker": "688629", "action": "BUY", "setup": "btst_breakout", "horizon": 10, "kelly_pct": 0.1, "entry_price": 50.0, "soft_stop": 45.0, "hard_stop": 46.0, "time_exit": "T+10", "invalidation_condition": "", "reasoning": "dupe3"},
        {"date": "20260706", "ticker": "688629", "action": "BUY", "setup": "btst_breakout", "horizon": 10, "kelly_pct": 0.1, "entry_price": 50.0, "soft_stop": 45.0, "hard_stop": 46.0, "time_exit": "T+10", "invalidation_condition": "", "reasoning": "dupe4"},
        {"date": "20260706", "ticker": "000559", "action": "BUY", "setup": "btst_breakout", "horizon": 10, "kelly_pct": 0.1, "entry_price": 10.0, "soft_stop": 9.0, "hard_stop": 9.2, "time_exit": "T+10", "invalidation_condition": "", "reasoning": "unique"},
        {"date": "20260706", "ticker": "002217", "action": "BUY", "setup": "oversold_bounce", "horizon": 5, "kelly_pct": 0.1, "entry_price": 3.0, "soft_stop": 2.7, "hard_stop": 2.76, "time_exit": "T+5", "invalidation_condition": "", "reasoning": "open"},
    ]
    journal.write_text("\n".join(_json.dumps(r) for r in records) + "\n", encoding="utf-8")

    tracker = PaperTracker(journal_dir=tmp_path)
    # 688629 去重=1 + 000559=1 + 002217=1 = 3 (无 EXIT)
    assert tracker.state.open_positions == 3, f"expected 3, got {tracker.state.open_positions}"


def test_open_positions_self_heal_subtracts_exits(tmp_path):
    """有 EXIT 的仓位不计入 open_positions (EXIT.date = buy_date 约定)."""
    import json as _json

    journal = tmp_path / "journal.jsonl"
    records = [
        {"date": "20260706", "ticker": "000001", "action": "BUY"},
        {"date": "20260706", "ticker": "000002", "action": "BUY"},
        {"date": "20260706", "ticker": "000002", "action": "EXIT"},  # closed (buy_date 约定)
    ]
    journal.write_text("\n".join(_json.dumps(r) for r in records) + "\n", encoding="utf-8")
    tracker = PaperTracker(journal_dir=tmp_path)
    # 000001 open + 000002 closed = 1
    assert tracker.state.open_positions == 1


def test_open_positions_self_heal_persists_correction(tmp_path):
    """自愈后的正确计数应持久化到 portfolio_state.json."""
    import json as _json

    journal = tmp_path / "journal.jsonl"
    state = tmp_path / "portfolio_state.json"
    # 预置一个污染的 state (open_positions=99)
    state.write_text(
        _json.dumps(
            {
                "nav": 1.0,
                "peak": 1.0,
                "drawdown_pct": 0.0,
                "open_positions": 99,
                "total_trades": 0,
                "realized_pnl_pct": 0.0,
                "last_30d_pnl": [],
            }
        )
    )
    # journal 只有 1 条 BUY (真实持仓=1)
    journal.write_text(_json.dumps({"date": "20260706", "ticker": "000001", "action": "BUY"}) + "\n")

    tracker = PaperTracker(journal_dir=tmp_path)
    assert tracker.state.open_positions == 1  # 自愈 99 → 1
    persisted = _json.loads(state.read_text())
    assert persisted["open_positions"] == 1  # 已持久化


def test_record_buy_idempotent_across_instances(tmp_path):
    """两个 PaperTracker 实例 (模拟两次进程) 对同一 (date, ticker) 不重复记录."""
    tracker1 = PaperTracker(journal_dir=tmp_path)
    tracker1.record_buy("20260706", "688629", "btst_breakout", 10, 50.0, 0.1, 45.0, 46.0, "test")
    # 第二个实例读同一 journal (跨进程场景)
    tracker2 = PaperTracker(journal_dir=tmp_path)
    tracker2.record_buy("20260706", "688629", "btst_breakout", 10, 50.0, 0.1, 45.0, 46.0, "dup")
    import json as _json

    lines = [line for line in (tmp_path / "journal.jsonl").read_text().strip().split("\n") if line.strip()]
    buys = [_json.loads(line) for line in lines if '"BUY"' in line]
    assert len(buys) == 1, f"expected 1 BUY, got {len(buys)}"


# ---- NS-17 silent-except regression guards (autodev-32) ----


def test_load_st_tickers_does_not_import_tushare_without_token(monkeypatch):
    from src.screening.offensive.daily_action import _load_st_tickers
    from src.tools import tushare_api

    monkeypatch.setattr(tushare_api, "get_tushare_token", lambda: "")

    class ForbiddenTushare:
        def __getattr__(self, name):
            raise AssertionError(f"Tushare must not be used without credentials: {name}")

    monkeypatch.setitem(__import__("sys").modules, "tushare", ForbiddenTushare())
    assert _load_st_tickers() == set()


def test_compact_trade_date_invalid_logs_warning(caplog):
    """_compact_trade_date with unparseable input logs warning (not silent)."""
    from src.screening.offensive.daily_action import _compact_trade_date
    result = _compact_trade_date("not-a-date")
    assert result == ""
    assert any("_compact_trade_date failed" in record.message for record in caplog.records)


def test_compact_trade_date_absent_value_is_quiet(caplog):
    """Absent auto-report dates are expected and must not emit warning tracebacks."""
    from src.screening.offensive.daily_action import _compact_trade_date

    caplog.set_level("WARNING")
    for value in (None, "", "   "):
        assert _compact_trade_date(value) == ""
    assert not caplog.records


def test_compact_trade_date_edge_cases():
    """_compact_trade_date handles valid inputs correctly."""
    from src.screening.offensive.daily_action import _compact_trade_date

    # Already compact
    assert _compact_trade_date("20260709") == "20260709"
    # Timestamp string
    assert _compact_trade_date("2026-07-09") == "20260709"
    # Datetime-like
    assert _compact_trade_date("2026/07/09") == "20260709"
    # Empty
    assert _compact_trade_date("") == ""
    # Invalid
    assert _compact_trade_date("not-a-date") == ""


def test_latest_fund_flow_date_corrupted_csv_logs_warning(caplog, tmp_path):
    """_latest_fund_flow_date logs warning on corrupted CSV (not silent)."""
    from src.screening.offensive.cache_refresh import _latest_fund_flow_date
    import logging

    # Create a corrupted CSV
    cache_dir = tmp_path / "fund_flow"
    cache_dir.mkdir()
    csv_path = cache_dir / "000001.csv"
    csv_path.write_text("broken,csv,content\nno,proper,columns", encoding="utf-8")

    caplog.set_level(logging.WARNING)
    result = _latest_fund_flow_date(cache_dir, "000001")
    assert result is None  # graceful degradation
    assert any("cache_refresh" in r.name and "failed to read fund flow cache" in r.message for r in caplog.records), f"Expected warning log, got: {[r.message for r in caplog.records]}"


def test_latest_fund_flow_date_missing_file_returns_none(tmp_path):
    """Missing fund flow CSV returns None silently (no exception)."""
    from src.screening.offensive.cache_refresh import _latest_fund_flow_date

    cache_dir = tmp_path / "fund_flow"
    cache_dir.mkdir()
    result = _latest_fund_flow_date(cache_dir, "999999")
    assert result is None


def test_latest_fund_flow_date_valid_csv_returns_date(tmp_path):
    """Healthy fund flow CSV returns max date."""
    from src.screening.offensive.cache_refresh import _latest_fund_flow_date

    cache_dir = tmp_path / "fund_flow"
    cache_dir.mkdir()
    csv_path = cache_dir / "000001.csv"
    csv_path.write_text("date\n20260707\n20260708\n20260709", encoding="utf-8")

    result = _latest_fund_flow_date(cache_dir, "000001")
    assert result == "20260709"


# ---------------------------------------------------------------------------
# C-PORTFOLIO-CAP-IGNORES-OPEN-POSITIONS (empirical dogfood 20260710)
# 真实 journal 峰值 26 仓 / 260% 敞口 (20260616), 61 天超 60% 上限.
# 根因: generate_daily_action 的 portfolio_position_used 每次 run 重置为 0,
# 忽略前序未平仓 (BTST T+10 持仓跨日) → "组合 ≤ 60%" 上限按 per-run 执行而非
# per-portfolio → 超杠杆, paper nav (+110%) 不可达成, 风控形同虚设.
# ---------------------------------------------------------------------------


def test_record_buy_tracks_open_exposure(tmp_path):
    """record_buy 必须累加 open_exposure (单仓 kelly_pct 之和), 供组合上限判断.

    此前只数 open_positions (计数), 不追踪 open_exposure (敞口%) → 上限判断缺
    "已用多少额度" 的输入. record_buy 累加, 幂等跳过的不加.
    """
    t = PaperTracker(journal_dir=tmp_path)
    assert t.state.open_exposure == 0.0
    t.record_buy("20260707", "300502", "btst_breakout", 10, 50.0, 0.05, 46.0, 45.0, "跌破45")
    assert abs(t.state.open_exposure - 0.05) < 1e-9
    t.record_buy("20260707", "688629", "btst_breakout", 10, 200.0, 0.10, 180.0, 184.0, "跌破184")
    assert abs(t.state.open_exposure - 0.15) < 1e-9
    # 幂等重复 BUY 不再加 open_exposure
    t.record_buy("20260707", "300502", "btst_breakout", 10, 50.0, 0.05, 46.0, 45.0, "跌破45")
    assert abs(t.state.open_exposure - 0.15) < 1e-9


def test_open_exposure_self_heals_from_journal(tmp_path):
    """新实例从 journal 重建 open_exposure (与 open_positions 同口径自愈).

    历史 journal 可能含重复 BUY / 旧版无 open_exposure 字段. 重算口径:
    open_exposure = sum(去重 BUY.kelly_pct) - 0 (EXIT 不减, 因 EXIT 时 close_matured
    已减; 重建只数当前未平仓). 这里测纯 BUY 重建.
    """
    t1 = PaperTracker(journal_dir=tmp_path)
    t1.record_buy("20260707", "300502", "btst_breakout", 10, 50.0, 0.10, 46.0, 45.0, "跌破45")
    t1.record_buy("20260707", "688629", "btst_breakout", 10, 200.0, 0.10, 180.0, 184.0, "跌破184")

    t2 = PaperTracker(journal_dir=tmp_path)
    assert abs(t2.state.open_exposure - 0.20) < 1e-9, f"open_exposure 未从 journal 自愈: got {t2.state.open_exposure}"


def test_close_matured_decrements_open_exposure(tmp_path):
    """close_matured 平仓时 open_exposure 扣减已平仓位的 kelly_pct 之和."""
    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260601", "300502", "btst_breakout", 10, 100.0, 0.10, 85.0, 92.0, "跌破92")
    tracker.record_buy("20260601", "688629", "btst_breakout", 10, 200.0, 0.10, 180.0, 184.0, "跌破184")
    assert abs(tracker.state.open_exposure - 0.20) < 1e-9

    fetcher_map = {
        "300502": _make_price_series("20260601", 100.0, 105.0),
        "688629": _make_price_series("20260601", 200.0, 210.0),
    }
    fetcher = lambda ticker, start, end: fetcher_map.get(ticker, [])  # noqa: E731
    closed = tracker.close_matured(as_of="20260620", use_data_fetcher=fetcher)
    assert len(closed) == 2
    assert tracker.state.open_positions == 0
    assert abs(tracker.state.open_exposure - 0.0) < 1e-9, f"平仓后 open_exposure 应归零: got {tracker.state.open_exposure}"


def test_portfolio_cap_accounts_for_open_positions(tmp_path, monkeypatch):
    """组合 60% 上限必须计入已开仓位, 不能每次 run 重置为 0.

    Bug: generate_daily_action 的 portfolio_position_used 每次 reset 为 0, 忽略
    前序未平仓. BTST T+10 持仓跨日 → 实际敞口常超 60% (真实 journal 峰值 260%).
    预置 50% 已开仓 + 5 只新信号 → 应只追加 1 只 (10%) 到 60%, 不能 5 只全开 (会到 100%).
    """
    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    class FakeSetup:
        def detect(self, ticker, trade_date, context):
            return DetectionResult(
                hit=True,
                ticker=ticker,
                trade_date=trade_date,
                trigger_strength=1.0,
                invalidation_condition="fake",
            )

    dist = Distribution(
        n=100,
        winrate=0.60,
        avg_gain=0.12,
        avg_loss=-0.06,
        convexity_ratio=2.0,
        expected_return=0.05,
        ci_low=0.02,
        ci_high=0.08,
        ic=0.10,
    )
    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [("btst_breakout", FakeSetup, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    monkeypatch.setattr(da, "_env_setup_disable_list", lambda: set())
    monkeypatch.delenv("DAILY_ACTION_ENFORCE_OPEN_CAP", raising=False)

    tracker = PaperTracker(journal_dir=tmp_path)
    # 预置 5 个已开仓 (前一日买入, T+10 未到期) = 50% 敞口
    for tkr in ["100001", "100002", "100003", "100004", "100005"]:
        tracker.record_buy("20260707", tkr, "btst_breakout", 10, 10.0, 0.10, 9.0, 9.2, "fake")
    assert tracker.state.open_positions == 5
    assert abs(tracker.state.open_exposure - 0.50) < 1e-9

    # 今日 (20260708) 报告含 5 只新票, 全部 BTST 命中
    report_path = tmp_path / "auto_screening_20260708.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "20260708",
                "recommendations": [{"ticker": t} for t in ["200001", "200002", "200003", "200004", "200005"]],
                "market_state": {"regime_gate_level": "normal"},
            }
        ),
        encoding="utf-8",
    )
    prices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-07-08"),
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0,
                "pct_change": 9.5,
            }
        ]
    )
    actions = da.generate_daily_action(
        report_path=report_path,
        tracker=tracker,
        scan_mode="report",
        price_loader=lambda ticker, report_date: prices.copy(),
    )

    new_exposure = sum(a.kelly_pct for a in actions)
    total_exposure = 0.50 + new_exposure
    assert total_exposure <= 0.60 + 1e-9, f"组合敞口超 60% 上限: 已开 50% + 新 {new_exposure:.0%} = {total_exposure:.0%} " f"(应只追加 ≤10%, 实际追加 {len(actions)} 只)"
    # 50% 已开 → 只能再追加 1 只 (10%) 到 60%; 不能 5 只全开
    assert len(actions) == 1, f"应只追加 1 只新仓到 60%, 实际 {len(actions)} 只 ({new_exposure:.0%})"


def test_portfolio_cap_escape_hatch_restores_old_behavior(tmp_path, monkeypatch):
    """DAILY_ACTION_ENFORCE_OPEN_CAP=false 时恢复旧 per-run 行为 (逃生口).

    默认 true (修复生效). owner 若要对比旧行为可设 false → portfolio_position_used
    从 0 起算 (忽略已开仓), 与历史行为一致. 仅作逃生口, 不改变默认.
    """
    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    class FakeSetup:
        def detect(self, ticker, trade_date, context):
            return DetectionResult(
                hit=True,
                ticker=ticker,
                trade_date=trade_date,
                trigger_strength=1.0,
                invalidation_condition="fake",
            )

    dist = Distribution(
        n=100,
        winrate=0.60,
        avg_gain=0.12,
        avg_loss=-0.06,
        convexity_ratio=2.0,
        expected_return=0.05,
        ci_low=0.02,
        ci_high=0.08,
        ic=0.10,
    )
    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [("btst_breakout", FakeSetup, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    monkeypatch.setattr(da, "_env_setup_disable_list", lambda: set())
    # 行业集中度限制: 5 只票各分到不同行业, 避免被 2/行业 限制截断
    monkeypatch.setattr(
        da, "_load_ticker_to_industry_from_snapshots",
        lambda tickers, **kw: {t: f"industry_{i}" for i, t in enumerate(tickers)},
    )
    monkeypatch.setenv("DAILY_ACTION_ENFORCE_OPEN_CAP", "false")

    tracker = PaperTracker(journal_dir=tmp_path)
    for tkr in ["100001", "100002", "100003", "100004", "100005"]:
        tracker.record_buy("20260707", tkr, "btst_breakout", 10, 10.0, 0.10, 9.0, 9.2, "fake")

    report_path = tmp_path / "auto_screening_20260708.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "20260708",
                "recommendations": [{"ticker": t} for t in ["200001", "200002", "200003", "200004", "200005"]],
                "market_state": {"regime_gate_level": "normal"},
            }
        ),
        encoding="utf-8",
    )
    prices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-07-08"),
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0,
                "pct_change": 9.5,
            }
        ]
    )
    actions = da.generate_daily_action(
        report_path=report_path,
        tracker=tracker,
        scan_mode="report",
        price_loader=lambda ticker, report_date: prices.copy(),
    )
    # 旧行为: 忽略已开仓, 5只×10%=50%, 全部可录入.
    assert len(actions) == 5, f"逃生口=false: BTST 10%×5=50%, 实际 {len(actions)} 只"


def test_portfolio_cap_blocked_count_reports_all_skipped(tmp_path, monkeypatch):
    """len(blocked_candidates) 必须报告被跳过的全部信号数, 不只 1 个.

    Bug (autodev-34 /loop, 自查 C-PORTFOLIO-CAP 修复): 上限耗尽时
    旧实现 ``cap_blocked_count += 1; break`` 只计 1, 但其后所有剩余信号都被跳过.
    预置 50% 已开仓 + 10 只新信号 → 只追加 1 只, 跳过 9 只; disclose 应报 9 不报 1.
    """
    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    class FakeSetup:
        def detect(self, ticker, trade_date, context):
            return DetectionResult(
                hit=True,
                ticker=ticker,
                trade_date=trade_date,
                trigger_strength=1.0,
                invalidation_condition="fake",
            )

    dist = Distribution(
        n=100,
        winrate=0.60,
        avg_gain=0.12,
        avg_loss=-0.06,
        convexity_ratio=2.0,
        expected_return=0.05,
        ci_low=0.02,
        ci_high=0.08,
        ic=0.10,
    )
    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [("btst_breakout", FakeSetup, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    monkeypatch.setattr(da, "_env_setup_disable_list", lambda: set())
    monkeypatch.delenv("DAILY_ACTION_ENFORCE_OPEN_CAP", raising=False)

    tracker = PaperTracker(journal_dir=tmp_path)
    # 50% 已开仓
    for tkr in ["100001", "100002", "100003", "100004", "100005"]:
        tracker.record_buy("20260707", tkr, "btst_breakout", 10, 10.0, 0.10, 9.0, 9.2, "fake")

    # 10 只新信号: 50% 已开 + 只能再加 1 只 (10%) 到 60%, 其余 9 只被跳过
    new_tickers = [f"20000{i}" for i in range(10)]
    report_path = tmp_path / "auto_screening_20260708.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "20260708",
                "recommendations": [{"ticker": t} for t in new_tickers],
                "market_state": {"regime_gate_level": "normal"},
            }
        ),
        encoding="utf-8",
    )
    prices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-07-08"),
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0,
                "pct_change": 9.5,
            }
        ]
    )
    actions = da.generate_daily_action(
        report_path=report_path,
        tracker=tracker,
        scan_mode="report",
        price_loader=lambda ticker, report_date: prices.copy(),
    )
    assert len(actions) == 1, f"应只追加 1 只到 60%, 实际 {len(actions)}"
    # 10 信号 - 1 录入 = 9 被跳过 (不是 1)
    assert len(tracker.last_blocked_candidates) == 9, f"blocked_candidates 应有 9 个 (10 信号 - 1 录入), 实际 {len(tracker.last_blocked_candidates)}"


# ---------------------------------------------------------------------------
# C-DUAL-SIGNAL-CONVERGENCE (20260710): --auto Top-N ∩ BTST 命中 双信号标记
# empirical: BTST∩--auto 同日 n=34 win=76% med+7.35% vs BTST-only n=99 win=66% med+5.67%
# (n 小未达显著, 仅供优先级参考)
# ---------------------------------------------------------------------------


def test_load_auto_topn_tickers_reads_report(tmp_path, monkeypatch):
    """_load_auto_topn_tickers 从信号日 --auto 报告读 Top-N ticker 集合."""
    import json as _json
    from src.screening.offensive import daily_action as da

    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "auto_screening_20260709.json").write_text(
        _json.dumps({"date": "20260709", "recommendations": [{"ticker": "300308"}, {"ticker": "688008.SH"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.screening.consecutive_recommendation.resolve_report_dir", lambda: reports)
    topn = da._load_auto_topn_tickers("20260709")
    assert topn == {"300308", "688008"}, f"got {topn}"


def test_load_auto_topn_tickers_missing_report_returns_empty(tmp_path, monkeypatch):
    """报告缺失 → 空集合 (收敛标记降级, 不阻塞渲染)."""
    from src.screening.offensive import daily_action as da

    monkeypatch.setattr("src.screening.consecutive_recommendation.resolve_report_dir", lambda: tmp_path)
    assert da._load_auto_topn_tickers("20260101") == set()
    assert da._load_auto_topn_tickers("") == set()


def test_render_badges_dual_signal_convergence(tmp_path, monkeypatch):
    """BTST 命中里同日也在 --auto Top-N 的票, 渲染时标 ⭐双信号."""
    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    class FakeSetup:
        def detect(self, ticker, trade_date, context):
            return DetectionResult(hit=True, ticker=ticker, trade_date=trade_date, trigger_strength=1.0, invalidation_condition="fake")

    dist = Distribution(n=100, winrate=0.60, avg_gain=0.12, avg_loss=-0.06, convexity_ratio=2.0, expected_return=0.05, ci_low=0.02, ci_high=0.08, ic=0.10)
    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [("btst_breakout", FakeSetup, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    monkeypatch.setattr(da, "_env_setup_disable_list", lambda: set())
    monkeypatch.delenv("DAILY_ACTION_ENFORCE_OPEN_CAP", raising=False)
    # --auto Top-N 含 300308 (收敛), 不含 688999
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "auto_screening_20260709.json").write_text(
        __import__("json").dumps({"date": "20260709", "recommendations": [{"ticker": "300308"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.screening.consecutive_recommendation.resolve_report_dir", lambda: reports)

    tracker = PaperTracker(journal_dir=tmp_path)
    report_path = tmp_path / "auto_screening_20260709.json"
    report_path.write_text(
        __import__("json").dumps({"date": "20260709", "recommendations": [{"ticker": "300308"}, {"ticker": "688999"}], "market_state": {"regime_gate_level": "normal"}}),
        encoding="utf-8",
    )
    prices = pd.DataFrame([{"date": pd.Timestamp("2026-07-09"), "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "pct_change": 9.5}])
    actions = da.generate_daily_action(report_path=report_path, tracker=tracker, scan_mode="report", price_loader=lambda ticker, report_date: prices.copy())
    out = da.render_daily_action(actions, "20260709", tracker)
    # 300308 收敛 → 标 ⭐双信号; 688999 不收敛 → 无标记
    assert "300308" in out and "⭐双信号" in out, "收敛票应标 ⭐双信号"
    assert "688999" in out
    # 双信号摘要行: bootstrap 验证未达显著 → 诚实披露 "未达显著/可能是噪声", 不宣称 76% vs 66%
    assert "双信号" in out and "未达显著" in out, "应诚实披露 bootstrap 未验证"
    assert "76%" not in out, "不应展示未达显著的点估计 (会误导 operator)"


# ---------------------------------------------------------------------------
# C-DAILY-ACTION-POSITION-VISIBILITY (c85bfe50, 20260710): 持仓明细 + 到期释放日程
# 渲染回归守卫. commit c85bfe50 加了 +147 行渲染逻辑 (open_positions_detail +
# render 持仓块 + _render_candidate_list 截断) 却无直接测试 — 同期 cap 守卫加了
# 434 行测试, 这块是发布前的验证盲区. 以下回归锁定 operator 能看到 "买了什么 /
# 何时到期释放 / 上限跳过哪些候选", 防止未来重构悄悄删掉这些披露.
# ---------------------------------------------------------------------------


def test_open_positions_detail_returns_only_unexited_buys(tmp_path):
    """open_positions_detail 必须从 journal 真值重建未平仓明细 (BUY - EXIT).

    幂等语义关键点: EXIT 记录的 date 字段是 *买入日* (close_matured 用
    ``date=buy_date`` 写 EXIT, 对齐 BUY natural-key), 不是平仓日. 本测试
    锁定这一口径 — 如果未来有人误改成用平仓日写 EXIT, open_positions_detail
    会把已平仓位算成未平仓 (exit_keys 永不命中), operator 看到幽灵持仓.
    直接写 journal 原始记录 (与 test_open_positions_self_heal_subtracts_exits
    同口径), 隔离 close_matured 的数据拉取复杂度, 聚焦被测函数.
    """
    import json as _json
    from src.screening.offensive.paper_tracker import PaperTracker

    journal = tmp_path / "journal.jsonl"
    records = [
        {"date": "20260701", "ticker": "300308", "setup": "btst_breakout", "horizon": 10, "action": "BUY", "kelly_pct": 0.10, "entry_price": 10.0},
        {"date": "20260702", "ticker": "688999", "setup": "oversold_bounce", "horizon": 5, "action": "BUY", "kelly_pct": 0.05, "entry_price": 20.0},
        # EXIT.date = buy_date 约定 (与 close_matured 写出口径一致) → 300308 已平仓
        {"date": "20260701", "ticker": "300308", "action": "EXIT"},
    ]
    journal.write_text("\n".join(_json.dumps(r) for r in records) + "\n", encoding="utf-8")

    tracker = PaperTracker(journal_dir=tmp_path)
    details = tracker.open_positions_detail(as_of="20260710")

    tickers = {d["ticker"] for d in details}
    assert "300308" not in tickers, "已平仓的 300308 不应出现在未平仓明细"
    assert "688999" in tickers, "未平仓的 688999 应出现"
    # 第二笔的到期日 = 买入日 + T+5 交易日 (保守日历日下限 5 + 2*floor(5/5) = 7)
    # = 20260702 + 7 = 20260709 (旧日历日口径 20260707 比真实 T+5 交易日早 2 天)
    row = next(d for d in details if d["ticker"] == "688999")
    assert row["matures_on"] == "20260709", f"到期日应为 20260709 (T+5 交易日口径), 实际 {row['matures_on']}"
    assert row["days_to_maturity"] == -1, f"20260709 相对 20260710 应 -1 天 (已过期未平), 实际 {row['days_to_maturity']}"
    assert row["setup"] == "oversold_bounce"
    assert row["horizon"] == 5
    assert row["kelly_pct"] == 0.05


def test_open_positions_detail_sorted_by_maturity_ascending(tmp_path):
    """多仓时应按 matures_on 升序, 让 operator 第一眼看到最快到期的仓位."""
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker(journal_dir=tmp_path)
    # 故意以乱序买入: horizon 5 的后买, horizon 10 的先买
    # (到期日 = 买入日 + T+N 交易日保守日历日下限: h10→+14, h5→+7)
    tracker.record_buy("20260701", "AAAAAA", "btst_breakout", 10, 10.0, 0.10, 9.0, 9.2, "fake")  # 到期 0715
    tracker.record_buy("20260705", "BBBBBB", "oversold_bounce", 5, 10.0, 0.10, 9.0, 9.2, "fake")  # 到期 0712

    details = tracker.open_positions_detail(as_of="20260706")

    matures = [d["matures_on"] for d in details]
    assert matures == sorted(matures), f"应按 matures_on 升序, 实际顺序 {matures}"
    assert details[0]["ticker"] == "BBBBBB", "最快到期 (0712) 应排第一"


# ---------------------------------------------------------------------------
# C-DAILY-ACTION-MATURITY-CALENDAR-TRADING-MISMATCH (autodev loop 177):
# _is_matured / open_positions_detail 用 ``timedelta(days=horizon)`` (日历日),
# 但 close_matured 的 P&L 用 ``fetch_actual_returns`` 的 ``closes[horizon]`` (交易日,
# 索引 0=买入日). BTST horizon=10: 10 日历日 ≈ 7 交易日, 而 10 交易日 ≈ 14-16 日历日
# (真实 backtest journal: BUY→T+10交易日 间距 14-22 日历日, mean 15.6). → 显示的
# matures_on 比真实 T+10 交易日早 4-12 天, operator 在 as_of=calendar-day-10 看到
# "今日到期 (days_to_maturity=0)" 但 close_matured 拿不到 day_10 (收盘价尚未存在) →
# 静默跳过, 持仓继续显示 "今日到期" 直到交易日-10 收盘价出现 (4-12 天空窗).
# Fix: maturity 用交易日口径 (保守日历日近似 ``horizon + 2*floor(horizon/5)``,
# 每 5 交易日加 2 个周末日), 与 day_{horizon} P&L 回填语义对齐.
# ---------------------------------------------------------------------------


def test_is_matured_uses_trading_day_not_calendar_day_btst():
    """BTST horizon=10: 日历日 +10 天不应判到期 (真实 T+10 交易日 ≈ +14 日历日).

    旧实现 ``timedelta(days=10)`` 在 as_of=buy+10 日历日就返回 True, 比 day_10 P&L
    (closes[10] = 第 10 个交易日 ≈ +14 日历日) 早 4 天 → 触发 close_matured 但
    day_10 数据未成熟 → 静默跳过, 渲染层却显示 "今日到期".
    """
    from src.screening.offensive.paper_tracker import PaperTracker

    # BUY 20260601 (周一), horizon=10. 日历日 +10 = 20260611 (周四), 但 T+10 交易日
    # 至少需 +14 日历日 (含 2 个周末). 0611 不应判到期.
    assert not PaperTracker._is_matured("20260601", 10, "20260611"), "BTST horizon=10 在 +10 日历日 (0611) 不应判到期: 真实 T+10 交易日 ≈ +14 日历日, " "过早判到期会触发 close_matured 但 day_10 数据未成熟 → 静默跳过 + 显示'今日到期'空窗"
    # +14 日历日 (20260615) 是保守下限 (真实分布 14-22), 应判到期
    assert PaperTracker._is_matured("20260601", 10, "20260615"), "BTST horizon=10 在 +14 日历日 (0615, 保守交易日下限) 应判到期"


def test_is_matured_oversold_horizon5_uses_trading_day():
    """OversoldBounce horizon=5: 日历日 +5 不应判到期 (T+5 交易日 ≈ +7 日历日)."""
    from src.screening.offensive.paper_tracker import PaperTracker

    # BUY 20260601, horizon=5. 日历日 +5 = 20260606 (周六), T+5 交易日 ≈ +7 日历日.
    assert not PaperTracker._is_matured("20260601", 5, "20260606"), "OversoldBounce horizon=5 在 +5 日历日不应判到期: T+5 交易日 ≈ +7 日历日"
    assert PaperTracker._is_matured("20260601", 5, "20260608"), "OversoldBounce horizon=5 在 +7 日历日应判到期 (保守交易日下限)"


def test_open_positions_detail_matures_on_uses_trading_day(tmp_path):
    """matures_on 必须用交易日口径, 不能是 buy_date + horizon 日历日.

    旧实现: BTST 0701 买入 → matures_on=0711 (0701+10 日历日), 比真实 T+10 交易日
    (≈0715) 早 4 天. operator 看到 "到期 0711" 但 P&L 在 ~0715 才回填 → 0711-0715
    显示 "今日到期" 却无平仓.
    """
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker(journal_dir=tmp_path)
    tracker.record_buy("20260701", "300308", "btst_breakout", 10, 10.0, 0.10, 9.0, 9.2, "fake")
    details = tracker.open_positions_detail(as_of="20260701")
    assert len(details) == 1
    row = details[0]
    # horizon=10 交易日 → 至少 +14 日历日 (20260715), 不能是 +10 日历日 (20260711)
    assert row["matures_on"] >= "20260715", f"BTST horizon=10 matures_on 应 >= 20260715 (交易日口径 +14 日历日下限), " f"实际 {row['matures_on']} (旧日历日口径 20260711 比真实 T+10 早 4 天)"
    assert row["matures_on"] != "20260711", "matures_on 不能是 buy_date + 10 日历日 (0711): 这比 day_10 P&L (closes[10], " "第 10 个交易日 ≈ 0715) 早 4 天, 导致 '今日到期' 却无平仓的空窗"


def test_render_shows_held_positions_and_maturity_release_schedule(tmp_path, monkeypatch):
    """render 持仓块必须列出每仓 + 最近到期释放日程 + 释放机制说明.

    锁定 c85bfe50 加的三块披露: (1) 📌 每仓明细 (2) 💡 最近到期释放多少敞口
    (3) 释放机制说明. 这些是 operator 理解 "仓位何时释放 / 释放后能否出新仓"
    的唯一入口 — 删掉任何一块都是回退到 "只看到持仓数 N" 的盲区.
    """
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260709", raising=False)
    monkeypatch.setattr(da, "_setup_policy_lines", lambda **kw: [], raising=False)
    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda t: f"测试股{t[-2:]}")

    tracker = PaperTracker(journal_dir=tmp_path)
    # 一笔未到期 (剩 3 天), 50% 敞口占用
    tracker.record_buy("20260706", "300308", "btst_breakout", 10, 10.0, 0.50, 9.0, 9.2, "fake")

    out = da.render_daily_action([], "20260706", tracker, explain=True)

    # (1) 持仓明细: ticker + setup + 买入日 + 价格 + 到期日
    assert "📌" in out and "当前持仓" in out, "应有持仓明细标题"
    assert "300308" in out and "btst_breakout" in out, "应列出每仓 ticker + setup"
    assert "20260706买入" in out, "应显示买入日"
    # 到期日 = 买入日 + T+10 交易日 (保守日历日下限 10 + 2*floor(10/5) = 14)
    # = 20260706 + 14 = 20260720 (旧日历日口径 20260716 比真实 T+10 交易日早 4 天)
    # 剩N天以今天为基准 (非信号日), 故只断言到期日存在, 不断言具体天数.
    assert "到期 20260720" in out, f"应显示到期日, 实际:\n{out}"
    # (2) 最近到期释放日程
    assert "💡" in out and "最近到期" in out, "应有最近到期释放日程"
    assert "释放" in out and "敞口" in out, "应说明释放多少敞口"
    # (3) 释放机制说明 (operator 需要知道无需手动平仓)
    assert "释放机制" in out, "应说明自动平仓机制"


def test_render_release_schedule_says_cap_cleared_when_dropping_below_limit(tmp_path, monkeypatch):
    """到期释放后敞口降回上限内时, 应明确告诉 operator "可恢复出新仓".

    这是 c85bfe50 的关键行为: 释放日程不仅算数字, 还判断释放后是否仍超上限,
    给出可执行结论 ("降回上限内, 可恢复出新仓" vs "仍超上限, 需继续等待").
    """
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260709", raising=False)
    monkeypatch.setattr(da, "_setup_policy_lines", lambda **kw: [], raising=False)
    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda t: f"测试股{t[-2:]}")

    tracker = PaperTracker(journal_dir=tmp_path)
    # 50% 敞口, T+10 未来到期 → 释放后敞口降到 0% (< 60% 上限) → 应说 "可恢复"
    # buy_date 用近期日期, 确保 days_to_maturity (以今天为基准) > 0.
    tracker.record_buy("20260710", "300308", "btst_breakout", 10, 10.0, 0.50, 9.0, 9.2, "fake")

    out = da.render_daily_action([], "20260710", tracker)

    assert "可恢复出新仓" in out, f"释放后敞口降回上限内, 应告诉 operator 可恢复, 实际:\n{out}"
    assert "仍超" not in out


def test_render_candidate_list_truncates_with_rest_count(tmp_path, monkeypatch):
    """候选超过 limit 时应显示前 limit 个 + '其余 N 只略', 避免刷屏.

    锁定 _render_candidate_list (c85bfe50 新增) 的截断行为. 当敞口超限全部候选
    被跳过 (not actions and blocked) 时, render 走 limit=12 列出候选 (daily_action.py:945-949),
    operator 需要知道 "总共有几只", 不能只看到前 N 只以为就这么多.
    """
    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    class FakeSetup:
        def detect(self, ticker, trade_date, context):
            return DetectionResult(hit=True, ticker=ticker, trade_date=trade_date, trigger_strength=1.0, invalidation_condition="fake")

    dist = Distribution(n=100, winrate=0.60, avg_gain=0.12, avg_loss=-0.06, convexity_ratio=2.0, expected_return=0.05, ci_low=0.02, ci_high=0.08, ic=0.10)
    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [("btst_breakout", FakeSetup, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    monkeypatch.setattr(da, "_env_setup_disable_list", lambda: set())
    monkeypatch.delenv("DAILY_ACTION_ENFORCE_OPEN_CAP", raising=False)
    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260709", raising=False)
    monkeypatch.setattr(da, "_setup_policy_lines", lambda **kw: [], raising=False)
    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda t: f"股{t[-2:]}")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "auto_screening_20260709.json").write_text(
        __import__("json").dumps({"date": "20260709", "recommendations": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.screening.consecutive_recommendation.resolve_report_dir", lambda: reports)

    tracker = PaperTracker(journal_dir=tmp_path)
    # 60% 已开仓 → 上限满, 14 只新信号全部被跳过 (not actions, all blocked)
    tracker.record_buy("20260707", "500001", "btst_breakout", 10, 10.0, 0.60, 9.0, 9.2, "fake")
    new_tickers = [f"60000{i}" for i in range(14)]
    report_path = tmp_path / "auto_screening_20260709.json"
    report_path.write_text(
        __import__("json").dumps({"date": "20260709", "recommendations": [{"ticker": t} for t in new_tickers], "market_state": {"regime_gate_level": "normal"}}),
        encoding="utf-8",
    )
    prices = pd.DataFrame([{"date": pd.Timestamp("2026-07-09"), "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "pct_change": 9.5}])

    actions = da.generate_daily_action(report_path=report_path, tracker=tracker, scan_mode="report", price_loader=lambda ticker, report_date: prices.copy())
    assert actions == [], "60% 已满 + 60% 单仓 → 应无新 BUY (全部 blocked)"
    out = da.render_daily_action(actions, "20260709", tracker)

    # not actions + blocked → 走 limit=12 候选列出路径 (daily_action.py:945-949)
    assert "14 个 setup 命中" in out, f"应报告 14 个被跳过的候选, 实际:\n{out}"
    assert "暂不买入" in out, "应说明因敞口超限暂不买入"
    # limit=12, 14 候选 → 显示前 12 + "其余 2 只略"
    assert "其余" in out and "只略" in out, "候选超过 limit 应显示截断提示"
    assert "其余 2 只略" in out, f"14 - 12 = 2 只略, 实际:\n{out}"


def test_held_ticker_excluded_from_candidates(tmp_path, monkeypatch):
    """已持仓 ticker 不应出现在候选列表 (C-HELD-DEDUP).

    回归: 此前 generate_daily_action 不排除已开仓 ticker, 同一涨停日对已持仓票
    同样触发 setup → 候选列表 (敞口超限时的"仓位释放后买以下候选")出现当前已持有的
    票, operator 误以为"释放后买这些"实为重复建仓. 修复: 扫描前从 open_positions_detail
    取 held_tickers, 循环内 continue.
    """
    import json

    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    class FakeSetup:
        def detect(self, ticker, trade_date, context):
            return DetectionResult(hit=True, ticker=ticker, trade_date=trade_date, trigger_strength=0.9, invalidation_condition="fake")

    dist = Distribution(n=100, winrate=0.60, avg_gain=0.12, avg_loss=-0.06, convexity_ratio=2.0, expected_return=0.05, ci_low=0.02, ci_high=0.08, ic=0.10)
    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [("btst_breakout", FakeSetup, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    monkeypatch.setattr(da, "_env_setup_disable_list", lambda: set())
    monkeypatch.delenv("DAILY_ACTION_ENFORCE_OPEN_CAP", raising=False)
    monkeypatch.setattr(da, "_resolve_next_trade_date", lambda trade_date: "20260709", raising=False)
    monkeypatch.setattr(da, "_setup_policy_lines", lambda **kw: [], raising=False)
    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda t: f"股{t[-2:]}")

    tracker = PaperTracker(journal_dir=tmp_path)
    # 已持仓 500001 (60% 单仓占满上限, 使后续信号全部进 blocked 候选列表)
    held_ticker = "500001"
    tracker.record_buy("20260707", held_ticker, "btst_breakout", 10, 10.0, 0.60, 9.0, 9.2, "fake")

    # 扫描集 = [已持仓 500001, 新票 600001] — 已持仓的不应进候选
    report_path = tmp_path / "auto_screening_20260709.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "20260709",
                "recommendations": [{"ticker": held_ticker}, {"ticker": "600001"}],
                "market_state": {"regime_gate_level": "normal"},
            }
        ),
        encoding="utf-8",
    )
    prices = pd.DataFrame([{"date": pd.Timestamp("2026-07-09"), "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "pct_change": 9.5}])

    actions = da.generate_daily_action(report_path=report_path, tracker=tracker, scan_mode="report", price_loader=lambda ticker, report_date: prices.copy())
    assert actions == [], "60% 已满 → 应无新 BUY (全部 blocked)"
    out = da.render_daily_action(actions, "20260709", tracker)

    # 去重生效: 命中数 = 1 (只含未持仓的 600001), 不含已持仓的 500001.
    # 500001 合理出现在"当前持仓"段, 但不应出现在"候选"段 — 用分隔锚点切分两段检查.
    candidate_section = out.split("按强度优先买以下候选")[-1] if "按强度优先买以下候选" in out else out
    assert "1 个 setup 命中" in out, f"应报告 1 个候选 (不含已持仓的), 实际:\n{out}"
    assert held_ticker not in candidate_section, f"已持仓 {held_ticker} 不应出现在候选段, 实际:\n{candidate_section}"
    assert "600001" in candidate_section, f"未持仓 600001 应在候选段, 实际:\n{candidate_section}"
    # trigger_strength 也应展示 (改动3: 排序依据可见)
    assert "强度 0.90" in candidate_section, f"候选行应展示 trigger_strength, 实际:\n{candidate_section}"
    assert "先验(驱动Kelly)" in candidate_section, f"候选行应标注'先验(驱动Kelly)'区分口径, 实际:\n{candidate_section}"
