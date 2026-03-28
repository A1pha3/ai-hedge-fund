from __future__ import annotations

from typing import Any

from src.execution.models import LayerCResult
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetMode
from src.targets.research_target import evaluate_research_rejected_target, evaluate_research_selected_target
from src.targets.short_trade_target import evaluate_short_trade_skeleton


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
            else:
                summary.short_trade_rejected_count += 1
        if evaluation.research is None and evaluation.short_trade is None:
            summary.shell_target_count += 1
        if evaluation.delta_classification:
            summary.delta_classification_counts[evaluation.delta_classification] = int(summary.delta_classification_counts.get(evaluation.delta_classification) or 0) + 1
    return summary


def _build_selected_evaluation(*, trade_date: str, item: LayerCResult, rank_hint: int, included_in_buy_orders: bool, target_mode: TargetMode) -> DualTargetEvaluation:
    research_result = evaluate_research_selected_target(
        trade_date=trade_date,
        item=item,
        rank_hint=rank_hint,
        included_in_buy_orders=included_in_buy_orders,
    )
    short_trade_result = evaluate_short_trade_skeleton(trade_date=trade_date, ticker=item.ticker) if target_mode != "research_only" else None
    evaluation = DualTargetEvaluation(
        ticker=item.ticker,
        trade_date=trade_date,
        research=research_result,
        short_trade=short_trade_result,
    )
    evaluation.delta_classification = _classify_delta(evaluation)
    if evaluation.delta_classification == "research_pass_short_reject":
        evaluation.delta_summary = ["research target selected while short trade target remains blocked by skeleton rules"]
    return evaluation


def _build_rejected_evaluation(*, trade_date: str, entry: dict[str, Any], rank_hint: int, target_mode: TargetMode) -> DualTargetEvaluation:
    ticker = str(entry.get("ticker") or "")
    research_result = evaluate_research_rejected_target(trade_date=trade_date, entry=entry, rank_hint=rank_hint)
    short_trade_result = evaluate_short_trade_skeleton(trade_date=trade_date, ticker=ticker) if target_mode != "research_only" else None
    evaluation = DualTargetEvaluation(
        ticker=ticker,
        trade_date=trade_date,
        research=research_result,
        short_trade=short_trade_result,
    )
    evaluation.delta_classification = _classify_delta(evaluation)
    if evaluation.delta_classification == "both_reject_but_reason_diverge":
        evaluation.delta_summary = ["research target rejected by current pipeline filters while short trade target is still skeleton-only"]
    return evaluation


def build_selection_targets(
    *,
    trade_date: str,
    watchlist: list[LayerCResult],
    rejected_entries: list[dict[str, Any]] | None = None,
    buy_order_tickers: set[str] | None = None,
    target_mode: TargetMode = "research_only",
) -> tuple[dict[str, DualTargetEvaluation], DualTargetSummary]:
    buy_order_tickers = set(buy_order_tickers or set())
    selection_targets: dict[str, DualTargetEvaluation] = {}

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
        selection_targets[ticker] = _build_rejected_evaluation(
            trade_date=trade_date,
            entry=entry,
            rank_hint=rank_hint,
            target_mode=target_mode,
        )

    return selection_targets, summarize_selection_targets(selection_targets=selection_targets, target_mode=target_mode)