from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_merge_replay_validation import (
    generate_btst_merge_replay_validation,
    render_btst_merge_replay_validation_markdown,
)
from src.execution.models import LayerCResult
from src.screening.models import StrategySignal
from src.targets.router import build_selection_targets


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_merge_boundary_replay_report(report_dir: Path) -> None:
    watch_item = LayerCResult(
        ticker="300720",
        score_b=0.60,
        score_c=0.20,
        score_final=0.45,
        quality_score=0.60,
        decision="watch",
        candidate_source="layer_c_watchlist",
        strategy_signals={
            "trend": _make_signal(
                1,
                60.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 65.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 60.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 58.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 56.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 20.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                55.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 65.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(-1, 20.0).model_dump(mode="json"),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.10, "investor": 0.04}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date="20260328",
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "merge_replay_validation",
        "trade_date": "2026-03-28",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 1,
            "rejected_entry_count": 0,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [watch_item.model_dump(mode="json")],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    _write_json(report_dir / "selection_artifacts" / "2026-03-28" / "selection_target_replay_input.json", replay_input)


def _build_merge_already_selected_replay_report(report_dir: Path) -> None:
    watch_item = LayerCResult(
        ticker="300720",
        score_b=0.72,
        score_c=0.24,
        score_final=0.68,
        quality_score=0.72,
        decision="selected",
        candidate_source="layer_c_watchlist",
        strategy_signals={
            "trend": _make_signal(
                1,
                74.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 74.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 64.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 35.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                66.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 76.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 58.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(-1, 18.0).model_dump(mode="json"),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.12, "investor": 0.08}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date="20260406",
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "merge_replay_validation_selected",
        "trade_date": "2026-04-06",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 1,
            "rejected_entry_count": 0,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [watch_item.model_dump(mode="json")],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    _write_json(report_dir / "selection_artifacts" / "2026-04-06" / "selection_target_replay_input.json", replay_input)


def _build_upstream_gap_replay_report(report_dir: Path) -> None:
    watch_item = LayerCResult(
        ticker="300505",
        score_b=0.3899,
        score_c=0.375,
        score_final=0.3832,
        quality_score=0.75,
        decision="watch",
        candidate_source="layer_c_watchlist",
        strategy_signals={
            "trend": _make_signal(
                1,
                39.9,
                sub_factors={
                    "momentum": {
                        "direction": 0,
                        "confidence": 50.0,
                        "completeness": 1.0,
                        "metrics": {
                            "momentum_1m": -0.1924,
                            "momentum_3m": 0.3893,
                            "momentum_6m": 0.4729,
                            "volume_momentum": 0.5695,
                        },
                    },
                    "adx_strength": {"direction": 1, "confidence": 31.1, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {
                        "direction": 0,
                        "confidence": 50.0,
                        "completeness": 1.0,
                        "metrics": {"volatility_regime": 1.26, "atr_ratio": 0.0988},
                    },
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 0.0},
                },
            ).model_dump(mode="json"),
            "fundamental": _make_signal(1, 52.7).model_dump(mode="json"),
            "mean_reversion": _make_signal(1, 11.1).model_dump(mode="json"),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.375, "investor": 0.0}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date="20260326",
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "merge_replay_validation_upstream_gap",
        "trade_date": "2026-03-26",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 1,
            "rejected_entry_count": 0,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [watch_item.model_dump(mode="json")],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    _write_json(report_dir / "selection_artifacts" / "2026-03-26" / "selection_target_replay_input.json", replay_input)


def test_generate_btst_merge_replay_validation_promotes_merge_approved_boundary_case(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_20260328_20260328_merge_validation_case"
    _build_merge_boundary_replay_report(report_dir)

    _write_json(
        reports_root / "btst_default_merge_review_latest.json",
        {
            "focus_ticker": "300720",
            "merge_review_verdict": "ready_for_default_btst_merge_review",
        },
    )
    _write_json(
        reports_root / "btst_continuation_merge_candidate_ranking_latest.json",
        {
            "ranked_candidates": [
                {"ticker": "300720", "merge_candidate_rank": 1},
            ]
        },
    )
    _write_json(
        reports_root / "btst_tplus2_candidate_dossier_300720_latest.json",
        {
            "candidate_ticker": "300720",
            "recent_window_summaries": [
                {
                    "report_label": "20260328",
                    "report_dir": str(report_dir),
                    "decision": "near_miss",
                }
            ],
        },
    )

    analysis = generate_btst_merge_replay_validation(reports_root=reports_root)

    assert analysis["overall_verdict"] == "merge_replay_promotes_selected"
    assert analysis["promoted_to_selected_count"] == 1
    assert analysis["decision_deteriorated_count"] == 0
    assert analysis["relief_promoted_to_selected_count"] == 1
    assert analysis["relief_promoted_to_near_miss_count"] == 0
    assert analysis["relief_positive_promotion_count"] == 1
    assert analysis["relief_without_decision_promotion_count"] == 0
    assert analysis["relief_decision_deteriorated_count"] == 0
    assert analysis["relief_actionable_applied_count"] == 1
    assert analysis["relief_already_selected_count"] == 0
    assert analysis["relief_already_selected_score_shift_only_count"] == 0
    assert analysis["relief_positive_promotion_precision"] == 1.0
    assert analysis["relief_selected_promotion_precision"] == 1.0
    assert analysis["relief_no_promotion_ratio"] == 0.0
    assert analysis["relief_actionable_promoted_to_selected_count"] == 1
    assert analysis["relief_actionable_promoted_to_near_miss_count"] == 0
    assert analysis["relief_actionable_positive_promotion_count"] == 1
    assert analysis["relief_actionable_without_decision_promotion_count"] == 0
    assert analysis["relief_actionable_positive_promotion_precision"] == 1.0
    assert analysis["relief_actionable_selected_promotion_precision"] == 1.0
    assert analysis["relief_actionable_no_promotion_ratio"] == 0.0
    assert analysis["breakout_signal_uplift_applied_count"] == 1
    assert analysis["volume_signal_uplift_applied_count"] == 0
    assert analysis["layer_c_alignment_uplift_applied_count"] == 0
    assert analysis["sector_resonance_uplift_applied_count"] == 0
    assert analysis["prepared_breakout_penalty_relief_applied_count"] == 0
    assert analysis["prepared_breakout_catalyst_relief_applied_count"] == 0
    assert analysis["prepared_breakout_volume_relief_applied_count"] == 0
    assert analysis["prepared_breakout_continuation_relief_applied_count"] == 0
    assert analysis["prepared_breakout_selected_catalyst_relief_applied_count"] == 0
    assert analysis["candidate_count"] == 1
    summary = analysis["candidate_summaries"][0]
    assert summary["focus_ticker"] == "300720"
    assert summary["promoted_to_selected_count"] == 1
    assert summary["decision_deteriorated_count"] == 0
    assert summary["relief_promoted_to_selected_count"] == 1
    assert summary["relief_promoted_to_near_miss_count"] == 0
    assert summary["relief_positive_promotion_count"] == 1
    assert summary["relief_without_decision_promotion_count"] == 0
    assert summary["relief_decision_deteriorated_count"] == 0
    assert summary["relief_actionable_applied_count"] == 1
    assert summary["relief_already_selected_count"] == 0
    assert summary["relief_already_selected_score_shift_only_count"] == 0
    assert summary["relief_positive_promotion_precision"] == 1.0
    assert summary["relief_selected_promotion_precision"] == 1.0
    assert summary["relief_no_promotion_ratio"] == 0.0
    assert summary["relief_actionable_promoted_to_selected_count"] == 1
    assert summary["relief_actionable_promoted_to_near_miss_count"] == 0
    assert summary["relief_actionable_positive_promotion_count"] == 1
    assert summary["relief_actionable_without_decision_promotion_count"] == 0
    assert summary["relief_actionable_positive_promotion_precision"] == 1.0
    assert summary["relief_actionable_selected_promotion_precision"] == 1.0
    assert summary["relief_actionable_no_promotion_ratio"] == 0.0
    assert summary["breakout_signal_uplift_applied_count"] == 1
    assert summary["volume_signal_uplift_applied_count"] == 0
    assert summary["layer_c_alignment_uplift_applied_count"] == 0
    assert summary["sector_resonance_uplift_applied_count"] == 0
    assert summary["prepared_breakout_penalty_relief_applied_count"] == 0
    assert summary["prepared_breakout_catalyst_relief_applied_count"] == 0
    assert summary["prepared_breakout_volume_relief_applied_count"] == 0
    assert summary["prepared_breakout_continuation_relief_applied_count"] == 0
    assert summary["prepared_breakout_selected_catalyst_relief_applied_count"] == 0
    assert summary["candidate_recommendation"] == "supports_merge_approved_replay_followup"
    assert summary["recommended_primary_lever"] == "none"
    assert summary["recommended_signal_levers"][:2] == ["sector_resonance", "trend_acceleration"]
    row = summary["rows"][0]
    assert row["baseline_replayed_decision"] == "near_miss"
    assert row["merge_replayed_decision"] == "selected"
    assert row["decision_uplift_classification"] == "promoted_to_selected"
    assert row["remaining_leverage_classification"] == "already_selected"
    assert row["recommended_primary_lever"] == "none"
    assert row["required_score_uplift_to_selected"] == 0.0
    assert row["priority_signal_levers"][:2] == ["sector_resonance", "trend_acceleration"]
    assert row["breakout_signal_uplift_applied"] is True
    assert row["breakout_signal_uplift_eligible"] is True
    assert row["breakout_signal_uplift_confidence_delta"]["momentum_confidence"] == 13.0
    assert row["breakout_signal_uplift_confidence_delta"]["event_freshness_confidence"] == 17.0
    assert row["volume_signal_uplift_applied"] is False
    assert row["volume_signal_uplift_eligible"] is False
    assert row["volume_signal_uplift_confidence_delta"]["volatility_confidence"] == 0.0
    assert row["layer_c_alignment_uplift_applied"] is False
    assert row["layer_c_alignment_uplift_eligible"] is False
    assert row["layer_c_alignment_uplift_delta"]["score_c"] == 0.0
    assert row["sector_resonance_uplift_applied"] is False
    assert row["sector_resonance_uplift_eligible"] is False
    assert row["sector_resonance_uplift_delta"]["investor_contribution"] == 0.0
    assert row["prepared_breakout_penalty_relief_applied"] is False
    assert row["prepared_breakout_penalty_relief_eligible"] is False
    assert row["prepared_breakout_penalty_relief_penalty_delta"]["stale_score_penalty_weight"] == 0.0
    assert row["prepared_breakout_catalyst_relief_applied"] is False
    assert row["prepared_breakout_catalyst_relief_eligible"] is False
    assert row["prepared_breakout_catalyst_relief_catalyst_delta"] == 0.0
    assert row["prepared_breakout_volume_relief_applied"] is False
    assert row["prepared_breakout_volume_relief_eligible"] is False
    assert row["prepared_breakout_volume_relief_volume_delta"] == 0.0
    assert row["prepared_breakout_continuation_relief_applied"] is False
    assert row["prepared_breakout_continuation_relief_eligible"] is False
    assert row["prepared_breakout_continuation_relief_breakout_delta"] == 0.0
    assert row["prepared_breakout_continuation_relief_trend_delta"] == 0.0
    assert row["prepared_breakout_selected_catalyst_relief_applied"] is False
    assert row["prepared_breakout_selected_catalyst_relief_eligible"] is False
    assert row["prepared_breakout_selected_catalyst_relief_breakout_delta"] == 0.0
    assert row["prepared_breakout_selected_catalyst_relief_catalyst_delta"] == 0.0
    assert row["merge_relief_applied"] is True
    assert row["merge_effective_select_threshold"] == 0.56
    markdown = render_btst_merge_replay_validation_markdown(analysis)
    assert "# BTST Merge Replay Validation" in markdown
    assert "supports_merge_approved_replay_followup" in markdown
    assert "breakout_signal_uplift_applied_count" in markdown
    assert "volume_signal_uplift_applied_count" in markdown
    assert "layer_c_alignment_uplift_applied_count" in markdown
    assert "sector_resonance_uplift_applied_count" in markdown
    assert "prepared_breakout_penalty_relief_applied_count" in markdown
    assert "prepared_breakout_catalyst_relief_applied_count" in markdown
    assert "prepared_breakout_volume_relief_applied_count" in markdown
    assert "prepared_breakout_continuation_relief_applied_count" in markdown
    assert "prepared_breakout_selected_catalyst_relief_applied_count" in markdown
    assert "relief_positive_promotion_precision" in markdown
    assert "relief_no_promotion_ratio" in markdown
    assert "relief_actionable_positive_promotion_precision" in markdown
    assert "relief_actionable_no_promotion_ratio" in markdown


def test_generate_btst_merge_replay_validation_separates_already_selected_relief_from_actionable_precision(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_20260406_20260406_merge_validation_selected_case"
    _build_merge_already_selected_replay_report(report_dir)

    _write_json(
        reports_root / "btst_default_merge_review_latest.json",
        {
            "focus_ticker": "300720",
            "merge_review_verdict": "ready_for_default_btst_merge_review",
        },
    )
    _write_json(
        reports_root / "btst_continuation_merge_candidate_ranking_latest.json",
        {
            "ranked_candidates": [
                {"ticker": "300720", "merge_candidate_rank": 1},
            ]
        },
    )
    _write_json(
        reports_root / "btst_tplus2_candidate_dossier_300720_latest.json",
        {
            "candidate_ticker": "300720",
            "recent_window_summaries": [
                {
                    "report_label": "20260406",
                    "report_dir": str(report_dir),
                    "decision": "selected",
                }
            ],
        },
    )

    analysis = generate_btst_merge_replay_validation(reports_root=reports_root)

    assert analysis["overall_verdict"] == "merge_replay_relief_confirms_selected"
    assert analysis["promoted_to_selected_count"] == 0
    assert analysis["relief_applied_count"] == 1
    assert analysis["relief_actionable_applied_count"] == 0
    assert analysis["relief_already_selected_count"] == 1
    assert analysis["relief_already_selected_score_shift_only_count"] == 1
    assert analysis["relief_positive_promotion_count"] == 0
    assert analysis["relief_without_decision_promotion_count"] == 1
    assert analysis["relief_positive_promotion_precision"] == 0.0
    assert analysis["relief_no_promotion_ratio"] == 1.0
    assert analysis["relief_actionable_positive_promotion_precision"] is None
    assert analysis["relief_actionable_selected_promotion_precision"] is None
    assert analysis["relief_actionable_no_promotion_ratio"] is None
    summary = analysis["candidate_summaries"][0]
    assert summary["candidate_recommendation"] == "relief_confirms_already_selected"
    assert summary["relief_actionable_applied_count"] == 0
    assert summary["relief_already_selected_count"] == 1
    assert summary["relief_already_selected_score_shift_only_count"] == 1
    assert summary["relief_actionable_positive_promotion_precision"] is None
    assert summary["relief_actionable_no_promotion_ratio"] is None
    row = summary["rows"][0]
    assert row["baseline_replayed_decision"] == "selected"
    assert row["merge_replayed_decision"] == "selected"
    assert row["decision_uplift_classification"] == "score_shift_only"
    assert row["merge_relief_applied"] is True


def test_generate_btst_merge_replay_validation_recovers_report_dir_from_report_label(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_btst_fast_tier_aggressive"
    _build_upstream_gap_replay_report(report_dir)

    _write_json(
        reports_root / "btst_default_merge_review_latest.json",
        {
            "focus_ticker": "300505",
            "merge_review_verdict": "ready_for_default_btst_merge_review",
        },
    )
    _write_json(
        reports_root / "btst_continuation_merge_candidate_ranking_latest.json",
        {
            "ranked_candidates": [
                {"ticker": "300505", "merge_candidate_rank": 1},
            ]
        },
    )
    _write_json(
        reports_root / "btst_tplus2_candidate_dossier_300505_latest.json",
        {
            "candidate_ticker": "300505",
            "recent_window_summaries": [
                {
                    "report_label": report_dir.name,
                    "decision": "watch",
                }
            ],
        },
    )

    analysis = generate_btst_merge_replay_validation(reports_root=reports_root)

    assert analysis["candidate_count"] == 1
    assert analysis["recommended_next_lever"] == "none"
    assert analysis["decision_deteriorated_count"] == 0
    assert analysis["relief_positive_promotion_count"] == 0
    assert analysis["relief_without_decision_promotion_count"] == 0
    assert analysis["relief_decision_deteriorated_count"] == 0
    assert analysis["relief_actionable_applied_count"] == 0
    assert analysis["relief_already_selected_count"] == 0
    assert analysis["relief_already_selected_score_shift_only_count"] == 0
    assert analysis["relief_positive_promotion_precision"] is None
    assert analysis["relief_selected_promotion_precision"] is None
    assert analysis["relief_no_promotion_ratio"] is None
    assert analysis["relief_actionable_positive_promotion_precision"] is None
    assert analysis["relief_actionable_selected_promotion_precision"] is None
    assert analysis["relief_actionable_no_promotion_ratio"] is None
    summary = analysis["candidate_summaries"][0]
    assert summary["focus_ticker"] == "300505"
    assert summary["report_dir_count"] == 1
    assert summary["trade_date_count"] == 1
    assert summary["candidate_recommendation"] == "no_incremental_merge_approved_replay_uplift_observed"
    assert summary["recommended_primary_lever"] == "none"
    assert summary["decision_deteriorated_count"] == 0
    assert summary["relief_positive_promotion_count"] == 0
    assert summary["relief_without_decision_promotion_count"] == 0
    assert summary["relief_decision_deteriorated_count"] == 0
    assert summary["relief_actionable_applied_count"] == 0
    assert summary["relief_already_selected_count"] == 0
    assert summary["relief_already_selected_score_shift_only_count"] == 0
    assert summary["relief_positive_promotion_precision"] is None
    assert summary["relief_selected_promotion_precision"] is None
    assert summary["relief_no_promotion_ratio"] is None
    assert summary["relief_actionable_positive_promotion_precision"] is None
    assert summary["relief_actionable_selected_promotion_precision"] is None
    assert summary["relief_actionable_no_promotion_ratio"] is None
    assert summary["recommended_signal_levers"][:2] == ["catalyst_freshness", "volume_expansion_quality"]
    assert summary["prepared_breakout_penalty_relief_applied_count"] == 1
    assert summary["prepared_breakout_catalyst_relief_applied_count"] == 1
    assert summary["prepared_breakout_volume_relief_applied_count"] == 1
    assert summary["prepared_breakout_continuation_relief_applied_count"] == 1
    assert summary["prepared_breakout_selected_catalyst_relief_applied_count"] == 1
    assert summary["minimum_required_score_uplift_to_selected"] is not None
    row = summary["rows"][0]
    assert row["report_dir"] == str(report_dir)
    assert row["merge_relief_applied"] is False
    assert row["merge_replayed_decision"] == "selected"
    assert row["recommended_primary_lever"] == "none"
    assert row["prepared_breakout_penalty_relief_applied"] is True
    assert row["prepared_breakout_penalty_relief_eligible"] is True
    assert row["prepared_breakout_penalty_relief_penalty_delta"]["stale_score_penalty_weight"] == -0.06
    assert row["prepared_breakout_catalyst_relief_applied"] is True
    assert row["prepared_breakout_catalyst_relief_eligible"] is True
    assert row["prepared_breakout_catalyst_relief_catalyst_delta"] == 0.35
    assert row["prepared_breakout_volume_relief_applied"] is True
    assert row["prepared_breakout_volume_relief_eligible"] is True
    assert row["prepared_breakout_volume_relief_volume_delta"] == 0.35
    assert row["prepared_breakout_continuation_relief_applied"] is True
    assert row["prepared_breakout_continuation_relief_eligible"] is True
    assert row["prepared_breakout_continuation_relief_breakout_delta"] == 0.24
    assert row["prepared_breakout_continuation_relief_trend_delta"] == 0.4211
    assert row["prepared_breakout_selected_catalyst_relief_applied"] is True
    assert row["prepared_breakout_selected_catalyst_relief_eligible"] is True
    assert row["prepared_breakout_selected_catalyst_relief_breakout_delta"] == 0.11
    assert row["prepared_breakout_selected_catalyst_relief_catalyst_delta"] == 0.65
