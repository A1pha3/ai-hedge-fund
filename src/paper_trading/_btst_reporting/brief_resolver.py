"""Resolve brief analysis payload from input path or pre-built dict.

Handles lazy loading and normalization of trade brief analysis data,
including frontier summary and upstream shadow defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.paper_trading.btst_reporting_utils import (
    _load_json,
    _normalize_trade_date,
)
from src.paper_trading._btst_reporting.entry_builders import (
    _load_catalyst_theme_frontier_summary as _load_catalyst_theme_frontier_summary_eb,
    _build_catalyst_theme_frontier_priority as _build_catalyst_theme_frontier_priority_eb,
)


def _resolve_brief_analysis(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None,
    next_trade_date: str | None,
) -> dict[str, Any]:
    payload = dict(input_path) if isinstance(input_path, dict) else {}

    if not payload:
        resolved_input = Path(input_path).expanduser().resolve()
        if resolved_input.is_file():
            payload = _load_json(resolved_input)
            if "selected_entries" not in payload or "near_miss_entries" not in payload:
                return _invoke_analyze_brief(
                    resolved_input, trade_date, next_trade_date
                )
        else:
            return _invoke_analyze_brief(
                resolved_input, trade_date, next_trade_date
            )

    if next_trade_date and not payload.get("next_trade_date"):
        payload["next_trade_date"] = _normalize_trade_date(next_trade_date)

    frontier_summary = dict(payload.get("catalyst_theme_frontier_summary") or {})
    frontier_priority = dict(payload.get("catalyst_theme_frontier_priority") or {})
    if not frontier_summary or not frontier_priority:
        frontier_summary = frontier_summary or _load_catalyst_theme_frontier_summary_eb(
            payload.get("report_dir")
        )
        frontier_priority = (
            frontier_priority
            or _build_catalyst_theme_frontier_priority_eb(
                frontier_summary,
                list(payload.get("catalyst_theme_shadow_entries") or []),
            )
        )
        payload["catalyst_theme_frontier_summary"] = frontier_summary
        payload["catalyst_theme_frontier_priority"] = frontier_priority

    summary = dict(payload.get("summary") or {})
    summary.setdefault(
        "catalyst_theme_frontier_promoted_count",
        len(frontier_priority.get("promoted_tickers") or []),
    )
    payload["summary"] = summary
    payload.setdefault("upstream_shadow_entries", [])
    payload.setdefault(
        "upstream_shadow_summary",
        {
            "shadow_candidate_count": 0,
            "promotable_count": 0,
            "lane_counts": {},
            "decision_counts": {},
            "top_focus_tickers": [],
        },
    )
    return payload


def _invoke_analyze_brief(
    resolved_input: Path,
    trade_date: str | None,
    next_trade_date: str | None,
) -> dict[str, Any]:
    # Lazy import to avoid circular dependency with btst_reporting.py
    from src.paper_trading.btst_reporting import analyze_btst_next_day_trade_brief

    return analyze_btst_next_day_trade_brief(
        resolved_input, trade_date=trade_date, next_trade_date=next_trade_date
    )
