"""日度执行流水线。"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from inspect import signature
from pathlib import Path
from time import perf_counter
from typing import Any

from scripts.btst_latest_followup_utils import (
    load_latest_btst_historical_prior_by_ticker,
    load_recent_btst_buy_order_cooldowns,
)
from src.execution.crisis_handler import evaluate_crisis_response
from src.execution.btst_shadow_promotion_helpers import resolve_btst_shadow_promotion_payload
from src.execution.daily_pipeline_buy_diagnostics_helpers import (
    _enforce_btst_daily_trade_limit,
    build_buy_orders_with_diagnostics as build_buy_orders_with_diagnostics_impl,
)
from src.execution.daily_pipeline_buy_diagnostics_helpers import (
    _apply_btst_risk_budget_overlay_to_plan,
    _resolve_btst_position_budget,
    build_reentry_filter_payload,
)
from src.execution.daily_pipeline_catalyst_diagnostics_helpers import (
    _build_catalyst_theme_candidate_diagnostics,
    _build_catalyst_theme_entry,
    _build_catalyst_theme_shadow_entry,
    _compute_catalyst_theme_candidate_score,
    _compute_catalyst_theme_threshold_shortfalls,
    _qualifies_catalyst_theme_candidate,
    _resolve_catalyst_theme_close_momentum_relief,
    build_catalyst_theme_candidate_diagnostics_payload,
    build_catalyst_theme_prefilter_thresholds,
    build_catalyst_theme_ranked_outputs,
    build_upstream_catalyst_theme_candidates,
    collect_catalyst_theme_diagnostic_rankings,
    finalize_catalyst_theme_candidate_diagnostics,
)
from src.execution.daily_pipeline_historical_prior_attachment import (
    attach_historical_prior_to_entries as _attach_historical_prior_to_entries_impl,
)
from src.execution.daily_pipeline_historical_prior_attachment import (
    attach_historical_prior_to_watchlist as _attach_historical_prior_to_watchlist,
)
from src.execution.daily_pipeline_merge_approved_wrappers import (
    _apply_merge_approved_breakout_signal_uplift,
    _apply_merge_approved_fused_boost,
    _apply_merge_approved_layer_c_alignment_uplift,
    _apply_merge_approved_sector_resonance_uplift,
    _build_layer_b_filter_diagnostics,
    _build_merge_approved_watchlist,
    _build_watchlist_filter_diagnostics,
    _tag_merge_approved_layer_c_results,
)
from src.execution.daily_pipeline_phase4_entry_helpers import (  # noqa: F401 — re-exported for scripts
    _build_upstream_shadow_observation_entry,
)
from src.execution.daily_pipeline_phase4_test_adapter import (
    run_with_phase4_test_overrides,
    sync_phase4_test_overrides,
)
from src.execution.daily_pipeline_post_market_helpers import (
    aggregate_post_market_diagnostics,
    build_high_pool,
    build_post_market_execution_plan,
    build_selection_target_inputs,
)
from src.execution.daily_pipeline_post_market_helpers import (
    build_sell_order_diagnostics as build_sell_order_diagnostics_impl,
)
from src.execution.daily_pipeline_post_market_helpers import (
    build_watchlist_price_map as build_watchlist_price_map_impl,
)
from src.execution.daily_pipeline_post_market_helpers import (
    ensure_plan_target_shells as ensure_plan_target_shells_impl,
)
from src.execution.daily_pipeline_post_market_helpers import (
    merge_agent_results,
    PostMarketCandidateContext,
    PostMarketDiagnosticsAggregation,
    PostMarketOrderContext,
    PostMarketSelectionResolution,
    PostMarketWatchlistContext,
    resolve_post_market_selection_targets,
)
from src.execution.daily_pipeline_runtime_helpers import (
    build_filter_summary as _build_filter_summary_impl,
)
from src.execution.daily_pipeline_runtime_helpers import (
    default_exit_checker as _default_exit_checker_impl,
)
from src.execution.daily_pipeline_runtime_helpers import (
    load_candidate_pool_bundle as _load_candidate_pool_bundle_impl,
)
from src.execution.daily_pipeline_runtime_helpers import (
    load_latest_historical_prior_by_ticker as _load_latest_historical_prior_by_ticker_impl,
)
from src.execution.daily_pipeline_runtime_helpers import (
    resolve_historical_prior_for_ticker as _resolve_historical_prior_for_ticker_impl,
)
from src.execution.daily_pipeline_settings import (  # noqa: F401 — re-exported for tests
    UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS,
)
from src.execution.daily_pipeline_settings import (  # noqa: F401 — re-exported for tests
    UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS,
)
from src.execution.daily_pipeline_settings import (  # noqa: F401 — re-exported for tests
    UPSTREAM_SHADOW_RELEASE_MAX_TICKERS,
)
from src.execution.daily_pipeline_settings import (  # noqa: F401 — re-exported for tests
    UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE,
)
from src.execution.daily_pipeline_settings import (  # noqa: F401 — re-exported for tests
    UPSTREAM_SHADOW_WATCHLIST_PROMOTION_LANES,
)
from src.execution.daily_pipeline_settings import (  # noqa: F401 — re-exported for tests
    UPSTREAM_SHADOW_WATCHLIST_PROMOTION_MAX_TICKERS,
)
from src.execution.daily_pipeline_settings import (
    BTST_REPORTS_ROOT,
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
    CONTINUATION_EXECUTION_ENABLED,
    CONTINUATION_WATCHLIST_EDGE_EXECUTION_RATIO,
    CONTINUATION_WATCHLIST_MIN_SCORE,
    EXIT_REENTRY_CONFIRM_SCORE_MIN,
    EXIT_REENTRY_WEAK_CONFIRMATION_SCORE_MIN,
    FAST_AGENT_MAX_TICKERS,
    FAST_AGENT_SCORE_THRESHOLD,
    MERGE_APPROVED_MERGE_REVIEW_PATH,
    MERGE_APPROVED_RANKING_PATH,
    MERGE_APPROVED_SCORE_BOOST,
    MERGE_APPROVED_TICKERS,
    MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION,
    PRECISE_AGENT_MAX_TICKERS,
    WATCHLIST_SCORE_THRESHOLD,
)
from src.execution.daily_pipeline_short_trade_diagnostics_helpers import (
    _qualifies_short_trade_boundary_candidate as _qualifies_short_trade_boundary_candidate_impl,
)
from src.execution.daily_pipeline_short_trade_diagnostics_helpers import (
    build_short_trade_candidate_diagnostics_with_defaults as _build_short_trade_candidate_diagnostics_impl,
)

# Re-exported for test access (tests/execution/test_phase4_execution.py)
from src.execution.daily_pipeline_upstream_shadow_helpers import (
    _build_catalyst_theme_short_trade_carryover_relief_config,
    _build_upstream_shadow_catalyst_relief_config,
    _build_upstream_shadow_catalyst_relief_payload_kwargs,
    _build_upstream_shadow_catalyst_relief_threshold_inputs,
    _build_upstream_shadow_release_entry,
    _build_upstream_shadow_watchlist_entry,
    _build_upstream_shadow_watchlist_reason_codes,
    _coerce_upstream_shadow_strategy_signal,
    _compute_short_trade_boundary_candidate_score,
    _extract_upstream_shadow_catalyst_relief_metrics,
    _mark_upstream_shadow_watchlist_promotions,
    _merge_watchlist_with_upstream_shadow_promotions,
    _parse_optional_float,
    _passes_upstream_shadow_catalyst_relief_gates,
    _passes_upstream_shadow_release_quality_floor,
    _resolve_upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff,
    _resolve_upstream_shadow_release_max_tickers,
    _resolve_upstream_shadow_release_priority_rank,
    _resolve_upstream_shadow_selected_threshold,
)
from src.execution.daily_pipeline_upstream_shadow_helpers import (  # noqa: F401
    _select_upstream_shadow_release_entries as _select_upstream_shadow_release_entries_impl,
)
from src.execution.daily_pipeline_upstream_shadow_helpers import (
    _select_upstream_shadow_watchlist_entries,
    _should_promote_upstream_shadow_release_to_watchlist,
)
from src.execution.daily_pipeline_upstream_shadow_helpers import (
    _should_release_upstream_shadow_candidate as _should_release_upstream_shadow_candidate_impl,
)
from src.execution.daily_pipeline_upstream_shadow_helpers import (
    _summarize_upstream_shadow_release_historical_support,
    _supports_upstream_shadow_catalyst_relief_history,
    _upstream_shadow_watchlist_promotion_sort_key,
)
from src.execution.layer_c_aggregator import aggregate_layer_c_results
from src.execution.merge_approved_loader import load_merge_approved_tickers
from src.execution.models import ExecutionPlan, LayerCResult
from src.execution.plan_generator import generate_execution_plan
from src.execution.signal_decay import apply_signal_decay
from src.execution.t1_confirmation import confirm_buy_signal
from src.llm.defaults import get_default_model_config
from src.portfolio.exit_manager import check_exit_signal
from src.portfolio.models import HoldingState
from src.portfolio.position_calculator import calculate_position
from src.screening.candidate_pool import (
    build_candidate_pool,
    build_candidate_pool_with_shadow,
)
from src.screening.market_state import detect_market_state
from src.screening.models import CandidateStock
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import _build_intraday_short_trade_metrics
from src.screening.strategy_scorer import score_batch
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetMode
from src.targets.early_runner_runtime_adapter import build_runtime_supplemental_entries
from src.targets.profiles import (
    build_short_trade_target_profile,
    use_short_trade_target_profile,
)
from src.targets.router import (
    _P2_BLOCKED_GATES,
    apply_p2_regime_gate_enforcement_to_selection_targets,
    build_selection_targets,
    summarize_selection_targets,
)
from src.targets.short_trade_target import (  # noqa: F401 — re-exported for scripts/tests
    build_short_trade_target_snapshot_from_entry,
)
from src.tools.ashare_board_utils import to_tushare_code
from src.tools.tushare_api import get_daily_basic_batch

AgentRunner = Callable[[list[str], str, str], dict[str, dict[str, dict]]]
ExitChecker = Callable[..., list]
_ORIGINAL_BUILD_CANDIDATE_POOL = build_candidate_pool
_EARLY_RUNNER_RUNTIME_ARTIFACT = Path("data/reports/btst_early_runner_v1_latest.json")


def _load_early_runner_runtime_entries(trade_date: str) -> list[dict[str, Any]]:
    """Load confirmed early-runner entries and adapt them into runtime supplemental entries."""
    artifact_path = _EARLY_RUNNER_RUNTIME_ARTIFACT.expanduser().resolve()
    if not artifact_path.exists():
        return []
    try:
        analysis = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return build_runtime_supplemental_entries(analysis, trade_date=trade_date, require_tradeable_gate=True)
_ORIGINAL_BUILD_CANDIDATE_POOL_WITH_SHADOW = build_candidate_pool_with_shadow
WEAK_CONFIRMATION_REENTRY_NEGATIVE_TAGS = frozenset(
    {
        "watchlist_zero_catalyst_penalty_applied",
        "watchlist_zero_catalyst_crowded_penalty_applied",
        "watchlist_zero_catalyst_flat_trend_penalty_applied",
    }
)
WEAK_CONFIRMATION_REENTRY_GUARD_KEYS = (
    "watchlist_zero_catalyst_guard",
    "watchlist_zero_catalyst_crowded_guard",
    "watchlist_zero_catalyst_flat_trend_guard",
)
BTST_0422_P1_REGIME_GATE_MODE_ENV = "BTST_0422_P1_REGIME_GATE_MODE"
BTST_0422_P1_REGIME_GATE_MODES = frozenset({"off", "shadow"})
BTST_0422_P2_REGIME_GATE_MODE_ENV = "BTST_0422_P2_REGIME_GATE_MODE"
BTST_0422_P2_REGIME_GATE_MODES = frozenset({"off", "enforce"})
# _P2_BLOCKED_GATES is imported from src.targets.router (single source of truth)
BTST_0422_P3_PRIOR_QUALITY_MODE_ENV = "BTST_0422_P3_PRIOR_QUALITY_MODE"
BTST_0422_P3_PRIOR_QUALITY_MODES = frozenset({"off", "enforce"})
BTST_0422_P4_PRIOR_SHRINKAGE_MODE_ENV = "BTST_0422_P4_PRIOR_SHRINKAGE_MODE"
BTST_0422_P4_PRIOR_SHRINKAGE_MODES = frozenset({"off", "enforce"})
BTST_0422_P5_EXECUTION_CONTRACT_MODE_ENV = "BTST_0422_P5_EXECUTION_CONTRACT_MODE"
BTST_0422_P5_EXECUTION_CONTRACT_MODES = frozenset({"off", "enforce"})
BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE_ENV = "BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE"
BTST_0422_P6_RISK_BUDGET_MODE_ENV = "BTST_0422_P6_RISK_BUDGET_MODE"
BTST_0422_P6_RISK_BUDGET_MODES = frozenset({"off", "enforce"})


def _qualifies_short_trade_boundary_candidate(*, trade_date: str, entry: dict) -> tuple[bool, str, dict]:
    return run_with_phase4_test_overrides(_qualifies_short_trade_boundary_candidate_impl, globals(), trade_date=trade_date, entry=entry)


def _build_short_trade_candidate_diagnostics(*args, **kwargs):
    return run_with_phase4_test_overrides(_build_short_trade_candidate_diagnostics_impl, globals(), *args, **kwargs)


def _should_release_upstream_shadow_candidate(*args, **kwargs):
    return run_with_phase4_test_overrides(_should_release_upstream_shadow_candidate_impl, globals(), *args, **kwargs)


def _select_upstream_shadow_release_entries(*args, **kwargs):
    return run_with_phase4_test_overrides(_select_upstream_shadow_release_entries_impl, globals(), *args, **kwargs)


def _load_candidate_pool_bundle(trade_date: str) -> tuple[list[CandidateStock], list[CandidateStock], dict[str, Any]]:
    return _load_candidate_pool_bundle_impl(
        trade_date,
        build_candidate_pool=build_candidate_pool,
        build_candidate_pool_with_shadow=build_candidate_pool_with_shadow,
        original_build_candidate_pool=_ORIGINAL_BUILD_CANDIDATE_POOL,
        original_build_candidate_pool_with_shadow=_ORIGINAL_BUILD_CANDIDATE_POOL_WITH_SHADOW,
    )


def _resolve_pipeline_model_config(model_tier: str, base_model_name: str, base_model_provider: str) -> tuple[str, str]:
    """Resolves fast/precise pipeline model settings without silently switching providers."""
    provider_name = str(base_model_provider or "")
    model_name = str(base_model_name or "")

    if not provider_name or not model_name:
        default_model_name, default_model_provider = get_default_model_config()
        provider_name = provider_name or str(default_model_provider)
        model_name = model_name or str(default_model_name)

    if provider_name == "OpenAI" and model_name in {"gpt-4.1", "gpt-4.1-mini"}:
        return ("gpt-4.1-mini" if model_tier == "fast" else "gpt-4.1"), provider_name

    return model_name, provider_name


def _should_skip_precise_stage(base_model_name: str, base_model_provider: str) -> bool:
    """Skips precise reruns when fast/precise tiers resolve to the same config."""
    fast_model_name, fast_provider_name = _resolve_pipeline_model_config("fast", base_model_name, base_model_provider)
    precise_model_name, precise_provider_name = _resolve_pipeline_model_config("precise", base_model_name, base_model_provider)
    return fast_model_name == precise_model_name and fast_provider_name == precise_provider_name


def _estimate_skipped_precise_seconds(fast_agent_seconds: float, fast_ticker_count: int, skipped_precise_ticker_count: int) -> float:
    """Estimates the avoided precise-stage cost when the same model config would have been rerun."""
    if fast_ticker_count <= 0 or skipped_precise_ticker_count <= 0:
        return 0.0
    return fast_agent_seconds * (skipped_precise_ticker_count / fast_ticker_count)


def _build_logic_score_map(layer_c_results: list[LayerCResult]) -> dict[str, float]:
    return {item.ticker: float(item.score_final) for item in layer_c_results}


BTST_RUNTIME_EXIT_METRIC_KEYS = (
    "sector_amt_share",
    "sector_breadth_3",
    "follow_ratio_2",
    "catalyst_freshness",
    "flow_60",
    "persist_120",
    "close_support_30",
    "retention_proxy",
    "supply_pressure_60",
    "failed_breakout_10",
    "prior_retention_score",
)


def _extract_btst_runtime_exit_metrics(result: LayerCResult) -> dict[str, Any]:
    metrics = dict(result.metrics or {})
    return {key: metrics[key] for key in BTST_RUNTIME_EXIT_METRIC_KEYS if key in metrics}


def _attach_btst_runtime_exit_metrics_to_portfolio_snapshot(portfolio_snapshot: dict, layer_c_results: list[LayerCResult]) -> dict:
    positions = dict(portfolio_snapshot.get("positions", {}) or {})
    if not positions or not layer_c_results:
        return portfolio_snapshot

    runtime_metrics_by_ticker = {result.ticker: extracted_metrics for result in layer_c_results if (extracted_metrics := _extract_btst_runtime_exit_metrics(result))}
    if not runtime_metrics_by_ticker:
        return portfolio_snapshot

    for ticker, position in positions.items():
        if float(position.get("long", 0.0) or 0.0) <= 0:
            continue
        runtime_metrics = runtime_metrics_by_ticker.get(str(ticker))
        if runtime_metrics:
            position["btst_runtime_metrics"] = dict(runtime_metrics)
        else:
            position.pop("btst_runtime_metrics", None)
    return portfolio_snapshot


def resolve_default_fast_selected_analysts(
    *,
    selection_target: str,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
) -> list[str] | None:
    if fast_selected_analysts is not None:
        return list(fast_selected_analysts)
    if selected_analysts is not None:
        return None
    if str(selection_target or "").strip().lower() != "short_trade_only":
        return None
    return ["technical_analyst", "sentiment_analyst"]


def _resolve_btst_regime_gate_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P1_REGIME_GATE_MODES else "off"


def _build_btst_regime_gate_payload(market_state: Any | None) -> dict[str, Any]:
    if _resolve_btst_regime_gate_mode() == "off":
        return {}
    from src.screening.market_state_helpers import (
        classify_btst_regime_gate_from_market_state,
    )

    gate_payload = dict(classify_btst_regime_gate_from_market_state(market_state) or {})
    if not gate_payload:
        return {}
    gate_payload["mode"] = _resolve_btst_regime_gate_mode()
    return gate_payload


def _build_downstream_target_market_state_payload(market_state: Any | None) -> dict[str, Any]:
    if market_state is None:
        return {}
    if hasattr(market_state, "model_dump"):
        payload = dict(market_state.model_dump(mode="json") or {})
    elif isinstance(market_state, dict):
        payload = dict(market_state)
    else:
        return {}
    gate_payload = _build_btst_regime_gate_payload(payload)
    if gate_payload:
        payload["btst_regime_gate"] = dict(gate_payload)
    return payload


def _attach_downstream_target_market_state_payload(
    layer_c_results: list[LayerCResult],
    *,
    market_state: Any | None,
) -> list[LayerCResult]:
    market_state_payload = _build_downstream_target_market_state_payload(market_state)
    if not market_state_payload:
        return list(layer_c_results)
    attached_results: list[LayerCResult] = []
    for item in list(layer_c_results):
        merged_market_state = dict(getattr(item, "market_state", {}) or {})
        merged_market_state.pop("btst_regime_gate", None)
        merged_market_state.update(dict(market_state_payload))
        attached_results.append(item.model_copy(update={"market_state": merged_market_state}))
    return attached_results


def _attach_btst_regime_gate_shadow(plan: ExecutionPlan) -> ExecutionPlan:
    gate_payload = _build_btst_regime_gate_payload(getattr(plan, "market_state", None))
    if not gate_payload:
        return plan
    plan = plan.model_copy(deep=True)
    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    risk_metrics["btst_regime_gate"] = gate_payload
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    funnel_diagnostics["btst_regime_gate"] = gate_payload
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    return plan


def _resolve_btst_regime_gate_p2_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P2_REGIME_GATE_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P2_REGIME_GATE_MODES else "off"


def _get_or_classify_gate(plan: ExecutionPlan) -> str | None:
    """Return the gate string for P2 enforcement.

    Reuses the P1 gate payload already stored in risk_metrics when available;
    otherwise classifies independently from the plan's market_state.
    """
    existing_gate = str((plan.risk_metrics or {}).get("btst_regime_gate", {}).get("gate", "") or "").strip()
    if existing_gate:
        return existing_gate
    from src.screening.market_state_helpers import (
        classify_btst_regime_gate_from_market_state,
    )

    result = classify_btst_regime_gate_from_market_state(getattr(plan, "market_state", None))
    if not result:
        return None
    return str(result.get("gate", "") or "").strip() or None


def _enforce_btst_regime_gate_p2(plan: ExecutionPlan) -> ExecutionPlan:
    """P2 hard enforcement: clear buy_orders and mark selection_targets for halt / shadow_only days.

    Only active when BTST_0422_P2_REGIME_GATE_MODE=enforce.
    Preserves backward compatibility — off by default.
    Reuses the P1 gate payload from risk_metrics when already computed.
    Also updates plan.selection_targets to mark items as p2_execution_blocked (router-level semantic).
    """
    if _resolve_btst_regime_gate_p2_mode() != "enforce":
        return plan

    plan = plan.model_copy(deep=True)
    gate = _get_or_classify_gate(plan)
    if gate is None:
        return plan

    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})

    if gate in _P2_BLOCKED_GATES:
        selection_targets = dict(plan.selection_targets or {})
        shadow_promotion_tickers = {str(ticker) for ticker, evaluation in selection_targets.items() if resolve_btst_shadow_promotion_payload(evaluation=evaluation, gate=gate).get("eligible")}
        original_buy_orders = list(plan.buy_orders or [])
        retained_orders = [order for order in original_buy_orders if order.ticker in shadow_promotion_tickers]
        cleared_count = max(0, len(original_buy_orders) - len(retained_orders))
        cleared = cleared_count > 0
        plan.buy_orders = retained_orders
        enforcement_payload: dict[str, Any] = {
            "enforced": True,
            "gate": gate,
            "mode": "enforce",
            "buy_orders_cleared": cleared,
            "buy_orders_cleared_count": cleared_count,
            "shadow_promotion_count": len(shadow_promotion_tickers),
            "shadow_promotion_tickers": sorted(shadow_promotion_tickers),
        }
        counts = dict(risk_metrics.get("counts", {}))
        counts["buy_order_count"] = len(plan.buy_orders)
        risk_metrics["counts"] = counts
        # Router-level: mark formal execution eligibility as blocked in selection_targets.
        if plan.selection_targets:
            apply_p2_regime_gate_enforcement_to_selection_targets(
                plan.selection_targets,
                gate=gate,
                allowed_tickers=shadow_promotion_tickers,
            )
    else:
        enforcement_payload = {
            "enforced": False,
            "gate": gate,
            "mode": "enforce",
            "buy_orders_cleared": False,
            "buy_orders_cleared_count": 0,
            "shadow_promotion_count": 0,
            "shadow_promotion_tickers": [],
        }

    risk_metrics["btst_regime_gate_enforcement"] = enforcement_payload
    funnel_diagnostics["btst_regime_gate_enforcement"] = enforcement_payload
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    plan.dual_target_summary = summarize_selection_targets(
        selection_targets=dict(plan.selection_targets or {}),
        target_mode=plan.target_mode,
    )
    return plan


def _resolve_btst_prior_quality_p3_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P3_PRIOR_QUALITY_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P3_PRIOR_QUALITY_MODES else "off"


def _extract_frozen_prior_by_ticker(plan: ExecutionPlan) -> dict[str, dict[str, Any]]:
    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    explicit_mapping = dict(risk_metrics.get("historical_prior_by_ticker", {}) or {})
    if explicit_mapping:
        return {str(ticker): dict(payload or {}) for ticker, payload in explicit_mapping.items() if str(ticker or "").strip() and isinstance(payload, dict)}

    recovered: dict[str, dict[str, Any]] = {}
    for ticker, evaluation in dict(getattr(plan, "selection_targets", {}) or {}).items():
        short_trade = getattr(evaluation, "short_trade", None)
        metrics_payload = dict(getattr(short_trade, "metrics_payload", {}) or {}) if short_trade is not None else {}
        historical_prior = dict(metrics_payload.get("historical_prior", {}) or {})
        if historical_prior:
            recovered[str(ticker)] = historical_prior
    return recovered


def _enforce_btst_prior_quality_p3(plan: ExecutionPlan, *, prior_by_ticker: dict[str, dict[str, Any]]) -> ExecutionPlan:
    """P3 prior quality hard gate: annotate and block selection_targets with poor historical priors.

    Only active when BTST_0422_P3_PRIOR_QUALITY_MODE=enforce.
    Preserves backward compatibility — off by default.
    Reuses prior_by_ticker already loaded during post-market watchlist context construction.

    In enforce mode:
      1. Classifies each selection target's historical prior and marks p3_execution_blocked.
      2. Removes buy orders for P3-blocked tickers from plan.buy_orders.
      3. Rebuilds plan.dual_target_summary to reflect post-enforcement P3 counts.
    """
    from src.targets.prior_quality import (
        apply_p3_prior_quality_gate_to_selection_targets,
    )
    from src.targets.router_build_helpers import build_dual_target_summary

    mode = _resolve_btst_prior_quality_p3_mode()
    if mode != "enforce":
        return plan

    plan = plan.model_copy(deep=True)
    selection_targets = plan.selection_targets or {}
    if selection_targets:
        apply_p3_prior_quality_gate_to_selection_targets(
            selection_targets,
            mode=mode,
            prior_by_ticker=prior_by_ticker,
        )

    # Gap 1 fix: filter buy_orders to remove P3-blocked tickers.
    blocked_tickers = {ticker for ticker, ev in selection_targets.items() if ev.p3_execution_blocked}
    if blocked_tickers and plan.buy_orders:
        original_count = len(plan.buy_orders)
        plan.buy_orders = [o for o in plan.buy_orders if o.ticker not in blocked_tickers]
        buy_orders_removed = original_count - len(plan.buy_orders)
    else:
        buy_orders_removed = 0

    p3_blocked_count = len(blocked_tickers)
    enforcement_payload: dict[str, Any] = {
        "mode": "enforce",
        "p3_execution_blocked_count": p3_blocked_count,
        "buy_orders_removed": buy_orders_removed,
    }

    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    risk_metrics["btst_prior_quality_p3_enforcement"] = enforcement_payload
    funnel_diagnostics["btst_prior_quality_p3_enforcement"] = enforcement_payload
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    # Keep buy_order_count in sync with the actual post-enforcement list length.
    if buy_orders_removed:
        counts = dict(risk_metrics.get("counts", {}))
        counts["buy_order_count"] = len(plan.buy_orders)
        risk_metrics["counts"] = counts
    plan.risk_metrics = risk_metrics

    # Gap 2 fix: rebuild dual_target_summary so P3 counts are live (not pre-enforcement stale).
    if selection_targets:
        plan.dual_target_summary = build_dual_target_summary(
            selection_targets=selection_targets,
            target_mode=plan.target_mode,
        )

    return plan


def _resolve_btst_execution_contract_p5_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P5_EXECUTION_CONTRACT_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P5_EXECUTION_CONTRACT_MODES else "off"


def _resolve_btst_win_rate_first_precision_mode() -> bool:
    """Resolve win-rate-first precision mode from environment.

    When enabled, tightens P5 enforcement to downgrade any candidate without
    execution_ready prior quality. This mode requires P5 enforce mode to be active.
    Default: False (off) to preserve baseline behavior.
    """
    raw = str(os.getenv(BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE_ENV, "false") or "false").strip().lower()
    return raw in {"true", "1", "yes", "on"}


def _enforce_btst_execution_contract_p5(plan: ExecutionPlan) -> ExecutionPlan:
    from src.targets.router_build_helpers import build_dual_target_summary
    from src.targets.router_build_helpers import collect_formal_execution_block_flags

    if _resolve_btst_execution_contract_p5_mode() != "enforce":
        return plan

    plan = plan.model_copy(deep=True)
    selection_targets = plan.selection_targets or {}
    if not selection_targets:
        return plan

    gate = _get_or_classify_gate(plan) or ""
    allowed_gate = gate in {"", "normal_trade", "aggressive_trade"}
    win_rate_first_precision_mode = _resolve_btst_win_rate_first_precision_mode()
    downgrade_reason_counts: dict[str, int] = {}
    downgraded_tickers: set[str] = set()

    for ticker, evaluation in selection_targets.items():
        short_trade_result = evaluation.short_trade
        prior_quality_level = str(evaluation.p3_prior_quality_label or evaluation.historical_prior_quality_level or "").strip() or None
        shadow_promotion = resolve_btst_shadow_promotion_payload(
            evaluation=evaluation,
            short_trade_result=short_trade_result,
            gate=gate,
        )
        shadow_promotion_applied = bool(shadow_promotion.get("eligible"))
        if short_trade_result is not None and shadow_promotion.get("promoted_from_near_miss"):
            short_trade_result.decision = "selected"
            positive_tags = [str(tag) for tag in list(short_trade_result.positive_tags or []) if str(tag or "").strip()]
            if "shadow_promotion_lane" not in positive_tags:
                positive_tags.append("shadow_promotion_lane")
            short_trade_result.positive_tags = positive_tags
        downgrade_reasons: list[str] = []

        # Check if this is already formally blocked (P2/P3/P5/P6)
        # If so, we must NOT downgrade it - preserve the raw selected decision for correct blocked-selected provenance
        formal_execution_block_flags = collect_formal_execution_block_flags(evaluation, short_trade_result)
        is_formally_blocked = bool(formal_execution_block_flags)

        if short_trade_result is not None and short_trade_result.decision == "selected":
            # CRITICAL: Do NOT collect downgrade reasons if already formally blocked
            # Formal blocks are upstream hard stops - we don't need to re-reason about them
            if not is_formally_blocked:
                if not (allowed_gate or shadow_promotion_applied):
                    downgrade_reasons.append("btst_regime_gate_not_tradeable")

                if win_rate_first_precision_mode:
                    if prior_quality_level != "execution_ready" and not shadow_promotion_applied:
                        downgrade_reasons.append("win_rate_first_precision_prior_not_execution_ready")
                else:
                    if prior_quality_level not in {None, "", "execution_ready"} and not shadow_promotion_applied:
                        downgrade_reasons.append("historical_prior_not_execution_ready")
                if str(evaluation.candidate_source or "").strip() in {"upgrade_only", "research_only"}:
                    downgrade_reasons.append("research_only_source_not_formal_execution")

            # CRITICAL: Only apply downgrade if NOT already formally blocked
            # Formally-blocked names must preserve their raw "selected" decision for correct reporting
            # (blocked-selected provenance in build_reporting_target_summary)
            # But still mark execution_eligible=False and clear buy orders
            if downgrade_reasons and not is_formally_blocked:
                short_trade_result.decision = "near_miss"
                downgraded_tickers.add(str(ticker))

        # CRITICAL: A name is execution_eligible ONLY if:
        # 1. short_trade decision is "selected" (raw or preserved)
        # 2. AND NOT formally blocked (p2/p3/p5/p6_execution_blocked)
        # 3. AND has no downgrade reasons (gate, prior quality, source)
        execution_eligible = bool(short_trade_result is not None and short_trade_result.decision == "selected" and not is_formally_blocked and not downgrade_reasons)
        evaluation.execution_eligible = execution_eligible
        evaluation.downgrade_reasons = list(downgrade_reasons)
        evaluation.historical_prior_quality_level = prior_quality_level
        evaluation.btst_regime_gate = gate or None

        if short_trade_result is not None:
            short_trade_result.execution_eligible = execution_eligible
            short_trade_result.downgrade_reasons = list(downgrade_reasons)
            short_trade_result.historical_prior_quality_level = prior_quality_level
            short_trade_result.btst_regime_gate = gate or None
            metrics_payload = dict(short_trade_result.metrics_payload or {})
            explainability_payload = dict(short_trade_result.explainability_payload or {})
            metrics_payload.update(
                {
                    "execution_eligible": execution_eligible,
                    "downgrade_reasons": list(downgrade_reasons),
                    "historical_prior_quality_level": prior_quality_level,
                    "btst_regime_gate": gate or None,
                    "shadow_promotion": dict(shadow_promotion),
                }
            )
            explainability_payload.update(
                {
                    "execution_eligible": execution_eligible,
                    "downgrade_reasons": list(downgrade_reasons),
                    "historical_prior_quality_level": prior_quality_level,
                    "btst_regime_gate": gate or None,
                    "shadow_promotion": dict(shadow_promotion),
                }
            )
            short_trade_result.metrics_payload = metrics_payload
            short_trade_result.explainability_payload = explainability_payload

        for reason in downgrade_reasons:
            downgrade_reason_counts[reason] = int(downgrade_reason_counts.get(reason) or 0) + 1

    original_buy_order_count = len(plan.buy_orders)
    eligible_tickers = {ticker for ticker, evaluation in selection_targets.items() if evaluation.execution_eligible}
    plan.buy_orders = [order for order in plan.buy_orders if order.ticker in eligible_tickers]
    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    p2_enforcement = dict(risk_metrics.get("btst_regime_gate_enforcement", {}) or {})
    upstream_cleared_count = int(p2_enforcement.get("buy_orders_cleared_count") or 0)
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    enforcement_payload = {
        "mode": "enforce",
        "gate": gate or None,
        "execution_eligible_count": len(eligible_tickers),
        "downgraded_to_near_miss_count": len(downgraded_tickers),
        "buy_orders_removed": max(0, original_buy_order_count - len(plan.buy_orders)),
        "buy_orders_already_cleared_upstream_count": upstream_cleared_count,
        "downgrade_reason_counts": downgrade_reason_counts,
    }
    risk_metrics["btst_execution_contract_p5_enforcement"] = enforcement_payload
    funnel_diagnostics["btst_execution_contract_p5_enforcement"] = enforcement_payload
    counts = dict(risk_metrics.get("counts", {}) or {})
    counts["buy_order_count"] = len(plan.buy_orders)
    risk_metrics["counts"] = counts
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    plan.dual_target_summary = build_dual_target_summary(selection_targets=selection_targets, target_mode=plan.target_mode)
    return plan


def _resolve_btst_risk_budget_p6_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P6_RISK_BUDGET_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P6_RISK_BUDGET_MODES else "off"


def _attach_btst_risk_budget_p6(plan: ExecutionPlan) -> ExecutionPlan:
    mode = _resolve_btst_risk_budget_p6_mode()
    if mode != "enforce":
        return plan
    plan = plan.model_copy(deep=True)
    selection_targets = dict(getattr(plan, "selection_targets", {}) or {})
    watchlist_by_ticker = {str(item.ticker): item for item in list(getattr(plan, "watchlist", []) or [])}
    buy_order_by_ticker = {str(order.ticker): order for order in list(getattr(plan, "buy_orders", []) or [])}
    nav = float((plan.portfolio_snapshot or {}).get("cash", 0.0) or 0.0)
    nav += sum(float(position.get("long", 0) or 0) * float(position.get("long_cost_basis", 0.0) or 0.0) for position in dict((plan.portfolio_snapshot or {}).get("positions", {}) or {}).values())
    summary = {
        "mode": mode,
        "gate_distribution": {},
        "formal_exposure_distribution": {},
        "suppressed_position_summary": {
            "zero_budget_count": 0,
            "reduced_budget_count": 0,
        },
    }
    for ticker, evaluation in selection_targets.items():
        item = watchlist_by_ticker.get(str(ticker))
        if item is None:
            continue
        budget = _resolve_btst_position_budget(
            item=item,
            selection_target=evaluation,
            candidate=None,
            nav=nav if nav > 0 else 1.0,
        )
        p6_payload = {
            "mode": str(budget.get("risk_budget_mode") or mode),
            "risk_budget_ratio": float(budget.get("formal_risk_budget_ratio", 1.0) or 0.0),
            "formal_exposure_bucket": str(budget.get("formal_exposure_bucket") or ""),
            "execution_contract_bucket": str(budget.get("execution_contract_bucket") or ""),
            "risk_budget_gate": str(budget.get("risk_budget_gate") or ""),
            "prior_quality_label": str(budget.get("prior_quality_label") or ""),
        }
        matching_order = buy_order_by_ticker.get(str(ticker))
        if matching_order is not None:
            p6_payload["planned_amount"] = round(float(getattr(matching_order, "amount", 0.0) or 0.0), 4)
            p6_payload["planned_shares"] = int(getattr(matching_order, "shares", 0) or 0)
            p6_payload["risk_budget_ratio_applied"] = round(float(getattr(matching_order, "risk_budget_ratio", 1.0) or 0.0), 4)
        short_trade_result = getattr(evaluation, "short_trade", None)
        if short_trade_result is not None:
            metrics_payload = dict(short_trade_result.metrics_payload or {})
            explainability_payload = dict(short_trade_result.explainability_payload or {})
            metrics_payload["p6_risk_budget"] = p6_payload
            explainability_payload["p6_risk_budget"] = p6_payload
            short_trade_result.metrics_payload = metrics_payload
            short_trade_result.explainability_payload = explainability_payload
        gate_name = p6_payload["risk_budget_gate"] or "unknown"
        bucket = p6_payload["formal_exposure_bucket"] or "unknown"
        summary["gate_distribution"][gate_name] = int(summary["gate_distribution"].get(gate_name) or 0) + 1
        summary["formal_exposure_distribution"][bucket] = int(summary["formal_exposure_distribution"].get(bucket) or 0) + 1
        if bucket == "zero_budget":
            summary["suppressed_position_summary"]["zero_budget_count"] += 1
        if bucket == "reduced":
            summary["suppressed_position_summary"]["reduced_budget_count"] += 1

    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    risk_metrics["btst_risk_budget_p6_enforcement"] = summary
    funnel_diagnostics["btst_risk_budget_p6_enforcement"] = summary
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    return plan


def _serialize_market_state_for_backfill(market_state: Any | None) -> dict[str, Any]:
    if market_state is None:
        return {}
    if hasattr(market_state, "model_dump"):
        return dict(market_state.model_dump(mode="json") or {})
    if isinstance(market_state, dict):
        return dict(market_state)
    return {}


def _build_btst_post_p5_watchlist_shell(
    *,
    ticker: str,
    selection_target: DualTargetEvaluation | None,
    shell_entry: dict[str, Any] | None,
    market_state: Any | None,
) -> LayerCResult:
    entry = dict(shell_entry or {})
    short_trade_result = getattr(selection_target, "short_trade", None)
    execution_eligible = bool(getattr(selection_target, "execution_eligible", False))
    shell_score_b = float(entry.get("score_b", entry.get("score_final", 0.0)) or 0.0)
    shell_score_final = float(entry.get("score_final", entry.get("score_b", 0.0)) or 0.0)
    shell_quality_score = float(entry.get("quality_score", 0.5) or 0.5)
    target_score = float(getattr(short_trade_result, "score_target", 0.0) or 0.0)
    target_confidence = float(getattr(short_trade_result, "confidence", 0.0) or 0.0)
    resolved_score_final = max(shell_score_final, target_score) if execution_eligible else shell_score_final
    resolved_quality_score = max(shell_quality_score, target_confidence) if execution_eligible else shell_quality_score
    return LayerCResult(
        ticker=str(ticker),
        score_c=float(entry.get("score_c", 0.0) or 0.0),
        score_final=resolved_score_final,
        score_b=max(shell_score_b, target_score) if execution_eligible else shell_score_b,
        quality_score=resolved_quality_score,
        market_state=dict(entry.get("market_state") or _serialize_market_state_for_backfill(market_state)),
        candidate_source=str(entry.get("candidate_source") or getattr(selection_target, "candidate_source", None) or getattr(short_trade_result, "candidate_source", None) or "selection_target_backfill"),
        candidate_reason_codes=[str(code) for code in list(entry.get("candidate_reason_codes", [])) if str(code or "").strip()],
        metrics=dict(entry.get("metrics") or {}),
        decision=str(entry.get("layer_c_decision") or entry.get("decision") or "watch"),
        theme_name=str(entry.get("theme_name") or ""),
        theme_category=str(entry.get("theme_category") or ""),
        is_new_theme=bool(entry.get("is_new_theme")),
        projected_theme_exposure=float(entry.get("projected_theme_exposure", 0.0) or 0.0),
        incremental_theme_exposure=float(entry.get("incremental_theme_exposure", 0.0) or 0.0),
    )


def _backfill_btst_post_p5_buy_orders(
    plan: ExecutionPlan,
    *,
    trade_date: str,
    candidate_by_ticker: dict[str, CandidateStock] | None = None,
    price_map: dict[str, float] | None = None,
    blocked_buy_tickers: dict[str, dict[str, Any]] | None = None,
) -> ExecutionPlan:
    selection_targets = dict(getattr(plan, "selection_targets", {}) or {})
    if not selection_targets:
        return plan

    existing_buy_orders = list(getattr(plan, "buy_orders", []) or [])
    existing_buy_order_tickers = {str(order.ticker) for order in existing_buy_orders}
    execution_eligible_tickers = {str(ticker) for ticker, evaluation in selection_targets.items() if getattr(evaluation, "execution_eligible", False)}
    missing_order_tickers = sorted(execution_eligible_tickers - existing_buy_order_tickers)
    if not missing_order_tickers:
        return plan

    plan = plan.model_copy(deep=True)
    # Re-read selection_targets from the deep copy to ensure isolation
    selection_targets = dict(getattr(plan, "selection_targets", {}) or {})
    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    shell_inputs = dict(risk_metrics.get("selection_target_shell_inputs", {}) or {})
    shell_entries = [
        *list(shell_inputs.get("supplemental_short_trade_entries", []) or []),
        *list(shell_inputs.get("rejected_entries", []) or []),
    ]
    shell_entry_by_ticker = {str(entry.get("ticker") or "").strip(): dict(entry) for entry in shell_entries if str(dict(entry).get("ticker") or "").strip()}
    watchlist = list(getattr(plan, "watchlist", []) or [])
    watchlist_by_ticker = {str(item.ticker): item for item in watchlist}
    for ticker in missing_order_tickers:
        if ticker in watchlist_by_ticker:
            continue
        shell_entry = shell_entry_by_ticker.get(ticker)
        if shell_entry is None:
            continue
        watch_item = _build_btst_post_p5_watchlist_shell(
            ticker=ticker,
            selection_target=selection_targets.get(ticker),
            shell_entry=shell_entry,
            market_state=getattr(plan, "market_state", None),
        )
        watchlist.append(watch_item)
        watchlist_by_ticker[ticker] = watch_item

    rebuild_watchlist = [item for item in watchlist if str(item.ticker) in execution_eligible_tickers]
    if not rebuild_watchlist:
        return plan

    resolved_price_map = {str(ticker): float(value) for ticker, value in dict(price_map or {}).items() if value is not None}
    for ticker in execution_eligible_tickers:
        if ticker in resolved_price_map:
            continue
        shell_entry = shell_entry_by_ticker.get(ticker, {})
        for price_key in ("close", "current_price", "last_price", "price"):
            raw_price = shell_entry.get(price_key)
            try:
                if raw_price is not None and raw_price != "":
                    resolved_price_map[ticker] = float(raw_price)
                    break
            except (TypeError, ValueError):
                continue

    rebuilt_buy_orders, rebuilt_buy_order_diagnostics = build_buy_orders_with_diagnostics(
        rebuild_watchlist,
        dict(getattr(plan, "portfolio_snapshot", {}) or {}),
        trade_date=trade_date,
        candidate_by_ticker=dict(candidate_by_ticker or {}),
        price_map=resolved_price_map,
        blocked_buy_tickers=blocked_buy_tickers,
        selection_targets=selection_targets,
    )
    rebuilt_buy_order_tickers = {str(order.ticker) for order in rebuilt_buy_orders}
    backfilled_tickers = sorted(rebuilt_buy_order_tickers - existing_buy_order_tickers)
    if not backfilled_tickers and len(rebuilt_buy_orders) == len(existing_buy_orders):
        return plan

    counts = dict(risk_metrics.get("counts", {}) or {})
    counts["buy_order_count"] = len(rebuilt_buy_orders)
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    filters = dict(funnel_diagnostics.get("filters", {}) or {})
    filters["buy_orders"] = rebuilt_buy_order_diagnostics
    funnel_diagnostics["filters"] = filters
    backfill_payload = {
        "attempted_tickers": missing_order_tickers,
        "backfilled_tickers": backfilled_tickers,
        "eligible_missing_order_count": len(missing_order_tickers),
        "backfilled_count": len(backfilled_tickers),
    }
    risk_metrics["counts"] = counts
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    risk_metrics["btst_post_p5_buy_order_backfill"] = backfill_payload
    plan.risk_metrics = risk_metrics
    plan.watchlist = watchlist
    plan.buy_orders = rebuilt_buy_orders
    return plan


def _default_exit_checker(portfolio_snapshot: dict, trade_date: str, logic_scores: dict[str, float] | None = None) -> list:
    return _default_exit_checker_impl(
        portfolio_snapshot,
        trade_date,
        logic_scores,
        build_watchlist_price_map=build_watchlist_price_map,
        check_exit_signal=check_exit_signal,
        holding_state_cls=HoldingState,
    )


def _build_filter_summary(entries: list[dict]) -> dict:
    return _build_filter_summary_impl(entries)


def _load_latest_btst_historical_prior_by_ticker() -> dict[str, dict[str, Any]]:
    return _load_latest_historical_prior_by_ticker_impl(
        reports_root=BTST_REPORTS_ROOT,
        loader=load_latest_btst_historical_prior_by_ticker,
    )


def _resolve_historical_prior_for_ticker(
    *,
    ticker: str,
    historical_prior: dict[str, Any] | None,
    prior_by_ticker: dict[str, dict[str, Any]],
    candidate_source: str | None = None,
) -> dict[str, Any]:
    return _resolve_historical_prior_for_ticker_impl(
        ticker=ticker,
        historical_prior=historical_prior,
        prior_by_ticker=prior_by_ticker,
        candidate_source=candidate_source,
    )


def _build_layer_b_filter_diagnostics_wrapper(
    fused: list[Any],
    high_pool: list[Any],
) -> dict[str, Any]:
    return _build_layer_b_filter_diagnostics(fused, high_pool, build_filter_summary_fn=_build_filter_summary)


def _build_watchlist_filter_diagnostics_wrapper(
    layer_c_results: list[LayerCResult],
    watchlist: list[LayerCResult],
    *,
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
) -> dict[str, Any]:
    return _build_watchlist_filter_diagnostics(
        layer_c_results,
        watchlist,
        merge_approved_tickers=merge_approved_tickers,
        threshold_relaxation=threshold_relaxation,
        build_filter_summary_fn=_build_filter_summary,
    )


def _attach_historical_prior_to_entries(entries: list[dict[str, Any]], *, prior_by_ticker: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return _attach_historical_prior_to_entries_impl(
        entries,
        prior_by_ticker=prior_by_ticker,
        resolve_historical_prior_for_ticker_fn=_resolve_historical_prior_for_ticker,
    )


def _build_sell_order_diagnostics(sell_orders: list) -> dict:
    return build_sell_order_diagnostics_impl(
        sell_orders=sell_orders,
        build_filter_summary_fn=_build_filter_summary,
    )


def _normalize_blocked_buy_tickers(blocked_buy_tickers: dict[str, dict] | None) -> dict[str, dict]:
    normalized: dict[str, dict] = {}
    for ticker, payload in (blocked_buy_tickers or {}).items():
        normalized[str(ticker)] = dict(payload or {})
    return normalized


def _merge_recent_formal_buy_cooldowns(trade_date: str, blocked_buy_tickers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    recent_cooldowns = load_recent_btst_buy_order_cooldowns(
        BTST_REPORTS_ROOT,
        trade_date=trade_date,
    )
    if not recent_cooldowns:
        return blocked_buy_tickers
    merged = dict(recent_cooldowns)
    merged.update(blocked_buy_tickers)
    return merged


def _selection_target_has_weak_confirmation_reentry_risk(selection_target: DualTargetEvaluation | None) -> bool:
    short_trade = selection_target.short_trade if selection_target is not None else None
    if short_trade is None:
        return False
    negative_tags = {str(tag) for tag in short_trade.negative_tags}
    if negative_tags & WEAK_CONFIRMATION_REENTRY_NEGATIVE_TAGS:
        return True
    metrics_payload = dict(short_trade.metrics_payload or {})
    for metric_key in WEAK_CONFIRMATION_REENTRY_GUARD_KEYS:
        metric_value = metrics_payload.get(metric_key)
        if isinstance(metric_value, dict) and bool(metric_value.get("applied")):
            return True
    return False


def _resolve_reentry_required_score(cooldown_payload: dict, selection_target: DualTargetEvaluation | None) -> tuple[float, bool]:
    required_score = float(cooldown_payload.get("reentry_min_score", EXIT_REENTRY_CONFIRM_SCORE_MIN))
    weak_confirmation_reentry_guard = _selection_target_has_weak_confirmation_reentry_risk(selection_target)
    if weak_confirmation_reentry_guard:
        required_score = max(required_score, EXIT_REENTRY_WEAK_CONFIRMATION_SCORE_MIN)
    return required_score, weak_confirmation_reentry_guard


def _build_reentry_filter_payload(
    ticker: str,
    score_final: float,
    cooldown_payload: dict,
    trade_date: str,
    selection_target: DualTargetEvaluation | None = None,
) -> dict | None:
    return build_reentry_filter_payload(
        ticker=ticker,
        score_final=score_final,
        cooldown_payload=cooldown_payload,
        trade_date=trade_date,
        selection_target=selection_target,
        resolve_reentry_required_score_fn=_resolve_reentry_required_score,
    )


def _build_reentry_filter_entry(
    item: LayerCResult,
    cooldown_payload: dict,
    trade_date: str,
    selection_target: DualTargetEvaluation | None = None,
) -> dict | None:
    return _build_reentry_filter_payload(item.ticker, item.score_final, cooldown_payload, trade_date, selection_target=selection_target)


def _to_ts_code_for_price_lookup(ticker: str) -> str:
    return to_tushare_code(ticker)


def build_watchlist_price_map(trade_date: str, tickers: list[str]) -> dict[str, float]:
    return build_watchlist_price_map_impl(
        trade_date=trade_date,
        tickers=tickers,
        get_daily_basic_batch_fn=get_daily_basic_batch,
        to_ts_code_for_price_lookup_fn=_to_ts_code_for_price_lookup,
    )


def _serialize_short_trade_target_profile(profile) -> dict[str, object]:
    return {
        "select_threshold": float(profile.select_threshold),
        "near_miss_threshold": float(profile.near_miss_threshold),
        "stale_penalty_block_threshold": float(profile.stale_penalty_block_threshold),
        "overhead_penalty_block_threshold": float(profile.overhead_penalty_block_threshold),
        "extension_penalty_block_threshold": float(profile.extension_penalty_block_threshold),
        "layer_c_avoid_penalty": float(profile.layer_c_avoid_penalty),
        "profitability_relief_enabled": bool(profile.profitability_relief_enabled),
        "profitability_relief_breakout_freshness_min": float(profile.profitability_relief_breakout_freshness_min),
        "profitability_relief_catalyst_freshness_min": float(profile.profitability_relief_catalyst_freshness_min),
        "profitability_relief_sector_resonance_min": float(profile.profitability_relief_sector_resonance_min),
        "profitability_relief_avoid_penalty": float(profile.profitability_relief_avoid_penalty),
        "stale_score_penalty_weight": float(profile.stale_score_penalty_weight),
        "overhead_score_penalty_weight": float(profile.overhead_score_penalty_weight),
        "extension_score_penalty_weight": float(profile.extension_score_penalty_weight),
        "momentum_strength_weight": float(getattr(profile, "momentum_strength_weight", 0.0)),
        "short_term_reversal_weight": float(getattr(profile, "short_term_reversal_weight", 0.0)),
        "intraday_strength_weight": float(getattr(profile, "intraday_strength_weight", 0.0)),
        "reversal_2d_weight": float(getattr(profile, "reversal_2d_weight", 0.0)),
        "strong_bearish_conflicts": sorted(str(item) for item in profile.strong_bearish_conflicts),
        "hard_block_bearish_conflicts": sorted(str(item) for item in profile.hard_block_bearish_conflicts),
        "overhead_conflict_penalty_conflicts": sorted(str(item) for item in profile.overhead_conflict_penalty_conflicts),
    }


def _attach_short_trade_target_profile(
    plan: ExecutionPlan,
    *,
    profile_name: str,
    profile_overrides: dict[str, object] | None,
) -> ExecutionPlan:
    profile = build_short_trade_target_profile(profile_name, profile_overrides)
    plan.short_trade_target_profile_name = profile.name
    plan.short_trade_target_profile_config = _serialize_short_trade_target_profile(profile)
    return plan


def _resolve_effective_short_trade_target_profile_name(
    *,
    requested_profile_name: str,
    requested_profile_overrides: dict[str, object] | None,
    market_state: Any,
) -> str:
    normalized_profile_name = str(requested_profile_name or "default").strip() or "default"
    if normalized_profile_name != "default" or requested_profile_overrides:
        return normalized_profile_name
    if market_state is None:
        return normalized_profile_name

    from src.targets.short_trade_target_profile_routing import (
        resolve_short_trade_target_profile_name_from_market_state,
    )

    return resolve_short_trade_target_profile_name_from_market_state(
        market_state,
        fallback=normalized_profile_name,
    )


def _has_rebuildable_target_shell_inputs(plan: ExecutionPlan, *, target_mode: TargetMode) -> bool:
    if list(getattr(plan, "watchlist", []) or []):
        return True

    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    frozen_selection_target_replay_input = dict(risk_metrics.get("frozen_selection_target_replay_input", {}) or {})
    if list(frozen_selection_target_replay_input.get("watchlist", []) or []):
        return True
    if list(frozen_selection_target_replay_input.get("rejected_entries", []) or []):
        return True
    if list(frozen_selection_target_replay_input.get("supplemental_short_trade_entries", []) or []):
        return True
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    funnel_filters = dict(funnel_diagnostics.get("filters", {}) or {})
    watchlist_filter_diagnostics = dict(funnel_filters.get("watchlist", {}) or {})
    short_trade_candidate_diagnostics = dict(funnel_filters.get("short_trade_candidates", {}) or {})
    catalyst_theme_candidates = dict(funnel_filters.get("catalyst_theme_candidates", {}) or {})

    if list(watchlist_filter_diagnostics.get("tickers", []) or []):
        return True
    if list(watchlist_filter_diagnostics.get("released_shadow_entries", []) or []):
        return True
    if list(short_trade_candidate_diagnostics.get("tickers", []) or []):
        return True
    if list(short_trade_candidate_diagnostics.get("released_shadow_entries", []) or []):
        return True
    if str(target_mode or "") == "short_trade_only" and list(catalyst_theme_candidates.get("tickers", []) or []):
        return True
    return False


def _ensure_plan_target_shells(
    plan: ExecutionPlan,
    target_mode: TargetMode,
    *,
    short_trade_target_profile_name: str = "default",
    short_trade_target_profile_overrides: dict[str, object] | None = None,
) -> ExecutionPlan:
    plan = plan.model_copy(deep=True)
    requested_profile = build_short_trade_target_profile(
        short_trade_target_profile_name,
        short_trade_target_profile_overrides,
    )
    requested_profile_config = _serialize_short_trade_target_profile(requested_profile)
    plan.watchlist = _attach_downstream_target_market_state_payload(
        list(getattr(plan, "watchlist", []) or []),
        market_state=getattr(plan, "market_state", None),
    )
    existing_profile_name = str(getattr(plan, "short_trade_target_profile_name", "") or "")
    existing_profile_config = dict(getattr(plan, "short_trade_target_profile_config", {}) or {})
    profile_mismatch = existing_profile_name != requested_profile.name or existing_profile_config != requested_profile_config
    frozen_replay_has_sidecar = bool(dict(dict(getattr(plan, "risk_metrics", {}) or {}).get("frozen_selection_target_replay_input", {}) or {}))
    replay_sidecar_can_rebuild = frozen_replay_has_sidecar and _has_rebuildable_target_shell_inputs(
        plan,
        target_mode=target_mode,
    )
    if profile_mismatch or replay_sidecar_can_rebuild:
        # Frozen replay plans may carry stale selection_targets even when the requested profile matches.
        # Only clear sidecar-backed selection_targets when shell inputs exist and recomputation is possible.
        plan.selection_targets = {}

    return ensure_plan_target_shells_impl(
        plan=plan,
        target_mode=target_mode,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        dual_target_summary_cls=DualTargetSummary,
        load_latest_historical_prior_by_ticker_fn=_load_latest_btst_historical_prior_by_ticker,
        attach_historical_prior_to_entries_fn=_attach_historical_prior_to_entries,
        attach_historical_prior_to_watchlist_fn=_attach_historical_prior_to_watchlist,
        use_short_trade_target_profile_fn=use_short_trade_target_profile,
        build_selection_targets_fn=build_selection_targets,
        summarize_selection_targets_fn=summarize_selection_targets,
        attach_short_trade_target_profile_fn=_attach_short_trade_target_profile,
    )


def build_buy_orders_with_diagnostics(
    watchlist: list[LayerCResult],
    portfolio_snapshot: dict,
    trade_date: str = "",
    candidate_by_ticker: dict[str, CandidateStock] | None = None,
    price_map: dict[str, float] | None = None,
    blocked_buy_tickers: dict[str, dict] | None = None,
    selection_targets: dict[str, DualTargetEvaluation] | None = None,
) -> tuple[list, dict]:
    return build_buy_orders_with_diagnostics_impl(
        watchlist=watchlist,
        portfolio_snapshot=portfolio_snapshot,
        trade_date=trade_date,
        candidate_by_ticker=candidate_by_ticker,
        price_map=price_map,
        blocked_buy_tickers=blocked_buy_tickers,
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=_normalize_blocked_buy_tickers,
        build_filter_summary_fn=_build_filter_summary,
        build_reentry_filter_entry_fn=_build_reentry_filter_entry,
        resolve_continuation_execution_overrides_fn=_resolve_continuation_execution_overrides,
        calculate_position_fn=calculate_position,
        enforce_daily_trade_limit_fn=_enforce_btst_daily_trade_limit,
    )


def _resolve_continuation_execution_overrides(*, item: LayerCResult, selection_target: DualTargetEvaluation | None) -> dict[str, Any]:
    if not CONTINUATION_EXECUTION_ENABLED or selection_target is None or selection_target.short_trade is None:
        return {}

    short_trade = selection_target.short_trade
    positive_tags = {str(tag).strip() for tag in list(short_trade.positive_tags or []) if str(tag or "").strip()}
    continuation_payload = dict((short_trade.metrics_payload or {}).get("t_plus_2_continuation_candidate") or {})
    if "t_plus_2_continuation_candidate" not in positive_tags or not bool(continuation_payload.get("applied")):
        return {}

    return {
        "applied": True,
        "watchlist_min_score_override": CONTINUATION_WATCHLIST_MIN_SCORE,
        "watchlist_edge_execution_ratio_override": CONTINUATION_WATCHLIST_EDGE_EXECUTION_RATIO,
        "candidate_source": str(continuation_payload.get("candidate_source") or ""),
        "ticker": item.ticker,
    }


@dataclass
class DailyPipeline:
    agent_runner: AgentRunner | None = None
    exit_checker: ExitChecker = _default_exit_checker
    base_model_name: str = ""
    base_model_provider: str = ""
    selected_analysts: list[str] | None = None
    fast_selected_analysts: list[str] | None = None
    frozen_post_market_plans: dict[str, ExecutionPlan] | None = None
    frozen_plan_source: str | None = None
    target_mode: TargetMode = "research_only"
    short_trade_target_profile_name: str = "default"
    short_trade_target_profile_overrides: dict[str, object] = field(default_factory=dict)
    merge_approved_tickers: set[str] = field(default_factory=set)
    execution_plan_provenance_log: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        uses_default_agent_runner = self.agent_runner is None
        if uses_default_agent_runner:
            if not self.base_model_name or not self.base_model_provider:
                default_model_name, default_model_provider = get_default_model_config()
                self.base_model_name = str(self.base_model_name or default_model_name)
                self.base_model_provider = str(self.base_model_provider or default_model_provider)
            self.agent_runner = self._run_agents_with_base_model
        if self.base_model_name and self.base_model_provider:
            self._skip_precise_stage = _should_skip_precise_stage(self.base_model_name, self.base_model_provider)
        else:
            self._skip_precise_stage = not uses_default_agent_runner
        self._exit_checker_accepts_logic_scores = len(signature(self.exit_checker).parameters) >= 3
        self.short_trade_target_profile_name = str(self.short_trade_target_profile_name or "default")
        self.short_trade_target_profile_overrides = dict(self.short_trade_target_profile_overrides or {})
        self.merge_approved_tickers = load_merge_approved_tickers(
            explicit_tickers=set(self.merge_approved_tickers or set()).union(MERGE_APPROVED_TICKERS),
            merge_review_path=MERGE_APPROVED_MERGE_REVIEW_PATH or None,
            merge_ranking_path=MERGE_APPROVED_RANKING_PATH or None,
        )
        self._short_trade_target_profile = build_short_trade_target_profile(
            self.short_trade_target_profile_name,
            self.short_trade_target_profile_overrides,
        )
        if self.frozen_post_market_plans is not None:
            self.frozen_post_market_plans = {
                str(trade_date): _ensure_plan_target_shells(
                    ExecutionPlan.model_validate(plan),
                    self.target_mode,
                    short_trade_target_profile_name=self.short_trade_target_profile_name,
                    short_trade_target_profile_overrides=self.short_trade_target_profile_overrides,
                )
                for trade_date, plan in self.frozen_post_market_plans.items()
            }

    def _run_exit_checker(self, portfolio_snapshot: dict, trade_date: str, logic_scores: dict[str, float] | None = None) -> list:
        if self._exit_checker_accepts_logic_scores:
            return self.exit_checker(portfolio_snapshot, trade_date, logic_scores or {})
        return self.exit_checker(portfolio_snapshot, trade_date)

    def _resolve_selected_analysts_for_tier(self, model_tier: str) -> list[str] | None:
        if model_tier == "fast":
            default_fast_selected_analysts = resolve_default_fast_selected_analysts(
                selection_target=self.target_mode,
                selected_analysts=self.selected_analysts,
                fast_selected_analysts=self.fast_selected_analysts,
            )
            if default_fast_selected_analysts is not None:
                return default_fast_selected_analysts
        if self.selected_analysts is not None:
            return list(self.selected_analysts)
        return None

    def _run_agents_with_base_model(self, tickers: list[str], trade_date: str, model_tier: str) -> dict[str, dict[str, dict]]:
        from src.main import run_hedge_fund

        start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=365)).strftime("%Y-%m-%d")
        end_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
        model_name, model_provider = _resolve_pipeline_model_config(model_tier, self.base_model_name, self.base_model_provider)
        selected_analysts = self._resolve_selected_analysts_for_tier(model_tier)
        llm_observability = {
            "trade_date": trade_date,
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": model_tier,
        }
        if selected_analysts is not None:
            llm_observability["selected_analysts"] = list(selected_analysts)
        result = run_hedge_fund(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            portfolio={"cash": 1_000_000, "positions": {}, "margin_requirement": 0.0, "margin_used": 0.0, "realized_gains": {}},
            show_reasoning=False,
            selected_analysts=selected_analysts or [],
            model_name=model_name,
            model_provider=model_provider,
            llm_observability=llm_observability,
        )
        execution_plan_provenance = result.get("execution_plan_provenance")
        if isinstance(execution_plan_provenance, dict):
            execution_observation = {
                "trade_date": trade_date,
                "model_tier": model_tier,
                "tickers": list(tickers),
                "execution_plan_provenance": execution_plan_provenance,
            }
            if selected_analysts is not None:
                execution_observation["selected_analysts"] = list(selected_analysts)
            self.execution_plan_provenance_log.append(execution_observation)
        return result.get("analyst_signals", {})

    def _apply_frozen_buy_order_filters(self, frozen_plan: ExecutionPlan, trade_date: str, blocked_buy_tickers: dict[str, dict]) -> ExecutionPlan:
        plan = frozen_plan.model_copy(deep=True)
        plan = _ensure_plan_target_shells(
            plan,
            self.target_mode,
            short_trade_target_profile_name=self.short_trade_target_profile_name,
            short_trade_target_profile_overrides=self.short_trade_target_profile_overrides,
        )
        if not blocked_buy_tickers or not plan.buy_orders:
            return plan

        watchlist_by_ticker = {item.ticker: item for item in plan.watchlist}
        selection_targets = dict(plan.selection_targets or {})
        retained_orders = []
        filtered_entries: list[dict] = []
        for order in plan.buy_orders:
            cooldown_payload = blocked_buy_tickers.get(order.ticker)
            if cooldown_payload is None:
                retained_orders.append(order)
                continue

            watch_item = watchlist_by_ticker.get(order.ticker)
            score_final = float(watch_item.score_final if watch_item is not None else order.score_final)
            filter_entry = _build_reentry_filter_payload(
                order.ticker,
                score_final,
                cooldown_payload,
                trade_date,
                selection_target=selection_targets.get(order.ticker),
            )
            if filter_entry is None:
                retained_orders.append(order)
                continue
            filtered_entries.append(filter_entry)

        if not filtered_entries:
            return plan

        plan.buy_orders = retained_orders
        risk_metrics = dict(plan.risk_metrics or {})
        counts = dict(risk_metrics.get("counts", {}))
        funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}))
        filters = dict(funnel_diagnostics.get("filters", {}))
        existing_buy_order_summary = dict(filters.get("buy_orders", {}))
        existing_entries = list(existing_buy_order_summary.get("tickers", []))
        existing_entries.extend(filtered_entries)
        buy_order_summary = _build_filter_summary(existing_entries)
        buy_order_summary["selected_tickers"] = [order.ticker for order in retained_orders]
        filters["buy_orders"] = buy_order_summary
        funnel_diagnostics["filters"] = filters
        funnel_diagnostics["blocked_buy_tickers"] = blocked_buy_tickers
        counts["buy_order_count"] = len(retained_orders)
        risk_metrics["counts"] = counts
        risk_metrics["funnel_diagnostics"] = funnel_diagnostics
        plan.risk_metrics = risk_metrics
        return plan

    def _apply_frozen_p6_risk_budget_overlay(self, plan: ExecutionPlan) -> ExecutionPlan:
        if _resolve_btst_risk_budget_p6_mode() != "enforce":
            return plan

        plan = plan.model_copy(deep=True)
        selection_targets = dict(plan.selection_targets or {})
        watchlist_by_ticker = {item.ticker: item for item in plan.watchlist}
        nav = float((plan.portfolio_snapshot or {}).get("cash", 0.0) or 0.0)
        nav += sum(float(position.get("long", 0) or 0) * float(position.get("long_cost_basis", 0.0) or 0.0) for position in dict((plan.portfolio_snapshot or {}).get("positions", {}) or {}).values())
        nav = nav if nav > 0 else 1.0

        filtered_entries: list[dict[str, Any]] = []
        updated_orders = []
        any_overlay_change = False
        for order in list(plan.buy_orders or []):
            item = watchlist_by_ticker.get(order.ticker)
            selection_target = selection_targets.get(order.ticker)
            if item is None or selection_target is None:
                updated_orders.append(order)
                continue

            shares = int(getattr(order, "shares", 0) or 0)
            amount = float(getattr(order, "amount", 0.0) or 0.0)
            current_price = (amount / shares) if shares > 0 and amount > 0 else 0.0
            if current_price <= 0:
                updated_orders.append(order)
                continue

            budget = _resolve_btst_position_budget(
                item=item,
                selection_target=selection_target,
                candidate=None,
                nav=nav,
            )
            updated_order = _apply_btst_risk_budget_overlay_to_plan(
                plan=order,
                budget=budget,
                current_price=current_price,
            )
            any_overlay_change = any_overlay_change or updated_order != order
            if int(getattr(updated_order, "shares", 0) or 0) > 0:
                updated_orders.append(updated_order)
                continue

            filtered_entries.append(
                {
                    "ticker": order.ticker,
                    "reason": "position_blocked_risk_budget_overlay",
                    "score_final": round(float(getattr(item, "score_final", getattr(order, "score_final", 0.0)) or 0.0), 4),
                    "constraint_binding": getattr(updated_order, "constraint_binding", ""),
                    "amount": round(float(getattr(updated_order, "amount", 0.0) or 0.0), 4),
                    "execution_ratio": float(getattr(updated_order, "execution_ratio", 0.0) or 0.0),
                    "quality_score": round(float(getattr(item, "quality_score", getattr(order, "quality_score", 0.0)) or 0.0), 4),
                    "risk_budget_gate": str(budget.get("risk_budget_gate") or ""),
                    "risk_budget_ratio": round(float(budget.get("formal_risk_budget_ratio", 1.0) or 0.0), 4),
                    "formal_exposure_bucket": str(budget.get("formal_exposure_bucket") or ""),
                    "execution_contract_bucket": str(budget.get("execution_contract_bucket") or ""),
                }
            )

        if filtered_entries or any_overlay_change:
            plan.buy_orders = updated_orders
            risk_metrics = dict(plan.risk_metrics or {})
            counts = dict(risk_metrics.get("counts", {}))
            funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
            filters = dict(funnel_diagnostics.get("filters", {}) or {})
            existing_buy_order_summary = dict(filters.get("buy_orders", {}) or {})
            existing_entries = list(existing_buy_order_summary.get("tickers", []))
            existing_entries.extend(filtered_entries)
            buy_order_summary = _build_filter_summary(existing_entries)
            buy_order_summary["selected_tickers"] = [order.ticker for order in updated_orders]
            filters["buy_orders"] = buy_order_summary
            funnel_diagnostics["filters"] = filters
            counts["buy_order_count"] = len(updated_orders)
            risk_metrics["counts"] = counts
            risk_metrics["funnel_diagnostics"] = funnel_diagnostics
            plan.risk_metrics = risk_metrics

        return _attach_btst_risk_budget_p6(plan)

    def run_post_market(self, trade_date: str, portfolio_snapshot: dict | None = None, blocked_buy_tickers: dict[str, dict] | None = None) -> ExecutionPlan:
        sync_phase4_test_overrides(globals())
        blocked_buy_tickers = _normalize_blocked_buy_tickers(blocked_buy_tickers)
        blocked_buy_tickers = _merge_recent_formal_buy_cooldowns(trade_date, blocked_buy_tickers)
        if self.frozen_post_market_plans is not None:
            frozen_plan = self.frozen_post_market_plans.get(trade_date)
            if frozen_plan is None:
                raise ValueError(f"Missing frozen current_plan for trade_date={trade_date}")
            plan = self._apply_frozen_buy_order_filters(frozen_plan, trade_date, blocked_buy_tickers)
            plan = _enforce_btst_regime_gate_p2(_attach_btst_regime_gate_shadow(plan))
            plan = _enforce_btst_prior_quality_p3(
                plan,
                prior_by_ticker=_extract_frozen_prior_by_ticker(plan),
            )
            plan = _backfill_btst_post_p5_buy_orders(
                _enforce_btst_execution_contract_p5(plan),
                trade_date=trade_date,
                blocked_buy_tickers=blocked_buy_tickers,
            )
            return self._apply_frozen_p6_risk_budget_overlay(plan)

        total_started_at = perf_counter()
        portfolio_snapshot = portfolio_snapshot or {"cash": 1_000_000, "positions": {}}
        candidate_context, candidate_timing = self._collect_post_market_candidate_context(trade_date)
        watchlist_context = self._build_post_market_watchlist_context(candidate_context, trade_date)
        order_context, order_timing = self._build_post_market_order_context(
            trade_date=trade_date,
            portfolio_snapshot=portfolio_snapshot,
            blocked_buy_tickers=blocked_buy_tickers,
            watchlist_context=watchlist_context,
            layer_c_results=candidate_context.layer_c_results,
            logic_scores=candidate_context.logic_scores,
        )

        diagnostics_aggregation: PostMarketDiagnosticsAggregation = aggregate_post_market_diagnostics(
            candidate_context=candidate_context,
            watchlist_context=watchlist_context,
            order_context=order_context,
            blocked_buy_tickers=blocked_buy_tickers,
            precise_stage_skipped=self._skip_precise_stage,
            fast_agent_score_threshold=FAST_AGENT_SCORE_THRESHOLD,
            fast_agent_max_tickers=FAST_AGENT_MAX_TICKERS,
            precise_agent_max_tickers=PRECISE_AGENT_MAX_TICKERS,
            watchlist_score_threshold=WATCHLIST_SCORE_THRESHOLD,
            candidate_timing=candidate_timing,
            order_timing=order_timing,
            total_post_market_seconds=perf_counter() - total_started_at,
        )
        counts = diagnostics_aggregation.counts
        funnel_diagnostics = diagnostics_aggregation.funnel_diagnostics
        timing_seconds = diagnostics_aggregation.timing_seconds
        effective_profile_name = _resolve_effective_short_trade_target_profile_name(
            requested_profile_name=self.short_trade_target_profile_name,
            requested_profile_overrides=self.short_trade_target_profile_overrides,
            market_state=candidate_context.market_state,
        )
        effective_profile_overrides = self.short_trade_target_profile_overrides
        effective_profile = build_short_trade_target_profile(
            effective_profile_name,
            effective_profile_overrides,
        )

        selection_resolution: PostMarketSelectionResolution = resolve_post_market_selection_targets(
            trade_date=trade_date,
            watchlist_context=watchlist_context,
            portfolio_snapshot=portfolio_snapshot,
            market_state=_build_downstream_target_market_state_payload(candidate_context.market_state),
            buy_orders=order_context.buy_orders,
            counts=counts,
            funnel_diagnostics=funnel_diagnostics,
            target_mode=self.target_mode,
            short_trade_target_profile_name=effective_profile_name,
            short_trade_target_profile_overrides=effective_profile_overrides,
            use_short_trade_target_profile_fn=use_short_trade_target_profile,
            build_selection_target_inputs_fn=build_selection_target_inputs,
            attach_historical_prior_to_entries_fn=_attach_historical_prior_to_entries,
            build_selection_targets_fn=build_selection_targets,
            build_intraday_short_trade_metrics_fn=_build_intraday_short_trade_metrics,
        )
        counts = selection_resolution.counts
        funnel_diagnostics = selection_resolution.funnel_diagnostics
        selection_targets = selection_resolution.selection_targets
        dual_target_summary = selection_resolution.dual_target_summary
        plan = build_post_market_execution_plan(
            trade_date=trade_date,
            candidate_context=candidate_context,
            watchlist_context=watchlist_context,
            resolved_watchlist=selection_resolution.resolved_watchlist,
            resolved_rejected_entries=selection_resolution.resolved_rejected_entries,
            resolved_supplemental_short_trade_entries=selection_resolution.resolved_supplemental_short_trade_entries,
            order_context=order_context,
            portfolio_snapshot=portfolio_snapshot,
            timing_seconds=timing_seconds,
            counts=counts,
            funnel_diagnostics=funnel_diagnostics,
            merge_approved_tickers=self.merge_approved_tickers,
            merge_approved_score_boost=MERGE_APPROVED_SCORE_BOOST,
            merge_approved_watchlist_threshold_relaxation=MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION,
            selection_targets=selection_targets,
            target_mode=self.target_mode,
            dual_target_summary=dual_target_summary,
            short_trade_target_profile=effective_profile,
            serialize_short_trade_target_profile_fn=_serialize_short_trade_target_profile,
            generate_execution_plan_fn=generate_execution_plan,
        )
        plan = _attach_btst_risk_budget_p6(
            _backfill_btst_post_p5_buy_orders(
                _enforce_btst_execution_contract_p5(
                    _enforce_btst_prior_quality_p3(
                        _enforce_btst_regime_gate_p2(_attach_btst_regime_gate_shadow(plan)),
                        prior_by_ticker=watchlist_context.historical_prior_by_ticker,
                    )
                ),
                trade_date=trade_date,
                candidate_by_ticker=watchlist_context.candidate_by_ticker,
                price_map=watchlist_context.price_map,
                blocked_buy_tickers=blocked_buy_tickers,
            )
        )
        if watchlist_context.historical_prior_by_ticker:
            risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
            risk_metrics["historical_prior_by_ticker"] = {str(ticker): dict(payload or {}) for ticker, payload in watchlist_context.historical_prior_by_ticker.items() if str(ticker or "").strip() and isinstance(payload, dict)}
            plan.risk_metrics = risk_metrics
        return plan

    def _collect_post_market_candidate_context(self, trade_date: str) -> tuple[PostMarketCandidateContext, dict[str, float]]:
        stage_started_at = perf_counter()
        candidates, shadow_candidates, candidate_pool_shadow_summary = _load_candidate_pool_bundle(trade_date)
        candidate_pool_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        market_state = detect_market_state(trade_date)
        market_state_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        scored = score_batch(candidates, trade_date)
        score_batch_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        shadow_scored = score_batch(shadow_candidates, trade_date) if shadow_candidates else {}
        shadow_score_batch_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        fused = fuse_batch(scored, market_state, trade_date)
        fused = _apply_merge_approved_fused_boost(fused, self.merge_approved_tickers, MERGE_APPROVED_SCORE_BOOST)
        fused, merge_approved_breakout_signal_uplift = _apply_merge_approved_breakout_signal_uplift(fused, self.merge_approved_tickers)
        fuse_batch_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        shadow_fused = fuse_batch(shadow_scored, market_state, trade_date) if shadow_scored else []
        shadow_fuse_batch_seconds = perf_counter() - stage_started_at

        high_pool = build_high_pool(
            fused,
            score_threshold=FAST_AGENT_SCORE_THRESHOLD,
            max_tickers=FAST_AGENT_MAX_TICKERS,
        )
        top_precise_pool = high_pool[:PRECISE_AGENT_MAX_TICKERS]

        stage_started_at = perf_counter()
        agent_results = self.agent_runner([item.ticker for item in high_pool], trade_date, "fast") if high_pool else {}
        fast_agent_seconds = perf_counter() - stage_started_at

        skipped_precise_ticker_count = len(top_precise_pool) if self._skip_precise_stage else 0
        estimated_skipped_precise_seconds = _estimate_skipped_precise_seconds(fast_agent_seconds, len(high_pool), skipped_precise_ticker_count)
        stage_started_at = perf_counter()
        precise_results = self.agent_runner([item.ticker for item in top_precise_pool], trade_date, "precise") if top_precise_pool and not self._skip_precise_stage else {}
        precise_agent_seconds = perf_counter() - stage_started_at
        merged_agent_results = merge_agent_results(agent_results, precise_results)

        stage_started_at = perf_counter()
        layer_c_results = aggregate_layer_c_results(high_pool, merged_agent_results)
        layer_c_results = _attach_downstream_target_market_state_payload(
            layer_c_results,
            market_state=market_state,
        )
        layer_c_results, merge_approved_layer_c_alignment_uplift = _apply_merge_approved_layer_c_alignment_uplift(
            layer_c_results,
            self.merge_approved_tickers,
            merge_approved_breakout_signal_uplift,
        )
        layer_c_results, merge_approved_sector_resonance_uplift = _apply_merge_approved_sector_resonance_uplift(
            layer_c_results,
            self.merge_approved_tickers,
            merge_approved_layer_c_alignment_uplift,
        )
        layer_c_results = _tag_merge_approved_layer_c_results(layer_c_results, self.merge_approved_tickers)
        aggregate_layer_c_seconds = perf_counter() - stage_started_at

        return (
            PostMarketCandidateContext(
                candidates=candidates,
                shadow_candidates=shadow_candidates,
                candidate_pool_shadow_summary=candidate_pool_shadow_summary,
                market_state=market_state,
                fused=fused,
                shadow_fused=shadow_fused,
                high_pool=high_pool,
                top_precise_pool=top_precise_pool,
                layer_c_results=layer_c_results,
                logic_scores=_build_logic_score_map(layer_c_results),
                merge_approved_breakout_signal_uplift=merge_approved_breakout_signal_uplift,
                merge_approved_layer_c_alignment_uplift=merge_approved_layer_c_alignment_uplift,
                merge_approved_sector_resonance_uplift=merge_approved_sector_resonance_uplift,
            ),
            {
                "candidate_pool_seconds": candidate_pool_seconds,
                "market_state_seconds": market_state_seconds,
                "score_batch_seconds": score_batch_seconds,
                "shadow_score_batch_seconds": shadow_score_batch_seconds,
                "fuse_batch_seconds": fuse_batch_seconds,
                "shadow_fuse_batch_seconds": shadow_fuse_batch_seconds,
                "fast_agent_seconds": fast_agent_seconds,
                "precise_agent_seconds": precise_agent_seconds,
                "estimated_skipped_precise_seconds": estimated_skipped_precise_seconds,
                "aggregate_layer_c_seconds": aggregate_layer_c_seconds,
            },
        )

    def _build_post_market_watchlist_context(
        self,
        candidate_context: PostMarketCandidateContext,
        trade_date: str,
    ) -> PostMarketWatchlistContext:
        watchlist = _build_merge_approved_watchlist(
            candidate_context.layer_c_results,
            self.merge_approved_tickers,
            MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION,
        )
        layer_b_filter_diagnostics = _build_layer_b_filter_diagnostics_wrapper(candidate_context.fused, candidate_context.high_pool)
        watchlist_filter_diagnostics = _build_watchlist_filter_diagnostics_wrapper(
            candidate_context.layer_c_results,
            watchlist,
            merge_approved_tickers=self.merge_approved_tickers,
            threshold_relaxation=MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION,
        )
        historical_prior_by_ticker = _load_latest_btst_historical_prior_by_ticker()
        short_trade_candidate_diagnostics = _build_short_trade_candidate_diagnostics(
            candidate_context.fused,
            candidate_context.high_pool,
            trade_date,
            shadow_fused=candidate_context.shadow_fused,
            shadow_candidate_by_ticker={candidate.ticker: candidate for candidate in candidate_context.shadow_candidates},
            historical_prior_by_ticker=historical_prior_by_ticker,
        )
        promoted_shadow_watchlist_entries = _select_upstream_shadow_watchlist_entries(
            list((short_trade_candidate_diagnostics or {}).get("released_shadow_entries", []) or []),
            existing_tickers={item.ticker for item in watchlist},
        )
        if promoted_shadow_watchlist_entries:
            promoted_tickers = {item.ticker for item in promoted_shadow_watchlist_entries}
            short_trade_candidate_diagnostics = _mark_upstream_shadow_watchlist_promotions(
                short_trade_candidate_diagnostics,
                promoted_tickers=promoted_tickers,
            )
            watchlist = _merge_watchlist_with_upstream_shadow_promotions(
                watchlist,
                promoted_shadow_watchlist_entries,
            )
        watchlist = _attach_historical_prior_to_watchlist(
            watchlist,
            prior_by_ticker=historical_prior_by_ticker,
        )
        catalyst_theme_candidate_diagnostics = _build_catalyst_theme_candidate_diagnostics(
            candidate_context.fused,
            watchlist,
            short_trade_candidate_diagnostics,
            trade_date,
        )
        early_runner_runtime_entries = _load_early_runner_runtime_entries(trade_date)
        if early_runner_runtime_entries:
            existing_short_trade_tickers = {
                str(dict(entry).get("ticker") or "").strip()
                for entry in list((short_trade_candidate_diagnostics or {}).get("tickers", []) or [])
            }
            short_trade_candidate_diagnostics = {
                **dict(short_trade_candidate_diagnostics or {}),
                "tickers": [
                    *list((short_trade_candidate_diagnostics or {}).get("tickers", []) or []),
                    *[
                        dict(entry)
                        for entry in early_runner_runtime_entries
                        if str(dict(entry).get("ticker") or "").strip() not in existing_short_trade_tickers
                    ],
                ],
                "early_runner_promoted_entries": [dict(entry) for entry in early_runner_runtime_entries],
            }
        return PostMarketWatchlistContext(
            watchlist=watchlist,
            layer_b_filter_diagnostics=layer_b_filter_diagnostics,
            watchlist_filter_diagnostics=watchlist_filter_diagnostics,
            historical_prior_by_ticker=historical_prior_by_ticker,
            short_trade_candidate_diagnostics=short_trade_candidate_diagnostics,
            catalyst_theme_candidate_diagnostics=catalyst_theme_candidate_diagnostics,
            candidate_by_ticker={candidate.ticker: candidate for candidate in [*candidate_context.candidates, *candidate_context.shadow_candidates]},
            price_map=build_watchlist_price_map(trade_date, [item.ticker for item in watchlist]),
        )

    def _build_post_market_order_context(
        self,
        *,
        trade_date: str,
        portfolio_snapshot: dict,
        blocked_buy_tickers: dict[str, dict],
        watchlist_context: PostMarketWatchlistContext,
        layer_c_results: list[LayerCResult],
        logic_scores: dict[str, float],
    ) -> tuple[PostMarketOrderContext, dict[str, float]]:
        with use_short_trade_target_profile(profile_name=self.short_trade_target_profile_name, overrides=self.short_trade_target_profile_overrides):
            prebuy_selection_targets, _ = build_selection_targets(
                trade_date=trade_date,
                watchlist=watchlist_context.watchlist,
                rejected_entries=[],
                supplemental_short_trade_entries=[],
                buy_order_tickers=set(),
                target_mode=self.target_mode,
            )

        stage_started_at = perf_counter()
        buy_orders, buy_order_filter_diagnostics = self._build_buy_orders_with_diagnostics(
            watchlist_context.watchlist,
            portfolio_snapshot,
            trade_date=trade_date,
            candidate_by_ticker=watchlist_context.candidate_by_ticker,
            price_map=watchlist_context.price_map,
            blocked_buy_tickers=blocked_buy_tickers,
            selection_targets=prebuy_selection_targets,
        )
        build_buy_orders_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        portfolio_snapshot = _attach_btst_runtime_exit_metrics_to_portfolio_snapshot(portfolio_snapshot, layer_c_results)
        sell_orders = self._run_exit_checker(portfolio_snapshot, trade_date, logic_scores)
        sell_check_seconds = perf_counter() - stage_started_at
        return (
            PostMarketOrderContext(
                prebuy_selection_targets=prebuy_selection_targets,
                buy_orders=buy_orders,
                buy_order_filter_diagnostics=buy_order_filter_diagnostics,
                sell_orders=sell_orders,
                sell_order_diagnostics=_build_sell_order_diagnostics(sell_orders),
            ),
            {
                "build_buy_orders_seconds": build_buy_orders_seconds,
                "sell_check_seconds": sell_check_seconds,
            },
        )

    def run_pre_market(
        self,
        plan: ExecutionPlan,
        trade_date_t1: str,
        refreshed_scores: dict[str, float] | None = None,
        atr_values: dict[str, float] | None = None,
        open_gap_pct: dict[str, float] | None = None,
        negative_news_tickers: set[str] | None = None,
    ) -> ExecutionPlan:
        return apply_signal_decay(
            plan,
            trade_date_t1,
            refreshed_scores=refreshed_scores,
            atr_values=atr_values,
            open_gap_pct=open_gap_pct,
            negative_news_tickers=negative_news_tickers,
        )

    def run_intraday(
        self,
        plan: ExecutionPlan,
        trade_date_t1: str,
        confirmation_inputs: dict[str, dict] | None = None,
        crisis_inputs: dict | None = None,
    ) -> tuple[list, list, dict]:
        confirmation_inputs = confirmation_inputs or {}
        confirmed_orders = []
        for order in plan.buy_orders:
            data = confirmation_inputs.get(order.ticker, {})
            result = confirm_buy_signal(
                day_low=float(data.get("day_low", 0.0)),
                ema30=float(data.get("ema30", 0.0)),
                current_price=float(data.get("current_price", 0.0)),
                vwap=float(data.get("vwap", 0.0)),
                intraday_volume=float(data.get("intraday_volume", 0.0)),
                avg_same_time_volume=float(data.get("avg_same_time_volume", 1.0)),
                industry_percentile=float(data.get("industry_percentile", 1.0)),
                stock_pct_change=float(data.get("stock_pct_change", 0.0)),
                industry_pct_change=float(data.get("industry_pct_change", 0.0)),
                open_price=float(data.get("open_price", 0.0)),
                prev_close=float(data.get("prev_close", 0.0)),
                breakout_anchor=float(data.get("breakout_anchor", 0.0)),
                open_gap_pct=data.get("open_gap_pct"),
                minutes_since_open=data.get("minutes_since_open"),
                failed_breakout=bool(data.get("failed_breakout", False)),
            )
            if result["confirmed"]:
                confirmed_orders.append(order)

        crisis_inputs = crisis_inputs or {}
        crisis_response = evaluate_crisis_response(
            hs300_daily_return=float(crisis_inputs.get("hs300_daily_return", 0.0)),
            limit_down_count=int(crisis_inputs.get("limit_down_count", 0)),
            recent_total_volumes=list(crisis_inputs.get("recent_total_volumes", [])),
            drawdown_pct=float(crisis_inputs.get("drawdown_pct", 0.0)),
        )
        exits = self._run_exit_checker(plan.portfolio_snapshot, trade_date_t1, plan.logic_scores)
        return confirmed_orders, exits, crisis_response

    def _build_buy_orders_with_diagnostics(
        self,
        watchlist: list[LayerCResult],
        portfolio_snapshot: dict,
        trade_date: str = "",
        candidate_by_ticker: dict[str, CandidateStock] | None = None,
        price_map: dict[str, float] | None = None,
        blocked_buy_tickers: dict[str, dict] | None = None,
        selection_targets: dict[str, DualTargetEvaluation] | None = None,
    ) -> tuple[list, dict]:
        return build_buy_orders_with_diagnostics(
            watchlist,
            portfolio_snapshot,
            trade_date=trade_date,
            candidate_by_ticker=candidate_by_ticker,
            price_map=price_map,
            blocked_buy_tickers=blocked_buy_tickers,
            selection_targets=selection_targets,
        )
