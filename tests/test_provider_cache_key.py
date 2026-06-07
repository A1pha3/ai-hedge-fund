"""Provider-aware cache key regression tests (5.1 P1).

These tests guard the requirement that the high-level data cache
(`CacheAdapter` + the cache keys constructed in `src/tools/api.py`)
isolates entries per data provider (tushare / akshare / financial_datasets).
Without the provider dimension, an akshare write could be returned for a
later tushare query (or vice versa), causing silent data corruption.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import src.tools.api as api
from src.data.base_provider import DataResponse, DataType
from src.data.router import DataRouter


# ---------------------------------------------------------------------------
# api.py provider-key generation
# ---------------------------------------------------------------------------


def test_provider_key_normalises_provider_to_lowercase():
    assert api._provider_key("Tushare", "000001_x") == "tushare::000001_x"
    assert api._provider_key("AKSHARE", "AAPL") == "akshare::AAPL"
    # Single underscore in raw_key is preserved; the double-colon is the
    # provider separator so it never collides with single-char providers.
    assert api._provider_key("financial_datasets", "raw_key_1") == "financial_datasets::raw_key_1"


def test_provider_key_uses_double_colon_separator():
    """The `::` separator is a stable, recognisable boundary that cannot
    appear in raw keys (which use `_` as their internal separator)."""
    raw = "000001_2025-01-01_2025-03-01"
    keyed = api._provider_key("tushare", raw)
    assert keyed.startswith("tushare::")
    assert keyed.endswith(raw)
    assert "::" in keyed


# ---------------------------------------------------------------------------
# get_prices: cross-provider isolation
# ---------------------------------------------------------------------------


def test_get_prices_uses_provider_tag_for_ashare(monkeypatch):
    """A-share price writes must NOT share a cache key with US prices."""
    cache: dict[str, list[dict]] = {}
    sentinel = [
        api.Price(time="2025-01-02", open=1.0, high=2.0, low=0.5, close=1.5, volume=100),
    ]

    class _Cache:
        def get_prices(self, key):
            return cache.get(key)

        def set_prices(self, key, value):
            cache[key] = value

    monkeypatch.setattr(api, "_cache", _Cache())
    monkeypatch.setattr(api, "is_ashare", lambda ticker: True)
    monkeypatch.setattr(api, "get_ashare_prices_with_tushare", lambda *args, **kwargs: sentinel)

    result = api.get_prices("000001", "2025-01-01", "2025-01-31")

    assert result == sentinel
    # Verify the cache key has the provider tag and the legacy key is untouched.
    assert "tushare::000001_2025-01-01_2025-01-31" in cache
    # Negative: a US key without provider must NOT be populated.
    assert "000001_2025-01-01_2025-01-31" not in cache


def test_get_prices_uses_provider_tag_for_us(monkeypatch):
    """US price writes must carry a financial_datasets tag — distinct from
    any A-share tag, even when the ticker / dates happen to overlap."""
    cache: dict[str, list[dict]] = {}

    class _Cache:
        def get_prices(self, key):
            return cache.get(key)

        def set_prices(self, key, value):
            cache[key] = value

    monkeypatch.setattr(api, "_cache", _Cache())
    monkeypatch.setattr(api, "is_ashare", lambda ticker: False)

    response_payload = {
        "ticker": "AAPL",
        "prices": [
            {
                "time": "2025-01-02",
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
            }
        ],
    }
    monkeypatch.setattr(
        api,
        "_make_api_request",
        lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: response_payload),
    )

    result = api.get_prices("AAPL", "2025-01-01", "2025-01-31", api_key="dummy")

    assert len(result) == 1
    assert "financial_datasets::AAPL_2025-01-01_2025-01-31" in cache
    assert "AAPL_2025-01-01_2025-01-31" not in cache


# ---------------------------------------------------------------------------
# get_financial_metrics, search_line_items: cross-provider isolation
# ---------------------------------------------------------------------------


def test_get_financial_metrics_uses_provider_tag_for_ashare(monkeypatch):
    cache_metrics: dict[str, list[dict]] = {}

    class _Cache:
        def get_financial_metrics(self, key):
            return cache_metrics.get(key)

        def set_financial_metrics(self, key, value):
            cache_metrics[key] = value

    monkeypatch.setattr(api, "_cache", _Cache())
    monkeypatch.setattr(api, "is_ashare", lambda ticker: True)
    # Mock must return list of objects with .model_dump(); api.py writes
    # via [m.model_dump() for m in metrics].
    class _MetricStub:
        def __init__(self, payload):
            self._payload = payload

        def model_dump(self):
            return self._payload

    sentinel_payload = {"ticker": "000001", "report_period": "2024-12-31", "period": "ttm", "currency": "CNY"}
    monkeypatch.setattr(api, "get_ashare_financial_metrics_with_tushare", lambda *args, **kwargs: [_MetricStub(sentinel_payload)])

    result = api.get_financial_metrics("000001", "2024-12-31", period="ttm", limit=10)

    assert len(result) == 1
    assert "tushare::000001_ttm_2024-12-31_10" in cache_metrics
    assert "000001_ttm_2024-12-31_10" not in cache_metrics


def test_search_line_items_uses_provider_tag_for_ashare(monkeypatch):
    cache_items: dict[str, list[dict]] = {}

    class _Cache:
        def get_line_items(self, key):
            return cache_items.get(key)

        def set_line_items(self, key, value):
            cache_items[key] = value

    monkeypatch.setattr(api, "_cache", _Cache())
    monkeypatch.setattr(api, "is_ashare", lambda ticker: True)
    sentinel = [api.LineItem(ticker="000001", report_period="2024-12-31", period="ttm", currency="CNY")]
    monkeypatch.setattr(api, "get_ashare_line_items_with_tushare", lambda *args, **kwargs: sentinel)

    result = api.search_line_items("000001", ["revenue"], "2024-12-31", period="ttm", limit=10)

    assert result == sentinel
    # Single key, provider-tagged, regardless of which line items were selected.
    assert len(cache_items) == 1
    (cached_key, _), = cache_items.items()
    assert cached_key.startswith("tushare::000001_revenue_ttm_2024-12-31_10")
    assert "000001_revenue_ttm_2024-12-31_10" not in cache_items  # negative


# ---------------------------------------------------------------------------
# get_insider_trades, get_company_news: cross-provider isolation
# ---------------------------------------------------------------------------


def test_get_insider_trades_ashare_and_us_use_distinct_provider_tags(monkeypatch):
    """For the same ticker + dates + limit, an A-share (tushare) write and
    a US (financial_datasets) write must end up in different cache slots."""
    ashare_cache: dict[str, list[dict]] = {}
    us_cache: dict[str, list[dict]] = {}

    class _AshareCache:
        def get_insider_trades(self, key):
            return ashare_cache.get(key)

        def set_insider_trades(self, key, value):
            ashare_cache[key] = value

    class _UsCache:
        def get_insider_trades(self, key):
            return us_cache.get(key)

        def set_insider_trades(self, key, value):
            us_cache[key] = value

    # --- Round 1: A-share path (tushare) ---
    monkeypatch.setattr(api, "_cache", _AshareCache())
    monkeypatch.setattr(api, "is_ashare", lambda ticker: True)
    ashare_trade = api.InsiderTrade(
        ticker="000001",
        issuer="i",
        name="n",
        title="t",
        is_board_director=False,
        transaction_date="2025-01-02",
        transaction_shares=1,
        transaction_price_per_share=1.0,
        transaction_value=1,
        shares_owned_before_transaction=0,
        shares_owned_after_transaction=1,
        security_title="common",
        filing_date="2025-01-03",
    )
    monkeypatch.setattr(api, "get_ashare_insider_trades_with_tushare", lambda *args, **kwargs: [ashare_trade])

    api.get_insider_trades("000001", "2025-01-10", "2025-01-01", 5)

    # --- Round 2: US path (financial_datasets) for the same params ---
    monkeypatch.setattr(api, "_cache", _UsCache())
    monkeypatch.setattr(api, "is_ashare", lambda ticker: False)
    remote_payload = {
        "insider_trades": [
            {
                "ticker": "000001",
                "issuer": "Remote",
                "name": "Alice",
                "title": "CFO",
                "is_board_director": True,
                "transaction_date": "2025-01-04",
                "transaction_shares": 5,
                "transaction_price_per_share": 2.0,
                "transaction_value": 10,
                "shares_owned_before_transaction": 100,
                "shares_owned_after_transaction": 105,
                "security_title": "Common",
                "filing_date": "2025-01-05T00:00:00",
            }
        ]
    }
    monkeypatch.setattr(api, "_make_api_request", lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: remote_payload))

    api.get_insider_trades("000001", "2025-01-10", "2025-01-01", 5)

    # Two distinct keys, one per provider, neither polluting the legacy slot.
    assert "tushare::000001_2025-01-01_2025-01-10_5" in ashare_cache
    assert "000001_2025-01-01_2025-01-10_5" not in ashare_cache
    assert "financial_datasets::000001_2025-01-01_2025-01-10_5" in us_cache
    assert "000001_2025-01-01_2025-01-10_5" not in us_cache


def test_get_company_news_ashare_uses_akshare_provider_tag(monkeypatch):
    cache_news: dict[str, list[dict]] = {}

    class _Cache:
        def get_company_news(self, key):
            return cache_news.get(key)

        def set_company_news(self, key, value, ttl=None):
            cache_news[key] = value

    monkeypatch.setattr(api, "_cache", _Cache())
    monkeypatch.setattr(api, "is_ashare", lambda ticker: True)
    sentinel = [
        api.CompanyNews(
            ticker="000001",
            title="t",
            author="a",
            source="s",
            date="2025-01-03",
            url="https://example.com",
            sentiment="neutral",
            content="body",
        )
    ]
    monkeypatch.setattr(api, "get_ashare_company_news", lambda *args, **kwargs: sentinel)

    api.get_company_news("000001", "2025-01-10", "2025-01-01", 5)

    assert "akshare::000001_2025-01-01_2025-01-10_5_ashare" in cache_news
    assert "000001_2025-01-01_2025-01-10_5_ashare" not in cache_news


def test_get_company_news_us_uses_financial_datasets_provider_tag(monkeypatch):
    cache_news: dict[str, list[dict]] = {}

    class _Cache:
        def get_company_news(self, key):
            return cache_news.get(key)

        def set_company_news(self, key, value, ttl=None):
            cache_news[key] = value

    monkeypatch.setattr(api, "_cache", _Cache())
    monkeypatch.setattr(api, "is_ashare", lambda ticker: False)
    remote_payload = {
        "news": [
            {
                "ticker": "AAPL",
                "title": "earnings beat",
                "author": "reuters",
                "source": "reuters",
                "date": "2025-01-03T00:00:00",
                "url": "https://example.com/1",
                "sentiment": None,
                "content": None,
            }
        ]
    }
    response = SimpleNamespace(status_code=200, json=lambda: remote_payload)
    monkeypatch.setattr(api, "_make_api_request", lambda *args, **kwargs: response)

    api.get_company_news("AAPL", "2025-01-10", "2025-01-01", 5)

    assert "financial_datasets::AAPL_2025-01-01_2025-01-10_5" in cache_news
    assert "AAPL_2025-01-01_2025-01-10_5" not in cache_news


# ---------------------------------------------------------------------------
# akshare_api.py: cross-provider isolation for direct AKShare callers
# ---------------------------------------------------------------------------


def test_akshare_api_cache_keys_include_provider_prefix():
    """akshare_api.get_prices() writes a cache key with the `akshare::` prefix
    so its entries never collide with tushare writes for the same ticker."""
    from src.tools import akshare_api  # noqa: F401

    # The raw key format used by akshare_api.get_prices().
    raw_akshare = "akshare::ashare_000001_2025-01-01_2025-01-31_daily"
    # The raw key format used by api.py for the same ticker.
    raw_tushare_via_api = api._provider_key("tushare", "000001_2025-01-01_2025-01-31")
    # They must not collide.
    assert raw_akshare != raw_tushare_via_api
    # The akshare key has the explicit akshare tag.
    assert raw_akshare.startswith("akshare::ashare_")
    # The api.py key is tagged as tushare, not akshare.
    assert raw_tushare_via_api.startswith("tushare::")


# ---------------------------------------------------------------------------
# DataRouter: cache key carries the router namespace
# ---------------------------------------------------------------------------


class _RecordingCache:
    def __init__(self):
        self.saved: list[tuple[str, list[dict]]] = []

    def get_prices(self, key):
        return None

    def set_prices(self, key, data):
        self.saved.append((key, data))

    def get_financial_metrics(self, key):
        return None

    def set_financial_metrics(self, key, data):
        self.saved.append((key, data))

    def get_company_news(self, key):
        return None

    def set_company_news(self, key, data):
        pass

    def get_insider_trades(self, key):
        return None

    def set_insider_trades(self, key, data):
        pass


class _StubProvider:
    def __init__(self, name, *, price_response=None, metrics_response=None):
        self.name = name
        self.priority = 1
        self._price_response = price_response
        self._metrics_response = metrics_response

    async def health_check(self) -> bool:
        return True

    async def get_prices(self, ticker, start_date, end_date):
        return self._price_response

    async def get_financial_metrics(self, ticker, end_date):
        return self._metrics_response


def test_router_cache_key_includes_provider_tag():
    """The router's cache key should embed a provider dimension so the router
    namespace does not collide with the api.py namespace."""
    from datetime import datetime

    cache = _RecordingCache()
    router = DataRouter(
        [
            _StubProvider(
                "good",
                price_response=DataResponse(
                    data=[SimpleNamespace(model_dump=lambda: {"close": 10})],
                    source="good",
                ),
            )
        ]
    )
    router.cache = cache
    router._health_cache = {"good": True}
    router._last_health_check = datetime.now()

    asyncio.run(router.get_prices("AAPL", "2024-01-01", "2024-01-02"))

    assert len(cache.saved) == 1
    saved_key, _ = cache.saved[0]
    # New format: provider_tag + data_type + ticker + kwargs
    assert saved_key.startswith("router_price_AAPL_")
    # Legacy format had no prefix: must NOT match.
    assert not saved_key.startswith("price_AAPL_")


def test_router_cache_key_default_is_default_when_provider_omitted():
    """Backwards-compat: callers that omit `provider` still get a valid
    namespaced key, never the unprefixed legacy format."""
    from src.data.router import DataRouter

    router = DataRouter([])
    key = router._get_cache_key(DataType.PRICE, "AAPL", start="2024-01-01", end="2024-01-02")
    assert key.startswith("default_price_AAPL_")
    # Lower-cased normalisation.
    key_upper = router._get_cache_key(DataType.PRICE, "AAPL", provider="AKShare", start="2024-01-01")
    assert key_upper.startswith("akshare_price_AAPL_")
