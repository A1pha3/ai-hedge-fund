from __future__ import annotations

import json

from scripts.analyze_btst_carryover_peer_board import analyze_btst_carryover_peer_board, render_btst_carryover_peer_board_markdown


def test_analyze_btst_carryover_peer_board_classifies_aligned_and_broad_family_candidates(monkeypatch, tmp_path):
    report_a = tmp_path / "report_a" / "selection_artifacts" / "2026-03-30"
    report_b = tmp_path / "report_b" / "selection_artifacts" / "2026-04-09"
    report_c = tmp_path / "report_c" / "selection_artifacts" / "2026-04-09"
    report_a.mkdir(parents=True)
    report_b.mkdir(parents=True)
    report_c.mkdir(parents=True)

    def _write_snapshot(path, ticker, decision, score_target, hist):
        payload = {
            "selection_targets": {
                ticker: {
                    "short_trade": {
                        "decision": decision,
                        "score_target": score_target,
                        "candidate_source": "catalyst_theme",
                        "preferred_entry_mode": "confirm_then_hold_breakout",
                        "top_reasons": ["trend_acceleration=0.77", "confirmed_breakout"],
                        "explainability_payload": {
                            "historical_prior": hist,
                            "replay_context": {
                                "candidate_reason_codes": ["catalyst_theme_short_trade_carryover_candidate"],
                                "short_trade_catalyst_relief": {"reason": "catalyst_theme_short_trade_carryover"},
                            },
                            "upstream_shadow_catalyst_relief": {
                                "applied": decision == "selected",
                                "reason": "catalyst_theme_short_trade_carryover",
                                "effective_select_threshold": 0.45 if decision == "selected" else 0.58,
                                "selected_score_tolerance": 0.001 if decision == "selected" else 0.0,
                            },
                        },
                    }
                }
            }
        }
        (path / "selection_snapshot.json").write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    _write_snapshot(
        report_a,
        "688498",
        "rejected",
        0.3626,
        {
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "applied_scope": "same_ticker",
            "sample_count": 1,
            "evaluable_count": 1,
            "next_close_positive_rate": 1.0,
            "next_open_to_close_return_mean": 0.0172,
            "same_ticker_sample_count": 1,
            "same_family_sample_count": 74,
            "same_family_source_sample_count": 0,
            "same_family_source_score_catalyst_sample_count": 0,
            "same_source_score_sample_count": 0,
        },
    )
    _write_snapshot(
        report_b,
        "002001",
        "selected",
        0.4493,
        {
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "applied_scope": "same_ticker",
            "sample_count": 2,
            "evaluable_count": 2,
            "next_close_positive_rate": 1.0,
            "next_open_to_close_return_mean": 0.0393,
            "same_ticker_sample_count": 2,
            "same_family_sample_count": 5,
            "same_family_source_sample_count": 5,
            "same_family_source_score_catalyst_sample_count": 2,
            "same_source_score_sample_count": 2,
        },
    )
    _write_snapshot(
        report_c,
        "300999",
        "near_miss",
        0.4312,
        {
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "applied_scope": "family_source",
            "sample_count": 1,
            "evaluable_count": 1,
            "next_close_positive_rate": 0.75,
            "next_open_to_close_return_mean": 0.02,
            "same_ticker_sample_count": 1,
            "same_family_sample_count": 12,
            "same_family_source_sample_count": 4,
            "same_family_source_score_catalyst_sample_count": 1,
            "same_source_score_sample_count": 1,
        },
    )

    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_selected_cohort.extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "next_close_return": 0.02 if ticker != "688498" else -0.0533,
            "next_high_return": 0.03 if ticker != "688498" else -0.0179,
            "t_plus_2_close_return": 0.015 if ticker != "688498" else -0.0019,
        },
    )

    analysis = analyze_btst_carryover_peer_board(tmp_path)
    markdown = render_btst_carryover_peer_board_markdown(analysis)

    assert analysis["supportive_case_count"] == 3
    assert analysis["aligned_candidate_count"] == 1
    assert analysis["aligned_candidates"][0]["ticker"] == "300999"
    assert analysis["broad_family_only_count"] == 1
    assert analysis["broad_family_only_candidates"][0]["ticker"] == "688498"
    assert analysis["same_ticker_ready_count"] == 1
    assert analysis["same_ticker_ready_rows"][0]["ticker"] == "002001"
    assert "300999" in markdown
    assert "688498" in markdown
    assert "002001" in markdown
