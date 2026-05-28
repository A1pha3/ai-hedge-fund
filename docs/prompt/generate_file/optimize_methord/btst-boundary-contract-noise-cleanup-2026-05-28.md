# BTST 边界契约修复与研究面降噪方案（2026-05-28）

## 结论先说

这轮把 **2026-05-19 ~ 2026-05-23** 的 BTST 因子研究面、边界来源契约和本周日报回测一起对齐后，可以把问题拆成两层：

1. **周度执行层症状**：正式 `selected` 层过度偏向 `T+1/T+2 continuation`，没有对准 `5D/+15%` 目标。  
2. **更上游的研究层根因**：`5D/+15%` 研究样本里有大量噪声，同时 `boundary` 路径缺失核心因子键，导致 round1 的 Alpha 判断从源头失真。

如果只问“本周 formal selected 为什么输给 near_miss”，答案是 **selected 目标错位**。  
如果问“当前系统为什么始终很难稳定找到 5 日内能涨 15% 的 runner”，更深层的答案是：

> **研究样本被噪声污染、boundary 契约缺失，导致真正的 5D/+15% Alpha 根本没有在干净基准上被测出来。**

所以这轮最值得立即推进的，不是直接升级 live admission，而是：

1. **先修 `boundary` 来源契约**
2. **再把噪声从因子研究面里隔离出去**
3. **最后才把 payoff-first selected 重排 + runner recall shadow overlay 推进到更深一层的 shadow backtest**

---

## 一、当前最伤 5D/+15% 目标的根因

### 1. round1 因子研究首轮全部没有通过 Alpha 门

关键证据：

- `data/reports/btst_5d_15pct_factor_research_round1_latest.md`

核心结果：

| 候选层 | hit_rate_15pct | mean_max_return | Alpha 门 |
| --- | ---: | ---: | --- |
| `trend_continuation` | **25.87%** | **10.50%** | 失败 |
| `trend_family` | **25.74%** | **10.28%** | 失败 |
| `breakout_family` | **25.74%** | **10.28%** | 失败 |
| `volume_quality_family` | 19.28% | 8.69% | 失败 |

和最终目标相比：

- 目标 hit rate：`55%+`
- 当前最优原型：`25.87%`
- 差距：**-29 个百分点**

说明当前问题不是“已经接近 rollout，只差一点点”，而是 **整个 5D/+15% 研究面还没有找到可过 Alpha 门的稳定方向**。

---

### 2. 856 行研究样本里，347 行（40.5%）核心特征缺失

关键证据：

- `data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.md`
- `docs/prompt/find_actor_methord/btst-5d15-missing-core-features-noise-compression-2026-05-22.md`

核心结果：

| 噪声桶 | 行数 | 来源 | hit_rate_15pct | 动作 |
| --- | ---: | --- | ---: | --- |
| `watchlist_empty_payload` | 146 | `layer_c_watchlist` | 14.38% | `ignore_observation_noise` |
| `boundary_without_explainability` | 121 | `short_trade_boundary` + `layer_b_boundary` | 6.61% | `inspect_candidate_source_contract` |
| `diagnostic_probe_without_core_features` | 71 | `watchlist_filter_diagnostics` | 7.04% | `exclude_from_factor_surface` |
| `unknown_missing_core_contract` | 9 | `upstream_liquidity_corridor_shadow` | 0.00% | `split_into_separate_research_surface` |

这意味着：

- 研究面里 **40.5%** 的样本并不适合直接参与 Alpha 评价
- 它们的 `5D/+15%` 命中率大多只有 **0%~14%**
- 如果仍把这 347 行和干净样本混在一起，round1 的 hit rate / mean max return 会被系统性压低

也就是说，当前 round1 不是“干净失败”，而是 **污染后失败**。

---

### 3. `boundary` 路径上的核心因子键从源头就缺失

关键证据：

- `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.md`
- `docs/prompt/find_actor_methord/btst-5d15-boundary-contract-inspection-2026-05-22.md`

核心结果：

- `boundary_row_count = 121`
- `short_trade_boundary = 75`
- `layer_b_boundary = 46`

其中最关键的三条：

- `trend_continuation`：`source_payload_count = 0`
- `short_term_reversal`：`source_payload_count = 0`
- `t0_tail_strength`：`source_payload_count = 0`

这说明问题不是“因子在中间链路里被丢了”，而是：

> **`boundary` 路径从源头就没有把这几个关键因子吐出来。**

因此当前最优治理动作已经很明确：

- `governance_action = fix_boundary_source_contract`

---

## 二、为什么这比“直接调 selected 排序”更优先

周度执行层的结论没有错：

- `selected` 的 `5D/+15%` 命中率只有 `0.20`
- `near_miss` 达到 `0.4507`
- `watchlist_filter_diagnostics` 漏掉了 6 只真实 runner
- `short_trade_boundary` / `layer_c_watchlist` 在 formal selected 中的 `5D/+15%` 命中率都为 `0.0`

对应证据：

- `data/reports/btst_weekly_validation_20260518_20260522.json`
- `docs/prompt/generate_file/optimize_methord/btst-payoff-first-selected-rerank-runner-recall-2026-05-28.md`

但这更像是 **症状层**：

- formal selected 确实选错了目标
- payoff-first selected 重排 + runner recall shadow overlay 也确实值得做

不过，如果不先修：

1. `boundary` 契约缺失
2. `watchlist` / `diagnostics` 噪声污染

那后面的 payoff-first 排序优化，仍然会建立在一个 **被污染的研究面** 上。  
最终会出现一个很危险的假象：

- 你以为自己在优化正式层
- 实际上你只是对一堆不完整样本继续做排序微调

所以顺序必须是：

1. **先修数据与研究面**
2. **再修正式层排序**
3. **最后考虑 live admission 是否值得升级**

---

## 二点五、当前 replay / rollout 证据链还有一个执行契约 blocker

这轮又新增了一条不能忽略的证据：

- `data/reports/btst_weekly_execution_selection_mismatch_20260518_20260522.json`
- `data/reports/btst_weekly_execution_selection_mismatch_20260518_20260522.md`

在 `2026-05-18 ~ 2026-05-22` 的正式买单里：

- 总正式买单数：`6`
- 其中 `4` 笔（`66.67%`）对应的 `selection_targets.short_trade.decision` 已经不是 `selected`
- 同样有 `4` 笔的 `execution_eligible = false`

最典型的是：

- `20260518`：`300408` 已是 `near_miss`，`600487` 已是 `rejected`，但两者仍然留在正式 `buy_orders`
- `20260519`：`300408` / `600487` 继续是 `near_miss`，仍然留在正式 `buy_orders`

这说明当前周窗 live artifact 里，至少存在一段 **buy_order / selection_target 的执行契约错位**：

> `buy_orders` 还保留着旧执行结果，但 `selection_targets` 已经不再支持这些名字属于正式执行。

这条证据非常重要，但要注意边界：

- 它**不是**“已经证明这些错配买单一定拖累了 5D/+15%”
- 因为同一组样本里，错配票的 `5D/+15%` 命中率并不比对齐票更差：
  - mismatch：`50.00%`
  - aligned：`0.00%`

所以这条证据的正确定位不是“直接证明 payoff 问题”，而是：

> **当前 replay / rollout 验证链路本身不够干净，不能把这些 frozen live artifact 直接当成 profile shadow rollout 的充分证据。**

也就是说：

- 周度主结论仍然是 `selected` 目标错位、`layer_c_watchlist` 是更稳定的 formal payoff drag、`watchlist_filter_diagnostics` 漏掉 runner；
- 但在执行验证层，还需要额外修复 **buy_order / selection_target / replay shell** 的契约一致性，才能让后续 shadow replay 真正具备 rollout 说服力。

这条 blocker 现在又往前推进了一步，新增证据：

- `data/reports/btst_shadow_profile_replay_sidecar_aware_20260518_20260522.json`
- `data/reports/btst_shadow_profile_replay_sidecar_aware_20260518_20260522.md`

通过补齐 replay shell sidecar 消费、sidecar-backed selection_target 重建，以及 replay compare 的 profile overrides 后，真实 live 基线 `momentum_optimized + {"select_threshold": 0.5}` 已经能在周级 replay 上稳定看到：

- `layer_c_watchlist_selected_rank_cap=0` 会把 `20260518` 的 `605117`、`20260522` 的 `002222 / 300054 / 600176` 从 formal `selected` 降到非正式层；
- `selected_count` 从 `22` 降到 `18`，`near_miss_count` 从 `64` 升到 `68`；
- `execution_eligible_count` 与 `buy_order_count` 现在也都从 `2` 降到 `0`，真实周窗第一次出现 execution 层 delta。

这说明 replay blocker 的状态已经从：

- “真实 frozen replay 连 selected 层都不一定能重建出来”

收敛成：

- “selected 层与 execution 层都已经能在真实周窗里复现出 shadow delta”。

因此当前最准确的 rollout 口径应该改成：

1. **selection-layer replay blocker 已解除**
2. **execution-layer replay blocker 也已经在 `300054 / 002222` 这组关键样本上打通**
3. 但这仍然只是单周 shadow replay 证据，不能直接包装成 live 默认升级完成

并且这条 execution replay 证据已经不只是一周窗：

- `data/reports/btst_shadow_profile_replay_sidecar_aware_20260506_20260522.json`
- `data/reports/btst_shadow_profile_replay_sidecar_aware_20260506_20260522.md`

在 **2026-05-06 ~ 2026-05-22** 的 13 个完整日报窗口里，`layer_c_watchlist_selected_rank_cap=0` 会把：

- `20260508` 的 `688183`
- `20260522` 的 `002222 / 300054`

从 baseline 的 formal `execution_eligible + buy_order` 打到 shadow 的 `0`，对应聚合结果是：

- `execution_eligible_count: 3 -> 0`
- `buy_order_count: 3 -> 0`

所以这条线现在已经从“单周可见”推进到“扩窗后仍然可见”，只差更长样本外窗口去决定它够不够进入更强的 governed rollout。

这条 governed rollout 线现在也已经收敛成了统一 artifact：

- `data/reports/btst_layer_c_rollout_validation_20260506_20260522.json`
- `data/reports/btst_layer_c_rollout_validation_20260506_20260522.md`
- `docs/prompt/generate_file/optimize_methord/btst-layer-c-formal-precision-rollout-2026-05-28.md`

对应状态是：

- `status = governed_shadow_ready`
- `primary_lane = layer_c_formal_precision_tightening`

因此这一节的重点，已经不再是“replay blocker 还卡着什么”，而是：

1. replay fidelity 足够支撑 governed rollout 判断；
2. 是否进入默认升级，取决于更长窗口和样本外证据；
3. 更上游仍然要继续修 `boundary` 契约和研究面降噪，否则 rollout 判断会重新被污染。

这一步之所以能打通，是因为 `20260522` 那组 execution-layer fidelity gap 也已经被补上了：

- `data/reports/btst_execution_replay_fidelity_gap_20260522.json`
- `data/reports/btst_execution_replay_fidelity_gap_20260522.md`

在 `20260522` 这一天，原始 `selection_snapshot` 里：

- `300054`
- `002222`

都属于 `selected + execution_eligible = true`。

但对应的 `selection_target_replay_input.watchlist` 行里，两个名字的 `strategy_signals` 都是空的：

- `300054`：只剩 `canonical_btst_evaluation_bundle`
- `002222`：只剩少量 top-level metrics（`trend_acceleration / close_strength / catalyst_freshness / sector_resonance` 等）

先前的缺口不是停留在诊断层，而是已经完成了两段修复：

1. frozen replay 会在 replay-input 过稀时，从同目录 `selection_snapshot` 回填 rich row 的 `strategy_signals` 等关键字段；
2. 对 sidecar-backed frozen plans，会在清空 `buy_orders` 做 shadow replay 时，额外保留原始 formal buy bridge，只用于 replay 后的 execution-bridge 同步，不再把 stale buy_order 直接喂回 target 决策。

修完之后，这两个名字不再从：

- 原始 snapshot：`selected + execution_eligible=true`

掉成：

- replay：`selected + execution_eligible=true`

也就是说，当前这组样本上的 execution-layer fidelity gap 已经闭合，不再是：

> **selected-layer 回来了，但 execution-layer 还穿不透。**

因此，之前“先二选一：artifact enrichment vs replay hydration”的架构选择，现在已经完成了第一阶段闭环：

1. **replay hydration 这条路已经落地并验证有效**：它修复了 `300054 / 002222` 的 selected-layer replay；
2. **sidecar-backed preserved execution bridge 也已经落地并验证有效**：它让 baseline replay 的 `execution_eligible / buy_orders` 恢复到与原始 snapshot 一致；
3. **`layer_c_watchlist_selected_rank_cap=0` 现在已经不是只有 selected 层 delta 的 shadow 假设，而是具备了真实 formal buy 收缩证据的 governed replay 方案。**

换句话说，当前 blocker 已经不再是 replay fidelity；剩下的主要问题回到更上游的研究面噪声、boundary 契约，以及扩窗/样本外 rollout 证据是否足够。

---

## 三、这轮验证出来的三个方向

### 方向 A：Catalyst + 低过热 close_strength 窄 Gate

关键证据：

- `data/reports/btst_5d_15pct_trend_gate_threshold_grid_latest.md`
- `data/reports/btst_5d_15pct_trend_gate_oos_validation_catalyst_close_lt_0_86_top20.md`
- `docs/prompt/find_actor_methord/btst-5d15-catalyst-close-strength-confirmation-boundary-2026-05-23.md`

当前最接近目标的方向是：

- `candidate_source == catalyst_theme`
- `trend_acceleration_top_20pct`
- `next_open_return <= 3%`
- `close_strength <= 0.89`

现有证据表明：

- `close_strength < 0.90` 时，`candidate_unique_hit_rate_15pct = 45.45%`
- 再叠确认后，小样本能到 `60%~75%`

但当前样本量还不足以 rollout，所以只能继续 **collect samples**。

### 方向 B：Boundary 契约修复 + 研究面降噪

这轮最值得马上做的方向。

原因：

1. 这是 **确定性代码问题**
2. 不依赖未来行情
3. 已有明确治理动作
4. 是方向 A 和 payoff-first 排序优化的前置依赖

### 方向 C：执行质量字段补齐

比如补：

- `payoff_ratio`
- `profit_factor`
- `expectancy`
- 结构化开盘执行条件

这条有价值，但优先级低于方向 B，因为它不会直接修复当前研究面失真问题。

---

## 四、当前最优推进顺序

### 第 1 步：立刻推进方向 B

目标：

- 修复 `short_trade_boundary` / `layer_b_boundary` 的 source contract
- 把 `trend_continuation`、`short_term_reversal`、`t0_tail_strength` 补到源头
- 将 `layer_c_watchlist` / `watchlist_filter_diagnostics` 从 round1 因子研究面里隔离

预期收益：

- 把 856 行污染样本净化为更接近真实 Alpha 的干净研究面
- 让 round1 的 `hit_rate_15pct` / `mean_max_return` 重新具备解释力

### 第 2 步：同步继续积累方向 A 的 closed 样本

目标：

- 继续收集 `catalyst_theme + close_strength <= 0.89` 的 closed 样本
- 把当前 `11` 个去重 closed 往 `30` 个以上推
- 继续观察 `quality_promising_but_sample_size_still_small` 是否能升级

### 第 3 步：在干净研究面上继续推进 payoff-first selected 重排

前提：

- boundary 契约修复完成
- round1 clean-sample 结果更新

然后再继续验证：

1. `short_trade_boundary / layer_c_watchlist` 是否应降级
2. `watchlist_filter_diagnostics` 是否应进入 runner recall review
3. payoff-first selected 重排是否在不污染 continuation 主链的前提下抬升 `5D/+15%`

---

## 五、alpha / beta / gamma 的统一结论

### alpha

当前首要问题不是再发明一个新因子，而是：

- 先把研究样本清干净
- 先把缺失的关键因子键补齐
- 再判断哪个方向真的能服务 `5D/+15%`

### beta

执行侧现在最容易犯的错，不是“太保守”，而是：

- 把 `boundary` / `watchlist` 里本来不完整、或者本来不该入 formal 的样本，提前送进执行链路

所以 beta 当前不应该直接放松 live admission，而应该等上游研究面干净后，再做更可靠的 shadow backtest。

### gamma

Gamma 的正式态度应当是：

- `boundary contract fix`：**应立即推进**
- `payoff-first selected 重排`：**允许 shadow rollout**
- `默认 live admission 升级`：**当前仍不允许**

---

## 六、当前阶段的正式判断

如果只看本周 formal selected 的表现，最大问题是：

> **selected 目标错位，过度偏向 continuation。**

如果看整个系统为什么还做不到 `5D/+15%` 目标，最大问题是：

> **研究面里有 40.5% 的噪声样本，同时 boundary 路径缺失核心因子键，导致真正的 5D/+15% Alpha 无法在干净基准上被识别。**

所以这轮最值得推进的立即任务不是“直接改默认 admission”，而是：

1. **修复 boundary source contract**
2. **对 research surface 做 noise compression**
3. **然后再在干净样本上推进 payoff-first selected 重排 + runner recall shadow overlay**

---

## 七、关键证据文件

- `data/reports/btst_5d_15pct_factor_research_round1_latest.md`
- `data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.md`
- `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.md`
- `data/reports/btst_5d_15pct_trend_gate_threshold_grid_latest.md`
- `data/reports/btst_5d_15pct_trend_gate_oos_validation_catalyst_close_lt_0_86_top20.md`
- `data/reports/btst_weekly_validation_20260518_20260522.json`
- `docs/prompt/generate_file/optimize_methord/btst-payoff-first-selected-rerank-runner-recall-2026-05-28.md`
- `docs/prompt/find_actor_methord/btst-5d15-boundary-contract-inspection-2026-05-22.md`
- `docs/prompt/find_actor_methord/btst-5d15-missing-core-features-noise-compression-2026-05-22.md`
- `docs/prompt/find_actor_methord/btst-5d15-catalyst-close-strength-confirmation-boundary-2026-05-23.md`
