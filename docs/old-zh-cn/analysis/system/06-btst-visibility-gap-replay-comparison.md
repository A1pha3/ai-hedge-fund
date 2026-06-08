# BTST `visibility-gap` 治理前后 replay 对比结论

> **生成时间：** 2026-04-08  
> **对比范围：** `2026-03-23` 旧版 `visibility-gap probe` vs `2026-03-27` 新版 governed replay  
> **目标读者：** 持续推进 BTST 胜率与收益优化的策略研发、回放验证与治理人员

## 学习目标

阅读完本文后，你应该能回答：

1. `visibility-gap` 在旧 probe 中为什么会被视为 weak-overnight leak path。
2. 新版 governed replay 为什么说明这条路径已经从执行面收口。
3. `300720` 当前为什么仍值得保留在 shadow observation，而不该再被直接抬进 `near_miss`。

## 为什么要做这份对比

这次对比不是为了证明 `300720` 完全消失，而是为了回答一个更关键的问题：**`visibility-gap` 这条通道是否还会把已知隔夜质量偏弱的样本抬进 BTST 执行面。**

如果答案仍然是“会”，那说明此前对 `merge_approved`、`upstream shadow` 的治理并没有真正封住旁路；如果答案变成“不会，但仍能带回 shadow observation”，那就说明当前策略已经把它从执行 leak 收口成可诊断、可观察的上游信号。

## 对比对象

| 维度 | 旧 probe | 新 governed replay |
|------|------|------|
| 目录 | `data/reports/paper_trading_20260323_20260323_live_m2_7_short_trade_only_20260407_visibility_gap_probe` | `data/reports/paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260408_visibility_gap_governed` |
| 交易日 | `2026-03-23` | `2026-03-27` |
| 目的 | 验证 visibility-gap exposure relief 能否把焦点票重新带回短线面 | 验证在新 execution-quality guard 下，visibility-gap 是否还会抬升 weak-overnight 样本 |
| 关注票 | `300720` | `300720` |

## 核心结论

**结论：`visibility-gap` 已经从“可能把弱隔夜样本抬进 near-miss 的 leak path”收口成“最多带回 shadow observation，但不会越过 short-trade 执行面”。**

换句话说，`300720` 并没有从系统中消失；它仍然被识别为值得观察的 `visibility-gap` 焦点票。但在新 governed replay 里，它不再被抬进 `near_miss` 或 `selected`，而是被明确限制在 `shadow_observation_only`。

## 关键证据对比

### 1. 旧 probe：`300720` 仍会被抬进 `near_miss`

旧 probe 的直接证据来自 `btst_next_day_trade_brief_latest.json`：

- `short_trade_selected_count = 0`
- `short_trade_near_miss_count = 1`
- `upstream_shadow_promotable_count = 1`
- `300720.decision = "near_miss"`
- `300720.positive_tags` 包含 `upstream_shadow_catalyst_relief_applied`

对应文件位置：

- `.../paper_trading_20260323_20260323_live_m2_7_short_trade_only_20260407_visibility_gap_probe/session_summary.json:152-155`
- `.../paper_trading_20260323_20260323_live_m2_7_short_trade_only_20260407_visibility_gap_probe/btst_next_day_trade_brief_latest.json:27-88`

这说明旧 probe 下，`visibility-gap` 确实有能力把 `300720` 从上游影子面抬到 short-trade `near_miss`。

### 2. 旧 probe 的最大缺口：历史先验还是 `none / unknown`

旧 probe 中，`300720.historical_prior` 的关键字段是：

- `applied_scope = "none"`
- `sample_count = 0`
- `evaluable_count = 0`
- `execution_quality_label = "unknown"`

这意味着旧 probe 虽然让 `300720` 进入了 `near_miss`，但当时系统并**没有**拿到能约束它的同票执行质量画像，因此还不能判断这次 uplift 是否误放了“盘中兑现、隔夜偏弱”的样本。

## 3. 新 governed replay：`300720` 仍在 visibility-gap 面，但只剩 observation

新 replay 中，`300720` 仍然被明确识别为 `visibility-gap` 焦点票：

- `visibility_gap_tickers = ["300720"]`
- `candidate_pool_shadow_reason = "upstream_base_liquidity_uplift_shadow_visibility_gap_relaxed_band"`
- `shadow_visibility_gap_selected = true`
- `shadow_visibility_gap_relaxed_band = true`

对应文件位置：

- `.../paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260408_visibility_gap_governed/selection_artifacts/2026-03-27/selection_snapshot.json:16957-16978`

但它最终的 short-trade 结果已经变成：

- `decision = "observation"`
- `preferred_entry_mode = "shadow_observation_only"`
- `candidate_source = "upstream_liquidity_corridor_shadow"`
- `score_target = 0.1866`

对应文件位置：

- `.../paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260408_visibility_gap_governed/btst_next_day_trade_brief_latest.json:451-487`
- `.../paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260408_visibility_gap_governed/selection_artifacts/2026-03-27/selection_snapshot.json:19057-19438`

这一步很重要，因为它说明系统现在的行为不再是“看见 visibility-gap 就继续向 near-miss 推”，而是“承认它值得观察，但不默认它具备 BTST 隔夜执行资格”。

### 4. 新 governed replay 拿到了真正可约束的历史画像

新 replay 中，`300720.historical_prior` 已经不再是空白，而是明确显示：

- `applied_scope = "same_ticker"`
- `sample_count = 4`
- `evaluable_count = 4`
- `next_high_hit_rate_at_threshold = 1.0`
- `next_close_positive_rate = 0.0`
- `execution_quality_label = "intraday_only"`
- `entry_timing_bias = "confirm_then_reduce"`

对应文件位置：

- `.../paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260408_visibility_gap_governed/selection_artifacts/2026-03-27/selection_snapshot.json:19348-19406`

这组字段正是本轮治理最关键的变化。它回答了“为什么要把 execution-quality guard 前移到 relief gate”：

1. **因为 `300720` 不是没有空间。** 它的历史 `next_high_hit_rate_at_threshold = 1.0`，说明盘中经常给空间。
2. **但它不适合被当作标准隔夜延续。** `next_close_positive_rate = 0.0` 且 `execution_quality_label = intraday_only`，说明更像“盘中确认后兑现”，而不是“收盘后继续持有”。
3. **所以正确处理方式不是彻底忽略它，而是把它留在 observation。**

## 旧版与新版差异总表

| 对比项 | `2026-03-23` 旧 probe | `2026-03-27` governed replay | 含义 |
|------|------|------|------|
| `short_trade_near_miss_count` | `1` | `0` | 新版不再把焦点票抬进 `near_miss` |
| `upstream_shadow_promotable_count` | `1` | `0` | 新版不再让上游影子召回直接形成可晋升样本 |
| `300720.decision` | `near_miss` | `observation` | 焦点票被降回 shadow observation |
| `historical_prior.applied_scope` | `none` | `same_ticker` | 新版真正读到了同票历史画像 |
| `historical_prior.execution_quality_label` | `unknown` | `intraday_only` | 新版知道它是弱隔夜画像 |
| `historical_prior.next_close_positive_rate` | `null` | `0.0` | 新版有足够证据阻断执行面 uplift |

## 为什么这次结果是好事

这次结果看起来像“没有放出票”，但对当前主线其实是正收益信号。

原因有三点：

1. **它证明治理前移是有效的。**  
   旧版的问题不是完全看不见 `300720`，而是看见后还会把它抬进 `near_miss`。新版仍然看得见，但已经不再误抬。

2. **它证明 artifact 诊断链已经闭环。**  
   现在不需要再猜测是“没拿到 prior”还是“拿到了 prior 但 gate 没拦住”。`same_ticker + intraday_only + next_close_positive_rate = 0.0` 已经明确写进 artifact。

3. **它保留了研究价值，而不是简单删除样本。**  
   `300720` 仍在 `visibility_gap_tickers` 和 shadow 列表中，后续若出现新的盘中强确认，仍可以作为 intraday 观察对象，但不再默认作为 BTST 隔夜候选。

## 当前策略判断

### 应该保留的判断

1. `300720` 仍是值得追踪的上游漏票修复样本。
2. `visibility-gap` 仍然是一个有价值的 shadow 曝光通道。
3. `shadow observation` 不是失败，而是对弱隔夜样本更准确的分层。

### 不应该再做的事

1. 不要再把 `03-23` 的旧 probe 当作“visibility-gap 可稳定提升 BTST 执行面”的证据。
2. 不要因为 `300720` 仍被 shadow 带回，就误判这条路径还在泄漏。
3. 不要为了让它重新进入 `near_miss` 去放宽全局 threshold；当前 blocker 已经不是简单阈值问题，而是明确的 execution-quality 风险画像。

## 下一步建议

1. **把这次对比结论视为 `visibility-gap` 第一阶段治理收口。**
2. **继续审计剩余 recall / supplemental 路径。** 当前最值得继续检查的是：是否还有别的通道会把 `same_ticker + intraday_only` 样本重新抬回 `near_miss`。
3. **若后续 live 再出现同类样本，只接受两种解释：**
   - 该样本没有拿到可靠 `historical_prior`
   - 该样本虽然来自同票，但画像已经不再是 `intraday_only / next_close_positive_rate <= 0`

## 自测检查

1. 为什么旧 probe 不能作为“治理已完成”的证据？
2. 新 governed replay 中，`300720` 为什么仍保留在 shadow 面？
3. `next_high_hit_rate_at_threshold = 1.0` 与 `next_close_positive_rate = 0.0` 的组合，为什么更适合 `intraday_only` 而不是 BTST 隔夜执行？

## 进阶阅读

1. `src/targets/short_trade_target.py`：查看 `visibility_gap_continuation_relief` 的 execution-quality guard 实现。
2. `src/execution/daily_pipeline.py`：查看 watchlist / shadow 路径如何注入 `historical_prior`。
3. `data/reports/paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260408_visibility_gap_governed/selection_artifacts/2026-03-27/selection_snapshot.json`：直接核对 artifact 真值。
