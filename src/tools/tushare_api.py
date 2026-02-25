import os
from typing import List

import pandas as pd

from src.data.models import Price, FinancialMetrics

_pro = None


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
    if ticker.startswith(("4", "8", "43", "83", "87")):
        return f"{ticker}.BJ"
    return f"{ticker}.SZ"


def get_ashare_prices_with_tushare(
    ticker: str,
    start_date: str,
    end_date: str
) -> List[Price]:
    """
    使用 Tushare 获取 A 股价格数据
    """
    pro = _get_pro()
    if not pro:
        return []
    try:
        ts_code = _to_ts_code(ticker)
        start_fmt = start_date.replace("-", "")
        end_fmt = end_date.replace("-", "")
        df = pro.daily(ts_code=ts_code, start_date=start_fmt, end_date=end_fmt)
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
        return prices
    except Exception:
        return []


def get_ashare_financial_metrics_with_tushare(
    ticker: str,
    end_date: str,
    limit: int = 10
) -> List[FinancialMetrics]:
    """
    使用 Tushare 获取 A 股财务指标
    """
    pro = _get_pro()
    if not pro:
        return []
    try:
        ts_code = _to_ts_code(ticker)
        end_fmt = end_date.replace("-", "")
        df_fin = pro.fina_indicator(ts_code=ts_code, end_date=end_fmt, limit=limit)
        if df_fin is None or df_fin.empty:
            return []
        metrics = []
        for _, row in df_fin.iterrows():
            metrics.append(
                FinancialMetrics(
                    ticker=ticker,
                    report_period=str(row.get("end_date", "")),
                    period="ttm",
                    currency="CNY",
                    market_cap=float(row.get("total_mv", 0)) * 10000 if pd.notna(row.get("total_mv")) else None,
                    price_to_earnings_ratio=float(row.get("q_sales_yoy", 0)) if pd.notna(row.get("q_sales_yoy")) else None,
                    price_to_book_ratio=float(row.get("bps", 0)) if pd.notna(row.get("bps")) else None,
                    return_on_equity=float(row.get("roe", 0)) if pd.notna(row.get("roe")) else None,
                    debt_to_equity=float(row.get("debt_to_assets", 0)) if pd.notna(row.get("debt_to_assets")) else None,
                    revenue_growth=float(row.get("q_sales_yoy", 0)) / 100 if pd.notna(row.get("q_sales_yoy")) else None,
                )
            )
        return metrics
    except Exception:
        return []


def get_ashare_market_cap_with_tushare(
    ticker: str,
    end_date: str
) -> float | None:
    """
    使用 Tushare 获取 A 股市值
    """
    pro = _get_pro()
    if not pro:
        return None
    try:
        ts_code = _to_ts_code(ticker)
        end_fmt = end_date.replace("-", "")
        df_daily = pro.daily_basic(ts_code=ts_code, trade_date=end_fmt)
        if df_daily is None or df_daily.empty:
            return None
        value = df_daily.iloc[0].get("total_mv", None)
        if value is None or pd.isna(value):
            return None
        return float(value) * 10000
    except Exception:
        return None
