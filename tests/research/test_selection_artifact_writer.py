import json
from pathlib import Path

import pytest

from src.execution.models import ExecutionPlan, LayerCResult
from src.screening.models import MarketState, StrategySignal
from src.portfolio.models import ExitSignal, PositionPlan
from src.research.artifacts import FileSelectionArtifactWriter
from src.targets.models import DualTargetEvaluation, DualTargetSummary
from src.targets.router import build_selection_targets


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def test_file_selection_artifact_writer_writes_expected_files(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_001")
    plan = ExecutionPlan(
        date="20260322",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "counts": {
                "layer_a_count": 50,
                "layer_b_count": 8,
                "watchlist_count": 1,
                "buy_order_count": 1,
                "sell_order_count": 1,
                "catalyst_theme_shadow_candidate_count": 1,
            },
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {
                        "tickers": [
                            {
                                "ticker": "300750",
                                "score_b": 0.61,
                                "score_c": 0.20,
                                "score_final": 0.39,
                                "reason": "analyst_divergence_high",
                                "reasons": ["analyst_divergence_high"],
                            }
                        ]
                    },
                    "catalyst_theme_candidates": {
                        "tickers": [
                            {
                                "ticker": "300999",
                                "decision": "catalyst_theme",
                                "score_target": 0.4123,
                                "preferred_entry_mode": "theme_research_followup",
                                "candidate_source": "catalyst_theme",
                                "positive_tags": ["strong_catalyst_freshness"],
                                "top_reasons": ["catalyst_freshness=0.82", "sector_resonance=0.25"],
                                "metrics": {
                                    "breakout_freshness": 0.31,
                                    "trend_acceleration": 0.26,
                                    "close_strength": 0.57,
                                    "sector_resonance": 0.25,
                                    "catalyst_freshness": 0.82,
                                },
                                "gate_status": {"data": "pass", "structural": "fail", "score": "proxy_only"},
                                "blockers": ["stale_trend_repair_penalty"],
                            }
                        ],
                        "shadow_candidates": [
                            {
                                "ticker": "301000",
                                "decision": "catalyst_theme_shadow",
                                "score_target": 0.3891,
                                "preferred_entry_mode": "theme_research_followup",
                                "candidate_source": "catalyst_theme_shadow",
                                "positive_tags": ["strong_catalyst_freshness"],
                                "top_reasons": ["candidate_score=0.39", "total_shortfall=0.07"],
                                "metrics": {
                                    "breakout_freshness": 0.28,
                                    "trend_acceleration": 0.22,
                                    "close_strength": 0.41,
                                    "sector_resonance": 0.18,
                                    "catalyst_freshness": 0.79,
                                },
                                "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                                "blockers": ["sector_resonance_below_catalyst_theme_floor"],
                                "filter_reason": "sector_resonance_below_catalyst_theme_floor",
                                "threshold_shortfalls": {"sector_resonance": 0.02, "candidate_score": 0.05},
                                "failed_threshold_count": 2,
                                "total_shortfall": 0.07,
                            }
                        ]
                    }
                }
            },
        },
        watchlist=[
            LayerCResult(
                ticker="000001",
                score_b=0.71,
                score_c=0.66,
                score_final=0.69,
                quality_score=0.65,
                decision="watch",
            )
        ],
        selection_targets={
            "000001": DualTargetEvaluation(ticker="000001", trade_date="20260322"),
        },
        target_mode="research_only",
        dual_target_summary=DualTargetSummary(target_mode="research_only", selection_target_count=1, shell_target_count=1),
        buy_orders=[PositionPlan(ticker="000001", shares=100, amount=12000.0, score_final=0.69, quality_score=0.65)],
        sell_orders=[ExitSignal(ticker="600000", level="trim", trigger_reason="take_profit")],
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)

    assert result.write_status == "success"
    assert (tmp_path / "2026-03-22" / "selection_snapshot.json").exists()
    assert (tmp_path / "2026-03-22" / "selection_review.md").exists()
    assert (tmp_path / "2026-03-22" / "research_feedback.jsonl").exists()
    assert (tmp_path / "2026-03-22" / "selection_target_replay_input.json").exists()
    snapshot_text = (tmp_path / "2026-03-22" / "selection_snapshot.json").read_text(encoding="utf-8")
    replay_input_text = (tmp_path / "2026-03-22" / "selection_target_replay_input.json").read_text(encoding="utf-8")
    review_text = (tmp_path / "2026-03-22" / "selection_review.md").read_text(encoding="utf-8")
    assert '"target_mode": "research_only"' in snapshot_text
    assert '"short_trade_target_profile": {' in snapshot_text
    assert '"name": "default"' in snapshot_text
    assert '"selection_targets": {' in snapshot_text
    assert '"shell_target_count": 1' in snapshot_text
    assert '"research_view": {' in snapshot_text
    assert '"short_trade_view": {' in snapshot_text
    assert '"dual_target_delta": {' in snapshot_text
    assert '"catalyst_theme_candidates": [' in snapshot_text
    assert '"catalyst_theme_shadow_candidates": [' in snapshot_text
    assert '"replay_input_written": true' in snapshot_text
    assert '"watchlist": [' in replay_input_text
    assert '"buy_order_tickers": [' in replay_input_text
    assert '"supplemental_catalyst_theme_entries": [' in replay_input_text
    assert "## 双目标空壳状态" in review_text
    assert "## 题材催化研究池" in review_text
    assert "### 近阈值影子池" in review_text
    assert "301000" in review_text
    assert "## Research Target Summary" in review_text
    assert "## Short Trade Target Summary" in review_text
    assert "## Target Delta Highlights" in review_text
    assert "selection_target_count: 1" in review_text


def test_file_selection_artifact_writer_renders_target_decisions_for_selected_and_rejected(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_target_decisions")
    watch_item = LayerCResult(
        ticker="000001",
        score_b=0.71,
        score_c=0.66,
        score_final=0.69,
        quality_score=0.65,
        decision="watch",
        strategy_signals={
            "trend": _make_signal(
                1,
                84.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 86.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 74.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 66.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 30.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                1,
                76.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 65.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(-1, 18.0),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.22, "investor": 0.11}},
    )
    selection_targets, dual_target_summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[watch_item],
        rejected_entries=[
            {
                "ticker": "300750",
                "score_b": 0.61,
                "score_c": 0.20,
                "score_final": 0.39,
                "quality_score": 0.57,
                "decision": "watch",
                "reason": "score_final_below_watchlist_threshold",
                "reasons": ["score_final_below_watchlist_threshold"],
                "strategy_signals": {
                    "trend": _make_signal(
                        1,
                        79.0,
                        sub_factors={
                            "momentum": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                            "adx_strength": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                            "ema_alignment": {"direction": 1, "confidence": 69.0, "completeness": 1.0},
                            "volatility": {"direction": 1, "confidence": 63.0, "completeness": 1.0},
                            "long_trend_alignment": {"direction": 0, "confidence": 22.0, "completeness": 1.0},
                        },
                    ).model_dump(mode="json"),
                    "event_sentiment": _make_signal(
                        1,
                        71.0,
                        sub_factors={
                            "event_freshness": {"direction": 1, "confidence": 86.0, "completeness": 1.0},
                            "news_sentiment": {"direction": 1, "confidence": 60.0, "completeness": 1.0},
                        },
                    ).model_dump(mode="json"),
                    "mean_reversion": _make_signal(-1, 15.0).model_dump(mode="json"),
                },
                "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.18, "investor": 0.08}},
            }
        ],
        buy_order_tickers={"000001"},
        target_mode="dual_target",
    )
    plan = ExecutionPlan(
        date="20260322",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "counts": {
                "layer_a_count": 50,
                "layer_b_count": 8,
                "watchlist_count": 1,
                "buy_order_count": 1,
                "sell_order_count": 0,
            },
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {
                        "tickers": [
                            {
                                "ticker": "300750",
                                "score_b": 0.61,
                                "score_c": 0.20,
                                "score_final": 0.39,
                                "quality_score": 0.57,
                                "decision": "watch",
                                "reason": "score_final_below_watchlist_threshold",
                                "reasons": ["score_final_below_watchlist_threshold"],
                                "strategy_signals": {
                                    "trend": _make_signal(
                                        1,
                                        79.0,
                                        sub_factors={
                                            "momentum": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                                            "adx_strength": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                                            "ema_alignment": {"direction": 1, "confidence": 69.0, "completeness": 1.0},
                                            "volatility": {"direction": 1, "confidence": 63.0, "completeness": 1.0},
                                            "long_trend_alignment": {"direction": 0, "confidence": 22.0, "completeness": 1.0},
                                        },
                                    ).model_dump(mode="json"),
                                    "event_sentiment": _make_signal(
                                        1,
                                        71.0,
                                        sub_factors={
                                            "event_freshness": {"direction": 1, "confidence": 86.0, "completeness": 1.0},
                                            "news_sentiment": {"direction": 1, "confidence": 60.0, "completeness": 1.0},
                                        },
                                    ).model_dump(mode="json"),
                                    "mean_reversion": _make_signal(-1, 15.0).model_dump(mode="json"),
                                },
                                "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.18, "investor": 0.08}},
                            }
                        ]
                    }
                }
            },
        },
        watchlist=[watch_item],
        selection_targets=selection_targets,
        target_mode="dual_target",
        dual_target_summary=dual_target_summary,
        buy_orders=[PositionPlan(ticker="000001", shares=100, amount=12000.0, score_final=0.69, quality_score=0.65)],
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)

    assert result.write_status == "success"
    review_text = (tmp_path / "2026-03-22" / "selection_review.md").read_text(encoding="utf-8")
    snapshot_text = (tmp_path / "2026-03-22" / "selection_snapshot.json").read_text(encoding="utf-8")
    replay_input_text = (tmp_path / "2026-03-22" / "selection_target_replay_input.json").read_text(encoding="utf-8")
    assert "research_target: selected" in review_text
    assert "short_trade_target: selected" in review_text
    assert "selected_symbols: 000001" in review_text
    assert "near_miss_symbols: 300750" in review_text
    assert "delta_counts:" in review_text
    assert "research_reject_short_pass=1" in review_text
    assert '"target_decisions": {' in snapshot_text
    assert '"delta_classification": "research_reject_short_pass"' in snapshot_text
    assert '"candidate_source": "watchlist_filter_diagnostics"' in snapshot_text
    assert '"selected_symbols": [' in snapshot_text
    assert '"dominant_delta_reasons": [' in snapshot_text
    assert '"supplemental_short_trade_entries": [' in replay_input_text
    assert '"strategy_signals": {' in replay_input_text
    assert '"event_sentiment": {' in replay_input_text


def test_file_selection_artifact_writer_persists_short_trade_profile_metadata(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_profile")
    plan = ExecutionPlan(
        date="20260322",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        short_trade_target_profile_name="aggressive",
        short_trade_target_profile_config={
            "select_threshold": 0.54,
            "near_miss_threshold": 0.42,
            "strong_bearish_conflicts": ["b_positive_c_strong_bearish"],
        },
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)

    assert result.write_status == "success"
    snapshot_text = (tmp_path / "2026-03-22" / "selection_snapshot.json").read_text(encoding="utf-8")
    replay_input_text = (tmp_path / "2026-03-22" / "selection_target_replay_input.json").read_text(encoding="utf-8")
    assert '"short_trade_target_profile": {' in snapshot_text
    assert '"name": "aggressive"' in snapshot_text
    assert '"select_threshold": 0.54' in snapshot_text
    assert '"short_trade_target_profile": {' in replay_input_text
    assert '"name": "aggressive"' in replay_input_text


def test_selection_snapshot_serializes_short_trade_frontier_fields(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_short_trade_frontier")
    selection_targets, dual_target_summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=[],
        supplemental_short_trade_entries=[
            {
                "ticker": "300720",
                "score_b": 0.46,
                "score_c": 0.0,
                "score_final": 0.46,
                "quality_score": 0.6,
                "decision": "watch",
                "reason": "short_trade_candidate_score_ranked",
                "reasons": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
                "candidate_source": "short_trade_boundary",
                "candidate_reason_codes": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
                "strategy_signals": {
                    "trend": _make_signal(
                        1,
                        82.0,
                        sub_factors={
                            "momentum": {"direction": 1, "confidence": 84.0, "completeness": 1.0},
                            "adx_strength": {"direction": 1, "confidence": 76.0, "completeness": 1.0},
                            "ema_alignment": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                            "volatility": {"direction": 1, "confidence": 66.0, "completeness": 1.0},
                            "long_trend_alignment": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                        },
                    ).model_dump(mode="json"),
                    "event_sentiment": _make_signal(
                        1,
                        74.0,
                        sub_factors={
                            "event_freshness": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                            "news_sentiment": {"direction": 1, "confidence": 62.0, "completeness": 1.0},
                        },
                    ).model_dump(mode="json"),
                    "fundamental": _make_signal(1, 58.0).model_dump(mode="json"),
                    "mean_reversion": _make_signal(-1, 12.0).model_dump(mode="json"),
                },
                "agent_contribution_summary": {},
            }
        ],
        target_mode="short_trade_only",
    )
    plan = ExecutionPlan(
        date="20260322",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"layer_a_count": 1, "layer_b_count": 0, "watchlist_count": 0, "buy_order_count": 0, "sell_order_count": 0}},
        watchlist=[],
        selection_targets=selection_targets,
        target_mode="short_trade_only",
        dual_target_summary=dual_target_summary,
        buy_orders=[],
        sell_orders=[],
    )

    writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)

    snapshot = json.loads((tmp_path / "2026-03-22" / "selection_snapshot.json").read_text(encoding="utf-8"))
    short_trade = snapshot["selection_targets"]["300720"]["short_trade"]
    assert short_trade["candidate_source"] == "short_trade_boundary"
    assert isinstance(short_trade["effective_near_miss_threshold"], float)
    assert isinstance(short_trade["effective_select_threshold"], float)
    assert isinstance(short_trade["weighted_positive_contributions"], dict)
    assert isinstance(short_trade["weighted_negative_contributions"], dict)
    assert isinstance(short_trade["breakout_freshness"], float)
    assert isinstance(short_trade["trend_acceleration"], float)


def test_file_selection_artifact_writer_includes_catalyst_theme_candidates_in_short_trade_replay_inputs(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_short_trade_catalyst_bridge")
    plan = ExecutionPlan(
        date="20260322",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "counts": {
                "layer_a_count": 50,
                "layer_b_count": 8,
                "watchlist_count": 0,
                "buy_order_count": 0,
                "sell_order_count": 0,
                "catalyst_theme_candidate_count": 1,
            },
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": [], "shadow_observation_entries": []},
                    "catalyst_theme_candidates": {
                        "tickers": [
                            {
                                "ticker": "300999",
                                "decision": "catalyst_theme",
                                "score_b": 0.34,
                                "score_c": 0.0,
                                "score_final": 0.34,
                                "quality_score": 0.5,
                                "preferred_entry_mode": "theme_research_followup",
                                "candidate_source": "catalyst_theme",
                                "candidate_reason_codes": [
                                    "catalyst_theme_candidate_score_ranked",
                                    "catalyst_theme_research_candidate",
                                    "catalyst_theme_short_trade_carryover_candidate",
                                ],
                                "positive_tags": ["close_momentum_catalyst_relief"],
                                "top_reasons": ["candidate_score=0.44"],
                                "short_trade_catalyst_relief": {
                                    "enabled": True,
                                    "reason": "catalyst_theme_short_trade_carryover",
                                    "catalyst_freshness_floor": 1.0,
                                    "near_miss_threshold": 0.44,
                                    "breakout_freshness_min": 0.35,
                                    "trend_acceleration_min": 0.72,
                                    "close_strength_min": 0.85,
                                    "require_no_profitability_hard_cliff": True,
                                },
                                "metrics": {
                                    "breakout_freshness": 0.40,
                                    "trend_acceleration": 0.80,
                                    "close_strength": 0.91,
                                    "sector_resonance": 0.10,
                                    "catalyst_freshness": 0.0,
                                },
                                "gate_status": {"data": "pass", "structural": "pass", "score": "proxy_only"},
                                "blockers": [],
                            }
                        ],
                        "shadow_candidates": [],
                    },
                }
            },
        },
        watchlist=[],
        selection_targets={},
        target_mode="short_trade_only",
        dual_target_summary=DualTargetSummary(target_mode="short_trade_only", selection_target_count=0, short_trade_target_count=0, shell_target_count=0),
        buy_orders=[],
        sell_orders=[],
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)

    assert result.write_status == "success"
    replay_input_payload = json.loads((tmp_path / "2026-03-22" / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    assert replay_input_payload["source_summary"]["supplemental_catalyst_theme_entry_count"] == 1
    assert replay_input_payload["source_summary"]["supplemental_short_trade_entry_count"] == 1
    assert replay_input_payload["supplemental_short_trade_entries"][0]["ticker"] == "300999"
    assert replay_input_payload["supplemental_short_trade_entries"][0]["short_trade_catalyst_relief"]["reason"] == "catalyst_theme_short_trade_carryover"


def test_file_selection_artifact_writer_merges_released_shadow_entries_into_replay_input(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_shadow_release")
    plan = ExecutionPlan(
        date="20260322",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "short_trade_candidates": {
                        "tickers": [
                            {
                                "ticker": "000001",
                                "candidate_source": "short_trade_boundary",
                            }
                        ],
                        "released_shadow_entries": [
                            {
                                "ticker": "301292",
                                "candidate_source": "post_gate_liquidity_competition_shadow",
                                "candidate_pool_lane": "post_gate_liquidity_competition",
                                "shadow_release_reason": "upstream_shadow_release_score_floor_pass",
                            }
                        ],
                    }
                }
            }
        },
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)

    assert result.write_status == "success"
    replay_input_text = (tmp_path / "2026-03-22" / "selection_target_replay_input.json").read_text(encoding="utf-8")
    assert '"supplemental_short_trade_entry_count": 2' in replay_input_text
    assert '"ticker": "301292"' in replay_input_text
    assert '"shadow_release_reason": "upstream_shadow_release_score_floor_pass"' in replay_input_text


def test_file_selection_artifact_writer_includes_watchlist_shadow_release_entries(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_watchlist_shadow_release")
    plan = ExecutionPlan(
        date="20260322",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {
                        "tickers": [
                            {
                                "ticker": "000960",
                                "candidate_source": "watchlist_filter_diagnostics",
                                "reason": "decision_avoid",
                            }
                        ],
                        "released_shadow_entries": [
                            {
                                "ticker": "000960",
                                "candidate_source": "watchlist_avoid_shadow_release",
                                "shadow_release_reason": "watchlist_avoid_shadow_release_boundary_pass",
                            }
                        ],
                    }
                }
            }
        },
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)

    assert result.write_status == "success"
    replay_input_text = (tmp_path / "2026-03-22" / "selection_target_replay_input.json").read_text(encoding="utf-8")
    assert '"supplemental_short_trade_entry_count": 1' in replay_input_text
    assert '"candidate_source": "watchlist_avoid_shadow_release"' in replay_input_text
    assert '"shadow_release_reason": "watchlist_avoid_shadow_release_boundary_pass"' in replay_input_text


def test_file_selection_artifact_writer_builds_fallback_layer_b_factors_for_legacy_replay(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_legacy")
    plan = ExecutionPlan(
        date="20260205",
        market_state=MarketState(state_type="mixed", adjusted_weights={"trend": 0.3, "fundamental": 0.3, "event_sentiment": 0.2, "mean_reversion": 0.2}),
        strategy_weights={"trend": 0.3, "fundamental": 0.3, "event_sentiment": 0.2, "mean_reversion": 0.2},
        logic_scores={"300724": 0.5629},
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "counts": {
                "layer_a_count": 200,
                "layer_b_count": 3,
                "watchlist_count": 1,
                "buy_order_count": 1,
            }
        },
        watchlist=[
            LayerCResult(
                ticker="300724",
                score_b=0.5629,
                score_c=-0.023,
                score_final=0.2993,
                quality_score=0.72,
                decision="watch",
            )
        ],
        buy_orders=[PositionPlan(ticker="300724", shares=100, amount=12940.0, score_final=0.2993, quality_score=0.72)],
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260205", pipeline=None, selected_analysts=None)

    assert result.write_status == "success"

    snapshot_path = tmp_path / "2026-02-05" / "selection_snapshot.json"
    review_path = tmp_path / "2026-02-05" / "selection_review.md"
    snapshot_text = snapshot_path.read_text(encoding="utf-8")
    review_text = review_path.read_text(encoding="utf-8")

    assert '"explanation_source": "legacy_plan_fields"' in snapshot_text
    assert '"name": "logic_score"' in snapshot_text
    assert '"name": "trend"' in snapshot_text
    assert "Layer B 因子摘要" in review_text
    assert "logic_score: value=0.5629 (plan.logic_scores)" in review_text


def test_file_selection_artifact_writer_returns_partial_success_when_snapshot_write_fails(tmp_path, monkeypatch):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_partial")
    plan = ExecutionPlan(
        date="20260322",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        watchlist=[
            LayerCResult(
                ticker="000001",
                score_b=0.71,
                score_c=0.66,
                score_final=0.69,
                quality_score=0.65,
                decision="watch",
            )
        ],
    )

    original_write_text = Path.write_text

    def _patched_write_text(self, data, *args, **kwargs):
        if self.name == "selection_snapshot.json":
            raise OSError("snapshot write failed")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _patched_write_text)

    result = writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)

    assert result.write_status == "partial_success"
    assert result.snapshot_path is None
    assert result.review_path is not None
    assert result.feedback_path is not None
    assert result.replay_input_path is not None
    assert "snapshot write failed" in str(result.error_message)


def test_file_selection_artifact_writer_returns_failed_when_directory_creation_fails(tmp_path, monkeypatch):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_failed")
    plan = ExecutionPlan(
        date="20260322",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        watchlist=[
            LayerCResult(
                ticker="000001",
                score_b=0.71,
                score_c=0.66,
                score_final=0.69,
                quality_score=0.65,
                decision="watch",
            )
        ],
    )

    def _patched_mkdir(self, *args, **kwargs):
        raise OSError("mkdir failed")

    monkeypatch.setattr(Path, "mkdir", _patched_mkdir)

    result = writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)

    assert result.write_status == "failed"
    assert result.snapshot_path is None
    assert result.review_path is None
    assert result.feedback_path is None
    assert result.replay_input_path is None
    assert "mkdir failed" in str(result.error_message)


def test_file_selection_artifact_writer_captures_buy_order_blocker_details(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_blocker")
    plan = ExecutionPlan(
        date="20260311",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "counts": {
                "layer_a_count": 200,
                "layer_b_count": 1,
                "watchlist_count": 1,
                "buy_order_count": 0,
            },
            "funnel_diagnostics": {
                "filters": {
                    "buy_orders": {
                        "tickers": [
                            {
                                "ticker": "300724",
                                "reason": "blocked_by_reentry_score_confirmation",
                                "constraint_binding": "score",
                                "execution_ratio": 0.0,
                            }
                        ]
                    }
                },
                "blocked_buy_tickers": {
                    "300724": {
                        "trigger_reason": "hard_stop_loss",
                        "exit_trade_date": "20260226",
                        "blocked_until": "20260305",
                        "reentry_review_until": "20260312",
                    }
                },
            },
        },
        watchlist=[
            LayerCResult(
                ticker="300724",
                score_b=0.3897,
                score_c=0.0002,
                score_final=0.2144,
                quality_score=0.72,
                decision="watch",
            )
        ],
        buy_orders=[],
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260311", pipeline=None, selected_analysts=None)

    assert result.write_status == "success"

    snapshot_text = (tmp_path / "2026-03-11" / "selection_snapshot.json").read_text(encoding="utf-8")
    review_text = (tmp_path / "2026-03-11" / "selection_review.md").read_text(encoding="utf-8")

    assert '"block_reason": "blocked_by_reentry_score_confirmation"' in snapshot_text
    assert '"constraint_binding": "score"' in snapshot_text
    assert '"reentry_review_until": "20260312"' in snapshot_text
    assert "buy_order_blocker: blocked_by_reentry_score_confirmation (binding=score)" in review_text
    assert "reentry_review_until: 20260312" in review_text
