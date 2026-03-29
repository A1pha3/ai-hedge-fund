# BTST 排障与问题定位手册

适用对象：在 BTST 真实窗口、replay 校准或研究复盘中遇到异常结果，想快速判断问题落在哪一层的研究员、开发者和 AI 助手。

这份文档解决的问题：把常见 BTST 症状，直接映射成最可能的根因、优先检查对象和建议动作，减少“知道不对，但不知道先查哪里”的时间浪费。

---

## 1. 先用一句话理解排障顺序

BTST 排障最稳的顺序不是“先调参数”，而是：

```text
先定位在哪一层出问题
  -> 再确认是结构问题还是阈值问题
  -> 再决定用哪个脚本或哪个参数组
```

---

## 2. 五层问题地图

### 2.1 第 1 层：Layer B 供给

典型问题：上游几乎没有可研究候选。

常看对象：

1. `layer_b_count`
2. `fast_pool`
3. `score_b`
4. Layer B 语义与 heavy score 覆盖

### 2.2 第 2 层：short trade boundary admission

典型问题：上游有候选，但 boundary 入口太冷。

常看对象：

1. `candidate_count`
2. `filtered_reason_counts`
3. boundary floor 各项指标

### 2.3 第 3 层：short trade target 正式评分

典型问题：admission 已经过了，但 selected / near_miss 很少。

常看对象：

1. `score_target`
2. gap to near-miss
3. `weighted_positive_contributions`
4. `weighted_negative_contributions`

### 2.4 第 4 层：structural conflict / blocker

典型问题：样本不是分数不够，而是被结构直接挡住。

常看对象：

1. `blockers`
2. `bc_conflict`
3. `gate_status`
4. penalty block threshold

### 2.5 第 5 层：execution 承接

典型问题：规则上通过了，但没有真实执行价值。

常看对象：

1. `included_in_buy_orders`
2. buy order 转化
3. T+1 确认
4. 次日实际表现

---

## 3. 症状到根因速查表

| 症状 | 最可能问题层 | 优先检查 | 常见建议动作 |
| --- | --- | --- | --- |
| BTST 候选总体很少 | Layer B 供给 / admission | `layer_b_count`、boundary candidate count | 先查上游供给，再查 admission |
| boundary 候选几乎为 0 | admission | `filtered_reason_counts` | 先看哪条 floor 卡得最多 |
| 很多样本是 `rejected` | 正式评分 | gap to near-miss、主负贡献 | 先判定 threshold 还是 penalty |
| 很多样本是 `blocked` | structural conflict | blockers、gate status | 先做 structural review，不先降阈值 |
| 某个 ticker 总差一点 | focused ticker frontier | focused score diagnostics | 看最小 rescue row |
| selected 增多但次日变差 | execution / 质量劣化 | next-day outcomes | 回滚本轮变体，重新评估 admission |
| replay 变好但 live 没变好 | 验证错位 | live report、next-day outcomes | 以 live 结果为准 |

---

## 4. 12 个最常见故障场景

### 场景 1：`layer_b_count` 很低

why：BTST 没有供给，后面调什么都像救火。

先查：

1. Layer B 冷不冷
2. neutral mean reversion 语义
3. heavy score 覆盖够不够

先做什么：

1. 回到 Layer B 调参，不先改 BTST threshold。

### 场景 2：`short_trade_boundary candidate_count` 很低

why：通常是 admission 过严，不一定是正式目标太严。

先查：

1. `filtered_reason_counts`
2. 哪条 floor 杀得最多

先做什么：

1. admission 变体优先，不先动 target profile。

### 场景 3：大量 `rejected_short_trade_boundary_score_fail`

why：说明 admission 通过后，正式评分仍压死了大批样本。

先查：

1. 是否普遍离 near-miss 超过 `0.06`
2. 主负贡献集中在哪里

先做什么：

1. 如果远离 near-miss，先做 penalty / score construction 审查。
2. 如果有贴线样本，先做 frontier rescue。

### 场景 4：`blocked` 样本很多

why：通常是结构冲突，不是热度不够。

先查：

1. `layer_c_bearish_conflict`
2. `trend_not_constructive`
3. stale / overhead / extension block

先做什么：

1. structural variant 或 case-based review。

### 场景 5：只有个别 ticker 被低成本救回

why：说明不适合做 cluster-wide 放松。

先查：

1. minimal adjustment cost
2. 其他样本是否根本没有 rescue row

先做什么：

1. case-based 实验，不做全局改动。

### 场景 6：candidate entry 看起来过宽

why：有些票根本不该进入 BTST replay 候选池。

先查：

1. `candidate_source`
2. `candidate_reason_codes`
3. focus ticker 的结构指标

先做什么：

1. candidate entry metric grid 或 semantic frontier。

### 场景 7：`300502` 一类样本一直救不回来

why：这往往不是 penalty 微调问题，而是入口语义不匹配。

先查：

1. `breakout_freshness`
2. `volume_expansion_quality`
3. `trend_acceleration`
4. `close_strength`

先做什么：

1. 优先 candidate entry 路线，不继续走 penalty 路线。

### 场景 8：`300394` 一类样本 penalty 很重但仍有正贡献

why：这类样本更像 penalty 主导问题，而不是入口问题。

先查：

1. `layer_c_avoid_penalty`
2. `stale_trend_repair_penalty`
3. `extension_without_room_penalty`

先做什么：

1. penalty frontier，必要时再加 threshold。

### 场景 9：replay 里能 near-miss，live 里没改善

why：可能是 replay 输入和真实 post-market 供给不一致。

先查：

1. replay 输入来源
2. 真实 candidate generation 是否真的发生变化

先做什么：

1. 优先信任 live，回查 replay 的适用边界。

### 场景 10：next_high 好看，但 next_close 很差

why：说明弹性可能有，但兑现质量差。

先查：

1. `close_strength`
2. `extension_without_room_penalty`
3. execution 口径

先做什么：

1. 不要只盯 `next_high`，要重新看可兑现性。

### 场景 11：新增候选数上来了，但 watchlist / buy order 没承接

why：说明你优化的可能只是研究层前置供给，不是可执行机会。

先查：

1. `included_in_buy_orders`
2. execution blocker
3. T+1 confirmation

先做什么：

1. 把重点从 BTST 本身转到 execution bridge。

### 场景 12：多窗口表现不稳定

why：说明参数可能在局部过拟合。

先查：

1. 是否只有一个窗口变好
2. 是否靠少数 ticker 支撑结果

先做什么：

1. 扩窗口，不急着升级默认值。

---

## 5. 排障时优先读哪些产物

### 第一优先级

1. `selection_snapshot.json`
2. `selection_target_replay_input.json`
3. `selection_review.md`

### 第二优先级

1. `daily_events.jsonl`
2. `pipeline_timings.jsonl`
3. `session_summary.json`

### 第三优先级

1. score failure 分析
2. frontier 分析
3. next-day outcome 分析

原则：先看原始 artifacts，再看分析脚本产物，不要反过来。

---

## 6. 排障时优先用哪些脚本

| 问题类型 | 脚本 | 目标 |
| --- | --- | --- |
| replay 决策漂移 | `replay_selection_target_calibration.py` | 先看是不是规则漂移 |
| 前置候选质量 | `analyze_pre_layer_short_trade_outcomes.py` | 看次日质量 |
| score fail 主因 | `analyze_short_trade_boundary_score_failures.py` | 看主失败簇 |
| near-miss rescue | `analyze_short_trade_boundary_score_failures_frontier.py` | 找最小成本 rescue |
| blocked 释放优先级 | `analyze_structural_conflict_rescue_window.py` | 看谁值得先救 |
| 定点 blocked 实验 | `analyze_targeted_structural_conflict_release.py` | 做 case-based release |

---

## 7. 最小排障流程

1. 先确定症状属于哪一层。
2. 再找对应 artifacts。
3. 再跑一个最贴近该层的分析脚本。
4. 最后才决定是否需要调参数或改规则。

如果你一上来就改参数，通常会同时失去：

1. 归因能力
2. 可回滚性
3. 对下一轮问题的判断力

---

## 8. 一句话总结

BTST 排障最重要的不是“知道哪些参数能改”，而是先判断问题到底落在哪一层；只有层级判断正确，后续 replay、frontier、live validation 和默认值升级才不会跑偏。
