# 数据层架构

> Round 19 整理。本文档描述 `src/data/` 与 `src/screening/batch_data_fetcher.py` 的整体设计、关键约定与已知限制。

## 1. 缓存层次

数据访问按以下顺序逐级回退，命中即返回：

```
+-------------------+        +-------------------+        +--------------------+
| LRUCache (内存)   |  miss  | RedisCache (可选) |  miss  | DiskCache (SQLite) |
| maxsize=128 默认  | -----> | 跨进程共享         | -----> | ~/.cache/...       |
| O(1) get/set      |        | pickle + TTL      |        | pickle + TTL       |
+-------------------+        +-------------------+        +--------------------+
                                                              |
                                                              | miss
                                                              v
                                                      +-------------------+
                                                      | DataRouter        |
                                                      |  → providers      |
                                                      +-------------------+
```

实现：`src/data/enhanced_cache.py::EnhancedCache.get()` 严格按 `LRU → Redis → Disk` 顺序查询，命中下层时**同步回填**上层；`set()` 三层同时写入。`BatchDataFetcher` 维护一个**独立**的短期内存缓存 (`BatchDataCache`，TTL=60s) 专门给批量接口去重，不与 `EnhancedCache` 共享。

### 1.1 LRU 内存缓存

- `LRUCache`（`src/data/enhanced_cache.py:25-106`）使用手写 `dict + access_time` 实现，**非线程安全**（`get/set` 都不加锁）。
- 默认 `maxsize=128`，可由 `EnhancedCache(lru_size=...)` 覆盖；CLI 无 env override。
- `_evict_lru` 用 `min(self._access_time, key=self._access_time.get)` 扫描最旧条目 —— O(n)，eviction 退化为 O(n) 而非 O(log n) 或 O(1)（`functools.OrderedDict` 才是真正的 LRU O(1)）。

### 1.2 Redis 缓存

- 客户端只读，调用方在 `is_available()` 为 False 时必须降级 —— 实际生产部署**未配置 Redis**（`REDIS_AVAILABLE` 在大多数环境为 False），故此层基本是占位。
- `default_ttl=3600s`（1 小时），单 key TTL 由 `set(..., ttl=...)` 覆盖。

### 1.3 SQLite 磁盘缓存

- 路径优先级：`DISK_CACHE_PATH` 环境变量 → `~/.cache/ai-hedge-fund/cache.sqlite`。
- 表结构 `cache(key PRIMARY KEY, value BLOB, expires_at INTEGER)`，单行单 value，**无分表/无 partition**。
- **每次 `get`/`set`/`delete` 创建一个新连接**（`self._get_conn()`）—— 不共享连接、不使用 WAL 模式、也未启用 `PRAGMA journal_mode=WAL`。
- TTL 过期检查在 read 路径上 lazy 执行（`get` 中 `if expires_at < now: self.delete`），无后台清理线程。

### 1.4 批量短期缓存（BatchDataCache）

- 独立于 `EnhancedCache`，TTL=60s，定位是"同一进程同一分钟对同一 trade_date 的批量请求去重"。
- Key 命名：`daily_price_batch:{trade_date}`、`daily_basic_batch:{trade_date}`。
- `BatchDataFetcher._cached_batch_call` 在批量接口和单 ticker 接口之间**不共享**：单 ticker 路径直接调 `_fetch_single_ticker_prices_sync` 不读批量缓存。

## 2. 缓存 Key 命名规范

### 2.1 EnhancedCache 域（`CacheAdapter._make_key`）

```
{prefix}:{provider}:{identifier}     # provider 非空
{prefix}:{identifier}               # provider 为空（向后兼容）
```

前缀清单（`CacheAdapter` 方法）：

| 方法                    | prefix       | 默认 TTL   |
|------------------------|--------------|-----------|
| `get_prices`           | `prices`     | 86400     |
| `get_financial_metrics`| `metrics`    | 604800    |
| `get_line_items`       | `line_items` | 604800    |
| `get_insider_trades`   | `insider`    | 86400     |
| `get_company_news`     | `news`       | 10800     |

### 2.2 DataRouter 域（`_get_cache_key`）

```
{provider_tag}_{DataType.value}_{ticker}_k1=v1_k2=v2
```

例：`router_price_000001_start=20260101_end=20260201`。**`provider_tag` 包含 "router"，所有路由层的 key 共享同一 namespace** —— 实际写入时 `provider=""` 走 `CacheAdapter._make_key`（无 provider 后缀），故 router 层 key 的**实际形式**是 `prices:router_price_000001_start=..._end=...`（注意 `_make_key` 把 identifier 整体作为一段）。

### 2.3 BatchDataFetcher 域

```
daily_price_batch:{trade_date}
daily_basic_batch:{trade_date}
```

预热任务（`cache_preheater.py`）用同一前缀，但**直接复用** `BatchDataCache`，不做独立命名空间。

## 3. 数据获取路由

### 3.1 A 股 / 美股识别

`DataRouter` 不做 ticker 形态识别 —— **它对所有 ticker 一视同仁**，按 provider 优先级 + 健康度依次尝试，由 `BaseDataProvider` 内部决定支持范围。`get_router()` 注册顺序：

1. `AKShareProvider` (priority 较低) — 主力 A 股
2. `TushareProvider` — A 股（带 `daily`/`daily_basic` 批量接口）
3. `MockProvider` — **始终注册**作为最终降级方案

`provider.priority` 数值越小优先级越高；`HealthMonitor` 标记为 DEGRADED 的 provider 在 `_get_healthy_providers` 中被过滤。

### 3.2 Fallback 机制

`fetch_from_providers`（`router_helpers.py:23-71`）顺序遍历 providers：

- 有 `error` → `record_failure`，下一个
- 有 `data` → `record_success`，返回
- 空 data 无 error → `record_success`（**视作 provider 正常**），`last_error="empty response"`，**继续尝试下一个**（这意味着 N 个 provider 都会被打一遍来确认确实都空）
- 异常 → `record_failure`，下一个

### 3.3 健康监控

`HealthMonitor`（`src/data/health.py`）维护每个 provider 的滑动窗口 tracker；`is_healthy` 决定 provider 是否进入候选。`router._check_health()` 每 5 分钟主动 ping 一次（`health_check_interval=300`），主动探测失败会 `record_failure` 注入 tracker。

### 3.4 BatchDataFetcher 内部 fallback

`BatchDataFetcher.fetch_prices_for_tickers` 走 `asyncio.to_thread + Semaphore(max_concurrency=8)`，**没有内建 rate limiter**，只受并发上限保护 —— 800 只 A 股的并发 fallback 仍可能在 tushare 端触发 429。

## 4. 验证与质量

### 4.1 validator_v2 规则集

16 个 `ValidationRule`（`validation_rules.py:19-148`），按 `severity` 分为 `error`/`warning`：

- `error` (5 个)：ROE/ROA/gross_margin/operating_margin/net_margin
- `warning` (11 个)：杠杆、流动性、增长、估值类

`get_prices` 调用的 `data_type` 不在规则集 —— **价格类数据无内建规则**（`validator_v2_helpers` 假设 field 总有 rule，未覆盖的 field 走 `getattr(..., None)` 返回 None，被 `allow_null=True` 放过）。

### 4.2 NaN/Inf 拦截（R15 + R18）

`_is_invalid_value`（`validator_v2_helpers.py:50-85`）三层防御：

1. **Python float** — `math.isnan || math.isinf`
2. **NumPy scalar** — 区分 `np.bool_`/`np.floating`/`np.integer`，`np.floating` 走 `np.isnan || np.isinf`
3. **字符串** — `frozenset` 包含 20 个变体（`"nan"` / `"NaN"` / `"+Inf"` / `"Infinity"` / `"-infinity"` 等）

> **R18 关键修复点**：之前 NaN/Inf 字符串会通过 `value.strip() in _STRING_NAN_VALUES` 静默放行，绕过 `min/max` 比较；现在统一以 error 拒绝。

`bool` 在第 64 行显式 `return False` —— **意即 `True` 不会触发 NaN 检查**，但若上游误把 `True` 当数字传下来，`True > 0` 和 `True < 1` 都会触发（Python 把 `True==1`），可能被规则误判。

### 4.3 调用频率

`validate_financial_metrics` 在 `validator.py:343` 和 `api_new.py:85` 中被调用，**未与 `BatchDataFetcher` 集成**——批量回填的 DataFrame **不经过 validator_v2**。如要在批量路径上加验证，需在 `_fetch_single_ticker_prices_sync` 或更上游手工接入。

## 5. 数据质量监控

`DataQualityMonitor`（`src/data/quality_monitor.py`）：

- 存储路径默认 `data/quality_reports/`，按日期分文件 `<YYYYMMDD>.jsonl`。
- 阈值 0.8 —— `quality_score < 0.8` 时 `_send_alert`（仅写 logger.error，无外发通道）。
- 每日报告 / 趋势接口只在 `metrics_history` 内存列表上计算 —— 进程重启后**历史归零**。
- `DataQualityMonitor` 是**单实例类**（无 global singleton），目前 `src/` 内零调用方（`grep` 结果仅自身），是 dead code 状态。

## 6. 性能优化

### 6.1 批量获取（BatchDataFetcher）

- `fetch_daily_prices_batch` / `fetch_daily_basic_batch` —— 全市场当日 5000+ 只 ticker 一次拉完，**避免 per-ticker 网络往返**。
- TTL=60s 缓存避免同一 trade_date 重复拉。
- `USE_BATCH_FETCHER=0/false/no/off` 可禁用（kill switch）。
- `stats()` 暴露 `batch_calls` / `batch_failures` / `single_ticker_calls` / `cache_hits`，便于回归对比。

### 6.2 并发控制

- `BatchDataFetcher._max_concurrency=8` 默认值（`asyncio.Semaphore`）。
- `cache_preheater` 用 `concurrency=4`（CLI `run_preheat` 硬编码）。

### 6.3 频率限制

- `BaseDataProvider` 实现 `_update_rate_limit` 从响应头读 `X-RateLimit-Remaining/Reset`（`base_provider.py:263-279`），但**仅 akShare/financial_datasets 端点返回标准 header**；tushare 走 SDK，无标准 header，`rate_limit_info` 返回 None。
- **tushare 实际限流靠"每分钟 200 次"的口头约定**，代码层无 enforcement。

## 7. 已知限制

| # | 限制 | 位置 |
|---|------|------|
| 1 | LRU eviction 是 O(n) 扫描 | `enhanced_cache.py:101` |
| 2 | `LRUCache` 非线程安全 | `enhanced_cache.py:39-43` |
| 3 | `DiskCache` 每次 get/set 重建连接，未启用 WAL | `enhanced_cache.py:272-275, 312-325` |
| 4 | 磁盘缓存无后台 TTL 清理线程 | `enhanced_cache.py:392-406` |
| 5 | Redis 在生产环境通常不可用，第二层是占位 | `enhanced_cache.py:131-141` |
| 6 | 价格类数据无 validator_v2 规则 | `validation_rules.py`（全无 price_*） |
| 7 | 批量回填的 DataFrame 不经过 validator_v2 | `batch_data_fetcher.py:187-213` |
| 8 | `DataQualityMonitor` 无调用方，是 dead code | `quality_monitor.py` 全文 |
| 9 | 空响应会被视为"成功"且继续尝试下一个 provider —— N 个 provider 一定全部跑完 | `router_helpers.py:58-63` |
| 10 | `BatchDataFetcher` 无内建 rate limiter，仅 Semaphore | `batch_data_fetcher.py:225-239` |
| 11 | `cache_preheater` 直接访问 `fetcher._cache` 私有属性 | `cache_preheater.py:114, 133` |
| 12 | DataRouter 写缓存时 `provider=""` 退化为旧 key 格式，与新 key 不一致 | `router.py:142-160, 91-113` |
| 13 | tushare 限流无代码层 enforcement（靠 SDK token 桶） | 整层 |
| 14 | 跨进程缓存不共享 —— DiskCache SQLite 实际上**能**共享，但 CLI/webapp 各自 `get_enhanced_cache()` 单例运行在各自进程 | 架构层面 |

## 8. 缓存统计接口

`get_cache_stats()`（`enhanced_cache.py:713`）返回：

```
{
  "lru_hits": N, "redis_hits": N, "disk_hits": N,
  "misses": N, "sets": N,
  "total_hits": N, "total_requests": N, "hit_rate": float
}
```

`diff_cache_stats(before, after)` 用于计算单次运行的增量；`get_cache_runtime_info()` 返回 lru_maxsize / redis_available / disk_path / disk_entry_count / disk_file_size_bytes / stats 一站式诊断快照，CLI `--cache-stats` 走这个。

## 9. 缓存预热

`cache_preheater.py` 暴露 2 个任务（`get_preheat_tasks`），均通过 `BatchDataFetcher` 写入 `BatchDataCache`：

1. `daily_basic` → `daily_basic_batch:{trade_date}`
2. `daily_prices` → `daily_price_batch:{trade_date}`

CLI 入口 `python src/main.py --preheat --date 20260313`，并发=4。`force=True` 时绕过已有缓存（实际是 `if not force and cache.get(...) is not None: return None` 的 short-circuit 写法）。

## 10. 相关文件索引

- 缓存层：`src/data/enhanced_cache.py`, `src/data/cache.py`
- 路由：`src/data/router.py`, `src/data/router_helpers.py`, `src/data/base_provider.py`
- 验证：`src/data/validator_v2.py`, `src/data/validator_v2_helpers.py`, `src/data/validation_rules.py`, `src/data/validator.py`
- 质量：`src/data/quality_monitor.py`
- 健康：`src/data/health.py`, `src/data/health_checker.py`
- 批量：`src/screening/batch_data_fetcher.py`, `src/data/cache_preheater.py`
- 预热入口：`src/main.py::run_preheat`（line 722）
