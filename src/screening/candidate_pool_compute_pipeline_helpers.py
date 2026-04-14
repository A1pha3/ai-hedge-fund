from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import pandas as pd

if TYPE_CHECKING:
    from src.screening.models import CandidateStock


@dataclass(frozen=True)
class CandidatePoolComputationContext:
    pro: Any
    stock_df: pd.DataFrame
    focus_filter_diagnostics: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class CandidatePoolPreparedUniverse:
    stock_df: pd.DataFrame
    cooldown_review_df: pd.DataFrame


@dataclass(frozen=True)
class CandidatePoolLiquidityState:
    stock_df: pd.DataFrame
    cooldown_review_df: pd.DataFrame
    amount_map: dict[str, float]
    mv_map: dict[str, float]


@dataclass(frozen=True)
class CandidatePoolComputeInputs:
    trade_date: str
    cooldown_tickers: set[str] | None
    min_listing_days: int
    min_estimated_amount_1d: float
    min_avg_amount_20d: float
    tushare_daily_batch_size: int
    get_pro_fn: Callable[[], Any]
    get_all_stock_basic_fn: Callable[[], pd.DataFrame | None]
    resolve_cooldown_shadow_review_tickers_fn: Callable[[], set[str]]
    init_focus_filter_diagnostics_fn: Callable[..., dict[str, dict[str, Any]]]
    record_focus_filter_stage_fn: Callable[..., None]
    build_beijing_exchange_mask_fn: Callable[[pd.DataFrame], pd.Series]
    estimate_trading_days_fn: Callable[[str, str], int]
    get_suspend_list_fn: Callable[[str], pd.DataFrame | None]
    get_limit_list_fn: Callable[[str], pd.DataFrame | None]
    resolve_cooldown_tickers_fn: Callable[..., set[str]]
    get_cooled_tickers_fn: Callable[[str], set[str]]
    apply_cooldown_filter_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame, int]]
    get_daily_basic_batch_fn: Callable[[str], pd.DataFrame | None]
    build_daily_basic_maps_fn: Callable[..., tuple[dict[str, float], dict[str, float]]]
    estimate_amount_from_daily_basic_fn: Callable[..., float]
    apply_estimated_liquidity_filter_with_logging_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame]]
    load_amount_map_and_low_liquidity_codes_fn: Callable[..., tuple[dict[str, float], set[str], bool]]
    get_avg_amount_20d_map_fn: Callable[..., dict[str, float]]
    get_avg_amount_20d_fn: Callable[..., float]
    enforce_tushare_daily_rate_limit_fn: Callable[[], None]
    filter_low_liquidity_candidates_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame, int]]
    normalize_sw_map_fn: Callable[[Any], dict[str, str]]
    get_sw_industry_classification_fn: Callable[[], Any]
    is_disclosure_window_fn: Callable[[str], bool]
    build_candidate_stocks_fn: Callable[..., list["CandidateStock"]]
    finalize_focus_filter_diagnostics_fn: Callable[..., list[dict[str, Any]]]


def _record_candidate_filter_stage(
    *,
    stock_df: pd.DataFrame,
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    stage: str,
    record_focus_filter_stage_fn: Callable[..., None],
) -> None:
    record_focus_filter_stage_fn(
        focus_filter_diagnostics,
        stage=stage,
        active_symbols=set(stock_df["symbol"].astype(str).tolist()),
    )


def _apply_stock_dataframe_filter(
    *,
    stock_df: pd.DataFrame,
    mask: pd.Series,
    label: str,
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    stage: str,
    record_focus_filter_stage_fn: Callable[..., None],
) -> pd.DataFrame:
    filtered_df = stock_df[~mask].copy()
    print(f"[CandidatePool] {label}: {len(filtered_df)} (过滤 {mask.sum()})")
    _record_candidate_filter_stage(
        stock_df=filtered_df,
        focus_filter_diagnostics=focus_filter_diagnostics,
        stage=stage,
        record_focus_filter_stage_fn=record_focus_filter_stage_fn,
    )
    return filtered_df


def _apply_optional_ts_code_filter(
    *,
    stock_df: pd.DataFrame,
    filter_df: pd.DataFrame | None,
    code_column: str,
    label: str,
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    stage: str,
    record_focus_filter_stage_fn: Callable[..., None],
) -> pd.DataFrame:
    if filter_df is None or filter_df.empty:
        _record_candidate_filter_stage(
            stock_df=stock_df,
            focus_filter_diagnostics=focus_filter_diagnostics,
            stage=stage,
            record_focus_filter_stage_fn=record_focus_filter_stage_fn,
        )
        return stock_df

    mask = stock_df["ts_code"].isin(set(filter_df[code_column].tolist()))
    return _apply_stock_dataframe_filter(
        stock_df=stock_df,
        mask=mask,
        label=label,
        focus_filter_diagnostics=focus_filter_diagnostics,
        stage=stage,
        record_focus_filter_stage_fn=record_focus_filter_stage_fn,
    )


def _record_cooldown_filter_stage(
    *,
    stock_df: pd.DataFrame,
    cooldown_review_df: pd.DataFrame,
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    record_focus_filter_stage_fn: Callable[..., None],
) -> None:
    record_focus_filter_stage_fn(
        focus_filter_diagnostics,
        stage="cooldown_filter",
        active_symbols=set(stock_df["symbol"].astype(str).tolist()) | set(cooldown_review_df["symbol"].astype(str).tolist()),
    )


def _apply_core_candidate_filters(
    *,
    trade_date: str,
    stock_df: pd.DataFrame,
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    min_listing_days: int,
    record_focus_filter_stage_fn: Callable[..., None],
    build_beijing_exchange_mask_fn: Callable[[pd.DataFrame], pd.Series],
    estimate_trading_days_fn: Callable[[str, str], int],
) -> pd.DataFrame:
    stock_df = _apply_stock_dataframe_filter(
        stock_df=stock_df,
        mask=stock_df["name"].str.contains("ST", case=False, na=False),
        label="排除 ST 后",
        focus_filter_diagnostics=focus_filter_diagnostics,
        stage="st_filter",
        record_focus_filter_stage_fn=record_focus_filter_stage_fn,
    )
    stock_df = _apply_stock_dataframe_filter(
        stock_df=stock_df,
        mask=build_beijing_exchange_mask_fn(stock_df),
        label="排除北交所后",
        focus_filter_diagnostics=focus_filter_diagnostics,
        stage="beijing_exchange_filter",
        record_focus_filter_stage_fn=record_focus_filter_stage_fn,
    )
    listing_days_mask = stock_df["list_date"].apply(
        lambda d: estimate_trading_days_fn(str(d) if pd.notna(d) else "", trade_date) < min_listing_days
    )
    return _apply_stock_dataframe_filter(
        stock_df=stock_df,
        mask=listing_days_mask,
        label="排除新股后",
        focus_filter_diagnostics=focus_filter_diagnostics,
        stage="listing_days_filter",
        record_focus_filter_stage_fn=record_focus_filter_stage_fn,
    )


def _initialize_candidate_pool_context(
    *,
    get_pro_fn: Callable[[], Any],
    get_all_stock_basic_fn: Callable[[], pd.DataFrame | None],
    resolve_cooldown_shadow_review_tickers_fn: Callable[[], set[str]],
    init_focus_filter_diagnostics_fn: Callable[..., dict[str, dict[str, Any]]],
) -> tuple[Any, pd.DataFrame, dict[str, dict[str, Any]]] | tuple[None, None, None]:
    pro = get_pro_fn()
    if pro is None:
        print("[CandidatePool] Tushare 未初始化，无法构建候选池")
        return None, None, None

    stock_df = get_all_stock_basic_fn()
    if stock_df is None or stock_df.empty:
        print("[CandidatePool] 无法获取全 A 股基本信息")
        return None, None, None

    focus_review_tickers = resolve_cooldown_shadow_review_tickers_fn()
    focus_filter_diagnostics = init_focus_filter_diagnostics_fn(stock_df, focus_tickers=focus_review_tickers)
    return pro, stock_df, focus_filter_diagnostics


def _build_candidate_pool_computation_context(
    *,
    get_pro_fn: Callable[[], Any],
    get_all_stock_basic_fn: Callable[[], pd.DataFrame | None],
    resolve_cooldown_shadow_review_tickers_fn: Callable[[], set[str]],
    init_focus_filter_diagnostics_fn: Callable[..., dict[str, dict[str, Any]]],
) -> CandidatePoolComputationContext | None:
    pro, stock_df, focus_filter_diagnostics = _initialize_candidate_pool_context(
        get_pro_fn=get_pro_fn,
        get_all_stock_basic_fn=get_all_stock_basic_fn,
        resolve_cooldown_shadow_review_tickers_fn=resolve_cooldown_shadow_review_tickers_fn,
        init_focus_filter_diagnostics_fn=init_focus_filter_diagnostics_fn,
    )
    if pro is None or stock_df is None or focus_filter_diagnostics is None:
        return None
    return CandidatePoolComputationContext(
        pro=pro,
        stock_df=stock_df,
        focus_filter_diagnostics=focus_filter_diagnostics,
    )


def _apply_preliminary_candidate_filters(
    *,
    trade_date: str,
    stock_df: pd.DataFrame,
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    cooldown_tickers: set[str] | None,
    min_listing_days: int,
    record_focus_filter_stage_fn: Callable[..., None],
    build_beijing_exchange_mask_fn: Callable[[pd.DataFrame], pd.Series],
    estimate_trading_days_fn: Callable[[str, str], int],
    get_suspend_list_fn: Callable[[str], pd.DataFrame | None],
    get_limit_list_fn: Callable[[str], pd.DataFrame | None],
    resolve_cooldown_tickers_fn: Callable[..., set[str]],
    get_cooled_tickers_fn: Callable[[str], set[str]],
    apply_cooldown_filter_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame, int]],
    resolve_cooldown_shadow_review_tickers_fn: Callable[[], set[str]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    initial_count = len(stock_df)
    print(f"[CandidatePool] 全 A 股标的: {initial_count}")

    stock_df = _apply_core_candidate_filters(
        trade_date=trade_date,
        stock_df=stock_df,
        focus_filter_diagnostics=focus_filter_diagnostics,
        min_listing_days=min_listing_days,
        record_focus_filter_stage_fn=record_focus_filter_stage_fn,
        build_beijing_exchange_mask_fn=build_beijing_exchange_mask_fn,
        estimate_trading_days_fn=estimate_trading_days_fn,
    )

    stock_df = _apply_optional_ts_code_filter(
        stock_df=stock_df,
        filter_df=get_suspend_list_fn(trade_date),
        code_column="ts_code",
        label="排除停牌后",
        focus_filter_diagnostics=focus_filter_diagnostics,
        stage="suspend_filter",
        record_focus_filter_stage_fn=record_focus_filter_stage_fn,
    )

    limit_df = get_limit_list_fn(trade_date)
    limit_up_df = limit_df[limit_df["limit"] == "U"] if limit_df is not None and not limit_df.empty else None
    # 涨停股次日胜率53%、大涨率33%，显著优于普通候选池。
    # BTST在T+1买入，涨停股在T+1可正常交易。默认包含涨停股。
    exclude_limit_up = os.getenv("BTST_EXCLUDE_LIMIT_UP", "").strip().lower() in {"1", "true", "yes", "on"}
    if exclude_limit_up:
        stock_df = _apply_optional_ts_code_filter(
            stock_df=stock_df,
            filter_df=limit_up_df,
            code_column="ts_code",
            label="排除涨停后",
            focus_filter_diagnostics=focus_filter_diagnostics,
            stage="limit_up_filter",
            record_focus_filter_stage_fn=record_focus_filter_stage_fn,
        )
    else:
        _record_candidate_filter_stage(
            stock_df=stock_df,
            focus_filter_diagnostics=focus_filter_diagnostics,
            stage="limit_up_filter_included",
            record_focus_filter_stage_fn=record_focus_filter_stage_fn,
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
    _record_cooldown_filter_stage(
        stock_df=stock_df,
        cooldown_review_df=cooldown_review_df,
        focus_filter_diagnostics=focus_filter_diagnostics,
        record_focus_filter_stage_fn=record_focus_filter_stage_fn,
    )
    if resolved_cooldown_tickers:
        print(f"[CandidatePool] 排除冷却期后: {len(stock_df)} (过滤 {cooldown_filtered_count})")
        if not cooldown_review_df.empty:
            print(f"[CandidatePool] 保留冷却期 focus shadow review: {len(cooldown_review_df)}")

    return stock_df, cooldown_review_df


def _build_candidate_pool_prepared_universe(
    *,
    trade_date: str,
    stock_df: pd.DataFrame,
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    cooldown_tickers: set[str] | None,
    min_listing_days: int,
    record_focus_filter_stage_fn: Callable[..., None],
    build_beijing_exchange_mask_fn: Callable[[pd.DataFrame], pd.Series],
    estimate_trading_days_fn: Callable[[str, str], int],
    get_suspend_list_fn: Callable[[str], pd.DataFrame | None],
    get_limit_list_fn: Callable[[str], pd.DataFrame | None],
    resolve_cooldown_tickers_fn: Callable[..., set[str]],
    get_cooled_tickers_fn: Callable[[str], set[str]],
    apply_cooldown_filter_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame, int]],
    resolve_cooldown_shadow_review_tickers_fn: Callable[[], set[str]],
) -> CandidatePoolPreparedUniverse:
    stock_df, cooldown_review_df = _apply_preliminary_candidate_filters(
        trade_date=trade_date,
        stock_df=stock_df,
        focus_filter_diagnostics=focus_filter_diagnostics,
        cooldown_tickers=cooldown_tickers,
        min_listing_days=min_listing_days,
        record_focus_filter_stage_fn=record_focus_filter_stage_fn,
        build_beijing_exchange_mask_fn=build_beijing_exchange_mask_fn,
        estimate_trading_days_fn=estimate_trading_days_fn,
        get_suspend_list_fn=get_suspend_list_fn,
        get_limit_list_fn=get_limit_list_fn,
        resolve_cooldown_tickers_fn=resolve_cooldown_tickers_fn,
        get_cooled_tickers_fn=get_cooled_tickers_fn,
        apply_cooldown_filter_fn=apply_cooldown_filter_fn,
        resolve_cooldown_shadow_review_tickers_fn=resolve_cooldown_shadow_review_tickers_fn,
    )
    return CandidatePoolPreparedUniverse(
        stock_df=stock_df,
        cooldown_review_df=cooldown_review_df,
    )


def _apply_candidate_pool_liquidity_filters(
    *,
    trade_date: str,
    pro: Any,
    stock_df: pd.DataFrame,
    cooldown_review_df: pd.DataFrame,
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    min_estimated_amount_1d: float,
    min_avg_amount_20d: float,
    tushare_daily_batch_size: int,
    record_focus_filter_stage_fn: Callable[..., None],
    get_daily_basic_batch_fn: Callable[[str], pd.DataFrame | None],
    build_daily_basic_maps_fn: Callable[..., tuple[dict[str, float], dict[str, float]]],
    estimate_amount_from_daily_basic_fn: Callable[..., float],
    apply_estimated_liquidity_filter_with_logging_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame]],
    load_amount_map_and_low_liquidity_codes_fn: Callable[..., tuple[dict[str, float], set[str], bool]],
    get_avg_amount_20d_map_fn: Callable[..., dict[str, float]],
    get_avg_amount_20d_fn: Callable[..., float],
    enforce_tushare_daily_rate_limit_fn: Callable[[], None],
    filter_low_liquidity_candidates_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame, int]],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float], dict[str, float]]:
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
    return stock_df, cooldown_review_df, amount_map, mv_map


def _build_candidate_pool_liquidity_state(
    *,
    trade_date: str,
    pro: Any,
    prepared_universe: CandidatePoolPreparedUniverse,
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    min_estimated_amount_1d: float,
    min_avg_amount_20d: float,
    tushare_daily_batch_size: int,
    record_focus_filter_stage_fn: Callable[..., None],
    get_daily_basic_batch_fn: Callable[[str], pd.DataFrame | None],
    build_daily_basic_maps_fn: Callable[..., tuple[dict[str, float], dict[str, float]]],
    estimate_amount_from_daily_basic_fn: Callable[..., float],
    apply_estimated_liquidity_filter_with_logging_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame]],
    load_amount_map_and_low_liquidity_codes_fn: Callable[..., tuple[dict[str, float], set[str], bool]],
    get_avg_amount_20d_map_fn: Callable[..., dict[str, float]],
    get_avg_amount_20d_fn: Callable[..., float],
    enforce_tushare_daily_rate_limit_fn: Callable[[], None],
    filter_low_liquidity_candidates_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame, int]],
) -> CandidatePoolLiquidityState:
    stock_df, cooldown_review_df, amount_map, mv_map = _apply_candidate_pool_liquidity_filters(
        trade_date=trade_date,
        pro=pro,
        stock_df=prepared_universe.stock_df,
        cooldown_review_df=prepared_universe.cooldown_review_df,
        focus_filter_diagnostics=focus_filter_diagnostics,
        min_estimated_amount_1d=min_estimated_amount_1d,
        min_avg_amount_20d=min_avg_amount_20d,
        tushare_daily_batch_size=tushare_daily_batch_size,
        record_focus_filter_stage_fn=record_focus_filter_stage_fn,
        get_daily_basic_batch_fn=get_daily_basic_batch_fn,
        build_daily_basic_maps_fn=build_daily_basic_maps_fn,
        estimate_amount_from_daily_basic_fn=estimate_amount_from_daily_basic_fn,
        apply_estimated_liquidity_filter_with_logging_fn=apply_estimated_liquidity_filter_with_logging_fn,
        load_amount_map_and_low_liquidity_codes_fn=load_amount_map_and_low_liquidity_codes_fn,
        get_avg_amount_20d_map_fn=get_avg_amount_20d_map_fn,
        get_avg_amount_20d_fn=get_avg_amount_20d_fn,
        enforce_tushare_daily_rate_limit_fn=enforce_tushare_daily_rate_limit_fn,
        filter_low_liquidity_candidates_fn=filter_low_liquidity_candidates_fn,
    )
    return CandidatePoolLiquidityState(
        stock_df=stock_df,
        cooldown_review_df=cooldown_review_df,
        amount_map=amount_map,
        mv_map=mv_map,
    )


def _build_candidate_pool_outputs(
    *,
    trade_date: str,
    stock_df: pd.DataFrame,
    cooldown_review_df: pd.DataFrame,
    focus_filter_diagnostics: dict[str, dict[str, Any]],
    amount_map: dict[str, float],
    mv_map: dict[str, float],
    normalize_sw_map_fn: Callable[[Any], dict[str, str]],
    get_sw_industry_classification_fn: Callable[[], Any],
    is_disclosure_window_fn: Callable[[str], bool],
    build_candidate_stocks_fn: Callable[..., list["CandidateStock"]],
    finalize_focus_filter_diagnostics_fn: Callable[..., list[dict[str, Any]]],
) -> tuple[list["CandidateStock"], list["CandidateStock"], list[dict[str, Any]]]:
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
    return _compute_candidate_pool_candidates_impl(
        inputs=CandidatePoolComputeInputs(
            trade_date=trade_date,
            cooldown_tickers=cooldown_tickers,
            min_listing_days=min_listing_days,
            min_estimated_amount_1d=min_estimated_amount_1d,
            min_avg_amount_20d=min_avg_amount_20d,
            tushare_daily_batch_size=tushare_daily_batch_size,
            get_pro_fn=get_pro_fn,
            get_all_stock_basic_fn=get_all_stock_basic_fn,
            resolve_cooldown_shadow_review_tickers_fn=resolve_cooldown_shadow_review_tickers_fn,
            init_focus_filter_diagnostics_fn=init_focus_filter_diagnostics_fn,
            record_focus_filter_stage_fn=record_focus_filter_stage_fn,
            build_beijing_exchange_mask_fn=build_beijing_exchange_mask_fn,
            estimate_trading_days_fn=estimate_trading_days_fn,
            get_suspend_list_fn=get_suspend_list_fn,
            get_limit_list_fn=get_limit_list_fn,
            resolve_cooldown_tickers_fn=resolve_cooldown_tickers_fn,
            get_cooled_tickers_fn=get_cooled_tickers_fn,
            apply_cooldown_filter_fn=apply_cooldown_filter_fn,
            get_daily_basic_batch_fn=get_daily_basic_batch_fn,
            build_daily_basic_maps_fn=build_daily_basic_maps_fn,
            estimate_amount_from_daily_basic_fn=estimate_amount_from_daily_basic_fn,
            apply_estimated_liquidity_filter_with_logging_fn=apply_estimated_liquidity_filter_with_logging_fn,
            load_amount_map_and_low_liquidity_codes_fn=load_amount_map_and_low_liquidity_codes_fn,
            get_avg_amount_20d_map_fn=get_avg_amount_20d_map_fn,
            get_avg_amount_20d_fn=get_avg_amount_20d_fn,
            enforce_tushare_daily_rate_limit_fn=enforce_tushare_daily_rate_limit_fn,
            filter_low_liquidity_candidates_fn=filter_low_liquidity_candidates_fn,
            normalize_sw_map_fn=normalize_sw_map_fn,
            get_sw_industry_classification_fn=get_sw_industry_classification_fn,
            is_disclosure_window_fn=is_disclosure_window_fn,
            build_candidate_stocks_fn=build_candidate_stocks_fn,
            finalize_focus_filter_diagnostics_fn=finalize_focus_filter_diagnostics_fn,
        )
    )


def _compute_candidate_pool_candidates_impl(
    *,
    inputs: CandidatePoolComputeInputs,
) -> tuple[list["CandidateStock"], list["CandidateStock"], list[dict[str, Any]]]:
    context = _build_candidate_pool_computation_context(
        get_pro_fn=inputs.get_pro_fn,
        get_all_stock_basic_fn=inputs.get_all_stock_basic_fn,
        resolve_cooldown_shadow_review_tickers_fn=inputs.resolve_cooldown_shadow_review_tickers_fn,
        init_focus_filter_diagnostics_fn=inputs.init_focus_filter_diagnostics_fn,
    )
    if context is None:
        return [], [], []

    prepared_universe = _build_candidate_pool_prepared_universe(
        trade_date=inputs.trade_date,
        stock_df=context.stock_df,
        focus_filter_diagnostics=context.focus_filter_diagnostics,
        cooldown_tickers=inputs.cooldown_tickers,
        min_listing_days=inputs.min_listing_days,
        record_focus_filter_stage_fn=inputs.record_focus_filter_stage_fn,
        build_beijing_exchange_mask_fn=inputs.build_beijing_exchange_mask_fn,
        estimate_trading_days_fn=inputs.estimate_trading_days_fn,
        get_suspend_list_fn=inputs.get_suspend_list_fn,
        get_limit_list_fn=inputs.get_limit_list_fn,
        resolve_cooldown_tickers_fn=inputs.resolve_cooldown_tickers_fn,
        get_cooled_tickers_fn=inputs.get_cooled_tickers_fn,
        apply_cooldown_filter_fn=inputs.apply_cooldown_filter_fn,
        resolve_cooldown_shadow_review_tickers_fn=inputs.resolve_cooldown_shadow_review_tickers_fn,
    )

    liquidity_state = _build_candidate_pool_liquidity_state(
        trade_date=inputs.trade_date,
        pro=context.pro,
        prepared_universe=prepared_universe,
        focus_filter_diagnostics=context.focus_filter_diagnostics,
        min_estimated_amount_1d=inputs.min_estimated_amount_1d,
        min_avg_amount_20d=inputs.min_avg_amount_20d,
        tushare_daily_batch_size=inputs.tushare_daily_batch_size,
        record_focus_filter_stage_fn=inputs.record_focus_filter_stage_fn,
        get_daily_basic_batch_fn=inputs.get_daily_basic_batch_fn,
        build_daily_basic_maps_fn=inputs.build_daily_basic_maps_fn,
        estimate_amount_from_daily_basic_fn=inputs.estimate_amount_from_daily_basic_fn,
        apply_estimated_liquidity_filter_with_logging_fn=inputs.apply_estimated_liquidity_filter_with_logging_fn,
        load_amount_map_and_low_liquidity_codes_fn=inputs.load_amount_map_and_low_liquidity_codes_fn,
        get_avg_amount_20d_map_fn=inputs.get_avg_amount_20d_map_fn,
        get_avg_amount_20d_fn=inputs.get_avg_amount_20d_fn,
        enforce_tushare_daily_rate_limit_fn=inputs.enforce_tushare_daily_rate_limit_fn,
        filter_low_liquidity_candidates_fn=inputs.filter_low_liquidity_candidates_fn,
    )

    return _build_candidate_pool_outputs(
        trade_date=inputs.trade_date,
        stock_df=liquidity_state.stock_df,
        cooldown_review_df=liquidity_state.cooldown_review_df,
        focus_filter_diagnostics=context.focus_filter_diagnostics,
        amount_map=liquidity_state.amount_map,
        mv_map=liquidity_state.mv_map,
        normalize_sw_map_fn=inputs.normalize_sw_map_fn,
        get_sw_industry_classification_fn=inputs.get_sw_industry_classification_fn,
        is_disclosure_window_fn=inputs.is_disclosure_window_fn,
        build_candidate_stocks_fn=inputs.build_candidate_stocks_fn,
        finalize_focus_filter_diagnostics_fn=inputs.finalize_focus_filter_diagnostics_fn,
    )
