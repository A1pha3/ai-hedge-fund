from __future__ import annotations

import json

from scripts.analyze_btst_carryover_horizon_validation import (
    analyze_btst_carryover_horizon_validation,
    render_btst_carryover_horizon_validation_markdown,
)


def test_analyze_btst_carryover_horizon_validation_separates_selected_from_rejected(monkeypatch, tmp_path):
    report_a = tmp_path / "report_a" / "selection_artifacts" / "2026-03-30"
    report_b = tmp_path / "report_b" / "selection_artifacts" / "2026-04-09"
    report_a.mkdir(parents=True)
    report_b.mkdir(parents=True)

    def _write_snapshot(path, ticker, decision, score_target, relief_applied, evaluable_count):
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
                            "historical_prior": {
                                "execution_quality_label": "close_continuation",
                                "entry_timing_bias": "confirm_then_hold",
                                "sample_count": evaluable_count,
                                "evaluable_count": evaluable_count,
                                "next_close_positive_rate": 1.0,
                            },
                            "replay_context": {
                                "candidate_reason_codes": ["catalyst_theme_short_trade_carryover_candidate"],
                                "short_trade_catalyst_relief": {"reason": "catalyst_theme_short_trade_carryover"},
                            },
                            "upstream_shadow_catalyst_relief": {
                                "applied": relief_applied,
                                "reason": "catalyst_theme_short_trade_carryover",
                                "effective_select_threshold": 0.45 if relief_applied else 0.58,
                                "selected_score_tolerance": 0.001 if relief_applied else 0.0,
                            },
                        },
                    }
                }
            }
        }
        (path / "selection_snapshot.json").write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    _write_snapshot(report_a, "688498", "rejected", 0.3626, False, 1)
    _write_snapshot(report_b, "002001", "selected", 0.4493, True, 2)

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
            "t_plus_3_close_return": -0.012,
            "t_plus_4_close_return": -0.02,
        }

    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_horizon_validation._extract_holding_outcome",
        _fake_extract_holding_outcome,
    )

    analysis = analyze_btst_carryover_horizon_validation(tmp_path)
    markdown = render_btst_carryover_horizon_validation_markdown(analysis)

    assert analysis["supportive_case_count"] == 2
    assert analysis["selected_or_relief_summary"]["t_plus_2_close_positive_rate"] == 1.0
    assert analysis["selected_or_relief_summary"]["t_plus_3_close_positive_rate"] == 0.0
    assert analysis["rejected_supportive_summary"]["t_plus_2_close_positive_rate"] == 0.0
    assert "T+2" in markdown or "t_plus_2" in markdown
    assert "002001" in markdown
    assert "688498" in markdown
