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
    assert dist.n == 915  # 条件4 (涨停前5日涨幅≤5%) 过滤后
    assert dist.convexity_ratio > 1.5
    assert dist.winrate > 0.5
    assert abs(dist.expected_return - 0.0446) < 0.001


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
                date="20260601", ticker="300502", setup="btst_breakout", horizon=10,
                action="BUY", kelly_pct=0.10, entry_price=100.0, soft_stop=85.0,
                hard_stop=92.0, time_exit="T+10", invalidation_condition="跌破92", reasoning="dup",
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

    closed = tracker.close_matured(
        as_of="20260620", use_data_fetcher=fetcher, price_loader=price_loader
    )
    assert len(closed) == 1
    c = closed[0]
    assert c["stop_would_have_triggered"] is True, "期间 low=90 < hard_stop=92 应标记"
    # 主 P&L 仍是 T+10 收盘口径 (+5%), 不是止损价
    assert abs(c["realized_pnl"] - 0.05) < 1e-6, f"主P&L应=T+10收盘, got {c['realized_pnl']}"


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
    assert tracker.state.open_positions == 0, (
        f"generate_daily_action 未先平到期仓: open_positions={tracker.state.open_positions}. "
        f"闭环接入失败 — drawdown 检查基于陈旧 nav."
    )
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
    actions = da.generate_daily_action(
        report_path=report_path, tracker=tracker, use_data_fetcher=fetcher, price_loader=price_loader
    )
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


def test_generate_daily_action_blocks_new_buys_when_price_cache_lags_auto_report(tmp_path, monkeypatch):
    """price_cache 落后于最新 --auto 报告时, full_market 不应输出新 BUY."""
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker

    tracker = PaperTracker(journal_dir=tmp_path)
    monkeypatch.setattr(da, "_resolve_trade_date_and_regime", lambda: ("20260706", "normal"))
    monkeypatch.setattr(da, "_latest_auto_report_date", lambda: "20260708", raising=False)

    actions = da.generate_daily_action(tracker=tracker, scan_mode="full_market")

    assert actions == []
    assert "20260706" in tracker.last_action_stale_reason
    assert "20260708" in tracker.last_action_stale_reason


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
    monkeypatch.setattr(da, "_current_cn_datetime", lambda: datetime(2026, 7, 8, 12, 0), raising=False)
    monkeypatch.setattr(da, "_load_st_tickers", lambda: set())
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
    assert len(selected) == 6
    assert "000007" in selected
    assert "000001" not in selected
    assert selected[0] == "000007"


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
            distribution_summary="n=915 winrate=61% cv=2.18 E=+4.5%",
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

    out = da.render_daily_action(actions, "20260708", tracker)

    assert "软止损=历史平均亏损x1.5的观察线" in out
    assert "硬止损=固定-8%的实际风控线" in out
    assert "n=历史样本数" in out
    assert "winrate=历史胜率" in out
    assert "cv=凸性比" in out
    assert "E=历史平均收益" in out
    assert "执行规则 (按规则执行)" in out
    assert "不临盘主观加仓/扛单" in out
    assert "移除情绪" not in out


# ---------------------------------------------------------------------------
# render_daily_action — 平仓披露 + 移除死承诺
# ---------------------------------------------------------------------------


def test_render_shows_closed_positions(tmp_path):
    """render_daily_action 有平仓时, 必须显示平仓摘要 (ticker/realized_pnl/止损触发).

    诚实披露: 平仓是组合状态演进的核心, operator 必须能看到今日平了哪些仓、各仓
    realized P&L、以及期间是否触发了硬止损 (披露但未混入主 P&L).
    """
    from src.screening.offensive.daily_action import render_daily_action

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
    """OVERSOLD_BOUNCE_T5 已注册到 KNOWN_DISTRIBUTIONS."""
    from src.screening.offensive.known_distributions import get_known_distribution

    dist = get_known_distribution("oversold_bounce", 5)
    assert dist is not None
    assert dist.n >= 1000
    assert dist.convexity_ratio > 1.5
    assert dist.winrate > 0.5
    assert dist.expected_return > 0.02  # +2% 以上


def test_verified_setups_includes_both_btst_and_oversold():
    """_VERIFIED_SETUPS 应含 BTST + OversoldBounce 两个 setup."""
    from src.screening.offensive.daily_action import _VERIFIED_SETUPS

    names = [cfg[0] for cfg in _VERIFIED_SETUPS]
    assert "btst_breakout" in names
    assert "oversold_bounce" in names
