from __future__ import annotations

from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from src.screening.models import CandidateStock


def _prepare_shadow_selection_context(
    *,
    candidates: list["CandidateStock"],
    pool_size: int,
    cooldown_review_candidates: list["CandidateStock"] | None,
    candidate_liquidity_sort_key_fn: Callable[["CandidateStock"], tuple[int, float, float, str]],
    build_cooldown_review_shadow_payload_fn: Callable[..., tuple[list["CandidateStock"], list[dict[str, Any]]]],
    resolve_cooldown_shadow_review_tickers_fn: Callable[[], set[str]],
    shadow_visibility_gap_tickers: set[str],
    min_avg_amount_20d: float,
) -> tuple[
    list["CandidateStock"],
    list["CandidateStock"],
    float,
    float,
    list["CandidateStock"],
    list[dict[str, Any]],
]:
    ranked_candidates = sorted(candidates, key=candidate_liquidity_sort_key_fn, reverse=True)
    selected_candidates = [
        candidate.model_copy(update={"candidate_pool_rank": rank})
        for rank, candidate in enumerate(ranked_candidates[:pool_size], start=1)
    ]
    resolved_cooldown_review_candidates = list(cooldown_review_candidates or [])
    cutoff_avg_volume = round(float(ranked_candidates[-1].avg_volume_20d), 4) if ranked_candidates else 0.0
    cutoff_reference = max(float(selected_candidates[-1].avg_volume_20d), 1.0) if selected_candidates else 1.0

    shadow_candidates: list[CandidateStock] = []
    shadow_entries: list[dict[str, Any]] = []
    if resolved_cooldown_review_candidates:
        cooldown_shadow_candidates, cooldown_shadow_entries = build_cooldown_review_shadow_payload_fn(
            candidates=resolved_cooldown_review_candidates,
            cutoff_reference=cutoff_reference,
            min_avg_amount_20d=min_avg_amount_20d,
            review_focus_tickers=resolve_cooldown_shadow_review_tickers_fn(),
            visibility_gap_tickers=shadow_visibility_gap_tickers,
        )
        shadow_candidates.extend(cooldown_shadow_candidates)
        shadow_entries.extend(cooldown_shadow_entries)

    return (
        ranked_candidates,
        selected_candidates,
        cutoff_avg_volume,
        cutoff_reference,
        shadow_candidates,
        shadow_entries,
    )


def _classify_shadow_overflow_candidates(
    *,
    ranked_candidates: list["CandidateStock"],
    pool_size: int,
    min_avg_amount_20d: float,
    resolve_shadow_focus_tickers_fn: Callable[..., set[str]],
    resolve_shadow_visibility_gap_tickers_fn: Callable[..., set[str]],
    classify_overflow_candidate_fn: Callable[..., tuple[str, tuple[float, int, "CandidateStock", bool, bool]] | None],
    shadow_liquidity_corridor_min_gate_share: float,
    shadow_liquidity_corridor_max_cutoff_share: float,
    shadow_liquidity_corridor_focus_min_gate_share: float,
    shadow_liquidity_corridor_focus_max_cutoff_share: float,
    shadow_liquidity_corridor_focus_low_gate_max_cutoff_share: float,
    shadow_liquidity_corridor_visibility_gap_max_cutoff_share: float,
    shadow_rebucket_min_gate_share: float,
    shadow_rebucket_min_cutoff_share: float,
    shadow_rebucket_max_cutoff_share: float,
    shadow_rebucket_focus_min_cutoff_share: float,
    shadow_rebucket_visibility_gap_min_cutoff_share: float,
) -> tuple[
    list["CandidateStock"],
    float,
    list[tuple[float, int, "CandidateStock", bool, bool]],
    list[tuple[float, int, "CandidateStock", bool, bool]],
]:
    cutoff_avg_volume = max(float(ranked_candidates[pool_size - 1].avg_volume_20d), 1.0)
    overflow_candidates = ranked_candidates[pool_size:]
    corridor_candidates: list[tuple[float, int, CandidateStock, bool, bool]] = []
    rebucket_candidates: list[tuple[float, int, CandidateStock, bool, bool]] = []
    corridor_focus_tickers = resolve_shadow_focus_tickers_fn(lane="layer_a_liquidity_corridor")
    rebucket_focus_tickers = resolve_shadow_focus_tickers_fn(lane="post_gate_liquidity_competition")
    corridor_visibility_gap_tickers = resolve_shadow_visibility_gap_tickers_fn(lane="layer_a_liquidity_corridor")
    rebucket_visibility_gap_tickers = resolve_shadow_visibility_gap_tickers_fn(lane="post_gate_liquidity_competition")

    for rank, candidate in enumerate(overflow_candidates, start=pool_size + 1):
        cutoff_share = round(float(candidate.avg_volume_20d) / cutoff_avg_volume, 4)
        min_gate_share = round(float(candidate.avg_volume_20d) / float(min_avg_amount_20d), 4)
        classified_row = classify_overflow_candidate_fn(
            candidate=candidate,
            rank=rank,
            cutoff_share=cutoff_share,
            min_gate_share=min_gate_share,
            corridor_focus_tickers=corridor_focus_tickers,
            rebucket_focus_tickers=rebucket_focus_tickers,
            corridor_visibility_gap_tickers=corridor_visibility_gap_tickers,
            rebucket_visibility_gap_tickers=rebucket_visibility_gap_tickers,
            corridor_min_gate_share=shadow_liquidity_corridor_min_gate_share,
            corridor_max_cutoff_share=shadow_liquidity_corridor_max_cutoff_share,
            corridor_focus_min_gate_share=shadow_liquidity_corridor_focus_min_gate_share,
            corridor_focus_max_cutoff_share=shadow_liquidity_corridor_focus_max_cutoff_share,
            corridor_focus_low_gate_max_cutoff_share=shadow_liquidity_corridor_focus_low_gate_max_cutoff_share,
            corridor_visibility_gap_max_cutoff_share=shadow_liquidity_corridor_visibility_gap_max_cutoff_share,
            rebucket_min_gate_share=shadow_rebucket_min_gate_share,
            rebucket_min_cutoff_share=shadow_rebucket_min_cutoff_share,
            rebucket_max_cutoff_share=shadow_rebucket_max_cutoff_share,
            rebucket_focus_min_cutoff_share=shadow_rebucket_focus_min_cutoff_share,
            rebucket_visibility_gap_min_cutoff_share=shadow_rebucket_visibility_gap_min_cutoff_share,
        )
        if classified_row is None:
            continue
        lane, row = classified_row
        if lane == "layer_a_liquidity_corridor":
            corridor_candidates.append(row)
        else:
            rebucket_candidates.append(row)

    return overflow_candidates, cutoff_avg_volume, corridor_candidates, rebucket_candidates


def _build_shadow_lane_payloads(
    *,
    corridor_candidates: list[tuple[float, int, "CandidateStock", bool, bool]],
    rebucket_candidates: list[tuple[float, int, "CandidateStock", bool, bool]],
    cutoff_avg_volume: float,
    min_avg_amount_20d: float,
    candidate_liquidity_sort_key_fn: Callable[["CandidateStock"], tuple[int, float, float, str]],
    resolve_shadow_focus_tickers_fn: Callable[..., set[str]],
    resolve_shadow_visibility_gap_tickers_fn: Callable[..., set[str]],
    select_shadow_rows_fn: Callable[..., list[tuple[float, int, "CandidateStock", bool, bool]]],
    build_shadow_lane_payload_fn: Callable[..., tuple[list["CandidateStock"], list[dict[str, Any]]]],
    shadow_liquidity_corridor_max_tickers: int,
    shadow_rebucket_max_tickers: int,
) -> tuple[list["CandidateStock"], list[dict[str, Any]]]:
    shadow_candidates: list[CandidateStock] = []
    shadow_entries: list[dict[str, Any]] = []
    for rows, max_tickers, lane, reason, rank_key in [
        (
            corridor_candidates,
            shadow_liquidity_corridor_max_tickers,
            "layer_a_liquidity_corridor",
            "upstream_base_liquidity_uplift_shadow",
            "gate_share_score",
        ),
        (
            rebucket_candidates,
            shadow_rebucket_max_tickers,
            "post_gate_liquidity_competition",
            "post_gate_liquidity_competition_shadow",
            "cutoff_share_score",
        ),
    ]:
        focus_tickers = resolve_shadow_focus_tickers_fn(lane=lane)
        visibility_gap_tickers = resolve_shadow_visibility_gap_tickers_fn(lane=lane)
        selected_rows = select_shadow_rows_fn(
            rows=rows,
            max_tickers=max_tickers,
            focus_tickers=focus_tickers,
            visibility_gap_tickers=visibility_gap_tickers,
            liquidity_sort_key=candidate_liquidity_sort_key_fn,
        )
        lane_shadow_candidates, lane_shadow_entries = build_shadow_lane_payload_fn(
            selected_rows=selected_rows,
            cutoff_reference=cutoff_avg_volume,
            min_avg_amount_20d=min_avg_amount_20d,
            lane=lane,
            reason=reason,
            rank_key=rank_key,
            focus_tickers=focus_tickers,
            visibility_gap_tickers=visibility_gap_tickers,
        )
        shadow_candidates.extend(lane_shadow_candidates)
        shadow_entries.extend(lane_shadow_entries)
    return shadow_candidates, shadow_entries


def _build_shadow_candidate_pool_summary(
    *,
    pool_size: int,
    selected_candidates: list["CandidateStock"],
    overflow_count: int,
    selected_cutoff_avg_volume_20d: float,
    shadow_candidates: list["CandidateStock"],
    shadow_entries: list[dict[str, Any]],
    shadow_focus_signature_fn: Callable[[], str],
    focus_filter_diagnostics: list[dict[str, Any]] | None,
    build_shadow_summary_payload_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return build_shadow_summary_payload_fn(
        pool_size=pool_size,
        selected_count=len(selected_candidates),
        overflow_count=overflow_count,
        selected_cutoff_avg_volume_20d=round(selected_cutoff_avg_volume_20d, 4),
        shadow_candidates=shadow_candidates,
        shadow_entries=shadow_entries,
        focus_signature=shadow_focus_signature_fn(),
        focus_filter_diagnostics=focus_filter_diagnostics,
    )


def _resolve_shadow_overflow_payload(
    *,
    ranked_candidates: list["CandidateStock"],
    pool_size: int,
    min_avg_amount_20d: float,
    candidate_liquidity_sort_key_fn: Callable[["CandidateStock"], tuple[int, float, float, str]],
    resolve_shadow_focus_tickers_fn: Callable[..., set[str]],
    resolve_shadow_visibility_gap_tickers_fn: Callable[..., set[str]],
    classify_overflow_candidate_fn: Callable[..., tuple[str, tuple[float, int, "CandidateStock", bool, bool]] | None],
    select_shadow_rows_fn: Callable[..., list[tuple[float, int, "CandidateStock", bool, bool]]],
    build_shadow_lane_payload_fn: Callable[..., tuple[list["CandidateStock"], list[dict[str, Any]]]],
    shadow_liquidity_corridor_min_gate_share: float,
    shadow_liquidity_corridor_max_cutoff_share: float,
    shadow_liquidity_corridor_focus_min_gate_share: float,
    shadow_liquidity_corridor_focus_max_cutoff_share: float,
    shadow_liquidity_corridor_focus_low_gate_max_cutoff_share: float,
    shadow_liquidity_corridor_visibility_gap_max_cutoff_share: float,
    shadow_rebucket_min_gate_share: float,
    shadow_rebucket_min_cutoff_share: float,
    shadow_rebucket_max_cutoff_share: float,
    shadow_rebucket_focus_min_cutoff_share: float,
    shadow_rebucket_visibility_gap_min_cutoff_share: float,
    shadow_liquidity_corridor_max_tickers: int,
    shadow_rebucket_max_tickers: int,
) -> tuple[list["CandidateStock"], list[dict[str, Any]], int, float]:
    overflow_candidates, cutoff_avg_volume, corridor_candidates, rebucket_candidates = _classify_shadow_overflow_candidates(
        ranked_candidates=ranked_candidates,
        pool_size=pool_size,
        min_avg_amount_20d=min_avg_amount_20d,
        resolve_shadow_focus_tickers_fn=resolve_shadow_focus_tickers_fn,
        resolve_shadow_visibility_gap_tickers_fn=resolve_shadow_visibility_gap_tickers_fn,
        classify_overflow_candidate_fn=classify_overflow_candidate_fn,
        shadow_liquidity_corridor_min_gate_share=shadow_liquidity_corridor_min_gate_share,
        shadow_liquidity_corridor_max_cutoff_share=shadow_liquidity_corridor_max_cutoff_share,
        shadow_liquidity_corridor_focus_min_gate_share=shadow_liquidity_corridor_focus_min_gate_share,
        shadow_liquidity_corridor_focus_max_cutoff_share=shadow_liquidity_corridor_focus_max_cutoff_share,
        shadow_liquidity_corridor_focus_low_gate_max_cutoff_share=shadow_liquidity_corridor_focus_low_gate_max_cutoff_share,
        shadow_liquidity_corridor_visibility_gap_max_cutoff_share=shadow_liquidity_corridor_visibility_gap_max_cutoff_share,
        shadow_rebucket_min_gate_share=shadow_rebucket_min_gate_share,
        shadow_rebucket_min_cutoff_share=shadow_rebucket_min_cutoff_share,
        shadow_rebucket_max_cutoff_share=shadow_rebucket_max_cutoff_share,
        shadow_rebucket_focus_min_cutoff_share=shadow_rebucket_focus_min_cutoff_share,
        shadow_rebucket_visibility_gap_min_cutoff_share=shadow_rebucket_visibility_gap_min_cutoff_share,
    )
    shadow_candidates, shadow_entries = _build_shadow_lane_payloads(
        corridor_candidates=corridor_candidates,
        rebucket_candidates=rebucket_candidates,
        cutoff_avg_volume=cutoff_avg_volume,
        min_avg_amount_20d=min_avg_amount_20d,
        candidate_liquidity_sort_key_fn=candidate_liquidity_sort_key_fn,
        resolve_shadow_focus_tickers_fn=resolve_shadow_focus_tickers_fn,
        resolve_shadow_visibility_gap_tickers_fn=resolve_shadow_visibility_gap_tickers_fn,
        select_shadow_rows_fn=select_shadow_rows_fn,
        build_shadow_lane_payload_fn=build_shadow_lane_payload_fn,
        shadow_liquidity_corridor_max_tickers=shadow_liquidity_corridor_max_tickers,
        shadow_rebucket_max_tickers=shadow_rebucket_max_tickers,
    )
    return shadow_candidates, shadow_entries, len(overflow_candidates), cutoff_avg_volume


def _build_shadow_candidate_pool_payload_impl(
    candidates: list["CandidateStock"],
    *,
    pool_size: int,
    cooldown_review_candidates: list["CandidateStock"] | None,
    focus_filter_diagnostics: list[dict[str, Any]] | None,
    candidate_liquidity_sort_key_fn: Callable[["CandidateStock"], tuple[int, float, float, str]],
    build_cooldown_review_shadow_payload_fn: Callable[..., tuple[list["CandidateStock"], list[dict[str, Any]]]],
    build_shadow_summary_payload_fn: Callable[..., dict[str, Any]],
    shadow_focus_signature_fn: Callable[[], str],
    resolve_cooldown_shadow_review_tickers_fn: Callable[[], set[str]],
    resolve_shadow_focus_tickers_fn: Callable[..., set[str]],
    resolve_shadow_visibility_gap_tickers_fn: Callable[..., set[str]],
    classify_overflow_candidate_fn: Callable[..., tuple[str, tuple[float, int, "CandidateStock", bool, bool]] | None],
    select_shadow_rows_fn: Callable[..., list[tuple[float, int, "CandidateStock", bool, bool]]],
    build_shadow_lane_payload_fn: Callable[..., tuple[list["CandidateStock"], list[dict[str, Any]]]],
    min_avg_amount_20d: float,
    shadow_visibility_gap_tickers: set[str],
    shadow_liquidity_corridor_min_gate_share: float,
    shadow_liquidity_corridor_max_cutoff_share: float,
    shadow_liquidity_corridor_focus_min_gate_share: float,
    shadow_liquidity_corridor_focus_max_cutoff_share: float,
    shadow_liquidity_corridor_focus_low_gate_max_cutoff_share: float,
    shadow_liquidity_corridor_visibility_gap_max_cutoff_share: float,
    shadow_rebucket_min_gate_share: float,
    shadow_rebucket_min_cutoff_share: float,
    shadow_rebucket_max_cutoff_share: float,
    shadow_rebucket_focus_min_cutoff_share: float,
    shadow_rebucket_visibility_gap_min_cutoff_share: float,
    shadow_liquidity_corridor_max_tickers: int,
    shadow_rebucket_max_tickers: int,
) -> tuple[list["CandidateStock"], list["CandidateStock"], dict[str, Any]]:
    (
        ranked_candidates,
        selected_candidates,
        cutoff_avg_volume,
        _cutoff_reference,
        shadow_candidates,
        shadow_entries,
    ) = _prepare_shadow_selection_context(
        candidates=candidates,
        pool_size=pool_size,
        cooldown_review_candidates=cooldown_review_candidates,
        candidate_liquidity_sort_key_fn=candidate_liquidity_sort_key_fn,
        build_cooldown_review_shadow_payload_fn=build_cooldown_review_shadow_payload_fn,
        resolve_cooldown_shadow_review_tickers_fn=resolve_cooldown_shadow_review_tickers_fn,
        shadow_visibility_gap_tickers=shadow_visibility_gap_tickers,
        min_avg_amount_20d=min_avg_amount_20d,
    )

    if len(ranked_candidates) <= pool_size:
        return selected_candidates, shadow_candidates, _build_shadow_candidate_pool_summary(
            pool_size=pool_size,
            selected_candidates=selected_candidates,
            overflow_count=0,
            selected_cutoff_avg_volume_20d=cutoff_avg_volume,
            shadow_candidates=shadow_candidates,
            shadow_entries=shadow_entries,
            shadow_focus_signature_fn=shadow_focus_signature_fn,
            focus_filter_diagnostics=focus_filter_diagnostics,
            build_shadow_summary_payload_fn=build_shadow_summary_payload_fn,
        )

    lane_shadow_candidates, lane_shadow_entries, overflow_count, cutoff_avg_volume = _resolve_shadow_overflow_payload(
        ranked_candidates=ranked_candidates,
        pool_size=pool_size,
        min_avg_amount_20d=min_avg_amount_20d,
        candidate_liquidity_sort_key_fn=candidate_liquidity_sort_key_fn,
        resolve_shadow_focus_tickers_fn=resolve_shadow_focus_tickers_fn,
        resolve_shadow_visibility_gap_tickers_fn=resolve_shadow_visibility_gap_tickers_fn,
        classify_overflow_candidate_fn=classify_overflow_candidate_fn,
        select_shadow_rows_fn=select_shadow_rows_fn,
        build_shadow_lane_payload_fn=build_shadow_lane_payload_fn,
        shadow_liquidity_corridor_min_gate_share=shadow_liquidity_corridor_min_gate_share,
        shadow_liquidity_corridor_max_cutoff_share=shadow_liquidity_corridor_max_cutoff_share,
        shadow_liquidity_corridor_focus_min_gate_share=shadow_liquidity_corridor_focus_min_gate_share,
        shadow_liquidity_corridor_focus_max_cutoff_share=shadow_liquidity_corridor_focus_max_cutoff_share,
        shadow_liquidity_corridor_focus_low_gate_max_cutoff_share=shadow_liquidity_corridor_focus_low_gate_max_cutoff_share,
        shadow_liquidity_corridor_visibility_gap_max_cutoff_share=shadow_liquidity_corridor_visibility_gap_max_cutoff_share,
        shadow_rebucket_min_gate_share=shadow_rebucket_min_gate_share,
        shadow_rebucket_min_cutoff_share=shadow_rebucket_min_cutoff_share,
        shadow_rebucket_max_cutoff_share=shadow_rebucket_max_cutoff_share,
        shadow_rebucket_focus_min_cutoff_share=shadow_rebucket_focus_min_cutoff_share,
        shadow_rebucket_visibility_gap_min_cutoff_share=shadow_rebucket_visibility_gap_min_cutoff_share,
        shadow_liquidity_corridor_max_tickers=shadow_liquidity_corridor_max_tickers,
        shadow_rebucket_max_tickers=shadow_rebucket_max_tickers,
    )
    shadow_candidates.extend(lane_shadow_candidates)
    shadow_entries.extend(lane_shadow_entries)

    return selected_candidates, shadow_candidates, _build_shadow_candidate_pool_summary(
        pool_size=pool_size,
        selected_candidates=selected_candidates,
        overflow_count=overflow_count,
        selected_cutoff_avg_volume_20d=cutoff_avg_volume,
        shadow_candidates=shadow_candidates,
        shadow_entries=shadow_entries,
        shadow_focus_signature_fn=shadow_focus_signature_fn,
        focus_filter_diagnostics=focus_filter_diagnostics,
        build_shadow_summary_payload_fn=build_shadow_summary_payload_fn,
    )


def build_shadow_candidate_pool_payload(
    candidates: list["CandidateStock"],
    *,
    pool_size: int,
    cooldown_review_candidates: list["CandidateStock"] | None = None,
    focus_filter_diagnostics: list[dict[str, Any]] | None = None,
    candidate_liquidity_sort_key_fn: Callable[["CandidateStock"], tuple[int, float, float, str]],
    build_cooldown_review_shadow_payload_fn: Callable[..., tuple[list["CandidateStock"], list[dict[str, Any]]]],
    build_shadow_summary_payload_fn: Callable[..., dict[str, Any]],
    shadow_focus_signature_fn: Callable[[], str],
    resolve_cooldown_shadow_review_tickers_fn: Callable[[], set[str]],
    resolve_shadow_focus_tickers_fn: Callable[..., set[str]],
    resolve_shadow_visibility_gap_tickers_fn: Callable[..., set[str]],
    classify_overflow_candidate_fn: Callable[..., tuple[str, tuple[float, int, "CandidateStock", bool, bool]] | None],
    select_shadow_rows_fn: Callable[..., list[tuple[float, int, "CandidateStock", bool, bool]]],
    build_shadow_lane_payload_fn: Callable[..., tuple[list["CandidateStock"], list[dict[str, Any]]]],
    min_avg_amount_20d: float,
    shadow_visibility_gap_tickers: set[str],
    shadow_liquidity_corridor_min_gate_share: float,
    shadow_liquidity_corridor_max_cutoff_share: float,
    shadow_liquidity_corridor_focus_min_gate_share: float,
    shadow_liquidity_corridor_focus_max_cutoff_share: float,
    shadow_liquidity_corridor_focus_low_gate_max_cutoff_share: float,
    shadow_liquidity_corridor_visibility_gap_max_cutoff_share: float,
    shadow_rebucket_min_gate_share: float,
    shadow_rebucket_min_cutoff_share: float,
    shadow_rebucket_max_cutoff_share: float,
    shadow_rebucket_focus_min_cutoff_share: float,
    shadow_rebucket_visibility_gap_min_cutoff_share: float,
    shadow_liquidity_corridor_max_tickers: int,
    shadow_rebucket_max_tickers: int,
) -> tuple[list["CandidateStock"], list["CandidateStock"], dict[str, Any]]:
    return _build_shadow_candidate_pool_payload_impl(
        candidates=candidates,
        pool_size=pool_size,
        cooldown_review_candidates=cooldown_review_candidates,
        focus_filter_diagnostics=focus_filter_diagnostics,
        candidate_liquidity_sort_key_fn=candidate_liquidity_sort_key_fn,
        build_cooldown_review_shadow_payload_fn=build_cooldown_review_shadow_payload_fn,
        build_shadow_summary_payload_fn=build_shadow_summary_payload_fn,
        shadow_focus_signature_fn=shadow_focus_signature_fn,
        resolve_cooldown_shadow_review_tickers_fn=resolve_cooldown_shadow_review_tickers_fn,
        resolve_shadow_focus_tickers_fn=resolve_shadow_focus_tickers_fn,
        resolve_shadow_visibility_gap_tickers_fn=resolve_shadow_visibility_gap_tickers_fn,
        classify_overflow_candidate_fn=classify_overflow_candidate_fn,
        select_shadow_rows_fn=select_shadow_rows_fn,
        build_shadow_lane_payload_fn=build_shadow_lane_payload_fn,
        shadow_visibility_gap_tickers=shadow_visibility_gap_tickers,
        min_avg_amount_20d=min_avg_amount_20d,
        shadow_liquidity_corridor_min_gate_share=shadow_liquidity_corridor_min_gate_share,
        shadow_liquidity_corridor_max_cutoff_share=shadow_liquidity_corridor_max_cutoff_share,
        shadow_liquidity_corridor_focus_min_gate_share=shadow_liquidity_corridor_focus_min_gate_share,
        shadow_liquidity_corridor_focus_max_cutoff_share=shadow_liquidity_corridor_focus_max_cutoff_share,
        shadow_liquidity_corridor_focus_low_gate_max_cutoff_share=shadow_liquidity_corridor_focus_low_gate_max_cutoff_share,
        shadow_liquidity_corridor_visibility_gap_max_cutoff_share=shadow_liquidity_corridor_visibility_gap_max_cutoff_share,
        shadow_rebucket_min_gate_share=shadow_rebucket_min_gate_share,
        shadow_rebucket_min_cutoff_share=shadow_rebucket_min_cutoff_share,
        shadow_rebucket_max_cutoff_share=shadow_rebucket_max_cutoff_share,
        shadow_rebucket_focus_min_cutoff_share=shadow_rebucket_focus_min_cutoff_share,
        shadow_rebucket_visibility_gap_min_cutoff_share=shadow_rebucket_visibility_gap_min_cutoff_share,
        shadow_liquidity_corridor_max_tickers=shadow_liquidity_corridor_max_tickers,
        shadow_rebucket_max_tickers=shadow_rebucket_max_tickers,
    )
