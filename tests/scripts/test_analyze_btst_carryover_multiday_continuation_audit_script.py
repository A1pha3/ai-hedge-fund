from __future__ import annotations

import json

from scripts.analyze_btst_carryover_multiday_continuation_audit import (
    analyze_btst_carryover_multiday_continuation_audit,
    render_btst_carryover_multiday_continuation_audit_markdown,
)


def test_analyze_btst_carryover_multiday_continuation_audit_recommends_t2_bias(monkeypatch, tmp_path):
    selected_report = tmp_path / "paper_trading_selected" / "selection_artifacts" / "2026-04-09"
    rejected_report = tmp_path / "paper_trading_rejected" / "selection_artifacts" / "2026-03-30"
    selected_report.mkdir(parents=True)
    rejected_report.mkdir(parents=True)

    selected_snapshot = {
        "trade_date": "2026-04-09",
        "selection_targets": {
            "002001": {
                "short_trade": {
                    "decision": "selected",
                    "score_target": 0.4493,
                    "effective_select_threshold": 0.45,
                    "selected_score_tolerance": 0.001,
                    "candidate_source": "catalyst_theme",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "explainability_payload": {
                        "historical_prior": {
                            "execution_quality_label": "close_continuation",
                            "entry_timing_bias": "confirm_then_hold",
                            "sample_count": 2,
                            "evaluable_count": 2,
                            "next_high_hit_threshold": 0.02,
                            "next_close_positive_rate": 1.0,
                            "recent_examples": [
                                {
                                    "trade_date": "2026-03-27",
                                    "ticker": "002001",
                                    "candidate_source": "layer_c_watchlist",
                                }
                            ],
                        },
                        "replay_context": {
                            "candidate_reason_codes": ["catalyst_theme_short_trade_carryover_candidate"],
                        },
                        "upstream_shadow_catalyst_relief": {
                            "applied": True,
                            "reason": "catalyst_theme_short_trade_carryover",
                            "effective_select_threshold": 0.45,
                            "selected_score_tolerance": 0.001,
                        },
                    },
                }
            }
        },
    }
    rejected_snapshot = {
        "trade_date": "2026-03-30",
        "selection_targets": {
            "688498": {
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.3626,
                    "candidate_source": "catalyst_theme",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "explainability_payload": {
                        "historical_prior": {
                            "execution_quality_label": "close_continuation",
                            "entry_timing_bias": "confirm_then_hold",
                            "sample_count": 1,
                            "evaluable_count": 1,
                            "next_close_positive_rate": 1.0,
                            "same_ticker_sample_count": 1,
                            "same_family_sample_count": 74,
                            "same_family_source_sample_count": 0,
                            "same_family_source_score_catalyst_sample_count": 0,
                            "same_source_score_sample_count": 0,
                        },
                        "replay_context": {
                            "candidate_reason_codes": ["catalyst_theme_short_trade_carryover_candidate"],
                        },
                        "upstream_shadow_catalyst_relief": {
                            "applied": False,
                            "reason": "catalyst_theme_short_trade_carryover",
                        },
                    },
                }
            }
        },
    }
    (selected_report / "selection_snapshot.json").write_text(json.dumps(selected_snapshot, ensure_ascii=False) + "\n", encoding="utf-8")
    (rejected_report / "selection_snapshot.json").write_text(json.dumps(rejected_snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    def _fake_extract_holding_outcome(ticker: str, trade_date: str, price_cache):
        if ticker == "002001":
            return {
                "data_status": "ok",
                "cycle_status": "t_plus_4_closed",
                "next_high_return": 0.0537,
                "next_close_return": 0.045,
                "next_open_to_close_return": 0.0393,
                "t_plus_2_close_return": 0.0029,
                "t_plus_3_close_return": -0.0032,
                "t_plus_4_close_return": 0.0041,
            }
        return {
            "data_status": "ok",
            "cycle_status": "t_plus_4_closed",
            "next_high_return": -0.0179,
            "next_close_return": -0.0533,
            "next_open_to_close_return": -0.0191,
            "t_plus_2_close_return": -0.0019,
            "t_plus_3_close_return": -0.0264,
            "t_plus_4_close_return": 0.0217,
        }

    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_multiday_continuation_audit._extract_holding_outcome",
        _fake_extract_holding_outcome,
    )

    analysis = analyze_btst_carryover_multiday_continuation_audit(tmp_path)
    markdown = render_btst_carryover_multiday_continuation_audit_markdown(analysis)

    assert analysis["selected_ticker"] == "002001"
    assert analysis["selected_current_data_status"] == "ok"
    assert analysis["selected_current_cycle_status"] == "t_plus_4_closed"
    assert analysis["selected_current_next_close_return"] == 0.045
    assert analysis["selected_current_t_plus_2_close_return"] == 0.0029
    assert analysis["policy_checks"]["selected_path_t2_bias_only"] is True
    assert analysis["policy_checks"]["broad_family_only_multiday_unsupported"] is True
    assert analysis["policy_checks"]["open_selected_case_count"] == 0
    assert analysis["broad_family_only_summary"]["next_close_positive_rate"] == 0.0
    assert "T+2 bias" in analysis["recommendation"]
    assert "broad_family_only" in analysis["recommendation"]
    assert "002001" in markdown
    assert "688498" in markdown


def test_analyze_btst_carryover_multiday_continuation_audit_finds_legacy_selected_snapshot(monkeypatch, tmp_path):
    selected_report = tmp_path / "paper_trading_selected" / "selection_artifacts" / "2026-04-22"
    selected_report.mkdir(parents=True)
    (selected_report / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-22",
                "target_context": [
                    {
                        "ticker": "688313",
                        "short_trade": {"decision": "selected"},
                        "replay_context": {
                            "historical_prior": {
                                "execution_quality_label": "close_continuation",
                                "entry_timing_bias": "confirm_then_hold",
                            }
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_multiday_continuation_audit.analyze_btst_selected_outcome_proof",
        lambda snapshot_path: {
            "ticker": "688313",
            "trade_date": "2026-04-22",
            "preferred_entry_mode": "confirm_then_hold_breakout",
            "current_contract_status": "open",
            "historical_prior": {
                "execution_quality_label": "close_continuation",
                "entry_timing_bias": "confirm_then_hold",
            },
            "summary": {},
            "evidence_rows": [],
        },
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_multiday_continuation_audit._extract_holding_outcome",
        lambda ticker, trade_date, price_cache: {
            "data_status": "ok",
            "cycle_status": "missing_next_day",
            "next_trade_date": None,
            "next_close_return": None,
            "t_plus_2_close_return": None,
            "trade_anchor_date": trade_date,
            "trade_date_was_non_trading": False,
        },
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_multiday_continuation_audit._build_supportive_cohort_rows",
        lambda reports_root: [],
    )

    analysis = analyze_btst_carryover_multiday_continuation_audit(tmp_path)

    assert analysis["selected_ticker"] == "688313"
    assert analysis["selected_snapshot_path"].endswith("selection_artifacts/2026-04-22/selection_snapshot.json")
