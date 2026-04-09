from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.project_env import load_project_dotenv
from src.screening.candidate_pool import (
    MAX_CANDIDATE_POOL_SIZE,
    MIN_AVG_AMOUNT_20D,
    MIN_ESTIMATED_AMOUNT_1D,
    SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE,
    SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE,
    SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE,
    _load_candidate_pool_shadow_snapshot,
    _estimate_amount_from_daily_basic,
    MIN_LISTING_DAYS,
    _estimate_trading_days,
    _get_avg_amount_20d,
    _get_avg_amount_20d_map,
    _get_pro,
    build_beijing_exchange_mask,
    get_cooled_tickers,
    is_beijing_exchange_stock,
)
from src.tools.tushare_api import get_all_stock_basic, get_daily_basic_batch, get_limit_list, get_suspend_list


load_project_dotenv()


REPORTS_DIR = Path("data/reports")
DEFAULT_TRADEABLE_OPPORTUNITY_POOL_PATH = REPORTS_DIR / "btst_tradeable_opportunity_pool_march.json"
DEFAULT_FAILURE_DOSSIER_PATH = REPORTS_DIR / "btst_no_candidate_entry_failure_dossier_latest.json"
DEFAULT_WATCHLIST_RECALL_DOSSIER_PATH = REPORTS_DIR / "btst_watchlist_recall_dossier_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.md"
DEFAULT_PRIORITY_LIMIT = 5
DEFAULT_FRONTIER_NEIGHBOR_COUNT = 2
STAGE_ORDER = [
    "shadow_snapshot_legacy_unknown",
    "missing_market_context",
    "missing_stock_basic",
    "st_excluded",
    "beijing_exchange_excluded",
    "new_listing_excluded",
    "suspended",
    "limit_up_excluded",
    "cooldown_excluded",
    "low_estimated_liquidity",
    "low_avg_amount_20d",
    "candidate_pool_truncated_after_filters",
    "candidate_pool_visible_or_later_stage",
]


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _safe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _compact_trade_date(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    left = _safe_float(numerator)
    right = _safe_float(denominator)
    if left is None or right is None or right <= 0:
        return None
    return round(left / right, 4)


def _avg_amount_share_of_min_gate(value: Any) -> float | None:
    amount = _safe_float(value)
    if amount is None or MIN_AVG_AMOUNT_20D <= 0:
        return None
    return round(amount / float(MIN_AVG_AMOUNT_20D), 4)


def _snapshot_paths(snapshots_root: Path, trade_date: str) -> list[Path]:
    compact_trade_date = _compact_trade_date(trade_date)
    return [
        snapshots_root / f"candidate_pool_{compact_trade_date}_top300.json",
        snapshots_root / f"candidate_pool_{compact_trade_date}.json",
    ]


def _shadow_snapshot_path(snapshots_root: Path, trade_date: str) -> Path:
    compact_trade_date = _compact_trade_date(trade_date)
    return snapshots_root / f"candidate_pool_{compact_trade_date}_top300_shadow.json"


def _find_local_prices_snapshot_path(snapshots_root: Path, ticker: str, trade_date: str) -> Path | None:
    ticker_root = snapshots_root / ticker
    if not ticker_root.exists():
        return None
    compact_trade_date = _compact_trade_date(trade_date)
    for path in sorted(ticker_root.glob("*/prices.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        observed_trade_dates = {_compact_trade_date(str(row.get("time") or "")) for row in list(rows or [])}
        if compact_trade_date in observed_trade_dates:
            return path
    return None


def _estimate_avg_amount_20d_from_local_prices(snapshots_root: Path, ticker: str, trade_date: str) -> tuple[float | None, str | None]:
    prices_path = _find_local_prices_snapshot_path(snapshots_root, ticker, trade_date)
    if prices_path is None:
        return None, None

    try:
        rows = json.loads(prices_path.read_text(encoding="utf-8"))
    except Exception:
        return None, None

    compact_trade_date = _compact_trade_date(trade_date)
    amount_samples: list[float] = []
    for row in list(rows or []):
        row_trade_date = _compact_trade_date(str(row.get("time") or ""))
        if not row_trade_date or row_trade_date > compact_trade_date:
            continue
        close_price = _safe_float(row.get("close"))
        volume = _safe_float(row.get("volume"))
        if close_price is None or volume is None:
            continue
        amount_samples.append(round(close_price * volume / 100.0, 4))

    if not amount_samples:
        return None, prices_path.as_posix()
    return round(sum(amount_samples[-20:]) / len(amount_samples[-20:]), 4), prices_path.as_posix()


def _load_candidate_pool_snapshot(
    snapshots_root: Path,
    trade_date: str,
    *,
    snapshot_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    compact_trade_date = _compact_trade_date(trade_date)
    cached = snapshot_cache.get(compact_trade_date)
    if cached is not None:
        return cached

    shadow_snapshot_path = _shadow_snapshot_path(snapshots_root, trade_date)
    shadow_snapshot_payload = _load_candidate_pool_shadow_snapshot(shadow_snapshot_path) if shadow_snapshot_path.exists() else {}
    shadow_summary = dict(shadow_snapshot_payload.get("shadow_summary") or {})
    for path in _snapshot_paths(snapshots_root, trade_date):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        ticker_ranks: dict[str, int] = {}
        snapshot_cutoff_ticker = None
        snapshot_cutoff_avg_amount_20d = None
        for index, item in enumerate(list(payload or []), start=1):
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").strip()
            if ticker and ticker not in ticker_ranks:
                ticker_ranks[ticker] = index
            snapshot_cutoff_ticker = ticker or snapshot_cutoff_ticker
            avg_volume_20d = _safe_float(item.get("avg_volume_20d"))
            if avg_volume_20d is not None:
                snapshot_cutoff_avg_amount_20d = round(float(avg_volume_20d), 4)
        cached = {
            "snapshot_path": path.as_posix(),
            "snapshot_name": path.name,
            "snapshot_size": len(ticker_ranks),
            "ticker_ranks": ticker_ranks,
            "selected_cutoff_ticker": snapshot_cutoff_ticker,
            "selected_cutoff_avg_volume_20d": snapshot_cutoff_avg_amount_20d,
            "shadow_snapshot_path": shadow_snapshot_path.as_posix() if shadow_snapshot_path.exists() else None,
            "shadow_recall_complete": shadow_summary.get("shadow_recall_complete"),
            "shadow_recall_status": shadow_summary.get("shadow_recall_status"),
            "shadow_selected_cutoff_avg_volume_20d": shadow_summary.get("selected_cutoff_avg_volume_20d"),
        }
        snapshot_cache[compact_trade_date] = cached
        return cached

    cached = {
        "snapshot_path": None,
        "snapshot_name": None,
        "snapshot_size": 0,
        "ticker_ranks": {},
        "selected_cutoff_ticker": None,
        "selected_cutoff_avg_volume_20d": None,
        "shadow_snapshot_path": shadow_snapshot_path.as_posix() if shadow_snapshot_path.exists() else None,
        "shadow_recall_complete": shadow_summary.get("shadow_recall_complete"),
        "shadow_recall_status": shadow_summary.get("shadow_recall_status"),
        "shadow_selected_cutoff_avg_volume_20d": shadow_summary.get("selected_cutoff_avg_volume_20d"),
    }
    snapshot_cache[compact_trade_date] = cached
    return cached


def _build_focus_tickers(
    tradeable_pool: dict[str, Any],
    watchlist_recall_dossier: dict[str, Any],
    failure_dossier: dict[str, Any],
    *,
    priority_limit: int,
) -> list[str]:
    priority_limit = max(int(priority_limit), 0)
    focus_tickers: list[str] = []

    def _extend_unique(candidates: list[str]) -> None:
        for value in candidates:
            ticker = str(value or "").strip()
            if not ticker or ticker in focus_tickers:
                continue
            focus_tickers.append(ticker)
            if len(focus_tickers) >= priority_limit:
                break

    top_absent_from_candidate_pool = [
        str(value)
        for value in list(watchlist_recall_dossier.get("top_absent_from_candidate_pool_tickers") or [])
        if str(value or "").strip()
    ]
    _extend_unique(top_absent_from_candidate_pool)
    if len(focus_tickers) >= priority_limit:
        return focus_tickers[:priority_limit]

    top_absent_from_watchlist = [
        str(value)
        for value in list(failure_dossier.get("top_absent_from_watchlist_tickers") or [])
        if str(value or "").strip()
    ]
    _extend_unique(top_absent_from_watchlist)
    if len(focus_tickers) >= priority_limit:
        return focus_tickers[:priority_limit]

    high_value_ticker_metrics: dict[str, dict[str, Any]] = {}
    for row in list(tradeable_pool.get("rows") or []):
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        if str(row.get("first_kill_switch") or "") != "no_candidate_entry":
            continue
        if not bool(row.get("strict_btst_goal_case")):
            continue
        metrics = high_value_ticker_metrics.setdefault(
            ticker,
            {
                "ticker": ticker,
                "occurrence_count": 0,
                "max_t_plus_2_close_return": float("-inf"),
                "max_next_high_return": float("-inf"),
                "latest_trade_date": 0,
            },
        )
        metrics["occurrence_count"] += 1
        t_plus_2_close_return = _safe_float(row.get("t_plus_2_close_return"))
        next_high_return = _safe_float(row.get("next_high_return"))
        if t_plus_2_close_return is not None:
            metrics["max_t_plus_2_close_return"] = max(float(metrics["max_t_plus_2_close_return"]), float(t_plus_2_close_return))
        if next_high_return is not None:
            metrics["max_next_high_return"] = max(float(metrics["max_next_high_return"]), float(next_high_return))
        compact_trade_date = _compact_trade_date(str(row.get("trade_date") or ""))
        if compact_trade_date:
            metrics["latest_trade_date"] = max(int(metrics["latest_trade_date"]), int(compact_trade_date))

    high_value_focus_tickers = [
        str(row.get("ticker") or "")
        for row in sorted(
            high_value_ticker_metrics.values(),
            key=lambda current: (
                -float(current.get("max_t_plus_2_close_return") if current.get("max_t_plus_2_close_return") != float("-inf") else -999.0),
                -float(current.get("max_next_high_return") if current.get("max_next_high_return") != float("-inf") else -999.0),
                -int(current.get("occurrence_count") or 0),
                -int(current.get("latest_trade_date") or 0),
                str(current.get("ticker") or ""),
            ),
        )
        if str(row.get("ticker") or "").strip()
    ]
    _extend_unique(high_value_focus_tickers)
    if len(focus_tickers) >= priority_limit:
        return focus_tickers[:priority_limit]

    top_ticker_rows = [
        dict(row)
        for row in list(dict(tradeable_pool.get("no_candidate_entry_summary") or {}).get("top_ticker_rows") or [])
        if str(row.get("ticker") or "").strip()
    ]
    _extend_unique([str(row.get("ticker") or "") for row in top_ticker_rows])
    return focus_tickers[:priority_limit]


def _build_trade_date_allowlist(watchlist_recall_dossier: dict[str, Any]) -> dict[str, set[str]]:
    allowlist: dict[str, set[str]] = {}
    for row in list(watchlist_recall_dossier.get("priority_ticker_dossiers") or []):
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        trade_dates = {
            _compact_trade_date(str(evidence.get("trade_date") or ""))
            for evidence in list(row.get("occurrence_evidence") or [])
            if str(evidence.get("recall_stage") or "") == "absent_from_candidate_pool"
        }
        if trade_dates:
            allowlist[ticker] = trade_dates
    return allowlist


def _build_stock_basic_by_symbol() -> dict[str, dict[str, Any]]:
    stock_df = get_all_stock_basic()
    if stock_df is None or stock_df.empty:
        return {}
    normalized = stock_df.fillna("")
    result: dict[str, dict[str, Any]] = {}
    for _, row in normalized.iterrows():
        symbol = str(row.get("symbol") or "").strip()
        if symbol:
            result[symbol] = row.to_dict()
    return result


def _load_stock_basic_universe() -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    stock_df = get_all_stock_basic()
    if stock_df is None or stock_df.empty:
        return pd.DataFrame(), {}
    normalized = stock_df.fillna("").copy()
    result: dict[str, dict[str, Any]] = {}
    for _, row in normalized.iterrows():
        symbol = str(row.get("symbol") or "").strip()
        if symbol:
            result[symbol] = row.to_dict()
    return normalized, result


def _build_tradeable_pool_stock_basic_fallback(rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    fallback_rows: list[dict[str, Any]] = []
    fallback_by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("ticker") or "").strip()
        ts_code = str(row.get("ts_code") or "").strip()
        if not symbol or not ts_code:
            continue
        fallback_row = {
            "symbol": symbol,
            "ts_code": ts_code,
            "name": str(row.get("name") or "").strip(),
            "list_date": str(row.get("list_date") or "").strip(),
            "market": str(row.get("market") or "").strip(),
        }
        fallback_by_symbol[symbol] = fallback_row
    if fallback_by_symbol:
        fallback_rows = list(fallback_by_symbol.values())
    return pd.DataFrame(fallback_rows), fallback_by_symbol


def _build_frontier_window(rows: list[dict[str, Any]], *, center_rank: int | None, neighbor_count: int = DEFAULT_FRONTIER_NEIGHBOR_COUNT) -> list[dict[str, Any]]:
    if not rows or center_rank is None:
        return []
    start_rank = max(1, int(center_rank) - max(int(neighbor_count), 0))
    end_rank = min(len(rows), int(center_rank) + max(int(neighbor_count), 0))
    return [dict(row) for row in rows[start_rank - 1:end_rank]]


def _classify_pre_truncation_ranking_driver(
    *,
    pre_truncation_rank_gap_to_cutoff: Any,
    avg_amount_share_of_cutoff: Any,
    market_cap_share_of_cutoff: Any,
) -> str:
    rank_gap = int(pre_truncation_rank_gap_to_cutoff) if pre_truncation_rank_gap_to_cutoff is not None else None
    avg_share = _safe_float(avg_amount_share_of_cutoff)
    market_cap_share = _safe_float(market_cap_share_of_cutoff)
    if avg_share is None:
        return "unknown"
    if avg_share <= 0.8:
        return "avg_amount_20d_gap_dominant"
    if avg_share < 0.95:
        return "avg_amount_20d_gap"
    if rank_gap is not None and rank_gap <= 20 and market_cap_share is not None and market_cap_share < 1.0:
        return "market_cap_tie_break_gap"
    if market_cap_share is not None and market_cap_share < 0.9:
        return "market_cap_tie_break_gap"
    return "mixed_post_filter_gap"


def _classify_pre_truncation_liquidity_gap_mode(
    *,
    avg_amount_share_of_min_gate: Any,
    avg_amount_share_of_cutoff: Any,
) -> str:
    gate_share = _safe_float(avg_amount_share_of_min_gate)
    cutoff_share = _safe_float(avg_amount_share_of_cutoff)
    if gate_share is None or cutoff_share is None:
        return "unknown"
    if cutoff_share < 0.65 and gate_share < 6.0:
        return "barely_above_gate_and_far_below_cutoff"
    if cutoff_share < 0.65:
        return "well_above_gate_but_far_below_cutoff"
    if cutoff_share < 0.85:
        return "moderate_gap_above_gate"
    return "near_cutoff_liquidity_gap"


def _build_ticker_truncation_ranking_summary(occurrence_evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    truncation_rows = [
        dict(row)
        for row in occurrence_evidence
        if str(row.get("blocking_stage") or "") == "candidate_pool_truncated_after_filters"
        and (row.get("pre_truncation_rank") is not None or row.get("pre_truncation_avg_amount_share_of_cutoff") is not None)
    ]
    if not truncation_rows:
        return None

    rank_gaps = [int(row.get("pre_truncation_rank_gap_to_cutoff") or 0) for row in truncation_rows if row.get("pre_truncation_rank_gap_to_cutoff") is not None]
    avg_amount_shares = [_safe_float(row.get("pre_truncation_avg_amount_share_of_cutoff")) for row in truncation_rows]
    avg_amount_shares = [value for value in avg_amount_shares if value is not None]
    avg_amount_gate_shares = [_safe_float(row.get("avg_amount_share_of_min_gate")) for row in truncation_rows]
    avg_amount_gate_shares = [value for value in avg_amount_gate_shares if value is not None]
    cutoff_avg_amount_gate_shares = [_safe_float(row.get("pre_truncation_cutoff_avg_amount_share_of_min_gate")) for row in truncation_rows]
    cutoff_avg_amount_gate_shares = [value for value in cutoff_avg_amount_gate_shares if value is not None]
    ranking_driver_counts = Counter(str(row.get("pre_truncation_ranking_driver") or "unknown") for row in truncation_rows)
    dominant_ranking_driver = ranking_driver_counts.most_common(1)[0][0] if ranking_driver_counts else None
    liquidity_gap_mode_counts = Counter(str(row.get("pre_truncation_liquidity_gap_mode") or "unknown") for row in truncation_rows)
    dominant_liquidity_gap_mode = liquidity_gap_mode_counts.most_common(1)[0][0] if liquidity_gap_mode_counts else None
    closest_case = min(
        truncation_rows,
        key=lambda row: (
            0 if row.get("pre_truncation_rank") is not None else 1,
            int(row.get("pre_truncation_rank_gap_to_cutoff") or 10**9),
            int(row.get("pre_truncation_rank") or 10**9),
            -float(_safe_float(row.get("pre_truncation_avg_amount_share_of_cutoff")) or 0.0),
            str(row.get("trade_date") or ""),
        ),
    )
    return {
        "truncation_case_count": len(truncation_rows),
        "dominant_ranking_driver": dominant_ranking_driver,
        "ranking_driver_counts": {key: int(value) for key, value in ranking_driver_counts.most_common()},
        "dominant_liquidity_gap_mode": dominant_liquidity_gap_mode,
        "liquidity_gap_mode_counts": {key: int(value) for key, value in liquidity_gap_mode_counts.most_common()},
        "avg_rank_gap_to_cutoff": round(sum(rank_gaps) / len(rank_gaps), 4) if rank_gaps else None,
        "min_rank_gap_to_cutoff": min(rank_gaps) if rank_gaps else None,
        "avg_amount_share_of_cutoff_mean": round(sum(avg_amount_shares) / len(avg_amount_shares), 4) if avg_amount_shares else None,
        "avg_amount_share_of_cutoff_min": min(avg_amount_shares) if avg_amount_shares else None,
        "avg_amount_share_of_cutoff_max": max(avg_amount_shares) if avg_amount_shares else None,
        "avg_amount_share_of_min_gate_mean": round(sum(avg_amount_gate_shares) / len(avg_amount_gate_shares), 4) if avg_amount_gate_shares else None,
        "avg_amount_share_of_min_gate_min": min(avg_amount_gate_shares) if avg_amount_gate_shares else None,
        "avg_amount_share_of_min_gate_max": max(avg_amount_gate_shares) if avg_amount_gate_shares else None,
        "cutoff_avg_amount_share_of_min_gate_mean": round(sum(cutoff_avg_amount_gate_shares) / len(cutoff_avg_amount_gate_shares), 4) if cutoff_avg_amount_gate_shares else None,
        "cutoff_avg_amount_share_of_min_gate_min": min(cutoff_avg_amount_gate_shares) if cutoff_avg_amount_gate_shares else None,
        "cutoff_avg_amount_share_of_min_gate_max": max(cutoff_avg_amount_gate_shares) if cutoff_avg_amount_gate_shares else None,
        "closest_case": {
            "trade_date": closest_case.get("trade_date"),
            "pre_truncation_rank": closest_case.get("pre_truncation_rank"),
            "pre_truncation_rank_gap_to_cutoff": closest_case.get("pre_truncation_rank_gap_to_cutoff"),
            "pre_truncation_avg_amount_share_of_cutoff": closest_case.get("pre_truncation_avg_amount_share_of_cutoff"),
            "pre_truncation_ranking_driver": closest_case.get("pre_truncation_ranking_driver"),
            "avg_amount_share_of_min_gate": closest_case.get("avg_amount_share_of_min_gate"),
            "pre_truncation_liquidity_gap_mode": closest_case.get("pre_truncation_liquidity_gap_mode"),
        },
    }


def _classify_truncation_handoff_priority(liquidity_gap_mode: str | None, ranking_driver: str | None) -> str:
    normalized_gap_mode = str(liquidity_gap_mode or "").strip()
    normalized_ranking_driver = str(ranking_driver or "").strip()
    if normalized_gap_mode == "barely_above_gate_and_far_below_cutoff":
        return "layer_a_liquidity_corridor"
    if normalized_gap_mode == "well_above_gate_but_far_below_cutoff":
        return "post_gate_liquidity_competition"
    if normalized_gap_mode == "moderate_gap_above_gate":
        return "post_gate_liquidity_gap_review"
    if normalized_gap_mode == "near_cutoff_liquidity_gap":
        return "top300_boundary_micro_tuning"
    if normalized_ranking_driver == "market_cap_tie_break_gap":
        return "cutoff_market_cap_tie_break"
    return "candidate_pool_truncation_unknown"


def _build_truncation_liquidity_profile(ticker: str, truncation_ranking_summary: dict[str, Any] | None) -> dict[str, Any] | None:
    summary = dict(truncation_ranking_summary or {})
    if not summary:
        return None

    dominant_liquidity_gap_mode = str(summary.get("dominant_liquidity_gap_mode") or "").strip() or None
    dominant_ranking_driver = str(summary.get("dominant_ranking_driver") or "").strip() or None
    priority_handoff = _classify_truncation_handoff_priority(dominant_liquidity_gap_mode, dominant_ranking_driver)
    profile_summary = "候选池截断画像仍需更多证据。"
    if dominant_liquidity_gap_mode == "barely_above_gate_and_far_below_cutoff":
        profile_summary = "这只票更多属于 gate 与 cutoff 之间的长尾流动性走廊，下一步应优先回查 Layer A 流动性 corridor，而不是先调 top300 边界。"
    elif dominant_liquidity_gap_mode == "well_above_gate_but_far_below_cutoff":
        profile_summary = "这只票已经显著高于最低流动性门槛，但仍持续输给 cutoff 竞争集，下一步应优先回查 post-gate liquidity competition。"
    elif dominant_liquidity_gap_mode == "moderate_gap_above_gate":
        profile_summary = "这只票属于中等 liquidity gap，仍需继续核对 cutoff 附近竞争强度与排序来源。"
    elif dominant_liquidity_gap_mode == "near_cutoff_liquidity_gap":
        profile_summary = "这只票更接近 cutoff 微边界，可保留为 top300 boundary 微调对照样本。"
    elif dominant_ranking_driver == "market_cap_tie_break_gap":
        profile_summary = "这只票的主差距更像 cutoff 附近市值 tie-break，而不是流动性 gate 本身。"

    return {
        "ticker": ticker,
        "truncation_case_count": summary.get("truncation_case_count"),
        "dominant_liquidity_gap_mode": dominant_liquidity_gap_mode,
        "dominant_ranking_driver": dominant_ranking_driver,
        "avg_amount_share_of_cutoff_mean": summary.get("avg_amount_share_of_cutoff_mean"),
        "avg_amount_share_of_min_gate_mean": summary.get("avg_amount_share_of_min_gate_mean"),
        "cutoff_avg_amount_share_of_min_gate_mean": summary.get("cutoff_avg_amount_share_of_min_gate_mean"),
        "min_rank_gap_to_cutoff": summary.get("min_rank_gap_to_cutoff"),
        "avg_rank_gap_to_cutoff": summary.get("avg_rank_gap_to_cutoff"),
        "priority_handoff": priority_handoff,
        "profile_summary": profile_summary,
        "closest_case": dict(summary.get("closest_case") or {}),
    }


def _build_focus_liquidity_profile_summary(priority_ticker_dossiers: list[dict[str, Any]]) -> dict[str, Any]:
    profiles = [dict(row.get("truncation_liquidity_profile") or {}) for row in priority_ticker_dossiers if dict(row.get("truncation_liquidity_profile") or {})]
    if not profiles:
        return {
            "profile_count": 0,
            "dominant_liquidity_gap_mode": None,
            "liquidity_gap_mode_counts": {},
            "priority_handoff_counts": {},
            "primary_focus_tickers": [],
        }

    liquidity_gap_mode_counts = Counter(str(row.get("dominant_liquidity_gap_mode") or "unknown") for row in profiles)
    priority_handoff_counts = Counter(str(row.get("priority_handoff") or "unknown") for row in profiles)
    dominant_liquidity_gap_mode = liquidity_gap_mode_counts.most_common(1)[0][0] if liquidity_gap_mode_counts else None
    ordered_profiles = sorted(
        profiles,
        key=lambda row: (
            0 if str(row.get("priority_handoff") or "") == "layer_a_liquidity_corridor" else 1,
            int(row.get("min_rank_gap_to_cutoff") or 10**9),
            str(row.get("ticker") or ""),
        ),
    )
    return {
        "profile_count": len(profiles),
        "dominant_liquidity_gap_mode": dominant_liquidity_gap_mode,
        "liquidity_gap_mode_counts": {key: int(value) for key, value in liquidity_gap_mode_counts.most_common()},
        "priority_handoff_counts": {key: int(value) for key, value in priority_handoff_counts.most_common()},
        "primary_focus_tickers": ordered_profiles[:5],
    }


def _describe_priority_handoff_branch(
    priority_handoff: str,
    *,
    tickers: list[str],
    avg_amount_share_of_cutoff_mean: float | None,
    avg_amount_share_of_min_gate_mean: float | None,
    min_rank_gap_to_cutoff: int | None,
) -> tuple[str, str]:
    ticker_label = "/".join(tickers) if tickers else "焦点票"
    if priority_handoff == "layer_a_liquidity_corridor":
        return (
            f"{ticker_label} 更像 Layer A 流动性走廊样本：虽然平均已达到最低门槛的 {avg_amount_share_of_min_gate_mean} 倍，但平均只达到 cutoff 的 {avg_amount_share_of_cutoff_mean}，且最近仍距 cutoff {min_rank_gap_to_cutoff} 名以上。",
            "优先把这条支路下钻到 gate 与 cutoff 之间的 liquidity corridor，核对 MIN_AVG_AMOUNT_20D 之上的长尾质量断层，而不是先扩大候选池上限。",
        )
    if priority_handoff == "post_gate_liquidity_competition":
        return (
            f"{ticker_label} 已明显通过最低流动性门槛，平均达到门槛的 {avg_amount_share_of_min_gate_mean} 倍，但平均仅达到 cutoff 的 {avg_amount_share_of_cutoff_mean}，说明主矛盾是过 gate 后仍输给 cutoff 竞争集。",
            "优先回查 post-gate liquidity competition：解释 cutoff 附近竞争集为何持续更强，而不是先下调 MIN_AVG_AMOUNT_20D。",
        )
    if priority_handoff == "post_gate_liquidity_gap_review":
        return (
            f"{ticker_label} 已过最低门槛但仍有中等 liquidity gap，当前更适合作为 post-gate gap review 样本。",
            "继续核对 cutoff 邻域竞争强度与过滤后排序来源，暂不直接调整池大小。",
        )
    if priority_handoff == "top300_boundary_micro_tuning":
        return (
            f"{ticker_label} 更接近 cutoff 微边界，当前可以保留为 top300 boundary micro-tuning 对照样本。",
            "优先保留 pre-truncation rank 观测，评估是否存在可控的 top300 微边界调参空间。",
        )
    if priority_handoff == "cutoff_market_cap_tie_break":
        return (
            f"{ticker_label} 的主差距更像 cutoff 附近的市值 tie-break，而不是流动性 gate 本身。",
            "优先回看 cutoff 邻域市值 tie-break 结构，不要把问题泛化成 liquidity gate。",
        )
    return (
        f"{ticker_label} 的截断证据仍偏混合，当前只能先归入待补证据分支。",
        "继续补 pre-truncation frontier 与排序来源观测，再决定上游修复方向。",
    )


def _build_priority_handoff_branch_diagnoses(priority_ticker_dossiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profiles = [dict(row.get("truncation_liquidity_profile") or {}) for row in priority_ticker_dossiers if dict(row.get("truncation_liquidity_profile") or {})]
    if not profiles:
        return []

    grouped_profiles: dict[str, list[dict[str, Any]]] = {}
    for profile in profiles:
        handoff = str(profile.get("priority_handoff") or "candidate_pool_truncation_unknown").strip() or "candidate_pool_truncation_unknown"
        grouped_profiles.setdefault(handoff, []).append(profile)

    handoff_priority_order = {
        "layer_a_liquidity_corridor": 0,
        "post_gate_liquidity_competition": 1,
        "post_gate_liquidity_gap_review": 2,
        "top300_boundary_micro_tuning": 3,
        "cutoff_market_cap_tie_break": 4,
        "candidate_pool_truncation_unknown": 5,
    }
    diagnoses: list[dict[str, Any]] = []
    for priority_handoff, branch_profiles in sorted(
        grouped_profiles.items(),
        key=lambda item: (
            handoff_priority_order.get(item[0], 99),
            min(int(row.get("min_rank_gap_to_cutoff") or 10**9) for row in item[1]),
            item[0],
        ),
    ):
        ordered_profiles = sorted(
            branch_profiles,
            key=lambda row: (int(row.get("min_rank_gap_to_cutoff") or 10**9), str(row.get("ticker") or "")),
        )
        tickers = [str(row.get("ticker") or "") for row in ordered_profiles if str(row.get("ticker") or "").strip()]
        avg_amount_share_of_cutoff_values = [_safe_float(row.get("avg_amount_share_of_cutoff_mean")) for row in ordered_profiles]
        avg_amount_share_of_cutoff_values = [value for value in avg_amount_share_of_cutoff_values if value is not None]
        avg_amount_share_of_min_gate_values = [_safe_float(row.get("avg_amount_share_of_min_gate_mean")) for row in ordered_profiles]
        avg_amount_share_of_min_gate_values = [value for value in avg_amount_share_of_min_gate_values if value is not None]
        min_rank_gaps = [int(row.get("min_rank_gap_to_cutoff") or 0) for row in ordered_profiles if row.get("min_rank_gap_to_cutoff") is not None]
        liquidity_gap_mode_counts = Counter(str(row.get("dominant_liquidity_gap_mode") or "unknown") for row in ordered_profiles)
        ranking_driver_counts = Counter(str(row.get("dominant_ranking_driver") or "unknown") for row in ordered_profiles)
        dominant_liquidity_gap_mode = liquidity_gap_mode_counts.most_common(1)[0][0] if liquidity_gap_mode_counts else None
        dominant_ranking_driver = ranking_driver_counts.most_common(1)[0][0] if ranking_driver_counts else None
        avg_amount_share_of_cutoff_mean = round(sum(avg_amount_share_of_cutoff_values) / len(avg_amount_share_of_cutoff_values), 4) if avg_amount_share_of_cutoff_values else None
        avg_amount_share_of_min_gate_mean = round(sum(avg_amount_share_of_min_gate_values) / len(avg_amount_share_of_min_gate_values), 4) if avg_amount_share_of_min_gate_values else None
        min_rank_gap_to_cutoff = min(min_rank_gaps) if min_rank_gaps else None
        diagnosis_summary, next_step = _describe_priority_handoff_branch(
            priority_handoff,
            tickers=tickers,
            avg_amount_share_of_cutoff_mean=avg_amount_share_of_cutoff_mean,
            avg_amount_share_of_min_gate_mean=avg_amount_share_of_min_gate_mean,
            min_rank_gap_to_cutoff=min_rank_gap_to_cutoff,
        )
        diagnoses.append(
            {
                "priority_handoff": priority_handoff,
                "ticker_count": len(ordered_profiles),
                "tickers": tickers,
                "dominant_liquidity_gap_mode": dominant_liquidity_gap_mode,
                "dominant_ranking_driver": dominant_ranking_driver,
                "avg_amount_share_of_cutoff_mean": avg_amount_share_of_cutoff_mean,
                "avg_amount_share_of_min_gate_mean": avg_amount_share_of_min_gate_mean,
                "min_rank_gap_to_cutoff": min_rank_gap_to_cutoff,
                "liquidity_gap_mode_counts": {key: int(value) for key, value in liquidity_gap_mode_counts.most_common()},
                "ranking_driver_counts": {key: int(value) for key, value in ranking_driver_counts.most_common()},
                "closest_focus_profile": dict(ordered_profiles[0]),
                "diagnosis_summary": diagnosis_summary,
                "next_step": next_step,
            }
        )
    return diagnoses


def _describe_pressure_peer_cluster(
    priority_handoff: str,
    *,
    occurrence_count: int,
    peer_avg_amount_multiple_mean: float | None,
    peer_market_cap_multiple_mean: float | None,
    lower_market_cap_higher_liquidity_peer_share: float | None,
    recurring_top5_peer_share: float | None,
) -> tuple[str, str]:
    if occurrence_count < 3 or peer_avg_amount_multiple_mean is None or peer_market_cap_multiple_mean is None:
        return "insufficient_branch_evidence", "当前分支还缺足够样本解释其压力同伴结构。"

    lower_cap_share_pct = round(float(lower_market_cap_higher_liquidity_peer_share or 0.0) * 100, 1)
    top5_share_pct = round(float(recurring_top5_peer_share or 0.0) * 100, 1)
    if priority_handoff == "layer_a_liquidity_corridor":
        if lower_cap_share_pct <= 10.0:
            return (
                "broad_large_cap_liquidity_wall",
                f"重复压力并不集中在单一 ticker 上，前五 recurring peer 只占 {top5_share_pct}% ，但 frontier peer 平均仍有约 {peer_avg_amount_multiple_mean} 倍成交额与 {peer_market_cap_multiple_mean} 倍市值，且只有 {lower_cap_share_pct}% 的 peer 在更小市值下还能压过候选，说明这条车道主要被一整层更大更活跃的 liquidity wall 持续压制。",
            )
        return (
            "mixed_liquidity_wall",
            f"这条走廊车道的重复压力来自一个分散但持续复现的对手簇，前五 recurring peer 占比约 {top5_share_pct}% ，frontier peer 平均仍有约 {peer_avg_amount_multiple_mean} 倍成交额与 {peer_market_cap_multiple_mean} 倍市值，说明它不是 top300 微边界，而是长期输给更强流动性俱乐部。",
        )
    if priority_handoff == "post_gate_liquidity_competition":
        if lower_cap_share_pct >= 10.0:
            return (
                "mixed_size_hot_peer_competition",
                f"这条车道的竞争压力不是单纯大市值压制：前五 recurring peer 占比约 {top5_share_pct}% ，frontier peer 平均仍有约 {peer_avg_amount_multiple_mean} 倍成交额，但已有 {lower_cap_share_pct}% 的 peer 在更小市值下仍具备更高流动性，说明主问题是 post-gate 竞争集里混有更轻更热的对手。",
            )
        return (
            "large_cap_post_gate_competition",
            f"这条车道的竞争压力主要来自一组更大更活跃的 cutoff 同伴，前五 recurring peer 占比约 {top5_share_pct}% ，frontier peer 平均仍有约 {peer_avg_amount_multiple_mean} 倍成交额与 {peer_market_cap_multiple_mean} 倍市值，因此下一步应优先重审 post-gate 竞争构成，而不是下调 gate。",
        )
    return (
        "generic_pressure_cluster",
        f"当前分支的 recurring peer 前五占比约 {top5_share_pct}% ，frontier peer 平均仍有约 {peer_avg_amount_multiple_mean} 倍成交额与 {peer_market_cap_multiple_mean} 倍市值，说明截断压力已具备稳定的重复对手结构。",
    )


def _describe_branch_repair_hypothesis(
    priority_handoff: str,
    *,
    nearest_frontier_peer_amount_multiple_mean: float | None,
    nearest_frontier_peer_amount_multiple_min: float | None,
    lower_market_cap_higher_liquidity_peer_share: float | None,
    top_lower_market_cap_hot_peers: list[dict[str, Any]],
    top_larger_market_cap_wall_peers: list[dict[str, Any]],
) -> tuple[str, str]:
    if nearest_frontier_peer_amount_multiple_mean is None:
        return "insufficient_repair_evidence", "当前分支还缺足够样本支撑修复假设。"

    lower_cap_hot_peer_labels = [str(row.get("ticker") or "") for row in top_lower_market_cap_hot_peers[:3] if str(row.get("ticker") or "").strip()]
    larger_cap_wall_peer_labels = [str(row.get("ticker") or "") for row in top_larger_market_cap_wall_peers[:3] if str(row.get("ticker") or "").strip()]
    lower_cap_share_pct = round(float(lower_market_cap_higher_liquidity_peer_share or 0.0) * 100, 1)
    if priority_handoff == "layer_a_liquidity_corridor":
        return (
            "raise_base_liquidity_before_cutoff_tuning",
            f"要脱离当前 corridor 并摸到最近 frontier peer，候选平均仍需把 20 日成交额抬到当前的 {nearest_frontier_peer_amount_multiple_mean} 倍，最轻样本也还要 {nearest_frontier_peer_amount_multiple_min} 倍；主压力同伴仍是 {larger_cap_wall_peer_labels or ['larger-cap liquidity wall']}，因此下一步应优先寻找能系统性抬升基础流动性的 upstream entry，而不是继续讨论 cutoff 微调。",
        )
    if priority_handoff == "post_gate_liquidity_competition":
        if lower_cap_share_pct >= 10.0:
            return (
                "rebucket_mixed_size_hot_competitors",
                f"这条车道距离最近 frontier peer 的成交额差距均值已收敛到 {nearest_frontier_peer_amount_multiple_mean} 倍，但 recurring 对手里仍持续混有 {lower_cap_share_pct}% 的更小市值高流动性 peer，例如 {lower_cap_hot_peer_labels or ['smaller-cap hot peers']}；下一步应优先验证 post-gate competition composition 拆桶或选择性豁免，而不是下调 gate。",
            )
        return (
            "review_large_cap_competition_set",
            f"这条车道距离最近 frontier peer 的成交额差距均值约为 {nearest_frontier_peer_amount_multiple_mean} 倍，主压力仍来自 {larger_cap_wall_peer_labels or ['larger-cap peers']} 这类更大更活跃的 cutoff 同伴，因此下一步应先重审 post-gate competition set。",
        )
    return (
        "generic_branch_repair_hypothesis",
        f"当前分支距离最近 frontier peer 的成交额差距均值约为 {nearest_frontier_peer_amount_multiple_mean} 倍，可继续围绕 recurring peer 结构做定向修复实验。",
    )


def _describe_branch_experiment_prototype(
    mechanism: dict[str, Any],
) -> tuple[str, str, str, str]:
    priority_handoff = str(mechanism.get("priority_handoff") or "").strip()
    tickers = [str(value) for value in list(mechanism.get("tickers") or []) if str(value or "").strip()]
    ticker_label = "/".join(tickers) if tickers else "该分支"
    avg_amount_share_of_cutoff_mean = mechanism.get("avg_amount_share_of_cutoff_mean")
    avg_amount_share_of_min_gate_mean = _safe_float(mechanism.get("avg_amount_share_of_min_gate_mean"))
    nearest_frontier_peer_amount_multiple_mean = mechanism.get("nearest_frontier_peer_amount_multiple_mean")
    nearest_frontier_peer_amount_multiple_min = mechanism.get("nearest_frontier_peer_amount_multiple_min")
    lower_market_cap_higher_liquidity_peer_share = _safe_float(mechanism.get("lower_market_cap_higher_liquidity_peer_share"))
    pressure_peer_cluster_type = str(mechanism.get("pressure_peer_cluster_type") or "").strip() or "generic_pressure_cluster"
    top_lower_market_cap_hot_peers = [
        str(row.get("ticker") or "")
        for row in list(mechanism.get("top_lower_market_cap_hot_peers") or [])[:3]
        if str(row.get("ticker") or "").strip()
    ]

    if priority_handoff == "layer_a_liquidity_corridor":
        low_gate_focus_clause = ""
        low_gate_guardrail_clause = ""
        if avg_amount_share_of_min_gate_mean is not None and SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE <= avg_amount_share_of_min_gate_mean < SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE:
            low_gate_focus_clause = (
                f" 对低于 {SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE}x 最低流动性门槛的 focus 子样本，"
                f"先用 tighter cutoff split（avg_amount/cutoff <= {SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE}）隔离 deepest corridor，再观察是否值得继续保留。"
            )
            low_gate_guardrail_clause = (
                f" 对 low-gate focus 子样本，只有 avg_amount/cutoff 仍不高于 {SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE} 时才允许进入 shadow；"
                "不得把更厚的 low-gate tail 一起带入 corridor focus。"
            )
        return (
            "upstream_base_liquidity_uplift_probe",
            f"先把 {ticker_label} 收敛到 upstream base-liquidity uplift shadow probe，只验证能否把基础流动性从当前 corridor 系统性抬升，不提前讨论 cutoff 微调。{low_gate_focus_clause}",
            f"若 nearest frontier multiple 能持续从当前均值 {nearest_frontier_peer_amount_multiple_mean} 倍压向当前最轻样本 {nearest_frontier_peer_amount_multiple_min} 倍，且 avg_amount_share_of_cutoff 明显高于当前 {avg_amount_share_of_cutoff_mean}，再进入 cutoff tuning 讨论。",
            f"仅限 {pressure_peer_cluster_type} 车道；若 larger-cap liquidity wall 仍主导，就不得把这条 lane 改写成 top300 boundary 微调。{low_gate_guardrail_clause}",
        )
    if priority_handoff == "post_gate_liquidity_competition":
        lower_cap_share_pct = round(float(lower_market_cap_higher_liquidity_peer_share or 0.0) * 100, 1)
        return (
            "post_gate_competition_rebucket_probe",
            f"先把 {ticker_label} 放入 post-gate competition rebucket shadow probe，只验证 mixed-size hot peer 分桶后是否能缩小 cutoff 竞争压力，不调整 liquidity gate。",
            f"若更小市值高流动性 peer 占比能从当前 {lower_cap_share_pct}% 收敛，且 nearest frontier multiple 继续低于当前 {nearest_frontier_peer_amount_multiple_mean} 倍，再考虑 selective exemption；当前先盯 {top_lower_market_cap_hot_peers or ['smaller-cap hot peers']}。",
            "仅限存在 recurring smaller-cap hot peers 的 post-gate competition 车道；不得直接下调 MIN_AVG_AMOUNT_20D。",
        )
    if priority_handoff == "top300_boundary_micro_tuning":
        return (
            "top300_boundary_shadow_tuning_probe",
            f"把 {ticker_label} 保留为 top300 boundary shadow tuning 对照样本，只验证 cutoff 附近的微边界弹性，不与 far-below-cutoff 车道混用。",
            f"若 min_rank_gap_to_cutoff 持续维持在当前近边界水平，且 nearest frontier multiple 保持在 {nearest_frontier_peer_amount_multiple_mean} 倍附近，再评估是否值得做微调。",
            "仅限 top300 boundary micro-tuning 分支；不得把该样本外推成 corridor 或 competition lane 的修复规则。",
        )
    return (
        "generic_branch_shadow_probe",
        f"把 {ticker_label} 保留为 branch-specific shadow probe，先继续积累 recurring peer 证据，再决定是否进入更明确的 repair lane。",
        f"若 nearest frontier multiple 稳定低于当前 {nearest_frontier_peer_amount_multiple_mean} 倍，并形成更稳定的 peer 结构，再升级实验语义。",
        "仅限当前 branch 内部观察；不得跨 branch 直接复用规则。",
    )


def _build_priority_handoff_branch_experiment_queue(
    priority_handoff_branch_mechanisms: list[dict[str, Any]],
    priority_ticker_dossiers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    priority_order = {
        "layer_a_liquidity_corridor": 1,
        "post_gate_liquidity_competition": 2,
        "post_gate_liquidity_gap_review": 3,
        "top300_boundary_micro_tuning": 4,
        "cutoff_market_cap_tie_break": 5,
        "candidate_pool_truncation_unknown": 6,
    }
    grouped_occurrences: dict[str, list[dict[str, Any]]] = {}
    for dossier in list(priority_ticker_dossiers or []):
        profile = dict(dossier.get("truncation_liquidity_profile") or {})
        priority_handoff = str(profile.get("priority_handoff") or "").strip()
        if not priority_handoff:
            continue
        grouped_occurrences.setdefault(priority_handoff, []).extend(
            [
                dict(row)
                for row in list(dossier.get("occurrence_evidence") or [])
                if str(row.get("blocking_stage") or "") == "candidate_pool_truncated_after_filters"
            ]
        )
    queue: list[dict[str, Any]] = []
    for mechanism in list(priority_handoff_branch_mechanisms or []):
        normalized = dict(mechanism or {})
        priority_handoff = str(normalized.get("priority_handoff") or "").strip()
        if not priority_handoff:
            continue
        prototype_type, prototype_summary, success_signal, guardrail_summary = _describe_branch_experiment_prototype(normalized)
        occurrences = list(grouped_occurrences.get(priority_handoff) or [])
        uplift_to_cutoff_multiples = [
            round(1.0 / float(value), 4)
            for value in [_safe_float(row.get("pre_truncation_avg_amount_share_of_cutoff")) for row in occurrences]
            if value is not None and value > 0
        ]
        cutoff_targets = [
            float(value)
            for value in [_safe_float(row.get("pre_truncation_cutoff_avg_amount_20d")) for row in occurrences]
            if value is not None
        ]
        lower_cap_hot_peer_counts = [
            int(value)
            for value in [row.get("top300_lower_market_cap_hot_peer_count") for row in occurrences]
            if value is not None
        ]
        rebucket_rank_gaps = [
            int(value)
            for value in [row.get("estimated_rank_gap_after_rebucket") for row in occurrences]
            if value is not None
        ]
        uplift_to_cutoff_multiple_mean = round(sum(uplift_to_cutoff_multiples) / len(uplift_to_cutoff_multiples), 4) if uplift_to_cutoff_multiples else None
        uplift_to_cutoff_multiple_min = min(uplift_to_cutoff_multiples) if uplift_to_cutoff_multiples else None
        uplift_to_cutoff_multiple_max = max(uplift_to_cutoff_multiples) if uplift_to_cutoff_multiples else None
        target_cutoff_avg_amount_20d_mean = round(sum(cutoff_targets) / len(cutoff_targets), 4) if cutoff_targets else None
        top300_lower_market_cap_hot_peer_count_mean = round(sum(lower_cap_hot_peer_counts) / len(lower_cap_hot_peer_counts), 4) if lower_cap_hot_peer_counts else None
        lower_cap_hot_peer_case_share = round(sum(1 for value in lower_cap_hot_peer_counts if value > 0) / len(lower_cap_hot_peer_counts), 4) if lower_cap_hot_peer_counts else None
        estimated_rank_gap_after_rebucket_mean = round(sum(rebucket_rank_gaps) / len(rebucket_rank_gaps), 4) if rebucket_rank_gaps else None
        prototype_readiness = "research_only"
        evaluation_summary = "当前 prototype 还缺足够 occurrence 证据，暂不进入 execution-ready 讨论。"
        if priority_handoff == "layer_a_liquidity_corridor" and uplift_to_cutoff_multiple_mean is not None:
            prototype_readiness = "shadow_ready_large_gap" if uplift_to_cutoff_multiple_mean >= 3.0 else "shadow_ready_boundary_gap"
            evaluation_summary = (
                f"按当前 top300 cutoff 成交额口径，{priority_handoff} 分支平均需要把 20 日成交额抬到当前的 {uplift_to_cutoff_multiple_mean} 倍，"
                f"目标 cutoff 成交额均值约为 {target_cutoff_avg_amount_20d_mean}；因此现阶段更适合先做 upstream uplift shadow probe，而不是直接讨论 pool-size 或 cutoff 微调。"
            )
            avg_amount_share_of_min_gate_mean = _safe_float(normalized.get("avg_amount_share_of_min_gate_mean"))
            if avg_amount_share_of_min_gate_mean is not None and SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE <= avg_amount_share_of_min_gate_mean < SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE:
                evaluation_summary = (
                    f"{evaluation_summary} 其中 low-gate corridor focus 子样本应先走 tighter cutoff split："
                    f"只有 avg_amount/cutoff 不高于 {SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE} 的 deepest corridor 样本才继续保留，"
                    "避免把更厚的低门槛长尾一起放进 shadow probe。"
                )
        elif priority_handoff == "post_gate_liquidity_competition" and uplift_to_cutoff_multiple_mean is not None:
            prototype_readiness = "shadow_ready_rebucket_signal" if lower_cap_hot_peer_case_share and lower_cap_hot_peer_case_share > 0 else "shadow_ready_without_rebucket_signal"
            if top300_lower_market_cap_hot_peer_count_mean is not None and estimated_rank_gap_after_rebucket_mean is not None:
                evaluation_summary = (
                    f"按当前 top300 cutoff 口径，{priority_handoff} 分支平均仍需 {uplift_to_cutoff_multiple_mean} 倍成交额才能贴近 cutoff，"
                    f"但 top300 中平均约有 {top300_lower_market_cap_hot_peer_count_mean} 个更小市值高流动性 peer 挡在前面，"
                    f"若做 rebucket，估算 rank gap 均值可收敛到 {estimated_rank_gap_after_rebucket_mean}。"
                )
            else:
                evaluation_summary = (
                    f"按当前 top300 cutoff 口径，{priority_handoff} 分支平均仍需 {uplift_to_cutoff_multiple_mean} 倍成交额才能贴近 cutoff，"
                    "但当前还缺稳定的 top300 smaller-cap hot-peer 计数，暂时只宜保持 shadow probe。"
                )
        queue.append(
            {
                "task_id": f"{priority_handoff}_{prototype_type}",
                "priority_rank": int(priority_order.get(priority_handoff, 99)),
                "priority_handoff": priority_handoff,
                "tickers": list(normalized.get("tickers") or []),
                "repair_hypothesis_type": normalized.get("repair_hypothesis_type"),
                "prototype_type": prototype_type,
                "prototype_readiness": prototype_readiness,
                "uplift_to_cutoff_multiple_mean": uplift_to_cutoff_multiple_mean,
                "uplift_to_cutoff_multiple_min": uplift_to_cutoff_multiple_min,
                "uplift_to_cutoff_multiple_max": uplift_to_cutoff_multiple_max,
                "target_cutoff_avg_amount_20d_mean": target_cutoff_avg_amount_20d_mean,
                "top300_lower_market_cap_hot_peer_count_mean": top300_lower_market_cap_hot_peer_count_mean,
                "lower_cap_hot_peer_case_share": lower_cap_hot_peer_case_share,
                "estimated_rank_gap_after_rebucket_mean": estimated_rank_gap_after_rebucket_mean,
                "prototype_summary": prototype_summary,
                "success_signal": success_signal,
                "guardrail_summary": guardrail_summary,
                "evaluation_summary": evaluation_summary,
                "why_now": str(normalized.get("repair_hypothesis_summary") or normalized.get("mechanism_summary") or "").strip(),
            }
        )
    return sorted(queue, key=lambda row: (int(row.get("priority_rank") or 99), str(row.get("task_id") or "")))


def _build_priority_handoff_branch_mechanisms(priority_ticker_dossiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profiles_by_ticker = {
        str(row.get("ticker") or ""): dict(row.get("truncation_liquidity_profile") or {})
        for row in priority_ticker_dossiers
        if str(row.get("ticker") or "").strip() and dict(row.get("truncation_liquidity_profile") or {})
    }
    grouped_occurrences: dict[str, list[dict[str, Any]]] = {}
    grouped_tickers: dict[str, set[str]] = {}
    for dossier in priority_ticker_dossiers:
        ticker = str(dossier.get("ticker") or "").strip()
        profile = profiles_by_ticker.get(ticker) or {}
        priority_handoff = str(profile.get("priority_handoff") or "").strip()
        if not ticker or not priority_handoff:
            continue
        truncation_occurrences = [
            {**dict(row), "ticker": ticker}
            for row in list(dossier.get("occurrence_evidence") or [])
            if str(row.get("blocking_stage") or "") == "candidate_pool_truncated_after_filters"
        ]
        if not truncation_occurrences:
            continue
        grouped_occurrences.setdefault(priority_handoff, []).extend(truncation_occurrences)
        grouped_tickers.setdefault(priority_handoff, set()).add(ticker)

    if not grouped_occurrences:
        return []

    handoff_priority_order = {
        "layer_a_liquidity_corridor": 0,
        "post_gate_liquidity_competition": 1,
        "post_gate_liquidity_gap_review": 2,
        "top300_boundary_micro_tuning": 3,
        "cutoff_market_cap_tie_break": 4,
        "candidate_pool_truncation_unknown": 5,
    }
    mechanisms: list[dict[str, Any]] = []
    for priority_handoff, occurrences in sorted(grouped_occurrences.items(), key=lambda item: (handoff_priority_order.get(item[0], 99), item[0])):
        tickers = sorted(grouped_tickers.get(priority_handoff) or set())
        avg_amount_share_values = [_safe_float(row.get("pre_truncation_avg_amount_share_of_cutoff")) for row in occurrences]
        avg_amount_share_values = [value for value in avg_amount_share_values if value is not None and value > 0]
        avg_amount_gap_values = [_safe_float(row.get("pre_truncation_avg_amount_gap_to_cutoff")) for row in occurrences]
        avg_amount_gap_values = [value for value in avg_amount_gap_values if value is not None]
        gate_share_values = [_safe_float(row.get("avg_amount_share_of_min_gate")) for row in occurrences]
        gate_share_values = [value for value in gate_share_values if value is not None]
        cutoff_gate_share_values = [_safe_float(row.get("pre_truncation_cutoff_avg_amount_share_of_min_gate")) for row in occurrences]
        cutoff_gate_share_values = [value for value in cutoff_gate_share_values if value is not None]
        rank_gap_values = [int(row.get("pre_truncation_rank_gap_to_cutoff") or 0) for row in occurrences if row.get("pre_truncation_rank_gap_to_cutoff") is not None]
        cutoff_ticker_counts = Counter(str(row.get("pre_truncation_cutoff_ticker") or "unknown") for row in occurrences if str(row.get("pre_truncation_cutoff_ticker") or "").strip())
        frontier_peer_counts: Counter[str] = Counter()
        lower_market_cap_hot_peer_counts: Counter[str] = Counter()
        larger_market_cap_wall_peer_counts: Counter[str] = Counter()
        peer_avg_amount_multiple_values: list[float] = []
        peer_market_cap_multiple_values: list[float] = []
        lower_market_cap_higher_liquidity_peer_count = 0
        peer_observation_count = 0
        cutoff_lower_market_cap_count = 0
        cutoff_market_cap_observation_count = 0
        nearest_frontier_peer_amount_multiples: list[float] = []
        for row in occurrences:
            current_ticker = str(row.get("ticker") or "").strip()
            candidate_avg_amount = _safe_float(row.get("avg_amount_20d"))
            candidate_market_cap = _safe_float(row.get("market_cap"))
            cutoff_market_cap = _safe_float(row.get("pre_truncation_cutoff_market_cap"))
            if candidate_market_cap is not None and candidate_market_cap > 0 and cutoff_market_cap is not None:
                cutoff_market_cap_observation_count += 1
                if cutoff_market_cap <= candidate_market_cap:
                    cutoff_lower_market_cap_count += 1
            frontier_window = [dict(item) for item in list(row.get("pre_truncation_frontier_window") or [])]
            frontier_row_multiples: list[float] = []
            for peer in frontier_window:
                peer_ticker = str(peer.get("ticker") or "").strip()
                if not peer_ticker or peer_ticker == current_ticker:
                    continue
                frontier_peer_counts[peer_ticker] += 1
                peer_observation_count += 1
                peer_avg_amount = _safe_float(peer.get("avg_amount_20d"))
                peer_market_cap = _safe_float(peer.get("market_cap"))
                if candidate_avg_amount is not None and candidate_avg_amount > 0 and peer_avg_amount is not None:
                    peer_amount_multiple = round(peer_avg_amount / candidate_avg_amount, 4)
                    peer_avg_amount_multiple_values.append(peer_amount_multiple)
                    frontier_row_multiples.append(peer_amount_multiple)
                if candidate_market_cap is not None and candidate_market_cap > 0 and peer_market_cap is not None:
                    peer_market_cap_multiple_values.append(round(peer_market_cap / candidate_market_cap, 4))
                    if peer_market_cap <= candidate_market_cap and peer_avg_amount is not None and candidate_avg_amount is not None and peer_avg_amount > candidate_avg_amount:
                        lower_market_cap_higher_liquidity_peer_count += 1
                        lower_market_cap_hot_peer_counts[peer_ticker] += 1
                    elif peer_avg_amount is not None and candidate_avg_amount is not None and peer_avg_amount > candidate_avg_amount:
                        larger_market_cap_wall_peer_counts[peer_ticker] += 1
            if frontier_row_multiples:
                nearest_frontier_peer_amount_multiples.append(min(frontier_row_multiples))
        liquidity_multiple_values = [round(1.0 / value, 4) for value in avg_amount_share_values if value > 0]
        representative_cases = sorted(
            [
                {
                    "ticker": str(row.get("ticker") or "").strip(),
                    "trade_date": row.get("trade_date"),
                    "pre_truncation_rank": row.get("pre_truncation_rank"),
                    "pre_truncation_rank_gap_to_cutoff": row.get("pre_truncation_rank_gap_to_cutoff"),
                    "pre_truncation_avg_amount_share_of_cutoff": row.get("pre_truncation_avg_amount_share_of_cutoff"),
                    "avg_amount_share_of_min_gate": row.get("avg_amount_share_of_min_gate"),
                    "pre_truncation_cutoff_ticker": row.get("pre_truncation_cutoff_ticker"),
                    "pre_truncation_ranking_driver": row.get("pre_truncation_ranking_driver"),
                }
                for row in occurrences
            ],
            key=lambda row: (
                int(row.get("pre_truncation_rank_gap_to_cutoff") or 10**9),
                str(row.get("ticker") or ""),
                str(row.get("trade_date") or ""),
            ),
        )[:5]
        avg_amount_share_of_cutoff_mean = round(sum(avg_amount_share_values) / len(avg_amount_share_values), 4) if avg_amount_share_values else None
        avg_amount_gap_to_cutoff_mean = round(sum(avg_amount_gap_values) / len(avg_amount_gap_values), 4) if avg_amount_gap_values else None
        avg_amount_share_of_min_gate_mean = round(sum(gate_share_values) / len(gate_share_values), 4) if gate_share_values else None
        cutoff_avg_amount_share_of_min_gate_mean = round(sum(cutoff_gate_share_values) / len(cutoff_gate_share_values), 4) if cutoff_gate_share_values else None
        cutoff_to_candidate_liquidity_multiple_mean = round(sum(liquidity_multiple_values) / len(liquidity_multiple_values), 4) if liquidity_multiple_values else None
        min_rank_gap_to_cutoff = min(rank_gap_values) if rank_gap_values else None
        peer_avg_amount_multiple_mean = round(sum(peer_avg_amount_multiple_values) / len(peer_avg_amount_multiple_values), 4) if peer_avg_amount_multiple_values else None
        peer_market_cap_multiple_mean = round(sum(peer_market_cap_multiple_values) / len(peer_market_cap_multiple_values), 4) if peer_market_cap_multiple_values else None
        nearest_frontier_peer_amount_multiple_mean = round(sum(nearest_frontier_peer_amount_multiples) / len(nearest_frontier_peer_amount_multiples), 4) if nearest_frontier_peer_amount_multiples else None
        nearest_frontier_peer_amount_multiple_min = round(min(nearest_frontier_peer_amount_multiples), 4) if nearest_frontier_peer_amount_multiples else None
        nearest_frontier_peer_amount_multiple_median = round(sorted(nearest_frontier_peer_amount_multiples)[len(nearest_frontier_peer_amount_multiples) // 2], 4) if nearest_frontier_peer_amount_multiples else None
        lower_market_cap_higher_liquidity_peer_share = round(lower_market_cap_higher_liquidity_peer_count / peer_observation_count, 4) if peer_observation_count else None
        cutoff_lower_market_cap_share = round(cutoff_lower_market_cap_count / cutoff_market_cap_observation_count, 4) if cutoff_market_cap_observation_count else None
        recurring_top5_peer_share = round(sum(value for _, value in frontier_peer_counts.most_common(5)) / peer_observation_count, 4) if peer_observation_count else None
        pressure_peer_cluster_type, pressure_cluster_summary = _describe_pressure_peer_cluster(
            priority_handoff,
            occurrence_count=len(occurrences),
            peer_avg_amount_multiple_mean=peer_avg_amount_multiple_mean,
            peer_market_cap_multiple_mean=peer_market_cap_multiple_mean,
            lower_market_cap_higher_liquidity_peer_share=lower_market_cap_higher_liquidity_peer_share,
            recurring_top5_peer_share=recurring_top5_peer_share,
        )
        top_lower_market_cap_hot_peers = [{"ticker": key, "count": int(value)} for key, value in lower_market_cap_hot_peer_counts.most_common(5)]
        top_larger_market_cap_wall_peers = [{"ticker": key, "count": int(value)} for key, value in larger_market_cap_wall_peer_counts.most_common(5)]
        repair_hypothesis_type, repair_hypothesis_summary = _describe_branch_repair_hypothesis(
            priority_handoff,
            nearest_frontier_peer_amount_multiple_mean=nearest_frontier_peer_amount_multiple_mean,
            nearest_frontier_peer_amount_multiple_min=nearest_frontier_peer_amount_multiple_min,
            lower_market_cap_higher_liquidity_peer_share=lower_market_cap_higher_liquidity_peer_share,
            top_lower_market_cap_hot_peers=top_lower_market_cap_hot_peers,
            top_larger_market_cap_wall_peers=top_larger_market_cap_wall_peers,
        )
        mechanism_summary = "当前分支还缺足够样本解释其截断机制。"
        if priority_handoff == "layer_a_liquidity_corridor":
            mechanism_summary = (
                f"{tickers} 在通过最低流动性门槛后，平均仍只达到 cutoff 成交额的 {avg_amount_share_of_cutoff_mean}，"
                f"对应 cutoff 对候选的流动性压力倍数约为 {cutoff_to_candidate_liquidity_multiple_mean} 倍，说明主问题是 gate 以上到 cutoff 以下的长尾走廊。"
            )
        elif priority_handoff == "post_gate_liquidity_competition":
            mechanism_summary = (
                f"{tickers} 已明显过 gate，但 cutoff 竞争者平均仍有约 {cutoff_to_candidate_liquidity_multiple_mean} 倍流动性优势，"
                f"且最近仍差 {min_rank_gap_to_cutoff} 名，说明主问题是过 gate 后的竞争集压力，而不是 gate 本身。"
            )
        mechanisms.append(
            {
                "priority_handoff": priority_handoff,
                "ticker_count": len(tickers),
                "tickers": tickers,
                "occurrence_count": len(occurrences),
                "avg_amount_share_of_cutoff_mean": avg_amount_share_of_cutoff_mean,
                "avg_amount_gap_to_cutoff_mean": avg_amount_gap_to_cutoff_mean,
                "avg_amount_share_of_min_gate_mean": avg_amount_share_of_min_gate_mean,
                "cutoff_avg_amount_share_of_min_gate_mean": cutoff_avg_amount_share_of_min_gate_mean,
                "cutoff_to_candidate_liquidity_multiple_mean": cutoff_to_candidate_liquidity_multiple_mean,
                "min_rank_gap_to_cutoff": min_rank_gap_to_cutoff,
                "peer_avg_amount_multiple_mean": peer_avg_amount_multiple_mean,
                "peer_market_cap_multiple_mean": peer_market_cap_multiple_mean,
                "nearest_frontier_peer_amount_multiple_mean": nearest_frontier_peer_amount_multiple_mean,
                "nearest_frontier_peer_amount_multiple_min": nearest_frontier_peer_amount_multiple_min,
                "nearest_frontier_peer_amount_multiple_median": nearest_frontier_peer_amount_multiple_median,
                "lower_market_cap_higher_liquidity_peer_share": lower_market_cap_higher_liquidity_peer_share,
                "cutoff_lower_market_cap_share": cutoff_lower_market_cap_share,
                "recurring_top5_peer_share": recurring_top5_peer_share,
                "pressure_peer_cluster_type": pressure_peer_cluster_type,
                "top_cutoff_tickers": [{"ticker": key, "count": int(value)} for key, value in cutoff_ticker_counts.most_common(5)],
                "top_frontier_peers": [{"ticker": key, "count": int(value)} for key, value in frontier_peer_counts.most_common(5)],
                "top_lower_market_cap_hot_peers": top_lower_market_cap_hot_peers,
                "top_larger_market_cap_wall_peers": top_larger_market_cap_wall_peers,
                "representative_cases": representative_cases,
                "mechanism_summary": mechanism_summary,
                "pressure_cluster_summary": pressure_cluster_summary,
                "repair_hypothesis_type": repair_hypothesis_type,
                "repair_hypothesis_summary": repair_hypothesis_summary,
            }
        )
    return mechanisms


def _build_pre_truncation_frontier_context(
    trade_date: str,
    *,
    stock_basic_universe: pd.DataFrame,
    trade_date_context: dict[str, Any],
    pro: Any,
    frontier_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    compact_trade_date = _compact_trade_date(trade_date)
    cached = frontier_cache.get(compact_trade_date)
    if cached is not None:
        return cached

    if stock_basic_universe.empty or pro is None:
        cached = {
            "status": "missing_market_context",
            "pre_truncation_total_candidates": 0,
            "pre_truncation_cutoff_rank": None,
            "cutoff_row": None,
            "frontier_window": [],
            "ranking_by_ticker": {},
        }
        frontier_cache[compact_trade_date] = cached
        return cached

    working_df = stock_basic_universe.copy()
    mask_st = working_df["name"].astype(str).str.contains("ST", case=False, na=False)
    working_df = working_df[~mask_st].copy()

    mask_bj = build_beijing_exchange_mask(working_df)
    working_df = working_df[~mask_bj].copy()

    mask_new = working_df["list_date"].apply(lambda value: _estimate_trading_days(_compact_trade_date(str(value or "")), compact_trade_date) < MIN_LISTING_DAYS)
    working_df = working_df[~mask_new].copy()

    suspend_codes = set(trade_date_context.get("suspend_codes") or set())
    if suspend_codes:
        working_df = working_df[~working_df["ts_code"].astype(str).isin(suspend_codes)].copy()

    limit_up_codes = set(trade_date_context.get("limit_up_codes") or set())
    if limit_up_codes:
        working_df = working_df[~working_df["ts_code"].astype(str).isin(limit_up_codes)].copy()

    cooldown_tickers = set(trade_date_context.get("cooldown_tickers") or set())
    if cooldown_tickers:
        working_df = working_df[~working_df["symbol"].astype(str).isin(cooldown_tickers)].copy()

    daily_basic_by_ts = dict(trade_date_context.get("daily_basic_by_ts") or {})
    estimated_amount_map: dict[str, float] = {}
    market_cap_map: dict[str, float] = {}
    for ts_code, row in daily_basic_by_ts.items():
        row_series = pd.Series(row)
        estimated_amount_map[str(ts_code)] = float(_estimate_amount_from_daily_basic(row_series))
        total_mv = _safe_float(row.get("total_mv"))
        if total_mv is not None:
            market_cap_map[str(ts_code)] = total_mv / 10000.0

    if estimated_amount_map:
        low_estimated_codes = {
            ts_code
            for ts_code in working_df["ts_code"].astype(str).tolist()
            if 0.0 < float(estimated_amount_map.get(ts_code, 0.0)) < MIN_ESTIMATED_AMOUNT_1D
        }
        if low_estimated_codes:
            working_df = working_df[~working_df["ts_code"].astype(str).isin(low_estimated_codes)].copy()

    remaining_codes = working_df["ts_code"].astype(str).tolist()
    amount_map = _get_avg_amount_20d_map(pro, remaining_codes, compact_trade_date) if remaining_codes else {}
    if amount_map is None:
        amount_map = {}

    ranking_rows: list[dict[str, Any]] = []
    for _, row in working_df.iterrows():
        ts_code = str(row.get("ts_code") or "").strip()
        ticker = str(row.get("symbol") or "").strip()
        if not ts_code or not ticker:
            continue
        avg_amount_20d = round(float(amount_map.get(ts_code, 0.0)), 4)
        if avg_amount_20d < MIN_AVG_AMOUNT_20D:
            continue
        ranking_rows.append(
            {
                "rank": 0,
                "ticker": ticker,
                "ts_code": ts_code,
                "name": str(row.get("name") or "").strip() or None,
                "avg_amount_20d": avg_amount_20d,
                "market_cap": round(float(market_cap_map.get(ts_code, 0.0)), 4),
            }
        )

    ranking_rows.sort(key=lambda row: (float(row.get("avg_amount_20d") or 0.0), float(row.get("market_cap") or 0.0)), reverse=True)
    ranking_by_ticker: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(ranking_rows, start=1):
        row["rank"] = index
        ranking_by_ticker[str(row.get("ticker") or "")] = dict(row)

    cutoff_rank = min(MAX_CANDIDATE_POOL_SIZE, len(ranking_rows)) if ranking_rows else None
    cutoff_row = dict(ranking_rows[cutoff_rank - 1]) if cutoff_rank else None
    frontier_window = _build_frontier_window(ranking_rows, center_rank=cutoff_rank)

    cached = {
        "status": "ready",
        "pre_truncation_total_candidates": len(ranking_rows),
        "pre_truncation_cutoff_rank": cutoff_rank,
        "cutoff_row": cutoff_row,
        "frontier_window": frontier_window,
        "ranking_by_ticker": ranking_by_ticker,
    }
    frontier_cache[compact_trade_date] = cached
    return cached


def _build_trade_date_context(
    trade_date: str,
    *,
    snapshots_root: Path,
    snapshot_cache: dict[str, dict[str, Any]],
    context_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    compact_trade_date = _compact_trade_date(trade_date)
    cached = context_cache.get(compact_trade_date)
    if cached is not None:
        return cached

    suspend_df = get_suspend_list(compact_trade_date)
    suspend_codes = set(suspend_df["ts_code"].astype(str).tolist()) if suspend_df is not None and not suspend_df.empty else set()

    limit_df = get_limit_list(compact_trade_date)
    limit_up_codes = set()
    if limit_df is not None and not limit_df.empty:
        normalized_limit_df = limit_df.copy()
        normalized_limit_df["limit"] = normalized_limit_df["limit"].astype(str)
        limit_up_codes = set(normalized_limit_df[normalized_limit_df["limit"] == "U"]["ts_code"].astype(str).tolist())

    daily_df = get_daily_basic_batch(compact_trade_date)
    daily_basic_by_ts: dict[str, dict[str, Any]] = {}
    if daily_df is not None and not daily_df.empty:
        normalized_daily_df = daily_df.fillna("")
        for _, row in normalized_daily_df.iterrows():
            ts_code = str(row.get("ts_code") or "").strip()
            if ts_code:
                daily_basic_by_ts[ts_code] = row.to_dict()

    cached = {
        "snapshot": _load_candidate_pool_snapshot(snapshots_root, compact_trade_date, snapshot_cache=snapshot_cache),
        "suspend_codes": suspend_codes,
        "limit_up_codes": limit_up_codes,
        "cooldown_tickers": set(get_cooled_tickers(compact_trade_date) or set()),
        "daily_basic_by_ts": daily_basic_by_ts,
    }
    context_cache[compact_trade_date] = cached
    return cached


def _blocking_stage_details(stage: str, *, subject: str) -> tuple[str, str, str]:
    if stage == "missing_market_context":
        return (
            "p0_market_context_gap",
            f"补齐 {subject} 的 Layer A 市场上下文，当前还无法稳定还原 candidate_pool 排除原因。",
            f"先确认 {subject} 对应 trade_date 的 stock_basic / daily_basic / cooldown / limit 数据是否可用，再继续 Layer A 归因。",
        )
    if stage == "missing_stock_basic":
        return (
            "p0_stock_basic_gap",
            f"补齐 {subject} 的 stock_basic 基础信息，当前候选池 universe 都无法准确定位该票。",
            f"优先核对 {subject} 是否在全市场 stock_basic universe 中可见，再继续 Layer A 召回诊断。",
        )
    if stage in {"st_excluded", "beijing_exchange_excluded", "new_listing_excluded", "suspended", "limit_up_excluded", "cooldown_excluded"}:
        return (
            "p1_hard_prefilter",
            f"{subject} 在 Layer A 先验硬过滤阶段被排除，当前不属于 watchlist 或 candidate-entry 主矛盾。",
            f"优先核对 {subject} 的硬过滤规则是否符合策略意图，再决定是否放宽召回边界。",
        )
    if stage == "low_estimated_liquidity":
        return (
            "p0_daily_liquidity_gate",
            f"{subject} 卡在当日估算流动性粗筛，Layer A 先被 1D liquidity gate 拦下。",
            f"先复核 {subject} 的 turnover_rate / circ_mv 与 {MIN_ESTIMATED_AMOUNT_1D} 万门槛，而不是继续看 watchlist。",
        )
    if stage == "low_avg_amount_20d":
        return (
            "p0_avg_amount_gate",
            f"{subject} 卡在 20 日均成交额门槛，Layer A 主矛盾落在中期流动性过滤。",
            f"先审 {subject} 的 20 日均额与 {MIN_AVG_AMOUNT_20D} 万门槛，再讨论 top300 截断或下游 handoff。",
        )
    if stage == "candidate_pool_truncated_after_filters":
        return (
            "p0_top300_truncation",
            f"{subject} 通过了 Layer A 过滤但仍未进 snapshot，当前更像是 top300 截断 / 排名边界问题。",
            f"先补 {subject} 的 pre-truncation 排名观测与 top300 frontier，而不是继续下游 recall 诊断。",
        )
    return (
        "p4_downstream_followup",
        f"{subject} 已进入 candidate_pool 或更下游阶段，Layer A recall 已不是首要矛盾。",
        f"把 {subject} 转回 Layer B / watchlist / candidate-entry handoff 诊断。",
    )


def _count_stages(rows: list[dict[str, Any]], key: str = "blocking_stage") -> dict[str, int]:
    counts = Counter(str(row.get(key) or "unknown") for row in rows if str(row.get(key) or "").strip())
    ordered: dict[str, int] = {}
    for stage in STAGE_ORDER:
        if counts.get(stage):
            ordered[stage] = int(counts[stage])
    for stage, count in counts.most_common():
        if stage not in ordered:
            ordered[stage] = int(count)
    return ordered


def _dominant_stage(stage_counts: dict[str, int]) -> str | None:
    if not stage_counts:
        return None
    ranked = sorted(
        stage_counts.items(),
        key=lambda item: (-int(item[1] or 0), STAGE_ORDER.index(item[0]) if item[0] in STAGE_ORDER else len(STAGE_ORDER)),
    )
    return ranked[0][0] if ranked else None


def _top_tickers_by_stage(priority_ticker_dossiers: list[dict[str, Any]], stage: str) -> list[str]:
    return [
        str(row.get("ticker") or "")
        for row in priority_ticker_dossiers
        if str(row.get("dominant_blocking_stage") or "") == stage and str(row.get("ticker") or "").strip()
    ][:3]


def _build_top_stage_tickers(priority_ticker_dossiers: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for stage in STAGE_ORDER:
        tickers = _top_tickers_by_stage(priority_ticker_dossiers, stage)
        if tickers:
            result[stage] = tickers
    return result


def _evaluate_ticker_stage(
    ticker: str,
    trade_date: str,
    *,
    snapshots_root: Path,
    stock_basic_by_symbol: dict[str, dict[str, Any]],
    trade_date_context: dict[str, Any],
    frontier_context: dict[str, Any],
    pro: Any,
    diagnostics_override: dict[tuple[str, str], dict[str, Any]] | None,
) -> dict[str, Any]:
    compact_trade_date = _compact_trade_date(trade_date)
    override = (diagnostics_override or {}).get((ticker, compact_trade_date))
    if override is not None:
        payload = dict(override)
        payload.setdefault("ticker", ticker)
        payload.setdefault("trade_date", compact_trade_date)
        payload.setdefault("blocking_stage", "missing_market_context")
        payload.setdefault("pre_truncation_total_candidates", None)
        payload.setdefault("pre_truncation_cutoff_rank", None)
        payload.setdefault("pre_truncation_rank", None)
        payload.setdefault("pre_truncation_rank_gap_to_cutoff", None)
        payload.setdefault("pre_truncation_cutoff_ticker", None)
        payload.setdefault("pre_truncation_cutoff_avg_amount_20d", None)
        payload.setdefault("pre_truncation_cutoff_market_cap", None)
        payload.setdefault("pre_truncation_avg_amount_gap_to_cutoff", None)
        payload.setdefault("pre_truncation_avg_amount_share_of_cutoff", None)
        payload.setdefault("pre_truncation_market_cap_gap_to_cutoff", None)
        payload.setdefault("pre_truncation_market_cap_share_of_cutoff", None)
        payload.setdefault("pre_truncation_ranking_driver", None)
        payload.setdefault("avg_amount_share_of_min_gate", None)
        payload.setdefault("pre_truncation_cutoff_avg_amount_share_of_min_gate", None)
        payload.setdefault("pre_truncation_liquidity_gap_mode", None)
        payload.setdefault("market_cap", None)
        if payload.get("avg_amount_share_of_min_gate") is None:
            payload["avg_amount_share_of_min_gate"] = _avg_amount_share_of_min_gate(payload.get("avg_amount_20d"))
        if payload.get("pre_truncation_cutoff_avg_amount_share_of_min_gate") is None:
            payload["pre_truncation_cutoff_avg_amount_share_of_min_gate"] = _avg_amount_share_of_min_gate(
                payload.get("pre_truncation_cutoff_avg_amount_20d")
            )
        if payload.get("pre_truncation_avg_amount_gap_to_cutoff") is None:
            avg_amount_20d = _safe_float(payload.get("avg_amount_20d"))
            cutoff_avg_amount_20d = _safe_float(payload.get("pre_truncation_cutoff_avg_amount_20d"))
            if avg_amount_20d is not None and cutoff_avg_amount_20d is not None:
                payload["pre_truncation_avg_amount_gap_to_cutoff"] = round(cutoff_avg_amount_20d - avg_amount_20d, 4)
        if payload.get("pre_truncation_avg_amount_share_of_cutoff") is None:
            payload["pre_truncation_avg_amount_share_of_cutoff"] = _safe_ratio(
                payload.get("avg_amount_20d"),
                payload.get("pre_truncation_cutoff_avg_amount_20d"),
            )
        if payload.get("pre_truncation_market_cap_gap_to_cutoff") is None:
            market_cap = _safe_float(payload.get("market_cap"))
            cutoff_market_cap = _safe_float(payload.get("pre_truncation_cutoff_market_cap"))
            if market_cap is not None and cutoff_market_cap is not None:
                payload["pre_truncation_market_cap_gap_to_cutoff"] = round(cutoff_market_cap - market_cap, 4)
        if payload.get("pre_truncation_market_cap_share_of_cutoff") is None:
            payload["pre_truncation_market_cap_share_of_cutoff"] = _safe_ratio(
                payload.get("market_cap"),
                payload.get("pre_truncation_cutoff_market_cap"),
            )
        if payload.get("pre_truncation_ranking_driver") is None:
            payload["pre_truncation_ranking_driver"] = _classify_pre_truncation_ranking_driver(
                pre_truncation_rank_gap_to_cutoff=payload.get("pre_truncation_rank_gap_to_cutoff"),
                avg_amount_share_of_cutoff=payload.get("pre_truncation_avg_amount_share_of_cutoff"),
                market_cap_share_of_cutoff=payload.get("pre_truncation_market_cap_share_of_cutoff"),
            )
        if payload.get("pre_truncation_liquidity_gap_mode") is None:
            payload["pre_truncation_liquidity_gap_mode"] = _classify_pre_truncation_liquidity_gap_mode(
                avg_amount_share_of_min_gate=payload.get("avg_amount_share_of_min_gate"),
                avg_amount_share_of_cutoff=payload.get("pre_truncation_avg_amount_share_of_cutoff"),
            )
        payload.setdefault("pre_truncation_frontier_window", [])
        payload.setdefault("top300_higher_liquidity_peer_count", None)
        payload.setdefault("top300_lower_market_cap_hot_peer_count", None)
        payload.setdefault("top300_lower_market_cap_hot_peer_examples", [])
        payload.setdefault("estimated_rank_gap_after_rebucket", None)
        return payload

    snapshot = dict(trade_date_context.get("snapshot") or {})
    ranking_by_ticker = dict(frontier_context.get("ranking_by_ticker") or {})
    frontier_row = dict(ranking_by_ticker.get(ticker) or {})
    cutoff_row = dict(frontier_context.get("cutoff_row") or {})
    snapshot_cutoff_ticker = snapshot.get("selected_cutoff_ticker")
    snapshot_cutoff_avg_amount_20d = _safe_float(snapshot.get("selected_cutoff_avg_volume_20d"))
    pre_truncation_rank = frontier_row.get("rank")
    pre_truncation_cutoff_rank = frontier_context.get("pre_truncation_cutoff_rank")
    pre_truncation_rank_gap_to_cutoff = None
    if pre_truncation_rank is not None and pre_truncation_cutoff_rank is not None:
        pre_truncation_rank_gap_to_cutoff = max(0, int(pre_truncation_rank) - int(pre_truncation_cutoff_rank))
    pre_truncation_frontier_window = list(frontier_context.get("frontier_window") or [])
    pre_truncation_avg_amount_gap_to_cutoff = None
    cutoff_avg_amount_20d = _safe_float(cutoff_row.get("avg_amount_20d"))
    if cutoff_avg_amount_20d is None:
        cutoff_avg_amount_20d = snapshot_cutoff_avg_amount_20d
    current_avg_amount_20d = frontier_row.get("avg_amount_20d")
    avg_amount_share_of_min_gate = _avg_amount_share_of_min_gate(current_avg_amount_20d)
    pre_truncation_cutoff_avg_amount_share_of_min_gate = _avg_amount_share_of_min_gate(cutoff_avg_amount_20d)
    if cutoff_avg_amount_20d is not None and current_avg_amount_20d is not None:
        pre_truncation_avg_amount_gap_to_cutoff = round(float(cutoff_avg_amount_20d) - float(current_avg_amount_20d), 4)
    pre_truncation_avg_amount_share_of_cutoff = _safe_ratio(current_avg_amount_20d, cutoff_avg_amount_20d)
    pre_truncation_market_cap_gap_to_cutoff = None
    cutoff_market_cap = cutoff_row.get("market_cap")
    current_market_cap = frontier_row.get("market_cap")
    if cutoff_market_cap is not None and current_market_cap is not None:
        pre_truncation_market_cap_gap_to_cutoff = round(float(cutoff_market_cap) - float(current_market_cap), 4)
    pre_truncation_market_cap_share_of_cutoff = _safe_ratio(current_market_cap, cutoff_market_cap)
    top300_higher_liquidity_peer_count = None
    top300_lower_market_cap_hot_peer_count = None
    top300_lower_market_cap_hot_peer_examples: list[str] = []
    estimated_rank_gap_after_rebucket = None
    if current_avg_amount_20d is not None and current_market_cap is not None and pre_truncation_cutoff_rank is not None:
        top300_higher_liquidity_peer_count = 0
        top300_lower_market_cap_hot_peer_count = 0
        for peer in ranking_by_ticker.values():
            peer_ticker = str(peer.get("ticker") or "").strip()
            peer_rank = peer.get("rank")
            if not peer_ticker or peer_ticker == ticker or peer_rank is None or int(peer_rank) > int(pre_truncation_cutoff_rank):
                continue
            peer_avg_amount = _safe_float(peer.get("avg_amount_20d"))
            peer_market_cap = _safe_float(peer.get("market_cap"))
            if peer_avg_amount is None or peer_avg_amount <= float(current_avg_amount_20d):
                continue
            top300_higher_liquidity_peer_count += 1
            if peer_market_cap is not None and peer_market_cap <= float(current_market_cap):
                top300_lower_market_cap_hot_peer_count += 1
                if len(top300_lower_market_cap_hot_peer_examples) < 5:
                    top300_lower_market_cap_hot_peer_examples.append(peer_ticker)
        if pre_truncation_rank_gap_to_cutoff is not None:
            estimated_rank_gap_after_rebucket = max(
                int(pre_truncation_rank_gap_to_cutoff) - int(top300_lower_market_cap_hot_peer_count or 0),
                0,
            )
    pre_truncation_ranking_driver = _classify_pre_truncation_ranking_driver(
        pre_truncation_rank_gap_to_cutoff=pre_truncation_rank_gap_to_cutoff,
        avg_amount_share_of_cutoff=pre_truncation_avg_amount_share_of_cutoff,
        market_cap_share_of_cutoff=pre_truncation_market_cap_share_of_cutoff,
    )
    pre_truncation_liquidity_gap_mode = _classify_pre_truncation_liquidity_gap_mode(
        avg_amount_share_of_min_gate=avg_amount_share_of_min_gate,
        avg_amount_share_of_cutoff=pre_truncation_avg_amount_share_of_cutoff,
    )
    candidate_pool_rank = dict(snapshot.get("ticker_ranks") or {}).get(ticker)
    stock_row = dict(stock_basic_by_symbol.get(ticker) or {})
    if not stock_basic_by_symbol:
        return {
            "ticker": ticker,
            "trade_date": compact_trade_date,
            "blocking_stage": "missing_market_context",
            "candidate_pool_visible": candidate_pool_rank is not None,
            "candidate_pool_rank": candidate_pool_rank,
            "candidate_pool_snapshot": snapshot.get("snapshot_name"),
            "candidate_pool_snapshot_path": snapshot.get("snapshot_path"),
            "candidate_pool_snapshot_size": snapshot.get("snapshot_size"),
            "pre_truncation_total_candidates": frontier_context.get("pre_truncation_total_candidates"),
            "pre_truncation_cutoff_rank": pre_truncation_cutoff_rank,
            "pre_truncation_rank": pre_truncation_rank,
            "pre_truncation_rank_gap_to_cutoff": pre_truncation_rank_gap_to_cutoff,
            "pre_truncation_cutoff_ticker": cutoff_row.get("ticker") or snapshot_cutoff_ticker,
            "pre_truncation_cutoff_avg_amount_20d": cutoff_avg_amount_20d,
            "pre_truncation_cutoff_market_cap": cutoff_row.get("market_cap"),
            "pre_truncation_avg_amount_gap_to_cutoff": pre_truncation_avg_amount_gap_to_cutoff,
            "pre_truncation_avg_amount_share_of_cutoff": pre_truncation_avg_amount_share_of_cutoff,
            "avg_amount_share_of_min_gate": avg_amount_share_of_min_gate,
            "pre_truncation_cutoff_avg_amount_share_of_min_gate": pre_truncation_cutoff_avg_amount_share_of_min_gate,
            "pre_truncation_market_cap_gap_to_cutoff": pre_truncation_market_cap_gap_to_cutoff,
            "pre_truncation_market_cap_share_of_cutoff": pre_truncation_market_cap_share_of_cutoff,
            "pre_truncation_ranking_driver": pre_truncation_ranking_driver,
            "pre_truncation_liquidity_gap_mode": pre_truncation_liquidity_gap_mode,
            "market_cap": current_market_cap,
            "pre_truncation_frontier_window": pre_truncation_frontier_window,
            "top300_higher_liquidity_peer_count": top300_higher_liquidity_peer_count,
            "top300_lower_market_cap_hot_peer_count": top300_lower_market_cap_hot_peer_count,
            "top300_lower_market_cap_hot_peer_examples": top300_lower_market_cap_hot_peer_examples,
            "estimated_rank_gap_after_rebucket": estimated_rank_gap_after_rebucket,
            "failed_filters": [],
        }
    if not stock_row:
        return {
            "ticker": ticker,
            "trade_date": compact_trade_date,
            "blocking_stage": "missing_stock_basic",
            "candidate_pool_visible": candidate_pool_rank is not None,
            "candidate_pool_rank": candidate_pool_rank,
            "candidate_pool_snapshot": snapshot.get("snapshot_name"),
            "candidate_pool_snapshot_path": snapshot.get("snapshot_path"),
            "candidate_pool_snapshot_size": snapshot.get("snapshot_size"),
            "pre_truncation_total_candidates": frontier_context.get("pre_truncation_total_candidates"),
            "pre_truncation_cutoff_rank": pre_truncation_cutoff_rank,
            "pre_truncation_rank": pre_truncation_rank,
            "pre_truncation_rank_gap_to_cutoff": pre_truncation_rank_gap_to_cutoff,
            "pre_truncation_cutoff_ticker": cutoff_row.get("ticker") or snapshot_cutoff_ticker,
            "pre_truncation_cutoff_avg_amount_20d": cutoff_avg_amount_20d,
            "pre_truncation_cutoff_market_cap": cutoff_row.get("market_cap"),
            "pre_truncation_avg_amount_gap_to_cutoff": pre_truncation_avg_amount_gap_to_cutoff,
            "pre_truncation_avg_amount_share_of_cutoff": pre_truncation_avg_amount_share_of_cutoff,
            "avg_amount_share_of_min_gate": avg_amount_share_of_min_gate,
            "pre_truncation_cutoff_avg_amount_share_of_min_gate": pre_truncation_cutoff_avg_amount_share_of_min_gate,
            "pre_truncation_market_cap_gap_to_cutoff": pre_truncation_market_cap_gap_to_cutoff,
            "pre_truncation_market_cap_share_of_cutoff": pre_truncation_market_cap_share_of_cutoff,
            "pre_truncation_ranking_driver": pre_truncation_ranking_driver,
            "pre_truncation_liquidity_gap_mode": pre_truncation_liquidity_gap_mode,
            "market_cap": current_market_cap,
            "pre_truncation_frontier_window": pre_truncation_frontier_window,
            "top300_higher_liquidity_peer_count": top300_higher_liquidity_peer_count,
            "top300_lower_market_cap_hot_peer_count": top300_lower_market_cap_hot_peer_count,
            "top300_lower_market_cap_hot_peer_examples": top300_lower_market_cap_hot_peer_examples,
            "estimated_rank_gap_after_rebucket": estimated_rank_gap_after_rebucket,
            "failed_filters": [],
        }

    ts_code = str(stock_row.get("ts_code") or "").strip()
    name = str(stock_row.get("name") or "").strip()
    list_date = _compact_trade_date(str(stock_row.get("list_date") or ""))
    market = stock_row.get("market")
    listing_days = _estimate_trading_days(list_date, compact_trade_date)
    is_st = "ST" in name.upper()
    is_bj = is_beijing_exchange_stock(ts_code=ts_code, symbol=ticker, market=market)
    is_suspended = ts_code in set(trade_date_context.get("suspend_codes") or set())
    is_limit_up = ts_code in set(trade_date_context.get("limit_up_codes") or set())
    is_cooldown = ticker in set(trade_date_context.get("cooldown_tickers") or set())
    daily_row = dict(dict(trade_date_context.get("daily_basic_by_ts") or {}).get(ts_code) or {})

    failed_filters: list[str] = []
    if is_st:
        failed_filters.append("st_excluded")
    if is_bj:
        failed_filters.append("beijing_exchange_excluded")
    if listing_days < MIN_LISTING_DAYS:
        failed_filters.append("new_listing_excluded")
    if is_suspended:
        failed_filters.append("suspended")
    if is_limit_up:
        failed_filters.append("limit_up_excluded")
    if is_cooldown:
        failed_filters.append("cooldown_excluded")

    if candidate_pool_rank is not None:
        blocking_stage = "candidate_pool_visible_or_later_stage"
        avg_amount_20d = None
        estimated_amount_1d = None
        if daily_row:
            turnover_rate = _safe_float(daily_row.get("turnover_rate"))
            circ_mv = _safe_float(daily_row.get("circ_mv"))
            if turnover_rate is not None and circ_mv is not None:
                estimated_amount_1d = round(max(0.0, circ_mv * turnover_rate / 100.0), 4)
    elif failed_filters:
        blocking_stage = failed_filters[0]
        estimated_amount_1d = None
        avg_amount_20d = None
    else:
        shadow_recall_status = str(snapshot.get("shadow_recall_status") or "").strip()
        if shadow_recall_status == "legacy_unknown":
            blocking_stage = "shadow_snapshot_legacy_unknown"
            estimated_amount_1d = None
            avg_amount_20d = None
        elif not daily_row or pro is None:
            local_avg_amount_20d, local_prices_snapshot_path = _estimate_avg_amount_20d_from_local_prices(
                snapshots_root,
                ticker,
                compact_trade_date,
            )
            if local_avg_amount_20d is not None:
                avg_amount_20d = local_avg_amount_20d
                estimated_amount_1d = None
                if avg_amount_20d < MIN_AVG_AMOUNT_20D:
                    blocking_stage = "low_avg_amount_20d"
                    failed_filters.append("low_avg_amount_20d")
                else:
                    blocking_stage = "candidate_pool_truncated_after_filters"
            else:
                blocking_stage = "missing_market_context"
                estimated_amount_1d = None
                avg_amount_20d = None
                local_prices_snapshot_path = None
        else:
            turnover_rate = _safe_float(daily_row.get("turnover_rate"))
            circ_mv = _safe_float(daily_row.get("circ_mv"))
            estimated_amount_1d = None
            local_prices_snapshot_path = None
            if turnover_rate is not None and circ_mv is not None:
                estimated_amount_1d = round(max(0.0, circ_mv * turnover_rate / 100.0), 4)
            if estimated_amount_1d is not None and 0.0 < estimated_amount_1d < MIN_ESTIMATED_AMOUNT_1D:
                blocking_stage = "low_estimated_liquidity"
                avg_amount_20d = None
                failed_filters.append("low_estimated_liquidity")
            else:
                avg_amount_value = _get_avg_amount_20d(pro, ts_code, compact_trade_date)
                avg_amount_20d = round(float(avg_amount_value), 4)
                if avg_amount_20d < MIN_AVG_AMOUNT_20D:
                    blocking_stage = "low_avg_amount_20d"
                    failed_filters.append("low_avg_amount_20d")
                else:
                    blocking_stage = "candidate_pool_truncated_after_filters"
    if "local_prices_snapshot_path" not in locals():
        local_prices_snapshot_path = None
    if avg_amount_share_of_min_gate is None:
        avg_amount_share_of_min_gate = _avg_amount_share_of_min_gate(avg_amount_20d)
    if pre_truncation_avg_amount_gap_to_cutoff is None and cutoff_avg_amount_20d is not None and avg_amount_20d is not None:
        pre_truncation_avg_amount_gap_to_cutoff = round(float(cutoff_avg_amount_20d) - float(avg_amount_20d), 4)
    if pre_truncation_avg_amount_share_of_cutoff is None:
        pre_truncation_avg_amount_share_of_cutoff = _safe_ratio(avg_amount_20d, cutoff_avg_amount_20d)
    if pre_truncation_ranking_driver == "unknown":
        pre_truncation_ranking_driver = _classify_pre_truncation_ranking_driver(
            pre_truncation_rank_gap_to_cutoff=pre_truncation_rank_gap_to_cutoff,
            avg_amount_share_of_cutoff=pre_truncation_avg_amount_share_of_cutoff,
            market_cap_share_of_cutoff=pre_truncation_market_cap_share_of_cutoff,
        )
    if pre_truncation_liquidity_gap_mode == "unknown":
        pre_truncation_liquidity_gap_mode = _classify_pre_truncation_liquidity_gap_mode(
            avg_amount_share_of_min_gate=avg_amount_share_of_min_gate,
            avg_amount_share_of_cutoff=pre_truncation_avg_amount_share_of_cutoff,
        )
    local_avg_amount_share_of_cutoff = _safe_ratio(avg_amount_20d, snapshot.get("shadow_selected_cutoff_avg_volume_20d"))

    return {
        "ticker": ticker,
        "trade_date": compact_trade_date,
        "ts_code": ts_code,
        "name": name,
        "list_date": list_date or None,
        "listing_days": listing_days,
        "market": market,
        "candidate_pool_visible": candidate_pool_rank is not None,
        "candidate_pool_rank": candidate_pool_rank,
        "candidate_pool_snapshot": snapshot.get("snapshot_name"),
        "candidate_pool_snapshot_path": snapshot.get("snapshot_path"),
        "candidate_pool_snapshot_size": snapshot.get("snapshot_size"),
        "candidate_pool_shadow_snapshot_path": snapshot.get("shadow_snapshot_path"),
        "candidate_pool_selected_cutoff_ticker": snapshot_cutoff_ticker,
        "candidate_pool_selected_cutoff_avg_volume_20d": snapshot_cutoff_avg_amount_20d,
        "candidate_pool_shadow_recall_complete": snapshot.get("shadow_recall_complete"),
        "candidate_pool_shadow_recall_status": snapshot.get("shadow_recall_status"),
        "candidate_pool_shadow_selected_cutoff_avg_volume_20d": snapshot.get("shadow_selected_cutoff_avg_volume_20d"),
        "pre_truncation_total_candidates": frontier_context.get("pre_truncation_total_candidates"),
        "pre_truncation_cutoff_rank": pre_truncation_cutoff_rank,
        "pre_truncation_rank": pre_truncation_rank,
        "pre_truncation_rank_gap_to_cutoff": pre_truncation_rank_gap_to_cutoff,
        "pre_truncation_cutoff_ticker": cutoff_row.get("ticker") or snapshot_cutoff_ticker,
        "pre_truncation_cutoff_avg_amount_20d": cutoff_avg_amount_20d,
        "pre_truncation_cutoff_market_cap": cutoff_row.get("market_cap"),
        "pre_truncation_avg_amount_gap_to_cutoff": pre_truncation_avg_amount_gap_to_cutoff,
        "pre_truncation_avg_amount_share_of_cutoff": pre_truncation_avg_amount_share_of_cutoff,
        "avg_amount_share_of_min_gate": avg_amount_share_of_min_gate,
        "pre_truncation_cutoff_avg_amount_share_of_min_gate": pre_truncation_cutoff_avg_amount_share_of_min_gate,
        "pre_truncation_market_cap_gap_to_cutoff": pre_truncation_market_cap_gap_to_cutoff,
        "pre_truncation_market_cap_share_of_cutoff": pre_truncation_market_cap_share_of_cutoff,
        "pre_truncation_ranking_driver": pre_truncation_ranking_driver,
        "pre_truncation_liquidity_gap_mode": pre_truncation_liquidity_gap_mode,
        "pre_truncation_frontier_window": pre_truncation_frontier_window,
        "top300_higher_liquidity_peer_count": top300_higher_liquidity_peer_count,
        "top300_lower_market_cap_hot_peer_count": top300_lower_market_cap_hot_peer_count,
        "top300_lower_market_cap_hot_peer_examples": top300_lower_market_cap_hot_peer_examples,
        "estimated_rank_gap_after_rebucket": estimated_rank_gap_after_rebucket,
        "estimated_amount_1d": estimated_amount_1d,
        "avg_amount_20d": avg_amount_20d,
        "avg_amount_20d_source": "local_snapshot_prices" if local_prices_snapshot_path else ("tushare_daily" if avg_amount_20d is not None else None),
        "local_prices_snapshot_path": local_prices_snapshot_path,
        "local_avg_amount_share_of_cutoff": local_avg_amount_share_of_cutoff,
        "market_cap": current_market_cap,
        "is_st": is_st,
        "is_beijing_exchange": is_bj,
        "is_suspended": is_suspended,
        "is_limit_up": is_limit_up,
        "is_cooldown": is_cooldown,
        "failed_filters": failed_filters,
        "blocking_stage": blocking_stage,
    }


def _build_priority_ticker_dossiers(
    focus_tickers: list[str],
    tradeable_pool: dict[str, Any],
    *,
    watchlist_trade_date_allowlist: dict[str, set[str]],
    snapshots_root: Path,
    diagnostics_override: dict[tuple[str, str], dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    no_candidate_rows = [
        dict(row)
        for row in list(tradeable_pool.get("rows") or [])
        if str(row.get("first_kill_switch") or "") == "no_candidate_entry"
    ]
    stock_basic_universe, stock_basic_by_symbol = _load_stock_basic_universe()
    fallback_stock_basic_universe, fallback_stock_basic_by_symbol = _build_tradeable_pool_stock_basic_fallback(no_candidate_rows)
    if stock_basic_universe.empty:
        stock_basic_universe = fallback_stock_basic_universe
    elif not fallback_stock_basic_universe.empty:
        existing_symbols = set(stock_basic_universe["symbol"].astype(str).tolist()) if "symbol" in stock_basic_universe.columns else set()
        missing_rows = fallback_stock_basic_universe[
            ~fallback_stock_basic_universe["symbol"].astype(str).isin(existing_symbols)
        ].copy()
        if not missing_rows.empty:
            stock_basic_universe = pd.concat([stock_basic_universe, missing_rows], ignore_index=True)
    if fallback_stock_basic_by_symbol:
        stock_basic_by_symbol = {**fallback_stock_basic_by_symbol, **stock_basic_by_symbol}
    pro = _get_pro()
    snapshot_cache: dict[str, dict[str, Any]] = {}
    context_cache: dict[str, dict[str, Any]] = {}
    frontier_cache: dict[str, dict[str, Any]] = {}
    dossiers: list[dict[str, Any]] = []

    for priority_rank, ticker in enumerate(focus_tickers, start=1):
        ticker_rows = [row for row in no_candidate_rows if str(row.get("ticker") or "").strip() == ticker]
        allowed_trade_dates = watchlist_trade_date_allowlist.get(ticker) or set()
        if allowed_trade_dates:
            ticker_rows = [row for row in ticker_rows if _compact_trade_date(str(row.get("trade_date") or "")) in allowed_trade_dates]

        occurrence_evidence: list[dict[str, Any]] = []
        report_dir_counts = Counter(str(row.get("report_dir") or "") for row in ticker_rows if str(row.get("report_dir") or "").strip())
        for row in sorted(ticker_rows, key=lambda current: (_compact_trade_date(str(current.get("trade_date") or "")), str(current.get("report_dir") or ""))):
            compact_trade_date = _compact_trade_date(str(row.get("trade_date") or ""))
            trade_date_context = _build_trade_date_context(
                compact_trade_date,
                snapshots_root=snapshots_root,
                snapshot_cache=snapshot_cache,
                context_cache=context_cache,
            )
            frontier_context = _build_pre_truncation_frontier_context(
                compact_trade_date,
                stock_basic_universe=stock_basic_universe,
                trade_date_context=trade_date_context,
                pro=pro,
                frontier_cache=frontier_cache,
            )
            stage_payload = _evaluate_ticker_stage(
                ticker,
                compact_trade_date,
                snapshots_root=snapshots_root,
                stock_basic_by_symbol=stock_basic_by_symbol,
                trade_date_context=trade_date_context,
                frontier_context=frontier_context,
                pro=pro,
                diagnostics_override=diagnostics_override,
            )
            occurrence_evidence.append(
                {
                    "trade_date": compact_trade_date,
                    "report_dir": row.get("report_dir"),
                    "report_mode": row.get("report_mode"),
                    "report_selection_target": row.get("report_selection_target"),
                    "strict_btst_goal_case": bool(row.get("strict_btst_goal_case")),
                    "next_high_return": row.get("next_high_return"),
                    "t_plus_2_close_return": row.get("t_plus_2_close_return"),
                    **stage_payload,
                }
            )

        stage_counts = _count_stages(occurrence_evidence)
        dominant_stage = _dominant_stage(stage_counts)
        action_tier, title, next_step = _blocking_stage_details(dominant_stage or "missing_market_context", subject=ticker)
        strict_goal_case_count = sum(1 for row in occurrence_evidence if bool(row.get("strict_btst_goal_case")))
        failure_reason_map = {
            "shadow_snapshot_legacy_unknown": f"{ticker} 当前只有 legacy 空 shadow 快照，暂时不能把 upstream absence 直接当成真实 candidate_pool 漏票。",
            "missing_market_context": f"{ticker} 当前还缺 Layer A 市场上下文，无法稳定还原 candidate_pool 排除原因。",
            "missing_stock_basic": f"{ticker} 在 stock_basic universe 中没有稳定命中，Layer A 基础输入仍有缺口。",
            "st_excluded": f"{ticker} 在 Layer A 就被 ST 过滤挡下。",
            "beijing_exchange_excluded": f"{ticker} 在 Layer A 就被北交所过滤挡下。",
            "new_listing_excluded": f"{ticker} 在 Layer A 就被上市时长过滤挡下。",
            "suspended": f"{ticker} 在 Layer A 就被停牌过滤挡下。",
            "limit_up_excluded": f"{ticker} 在 Layer A 就被涨停过滤挡下。",
            "cooldown_excluded": f"{ticker} 在 Layer A 就被冷却期过滤挡下。",
            "low_estimated_liquidity": f"{ticker} 在 Layer A 卡在当日估算流动性粗筛。",
            "low_avg_amount_20d": f"{ticker} 在 Layer A 卡在 20 日均成交额门槛。",
            "candidate_pool_truncated_after_filters": f"{ticker} 通过了 Layer A 过滤但仍未进 snapshot，当前更像 top300 截断边界问题。",
            "candidate_pool_visible_or_later_stage": f"{ticker} 已进入 candidate_pool 或更下游阶段，Layer A recall 已不是首要矛盾。",
        }
        truncation_ranking_summary = _build_ticker_truncation_ranking_summary(occurrence_evidence)
        dossiers.append(
            {
                "priority_rank": priority_rank,
                "ticker": ticker,
                "occurrence_count": len(occurrence_evidence),
                "strict_btst_goal_case_count": strict_goal_case_count,
                "primary_report_dir": report_dir_counts.most_common(1)[0][0] if report_dir_counts else None,
                "report_dir_counts": {key: int(value) for key, value in report_dir_counts.most_common()},
                "blocking_stage_counts": stage_counts,
                "dominant_blocking_stage": dominant_stage,
                "action_tier": action_tier,
                "title": title,
                "failure_reason": failure_reason_map.get(dominant_stage or "", f"{ticker} 的 Layer A 归因仍混合，需要更多 occurrence 证据。"),
                "next_step": next_step,
                "closest_pre_truncation_gap": min(
                    [
                        int(current.get("pre_truncation_rank_gap_to_cutoff"))
                        for current in occurrence_evidence
                        if current.get("pre_truncation_rank_gap_to_cutoff") is not None
                    ],
                    default=None,
                ),
                "truncation_ranking_summary": truncation_ranking_summary,
                "truncation_liquidity_profile": _build_truncation_liquidity_profile(ticker, truncation_ranking_summary),
                "occurrence_evidence": occurrence_evidence,
            }
        )
    return dossiers


def _build_truncation_frontier_summary(priority_ticker_dossiers: list[dict[str, Any]]) -> dict[str, Any]:
    truncation_case_count = 0
    truncation_rows: list[dict[str, Any]] = []
    for row in priority_ticker_dossiers:
        ticker = str(row.get("ticker") or "").strip()
        for occurrence in list(row.get("occurrence_evidence") or []):
            if str(occurrence.get("blocking_stage") or "") != "candidate_pool_truncated_after_filters":
                continue
            truncation_case_count += 1
            rank_gap = occurrence.get("pre_truncation_rank_gap_to_cutoff")
            rank_value = occurrence.get("pre_truncation_rank")
            cutoff_rank = occurrence.get("pre_truncation_cutoff_rank")
            share_of_cutoff = occurrence.get("pre_truncation_avg_amount_share_of_cutoff")
            if rank_gap is None and rank_value is None and cutoff_rank is None and share_of_cutoff is None:
                continue
            truncation_rows.append(
                {
                    "ticker": ticker,
                    "trade_date": occurrence.get("trade_date"),
                    "pre_truncation_rank": rank_value,
                    "pre_truncation_cutoff_rank": cutoff_rank,
                    "pre_truncation_rank_gap_to_cutoff": rank_gap,
                    "pre_truncation_total_candidates": occurrence.get("pre_truncation_total_candidates"),
                    "pre_truncation_cutoff_ticker": occurrence.get("pre_truncation_cutoff_ticker"),
                    "pre_truncation_cutoff_avg_amount_20d": occurrence.get("pre_truncation_cutoff_avg_amount_20d"),
                    "pre_truncation_cutoff_avg_amount_share_of_min_gate": occurrence.get("pre_truncation_cutoff_avg_amount_share_of_min_gate"),
                    "pre_truncation_cutoff_market_cap": occurrence.get("pre_truncation_cutoff_market_cap"),
                    "pre_truncation_avg_amount_gap_to_cutoff": occurrence.get("pre_truncation_avg_amount_gap_to_cutoff"),
                    "pre_truncation_avg_amount_share_of_cutoff": share_of_cutoff,
                    "avg_amount_share_of_min_gate": occurrence.get("avg_amount_share_of_min_gate"),
                    "pre_truncation_market_cap_gap_to_cutoff": occurrence.get("pre_truncation_market_cap_gap_to_cutoff"),
                    "pre_truncation_market_cap_share_of_cutoff": occurrence.get("pre_truncation_market_cap_share_of_cutoff"),
                    "pre_truncation_ranking_driver": occurrence.get("pre_truncation_ranking_driver"),
                    "pre_truncation_liquidity_gap_mode": occurrence.get("pre_truncation_liquidity_gap_mode"),
                    "avg_amount_20d": occurrence.get("avg_amount_20d"),
                    "market_cap": occurrence.get("market_cap"),
                    "pre_truncation_frontier_window": occurrence.get("pre_truncation_frontier_window") or [],
                }
            )
    ordered_rows = sorted(
        truncation_rows,
        key=lambda current: (
            0 if current.get("pre_truncation_rank") is not None else 1,
            int(current.get("pre_truncation_rank_gap_to_cutoff") or 10**9),
            int(current.get("pre_truncation_rank") or 10**9),
            -float(_safe_float(current.get("pre_truncation_avg_amount_share_of_cutoff")) or 0.0),
            str(current.get("ticker") or ""),
            str(current.get("trade_date") or ""),
        ),
    )
    rank_gaps = [int(row.get("pre_truncation_rank_gap_to_cutoff") or 0) for row in ordered_rows if row.get("pre_truncation_rank_gap_to_cutoff") is not None]
    distinct_ticker_cases: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()
    for row in ordered_rows:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker or ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        distinct_ticker_cases.append(dict(row))

    min_rank_gap = min(rank_gaps) if rank_gaps else None
    avg_amount_shares = [_safe_float(row.get("pre_truncation_avg_amount_share_of_cutoff")) for row in ordered_rows]
    avg_amount_shares = [value for value in avg_amount_shares if value is not None]
    avg_amount_gate_shares = [_safe_float(row.get("avg_amount_share_of_min_gate")) for row in ordered_rows]
    avg_amount_gate_shares = [value for value in avg_amount_gate_shares if value is not None]
    cutoff_avg_amount_gate_shares = [_safe_float(row.get("pre_truncation_cutoff_avg_amount_share_of_min_gate")) for row in ordered_rows]
    cutoff_avg_amount_gate_shares = [value for value in cutoff_avg_amount_gate_shares if value is not None]
    avg_amount_gaps = [_safe_float(row.get("pre_truncation_avg_amount_gap_to_cutoff")) for row in ordered_rows]
    avg_amount_gaps = [value for value in avg_amount_gaps if value is not None]
    ranking_driver_counts = Counter(str(row.get("pre_truncation_ranking_driver") or "unknown") for row in ordered_rows)
    dominant_ranking_driver = ranking_driver_counts.most_common(1)[0][0] if ranking_driver_counts else None
    liquidity_gap_mode_counts = Counter(str(row.get("pre_truncation_liquidity_gap_mode") or "unknown") for row in ordered_rows)
    dominant_liquidity_gap_mode = liquidity_gap_mode_counts.most_common(1)[0][0] if liquidity_gap_mode_counts else None
    if min_rank_gap is None:
        max_share = max(avg_amount_shares) if avg_amount_shares else None
        if max_share is not None and max_share < 0.65:
            frontier_verdict = "far_below_cutoff_not_boundary"
        elif max_share is not None and max_share < 0.85:
            frontier_verdict = "mid_cutoff_gap"
        else:
            frontier_verdict = "no_rank_observability"
    elif min_rank_gap <= 20:
        frontier_verdict = "near_cutoff_boundary"
    elif min_rank_gap <= 100:
        frontier_verdict = "mid_cutoff_gap"
    else:
        frontier_verdict = "far_below_cutoff_not_boundary"

    return {
        "observed_case_count": truncation_case_count,
        "rank_observed_case_count": len(ordered_rows),
        "frontier_verdict": frontier_verdict,
        "closest_cases": ordered_rows[:5],
        "closest_distinct_ticker_cases": distinct_ticker_cases[:5],
        "ranking_driver_counts": {key: int(value) for key, value in ranking_driver_counts.most_common()},
        "dominant_ranking_driver": dominant_ranking_driver,
        "liquidity_gap_mode_counts": {key: int(value) for key, value in liquidity_gap_mode_counts.most_common()},
        "dominant_liquidity_gap_mode": dominant_liquidity_gap_mode,
        "avg_amount_share_of_cutoff_mean": round(sum(avg_amount_shares) / len(avg_amount_shares), 4) if avg_amount_shares else None,
        "avg_amount_share_of_cutoff_min": min(avg_amount_shares) if avg_amount_shares else None,
        "avg_amount_share_of_cutoff_max": max(avg_amount_shares) if avg_amount_shares else None,
        "avg_amount_share_of_min_gate_mean": round(sum(avg_amount_gate_shares) / len(avg_amount_gate_shares), 4) if avg_amount_gate_shares else None,
        "avg_amount_share_of_min_gate_min": min(avg_amount_gate_shares) if avg_amount_gate_shares else None,
        "avg_amount_share_of_min_gate_max": max(avg_amount_gate_shares) if avg_amount_gate_shares else None,
        "cutoff_avg_amount_share_of_min_gate_mean": round(sum(cutoff_avg_amount_gate_shares) / len(cutoff_avg_amount_gate_shares), 4) if cutoff_avg_amount_gate_shares else None,
        "cutoff_avg_amount_share_of_min_gate_min": min(cutoff_avg_amount_gate_shares) if cutoff_avg_amount_gate_shares else None,
        "cutoff_avg_amount_share_of_min_gate_max": max(cutoff_avg_amount_gate_shares) if cutoff_avg_amount_gate_shares else None,
        "avg_amount_gap_to_cutoff_mean": round(sum(avg_amount_gaps) / len(avg_amount_gaps), 4) if avg_amount_gaps else None,
        "avg_amount_gap_to_cutoff_min": min(avg_amount_gaps) if avg_amount_gaps else None,
        "avg_amount_gap_to_cutoff_max": max(avg_amount_gaps) if avg_amount_gaps else None,
        "min_rank_gap_to_cutoff": min_rank_gap,
        "max_rank_gap_to_cutoff": max(rank_gaps) if rank_gaps else None,
        "avg_rank_gap_to_cutoff": round(sum(rank_gaps) / len(rank_gaps), 4) if rank_gaps else None,
    }


def _build_action_queue(priority_ticker_dossiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for row in priority_ticker_dossiers:
        ticker = str(row.get("ticker") or "").strip()
        dominant_stage = str(row.get("dominant_blocking_stage") or "").strip()
        if not ticker or not dominant_stage:
            continue
        action_tier, title, next_step = _blocking_stage_details(dominant_stage, subject=ticker)
        queue.append(
            {
                "task_id": f"{ticker}_{dominant_stage}",
                "priority_rank": row.get("priority_rank"),
                "ticker": ticker,
                "dominant_blocking_stage": dominant_stage,
                "action_tier": action_tier,
                "title": title,
                "why_now": row.get("failure_reason"),
                "truncation_liquidity_profile": row.get("truncation_liquidity_profile"),
                "next_step": next_step,
            }
        )
    return queue


def _build_recommendation(
    dominant_stage: str | None,
    *,
    top_stage_tickers: dict[str, list[str]],
    truncation_frontier_summary: dict[str, Any] | None = None,
    focus_liquidity_profile_summary: dict[str, Any] | None = None,
    priority_handoff_branch_diagnoses: list[dict[str, Any]] | None = None,
    priority_handoff_branch_mechanisms: list[dict[str, Any]] | None = None,
    priority_handoff_branch_experiment_queue: list[dict[str, Any]] | None = None,
) -> str:
    if dominant_stage == "shadow_snapshot_legacy_unknown":
        return (
            f"当前 Layer A candidate_pool recall backlog 里至少有一部分样本仍停留在 legacy 空 shadow 快照状态："
            f"{top_stage_tickers.get('shadow_snapshot_legacy_unknown', [])} 还不能被直接解释成真实 upstream absence。"
            "下一步应先补齐 shadow 证据，再决定是否调整 recall 规则。"
        )
    if dominant_stage == "low_avg_amount_20d":
        return (
            f"当前 Layer A candidate_pool recall backlog 的主矛盾落在 20 日均成交额门槛：{top_stage_tickers.get('low_avg_amount_20d', [])} 持续卡在 {MIN_AVG_AMOUNT_20D} 万流动性线下。"
            "下一步应先审 liquidity gate，而不是继续调 watchlist 或 candidate-entry。"
        )
    if dominant_stage == "candidate_pool_truncated_after_filters":
        frontier_summary = dict(truncation_frontier_summary or {})
        focus_profile_summary = dict(focus_liquidity_profile_summary or {})
        frontier_verdict = str(frontier_summary.get("frontier_verdict") or "").strip()
        dominant_ranking_driver = str(frontier_summary.get("dominant_ranking_driver") or "").strip()
        dominant_liquidity_gap_mode = str(frontier_summary.get("dominant_liquidity_gap_mode") or "").strip()
        primary_focus_tickers = [dict(row) for row in list(focus_profile_summary.get("primary_focus_tickers") or [])]
        closest_distinct = list(frontier_summary.get("closest_distinct_ticker_cases") or [])
        closest_case = dict(closest_distinct[0]) if closest_distinct else {}
        if frontier_verdict == "far_below_cutoff_not_boundary" and closest_case:
            ranking_reason = "过滤后排序仍明显偏弱"
            if dominant_ranking_driver in {"avg_amount_20d_gap_dominant", "avg_amount_20d_gap"}:
                ranking_reason = "过滤后排序弱势仍主要由 20 日成交额落后于 cutoff 驱动"
            elif dominant_ranking_driver == "market_cap_tie_break_gap":
                ranking_reason = "过滤后排序弱势更像是 cutoff 附近的市值 tie-break 差距"
            gap_mode_reason = ""
            if dominant_liquidity_gap_mode == "well_above_gate_but_far_below_cutoff":
                gap_mode_reason = " 这些票已经明显高于最低流动性门槛，问题更像是通过 gate 后仍打不过 cutoff 竞争集。"
            elif dominant_liquidity_gap_mode == "barely_above_gate_and_far_below_cutoff":
                gap_mode_reason = " 这些票多数只是勉强高于最低流动性门槛，说明 gate 与 top300 cutoff 之间存在很长的质量走廊。"
            if closest_case.get("pre_truncation_rank") is None:
                share_of_cutoff = closest_case.get("pre_truncation_avg_amount_share_of_cutoff")
                cutoff_target = closest_case.get("pre_truncation_cutoff_avg_amount_20d")
                return (
                    f"当前 Layer A candidate_pool recall backlog 虽然都落在 top300 截断后，但最近 distinct ticker {closest_case.get('ticker')}@{closest_case.get('trade_date')} "
                    f"在缺 rank 观测时，avg_amount/cutoff 也只有 {share_of_cutoff}，目标 cutoff 成交额约为 {cutoff_target}。"
                    f"这说明当前主矛盾已经不是小幅 top300 边界调参，而是{ranking_reason}，下一步应优先拆解 liquidity / ranking source，而不是直接放宽 top300。{gap_mode_reason}"
                    f" 当前焦点 ticker 画像为 {[(row.get('ticker'), row.get('dominant_liquidity_gap_mode'), row.get('priority_handoff')) for row in primary_focus_tickers[:3]]}。"
                )
            return (
                f"当前 Layer A candidate_pool recall backlog 虽然都落在 top300 截断后，但最近的 distinct ticker 也只有 {closest_case.get('ticker')}@{closest_case.get('trade_date')}，"
                f"pre-truncation rank={closest_case.get('pre_truncation_rank')}，距 cutoff 仍有 {closest_case.get('pre_truncation_rank_gap_to_cutoff')} 名。"
                f"这说明当前主矛盾已经不是小幅 top300 边界调参，而是{ranking_reason}，下一步应优先拆解 liquidity / ranking source，而不是直接放宽 top300。{gap_mode_reason}"
                f" 当前焦点 ticker 画像为 {[(row.get('ticker'), row.get('dominant_liquidity_gap_mode'), row.get('priority_handoff')) for row in primary_focus_tickers[:3]]}。"
            )
        branch_diagnoses = [dict(row) for row in list(priority_handoff_branch_diagnoses or [])]
        branch_mechanisms = [dict(row) for row in list(priority_handoff_branch_mechanisms or [])]
        branch_experiment_queue = [dict(row) for row in list(priority_handoff_branch_experiment_queue or [])]
        if branch_diagnoses:
            mechanism_suffix = ""
            if branch_mechanisms:
                pressure_summary = str(branch_mechanisms[0].get("pressure_cluster_summary") or "").strip()
                repair_summary = str(branch_mechanisms[0].get("repair_hypothesis_summary") or "").strip()
                mechanism_suffix = f" 当前最重要的机制摘要是：{branch_mechanisms[0].get('mechanism_summary')}"
                if pressure_summary:
                    mechanism_suffix = f"{mechanism_suffix} 压力同伴结构显示：{pressure_summary}"
                if repair_summary:
                    mechanism_suffix = f"{mechanism_suffix} 当前优先修复假设是：{repair_summary}"
            if branch_experiment_queue:
                experiment_summary = str(branch_experiment_queue[0].get("prototype_summary") or "").strip()
                guardrail_summary = str(branch_experiment_queue[0].get("guardrail_summary") or "").strip()
                evaluation_summary = str(branch_experiment_queue[0].get("evaluation_summary") or "").strip()
                if experiment_summary:
                    mechanism_suffix = f"{mechanism_suffix} 当前优先实验原型是：{experiment_summary}"
                if evaluation_summary:
                    mechanism_suffix = f"{mechanism_suffix} 当前实验评估是：{evaluation_summary}"
                if guardrail_summary:
                    mechanism_suffix = f"{mechanism_suffix} 守门条件是：{guardrail_summary}"
            return (
                f"当前 Layer A candidate_pool recall backlog 的主矛盾虽然都落在 top300 截断，但已拆成分支车道："
                f"{[(row.get('priority_handoff'), row.get('tickers')) for row in branch_diagnoses[:3]]}。"
                f" {branch_diagnoses[0].get('diagnosis_summary')}{mechanism_suffix}"
            )
        return (
            f"当前 Layer A candidate_pool recall backlog 的主矛盾更像 top300 截断：{top_stage_tickers.get('candidate_pool_truncated_after_filters', [])} 通过过滤后仍未进入 snapshot。"
            "下一步应优先补 pre-truncation 排名观测与 frontier，而不是继续下游 recall 诊断。"
        )
    if dominant_stage == "low_estimated_liquidity":
        return (
            f"当前 Layer A candidate_pool recall backlog 的主矛盾落在当日估算流动性粗筛：{top_stage_tickers.get('low_estimated_liquidity', [])} 先被 1D liquidity gate 拦下。"
            "下一步应优先核对 turnover_rate/circ_mv 与粗筛门槛。"
        )
    if dominant_stage in {"st_excluded", "beijing_exchange_excluded", "new_listing_excluded", "suspended", "limit_up_excluded", "cooldown_excluded"}:
        return (
            f"当前 Layer A candidate_pool recall backlog 的主矛盾落在硬过滤阶段：{top_stage_tickers.get(dominant_stage, [])} 已在候选池前置规则里被挡下。"
            "下一步应先核对硬过滤规则是否符合当前策略边界。"
        )
    if dominant_stage == "missing_market_context":
        return "当前 Layer A candidate_pool recall dossier 还缺足够市场上下文，需先补 stock_basic/daily_basic/limit/cooldown 观测后再做稳定归因。"
    return "当前 Layer A candidate_pool recall dossier 没有形成单一主矛盾，继续累积 occurrence 证据再推进。"


def _build_next_actions(
    dominant_stage: str | None,
    *,
    top_stage_tickers: dict[str, list[str]],
    truncation_frontier_summary: dict[str, Any] | None = None,
    focus_liquidity_profile_summary: dict[str, Any] | None = None,
    priority_handoff_branch_diagnoses: list[dict[str, Any]] | None = None,
    priority_handoff_branch_mechanisms: list[dict[str, Any]] | None = None,
    priority_handoff_branch_experiment_queue: list[dict[str, Any]] | None = None,
) -> list[str]:
    actions: list[str] = []
    if dominant_stage == "shadow_snapshot_legacy_unknown":
        actions.append(f"先补 {top_stage_tickers.get('shadow_snapshot_legacy_unknown', [])} 的默认 shadow 快照证据，再判断是否存在真实 candidate_pool absence。")
    elif dominant_stage == "low_avg_amount_20d":
        actions.append(f"优先回查 {top_stage_tickers.get('low_avg_amount_20d', [])} 的 20 日均成交额门槛与 liquidity gate。")
    elif dominant_stage == "candidate_pool_truncated_after_filters":
        frontier_summary = dict(truncation_frontier_summary or {})
        focus_profile_summary = dict(focus_liquidity_profile_summary or {})
        frontier_verdict = str(frontier_summary.get("frontier_verdict") or "").strip()
        dominant_ranking_driver = str(frontier_summary.get("dominant_ranking_driver") or "").strip()
        dominant_liquidity_gap_mode = str(frontier_summary.get("dominant_liquidity_gap_mode") or "").strip()
        primary_focus_tickers = [dict(row) for row in list(focus_profile_summary.get("primary_focus_tickers") or [])]
        closest_distinct = list(frontier_summary.get("closest_distinct_ticker_cases") or [])
        if frontier_verdict == "far_below_cutoff_not_boundary" and closest_distinct:
            closest_case = dict(closest_distinct[0])
            if closest_case.get("pre_truncation_rank_gap_to_cutoff") is None:
                actions.append(
                    f"不要把 {top_stage_tickers.get('candidate_pool_truncated_after_filters', [])} 直接当作 top300 边界微调问题；最近 distinct 样本 {closest_case.get('ticker')} 的 avg_amount/cutoff 也只有 {closest_case.get('pre_truncation_avg_amount_share_of_cutoff')}。"
                )
            else:
                actions.append(
                    f"不要把 {top_stage_tickers.get('candidate_pool_truncated_after_filters', [])} 直接当作 top300 边界微调问题；最近 distinct 样本 {closest_case.get('ticker')} 也还差 {closest_case.get('pre_truncation_rank_gap_to_cutoff')} 名。"
                )
            if dominant_ranking_driver in {"avg_amount_20d_gap_dominant", "avg_amount_20d_gap"}:
                actions.append("优先拆解过滤后排序里的 20 日成交额落差，而不是先调 MAX_CANDIDATE_POOL_SIZE。")
            elif dominant_ranking_driver == "market_cap_tie_break_gap":
                actions.append("优先复核 cutoff 附近的市值 tie-break，而不是直接扩大候选池上限。")
            else:
                actions.append("优先拆解过滤后排序为何仍然明显弱于 cutoff，而不是先调 MAX_CANDIDATE_POOL_SIZE。")
            if dominant_liquidity_gap_mode == "well_above_gate_but_far_below_cutoff":
                actions.append("这些票多数已显著高于最低流动性门槛，下一步不要优先放松 MIN_AVG_AMOUNT_20D，而要查上游流动性来源与竞争集。")
            elif dominant_liquidity_gap_mode == "barely_above_gate_and_far_below_cutoff":
                actions.append("这些票多数只是勉强高于最低流动性门槛，下一步应同时复核 liquidity gate 与 cutoff 竞争强度。")
            if primary_focus_tickers:
                actions.append(f"按焦点 ticker 画像拆分后续 handoff：{[(row.get('ticker'), row.get('priority_handoff')) for row in primary_focus_tickers[:3]]}。")
            for diagnosis in list(priority_handoff_branch_diagnoses or [])[:2]:
                next_step = str(dict(diagnosis).get("next_step") or "").strip()
                if next_step:
                    actions.append(next_step)
            for mechanism in list(priority_handoff_branch_mechanisms or [])[:2]:
                summary = str(dict(mechanism).get("mechanism_summary") or "").strip()
                if summary:
                    actions.append(summary)
                pressure_summary = str(dict(mechanism).get("pressure_cluster_summary") or "").strip()
                if pressure_summary:
                    actions.append(pressure_summary)
                repair_summary = str(dict(mechanism).get("repair_hypothesis_summary") or "").strip()
                if repair_summary:
                    actions.append(repair_summary)
            for experiment in list(priority_handoff_branch_experiment_queue or [])[:2]:
                prototype_summary = str(dict(experiment).get("prototype_summary") or "").strip()
                if prototype_summary:
                    actions.append(prototype_summary)
                evaluation_summary = str(dict(experiment).get("evaluation_summary") or "").strip()
                if evaluation_summary:
                    actions.append(evaluation_summary)
                success_signal = str(dict(experiment).get("success_signal") or "").strip()
                if success_signal:
                    actions.append(success_signal)
        else:
            actions.append(f"优先补 {top_stage_tickers.get('candidate_pool_truncated_after_filters', [])} 的 pre-truncation 排名观测与 top300 frontier。")
    elif dominant_stage == "low_estimated_liquidity":
        actions.append(f"优先回查 {top_stage_tickers.get('low_estimated_liquidity', [])} 的 turnover_rate / circ_mv 与当日粗筛门槛。")
    elif dominant_stage in {"st_excluded", "beijing_exchange_excluded", "new_listing_excluded", "suspended", "limit_up_excluded", "cooldown_excluded"}:
        actions.append(f"优先核对 {top_stage_tickers.get(dominant_stage, [])} 的 Layer A 硬过滤规则是否需要调整。")
    elif dominant_stage == "missing_market_context":
        actions.append("优先补齐 stock_basic / daily_basic / limit / cooldown 数据，再继续 Layer A root-cause 诊断。")
    if not actions:
        actions.append("继续保留 Layer A candidate_pool recall 观察，并累积更多 absent_from_candidate_pool occurrence。")
    return actions[:4]


def analyze_btst_candidate_pool_recall_dossier(
    tradeable_opportunity_pool_path: str | Path,
    *,
    watchlist_recall_dossier_path: str | Path | None = None,
    failure_dossier_path: str | Path | None = None,
    priority_limit: int = DEFAULT_PRIORITY_LIMIT,
    diagnostics_override: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tradeable_pool = _load_json(tradeable_opportunity_pool_path)
    watchlist_recall_dossier = _safe_load_json(watchlist_recall_dossier_path)
    failure_dossier = _safe_load_json(failure_dossier_path)
    resolved_tradeable_pool_path = Path(tradeable_opportunity_pool_path).expanduser().resolve()
    reports_root = Path(tradeable_pool.get("reports_root") or resolved_tradeable_pool_path.parent).expanduser().resolve()
    snapshots_root = reports_root.parent / "snapshots"
    focus_tickers = _build_focus_tickers(
        tradeable_pool,
        watchlist_recall_dossier,
        failure_dossier,
        priority_limit=priority_limit,
    )
    watchlist_trade_date_allowlist = _build_trade_date_allowlist(watchlist_recall_dossier)
    priority_ticker_dossiers = _build_priority_ticker_dossiers(
        focus_tickers,
        tradeable_pool,
        watchlist_trade_date_allowlist=watchlist_trade_date_allowlist,
        snapshots_root=snapshots_root,
        diagnostics_override=diagnostics_override,
    )
    priority_stage_counts = _count_stages(priority_ticker_dossiers, key="dominant_blocking_stage")
    dominant_stage = _dominant_stage(priority_stage_counts)
    top_stage_tickers = _build_top_stage_tickers(priority_ticker_dossiers)
    truncation_frontier_summary = _build_truncation_frontier_summary(priority_ticker_dossiers)
    focus_liquidity_profile_summary = _build_focus_liquidity_profile_summary(priority_ticker_dossiers)
    priority_handoff_branch_diagnoses = _build_priority_handoff_branch_diagnoses(priority_ticker_dossiers)
    priority_handoff_branch_mechanisms = _build_priority_handoff_branch_mechanisms(priority_ticker_dossiers)
    priority_handoff_branch_experiment_queue = _build_priority_handoff_branch_experiment_queue(
        priority_handoff_branch_mechanisms,
        priority_ticker_dossiers,
    )
    action_queue = _build_action_queue(priority_ticker_dossiers)
    recommendation = _build_recommendation(
        dominant_stage,
        top_stage_tickers=top_stage_tickers,
        truncation_frontier_summary=truncation_frontier_summary,
        focus_liquidity_profile_summary=focus_liquidity_profile_summary,
        priority_handoff_branch_diagnoses=priority_handoff_branch_diagnoses,
        priority_handoff_branch_mechanisms=priority_handoff_branch_mechanisms,
        priority_handoff_branch_experiment_queue=priority_handoff_branch_experiment_queue,
    )
    next_actions = _build_next_actions(
        dominant_stage,
        top_stage_tickers=top_stage_tickers,
        truncation_frontier_summary=truncation_frontier_summary,
        focus_liquidity_profile_summary=focus_liquidity_profile_summary,
        priority_handoff_branch_diagnoses=priority_handoff_branch_diagnoses,
        priority_handoff_branch_mechanisms=priority_handoff_branch_mechanisms,
        priority_handoff_branch_experiment_queue=priority_handoff_branch_experiment_queue,
    )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tradeable_opportunity_pool_path": resolved_tradeable_pool_path.as_posix(),
        "watchlist_recall_dossier_path": Path(watchlist_recall_dossier_path).expanduser().resolve().as_posix() if watchlist_recall_dossier_path else None,
        "failure_dossier_path": Path(failure_dossier_path).expanduser().resolve().as_posix() if failure_dossier_path else None,
        "reports_root": reports_root.as_posix(),
        "snapshots_root": snapshots_root.as_posix(),
        "priority_limit": max(int(priority_limit), 0),
        "focus_tickers": focus_tickers,
        "priority_stage_counts": priority_stage_counts,
        "dominant_stage": dominant_stage,
        "top_stage_tickers": top_stage_tickers,
        "truncation_frontier_summary": truncation_frontier_summary,
        "focus_liquidity_profile_summary": focus_liquidity_profile_summary,
        "priority_handoff_branch_diagnoses": priority_handoff_branch_diagnoses,
        "priority_handoff_branch_mechanisms": priority_handoff_branch_mechanisms,
        "priority_handoff_branch_experiment_queue": priority_handoff_branch_experiment_queue,
        "priority_ticker_dossiers": priority_ticker_dossiers,
        "action_queue": action_queue,
        "next_actions": next_actions,
        "recommendation": recommendation,
    }


def render_btst_candidate_pool_recall_dossier_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    branch_experiment_queue = list(analysis.get("priority_handoff_branch_experiment_queue") or [])
    lines.append("# BTST Candidate Pool Recall Dossier")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- tradeable_opportunity_pool_path: {analysis.get('tradeable_opportunity_pool_path')}")
    lines.append(f"- watchlist_recall_dossier_path: {analysis.get('watchlist_recall_dossier_path')}")
    lines.append(f"- failure_dossier_path: {analysis.get('failure_dossier_path')}")
    lines.append(f"- priority_stage_counts: {analysis.get('priority_stage_counts')}")
    lines.append(f"- dominant_stage: {analysis.get('dominant_stage')}")
    lines.append(f"- top_stage_tickers: {analysis.get('top_stage_tickers')}")
    lines.append(f"- truncation_frontier_summary: {analysis.get('truncation_frontier_summary')}")
    lines.append(f"- priority_handoff_branch_diagnoses: {analysis.get('priority_handoff_branch_diagnoses')}")
    lines.append(f"- priority_handoff_branch_mechanisms: {analysis.get('priority_handoff_branch_mechanisms')}")
    lines.append("- priority_handoff_branch_experiment_queue: structured_summary")
    lines.append(f"- priority_handoff_branch_experiment_queue_count: {len(branch_experiment_queue)}")
    for experiment in branch_experiment_queue[:3]:
        lines.append(
            f"- branch_experiment: task_id={experiment.get('task_id')} handoff={experiment.get('priority_handoff')} readiness={experiment.get('prototype_readiness')} tickers={experiment.get('tickers')}"
        )
        lines.append(f"  prototype_summary: {experiment.get('prototype_summary')}")
        lines.append(f"  evaluation_summary: {experiment.get('evaluation_summary')}")
        lines.append(f"  guardrail_summary: {experiment.get('guardrail_summary')}")
    lines.append(f"- recommendation: {analysis.get('recommendation')}")
    lines.append("")
    lines.append("## Priority Ticker Dossiers")
    for row in list(analysis.get("priority_ticker_dossiers") or []):
        lines.append(
            f"- rank={row.get('priority_rank')} ticker={row.get('ticker')} dominant_blocking_stage={row.get('dominant_blocking_stage')} occurrence_count={row.get('occurrence_count')}"
        )
        lines.append(f"  blocking_stage_counts: {row.get('blocking_stage_counts')}")
        lines.append(f"  failure_reason: {row.get('failure_reason')}")
        lines.append(f"  next_step: {row.get('next_step')}")
        lines.append(f"  closest_pre_truncation_gap: {row.get('closest_pre_truncation_gap')}")
        lines.append(f"  truncation_ranking_summary: {row.get('truncation_ranking_summary')}")
        for evidence_row in list(row.get("occurrence_evidence") or [])[:6]:
            lines.append(
                f"  occurrence: trade_date={evidence_row.get('trade_date')} report_dir={evidence_row.get('report_dir')} blocking_stage={evidence_row.get('blocking_stage')} candidate_pool_visible={evidence_row.get('candidate_pool_visible')} candidate_pool_rank={evidence_row.get('candidate_pool_rank')} pre_truncation_rank={evidence_row.get('pre_truncation_rank')} pre_truncation_rank_gap_to_cutoff={evidence_row.get('pre_truncation_rank_gap_to_cutoff')} pre_truncation_cutoff_ticker={evidence_row.get('pre_truncation_cutoff_ticker')} pre_truncation_avg_amount_share_of_cutoff={evidence_row.get('pre_truncation_avg_amount_share_of_cutoff')} avg_amount_share_of_min_gate={evidence_row.get('avg_amount_share_of_min_gate')} pre_truncation_liquidity_gap_mode={evidence_row.get('pre_truncation_liquidity_gap_mode')} pre_truncation_ranking_driver={evidence_row.get('pre_truncation_ranking_driver')} estimated_amount_1d={evidence_row.get('estimated_amount_1d')} avg_amount_20d={evidence_row.get('avg_amount_20d')}"
            )
            frontier_window = list(evidence_row.get("pre_truncation_frontier_window") or [])
            if frontier_window:
                lines.append(f"  frontier_window: {frontier_window}")
    if not list(analysis.get("priority_ticker_dossiers") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Action Queue")
    for row in list(analysis.get("action_queue") or []):
        lines.append(
            f"- task_id={row.get('task_id')} ticker={row.get('ticker')} action_tier={row.get('action_tier')} dominant_blocking_stage={row.get('dominant_blocking_stage')}"
        )
        lines.append(f"  why_now: {row.get('why_now')}")
        lines.append(f"  next_step: {row.get('next_step')}")
    if not list(analysis.get("action_queue") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Next Actions")
    for item in list(analysis.get("next_actions") or []):
        lines.append(f"- {item}")
    if not list(analysis.get("next_actions") or []):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose why absent_from_candidate_pool backlog names fail inside Layer A candidate_pool construction.")
    parser.add_argument("--tradeable-opportunity-pool", default=str(DEFAULT_TRADEABLE_OPPORTUNITY_POOL_PATH))
    parser.add_argument("--watchlist-recall-dossier", default=str(DEFAULT_WATCHLIST_RECALL_DOSSIER_PATH))
    parser.add_argument("--failure-dossier", default=str(DEFAULT_FAILURE_DOSSIER_PATH))
    parser.add_argument("--priority-limit", type=int, default=DEFAULT_PRIORITY_LIMIT)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_recall_dossier(
        args.tradeable_opportunity_pool,
        watchlist_recall_dossier_path=args.watchlist_recall_dossier or None,
        failure_dossier_path=args.failure_dossier or None,
        priority_limit=args.priority_limit,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_candidate_pool_recall_dossier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
