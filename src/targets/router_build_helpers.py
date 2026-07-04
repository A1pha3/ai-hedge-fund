from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.execution.models import LayerCResult
from src.targets.models import (
    DualTargetEvaluation,
    DualTargetSummary,
    TargetEvaluationResult,
    TargetMode,
)

FORMAL_EXECUTION_BLOCK_FLAGS = (
    "p2_execution_blocked",
    "p3_execution_blocked",
    "p5_execution_blocked",
    "p6_execution_blocked",
)


def _read_field(payload: Any, field_name: str) -> Any:
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload.get(field_name)
    return getattr(payload, field_name, None)


def build_dual_target_summary(*, selection_targets: dict[str, DualTargetEvaluation], target_mode: TargetMode) -> DualTargetSummary:
    summary = DualTargetSummary(target_mode=target_mode, selection_target_count=len(selection_targets))
    for evaluation in selection_targets.values():
        if bool(_read_field(evaluation, "execution_eligible")):
            summary.execution_eligible_count += 1
        research_result = _read_field(evaluation, "research")
        short_trade_result = _read_field(evaluation, "short_trade")
        _accumulate_target_result(summary=summary, result=research_result, target_type="research")
        _accumulate_target_result(summary=summary, result=short_trade_result, target_type="short_trade")
        if research_result is None and short_trade_result is None:
            summary.shell_target_count += 1
        delta_classification = str(_read_field(evaluation, "delta_classification") or "").strip()
        if delta_classification:
            summary.delta_classification_counts[delta_classification] = int(summary.delta_classification_counts.get(delta_classification) or 0) + 1
        if bool(_read_field(evaluation, "p2_execution_blocked")):
            summary.p2_execution_blocked_count += 1
        if bool(_read_field(evaluation, "p3_execution_blocked")):
            summary.p3_execution_blocked_count += 1
        label = str(_read_field(evaluation, "p3_prior_quality_label") or "").strip()
        if label:
            summary.p3_prior_quality_distribution[label] = int(summary.p3_prior_quality_distribution.get(label) or 0) + 1
    return summary


def collect_formal_execution_block_flags(evaluation: Any, short_trade_result: Any | None = None) -> list[str]:
    short_trade_result = short_trade_result if short_trade_result is not None else _read_field(evaluation, "short_trade")
    return [flag for flag in FORMAL_EXECUTION_BLOCK_FLAGS if bool(_read_field(evaluation, flag)) or bool(_read_field(short_trade_result, flag))]


def resolve_short_trade_reporting_decision(evaluation: Any, short_trade_result: Any | None = None) -> tuple[str, list[str]]:
    short_trade_result = short_trade_result if short_trade_result is not None else _read_field(evaluation, "short_trade")
    raw_decision = str(_read_field(short_trade_result, "decision") or "")
    formal_execution_block_flags = collect_formal_execution_block_flags(evaluation, short_trade_result)
    if raw_decision in {"selected", "near_miss"} and formal_execution_block_flags:
        return "blocked", formal_execution_block_flags
    return raw_decision, formal_execution_block_flags


def _resolve_formal_block_gate_label(evaluation: Any, short_trade_result: Any | None = None) -> str | None:
    short_trade_result = short_trade_result if short_trade_result is not None else _read_field(evaluation, "short_trade")
    gate_label = str(_read_field(evaluation, "btst_regime_gate") or _read_field(short_trade_result, "btst_regime_gate") or "").strip()
    if gate_label:
        return gate_label
    p2_reason = str(_read_field(evaluation, "p2_execution_block_reason") or "").strip()
    if ":" in p2_reason:
        _, _, suffix = p2_reason.rpartition(":")
        normalized = suffix.strip()
        if normalized:
            return normalized
    return None


def _resolve_formal_block_prior_quality_label(evaluation: Any, short_trade_result: Any | None = None) -> str | None:
    short_trade_result = short_trade_result if short_trade_result is not None else _read_field(evaluation, "short_trade")
    for field_name in ("historical_prior_quality_level", "p3_prior_quality_label"):
        value = str(_read_field(evaluation, field_name) or _read_field(short_trade_result, field_name) or "").strip()
        if value:
            return value
    return None


def _is_non_halt_formal_block(evaluation: Any, short_trade_result: Any | None = None) -> bool:
    gate_label = str(_resolve_formal_block_gate_label(evaluation, short_trade_result) or "").strip().lower()
    p2_reason = str(_read_field(evaluation, "p2_execution_block_reason") or "").strip().lower()
    return gate_label != "halt" and "halt" not in p2_reason


def build_reporting_target_summary(*, selection_targets: dict[str, Any], target_mode: TargetMode | str) -> DualTargetSummary:
    summary = DualTargetSummary(target_mode=target_mode, selection_target_count=len(selection_targets))
    for evaluation in selection_targets.values():
        if bool(_read_field(evaluation, "execution_eligible")):
            summary.execution_eligible_count += 1
        research_result = _read_field(evaluation, "research")
        short_trade_result = _read_field(evaluation, "short_trade")
        _accumulate_target_result(summary=summary, result=research_result, target_type="research")
        reporting_decision, formal_execution_block_flags = resolve_short_trade_reporting_decision(evaluation, short_trade_result)
        raw_decision = str(_read_field(short_trade_result, "decision") or "")
        if raw_decision == "selected" and formal_execution_block_flags:
            summary.short_trade_formal_blocked_selected_count += 1
            for flag in formal_execution_block_flags:
                summary.short_trade_formal_block_flag_counts[flag] = int(summary.short_trade_formal_block_flag_counts.get(flag) or 0) + 1
            if _is_non_halt_formal_block(evaluation, short_trade_result):
                summary.short_trade_formal_non_halt_blocked_selected_count += 1
                gate_label = _resolve_formal_block_gate_label(evaluation, short_trade_result)
                if gate_label:
                    summary.short_trade_formal_non_halt_gate_counts[gate_label] = int(summary.short_trade_formal_non_halt_gate_counts.get(gate_label) or 0) + 1
                prior_quality_label = _resolve_formal_block_prior_quality_label(evaluation, short_trade_result)
                if prior_quality_label:
                    summary.short_trade_formal_non_halt_prior_quality_counts[prior_quality_label] = int(summary.short_trade_formal_non_halt_prior_quality_counts.get(prior_quality_label) or 0) + 1
        _accumulate_target_result(
            summary=summary,
            result=short_trade_result,
            target_type="short_trade",
            decision_override=reporting_decision,
        )
        if research_result is None and short_trade_result is None:
            summary.shell_target_count += 1
        delta_classification = str(_read_field(evaluation, "delta_classification") or "").strip()
        if delta_classification:
            summary.delta_classification_counts[delta_classification] = int(summary.delta_classification_counts.get(delta_classification) or 0) + 1
        if bool(_read_field(evaluation, "p2_execution_blocked")):
            summary.p2_execution_blocked_count += 1
        if bool(_read_field(evaluation, "p3_execution_blocked")):
            summary.p3_execution_blocked_count += 1
        label = str(_read_field(evaluation, "p3_prior_quality_label") or "").strip()
        if label:
            summary.p3_prior_quality_distribution[label] = int(summary.p3_prior_quality_distribution.get(label) or 0) + 1
    return summary


def _accumulate_target_result(*, summary: DualTargetSummary, result: TargetEvaluationResult | dict[str, Any] | None, target_type: str, decision_override: str | None = None) -> None:
    if result is None:
        return
    decision = str(decision_override or _read_field(result, "decision") or "")
    if target_type == "research":
        summary.research_target_count += 1
        if decision == "selected":
            summary.research_selected_count += 1
        elif decision == "near_miss":
            summary.research_near_miss_count += 1
        else:
            summary.research_rejected_count += 1
        return
    summary.short_trade_target_count += 1
    if decision == "selected":
        summary.short_trade_selected_count += 1
    elif decision == "near_miss":
        summary.short_trade_near_miss_count += 1
    elif decision == "blocked":
        summary.short_trade_blocked_count += 1
    else:
        summary.short_trade_rejected_count += 1


def build_remaining_supplemental_short_trade_entries(
    *,
    supplemental_short_trade_entries: list[dict[str, Any]] | None,
    target_mode: TargetMode,
) -> dict[str, dict[str, Any]]:
    if target_mode == "research_only":
        return {}
    remaining_entries: dict[str, dict[str, Any]] = {}
    sorted_entries = sorted(
        supplemental_short_trade_entries or [],
        key=lambda current: float(current.get("score_final", current.get("score_b", 0.0)) or 0.0),
        reverse=True,
    )
    for entry in sorted_entries:
        ticker = str(entry.get("ticker") or "")
        if ticker and ticker not in remaining_entries:
            remaining_entries[ticker] = entry
    return remaining_entries


def add_watchlist_selection_targets(
    *,
    selection_targets: dict[str, DualTargetEvaluation],
    watchlist: list[LayerCResult],
    buy_order_tickers: set[str],
    trade_date: str,
    target_mode: TargetMode,
    build_selected_evaluation: Callable[..., DualTargetEvaluation],
) -> None:
    sorted_watchlist = sorted(watchlist, key=lambda current: current.score_final, reverse=True)
    rank_population = len(sorted_watchlist)
    for rank_hint, item in enumerate(sorted_watchlist, start=1):
        selection_targets[item.ticker] = build_selected_evaluation(
            trade_date=trade_date,
            item=item,
            rank_hint=rank_hint,
            rank_population=rank_population,
            included_in_buy_orders=item.ticker in buy_order_tickers,
            target_mode=target_mode,
        )


def add_rejected_selection_targets(
    *,
    selection_targets: dict[str, DualTargetEvaluation],
    rejected_entries: list[dict[str, Any]] | None,
    remaining_supplemental_short_trade_entries: dict[str, dict[str, Any]],
    trade_date: str,
    target_mode: TargetMode,
    build_rejected_with_supplemental_evaluation: Callable[..., DualTargetEvaluation],
    build_rejected_evaluation: Callable[..., DualTargetEvaluation],
) -> None:
    sorted_rejected_entries = sorted(
        rejected_entries or [],
        key=lambda current: float(current.get("score_final", current.get("score_b", 0.0)) or 0.0),
        reverse=True,
    )
    rank_population = len(sorted_rejected_entries)
    for rank_hint, entry in enumerate(sorted_rejected_entries, start=1):
        ticker = str(entry.get("ticker") or "")
        if not ticker or ticker in selection_targets:
            continue
        supplemental_entry = remaining_supplemental_short_trade_entries.pop(ticker, None) if target_mode != "research_only" else None
        if supplemental_entry is not None:
            selection_targets[ticker] = build_rejected_with_supplemental_evaluation(
                trade_date=trade_date,
                rejected_entry=entry,
                supplemental_entry=supplemental_entry,
                rank_hint=rank_hint,
                rank_population=rank_population,
            )
            continue
        selection_targets[ticker] = build_rejected_evaluation(
            trade_date=trade_date,
            entry=entry,
            rank_hint=rank_hint,
            rank_population=rank_population,
            target_mode=target_mode,
        )


def add_short_trade_only_selection_targets(
    *,
    selection_targets: dict[str, DualTargetEvaluation],
    remaining_supplemental_short_trade_entries: dict[str, dict[str, Any]],
    target_mode: TargetMode,
    trade_date: str,
    build_short_trade_only_evaluation: Callable[..., DualTargetEvaluation],
) -> None:
    if target_mode == "research_only":
        return
    supplemental_entries = list(remaining_supplemental_short_trade_entries.values())
    rank_population = len(supplemental_entries)
    for rank_hint, entry in enumerate(supplemental_entries, start=1):
        ticker = str(entry.get("ticker") or "")
        if not ticker or ticker in selection_targets:
            continue
        selection_targets[ticker] = build_short_trade_only_evaluation(
            trade_date=trade_date,
            entry=entry,
            rank_hint=rank_hint,
            rank_population=rank_population,
        )
