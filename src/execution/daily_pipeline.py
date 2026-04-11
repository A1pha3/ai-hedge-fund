"""日度执行流水线。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from inspect import signature
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Optional
import os

from scripts.btst_latest_followup_utils import load_latest_btst_historical_prior_by_ticker
from src.execution.daily_pipeline_candidate_helpers import (
    build_catalyst_theme_metrics_payload,
    build_catalyst_theme_tags,
    rank_scored_entries,
    resolve_catalyst_theme_filter_reason,
    resolve_short_trade_candidate_context,
)
from src.execution.daily_pipeline_hotspot_helpers import (
    build_upstream_shadow_catalyst_relief_payload,
    resolve_catalyst_relief_thresholds,
    resolve_selected_threshold,
    summarize_shadow_release_historical_support,
)
from src.execution.crisis_handler import evaluate_crisis_response
from src.execution.layer_c_aggregator import aggregate_layer_c_results
from src.execution.merge_approved_loader import load_merge_approved_tickers
from src.execution.merge_approved_breakout_uplift import (
    apply_merge_approved_breakout_uplift_to_signal_map,
    apply_merge_approved_layer_c_alignment_uplift,
    apply_merge_approved_sector_resonance_uplift,
    summarize_merge_approved_breakout_uplift_config,
)
from src.execution.models import ExecutionPlan, LayerCResult
from src.execution.plan_generator import generate_execution_plan
from src.execution.signal_decay import apply_signal_decay
from src.execution.t1_confirmation import confirm_buy_signal
from src.portfolio.exit_manager import check_exit_signal
from src.portfolio.models import HoldingState
from src.portfolio.position_calculator import STANDARD_EXECUTION_SCORE, calculate_position, enforce_daily_trade_limit
from src.screening.candidate_pool import build_candidate_pool, build_candidate_pool_with_shadow
from src.screening.models import CandidateStock
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetMode
from src.targets.profiles import build_short_trade_target_profile, use_short_trade_target_profile
from src.targets.router import build_selection_targets, summarize_selection_targets
from src.targets.short_trade_target import build_short_trade_target_snapshot_from_entry
from src.llm.defaults import get_default_model_config
from src.tools.tushare_api import get_daily_basic_batch


AgentRunner = Callable[[list[str], str, str], dict[str, dict[str, dict]]]
ExitChecker = Callable[..., list]


def _get_env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _get_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _get_env_csv_set(name: str, default: str) -> set[str]:
    raw_value = os.getenv(name, default)
    return {item.strip() for item in str(raw_value or "").split(",") if item.strip()}


FAST_AGENT_SCORE_THRESHOLD = _get_env_float("DAILY_PIPELINE_FAST_SCORE_THRESHOLD", 0.38)
FAST_AGENT_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_FAST_POOL_MAX_SIZE", 12)
PRECISE_AGENT_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_PRECISE_POOL_MAX_SIZE", 6)
WATCHLIST_SCORE_THRESHOLD = _get_env_float("DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD", 0.20)
MERGE_APPROVED_SCORE_BOOST = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_SCORE_BOOST", 0.08)
MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION", 0.05)
EXIT_REENTRY_CONFIRM_SCORE_MIN = _get_env_float("PIPELINE_EXIT_REENTRY_CONFIRM_SCORE_MIN", STANDARD_EXECUTION_SCORE)
EXIT_REENTRY_WEAK_CONFIRMATION_SCORE_MIN = _get_env_float("PIPELINE_EXIT_REENTRY_WEAK_CONFIRMATION_SCORE_MIN", 0.30)
CONTINUATION_EXECUTION_ENABLED = bool(_get_env_int("PIPELINE_CONTINUATION_EXECUTION_ENABLED", 1))
CONTINUATION_WATCHLIST_MIN_SCORE = _get_env_float("PIPELINE_CONTINUATION_WATCHLIST_MIN_SCORE", 0.21)
CONTINUATION_WATCHLIST_EDGE_EXECUTION_RATIO = _get_env_float("PIPELINE_CONTINUATION_WATCHLIST_EDGE_EXECUTION_RATIO", 0.3)
SHORT_TRADE_BOUNDARY_SCORE_BUFFER = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_SCORE_BUFFER", 0.08)
SHORT_TRADE_BOUNDARY_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_MAX_TICKERS", 6)
SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN", 0.24)
SHORT_TRADE_BOUNDARY_BREAKOUT_MIN = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_BREAKOUT_MIN", 0.18)
SHORT_TRADE_BOUNDARY_TREND_MIN = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_TREND_MIN", 0.22)
SHORT_TRADE_BOUNDARY_VOLUME_MIN = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_VOLUME_MIN", 0.15)
SHORT_TRADE_BOUNDARY_CATALYST_MIN = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CATALYST_MIN", 0.12)
UPSTREAM_SHADOW_OBSERVATION_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_UPSTREAM_SHADOW_OBSERVATION_MAX_TICKERS", 3)
UPSTREAM_SHADOW_RELEASE_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_MAX_TICKERS", 5)
UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN = _get_env_float("DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN", 0.30)
UPSTREAM_SHADOW_RELEASE_LANES = _get_env_csv_set(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_LANES",
    "layer_a_liquidity_corridor,post_gate_liquidity_competition",
)
UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS = {
    "layer_a_liquidity_corridor": _get_env_float(
        "DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_LIQUIDITY_CORRIDOR_SCORE_MIN",
        0.28,
    ),
    "post_gate_liquidity_competition": _get_env_float(
        "DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_POST_GATE_REBUCKET_SCORE_MIN",
        UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN,
    ),
}
UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS = {
    "layer_a_liquidity_corridor": _get_env_int(
        "DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_LIQUIDITY_CORRIDOR_MAX_TICKERS",
        4,
    ),
    "post_gate_liquidity_competition": _get_env_int(
        "DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_POST_GATE_REBUCKET_MAX_TICKERS",
        1,
    ),
}
UPSTREAM_SHADOW_CATALYST_RELIEF_CANDIDATE_SCORE_MIN = _get_env_float("DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_CANDIDATE_SCORE_MIN", 0.47)
UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN = _get_env_float("DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN", 0.38)
UPSTREAM_SHADOW_CATALYST_RELIEF_TREND_MIN = _get_env_float("DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_TREND_MIN", 0.80)
UPSTREAM_SHADOW_CATALYST_RELIEF_CLOSE_MIN = _get_env_float("DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_CLOSE_MIN", 0.85)
UPSTREAM_SHADOW_CATALYST_RELIEF_CATALYST_FRESHNESS_FLOOR = _get_env_float("DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_CATALYST_FRESHNESS_FLOOR", 1.0)
UPSTREAM_SHADOW_CATALYST_RELIEF_NEAR_MISS_THRESHOLD = _get_env_float("DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_NEAR_MISS_THRESHOLD", 0.45)
UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_NEAR_MISS_THRESHOLD = _get_env_float(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_NEAR_MISS_THRESHOLD",
    0.42,
)
UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_SELECTED_THRESHOLD = _get_env_float(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_SELECTED_THRESHOLD",
    0.45,
)
UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_SELECTED_THRESHOLD = _get_env_float(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_SELECTED_THRESHOLD",
    0.43,
)
UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_TREND_MIN = _get_env_float(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_TREND_MIN",
    0.75,
)
UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CLOSE_MIN = _get_env_float(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CLOSE_MIN",
    0.80,
)
UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_HISTORY_NEXT_CLOSE_MIN = _get_env_float(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_HISTORY_NEXT_CLOSE_MIN",
    0.50,
)
UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_REQUIRED_EXECUTION_QUALITY = _get_env_csv_set(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_REQUIRED_EXECUTION_QUALITY",
    "close_continuation",
)
UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_MIN_EVALUABLE_COUNT = _get_env_int(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_MIN_EVALUABLE_COUNT",
    2,
)
UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_CLOSE_MIN = _get_env_float(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_CLOSE_MIN",
    0.50,
)
UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_OPEN_TO_CLOSE_MIN = _get_env_float(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_OPEN_TO_CLOSE_MIN",
    0.0,
)
UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CANDIDATE_SCORE_MIN = _get_env_float(
    "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CANDIDATE_SCORE_MIN",
    0.44,
)
UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_DEFAULT = bool(
    _get_env_int("DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF", 1)
)
UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_BY_LANE = {
    "layer_a_liquidity_corridor": bool(
        _get_env_int("DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_LIQUIDITY_CORRIDOR_REQUIRE_NO_PROFITABILITY_HARD_CLIFF", 0)
    ),
    "post_gate_liquidity_competition": bool(
        _get_env_int(
            "DAILY_PIPELINE_UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_REBUCKET_REQUIRE_NO_PROFITABILITY_HARD_CLIFF",
            0,
        )
    ),
}
WATCHLIST_SHADOW_RELEASE_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_WATCHLIST_SHADOW_RELEASE_MAX_TICKERS", 2)
WATCHLIST_SHADOW_RELEASE_SCORE_B_MIN = _get_env_float("DAILY_PIPELINE_WATCHLIST_SHADOW_RELEASE_SCORE_B_MIN", FAST_AGENT_SCORE_THRESHOLD)
WATCHLIST_SHADOW_RELEASE_SCORE_FINAL_MIN = _get_env_float("DAILY_PIPELINE_WATCHLIST_SHADOW_RELEASE_SCORE_FINAL_MIN", 0.18)
WATCHLIST_SHADOW_RELEASE_SCORE_C_MIN = _get_env_float("DAILY_PIPELINE_WATCHLIST_SHADOW_RELEASE_SCORE_C_MIN", -0.08)
WATCHLIST_SHADOW_RELEASE_CONFLICTS = _get_env_csv_set(
    "DAILY_PIPELINE_WATCHLIST_SHADOW_RELEASE_CONFLICTS",
    "b_positive_c_strong_bearish",
)
CATALYST_THEME_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_CATALYST_THEME_MAX_TICKERS", 8)
CATALYST_THEME_SHADOW_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_CATALYST_THEME_SHADOW_MAX_TICKERS", 8)
CATALYST_THEME_CANDIDATE_SCORE_MIN = _get_env_float("DAILY_PIPELINE_CATALYST_THEME_CANDIDATE_SCORE_MIN", 0.34)
CATALYST_THEME_BREAKOUT_MIN = _get_env_float("DAILY_PIPELINE_CATALYST_THEME_BREAKOUT_MIN", 0.10)
CATALYST_THEME_CLOSE_MIN = _get_env_float("DAILY_PIPELINE_CATALYST_THEME_CLOSE_MIN", 0.20)
CATALYST_THEME_SECTOR_MIN = _get_env_float("DAILY_PIPELINE_CATALYST_THEME_SECTOR_MIN", 0.25)
CATALYST_THEME_CATALYST_MIN = _get_env_float("DAILY_PIPELINE_CATALYST_THEME_CATALYST_MIN", 0.45)
CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN = 0.35
CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN = 0.72
CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN = 0.85
CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_SECTOR_MIN = 0.10
CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN = _get_env_float("DAILY_PIPELINE_CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN", 0.45)
CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR = _get_env_float("DAILY_PIPELINE_CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR", 1.0)
CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD = _get_env_float("DAILY_PIPELINE_CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD", 0.44)
CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT = _get_env_int(
    "DAILY_PIPELINE_CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT",
    3,
)
CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF = bool(
    _get_env_int("DAILY_PIPELINE_CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF", 1)
)
BTST_REPORTS_ROOT = Path(os.getenv("DAILY_PIPELINE_BTST_REPORTS_ROOT", "data/reports")).expanduser()
MERGE_APPROVED_TICKERS = _get_env_csv_set("DAILY_PIPELINE_MERGE_APPROVED_TICKERS", "")
MERGE_APPROVED_MERGE_REVIEW_PATH = os.getenv("DAILY_PIPELINE_MERGE_APPROVED_MERGE_REVIEW_PATH", "")
MERGE_APPROVED_RANKING_PATH = os.getenv("DAILY_PIPELINE_MERGE_APPROVED_RANKING_PATH", "")
_ORIGINAL_BUILD_CANDIDATE_POOL = build_candidate_pool
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


def _load_candidate_pool_bundle(trade_date: str) -> tuple[list[CandidateStock], list[CandidateStock], dict[str, Any]]:
    if build_candidate_pool is not _ORIGINAL_BUILD_CANDIDATE_POOL and build_candidate_pool_with_shadow is _ORIGINAL_BUILD_CANDIDATE_POOL_WITH_SHADOW:
        candidates = build_candidate_pool(trade_date)
        return candidates, [], {
            "pool_size": len(candidates),
            "selected_count": len(candidates),
            "overflow_count": 0,
            "selected_cutoff_avg_volume_20d": round(float(candidates[-1].avg_volume_20d), 4) if candidates else 0.0,
            "lane_counts": {},
            "selected_tickers": [],
            "tickers": [],
        }
    return build_candidate_pool_with_shadow(trade_date)


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


def _default_exit_checker(portfolio_snapshot: dict, trade_date: str, logic_scores: dict[str, float] | None = None) -> list:
    positions = portfolio_snapshot.get("positions", {})
    active_tickers = [ticker for ticker, position in positions.items() if float(position.get("long", 0.0)) > 0]
    if not active_tickers:
        return []

    price_map = build_watchlist_price_map(trade_date, active_tickers)
    exits = []
    for ticker in active_tickers:
        current_price = price_map.get(ticker)
        if current_price is None or current_price <= 0:
            continue
        position = positions.get(ticker, {})
        shares = int(position.get("long", 0))
        entry_price = float(position.get("long_cost_basis", 0.0))
        if shares <= 0 or entry_price <= 0:
            continue
        holding = HoldingState(
            ticker=ticker,
            entry_price=entry_price,
            entry_date=str(position.get("entry_date") or trade_date),
            shares=shares,
            cost_basis=entry_price * shares,
            industry_sw=str(position.get("industry_sw", "")),
            max_unrealized_pnl_pct=float(position.get("max_unrealized_pnl_pct", 0.0)),
            holding_days=int(position.get("holding_days", 0)),
            profit_take_stage=int(position.get("profit_take_stage", 0)),
            entry_score=float(position.get("entry_score", 0.0)),
            quality_score=float(position.get("quality_score", 0.5)),
            is_fundamental_driven=bool(position.get("is_fundamental_driven", False)),
        )
        signal = check_exit_signal(
            holding,
            current_price=float(current_price),
            trade_date=trade_date,
            logic_score=(logic_scores or {}).get(ticker),
        )
        if signal is not None:
            exits.append(signal)
    return exits


def _build_filter_summary(entries: list[dict]) -> dict:
    reason_counts: dict[str, int] = {}
    for entry in entries:
        reason = str(entry.get("reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "filtered_count": len(entries),
        "reason_counts": reason_counts,
        "tickers": entries,
    }


def _load_latest_btst_historical_prior_by_ticker() -> dict[str, dict[str, Any]]:
    return load_latest_btst_historical_prior_by_ticker(BTST_REPORTS_ROOT)


def _historical_prior_value_is_missing(key: str, value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return True
        if key == "execution_quality_label" and normalized == "unknown":
            return True
    return False


def _resolve_historical_prior_for_ticker(*, ticker: str, historical_prior: dict[str, Any] | None, prior_by_ticker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    embedded_historical_prior = dict(historical_prior or {})
    latest_historical_prior = dict(prior_by_ticker.get(ticker) or {})
    if not embedded_historical_prior:
        return latest_historical_prior
    if not latest_historical_prior:
        return embedded_historical_prior

    resolved_historical_prior = dict(latest_historical_prior)
    for key, value in embedded_historical_prior.items():
        if _historical_prior_value_is_missing(str(key), value):
            continue
        resolved_historical_prior[str(key)] = value
    return resolved_historical_prior


def _refresh_attached_entry_relief(entry: dict[str, Any]) -> dict[str, Any]:
    updated_entry = dict(entry)
    candidate_pool_lane = str(updated_entry.get("candidate_pool_lane") or "")
    historical_prior = dict(updated_entry.get("historical_prior") or {})
    current_relief = dict(updated_entry.get("short_trade_catalyst_relief") or {})
    if candidate_pool_lane != "post_gate_liquidity_competition":
        return updated_entry
    if str(current_relief.get("reason") or "") != "upstream_shadow_catalyst_relief":
        return updated_entry
    next_close_positive_rate = historical_prior.get("next_close_positive_rate")
    if next_close_positive_rate is not None and float(next_close_positive_rate) < 0.5:
        updated_entry.pop("short_trade_catalyst_relief", None)
    return updated_entry


def _attach_historical_prior_to_entries(entries: list[dict[str, Any]], *, prior_by_ticker: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    attached_entries: list[dict[str, Any]] = []
    for entry in entries:
        updated_entry = dict(entry)
        ticker = str(updated_entry.get("ticker") or "")
        historical_prior = _resolve_historical_prior_for_ticker(
            ticker=ticker,
            historical_prior=dict(updated_entry.get("historical_prior") or {}),
            prior_by_ticker=prior_by_ticker,
        )
        if historical_prior:
            updated_entry["historical_prior"] = historical_prior
        updated_entry = _refresh_attached_entry_relief(updated_entry)
        attached_entries.append(updated_entry)
    return attached_entries


def _attach_historical_prior_to_watchlist(
    watchlist: list[LayerCResult],
    *,
    prior_by_ticker: dict[str, dict[str, Any]],
) -> list[LayerCResult]:
    attached_watchlist: list[LayerCResult] = []
    for item in list(watchlist or []):
        historical_prior = dict(prior_by_ticker.get(str(item.ticker or "")) or {})
        if historical_prior:
            attached_watchlist.append(item.model_copy(update={"historical_prior": historical_prior}))
        else:
            attached_watchlist.append(item)
    return attached_watchlist


def _historical_prior_float(prior: dict[str, Any], key: str) -> float | None:
    value = prior.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _historical_prior_int(prior: dict[str, Any], key: str) -> int | None:
    value = prior.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summarize_upstream_shadow_release_historical_support(historical_prior: dict[str, Any]) -> dict[str, Any]:
    prior = dict(historical_prior or {})
    execution_quality_label = str(prior.get("execution_quality_label") or "").strip()
    applied_scope = str(prior.get("applied_scope") or "").strip()
    evaluable_count = _historical_prior_int(prior, "evaluable_count") or 0
    next_close_positive_rate = _historical_prior_float(prior, "next_close_positive_rate")
    next_high_hit_rate = _historical_prior_float(prior, "next_high_hit_rate_at_threshold")
    support_summary = summarize_shadow_release_historical_support(
        execution_quality_label=execution_quality_label,
        applied_scope=applied_scope,
        evaluable_count=evaluable_count,
        next_close_positive_rate=next_close_positive_rate,
        next_high_hit_rate=next_high_hit_rate,
    )

    return {
        "execution_quality_label": execution_quality_label or None,
        "applied_scope": applied_scope or None,
        "evaluable_count": evaluable_count,
        "next_close_positive_rate": round(float(next_close_positive_rate), 4) if next_close_positive_rate is not None else None,
        "next_high_hit_rate_at_threshold": round(float(next_high_hit_rate), 4) if next_high_hit_rate is not None else None,
        **support_summary,
    }


def _supports_upstream_shadow_catalyst_relief_history(historical_prior: dict[str, Any] | None) -> bool:
    prior = dict(historical_prior or {})
    execution_quality_label = str(prior.get("execution_quality_label") or "").strip()
    evaluable_count = _historical_prior_int(prior, "evaluable_count") or 0
    next_close_positive_rate = _historical_prior_float(prior, "next_close_positive_rate")
    next_open_to_close_return_mean = _historical_prior_float(prior, "next_open_to_close_return_mean")

    return (
        execution_quality_label in UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_REQUIRED_EXECUTION_QUALITY
        and evaluable_count >= UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_MIN_EVALUABLE_COUNT
        and next_close_positive_rate is not None
        and next_close_positive_rate >= UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_CLOSE_MIN
        and next_open_to_close_return_mean is not None
        and next_open_to_close_return_mean >= UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_OPEN_TO_CLOSE_MIN
    )


def _build_layer_b_filter_diagnostics(fused: list, high_pool: list) -> dict:
    selected_tickers = {item.ticker for item in high_pool}
    entries: list[dict] = []
    for rank, item in enumerate(sorted(fused, key=lambda current: current.score_b, reverse=True), start=1):
        if item.ticker in selected_tickers:
            continue
        reason = "below_fast_score_threshold" if item.score_b < FAST_AGENT_SCORE_THRESHOLD else "high_pool_truncated_by_max_size"
        entries.append(
            {
                "ticker": item.ticker,
                "reason": reason,
                "score_b": round(item.score_b, 4),
                "decision": item.decision,
                "rank": rank,
            }
        )
    summary = _build_filter_summary(entries)
    summary["selected_tickers"] = [item.ticker for item in high_pool]
    return summary


def _classify_watchlist_filter(item: LayerCResult) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if item.decision == "avoid":
        reasons.append("decision_avoid")
    if item.score_final < WATCHLIST_SCORE_THRESHOLD:
        reasons.append("score_final_below_watchlist_threshold")
    if not reasons:
        reasons.append("filtered_from_watchlist")
    return reasons[0], reasons


def _build_watchlist_filter_diagnostics(
    layer_c_results: list[LayerCResult],
    watchlist: list[LayerCResult],
    *,
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
) -> dict:
    selected_tickers = {item.ticker for item in watchlist}
    entries: list[dict] = []
    selected_entries: list[dict] = []
    released_shadow_entries: list[dict[str, Any]] = []
    ranked_released_shadow_entries: list[tuple[float, float, dict[str, Any]]] = []
    for item in layer_c_results:
        payload = {
            "ticker": item.ticker,
            "score_b": round(item.score_b, 4),
            "score_c": round(item.score_c, 4),
            "score_final": round(item.score_final, 4),
            "quality_score": round(item.quality_score, 4),
            "decision": item.decision,
            "bc_conflict": item.bc_conflict,
            "merge_approved_ticker": item.ticker in merge_approved_tickers,
            "required_score_final_threshold": round(
                _watchlist_threshold_for_ticker(item.ticker, merge_approved_tickers, threshold_relaxation),
                4,
            ),
            "strategy_signals": {
                name: signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {})
                for name, signal in dict(item.strategy_signals or {}).items()
            },
            "agent_contribution_summary": item.agent_contribution_summary,
        }
        if item.ticker in selected_tickers:
            selected_entries.append(payload)
            continue
        primary_reason, reasons = _classify_watchlist_filter(item)
        entries.append({**payload, "reason": primary_reason, "reasons": reasons})
        should_release, release_reason = _should_release_watchlist_shadow_candidate(
            item=item,
            primary_reason=primary_reason,
        )
        if should_release and release_reason is not None:
            ranked_released_shadow_entries.append(
                (
                    float(item.score_final),
                    float(item.score_b),
                    _build_watchlist_shadow_release_entry(
                        item=item,
                        reasons=reasons,
                        release_reason=release_reason,
                    ),
                )
            )
    summary = _build_filter_summary(entries)
    ranked_released_shadow_entries.sort(key=lambda row: (row[0], row[1], str(row[2].get("ticker") or "")), reverse=True)
    for rank, (_, _, entry) in enumerate(ranked_released_shadow_entries[:WATCHLIST_SHADOW_RELEASE_MAX_TICKERS], start=1):
        entry["rank"] = rank
        released_shadow_entries.append(entry)
    summary["selected_tickers"] = [item.ticker for item in watchlist]
    summary["selected_entries"] = selected_entries
    summary["released_shadow_count"] = len(released_shadow_entries)
    summary["released_shadow_tickers"] = [entry["ticker"] for entry in released_shadow_entries]
    summary["released_shadow_entries"] = released_shadow_entries
    summary["prefilter_thresholds"] = {
        "score_b_min": round(WATCHLIST_SHADOW_RELEASE_SCORE_B_MIN, 4),
        "score_final_min": round(WATCHLIST_SHADOW_RELEASE_SCORE_FINAL_MIN, 4),
        "score_c_min": round(WATCHLIST_SHADOW_RELEASE_SCORE_C_MIN, 4),
        "conflicts": sorted(WATCHLIST_SHADOW_RELEASE_CONFLICTS),
    }
    summary["selection_thresholds"] = {
        "default_score_final_min": round(WATCHLIST_SCORE_THRESHOLD, 4),
        "merge_approved_score_final_min": round(max(0.0, WATCHLIST_SCORE_THRESHOLD - threshold_relaxation), 4),
        "merge_approved_tickers": sorted(merge_approved_tickers),
        "merge_approved_threshold_relaxation": round(threshold_relaxation, 4),
    }
    return summary


def _watchlist_threshold_for_ticker(ticker: str, merge_approved_tickers: set[str], threshold_relaxation: float) -> float:
    if ticker in merge_approved_tickers and threshold_relaxation > 0:
        return max(0.0, WATCHLIST_SCORE_THRESHOLD - threshold_relaxation)
    return WATCHLIST_SCORE_THRESHOLD


def _build_merge_approved_watchlist(
    layer_c_results: list[LayerCResult],
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
) -> list[LayerCResult]:
    return [
        item
        for item in layer_c_results
        if item.decision != "avoid" and item.score_final >= _watchlist_threshold_for_ticker(item.ticker, merge_approved_tickers, threshold_relaxation)
    ]


def _apply_merge_approved_fused_boost(
    fused: list,
    merge_approved_tickers: set[str],
    score_boost: float,
) -> list:
    if not merge_approved_tickers or score_boost <= 0:
        return fused
    boosted: list = []
    for item in fused:
        if item.ticker not in merge_approved_tickers:
            boosted.append(item)
            continue
        boosted_score_b = min(1.0, float(item.score_b) + score_boost)
        arbitration_applied = list(item.arbitration_applied or [])
        if "merge_approved_score_boost_applied" not in arbitration_applied:
            arbitration_applied.append("merge_approved_score_boost_applied")
        boosted.append(
            item.model_copy(
                update={
                    "score_b": boosted_score_b,
                    "decision": item.classify_decision(boosted_score_b),
                    "arbitration_applied": arbitration_applied,
                }
            )
        )
    return boosted


def _apply_merge_approved_breakout_signal_uplift(
    fused: list,
    merge_approved_tickers: set[str],
) -> tuple[list, dict[str, Any]]:
    if not merge_approved_tickers:
        return fused, {"applied_tickers": [], "eligible_tickers": [], "by_ticker": {}, "config": summarize_merge_approved_breakout_uplift_config()}
    uplifted: list = []
    by_ticker: dict[str, Any] = {}
    applied_tickers: list[str] = []
    eligible_tickers: list[str] = []
    for item in fused:
        if item.ticker not in merge_approved_tickers:
            uplifted.append(item)
            continue
        updated_signals, diagnostics = apply_merge_approved_breakout_uplift_to_signal_map(
            item.strategy_signals,
            score_b=float(item.score_b),
        )
        by_ticker[item.ticker] = diagnostics
        if diagnostics.get("eligible"):
            eligible_tickers.append(item.ticker)
        if diagnostics.get("applied"):
            applied_tickers.append(item.ticker)
            arbitration_applied = list(item.arbitration_applied or [])
            if "merge_approved_breakout_signal_uplift_applied" not in arbitration_applied:
                arbitration_applied.append("merge_approved_breakout_signal_uplift_applied")
            uplifted.append(
                item.model_copy(
                    update={
                        "strategy_signals": updated_signals,
                        "arbitration_applied": arbitration_applied,
                    }
                )
            )
            continue
        uplifted.append(item)
    return uplifted, {
        "config": summarize_merge_approved_breakout_uplift_config(),
        "eligible_tickers": sorted(eligible_tickers),
        "applied_tickers": sorted(applied_tickers),
        "by_ticker": by_ticker,
    }


def _apply_merge_approved_layer_c_alignment_uplift(
    layer_c_results: list[LayerCResult],
    merge_approved_tickers: set[str],
    breakout_signal_uplift: dict[str, Any],
) -> tuple[list[LayerCResult], dict[str, Any]]:
    if not merge_approved_tickers:
        return layer_c_results, {"applied_tickers": [], "eligible_tickers": [], "by_ticker": {}}
    uplifted: list[LayerCResult] = []
    by_ticker: dict[str, Any] = {}
    applied_tickers: list[str] = []
    eligible_tickers: list[str] = []
    breakout_by_ticker = dict(breakout_signal_uplift.get("by_ticker") or {})
    for item in layer_c_results:
        if item.ticker not in merge_approved_tickers:
            uplifted.append(item)
            continue
        updated_payload, diagnostics = apply_merge_approved_layer_c_alignment_uplift(
            item.model_dump(mode="json"),
            breakout_diagnostics=dict(breakout_by_ticker.get(item.ticker) or {}),
        )
        by_ticker[item.ticker] = diagnostics
        if diagnostics.get("eligible"):
            eligible_tickers.append(item.ticker)
        if diagnostics.get("applied"):
            applied_tickers.append(item.ticker)
            uplifted.append(
                item.model_copy(
                    update={
                        "score_c": updated_payload["score_c"],
                        "score_final": updated_payload["score_final"],
                        "decision": updated_payload["decision"],
                        "agent_contribution_summary": updated_payload["agent_contribution_summary"],
                    }
                )
            )
            continue
        uplifted.append(item)
    return uplifted, {
        "eligible_tickers": sorted(eligible_tickers),
        "applied_tickers": sorted(applied_tickers),
        "by_ticker": by_ticker,
    }


def _apply_merge_approved_sector_resonance_uplift(
    layer_c_results: list[LayerCResult],
    merge_approved_tickers: set[str],
    layer_c_alignment_uplift: dict[str, Any],
) -> tuple[list[LayerCResult], dict[str, Any]]:
    if not merge_approved_tickers:
        return layer_c_results, {"applied_tickers": [], "eligible_tickers": [], "by_ticker": {}}
    uplifted: list[LayerCResult] = []
    by_ticker: dict[str, Any] = {}
    applied_tickers: list[str] = []
    eligible_tickers: list[str] = []
    alignment_by_ticker = dict(layer_c_alignment_uplift.get("by_ticker") or {})
    for item in layer_c_results:
        if item.ticker not in merge_approved_tickers:
            uplifted.append(item)
            continue
        updated_payload, diagnostics = apply_merge_approved_sector_resonance_uplift(
            item.model_dump(mode="json"),
            alignment_diagnostics=dict(alignment_by_ticker.get(item.ticker) or {}),
        )
        by_ticker[item.ticker] = diagnostics
        if diagnostics.get("eligible"):
            eligible_tickers.append(item.ticker)
        if diagnostics.get("applied"):
            applied_tickers.append(item.ticker)
            uplifted.append(item.model_copy(update={"agent_contribution_summary": updated_payload["agent_contribution_summary"]}))
            continue
        uplifted.append(item)
    return uplifted, {
        "eligible_tickers": sorted(eligible_tickers),
        "applied_tickers": sorted(applied_tickers),
        "by_ticker": by_ticker,
    }


def _tag_merge_approved_layer_c_results(layer_c_results: list[LayerCResult], merge_approved_tickers: set[str]) -> list[LayerCResult]:
    if not merge_approved_tickers:
        return layer_c_results
    tagged_results: list[LayerCResult] = []
    for item in layer_c_results:
        if item.ticker not in merge_approved_tickers:
            tagged_results.append(item)
            continue
        candidate_reason_codes = [str(code) for code in list(item.candidate_reason_codes or []) if str(code or "").strip()]
        if "merge_approved_continuation" not in candidate_reason_codes:
            candidate_reason_codes.append("merge_approved_continuation")
        tagged_results.append(
            item.model_copy(
                update={
                    "candidate_source": "layer_c_watchlist_merge_approved",
                    "candidate_reason_codes": candidate_reason_codes,
                }
            )
        )
    return tagged_results


def _should_release_watchlist_shadow_candidate(*, item: LayerCResult, primary_reason: str) -> tuple[bool, str | None]:
    if primary_reason != "decision_avoid":
        return False, None
    if str(item.decision or "") != "avoid":
        return False, None
    if str(item.bc_conflict or "") not in WATCHLIST_SHADOW_RELEASE_CONFLICTS:
        return False, None
    if float(item.score_b) < WATCHLIST_SHADOW_RELEASE_SCORE_B_MIN:
        return False, None
    if float(item.score_final) < WATCHLIST_SHADOW_RELEASE_SCORE_FINAL_MIN:
        return False, None
    if float(item.score_c) < WATCHLIST_SHADOW_RELEASE_SCORE_C_MIN:
        return False, None
    return True, "watchlist_avoid_shadow_release_boundary_pass"


def _build_watchlist_shadow_release_entry(*, item: LayerCResult, reasons: list[str], release_reason: str) -> dict[str, Any]:
    resolved_reason_codes = [
        "watchlist_avoid_shadow_release",
        release_reason,
        *[str(reason) for reason in list(reasons or []) if str(reason or "").strip()],
    ]
    deduped_reason_codes: list[str] = []
    for code in resolved_reason_codes:
        if code not in deduped_reason_codes:
            deduped_reason_codes.append(code)

    return {
        "ticker": item.ticker,
        "score_b": round(float(item.score_b), 4),
        "score_c": round(float(item.score_c), 4),
        "score_final": round(float(item.score_final), 4),
        "quality_score": round(float(item.quality_score), 4),
        "decision": str(item.decision or "avoid"),
        "reason": "watchlist_avoid_shadow_release",
        "reasons": deduped_reason_codes,
        "candidate_source": "watchlist_avoid_shadow_release",
        "candidate_reason_codes": deduped_reason_codes,
        "bc_conflict": None,
        "source_decision": str(item.decision or ""),
        "source_bc_conflict": item.bc_conflict,
        "shadow_release_reason": release_reason,
        "shadow_release_thresholds": {
            "score_b_min": round(WATCHLIST_SHADOW_RELEASE_SCORE_B_MIN, 4),
            "score_final_min": round(WATCHLIST_SHADOW_RELEASE_SCORE_FINAL_MIN, 4),
            "score_c_min": round(WATCHLIST_SHADOW_RELEASE_SCORE_C_MIN, 4),
        },
        "strategy_signals": {
            name: signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {})
            for name, signal in dict(item.strategy_signals or {}).items()
        },
        "agent_contribution_summary": dict(item.agent_contribution_summary or {}),
        "promotion_trigger": "主 watchlist veto 保持不变；仅把边界 avoid 样本送入 short-trade supplemental replay，验证是否属于 000960 式 false negative。",
    }


def _build_short_trade_boundary_entry(
    *,
    item,
    reason: str,
    rank: int,
    candidate_source: str = "short_trade_boundary",
    upstream_candidate_source: str = "layer_b_boundary",
    candidate_reason_codes: list[str] | None = None,
    candidate_pool_rank: int | None = None,
    candidate_pool_lane: str | None = None,
    candidate_pool_shadow_reason: str | None = None,
    candidate_pool_avg_amount_share_of_cutoff: float | None = None,
    candidate_pool_avg_amount_share_of_min_gate: float | None = None,
    shadow_visibility_gap_selected: bool = False,
    shadow_visibility_gap_relaxed_band: bool = False,
) -> dict:
    resolved_reason_codes = [str(code) for code in list(candidate_reason_codes or [reason, "short_trade_prequalified"]) if str(code or "").strip()]
    if reason not in resolved_reason_codes:
        resolved_reason_codes.insert(0, reason)
    return {
        "ticker": item.ticker,
        "score_b": round(float(item.score_b), 4),
        "score_c": 0.0,
        "score_final": round(float(item.score_b), 4),
        "quality_score": 0.5,
        "decision": str(item.decision or "neutral"),
        "reason": reason,
        "reasons": resolved_reason_codes,
        "candidate_source": candidate_source,
        "upstream_candidate_source": upstream_candidate_source,
        "candidate_reason_codes": resolved_reason_codes,
        "strategy_signals": {
            name: signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {})
            for name, signal in dict(item.strategy_signals or {}).items()
        },
        "agent_contribution_summary": {},
        "rank": rank,
        "candidate_pool_rank": candidate_pool_rank,
        "candidate_pool_lane": candidate_pool_lane,
        "candidate_pool_shadow_reason": candidate_pool_shadow_reason,
        "candidate_pool_avg_amount_share_of_cutoff": candidate_pool_avg_amount_share_of_cutoff,
        "candidate_pool_avg_amount_share_of_min_gate": candidate_pool_avg_amount_share_of_min_gate,
        "shadow_visibility_gap_selected": shadow_visibility_gap_selected,
        "shadow_visibility_gap_relaxed_band": shadow_visibility_gap_relaxed_band,
    }


def _compute_short_trade_boundary_candidate_score(snapshot: dict) -> float:
    return round(
        (0.30 * float(snapshot.get("breakout_freshness", 0.0) or 0.0))
        + (0.25 * float(snapshot.get("trend_acceleration", 0.0) or 0.0))
        + (0.20 * float(snapshot.get("volume_expansion_quality", 0.0) or 0.0))
        + (0.15 * float(snapshot.get("catalyst_freshness", 0.0) or 0.0))
        + (0.10 * float(snapshot.get("close_strength", 0.0) or 0.0)),
        4,
    )


def _build_upstream_shadow_observation_entry(*, candidate_entry: dict[str, Any], filter_reason: str, metrics_payload: dict[str, Any]) -> dict[str, Any]:
    candidate_score = round(float(metrics_payload.get("candidate_score", 0.0) or 0.0), 4)
    gate_status = dict(metrics_payload.get("gate_status") or {})
    gate_status.setdefault("score", "shadow_observation")
    blockers = list(metrics_payload.get("blockers") or [])
    return {
        **candidate_entry,
        "decision": "observation",
        "score_target": candidate_score,
        "confidence": round(min(1.0, max(0.0, candidate_score)), 4),
        "top_reasons": [
            f"candidate_score={candidate_score:.2f}",
            f"filter_reason={filter_reason}",
            f"breakout_freshness={float(metrics_payload.get('breakout_freshness', 0.0) or 0.0):.2f}",
        ],
        "rejection_reasons": [filter_reason],
        "filter_reason": filter_reason,
        "gate_status": gate_status,
        "blockers": blockers,
        "metrics": {
            "breakout_freshness": metrics_payload.get("breakout_freshness"),
            "trend_acceleration": metrics_payload.get("trend_acceleration"),
            "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
            "close_strength": metrics_payload.get("close_strength"),
            "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
        },
        "promotion_trigger": "仅作上游影子补票观察；只有盘中新强度确认后才允许升级到 near-miss 或 selected 观察层。",
        "short_trade_boundary_metrics": metrics_payload,
    }


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
    return True, "upstream_shadow_release_score_floor_pass"


def _resolve_upstream_shadow_release_max_tickers(candidate_pool_lane: str) -> int:
    return int(UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS.get(candidate_pool_lane, UPSTREAM_SHADOW_RELEASE_MAX_TICKERS))


def _select_upstream_shadow_release_entries(
    ranked_released_shadow_entries: list[tuple[float, float, float, dict[str, Any]]],
) -> list[dict[str, Any]]:
    ranked_released_shadow_entries.sort(
        key=lambda row: (*row[:-1], str(row[-1].get("ticker") or "")),
        reverse=True,
    )
    selected_rows: list[tuple[float, float, float, dict[str, Any]]] = []
    lane_counts: dict[str, int] = {}
    for row in ranked_released_shadow_entries:
        entry = row[-1]
        candidate_pool_lane = str(entry.get("candidate_pool_lane") or "")
        lane_limit = _resolve_upstream_shadow_release_max_tickers(candidate_pool_lane)
        if lane_limit <= 0:
            continue
        if lane_counts.get(candidate_pool_lane, 0) >= lane_limit:
            continue
        selected_rows.append(row)
        lane_counts[candidate_pool_lane] = lane_counts.get(candidate_pool_lane, 0) + 1
        if len(selected_rows) >= UPSTREAM_SHADOW_RELEASE_MAX_TICKERS:
            break
    return rank_scored_entries(selected_rows, limit=len(selected_rows))


def _resolve_upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff(candidate_pool_lane: str) -> bool:
    return bool(
        UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_BY_LANE.get(
            candidate_pool_lane,
            UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_DEFAULT,
        )
    )


def _build_upstream_shadow_catalyst_relief_config(
    *,
    candidate_pool_lane: str,
    filter_reason: str,
    metrics_payload: dict[str, Any],
    historical_prior: dict[str, Any] | None = None,
    shadow_visibility_gap_selected: bool = False,
) -> dict[str, Any]:
    if filter_reason != "catalyst_freshness_below_short_trade_boundary_floor":
        return {}

    candidate_score = float(metrics_payload.get("candidate_score", 0.0) or 0.0)
    breakout_freshness = float(metrics_payload.get("breakout_freshness", 0.0) or 0.0)
    trend_acceleration = float(metrics_payload.get("trend_acceleration", 0.0) or 0.0)
    close_strength = float(metrics_payload.get("close_strength", 0.0) or 0.0)
    profitability_hard_cliff = bool(metrics_payload.get("profitability_hard_cliff"))
    candidate_score_min = float(UPSTREAM_SHADOW_CATALYST_RELIEF_CANDIDATE_SCORE_MIN)
    trend_acceleration_min = float(UPSTREAM_SHADOW_CATALYST_RELIEF_TREND_MIN)
    close_strength_min = float(UPSTREAM_SHADOW_CATALYST_RELIEF_CLOSE_MIN)
    historical_next_close_positive_rate_raw = dict(historical_prior or {}).get("next_close_positive_rate")
    historical_next_close_positive_rate = None
    if historical_next_close_positive_rate_raw is not None:
        try:
            historical_next_close_positive_rate = float(historical_next_close_positive_rate_raw)
        except (TypeError, ValueError):
            historical_next_close_positive_rate = None
    threshold_config = resolve_catalyst_relief_thresholds(
        candidate_pool_lane=candidate_pool_lane,
        profitability_hard_cliff=profitability_hard_cliff,
        historical_next_close_positive_rate=historical_next_close_positive_rate,
        candidate_score_min=float(UPSTREAM_SHADOW_CATALYST_RELIEF_CANDIDATE_SCORE_MIN),
        trend_acceleration_min=float(UPSTREAM_SHADOW_CATALYST_RELIEF_TREND_MIN),
        close_strength_min=float(UPSTREAM_SHADOW_CATALYST_RELIEF_CLOSE_MIN),
        near_miss_threshold=float(UPSTREAM_SHADOW_CATALYST_RELIEF_NEAR_MISS_THRESHOLD),
        post_gate_history_next_close_min=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_HISTORY_NEXT_CLOSE_MIN),
        post_gate_hard_cliff_candidate_score_min=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CANDIDATE_SCORE_MIN),
        post_gate_hard_cliff_trend_min=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_TREND_MIN),
        post_gate_hard_cliff_close_min=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CLOSE_MIN),
        post_gate_hard_cliff_near_miss_threshold=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_NEAR_MISS_THRESHOLD),
    )
    if threshold_config is None:
        return {}
    if not _supports_upstream_shadow_catalyst_relief_history(historical_prior):
        return {}
    if candidate_score < threshold_config["candidate_score_min"]:
        return {}
    if breakout_freshness < UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN:
        return {}
    if trend_acceleration < threshold_config["trend_acceleration_min"]:
        return {}
    if close_strength < threshold_config["close_strength_min"]:
        return {}

    require_no_profitability_hard_cliff = _resolve_upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff(candidate_pool_lane)
    selected_threshold_override_enabled, selected_threshold = resolve_selected_threshold(
        candidate_pool_lane=candidate_pool_lane,
        profitability_hard_cliff=profitability_hard_cliff,
        shadow_visibility_gap_selected=shadow_visibility_gap_selected,
        post_gate_selected_threshold=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_SELECTED_THRESHOLD),
        post_gate_hard_cliff_selected_threshold=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_SELECTED_THRESHOLD),
    )
    return build_upstream_shadow_catalyst_relief_payload(
        near_miss_threshold=threshold_config["near_miss_threshold"],
        selected_threshold_override_enabled=selected_threshold_override_enabled,
        selected_threshold=selected_threshold,
        breakout_freshness_min=UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN,
        trend_acceleration_min=threshold_config["trend_acceleration_min"],
        close_strength_min=threshold_config["close_strength_min"],
        require_no_profitability_hard_cliff=require_no_profitability_hard_cliff,
        required_execution_quality_labels=UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_REQUIRED_EXECUTION_QUALITY,
        min_historical_evaluable_count=UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_MIN_EVALUABLE_COUNT,
        min_historical_next_close_positive_rate=UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_CLOSE_MIN,
        min_historical_next_open_to_close_return_mean=UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_OPEN_TO_CLOSE_MIN,
        catalyst_freshness_floor=UPSTREAM_SHADOW_CATALYST_RELIEF_CATALYST_FRESHNESS_FLOOR,
    )


def _build_catalyst_theme_short_trade_carryover_relief_config(*, metrics_payload: dict[str, Any]) -> dict[str, Any]:
    close_momentum_catalyst_relief = dict(metrics_payload.get("close_momentum_catalyst_relief") or {})
    if not bool(close_momentum_catalyst_relief.get("applied")):
        return {}

    candidate_score = float(metrics_payload.get("candidate_score", 0.0) or 0.0)
    breakout_freshness = float(metrics_payload.get("breakout_freshness", 0.0) or 0.0)
    trend_acceleration = float(metrics_payload.get("trend_acceleration", 0.0) or 0.0)
    close_strength = float(metrics_payload.get("close_strength", 0.0) or 0.0)
    if candidate_score < CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN:
        return {}
    if breakout_freshness < CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN:
        return {}
    if trend_acceleration < CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN:
        return {}
    if close_strength < CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN:
        return {}

    return {
        "enabled": True,
        "reason": "catalyst_theme_short_trade_carryover",
        "catalyst_freshness_floor": round(CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR, 4),
        "near_miss_threshold": round(CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD, 4),
        "breakout_freshness_min": round(CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN, 4),
        "trend_acceleration_min": round(CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN, 4),
        "close_strength_min": round(CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN, 4),
        "min_historical_evaluable_count": int(CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT),
        "require_no_profitability_hard_cliff": CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF,
    }


def _build_upstream_shadow_release_entry(*, candidate_entry: dict[str, Any], filter_reason: str, metrics_payload: dict[str, Any], release_reason: str) -> dict[str, Any]:
    candidate_score = round(float(metrics_payload.get("candidate_score", 0.0) or 0.0), 4)
    candidate_pool_lane = str(candidate_entry.get("candidate_pool_lane") or "")
    lane_score_floor = round(float(UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS.get(candidate_pool_lane, UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN)), 4)
    historical_support = _summarize_upstream_shadow_release_historical_support(dict(candidate_entry.get("historical_prior") or {}))
    catalyst_relief_config = _build_upstream_shadow_catalyst_relief_config(
        candidate_pool_lane=candidate_pool_lane,
        filter_reason=filter_reason,
        metrics_payload=metrics_payload,
        historical_prior=dict(candidate_entry.get("historical_prior") or {}),
        shadow_visibility_gap_selected=bool(candidate_entry.get("shadow_visibility_gap_selected")),
    )
    resolved_reason_codes = [
        str(code)
        for code in list(candidate_entry.get("candidate_reason_codes") or candidate_entry.get("reasons") or [])
        if str(code or "").strip()
    ]
    for code in [filter_reason, release_reason, "upstream_shadow_release_candidate"]:
        if code not in resolved_reason_codes:
            resolved_reason_codes.append(code)
    return {
        **candidate_entry,
        "reasons": resolved_reason_codes,
        "candidate_reason_codes": resolved_reason_codes,
        "short_trade_boundary_metrics": dict(metrics_payload),
        "shadow_release_filter_reason": filter_reason,
        "shadow_release_reason": release_reason,
        "shadow_release_score_floor": lane_score_floor,
        "shadow_release_candidate_score": candidate_score,
        "shadow_release_historical_support": historical_support,
        "promotion_trigger": "受控 upstream shadow release 样本，仅进入 short-trade supplemental replay，默认不直接进入正式买入名单。",
        **({"short_trade_catalyst_relief": catalyst_relief_config} if catalyst_relief_config else {}),
    }


def _qualifies_short_trade_boundary_candidate(*, trade_date: str, entry: dict) -> tuple[bool, str, dict]:
    snapshot = build_short_trade_target_snapshot_from_entry(trade_date=trade_date, entry=entry)
    gate_status = dict(snapshot.get("gate_status") or {})
    blockers = sorted({str(blocker) for blocker in list(snapshot.get("blockers") or []) if str(blocker or "").strip()})
    metrics_payload = {
        "breakout_freshness": round(float(snapshot.get("breakout_freshness", 0.0) or 0.0), 4),
        "trend_acceleration": round(float(snapshot.get("trend_acceleration", 0.0) or 0.0), 4),
        "volume_expansion_quality": round(float(snapshot.get("volume_expansion_quality", 0.0) or 0.0), 4),
        "catalyst_freshness": round(float(snapshot.get("catalyst_freshness", 0.0) or 0.0), 4),
        "close_strength": round(float(snapshot.get("close_strength", 0.0) or 0.0), 4),
        "candidate_score": _compute_short_trade_boundary_candidate_score(snapshot),
        "gate_status": gate_status,
        "blockers": blockers,
    }

    if str(gate_status.get("data") or "") != "pass":
        return False, "metric_data_fail", metrics_payload
    if str(gate_status.get("structural") or "") == "fail" or blockers:
        return False, "structural_prefilter_fail", metrics_payload
    if float(metrics_payload.get("breakout_freshness", 0.0) or 0.0) < SHORT_TRADE_BOUNDARY_BREAKOUT_MIN:
        return False, "breakout_freshness_below_short_trade_boundary_floor", metrics_payload
    if float(metrics_payload.get("trend_acceleration", 0.0) or 0.0) < SHORT_TRADE_BOUNDARY_TREND_MIN:
        return False, "trend_acceleration_below_short_trade_boundary_floor", metrics_payload
    if float(metrics_payload.get("volume_expansion_quality", 0.0) or 0.0) < SHORT_TRADE_BOUNDARY_VOLUME_MIN:
        return False, "volume_expansion_below_short_trade_boundary_floor", metrics_payload
    if float(metrics_payload.get("catalyst_freshness", 0.0) or 0.0) < SHORT_TRADE_BOUNDARY_CATALYST_MIN:
        return False, "catalyst_freshness_below_short_trade_boundary_floor", metrics_payload
    if float(metrics_payload.get("candidate_score", 0.0) or 0.0) < SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN:
        return False, "candidate_score_below_short_trade_boundary_floor", metrics_payload
    return True, "short_trade_prequalified", metrics_payload


def _build_short_trade_candidate_diagnostics(
    fused: list,
    high_pool: list,
    trade_date: str,
    *,
    shadow_fused: list | None = None,
    shadow_candidate_by_ticker: dict[str, CandidateStock] | None = None,
    historical_prior_by_ticker: dict[str, dict[str, Any]] | None = None,
) -> dict:
    selected_tickers = {item.ticker for item in high_pool}
    entries: list[dict] = []
    shadow_observation_entries: list[dict] = []
    released_shadow_entries: list[dict] = []
    reason_counts: dict[str, int] = {}
    filtered_reason_counts: dict[str, int] = {}
    ranked_candidates: list[tuple[float, float, dict]] = []
    ranked_shadow_observations: list[tuple[float, float, dict]] = []
    ranked_released_shadow_entries: list[tuple[float, float, dict]] = []
    shadow_candidate_by_ticker = dict(shadow_candidate_by_ticker or {})
    upstream_candidates_by_ticker = {item.ticker: item for item in fused if item.ticker not in selected_tickers}
    for item in list(shadow_fused or []):
        if item.ticker not in selected_tickers:
            upstream_candidates_by_ticker.setdefault(item.ticker, item)
    upstream_candidates = sorted(upstream_candidates_by_ticker.values(), key=lambda current: current.score_b, reverse=True)

    for item in upstream_candidates:
        shadow_candidate = shadow_candidate_by_ticker.get(item.ticker)
        reason, candidate_source, upstream_candidate_source, candidate_reason_codes = resolve_short_trade_candidate_context(shadow_candidate)

        candidate_entry = _build_short_trade_boundary_entry(
            item=item,
            reason=reason,
            rank=0,
            candidate_source=candidate_source,
            upstream_candidate_source=upstream_candidate_source,
            candidate_reason_codes=candidate_reason_codes,
            candidate_pool_rank=int(shadow_candidate.candidate_pool_rank or 0) if shadow_candidate else None,
            candidate_pool_lane=str(shadow_candidate.candidate_pool_lane or "") if shadow_candidate else None,
            candidate_pool_shadow_reason=str(shadow_candidate.candidate_pool_shadow_reason or "") if shadow_candidate else None,
            candidate_pool_avg_amount_share_of_cutoff=round(float(shadow_candidate.candidate_pool_avg_amount_share_of_cutoff), 4) if shadow_candidate else None,
            candidate_pool_avg_amount_share_of_min_gate=round(float(shadow_candidate.candidate_pool_avg_amount_share_of_min_gate), 4) if shadow_candidate else None,
            shadow_visibility_gap_selected=bool(shadow_candidate.shadow_visibility_gap_selected) if shadow_candidate else False,
            shadow_visibility_gap_relaxed_band=bool(shadow_candidate.shadow_visibility_gap_relaxed_band) if shadow_candidate else False,
        )
        historical_prior = _resolve_historical_prior_for_ticker(
            ticker=str(item.ticker or ""),
            historical_prior=dict(candidate_entry.get("historical_prior") or {}),
            prior_by_ticker=historical_prior_by_ticker or {},
        )
        if historical_prior:
            candidate_entry["historical_prior"] = historical_prior
        qualified, filter_reason, metrics_payload = _qualifies_short_trade_boundary_candidate(trade_date=trade_date, entry=candidate_entry)
        if not qualified:
            filtered_reason_counts[filter_reason] = filtered_reason_counts.get(filter_reason, 0) + 1
            if shadow_candidate is not None:
                historical_support = _summarize_upstream_shadow_release_historical_support(historical_prior)
                should_release, release_reason = _should_release_upstream_shadow_candidate(
                    candidate_entry=candidate_entry,
                    filter_reason=filter_reason,
                    metrics_payload=metrics_payload,
                    historical_support=historical_support,
                )
                if should_release and release_reason is not None:
                    ranked_released_shadow_entries.append(
                        (
                            float(historical_support.get("support_score", 0.0) or 0.0),
                            float(metrics_payload.get("candidate_score", 0.0) or 0.0),
                            float(item.score_b),
                            _build_upstream_shadow_release_entry(
                                candidate_entry=candidate_entry,
                                filter_reason=filter_reason,
                                metrics_payload=metrics_payload,
                                release_reason=release_reason,
                            ),
                        )
                    )
                ranked_shadow_observations.append(
                    (
                        float(historical_support.get("support_score", 0.0) or 0.0),
                        float(metrics_payload.get("candidate_score", 0.0) or 0.0),
                        float(item.score_b),
                        _build_upstream_shadow_observation_entry(
                            candidate_entry=candidate_entry,
                            filter_reason=filter_reason,
                            metrics_payload=metrics_payload,
                        ),
                    )
                )
            continue

        historical_support = _summarize_upstream_shadow_release_historical_support(historical_prior)
        ranked_candidates.append(
            (
                float(historical_support.get("support_score", 0.0) or 0.0),
                float(metrics_payload.get("candidate_score", 0.0) or 0.0),
                float(item.score_b),
                {
                    **candidate_entry,
                    "short_trade_boundary_metrics": metrics_payload,
                    **({"shadow_release_historical_support": historical_support} if historical_prior else {}),
                },
            )
        )

    for entry in rank_scored_entries(ranked_candidates, limit=SHORT_TRADE_BOUNDARY_MAX_TICKERS):
        reason = str(entry.get("reason") or "short_trade_candidate_score_ranked")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        entries.append(entry)

    shadow_observation_entries.extend(rank_scored_entries(ranked_shadow_observations, limit=UPSTREAM_SHADOW_OBSERVATION_MAX_TICKERS))

    released_shadow_entries.extend(_select_upstream_shadow_release_entries(ranked_released_shadow_entries))

    return {
        "upstream_candidate_count": len(upstream_candidates),
        "candidate_count": len(entries),
        "shadow_observation_count": len(shadow_observation_entries),
        "released_shadow_count": len(released_shadow_entries),
        "reason_counts": reason_counts,
        "filtered_reason_counts": filtered_reason_counts,
        "prefilter_thresholds": {
            "candidate_score_min": round(SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN, 4),
            "breakout_freshness_min": round(SHORT_TRADE_BOUNDARY_BREAKOUT_MIN, 4),
            "trend_acceleration_min": round(SHORT_TRADE_BOUNDARY_TREND_MIN, 4),
            "volume_expansion_quality_min": round(SHORT_TRADE_BOUNDARY_VOLUME_MIN, 4),
            "catalyst_freshness_min": round(SHORT_TRADE_BOUNDARY_CATALYST_MIN, 4),
            "upstream_shadow_release_candidate_score_min": round(UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN, 4),
            "upstream_shadow_catalyst_relief_candidate_score_min": round(UPSTREAM_SHADOW_CATALYST_RELIEF_CANDIDATE_SCORE_MIN, 4),
            "upstream_shadow_catalyst_relief_breakout_min": round(UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN, 4),
            "upstream_shadow_catalyst_relief_trend_min": round(UPSTREAM_SHADOW_CATALYST_RELIEF_TREND_MIN, 4),
            "upstream_shadow_catalyst_relief_close_min": round(UPSTREAM_SHADOW_CATALYST_RELIEF_CLOSE_MIN, 4),
            "upstream_shadow_catalyst_relief_catalyst_freshness_floor": round(UPSTREAM_SHADOW_CATALYST_RELIEF_CATALYST_FRESHNESS_FLOOR, 4),
            "upstream_shadow_catalyst_relief_near_miss_threshold": round(UPSTREAM_SHADOW_CATALYST_RELIEF_NEAR_MISS_THRESHOLD, 4),
            "upstream_shadow_catalyst_relief_post_gate_selected_threshold": round(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_SELECTED_THRESHOLD, 4),
            "upstream_shadow_catalyst_relief_visibility_gap_corridor_selected_threshold": round(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_SELECTED_THRESHOLD, 4),
            "upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff": UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_DEFAULT,
            "upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_by_lane": {
                lane: _resolve_upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff(lane)
                for lane in sorted(UPSTREAM_SHADOW_RELEASE_LANES)
            },
            "upstream_shadow_release_lane_score_mins": {
                lane: round(float(score_min), 4)
                for lane, score_min in UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS.items()
            },
            "upstream_shadow_release_lane_max_tickers": {
                lane: int(limit)
                for lane, limit in UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS.items()
            },
        },
        "selected_tickers": [entry["ticker"] for entry in entries],
        "shadow_observation_tickers": [entry["ticker"] for entry in shadow_observation_entries],
        "released_shadow_tickers": [entry["ticker"] for entry in released_shadow_entries],
        "score_buffer": round(SHORT_TRADE_BOUNDARY_SCORE_BUFFER, 4),
        "minimum_score_b": round(FAST_AGENT_SCORE_THRESHOLD - SHORT_TRADE_BOUNDARY_SCORE_BUFFER, 4),
        "max_candidates": SHORT_TRADE_BOUNDARY_MAX_TICKERS,
        "tickers": entries,
        "shadow_observation_entries": shadow_observation_entries,
        "released_shadow_entries": released_shadow_entries,
    }


def _build_catalyst_theme_entry(*, item, reason: str, rank: int) -> dict:
    return {
        "ticker": item.ticker,
        "decision": "catalyst_theme",
        "score_b": round(float(item.score_b), 4),
        "score_c": 0.0,
        "score_final": round(float(item.score_b), 4),
        "quality_score": 0.5,
        "preferred_entry_mode": "theme_research_followup",
        "reason": reason,
        "reasons": [reason, "catalyst_theme_research_candidate"],
        "candidate_source": "catalyst_theme",
        "upstream_candidate_source": "layer_b_fused_universe",
        "candidate_reason_codes": [reason, "catalyst_theme_research_candidate"],
        "strategy_signals": {
            name: signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {})
            for name, signal in dict(item.strategy_signals or {}).items()
        },
        "agent_contribution_summary": {},
        "rank": rank,
    }


def _compute_catalyst_theme_candidate_score(snapshot: dict[str, Any]) -> float:
    return round(
        (0.40 * float(snapshot.get("catalyst_freshness", 0.0) or 0.0))
        + (0.25 * float(snapshot.get("sector_resonance", 0.0) or 0.0))
        + (0.15 * float(snapshot.get("breakout_freshness", 0.0) or 0.0))
        + (0.10 * float(snapshot.get("close_strength", 0.0) or 0.0))
        + (0.10 * float(snapshot.get("trend_acceleration", 0.0) or 0.0)),
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
    eligible = (
        catalyst_freshness < CATALYST_THEME_CATALYST_MIN
        and breakout_freshness >= CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN
        and trend_acceleration >= CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN
        and close_strength >= CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN
        and sector_resonance >= CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_SECTOR_MIN
    )
    effective_catalyst_freshness = round(max(catalyst_freshness, CATALYST_THEME_CATALYST_MIN if eligible else catalyst_freshness), 4)
    effective_sector_min = round(CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_SECTOR_MIN if eligible else CATALYST_THEME_SECTOR_MIN, 4)
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible,
        "effective_catalyst_freshness": effective_catalyst_freshness,
        "effective_sector_min": effective_sector_min,
    }


def _compute_catalyst_theme_threshold_shortfalls(metric_values: dict[str, Any], threshold_checks: dict[str, float] | None = None) -> dict[str, float]:
    threshold_checks = threshold_checks or {
        "candidate_score": round(float(CATALYST_THEME_CANDIDATE_SCORE_MIN), 4),
        "breakout_freshness": round(float(CATALYST_THEME_BREAKOUT_MIN), 4),
        "close_strength": round(float(CATALYST_THEME_CLOSE_MIN), 4),
        "sector_resonance": round(float(CATALYST_THEME_SECTOR_MIN), 4),
        "catalyst_freshness": round(float(CATALYST_THEME_CATALYST_MIN), 4),
    }
    shortfalls: dict[str, float] = {}
    for metric_key, threshold_value in threshold_checks.items():
        actual_value = round(float(metric_values.get(metric_key, 0.0) or 0.0), 4)
        shortfall = round(threshold_value - actual_value, 4)
        if shortfall > 0:
            shortfalls[metric_key] = shortfall
    return shortfalls


def _build_catalyst_theme_shadow_entry(*, item, filter_reason: str, metrics_payload: dict[str, Any]) -> dict[str, Any]:
    threshold_shortfalls = _compute_catalyst_theme_threshold_shortfalls(
        dict(metrics_payload.get("threshold_metric_values") or metrics_payload),
        dict(metrics_payload.get("threshold_checks") or {}),
    )
    total_shortfall = round(sum(threshold_shortfalls.values()), 4)
    return {
        **_build_catalyst_theme_entry(item=item, reason=filter_reason, rank=0),
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


def _qualifies_catalyst_theme_candidate(*, trade_date: str, entry: dict) -> tuple[bool, str, dict[str, Any]]:
    snapshot = build_short_trade_target_snapshot_from_entry(trade_date=trade_date, entry=entry)
    gate_status = dict(snapshot.get("gate_status") or {})
    blockers = sorted({str(blocker) for blocker in list(snapshot.get("blockers") or []) if str(blocker or "").strip()})

    breakout_freshness = round(float(snapshot.get("breakout_freshness", 0.0) or 0.0), 4)
    trend_acceleration = round(float(snapshot.get("trend_acceleration", 0.0) or 0.0), 4)
    close_strength = round(float(snapshot.get("close_strength", 0.0) or 0.0), 4)
    sector_resonance = round(float(snapshot.get("sector_resonance", 0.0) or 0.0), 4)
    catalyst_freshness = round(float(snapshot.get("catalyst_freshness", 0.0) or 0.0), 4)
    close_momentum_catalyst_relief = _resolve_catalyst_theme_close_momentum_relief(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        catalyst_freshness=catalyst_freshness,
    )
    effective_catalyst_freshness = round(float(close_momentum_catalyst_relief.get("effective_catalyst_freshness") or catalyst_freshness), 4)
    effective_sector_min = round(float(close_momentum_catalyst_relief.get("effective_sector_min") or CATALYST_THEME_SECTOR_MIN), 4)
    candidate_score = _compute_catalyst_theme_candidate_score(
        {
            "breakout_freshness": breakout_freshness,
            "trend_acceleration": trend_acceleration,
            "close_strength": close_strength,
            "sector_resonance": sector_resonance,
            "catalyst_freshness": effective_catalyst_freshness,
        }
    )
    threshold_checks = {
        "candidate_score": round(float(CATALYST_THEME_CANDIDATE_SCORE_MIN), 4),
        "breakout_freshness": round(float(CATALYST_THEME_BREAKOUT_MIN), 4),
        "close_strength": round(float(CATALYST_THEME_CLOSE_MIN), 4),
        "sector_resonance": effective_sector_min,
        "catalyst_freshness": round(float(CATALYST_THEME_CATALYST_MIN), 4),
    }
    threshold_metric_values = {
        "candidate_score": candidate_score,
        "breakout_freshness": breakout_freshness,
        "close_strength": close_strength,
        "sector_resonance": sector_resonance,
        "catalyst_freshness": effective_catalyst_freshness,
    }
    metrics_payload = build_catalyst_theme_metrics_payload(
        gate_status=gate_status,
        blockers=blockers,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        catalyst_freshness=catalyst_freshness,
        candidate_score=candidate_score,
        effective_catalyst_freshness=effective_catalyst_freshness,
        close_momentum_catalyst_relief=close_momentum_catalyst_relief,
        threshold_checks=threshold_checks,
        threshold_metric_values=threshold_metric_values,
        theme_tags=build_catalyst_theme_tags(
            catalyst_freshness=catalyst_freshness,
            catalyst_freshness_min=CATALYST_THEME_CATALYST_MIN,
            breakout_freshness=breakout_freshness,
            close_strength=close_strength,
            sector_resonance=sector_resonance,
            close_momentum_catalyst_relief_applied=bool(close_momentum_catalyst_relief.get("applied")),
        ),
    )
    filter_reason = resolve_catalyst_theme_filter_reason(
        gate_status=gate_status,
        effective_catalyst_freshness=effective_catalyst_freshness,
        catalyst_freshness_min=CATALYST_THEME_CATALYST_MIN,
        sector_resonance=sector_resonance,
        effective_sector_min=effective_sector_min,
        close_strength=close_strength,
        close_strength_min=CATALYST_THEME_CLOSE_MIN,
        breakout_freshness=breakout_freshness,
        breakout_freshness_min=CATALYST_THEME_BREAKOUT_MIN,
        candidate_score=candidate_score,
        candidate_score_min=CATALYST_THEME_CANDIDATE_SCORE_MIN,
    )
    return filter_reason == "catalyst_theme_candidate_score_ranked", filter_reason, metrics_payload


def _build_catalyst_theme_candidate_diagnostics(
    fused: list,
    watchlist: list[LayerCResult],
    short_trade_candidate_diagnostics: dict[str, Any],
    trade_date: str,
) -> dict[str, Any]:
    excluded_tickers = {item.ticker for item in watchlist}
    excluded_tickers.update(str(ticker) for ticker in list((short_trade_candidate_diagnostics or {}).get("selected_tickers", []) or []))

    entries: list[dict[str, Any]] = []
    shadow_entries: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}
    filtered_reason_counts: dict[str, int] = {}
    ranked_candidates: list[tuple[float, float, dict[str, Any]]] = []
    ranked_shadow_candidates: list[tuple[float, float, float, dict[str, Any]]] = []
    upstream_candidates = sorted(
        [item for item in fused if item.ticker not in excluded_tickers],
        key=lambda current: current.score_b,
        reverse=True,
    )

    for item in upstream_candidates:
        reason = "catalyst_theme_candidate_score_ranked"
        candidate_entry = _build_catalyst_theme_entry(item=item, reason=reason, rank=0)
        qualified, filter_reason, metrics_payload = _qualifies_catalyst_theme_candidate(trade_date=trade_date, entry=candidate_entry)
        if not qualified:
            filtered_reason_counts[filter_reason] = filtered_reason_counts.get(filter_reason, 0) + 1
            if filter_reason != "metric_data_fail":
                shadow_entry = _build_catalyst_theme_shadow_entry(item=item, filter_reason=filter_reason, metrics_payload=metrics_payload)
                ranked_shadow_candidates.append(
                    (
                        float(metrics_payload.get("candidate_score", 0.0) or 0.0),
                        -float(shadow_entry.get("total_shortfall", 0.0) or 0.0),
                        float(item.score_b),
                        shadow_entry,
                    )
                )
            continue

        carryover_relief_config = _build_catalyst_theme_short_trade_carryover_relief_config(metrics_payload=metrics_payload)
        resolved_reason_codes = [
            str(code)
            for code in list(candidate_entry.get("candidate_reason_codes") or candidate_entry.get("reasons") or [])
            if str(code or "").strip()
        ]
        if carryover_relief_config and "catalyst_theme_short_trade_carryover_candidate" not in resolved_reason_codes:
            resolved_reason_codes.append("catalyst_theme_short_trade_carryover_candidate")
        ranked_candidates.append(
            (
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
            )
        )

    ranked_candidates.sort(key=lambda row: (row[0], row[1], str(row[2].get("ticker") or "")), reverse=True)
    for rank, (_, _, entry) in enumerate(ranked_candidates[:CATALYST_THEME_MAX_TICKERS], start=1):
        entry["rank"] = rank
        reason = str(entry.get("reason") or "catalyst_theme_candidate_score_ranked")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        entries.append(entry)

    ranked_shadow_candidates.sort(key=lambda row: (row[0], row[1], row[2], str(row[3].get("ticker") or "")), reverse=True)
    for rank, (_, _, _, entry) in enumerate(ranked_shadow_candidates[:CATALYST_THEME_SHADOW_MAX_TICKERS], start=1):
        entry["rank"] = rank
        shadow_entries.append(entry)

    return {
        "upstream_candidate_count": len(upstream_candidates),
        "candidate_count": len(entries),
        "shadow_candidate_count": len(shadow_entries),
        "reason_counts": reason_counts,
        "filtered_reason_counts": filtered_reason_counts,
        "prefilter_thresholds": {
            "candidate_score_min": round(CATALYST_THEME_CANDIDATE_SCORE_MIN, 4),
            "breakout_freshness_min": round(CATALYST_THEME_BREAKOUT_MIN, 4),
            "close_strength_min": round(CATALYST_THEME_CLOSE_MIN, 4),
            "sector_resonance_min": round(CATALYST_THEME_SECTOR_MIN, 4),
            "catalyst_freshness_min": round(CATALYST_THEME_CATALYST_MIN, 4),
            "short_trade_carryover_candidate_score_min": round(CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN, 4),
            "short_trade_carryover_catalyst_freshness_floor": round(CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR, 4),
            "short_trade_carryover_near_miss_threshold": round(CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD, 4),
            "short_trade_carryover_min_historical_evaluable_count": int(CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT),
            "short_trade_carryover_require_no_profitability_hard_cliff": CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF,
        },
        "selected_tickers": [entry["ticker"] for entry in entries],
        "shadow_tickers": [entry["ticker"] for entry in shadow_entries],
        "max_candidates": CATALYST_THEME_MAX_TICKERS,
        "tickers": entries,
        "shadow_candidates": shadow_entries,
    }


def _extract_sell_order_value(order, field_name: str, default=None):
    if isinstance(order, dict):
        return order.get(field_name, default)
    return getattr(order, field_name, default)


def _build_sell_order_diagnostics(sell_orders: list) -> dict:
    entries: list[dict] = []
    for order in sell_orders:
        reason = (
            _extract_sell_order_value(order, "trigger_reason")
            or _extract_sell_order_value(order, "level")
            or _extract_sell_order_value(order, "reason")
            or "sell_signal"
        )
        entries.append(
            {
                "ticker": _extract_sell_order_value(order, "ticker", ""),
                "reason": str(reason),
                "level": _extract_sell_order_value(order, "level"),
                "urgency": _extract_sell_order_value(order, "urgency"),
                "sell_ratio": _extract_sell_order_value(order, "sell_ratio"),
            }
        )
    summary = _build_filter_summary(entries)
    summary["count"] = len(sell_orders)
    return summary


def _normalize_blocked_buy_tickers(blocked_buy_tickers: dict[str, dict] | None) -> dict[str, dict]:
    normalized: dict[str, dict] = {}
    for ticker, payload in (blocked_buy_tickers or {}).items():
        normalized[str(ticker)] = dict(payload or {})
    return normalized


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
    normalized_ticker = str(ticker)
    blocked_until = str(cooldown_payload.get("blocked_until") or "")
    trigger_reason = str(cooldown_payload.get("trigger_reason") or "")
    exit_trade_date = str(cooldown_payload.get("exit_trade_date") or "")
    if blocked_until and trade_date and trade_date < blocked_until:
        return {
            "ticker": normalized_ticker,
            "reason": "blocked_by_exit_cooldown",
            "score_final": round(score_final, 4),
            "blocked_until": blocked_until,
            "trigger_reason": trigger_reason,
            "exit_trade_date": exit_trade_date,
        }

    reentry_review_until = str(cooldown_payload.get("reentry_review_until") or "")
    required_score, weak_confirmation_reentry_guard = _resolve_reentry_required_score(cooldown_payload, selection_target)
    if reentry_review_until and trade_date and trade_date <= reentry_review_until and score_final < required_score:
        return {
            "ticker": normalized_ticker,
            "reason": "blocked_by_reentry_score_confirmation",
            "score_final": round(score_final, 4),
            "required_score": round(required_score, 4),
            "weak_confirmation_reentry_guard": weak_confirmation_reentry_guard,
            "reentry_review_until": reentry_review_until,
            "trigger_reason": trigger_reason,
            "exit_trade_date": exit_trade_date,
        }

    return None


def _build_reentry_filter_entry(
    item: LayerCResult,
    cooldown_payload: dict,
    trade_date: str,
    selection_target: DualTargetEvaluation | None = None,
) -> dict | None:
    return _build_reentry_filter_payload(item.ticker, item.score_final, cooldown_payload, trade_date, selection_target=selection_target)


def _to_ts_code_for_price_lookup(ticker: str) -> str:
    ticker = ticker.strip().lower()
    if ticker.startswith("sh"):
        return f"{ticker[2:]}.SH"
    if ticker.startswith("sz"):
        return f"{ticker[2:]}.SZ"
    if ticker.startswith("bj"):
        return f"{ticker[2:]}.BJ"
    if ticker.startswith(("6", "68", "51", "56", "58", "60")):
        return f"{ticker}.SH"
    if ticker.startswith(("0", "3", "15", "16", "18", "20")):
        return f"{ticker}.SZ"
    if ticker.startswith(("4", "8", "43", "83", "87", "92")):
        return f"{ticker}.BJ"
    return f"{ticker}.SZ"


def build_watchlist_price_map(trade_date: str, tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    df = get_daily_basic_batch(trade_date)
    if df is None or df.empty or "ts_code" not in df.columns or "close" not in df.columns:
        return {}

    ts_to_ticker = {_to_ts_code_for_price_lookup(ticker): ticker for ticker in tickers}
    filtered = df[df["ts_code"].isin(ts_to_ticker.keys())]
    if filtered.empty:
        return {}

    price_map: dict[str, float] = {}
    for _, row in filtered.iterrows():
        ticker = ts_to_ticker.get(str(row["ts_code"]))
        close = row.get("close")
        if ticker and close is not None:
            try:
                price_map[ticker] = float(close)
            except (TypeError, ValueError):
                continue
    return price_map


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


def _ensure_plan_target_shells(
    plan: ExecutionPlan,
    target_mode: TargetMode,
    *,
    short_trade_target_profile_name: str = "default",
    short_trade_target_profile_overrides: dict[str, object] | None = None,
) -> ExecutionPlan:
    selection_targets = dict(plan.selection_targets or {})
    summary = plan.dual_target_summary if isinstance(plan.dual_target_summary, DualTargetSummary) else DualTargetSummary.model_validate(plan.dual_target_summary or {})
    watchlist_filter_diagnostics = ((((plan.risk_metrics or {}).get("funnel_diagnostics", {}) or {}).get("filters", {}) or {}).get("watchlist", {}) or {})
    short_trade_candidate_diagnostics = ((((plan.risk_metrics or {}).get("funnel_diagnostics", {}) or {}).get("filters", {}) or {}).get("short_trade_candidates", {}) or {})
    historical_prior_by_ticker = _load_latest_btst_historical_prior_by_ticker()
    rejected_entries = _attach_historical_prior_to_entries(
        list(watchlist_filter_diagnostics.get("tickers", []) or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    watchlist = _attach_historical_prior_to_watchlist(
        list(plan.watchlist or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    funnel_diagnostics = dict((plan.risk_metrics or {}).get("funnel_diagnostics", {}) or {})
    funnel_filters = dict(funnel_diagnostics.get("filters", {}) or {})
    catalyst_theme_candidates = list(dict(funnel_filters.get("catalyst_theme_candidates", {}) or {}).get("tickers", []) or []) if target_mode == "short_trade_only" else []
    supplemental_short_trade_entries = _attach_historical_prior_to_entries(
        [
            *list(short_trade_candidate_diagnostics.get("tickers", []) or []),
            *list(short_trade_candidate_diagnostics.get("released_shadow_entries", []) or []),
            *list(watchlist_filter_diagnostics.get("released_shadow_entries", []) or []),
            *catalyst_theme_candidates,
        ],
        prior_by_ticker=historical_prior_by_ticker,
    )
    buy_order_tickers = {order.ticker for order in list(plan.buy_orders or [])}
    if not selection_targets and (watchlist or rejected_entries or supplemental_short_trade_entries):
        with use_short_trade_target_profile(profile_name=short_trade_target_profile_name, overrides=short_trade_target_profile_overrides):
            selection_targets, summary = build_selection_targets(
                trade_date=plan.date,
                watchlist=watchlist,
                rejected_entries=rejected_entries,
                supplemental_short_trade_entries=supplemental_short_trade_entries,
                buy_order_tickers=buy_order_tickers,
                target_mode=target_mode,
            )
    else:
        summary = summarize_selection_targets(selection_targets=selection_targets, target_mode=target_mode)

    plan.selection_targets = selection_targets
    plan.target_mode = target_mode
    plan.dual_target_summary = summary
    return _attach_short_trade_target_profile(
        plan,
        profile_name=short_trade_target_profile_name,
        profile_overrides=short_trade_target_profile_overrides,
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
    cash = float(portfolio_snapshot.get("cash", 0.0))
    nav = cash + sum(
        float(position.get("long", 0)) * float(position.get("long_cost_basis", 0.0))
        for position in portfolio_snapshot.get("positions", {}).values()
    )
    nav = nav if nav > 0 else cash
    candidate_by_ticker = candidate_by_ticker or {}
    price_map = price_map or {}
    blocked_buy_tickers = _normalize_blocked_buy_tickers(blocked_buy_tickers)
    if not watchlist:
        return [], _build_filter_summary([])
    if cash <= 0:
        entries = [
            {
                "ticker": item.ticker,
                "reason": "no_available_cash",
                "score_final": round(item.score_final, 4),
            }
            for item in watchlist
        ]
        summary = _build_filter_summary(entries)
        summary["selected_tickers"] = []
        return [], summary

    per_name_cash = cash / max(1, min(3, len(watchlist)))
    candidate_plans = []
    filtered_entries: list[dict] = []
    selection_targets = selection_targets or {}
    for item in watchlist:
        cooldown_payload = blocked_buy_tickers.get(item.ticker)
        if cooldown_payload is not None:
            reentry_filter_entry = _build_reentry_filter_entry(
                item,
                cooldown_payload,
                trade_date,
                selection_target=selection_targets.get(item.ticker),
            )
            if reentry_filter_entry is not None:
                filtered_entries.append(reentry_filter_entry)
                continue
        current_price = float(price_map.get(item.ticker, 10.0))
        candidate = candidate_by_ticker.get(item.ticker)
        avg_volume_20d = float(candidate.avg_volume_20d) if candidate and candidate.avg_volume_20d > 0 else 10_000_000.0
        industry_quota = nav * 0.25
        existing_position = portfolio_snapshot.get("positions", {}).get(item.ticker, {})
        existing_long_shares = float(existing_position.get("long", 0.0))
        existing_position_ratio = ((existing_long_shares * current_price) / nav) if nav > 0 else 0.0
        continuation_overrides = _resolve_continuation_execution_overrides(item=item, selection_target=selection_targets.get(item.ticker))
        plan = calculate_position(
            ticker=item.ticker,
            current_price=current_price,
            score_final=item.score_final,
            portfolio_nav=nav,
            available_cash=min(cash, per_name_cash),
            avg_volume_20d=avg_volume_20d,
            industry_remaining_quota=industry_quota,
            quality_score=item.quality_score,
            existing_position_ratio=existing_position_ratio,
            watchlist_min_score_override=continuation_overrides.get("watchlist_min_score_override"),
            watchlist_edge_execution_ratio_override=continuation_overrides.get("watchlist_edge_execution_ratio_override"),
        )
        if plan.shares > 0:
            candidate_plans.append(plan)
            continue
        filtered_entries.append(
            {
                "ticker": item.ticker,
                "reason": f"position_blocked_{plan.constraint_binding or 'unknown'}",
                "score_final": round(item.score_final, 4),
                "constraint_binding": plan.constraint_binding,
                "amount": round(plan.amount, 4),
                "execution_ratio": plan.execution_ratio,
                "quality_score": round(plan.quality_score, 4),
                "continuation_execution_override": bool(continuation_overrides.get("applied")),
            }
        )

    buy_orders = enforce_daily_trade_limit(candidate_plans, nav)
    selected_tickers = {plan.ticker for plan in buy_orders}
    for plan in candidate_plans:
        if plan.ticker in selected_tickers:
            continue
        filtered_entries.append(
            {
                "ticker": plan.ticker,
                "reason": "filtered_by_daily_trade_limit",
                "score_final": round(plan.score_final, 4),
                "constraint_binding": plan.constraint_binding,
                "amount": round(plan.amount, 4),
                "execution_ratio": plan.execution_ratio,
                "quality_score": round(plan.quality_score, 4),
            }
        )

    summary = _build_filter_summary(filtered_entries)
    summary["selected_tickers"] = [plan.ticker for plan in buy_orders]
    return buy_orders, summary


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
        if model_tier == "fast" and self.fast_selected_analysts is not None:
            return list(self.fast_selected_analysts)
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
            self.execution_plan_provenance_log.append(
                execution_observation
            )
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

    def run_post_market(self, trade_date: str, portfolio_snapshot: Optional[dict] = None, blocked_buy_tickers: dict[str, dict] | None = None) -> ExecutionPlan:
        blocked_buy_tickers = _normalize_blocked_buy_tickers(blocked_buy_tickers)
        if self.frozen_post_market_plans is not None:
            frozen_plan = self.frozen_post_market_plans.get(trade_date)
            if frozen_plan is None:
                raise ValueError(f"Missing frozen current_plan for trade_date={trade_date}")
            return self._apply_frozen_buy_order_filters(frozen_plan, trade_date, blocked_buy_tickers)

        total_started_at = perf_counter()
        portfolio_snapshot = portfolio_snapshot or {"cash": 1_000_000, "positions": {}}

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
        high_pool = sorted(
            [item for item in fused if item.score_b >= FAST_AGENT_SCORE_THRESHOLD],
            key=lambda item: item.score_b,
            reverse=True,
        )[:FAST_AGENT_MAX_TICKERS]

        stage_started_at = perf_counter()
        agent_results = self.agent_runner([item.ticker for item in high_pool], trade_date, "fast") if high_pool else {}
        fast_agent_seconds = perf_counter() - stage_started_at

        top_20 = high_pool[:PRECISE_AGENT_MAX_TICKERS]
        skipped_precise_ticker_count = len(top_20) if self._skip_precise_stage else 0
        estimated_skipped_precise_seconds = _estimate_skipped_precise_seconds(fast_agent_seconds, len(high_pool), skipped_precise_ticker_count)
        stage_started_at = perf_counter()
        if top_20 and not self._skip_precise_stage:
            precise_results = self.agent_runner([item.ticker for item in top_20], trade_date, "precise")
            for agent_id, ticker_payload in precise_results.items():
                agent_results.setdefault(agent_id, {}).update(ticker_payload)
        precise_agent_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        layer_c_results = aggregate_layer_c_results(high_pool, agent_results)
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
        logic_scores = _build_logic_score_map(layer_c_results)
        watchlist = _build_merge_approved_watchlist(
            layer_c_results,
            self.merge_approved_tickers,
            MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION,
        )
        layer_b_filter_diagnostics = _build_layer_b_filter_diagnostics(fused, high_pool)
        watchlist_filter_diagnostics = _build_watchlist_filter_diagnostics(
            layer_c_results,
            watchlist,
            merge_approved_tickers=self.merge_approved_tickers,
            threshold_relaxation=MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION,
        )
        historical_prior_by_ticker = _load_latest_btst_historical_prior_by_ticker()
        short_trade_candidate_diagnostics = _build_short_trade_candidate_diagnostics(
            fused,
            high_pool,
            trade_date,
            shadow_fused=shadow_fused,
            shadow_candidate_by_ticker={candidate.ticker: candidate for candidate in shadow_candidates},
            historical_prior_by_ticker=historical_prior_by_ticker,
        )
        watchlist = _attach_historical_prior_to_watchlist(
            watchlist,
            prior_by_ticker=historical_prior_by_ticker,
        )
        catalyst_theme_candidate_diagnostics = _build_catalyst_theme_candidate_diagnostics(
            fused,
            watchlist,
            short_trade_candidate_diagnostics,
            trade_date,
        )

        candidate_by_ticker = {candidate.ticker: candidate for candidate in candidates}
        price_map = build_watchlist_price_map(trade_date, [item.ticker for item in watchlist])
        with use_short_trade_target_profile(profile_name=self.short_trade_target_profile_name, overrides=self.short_trade_target_profile_overrides):
            prebuy_selection_targets, _ = build_selection_targets(
                trade_date=trade_date,
                watchlist=watchlist,
                rejected_entries=[],
                supplemental_short_trade_entries=[],
                buy_order_tickers=set(),
                target_mode=self.target_mode,
            )

        stage_started_at = perf_counter()
        buy_orders, buy_order_filter_diagnostics = self._build_buy_orders_with_diagnostics(
            watchlist,
            portfolio_snapshot,
            trade_date=trade_date,
            candidate_by_ticker=candidate_by_ticker,
            price_map=price_map,
            blocked_buy_tickers=blocked_buy_tickers,
            selection_targets=prebuy_selection_targets,
        )
        build_buy_orders_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        sell_orders = self._run_exit_checker(portfolio_snapshot, trade_date, logic_scores)
        sell_check_seconds = perf_counter() - stage_started_at
        sell_order_diagnostics = _build_sell_order_diagnostics(sell_orders)

        counts = {
            "layer_a_count": len(candidates),
            "layer_b_count": len(high_pool),
            "layer_c_count": len(layer_c_results),
            "watchlist_count": len(watchlist),
            "buy_order_count": len(buy_orders),
            "sell_order_count": len(sell_orders),
            "catalyst_theme_candidate_count": int((catalyst_theme_candidate_diagnostics or {}).get("candidate_count") or 0),
            "catalyst_theme_shadow_candidate_count": int((catalyst_theme_candidate_diagnostics or {}).get("shadow_candidate_count") or 0),
            "candidate_pool_shadow_candidate_count": len(shadow_candidates),
            "upstream_shadow_observation_count": int((short_trade_candidate_diagnostics or {}).get("shadow_observation_count") or 0),
            "upstream_shadow_released_count": int((short_trade_candidate_diagnostics or {}).get("released_shadow_count") or 0),
            "watchlist_shadow_released_count": int((watchlist_filter_diagnostics or {}).get("released_shadow_count") or 0),
            "fast_agent_ticker_count": len(high_pool),
            "precise_agent_ticker_count": len(top_20),
            "precise_stage_skipped": self._skip_precise_stage,
            "skipped_precise_ticker_count": skipped_precise_ticker_count,
            "fast_agent_score_threshold": FAST_AGENT_SCORE_THRESHOLD,
            "fast_agent_max_tickers": FAST_AGENT_MAX_TICKERS,
            "precise_agent_max_tickers": PRECISE_AGENT_MAX_TICKERS,
            "watchlist_score_threshold": WATCHLIST_SCORE_THRESHOLD,
        }
        funnel_diagnostics = {
            "counts": counts,
            "filters": {
                "layer_b": layer_b_filter_diagnostics,
                "candidate_pool_shadow": candidate_pool_shadow_summary,
                "watchlist": watchlist_filter_diagnostics,
                "short_trade_candidates": short_trade_candidate_diagnostics,
                "catalyst_theme_candidates": catalyst_theme_candidate_diagnostics,
                "buy_orders": buy_order_filter_diagnostics,
            },
            "sell_orders": sell_order_diagnostics,
            "blocked_buy_tickers": blocked_buy_tickers,
        }

        timing_seconds = {
            "candidate_pool": round(candidate_pool_seconds, 3),
            "market_state": round(market_state_seconds, 3),
            "score_batch": round(score_batch_seconds, 3),
            "fuse_batch": round(fuse_batch_seconds, 3),
            "shadow_score_batch": round(shadow_score_batch_seconds, 3),
            "shadow_fuse_batch": round(shadow_fuse_batch_seconds, 3),
            "fast_agent": round(fast_agent_seconds, 3),
            "precise_agent": round(precise_agent_seconds, 3),
            "estimated_skipped_precise": round(estimated_skipped_precise_seconds, 3),
            "aggregate_layer_c": round(aggregate_layer_c_seconds, 3),
            "build_buy_orders": round(build_buy_orders_seconds, 3),
            "sell_check": round(sell_check_seconds, 3),
            "total_post_market": round(perf_counter() - total_started_at, 3),
        }
        with use_short_trade_target_profile(profile_name=self.short_trade_target_profile_name, overrides=self.short_trade_target_profile_overrides):
            selection_targets, dual_target_summary = build_selection_targets(
                trade_date=trade_date,
                watchlist=watchlist,
                rejected_entries=_attach_historical_prior_to_entries(
                    list((watchlist_filter_diagnostics or {}).get("tickers", []) or []),
                    prior_by_ticker=historical_prior_by_ticker,
                ),
                supplemental_short_trade_entries=_attach_historical_prior_to_entries(
                    [
                        *list((short_trade_candidate_diagnostics or {}).get("tickers", []) or []),
                        *list((short_trade_candidate_diagnostics or {}).get("released_shadow_entries", []) or []),
                        *list((watchlist_filter_diagnostics or {}).get("released_shadow_entries", []) or []),
                        *(
                            list((catalyst_theme_candidate_diagnostics or {}).get("tickers", []) or [])
                            if self.target_mode == "short_trade_only"
                            else []
                        ),
                    ],
                    prior_by_ticker=historical_prior_by_ticker,
                ),
                buy_order_tickers={order.ticker for order in buy_orders},
                target_mode=self.target_mode,
            )
        return generate_execution_plan(
            trade_date=trade_date,
            market_state=market_state,
            watchlist=watchlist,
            logic_scores=logic_scores,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
            portfolio_snapshot=portfolio_snapshot,
            risk_alerts=[],
            risk_metrics={
                "timing_seconds": timing_seconds,
                "counts": counts,
                "funnel_diagnostics": funnel_diagnostics,
                "merge_approved_context": {
                    "tickers": sorted(self.merge_approved_tickers),
                    "score_boost": round(MERGE_APPROVED_SCORE_BOOST, 4),
                    "watchlist_threshold_relaxation": round(MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION, 4),
                    "breakout_signal_uplift": merge_approved_breakout_signal_uplift,
                    "layer_c_alignment_uplift": merge_approved_layer_c_alignment_uplift,
                    "sector_resonance_uplift": merge_approved_sector_resonance_uplift,
                },
            },
            layer_a_count=len(candidates),
            layer_b_count=len(high_pool),
            layer_c_count=len(layer_c_results),
            selection_targets=selection_targets,
            target_mode=self.target_mode,
            dual_target_summary=dual_target_summary,
            short_trade_target_profile_name=self._short_trade_target_profile.name,
            short_trade_target_profile_config=_serialize_short_trade_target_profile(self._short_trade_target_profile),
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
