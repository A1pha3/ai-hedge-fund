from __future__ import annotations

import json
from pathlib import Path

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


def test_load_frozen_post_market_plans_hydrates_sparse_replay_watchlist_signals_from_selection_snapshot(tmp_path) -> None:
    source_path = tmp_path / "daily_events.jsonl"
    selection_dir = tmp_path / "selection_artifacts" / "2026-04-21"
    selection_dir.mkdir(parents=True)
    source_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20260421",
                "current_plan": {
                    "date": "20260421",
                    "watchlist": [],
                    "portfolio_snapshot": {"cash": 500000.0, "positions": {}},
                    "risk_metrics": {},
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "watchlist": [
                    {
                        "ticker": "300054",
                        "score_b": 0.51,
                        "score_c": 0.42,
                        "score_final": 0.58,
                        "quality_score": 0.71,
                        "decision": "watch",
                        "candidate_source": "layer_c_watchlist",
                        "strategy_signals": {},
                        "agent_contribution_summary": {},
                        "metrics": {"canonical_btst_evaluation_bundle": {}},
                    }
                ],
                "rejected_entries": [],
                "supplemental_short_trade_entries": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "funnel_diagnostics": {
                    "filters": {
                        "watchlist": {
                            "tickers": [
                                {
                                    "ticker": "300054",
                                    "strategy_signals": {
                                        "trend": {
                                            "direction": 1,
                                            "confidence": 68.0,
                                            "completeness": 1.0,
                                            "sub_factors": {
                                                "ema_alignment": {"direction": 1, "confidence": 84.0, "completeness": 1.0}
                                            },
                                        }
                                    },
                                    "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.44}},
                                }
                            ]
                        }
                    }
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    plans = load_frozen_post_market_plans(source_path)

    replay_input = plans["20260421"].risk_metrics["frozen_selection_target_replay_input"]
    watchlist_row = replay_input["watchlist"][0]
    assert watchlist_row["ticker"] == "300054"
    assert watchlist_row["strategy_signals"]["trend"]["direction"] == 1


def test_replay_frozen_post_market_sequence_preserves_execution_eligibility_for_original_buy_orders() -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "data/reports/paper_trading_20260522_20260522_live_m2_7_short_trade_only_20260525_plan/daily_events.jsonl"
    )

    plans = replay_frozen_post_market_sequence(
        source_path,
        target_mode="short_trade_only",
        base_model_name="gpt-4.1",
        base_model_provider="OpenAI",
        short_trade_target_profile_name="momentum_optimized",
        short_trade_target_profile_overrides={"select_threshold": 0.5},
        clear_existing_buy_orders=True,
    )

    replayed_plan = plans["20260522"]
    assert replayed_plan.selection_targets["300054"].execution_eligible is True
    assert replayed_plan.selection_targets["002222"].execution_eligible is True
