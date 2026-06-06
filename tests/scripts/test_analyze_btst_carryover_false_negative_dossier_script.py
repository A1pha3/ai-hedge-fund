from __future__ import annotations

import json

from scripts.analyze_btst_carryover_false_negative_dossier import analyze_btst_carryover_false_negative_dossier


def test_analyze_btst_carryover_false_negative_dossier_profiles_penalty_dominated_cases(monkeypatch, tmp_path):
    report_a = tmp_path / "report_a" / "selection_artifacts" / "2026-03-30"
    report_b = tmp_path / "report_b" / "selection_artifacts" / "2026-04-09"
    report_a.mkdir(parents=True)
    report_b.mkdir(parents=True)

    snapshot_a = {
        "selection_targets": {
            "688498": {
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.3626,
                    "candidate_source": "catalyst_theme",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "top_reasons": ["trend_acceleration=0.77", "confirmed_breakout", "stale_trend_repair_penalty=0.47"],
                        "metrics_payload": {
                            "stale_trend_repair_penalty": 0.47,
                            "extension_without_room_penalty": 0.45,
                            "carryover_evidence_deficiency": {"evidence_deficient": True},
                        },
                        "explainability_payload": {
                            "historical_prior": {
                                "execution_quality_label": "close_continuation",
                                "entry_timing_bias": "confirm_then_hold",
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
                        "replay_context": {
                            "candidate_reason_codes": ["catalyst_theme_short_trade_carryover_candidate"],
                            "short_trade_catalyst_relief": {"reason": "catalyst_theme_short_trade_carryover"},
                        },
                    },
                }
            }
        }
    }
    snapshot_b = {
        "selection_targets": {
            "688498": {
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.3625,
                    "candidate_source": "catalyst_theme",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "top_reasons": ["trend_acceleration=0.77", "confirmed_breakout", "stale_trend_repair_penalty=0.47"],
                        "metrics_payload": {
                            "stale_trend_repair_penalty": 0.47,
                            "extension_without_room_penalty": 0.45,
                            "carryover_evidence_deficiency": {"evidence_deficient": True},
                        },
                        "explainability_payload": {
                            "historical_prior": {
                                "execution_quality_label": "close_continuation",
                                "entry_timing_bias": "confirm_then_hold",
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
                        "replay_context": {
                            "candidate_reason_codes": ["catalyst_theme_short_trade_carryover_candidate"],
                            "short_trade_catalyst_relief": {"reason": "catalyst_theme_short_trade_carryover"},
                        },
                    },
                }
            }
        }
    }
    (report_a / "selection_snapshot.json").write_text(json.dumps(snapshot_a, ensure_ascii=False) + "\n", encoding="utf-8")
    (report_b / "selection_snapshot.json").write_text(json.dumps(snapshot_b, ensure_ascii=False) + "\n", encoding="utf-8")

    def _fake_extract_btst_price_outcome(ticker: str, trade_date: str, price_cache):
        if trade_date == "2026-03-30":
            return {
                "next_close_return": -0.0533,
                "t_plus_2_close_return": -0.0019,
            }
        return {
            "next_close_return": None,
            "t_plus_2_close_return": None,
        }

    monkeypatch.setattr("scripts.analyze_btst_carryover_false_negative_dossier.extract_btst_price_outcome", _fake_extract_btst_price_outcome)

    analysis = analyze_btst_carryover_false_negative_dossier(tmp_path)

    assert analysis["false_negative_count"] == 2
    assert analysis["decision_counts"] == {"rejected": 2}
    assert analysis["top_reason_counts"]["stale_trend_repair_penalty=0.47"] == 2
    assert analysis["peer_status_counts"] == {"broad_family_only": 2}
    assert analysis["closed_cycle_peer_status_counts"] == {"broad_family_only": 1}
    assert analysis["evidence_deficient_count"] == 2
    assert analysis["rows"][0]["peer_evidence_status"] == "broad_family_only"
    assert analysis["rows"][0]["carryover_evidence_deficient"] is True
    assert analysis["next_close_return_summary"]["mean"] == -0.0533
    assert analysis["stale_trend_repair_penalty_summary"]["mean"] == 0.47
    assert "broad-family-only / evidence-deficient" in analysis["recommendation"]
