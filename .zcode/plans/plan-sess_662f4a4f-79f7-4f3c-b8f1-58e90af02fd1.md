# 多源数据获取层设计方案（tushare → akshare → ftshare）

## 设计哲学（第一性原理）

**问题本质**：当前系统有 3 个独立的数据源 wrapper（tushare_api / akshare_api / 尚无 ftshare），但每个源各自有缺陷——tushare 宏观接口无权限、akshare 资金流偶发不稳、price_cache 只有 6 个月深度。没有一个源是完整的。

**核心洞察**：`fund_flow.py` 已经解决了这个问题的**一个实例**——用 2 源 dispatcher 兜底。我们要做的不是发明新架构，而是**把这个已验证的模式泛化为 N 源**，然后给 3 类数据各建一条链。

**三条设计原则**：
1. **一数据类型一 dispatcher**——每种数据（price / fund_flow / macro）有自己的源优先级和归一化逻辑，不搞万能 generic
2. **dispatcher 只负责选源 + 归一化**——不负责缓存（cache_refresh 管）、不负责重试（各源 fetcher 自己管）
3. **新增源 = 新增一个 `_try_*` 函数**——不改 dispatcher 逻辑，不改消费者代码

---

## 架构总览

```
                    ┌─────────────────────────────────┐
                    │   cache_refresh.py (消费者)      │
                    │   refresh_price_cache()          │
                    │   refresh_fund_flow_cache()      │
                    └──────────┬──────────────────────-┘
                               │ 调用统一 dispatcher
                    ┌──────────▼──────────────────────-┐
                    │   src/tools/price.py (新)         │  ← 泛化的 price dispatcher
                    │   fetch_daily_ohlcv()             │
                    │   tushare → akshare → ftshare     │
                    └──┬──────────┬──────────┬────────-┘
                       │          │          │
              ┌────────▼──┐ ┌─────▼─────┐ ┌──▼──────────────┐
              │tushare_api│ │akshare_api│ │ftshare_api(新)   │
              │(已有)      │ │(已有)      │ │ftshare_fetcher  │
              └───────────┘ └───────────┘ │(新)              │
                                           └─────────────────┘
```

**关键**：消费者（cache_refresh）只调 dispatcher，dispatcher 按优先级试每个源的 `_try_*` 函数，第一个返回非空 DataFrame 的源胜出。

---

## 文件变更清单（7 个新文件 + 3 个改动）

### 新文件

| 文件 | 职责 | 行数估计 |
|---|---|---|
| `src/tools/ftshare_client.py` | ftshare SDK 单例管理（懒加载 `ft.market_api()` + 带重试的 session 注入） | ~80 |
| `src/tools/ftshare_api.py` | ftshare 源 fetcher（日线/资金流/宏观 3 类），返回与 tushare/akshare 同 schema 的 DataFrame | ~250 |
| `src/tools/price.py` | **日线行情 N 源 dispatcher**（泛化 fund_flow.py 模式） | ~120 |
| `src/tools/macro_multi.py` | **宏观指标 N 源 dispatcher**（CPI/PPI/PMI/M2/社融/LPR） | ~150 |
| `tests/tools/test_ftshare_api.py` | ftshare fetcher 单元测试 | ~150 |
| `tests/tools/test_price_dispatcher.py` | price dispatcher fallback 测试 | ~120 |
| `tests/tools/test_macro_multi.py` | 宏观 dispatcher fallback 测试 | ~100 |

### 改动文件

| 文件 | 改动 |
|---|---|
| `src/tools/fund_flow.py` | 在 `sources` 列表追加 `("ftshare", _try_ftshare)` 作为第 3 源；新增 `_try_ftshare` 函数 |
| `src/screening/offensive/cache_refresh.py` | `refresh_price_cache_from_daily_batch` 的 `backfill_price_history_fn` 默认值从 `_fetch_price_history_with_tushare` 改为 `price.fetch_daily_ohlcv`（多源版）；`_DEFAULT_PRICE_HISTORY_LOOKBACK_DAYS` 从 180 → 400（解锁 trend 200 行门槛） |
| `pyproject.toml` | 添加 `ftshare` 依赖 |

---

## 详细设计

### 1. `src/tools/ftshare_client.py` — SDK 单例 + 重试

```python
"""ftshare SDK 单例管理 — 懒加载 + 带重试的 requests.Session 注入。

ftshare SDK 本身不内置重试/限频处理 (base.py 只有 timeout=10s)。
本模块构造一个带 urllib3 Retry 的 Session 注入给 ft.market_api(session=)，
使其具备与 tushare_api 同级的瞬时错误重试能力。
"""
```

**核心函数**：
- `_get_market()` — 线程安全懒加载单例（仿 tushare_api._get_pro 模式），返回 `ft.market_api(session=_retry_session)` 或 None（SDK 未安装时）
- `_retry_session` — 预配置的 `requests.Session`，挂载 `HTTPAdapter(max_retries=Retry(total=3, backoff_factor=0.5, status_forcelist=[429,500,502,503,504]))`

**可用性 flag**：`_ftshare_available`（仿 akshare_api 的 `_akshare_available`），import 失败时设 False，`_get_market()` 返回 None。

### 2. `src/tools/ftshare_api.py` — ftshare 源 fetcher

3 个公开函数，每个返回与现有 tushare/akshare fetcher **完全相同的 schema**：

#### `fetch_daily_ohlcv_ftshare(ticker, start_date, end_date) -> pd.DataFrame`
- 调用 `market.stock_ohlcs(symbol=ticker, start_date=start_date, end_date=end_date, adjust="qfq")`
- 归一化为 `date,close,open,high,low,pct_change,volume`（price_cache schema）
- **date 格式 `YYYY-MM-DD`**（与 price_cache 一致，fund_flow_cache 是 `YYYYMMDD`）
- pct_change 为百分比（9.52 = +9.52%）
- 异常/空时返回 `pd.DataFrame(columns=["date","close","open","high","low","pct_change","volume"])`

#### `fetch_individual_fund_flow_ftshare(ticker, start_date, end_date) -> pd.DataFrame`
- 调用 `market.stock_capital_flows(symbol=ticker, start_date=..., end_date=...)`
- 归一化为 `date,close,pct_change,main_net_inflow,main_net_pct,...`（fund_flow_cache schema）
- **date 格式 `YYYYMMDD`**（与 fund_flow_cache 一致）
- 金额单位：元（ftshare 东财源可能已是元，需验证后确认是否 ×10000）
- **填补 tushare 的 main_net_pct=0.0 问题**——东财源提供占比

#### `fetch_macro_snapshot_ftshare() -> dict`
- 批量调用 6 个宏观接口（CPI/PPI/PMI/M2/社融/LPR）
- 返回与现有 `macro_data.fetch_macro_snapshot` 兼容的 dict 结构
- 这是 tushare 宏观无权限问题的**唯一解决方案**

### 3. `src/tools/price.py` — 日线 N 源 dispatcher

**完全复刻 `fund_flow.py` 的 dispatcher 模式**，零新概念：

```python
def fetch_daily_ohlcv(ticker, start_date, end_date, primary="tushare"):
    """日线行情 N 源 fallback: tushare → akshare → ftshare。

    返回标准化 DataFrame (date[YYYY-MM-DD]/close/open/high/low/pct_change/volume)。
    所有源均失败时返回空 DataFrame。
    """
    sources = [
        ("tushare", _try_tushare_price),
        ("akshare", _try_akshare_price),
        ("ftshare", _try_ftshare_price),
    ]
    # ... 与 fund_flow.py 完全相同的 outcomes dict + dedup 计数逻辑
```

每个 `_try_*` 函数做懒 import + schema 归一化 + 返回标准 DataFrame 或空 DataFrame。

### 4. `src/tools/fund_flow.py` 改动 — 追加第 3 源

```python
# 现有:
sources = [("tushare", _try_tushare), ("akshare", _try_akshare)]
# 改为:
sources = [("tushare", _try_tushare), ("akshare", _try_akshare), ("ftshare", _try_ftshare)]

def _try_ftshare(ticker, start_date, end_date):
    from src.tools.ftshare_api import fetch_individual_fund_flow_ftshare
    return fetch_individual_fund_flow_ftshare(ticker, start_date, end_date)
```

### 5. `src/tools/macro_multi.py` — 宏观 N 源 dispatcher

宏观数据特殊：不是 per-ticker，而是全市场快照。所以独立 dispatcher：

```python
def fetch_macro_snapshot(primary="tushare"):
    """宏观快照 N 源: tushare → ftshare。

    tushare 多数宏观接口无权限 (返回 "请指定正确的接口名")，
    ftshare 作为唯一可靠宏观源补位。

    返回 dict: {"cpi": ..., "ppi": ..., "pmi": ..., "m2": ..., "sf": ..., "lpr": ...}
    """
```

### 6. cache_refresh.py 改动 — 接入多源

```python
# 现有 (line 389):
if backfill_price_history_fn is None:
    backfill_price_history_fn = _fetch_price_history_with_tushare
# 改为:
if backfill_price_history_fn is None:
    from src.tools.price import fetch_daily_ohlcv
    backfill_price_history_fn = fetch_daily_ohlcv

# 现有 (line 28):
_DEFAULT_PRICE_HISTORY_LOOKBACK_DAYS = 180
# 改为:
_DEFAULT_PRICE_HISTORY_LOOKBACK_DAYS = 400  # 解锁 trend 策略 200 行门槛
```

---

## 测试策略

遵循 `tests/tools/test_fund_flow.py` 的既定模式：

1. **patch 内部 `_try_*` 函数**（不 patch 网络），注入假 DataFrame 验证 fallback 链
2. **验证归一化 schema**：每个源返回的 DataFrame 列名/单位/日期格式一致
3. **验证 dedup 计数**：首次 WARNING，后续静默，每 50 次 INFO
4. **ftshare SDK 不可用时优雅降级**：`_ftshare_available=False` → `_try_ftshare` 返回空 DataFrame

---

## 实施步骤（建议顺序）

1. **`ftshare_client.py`** + **`ftshare_api.py`**（ftshare 源能力）
2. **`price.py`**（price dispatcher，最高优先级 ⭐⭐⭐）
3. **cache_refresh.py 改动**（接入多源 price + 加深 lookback）
4. **`fund_flow.py` 改动**（追加 ftshare 第 3 源 ⭐⭐）
5. **`macro_multi.py`**（宏观 dispatcher ⭐⭐）
6. **全套测试**
7. **pyproject.toml 加 ftshare 依赖 + .env.example 更新**

---

## 不做的事（明确排除）

- **不碰 async `src/data/` 栈**——daily-action 路径不用它，投入产出比低
- **不改 `--auto` 的 `refresh_scoring_features` stub**——那是另一个独立的管道断裂问题（见前序分析的 B 类根因），本次只解决数据源 A 类问题
- **不引入新抽象层/BaseClass/Protocol**——fund_flow.py 的 tuple-list + outcomes-dict 模式已经足够，不需要过度工程化
- **首批不加龙虎榜/分钟线/行业PE**——用户选了 3 类优先数据（price/fund_flow/macro），其余后续迭代