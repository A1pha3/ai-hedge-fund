# P0-1 全市场筛选速度优化 — 设计

## 1. 目标

将 `--auto` 模式对 ~5000 只 A 股的逐 ticker 串行评分从「分钟级」压缩到「秒级」。

## 2. 现状 (As-Is)

筛选流水线主要数据获取热路径：

| 阶段 | 数据源 | 当前调用方式 | 痛点 |
|------|--------|--------------|------|
| Layer A: 20 日均成交额 | `pro.daily(trade_date=...)` | **已批量**（按日聚合 `_get_avg_amount_20d_map`） | OK |
| Layer A: daily_basic | `pro.daily_basic(trade_date=...)` | 一次全市场拉取 | OK |
| Layer B: 趋势 / 均值回归 评分 | `get_prices` (akshare/tushare) | **逐 ticker 串行/线程** | 5000 次请求 |
| Layer B: 基本面 评分 | `get_financial_metrics` (tushare fina_indicator) | **逐 ticker 线程池** | ~300 次 |
| Layer B: 事件情绪 评分 | `get_money_flow` / 龙虎榜 | **逐 ticker 线程池** | ~50 次 |

瓶颈集中在 Layer B 的逐 ticker 串行调用。

## 3. 设计 (To-Be)

### 3.1 新增 `src/screening/batch_data_fetcher.py`

**核心类**：

```python
class BatchDataCache:
    """短期内存缓存 (默认 TTL 60s)。"""
    def __init__(self, ttl_seconds: int = 60): ...
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...
    def clear(self) -> None: ...

class BatchDataFetcher:
    """批量数据获取器 — 包装 tushare/akshare 批量接口 + 并发 fallback。"""
    def __init__(
        self,
        *,
        use_batch: bool | None = None,        # None → 读 USE_BATCH_FETCHER env
        max_concurrency: int = 8,
        cache_ttl_seconds: int = 60,
    ): ...
    # ---- 全市场批量接口 ----
    def fetch_daily_prices_batch(self, trade_date: str) -> pd.DataFrame | None: ...
    def fetch_daily_basic_batch(self, trade_date: str) -> pd.DataFrame | None: ...
    def fetch_ashare_spot_em(self) -> pd.DataFrame | None: ...
    # ---- 单 ticker 接口 (fallback) ----
    async def fetch_prices_async(self, ticker: str, start_date: str, end_date: str) -> list[dict]: ...
    async def fetch_financial_metrics_async(self, ticker: str, end_date: str) -> list[dict]: ...
    # ---- 工具 ----
    def stats(self) -> dict[str, int]: ...
```

**关键策略**：
- 批量接口优先：tushare `pro.daily(trade_date=...)` 一次取全市场 → 内存按 `ts_code` 索引
- 批量失败时降级到 `asyncio.Semaphore(N)` 控制的并发单 ticker 调用
- 全局 `BatchDataCache` (TTL 60s) 避免同一进程内重复请求
- `USE_BATCH_FETCHER=False` 环境变量禁用批量（kill switch）

### 3.2 集成点

**`src/screening/strategy_scorer.py`** 中：
- `score_batch` 在开头调用一次 `fetcher.fetch_daily_prices_batch(trade_date)`，结果注入 `_populate_trend_and_mean_reversion_signals` 避免逐 ticker `get_prices`
- `score_fundamental_strategy` 改用 `fetcher.fetch_financial_metrics_async` (semaphore 控制并发)
- `score_event_sentiment_strategy` 同样改用 fetcher

**`src/screening/candidate_pool.py`** 中：
- `load_amount_map_and_low_liquidity_codes` 优先使用 `fetcher` 的批量 `daily` 聚合
- `get_daily_basic_batch` 调用走 fetcher 缓存

**`src/main.py`** 中：
- `run_auto_screening` 入口检查 `USE_BATCH_FETCHER` 环境变量并创建 fetcher
- fetcher 注入到下游 `score_batch`、`build_candidate_pool`

### 3.3 向后兼容

- 单 ticker 调用 (`get_prices`, `get_financial_metrics`) 保留原样，fetcher 仅作为「优先路径」
- `USE_BATCH_FETCHER=false` 时完全走原路径
- 批量失败 → 静默降级到单 ticker（捕获 Exception）

## 4. 数据格式契约

`fetch_daily_prices_batch` 返回 `pd.DataFrame`，列: `ts_code, trade_date, open, high, low, close, pre_close, vol, amount, pct_chg` (与 tushare `daily` 一致)。
`fetch_daily_basic_batch` 返回 `pd.DataFrame`，列: `ts_code, trade_date, close, turnover_rate, pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm, total_share, float_share, free_share, total_mv, circ_mv`。

## 5. 测试

- `tests/test_batch_data_fetcher.py`:
  - `BatchDataCache` 单元测试（TTL 过期、key 命中）
  - `BatchDataFetcher` mock 测试
    - 批量接口数据格式校验
    - 批量失败降级到单 ticker
    - 并发受 semaphore 限制
    - 缓存命中减少底层调用
    - `USE_BATCH_FETCHER=false` 走单 ticker
- `tests/screening/test_screening_performance.py`:
  - mock 环境对比 50 标的 × 2 模式耗时
  - 批量模式调用次数 << 串行模式

## 6. 验收

- `uv run pytest tests/test_batch_data_fetcher.py -v` 全过
- `uv run pytest tests/screening/ -v` 161 个无回归
- `uv run pytest tests/ -x -q --tb=short` 全套无回归
- 行长度 ≤ 420，类型注解完整

## 7. 文档更新

`docs/cn/product/feature-proposals.md`：
- P0-1 状态改为 ✅
- 末尾追加 P0-1 实现细节章节
- Phase 1 路线图 P0-1 加 ✅
