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
    snapshot_text = (tmp_path / "2026-03-22" / "selection_snapshot.json").read_text(encoding="utf-8")
    review_text = (tmp_path / "2026-03-22" / "selection_review.md").read_text(encoding="utf-8")
    assert '"target_mode": "research_only"' in snapshot_text
    assert '"selection_targets": {' in snapshot_text
    assert '"shell_target_count": 1' in snapshot_text
    assert '"research_view": {' in snapshot_text
    assert '"short_trade_view": {' in snapshot_text
    assert '"dual_target_delta": {' in snapshot_text
    assert "## 双目标空壳状态" in review_text
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