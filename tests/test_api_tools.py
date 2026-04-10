import time as time_module
from types import SimpleNamespace

import pandas as pd

import src.tools.api as api
import src.tools.tushare_api as tushare_api


class _DummyCache:
    def __init__(self):
        self.insider_trades = {}
        self.company_news = {}

    def get_insider_trades(self, key):
        return self.insider_trades.get(key)

    def set_insider_trades(self, key, value):
        self.insider_trades[key] = value

    def get_company_news(self, key):
        return self.company_news.get(key)

    def set_company_news(self, key, value):
        self.company_news[key] = value


def test_get_insider_trades_ashare_uses_tushare_and_caches(monkeypatch):
    cache = _DummyCache()
    sentinel = [
        api.InsiderTrade(
            ticker="000001",
            issuer="issuer",
            name="name",
            title="title",
            is_board_director=False,
            transaction_date="2026-04-01",
            transaction_shares=10,
            transaction_price_per_share=1.2,
            transaction_value=12,
            shares_owned_before_transaction=100,
            shares_owned_after_transaction=110,
            security_title="common",
            filing_date="2026-04-02",
        )
    ]
    monkeypatch.setattr(api, "_cache", cache)
    monkeypatch.setattr(api, "is_ashare", lambda ticker: True)
    monkeypatch.setattr(api, "get_ashare_insider_trades_with_tushare", lambda *args: sentinel)

    trades = api.get_insider_trades("000001", "2026-04-10", "2026-04-01", 5)

    assert trades is sentinel
    assert cache.insider_trades["000001_2026-04-01_2026-04-10_5"] == [trade.model_dump() for trade in sentinel]


def test_get_insider_trades_remote_paginates_and_caches(monkeypatch):
    cache = _DummyCache()
    responses = iter(
        [
            SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "insider_trades": [
                        {
                            "ticker": "AAPL",
                            "issuer": "Apple",
                            "name": "Tim",
                            "title": "CEO",
                            "is_board_director": True,
                            "transaction_date": "2026-04-02",
                            "transaction_shares": 10,
                            "transaction_price_per_share": 100,
                            "transaction_value": 1000,
                            "shares_owned_before_transaction": 100,
                            "shares_owned_after_transaction": 110,
                            "security_title": "Common",
                            "filing_date": "2026-04-03T00:00:00",
                        }
                    ]
                },
            ),
            SimpleNamespace(status_code=200, json=lambda: {"insider_trades": []}),
        ]
    )
    monkeypatch.setattr(api, "_cache", cache)
    monkeypatch.setattr(api, "is_ashare", lambda ticker: False)
    monkeypatch.setattr(api, "_make_api_request", lambda *args, **kwargs: next(responses))

    trades = api.get_insider_trades("AAPL", "2026-04-10", "2026-04-01", 1)

    assert len(trades) == 1
    assert trades[0].ticker == "AAPL"
    assert cache.insider_trades["AAPL_2026-04-01_2026-04-10_1"] == [trade.model_dump() for trade in trades]


def test_get_company_news_ashare_uses_akshare_and_caches(monkeypatch):
    cache = _DummyCache()
    sentinel = [
        api.CompanyNews(
            ticker="000001",
            title="headline",
            author="author",
            source="source",
            date="2026-04-03",
            url="https://example.com",
            sentiment="neutral",
            content="body",
        )
    ]
    monkeypatch.setattr(api, "_cache", cache)
    monkeypatch.setattr(api, "is_ashare", lambda ticker: True)
    monkeypatch.setattr(api, "get_ashare_company_news", lambda *args: sentinel)

    news = api.get_company_news("000001", "2026-04-10", "2026-04-01", 5)

    assert news is sentinel
    assert cache.company_news["000001_2026-04-01_2026-04-10_5_ashare"] == [item.model_dump() for item in sentinel]


def test_get_company_news_remote_sorts_descending_and_caches(monkeypatch):
    cache = _DummyCache()
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "news": [
                {
                    "ticker": "AAPL",
                    "title": "older",
                    "author": "author",
                    "source": "source",
                    "date": "2026-04-01T00:00:00",
                    "url": "https://example.com/1",
                    "sentiment": None,
                    "content": None,
                },
                {
                    "ticker": "AAPL",
                    "title": "newer",
                    "author": "author",
                    "source": "source",
                    "date": "2026-04-03T00:00:00",
                    "url": "https://example.com/2",
                    "sentiment": None,
                    "content": None,
                },
            ]
        },
    )
    monkeypatch.setattr(api, "_cache", cache)
    monkeypatch.setattr(api, "is_ashare", lambda ticker: False)
    monkeypatch.setattr(api, "_make_api_request", lambda *args, **kwargs: response)

    news = api.get_company_news("AAPL", "2026-04-10", "2026-04-01", 5)

    assert [item.title for item in news] == ["newer", "older"]
    assert cache.company_news["AAPL_2026-04-01_2026-04-10_5"] == [item.model_dump() for item in news]


def test_get_ashare_daily_gainers_with_tushare_filters_st_and_formats_results(monkeypatch):
    pro = object()
    monkeypatch.setattr(tushare_api, "_get_pro", lambda: pro)

    def fake_cached_call(_pro, api_name, **kwargs):
        if api_name == "daily":
            return pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "trade_date": "20260410", "open": 10.0, "high": 11.0, "low": 9.8, "close": 10.8, "pre_close": 10.0, "vol": 1000, "amount": 2000, "pct_chg": 8.0},
                    {"ts_code": "000002.SZ", "trade_date": "20260410", "open": 5.0, "high": 5.1, "low": 4.9, "close": 5.0, "pre_close": 5.0, "vol": 800, "amount": 1200, "pct_chg": 0.0},
                    {"ts_code": "000003.SZ", "trade_date": "20260410", "open": 3.0, "high": 3.5, "low": 2.9, "close": 3.3, "pre_close": 3.0, "vol": 500, "amount": 600, "pct_chg": 10.0},
                ]
            )
        if api_name == "stock_basic":
            return pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "name": "平安银行", "area": "深圳", "industry": "银行", "market": "主板", "list_date": "19910403"},
                    {"ts_code": "000003.SZ", "name": "ST测试", "area": "深圳", "industry": "测试", "market": "主板", "list_date": "20000101"},
                ]
            )
        raise AssertionError(api_name)

    monkeypatch.setattr(tushare_api, "_cached_tushare_dataframe_call", fake_cached_call)

    results = tushare_api.get_ashare_daily_gainers_with_tushare("2026-04-10", pct_threshold=3.0, include_name=True)

    assert results == [
        {
            "ts_code": "000001.SZ",
            "trade_date": "2026-04-10",
            "pct_chg": 8.0,
            "open": 10.0,
            "high": 11.0,
            "low": 9.8,
            "close": 10.8,
            "pre_close": 10.0,
            "vol": 1000,
            "amount": 2000.0,
            "name": "平安银行",
            "area": "深圳",
            "industry": "银行",
            "market": "主板",
            "list_date": "19910403",
        }
    ]


def test_get_sw_industry_classification_merges_members_and_caches(monkeypatch):
    pro = object()
    monkeypatch.setattr(tushare_api, "_get_pro", lambda: pro)
    monkeypatch.setattr(tushare_api, "_sw_industry_cache", None)
    sleep_calls = []
    monkeypatch.setattr(time_module, "sleep", lambda seconds: sleep_calls.append(seconds))

    def fake_cached_call(_pro, api_name, **kwargs):
        if api_name == "index_classify":
            return pd.DataFrame(
                [
                    {"index_code": "801010.SI", "industry_name": "农林牧渔"},
                    {"index_code": "801020.SI", "industry_name": "采掘"},
                ]
            )
        if api_name == "index_member" and kwargs["index_code"] == "801010.SI":
            return pd.DataFrame([{"con_code": "000001.SZ", "out_date": None}])
        if api_name == "index_member" and kwargs["index_code"] == "801020.SI":
            return pd.DataFrame([{"con_code": "000002.SZ", "out_date": "20200101"}])
        raise AssertionError((api_name, kwargs))

    monkeypatch.setattr(tushare_api, "_cached_tushare_dataframe_call", fake_cached_call)

    result = tushare_api.get_sw_industry_classification()
    cached_result = tushare_api.get_sw_industry_classification()

    assert result == {"000001.SZ": "农林牧渔"}
    assert cached_result == {"000001.SZ": "农林牧渔"}
    assert sleep_calls == [0.35, 0.35]


def test_get_ashare_insider_trades_with_tushare_formats_signed_values(monkeypatch):
    pro = object()
    monkeypatch.setattr(tushare_api, "_get_pro", lambda: pro)
    monkeypatch.setattr(tushare_api, "_to_ts_code", lambda ticker: "000001.SZ")
    monkeypatch.setattr(
        tushare_api,
        "_cached_tushare_dataframe_call",
        lambda *_args, **_kwargs: pd.DataFrame(
            [
                {
                    "ann_date": "20260410",
                    "in_de": "DE",
                    "change_vol": 1000,
                    "avg_price": 10.5,
                    "after_share": 9000,
                    "holder_name": "股东甲",
                    "holder_type": "P",
                }
            ]
        ),
    )

    trades = tushare_api.get_ashare_insider_trades_with_tushare("000001", "2026-04-10", "2026-04-01", 5)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.filing_date == "2026-04-10"
    assert trade.transaction_shares == -1000.0
    assert trade.transaction_value == 10500.0
    assert trade.shares_owned_before_transaction == 10000.0
    assert trade.shares_owned_after_transaction == 9000.0


def test_get_ashare_line_items_with_tushare_builds_requested_fields(monkeypatch):
    pro = object()
    monkeypatch.setattr(tushare_api, "_get_pro", lambda: pro)
    monkeypatch.setattr(tushare_api, "_to_ts_code", lambda ticker: "000001.SZ")

    def fake_cached_call(_pro, api_name, ts_code, limit, dedupe=False):
        if api_name == "fina_indicator":
            return pd.DataFrame(
                [
                    {
                        "end_date": "20241231",
                        "grossprofit_margin": 25.0,
                        "eps": 1.2,
                        "bps": 5.6,
                        "debt_to_eqt": 0.4,
                        "op_of_gr": 12.0,
                    }
                ]
            )
        if api_name == "balancesheet":
            return pd.DataFrame(
                [
                    {
                        "end_date": "20241231",
                        "total_assets": 1000,
                        "total_liab": 400,
                        "total_hldr_eqy_exc_min_int": 600,
                        "total_share": 100,
                        "lt_borr": 50,
                        "st_borr": 30,
                        "bond_payable": 20,
                        "money_cap": 200,
                        "total_cur_assets": 300,
                        "total_cur_liab": 150,
                        "goodwill": 10,
                        "intan_assets": 5,
                    }
                ]
            )
        if api_name == "cashflow":
            return pd.DataFrame(
                [
                    {
                        "end_date": "20241231",
                        "n_cashflow_act": 120,
                        "c_pay_acq_const_fiolta": 20,
                        "depr_fa_coga_dpba": 15,
                        "c_pay_dist_dpcp_int_exp": 5,
                        "c_recp_cap_contrib": 2,
                    }
                ]
            )
        if api_name == "income":
            return pd.DataFrame(
                [
                    {
                        "end_date": "20241231",
                        "total_revenue": 500,
                        "revenue": 500,
                        "n_income_attr_p": 80,
                        "oper_cost": 300,
                        "total_profit": 100,
                        "operate_profit": 90,
                        "fin_exp_int_exp": 10,
                        "rd_exp": 12,
                    }
                ]
            )
        raise AssertionError(api_name)

    monkeypatch.setattr(tushare_api, "_cached_tushare_call", fake_cached_call)

    items = tushare_api.get_ashare_line_items_with_tushare(
        "000001",
        ["revenue", "gross_profit", "free_cash_flow", "working_capital", "gross_margin", "ebitda"],
        "2024-12-31",
        period="annual",
        limit=1,
    )

    assert len(items) == 1
    item = items[0]
    assert item.report_period == "20241231"
    assert item.revenue == 500.0
    assert item.gross_profit == 200.0
    assert item.free_cash_flow == 100.0
    assert item.working_capital == 150.0
    assert item.gross_margin == 0.25
    assert item.ebitda == 115.0


def test_get_ashare_financial_metrics_with_tushare_builds_ttm_metrics(monkeypatch):
    pro = object()
    daily_anchor_calls = []
    monkeypatch.setattr(tushare_api, "_get_pro", lambda: pro)
    monkeypatch.setattr(tushare_api, "_to_ts_code", lambda ticker: "000001.SZ")

    def fake_cached_call(_pro, api_name, ts_code, limit, dedupe=False):
        if api_name == "fina_indicator":
            return pd.DataFrame(
                [
                    {
                        "end_date": "20260331",
                        "netprofit_yoy": 30.0,
                        "or_yoy": 20.0,
                        "op_yoy": 10.0,
                        "grossprofit_margin": 25.0,
                        "roe": 12.0,
                        "roa": 8.0,
                        "debt_to_eqt": 0.45,
                        "debt_to_assets": 35.0,
                        "assets_turn": 1.5,
                        "current_ratio": 1.8,
                        "quick_ratio": 1.2,
                        "cash_ratio": 0.4,
                        "ar_turn": 8.0,
                        "basic_eps_yoy": 15.0,
                        "eps": 1.5,
                        "bps": 2.0,
                    },
                    {
                        "end_date": "20251231",
                        "netprofit_yoy": 18.0,
                        "or_yoy": 16.0,
                        "op_yoy": 9.0,
                        "grossprofit_margin": 24.0,
                        "roe": 11.0,
                        "roa": 7.0,
                        "debt_to_eqt": 0.4,
                        "debt_to_assets": 34.0,
                        "assets_turn": 1.4,
                        "current_ratio": 1.7,
                        "quick_ratio": 1.1,
                        "cash_ratio": 0.35,
                        "ar_turn": 7.5,
                        "basic_eps_yoy": 12.0,
                        "eps": 1.4,
                        "bps": 1.8,
                    },
                    {
                        "end_date": "20250331",
                        "netprofit_yoy": 12.0,
                        "or_yoy": 11.0,
                        "op_yoy": 8.0,
                        "grossprofit_margin": 23.0,
                        "roe": 10.0,
                        "roa": 6.5,
                        "debt_to_eqt": 0.38,
                        "debt_to_assets": 33.0,
                        "assets_turn": 1.3,
                        "current_ratio": 1.6,
                        "quick_ratio": 1.0,
                        "cash_ratio": 0.3,
                        "ar_turn": 7.0,
                        "basic_eps_yoy": 10.0,
                        "eps": 1.1,
                        "bps": 1.5,
                    },
                ]
            )
        if api_name == "cashflow":
            return pd.DataFrame(
                [
                    {"end_date": "20260331", "n_cashflow_act": 40.0, "c_pay_acq_const_fiolta": 10.0, "depr_fa_coga_dpba": None},
                    {"end_date": "20251231", "n_cashflow_act": 200.0, "c_pay_acq_const_fiolta": 50.0, "depr_fa_coga_dpba": 30.0},
                    {"end_date": "20250331", "n_cashflow_act": 20.0, "c_pay_acq_const_fiolta": 5.0, "depr_fa_coga_dpba": None},
                ]
            )
        if api_name == "balancesheet":
            return pd.DataFrame(
                [
                    {
                        "end_date": "20260331",
                        "lt_borr": 100.0,
                        "st_borr": 50.0,
                        "bond_payable": 20.0,
                        "money_cap": 80.0,
                        "total_share": 1000.0,
                        "total_assets": 1000.0,
                        "total_cur_liab": 200.0,
                        "total_hldr_eqy_exc_min_int": 500.0,
                    },
                    {
                        "end_date": "20251231",
                        "lt_borr": 90.0,
                        "st_borr": 45.0,
                        "bond_payable": 15.0,
                        "money_cap": 70.0,
                        "total_share": 1000.0,
                        "total_assets": 980.0,
                        "total_cur_liab": 190.0,
                        "total_hldr_eqy_exc_min_int": 480.0,
                    },
                    {
                        "end_date": "20250331",
                        "lt_borr": 80.0,
                        "st_borr": 40.0,
                        "bond_payable": 10.0,
                        "money_cap": 60.0,
                        "total_share": 1000.0,
                        "total_assets": 900.0,
                        "total_cur_liab": 180.0,
                        "total_hldr_eqy_exc_min_int": 420.0,
                    },
                ]
            )
        if api_name == "income":
            return pd.DataFrame(
                [
                    {
                        "end_date": "20260331",
                        "operate_profit": 30.0,
                        "total_revenue": 200.0,
                        "fin_exp": 5.0,
                        "int_exp": 4.0,
                        "n_income_attr_p": 20.0,
                    },
                    {
                        "end_date": "20251231",
                        "operate_profit": 150.0,
                        "total_revenue": 1000.0,
                        "fin_exp": 20.0,
                        "int_exp": 15.0,
                        "n_income_attr_p": 120.0,
                    },
                    {
                        "end_date": "20250331",
                        "operate_profit": 20.0,
                        "total_revenue": 100.0,
                        "fin_exp": 3.0,
                        "int_exp": 2.0,
                        "n_income_attr_p": 10.0,
                    },
                ]
            )
        raise AssertionError(api_name)

    def fake_cached_dataframe_call(_pro, api_name, **kwargs):
        assert api_name == "fina_indicator"
        return pd.DataFrame(
            [
                {"end_date": "20260331", "inv_turn": 4.0, "dp_dt_ratio": 30.0},
                {"end_date": "20251231", "inv_turn": 3.0, "dp_dt_ratio": 25.0},
                {"end_date": "20250331", "inv_turn": 2.5, "dp_dt_ratio": 20.0},
            ]
        )

    def fake_daily_basic(_pro, ts_code, anchor_date, lookback_days=30):
        daily_anchor_calls.append(anchor_date)
        return {
            "2026-04-10": {"total_mv": 100.0, "pe_ttm": 20.0, "pb": 2.0, "ps_ttm": 3.0},
            "20251231": {"total_mv": 90.0, "pe_ttm": 18.0, "pb": 1.8, "ps_ttm": 2.8},
            "20250331": {"total_mv": 80.0, "pe_ttm": 16.0, "pb": 1.6, "ps_ttm": 2.5},
        }[anchor_date]

    monkeypatch.setattr(tushare_api, "_cached_tushare_call", fake_cached_call)
    monkeypatch.setattr(tushare_api, "_cached_tushare_dataframe_call", fake_cached_dataframe_call)
    monkeypatch.setattr(tushare_api, "_get_latest_daily_basic", fake_daily_basic)

    metrics = tushare_api.get_ashare_financial_metrics_with_tushare("000001", "2026-04-10", limit=2, period="ttm")

    assert len(metrics) == 2
    latest = metrics[0]
    assert latest.report_period == "20260331"
    assert latest.period == "ttm"
    assert latest.market_cap == 1_000_000.0
    assert latest.free_cash_flow_yield == 165.0 / 1_000_000.0
    assert latest.free_cash_flow_per_share == 0.165
    assert latest.free_cash_flow_growth == 0.1
    assert latest.operating_margin == 160.0 / 1100.0
    assert latest.net_margin == 130.0 / 1100.0
    assert latest.return_on_equity == 130.0 / 500.0
    assert latest.return_on_invested_capital == 0.15
    assert latest.enterprise_value == 1_000_090.0
    assert round(latest.enterprise_value_to_ebitda_ratio, 6) == round(1_000_090.0 / 212.0, 6)
    assert round(latest.interest_coverage, 6) == round(182.0 / 17.0, 6)
    assert latest.inventory_turnover == 4.0
    assert latest.days_sales_outstanding == 365.0 / 8.0
    assert latest.payout_ratio == 0.3
    assert latest.book_value_growth == (2.0 - 1.8) / 1.8
    assert daily_anchor_calls == ["2026-04-10", "20251231", "20250331"]


def test_get_ashare_financial_metrics_with_tushare_annual_filters_to_1231(monkeypatch):
    pro = object()
    monkeypatch.setattr(tushare_api, "_get_pro", lambda: pro)
    monkeypatch.setattr(tushare_api, "_to_ts_code", lambda ticker: "000001.SZ")
    monkeypatch.setattr(
        tushare_api,
        "_cached_tushare_call",
        lambda *_args, **_kwargs: pd.DataFrame(
            [
                {
                    "end_date": "20260331",
                    "netprofit_yoy": 30.0,
                    "or_yoy": 20.0,
                    "op_yoy": 10.0,
                    "grossprofit_margin": 25.0,
                    "roe": 12.0,
                    "roa": 8.0,
                    "debt_to_eqt": 0.45,
                    "debt_to_assets": 35.0,
                    "assets_turn": 1.5,
                    "current_ratio": 1.8,
                    "quick_ratio": 1.2,
                    "cash_ratio": 0.4,
                    "ar_turn": 8.0,
                    "basic_eps_yoy": 15.0,
                    "eps": 1.5,
                    "bps": 2.0,
                },
                {
                    "end_date": "20251231",
                    "netprofit_yoy": 18.0,
                    "or_yoy": 16.0,
                    "op_yoy": 9.0,
                    "grossprofit_margin": 24.0,
                    "roe": 11.0,
                    "roa": 7.0,
                    "debt_to_eqt": 0.4,
                    "debt_to_assets": 34.0,
                    "assets_turn": 1.4,
                    "current_ratio": 1.7,
                    "quick_ratio": 1.1,
                    "cash_ratio": 0.35,
                    "ar_turn": 7.5,
                    "basic_eps_yoy": 12.0,
                    "eps": 1.4,
                    "bps": 1.8,
                    "inv_turn": 3.0,
                    "dp_dt_ratio": 25.0,
                },
            ]
        ),
    )
    monkeypatch.setattr(tushare_api, "_cached_tushare_dataframe_call", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(tushare_api, "_get_latest_daily_basic", lambda *_args, **_kwargs: {"total_mv": 90.0, "pe_ttm": 18.0, "pb": 1.8, "ps_ttm": 2.8})

    metrics = tushare_api.get_ashare_financial_metrics_with_tushare("000001", "2026-04-10", limit=1, period="annual")

    assert len(metrics) == 1
    assert metrics[0].report_period == "20251231"
    assert metrics[0].period == "annual"
