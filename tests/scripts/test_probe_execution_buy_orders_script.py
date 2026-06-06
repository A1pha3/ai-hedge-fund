from __future__ import annotations

import json

import pytest

from scripts.probe_execution_buy_orders import probe_execution_buy_orders
from src.screening.models import CandidateStock


def test_probe_execution_buy_orders_recomputes_fixed_watchlist_sample(monkeypatch: pytest.MonkeyPatch, tmp_path):
    daily_events_path = tmp_path / "daily_events.jsonl"
    daily_events_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20260305",
                "current_plan": {
                    "date": "20260305",
                    "strategy_weights": {},
                    "logic_scores": {"600988": 0.217},
                    "buy_orders": [],
                    "sell_orders": [],
                    "pending_buy_queue": [],
                    "pending_sell_queue": [],
                    "portfolio_snapshot": {"cash": 100000.0, "positions": {}, "realized_gains": {}},
                    "risk_alerts": [],
                    "risk_metrics": {
                        "funnel_diagnostics": {
                            "filters": {
                                "buy_orders": {
                                    "filtered_count": 1,
                                    "reason_counts": {"position_blocked_score": 1},
                                    "tickers": [
                                        {
                                            "ticker": "600988",
                                            "reason": "position_blocked_score",
                                            "constraint_binding": "score",
                                            "amount": 0.0,
                                            "execution_ratio": 0.0,
                                            "quality_score": 0.5,
                                        }
                                    ],
                                    "selected_tickers": [],
                                }
                            },
                            "blocked_buy_tickers": {},
                        }
                    },
                    "layer_a_count": 0,
                    "layer_b_count": 0,
                    "layer_c_count": 1,
                    "watchlist": [
                        {
                            "ticker": "600988",
                            "score_c": 0.0182,
                            "score_final": 0.217,
                            "score_b": 0.3798,
                            "quality_score": 0.5,
                            "strategy_signals": {},
                            "agent_signals": {},
                            "agent_contribution_summary": {},
                            "bc_conflict": None,
                            "decision": "watch",
                        }
                    ],
                    "selection_artifacts": {},
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.probe_execution_buy_orders.build_candidate_pool",
        lambda trade_date: [CandidateStock(ticker="600988", name="样本", industry_sw="电力设备", avg_volume_20d=10_000_000, market_cap=100, listing_date="19910403")],
    )
    monkeypatch.setattr(
        "scripts.probe_execution_buy_orders.build_watchlist_price_map",
        lambda trade_date, tickers: {"600988": 20.0},
    )

    report = probe_execution_buy_orders(
        daily_events_path,
        trade_date="2026-03-05",
        symbols=["600988"],
        threshold_overrides={"PIPELINE_WATCHLIST_MIN_SCORE": "0.21"},
    )

    assert report["original_buy_order_selected_tickers"] == []
    assert report["recomputed_buy_order_selected_tickers"] == ["600988"]
    assert report["recomputed_buy_order_reason_counts"] == {}
    assert report["missing_candidate_context"] == []
    assert report["probes"][0]["original"]["reason"] == "position_blocked_score"
    assert report["probes"][0]["probed"]["included_in_buy_orders"] is True
    assert report["probes"][0]["probed"]["constraint_binding"] == "single_name"
    assert report["probes"][0]["probed"]["shares"] == 100


def test_probe_execution_buy_orders_requires_trustworthy_price(monkeypatch: pytest.MonkeyPatch, tmp_path):
    daily_events_path = tmp_path / "daily_events.jsonl"
    daily_events_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20260305",
                "current_plan": {
                    "date": "20260305",
                    "strategy_weights": {},
                    "logic_scores": {"600988": 0.217},
                    "buy_orders": [],
                    "sell_orders": [],
                    "pending_buy_queue": [],
                    "pending_sell_queue": [],
                    "portfolio_snapshot": {"cash": 100000.0, "positions": {}, "realized_gains": {}},
                    "risk_alerts": [],
                    "risk_metrics": {"funnel_diagnostics": {"filters": {"buy_orders": {"tickers": []}}, "blocked_buy_tickers": {}}},
                    "layer_a_count": 0,
                    "layer_b_count": 0,
                    "layer_c_count": 1,
                    "watchlist": [
                        {
                            "ticker": "600988",
                            "score_c": 0.0182,
                            "score_final": 0.217,
                            "score_b": 0.3798,
                            "quality_score": 0.5,
                            "strategy_signals": {},
                            "agent_signals": {},
                            "agent_contribution_summary": {},
                            "bc_conflict": None,
                            "decision": "watch",
                        }
                    ],
                    "selection_artifacts": {},
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.probe_execution_buy_orders.build_candidate_pool",
        lambda trade_date: [CandidateStock(ticker="600988", name="样本", industry_sw="电力设备", avg_volume_20d=10_000_000, market_cap=100, listing_date="19910403")],
    )
    monkeypatch.setattr(
        "scripts.probe_execution_buy_orders.build_watchlist_price_map",
        lambda trade_date, tickers: {},
    )

    with pytest.raises(ValueError, match="缺少可信价格"):
        probe_execution_buy_orders(
            daily_events_path,
            trade_date="2026-03-05",
            symbols=["600988"],
            threshold_overrides={"PIPELINE_WATCHLIST_MIN_SCORE": "0.21"},
        )