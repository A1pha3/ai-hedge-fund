from collections.abc import Callable

import pandas as pd

from src.data.models import FinancialMetrics

_INCOME_TTM_FIELDS = ["operate_profit", "total_revenue", "fin_exp", "fin_exp_int_exp", "int_exp", "n_income_attr_p"]
_CASH_TTM_FIELDS = ["depr_fa_coga_dpba"]


def resolve_financial_metrics_fetch_limit(limit: int, period: str) -> int:
    return limit * 4 if period == "annual" else limit


def fetch_financial_metric_frames(
    cached_call: Callable,
    cached_dataframe_call: Callable,
    pro,
    ts_code: str,
    fetch_limit: int,
    financial_fetch_limit: int,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    df_fin = cached_call(pro, "fina_indicator", ts_code, fetch_limit, dedupe=True)
    if df_fin is None or df_fin.empty:
        return None, None, None, None
    df_fin = _merge_financial_metric_extra_fields(cached_dataframe_call, pro, ts_code, fetch_limit, df_fin)
    df_cash = _safe_cached_statement_call(cached_call, pro, "cashflow", ts_code, financial_fetch_limit)
    df_bal = _safe_cached_statement_call(cached_call, pro, "balancesheet", ts_code, financial_fetch_limit)
    df_income = _safe_cached_statement_call(cached_call, pro, "income", ts_code, financial_fetch_limit)
    return df_fin, df_cash, df_bal, df_income


def _merge_financial_metric_extra_fields(cached_dataframe_call: Callable, pro, ts_code: str, fetch_limit: int, df_fin: pd.DataFrame) -> pd.DataFrame:
    try:
        df_extra = cached_dataframe_call(
            pro,
            "fina_indicator",
            ts_code=ts_code,
            limit=fetch_limit,
            fields="ts_code,end_date,inv_turn,dp_dt_ratio",
            dedupe=True,
        )
    except Exception:
        return df_fin
    if df_extra is None or df_extra.empty:
        return df_fin
    extra_cols = [column for column in df_extra.columns if column not in df_fin.columns]
    if not extra_cols:
        return df_fin
    return df_fin.merge(df_extra[["end_date"] + extra_cols], on="end_date", how="left")


def _safe_cached_statement_call(cached_call: Callable, pro, api_name: str, ts_code: str, limit: int) -> pd.DataFrame | None:
    try:
        return cached_call(pro, api_name, ts_code, limit, dedupe=True)
    except Exception:
        return None


def build_financial_metric_support_maps(
    df_fin: pd.DataFrame,
    df_cash: pd.DataFrame | None,
    df_income: pd.DataFrame | None,
) -> tuple[list[float | None], dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    period_dates = [str(row.get("end_date", "")) for _, row in df_fin.iterrows()]
    raw_fcf_map = _build_raw_fcf_map(df_cash)
    fcf_values = _build_fcf_values(period_dates, raw_fcf_map)
    raw_income_map = _build_raw_income_map(df_income, df_cash)
    ttm_income_map = _build_ttm_income_map(period_dates, raw_income_map)
    return fcf_values, raw_income_map, ttm_income_map


def _build_raw_fcf_map(df_cash: pd.DataFrame | None) -> dict[str, float]:
    raw_fcf_map: dict[str, float] = {}
    if df_cash is None or df_cash.empty:
        return raw_fcf_map
    for _, cash_row in df_cash.iterrows():
        end_date = str(cash_row.get("end_date", ""))
        if end_date in raw_fcf_map:
            continue
        op_cf_value = cash_row.get("n_cashflow_act")
        capex_value = cash_row.get("c_pay_acq_const_fiolta")
        if _is_present(op_cf_value) and _is_present(capex_value):
            raw_fcf_map[end_date] = float(op_cf_value) - float(capex_value)
            continue
        fallback_fcf = cash_row.get("free_cashflow")
        if _is_present(fallback_fcf):
            raw_fcf_map[end_date] = float(fallback_fcf)
    return raw_fcf_map


def _build_fcf_values(period_dates: list[str], raw_fcf_map: dict[str, float]) -> list[float | None]:
    fcf_values = [raw_fcf_map.get(end_date) for end_date in period_dates]
    for index, end_date in enumerate(period_dates):
        if fcf_values[index] is None or end_date.endswith("1231"):
            continue
        prior_annual_key, prior_same_key = _build_prior_period_keys(end_date)
        if prior_annual_key in raw_fcf_map and prior_same_key in raw_fcf_map:
            fcf_values[index] = fcf_values[index] + raw_fcf_map[prior_annual_key] - raw_fcf_map[prior_same_key]
    return fcf_values


def _build_raw_income_map(df_income: pd.DataFrame | None, df_cash: pd.DataFrame | None) -> dict[tuple[str, str], float]:
    raw_income_map: dict[tuple[str, str], float] = {}
    _collect_raw_income_fields(raw_income_map, df_income, _INCOME_TTM_FIELDS)
    _collect_raw_income_fields(raw_income_map, df_cash, _CASH_TTM_FIELDS)
    return raw_income_map


def _collect_raw_income_fields(raw_income_map: dict[tuple[str, str], float], frame: pd.DataFrame | None, fields: list[str]) -> None:
    if frame is None or frame.empty:
        return
    for _, source_row in frame.iterrows():
        end_date = str(source_row.get("end_date", ""))
        for field in fields:
            value = source_row.get(field)
            if _is_present(value):
                raw_income_map[(end_date, field)] = float(value)


def _build_ttm_income_map(period_dates: list[str], raw_income_map: dict[tuple[str, str], float]) -> dict[tuple[str, str], float]:
    ttm_income_map: dict[tuple[str, str], float] = {}
    all_ttm_fields = _INCOME_TTM_FIELDS + _CASH_TTM_FIELDS
    synthesis_dates = _extend_ttm_synthesis_dates(period_dates)
    for end_date in sorted(synthesis_dates):
        for field in all_ttm_fields:
            _populate_ttm_income_field(ttm_income_map, raw_income_map, end_date, field)
    return ttm_income_map


def _extend_ttm_synthesis_dates(period_dates: list[str]) -> set[str]:
    synthesis_dates = set(period_dates)
    for end_date in period_dates:
        if end_date.endswith("1231"):
            continue
        _, prior_same_key = _build_prior_period_keys(end_date)
        synthesis_dates.add(prior_same_key)
    return synthesis_dates


def _populate_ttm_income_field(ttm_income_map: dict[tuple[str, str], float], raw_income_map: dict[tuple[str, str], float], end_date: str, field: str) -> None:
    raw_value = raw_income_map.get((end_date, field))
    if raw_value is None:
        return
    if end_date.endswith("1231"):
        ttm_income_map[(end_date, field)] = raw_value
        return
    prior_annual_key, prior_same_key = _build_prior_period_keys(end_date)
    prior_annual = raw_income_map.get((prior_annual_key, field))
    prior_same = raw_income_map.get((prior_same_key, field))
    if prior_annual is not None and prior_same is not None:
        ttm_income_map[(end_date, field)] = raw_value + prior_annual - prior_same


def build_financial_metrics_from_frames(
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
    fcf_values: list[float | None],
    raw_income_map: dict[tuple[str, str], float],
    ttm_income_map: dict[tuple[str, str], float],
    get_latest_daily_basic: Callable,
    validate_margin: Callable[[float | None], float | None],
    validate_roe: Callable[[float | None], float | None],
) -> list[FinancialMetrics]:
    metrics: list[FinancialMetrics] = []
    balance_rows = _index_rows_by_end_date(df_bal)
    cash_rows = _index_rows_by_end_date(df_cash)
    income_rows = _index_rows_by_end_date(df_income)
    idx_out = 0
    for idx, (_, row) in enumerate(df_fin.iterrows()):
        end_date_str = str(row.get("end_date", ""))
        if not _should_include_financial_period(end_date_str, period):
            continue
        metric = _build_single_financial_metric(
            ticker=ticker,
            end_date=end_date,
            period=period,
            pro=pro,
            ts_code=ts_code,
            idx=idx,
            idx_out=idx_out,
            row=row,
            end_date_str=end_date_str,
            balance_rows=balance_rows,
            cash_rows=cash_rows,
            income_rows=income_rows,
            fcf_values=fcf_values,
            df_fin=df_fin,
            raw_income_map=raw_income_map,
            ttm_income_map=ttm_income_map,
            get_latest_daily_basic=get_latest_daily_basic,
            validate_margin=validate_margin,
            validate_roe=validate_roe,
        )
        metrics.append(metric)
        idx_out += 1
    return metrics[:limit]


def _build_single_financial_metric(**kwargs) -> FinancialMetrics:
    daily_anchor = kwargs["end_date"] if kwargs["idx_out"] == 0 else kwargs["end_date_str"]
    daily_data = kwargs["get_latest_daily_basic"](kwargs["pro"], kwargs["ts_code"], daily_anchor)
    market_snapshot = _build_market_snapshot(kwargs["row"], daily_data)
    balance_row = kwargs["balance_rows"].get(kwargs["end_date_str"])
    cash_row = kwargs["cash_rows"].get(kwargs["end_date_str"])
    income_row = kwargs["income_rows"].get(kwargs["end_date_str"])
    enterprise_metrics = _build_enterprise_metrics(
        market_cap=market_snapshot["market_cap"],
        end_date_str=kwargs["end_date_str"],
        balance_row=balance_row,
        cash_row=cash_row,
        income_row=income_row,
        raw_income_map=kwargs["raw_income_map"],
        ttm_income_map=kwargs["ttm_income_map"],
    )
    fcf_metrics = _build_fcf_metrics(
        idx=kwargs["idx"],
        end_date_str=kwargs["end_date_str"],
        balance_row=balance_row,
        fcf_values=kwargs["fcf_values"],
        market_cap=market_snapshot["market_cap"],
    )
    turnover_metrics = _build_turnover_metrics(
        row=kwargs["row"],
        end_date_str=kwargs["end_date_str"],
        balance_row=balance_row,
        cash_row=cash_row,
        ttm_income_map=kwargs["ttm_income_map"],
    )
    profitability_metrics = _build_profitability_metrics(
        row=kwargs["row"],
        end_date_str=kwargs["end_date_str"],
        balance_row=balance_row,
        df_fin=kwargs["df_fin"],
        idx=kwargs["idx"],
        ttm_income_map=kwargs["ttm_income_map"],
        validate_margin=kwargs["validate_margin"],
        validate_roe=kwargs["validate_roe"],
    )
    return _build_financial_metrics_model(
        ticker=kwargs["ticker"],
        period=kwargs["period"],
        row=kwargs["row"],
        end_date_str=kwargs["end_date_str"],
        market_snapshot=market_snapshot,
        enterprise_metrics=enterprise_metrics,
        fcf_metrics=fcf_metrics,
        turnover_metrics=turnover_metrics,
        profitability_metrics=profitability_metrics,
    )


def _should_include_financial_period(end_date_str: str, period: str) -> bool:
    if period == "annual":
        return end_date_str.endswith("1231")
    if period == "quarterly":
        return not end_date_str.endswith("1231")
    return True


def _build_market_snapshot(row, daily_data: dict | None) -> dict[str, float | None]:
    market_cap = None
    pe_ratio = None
    pb_ratio = None
    ps_ratio = None
    if daily_data:
        market_cap = _resolve_market_cap(daily_data)
        pe_ratio = _resolve_nonzero_ratio(daily_data, "pe_ttm", "pe")
        pb_ratio = _resolve_nonzero_ratio(daily_data, "pb")
        ps_ratio = _resolve_nonzero_ratio(daily_data, "ps_ttm", "ps")
    return {
        "market_cap": market_cap,
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "ps_ratio": ps_ratio,
        "peg_ratio": _build_peg_ratio(row, pe_ratio),
    }


def _resolve_market_cap(daily_data: dict) -> float | None:
    total_mv = daily_data.get("total_mv")
    if total_mv is None or pd.isna(total_mv):
        return None
    return float(total_mv) * 10000


def _resolve_nonzero_ratio(daily_data: dict, *field_names: str) -> float | None:
    for field_name in field_names:
        value = daily_data.get(field_name)
        if value is None or pd.isna(value) or float(value) == 0:
            continue
        return float(value)
    return None


def _build_peg_ratio(row, pe_ratio: float | None) -> float | None:
    if pe_ratio is None or pe_ratio <= 0:
        return None
    earnings_growth = float(row.get("netprofit_yoy", 0)) / 100 if pd.notna(row.get("netprofit_yoy")) else None
    if earnings_growth is None or earnings_growth <= 0:
        return None
    return pe_ratio / (earnings_growth * 100)


def _build_enterprise_metrics(
    *,
    market_cap: float | None,
    end_date_str: str,
    balance_row,
    cash_row,
    income_row,
    raw_income_map: dict[tuple[str, str], float],
    ttm_income_map: dict[tuple[str, str], float],
) -> dict[str, float | None]:
    enterprise_value = _build_enterprise_value(market_cap, balance_row)
    ev_to_ebitda, ev_to_revenue, interest_coverage = _build_ev_ratio_metrics(
        enterprise_value=enterprise_value,
        end_date_str=end_date_str,
        cash_row=cash_row,
        income_row=income_row,
        raw_income_map=raw_income_map,
        ttm_income_map=ttm_income_map,
    )
    return {
        "enterprise_value": enterprise_value,
        "ev_to_ebitda": ev_to_ebitda,
        "ev_to_revenue": ev_to_revenue,
        "interest_coverage": interest_coverage,
        "roic": _build_roic(end_date_str, balance_row, income_row, ttm_income_map),
    }


def _build_enterprise_value(market_cap: float | None, balance_row) -> float | None:
    if market_cap is None or balance_row is None:
        return None
    total_debt = _sum_present_values(balance_row.get("lt_borr", 0), balance_row.get("st_borr", 0), balance_row.get("bond_payable", 0))
    cash_eq = _to_clean_float(balance_row.get("money_cap", 0), default=0.0)
    enterprise_value = market_cap + total_debt - cash_eq
    return market_cap if enterprise_value < 0 else enterprise_value


def _build_ev_ratio_metrics(
    *,
    enterprise_value: float | None,
    end_date_str: str,
    cash_row,
    income_row,
    raw_income_map: dict[tuple[str, str], float],
    ttm_income_map: dict[tuple[str, str], float],
) -> tuple[float | None, float | None, float | None]:
    if enterprise_value is None or income_row is None:
        return None, None, None
    op_profit_ttm = _resolve_ttm_or_raw_value(ttm_income_map, end_date_str, "operate_profit", income_row.get("operate_profit"))
    int_exp_ttm = _resolve_interest_expense(ttm_income_map, end_date_str, income_row)
    fin_exp_ttm = _resolve_ttm_or_raw_value(ttm_income_map, end_date_str, "fin_exp", income_row.get("fin_exp", 0) or 0)
    revenue_ttm = _resolve_ttm_or_raw_value(ttm_income_map, end_date_str, "total_revenue", income_row.get("total_revenue"))
    depr_ttm = _resolve_depreciation(end_date_str, cash_row, raw_income_map, ttm_income_map)
    ev_to_ebitda = _build_ev_to_ebitda(enterprise_value, op_profit_ttm, fin_exp_ttm, depr_ttm)
    ev_to_revenue = enterprise_value / revenue_ttm if revenue_ttm is not None and revenue_ttm > 0 else None
    interest_coverage = None
    if op_profit_ttm is not None and int_exp_ttm > 0:
        interest_coverage = (op_profit_ttm + fin_exp_ttm) / int_exp_ttm
    return ev_to_ebitda, ev_to_revenue, interest_coverage


def _resolve_interest_expense(ttm_income_map: dict[tuple[str, str], float], end_date_str: str, income_row) -> float:
    int_exp_ttm = ttm_income_map.get((end_date_str, "fin_exp_int_exp"))
    if int_exp_ttm is None:
        int_exp_ttm = ttm_income_map.get((end_date_str, "int_exp"))
    if int_exp_ttm is not None:
        return int_exp_ttm
    raw_interest = income_row.get("fin_exp_int_exp") or income_row.get("int_exp", 0) or 0
    return _to_clean_float(raw_interest, default=0.0)


def _resolve_ttm_or_raw_value(ttm_income_map: dict[tuple[str, str], float], end_date_str: str, field: str, raw_value) -> float | None:
    ttm_value = ttm_income_map.get((end_date_str, field))
    if ttm_value is not None:
        return ttm_value
    return _to_clean_float(raw_value)


def _resolve_depreciation(
    end_date_str: str,
    cash_row,
    raw_income_map: dict[tuple[str, str], float],
    ttm_income_map: dict[tuple[str, str], float],
) -> float:
    depreciation = ttm_income_map.get((end_date_str, "depr_fa_coga_dpba"))
    if depreciation not in {None, 0}:
        return depreciation
    if cash_row is not None:
        raw_depreciation = cash_row.get("depr_fa_coga_dpba")
        if _is_present(raw_depreciation):
            return float(raw_depreciation)
    year = end_date_str[:4]
    prior_year = str(int(year) - 1)
    h1_key = (f"{year}0630", "depr_fa_coga_dpba")
    annual_key = (f"{prior_year}1231", "depr_fa_coga_dpba")
    if h1_key in raw_income_map:
        return raw_income_map[h1_key] * 2.0
    if annual_key in raw_income_map:
        return raw_income_map[annual_key]
    return 0.0


def _build_ev_to_ebitda(enterprise_value: float, op_profit_ttm: float | None, fin_exp_ttm: float, depr_ttm: float) -> float | None:
    if op_profit_ttm is None:
        return None
    ebit = op_profit_ttm + fin_exp_ttm
    ebitda = ebit + depr_ttm
    if ebitda > 0:
        return enterprise_value / ebitda
    if ebit > 0:
        return enterprise_value / ebit
    return None


def _build_roic(end_date_str: str, balance_row, income_row, ttm_income_map: dict[tuple[str, str], float]) -> float | None:
    if balance_row is None:
        return None
    op_profit = ttm_income_map.get((end_date_str, "operate_profit"))
    if op_profit is None and income_row is not None:
        op_profit = _to_clean_float(income_row.get("operate_profit"))
    total_assets = balance_row.get("total_assets")
    current_liabilities = balance_row.get("total_cur_liab")
    if op_profit is None or total_assets is None or current_liabilities is None:
        return None
    if any(isinstance(value, float) and pd.isna(value) for value in [total_assets, current_liabilities]):
        return None
    invested_capital = float(total_assets) - float(current_liabilities)
    if invested_capital <= 0:
        return None
    return (op_profit * 0.75) / invested_capital


def _build_fcf_metrics(
    *,
    idx: int,
    end_date_str: str,
    balance_row,
    fcf_values: list[float | None],
    market_cap: float | None,
) -> dict[str, float | None]:
    if not fcf_values or idx >= len(fcf_values) or fcf_values[idx] is None:
        return {"yield": None, "growth": None, "per_share": None}
    current_fcf = fcf_values[idx]
    fcf_per_share = _build_fcf_per_share(balance_row, current_fcf)
    return {
        "yield": current_fcf / market_cap if market_cap is not None and market_cap > 0 else None,
        "growth": _build_fcf_growth(idx, fcf_values, current_fcf),
        "per_share": fcf_per_share,
    }


def _build_fcf_per_share(balance_row, current_fcf: float) -> float | None:
    if balance_row is None:
        return None
    shares = balance_row.get("total_share")
    if shares is None or (isinstance(shares, float) and pd.isna(shares)) or float(shares) <= 0:
        return None
    return current_fcf / float(shares)


def _build_fcf_growth(idx: int, fcf_values: list[float | None], current_fcf: float) -> float | None:
    if idx + 1 >= len(fcf_values):
        return None
    previous_fcf = fcf_values[idx + 1]
    if previous_fcf is None or abs(previous_fcf) <= 1e-9:
        return None
    if (current_fcf > 0 > previous_fcf) or (current_fcf < 0 < previous_fcf):
        return None
    raw_growth = (current_fcf - previous_fcf) / abs(previous_fcf)
    if abs(raw_growth) > 3.0 and abs(previous_fcf) < abs(current_fcf) * 0.05:
        return None
    return raw_growth


def _build_turnover_metrics(
    *,
    row,
    end_date_str: str,
    balance_row,
    cash_row,
    ttm_income_map: dict[tuple[str, str], float],
) -> dict[str, float | None]:
    inventory_turnover = _resolve_positive_row_metric(row, "inv_turn")
    receivables_turnover = _resolve_positive_row_metric(row, "ar_turn")
    dso = 365.0 / receivables_turnover if receivables_turnover is not None and receivables_turnover > 0 else None
    operating_cycle = None
    if inventory_turnover is not None and receivables_turnover is not None:
        operating_cycle = 365.0 / inventory_turnover + 365.0 / receivables_turnover
    return {
        "inventory_turnover": inventory_turnover,
        "receivables_turnover": receivables_turnover,
        "days_sales_outstanding": dso,
        "operating_cycle": operating_cycle,
        "working_capital_turnover": _build_working_capital_turnover(end_date_str, balance_row, ttm_income_map),
        "operating_cash_flow_ratio": _build_operating_cash_flow_ratio(balance_row, cash_row),
        "ebitda_growth": None,
        "payout_ratio": _build_payout_ratio(row),
    }


def _resolve_positive_row_metric(row, field_name: str) -> float | None:
    value = row.get(field_name)
    if value is None or pd.isna(value) or float(value) <= 0:
        return None
    return float(value)


def _build_working_capital_turnover(end_date_str: str, balance_row, ttm_income_map: dict[tuple[str, str], float]) -> float | None:
    if balance_row is None:
        return None
    current_assets = balance_row.get("total_cur_assets")
    current_liabilities = balance_row.get("total_cur_liab")
    if current_assets is None or current_liabilities is None:
        return None
    if any(isinstance(value, float) and pd.isna(value) for value in [current_assets, current_liabilities]):
        return None
    working_capital = float(current_assets) - float(current_liabilities)
    if abs(working_capital) <= 1e-9:
        return None
    revenue_ttm = ttm_income_map.get((end_date_str, "total_revenue"))
    if revenue_ttm is None or revenue_ttm <= 0:
        return None
    return revenue_ttm / abs(working_capital)


def _build_operating_cash_flow_ratio(balance_row, cash_row) -> float | None:
    if balance_row is None or cash_row is None:
        return None
    net_cashflow = cash_row.get("n_cashflow_act")
    current_liabilities = balance_row.get("total_cur_liab")
    if net_cashflow is None or current_liabilities is None:
        return None
    if any(isinstance(value, float) and pd.isna(value) for value in [net_cashflow, current_liabilities]):
        return None
    if float(current_liabilities) <= 0:
        return None
    return float(net_cashflow) / float(current_liabilities)


def _build_payout_ratio(row) -> float | None:
    payout_ratio = row.get("dp_dt_ratio")
    if payout_ratio is None or pd.isna(payout_ratio):
        return None
    return float(payout_ratio) / 100.0


def _build_profitability_metrics(
    *,
    row,
    end_date_str: str,
    balance_row,
    df_fin: pd.DataFrame,
    idx: int,
    ttm_income_map: dict[tuple[str, str], float],
    validate_margin: Callable[[float | None], float | None],
    validate_roe: Callable[[float | None], float | None],
) -> dict[str, float | None]:
    ttm_operating_margin, ttm_net_margin, ttm_roe, ttm_revenue_growth, ttm_earnings_growth = _build_ttm_profitability_values(
        row=row,
        end_date_str=end_date_str,
        balance_row=balance_row,
        ttm_income_map=ttm_income_map,
    )
    return {
        "gross_margin": validate_margin(_resolve_margin_percentage(row.get("grossprofit_margin"))),
        "operating_margin": validate_margin(ttm_operating_margin),
        "net_margin": validate_margin(ttm_net_margin),
        "return_on_equity": validate_roe(ttm_roe),
        "return_on_assets": validate_roe(_resolve_margin_percentage(row.get("roa"))),
        "revenue_growth": ttm_revenue_growth,
        "earnings_growth": ttm_earnings_growth,
        "book_value_growth": _build_book_value_growth(df_fin, idx, row),
        "eps_growth": _clamp_growth_percentage(row.get("basic_eps_yoy")),
        "operating_income_growth": _clamp_growth_percentage(row.get("op_yoy")),
        "ebitda_growth": _build_ebitda_growth(end_date_str, idx, df_fin, ttm_income_map),
    }


def _build_ttm_profitability_values(*, row, end_date_str: str, balance_row, ttm_income_map: dict[tuple[str, str], float]) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    ttm_operating_profit = ttm_income_map.get((end_date_str, "operate_profit"))
    ttm_total_revenue = ttm_income_map.get((end_date_str, "total_revenue"))
    ttm_net_income = ttm_income_map.get((end_date_str, "n_income_attr_p"))
    ttm_operating_margin = _build_ttm_margin_value(ttm_operating_profit, ttm_total_revenue, fallback_percentage=row.get("op_of_gr"))
    ttm_net_margin = _build_ttm_margin_value(ttm_net_income, ttm_total_revenue, fallback_percentage=row.get("netprofit_margin"))
    ttm_roe = _build_ttm_roe(ttm_net_income, balance_row, fallback_percentage=row.get("roe"))
    ttm_revenue_growth, ttm_earnings_growth = _build_ttm_growth_values(end_date_str, ttm_total_revenue, ttm_net_income, ttm_income_map)
    if ttm_revenue_growth is None:
        ttm_revenue_growth = _clamp_growth_percentage(row.get("or_yoy"))
    if ttm_earnings_growth is None:
        ttm_earnings_growth = _clamp_growth_percentage(row.get("netprofit_yoy"))
    return ttm_operating_margin, ttm_net_margin, ttm_roe, ttm_revenue_growth, ttm_earnings_growth


def _build_ttm_margin_value(ttm_numerator: float | None, ttm_revenue: float | None, fallback_percentage) -> float | None:
    if ttm_numerator is not None and ttm_revenue is not None and ttm_revenue != 0:
        return ttm_numerator / ttm_revenue
    return _resolve_margin_percentage(fallback_percentage)


def _build_ttm_roe(ttm_net_income: float | None, balance_row, fallback_percentage) -> float | None:
    if ttm_net_income is not None and balance_row is not None:
        equity = balance_row.get("total_hldr_eqy_exc_min_int")
        if equity is None or (isinstance(equity, float) and pd.isna(equity)):
            equity = balance_row.get("total_hldr_eqy_inc_min_int")
        if equity is not None and not (isinstance(equity, float) and pd.isna(equity)) and float(equity) > 0:
            return ttm_net_income / float(equity)
    return _resolve_margin_percentage(fallback_percentage)


def _build_ttm_growth_values(end_date_str: str, ttm_total_revenue: float | None, ttm_net_income: float | None, ttm_income_map: dict[tuple[str, str], float]) -> tuple[float | None, float | None]:
    if end_date_str.endswith("1231") or ttm_total_revenue is None:
        return None, None
    prior_same_key = _build_prior_period_keys(end_date_str)[1]
    prior_ttm_revenue = ttm_income_map.get((prior_same_key, "total_revenue"))
    revenue_growth = _build_growth_from_prior(ttm_total_revenue, prior_ttm_revenue)
    prior_ttm_net_income = ttm_income_map.get((prior_same_key, "n_income_attr_p")) if ttm_net_income is not None else None
    earnings_growth = _build_growth_from_prior(ttm_net_income, prior_ttm_net_income)
    return revenue_growth, earnings_growth


def _build_growth_from_prior(current_value: float | None, prior_value: float | None) -> float | None:
    if current_value is None or prior_value is None or abs(prior_value) <= 1e-9:
        return None
    return max(-1.0, min(5.0, (current_value - prior_value) / abs(prior_value)))


def _build_book_value_growth(df_fin: pd.DataFrame, idx: int, row) -> float | None:
    current_bps = row.get("bps")
    if current_bps is None or pd.isna(current_bps) or float(current_bps) <= 0 or idx + 1 >= len(df_fin):
        return None
    previous_bps = df_fin.iloc[idx + 1].get("bps")
    if previous_bps is None or pd.isna(previous_bps) or float(previous_bps) <= 0:
        return None
    return (float(current_bps) - float(previous_bps)) / float(previous_bps)


def _build_ebitda_growth(end_date_str: str, idx: int, df_fin: pd.DataFrame, ttm_income_map: dict[tuple[str, str], float]) -> float | None:
    current_ebitda = _resolve_ttm_ebitda(end_date_str, ttm_income_map)
    if current_ebitda is None or idx + 1 >= len(df_fin):
        return None
    previous_end_date = str(df_fin.iloc[idx + 1].get("end_date", ""))
    previous_ebitda = _resolve_ttm_ebitda(previous_end_date, ttm_income_map)
    if previous_ebitda is None or abs(previous_ebitda) <= 1e-9:
        return None
    return (current_ebitda - previous_ebitda) / abs(previous_ebitda)


def _resolve_ttm_ebitda(end_date_str: str, ttm_income_map: dict[tuple[str, str], float]) -> float | None:
    operating_profit = ttm_income_map.get((end_date_str, "operate_profit"))
    financial_expense = ttm_income_map.get((end_date_str, "fin_exp"))
    if operating_profit is None or financial_expense is None:
        return None
    depreciation = ttm_income_map.get((end_date_str, "depr_fa_coga_dpba")) or 0
    return operating_profit + financial_expense + depreciation


def _build_financial_metrics_model(
    *,
    ticker: str,
    period: str,
    row,
    end_date_str: str,
    market_snapshot: dict[str, float | None],
    enterprise_metrics: dict[str, float | None],
    fcf_metrics: dict[str, float | None],
    turnover_metrics: dict[str, float | None],
    profitability_metrics: dict[str, float | None],
) -> FinancialMetrics:
    return FinancialMetrics(
        ticker=ticker,
        report_period=end_date_str,
        period="annual" if end_date_str.endswith("1231") else period,
        currency="CNY",
        market_cap=market_snapshot["market_cap"],
        enterprise_value=enterprise_metrics["enterprise_value"],
        price_to_earnings_ratio=market_snapshot["pe_ratio"],
        price_to_book_ratio=market_snapshot["pb_ratio"],
        price_to_sales_ratio=market_snapshot["ps_ratio"],
        enterprise_value_to_ebitda_ratio=enterprise_metrics["ev_to_ebitda"],
        enterprise_value_to_revenue_ratio=enterprise_metrics["ev_to_revenue"],
        free_cash_flow_yield=fcf_metrics["yield"],
        peg_ratio=market_snapshot["peg_ratio"],
        gross_margin=profitability_metrics["gross_margin"],
        operating_margin=profitability_metrics["operating_margin"],
        net_margin=profitability_metrics["net_margin"],
        return_on_equity=profitability_metrics["return_on_equity"],
        return_on_assets=profitability_metrics["return_on_assets"],
        return_on_invested_capital=enterprise_metrics["roic"],
        asset_turnover=float(row.get("assets_turn", 0)) if pd.notna(row.get("assets_turn")) else None,
        inventory_turnover=turnover_metrics["inventory_turnover"],
        receivables_turnover=turnover_metrics["receivables_turnover"],
        days_sales_outstanding=turnover_metrics["days_sales_outstanding"],
        operating_cycle=turnover_metrics["operating_cycle"],
        working_capital_turnover=turnover_metrics["working_capital_turnover"],
        current_ratio=_to_clean_float(row.get("current_ratio", 0)) if pd.notna(row.get("current_ratio")) else None,
        quick_ratio=_to_clean_float(row.get("quick_ratio", 0)) if pd.notna(row.get("quick_ratio")) else None,
        cash_ratio=_to_clean_float(row.get("cash_ratio", 0)) if pd.notna(row.get("cash_ratio")) else None,
        operating_cash_flow_ratio=turnover_metrics["operating_cash_flow_ratio"],
        debt_to_equity=_to_clean_float(row.get("debt_to_eqt", 0)) if pd.notna(row.get("debt_to_eqt")) else None,
        debt_to_assets=_resolve_margin_percentage(row.get("debt_to_assets")),
        interest_coverage=enterprise_metrics["interest_coverage"],
        revenue_growth=profitability_metrics["revenue_growth"],
        earnings_growth=profitability_metrics["earnings_growth"],
        book_value_growth=profitability_metrics["book_value_growth"],
        earnings_per_share_growth=profitability_metrics["eps_growth"],
        free_cash_flow_growth=_clamp_optional_growth(fcf_metrics["growth"]),
        operating_income_growth=profitability_metrics["operating_income_growth"],
        ebitda_growth=profitability_metrics["ebitda_growth"],
        payout_ratio=turnover_metrics["payout_ratio"],
        earnings_per_share=_to_clean_float(row.get("eps", 0)) if pd.notna(row.get("eps")) else None,
        book_value_per_share=_to_clean_float(row.get("bps", 0)) if pd.notna(row.get("bps")) else None,
        free_cash_flow_per_share=fcf_metrics["per_share"],
    )


def _index_rows_by_end_date(frame: pd.DataFrame | None) -> dict[str, pd.Series]:
    if frame is None or frame.empty:
        return {}
    return {str(source_row.get("end_date", "")): source_row for _, source_row in frame.iterrows()}


def _build_prior_period_keys(end_date_str: str) -> tuple[str, str]:
    prior_year = str(int(end_date_str[:4]) - 1)
    return f"{prior_year}1231", f"{prior_year}{end_date_str[4:]}"


def _sum_present_values(*values) -> float:
    total = 0.0
    for value in values:
        total += _to_clean_float(value, default=0.0)
    return total


def _resolve_margin_percentage(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value) / 100.0


def _clamp_growth_percentage(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return max(-1.0, min(5.0, float(value) / 100.0))


def _clamp_optional_growth(value: float | None) -> float | None:
    if value is None:
        return None
    return max(-1.0, min(5.0, value))


def _to_clean_float(value, default=None):
    if value is None:
        return default
    if isinstance(value, float) and pd.isna(value):
        return default
    return float(value)


def _is_present(value) -> bool:
    return value is not None and not (isinstance(value, float) and pd.isna(value))
