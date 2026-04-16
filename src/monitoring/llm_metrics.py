import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()
_SESSION_ID = os.getenv("LLM_METRICS_SESSION_ID") or datetime.now().strftime("%Y%m%d_%H%M%S")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = Path(os.getenv("LLM_METRICS_DIR", str(_REPO_ROOT / "logs")))
_JSONL_PATH = _OUTPUT_DIR / f"llm_metrics_{_SESSION_ID}.jsonl"
_SUMMARY_PATH = _OUTPUT_DIR / f"llm_metrics_{_SESSION_ID}.summary.json"
_SUMMARY: dict[str, Any] = {
    "session_id": _SESSION_ID,
    "started_at": datetime.now().isoformat(timespec="seconds"),
    "updated_at": None,
    "totals": {},
    "providers": {},
    "routes": {},
    "transport_families": {},
    "models": {},
    "agents": {},
    "trade_dates": {},
    "pipeline_stages": {},
    "model_tiers": {},
}


def _bucket_template() -> dict[str, Any]:
    return {
        "attempts": 0,
        "successes": 0,
        "errors": 0,
        "rate_limit_errors": 0,
        "fallback_attempts": 0,
        "total_duration_ms": 0.0,
        "avg_duration_ms": 0.0,
        "prompt_chars": 0,
        "response_chars": 0,
        "error_types": {},
    }


_SUMMARY["totals"] = _bucket_template()


def _ensure_output_dir() -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _estimate_size(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if hasattr(value, "content") and isinstance(value.content, str):
        return len(value.content)

    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        return len(str(value))


def _error_message(error: Exception | None) -> str | None:
    if error is None:
        return None
    return str(error)[:500]


def _update_bucket(bucket: dict[str, Any], entry: dict[str, Any]) -> None:
    bucket["attempts"] += 1
    bucket["successes"] += 1 if entry["success"] else 0
    bucket["errors"] += 0 if entry["success"] else 1
    bucket["rate_limit_errors"] += 1 if entry["is_rate_limit"] else 0
    bucket["fallback_attempts"] += 1 if entry["used_fallback"] else 0
    bucket["total_duration_ms"] += entry["duration_ms"]
    bucket["avg_duration_ms"] = round(bucket["total_duration_ms"] / bucket["attempts"], 3)
    bucket["prompt_chars"] += entry["prompt_chars"]
    bucket["response_chars"] += entry["response_chars"]

    error_type = entry.get("error_type")
    if error_type:
        error_types = bucket.setdefault("error_types", {})
        error_types[error_type] = error_types.get(error_type, 0) + 1


def _write_summary() -> None:
    _SUMMARY["updated_at"] = datetime.now().isoformat(timespec="seconds")
    totals = _SUMMARY["totals"]
    if totals["attempts"]:
        totals["avg_duration_ms"] = round(totals["total_duration_ms"] / totals["attempts"], 3)
    with _SUMMARY_PATH.open("w", encoding="utf-8") as handle:
        json.dump(_SUMMARY, handle, ensure_ascii=False, indent=2)


def get_llm_metrics_paths() -> dict[str, str]:
    return {
        "session_id": _SESSION_ID,
        "jsonl_path": str(_JSONL_PATH),
        "summary_path": str(_SUMMARY_PATH),
    }


def record_llm_attempt(
    *,
    agent_name: str | None,
    model_provider: str,
    model_name: str,
    attempt_number: int,
    success: bool,
    duration_ms: float,
    prompt: Any,
    response: Any = None,
    error: Exception | None = None,
    is_rate_limit: bool = False,
    used_fallback: bool = False,
    route_id: str | None = None,
    transport_family: str | None = None,
    trade_date: str | None = None,
    pipeline_stage: str | None = None,
    model_tier: str | None = None,
) -> None:
    _ensure_output_dir()
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "session_id": _SESSION_ID,
        "agent_name": agent_name,
        "model_provider": str(model_provider),
        "model_name": str(model_name),
        "attempt_number": attempt_number,
        "success": success,
        "duration_ms": round(duration_ms, 3),
        "prompt_chars": _estimate_size(prompt),
        "response_chars": _estimate_size(response),
        "error_type": type(error).__name__ if error else None,
        "error_message": _error_message(error),
        "is_rate_limit": is_rate_limit,
        "used_fallback": used_fallback,
        "route_id": route_id,
        "transport_family": transport_family,
        "trade_date": trade_date,
        "pipeline_stage": pipeline_stage,
        "model_tier": model_tier,
    }

    provider_key = entry["model_provider"]
    route_key = entry["route_id"] or "unknown"
    transport_key = entry["transport_family"] or "unknown"
    model_key = f"{entry['model_provider']}:{entry['model_name']}"
    agent_key = entry["agent_name"] or "unknown"
    trade_date_key = entry["trade_date"] or "unknown"
    pipeline_stage_key = entry["pipeline_stage"] or "unknown"
    model_tier_key = entry["model_tier"] or "unknown"

    with _LOCK:
        with _JSONL_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

        _update_bucket(_SUMMARY["totals"], entry)
        providers = _SUMMARY.setdefault("providers", {})
        routes = _SUMMARY.setdefault("routes", {})
        transport_families = _SUMMARY.setdefault("transport_families", {})
        models = _SUMMARY.setdefault("models", {})
        agents = _SUMMARY.setdefault("agents", {})
        trade_dates = _SUMMARY.setdefault("trade_dates", {})
        pipeline_stages = _SUMMARY.setdefault("pipeline_stages", {})
        model_tiers = _SUMMARY.setdefault("model_tiers", {})
        _update_bucket(providers.setdefault(provider_key, _bucket_template()), entry)
        _update_bucket(routes.setdefault(route_key, _bucket_template()), entry)
        _update_bucket(transport_families.setdefault(transport_key, _bucket_template()), entry)
        _update_bucket(models.setdefault(model_key, _bucket_template()), entry)
        _update_bucket(agents.setdefault(agent_key, _bucket_template()), entry)
        _update_bucket(trade_dates.setdefault(trade_date_key, _bucket_template()), entry)
        _update_bucket(pipeline_stages.setdefault(pipeline_stage_key, _bucket_template()), entry)
        _update_bucket(model_tiers.setdefault(model_tier_key, _bucket_template()), entry)
        _write_summary()


def reset_llm_metrics_for_testing() -> None:
    with _LOCK:
        _SUMMARY["started_at"] = datetime.now().isoformat(timespec="seconds")
        _SUMMARY["updated_at"] = None
        _SUMMARY["totals"] = _bucket_template()
        _SUMMARY["providers"] = {}
        _SUMMARY["routes"] = {}
        _SUMMARY["transport_families"] = {}
        _SUMMARY["models"] = {}
        _SUMMARY["agents"] = {}
        _SUMMARY["trade_dates"] = {}
        _SUMMARY["pipeline_stages"] = {}
        _SUMMARY["model_tiers"] = {}
        if _JSONL_PATH.exists():
            _JSONL_PATH.unlink()
        if _SUMMARY_PATH.exists():
            _SUMMARY_PATH.unlink()
