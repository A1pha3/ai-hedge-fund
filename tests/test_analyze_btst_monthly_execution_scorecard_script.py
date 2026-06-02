from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import scripts.analyze_btst_monthly_execution_scorecard as exec_scorecard


def test_analyze_btst_monthly_execution_scorecard_uses_formal_selected(monkeypatch, tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)

    plan_dir = reports_dir / "paper_trading_20260506_20260506_live_test_short_trade_only_20260506_plan"
    plan_dir.mkdir(parents=True)

    (plan_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20260506",
                "current_plan": {"market_state": {"regime_gate_level": "normal"}},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # trade brief: one primary entry + one selected entry
    (plan_dir / "btst_next_day_trade_brief_latest.json").write_text(
        json.dumps(
            {
                "trade_date": "20260506",
                "next_trade_date": "20260507",
                "primary_entry": {"ticker": "000001"},
                "selected_entries": [{"ticker": "000002"}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def _fake_realized_prices(*, signal_date: str, tickers: list[str]):
        assert signal_date == "20260506"
        assert sorted(tickers) == ["000001", "000002"]
        return {
            "000001": {
                "data_status": "ok",
                "next_open_return": 0.01,
                "next_close_return": 0.02,
                "next_open_to_close_return": 0.01,
                "max_high_t1_t5_from_open": 0.2,
            },
            "000002": {
                "data_status": "ok",
                "next_open_return": -0.01,
                "next_close_return": -0.02,
                "next_open_to_close_return": -0.01,
                "max_high_t1_t5_from_open": 0.1,
            },
        }

    monkeypatch.setattr(exec_scorecard, "generate_realized_prices", _fake_realized_prices)

    analysis = exec_scorecard.analyze_btst_monthly_execution_scorecard(month="202605", reports_dir=reports_dir)

    assert analysis["month"] == "202605"
    assert analysis["overall"]["pick_count"] == 2
    assert analysis["overall"]["ok_count"] == 2
    assert analysis["overall"]["win_rate_next_close"] == 0.5

    segments = analysis["overall"]["gap_segments"]
    assert segments["negative"]["count"] == 1
    assert segments["non_negative"]["count"] == 1

    # Should have one daily row
    assert len(analysis["daily"]) == 1
    assert analysis["daily"][0]["pick_count"] == 2

    markdown = exec_scorecard.render_btst_monthly_execution_scorecard_markdown(analysis)
    assert "BTST Monthly Execution Scorecard 202605" in markdown
    assert "Daily breakdown" in markdown
    assert "Gap overlay counterfactual" in markdown
