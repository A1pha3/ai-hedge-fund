# BTST 一页速查卡

适用对象：已经读过 BTST 长文，但在复盘、讨论、排障和实验决策时需要快速抓重点的研究员、开发者和 AI 助手。

---

## 1. 一句话定义

BTST 是一条面向次日短线的规则型目标链路，负责把“明天仍可能有交易弹性”的样本，从 Layer B 供给、边界补充和 Layer C 共识中筛出来，并在 T 日生成计划、T+1 执行验证。

---

## 2. 你只需要先记住的 8 件事

1. BTST 不是最终执行层，也不是单一阈值。
2. BTST 先吃 Layer B 供给，再做 short trade boundary 预选补充。
3. short trade target 才是正式判定 `selected / near_miss / blocked / rejected` 的地方。
4. `blocked` 和 `rejected` 不是一回事，调参方式也不同。
5. 正向因子主要回答“明天还有没有继续强的理由”。
6. penalty 主要回答“这是不是老修复票、末端延伸票或上方压力票”。
7. replay 解决的是规则漂移与可归因，次日结果验证解决的才是策略是否真的更好。
8. 最优参数通常是稳定区间，不是某一天最热的点。

---

## 3. BTST 最小链路速查

```text
Layer A 候选池
  -> Layer B 四策略评分
  -> fast pool / Layer C watchlist
  -> short_trade_boundary 补充候选
  -> short_trade_target 正式评分
  -> selection_targets
  -> T 日 post-market 生成计划
  -> T+1 执行与次日验证
```

---

## 4. 两层关键对象速查

### 4.1 short_trade_boundary

定位：前置 admission 层，只决定“值不值得送进 BTST 正式评估”。

默认 floor：

1. `breakout_freshness >= 0.18`
2. `trend_acceleration >= 0.22`
3. `volume_expansion_quality >= 0.15`
4. `catalyst_freshness >= 0.12`
5. `candidate_score >= 0.24`

默认边界参数：

1. `score_buffer = 0.08`
2. `max_candidates = 6`

### 4.2 short_trade_target

定位：正式目标评估层，决定次日短线结论与 explainability。

默认 profile：

1. `select_threshold = 0.58`
2. `near_miss_threshold = 0.46`
3. `stale_penalty_block_threshold = 0.72`
4. `overhead_penalty_block_threshold = 0.68`
5. `extension_penalty_block_threshold = 0.74`
6. `layer_c_avoid_penalty = 0.12`

---

## 5. 正向因子速查

| 因子 | 它在回答什么 | 当前作用强度 |
| --- | --- | --- |
| `breakout_freshness` | 这是不是刚启动，而不是老票延续 | 很高 |
| `trend_acceleration` | 趋势是不是刚在增强 | 很高 |
| `volume_expansion_quality` | 放量是不是支持继续上攻 | 高 |
| `close_strength` | 当日收盘是不是足够强 | 中高 |
| `sector_resonance` | 个股是不是得到板块和 cohort 共振支持 | 中 |
| `catalyst_freshness` | 催化是不是还新鲜可交易 | 中 |
| `layer_c_alignment` | 研究层是否提供辅助共识 | 中 |

---

## 6. penalty 速查

| penalty | 它在打击什么 | 当前常见含义 |
| --- | --- | --- |
| `stale_trend_repair_penalty` | 老趋势修复、均值回归反抽 | “不是新启动” |
| `overhead_supply_penalty` | 上方抛压或强烈 bearish 冲突 | “有明显压制” |
| `extension_without_room_penalty` | 趋势已延伸但上方空间有限 | “太晚了” |
| `layer_c_avoid_penalty` | 研究层明确 `avoid` | “研究层强烈不背书” |

---

## 7. 总分公式速查

```text
score_target =
  0.22 * breakout_freshness
  + 0.18 * trend_acceleration
  + 0.16 * volume_expansion_quality
  + 0.14 * close_strength
  + 0.12 * sector_resonance
  + 0.08 * catalyst_freshness
  + 0.10 * layer_c_alignment
  - 0.12 * stale_trend_repair_penalty
  - 0.10 * overhead_supply_penalty
  - 0.08 * extension_without_room_penalty
  - layer_c_avoid_penalty
```

最重要的理解：

1. 正向项决定“有没有继续强的理由”。
2. penalty 决定“即使看起来强，这票是不是其实不该追”。

---

## 8. 决策标签速查

| 标签 | 意义 | 常见下一步 |
| --- | --- | --- |
| `selected` | 规则上已具备次日短线资格 | 继续看 execution bridge 与 T+1 承接 |
| `near_miss` | 已很接近，值得重点审查 | 优先做 frontier 诊断 |
| `blocked` | 结构或数据层直接阻断 | 优先看 structural / penalty，不先降阈值 |
| `rejected` | 结构未必完全错误，但当前还不够 | 看是 threshold 问题还是 score construction 问题 |

---

## 9. 最常见的 6 个错误动作

1. 候选少，就先降 `select_threshold`。
2. `blocked` 多，就直接当成 near-miss 去救。
3. admission 和正式评分一起放松。
4. 只看 `selected` 数量，不看次日表现。
5. 只看 replay 提升，不看真实窗口 live validation。
6. 把 `layer_c_bearish_conflict` 当作统一全局放松对象。

---

## 10. 脚本速查

| 脚本 | 用途 | 什么时候用 |
| --- | --- | --- |
| `scripts/replay_selection_target_calibration.py` | replay 校准总入口 | 每次改规则前后都先跑 |
| `scripts/analyze_pre_layer_short_trade_outcomes.py` | 看前置候选的次日表现 | 判断候选质量是否真的变好 |
| `scripts/analyze_short_trade_boundary_score_failures.py` | 看 score-fail 簇主因 | admission 已过但大量 rejected 时 |
| `scripts/analyze_short_trade_boundary_score_failures_frontier.py` | 找最小 rescue row | 确认存在贴线样本时 |
| `scripts/run_short_trade_boundary_variant_validation.py` | 跑真实窗口变体 | replay 之后做 live 验证 |

---

## 11. 最小调参顺序

1. 先分型：供给、admission、score frontier、structural conflict、execution 承接。
2. 每次只动一类机制。
3. 先做 replay。
4. 再做真实窗口验证。
5. 最后才考虑升级默认值。

---

## 12. 一句话结论模板

如果你要快速写一句复盘结论，推荐用这个模板：

“该样本当前属于 `selected / near_miss / blocked / rejected`，主正贡献来自 `X / Y`，主负贡献来自 `A / B`；因此下一步更像是 `admission / threshold / penalty / structural conflict / execution` 问题，而不是简单整体降线问题。”
