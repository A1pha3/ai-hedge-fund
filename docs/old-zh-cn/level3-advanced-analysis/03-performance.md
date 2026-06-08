# 第三章：性能优化策略

## 学习目标

完成本章节学习后，你将能够识别和分析系统的性能瓶颈，掌握并发处理和异步编程的技术，学会缓存策略的优化方法，以及能够实施资源管理和监控。预计学习时间为 2-3 小时。

## 3.1 性能分析基础

### 性能瓶颈识别

在进行优化之前，首先需要识别系统的性能瓶颈。使用性能分析工具可以帮助定位问题所在。

```python
import cProfile
import pstats
from functools import wraps

def profile(func):
    """性能分析装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        result = profiler.runcall(func, *args, **kwargs)
        
        # 输出性能统计
        stats = pstats.Stats(profiler)
        stats.sort_stats('cumulative')
        stats.print_stats(20)  # 显示前 20 个最耗时的函数
        
        return result
    return wrapper

@profile
def run_analysis():
    """运行分析（带性能分析）"""
    # 分析代码
    pass
```

### 关键性能指标

**延迟（Latency）**：从请求到响应的时间，影响用户体验。

**吞吐量（Throughput）**：单位时间内处理的请求数量，影响系统容量。

**资源利用率**：CPU、内存、I/O 等资源的使用效率。

## 3.2 并发与异步优化

### 智能体并行执行

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import List, Dict, Any

class AgentExecutor:
    """智能体并行执行器"""
    
    def __init__(
        self,
        max_workers: int = None,
        use_multiprocessing: bool = False
    ):
        self.max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
        self.use_multiprocessing = use_multiprocessing
        
        if use_multiprocessing:
            self.executor = ProcessPoolExecutor(max_workers=self.max_workers)
        else:
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
    
    async def run_agents_async(
        self,
        agents: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """异步并行运行多个智能体"""
        loop = asyncio.get_event_loop()
        
        # 创建任务
        tasks = [
            loop.run_in_executor(
                self.executor,
                self._run_single_agent,
                agent
            )
            for agent in agents
        ]
        
        # 并发执行
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "agent_id": agents[i]["id"],
                    "error": str(result)
                })
            else:
                processed_results.append(result)
        
        return processed_results
    
    def _run_single_agent(self, agent: Dict[str, Any]) -> Dict[str, Any]:
        """运行单个智能体"""
        # 智能体执行逻辑
        pass
    
    def shutdown(self):
        """关闭执行器"""
        self.executor.shutdown(wait=True)
```

### 异步数据获取

```python
import aiohttp
import asyncio
from typing import List, Dict, Any

class AsyncDataFetcher:
    """异步数据获取器"""
    
    def __init__(self, max_concurrent: int = 10):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.session = None
    
    async def fetch_all(
        self,
        requests: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """并发获取所有数据"""
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            tasks = [self._fetch_with_semaphore(req) for req in requests]
            results = await asyncio.gather(*tasks)
            
            return results
    
    async def _fetch_with_semaphore(
        self,
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """使用信号量限制并发"""
        async with self.semaphore:
            return await self._fetch_single(request)
    
    async def _fetch_single(
        self,
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """获取单个数据"""
        async with self.session.get(request["url"]) as response:
            data = await response.json()
            return {
                "id": request["id"],
                "data": data
            }
```

## 3.3 缓存策略优化

### 多层缓存架构

```python
from functools import lru_cache
import redis
import pickle
import hashlib
from typing import Any, Optional
import time

class CacheManager:
    """多级缓存管理器"""
    
    def __init__(
        self,
        memory_cache_size: int = 1000,
        redis_url: Optional[str] = None,
        default_ttl: int = 3600
    ):
        # L1: 内存缓存（LRU）
        self.memory_cache = LRUCache(max_size=memory_cache_size)
        
        # L2: Redis 分布式缓存
        self.redis_client = None
        if redis_url:
            self.redis_client = redis.from_url(redis_url)
        
        self.default_ttl = default_ttl
    
    def get(self, key: str) -> Any:
        """获取缓存（多层查询）"""
        # L1: 内存
        value = self.memory_cache.get(key)
        if value is not None:
            return value
        
        # L2: Redis
        if self.redis_client:
            redis_value = self.redis_client.get(key)
            if redis_value:
                value = pickle.loads(redis_value)
                # 回填 L1
                self.memory_cache.set(key, value)
                return value
        
        return None
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ):
        """设置缓存（多层写入）"""
        ttl = ttl or self.default_ttl
        
        # L1: 内存
        self.memory_cache.set(key, value)
        
        # L2: Redis
        if self.redis_client:
            self.redis_client.setex(
                key,
                ttl,
                pickle.dumps(value)
            )
    
    def invalidate(self, key: str):
        """使缓存失效"""
        self.memory_cache.delete(key)
        if self.redis_client:
            self.redis_client.delete(key)
    
    def clear(self):
        """清空所有缓存"""
        self.memory_cache.clear()
        if self.redis_client:
            self.redis_client.flushdb()
```

### 智能缓存失效

```python
class SmartCacheInvalidator:
    """智能缓存失效器"""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self.dependency_graph = DependencyGraph()
    
    def register_dependency(
        self,
        cache_key: str,
        dependencies: List[str]
    ):
        """注册缓存依赖关系"""
        for dep in dependencies:
            self.dependency_graph.add_edge(dep, cache_key)
    
    def invalidate_dependencies(self, source_key: str):
        """使依赖源失效"""
        # 获取所有依赖于 source_key 的缓存键
        dependent_keys = self.dependency_graph.get_dependents(source_key)
        
        # 批量失效
        for key in dependent_keys:
            self.cache.invalidate(key)
    
    def with_invalidation(
        self,
        source_keys: List[str]
    ):
        """上下文管理器：在更新时自动失效缓存"""
        return CacheInvalidationContext(self, source_keys)


class CacheInvalidationContext:
    """缓存失效上下文"""
    
    def __init__(
        self,
        invalidator: SmartCacheInvalidator,
        source_keys: List[str]
    ):
        self.invalidator = invalidator
        self.source_keys = source_keys
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # 更新完成后失效相关缓存
        for key in self.source_keys:
            self.invalidator.invalidate_dependencies(key)
```

## 3.4 资源管理

### 连接池管理

```python
from contextlib import contextmanager
import threading

class ConnectionPool:
    """连接池管理器"""
    
    def __init__(
        self,
        factory_func,
        min_size: int = 5,
        max_size: int = 20
    ):
        self.factory = factory_func
        self.min_size = min_size
        self.max_size = max_size
        
        self._lock = threading.Lock()
        self._pool = []
        self._in_use = set()
    
    def get_connection(self):
        """从池中获取连接"""
        with self._lock:
            # 尝试从池中获取
            if self._pool:
                conn = self._pool.pop()
            elif len(self._in_use) < self.max_size:
                conn = self.factory()
            else:
                raise PoolExhaustedError("连接池已耗尽")
            
            self._in_use[id(conn)] = conn
            return conn
    
    def return_connection(self, conn):
        """归还连接到池中"""
        with self._lock:
            if id(conn) in self._in_use:
                del self._in_use[id(conn)]
                
                if len(self._pool) < self.max_size:
                    self._pool.append(conn)
    
    @contextmanager
    def connection(self):
        """连接上下文管理器"""
        conn = self.get_connection()
        try:
            yield conn
        finally:
            self.return_connection(conn)
```

### 内存管理

```python
import gc
import weakref
from typing import Any, Dict

class MemoryManager:
    """内存管理器"""
    
    def __init__(self, max_memory_mb: int = 1024):
        self.max_memory = max_memory_mb * 1024 * 1024
        self.large_objects: Dict[str, Any] = {}
    
    def register_large_object(
        self,
        key: str,
        obj: Any,
        priority: int = 0
    ):
        """注册大对象"""
        size = self._get_size(obj)
        
        if size > self.max_memory // 10:
            self.large_objects[key] = {
                "object": weakref.ref(obj),
                "size": size,
                "priority": priority,
                "last_access": time.time()
            }
    
    def cleanup(self):
        """清理内存"""
        current_memory = self._get_memory_usage()
        
        if current_memory > self.max_memory * 0.8:
            # 按优先级和最后访问时间排序，清理低优先级对象
            sorted_objs = sorted(
                self.large_objects.values(),
                key=lambda x: (x["priority"], x["last_access"])
            )
            
            for obj_info in sorted_objs:
                if current_memory <= self.max_memory * 0.6:
                    break
                
                obj = obj_info["object"]()
                if obj is not None:
                    del obj
                
                current_memory = self._get_memory_usage()
            
            gc.collect()
    
    def _get_size(self, obj: Any) -> int:
        """获取对象大小"""
        import sys
        return sys.getsizeof(obj)
    
    def _get_memory_usage(self) -> int:
        """获取当前内存使用"""
        import psutil
        process = psutil.Process()
        return process.memory_info().rss
```

## 3.5 监控与告警

### 性能监控

```python
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Any
import logging

logger = logging.getLogger(__name__)

@dataclass
class PerformanceMetric:
    """性能指标"""
    name: str
    value: float
    unit: str
    timestamp: datetime
    tags: Dict[str, str]

class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self.metrics = []
        self.counters = {}
        self.histograms = {}
    
    def record(
        self,
        name: str,
        value: float,
        unit: str = "",
        tags: Dict[str, str] = None
    ):
        """记录指标"""
        metric = PerformanceMetric(
            name=name,
            value=value,
            unit=unit,
            timestamp=datetime.now(),
            tags=tags or {}
        )
        self.metrics.append(metric)
        
        # 输出日志
        logger.info(
            f"Metric: {name}={value}{unit} tags={tags}"
        )
    
    def time_function(self, name: str, tags: Dict[str, str] = None):
        """函数计时装饰器"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                start_time = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    status = "success"
                except Exception as e:
                    status = "error"
                    raise
                finally:
                    duration = time.perf_counter() - start_time
                    self.record(
                        name=f"{name}.duration",
                        value=duration,
                        unit="seconds",
                        tags={**(tags or {}), "status": status}
                    )
                return result
            return wrapper
        return decorator
    
    def get_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        from collections import defaultdict
        import statistics
        
        summaries = defaultdict(list)
        
        for metric in self.metrics:
            if metric.unit in ["seconds", "milliseconds"]:
                summaries[metric.name].append(metric.value)
        
        result = {}
        for name, values in summaries.items():
            result[name] = {
                "count": len(values),
                "mean": statistics.mean(values),
                "median": statistics.median(values),
                "p95": sorted(values)[int(len(values) * 0.95)],
                "max": max(values),
                "min": min(values)
            }
        
        return result
```

### 告警系统

```python
from abc import ABC, abstractmethod
from typing import Callable, List

class AlertRule:
    """告警规则"""
    
    def __init__(
        self,
        name: str,
        condition: Callable[[PerformanceMonitor], bool],
        severity: str = "warning",
        message: str = ""
    ):
        self.name = name
        self.condition = condition
        self.severity = severity
        self.message = message
    
    def check(self, monitor: PerformanceMonitor) -> List[Alert]:
        """检查是否触发告警"""
        if self.condition(monitor):
            return [Alert(
                rule_name=self.name,
                severity=self.severity,
                message=self.message,
                timestamp=datetime.now()
            )]
        return []


class AlertManager:
    """告警管理器"""
    
    def __init__(self):
        self.rules: List[AlertRule] = []
        self.alerts: List[Alert] = []
    
    def add_rule(self, rule: AlertRule):
        """添加告警规则"""
        self.rules.append(rule)
    
    def check_alerts(self, monitor: PerformanceMonitor) -> List[Alert]:
        """检查所有告警规则"""
        new_alerts = []
        
        for rule in self.rules:
            alerts = rule.check(monitor)
            new_alerts.extend(alerts)
        
        self.alerts.extend(new_alerts)
        
        # 发送告警通知
        for alert in new_alerts:
            self._send_notification(alert)
        
        return new_alerts
    
    def _send_notification(self, alert: Alert):
        """发送告警通知"""
        # 可以集成邮件、Slack、PagerDuty 等
        logger.warning(
            f"ALERT [{alert.severity}]: {alert.rule_name} - {alert.message}"
        )
```

## 3.6 练习题

### 练习 3.1：性能基准测试

**任务**：建立系统的性能基准测试框架。

**要求**：能够测量关键操作的延迟和吞吐量，建立性能基线，识别性能回归。

### 练习 3.2：优化并发处理

**任务**：优化智能体并行执行的效率。

**步骤**：首先分析当前实现的瓶颈，然后实现连接池管理，最后添加监控和限流。

### 练习 3.3：监控系统实现

**任务**：实现完整的性能监控和告警系统。

**要求**：系统能够收集关键指标，提供实时仪表板，支持告警规则配置。
