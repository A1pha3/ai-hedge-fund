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
        # Tushare fina_indicator 使用 end_date 参数，但需要正确的日期格式
        # 尝试使用 limit 参数获取最新数据
        df_fin = pro.fina_indicator(ts_code=ts_code, limit=limit)
        if df_fin is None or df_fin.empty:
            return []
        metrics = []
        for _, row in df_fin.iterrows():
            # 从 daily_basic 获取市值数据
            end_date_str = str(row.get("end_date", ""))
            market_cap = None
            try:
                df_daily = pro.daily_basic(ts_code=ts_code, trade_date=end_date_str)
                if df_daily is not None and not df_daily.empty:
                    market_cap = float(df_daily.iloc[0].get("total_mv", 0)) * 10000
            except Exception:
                pass
            
            metrics.append(
                FinancialMetrics(
                    ticker=ticker,
                    report_period=end_date_str,
                    period="ttm",
                    currency="CNY",
                    market_cap=market_cap,
                    enterprise_value=None,
                    price_to_earnings_ratio=float(row.get("pe", 0)) if pd.notna(row.get("pe")) else None,
                    price_to_book_ratio=float(row.get("pb", 0)) if pd.notna(row.get("pb")) else None,
                    price_to_sales_ratio=None,
                    enterprise_value_to_ebitda_ratio=None,
                    enterprise_value_to_revenue_ratio=None,
                    free_cash_flow_yield=None,
                    peg_ratio=None,
                    gross_margin=float(row.get("grossprofit_margin", 0)) if pd.notna(row.get("grossprofit_margin")) else None,
                    operating_margin=float(row.get("op_of_gr", 0)) if pd.notna(row.get("op_of_gr")) else None,
                    net_margin=float(row.get("netprofit_margin", 0)) if pd.notna(row.get("netprofit_margin")) else None,
                    return_on_equity=float(row.get("roe", 0)) if pd.notna(row.get("roe")) else None,
                    return_on_assets=float(row.get("roa", 0)) if pd.notna(row.get("roa")) else None,
                    return_on_invested_capital=None,
                    asset_turnover=float(row.get("assets_turn", 0)) if pd.notna(row.get("assets_turn")) else None,
                    inventory_turnover=None,
                    receivables_turnover=None,
                    days_sales_outstanding=None,
                    operating_cycle=None,
                    working_capital_turnover=None,
                    current_ratio=float(row.get("current_ratio", 0)) if pd.notna(row.get("current_ratio")) else None,
                    quick_ratio=float(row.get("quick_ratio", 0)) if pd.notna(row.get("quick_ratio")) else None,
                    cash_ratio=float(row.get("cash_ratio", 0)) if pd.notna(row.get("cash_ratio")) else None,
                    operating_cash_flow_ratio=None,
                    debt_to_equity=float(row.get("debt_to_eqt", 0)) if pd.notna(row.get("debt_to_eqt")) else None,
                    debt_to_assets=float(row.get("debt_to_assets", 0)) if pd.notna(row.get("debt_to_assets")) else None,
                    interest_coverage=None,
                    revenue_growth=float(row.get("q_sales_yoy", 0)) / 100 if pd.notna(row.get("q_sales_yoy")) else None,
                    earnings_growth=float(row.get("netprofit_yoy", 0)) / 100 if pd.notna(row.get("netprofit_yoy")) else None,
                    book_value_growth=None,
                    earnings_per_share_growth=float(row.get("basic_eps_yoy", 0)) / 100 if pd.notna(row.get("basic_eps_yoy")) else None,
                    free_cash_flow_growth=None,
                    operating_income_growth=float(row.get("op_yoy", 0)) / 100 if pd.notna(row.get("op_yoy")) else None,
                    ebitda_growth=None,
                    payout_ratio=None,
                    earnings_per_share=float(row.get("eps", 0)) if pd.notna(row.get("eps")) else None,
                    book_value_per_share=float(row.get("bps", 0)) if pd.notna(row.get("bps")) else None,
                    free_cash_flow_per_share=None,
                )
            )
        return metrics
    except Exception as e:
        print(f"[Tushare] 获取财务指标失败: {e}")
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
