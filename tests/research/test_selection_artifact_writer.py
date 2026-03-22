from pathlib import Path

import pytest

from src.execution.models import ExecutionPlan, LayerCResult
from src.screening.models import MarketState
from src.portfolio.models import ExitSignal, PositionPlan
from src.research.artifacts import FileSelectionArtifactWriter


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
        buy_orders=[PositionPlan(ticker="000001", shares=100, amount=12000.0, score_final=0.69, quality_score=0.65)],
        sell_orders=[ExitSignal(ticker="600000", level="trim", trigger_reason="take_profit")],
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)

    assert result.write_status == "success"
    assert (tmp_path / "2026-03-22" / "selection_snapshot.json").exists()
    assert (tmp_path / "2026-03-22" / "selection_review.md").exists()
    assert (tmp_path / "2026-03-22" / "research_feedback.jsonl").exists()


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