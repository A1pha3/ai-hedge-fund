from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from src.tools.tushare_api import _cached_tushare_dataframe_call, _get_pro

# ---------------------------------------------------------------------------
# Configuration constants (shared across BTST reporting modules)
# ---------------------------------------------------------------------------
OPPORTUNITY_POOL_MIN_SCORE_TARGET = 0.30
OPPORTUNITY_POOL_STRONG_SIGNAL_MIN = 0.65
OPPORTUNITY_POOL_MAX_ENTRIES = 3
OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS = 24
OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD = 0.02
OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES = 2
WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT = 3
WEAK_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT = 2
WEAK_BALANCED_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT = 4
WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE = 0.5
WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE = 0.2
MIXED_BOUNDARY_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT = 6
MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE = 0.5
MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE = 0.5
MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_SCORE_TARGET = 0.40
MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_BREAKOUT_FRESHNESS = 0.50
LOW_SCORE_NO_HISTORY_UPSTREAM_MAX_SCORE_TARGET = 0.34
WATCH_CANDIDATE_HISTORICAL_SCORE_BUCKET_SIZE = 0.05
RESEARCH_UPSIDE_RADAR_MAX_ENTRIES = 3
CATALYST_THEME_MAX_ENTRIES = 5
CATALYST_THEME_SHADOW_MAX_ENTRIES = 5
CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES = 3
RISKY_OBSERVER_EXECUTION_QUALITY_LABELS = {"gap_chase_risk", "intraday_only"}
UPSTREAM_SHADOW_CANDIDATE_SOURCES = {
    "upstream_liquidity_corridor_shadow": "layer_a_liquidity_corridor",
    "post_gate_liquidity_competition_shadow": "post_gate_liquidity_competition",
}


# ---------------------------------------------------------------------------
# Decision / source helpers
# ---------------------------------------------------------------------------
def _shadow_decision_rank(decision: str | None) -> int:
    return {
        "selected": 0,
        "near_miss": 1,
        "observation": 2,
        "blocked": 3,
        "rejected": 4,
    }.get(str(decision or "rejected"), 5)


def _source_lane_label(candidate_source: str | None) -> str:
    normalized = str(candidate_source or "")
    return UPSTREAM_SHADOW_CANDIDATE_SOURCES.get(normalized, normalized or "unknown")


def _source_lane_display(candidate_source: str | None) -> str:
    return {
        "upstream_liquidity_corridor_shadow": "layer_a_liquidity_corridor",
        "post_gate_liquidity_competition_shadow": "post_gate_liquidity_competition",
    }.get(str(candidate_source or ""), str(candidate_source or "unknown"))


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sync_text_artifact_alias(source_path: str | Path, alias_path: str | Path) -> str:
    resolved_source = Path(source_path).expanduser().resolve()
    resolved_alias = Path(alias_path).expanduser().resolve()
    resolved_alias.write_text(resolved_source.read_text(encoding="utf-8"), encoding="utf-8")
    return str(resolved_alias)


# ---------------------------------------------------------------------------
# Path / replay helpers
# ---------------------------------------------------------------------------
def _resolve_replay_input_path(snapshot_path: str | Path) -> Path:
    return Path(snapshot_path).expanduser().resolve().with_name("selection_target_replay_input.json")


def _load_selection_replay_input(snapshot_path: str | Path) -> dict[str, Any]:
    replay_input_path = _resolve_replay_input_path(snapshot_path)
    if not replay_input_path.exists():
        return {}
    return _load_json(replay_input_path)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def _normalize_trade_date(value: str | None) -> str | None:
    if not value:
        return None
    if "-" in value:
        return value
    if len(value) == 8:
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def _compact_trade_date(value: str | None) -> str | None:
    normalized = _normalize_trade_date(value)
    return normalized.replace("-", "") if normalized else None


def _fallback_next_weekday(trade_date: str | None) -> str | None:
    normalized = _normalize_trade_date(trade_date)
    if not normalized:
        return None
    cursor = datetime.strptime(normalized, "%Y-%m-%d") + timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor.strftime("%Y-%m-%d")


def infer_next_trade_date(trade_date: str | None, lookahead_days: int = 14) -> str | None:
    normalized = _normalize_trade_date(trade_date)
    if not normalized:
        return None

    pro = _get_pro()
    if pro is None:
        return _fallback_next_weekday(normalized)

    start_date = (datetime.strptime(normalized, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y%m%d")
    end_date = (datetime.strptime(normalized, "%Y-%m-%d") + timedelta(days=lookahead_days)).strftime("%Y%m%d")

    try:
        df = _cached_tushare_dataframe_call(
            pro,
            "trade_cal",
            exchange="",
            start_date=start_date,
            end_date=end_date,
            is_open=1,
            fields="cal_date,is_open",
        )
    except Exception:
        df = None

    if df is not None and not df.empty:
        candidate_dates = sorted(_normalize_trade_date(str(value)) for value in df["cal_date"].tolist())
        if candidate_dates:
            return candidate_dates[0]
    return _fallback_next_weekday(normalized)


def _resolve_followup_trade_dates(
    trade_date: str | None,
    next_trade_date: str | None,
    brief_json_path: str | Path,
    card_json_path: str | Path,
) -> tuple[str | None, str | None]:
    normalized_trade_date = _normalize_trade_date(trade_date)
    normalized_next_trade_date = _normalize_trade_date(next_trade_date)
    if normalized_trade_date and normalized_next_trade_date:
        return normalized_trade_date, normalized_next_trade_date

    brief_payload = _load_json(brief_json_path)
    card_payload = _load_json(card_json_path)
    return (
        normalized_trade_date or _normalize_trade_date(brief_payload.get("trade_date") or card_payload.get("trade_date")),
        normalized_next_trade_date or _normalize_trade_date(brief_payload.get("next_trade_date") or card_payload.get("next_trade_date")),
    )


# ---------------------------------------------------------------------------
# Numeric / formatting helpers
# ---------------------------------------------------------------------------
def _format_float(value: Any, digits: int = 4) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return "n/a"


def _as_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _round_or_none(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 4)


def _score_bucket_label(score_target: Any, bucket_size: float = WATCH_CANDIDATE_HISTORICAL_SCORE_BUCKET_SIZE) -> str:
    if not isinstance(score_target, (int, float)):
        return "unknown"
    score_value = max(0.0, float(score_target))
    lower = round(int(score_value / bucket_size) * bucket_size, 2)
    upper = round(lower + bucket_size, 2)
    return f"{lower:.2f}-{upper:.2f}"


def _catalyst_bucket_label(metrics: dict[str, Any] | None) -> str:
    catalyst_freshness = _as_float((metrics or {}).get("catalyst_freshness"))
    if catalyst_freshness >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN:
        return "strong"
    if catalyst_freshness >= 0.45:
        return "medium"
    if catalyst_freshness > 0:
        return "weak"
    return "none"


# ---------------------------------------------------------------------------
# Report directory helpers
# ---------------------------------------------------------------------------
def _looks_like_paper_trading_report_dir(path: Path) -> bool:
    return path.is_dir() and path.name.startswith("paper_trading") and (path / "session_summary.json").exists() and (path / "selection_artifacts").exists()


def _iter_selection_snapshot_paths(report_dir: Path) -> list[Path]:
    selection_artifacts_dir = report_dir / "selection_artifacts"
    if not selection_artifacts_dir.exists():
        return []
    return [
        snapshot_path
        for snapshot_path in sorted(selection_artifacts_dir.glob("*/selection_snapshot.json"))
        if snapshot_path.is_file()
    ]


# ---------------------------------------------------------------------------
# Monitoring / priority helpers
# ---------------------------------------------------------------------------
def _monitor_priority_rank(priority: str | None) -> int:
    return {
        "high": 0,
        "medium": 1,
        "low": 2,
        "unscored": 3,
    }.get(str(priority or "unscored"), 3)


# ---------------------------------------------------------------------------
# Short trade metric extraction helpers
# ---------------------------------------------------------------------------
def _extract_short_trade_core_metrics(metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "breakout_freshness": metrics_payload.get("breakout_freshness"),
        "trend_acceleration": metrics_payload.get("trend_acceleration"),
        "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
        "close_strength": metrics_payload.get("close_strength"),
        "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
    }


def _build_opportunity_pool_promotion_trigger(metrics_payload: dict[str, Any]) -> str:
    breakout_freshness = _as_float(metrics_payload.get("breakout_freshness"))
    trend_acceleration = _as_float(metrics_payload.get("trend_acceleration"))
    close_strength = _as_float(metrics_payload.get("close_strength"))
    catalyst_freshness = _as_float(metrics_payload.get("catalyst_freshness"))

    if breakout_freshness >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN and trend_acceleration >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN:
        return "若盘中 breakout 与 trend 强度继续抬升，可升级为观察票。"
    if catalyst_freshness >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN:
        return "若催化延续并出现量价确认，可升级为观察票。"
    if close_strength >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN:
        return "若开盘后 close-strength 类信号延续，可升级为观察票。"
    return "只有盘中新增强度确认时，才允许从机会池升级。"


# ---------------------------------------------------------------------------
# Execution quality result builders
# ---------------------------------------------------------------------------
def _build_execution_quality_unknown_result() -> dict[str, str]:
    return {
        "execution_quality_label": "unknown",
        "execution_priority": "unscored",
        "entry_timing_bias": "unknown",
        "execution_note": "历史执行样本不足，仍需以盘中确认为准。",
    }


def _build_execution_quality_zero_follow_through_result() -> dict[str, str]:
    return {
        "execution_quality_label": "zero_follow_through",
        "execution_priority": "low",
        "entry_timing_bias": "avoid_without_new_strength",
        "execution_note": "历史同层样本几乎不给盘中空间，也没有收盘正收益，除非出现新的强确认，否则不应进入高优先级执行面。",
    }


def _build_execution_quality_gap_chase_risk_result() -> dict[str, str]:
    return {
        "execution_quality_label": "gap_chase_risk",
        "execution_priority": "low",
        "entry_timing_bias": "avoid_open_chase",
        "execution_note": "历史上更像高开后回落，避免开盘直接追价。",
    }


def _build_execution_quality_close_continuation_result() -> dict[str, str]:
    return {
        "execution_quality_label": "close_continuation",
        "execution_priority": "high",
        "entry_timing_bias": "confirm_then_hold",
        "execution_note": "历史上更偏向次日收盘延续，确认后可保留 follow-through 预期。",
    }


def _build_execution_quality_intraday_only_result() -> dict[str, str]:
    return {
        "execution_quality_label": "intraday_only",
        "execution_priority": "medium",
        "entry_timing_bias": "confirm_then_reduce",
        "execution_note": "历史上更多是盘中给空间、收盘回落，更适合作为 intraday 机会而不是隔夜延续。",
    }


def _build_execution_quality_balanced_confirmation_result() -> dict[str, str]:
    return {
        "execution_quality_label": "balanced_confirmation",
        "execution_priority": "medium",
        "entry_timing_bias": "confirm_then_review",
        "execution_note": "历史表现相对均衡，仍应坚持盘中确认后再决定是否持有。",
    }


# ---------------------------------------------------------------------------
# Sorting / ranking helpers
# ---------------------------------------------------------------------------
def _summary_value(summary: dict[str, Any], key: str, fallback: int) -> int:
    value = summary.get(key)
    return fallback if value is None else value


def _execution_priority_rank(priority: str | None) -> int:
    return {
        "high": 0,
        "medium": 1,
        "low": 2,
        "unscored": 3,
    }.get(str(priority or "unscored"), 3)


def _historical_execution_entry_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _execution_priority_rank((entry.get("historical_prior") or {}).get("execution_priority")),
        _monitor_priority_rank((entry.get("historical_prior") or {}).get("monitor_priority")),
        -(entry.get("score_target") or 0.0),
        -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
        entry.get("ticker") or "",
    )


def _research_historical_entry_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _execution_priority_rank((entry.get("historical_prior") or {}).get("execution_priority")),
        _monitor_priority_rank((entry.get("historical_prior") or {}).get("monitor_priority")),
        -(entry.get("research_score_target") or 0.0),
        -(entry.get("score_target") or 0.0),
        entry.get("ticker") or "",
    )


def _entry_mode_action_guidance(preferred_entry_mode: str | None, *, default_action: str) -> tuple[str, str]:
    if preferred_entry_mode == "intraday_confirmation_only":
        return "confirm_then_reduce", "只做盘中确认后的 intraday 机会，不把默认隔夜持有当成执行目标。"
    if preferred_entry_mode == "avoid_open_chase_confirmation":
        return "avoid_open_chase", "避免开盘直接追价，等待回踩或二次确认后再决定是否参与。"
    if preferred_entry_mode == "confirm_then_hold_breakout":
        return "confirm_then_hold", "先等盘中 continuation 确认，再决定是否入场；若确认质量足够，允许把 follow-through 持有到收盘而不是机械快进快出。"
    if preferred_entry_mode == "strong_reconfirmation_only":
        return "reconfirm_only", "历史兑现极弱，只有出现新的强确认时才允许重新评估。"
    return "standard_confirmation", default_action


def _opportunity_pool_execution_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    historical_prior = dict(entry.get("historical_prior") or {})
    execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")
    execution_quality_rank = {
        "close_continuation": 0,
        "balanced_confirmation": 1,
        "gap_chase_risk": 2,
        "intraday_only": 3,
        "unknown": 4,
        "zero_follow_through": 5,
    }.get(execution_quality_label, 4)
    next_close_positive_rate = _as_float(historical_prior.get("next_close_positive_rate"))
    next_high_hit_rate = _as_float(historical_prior.get("next_high_hit_rate_at_threshold"))
    return (
        execution_quality_rank,
        -next_close_positive_rate,
        -next_high_hit_rate,
        entry.get("score_gap_to_near_miss") if entry.get("score_gap_to_near_miss") is not None else 999.0,
        -(entry.get("score_target") or 0.0),
        -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
        entry.get("ticker") or "",
    )
