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
from typing import Any

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
from src.screening.candidate_pool_compute_pipeline_helpers import (
    compute_candidate_pool_candidates as compute_candidate_pool_candidates_helper,
)
from src.screening.candidate_pool_shadow_helpers import (
    build_shadow_summary_payload,
    build_cooldown_review_shadow_payload,
    build_shadow_lane_payload,
    classify_overflow_candidate,
    select_shadow_rows,
)
from src.screening.candidate_pool_shadow_payload_helpers import (
    build_shadow_candidate_pool_payload as build_shadow_candidate_pool_payload_helper,
)
from src.screening.candidate_pool_run_helpers import (
    build_candidate_pool_with_shadow as build_candidate_pool_with_shadow_helper,
)
from src.screening.candidate_pool_persistence_helpers import (
    add_cooldown as add_cooldown_helper,
    get_cooled_tickers as get_cooled_tickers_helper,
    load_candidate_pool_shadow_snapshot as load_candidate_pool_shadow_snapshot_helper,
    load_candidate_pool_snapshot as load_candidate_pool_snapshot_helper,
    load_cooldown_registry as load_cooldown_registry_helper,
    normalize_shadow_summary as normalize_shadow_summary_helper,
    save_cooldown_registry as save_cooldown_registry_helper,
    write_candidate_pool_shadow_snapshot as write_candidate_pool_shadow_snapshot_helper,
    write_candidate_pool_snapshot as write_candidate_pool_snapshot_helper,
)
from src.screening.models import CandidateStock
from src.tools.ashare_board_utils import BEIJING_EXCHANGE_SYMBOL_PREFIXES, build_beijing_exchange_mask, is_beijing_exchange_stock
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
SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE", "2.5"))
SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MAX_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MAX_CUTOFF_SHARE", "0.30"))
SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE", "0.075"))
SHADOW_LIQUIDITY_CORRIDOR_VISIBILITY_GAP_MAX_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_VISIBILITY_GAP_MAX_CUTOFF_SHARE", "0.35"))
SHADOW_REBUCKET_MIN_GATE_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_MIN_GATE_SHARE", "8.0"))
SHADOW_REBUCKET_MIN_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_MIN_CUTOFF_SHARE", "0.35"))
SHADOW_REBUCKET_MAX_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_MAX_CUTOFF_SHARE", "0.80"))
SHADOW_REBUCKET_FOCUS_MIN_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_FOCUS_MIN_CUTOFF_SHARE", "0.25"))
SHADOW_REBUCKET_VISIBILITY_GAP_MIN_CUTOFF_SHARE = float(os.getenv("CANDIDATE_POOL_SHADOW_REBUCKET_VISIBILITY_GAP_MIN_CUTOFF_SHARE", "0.25"))
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


def _candidate_pool_snapshot_path(trade_date: str, pool_size: int | None = None) -> Path:
    resolved_pool_size = MAX_CANDIDATE_POOL_SIZE if pool_size is None else int(pool_size)
    return _SNAPSHOT_DIR / f"candidate_pool_{trade_date}_top{resolved_pool_size}.json"


def _candidate_pool_legacy_snapshot_path(trade_date: str) -> Path:
    return _SNAPSHOT_DIR / f"candidate_pool_{trade_date}.json"


def _candidate_pool_shadow_snapshot_path(trade_date: str, pool_size: int | None = None) -> Path:
    resolved_pool_size = MAX_CANDIDATE_POOL_SIZE if pool_size is None else int(pool_size)
    focus_signature = _shadow_focus_signature()
    focus_suffix = f"_focus_{focus_signature}" if focus_signature else ""
    return _SNAPSHOT_DIR / f"candidate_pool_{trade_date}_top{resolved_pool_size}_shadow{focus_suffix}.json"


def _load_candidate_pool_snapshot(snapshot_path: Path) -> list[CandidateStock]:
    return load_candidate_pool_snapshot_helper(snapshot_path, candidate_stock_cls=CandidateStock)


def _normalize_shadow_summary(shadow_summary: dict[str, Any], *, shadow_candidates: list[CandidateStock]) -> dict[str, Any]:
    return normalize_shadow_summary_helper(shadow_summary, shadow_candidates=shadow_candidates)


def _write_candidate_pool_snapshot(snapshot_path: Path, candidates: list[CandidateStock]) -> None:
    return write_candidate_pool_snapshot_helper(snapshot_path, candidates, snapshot_dir=_SNAPSHOT_DIR)


def _load_candidate_pool_shadow_snapshot(snapshot_path: Path) -> dict[str, Any]:
    return load_candidate_pool_shadow_snapshot_helper(
        snapshot_path,
        candidate_stock_cls=CandidateStock,
        normalize_shadow_summary_fn=_normalize_shadow_summary,
    )


def _write_candidate_pool_shadow_snapshot(snapshot_path: Path, *, selected_candidates: list[CandidateStock], shadow_candidates: list[CandidateStock], shadow_summary: dict[str, Any]) -> None:
    return write_candidate_pool_shadow_snapshot_helper(
        snapshot_path,
        selected_candidates=selected_candidates,
        shadow_candidates=shadow_candidates,
        shadow_summary=shadow_summary,
        snapshot_dir=_SNAPSHOT_DIR,
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
        entry["final_visibility"] = _resolve_focus_filter_final_visibility(
            ticker=ticker,
            entry=entry,
            candidate_tickers=candidate_tickers,
            cooldown_review_tickers=cooldown_review_tickers,
            selected_tickers=selected_tickers,
            shadow_tickers=shadow_tickers,
        )
        finalized.append(entry)
    return finalized


def _resolve_focus_filter_final_visibility(
    *,
    ticker: str,
    entry: dict[str, Any],
    candidate_tickers: set[str],
    cooldown_review_tickers: set[str],
    selected_tickers: set[str],
    shadow_tickers: set[str],
) -> str:
    if not entry["present_in_stock_basic"]:
        return "missing_from_stock_basic"
    if ticker in selected_tickers:
        return "selected_pool"
    if ticker in shadow_tickers:
        return "shadow_pool"
    if ticker in candidate_tickers:
        return "overflow_pool"
    if ticker in cooldown_review_tickers:
        return "cooldown_review_pool"
    return "filtered_out"


def _build_shadow_candidate_pool_payload(
    candidates: list[CandidateStock],
    *,
    pool_size: int,
    cooldown_review_candidates: list[CandidateStock] | None = None,
    focus_filter_diagnostics: list[dict[str, Any]] | None = None,
) -> tuple[list[CandidateStock], list[CandidateStock], dict[str, Any]]:
    return build_shadow_candidate_pool_payload_helper(
        candidates,
        **_build_shadow_candidate_pool_payload_kwargs(
            pool_size=pool_size,
            cooldown_review_candidates=cooldown_review_candidates,
            focus_filter_diagnostics=focus_filter_diagnostics,
        ),
    )


def _build_shadow_candidate_pool_payload_kwargs(
    *,
    pool_size: int,
    cooldown_review_candidates: list[CandidateStock] | None,
    focus_filter_diagnostics: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    return {
        "pool_size": pool_size,
        "cooldown_review_candidates": cooldown_review_candidates,
        "focus_filter_diagnostics": focus_filter_diagnostics,
        "candidate_liquidity_sort_key_fn": _candidate_liquidity_sort_key,
        "build_cooldown_review_shadow_payload_fn": build_cooldown_review_shadow_payload,
        "build_shadow_summary_payload_fn": build_shadow_summary_payload,
        "shadow_focus_signature_fn": _shadow_focus_signature,
        "resolve_cooldown_shadow_review_tickers_fn": _resolve_cooldown_shadow_review_tickers,
        "resolve_shadow_focus_tickers_fn": _resolve_shadow_focus_tickers,
        "resolve_shadow_visibility_gap_tickers_fn": _resolve_shadow_visibility_gap_tickers,
        "classify_overflow_candidate_fn": classify_overflow_candidate,
        "select_shadow_rows_fn": select_shadow_rows,
        "build_shadow_lane_payload_fn": build_shadow_lane_payload,
        "min_avg_amount_20d": float(MIN_AVG_AMOUNT_20D),
        "shadow_visibility_gap_tickers": set(SHADOW_VISIBILITY_GAP_TICKERS),
        "shadow_liquidity_corridor_min_gate_share": SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE,
        "shadow_liquidity_corridor_max_cutoff_share": SHADOW_LIQUIDITY_CORRIDOR_MAX_CUTOFF_SHARE,
        "shadow_liquidity_corridor_focus_min_gate_share": SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE,
        "shadow_liquidity_corridor_focus_max_cutoff_share": SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MAX_CUTOFF_SHARE,
        "shadow_liquidity_corridor_focus_low_gate_max_cutoff_share": SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE,
        "shadow_liquidity_corridor_visibility_gap_max_cutoff_share": SHADOW_LIQUIDITY_CORRIDOR_VISIBILITY_GAP_MAX_CUTOFF_SHARE,
        "shadow_rebucket_min_gate_share": SHADOW_REBUCKET_MIN_GATE_SHARE,
        "shadow_rebucket_min_cutoff_share": SHADOW_REBUCKET_MIN_CUTOFF_SHARE,
        "shadow_rebucket_max_cutoff_share": SHADOW_REBUCKET_MAX_CUTOFF_SHARE,
        "shadow_rebucket_focus_min_cutoff_share": SHADOW_REBUCKET_FOCUS_MIN_CUTOFF_SHARE,
        "shadow_rebucket_visibility_gap_min_cutoff_share": SHADOW_REBUCKET_VISIBILITY_GAP_MIN_CUTOFF_SHARE,
        "shadow_liquidity_corridor_max_tickers": SHADOW_LIQUIDITY_CORRIDOR_MAX_TICKERS,
        "shadow_rebucket_max_tickers": SHADOW_REBUCKET_MAX_TICKERS,
    }


def _build_shadow_summary_from_selected_candidates(selected_candidates: list[CandidateStock], *, pool_size: int) -> dict[str, Any]:
    cutoff_avg_volume = _resolve_selected_cutoff_avg_volume(selected_candidates)
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


def _resolve_selected_cutoff_avg_volume(selected_candidates: list[CandidateStock]) -> float:
    return round(float(selected_candidates[-1].avg_volume_20d), 4) if selected_candidates else 0.0


def _compute_candidate_pool_candidates(
    trade_date: str,
    cooldown_tickers: set[str] | None = None,
) -> tuple[list[CandidateStock], list[CandidateStock], list[dict[str, Any]]]:
    """计算未截断的候选池，供主池与 shadow recall 共同消费。"""
    return compute_candidate_pool_candidates_helper(**_build_compute_candidate_pool_candidate_kwargs(trade_date, cooldown_tickers))


def _build_compute_candidate_pool_candidate_kwargs(
    trade_date: str,
    cooldown_tickers: set[str] | None,
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "cooldown_tickers": set(cooldown_tickers) if cooldown_tickers is not None else None,
        "min_listing_days": MIN_LISTING_DAYS,
        "min_estimated_amount_1d": MIN_ESTIMATED_AMOUNT_1D,
        "min_avg_amount_20d": MIN_AVG_AMOUNT_20D,
        "tushare_daily_batch_size": TUSHARE_DAILY_BATCH_SIZE,
        "get_pro_fn": _get_pro,
        "get_all_stock_basic_fn": get_all_stock_basic,
        "resolve_cooldown_shadow_review_tickers_fn": _resolve_cooldown_shadow_review_tickers,
        "init_focus_filter_diagnostics_fn": _init_focus_filter_diagnostics,
        "record_focus_filter_stage_fn": _record_focus_filter_stage,
        "build_beijing_exchange_mask_fn": build_beijing_exchange_mask,
        "estimate_trading_days_fn": _estimate_trading_days,
        "get_suspend_list_fn": get_suspend_list,
        "get_limit_list_fn": get_limit_list,
        "resolve_cooldown_tickers_fn": resolve_cooldown_tickers,
        "get_cooled_tickers_fn": get_cooled_tickers,
        "apply_cooldown_filter_fn": apply_cooldown_filter,
        "get_daily_basic_batch_fn": get_daily_basic_batch,
        "build_daily_basic_maps_fn": build_daily_basic_maps,
        "estimate_amount_from_daily_basic_fn": _estimate_amount_from_daily_basic,
        "apply_estimated_liquidity_filter_with_logging_fn": apply_estimated_liquidity_filter_with_logging,
        "load_amount_map_and_low_liquidity_codes_fn": load_amount_map_and_low_liquidity_codes,
        "get_avg_amount_20d_map_fn": _get_avg_amount_20d_map,
        "get_avg_amount_20d_fn": _get_avg_amount_20d,
        "enforce_tushare_daily_rate_limit_fn": _enforce_tushare_daily_rate_limit,
        "filter_low_liquidity_candidates_fn": filter_low_liquidity_candidates,
        "normalize_sw_map_fn": normalize_sw_map,
        "get_sw_industry_classification_fn": get_sw_industry_classification,
        "is_disclosure_window_fn": _is_disclosure_window,
        "build_candidate_stocks_fn": build_candidate_stocks,
        "finalize_focus_filter_diagnostics_fn": _finalize_focus_filter_diagnostics,
    }


def build_candidate_pool_with_shadow(
    trade_date: str,
    use_cache: bool = True,
    cooldown_tickers: set[str] | None = None,
) -> tuple[list[CandidateStock], list[CandidateStock], dict[str, Any]]:
    return build_candidate_pool_with_shadow_helper(
        **_build_candidate_pool_with_shadow_kwargs(
            trade_date=trade_date,
            use_cache=use_cache,
            cooldown_tickers=cooldown_tickers,
        )
    )


def _build_candidate_pool_with_shadow_kwargs(
    *,
    trade_date: str,
    use_cache: bool,
    cooldown_tickers: set[str] | None,
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "use_cache": use_cache,
        "cooldown_tickers": set(cooldown_tickers) if cooldown_tickers is not None else None,
        "snapshot_path": _candidate_pool_snapshot_path(trade_date),
        "legacy_snapshot_path": _candidate_pool_legacy_snapshot_path(trade_date),
        "shadow_snapshot_path": _candidate_pool_shadow_snapshot_path(trade_date),
        "max_candidate_pool_size": MAX_CANDIDATE_POOL_SIZE,
        "shadow_focus_signature_fn": _shadow_focus_signature,
        "load_candidate_pool_shadow_snapshot_fn": _load_candidate_pool_shadow_snapshot,
        "write_candidate_pool_snapshot_fn": _write_candidate_pool_snapshot,
        "load_candidate_pool_snapshot_fn": _load_candidate_pool_snapshot,
        "build_shadow_summary_from_selected_candidates_fn": _build_shadow_summary_from_selected_candidates,
        "write_candidate_pool_shadow_snapshot_fn": _write_candidate_pool_shadow_snapshot,
        "compute_candidate_pool_candidates_fn": _compute_candidate_pool_candidates,
        "build_shadow_candidate_pool_payload_fn": _build_shadow_candidate_pool_payload,
        "finalize_focus_filter_diagnostics_fn": _finalize_focus_filter_diagnostics,
    }


# ============================================================================
# 冷却期注册表（持久化 JSON）
# ============================================================================

def load_cooldown_registry() -> dict[str, str]:
    """加载冷却期注册表：{ticker: expire_date_YYYYMMDD}"""
    return load_cooldown_registry_helper(_COOLDOWN_FILE)


def save_cooldown_registry(registry: dict[str, str]) -> None:
    """保存冷却期注册表"""
    return save_cooldown_registry_helper(registry, cooldown_file=_COOLDOWN_FILE, snapshot_dir=_SNAPSHOT_DIR)


def add_cooldown(ticker: str, trade_date: str, days: int = COOLDOWN_TRADING_DAYS) -> None:
    """将标的加入冷却期。trade_date 格式 YYYYMMDD。"""
    return add_cooldown_helper(
        ticker,
        trade_date,
        days=days,
        load_cooldown_registry_fn=load_cooldown_registry,
        save_cooldown_registry_fn=save_cooldown_registry,
    )


def get_cooled_tickers(trade_date: str) -> set[str]:
    """获取当前处于冷却期的标的集合"""
    return get_cooled_tickers_helper(
        trade_date,
        load_cooldown_registry_fn=load_cooldown_registry,
        save_cooldown_registry_fn=save_cooldown_registry,
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
        dt_list, dt_trade = _parse_trading_day_estimate_dates(list_date, trade_date)
        natural_days = (dt_trade - dt_list).days
        return max(0, int(natural_days * 0.7))
    except (ValueError, TypeError):
        return 0


def _parse_trading_day_estimate_dates(list_date: str, trade_date: str) -> tuple[datetime, datetime]:
    return (
        datetime.strptime(list_date, "%Y%m%d"),
        datetime.strptime(trade_date, "%Y%m%d"),
    )


def _get_avg_amount_20d(pro, ts_code: str, trade_date: str) -> float:
    """获取近 20 日平均成交额（万元）。使用 daily_basic 批量缓存优先。"""
    try:
        df = _cached_tushare_dataframe_call(
            pro,
            "daily",
            ts_code=ts_code,
            **_build_avg_amount_20d_daily_kwargs(trade_date),
            fields="trade_date,amount",
        )
        if df is None or df.empty:
            return 0.0
        return _resolve_avg_amount_20d_from_daily_df(df)
    except Exception:
        return 0.0


def _build_avg_amount_20d_daily_kwargs(trade_date: str) -> dict[str, str]:
    end_dt = datetime.strptime(trade_date, "%Y%m%d")
    start_dt = end_dt - timedelta(days=35)
    return {
        "start_date": start_dt.strftime("%Y%m%d"),
        "end_date": trade_date,
    }


def _resolve_avg_amount_20d_from_daily_df(df: pd.DataFrame) -> float:
    amounts = df["amount"].dropna().tail(20)
    if amounts.empty:
        return 0.0
    return float(amounts.mean() / 10.0)


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
        return _extract_recent_open_dates(df_cal, lookback_sessions)
    except Exception:
        return []


def _extract_recent_open_dates(df_cal: pd.DataFrame, lookback_sessions: int) -> list[str]:
    return [str(value) for value in df_cal["cal_date"].tail(lookback_sessions).tolist()]


def _get_avg_amount_20d_map(pro, ts_codes: list[str], trade_date: str, lookback_sessions: int = 20) -> dict[str, float]:
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
        _accumulate_daily_amount_rows(filtered, amount_buckets)

    return _build_avg_amount_map(amount_buckets)


def _accumulate_daily_amount_rows(filtered: pd.DataFrame, amount_buckets: dict[str, list[float]]) -> None:
    for _, row in filtered.iterrows():
        amount = row.get("amount")
        if pd.notna(amount):
            amount_buckets[str(row["ts_code"])].append(float(amount) / 10.0)


def _build_avg_amount_map(amount_buckets: dict[str, list[float]]) -> dict[str, float]:
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

    sleep_seconds = _resolve_tushare_daily_sleep_seconds(
        batch_started_at=batch_started_at,
        processed_calls=processed_calls,
    )
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    return sleep_seconds


def _resolve_tushare_daily_sleep_seconds(*, batch_started_at: float, processed_calls: int) -> float:
    target_seconds = processed_calls * (60.0 / TUSHARE_DAILY_CALLS_PER_MINUTE)
    elapsed_seconds = perf_counter() - batch_started_at
    return max(0.0, target_seconds - elapsed_seconds)


def build_candidate_pool(
    trade_date: str,
    use_cache: bool = True,
    cooldown_tickers: set[str] | None = None,
) -> list[CandidateStock]:
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
