"""TDD red test: BacktestEngine._write_selection_artifacts must log when the
selection-artifact writer raises, mirroring the BH-017 silent-degradation
family drain (R48-R50 / R57-R60 / R63 / R67 / R89-R90 / R113).

R113 drained 6 silent ``except Exception`` sites in the 估值/筛选/回测 path
but missed ``engine.py:_write_selection_artifacts``: when the selection-
artifact writer raises (disk full / permission / serialization error), the
except block records ``{"write_status": "failed", "error_message": ...}`` in
``plan.selection_artifacts`` but emits NO log. Operators running long
backtests who monitor logs (rather than inspecting every plan dict) cannot
detect that selection artifacts silently stopped being written — a BH-017
observability gap in the backtest artifact path.

Fix: add ``logger.debug(..., exc_info=True)`` to the except block (consistent
with R113's pattern), zero behavior change (plan dict still records failure).
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.backtesting.engine import BacktestEngine
from src.execution.models import ExecutionPlan, LayerCResult
from src.portfolio.models import PositionPlan
from src.research.artifacts import FileSelectionArtifactWriter


def _fake_agent(*args, **kwargs):
    return {}


def _build_engine(tmp_path: Path) -> BacktestEngine:
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="engine_session_001")
    pipeline_stub = SimpleNamespace(
        base_model_name="MiniMax-M2.7",
        base_model_provider="MiniMax",
        frozen_post_market_plans=None,
        frozen_plan_source=None,
    )
    return BacktestEngine(
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


def _make_plan() -> ExecutionPlan:
    return ExecutionPlan(
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


def test_selection_artifact_write_failure_is_logged(tmp_path: Path, caplog) -> None:
    """When the selection-artifact writer raises, the engine must emit a log
    message (BH-017 observability) in addition to recording failure in the
    plan dict, so operators monitoring logs can detect silently-stopped
    artifact writes during long backtest runs."""
    engine = _build_engine(tmp_path)
    plan = _make_plan()

    # Force the writer to raise on write_for_plan
    with patch.object(
        engine._selection_artifact_writer,
        "write_for_plan",
        side_effect=RuntimeError("simulated disk full"),
    ):
        engine._write_selection_artifacts(plan, "20260320")

    # Existing behavior: failure recorded in plan dict
    assert plan.selection_artifacts.get("write_status") == "failed"
    assert "simulated disk full" in str(plan.selection_artifacts.get("error_message", ""))

    # NEW behavior (BH-017): failure must also appear in logs
    with caplog.at_level(logging.DEBUG, logger="src.backtesting.engine"):
        # Re-run to capture in fresh caplog context
        plan2 = _make_plan()
        with patch.object(
            engine._selection_artifact_writer,
            "write_for_plan",
            side_effect=RuntimeError("simulated disk full"),
        ):
            engine._write_selection_artifacts(plan2, "20260320")

    assert any(
        "selection artifact" in record.message.lower() or "artifact" in record.message.lower()
        for record in caplog.records
    ), (
        "selection-artifact write failure must be logged (BH-017 observability); "
        "currently the engine records the failure only in plan.selection_artifacts "
        "with no log, so operators monitoring logs miss silently-stopped writes"
    )
