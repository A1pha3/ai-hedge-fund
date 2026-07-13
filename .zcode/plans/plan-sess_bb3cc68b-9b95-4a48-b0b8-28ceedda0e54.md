# 对抗性审查 + 优化方案

## 审查方法
从第一性原理出发，追踪了 `--auto`（因子评分→score_b→investability→Top10）和 `--daily-action`（凸性 setup→Kelly→paper trading）两条完整代码路径。阅读了所有关键模块（daily_action.py、paper_tracker.py、btst_breakout.py、oversold_bounce.py、event_sentiment_helpers.py、kelly.py、execution_adjuster.py、atr_utils.py），运行了 309 个测试确认基线通过。

---

## 任务 1：发现的 Bug（按影响排序）

### Bug 1【高危】`_check_stop_hit` except 兜底扫描全历史（前瞻偏差）
**位置**: `src/screening/offensive/paper_tracker.py:639-644`

```python
try:
    mask = (df["date"].dt.date > buy_dt) & (df["date"].dt.date <= end_dt)
    window = df.loc[mask, "low"].dropna()
except Exception:
    window = df["low"].dropna()  # ← 扫描整个历史！
```

**第一性原理问题**：主路径正确排除了 T+0 信号日、限制了 T+N 窗口。但 `except` 兜底退化为 `df["low"].dropna()`——扫描**整个价格历史的所有 low**，包括：
- T+0 信号日（用户还没买入，涨停日盘中波动会误报止损）
- T+N **之后**的未来日期（look-ahead bias：用了退出日之后的低点）

触发条件仅需 date 列解析失败（datetime 格式异常、字符串日期），在实际 CSV 数据中完全可能发生。

**修复**（最简洁安全）：`except` 兜底返回 `False`（保守不触发）而非扫描全历史。与函数开头 `prices_df is None → return False` 同语义。主路径失败时不应猜测。

### Bug 2【高危】行业数据加载失败静默杀掉全部 BTST 信号
**位置**: `src/screening/offensive/daily_action.py:415-427` + `btst_breakout.py:299-302`

```python
# daily_action.py:425
except Exception as exc:
    logger.warning("...BTST 行业过滤将按 0%% 处理: %s", exc)
    return {}  # ← 空字典

# daily_action.py:734
industry_pct = float(industry_day_pct_by_ticker.get(ticker, 0.0) or 0.0)
# 加载失败时 industry_pct = 0.0

# btst_breakout.py:301
if industry_pct != industry_pct or industry_pct < _INDUSTRY_PCT_MIN:
    return self._miss(...)  # 0.0 < 2.0 → 全部 miss
```

**第一性原理问题**：行业数据依赖 `scripts/setup_research.load_industry_day_pct()`（需要 `_industry_codes.json` + `industry_index_cache/*.csv`）。如果缓存缺失/损坏/import 失败，`_load_industry_day_pct_by_ticker` 返回 `{}` → 每个 ticker 的 `industry_pct = 0.0` → **BTST 条件3（行业涨幅≥2%）永远不满足 → 当日 0 个 BTST 信号**。用户看到的是"今天没机会"，实际是数据管道断裂。

**修复**：在 `generate_daily_action` 中检测 `industry_day_pct_by_ticker` 为空但 BTST 已启用时，将行业条件降级为 `degraded=True`（标记残缺）而非静默全杀。具体做法：BTST 的 industry_pct 改为传入一个哨兵 `None`，setup 检测到 `None` 时跳过行业过滤但标 `degraded`（与资金流浅数据降级同模式）。这样用户至少能看到 BTST 候选（标注 `⚠残缺:行业数据缺失`），而非虚假的"无信号"。

### Bug 3【中危】Bug 4 测试断言条件化（silent no-op）
**位置**: `tests/screening/test_event_sentiment_fixes.py:210, 228`

```python
factor = _score_insider_conviction([buy, sell])
if factor.direction == 0:  # ← 如果 direction≠0，断言永远不执行
    assert factor.completeness == 0.0
```

**问题**：测试的目的是验证"direction=0 时 completeness=0"。但如果 `_resolve_insider_conviction_direction_and_confidence` 因输入数据导致 direction≠0（如买卖比偏移到 >0.6），断言被跳过，测试虚假通过。**这正是 Bug 4 原本要防止的失败模式**。

**修复**：构造确保 direction=0 的输入（score 精确落在 [0.4, 0.6] 死区），或直接断言 `factor.direction == 0`（前置断言）再断言 completeness。删除条件包裹。

### Bug 4【低危】docstring 与常量不一致
**位置**: `src/screening/offensive/setups/btst_breakout.py:7` (docstring) vs `:44` (常量)

docstring 说"涨停前 5 日累计涨幅 ≤ 10%"，但 `_PRE_RUNUP_MAX_PCT = 8.0`。常量是 2026-07 回测后从 10 收紧到 8 的（代码注释有数据依据），docstring 没同步。

**修复**：更新 docstring 为 ≤ 8%。

### Bug 5【低危】`kelly.py` 是 daily-action 路径的死代码
**位置**: `src/screening/offensive/daily_action.py:27` import + `:748` 注释

`compute_kelly_size` 被 import 但从未调用（注释承认"BTST Kelly f*=5.35 永远触顶 → 直接用 setup_max_pct"）。输出仍称"half-Kelly"，实际是 `setup_max × regime × drawdown × strength`。误导性命名。

**修复**：删除死 import；render 的 "half-Kelly" 措辞改为"仓位"（诚实）。不删 kelly.py 本身（test_kelly.py 仍有 7 个测试覆盖公式本身）。

---

## 修复实现步骤

1. **Bug 1**: `paper_tracker.py:643-644` — except 兜底改为 `return False`
2. **Bug 2**: `btst_breakout.py` — 行业条件降级（None→skip+degraded）；`daily_action.py:734` — 传 None 而非 0.0
3. **Bug 3**: `test_event_sentiment_fixes.py:210,228` — 去掉条件包裹，加 direction 前置断言
4. **Bug 4**: `btst_breakout.py:7` — docstring 改 8%
5. **Bug 5**: `daily_action.py:27` — 删 import；render 措辞修正

## 回归测试

每个 bug 修复配套新增测试：
- `test_check_stop_hit_fallback_returns_false_not_whole_history` — 构造 date 列异常 → 断言返回 False（非扫描全历史）
- `test_btst_industry_data_missing_degrades_not_kills` — industry 加载返回 {} → BTST 仍 hit 但 degraded=True
- `test_insider_dead_zone_unconditional_assertion` — direction=0 的确定性输入 + 无条件断言

运行 `tests/offensive/` + `tests/screening/test_event_sentiment_fixes.py` + `tests/screening/test_strategy_scorer_utils.py` + `tests/test_main_auto_cache_refresh.py` 全套（当前 309 passed，修复后应 ≥312）。

---

## 任务 2：优化机会（提高胜率和收益）

### 优化 A：BTST 增加「次日竞价表现」确认信号（高价值）
**现状**：BTST 命中基于 T+0 涨停日的板块/资金/位置因子。但 T+1 开盘竞价（9:25）是市场对涨停有效性的实时验证——高开 = 市场确认，低开/平开 = 动能衰竭。

**方案**：在 `stk_auction_o` 已有的开盘竞价数据中，T+1 实际买入时检查竞价涨幅。但这改变信号时机（T+0 信号 → T+1 09:25 确认），需要用户改变操作流程。**作为建议而非实现**，因为涉及工作流变更。

### 优化 B：OversoldBounce 增加「跌幅速度」过滤（中价值）
**现状**：OB 条件1 是 30 日跌幅 > 20%，但 30 天阴跌 vs 3 天暴跌是不同结构。缓跌（每日 -0.7%）的反弹弱于急跌（3 天 -20% 后的 V 型反转）。

**方案**：在 detect 中增加 `recent_drop_pct = (close[-3]/close[-6]-1)*100`，要求急跌分量占比 > 40%。这可以用现有 price_cache 数据计算，不需要新数据源。**可作为 OB 恢复的条件之一**（补全历史重跑后）。

### 优化 C：trigger_strength ranker 加入「涨停封单强度」因子（中价值）
**现状**：BTST 的 5 因子 ranker（weekday+board+position+squeeze+volume）不含封单质量。首板一封到底（尾盘不打开）vs 盘中多次打开的涨停，后续表现差异显著。

**方案**：如果有分笔数据可用，加入「涨停后打开次数」因子。但 price_cache 只有日 OHLC，无法精确判定。**当前不可行，标注为未来数据增强方向**。

### 优化 D：组合层面加入「行业轮动」regime 检测（中长期）
**现状**：regime 只分 crisis/risk_off/normal 三档（基于大盘），不考虑行业轮动。BTST 的 `_MAX_PER_INDUSTRY_DAILY = 2` 是静态限制。

**方案**：从 `industry_index_cache`（2020-2026 完整）计算各行业的 5/20 日动量排名，对处于行业动量 TOP 5 的 BTST 候选放宽行业集中限制（允许 3 仓），对 BOTTOM 5 收紧（1 仓）。用完整历史数据可回测验证。

---

## 不会做的事（避免过度工程）
- ❌ 不启用真实止损执行（AGENTS.md 明确：当前牛市样本止损降低 E[r]）
- ❌ 不恢复 OversoldBounce（统计不显著，需补全历史重跑后再定）
- ❌ 不改 Kelly 公式（kelly.py 死代码，删除 import 即可，公式本身正确）
- ❌ 不动 DiskCache 线程安全修复（commit a5aca89f 刚修完，有 13 个测试覆盖）

## 承诺
- 所有修改保持最小 diff，匹配周围代码风格
- 每个 bug 修复有对应测试
- 全套回归测试通过后才报告完成