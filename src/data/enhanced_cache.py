"""
增强缓存模块

实现多层缓存策略：内存 LRU + Redis 持久化
"""

import logging
import os
import pickle
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class LRUCache:
    """
    内存 LRU 缓存

    使用 functools.lru_cache 实现热点数据快速访问
    """

    def __init__(self, maxsize: int = 128):
        """
        初始化 LRU 缓存

        Args:
            maxsize: 最大缓存条目数
        """
        self.maxsize = maxsize
        self._cache: dict[str, Any] = {}
        self._access_time: dict[str, datetime] = {}

    # Sentinel for cache miss — distinguishes "key not present" from "cached None".
    _MISSING = object()

    def get(self, key: str, *, _sentinel: Any = None) -> Any | None:
        """
        获取缓存值

        Args:
            key: 缓存键
            _sentinel: if provided, return this instead of None on miss.
                       Callers can pass a unique sentinel to distinguish
                       "cached None" from "key not present".

        Returns:
            缓存值, _sentinel on miss, or None on miss (default)
        """
        if key in self._cache:
            # 更新访问时间
            self._access_time[key] = datetime.now()
            return self._cache[key]
        return _sentinel

    def set(self, key: str, value: Any):
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
        """
        # 如果缓存已满，淘汰最久未使用的
        if len(self._cache) >= self.maxsize and key not in self._cache:
            self._evict_lru()

        self._cache[key] = value
        self._access_time[key] = datetime.now()

    def delete(self, key: str):
        """
        删除缓存值

        Args:
            key: 缓存键
        """
        self._cache.pop(key, None)
        self._access_time.pop(key, None)

    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._access_time.clear()

    def _evict_lru(self):
        """淘汰最久未使用的条目"""
        if not self._access_time:
            return

        # 找到最久未使用的键
        lru_key = min(self._access_time, key=self._access_time.get)
        self.delete(lru_key)

    def keys(self) -> list[str]:
        """获取所有缓存键"""
        return list(self._cache.keys())


class RedisCache:
    """
    Redis 缓存

    使用 Redis 进行持久化存储，支持跨进程共享
    """

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, password: str | None = None, default_ttl: int = 3600):
        """
        初始化 Redis 缓存

        Args:
            host: Redis 主机
            port: Redis 端口
            db: Redis 数据库
            password: Redis 密码
            default_ttl: 默认过期时间（秒）
        """
        self.default_ttl = default_ttl
        self._available = False
        self._client = None

        if not REDIS_AVAILABLE:
            logger.warning("Redis not available, install with: pip install redis")
            return

        try:
            self._client = redis.Redis(host=host, port=port, db=db, password=password, decode_responses=False, socket_connect_timeout=5, socket_timeout=5)  # 使用二进制序列化
            # 测试连接
            self._client.ping()
            self._available = True
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")

    def is_available(self) -> bool:
        """
        检查 Redis 是否可用

        Returns:
            是否可用
        """
        return self._available

    def _make_key(self, key: str) -> str:
        """
        生成 Redis 键

        Args:
            key: 原始键

        Returns:
            带前缀的键
        """
        return f"ai-hedge-fund:{key}"

    # Sentinel for cache miss — distinguishes "key not present" from "cached None".
    _MISSING = object()

    def get(self, key: str, *, _sentinel: Any = None) -> Any | None:
        """
        获取缓存值

        Args:
            key: 缓存键
            _sentinel: if provided, return this instead of None on miss.
                       Callers can pass a unique sentinel to distinguish
                       "cached None" from "key not present".

        Returns:
            缓存值，或 _sentinel（未命中时），或 None（默认未命中时）
        """
        if not self.is_available():
            return _sentinel
        try:
            data = self._client.get(self._make_key(key))
            if data is None:
                return _sentinel
            return pickle.loads(data)
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return _sentinel

    def set(self, key: str, value: Any, ttl: int | None = None):
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
        """
        if not self.is_available():
            return
        try:
            ttl_seconds = self.default_ttl if ttl is None else ttl
            data = pickle.dumps(value)
            self._client.setex(self._make_key(key), timedelta(seconds=ttl_seconds), data)
        except Exception as e:
            logger.warning(f"Redis set error: {e}")

    def delete(self, key: str):
        """
        删除缓存值

        Args:
            key: 缓存键
        """
        if not self.is_available():
            return
        try:
            self._client.delete(self._make_key(key))
        except Exception as e:
            logger.warning(f"Redis delete error: {e}")

    def clear(self):
        """
        清空缓存

        只清除带前缀的键
        """
        if not self.is_available():
            return
        try:
            pattern = self._make_key("*")
            for key in self._client.scan_iter(match=pattern):
                self._client.delete(key)
        except Exception as e:
            logger.warning(f"Redis clear error: {e}")


class DiskCache:
    """
    磁盘缓存

    使用 SQLite 进行持久化存储（线程安全）
    """

    def __init__(self, path: str | None = None, default_ttl: int = 3600):
        """
        初始化磁盘缓存

        Args:
            path: 缓存数据库路径
            default_ttl: 默认过期时间（秒）
        """
        self.default_ttl = default_ttl
        self._available = True
        cache_path = path or os.environ.get("DISK_CACHE_PATH")
        if not cache_path:
            cache_path = os.path.join(os.path.expanduser("~"), ".cache", "ai-hedge-fund", "cache.sqlite")
        self._path = cache_path

        # 初始化数据库表（只执行一次）
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            conn = sqlite3.connect(self._path)
            conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value BLOB, expires_at INTEGER)")
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Disk cache init error: {e}")
            self._available = False

    def _get_conn(self):
        """获取新的数据库连接（线程安全）"""
        return sqlite3.connect(self._path)

    def is_available(self) -> bool:
        """
        检查磁盘缓存是否可用

        Returns:
            是否可用
        """
        return self._available

    def _now_ts(self) -> int:
        """
        获取当前时间戳

        Returns:
            秒级时间戳
        """
        return int(datetime.now().timestamp())

    # Sentinel for cache miss — distinguishes "key not present" from "cached None".
    _MISSING = object()

    def get(self, key: str, *, _sentinel: Any = None) -> Any | None:
        """
        获取缓存值

        Args:
            key: 缓存键
            _sentinel: if provided, return this instead of None on miss.
                       Callers can pass a unique sentinel to distinguish
                       "cached None" from "key not present".

        Returns:
            缓存值，或 _sentinel（未命中时），或 None（默认未命中时）
        """
        if not self.is_available():
            return _sentinel
        try:
            conn = self._get_conn()
            try:
                cursor = conn.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,))
                row = cursor.fetchone()
                if not row:
                    return _sentinel
                value, expires_at = row
                if expires_at and expires_at < self._now_ts():
                    self.delete(key)
                    return _sentinel
                return pickle.loads(value)
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Disk cache get error: {e}")
            return _sentinel

    def set(self, key: str, value: Any, ttl: int | None = None):
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
        """
        if not self.is_available():
            return
        try:
            conn = self._get_conn()
            try:
                ttl_seconds = self.default_ttl if ttl is None else ttl
                expires_at = 0 if ttl_seconds == 0 else self._now_ts() + ttl_seconds
                data = pickle.dumps(value)
                conn.execute("INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)", (key, data, expires_at))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Disk cache set error: {e}")

    def delete(self, key: str):
        """
        删除缓存值

        Args:
            key: 缓存键
        """
        if not self.is_available():
            return
        try:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Disk cache delete error: {e}")

    def clear(self):
        """
        清空缓存

        Returns:
            None
        """
        if not self.is_available():
            return
        try:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM cache")
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Disk cache clear error: {e}")

    def count_entries(self) -> int:
        """返回当前磁盘缓存中的条目数。"""
        if not self.is_available():
            return 0
        try:
            conn = self._get_conn()
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM cache")
                row = cursor.fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Disk cache count error: {e}")
            return 0

    def get_file_size_bytes(self) -> int:
        """返回 SQLite 缓存文件大小。"""
        if not self.is_available():
            return 0
        try:
            return int(os.path.getsize(self._path)) if os.path.exists(self._path) else 0
        except Exception as e:
            logger.warning(f"Disk cache size error: {e}")
            return 0


class EnhancedCache:
    """
    增强缓存

    组合 LRU 内存缓存和 Redis 持久化缓存
    实现多级缓存策略

    缓存策略：
    1. 先查 LRU（最快）
    2. 再查 Redis（跨进程）
    3. 写入时同时更新两级缓存
    """

    def __init__(self, lru_size: int = 128, redis_host: str = "localhost", redis_port: int = 6379, redis_ttl: int = 3600, disk_path: str | None = None):
        """
        初始化增强缓存

        Args:
            lru_size: LRU 缓存大小
            redis_host: Redis 主机
            redis_port: Redis 端口
            redis_ttl: Redis 默认过期时间
            disk_path: 磁盘缓存路径
        """
        self.lru = LRUCache(maxsize=lru_size)
        self.redis = RedisCache(host=redis_host, port=redis_port, default_ttl=redis_ttl)
        self.disk = DiskCache(path=disk_path, default_ttl=redis_ttl)

        # 统计信息
        self._stats = {"lru_hits": 0, "redis_hits": 0, "disk_hits": 0, "misses": 0, "sets": 0}

    # Sentinel for cache miss — distinguishes "key not present" from "cached None".
    _MISSING = object()

    def get(self, key: str) -> Any | None:
        """
        获取缓存值

        查询顺序：LRU -> Redis -> Disk

        Args:
            key: 缓存键

        Returns:
            缓存值或 None
        """
        # 1. 查 LRU
        value = self.lru.get(key, _sentinel=self._MISSING)
        if value is not self._MISSING:
            self._stats["lru_hits"] += 1
            return value

        # 2. 查 Redis
        value = self.redis.get(key, _sentinel=self._MISSING)
        if value is not self._MISSING:
            self._stats["redis_hits"] += 1
            # 回填 LRU
            self.lru.set(key, value)
            return value

        # 3. 查 Disk
        value = self.disk.get(key, _sentinel=self._MISSING)
        if value is not self._MISSING:
            self._stats["disk_hits"] += 1
            # 回填 Redis 和 LRU
            self.redis.set(key, value)
            self.lru.set(key, value)
            return value

        self._stats["misses"] += 1
        return None

    def set(self, key: str, value: Any, ttl: int | None = None):
        """
        设置缓存值

        同时写入 LRU、Redis 和 Disk

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
        """
        self.lru.set(key, value)
        self.redis.set(key, value, ttl)
        self.disk.set(key, value, ttl)
        self._stats["sets"] += 1

    def delete(self, key: str):
        """
        删除缓存值

        同时删除 LRU、Redis 和 Disk 中的值

        Args:
            key: 缓存键
        """
        self.lru.delete(key)
        self.redis.delete(key)
        self.disk.delete(key)

    def clear(self):
        """清空所有缓存"""
        self.lru.clear()
        self.redis.clear()
        self.disk.clear()

    def get_stats(self) -> dict[str, int]:
        """
        获取缓存统计信息

        Returns:
            统计字典
        """
        total_hits = self._stats["lru_hits"] + self._stats["redis_hits"] + self._stats["disk_hits"]
        total_requests = total_hits + self._stats["misses"]
        hit_rate = total_hits / total_requests if total_requests > 0 else 0

        return {**self._stats, "total_hits": total_hits, "total_requests": total_requests, "hit_rate": round(hit_rate, 4)}


class CacheAdapter:
    """
    缓存适配器

    提供与原有 Cache 接口兼容的方法
    """

    def __init__(self, enhanced_cache: EnhancedCache | None = None):
        """
        初始化缓存适配器

        Args:
            enhanced_cache: 增强缓存实例
        """
        self._cache = enhanced_cache or EnhancedCache()

    def _make_key(self, prefix: str, identifier: str, provider: str = "") -> str:
        """生成缓存键

        Args:
            prefix: 缓存前缀（如 "prices", "metrics"）
            identifier: 标识符（如 ticker 或复合键）
            provider: 数据源（如 "akshare", "tushare", "financial_datasets"）。
                      为空时退化为旧格式，保持向后兼容。

        Returns:
            缓存键字符串。provider 非空时格式为 "{prefix}:{provider}:{identifier}"，
            否则为 "{prefix}:{identifier}"。
        """
        if provider:
            return f"{prefix}:{provider}:{identifier}"
        return f"{prefix}:{identifier}"

    def get_prices(self, ticker: str, provider: str = "") -> list[dict] | None:
        """获取价格数据

        Args:
            ticker: 股票代码或复合缓存键
            provider: 数据源（如 "akshare", "tushare"）
        """
        key = self._make_key("prices", ticker, provider)
        return self._cache.get(key)

    def set_prices(self, ticker: str, data: list[dict], provider: str = ""):
        """设置价格数据

        Args:
            ticker: 股票代码或复合缓存键
            data: 价格数据
            provider: 数据源（如 "akshare", "tushare"）
        """
        key = self._make_key("prices", ticker, provider)
        self._cache.set(key, data, ttl=86400)

    def get_financial_metrics(self, ticker: str, provider: str = "") -> list[dict] | None:
        """获取财务指标

        Args:
            ticker: 股票代码或复合缓存键
            provider: 数据源（如 "akshare", "tushare"）
        """
        key = self._make_key("metrics", ticker, provider)
        return self._cache.get(key)

    def set_financial_metrics(self, ticker: str, data: list[dict], provider: str = ""):
        """设置财务指标

        Args:
            ticker: 股票代码或复合缓存键
            data: 财务指标数据
            provider: 数据源（如 "akshare", "tushare"）
        """
        key = self._make_key("metrics", ticker, provider)
        self._cache.set(key, data, ttl=604800)

    def get_line_items(self, ticker: str, provider: str = "") -> list[dict] | None:
        """获取行项目数据

        Args:
            ticker: 股票代码或复合缓存键
            provider: 数据源（如 "akshare", "tushare"）
        """
        key = self._make_key("line_items", ticker, provider)
        return self._cache.get(key)

    def set_line_items(self, ticker: str, data: list[dict], provider: str = ""):
        """设置行项目数据

        Args:
            ticker: 股票代码或复合缓存键
            data: 行项目数据
            provider: 数据源（如 "akshare", "tushare"）
        """
        key = self._make_key("line_items", ticker, provider)
        self._cache.set(key, data, ttl=604800)

    def get_insider_trades(self, ticker: str, provider: str = "") -> list[dict] | None:
        """获取内部交易数据

        Args:
            ticker: 股票代码或复合缓存键
            provider: 数据源（如 "akshare", "tushare"）
        """
        key = self._make_key("insider", ticker, provider)
        return self._cache.get(key)

    def set_insider_trades(self, ticker: str, data: list[dict], provider: str = ""):
        """设置内部交易数据

        Args:
            ticker: 股票代码或复合缓存键
            data: 内部交易数据
            provider: 数据源（如 "akshare", "tushare"）
        """
        key = self._make_key("insider", ticker, provider)
        self._cache.set(key, data, ttl=86400)

    def get_company_news(self, ticker: str, provider: str = "") -> list[dict] | None:
        """获取公司新闻

        Args:
            ticker: 股票代码或复合缓存键
            provider: 数据源（如 "akshare", "tushare"）
        """
        key = self._make_key("news", ticker, provider)
        return self._cache.get(key)

    def set_company_news(self, ticker: str, data: list[dict], ttl: int | None = None, provider: str = ""):
        """设置公司新闻

        Args:
            ticker: 股票代码或复合缓存键
            data: 公司新闻数据
            ttl: 过期时间（秒）
            provider: 数据源（如 "akshare", "tushare"）
        """
        key = self._make_key("news", ticker, provider)
        self._cache.set(key, data, ttl=10800 if ttl is None else ttl)


_enhanced_cache: EnhancedCache | None = None
_cache_adapter: CacheAdapter | None = None
_singleton_lock = threading.Lock()


def get_enhanced_cache() -> EnhancedCache:
    """获取全局增强缓存实例（线程安全）"""
    global _enhanced_cache
    if _enhanced_cache is not None:
        return _enhanced_cache
    with _singleton_lock:
        if _enhanced_cache is None:
            _enhanced_cache = EnhancedCache()
        return _enhanced_cache


def get_cache() -> CacheAdapter:
    """获取兼容接口的缓存实例（线程安全）"""
    global _cache_adapter
    if _cache_adapter is not None:
        return _cache_adapter
    with _singleton_lock:
        if _cache_adapter is None:
            _cache_adapter = CacheAdapter(get_enhanced_cache())
        return _cache_adapter


def clear_cache():
    """清空全局缓存"""
    cache = get_enhanced_cache()
    cache.clear()


def get_cache_stats() -> dict[str, int]:
    """
    获取缓存统计信息

    Returns:
        统计字典
    """
    cache = get_enhanced_cache()
    return cache.get_stats()


def snapshot_cache_stats() -> dict[str, int]:
    """获取当前缓存统计快照，用于计算单次运行的增量。"""
    return dict(get_cache_stats())


def diff_cache_stats(before: dict[str, int], after: dict[str, int]) -> dict[str, int | float]:
    """计算缓存统计的增量值。"""
    numeric_keys = ["lru_hits", "redis_hits", "disk_hits", "misses", "sets", "total_hits", "total_requests"]
    delta = {key: int(after.get(key, 0)) - int(before.get(key, 0)) for key in numeric_keys}
    total_requests = delta["total_requests"]
    delta["hit_rate"] = round((delta["total_hits"] / total_requests), 4) if total_requests > 0 else 0.0
    return delta


def get_cache_runtime_info() -> dict[str, Any]:
    """获取缓存运行时信息，便于排查命中率和落盘位置。"""
    cache = get_enhanced_cache()
    return {
        "lru_maxsize": cache.lru.maxsize,
        "redis_available": cache.redis.is_available(),
        "disk_available": cache.disk.is_available(),
        "disk_path": getattr(cache.disk, "_path", None),
        "disk_entry_count": cache.disk.count_entries(),
        "disk_file_size_bytes": cache.disk.get_file_size_bytes(),
        "stats": cache.get_stats(),
    }
