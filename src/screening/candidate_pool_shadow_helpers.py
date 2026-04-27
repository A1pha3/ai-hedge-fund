from __future__ import annotations

from typing import Any
from collections.abc import Callable

from src.screening.models import CandidateStock

ShadowRankRow = tuple[float, int, CandidateStock, bool, bool]


def compute_shadow_share_metrics(*, avg_volume_20d: float, cutoff_reference: float, min_avg_amount_20d: float) -> tuple[float, float]:
    if avg_volume_20d <= 0:
        return 0.0, 0.0
    return (
        round(float(avg_volume_20d) / cutoff_reference, 4),
        round(float(avg_volume_20d) / float(min_avg_amount_20d), 4),
    )


def build_cooldown_review_shadow_payload(
    *,
    candidates: list[CandidateStock],
    cutoff_reference: float,
    min_avg_amount_20d: float,
    review_focus_tickers: set[str],
    visibility_gap_tickers: set[str],
) -> tuple[list[CandidateStock], list[dict[str, Any]]]:
    shadow_candidates: list[CandidateStock] = []
    shadow_entries: list[dict[str, Any]] = []
    for candidate in candidates:
        cutoff_share, min_gate_share = compute_shadow_share_metrics(
            avg_volume_20d=float(candidate.avg_volume_20d),
            cutoff_reference=cutoff_reference,
            min_avg_amount_20d=min_avg_amount_20d,
        )
        shadow_candidate = candidate.model_copy(
            update={
                "candidate_pool_rank": 0,
                "candidate_pool_lane": "cooldown_review",
                "candidate_pool_shadow_reason": "cooldown_review_shadow",
                "candidate_pool_avg_amount_share_of_cutoff": cutoff_share,
                "candidate_pool_avg_amount_share_of_min_gate": min_gate_share,
                "shadow_visibility_gap_selected": candidate.ticker in visibility_gap_tickers,
                "shadow_visibility_gap_relaxed_band": False,
            }
        )
        shadow_candidates.append(shadow_candidate)
        shadow_entries.append(
            {
                "ticker": shadow_candidate.ticker,
                "candidate_pool_rank": 0,
                "candidate_pool_lane": "cooldown_review",
                "candidate_pool_shadow_reason": "cooldown_review_shadow",
                "avg_volume_20d": round(float(shadow_candidate.avg_volume_20d), 4),
                "market_cap": round(float(shadow_candidate.market_cap), 4),
                "avg_amount_share_of_cutoff": cutoff_share,
                "avg_amount_share_of_min_gate": min_gate_share,
                "shadow_focus_selected": shadow_candidate.ticker in review_focus_tickers,
                "shadow_focus_relaxed_band": False,
                "shadow_visibility_gap_selected": shadow_candidate.ticker in visibility_gap_tickers,
                "shadow_visibility_gap_relaxed_band": False,
                "cooldown_review": True,
            }
        )
    return shadow_candidates, shadow_entries


def select_shadow_rows(
    *,
    rows: list[ShadowRankRow],
    max_tickers: int,
    focus_tickers: set[str],
    visibility_gap_tickers: set[str],
    liquidity_sort_key: Callable[[CandidateStock], tuple[int, float, float, str]],
) -> list[ShadowRankRow]:
    ranked_rows = sorted(
        rows,
        key=lambda item: (0 if item[4] else 1, 0 if item[3] else 1, item[0], -item[1], liquidity_sort_key(item[2])),
        reverse=True,
    )
    selected_rows: list[ShadowRankRow] = []
    selected_tickers: set[str] = set()

    for prioritized_tickers in (visibility_gap_tickers, focus_tickers, None):
        for row in ranked_rows:
            _, _, candidate, _, _ = row
            if candidate.ticker in selected_tickers:
                continue
            if prioritized_tickers is not None and candidate.ticker not in prioritized_tickers:
                continue
            selected_rows.append(row)
            selected_tickers.add(candidate.ticker)
            if len(selected_rows) >= max_tickers:
                return selected_rows
    return selected_rows


def build_shadow_lane_payload(
    *,
    selected_rows: list[ShadowRankRow],
    cutoff_reference: float,
    min_avg_amount_20d: float,
    lane: str,
    reason: str,
    rank_key: str,
    focus_tickers: set[str],
    visibility_gap_tickers: set[str],
) -> tuple[list[CandidateStock], list[dict[str, Any]]]:
    shadow_candidates: list[CandidateStock] = []
    shadow_entries: list[dict[str, Any]] = []
    for score, rank, candidate, focus_relaxed_band, visibility_gap_relaxed_band in selected_rows:
        cutoff_share, min_gate_share = compute_shadow_share_metrics(
            avg_volume_20d=float(candidate.avg_volume_20d),
            cutoff_reference=cutoff_reference,
            min_avg_amount_20d=min_avg_amount_20d,
        )
        resolved_reason = reason
        if visibility_gap_relaxed_band:
            resolved_reason = f"{reason}_visibility_gap_relaxed_band"
        elif focus_relaxed_band:
            resolved_reason = f"{reason}_focus_relaxed_band"
        shadow_candidate = candidate.model_copy(
            update={
                "candidate_pool_rank": rank,
                "candidate_pool_lane": lane,
                "candidate_pool_shadow_reason": resolved_reason,
                "candidate_pool_avg_amount_share_of_cutoff": cutoff_share,
                "candidate_pool_avg_amount_share_of_min_gate": min_gate_share,
                "shadow_visibility_gap_selected": candidate.ticker in visibility_gap_tickers,
                "shadow_visibility_gap_relaxed_band": visibility_gap_relaxed_band,
            }
        )
        shadow_candidates.append(shadow_candidate)
        shadow_entries.append(
            {
                "ticker": shadow_candidate.ticker,
                "candidate_pool_rank": rank,
                "candidate_pool_lane": lane,
                "candidate_pool_shadow_reason": resolved_reason,
                "avg_volume_20d": round(float(shadow_candidate.avg_volume_20d), 4),
                "market_cap": round(float(shadow_candidate.market_cap), 4),
                "avg_amount_share_of_cutoff": cutoff_share,
                "avg_amount_share_of_min_gate": min_gate_share,
                "shadow_focus_selected": shadow_candidate.ticker in focus_tickers,
                "shadow_focus_relaxed_band": focus_relaxed_band,
                "shadow_visibility_gap_selected": shadow_candidate.ticker in visibility_gap_tickers,
                "shadow_visibility_gap_relaxed_band": visibility_gap_relaxed_band,
                rank_key: round(float(score), 4),
            }
        )
    return shadow_candidates, shadow_entries


def count_shadow_lanes(shadow_entries: list[dict[str, Any]]) -> dict[str, int]:
    lane_counts: dict[str, int] = {}
    for entry in shadow_entries:
        lane = str(entry.get("candidate_pool_lane") or "unknown")
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
    return lane_counts


def classify_overflow_candidate(
    *,
    candidate: CandidateStock,
    rank: int,
    cutoff_share: float,
    min_gate_share: float,
    corridor_focus_tickers: set[str],
    rebucket_focus_tickers: set[str],
    corridor_visibility_gap_tickers: set[str],
    rebucket_visibility_gap_tickers: set[str],
    corridor_min_gate_share: float,
    corridor_max_cutoff_share: float,
    corridor_focus_min_gate_share: float,
    corridor_focus_max_cutoff_share: float,
    corridor_focus_low_gate_max_cutoff_share: float,
    corridor_visibility_gap_max_cutoff_share: float,
    rebucket_min_gate_share: float,
    rebucket_min_cutoff_share: float,
    rebucket_max_cutoff_share: float,
    rebucket_focus_min_cutoff_share: float,
    rebucket_visibility_gap_min_cutoff_share: float,
) -> tuple[str, ShadowRankRow] | None:
    annotated_candidate = candidate.model_copy(
        update={
            "candidate_pool_avg_amount_share_of_cutoff": cutoff_share,
            "candidate_pool_avg_amount_share_of_min_gate": min_gate_share,
        }
    )
    if min_gate_share >= corridor_min_gate_share and cutoff_share <= corridor_max_cutoff_share:
        return "layer_a_liquidity_corridor", (min_gate_share, rank, annotated_candidate, False, False)
    if (
        candidate.ticker in corridor_visibility_gap_tickers
        and min_gate_share >= corridor_min_gate_share
        and cutoff_share <= corridor_visibility_gap_max_cutoff_share
    ):
        return "layer_a_liquidity_corridor", (min_gate_share, rank, annotated_candidate, False, True)
    if (
        candidate.ticker in corridor_focus_tickers
        and min_gate_share >= corridor_min_gate_share
        and cutoff_share <= corridor_focus_max_cutoff_share
    ):
        return "layer_a_liquidity_corridor", (min_gate_share, rank, annotated_candidate, True, False)
    if (
        candidate.ticker in corridor_focus_tickers
        and min_gate_share >= corridor_focus_min_gate_share
        and cutoff_share <= corridor_focus_low_gate_max_cutoff_share
    ):
        return "layer_a_liquidity_corridor", (min_gate_share, rank, annotated_candidate, True, False)
    if (
        min_gate_share >= rebucket_min_gate_share
        and cutoff_share >= rebucket_min_cutoff_share
        and cutoff_share <= rebucket_max_cutoff_share
    ):
        return "post_gate_liquidity_competition", (cutoff_share, rank, annotated_candidate, False, False)
    if (
        candidate.ticker in rebucket_visibility_gap_tickers
        and min_gate_share >= rebucket_min_gate_share
        and cutoff_share >= rebucket_visibility_gap_min_cutoff_share
        and cutoff_share <= rebucket_max_cutoff_share
    ):
        return "post_gate_liquidity_competition", (cutoff_share, rank, annotated_candidate, False, True)
    if (
        candidate.ticker in rebucket_focus_tickers
        and min_gate_share >= rebucket_min_gate_share
        and cutoff_share >= rebucket_focus_min_cutoff_share
        and cutoff_share <= rebucket_max_cutoff_share
    ):
        return "post_gate_liquidity_competition", (cutoff_share, rank, annotated_candidate, True, False)
    return None


def build_shadow_summary_payload(
    *,
    pool_size: int,
    selected_count: int,
    overflow_count: int,
    selected_cutoff_avg_volume_20d: float,
    shadow_candidates: list[CandidateStock],
    shadow_entries: list[dict[str, Any]],
    focus_signature: str,
    focus_filter_diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "pool_size": pool_size,
        "selected_count": selected_count,
        "overflow_count": overflow_count,
        "selected_cutoff_avg_volume_20d": selected_cutoff_avg_volume_20d,
        "lane_counts": count_shadow_lanes(shadow_entries),
        "selected_tickers": [candidate.ticker for candidate in shadow_candidates],
        "focus_tickers": sorted({entry["ticker"] for entry in shadow_entries if entry.get("shadow_focus_selected")}),
        "visibility_gap_tickers": sorted({entry["ticker"] for entry in shadow_entries if entry.get("shadow_visibility_gap_selected")}),
        "focus_signature": focus_signature,
        "shadow_recall_complete": True,
        "shadow_recall_status": "computed",
        "tickers": shadow_entries,
        "focus_filter_diagnostics": list(focus_filter_diagnostics or []),
    }
