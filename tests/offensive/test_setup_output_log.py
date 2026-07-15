"""Tests for the live BTST setup-output logger (out-of-sample accumulation)."""

from __future__ import annotations

import json
from datetime import date

from src.screening.offensive.daily_action import DailyAction
from src.screening.offensive.setup_output_log import log_setup_outputs


def _action(ticker: str, **kw) -> DailyAction:
    base = dict(
        ticker=ticker,
        setup="btst_breakout",
        action="BUY",
        kelly_pct=0.067,
        entry_price=9.79,
        soft_stop=9.0,
        hard_stop=9.0,
        time_exit="T+10",
        invalidation_condition="",
        distribution_summary="n=133 winrate=68% cv=1.9 E=+8.2%",
        reasoning="",
        trigger_strength=0.62,
    )
    base.update(kw)
    return DailyAction(**base)


def test_log_setup_outputs_writes_structured_records(tmp_path):
    cand = _action(
        "600497",
        metadata={
            "pct_change": 10.0,
            "main_net_inflow": 3000.0,
            "industry_pct": 1.5,
            "pre_5d_runup_pct": 4.2,
        },
    )
    blocked = _action(
        "600362",
        action="SKIP",
        kelly_pct=0.0,
        entry_price=0.0,
        degraded=True,
        block_reason="readiness degraded: fund_flow_history_1d_lt_min_5d",
        trigger_strength=0.0,
    )

    path = log_setup_outputs(
        date(2026, 7, 14), [cand], [blocked], regime="normal", out_dir=tmp_path
    )

    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(records) == 2

    rec = next(r for r in records if r["ticker"] == "600497")
    assert rec["schema_version"] == 1
    assert rec["signal_date"] == "20260714"
    assert rec["setup"] == "btst_breakout"
    assert rec["plan_eligible"] is True
    assert rec["degraded"] is False
    assert rec["trigger_strength"] == 0.62
    assert rec["entry_price"] == 9.79
    assert rec["regime"] == "normal"
    assert rec["main_net_inflow"] == 3000.0
    assert rec["pre_5d_runup_pct"] == 4.2
    assert rec["industry_pct"] == 1.5

    blk = next(r for r in records if r["ticker"] == "600362")
    assert blk["plan_eligible"] is False
    assert blk["degraded"] is True
    assert "fund_flow_history" in blk["block_reason"]


def test_log_setup_outputs_is_idempotent_per_signal_date(tmp_path):
    cand = _action("600497", metadata={"pct_change": 10.0})
    for _ in range(3):
        path = log_setup_outputs(
            date(2026, 7, 14), [cand], [], regime="normal", out_dir=tmp_path
        )
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(records) == 1  # rerun overwrites the day's file, never duplicates
