from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


LoadLatestUpstreamShadowFollowupSummary = Callable[[str | Path], dict[str, Any]]


def ordered_without(values: list[Any] | None, excluded: set[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        token = str(value or "").strip()
        if not token or token in excluded or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def build_upstream_shadow_followup_overlay(
    reports_root: str | Path,
    *,
    no_candidate_entry_priority_tickers: list[Any] | None = None,
    absent_from_watchlist_tickers: list[Any] | None = None,
    watchlist_absent_from_candidate_pool_tickers: list[Any] | None = None,
    upstream_handoff_focus_tickers: list[Any] | None = None,
    load_latest_upstream_shadow_followup_summary: LoadLatestUpstreamShadowFollowupSummary,
) -> dict[str, Any]:
    summary = load_latest_upstream_shadow_followup_summary(reports_root)
    validated_tickers = [str(value or "") for value in list(summary.get("validated_tickers") or []) if str(value or "").strip()]
    validated_set = set(validated_tickers)

    active_priority_tickers = ordered_without(no_candidate_entry_priority_tickers, validated_set)
    active_absent_from_watchlist_tickers = ordered_without(absent_from_watchlist_tickers, validated_set)
    active_watchlist_absent_from_candidate_pool_tickers = ordered_without(watchlist_absent_from_candidate_pool_tickers, validated_set)
    active_upstream_handoff_focus_tickers = ordered_without(upstream_handoff_focus_tickers, validated_set)

    recommendation = summary.get("recommendation")
    if summary.get("status") == "validated_upstream_shadow_followup_available":
        if active_priority_tickers:
            recommendation = (
                f"最新正式 upstream shadow followup 已把 {validated_tickers} 转入 downstream decision 分层；"
                f"当前 upstream recall backlog 应收敛到 {active_priority_tickers}，避免对已验证票重复做 absent_from_watchlist / candidate_pool recall。"
            )
        else:
            recommendation = (
                f"最新正式 upstream shadow followup 已把 {validated_tickers} 全部转入 downstream decision 分层；"
                "当前 control tower 不应再把这些票作为 upstream recall 主任务。"
            )

    return {
        **summary,
        "validated_tickers": validated_tickers,
        "active_no_candidate_entry_priority_tickers": active_priority_tickers,
        "active_absent_from_watchlist_tickers": active_absent_from_watchlist_tickers,
        "active_watchlist_absent_from_candidate_pool_tickers": active_watchlist_absent_from_candidate_pool_tickers,
        "active_upstream_handoff_focus_tickers": active_upstream_handoff_focus_tickers,
        "recommendation": recommendation,
    }
