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
