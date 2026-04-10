from __future__ import annotations

from scripts.analyze_watchlist_suppression import analyze_variant


def test_analyze_variant_counts_watchlist_buy_orders_and_missing_buckets() -> None:
    baseline_rows = {
        "20260325": {
            "current_plan": {
                "funnel_diagnostics": {
                    "filters": {
                        "layer_b": {
                            "selected_tickers": ["000001"],
                        }
                    }
                }
            }
        }
    }
    variant_rows = {
        "20260325": {
            "current_plan": {
                "counts": {"watchlist_score_threshold": 0.25},
                "funnel_diagnostics": {
                    "filters": {
                        "layer_b": {
                            "selected_tickers": ["000001", "000002", "000003", "000004"],
                        },
                        "watchlist": {
                            "tickers": [
                                {
                                    "ticker": "000002",
                                    "reasons": ["score_c_below_threshold"],
                                    "bc_conflict": "b_strong_buy_c_negative",
                                    "decision": "watch",
                                    "score_b": 0.36,
                                    "score_c": 0.10,
                                    "score_final": 0.20,
                                }
                            ]
                        },
                        "buy_orders": {
                            "tickers": [
                                {
                                    "ticker": "000003",
                                    "reason": "position_limit",
                                    "decision": "buy_order_blocked",
                                    "score_b": 0.40,
                                    "score_c": 0.20,
                                    "score_final": 0.28,
                                }
                            ]
                        },
                    }
                },
            }
        }
    }

    summary = analyze_variant(baseline_rows, variant_rows, "probe")

    assert summary["extra_layer_b_total"] == 3
    assert summary["blocked_at_watchlist"] == 1
    assert summary["blocked_at_buy_orders"] == 1
    assert summary["missing_from_filters"] == 1
    assert summary["ticker_counts"]["000004"] == 1
    assert summary["bc_conflict_counts"] == {"b_strong_buy_c_negative": 1}
    assert summary["reason_counts"][("watchlist", ("score_c_below_threshold",))] == 1
    assert summary["reason_counts"][("buy_orders", ("position_limit",))] == 1
    assert summary["reason_counts"][("missing_from_filters", tuple())] == 1


def test_analyze_variant_records_required_score_c_and_gap() -> None:
    baseline_rows = {
        "20260326": {
            "current_plan": {
                "funnel_diagnostics": {
                    "filters": {
                        "layer_b": {
                            "selected_tickers": [],
                        }
                    }
                }
            }
        }
    }
    variant_rows = {
        "20260326": {
            "current_plan": {
                "counts": {"watchlist_score_threshold": 0.25},
                "funnel_diagnostics": {
                    "filters": {
                        "layer_b": {"selected_tickers": ["300001"]},
                        "watchlist": {
                            "tickers": [
                                {
                                    "ticker": "300001",
                                    "reasons": ["weak_c_signal"],
                                    "decision": "watch",
                                    "score_b": 0.30,
                                    "score_c": 0.05,
                                    "score_final": 0.15,
                                }
                            ]
                        },
                    }
                },
            }
        }
    }

    summary = analyze_variant(baseline_rows, variant_rows, "probe")

    detail = summary["details"][0]
    assert detail["required_score_c"] == 0.2167
    assert detail["score_c_gap"] == -0.1667
    assert summary["score_c_gap_values"] == [-0.16666666666666669]
