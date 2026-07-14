---
难度: ⭐⭐⭐
类型: 进阶分析
预计时间: 12 分钟
前置知识:
  - [架构总览](../03-architecture/overview.md) ⭐⭐⭐
  - [设计原则](principles.md) ⭐⭐⭐⭐
---

# 候选池设计

候选池是 `--auto` 的 Layer A：从全 A 股 ~5000 只里筛出可进入 Layer B 评分的 ~300 只。代码在 `src/screening/candidate_pool.py`，过滤规则常量化在文件顶部，每条都对应一个具体的失败模式。

## 为什么需要 Layer A

`--auto` 的 Layer B 评分（trend / mean_reversion / fundamental / event_sentiment）需要拉价格序列、财务指标、事件新闻，每只票都要做 IO + CPU。如果不预筛，全市场跑一遍要数十分钟。Layer A 的目标是：用便宜的数据（基本信息 + 成交额）排除明显不可交易的票，把评分空间压到 300 只以内。

`--daily-action` 不依赖这个候选池 — 它直扫 `price_cache` 全市场。两个系统的设计原则不同：`--auto` 要"好股票"，`--daily-action` 要"极端股票"（详见 [设计原则](principles.md) §1）。

## 过滤规则与代码实现

`candidate_pool.py` 顶部 docstring 列出 9 条过滤规则：

```python
"""
1. 获取全 A 股基本信息（~5000 只）
2. 排除 ST / *ST 标的（名称包含 ST）
3. 排除北交所标的（市场 = 'BJ' / '北交所'、ts_code = '.BJ' 或代码 4xxxxx / 8xxxxx / 92xxxx）
4. 排除上市不满 60 个交易日的新股/次新股
5. 排除当日停牌标的
6. 排除当日涨停标的（买入排队失败）
7. 排除停牌超过 5 日后复牌未满 3 个正常交易日的标的（简化实现）
8. 排除近 20 日平均成交额 < 5000 万元的低流动性标的
9. 排除被冲突仲裁规则一标记的"回避冷却期"标的（15 个交易日）
"""
```

每条规则对应一个具体场景：

- **排除 ST**：ST 股超跌常见，OversoldBounce 容易误命中（如 002217 ST 合力泰）。`--daily-action` 的 `_load_st_tickers` 也独立做这一步，因为 full_market 不经 Layer A。
- **排除北交所**：北交所 30% 涨跌停板，流动性差，`_LIMIT_UP_PCT_BJ = 29.0` 的口径与主板不同（详见 [BTST 深度](btst-breakout-design.md)）。
- **新股过滤**：`MIN_LISTING_DAYS = 60`，新股波动大、缺乏历史数据，BTST 的 5 日累计涨幅判定不可靠。
- **流动性下限**：`MIN_AVG_AMOUNT_20D = 5000`（万元），20 日平均成交额低于此值的票，BTST 涨停日的"主力净流入 > 20 日均值"判定会被一两只大单污染。
- **冷却期**：`COOLDOWN_TRADING_DAYS = 15`，被冲突仲裁标记的票 15 个交易日内不再入池。

## 流动性筛选的两段式实现

`_get_avg_amount_20d_map` 是性能关键路径。原实现逐票调用 `daily` API，~3000 只票要数十分钟。优化后的两段式：

1. **第一阶段（粗筛）**：`MIN_ESTIMATED_AMOUNT_1D = 3000` 万元，用 `daily_basic` 的换手率 × 流通市值估算当日成交额。这是 O(1) 查表，秒级返回。
2. **第二阶段（精筛）**：粗筛通过的票才调 `_get_avg_amount_20d` 取真实 20 日均额。

`_resolve_batch_fetcher_for_avg_amount` 还会优先走 `BatchDataFetcher`（带 60s 内存缓存），失败才回退到 `_cached_tushare_dataframe_call`。

```python
def _resolve_batch_fetcher_for_avg_amount() -> "BatchDataFetcher | None":
    """获取 (lazy) 全局 BatchDataFetcher 单例；导入失败/未安装时返回 None。"""
    try:
        from src.screening.batch_data_fetcher import get_global_batch_data_fetcher
    except Exception as exc:
        # NS-17/BH-017 同族 (c274): ImportError 静默返回 None 会掩盖
        # batch_data_fetcher 模块的语法错误/循环依赖/缺失依赖
        logger.warning("batch_data_fetcher import failed ...", exc_info=True)
        return None
```

注意 `logger.warning` 而非静默 `return None` — 决策链数据源降级必须可观测，否则瞬时 API 失败会让候选池静默缩水。

## shadow pool：被截断的票去哪了

`MAX_CANDIDATE_POOL_SIZE = 300` 是硬上限。超过的票进入 shadow pool，按 `_candidate_liquidity_sort_key` 排序保留。`build_candidate_pool_with_shadow` 返回三元组：

```python
def build_candidate_pool_with_shadow(
    trade_date: str,
    use_cache: bool = True,
    cooldown_tickers: set[str] | None = None,
) -> tuple[list[CandidateStock], list[CandidateStock], dict[str, Any]]:
    # returns: (selected_candidates, shadow_candidates, shadow_summary)
```

shadow pool 的作用是「focus ticker 追踪」：运维指定的 ticker（`SHADOW_FOCUS_TICKERS` env）即使被截断，也会在 shadow pool 里持续追踪可见性，避免"今天为什么没看到 300683"这类问题。`_finalize_focus_filter_diagnostics` 给每个 focus ticker 标注 `first_removed_stage`（在哪一步过滤被剔除）和 `final_visibility`（最终落在哪个 pool）。

## 行业配额： Layer A 不做，Layer B 才做

`candidate_pool.py` 不做行业配额 — Layer A 只做"可交易性"过滤，行业分散由 Layer B 的 `_apply_cross_sectional_attention_metrics` 和 investability 排序处理。`--daily-action` 才在 `generate_daily_action` 里做行业集中度控制：

```python
# daily_action.py:1036-1039
# 行业集中度控制: 同一信号日同一行业最多 2 个仓位.
# 回测验证: 集中日(≥50%同行业)平均收益 +6.3% vs 分散日 +9.7% (差 3.4pp).
# 最差日全部是高度集中的 (通信 4/6, 有色 4/6). 限制集中度降低尾部风险.
industry_count_today: dict[str, int] = {}
_MAX_PER_INDUstry_DAILY = 2
```

注意 `_MAX_PER_INDUstry_DAILY = 2` 的回测依据：集中日（≥50% 同行业）平均收益 `+6.3%` vs 分散日 `+9.7%`，差 3.4pp；最差日全部是高度集中的（通信 4/6、有色 4/6）。

## 已知陷阱

1. **`tushare` `daily` API 速率限制**：`TUSHARE_DAILY_CALLS_PER_MINUTE = 200`、`TUSHARE_DAILY_BATCH_SIZE = 50`。`_enforce_tushare_daily_rate_limit` 按实际已耗时补足 sleep，避免触发限流。
2. **财报窗口期**：`DISCLOSURE_MONTHS = {4, 8, 10}`，这三个月财报披露密集，基本面数据可能 stale，`fundamental` 评分会自动降权。
3. **`_estimate_trading_days` 是估算**：用自然日 × 0.7 近似交易日（A 股年 250 交易日 / 365 自然日 ≈ 0.685），不是精确交易日历。新股判定有 ±5 天误差，但 `MIN_LISTING_DAYS = 60` 足够保守，不会让真新股误入。

## 与 `--daily-action` 的边界

`--daily-action` 不读 `candidate_pool` 的 snapshot，直扫 `price_cache` 文件名集合。这是设计选择 — 凸性 setup 要极端股票，候选池的流动性过滤会漏掉小盘涨停股。但 ST 过滤仍要做，所以 `_load_st_tickers` 独立实现一次。两个系统的 ST 集合来自同一数据源（tushare `stock_basic`），口径一致。
