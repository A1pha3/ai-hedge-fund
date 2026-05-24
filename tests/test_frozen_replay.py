from __future__ import annotations

import json

from src.paper_trading.frozen_replay import load_frozen_post_market_plans, replay_frozen_post_market_sequence


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


def test_replay_frozen_post_market_sequence_carries_recent_formal_buy_block(tmp_path) -> None:
    source_path = tmp_path / "daily_events.jsonl"
    source_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "paper_trading_day",
                        "trade_date": "20260421",
                        "current_plan": {
                            "date": "20260421",
                            "buy_orders": [
                                {
                                    "ticker": "300724",
                                    "shares": 100,
                                    "amount": 12000.0,
                                    "score_final": 0.52,
                                    "execution_ratio": 0.3,
                                }
                            ],
                            "watchlist": [
                                {
                                    "ticker": "300724",
                                    "score_c": -0.05,
                                    "score_final": 0.52,
                                    "score_b": 0.43,
                                    "decision": "watch",
                                }
                            ],
                            "portfolio_snapshot": {"cash": 500000.0, "positions": {}},
                            "risk_metrics": {
                                "counts": {"watchlist_count": 1, "buy_order_count": 1},
                                "funnel_diagnostics": {"filters": {"buy_orders": {"filtered_count": 0, "reason_counts": {}, "tickers": [], "selected_tickers": ["300724"]}}},
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "event": "paper_trading_day",
                        "trade_date": "20260422",
                        "current_plan": {
                            "date": "20260422",
                            "buy_orders": [
                                {
                                    "ticker": "300724",
                                    "shares": 100,
                                    "amount": 12000.0,
                                    "score_final": 0.54,
                                    "execution_ratio": 0.3,
                                }
                            ],
                            "watchlist": [
                                {
                                    "ticker": "300724",
                                    "score_c": -0.04,
                                    "score_final": 0.54,
                                    "score_b": 0.45,
                                    "decision": "watch",
                                }
                            ],
                            "portfolio_snapshot": {"cash": 500000.0, "positions": {}},
                            "risk_metrics": {
                                "counts": {"watchlist_count": 1, "buy_order_count": 1},
                                "funnel_diagnostics": {"filters": {"buy_orders": {"filtered_count": 0, "reason_counts": {}, "tickers": [], "selected_tickers": ["300724"]}}},
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    plans = replay_frozen_post_market_sequence(
        source_path,
        target_mode="short_trade_only",
        base_model_name="gpt-4.1",
        base_model_provider="OpenAI",
    )

    assert [order.ticker for order in plans["20260421"].buy_orders] == ["300724"]
    assert plans["20260422"].buy_orders == []
    assert plans["20260422"].risk_metrics["funnel_diagnostics"]["filters"]["buy_orders"]["reason_counts"] == {"blocked_by_exit_cooldown": 1}
    assert plans["20260422"].risk_metrics["funnel_diagnostics"]["filters"]["buy_orders"]["tickers"][0]["trigger_reason"] == "recent_formal_buy_cooldown"


def test_replay_frozen_post_market_sequence_strips_stale_buy_order_filter_summary(tmp_path) -> None:
    source_path = tmp_path / "daily_events.jsonl"
    source_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20260421",
                "current_plan": {
                    "date": "20260421",
                    "buy_orders": [],
                    "watchlist": [],
                    "portfolio_snapshot": {"cash": 500000.0, "positions": {}},
                    "risk_metrics": {
                        "counts": {"watchlist_count": 0, "buy_order_count": 0},
                        "funnel_diagnostics": {
                            "filters": {
                                "buy_orders": {
                                    "filtered_count": 1,
                                    "reason_counts": {"blocked_by_exit_cooldown": 1},
                                    "tickers": [{"ticker": "300724", "reason": "blocked_by_exit_cooldown", "trigger_reason": "recent_formal_buy_cooldown"}],
                                    "selected_tickers": [],
                                }
                            }
                        },
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    plans = replay_frozen_post_market_sequence(
        source_path,
        target_mode="short_trade_only",
        base_model_name="gpt-4.1",
        base_model_provider="OpenAI",
    )

    assert plans["20260421"].risk_metrics["funnel_diagnostics"]["filters"]["buy_orders"] == {
        "filtered_count": 0,
        "reason_counts": {},
        "tickers": [],
        "selected_tickers": [],
    }
