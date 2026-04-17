"""Entry transformation helpers shared across card modules.

Pure functions that transform entry dicts — no dependency on btst_reporting.py.
"""

from __future__ import annotations

from typing import Any

from src.paper_trading.btst_reporting_utils import (
    _as_float,
    _round_or_none,
)


CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES = 3


def _apply_execution_quality_entry_mode(entry: dict[str, Any]) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    execution_quality_label = str(
        historical_prior.get("execution_quality_label") or "unknown"
    )
    updated_entry = dict(entry)
    updated_entry["historical_prior"] = historical_prior

    top_reasons = [
        str(reason)
        for reason in list(updated_entry.get("top_reasons") or [])
        if str(reason or "").strip()
    ]

    if execution_quality_label == "intraday_only":
        updated_entry["preferred_entry_mode"] = "intraday_confirmation_only"
        updated_entry["promotion_trigger"] = (
            "历史更像盘中确认后的 intraday 机会，不把默认隔夜持有当成升级方向。"
        )
        if "historical_intraday_only_execution" not in top_reasons:
            top_reasons.append("historical_intraday_only_execution")
    elif execution_quality_label == "gap_chase_risk":
        updated_entry["preferred_entry_mode"] = "avoid_open_chase_confirmation"
        updated_entry["promotion_trigger"] = (
            "若盘中回踩后重新走强可再确认，避免把开盘追价当成默认动作。"
        )
        if "historical_gap_chase_risk" not in top_reasons:
            top_reasons.append("historical_gap_chase_risk")
    elif execution_quality_label == "close_continuation":
        updated_entry["preferred_entry_mode"] = "confirm_then_hold_breakout"
        updated_entry["promotion_trigger"] = (
            "若盘中 continuation 确认后量价延续良好，可升级为 confirm-then-hold，而不是默认快进快出。"
        )
        if "historical_close_continuation" not in top_reasons:
            top_reasons.append("historical_close_continuation")
    elif execution_quality_label == "zero_follow_through":
        updated_entry["preferred_entry_mode"] = "strong_reconfirmation_only"
        updated_entry["promotion_trigger"] = (
            "历史同层兑现极弱，只有出现新的强确认时才允许重新升级。"
        )
        if "historical_zero_follow_through" not in top_reasons:
            top_reasons.append("historical_zero_follow_through")

    updated_entry["top_reasons"] = top_reasons
    return updated_entry


def _build_catalyst_theme_shadow_watch_rows(
    entries: list[dict[str, Any]],
    *,
    limit: int = CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES,
) -> list[dict[str, Any]]:
    ranked_entries = sorted(
        [dict(entry) for entry in entries if entry and entry.get("ticker")],
        key=lambda entry: (
            entry.get("total_shortfall")
            if entry.get("total_shortfall") is not None
            else 999.0,
            -_as_float(entry.get("score_target")),
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            str(entry.get("ticker") or ""),
        ),
    )

    rows: list[dict[str, Any]] = []
    for entry in ranked_entries[:limit]:
        metrics = dict(entry.get("metrics") or {})
        rows.append(
            {
                "ticker": entry.get("ticker"),
                "candidate_score": entry.get("score_target"),
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "candidate_source": entry.get("candidate_source"),
                "filter_reason": entry.get("filter_reason"),
                "failed_threshold_count": int(entry.get("failed_threshold_count") or 0),
                "total_shortfall": _round_or_none(entry.get("total_shortfall")),
                "threshold_shortfalls": dict(entry.get("threshold_shortfalls") or {}),
                "promotion_trigger": entry.get("promotion_trigger"),
                "positive_tags": list(entry.get("positive_tags") or []),
                "top_reasons": list(entry.get("top_reasons") or []),
                "metrics": {
                    "breakout_freshness": metrics.get("breakout_freshness"),
                    "trend_acceleration": metrics.get("trend_acceleration"),
                    "close_strength": metrics.get("close_strength"),
                    "sector_resonance": metrics.get("sector_resonance"),
                    "catalyst_freshness": metrics.get("catalyst_freshness"),
                },
            }
        )
    return rows
