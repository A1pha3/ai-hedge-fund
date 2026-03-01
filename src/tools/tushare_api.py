import os
from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd

from src.data.models import FinancialMetrics, InsiderTrade, LineItem, Price

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


def _get_latest_daily_basic(pro, ts_code: str, anchor_date: str, lookback_days: int = 30) -> dict | None:
    """获取指定日期（含）之前最近一个交易日的 daily_basic 数据行。

    返回包含 total_mv, pe, pe_ttm, pb, ps, ps_ttm 等字段的 dict，
    如果找不到数据则返回 None。
    """
    date_fmt = anchor_date.replace("-", "")

    try:
        df_exact = pro.daily_basic(ts_code=ts_code, trade_date=date_fmt)
        if df_exact is not None and not df_exact.empty:
            return df_exact.iloc[0].to_dict()
    except Exception:
        pass

    try:
        date_obj = datetime.strptime(date_fmt, "%Y%m%d")
    except Exception:
        return None

    start_fmt = (date_obj - timedelta(days=lookback_days)).strftime("%Y%m%d")
    try:
        df_window = pro.daily_basic(ts_code=ts_code, start_date=start_fmt, end_date=date_fmt)
        if df_window is None or df_window.empty:
            return None

        if "trade_date" in df_window.columns:
            df_window = df_window.sort_values("trade_date", ascending=False)

        return df_window.iloc[0].to_dict()
    except Exception:
        return None


def _get_latest_total_mv(pro, ts_code: str, anchor_date: str, lookback_days: int = 30) -> float | None:
    """获取指定日期（含）之前最近一个交易日的总市值（元）。"""
    row = _get_latest_daily_basic(pro, ts_code, anchor_date, lookback_days)
    if row is None:
        return None
    value = row.get("total_mv", None)
    if value is not None and not pd.isna(value):
        return float(value) * 10000
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

        # 获取现金流量表数据以补充 FCF 字段
        df_cash = None
        try:
            df_cash = pro.cashflow(ts_code=ts_code, limit=limit)
        except Exception:
            pass

        # 获取总股本用于计算 free_cash_flow_per_share
        df_bal = None
        try:
            df_bal = pro.balancesheet(ts_code=ts_code, limit=limit)
        except Exception:
            pass

        # 获取利润表数据（用于计算 EBITDA、interest_coverage 等）
        df_income = None
        try:
            df_income = pro.income(ts_code=ts_code, limit=limit)
        except Exception:
            pass

        metrics = []
        # 预计算 FCF growth 所需的 FCF 值列表
        fcf_values = []
        if df_cash is not None and not df_cash.empty:
            for _, row in df_fin.iterrows():
                end_date_str = str(row.get("end_date", ""))
                cash_row = df_cash[df_cash["end_date"] == end_date_str]
                if not cash_row.empty:
                    fcf_val = cash_row.iloc[0].get("free_cashflow")
                    if fcf_val is not None and not (isinstance(fcf_val, float) and pd.isna(fcf_val)):
                        fcf_values.append(float(fcf_val))
                    else:
                        fcf_values.append(None)
                else:
                    fcf_values.append(None)

        for idx, (_, row) in enumerate(df_fin.iterrows()):
            # 从 daily_basic 获取市值和估值数据（pe/pb/ps 仅存在于 daily_basic，不在 fina_indicator 中）
            end_date_str = str(row.get("end_date", ""))
            daily_data = _get_latest_daily_basic(pro, ts_code, end_date_str)
            market_cap = None
            pe_ratio = None
            pb_ratio = None
            ps_ratio_val = None
            if daily_data:
                mv = daily_data.get("total_mv")
                if mv is not None and not pd.isna(mv):
                    market_cap = float(mv) * 10000
                pe_val = daily_data.get("pe_ttm") or daily_data.get("pe")
                if pe_val is not None and not pd.isna(pe_val) and float(pe_val) != 0:
                    pe_ratio = float(pe_val)
                pb_val = daily_data.get("pb")
                if pb_val is not None and not pd.isna(pb_val) and float(pb_val) != 0:
                    pb_ratio = float(pb_val)
                ps_val = daily_data.get("ps_ttm") or daily_data.get("ps")
                if ps_val is not None and not pd.isna(ps_val) and float(ps_val) != 0:
                    ps_ratio_val = float(ps_val)

            peg_ratio_val = None
            if pe_ratio and pe_ratio > 0:
                earnings_growth = float(row.get("netprofit_yoy", 0)) / 100 if pd.notna(row.get("netprofit_yoy")) else None
                if earnings_growth and earnings_growth > 0:
                    peg_ratio_val = pe_ratio / (earnings_growth * 100)

            # 计算 enterprise_value, EV/EBITDA, EV/Revenue, interest_coverage
            ev_val = None
            ev_to_ebitda_val = None
            ev_to_revenue_val = None
            interest_coverage_val = None
            if market_cap and df_bal is not None and not df_bal.empty:
                bal_row = df_bal[df_bal["end_date"] == end_date_str]
                if not bal_row.empty:
                    bal = bal_row.iloc[0]
                    lt_borr = bal.get("lt_borr", 0) or 0
                    st_borr = bal.get("st_borr", 0) or 0
                    bonds_payable = bal.get("bond_payable", 0) or 0
                    # Handle NaN values
                    lt_borr = 0 if (isinstance(lt_borr, float) and pd.isna(lt_borr)) else float(lt_borr)
                    st_borr = 0 if (isinstance(st_borr, float) and pd.isna(st_borr)) else float(st_borr)
                    bonds_payable = 0 if (isinstance(bonds_payable, float) and pd.isna(bonds_payable)) else float(bonds_payable)
                    total_debt = lt_borr + st_borr + bonds_payable
                    cash_eq = bal.get("money_cap", 0) or 0
                    cash_eq = 0 if (isinstance(cash_eq, float) and pd.isna(cash_eq)) else float(cash_eq)
                    ev_val = market_cap + total_debt - cash_eq
                    if ev_val < 0:
                        ev_val = market_cap  # EV should not be negative; fallback to market cap

            # 计算 EBITDA 和 EV/EBITDA
            if ev_val and df_income is not None and not df_income.empty:
                inc_row = df_income[df_income["end_date"] == end_date_str]
                if not inc_row.empty:
                    inc = inc_row.iloc[0]
                    op_profit = inc.get("operate_profit")
                    # 利息支出: 优先使用 fin_exp_int_exp，回退到 int_exp
                    int_exp = inc.get("fin_exp_int_exp") or inc.get("int_exp", 0) or 0
                    int_exp = 0 if (isinstance(int_exp, float) and pd.isna(int_exp)) else float(int_exp)
                    # 财务费用 (含利息支出、汇兑损益等)
                    fin_exp = inc.get("fin_exp", 0) or 0
                    fin_exp = 0 if (isinstance(fin_exp, float) and pd.isna(fin_exp)) else float(fin_exp)
                    total_revenue = inc.get("total_revenue")
                    # 中国会计准则: 营业利润已扣除财务费用(含利息)
                    # EBITDA = 营业利润 + 财务费用 + 折旧摊销
                    # EBIT = 营业利润 + 财务费用
                    depr_val = 0
                    if df_cash is not None and not df_cash.empty:
                        cash_row = df_cash[df_cash["end_date"] == end_date_str]
                        if not cash_row.empty:
                            dv = cash_row.iloc[0].get("depr_fa_coga_dpba", 0) or 0
                            depr_val = 0 if (isinstance(dv, float) and pd.isna(dv)) else float(dv)
                    if op_profit is not None and not (isinstance(op_profit, float) and pd.isna(op_profit)):
                        ebit = float(op_profit) + fin_exp
                        ebitda = ebit + depr_val
                        if ebitda > 0:
                            ev_to_ebitda_val = ev_val / ebitda
                        elif ebit > 0:
                            # EBITDA 为负但 EBIT 为正时，使用 EBIT 作为保守估计
                            ev_to_ebitda_val = ev_val / ebit
                    # EV/Revenue
                    if total_revenue is not None and not (isinstance(total_revenue, float) and pd.isna(total_revenue)) and float(total_revenue) > 0:
                        ev_to_revenue_val = ev_val / float(total_revenue)
                    # Interest coverage = EBIT / interest_expense
                    if op_profit is not None and not (isinstance(op_profit, float) and pd.isna(op_profit)) and int_exp > 0:
                        ebit_for_ic = float(op_profit) + fin_exp
                        interest_coverage_val = ebit_for_ic / int_exp

            # 从现金流量表获取 FCF 相关数据
            fcf_yield_val = None
            fcf_growth_val = None
            fcf_per_share_val = None
            if fcf_values and idx < len(fcf_values) and fcf_values[idx] is not None:
                current_fcf = fcf_values[idx]
                # FCF yield = FCF / Market Cap
                if market_cap and market_cap > 0:
                    fcf_yield_val = current_fcf / market_cap
                # FCF per share = FCF / outstanding shares
                if df_bal is not None and not df_bal.empty:
                    bal_row = df_bal[df_bal["end_date"] == end_date_str]
                    if not bal_row.empty:
                        shares = bal_row.iloc[0].get("total_share")
                        if shares is not None and not (isinstance(shares, float) and pd.isna(shares)) and float(shares) > 0:
                            fcf_per_share_val = current_fcf / float(shares)
                # FCF growth: compare with next period (older)
                if idx + 1 < len(fcf_values) and fcf_values[idx + 1] is not None and abs(fcf_values[idx + 1]) > 1e-9:
                    fcf_growth_val = (current_fcf - fcf_values[idx + 1]) / abs(fcf_values[idx + 1])

            # 计算 ROIC = NOPAT / Invested Capital
            # NOPAT = operating_income * (1 - tax_rate), tax_rate 默认 25% (中国企业所得税)
            # Invested Capital = total_assets - current_liabilities
            roic_val = None
            if df_income is not None and not df_income.empty and df_bal is not None and not df_bal.empty:
                inc_row = df_income[df_income["end_date"] == end_date_str]
                bal_row = df_bal[df_bal["end_date"] == end_date_str]
                if not inc_row.empty and not bal_row.empty:
                    op_profit = inc_row.iloc[0].get("operate_profit")
                    total_assets = bal_row.iloc[0].get("total_assets")
                    cur_liab = bal_row.iloc[0].get("total_cur_liab")
                    if op_profit is not None and total_assets is not None and cur_liab is not None:
                        if not any(isinstance(v, float) and pd.isna(v) for v in [op_profit, total_assets, cur_liab]):
                            invested_capital = float(total_assets) - float(cur_liab)
                            if invested_capital > 0:
                                nopat = float(op_profit) * 0.75  # 25% 企业所得税
                                roic_val = nopat / invested_capital

            # 计算 book_value_growth (从相邻两期 bps 计算)
            bvg_val = None
            bps_current = row.get("bps")
            if bps_current is not None and pd.notna(bps_current) and float(bps_current) > 0:
                if idx + 1 < len(df_fin):
                    bps_prev = df_fin.iloc[idx + 1].get("bps")
                    if bps_prev is not None and pd.notna(bps_prev) and float(bps_prev) > 0:
                        bvg_val = (float(bps_current) - float(bps_prev)) / float(bps_prev)

            metrics.append(
                FinancialMetrics(
                    ticker=ticker,
                    report_period=end_date_str,
                    period="ttm",
                    currency="CNY",
                    market_cap=market_cap,
                    enterprise_value=ev_val,
                    price_to_earnings_ratio=pe_ratio,
                    price_to_book_ratio=pb_ratio,
                    price_to_sales_ratio=ps_ratio_val,
                    enterprise_value_to_ebitda_ratio=ev_to_ebitda_val,
                    enterprise_value_to_revenue_ratio=ev_to_revenue_val,
                    free_cash_flow_yield=fcf_yield_val,
                    peg_ratio=peg_ratio_val,
                    gross_margin=_validate_margin(float(row.get("grossprofit_margin", 0)) / 100 if pd.notna(row.get("grossprofit_margin")) else None),
                    operating_margin=_validate_margin(float(row.get("op_of_gr", 0)) / 100 if pd.notna(row.get("op_of_gr")) else None),
                    net_margin=_validate_margin(float(row.get("netprofit_margin", 0)) / 100 if pd.notna(row.get("netprofit_margin")) else None),
                    return_on_equity=_validate_roe(float(row.get("roe", 0)) / 100 if pd.notna(row.get("roe")) else None),
                    return_on_assets=_validate_roe(float(row.get("roa", 0)) / 100 if pd.notna(row.get("roa")) else None),
                    return_on_invested_capital=roic_val,
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
                    interest_coverage=interest_coverage_val,
                    revenue_growth=float(row.get("q_sales_yoy", 0)) / 100 if pd.notna(row.get("q_sales_yoy")) else None,
                    earnings_growth=float(row.get("netprofit_yoy", 0)) / 100 if pd.notna(row.get("netprofit_yoy")) else None,
                    book_value_growth=bvg_val,
                    earnings_per_share_growth=float(row.get("basic_eps_yoy", 0)) / 100 if pd.notna(row.get("basic_eps_yoy")) else None,
                    free_cash_flow_growth=fcf_growth_val,
                    operating_income_growth=float(row.get("op_yoy", 0)) / 100 if pd.notna(row.get("op_yoy")) else None,
                    ebitda_growth=None,
                    payout_ratio=None,
                    earnings_per_share=float(row.get("eps", 0)) if pd.notna(row.get("eps")) else None,
                    book_value_per_share=float(row.get("bps", 0)) if pd.notna(row.get("bps")) else None,
                    free_cash_flow_per_share=fcf_per_share_val,
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
                    # 补充资产负债表字段（投资者代理需要）
                    lt_borr = bal.get("lt_borr", 0) or 0
                    st_borr = bal.get("st_borr", 0) or 0
                    bonds_payable = bal.get("bond_payable", 0) or 0
                    lt_borr = 0 if (isinstance(lt_borr, float) and pd.isna(lt_borr)) else float(lt_borr)
                    st_borr = 0 if (isinstance(st_borr, float) and pd.isna(st_borr)) else float(st_borr)
                    bonds_payable = 0 if (isinstance(bonds_payable, float) and pd.isna(bonds_payable)) else float(bonds_payable)
                    total_debt_val = lt_borr + st_borr + bonds_payable
                    if total_debt_val > 0:
                        field_mapping["total_debt"] = total_debt_val
                    field_mapping["cash_and_equivalents"] = bal.get("money_cap")
                    field_mapping["current_assets"] = bal.get("total_cur_assets")
                    field_mapping["current_liabilities"] = bal.get("total_cur_liab")
                    # 计算 working_capital = current_assets - current_liabilities
                    cur_assets = bal.get("total_cur_assets")
                    cur_liab = bal.get("total_cur_liab")
                    if cur_assets is not None and cur_liab is not None and not (isinstance(cur_assets, float) and pd.isna(cur_assets)) and not (isinstance(cur_liab, float) and pd.isna(cur_liab)):
                        field_mapping["working_capital"] = float(cur_assets) - float(cur_liab)
                    # 商誉和无形资产
                    goodwill_val = bal.get("goodwill", 0) or 0
                    intan_val = bal.get("intan_assets", 0) or 0
                    goodwill_val = 0 if (isinstance(goodwill_val, float) and pd.isna(goodwill_val)) else float(goodwill_val)
                    intan_val = 0 if (isinstance(intan_val, float) and pd.isna(intan_val)) else float(intan_val)
                    if goodwill_val > 0 or intan_val > 0:
                        field_mapping["goodwill_and_intangible_assets"] = goodwill_val + intan_val

            # 从 income 获取利润数据
            if df_income is not None and not df_income.empty:
                inc_row = df_income[df_income["end_date"] == end_date_str]
                if not inc_row.empty:
                    inc = inc_row.iloc[0]
                    field_mapping["revenue"] = inc.get("total_revenue")
                    field_mapping["net_income"] = inc.get("n_income_attr_p")
                    field_mapping["gross_profit"] = inc.get("total_profit")
                    field_mapping["operating_income"] = inc.get("operate_profit")
                    # interest_expense (利息支出) - tushare 字段名为 fin_exp_int_exp
                    int_exp_val = inc.get("fin_exp_int_exp") or inc.get("int_exp")
                    if int_exp_val is not None and not (isinstance(int_exp_val, float) and pd.isna(int_exp_val)):
                        field_mapping["interest_expense"] = float(int_exp_val)
                    # research_and_development (研发费用)
                    rd_val = inc.get("rd_exp")
                    if rd_val is not None and not (isinstance(rd_val, float) and pd.isna(rd_val)):
                        field_mapping["research_and_development"] = float(rd_val)
                    # ebit = operating_income + interest_expense (近似)
                    op_inc = inc.get("operate_profit")
                    if op_inc is not None and not (isinstance(op_inc, float) and pd.isna(op_inc)):
                        field_mapping["ebit"] = float(op_inc)
                        if int_exp_val is not None and not (isinstance(int_exp_val, float) and pd.isna(int_exp_val)):
                            field_mapping["ebit"] = float(op_inc) + float(int_exp_val)
                    # 计算 operating_margin = operating_income / revenue
                    op_income = inc.get("operate_profit")
                    total_rev = inc.get("total_revenue")
                    if op_income is not None and total_rev is not None and not (isinstance(op_income, float) and pd.isna(op_income)) and not (isinstance(total_rev, float) and pd.isna(total_rev)) and total_rev != 0:
                        field_mapping["operating_margin"] = float(op_income) / float(total_rev)
                    # 计算 gross_margin (使用 fina_indicator 的 grossprofit_margin)
                    gpm = row.get("grossprofit_margin")
                    if gpm is not None and not (isinstance(gpm, float) and pd.isna(gpm)):
                        field_mapping["gross_margin"] = float(gpm) / 100.0

            # 从 cashflow 获取现金流数据
            if df_cash is not None and not df_cash.empty:
                cash_row = df_cash[df_cash["end_date"] == end_date_str]
                if not cash_row.empty:
                    cash = cash_row.iloc[0]
                    # 自由现金流 (Tushare 已计算好)
                    field_mapping["free_cash_flow"] = cash.get("free_cashflow")
                    # 资本支出 (购建固定资产等支付的现金)
                    field_mapping["capital_expenditure"] = cash.get("c_pay_acq_const_fiolta")
                    # 折旧摊销 - Q1/Q3季报无此字段，需回退到最近可用期
                    depr_raw = cash.get("depr_fa_coga_dpba")
                    if depr_raw is not None and not (isinstance(depr_raw, float) and pd.isna(depr_raw)):
                        field_mapping["depreciation_and_amortization"] = float(depr_raw)
                    else:
                        # Q1/Q3 季报无折旧数据，从历史期中查找最近的非空值
                        for _, hist_cash in df_cash.iterrows():
                            hist_depr = hist_cash.get("depr_fa_coga_dpba")
                            if hist_depr is not None and not (isinstance(hist_depr, float) and pd.isna(hist_depr)) and float(hist_depr) > 0:
                                field_mapping["depreciation_and_amortization"] = float(hist_depr)
                                break
                    # 股息支付
                    field_mapping["dividends_and_other_cash_distributions"] = cash.get("c_pay_dist_dpcp_int_exp")
                    # 股权融资/回购
                    field_mapping["issuance_or_purchase_of_equity_shares"] = cash.get("c_recp_cap_contrib")
                    # 计算 ebitda = ebit + depreciation_and_amortization
                    depr_val = field_mapping.get("depreciation_and_amortization")
                    if "ebit" in field_mapping:
                        if depr_val is not None:
                            field_mapping["ebitda"] = field_mapping["ebit"] + float(depr_val)
                        else:
                            # 折旧不可用时 EBITDA ≈ EBIT（保守估计）
                            field_mapping["ebitda"] = field_mapping["ebit"]

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
            # 补充 EPS 和其他 fina_indicator 字段
            # 注意: tushare fina_indicator 中 EPS 字段名为 "eps"，不是 "basic_eps"
            if "earnings_per_share" not in field_mapping or field_mapping["earnings_per_share"] is None:
                eps_val = row.get("eps") or row.get("basic_eps")
                if eps_val is not None and not (isinstance(eps_val, float) and pd.isna(eps_val)):
                    field_mapping["earnings_per_share"] = eps_val
            # 补充 book_value_per_share (来自 fina_indicator 的 bps 字段)
            if "book_value_per_share" not in field_mapping or field_mapping["book_value_per_share"] is None:
                bps_val = row.get("bps")
                if bps_val is not None and not (isinstance(bps_val, float) and pd.isna(bps_val)):
                    field_mapping["book_value_per_share"] = bps_val
            # 补充 debt_to_equity (来自 fina_indicator 的标准计算: total_liabilities / equity)
            dte_val = row.get("debt_to_eqt")
            if dte_val is not None and not (isinstance(dte_val, float) and pd.isna(dte_val)):
                field_mapping["debt_to_equity"] = float(dte_val)
            # 补充 operating_margin (如果从 income 表未计算到)
            if "operating_margin" not in field_mapping or field_mapping["operating_margin"] is None:
                om_val = row.get("op_of_gr")
                if om_val is not None and not (isinstance(om_val, float) and pd.isna(om_val)):
                    field_mapping["operating_margin"] = float(om_val) / 100.0

            # 计算 ROIC = NOPAT / Invested Capital (用于 Charlie Munger 等 Agent)
            if "return_on_invested_capital" not in field_mapping or field_mapping.get("return_on_invested_capital") is None:
                op_inc = field_mapping.get("operating_income")
                total_assets_val = field_mapping.get("total_assets")
                cur_liab_val = field_mapping.get("current_liabilities")
                if op_inc is not None and total_assets_val is not None and cur_liab_val is not None:
                    try:
                        invested_capital = float(total_assets_val) - float(cur_liab_val)
                        if invested_capital > 0:
                            nopat = float(op_inc) * 0.75  # 25% 企业所得税
                            field_mapping["return_on_invested_capital"] = nopat / invested_capital
                    except (ValueError, TypeError):
                        pass

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
        end_fmt = end_date.replace("-", "")

        # 使用 ann_date 范围查询
        kwargs = {"ts_code": ts_code, "end_date": end_fmt}
        if start_date:
            start_fmt = start_date.replace("-", "")
            kwargs["start_date"] = start_fmt

        df = pro.stk_holdertrade(**kwargs)
        if df is None or df.empty:
            return []

        # 按公告日期降序排序
        if "ann_date" in df.columns:
            df = df.sort_values("ann_date", ascending=False)

        trades = []
        for _, row in df.head(limit).iterrows():
            ann_date = str(row.get("ann_date", ""))
            # 格式化日期 YYYYMMDD -> YYYY-MM-DD
            filing_date = f"{ann_date[:4]}-{ann_date[4:6]}-{ann_date[6:8]}" if len(ann_date) == 8 else ann_date

            in_de = str(row.get("in_de", ""))
            change_vol = row.get("change_vol")
            avg_price = row.get("avg_price")
            after_share = row.get("after_share")
            holder_name = str(row.get("holder_name", ""))

            # 计算交易股数和交易价值
            shares = None
            tx_value = None
            if change_vol is not None and not (isinstance(change_vol, float) and pd.isna(change_vol)):
                shares = float(change_vol)
                # 增持为正, 减持为负
                if in_de == "DE" and shares > 0:
                    shares = -shares
                if avg_price is not None and not (isinstance(avg_price, float) and pd.isna(avg_price)):
                    tx_value = abs(shares) * float(avg_price)

            shares_after = None
            if after_share is not None and not (isinstance(after_share, float) and pd.isna(after_share)):
                shares_after = float(after_share)

            shares_before = None
            if shares_after is not None and shares is not None:
                shares_before = shares_after - shares

            tx_price = None
            if avg_price is not None and not (isinstance(avg_price, float) and pd.isna(avg_price)):
                tx_price = float(avg_price)

            trades.append(InsiderTrade(
                ticker=ticker,
                issuer=None,
                name=holder_name,
                title=str(row.get("holder_type", "")),  # C=公司, P=个人
                is_board_director=None,
                transaction_date=filing_date,
                transaction_shares=shares,
                transaction_price_per_share=tx_price,
                transaction_value=tx_value,
                shares_owned_before_transaction=shares_before,
                shares_owned_after_transaction=shares_after,
                security_title=None,
                filing_date=filing_date,
            ))

        return trades
    except Exception as e:
        print(f"[Tushare] 获取股东增减持数据失败: {e}")
        return []
