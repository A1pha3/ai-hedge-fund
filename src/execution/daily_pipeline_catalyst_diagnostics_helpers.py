from __future__ import annotations

from typing import Any
from collections.abc import Callable

from src.execution.daily_pipeline_candidate_helpers import (
    qualify_catalyst_theme_candidate_from_snapshot,
)
from src.execution.layer_c_aggregator import _derive_quality_score
from src.execution.daily_pipeline_settings import (
    CATALYST_THEME_BREAKOUT_MIN,
    CATALYST_THEME_CANDIDATE_SCORE_MIN,
    CATALYST_THEME_CATALYST_MIN,
    CATALYST_THEME_CLOSE_MIN,
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN,
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN,
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_SECTOR_MIN,
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN,
    CATALYST_THEME_MAX_TICKERS,
    CATALYST_THEME_QUALITY_MIN,
    CATALYST_THEME_SECTOR_MIN,
    CATALYST_THEME_SHADOW_MAX_TICKERS,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF,
)
from src.targets.short_trade_target import build_short_trade_target_snapshot_from_entry


def _signal_directional_strength(signal: Any) -> float:
    if signal is None:
        return 0.0
    direction = int(getattr(signal, "direction", 0) or 0)
    confidence = max(0.0, min(100.0, float(getattr(signal, "confidence", 0.0) or 0.0)))
    completeness = max(0.0, min(1.0, float(getattr(signal, "completeness", 0.0) or 0.0)))
    return max(-1.0, min(1.0, direction * (confidence / 100.0) * completeness))


def _serialize_market_state(item: Any) -> dict[str, Any]:
    market_state = getattr(item, "market_state", None)
    if hasattr(market_state, "model_dump"):
        return dict(market_state.model_dump(mode="json"))
    return dict(market_state or {})


def _build_catalyst_theme_agent_contribution_summary(item: Any) -> tuple[float, dict[str, Any]]:
    strategy_signals = dict(getattr(item, "strategy_signals", {}) or {})
    trend_strength = _signal_directional_strength(strategy_signals.get("trend"))
    event_strength = _signal_directional_strength(strategy_signals.get("event_sentiment"))
    fundamental_strength = _signal_directional_strength(strategy_signals.get("fundamental"))

    analyst_contribution = max(0.0, (0.40 * max(0.0, fundamental_strength)) + (0.10 * max(0.0, event_strength)))
    investor_contribution = max(0.0, (0.35 * max(0.0, trend_strength)) + (0.10 * max(0.0, event_strength)))
    adjusted_score_c = round((0.55 * analyst_contribution) + (0.45 * investor_contribution), 4)

    positive_agents = []
    if analyst_contribution > 0:
        positive_agents.append(
            {
                "agent_id": "catalyst_theme_fundamental_proxy",
                "contribution": round(analyst_contribution, 4),
                "raw_contribution": round(analyst_contribution, 4),
                "normalized_weight": 1.0,
                "direction": 1,
                "confidence": round(max(0.0, fundamental_strength) * 100.0, 2),
                "completeness": 1.0,
                "cohort": "analyst",
            }
        )
    if investor_contribution > 0:
        positive_agents.append(
            {
                "agent_id": "catalyst_theme_trend_proxy",
                "contribution": round(investor_contribution, 4),
                "raw_contribution": round(investor_contribution, 4),
                "normalized_weight": 1.0,
                "direction": 1,
                "confidence": round(max(0.0, trend_strength) * 100.0, 2),
                "completeness": 1.0,
                "cohort": "investor",
            }
        )

    return adjusted_score_c, {
        "active_agent_count": len(positive_agents),
        "positive_agent_count": len(positive_agents),
        "negative_agent_count": 0,
        "neutral_agent_count": 0,
        "raw_score_c": adjusted_score_c,
        "adjusted_score_c": adjusted_score_c,
        "cohort_contributions": {
            "analyst": round(analyst_contribution, 4),
            "investor": round(investor_contribution, 4),
            "other": 0.0,
        },
        "top_positive_agents": positive_agents[:3],
        "top_negative_agents": [],
    }


def build_upstream_catalyst_theme_candidates(
    *,
    fused: list[Any],
    watchlist: list[Any],
    short_trade_candidate_diagnostics: dict[str, Any],
) -> list[Any]:
    excluded_tickers = {item.ticker for item in watchlist}
    excluded_tickers.update(str(ticker) for ticker in list((short_trade_candidate_diagnostics or {}).get("selected_tickers", []) or []))
    return sorted(
        [item for item in fused if item.ticker not in excluded_tickers],
        key=lambda current: current.score_b,
        reverse=True,
    )


def collect_catalyst_theme_diagnostic_rankings(
    *,
    upstream_candidates: list[Any],
    trade_date: str,
    build_catalyst_theme_entry_fn: Callable[..., dict[str, Any]],
    qualifies_catalyst_theme_candidate_fn: Callable[..., tuple[bool, str, dict[str, Any]]],
    build_catalyst_theme_shadow_entry_fn: Callable[..., dict[str, Any]],
    build_catalyst_theme_short_trade_carryover_relief_config_fn: Callable[..., dict[str, Any] | None],
) -> dict[str, Any]:
    filtered_reason_counts: dict[str, int] = {}
    ranked_candidates: list[tuple[float, float, dict[str, Any]]] = []
    ranked_shadow_candidates: list[tuple[float, float, float, dict[str, Any]]] = []

    for item in upstream_candidates:
        diagnostic = process_catalyst_theme_candidate_diagnostic(
            item=item,
            trade_date=trade_date,
            build_catalyst_theme_entry_fn=build_catalyst_theme_entry_fn,
            qualifies_catalyst_theme_candidate_fn=qualifies_catalyst_theme_candidate_fn,
            build_catalyst_theme_shadow_entry_fn=build_catalyst_theme_shadow_entry_fn,
            build_catalyst_theme_short_trade_carryover_relief_config_fn=build_catalyst_theme_short_trade_carryover_relief_config_fn,
        )
        accumulate_catalyst_theme_diagnostic_result(
            diagnostic=diagnostic,
            ranked_candidates=ranked_candidates,
            ranked_shadow_candidates=ranked_shadow_candidates,
            filtered_reason_counts=filtered_reason_counts,
        )

    return {
        "filtered_reason_counts": filtered_reason_counts,
        "ranked_candidates": ranked_candidates,
        "ranked_shadow_candidates": ranked_shadow_candidates,
    }


def build_catalyst_theme_shadow_entry(
    *,
    item: Any,
    filter_reason: str,
    metrics_payload: dict[str, Any],
    build_catalyst_theme_entry_fn: Callable[..., dict[str, Any]],
    compute_threshold_shortfalls_fn: Callable[[dict[str, Any], dict[str, float] | None], dict[str, float]],
) -> dict[str, Any]:
    threshold_shortfalls = compute_threshold_shortfalls_fn(
        dict(metrics_payload.get("threshold_metric_values") or metrics_payload),
        dict(metrics_payload.get("threshold_checks") or {}),
    )
    total_shortfall = round(sum(threshold_shortfalls.values()), 4)
    return {
        **build_catalyst_theme_entry_fn(item=item, reason=filter_reason, rank=0),
        "decision": "catalyst_theme_shadow",
        "candidate_source": "catalyst_theme_shadow",
        "score_target": float(metrics_payload.get("candidate_score", 0.0) or 0.0),
        "confidence": round(min(1.0, max(0.0, float(metrics_payload.get("candidate_score", 0.0) or 0.0))), 4),
        "top_reasons": [
            f"candidate_score={float(metrics_payload.get('candidate_score', 0.0) or 0.0):.2f}",
            f"catalyst_freshness={float(metrics_payload.get('catalyst_freshness', 0.0) or 0.0):.2f}",
            f"total_shortfall={total_shortfall:.2f}",
        ],
        "positive_tags": list(metrics_payload.get("theme_tags") or []),
        "gate_status": dict(metrics_payload.get("gate_status") or {}),
        "blockers": list(metrics_payload.get("blockers") or []),
        "metrics": {
            "breakout_freshness": metrics_payload.get("breakout_freshness"),
            "trend_acceleration": metrics_payload.get("trend_acceleration"),
            "close_strength": metrics_payload.get("close_strength"),
            "sector_resonance": metrics_payload.get("sector_resonance"),
            "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
        },
        "filter_reason": filter_reason,
        "threshold_shortfalls": threshold_shortfalls,
        "failed_threshold_count": len(threshold_shortfalls),
        "total_shortfall": total_shortfall,
        "promotion_trigger": "若催化继续发酵，或在受控实验里适度放宽题材催化门槛，可升级到题材催化研究池。",
        "catalyst_theme_metrics": metrics_payload,
    }


def resolve_catalyst_theme_close_momentum_relief(
    *,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    catalyst_freshness: float,
    catalyst_theme_catalyst_min: float,
    catalyst_theme_close_momentum_relief_breakout_min: float,
    catalyst_theme_close_momentum_relief_trend_min: float,
    catalyst_theme_close_momentum_relief_close_min: float,
    catalyst_theme_close_momentum_relief_sector_min: float,
    catalyst_theme_sector_min: float,
) -> dict[str, Any]:
    eligible = (
        catalyst_freshness < catalyst_theme_catalyst_min
        and breakout_freshness >= catalyst_theme_close_momentum_relief_breakout_min
        and trend_acceleration >= catalyst_theme_close_momentum_relief_trend_min
        and close_strength >= catalyst_theme_close_momentum_relief_close_min
        and sector_resonance >= catalyst_theme_close_momentum_relief_sector_min
    )
    effective_catalyst_freshness = round(max(catalyst_freshness, catalyst_theme_catalyst_min if eligible else catalyst_freshness), 4)
    effective_sector_min = round(catalyst_theme_close_momentum_relief_sector_min if eligible else catalyst_theme_sector_min, 4)
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible,
        "effective_catalyst_freshness": effective_catalyst_freshness,
        "effective_sector_min": effective_sector_min,
    }


def compute_catalyst_theme_threshold_shortfalls(
    *,
    metric_values: dict[str, Any],
    threshold_checks: dict[str, float] | None,
    catalyst_theme_candidate_score_min: float,
    catalyst_theme_breakout_min: float,
    catalyst_theme_close_min: float,
    catalyst_theme_sector_min: float,
    catalyst_theme_catalyst_min: float,
) -> dict[str, float]:
    threshold_checks = threshold_checks or {
        "candidate_score": round(float(catalyst_theme_candidate_score_min), 4),
        "breakout_freshness": round(float(catalyst_theme_breakout_min), 4),
        "close_strength": round(float(catalyst_theme_close_min), 4),
        "sector_resonance": round(float(catalyst_theme_sector_min), 4),
        "catalyst_freshness": round(float(catalyst_theme_catalyst_min), 4),
    }
    shortfalls: dict[str, float] = {}
    for metric_key, threshold_value in threshold_checks.items():
        actual_value = round(float(metric_values.get(metric_key, 0.0) or 0.0), 4)
        shortfall = round(threshold_value - actual_value, 4)
        if shortfall > 0:
            shortfalls[metric_key] = shortfall
    return shortfalls


def accumulate_catalyst_theme_diagnostic_result(
    *,
    diagnostic: dict[str, Any],
    ranked_candidates: list[tuple[float, float, dict[str, Any]]],
    ranked_shadow_candidates: list[tuple[float, float, float, dict[str, Any]]],
    filtered_reason_counts: dict[str, int],
) -> None:
    if diagnostic["qualified"]:
        ranked_candidates.append(diagnostic["candidate_ranked"])
        return

    filter_reason = str(diagnostic["filter_reason"] or "")
    filtered_reason_counts[filter_reason] = filtered_reason_counts.get(filter_reason, 0) + 1
    if diagnostic.get("shadow_ranked") is not None:
        ranked_shadow_candidates.append(diagnostic["shadow_ranked"])


def build_catalyst_theme_ranked_outputs(
    *,
    ranked_candidates: list[tuple[float, float, dict[str, Any]]],
    ranked_shadow_candidates: list[tuple[float, float, float, dict[str, Any]]],
    catalyst_theme_max_tickers: int,
    catalyst_theme_shadow_max_tickers: int,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    shadow_entries: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}

    ranked_candidates.sort(key=lambda row: (row[0], row[1], str(row[2].get("ticker") or "")), reverse=True)
    for rank, (_, _, entry) in enumerate(ranked_candidates[:catalyst_theme_max_tickers], start=1):
        entry["rank"] = rank
        reason = str(entry.get("reason") or "catalyst_theme_candidate_score_ranked")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        entries.append(entry)

    ranked_shadow_candidates.sort(key=lambda row: (row[0], row[1], row[2], str(row[3].get("ticker") or "")), reverse=True)
    for rank, (_, _, _, entry) in enumerate(ranked_shadow_candidates[:catalyst_theme_shadow_max_tickers], start=1):
        entry["rank"] = rank
        shadow_entries.append(entry)

    return {
        "entries": entries,
        "shadow_entries": shadow_entries,
        "reason_counts": reason_counts,
    }


def process_catalyst_theme_candidate_diagnostic(
    *,
    item,
    trade_date: str,
    build_catalyst_theme_entry_fn: Callable[..., dict[str, Any]],
    qualifies_catalyst_theme_candidate_fn: Callable[..., tuple[bool, str, dict[str, Any]]],
    build_catalyst_theme_shadow_entry_fn: Callable[..., dict[str, Any]],
    build_catalyst_theme_short_trade_carryover_relief_config_fn: Callable[..., dict[str, Any] | None],
) -> dict[str, Any]:
    reason = "catalyst_theme_candidate_score_ranked"
    candidate_entry = build_catalyst_theme_entry_fn(item=item, reason=reason, rank=0)
    qualified, filter_reason, metrics_payload = qualifies_catalyst_theme_candidate_fn(
        trade_date=trade_date,
        entry=candidate_entry,
    )
    if not qualified:
        result: dict[str, Any] = {"qualified": False, "filter_reason": filter_reason, "shadow_ranked": None}
        if filter_reason != "metric_data_fail":
            shadow_entry = build_catalyst_theme_shadow_entry_fn(
                item=item,
                filter_reason=filter_reason,
                metrics_payload=metrics_payload,
            )
            result["shadow_ranked"] = (
                float(metrics_payload.get("candidate_score", 0.0) or 0.0),
                -float(shadow_entry.get("total_shortfall", 0.0) or 0.0),
                float(item.score_b),
                shadow_entry,
            )
        return result

    carryover_relief_config = build_catalyst_theme_short_trade_carryover_relief_config_fn(metrics_payload=metrics_payload)
    resolved_reason_codes = [
        str(code)
        for code in list(candidate_entry.get("candidate_reason_codes") or candidate_entry.get("reasons") or [])
        if str(code or "").strip()
    ]
    if carryover_relief_config and "catalyst_theme_short_trade_carryover_candidate" not in resolved_reason_codes:
        resolved_reason_codes.append("catalyst_theme_short_trade_carryover_candidate")

    return {
        "qualified": True,
        "filter_reason": filter_reason,
        "candidate_ranked": (
            float(metrics_payload.get("candidate_score", 0.0) or 0.0),
            float(item.score_b),
            {
                **candidate_entry,
                "reasons": resolved_reason_codes,
                "candidate_reason_codes": resolved_reason_codes,
                "score_target": float(metrics_payload.get("candidate_score", 0.0) or 0.0),
                "confidence": round(min(1.0, max(0.0, float(metrics_payload.get("candidate_score", 0.0) or 0.0))), 4),
                "top_reasons": [
                    f"catalyst_freshness={float(metrics_payload.get('catalyst_freshness', 0.0) or 0.0):.2f}",
                    f"sector_resonance={float(metrics_payload.get('sector_resonance', 0.0) or 0.0):.2f}",
                    f"candidate_score={float(metrics_payload.get('candidate_score', 0.0) or 0.0):.2f}",
                ],
                "positive_tags": list(metrics_payload.get("theme_tags") or []),
                "gate_status": dict(metrics_payload.get("gate_status") or {}),
                "blockers": list(metrics_payload.get("blockers") or []),
                "metrics": {
                    "breakout_freshness": metrics_payload.get("breakout_freshness"),
                    "trend_acceleration": metrics_payload.get("trend_acceleration"),
                    "close_strength": metrics_payload.get("close_strength"),
                    "sector_resonance": metrics_payload.get("sector_resonance"),
                    "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
                },
                "promotion_trigger": "若催化继续扩散并形成量价确认，可升级到 short-trade shadow 观察。",
                "catalyst_theme_metrics": metrics_payload,
                **({"short_trade_catalyst_relief": carryover_relief_config} if carryover_relief_config else {}),
            },
        ),
    }


def build_catalyst_theme_short_trade_carryover_relief_config(
    *,
    metrics_payload: dict[str, Any],
    candidate_score_min: float,
    breakout_min: float,
    trend_min: float,
    close_min: float,
    catalyst_freshness_floor: float,
    near_miss_threshold: float,
    min_historical_evaluable_count: int,
    require_no_profitability_hard_cliff: bool,
) -> dict[str, Any]:
    close_momentum_catalyst_relief = dict(metrics_payload.get("close_momentum_catalyst_relief") or {})
    if not bool(close_momentum_catalyst_relief.get("applied")):
        return {}

    candidate_score = float(metrics_payload.get("candidate_score", 0.0) or 0.0)
    breakout_freshness = float(metrics_payload.get("breakout_freshness", 0.0) or 0.0)
    trend_acceleration = float(metrics_payload.get("trend_acceleration", 0.0) or 0.0)
    close_strength = float(metrics_payload.get("close_strength", 0.0) or 0.0)
    if candidate_score < candidate_score_min:
        return {}
    if breakout_freshness < breakout_min:
        return {}
    if trend_acceleration < trend_min:
        return {}
    if close_strength < close_min:
        return {}

    return {
        "enabled": True,
        "reason": "catalyst_theme_short_trade_carryover",
        "catalyst_freshness_floor": round(catalyst_freshness_floor, 4),
        "near_miss_threshold": round(near_miss_threshold, 4),
        "breakout_freshness_min": round(breakout_min, 4),
        "trend_acceleration_min": round(trend_min, 4),
        "close_strength_min": round(close_min, 4),
        "min_historical_evaluable_count": int(min_historical_evaluable_count),
        "require_no_profitability_hard_cliff": require_no_profitability_hard_cliff,
    }


def build_catalyst_theme_candidate_diagnostics_payload(
    *,
    upstream_candidates: list[Any],
    entries: list[dict[str, Any]],
    shadow_entries: list[dict[str, Any]],
    reason_counts: dict[str, int],
    filtered_reason_counts: dict[str, int],
    prefilter_thresholds: dict[str, Any],
    max_candidates: int,
) -> dict[str, Any]:
    return {
        "upstream_candidate_count": len(upstream_candidates),
        "candidate_count": len(entries),
        "shadow_candidate_count": len(shadow_entries),
        "reason_counts": reason_counts,
        "filtered_reason_counts": filtered_reason_counts,
        "prefilter_thresholds": prefilter_thresholds,
        "selected_tickers": [entry["ticker"] for entry in entries],
        "shadow_tickers": [entry["ticker"] for entry in shadow_entries],
        "max_candidates": max_candidates,
        "tickers": entries,
        "shadow_candidates": shadow_entries,
    }


def finalize_catalyst_theme_candidate_diagnostics(
    *,
    upstream_candidates: list[Any],
    ranking_state: dict[str, Any],
    ranked_outputs: dict[str, Any],
    build_catalyst_theme_candidate_diagnostics_payload_fn: Callable[..., dict[str, Any]],
    build_catalyst_theme_prefilter_thresholds_fn: Callable[..., dict[str, Any]],
    catalyst_theme_candidate_score_min: float,
    catalyst_theme_breakout_min: float,
    catalyst_theme_close_min: float,
    catalyst_theme_sector_min: float,
    catalyst_theme_catalyst_min: float,
    short_trade_carryover_candidate_score_min: float,
    short_trade_carryover_catalyst_freshness_floor: float,
    short_trade_carryover_near_miss_threshold: float,
    short_trade_carryover_min_historical_evaluable_count: int,
    short_trade_carryover_require_no_profitability_hard_cliff: bool,
    max_candidates: int,
) -> dict[str, Any]:
    return build_catalyst_theme_candidate_diagnostics_payload_fn(
        upstream_candidates=upstream_candidates,
        entries=ranked_outputs["entries"],
        shadow_entries=ranked_outputs["shadow_entries"],
        reason_counts=ranked_outputs["reason_counts"],
        filtered_reason_counts=ranking_state["filtered_reason_counts"],
        prefilter_thresholds=build_catalyst_theme_prefilter_thresholds_fn(
            catalyst_theme_candidate_score_min=catalyst_theme_candidate_score_min,
            catalyst_theme_breakout_min=catalyst_theme_breakout_min,
            catalyst_theme_close_min=catalyst_theme_close_min,
            catalyst_theme_sector_min=catalyst_theme_sector_min,
            catalyst_theme_catalyst_min=catalyst_theme_catalyst_min,
            short_trade_carryover_candidate_score_min=short_trade_carryover_candidate_score_min,
            short_trade_carryover_catalyst_freshness_floor=short_trade_carryover_catalyst_freshness_floor,
            short_trade_carryover_near_miss_threshold=short_trade_carryover_near_miss_threshold,
            short_trade_carryover_min_historical_evaluable_count=short_trade_carryover_min_historical_evaluable_count,
            short_trade_carryover_require_no_profitability_hard_cliff=short_trade_carryover_require_no_profitability_hard_cliff,
        ),
        max_candidates=max_candidates,
    )


def build_catalyst_theme_candidate_diagnostics(
    *,
    fused: list[Any],
    watchlist: list[Any],
    short_trade_candidate_diagnostics: dict[str, Any],
    trade_date: str,
    build_upstream_catalyst_theme_candidates_fn: Callable[..., list[Any]],
    collect_catalyst_theme_diagnostic_rankings_fn: Callable[..., dict[str, Any]],
    build_catalyst_theme_ranked_outputs_fn: Callable[..., dict[str, Any]],
    finalize_catalyst_theme_candidate_diagnostics_fn: Callable[..., dict[str, Any]],
    build_catalyst_theme_entry_fn: Callable[..., dict[str, Any]],
    qualifies_catalyst_theme_candidate_fn: Callable[..., tuple[bool, str, dict[str, Any]]],
    build_catalyst_theme_shadow_entry_fn: Callable[..., dict[str, Any]],
    build_catalyst_theme_short_trade_carryover_relief_config_fn: Callable[..., dict[str, Any] | None],
    build_catalyst_theme_candidate_diagnostics_payload_fn: Callable[..., dict[str, Any]],
    build_catalyst_theme_prefilter_thresholds_fn: Callable[..., dict[str, Any]],
    catalyst_theme_candidate_score_min: float,
    catalyst_theme_breakout_min: float,
    catalyst_theme_close_min: float,
    catalyst_theme_sector_min: float,
    catalyst_theme_catalyst_min: float,
    short_trade_carryover_candidate_score_min: float,
    short_trade_carryover_catalyst_freshness_floor: float,
    short_trade_carryover_near_miss_threshold: float,
    short_trade_carryover_min_historical_evaluable_count: int,
    short_trade_carryover_require_no_profitability_hard_cliff: bool,
    catalyst_theme_max_tickers: int,
    catalyst_theme_shadow_max_tickers: int,
) -> dict[str, Any]:
    upstream_candidates = build_upstream_catalyst_theme_candidates_fn(
        fused=fused,
        watchlist=watchlist,
        short_trade_candidate_diagnostics=short_trade_candidate_diagnostics,
    )
    ranking_state = collect_catalyst_theme_diagnostic_rankings_fn(
        upstream_candidates=upstream_candidates,
        trade_date=trade_date,
        build_catalyst_theme_entry_fn=build_catalyst_theme_entry_fn,
        qualifies_catalyst_theme_candidate_fn=qualifies_catalyst_theme_candidate_fn,
        build_catalyst_theme_shadow_entry_fn=build_catalyst_theme_shadow_entry_fn,
        build_catalyst_theme_short_trade_carryover_relief_config_fn=build_catalyst_theme_short_trade_carryover_relief_config_fn,
    )
    ranked_outputs = build_catalyst_theme_ranked_outputs_fn(
        ranked_candidates=ranking_state["ranked_candidates"],
        ranked_shadow_candidates=ranking_state["ranked_shadow_candidates"],
        catalyst_theme_max_tickers=catalyst_theme_max_tickers,
        catalyst_theme_shadow_max_tickers=catalyst_theme_shadow_max_tickers,
    )
    return finalize_catalyst_theme_candidate_diagnostics_fn(
        upstream_candidates=upstream_candidates,
        ranking_state=ranking_state,
        ranked_outputs=ranked_outputs,
        build_catalyst_theme_candidate_diagnostics_payload_fn=build_catalyst_theme_candidate_diagnostics_payload_fn,
        build_catalyst_theme_prefilter_thresholds_fn=build_catalyst_theme_prefilter_thresholds_fn,
        catalyst_theme_candidate_score_min=catalyst_theme_candidate_score_min,
        catalyst_theme_breakout_min=catalyst_theme_breakout_min,
        catalyst_theme_close_min=catalyst_theme_close_min,
        catalyst_theme_sector_min=catalyst_theme_sector_min,
        catalyst_theme_catalyst_min=catalyst_theme_catalyst_min,
        short_trade_carryover_candidate_score_min=short_trade_carryover_candidate_score_min,
        short_trade_carryover_catalyst_freshness_floor=short_trade_carryover_catalyst_freshness_floor,
        short_trade_carryover_near_miss_threshold=short_trade_carryover_near_miss_threshold,
        short_trade_carryover_min_historical_evaluable_count=short_trade_carryover_min_historical_evaluable_count,
        short_trade_carryover_require_no_profitability_hard_cliff=short_trade_carryover_require_no_profitability_hard_cliff,
        max_candidates=catalyst_theme_max_tickers,
    )


def build_catalyst_theme_prefilter_thresholds(
    *,
    catalyst_theme_candidate_score_min: float,
    catalyst_theme_breakout_min: float,
    catalyst_theme_close_min: float,
    catalyst_theme_sector_min: float,
    catalyst_theme_catalyst_min: float,
    short_trade_carryover_candidate_score_min: float,
    short_trade_carryover_catalyst_freshness_floor: float,
    short_trade_carryover_near_miss_threshold: float,
    short_trade_carryover_min_historical_evaluable_count: int,
    short_trade_carryover_require_no_profitability_hard_cliff: bool,
) -> dict[str, Any]:
    return {
        "candidate_score_min": round(catalyst_theme_candidate_score_min, 4),
        "breakout_freshness_min": round(catalyst_theme_breakout_min, 4),
        "close_strength_min": round(catalyst_theme_close_min, 4),
        "sector_resonance_min": round(catalyst_theme_sector_min, 4),
        "catalyst_freshness_min": round(catalyst_theme_catalyst_min, 4),
        "short_trade_carryover_candidate_score_min": round(short_trade_carryover_candidate_score_min, 4),
        "short_trade_carryover_catalyst_freshness_floor": round(short_trade_carryover_catalyst_freshness_floor, 4),
        "short_trade_carryover_near_miss_threshold": round(short_trade_carryover_near_miss_threshold, 4),
        "short_trade_carryover_min_historical_evaluable_count": int(short_trade_carryover_min_historical_evaluable_count),
        "short_trade_carryover_require_no_profitability_hard_cliff": short_trade_carryover_require_no_profitability_hard_cliff,
    }


# ---------------------------------------------------------------------------
# Catalyst theme wrapper functions (moved from daily_pipeline.py)
# These collapse the previous wrapper → _impl delegation pattern by calling
# the impl functions directly since they now live in the same module.
# ---------------------------------------------------------------------------


def _build_catalyst_theme_entry(*, item: Any, reason: str, rank: int) -> dict[str, Any]:
    score_c, agent_contribution_summary = _build_catalyst_theme_agent_contribution_summary(item)
    return {
        "ticker": item.ticker,
        "decision": "catalyst_theme",
        "score_b": round(float(item.score_b), 4),
        "score_c": score_c,
        "score_final": round(float(item.score_b), 4),
        "quality_score": round(float(_derive_quality_score(item)), 4),
        "market_state": _serialize_market_state(item),
        "preferred_entry_mode": "theme_research_followup",
        "reason": reason,
        "reasons": [reason, "catalyst_theme_research_candidate"],
        "candidate_source": "catalyst_theme",
        "upstream_candidate_source": "layer_b_fused_universe",
        "candidate_reason_codes": [reason, "catalyst_theme_research_candidate"],
        "strategy_signals": {name: signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {}) for name, signal in dict(item.strategy_signals or {}).items()},
        "agent_contribution_summary": agent_contribution_summary,
        "rank": rank,
    }


def _compute_catalyst_theme_candidate_score(snapshot: dict[str, Any]) -> float:
    return round(
        (0.40 * float(snapshot.get("catalyst_freshness", 0.0) or 0.0)) + (0.25 * float(snapshot.get("sector_resonance", 0.0) or 0.0)) + (0.15 * float(snapshot.get("breakout_freshness", 0.0) or 0.0)) + (0.10 * float(snapshot.get("close_strength", 0.0) or 0.0)) + (0.10 * float(snapshot.get("trend_acceleration", 0.0) or 0.0)),
        4,
    )


def _resolve_catalyst_theme_close_momentum_relief(
    *,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    catalyst_freshness: float,
) -> dict[str, Any]:
    return resolve_catalyst_theme_close_momentum_relief(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        catalyst_freshness=catalyst_freshness,
        catalyst_theme_catalyst_min=CATALYST_THEME_CATALYST_MIN,
        catalyst_theme_close_momentum_relief_breakout_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN,
        catalyst_theme_close_momentum_relief_trend_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN,
        catalyst_theme_close_momentum_relief_close_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN,
        catalyst_theme_close_momentum_relief_sector_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_SECTOR_MIN,
        catalyst_theme_sector_min=CATALYST_THEME_SECTOR_MIN,
    )


def _compute_catalyst_theme_threshold_shortfalls(metric_values: dict[str, Any], threshold_checks: dict[str, float] | None = None) -> dict[str, float]:
    return compute_catalyst_theme_threshold_shortfalls(
        metric_values=metric_values,
        threshold_checks=threshold_checks,
        catalyst_theme_candidate_score_min=CATALYST_THEME_CANDIDATE_SCORE_MIN,
        catalyst_theme_breakout_min=CATALYST_THEME_BREAKOUT_MIN,
        catalyst_theme_close_min=CATALYST_THEME_CLOSE_MIN,
        catalyst_theme_sector_min=CATALYST_THEME_SECTOR_MIN,
        catalyst_theme_catalyst_min=CATALYST_THEME_CATALYST_MIN,
    )


def _build_catalyst_theme_shadow_entry(*, item: Any, filter_reason: str, metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return build_catalyst_theme_shadow_entry(
        item=item,
        filter_reason=filter_reason,
        metrics_payload=metrics_payload,
        build_catalyst_theme_entry_fn=_build_catalyst_theme_entry,
        compute_threshold_shortfalls_fn=_compute_catalyst_theme_threshold_shortfalls,
    )


def _qualifies_catalyst_theme_candidate(*, trade_date: str, entry: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    snapshot = build_short_trade_target_snapshot_from_entry(trade_date=trade_date, entry=entry)
    if "quality_score" not in snapshot:
        snapshot = {
            **snapshot,
            "quality_score": float(entry.get("quality_score", 0.5) or 0.5),
        }
    return qualify_catalyst_theme_candidate_from_snapshot(
        snapshot=snapshot,
        resolve_close_momentum_relief_fn=_resolve_catalyst_theme_close_momentum_relief,
        compute_candidate_score_fn=_compute_catalyst_theme_candidate_score,
        catalyst_theme_sector_min=CATALYST_THEME_SECTOR_MIN,
        catalyst_theme_candidate_score_min=CATALYST_THEME_CANDIDATE_SCORE_MIN,
        catalyst_theme_breakout_min=CATALYST_THEME_BREAKOUT_MIN,
        catalyst_theme_close_min=CATALYST_THEME_CLOSE_MIN,
        catalyst_theme_catalyst_min=CATALYST_THEME_CATALYST_MIN,
        catalyst_theme_quality_min=CATALYST_THEME_QUALITY_MIN,
    )


def _build_catalyst_theme_short_trade_carryover_relief_config(*, metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return build_catalyst_theme_short_trade_carryover_relief_config(
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


def _build_catalyst_theme_candidate_diagnostics(
    fused: list[Any],
    watchlist: list[Any],
    short_trade_candidate_diagnostics: dict[str, Any],
    trade_date: str,
) -> dict[str, Any]:
    return build_catalyst_theme_candidate_diagnostics(
        fused=fused,
        watchlist=watchlist,
        short_trade_candidate_diagnostics=short_trade_candidate_diagnostics,
        trade_date=trade_date,
        build_upstream_catalyst_theme_candidates_fn=build_upstream_catalyst_theme_candidates,
        collect_catalyst_theme_diagnostic_rankings_fn=collect_catalyst_theme_diagnostic_rankings,
        build_catalyst_theme_ranked_outputs_fn=build_catalyst_theme_ranked_outputs,
        finalize_catalyst_theme_candidate_diagnostics_fn=finalize_catalyst_theme_candidate_diagnostics,
        build_catalyst_theme_entry_fn=_build_catalyst_theme_entry,
        qualifies_catalyst_theme_candidate_fn=_qualifies_catalyst_theme_candidate,
        build_catalyst_theme_shadow_entry_fn=_build_catalyst_theme_shadow_entry,
        build_catalyst_theme_short_trade_carryover_relief_config_fn=_build_catalyst_theme_short_trade_carryover_relief_config,
        build_catalyst_theme_candidate_diagnostics_payload_fn=build_catalyst_theme_candidate_diagnostics_payload,
        build_catalyst_theme_prefilter_thresholds_fn=build_catalyst_theme_prefilter_thresholds,
        catalyst_theme_candidate_score_min=CATALYST_THEME_CANDIDATE_SCORE_MIN,
        catalyst_theme_breakout_min=CATALYST_THEME_BREAKOUT_MIN,
        catalyst_theme_close_min=CATALYST_THEME_CLOSE_MIN,
        catalyst_theme_sector_min=CATALYST_THEME_SECTOR_MIN,
        catalyst_theme_catalyst_min=CATALYST_THEME_CATALYST_MIN,
        short_trade_carryover_candidate_score_min=CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN,
        short_trade_carryover_catalyst_freshness_floor=CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR,
        short_trade_carryover_near_miss_threshold=CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD,
        short_trade_carryover_min_historical_evaluable_count=CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT,
        short_trade_carryover_require_no_profitability_hard_cliff=CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF,
        catalyst_theme_max_tickers=CATALYST_THEME_MAX_TICKERS,
        catalyst_theme_shadow_max_tickers=CATALYST_THEME_SHADOW_MAX_TICKERS,
    )
