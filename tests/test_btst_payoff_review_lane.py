from __future__ import annotations

from src.paper_trading._btst_reporting.payoff_review_lane import (
    build_payoff_review_entries,
)


def test_build_payoff_review_entries_ranks_by_proxy_prior_and_reliability(monkeypatch):
    """Fallback behavior when 5D priors are missing (v1 proxy)."""

    monkeypatch.setenv("BTST_PAYOFF_REVIEW_LANE_MODE", "report")
    entries = [
        {
            "ticker": "300001",
            "decision": "near_miss",
            "candidate_source": "short_trade_boundary",
            "historical_prior": {
                "next_high_hit_rate_at_threshold": 0.20,
                "evaluable_count": 8,
                "execution_quality_label": "close_continuation",
            },
        },
        {
            "ticker": "300002",
            "decision": "selected",
            "candidate_source": "short_trade_boundary",
            "historical_prior": {
                "next_high_hit_rate_at_threshold": 0.40,
                "evaluable_count": 1,
                "execution_quality_label": "close_continuation",
            },
        },
    ]

    lane = build_payoff_review_entries(selected_entries=[entries[1]], near_miss_entries=[entries[0]])

    assert [row["ticker"] for row in lane] == ["300001", "300002"]
    assert lane[0]["review_semantics"] == "review_only"
    assert lane[0]["payoff_review_lane_rank"] == 1
    assert 0.0 <= lane[0]["payoff_review_lane_score"] <= 1.0
    assert lane[0]["payoff_review_lane_components"]["scoring_version"] == "v1_next_high_proxy"


def test_build_payoff_review_entries_dedupes_by_ticker_preferring_selected(monkeypatch):
    monkeypatch.setenv("BTST_PAYOFF_REVIEW_LANE_MODE", "report")
    selected = {
        "ticker": "300003",
        "decision": "selected",
        "candidate_source": "short_trade_boundary",
        "historical_prior": {
            "next_high_hit_rate_at_threshold": 0.10,
            "evaluable_count": 3,
        },
    }
    near_miss = {
        "ticker": "300003",
        "decision": "near_miss",
        "candidate_source": "short_trade_boundary",
        "historical_prior": {
            "next_high_hit_rate_at_threshold": 0.90,
            "evaluable_count": 12,
        },
    }

    lane = build_payoff_review_entries(selected_entries=[selected], near_miss_entries=[near_miss])

    assert len(lane) == 1
    assert lane[0]["ticker"] == "300003"
    assert lane[0]["decision"] == "selected"


def test_build_payoff_review_entries_prefers_five_day_priors_when_available(monkeypatch):
    monkeypatch.setenv("BTST_PAYOFF_REVIEW_LANE_MODE", "report")

    # Even though 300102 has a higher next-day proxy hit-rate, 300101 should win on 5D/+15% priors.
    lane = build_payoff_review_entries(
        selected_entries=[],
        near_miss_entries=[
            {
                "ticker": "300101",
                "decision": "near_miss",
                "candidate_source": "short_trade_boundary",
                "historical_prior": {
                    "next_high_hit_rate_at_threshold": 0.10,
                    "evaluable_count": 10,
                    "execution_quality_label": "close_continuation",
                    "five_day_evaluable_count": 6,
                    "five_day_hit_rate_at_15pct": 0.50,
                    "five_day_mean_max_future_high_return_2_5d": 0.18,
                },
            },
            {
                "ticker": "300102",
                "decision": "near_miss",
                "candidate_source": "short_trade_boundary",
                "historical_prior": {
                    "next_high_hit_rate_at_threshold": 0.60,
                    "evaluable_count": 10,
                    "execution_quality_label": "close_continuation",
                    "five_day_evaluable_count": 6,
                    "five_day_hit_rate_at_15pct": 0.10,
                    "five_day_mean_max_future_high_return_2_5d": 0.05,
                },
            },
        ],
        max_entries=5,
    )

    assert [row["ticker"] for row in lane][:2] == ["300101", "300102"]
    assert lane[0]["payoff_review_lane_components"]["scoring_version"] == "v2_five_day"


def test_build_payoff_review_entries_returns_empty_when_mode_off(monkeypatch):
    monkeypatch.delenv("BTST_PAYOFF_REVIEW_LANE_MODE", raising=False)
    lane = build_payoff_review_entries(selected_entries=[{"ticker": "300004"}], near_miss_entries=[])
    assert lane == []
