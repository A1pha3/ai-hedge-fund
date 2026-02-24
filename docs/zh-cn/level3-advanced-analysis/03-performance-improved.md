# 第三章：性能优化策略 ⭐⭐⭐

**本章级别**：Level 3 - 进阶分析  
**预计学习时间**：3-4 小时  
**前置知识**：熟悉 Python 基础编程、了解异步编程概念

---

## 学习目标

完成本章节学习后，你将能够：

### 基础目标（必掌握）

- [ ] 理解性能瓶颈识别的关键指标（延迟、吞吐量、资源利用率）
- [ ] 掌握 `cProfile` 等性能分析工具的使用方法
- [ ] 理解并发与异步编程的基础概念和应用场景
- [ ] 掌握基础的缓存策略和实现方法
- [ ] 了解资源管理的基本原则（连接池、内存管理）

### 进阶目标（建议掌握）

- [ ] 能够独立设计和实现多层缓存架构（L1+L2）
- [ ] 掌握连接池管理的最佳实践和优化技巧
- [ ] 能够搭建完整的性能监控系统（指标收集、告警）
- [ ] 能够分析和解决常见的性能问题（N+1 查询、内存泄漏等）
- [ ] 理解异步编程的适用场景和注意事项

### 专家目标（挑战）

- [ ] 设计智能缓存失效机制和依赖关系管理
- [ ] 实现自适应资源管理和自动扩缩容策略
- [ ] 制定团队性能优化最佳实践规范和检查清单
- [ ] 能够诊断和解决复杂的分布式性能问题
- [ ] 设计性能回归检测和持续集成方案

---

## 3.1 性能分析基础

### 3.1.1 性能瓶颈识别

在进行优化之前，首先需要识别系统的性能瓶颈。盲目优化往往适得其反——你可能花费大量时间优化一个不是瓶颈的地方。

**为什么需要系统化的性能分析？**

> 📚 **专家经验**：在优化之前，先用数据说话。性能分析工具可以帮助你：
> 1. **定位热点**：找到最耗时的代码路径（80% 的性能问题往往来自 20% 的代码）
> 2. **量化问题**：用数据验证你的假设（不要凭感觉优化）
> 3. **跟踪变化**：比较优化前后的性能差异

#### 性能分析工具

Python 提供了多种性能分析工具：

| 工具 | 类型 | 优点 | 缺点 | 适用场景 |
|------|------|------|------|----------|
| `cProfile` | 内置统计 | 标准库、性能好 | 开销较大 | 生产环境快速分析 |
| `line_profiler` | 逐行分析 | 精确定位 | 需要额外安装 | 开发环境深度分析 |
| `memory_profiler` | 内存分析 | 追踪内存使用 | 较慢 | 内存泄漏诊断 |
| `py-spy` | 采样分析 | 低开销、可视化 | 需要额外安装 | 长时间运行的服务 |

#### 实践：使用 cProfile 进行性能分析

**cProfile（Python 内置的性能分析工具）**：可以统计函数调用次数、执行时间等关键指标。

```python
import cProfile
import pstats
from functools import wraps

def profile(func):
    """性能分析装饰器

    用于测量函数的执行时间和调用次数，帮助识别性能瓶颈。
    使用方法：
        @profile
        def my_function():
            # 你的代码
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        result = profiler.runcall(func, *args, **kwargs)

        # 输出性能统计
        stats = pstats.Stats(profiler)
        stats.sort_stats('cumulative')  # 按累计时间排序
        stats.print_stats(20)  # 显示前 20 个最耗时的函数

        return result
    return wrapper

@profile
def run_analysis():
    """运行分析（带性能分析）"""
    # 分析代码
    pass
```

**如何解读性能报告？**

```
ncalls  tottime  percall  cumtime  percall filename:lineno(function)
     1    0.003    0.003    0.045    0.045 my_script.py:10(run_analysis)
   100    0.020    0.000    0.040    0.000 external_lib.py:50(process_data)
```

- `ncalls`：调用次数
- `tottime`：函数自身执行时间（不包括子函数）
- `cumtime`：累计执行时间（包括子函数）← **优化重点**
- `percall`：每次调用平均时间

**专家提示**：优先优化 `cumtime` 最高的函数，而不是 `tottime` 最高的函数。

---

### 3.1.2 关键性能指标

理解性能指标是优化的基础。你需要知道"什么是好的性能"。

**延迟（Latency）**：从请求发出到收到响应的时间

> **影响**：直接决定用户体验
>
> **目标参考**：
> - 网页加载：< 2s（优秀），< 3s（可接受），> 3s（差）
> - API 调用：< 100ms（优秀），< 500ms（可接受），> 1s（差）
> - 数据库查询：< 10ms（简单），< 100ms（复杂）

**吞吐量（Throughput）**：单位时间内处理的请求数量

> **影响**：决定系统容量和成本
>
> **目标参考**：
> - Web 服务：> 1000 req/s（单核）
> - 数据库：> 10000 qps（简单查询）

**资源利用率**：CPU、内存、I/O 等资源的使用效率

> **目标**：
> - CPU：70-80%（高峰期）
> - 内存：< 80%（避免 OOM）
> - I/O：< 80%（避免队列堆积）

**三者关系**：
```
高吞吐量 × 低延迟 = 高性能

资源利用率过高  → 延迟增加（队列堆积）
资源利用率过低  → 浪费资源（成本高）
```

---

## 3.2 并发与异步优化

### 3.2.1 智能体并行执行

**核心问题**：智能体（Agent）串行执行效率低，如何通过并发提高吞吐量？

**为什么需要并发？**

想象一下，你需要向 100 个智能体发送请求并收集结果：
- **串行方式**：100 × 1s = 100s（假设每个请求 1s）
- **并发方式**：100s / 10（并发数）= 10s

**性能提升**：10 倍！

#### 并发模型选择

Python 中有多种并发模型，选择正确的模型至关重要：

| 模型 | 类型 | 适合场景 | 优点 | 缺点 |
|------|------|----------|------|------|
| **ThreadPoolExecutor** | 线程池 | I/O 密集型（网络、文件） | 轻量、启动快 | 受 GIL 限制 |
| **ProcessPoolExecutor** | 进程池 | CPU 密集型（计算） | 绕过 GIL | 重量级、IPC 开销 |
| **asyncio** | 协程 | 大量 I/O 并发 | 高效、低开销 | 异步学习曲线 |

**GIL（全局解释器锁）**：Python 解释器的一个机制，同一时刻只有一个线程执行 Python 字节码。

**决策指南**：
```
你的任务主要是网络请求、数据库查询？ → ThreadPoolExecutor
你的任务主要是数值计算、数据处理？   → ProcessPoolExecutor
你需要管理成千上万个并发连接？      → asyncio
```

#### 实现并行执行

```python
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import List, Dict, Any

class AgentExecutor:
    """智能体并行执行器

    支持线程池和进程池两种并发模式，根据任务类型自动选择合适的执行器。
    """

    def __init__(
        self,
        max_workers: int = None,
        use_multiprocessing: bool = False
    ):
        # 默认工作线程数：(CPU 核心数) + 4
        self.max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
        self.use_multiprocessing = use_multiprocessing

        # 根据任务类型选择执行器
        if use_multiprocessing:
            self.executor = ProcessPoolExecutor(max_workers=self.max_workers)
        else:
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)

    async def run_agents_async(
        self,
        agents: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """异步并行运行多个智能体

        Args:
            agents: 智能体列表，每个智能体包含 id 和配置

        Returns:
            执行结果列表，包含成功和失败的结果
        """
        loop = asyncio.get_event_loop()

        # 创建所有任务
        tasks = [
            loop.run_in_executor(
                self.executor,
                self._run_single_agent,
                agent
            )
            for agent in agents
        ]

        # 并发执行所有任务
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常，统一返回格式
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
        """运行单个智能体（同步方法）

        Args:
            agent: 智能体配置

        Returns:
            智能体执行结果
        """
        # TODO: 实现具体的智能体执行逻辑
        pass

    def shutdown(self):
        """关闭执行器，释放资源"""
        self.executor.shutdown(wait=True)
```

**为什么使用 `asyncio.gather` 而不是 `await`？**

```python
# ❌ 错误方式：顺序等待
results = []
for agent in agents:
    result = await run_single_agent(agent)  # 每次等待完成后才执行下一个
    results.append(result)

# ✅ 正确方式：并发等待
tasks = [run_single_agent(agent) for agent in agents]
results = await asyncio.gather(*tasks)  # 同时启动所有任务，等待全部完成
```

---

### 3.2.2 异步数据获取

**核心问题**：如何高效地发起大量 HTTP 请求并处理响应？

**为什么需要异步 I/O？**

HTTP 请求的大部分时间都花在"等待"上（网络延迟、服务器处理）。同步方式会阻塞整个线程，而异步方式可以在等待时处理其他请求。

#### Semaphore（信号量）：并发控制

**Semaphore（信号量）**：一种并发控制机制，限制同时进行的操作数量。

**为什么需要限流？**
- 保护目标服务器：避免被限流或封禁
- 保护本地资源：避免内存或连接耗尽
- 提高稳定性：避免级联失败

```python
import aiohttp
import asyncio
from typing import List, Dict, Any

class AsyncDataFetcher:
    """异步数据获取器

    使用 aiohttp 进行高效的并发 HTTP 请求，支持信号量限制并发数。
    """

    def __init__(self, max_concurrent: int = 10):
        """
        Args:
            max_concurrent: 最大并发请求数
        """
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.session = None

    async def fetch_all(
        self,
        requests: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """并发获取所有数据

        Args:
            requests: 请求列表，每个包含 id 和 url

        Returns:
            响应数据列表
        """
        async with aiohttp.ClientSession() as session:
            self.session = session

            # 创建所有任务（受信号量限制）
            tasks = [self._fetch_with_semaphore(req) for req in requests]
            results = await asyncio.gather(*tasks)

            return results

    async def _fetch_with_semaphore(
        self,
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """使用信号量限制并发

        确保同一时间最多有 max_concurrent 个请求在进行中。
        """
        async with self.semaphore:
            return await self._fetch_single(request)

    async def _fetch_single(
        self,
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """获取单个数据

        Args:
            request: 包含 id 和 url 的字典

        Returns:
            响应数据
        """
        try:
            async with self.session.get(request["url"]) as response:
                data = await response.json()
                return {
                    "id": request["id"],
                    "data": data,
                    "status": "success"
                }
        except Exception as e:
            return {
                "id": request["id"],
                "error": str(e),
                "status": "error"
            }
```

**性能对比**：
| 方式 | 100 个请求耗时 | 并发数 |
|------|--------------|--------|
| 同步（requests） | ~100s | 1 |
| 异步（aiohttp，无限制） | ~5s | 100 |
| 异步（aiohttp，限制 10） | ~10s | 10 |

**为什么限制并发数？**
- 无限制并发可能导致：
  - 目标服务器拒绝服务（429 Too Many Requests）
  - 本地端口耗尽
  - 内存溢出

---

## 3.3 缓存策略优化

### 3.3.1 多层缓存架构

**核心问题**：单一缓存层无法同时满足性能和容量需求，如何设计高效的缓存系统？

**为什么需要多层缓存？**

| 缓存类型 | 优点 | 缺点 | 典型延迟 |
|---------|------|------|----------|
| **内存缓存** | 极快、零网络开销 | 容量有限、进程隔离 | ~1μs |
| **分布式缓存（Redis）** | 容量大、跨进程共享 | 有网络延迟 | ~1ms |
| **数据库** | 持久化、容量大 | 很慢 | ~10-100ms |

**多层缓存设计（L1 + L2）**：
```
请求 → L1（内存） → 命中？返回
        ↓ 未命中
     L2（Redis） → 命中？回填 L1 + 返回
        ↓ 未命中
     数据库     → 填充 L2 + L1 + 返回
```

**性能提升**：
- L1 命中率：90% → 平均延迟：0.1μs + 0.1ms（10% × 1ms） = 0.1ms
- 无 L1：平均延迟：1ms
- **提升**：10 倍

#### 实现多层缓存

```python
from functools import lru_cache
import redis
import pickle
import hashlib
from typing import Any, Optional
import time

class CacheManager:
    """多级缓存管理器

    实现 L1（内存）+ L2（Redis）双层缓存架构。
    """

    def __init__(
        self,
        memory_cache_size: int = 1000,
        redis_url: Optional[str] = None,
        default_ttl: int = 3600
    ):
        """
        Args:
            memory_cache_size: L1 缓存大小
            redis_url: Redis 连接 URL（可选）
            default_ttl: 默认缓存过期时间（秒）
        """
        # L1: 内存缓存（使用 LRU 淘汰策略）
        self.memory_cache = LRUCache(max_size=memory_cache_size)

        # L2: Redis 分布式缓存
        self.redis_client = None
        if redis_url:
            self.redis_client = redis.from_url(redis_url)

        self.default_ttl = default_ttl

    def get(self, key: str) -> Any:
        """获取缓存（多层查询）

        查询顺序：L1 → L2 → 返回 None
        L2 命中后自动回填 L1（缓存预热）
        """
        # L1: 内存缓存
        value = self.memory_cache.get(key)
        if value is not None:
            return value

        # L2: Redis
        if self.redis_client:
            redis_value = self.redis_client.get(key)
            if redis_value:
                value = pickle.loads(redis_value)
                # 回填 L1（下次访问更快）
                self.memory_cache.set(key, value)
                return value

        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ):
        """设置缓存（多层写入）

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
        """
        ttl = ttl or self.default_ttl

        # L1: 内存缓存（不过期，由 LRU 自动淘汰）
        self.memory_cache.set(key, value)

        # L2: Redis（设置 TTL）
        if self.redis_client:
            self.redis_client.setex(
                key,
                ttl,
                pickle.dumps(value)
            )

    def invalidate(self, key: str):
        """使缓存失效（多层删除）

        同时删除 L1 和 L2 中的缓存。
        """
        self.memory_cache.delete(key)
        if self.redis_client:
            self.redis_client.delete(key)

    def clear(self):
        """清空所有缓存"""
        self.memory_cache.clear()
        if self.redis_client:
            self.redis_client.flushdb()


class LRUCache:
    """LRU（Least Recently Used）缓存实现

    当缓存满时，自动淘汰最久未使用的数据。
    """

    def __init__(self, max_size: int = 1000):
        """
        Args:
            max_size: 最大缓存数量
        """
        self.max_size = max_size
        self.cache = {}  # key: (value, access_time)
        self.access_order = []  # 记录访问顺序

    def get(self, key: str) -> Any:
        """获取缓存值"""
        if key in self.cache:
            # 更新访问时间
            value = self.cache[key]
            self.access_order.remove(key)
            self.access_order.append(key)
            return value
        return None

    def set(self, key: str, value: Any):
        """设置缓存值"""
        if key in self.cache:
            # 更新现有值
            self.cache[key] = value
            self.access_order.remove(key)
        elif len(self.cache) >= self.max_size:
            # 淘汰最久未使用的数据
            oldest_key = self.access_order.pop(0)
            del self.cache[oldest_key]

        self.cache[key] = value
        self.access_order.append(key)

    def delete(self, key: str):
        """删除缓存"""
        if key in self.cache:
            del self.cache[key]
            self.access_order.remove(key)

    def clear(self):
        """清空缓存"""
        self.cache.clear()
        self.access_order.clear()
```

**为什么使用 LRU 淘汰策略？**

**LRU（Least Recently Used）**：淘汰最久未使用的数据。

**核心思想**：如果数据最近被访问过，那么将来很可能还会被访问。

**对比其他策略**：
| 策略 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **LRU** | 符合时间局部性 | 实现稍复杂 | 通用场景 |
| FIFO | 简单 | 可能淘汰热点数据 | 简单场景 |
| LFU | 符合频率局部性 | 无法应对模式变化 | 稳定场景 |

---

### 3.3.2 智能缓存失效

**核心问题**：数据更新后，如何保证缓存一致性？

**为什么需要智能失效？**

```python
# ❌ 问题场景
cache.set("user_123", user_data)  # 缓存用户数据
update_user(123, {"name": "New Name"})  # 更新数据库
# ❌ 缓存还是旧数据！用户看到的过时信息
```

**解决方案**：
1. **手动失效**：更新后手动删除缓存
2. **TTL（过期时间）**：自动过期
3. **智能依赖追踪**：自动失效相关缓存

```python
class SmartCacheInvalidator:
    """智能缓存失效器

    维护缓存依赖关系图，当源数据更新时自动失效相关缓存。
    """

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self.dependency_graph = DependencyGraph()

    def register_dependency(
        self,
        cache_key: str,
        dependencies: List[str]
    ):
        """注册缓存依赖关系

        Args:
            cache_key: 缓存键
            dependencies: 该缓存依赖的数据源（如 "user_123"）

        示例：
            register_dependency(
                "user_orders_123",
                ["user_123", "orders"]
            )
            # 当 user_123 或 orders 更新时，自动失效 user_orders_123
        """
        for dep in dependencies:
            self.dependency_graph.add_edge(dep, cache_key)

    def invalidate_dependencies(self, source_key: str):
        """使依赖源失效

        当 source_key 更新时，失效所有依赖于它的缓存。
        """
        # 获取所有依赖于 source_key 的缓存键
        dependent_keys = self.dependency_graph.get_dependents(source_key)

        # 批量失效
        for key in dependent_keys:
            self.cache.invalidate(key)

    def with_invalidation(
        self,
        source_keys: List[str]
    ):
        """上下文管理器：在更新时自动失效缓存

        使用示例：
            with invalidator.with_invalidation(["user_123"]):
                update_user(123, {"name": "New Name"})
                # 退出上下文时自动失效相关缓存
        """
        return CacheInvalidationContext(self, source_keys)


class DependencyGraph:
    """依赖关系图（简化版）"""

    def __init__(self):
        self.graph = {}  # source: [cache_keys]

    def add_edge(self, source: str, cache_key: str):
        """添加依赖关系"""
        if source not in self.graph:
            self.graph[source] = []
        self.graph[source].append(cache_key)

    def get_dependents(self, source: str) -> List[str]:
        """获取依赖于 source 的所有缓存键"""
        return self.graph.get(source, [])


class CacheInvalidationContext:
    """缓存失效上下文管理器"""

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

**为什么使用上下文管理器？**

```python
# ❌ 传统方式：容易忘记失效缓存
update_user(123, data)
invalidate_cache("user_123")
invalidate_cache("user_orders_123")  # 可能遗漏

# ✅ 使用上下文管理器：自动失效
with invalidator.with_invalidation(["user_123"]):
    update_user(123, data)
    # 退出时自动失效所有相关缓存
```

---

## 3.4 资源管理

### 3.4.1 连接池管理

**核心问题**：频繁创建和销毁连接开销很大，如何高效管理数据库、HTTP 等连接？

**为什么需要连接池？**

```
无连接池：
    创建连接（100ms）→ 执行查询（10ms）→ 销毁连接（100ms）
    总计：210ms / 查询

连接池：
    复用连接 → 执行查询（10ms）
    总计：10ms / 查询（首次创建后）

性能提升：21 倍！
```

#### 实现连接池

```python
from contextlib import contextmanager
import threading

class ConnectionPool:
    """连接池管理器

    管理数据库、HTTP 等连接的复用，避免频繁创建和销毁的开销。
    """

    def __init__(
        self,
        factory_func,
        min_size: int = 5,
        max_size: int = 20
    ):
        """
        Args:
            factory_func: 创建连接的函数
            min_size: 最小连接数（预热）
            max_size: 最大连接数
        """
        self.factory = factory_func
        self.min_size = min_size
        self.max_size = max_size

        self._lock = threading.Lock()
        self._pool = []  # 空闲连接列表
        self._in_use = set()  # 正在使用的连接（用 id 标识）

        # 预热连接池
        self._initialize_pool()

    def _initialize_pool(self):
        """初始化连接池（创建最小数量的连接）"""
        for _ in range(self.min_size):
            conn = self.factory()
            self._pool.append(conn)

    def get_connection(self):
        """从池中获取连接"""
        with self._lock:
            # 尝试从池中获取空闲连接
            if self._pool:
                conn = self._pool.pop()
            elif len(self._in_use) < self.max_size:
                # 池为空但未达上限，创建新连接
                conn = self.factory()
            else:
                # 连接池已耗尽
                raise PoolExhaustedError(
                    f"连接池已耗尽（max={self.max_size}）"
                )

            self._in_use[id(conn)] = conn
            return conn

    def return_connection(self, conn):
        """归还连接到池中"""
        with self._lock:
            if id(conn) in self._in_use:
                del self._in_use[id(conn)]

                # 检查连接是否仍然有效（可选）
                if self._is_connection_valid(conn):
                    if len(self._pool) < self.max_size:
                        self._pool.append(conn)
                else:
                    # 连接已失效，丢弃
                    self._close_connection(conn)

    @contextmanager
    def connection(self):
        """连接上下文管理器

        使用示例：
            with pool.connection() as conn:
                conn.execute("SELECT * FROM users")
            # 自动归还连接
        """
        conn = self.get_connection()
        try:
            yield conn
        finally:
            self.return_connection(conn)

    def _is_connection_valid(self, conn) -> bool:
        """检查连接是否有效（子类可覆盖）"""
        return True

    def _close_connection(self, conn):
        """关闭连接（子类可覆盖）"""
        pass


class PoolExhaustedError(Exception):
    """连接池耗尽异常"""
    pass
```

**为什么使用上下文管理器？**

```python
# ❌ 容易忘记归还连接
conn = pool.get_connection()
try:
    conn.execute(query)
finally:
    pool.return_connection(conn)  # 可能忘记

# ✅ 自动归还连接
with pool.connection() as conn:
    conn.execute(query)
# 自动调用 return_connection
```

---

### 3.4.2 内存管理

**核心问题**：如何避免内存泄漏和 OOM（Out of Memory）？

**为什么需要主动内存管理？**

Python 有垃圾回收机制，但在某些场景下仍可能导致内存问题：
- **循环引用**：对象互相引用，无法自动回收
- **大对象积累**：缓存、图片等大对象未及时清理
- **全局变量**：长期持有大量数据

#### 实现内存管理

```python
import gc
import weakref
from typing import Any, Dict
import time

class MemoryManager:
    """内存管理器

    监控内存使用，自动清理低优先级的大对象。
    """

    def __init__(self, max_memory_mb: int = 1024):
        """
        Args:
            max_memory_mb: 最大内存限制（MB）
        """
        self.max_memory = max_memory_mb * 1024 * 1024  # 转换为字节
        self.large_objects: Dict[str, Any] = {}

    def register_large_object(
        self,
        key: str,
        obj: Any,
        priority: int = 0
    ):
        """注册大对象

        Args:
            key: 对象标识
            obj: 大对象（图片、数据集等）
            priority: 优先级（0=最低，10=最高，越不容易被清理）
        """
        size = self._get_size(obj)

        # 只管理大对象（> max_memory 的 10%）
        if size > self.max_memory // 10:
            self.large_objects[key] = {
                "object": weakref.ref(obj),  # 使用弱引用，不增加引用计数
                "size": size,
                "priority": priority,
                "last_access": time.time()
            }

    def cleanup(self):
        """清理内存

        当内存使用超过阈值时，自动清理低优先级对象。
        """
        current_memory = self._get_memory_usage()

        if current_memory > self.max_memory * 0.8:  # 超过 80% 触发清理
            # 按优先级（升序）和最后访问时间（升序）排序
            sorted_objs = sorted(
                self.large_objects.values(),
                key=lambda x: (x["priority"], x["last_access"])
            )

            # 清理低优先级对象，直到内存降到 60%
            for obj_info in sorted_objs:
                if current_memory <= self.max_memory * 0.6:
                    break

                obj = obj_info["object"]()
                if obj is not None:
                    del obj  # 删除对象，释放内存
                    del self.large_objects[obj_info.get("key")]

                current_memory = self._get_memory_usage()

            # 强制垃圾回收
            gc.collect()

    def _get_size(self, obj: Any) -> int:
        """获取对象大小（简化版）"""
        import sys
        return sys.getsizeof(obj)

    def _get_memory_usage(self) -> int:
        """获取当前进程的内存使用"""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss  # RSS（Resident Set Size）
        except ImportError:
            # 如果没有 psutil，返回估算值
            return 0
```

**为什么使用弱引用（weakref）？**

```python
# ❌ 普通引用：增加引用计数，阻止垃圾回收
objects = []
obj = {"data": "large"}
objects.append(obj)  # obj 不会被垃圾回收

# ✅ 弱引用：不增加引用计数
import weakref
objects = []
obj = {"data": "large"}
objects.append(weakref.ref(obj))  # obj 仍可被垃圾回收
```

---

## 3.5 监控与告警

### 3.5.1 性能监控

**核心问题**：如何持续跟踪系统性能，及时发现异常？

**为什么需要监控？**

> 📚 **专家经验**："你无法优化你无法测量的东西。"

监控的价值：
1. **趋势分析**：发现性能退化（P99 延迟从 100ms 升到 500ms）
2. **问题定位**：快速找到问题根源（哪个 API 变慢了）
3. **容量规划**：预测何时需要扩容（流量趋势）
4. **SLA 合规**：确保满足服务水平协议

#### 实现性能监控

```python
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Any
import logging
from functools import wraps

logger = logging.getLogger(__name__)

@dataclass
class PerformanceMetric:
    """性能指标数据类"""
    name: str  # 指标名称（如 "api.duration"）
    value: float  # 指标值
    unit: str  # 单位（如 "ms", "seconds"）
    timestamp: datetime  # 记录时间
    tags: Dict[str, str]  # 标签（如 {"endpoint": "/api/users"}）

class PerformanceMonitor:
    """性能监控器

    收集、记录和分析性能指标。
    """

    def __init__(self):
        self.metrics = []  # 存储所有指标
        self.counters = {}  # 计数器（如请求数）
        self.histograms = {}  # 直方图（如延迟分布）

    def record(
        self,
        name: str,
        value: float,
        unit: str = "",
        tags: Dict[str, str] = None
    ):
        """记录指标

        Args:
            name: 指标名称
            value: 指标值
            unit: 单位
            tags: 标签（用于聚合和分析）
        """
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
        """函数计时装饰器

        自动记录函数执行时间。

        使用示例：
            @monitor.time_function("api.users.get")
            def get_user(user_id):
                # ...
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                start_time = time.perf_counter()
                status = "success"
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    status = "error"
                    logger.error(f"Function {func.__name__} failed: {e}")
                    raise
                finally:
                    duration = time.perf_counter() - start_time
                    self.record(
                        name=f"{name}.duration",
                        value=duration,
                        unit="seconds",
                        tags={**(tags or {}), "status": status}
                    )
            return wrapper
        return decorator

    def increment(self, name: str, value: int = 1, tags: Dict[str, str] = None):
        """增加计数器

        用于统计事件次数（如请求数、错误数）。
        """
        key = self._make_key(name, tags)
        self.counters[key] = self.counters.get(key, 0) + value

    def get_summary(self) -> Dict[str, Any]:
        """获取性能摘要

        计算统计指标（平均值、中位数、P95、最大值）。
        """
        from collections import defaultdict
        import statistics

        summaries = defaultdict(list)

        # 按指标名称分组
        for metric in self.metrics:
            if metric.unit in ["seconds", "milliseconds", "ms"]:
                summaries[metric.name].append(metric.value)

        result = {}
        for name, values in summaries.items():
            if not values:
                continue

            sorted_values = sorted(values)
            result[name] = {
                "count": len(values),
                "mean": statistics.mean(values),
                "median": statistics.median(values),
                "p95": sorted_values[int(len(values) * 0.95)],  # 95 百分位
                "p99": sorted_values[int(len(values) * 0.99)],  # 99 百分位
                "max": max(values),
                "min": min(values)
            }

        return result

    def _make_key(self, name: str, tags: Dict[str, str] = None) -> str:
        """生成指标键"""
        if tags:
            tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
            return f"{name}?{tag_str}"
        return name
```

**为什么关注 P95 和 P99？**

```
假设你的 API 有以下延迟分布：
- 平均值：100ms
- P95：500ms（95% 的请求 < 500ms）
- P99：1000ms（99% 的请求 < 1000ms）

问题：平均值掩盖了尾部延迟
→ 1% 的用户体验很差（延迟 > 1s）
→ P95/P99 更能反映真实用户体验
```

---

### 3.5.2 告警系统

**核心问题**：如何及时发现和处理性能问题？

**为什么需要告警？**

监控提供数据，告警提供行动。
- **被动响应**：用户投诉才发现问题
- **主动告警**：问题发生前或发生时立即处理

#### 实现告警系统

```python
from abc import ABC, abstractmethod
from typing import Callable, List
from datetime import datetime

@dataclass
class Alert:
    """告警数据类"""
    rule_name: str  # 规则名称
    severity: str  # 严重级别（info, warning, error, critical）
    message: str  # 告警消息
    timestamp: datetime  # 告警时间
    metrics: Dict[str, Any] = None  # 相关指标

class AlertRule:
    """告警规则

    定义何时触发告警的条件。
    """

    def __init__(
        self,
        name: str,
        condition: Callable[['PerformanceMonitor'], bool],
        severity: str = "warning",
        message: str = ""
    ):
        """
        Args:
            name: 规则名称
            condition: 条件函数（返回 True 触发告警）
            severity: 严重级别
            message: 告警消息
        """
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
    """告警管理器

    管理告警规则、检查条件和发送通知。
    """

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
        """发送告警通知

        可扩展支持邮件、Slack、PagerDuty、钉钉等。
        """
        logger.warning(
            f"ALERT [{alert.severity.upper()}]: {alert.rule_name} - {alert.message}"
        )

        # TODO: 集成其他通知渠道
        # if alert.severity in ["error", "critical"]:
        #     send_email(alert)
        #     send_slack(alert)
```

**告警规则示例**：

```python
# 创建监控器和告警管理器
monitor = PerformanceMonitor()
alert_manager = AlertManager()

# 规则 1：P99 延迟超过 1s 告警
alert_manager.add_rule(AlertRule(
    name="high_p99_latency",
    condition=lambda m: m.get_summary().get("api.duration", {}).get("p99", 0) > 1.0,
    severity="warning",
    message="API P99 延迟超过 1 秒"
))

# 规则 2：错误率超过 5% 告警
alert_manager.add_rule(AlertRule(
    name="high_error_rate",
    condition=lambda m: (m.counters.get("errors", 0) / max(m.counters.get("requests", 1), 1)) > 0.05,
    severity="critical",
    message="错误率超过 5%"
))

# 检查告警
alert_manager.check_alerts(monitor)
```

---

## 3.6 练习题

### 练习 3.1：性能基准测试 ⭐

**难度**：⭐（基础）  
**预计时间**：30 分钟

**任务**：建立系统的性能基准测试框架。

**学习目标**：
- 掌握 `cProfile` 的使用方法
- 能够测量和记录关键性能指标
- 理解 P50、P95、P99 等统计指标的含义

**具体要求**：

1. **创建性能分析装饰器**
   ```python
   @performance_monitor("user_analysis")
   def analyze_user(user_id):
       # 你的分析代码
       pass
   ```

2. **测量至少 3 个关键函数**：
   - [ ] 数据加载函数
   - [ ] 数据处理函数
   - [ ] 结果生成函数

3. **输出格式化报告**，包含：
   - [ ] 每个函数的平均执行时间
   - [ ] P95 和 P99 延迟
   - [ ] 函数调用次数

**评估标准**：
- ✅ 能够复现测试结果（多次运行误差 < 10%）
- ✅ 报告包含关键指标（平均值、P95、P99）
- ✅ 代码可读性良好，有适当注释

**参考答案**：
```python
import cProfile
import pstats
from functools import wraps
from typing import Dict, List
import time

class PerformanceBenchmark:
    """性能基准测试器"""

    def __init__(self):
        self.metrics = {}

    def measure(self, func_name: str):
        """测量装饰器"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # 使用 cProfile 分析
                profiler = cProfile.Profile()
                profiler.enable()

                start_time = time.perf_counter()
                result = func(*args, **kwargs)
                duration = time.perf_counter() - start_time

                profiler.disable()

                # 收集统计信息
                stats = pstats.Stats(profiler)
                total_calls = stats.total_calls

                # 记录指标
                if func_name not in self.metrics:
                    self.metrics[func_name] = []
                self.metrics[func_name].append(duration)

                return result
            return wrapper
        return decorator

    def report(self) -> Dict:
        """生成性能报告"""
        from statistics import mean, median

        report = {}
        for func_name, durations in self.metrics.items():
            sorted_durations = sorted(durations)
            report[func_name] = {
                "count": len(durations),
                "mean": mean(durations),
                "median": median(sorted_durations),
                "p95": sorted_durations[int(len(durations) * 0.95)],
                "p99": sorted_durations[int(len(durations) * 0.99)],
                "min": min(durations),
                "max": max(durations)
            }

        return report

# 使用示例
benchmark = PerformanceBenchmark()

@benchmark.measure("load_data")
def load_data():
    # 模拟数据加载
    time.sleep(0.1)
    return {"data": "test"}

# 多次调用建立基准
for _ in range(100):
    load_data()

# 生成报告
print(benchmark.report())
```

**扩展挑战** ⭐⭐：
- 添加性能回归检测（比较两次基准测试结果）
- 支持对比多个版本的性能数据
- 生成可视化图表（使用 matplotlib）

---

### 练习 3.2：优化并发处理 ⭐⭐

**难度**：⭐⭐（进阶）  
**预计时间**：1 小时

**任务**：优化智能体并行执行的效率。

**学习目标**：
- 理解并发模型的选择（线程池 vs 进程池 vs asyncio）
- 掌握连接池的使用和配置
- 学会分析和优化并发性能

**步骤 1：分析当前实现的瓶颈**

```python
# 当前实现：串行执行
def run_agents_serial(agents: List[Dict]) -> List[Dict]:
    results = []
    for agent in agents:
        result = run_single_agent(agent)  # 每次等待 1s
        results.append(result)
    return results

# 问题：100 个智能体需要 100 秒
```

**任务清单**：
- [ ] 使用 `cProfile` 分析当前实现，识别瓶颈
- [ ] 确定任务类型（I/O 密集型还是 CPU 密集型）
- [ ] 记录基线性能（平均延迟、吞吐量）

**步骤 2：实现并发执行**

**要求**：
1. 根据任务类型选择合适的并发模型
2. 实现连接池管理（数据库、HTTP）
3. 添加并发数限制（避免资源耗尽）
4. 实现错误处理和重试机制

```python
# 提示：使用 AgentExecutor 类
executor = AgentExecutor(max_workers=10, use_multiprocessing=False)
results = await executor.run_agents_async(agents)
```

**评估标准**：
- ✅ 性能提升 > 5 倍（相对于串行）
- ✅ 能够正确处理异常和失败
- ✅ 资源使用合理（CPU、内存）

**步骤 3：添加监控和限流**

- [ ] 集成 `PerformanceMonitor` 记录执行时间
- [ ] 实现动态并发数调整（根据延迟自动调整）
- [ ] 添加熔断机制（错误率过高时自动降级）

**参考答案**：
```python
# 完整实现见 3.2.1 节
# 关键点：
# 1. I/O 密集型使用 ThreadPoolExecutor
# 2. CPU 密集型使用 ProcessPoolExecutor
# 3. 使用 asyncio.gather 并发等待
# 4. 使用信号量限制并发数
```

**扩展挑战** ⭐⭐⭐：
- 实现工作窃取（Work Stealing）调度算法
- 添加优先级队列（高优先级任务优先执行）
- 实现自适应并发控制（根据响应时间自动调整）

---

### 练习 3.3：多层缓存实现 ⭐⭐

**难度**：⭐⭐（进阶）  
**预计时间**：1.5 小时

**任务**：实现完整的 L1 + L2 多层缓存系统。

**学习目标**：
- 理解多层缓存的设计原理
- 掌握 LRU 缓存淘汰算法
- 学会设计智能缓存失效机制

**步骤 1：实现 LRU 缓存**

**要求**：
1. 实现基本的 LRU 缓存类
2. 支持设置最大容量
3. 实现 get/set/delete 操作

```python
class LRUCache:
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache = {}
        self.access_order = []

    def get(self, key: str) -> Any:
        # TODO: 实现获取逻辑，更新访问顺序
        pass

    def set(self, key: str, value: Any):
        # TODO: 实现设置逻辑，淘汰最久未使用的数据
        pass

    def delete(self, key: str):
        # TODO: 实现删除逻辑
        pass
```

**评估标准**：
- ✅ 正确实现 LRU 淘汰策略
- ✅ 时间复杂度为 O(1)（使用字典 + 双向链表）
- ✅ 代码有单元测试覆盖

**步骤 2：集成 Redis 作为 L2 缓存**

**要求**：
1. 连接到 Redis 实例（或使用模拟）
2. 实现缓存的读写逻辑（L1 → L2 → 源）
3. 实现 L2 到 L1 的回填机制

```python
class TwoLevelCache:
    def __init__(self, l1_size: int = 1000, redis_url: str = None):
        self.l1 = LRUCache(max_size=l1_size)
        self.l2 = RedisCache(url=redis_url) if redis_url else None

    def get(self, key: str) -> Any:
        # TODO: L1 → L2 → None
        # L2 命中后回填 L1
        pass

    def set(self, key: str, value: Any, ttl: int = 3600):
        # TODO: 同时写入 L1 和 L2
        pass
```

**评估标准**：
- ✅ L1 命中率 > 80%（测试数据）
- ✅ 正确处理缓存穿透和缓存雪崩
- ✅ 有 TTL 过期机制

**步骤 3：实现智能缓存失效**

**要求**：
1. 维护依赖关系图
2. 实现自动失效机制
3. 提供上下文管理器简化使用

```python
class SmartCacheInvalidator:
    def __init__(self, cache: TwoLevelCache):
        self.cache = cache
        self.dependency_graph = {}

    def register(self, cache_key: str, dependencies: List[str]):
        # TODO: 注册依赖关系
        pass

    def invalidate(self, source_key: str):
        # TODO: 失效所有依赖该源的数据
        pass
```

**评估标准**：
- ✅ 能够追踪多层依赖关系
- ✅ 更新数据后自动失效相关缓存
- ✅ 提供易用的 API

**参考答案**：
见 3.3 节完整实现。

**扩展挑战** ⭐⭐⭐：
- 实现缓存预热（启动时加载热点数据）
- 添加缓存统计（命中率、吞吐量）
- 实现分布式缓存一致性（使用 Redis Pub/Sub）

---

### 练习 3.4：监控系统搭建 ⭐⭐⭐

**难度**：⭐⭐⭐（专家）  
**预计时间**：2 小时

**任务**：实现完整的性能监控和告警系统。

**学习目标**：
- 掌握性能指标的收集和分析
- 学会设计和实现告警规则
- 理解如何构建可观测性系统

**步骤 1：实现指标收集**

**要求**：
1. 支持多种指标类型（Counter、Gauge、Histogram）
2. 支持标签（tags）进行分组聚合
3. 支持指标采样和聚合

```python
class MetricsCollector:
    def __init__(self):
        self.counters = {}  # 计数器（只增不减）
        self.gauges = {}    # 仪表盘（可增可减）
        self.histograms = {}  # 直方图（分布统计）

    def increment(self, name: str, value: float = 1, tags: Dict = None):
        # TODO: 增加计数器
        pass

    def set(self, name: str, value: float, tags: Dict = None):
        # TODO: 设置仪表盘值
        pass

    def observe(self, name: str, value: float, tags: Dict = None):
        # TODO: 记录直方图观测值
        pass
```

**评估标准**：
- ✅ 支持至少 3 种指标类型
- ✅ 标签正确分组聚合
- ✅ 线程安全（使用锁）

**步骤 2：实现告警规则引擎**

**要求**：
1. 支持多种告警条件（阈值、趋势、异常）
2. 支持告警级别（info、warning、error、critical）
3. 支持告警去重和抑制

```python
class AlertEngine:
    def __init__(self):
        self.rules = []
        self.active_alerts = {}

    def add_rule(self, rule: AlertRule):
        # TODO: 添加规则
        pass

    def evaluate(self, metrics: MetricsCollector) -> List[Alert]:
        # TODO: 评估所有规则，返回触发的告警
        pass
```

**评估标准**：
- ✅ 至少实现 5 个常见告警规则
- ✅ 告警去重（相同告警不重复发送）
- ✅ 支持告警抑制（依赖关系、维护窗口）

**步骤 3：集成通知渠道**

**要求**：
1. 支持至少 2 种通知方式（邮件、Slack、钉钉、企业微信）
2. 实现告警升级机制（未处理自动升级）
3. 实现告警确认和关闭流程

```python
class Notifier:
    def __init__(self):
        self.channels = {}

    def register_channel(self, name: str, channel: NotificationChannel):
        # TODO: 注册通知渠道
        pass

    def send(self, alert: Alert, channels: List[str] = None):
        # TODO: 发送告警通知
        pass
```

**评估标准**：
- ✅ 至少集成 2 种通知渠道
- ✅ 告警内容清晰、可操作
- ✅ 支持告警路由（根据级别、标签路由到不同渠道）

**步骤 4：构建实时仪表板（可选）**

**要求**：
1. 使用 Grafana 或自定义 Web 界面展示指标
2. 支持查询和过滤
3. 支持告警状态展示

**评估标准**：
- ✅ 能够查看关键指标趋势
- ✅ 能够查询历史数据
- ✅ 能够查看告警历史

**参考答案**：
见 3.5 节完整实现。

**扩展挑战** ⭐⭐⭐⭐：
- 集成 Prometheus + Grafana（工业级监控栈）
- 实现分布式追踪（使用 Jaeger 或 Zipkin）
- 实现智能异常检测（使用机器学习）

---

## 总结

本章我们学习了：

### 核心概念

| 概念 | 关键要点 |
|------|----------|
| **性能分析** | 使用 `cProfile` 定位热点，关注 P95/P99 |
| **并发优化** | I/O 密集型用线程池，CPU 密集型用进程池 |
| **多层缓存** | L1（内存）+ L2（Redis），提升 10 倍性能 |
| **连接池** | 避免频繁创建连接，提升 20 倍性能 |
| **内存管理** | 使用弱引用、LRU 淘汰、自动清理 |
| **监控告警** | 收集指标、设置规则、主动告警 |

### 性能优化检查清单

优化前，请确认：

- [ ] 已使用 `cProfile` 分析，识别了真正的瓶颈
- [ ] 建立了性能基线（可以对比优化前后）
- [ ] 理解了优化方案的权衡（优缺点、适用场景）
- [ ] 添加了性能监控，可以跟踪优化效果
- [ ] 考虑了边界条件（空数据、异常情况）
- [ ] 编写了单元测试，确保优化不破坏功能

### 常见性能问题速查

| 问题 | 症状 | 原因 | 解决方案 |
|------|------|------|----------|
| N+1 查询 | 数据库查询次数随数据量线性增长 | 循环中查询数据库 | 批量查询、JOIN |
| 缓存穿透 | 大量请求未命中缓存，直击数据库 | 查询不存在的数据 | 缓存空值、布隆过滤器 |
| 缓存雪崩 | 大量缓存同时过期，请求压垮数据库 | 相同 TTL | TTL 加随机值 |
| 内存泄漏 | 内存持续增长，最终 OOM | 循环引用、全局变量 | 使用弱引用、定期清理 |
| 连接耗尽 | 无法获取新连接，请求失败 | 连接未正确关闭 | 使用连接池、上下文管理器 |

### 下一步

完成本章学习后，建议：

1. **实践应用**：在你的项目中应用本章学到的技术
2. **深入学习**：阅读相关源码（如 Redis、asyncio）
3. **扩展学习**：学习分布式追踪、服务网格等高级主题

---

## 参考资源

### 官方文档

- [Python cProfile](https://docs.python.org/3/library/profile.html)
- [Python asyncio](https://docs.python.org/3/library/asyncio.html)
- [Redis 文档](https://redis.io/documentation)
- [Prometheus](https://prometheus.io/docs/)

### 推荐阅读

- 《高性能 Python》- Micha Gorelick, Ian Ozsvald
- 《系统设计面试》- Alex Xu
- 《凤凰项目》- Gene Kim 等

### 工具推荐

- 性能分析：`py-spy`, `line_profiler`, `memory_profiler`
- 监控：Prometheus + Grafana, Datadog, New Relic
- 追踪：Jaeger, Zipkin
- APM：Sentry, Elastic APM

---

**附录：术语表**

| 英文术语 | 中文术语 | 说明 |
|---------|---------|------|
| cProfile | 性能分析工具 | Python 内置的函数级性能分析器 |
| asyncio | 异步编程库 | Python 的异步 I/O 框架 |
| ThreadPoolExecutor | 线程池 | 基于线程的并发执行器 |
| ProcessPoolExecutor | 进程池 | 基于进程的并发执行器 |
| LRU | 最近最少使用 | 缓存淘汰策略，淘汰最久未使用的数据 |
| Redis | 内存数据库 | 高性能的键值存储系统 |
| Semaphore | 信号量 | 并发控制机制，限制同时进行的操作数 |
| aiohttp | 异步 HTTP 客户端 | 基于 asyncio 的 HTTP 客户端/服务器 |
| weakref | 弱引用 | 不增加引用计数的对象引用 |
| psutil | 进程监控库 | 跨平台的系统和进程监控库 |
| RSS | 常驻内存集 | 进程使用的物理内存大小 |
| OOM | 内存溢出 | Out of Memory，程序因内存不足崩溃 |
| SLA | 服务水平协议 | 定义服务质量和性能指标 |
| APM | 应用性能监控 | Application Performance Monitoring |
| P95/P99 | 百分位数延迟 | 95%/99% 的请求延迟都低于该值 |
