from src.execution.models import ExecutionPlan, LayerCResult
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