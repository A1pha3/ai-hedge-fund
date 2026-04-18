"""Upstream shadow release and catalyst relief logic for daily pipeline.

Handles:
- Upstream shadow candidate release scoring and filtering
- Shadow watchlist promotion logic
- Catalyst relief config building (including carryover)
"""

from __future__ import annotations

from typing import Any

from src.execution.daily_pipeline_catalyst_diagnostics_helpers import (
    build_catalyst_theme_short_trade_carryover_relief_config as build_catalyst_theme_short_trade_carryover_relief_config_impl,
)
from src.execution.daily_pipeline_hotspot_helpers import (
    build_upstream_shadow_catalyst_relief_config as build_upstream_shadow_catalyst_relief_config_impl,
    build_upstream_shadow_release_entry as build_upstream_shadow_release_entry_impl,
    rank_scored_entries,
    resolve_selected_threshold,
    select_upstream_shadow_release_entries as select_upstream_shadow_release_entries_impl,
    summarize_shadow_release_historical_support,
    summarize_upstream_shadow_release_historical_support as summarize_upstream_shadow_release_historical_support_impl,
)
from src.execution.daily_pipeline_settings import (
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN,
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN,
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF,
    UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_CANDIDATE_SCORE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_CATALYST_FRESHNESS_FLOOR,
    UPSTREAM_SHADOW_CATALYST_RELIEF_CLOSE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_MIN_EVALUABLE_COUNT,
    UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_CLOSE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_OPEN_TO_CLOSE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_REQUIRED_EXECUTION_QUALITY,
    UPSTREAM_SHADOW_CATALYST_RELIEF_NEAR_MISS_THRESHOLD,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CANDIDATE_SCORE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CLOSE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_HISTORY_NEXT_CLOSE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_NEAR_MISS_THRESHOLD,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_SELECTED_THRESHOLD,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_TREND_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_SELECTED_THRESHOLD,
    UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_BY_LANE,
    UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_DEFAULT,
    UPSTREAM_SHADOW_CATALYST_RELIEF_TREND_MIN,
    UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN,
    UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS,
    UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS,
    UPSTREAM_SHADOW_RELEASE_LANES,
    UPSTREAM_SHADOW_RELEASE_MAX_TICKERS,
    UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE,
    UPSTREAM_SHADOW_RELEASE_SCORE_FLOOR_CLOSE_MIN,
    UPSTREAM_SHADOW_RELEASE_SCORE_FLOOR_TREND_MIN,
    UPSTREAM_SHADOW_WATCHLIST_PROMOTION_LANES,
    UPSTREAM_SHADOW_WATCHLIST_PROMOTION_MAX_TICKERS,
)
from src.execution.models import LayerCResult
from src.screening.models import StrategySignal


def _summarize_upstream_shadow_release_historical_support(historical_prior: dict[str, Any]) -> dict[str, Any]:
    return summarize_upstream_shadow_release_historical_support_impl(historical_prior)


def _supports_upstream_shadow_catalyst_relief_history(historical_prior: dict[str, Any] | None) -> bool:
    if not historical_prior:
        return False
    execution_quality_label = str(historical_prior.get("execution_quality_label") or "")
    evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    next_close_positive_rate = float(historical_prior.get("next_close_positive_rate") or 0.0)
    next_open_to_close_return_mean = float(historical_prior.get("next_open_to_close_return_mean") or 0.0)
    return (
        execution_quality_label in UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_REQUIRED_EXECUTION_QUALITY
        and evaluable_count >= UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_MIN_EVALUABLE_COUNT
        and next_close_positive_rate >= UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_CLOSE_MIN
        and next_open_to_close_return_mean >= UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_OPEN_TO_CLOSE_MIN
    )


def _compute_short_trade_boundary_candidate_score(snapshot: dict) -> float:
    return round(
        (0.30 * float(snapshot.get("breakout_freshness", 0.0) or 0.0)) + (0.25 * float(snapshot.get("trend_acceleration", 0.0) or 0.0)) + (0.20 * float(snapshot.get("volume_expansion_quality", 0.0) or 0.0)) + (0.15 * float(snapshot.get("catalyst_freshness", 0.0) or 0.0)) + (0.10 * float(snapshot.get("close_strength", 0.0) or 0.0)),
        4,
    )


def _should_release_upstream_shadow_candidate(
    *,
    candidate_entry: dict[str, Any],
    filter_reason: str,
    metrics_payload: dict[str, Any],
    historical_support: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    candidate_pool_lane = str(candidate_entry.get("candidate_pool_lane") or "")
    candidate_score = float(metrics_payload.get("candidate_score", 0.0) or 0.0)
    lane_score_floor = float(UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS.get(candidate_pool_lane, UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN))

    if candidate_pool_lane not in UPSTREAM_SHADOW_RELEASE_LANES:
        return False, None
    if filter_reason in {"metric_data_fail", "structural_prefilter_fail"}:
        return False, None
    if candidate_score < lane_score_floor:
        return False, None
    if bool((historical_support or {}).get("suppress_release")):
        return False, None
    if bool((historical_support or {}).get("sparse_weak_history")):
        return False, None
    if str((historical_support or {}).get("verdict") or "") == "supportive":
        return True, "upstream_shadow_release_supported_by_historical_prior"
    if not _passes_upstream_shadow_release_quality_floor(metrics_payload):
        return False, None
    return True, "upstream_shadow_release_score_floor_pass"


def _passes_upstream_shadow_release_quality_floor(metrics_payload: dict[str, Any]) -> bool:
    trend_acceleration = float(metrics_payload.get("trend_acceleration", 0.0) or 0.0)
    close_strength = float(metrics_payload.get("close_strength", 0.0) or 0.0)
    return trend_acceleration >= float(UPSTREAM_SHADOW_RELEASE_SCORE_FLOOR_TREND_MIN) and close_strength >= float(UPSTREAM_SHADOW_RELEASE_SCORE_FLOOR_CLOSE_MIN)


def _resolve_upstream_shadow_release_max_tickers(candidate_pool_lane: str) -> int:
    return int(UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS.get(candidate_pool_lane, UPSTREAM_SHADOW_RELEASE_MAX_TICKERS))


def _resolve_upstream_shadow_release_priority_rank(candidate_pool_lane: str, ticker: str) -> int | None:
    priority_tickers = list(UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE.get(candidate_pool_lane, []))
    try:
        return priority_tickers.index(ticker)
    except ValueError:
        return None


def _select_upstream_shadow_release_entries(
    ranked_released_shadow_entries: list[tuple[float, float, float, dict[str, Any]]],
) -> list[dict[str, Any]]:
    return select_upstream_shadow_release_entries_impl(
        ranked_released_shadow_entries=ranked_released_shadow_entries,
        resolve_priority_rank_fn=_resolve_upstream_shadow_release_priority_rank,
        resolve_lane_limit_fn=_resolve_upstream_shadow_release_max_tickers,
        max_tickers=UPSTREAM_SHADOW_RELEASE_MAX_TICKERS,
        rank_scored_entries_fn=rank_scored_entries,
    )


def _coerce_upstream_shadow_strategy_signal(payload: Any) -> StrategySignal | None:
    if isinstance(payload, StrategySignal):
        return payload
    if isinstance(payload, dict):
        try:
            return StrategySignal.model_validate(dict(payload))
        except Exception:
            return None
    return None


def _build_upstream_shadow_watchlist_reason_codes(entry: dict[str, Any]) -> list[str]:
    reason_codes = [str(code) for code in list(entry.get("candidate_reason_codes") or entry.get("reasons") or []) if str(code or "").strip()]
    if "upstream_shadow_watchlist_promotion" not in reason_codes:
        reason_codes.append("upstream_shadow_watchlist_promotion")
    return reason_codes


def _upstream_shadow_watchlist_promotion_sort_key(entry: dict[str, Any]) -> tuple[float, float, float, float, float, str]:
    historical_support = dict(entry.get("shadow_release_historical_support") or {})
    catalyst_relief = dict(entry.get("short_trade_catalyst_relief") or {})
    release_reason = str(entry.get("shadow_release_reason") or "")
    return (
        1.0 if release_reason == "upstream_shadow_release_supported_by_historical_prior" else 0.0,
        float(historical_support.get("support_score", 0.0) or 0.0),
        1.0 if catalyst_relief.get("selected_threshold") is not None else 0.0,
        float(entry.get("shadow_release_candidate_score", 0.0) or 0.0),
        float(entry.get("score_final", 0.0) or 0.0),
        str(entry.get("ticker") or ""),
    )


def _should_promote_upstream_shadow_release_to_watchlist(
    entry: dict[str, Any],
    *,
    existing_tickers: set[str],
) -> bool:
    ticker = str(entry.get("ticker") or "")
    if not ticker or ticker in existing_tickers:
        return False

    candidate_pool_lane = str(entry.get("candidate_pool_lane") or "")
    if candidate_pool_lane not in UPSTREAM_SHADOW_WATCHLIST_PROMOTION_LANES:
        return False

    if str(entry.get("shadow_release_reason") or "") == "upstream_shadow_release_supported_by_historical_prior":
        return True

    catalyst_relief = dict(entry.get("short_trade_catalyst_relief") or {})
    return catalyst_relief.get("selected_threshold") is not None


def _build_upstream_shadow_watchlist_entry(entry: dict[str, Any]) -> LayerCResult:
    strategy_signals = {name: signal for name, payload in dict(entry.get("strategy_signals") or {}).items() if (signal := _coerce_upstream_shadow_strategy_signal(payload)) is not None}
    reason_codes = _build_upstream_shadow_watchlist_reason_codes(entry)
    return LayerCResult(
        ticker=str(entry.get("ticker") or ""),
        score_c=float(entry.get("score_c", 0.0) or 0.0),
        score_final=float(entry.get("score_final", entry.get("score_b", 0.0)) or 0.0),
        score_b=float(entry.get("score_b", 0.0) or 0.0),
        quality_score=float(entry.get("quality_score", 0.5) or 0.5),
        market_state=dict(entry.get("market_state") or {}),
        candidate_source=str(entry.get("candidate_source") or "upstream_shadow_release_watchlist"),
        candidate_reason_codes=reason_codes,
        strategy_signals=strategy_signals,
        agent_signals={},
        agent_contribution_summary=dict(entry.get("agent_contribution_summary") or {}),
        bc_conflict=str(entry.get("bc_conflict") or "") or None,
        decision=str(entry.get("decision") or "watch"),
    )


def _select_upstream_shadow_watchlist_entries(
    released_shadow_entries: list[dict[str, Any]],
    *,
    existing_tickers: set[str],
) -> list[LayerCResult]:
    ranked_entries = [dict(entry) for entry in list(released_shadow_entries or []) if _should_promote_upstream_shadow_release_to_watchlist(dict(entry), existing_tickers=existing_tickers)]
    ranked_entries.sort(key=_upstream_shadow_watchlist_promotion_sort_key, reverse=True)

    promoted_entries: list[LayerCResult] = []
    seen_tickers = set(existing_tickers)
    for entry in ranked_entries:
        ticker = str(entry.get("ticker") or "")
        if not ticker or ticker in seen_tickers:
            continue
        promoted_entries.append(_build_upstream_shadow_watchlist_entry(entry))
        seen_tickers.add(ticker)
        if len(promoted_entries) >= UPSTREAM_SHADOW_WATCHLIST_PROMOTION_MAX_TICKERS:
            break
    return promoted_entries


def _mark_upstream_shadow_watchlist_promotions(
    short_trade_candidate_diagnostics: dict[str, Any],
    *,
    promoted_tickers: set[str],
) -> dict[str, Any]:
    if not promoted_tickers:
        return short_trade_candidate_diagnostics

    updated_diagnostics = dict(short_trade_candidate_diagnostics or {})
    updated_released_entries: list[dict[str, Any]] = []
    for entry in list(updated_diagnostics.get("released_shadow_entries", []) or []):
        updated_entry = dict(entry)
        ticker = str(updated_entry.get("ticker") or "")
        if ticker in promoted_tickers:
            updated_entry["promoted_to_watchlist"] = True
            updated_entry["promotion_target"] = "watchlist"
            updated_entry["promotion_reason"] = "upstream_shadow_watchlist_promotion"
        updated_released_entries.append(updated_entry)

    updated_diagnostics["released_shadow_entries"] = updated_released_entries
    updated_diagnostics["promoted_to_watchlist_count"] = len(promoted_tickers)
    updated_diagnostics["promoted_to_watchlist_tickers"] = sorted(promoted_tickers)
    return updated_diagnostics


def _merge_watchlist_with_upstream_shadow_promotions(
    watchlist: list[LayerCResult],
    promoted_entries: list[LayerCResult],
) -> list[LayerCResult]:
    merged_by_ticker = {item.ticker: item for item in list(watchlist or [])}
    for item in list(promoted_entries or []):
        merged_by_ticker.setdefault(item.ticker, item)
    return sorted(
        merged_by_ticker.values(),
        key=lambda item: (float(item.score_final), float(item.score_b), str(item.ticker)),
        reverse=True,
    )


def _resolve_upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff(candidate_pool_lane: str) -> bool:
    return bool(
        UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_BY_LANE.get(
            candidate_pool_lane,
            UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_DEFAULT,
        )
    )


def _parse_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_upstream_shadow_catalyst_relief_metrics(metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_score": float(metrics_payload.get("candidate_score", 0.0) or 0.0),
        "breakout_freshness": float(metrics_payload.get("breakout_freshness", 0.0) or 0.0),
        "trend_acceleration": float(metrics_payload.get("trend_acceleration", 0.0) or 0.0),
        "close_strength": float(metrics_payload.get("close_strength", 0.0) or 0.0),
        "profitability_hard_cliff": bool(metrics_payload.get("profitability_hard_cliff")),
    }


def _passes_upstream_shadow_catalyst_relief_gates(
    *,
    threshold_config: dict[str, float],
    historical_prior: dict[str, Any] | None,
    metric_snapshot: dict[str, Any],
) -> bool:
    if not _supports_upstream_shadow_catalyst_relief_history(historical_prior):
        return False
    if float(metric_snapshot["candidate_score"]) < threshold_config["candidate_score_min"]:
        return False
    if float(metric_snapshot["breakout_freshness"]) < UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN:
        return False
    if float(metric_snapshot["trend_acceleration"]) < threshold_config["trend_acceleration_min"]:
        return False
    return not float(metric_snapshot["close_strength"]) < threshold_config["close_strength_min"]


def _build_upstream_shadow_catalyst_relief_threshold_inputs(
    *,
    candidate_pool_lane: str,
    profitability_hard_cliff: bool,
    historical_next_close_positive_rate: float | None,
) -> dict[str, Any]:
    return {
        "candidate_pool_lane": candidate_pool_lane,
        "profitability_hard_cliff": profitability_hard_cliff,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
        "candidate_score_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_CANDIDATE_SCORE_MIN),
        "trend_acceleration_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_TREND_MIN),
        "close_strength_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_CLOSE_MIN),
        "near_miss_threshold": float(UPSTREAM_SHADOW_CATALYST_RELIEF_NEAR_MISS_THRESHOLD),
        "post_gate_history_next_close_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_HISTORY_NEXT_CLOSE_MIN),
        "post_gate_hard_cliff_candidate_score_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CANDIDATE_SCORE_MIN),
        "post_gate_hard_cliff_trend_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_TREND_MIN),
        "post_gate_hard_cliff_close_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CLOSE_MIN),
        "post_gate_hard_cliff_near_miss_threshold": float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_NEAR_MISS_THRESHOLD),
    }


def _resolve_upstream_shadow_selected_threshold(
    *,
    candidate_pool_lane: str,
    profitability_hard_cliff: bool,
    shadow_visibility_gap_selected: bool,
) -> tuple[bool, float]:
    return resolve_selected_threshold(
        candidate_pool_lane=candidate_pool_lane,
        profitability_hard_cliff=profitability_hard_cliff,
        shadow_visibility_gap_selected=shadow_visibility_gap_selected,
        post_gate_selected_threshold=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_SELECTED_THRESHOLD),
        post_gate_hard_cliff_selected_threshold=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_SELECTED_THRESHOLD),
    )


def _build_upstream_shadow_catalyst_relief_payload_kwargs(
    *,
    threshold_config: dict[str, float],
    selected_threshold_override_enabled: bool,
    selected_threshold: float,
    require_no_profitability_hard_cliff: bool,
) -> dict[str, Any]:
    return {
        "near_miss_threshold": threshold_config["near_miss_threshold"],
        "selected_threshold_override_enabled": selected_threshold_override_enabled,
        "selected_threshold": selected_threshold,
        "breakout_freshness_min": UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN,
        "trend_acceleration_min": threshold_config["trend_acceleration_min"],
        "close_strength_min": threshold_config["close_strength_min"],
        "require_no_profitability_hard_cliff": require_no_profitability_hard_cliff,
        "required_execution_quality_labels": UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_REQUIRED_EXECUTION_QUALITY,
        "min_historical_evaluable_count": UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_MIN_EVALUABLE_COUNT,
        "min_historical_next_close_positive_rate": UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_CLOSE_MIN,
        "min_historical_next_open_to_close_return_mean": UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_OPEN_TO_CLOSE_MIN,
        "catalyst_freshness_floor": UPSTREAM_SHADOW_CATALYST_RELIEF_CATALYST_FRESHNESS_FLOOR,
    }


def _build_upstream_shadow_catalyst_relief_config(
    *,
    candidate_pool_lane: str,
    filter_reason: str,
    metrics_payload: dict[str, Any],
    historical_prior: dict[str, Any] | None = None,
    shadow_visibility_gap_selected: bool = False,
) -> dict[str, Any]:
    return build_upstream_shadow_catalyst_relief_config_impl(
        candidate_pool_lane=candidate_pool_lane,
        filter_reason=filter_reason,
        metrics_payload=metrics_payload,
        historical_prior=historical_prior,
        shadow_visibility_gap_selected=shadow_visibility_gap_selected,
        extract_metric_snapshot_fn=_extract_upstream_shadow_catalyst_relief_metrics,
        parse_optional_float_fn=_parse_optional_float,
        build_threshold_inputs_fn=_build_upstream_shadow_catalyst_relief_threshold_inputs,
        passes_relief_gates_fn=_passes_upstream_shadow_catalyst_relief_gates,
        resolve_require_no_profitability_hard_cliff_fn=_resolve_upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff,
        resolve_selected_threshold_fn=_resolve_upstream_shadow_selected_threshold,
        build_payload_kwargs_fn=_build_upstream_shadow_catalyst_relief_payload_kwargs,
    )


def _build_catalyst_theme_short_trade_carryover_relief_config(*, metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return build_catalyst_theme_short_trade_carryover_relief_config_impl(
        metrics_payload=metrics_payload,
        candidate_score_min=CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN,
        breakout_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN,
        trend_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN,
        close_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN,
        catalyst_freshness_floor=CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR,
        near_miss_threshold=CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD,
        min_historical_evaluable_count=CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT,
        require_no_profitability_hard_cliff=CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF,
    )


def _build_upstream_shadow_release_entry(*, candidate_entry: dict[str, Any], filter_reason: str, metrics_payload: dict[str, Any], release_reason: str) -> dict[str, Any]:
    return build_upstream_shadow_release_entry_impl(
        candidate_entry=candidate_entry,
        filter_reason=filter_reason,
        metrics_payload=metrics_payload,
        release_reason=release_reason,
        upstream_shadow_release_lane_score_mins=UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS,
        upstream_shadow_release_candidate_score_min=UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN,
        summarize_shadow_release_historical_support_fn=_summarize_upstream_shadow_release_historical_support,
        build_upstream_shadow_catalyst_relief_config_fn=_build_upstream_shadow_catalyst_relief_config,
    )
