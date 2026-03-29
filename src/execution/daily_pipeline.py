"""日度执行流水线。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from inspect import signature
from time import perf_counter
from typing import Callable, Optional
import os

from src.execution.crisis_handler import evaluate_crisis_response
from src.execution.layer_c_aggregator import aggregate_layer_c_results
from src.execution.models import ExecutionPlan, LayerCResult
from src.execution.plan_generator import generate_execution_plan
from src.execution.signal_decay import apply_signal_decay
from src.execution.t1_confirmation import confirm_buy_signal
from src.portfolio.exit_manager import check_exit_signal
from src.portfolio.models import HoldingState
from src.portfolio.position_calculator import STANDARD_EXECUTION_SCORE, calculate_position, enforce_daily_trade_limit
from src.screening.candidate_pool import build_candidate_pool
from src.screening.models import CandidateStock
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch
from src.targets.models import DualTargetSummary, TargetMode
from src.targets.profiles import build_short_trade_target_profile, use_short_trade_target_profile
from src.targets.router import build_selection_targets, summarize_selection_targets
from src.targets.short_trade_target import build_short_trade_target_snapshot_from_entry, evaluate_short_trade_rejected_target
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


FAST_AGENT_SCORE_THRESHOLD = _get_env_float("DAILY_PIPELINE_FAST_SCORE_THRESHOLD", 0.38)
FAST_AGENT_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_FAST_POOL_MAX_SIZE", 12)
PRECISE_AGENT_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_PRECISE_POOL_MAX_SIZE", 6)
WATCHLIST_SCORE_THRESHOLD = _get_env_float("DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD", 0.20)
EXIT_REENTRY_CONFIRM_SCORE_MIN = _get_env_float("PIPELINE_EXIT_REENTRY_CONFIRM_SCORE_MIN", STANDARD_EXECUTION_SCORE)
SHORT_TRADE_BOUNDARY_SCORE_BUFFER = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_SCORE_BUFFER", 0.08)
SHORT_TRADE_BOUNDARY_MAX_TICKERS = _get_env_int("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_MAX_TICKERS", 6)
SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN", 0.24)
SHORT_TRADE_BOUNDARY_BREAKOUT_MIN = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_BREAKOUT_MIN", 0.18)
SHORT_TRADE_BOUNDARY_TREND_MIN = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_TREND_MIN", 0.22)
SHORT_TRADE_BOUNDARY_VOLUME_MIN = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_VOLUME_MIN", 0.15)
SHORT_TRADE_BOUNDARY_CATALYST_MIN = _get_env_float("DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CATALYST_MIN", 0.12)


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


def _build_watchlist_filter_diagnostics(layer_c_results: list[LayerCResult], watchlist: list[LayerCResult]) -> dict:
    selected_tickers = {item.ticker for item in watchlist}
    entries: list[dict] = []
    selected_entries: list[dict] = []
    for item in layer_c_results:
        payload = {
            "ticker": item.ticker,
            "score_b": round(item.score_b, 4),
            "score_c": round(item.score_c, 4),
            "score_final": round(item.score_final, 4),
            "quality_score": round(item.quality_score, 4),
            "decision": item.decision,
            "bc_conflict": item.bc_conflict,
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
    summary = _build_filter_summary(entries)
    summary["selected_tickers"] = [item.ticker for item in watchlist]
    summary["selected_entries"] = selected_entries
    return summary


def _build_short_trade_boundary_entry(*, item, reason: str, rank: int) -> dict:
    return {
        "ticker": item.ticker,
        "score_b": round(float(item.score_b), 4),
        "score_c": 0.0,
        "score_final": round(float(item.score_b), 4),
        "quality_score": 0.5,
        "decision": str(item.decision or "neutral"),
        "reason": reason,
        "reasons": [reason, "short_trade_prequalified"],
        "candidate_source": "short_trade_boundary",
        "upstream_candidate_source": "layer_b_boundary",
        "candidate_reason_codes": [reason, "short_trade_prequalified"],
        "strategy_signals": {
            name: signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {})
            for name, signal in dict(item.strategy_signals or {}).items()
        },
        "agent_contribution_summary": {},
        "rank": rank,
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


def _qualifies_short_trade_boundary_candidate(*, trade_date: str, entry: dict) -> tuple[bool, str, dict]:
    snapshot = build_short_trade_target_snapshot_from_entry(trade_date=trade_date, entry=entry)
    gate_status = dict(snapshot.get("gate_status") or {})
    blockers = {str(blocker) for blocker in list(snapshot.get("blockers") or []) if str(blocker or "").strip()}
    metrics_payload = {
        "breakout_freshness": round(float(snapshot.get("breakout_freshness", 0.0) or 0.0), 4),
        "trend_acceleration": round(float(snapshot.get("trend_acceleration", 0.0) or 0.0), 4),
        "volume_expansion_quality": round(float(snapshot.get("volume_expansion_quality", 0.0) or 0.0), 4),
        "catalyst_freshness": round(float(snapshot.get("catalyst_freshness", 0.0) or 0.0), 4),
        "close_strength": round(float(snapshot.get("close_strength", 0.0) or 0.0), 4),
        "candidate_score": _compute_short_trade_boundary_candidate_score(snapshot),
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


def _build_short_trade_candidate_diagnostics(fused: list, high_pool: list, trade_date: str) -> dict:
    selected_tickers = {item.ticker for item in high_pool}
    entries: list[dict] = []
    reason_counts: dict[str, int] = {}
    filtered_reason_counts: dict[str, int] = {}
    ranked_candidates: list[tuple[float, float, dict]] = []
    upstream_candidates = sorted([item for item in fused if item.ticker not in selected_tickers], key=lambda current: current.score_b, reverse=True)

    for item in upstream_candidates:
        reason = "short_trade_candidate_score_ranked"
        candidate_entry = _build_short_trade_boundary_entry(item=item, reason=reason, rank=0)
        qualified, filter_reason, metrics_payload = _qualifies_short_trade_boundary_candidate(trade_date=trade_date, entry=candidate_entry)
        if not qualified:
            filtered_reason_counts[filter_reason] = filtered_reason_counts.get(filter_reason, 0) + 1
            continue

        ranked_candidates.append((float(metrics_payload.get("candidate_score", 0.0) or 0.0), float(item.score_b), {**candidate_entry, "short_trade_boundary_metrics": metrics_payload}))

    ranked_candidates.sort(key=lambda row: (row[0], row[1], str(row[2].get("ticker") or "")), reverse=True)
    for rank, (_, _, entry) in enumerate(ranked_candidates[:SHORT_TRADE_BOUNDARY_MAX_TICKERS], start=1):
        entry["rank"] = rank
        reason = str(entry.get("reason") or "short_trade_candidate_score_ranked")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        entries.append(entry)

    return {
        "upstream_candidate_count": len(upstream_candidates),
        "candidate_count": len(entries),
        "reason_counts": reason_counts,
        "filtered_reason_counts": filtered_reason_counts,
        "prefilter_thresholds": {
            "candidate_score_min": round(SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN, 4),
            "breakout_freshness_min": round(SHORT_TRADE_BOUNDARY_BREAKOUT_MIN, 4),
            "trend_acceleration_min": round(SHORT_TRADE_BOUNDARY_TREND_MIN, 4),
            "volume_expansion_quality_min": round(SHORT_TRADE_BOUNDARY_VOLUME_MIN, 4),
            "catalyst_freshness_min": round(SHORT_TRADE_BOUNDARY_CATALYST_MIN, 4),
        },
        "selected_tickers": [entry["ticker"] for entry in entries],
        "score_buffer": round(SHORT_TRADE_BOUNDARY_SCORE_BUFFER, 4),
        "minimum_score_b": round(FAST_AGENT_SCORE_THRESHOLD - SHORT_TRADE_BOUNDARY_SCORE_BUFFER, 4),
        "max_candidates": SHORT_TRADE_BOUNDARY_MAX_TICKERS,
        "tickers": entries,
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


def _build_reentry_filter_payload(ticker: str, score_final: float, cooldown_payload: dict, trade_date: str) -> dict | None:
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
    required_score = float(cooldown_payload.get("reentry_min_score", EXIT_REENTRY_CONFIRM_SCORE_MIN))
    if reentry_review_until and trade_date and trade_date <= reentry_review_until and score_final < required_score:
        return {
            "ticker": normalized_ticker,
            "reason": "blocked_by_reentry_score_confirmation",
            "score_final": round(score_final, 4),
            "required_score": round(required_score, 4),
            "reentry_review_until": reentry_review_until,
            "trigger_reason": trigger_reason,
            "exit_trade_date": exit_trade_date,
        }

    return None


def _build_reentry_filter_entry(item: LayerCResult, cooldown_payload: dict, trade_date: str) -> dict | None:
    return _build_reentry_filter_payload(item.ticker, item.score_final, cooldown_payload, trade_date)


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
    rejected_entries = list((((plan.risk_metrics or {}).get("funnel_diagnostics", {}) or {}).get("filters", {}) or {}).get("watchlist", {}).get("tickers", []) or [])
    buy_order_tickers = {order.ticker for order in list(plan.buy_orders or [])}
    if not selection_targets and (plan.watchlist or rejected_entries):
        with use_short_trade_target_profile(profile_name=short_trade_target_profile_name, overrides=short_trade_target_profile_overrides):
            selection_targets, summary = build_selection_targets(
                trade_date=plan.date,
                watchlist=plan.watchlist,
                rejected_entries=rejected_entries,
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
    for item in watchlist:
        cooldown_payload = blocked_buy_tickers.get(item.ticker)
        if cooldown_payload is not None:
            reentry_filter_entry = _build_reentry_filter_entry(item, cooldown_payload, trade_date)
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


@dataclass
class DailyPipeline:
    agent_runner: AgentRunner | None = None
    exit_checker: ExitChecker = _default_exit_checker
    base_model_name: str = ""
    base_model_provider: str = ""
    frozen_post_market_plans: dict[str, ExecutionPlan] | None = None
    frozen_plan_source: str | None = None
    target_mode: TargetMode = "research_only"
    short_trade_target_profile_name: str = "default"
    short_trade_target_profile_overrides: dict[str, object] = field(default_factory=dict)
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

    def _run_agents_with_base_model(self, tickers: list[str], trade_date: str, model_tier: str) -> dict[str, dict[str, dict]]:
        from src.main import run_hedge_fund

        start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=365)).strftime("%Y-%m-%d")
        end_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
        model_name, model_provider = _resolve_pipeline_model_config(model_tier, self.base_model_name, self.base_model_provider)
        result = run_hedge_fund(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            portfolio={"cash": 1_000_000, "positions": {}, "margin_requirement": 0.0, "margin_used": 0.0, "realized_gains": {}},
            show_reasoning=False,
            model_name=model_name,
            model_provider=model_provider,
            llm_observability={
                "trade_date": trade_date,
                "pipeline_stage": "daily_pipeline_post_market",
                "model_tier": model_tier,
            },
        )
        execution_plan_provenance = result.get("execution_plan_provenance")
        if isinstance(execution_plan_provenance, dict):
            self.execution_plan_provenance_log.append(
                {
                    "trade_date": trade_date,
                    "model_tier": model_tier,
                    "tickers": list(tickers),
                    "execution_plan_provenance": execution_plan_provenance,
                }
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
        retained_orders = []
        filtered_entries: list[dict] = []
        for order in plan.buy_orders:
            cooldown_payload = blocked_buy_tickers.get(order.ticker)
            if cooldown_payload is None:
                retained_orders.append(order)
                continue

            watch_item = watchlist_by_ticker.get(order.ticker)
            score_final = float(watch_item.score_final if watch_item is not None else order.score_final)
            filter_entry = _build_reentry_filter_payload(order.ticker, score_final, cooldown_payload, trade_date)
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
        candidates = build_candidate_pool(trade_date)
        candidate_pool_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        market_state = detect_market_state(trade_date)
        market_state_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        scored = score_batch(candidates, trade_date)
        score_batch_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        fused = fuse_batch(scored, market_state, trade_date)
        fuse_batch_seconds = perf_counter() - stage_started_at
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
        aggregate_layer_c_seconds = perf_counter() - stage_started_at
        logic_scores = _build_logic_score_map(layer_c_results)
        watchlist = [item for item in layer_c_results if item.score_final >= WATCHLIST_SCORE_THRESHOLD and item.decision != "avoid"]
        layer_b_filter_diagnostics = _build_layer_b_filter_diagnostics(fused, high_pool)
        watchlist_filter_diagnostics = _build_watchlist_filter_diagnostics(layer_c_results, watchlist)
        short_trade_candidate_diagnostics = _build_short_trade_candidate_diagnostics(fused, high_pool, trade_date)

        candidate_by_ticker = {candidate.ticker: candidate for candidate in candidates}
        price_map = build_watchlist_price_map(trade_date, [item.ticker for item in watchlist])

        stage_started_at = perf_counter()
        buy_orders, buy_order_filter_diagnostics = self._build_buy_orders_with_diagnostics(
            watchlist,
            portfolio_snapshot,
            trade_date=trade_date,
            candidate_by_ticker=candidate_by_ticker,
            price_map=price_map,
            blocked_buy_tickers=blocked_buy_tickers,
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
                "watchlist": watchlist_filter_diagnostics,
                "short_trade_candidates": short_trade_candidate_diagnostics,
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
                rejected_entries=list((watchlist_filter_diagnostics or {}).get("tickers", []) or []),
                supplemental_short_trade_entries=list((short_trade_candidate_diagnostics or {}).get("tickers", []) or []),
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
    ) -> tuple[list, dict]:
        return build_buy_orders_with_diagnostics(
            watchlist,
            portfolio_snapshot,
            trade_date=trade_date,
            candidate_by_ticker=candidate_by_ticker,
            price_map=price_map,
            blocked_buy_tickers=blocked_buy_tickers,
        )
