from __future__ import annotations

from src.paper_trading.btst_decision_enrichment import (
    build_decision_card,
    enrich_btst_row,
    normalize_historical_metric,
)


def test_normalize_historical_metric_prefers_nested_prior() -> None:
    row = {
        "next_close_positive_rate": 0.25,
        "historical_prior": {
            "next_close_positive_rate": 0.72,
        },
    }

    assert normalize_historical_metric(row, "next_close_positive_rate") == 0.72


def test_enrich_btst_row_assigns_b_grade_for_confirmable_positive_payoff() -> None:
    row = {
        "ticker": "002222",
        "name": "物产金轮",
        "preferred_entry_mode": "confirm_then_hold_breakout",
        "score_target": 0.5433,
        "historical_prior": {
            "applied_scope": "same_ticker",
            "evaluable_count": 44,
            "next_close_positive_rate": 0.7273,
            "next_close_payoff_ratio": 1.0792,
            "next_close_expectancy": 0.0272,
            "next_close_profit_factor": 2.8793,
            "win_rate_payoff_divergence": False,
        },
    }

    enriched = enrich_btst_row(row, role="formal_selected", early_runner_status="exact")

    assert enriched["ticker"] == "002222"
    assert enriched["evidence_grade"] == "B"
    assert enriched["data_quality"] == "fresh"
    assert enriched["trade_bias"] == "confirmation_only"
    assert enriched["risk_posture"] == "reduced"
    assert enriched["must_confirm"] == "等待盘中延续确认后再执行，不做开盘无确认追价。"
    assert enriched["invalidate_if"] == "若开盘后无法形成延续确认，或快速冲高回落，则取消正式执行。"
    assert enriched["action_matrix"][0]["scenario"] == "开盘强且延续确认"
    assert enriched["metrics"]["win_rate"] == 0.7273


def test_enrich_btst_row_caps_grade_when_payoff_diverges() -> None:
    row = {
        "ticker": "002916",
        "preferred_entry_mode": "payoff_reconfirmation_only",
        "historical_prior": {
            "applied_scope": "same_ticker",
            "evaluable_count": 8,
            "next_close_positive_rate": 0.75,
            "next_close_payoff_ratio": 0.9217,
            "next_close_expectancy": 0.0248,
            "next_close_profit_factor": 2.7633,
            "win_rate_payoff_divergence": True,
        },
    }

    enriched = enrich_btst_row(row, role="formal_selected", early_runner_status="exact")

    assert enriched["evidence_grade"] == "C"
    assert enriched["data_quality"] == "usable_with_warning"
    assert enriched["trade_bias"] == "confirmation_only"
    assert "胜率和盈亏比/期望背离" in enriched["quality_notes"]
    assert "样本不足 10" in enriched["quality_notes"]


def test_enrich_btst_row_downgrades_stale_early_runner_reference() -> None:
    row = {
        "ticker": "300476",
        "preferred_entry_mode": "confirm_then_hold_breakout",
        "historical_prior": {
            "applied_scope": "same_ticker",
            "evaluable_count": 31,
            "next_close_positive_rate": 0.9355,
            "next_close_payoff_ratio": None,
        },
    }

    enriched = enrich_btst_row(
        row,
        role="early_runner_research",
        early_runner_status="stale_fallback",
    )

    assert enriched["evidence_grade"] == "D"
    assert enriched["data_quality"] == "stale_reference"
    assert enriched["trade_bias"] == "watch_only"
    assert enriched["risk_posture"] == "no_trade"
    assert "early-runner 非当日板" in enriched["quality_notes"]


def test_build_decision_card_selects_first_confirmable_candidate() -> None:
    rows = [
        enrich_btst_row(
            {
                "ticker": "002222",
                "preferred_entry_mode": "confirm_then_hold_breakout",
                "historical_prior": {
                    "applied_scope": "same_ticker",
                    "evaluable_count": 44,
                    "next_close_positive_rate": 0.7273,
                    "next_close_payoff_ratio": 1.0792,
                    "next_close_expectancy": 0.0272,
                    "win_rate_payoff_divergence": False,
                },
            },
            role="formal_selected",
            early_runner_status="exact",
        )
    ]

    card = build_decision_card(
        selected_rows=rows,
        early_runner_status="exact",
        signal_date="2026-05-28",
        next_trade_date="2026-05-29",
    )

    assert card["trade_bias"] == "confirmation_only"
    assert card["primary_ticker"] == "002222"
    assert card["evidence_grade"] == "B"
    assert card["data_quality"] == "fresh"
    assert card["risk_posture"] == "reduced"
