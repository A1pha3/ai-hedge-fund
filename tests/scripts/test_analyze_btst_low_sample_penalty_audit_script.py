from __future__ import annotations

import json

from scripts.analyze_btst_low_sample_penalty_audit import analyze_btst_low_sample_penalty_audit, render_btst_low_sample_penalty_audit_markdown


def test_analyze_btst_low_sample_penalty_audit_flags_penalty_as_protective(monkeypatch, tmp_path):
    report_dir = tmp_path / "report" / "selection_artifacts" / "2026-03-30"
    report_dir.mkdir(parents=True)

    payload = {
        "selection_targets": {
            "688498": {
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.3626,
                    "effective_near_miss_threshold": 0.46,
                    "effective_select_threshold": 0.58,
                    "candidate_source": "catalyst_theme",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "negative_tags": ["catalyst_theme_short_trade_carryover_not_triggered"],
                    "rejection_reasons": ["score_short_below_threshold"],
                    "metrics_payload": {
                        "stale_trend_repair_penalty": 0.47,
                        "extension_without_room_penalty": 0.45,
                        "total_negative_contribution": 0.0924,
                        "weighted_negative_contributions": {
                            "stale_trend_repair_penalty": 0.0564,
                            "extension_without_room_penalty": 0.036,
                        },
                    },
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
                            "short_trade_catalyst_relief": {"reason": "catalyst_theme_short_trade_carryover"},
                        },
                    },
                }
            }
        }
    }
    (report_dir / "selection_snapshot.json").write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "scripts.analyze_btst_low_sample_penalty_audit.extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "next_close_return": -0.0533,
            "t_plus_2_close_return": -0.0019,
        },
    )

    analysis = analyze_btst_low_sample_penalty_audit(tmp_path)
    markdown = render_btst_low_sample_penalty_audit_markdown(analysis)

    assert analysis["audited_case_count"] == 1
    assert analysis["rows"][0]["peer_evidence_status"] == "broad_family_only"
    assert analysis["rows"][0]["counterfactual_score_without_stale_extension"] == 0.455
    assert analysis["closed_cycle_summary"]["t_plus_2_close_positive_rate"] == 0.0
    assert "保护胜率" in analysis["recommendation"]
    assert "counterfactual_score_without_stale_extension=0.455" in markdown
