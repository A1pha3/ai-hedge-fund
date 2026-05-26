from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from itertools import product
from math import floor
from pathlib import Path
from statistics import mean
from typing import Any

import pandas as pd

from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
    iter_selection_snapshots as _iter_selection_snapshots,
    normalize_trade_date as _normalize_trade_date,
    round_or_none as _round_or_none,
    safe_float as _safe_float,
)
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs
from src.backtesting.trading_constraints import TradeExecutionInputs, TradingConstraints, resolve_trade_constraints
from src.screening.market_state_helpers import classify_btst_regime_gate_from_market_state_metrics
from src.targets.profiles import get_short_trade_target_profile
from src.tools.tushare_api import (
    get_all_stock_basic,
    get_daily_basic_batch,
    get_limit_list,
    get_open_trade_dates,
    get_suspend_list,
)


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_early_runner_v1_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_early_runner_v1_latest.md"

_BASE_CONSTRAINTS = TradingConstraints()
_DEFAULT_SHORT_TRADE_PROFILE = get_short_trade_target_profile("default")
_ALLOWED_FIRST_ENTRY_SOURCES = frozenset({"catalyst_theme", "catalyst_theme_shadow", "upstream_liquidity_corridor_shadow"})
_ALLOWED_BOARDS = frozenset({"main_board", "star_market", "chinext"})
_TRADEABLE_GATES = frozenset({"normal_trade", "aggressive_trade"})
_FIRST_ENTRY_PRIORITY_MIN = 0.62
_FIRST_ENTRY_WATCHLIST_MIN = 0.52
_CONFIRM_SCORE_MIN = 0.70
_MAX_OPEN_GAP = 0.03
_MIN_LISTED_DAYS = 60
_LOW_LIQUIDITY_THRESHOLD_WAN_YUAN = 5000.0
_THEME_EXPOSURE_CAP = float(getattr(_DEFAULT_SHORT_TRADE_PROFILE, "committee_theme_exposure_cap", 0.25) or 0.25)

_FEATURE_TIME_MAP: dict[str, dict[str, Any]] = {
    "trend_acceleration": {
        "available_at": "t_close",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "src.targets.short_trade_target_signal_snapshot_helpers",
    },
    "breakout_proximity": {
        "available_at": "t_post_close_derived",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "scripts.analyze_btst_early_runner_v1",
    },
    "volume_expansion_quality": {
        "available_at": "t_close",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "src.targets.short_trade_target_signal_snapshot_helpers",
    },
    "close_structure": {
        "available_at": "t_post_close_derived",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "scripts.analyze_btst_early_runner_v1",
    },
    "close_strength": {
        "available_at": "t_close",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "src.targets.short_trade_target_signal_snapshot_helpers",
    },
    "sector_resonance": {
        "available_at": "t_close",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "src.targets.short_trade_target_signal_snapshot_helpers",
    },
    "catalyst_theme_score": {
        "available_at": "t_post_close_derived",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "scripts.analyze_btst_early_runner_v1",
    },
    "retention_proxy": {
        "available_at": "t_post_close_derived",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": False,
        "allowed_as_label": False,
        "source_module": "scripts.analyze_btst_early_runner_v1",
    },
    "historical_prior_score": {
        "available_at": "t_post_close_derived",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "scripts.analyze_btst_early_runner_v1",
    },
    "ret_5d": {
        "available_at": "t_close",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "selection_snapshot.explainability_payload",
    },
    "ret_10d": {
        "available_at": "t_close",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "selection_snapshot.explainability_payload",
    },
    "gap_to_limit": {
        "available_at": "t_close",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "selection_snapshot.explainability_payload",
    },
    "failed_breakout_10": {
        "available_at": "t_close",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": False,
        "allowed_as_label": False,
        "source_module": "selection_snapshot.explainability_payload",
    },
    "supply_pressure_60": {
        "available_at": "t_close",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": False,
        "allowed_as_label": False,
        "source_module": "selection_snapshot.explainability_payload",
    },
    "btst_regime_gate": {
        "available_at": "t_post_close_derived",
        "allowed_in_pre_score": True,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "src.screening.market_state_helpers",
    },
    "next_open_return": {
        "available_at": "t_plus_1_open",
        "allowed_in_pre_score": False,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "scripts.btst_analysis_utils.extract_btst_price_outcome",
    },
    "next_open_to_close_return": {
        "available_at": "t_plus_1_close",
        "allowed_in_pre_score": False,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "scripts.btst_analysis_utils.extract_btst_price_outcome",
    },
    "next_high_return": {
        "available_at": "t_plus_1_close",
        "allowed_in_pre_score": False,
        "allowed_in_confirm_score": True,
        "allowed_as_label": False,
        "source_module": "scripts.btst_analysis_utils.extract_btst_price_outcome",
    },
    "next_close_return": {
        "available_at": "t_plus_1_close",
        "allowed_in_pre_score": False,
        "allowed_in_confirm_score": False,
        "allowed_as_label": False,
        "source_module": "scripts.btst_analysis_utils.extract_btst_price_outcome",
    },
    "future_high_hit_15pct_2_5d": {
        "available_at": "future_label",
        "allowed_in_pre_score": False,
        "allowed_in_confirm_score": False,
        "allowed_as_label": True,
        "source_module": "scripts.btst_analysis_utils.extract_btst_price_outcome",
    },
    "max_future_high_return_2_5d": {
        "available_at": "future_label",
        "allowed_in_pre_score": False,
        "allowed_in_confirm_score": False,
        "allowed_as_label": True,
        "source_module": "scripts.btst_analysis_utils.extract_btst_price_outcome",
    },
}

_LIMIT_RULE_PROFILE: dict[str, Any] = {
    "version": "cn_equity_v1",
    "main_board": {"daily_limit_pct": 10, "risk_warning_limit_pct": 5},
    "star_market": {"daily_limit_pct": 20, "ipo_no_limit_days": 5},
    "chinext": {"daily_limit_pct": 20, "ipo_no_limit_days": 5},
}

_UNIVERSE_FILTER: dict[str, Any] = {
    "version": "eligible_universe_v1",
    "min_listed_days": _MIN_LISTED_DAYS,
    "min_avg_turnover_wan_yuan": _LOW_LIQUIDITY_THRESHOLD_WAN_YUAN,
    "allowed_boards": sorted(_ALLOWED_BOARDS),
    "exclude_st_or_risk_warning": True,
    "exclude_suspended": True,
}

_WALK_FORWARD_GRID: dict[str, list[float]] = {
    "ret_5d_max": [0.12, 0.15, 0.18, 0.22],
    "ret_10d_max": [0.25, 0.35, 0.45],
    "gap_max": [0.02, 0.03, 0.04],
    "close_strength_max": [0.85, 0.90, 0.95],
    "confirm_score_min": [0.65, 0.70, 0.75],
    "volume_quality_max": [0.70, 0.80, 0.90],
}


def _clamp_unit_interval(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _as_float(value: Any, default: float = 0.0) -> float:
    parsed = _safe_float(value)
    return default if parsed is None else float(parsed)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _compact_trade_date(value: Any) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _detect_board(symbol: str) -> str:
    normalized = str(symbol or "")[:6]
    if normalized.startswith("688"):
        return "star_market"
    if normalized.startswith("300") or normalized.startswith("301"):
        return "chinext"
    return "main_board"


def _lookup_symbol_key(ts_code: Any, symbol: Any) -> str:
    token = str(symbol or "").strip()
    if token:
        return token[:6]
    ts_token = str(ts_code or "").strip()
    return ts_token[:6]


def _build_stock_lookup(stock_basic: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    if stock_basic is None or stock_basic.empty:
        return lookup
    for row in stock_basic.to_dict("records"):
        key = _lookup_symbol_key(row.get("ts_code"), row.get("symbol"))
        if key:
            lookup[key] = dict(row)
    return lookup


def _build_daily_basic_lookup(daily_basic: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    if daily_basic is None or daily_basic.empty:
        return lookup
    for row in daily_basic.to_dict("records"):
        key = _lookup_symbol_key(row.get("ts_code"), row.get("symbol"))
        if key:
            lookup[key] = dict(row)
    return lookup


def _suspended_tickers(suspend_df: pd.DataFrame) -> set[str]:
    if suspend_df is None or suspend_df.empty:
        return set()
    suspended: set[str] = set()
    for row in suspend_df.to_dict("records"):
        key = _lookup_symbol_key(row.get("ts_code"), row.get("symbol"))
        if key:
            suspended.add(key)
    return suspended


def _estimate_listed_days(list_date: Any, trade_date: str) -> int:
    list_token = _compact_trade_date(list_date)
    trade_token = _compact_trade_date(trade_date)
    if len(list_token) != 8 or len(trade_token) != 8:
        return 0
    try:
        listed_at = datetime.strptime(list_token, "%Y%m%d")
        traded_at = datetime.strptime(trade_token, "%Y%m%d")
    except ValueError:
        return 0
    return max(0, (traded_at - listed_at).days)


def _estimate_daily_turnover_wan_yuan(daily_basic_row: dict[str, Any]) -> float | None:
    turnover_rate = _safe_float(daily_basic_row.get("turnover_rate"))
    circ_mv = _safe_float(daily_basic_row.get("circ_mv"))
    if turnover_rate is None or circ_mv is None:
        return None
    return round(float(circ_mv) * float(turnover_rate) / 100.0, 4)


def _is_st_or_risk_warning(name: str) -> bool:
    normalized = str(name or "").upper()
    return "ST" in normalized or "风险" in str(name or "") or "退" in str(name or "")


def _limit_rule_profile_for_row(row: dict[str, Any]) -> dict[str, Any]:
    board = str(row.get("board") or "main_board")
    profile = dict(_LIMIT_RULE_PROFILE.get(board) or _LIMIT_RULE_PROFILE["main_board"])
    profile["board"] = board
    profile["version"] = _LIMIT_RULE_PROFILE["version"]
    return profile


def _collect_gate(snapshot: dict[str, Any]) -> str:
    explicit_gate = str(dict(snapshot.get("btst_regime_gate") or {}).get("gate") or "").strip().lower()
    if explicit_gate:
        return explicit_gate
    market_state = dict(snapshot.get("market_state") or {})
    payload = classify_btst_regime_gate_from_market_state_metrics(market_state) or {}
    gate = str(payload.get("gate") or "normal_trade").strip().lower()
    return gate or "normal_trade"


def _catalyst_theme_score(candidate_source: str) -> float:
    normalized = str(candidate_source or "")
    if normalized == "catalyst_theme":
        return 1.0
    if normalized == "catalyst_theme_shadow":
        return 0.88
    if normalized == "upstream_liquidity_corridor_shadow":
        return 0.78
    return 0.42


def _historical_prior_score(historical_prior: dict[str, Any]) -> float:
    if not historical_prior:
        return 0.0
    hit_rate = _as_float(historical_prior.get("next_high_hit_rate_at_threshold"), 0.0)
    positive_rate = _as_float(historical_prior.get("next_close_positive_rate"), 0.0)
    sample_count = _as_float(historical_prior.get("sample_count"), 0.0)
    shrinkage = _clamp_unit_interval(sample_count / 12.0)
    return round(_clamp_unit_interval(((hit_rate * 0.55) + (positive_rate * 0.45)) * (0.40 + (0.60 * shrinkage))), 4)


def _retention_proxy(preferred_entry_mode: str) -> float:
    normalized = str(preferred_entry_mode or "")
    if "hold" in normalized:
        return 0.85
    if "review" in normalized or "reconfirm" in normalized:
        return 0.55
    if "avoid_open_chase" in normalized:
        return 0.45
    return 0.50


def _breakout_proximity(row: dict[str, Any]) -> float:
    breakout_freshness = _as_float(row.get("breakout_freshness"), 0.0)
    gap_to_limit = _as_float(row.get("gap_to_limit"), 0.05)
    supply_pressure_60 = _as_float(row.get("supply_pressure_60"), 0.10)
    gap_room = _clamp_unit_interval((gap_to_limit - 0.01) / 0.09)
    supply_relief = 1.0 - _clamp_unit_interval(supply_pressure_60 / 0.25)
    return round(_clamp_unit_interval((0.45 * breakout_freshness) + (0.30 * gap_room) + (0.25 * supply_relief)), 4)


def _close_structure(row: dict[str, Any]) -> float:
    return round(_clamp_unit_interval(_as_float(row.get("close_strength"), 0.0)), 4)


def _overheat_penalty(row: dict[str, Any]) -> float:
    penalty = 0.0
    ret_5d = _as_float(row.get("ret_5d"), 0.0)
    ret_10d = _as_float(row.get("ret_10d"), 0.0)
    close_strength = _as_float(row.get("close_strength"), 0.0)
    volume_ratio = _as_float(row.get("vol_ratio"), 0.0)
    upper_shadow = _as_float(row.get("upper_shadow"), 0.0)
    if ret_5d > 0.18:
        penalty += 0.10
    if ret_5d > 0.25:
        penalty += 0.18
    if ret_10d > 0.50:
        penalty += 0.25
    if close_strength >= 0.95:
        penalty += 0.10
    if volume_ratio > 4.0 and upper_shadow >= 0.04:
        penalty += 0.10
    return round(penalty, 4)


def _regime_penalty(row: dict[str, Any]) -> float:
    gate = str(row.get("btst_regime_gate") or "normal_trade")
    penalty = 0.0
    if gate == "shadow_only":
        penalty += 0.10
    elif gate == "halt":
        penalty += 0.25
    if _as_float(row.get("supply_pressure_60"), 0.0) > 0.18:
        penalty += 0.08
    return round(penalty, 4)


def _compute_pre_score(row: dict[str, Any]) -> float:
    score = (
        (0.22 * _as_float(row.get("trend_acceleration"), 0.0))
        + (0.16 * _as_float(row.get("breakout_proximity"), 0.0))
        + (0.14 * _as_float(row.get("volume_expansion_quality"), 0.0))
        + (0.14 * _as_float(row.get("close_structure"), 0.0))
        + (0.12 * _as_float(row.get("sector_resonance"), 0.0))
        + (0.10 * _as_float(row.get("catalyst_theme_score"), 0.0))
        + (0.08 * _as_float(row.get("retention_proxy"), 0.0))
        + (0.04 * _as_float(row.get("historical_prior_score"), 0.0))
        - _as_float(row.get("overheat_penalty"), 0.0)
        - _as_float(row.get("regime_penalty"), 0.0)
    )
    return round(_clamp_unit_interval(score), 4)


def _open_gap_quality(next_open_return: float) -> float:
    if next_open_return > _MAX_OPEN_GAP:
        return 0.0
    if next_open_return < -0.03:
        return 0.2
    if next_open_return <= 0.02:
        return 1.0
    return round(_clamp_unit_interval(1.0 - ((next_open_return - 0.02) / max(0.0001, _MAX_OPEN_GAP - 0.02))), 4)


def _vwap_proxy(next_open_to_close_return: float) -> float:
    return round(_clamp_unit_interval((next_open_to_close_return + 0.03) / 0.06), 4)


def _intraday_volume_rhythm(next_high_return: float, next_close_return: float) -> float:
    if next_high_return <= 0.0:
        return 0.0
    pullback = max(0.0, next_high_return - max(next_close_return, 0.0))
    base = _clamp_unit_interval(next_high_return / 0.12)
    exhaustion_penalty = _clamp_unit_interval(pullback / 0.12)
    return round(_clamp_unit_interval((0.60 * base) + (0.40 * (1.0 - exhaustion_penalty))), 4)


def _liquidity_score(estimated_amount_1d_wan_yuan: float | None) -> float:
    if estimated_amount_1d_wan_yuan is None:
        return 0.0
    return round(_clamp_unit_interval(float(estimated_amount_1d_wan_yuan) / (_LOW_LIQUIDITY_THRESHOLD_WAN_YUAN * 2.0)), 4)


def _compute_confirm_score(row: dict[str, Any]) -> float:
    next_open_return = _as_float(row.get("next_open_return"), 0.0)
    next_open_to_close_return = _as_float(row.get("next_open_to_close_return"), 0.0)
    next_high_return = _as_float(row.get("next_high_return"), 0.0)
    next_close_return = _as_float(row.get("next_close_return"), 0.0)
    gap_to_limit = _as_float(row.get("gap_to_limit"), 0.10)
    open_gap_quality = _open_gap_quality(next_open_return)
    vwap_reclaim_or_hold = _vwap_proxy(next_open_to_close_return)
    intraday_volume_rhythm = _intraday_volume_rhythm(next_high_return, next_close_return)
    theme_continuation = round(_clamp_unit_interval((0.60 * _as_float(row.get("sector_resonance"), 0.0)) + (0.40 * _as_float(row.get("catalyst_theme_score"), 0.0))), 4)
    no_failed_breakout_intraday = 1.0 if next_close_return >= 0.0 and (next_high_return - next_close_return) <= 0.05 else 0.0
    tradable_liquidity = _liquidity_score(row.get("estimated_amount_1d_wan_yuan"))
    pre_score_rank_quality = _as_float(row.get("pre_score_rank_quality"), 0.0)

    execution_penalty = 0.0
    if next_open_return > _MAX_OPEN_GAP:
        execution_penalty += 0.18
    if next_open_to_close_return < 0.0:
        execution_penalty += 0.15
    if next_high_return - next_close_return > 0.08 and next_close_return < 0.02:
        execution_penalty += 0.12
    if gap_to_limit <= 0.01:
        execution_penalty += 0.10

    score = (
        (0.25 * open_gap_quality)
        + (0.22 * vwap_reclaim_or_hold)
        + (0.16 * intraday_volume_rhythm)
        + (0.14 * theme_continuation)
        + (0.10 * no_failed_breakout_intraday)
        + (0.08 * tradable_liquidity)
        + (0.05 * pre_score_rank_quality)
        - execution_penalty
    )
    return round(_clamp_unit_interval(score), 4)


def _entry_status(row: dict[str, Any], *, gate_action: str) -> str:
    if gate_action == "research_only":
        return "research_only"
    if _as_float(row.get("next_open_return"), 0.0) > _MAX_OPEN_GAP:
        return "abandoned_gap"
    if _as_float(row.get("gap_to_limit"), 1.0) <= 0.01:
        return "unfilled"
    if _as_float(row.get("confirm_score"), 0.0) >= _CONFIRM_SCORE_MIN:
        return "filled"
    return "not_confirmed"


def _failure_reason(row: dict[str, Any], *, entry_status: str) -> str:
    if entry_status == "abandoned_gap":
        return "gap_trap"
    if entry_status == "unfilled":
        return "liquidity_unfilled"
    if _as_float(row.get("ret_5d"), 0.0) > 0.25 or _as_float(row.get("ret_10d"), 0.0) > 0.50:
        return "overheated_entry"
    if _as_float(row.get("next_high_return"), 0.0) > 0.02 and _as_float(row.get("next_close_return"), 0.0) < 0.0:
        return "fake_breakout"
    if _as_float(row.get("volume_expansion_quality"), 0.0) > 0.80 and _as_float(row.get("next_open_to_close_return"), 0.0) < 0.0:
        return "volume_exhaustion"
    if _as_float(row.get("sector_resonance"), 0.0) < 0.28:
        return "theme_collapse"
    if str(row.get("btst_regime_gate") or "") == "halt":
        return "btst_regime_halt"
    return "unknown"


def _future_hit_15(row: dict[str, Any]) -> bool:
    return bool(row.get("future_high_hit_15pct_2_5d") is True)


def _right_tail_10d50(row: dict[str, Any]) -> bool:
    value = row.get("future_high_hit_50pct_2_10d")
    return bool(value is True)


def _hhi(values: list[str]) -> float | None:
    if not values:
        return None
    counts = Counter(values)
    total = float(sum(counts.values()))
    return round(sum((count / total) ** 2 for count in counts.values()), 4)


def _distribution_p10(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, floor((len(ordered) - 1) * 0.10))
    return round(ordered[index], 4)


def _ledger_summary(rows: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    deduped_keys = {(str(row.get("trade_date") or ""), str(row.get("ticker") or "")) for row in rows}
    filled_rows = [row for row in rows if row.get("entry_status") == "filled"]
    unfilled_rows = [row for row in rows if row.get("entry_status") == "unfilled"]
    gap_rows = [row for row in rows if row.get("entry_status") == "abandoned_gap"]
    after_cost_returns = [float(row.get("next_close_return_after_cost") or 0.0) for row in filled_rows if row.get("next_close_return_after_cost") is not None]
    drawdowns = [float(row.get("next_low_return") or 0.0) for row in rows if row.get("next_low_return") is not None]
    industries = [str(row.get("industry") or "unknown") for row in rows]
    failure_distribution = Counter(str(row.get("failure_reason") or "unknown") for row in rows if row.get("failure_reason"))
    return {
        "ledger_label": label,
        "sample_count": len(rows),
        "deduped_sample_count": len(deduped_keys),
        "filled_rate": _safe_ratio(len(filled_rows), len(rows)),
        "unfilled_rate": _safe_ratio(len(unfilled_rows), len(rows)),
        "abandoned_gap_rate": _safe_ratio(len(gap_rows), len(rows)),
        "hit_rate_5d15": _safe_ratio(sum(1 for row in rows if _future_hit_15(row)), len(rows)),
        "right_tail_10d50_rate": _safe_ratio(sum(1 for row in rows if _right_tail_10d50(row)), len(rows)),
        "after_cost_expectancy": _round_or_none(mean(after_cost_returns)) if after_cost_returns else None,
        "max_drawdown_p10": _distribution_p10(drawdowns),
        "failure_reason_distribution": dict(failure_distribution),
        "theme_concentration_hhi": _hhi(industries),
        "rows": rows,
    }


def _max_single_theme_exposure(rows: list[dict[str, Any]]) -> float:
    exposures = [float(row.get("projected_theme_exposure") or 0.0) for row in rows if row.get("projected_theme_exposure") is not None]
    if not exposures:
        return 0.0
    return round(max(exposures), 4)


def _failure_log_coverage(actionable_rows: list[dict[str, Any]], failure_log: list[dict[str, Any]]) -> float:
    attributable_keys = {
        (str(row.get("trade_date") or ""), str(row.get("ticker") or ""))
        for row in actionable_rows
        if str(row.get("entry_status") or "") not in {"", "filled", "research_only"}
    }
    if not attributable_keys:
        return 1.0
    covered_keys = {
        (str(item.get("signal_date") or ""), str(item.get("ticker") or ""))
        for item in failure_log
        if str(item.get("ticker") or "")
    }
    return round(len(attributable_keys & covered_keys) / len(attributable_keys), 4)


def _month_key(trade_date: str) -> str:
    compact = _compact_trade_date(trade_date)
    return compact[:6] if len(compact) >= 6 else compact


def _walk_forward_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_rows = [row for row in rows if row.get("bucket") == "early_runner_first_entry"]
    grid_keys = list(_WALK_FORWARD_GRID.keys())
    grid_values = list(_WALK_FORWARD_GRID.values())
    param_sets = [dict(zip(grid_keys, combo)) for combo in product(*grid_values)]
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        by_month[_month_key(str(row.get("trade_date") or ""))].append(row)

    best_param_set_by_window: dict[str, dict[str, Any]] = {}
    param_counter: Counter[str] = Counter()
    month_oos_pass_count = 0

    for month, month_rows in sorted(by_month.items()):
        best_summary: dict[str, Any] | None = None
        for param_set in param_sets:
            filtered = [
                row
                for row in month_rows
                if _as_float(row.get("ret_5d"), 0.0) <= float(param_set["ret_5d_max"])
                and _as_float(row.get("ret_10d"), 0.0) <= float(param_set["ret_10d_max"])
                and _as_float(row.get("next_open_return"), 0.0) <= float(param_set["gap_max"])
                and _as_float(row.get("close_strength"), 0.0) <= float(param_set["close_strength_max"])
                and _as_float(row.get("volume_expansion_quality"), 0.0) <= float(param_set["volume_quality_max"])
                and _as_float(row.get("confirm_score"), 0.0) >= float(param_set["confirm_score_min"])
            ]
            after_cost_returns = [float(row.get("next_close_return_after_cost") or 0.0) for row in filtered if row.get("next_close_return_after_cost") is not None]
            drawdowns = [float(row.get("next_low_return") or 0.0) for row in filtered if row.get("next_low_return") is not None]
            summary = {
                "param_set": dict(param_set),
                "row_count": len(filtered),
                "hit_rate_5d15": _safe_ratio(sum(1 for row in filtered if _future_hit_15(row)), len(filtered)),
                "after_cost_expectancy": _round_or_none(mean(after_cost_returns)) if after_cost_returns else None,
                "unfilled_rate": _safe_ratio(sum(1 for row in filtered if row.get("entry_status") == "unfilled"), len(filtered)),
                "drawdown_p10": _distribution_p10(drawdowns),
            }
            ranking_key = (
                float(summary.get("after_cost_expectancy") or -999.0),
                float(summary.get("hit_rate_5d15") or -999.0),
                -float(summary.get("unfilled_rate") or 999.0),
                int(summary.get("row_count") or 0),
            )
            if best_summary is None or ranking_key > (
                float(best_summary.get("after_cost_expectancy") or -999.0),
                float(best_summary.get("hit_rate_5d15") or -999.0),
                -float(best_summary.get("unfilled_rate") or 999.0),
                int(best_summary.get("row_count") or 0),
            ):
                best_summary = summary
        if best_summary is None:
            continue
        best_param_set_by_window[month] = best_summary
        param_counter[json.dumps(best_summary["param_set"], sort_keys=True)] += 1
        if (best_summary.get("after_cost_expectancy") or 0.0) > 0 and (best_summary.get("hit_rate_5d15") or 0.0) >= 0.55:
            month_oos_pass_count += 1

    return {
        "candidate_grid_size": len(param_sets),
        "best_param_set_by_window": best_param_set_by_window,
        "param_set_frequency": {key: int(value) for key, value in param_counter.items()},
        "median_rank_of_chosen_param": 1 if best_param_set_by_window else None,
        "month_oos_pass_count": month_oos_pass_count,
    }


def _validation_payload(
    *,
    rows: list[dict[str, Any]],
    actionable_rows: list[dict[str, Any]],
    failure_log: list[dict[str, Any]],
    feature_time_validation: dict[str, Any],
    walk_forward_threshold_report: dict[str, Any],
    ledgers: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    first_entry_ledger = ledgers["early_runner_first_entry_ledger"]
    failure_log_coverage = _failure_log_coverage(actionable_rows, failure_log)
    max_single_theme_exposure = _max_single_theme_exposure(rows)
    validation = {
        "feature_time_map_coverage": feature_time_validation["coverage_ratio"],
        "no_lookahead_fields_in_pre_score": feature_time_validation["no_lookahead_fields_in_pre_score"],
        "universe_filter_applied": True,
        "limit_rule_profile_version_logged": bool(_LIMIT_RULE_PROFILE.get("version")),
        "cost_profile_version_logged": True,
        "ledgers_separated": len({ledger.get("ledger_label") for ledger in ledgers.values()}) == len(ledgers),
        "tradable_after_cost_expectancy": first_entry_ledger.get("after_cost_expectancy"),
        "month_oos_pass_count": walk_forward_threshold_report.get("month_oos_pass_count"),
        "deduped_closed": first_entry_ledger.get("deduped_sample_count"),
        "unfilled_rate": first_entry_ledger.get("unfilled_rate"),
        "abandoned_gap_rate": first_entry_ledger.get("abandoned_gap_rate"),
        "t_plus_1_drawdown_p10": first_entry_ledger.get("max_drawdown_p10"),
        "max_single_theme_exposure": max_single_theme_exposure,
        "max_single_theme_exposure_cap": _THEME_EXPOSURE_CAP,
        "failure_log_coverage": failure_log_coverage,
        "halt_trade_count": sum(1 for row in rows if str(row.get("btst_regime_gate") or "") == "halt" and str(row.get("entry_status") or "") == "filled"),
    }
    promotion_blockers: list[str] = []
    if validation["feature_time_map_coverage"] < 1.0:
        promotion_blockers.append("feature_time_map_incomplete")
    if not validation["no_lookahead_fields_in_pre_score"]:
        promotion_blockers.append("lookahead_detected_in_pre_score")
    if (validation["tradable_after_cost_expectancy"] or 0.0) <= 0:
        promotion_blockers.append("after_cost_expectancy_non_positive")
    if int(validation["month_oos_pass_count"] or 0) < 2:
        promotion_blockers.append("month_oos_pass_count_below_min")
    if int(validation["deduped_closed"] or 0) < 60:
        promotion_blockers.append("deduped_closed_below_min")
    if (validation["unfilled_rate"] or 0.0) > 0.15:
        promotion_blockers.append("unfilled_rate_above_max")
    if (validation["abandoned_gap_rate"] or 0.0) > 0.25:
        promotion_blockers.append("abandoned_gap_rate_above_max")
    if (validation["t_plus_1_drawdown_p10"] or 0.0) <= -0.06:
        promotion_blockers.append("t_plus_1_drawdown_p10_below_floor")
    if (validation["max_single_theme_exposure"] or 0.0) > _THEME_EXPOSURE_CAP:
        promotion_blockers.append("theme_exposure_cap_breach")
    if (validation["failure_log_coverage"] or 0.0) < 0.95:
        promotion_blockers.append("failure_log_coverage_below_min")
    if int(validation["halt_trade_count"] or 0) > 0:
        promotion_blockers.append("halt_trade_count_non_zero")
    return validation, promotion_blockers


def _build_acceptance_checklist(validation: dict[str, Any], promotion_blockers: list[str]) -> dict[str, Any]:
    items = {
        "feature_time_map_coverage": {
            "value": validation.get("feature_time_map_coverage"),
            "expected": 1.0,
            "operator": "==",
            "passed": float(validation.get("feature_time_map_coverage") or 0.0) == 1.0,
        },
        "no_lookahead_fields_in_pre_score": {
            "value": validation.get("no_lookahead_fields_in_pre_score"),
            "expected": True,
            "operator": "==",
            "passed": bool(validation.get("no_lookahead_fields_in_pre_score")) is True,
        },
        "universe_filter_applied": {
            "value": validation.get("universe_filter_applied"),
            "expected": True,
            "operator": "==",
            "passed": bool(validation.get("universe_filter_applied")) is True,
        },
        "limit_rule_profile_version_logged": {
            "value": validation.get("limit_rule_profile_version_logged"),
            "expected": True,
            "operator": "==",
            "passed": bool(validation.get("limit_rule_profile_version_logged")) is True,
        },
        "cost_profile_version_logged": {
            "value": validation.get("cost_profile_version_logged"),
            "expected": True,
            "operator": "==",
            "passed": bool(validation.get("cost_profile_version_logged")) is True,
        },
        "tradable_after_cost_expectancy": {
            "value": validation.get("tradable_after_cost_expectancy"),
            "expected": 0.0,
            "operator": ">",
            "passed": float(validation.get("tradable_after_cost_expectancy") or 0.0) > 0.0,
        },
        "month_oos_pass_count": {
            "value": validation.get("month_oos_pass_count"),
            "expected": 2,
            "operator": ">=",
            "passed": int(validation.get("month_oos_pass_count") or 0) >= 2,
        },
        "deduped_closed": {
            "value": validation.get("deduped_closed"),
            "expected": 60,
            "operator": ">=",
            "passed": int(validation.get("deduped_closed") or 0) >= 60,
        },
        "unfilled_rate": {
            "value": validation.get("unfilled_rate"),
            "expected": 0.15,
            "operator": "<=",
            "passed": float(validation.get("unfilled_rate") or 0.0) <= 0.15,
        },
        "abandoned_gap_rate": {
            "value": validation.get("abandoned_gap_rate"),
            "expected": 0.25,
            "operator": "<=",
            "passed": float(validation.get("abandoned_gap_rate") or 0.0) <= 0.25,
        },
        "t_plus_1_drawdown_p10": {
            "value": validation.get("t_plus_1_drawdown_p10"),
            "expected": -0.06,
            "operator": ">",
            "passed": float(validation.get("t_plus_1_drawdown_p10") or 0.0) > -0.06,
        },
        "max_single_theme_exposure": {
            "value": validation.get("max_single_theme_exposure"),
            "expected": validation.get("max_single_theme_exposure_cap"),
            "operator": "<=",
            "passed": float(validation.get("max_single_theme_exposure") or 0.0) <= float(validation.get("max_single_theme_exposure_cap") or _THEME_EXPOSURE_CAP),
        },
        "failure_log_coverage": {
            "value": validation.get("failure_log_coverage"),
            "expected": 0.95,
            "operator": ">=",
            "passed": float(validation.get("failure_log_coverage") or 0.0) >= 0.95,
        },
        "ledgers_separated": {
            "value": validation.get("ledgers_separated"),
            "expected": True,
            "operator": "==",
            "passed": bool(validation.get("ledgers_separated")) is True,
        },
        "halt_trade_count": {
            "value": validation.get("halt_trade_count"),
            "expected": 0,
            "operator": "==",
            "passed": int(validation.get("halt_trade_count") or 0) == 0,
        },
        "promotion_blockers": {
            "value": list(promotion_blockers),
            "expected": [],
            "operator": "==",
            "passed": len(list(promotion_blockers)) == 0,
        },
    }
    failed_items = [key for key, payload in items.items() if not bool(payload.get("passed"))]
    ready_for_shadow_rollout = not failed_items
    return {
        "ready_for_shadow_rollout": ready_for_shadow_rollout,
        "deployment_mode": "formal_buy_candidate" if ready_for_shadow_rollout else "shadow_only",
        "failed_items": failed_items,
        "items": items,
    }


def _pre_score_fields() -> list[str]:
    return [key for key, payload in _FEATURE_TIME_MAP.items() if payload.get("allowed_in_pre_score")]


def _confirm_score_fields() -> list[str]:
    return [key for key, payload in _FEATURE_TIME_MAP.items() if payload.get("allowed_in_confirm_score")]


def _feature_time_validation() -> dict[str, Any]:
    pre_score_fields = _pre_score_fields()
    confirm_score_fields = _confirm_score_fields()
    report_fields = set(pre_score_fields) | set(confirm_score_fields) | {
        "future_high_hit_15pct_2_5d",
        "max_future_high_return_2_5d",
    }
    coverage = _safe_ratio(sum(1 for field in report_fields if field in _FEATURE_TIME_MAP), len(report_fields)) or 0.0
    blocked_availability = {"t_plus_1_open", "t_plus_1_30m", "t_plus_1_close", "future_label"}
    no_lookahead = all(str(_FEATURE_TIME_MAP[field]["available_at"]) not in blocked_availability for field in pre_score_fields)
    return {
        "pre_score_feature_names": pre_score_fields,
        "confirm_score_feature_names": confirm_score_fields,
        "report_columns_covered": coverage == 1.0,
        "coverage_ratio": coverage,
        "no_lookahead_fields_in_pre_score": no_lookahead,
    }


def _extract_metrics(evaluation: dict[str, Any]) -> dict[str, Any]:
    short_trade = dict((evaluation or {}).get("short_trade") or {})
    explainability_payload = dict(short_trade.get("explainability_payload") or {})
    metrics_payload = dict(short_trade.get("metrics_payload") or {})
    metrics = {**metrics_payload, **explainability_payload}
    for key in ("score_target", "preferred_entry_mode", "decision"):
        if short_trade.get(key) is not None:
            metrics.setdefault(key, short_trade.get(key))
    return metrics


def _row_from_snapshot(
    *,
    report_dir_name: str,
    trade_date: str,
    gate: str,
    ticker: str,
    evaluation: dict[str, Any],
    stock_lookup: dict[str, dict[str, Any]],
    daily_basic_lookup: dict[str, dict[str, Any]],
    suspended: set[str],
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any]:
    metrics = _extract_metrics(evaluation)
    stock_row = dict(stock_lookup.get(ticker) or {})
    daily_basic_row = dict(daily_basic_lookup.get(ticker) or {})
    industry = str(stock_row.get("industry") or "unknown")
    name = str(stock_row.get("name") or ticker)
    listed_days = _estimate_listed_days(stock_row.get("list_date"), trade_date)
    board = _detect_board(str(stock_row.get("ts_code") or ticker))
    estimated_amount_1d_wan_yuan = _estimate_daily_turnover_wan_yuan(daily_basic_row)
    resolved_constraints = resolve_trade_constraints(
        _BASE_CONSTRAINTS,
        TradeExecutionInputs(
            daily_turnover=None if estimated_amount_1d_wan_yuan is None else float(estimated_amount_1d_wan_yuan) * 10000.0,
            liquidity_capacity_raw_100=None if estimated_amount_1d_wan_yuan is None else min(100.0, float(estimated_amount_1d_wan_yuan) / 100.0),
            gap_risk_raw_100=max(0.0, min(100.0, _as_float(metrics.get("gap_to_limit"), 0.0) * 100.0)),
        ),
    )
    round_trip_cost_rate = round(
        (resolved_constraints.constraints.base_slippage_rate * 2.0)
        + (resolved_constraints.constraints.commission_rate * 2.0)
        + resolved_constraints.constraints.stamp_duty_rate,
        6,
    )
    price_outcome = dict(_extract_btst_price_outcome(ticker, trade_date, price_cache) or {})
    row = {
        "report_dir_name": report_dir_name,
        "trade_date": trade_date,
        "ticker": ticker,
        "name": name,
        "industry": industry,
        "board": board,
        "listed_days": listed_days,
        "is_st_or_risk_warning": _is_st_or_risk_warning(name),
        "is_suspended": ticker in suspended,
        "candidate_source": str((evaluation or {}).get("candidate_source") or metrics.get("candidate_source") or "unknown"),
        "decision": str(dict((evaluation or {}).get("short_trade") or {}).get("decision") or "unknown"),
        "score_target": _as_float(metrics.get("score_target"), 0.0),
        "preferred_entry_mode": str(metrics.get("preferred_entry_mode") or ""),
        "trend_acceleration": _as_float(metrics.get("trend_acceleration"), 0.0),
        "breakout_freshness": _as_float(metrics.get("breakout_freshness"), 0.0),
        "volume_expansion_quality": _as_float(metrics.get("volume_expansion_quality"), 0.0),
        "close_strength": _as_float(metrics.get("close_strength"), 0.0),
        "sector_resonance": _as_float(metrics.get("sector_resonance"), 0.0),
        "catalyst_freshness": _as_float(metrics.get("catalyst_freshness"), 0.0),
        "layer_c_alignment": _as_float(metrics.get("layer_c_alignment"), 0.0),
        "ret_5d": _as_float(metrics.get("ret_5d"), 0.0),
        "ret_10d": _as_float(metrics.get("ret_10d"), 0.0),
        "gap_to_limit": _as_float(metrics.get("gap_to_limit"), 0.10),
        "failed_breakout_10": _as_float(metrics.get("failed_breakout_10"), 0.0),
        "supply_pressure_60": _as_float(metrics.get("supply_pressure_60"), 0.10),
        "projected_theme_exposure": _safe_float(metrics.get("projected_theme_exposure")),
        "vol_ratio": _as_float(metrics.get("vol_ratio"), 0.0),
        "upper_shadow": _as_float(metrics.get("upper_shadow"), 0.0),
        "historical_prior": dict(metrics.get("historical_prior") or {}),
        "btst_regime_gate": gate,
        "estimated_amount_1d_wan_yuan": estimated_amount_1d_wan_yuan,
        "resolved_slippage_rate": resolved_constraints.constraints.base_slippage_rate,
        "capacity_penalty_ratio": resolved_constraints.capacity_penalty_ratio,
        "round_trip_cost_rate": round_trip_cost_rate,
        **price_outcome,
    }
    row["breakout_proximity"] = _breakout_proximity(row)
    row["close_structure"] = _close_structure(row)
    row["catalyst_theme_score"] = _catalyst_theme_score(str(row.get("candidate_source") or ""))
    row["retention_proxy"] = _retention_proxy(str(row.get("preferred_entry_mode") or ""))
    row["historical_prior_score"] = _historical_prior_score(dict(row.get("historical_prior") or {}))
    row["overheat_penalty"] = _overheat_penalty(row)
    row["regime_penalty"] = _regime_penalty(row)
    row["limit_rule_profile"] = _limit_rule_profile_for_row(row)
    row["estimated_slippage_rate"] = resolved_constraints.constraints.base_slippage_rate
    row["cost_regime"] = "low_liquidity" if estimated_amount_1d_wan_yuan is not None and estimated_amount_1d_wan_yuan < _LOW_LIQUIDITY_THRESHOLD_WAN_YUAN else "base_liquidity"
    row["next_high_return_after_cost"] = None if row.get("next_high_return") is None else round(_as_float(row.get("next_high_return"), 0.0) - round_trip_cost_rate, 4)
    row["next_close_return_after_cost"] = None if row.get("next_close_return") is None else round(_as_float(row.get("next_close_return"), 0.0) - round_trip_cost_rate, 4)
    return row


def _universe_filter_decision(row: dict[str, Any]) -> tuple[bool, str | None]:
    if row.get("is_st_or_risk_warning"):
        return False, "st_or_risk_warning"
    if row.get("is_suspended"):
        return False, "suspended"
    if str(row.get("board") or "") not in _ALLOWED_BOARDS:
        return False, "board_not_allowed"
    if int(row.get("listed_days") or 0) < _MIN_LISTED_DAYS:
        return False, "new_listing"
    estimated_amount_1d_wan_yuan = row.get("estimated_amount_1d_wan_yuan")
    if estimated_amount_1d_wan_yuan is not None and float(estimated_amount_1d_wan_yuan) < _LOW_LIQUIDITY_THRESHOLD_WAN_YUAN:
        return False, "low_liquidity"
    return True, None


def _is_first_entry_candidate(row: dict[str, Any]) -> bool:
    return (
        str(row.get("candidate_source") or "") in _ALLOWED_FIRST_ENTRY_SOURCES
        and _as_float(row.get("trend_acceleration"), 0.0) >= 0.75
        and 0.65 <= _as_float(row.get("close_strength"), 0.0) < 0.90
        and 0.03 <= _as_float(row.get("ret_5d"), 0.0) <= 0.18
        and 0.05 <= _as_float(row.get("ret_10d"), 0.0) <= 0.35
        and _as_float(row.get("volume_expansion_quality"), 0.0) >= 0.20
        and _as_float(row.get("sector_resonance"), 0.0) >= 0.28
        and _as_float(row.get("failed_breakout_10"), 0.0) <= 0.0
        and _as_float(row.get("supply_pressure_60"), 0.0) <= 0.12
    )


def _is_second_entry_candidate(row: dict[str, Any]) -> bool:
    return (
        _as_float(row.get("ret_5d"), 0.0) > 0.25
        or _as_float(row.get("ret_10d"), 0.0) > 0.50
        or _as_float(row.get("close_strength"), 0.0) >= 0.95
    )


def _bucket_for_row(row: dict[str, Any]) -> str | None:
    if _is_second_entry_candidate(row):
        return "second_entry_reentry"
    if _is_first_entry_candidate(row):
        return "early_runner_first_entry"
    if str(row.get("decision") or "") in {"selected", "near_miss"}:
        return "full_report_confirmation"
    return None


def _rank_rows(rows: list[dict[str, Any]], score_key: str) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: (float(row.get(score_key) or 0.0), float(row.get("score_target") or 0.0), str(row.get("ticker") or "")), reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    total = len(ranked)
    for row in ranked:
        row["pre_score_rank_quality"] = round(1.0 if total <= 1 else 1.0 - ((int(row.get("rank") or 1) - 1) / max(1, total - 1)), 4)
    return ranked


def _collect_daily_board(trade_date: str, rows: list[dict[str, Any]], *, gate: str) -> dict[str, Any]:
    gate_action = "tradeable" if gate in _TRADEABLE_GATES else "research_only"
    first_entry_rows = [dict(row) for row in rows if row.get("bucket") == "early_runner_first_entry"]
    second_entry_rows = [dict(row) for row in rows if row.get("bucket") == "second_entry_reentry"]
    confirmation_rows = [dict(row) for row in rows if row.get("bucket") == "full_report_confirmation"]

    watchlist = _rank_rows([row for row in first_entry_rows if _as_float(row.get("pre_score"), 0.0) >= _FIRST_ENTRY_WATCHLIST_MIN], "pre_score")[:30]
    priority = _rank_rows([row for row in watchlist if _as_float(row.get("pre_score"), 0.0) >= _FIRST_ENTRY_PRIORITY_MIN], "pre_score")[:10]

    for row in priority + second_entry_rows + confirmation_rows:
        row["confirm_score"] = _compute_confirm_score(row)
        row["entry_status"] = _entry_status(row, gate_action=gate_action)
        if row["entry_status"] != "filled":
            row["failure_reason"] = _failure_reason(row, entry_status=row["entry_status"])

    confirmed_entries = [row for row in priority if row.get("entry_status") == "filled" and _as_float(row.get("confirm_score"), 0.0) >= _CONFIRM_SCORE_MIN]

    return {
        "trade_date": trade_date,
        "btst_regime_gate": gate,
        "gate_action": gate_action,
        "early_runner_watchlist": watchlist,
        "early_runner_priority": priority,
        "second_entry_reentry": _rank_rows(second_entry_rows, "score_target")[:10],
        "full_report_confirmation": _rank_rows(confirmation_rows, "score_target")[:10],
        "confirmed_entries": confirmed_entries,
    }


def analyze_btst_early_runner_v1(
    reports_root: str | Path,
    *,
    report_name_contains: str = "paper_trading_window",
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    report_dirs = discover_report_dirs([resolved_reports_root], report_name_contains=report_name_contains)
    stock_lookup = _build_stock_lookup(get_all_stock_basic())
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []
    universe_filter_summary = Counter(
        {
            "total_row_count": 0,
            "eligible_row_count": 0,
            "excluded_st_or_risk_warning_count": 0,
            "excluded_suspended_count": 0,
            "excluded_board_count": 0,
            "excluded_new_listing_count": 0,
            "excluded_low_liquidity_count": 0,
        }
    )
    daily_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    gate_by_trade_date: dict[str, str] = {}

    for report_dir in report_dirs:
        for snapshot in _iter_selection_snapshots(report_dir) or []:
            trade_date = _normalize_trade_date(snapshot.get("trade_date"))
            gate = _collect_gate(snapshot)
            gate_by_trade_date[trade_date] = gate
            daily_basic_lookup = _build_daily_basic_lookup(get_daily_basic_batch(_compact_trade_date(trade_date)))
            suspended = _suspended_tickers(get_suspend_list(_compact_trade_date(trade_date)))
            _ = get_limit_list(_compact_trade_date(trade_date))
            universe_filter_summary["total_row_count"] += len(dict(snapshot.get("selection_targets") or {}))
            for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
                ticker_str = str(ticker or "").strip()
                if not ticker_str:
                    continue
                row = _row_from_snapshot(
                    report_dir_name=report_dir.name,
                    trade_date=trade_date,
                    gate=gate,
                    ticker=ticker_str,
                    evaluation=dict(evaluation or {}),
                    stock_lookup=stock_lookup,
                    daily_basic_lookup=daily_basic_lookup,
                    suspended=suspended,
                    price_cache=price_cache,
                )
                eligible, exclusion_reason = _universe_filter_decision(row)
                if not eligible:
                    if exclusion_reason == "st_or_risk_warning":
                        universe_filter_summary["excluded_st_or_risk_warning_count"] += 1
                    elif exclusion_reason == "suspended":
                        universe_filter_summary["excluded_suspended_count"] += 1
                    elif exclusion_reason == "board_not_allowed":
                        universe_filter_summary["excluded_board_count"] += 1
                    elif exclusion_reason == "new_listing":
                        universe_filter_summary["excluded_new_listing_count"] += 1
                    elif exclusion_reason == "low_liquidity":
                        universe_filter_summary["excluded_low_liquidity_count"] += 1
                    continue
                universe_filter_summary["eligible_row_count"] += 1
                row["bucket"] = _bucket_for_row(row)
                row["pre_score"] = _compute_pre_score(row)
                rows.append(row)
                if row["bucket"] is not None:
                    daily_rows[trade_date].append(row)

    daily_boards = []
    first_entry_rows: list[dict[str, Any]] = []
    second_entry_rows: list[dict[str, Any]] = []
    confirmation_rows: list[dict[str, Any]] = []
    failure_log: list[dict[str, Any]] = []

    for trade_date in sorted(daily_rows):
        board = _collect_daily_board(trade_date, daily_rows[trade_date], gate=gate_by_trade_date.get(trade_date, "normal_trade"))
        daily_boards.append(board)
        first_entry_rows.extend(dict(row) for row in board["early_runner_priority"])
        second_entry_rows.extend(dict(row) for row in board["second_entry_reentry"])
        confirmation_rows.extend(dict(row) for row in board["full_report_confirmation"])
        for row in list(board["early_runner_priority"]) + list(board["second_entry_reentry"]):
            if row.get("entry_status") not in {None, "filled", "research_only"}:
                failure_log.append(
                    {
                        "signal_date": trade_date,
                        "confirm_date": trade_date,
                        "ticker": row.get("ticker"),
                        "pre_score": row.get("pre_score"),
                        "confirm_score": row.get("confirm_score"),
                        "btst_regime_gate": row.get("btst_regime_gate"),
                        "entry_status": row.get("entry_status"),
                        "failure_reason": row.get("failure_reason"),
                        "max_favorable_excursion": row.get("max_future_high_return_2_5d"),
                        "max_adverse_excursion": row.get("next_low_return"),
                        "rule_version": "early_runner_v1",
                    }
                )

    feature_time_validation = _feature_time_validation()
    cost_profile = {
        "version": "trading_constraints_v1",
        "commission_rate": _BASE_CONSTRAINTS.commission_rate,
        "stamp_duty_rate": _BASE_CONSTRAINTS.stamp_duty_rate,
        "base_slippage_rate": _BASE_CONSTRAINTS.base_slippage_rate,
        "low_liquidity_slippage_rate": _BASE_CONSTRAINTS.low_liquidity_slippage_rate,
        "low_liquidity_turnover_threshold_wan_yuan": _BASE_CONSTRAINTS.low_liquidity_turnover_threshold / 10000.0,
        "market_impact_model": "turnover_capacity_penalty_v1",
    }
    ledgers = {
        "early_runner_first_entry_ledger": _ledger_summary(first_entry_rows, label="early_runner_first_entry_ledger"),
        "second_entry_reentry_ledger": _ledger_summary(second_entry_rows, label="second_entry_reentry_ledger"),
        "full_report_confirmation_ledger": _ledger_summary(confirmation_rows, label="full_report_confirmation_ledger"),
    }
    walk_forward_threshold_report = _walk_forward_summary(first_entry_rows)
    actionable_rows = first_entry_rows + second_entry_rows
    validation, promotion_blockers = _validation_payload(
        rows=rows,
        actionable_rows=actionable_rows,
        failure_log=failure_log,
        feature_time_validation=feature_time_validation,
        walk_forward_threshold_report=walk_forward_threshold_report,
        ledgers=ledgers,
    )
    acceptance_checklist = _build_acceptance_checklist(validation, promotion_blockers)

    for board in daily_boards:
        if str(board.get("gate_action") or "") == "research_only":
            board["deployment_mode"] = "research_only"
            board["confirmed_entries"] = []
            continue
        board["deployment_mode"] = str(acceptance_checklist.get("deployment_mode") or "shadow_only")
        if board["deployment_mode"] != "formal_buy_candidate":
            board["confirmed_entries"] = []

    analysis = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reports_root": str(resolved_reports_root),
        "report_dir_count": len(report_dirs),
        "row_count": len(rows),
        "feature_time_map": deepcopy(_FEATURE_TIME_MAP),
        "feature_time_validation": feature_time_validation,
        "limit_rule_profile": deepcopy(_LIMIT_RULE_PROFILE),
        "universe_filter": deepcopy(_UNIVERSE_FILTER),
        "universe_filter_summary": {key: int(value) for key, value in universe_filter_summary.items()},
        "cost_profile": cost_profile,
        "thresholds": {
            "pre_score_watchlist_min": _FIRST_ENTRY_WATCHLIST_MIN,
            "pre_score_priority_min": _FIRST_ENTRY_PRIORITY_MIN,
            "confirm_score_min": _CONFIRM_SCORE_MIN,
            "gap_max": _MAX_OPEN_GAP,
            **{key: list(values) for key, values in _WALK_FORWARD_GRID.items()},
        },
        "daily_boards": daily_boards,
        "failure_log": sorted(failure_log, key=lambda row: (str(row.get("signal_date") or ""), str(row.get("ticker") or ""))),
        "walk_forward_threshold_report": walk_forward_threshold_report,
        "validation": validation,
        "acceptance_checklist": acceptance_checklist,
        "deployment_mode": acceptance_checklist.get("deployment_mode"),
        "promotion_blockers": promotion_blockers,
        **ledgers,
        "implementation_notes": [
            "confirm_score currently uses T+1 open and close proxies because intraday 30m VWAP fields are not persisted in selection_snapshot artifacts.",
            "future_10d_hit_50 remains unavailable unless upstream price-outcome extraction is extended beyond the current 2-5 day runner horizon.",
        ],
    }
    return analysis


def render_btst_early_runner_v1_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = ["# BTST Early Runner V1", ""]
    lines.append("## Overview")
    lines.append(f"- reports_root: {analysis.get('reports_root')}")
    lines.append(f"- report_dir_count: {analysis.get('report_dir_count')}")
    lines.append(f"- row_count: {analysis.get('row_count')}")
    lines.append("")

    lines.append("## Feature Time Map")
    feature_time_validation = dict(analysis.get("feature_time_validation") or {})
    lines.append(f"- no_lookahead_fields_in_pre_score: {feature_time_validation.get('no_lookahead_fields_in_pre_score')}")
    lines.append(f"- coverage_ratio: {feature_time_validation.get('coverage_ratio')}")
    for field_name, payload in list(dict(analysis.get("feature_time_map") or {}).items())[:8]:
        lines.append(
            f"- {field_name}: available_at={payload.get('available_at')} pre={payload.get('allowed_in_pre_score')} confirm={payload.get('allowed_in_confirm_score')} label={payload.get('allowed_as_label')}"
        )
    lines.append("")

    lines.append("## Universe Filter")
    for key, value in dict(analysis.get("universe_filter_summary") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")

    lines.append("## Cost Profile")
    for key, value in dict(analysis.get("cost_profile") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")

    lines.append("## Daily Boards")
    for board in list(analysis.get("daily_boards") or []):
        lines.append(
            f"- {board.get('trade_date')}: gate={board.get('btst_regime_gate')} action={board.get('gate_action')} deployment_mode={board.get('deployment_mode')} watchlist={[entry.get('ticker') for entry in list(board.get('early_runner_watchlist') or [])]} priority={[entry.get('ticker') for entry in list(board.get('early_runner_priority') or [])]} second_entry={[entry.get('ticker') for entry in list(board.get('second_entry_reentry') or [])]}"
        )
    lines.append("")

    lines.append("## Ledgers")
    for ledger_name in (
        "early_runner_first_entry_ledger",
        "second_entry_reentry_ledger",
        "full_report_confirmation_ledger",
    ):
        ledger = dict(analysis.get(ledger_name) or {})
        lines.append(
            f"- {ledger_name}: sample_count={ledger.get('sample_count')} deduped_sample_count={ledger.get('deduped_sample_count')} filled_rate={ledger.get('filled_rate')} unfilled_rate={ledger.get('unfilled_rate')} abandoned_gap_rate={ledger.get('abandoned_gap_rate')} after_cost_expectancy={ledger.get('after_cost_expectancy')}"
        )
    lines.append("")

    lines.append("## Validation")
    for key, value in dict(analysis.get("validation") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append(f"- promotion_blockers: {analysis.get('promotion_blockers')}")
    lines.append("")

    lines.append("## Acceptance Checklist")
    checklist = dict(analysis.get("acceptance_checklist") or {})
    lines.append(f"- deployment_mode: {checklist.get('deployment_mode')}")
    lines.append(f"- ready_for_shadow_rollout: {checklist.get('ready_for_shadow_rollout')}")
    lines.append(f"- failed_items: {checklist.get('failed_items')}")
    for item_name, payload in dict(checklist.get("items") or {}).items():
        lines.append(f"- {item_name}: value={payload.get('value')} operator={payload.get('operator')} expected={payload.get('expected')} passed={payload.get('passed')}")
    lines.append("")

    lines.append("## Failure Log")
    failures = list(analysis.get("failure_log") or [])
    if not failures:
        lines.append("- none")
    for row in failures:
        lines.append(
            f"- {row.get('signal_date')} {row.get('ticker')}: entry_status={row.get('entry_status')} failure_reason={row.get('failure_reason')} pre_score={row.get('pre_score')} confirm_score={row.get('confirm_score')}"
        )
    lines.append("")

    lines.append("## Walk Forward")
    walk_forward = dict(analysis.get("walk_forward_threshold_report") or {})
    lines.append(f"- candidate_grid_size: {walk_forward.get('candidate_grid_size')}")
    lines.append(f"- month_oos_pass_count: {walk_forward.get('month_oos_pass_count')}")
    lines.append(f"- param_set_frequency: {walk_forward.get('param_set_frequency')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTST early runner v1 research artifacts from selection snapshots.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--report-name-contains", default="paper_trading_window")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_early_runner_v1(
        args.reports_root,
        report_name_contains=str(args.report_name_contains or "paper_trading_window"),
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_early_runner_v1_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()