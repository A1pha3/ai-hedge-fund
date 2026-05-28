# BTST payoff-first selected 重排与 runner recall 方案（2026-05-28）

## 结论先说

这轮按 **2026-05-18 ~ 2026-05-22** 这一个完整交易周，把 BTST 每日交易分析报告和次日/后续实际行情做了周度回测后，当前系统最伤胜率和赔率的核心问题已经比较清楚：

- **正式 `selected` 层的排序目标和最终目标错位了。**
- 系统现在更像是在挑 **`T+1/T+2` 容易延续的票**，而不是在挑 **`5` 个交易日内更容易冲出 `+15%` 的 runner**。
- 结果是：
  - 正式 `selected` 层本周 `5D/+15%` 命中率只有 **20.00%（3/15）**；
  - 反而 `near_miss` 层达到 **45.07%（32/71）**；
  - 被 `blocked/rejected` 的票里，仍然漏掉了 **6** 只真实 `5D/+15%` runner；
  - 这些漏掉的 runner **全部** 来自 `watchlist_filter_diagnostics`。

换句话说，当前主矛盾已经不是“票不够多”或“执行不够激进”，而是 **正式层把偏 continuation 的低赔率样本排在前面，同时把更像 delayed-runner 的样本压在正式层之外**。

## 这周回测把问题暴露得很直白

### 周度聚合结果

本周一共回放出 `111` 条 short-trade 决策样本，全部已经有 closed-cycle 结果：

| 层级 | 样本数 | 5日内最高涨幅 >=15% 命中率 | 5日内最高涨幅均值 | T+2 收盘正收益率 | T+2 >=5% 命中率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `selected` | 15 | **20.00%** | **11.84%** | **73.33%** | **66.67%** |
| `near_miss` | 71 | **45.07%** | **16.10%** | 57.75% | 35.21% |
| `tradeable(selected+near_miss)` | 86 | 40.70% | 15.36% | 60.47% | 40.70% |
| `blocked+rejected` | 25 | 24.00% | 11.49% | 56.00% | 40.00% |

这组数说明两件事：

1. **当前正式层确实更擅长做短一拍的 continuation**，因为它的 `T+2` 数据明显更好；
2. 但它 **没有把真正符合最终目标的 runner 放到正式层**，因为 `5D/+15%` 反而明显落后于 `near_miss`。

### 被正式层选中的弱样本长什么样

本周正式 `selected` 里，最拖后腿的是两类来源：

1. `short_trade_boundary`
2. `layer_c_watchlist`

只看这两类被抬进正式层的样本：

- `count = 5`
- `5D/+15% hit_rate = 0.00%`
- `mean_max_future_high_return_2_5d = 7.87%`

也就是说，本周一旦把这两类边界/观察池样本抬成正式票，**5日赔率基本立刻塌掉**。

### 最新 shadow 剔除验证结果

基于刚更新的 `data/reports/btst_weekly_validation_20260518_20260522.json`，这周已经把

- `short_trade_boundary`
- `layer_c_watchlist`

从正式 `selected` 里做了一次 **shadow-only 剔除情景**，结果如下：

| 情景 | selected 样本数 | 5日内最高涨幅 >=15% 命中率 | T+2 收盘正收益率 |
| --- | ---: | ---: | ---: |
| 原始 `selected` | 15 | **20.00%** | **73.33%** |
| shadow 剔除 `short_trade_boundary + layer_c_watchlist` 后 | 10 | **30.00%** | 70.00% |

这条结果很重要，因为它说明：

1. 现在已经有周度回测证明，**先把这两类来源从正式层降权/剔除，5D/+15% 命中率能从 `0.20` 提升到 `0.30`**；
2. 代价相对可控：`T+2` 正收益率只从 `0.7333` 回落到 `0.70`；
3. 所以下一步最值得做的，不是扩大候选池，而是把这条 **formal-source downrank / exclusion shadow** 做成受控 admission backtest。

### 扩窗后的收敛结论

为了避免只被单周样本误导，这轮又把窗口扩到 **2026-05-06 ~ 2026-05-22**（无缺日报，共 `13` 个完整日报）重新验证：

| 情景 | selected 样本数 | 5日内最高涨幅 >=15% 命中率 | T+2 收盘正收益率 |
| --- | ---: | ---: | ---: |
| 原始 `selected` | 26 | **30.77%** | **65.38%** |
| shadow 剔除 `layer_c_watchlist` 后 | 24 | **33.33%** | 62.50% |

这一步把结论收敛得更清楚了：

1. **`layer_c_watchlist` 是更稳定的 formal payoff drag**，因为扩窗后它仍然是唯一保持 `5D/+15% = 0%` 的正式层来源；
2. `short_trade_boundary` 在单周窗口里很差，但扩到 13 个日报后，`5D/+15% hit_rate = 33.33%`，说明它更像**周度波动较大的次级问题**，还不适合直接全局剔除；
3. 因此更合理的执行顺序应该改成：
   - 先做 `layer_c_watchlist` 的正式层降权 / admission shadow；
   - 再单独验证 `short_trade_boundary` 是否只在某些市场窗口里需要收紧；
   - `watchlist_filter_diagnostics` 继续沿 runner recall 复审线推进，而不是简单抬升为正式票。

### 被系统漏掉的强 runner 长什么样

本周被 `blocked/rejected`、但后验上真实达到 `5D/+15%` 的 false negative 一共 `6` 只，全部来自：

- `candidate_source = watchlist_filter_diagnostics`

典型样本：

1. `603256`
   - `2026-05-19`：`score_target = 0.2049`
   - `max_future_high_return_2_5d = +39.11%`
   - `T+2 close return = +5.59%`
2. `688183`
   - `2026-05-20`：`score_target = 0.2040`
   - `max_future_high_return_2_5d = +32.51%`
3. `002463`
   - `2026-05-19`：`score_target = 0.2530`
   - `max_future_high_return_2_5d = +31.37%`
4. `002463`
   - `2026-05-20`：`score_target = 0.1982`
   - `max_future_high_return_2_5d = +30.13%`
5. `603256`
   - `2026-05-22`：`score_target = 0.2058`
   - `max_future_high_return_2_5d = +19.77%`
6. `300308`
   - `2026-05-21`：`score_target = 0.1539`
   - `max_future_high_return_2_5d = +15.47%`

这 6 只票的共同点很明确：

- 它们不是当前正式层偏好的高 continuation 票；
- 它们更像 **低分、延迟兑现、后续扩张更强** 的 runner；
- 当前正式层的排序逻辑，对这类票天然不友好。

## alpha / beta / gamma 一起给出的诊断

### alpha：标签错位，正式层仍在优化“次日延续”而不是“5日扩张”

alpha 视角下，当前正式层真正优化的目标更接近：

- `next_close_positive_rate`
- `T+2 close continuation`
- `confirm_then_hold_breakout`

而不是用户要求的：

- `5` 个交易日内
- `55%+` 概率
- `max_future_high_return >= 15%`

这也是为什么本周正式层会出现这种典型错位：

- `selected` 的 `T+2` 很漂亮；
- 但 `5D/+15%` 明显输给 `near_miss`。

再看仓库已有的长期 OOS 证据，这个问题不是本周偶发，而是主线结构性问题：

- `btst_5d_15pct_trend_gate_oos_validation_latest.json`
  - `trend_acceleration_ge_0_85` 基础门在 `2026-05` 的 `hit_rate_15pct` 只有 **30.43%**
  - 同一门在 `2026-04` 还能到 **62.50%**
- `btst_5d_15pct_trend_breakout_drilldown_latest.json`
  - `trend_acceleration_top_20pct_selected_only` 的 `hit_rate_15pct` 只有 **23.68%**
  - 并且已经被标成 `decision = "downgrade"`

这说明 **把高趋势 continuation 样本直接压进正式层**，并不能稳定服务 `5D/+15%` 目标。

### beta：执行模式没有错，错的是谁被送进了执行模式

beta 视角下，本周最大的执行问题不是：

- `confirm_then_hold_breakout` 本身错误；
- 或者执行卡太保守；

而是：

- **哪些票被送进了 `confirm_then_hold_breakout`**

本周正式层里表现最差的，是被抬进正式层的：

- `short_trade_boundary`
- `layer_c_watchlist`

这两类样本本周 `5D/+15% = 0%`，说明当前执行模式被喂进去的是 **偏 continuation、但不够 runner 化** 的样本。

相反，本周最接近用户最终目标的候选来源是：

- `candidate_source = catalyst_theme`

它在本周全样本上的表现是：

- `count = 33`
- `5D/+15% hit_rate = 54.55%`
- `mean_max_future_high_return_2_5d = 17.36%`

这已经几乎贴到用户要求的最终线了。

所以 beta 侧的结论不是“把执行变激进”，而是：

> 先把正式层的喂票结构改对，再谈执行模式优化。

### gamma：方向已经出来了，但还不够资格直接默认升级

gamma 侧需要把好最后一道纪律：

- 当前方向 **值得做 shadow rollout**
- 但 **还不值得默认升级**

原因有两层：

1. 仓库已有 OOS confirmation grid 确实给出更优方向  
   `btst_5d_15pct_trend_gate_confirmation_grid_latest.json` 显示：
   - 基础 slice：`catalyst_theme_close_strength_lt_0_90`
   - 基础命中率：**45.45%**
   - 加上 `close_strength <= 0.890` 后：
     - `candidate_unique_hit_rate_15pct = 60.00%`
     - `candidate_unique_mean_max_return = 21.79%`
   - 但当前结论仍然是：
     - `next_step = keep_confirmation_candidate_collect_samples`

2. 更广覆盖的数据完备度还不够  
   `btst_5d_15pct_scoped_missing_price_manifest_latest.json` 显示：
   - `local_outcome_count = 777`
   - `missing_count = 1989`
   - `coverage_rate = 28.09%`

所以 gamma 侧的正式结论应该是：

- **可以做 payoff-first shadow overlay**
- **不可以把它包装成默认升级完成**

## 这轮确定下来的最优方案

### 方案名

**payoff-first selected 重排 + runner recall shadow overlay**

### 核心思想

不是继续放松阈值，而是把当前正式层拆成两种完全不同的角色：

1. **continuation 正式执行层**
   - 只保留那些既有 `T+2` 兑现，也没有明显拖累 `5D/+15%` 的名字；
2. **runner recall 复审层**
   - 专门承接那些当前分数不高、但更像 `5D` 扩张票的 delayed-runner。

### alpha 落点

alpha 侧新增一条明确的排序纪律：

1. 正式 `selected` 不再优先提升
   - `short_trade_boundary`
   - `layer_c_watchlist`
   这两类没有 `5D/+15%` 证据的样本；
   - 单周 shadow 剔除已经验证：移除这两类来源后，`selected` 的 `5D/+15%` 命中率能从 `20%` 提升到 `30%`；
   - 但扩窗后更稳定的 drag 只剩 `layer_c_watchlist`，因此 admission shadow 的第一优先级应该先落在它身上；
   - 仓库里已经补出一个**默认不生效**的命名 shadow profile：`btst_precision_v2_layer_c_watchlist_shadow`，它通过 `layer_c_watchlist_selected_rank_cap=0` 把 layer C 来源从正式 `selected` 里降到非正式层，方便后续 replay / backtest 直接验证；
2. `candidate_source = catalyst_theme` 单独做 payoff-first 优先级加成；
3. 对 `watchlist_filter_diagnostics` 的低分拒绝带，新增 **runner recall review**，不再把它们统一视为低价值噪音。

这一步不是直接把 diagnostics reject 全部抬成正式票，而是承认：

- 它们里边确实藏着本周最集中的 runner false negatives；
- 所以它们必须有一条单独的复审通道。

### beta 落点

beta 侧不建议直接改成“无脑追强”，而是把执行分成两类：

1. **continuation 主票**
   - 继续按 `confirm_then_hold_breakout`
   - 但只给真正有 `5D` 赔率证明的主票
2. **runner recall 票**
   - 统一按 `next_day_breakout_confirmation`
   - 不抢主票，不做无确认开盘追价
   - 只有盘中新强度确认后，才允许升级

这样做的意义是：

- 不会破坏当前 continuation 主链；
- 同时能把本周 `603256 / 002463 / 688183 / 300308` 这类 delayed-runner 从“直接拒绝”改成“受控复审”。

### gamma 落点

gamma 侧的 rollout 纪律固定为：

1. 先做 **shadow overlay**
2. 不改默认 profile
3. 不把 `runner recall` 直接写成正式升级完成
4. 先补历史 outcome coverage，再决定是否默认接入

当前最稳的推进方式是：

- 先把 `payoff-first selected 重排` 做成周度 shadow 评估项；
- frozen replay 侧现在优先走 manifest-driven 入口：`uv run python scripts/analyze_btst_shadow_profile_replay.py --weekly-validation-json data/reports/btst_weekly_validation_20260506_20260522.json --baseline-profile btst_precision_v2 --baseline-overrides '{}' --shadow-profile btst_precision_v2_layer_c_watchlist_shadow --shadow-overrides '{}'`，不再手工拼 `daily_events.jsonl` 列表；
- rollout 结论统一回收到 `data/reports/btst_layer_c_rollout_validation_20260506_20260522.{json,md}`；
- 连续观察：
  - 正式层 `5D/+15% hit_rate`
  - runner recall 层 `5D/+15% hit_rate`
  - false negative 回收数
  - continuation 主链是否被明显污染

### 最新 sidecar-aware replay 结果

这轮把 frozen replay 再往前推进了一步：

- `build_plan_target_shell_inputs()` 现在会优先消费 `frozen_selection_target_replay_input` 的 watchlist / rejected / supplemental sidecar；
- `_ensure_plan_target_shells()` 会把 sidecar shell 认定为 **可重建输入**，不再在 sidecar 存在时错误保留旧 `selection_targets`；
- `scripts/analyze_btst_shadow_profile_replay.py` 新增了 `baseline/shadow overrides`，可以直接复现真实 live 基线。

对应的真实周级 sidecar-aware replay 证据：

- `data/reports/btst_shadow_profile_replay_sidecar_aware_20260518_20260522.json`
- `data/reports/btst_shadow_profile_replay_sidecar_aware_20260518_20260522.md`

在真实 live 基线 `momentum_optimized + {"select_threshold": 0.5}` 下，`layer_c_watchlist_selected_rank_cap=0` 的 shadow 结果是：

| 指标 | Baseline | Shadow | Delta |
| --- | ---: | ---: | ---: |
| `selected_count` | 22 | 18 | **-4** |
| `near_miss_count` | 64 | 68 | **+4** |
| `execution_eligible_count` | 2 | 0 | **-2** |
| `buy_order_count` | 2 | 0 | **-2** |

被 shadow 从正式 `selected` 层移除的是真实 `layer_c_watchlist` 名字：

- `20260518`：`605117`
- `20260522`：`002222`、`300054`、`600176`

这条结果的意义很明确：

1. **`layer_c_watchlist` 的 admission shadow 已经在真实周 replay 上打到了 selected 层**，不再只是停留在周度统计假设；
2. 这次新增被 shadow 移除的 `002222 / 300054` 也证明：在给稀疏 replay-input 行补齐 `selection_snapshot` rich row，并保留 sidecar 里的原始 formal buy bridge 后，`20260522` 的 **selected-layer + execution-layer fidelity 都已经明显提高**；
3. 真实周级 replay 现在第一次出现了 execution 层 delta：`20260522` 的 `002222 / 300054` 在 baseline 里仍是 formal `execution_eligible + buy_order`，而 shadow 会把它们一起打掉；
4. 因此当前可以确认的不再只是“selected 层结构被纠偏”，而是 **本周 formal buy 收缩也已经能被 frozen replay 复现出来**；
5. 但这仍然是 **shadow-only / governed follow-up** 证据，不等于默认 live 升级完成；下一步仍要扩窗、回测和样本外验证。

### 扩窗后的 execution replay 结果

这轮又把同一套 sidecar-aware shadow replay 扩到 **2026-05-06 ~ 2026-05-22** 的 13 个完整日报窗口，新增证据：

- `data/reports/btst_shadow_profile_replay_sidecar_aware_20260506_20260522.json`
- `data/reports/btst_shadow_profile_replay_sidecar_aware_20260506_20260522.md`

扩窗后的核心结果是：

| 指标 | Baseline | Shadow | Delta |
| --- | ---: | ---: | ---: |
| `selected_count` | 79 | 74 | **-5** |
| `near_miss_count` | 145 | 150 | **+5** |
| `execution_eligible_count` | 3 | 0 | **-3** |
| `buy_order_count` | 3 | 0 | **-3** |

其中 execution / buy 层被 shadow 打掉的正式票来自两天：

1. `20260508`：`688183`
2. `20260522`：`002222`、`300054`

这说明 `layer_c_watchlist_selected_rank_cap=0` 不只是单周碰巧打掉两只票，而是在更长窗口里也会**稳定收缩 formal buy**。  
当然，样本量依然不大，所以这条证据现在最适合用来支撑 **governed replay rollout**，还不够直接升级成默认 live admission。

### 当前正式 rollout 口径

这一步现在已经不需要继续靠手工口述汇总，统一口径已经收敛到：

- `data/reports/btst_layer_c_rollout_validation_20260506_20260522.json`
- `data/reports/btst_layer_c_rollout_validation_20260506_20260522.md`
- `docs/prompt/generate_file/optimize_methord/btst-layer-c-formal-precision-rollout-2026-05-28.md`

对应结论是：

1. `status = governed_shadow_ready`
2. `primary_lane = layer_c_formal_precision_tightening`
3. `summary = 先收 formal buy：shadow 把 execution_eligible 收缩 3 个、buy_order 收缩 3 个，同时 5D/+15% 命中率从 0.3077 提升到 0.3333。`

所以这份文档后续更多承担 **runner recall / payoff-first 诊断** 的角色；  
`layer_c_watchlist` 的 formal 收缩 rollout 结论，统一以新 rollout artifact 和专门文档为准。

## 为什么这套方案是当前最优，而不是别的方向

### 不是继续放宽 broad trend gate

仓库已有 OOS 板已经说明：

- broad `trend_acceleration` 门在 `2026-05` 明显失效；
- `selected_only` drilldown 已经被明确标成 `downgrade`。

所以再去放宽大门，只会把 continuation 噪音放得更大。

### 不是继续把所有低分 diagnostics reject 打回去

这一层里确实有强 runner，但也有噪音。

因此正确做法不是：

- 直接把 diagnostics reject 全体升成正式票；

而是：

- 新增 `runner recall review`，
- 让这类样本先进入受控复审层，
- 由盘中确认来决定能不能升级。

### 不是现在就默认启用 OOS confirmation candidate

`catalyst_theme + close_strength <= 0.890` 的 OOS 候选方向很有希望，
但仓库自己的 validation 结论已经写明：

- `quality_promising_but_sample_size_still_small`

所以这一步现在只能作为：

- **shadow priority overlay**

不能写成：

- **default upgrade**

## 这轮方案的最小可执行版本

如果只做一轮最小、最安全、最贴主线的改动，建议顺序固定为：

1. **先降级**
   - 正式层里的 `short_trade_boundary`
   - 正式层里的 `layer_c_watchlist`
2. **再加一层**
   - `watchlist_filter_diagnostics_runner_recall_review`
3. **最后重排**
   - `catalyst_theme` 在 payoff-first 目标下优先于 continuation-only 边界样本

这个顺序的好处是：

1. 先把本周已经确认拖赔率的正式层噪音拿掉；
2. 再把本周真实漏掉的 runner 类型补一个入口；
3. 最后才讨论更大范围的默认升级。

## 当前判断

这轮回测后，当前 BTST 系统最大的具体问题已经不是抽象的“精度还不够”，而是：

> **正式层把 continuation 友好的边界样本排到了前面，却没有把更像 5D runner 的 recall 样本纳入正式复审逻辑。**

因此，当前最值得推进的，不是继续调大 broad gate，也不是继续放松执行阈值，而是：

1. **把正式层改成 payoff-first 重排**
2. **给 diagnostics reject 单独补一条 runner recall review**
3. **先 shadow rollout，再等覆盖率和样本数补足后决定是否默认升级**

## 2026-05-28 已落地的最小 shadow rollout

本轮代码层先落地的是 **最小、最保守的 reporting shadow overlay**，还没有改默认 admission 阈值：

1. `btst_next_day_trade_brief` 新增 **Payoff-First Runner Recall Review** 段落；
2. `btst_premarket_execution_card` 新增 **Runner Recall Review Actions** 段落；
3. 只从 `watchlist_filter_diagnostics` 中抽取 recall 候选；
4. 默认只做 **shadow_review_only**，明确不直接并入 formal BTST 执行名单；
5. 对明显 `payoff_divergence_risk` 的样本继续排除，避免把坏赔率样本重新包装成 recall 机会。
6. 周度复盘已经固化成仓库内 artifact：
   - `scripts/analyze_btst_weekly_validation.py`
   - `data/reports/btst_weekly_validation_20260518_20260522.json`
   - `data/reports/btst_weekly_validation_20260518_20260522.md`

这一步的目的不是“把漏票直接升格”，而是先把本周反复出现的 delayed-runner 漏票放进一个可追踪、可复盘、可继续回测验证的影子复审层。

## 这轮分析使用的关键证据

- `data/reports/btst_full_report_20260518.json`
- `data/reports/btst_full_report_20260519.json`
- `data/reports/btst_full_report_20260520.json`
- `data/reports/btst_full_report_20260521.json`
- `data/reports/btst_full_report_20260522.json`
- `data/reports/paper_trading_20260518_20260518_live_m2_7_short_trade_only_20260519_plan/session_summary.json`
- `data/reports/paper_trading_20260519_20260519_live_m2_7_short_trade_only_20260520_plan/session_summary.json`
- `data/reports/paper_trading_2026-05-20_2026-05-20_live_m2_7_short_trade_only_20260520_plan/session_summary.json`
- `data/reports/paper_trading_2026-05-21_2026-05-21_live_m2_7_short_trade_only_20260521_plan/session_summary.json`
- `data/reports/paper_trading_20260522_20260522_live_m2_7_short_trade_only_20260525_plan/session_summary.json`
- `data/reports/btst_5d_15pct_trend_gate_oos_validation_latest.json`
- `data/reports/btst_5d_15pct_trend_gate_confirmation_grid_latest.json`
- `data/reports/btst_5d_15pct_trend_breakout_drilldown_latest.json`
- `data/reports/btst_5d_15pct_scoped_missing_price_manifest_latest.json`
- `data/reports/btst_weekly_validation_20260518_20260522.json`

## 最新 analyzer artifact 输出

这轮又把 payoff / runner 诊断单独固化成了两份 JSON：

- `data/reports/btst_runner_payoff_realignment_20260518_20260522.json`
- `data/reports/btst_runner_payoff_realignment_20260506_20260522.json`

对应输出把当前结论重新钉实了一遍：

### 周度窗口 `2026-05-18 ~ 2026-05-22`

- `primary_problem = formal_selected_target_misalignment`
- `selected_hit_rate_15pct = 0.2000`
- `near_miss_hit_rate_15pct = 0.4507`
- `payoff_gap_vs_near_miss_15pct = 0.2507`
- `watchlist_filter_diagnostics_false_negatives = 6`
- `formal_source_drag_count = 2`
- `recommendation = staged_formal_shrink_plus_runner_recall`

### 扩窗 `2026-05-06 ~ 2026-05-22`

- `primary_problem = formal_selected_target_misalignment`
- `selected_hit_rate_15pct = 0.3077`
- `near_miss_hit_rate_15pct = 0.3564`
- `payoff_gap_vs_near_miss_15pct = 0.0487`
- `watchlist_filter_diagnostics_false_negatives = 13`
- `formal_source_drag_count = 1`
- `recommendation = staged_formal_shrink_plus_runner_recall`

这一步的意义在于：  
现在不只是长文里“解释为什么要这么做”，而是已经有独立 analyzer artifact 明确给出同一句建议——**先做 formal-source shrink，再做 payoff-first runner recall**。这让后续 rollout 文档、周度复盘和 profile 讨论都能直接引用同一组机器产出的结论。
