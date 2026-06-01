from __future__ import annotations

from src.paper_trading.btst_decision_enrichment import (
    build_decision_card,
    build_execution_semantics,
    build_premarket_control_tower,
    build_report_mode,
    build_review_ledger_rows,
    build_veto_owner,
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
            "sample_count": 8,
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
                "ticker": "000000",
                "preferred_entry_mode": "skip",
                "historical_prior": {
                    "applied_scope": "same_ticker",
                    "evaluable_count": 0,
                    "next_close_positive_rate": None,
                    "next_close_payoff_ratio": None,
                    "next_close_expectancy": None,
                    "win_rate_payoff_divergence": False,
                },
            },
            role="formal_selected",
            early_runner_status="exact",
        ),
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


def test_build_execution_semantics_confirmation_review_only_keeps_watch_only_formal_selected_in_watch_queue() -> None:
    semantics = build_execution_semantics(
        report_mode="confirmation_review_only",
        role="formal_selected",
        trade_bias="watch_only",
    )

    assert semantics["execution_state"] == "watching"
    assert semantics["allowed_sections"] == ["watch_queue"]
    assert semantics["formal_buy_allowed"] is False
    assert semantics["max_allowed_state_today"] == "confirmable"


def test_build_execution_semantics_formal_execution_trade_allowed_is_orderable() -> None:
    semantics = build_execution_semantics(
        report_mode="formal_execution",
        role="formal_selected",
        trade_bias="trade_allowed",
    )

    assert semantics["report_mode"] == "formal_execution"
    assert semantics["execution_state"] == "orderable"
    assert semantics["max_allowed_state_today"] == "orderable"
    assert semantics["formal_buy_allowed"] is True
    assert semantics["allowed_sections"] == ["formal_queue"]


def test_build_execution_semantics_uses_veto_owner_as_release_authority_in_confirmation_review_mode() -> None:
    semantics = build_execution_semantics(
        report_mode="confirmation_review_only",
        role="formal_selected",
        trade_bias="trade_allowed",
        control_tower={"reason_codes": ["buy_orders_cleared"]},
    )

    assert semantics["execution_state"] == "confirmable"
    assert semantics["release_authority"] == "market_gate"


def test_build_execution_semantics_uses_execution_desk_as_release_authority_for_formal_confirmation_rows() -> None:
    semantics = build_execution_semantics(
        report_mode="formal_execution",
        role="formal_selected",
        trade_bias="confirmation_only",
    )

    assert semantics["execution_state"] == "confirmable"
    assert semantics["release_authority"] == "execution_desk"


def test_build_report_mode_prefers_current_control_tower_bias_over_legacy_mode() -> None:
    assert (
        build_report_mode(
            {
                "effective_trade_bias": "gate_locked_confirmation_only",
                "report_mode": "formal_execution",
            }
        )
        == "confirmation_review_only"
    )
    assert (
        build_report_mode(
            {
                "effective_trade_bias": "trade_allowed",
                "report_mode": "confirmation_review_only",
            }
        )
        == "formal_execution"
    )
    assert build_report_mode({"report_mode": "formal_execution"}) == "formal_execution"


def test_build_premarket_control_tower_downgrades_trade_allowed_under_hard_market_gate() -> None:
    control_tower = build_premarket_control_tower(
        {
            "trade_bias": "trade_allowed",
            "primary_ticker": "300408",
            "evidence_grade": "A",
            "data_quality": "fresh",
            "risk_posture": "normal",
        },
        {
            "market_state": {
                "regime_gate_level": "crisis",
                "position_scale": 0.75,
            },
            "funnel_diagnostics": {
                "btst_regime_gate_enforcement": {
                    "gate": "halt",
                    "buy_orders_cleared": True,
                    "buy_orders_cleared_count": 1,
                }
            },
        },
    )

    assert control_tower["effective_trade_bias"] == "gate_locked_confirmation_only"
    assert control_tower["reason_codes"] == ["market_gate_downgraded_raw_trade_allowed"]
    assert control_tower["buy_orders_cleared"] is True
    assert control_tower["regime_gate_level"] == "crisis"


def test_build_veto_owner_maps_market_gate_manual_review_and_model_evidence() -> None:
    assert build_veto_owner({"reason_codes": ["buy_orders_cleared"]}) == "market_gate"
    assert build_veto_owner({"reason_codes": ["selection_snapshot_missing"]}) == "manual_review"
    assert build_veto_owner({"reason_codes": ["insufficient_sample"]}) == "model_evidence"


def test_build_review_ledger_rows_control_tower_normalizes_legacy_semantics() -> None:
    ledger_rows = build_review_ledger_rows(
        signal_date="2026-05-28",
        next_trade_date="2026-05-29",
        control_tower={
            "effective_trade_bias": "gate_locked_confirmation_only",
            "report_mode": "formal_execution",
            "reason_codes": ["buy_orders_cleared", "market_gate_requires_confirmation"],
        },
        rows=[
            {
                "ticker": "002222",
                "role": "formal_selected",
                "evidence_grade": "B",
                "data_quality": "fresh",
                "trade_bias": "trade_allowed",
                "risk_posture": "normal",
                "preferred_entry_mode": "confirm_then_hold_breakout",
                "must_confirm": "等待盘中延续确认后再执行，不做开盘无确认追价。",
                "invalidate_if": "若开盘后无法形成延续确认，或快速冲高回落，则取消正式执行。",
                "metrics": {
                    "win_rate": 0.7273,
                    "payoff_ratio": 1.0792,
                    "expectancy": 0.0272,
                },
                "source_row": {
                    "historical_prior": {
                        "sample_count": 10,
                        "evaluable_count": 10,
                        "next_close_positive_count": 7,
                        "next_close_negative_count": 3,
                        "next_close_positive_rate": 0.7,
                    }
                },
            }
        ],
    )

    assert ledger_rows[0]["report_mode"] == "confirmation_review_only"
    assert ledger_rows[0]["execution_state"] == "confirmable"
    assert ledger_rows[0]["max_allowed_state_today"] == "confirmable"
    assert ledger_rows[0]["formal_buy_allowed"] is False
    assert ledger_rows[0]["allowed_sections"] == ["review_queue"]
    assert ledger_rows[0]["veto_owner"] == "market_gate"
    assert ledger_rows[0]["release_authority"] == "market_gate"
    assert ledger_rows[0]["state_reason_codes"] == ["buy_orders_cleared", "market_gate_requires_confirmation"]
    assert ledger_rows[0]["post_close_review_state"] is None
    assert ledger_rows[0]["post_close_review_transition"] is None


def test_build_review_ledger_rows_partial_control_tower_keeps_explicit_formal_execution() -> None:
    ledger_rows = build_review_ledger_rows(
        signal_date="2026-05-28",
        next_trade_date="2026-05-29",
        control_tower={
            "reason_codes": ["buy_orders_cleared"],
        },
        rows=[
            {
                "ticker": "002222",
                "role": "formal_selected",
                "evidence_grade": "B",
                "data_quality": "fresh",
                "trade_bias": "trade_allowed",
                "risk_posture": "normal",
                "preferred_entry_mode": "confirm_then_hold_breakout",
                "must_confirm": "x",
                "invalidate_if": "y",
                "metrics": {},
                "report_mode": "formal_execution",
            }
        ],
    )

    assert ledger_rows[0]["report_mode"] == "formal_execution"
    assert ledger_rows[0]["execution_state"] == "orderable"
    assert ledger_rows[0]["max_allowed_state_today"] == "orderable"
    assert ledger_rows[0]["formal_buy_allowed"] is True
    assert ledger_rows[0]["allowed_sections"] == ["formal_queue"]
    assert ledger_rows[0]["veto_owner"] == "market_gate"
    assert ledger_rows[0]["release_authority"] == "already_released"
    assert ledger_rows[0]["state_reason_codes"] == ["buy_orders_cleared"]
