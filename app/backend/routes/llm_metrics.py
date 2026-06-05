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
        }
    )

    # Per-date aggregation (YYYY-MM-DD)
    date_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "successes": 0,
            "total_duration_ms": 0.0,
        }
    )

    totals: dict[str, Any] = {
        "calls": 0,
        "successes": 0,
        "errors": 0,
        "total_duration_ms": 0.0,
        "prompt_chars": 0,
        "response_chars": 0,
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
                    prompt_chars = int(entry.get("prompt_chars") or 0)
                    response_chars = int(entry.get("response_chars") or 0)

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

                    # Date aggregation
                    dd = date_data[entry_date]
                    dd["calls"] += 1
                    dd["successes"] += 1 if success else 0
                    dd["total_duration_ms"] += duration

                    # Totals
                    totals["calls"] += 1
                    totals["successes"] += 1 if success else 0
                    totals["errors"] += 0 if success else 1
                    totals["total_duration_ms"] += duration
                    totals["prompt_chars"] += prompt_chars
                    totals["response_chars"] += response_chars
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
            }
        )

    # Global derived
    avg_total = totals["total_duration_ms"] / totals["calls"] if totals["calls"] else 0.0
    totals["avg_duration_ms"] = round(avg_total, 1)

    return {
        "totals": totals,
        "agents": agents_summary,
        "daily_trend": daily_trend,
        "lookback_days": lookback_days,
    }


@router.get("/summary")
async def llm_metrics_summary(days: int = _DEFAULT_LOOKBACK_DAYS) -> dict[str, Any]:
    """Return aggregated LLM call metrics for the last N days.

    Response shape::

        {
          "totals": { "calls": N, "successes": N, ... "avg_duration_ms": X },
          "agents": [ { "agent_name": "...", "calls": N, "p95_duration_ms": X, ... } ],
          "daily_trend": [ { "date": "YYYY-MM-DD", "calls": N, ... } ],
          "lookback_days": 7
        }
    """
    logs_dir = _get_logs_dir()
    lookback = max(1, min(days, 90))  # clamp to [1, 90]
    return _collect_metrics(logs_dir, lookback)
