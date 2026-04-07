from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import (
    build_day_breakdown as _build_day_breakdown,
    build_false_negative_proxy_rows as _build_false_negative_proxy_rows,
    build_surface_summary as _build_surface_summary,
    extract_btst_price_outcome as _extract_btst_price_outcome,
)
from scripts.replay_selection_target_calibration import (
    STRUCTURAL_VARIANTS,
    _apply_candidate_entry_filters,
    _coerce_watchlist_entries,
    _extract_short_trade_snapshot_map,
    _iter_replay_input_sources,
    _override_short_trade_thresholds,
    _summarize_candidate_entry_filter_observability,
)
from src.targets import build_short_trade_target_profile
from src.targets.router import build_selection_targets


DEFAULT_GUARDRAIL_NEXT_HIGH_HIT_RATE = 0.5217
DEFAULT_GUARDRAIL_NEXT_CLOSE_POSITIVE_RATE = 0.5652


def _serialize_profile(profile: Any) -> dict[str, Any]:
    return {
        "name": profile.name,
        "select_threshold": round(float(profile.select_threshold), 4),
        "near_miss_threshold": round(float(profile.near_miss_threshold), 4),
        "selected_breakout_freshness_min": round(float(profile.selected_breakout_freshness_min), 4),
        "selected_trend_acceleration_min": round(float(profile.selected_trend_acceleration_min), 4),
        "near_miss_breakout_freshness_min": round(float(profile.near_miss_breakout_freshness_min), 4),
        "near_miss_trend_acceleration_min": round(float(profile.near_miss_trend_acceleration_min), 4),
        "breakout_freshness_weight": round(float(profile.breakout_freshness_weight), 4),
        "trend_acceleration_weight": round(float(profile.trend_acceleration_weight), 4),
        "volume_expansion_quality_weight": round(float(profile.volume_expansion_quality_weight), 4),
        "close_strength_weight": round(float(profile.close_strength_weight), 4),
        "sector_resonance_weight": round(float(profile.sector_resonance_weight), 4),
        "catalyst_freshness_weight": round(float(profile.catalyst_freshness_weight), 4),
        "layer_c_alignment_weight": round(float(profile.layer_c_alignment_weight), 4),
        "watchlist_zero_catalyst_penalty": round(float(profile.watchlist_zero_catalyst_penalty), 4),
        "watchlist_zero_catalyst_catalyst_freshness_max": round(float(profile.watchlist_zero_catalyst_catalyst_freshness_max), 4),
        "watchlist_zero_catalyst_close_strength_min": round(float(profile.watchlist_zero_catalyst_close_strength_min), 4),
        "watchlist_zero_catalyst_layer_c_alignment_min": round(float(profile.watchlist_zero_catalyst_layer_c_alignment_min), 4),
        "watchlist_zero_catalyst_sector_resonance_min": round(float(profile.watchlist_zero_catalyst_sector_resonance_min), 4),
        "watchlist_zero_catalyst_crowded_penalty": round(float(profile.watchlist_zero_catalyst_crowded_penalty), 4),
        "watchlist_zero_catalyst_crowded_catalyst_freshness_max": round(float(profile.watchlist_zero_catalyst_crowded_catalyst_freshness_max), 4),
        "watchlist_zero_catalyst_crowded_close_strength_min": round(float(profile.watchlist_zero_catalyst_crowded_close_strength_min), 4),
        "watchlist_zero_catalyst_crowded_layer_c_alignment_min": round(float(profile.watchlist_zero_catalyst_crowded_layer_c_alignment_min), 4),
        "watchlist_zero_catalyst_crowded_sector_resonance_min": round(float(profile.watchlist_zero_catalyst_crowded_sector_resonance_min), 4),
        "watchlist_zero_catalyst_flat_trend_penalty": round(float(profile.watchlist_zero_catalyst_flat_trend_penalty), 4),
        "watchlist_zero_catalyst_flat_trend_catalyst_freshness_max": round(float(profile.watchlist_zero_catalyst_flat_trend_catalyst_freshness_max), 4),
        "watchlist_zero_catalyst_flat_trend_close_strength_min": round(float(profile.watchlist_zero_catalyst_flat_trend_close_strength_min), 4),
        "watchlist_zero_catalyst_flat_trend_layer_c_alignment_min": round(float(profile.watchlist_zero_catalyst_flat_trend_layer_c_alignment_min), 4),
        "watchlist_zero_catalyst_flat_trend_sector_resonance_min": round(float(profile.watchlist_zero_catalyst_flat_trend_sector_resonance_min), 4),
        "watchlist_zero_catalyst_flat_trend_trend_acceleration_max": round(float(profile.watchlist_zero_catalyst_flat_trend_trend_acceleration_max), 4),
        "t_plus_2_continuation_enabled": bool(profile.t_plus_2_continuation_enabled),
        "t_plus_2_continuation_catalyst_freshness_max": round(float(profile.t_plus_2_continuation_catalyst_freshness_max), 4),
        "t_plus_2_continuation_breakout_freshness_min": round(float(profile.t_plus_2_continuation_breakout_freshness_min), 4),
        "t_plus_2_continuation_trend_acceleration_min": round(float(profile.t_plus_2_continuation_trend_acceleration_min), 4),
        "t_plus_2_continuation_trend_acceleration_max": round(float(profile.t_plus_2_continuation_trend_acceleration_max), 4),
        "t_plus_2_continuation_layer_c_alignment_min": round(float(profile.t_plus_2_continuation_layer_c_alignment_min), 4),
        "t_plus_2_continuation_layer_c_alignment_max": round(float(profile.t_plus_2_continuation_layer_c_alignment_max), 4),
        "t_plus_2_continuation_close_strength_max": round(float(profile.t_plus_2_continuation_close_strength_max), 4),
        "t_plus_2_continuation_sector_resonance_max": round(float(profile.t_plus_2_continuation_sector_resonance_max), 4),
        "stale_penalty_block_threshold": round(float(profile.stale_penalty_block_threshold), 4),
        "overhead_penalty_block_threshold": round(float(profile.overhead_penalty_block_threshold), 4),
        "extension_penalty_block_threshold": round(float(profile.extension_penalty_block_threshold), 4),
        "layer_c_avoid_penalty": round(float(profile.layer_c_avoid_penalty), 4),
        "profitability_relief_enabled": bool(profile.profitability_relief_enabled),
        "profitability_relief_breakout_freshness_min": round(float(profile.profitability_relief_breakout_freshness_min), 4),
        "profitability_relief_catalyst_freshness_min": round(float(profile.profitability_relief_catalyst_freshness_min), 4),
        "profitability_relief_sector_resonance_min": round(float(profile.profitability_relief_sector_resonance_min), 4),
        "profitability_relief_avoid_penalty": round(float(profile.profitability_relief_avoid_penalty), 4),
        "prepared_breakout_penalty_relief_enabled": bool(profile.prepared_breakout_penalty_relief_enabled),
        "prepared_breakout_penalty_relief_breakout_freshness_max": round(float(profile.prepared_breakout_penalty_relief_breakout_freshness_max), 4),
        "prepared_breakout_penalty_relief_trend_acceleration_min": round(float(profile.prepared_breakout_penalty_relief_trend_acceleration_min), 4),
        "prepared_breakout_penalty_relief_close_strength_min": round(float(profile.prepared_breakout_penalty_relief_close_strength_min), 4),
        "prepared_breakout_penalty_relief_sector_resonance_min": round(float(profile.prepared_breakout_penalty_relief_sector_resonance_min), 4),
        "prepared_breakout_penalty_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_penalty_relief_layer_c_alignment_min), 4),
        "prepared_breakout_penalty_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_penalty_relief_catalyst_freshness_max), 4),
        "prepared_breakout_penalty_relief_long_trend_strength_min": round(float(profile.prepared_breakout_penalty_relief_long_trend_strength_min), 4),
        "prepared_breakout_penalty_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_penalty_relief_mean_reversion_strength_max), 4),
        "prepared_breakout_penalty_relief_breakout_freshness_weight": round(float(profile.prepared_breakout_penalty_relief_breakout_freshness_weight), 4),
        "prepared_breakout_penalty_relief_trend_acceleration_weight": round(float(profile.prepared_breakout_penalty_relief_trend_acceleration_weight), 4),
        "prepared_breakout_penalty_relief_volume_expansion_quality_weight": round(float(profile.prepared_breakout_penalty_relief_volume_expansion_quality_weight), 4),
        "prepared_breakout_penalty_relief_close_strength_weight": round(float(profile.prepared_breakout_penalty_relief_close_strength_weight), 4),
        "prepared_breakout_penalty_relief_sector_resonance_weight": round(float(profile.prepared_breakout_penalty_relief_sector_resonance_weight), 4),
        "prepared_breakout_penalty_relief_catalyst_freshness_weight": round(float(profile.prepared_breakout_penalty_relief_catalyst_freshness_weight), 4),
        "prepared_breakout_penalty_relief_layer_c_alignment_weight": round(float(profile.prepared_breakout_penalty_relief_layer_c_alignment_weight), 4),
        "prepared_breakout_penalty_relief_stale_score_penalty_weight": round(float(profile.prepared_breakout_penalty_relief_stale_score_penalty_weight), 4),
        "prepared_breakout_penalty_relief_extension_score_penalty_weight": round(float(profile.prepared_breakout_penalty_relief_extension_score_penalty_weight), 4),
        "prepared_breakout_catalyst_relief_enabled": bool(profile.prepared_breakout_catalyst_relief_enabled),
        "prepared_breakout_catalyst_relief_breakout_freshness_max": round(float(profile.prepared_breakout_catalyst_relief_breakout_freshness_max), 4),
        "prepared_breakout_catalyst_relief_trend_acceleration_min": round(float(profile.prepared_breakout_catalyst_relief_trend_acceleration_min), 4),
        "prepared_breakout_catalyst_relief_close_strength_min": round(float(profile.prepared_breakout_catalyst_relief_close_strength_min), 4),
        "prepared_breakout_catalyst_relief_sector_resonance_min": round(float(profile.prepared_breakout_catalyst_relief_sector_resonance_min), 4),
        "prepared_breakout_catalyst_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_catalyst_relief_layer_c_alignment_min), 4),
        "prepared_breakout_catalyst_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_max), 4),
        "prepared_breakout_catalyst_relief_long_trend_strength_min": round(float(profile.prepared_breakout_catalyst_relief_long_trend_strength_min), 4),
        "prepared_breakout_catalyst_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_catalyst_relief_mean_reversion_strength_max), 4),
        "prepared_breakout_catalyst_relief_catalyst_freshness_floor": round(float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_floor), 4),
        "prepared_breakout_volume_relief_enabled": bool(profile.prepared_breakout_volume_relief_enabled),
        "prepared_breakout_volume_relief_breakout_freshness_max": round(float(profile.prepared_breakout_volume_relief_breakout_freshness_max), 4),
        "prepared_breakout_volume_relief_trend_acceleration_min": round(float(profile.prepared_breakout_volume_relief_trend_acceleration_min), 4),
        "prepared_breakout_volume_relief_close_strength_min": round(float(profile.prepared_breakout_volume_relief_close_strength_min), 4),
        "prepared_breakout_volume_relief_sector_resonance_min": round(float(profile.prepared_breakout_volume_relief_sector_resonance_min), 4),
        "prepared_breakout_volume_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_volume_relief_layer_c_alignment_min), 4),
        "prepared_breakout_volume_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_volume_relief_catalyst_freshness_max), 4),
        "prepared_breakout_volume_relief_long_trend_strength_min": round(float(profile.prepared_breakout_volume_relief_long_trend_strength_min), 4),
        "prepared_breakout_volume_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_volume_relief_mean_reversion_strength_max), 4),
        "prepared_breakout_volume_relief_volatility_strength_max": round(float(profile.prepared_breakout_volume_relief_volatility_strength_max), 4),
        "prepared_breakout_volume_relief_volatility_regime_min": round(float(profile.prepared_breakout_volume_relief_volatility_regime_min), 4),
        "prepared_breakout_volume_relief_atr_ratio_min": round(float(profile.prepared_breakout_volume_relief_atr_ratio_min), 4),
        "prepared_breakout_volume_relief_volume_expansion_quality_floor": round(float(profile.prepared_breakout_volume_relief_volume_expansion_quality_floor), 4),
        "prepared_breakout_continuation_relief_enabled": bool(profile.prepared_breakout_continuation_relief_enabled),
        "prepared_breakout_continuation_relief_breakout_freshness_max": round(float(profile.prepared_breakout_continuation_relief_breakout_freshness_max), 4),
        "prepared_breakout_continuation_relief_trend_acceleration_min": round(float(profile.prepared_breakout_continuation_relief_trend_acceleration_min), 4),
        "prepared_breakout_continuation_relief_trend_acceleration_max": round(float(profile.prepared_breakout_continuation_relief_trend_acceleration_max), 4),
        "prepared_breakout_continuation_relief_close_strength_min": round(float(profile.prepared_breakout_continuation_relief_close_strength_min), 4),
        "prepared_breakout_continuation_relief_sector_resonance_min": round(float(profile.prepared_breakout_continuation_relief_sector_resonance_min), 4),
        "prepared_breakout_continuation_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_continuation_relief_layer_c_alignment_min), 4),
        "prepared_breakout_continuation_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_continuation_relief_catalyst_freshness_max), 4),
        "prepared_breakout_continuation_relief_long_trend_strength_min": round(float(profile.prepared_breakout_continuation_relief_long_trend_strength_min), 4),
        "prepared_breakout_continuation_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_continuation_relief_mean_reversion_strength_max), 4),
        "prepared_breakout_continuation_relief_momentum_1m_max": round(float(profile.prepared_breakout_continuation_relief_momentum_1m_max), 4),
        "prepared_breakout_continuation_relief_continuation_support_min": round(float(profile.prepared_breakout_continuation_relief_continuation_support_min), 4),
        "prepared_breakout_continuation_relief_breakout_freshness_floor": round(float(profile.prepared_breakout_continuation_relief_breakout_freshness_floor), 4),
        "prepared_breakout_continuation_relief_trend_acceleration_floor": round(float(profile.prepared_breakout_continuation_relief_trend_acceleration_floor), 4),
        "prepared_breakout_selected_catalyst_relief_enabled": bool(profile.prepared_breakout_selected_catalyst_relief_enabled),
        "prepared_breakout_selected_catalyst_relief_breakout_freshness_min": round(float(profile.prepared_breakout_selected_catalyst_relief_breakout_freshness_min), 4),
        "prepared_breakout_selected_catalyst_relief_trend_acceleration_min": round(float(profile.prepared_breakout_selected_catalyst_relief_trend_acceleration_min), 4),
        "prepared_breakout_selected_catalyst_relief_close_strength_min": round(float(profile.prepared_breakout_selected_catalyst_relief_close_strength_min), 4),
        "prepared_breakout_selected_catalyst_relief_sector_resonance_min": round(float(profile.prepared_breakout_selected_catalyst_relief_sector_resonance_min), 4),
        "prepared_breakout_selected_catalyst_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_selected_catalyst_relief_layer_c_alignment_min), 4),
        "prepared_breakout_selected_catalyst_relief_volume_expansion_quality_min": round(float(profile.prepared_breakout_selected_catalyst_relief_volume_expansion_quality_min), 4),
        "prepared_breakout_selected_catalyst_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_max), 4),
        "prepared_breakout_selected_catalyst_relief_long_trend_strength_min": round(float(profile.prepared_breakout_selected_catalyst_relief_long_trend_strength_min), 4),
        "prepared_breakout_selected_catalyst_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_selected_catalyst_relief_mean_reversion_strength_max), 4),
        "prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor": round(float(profile.prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor), 4),
        "prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor": round(float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor), 4),
        "stale_score_penalty_weight": round(float(profile.stale_score_penalty_weight), 4),
        "overhead_score_penalty_weight": round(float(profile.overhead_score_penalty_weight), 4),
        "extension_score_penalty_weight": round(float(profile.extension_score_penalty_weight), 4),
        "hard_block_bearish_conflicts": sorted(str(item) for item in profile.hard_block_bearish_conflicts),
        "overhead_conflict_penalty_conflicts": sorted(str(item) for item in profile.overhead_conflict_penalty_conflicts),
    }


def analyze_btst_profile_replay_window(
    input_path: str | Path,
    *,
    profile_name: str,
    label: str | None = None,
    next_high_hit_threshold: float = 0.02,
    structural_variant: str = "baseline",
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    profile_overrides: dict[str, Any] | None = None,
    structural_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    replay_input_sources = _iter_replay_input_sources(input_path)
    if not replay_input_sources:
        raise FileNotFoundError(f"No replay inputs found under: {input_path}")

    effective_structural_overrides = dict(STRUCTURAL_VARIANTS.get(structural_variant, {}))
    if structural_overrides:
        effective_structural_overrides.update(dict(structural_overrides or {}))
    entry_filter_rules = list(effective_structural_overrides.get("exclude_candidate_entries") or [])
    structural_profile_overrides = dict(effective_structural_overrides.get("profile_overrides") or {})
    effective_profile_overrides = {
        key: value
        for key, value in {
            **structural_profile_overrides,
            **dict(profile_overrides or {}),
        }.items()
        if value is not None
    }
    if select_threshold is not None:
        effective_profile_overrides["select_threshold"] = select_threshold
    if near_miss_threshold is not None:
        effective_profile_overrides["near_miss_threshold"] = near_miss_threshold
    profile = build_short_trade_target_profile(profile_name, overrides=effective_profile_overrides)

    rows: list[dict[str, Any]] = []
    price_cache: dict[tuple[str, str], Any] = {}
    decision_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()
    cycle_status_counts: Counter[str] = Counter()
    data_status_counts: Counter[str] = Counter()
    target_modes: Counter[str] = Counter()
    filtered_candidate_entry_counts: Counter[str] = Counter()
    filtered_candidate_entry_rows: list[dict[str, Any]] = []
    candidate_entry_filter_observability: dict[str, Counter[str]] = {}

    with _override_short_trade_thresholds(
        profile_name=profile_name,
        profile_overrides=effective_profile_overrides,
        select_threshold=effective_profile_overrides.get("select_threshold"),
        near_miss_threshold=effective_profile_overrides.get("near_miss_threshold"),
        breakout_freshness_weight=effective_profile_overrides.get("breakout_freshness_weight"),
        trend_acceleration_weight=effective_profile_overrides.get("trend_acceleration_weight"),
        volume_expansion_quality_weight=effective_profile_overrides.get("volume_expansion_quality_weight"),
        close_strength_weight=effective_profile_overrides.get("close_strength_weight"),
        sector_resonance_weight=effective_profile_overrides.get("sector_resonance_weight"),
        catalyst_freshness_weight=effective_profile_overrides.get("catalyst_freshness_weight"),
        layer_c_alignment_weight=effective_profile_overrides.get("layer_c_alignment_weight"),
        stale_penalty_block_threshold=effective_structural_overrides.get("stale_penalty_block_threshold"),
        overhead_penalty_block_threshold=effective_structural_overrides.get("overhead_penalty_block_threshold"),
        extension_penalty_block_threshold=effective_structural_overrides.get("extension_penalty_block_threshold"),
        layer_c_avoid_penalty=effective_structural_overrides.get("layer_c_avoid_penalty"),
        strong_bearish_conflicts=effective_structural_overrides.get("strong_bearish_conflicts"),
        stale_score_penalty_weight=effective_structural_overrides.get("stale_score_penalty_weight"),
        overhead_score_penalty_weight=effective_structural_overrides.get("overhead_score_penalty_weight"),
        extension_score_penalty_weight=effective_structural_overrides.get("extension_score_penalty_weight"),
    ):
        for replay_input_path, payload in replay_input_sources:
            trade_date = str(payload.get("trade_date") or "")
            target_mode = str(payload.get("target_mode") or "research_only")
            target_modes[target_mode] += 1
            rejected_filter_observability = _summarize_candidate_entry_filter_observability(
                list(payload.get("rejected_entries") or []),
                entry_filter_rules,
                trade_date=trade_date,
                default_candidate_source="watchlist_filter_diagnostics",
            )
            supplemental_filter_observability = _summarize_candidate_entry_filter_observability(
                list(payload.get("supplemental_short_trade_entries") or []),
                entry_filter_rules,
                trade_date=trade_date,
                default_candidate_source="layer_b_boundary",
            )
            rejected_entries, filtered_rejected_entries = _apply_candidate_entry_filters(
                list(payload.get("rejected_entries") or []),
                entry_filter_rules,
                trade_date=trade_date,
                default_candidate_source="watchlist_filter_diagnostics",
            )
            supplemental_entries, filtered_supplemental_entries = _apply_candidate_entry_filters(
                list(payload.get("supplemental_short_trade_entries") or []),
                entry_filter_rules,
                trade_date=trade_date,
                default_candidate_source="layer_b_boundary",
            )
            filtered_entries = filtered_rejected_entries + filtered_supplemental_entries
            filtered_candidate_entry_counts.update(
                str(entry.get("matched_filter") or "unknown") for entry in filtered_entries
            )
            for observability in [rejected_filter_observability, supplemental_filter_observability]:
                for rule_name, counters in observability.items():
                    aggregate_counters = candidate_entry_filter_observability.setdefault(rule_name, Counter())
                    aggregate_counters.update(counters)
            for filtered_entry in filtered_entries:
                ticker = str(filtered_entry.get("ticker") or "")
                if not ticker:
                    continue
                price_outcome = _extract_btst_price_outcome(ticker, trade_date, price_cache)
                filtered_candidate_entry_rows.append(
                    {
                        "report_label": label or profile_name,
                        "profile_name": profile_name,
                        "trade_date": trade_date,
                        "ticker": ticker,
                        "decision": "filtered_out",
                        "candidate_source": str(filtered_entry.get("candidate_source") or "unknown"),
                        "candidate_reason_codes": list(filtered_entry.get("candidate_reason_codes") or []),
                        "matched_filter": str(filtered_entry.get("matched_filter") or "unknown"),
                        "metric_snapshot": dict(filtered_entry.get("metric_snapshot") or {}),
                        "metric_gate_status": dict(filtered_entry.get("metric_gate_status") or {}),
                        "replay_input_path": str(replay_input_path),
                        **price_outcome,
                    }
                )
            watchlist = _coerce_watchlist_entries(list(payload.get("watchlist") or []))
            buy_order_tickers = {str(ticker) for ticker in list(payload.get("buy_order_tickers") or []) if str(ticker or "").strip()}
            replayed_targets, _ = build_selection_targets(
                trade_date=trade_date.replace("-", ""),
                watchlist=watchlist,
                rejected_entries=rejected_entries,
                supplemental_short_trade_entries=supplemental_entries,
                buy_order_tickers=buy_order_tickers,
                target_mode=target_mode,
            )
            replayed_snapshots = _extract_short_trade_snapshot_map(replayed_targets)
            stored_targets = dict(payload.get("selection_targets") or {})

            for ticker, replayed_snapshot in replayed_snapshots.items():
                if not replayed_snapshot:
                    continue
                stored_evaluation = dict(stored_targets.get(ticker) or {})
                stored_short_trade = dict(stored_evaluation.get("short_trade") or {})
                price_outcome = _extract_btst_price_outcome(str(ticker), trade_date, price_cache)
                candidate_source = str(
                    stored_evaluation.get("candidate_source")
                    or dict(replayed_snapshot.get("explainability_payload") or {}).get("candidate_source")
                    or "unknown"
                )
                row = {
                    "report_label": label or profile_name,
                    "profile_name": profile_name,
                    "trade_date": trade_date,
                    "ticker": str(ticker),
                    "stored_decision": stored_short_trade.get("decision"),
                    "decision": replayed_snapshot.get("decision"),
                    "score_target": replayed_snapshot.get("score_target"),
                    "candidate_source": candidate_source,
                    "candidate_reason_codes": list(stored_evaluation.get("candidate_reason_codes") or []),
                    "delta_classification": stored_evaluation.get("delta_classification"),
                    "blockers": list(replayed_snapshot.get("blockers") or []),
                    "gate_status": dict(replayed_snapshot.get("gate_status") or {}),
                    "metrics_payload": dict(replayed_snapshot.get("metrics_payload") or {}),
                    "explainability_payload": dict(replayed_snapshot.get("explainability_payload") or {}),
                    "target_mode": target_mode,
                    "replay_input_path": str(replay_input_path),
                    **price_outcome,
                }
                rows.append(row)
                decision_counts[str(row.get("decision") or "unknown")] += 1
                candidate_source_counts[candidate_source] += 1
                cycle_status_counts[str(row.get("cycle_status") or "unknown")] += 1
                data_status_counts[str(row.get("data_status") or "unknown")] += 1

    rows.sort(key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or "")))
    actionable_rows = [row for row in rows if row.get("decision") in {"selected", "near_miss"}]
    selected_rows = [row for row in rows if row.get("decision") == "selected"]
    near_miss_rows = [row for row in rows if row.get("decision") == "near_miss"]
    blocked_rows = [row for row in rows if row.get("decision") == "blocked"]
    rejected_rows = [row for row in rows if row.get("decision") == "rejected"]
    false_negative_rows = _build_false_negative_proxy_rows(rows, next_high_hit_threshold=next_high_hit_threshold)

    top_tradeable_rows = sorted(
        actionable_rows,
        key=lambda row: (
            1 if row.get("decision") == "selected" else 0,
            float(row.get("score_target") or -999.0),
            float(row.get("next_high_return") or -999.0),
        ),
        reverse=True,
    )[:8]

    if actionable_rows:
        recommendation = f"{profile_name} 已形成可研究的 actionable surface，下一步优先检查其 closed-cycle 质量是否优于 baseline false negative proxy。"
    elif false_negative_rows:
        recommendation = f"{profile_name} 仍未形成 actionable surface，但 false negative proxy 仍存在，说明还需要继续优化 score frontier 或 profile 语义。"
    else:
        recommendation = f"{profile_name} 既没有 actionable surface，也没有可用 false negative proxy，先检查样本窗口与 replay 输入质量。"

    false_negative_source_counts: Counter[str] = Counter(str(row.get("candidate_source") or "unknown") for row in false_negative_rows)
    false_negative_decision_counts: Counter[str] = Counter(str(row.get("decision") or "unknown") for row in false_negative_rows)
    filtered_candidate_source_counts: Counter[str] = Counter(str(row.get("candidate_source") or "unknown") for row in filtered_candidate_entry_rows)
    top_filtered_candidate_entry_rows = sorted(
        filtered_candidate_entry_rows,
        key=lambda row: (
            float(row.get("next_high_return") or -999.0),
            float(row.get("next_close_return") or -999.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )[:8]

    return {
        "label": label or profile_name,
        "profile_name": profile_name,
        "profile_config": _serialize_profile(profile),
        "profile_overrides": effective_profile_overrides,
        "structural_variant": structural_variant,
        "structural_overrides": effective_structural_overrides,
        "input_path": str(Path(input_path).expanduser().resolve()),
        "target_mode": target_modes.most_common(1)[0][0] if target_modes else "unknown",
        "trade_dates": sorted({str(row.get("trade_date") or "") for row in rows}),
        "row_count": len(rows),
        "decision_counts": dict(decision_counts),
        "candidate_source_counts": dict(candidate_source_counts),
        "cycle_status_counts": dict(cycle_status_counts),
        "data_status_counts": dict(data_status_counts),
        "candidate_entry_filter_observability": {
            rule_name: {key: int(value) for key, value in counters.items()}
            for rule_name, counters in sorted(candidate_entry_filter_observability.items())
        },
        "surface_summaries": {
            "all": _build_surface_summary(rows, next_high_hit_threshold=next_high_hit_threshold),
            "tradeable": _build_surface_summary(actionable_rows, next_high_hit_threshold=next_high_hit_threshold),
            "selected": _build_surface_summary(selected_rows, next_high_hit_threshold=next_high_hit_threshold),
            "near_miss": _build_surface_summary(near_miss_rows, next_high_hit_threshold=next_high_hit_threshold),
            "blocked": _build_surface_summary(blocked_rows, next_high_hit_threshold=next_high_hit_threshold),
            "rejected": _build_surface_summary(rejected_rows, next_high_hit_threshold=next_high_hit_threshold),
        },
        "false_negative_proxy_summary": {
            "count": len(false_negative_rows),
            "candidate_source_counts": dict(false_negative_source_counts),
            "decision_counts": dict(false_negative_decision_counts),
            "surface_metrics": _build_surface_summary(false_negative_rows, next_high_hit_threshold=next_high_hit_threshold),
        },
        "filtered_candidate_entry_summary": {
            "count": len(filtered_candidate_entry_rows),
            "matched_filter_counts": dict(filtered_candidate_entry_counts),
            "candidate_source_counts": dict(filtered_candidate_source_counts),
            "surface_metrics": _build_surface_summary(filtered_candidate_entry_rows, next_high_hit_threshold=next_high_hit_threshold),
        },
        "top_tradeable_rows": top_tradeable_rows,
        "top_false_negative_rows": false_negative_rows[:8],
        "top_filtered_candidate_entry_rows": top_filtered_candidate_entry_rows,
        "day_breakdown": _build_day_breakdown(rows),
        "recommendation": recommendation,
        "filtered_candidate_entry_rows": filtered_candidate_entry_rows,
        "rows": rows,
    }
