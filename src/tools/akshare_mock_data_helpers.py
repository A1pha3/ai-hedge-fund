from __future__ import annotations

from datetime import datetime, timedelta
from random import Random

from src.data.models import FinancialMetrics, Price


def build_mock_price(*, current: datetime, base_price: float, rand: Random) -> tuple[Price, float]:
    change = rand.uniform(-0.02, 0.02)
    close = base_price * (1 + change)
    open_price = base_price * (1 + rand.uniform(-0.01, 0.01))
    high = max(open_price, close) * (1 + rand.uniform(0, 0.01))
    low = min(open_price, close) * (1 - rand.uniform(0, 0.01))
    volume = rand.randint(1000000, 10000000)

    return (
        Price(
            time=current.strftime("%Y-%m-%d"),
            open=round(open_price, 2),
            high=round(high, 2),
            low=round(low, 2),
            close=round(close, 2),
            volume=volume,
        ),
        close,
    )


def build_mock_prices(start_date: str, end_date: str, rand: Random) -> list[Price]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    prices: list[Price] = []
    current = start
    base_price = 50.0

    while current <= end:
        if current.weekday() < 5:
            price, base_price = build_mock_price(current=current, base_price=base_price, rand=rand)
            prices.append(price)
        current += timedelta(days=1)

    return prices


def build_mock_financial_metric(
    *,
    ticker: str,
    report_period: str,
    rand: Random,
) -> FinancialMetrics:
    pe_ratio = rand.uniform(10.0, 30.0)
    pb_ratio = rand.uniform(1.0, 5.0)
    roe = rand.uniform(0.10, 0.20)
    debt_to_equity = rand.uniform(0.3, 0.7)

    return FinancialMetrics(
        ticker=ticker,
        report_period=report_period,
        period="quarterly",
        currency="CNY",
        market_cap=rand.uniform(100000000000, 1000000000000),
        enterprise_value=rand.uniform(100000000000, 1000000000000),
        price_to_earnings_ratio=pe_ratio,
        price_to_book_ratio=pb_ratio,
        price_to_sales_ratio=rand.uniform(1.0, 10.0),
        enterprise_value_to_ebitda_ratio=rand.uniform(5.0, 20.0),
        enterprise_value_to_revenue_ratio=rand.uniform(1.0, 5.0),
        free_cash_flow_yield=rand.uniform(0.02, 0.08),
        peg_ratio=rand.uniform(0.5, 2.0),
        gross_margin=rand.uniform(0.3, 0.6),
        operating_margin=rand.uniform(0.15, 0.35),
        net_margin=rand.uniform(0.1, 0.25),
        return_on_equity=roe,
        return_on_assets=rand.uniform(0.05, 0.15),
        return_on_invested_capital=rand.uniform(0.08, 0.18),
        asset_turnover=rand.uniform(0.5, 1.5),
        inventory_turnover=rand.uniform(2.0, 10.0),
        receivables_turnover=rand.uniform(5.0, 15.0),
        days_sales_outstanding=rand.uniform(20.0, 60.0),
        operating_cycle=rand.uniform(50.0, 150.0),
        working_capital_turnover=rand.uniform(2.0, 8.0),
        current_ratio=rand.uniform(1.0, 3.0),
        quick_ratio=rand.uniform(0.8, 2.5),
        cash_ratio=rand.uniform(0.3, 1.5),
        operating_cash_flow_ratio=rand.uniform(0.1, 0.4),
        debt_to_equity=debt_to_equity,
        debt_to_assets=rand.uniform(0.2, 0.6),
        interest_coverage=rand.uniform(5.0, 20.0),
        revenue_growth=rand.uniform(-0.1, 0.3),
        earnings_growth=rand.uniform(-0.1, 0.4),
        book_value_growth=rand.uniform(0.05, 0.25),
        earnings_per_share_growth=rand.uniform(-0.1, 0.4),
        free_cash_flow_growth=rand.uniform(-0.1, 0.3),
        operating_income_growth=rand.uniform(-0.05, 0.3),
        ebitda_growth=rand.uniform(-0.05, 0.35),
        payout_ratio=rand.uniform(0.2, 0.6),
        earnings_per_share=rand.uniform(1.0, 10.0),
        book_value_per_share=rand.uniform(10.0, 50.0),
        free_cash_flow_per_share=rand.uniform(2.0, 15.0),
    )


def roll_back_to_previous_quarter(base_date: datetime) -> datetime:
    quarter = (base_date.month - 1) // 3
    year = base_date.year
    if quarter == 0:
        return base_date.replace(year=year - 1, month=10, day=1)
    return base_date.replace(month=(quarter - 1) * 3 + 1, day=1)


def build_mock_financial_metrics(ticker: str, end_date: str, limit: int, rand: Random) -> list[FinancialMetrics]:
    metrics: list[FinancialMetrics] = []
    base_date = datetime.strptime(end_date, "%Y-%m-%d")

    for _ in range(limit):
        quarter = (base_date.month - 1) // 3
        report_period = f"{base_date.year}Q{quarter + 1}"
        metrics.append(build_mock_financial_metric(ticker=ticker, report_period=report_period, rand=rand))
        base_date = roll_back_to_previous_quarter(base_date)

    return metrics
