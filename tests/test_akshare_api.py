from __future__ import annotations

import time
from types import SimpleNamespace

import pandas as pd
import pytest

import src.tools.akshare_api as akshare_api


class _DummyPersistentCache:
    def get(self, _key):
        return None

    def set(self, _key, _value, ttl=None):
        return None


class _DummyPriceCache:
    def __init__(self, cached=None):
        self.cached = cached
        self.saved = None

    def get_prices(self, _key):
        return self.cached

    def set_prices(self, _key, value):
        self.saved = value


class _DummyFinancialCache:
    def __init__(self, cached=None):
        self.cached = cached
        self.saved = None

    def get_financial_metrics(self, _key):
        return self.cached

    def set_financial_metrics(self, _key, value):
        self.saved = value


def test_cached_akshare_dataframe_call_times_out_for_stock_news(monkeypatch):
    monkeypatch.setattr(akshare_api, "_persistent_cache", _DummyPersistentCache())
    monkeypatch.setattr(akshare_api, "AKSHARE_STOCK_NEWS_TIMEOUT_SECONDS", 0.01)

    def _slow_news(**_kwargs):
        time.sleep(0.05)
        return pd.DataFrame([{"新闻标题": "x"}])

    with pytest.raises(TimeoutError, match="stock_news_em"):
        akshare_api._cached_akshare_dataframe_call("stock_news_em", _slow_news, symbol="300438")


def test_get_ashare_company_news_returns_empty_when_stock_news_times_out(monkeypatch):
    monkeypatch.setattr(akshare_api, "_persistent_cache", _DummyPersistentCache())
    monkeypatch.setattr(akshare_api, "_akshare_available", True)
    monkeypatch.setattr(akshare_api, "AKSHARE_STOCK_NEWS_TIMEOUT_SECONDS", 0.01)

    def _slow_news(**_kwargs):
        time.sleep(0.05)
        return pd.DataFrame(
            [
                {
                    "发布时间": "2026-03-30 09:30:00",
                    "新闻标题": "测试新闻",
                    "新闻内容": "测试内容",
                    "文章来源": "测试来源",
                    "新闻链接": "https://example.com",
                }
            ]
        )

    monkeypatch.setattr(akshare_api, "ak", SimpleNamespace(stock_news_em=_slow_news))

    news = akshare_api.get_ashare_company_news("300438", "2026-03-30")

    assert news == []


def test_get_prices_returns_mock_data_when_requested(monkeypatch):
    sentinel = [akshare_api.Price(time="2026-04-01", open=1, high=1, low=1, close=1, volume=1)]
    monkeypatch.setattr(akshare_api, "_cache", _DummyPriceCache())
    monkeypatch.setattr(akshare_api, "get_mock_prices", lambda *args, **kwargs: sentinel)

    result = akshare_api.get_prices("000001", "2026-04-01", "2026-04-02", use_mock=True)

    assert result is sentinel


def test_get_realtime_quote_sina_maps_response_fields(monkeypatch):
    class _Response:
        status_code = 200
        text = 'var hq_str_sz000001="平安银行,10.00,9.90,10.10,10.20,9.80,10.09,10.10,12345,67890,1,10.09,2,10.08,3,10.07,4,10.06,5,10.05,1,10.10,2,10.11,3,10.12,4,10.13,5,10.14,2026-04-11,15:00:00,00";'

    class _Session:
        def get(self, url, headers, timeout):
            assert url == "https://hq.sinajs.cn/list=sz000001"
            assert timeout == 30
            assert headers == akshare_api.SINA_QUOTE_HEADERS
            return _Response()

    monkeypatch.setattr(
        akshare_api.AShareTicker,
        "from_symbol",
        classmethod(lambda cls, symbol: SimpleNamespace(symbol=symbol, full_code="sz000001")),
    )
    monkeypatch.setattr(akshare_api, "_create_session", lambda: _Session())

    quote = akshare_api.get_realtime_quote_sina("000001")

    assert quote["name"] == "平安银行"
    assert quote["current"] == 10.10
    assert quote["volume"] == 12345
    assert quote["date"] == "2026-04-11"


def test_get_realtime_quote_sina_wraps_unexpected_errors(monkeypatch):
    monkeypatch.setattr(
        akshare_api.AShareTicker,
        "from_symbol",
        classmethod(lambda cls, symbol: (_ for _ in ()).throw(RuntimeError("bad ticker"))),
    )

    with pytest.raises(akshare_api.AShareDataError, match="获取新浪实时行情失败: bad ticker"):
        akshare_api.get_realtime_quote_sina("000001")


def test_get_prices_uses_akshare_dataframe_and_caches(monkeypatch):
    cache = _DummyPriceCache()
    monkeypatch.setattr(akshare_api, "_cache", cache)
    monkeypatch.setattr(akshare_api, "_get_akshare", lambda: SimpleNamespace(stock_zh_a_hist=object()))
    monkeypatch.setattr(akshare_api.AShareTicker, "from_symbol", classmethod(lambda cls, symbol: SimpleNamespace(symbol=symbol)))
    monkeypatch.setattr(akshare_api, "_disable_system_proxies", lambda: {"HTTP_PROXY": "x"})
    restored = {}
    monkeypatch.setattr(akshare_api, "_restore_proxies", lambda saved: restored.update(saved))
    monkeypatch.setattr(
        akshare_api,
        "_cached_akshare_dataframe_call",
        lambda *args, **kwargs: pd.DataFrame(
            [{"日期": "2026-04-01", "开盘": 10.0, "最高": 11.0, "最低": 9.5, "收盘": 10.8, "成交量": 12345}]
        ),
    )

    prices = akshare_api.get_prices("000001", "2026-04-01", "2026-04-02")

    assert [(price.time, price.close, price.volume) for price in prices] == [("2026-04-01", 10.8, 12345)]
    assert cache.saved == [price.model_dump() for price in prices]
    assert restored == {"HTTP_PROXY": "x"}


def test_get_prices_falls_back_to_tencent_when_akshare_fails(monkeypatch):
    cache = _DummyPriceCache()
    sentinel = [akshare_api.Price(time="2026-04-02", open=20, high=21, low=19, close=20.5, volume=888)]
    monkeypatch.setattr(akshare_api, "_cache", cache)
    monkeypatch.setattr(akshare_api, "_get_akshare", lambda: SimpleNamespace(stock_zh_a_hist=object()))
    monkeypatch.setattr(akshare_api.AShareTicker, "from_symbol", classmethod(lambda cls, symbol: SimpleNamespace(symbol=symbol)))
    monkeypatch.setattr(akshare_api, "_disable_system_proxies", lambda: {})
    monkeypatch.setattr(akshare_api, "_restore_proxies", lambda saved: None)
    monkeypatch.setattr(akshare_api, "_cached_akshare_dataframe_call", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(akshare_api, "_get_prices_from_tencent", lambda *args, **kwargs: sentinel)

    prices = akshare_api.get_prices("000001", "2026-04-01", "2026-04-02")

    assert prices is sentinel
    assert cache.saved == [price.model_dump() for price in sentinel]


def test_get_financial_metrics_uses_analysis_indicator_and_caches(monkeypatch):
    cache = _DummyFinancialCache()
    monkeypatch.setattr(akshare_api, "_cache", cache)
    monkeypatch.setattr(
        akshare_api,
        "_get_akshare",
        lambda: SimpleNamespace(
            stock_financial_analysis_indicator=object(),
            stock_financial_report_sina=object(),
        ),
    )
    monkeypatch.setattr(
        akshare_api.AShareTicker,
        "from_symbol",
        classmethod(lambda cls, symbol: SimpleNamespace(symbol=symbol)),
    )
    monkeypatch.setattr(
        akshare_api,
        "_cached_akshare_dataframe_call",
        lambda api_name, *_args, **_kwargs: pd.DataFrame(
            [{"报告期": "2026Q1", "市盈率": 15.2, "市净率": 2.3, "净资产收益率": 12.5, "资产负债率": 34.0}]
        )
        if api_name == "stock_financial_analysis_indicator"
        else pytest.fail(f"unexpected api call: {api_name}"),
    )

    metrics = akshare_api.get_financial_metrics("000001", "2026-04-02", limit=1)

    assert len(metrics) == 1
    assert metrics[0].report_period == "2026Q1"
    assert metrics[0].price_to_earnings_ratio == 15.2
    assert metrics[0].return_on_equity == pytest.approx(0.125)
    assert metrics[0].debt_to_equity == pytest.approx(0.34)
    assert cache.saved == [metric.model_dump() for metric in metrics]


def test_get_financial_metrics_falls_back_to_sina_profit_when_indicator_empty(monkeypatch):
    cache = _DummyFinancialCache()
    monkeypatch.setattr(akshare_api, "_cache", cache)
    monkeypatch.setattr(
        akshare_api,
        "_get_akshare",
        lambda: SimpleNamespace(
            stock_financial_analysis_indicator=object(),
            stock_financial_report_sina=object(),
        ),
    )
    monkeypatch.setattr(
        akshare_api.AShareTicker,
        "from_symbol",
        classmethod(lambda cls, symbol: SimpleNamespace(symbol=symbol)),
    )

    def _fake_cached_call(api_name, *_args, **_kwargs):
        if api_name == "stock_financial_analysis_indicator":
            return pd.DataFrame()
        if api_name == "stock_financial_report_sina":
            return pd.DataFrame([{"报告日": "2026-03-31", "营业收入": 100.0, "净利润": 12.0}])
        pytest.fail(f"unexpected api call: {api_name}")

    monkeypatch.setattr(akshare_api, "_cached_akshare_dataframe_call", _fake_cached_call)

    metrics = akshare_api.get_financial_metrics("000001", "2026-04-02", limit=1)

    assert len(metrics) == 1
    assert metrics[0].report_period == "2026-03-31"
    assert metrics[0].price_to_earnings_ratio is None
    assert cache.saved == [metric.model_dump() for metric in metrics]


def test_get_financial_metrics_returns_mock_data_when_requested(monkeypatch):
    sentinel = [object()]
    monkeypatch.setattr(akshare_api, "_cache", _DummyFinancialCache())
    monkeypatch.setattr(akshare_api, "get_mock_financial_metrics", lambda *args, **kwargs: sentinel)

    result = akshare_api.get_financial_metrics("000001", "2026-04-02", limit=1, use_mock=True)

    assert result is sentinel


def test_get_stock_info_maps_rows_to_dict(monkeypatch):
    monkeypatch.setattr(akshare_api, "_get_akshare", lambda: SimpleNamespace(stock_individual_info_em=lambda symbol: pd.DataFrame([{"item": "股票简称", "value": "平安银行"}, {"item": "行业", "value": "银行"}])))
    monkeypatch.setattr(
        akshare_api.AShareTicker,
        "from_symbol",
        classmethod(lambda cls, symbol: SimpleNamespace(symbol=symbol)),
    )

    info = akshare_api.get_stock_info("000001")

    assert info == {"股票简称": "平安银行", "行业": "银行"}


def test_get_stock_info_raises_when_dataframe_empty(monkeypatch):
    monkeypatch.setattr(akshare_api, "_get_akshare", lambda: SimpleNamespace(stock_individual_info_em=lambda symbol: pd.DataFrame()))
    monkeypatch.setattr(
        akshare_api.AShareTicker,
        "from_symbol",
        classmethod(lambda cls, symbol: SimpleNamespace(symbol=symbol)),
    )

    with pytest.raises(akshare_api.AShareDataError, match="返回空数据"):
        akshare_api.get_stock_info("000001")


def test_search_stocks_filters_keyword_and_maps_rows(monkeypatch):
    monkeypatch.setattr(
        akshare_api,
        "_get_akshare",
        lambda: SimpleNamespace(
            stock_zh_a_spot_em=lambda: pd.DataFrame(
                [
                    {"代码": "000001", "名称": "平安银行", "最新价": 10.5, "涨跌幅": 1.2},
                    {"代码": "600036", "名称": "招商银行", "最新价": 42.1, "涨跌幅": -0.3},
                ]
            )
        ),
    )

    results = akshare_api.search_stocks("平安")

    assert results == [{"symbol": "000001", "name": "平安银行", "price": 10.5, "change": 1.2}]


def test_search_stocks_wraps_search_errors(monkeypatch):
    monkeypatch.setattr(
        akshare_api,
        "_get_akshare",
        lambda: SimpleNamespace(stock_zh_a_spot_em=lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    with pytest.raises(akshare_api.AShareDataError, match="搜索 A 股失败"):
        akshare_api.search_stocks("平安")


def test_get_mock_financial_metrics_rolls_back_quarters():
    metrics = akshare_api.get_mock_financial_metrics("000001", "2026-04-02", limit=3)

    assert [metric.report_period for metric in metrics] == ["2026Q2", "2026Q1", "2025Q4"]
    assert all(metric.ticker == "000001" for metric in metrics)


def test_get_mock_financial_metrics_returns_requested_limit():
    metrics = akshare_api.get_mock_financial_metrics("000001", "2026-12-31", limit=2)

    assert len(metrics) == 2
    assert all(metric.period == "quarterly" for metric in metrics)


def test_get_mock_prices_skips_weekends():
    prices = akshare_api.get_mock_prices("000001", "2026-04-03", "2026-04-06")

    assert [price.time for price in prices] == ["2026-04-03", "2026-04-06"]


def test_get_mock_prices_returns_requested_date_window_shape():
    prices = akshare_api.get_mock_prices("000001", "2026-04-06", "2026-04-08")

    assert len(prices) == 3
    assert all(price.volume >= 1_000_000 for price in prices)


def test_get_prices_from_tencent_maps_payload_to_prices(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "data": {
                    "sz000001": {
                        "qfqday": [
                            ["2026-04-03", "10.0", "10.8", "11.0", "9.8", "12345"],
                        ]
                    }
                },
            }

    class _Session:
        def get(self, url, params, headers, timeout):
            captured.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
            return _Response()

    monkeypatch.setattr(
        akshare_api.AShareTicker,
        "from_symbol",
        classmethod(lambda cls, symbol: SimpleNamespace(symbol=symbol, full_code="sz000001")),
    )
    monkeypatch.setattr(akshare_api, "_create_session", lambda: _Session())

    prices = akshare_api._get_prices_from_tencent("000001", "2026-04-03", "2026-04-06")

    assert [(price.time, price.open, price.close, price.volume) for price in prices] == [("2026-04-03", 10.0, 10.8, 12345)]
    assert captured["params"]["param"] == "sz000001,day,2026-04-03,2026-04-06,640,qfq"
    assert captured["timeout"] == 30


def test_get_prices_from_tencent_raises_when_payload_has_no_prices(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "data": {"sz000001": {"qfqday": []}}}

    class _Session:
        def get(self, *_args, **_kwargs):
            return _Response()

    monkeypatch.setattr(
        akshare_api.AShareTicker,
        "from_symbol",
        classmethod(lambda cls, symbol: SimpleNamespace(symbol=symbol, full_code="sz000001")),
    )
    monkeypatch.setattr(akshare_api, "_create_session", lambda: _Session())

    with pytest.raises(akshare_api.AShareDataError, match="腾讯接口返回空数据"):
        akshare_api._get_prices_from_tencent("000001", "2026-04-03", "2026-04-06")


def test_get_realtime_quotes_filters_requested_tickers(monkeypatch):
    monkeypatch.setattr(akshare_api, "_akshare_available", True)
    monkeypatch.setattr(
        akshare_api,
        "ak",
        SimpleNamespace(
            stock_zh_a_spot_em=lambda: pd.DataFrame(
                [
                    {"代码": "000001", "名称": "平安银行"},
                    {"代码": "600036", "名称": "招商银行"},
                ]
            )
        ),
    )

    result = akshare_api.get_realtime_quotes(["600036"])

    assert list(result["代码"]) == ["600036"]


def test_get_industry_realtime_returns_none_on_errors(monkeypatch):
    monkeypatch.setattr(akshare_api, "_akshare_available", True)
    monkeypatch.setattr(
        akshare_api,
        "ak",
        SimpleNamespace(stock_board_industry_name_em=lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    assert akshare_api.get_industry_realtime() is None


def test_get_money_flow_uses_exchange_market(monkeypatch):
    monkeypatch.setattr(akshare_api, "_akshare_available", True)
    captured = {}

    def _stock_individual_fund_flow(*, stock, market):
        captured.update({"stock": stock, "market": market})
        return pd.DataFrame([{"日期": "2026-04-03", "主力净流入": 1.0}])

    monkeypatch.setattr(akshare_api, "ak", SimpleNamespace(stock_individual_fund_flow=_stock_individual_fund_flow))

    result = akshare_api.get_money_flow("600036")

    assert result is not None
    assert captured == {"stock": "600036", "market": "sh"}


def test_get_sina_historical_data_reuses_mock_price_window(monkeypatch):
    monkeypatch.setattr(
        akshare_api.AShareTicker,
        "from_symbol",
        classmethod(lambda cls, symbol: SimpleNamespace(symbol=symbol)),
    )
    monkeypatch.setattr(akshare_api, "_create_session", lambda: object())

    prices = akshare_api.get_sina_historical_data("000001", "2026-04-03", "2026-04-06")

    assert [price.time for price in prices] == ["2026-04-03", "2026-04-06"]


def test_get_sina_historical_data_wraps_errors(monkeypatch):
    monkeypatch.setattr(
        akshare_api.AShareTicker,
        "from_symbol",
        classmethod(lambda cls, symbol: (_ for _ in ()).throw(RuntimeError("bad ticker"))),
    )

    with pytest.raises(akshare_api.AShareDataError, match="获取新浪历史数据失败"):
        akshare_api.get_sina_historical_data("000001", "2026-04-03", "2026-04-06")


def test_get_prices_robust_falls_back_to_mock_when_all_sources_fail(monkeypatch):
    monkeypatch.setattr(akshare_api, "get_prices", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("akshare fail")))
    monkeypatch.setattr(akshare_api, "get_sina_historical_data", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("sina fail")))
    monkeypatch.setattr("src.tools.ashare_data_sources.get_prices_multi_source", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("multi fail")))
    sentinel = [akshare_api.Price(time="2026-04-03", open=1, high=1, low=1, close=1, volume=1)]
    monkeypatch.setattr(akshare_api, "get_mock_prices", lambda *args, **kwargs: sentinel)

    result = akshare_api.get_prices_robust("000001", "2026-04-03", "2026-04-06")

    assert result is sentinel


def test_get_prices_robust_raises_when_all_sources_fail_and_mock_disabled(monkeypatch):
    monkeypatch.setattr(akshare_api, "get_prices", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("akshare fail")))
    monkeypatch.setattr(akshare_api, "get_sina_historical_data", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("sina fail")))
    monkeypatch.setattr("src.tools.ashare_data_sources.get_prices_multi_source", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("multi fail")))

    with pytest.raises(akshare_api.AShareDataError, match="所有数据源都失败"):
        akshare_api.get_prices_robust("000001", "2026-04-03", "2026-04-06", use_mock_on_fail=False)


def test_get_ashare_company_news_sorts_filters_and_deduplicates(monkeypatch, capsys):
    monkeypatch.setattr(akshare_api, "_akshare_available", True)
    monkeypatch.setattr(
        akshare_api,
        "_cached_akshare_dataframe_call",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "发布时间": "2026-03-30 08:00:00",
                    "新闻标题": "旧新闻",
                    "新闻内容": "旧内容",
                    "文章来源": "来源A",
                    "新闻链接": "https://example.com/old",
                },
                {
                    "发布时间": "2026-03-30 09:30:00",
                    "新闻标题": "新新闻",
                    "新闻内容": "新内容",
                    "文章来源": "来源B",
                    "新闻链接": "https://example.com/new",
                },
                {
                    "发布时间": "2026-03-30 10:00:00",
                    "新闻标题": "无关市场快讯",
                    "新闻内容": "无关内容",
                    "文章来源": "来源C",
                    "新闻链接": "https://example.com/skip",
                },
            ]
        ),
    )
    monkeypatch.setattr(akshare_api, "ak", SimpleNamespace(stock_news_em=object()))
    monkeypatch.setattr(akshare_api, "_is_news_relevant_to_stock", lambda title, *_args: title != "无关市场快讯")
    monkeypatch.setattr(akshare_api, "_classify_news_sentiment", lambda title, content: "正面" if "新" in title else "中性")
    monkeypatch.setattr(akshare_api, "_deduplicate_news", lambda results: results[:1])

    import sys
    module = SimpleNamespace(get_stock_name=lambda ticker: "测试股")
    monkeypatch.setitem(sys.modules, "src.tools.tushare_api", module)

    news = akshare_api.get_ashare_company_news("300438", "2026-03-30", start_date="2026-03-30", limit=5)

    assert len(news) == 1
    assert news[0].title == "新新闻"
    assert news[0].sentiment == "正面"
    assert "[AKShare] 已过滤 1 篇与 300438(测试股) 无直接关联的通用市场文章" in capsys.readouterr().out
