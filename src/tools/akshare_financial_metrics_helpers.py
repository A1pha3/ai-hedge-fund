from __future__ import annotations

from typing import List

import pandas as pd

from src.data.models import FinancialMetrics


def hydrate_cached_financial_metrics(cached_data: list[dict]) -> List[FinancialMetrics]:
    return [FinancialMetrics(**metric) for metric in cached_data]


def dump_financial_metrics_for_cache(metrics: List[FinancialMetrics]) -> list[dict]:
    return [metric.model_dump() for metric in metrics]


def execute_financial_metrics_request(
    *,
    ticker: str,
    end_date: str,
    limit: int,
    use_mock: bool,
    cache_key: str,
    cache,
    hydrate_cached_fn,
    get_mock_metrics_fn,
    get_akshare_fn,
    load_financial_metrics_fn,
    dump_metrics_fn,
    error_factory,
) -> List[FinancialMetrics]:
    if cached_data := cache.get_financial_metrics(cache_key):
        return hydrate_cached_fn(cached_data)

    if use_mock:
        return get_mock_metrics_fn(ticker, end_date, limit)

    ak_module = get_akshare_fn()
    if ak_module is None:
        raise error_factory("AKShare 模块不可用，无法获取 A 股财务数据。\n请检查网络连接，或使用 use_mock=True 参数使用模拟数据。")

    metrics = load_financial_metrics_fn(ticker=ticker, limit=limit, ak_module=ak_module)
    cache.set_financial_metrics(cache_key, dump_metrics_fn(metrics))
    return metrics


def load_financial_metrics_with_fallback(
    *,
    ticker: str,
    limit: int,
    ak_module,
    cached_dataframe_call_fn,
    ticker_parser,
    error_factory,
) -> List[FinancialMetrics]:
    ashare = ticker_parser.from_symbol(ticker)

    df = cached_dataframe_call_fn(
        "stock_financial_analysis_indicator",
        ak_module.stock_financial_analysis_indicator,
        symbol=ashare.symbol,
    )
    if df is not None and not df.empty:
        return build_metrics_from_analysis_indicator_df(ticker=ticker, df=df, limit=limit)

    df_profit = cached_dataframe_call_fn(
        "stock_financial_report_sina",
        ak_module.stock_financial_report_sina,
        stock=ashare.symbol,
        symbol="利润表",
    )
    if df_profit is None or df_profit.empty:
        raise error_factory(
            f"无法获取股票 {ticker} 的财务数据（AKShare 返回空数据）。\n"
            "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。"
        )

    return build_metrics_from_sina_profit_df(ticker=ticker, df_profit=df_profit, limit=limit)


def build_metrics_from_sina_profit_df(*, ticker: str, df_profit: pd.DataFrame, limit: int) -> List[FinancialMetrics]:
    metrics: list[FinancialMetrics] = []
    for _, row in df_profit.head(limit).iterrows():
        metrics.append(
            FinancialMetrics(
                ticker=ticker,
                report_period=str(row.get("报告日", "")),
                period="ttm",
                currency="CNY",
                market_cap=None,
                enterprise_value=None,
                price_to_earnings_ratio=None,
                price_to_book_ratio=None,
                price_to_sales_ratio=None,
                enterprise_value_to_ebitda_ratio=None,
                enterprise_value_to_revenue_ratio=None,
                free_cash_flow_yield=None,
                peg_ratio=None,
                gross_margin=None,
                operating_margin=None,
                net_margin=None,
                return_on_equity=None,
                return_on_assets=None,
                return_on_invested_capital=None,
                asset_turnover=None,
                inventory_turnover=None,
                receivables_turnover=None,
                days_sales_outstanding=None,
                operating_cycle=None,
                working_capital_turnover=None,
                current_ratio=None,
                quick_ratio=None,
                cash_ratio=None,
                operating_cash_flow_ratio=None,
                debt_to_equity=None,
                debt_to_assets=None,
                interest_coverage=None,
                revenue_growth=None,
                earnings_growth=None,
                book_value_growth=None,
                earnings_per_share_growth=None,
                free_cash_flow_growth=None,
                operating_income_growth=None,
                ebitda_growth=None,
                payout_ratio=None,
                earnings_per_share=None,
                book_value_per_share=None,
                free_cash_flow_per_share=None,
            )
        )
    return metrics


def build_metrics_from_analysis_indicator_df(*, ticker: str, df: pd.DataFrame, limit: int) -> List[FinancialMetrics]:
    metrics: list[FinancialMetrics] = []
    for _, row in df.head(limit).iterrows():
        metrics.append(
            FinancialMetrics(
                ticker=ticker,
                report_period=str(row.get("报告期", "")),
                period="ttm",
                currency="CNY",
                market_cap=None,
                enterprise_value=None,
                price_to_earnings_ratio=float(row.get("市盈率", 0)) if pd.notna(row.get("市盈率")) else None,
                price_to_book_ratio=float(row.get("市净率", 0)) if pd.notna(row.get("市净率")) else None,
                price_to_sales_ratio=None,
                enterprise_value_to_ebitda_ratio=None,
                enterprise_value_to_revenue_ratio=None,
                free_cash_flow_yield=None,
                peg_ratio=None,
                gross_margin=None,
                operating_margin=None,
                net_margin=None,
                return_on_equity=float(row.get("净资产收益率", 0)) / 100 if pd.notna(row.get("净资产收益率")) else None,
                return_on_assets=None,
                return_on_invested_capital=None,
                asset_turnover=None,
                inventory_turnover=None,
                receivables_turnover=None,
                days_sales_outstanding=None,
                operating_cycle=None,
                working_capital_turnover=None,
                current_ratio=None,
                quick_ratio=None,
                cash_ratio=None,
                operating_cash_flow_ratio=None,
                debt_to_equity=float(row.get("资产负债率", 0)) / 100 if pd.notna(row.get("资产负债率")) else None,
                debt_to_assets=None,
                interest_coverage=None,
                revenue_growth=None,
                earnings_growth=None,
                book_value_growth=None,
                earnings_per_share_growth=None,
                free_cash_flow_growth=None,
                operating_income_growth=None,
                ebitda_growth=None,
                payout_ratio=None,
                earnings_per_share=None,
                book_value_per_share=None,
                free_cash_flow_per_share=None,
            )
        )
    return metrics
