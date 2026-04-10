from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.data.base_provider import DataResponse
from src.data.router import DataRouter


class _CacheStub:
    def __init__(self, *, prices=None, metrics=None):
        self._prices = prices
        self._metrics = metrics
        self.saved_prices: list[tuple[str, list[dict]]] = []
        self.saved_metrics: list[tuple[str, list[dict]]] = []

    def get_prices(self, key):
        return self._prices

    def get_financial_metrics(self, key):
        return self._metrics

    def get_company_news(self, key):
        return None

    def get_insider_trades(self, key):
        return None

    def set_prices(self, key, data):
        self.saved_prices.append((key, data))

    def set_financial_metrics(self, key, data):
        self.saved_metrics.append((key, data))

    def set_company_news(self, key, data):
        pass

    def set_insider_trades(self, key, data):
        pass


class _Provider:
    def __init__(self, name: str, *, price_response=None, metrics_response=None):
        self.name = name
        self.priority = 1
        self._price_response = price_response
        self._metrics_response = metrics_response

    async def health_check(self) -> bool:
        return True

    async def get_prices(self, ticker: str, start_date: str, end_date: str):
        if isinstance(self._price_response, Exception):
            raise self._price_response
        return self._price_response

    async def get_financial_metrics(self, ticker: str, end_date: str):
        if isinstance(self._metrics_response, Exception):
            raise self._metrics_response
        return self._metrics_response


def test_get_prices_returns_cached_response():
    router = DataRouter([])
    router.cache = _CacheStub(prices=[{"time": "2024-01-01", "open": 1}])

    result = asyncio.run(router.get_prices("AAPL", "2024-01-01", "2024-01-02"))

    assert result.data == [{"time": "2024-01-01", "open": 1}]
    assert result.source == "cache"
    assert result.cached is True


def test_get_prices_falls_back_to_healthy_provider_and_caches_serialized_rows():
    router = DataRouter(
        [
            _Provider("bad", price_response=DataResponse(data=[], source="bad", error="bad prices")),
            _Provider("good", price_response=DataResponse(data=[SimpleNamespace(model_dump=lambda: {"close": 10})], source="good", latency_ms=5)),
        ]
    )
    router.cache = _CacheStub()
    router._health_cache = {"bad": True, "good": True}
    router._last_health_check = __import__("datetime").datetime.now()

    result = asyncio.run(router.get_prices("AAPL", "2024-01-01", "2024-01-02"))

    assert result.source == "good"
    assert result.latency_ms == 5
    assert router.cache.saved_prices == [
        ("price_AAPL_end=2024-01-02_start=2024-01-01", [{"close": 10}])
    ]


def test_get_financial_metrics_applies_limit_and_caches_trimmed_rows():
    router = DataRouter(
        [
            _Provider(
                "bad",
                metrics_response=DataResponse(data=[], source="bad", error="bad metrics"),
            ),
            _Provider(
                "good",
                metrics_response=DataResponse(
                    data=[SimpleNamespace(model_dump=lambda: {"ticker": "AAPL"}), {"ticker": "MSFT"}],
                    source="good",
                    latency_ms=7,
                ),
            ),
        ]
    )
    router.cache = _CacheStub()
    router._health_cache = {"bad": True, "good": True}
    router._last_health_check = __import__("datetime").datetime.now()

    result = asyncio.run(router.get_financial_metrics("AAPL", "2024-01-02", limit=1))

    assert result.data == [result.data[0]]
    assert result.source == "good"
    assert result.latency_ms == 7
    assert router.cache.saved_metrics == [
        ("fundamental_AAPL_end=2024-01-02_limit=1", [{"ticker": "AAPL"}])
    ]


def test_get_financial_metrics_returns_router_error_when_all_providers_fail():
    router = DataRouter([_Provider("boom", metrics_response=Exception("kapow"))])
    router.cache = _CacheStub()
    router._health_cache = {"boom": True}
    router._last_health_check = __import__("datetime").datetime.now()

    result = asyncio.run(router.get_financial_metrics("AAPL", "2024-01-02", use_cache=False))

    assert result.data == []
    assert result.source == "router"
    assert result.error == "All providers failed. Last error: kapow"
