from typing import List

import pandas as pd

from src.data.models import LineItem


TTM_FLOW_FIELDS = {
    "revenue",
    "net_income",
    "gross_profit",
    "total_profit",
    "operating_income",
    "interest_expense",
    "research_and_development",
    "ebit",
    "operating_cash_flow",
    "free_cash_flow",
    "capital_expenditure",
    "depreciation_and_amortization",
    "dividends_and_other_cash_distributions",
    "issuance_or_purchase_of_equity_shares",
}


def fetch_line_item_statement_frames(fetch_call, pro, ts_code: str, fetch_limit: int) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    try:
        df_fin = fetch_call(pro, "fina_indicator", ts_code, fetch_limit, dedupe=True)
    except Exception as e:
        print(f"[Tushare] 获取财务指标失败: {e}")
        df_fin = None

    df_bal = _fetch_optional_frame(fetch_call, pro, "balancesheet", ts_code, fetch_limit, "资产负债表")
    df_cash = _fetch_optional_frame(fetch_call, pro, "cashflow", ts_code, fetch_limit, "现金流量表")
    df_income = _fetch_optional_frame(fetch_call, pro, "income", ts_code, fetch_limit, "利润表")
    return df_fin, df_bal, df_cash, df_income


def _fetch_optional_frame(fetch_call, pro, api_name: str, ts_code: str, fetch_limit: int, label: str) -> pd.DataFrame | None:
    try:
        return fetch_call(pro, api_name, ts_code, fetch_limit, dedupe=True)
    except Exception as e:
        print(f"[Tushare] 获取{label}失败(非致命): {e}")
        return None


def should_include_period(end_date_str: str, period: str) -> bool:
    if period == "annual":
        return end_date_str.endswith("1231")
    if period == "quarterly":
        return not end_date_str.endswith("1231")
    return True


def build_period_item_data(
    *,
    ticker: str,
    period: str,
    end_date_str: str,
    row,
    line_items: List[str],
    df_bal: pd.DataFrame | None,
    df_cash: pd.DataFrame | None,
    df_income: pd.DataFrame | None,
) -> tuple[dict, dict]:
    item_data = {"ticker": ticker, "report_period": end_date_str, "period": period, "currency": "CNY"}
    field_mapping: dict = {}
    _populate_balance_fields(field_mapping, end_date_str, df_bal)
    _populate_income_fields(field_mapping, end_date_str, row, df_income)
    _populate_cashflow_fields(field_mapping, end_date_str, df_cash)
    _populate_fina_indicator_fields(field_mapping, row)
    _append_requested_fields(item_data, field_mapping, line_items)
    return item_data, field_mapping


def _populate_balance_fields(field_mapping: dict, end_date_str: str, df_bal: pd.DataFrame | None) -> None:
    if df_bal is None or df_bal.empty:
        return
    bal_row = df_bal[df_bal["end_date"] == end_date_str]
    if bal_row.empty:
        return
    bal = bal_row.iloc[0]
    field_mapping["total_assets"] = bal.get("total_assets")
    field_mapping["total_liabilities"] = bal.get("total_liab")
    field_mapping["shareholders_equity"] = bal.get("total_hldr_eqy_exc_min_int")
    field_mapping["outstanding_shares"] = bal.get("total_share")
    lt_borr = _to_clean_float(bal.get("lt_borr", 0), default=0.0)
    st_borr = _to_clean_float(bal.get("st_borr", 0), default=0.0)
    bonds_payable = _to_clean_float(bal.get("bond_payable", 0), default=0.0)
    total_debt_val = lt_borr + st_borr + bonds_payable
    if total_debt_val > 0:
        field_mapping["total_debt"] = total_debt_val
    field_mapping["cash_and_equivalents"] = bal.get("money_cap")
    field_mapping["current_assets"] = bal.get("total_cur_assets")
    field_mapping["current_liabilities"] = bal.get("total_cur_liab")
    cur_assets = bal.get("total_cur_assets")
    cur_liab = bal.get("total_cur_liab")
    if _is_present(cur_assets) and _is_present(cur_liab):
        field_mapping["working_capital"] = float(cur_assets) - float(cur_liab)
    goodwill_val = _to_clean_float(bal.get("goodwill", 0), default=0.0)
    intan_val = _to_clean_float(bal.get("intan_assets", 0), default=0.0)
    if goodwill_val > 0 or intan_val > 0:
        field_mapping["goodwill_and_intangible_assets"] = goodwill_val + intan_val


def _populate_income_fields(field_mapping: dict, end_date_str: str, row, df_income: pd.DataFrame | None) -> None:
    if df_income is None or df_income.empty:
        return
    inc_row = df_income[df_income["end_date"] == end_date_str]
    if inc_row.empty:
        return
    inc = inc_row.iloc[0]
    _set_income_core_fields(field_mapping, inc)
    int_exp_val = _set_income_expense_fields(field_mapping, inc)
    _set_income_profitability_fields(field_mapping, row, inc, int_exp_val)


def _set_income_core_fields(field_mapping: dict, inc) -> None:
    field_mapping["revenue"] = inc.get("total_revenue")
    field_mapping["net_income"] = inc.get("n_income_attr_p")
    rev_val = inc.get("revenue")
    if rev_val is None or _is_nan(rev_val):
        rev_val = inc.get("total_revenue")
    oper_cost_val = inc.get("oper_cost")
    if _is_present(rev_val) and _is_present(oper_cost_val):
        field_mapping["gross_profit"] = float(rev_val) - float(oper_cost_val)
    field_mapping["total_profit"] = inc.get("total_profit")
    field_mapping["operating_income"] = inc.get("operate_profit")


def _set_income_expense_fields(field_mapping: dict, inc):
    int_exp_val = inc.get("fin_exp_int_exp") or inc.get("int_exp")
    if _is_present(int_exp_val):
        field_mapping["interest_expense"] = float(int_exp_val)
    rd_val = inc.get("rd_exp")
    if _is_present(rd_val):
        field_mapping["research_and_development"] = float(rd_val)
    return int_exp_val


def _set_income_profitability_fields(field_mapping: dict, row, inc, int_exp_val) -> None:
    op_inc = inc.get("operate_profit")
    if _is_present(op_inc):
        field_mapping["ebit"] = float(op_inc)
        if _is_present(int_exp_val):
            field_mapping["ebit"] = float(op_inc) + float(int_exp_val)
    total_rev = inc.get("total_revenue")
    if _is_present(op_inc) and _is_present(total_rev) and total_rev != 0:
        field_mapping["operating_margin"] = float(op_inc) / float(total_rev)
    if _is_present(total_rev) and _is_present(op_inc):
        field_mapping["operating_expense"] = float(total_rev) - float(op_inc)
    gpm = row.get("grossprofit_margin")
    if _is_present(gpm):
        field_mapping["gross_margin"] = float(gpm) / 100.0


def _populate_cashflow_fields(field_mapping: dict, end_date_str: str, df_cash: pd.DataFrame | None) -> None:
    if df_cash is None or df_cash.empty:
        return
    cash_row = df_cash[df_cash["end_date"] == end_date_str]
    if cash_row.empty:
        return
    cash = cash_row.iloc[0]
    field_mapping["operating_cash_flow"] = cash.get("n_cashflow_act")
    op_cf_raw = cash.get("n_cashflow_act")
    capex_raw = cash.get("c_pay_acq_const_fiolta")
    if _is_present(op_cf_raw) and _is_present(capex_raw):
        field_mapping["free_cash_flow"] = float(op_cf_raw) - float(capex_raw)
    else:
        fcf_raw = cash.get("free_cashflow")
        if _is_present(fcf_raw):
            field_mapping["free_cash_flow"] = fcf_raw
    field_mapping["capital_expenditure"] = cash.get("c_pay_acq_const_fiolta")
    depr_raw = cash.get("depr_fa_coga_dpba")
    if _is_present(depr_raw):
        field_mapping["depreciation_and_amortization"] = float(depr_raw)
    field_mapping["dividends_and_other_cash_distributions"] = cash.get("c_pay_dist_dpcp_int_exp")
    field_mapping["issuance_or_purchase_of_equity_shares"] = cash.get("c_recp_cap_contrib")
    depr_val = field_mapping.get("depreciation_and_amortization")
    if "ebit" in field_mapping:
        field_mapping["ebitda"] = field_mapping["ebit"] + float(depr_val) if depr_val is not None else field_mapping["ebit"]


def _populate_fina_indicator_fields(field_mapping: dict, row) -> None:
    _backfill_balance_defaults(field_mapping, row)
    _backfill_per_share_defaults(field_mapping, row)
    dte_val = row.get("debt_to_eqt")
    if _is_present(dte_val):
        field_mapping["debt_to_equity"] = float(dte_val)
    if field_mapping.get("operating_margin") is None:
        om_val = row.get("op_of_gr")
        if _is_present(om_val):
            field_mapping["operating_margin"] = float(om_val) / 100.0
    _backfill_roic(field_mapping)


def _backfill_balance_defaults(field_mapping: dict, row) -> None:
    if field_mapping.get("net_income") is None:
        field_mapping["net_income"] = row.get("profit_dedt")
    if field_mapping.get("total_assets") is None:
        field_mapping["total_assets"] = row.get("total_assets")
    if field_mapping.get("total_liabilities") is None:
        field_mapping["total_liabilities"] = row.get("total_liabilities")
    if field_mapping.get("shareholders_equity") is None:
        field_mapping["shareholders_equity"] = row.get("total_hldr_eqy_exc_min_int")
    if field_mapping.get("outstanding_shares") is None:
        field_mapping["outstanding_shares"] = row.get("total_share")


def _backfill_per_share_defaults(field_mapping: dict, row) -> None:
    if field_mapping.get("earnings_per_share") is None:
        eps_val = row.get("eps") or row.get("basic_eps")
        if _is_present(eps_val):
            field_mapping["earnings_per_share"] = eps_val
    if field_mapping.get("book_value_per_share") is None:
        bps_val = row.get("bps")
        if _is_present(bps_val):
            field_mapping["book_value_per_share"] = bps_val


def _backfill_roic(field_mapping: dict) -> None:
    if field_mapping.get("return_on_invested_capital") is None:
        op_inc = field_mapping.get("operating_income")
        total_assets_val = field_mapping.get("total_assets")
        cur_liab_val = field_mapping.get("current_liabilities")
        if op_inc is not None and total_assets_val is not None and cur_liab_val is not None:
            try:
                invested_capital = float(total_assets_val) - float(cur_liab_val)
                if invested_capital > 0:
                    nopat = float(op_inc) * 0.75
                    field_mapping["return_on_invested_capital"] = nopat / invested_capital
            except (ValueError, TypeError):
                pass


def _append_requested_fields(item_data: dict, field_mapping: dict, line_items: List[str]) -> None:
    for field in line_items:
        if field not in field_mapping or field_mapping[field] is None:
            continue
        value = field_mapping[field]
        if isinstance(value, float) and pd.isna(value):
            continue
        try:
            item_data[field] = float(value)
        except (ValueError, TypeError):
            item_data[field] = value


def build_line_items_from_frames(
    *,
    ticker: str,
    line_items: List[str],
    period: str,
    limit: int,
    df_fin: pd.DataFrame,
    df_bal: pd.DataFrame | None,
    df_cash: pd.DataFrame | None,
    df_income: pd.DataFrame | None,
) -> List[LineItem]:
    results: list[LineItem] = []
    all_period_data: dict = {}
    for _, row in df_fin.iterrows():
        end_date_str = str(row.get("end_date", ""))
        if not should_include_period(end_date_str, period):
            continue
        item_data, field_mapping = build_period_item_data(
            ticker=ticker,
            period=period,
            end_date_str=end_date_str,
            row=row,
            line_items=line_items,
            df_bal=df_bal,
            df_cash=df_cash,
            df_income=df_income,
        )
        if period == "ttm":
            all_period_data[end_date_str] = (item_data, field_mapping)
        else:
            results.append(LineItem(**item_data))
            if len(results) >= limit:
                break
    if period == "ttm" and all_period_data:
        results.extend(_build_ttm_results(ticker, line_items, limit, all_period_data))
    return results


def _build_ttm_results(ticker: str, line_items: List[str], limit: int, all_period_data: dict) -> list[LineItem]:
    results: list[LineItem] = []
    sorted_periods = sorted(all_period_data.keys(), reverse=True)
    latest_period = sorted_periods[0] if sorted_periods else None
    if not latest_period:
        return results
    if latest_period.endswith("1231"):
        results.append(_build_annual_ttm_item(all_period_data, latest_period))
    else:
        results.append(_build_non_annual_ttm_item(ticker, latest_period, line_items, all_period_data))
    results.extend(_build_historical_ttm_items(sorted_periods, latest_period, limit, all_period_data))
    return results


def _build_annual_ttm_item(all_period_data: dict, latest_period: str) -> LineItem:
    latest_item_data, _ = all_period_data[latest_period]
    latest_item_data["period"] = "ttm"
    return LineItem(**latest_item_data)


def _build_non_annual_ttm_item(ticker: str, latest_period: str, line_items: List[str], all_period_data: dict) -> LineItem:
    latest_item_data, latest_fm = all_period_data[latest_period]
    prior_year = str(int(latest_period[:4]) - 1)
    prior_annual_data = all_period_data.get(f"{prior_year}1231")
    prior_same_data = all_period_data.get(f"{prior_year}{latest_period[4:]}")
    if not (prior_annual_data and prior_same_data):
        latest_item_data["period"] = "ttm"
        return LineItem(**latest_item_data)
    _, prior_annual_fm = prior_annual_data
    _, prior_same_fm = prior_same_data
    ttm_item_data = {"ticker": ticker, "report_period": latest_period, "period": "ttm", "currency": "CNY"}
    for field in line_items:
        _populate_ttm_field(ttm_item_data, field, latest_fm, prior_annual_fm, prior_same_fm)
    _recalculate_ttm_metrics(ttm_item_data)
    return LineItem(**ttm_item_data)


def _populate_ttm_field(ttm_item_data: dict, field: str, latest_fm: dict, prior_annual_fm: dict, prior_same_fm: dict) -> None:
    if field in TTM_FLOW_FIELDS:
        _populate_ttm_flow_field(ttm_item_data, field, latest_fm, prior_annual_fm, prior_same_fm)
        return
    val = latest_fm.get(field)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return
    try:
        ttm_item_data[field] = float(val)
    except (ValueError, TypeError):
        ttm_item_data[field] = val


def _populate_ttm_flow_field(ttm_item_data: dict, field: str, latest_fm: dict, prior_annual_fm: dict, prior_same_fm: dict) -> None:
    curr_val = latest_fm.get(field)
    annual_val = prior_annual_fm.get(field)
    same_val = prior_same_fm.get(field)
    if curr_val is None or annual_val is None or same_val is None:
        return
    try:
        c = _normalized_numeric(curr_val)
        a = _normalized_numeric(annual_val)
        s = _normalized_numeric(same_val)
        if c is not None and a is not None and s is not None:
            ttm_item_data[field] = c + a - s
    except (ValueError, TypeError):
        return


def _build_historical_ttm_items(sorted_periods: list[str], latest_period: str, limit: int, all_period_data: dict) -> list[LineItem]:
    results: list[LineItem] = []
    for period_key in sorted_periods:
        if not period_key.endswith("1231") or period_key == latest_period:
            continue
        hist_item_data, _ = all_period_data[period_key]
        hist_item_data["period"] = "ttm"
        results.append(LineItem(**hist_item_data))
        if len(results) >= limit:
            break
    return results


def _recalculate_ttm_metrics(ttm_item_data: dict) -> None:
    ttm_rev = ttm_item_data.get("revenue")
    ttm_op_inc = ttm_item_data.get("operating_income")
    if ttm_rev and ttm_op_inc and ttm_rev != 0:
        ttm_item_data["operating_margin"] = ttm_op_inc / ttm_rev
    ttm_ebit = ttm_item_data.get("ebit")
    ttm_depr = ttm_item_data.get("depreciation_and_amortization")
    if ttm_ebit is not None and ttm_depr is not None:
        ttm_item_data["ebitda"] = ttm_ebit + ttm_depr
    elif ttm_ebit is not None:
        ttm_item_data["ebitda"] = ttm_ebit
    if ttm_op_inc is not None:
        ttm_total_assets = ttm_item_data.get("total_assets")
        ttm_cur_liab = ttm_item_data.get("current_liabilities")
        if ttm_total_assets is not None and ttm_cur_liab is not None:
            try:
                invested_capital = float(ttm_total_assets) - float(ttm_cur_liab)
                if invested_capital > 0:
                    ttm_item_data["return_on_invested_capital"] = (ttm_op_inc * 0.75) / invested_capital
            except (ValueError, TypeError):
                pass


def _normalized_numeric(value):
    if isinstance(value, float) and pd.isna(value):
        return None
    return float(value)


def _to_clean_float(value, default=None):
    if value is None:
        return default
    if isinstance(value, float) and pd.isna(value):
        return default
    return float(value)


def _is_nan(value) -> bool:
    return isinstance(value, float) and pd.isna(value)


def _is_present(value) -> bool:
    return value is not None and not _is_nan(value)
