from __future__ import annotations

import logging
from typing import Any, Callable

from src.execution.models import LayerCResult
from src.targets.models import TargetEvaluationInput

_logger = logging.getLogger(__name__)


def build_item_replay_context(
    item: LayerCResult,
    *,
    normalized_reason_codes_fn: Callable[[Any], list[str]],
) -> dict[str, Any]:
    candidate_source = str(getattr(item, "candidate_source", "") or "layer_c_watchlist")
    explicit_metric_overrides: dict[str, Any] = {}
    if candidate_source == "catalyst_theme":
        explicit_metric_overrides = dict(getattr(item, "catalyst_theme_metrics", None) or getattr(item, "metrics", None) or {})
    return {
        "source": candidate_source,
        "reason": str(getattr(item, "reason", "") or ""),
        "candidate_reason_codes": normalized_reason_codes_fn(getattr(item, "candidate_reason_codes", [])),
        "historical_prior": dict(getattr(item, "historical_prior", {}) or {}),
        "candidate_pool_lane": str(getattr(item, "candidate_pool_lane", "") or ""),
        "candidate_pool_shadow_reason": str(getattr(item, "candidate_pool_shadow_reason", "") or ""),
        "shadow_visibility_gap_selected": bool(getattr(item, "shadow_visibility_gap_selected", False)),
        "shadow_visibility_gap_relaxed_band": bool(getattr(item, "shadow_visibility_gap_relaxed_band", False)),
        "short_trade_catalyst_relief": dict(getattr(item, "short_trade_catalyst_relief", {}) or {}),
        "explicit_metric_overrides": explicit_metric_overrides,
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
    return TargetEvaluationInput(
        trade_date=trade_date,
        ticker=str(entry.get("ticker") or ""),
        market_state=dict(entry.get("market_state") or {}),
        score_b=float(entry.get("score_b", 0.0) or 0.0),
        score_c=float(entry.get("score_c", 0.0) or 0.0),
        score_final=float(entry.get("score_final", 0.0) or 0.0),
        quality_score=float(entry.get("quality_score", 0.5) or 0.5),
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
            "shadow_visibility_gap_selected": bool(entry.get("shadow_visibility_gap_selected")),
            "shadow_visibility_gap_relaxed_band": bool(entry.get("shadow_visibility_gap_relaxed_band")),
            "short_trade_catalyst_relief": dict(entry.get("short_trade_catalyst_relief") or {}),
            "explicit_metric_overrides": explicit_metric_overrides,
        },
    )


def _extract_strategy_signals(raw_signals: Any, ticker: str, *, source: str) -> dict[str, Any]:
    signals = dict(raw_signals or {})
    if not signals:
        _logger.warning("strategy_signals is empty for ticker=%s source=%s — snapshot scoring will use neutral defaults", ticker, source)
    return signals
