from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

import pandas as pd

if TYPE_CHECKING:
    from src.screening.models import CandidateStock


def compute_candidate_pool_candidates(
    *,
    trade_date: str,
    cooldown_tickers: set[str] | None,
    min_listing_days: int,
    min_estimated_amount_1d: float,
    min_avg_amount_20d: float,
    tushare_daily_batch_size: int,
    get_pro_fn: Callable[[], Any],
    get_all_stock_basic_fn: Callable[[], pd.DataFrame | None],
    resolve_cooldown_shadow_review_tickers_fn: Callable[[], set[str]],
    init_focus_filter_diagnostics_fn: Callable[..., dict[str, dict[str, Any]]],
    record_focus_filter_stage_fn: Callable[..., None],
    build_beijing_exchange_mask_fn: Callable[[pd.DataFrame], pd.Series],
    estimate_trading_days_fn: Callable[[str, str], int],
    get_suspend_list_fn: Callable[[str], pd.DataFrame | None],
    get_limit_list_fn: Callable[[str], pd.DataFrame | None],
    resolve_cooldown_tickers_fn: Callable[..., set[str]],
    get_cooled_tickers_fn: Callable[[str], set[str]],
    apply_cooldown_filter_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame, int]],
    get_daily_basic_batch_fn: Callable[[str], pd.DataFrame | None],
    build_daily_basic_maps_fn: Callable[..., tuple[dict[str, float], dict[str, float]]],
    estimate_amount_from_daily_basic_fn: Callable[..., float],
    apply_estimated_liquidity_filter_with_logging_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame]],
    load_amount_map_and_low_liquidity_codes_fn: Callable[..., tuple[dict[str, float], set[str], bool]],
    get_avg_amount_20d_map_fn: Callable[..., dict[str, float]],
    get_avg_amount_20d_fn: Callable[..., float],
    enforce_tushare_daily_rate_limit_fn: Callable[[], None],
    filter_low_liquidity_candidates_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame, int]],
    normalize_sw_map_fn: Callable[[Any], dict[str, str]],
    get_sw_industry_classification_fn: Callable[[], Any],
    is_disclosure_window_fn: Callable[[str], bool],
    build_candidate_stocks_fn: Callable[..., list["CandidateStock"]],
    finalize_focus_filter_diagnostics_fn: Callable[..., list[dict[str, Any]]],
) -> tuple[list["CandidateStock"], list["CandidateStock"], list[dict[str, Any]]]:
    pro = get_pro_fn()
    if pro is None:
        print("[CandidatePool] Tushare 未初始化，无法构建候选池")
        return [], [], []

    stock_df = get_all_stock_basic_fn()
    if stock_df is None or stock_df.empty:
        print("[CandidatePool] 无法获取全 A 股基本信息")
        return [], [], []

    focus_review_tickers = resolve_cooldown_shadow_review_tickers_fn()
    focus_filter_diagnostics = init_focus_filter_diagnostics_fn(stock_df, focus_tickers=focus_review_tickers)

    initial_count = len(stock_df)
    print(f"[CandidatePool] 全 A 股标的: {initial_count}")

    mask_st = stock_df["name"].str.contains("ST", case=False, na=False)
    stock_df = stock_df[~mask_st].copy()
    print(f"[CandidatePool] 排除 ST 后: {len(stock_df)} (过滤 {mask_st.sum()})")
    record_focus_filter_stage_fn(
        focus_filter_diagnostics,
        stage="st_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )

    mask_bj = build_beijing_exchange_mask_fn(stock_df)
    stock_df = stock_df[~mask_bj].copy()
    print(f"[CandidatePool] 排除北交所后: {len(stock_df)} (过滤 {mask_bj.sum()})")
    record_focus_filter_stage_fn(
        focus_filter_diagnostics,
        stage="beijing_exchange_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )

    mask_new = stock_df["list_date"].apply(
        lambda d: estimate_trading_days_fn(str(d) if pd.notna(d) else "", trade_date) < min_listing_days
    )
    stock_df = stock_df[~mask_new].copy()
    print(f"[CandidatePool] 排除新股后: {len(stock_df)} (过滤 {mask_new.sum()})")
    record_focus_filter_stage_fn(
        focus_filter_diagnostics,
        stage="listing_days_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )

    suspend_df = get_suspend_list_fn(trade_date)
    if suspend_df is not None and not suspend_df.empty:
        suspend_codes = set(suspend_df["ts_code"].tolist())
        mask_suspend = stock_df["ts_code"].isin(suspend_codes)
        stock_df = stock_df[~mask_suspend].copy()
        print(f"[CandidatePool] 排除停牌后: {len(stock_df)} (过滤 {mask_suspend.sum()})")
    record_focus_filter_stage_fn(
        focus_filter_diagnostics,
        stage="suspend_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )

    limit_df = get_limit_list_fn(trade_date)
    if limit_df is not None and not limit_df.empty:
        limit_up_codes = set(limit_df[limit_df["limit"] == "U"]["ts_code"].tolist())
        mask_limit_up = stock_df["ts_code"].isin(limit_up_codes)
        stock_df = stock_df[~mask_limit_up].copy()
        print(f"[CandidatePool] 排除涨停后: {len(stock_df)} (过滤 {mask_limit_up.sum()})")
    record_focus_filter_stage_fn(
        focus_filter_diagnostics,
        stage="limit_up_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )

    resolved_cooldown_tickers = resolve_cooldown_tickers_fn(
        cooldown_tickers=set(cooldown_tickers) if cooldown_tickers is not None else None,
        trade_date=trade_date,
        get_cooled_tickers_fn=get_cooled_tickers_fn,
    )
    stock_df, cooldown_review_df, cooldown_filtered_count = apply_cooldown_filter_fn(
        stock_df=stock_df,
        cooldown_tickers=set(resolved_cooldown_tickers),
        cooldown_review_tickers=resolve_cooldown_shadow_review_tickers_fn(),
    )
    record_focus_filter_stage_fn(
        focus_filter_diagnostics,
        stage="cooldown_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()) | set(cooldown_review_df["symbol"].astype(str).tolist()),
    )
    if resolved_cooldown_tickers:
        print(f"[CandidatePool] 排除冷却期后: {len(stock_df)} (过滤 {cooldown_filtered_count})")
        if not cooldown_review_df.empty:
            print(f"[CandidatePool] 保留冷却期 focus shadow review: {len(cooldown_review_df)}")

    daily_df = get_daily_basic_batch_fn(trade_date)
    estimated_amount_map, mv_map = build_daily_basic_maps_fn(
        daily_df=daily_df,
        estimate_amount_fn=estimate_amount_from_daily_basic_fn,
    )

    stock_df, cooldown_review_df = apply_estimated_liquidity_filter_with_logging_fn(
        stock_df=stock_df,
        cooldown_review_df=cooldown_review_df,
        estimated_amount_map=estimated_amount_map,
        min_estimated_amount_1d=min_estimated_amount_1d,
    )
    record_focus_filter_stage_fn(
        focus_filter_diagnostics,
        stage="estimated_liquidity_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()) | set(cooldown_review_df["symbol"].astype(str).tolist()),
    )

    remaining_codes = stock_df["ts_code"].tolist() + cooldown_review_df["ts_code"].tolist()
    print(f"[CandidatePool] 开始计算 {len(remaining_codes)} 只标的的 20 日均成交额...")

    amount_map, low_liq_codes, used_batch_daily = load_amount_map_and_low_liquidity_codes_fn(
        pro=pro,
        remaining_codes=remaining_codes,
        trade_date=trade_date,
        min_avg_amount_20d=min_avg_amount_20d,
        batch_size=tushare_daily_batch_size,
        get_avg_amount_map_fn=get_avg_amount_20d_map_fn,
        get_avg_amount_fn=get_avg_amount_20d_fn,
        enforce_rate_limit_fn=enforce_tushare_daily_rate_limit_fn,
    )
    if used_batch_daily:
        print("[CandidatePool] 使用批量 daily 聚合完成 20 日均成交额计算")

    stock_df, cooldown_review_df, low_liq_filtered_count = filter_low_liquidity_candidates_fn(
        stock_df=stock_df,
        cooldown_review_df=cooldown_review_df,
        low_liq_codes=low_liq_codes,
    )
    print(f"[CandidatePool] 排除低流动性后: {len(stock_df)} (过滤 {low_liq_filtered_count})")
    record_focus_filter_stage_fn(
        focus_filter_diagnostics,
        stage="avg_amount_20d_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()) | set(cooldown_review_df["symbol"].astype(str).tolist()),
    )

    sw_map = normalize_sw_map_fn(get_sw_industry_classification_fn())

    is_disclosure = is_disclosure_window_fn(trade_date)
    candidates = build_candidate_stocks_fn(
        stock_df=stock_df,
        sw_map=sw_map,
        mv_map=mv_map,
        amount_map=amount_map,
        is_disclosure=is_disclosure,
    )
    cooldown_review_candidates = build_candidate_stocks_fn(
        stock_df=cooldown_review_df,
        sw_map=sw_map,
        mv_map=mv_map,
        amount_map=amount_map,
        is_disclosure=is_disclosure,
        cooldown_review=True,
    )

    finalized_focus_filter_diagnostics = finalize_focus_filter_diagnostics_fn(
        focus_filter_diagnostics,
        candidate_tickers={candidate.ticker for candidate in candidates},
        cooldown_review_tickers={candidate.ticker for candidate in cooldown_review_candidates},
        selected_tickers=set(),
        shadow_tickers=set(),
    )

    return candidates, cooldown_review_candidates, finalized_focus_filter_diagnostics
