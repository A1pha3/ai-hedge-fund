"""Watchlist and merge-approved helpers for the daily pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Callable

from src.execution.models import LayerCResult


WatchlistFilterClassifier = Callable[[LayerCResult], tuple[str, list[str]]]
FilterSummaryBuilder = Callable[[list[dict[str, Any]]], dict[str, Any]]


@dataclass(frozen=True)
class WatchlistDiagnosticsConfig:
    watchlist_score_threshold: float
    shadow_release_max_tickers: int
    shadow_release_score_b_min: float
    shadow_release_score_final_min: float
    shadow_release_score_c_min: float
    shadow_release_conflicts: frozenset[str]


def build_watchlist_filter_diagnostics(
    layer_c_results: list[LayerCResult],
    watchlist: list[LayerCResult],
    *,
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
    config: WatchlistDiagnosticsConfig,
    classify_watchlist_filter: WatchlistFilterClassifier,
    build_filter_summary: FilterSummaryBuilder,
) -> dict[str, Any]:
    selected_tickers, ordered_selected_tickers = _build_watchlist_ticker_index(watchlist)
    released_shadow_entries: list[dict[str, Any]] = []
    entries, selected_entries, ranked_released_shadow_entries = _collect_watchlist_filter_entries(
        layer_c_results=layer_c_results,
        selected_tickers=selected_tickers,
        merge_approved_tickers=merge_approved_tickers,
        threshold_relaxation=threshold_relaxation,
        config=config,
        classify_watchlist_filter=classify_watchlist_filter,
    )
    summary = build_filter_summary(entries)
    _append_ranked_watchlist_shadow_entries(
        ranked_entries=ranked_released_shadow_entries,
        released_shadow_entries=released_shadow_entries,
        shadow_release_max_tickers=config.shadow_release_max_tickers,
    )
    summary.update(
        _build_watchlist_filter_summary_updates(
            selected_tickers=ordered_selected_tickers,
            selected_entries=selected_entries,
            released_shadow_entries=released_shadow_entries,
            merge_approved_tickers=merge_approved_tickers,
            threshold_relaxation=threshold_relaxation,
            config=config,
        )
    )
    return summary


def build_merge_approved_watchlist(
    layer_c_results: list[LayerCResult],
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
    *,
    watchlist_score_threshold: float,
) -> list[LayerCResult]:
    return [
        item
        for item in layer_c_results
        if item.decision != "avoid"
        and item.score_final >= _watchlist_threshold_for_ticker(
            item.ticker,
            merge_approved_tickers,
            threshold_relaxation,
            watchlist_score_threshold=watchlist_score_threshold,
        )
    ]


def tag_merge_approved_layer_c_results(
    layer_c_results: list[LayerCResult],
    merge_approved_tickers: set[str],
) -> list[LayerCResult]:
    if not merge_approved_tickers:
        return layer_c_results

    tagged_results: list[LayerCResult] = []
    for item in layer_c_results:
        if item.ticker not in merge_approved_tickers:
            tagged_results.append(item)
            continue
        tagged_results.append(item.model_copy(update=_build_merge_approved_layer_c_tag_update(item)))
    return tagged_results


def _build_watchlist_ticker_index(watchlist: list[LayerCResult]) -> tuple[set[str], list[str]]:
    ordered_tickers = [item.ticker for item in watchlist]
    return set(ordered_tickers), ordered_tickers


def _collect_watchlist_filter_entries(
    *,
    layer_c_results: list[LayerCResult],
    selected_tickers: set[str],
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
    config: WatchlistDiagnosticsConfig,
    classify_watchlist_filter: WatchlistFilterClassifier,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[tuple[float, float, dict[str, Any]]]]:
    entries: list[dict[str, Any]] = []
    selected_entries: list[dict[str, Any]] = []
    ranked_released_shadow_entries: list[tuple[float, float, dict[str, Any]]] = []

    for item in layer_c_results:
        payload = _build_watchlist_filter_payload(
            item=item,
            merge_approved_tickers=merge_approved_tickers,
            threshold_relaxation=threshold_relaxation,
            watchlist_score_threshold=config.watchlist_score_threshold,
        )
        if item.ticker in selected_tickers:
            selected_entries.append(payload)
            continue

        filtered_entry, primary_reason, reasons = _build_watchlist_filtered_entry(
            item=item,
            payload=payload,
            classify_watchlist_filter=classify_watchlist_filter,
        )
        entries.append(filtered_entry)
        should_release, release_reason = _should_release_watchlist_shadow_candidate(
            item=item,
            primary_reason=primary_reason,
            config=config,
        )
        if should_release and release_reason is not None:
            ranked_released_shadow_entries.append(
                _build_ranked_watchlist_shadow_entry(
                    item=item,
                    reasons=reasons,
                    release_reason=release_reason,
                    config=config,
                )
            )

    return entries, selected_entries, ranked_released_shadow_entries


def _build_watchlist_filter_payload(
    *,
    item: LayerCResult,
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
    watchlist_score_threshold: float,
) -> dict[str, Any]:
    return {
        "ticker": item.ticker,
        "score_b": round(item.score_b, 4),
        "score_c": round(item.score_c, 4),
        "score_final": round(item.score_final, 4),
        "quality_score": round(item.quality_score, 4),
        "decision": item.decision,
        "bc_conflict": item.bc_conflict,
        "merge_approved_ticker": item.ticker in merge_approved_tickers,
        "required_score_final_threshold": round(
            _watchlist_threshold_for_ticker(
                item.ticker,
                merge_approved_tickers,
                threshold_relaxation,
                watchlist_score_threshold=watchlist_score_threshold,
            ),
            4,
        ),
        "strategy_signals": {
            name: signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {})
            for name, signal in dict(item.strategy_signals or {}).items()
        },
        "agent_contribution_summary": item.agent_contribution_summary,
    }


def _build_watchlist_filtered_entry(
    *,
    item: LayerCResult,
    payload: dict[str, Any],
    classify_watchlist_filter: WatchlistFilterClassifier,
) -> tuple[dict[str, Any], str, list[str]]:
    primary_reason, reasons = classify_watchlist_filter(item)
    return {**payload, "reason": primary_reason, "reasons": reasons}, primary_reason, reasons


def _build_ranked_watchlist_shadow_entry(
    *,
    item: LayerCResult,
    reasons: list[str],
    release_reason: str,
    config: WatchlistDiagnosticsConfig,
) -> tuple[float, float, dict[str, Any]]:
    return (
        float(item.score_final),
        float(item.score_b),
        _build_watchlist_shadow_release_entry(
            item=item,
            reasons=reasons,
            release_reason=release_reason,
            config=config,
        ),
    )


def _append_ranked_watchlist_shadow_entries(
    *,
    ranked_entries: list[tuple[float, float, dict[str, Any]]],
    released_shadow_entries: list[dict[str, Any]],
    shadow_release_max_tickers: int,
) -> None:
    ranked_entries.sort(key=lambda row: (row[0], row[1], str(row[2].get("ticker") or "")), reverse=True)
    for rank, (_, _, entry) in enumerate(ranked_entries[:shadow_release_max_tickers], start=1):
        entry["rank"] = rank
        released_shadow_entries.append(entry)


def _build_watchlist_selection_thresholds(
    *,
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
    watchlist_score_threshold: float,
) -> dict[str, Any]:
    return {
        "default_score_final_min": round(watchlist_score_threshold, 4),
        "merge_approved_score_final_min": round(max(0.0, watchlist_score_threshold - threshold_relaxation), 4),
        "merge_approved_tickers": sorted(merge_approved_tickers),
        "merge_approved_threshold_relaxation": round(threshold_relaxation, 4),
    }


def _build_watchlist_prefilter_thresholds(config: WatchlistDiagnosticsConfig) -> dict[str, Any]:
    return {
        "score_b_min": round(config.shadow_release_score_b_min, 4),
        "score_final_min": round(config.shadow_release_score_final_min, 4),
        "score_c_min": round(config.shadow_release_score_c_min, 4),
        "conflicts": sorted(config.shadow_release_conflicts),
    }


def _build_watchlist_selected_summary(*, selected_tickers: list[str], selected_entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "selected_tickers": selected_tickers,
        "selected_entries": selected_entries,
    }


def _build_watchlist_released_shadow_summary(released_shadow_entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "released_shadow_count": len(released_shadow_entries),
        "released_shadow_tickers": [entry["ticker"] for entry in released_shadow_entries],
        "released_shadow_entries": released_shadow_entries,
    }


def _build_watchlist_threshold_summaries(
    *,
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
    config: WatchlistDiagnosticsConfig,
) -> dict[str, Any]:
    return {
        "prefilter_thresholds": _build_watchlist_prefilter_thresholds(config),
        "selection_thresholds": _build_watchlist_selection_thresholds(
            merge_approved_tickers=merge_approved_tickers,
            threshold_relaxation=threshold_relaxation,
            watchlist_score_threshold=config.watchlist_score_threshold,
        ),
    }


def _build_watchlist_filter_summary_updates(
    *,
    selected_tickers: list[str],
    selected_entries: list[dict[str, Any]],
    released_shadow_entries: list[dict[str, Any]],
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
    config: WatchlistDiagnosticsConfig,
) -> dict[str, Any]:
    updates = _build_watchlist_selected_summary(
        selected_tickers=selected_tickers,
        selected_entries=selected_entries,
    )
    updates.update(_build_watchlist_released_shadow_summary(released_shadow_entries))
    updates.update(
        _build_watchlist_threshold_summaries(
            merge_approved_tickers=merge_approved_tickers,
            threshold_relaxation=threshold_relaxation,
            config=config,
        )
    )
    return updates


def _watchlist_threshold_for_ticker(
    ticker: str,
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
    *,
    watchlist_score_threshold: float,
) -> float:
    if ticker in merge_approved_tickers and threshold_relaxation > 0:
        return max(0.0, watchlist_score_threshold - threshold_relaxation)
    return watchlist_score_threshold


def _merge_approved_candidate_reason_codes(item: LayerCResult) -> list[str]:
    candidate_reason_codes = [str(code) for code in list(item.candidate_reason_codes or []) if str(code or "").strip()]
    if "merge_approved_continuation" not in candidate_reason_codes:
        candidate_reason_codes.append("merge_approved_continuation")
    return candidate_reason_codes


def _build_merge_approved_layer_c_tag_update(item: LayerCResult) -> dict[str, Any]:
    return {
        "candidate_source": "layer_c_watchlist_merge_approved",
        "candidate_reason_codes": _merge_approved_candidate_reason_codes(item),
    }


def _dedupe_reason_codes(reason_codes: list[str]) -> list[str]:
    deduped_reason_codes: list[str] = []
    for code in reason_codes:
        if code not in deduped_reason_codes:
            deduped_reason_codes.append(code)
    return deduped_reason_codes


def _should_release_watchlist_shadow_candidate(
    *,
    item: LayerCResult,
    primary_reason: str,
    config: WatchlistDiagnosticsConfig,
) -> tuple[bool, str | None]:
    if primary_reason != "decision_avoid":
        return False, None
    if str(item.decision or "") != "avoid":
        return False, None
    if str(item.bc_conflict or "") not in config.shadow_release_conflicts:
        return False, None
    if float(item.score_b) < config.shadow_release_score_b_min:
        return False, None
    if float(item.score_final) < config.shadow_release_score_final_min:
        return False, None
    if float(item.score_c) < config.shadow_release_score_c_min:
        return False, None
    return True, "watchlist_avoid_shadow_release_boundary_pass"


def _build_watchlist_shadow_release_entry(
    *,
    item: LayerCResult,
    reasons: list[str],
    release_reason: str,
    config: WatchlistDiagnosticsConfig,
) -> dict[str, Any]:
    deduped_reason_codes = _build_watchlist_shadow_release_reason_codes(
        reasons=reasons,
        release_reason=release_reason,
    )
    return {
        "ticker": item.ticker,
        **_build_watchlist_shadow_release_payload(
            item=item,
            reason_codes=deduped_reason_codes,
            release_reason=release_reason,
            config=config,
        ),
    }


def _build_watchlist_shadow_release_reason_codes(*, reasons: list[str], release_reason: str) -> list[str]:
    resolved_reason_codes = [
        "watchlist_avoid_shadow_release",
        release_reason,
        *[str(reason) for reason in list(reasons or []) if str(reason or "").strip()],
    ]
    return _dedupe_reason_codes(resolved_reason_codes)


def _build_watchlist_shadow_release_thresholds(config: WatchlistDiagnosticsConfig) -> dict[str, float]:
    return {
        "score_b_min": round(config.shadow_release_score_b_min, 4),
        "score_final_min": round(config.shadow_release_score_final_min, 4),
        "score_c_min": round(config.shadow_release_score_c_min, 4),
    }


def _build_watchlist_shadow_release_score_fields(item: LayerCResult) -> dict[str, float]:
    return {
        "score_b": round(float(item.score_b), 4),
        "score_c": round(float(item.score_c), 4),
        "score_final": round(float(item.score_final), 4),
        "quality_score": round(float(item.quality_score), 4),
    }


def _build_watchlist_shadow_release_strategy_signals(item: LayerCResult) -> dict[str, Any]:
    return {
        name: signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {})
        for name, signal in dict(item.strategy_signals or {}).items()
    }


def _build_watchlist_shadow_release_agent_summary(item: LayerCResult) -> dict[str, Any]:
    return dict(item.agent_contribution_summary or {})


def _watchlist_shadow_release_promotion_trigger() -> str:
    return "主 watchlist veto 保持不变；仅把边界 avoid 样本送入 short-trade supplemental replay，验证是否属于 000960 式 false negative。"


def _build_watchlist_shadow_release_reason_fields(*, reason_codes: list[str], release_reason: str) -> dict[str, Any]:
    return {
        "reason": "watchlist_avoid_shadow_release",
        "reasons": reason_codes,
        "candidate_source": "watchlist_avoid_shadow_release",
        "candidate_reason_codes": reason_codes,
        "shadow_release_reason": release_reason,
    }


def _build_watchlist_shadow_release_metadata_fields(item: LayerCResult, config: WatchlistDiagnosticsConfig) -> dict[str, Any]:
    return {
        "shadow_release_thresholds": _build_watchlist_shadow_release_thresholds(config),
        "strategy_signals": _build_watchlist_shadow_release_strategy_signals(item),
        "agent_contribution_summary": _build_watchlist_shadow_release_agent_summary(item),
        "promotion_trigger": _watchlist_shadow_release_promotion_trigger(),
    }


def _build_watchlist_shadow_release_source_fields(item: LayerCResult) -> dict[str, Any]:
    return {
        "decision": str(item.decision or "avoid"),
        "bc_conflict": None,
        "source_decision": str(item.decision or ""),
        "source_bc_conflict": item.bc_conflict,
    }


def _build_watchlist_shadow_release_core_fields(
    *,
    item: LayerCResult,
    reason_codes: list[str],
    release_reason: str,
) -> dict[str, Any]:
    core_fields = _build_watchlist_shadow_release_source_fields(item)
    core_fields.update(
        _build_watchlist_shadow_release_reason_fields(
            reason_codes=reason_codes,
            release_reason=release_reason,
        )
    )
    return core_fields


def _build_watchlist_shadow_release_payload(
    *,
    item: LayerCResult,
    reason_codes: list[str],
    release_reason: str,
    config: WatchlistDiagnosticsConfig,
) -> dict[str, Any]:
    payload = _build_watchlist_shadow_release_score_fields(item)
    payload.update(
        _build_watchlist_shadow_release_core_fields(
            item=item,
            reason_codes=reason_codes,
            release_reason=release_reason,
        )
    )
    payload.update(_build_watchlist_shadow_release_metadata_fields(item, config))
    return payload
