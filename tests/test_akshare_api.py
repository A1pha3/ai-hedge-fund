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
