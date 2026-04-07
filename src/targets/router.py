from __future__ import annotations

from typing import Any

from src.execution.models import LayerCResult
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetMode
from src.targets.research_target import evaluate_research_rejected_target, evaluate_research_selected_target
from src.targets.short_trade_target import evaluate_short_trade_rejected_target, evaluate_short_trade_selected_target


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
    summary = DualTargetSummary(target_mode=target_mode, selection_target_count=len(selection_targets))
    for evaluation in selection_targets.values():
        if evaluation.research is not None:
            summary.research_target_count += 1
            if evaluation.research.decision == "selected":
                summary.research_selected_count += 1
            elif evaluation.research.decision == "near_miss":
                summary.research_near_miss_count += 1
            else:
                summary.research_rejected_count += 1
        if evaluation.short_trade is not None:
            summary.short_trade_target_count += 1
            if evaluation.short_trade.decision == "selected":
                summary.short_trade_selected_count += 1
            elif evaluation.short_trade.decision == "near_miss":
                summary.short_trade_near_miss_count += 1
            elif evaluation.short_trade.decision == "blocked":
                summary.short_trade_blocked_count += 1
            else:
                summary.short_trade_rejected_count += 1
        if evaluation.research is None and evaluation.short_trade is None:
            summary.shell_target_count += 1
        if evaluation.delta_classification:
            summary.delta_classification_counts[evaluation.delta_classification] = int(summary.delta_classification_counts.get(evaluation.delta_classification) or 0) + 1
    return summary


def _build_selected_evaluation(*, trade_date: str, item: LayerCResult, rank_hint: int, included_in_buy_orders: bool, target_mode: TargetMode) -> DualTargetEvaluation:
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


def _build_rejected_evaluation(*, trade_date: str, entry: dict[str, Any], rank_hint: int, target_mode: TargetMode) -> DualTargetEvaluation:
    ticker = str(entry.get("ticker") or "")
    candidate_source, candidate_reason_codes = _resolve_candidate_source(entry=entry, default="watchlist_filter_diagnostics")
    research_result = evaluate_research_rejected_target(trade_date=trade_date, entry=entry, rank_hint=rank_hint)
    short_trade_result = evaluate_short_trade_rejected_target(trade_date=trade_date, entry=entry, rank_hint=rank_hint) if target_mode != "research_only" else None
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
) -> DualTargetEvaluation:
    ticker = str(rejected_entry.get("ticker") or supplemental_entry.get("ticker") or "")
    candidate_source, candidate_reason_codes = _resolve_candidate_source(entry=rejected_entry, default="watchlist_filter_diagnostics")
    _, supplemental_reason_codes = _resolve_candidate_source(entry=supplemental_entry, default="short_trade_boundary")
    research_result = evaluate_research_rejected_target(trade_date=trade_date, entry=rejected_entry, rank_hint=rank_hint)
    short_trade_result = evaluate_short_trade_rejected_target(trade_date=trade_date, entry=supplemental_entry, rank_hint=rank_hint)
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


def _build_short_trade_only_evaluation(*, trade_date: str, entry: dict[str, Any], rank_hint: int) -> DualTargetEvaluation:
    ticker = str(entry.get("ticker") or "")
    candidate_source, candidate_reason_codes = _resolve_candidate_source(entry=entry, default="short_trade_boundary")
    short_trade_result = evaluate_short_trade_rejected_target(trade_date=trade_date, entry=entry, rank_hint=rank_hint)
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
    remaining_supplemental_short_trade_entries: dict[str, dict[str, Any]] = {}

    if target_mode != "research_only":
        sorted_supplemental_entries = sorted(
            list(supplemental_short_trade_entries or []),
            key=lambda current: float(current.get("score_final", current.get("score_b", 0.0)) or 0.0),
            reverse=True,
        )
        for entry in sorted_supplemental_entries:
            ticker = str(entry.get("ticker") or "")
            if ticker and ticker not in remaining_supplemental_short_trade_entries:
                remaining_supplemental_short_trade_entries[ticker] = entry

    for rank_hint, item in enumerate(sorted(watchlist, key=lambda current: current.score_final, reverse=True), start=1):
        selection_targets[item.ticker] = _build_selected_evaluation(
            trade_date=trade_date,
            item=item,
            rank_hint=rank_hint,
            included_in_buy_orders=item.ticker in buy_order_tickers,
            target_mode=target_mode,
        )

    for rank_hint, entry in enumerate(sorted(list(rejected_entries or []), key=lambda current: float(current.get("score_final", current.get("score_b", 0.0)) or 0.0), reverse=True), start=1):
        ticker = str(entry.get("ticker") or "")
        if not ticker or ticker in selection_targets:
            continue
        supplemental_entry = remaining_supplemental_short_trade_entries.pop(ticker, None) if target_mode != "research_only" else None
        if supplemental_entry is not None:
            selection_targets[ticker] = _build_rejected_with_supplemental_short_trade_evaluation(
                trade_date=trade_date,
                rejected_entry=entry,
                supplemental_entry=supplemental_entry,
                rank_hint=rank_hint,
            )
        else:
            selection_targets[ticker] = _build_rejected_evaluation(
                trade_date=trade_date,
                entry=entry,
                rank_hint=rank_hint,
                target_mode=target_mode,
            )

    if target_mode != "research_only":
        for rank_hint, entry in enumerate(remaining_supplemental_short_trade_entries.values(), start=1):
            ticker = str(entry.get("ticker") or "")
            if not ticker or ticker in selection_targets:
                continue
            selection_targets[ticker] = _build_short_trade_only_evaluation(
                trade_date=trade_date,
                entry=entry,
                rank_hint=rank_hint,
            )

    return selection_targets, summarize_selection_targets(selection_targets=selection_targets, target_mode=target_mode)
