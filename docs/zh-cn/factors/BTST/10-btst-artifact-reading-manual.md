# BTST 产物判读手册

适用对象：已经跑完 BTST replay、live validation 或真实窗口分析，但不知道应该先看哪个 artifact、每个文件分别回答什么问题的读者。

这份文档解决的问题：把 BTST 当前最关键的 artifact、分析脚本输出和阅读顺序整理成一份判读手册，避免“文件很多，但不知道哪个最重要”。

建议搭配阅读：

1. [03-btst-one-page-cheatsheet.md](./03-btst-one-page-cheatsheet.md)
2. [04-btst-experiment-template.md](./04-btst-experiment-template.md)
3. [07-btst-factor-metric-dictionary.md](./07-btst-factor-metric-dictionary.md)
4. [08-btst-current-window-case-studies.md](./08-btst-current-window-case-studies.md)

---

## 1. 先讲结论：BTST 产物分成 4 层

如果你每次都从 report 目录随机打开文件，阅读效率会很低。当前最稳的顺序是按 4 层看：

1. 总览层：这轮实验或窗口整体发生了什么。
2. 日级快照层：某个 trade_date 里有哪些候选、决策和理由。
3. replay / frontier 层：如果规则变化，会改变哪些样本。
4. 次日表现层：新增样本到底有没有交易价值。

最常见的错误，是直接先看 frontier，却没先知道当前主矛盾到底是 admission、blocked 还是 score-fail。

---

## 2. 总览层先看什么

### 2.1 `session_summary.json`

它回答的问题：

1. 这轮窗口跑了多少天。
2. 当前 report 的产物根目录在哪里。
3. 是否有 selection artifacts、feedback summary、timings 等总览信息。

适合什么时候先看：

1. 你刚拿到一个新 report。
2. 你想先确认这轮运行链路是否完整。

### 2.2 `daily_events.jsonl`

它回答的问题：

1. 每个交易日生成了什么 `current_plan`。
2. 哪些 plan 带有 `selection_artifacts` 元信息。
3. T 日计划和 T+1 执行如何串起来。

适合什么时候先看：

1. 你怀疑日级时序解释不一致。
2. 你想确认计划到底是不是当天生成、次日执行。

### 2.3 `pipeline_timings.jsonl`

它回答的问题：

1. 每个阶段是否真实执行。
2. artifact 是不是写出成功。
3. 某天是否存在链路异常或阶段缺失。

适合什么时候先看：

1. 你怀疑不是规则问题，而是运行链路问题。
2. 你需要先排除工程异常。

---

## 3. 日级快照层先看什么

### 3.1 `selection_snapshot.json`

这是 BTST 日级判读最重要的结构化文件。

它回答的问题：

1. 当天有哪些 watchlist、rejected entries、supplemental short-trade entries。
2. 每个样本的 decision、score、candidate_source 和 explainability 是什么。
3. 是否存在 blocker、buy_order_blocker、reentry_review_until 等执行侧信息。

什么时候先看：

1. 你要复盘某个具体 `trade_date:ticker`。
2. 你要判断样本属于 `selected`、`near_miss`、`blocked` 还是 `rejected`。

### 3.2 `selection_review.md`

它回答的问题：

1. 当前日级样本最值得人工快速阅读的结论是什么。
2. 哪些 top factors、Layer C 共识、blocker 和 research prompts 最值得注意。

什么时候先看：

1. 你想先快速形成一句人类可读结论。
2. 你不打算先钻 JSON 字段细节。

怎么和 snapshot 配合：

1. 先用 `selection_review.md` 快速定位重点 ticker。
2. 再回到 `selection_snapshot.json` 看字段级结构。

### 3.3 `selection_target_replay_input.json`

它回答的问题：

1. 如果重放 short-trade 规则，这一天的高保真输入到底是什么。
2. watchlist、rejected entries、supplemental entries 和原生 `strategy_signals` 是否完整。
3. 这一天是否适合做 replay calibration。

什么时候一定要看：

1. 你要跑 threshold grid、penalty grid、candidate-entry frontier。
2. 你怀疑老源因为缺信号不适合做某类实验。

---

## 4. replay / frontier 层怎么看

### 4.1 `replay_selection_target_calibration.py` 系列产物

这类产物回答的问题：

1. 如果改阈值、改 penalty、改 candidate-entry 规则，会改变谁。
2. 变化是 threshold-only，还是必须联动其他机制。
3. 最小 rescue row 是什么，调整成本多大。

最常见输出包括：

1. threshold grid
2. structural variants
3. combination grid
4. candidate-entry metric grid
5. penalty frontier
6. penalty + threshold frontier

正确读法：

1. 先看哪些 ticker 发生变化。
2. 再看变化后的 decision 和 gap。
3. 最后判断这是单样本特例还是可推广机制。

### 4.2 `analyze_short_trade_blockers.py`

它回答的问题：

1. 当前窗口最大的失败簇是什么。
2. 样本主要死在 `layer_b_boundary`、`short_trade_boundary`、`blocked` 还是 execution。

什么时候先看：

1. 你还没定位主矛盾。
2. 你不想一开始就钻单票分析。

### 4.3 `analyze_short_trade_boundary_score_failures.py` 与 frontier 版本

它回答的问题：

1. admission 已放行的样本，为什么还在 score frontier 被拒。
2. 这些样本里哪些属于 threshold-only 低成本释放。
3. 哪些必须联动 stale / extension 等 penalty。

什么时候先看：

1. 当前失败簇主要是 `rejected_short_trade_boundary_score_fail`。
2. 你已经知道 admission 不是主矛盾。

### 4.4 `analyze_structural_conflict_rescue_window.py` 与 targeted release 产物

它回答的问题：

1. blocked 簇里谁最值得优先 rescue。
2. 这是 cluster-wide 问题，还是个别 case。

什么时候先看：

1. 你的问题主要是 `layer_c_bearish_conflict` 或其他 hard block。
2. 你需要决定“放整簇还是放单票”。

---

## 5. 次日表现层怎么看

### 5.1 `analyze_pre_layer_short_trade_outcomes.py` 产物

它回答的问题：

1. Layer C 之前的补充候选池质量是否真的提高。
2. 新 builder 或 admission 变体是不是只是在放热。

优先看：

1. `next_high_return_mean`
2. `next_close_return_mean`
3. `next_high_hit_rate@threshold`
4. `next_close_positive_rate`

### 5.2 `analyze_short_trade_boundary_coverage_variants.py` 产物

它回答的问题：

1. 如果放松某条 floor，会新增哪些样本。
2. 这些新增样本的次日表现是否仍可接受。

什么时候先看：

1. 你想做 admission 扩覆盖。
2. 你要决定某条 floor 是否能升级默认候选。

---

## 6. 按任务选择 artifact

### 6.1 我只想知道当前主矛盾在哪里

先看：

1. `session_summary.json`
2. `selection_review.md`
3. blocker analysis

### 6.2 我只想复盘一只票为什么没过

先看：

1. `selection_review.md`
2. `selection_snapshot.json`
3. 必要时再看 replay 输入和 frontier 产物

### 6.3 我想决定下一轮调什么

先看：

1. blocker analysis
2. score-fail frontier 或 structural rescue queue
3. 次日表现产物

### 6.4 我想判断变体能不能升级默认

先看：

1. replay 结果是否稳定
2. 真实窗口 quality 指标是否稳定
3. 是否存在无关样本污染

---

## 7. 一张最实用的阅读顺序表

| 你的目标 | 先看什么 | 第二步看什么 |
| -------- | -------- | ------------ |
| 快速知道窗口发生了什么 | `session_summary.json` | `selection_review.md` |
| 复盘单票 | `selection_review.md` | `selection_snapshot.json` |
| 做 replay 调参 | `selection_target_replay_input.json` | frontier 产物 |
| 判断主失败簇 | blocker analysis | 专用 frontier / rescue 分析 |
| 判断 admission 是否成立 | coverage variants | pre-layer outcomes |
| 判断能否升级默认 | replay 一致性 | live quality 指标 |

---

## 8. 一句话总结

BTST 产物最有效的读法，不是从一个 JSON 里挖到底，而是先用总览和 review 定位问题，再用 snapshot 和 replay 输入确认字段，再用 frontier 和次日表现产物决定下一步动作。这样你读的是“问题链路”，不是“文件目录”。
