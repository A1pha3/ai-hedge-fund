from __future__ import annotations

from time import perf_counter
from collections.abc import Callable

import pandas as pd

from src.screening.models import CandidateStock


def apply_cooldown_filter(
    *,
    stock_df: pd.DataFrame,
    cooldown_tickers: set[str],
    cooldown_review_tickers: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    cooldown_review_df = stock_df.iloc[0:0].copy()
    if not cooldown_tickers:
        return stock_df, cooldown_review_df, 0
    mask_cool = stock_df["symbol"].isin(cooldown_tickers)
    if cooldown_review_tickers:
        cooldown_review_df = stock_df[mask_cool & stock_df["symbol"].isin(cooldown_review_tickers)].copy()
    return stock_df[~mask_cool].copy(), cooldown_review_df, int(mask_cool.sum())


def resolve_cooldown_tickers(
    *,
    cooldown_tickers: set[str] | None,
    trade_date: str,
    get_cooled_tickers_fn: Callable[[str], set[str]],
) -> set[str]:
    return set(cooldown_tickers) if cooldown_tickers is not None else set(get_cooled_tickers_fn(trade_date))


def build_daily_basic_maps(
    daily_df: pd.DataFrame | None,
    estimate_amount_fn: Callable[[pd.Series], float],
) -> tuple[dict[str, float], dict[str, float]]:
    estimated_amount_map: dict[str, float] = {}
    mv_map: dict[str, float] = {}
    if daily_df is None or daily_df.empty:
        return estimated_amount_map, mv_map
    for _, row in daily_df.iterrows():
        ts_code = str(row["ts_code"])
        if pd.notna(row.get("total_mv")):
            mv_map[ts_code] = float(row["total_mv"])
        estimated_amount_map[ts_code] = estimate_amount_fn(row)
    return estimated_amount_map, mv_map


def filter_low_estimated_liquidity(
    *,
    stock_df: pd.DataFrame,
    cooldown_review_df: pd.DataFrame,
    estimated_amount_map: dict[str, float],
    min_estimated_amount_1d: float,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    low_estimated_liq_codes = {
        ts_code
        for ts_code in stock_df["ts_code"].tolist()
        if 0.0 < estimated_amount_map.get(ts_code, 0.0) < min_estimated_amount_1d
    }
    if not low_estimated_liq_codes:
        return stock_df, cooldown_review_df, 0
    mask_low_estimated_liq = stock_df["ts_code"].isin(low_estimated_liq_codes)
    filtered_stock_df = stock_df[~mask_low_estimated_liq].copy()
    filtered_cooldown_df = cooldown_review_df
    if not cooldown_review_df.empty:
        filtered_cooldown_df = cooldown_review_df[~cooldown_review_df["ts_code"].isin(low_estimated_liq_codes)].copy()
    return filtered_stock_df, filtered_cooldown_df, int(mask_low_estimated_liq.sum())


def apply_estimated_liquidity_filter_with_logging(
    *,
    stock_df: pd.DataFrame,
    cooldown_review_df: pd.DataFrame,
    estimated_amount_map: dict[str, float],
    min_estimated_amount_1d: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not estimated_amount_map:
        return stock_df, cooldown_review_df
    filtered_stock_df, filtered_cooldown_df, filtered_count = filter_low_estimated_liquidity(
        stock_df=stock_df,
        cooldown_review_df=cooldown_review_df,
        estimated_amount_map=estimated_amount_map,
        min_estimated_amount_1d=min_estimated_amount_1d,
    )
    if filtered_count:
        print(f"[CandidatePool] 排除低当日估算流动性后: {len(filtered_stock_df)} (过滤 {filtered_count})")
    return filtered_stock_df, filtered_cooldown_df


def load_amount_map_and_low_liquidity_codes(
    *,
    pro: object,
    remaining_codes: list[str],
    trade_date: str,
    min_avg_amount_20d: float,
    batch_size: int,
    get_avg_amount_map_fn: Callable[[object, list[str], str], dict[str, float]],
    get_avg_amount_fn: Callable[[object, str, str], float],
    enforce_rate_limit_fn: Callable[[float, int, bool], float],
) -> tuple[dict[str, float], set[str], bool]:
    amount_map = get_avg_amount_map_fn(pro, remaining_codes, trade_date)
    low_liq_codes: set[str] = set()
    if amount_map:
        for ts_code in remaining_codes:
            if amount_map.get(ts_code, 0.0) < min_avg_amount_20d:
                low_liq_codes.add(ts_code)
        return amount_map, low_liq_codes, True

    for index in range(0, len(remaining_codes), batch_size):
        batch = remaining_codes[index:index + batch_size]
        batch_started_at = perf_counter()
        for ts_code in batch:
            avg_amt = get_avg_amount_fn(pro, ts_code, trade_date)
            amount_map[ts_code] = avg_amt
            if avg_amt < min_avg_amount_20d:
                low_liq_codes.add(ts_code)
        enforce_rate_limit_fn(
            batch_started_at=batch_started_at,
            processed_calls=len(batch),
            has_more_batches=(index + batch_size) < len(remaining_codes),
        )
        progress_pct = min(100, int((index + batch_size) / len(remaining_codes) * 100))
        print(f"[CandidatePool] 成交额计算进度: {progress_pct}%")
    return amount_map, low_liq_codes, False


def filter_low_liquidity_candidates(
    *,
    stock_df: pd.DataFrame,
    cooldown_review_df: pd.DataFrame,
    low_liq_codes: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    mask_low_liq = stock_df["ts_code"].isin(low_liq_codes)
    filtered_stock_df = stock_df[~mask_low_liq].copy()
    filtered_cooldown_df = cooldown_review_df
    if not cooldown_review_df.empty:
        filtered_cooldown_df = cooldown_review_df[~cooldown_review_df["ts_code"].isin(low_liq_codes)].copy()
    return filtered_stock_df, filtered_cooldown_df, int(mask_low_liq.sum())


def build_candidate_stocks(
    *,
    stock_df: pd.DataFrame,
    sw_map: dict[str, str],
    mv_map: dict[str, float],
    amount_map: dict[str, float],
    is_disclosure: bool,
    cooldown_review: bool = False,
) -> list[CandidateStock]:
    candidates: list[CandidateStock] = []
    for _, row in stock_df.iterrows():
        ts_code = str(row["ts_code"])
        candidate_kwargs = {
            "ticker": str(row["symbol"]),
            "name": str(row["name"]),
            "industry_sw": sw_map.get(ts_code, str(row.get("industry", ""))),
            "market_cap": mv_map.get(ts_code, 0.0) / 10000.0,
            "avg_volume_20d": amount_map.get(ts_code, 0.0),
            "listing_date": str(row["list_date"]) if pd.notna(row.get("list_date")) else "",
            "disclosure_risk": is_disclosure,
        }
        if cooldown_review:
            candidate_kwargs.update(
                {
                    "candidate_pool_lane": "cooldown_review",
                    "candidate_pool_shadow_reason": "cooldown_review_shadow",
                }
            )
        candidates.append(CandidateStock(**candidate_kwargs))
    return candidates


def normalize_sw_map(sw_map: dict[str, str] | None) -> dict[str, str]:
    return sw_map or {}
