from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_monthly_scorecard as scorecard


def test_analyze_btst_monthly_scorecard_adds_regime_gate_buckets_when_daily_events_available(tmp_path: Path, monkeypatch) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_path = reports_dir / "btst_full_report_20260506.json"
    report_path.write_text(
        json.dumps(
            {
                "trade_date": "20260506",
                "next_date": "20260507",
                "high_confidence": [{"ticker": "000001", "name": "PingAn", "score": 0.9, "pct_chg": 6.0, "close_strength": 1.0, "catalyst_freshness": 0.8}],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    daily_events_root = tmp_path / "daily_events"
    plan_dir = daily_events_root / "paper_trading_20260506_20260506_live_test_short_trade_only_20260506_plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    daily_events_path = plan_dir / "daily_events.jsonl"
    daily_events_path.write_text(
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

    def _fake_realized_prices(*, signal_date: str, tickers: list[str]):
        return {
            "000001": {
                "data_status": "ok",
                "next_open_return": 0.001,
                "next_close_return": 0.01,
                "next_open_to_close_return": 0.011,
                "max_high_t1_t5_from_open": 0.2,
            }
        }

    monkeypatch.setattr(scorecard, "generate_realized_prices", _fake_realized_prices)

    analysis = scorecard.analyze_btst_monthly_scorecard(
        month="202605",
        reports_dir=reports_dir,
        top_n=1,
        gap_cutoffs=[0.0],
        daily_events_root=daily_events_root,
    )

    assert analysis["tickers"][0]["regime_gate_level"] == "normal"
    assert analysis["overall"]["regime_gate_buckets"]["normal"]["count"] == 1
    assert analysis["overall"]["gap_overlay_suggestion"]["picked"]["label"] == "gap>=0.0%"
    assert analysis["overall"]["regime_gate_gap_overlay_suggestions"]["normal"]["picked"]["label"] == "gap>=0.0%"

    markdown = scorecard.render_btst_monthly_scorecard_markdown(analysis)
    assert "Regime buckets" in markdown
