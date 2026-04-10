from __future__ import annotations

import json

from scripts.analyze_btst_carryover_selected_cohort import _extract_case_row, analyze_btst_carryover_selected_cohort, render_btst_carryover_selected_cohort_markdown


def test_analyze_btst_carryover_selected_cohort_deduplicates_and_ranks_expansion_candidates(monkeypatch, tmp_path):
    report_a = tmp_path / "report_a" / "selection_artifacts" / "2026-04-09"
    report_b = tmp_path / "report_b" / "selection_artifacts" / "2026-04-09"
    report_c = tmp_path / "report_c" / "selection_artifacts" / "2026-03-30"
    report_a.mkdir(parents=True)
    report_b.mkdir(parents=True)
    report_c.mkdir(parents=True)

    def _write_snapshot(path, score_target, decision, evaluable_count, ticker="688498", relief_applied=False):
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
                                "applied_scope": "same_ticker",
                                "sample_count": evaluable_count,
                                "evaluable_count": evaluable_count,
                                "next_close_positive_rate": 1.0,
                                "next_open_to_close_return_mean": 0.01,
                                "same_ticker_sample_count": evaluable_count,
                                "same_family_sample_count": 74 if ticker == "688498" else evaluable_count,
                                "same_family_source_sample_count": 0,
                                "same_family_source_score_catalyst_sample_count": 0,
                                "same_source_score_sample_count": 0,
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

    _write_snapshot(report_a, 0.3625, "rejected", 1)
    _write_snapshot(report_b, 0.3812, "near_miss", 1)
    _write_snapshot(report_c, 0.4493, "selected", 2, ticker="002001", relief_applied=True)

    def _fake_extract_btst_price_outcome(ticker: str, trade_date: str, price_cache):
        if ticker == "002001":
            return {
                "next_close_return": 0.045,
                "next_high_return": 0.0537,
                "t_plus_2_close_return": 0.0029,
            }
        return {
            "next_close_return": -0.0533,
            "next_high_return": -0.0179,
            "t_plus_2_close_return": -0.0019,
        }

    monkeypatch.setattr("scripts.analyze_btst_carryover_selected_cohort.extract_btst_price_outcome", _fake_extract_btst_price_outcome)

    analysis = analyze_btst_carryover_selected_cohort(tmp_path)
    markdown = render_btst_carryover_selected_cohort_markdown(analysis)

    assert analysis["raw_case_count"] == 3
    assert analysis["unique_case_count"] == 2
    assert analysis["relief_applied_count"] == 1
    assert analysis["supportive_case_count"] == 2
    assert analysis["applied_relief_rows"][0]["ticker"] == "002001"
    assert analysis["top_expansion_candidates"][0]["ticker"] == "688498"
    assert analysis["top_expansion_candidates"][0]["decision"] == "near_miss"
    assert analysis["top_expansion_candidates"][0]["peer_evidence_status"] == "broad_family_only"
    assert analysis["top_expansion_candidates"][0]["same_family_sample_count"] == 74
    assert "688498" in markdown
    assert "peer_evidence_status=broad_family_only" in markdown
    assert "002001" in markdown


def test_extract_case_row_returns_none_without_carryover_relief_signal(tmp_path):
    snapshot_path = tmp_path / "report" / "selection_artifacts" / "2026-04-09" / "selection_snapshot.json"
    snapshot_path.parent.mkdir(parents=True)

    row = _extract_case_row(
        snapshot_path,
        "688498",
        {
            "short_trade": {
                "decision": "rejected",
                "candidate_source": "catalyst_theme",
                "explainability_payload": {"replay_context": {"candidate_reason_codes": ["ordinary_candidate"]}},
            }
        },
    )

    assert row is None


def test_extract_case_row_uses_threshold_fallback_chain(tmp_path):
    snapshot_path = tmp_path / "report" / "selection_artifacts" / "2026-04-09" / "selection_snapshot.json"
    snapshot_path.parent.mkdir(parents=True)

    row = _extract_case_row(
        snapshot_path,
        "002001",
        {
            "short_trade": {
                "decision": "selected",
                "score_target": 0.44934,
                "candidate_source": "catalyst_theme",
                "preferred_entry_mode": "confirm_then_hold_breakout",
                "metrics_payload": {"thresholds": {"effective_select_threshold": 0.46, "selected_score_tolerance": 0.0005}},
                "explainability_payload": {
                    "historical_prior": {
                        "execution_quality_label": "close_continuation",
                        "entry_timing_bias": "confirm_then_hold",
                        "sample_count": 3,
                        "evaluable_count": 3,
                    },
                    "replay_context": {"candidate_reason_codes": ["catalyst_theme_short_trade_carryover_candidate"]},
                    "upstream_shadow_catalyst_relief": {
                        "applied": True,
                        "reason": "catalyst_theme_short_trade_carryover",
                    },
                },
            }
        },
    )

    assert row is not None
    assert row["trade_date"] == "2026-04-09"
    assert row["effective_select_threshold"] == 0.46
    assert row["selected_score_tolerance"] == 0.0005
    assert row["gap_to_selected"] == 0.0107
    assert row["selected_within_tolerance"] is False
