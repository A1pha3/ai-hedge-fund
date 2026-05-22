from __future__ import annotations

from scripts.btst_round1_factor_mining_helpers import (
    build_round1_research_row,
    classify_round1_event_prototype,
    compute_round1_factor_family_scores,
    compute_round1_interaction_scores,
    summarize_round1_row_gates,
)


def test_classify_round1_event_prototype_prefers_breakout_ignition_when_breakout_and_volume_are_both_strong() -> None:
    row = {
        "breakout_freshness": 0.66,
        "volume_expansion_quality": 0.70,
        "trend_acceleration": 0.42,
        "close_strength": 0.62,
    }

    assert classify_round1_event_prototype(row) == "breakout_ignition"


def test_compute_round1_factor_family_scores_returns_three_named_families() -> None:
    row = {
        "breakout_freshness": 0.60,
        "trend_acceleration": 0.58,
        "close_strength": 0.64,
        "volume_expansion_quality": 0.67,
        "t0_tail_strength": 0.61,
        "trend_continuation": 0.62,
    }

    scores = compute_round1_factor_family_scores(row)

    assert set(scores) == {"trend_family", "breakout_family", "volume_quality_family"}
    assert scores["trend_family"] == 0.6133
    assert scores["breakout_family"] == 0.6367
    assert scores["volume_quality_family"] == 0.64


def test_compute_round1_interaction_scores_returns_both_named_interactions() -> None:
    row = {
        "trend_acceleration": 0.58,
        "close_strength": 0.64,
        "breakout_freshness": 0.60,
        "volume_expansion_quality": 0.67,
    }

    scores = compute_round1_interaction_scores(row)

    assert scores == {
        "trend_x_close_strength": 0.3712,
        "breakout_x_volume_quality": 0.402,
    }


def test_compute_round1_factor_family_scores_returns_none_for_empty_factor_rows() -> None:
    scores = compute_round1_factor_family_scores({})

    assert scores == {
        "trend_family": None,
        "breakout_family": None,
        "volume_quality_family": None,
    }


def test_summarize_round1_row_gates_marks_tradeable_closed_cycle_rows() -> None:
    row = {
        "cycle_status": "closed_cycle",
        "next_open_return": 0.02,
        "future_high_hit_15pct_2_5d": True,
    }

    gates = summarize_round1_row_gates(row)

    assert gates == {
        "alpha_observable": True,
        "beta_tradeable": True,
        "gamma_closed_cycle": True,
    }


def test_build_round1_research_row_merges_evaluation_price_outcome_and_derived_scores() -> None:
    evaluation = {
        "candidate_source": "short_trade_boundary",
        "short_trade": {
            "decision": "selected",
            "explainability_payload": {
                "breakout_freshness": 0.58,
                "trend_acceleration": 0.64,
                "volume_expansion_quality": 0.62,
                "close_strength": 0.67,
                "t0_tail_strength": 0.61,
                "trend_continuation": 0.66,
            },
        },
    }
    price_outcome = {
        "cycle_status": "closed_cycle",
        "future_high_hit_15pct_2_5d": True,
        "max_future_high_return_2_5d": 0.18,
        "time_to_hit_15pct": 2,
        "next_open_return": 0.01,
    }

    row = build_round1_research_row(
        ticker="001309",
        trade_date="2026-03-24",
        report_dir_name="paper_trading_window_20260323_20260326_round1",
        evaluation=evaluation,
        price_outcome=price_outcome,
    )

    assert row["ticker"] == "001309"
    assert row["candidate_source"] == "short_trade_boundary"
    assert row["event_prototype"] == "breakout_ignition"
    assert row["trend_family"] == 0.6567
    assert row["breakout_x_volume_quality"] == 0.3596
    assert row["alpha_observable"] is True
    assert row["beta_tradeable"] is True
    assert row["gamma_closed_cycle"] is True


def test_build_round1_research_row_handles_watchlist_rows_without_factor_payload() -> None:
    evaluation = {
        "candidate_source": "layer_c_watchlist",
        "short_trade": {
            "decision": "blocked",
            "explainability_payload": {},
        },
    }
    price_outcome = {
        "cycle_status": "closed_cycle",
        "future_high_hit_15pct_2_5d": False,
        "max_future_high_return_2_5d": 0.03,
        "next_open_return": 0.01,
    }

    row = build_round1_research_row(
        ticker="601600",
        trade_date="2026-02-02",
        report_dir_name="paper_trading_window_demo",
        evaluation=evaluation,
        price_outcome=price_outcome,
    )

    assert row["event_prototype"] == "unclassified"
    assert row["trend_family"] is None
    assert row["breakout_family"] is None
    assert row["volume_quality_family"] is None
