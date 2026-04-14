from __future__ import annotations

from typing import Any

from src.execution.models import LayerCResult
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetMode
from src.targets.research_target import (
    evaluate_research_rejected_target,
    evaluate_research_selected_target,
)
from src.targets.router_build_helpers import (
    add_rejected_selection_targets,
    add_short_trade_only_selection_targets,
    add_watchlist_selection_targets,
    build_dual_target_summary,
    build_remaining_supplemental_short_trade_entries,
)
from src.targets.short_trade_target import (
    evaluate_short_trade_rejected_target,
    evaluate_short_trade_selected_target,
)


def _classify_delta(evaluation: DualTargetEvaluation) -> str | None:
    research_result = evaluation.research
    short_trade_result = evaluation.short_trade
    if research_result is None or short_trade_result is None:
        return None

    research_selected = research_result.decision == "selected"
    short_trade_selected = short_trade_result.decision == "selected"
    if research_selected and not short_trade_selected:
        return "research_pass_short_reject"
    if not research_selected and short_trade_selected:
        return "research_reject_short_pass"
    if research_selected and short_trade_selected and research_result.rank_hint != short_trade_result.rank_hint:
        return "both_pass_but_rank_diverge"
    if not research_selected and not short_trade_selected:
        return "both_reject_but_reason_diverge"
    return None


def _resolve_candidate_source(*, item: LayerCResult | None = None, entry: dict[str, Any] | None = None, default: str) -> tuple[str, list[str]]:
    if item is not None:
        source = str(getattr(item, "candidate_source", "") or default)
        reason_codes = [str(reason) for reason in list(getattr(item, "candidate_reason_codes", []) or []) if str(reason or "").strip()]
        return source, reason_codes
    entry = dict(entry or {})
    source = str(entry.get("candidate_source") or entry.get("source") or default)
    reason_codes = [str(reason) for reason in list(entry.get("candidate_reason_codes", entry.get("reasons", [])) or []) if str(reason or "").strip()]
    primary_reason = str(entry.get("reason") or "").strip()
    if primary_reason and primary_reason not in reason_codes:
        reason_codes.insert(0, primary_reason)
    return source, reason_codes


def _merge_reason_codes(*code_lists: list[str]) -> list[str]:
    merged: list[str] = []
    for code_list in code_lists:
        for code in code_list:
            normalized = str(code or "").strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
    return merged


def summarize_selection_targets(*, selection_targets: dict[str, DualTargetEvaluation], target_mode: TargetMode) -> DualTargetSummary:
    return build_dual_target_summary(selection_targets=selection_targets, target_mode=target_mode)


def _build_selected_evaluation(
    *,
    trade_date: str,
    item: LayerCResult,
    rank_hint: int,
    rank_population: int,
    included_in_buy_orders: bool,
    target_mode: TargetMode,
) -> DualTargetEvaluation:
    candidate_source, candidate_reason_codes = _resolve_candidate_source(item=item, default="layer_c_watchlist")
    research_result = evaluate_research_selected_target(
        trade_date=trade_date,
        item=item,
        rank_hint=rank_hint,
        included_in_buy_orders=included_in_buy_orders,
    )
    short_trade_result = (
        evaluate_short_trade_selected_target(
            trade_date=trade_date,
            item=item,
            rank_hint=rank_hint,
            rank_population=rank_population,
            included_in_buy_orders=included_in_buy_orders,
        )
        if target_mode != "research_only"
        else None
    )
    evaluation = DualTargetEvaluation(
        ticker=item.ticker,
        trade_date=trade_date,
        research=research_result,
        short_trade=short_trade_result,
        candidate_source=candidate_source,
        candidate_reason_codes=candidate_reason_codes,
    )
    evaluation.delta_classification = _classify_delta(evaluation)
    if evaluation.delta_classification == "research_pass_short_reject":
        short_trade_decision = getattr(short_trade_result, "decision", "rejected") if short_trade_result is not None else "rejected"
        evaluation.delta_summary = [f"research target selected while short trade target stays {short_trade_decision}"]
    elif evaluation.delta_classification == "both_pass_but_rank_diverge":
        evaluation.delta_summary = ["research target and short trade target both passed but rank hints diverged"]
    return evaluation


def _build_rejected_evaluation(
    *,
    trade_date: str,
    entry: dict[str, Any],
    rank_hint: int,
    rank_population: int,
    target_mode: TargetMode,
) -> DualTargetEvaluation:
    ticker = str(entry.get("ticker") or "")
    candidate_source, candidate_reason_codes = _resolve_candidate_source(entry=entry, default="watchlist_filter_diagnostics")
    research_result = evaluate_research_rejected_target(trade_date=trade_date, entry=entry, rank_hint=rank_hint)
    short_trade_result = (
        evaluate_short_trade_rejected_target(
            trade_date=trade_date,
            entry=entry,
            rank_hint=rank_hint,
            rank_population=rank_population,
        )
        if target_mode != "research_only"
        else None
    )
    evaluation = DualTargetEvaluation(
        ticker=ticker,
        trade_date=trade_date,
        research=research_result,
        short_trade=short_trade_result,
        candidate_source=candidate_source,
        candidate_reason_codes=candidate_reason_codes,
    )
    evaluation.delta_classification = _classify_delta(evaluation)
    if evaluation.delta_classification == "research_reject_short_pass":
        evaluation.delta_summary = ["short trade target promoted a setup that research pipeline kept as near-miss"]
    elif evaluation.delta_classification == "both_reject_but_reason_diverge":
        evaluation.delta_summary = ["research target rejected by current pipeline filters while short trade target failed its own structural gates"]
    return evaluation


def _build_rejected_with_supplemental_short_trade_evaluation(
    *,
    trade_date: str,
    rejected_entry: dict[str, Any],
    supplemental_entry: dict[str, Any],
    rank_hint: int,
    rank_population: int,
) -> DualTargetEvaluation:
    ticker = str(rejected_entry.get("ticker") or supplemental_entry.get("ticker") or "")
    candidate_source, candidate_reason_codes = _resolve_candidate_source(entry=rejected_entry, default="watchlist_filter_diagnostics")
    _, supplemental_reason_codes = _resolve_candidate_source(entry=supplemental_entry, default="short_trade_boundary")
    research_result = evaluate_research_rejected_target(trade_date=trade_date, entry=rejected_entry, rank_hint=rank_hint)
    short_trade_result = evaluate_short_trade_rejected_target(
        trade_date=trade_date,
        entry=supplemental_entry,
        rank_hint=rank_hint,
        rank_population=rank_population,
    )
    evaluation = DualTargetEvaluation(
        ticker=ticker,
        trade_date=trade_date,
        research=research_result,
        short_trade=short_trade_result,
        candidate_source=candidate_source,
        candidate_reason_codes=_merge_reason_codes(candidate_reason_codes, supplemental_reason_codes),
    )
    evaluation.delta_classification = _classify_delta(evaluation)
    if evaluation.delta_classification == "research_reject_short_pass":
        evaluation.delta_summary = ["short trade target promoted a setup that research pipeline kept as near-miss"]
    elif evaluation.delta_classification == "both_reject_but_reason_diverge":
        evaluation.delta_summary = ["research target rejected by current pipeline filters while short trade target failed its own structural gates"]
    return evaluation


def _build_short_trade_only_evaluation(*, trade_date: str, entry: dict[str, Any], rank_hint: int, rank_population: int) -> DualTargetEvaluation:
    ticker = str(entry.get("ticker") or "")
    candidate_source, candidate_reason_codes = _resolve_candidate_source(entry=entry, default="short_trade_boundary")
    short_trade_result = evaluate_short_trade_rejected_target(
        trade_date=trade_date,
        entry=entry,
        rank_hint=rank_hint,
        rank_population=rank_population,
    )
    evaluation = DualTargetEvaluation(
        ticker=ticker,
        trade_date=trade_date,
        research=None,
        short_trade=short_trade_result,
        candidate_source=candidate_source,
        candidate_reason_codes=candidate_reason_codes,
    )
    if short_trade_result.decision == "selected":
        evaluation.delta_summary = ["short trade target promoted a boundary candidate outside the research funnel"]
    elif short_trade_result.decision == "near_miss":
        evaluation.delta_summary = ["short trade target retained a boundary candidate for follow-up despite no research target"]
    return evaluation


def build_selection_targets(
    *,
    trade_date: str,
    watchlist: list[LayerCResult],
    rejected_entries: list[dict[str, Any]] | None = None,
    supplemental_short_trade_entries: list[dict[str, Any]] | None = None,
    buy_order_tickers: set[str] | None = None,
    target_mode: TargetMode = "research_only",
) -> tuple[dict[str, DualTargetEvaluation], DualTargetSummary]:
    buy_order_tickers = set(buy_order_tickers or set())
    selection_targets: dict[str, DualTargetEvaluation] = {}
    remaining_supplemental_short_trade_entries = build_remaining_supplemental_short_trade_entries(
        supplemental_short_trade_entries=supplemental_short_trade_entries,
        target_mode=target_mode,
    )
    add_watchlist_selection_targets(
        selection_targets=selection_targets,
        watchlist=watchlist,
        buy_order_tickers=buy_order_tickers,
        trade_date=trade_date,
        target_mode=target_mode,
        build_selected_evaluation=_build_selected_evaluation,
    )
    add_rejected_selection_targets(
        selection_targets=selection_targets,
        rejected_entries=rejected_entries,
        remaining_supplemental_short_trade_entries=remaining_supplemental_short_trade_entries,
        trade_date=trade_date,
        target_mode=target_mode,
        build_rejected_with_supplemental_evaluation=_build_rejected_with_supplemental_short_trade_evaluation,
        build_rejected_evaluation=_build_rejected_evaluation,
    )
    add_short_trade_only_selection_targets(
        selection_targets=selection_targets,
        remaining_supplemental_short_trade_entries=remaining_supplemental_short_trade_entries,
        target_mode=target_mode,
        trade_date=trade_date,
        build_short_trade_only_evaluation=_build_short_trade_only_evaluation,
    )

    return selection_targets, summarize_selection_targets(selection_targets=selection_targets, target_mode=target_mode)
