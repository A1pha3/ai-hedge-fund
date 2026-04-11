"""
Layer A 候选池构建器 — 全市场快筛

实现框架 §1 先验约束矩阵 + §5.1 Step 1：
  1. 获取全 A 股基本信息（~5000 只）
  2. 排除 ST / *ST 标的（名称包含 ST）
    3. 排除北交所标的（市场 = 'BJ' / '北交所'、ts_code = '.BJ' 或代码 4xxxxx / 8xxxxx / 92xxxx）
  4. 排除上市不满 60 个交易日的新股/次新股
  5. 排除当日停牌标的
  6. 排除当日涨停标的（买入排队失败）
  7. 排除停牌超过 5 日后复牌未满 3 个正常交易日的标的（简化实现）
  8. 排除近 20 日平均成交额 < 5000 万元的低流动性标的
  9. 排除被冲突仲裁规则一标记的"回避冷却期"标的（15 个交易日）
"""

import json
import os
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Set

import time

import pandas as pd

from src.screening.candidate_pool_compute_helpers import (
    apply_estimated_liquidity_filter_with_logging,
    apply_cooldown_filter,
    build_candidate_stocks,
    build_daily_basic_maps,
    filter_low_liquidity_candidates,
    load_amount_map_and_low_liquidity_codes,
    normalize_sw_map,
    resolve_cooldown_tickers,
)
from src.screening.candidate_pool_shadow_helpers import (
    build_shadow_summary_payload,
    build_cooldown_review_shadow_payload,
    build_shadow_lane_payload,
    classify_overflow_candidate,
    select_shadow_rows,
)
from src.screening.models import CandidateStock
from src.tools.tushare_api import (
    _get_pro,
    _cached_tushare_dataframe_call,
    get_all_stock_basic,
    get_daily_basic_batch,
    get_limit_list,
    get_suspend_list,
    get_sw_industry_classification,
)

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SNAPSHOT_DIR = _PROJECT_ROOT / "data" / "snapshots"
_COOLDOWN_FILE = _SNAPSHOT_DIR / "cooldown_registry.json"

# 常量
MIN_LISTING_DAYS = 60
MIN_AVG_AMOUNT_20D = 5000  # 万元
MIN_ESTIMATED_AMOUNT_1D = 3000  # 万元，使用换手率 * 流通市值做粗筛
COOLDOWN_TRADING_DAYS = 15
DISCLOSURE_MONTHS = {4, 8, 10}  # 财报窗口月份
TUSHARE_DAILY_CALLS_PER_MINUTE = 200
TUSHARE_DAILY_BATCH_SIZE = 50
MAX_CANDIDATE_POOL_SIZE = int(os.getenv("MAX_CANDIDATE_POOL_SIZE", "300"))
BTST_LIQUIDITY_RANK_BUCKET = float(os.getenv("CANDIDATE_POOL_BTST_LIQUIDITY_RANK_BUCKET", "2500"))
SHADOW_LIQUIDITY_CORRIDOR_MAX_TICKERS = int(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_MAX_TICKERS", "4"))
SHADOW_REBUCKET_MAX_TICKERS = int(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_MAX_TICKERS", "1"))
SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE", "3.0"))
SHADOW_LIQUIDITY_CORRIDOR_MAX_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_MAX_CUTOFF_SHARE", "0.20"))
SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE", "2.25"))
SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MAX_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MAX_CUTOFF_SHARE", "0.30"))
SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE", "0.075"))
SHADOW_LIQUIDITY_CORRIDOR_VISIBILITY_GAP_MAX_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_VISIBILITY_GAP_MAX_CUTOFF_SHARE", "0.40"))
SHADOW_REBUCKET_MIN_GATE_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_MIN_GATE_SHARE", "8.0"))
SHADOW_REBUCKET_MIN_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_MIN_CUTOFF_SHARE", "0.30"))
SHADOW_REBUCKET_MAX_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_MAX_CUTOFF_SHARE", "0.80"))
SHADOW_REBUCKET_FOCUS_MIN_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_FOCUS_MIN_CUTOFF_SHARE", "0.20"))
SHADOW_REBUCKET_VISIBILITY_GAP_MIN_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_VISIBILITY_GAP_MIN_CUTOFF_SHARE", "0.15"))
SHADOW_FOCUS_TICKERS = {item.strip() for item in os.getenv("CANDIDATE_POOL_SHADOW_FOCUS_TICKERS", "").split(",") if item.strip()}
SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS = {
    item.strip() for item in os.getenv("CANDIDATE_POOL_SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS", "").split(",") if item.strip()
}
SHADOW_FOCUS_REBUCKET_TICKERS = {item.strip() for item in os.getenv("CANDIDATE_POOL_SHADOW_FOCUS_REBUCKET_TICKERS", "").split(",") if item.strip()}
SHADOW_VISIBILITY_GAP_TICKERS = {item.strip() for item in os.getenv("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_TICKERS", "").split(",") if item.strip()}
SHADOW_VISIBILITY_GAP_LIQUIDITY_CORRIDOR_TICKERS = {
    item.strip() for item in os.getenv("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_LIQUIDITY_CORRIDOR_TICKERS", "").split(",") if item.strip()
}
SHADOW_VISIBILITY_GAP_REBUCKET_TICKERS = {
    item.strip() for item in os.getenv("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_REBUCKET_TICKERS", "").split(",") if item.strip()
}
BEIJING_EXCHANGE_SYMBOL_PREFIXES: tuple[str, ...] = ("4", "8", "92")


def _candidate_pool_snapshot_path(trade_date: str, pool_size: Optional[int] = None) -> Path:
    resolved_pool_size = MAX_CANDIDATE_POOL_SIZE if pool_size is None else int(pool_size)
    return _SNAPSHOT_DIR / f"candidate_pool_{trade_date}_top{resolved_pool_size}.json"


def _candidate_pool_legacy_snapshot_path(trade_date: str) -> Path:
    return _SNAPSHOT_DIR / f"candidate_pool_{trade_date}.json"


def _candidate_pool_shadow_snapshot_path(trade_date: str, pool_size: Optional[int] = None) -> Path:
    resolved_pool_size = MAX_CANDIDATE_POOL_SIZE if pool_size is None else int(pool_size)
    focus_signature = _shadow_focus_signature()
    focus_suffix = f"_focus_{focus_signature}" if focus_signature else ""
    return _SNAPSHOT_DIR / f"candidate_pool_{trade_date}_top{resolved_pool_size}_shadow{focus_suffix}.json"


def _load_candidate_pool_snapshot(snapshot_path: Path) -> List[CandidateStock]:
    with open(snapshot_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [CandidateStock(**item) for item in data]


def _normalize_shadow_summary(shadow_summary: dict[str, Any], *, shadow_candidates: list[CandidateStock]) -> dict[str, Any]:
    normalized_summary = dict(shadow_summary or {})
    if "shadow_recall_complete" in normalized_summary and "shadow_recall_status" in normalized_summary:
        return normalized_summary

    has_shadow_entries = bool(normalized_summary.get("tickers")) or bool(shadow_candidates)
    if has_shadow_entries:
        normalized_summary.setdefault("shadow_recall_complete", True)
        normalized_summary.setdefault("shadow_recall_status", "computed_legacy")
        return normalized_summary

    normalized_summary.setdefault("shadow_recall_complete", False)
    normalized_summary.setdefault("shadow_recall_status", "legacy_unknown")
    return normalized_summary


def _write_candidate_pool_snapshot(snapshot_path: Path, candidates: List[CandidateStock]) -> None:
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump([candidate.model_dump() for candidate in candidates], f, ensure_ascii=False, indent=2)


def _load_candidate_pool_shadow_snapshot(snapshot_path: Path) -> dict[str, Any]:
    with open(snapshot_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    shadow_candidates = [CandidateStock(**item) for item in list(payload.get("shadow_candidates") or [])]
    return {
        "selected_candidates": [CandidateStock(**item) for item in list(payload.get("selected_candidates") or [])],
        "shadow_candidates": shadow_candidates,
        "shadow_summary": _normalize_shadow_summary(
            dict(payload.get("shadow_summary") or {}),
            shadow_candidates=shadow_candidates,
        ),
    }


def _write_candidate_pool_shadow_snapshot(snapshot_path: Path, *, selected_candidates: List[CandidateStock], shadow_candidates: List[CandidateStock], shadow_summary: dict[str, Any]) -> None:
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "selected_candidates": [candidate.model_dump() for candidate in selected_candidates],
                "shadow_candidates": [candidate.model_dump() for candidate in shadow_candidates],
                "shadow_summary": shadow_summary,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def _candidate_liquidity_sort_key(candidate: CandidateStock) -> tuple[int, float, float, str]:
    avg_amount = float(candidate.avg_volume_20d)
    market_cap = float(candidate.market_cap)
    liquidity_band = int(avg_amount / max(BTST_LIQUIDITY_RANK_BUCKET, 1.0))
    return (liquidity_band, -market_cap, avg_amount, str(candidate.ticker))


def _shadow_focus_payload() -> dict[str, list[str]]:
    return {
        "all": sorted(SHADOW_FOCUS_TICKERS),
        "layer_a_liquidity_corridor": sorted(SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS),
        "post_gate_liquidity_competition": sorted(SHADOW_FOCUS_REBUCKET_TICKERS),
        "visibility_gap_all": sorted(SHADOW_VISIBILITY_GAP_TICKERS),
        "visibility_gap_layer_a_liquidity_corridor": sorted(SHADOW_VISIBILITY_GAP_LIQUIDITY_CORRIDOR_TICKERS),
        "visibility_gap_post_gate_liquidity_competition": sorted(SHADOW_VISIBILITY_GAP_REBUCKET_TICKERS),
    }


def _shadow_focus_signature() -> str:
    focus_payload = _shadow_focus_payload()
    if not any(focus_payload.values()):
        return ""
    digest = hashlib.sha1(json.dumps(focus_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return digest[:10]


def _resolve_shadow_focus_tickers(*, lane: str) -> set[str]:
    lane_specific_focus: set[str] = set()
    if lane == "layer_a_liquidity_corridor":
        lane_specific_focus = SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS
    elif lane == "post_gate_liquidity_competition":
        lane_specific_focus = SHADOW_FOCUS_REBUCKET_TICKERS
    return set(SHADOW_FOCUS_TICKERS) | set(lane_specific_focus)


def _resolve_shadow_visibility_gap_tickers(*, lane: str) -> set[str]:
    lane_specific_focus: set[str] = set()
    if lane == "layer_a_liquidity_corridor":
        lane_specific_focus = SHADOW_VISIBILITY_GAP_LIQUIDITY_CORRIDOR_TICKERS
    elif lane == "post_gate_liquidity_competition":
        lane_specific_focus = SHADOW_VISIBILITY_GAP_REBUCKET_TICKERS
    return set(SHADOW_VISIBILITY_GAP_TICKERS) | set(lane_specific_focus)


def _resolve_cooldown_shadow_review_tickers() -> set[str]:
    return (
        set(SHADOW_FOCUS_TICKERS)
        | set(SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS)
        | set(SHADOW_FOCUS_REBUCKET_TICKERS)
        | set(SHADOW_VISIBILITY_GAP_TICKERS)
        | set(SHADOW_VISIBILITY_GAP_LIQUIDITY_CORRIDOR_TICKERS)
        | set(SHADOW_VISIBILITY_GAP_REBUCKET_TICKERS)
    )


def _init_focus_filter_diagnostics(stock_df: pd.DataFrame, *, focus_tickers: set[str]) -> dict[str, dict[str, Any]]:
    available_symbols = set(stock_df["symbol"].astype(str).tolist()) if "symbol" in stock_df else set()
    return {
        ticker: {
            "ticker": ticker,
            "present_in_stock_basic": ticker in available_symbols,
            "first_removed_stage": None,
            "final_visibility": "pending",
        }
        for ticker in sorted(focus_tickers)
    }


def _record_focus_filter_stage(
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    *,
    stage: str,
    active_symbols: set[str],
) -> None:
    if not focus_filter_diagnostics:
        return
    for entry in focus_filter_diagnostics.values():
        visible = entry["ticker"] in active_symbols
        entry[f"visible_after_{stage}"] = visible
        if entry["present_in_stock_basic"] and entry["first_removed_stage"] is None and not visible:
            entry["first_removed_stage"] = stage


def _finalize_focus_filter_diagnostics(
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    *,
    candidate_tickers: set[str],
    cooldown_review_tickers: set[str],
    selected_tickers: set[str],
    shadow_tickers: set[str],
) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    for ticker in sorted(focus_filter_diagnostics):
        entry = dict(focus_filter_diagnostics[ticker])
        if not entry["present_in_stock_basic"]:
            entry["final_visibility"] = "missing_from_stock_basic"
        elif ticker in selected_tickers:
            entry["final_visibility"] = "selected_pool"
        elif ticker in shadow_tickers:
            entry["final_visibility"] = "shadow_pool"
        elif ticker in candidate_tickers:
            entry["final_visibility"] = "overflow_pool"
        elif ticker in cooldown_review_tickers:
            entry["final_visibility"] = "cooldown_review_pool"
        else:
            entry["final_visibility"] = "filtered_out"
        finalized.append(entry)
    return finalized


def _build_shadow_candidate_pool_payload(
    candidates: List[CandidateStock],
    *,
    pool_size: int,
    cooldown_review_candidates: Optional[List[CandidateStock]] = None,
    focus_filter_diagnostics: Optional[list[dict[str, Any]]] = None,
) -> tuple[List[CandidateStock], List[CandidateStock], dict[str, Any]]:
    ranked_candidates = sorted(candidates, key=_candidate_liquidity_sort_key, reverse=True)
    selected_candidates = [candidate.model_copy(update={"candidate_pool_rank": rank}) for rank, candidate in enumerate(ranked_candidates[:pool_size], start=1)]
    cooldown_review_candidates = list(cooldown_review_candidates or [])
    cutoff_avg_volume = round(float(ranked_candidates[-1].avg_volume_20d), 4) if ranked_candidates else 0.0
    cutoff_reference = max(float(selected_candidates[-1].avg_volume_20d), 1.0) if selected_candidates else 1.0

    shadow_candidates: list[CandidateStock] = []
    shadow_entries: list[dict[str, Any]] = []

    if cooldown_review_candidates:
        cooldown_shadow_candidates, cooldown_shadow_entries = build_cooldown_review_shadow_payload(
            candidates=cooldown_review_candidates,
            cutoff_reference=cutoff_reference,
            min_avg_amount_20d=float(MIN_AVG_AMOUNT_20D),
            review_focus_tickers=_resolve_cooldown_shadow_review_tickers(),
            visibility_gap_tickers=set(SHADOW_VISIBILITY_GAP_TICKERS),
        )
        shadow_candidates.extend(cooldown_shadow_candidates)
        shadow_entries.extend(cooldown_shadow_entries)

    if len(ranked_candidates) <= pool_size:
        return selected_candidates, shadow_candidates, build_shadow_summary_payload(
            pool_size=pool_size,
            selected_count=len(selected_candidates),
            overflow_count=0,
            selected_cutoff_avg_volume_20d=cutoff_avg_volume,
            shadow_candidates=shadow_candidates,
            shadow_entries=shadow_entries,
            focus_signature=_shadow_focus_signature(),
            focus_filter_diagnostics=focus_filter_diagnostics,
        )

    cutoff_avg_volume = max(float(ranked_candidates[pool_size - 1].avg_volume_20d), 1.0)
    overflow_candidates = ranked_candidates[pool_size:]
    corridor_candidates: list[tuple[float, int, CandidateStock, bool, bool]] = []
    rebucket_candidates: list[tuple[float, int, CandidateStock, bool, bool]] = []
    corridor_focus_tickers = _resolve_shadow_focus_tickers(lane="layer_a_liquidity_corridor")
    rebucket_focus_tickers = _resolve_shadow_focus_tickers(lane="post_gate_liquidity_competition")
    corridor_visibility_gap_tickers = _resolve_shadow_visibility_gap_tickers(lane="layer_a_liquidity_corridor")
    rebucket_visibility_gap_tickers = _resolve_shadow_visibility_gap_tickers(lane="post_gate_liquidity_competition")

    for rank, candidate in enumerate(overflow_candidates, start=pool_size + 1):
        cutoff_share = round(float(candidate.avg_volume_20d) / cutoff_avg_volume, 4)
        min_gate_share = round(float(candidate.avg_volume_20d) / float(MIN_AVG_AMOUNT_20D), 4)
        classified_row = classify_overflow_candidate(
            candidate=candidate,
            rank=rank,
            cutoff_share=cutoff_share,
            min_gate_share=min_gate_share,
            corridor_focus_tickers=corridor_focus_tickers,
            rebucket_focus_tickers=rebucket_focus_tickers,
            corridor_visibility_gap_tickers=corridor_visibility_gap_tickers,
            rebucket_visibility_gap_tickers=rebucket_visibility_gap_tickers,
            corridor_min_gate_share=SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE,
            corridor_max_cutoff_share=SHADOW_LIQUIDITY_CORRIDOR_MAX_CUTOFF_SHARE,
            corridor_focus_min_gate_share=SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE,
            corridor_focus_max_cutoff_share=SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MAX_CUTOFF_SHARE,
            corridor_focus_low_gate_max_cutoff_share=SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE,
            corridor_visibility_gap_max_cutoff_share=SHADOW_LIQUIDITY_CORRIDOR_VISIBILITY_GAP_MAX_CUTOFF_SHARE,
            rebucket_min_gate_share=SHADOW_REBUCKET_MIN_GATE_SHARE,
            rebucket_min_cutoff_share=SHADOW_REBUCKET_MIN_CUTOFF_SHARE,
            rebucket_max_cutoff_share=SHADOW_REBUCKET_MAX_CUTOFF_SHARE,
            rebucket_focus_min_cutoff_share=SHADOW_REBUCKET_FOCUS_MIN_CUTOFF_SHARE,
            rebucket_visibility_gap_min_cutoff_share=SHADOW_REBUCKET_VISIBILITY_GAP_MIN_CUTOFF_SHARE,
        )
        if classified_row is None:
            continue
        lane, row = classified_row
        if lane == "layer_a_liquidity_corridor":
            corridor_candidates.append(row)
        else:
            rebucket_candidates.append(row)

    for rows, max_tickers, lane, reason, rank_key in [
        (
            corridor_candidates,
            SHADOW_LIQUIDITY_CORRIDOR_MAX_TICKERS,
            "layer_a_liquidity_corridor",
            "upstream_base_liquidity_uplift_shadow",
            "gate_share_score",
        ),
        (
            rebucket_candidates,
            SHADOW_REBUCKET_MAX_TICKERS,
            "post_gate_liquidity_competition",
            "post_gate_liquidity_competition_shadow",
            "cutoff_share_score",
        ),
    ]:
        focus_tickers = _resolve_shadow_focus_tickers(lane=lane)
        visibility_gap_tickers = _resolve_shadow_visibility_gap_tickers(lane=lane)
        selected_rows = select_shadow_rows(
            rows=rows,
            max_tickers=max_tickers,
            focus_tickers=focus_tickers,
            visibility_gap_tickers=visibility_gap_tickers,
            liquidity_sort_key=_candidate_liquidity_sort_key,
        )
        lane_shadow_candidates, lane_shadow_entries = build_shadow_lane_payload(
            selected_rows=selected_rows,
            cutoff_reference=cutoff_avg_volume,
            min_avg_amount_20d=float(MIN_AVG_AMOUNT_20D),
            lane=lane,
            reason=reason,
            rank_key=rank_key,
            focus_tickers=focus_tickers,
            visibility_gap_tickers=visibility_gap_tickers,
        )
        shadow_candidates.extend(lane_shadow_candidates)
        shadow_entries.extend(lane_shadow_entries)

    return selected_candidates, shadow_candidates, build_shadow_summary_payload(
        pool_size=pool_size,
        selected_count=len(selected_candidates),
        overflow_count=len(overflow_candidates),
        selected_cutoff_avg_volume_20d=round(cutoff_avg_volume, 4),
        shadow_candidates=shadow_candidates,
        shadow_entries=shadow_entries,
        focus_signature=_shadow_focus_signature(),
        focus_filter_diagnostics=focus_filter_diagnostics,
    )


def _build_shadow_summary_from_selected_candidates(selected_candidates: List[CandidateStock], *, pool_size: int) -> dict[str, Any]:
    cutoff_avg_volume = round(float(selected_candidates[-1].avg_volume_20d), 4) if selected_candidates else 0.0
    return {
        "pool_size": pool_size,
        "selected_count": len(selected_candidates),
        "overflow_count": 0,
        "selected_cutoff_avg_volume_20d": cutoff_avg_volume,
        "lane_counts": {},
        "selected_tickers": [],
        "focus_tickers": [],
        "visibility_gap_tickers": [],
        "focus_signature": _shadow_focus_signature(),
        "shadow_recall_complete": False,
        "shadow_recall_status": "selected_cache_backfill",
        "tickers": [],
        "focus_filter_diagnostics": [],
    }


def _compute_candidate_pool_candidates(
    trade_date: str,
    cooldown_tickers: Optional[Set[str]] = None,
) -> tuple[List[CandidateStock], List[CandidateStock], list[dict[str, Any]]]:
    """计算未截断的候选池，供主池与 shadow recall 共同消费。"""
    pro = _get_pro()
    if pro is None:
        print("[CandidatePool] Tushare 未初始化，无法构建候选池")
        return [], [], []

    stock_df = get_all_stock_basic()
    if stock_df is None or stock_df.empty:
        print("[CandidatePool] 无法获取全 A 股基本信息")
        return [], [], []

    focus_review_tickers = _resolve_cooldown_shadow_review_tickers()
    focus_filter_diagnostics = _init_focus_filter_diagnostics(stock_df, focus_tickers=focus_review_tickers)

    initial_count = len(stock_df)
    print(f"[CandidatePool] 全 A 股标的: {initial_count}")

    mask_st = stock_df["name"].str.contains("ST", case=False, na=False)
    stock_df = stock_df[~mask_st].copy()
    print(f"[CandidatePool] 排除 ST 后: {len(stock_df)} (过滤 {mask_st.sum()})")
    _record_focus_filter_stage(
        focus_filter_diagnostics,
        stage="st_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )

    mask_bj = build_beijing_exchange_mask(stock_df)
    stock_df = stock_df[~mask_bj].copy()
    print(f"[CandidatePool] 排除北交所后: {len(stock_df)} (过滤 {mask_bj.sum()})")
    _record_focus_filter_stage(
        focus_filter_diagnostics,
        stage="beijing_exchange_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )

    mask_new = stock_df["list_date"].apply(
        lambda d: _estimate_trading_days(str(d) if pd.notna(d) else "", trade_date) < MIN_LISTING_DAYS
    )
    stock_df = stock_df[~mask_new].copy()
    print(f"[CandidatePool] 排除新股后: {len(stock_df)} (过滤 {mask_new.sum()})")
    _record_focus_filter_stage(
        focus_filter_diagnostics,
        stage="listing_days_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )

    suspend_df = get_suspend_list(trade_date)
    if suspend_df is not None and not suspend_df.empty:
        suspend_codes = set(suspend_df["ts_code"].tolist())
        mask_suspend = stock_df["ts_code"].isin(suspend_codes)
        stock_df = stock_df[~mask_suspend].copy()
        print(f"[CandidatePool] 排除停牌后: {len(stock_df)} (过滤 {mask_suspend.sum()})")
    _record_focus_filter_stage(
        focus_filter_diagnostics,
        stage="suspend_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )

    limit_df = get_limit_list(trade_date)
    if limit_df is not None and not limit_df.empty:
        limit_up_codes = set(limit_df[limit_df["limit"] == "U"]["ts_code"].tolist())
        mask_limit_up = stock_df["ts_code"].isin(limit_up_codes)
        stock_df = stock_df[~mask_limit_up].copy()
        print(f"[CandidatePool] 排除涨停后: {len(stock_df)} (过滤 {mask_limit_up.sum()})")
    _record_focus_filter_stage(
        focus_filter_diagnostics,
        stage="limit_up_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )

    cooldown_tickers = resolve_cooldown_tickers(
        cooldown_tickers=set(cooldown_tickers) if cooldown_tickers is not None else None,
        trade_date=trade_date,
        get_cooled_tickers_fn=get_cooled_tickers,
    )
    stock_df, cooldown_review_df, cooldown_filtered_count = apply_cooldown_filter(
        stock_df=stock_df,
        cooldown_tickers=set(cooldown_tickers),
        cooldown_review_tickers=_resolve_cooldown_shadow_review_tickers(),
    )
    _record_focus_filter_stage(
        focus_filter_diagnostics,
        stage="cooldown_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()) | set(cooldown_review_df["symbol"].astype(str).tolist()),
    )
    if cooldown_tickers:
        print(f"[CandidatePool] 排除冷却期后: {len(stock_df)} (过滤 {cooldown_filtered_count})")
        if not cooldown_review_df.empty:
            print(f"[CandidatePool] 保留冷却期 focus shadow review: {len(cooldown_review_df)}")

    daily_df = get_daily_basic_batch(trade_date)
    amount_map: Dict[str, float] = {}
    estimated_amount_map, mv_map = build_daily_basic_maps(
        daily_df=daily_df,
        estimate_amount_fn=_estimate_amount_from_daily_basic,
    )

    stock_df, cooldown_review_df = apply_estimated_liquidity_filter_with_logging(
        stock_df=stock_df,
        cooldown_review_df=cooldown_review_df,
        estimated_amount_map=estimated_amount_map,
        min_estimated_amount_1d=MIN_ESTIMATED_AMOUNT_1D,
    )
    _record_focus_filter_stage(
        focus_filter_diagnostics,
        stage="estimated_liquidity_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()) | set(cooldown_review_df["symbol"].astype(str).tolist()),
    )

    remaining_codes = stock_df["ts_code"].tolist() + cooldown_review_df["ts_code"].tolist()
    print(f"[CandidatePool] 开始计算 {len(remaining_codes)} 只标的的 20 日均成交额...")

    amount_map, low_liq_codes, used_batch_daily = load_amount_map_and_low_liquidity_codes(
        pro=pro,
        remaining_codes=remaining_codes,
        trade_date=trade_date,
        min_avg_amount_20d=MIN_AVG_AMOUNT_20D,
        batch_size=TUSHARE_DAILY_BATCH_SIZE,
        get_avg_amount_map_fn=_get_avg_amount_20d_map,
        get_avg_amount_fn=_get_avg_amount_20d,
        enforce_rate_limit_fn=_enforce_tushare_daily_rate_limit,
    )
    if used_batch_daily:
        print("[CandidatePool] 使用批量 daily 聚合完成 20 日均成交额计算")

    stock_df, cooldown_review_df, low_liq_filtered_count = filter_low_liquidity_candidates(
        stock_df=stock_df,
        cooldown_review_df=cooldown_review_df,
        low_liq_codes=low_liq_codes,
    )
    print(f"[CandidatePool] 排除低流动性后: {len(stock_df)} (过滤 {low_liq_filtered_count})")
    _record_focus_filter_stage(
        focus_filter_diagnostics,
        stage="avg_amount_20d_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()) | set(cooldown_review_df["symbol"].astype(str).tolist()),
    )

    sw_map = normalize_sw_map(get_sw_industry_classification())

    is_disclosure = _is_disclosure_window(trade_date)
    candidates = build_candidate_stocks(
        stock_df=stock_df,
        sw_map=sw_map,
        mv_map=mv_map,
        amount_map=amount_map,
        is_disclosure=is_disclosure,
    )
    cooldown_review_candidates = build_candidate_stocks(
        stock_df=cooldown_review_df,
        sw_map=sw_map,
        mv_map=mv_map,
        amount_map=amount_map,
        is_disclosure=is_disclosure,
        cooldown_review=True,
    )

    finalized_focus_filter_diagnostics = _finalize_focus_filter_diagnostics(
        focus_filter_diagnostics,
        candidate_tickers={candidate.ticker for candidate in candidates},
        cooldown_review_tickers={candidate.ticker for candidate in cooldown_review_candidates},
        selected_tickers=set(),
        shadow_tickers=set(),
    )

    return candidates, cooldown_review_candidates, finalized_focus_filter_diagnostics


def build_candidate_pool_with_shadow(
    trade_date: str,
    use_cache: bool = True,
    cooldown_tickers: Optional[Set[str]] = None,
) -> tuple[List[CandidateStock], List[CandidateStock], dict[str, Any]]:
    snapshot_path = _candidate_pool_snapshot_path(trade_date)
    legacy_snapshot_path = _candidate_pool_legacy_snapshot_path(trade_date)
    shadow_snapshot_path = _candidate_pool_shadow_snapshot_path(trade_date)
    cached_selected_candidates: List[CandidateStock] = []
    focus_signature = _shadow_focus_signature()
    focus_label = f", focus={focus_signature}" if focus_signature else ""

    if use_cache and snapshot_path.exists() and shadow_snapshot_path.exists():
        try:
            shadow_payload = _load_candidate_pool_shadow_snapshot(shadow_snapshot_path)
            _write_candidate_pool_snapshot(legacy_snapshot_path, shadow_payload["selected_candidates"])
            print(
                f"[CandidatePool] 从缓存加载 {len(shadow_payload['selected_candidates'])} 只候选标的 + {len(shadow_payload['shadow_candidates'])} 只 shadow 标的 ({trade_date}, top{MAX_CANDIDATE_POOL_SIZE}{focus_label})"
            )
            return shadow_payload["selected_candidates"], shadow_payload["shadow_candidates"], shadow_payload["shadow_summary"]
        except Exception as e:
            print(f"[CandidatePool] shadow 缓存读取失败，重新计算: {e}")
    elif use_cache and snapshot_path.exists():
        print(f"[CandidatePool] 发现仅主池缓存 {snapshot_path.name}，补算 shadow recall 快照{focus_label}")
        try:
            cached_selected_candidates = _load_candidate_pool_snapshot(snapshot_path)
            if cached_selected_candidates and not focus_signature:
                shadow_summary = _build_shadow_summary_from_selected_candidates(
                    cached_selected_candidates,
                    pool_size=MAX_CANDIDATE_POOL_SIZE,
                )
                _write_candidate_pool_shadow_snapshot(
                    shadow_snapshot_path,
                    selected_candidates=cached_selected_candidates,
                    shadow_candidates=[],
                    shadow_summary=shadow_summary,
                )
                _write_candidate_pool_snapshot(legacy_snapshot_path, cached_selected_candidates)
                print(
                    f"[CandidatePool] 使用已有主池缓存直接回填空 shadow 快照 ({trade_date}, top{MAX_CANDIDATE_POOL_SIZE})"
                )
                return cached_selected_candidates, [], shadow_summary
        except Exception as e:
            print(f"[CandidatePool] 主池缓存读取失败，无法作为 shadow 补算回退: {e}")

    candidates, cooldown_review_candidates, focus_filter_diagnostics = _compute_candidate_pool_candidates(
        trade_date,
        cooldown_tickers=cooldown_tickers,
    )
    if not candidates and cached_selected_candidates:
        shadow_summary = _build_shadow_summary_from_selected_candidates(
            cached_selected_candidates,
            pool_size=MAX_CANDIDATE_POOL_SIZE,
        )
        shadow_summary["shadow_recall_status"] = "selected_cache_fallback_after_recompute_failure"
        _write_candidate_pool_shadow_snapshot(
            shadow_snapshot_path,
            selected_candidates=cached_selected_candidates,
            shadow_candidates=[],
            shadow_summary=shadow_summary,
        )
        _write_candidate_pool_snapshot(legacy_snapshot_path, cached_selected_candidates)
        print(
            f"[CandidatePool] 候选池重算失败，保留已有主池缓存并回填空 shadow 快照 ({trade_date}, top{MAX_CANDIDATE_POOL_SIZE})"
        )
        return cached_selected_candidates, [], shadow_summary

    selected_candidates, shadow_candidates, shadow_summary = _build_shadow_candidate_pool_payload(
        candidates,
        pool_size=MAX_CANDIDATE_POOL_SIZE,
        cooldown_review_candidates=cooldown_review_candidates,
        focus_filter_diagnostics=focus_filter_diagnostics,
    )
    shadow_summary["focus_filter_diagnostics"] = _finalize_focus_filter_diagnostics(
        {item["ticker"]: item for item in focus_filter_diagnostics},
        candidate_tickers={candidate.ticker for candidate in candidates},
        cooldown_review_tickers={candidate.ticker for candidate in cooldown_review_candidates},
        selected_tickers={candidate.ticker for candidate in selected_candidates},
        shadow_tickers={candidate.ticker for candidate in shadow_candidates},
    )

    _write_candidate_pool_snapshot(snapshot_path, selected_candidates)
    _write_candidate_pool_snapshot(legacy_snapshot_path, selected_candidates)
    _write_candidate_pool_shadow_snapshot(
        shadow_snapshot_path,
        selected_candidates=selected_candidates,
        shadow_candidates=shadow_candidates,
        shadow_summary=shadow_summary,
    )

    if len(candidates) > MAX_CANDIDATE_POOL_SIZE:
        print(f"[CandidatePool] 候选池截断至 Top {MAX_CANDIDATE_POOL_SIZE}（按20日均成交额/市值排序）")
    if shadow_candidates:
        print(
            f"[CandidatePool] shadow recall 标的: {len(shadow_candidates)} 只 ({shadow_summary.get('lane_counts')})"
        )
    print(f"[CandidatePool] 最终候选池: {len(selected_candidates)} 只 → {snapshot_path}")
    return selected_candidates, shadow_candidates, shadow_summary


# ============================================================================
# 冷却期注册表（持久化 JSON）
# ============================================================================

def load_cooldown_registry() -> Dict[str, str]:
    """加载冷却期注册表：{ticker: expire_date_YYYYMMDD}"""
    if _COOLDOWN_FILE.exists():
        try:
            with open(_COOLDOWN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_cooldown_registry(registry: Dict[str, str]) -> None:
    """保存冷却期注册表"""
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with open(_COOLDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def add_cooldown(ticker: str, trade_date: str, days: int = COOLDOWN_TRADING_DAYS) -> None:
    """将标的加入冷却期。trade_date 格式 YYYYMMDD。"""
    registry = load_cooldown_registry()
    dt = datetime.strptime(trade_date, "%Y%m%d")
    # 近似用自然日（交易日转换需要交易日历，此处用 1.5 倍近似）
    expire_dt = dt + timedelta(days=int(days * 1.5))
    registry[ticker] = expire_dt.strftime("%Y%m%d")
    save_cooldown_registry(registry)


def get_cooled_tickers(trade_date: str) -> Set[str]:
    """获取当前处于冷却期的标的集合"""
    registry = load_cooldown_registry()
    cooled: Set[str] = set()
    expired: list[str] = []
    for ticker, expire_date in registry.items():
        if expire_date > trade_date:
            cooled.add(ticker)
        else:
            expired.append(ticker)
    # 清理过期的冷却记录
    if expired:
        for t in expired:
            del registry[t]
        save_cooldown_registry(registry)
    return cooled


def is_beijing_exchange_stock(*, ts_code: str | None = None, symbol: str | None = None, market: str | None = None) -> bool:
    """判断标的是否属于北交所。"""
    market_text = str(market or "").strip()
    if market_text.upper() == "BJ" or market_text == "北交所":
        return True

    ts_code_text = str(ts_code or "").strip().upper()
    if ts_code_text.endswith(".BJ"):
        return True

    symbol_text = str(symbol or "").strip()
    return symbol_text.startswith(BEIJING_EXCHANGE_SYMBOL_PREFIXES)


def build_beijing_exchange_mask(stock_df: pd.DataFrame) -> pd.Series:
    """构建全量股票表中的北交所掩码。"""
    if stock_df.empty:
        return pd.Series(dtype=bool)

    market_series = stock_df["market"] if "market" in stock_df else pd.Series("", index=stock_df.index, dtype="object")
    ts_code_series = stock_df["ts_code"] if "ts_code" in stock_df else pd.Series("", index=stock_df.index, dtype="object")
    symbol_series = stock_df["symbol"] if "symbol" in stock_df else pd.Series("", index=stock_df.index, dtype="object")

    normalized_market = market_series.fillna("").astype(str).str.strip()
    normalized_ts_code = ts_code_series.fillna("").astype(str).str.strip().str.upper()
    normalized_symbol = symbol_series.fillna("").astype(str).str.strip()

    return (
        normalized_market.str.upper().eq("BJ")
        | normalized_market.eq("北交所")
        | normalized_ts_code.str.endswith(".BJ")
        | normalized_symbol.str.startswith(BEIJING_EXCHANGE_SYMBOL_PREFIXES)
    )


# ============================================================================
# 核心筛选逻辑
# ============================================================================

def _is_disclosure_window(trade_date: str) -> bool:
    """判断是否处于财报窗口期（4月/8月/10月）"""
    month = int(trade_date[4:6])
    return month in DISCLOSURE_MONTHS


def _estimate_trading_days(list_date: str, trade_date: str) -> int:
    """
    估算上市日期到交易日期之间的交易日数。
    使用自然日 × 0.7 近似（A 股年 250 交易日 / 365 自然日 ≈ 0.685）。
    """
    try:
        dt_list = datetime.strptime(list_date, "%Y%m%d")
        dt_trade = datetime.strptime(trade_date, "%Y%m%d")
        natural_days = (dt_trade - dt_list).days
        return max(0, int(natural_days * 0.7))
    except (ValueError, TypeError):
        return 0


def _get_avg_amount_20d(pro, ts_code: str, trade_date: str) -> float:
    """获取近 20 日平均成交额（万元）。使用 daily_basic 批量缓存优先。"""
    try:
        # 使用 daily 接口获取近 20 日成交额
        end_dt = datetime.strptime(trade_date, "%Y%m%d")
        start_dt = end_dt - timedelta(days=35)  # 多取几天确保覆盖 20 个交易日
        df = _cached_tushare_dataframe_call(
            pro,
            "daily",
            ts_code=ts_code,
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=trade_date,
            fields="trade_date,amount",
        )
        if df is None or df.empty:
            return 0.0
        # tushare daily 的 amount 单位是千元
        amounts = df["amount"].dropna().tail(20)
        if amounts.empty:
            return 0.0
        return float(amounts.mean() / 10.0)  # 千元 → 万元
    except Exception:
        return 0.0


def _get_recent_open_dates(pro, trade_date: str, lookback_sessions: int = 20) -> list[str]:
    """获取截至指定日期最近的开市交易日列表。"""
    try:
        end_dt = datetime.strptime(trade_date, "%Y%m%d")
        start_dt = end_dt - timedelta(days=45)
        df_cal = _cached_tushare_dataframe_call(
            pro,
            "trade_cal",
            exchange="",
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=trade_date,
            is_open=1,
            fields="cal_date,is_open",
        )
        if df_cal is None or df_cal.empty:
            return []
        return [str(value) for value in df_cal["cal_date"].tail(lookback_sessions).tolist()]
    except Exception:
        return []


def _get_avg_amount_20d_map(pro, ts_codes: list[str], trade_date: str, lookback_sessions: int = 20) -> Dict[str, float]:
    """按交易日批量获取全市场成交额并在本地聚合，避免逐票调用 `daily`。"""
    recent_open_dates = _get_recent_open_dates(pro, trade_date, lookback_sessions=lookback_sessions)
    if not recent_open_dates or not ts_codes:
        return {}

    target_codes = set(ts_codes)
    amount_buckets: dict[str, list[float]] = defaultdict(list)

    for open_date in recent_open_dates:
        try:
            df = _cached_tushare_dataframe_call(pro, "daily", trade_date=open_date, fields="ts_code,amount")
        except Exception:
            return {}
        if df is None or df.empty:
            continue
        filtered = df[df["ts_code"].isin(target_codes)]
        if filtered.empty:
            continue
        for _, row in filtered.iterrows():
            amount = row.get("amount")
            if pd.notna(amount):
                amount_buckets[str(row["ts_code"])].append(float(amount) / 10.0)

    return {
        ts_code: float(sum(amounts) / len(amounts))
        for ts_code, amounts in amount_buckets.items()
        if amounts
    }


def _estimate_amount_from_daily_basic(row: pd.Series) -> float:
    """使用当日换手率和流通市值粗略估算成交额（万元）。"""
    turnover_rate = row.get("turnover_rate")
    circ_mv = row.get("circ_mv")
    if pd.isna(turnover_rate) or pd.isna(circ_mv):
        return 0.0
    try:
        return max(0.0, float(circ_mv) * float(turnover_rate) / 100.0)
    except (TypeError, ValueError):
        return 0.0


def _enforce_tushare_daily_rate_limit(batch_started_at: float, processed_calls: int, has_more_batches: bool) -> float:
    """按实际已耗时补足 Tushare `daily` 调用的批次速率限制。"""
    if not has_more_batches or processed_calls <= 0:
        return 0.0

    target_seconds = processed_calls * (60.0 / TUSHARE_DAILY_CALLS_PER_MINUTE)
    elapsed_seconds = perf_counter() - batch_started_at
    sleep_seconds = max(0.0, target_seconds - elapsed_seconds)
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    return sleep_seconds


def build_candidate_pool(
    trade_date: str,
    use_cache: bool = True,
    cooldown_tickers: Optional[Set[str]] = None,
) -> List[CandidateStock]:
    """
    构建 Layer A 候选池。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD
        use_cache: 启用增量缓存（当日已生成则跳过）
        cooldown_tickers: 外部传入的冷却期标的集合（可选，未提供则从文件加载）

    返回:
        List[CandidateStock] — 通过所有筛选规则的候选标的

    流程:
        1) 全量股票基本信息 → 排除 ST / 北交所
        2) 排除新股（< 60 交易日）
        3) 排除当日停牌
        4) 排除当日涨停
        5) 排除冷却期标的
        6) 获取行业分类 + 成交额 → 排除低流动性
        7) 标记财报窗口期
        8) 输出结果 + 持久化
    """
    selected_candidates, _, _ = build_candidate_pool_with_shadow(
        trade_date,
        use_cache=use_cache,
        cooldown_tickers=cooldown_tickers,
    )
    return selected_candidates


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Layer A 候选池构建器")
    parser.add_argument("--trade-date", required=True, help="交易日期 YYYYMMDD")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    args = parser.parse_args()

    candidates = build_candidate_pool(args.trade_date, use_cache=not args.no_cache)
    print("\n=== 候选池结果 ===")
    print(f"日期: {args.trade_date}")
    print(f"标的数: {len(candidates)}")
    if candidates:
        # 按市值降序显示前 20 只
        sorted_candidates = sorted(candidates, key=lambda c: c.market_cap, reverse=True)
        print("\n市值 Top 20:")
        for i, c in enumerate(sorted_candidates[:20], 1):
            print(f"  {i:2d}. {c.ticker} {c.name:<8s} 行业={c.industry_sw:<6s} 市值={c.market_cap:.1f}亿 均额={c.avg_volume_20d:.0f}万")


if __name__ == "__main__":
    main()
