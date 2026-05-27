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
- 连续观察：
  - 正式层 `5D/+15% hit_rate`
  - runner recall 层 `5D/+15% hit_rate`
  - false negative 回收数
  - continuation 主链是否被明显污染

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
- `/Users/matrix/.copilot/session-state/92e81f7f-f1a5-403e-bbf3-3748d8d414aa/files/weekly_btst_20260518_20260522/weekly_outcome_aggregate.json`
