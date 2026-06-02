from __future__ import annotations

from src.paper_trading._btst_reporting.payoff_review_lane import build_payoff_review_entries


def test_build_payoff_review_entries_ranks_by_proxy_prior_and_reliability(monkeypatch):
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

    lane = build_payoff_review_entries(
        selected_entries=[entries[1]], near_miss_entries=[entries[0]]
    )

    assert [row["ticker"] for row in lane] == ["300001", "300002"]
    assert lane[0]["review_semantics"] == "review_only"
    assert lane[0]["payoff_review_lane_rank"] == 1
    assert 0.0 <= lane[0]["payoff_review_lane_score"] <= 1.0


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


def test_build_payoff_review_entries_returns_empty_when_mode_off(monkeypatch):
    monkeypatch.delenv("BTST_PAYOFF_REVIEW_LANE_MODE", raising=False)
    lane = build_payoff_review_entries(selected_entries=[{"ticker": "300004"}], near_miss_entries=[])
    assert lane == []
