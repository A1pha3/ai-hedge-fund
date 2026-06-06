from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_continuation_merge_candidate_ranking import (
    generate_btst_continuation_merge_candidate_ranking,
    render_btst_continuation_merge_candidate_ranking_markdown,
)
from scripts.generate_btst_default_merge_historical_counterfactual import (
    generate_btst_default_merge_historical_counterfactual,
    render_btst_default_merge_historical_counterfactual_markdown,
)
from scripts.generate_btst_default_merge_strict_counterfactual import (
    generate_btst_default_merge_strict_counterfactual,
    render_btst_default_merge_strict_counterfactual_markdown,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_generate_btst_default_merge_historical_counterfactual_builds_weighted_uplift(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    default_merge_review_path = reports_root / "btst_default_merge_review_latest.json"
    objective_monitor_path = reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json"
    focus_dossier_path = reports_root / "btst_tplus2_candidate_dossier_300720_latest.json"

    _write_json(
        default_merge_review_path,
        {
            "focus_ticker": "300720",
            "merge_review_verdict": "ready_for_default_btst_merge_review",
        },
    )
    _write_json(
        objective_monitor_path,
        {
            "tradeable_surface": {
                "closed_cycle_count": 17,
                "t_plus_2_positive_rate": 0.4706,
                "mean_t_plus_2_return": -0.0057,
            }
        },
    )
    _write_json(
        focus_dossier_path,
        {
            "governance_objective_support": {
                "closed_cycle_count": 15,
                "t_plus_2_positive_rate": 0.8667,
                "mean_t_plus_2_return": 0.0787,
                "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
            }
        },
    )

    analysis = generate_btst_default_merge_historical_counterfactual(
        default_merge_review_path=default_merge_review_path,
        objective_monitor_path=objective_monitor_path,
    )

    assert analysis["counterfactual_verdict"] == "merged_default_btst_uplift_positive"
    assert analysis["merged_counterfactual_surface"]["closed_cycle_count"] == 32
    assert analysis["merged_counterfactual_surface"]["t_plus_2_positive_rate"] == 0.6563
    assert analysis["merged_counterfactual_surface"]["mean_t_plus_2_return"] == 0.0339
    assert analysis["uplift_vs_default_btst"]["t_plus_2_positive_rate_uplift"] == 0.1857
    assert analysis["uplift_vs_default_btst"]["mean_t_plus_2_return_uplift"] == 0.0396
    markdown = render_btst_default_merge_historical_counterfactual_markdown(analysis)
    assert "BTST Default Merge Historical Counterfactual" in markdown


def test_generate_btst_continuation_merge_candidate_ranking_orders_by_readiness_and_edge(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    objective_monitor_path = reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json"

    _write_json(
        objective_monitor_path,
        {
            "tradeable_surface": {
                "closed_cycle_count": 17,
                "t_plus_2_positive_rate": 0.4706,
                "mean_t_plus_2_return": -0.0057,
            }
        },
    )
    _write_json(
        reports_root / "btst_tplus2_candidate_dossier_300720_latest.json",
        {
            "candidate_ticker": "300720",
            "verdict": "governance_followup_candidate",
            "candidate_tier_focus": "governance_followup",
            "promotion_readiness_verdict": "merge_review_ready",
            "promotion_path_status": "merge_review_ready",
            "promotion_merge_review_verdict": "ready_for_default_btst_merge_review",
            "recent_support_ratio": 1.0,
            "observed_independent_window_count": 2,
            "latest_followup_decision": "selected",
            "governance_objective_support": {
                "closed_cycle_count": 15,
                "t_plus_2_positive_rate": 0.8667,
                "mean_t_plus_2_return": 0.0787,
                "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
            },
        },
    )
    _write_json(
        reports_root / "btst_tplus2_candidate_dossier_300505_latest.json",
        {
            "candidate_ticker": "300505",
            "verdict": "observation_only_candidate",
            "candidate_tier_focus": "observation_candidate",
            "promotion_readiness_verdict": "validation_queue_ready",
            "recent_support_ratio": 0.0,
            "tier_focus_surface_summary": {
                "closed_cycle_count": 4,
                "t_plus_2_close_positive_rate": 1.0,
                "t_plus_2_close_return_distribution": {"mean": 0.0361},
            },
        },
    )

    analysis = generate_btst_continuation_merge_candidate_ranking(
        reports_root=reports_root,
        objective_monitor_path=objective_monitor_path,
    )

    assert analysis["candidate_count"] == 2
    assert analysis["top_candidate"]["ticker"] == "300720"
    assert analysis["ranked_candidates"][0]["merge_candidate_rank"] == 1
    assert analysis["ranked_candidates"][1]["ticker"] == "300505"
    markdown = render_btst_continuation_merge_candidate_ranking_markdown(analysis)
    assert "BTST Continuation Merge Candidate Ranking" in markdown


def test_generate_btst_default_merge_strict_counterfactual_deduplicates_overlap(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    default_merge_review_path = reports_root / "btst_default_merge_review_latest.json"
    candidate_pool_recall_dossier_path = reports_root / "btst_candidate_pool_recall_dossier_latest.json"

    _write_json(
        default_merge_review_path,
        {
            "focus_ticker": "300720",
            "merge_review_verdict": "ready_for_default_btst_merge_review",
        },
    )
    _write_json(candidate_pool_recall_dossier_path, {"priority_ticker_dossiers": []})

    monkeypatch.setattr(
        "scripts.generate_btst_default_merge_strict_counterfactual._collect_default_tradeable_rows",
        lambda reports_root: [
            {"trade_date": "2026-03-23", "ticker": "000001", "next_high_return": 0.03, "next_close_return": 0.01, "t_plus_2_close_return": 0.02},
            {"trade_date": "2026-03-24", "ticker": "000002", "next_high_return": 0.01, "next_close_return": -0.01, "t_plus_2_close_return": -0.02},
        ],
    )
    monkeypatch.setattr(
        "scripts.generate_btst_default_merge_strict_counterfactual._collect_focus_occurrence_rows",
        lambda dossier, focus_ticker: [
            {"trade_date": "2026-03-24", "ticker": "000002", "next_high_return": 0.04, "next_close_return": 0.02, "t_plus_2_close_return": 0.05},
            {"trade_date": "2026-03-25", "ticker": "300720", "next_high_return": 0.05, "next_close_return": 0.03, "t_plus_2_close_return": 0.08},
        ],
    )

    analysis = generate_btst_default_merge_strict_counterfactual(
        reports_root=reports_root,
        default_merge_review_path=default_merge_review_path,
        candidate_pool_recall_dossier_path=candidate_pool_recall_dossier_path,
    )

    assert analysis["strict_counterfactual_verdict"] == "strict_merge_uplift_positive"
    assert analysis["overlap_diagnostics"]["overlap_case_count"] == 1
    assert analysis["overlap_diagnostics"]["focus_only_case_count"] == 1
    assert analysis["overlap_diagnostics"]["default_trade_date_count"] == 2
    assert analysis["overlap_diagnostics"]["focus_trade_date_count"] == 2
    assert analysis["overlap_diagnostics"]["focus_only_trade_date_count"] == 1
    assert analysis["overlap_diagnostics"]["overlap_trade_date_count"] == 1
    assert analysis["overlap_diagnostics"]["focus_only_trade_dates"] == ["2026-03-25"]
    assert analysis["overlap_diagnostics"]["overlap_trade_dates"] == ["2026-03-24"]
    assert analysis["overlap_diagnostics"]["overlap_case_ratio_vs_focus_cases"] == 0.5
    assert analysis["strict_merged_surface"]["closed_cycle_count"] == 3
    assert analysis["strict_uplift_vs_default_btst"]["t_plus_2_positive_rate_uplift"] == 0.1667
    assert analysis["strict_uplift_vs_default_btst"]["mean_t_plus_2_return_uplift"] == 0.0267
    markdown = render_btst_default_merge_strict_counterfactual_markdown(analysis)
    assert "BTST Default Merge Strict Counterfactual" in markdown
