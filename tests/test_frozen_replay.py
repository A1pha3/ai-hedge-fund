from __future__ import annotations

import json

from src.paper_trading.frozen_replay import load_frozen_post_market_plans


def test_load_frozen_post_market_plans_backfills_missing_plan_date_from_trade_date(tmp_path) -> None:
    source_path = tmp_path / "daily_events.jsonl"
    source_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20260421",
                "current_plan": {
                    "market_state": {
                        "breadth_ratio": 0.66,
                        "daily_return": -0.004,
                        "style_dispersion": 0.18,
                        "regime_flip_risk": 0.08,
                        "regime_gate_level": "normal",
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    plans = load_frozen_post_market_plans(source_path)

    assert plans["20260421"].date == "20260421"
    assert plans["20260421"].market_state.regime_gate_level == "normal"
