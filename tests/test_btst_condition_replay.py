"""btst_condition_replay — 条件级重放分桶的 fixture 驱动测试.

零网络/零 gitignored 资产: 真实 BtstBreakoutSetup.detect + 合成帧
(fixture 手法与 tests/offensive/test_btst_breakout.py 同源)。
"""

from __future__ import annotations

import pandas as pd

from src.screening.offensive.data.fund_flow_store import FundFlowRecord

from scripts.btst_condition_replay import (
    BUCKETS,
    assign_bucket,
    attach_realized,
    bucket_stats,
    realized_map_from_journal,
    replay_one,
)


def _prices_with_limit_up_today():
    """22 个交易日, 今日涨停 +10%, 前 5 日涨幅 4.76% (过条件4)."""
    dates = pd.bdate_range("2026-06-01", periods=22)
    closes = [10.0] * 21 + [11.0]
    closes[-6] = 10.5
    pct = [0.0] * 20 + [0.0, 10.0]
    return pd.DataFrame(
        {"date": dates, "close": closes, "open": closes, "high": closes, "low": closes, "pct_change": pct}
    )


def _flows_today_strong(prices, today_inflow=5_000_000, hist_inflow=100_000):
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=today_inflow, main_net_pct=8.0)]
    for i in range(1, 21):
        d = prices.iloc[-1 - i]["date"].strftime("%Y%m%d")
        recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=hist_inflow, main_net_pct=0.5))
    return recs


def _today(prices):
    return prices.iloc[-1]["date"].strftime("%Y%m%d")


class TestAssignBucket:
    def test_regime_blocks_first(self):
        assert assign_bucket("crisis", True, 0.9)[0] == "regime_blocked"
        assert assign_bucket("risk_off", True, 0.9)[0] == "regime_blocked"

    def test_miss_when_no_hit(self):
        bucket, _ = assign_bucket("normal", False, 0.0)
        assert bucket == "detect_miss_today"

    def test_strength_below_threshold(self):
        bucket, stage = assign_bucket("normal", True, 0.49)
        assert bucket == "detect_miss_today"
        assert stage == "strength_below_threshold"

    def test_would_fire(self):
        assert assign_bucket("normal", True, 0.50) == ("would_fire_today", None)
        assert assign_bucket("normal", True, 0.75) == ("would_fire_today", None)

    def test_bucket_universe(self):
        assert set(BUCKETS) == {"regime_blocked", "detect_miss_today", "would_fire_today"}


class TestReplayOne:
    def test_would_fire_today_all_conditions_met(self):
        prices = _prices_with_limit_up_today()
        res = replay_one(
            "600600", _today(prices),
            prices=prices, fund_flow_records=_flows_today_strong(prices),
            industry_name="医药生物", industry_pct=3.0, regime="normal",
        )
        assert res.bucket == "would_fire_today"
        assert res.hit is True
        assert res.court_strength >= 0.50

    def test_regime_blocked_even_when_detect_hits(self):
        prices = _prices_with_limit_up_today()
        res = replay_one(
            "600600", _today(prices),
            prices=prices, fund_flow_records=_flows_today_strong(prices),
            industry_name="医药生物", industry_pct=3.0, regime="crisis",
        )
        assert res.bucket == "regime_blocked"
        assert res.hit is True  # detect 本身仍 hit — gate 是外层分桶

    def test_c3_industry_weak_miss(self):
        prices = _prices_with_limit_up_today()
        res = replay_one(
            "600600", _today(prices),
            prices=prices, fund_flow_records=_flows_today_strong(prices),
            industry_name="建筑材料", industry_pct=1.0, regime="normal",
        )
        assert res.bucket == "detect_miss_today"
        assert res.miss_stage and res.miss_stage.startswith("c3")

    def test_c2_flow_below_mean_miss(self):
        prices = _prices_with_limit_up_today()
        res = replay_one(
            "600600", _today(prices),
            prices=prices,
            fund_flow_records=_flows_today_strong(prices, today_inflow=10_000, hist_inflow=5_000_000),
            industry_name="医药生物", industry_pct=3.0, regime="normal",
        )
        assert res.bucket == "detect_miss_today"
        assert res.miss_stage and res.miss_stage.startswith("c2")


class TestRealizedAndStats:
    def _record(self, bucket, realized):
        from scripts.btst_condition_replay import ReplayResult

        return ReplayResult(
            signal_date="20260813", ticker="300534", horizon=10, regime="crisis",
            hit=True, miss_stage=None, court_strength=0.63,
            industry_name="医药生物", industry_pct=1.13,
            bucket=bucket, realized_pct=realized,
        )

    def test_realized_map_extracts_signed_percent(self):
        journal = [
            {"action": "EXIT", "date": "20260813", "ticker": "300534", "reasoning": "T+10 到期平仓; realized=-9.11%; x"},
            {"action": "EXIT", "date": "20260807", "ticker": "301234", "reasoning": "realized=+16.07%"},
            {"action": "EXIT", "date": "20260821", "ticker": "601212", "reasoning": "无 realized"},
        ]
        mapping = realized_map_from_journal(journal)
        assert mapping[("20260813", "300534")] == -9.11
        assert mapping[("20260807", "301234")] == 16.07
        assert ("20260821", "601212") not in mapping

    def test_attach_realized(self):
        records = [self._record("regime_blocked", None)]
        attached = attach_realized(records, {("20260813", "300534"): -9.11})
        assert attached[0].realized_pct == -9.11

    def test_bucket_stats_aggregates(self):
        records = [
            self._record("regime_blocked", -9.11),
            self._record("regime_blocked", -2.20),
            self._record("would_fire_today", 16.07),
            self._record("detect_miss_today", -13.89),
        ]
        stats = bucket_stats(records)
        assert stats["regime_blocked"]["n_realized"] == 2
        assert stats["regime_blocked"]["expectancy_pct"] == -5.65
        assert stats["regime_blocked"]["win_rate_pct"] == 0.0
        assert stats["would_fire_today"]["win_rate_pct"] == 100.0
        assert stats["would_fire_today"]["expectancy_pct"] == 16.07
        assert stats["detect_miss_today"]["n_buys"] == 1

    def test_bucket_stats_miss_stage_tally(self):
        records = [
            self._record("detect_miss_today", None),
            self._record("detect_miss_today", None),
        ]
        # 手工改 miss_stage (fixture 便利; _record 默认 None)
        records = [
            records[0].__class__(**{**records[0].__dict__, "miss_stage": "c3_industry_weak"}),
            records[1].__class__(**{**records[1].__dict__, "miss_stage": "c3_industry_weak"}),
        ]
        stats = bucket_stats(records)
        assert stats["detect_miss_stages"] == {"c3_industry_weak": 2}


class TestPanelMissingFailLoud:
    """R96 Op5 对抗修复: 面板缺票绝不静默消失."""

    def _pm_record(self, ticker="999999", realized=-5.0):
        from scripts.btst_condition_replay import ReplayResult, PANEL_MISSING_BUCKET

        return ReplayResult(
            signal_date="20260813", ticker=ticker, horizon=10, regime="normal",
            hit=False, miss_stage="panel_missing", court_strength=0.0,
            industry_name=None, industry_pct=None,
            bucket=PANEL_MISSING_BUCKET, realized_pct=realized,
        )

    def test_panel_missing_disclosed_and_conserved(self):
        from scripts.btst_condition_replay import bucket_stats

        normal = [self._pm_record(ticker="600600", realized=-5.0)]
        # normal row needs a real bucket; reuse _record-style via bucket_stats directly
        from scripts.btst_condition_replay import ReplayResult
        would = ReplayResult(signal_date="20260821", ticker="601212", horizon=10,
                             regime="normal", hit=True, miss_stage=None, court_strength=0.65,
                             industry_name="有色金属", industry_pct=2.7,
                             bucket="would_fire_today", realized_pct=None)
        stats = bucket_stats([self._pm_record(realized=-5.0), would])
        pm = stats["panel_missing_ticker"]
        assert pm["n_buys"] == 1
        assert pm["tickers"] == ["999999"]
        # 不污染三桶: would_fire 仍只有 1
        assert stats["would_fire_today"]["n_buys"] == 1
        assert stats["regime_blocked"]["n_buys"] == 0

    def test_no_panel_missing_key_when_covered(self):
        from scripts.btst_condition_replay import bucket_stats, ReplayResult

        row = ReplayResult(signal_date="20260821", ticker="601212", horizon=10,
                           regime="normal", hit=True, miss_stage=None, court_strength=0.65,
                           industry_name="有色金属", industry_pct=2.7,
                           bucket="would_fire_today", realized_pct=None)
        stats = bucket_stats([row])
        assert "panel_missing_ticker" not in stats

    def test_md_discloses_panel_missing(self):
        from scripts.btst_condition_replay import bucket_stats, render_md

        stats = bucket_stats([self._pm_record(realized=-5.0)])
        payload = {"buckets": stats, "records": [self._pm_record(realized=-5.0).__dict__]}
        text = render_md(payload)
        assert "panel_missing_ticker" in text
        assert "999999" in text
