"""
增强缓存模块

实现多层缓存策略：内存 LRU + Redis 持久化
"""

import json
import pickle
import hashlib
from typing import Any, Optional, Dict, List
from datetime import datetime, timedelta
from functools import lru_cache
import logging

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
        self._cache: Dict[str, Any] = {}
        self._access_time: Dict[str, datetime] = {}

    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
        
        Returns:
            缓存值或 None
        """
        if key in self._cache:
            # 更新访问时间
            self._access_time[key] = datetime.now()
            return self._cache[key]
        return None

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

    def keys(self) -> List[str]:
        """获取所有缓存键"""
        return list(self._cache.keys())

    def __len__(self) -> int:
        """获取缓存条目数"""
        return len(self._cache)


class RedisCache:
    """
    Redis 持久化缓存
    
    用于进程间共享和持久化存储
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        default_ttl: int = 3600
    ):
        """
        初始化 Redis 缓存
        
        Args:
            host: Redis 主机
            port: Redis 端口
            db: 数据库编号
            password: 密码
            default_ttl: 默认过期时间（秒）
        """
        self.default_ttl = default_ttl
        self._client: Optional[redis.Redis] = None
        
        if not REDIS_AVAILABLE:
            logger.warning("Redis not available. Install with: pip install redis")
            return
        
        try:
            self._client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=False,
                socket_connect_timeout=5
            )
            # 测试连接
            self._client.ping()
            logger.info("Redis cache connected")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            self._client = None

    def is_available(self) -> bool:
        """检查 Redis 是否可用"""
        if self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except Exception:
            return False

    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
        
        Returns:
            缓存值或 None
        """
        if not self.is_available():
            return None
        
        try:
            data = self._client.get(key)
            if data:
                return pickle.loads(data)
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
        
        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ):
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
            data = pickle.dumps(value)
            self._client.setex(key, ttl or self.default_ttl, data)
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
            self._client.delete(key)
        except Exception as e:
            logger.warning(f"Redis delete error: {e}")

    def clear(self):
        """清空当前数据库"""
        if not self.is_available():
            return
        
        try:
            self._client.flushdb()
        except Exception as e:
            logger.warning(f"Redis clear error: {e}")


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

    def __init__(
        self,
        lru_size: int = 128,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_ttl: int = 3600
    ):
        """
        初始化增强缓存
        
        Args:
            lru_size: LRU 缓存大小
            redis_host: Redis 主机
            redis_port: Redis 端口
            redis_ttl: Redis 默认过期时间
        """
        self.lru = LRUCache(maxsize=lru_size)
        self.redis = RedisCache(
            host=redis_host,
            port=redis_port,
            default_ttl=redis_ttl
        )
        
        # 统计信息
        self._stats = {
            "lru_hits": 0,
            "redis_hits": 0,
            "misses": 0,
            "sets": 0
        }

    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值（多级查询）
        
        Args:
            key: 缓存键
        
        Returns:
            缓存值或 None
        """
        # 1. 查 LRU
        value = self.lru.get(key)
        if value is not None:
            self._stats["lru_hits"] += 1
            return value
        
        # 2. 查 Redis
        value = self.redis.get(key)
        if value is not None:
            self._stats["redis_hits"] += 1
            # 回填 LRU
            self.lru.set(key, value)
            return value
        
        self._stats["misses"] += 1
        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ):
        """
        设置缓存值（多级写入）
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: Redis 过期时间
        """
        # 写入 LRU
        self.lru.set(key, value)
        
        # 写入 Redis
        self.redis.set(key, value, ttl)
        
        self._stats["sets"] += 1

    def delete(self, key: str):
        """
        删除缓存值
        
        Args:
            key: 缓存键
        """
        self.lru.delete(key)
        self.redis.delete(key)

    def clear(self):
        """清空所有缓存"""
        self.lru.clear()
        self.redis.clear()

    def get_stats(self) -> Dict[str, int]:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        total_hits = self._stats["lru_hits"] + self._stats["redis_hits"]
        total_requests = total_hits + self._stats["misses"]
        
        hit_rate = total_hits / total_requests if total_requests > 0 else 0
        
        return {
            **self._stats,
            "total_hits": total_hits,
            "total_requests": total_requests,
            "hit_rate": hit_rate,
            "lru_size": len(self.lru)
        }

    def reset_stats(self):
        """重置统计信息"""
        self._stats = {
            "lru_hits": 0,
            "redis_hits": 0,
            "misses": 0,
            "sets": 0
        }


# 兼容原有缓存接口的包装类
class CacheAdapter:
    """
    缓存适配器
    
    兼容原有 Cache 类的接口
    """

    def __init__(self, enhanced_cache: Optional[EnhancedCache] = None):
        """
        初始化缓存适配器
        
        Args:
            enhanced_cache: 增强缓存实例
        """
        self._cache = enhanced_cache or EnhancedCache()

    def _make_key(self, prefix: str, identifier: str) -> str:
        """生成缓存键"""
        return f"{prefix}:{identifier}"

    def get_prices(self, ticker: str) -> Optional[List[Dict]]:
        """获取价格数据"""
        key = self._make_key("prices", ticker)
        return self._cache.get(key)

    def set_prices(self, ticker: str, data: List[Dict]):
        """设置价格数据"""
        key = self._make_key("prices", ticker)
        self._cache.set(key, data, ttl=3600)  # 1小时过期

    def get_financial_metrics(self, ticker: str) -> Optional[List[Dict]]:
        """获取财务指标"""
        key = self._make_key("metrics", ticker)
        return self._cache.get(key)

    def set_financial_metrics(self, ticker: str, data: List[Dict]):
        """设置财务指标"""
        key = self._make_key("metrics", ticker)
        self._cache.set(key, data, ttl=7200)  # 2小时过期

    def get_line_items(self, ticker: str) -> Optional[List[Dict]]:
        """获取行项目数据"""
        key = self._make_key("line_items", ticker)
        return self._cache.get(key)

    def set_line_items(self, ticker: str, data: List[Dict]):
        """设置行项目数据"""
        key = self._make_key("line_items", ticker)
        self._cache.set(key, data, ttl=7200)

    def get_insider_trades(self, ticker: str) -> Optional[List[Dict]]:
        """获取内部交易数据"""
        key = self._make_key("insider", ticker)
        return self._cache.get(key)

    def set_insider_trades(self, ticker: str, data: List[Dict]):
        """设置内部交易数据"""
        key = self._make_key("insider", ticker)
        self._cache.set(key, data, ttl=3600)

    def get_company_news(self, ticker: str) -> Optional[List[Dict]]:
        """获取公司新闻"""
        key = self._make_key("news", ticker)
        return self._cache.get(key)

    def set_company_news(self, ticker: str, data: List[Dict]):
        """设置公司新闻"""
        key = self._make_key("news", ticker)
        self._cache.set(key, data, ttl=1800)  # 30分钟过期


# 全局缓存实例
_enhanced_cache: Optional[EnhancedCache] = None
_cache_adapter: Optional[CacheAdapter] = None


def get_enhanced_cache() -> EnhancedCache:
    """获取全局增强缓存实例"""
    global _enhanced_cache
    if _enhanced_cache is None:
        _enhanced_cache = EnhancedCache()
    return _enhanced_cache


def get_cache() -> CacheAdapter:
    """获取兼容接口的缓存实例"""
    global _cache_adapter
    if _cache_adapter is None:
        _cache_adapter = CacheAdapter(get_enhanced_cache())
    return _cache_adapter
