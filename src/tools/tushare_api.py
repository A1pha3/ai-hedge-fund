import hashlib
import json
import os
import threading
from datetime import datetime
from typing import Any

import pandas as pd

from src.data.enhanced_cache import get_enhanced_cache
from src.data.models import FinancialMetrics, InsiderTrade, LineItem, Price
from src.tools.ashare_board_utils import to_tushare_code
from src.tools.tushare_daily_basic_helpers import load_daily_basic_batch, select_latest_daily_basic_row
from src.tools.tushare_daily_gainers_helpers import (
    build_daily_gainer_item,
    build_daily_gainers_with_tushare_data,
    build_stock_basic_maps,
    fallback_trade_date_dataframe,
    fill_missing_pct_change,
)
from src.tools.tushare_batch_fetch_helpers import fetch_batch_cached_frame, fetch_process_cached_frame
from src.tools.tushare_financial_metrics_helpers import build_financial_metric_support_maps, build_financial_metrics_from_frames, fetch_financial_metric_frames, resolve_financial_metrics_fetch_limit
from src.tools.tushare_insider_trade_helpers import build_holdertrade_query_kwargs, build_insider_trade_from_row
from src.tools.tushare_line_items_helpers import build_line_items_from_frames, fetch_line_item_statement_frames
from src.tools.tushare_market_data_helpers import (
    build_index_daily_query_kwargs,
    build_northbound_flow_query_kwargs,
    fetch_sorted_cached_market_frame,
)
from src.tools.tushare_stock_details_helpers import (
    build_default_stock_details,
    build_prices_from_tushare_daily_df,
    build_stock_basic_details,
    build_stock_price_details,
)
from src.tools.tushare_sw_industry_helpers import (
    build_sw_industry_mapping,
    extract_open_trade_dates,
    load_sw_index_classification,
    resolve_cached_sw_industry_mapping,
)

_pro = None
_stock_name_cache: dict[str, str] = {}
_persistent_cache = get_enhanced_cache()

# Tushare 原始 DataFrame 内存缓存 — 同一次运行内复用，避免多 Agent 并行重复请求
_tushare_df_cache: dict[str, pd.DataFrame] = {}
_tushare_df_cache_lock = threading.Lock()


def _resolve_tushare_df_cache_max_entries() -> int:
    raw_value = os.getenv("TUSHARE_DF_CACHE_MAX_ENTRIES", "256")
    try:
        return max(64, int(raw_value))
    except ValueError:
        return 256


_TUSHARE_DF_CACHE_MAX_ENTRIES = _resolve_tushare_df_cache_max_entries()


def _get_tushare_cached_df(cache_key: str) -> pd.DataFrame | None:
    with _tushare_df_cache_lock:
        cached_df = _tushare_df_cache.pop(cache_key, None)
        if cached_df is None:
            return None
        _tushare_df_cache[cache_key] = cached_df
        return cached_df.copy()


def _store_tushare_cached_df(cache_key: str, df: pd.DataFrame) -> None:
    with _tushare_df_cache_lock:
        if cache_key in _tushare_df_cache:
            _tushare_df_cache.pop(cache_key)
        _tushare_df_cache[cache_key] = df
        while len(_tushare_df_cache) > _TUSHARE_DF_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(_tushare_df_cache))
            _tushare_df_cache.pop(oldest_key)


def _normalize_tushare_cache_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_tushare_cache_value(inner_value) for key, inner_value in sorted(value.items()) if inner_value is not None}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_tushare_cache_value(item) for item in value]
    return value


def _make_tushare_query_cache_key(api_name: str, **kwargs) -> str:
    normalized_payload = {
        "api_name": api_name,
        "params": _normalize_tushare_cache_value(kwargs),
    }
    payload = json.dumps(normalized_payload, sort_keys=True, ensure_ascii=True, default=str)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"tushare_df:{api_name}:{digest}"


def _resolve_tushare_cache_ttl(api_name: str, **kwargs) -> int:
    reference_date = str(kwargs.get("trade_date") or kwargs.get("end_date") or kwargs.get("ann_date") or "")
    today = datetime.now().strftime("%Y%m%d")
    is_historical = bool(reference_date) and reference_date < today

    if api_name in {"daily", "daily_basic", "limit_list_d", "suspend_d", "trade_cal"}:
        return 30 * 86400 if is_historical else 6 * 3600
    if api_name in {"stock_basic", "index_classify", "index_member"}:
        return 7 * 86400
    if api_name in {"fina_indicator", "cashflow", "balancesheet", "income"}:
        return 14 * 86400
    if api_name == "stk_holdertrade":
        return 24 * 3600
    return 24 * 3600


def _get_persisted_tushare_cached_df(cache_key: str) -> pd.DataFrame | None:
    persisted_df = _persistent_cache.get(cache_key)
    if not isinstance(persisted_df, pd.DataFrame):
        return None
    _store_tushare_cached_df(cache_key, persisted_df)
    return persisted_df.copy()


def _call_tushare_dataframe_api(pro, api_name: str, **kwargs) -> pd.DataFrame | None:
    api_func = getattr(pro, api_name, None)
    if api_func is None:
        return None
    try:
        return api_func(**kwargs)
    except Exception as e:
        print(f"[Tushare] API {api_name}({kwargs}) 调用失败: {e}")
        return None


def _persist_tushare_dataframe_result(cache_key: str, df: pd.DataFrame, *, api_name: str, ttl: int | None, **kwargs) -> pd.DataFrame:
    _store_tushare_cached_df(cache_key, df)
    _persistent_cache.set(cache_key, df, ttl=ttl if ttl is not None else _resolve_tushare_cache_ttl(api_name, **kwargs))
    return df.copy()


def _cached_tushare_dataframe_call(pro, api_name: str, dedupe: bool = False, ttl: int | None = None, **kwargs) -> pd.DataFrame | None:
    """带进程内 + 持久化缓存的通用 Tushare DataFrame 调用。"""
    cache_key = _make_tushare_query_cache_key(api_name, **kwargs)

    cached_df = _get_tushare_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    persisted_df = _get_persisted_tushare_cached_df(cache_key)
    if persisted_df is not None:
        return persisted_df

    df = _call_tushare_dataframe_api(pro, api_name, **kwargs)

    if dedupe and df is not None and not df.empty:
        df = _dedupe_tushare_df(df)

    if df is not None:
        return _persist_tushare_dataframe_result(
            cache_key,
            df,
            api_name=api_name,
            ttl=ttl,
            **kwargs,
        )

    return None


def _cached_tushare_call(pro, api_name: str, ts_code: str, limit: int, dedupe: bool = False) -> pd.DataFrame | None:
    """
    带内存缓存的 Tushare API 调用。

    同一 ts_code + api_name 的首次调用会实际请求 Tushare，后续直接从内存返回。
    limit 取已缓存和请求中的较大值，确保不会因 limit 不同而丢失数据。
    重新获取失败时，保留已有的有效缓存（防止空数据覆盖有效数据）。
    """
    return _cached_tushare_dataframe_call(pro, api_name, ts_code=ts_code, limit=limit, dedupe=dedupe)


def _get_pro():
    """
    初始化并返回 Tushare Pro 实例
    """
    global _pro
    if _pro is not None:
        return _pro
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        return None
    try:
        import tushare as ts

        # 直接使用 token 创建 pro_api，避免写入文件
        _pro = ts.pro_api(token=token)
        return _pro
    except Exception:
        return None


def _to_ts_code(ticker: str) -> str:
    """
    转换为 Tushare 代码格式
    """
    return to_tushare_code(ticker)


def get_stock_name(ticker: str) -> str:
    """
    获取 A 股股票名称

    Args:
        ticker: 股票代码

    Returns:
        str: 股票名称，如果获取失败则返回股票代码
    """
    if ticker in _stock_name_cache:
        return _stock_name_cache[ticker]

    pro = _get_pro()
    if not pro:
        return ticker

    try:
        ts_code = _to_ts_code(ticker)
        df = _cached_tushare_dataframe_call(pro, "stock_basic", ts_code=ts_code, fields="ts_code,name")
        if df is not None and not df.empty:
            name = str(df.iloc[0]["name"])
            _stock_name_cache[ticker] = name
            return name
    except Exception:
        pass

    return ticker


def get_ashare_prices_with_tushare(ticker: str, start_date: str, end_date: str) -> list[Price]:
    """
    使用 Tushare 获取 A 股价格数据
    """
    pro = _get_pro()
    if not pro:
        print("[Tushare] 未初始化，检查 TUSHARE_TOKEN")
        return []
    try:
        ts_code = _to_ts_code(ticker)
        start_fmt = start_date.replace("-", "")
        end_fmt = end_date.replace("-", "")
        print(f"[Tushare] 调用 daily API: ts_code={ts_code}, start_date={start_fmt}, end_date={end_fmt}")
        df = _fetch_tushare_ashare_prices_df(pro, ts_code, start_fmt, end_fmt)
        print(f"[Tushare] 返回数据: {df.shape if df is not None else 'None'}")
        prices = build_prices_from_tushare_daily_df(df)
        print(f"[Tushare] 成功获取 {len(prices)} 条数据")
        return prices
    except Exception as e:
        print(f"[Tushare] 获取价格数据失败: {e}")
        import traceback

        traceback.print_exc()
        return []


def _fetch_tushare_ashare_prices_df(pro, ts_code: str, start_fmt: str, end_fmt: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "daily",
        ts_code=ts_code,
        start_date=start_fmt,
        end_date=end_fmt,
    )


def get_ashare_daily_gainers_with_tushare(trade_date: str, pct_threshold: float = 3.0, include_name: bool = True) -> list[dict]:
    """
    使用 Tushare 获取指定交易日涨幅超过阈值的 A 股列表
    """
    pro = _get_pro()
    if not pro:
        print("[Tushare] 未初始化，检查 TUSHARE_TOKEN")
        return []
    try:
        trade_fmt = _normalize_tushare_trade_date(trade_date)
        return build_daily_gainers_with_tushare_data(
            pro=pro,
            trade_fmt=trade_fmt,
            pct_threshold=pct_threshold,
            include_name=include_name,
            fetch_dataframe=_cached_tushare_dataframe_call,
            fallback_trade_date_dataframe_fn=fallback_trade_date_dataframe,
            fill_missing_pct_change_fn=fill_missing_pct_change,
            build_stock_basic_maps_fn=build_stock_basic_maps,
            build_daily_gainer_item_fn=build_daily_gainer_item,
        )
    except Exception as e:
        print(f"[Tushare] 获取涨幅榜失败: {e}")
        import traceback

        traceback.print_exc()
        return []


def _normalize_tushare_trade_date(trade_date: str) -> str:
    return trade_date.replace("-", "")


def _validate_margin(value: float | None) -> float | None:
    """验证利润率数据，过滤异常值（利润率应在 -100% 到 100% 之间）"""
    if value is None:
        return None
    if value < -1.0 or value > 1.0:
        return None
    return value


def _validate_roe(value: float | None) -> float | None:
    """验证 ROE 数据，过滤异常值（ROE 应在 -200% 到 200% 之间）"""
    if value is None:
        return None
    if value < -2.0 or value > 2.0:
        return None
    return value


def _dedupe_tushare_df(df: pd.DataFrame, date_col: str = "end_date") -> pd.DataFrame:
    """去重 Tushare 返回的 DataFrame：同一 end_date 可能有多行（如数据修正）。

    策略：对每个 end_date 保留非 NaN 字段最多的那一行。
    这样可避免 iloc[0] 取到字段缺失较多的行。
    """
    if df is None or df.empty or date_col not in df.columns:
        return df
    # 计算每行的非NaN字段数
    df = df.copy()
    df["_non_null_cnt"] = df.drop(columns=[date_col], errors="ignore").notna().sum(axis=1)
    # 按 end_date 分组，保留非NaN最多的行
    df = df.sort_values([date_col, "_non_null_cnt"], ascending=[True, False])
    df = df.drop_duplicates(subset=[date_col], keep="first")
    df = df.drop(columns=["_non_null_cnt"])
    # 恢复原始排序（按 end_date 降序）
    return df.sort_values(date_col, ascending=False).reset_index(drop=True)


def _get_latest_daily_basic(pro, ts_code: str, anchor_date: str, lookback_days: int = 30) -> dict | None:
    """获取指定日期（含）之前最近一个交易日的 daily_basic 数据行。

    返回包含 total_mv, pe, pe_ttm, pb, ps, ps_ttm 等字段的 dict，
    如果找不到数据则返回 None。
    内置内存缓存：同一 ts_code 批量获取一次 daily_basic，后续按日期过滤。
    """
    batch_cache_key = f"{ts_code}_daily_basic_batch"
    df_batch = load_daily_basic_batch(
        pro=pro,
        ts_code=ts_code,
        anchor_date=anchor_date,
        cache_key=batch_cache_key,
        get_cached_df=_get_tushare_cached_df,
        store_cached_df=_store_tushare_cached_df,
    )
    return select_latest_daily_basic_row(df_batch, anchor_date)


def _get_latest_total_mv(pro, ts_code: str, anchor_date: str, lookback_days: int = 30) -> float | None:
    """获取指定日期（含）之前最近一个交易日的总市值（元）。"""
    row = _get_latest_daily_basic(pro, ts_code, anchor_date, lookback_days)
    if row is None:
        return None
    value = row.get("total_mv", None)
    if value is not None and not pd.isna(value):
        return float(value) * 10000
    return None


def _load_tushare_financial_metric_frames(pro, ts_code: str, *, limit: int, period: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    fetch_limit = resolve_financial_metrics_fetch_limit(limit, period)
    financial_fetch_limit = limit * 4
    return fetch_financial_metric_frames(
        _cached_tushare_call,
        _cached_tushare_dataframe_call,
        pro,
        ts_code,
        fetch_limit,
        financial_fetch_limit,
    )


def _build_tushare_financial_metrics(
    *,
    ticker: str,
    end_date: str,
    limit: int,
    period: str,
    pro,
    ts_code: str,
    df_fin: pd.DataFrame,
    df_cash: pd.DataFrame | None,
    df_bal: pd.DataFrame | None,
    df_income: pd.DataFrame | None,
) -> list[FinancialMetrics]:
    fcf_values, raw_income_map, ttm_income_map = build_financial_metric_support_maps(df_fin, df_cash, df_income)
    return build_financial_metrics_from_frames(
        ticker=ticker,
        end_date=end_date,
        limit=limit,
        period=period,
        pro=pro,
        ts_code=ts_code,
        df_fin=df_fin,
        df_cash=df_cash,
        df_bal=df_bal,
        df_income=df_income,
        fcf_values=fcf_values,
        raw_income_map=raw_income_map,
        ttm_income_map=ttm_income_map,
        get_latest_daily_basic=_get_latest_daily_basic,
        validate_margin=_validate_margin,
        validate_roe=_validate_roe,
    )


def get_ashare_financial_metrics_with_tushare(ticker: str, end_date: str, limit: int = 10, period: str = "ttm") -> list[FinancialMetrics]:
    """
    使用 Tushare 获取 A 股财务指标

    Args:
        period: "ttm" (默认, 返回所有季度含TTM合成) | "annual" (仅返回年报 1231) | "quarterly" (仅返回季报)
    """
    pro = _get_pro()
    if not pro:
        return []
    try:
        ts_code = _to_ts_code(ticker)
        df_fin, df_cash, df_bal, df_income = _load_tushare_financial_metric_frames(
            pro,
            ts_code,
            limit=limit,
            period=period,
        )
        if df_fin is None or df_fin.empty:
            return []
        return _build_tushare_financial_metrics(
            ticker=ticker,
            end_date=end_date,
            limit=limit,
            period=period,
            pro=pro,
            ts_code=ts_code,
            df_fin=df_fin,
            df_cash=df_cash,
            df_bal=df_bal,
            df_income=df_income,
        )
    except Exception as e:
        print(f"[Tushare] 获取财务指标失败: {e}")
        return []


def get_ashare_market_cap_with_tushare(ticker: str, end_date: str) -> float | None:
    """
    使用 Tushare 获取 A 股市值。
    优先使用 _get_latest_daily_basic 缓存（与 get_financial_metrics 共享）。
    """
    pro = _get_pro()
    if not pro:
        return None
    try:
        ts_code = _to_ts_code(ticker)
        # 优先从 daily_basic 缓存获取市值
        daily_data = _get_latest_daily_basic(pro, ts_code, end_date)
        if daily_data:
            mv = daily_data.get("total_mv")
            if mv is not None and not pd.isna(mv):
                return float(mv) * 10000
        return None
    except Exception as e:
        print(f"[Tushare] 获取市值失败({ticker}): {e}")
        return None


def _load_tushare_line_item_frames(pro, ts_code: str, *, limit: int) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    return fetch_line_item_statement_frames(
        _cached_tushare_call,
        pro,
        ts_code,
        limit * 4,
    )


def _build_tushare_line_items(
    *,
    ticker: str,
    line_items: list[str],
    period: str,
    limit: int,
    df_fin: pd.DataFrame,
    df_bal: pd.DataFrame | None,
    df_cash: pd.DataFrame | None,
    df_income: pd.DataFrame | None,
) -> list[LineItem]:
    return build_line_items_from_frames(
        ticker=ticker,
        line_items=line_items,
        period=period,
        limit=limit,
        df_fin=df_fin,
        df_bal=df_bal,
        df_cash=df_cash,
        df_income=df_income,
    )


def _resolve_tushare_line_items(
    *,
    pro,
    ticker: str,
    line_items: list[str],
    period: str,
    limit: int,
) -> list[LineItem]:
    ts_code = _to_ts_code(ticker)
    df_fin, df_bal, df_cash, df_income = _load_tushare_line_item_frames(
        pro,
        ts_code,
        limit=limit,
    )
    if df_fin is None or df_fin.empty:
        return []
    return _build_tushare_line_items(
        ticker=ticker,
        line_items=line_items,
        period=period,
        limit=limit,
        df_fin=df_fin,
        df_bal=df_bal,
        df_cash=df_cash,
        df_income=df_income,
    )


def get_ashare_line_items_with_tushare(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[LineItem]:
    """
    使用 Tushare 获取 A 股财务项目数据

    将 Tushare 的财务指标数据映射为 LineItem 格式
    """
    pro = _get_pro()
    if not pro:
        return []

    try:
        return _resolve_tushare_line_items(
            pro=pro,
            ticker=ticker,
            line_items=line_items,
            period=period,
            limit=limit,
        )
    except Exception as e:
        print(f"[Tushare] 获取财务项目失败: {e}")
        import traceback

        traceback.print_exc()
        return []


def _load_tushare_insider_trade_frame(pro, ts_code: str, end_date: str, start_date: str | None) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "stk_holdertrade",
        **build_holdertrade_query_kwargs(ts_code, end_date, start_date),
    )


def _build_tushare_insider_trades(ticker: str, df: pd.DataFrame, *, limit: int) -> list[InsiderTrade]:
    if "ann_date" in df.columns:
        df = df.sort_values("ann_date", ascending=False)
    return [build_insider_trade_from_row(ticker, row) for _, row in df.head(limit).iterrows()]


def get_ashare_insider_trades_with_tushare(ticker: str, end_date: str, start_date: str | None = None, limit: int = 100) -> list[InsiderTrade]:
    """
    使用 Tushare stk_holdertrade 获取 A 股股东增减持数据

    Args:
        ticker: 股票代码 (如 600567)
        end_date: 结束日期 (YYYY-MM-DD)
        start_date: 开始日期 (YYYY-MM-DD), 可选
        limit: 最大记录数

    Returns:
        List[InsiderTrade]
    """
    pro = _get_pro()
    if not pro:
        return []
    try:
        ts_code = _to_ts_code(ticker)
        df = _load_tushare_insider_trade_frame(pro, ts_code, end_date, start_date)
        if df is None or df.empty:
            return []
        return _build_tushare_insider_trades(ticker, df, limit=limit)
    except Exception as e:
        print(f"[Tushare] 获取股东增减持数据失败: {e}")
        return []


def _load_tushare_stock_basic_details(pro, ts_code: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "stock_basic",
        ts_code=ts_code,
        fields="ts_code,name,area,industry,market,list_date",
    )


def _load_tushare_stock_price_details(pro, ts_code: str, trade_date: str | None) -> pd.DataFrame | None:
    daily_kwargs: dict[str, Any] = {
        "ts_code": ts_code,
        "fields": "trade_date,close,pre_close,pct_chg",
    }
    if trade_date is None:
        daily_kwargs["limit"] = 1
    else:
        daily_kwargs["trade_date"] = trade_date
    return _cached_tushare_dataframe_call(pro, "daily", **daily_kwargs)


def get_stock_details(ticker: str, trade_date: str | None = None) -> dict:
    """
    获取股票详细信息，包括基本信息和最新价格数据

    Args:
        ticker: 股票代码（如 000807）
        trade_date: 交易日期（如 20260302），默认为最新日期

    Returns:
        dict: 股票详细信息，包含以下字段：
              - name: 股票名称
              - area: 地域
              - industry: 所属行业
              - market: 市场类型
              - list_date: 上市日期
              - pct_chg: 涨幅（%）
              - pre_close: 昨日收盘价
              - close: 今日收盘价
              字段不存在则为 N/A
    """
    pro = _get_pro()
    if not pro:
        return build_default_stock_details(ticker)

    try:
        ts_code = _to_ts_code(ticker)
        df_basic = _load_tushare_stock_basic_details(pro, ts_code)
        df_daily = _load_tushare_stock_price_details(pro, ts_code, trade_date)

        return {
            **build_stock_basic_details(ticker, df_basic),
            **build_stock_price_details(df_daily),
        }
    except Exception as e:
        print(f"[Tushare] 获取股票详细信息失败 ({ticker}): {e}")
        return build_default_stock_details(ticker)


# ============================================================================
# 以下为机构级多策略框架（Phase 0.2）新增接口
# ============================================================================

# 全量 stock_basic 缓存
_stock_basic_cache: pd.DataFrame | None = None
_stock_basic_cache_lock = threading.Lock()

# 申万行业分类缓存
_sw_industry_cache: dict[str, str] | None = None
_sw_industry_cache_lock = threading.Lock()


def _fetch_tushare_all_stock_basic(pro) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "stock_basic",
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,area,industry,market,list_date,list_status,is_hs",
        ttl=7 * 86400,
    )


def get_all_stock_basic() -> pd.DataFrame | None:
    """
    获取全 A 股基本信息（代码/名称/上市日期/行业/市场/状态）。

    返回 DataFrame 列: ts_code, symbol, name, area, industry, market,
                       list_date, list_status, is_hs
    结果全局缓存，同一进程内仅调用一次。
    """
    global _stock_basic_cache
    with _stock_basic_cache_lock:
        cached_stock_basic = _stock_basic_cache

    pro = _get_pro()
    if pro is None:
        return None

    try:
        return fetch_process_cached_frame(
            cached_frame=cached_stock_basic,
            fetch_frame=lambda: _fetch_tushare_all_stock_basic(pro),
            cache_frame=lambda df: _cache_stock_basic_frame(df),
        )
    except Exception as e:
        print(f"[Tushare] get_all_stock_basic 失败: {e}")
        return None


def _fetch_tushare_daily_basic_batch(pro, trade_date: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "daily_basic",
        trade_date=trade_date,
        fields="ts_code,trade_date,close,turnover_rate,pe,pe_ttm,pb,ps,ps_ttm,"
        "dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv",
    )


def get_daily_basic_batch(trade_date: str) -> pd.DataFrame | None:
    """
    获取全市场当日基础面指标（PE/PB/换手率/成交额/总市值/流通市值）。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: ts_code, trade_date, close, turnover_rate, pe, pe_ttm,
                       pb, ps, ps_ttm, dv_ratio, dv_ttm, total_share, float_share,
                       free_share, total_mv, circ_mv, volume, amount
    """
    cache_key = f"daily_basic_batch_{trade_date}"

    pro = _get_pro()
    if pro is None:
        return None

    try:
        return fetch_batch_cached_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_daily_basic_batch(pro, trade_date),
        )
    except Exception as e:
        print(f"[Tushare] get_daily_basic_batch({trade_date}) 失败: {e}")
        return None


def _fetch_tushare_daily_price_batch(pro, trade_date: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "daily",
        trade_date=trade_date,
        fields="ts_code,trade_date,open,high,low,close,pre_close,vol,amount,pct_chg",
    )


def get_daily_price_batch(trade_date: str) -> pd.DataFrame | None:
    """
    获取全市场当日日线行情。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: ts_code, trade_date, open, high, low, close,
                       pre_close, vol, amount, pct_chg
    """
    cache_key = f"daily_price_batch_{trade_date}"

    pro = _get_pro()
    if pro is None:
        return None

    try:
        return fetch_batch_cached_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_daily_price_batch(pro, trade_date),
        )
    except Exception as e:
        print(f"[Tushare] get_daily_price_batch({trade_date}) 失败: {e}")
        return None


def _cache_stock_basic_frame(df: pd.DataFrame) -> None:
    global _stock_basic_cache
    with _stock_basic_cache_lock:
        _stock_basic_cache = df


def get_open_trade_dates(start_date: str, end_date: str) -> list[str]:
    """
    获取区间内开市交易日列表。

    参数:
        start_date: 开始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD
    """
    pro = _get_pro()
    if pro is None:
        return []

    try:
        df = _fetch_tushare_open_trade_dates(pro, start_date, end_date)
        return extract_open_trade_dates(df)
    except Exception as e:
        print(f"[Tushare] get_open_trade_dates({start_date}, {end_date}) 失败: {e}")
        return []


def _fetch_tushare_open_trade_dates(pro, start_date: str, end_date: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "trade_cal",
        exchange="",
        start_date=start_date,
        end_date=end_date,
        is_open=1,
        fields="cal_date,is_open",
    )


def _resolve_tushare_sw_industry_mapping(pro, cached_mapping: dict[str, str] | None) -> dict[str, str] | None:
    return resolve_cached_sw_industry_mapping(
        cached_mapping=cached_mapping,
        load_index_df=lambda: load_sw_index_classification(_cached_tushare_dataframe_call, pro),
        build_mapping=lambda index_df: build_sw_industry_mapping(_cached_tushare_dataframe_call, pro, index_df),
        cache_mapping=_cache_sw_industry_mapping,
    )


def get_sw_industry_classification() -> dict[str, str] | None:
    """
    获取申万一级行业分类映射：{ts_code -> 行业名称}。

    使用 tushare index_classify（L1 申万一级）获取行业列表，
    再用 index_member 获取每个行业的成分股。
    结果全局缓存。
    """
    global _sw_industry_cache
    with _sw_industry_cache_lock:
        cached_mapping = _sw_industry_cache

    pro = _get_pro()
    if pro is None:
        return None

    try:
        result = _resolve_tushare_sw_industry_mapping(pro, cached_mapping)
        if result is None and cached_mapping is None:
            print("[Tushare] 无法获取申万行业分类")
        return result
    except Exception as e:
        print(f"[Tushare] get_sw_industry_classification 失败: {e}")
        return None


def _cache_sw_industry_mapping(mapping: dict[str, str]) -> None:
    global _sw_industry_cache
    with _sw_industry_cache_lock:
        _sw_industry_cache = mapping


def _fetch_tushare_limit_list(pro, trade_date: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(pro, "limit_list_d", trade_date=trade_date)


def get_limit_list(trade_date: str) -> pd.DataFrame | None:
    """
    获取当日涨跌停列表。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: trade_date, ts_code, name, close, pct_chg,
                       amp, fc_ratio, fl_ratio, fd_amount, first_time, last_time,
                       open_times, up_stat, limit_times, limit
    其中 limit 字段: U=涨停, D=跌停, Z=炸板
    """
    cache_key = f"limit_list_{trade_date}"

    pro = _get_pro()
    if pro is None:
        return None

    try:
        return fetch_batch_cached_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_limit_list(pro, trade_date),
        )
    except Exception as e:
        print(f"[Tushare] get_limit_list({trade_date}) 失败: {e}")
        return None


def get_suspend_list(trade_date: str) -> pd.DataFrame | None:
    """
    获取当日停牌列表。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: ts_code, trade_date, suspend_timing, suspend_type
    """
    cache_key = f"suspend_list_{trade_date}"

    pro = _get_pro()
    if pro is None:
        return None

    try:
        return fetch_batch_cached_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_suspend_list(pro, trade_date),
        )
    except Exception as e:
        print(f"[Tushare] get_suspend_list({trade_date}) 失败: {e}")
        return None


def _fetch_tushare_suspend_list(pro, trade_date: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(pro, "suspend_d", trade_date=trade_date)


def _fetch_tushare_index_daily(pro, kwargs: dict[str, Any]) -> pd.DataFrame | None:
    return pro.index_daily(**kwargs)


def get_index_daily(index_code: str, start_date: str = "", end_date: str = "", limit: int = 120) -> pd.DataFrame | None:
    """
    获取指数日线行情（沪深300/上证50/中证500等）。

    参数:
        index_code: 指数代码（如 '000300.SH' 沪深300, '000016.SH' 上证50, '000905.SH' 中证500）
        start_date: 开始日期 YYYYMMDD（可选）
        end_date: 结束日期 YYYYMMDD（可选）
        limit: 返回行数

    返回 DataFrame 列: ts_code, trade_date, close, open, high, low, pre_close,
                       change, pct_chg, vol, amount
    """
    cache_key = f"index_daily_{index_code}_{start_date}_{end_date}_{limit}"
    pro = _get_pro()
    if pro is None:
        return None

    try:
        kwargs = build_index_daily_query_kwargs(index_code, start_date, end_date, limit)
        return fetch_sorted_cached_market_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_index_daily(pro, kwargs),
        )
    except Exception as e:
        print(f"[Tushare] get_index_daily({index_code}) 失败: {e}")
        return None


def _fetch_tushare_northbound_flow(pro, kwargs: dict[str, Any]) -> pd.DataFrame | None:
    return pro.moneyflow_hsgt(**kwargs)


def get_northbound_flow(trade_date: str = "", start_date: str = "", end_date: str = "", limit: int = 30) -> pd.DataFrame | None:
    """
    获取北向资金（沪股通+深股通）每日流向。

    参数:
        trade_date: 单日查询 YYYYMMDD（可选）
        start_date/end_date: 区间查询（可选）
        limit: 默认 30 日

    返回 DataFrame 列: trade_date, ggt_ss（港股通上海）, ggt_sz（港股通深圳）,
                       hgt（沪股通）, sgt（深股通）, north_money（北向合计）, south_money（南向合计）
    """
    cache_key = f"northbound_{trade_date}_{start_date}_{end_date}_{limit}"
    pro = _get_pro()
    if pro is None:
        return None

    try:
        kwargs = build_northbound_flow_query_kwargs(trade_date, start_date, end_date, limit)
        return fetch_sorted_cached_market_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_northbound_flow(pro, kwargs),
        )
    except Exception as e:
        print(f"[Tushare] get_northbound_flow 失败: {e}")
        return None
