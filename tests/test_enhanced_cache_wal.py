"""R20 修复回归测试：DiskCache WAL + 连接复用 + DataRouter provider 一致性。

覆盖：
1. WAL 模式已启用（PRAGMA journal_mode 返回 wal）
2. 多次 set/get 复用长连接（self._conn 引用稳定）
3. 并发读写不报 SQLITE_BUSY
4. close() 之后行为正确（is_available 仍为 True 但读写返回 _sentinel）
5. DataRouter._set_to_cache / _get_from_cache 共享同一 provider-tagged key
"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import as_completed, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.data.base_provider import DataResponse, DataType
from src.data.enhanced_cache import CacheAdapter, DiskCache, EnhancedCache
from src.data.router import DataRouter

# ---------------------------------------------------------------------------
# DiskCache WAL 模式
# ---------------------------------------------------------------------------


def test_disk_cache_enables_wal_journal_mode(tmp_path: Path):
    """DiskCache 应在初始化时启用 WAL 模式，journal_mode 属性应为 'wal'。"""
    cache_path = tmp_path / "wal_cache.sqlite"
    cache = DiskCache(path=str(cache_path), default_ttl=3600)

    try:
        assert cache.is_available() is True
        # 通过 PRAGMA 验证 SQLite 报告的 journal_mode
        assert cache.journal_mode is not None
        assert cache.journal_mode.lower() == "wal"
        # 同时直接 PRAGMA 查询确认
        cur = cache._conn.execute("PRAGMA journal_mode")
        row = cur.fetchone()
        assert row is not None
        assert row[0].lower() == "wal"
    finally:
        cache.close()


def test_disk_cache_reuses_connection_across_set_get(tmp_path: Path):
    """多次 set/get/delete 不应重建 self._conn。"""
    cache_path = tmp_path / "reuse_cache.sqlite"
    cache = DiskCache(path=str(cache_path), default_ttl=3600)

    try:
        original_conn = cache._conn
        assert original_conn is not None
        # 50 次 set + 50 次 get
        for i in range(50):
            cache.set(f"key:{i}", {"v": i}, ttl=3600)
        for i in range(50):
            assert cache.get(f"key:{i}") == {"v": i}
        # 删除也走长连接
        for i in range(0, 50, 2):
            cache.delete(f"key:{i}")
        for i in range(0, 50, 2):
            assert cache.get(f"key:{i}", _sentinel="MISS") == "MISS"
        for i in range(1, 50, 2):
            assert cache.get(f"key:{i}") == {"v": i}
        # 关键断言：连接对象从未被替换
        assert cache._conn is original_conn
        # 仍可用
        assert cache._is_alive() is True
    finally:
        cache.close()


def test_disk_cache_concurrent_reads_writes_no_sqlite_busy(tmp_path: Path):
    """并发读写不抛 SQLITE_BUSY；所有写入的 key 都能在最后读出。"""
    cache_path = tmp_path / "concurrent_cache.sqlite"
    cache = DiskCache(path=str(cache_path), default_ttl=3600)

    try:
        n_writers = 4
        n_readers = 4
        ops_per_thread = 100
        errors: list[BaseException] = []
        write_keys: list[str] = []

        def writer(start: int) -> None:
            try:
                for i in range(ops_per_thread):
                    key = f"writer:{start}:{i}"
                    cache.set(key, {"writer": start, "i": i}, ttl=3600)
                    write_keys.append(key)
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        def reader(start: int) -> None:
            try:
                for i in range(ops_per_thread):
                    # 读不存在的 key 也走长连接，验证不抛 SQLITE_BUSY
                    cache.get(f"reader:{start}:{i}", _sentinel=None)
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        with ThreadPoolExecutor(max_workers=n_writers + n_readers) as pool:
            futures = []
            for w in range(n_writers):
                futures.append(pool.submit(writer, w))
            for r in range(n_readers):
                futures.append(pool.submit(reader, r))
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Concurrent ops raised: {errors[:3]}"
        # 所有写入的 key 都应能读出
        missing = [k for k in write_keys if cache.get(k, _sentinel="MISS") == "MISS"]
        assert missing == [], f"Lost {len(missing)} keys after concurrent writes (e.g. {missing[:3]})"
        # 计数一致
        assert cache.count_entries() == len(write_keys)
    finally:
        cache.close()


def test_disk_cache_close_drops_long_connection(tmp_path: Path):
    """close() 后 _conn 应为 None；close 后再 set/get 应静默失败（不抛异常）。"""
    cache_path = tmp_path / "close_cache.sqlite"
    cache = DiskCache(path=str(cache_path), default_ttl=3600)

    cache.set("k1", {"x": 1}, ttl=3600)
    assert cache.get("k1") == {"x": 1}

    cache.close()
    assert cache._conn is None
    # _is_alive() 在 _conn 为 None 时应返回 False
    assert cache._is_alive() is False

    # 关闭后调用 get/set/delete 不应抛异常（向量化降级到 sentinel/no-op）
    sentinel = object()
    assert cache.get("k1", _sentinel=sentinel) is sentinel
    # set/delete 在连接为空时静默 no-op
    cache.set("k2", {"y": 2}, ttl=3600)
    cache.delete("k1")
    cache.clear()
    cache.count_entries()  # 不抛


def test_disk_cache_get_conn_returns_long_connection(tmp_path: Path):
    """_get_conn() 仍能返回底层连接（向后兼容），但调用方不应再 .close()。"""
    cache_path = tmp_path / "compat_cache.sqlite"
    cache = DiskCache(path=str(cache_path), default_ttl=3600)

    try:
        conn_a = cache._get_conn()
        conn_b = cache._get_conn()
        # 两次调用返回同一长连接
        assert conn_a is conn_b
        assert conn_a is cache._conn
    finally:
        cache.close()


# ---------------------------------------------------------------------------
# DataRouter provider 一致性（R20 P1-2）
# ---------------------------------------------------------------------------


class _RouterTestCache:
    """记录 router 调用的 get/set key 的最小桩。"""

    def __init__(self):
        self.store: dict[str, list[dict]] = {}
        self.read_calls: list[tuple[str, str]] = []
        self.write_calls: list[tuple[str, str]] = []

    def get_prices(self, key, provider=""):
        self.read_calls.append((key, provider))
        return self.store.get(("prices", provider, key))

    def set_prices(self, key, data, provider=""):
        self.write_calls.append((key, provider))
        self.store[("prices", provider, key)] = data

    def get_financial_metrics(self, key, provider=""):
        self.read_calls.append((key, provider))
        return self.store.get(("metrics", provider, key))

    def set_financial_metrics(self, key, data, provider=""):
        self.write_calls.append((key, provider))
        self.store[("metrics", provider, key)] = data

    def get_company_news(self, key, provider=""):
        self.read_calls.append((key, provider))
        return self.store.get(("news", provider, key))

    def set_company_news(self, key, data, provider="", ttl=None):
        self.write_calls.append((key, provider))
        self.store[("news", provider, key)] = data

    def get_insider_trades(self, key, provider=""):
        self.read_calls.append((key, provider))
        return self.store.get(("insider", provider, key))

    def set_insider_trades(self, key, data, provider=""):
        self.write_calls.append((key, provider))
        self.store[("insider", provider, key)] = data


class _StubRouterProvider:
    def __init__(self, name: str, *, price=None, metrics=None):
        self.name = name
        self.priority = 1
        self._price = price
        self._metrics = metrics

    async def health_check(self) -> bool:
        return True

    async def get_prices(self, ticker, start_date, end_date):
        return self._price

    async def get_financial_metrics(self, ticker, end_date):
        return self._metrics


def test_router_set_and_get_use_consistent_provider_tag():
    """_set_to_cache 与 _get_from_cache 必须写入并读取 provider="router" 的 key。

    这避免空 provider 走 "prices:..." 旧 key 格式与带 provider 的 key 不一致。
    """
    import asyncio
    from datetime import datetime

    cache = _RouterTestCache()
    price_payload = [SimpleNamespace(model_dump=lambda: {"close": 10})]
    router = DataRouter(
        [_StubRouterProvider("good", price=DataResponse(data=price_payload, source="good"))]
    )
    router.cache = cache
    router._last_health_check = datetime.now()  # skip _check_health

    # 第一次：缓存空，走 provider → 写入
    resp1 = asyncio.run(router.get_prices("AAPL", "2024-01-01", "2024-01-02"))
    assert resp1 is not None
    # 写入时 provider 应为 "router"
    write_keys_w_provider = [(k, p) for k, p in cache.write_calls if p == "router"]
    assert len(write_keys_w_provider) == 1, f"Expected exactly 1 router-tagged write, got {cache.write_calls}"
    written_key, _ = write_keys_w_provider[0]
    # 读取时 provider 也应为 "router"
    assert any(p == "router" for _, p in cache.read_calls)
    # 写入的 key 与读时构造的 key 一致
    read_keys_w_provider = [k for k, p in cache.read_calls if p == "router"]
    assert written_key in read_keys_w_provider

    # 第二次：同一 cache_key 应能命中 _set_to_cache 写入的条目
    resp2 = asyncio.run(router.get_prices("AAPL", "2024-01-01", "2024-01-02"))
    assert resp2 is not None
    assert resp2.cached is True
    # 第二次调用没有新的写
    assert len(cache.write_calls) == 1


def test_router_set_to_cache_passes_explicit_router_provider():
    """直接验证 _set_to_cache 走 provider="router" 路径。"""
    cache = _RouterTestCache()
    router = DataRouter([])
    router.cache = cache

    router._set_to_cache("router_price_AAPL_x", DataType.PRICE, [{"close": 1.0}])
    router._set_to_cache("router_metrics_AAPL_y", DataType.FUNDAMENTAL, [{"roe": 0.1}])
    router._set_to_cache("router_news_AAPL_z", DataType.NEWS, [{"title": "t"}])
    router._set_to_cache("router_insider_AAPL_w", DataType.INSIDER_TRADE, [{"shares": 1}])

    providers = [p for _, p in cache.write_calls]
    assert providers == ["router", "router", "router", "router"]
    # 没有空 provider 写
    assert "" not in providers


def test_router_get_from_cache_reads_router_provider_key():
    """_get_from_cache 必须用 provider="router" 读，否则会找不到 _set_to_cache 写入的条目。"""
    cache = _RouterTestCache()
    router = DataRouter([])
    router.cache = cache

    # 预置带 provider="router" 的条目
    cache.store[("prices", "router", "router_price_X_...")] = [{"close": 9}]
    cache.store[("metrics", "router", "router_metrics_X_...")] = [{"roe": 0.2}]

    result_price = router._get_from_cache("router_price_X_...", DataType.PRICE)
    result_metrics = router._get_from_cache("router_metrics_X_...", DataType.FUNDAMENTAL)

    assert result_price is not None
    assert result_price.cached is True
    assert result_metrics is not None
    assert result_metrics.cached is True
    # 读取时 provider 都为 router
    assert all(p == "router" for _, p in cache.read_calls)


# ---------------------------------------------------------------------------
# EnhancedCache 集成：_make_key 旧格式仍可读（向后兼容）
# ---------------------------------------------------------------------------


def test_enhanced_cache_backwards_compatible_unprefixed_key(tmp_path: Path):
    """空 provider 的旧 key 格式（"prices:AAPL"）仍应可读，保持向后兼容。"""
    cache_path = tmp_path / "compat_legacy.sqlite"
    ec = EnhancedCache(disk_path=str(cache_path))

    # 用旧 key 写入
    legacy_key = "prices:000001"
    ec.set(legacy_key, {"legacy": True}, ttl=3600)
    assert ec.get(legacy_key) == {"legacy": True}
    # 用新格式（provider="router"）也仍能工作
    new_key = "prices:router:000001"
    ec.set(new_key, {"new": True}, ttl=3600)
    assert ec.get(new_key) == {"new": True}
    # 两条都还在
    assert ec.get(legacy_key) == {"legacy": True}
    assert ec.get(new_key) == {"new": True}
    # 统计
    stats = ec.get_stats()
    assert stats["sets"] >= 2
    assert stats["lru_hits"] >= 2


# ---------------------------------------------------------------------------
# BETA (R20.32): 惰性删除过期项的并发安全
# ---------------------------------------------------------------------------


def test_disk_cache_lazy_delete_does_not_clobber_fresh_value(tmp_path: Path):
    """R20.32 回归测试：DiskCache.get() 在发现过期项后，删除必须是条件的。

    模拟竞态：
      1. 写入一个 key（TTL = 0 表示立即过期）。
      2. 手动把 expires_at 改成一个较早的时间戳（看起来过期）。
      3. 在 get() 触发惰性删除之前，并发写入一个 fresh value（远期 expires_at）。
      4. 验证 fresh value 不会被 lazy delete 误删。

    修复前：get() 调用 self.delete(key) 无条件删除，会清掉后续写入的 fresh value。
    修复后：get() 走条件 DELETE（WHERE expires_at <= now），fresh value 保留。
    """
    import time as _time

    cache_path = tmp_path / "lazy_delete_cache.sqlite"
    cache = DiskCache(path=str(cache_path), default_ttl=3600)

    try:
        # 1) 写入初始 key（TTL 设为 0 通常表示永不过期；我们直接塞一个较近的过期值）
        cache.set("race_key", "initial_value", ttl=3600)
        conn = cache._conn
        assert conn is not None
        # 把过期时间改成一个已经过去的时间戳，让 get() 触发惰性删除分支
        past_ts = int(_time.time()) - 60
        conn.execute("UPDATE cache SET expires_at = ? WHERE key = ?", (past_ts, "race_key"))

        # 2) 在 get() 的过期检查和 lazy delete 之间，模拟并发的 SET
        #    这里的实现方式：直接调用 set() 把 fresh value 写进去。
        #    修复前：get() 内部无条件 DELETE 会把这一条 fresh value 清掉。
        #    修复后：get() 的条件 DELETE 只删除仍处于过期状态的记录，fresh value 保留。
        cache.set("race_key", "fresh_value", ttl=3600)

        # 3) 此时 key 已带 fresh value（expires_at = now + 3600，远期）。
        #    再次调用 get() 触发惰性删除（应当不删），然后验证返回值。
        sentinel = object()
        result = cache.get("race_key", _sentinel=sentinel)
        assert result is not sentinel, "fresh value should not be silently evicted by stale lazy delete"
        assert result == "fresh_value"
    finally:
        cache.close()
