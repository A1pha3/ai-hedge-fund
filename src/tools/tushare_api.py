import hashlib
import json
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from src.data.enhanced_cache import get_enhanced_cache
from src.data.models import FinancialMetrics, InsiderTrade, LineItem, Price
from src.tools.tushare_daily_gainers_helpers import build_daily_gainer_item, build_stock_basic_maps, fallback_trade_date_dataframe, fill_missing_pct_change
from src.tools.tushare_financial_metrics_helpers import build_financial_metric_support_maps, build_financial_metrics_from_frames, fetch_financial_metric_frames, resolve_financial_metrics_fetch_limit
from src.tools.tushare_insider_trade_helpers import build_holdertrade_query_kwargs, build_insider_trade_from_row
from src.tools.tushare_line_items_helpers import build_line_items_from_frames, fetch_line_item_statement_frames
from src.tools.tushare_sw_industry_helpers import build_sw_industry_mapping, load_sw_index_classification

_pro = None
_stock_name_cache: Dict[str, str] = {}
_persistent_cache = get_enhanced_cache()

# Tushare 原始 DataFrame 内存缓存 — 同一次运行内复用，避免多 Agent 并行重复请求
_tushare_df_cache: Dict[str, pd.DataFrame] = {}
_tushare_df_cache_lock = threading.Lock()


def _resolve_tushare_df_cache_max_entries() -> int:
    raw_value = os.getenv("TUSHARE_DF_CACHE_MAX_ENTRIES", "256")
    try:
        return max(64, int(raw_value))
    except ValueError:
        return 256


_TUSHARE_DF_CACHE_MAX_ENTRIES = _resolve_tushare_df_cache_max_entries()


def _get_tushare_cached_df(cache_key: str) -> Optional[pd.DataFrame]:
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


def _cached_tushare_dataframe_call(pro, api_name: str, dedupe: bool = False, ttl: Optional[int] = None, **kwargs) -> Optional[pd.DataFrame]:
    """带进程内 + 持久化缓存的通用 Tushare DataFrame 调用。"""
    cache_key = _make_tushare_query_cache_key(api_name, **kwargs)

    cached_df = _get_tushare_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    persisted_df = _persistent_cache.get(cache_key)
    if isinstance(persisted_df, pd.DataFrame):
        _store_tushare_cached_df(cache_key, persisted_df)
        return persisted_df.copy()

    api_func = getattr(pro, api_name, None)
    if api_func is None:
        return None

    try:
        df = api_func(**kwargs)
    except Exception as e:
        print(f"[Tushare] API {api_name}({kwargs}) 调用失败: {e}")
        return None

    if dedupe and df is not None and not df.empty:
        df = _dedupe_tushare_df(df)

    if df is not None:
        _store_tushare_cached_df(cache_key, df)
        _persistent_cache.set(cache_key, df, ttl=ttl if ttl is not None else _resolve_tushare_cache_ttl(api_name, **kwargs))
        return df.copy()

    return None


def _cached_tushare_call(pro, api_name: str, ts_code: str, limit: int, dedupe: bool = False) -> Optional[pd.DataFrame]:
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
    ticker = ticker.strip().lower()
    if ticker.startswith("sh"):
        return f"{ticker[2:]}.SH"
    if ticker.startswith("sz"):
        return f"{ticker[2:]}.SZ"
    if ticker.startswith("bj"):
        return f"{ticker[2:]}.BJ"
    if ticker.startswith(("6", "68", "51", "56", "58", "60")):
        return f"{ticker}.SH"
    if ticker.startswith(("0", "3", "15", "16", "18", "20")):
        return f"{ticker}.SZ"
    if ticker.startswith(("4", "8", "43", "83", "87", "92")):
        return f"{ticker}.BJ"
    return f"{ticker}.SZ"


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


def get_ashare_prices_with_tushare(ticker: str, start_date: str, end_date: str) -> List[Price]:
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
        df = _cached_tushare_dataframe_call(pro, "daily", ts_code=ts_code, start_date=start_fmt, end_date=end_fmt)
        print(f"[Tushare] 返回数据: {df.shape if df is not None else 'None'}")
        if df is None or df.empty:
            return []
        prices = []
        for _, row in df.iterrows():
            date_str = str(row["trade_date"])
            date_formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            prices.append(
                Price(
                    time=date_formatted,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["vol"]),
                )
            )
        prices.reverse()
        print(f"[Tushare] 成功获取 {len(prices)} 条数据")
        return prices
    except Exception as e:
        print(f"[Tushare] 获取价格数据失败: {e}")
        import traceback

        traceback.print_exc()
        return []


def get_ashare_daily_gainers_with_tushare(trade_date: str, pct_threshold: float = 3.0, include_name: bool = True) -> List[dict]:
    """
    使用 Tushare 获取指定交易日涨幅超过阈值的 A 股列表
    """
    pro = _get_pro()
    if not pro:
        print("[Tushare] 未初始化，检查 TUSHARE_TOKEN")
        return []
    try:
        trade_fmt = trade_date.replace("-", "")
        fields = "ts_code,trade_date,open,high,low,close,pre_close,vol,amount,pct_chg"
        df = _cached_tushare_dataframe_call(pro, "daily", trade_date=trade_fmt, fields=fields)
        if df is None or df.empty:
            df = fallback_trade_date_dataframe(_cached_tushare_dataframe_call, pro, trade_fmt, fields)
        if df is None or df.empty:
            return []
        df = fill_missing_pct_change(df)
        df = df[pd.notna(df["pct_chg"])]
        df = df[df["pct_chg"] > pct_threshold]
        if df.empty:
            return []

        name_map: dict[str, str] = {}
        area_map: dict[str, str] = {}
        industry_map: dict[str, str] = {}
        market_map: dict[str, str] = {}
        list_date_map: dict[str, str] = {}
        st_codes: set[str] = set()
        if include_name:
            df_basic = _cached_tushare_dataframe_call(pro, "stock_basic", exchange="", list_status="L", fields="ts_code,name,area,industry,market,list_date")
            name_map, area_map, industry_map, market_map, list_date_map, st_codes = build_stock_basic_maps(df_basic)

        results = []
        df_sorted = df.sort_values("pct_chg", ascending=False)
        for _, row in df_sorted.iterrows():
            ts_code = str(row["ts_code"])
            if ts_code in st_codes:
                continue
            results.append(build_daily_gainer_item(row, include_name, name_map, area_map, industry_map, market_map, list_date_map))
        return results
    except Exception as e:
        print(f"[Tushare] 获取涨幅榜失败: {e}")
        import traceback

        traceback.print_exc()
        return []


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
    df = df.sort_values(date_col, ascending=False).reset_index(drop=True)
    return df


def _get_latest_daily_basic(pro, ts_code: str, anchor_date: str, lookback_days: int = 30) -> dict | None:
    """获取指定日期（含）之前最近一个交易日的 daily_basic 数据行。

    返回包含 total_mv, pe, pe_ttm, pb, ps, ps_ttm 等字段的 dict，
    如果找不到数据则返回 None。
    内置内存缓存：同一 ts_code 批量获取一次 daily_basic，后续按日期过滤。
    """
    # 批量缓存：首次调用时获取近2年的 daily_basic 数据，后续按日期过滤
    batch_cache_key = f"{ts_code}_daily_basic_batch"
    date_fmt = anchor_date.replace("-", "")

    # 检查批量缓存
    df_batch = _get_tushare_cached_df(batch_cache_key)

    # 首次调用：批量获取近2年的 daily_basic 数据（一次 API 调用覆盖所有周期）
    if df_batch is None:
        # 始终以当前日期为终点，确保覆盖最新交易日数据
        today_fmt = datetime.now().strftime("%Y%m%d")
        try:
            # 使用 anchor_date 和 today 中较晚的作为终止日期
            actual_end = max(date_fmt, today_fmt)
            date_obj = datetime.strptime(actual_end, "%Y%m%d")
        except Exception:
            return None
        # 获取最近 730 天（约2年）的数据，覆盖所有财报周期
        start_fmt = (date_obj - timedelta(days=730)).strftime("%Y%m%d")
        try:
            # 使用 query 通用调用，避开 pro.daily_basic 可能的属性缺失
            df_batch = pro.query("daily_basic", ts_code=ts_code, start_date=start_fmt, end_date=actual_end)
            if df_batch is not None and not df_batch.empty and "trade_date" in df_batch.columns:
                df_batch = df_batch.sort_values("trade_date", ascending=False).reset_index(drop=True)
        except Exception as e:
            print(f"[Tushare] daily_basic 批量获取({ts_code}, {start_fmt}~{actual_end}) 失败: {e}")
            df_batch = pd.DataFrame()  # 空 DataFrame 表示已尝试

        _store_tushare_cached_df(batch_cache_key, df_batch)

    # 从批量数据中查找 <= anchor_date 的最近交易日
    if df_batch is None or df_batch.empty:
        return None

    mask = df_batch["trade_date"] <= date_fmt
    filtered = df_batch[mask]
    if filtered.empty:
        return None

    return filtered.iloc[0].to_dict()


def _get_latest_total_mv(pro, ts_code: str, anchor_date: str, lookback_days: int = 30) -> float | None:
    """获取指定日期（含）之前最近一个交易日的总市值（元）。"""
    row = _get_latest_daily_basic(pro, ts_code, anchor_date, lookback_days)
    if row is None:
        return None
    value = row.get("total_mv", None)
    if value is not None and not pd.isna(value):
        return float(value) * 10000
    return None


def get_ashare_financial_metrics_with_tushare(ticker: str, end_date: str, limit: int = 10, period: str = "ttm") -> List[FinancialMetrics]:
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
        fetch_limit = resolve_financial_metrics_fetch_limit(limit, period)
        financial_fetch_limit = limit * 4
        df_fin, df_cash, df_bal, df_income = fetch_financial_metric_frames(
            _cached_tushare_call,
            _cached_tushare_dataframe_call,
            pro,
            ts_code,
            fetch_limit,
            financial_fetch_limit,
        )
        if df_fin is None or df_fin.empty:
            return []
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


def get_ashare_line_items_with_tushare(
    ticker: str,
    line_items: List[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> List[LineItem]:
    """
    使用 Tushare 获取 A 股财务项目数据

    将 Tushare 的财务指标数据映射为 LineItem 格式
    """
    pro = _get_pro()
    if not pro:
        return []

    try:
        ts_code = _to_ts_code(ticker)
        fetch_limit = limit * 4
        df_fin, df_bal, df_cash, df_income = fetch_line_item_statement_frames(_cached_tushare_call, pro, ts_code, fetch_limit)
        if df_fin is None or df_fin.empty:
            return []
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
    except Exception as e:
        print(f"[Tushare] 获取财务项目失败: {e}")
        import traceback

        traceback.print_exc()
        return []


def get_ashare_insider_trades_with_tushare(ticker: str, end_date: str, start_date: str = None, limit: int = 100) -> List[InsiderTrade]:
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
        df = _cached_tushare_dataframe_call(pro, "stk_holdertrade", **build_holdertrade_query_kwargs(ts_code, end_date, start_date))
        if df is None or df.empty:
            return []

        if "ann_date" in df.columns:
            df = df.sort_values("ann_date", ascending=False)

        trades = []
        for _, row in df.head(limit).iterrows():
            trades.append(build_insider_trade_from_row(ticker, row))

        return trades
    except Exception as e:
        print(f"[Tushare] 获取股东增减持数据失败: {e}")
        return []


def get_stock_details(ticker: str, trade_date: Optional[str] = None) -> dict:
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
        return {
            "name": ticker,
            "area": "N/A",
            "industry": "N/A",
            "market": "N/A",
            "list_date": "N/A",
            "pct_chg": "N/A",
            "pre_close": "N/A",
            "close": "N/A",
        }

    try:
        ts_code = _to_ts_code(ticker)
        
        # 获取基本信息
        df_basic = _cached_tushare_dataframe_call(pro, "stock_basic", ts_code=ts_code, fields="ts_code,name,area,industry,market,list_date")
        basic_info = {
            "name": ticker,
            "area": "N/A",
            "industry": "N/A",
            "market": "N/A",
            "list_date": "N/A",
        }
        
        if df_basic is not None and not df_basic.empty:
            row = df_basic.iloc[0]
            basic_info["name"] = str(row["name"]) if pd.notna(row["name"]) else ticker
            basic_info["area"] = str(row["area"]) if pd.notna(row["area"]) else "N/A"
            basic_info["industry"] = str(row["industry"]) if pd.notna(row["industry"]) else "N/A"
            basic_info["market"] = str(row["market"]) if pd.notna(row["market"]) else "N/A"
            basic_info["list_date"] = str(row["list_date"]) if pd.notna(row["list_date"]) else "N/A"
        
        # 获取最新价格数据
        price_info = {
            "pct_chg": "N/A",
            "pre_close": "N/A",
            "close": "N/A",
        }
        
        if trade_date is None:
            # 获取最新日期的数据
            df_daily = _cached_tushare_dataframe_call(pro, "daily", ts_code=ts_code, limit=1, fields="trade_date,close,pre_close,pct_chg")
        else:
            # 获取指定日期的数据
            df_daily = _cached_tushare_dataframe_call(pro, "daily", trade_date=trade_date, ts_code=ts_code, fields="trade_date,close,pre_close,pct_chg")
        
        if df_daily is not None and not df_daily.empty:
            row = df_daily.iloc[0]
            price_info["pct_chg"] = f"{float(row['pct_chg']):.2f}%" if pd.notna(row["pct_chg"]) else "N/A"
            price_info["pre_close"] = f"{float(row['pre_close']):.2f}" if pd.notna(row["pre_close"]) else "N/A"
            price_info["close"] = f"{float(row['close']):.2f}" if pd.notna(row["close"]) else "N/A"
        
        return {**basic_info, **price_info}
        
    except Exception as e:
        print(f"[Tushare] 获取股票详细信息失败 ({ticker}): {e}")
        return {
            "name": ticker,
            "area": "N/A",
            "industry": "N/A",
            "market": "N/A",
            "list_date": "N/A",
            "pct_chg": "N/A",
            "pre_close": "N/A",
            "close": "N/A",
        }


# ============================================================================
# 以下为机构级多策略框架（Phase 0.2）新增接口
# ============================================================================

# 全量 stock_basic 缓存
_stock_basic_cache: Optional[pd.DataFrame] = None
_stock_basic_cache_lock = threading.Lock()

# 申万行业分类缓存
_sw_industry_cache: Optional[Dict[str, str]] = None
_sw_industry_cache_lock = threading.Lock()


def get_all_stock_basic() -> Optional[pd.DataFrame]:
    """
    获取全 A 股基本信息（代码/名称/上市日期/行业/市场/状态）。

    返回 DataFrame 列: ts_code, symbol, name, area, industry, market,
                       list_date, list_status, is_hs
    结果全局缓存，同一进程内仅调用一次。
    """
    global _stock_basic_cache
    with _stock_basic_cache_lock:
        if _stock_basic_cache is not None:
            return _stock_basic_cache.copy()

    pro = _get_pro()
    if pro is None:
        return None

    try:
        df = _cached_tushare_dataframe_call(
            pro,
            "stock_basic",
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date,list_status,is_hs",
            ttl=7 * 86400,
        )
        if df is not None and not df.empty:
            with _stock_basic_cache_lock:
                _stock_basic_cache = df
            return df.copy()
        return None
    except Exception as e:
        print(f"[Tushare] get_all_stock_basic 失败: {e}")
        return None


def get_daily_basic_batch(trade_date: str) -> Optional[pd.DataFrame]:
    """
    获取全市场当日基础面指标（PE/PB/换手率/成交额/总市值/流通市值）。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: ts_code, trade_date, close, turnover_rate, pe, pe_ttm,
                       pb, ps, ps_ttm, dv_ratio, dv_ttm, total_share, float_share,
                       free_share, total_mv, circ_mv, volume, amount
    """
    cache_key = f"daily_basic_batch_{trade_date}"
    cached_df = _get_tushare_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    pro = _get_pro()
    if pro is None:
        return None

    try:
        df = _cached_tushare_dataframe_call(
            pro,
            "daily_basic",
            trade_date=trade_date,
            fields="ts_code,trade_date,close,turnover_rate,pe,pe_ttm,pb,ps,ps_ttm,"
                   "dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv",
        )
        if df is not None and not df.empty:
            _store_tushare_cached_df(cache_key, df)
            return df.copy()
        return None
    except Exception as e:
        print(f"[Tushare] get_daily_basic_batch({trade_date}) 失败: {e}")
        return None


def get_daily_price_batch(trade_date: str) -> Optional[pd.DataFrame]:
    """
    获取全市场当日日线行情。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: ts_code, trade_date, open, high, low, close,
                       pre_close, vol, amount, pct_chg
    """
    cache_key = f"daily_price_batch_{trade_date}"
    cached_df = _get_tushare_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    pro = _get_pro()
    if pro is None:
        return None

    try:
        df = _cached_tushare_dataframe_call(
            pro,
            "daily",
            trade_date=trade_date,
            fields="ts_code,trade_date,open,high,low,close,pre_close,vol,amount,pct_chg",
        )
        if df is not None and not df.empty:
            _store_tushare_cached_df(cache_key, df)
            return df.copy()
        return None
    except Exception as e:
        print(f"[Tushare] get_daily_price_batch({trade_date}) 失败: {e}")
        return None


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
        df = _cached_tushare_dataframe_call(
            pro,
            "trade_cal",
            exchange="",
            start_date=start_date,
            end_date=end_date,
            is_open=1,
            fields="cal_date,is_open",
        )
        if df is None or df.empty:
            return []
        return sorted({str(row["cal_date"]) for _, row in df.iterrows() if str(row.get("cal_date") or "").strip()})
    except Exception as e:
        print(f"[Tushare] get_open_trade_dates({start_date}, {end_date}) 失败: {e}")
        return []


def get_sw_industry_classification() -> Optional[Dict[str, str]]:
    """
    获取申万一级行业分类映射：{ts_code -> 行业名称}。

    使用 tushare index_classify（L1 申万一级）获取行业列表，
    再用 index_member 获取每个行业的成分股。
    结果全局缓存。
    """
    global _sw_industry_cache
    with _sw_industry_cache_lock:
        if _sw_industry_cache is not None:
            return _sw_industry_cache.copy()

    pro = _get_pro()
    if pro is None:
        return None

    try:
        index_df = load_sw_index_classification(_cached_tushare_dataframe_call, pro)
        if index_df is None or index_df.empty:
            print("[Tushare] 无法获取申万行业分类")
            return None

        result = build_sw_industry_mapping(_cached_tushare_dataframe_call, pro, index_df)

        if result:
            with _sw_industry_cache_lock:
                _sw_industry_cache = result
        return result.copy() if result else None
    except Exception as e:
        print(f"[Tushare] get_sw_industry_classification 失败: {e}")
        return None


def get_limit_list(trade_date: str) -> Optional[pd.DataFrame]:
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
    cached_df = _get_tushare_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    pro = _get_pro()
    if pro is None:
        return None

    try:
        df = _cached_tushare_dataframe_call(pro, "limit_list_d", trade_date=trade_date)
        if df is not None and not df.empty:
            _store_tushare_cached_df(cache_key, df)
            return df.copy()
        return None
    except Exception as e:
        print(f"[Tushare] get_limit_list({trade_date}) 失败: {e}")
        return None


def get_suspend_list(trade_date: str) -> Optional[pd.DataFrame]:
    """
    获取当日停牌列表。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: ts_code, trade_date, suspend_timing, suspend_type
    """
    cache_key = f"suspend_list_{trade_date}"
    cached_df = _get_tushare_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    pro = _get_pro()
    if pro is None:
        return None

    try:
        df = _cached_tushare_dataframe_call(pro, "suspend_d", trade_date=trade_date)
        if df is not None and not df.empty:
            _store_tushare_cached_df(cache_key, df)
            return df.copy()
        return None
    except Exception as e:
        print(f"[Tushare] get_suspend_list({trade_date}) 失败: {e}")
        return None


def get_index_daily(index_code: str, start_date: str = "", end_date: str = "", limit: int = 120) -> Optional[pd.DataFrame]:
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
    cached_df = _get_tushare_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    pro = _get_pro()
    if pro is None:
        return None

    try:
        kwargs = {"ts_code": index_code}
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date
        if not start_date and not end_date:
            kwargs["limit"] = limit

        df = pro.index_daily(**kwargs)
        if df is not None and not df.empty:
            df = df.sort_values("trade_date").reset_index(drop=True)
            _store_tushare_cached_df(cache_key, df)
            return df.copy()
        return None
    except Exception as e:
        print(f"[Tushare] get_index_daily({index_code}) 失败: {e}")
        return None


def get_northbound_flow(trade_date: str = "", start_date: str = "", end_date: str = "", limit: int = 30) -> Optional[pd.DataFrame]:
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
    cached_df = _get_tushare_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    pro = _get_pro()
    if pro is None:
        return None

    try:
        kwargs: Dict = {}
        if trade_date:
            kwargs["trade_date"] = trade_date
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date
        if not trade_date and not start_date:
            kwargs["limit"] = limit

        df = pro.moneyflow_hsgt(**kwargs)
        if df is not None and not df.empty:
            df = df.sort_values("trade_date").reset_index(drop=True)
            _store_tushare_cached_df(cache_key, df)
            return df.copy()
        return None
    except Exception as e:
        print(f"[Tushare] get_northbound_flow 失败: {e}")
        return None
