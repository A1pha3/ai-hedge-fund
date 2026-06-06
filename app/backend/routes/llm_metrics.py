"""LLM metrics API route -- exposes cost, latency, and usage summaries from JSONL metrics files."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/llm-metrics")

_DEFAULT_LOOKBACK_DAYS = 7

# Approximate USD cost per 1K input/output characters for common models.
# These are rough averages updated 2026-Q1 — actual billing depends on
# tokens, not chars, so this is an estimate only. Used to surface
# "cost-savings suggestion" hints in the heatmap panel.
_MODEL_COST_PER_1K_CHARS: dict[str, dict[str, float]] = {
    # model_name_substring -> {"input": $, "output": $}
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4-turbo": {"input": 0.010, "output": 0.030},
    "gpt-4": {"input": 0.030, "output": 0.060},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-sonnet-4": {"input": 0.003, "output": 0.015},
    "claude-opus-4": {"input": 0.015, "output": 0.075},
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
    "gemini-1.5-pro": {"input": 0.0035, "output": 0.0105},
    "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
    "qwen-max": {"input": 0.0008, "output": 0.002},
    "qwen-plus": {"input": 0.0004, "output": 0.0012},
}

_DEFAULT_COST = {"input": 0.002, "output": 0.006}


def _estimate_cost_usd(model_name: str, prompt_chars: int, response_chars: int) -> float:
    """Approximate USD cost for a single LLM call based on character counts.

    The estimate uses per-1K-character pricing, not per-token, so it
    overstates cost by ~3-4x for English (1 token ≈ 4 chars). The point
    is to rank agents / providers for cost-saving suggestions, not to
    produce billing-accurate numbers.
    """
    rates = _DEFAULT_COST
    if model_name:
        for needle, candidate in _MODEL_COST_PER_1K_CHARS.items():
            if needle in model_name.lower():
                rates = candidate
                break
    in_cost = (prompt_chars / 1000.0) * rates["input"]
    out_cost = (response_chars / 1000.0) * rates["output"]
    return round(in_cost + out_cost, 6)


def _get_logs_dir() -> Path:
    """Resolve the logs directory from env or repo root."""
    repo_root = Path(__file__).resolve().parents[3]
    return Path(os.getenv("LLM_METRICS_DIR", str(repo_root / "logs")))


def _parse_date_from_filename(filename: str) -> datetime | None:
    """Extract the session start date from a metrics filename like llm_metrics_20260310_232939.jsonl."""
    try:
        # Format: llm_metrics_YYYYMMDD_HHMMSS.jsonl
        base = filename.replace("llm_metrics_", "").replace(".jsonl", "")
        return datetime.strptime(base.split("_")[0], "%Y%m%d").replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute the pct-th percentile (0-100) of a sorted list."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    k = (pct / 100.0) * (n - 1)
    f = int(k)
    c = f + 1
    if c >= n:
        return sorted_values[-1]
    d0 = sorted_values[f]
    d1 = sorted_values[c]
    return d0 + (d1 - d0) * (k - f)


def _collect_metrics(logs_dir: Path, lookback_days: int) -> dict[str, Any]:
    """Parse recent JSONL files and return aggregated metrics."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)

    # Per-agent aggregation
    agent_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "successes": 0,
            "errors": 0,
            "total_duration_ms": 0.0,
            "durations": [],
            "prompt_chars": 0,
            "response_chars": 0,
            "estimated_cost_usd": 0.0,
        }
    )

    # Per-provider aggregation
    provider_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "successes": 0,
            "errors": 0,
            "total_duration_ms": 0.0,
            "durations": [],
            "estimated_cost_usd": 0.0,
        }
    )

    # Per-date aggregation (YYYY-MM-DD)
    date_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "successes": 0,
            "total_duration_ms": 0.0,
            "estimated_cost_usd": 0.0,
        }
    )

    # Daily per-provider for the "availability timeline" heatmap
    daily_provider: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "calls": 0,
                "errors": 0,
                "total_duration_ms": 0.0,
                "estimated_cost_usd": 0.0,
            }
        )
    )

    totals: dict[str, Any] = {
        "calls": 0,
        "successes": 0,
        "errors": 0,
        "total_duration_ms": 0.0,
        "prompt_chars": 0,
        "response_chars": 0,
        "estimated_cost_usd": 0.0,
        "sessions_scanned": 0,
    }

    sessions_scanned = 0

    jsonl_files = sorted(logs_dir.glob("llm_metrics_*.jsonl"))
    for jsonl_path in jsonl_files:
        file_date = _parse_date_from_filename(jsonl_path.name)
        if file_date is None or file_date < cutoff:
            continue

        sessions_scanned += 1
        try:
            with jsonl_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    success = entry.get("success", False)
                    duration = float(entry.get("duration_ms") or 0.0)
                    agent = str(entry.get("agent_name") or "unknown")
                    provider = str(entry.get("model_provider") or "unknown")
                    model_name = str(entry.get("model_name") or "")
                    prompt_chars = int(entry.get("prompt_chars") or 0)
                    response_chars = int(entry.get("response_chars") or 0)
                    estimated_cost = _estimate_cost_usd(model_name, prompt_chars, response_chars)

                    # Extract date from entry timestamp for per-date grouping
                    ts_str = entry.get("timestamp", "")
                    try:
                        entry_date = datetime.fromisoformat(ts_str).strftime("%Y-%m-%d")
                    except (ValueError, TypeError):
                        entry_date = "unknown"

                    # Agent aggregation
                    ad = agent_data[agent]
                    ad["calls"] += 1
                    ad["successes"] += 1 if success else 0
                    ad["errors"] += 0 if success else 1
                    ad["total_duration_ms"] += duration
                    ad["durations"].append(duration)
                    ad["prompt_chars"] += prompt_chars
                    ad["response_chars"] += response_chars
                    ad["estimated_cost_usd"] += estimated_cost

                    # Provider aggregation
                    pd = provider_data[provider]
                    pd["calls"] += 1
                    pd["successes"] += 1 if success else 0
                    pd["errors"] += 0 if success else 1
                    pd["total_duration_ms"] += duration
                    pd["durations"].append(duration)
                    pd["estimated_cost_usd"] += estimated_cost

                    # Date aggregation
                    dd = date_data[entry_date]
                    dd["calls"] += 1
                    dd["successes"] += 1 if success else 0
                    dd["total_duration_ms"] += duration
                    dd["estimated_cost_usd"] += estimated_cost

                    # Daily per-provider
                    dpd = daily_provider[entry_date][provider]
                    dpd["calls"] += 1
                    dpd["errors"] += 0 if success else 1
                    dpd["total_duration_ms"] += duration
                    dpd["estimated_cost_usd"] += estimated_cost

                    # Totals
                    totals["calls"] += 1
                    totals["successes"] += 1 if success else 0
                    totals["errors"] += 0 if success else 1
                    totals["total_duration_ms"] += duration
                    totals["prompt_chars"] += prompt_chars
                    totals["response_chars"] += response_chars
                    totals["estimated_cost_usd"] += estimated_cost
        except OSError:
            continue

    totals["sessions_scanned"] = sessions_scanned

    # Compute derived fields for agents
    agents_summary: list[dict[str, Any]] = []
    for agent_name, ad in sorted(agent_data.items()):
        durations = sorted(ad["durations"])
        avg_dur = ad["total_duration_ms"] / ad["calls"] if ad["calls"] else 0.0
        p95_dur = _percentile(durations, 95)
        agents_summary.append(
            {
                "agent_name": agent_name,
                "calls": ad["calls"],
                "successes": ad["successes"],
                "errors": ad["errors"],
                "avg_duration_ms": round(avg_dur, 1),
                "p95_duration_ms": round(p95_dur, 1),
                "total_duration_ms": round(ad["total_duration_ms"], 1),
                "prompt_chars": ad["prompt_chars"],
                "response_chars": ad["response_chars"],
                "estimated_cost_usd": round(ad["estimated_cost_usd"], 4),
            }
        )

    # Compute derived fields for providers
    providers_summary: list[dict[str, Any]] = []
    for provider_name, pd in sorted(provider_data.items()):
        durations = sorted(pd["durations"])
        avg_dur = pd["total_duration_ms"] / pd["calls"] if pd["calls"] else 0.0
        p95_dur = _percentile(durations, 95)
        error_rate = (pd["errors"] / pd["calls"]) if pd["calls"] else 0.0
        providers_summary.append(
            {
                "provider": provider_name,
                "calls": pd["calls"],
                "successes": pd["successes"],
                "errors": pd["errors"],
                "error_rate": round(error_rate, 4),
                "avg_duration_ms": round(avg_dur, 1),
                "p95_duration_ms": round(p95_dur, 1),
                "total_duration_ms": round(pd["total_duration_ms"], 1),
                "estimated_cost_usd": round(pd["estimated_cost_usd"], 4),
            }
        )

    # Compute derived fields for dates
    daily_trend: list[dict[str, Any]] = []
    for date_str in sorted(date_data.keys()):
        dd = date_data[date_str]
        avg_dur = dd["total_duration_ms"] / dd["calls"] if dd["calls"] else 0.0
        daily_trend.append(
            {
                "date": date_str,
                "calls": dd["calls"],
                "successes": dd["successes"],
                "avg_duration_ms": round(avg_dur, 1),
                "total_duration_ms": round(dd["total_duration_ms"], 1),
                "estimated_cost_usd": round(dd["estimated_cost_usd"], 4),
            }
        )

    # Daily per-provider heatmap (used by the frontend heatmap panel)
    daily_provider_summary: list[dict[str, Any]] = []
    for date_str in sorted(daily_provider.keys()):
        providers_for_day = []
        for provider_name, dpd in sorted(daily_provider[date_str].items()):
            error_rate = (dpd["errors"] / dpd["calls"]) if dpd["calls"] else 0.0
            providers_for_day.append(
                {
                    "provider": provider_name,
                    "calls": dpd["calls"],
                    "errors": dpd["errors"],
                    "error_rate": round(error_rate, 4),
                    "estimated_cost_usd": round(dpd["estimated_cost_usd"], 4),
                }
            )
        daily_provider_summary.append({"date": date_str, "providers": providers_for_day})

    # Cost-savings suggestions: for each agent compute "if I switched to a
    # cheaper model with similar quality tier, how much would I save?".
    # We use a simple heuristic: if an agent's avg cost-per-call exceeds
    # the median cost-per-call by >= 2x, flag it.
    if agents_summary:
        cost_per_call = [a["estimated_cost_usd"] / a["calls"] for a in agents_summary if a["calls"] > 0]
        cost_per_call_sorted = sorted(cost_per_call)
        median_cost = _percentile(cost_per_call_sorted, 50) if cost_per_call_sorted else 0.0
        suggestions: list[dict[str, Any]] = []
        for agent in agents_summary:
            if agent["calls"] == 0:
                continue
            cpc = agent["estimated_cost_usd"] / agent["calls"]
            if median_cost > 0 and cpc >= 2 * median_cost:
                savings_pct = round((1 - median_cost / cpc) * 100, 1)
                suggestions.append(
                    {
                        "agent_name": agent["agent_name"],
                        "current_cost_per_call": round(cpc, 6),
                        "median_cost_per_call": round(median_cost, 6),
                        "potential_savings_pct": savings_pct,
                        "calls": agent["calls"],
                    }
                )
        # Top 3 by call volume
        suggestions.sort(key=lambda s: s["calls"], reverse=True)
        cost_savings_suggestions = suggestions[:3]
    else:
        cost_savings_suggestions = []

    # Global derived
    avg_total = totals["total_duration_ms"] / totals["calls"] if totals["calls"] else 0.0
    totals["avg_duration_ms"] = round(avg_total, 1)
    totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 4)

    # Heatmap: top 10 agents by cost, top 5 providers by avg duration.
    top_agents_by_cost = sorted(
        [a for a in agents_summary if a["calls"] > 0],
        key=lambda a: a["estimated_cost_usd"],
        reverse=True,
    )[:10]
    top_providers_by_latency = sorted(
        [p for p in providers_summary if p["calls"] > 0],
        key=lambda p: p["avg_duration_ms"],
        reverse=True,
    )[:5]

    return {
        "totals": totals,
        "agents": agents_summary,
        "providers": providers_summary,
        "daily_trend": daily_trend,
        "daily_provider": daily_provider_summary,
        "top_agents_by_cost": top_agents_by_cost,
        "top_providers_by_latency": top_providers_by_latency,
        "cost_savings_suggestions": cost_savings_suggestions,
        "lookback_days": lookback_days,
    }


@router.get("/summary")
async def llm_metrics_summary(days: int = _DEFAULT_LOOKBACK_DAYS) -> dict[str, Any]:
    """Return aggregated LLM call metrics for the last N days.

    Response shape::

        {
          "totals": { "calls": N, "successes": N, "errors": N,
                      "avg_duration_ms": X, "estimated_cost_usd": Y,
                      "prompt_chars": N, "response_chars": N,
                      "sessions_scanned": N },
          "agents": [ { "agent_name": "...", "calls": N, "p95_duration_ms": X,
                        "estimated_cost_usd": Y, ... } ],
          "providers": [ { "provider": "...", "calls": N, "error_rate": X,
                           "avg_duration_ms": Y, "estimated_cost_usd": Z } ],
          "daily_trend": [ { "date": "YYYY-MM-DD", "calls": N, ... } ],
          "daily_provider": [ { "date": "...", "providers": [ ... ] } ],
          "top_agents_by_cost": [ ... up to 10 ... ],
          "top_providers_by_latency": [ ... up to 5 ... ],
          "cost_savings_suggestions": [ { "agent_name", "potential_savings_pct", ... } ],
          "lookback_days": 7
        }
    """
    logs_dir = _get_logs_dir()
    lookback = max(1, min(days, 90))  # clamp to [1, 90]
    return _collect_metrics(logs_dir, lookback)
