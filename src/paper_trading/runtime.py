from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
from typing import Callable, Sequence

from src.backtesting.engine import BacktestEngine
from src.backtesting.types import PerformanceMetrics
from src.data.cache_benchmark import run_cache_reuse_benchmark
from src.data.enhanced_cache import diff_cache_stats, get_cache_runtime_info, snapshot_cache_stats
from src.execution.daily_pipeline import DailyPipeline
from src.llm.defaults import get_default_model_config
from src.main import run_hedge_fund
from src.monitoring.llm_metrics import get_llm_metrics_paths
from src.paper_trading.frozen_replay import load_frozen_post_market_plans
from src.research.artifacts import FileSelectionArtifactWriter
from src.research.feedback import summarize_research_feedback_directory


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


def _build_dual_target_session_summary(daily_events_path: Path) -> dict:
    summary = {
        "day_count": 0,
        "days_with_selection_targets": 0,
        "selection_target_count": 0,
        "research_target_count": 0,
        "short_trade_target_count": 0,
        "research_selected_count": 0,
        "research_near_miss_count": 0,
        "research_rejected_count": 0,
        "short_trade_selected_count": 0,
        "short_trade_near_miss_count": 0,
        "short_trade_blocked_count": 0,
        "short_trade_rejected_count": 0,
        "shell_target_count": 0,
        "target_mode_counts": {},
        "delta_classification_counts": {},
    }
    if not daily_events_path.exists():
        return summary

    try:
        lines = [line for line in daily_events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as error:
        summary["read_error"] = str(error)
        return summary

    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") != "paper_trading_day":
            continue

        summary["day_count"] += 1
        current_plan = dict(payload.get("current_plan") or {})
        target_mode = str(current_plan.get("target_mode") or "research_only")
        summary["target_mode_counts"][target_mode] = int(summary["target_mode_counts"].get(target_mode) or 0) + 1

        selection_targets = dict(current_plan.get("selection_targets") or {})
        if selection_targets:
            summary["days_with_selection_targets"] += 1
        summary["selection_target_count"] += len(selection_targets)

        target_summary = dict(current_plan.get("dual_target_summary") or {})
        summary["research_target_count"] += int(target_summary.get("research_target_count") or 0)
        summary["short_trade_target_count"] += int(target_summary.get("short_trade_target_count") or 0)
        summary["research_selected_count"] += int(target_summary.get("research_selected_count") or 0)
        summary["research_near_miss_count"] += int(target_summary.get("research_near_miss_count") or 0)
        summary["research_rejected_count"] += int(target_summary.get("research_rejected_count") or 0)
        summary["short_trade_selected_count"] += int(target_summary.get("short_trade_selected_count") or 0)
        summary["short_trade_near_miss_count"] += int(target_summary.get("short_trade_near_miss_count") or 0)
        summary["short_trade_blocked_count"] += int(target_summary.get("short_trade_blocked_count") or 0)
        summary["short_trade_rejected_count"] += int(target_summary.get("short_trade_rejected_count") or 0)
        summary["shell_target_count"] += int(target_summary.get("shell_target_count") or 0)
        for key, value in dict(target_summary.get("delta_classification_counts") or {}).items():
            summary["delta_classification_counts"][str(key)] = int(summary["delta_classification_counts"].get(str(key)) or 0) + int(value or 0)

    return summary


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
    selection_artifact_root: Path
    feedback_summary_path: Path


def _reset_output_artifacts_for_fresh_run(
    *,
    checkpoint_path: Path,
    daily_events_path: Path,
    timing_log_path: Path,
    selection_artifact_root: Path,
) -> None:
    if checkpoint_path.exists():
        return

    checkpoint_timing_log_path = checkpoint_path.with_name(f"{checkpoint_path.stem}.timings.jsonl")
    for stale_file in (daily_events_path, timing_log_path, checkpoint_timing_log_path):
        if stale_file.exists():
            stale_file.unlink()

    if selection_artifact_root.exists():
        shutil.rmtree(selection_artifact_root)


def _write_research_feedback_summary(selection_artifact_root: Path) -> tuple[dict, Path]:
    feedback_summary_path = selection_artifact_root / "research_feedback_summary.json"
    summary = summarize_research_feedback_directory(artifact_root=selection_artifact_root)
    feedback_summary_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_summary_path.write_text(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return summary.model_dump(mode="json"), feedback_summary_path


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
    selection_target: str = "research_only",
    cache_benchmark: bool = False,
    cache_benchmark_ticker: str | None = None,
    cache_benchmark_clear_first: bool = False,
) -> PaperTradingArtifacts:
    resolved_model_name, resolved_model_provider = (model_name, model_provider) if model_name and model_provider else get_default_model_config()

    output_dir_path = Path(output_dir).resolve()
    output_dir_path.mkdir(parents=True, exist_ok=True)
    frozen_plan_source_path = Path(frozen_plan_source).resolve() if frozen_plan_source is not None else None

    daily_events_path = output_dir_path / "daily_events.jsonl"
    timing_log_path = output_dir_path / "pipeline_timings.jsonl"
    summary_path = output_dir_path / "session_summary.json"
    checkpoint_path = output_dir_path / "session.checkpoint.json"
    selection_artifact_root = output_dir_path / "selection_artifacts"

    _reset_output_artifacts_for_fresh_run(
        checkpoint_path=checkpoint_path,
        daily_events_path=daily_events_path,
        timing_log_path=timing_log_path,
        selection_artifact_root=selection_artifact_root,
    )

    if frozen_plan_source_path is not None:
        if pipeline is not None:
            raise ValueError("pipeline and frozen_plan_source cannot be used together")
        pipeline = DailyPipeline(
            base_model_name=resolved_model_name,
            base_model_provider=resolved_model_provider,
            frozen_post_market_plans=load_frozen_post_market_plans(frozen_plan_source_path),
            frozen_plan_source=str(frozen_plan_source_path),
            target_mode=selection_target,
        )
    elif pipeline is None:
        pipeline = DailyPipeline(
            base_model_name=resolved_model_name,
            base_model_provider=resolved_model_provider,
            target_mode=selection_target,
        )

    cache_stats_before_run = snapshot_cache_stats()

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
        selection_artifact_writer=FileSelectionArtifactWriter(
            artifact_root=selection_artifact_root,
            run_id=output_dir_path.name,
        ),
    )

    metrics: PerformanceMetrics = engine.run_backtest()
    if engine._timing_log_path is not None and engine._timing_log_path != timing_log_path and engine._timing_log_path.exists():
        engine._timing_log_path.replace(timing_log_path)

    research_feedback_summary, feedback_summary_path = _write_research_feedback_summary(selection_artifact_root)

    llm_route_provenance, llm_metrics_artifacts = _build_llm_route_provenance()
    llm_observability_summary = _build_llm_observability_summary(Path(llm_metrics_artifacts["llm_metrics_jsonl"]))
    execution_plan_provenance = _build_execution_plan_provenance_summary(getattr(engine, "_pipeline", None))
    dual_target_summary = _build_dual_target_session_summary(daily_events_path)
    data_cache_summary = get_cache_runtime_info()
    data_cache_summary["session_stats"] = diff_cache_stats(cache_stats_before_run, data_cache_summary.get("stats", {}))

    cache_benchmark_summary = None
    cache_benchmark_artifacts: dict[str, str] = {}
    cache_benchmark_status = {
        "requested": bool(cache_benchmark),
        "executed": False,
        "write_status": "not_requested" if not cache_benchmark else "skipped",
        "reason": None,
    }
    benchmark_ticker = cache_benchmark_ticker or (tickers[0] if tickers else None)
    if cache_benchmark and benchmark_ticker:
        cache_benchmark_json_path = output_dir_path / "data_cache_benchmark.json"
        cache_benchmark_markdown_path = output_dir_path / "data_cache_benchmark.md"
        cache_benchmark_append_path = output_dir_path / "window_review.md"
        try:
            cache_benchmark_summary = run_cache_reuse_benchmark(
                repo_root=Path(__file__).resolve().parents[2],
                python_executable=sys.executable,
                trade_date=end_date.replace("-", ""),
                ticker=benchmark_ticker,
                clear_first=cache_benchmark_clear_first,
                output_path=cache_benchmark_json_path,
                markdown_output_path=cache_benchmark_markdown_path,
                append_markdown_to=cache_benchmark_append_path,
            )
            cache_benchmark_artifacts = {
                "data_cache_benchmark_json": str(cache_benchmark_json_path),
                "data_cache_benchmark_markdown": str(cache_benchmark_markdown_path),
                "data_cache_benchmark_appended_report": str(cache_benchmark_append_path),
            }
            cache_benchmark_status = {
                "requested": True,
                "executed": True,
                "write_status": "success",
                "reason": None,
            }
        except Exception as error:
            cache_benchmark_summary = {
                "requested": True,
                "executed": False,
                "write_status": "failed",
                "reason": str(error),
                "ticker": benchmark_ticker,
                "trade_date": end_date.replace("-", ""),
            }
            cache_benchmark_status = {
                "requested": True,
                "executed": False,
                "write_status": "failed",
                "reason": str(error),
            }
    elif cache_benchmark:
        cache_benchmark_summary = {
            "requested": True,
            "executed": False,
            "write_status": "skipped",
            "reason": "no benchmark ticker available",
        }
        cache_benchmark_status = {
            "requested": True,
            "executed": False,
            "write_status": "skipped",
            "reason": "no benchmark ticker available",
        }

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
            "selection_target": selection_target,
        },
        "performance_metrics": dict(metrics),
        "portfolio_values": _serialize_portfolio_values(engine.get_portfolio_values()),
        "final_portfolio_snapshot": engine.get_portfolio_snapshot(),
        "llm_route_provenance": llm_route_provenance,
        "execution_plan_provenance": execution_plan_provenance,
        "dual_target_summary": dual_target_summary,
        "llm_observability_summary": llm_observability_summary,
        "data_cache": data_cache_summary,
        "data_cache_benchmark": cache_benchmark_summary,
        "data_cache_benchmark_status": cache_benchmark_status,
        "research_feedback_summary": research_feedback_summary,
        "daily_event_stats": {
            "day_count": recorder.day_count,
            "executed_trade_days": recorder.executed_trade_days,
            "total_executed_orders": recorder.total_executed_orders,
        },
        "artifacts": {
            "daily_events": str(daily_events_path),
            "timing_log": str(timing_log_path),
            "summary": str(summary_path),
            "selection_artifact_root": str(selection_artifact_root),
            "research_feedback_summary": str(feedback_summary_path),
            "data_cache_path": data_cache_summary.get("disk_path"),
            **cache_benchmark_artifacts,
            **llm_metrics_artifacts,
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return PaperTradingArtifacts(
        output_dir=output_dir_path,
        daily_events_path=daily_events_path,
        timing_log_path=timing_log_path,
        summary_path=summary_path,
        selection_artifact_root=selection_artifact_root,
        feedback_summary_path=feedback_summary_path,
    )