"""Recommendation-line helpers for BTST reporting artifacts."""

from __future__ import annotations

from typing import Any
from collections.abc import Callable


SelectedHoldingContractNoteResolver = Callable[[str | None, dict[str, Any] | None], str | None]


def append_primary_and_near_miss_recommendations(
    recommendation_lines: list[str],
    *,
    primary_entry: dict[str, Any] | None,
    near_miss_entries: list[dict[str, Any]],
    selected_holding_contract_note: SelectedHoldingContractNoteResolver,
) -> None:
    if primary_entry:
        recommendation_lines.append(
            f"主入场票为 {primary_entry['ticker']}，应按 {primary_entry['preferred_entry_mode']} 执行，而不是把它视为无条件开盘追价。"
        )
        primary_historical = primary_entry.get("historical_prior") or {}
        if primary_historical.get("summary"):
            recommendation_lines.append("主票历史先验参考: " + str(primary_historical.get("summary")))
        if primary_historical.get("execution_note"):
            recommendation_lines.append("主票执行先验: " + str(primary_historical.get("execution_note")))
        primary_contract_note = selected_holding_contract_note(primary_entry.get("preferred_entry_mode"), primary_historical)
        if primary_contract_note:
            recommendation_lines.append("主票持有 contract: " + primary_contract_note)
    else:
        recommendation_lines.append("本次 short-trade 没有正式 selected 样本，不建议把 near_miss 直接当成主入场票。")

    if not near_miss_entries:
        return
    recommendation_lines.append(
        "备选观察票为 " + ", ".join(entry["ticker"] for entry in near_miss_entries) + "，仅适合作为盘中跟踪对象。"
    )
    near_miss_historical_lines = [
        f"{entry['ticker']}={entry.get('historical_prior', {}).get('summary')}"
        for entry in near_miss_entries
        if (entry.get("historical_prior") or {}).get("summary")
    ]
    if near_miss_historical_lines:
        recommendation_lines.append("观察票历史先验参考: " + "；".join(near_miss_historical_lines))


def append_pool_and_observer_recommendations(
    recommendation_lines: list[str],
    *,
    opportunity_pool_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
) -> None:
    _append_opportunity_pool_recommendation_lines(recommendation_lines, opportunity_pool_entries=opportunity_pool_entries)
    _append_observer_bucket_recommendation_lines(
        recommendation_lines,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
    )


def append_research_and_shadow_recommendations(
    recommendation_lines: list[str],
    *,
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    excluded_research_entries: list[dict[str, Any]],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_research_lane_recommendation_lines(
        recommendation_lines,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
    )
    _append_shadow_lane_recommendation_lines(
        recommendation_lines,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
    )
    _append_excluded_and_upstream_recommendation_lines(
        recommendation_lines,
        excluded_research_entries=excluded_research_entries,
        upstream_shadow_entries=upstream_shadow_entries,
    )


def _append_opportunity_pool_recommendation_lines(recommendation_lines: list[str], *, opportunity_pool_entries: list[dict[str, Any]]) -> None:
    _append_recommendation_line_if_entries(
        recommendation_lines,
        opportunity_pool_entries,
        prefix="自动扩容候选池为 ",
        suffix="，这些票结构未坏，但还没进入正式名单，只能在盘中新增强度确认后升级。",
    )
    _append_historical_prior_recommendation(
        recommendation_lines,
        entries=opportunity_pool_entries,
        prefix="机会池历史先验参考: ",
    )


def _append_observer_bucket_recommendation_lines(
    recommendation_lines: list[str],
    *,
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
) -> None:
    _append_recommendation_line_if_entries(
        recommendation_lines,
        risky_observer_entries,
        prefix="高风险观察桶为 ",
        suffix="，这些票更像盘中确认/避免追高对象，不与标准 BTST 机会池混用。",
    )
    _append_recommendation_line_if_entries(
        recommendation_lines,
        no_history_observer_entries,
        prefix="无历史先验观察桶为 ",
        suffix="，这些票暂无可评估历史先验，不再占用标准 BTST 机会池名额，只保留盘中新证据观察。",
    )
    _append_recommendation_line_if_entries(
        recommendation_lines,
        weak_history_pruned_entries,
        prefix="已从标准观察池剔除的低质量样本有 ",
        suffix="，这些名字要么历史兑现接近 0，要么缺少历史先验且当前分数/形态偏弱，不应继续占用明日观察名额。",
    )


def _append_research_lane_recommendation_lines(
    recommendation_lines: list[str],
    *,
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
) -> None:
    _append_recommendation_line_if_entries(
        recommendation_lines,
        research_upside_radar_entries,
        prefix="research 漏票雷达为 ",
        suffix="，这些票只用于第二天上涨线索复盘，不进入 BTST 执行名单。",
    )
    _append_recommendation_line_if_entries(
        recommendation_lines,
        catalyst_theme_entries,
        prefix="题材催化研究池为 ",
        suffix="，这些票只用于专题催化跟踪，不进入主池或 BTST 执行名单。",
    )


def _append_shadow_lane_recommendation_lines(
    recommendation_lines: list[str],
    *,
    catalyst_theme_frontier_priority: dict[str, Any],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_recommendation_line_if_tickers(
        recommendation_lines,
        catalyst_theme_frontier_priority.get("promoted_tickers") or [],
        prefix="题材催化前沿第一优先 research follow-up 为 ",
        suffix="；这些票是解释性前沿下的可晋级影子样本，只做研究跟踪，不进入当日 BTST 执行名单。",
    )
    _append_recommendation_line_if_entries(
        recommendation_lines,
        catalyst_theme_shadow_entries,
        prefix="题材催化影子观察为 ",
        suffix="，这些票距离正式题材研究池仅差少数阈值，当前只做近阈值跟踪，不进入主池或 BTST 执行名单。",
    )


def _append_excluded_and_upstream_recommendation_lines(
    recommendation_lines: list[str],
    *,
    excluded_research_entries: list[dict[str, Any]],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_recommendation_line_if_entries(
        recommendation_lines,
        excluded_research_entries,
        prefix="research 侧已选中但不属于本次 short-trade 执行名单的股票有 ",
        suffix="。",
    )
    _append_recommendation_line_if_entries(
        recommendation_lines,
        upstream_shadow_entries,
        prefix="上游影子召回覆盖 ",
        suffix="，这些票来自 candidate-pool 上游漏票修复通道，只能按当前 short-trade decision 分层处理，不能因为被召回就自动升级。",
    )


def _append_recommendation_line_if_entries(
    recommendation_lines: list[str],
    entries: list[dict[str, Any]],
    *,
    prefix: str,
    suffix: str,
) -> None:
    _append_recommendation_line_if_tickers(
        recommendation_lines,
        [entry["ticker"] for entry in entries],
        prefix=prefix,
        suffix=suffix,
    )


def _append_recommendation_line_if_tickers(
    recommendation_lines: list[str],
    tickers: list[str],
    *,
    prefix: str,
    suffix: str,
) -> None:
    if tickers:
        recommendation_lines.append(prefix + ", ".join(tickers) + suffix)


def _append_historical_prior_recommendation(
    recommendation_lines: list[str],
    *,
    entries: list[dict[str, Any]],
    prefix: str,
) -> None:
    historical_prior_lines = [
        f"{entry['ticker']}={entry.get('historical_prior', {}).get('summary')}"
        for entry in entries
        if (entry.get("historical_prior") or {}).get("summary")
    ]
    if historical_prior_lines:
        recommendation_lines.append(prefix + "；".join(historical_prior_lines))
