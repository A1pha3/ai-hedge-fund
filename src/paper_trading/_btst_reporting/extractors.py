from __future__ import annotations
from typing import Any
import pandas as pd

from src.paper_trading.btst_reporting_utils import (
    UPSTREAM_SHADOW_CANDIDATE_SOURCES,
    OPPORTUNITY_POOL_MIN_SCORE_TARGET,
    OPPORTUNITY_POOL_STRONG_SIGNAL_MIN,
    _as_float,
    _round_or_none,
    _source_lane_label,
    _source_lane_display,
)

from src.tools.akshare_api import get_prices_robust
from src.tools.api import get_price_data, prices_to_df


def _resolve_upstream_shadow_candidate_source(
    selection_entry: dict[str, Any],
    explainability_payload: dict[str, Any],
    replay_context: dict[str, Any],
) -> str:
    return str(
        explainability_payload.get("candidate_source")
        or selection_entry.get("candidate_source")
        or replay_context.get("source")
        or ""
    )


def _resolve_upstream_shadow_candidate_reason_codes(
    selection_entry: dict[str, Any],
    supplemental_entry: dict[str, Any],
    replay_context: dict[str, Any],
) -> list[str]:
    return [
        str(reason)
        for reason in (
            list(selection_entry.get("candidate_reason_codes") or [])
            or list(supplemental_entry.get("candidate_reason_codes") or [])
            or list(replay_context.get("candidate_reason_codes") or [])
        )
        if str(reason or "").strip()
    ]


def _build_upstream_shadow_promotion_trigger(decision: str) -> str:
    if decision == "selected":
        return (
            "影子召回样本已晋级为正式 short-trade selected，但仍需盘中确认后才能执行。"
        )
    if decision == "near_miss":
        return "影子召回样本已进入 near-miss 观察层，只能做盘中跟踪，不可预设交易。"
    return "影子召回样本尚未进入可执行层，只有盘中新强度确认后才允许升级。"


def _extract_short_trade_core_metrics(
    metrics_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "breakout_freshness": metrics_payload.get("breakout_freshness"),
        "trend_acceleration": metrics_payload.get("trend_acceleration"),
        "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
        "close_strength": metrics_payload.get("close_strength"),
        "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
    }


def _extract_upstream_shadow_replay_only_entry(
    entry: dict[str, Any],
) -> dict[str, Any] | None:
    candidate_source = str(entry.get("candidate_source") or "")
    if candidate_source not in UPSTREAM_SHADOW_CANDIDATE_SOURCES:
        return None

    metrics_payload = dict(
        entry.get("metrics") or entry.get("short_trade_boundary_metrics") or {}
    )
    candidate_pool_rank = entry.get("candidate_pool_rank")
    return {
        "ticker": entry.get("ticker"),
        "decision": str(entry.get("decision") or "observation"),
        "score_target": entry.get("score_target")
        if entry.get("score_target") is not None
        else metrics_payload.get("candidate_score"),
        "confidence": entry.get("confidence"),
        "preferred_entry_mode": entry.get("preferred_entry_mode")
        or "shadow_observation_only",
        "candidate_source": candidate_source,
        "candidate_pool_lane": str(
            entry.get("candidate_pool_lane") or _source_lane_label(candidate_source)
        ),
        "candidate_pool_lane_display": _source_lane_display(candidate_source),
        "candidate_pool_rank": int(candidate_pool_rank)
        if candidate_pool_rank not in (None, "")
        else None,
        "candidate_pool_avg_amount_share_of_cutoff": _round_or_none(
            entry.get("candidate_pool_avg_amount_share_of_cutoff")
        ),
        "candidate_pool_avg_amount_share_of_min_gate": _round_or_none(
            entry.get("candidate_pool_avg_amount_share_of_min_gate")
        ),
        "upstream_candidate_source": str(
            entry.get("upstream_candidate_source")
            or "candidate_pool_truncated_after_filters"
        ),
        "candidate_reason_codes": [
            str(reason)
            for reason in list(entry.get("candidate_reason_codes") or [])
            if str(reason or "").strip()
        ],
        "top_reasons": list(entry.get("top_reasons") or []),
        "rejection_reasons": list(
            entry.get("rejection_reasons")
            or ([entry.get("filter_reason")] if entry.get("filter_reason") else [])
        ),
        "positive_tags": list(entry.get("positive_tags") or []),
        "gate_status": dict(entry.get("gate_status") or {}),
        "promotion_trigger": str(
            entry.get("promotion_trigger")
            or "影子召回样本当前只保留为补票观察层，不自动升级到正式执行名单。"
        ),
        "metrics": _extract_short_trade_core_metrics(metrics_payload),
    }


RESEARCH_UPSIDE_RADAR_MAX_ENTRIES = 3


def _extract_catalyst_theme_frontier_summary(
    frontier: dict[str, Any],
) -> dict[str, Any]:
    if not frontier:
        return {}
    shadow_candidate_count = int(frontier.get("shadow_candidate_count") or 0)
    baseline_selected_count = int(frontier.get("baseline_selected_count") or 0)
    recommended_variant = frontier.get("recommended_variant") or {}
    promoted_shadow_count = int(recommended_variant.get("promoted_shadow_count") or 0)
    top_promoted_rows = list(recommended_variant.get("top_promoted_rows") or [])

    return {
        "status": frontier.get("status"),
        "shadow_candidate_count": shadow_candidate_count,
        "baseline_selected_count": baseline_selected_count,
        "recommended_variant_name": recommended_variant.get("variant_name"),
        "recommended_promoted_shadow_count": promoted_shadow_count,
        "recommended_relaxation_cost": recommended_variant.get(
            "threshold_relaxation_cost"
        ),
        "recommended_thresholds": dict(recommended_variant.get("thresholds") or {}),
        "recommended_promoted_tickers": [
            str(row.get("ticker") or "")
            for row in top_promoted_rows
            if row.get("ticker")
        ][:3],
        "recommendation": frontier.get("recommendation"),
    }


def _normalize_price_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    if not isinstance(normalized.index, pd.DatetimeIndex):
        normalized.index = pd.to_datetime(normalized.index)
    normalized = normalized.sort_index()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    return normalized


def _extract_next_day_outcome(
    ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]
) -> dict[str, Any]:
    cache_key = (ticker, trade_date)
    frame = price_cache.get(cache_key)
    if frame is None:
        end_date = (pd.Timestamp(trade_date) + pd.Timedelta(days=10)).strftime(
            "%Y-%m-%d"
        )
        try:
            frame = _normalize_price_frame(
                prices_to_df(
                    get_prices_robust(
                        ticker, trade_date, end_date, use_mock_on_fail=False
                    )
                )
            )
        except Exception:
            try:
                frame = _normalize_price_frame(
                    get_price_data(ticker, trade_date, end_date)
                )
            except Exception:
                frame = pd.DataFrame()
        price_cache[cache_key] = frame
    if frame.empty:
        return {"data_status": "missing_price_frame"}

    trade_ts = pd.Timestamp(trade_date)
    same_day = frame.loc[frame.index.normalize() == trade_ts.normalize()]
    next_day = frame.loc[frame.index.normalize() > trade_ts.normalize()]
    if same_day.empty:
        return {"data_status": "missing_trade_day_bar"}
    if next_day.empty:
        return {"data_status": "missing_next_trade_day_bar"}

    trade_row = same_day.iloc[0]
    next_row = next_day.iloc[0]
    trade_close = _as_float(trade_row.get("close"))
    next_open = _as_float(next_row.get("open"))
    next_high = _as_float(next_row.get("high"))
    next_close = _as_float(next_row.get("close"))
    if trade_close <= 0 or next_open <= 0 or next_high <= 0 or next_close <= 0:
        return {"data_status": "incomplete_price_bar"}

    return {
        "data_status": "ok",
        "next_trade_date": next_day.index[0].strftime("%Y-%m-%d"),
        "trade_close": round(trade_close, 4),
        "next_open": round(next_open, 4),
        "next_high": round(next_high, 4),
        "next_close": round(next_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 4),
        "next_high_return": round((next_high / trade_close) - 1.0, 4),
        "next_close_return": round((next_close / trade_close) - 1.0, 4),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 4),
    }


def _extract_short_trade_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    short_trade_entry = selection_entry.get("short_trade") or {}
    decision = short_trade_entry.get("decision")
    if decision not in {"selected", "near_miss"}:
        return None

    metrics_payload = short_trade_entry.get("metrics_payload") or {}
    explainability_payload = short_trade_entry.get("explainability_payload") or {}
    candidate_reason_codes = [
        str(reason)
        for reason in list(selection_entry.get("candidate_reason_codes") or [])
        if str(reason or "").strip()
    ]
    catalyst_relief = dict(
        explainability_payload.get("upstream_shadow_catalyst_relief") or {}
    )
    short_trade_catalyst_relief_reason = (
        str(catalyst_relief.get("reason") or "")
        if catalyst_relief
        and (
            bool(catalyst_relief.get("applied")) or bool(catalyst_relief.get("enabled"))
        )
        else None
    )

    return {
        "ticker": selection_entry.get("ticker"),
        "decision": decision,
        "reporting_decision": decision,
        "score_target": short_trade_entry.get("score_target"),
        "confidence": short_trade_entry.get("confidence"),
        "rank_hint": short_trade_entry.get("rank_hint"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "positive_tags": list(short_trade_entry.get("positive_tags") or []),
        "top_reasons": list(short_trade_entry.get("top_reasons") or []),
        "candidate_source": explainability_payload.get("candidate_source")
        or selection_entry.get("candidate_source"),
        "candidate_reason_codes": candidate_reason_codes,
        "short_trade_catalyst_relief_reason": short_trade_catalyst_relief_reason,
        "gate_status": dict(short_trade_entry.get("gate_status") or {}),
        "metrics": _extract_short_trade_core_metrics(metrics_payload),
        "historical_prior": dict(
            short_trade_entry.get("historical_prior")
            or explainability_payload.get("historical_prior")
            or {}
        ),
    }


def _is_short_trade_opportunity_candidate(
    short_trade_entry: dict[str, Any], gate_status: dict[str, Any]
) -> bool:
    if short_trade_entry.get("decision") != "opportunity_pool":
        return False
    return bool(gate_status.get("opportunity_pool_eligible") or False)


def _count_short_trade_strong_signals(metrics_payload: dict[str, Any]) -> int:
    count = 0
    if (
        _as_float(metrics_payload.get("breakout_freshness"))
        >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN
    ):
        count += 1
    if (
        _as_float(metrics_payload.get("trend_acceleration"))
        >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN
    ):
        count += 1
    if (
        _as_float(metrics_payload.get("catalyst_freshness"))
        >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN
    ):
        count += 1
    if (
        _as_float(metrics_payload.get("close_strength"))
        >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN
    ):
        count += 1
    return count


def _extract_short_trade_catalyst_relief_reason(
    explainability_payload: dict[str, Any],
) -> str | None:
    catalyst_relief = dict(
        explainability_payload.get("upstream_shadow_catalyst_relief") or {}
    )
    return (
        str(catalyst_relief.get("reason") or "")
        if catalyst_relief
        and (
            bool(catalyst_relief.get("applied")) or bool(catalyst_relief.get("enabled"))
        )
        else None
    )


def _extract_short_trade_opportunity_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    if (selection_entry.get("research") or {}).get("decision") == "selected":
        return None

    short_trade_entry = selection_entry.get("short_trade") or {}
    gate_status = dict(short_trade_entry.get("gate_status") or {})
    if not _is_short_trade_opportunity_candidate(short_trade_entry, gate_status):
        return None

    metrics_payload = dict(short_trade_entry.get("metrics_payload") or {})
    explainability_payload = dict(short_trade_entry.get("explainability_payload") or {})
    score_target = _as_float(short_trade_entry.get("score_target"))
    if score_target < OPPORTUNITY_POOL_MIN_SCORE_TARGET:
        return None

    positive_tags = list(short_trade_entry.get("positive_tags") or [])
    strong_signal_count = _count_short_trade_strong_signals(metrics_payload)
    if strong_signal_count <= 0 and not positive_tags:
        return None

    thresholds = dict(metrics_payload.get("thresholds") or {})
    near_miss_threshold = _as_float(thresholds.get("near_miss_threshold"))
    score_gap_to_near_miss = (
        round(max(0.0, near_miss_threshold - score_target), 4)
        if near_miss_threshold > 0
        else None
    )
    candidate_reason_codes = [
        str(reason)
        for reason in list(selection_entry.get("candidate_reason_codes") or [])
        if str(reason or "").strip()
    ]
    short_trade_catalyst_relief_reason = _extract_short_trade_catalyst_relief_reason(
        explainability_payload
    )

    return {
        "ticker": selection_entry.get("ticker"),
        "decision": "opportunity_pool",
        "reporting_decision": "opportunity_pool",
        "score_target": score_target,
        "confidence": short_trade_entry.get("confidence"),
        "score_gap_to_near_miss": score_gap_to_near_miss,
        "strong_signal_count": strong_signal_count,
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode")
        or "only_on_strong_confirmation",
        "positive_tags": positive_tags,
        "top_reasons": list(short_trade_entry.get("top_reasons") or []),
        "candidate_source": explainability_payload.get("candidate_source")
        or selection_entry.get("candidate_source"),
        "candidate_reason_codes": candidate_reason_codes,
        "short_trade_catalyst_relief_reason": short_trade_catalyst_relief_reason,
        "gate_status": gate_status,
        "metrics": _extract_short_trade_core_metrics(metrics_payload),
        "historical_prior": dict(
            short_trade_entry.get("historical_prior")
            or explainability_payload.get("historical_prior")
            or {}
        ),
        "promotion_trigger": "只有盘中新增强度确认时，才允许从机会池升级。",
    }


def _extract_research_upside_radar_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    research_entry = selection_entry.get("research") or {}
    if research_entry.get("decision") != "selected":
        return None

    return {
        "ticker": selection_entry.get("ticker"),
        "score_target": research_entry.get("score_target"),
        "confidence": research_entry.get("confidence"),
        "top_reasons": list(research_entry.get("top_reasons") or []),
        "catalyst_summary": research_entry.get("catalyst_summary"),
        "upside_potential_pct": research_entry.get("upside_potential_pct"),
        "risk_profile": research_entry.get("risk_profile"),
        "timeframe": research_entry.get("timeframe"),
    }


def _extract_catalyst_theme_entry(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if not candidate or not candidate.get("theme_name"):
        return None

    return {
        "theme_name": candidate.get("theme_name"),
        "theme_category": candidate.get("theme_category"),
        "theme_strength_score": candidate.get("theme_strength_score"),
        "catalyst_trigger": candidate.get("catalyst_trigger"),
        "related_tickers": [
            str(t) for t in list(candidate.get("related_tickers") or []) if t
        ],
        "top_ticker": candidate.get("top_ticker"),
        "trend_duration_days": candidate.get("trend_duration_days"),
        "recent_catalyst_count": candidate.get("recent_catalyst_count"),
        "is_new_theme": bool(candidate.get("is_new_theme")),
    }


def _extract_catalyst_theme_shadow_entry(
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    entry = _extract_catalyst_theme_entry(candidate)
    if not entry:
        return None

    entry["shadow_status"] = candidate.get("shadow_status") or "observation"
    entry["promotion_priority"] = candidate.get("promotion_priority") or 0
    entry["related_short_trade_tickers"] = [
        str(t) for t in list(candidate.get("related_short_trade_tickers") or []) if t
    ]
    return entry


def _extract_excluded_research_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    research_entry = selection_entry.get("research") or {}
    if research_entry.get("decision") != "excluded":
        return None

    return {
        "ticker": selection_entry.get("ticker"),
        "exclusion_reason": research_entry.get("exclusion_reason"),
        "exclusion_category": research_entry.get("exclusion_category"),
        "related_theme": research_entry.get("related_theme"),
        "risk_flag": research_entry.get("risk_flag"),
    }
