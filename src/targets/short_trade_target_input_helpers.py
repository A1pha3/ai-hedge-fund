from __future__ import annotations

import logging
from typing import Any
from collections.abc import Callable

from src.execution.models import LayerCResult
from src.targets.short_trade_target_kill_switch_helpers import extract_btst_kill_switch_metrics
from src.targets.models import TargetEvaluationInput

_logger = logging.getLogger(__name__)


def _merge_market_state_kill_switch_metrics(raw_candidate_metrics: dict[str, Any], market_state: dict[str, Any] | None) -> dict[str, Any]:
    merged_metrics = dict(raw_candidate_metrics or {})
    for key, value in extract_btst_kill_switch_metrics(market_state).items():
        merged_metrics.setdefault(key, value)
    return merged_metrics


def build_item_replay_context(
    item: LayerCResult,
    *,
    normalized_reason_codes_fn: Callable[[Any], list[str]],
) -> dict[str, Any]:
    candidate_source = str(getattr(item, "candidate_source", "") or "layer_c_watchlist")
    explicit_metric_overrides: dict[str, Any] = {}
    if candidate_source == "catalyst_theme":
        explicit_metric_overrides = dict(getattr(item, "catalyst_theme_metrics", None) or getattr(item, "metrics", None) or {})
    market_state = dict(getattr(item, "market_state", {}) or {})
    return {
        "source": candidate_source,
        "reason": str(getattr(item, "reason", "") or ""),
        "candidate_reason_codes": normalized_reason_codes_fn(getattr(item, "candidate_reason_codes", [])),
        "historical_prior": dict(getattr(item, "historical_prior", {}) or {}),
        "candidate_pool_lane": str(getattr(item, "candidate_pool_lane", "") or ""),
        "candidate_pool_shadow_reason": str(getattr(item, "candidate_pool_shadow_reason", "") or ""),
        "candidate_pool_rank": int(getattr(item, "candidate_pool_rank", 0) or 0),
        "candidate_pool_avg_amount_share_of_cutoff": float(getattr(item, "candidate_pool_avg_amount_share_of_cutoff", 0.0) or 0.0),
        "shadow_focus_selected": bool(getattr(item, "shadow_focus_selected", False)),
        "shadow_focus_relaxed_band": bool(getattr(item, "shadow_focus_relaxed_band", False)),
        "shadow_visibility_gap_selected": bool(getattr(item, "shadow_visibility_gap_selected", False)),
        "shadow_visibility_gap_relaxed_band": bool(getattr(item, "shadow_visibility_gap_relaxed_band", False)),
        "source_layer_release_stage": str(getattr(item, "source_layer_release_stage", "") or ""),
        "source_layer_release_reason": str(getattr(item, "source_layer_release_reason", "") or ""),
        "short_trade_catalyst_relief": dict(getattr(item, "short_trade_catalyst_relief", {}) or {}),
        "explicit_metric_overrides": explicit_metric_overrides,
        "raw_candidate_metrics": _merge_market_state_kill_switch_metrics(
            dict(getattr(item, "metrics", {}) or {}),
            market_state,
        ),
        "projected_theme_exposure": float(getattr(item, "projected_theme_exposure", 0.0) or 0.0),
        "incremental_theme_exposure": float(getattr(item, "incremental_theme_exposure", 0.0) or 0.0),
    }


def build_target_input_from_item(
    *,
    trade_date: str,
    item: LayerCResult,
    included_in_buy_orders: bool,
    build_item_replay_context_fn: Callable[[LayerCResult], dict[str, Any]],
) -> TargetEvaluationInput:
    return TargetEvaluationInput(
        trade_date=trade_date,
        ticker=item.ticker,
        market_state=dict(getattr(item, "market_state", {}) or {}),
        score_b=float(item.score_b),
        score_c=float(item.score_c),
        score_final=float(item.score_final),
        quality_score=float(item.quality_score),
        layer_c_decision=str(item.decision or ""),
        bc_conflict=item.bc_conflict,
        strategy_signals=_extract_strategy_signals(item.strategy_signals, item.ticker, source="layer_c_result"),
        agent_contribution_summary=dict(item.agent_contribution_summary or {}),
        execution_constraints={"included_in_buy_orders": bool(included_in_buy_orders)},
        replay_context=build_item_replay_context_fn(item),
    )


def build_target_input_from_entry(
    *,
    trade_date: str,
    entry: dict[str, Any],
    normalized_reason_codes_fn: Callable[[Any], list[str]],
) -> TargetEvaluationInput:
    candidate_reason_codes = normalized_reason_codes_fn(entry.get("candidate_reason_codes", entry.get("reasons", [])))
    candidate_source = str(entry.get("candidate_source") or "watchlist_filter_diagnostics")
    explicit_metric_overrides: dict[str, Any] = {}
    if candidate_source == "catalyst_theme":
        explicit_metric_overrides = dict(entry.get("catalyst_theme_metrics") or entry.get("metrics") or {})
    market_state = dict(entry.get("market_state") or {})
    raw_candidate_metrics = dict(entry.get("short_trade_boundary_metrics") or {})
    raw_candidate_metrics.update(dict(entry.get("metrics") or {}))
    return TargetEvaluationInput(
        trade_date=trade_date,
        ticker=str(entry.get("ticker") or ""),
        market_state=market_state,
        score_b=float(entry.get("score_b", 0.0) or 0.0),
        score_c=float(entry.get("score_c", 0.0) or 0.0),
        score_final=float(entry.get("score_final", 0.0) or 0.0),
        # NOTE: 0.0 是合法 quality_score (最低质量), 不能用 `or 0.5` 静默覆盖。
        quality_score=float(entry.get("quality_score")) if entry.get("quality_score") is not None else 0.5,
        layer_c_decision=str(entry.get("decision") or ""),
        bc_conflict=entry.get("bc_conflict"),
        strategy_signals=_extract_strategy_signals(entry.get("strategy_signals"), entry.get("ticker", "unknown"), source="entry_dict"),
        agent_contribution_summary=dict(entry.get("agent_contribution_summary") or {}),
        replay_context={
            "source": candidate_source,
            "reason": str(entry.get("reason") or ""),
            "candidate_reason_codes": candidate_reason_codes,
            "historical_prior": dict(entry.get("historical_prior") or {}),
            "candidate_pool_lane": str(entry.get("candidate_pool_lane") or ""),
            "candidate_pool_shadow_reason": str(entry.get("candidate_pool_shadow_reason") or ""),
            "candidate_pool_rank": int(entry.get("candidate_pool_rank", 0) or 0),
            "candidate_pool_avg_amount_share_of_cutoff": float(entry.get("candidate_pool_avg_amount_share_of_cutoff", 0.0) or 0.0),
            "shadow_focus_selected": bool(entry.get("shadow_focus_selected")),
            "shadow_focus_relaxed_band": bool(entry.get("shadow_focus_relaxed_band")),
            "shadow_visibility_gap_selected": bool(entry.get("shadow_visibility_gap_selected")),
            "shadow_visibility_gap_relaxed_band": bool(entry.get("shadow_visibility_gap_relaxed_band")),
            "source_layer_release_stage": str(entry.get("source_layer_release_stage") or ""),
            "source_layer_release_reason": str(entry.get("source_layer_release_reason") or ""),
            "short_trade_catalyst_relief": dict(entry.get("short_trade_catalyst_relief") or {}),
            "explicit_metric_overrides": explicit_metric_overrides,
            "raw_candidate_metrics": _merge_market_state_kill_switch_metrics(raw_candidate_metrics, market_state),
            "projected_theme_exposure": float(entry.get("projected_theme_exposure", 0.0) or 0.0),
            "incremental_theme_exposure": float(entry.get("incremental_theme_exposure", 0.0) or 0.0),
        },
    )


def _extract_strategy_signals(raw_signals: Any, ticker: str, *, source: str) -> dict[str, Any]:
    signals = dict(raw_signals or {})
    if not signals:
        _logger.warning("strategy_signals is empty for ticker=%s source=%s — snapshot scoring will use neutral defaults", ticker, source)
    return signals
