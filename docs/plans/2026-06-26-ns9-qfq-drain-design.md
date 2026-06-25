# NS-9 qfq 价格复权 drain — 设计决策包 (design_decision_packet)

**状态**: 设计完成, 待实现 (autodev C17X, change_risk=3 → 需 fresh session 实施 + 测试级联处理)
**来源**: owner §三·6 backlog NS-9 (P0); R37 family sibling drain
**决策权**: engineering (owner 已决定 "做 qfq"; 本包定 HOW + 风险)
**起草**: 2026-06-26 (autodev WIP-blocked 期间产出 — rb006 满 3/3, 此包为规划工件, 不撞 WIP)

---

## 1. 问题 (problem)

R37 修了 `_fetch_tushare_ashare_prices_df` (`src/tools/tushare_api.py:363`) 用 qfq 前复权,
但 **3 个 sibling 仍用不复权 raw price**:

| Sibling | 位置 | 现状 | 用途 |
|---|---|---|---|
| `TushareProvider.get_prices` | `src/data/providers/tushare_provider.py:123` | `self._pro.daily` 无 adj_factor | **router 主 provider** (data/router.py:461 注册) |
| `TushareDataSource.get_prices` | `src/tools/ashare_data_sources.py:91` | `_cached_tushare_dataframe_call(pro, "daily", ...)` 无 adj_factor | recommendation_tracker 真实收益回填 (live 路径) |
| `BaoStockDataSource` | `src/tools/ashare_data_sources.py:167` | `adjustflag="3"` (不复权) | fallback 数据源 |

**危害**: 跨除权除息日 (送股/分红/配股) raw close 跳水 → 制造**假亏损** → 污染收益/ATR/止损/回撤计算。
这是 A 股回测有效性的主要 bug (R37 已论证)。3 个 sibling 在不同路径上延续同一 bug。

**关键**: 3 个 sibling 都是 **live 代码** (非 dead code):
- TushareProvider 经 router 被 provider 抽象层调用
- TushareDataSource 在 `recommendation_tracker.py:229` 调用 (R162/R163 已修, 真实收益路径)
- BaoStockDataSource 作为 fallback

---

## 2. 不变量 (invariants)

1. 收益/ATR/止损/回撤计算必须基于 qfq (前复权) 价格, 消除除权除息假跳空
2. qfq 只调整 OHLC 价格水平, **不改变收益结构** (止损/ATR 逻辑不受影响 — R37 已论证)
3. volume 不做复权 (volume 复权是独立问题, 回测不从 volume 算收益)
4. adj_factor 不可用时 **优雅降级** 回 raw daily (R37 既定语义: 不准确但仍可跑, 优于无数据)
5. `_apply_qfq_adjustment` (tushare_api.py:410) 是唯一 qfq 实现, siblings 复用它, 不另造

---

## 3. 选项 (≥2 distinct options)

### Option A: 复用 `_apply_qfq_adjustment` (镜像 R37, 逐 sibling)

每个 tushare sibling 加一步 adj_factor 拉取 + `_apply_qfq_adjustment`; BaoStock 改 adjustflag。

- **TushareProvider.get_prices** (async): `df = await self._run_sync(self._pro.daily, ...)` 之后,
  加 `adj_df = await self._run_sync(self._pro.adj_factor, ...)` + `_apply_qfq_adjustment(df, adj_df)`。
  需 `from src.tools.tushare_api import _apply_qfq_adjustment` (跨 tools/←data/providers/ 导入, 已有先例)。
- **TushareDataSource.get_prices**: `_cached_tushare_dataframe_call` 之后再调一次拉 adj_factor,
  复用同一 helper。本模块已 import tushare_api, 无新依赖。
- **BaoStockDataSource**: `adjustflag="3"` → `"2"` (BaoStock `query_history_k_data_plus` 原生支持 qfq, 一字符改)。

**优点**: 与 R37 完全一致; proven helper; 每 sibling 独立可回滚
**缺点**: TushareProvider 多一次 async `_run_sync` (adj_factor 拉取); 改动面 3 处

### Option B: 2 个 tushare sibling 直接调 R37 的 `_fetch_tushare_ashare_prices_df`

不再各自 `pro.daily`, 改为调 `_fetch_tushare_ashare_prices_df(pro, ts_code, start, end)` (R37 已封装 daily+adj_factor+qfq)。

**优点**: 单一真相源 (DRY); 修复点集中在 R37 函数内
**缺点**: `_fetch_tushare_ashare_prices_df` 签名/返回 (DataFrame) 与 sibling 现有 Price-list 转换链不完全契合;
TushareProvider 是 async 而 R37 函数是 sync; 可能需重构签名 → 改动 R37 函数有回归风险

### Option C: feature-flag (`USE_QFQ_PRICES` env, 默认 off, 灰度)

**优点**: 安全灰度, 可 A/B
**缺点**: raw-price 是 **bug 不是 feature**, flag 它语义奇怪; 增加配置复杂度; 永久 flag 变技术债

---

## 4. 推荐 (recommendation)

**Option A** (复用 `_apply_qfq_adjustment`, 逐 sibling)。理由:
- 与 R37 既有模式完全一致, helper 已被测试验证
- 改动局部化 (每 sibling 独立), 回滚粒度细
- 不触碰 R37 函数签名 (零回归风险给已修路径)
- BaoStock 一字符改 (`adjustflag="3"`→`"2"`), 风险最低, 可作为**第一个 slice** 验证模式

**实施顺序** (每 sibling 一个独立 commit, 便于二分回滚):
1. BaoStockDataSource `adjustflag` (最简, 验证 qfq 模式可观测)
2. TushareDataSource (recommendation_tracker 真实收益路径, 中等风险)
3. TushareProvider (router 主路径, 最高 blast_radius, 最后做)

---

## 5. 风险 (risk dimensions)

| 维度 | 分 | 理由 |
|---|---|---|
| blast_radius | **3** | TushareProvider 是 router 主 provider; 改 raw→qfq 影响所有经 provider 层的 price fetch; 跨除权日历史价位整体平移 |
| design_uncertainty | 1 | R37 模式已确立, helper 已验证 |
| contract_ambiguity | 0 | owner 已明确 "做 qfq" |
| verification_gap | 2 | 需处理测试级联 (现有断言 raw 价位的测试会偏移) |
| rollback_difficulty | 1 | 每 sibling 独立 commit, 可分别 revert |
| migration_risk | 1 | 无数据迁移 |
| **change_risk (max)** | **3** | → 触发本设计包 (gate: 任一维度 > 2) |

---

## 6. 验收测试 (acceptance tests)

每个 sibling 一个:
1. **已知除权日 fixture**: 构造 raw daily + adj_factor (含一个除权日, adj_factor 跳变), 调 sibling get_prices,
   断言 qfq close 在除权日**无假跳空** (前后日收益连续, 不制造假亏损)
2. **adj_factor 不可用降级**: adj_factor 返回 None/空 → sibling 回落 raw daily (不崩, R37 语义)
3. **现有测试**: `tests/test_provider_prices_nan_row.py` / `test_r20_11_provider_field_fix.py` /
   `test_tushare_retry.py` 等若断言具体 raw 价位, 需更新为 qfq 调整后值 (或改用相对收益断言, 更鲁棒)
4. **characterization snapshot** (可选, risk-retirement slice): 改动前快照当前 raw-price 行为,
   改动后验证仅除权日价位平移、收益结构不变

**FULL 回归**: 改动后跑 FULL suite (当前基线 ~9918 passed), 预期:
- 价格-价位断言类测试可能偏移 (需更新)
- 收益/排序类测试应不变 (qfq 不改收益结构, 除权日处反而更准)

---

## 7. 回滚 (rollback)

- 每 sibling 独立 commit → 可 `git revert <sha>` 单独回滚
- 顺序回滚: 先回 TushareProvider (最高风险), 再 TushareDataSource, 再 BaoStock
- `_apply_qfq_adjustment` helper 本身不动 (R37 路径不回滚)

---

## 8. 下一步触发 (next trigger)

- **需 fresh session** 带完整 context budget (实施 + 测试级联处理可能耗时长)
- **前置**: rb006 WIP 释放 (owner observe+release, 或 campaign 2 wip_override) — 否则实施 commit 后又添 WIP 拥堵
- **或**: owner 直接指定 "做 NS-9 BaoStock slice" (最简, adjustflag 一字符, 可独立交付不入 WIP 拥堵核心? — 需 confirm 是否仍属 wf-top-picks-must-win)
- **stale 依赖**: owner 重跑 `_backtest_light_stage_universe.py` 刷新 REGIME_HISTORICAL_WINRATES (与 NS-9 正交但同属数据准确性)

---

## 附录: R37 helper 签名 (复用点)

```python
# src/tools/tushare_api.py:410
def _apply_qfq_adjustment(raw_df: pd.DataFrame, adj_df: pd.DataFrame) -> pd.DataFrame:
    """qfq = price_raw * adj_factor / adj_factor_latest; 仅 OHLC; volume 不动;
    按 trade_date 匹配; adj_factor 不可用返回 raw_df (降级)。"""
```

TushareProvider (async) 用法:
```python
df = await self._run_sync(self._pro.daily, ts_code=ts_code, start_date=start_fmt, end_date=end_fmt)
adj_df = await self._run_sync(self._pro.adj_factor, ts_code=ts_code, start_date=start_fmt, end_date=end_fmt)
if adj_df is not None and not adj_df.empty:
    df = _apply_qfq_adjustment(df, adj_df)
```
