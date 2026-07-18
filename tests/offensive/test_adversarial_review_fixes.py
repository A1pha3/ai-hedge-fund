"""对抗性审查 (2026-07-18) 修复的回归测试.

覆盖:
- price_returns.chained_return_pct: 除权免疫的窗口收益
- BTST: 幻影 pre_runup (除权) / 超帽无限制日上界护栏
- OversoldBounce: 幻影超跌 (除权)
- v2 scan: regime 证据未绑定前不实际加仓 (F4) / 台账未启用 setup 拦截 (F2)
- dispatcher._cached_daily_action_market_bar: 涨跌停价推导 + 停牌推导 (P0-1)
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pandas as pd
import pytest

from src.screening.offensive.data.fund_flow_store import FundFlowRecord
from src.screening.offensive.daily_action import scan_from_verified_snapshot
from src.screening.offensive.execution_adjuster import ExecutionStatus, classify_open_fill
from src.screening.offensive.price_returns import chained_return_pct
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup

from tests.offensive.test_daily_action_snapshot_scan import (
    _capability,
    _snapshot,
    hit_result,
)


# ---------------------------------------------------------------------------
# chained_return_pct
# ---------------------------------------------------------------------------


def _frame(closes, pcts=None):
    dates = pd.bdate_range("2026-06-01", periods=len(closes))
    if pcts is None:
        pcts = [0.0] + list(pd.Series(closes).pct_change().fillna(0.0) * 100.0)[1:]
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "pct_change": pcts,
        }
    )


def test_chained_return_matches_close_ratio_without_gap():
    prices = _frame([10.0, 10.5, 11.0, 11.5])
    assert chained_return_pct(prices, 0, 3) == pytest.approx(15.0)


def test_chained_return_ignores_ex_dividend_gap():
    """除权日: close 308.08 → 228.7 (raw -25.8%) 但真实涨幅 +5.68% (pct_change).
    链式复合必须返回真实涨幅, 不是原始价幻影."""
    prices = _frame([308.08, 228.7], pcts=[0.0, 5.68])
    assert chained_return_pct(prices, 0, 1) == pytest.approx(5.68)


def test_chained_return_none_on_nan_and_bad_bounds():
    prices = _frame([10.0, 10.5], pcts=[0.0, float("nan")])
    assert chained_return_pct(prices, 0, 1) is None
    assert chained_return_pct(prices, 1, 1) is None
    assert chained_return_pct(prices, 0, 5) is None
    assert chained_return_pct(prices.drop(columns=["pct_change"]), 0, 1) is None


# ---------------------------------------------------------------------------
# BTST: 幻影 pre_runup + 超帽护栏
# ---------------------------------------------------------------------------


def _btst_ctx(prices, trade_date):
    recs = [
        FundFlowRecord(
            ticker="X", date=trade_date, close=11.0, pct_change=10.0,
            main_net_inflow=5_000_000, main_net_pct=8.0,
        )
    ]
    for i in range(1, 21):
        d = prices.iloc[-1 - i]["date"].strftime("%Y%m%d")
        recs.append(
            FundFlowRecord(
                ticker="X", date=d, close=10.0, pct_change=0.0,
                main_net_inflow=100_000, main_net_pct=0.5,
            )
        )
    return {
        "prices": prices,
        "fund_flow_records": recs,
        "industry_day_pct": 3.0,
        "regime": "normal",
    }


def test_btst_misses_phantom_fresh_breakout_across_ex_dividend():
    """688167 型幻影: raw 5 日 -19.9% (看似超跌后首板), 调整后 +15.9% (追高),
    条件 4 必须按调整后收益拒绝."""
    dates = pd.bdate_range("2026-06-01", periods=22)
    closes = [10.0] * 22
    closes[-1] = 11.0  # 今日涨停
    closes[-6] = 20.0  # 除权前旧尺度价 (raw 看似高点)
    pcts = [0.0] * 22
    pcts[-5] = -50.0 + 0.0  # 占位, 下方精确构造
    # 精确构造: T-5 除权 -45% (raw 20→11) + 真实 -? — 简化为: T-5 raw 大跌但真实 +5%
    closes[-5] = 11.0
    pcts[-5] = 5.0   # 除权日: raw 20→11 (-45%) 但真实 +5%
    pcts[-4] = 0.0
    pcts[-3] = 5.0   # T-3 真实 +5%
    pcts[-2] = 5.0   # T-2 真实 +5%
    pcts[-1] = 10.0  # 今日涨停 (主板)
    prices = pd.DataFrame(
        {"date": dates, "open": closes, "high": closes, "low": closes, "close": closes, "pct_change": pcts}
    )
    trade_date = prices.iloc[-1]["date"].strftime("%Y%m%d")
    # raw 口径: 11.0/20.0 - 1 = -45% (幻影超跌); 调整后: 1.05×1.05×1.05-1 ≈ +15.8% (追高 > 8%)
    result = BtstBreakoutSetup().detect("X", trade_date, _btst_ctx(prices, trade_date))
    assert result.hit is False


def test_btst_misses_above_board_cap_resumption_day():
    """超过交易所真实板帽的 pct (如停牌复牌 +30%) 不是涨停, 必须拒绝."""
    dates = pd.bdate_range("2026-06-01", periods=22)
    closes = [10.0] * 22
    closes[-1] = 13.5
    pcts = [0.0] * 21 + [35.0]  # 主板 +35% > 10% 板帽 → 无限制日
    prices = pd.DataFrame(
        {"date": dates, "open": closes, "high": closes, "low": closes, "close": closes, "pct_change": pcts}
    )
    trade_date = prices.iloc[-1]["date"].strftime("%Y%m%d")
    result = BtstBreakoutSetup().detect("X", trade_date, _btst_ctx(prices, trade_date))
    assert result.hit is False


# ---------------------------------------------------------------------------
# OversoldBounce: 幻影超跌
# ---------------------------------------------------------------------------


def test_ob_misses_phantom_oversold_across_ex_dividend():
    """300033 型幻影: raw 30 日 -25.8% (看似超跌), 除权日真实 +5.68% → 必须拒绝."""
    dates = pd.bdate_range("2026-05-01", periods=32)
    closes = [10.0] * 31 + [7.5]  # raw 末日 -25%
    pcts = [0.0] * 31 + [5.68]  # 但末日真实是 +5.68% (除权)
    prices = pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000] * 32,
            "pct_change": pcts,
        }
    )
    trade_date = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs = [
        FundFlowRecord(
            ticker="X", date=trade_date, close=7.5, pct_change=5.68,
            main_net_inflow=5_000_000, main_net_pct=8.0,
        )
    ]
    ctx = {"prices": prices, "fund_flow_records": recs, "industry_day_pct": 0.0, "regime": "normal"}
    result = OversoldBounceSetup().detect("X", trade_date, ctx)
    assert result.hit is False


# ---------------------------------------------------------------------------
# v2 scan: F4 regime 不实际加仓 + F2 台账未启用 setup 拦截
# ---------------------------------------------------------------------------


def test_regime_uplift_not_applied_before_evidence_binding(monkeypatch) -> None:
    """crisis + strength 0.8: 证据未绑定前 weight = 10%×0.8 = 8%, 不得泄漏到 9.6%;
    候选仍带 authorization 标记用于披露."""
    from src.screening.offensive.daily_action_service import RegimeAuthorization

    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: dataclasses.replace(
            hit_result(), trigger_strength=0.8
        ),
    )
    snapshot = dataclasses.replace(_snapshot(), regime="crisis")

    scan = scan_from_verified_snapshot(snapshot)

    assert len(scan.candidates) == 1
    candidate = scan.candidates[0]
    assert candidate.target_weight == pytest.approx(0.08)  # 10%×0.8, 无 regime 泄漏
    assert candidate.authorization is RegimeAuthorization.BTST_CRISIS


def test_non_ledger_setup_is_blocked_not_raised(monkeypatch) -> None:
    """OB 在 manifest 启用时, scan 必须拦截为 blocked (setup_not_ledger_enabled)
    而不是在 PlanCandidate 构造时抛异常连带 BTST 一起 fail-closed."""
    from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup

    monkeypatch.setattr(
        BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result()
    )
    monkeypatch.setattr(
        OversoldBounceSetup, "detect", lambda self, ticker, trade_date, context: hit_result()
    )
    snapshot = _snapshot()
    # OB capability 启用 + OB consumed fingerprint 补齐 (setup_context 依赖).
    manifest = snapshot.manifest
    readiness = manifest.ticker_readiness["300001"]
    capabilities = dict(readiness.capabilities)
    capabilities["oversold_bounce"] = _capability()
    new_readiness = dataclasses.replace(
        readiness, capabilities=capabilities
    )
    ticker_readiness = dict(manifest.ticker_readiness)
    ticker_readiness["300001"] = new_readiness
    manifest = dataclasses.replace(manifest, ticker_readiness=ticker_readiness)
    consumed = dict(snapshot.consumed_fingerprint_by_ticker)
    from tests.offensive.test_daily_action_snapshot_scan import CONSUMED_FP

    consumed["300001"] = {"btst_breakout": CONSUMED_FP, "oversold_bounce": CONSUMED_FP}
    snapshot = dataclasses.replace(
        snapshot, manifest=manifest, consumed_fingerprint_by_ticker=consumed
    )

    scan = None
    # OB 预过滤要求 ≥31 行价格且 30 日跌幅 ≤ -20%; fixture 是 22 行平盘, 重新构造
    # 32 行: 30 日累计 -26% 的超跌序列 (pct_change 与 close 链一致).
    from decimal import Decimal
    from tests.offensive.test_daily_action_snapshot_scan import FrozenPriceRow, SIGNAL_DATE
    from datetime import timedelta

    # closes[0]=12.0 任意; closes[1..30] 阴跌 11.0→7.8 (-29%), 末日 +10% 涨停 (8.58).
    # BTST 需要末日 pct≥9.5; OB 需要 closes[1]→末日 ≤ -20% (8.58/11.0-1 = -22%).
    _r = (7.8 / 11.0) ** (1 / 29)
    closes = [12.0] + [11.0 * (_r**i) for i in range(30)] + [7.8 * 1.1]
    rows = []
    for index, close_value in enumerate(closes):
        session = SIGNAL_DATE - timedelta(days=31 - index)
        pct = 0.0 if index == 0 else (close_value / closes[index - 1] - 1) * 100.0
        close = Decimal(str(round(close_value, 4)))
        rows.append(
            FrozenPriceRow(
                trade_date=session,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("1000000"),
                pct_change=Decimal(str(round(pct, 4))),
            )
        )
    prices_map = dict(snapshot.prices_by_ticker)
    prices_map["300001"] = tuple(rows)
    snapshot = dataclasses.replace(snapshot, prices_by_ticker=prices_map)

    scan = scan_from_verified_snapshot(snapshot)  # 必须不抛异常

    assert len(scan.candidates) == 1
    assert scan.candidates[0].setup == "btst_breakout"
    reasons = {blocked.reason for blocked in scan.blocked_candidates}
    assert "setup_not_ledger_enabled" in reasons


# ---------------------------------------------------------------------------
# P0-1: MarketBar 涨跌停/停牌推导
# ---------------------------------------------------------------------------


def test_market_bar_derives_limit_prices_and_not_suspended(tmp_path) -> None:
    from src.cli.dispatcher import _cached_daily_action_market_bar

    cache = tmp_path / "000001.csv"
    pd.DataFrame(
        {
            "date": ["2026-07-16", "2026-07-17"],
            "close": [10.0, 10.2],
            "open": [10.0, 10.2],
            "high": [10.1, 10.3],
            "low": [9.9, 10.1],
            "pct_change": [0.0, 2.0],
            "volume": [1_000_000, 1_200_000],
        }
    ).to_csv(cache, index=False)

    bar = _cached_daily_action_market_bar(cache, date(2026, 7, 17))

    assert bar.suspended is False
    assert bar.limit_up == pytest.approx(11.0)   # 10.0 × 1.10, 四舍五入到分
    assert bar.limit_down == pytest.approx(9.0)
    assert (
        classify_open_fill(
            bar.open, bar.limit_down, bar.limit_up, bar.suspended,
            high=bar.high, low=bar.low,
        )
        is ExecutionStatus.EXECUTABLE_PROXY
    )


def test_market_bar_one_word_board_is_unexecutable(tmp_path) -> None:
    from src.cli.dispatcher import _cached_daily_action_market_bar

    cache = tmp_path / "000001.csv"
    pd.DataFrame(
        {
            "date": ["2026-07-16", "2026-07-17"],
            "close": [10.0, 11.0],
            "open": [10.0, 11.0],
            "high": [10.1, 11.0],
            "low": [9.9, 11.0],
            "pct_change": [0.0, 10.0],
            "volume": [1_000_000, 100_000],
        }
    ).to_csv(cache, index=False)

    bar = _cached_daily_action_market_bar(cache, date(2026, 7, 17))

    assert (
        classify_open_fill(
            bar.open, bar.limit_down, bar.limit_up, bar.suspended,
            high=bar.high, low=bar.low,
        )
        is ExecutionStatus.UNEXECUTABLE_PROXY
    )


def test_market_bar_first_row_stays_fail_closed(tmp_path) -> None:
    from src.cli.dispatcher import _cached_daily_action_market_bar

    cache = tmp_path / "000001.csv"
    pd.DataFrame(
        {
            "date": ["2026-07-17"],
            "close": [10.2],
            "open": [10.2],
            "high": [10.3],
            "low": [10.1],
            "pct_change": [2.0],
            "volume": [1_200_000],
        }
    ).to_csv(cache, index=False)

    bar = _cached_daily_action_market_bar(cache, date(2026, 7, 17))

    assert bar.limit_up is None and bar.limit_down is None
    assert (
        classify_open_fill(
            bar.open, bar.limit_down, bar.limit_up, bar.suspended,
            high=bar.high, low=bar.low,
        )
        is ExecutionStatus.UNKNOWN_QUEUE
    )
