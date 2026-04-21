from __future__ import annotations

import argparse
import json
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, cast

from scripts.btst_candidate_entry_utils import build_watchlist_avoid_weak_structure_filter as _build_watchlist_avoid_weak_structure_filter
from scripts.btst_latest_followup_utils import load_latest_btst_historical_prior_by_ticker
from scripts.replay_selection_target_calibration_helpers import (
    build_replay_analysis_config,
    build_replay_analysis_result,
    build_replay_analysis_state,
    ingest_replay_source_analysis,
    prepare_replay_source_context,
)
from src.execution.models import LayerCResult
from src.targets import SHORT_TRADE_TARGET_PROFILES, build_short_trade_target_profile, get_active_short_trade_target_profile, get_short_trade_target_profile, use_short_trade_target_profile
from src.targets.router import build_selection_targets
from src.targets.candidate_entry_filters import (
    apply_candidate_entry_filters as _apply_candidate_entry_filters,
    summarize_candidate_entry_filter_observability as _summarize_candidate_entry_filter_observability,
)
from src.execution.daily_pipeline_runtime_helpers import resolve_historical_prior_for_ticker as _resolve_historical_prior_for_ticker_impl


REPLAY_INPUT_FILENAME = "selection_target_replay_input.json"
SELECTION_SNAPSHOT_FILENAME = "selection_snapshot.json"
WATCHLIST_AVOID_BOUNDARY_ENTRY_FILTER = {
    "name": "watchlist_avoid_boundary_entry",
    "candidate_sources": ["watchlist_filter_diagnostics"],
    "all_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
}
WATCHLIST_AVOID_WEAK_STRUCTURE_ENTRY_FILTER = {
    **_build_watchlist_avoid_weak_structure_filter(
        breakout_freshness_max=0.05,
        volume_expansion_quality_max=0.05,
        catalyst_freshness_max=0.05,
    )
}

WATCHLIST_ZERO_CATALYST_GUARD_PROFILE_OVERRIDES: dict[str, Any] = {
    "watchlist_zero_catalyst_penalty": 0.12,
    "watchlist_zero_catalyst_catalyst_freshness_max": 0.05,
    "watchlist_zero_catalyst_close_strength_min": 0.92,
    "watchlist_zero_catalyst_layer_c_alignment_min": 0.72,
    "watchlist_zero_catalyst_sector_resonance_min": 0.35,
}
WATCHLIST_ZERO_CATALYST_GUARD_RELIEF_PROFILE_OVERRIDES: dict[str, Any] = {
    **WATCHLIST_ZERO_CATALYST_GUARD_PROFILE_OVERRIDES,
    "select_threshold": 0.40,
    "near_miss_threshold": 0.40,
    "watchlist_zero_catalyst_crowded_penalty": 0.06,
    "watchlist_zero_catalyst_crowded_catalyst_freshness_max": 0.05,
    "watchlist_zero_catalyst_crowded_close_strength_min": 0.938,
    "watchlist_zero_catalyst_crowded_layer_c_alignment_min": 0.78,
    "watchlist_zero_catalyst_crowded_sector_resonance_min": 0.42,
    "watchlist_zero_catalyst_flat_trend_penalty": 0.03,
    "watchlist_zero_catalyst_flat_trend_catalyst_freshness_max": 0.05,
    "watchlist_zero_catalyst_flat_trend_close_strength_min": 0.945,
    "watchlist_zero_catalyst_flat_trend_layer_c_alignment_min": 0.75,
    "watchlist_zero_catalyst_flat_trend_sector_resonance_min": 0.388,
    "watchlist_zero_catalyst_flat_trend_trend_acceleration_max": 0.66,
    "t_plus_2_continuation_enabled": True,
    "t_plus_2_continuation_catalyst_freshness_max": 0.08,
    "t_plus_2_continuation_breakout_freshness_min": 0.30,
    "t_plus_2_continuation_trend_acceleration_min": 0.38,
    "t_plus_2_continuation_trend_acceleration_max": 0.60,
    "t_plus_2_continuation_layer_c_alignment_min": 0.45,
    "t_plus_2_continuation_layer_c_alignment_max": 0.60,
    "t_plus_2_continuation_close_strength_max": 0.90,
    "t_plus_2_continuation_sector_resonance_max": 0.20,
}

STRUCTURAL_VARIANTS: dict[str, dict[str, Any]] = {
    "baseline": {},
    "no_bearish_conflict_block": {
        "strong_bearish_conflicts": [],
    },
    "half_avoid_penalty": {
        "layer_c_avoid_penalty": 0.06,
    },
    "relaxed_penalty_thresholds": {
        "stale_penalty_block_threshold": 0.9,
        "overhead_penalty_block_threshold": 0.9,
        "extension_penalty_block_threshold": 0.9,
    },
    "no_bearish_conflict_half_avoid": {
        "strong_bearish_conflicts": [],
        "layer_c_avoid_penalty": 0.06,
    },
    "no_bearish_conflict_relaxed_penalties": {
        "strong_bearish_conflicts": [],
        "stale_penalty_block_threshold": 0.9,
        "overhead_penalty_block_threshold": 0.9,
        "extension_penalty_block_threshold": 0.9,
    },
    "softer_penalty_weights": {
        "layer_c_avoid_penalty": 0.06,
        "stale_score_penalty_weight": 0.06,
        "overhead_score_penalty_weight": 0.05,
        "extension_score_penalty_weight": 0.04,
    },
    "no_bearish_conflict_softer_penalty_weights": {
        "strong_bearish_conflicts": [],
        "layer_c_avoid_penalty": 0.06,
        "stale_score_penalty_weight": 0.06,
        "overhead_score_penalty_weight": 0.05,
        "extension_score_penalty_weight": 0.04,
    },
    "no_bearish_conflict_softer_penalty_weights_watchlist_zero_catalyst_guard": {
        "strong_bearish_conflicts": [],
        "layer_c_avoid_penalty": 0.06,
        "stale_score_penalty_weight": 0.06,
        "overhead_score_penalty_weight": 0.05,
        "extension_score_penalty_weight": 0.04,
        "profile_overrides": dict(WATCHLIST_ZERO_CATALYST_GUARD_PROFILE_OVERRIDES),
    },
    "no_bearish_conflict_softer_penalty_weights_watchlist_zero_catalyst_guard_relief": {
        "strong_bearish_conflicts": [],
        "layer_c_avoid_penalty": 0.06,
        "stale_score_penalty_weight": 0.06,
        "overhead_score_penalty_weight": 0.05,
        "extension_score_penalty_weight": 0.04,
        "profile_overrides": dict(WATCHLIST_ZERO_CATALYST_GUARD_RELIEF_PROFILE_OVERRIDES),
    },
    "no_bearish_conflict_lower_avoid_penalty": {
        "strong_bearish_conflicts": [],
        "layer_c_avoid_penalty": 0.06,
    },
    "no_bearish_conflict_lower_stale_penalty_weight": {
        "strong_bearish_conflicts": [],
        "stale_score_penalty_weight": 0.06,
    },
    "no_bearish_conflict_lower_extension_penalty_weight": {
        "strong_bearish_conflicts": [],
        "extension_score_penalty_weight": 0.04,
    },
    "no_bearish_conflict_lower_avoid_plus_stale": {
        "strong_bearish_conflicts": [],
        "layer_c_avoid_penalty": 0.06,
        "stale_score_penalty_weight": 0.06,
    },
    "no_bearish_conflict_penalty_triplet_relief": {
        "strong_bearish_conflicts": [],
        "layer_c_avoid_penalty": 0.06,
        "stale_score_penalty_weight": 0.06,
        "extension_score_penalty_weight": 0.04,
    },
    "no_bearish_conflict_extreme_penalty_relief": {
        "strong_bearish_conflicts": [],
        "layer_c_avoid_penalty": 0.02,
        "stale_score_penalty_weight": 0.02,
        "extension_score_penalty_weight": 0.0,
    },
    "exclude_watchlist_avoid_boundary_entries": {
        "exclude_candidate_entries": [WATCHLIST_AVOID_BOUNDARY_ENTRY_FILTER],
    },
    "no_bearish_conflict_exclude_watchlist_avoid_boundary_entries": {
        "strong_bearish_conflicts": [],
        "exclude_candidate_entries": [WATCHLIST_AVOID_BOUNDARY_ENTRY_FILTER],
    },
    "exclude_watchlist_avoid_weak_structure_entries": {
        "exclude_candidate_entries": [WATCHLIST_AVOID_WEAK_STRUCTURE_ENTRY_FILTER],
    },
    "no_bearish_conflict_exclude_watchlist_avoid_weak_structure_entries": {
        "strong_bearish_conflicts": [],
        "exclude_candidate_entries": [WATCHLIST_AVOID_WEAK_STRUCTURE_ENTRY_FILTER],
    },
}


def _default_short_trade_target_profile():
    return get_short_trade_target_profile("default")


def _resolve_short_trade_target_profile(profile_name: str | None):
    return get_short_trade_target_profile(str(profile_name or "default"))


def _active_short_trade_target_profile():
    return get_active_short_trade_target_profile()


def _resolve_structural_profile_overrides(structural_overrides: dict[str, Any]) -> dict[str, Any]:
    return dict(structural_overrides.get("profile_overrides") or {})


def _extract_embedded_short_trade_profile_snapshot(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    pipeline_config_snapshot = dict(payload.get("pipeline_config_snapshot") or {})
    short_trade_profile_snapshot = dict(pipeline_config_snapshot.get("short_trade_target_profile") or {})
    embedded_profile_name = str(short_trade_profile_snapshot.get("name") or "").strip() or None
    embedded_profile_config = dict(short_trade_profile_snapshot.get("config") or {})
    return embedded_profile_name, embedded_profile_config


def _apply_legacy_bearish_conflict_block_fallback(embedded_profile_config: dict[str, Any]) -> dict[str, Any]:
    resolved_config = dict(embedded_profile_config or {})
    has_legacy_conflict_blockers = bool(resolved_config.get("hard_block_bearish_conflicts"))
    if not has_legacy_conflict_blockers:
        return resolved_config
    if "hard_block_conflict_score_b_relief_min" not in resolved_config:
        resolved_config["hard_block_conflict_score_b_relief_min"] = None
    if "hard_block_conflict_score_c_relief_min" not in resolved_config:
        resolved_config["hard_block_conflict_score_c_relief_min"] = None
    return resolved_config


def _resolve_replay_profile_context(
    payload: dict[str, Any],
    *,
    requested_profile_name: str,
    requested_profile_overrides: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    resolved_profile_name = str(requested_profile_name or "default")
    resolved_profile_overrides = dict(requested_profile_overrides or {})
    embedded_profile_name, embedded_profile_config = _extract_embedded_short_trade_profile_snapshot(payload)
    if resolved_profile_name == "default" and embedded_profile_name:
        resolved_profile_name = embedded_profile_name
        if embedded_profile_config:
            embedded_profile_config = _apply_legacy_bearish_conflict_block_fallback(embedded_profile_config)
            resolved_profile_overrides = {
                **embedded_profile_config,
                **resolved_profile_overrides,
            }
    return resolved_profile_name, resolved_profile_overrides


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_threshold_grid(raw: str | None) -> list[float]:
    if raw is None or not str(raw).strip():
        return []
    values = []
    for token in str(raw).split(","):
        token = token.strip()
        if not token:
            continue
        values.append(float(token))
    return values


def _parse_optional_threshold_grid(raw: str | None) -> list[float | None]:
    if raw is None or not str(raw).strip():
        return []
    values: list[float | None] = []
    for token in str(raw).split(","):
        token = token.strip()
        if not token:
            continue
        if token.lower() in {"none", "omit", "skip"}:
            values.append(None)
            continue
        values.append(float(token))
    return values


def _parse_structural_variant_grid(raw: str | None) -> list[str]:
    if raw is None or not str(raw).strip():
        return []
    names = [token.strip() for token in str(raw).split(",") if token.strip()]
    unknown = [name for name in names if name not in STRUCTURAL_VARIANTS]
    if unknown:
        raise ValueError(f"Unknown structural variants: {', '.join(unknown)}")
    return names


def _parse_ticker_grid(raw: str | None) -> list[str]:
    if raw is None or not str(raw).strip():
        return []
    return [token.strip() for token in str(raw).split(",") if token.strip()]


def _attach_market_state(entries: list[dict[str, Any]], *, market_state_payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not market_state_payload:
        return [dict(entry or {}) for entry in list(entries or [])]
    attached_entries: list[dict[str, Any]] = []
    for entry in list(entries or []):
        updated_entry = dict(entry or {})
        entry_market_state = dict(updated_entry.get("market_state") or {})
        if not entry_market_state:
            updated_entry["market_state"] = dict(market_state_payload)
        attached_entries.append(updated_entry)
    return attached_entries


def _build_replay_input_from_selection_snapshot(snapshot_payload: dict[str, Any]) -> dict[str, Any]:
    funnel_filters = dict(dict(snapshot_payload.get("funnel_diagnostics") or {}).get("filters") or {})
    watchlist_filter = dict(funnel_filters.get("watchlist") or {})
    short_trade_candidates_filter = dict(funnel_filters.get("short_trade_candidates") or {})
    catalyst_theme_filter = dict(funnel_filters.get("catalyst_theme_candidates") or {})
    watchlist_entries = [dict(entry or {}) for entry in list(watchlist_filter.get("selected_entries") or [])]
    rejected_entries = [dict(entry or {}) for entry in list(watchlist_filter.get("tickers") or [])]
    supplemental_short_trade_entries = [dict(entry or {}) for entry in list(short_trade_candidates_filter.get("tickers") or [])]
    upstream_shadow_observation_entries = [dict(entry or {}) for entry in list(short_trade_candidates_filter.get("shadow_observation_entries") or [])]
    supplemental_catalyst_theme_entries = [dict(entry or {}) for entry in list(catalyst_theme_filter.get("tickers") or [])]
    market_state_payload = dict(snapshot_payload.get("market_state") or {})
    if not market_state_payload:
        for entries in (
            watchlist_entries,
            rejected_entries,
            supplemental_short_trade_entries,
            upstream_shadow_observation_entries,
            supplemental_catalyst_theme_entries,
        ):
            for entry in entries:
                entry_market_state = dict(entry.get("market_state") or {})
                if entry_market_state:
                    market_state_payload = entry_market_state
                    break
            if market_state_payload:
                break
    watchlist_entries = _attach_market_state(watchlist_entries, market_state_payload=market_state_payload)
    rejected_entries = _attach_market_state(rejected_entries, market_state_payload=market_state_payload)
    supplemental_short_trade_entries = _attach_market_state(supplemental_short_trade_entries, market_state_payload=market_state_payload)
    upstream_shadow_observation_entries = _attach_market_state(
        upstream_shadow_observation_entries,
        market_state_payload=market_state_payload,
    )
    supplemental_catalyst_theme_entries = _attach_market_state(
        supplemental_catalyst_theme_entries,
        market_state_payload=market_state_payload,
    )
    buy_orders = [dict(entry or {}) for entry in list(snapshot_payload.get("buy_orders") or [])]
    return {
        "artifact_version": snapshot_payload.get("artifact_version") or "v1",
        "run_id": snapshot_payload.get("run_id") or "selection_snapshot_replay",
        "trade_date": snapshot_payload.get("trade_date"),
        "market": snapshot_payload.get("market"),
        "market_state": market_state_payload,
        "target_mode": snapshot_payload.get("target_mode") or "research_only",
        "pipeline_config_snapshot": dict(snapshot_payload.get("pipeline_config_snapshot") or {}),
        "source_summary": {
            "watchlist_count": len(watchlist_entries),
            "rejected_entry_count": len(rejected_entries),
            "supplemental_short_trade_entry_count": len(supplemental_short_trade_entries),
            "upstream_shadow_observation_entry_count": len(upstream_shadow_observation_entries),
            "supplemental_catalyst_theme_entry_count": len(supplemental_catalyst_theme_entries),
            "buy_order_ticker_count": len(buy_orders),
        },
        "watchlist": watchlist_entries,
        "rejected_entries": rejected_entries,
        "supplemental_short_trade_entries": supplemental_short_trade_entries,
        "upstream_shadow_observation_entries": upstream_shadow_observation_entries,
        "supplemental_catalyst_theme_entries": supplemental_catalyst_theme_entries,
        "buy_order_tickers": [str(entry.get("ticker") or "") for entry in buy_orders if str(entry.get("ticker") or "").strip()],
        "selection_targets": dict(snapshot_payload.get("selection_targets") or {}),
        "target_summary": dict(snapshot_payload.get("target_summary") or {}),
    }


def _merge_replay_short_trade_entries(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    supplemental_entries = [dict(entry or {}) for entry in list(payload.get("supplemental_short_trade_entries") or [])]
    upstream_shadow_observation_entries = [dict(entry or {}) for entry in list(payload.get("upstream_shadow_observation_entries") or [])]
    replay_entries = supplemental_entries + upstream_shadow_observation_entries
    return replay_entries, upstream_shadow_observation_entries


def _resolve_reports_root_from_replay_input_path(replay_input_path: Path) -> Path | None:
    resolved_path = replay_input_path.expanduser().resolve()
    for parent in resolved_path.parents:
        if parent.name != "selection_artifacts":
            continue
        report_dir = parent.parent
        reports_root = report_dir.parent
        return reports_root if reports_root.exists() else None
    return None


def _attach_latest_historical_prior_to_entry(entry: dict[str, Any], *, prior_by_ticker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    updated_entry = dict(entry or {})
    ticker = str(updated_entry.get("ticker") or "").strip()
    if not ticker:
        return updated_entry
    historical_prior = _resolve_historical_prior_for_ticker_impl(
        ticker=ticker,
        historical_prior=dict(updated_entry.get("historical_prior") or {}),
        prior_by_ticker=prior_by_ticker,
    )
    if historical_prior:
        updated_entry["historical_prior"] = historical_prior
    return updated_entry


def _attach_latest_historical_prior_to_payload(
    payload: dict[str, Any],
    *,
    replay_input_path: Path,
    prior_cache: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    reports_root = _resolve_reports_root_from_replay_input_path(replay_input_path)
    if reports_root is None:
        return dict(payload)

    cache_key = reports_root.as_posix()
    prior_by_ticker = prior_cache.get(cache_key)
    if prior_by_ticker is None:
        prior_by_ticker = load_latest_btst_historical_prior_by_ticker(reports_root)
        prior_cache[cache_key] = prior_by_ticker
    if not prior_by_ticker:
        return dict(payload)

    refreshed_payload = dict(payload)
    for key in ("watchlist", "rejected_entries", "supplemental_short_trade_entries", "upstream_shadow_observation_entries"):
        refreshed_payload[key] = [
            _attach_latest_historical_prior_to_entry(dict(entry or {}), prior_by_ticker=prior_by_ticker)
            for entry in list(payload.get(key) or [])
        ]
    return refreshed_payload


def _iter_replay_input_sources(input_path: str | Path) -> list[tuple[Path, dict[str, Any]]]:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Replay input path does not exist: {path}")
    if path.is_file():
        if path.name == REPLAY_INPUT_FILENAME:
            return [(path, _load_json(path))]
        if path.name == SELECTION_SNAPSHOT_FILENAME:
            return [(path, _build_replay_input_from_selection_snapshot(_load_json(path)))]
        raise ValueError(f"Expected {REPLAY_INPUT_FILENAME} or {SELECTION_SNAPSHOT_FILENAME}, got: {path.name}")
    replay_paths = sorted(current for current in path.rglob(REPLAY_INPUT_FILENAME) if current.is_file())
    if replay_paths:
        return [(current, _load_json(current)) for current in replay_paths]
    snapshot_paths = sorted(current for current in path.rglob(SELECTION_SNAPSHOT_FILENAME) if current.is_file())
    if snapshot_paths:
        return [(current, _build_replay_input_from_selection_snapshot(_load_json(current))) for current in snapshot_paths]
    return []


def _build_short_trade_profile_overrides(
    *,
    profile_overrides: dict[str, Any] | None = None,
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    breakout_freshness_weight: float | None = None,
    trend_acceleration_weight: float | None = None,
    volume_expansion_quality_weight: float | None = None,
    close_strength_weight: float | None = None,
    sector_resonance_weight: float | None = None,
    catalyst_freshness_weight: float | None = None,
    layer_c_alignment_weight: float | None = None,
    stale_penalty_block_threshold: float | None = None,
    overhead_penalty_block_threshold: float | None = None,
    extension_penalty_block_threshold: float | None = None,
    layer_c_avoid_penalty: float | None = None,
    strong_bearish_conflicts: list[str] | None = None,
    stale_score_penalty_weight: float | None = None,
    overhead_score_penalty_weight: float | None = None,
    extension_score_penalty_weight: float | None = None,
) -> dict[str, Any]:
    overrides: dict[str, Any] = dict(profile_overrides or {})
    numeric_overrides = {
        "select_threshold": select_threshold,
        "near_miss_threshold": near_miss_threshold,
        "breakout_freshness_weight": breakout_freshness_weight,
        "trend_acceleration_weight": trend_acceleration_weight,
        "volume_expansion_quality_weight": volume_expansion_quality_weight,
        "close_strength_weight": close_strength_weight,
        "sector_resonance_weight": sector_resonance_weight,
        "catalyst_freshness_weight": catalyst_freshness_weight,
        "layer_c_alignment_weight": layer_c_alignment_weight,
        "stale_penalty_block_threshold": stale_penalty_block_threshold,
        "overhead_penalty_block_threshold": overhead_penalty_block_threshold,
        "extension_penalty_block_threshold": extension_penalty_block_threshold,
        "layer_c_avoid_penalty": layer_c_avoid_penalty,
        "stale_score_penalty_weight": stale_score_penalty_weight,
        "overhead_score_penalty_weight": overhead_score_penalty_weight,
        "extension_score_penalty_weight": extension_score_penalty_weight,
    }
    for key, value in numeric_overrides.items():
        if value is not None:
            overrides[key] = float(value)
    if strong_bearish_conflicts is not None:
        overrides["strong_bearish_conflicts"] = [str(value) for value in strong_bearish_conflicts]
    return overrides


@contextmanager
def _override_short_trade_thresholds(
    *,
    profile_name: str = "default",
    profile_overrides: dict[str, Any] | None = None,
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    breakout_freshness_weight: float | None = None,
    trend_acceleration_weight: float | None = None,
    volume_expansion_quality_weight: float | None = None,
    close_strength_weight: float | None = None,
    sector_resonance_weight: float | None = None,
    catalyst_freshness_weight: float | None = None,
    layer_c_alignment_weight: float | None = None,
    stale_penalty_block_threshold: float | None = None,
    overhead_penalty_block_threshold: float | None = None,
    extension_penalty_block_threshold: float | None = None,
    layer_c_avoid_penalty: float | None = None,
    strong_bearish_conflicts: list[str] | None = None,
    stale_score_penalty_weight: float | None = None,
    overhead_score_penalty_weight: float | None = None,
    extension_score_penalty_weight: float | None = None,
) -> Iterator[None]:
    overrides = _build_short_trade_profile_overrides(
        profile_overrides=profile_overrides,
        select_threshold=select_threshold,
        near_miss_threshold=near_miss_threshold,
        breakout_freshness_weight=breakout_freshness_weight,
        trend_acceleration_weight=trend_acceleration_weight,
        volume_expansion_quality_weight=volume_expansion_quality_weight,
        close_strength_weight=close_strength_weight,
        sector_resonance_weight=sector_resonance_weight,
        catalyst_freshness_weight=catalyst_freshness_weight,
        layer_c_alignment_weight=layer_c_alignment_weight,
        stale_penalty_block_threshold=stale_penalty_block_threshold,
        overhead_penalty_block_threshold=overhead_penalty_block_threshold,
        extension_penalty_block_threshold=extension_penalty_block_threshold,
        layer_c_avoid_penalty=layer_c_avoid_penalty,
        strong_bearish_conflicts=strong_bearish_conflicts,
        stale_score_penalty_weight=stale_score_penalty_weight,
        overhead_score_penalty_weight=overhead_score_penalty_weight,
        extension_score_penalty_weight=extension_score_penalty_weight,
    )
    with use_short_trade_target_profile(profile_name=profile_name, overrides=overrides):
        yield


def _coerce_watchlist_entries(entries: list[dict[str, Any]]) -> list[LayerCResult]:
    return [LayerCResult.model_validate(entry) for entry in entries]


def _extract_short_trade_decision_map(selection_targets: dict[str, Any]) -> dict[str, str | None]:
    decisions: dict[str, str | None] = {}
    for ticker, evaluation in dict(selection_targets or {}).items():
        short_trade = None
        if hasattr(evaluation, "short_trade"):
            short_trade = getattr(evaluation, "short_trade")
            decisions[str(ticker)] = getattr(short_trade, "decision", None) if short_trade is not None else None
            continue
        if isinstance(evaluation, dict):
            short_trade = dict(evaluation.get("short_trade") or {})
            decisions[str(ticker)] = str(short_trade.get("decision")) if short_trade else None
            continue
        decisions[str(ticker)] = None
    return decisions


def _extract_short_trade_snapshot_map(selection_targets: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for ticker, evaluation in dict(selection_targets or {}).items():
        short_trade = None
        if hasattr(evaluation, "short_trade"):
            short_trade = getattr(evaluation, "short_trade")
            if short_trade is None:
                snapshots[str(ticker)] = {}
            else:
                snapshots[str(ticker)] = {
                    "decision": getattr(short_trade, "decision", None),
                    "score_target": getattr(short_trade, "score_target", None),
                    "blockers": list(getattr(short_trade, "blockers", []) or []),
                    "rejection_reasons": list(getattr(short_trade, "rejection_reasons", []) or []),
                    "top_reasons": list(getattr(short_trade, "top_reasons", []) or []),
                    "gate_status": dict(getattr(short_trade, "gate_status", {}) or {}),
                    "metrics_payload": dict(getattr(short_trade, "metrics_payload", {}) or {}),
                    "explainability_payload": dict(getattr(short_trade, "explainability_payload", {}) or {}),
                }
            continue
        if isinstance(evaluation, dict):
            short_trade = dict(evaluation.get("short_trade") or {})
            snapshots[str(ticker)] = {
                "decision": short_trade.get("decision"),
                "score_target": short_trade.get("score_target"),
                "blockers": list(short_trade.get("blockers") or []),
                "rejection_reasons": list(short_trade.get("rejection_reasons") or []),
                "top_reasons": list(short_trade.get("top_reasons") or []),
                "gate_status": dict(short_trade.get("gate_status") or {}),
                "metrics_payload": dict(short_trade.get("metrics_payload") or {}),
                "explainability_payload": dict(short_trade.get("explainability_payload") or {}),
            }
            continue
        snapshots[str(ticker)] = {}
    return snapshots


def _build_score_diagnostic_row(
    *,
    trade_date: str,
    ticker: str,
    stored_evaluation: dict[str, Any],
    stored_snapshot: dict[str, Any],
    replayed_snapshot: dict[str, Any],
    replay_input_path: Path,
    replay_entry: dict[str, Any] | None = None,
    filtered_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    replayed_metrics = dict(replayed_snapshot.get("metrics_payload") or {})
    replay_entry_payload = dict(replay_entry or {})
    candidate_source = (
        stored_evaluation.get("candidate_source")
        or replay_entry_payload.get("candidate_source")
        or replay_entry_payload.get("source")
    )
    candidate_reason_codes = list(stored_evaluation.get("candidate_reason_codes") or replay_entry_payload.get("candidate_reason_codes") or replay_entry_payload.get("reasons") or [])
    return {
        "trade_date": trade_date,
        "ticker": ticker,
        "candidate_source": candidate_source,
        "candidate_reason_codes": candidate_reason_codes,
        "merge_approved_breakout_signal_uplift": dict(replay_entry_payload.get("merge_approved_breakout_signal_uplift") or {}),
        "merge_approved_layer_c_alignment_uplift": dict(replay_entry_payload.get("merge_approved_layer_c_alignment_uplift") or {}),
        "merge_approved_sector_resonance_uplift": dict(replay_entry_payload.get("merge_approved_sector_resonance_uplift") or {}),
        "delta_classification": stored_evaluation.get("delta_classification"),
        "delta_summary": list(stored_evaluation.get("delta_summary") or []),
        "stored_decision": stored_snapshot.get("decision"),
        "replayed_decision": replayed_snapshot.get("decision"),
        "stored_score_target": stored_snapshot.get("score_target"),
        "replayed_score_target": replayed_snapshot.get("score_target"),
        "replayed_present": bool(replayed_snapshot),
        "filtered_candidate_entry": filtered_entry is not None,
        "filtered_candidate_entry_rule": None if filtered_entry is None else filtered_entry.get("matched_filter"),
        "filtered_candidate_entry_metrics": {} if filtered_entry is None else dict(filtered_entry.get("metric_snapshot") or {}),
        "filtered_candidate_entry_metric_gate_status": {} if filtered_entry is None else dict(filtered_entry.get("metric_gate_status") or {}),
        "replayed_gap_to_near_miss": None
        if replayed_snapshot.get("score_target") is None
        else round(float(_active_short_trade_target_profile().near_miss_threshold) - float(replayed_snapshot.get("score_target")), 4),
        "replayed_gap_to_selected": None
        if replayed_snapshot.get("score_target") is None
        else round(float(_active_short_trade_target_profile().select_threshold) - float(replayed_snapshot.get("score_target")), 4),
        "stored_blockers": list(stored_snapshot.get("blockers") or []),
        "replayed_blockers": list(replayed_snapshot.get("blockers") or []),
        "stored_rejection_reasons": list(stored_snapshot.get("rejection_reasons") or []),
        "replayed_rejection_reasons": list(replayed_snapshot.get("rejection_reasons") or []),
        "replayed_top_reasons": list(replayed_snapshot.get("top_reasons") or []),
        "replayed_gate_status": dict(replayed_snapshot.get("gate_status") or {}),
        "replayed_metrics_payload": replayed_metrics,
        "replayed_explainability_payload": dict(replayed_snapshot.get("explainability_payload") or {}),
        "replayed_weighted_positive_contributions": dict(replayed_metrics.get("weighted_positive_contributions") or {}),
        "replayed_weighted_negative_contributions": dict(replayed_metrics.get("weighted_negative_contributions") or {}),
        "replayed_total_positive_contribution": replayed_metrics.get("total_positive_contribution"),
        "replayed_total_negative_contribution": replayed_metrics.get("total_negative_contribution"),
        "replay_input_path": str(replay_input_path),
    }


def _merge_candidate_entry_filter_observability(
    aggregate_observability: dict[str, Counter[str]],
    observability_sets: list[dict[str, Counter[str]]],
) -> dict[str, Counter[str]]:
    day_candidate_entry_filter_observability: dict[str, Counter[str]] = {}
    for observability in observability_sets:
        for rule_name, counters in observability.items():
            aggregate_counters = aggregate_observability.setdefault(rule_name, Counter())
            aggregate_counters.update(counters)
            day_counters = day_candidate_entry_filter_observability.setdefault(rule_name, Counter())
            day_counters.update(counters)
    return day_candidate_entry_filter_observability


def _analyze_replay_source_decisions(
    *,
    trade_date: str,
    payload: dict[str, Any],
    replay_input_path: Path,
    replay_entry_index: dict[str, dict[str, Any]],
    filtered_entry_index: dict[str, dict[str, Any]],
    replayed_targets: dict[str, Any],
    focus_ticker_set: set[str],
    mismatch_budget: int,
) -> dict[str, Any]:
    stored_decisions = _extract_short_trade_decision_map(dict(payload.get("selection_targets") or {}))
    replayed_decisions = _extract_short_trade_decision_map(replayed_targets)
    stored_snapshots = _extract_short_trade_snapshot_map(dict(payload.get("selection_targets") or {}))
    replayed_snapshots = _extract_short_trade_snapshot_map(replayed_targets)
    stored_decision_counts: Counter[str] = Counter()
    replayed_decision_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()
    mismatch_examples: list[dict[str, Any]] = []
    focused_score_diagnostics: list[dict[str, Any]] = []
    day_transition_counts: Counter[str] = Counter()
    day_mismatch_count = 0
    active_profile = _active_short_trade_target_profile()
    resolved_near_miss_threshold = float(active_profile.near_miss_threshold)
    resolved_select_threshold = float(active_profile.select_threshold)

    for entry in replay_entry_index.values():
        candidate_source_counts[str(entry.get("candidate_source") or "unknown")] += 1

    for ticker in sorted(set(stored_decisions) | set(replayed_decisions)):
        stored_decision = stored_decisions.get(ticker)
        replayed_decision = replayed_decisions.get(ticker)
        stored_evaluation = dict((payload.get("selection_targets") or {}).get(ticker) or {})
        stored_decision_counts[str(stored_decision or "none")] += 1
        replayed_decision_counts[str(replayed_decision or "none")] += 1
        transition_key = f"{stored_decision or 'none'}->{replayed_decision or 'none'}"
        transition_counts[transition_key] += 1
        day_transition_counts[transition_key] += 1
        if stored_decision != replayed_decision:
            day_mismatch_count += 1
            if len(mismatch_examples) < mismatch_budget:
                stored_snapshot = dict(stored_snapshots.get(ticker) or {})
                replayed_snapshot = dict(replayed_snapshots.get(ticker) or {})
                replayed_score_target = replayed_snapshot.get("score_target")
                mismatch_examples.append(
                    {
                        "trade_date": trade_date,
                        "ticker": ticker,
                        "stored_decision": stored_decision,
                        "replayed_decision": replayed_decision,
                        "stored_score_target": stored_snapshot.get("score_target"),
                        "replayed_score_target": replayed_score_target,
                        "replayed_gap_to_near_miss": None if replayed_score_target is None else round(resolved_near_miss_threshold - float(replayed_score_target), 4),
                        "replayed_gap_to_selected": None if replayed_score_target is None else round(resolved_select_threshold - float(replayed_score_target), 4),
                        "stored_blockers": list(stored_snapshot.get("blockers") or []),
                        "replayed_blockers": list(replayed_snapshot.get("blockers") or []),
                        "stored_rejection_reasons": list(stored_snapshot.get("rejection_reasons") or []),
                        "replayed_rejection_reasons": list(replayed_snapshot.get("rejection_reasons") or []),
                        "replayed_top_reasons": list(replayed_snapshot.get("top_reasons") or []),
                        "replayed_gate_status": dict(replayed_snapshot.get("gate_status") or {}),
                        "replayed_metrics_payload": dict(replayed_snapshot.get("metrics_payload") or {}),
                        "replay_input_path": str(replay_input_path),
                    }
                )
        if ticker in focus_ticker_set:
            focused_score_diagnostics.append(
                _build_score_diagnostic_row(
                    trade_date=trade_date,
                    ticker=ticker,
                    stored_evaluation=stored_evaluation,
                    stored_snapshot=dict(stored_snapshots.get(ticker) or {}),
                    replayed_snapshot=dict(replayed_snapshots.get(ticker) or {}),
                    replay_input_path=replay_input_path,
                    replay_entry=replay_entry_index.get(ticker),
                    filtered_entry=filtered_entry_index.get(ticker),
                )
            )
    return {
        "stored_decision_counts": stored_decision_counts,
        "replayed_decision_counts": replayed_decision_counts,
        "transition_counts": transition_counts,
        "candidate_source_counts": candidate_source_counts,
        "mismatch_examples": mismatch_examples,
        "focused_score_diagnostics": focused_score_diagnostics,
        "day_transition_counts": day_transition_counts,
        "day_mismatch_count": day_mismatch_count,
    }


def _collect_decision_examples(
    stored_decisions: dict[str, str | None],
    replayed_decisions: dict[str, str | None],
    *,
    target_decision: str,
    exclude_if_stored: set[str] | None = None,
) -> list[str]:
    excluded = set(exclude_if_stored or set())
    return [
        ticker
        for ticker in sorted(set(stored_decisions) | set(replayed_decisions))
        if replayed_decisions.get(ticker) == target_decision and stored_decisions.get(ticker) not in excluded
    ]


def _summarize_signal_availability(entries: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    availability_counts: Counter[str] = Counter()
    signal_name_counts: Counter[str] = Counter()
    for entry in entries:
        signal_names = sorted(str(name) for name in dict(entry.get("strategy_signals") or {}).keys() if str(name or "").strip())
        if signal_names:
            availability_counts["has_any"] += 1
            signal_name_counts.update(signal_names)
        else:
            availability_counts["missing_all"] += 1
    return dict(availability_counts.most_common()), dict(signal_name_counts.most_common())


def _build_replay_summary_row(analysis: dict[str, Any], *, structural_variant: str | None = None) -> dict[str, Any]:
    row = {
        "decision_mismatch_count": int(analysis["decision_mismatch_count"]),
        "replayed_short_trade_decision_counts": dict(analysis["replayed_short_trade_decision_counts"]),
        "decision_transition_counts": dict(analysis["decision_transition_counts"]),
        "candidate_entry_filter_observability": dict(analysis.get("candidate_entry_filter_observability") or {}),
        "promoted_to_selected": [example["ticker"] for example in analysis["mismatch_examples"] if example["replayed_decision"] == "selected"],
        "promoted_to_near_miss": [
            example["ticker"]
            for example in analysis["mismatch_examples"]
            if example["replayed_decision"] == "near_miss" and example["stored_decision"] not in {"selected", "near_miss"}
        ],
        "demoted_from_selected": [
            example["ticker"] for example in analysis["mismatch_examples"] if example["stored_decision"] == "selected" and example["replayed_decision"] != "selected"
        ],
        "released_from_blocked": [
            example["ticker"] for example in analysis["mismatch_examples"] if example["stored_decision"] == "blocked" and example["replayed_decision"] != "blocked"
        ],
        "blocked_to_near_miss": [
            example["ticker"]
            for example in analysis["mismatch_examples"]
            if example["stored_decision"] == "blocked" and example["replayed_decision"] == "near_miss"
        ],
        "blocked_to_selected": [
            example["ticker"]
            for example in analysis["mismatch_examples"]
            if example["stored_decision"] == "blocked" and example["replayed_decision"] == "selected"
        ],
    }
    if structural_variant is not None:
        row["structural_variant"] = structural_variant
        row["structural_overrides"] = dict(analysis["structural_overrides"])
    return row


def load_selection_target_replay_sources(input_path: str | Path) -> list[tuple[Path, dict[str, Any]]]:
    return _iter_replay_input_sources(input_path)


def analyze_selection_target_replay_sources(
    replay_input_sources: list[tuple[Path, dict[str, Any]]],
    *,
    profile_name: str = "default",
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    structural_variant: str = "baseline",
    structural_overrides: dict[str, Any] | None = None,
    focus_tickers: list[str] | None = None,
    refresh_latest_historical_prior: bool = False,
) -> dict[str, Any]:
    if not replay_input_sources:
        raise FileNotFoundError("No replay input sources provided.")

    config = build_replay_analysis_config(
        structural_variants=STRUCTURAL_VARIANTS,
        profile_name=profile_name,
        structural_variant=structural_variant,
        structural_overrides=structural_overrides,
        focus_tickers=focus_tickers,
        resolve_structural_profile_overrides=_resolve_structural_profile_overrides,
    )
    state = build_replay_analysis_state()
    prior_cache: dict[str, dict[str, dict[str, Any]]] = {}

    default_profile_name, default_profile_overrides = _resolve_replay_profile_context(
        replay_input_sources[0][1],
        requested_profile_name=config.profile_name,
        requested_profile_overrides=config.structural_profile_overrides,
    )
    default_profile = build_short_trade_target_profile(default_profile_name, default_profile_overrides)

    for replay_input_path, payload in replay_input_sources:
        resolved_profile_name, resolved_profile_overrides = _resolve_replay_profile_context(
            payload,
            requested_profile_name=config.profile_name,
            requested_profile_overrides=config.structural_profile_overrides,
        )
        with _override_short_trade_thresholds(
            profile_name=resolved_profile_name,
            profile_overrides=resolved_profile_overrides or None,
            select_threshold=select_threshold,
            near_miss_threshold=near_miss_threshold,
            breakout_freshness_weight=config.effective_structural_overrides.get("breakout_freshness_weight"),
            trend_acceleration_weight=config.effective_structural_overrides.get("trend_acceleration_weight"),
            volume_expansion_quality_weight=config.effective_structural_overrides.get("volume_expansion_quality_weight"),
            close_strength_weight=config.effective_structural_overrides.get("close_strength_weight"),
            sector_resonance_weight=config.effective_structural_overrides.get("sector_resonance_weight"),
            catalyst_freshness_weight=config.effective_structural_overrides.get("catalyst_freshness_weight"),
            layer_c_alignment_weight=config.effective_structural_overrides.get("layer_c_alignment_weight"),
            stale_penalty_block_threshold=config.effective_structural_overrides.get("stale_penalty_block_threshold"),
            overhead_penalty_block_threshold=config.effective_structural_overrides.get("overhead_penalty_block_threshold"),
            extension_penalty_block_threshold=config.effective_structural_overrides.get("extension_penalty_block_threshold"),
            layer_c_avoid_penalty=config.effective_structural_overrides.get("layer_c_avoid_penalty"),
            strong_bearish_conflicts=config.effective_structural_overrides.get("strong_bearish_conflicts"),
            stale_score_penalty_weight=config.effective_structural_overrides.get("stale_score_penalty_weight"),
            overhead_score_penalty_weight=config.effective_structural_overrides.get("overhead_score_penalty_weight"),
            extension_score_penalty_weight=config.effective_structural_overrides.get("extension_score_penalty_weight"),
        ):
            refreshed_payload = (
                _attach_latest_historical_prior_to_payload(
                    payload,
                    replay_input_path=replay_input_path,
                    prior_cache=prior_cache,
                )
                if refresh_latest_historical_prior
                else dict(payload)
            )
            source_context = prepare_replay_source_context(
                replay_input_path=replay_input_path,
                payload=refreshed_payload,
                entry_filter_rules=config.entry_filter_rules,
                candidate_entry_default_source="watchlist_filter_diagnostics",
                supplemental_default_source="layer_b_boundary",
                merge_replay_entries=_merge_replay_short_trade_entries,
                summarize_filter_observability=_summarize_candidate_entry_filter_observability,
                apply_candidate_entry_filters=_apply_candidate_entry_filters,
                coerce_watchlist_entries=_coerce_watchlist_entries,
                merge_candidate_entry_filter_observability=_merge_candidate_entry_filter_observability,
                state_candidate_entry_filter_observability=state.candidate_entry_filter_observability,
                summarize_signal_availability=_summarize_signal_availability,
            )
            replayed_targets, replayed_summary = build_selection_targets(
                trade_date=source_context.trade_date.replace("-", ""),
                watchlist=source_context.watchlist,
                rejected_entries=source_context.rejected_entries,
                supplemental_short_trade_entries=source_context.supplemental_entries,
                buy_order_tickers=source_context.buy_order_tickers,
                target_mode=source_context.target_mode,
            )
            source_analysis = _analyze_replay_source_decisions(
                trade_date=source_context.trade_date,
                payload=refreshed_payload,
                replay_input_path=replay_input_path,
                replay_entry_index=source_context.replay_entry_index,
                filtered_entry_index=source_context.filtered_entry_index,
                replayed_targets=replayed_targets,
                focus_ticker_set=config.focus_ticker_set,
                mismatch_budget=max(0, 20 - len(state.mismatch_examples)),
            )
            ingest_replay_source_analysis(
                state=state,
                source_context=source_context,
                source_analysis=source_analysis,
                replayed_summary=replayed_summary,
            )

    return build_replay_analysis_result(
        replay_input_count=len(replay_input_sources),
        config=config,
        state=state,
        select_threshold=select_threshold,
        near_miss_threshold=near_miss_threshold,
        default_profile=default_profile,
    )


def analyze_selection_target_replay_inputs(
    input_path: str | Path,
    *,
    profile_name: str = "default",
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    structural_variant: str = "baseline",
    structural_overrides: dict[str, Any] | None = None,
    focus_tickers: list[str] | None = None,
    refresh_latest_historical_prior: bool = False,
) -> dict[str, Any]:
    replay_input_sources = load_selection_target_replay_sources(input_path)
    return analyze_selection_target_replay_sources(
        replay_input_sources,
        profile_name=profile_name,
        select_threshold=select_threshold,
        near_miss_threshold=near_miss_threshold,
        structural_variant=structural_variant,
        structural_overrides=structural_overrides,
        focus_tickers=focus_tickers,
        refresh_latest_historical_prior=refresh_latest_historical_prior,
    )


def _diff_count_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, dict[str, int]]:
    keys = sorted(set(left) | set(right))
    return {
        key: {
            "left": int(left.get(key) or 0),
            "right": int(right.get(key) or 0),
            "delta": int(right.get(key) or 0) - int(left.get(key) or 0),
        }
        for key in keys
    }


def _index_replay_source_payloads(sources: list[tuple[Path, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for replay_input_path, payload in sources:
        trade_date = str(payload.get("trade_date") or "")
        indexed[trade_date] = {
            "replay_input_path": str(replay_input_path),
            "source_summary": dict(payload.get("source_summary") or {}),
            "selected_analysts": list(dict(payload.get("pipeline_config_snapshot") or {}).get("selected_analysts") or []),
            "analyst_roster_version": str(dict(payload.get("pipeline_config_snapshot") or {}).get("analyst_roster_version") or ""),
        }
    return indexed


def _index_replay_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("trade_date") or ""), str(row.get("ticker") or "")): row
        for row in rows
        if str(row.get("ticker") or "").strip()
    }


def _collect_source_payload_differences(
    left_sources_by_date: dict[str, dict[str, Any]],
    right_sources_by_date: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_payload_differences: list[dict[str, Any]] = []
    roster_drift_differences: list[dict[str, Any]] = []
    for trade_date in sorted(set(left_sources_by_date) | set(right_sources_by_date)):
        left_row = left_sources_by_date.get(trade_date, {})
        right_row = right_sources_by_date.get(trade_date, {})
        roster_changed = (
            list(left_row.get("selected_analysts") or []) != list(right_row.get("selected_analysts") or [])
            or str(left_row.get("analyst_roster_version") or "") != str(right_row.get("analyst_roster_version") or "")
        )
        changed = dict(left_row.get("source_summary") or {}) != dict(right_row.get("source_summary") or {}) or roster_changed
        if not changed:
            continue
        difference = {
            "trade_date": trade_date,
            "left": left_row,
            "right": right_row,
        }
        source_payload_differences.append(difference)
        if roster_changed:
            roster_drift_differences.append(difference)
    return source_payload_differences, roster_drift_differences


def _build_roster_drift_message(roster_drift_differences: list[dict[str, Any]]) -> str:
    drift_lines = [
        (
            f"{row['trade_date']}: "
            f"left roster={row['left'].get('analyst_roster_version')} analysts={row['left'].get('selected_analysts')} "
            f"vs right roster={row['right'].get('analyst_roster_version')} analysts={row['right'].get('selected_analysts')}"
        )
        for row in roster_drift_differences
    ]
    return (
        "--compare-to detected analyst roster drift between fixed artifacts. "
        "These reports are not directly comparable for BTST validation. "
        "Re-run with --allow-roster-drift only if you explicitly want a diagnostic apples-to-oranges comparison.\n"
        + "\n".join(drift_lines)
    )


def _collect_focus_differences(
    left_focus: dict[tuple[str, str], dict[str, Any]],
    right_focus: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    focus_differences: list[dict[str, Any]] = []
    for trade_date, ticker in sorted(set(left_focus) | set(right_focus)):
        left_row = left_focus.get((trade_date, ticker), {})
        right_row = right_focus.get((trade_date, ticker), {})
        changed = (
            left_row.get("candidate_source") != right_row.get("candidate_source")
            or left_row.get("stored_decision") != right_row.get("stored_decision")
            or left_row.get("replayed_decision") != right_row.get("replayed_decision")
            or left_row.get("replayed_score_target") != right_row.get("replayed_score_target")
            or list(left_row.get("replayed_blockers") or []) != list(right_row.get("replayed_blockers") or [])
        )
        if not changed:
            continue
        focus_differences.append(
            {
                "trade_date": trade_date,
                "ticker": ticker,
                "left": {
                    "candidate_source": left_row.get("candidate_source"),
                    "stored_decision": left_row.get("stored_decision"),
                    "replayed_decision": left_row.get("replayed_decision"),
                    "replayed_score_target": left_row.get("replayed_score_target"),
                    "replayed_gap_to_near_miss": left_row.get("replayed_gap_to_near_miss"),
                    "replayed_blockers": list(left_row.get("replayed_blockers") or []),
                    "replayed_top_reasons": list(left_row.get("replayed_top_reasons") or []),
                    "replay_input_path": left_row.get("replay_input_path"),
                },
                "right": {
                    "candidate_source": right_row.get("candidate_source"),
                    "stored_decision": right_row.get("stored_decision"),
                    "replayed_decision": right_row.get("replayed_decision"),
                    "replayed_score_target": right_row.get("replayed_score_target"),
                    "replayed_gap_to_near_miss": right_row.get("replayed_gap_to_near_miss"),
                    "replayed_blockers": list(right_row.get("replayed_blockers") or []),
                    "replayed_top_reasons": list(right_row.get("replayed_top_reasons") or []),
                    "replay_input_path": right_row.get("replay_input_path"),
                },
            }
        )
    return focus_differences


def _collect_mismatch_differences(
    left_mismatches: dict[tuple[str, str], dict[str, Any]],
    right_mismatches: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    mismatch_differences: list[dict[str, Any]] = []
    for trade_date, ticker in sorted(set(left_mismatches) | set(right_mismatches)):
        left_row = left_mismatches.get((trade_date, ticker), {})
        right_row = right_mismatches.get((trade_date, ticker), {})
        changed = (
            left_row.get("stored_decision") != right_row.get("stored_decision")
            or left_row.get("replayed_decision") != right_row.get("replayed_decision")
            or left_row.get("replayed_score_target") != right_row.get("replayed_score_target")
            or list(left_row.get("replayed_blockers") or []) != list(right_row.get("replayed_blockers") or [])
        )
        if not changed:
            continue
        mismatch_differences.append(
            {
                "trade_date": trade_date,
                "ticker": ticker,
                "left": {
                    "stored_decision": left_row.get("stored_decision"),
                    "replayed_decision": left_row.get("replayed_decision"),
                    "replayed_score_target": left_row.get("replayed_score_target"),
                    "replayed_gap_to_near_miss": left_row.get("replayed_gap_to_near_miss"),
                    "replayed_blockers": list(left_row.get("replayed_blockers") or []),
                    "replay_input_path": left_row.get("replay_input_path"),
                },
                "right": {
                    "stored_decision": right_row.get("stored_decision"),
                    "replayed_decision": right_row.get("replayed_decision"),
                    "replayed_score_target": right_row.get("replayed_score_target"),
                    "replayed_gap_to_near_miss": right_row.get("replayed_gap_to_near_miss"),
                    "replayed_blockers": list(right_row.get("replayed_blockers") or []),
                    "replay_input_path": right_row.get("replay_input_path"),
                },
            }
        )
    return mismatch_differences


def compare_selection_target_replay_inputs(
    input_path: str | Path,
    compare_to_path: str | Path,
    *,
    profile_name: str = "default",
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    structural_variant: str = "baseline",
    focus_tickers: list[str] | None = None,
    allow_roster_drift: bool = False,
    refresh_latest_historical_prior: bool = False,
) -> dict[str, Any]:
    left_sources = load_selection_target_replay_sources(input_path)
    right_sources = load_selection_target_replay_sources(compare_to_path)
    left_sources_by_date = _index_replay_source_payloads(left_sources)
    right_sources_by_date = _index_replay_source_payloads(right_sources)
    source_payload_differences, roster_drift_differences = _collect_source_payload_differences(left_sources_by_date, right_sources_by_date)

    if roster_drift_differences and not allow_roster_drift:
        raise SystemExit(_build_roster_drift_message(roster_drift_differences))

    left_analysis = analyze_selection_target_replay_inputs(
        input_path,
        profile_name=profile_name,
        select_threshold=select_threshold,
        near_miss_threshold=near_miss_threshold,
        structural_variant=structural_variant,
        focus_tickers=focus_tickers,
        refresh_latest_historical_prior=refresh_latest_historical_prior,
    )
    right_analysis = analyze_selection_target_replay_inputs(
        compare_to_path,
        profile_name=profile_name,
        select_threshold=select_threshold,
        near_miss_threshold=near_miss_threshold,
        structural_variant=structural_variant,
        focus_tickers=focus_tickers,
        refresh_latest_historical_prior=refresh_latest_historical_prior,
    )

    left_focus = _index_replay_rows(list(left_analysis.get("focused_score_diagnostics") or []))
    right_focus = _index_replay_rows(list(right_analysis.get("focused_score_diagnostics") or []))
    focus_differences = _collect_focus_differences(left_focus, right_focus)

    left_mismatches = _index_replay_rows(list(left_analysis.get("mismatch_examples") or []))
    right_mismatches = _index_replay_rows(list(right_analysis.get("mismatch_examples") or []))
    mismatch_differences = _collect_mismatch_differences(left_mismatches, right_mismatches)

    return {
        "profile_name": str(profile_name or "default"),
        "structural_variant": structural_variant,
        "select_threshold": left_analysis["select_threshold"],
        "near_miss_threshold": left_analysis["near_miss_threshold"],
        "focus_tickers": sorted({ticker for ticker in (focus_tickers or []) if str(ticker).strip()}),
        "left_input_path": str(Path(input_path).expanduser().resolve()),
        "right_input_path": str(Path(compare_to_path).expanduser().resolve()),
        "left_replay_input_count": int(left_analysis["replay_input_count"]),
        "right_replay_input_count": int(right_analysis["replay_input_count"]),
        "left_trade_date_count": int(left_analysis["trade_date_count"]),
        "right_trade_date_count": int(right_analysis["trade_date_count"]),
        "decision_mismatch_count_diff": {
            "left": int(left_analysis["decision_mismatch_count"]),
            "right": int(right_analysis["decision_mismatch_count"]),
            "delta": int(right_analysis["decision_mismatch_count"]) - int(left_analysis["decision_mismatch_count"]),
        },
        "stored_short_trade_decision_counts_diff": _diff_count_dict(
            dict(left_analysis.get("stored_short_trade_decision_counts") or {}),
            dict(right_analysis.get("stored_short_trade_decision_counts") or {}),
        ),
        "replayed_short_trade_decision_counts_diff": _diff_count_dict(
            dict(left_analysis.get("replayed_short_trade_decision_counts") or {}),
            dict(right_analysis.get("replayed_short_trade_decision_counts") or {}),
        ),
        "decision_transition_counts_diff": _diff_count_dict(
            dict(left_analysis.get("decision_transition_counts") or {}),
            dict(right_analysis.get("decision_transition_counts") or {}),
        ),
        "candidate_source_counts_diff": _diff_count_dict(
            dict(left_analysis.get("candidate_source_counts") or {}),
            dict(right_analysis.get("candidate_source_counts") or {}),
        ),
        "source_payload_differences": source_payload_differences,
        "focus_differences": focus_differences,
        "mismatch_differences": mismatch_differences,
        "left_analysis": left_analysis,
        "right_analysis": right_analysis,
    }


def analyze_selection_target_threshold_grid(
    input_path: str | Path,
    *,
    profile_name: str = "default",
    select_thresholds: list[float],
    near_miss_thresholds: list[float],
) -> dict[str, Any]:
    profile_defaults = _resolve_short_trade_target_profile(profile_name)
    select_values = select_thresholds or [float(profile_defaults.select_threshold)]
    near_miss_values = near_miss_thresholds or [float(profile_defaults.near_miss_threshold)]
    rows: list[dict[str, Any]] = []

    for select_threshold in select_values:
        for near_miss_threshold in near_miss_values:
            if select_threshold < near_miss_threshold:
                continue
            analysis = analyze_selection_target_replay_inputs(
                input_path,
                profile_name=profile_name,
                select_threshold=select_threshold,
                near_miss_threshold=near_miss_threshold,
                structural_variant="baseline",
            )
            stored_decisions = analysis["stored_short_trade_decision_counts"]
            row = _build_replay_summary_row(analysis)
            row.update(
                {
                    "select_threshold": round(float(select_threshold), 4),
                    "near_miss_threshold": round(float(near_miss_threshold), 4),
                    "stored_short_trade_decision_counts": dict(stored_decisions),
                }
            )
            rows.append(row)

    first_selected_row = next((row for row in rows if row["replayed_short_trade_decision_counts"].get("selected", 0) > 0), None)
    first_near_miss_row = next((row for row in rows if row["replayed_short_trade_decision_counts"].get("near_miss", 0) > 0), None)
    return {
        "profile_name": str(profile_name or "default"),
        "select_threshold_grid": [round(float(value), 4) for value in select_values],
        "near_miss_threshold_grid": [round(float(value), 4) for value in near_miss_values],
        "grid_row_count": len(rows),
        "rows": rows,
        "first_row_with_selected": first_selected_row,
        "first_row_with_near_miss": first_near_miss_row,
    }


def analyze_selection_target_structural_variants(
    input_path: str | Path,
    *,
    profile_name: str = "default",
    structural_variants: list[str],
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    focus_tickers: list[str] | None = None,
) -> dict[str, Any]:
    variant_names = structural_variants or ["baseline"]
    rows: list[dict[str, Any]] = []
    for variant_name in variant_names:
        analysis = analyze_selection_target_replay_inputs(
            input_path,
            profile_name=profile_name,
            select_threshold=select_threshold,
            near_miss_threshold=near_miss_threshold,
            structural_variant=variant_name,
            focus_tickers=focus_tickers,
        )
        row = _build_replay_summary_row(analysis, structural_variant=variant_name)
        row["promoted_to_near_miss"] = [example["ticker"] for example in analysis["mismatch_examples"] if example["replayed_decision"] == "near_miss"]
        row["analysis"] = analysis
        rows.append(row)

    first_unblocked_row = next((row for row in rows if row["released_from_blocked"]), None)
    profile_defaults = _resolve_short_trade_target_profile(profile_name)
    return {
        "profile_name": str(profile_name or "default"),
        "select_threshold": float(select_threshold) if select_threshold is not None else float(profile_defaults.select_threshold),
        "near_miss_threshold": float(near_miss_threshold) if near_miss_threshold is not None else float(profile_defaults.near_miss_threshold),
        "structural_variants": variant_names,
        "variant_row_count": len(rows),
        "rows": rows,
        "first_row_releasing_blocked": first_unblocked_row,
    }


def analyze_selection_target_combination_grid(
    input_path: str | Path,
    *,
    profile_name: str = "default",
    structural_variants: list[str],
    select_thresholds: list[float],
    near_miss_thresholds: list[float],
) -> dict[str, Any]:
    variant_names = structural_variants or ["baseline"]
    profile_defaults = _resolve_short_trade_target_profile(profile_name)
    select_values = select_thresholds or [float(profile_defaults.select_threshold)]
    near_miss_values = near_miss_thresholds or [float(profile_defaults.near_miss_threshold)]
    rows: list[dict[str, Any]] = []

    for variant_name in variant_names:
        for select_threshold in select_values:
            for near_miss_threshold in near_miss_values:
                if select_threshold < near_miss_threshold:
                    continue
                analysis = analyze_selection_target_replay_inputs(
                    input_path,
                    profile_name=profile_name,
                    select_threshold=select_threshold,
                    near_miss_threshold=near_miss_threshold,
                    structural_variant=variant_name,
                )
                stored_decisions = analysis["stored_short_trade_decision_counts"]
                row = _build_replay_summary_row(analysis, structural_variant=variant_name)
                row.update(
                    {
                        "select_threshold": round(float(select_threshold), 4),
                        "near_miss_threshold": round(float(near_miss_threshold), 4),
                        "stored_short_trade_decision_counts": dict(stored_decisions),
                    }
                )
                rows.append(row)

    first_selected_row = next((row for row in rows if row["replayed_short_trade_decision_counts"].get("selected", 0) > 0), None)
    first_near_miss_row = next((row for row in rows if row["replayed_short_trade_decision_counts"].get("near_miss", 0) > 0), None)
    first_unblocked_row = next((row for row in rows if row["released_from_blocked"]), None)
    first_blocked_near_miss_row = next((row for row in rows if row["blocked_to_near_miss"]), None)
    first_blocked_selected_row = next((row for row in rows if row["blocked_to_selected"]), None)
    return {
        "profile_name": str(profile_name or "default"),
        "structural_variants": variant_names,
        "select_threshold_grid": [round(float(value), 4) for value in select_values],
        "near_miss_threshold_grid": [round(float(value), 4) for value in near_miss_values],
        "grid_row_count": len(rows),
        "rows": rows,
        "first_row_with_selected": first_selected_row,
        "first_row_with_near_miss": first_near_miss_row,
        "first_row_releasing_blocked": first_unblocked_row,
        "first_row_blocked_to_near_miss": first_blocked_near_miss_row,
        "first_row_blocked_to_selected": first_blocked_selected_row,
    }


def analyze_selection_target_candidate_entry_metric_grid(
    input_path: str | Path,
    *,
    profile_name: str = "default",
    breakout_freshness_max_values: list[float | None] | None,
    trend_acceleration_max_values: list[float | None] | None = None,
    volume_expansion_quality_max_values: list[float | None] | None,
    close_strength_max_values: list[float | None] | None = None,
    catalyst_freshness_max_values: list[float | None] | None,
    base_structural_variants: list[str] | None = None,
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    focus_tickers: list[str] | None = None,
    preserve_tickers: list[str] | None = None,
) -> dict[str, Any]:
    breakout_values = [None] if breakout_freshness_max_values == [] else list(breakout_freshness_max_values or [0.05])
    trend_values = list(trend_acceleration_max_values or []) or [None]
    volume_values = [None] if volume_expansion_quality_max_values == [] else list(volume_expansion_quality_max_values or [0.05])
    close_values = list(close_strength_max_values or []) or [None]
    catalyst_values = [None] if catalyst_freshness_max_values == [] else list(catalyst_freshness_max_values or [0.05])
    variant_names = base_structural_variants or ["baseline"]
    profile_defaults = _resolve_short_trade_target_profile(profile_name)
    rows: list[dict[str, Any]] = []
    focus_ticker_set = [ticker for ticker in (focus_tickers or []) if str(ticker).strip()]
    preserve_ticker_set = [ticker for ticker in (preserve_tickers or []) if str(ticker).strip()]

    for variant_name in variant_names:
        for breakout_max in breakout_values:
            for trend_max in trend_values:
                for volume_max in volume_values:
                    for close_max in close_values:
                        for catalyst_max in catalyst_values:
                            analysis = analyze_selection_target_replay_inputs(
                                input_path,
                                profile_name=profile_name,
                                select_threshold=select_threshold,
                                near_miss_threshold=near_miss_threshold,
                                structural_variant=variant_name,
                                structural_overrides={
                                    "exclude_candidate_entries": [
                                        _build_watchlist_avoid_weak_structure_filter(
                                            breakout_freshness_max=breakout_max,
                                            trend_acceleration_max=trend_max,
                                            volume_expansion_quality_max=volume_max,
                                            close_strength_max=close_max,
                                            catalyst_freshness_max=catalyst_max,
                                        )
                                    ]
                                },
                                focus_tickers=sorted(set(focus_ticker_set) | set(preserve_ticker_set)),
                            )
                            diagnostics_by_ticker = {
                                str(diagnostic.get("ticker") or ""): diagnostic
                                for diagnostic in list(analysis.get("focused_score_diagnostics") or [])
                                if str(diagnostic.get("ticker") or "").strip()
                            }
                            threshold_adjustment_cost = round(
                                sum(
                                    float(value)
                                    for value in [breakout_max, trend_max, volume_max, close_max, catalyst_max]
                                    if value is not None
                                ),
                                4,
                            )
                            row = _build_replay_summary_row(analysis, structural_variant=variant_name)
                            row.update(
                                {
                                    "breakout_freshness_max": None if breakout_max is None else round(float(breakout_max), 4),
                                    "trend_acceleration_max": None if trend_max is None else round(float(trend_max), 4),
                                    "volume_expansion_quality_max": None if volume_max is None else round(float(volume_max), 4),
                                    "close_strength_max": None if close_max is None else round(float(close_max), 4),
                                    "catalyst_freshness_max": None if catalyst_max is None else round(float(catalyst_max), 4),
                                    "threshold_adjustment_cost": threshold_adjustment_cost,
                                    "focus_filtered": {
                                        ticker: bool(diagnostics_by_ticker.get(ticker, {}).get("filtered_candidate_entry"))
                                        for ticker in focus_ticker_set
                                        if ticker in diagnostics_by_ticker
                                    },
                                    "preserve_filtered": {
                                        ticker: bool(diagnostics_by_ticker.get(ticker, {}).get("filtered_candidate_entry"))
                                        for ticker in preserve_ticker_set
                                        if ticker in diagnostics_by_ticker
                                    },
                                    "filtered_candidate_entry_counts": dict(analysis.get("filtered_candidate_entry_counts") or {}),
                                    "analysis": analysis,
                                }
                            )
                            rows.append(row)

    first_row_filtering_any = next((row for row in rows if sum(int(value) for value in dict(row.get("filtered_candidate_entry_counts") or {}).values()) > 0), None)
    first_row_filtering_subset = next(
        (
            row
            for row in rows
            if 0 < sum(int(value) for value in dict(row.get("filtered_candidate_entry_counts") or {}).values()) < sum(int(value) for value in dict(row.get("analysis", {}).get("filtered_candidate_entry_counts") or {}).values()) + row["replayed_short_trade_decision_counts"].get("none", 0) + row["replayed_short_trade_decision_counts"].get("blocked", 0)
        ),
        None,
    )
    first_focus_filtered_rows: dict[str, dict[str, Any]] = {}
    first_focus_filtered_preserving_rows: dict[str, dict[str, Any]] = {}
    for ticker in focus_ticker_set:
        filtered_rows = [row for row in rows if row.get("focus_filtered", {}).get(ticker) is True]
        if filtered_rows:
            first_focus_filtered_rows[ticker] = min(
                filtered_rows,
                key=lambda row: (
                    float(row.get("threshold_adjustment_cost") or 0.0),
                    int(sum(int(value) for value in dict(row.get("filtered_candidate_entry_counts") or {}).values())),
                ),
            )
            preserving_rows = [
                row
                for row in filtered_rows
                if not any(bool(row.get("preserve_filtered", {}).get(preserved_ticker)) for preserved_ticker in preserve_ticker_set)
            ]
            if preserving_rows:
                first_focus_filtered_preserving_rows[ticker] = min(
                    preserving_rows,
                    key=lambda row: (
                        float(row.get("threshold_adjustment_cost") or 0.0),
                        int(sum(int(value) for value in dict(row.get("filtered_candidate_entry_counts") or {}).values())),
                    ),
                )
    return {
        "profile_name": str(profile_name or "default"),
        "base_structural_variants": variant_names,
        "breakout_freshness_max_grid": [round(float(value), 4) for value in breakout_values if value is not None],
        "trend_acceleration_max_grid": [round(float(value), 4) for value in trend_values if value is not None],
        "volume_expansion_quality_max_grid": [round(float(value), 4) for value in volume_values if value is not None],
        "close_strength_max_grid": [round(float(value), 4) for value in close_values if value is not None],
        "catalyst_freshness_max_grid": [round(float(value), 4) for value in catalyst_values if value is not None],
        "select_threshold": float(select_threshold) if select_threshold is not None else float(profile_defaults.select_threshold),
        "near_miss_threshold": float(near_miss_threshold) if near_miss_threshold is not None else float(profile_defaults.near_miss_threshold),
        "focus_tickers": focus_ticker_set,
        "preserve_tickers": preserve_ticker_set,
        "grid_row_count": len(rows),
        "rows": rows,
        "first_row_filtering_any": first_row_filtering_any,
        "first_row_filtering_subset": first_row_filtering_subset,
        "first_focus_filtered_rows": first_focus_filtered_rows,
        "first_focus_filtered_preserving_rows": first_focus_filtered_preserving_rows,
    }


def analyze_selection_target_penalty_grid(
    input_path: str | Path,
    *,
    profile_name: str = "default",
    avoid_penalty_values: list[float],
    stale_score_penalty_weight_values: list[float],
    extension_score_penalty_weight_values: list[float],
    base_structural_variants: list[str] | None = None,
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    focus_tickers: list[str] | None = None,
) -> dict[str, Any]:
    variant_names = base_structural_variants or ["baseline"]
    profile_defaults = _resolve_short_trade_target_profile(profile_name)
    avoid_values = avoid_penalty_values or [float(profile_defaults.layer_c_avoid_penalty)]
    stale_values = stale_score_penalty_weight_values or [float(profile_defaults.stale_score_penalty_weight)]
    extension_values = extension_score_penalty_weight_values or [float(profile_defaults.extension_score_penalty_weight)]
    rows: list[dict[str, Any]] = []
    focus_ticker_set = [ticker for ticker in (focus_tickers or []) if str(ticker).strip()]

    for variant_name in variant_names:
        for avoid_penalty in avoid_values:
            for stale_weight in stale_values:
                for extension_weight in extension_values:
                    analysis = analyze_selection_target_replay_inputs(
                        input_path,
                        profile_name=profile_name,
                        select_threshold=select_threshold,
                        near_miss_threshold=near_miss_threshold,
                        structural_variant=variant_name,
                        structural_overrides={
                            "layer_c_avoid_penalty": float(avoid_penalty),
                            "stale_score_penalty_weight": float(stale_weight),
                            "extension_score_penalty_weight": float(extension_weight),
                        },
                        focus_tickers=focus_tickers,
                    )
                    row = _build_replay_summary_row(analysis, structural_variant=variant_name)
                    focused_diagnostics = list(analysis.get("focused_score_diagnostics") or [])
                    focus_by_ticker = {str(item.get("ticker") or ""): item for item in focused_diagnostics if str(item.get("ticker") or "").strip()}
                    row.update(
                        {
                            "layer_c_avoid_penalty": round(float(avoid_penalty), 4),
                            "stale_score_penalty_weight": round(float(stale_weight), 4),
                            "extension_score_penalty_weight": round(float(extension_weight), 4),
                            "analysis": analysis,
                            "focus_scores": {
                                ticker: focus_by_ticker[ticker].get("replayed_score_target")
                                for ticker in focus_ticker_set
                                if ticker in focus_by_ticker
                            },
                            "focus_gaps_to_near_miss": {
                                ticker: focus_by_ticker[ticker].get("replayed_gap_to_near_miss")
                                for ticker in focus_ticker_set
                                if ticker in focus_by_ticker
                            },
                            "focus_decisions": {
                                ticker: focus_by_ticker[ticker].get("replayed_decision")
                                for ticker in focus_ticker_set
                                if ticker in focus_by_ticker
                            },
                        }
                    )
                    rows.append(row)

    best_focus_rows: dict[str, dict[str, Any]] = {}
    first_focus_near_miss_rows: dict[str, dict[str, Any]] = {}
    for ticker in focus_ticker_set:
        ticker_rows = [row for row in rows if ticker in dict(row.get("focus_scores") or {})]
        if ticker_rows:
            best_focus_rows[ticker] = max(
                ticker_rows,
                key=lambda row: (
                    float("-inf") if row["focus_scores"].get(ticker) is None else float(row["focus_scores"][ticker]),
                    -float(row["layer_c_avoid_penalty"]),
                    -float(row["stale_score_penalty_weight"]),
                    -float(row["extension_score_penalty_weight"]),
                ),
            )
            qualifying_rows = [
                row
                for row in ticker_rows
                if row["focus_decisions"].get(ticker) in {"near_miss", "selected"}
            ]
            if qualifying_rows:
                first_focus_near_miss_rows[ticker] = min(
                    qualifying_rows,
                    key=lambda row: (
                        float(profile_defaults.layer_c_avoid_penalty) - float(row["layer_c_avoid_penalty"])
                        + float(profile_defaults.stale_score_penalty_weight) - float(row["stale_score_penalty_weight"])
                        + float(profile_defaults.extension_score_penalty_weight) - float(row["extension_score_penalty_weight"]),
                        float("inf") if row["focus_gaps_to_near_miss"].get(ticker) is None else abs(float(row["focus_gaps_to_near_miss"][ticker])),
                    ),
                )

    return {
        "profile_name": str(profile_name or "default"),
        "base_structural_variants": variant_names,
        "layer_c_avoid_penalty_grid": [round(float(value), 4) for value in avoid_values],
        "stale_score_penalty_weight_grid": [round(float(value), 4) for value in stale_values],
        "extension_score_penalty_weight_grid": [round(float(value), 4) for value in extension_values],
        "select_threshold": float(select_threshold) if select_threshold is not None else float(profile_defaults.select_threshold),
        "near_miss_threshold": float(near_miss_threshold) if near_miss_threshold is not None else float(profile_defaults.near_miss_threshold),
        "focus_tickers": focus_ticker_set,
        "grid_row_count": len(rows),
        "rows": rows,
        "best_focus_rows": best_focus_rows,
        "first_focus_near_miss_rows": first_focus_near_miss_rows,
    }


def _resolve_penalty_threshold_grid_defaults(
    *,
    profile_name: str,
    avoid_penalty_values: list[float],
    stale_score_penalty_weight_values: list[float],
    extension_score_penalty_weight_values: list[float],
    select_thresholds: list[float],
    near_miss_thresholds: list[float],
) -> dict[str, list[float] | float]:
    default_profile = _resolve_short_trade_target_profile(profile_name)
    return {
        "avoid_values": avoid_penalty_values or [float(default_profile.layer_c_avoid_penalty)],
        "stale_values": stale_score_penalty_weight_values or [float(default_profile.stale_score_penalty_weight)],
        "extension_values": extension_score_penalty_weight_values or [float(default_profile.extension_score_penalty_weight)],
        "select_values": select_thresholds or [float(default_profile.select_threshold)],
        "near_miss_values": near_miss_thresholds or [float(default_profile.near_miss_threshold)],
        "default_avoid_penalty": float(default_profile.layer_c_avoid_penalty),
        "default_stale_weight": float(default_profile.stale_score_penalty_weight),
        "default_extension_weight": float(default_profile.extension_score_penalty_weight),
        "default_select_threshold": float(default_profile.select_threshold),
        "default_near_miss_threshold": float(default_profile.near_miss_threshold),
    }


def _build_penalty_threshold_grid_row(
    *,
    input_path: str | Path,
    profile_name: str,
    variant_name: str,
    avoid_penalty: float,
    stale_weight: float,
    extension_weight: float,
    select_threshold: float,
    near_miss_threshold: float,
    focus_tickers: list[str] | None,
    focus_ticker_set: list[str],
    defaults: dict[str, list[float] | float],
) -> dict[str, Any]:
    analysis = analyze_selection_target_replay_inputs(
        input_path,
        profile_name=profile_name,
        select_threshold=select_threshold,
        near_miss_threshold=near_miss_threshold,
        structural_variant=variant_name,
        structural_overrides={
            "layer_c_avoid_penalty": float(avoid_penalty),
            "stale_score_penalty_weight": float(stale_weight),
            "extension_score_penalty_weight": float(extension_weight),
        },
        focus_tickers=focus_tickers,
    )
    row = _build_replay_summary_row(analysis, structural_variant=variant_name)
    focused_diagnostics = list(analysis.get("focused_score_diagnostics") or [])
    focus_by_ticker = {str(item.get("ticker") or ""): item for item in focused_diagnostics if str(item.get("ticker") or "").strip()}
    adjustment_cost = round(
        (float(defaults["default_avoid_penalty"]) - float(avoid_penalty))
        + (float(defaults["default_stale_weight"]) - float(stale_weight))
        + (float(defaults["default_extension_weight"]) - float(extension_weight))
        + (float(defaults["default_select_threshold"]) - float(select_threshold))
        + (float(defaults["default_near_miss_threshold"]) - float(near_miss_threshold)),
        4,
    )
    row.update(
        {
            "layer_c_avoid_penalty": round(float(avoid_penalty), 4),
            "stale_score_penalty_weight": round(float(stale_weight), 4),
            "extension_score_penalty_weight": round(float(extension_weight), 4),
            "select_threshold": round(float(select_threshold), 4),
            "near_miss_threshold": round(float(near_miss_threshold), 4),
            "adjustment_cost": adjustment_cost,
            "analysis": analysis,
            "focus_scores": {ticker: focus_by_ticker[ticker].get("replayed_score_target") for ticker in focus_ticker_set if ticker in focus_by_ticker},
            "focus_gaps_to_near_miss": {ticker: focus_by_ticker[ticker].get("replayed_gap_to_near_miss") for ticker in focus_ticker_set if ticker in focus_by_ticker},
            "focus_decisions": {ticker: focus_by_ticker[ticker].get("replayed_decision") for ticker in focus_ticker_set if ticker in focus_by_ticker},
        }
    )
    return row


def _select_penalty_threshold_focus_rows(rows: list[dict[str, Any]], focus_ticker_set: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    first_focus_near_miss_rows: dict[str, dict[str, Any]] = {}
    first_focus_selected_rows: dict[str, dict[str, Any]] = {}
    for ticker in focus_ticker_set:
        ticker_rows = [row for row in rows if ticker in dict(row.get("focus_decisions") or {})]
        near_miss_rows = [row for row in ticker_rows if row["focus_decisions"].get(ticker) in {"near_miss", "selected"}]
        selected_rows = [row for row in ticker_rows if row["focus_decisions"].get(ticker) == "selected"]
        if near_miss_rows:
            first_focus_near_miss_rows[ticker] = min(
                near_miss_rows,
                key=lambda row: (
                    float(row["adjustment_cost"]),
                    float("inf") if row["focus_gaps_to_near_miss"].get(ticker) is None else abs(float(row["focus_gaps_to_near_miss"][ticker])),
                    -float(row["focus_scores"].get(ticker) or float("-inf")),
                ),
            )
        if selected_rows:
            first_focus_selected_rows[ticker] = min(
                selected_rows,
                key=lambda row: (
                    float(row["adjustment_cost"]),
                    -float(row["focus_scores"].get(ticker) or float("-inf")),
                ),
            )
    return first_focus_near_miss_rows, first_focus_selected_rows


def analyze_selection_target_penalty_threshold_grid(
    input_path: str | Path,
    *,
    profile_name: str = "default",
    avoid_penalty_values: list[float],
    stale_score_penalty_weight_values: list[float],
    extension_score_penalty_weight_values: list[float],
    select_thresholds: list[float],
    near_miss_thresholds: list[float],
    base_structural_variants: list[str] | None = None,
    focus_tickers: list[str] | None = None,
) -> dict[str, Any]:
    variant_names = base_structural_variants or ["baseline"]
    defaults = _resolve_penalty_threshold_grid_defaults(
        profile_name=profile_name,
        avoid_penalty_values=avoid_penalty_values,
        stale_score_penalty_weight_values=stale_score_penalty_weight_values,
        extension_score_penalty_weight_values=extension_score_penalty_weight_values,
        select_thresholds=select_thresholds,
        near_miss_thresholds=near_miss_thresholds,
    )
    avoid_values = list(cast(list[float], defaults["avoid_values"]))
    stale_values = list(cast(list[float], defaults["stale_values"]))
    extension_values = list(cast(list[float], defaults["extension_values"]))
    select_values = list(cast(list[float], defaults["select_values"]))
    near_miss_values = list(cast(list[float], defaults["near_miss_values"]))
    focus_ticker_set = [ticker for ticker in (focus_tickers or []) if str(ticker).strip()]
    rows: list[dict[str, Any]] = []

    for variant_name in variant_names:
        for avoid_penalty in avoid_values:
            for stale_weight in stale_values:
                for extension_weight in extension_values:
                    for select_threshold in select_values:
                        for near_miss_threshold in near_miss_values:
                            if float(select_threshold) < float(near_miss_threshold):
                                continue
                            rows.append(
                                _build_penalty_threshold_grid_row(
                                    input_path=input_path,
                                    profile_name=profile_name,
                                    variant_name=variant_name,
                                    avoid_penalty=avoid_penalty,
                                    stale_weight=stale_weight,
                                    extension_weight=extension_weight,
                                    select_threshold=select_threshold,
                                    near_miss_threshold=near_miss_threshold,
                                    focus_tickers=focus_tickers,
                                    focus_ticker_set=focus_ticker_set,
                                    defaults=defaults,
                                )
                            )
    first_focus_near_miss_rows, first_focus_selected_rows = _select_penalty_threshold_focus_rows(rows, focus_ticker_set)

    return {
        "profile_name": str(profile_name or "default"),
        "base_structural_variants": variant_names,
        "layer_c_avoid_penalty_grid": [round(float(value), 4) for value in avoid_values],
        "stale_score_penalty_weight_grid": [round(float(value), 4) for value in stale_values],
        "extension_score_penalty_weight_grid": [round(float(value), 4) for value in extension_values],
        "select_threshold_grid": [round(float(value), 4) for value in select_values],
        "near_miss_threshold_grid": [round(float(value), 4) for value in near_miss_values],
        "focus_tickers": focus_ticker_set,
        "grid_row_count": len(rows),
        "rows": rows,
        "first_focus_near_miss_rows": first_focus_near_miss_rows,
        "first_focus_selected_rows": first_focus_selected_rows,
    }


def render_selection_target_replay_markdown(analysis: dict[str, Any]) -> str:
    lines = ["# Selection Target Replay Calibration", ""]
    lines.append(f"- profile_name: {analysis['profile_name']}")
    lines.append(f"- replay_input_count: {analysis['replay_input_count']}")
    lines.append(f"- trade_date_count: {analysis['trade_date_count']}")
    lines.append(f"- select_threshold: {analysis['select_threshold']}")
    lines.append(f"- near_miss_threshold: {analysis['near_miss_threshold']}")
    lines.append(f"- decision_mismatch_count: {analysis['decision_mismatch_count']}")
    lines.append(f"- stored_short_trade_decision_counts: {analysis['stored_short_trade_decision_counts']}")
    lines.append(f"- replayed_short_trade_decision_counts: {analysis['replayed_short_trade_decision_counts']}")
    lines.append(f"- decision_transition_counts: {analysis['decision_transition_counts']}")
    lines.append(f"- candidate_source_counts: {analysis['candidate_source_counts']}")
    lines.append(f"- entry_filter_rules: {analysis['entry_filter_rules']}")
    lines.append(f"- filtered_candidate_entry_counts: {analysis['filtered_candidate_entry_counts']}")
    lines.append(f"- signal_availability: {analysis['signal_availability']}")
    lines.append(f"- available_strategy_signal_counts: {analysis['available_strategy_signal_counts']}")
    lines.append("")
    lines.append("## By Trade Date")
    for row in analysis["by_trade_date"]:
        lines.append(
            f"- {row['trade_date']}: mismatches={row['decision_mismatch_count']}, stored={row['stored_short_trade_decision_counts']}, replayed={row['replayed_short_trade_decision_counts']}"
        )
    lines.append("")
    lines.append("## Mismatch Examples")
    if analysis["mismatch_examples"]:
        for example in analysis["mismatch_examples"]:
            lines.append(
                f"- {example['trade_date']} {example['ticker']}: {example['stored_decision']} -> {example['replayed_decision']}, replayed_score={example['replayed_score_target']}, gap_to_near_miss={example['replayed_gap_to_near_miss']}, gap_to_selected={example['replayed_gap_to_selected']}, replayed_blockers={example['replayed_blockers']}"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Focused Score Diagnostics")
    if analysis["focused_score_diagnostics"]:
        for row in analysis["focused_score_diagnostics"]:
            lines.append(
                f"- {row['trade_date']} {row['ticker']}: source={row['candidate_source']}, reasons={row['candidate_reason_codes']}, filtered={row['filtered_candidate_entry']}, filter_rule={row['filtered_candidate_entry_rule']}, {row['stored_decision']} -> {row['replayed_decision']}, replayed_score={row['replayed_score_target']}, gap_to_near_miss={row['replayed_gap_to_near_miss']}, positive={row['replayed_total_positive_contribution']}, negative={row['replayed_total_negative_contribution']}, top_reasons={row['replayed_top_reasons']}"
            )
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def render_selection_target_replay_comparison_markdown(comparison: dict[str, Any]) -> str:
    lines = ["# Selection Target Replay Comparison", ""]
    lines.append(f"- profile_name: {comparison['profile_name']}")
    lines.append(f"- structural_variant: {comparison['structural_variant']}")
    lines.append(f"- select_threshold: {comparison['select_threshold']}")
    lines.append(f"- near_miss_threshold: {comparison['near_miss_threshold']}")
    lines.append(f"- left_input_path: {comparison['left_input_path']}")
    lines.append(f"- right_input_path: {comparison['right_input_path']}")
    lines.append(f"- decision_mismatch_count_diff: {comparison['decision_mismatch_count_diff']}")
    lines.append(f"- stored_short_trade_decision_counts_diff: {comparison['stored_short_trade_decision_counts_diff']}")
    lines.append(f"- replayed_short_trade_decision_counts_diff: {comparison['replayed_short_trade_decision_counts_diff']}")
    lines.append(f"- decision_transition_counts_diff: {comparison['decision_transition_counts_diff']}")
    lines.append(f"- candidate_source_counts_diff: {comparison['candidate_source_counts_diff']}")
    lines.append("")
    lines.append("## Source Payload Differences")
    if comparison["source_payload_differences"]:
        for row in comparison["source_payload_differences"]:
            lines.append(
                f"- {row['trade_date']}: left(source_summary={row['left'].get('source_summary')}, roster={row['left'].get('analyst_roster_version')}, analysts={row['left'].get('selected_analysts')}) -> right(source_summary={row['right'].get('source_summary')}, roster={row['right'].get('analyst_roster_version')}, analysts={row['right'].get('selected_analysts')})"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Focus Differences")
    if comparison["focus_differences"]:
        for row in comparison["focus_differences"]:
            lines.append(
                f"- {row['trade_date']} {row['ticker']}: left(source={row['left']['candidate_source']}, stored={row['left']['stored_decision']}, replayed={row['left']['replayed_decision']}, score={row['left']['replayed_score_target']}, blockers={row['left']['replayed_blockers']}) -> right(source={row['right']['candidate_source']}, stored={row['right']['stored_decision']}, replayed={row['right']['replayed_decision']}, score={row['right']['replayed_score_target']}, blockers={row['right']['replayed_blockers']})"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Mismatch Differences")
    if comparison["mismatch_differences"]:
        for row in comparison["mismatch_differences"]:
            lines.append(
                f"- {row['trade_date']} {row['ticker']}: left({row['left']['stored_decision']} -> {row['left']['replayed_decision']}, score={row['left']['replayed_score_target']}, blockers={row['left']['replayed_blockers']}) -> right({row['right']['stored_decision']} -> {row['right']['replayed_decision']}, score={row['right']['replayed_score_target']}, blockers={row['right']['replayed_blockers']})"
            )
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def render_selection_target_threshold_grid_markdown(grid_analysis: dict[str, Any]) -> str:
    lines = ["# Selection Target Threshold Grid", ""]
    lines.append(f"- profile_name: {grid_analysis['profile_name']}")
    lines.append(f"- select_threshold_grid: {grid_analysis['select_threshold_grid']}")
    lines.append(f"- near_miss_threshold_grid: {grid_analysis['near_miss_threshold_grid']}")
    lines.append(f"- grid_row_count: {grid_analysis['grid_row_count']}")
    lines.append(f"- first_row_with_selected: {grid_analysis['first_row_with_selected']}")
    lines.append(f"- first_row_with_near_miss: {grid_analysis['first_row_with_near_miss']}")
    lines.append("")
    lines.append("## Grid Rows")
    for row in grid_analysis["rows"]:
        lines.append(
            f"- select={row['select_threshold']}, near_miss={row['near_miss_threshold']}, mismatches={row['decision_mismatch_count']}, replayed={row['replayed_short_trade_decision_counts']}, promoted_to_selected={row['promoted_to_selected']}, promoted_to_near_miss={row['promoted_to_near_miss']}"
        )
    return "\n".join(lines) + "\n"


def render_selection_target_structural_variants_markdown(variant_analysis: dict[str, Any]) -> str:
    lines = ["# Selection Target Structural Variants", ""]
    lines.append(f"- profile_name: {variant_analysis['profile_name']}")
    lines.append(f"- select_threshold: {variant_analysis['select_threshold']}")
    lines.append(f"- near_miss_threshold: {variant_analysis['near_miss_threshold']}")
    lines.append(f"- structural_variants: {variant_analysis['structural_variants']}")
    lines.append(f"- variant_row_count: {variant_analysis['variant_row_count']}")
    lines.append(f"- first_row_releasing_blocked: {variant_analysis['first_row_releasing_blocked']}")
    lines.append("")
    lines.append("## Variant Rows")
    for row in variant_analysis["rows"]:
        lines.append(
            f"- variant={row['structural_variant']}, mismatches={row['decision_mismatch_count']}, replayed={row['replayed_short_trade_decision_counts']}, released_from_blocked={row['released_from_blocked']}, promoted_to_selected={row['promoted_to_selected']}, promoted_to_near_miss={row['promoted_to_near_miss']}"
        )
        analysis = dict(row.get("analysis") or {})
        focused_score_diagnostics = list(analysis.get("focused_score_diagnostics") or [])
        for diagnostic in focused_score_diagnostics:
            lines.append(
                f"  - focus {diagnostic['trade_date']} {diagnostic['ticker']}: source={diagnostic['candidate_source']}, reasons={diagnostic['candidate_reason_codes']}, score={diagnostic['replayed_score_target']}, gap_to_near_miss={diagnostic['replayed_gap_to_near_miss']}, positive={diagnostic['replayed_total_positive_contribution']}, negative={diagnostic['replayed_total_negative_contribution']}, blockers={diagnostic['replayed_blockers']}"
            )
    return "\n".join(lines) + "\n"


def render_selection_target_combination_grid_markdown(grid_analysis: dict[str, Any]) -> str:
    lines = ["# Selection Target Structural + Threshold Grid", ""]
    lines.append(f"- profile_name: {grid_analysis['profile_name']}")
    lines.append(f"- structural_variants: {grid_analysis['structural_variants']}")
    lines.append(f"- select_threshold_grid: {grid_analysis['select_threshold_grid']}")
    lines.append(f"- near_miss_threshold_grid: {grid_analysis['near_miss_threshold_grid']}")
    lines.append(f"- grid_row_count: {grid_analysis['grid_row_count']}")
    lines.append(f"- first_row_releasing_blocked: {grid_analysis['first_row_releasing_blocked']}")
    lines.append(f"- first_row_blocked_to_near_miss: {grid_analysis['first_row_blocked_to_near_miss']}")
    lines.append(f"- first_row_blocked_to_selected: {grid_analysis['first_row_blocked_to_selected']}")
    lines.append("")
    lines.append("## Grid Rows")
    for row in grid_analysis["rows"]:
        lines.append(
            f"- variant={row['structural_variant']}, select={row['select_threshold']}, near_miss={row['near_miss_threshold']}, mismatches={row['decision_mismatch_count']}, replayed={row['replayed_short_trade_decision_counts']}, released_from_blocked={row['released_from_blocked']}, blocked_to_near_miss={row['blocked_to_near_miss']}, blocked_to_selected={row['blocked_to_selected']}, promoted_to_selected={row['promoted_to_selected']}, promoted_to_near_miss={row['promoted_to_near_miss']}"
        )
    return "\n".join(lines) + "\n"


def render_selection_target_candidate_entry_metric_grid_markdown(grid_analysis: dict[str, Any]) -> str:
    lines = ["# Selection Target Candidate Entry Metric Grid", ""]
    lines.append(f"- profile_name: {grid_analysis['profile_name']}")
    lines.append(f"- base_structural_variants: {grid_analysis['base_structural_variants']}")
    lines.append(f"- breakout_freshness_max_grid: {grid_analysis['breakout_freshness_max_grid']}")
    lines.append(f"- trend_acceleration_max_grid: {grid_analysis['trend_acceleration_max_grid']}")
    lines.append(f"- volume_expansion_quality_max_grid: {grid_analysis['volume_expansion_quality_max_grid']}")
    lines.append(f"- close_strength_max_grid: {grid_analysis['close_strength_max_grid']}")
    lines.append(f"- catalyst_freshness_max_grid: {grid_analysis['catalyst_freshness_max_grid']}")
    lines.append(f"- select_threshold: {grid_analysis['select_threshold']}")
    lines.append(f"- near_miss_threshold: {grid_analysis['near_miss_threshold']}")
    lines.append(f"- focus_tickers: {grid_analysis['focus_tickers']}")
    lines.append(f"- preserve_tickers: {grid_analysis['preserve_tickers']}")
    lines.append(f"- grid_row_count: {grid_analysis['grid_row_count']}")
    lines.append(f"- first_row_filtering_any: {grid_analysis['first_row_filtering_any']}")
    lines.append(f"- first_row_filtering_subset: {grid_analysis['first_row_filtering_subset']}")
    lines.append(f"- first_focus_filtered_rows: {grid_analysis['first_focus_filtered_rows']}")
    lines.append(f"- first_focus_filtered_preserving_rows: {grid_analysis['first_focus_filtered_preserving_rows']}")
    lines.append("")
    lines.append("## Grid Rows")
    for row in grid_analysis["rows"]:
        lines.append(
            f"- variant={row['structural_variant']}, breakout_max={row['breakout_freshness_max']}, trend_max={row['trend_acceleration_max']}, volume_max={row['volume_expansion_quality_max']}, close_max={row['close_strength_max']}, catalyst_max={row['catalyst_freshness_max']}, cost={row['threshold_adjustment_cost']}, focus_filtered={row['focus_filtered']}, preserve_filtered={row['preserve_filtered']}, mismatches={row['decision_mismatch_count']}, eligibility={row['candidate_entry_filter_observability']}, filtered={row['filtered_candidate_entry_counts']}, replayed={row['replayed_short_trade_decision_counts']}, released_from_blocked={row['released_from_blocked']}"
        )
        analysis = dict(row.get("analysis") or {})
        focused_score_diagnostics = list(analysis.get("focused_score_diagnostics") or [])
        for diagnostic in focused_score_diagnostics:
            lines.append(
                f"  - focus {diagnostic['trade_date']} {diagnostic['ticker']}: filtered={diagnostic['filtered_candidate_entry']}, filter_rule={diagnostic['filtered_candidate_entry_rule']}, metrics={diagnostic['filtered_candidate_entry_metrics']}, replayed_score={diagnostic['replayed_score_target']}, blockers={diagnostic['replayed_blockers']}"
            )
    return "\n".join(lines) + "\n"


def render_selection_target_penalty_grid_markdown(grid_analysis: dict[str, Any]) -> str:
    lines = ["# Selection Target Penalty Frontier Grid", ""]
    lines.append(f"- profile_name: {grid_analysis['profile_name']}")
    lines.append(f"- base_structural_variants: {grid_analysis['base_structural_variants']}")
    lines.append(f"- layer_c_avoid_penalty_grid: {grid_analysis['layer_c_avoid_penalty_grid']}")
    lines.append(f"- stale_score_penalty_weight_grid: {grid_analysis['stale_score_penalty_weight_grid']}")
    lines.append(f"- extension_score_penalty_weight_grid: {grid_analysis['extension_score_penalty_weight_grid']}")
    lines.append(f"- select_threshold: {grid_analysis['select_threshold']}")
    lines.append(f"- near_miss_threshold: {grid_analysis['near_miss_threshold']}")
    lines.append(f"- focus_tickers: {grid_analysis['focus_tickers']}")
    lines.append(f"- grid_row_count: {grid_analysis['grid_row_count']}")
    lines.append(f"- best_focus_rows: {grid_analysis['best_focus_rows']}")
    lines.append(f"- first_focus_near_miss_rows: {grid_analysis['first_focus_near_miss_rows']}")
    lines.append("")
    lines.append("## Grid Rows")
    for row in grid_analysis["rows"]:
        lines.append(
            f"- variant={row['structural_variant']}, avoid_penalty={row['layer_c_avoid_penalty']}, stale_weight={row['stale_score_penalty_weight']}, extension_weight={row['extension_score_penalty_weight']}, focus_scores={row['focus_scores']}, focus_gaps={row['focus_gaps_to_near_miss']}, focus_decisions={row['focus_decisions']}, replayed={row['replayed_short_trade_decision_counts']}"
        )
    return "\n".join(lines) + "\n"


def render_selection_target_penalty_threshold_grid_markdown(grid_analysis: dict[str, Any]) -> str:
    lines = ["# Selection Target Penalty + Threshold Frontier Grid", ""]
    lines.append(f"- profile_name: {grid_analysis['profile_name']}")
    lines.append(f"- base_structural_variants: {grid_analysis['base_structural_variants']}")
    lines.append(f"- layer_c_avoid_penalty_grid: {grid_analysis['layer_c_avoid_penalty_grid']}")
    lines.append(f"- stale_score_penalty_weight_grid: {grid_analysis['stale_score_penalty_weight_grid']}")
    lines.append(f"- extension_score_penalty_weight_grid: {grid_analysis['extension_score_penalty_weight_grid']}")
    lines.append(f"- select_threshold_grid: {grid_analysis['select_threshold_grid']}")
    lines.append(f"- near_miss_threshold_grid: {grid_analysis['near_miss_threshold_grid']}")
    lines.append(f"- focus_tickers: {grid_analysis['focus_tickers']}")
    lines.append(f"- grid_row_count: {grid_analysis['grid_row_count']}")
    lines.append(f"- first_focus_near_miss_rows: {grid_analysis['first_focus_near_miss_rows']}")
    lines.append(f"- first_focus_selected_rows: {grid_analysis['first_focus_selected_rows']}")
    lines.append("")
    lines.append("## Grid Rows")
    for row in grid_analysis["rows"]:
        lines.append(
            f"- variant={row['structural_variant']}, avoid_penalty={row['layer_c_avoid_penalty']}, stale_weight={row['stale_score_penalty_weight']}, extension_weight={row['extension_score_penalty_weight']}, select={row['select_threshold']}, near_miss={row['near_miss_threshold']}, adjustment_cost={row['adjustment_cost']}, focus_scores={row['focus_scores']}, focus_gaps={row['focus_gaps_to_near_miss']}, focus_decisions={row['focus_decisions']}"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay short-trade selection targets from selection_target_replay_input.json artifacts.")
    parser.add_argument("input_path", help="Path to a selection_target_replay_input.json file, a selection_artifacts directory, or a report directory.")
    parser.add_argument("--compare-to", default=None, help="Optional second replay input/report path to compare against the primary fixed artifact.")
    parser.add_argument("--allow-roster-drift", action="store_true", help="Allow compare mode to proceed even when selected_analysts rosters differ between artifacts.")
    parser.add_argument("--profile-name", default="default", help="Short-trade target profile used during replay. Available: " + ", ".join(sorted(SHORT_TRADE_TARGET_PROFILES.keys())))
    parser.add_argument("--select-threshold", type=float, default=None, help="Override short-trade SELECT_THRESHOLD during replay.")
    parser.add_argument("--near-miss-threshold", type=float, default=None, help="Override short-trade NEAR_MISS_THRESHOLD during replay.")
    parser.add_argument("--select-threshold-grid", default=None, help="Comma-separated select-threshold grid for threshold sweep.")
    parser.add_argument("--near-miss-threshold-grid", default=None, help="Comma-separated near-miss-threshold grid for threshold sweep.")
    parser.add_argument("--structural-variants", default=None, help="Comma-separated structural variants to evaluate. Available: " + ", ".join(sorted(STRUCTURAL_VARIANTS.keys())))
    parser.add_argument("--breakout-freshness-max-grid", default=None, help="Comma-separated breakout_freshness max grid for candidate-entry weak-structure filtering. Use 'none' to omit this dimension.")
    parser.add_argument("--trend-acceleration-max-grid", default=None, help="Comma-separated trend_acceleration max grid for candidate-entry weak-structure filtering. Use 'none' to omit this dimension.")
    parser.add_argument("--volume-expansion-quality-max-grid", default=None, help="Comma-separated volume_expansion_quality max grid for candidate-entry weak-structure filtering. Use 'none' to omit this dimension.")
    parser.add_argument("--close-strength-max-grid", default=None, help="Comma-separated close_strength max grid for candidate-entry weak-structure filtering. Use 'none' to omit this dimension.")
    parser.add_argument("--catalyst-freshness-max-grid", default=None, help="Comma-separated catalyst_freshness max grid for candidate-entry weak-structure filtering. Use 'none' to omit this dimension.")
    parser.add_argument("--avoid-penalty-grid", default=None, help="Comma-separated layer_c_avoid_penalty grid for penalty frontier analysis.")
    parser.add_argument("--stale-score-penalty-grid", default=None, help="Comma-separated stale_score_penalty_weight grid for penalty frontier analysis.")
    parser.add_argument("--extension-score-penalty-grid", default=None, help="Comma-separated extension_score_penalty_weight grid for penalty frontier analysis.")
    parser.add_argument("--focus-tickers", default=None, help="Comma-separated tickers to include in focused score diagnostics.")
    parser.add_argument("--preserve-tickers", default=None, help="Comma-separated tickers that should remain unfiltered when searching candidate-entry semantic rows.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--markdown-output", type=Path, default=None, help="Optional Markdown summary output path.")
    return parser.parse_args()


def _parse_main_grid_options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "select_grid": _parse_threshold_grid(args.select_threshold_grid),
        "near_miss_grid": _parse_threshold_grid(args.near_miss_threshold_grid),
        "structural_variants": _parse_structural_variant_grid(args.structural_variants),
        "breakout_max_grid": _parse_optional_threshold_grid(args.breakout_freshness_max_grid),
        "trend_max_grid": _parse_optional_threshold_grid(args.trend_acceleration_max_grid),
        "volume_max_grid": _parse_optional_threshold_grid(args.volume_expansion_quality_max_grid),
        "close_max_grid": _parse_optional_threshold_grid(args.close_strength_max_grid),
        "catalyst_max_grid": _parse_optional_threshold_grid(args.catalyst_freshness_max_grid),
        "avoid_penalty_grid": _parse_threshold_grid(args.avoid_penalty_grid),
        "stale_score_penalty_grid": _parse_threshold_grid(args.stale_score_penalty_grid),
        "extension_score_penalty_grid": _parse_threshold_grid(args.extension_score_penalty_grid),
        "focus_tickers": _parse_ticker_grid(args.focus_tickers),
        "preserve_tickers": _parse_ticker_grid(args.preserve_tickers),
    }


def _run_main_compare_analysis(
    args: argparse.Namespace,
    *,
    select_grid: list[float],
    near_miss_grid: list[float],
    structural_variants: list[str],
    breakout_max_grid: list[float | None],
    trend_max_grid: list[float | None],
    volume_max_grid: list[float | None],
    close_max_grid: list[float | None],
    catalyst_max_grid: list[float | None],
    avoid_penalty_grid: list[float],
    stale_score_penalty_grid: list[float],
    extension_score_penalty_grid: list[float],
    focus_tickers: list[str],
) -> tuple[dict[str, Any], str]:
    if avoid_penalty_grid or stale_score_penalty_grid or extension_score_penalty_grid or breakout_max_grid or trend_max_grid or volume_max_grid or close_max_grid or catalyst_max_grid:
        raise SystemExit("--compare-to does not support penalty or candidate-entry grid modes.")
    if select_grid or near_miss_grid:
        raise SystemExit("--compare-to does not support threshold grid modes.")
    if structural_variants and len(structural_variants) > 1:
        raise SystemExit("--compare-to accepts at most one structural variant.")
    analysis = compare_selection_target_replay_inputs(
        args.input_path,
        args.compare_to,
        profile_name=args.profile_name,
        select_threshold=args.select_threshold,
        near_miss_threshold=args.near_miss_threshold,
        structural_variant=(structural_variants or ["baseline"])[0],
        focus_tickers=focus_tickers,
        allow_roster_drift=args.allow_roster_drift,
    )
    return analysis, render_selection_target_replay_comparison_markdown(analysis)


def _run_main_analysis(args: argparse.Namespace, grid_options: dict[str, Any]) -> tuple[dict[str, Any], str]:
    select_grid = grid_options["select_grid"]
    near_miss_grid = grid_options["near_miss_grid"]
    structural_variants = grid_options["structural_variants"]
    breakout_max_grid = grid_options["breakout_max_grid"]
    trend_max_grid = grid_options["trend_max_grid"]
    volume_max_grid = grid_options["volume_max_grid"]
    close_max_grid = grid_options["close_max_grid"]
    catalyst_max_grid = grid_options["catalyst_max_grid"]
    avoid_penalty_grid = grid_options["avoid_penalty_grid"]
    stale_score_penalty_grid = grid_options["stale_score_penalty_grid"]
    extension_score_penalty_grid = grid_options["extension_score_penalty_grid"]
    focus_tickers = grid_options["focus_tickers"]
    preserve_tickers = grid_options["preserve_tickers"]

    if args.compare_to is not None:
        return _run_main_compare_analysis(
            args,
            select_grid=select_grid,
            near_miss_grid=near_miss_grid,
            structural_variants=structural_variants,
            breakout_max_grid=breakout_max_grid,
            trend_max_grid=trend_max_grid,
            volume_max_grid=volume_max_grid,
            close_max_grid=close_max_grid,
            catalyst_max_grid=catalyst_max_grid,
            avoid_penalty_grid=avoid_penalty_grid,
            stale_score_penalty_grid=stale_score_penalty_grid,
            extension_score_penalty_grid=extension_score_penalty_grid,
            focus_tickers=focus_tickers,
        )
    if (avoid_penalty_grid or stale_score_penalty_grid or extension_score_penalty_grid) and (select_grid or near_miss_grid):
        analysis = analyze_selection_target_penalty_threshold_grid(
            args.input_path,
            profile_name=args.profile_name,
            avoid_penalty_values=avoid_penalty_grid,
            stale_score_penalty_weight_values=stale_score_penalty_grid,
            extension_score_penalty_weight_values=extension_score_penalty_grid,
            select_thresholds=select_grid,
            near_miss_thresholds=near_miss_grid,
            base_structural_variants=structural_variants or ["baseline"],
            focus_tickers=focus_tickers,
        )
        return analysis, render_selection_target_penalty_threshold_grid_markdown(analysis)
    if avoid_penalty_grid or stale_score_penalty_grid or extension_score_penalty_grid:
        analysis = analyze_selection_target_penalty_grid(
            args.input_path,
            profile_name=args.profile_name,
            avoid_penalty_values=avoid_penalty_grid,
            stale_score_penalty_weight_values=stale_score_penalty_grid,
            extension_score_penalty_weight_values=extension_score_penalty_grid,
            base_structural_variants=structural_variants or ["baseline"],
            select_threshold=args.select_threshold,
            near_miss_threshold=args.near_miss_threshold,
            focus_tickers=focus_tickers,
        )
        return analysis, render_selection_target_penalty_grid_markdown(analysis)
    if breakout_max_grid or trend_max_grid or volume_max_grid or close_max_grid or catalyst_max_grid:
        analysis = analyze_selection_target_candidate_entry_metric_grid(
            args.input_path,
            profile_name=args.profile_name,
            breakout_freshness_max_values=breakout_max_grid,
            trend_acceleration_max_values=trend_max_grid,
            volume_expansion_quality_max_values=volume_max_grid,
            close_strength_max_values=close_max_grid,
            catalyst_freshness_max_values=catalyst_max_grid,
            base_structural_variants=structural_variants or ["baseline"],
            select_threshold=args.select_threshold,
            near_miss_threshold=args.near_miss_threshold,
            focus_tickers=focus_tickers,
            preserve_tickers=preserve_tickers,
        )
        return analysis, render_selection_target_candidate_entry_metric_grid_markdown(analysis)
    if structural_variants and (select_grid or near_miss_grid):
        analysis = analyze_selection_target_combination_grid(
            args.input_path,
            profile_name=args.profile_name,
            structural_variants=structural_variants,
            select_thresholds=select_grid,
            near_miss_thresholds=near_miss_grid,
        )
        return analysis, render_selection_target_combination_grid_markdown(analysis)
    if structural_variants:
        analysis = analyze_selection_target_structural_variants(
            args.input_path,
            profile_name=args.profile_name,
            structural_variants=structural_variants,
            select_threshold=args.select_threshold,
            near_miss_threshold=args.near_miss_threshold,
            focus_tickers=focus_tickers,
        )
        return analysis, render_selection_target_structural_variants_markdown(analysis)
    if select_grid or near_miss_grid:
        analysis = analyze_selection_target_threshold_grid(
            args.input_path,
            profile_name=args.profile_name,
            select_thresholds=select_grid,
            near_miss_thresholds=near_miss_grid,
        )
        return analysis, render_selection_target_threshold_grid_markdown(analysis)
    analysis = analyze_selection_target_replay_inputs(
        args.input_path,
        profile_name=args.profile_name,
        select_threshold=args.select_threshold,
        near_miss_threshold=args.near_miss_threshold,
        structural_variant="baseline",
        focus_tickers=focus_tickers,
    )
    return analysis, render_selection_target_replay_markdown(analysis)


def main() -> int:
    args = parse_args()
    analysis, markdown_text = _run_main_analysis(args, _parse_main_grid_options(args))
    if args.output is not None:
        _dump_json(args.output, analysis)
    if args.markdown_output is not None:
        args.markdown_output.write_text(markdown_text, encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
