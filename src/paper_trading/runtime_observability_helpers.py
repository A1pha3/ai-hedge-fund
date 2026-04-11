from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator

if TYPE_CHECKING:
    from src.execution.daily_pipeline import DailyPipeline


def build_llm_route_provenance(*, get_llm_metrics_paths_fn: Callable[[], dict[str, str]]) -> tuple[dict, dict]:
    metrics_paths = get_llm_metrics_paths_fn()
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


def build_llm_observability_summary(jsonl_path: Path) -> dict:
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


def build_llm_error_digest(llm_route_provenance: dict, llm_observability_summary: dict) -> dict:
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


def build_execution_plan_provenance_summary(pipeline: "DailyPipeline | None") -> dict:
    observations = list(getattr(pipeline, "execution_plan_provenance_log", []) or [])
    return {
        "observation_count": len(observations),
        "observations": observations,
    }


def build_dual_target_session_summary(daily_events_path: Path) -> dict:
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
    existing_keys = {
        tuple(item.get(field) for field in ("trade_date", "pipeline_stage", "model_tier", "provider", "error_type", "message"))
        for item in sample_errors
    }
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
