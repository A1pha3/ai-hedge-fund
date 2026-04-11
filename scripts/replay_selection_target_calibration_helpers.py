from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


FilterObservabilityFn = Callable[[list[dict[str, Any]], list[dict[str, Any]], str, str], dict[str, dict[str, int]]]
ApplyFiltersFn = Callable[[list[dict[str, Any]], list[dict[str, Any]], str, str], tuple[list[dict[str, Any]], list[dict[str, Any]]]]
MergeReplayEntriesFn = Callable[[dict[str, Any]], tuple[list[dict[str, Any]], list[dict[str, Any]]]]
CoerceWatchlistFn = Callable[[list[dict[str, Any]]], list[Any]]
MergeObservabilityFn = Callable[[dict[str, Counter[str]], list[dict[str, dict[str, int]]]], dict[str, Counter[str]]]


@dataclass(frozen=True)
class ReplayAnalysisConfig:
    profile_name: str
    structural_variant: str
    effective_structural_overrides: dict[str, Any]
    entry_filter_rules: list[dict[str, Any]]
    focus_ticker_set: set[str]
    structural_profile_overrides: dict[str, Any]


@dataclass
class ReplayAnalysisState:
    stored_decision_counts: Counter[str] = field(default_factory=Counter)
    replayed_decision_counts: Counter[str] = field(default_factory=Counter)
    transition_counts: Counter[str] = field(default_factory=Counter)
    candidate_source_counts: Counter[str] = field(default_factory=Counter)
    mismatch_examples: list[dict[str, Any]] = field(default_factory=list)
    focused_score_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    per_day: list[dict[str, Any]] = field(default_factory=list)
    overall_signal_availability: Counter[str] = field(default_factory=Counter)
    overall_signal_name_counts: Counter[str] = field(default_factory=Counter)
    filtered_candidate_entry_counts: Counter[str] = field(default_factory=Counter)
    candidate_entry_filter_observability: dict[str, Counter[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ReplaySourceContext:
    replay_input_path: Path
    trade_date: str
    target_mode: str
    payload: dict[str, Any]
    watchlist_entries: list[dict[str, Any]]
    upstream_shadow_observation_entries: list[dict[str, Any]]
    rejected_entries: list[dict[str, Any]]
    filtered_rejected_entries: list[dict[str, Any]]
    supplemental_entries: list[dict[str, Any]]
    filtered_supplemental_entries: list[dict[str, Any]]
    replay_entry_index: dict[str, dict[str, Any]]
    filtered_entry_index: dict[str, dict[str, Any]]
    buy_order_tickers: set[str]
    watchlist: list[Any]
    signal_availability: Counter[str]
    signal_name_counts: Counter[str]
    day_candidate_entry_filter_observability: dict[str, Counter[str]]


def build_replay_analysis_config(
    *,
    structural_variants: dict[str, dict[str, Any]],
    profile_name: str,
    structural_variant: str,
    structural_overrides: dict[str, Any] | None,
    focus_tickers: list[str] | None,
    resolve_structural_profile_overrides: Callable[[dict[str, Any]], dict[str, Any]],
) -> ReplayAnalysisConfig:
    effective_structural_overrides = dict(structural_variants.get(structural_variant, {}))
    if structural_overrides:
        effective_structural_overrides.update(dict(structural_overrides or {}))
    return ReplayAnalysisConfig(
        profile_name=str(profile_name or "default"),
        structural_variant=structural_variant,
        effective_structural_overrides=effective_structural_overrides,
        entry_filter_rules=list(effective_structural_overrides.get("exclude_candidate_entries") or []),
        focus_ticker_set={ticker for ticker in (focus_tickers or []) if str(ticker).strip()},
        structural_profile_overrides=resolve_structural_profile_overrides(effective_structural_overrides),
    )


def build_replay_analysis_state() -> ReplayAnalysisState:
    return ReplayAnalysisState()


def prepare_replay_source_context(
    *,
    replay_input_path: Path,
    payload: dict[str, Any],
    entry_filter_rules: list[dict[str, Any]],
    candidate_entry_default_source: str,
    supplemental_default_source: str,
    merge_replay_entries: MergeReplayEntriesFn,
    summarize_filter_observability: FilterObservabilityFn,
    apply_candidate_entry_filters: ApplyFiltersFn,
    coerce_watchlist_entries: CoerceWatchlistFn,
    merge_candidate_entry_filter_observability: MergeObservabilityFn,
    state_candidate_entry_filter_observability: dict[str, Counter[str]],
    summarize_signal_availability: Callable[[list[dict[str, Any]]], tuple[Counter[str], Counter[str]]],
) -> ReplaySourceContext:
    trade_date = str(payload.get("trade_date") or "")
    target_mode = str(payload.get("target_mode") or "research_only")
    watchlist_entries = [dict(entry or {}) for entry in list(payload.get("watchlist") or [])]
    replay_short_trade_entries, upstream_shadow_observation_entries = merge_replay_entries(payload)
    rejected_entries_input = [dict(entry or {}) for entry in list(payload.get("rejected_entries") or [])]

    rejected_filter_observability = summarize_filter_observability(
        rejected_entries_input,
        entry_filter_rules,
        trade_date=trade_date,
        default_candidate_source=candidate_entry_default_source,
    )
    supplemental_filter_observability = summarize_filter_observability(
        replay_short_trade_entries,
        entry_filter_rules,
        trade_date=trade_date,
        default_candidate_source=supplemental_default_source,
    )
    rejected_entries, filtered_rejected_entries = apply_candidate_entry_filters(
        rejected_entries_input,
        entry_filter_rules,
        trade_date=trade_date,
        default_candidate_source=candidate_entry_default_source,
    )
    supplemental_entries, filtered_supplemental_entries = apply_candidate_entry_filters(
        replay_short_trade_entries,
        entry_filter_rules,
        trade_date=trade_date,
        default_candidate_source=supplemental_default_source,
    )

    filtered_entry_index = {
        str(entry.get("ticker") or ""): entry
        for entry in filtered_rejected_entries + filtered_supplemental_entries
        if str(entry.get("ticker") or "").strip()
    }
    replay_entry_index = {
        str(entry.get("ticker") or ""): entry
        for entry in list(watchlist_entries) + rejected_entries + supplemental_entries
        if str(entry.get("ticker") or "").strip()
    }
    buy_order_tickers = {str(ticker) for ticker in list(payload.get("buy_order_tickers") or []) if str(ticker or "").strip()}
    watchlist = coerce_watchlist_entries(watchlist_entries)
    signal_availability, signal_name_counts = summarize_signal_availability(watchlist_entries + supplemental_entries)
    day_candidate_entry_filter_observability = merge_candidate_entry_filter_observability(
        state_candidate_entry_filter_observability,
        [rejected_filter_observability, supplemental_filter_observability],
    )
    return ReplaySourceContext(
        replay_input_path=replay_input_path,
        trade_date=trade_date,
        target_mode=target_mode,
        payload=payload,
        watchlist_entries=watchlist_entries,
        upstream_shadow_observation_entries=upstream_shadow_observation_entries,
        rejected_entries=rejected_entries,
        filtered_rejected_entries=filtered_rejected_entries,
        supplemental_entries=supplemental_entries,
        filtered_supplemental_entries=filtered_supplemental_entries,
        replay_entry_index=replay_entry_index,
        filtered_entry_index=filtered_entry_index,
        buy_order_tickers=buy_order_tickers,
        watchlist=watchlist,
        signal_availability=signal_availability,
        signal_name_counts=signal_name_counts,
        day_candidate_entry_filter_observability=day_candidate_entry_filter_observability,
    )


def ingest_replay_source_analysis(
    *,
    state: ReplayAnalysisState,
    source_context: ReplaySourceContext,
    source_analysis: dict[str, Any],
    replayed_summary: Any,
) -> None:
    state.stored_decision_counts.update(source_analysis["stored_decision_counts"])
    state.replayed_decision_counts.update(source_analysis["replayed_decision_counts"])
    state.transition_counts.update(source_analysis["transition_counts"])
    state.candidate_source_counts.update(source_analysis["candidate_source_counts"])
    state.mismatch_examples.extend(source_analysis["mismatch_examples"])
    state.focused_score_diagnostics.extend(source_analysis["focused_score_diagnostics"])
    state.overall_signal_availability.update(source_context.signal_availability)
    state.overall_signal_name_counts.update(source_context.signal_name_counts)
    state.filtered_candidate_entry_counts.update(
        entry["matched_filter"] for entry in source_context.filtered_rejected_entries + source_context.filtered_supplemental_entries
    )
    state.per_day.append(
        build_replay_day_summary(
            source_context=source_context,
            replayed_summary=replayed_summary,
            day_transition_counts=source_analysis["day_transition_counts"],
            day_mismatch_count=int(source_analysis["day_mismatch_count"]),
            stored_decision_counts=source_analysis["stored_decision_counts"],
        )
    )


def build_replay_day_summary(
    *,
    source_context: ReplaySourceContext,
    replayed_summary: Any,
    day_transition_counts: Counter[str],
    day_mismatch_count: int,
    stored_decision_counts: Counter[str],
) -> dict[str, Any]:
    return {
        "trade_date": source_context.trade_date,
        "target_mode": source_context.target_mode,
        "replay_input_path": str(source_context.replay_input_path),
        "stored_short_trade_decision_counts": dict(stored_decision_counts.most_common()),
        "replayed_short_trade_decision_counts": {
            "selected": int(replayed_summary.short_trade_selected_count),
            "near_miss": int(replayed_summary.short_trade_near_miss_count),
            "blocked": int(replayed_summary.short_trade_blocked_count),
            "rejected": int(replayed_summary.short_trade_rejected_count),
        },
        "decision_transition_counts": dict(day_transition_counts.most_common()),
        "decision_mismatch_count": day_mismatch_count,
        "source_summary": dict(source_context.payload.get("source_summary") or {}),
        "upstream_shadow_observation_entry_count": len(source_context.upstream_shadow_observation_entries),
        "candidate_entry_filter_observability": {
            rule_name: {key: int(value) for key, value in counters.items()}
            for rule_name, counters in sorted(source_context.day_candidate_entry_filter_observability.items())
        },
        "filtered_candidate_entries": source_context.filtered_rejected_entries + source_context.filtered_supplemental_entries,
        "signal_availability": source_context.signal_availability,
        "available_strategy_signal_counts": source_context.signal_name_counts,
    }


def build_replay_analysis_result(
    *,
    replay_input_count: int,
    config: ReplayAnalysisConfig,
    state: ReplayAnalysisState,
    select_threshold: float | None,
    near_miss_threshold: float | None,
    default_profile: Any,
) -> dict[str, Any]:
    return {
        "replay_input_count": replay_input_count,
        "trade_date_count": len(state.per_day),
        "profile_name": config.profile_name,
        "structural_variant": config.structural_variant,
        "structural_overrides": config.effective_structural_overrides,
        "select_threshold": float(select_threshold) if select_threshold is not None else float(default_profile.select_threshold),
        "near_miss_threshold": float(near_miss_threshold) if near_miss_threshold is not None else float(default_profile.near_miss_threshold),
        "stored_short_trade_decision_counts": dict(state.stored_decision_counts.most_common()),
        "replayed_short_trade_decision_counts": dict(state.replayed_decision_counts.most_common()),
        "decision_transition_counts": dict(state.transition_counts.most_common()),
        "decision_mismatch_count": int(sum(row["decision_mismatch_count"] for row in state.per_day)),
        "candidate_source_counts": dict(state.candidate_source_counts.most_common()),
        "entry_filter_rules": config.entry_filter_rules,
        "filtered_candidate_entry_counts": dict(state.filtered_candidate_entry_counts.most_common()),
        "candidate_entry_filter_observability": {
            rule_name: {key: int(value) for key, value in counters.items()}
            for rule_name, counters in sorted(state.candidate_entry_filter_observability.items())
        },
        "signal_availability": dict(state.overall_signal_availability.most_common()),
        "available_strategy_signal_counts": dict(state.overall_signal_name_counts.most_common()),
        "by_trade_date": sorted(state.per_day, key=lambda row: row["trade_date"]),
        "mismatch_examples": state.mismatch_examples,
        "focus_tickers": sorted(config.focus_ticker_set),
        "focused_score_diagnostics": sorted(state.focused_score_diagnostics, key=lambda row: (row["trade_date"], row["ticker"])),
    }
