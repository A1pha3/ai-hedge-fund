from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Callable, Sequence

from src.backtesting.engine import BacktestEngine
from src.backtesting.types import PerformanceMetrics
from src.execution.daily_pipeline import DailyPipeline
from src.llm.defaults import get_default_model_config
from src.main import run_hedge_fund
from src.paper_trading.frozen_replay import load_frozen_post_market_plans


def _serialize_portfolio_values(portfolio_values: Sequence[dict]) -> list[dict]:
    serialized: list[dict] = []
    for point in portfolio_values:
        payload = dict(point)
        date_value = payload.get("Date")
        if isinstance(date_value, datetime):
            payload["Date"] = date_value.strftime("%Y-%m-%d")
        serialized.append(payload)
    return serialized


class JsonlPaperTradingRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.day_count = 0
        self.executed_trade_days = 0
        self.total_executed_orders = 0

    def record(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.day_count += 1
        executed_order_count = sum(1 for quantity in payload.get("executed_trades", {}).values() if quantity)
        if executed_order_count > 0:
            self.executed_trade_days += 1
        self.total_executed_orders += executed_order_count
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class PaperTradingArtifacts:
    output_dir: Path
    daily_events_path: Path
    timing_log_path: Path
    summary_path: Path


def run_paper_trading_session(
    *,
    start_date: str,
    end_date: str,
    output_dir: str | Path,
    tickers: list[str] | None = None,
    initial_capital: float = 100000.0,
    model_name: str | None = None,
    model_provider: str | None = None,
    selected_analysts: list[str] | None = None,
    initial_margin_requirement: float = 0.0,
    agent: Callable = run_hedge_fund,
    pipeline: DailyPipeline | None = None,
    frozen_plan_source: str | Path | None = None,
) -> PaperTradingArtifacts:
    resolved_model_name, resolved_model_provider = (model_name, model_provider) if model_name and model_provider else get_default_model_config()

    output_dir_path = Path(output_dir).resolve()
    output_dir_path.mkdir(parents=True, exist_ok=True)
    frozen_plan_source_path = Path(frozen_plan_source).resolve() if frozen_plan_source is not None else None

    daily_events_path = output_dir_path / "daily_events.jsonl"
    timing_log_path = output_dir_path / "pipeline_timings.jsonl"
    summary_path = output_dir_path / "session_summary.json"
    checkpoint_path = output_dir_path / "session.checkpoint.json"

    if frozen_plan_source_path is not None:
        if pipeline is not None:
            raise ValueError("pipeline and frozen_plan_source cannot be used together")
        pipeline = DailyPipeline(
            base_model_name=resolved_model_name,
            base_model_provider=resolved_model_provider,
            frozen_post_market_plans=load_frozen_post_market_plans(frozen_plan_source_path),
            frozen_plan_source=str(frozen_plan_source_path),
        )

    recorder = JsonlPaperTradingRecorder(daily_events_path)
    engine = BacktestEngine(
        agent=agent,
        tickers=tickers or [],
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        model_name=resolved_model_name,
        model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=initial_margin_requirement,
        backtest_mode="pipeline",
        pipeline=pipeline,
        checkpoint_path=str(checkpoint_path),
        pipeline_event_recorder=recorder.record,
    )

    metrics: PerformanceMetrics = engine.run_backtest()
    if engine._timing_log_path is not None and engine._timing_log_path != timing_log_path and engine._timing_log_path.exists():
        engine._timing_log_path.replace(timing_log_path)

    summary = {
        "mode": "paper_trading",
        "start_date": start_date,
        "end_date": end_date,
        "tickers": list(tickers or []),
        "initial_capital": float(initial_capital),
        "model_name": resolved_model_name,
        "model_provider": resolved_model_provider,
        "selected_analysts": selected_analysts,
        "plan_generation": {
            "mode": "frozen_current_plan_replay" if frozen_plan_source_path is not None else "live_pipeline",
            "frozen_plan_source": str(frozen_plan_source_path) if frozen_plan_source_path is not None else None,
        },
        "performance_metrics": dict(metrics),
        "portfolio_values": _serialize_portfolio_values(engine.get_portfolio_values()),
        "final_portfolio_snapshot": engine.get_portfolio_snapshot(),
        "daily_event_stats": {
            "day_count": recorder.day_count,
            "executed_trade_days": recorder.executed_trade_days,
            "total_executed_orders": recorder.total_executed_orders,
        },
        "artifacts": {
            "daily_events": str(daily_events_path),
            "timing_log": str(timing_log_path),
            "summary": str(summary_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return PaperTradingArtifacts(
        output_dir=output_dir_path,
        daily_events_path=daily_events_path,
        timing_log_path=timing_log_path,
        summary_path=summary_path,
    )