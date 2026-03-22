from types import SimpleNamespace

from src.backtesting.engine import BacktestEngine
from src.execution.models import ExecutionPlan, LayerCResult
from src.portfolio.models import PositionPlan
from src.research.artifacts import FileSelectionArtifactWriter


def _fake_agent(*args, **kwargs):
    return {}


def test_backtest_engine_attaches_selection_artifact_metadata_to_plan(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="engine_session_001")
    pipeline_stub = SimpleNamespace(
        base_model_name="MiniMax-M2.7",
        base_model_provider="MiniMax",
        frozen_post_market_plans=None,
        frozen_plan_source=None,
    )
    engine = BacktestEngine(
        agent=_fake_agent,
        tickers=[],
        start_date="2026-03-20",
        end_date="2026-03-20",
        initial_capital=100000.0,
        model_name="MiniMax-M2.7",
        model_provider="MiniMax",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline_stub,
        selection_artifact_writer=writer,
    )
    plan = ExecutionPlan(
        date="20260320",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "counts": {
                "layer_a_count": 20,
                "layer_b_count": 5,
                "watchlist_count": 1,
                "buy_order_count": 1,
            },
            "funnel_diagnostics": {"filters": {"watchlist": {"tickers": []}}},
        },
        watchlist=[
            LayerCResult(
                ticker="000001",
                score_b=0.71,
                score_c=0.62,
                score_final=0.67,
                quality_score=0.6,
                decision="watch",
            )
        ],
        buy_orders=[PositionPlan(ticker="000001", shares=100, amount=10000.0, score_final=0.67, quality_score=0.6)],
    )

    engine._write_selection_artifacts(plan, "20260320")

    assert plan.selection_artifacts["write_status"] == "success"
    assert plan.selection_artifacts["snapshot_path"].endswith("selection_snapshot.json")
    assert (tmp_path / "2026-03-20" / "selection_snapshot.json").exists()