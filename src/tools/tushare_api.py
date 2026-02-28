import os
from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd

from src.data.models import FinancialMetrics, LineItem, Price

_pro = None
_stock_name_cache: Dict[str, str] = {}


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
        df = pro.stock_basic(ts_code=ts_code, fields="ts_code,name")
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
        df = pro.daily(ts_code=ts_code, start_date=start_fmt, end_date=end_fmt)
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
        df = pro.daily(trade_date=trade_fmt, fields=fields)
        if df is None or df.empty:
            try:
                end_dt = datetime.strptime(trade_fmt, "%Y%m%d")
                start_dt = end_dt - timedelta(days=30)
                df_cal = pro.trade_cal(exchange="", start_date=start_dt.strftime("%Y%m%d"), end_date=trade_fmt, is_open=1, fields="cal_date,is_open")
                if df_cal is not None and not df_cal.empty:
                    last_open = str(df_cal.iloc[-1]["cal_date"])
                    df = pro.daily(trade_date=last_open, fields=fields)
            except Exception:
                df = None
        if df is None or df.empty:
            return []
        missing_pct = pd.isna(df["pct_chg"])
        valid_pre_close = pd.notna(df["pre_close"]) & (df["pre_close"] != 0)
        df.loc[missing_pct & valid_pre_close, "pct_chg"] = (df.loc[missing_pct & valid_pre_close, "close"] - df.loc[missing_pct & valid_pre_close, "pre_close"]) / df.loc[missing_pct & valid_pre_close, "pre_close"] * 100
        df = df[pd.notna(df["pct_chg"])]
        df = df[df["pct_chg"] > pct_threshold]
        if df.empty:
            return []

        name_map = {}
        area_map: dict[str, str] = {}
        industry_map: dict[str, str] = {}
        market_map: dict[str, str] = {}
        list_date_map: dict[str, str] = {}
        st_codes: set[str] = set()
        if include_name:
            df_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,area,industry,market,list_date")
            if df_basic is not None and not df_basic.empty:
                name_map = {str(row["ts_code"]): str(row["name"]) for _, row in df_basic.iterrows()}
                st_codes = {str(row["ts_code"]) for _, row in df_basic.iterrows() if "ST" in str(row["name"]).upper()}
                area_map = {str(row["ts_code"]): str(row["area"]) for _, row in df_basic.iterrows() if pd.notna(row["area"])}
                industry_map = {str(row["ts_code"]): str(row["industry"]) for _, row in df_basic.iterrows() if pd.notna(row["industry"])}
                market_map = {str(row["ts_code"]): str(row["market"]) for _, row in df_basic.iterrows() if pd.notna(row["market"])}
                list_date_map = {str(row["ts_code"]): str(row["list_date"]) for _, row in df_basic.iterrows() if pd.notna(row["list_date"])}

        results = []
        df_sorted = df.sort_values("pct_chg", ascending=False)
        for _, row in df_sorted.iterrows():
            date_str = str(row["trade_date"])
            date_formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            ts_code = str(row["ts_code"])
            if ts_code in st_codes:
                continue
            item = {
                "ts_code": ts_code,
                "trade_date": date_formatted,
                "pct_chg": float(row["pct_chg"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "pre_close": float(row["pre_close"]) if "pre_close" in row and pd.notna(row["pre_close"]) else None,
                "vol": int(row["vol"]),
            }
            if "amount" in row and pd.notna(row["amount"]):
                item["amount"] = float(row["amount"])
            if include_name:
                item["name"] = name_map.get(ts_code, ts_code)
                item["area"] = area_map.get(ts_code)
                item["industry"] = industry_map.get(ts_code)
                item["market"] = market_map.get(ts_code)
                item["list_date"] = list_date_map.get(ts_code)
            results.append(item)
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


def _get_latest_total_mv(pro, ts_code: str, anchor_date: str, lookback_days: int = 30) -> float | None:
    """获取指定日期（含）之前最近一个交易日的总市值（元）。"""
    date_fmt = anchor_date.replace("-", "")

    try:
        df_exact = pro.daily_basic(ts_code=ts_code, trade_date=date_fmt)
        if df_exact is not None and not df_exact.empty:
            value = df_exact.iloc[0].get("total_mv", None)
            if value is not None and not pd.isna(value):
                return float(value) * 10000
    except Exception:
        pass

    try:
        date_obj = datetime.strptime(date_fmt, "%Y%m%d")
    except Exception:
        return None

    start_fmt = (date_obj - timedelta(days=lookback_days)).strftime("%Y%m%d")
    try:
        df_window = pro.daily_basic(ts_code=ts_code, start_date=start_fmt, end_date=date_fmt)
        if df_window is None or df_window.empty or "total_mv" not in df_window.columns:
            return None

        valid = df_window[df_window["total_mv"].notna()]
        if valid.empty:
            return None

        if "trade_date" in valid.columns:
            valid = valid.sort_values("trade_date", ascending=False)

        return float(valid.iloc[0]["total_mv"]) * 10000
    except Exception:
        return None


def get_ashare_financial_metrics_with_tushare(ticker: str, end_date: str, limit: int = 10) -> List[FinancialMetrics]:
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
            market_cap = _get_latest_total_mv(pro, ts_code, end_date_str)

            pe_ratio = float(row.get("pe", 0)) if pd.notna(row.get("pe")) and row.get("pe") != 0 else None
            pb_ratio = float(row.get("pb", 0)) if pd.notna(row.get("pb")) and row.get("pb") != 0 else None
            ps_ratio_val = float(row.get("ps", 0)) if pd.notna(row.get("ps")) and row.get("ps") != 0 else None
            peg_ratio_val = None
            if pe_ratio and pe_ratio > 0:
                earnings_growth = float(row.get("netprofit_yoy", 0)) / 100 if pd.notna(row.get("netprofit_yoy")) else None
                if earnings_growth and earnings_growth > 0:
                    peg_ratio_val = pe_ratio / (earnings_growth * 100)

            metrics.append(
                FinancialMetrics(
                    ticker=ticker,
                    report_period=end_date_str,
                    period="ttm",
                    currency="CNY",
                    market_cap=market_cap,
                    enterprise_value=None,
                    price_to_earnings_ratio=pe_ratio,
                    price_to_book_ratio=pb_ratio,
                    price_to_sales_ratio=ps_ratio_val,
                    enterprise_value_to_ebitda_ratio=None,
                    enterprise_value_to_revenue_ratio=None,
                    free_cash_flow_yield=None,
                    peg_ratio=peg_ratio_val,
                    gross_margin=_validate_margin(float(row.get("grossprofit_margin", 0)) / 100 if pd.notna(row.get("grossprofit_margin")) else None),
                    operating_margin=_validate_margin(float(row.get("op_of_gr", 0)) / 100 if pd.notna(row.get("op_of_gr")) else None),
                    net_margin=_validate_margin(float(row.get("netprofit_margin", 0)) / 100 if pd.notna(row.get("netprofit_margin")) else None),
                    return_on_equity=_validate_roe(float(row.get("roe", 0)) / 100 if pd.notna(row.get("roe")) else None),
                    return_on_assets=_validate_roe(float(row.get("roa", 0)) / 100 if pd.notna(row.get("roa")) else None),
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
                    debt_to_assets=float(row.get("debt_to_assets", 0)) / 100 if pd.notna(row.get("debt_to_assets")) else None,
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


def get_ashare_market_cap_with_tushare(ticker: str, end_date: str) -> float | None:
    """
    使用 Tushare 获取 A 股市值
    """
    pro = _get_pro()
    if not pro:
        return None
    try:
        ts_code = _to_ts_code(ticker)
        return _get_latest_total_mv(pro, ts_code, end_date)
    except Exception:
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

        # 获取财务指标数据
        df_fin = pro.fina_indicator(ts_code=ts_code, limit=limit)
        if df_fin is None or df_fin.empty:
            return []

        # 获取资产负债表数据（用于补充字段）
        df_bal = pro.balancesheet(ts_code=ts_code, limit=limit)

        # 获取现金流量表数据
        df_cash = pro.cashflow(ts_code=ts_code, limit=limit)

        # 获取利润表数据
        df_income = pro.income(ts_code=ts_code, limit=limit)

        results = []
        for _, row in df_fin.iterrows():
            end_date_str = str(row.get("end_date", ""))

            # 构建 line item 数据
            item_data = {
                "ticker": ticker,
                "report_period": end_date_str,
                "period": period,
                "currency": "CNY",
            }

            # 映射 Tushare 字段到标准字段
            field_mapping = {}

            # 从 balancesheet 获取基础数据
            if df_bal is not None and not df_bal.empty:
                bal_row = df_bal[df_bal["end_date"] == end_date_str]
                if not bal_row.empty:
                    bal = bal_row.iloc[0]
                    field_mapping["total_assets"] = bal.get("total_assets")
                    field_mapping["total_liabilities"] = bal.get("total_liab")
                    field_mapping["shareholders_equity"] = bal.get("total_hldr_eqy_exc_min_int")
                    field_mapping["outstanding_shares"] = bal.get("total_share")

            # 从 income 获取利润数据
            if df_income is not None and not df_income.empty:
                inc_row = df_income[df_income["end_date"] == end_date_str]
                if not inc_row.empty:
                    inc = inc_row.iloc[0]
                    field_mapping["revenue"] = inc.get("total_revenue")
                    field_mapping["net_income"] = inc.get("n_income_attr_p")
                    field_mapping["gross_profit"] = inc.get("total_profit")

            # 从 cashflow 获取现金流数据
            if df_cash is not None and not df_cash.empty:
                cash_row = df_cash[df_cash["end_date"] == end_date_str]
                if not cash_row.empty:
                    cash = cash_row.iloc[0]
                    # 自由现金流 (Tushare 已计算好)
                    field_mapping["free_cash_flow"] = cash.get("free_cashflow")
                    # 资本支出 (购建固定资产等支付的现金)
                    field_mapping["capital_expenditure"] = cash.get("c_pay_acq_const_fiolta")
                    # 折旧摊销
                    field_mapping["depreciation_and_amortization"] = cash.get("depr_fa_coga_dpba")
                    # 股息支付
                    field_mapping["dividends_and_other_cash_distributions"] = cash.get("c_pay_dist_dpcp_int_exp")
                    # 股权融资/回购
                    field_mapping["issuance_or_purchase_of_equity_shares"] = cash.get("c_recp_cap_contrib")

            # 从 fina_indicator 补充数据（如果上面没有获取到）
            if "net_income" not in field_mapping or field_mapping["net_income"] is None:
                field_mapping["net_income"] = row.get("profit_dedt")
            if "total_assets" not in field_mapping or field_mapping["total_assets"] is None:
                field_mapping["total_assets"] = row.get("total_assets")
            if "total_liabilities" not in field_mapping or field_mapping["total_liabilities"] is None:
                field_mapping["total_liabilities"] = row.get("total_liabilities")
            if "shareholders_equity" not in field_mapping or field_mapping["shareholders_equity"] is None:
                field_mapping["shareholders_equity"] = row.get("total_hldr_eqy_exc_min_int")
            if "outstanding_shares" not in field_mapping or field_mapping["outstanding_shares"] is None:
                field_mapping["outstanding_shares"] = row.get("total_share")

            # 只添加请求的字段
            for field in line_items:
                if field in field_mapping and field_mapping[field] is not None:
                    value = field_mapping[field]
                    # 处理 NaN 值
                    if isinstance(value, float) and pd.isna(value):
                        continue
                    try:
                        item_data[field] = float(value)
                    except (ValueError, TypeError):
                        item_data[field] = value

            results.append(LineItem(**item_data))

        return results
    except Exception as e:
        print(f"[Tushare] 获取财务项目失败: {e}")
        import traceback

        traceback.print_exc()
        return []
