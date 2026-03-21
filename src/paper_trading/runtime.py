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
from src.monitoring.llm_metrics import get_llm_metrics_paths
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


def _build_llm_route_provenance() -> tuple[dict, dict]:
    metrics_paths = get_llm_metrics_paths()
    summary_path = Path(metrics_paths["summary_path"])
    jsonl_path = Path(metrics_paths["jsonl_path"])
    artifacts = {
        "llm_metrics_jsonl": str(jsonl_path),
        "llm_metrics_summary": str(summary_path),
    }
    provenance = {
        "session_id": metrics_paths["session_id"],
        "summary_available": False,
        "attempts": 0,
        "successes": 0,
        "errors": 0,
        "rate_limit_errors": 0,
        "fallback_attempts": 0,
        "fallback_observed": False,
        "contaminated_by_provider_fallback": False,
        "providers_seen": [],
        "models_seen": [],
        "routes_seen": [],
    }

    if not summary_path.exists():
        return provenance, artifacts

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        provenance["summary_read_error"] = str(error)
        return provenance, artifacts

    totals = summary.get("totals") or {}
    providers = summary.get("providers") or {}
    models = summary.get("models") or {}
    routes = summary.get("routes") or {}
    fallback_attempts = int(totals.get("fallback_attempts") or 0)

    provenance.update(
        {
            "summary_available": True,
            "attempts": int(totals.get("attempts") or 0),
            "successes": int(totals.get("successes") or 0),
            "errors": int(totals.get("errors") or 0),
            "rate_limit_errors": int(totals.get("rate_limit_errors") or 0),
            "fallback_attempts": fallback_attempts,
            "fallback_observed": fallback_attempts > 0,
            "contaminated_by_provider_fallback": fallback_attempts > 0,
            "providers_seen": sorted(key for key, bucket in providers.items() if int((bucket or {}).get("attempts") or 0) > 0),
            "models_seen": sorted(key for key, bucket in models.items() if int((bucket or {}).get("attempts") or 0) > 0),
            "routes_seen": sorted(key for key, bucket in routes.items() if int((bucket or {}).get("attempts") or 0) > 0),
        }
    )
    return provenance, artifacts


def _empty_llm_observability_summary() -> dict:
    return {
        "jsonl_available": False,
        "entry_count": 0,
        "by_trade_date": {},
        "by_model_tier": {},
        "by_provider": {},
        "context_breakdown": [],
    }


def _update_observability_bucket(bucket: dict, entry: dict) -> None:
    bucket["attempts"] = int(bucket.get("attempts") or 0) + 1
    bucket["successes"] = int(bucket.get("successes") or 0) + (1 if entry.get("success") else 0)
    bucket["errors"] = int(bucket.get("errors") or 0) + (0 if entry.get("success") else 1)
    bucket["rate_limit_errors"] = int(bucket.get("rate_limit_errors") or 0) + (1 if entry.get("is_rate_limit") else 0)
    bucket["fallback_attempts"] = int(bucket.get("fallback_attempts") or 0) + (1 if entry.get("used_fallback") else 0)
    bucket["total_duration_ms"] = round(float(bucket.get("total_duration_ms") or 0.0) + float(entry.get("duration_ms") or 0.0), 3)
    attempts = int(bucket.get("attempts") or 0)
    bucket["avg_duration_ms"] = round(bucket["total_duration_ms"] / attempts, 3) if attempts else 0.0


def _build_llm_observability_summary(jsonl_path: Path) -> dict:
    summary = _empty_llm_observability_summary()
    if not jsonl_path.exists():
        return summary

    try:
        lines = [line for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as error:
        summary["jsonl_read_error"] = str(error)
        return summary

    context_buckets: dict[tuple[str, str, str, str], dict] = {}
    summary["jsonl_available"] = True
    summary["entry_count"] = len(lines)

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        trade_date = str(entry.get("trade_date") or "unknown")
        model_tier = str(entry.get("model_tier") or "unknown")
        pipeline_stage = str(entry.get("pipeline_stage") or "unknown")
        provider = str(entry.get("model_provider") or "unknown")

        _update_observability_bucket(summary["by_trade_date"].setdefault(trade_date, {}), entry)
        _update_observability_bucket(summary["by_model_tier"].setdefault(model_tier, {}), entry)
        _update_observability_bucket(summary["by_provider"].setdefault(provider, {}), entry)

        context_key = (trade_date, pipeline_stage, model_tier, provider)
        context_bucket = context_buckets.setdefault(
            context_key,
            {
                "trade_date": trade_date,
                "pipeline_stage": pipeline_stage,
                "model_tier": model_tier,
                "provider": provider,
            },
        )
        _update_observability_bucket(context_bucket, entry)

    summary["context_breakdown"] = sorted(
        context_buckets.values(),
        key=lambda item: (item["trade_date"], item["pipeline_stage"], item["model_tier"], item["provider"]),
    )
    return summary


def _build_execution_plan_provenance_summary(pipeline: DailyPipeline | None) -> dict:
    observations = list(getattr(pipeline, "execution_plan_provenance_log", []) or [])
    return {
        "observation_count": len(observations),
        "observations": observations,
    }


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

    llm_route_provenance, llm_metrics_artifacts = _build_llm_route_provenance()
    llm_observability_summary = _build_llm_observability_summary(Path(llm_metrics_artifacts["llm_metrics_jsonl"]))
    execution_plan_provenance = _build_execution_plan_provenance_summary(pipeline)

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
        "llm_route_provenance": llm_route_provenance,
        "execution_plan_provenance": execution_plan_provenance,
        "llm_observability_summary": llm_observability_summary,
        "daily_event_stats": {
            "day_count": recorder.day_count,
            "executed_trade_days": recorder.executed_trade_days,
            "total_executed_orders": recorder.total_executed_orders,
        },
        "artifacts": {
            "daily_events": str(daily_events_path),
            "timing_log": str(timing_log_path),
            "summary": str(summary_path),
            **llm_metrics_artifacts,
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return PaperTradingArtifacts(
        output_dir=output_dir_path,
        daily_events_path=daily_events_path,
        timing_log_path=timing_log_path,
        summary_path=summary_path,
    )