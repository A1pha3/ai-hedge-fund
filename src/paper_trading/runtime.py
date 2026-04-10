from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Callable, Iterator, Sequence

from src.backtesting.engine import BacktestEngine
from src.backtesting.types import PerformanceMetrics
from src.data.cache_benchmark import run_cache_reuse_benchmark
from src.data.enhanced_cache import diff_cache_stats, get_cache_runtime_info, snapshot_cache_stats
from src.execution.daily_pipeline import DailyPipeline
from src.llm.defaults import get_default_model_config
from src.main import run_hedge_fund
from src.monitoring.llm_metrics import get_llm_metrics_paths
from src.paper_trading.frozen_replay import load_frozen_post_market_plans
from src.paper_trading.runtime_session_helpers import build_session_summary, resolve_pipeline, resolve_session_paths, run_optional_cache_benchmark
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
    artifacts = _build_llm_route_artifacts(summary_path, jsonl_path)
    provenance = _build_empty_llm_route_provenance(session_id=str(metrics_paths["session_id"]))

    if not summary_path.exists():
        return provenance, artifacts

    summary, summary_read_error = _read_llm_metrics_summary(summary_path)
    if summary_read_error is not None:
        provenance["summary_read_error"] = summary_read_error
        return provenance, artifacts
    provenance.update(_build_llm_route_summary_payload(summary))
    return provenance, artifacts


def _build_llm_route_artifacts(summary_path: Path, jsonl_path: Path) -> dict:
    return {
        "llm_metrics_jsonl": str(jsonl_path),
        "llm_metrics_summary": str(summary_path),
    }


def _build_empty_llm_route_provenance(*, session_id: str) -> dict:
    return {
        "session_id": session_id,
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


def _read_llm_metrics_summary(summary_path: Path) -> tuple[dict, str | None]:
    try:
        return json.loads(summary_path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as error:
        return {}, str(error)


def _build_llm_route_summary_payload(summary: dict) -> dict:
    totals = summary.get("totals") or {}
    providers = summary.get("providers") or {}
    models = summary.get("models") or {}
    routes = summary.get("routes") or {}
    fallback_attempts = int(totals.get("fallback_attempts") or 0)
    return {
        "summary_available": True,
        "attempts": int(totals.get("attempts") or 0),
        "successes": int(totals.get("successes") or 0),
        "errors": int(totals.get("errors") or 0),
        "rate_limit_errors": int(totals.get("rate_limit_errors") or 0),
        "fallback_attempts": fallback_attempts,
        "fallback_observed": fallback_attempts > 0,
        "contaminated_by_provider_fallback": fallback_attempts > 0,
        "providers_seen": _collect_llm_seen_keys(providers),
        "models_seen": _collect_llm_seen_keys(models),
        "routes_seen": _collect_llm_seen_keys(routes),
    }


def _collect_llm_seen_keys(buckets: dict) -> list[str]:
    return sorted(key for key, bucket in buckets.items() if int((bucket or {}).get("attempts") or 0) > 0)


def _empty_llm_observability_summary() -> dict:
    return {
        "jsonl_available": False,
        "entry_count": 0,
        "by_trade_date": {},
        "by_model_tier": {},
        "by_provider": {},
        "context_breakdown": [],
        "error_type_counts": {},
        "sample_errors": [],
    }


def _update_observability_bucket(bucket: dict, entry: dict) -> None:
    bucket.setdefault("error_types", {})
    bucket["attempts"] = int(bucket.get("attempts") or 0) + 1
    bucket["successes"] = int(bucket.get("successes") or 0) + (1 if entry.get("success") else 0)
    bucket["errors"] = int(bucket.get("errors") or 0) + (0 if entry.get("success") else 1)
    bucket["rate_limit_errors"] = int(bucket.get("rate_limit_errors") or 0) + (1 if entry.get("is_rate_limit") else 0)
    bucket["fallback_attempts"] = int(bucket.get("fallback_attempts") or 0) + (1 if entry.get("used_fallback") else 0)
    bucket["total_duration_ms"] = round(float(bucket.get("total_duration_ms") or 0.0) + float(entry.get("duration_ms") or 0.0), 3)
    attempts = int(bucket.get("attempts") or 0)
    bucket["avg_duration_ms"] = round(bucket["total_duration_ms"] / attempts, 3) if attempts else 0.0
    error_type = str(entry.get("error_type") or "").strip()
    if error_type:
        error_types = bucket.setdefault("error_types", {})
        error_types[error_type] = int(error_types.get(error_type) or 0) + 1


def _normalize_llm_error_message(message: str | None) -> str | None:
    normalized = " ".join(str(message or "").split()).strip()
    if not normalized:
        return None
    return normalized[:240]


def _record_observability_error(summary: dict, entry: dict) -> None:
    error_type = str(entry.get("error_type") or "").strip()
    error_message = _normalize_llm_error_message(entry.get("error_message"))
    if not error_type and not error_message:
        return

    if error_type:
        error_type_counts = summary.setdefault("error_type_counts", {})
        error_type_counts[error_type] = int(error_type_counts.get(error_type) or 0) + 1

    sample_errors = summary.setdefault("sample_errors", [])
    sample = {
        "trade_date": str(entry.get("trade_date") or "unknown"),
        "pipeline_stage": str(entry.get("pipeline_stage") or "unknown"),
        "model_tier": str(entry.get("model_tier") or "unknown"),
        "provider": str(entry.get("model_provider") or "unknown"),
        "error_type": error_type or "unknown",
        "message": error_message or "n/a",
    }
    sample_key = tuple(sample.values())
    existing_keys = {tuple(item.get(field) for field in ("trade_date", "pipeline_stage", "model_tier", "provider", "error_type", "message")) for item in sample_errors}
    if sample_key in existing_keys:
        return
    if len(sample_errors) < 5:
        sample_errors.append(sample)


def _sorted_error_type_counts(error_type_counts: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    rows = [
        {"error_type": str(error_type), "count": int(count or 0)}
        for error_type, count in dict(error_type_counts or {}).items()
        if int(count or 0) > 0
    ]
    rows.sort(key=lambda item: (-item["count"], item["error_type"]))
    return rows[:limit]


def _build_llm_error_digest(llm_route_provenance: dict, llm_observability_summary: dict) -> dict:
    route = dict(llm_route_provenance or {})
    observability = dict(llm_observability_summary or {})
    error_count = int(route.get("errors") or 0)
    rate_limit_error_count = int(route.get("rate_limit_errors") or 0)
    fallback_attempt_count = int(route.get("fallback_attempts") or 0)
    affected_providers = _build_affected_provider_rows(observability)
    fallback_gap_detected = _detect_fallback_gap(route, error_count, fallback_attempt_count)
    status, recommendation = _resolve_llm_error_digest_status(
        route=route,
        observability=observability,
        error_count=error_count,
        rate_limit_error_count=rate_limit_error_count,
        fallback_gap_detected=fallback_gap_detected,
    )

    return {
        "status": status,
        "error_count": error_count,
        "rate_limit_error_count": rate_limit_error_count,
        "fallback_attempt_count": fallback_attempt_count,
        "affected_provider_count": len(affected_providers),
        "top_error_types": _sorted_error_type_counts(dict(observability.get("error_type_counts") or {})),
        "affected_providers": affected_providers[:3],
        "sample_errors": list(observability.get("sample_errors") or [])[:3],
        "fallback_gap_detected": fallback_gap_detected,
        "recommendation": recommendation,
    }

def _build_affected_provider_rows(observability: dict) -> list[dict]:
    affected_providers = []
    for provider, bucket in dict(observability.get("by_provider") or {}).items():
        errors = int((bucket or {}).get("errors") or 0)
        attempts = int((bucket or {}).get("attempts") or 0)
        if errors <= 0:
            continue
        affected_providers.append(
            {
                "provider": str(provider),
                "attempts": attempts,
                "errors": errors,
                "error_rate": round((errors / attempts), 4) if attempts else 0.0,
                "rate_limit_errors": int((bucket or {}).get("rate_limit_errors") or 0),
                "fallback_attempts": int((bucket or {}).get("fallback_attempts") or 0),
                "top_error_types": _sorted_error_type_counts(dict((bucket or {}).get("error_types") or {}), limit=2),
            }
        )
    affected_providers.sort(key=lambda item: (-item["errors"], -item["error_rate"], item["provider"]))
    return affected_providers


def _detect_fallback_gap(route: dict, error_count: int, fallback_attempt_count: int) -> bool:
    return error_count > 0 and fallback_attempt_count == 0 and len(list(route.get("providers_seen") or [])) > 1


def _resolve_llm_error_digest_status(
    *,
    route: dict,
    observability: dict,
    error_count: int,
    rate_limit_error_count: int,
    fallback_gap_detected: bool,
) -> tuple[str, str]:
    if not route.get("summary_available") and not observability.get("jsonl_available"):
        return "no_data", "no_llm_metrics_available"
    if error_count > 0:
        if rate_limit_error_count > 0:
            return "degraded", "rate_limit_pressure_detected_consider_cooldown_or_concurrency_reduction"
        if fallback_gap_detected:
            return "degraded", "errors_detected_without_fallback_review_provider_routing"
        return "degraded", "review_top_error_types_and_provider_breakdown"
    return "healthy", "no_action_needed"


def _build_llm_observability_summary(jsonl_path: Path) -> dict:
    summary = _empty_llm_observability_summary()
    if not jsonl_path.exists():
        return summary

    try:
        lines = _read_non_empty_jsonl_lines(jsonl_path)
    except OSError as error:
        summary["jsonl_read_error"] = str(error)
        return summary

    summary["jsonl_available"] = True
    summary["entry_count"] = len(lines)
    context_buckets: dict[tuple[str, str, str, str], dict] = {}

    for line in lines:
        entry = _parse_observability_entry(line)
        if entry is None:
            continue
        _accumulate_observability_entry(summary, context_buckets, entry)

    summary["context_breakdown"] = _build_sorted_context_breakdown(context_buckets)
    return summary


def _read_non_empty_jsonl_lines(jsonl_path: Path) -> list[str]:
    return [line for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _parse_observability_entry(line: str) -> dict | None:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _accumulate_observability_entry(summary: dict, context_buckets: dict[tuple[str, str, str, str], dict], entry: dict) -> None:
    trade_date = str(entry.get("trade_date") or "unknown")
    model_tier = str(entry.get("model_tier") or "unknown")
    pipeline_stage = str(entry.get("pipeline_stage") or "unknown")
    provider = str(entry.get("model_provider") or "unknown")

    _update_observability_bucket(summary["by_trade_date"].setdefault(trade_date, {}), entry)
    _update_observability_bucket(summary["by_model_tier"].setdefault(model_tier, {}), entry)
    _update_observability_bucket(summary["by_provider"].setdefault(provider, {}), entry)
    if not entry.get("success"):
        _record_observability_error(summary, entry)

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


def _build_sorted_context_breakdown(context_buckets: dict[tuple[str, str, str, str], dict]) -> list[dict]:
    return sorted(
        context_buckets.values(),
        key=lambda item: (item["trade_date"], item["pipeline_stage"], item["model_tier"], item["provider"]),
    )


def _build_execution_plan_provenance_summary(pipeline: DailyPipeline | None) -> dict:
    observations = list(getattr(pipeline, "execution_plan_provenance_log", []) or [])
    return {
        "observation_count": len(observations),
        "observations": observations,
    }


def _build_dual_target_session_summary(daily_events_path: Path) -> dict:
    summary = _build_empty_dual_target_session_summary()
    if not daily_events_path.exists():
        return summary

    lines, read_error = _read_daily_event_lines(daily_events_path)
    if read_error is not None:
        summary["read_error"] = read_error
        return summary

    for payload in _iter_paper_trading_day_payloads(lines):
        _accumulate_dual_target_day(summary, payload)
    return summary


def _build_empty_dual_target_session_summary() -> dict:
    return {
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


def _read_daily_event_lines(daily_events_path: Path) -> tuple[list[str], str | None]:
    try:
        return [line for line in daily_events_path.read_text(encoding="utf-8").splitlines() if line.strip()], None
    except OSError as error:
        return [], str(error)


def _iter_paper_trading_day_payloads(lines: list[str]) -> Iterator[dict]:
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") != "paper_trading_day":
            continue
        yield payload


def _accumulate_dual_target_day(summary: dict, payload: dict) -> None:
    summary["day_count"] += 1
    current_plan = dict(payload.get("current_plan") or {})
    target_mode = str(current_plan.get("target_mode") or "research_only")
    summary["target_mode_counts"][target_mode] = int(summary["target_mode_counts"].get(target_mode) or 0) + 1

    selection_targets = dict(current_plan.get("selection_targets") or {})
    if selection_targets:
        summary["days_with_selection_targets"] += 1
    summary["selection_target_count"] += len(selection_targets)

    target_summary = dict(current_plan.get("dual_target_summary") or {})
    _accumulate_dual_target_counts(summary, target_summary)
    _accumulate_delta_classification_counts(summary, target_summary)


def _accumulate_dual_target_counts(summary: dict, target_summary: dict) -> None:
    count_keys = (
        "research_target_count",
        "short_trade_target_count",
        "research_selected_count",
        "research_near_miss_count",
        "research_rejected_count",
        "short_trade_selected_count",
        "short_trade_near_miss_count",
        "short_trade_blocked_count",
        "short_trade_rejected_count",
        "shell_target_count",
    )
    for key in count_keys:
        summary[key] += int(target_summary.get(key) or 0)


def _accumulate_delta_classification_counts(summary: dict, target_summary: dict) -> None:
    for key, value in dict(target_summary.get("delta_classification_counts") or {}).items():
        summary["delta_classification_counts"][str(key)] = int(summary["delta_classification_counts"].get(str(key)) or 0) + int(value or 0)


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


@dataclass(frozen=True)
class SessionRuntimeContext:
    resolved_model_name: str
    resolved_model_provider: str
    session_paths: Any
    pipeline: DailyPipeline
    cache_stats_before_run: dict
    recorder: JsonlPaperTradingRecorder
    engine: BacktestEngine


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


def _prepare_session_runtime_context(
    *,
    output_dir: str | Path,
    frozen_plan_source: str | Path | None,
    model_name: str | None,
    model_provider: str | None,
    pipeline: DailyPipeline | None,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    agent: Callable,
    tickers: list[str] | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
    initial_margin_requirement: float,
) -> SessionRuntimeContext:
    resolved_model_name, resolved_model_provider = _resolve_runtime_model_config(model_name=model_name, model_provider=model_provider)
    session_paths, resolved_pipeline = _resolve_runtime_session_dependencies(
        output_dir=output_dir,
        frozen_plan_source=frozen_plan_source,
        pipeline=pipeline,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
    )
    recorder, engine = _build_runtime_recorder_and_engine(
        **_build_runtime_engine_inputs(
            agent=agent,
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            resolved_model_name=resolved_model_name,
            resolved_model_provider=resolved_model_provider,
            selected_analysts=selected_analysts,
            initial_margin_requirement=initial_margin_requirement,
            pipeline=resolved_pipeline,
            session_paths=session_paths,
        )
    )
    return _build_session_runtime_context(
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        session_paths=session_paths,
        pipeline=resolved_pipeline,
        recorder=recorder,
        engine=engine,
    )


def _build_runtime_engine_inputs(
    *,
    agent: Callable,
    tickers: list[str] | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    initial_margin_requirement: float,
    pipeline: DailyPipeline,
    session_paths: Any,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "tickers": tickers,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "resolved_model_name": resolved_model_name,
        "resolved_model_provider": resolved_model_provider,
        "selected_analysts": selected_analysts,
        "initial_margin_requirement": initial_margin_requirement,
        "pipeline": pipeline,
        "session_paths": session_paths,
    }


def _resolve_runtime_model_config(*, model_name: str | None, model_provider: str | None) -> tuple[str, str]:
    return (model_name, model_provider) if model_name and model_provider else get_default_model_config()


def _reset_runtime_outputs(session_paths: Any) -> None:
    _reset_output_artifacts_for_fresh_run(
        checkpoint_path=session_paths.checkpoint_path,
        daily_events_path=session_paths.daily_events_path,
        timing_log_path=session_paths.timing_log_path,
        selection_artifact_root=session_paths.selection_artifact_root,
    )


def _resolve_runtime_session_dependencies(
    *,
    output_dir: str | Path,
    frozen_plan_source: str | Path | None,
    pipeline: DailyPipeline | None,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
) -> tuple[Any, DailyPipeline]:
    session_paths = resolve_session_paths(output_dir=output_dir, frozen_plan_source=frozen_plan_source)
    _reset_runtime_outputs(session_paths)
    resolved_pipeline = _resolve_runtime_pipeline(
        pipeline=pipeline,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        frozen_plan_source_path=session_paths.frozen_plan_source_path,
    )
    return session_paths, resolved_pipeline


def _build_session_runtime_context(
    *,
    resolved_model_name: str,
    resolved_model_provider: str,
    session_paths: Any,
    pipeline: DailyPipeline,
    recorder: JsonlPaperTradingRecorder,
    engine: BacktestEngine,
) -> SessionRuntimeContext:
    return SessionRuntimeContext(
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        session_paths=session_paths,
        pipeline=pipeline,
        cache_stats_before_run=snapshot_cache_stats(),
        recorder=recorder,
        engine=engine,
    )


def _resolve_runtime_pipeline(
    *,
    pipeline: DailyPipeline | None,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    frozen_plan_source_path: Path | None,
) -> DailyPipeline:
    return resolve_pipeline(
        pipeline=pipeline,
        frozen_plan_source_path=frozen_plan_source_path,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        pipeline_cls=DailyPipeline,
        load_frozen_post_market_plans=load_frozen_post_market_plans,
    )


def _build_runtime_recorder_and_engine(
    *,
    agent: Callable,
    tickers: list[str] | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    initial_margin_requirement: float,
    pipeline: DailyPipeline,
    session_paths: Any,
) -> tuple[JsonlPaperTradingRecorder, BacktestEngine]:
    recorder = _build_runtime_recorder(session_paths)
    engine = _build_paper_trading_engine(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=initial_margin_requirement,
        pipeline=pipeline,
        session_paths=session_paths,
        recorder=recorder,
    )
    return recorder, engine


def _build_runtime_recorder(session_paths: Any) -> JsonlPaperTradingRecorder:
    return JsonlPaperTradingRecorder(session_paths.daily_events_path)


def _build_paper_trading_engine(
    *,
    agent: Callable,
    tickers: list[str] | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    initial_margin_requirement: float,
    pipeline: DailyPipeline,
    session_paths,
    recorder: JsonlPaperTradingRecorder,
) -> BacktestEngine:
    selection_artifact_writer = _build_selection_artifact_writer(session_paths)
    return BacktestEngine(
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
        checkpoint_path=str(session_paths.checkpoint_path),
        pipeline_event_recorder=recorder.record,
        selection_artifact_writer=selection_artifact_writer,
    )


def _build_selection_artifact_writer(session_paths: Any) -> FileSelectionArtifactWriter:
    return FileSelectionArtifactWriter(
        artifact_root=session_paths.selection_artifact_root,
        run_id=session_paths.output_dir_path.name,
    )


def _finalize_paper_trading_session(
    *,
    context: SessionRuntimeContext,
    metrics: PerformanceMetrics,
    start_date: str,
    end_date: str,
    tickers: list[str] | None,
    initial_capital: float,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    cache_benchmark: bool,
    cache_benchmark_ticker: str | None,
    cache_benchmark_clear_first: bool,
) -> tuple[dict, Path]:
    research_feedback_summary, feedback_summary_path = _write_research_feedback_summary(context.session_paths.selection_artifact_root)
    monitoring_summary = _build_runtime_monitoring_summary(context)
    data_cache_summary = _build_runtime_data_cache_summary(context)
    cache_benchmark_summary, cache_benchmark_artifacts, cache_benchmark_status = _run_runtime_cache_benchmark(
        context=context,
        cache_benchmark=cache_benchmark,
        cache_benchmark_ticker=cache_benchmark_ticker,
        tickers=tickers,
        end_date=end_date,
        cache_benchmark_clear_first=cache_benchmark_clear_first,
    )
    summary = build_session_summary(
        **_build_runtime_session_summary_inputs(
            context=context,
            metrics=metrics,
            start_date=start_date,
            end_date=end_date,
            tickers=tickers,
            initial_capital=initial_capital,
            selected_analysts=selected_analysts,
            fast_selected_analysts=fast_selected_analysts,
            short_trade_target_profile_name=short_trade_target_profile_name,
            short_trade_target_profile_overrides=short_trade_target_profile_overrides,
            selection_target=selection_target,
            research_feedback_summary=research_feedback_summary,
            feedback_summary_path=feedback_summary_path,
            monitoring_summary=monitoring_summary,
            data_cache_summary=data_cache_summary,
            cache_benchmark_summary=cache_benchmark_summary,
            cache_benchmark_artifacts=cache_benchmark_artifacts,
            cache_benchmark_status=cache_benchmark_status,
        )
    )
    _write_runtime_summary(context.session_paths.summary_path, summary)
    return summary, feedback_summary_path


def _build_runtime_session_summary_inputs(
    *,
    context: SessionRuntimeContext,
    metrics: PerformanceMetrics,
    start_date: str,
    end_date: str,
    tickers: list[str] | None,
    initial_capital: float,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    research_feedback_summary: dict,
    feedback_summary_path: Path,
    monitoring_summary: dict,
    data_cache_summary: dict,
    cache_benchmark_summary: dict,
    cache_benchmark_artifacts: dict,
    cache_benchmark_status: str,
) -> dict:
    return {
        **_build_runtime_session_summary_metadata(
            context=context,
            start_date=start_date,
            end_date=end_date,
            tickers=tickers,
            initial_capital=initial_capital,
            selected_analysts=selected_analysts,
            fast_selected_analysts=fast_selected_analysts,
            short_trade_target_profile_name=short_trade_target_profile_name,
            short_trade_target_profile_overrides=short_trade_target_profile_overrides,
            selection_target=selection_target,
        ),
        "metrics": dict(metrics),
        "portfolio_values": _serialize_portfolio_values(context.engine.get_portfolio_values()),
        "final_portfolio_snapshot": context.engine.get_portfolio_snapshot(),
        **_build_runtime_session_monitoring_inputs(monitoring_summary),
        "data_cache_summary": data_cache_summary,
        "cache_benchmark_summary": cache_benchmark_summary,
        "cache_benchmark_status": cache_benchmark_status,
        "research_feedback_summary": research_feedback_summary,
        **_build_runtime_session_recorder_inputs(context),
        **_build_runtime_session_artifact_inputs(
            context=context,
            feedback_summary_path=feedback_summary_path,
            cache_benchmark_artifacts=cache_benchmark_artifacts,
            llm_metrics_artifacts=monitoring_summary["llm_metrics_artifacts"],
        ),
    }


def _build_runtime_session_summary_metadata(
    *,
    context: SessionRuntimeContext,
    start_date: str,
    end_date: str,
    tickers: list[str] | None,
    initial_capital: float,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
) -> dict:
    return {
        "start_date": start_date,
        "end_date": end_date,
        "tickers": tickers,
        "initial_capital": initial_capital,
        "resolved_model_name": context.resolved_model_name,
        "resolved_model_provider": context.resolved_model_provider,
        "selected_analysts": selected_analysts,
        "fast_selected_analysts": fast_selected_analysts,
        "short_trade_target_profile_name": short_trade_target_profile_name,
        "short_trade_target_profile_overrides": short_trade_target_profile_overrides,
        "frozen_plan_source_path": context.session_paths.frozen_plan_source_path,
        "selection_target": selection_target,
    }


def _build_runtime_session_monitoring_inputs(monitoring_summary: dict) -> dict:
    return {
        "llm_route_provenance": monitoring_summary["llm_route_provenance"],
        "execution_plan_provenance": monitoring_summary["execution_plan_provenance"],
        "dual_target_summary": monitoring_summary["dual_target_summary"],
        "llm_observability_summary": monitoring_summary["llm_observability_summary"],
        "llm_error_digest": monitoring_summary["llm_error_digest"],
    }


def _build_runtime_session_recorder_inputs(context: SessionRuntimeContext) -> dict:
    return {
        "recorder_day_count": context.recorder.day_count,
        "recorder_executed_trade_days": context.recorder.executed_trade_days,
        "recorder_total_executed_orders": context.recorder.total_executed_orders,
    }


def _build_runtime_session_artifact_inputs(
    *,
    context: SessionRuntimeContext,
    feedback_summary_path: Path,
    cache_benchmark_artifacts: dict,
    llm_metrics_artifacts: dict,
) -> dict:
    return {
        "daily_events_path": context.session_paths.daily_events_path,
        "timing_log_path": context.session_paths.timing_log_path,
        "summary_path": context.session_paths.summary_path,
        "selection_artifact_root": context.session_paths.selection_artifact_root,
        "feedback_summary_path": feedback_summary_path,
        "cache_benchmark_artifacts": cache_benchmark_artifacts,
        "llm_metrics_artifacts": llm_metrics_artifacts,
    }


def _build_runtime_monitoring_summary(context: SessionRuntimeContext) -> dict:
    llm_route_provenance, llm_metrics_artifacts = _build_llm_route_provenance()
    llm_observability_summary = _build_llm_observability_summary(Path(llm_metrics_artifacts["llm_metrics_jsonl"]))
    return {
        "llm_route_provenance": llm_route_provenance,
        "llm_metrics_artifacts": llm_metrics_artifacts,
        "llm_observability_summary": llm_observability_summary,
        "llm_error_digest": _build_llm_error_digest(llm_route_provenance, llm_observability_summary),
        "execution_plan_provenance": _build_execution_plan_provenance_summary(getattr(context.engine, "_pipeline", None)),
        "dual_target_summary": _build_dual_target_session_summary(context.session_paths.daily_events_path),
    }


def _build_runtime_data_cache_summary(context: SessionRuntimeContext) -> dict:
    data_cache_summary = get_cache_runtime_info()
    data_cache_summary["session_stats"] = diff_cache_stats(context.cache_stats_before_run, data_cache_summary.get("stats", {}))
    return data_cache_summary


def _run_runtime_cache_benchmark(
    *,
    context: SessionRuntimeContext,
    cache_benchmark: bool,
    cache_benchmark_ticker: str | None,
    tickers: list[str] | None,
    end_date: str,
    cache_benchmark_clear_first: bool,
) -> tuple[dict, dict, str]:
    return run_optional_cache_benchmark(
        cache_benchmark=cache_benchmark,
        cache_benchmark_ticker=cache_benchmark_ticker,
        tickers=tickers,
        output_dir_path=context.session_paths.output_dir_path,
        end_date=end_date,
        cache_benchmark_clear_first=cache_benchmark_clear_first,
        run_cache_reuse_benchmark=run_cache_reuse_benchmark,
        repo_root=Path(__file__).resolve().parents[2],
        python_executable=sys.executable,
    )


def _write_runtime_summary(summary_path: Path, summary: dict) -> None:
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _promote_runtime_timing_log(context: SessionRuntimeContext) -> None:
    engine_timing_log_path = context.engine._timing_log_path
    session_timing_log_path = context.session_paths.timing_log_path
    if engine_timing_log_path is None:
        return
    if engine_timing_log_path == session_timing_log_path:
        return
    if not engine_timing_log_path.exists():
        return
    engine_timing_log_path.replace(session_timing_log_path)


def _build_runtime_artifacts(context: SessionRuntimeContext, feedback_summary_path: Path) -> PaperTradingArtifacts:
    return PaperTradingArtifacts(
        output_dir=context.session_paths.output_dir_path,
        daily_events_path=context.session_paths.daily_events_path,
        timing_log_path=context.session_paths.timing_log_path,
        summary_path=context.session_paths.summary_path,
        selection_artifact_root=context.session_paths.selection_artifact_root,
        feedback_summary_path=feedback_summary_path,
    )


def _run_runtime_backtest(context: SessionRuntimeContext) -> PerformanceMetrics:
    metrics: PerformanceMetrics = context.engine.run_backtest()
    _promote_runtime_timing_log(context)
    return metrics


def _finalize_runtime_run(
    *,
    context: SessionRuntimeContext,
    metrics: PerformanceMetrics,
    start_date: str,
    end_date: str,
    tickers: list[str] | None,
    initial_capital: float,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    cache_benchmark: bool,
    cache_benchmark_ticker: str | None,
    cache_benchmark_clear_first: bool,
) -> PaperTradingArtifacts:
    _, feedback_summary_path = _finalize_paper_trading_session(
        **_build_runtime_finalization_inputs(
            context=context,
            metrics=metrics,
            start_date=start_date,
            end_date=end_date,
            tickers=tickers,
            initial_capital=initial_capital,
            selected_analysts=selected_analysts,
            fast_selected_analysts=fast_selected_analysts,
            short_trade_target_profile_name=short_trade_target_profile_name,
            short_trade_target_profile_overrides=short_trade_target_profile_overrides,
            selection_target=selection_target,
            cache_benchmark=cache_benchmark,
            cache_benchmark_ticker=cache_benchmark_ticker,
            cache_benchmark_clear_first=cache_benchmark_clear_first,
        )
    )
    return _build_runtime_artifacts(context, feedback_summary_path)


def _build_runtime_finalization_inputs(
    *,
    context: SessionRuntimeContext,
    metrics: PerformanceMetrics,
    start_date: str,
    end_date: str,
    tickers: list[str] | None,
    initial_capital: float,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    cache_benchmark: bool,
    cache_benchmark_ticker: str | None,
    cache_benchmark_clear_first: bool,
) -> dict[str, Any]:
    return {
        "context": context,
        "metrics": metrics,
        "start_date": start_date,
        "end_date": end_date,
        "tickers": tickers,
        "initial_capital": initial_capital,
        "selected_analysts": selected_analysts,
        "fast_selected_analysts": fast_selected_analysts,
        "short_trade_target_profile_name": short_trade_target_profile_name,
        "short_trade_target_profile_overrides": short_trade_target_profile_overrides,
        "selection_target": selection_target,
        "cache_benchmark": cache_benchmark,
        "cache_benchmark_ticker": cache_benchmark_ticker,
        "cache_benchmark_clear_first": cache_benchmark_clear_first,
    }


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
    fast_selected_analysts: list[str] | None = None,
    short_trade_target_profile_name: str = "default",
    short_trade_target_profile_overrides: dict[str, object] | None = None,
    initial_margin_requirement: float = 0.0,
    agent: Callable = run_hedge_fund,
    pipeline: DailyPipeline | None = None,
    frozen_plan_source: str | Path | None = None,
    selection_target: str = "research_only",
    cache_benchmark: bool = False,
    cache_benchmark_ticker: str | None = None,
    cache_benchmark_clear_first: bool = False,
) -> PaperTradingArtifacts:
    context = _prepare_session_runtime_context(
        output_dir=output_dir,
        frozen_plan_source=frozen_plan_source,
        model_name=model_name,
        model_provider=model_provider,
        pipeline=pipeline,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        initial_margin_requirement=initial_margin_requirement,
    )
    metrics = _run_runtime_backtest(context)
    return _finalize_runtime_run(
        context=context,
        metrics=metrics,
        start_date=start_date,
        end_date=end_date,
        tickers=tickers,
        initial_capital=initial_capital,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        cache_benchmark=cache_benchmark,
        cache_benchmark_ticker=cache_benchmark_ticker,
        cache_benchmark_clear_first=cache_benchmark_clear_first,
    )
