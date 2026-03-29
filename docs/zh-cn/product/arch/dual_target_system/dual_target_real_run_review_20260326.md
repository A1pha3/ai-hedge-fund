# 2026-03-26 双目标真实运行复盘与优化建议

## 1. 目标与运行方式

本次复盘的目标是用真实 2026-03-26 A 股数据，实际跑出双目标结果，并判断当前实现是否已经能同时支持：

1. 长期研究目标 research
2. 次日买入目标 short trade

本次真实运行命令：

```bash
/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-03-26 \
  --end-date 2026-03-26 \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --selection-target dual_target \
  --output-dir data/reports/paper_trading_20260326_20260326_live_m2_7_dual_target_20260328
```

核心产物：

1. [docs/zh-cn/product/arch/dual_target_system/dual_target_real_run_review_20260326.md](docs/zh-cn/product/arch/dual_target_system/dual_target_real_run_review_20260326.md)
2. 本地验证输出目录：`data/reports/paper_trading_20260326_20260326_live_m2_7_dual_target_20260328`
3. 本文中的统计结论来自该目录下的 `session_summary.json`、`selection_snapshot.json` 与 `selection_review.md`
4. 这些运行产物仅作为本地验证证据，不纳入 git

## 2. 真实运行结果

### 2.1 产物完整性

本次运行已经不是占位状态，而是完整真实产物：

1. `session_summary.plan_generation.selection_target = dual_target`
2. `selection_snapshot.target_mode = dual_target`
3. `dual_target_summary.target_mode_counts.dual_target = 1`
4. `selection_targets`、`target_summary`、`short_trade_view`、`dual_target_delta` 均已落盘

### 2.2 双目标结果摘要

根据本地验证输出目录中的 `session_summary.json`：

1. `selection_target_count = 3`
2. `research_target_count = 3`
3. `short_trade_target_count = 3`
4. `research_selected_count = 1`
5. `short_trade_selected_count = 0`
6. `short_trade_blocked_count = 2`
7. `short_trade_rejected_count = 1`

### 2.3 个股层结论

根据本地验证输出目录中的 `selection_review.md`：

1. `300724`
   research: `selected`
   short trade: `rejected`
   delta: `research_pass_short_reject`

2. `300394`
   research: `rejected`
   short trade: `blocked`
   delta: `both_reject_but_reason_diverge`

3. `300502`
   research: `rejected`
   short trade: `blocked`
   delta: `both_reject_but_reason_diverge`

结论非常明确：

1. 长期研究目标已经可以真实跑出结果
2. 次日买入目标也已经真实计算出来
3. 但 2026-03-26 当天次日买入目标为空

这说明当前系统已经具备双目标运行能力，但 short trade 目标的候选进入方式和阻断逻辑仍然过强，导致真实日上没有产出可执行候选。

## 3. 主要问题判断

### 3.1 问题一：short trade 目标仍然复用 research 漏斗入口，覆盖面太窄

当前 `selection_targets` 的构造入口在 [src/execution/daily_pipeline.py](src/execution/daily_pipeline.py) 中，只把：

1. `watchlist`
2. `watchlist_filter_diagnostics.tickers`

传给 [src/targets/router.py](src/targets/router.py) 的 `build_selection_targets(...)`。

这意味着 short trade 目标并没有独立候选池，而是只能评估已经进入 research 高池或 watchlist 语境的股票。

本次真实运行里：

1. 200 只候选股只剩 3 只进入双目标评估
2. 例如 `000960`、`002463`、`600989`、`600938` 这些接近阈值的 Layer B 名字，根本没有进入 short trade 目标层

这与双目标设计初衷不一致。次日买入目标不应完全依赖 research 的先验漏斗，否则它不会产生独立增量。

### 3.2 问题二：short trade 对 Layer C bearish 冲突是硬阻断，而不是软惩罚

在 [src/targets/short_trade_target.py](src/targets/short_trade_target.py) 中，存在如下结构性阻断：

1. `input_data.bc_conflict in STRONG_BEARISH_CONFLICTS`
2. `input_data.layer_c_decision == "avoid"`

一旦满足，就直接追加 `layer_c_bearish_conflict` blocker，并把 `gate_status.structural = fail`。

这会导致：

1. `300394` 虽然 short trade `score_target = 0.2889`，仍然直接 `blocked`
2. `300502` 虽然被真实评估，仍然因为同样的机制直接 `blocked`

问题不在于 bearish 信息不该用，而在于当前实现把它变成了“绝对否决票”。

如果 short trade 目标的设计是 T+1 短周期，那么它应允许与中期 research 判断出现可解释分歧，而不是只要 research 风格的 Layer C 给出 `avoid`，就彻底失去 short trade 独立性。

### 3.3 问题三：short trade 阈值与惩罚组合偏硬，导致真实日容易空集

在 [src/targets/short_trade_target.py](src/targets/short_trade_target.py) 中：

1. `SELECT_THRESHOLD = 0.58`
2. `NEAR_MISS_THRESHOLD = 0.46`

而本次最强的 short trade 候选 `300724`：

1. `trend_acceleration = 0.65`
2. `close_strength = 0.9454`
3. `execution_bridge_ready = true`
4. 但 `score_target = 0.3835`
5. 最终仍然只是 `rejected`

这说明当前权重和阈值组合下，系统对以下维度依赖过重：

1. `catalyst_freshness`
2. `sector_resonance`
3. `stale_trend_repair_penalty`
4. `extension_without_room_penalty`

结果是即便研究目标已经通过、执行桥也可下单，short trade 仍可能完全空集。

如果真实日连续出现这种情况，说明 short trade 首版规则更像“极高标准的理论候选筛查”，而不是“可落地的 T+1 候选生成器”。

### 3.4 问题四：真实运行对比存在方法学噪声，不能直接拿历史 live 报告当严格基线

已有的历史报告 [data/reports/paper_trading_window_20260323_20260326_live_m2_7_20260326/selection_artifacts/2026-03-26/selection_snapshot.json](data/reports/paper_trading_window_20260323_20260326_live_m2_7_20260326/selection_artifacts/2026-03-26/selection_snapshot.json) 是 research_only 语义下的 live 运行，但它与本次 dual_target 运行并不是同一个受控实验：

1. 组合持仓状态不同
2. LLM 实时输出存在波动
3. 单日运行与窗口运行的前置状态不同

因此，这份历史 live 报告只能做现象参考，不能做精确阈值校准基线。

后续若要严谨优化 short trade 规则，必须优先使用 frozen current_plan replay 做对照实验。

### 3.5 问题五：单日 3 个高池候选耗时接近 10 分钟，调参反馈回路过慢

本次单日运行总耗时约 `599s`，其中：

1. `score_batch ≈ 244s`
2. `fast_agent ≈ 354s`
3. `total_post_market ≈ 598s`

这对“调一个 short trade 阈值再复跑”的研发节奏过慢。

这不是本次选股空集的直接根因，但会显著拖慢优化迭代。

## 4. 优化建议

### 4.1 P0：让 short trade 拥有独立候选入口

建议优先级最高。

建议改造：

1. short trade 候选不再只来自 `watchlist + watchlist rejected`
2. 至少扩展到 `high_pool top N`
3. 更理想的是显式拆出 `short_trade_candidate_pool`

这样做的原因：

1. 可以让 short trade 对 `000960`、`002463`、`600989`、`600938` 这类接近 Layer B 阈值的名字给出独立判断
2. 可以真正回答“次日买入目标与长期研究目标差在哪”
3. 可以减少 dual_target 结果退化成“research 结果加一个附属 verdict”

### 4.2 P0：把 Layer C bearish 冲突从硬阻断改成分级惩罚

建议改造：

1. 不要只要 `layer_c_decision == avoid` 就直接 `blocked`
2. 改成基于 `score_c`、`bc_conflict` 强弱、负向 agent 密度的分级惩罚
3. 只有在 `score_c` 极低或明确出现强负面结构时才硬阻断

最小可行版本：

1. 保留 `bc_conflict in STRONG_BEARISH_CONFLICTS` 的惩罚
2. 去掉 `layer_c_decision == avoid` 的直接 blocker
3. 将其转成 `overhead_supply_penalty` 或新增 `bearish_conflict_penalty`

这样能保证 short trade 仍尊重 Layer C，但不会完全失去独立性。

### 4.3 P1：重新校准 short trade 阈值与权重

建议先做参数层调优，而不是立刻重写规则。

优先实验方向：

1. `SELECT_THRESHOLD`: `0.58 -> 0.50`
2. `NEAR_MISS_THRESHOLD`: `0.46 -> 0.38` 或 `0.40`
3. 下调 `stale_trend_repair_penalty`、`extension_without_room_penalty` 的扣分系数
4. 上调 `close_strength`、`trend_acceleration` 的正向贡献

理由：

1. `300724` 在研究目标已选中、执行桥已通过、趋势加速明显的情况下，short trade 仍只有 `0.3835`
2. 这说明当前阈值与得分分布不匹配
3. 即使不直接放行，也至少应该更容易进入 `near_miss`，便于研究员复核

### 4.4 P1：补充 short trade 分布可观测性

建议新增以下 artifact 字段：

1. 当日 short trade `score_target` 排名分布
2. 每个 candidate 的 `candidate_source`
3. `blocked` 与 `rejected` 的分桶计数
4. 阈值命中前后 5 个样本的边界清单

这样下一轮不会只看到“今天是 0 个”，而不知道是：

1. 都被入口漏掉了
2. 都被 Layer C 硬阻断了
3. 还是都卡在 0.40 左右的阈值附近

### 4.5 P2：用 frozen replay 做短迭代验证，而不是继续 live 对比

建议后续所有 short trade 调参都用 frozen replay：

1. 冻结 2026-03-26 当前 `current_plan`
2. 用同一输入批量测试阈值和 gate 变体
3. 再扩展到 `20260323-20260326` 窗口验证稳定性

这样可以隔离：

1. LLM 波动
2. 组合状态差异
3. 数据实时变化

## 5. 推荐执行顺序

下一轮优化建议按下面顺序做，避免一次改太多：

1. 先放开 short trade candidate 入口到 `high_pool top N`
2. 再把 `layer_c_decision == avoid` 从硬阻断改成软惩罚
3. 最后再做 `SELECT_THRESHOLD` 和 `NEAR_MISS_THRESHOLD` 标定

原因：

1. 如果入口不改，short trade 永远看不到足够候选
2. 如果 blocker 不改，short trade 仍会被 research 逻辑强绑定
3. 在入口和 gate 都不合理时先调阈值，容易得到错误结论

## 6. 2026-03-28 跟进实现与受控验证

### 6.1 已完成实现

围绕上面的 P0 建议，当前代码已经补上三项基础设施改动：

1. 在 [src/execution/daily_pipeline.py](src/execution/daily_pipeline.py) 新增 `short_trade_candidates` 诊断与 supplemental 入口
2. 在 [src/targets/router.py](src/targets/router.py) 允许 `supplemental_short_trade_entries` 生成 research 为空、short trade 独立存在的目标条目
3. 在 [src/targets/short_trade_target.py](src/targets/short_trade_target.py) 中，把 `layer_c_decision == avoid` 从直接 `blocked` 改成惩罚项，仍保留 `STRONG_BEARISH_CONFLICTS` 的硬阻断
4. 在 [src/research/artifacts.py](src/research/artifacts.py) 中把 `candidate_source` 与 `candidate_reason_codes` 写入 `target_context`

这意味着 short trade 不再只能消费已经进入 research 漏斗的 Layer C 结果，它现在还可以接收靠近 fast threshold 的 Layer B 边界候选。

### 6.2 回归验证

本轮直接补了三类回归：

1. [tests/targets/test_target_models.py](tests/targets/test_target_models.py)：覆盖边界候选进入 short trade、`avoid` 软阻断、候选来源字段
2. [tests/research/test_selection_artifact_writer.py](tests/research/test_selection_artifact_writer.py)：覆盖 `candidate_source` 已写入 snapshot
3. [tests/execution/test_phase4_execution.py](tests/execution/test_phase4_execution.py)：覆盖 daily pipeline 会把边界候选注入 `selection_targets`

本地结果：

1. `pytest tests/targets/test_target_models.py tests/research/test_selection_artifact_writer.py -q` 通过
2. `env LLM_DEFAULT_MODEL_PROVIDER=OpenAI LLM_DEFAULT_MODEL_NAME=gpt-4.1 pytest tests/execution/test_phase4_execution.py::test_run_post_market_emits_structured_funnel_diagnostics tests/execution/test_phase4_execution.py::test_run_post_market_adds_boundary_short_trade_candidates_to_selection_targets -q` 通过

### 6.3 受控 frozen replay 样本

为了避免 live 噪声，本轮增加了一个小窗口 dual-target frozen replay：

```bash
/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.venv/bin/python scripts/run_paper_trading.py \
   --start-date 2026-03-10 \
   --end-date 2026-03-13 \
   --frozen-plan-source data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319/daily_events.jsonl \
   --model-provider MiniMax \
   --model-name MiniMax-M2.7 \
   --selection-target dual_target \
   --output-dir data/reports/paper_trading_window_20260310_20260313_w1_frozen_replay_m2_7_dual_target_20260328
```

核心产物：

1. 本地验证输出目录：`data/reports/paper_trading_window_20260310_20260313_w1_frozen_replay_m2_7_dual_target_20260328`
2. 本文中的样本统计来自该目录下的 `session_summary.json` 与 `selection_snapshot.json`

样本结果：

1. `days_with_selection_targets = 3`
2. `selection_target_count = 6`
3. `research_selected_count = 2`
4. `short_trade_selected_count = 0`
5. `short_trade_blocked_count = 6`

随后又补了一个 blocker 分布分析脚本，对该 replay 目录逐日统计 short trade 决策、blocker、负标签、候选来源与信号可用性：

1. 分析脚本：[scripts/analyze_short_trade_blockers.py](scripts/analyze_short_trade_blockers.py)
2. 分析产物：`data/reports/paper_trading_window_20260310_20260313_w1_frozen_replay_m2_7_dual_target_20260328/short_trade_blocker_analysis.json`
3. Markdown 摘要：`data/reports/paper_trading_window_20260310_20260313_w1_frozen_replay_m2_7_dual_target_20260328/short_trade_blocker_analysis.md`

分布结果：

1. `missing_trend_signal = 6`
2. `trend_not_constructive = 6`
3. `layer_c_bearish_conflict = 4`
4. `event_signal_incomplete = 6`
5. `score_target.max = 0.0787`
6. `available_strategy_signals = []` 在 6/6 个 short trade 样本中出现

这组结果把问题进一步收窄了：当前 4 日 frozen replay 样本里的 short trade 全 blocked，并不主要说明阈值还不够低，而是说明 replay 输入本身缺少 short trade 所需的 `trend` 与 `event_sentiment` 信号。

根因链路已经确认：

1. [src/paper_trading/frozen_replay.py](src/paper_trading/frozen_replay.py) 只是把历史 `daily_events.jsonl` 中的 `current_plan` 原样反序列化成 [src/execution/models.py](src/execution/models.py)
2. short trade 评分器在 [src/targets/short_trade_target.py](src/targets/short_trade_target.py) 只从 `item.strategy_signals` 读取 `trend`、`event_sentiment`、`mean_reversion`
3. 本次 frozen plan source 中保留下来的 `current_plan.watchlist` 主要包含 Layer C agent 信号与 legacy plan 字段，并没有这些 strategy signals

为了解掉这个约束，当前代码已新增伴随 `selection_artifacts` 同步落盘的高保真 replay input：

1. 文件名：`selection_target_replay_input.json`
2. 写出位置：每个 `selection_artifacts/<trade_date>/` 目录下
3. 写出来源：[src/research/artifacts.py](src/research/artifacts.py)
4. 内容用途：保留 `watchlist`、`rejected_entries`、`supplemental_short_trade_entries`、`buy_order_tickers` 以及完整 `strategy_signals`，用于后续做 short trade 规则校准或重建 `selection_targets`

这意味着后续不必继续依赖历史 `current_plan` 的字段完整性，新的 live / replay 运行结果会天然附带一份更适合 short trade 标定的 replay 输入。

围绕这份新 artifact，当前还新增了 replay 校准脚本 [scripts/replay_selection_target_calibration.py](scripts/replay_selection_target_calibration.py)，用于把 `selection_target_replay_input.json` 直接重放回 [src/targets/router.py](src/targets/router.py) 的 `build_selection_targets(...)`，并检查 stored short trade decision 与 replayed short trade decision 是否一致。

基于 2026-03-26 的新 live dual-target 样本 `data/reports/paper_trading_20260326_20260326_live_m2_7_dual_target_replay_input_validation_20260328` 已完成首轮真实校准基线验证：

1. `selection_target_replay_input.json` 已真实写出
2. 基线 replay 结果 `decision_mismatch_count = 0`
3. stored short trade 决策与 replayed short trade 决策完全一致：`rejected=7`、`blocked=2`
4. `signal_availability = {"has_any": 7}`，说明这个样本已不再受“strategy_signals 全缺失”的历史 replay 契约问题影响

这一步的意义不是说明当前 short trade 已经足够好，而是说明后续阈值/规则实验终于可以建立在可信的高保真输入上，而不是继续混用缺信号的旧 `current_plan` 回放样本。

在这个高保真样本上，当前还进一步跑了一轮阈值网格扫描：

1. 产物：`selection_target_threshold_grid.json` 与 `selection_target_threshold_grid.md`
2. 扫描区间：`select_threshold = [0.58, 0.52, 0.46, 0.40, 0.36]`，`near_miss_threshold = [0.46, 0.40, 0.36, 0.30, 0.24]`
3. 第一组能让 short trade 出现 near-miss 的组合是 `select=0.58, near_miss=0.36`
4. 第一组能让 short trade 出现 selected 的组合是 `select=0.36, near_miss=0.36`
5. 两组组合里被最先推动出来的 ticker 都是 `300724`

这说明至少在 2026-03-26 这个样本上，阈值调节的第一受益者是边界研究样本 `300724`，而不是当前那两个已进入 structural fail 的 blocked 候选。

同一份 fresh 高保真样本的 blocker 分析也已经补齐：

1. `short_trade_target_count = 9`
2. `short_trade_decision_counts = {rejected: 7, blocked: 2}`
3. `blocker_counts = {layer_c_bearish_conflict: 2}`
4. `signal_availability = {has_any: 9, missing_all: 0}`
5. `gate_status_counts.structural = {pass: 7, fail: 2}`

对应的两个 blocked ticker 分别是 `300394` 与 `300502`，二者都不是因为缺 signal 或阈值稍高而失败，而是因为：

1. `bc_conflict = b_positive_c_strong_bearish`
2. `layer_c_decision = avoid`
3. `overhead_supply_penalty` 与 `stale_trend_repair_penalty` 偏高

因此下一轮 short trade 优化的优先级已经清楚分层：

1. 如果目标是先让系统出现更多可复核 short trade 样本，应先围绕 `300724` 这类边界 research ticker 做温和阈值实验
2. 如果目标是解除 `300394`、`300502` 这类 blocked 样本，则需要进入结构性 gate 设计，而不是继续只调阈值

围绕第二条路径，当前还补了一轮 structural variant 实验，直接基于高保真 replay input 重放 short trade 规则，而不是去改 live 默认值盲试：

1. 产物：`selection_target_structural_variants.json` 与 `selection_target_structural_variants.md`
2. 变体集合：`baseline`、`no_bearish_conflict_block`、`half_avoid_penalty`、`relaxed_penalty_thresholds`、`no_bearish_conflict_half_avoid`、`no_bearish_conflict_relaxed_penalties`
3. 当前基线阈值保持不变：`select_threshold=0.58`、`near_miss_threshold=0.46`

结果很明确：

1. `half_avoid_penalty` 没有释放任何 blocked 样本
2. `relaxed_penalty_thresholds` 也没有释放任何 blocked 样本
3. 只有关闭 `b_positive_c_strong_bearish` hard block 的变体会产生变化
4. 但这种变化只是把 `300394`、`300502` 从 `blocked` 降为 `rejected`，并没有把它们推到 `near_miss` 或 `selected`

这意味着：

1. `layer_c_bearish_conflict` 的 hard block 确实是 blocked 状态的直接来源
2. 但它不是这两个样本的唯一问题，因为一旦移除 hard block，它们仍然因为 score_target 太低而停留在 `rejected`
3. 所以下一轮如果要继续做结构性优化，应优先考虑“把 bearish conflict 从 hard block 改成 penalty 后，是否还需要同步提高 score construction 或下调 threshold”，而不是只改一个开关

围绕第 3 条，当前又补了一轮 structural + threshold 联合扫描，直接把“结构放宽”和“阈值联动”放进同一个 replay 工作台里验证：

1. 产物：`selection_target_combination_grid.json` 与 `selection_target_combination_grid.md`
2. 变体集合：`baseline`、`no_bearish_conflict_block`、`no_bearish_conflict_half_avoid`、`no_bearish_conflict_relaxed_penalties`
3. 阈值网格：`select_threshold = [0.58, 0.52, 0.46, 0.40, 0.36]`，`near_miss_threshold = [0.46, 0.40, 0.36]`

结果比上一轮更明确：

1. 第一组释放 blocked 样本的组合仍然只是 `no_bearish_conflict_block @ select=0.58, near_miss=0.46`
2. 在整个联合网格内，`first_row_blocked_to_near_miss = None`，`first_row_blocked_to_selected = None`
3. 即使把 hard block 移除并把阈值放宽到 `select=0.36, near_miss=0.36`，被推进到 `near_miss/selected` 的依旧只有 `300724`
4. `300394`、`300502` 在所有联合组合里都只是 `blocked -> rejected`，没有进一步进入 `near_miss`

为了避免“只看到 rejected，不知道离阈值还有多远”，当前还补了一份定点诊断：

1. 产物：`selection_target_no_bearish_conflict_diagnostics.json` 与 `selection_target_no_bearish_conflict_diagnostics.md`
2. `300394` 在移除 hard block 后的 `replayed_score_target = 0.2133`，距离当前 `near_miss_threshold = 0.46` 仍差 `0.2467`
3. `300502` 在移除 hard block 后的 `replayed_score_target = 0.0`，距离当前 `near_miss_threshold = 0.46` 仍差 `0.46`
4. 二者的 `replayed_rejection_reasons` 都已经从 `layer_c_bearish_conflict` 切换成 `score_short_below_threshold`
5. `300394` 的主导问题转为 `stale_trend_repair_penalty=0.47` 与 `extension_without_room_penalty=0.45`，`300502` 则几乎是全量 score construction 失效，`score_short=0.00`

为了把“score_short_below_threshold”继续拆开，当前还补了一份 ticker 级 score construction 诊断：

1. 产物：`selection_target_score_diagnostics_300394_300502.json` 与 `selection_target_score_diagnostics_300394_300502.md`
2. `300394` 的 replay 后正贡献并不低：`trend_acceleration=0.1325`、`close_strength=0.1319`、`breakout_freshness=0.088`，总正贡献 `0.4281`
3. 但它被 `layer_c_avoid_penalty=0.12`、`stale_trend_repair_penalty=0.0564`、`extension_without_room_penalty=0.036` 持续压低，因此最终 `replayed_score_target` 只剩 `0.2133`
4. `300502` 的问题更深：总正贡献只有 `0.1919`，低于总负贡献 `0.2254`，其中 `breakout_freshness=0.0`、`volume_expansion_quality=0.0`、`catalyst_freshness=0.0`
5. 这说明 `300502` 不是一个“只差去掉 hard block 或降低 penalty”的边界样本，而是连 short trade 所需的 breakout 语义都没有被打出来

因此，当前对两个 blocked 样本的改造建议已经可以进一步分流：

1. `300394` 可以继续测试“削弱 avoid penalty / stale_trend_repair_penalty / extension_without_room_penalty”这一类 score construction 调整
2. `300502` 更应该回到 candidate entry 与短线 breakout 语义本身，检查它为什么会进入 short trade replay 候选但几乎没有正向 breakout 贡献

围绕第 1 条，当前还补了一轮真实 penalty weight 结构变体验证：

1. 产物：`selection_target_penalty_weight_variants.json` 与 `selection_target_penalty_weight_variants.md`
2. 对比变体：`no_bearish_conflict_block` vs `no_bearish_conflict_softer_penalty_weights`
3. `no_bearish_conflict_softer_penalty_weights` 同时把 `layer_c_avoid_penalty` 从 `0.12` 降到 `0.06`，并把 `stale/overhead/extension` 的 score 权重从 `0.12/0.10/0.08` 降到 `0.06/0.05/0.04`

结果很关键：

1. 两个样本都仍然没有进入 `near_miss`，所以这不是“一调权重就解决”的问题
2. 但 `300394` 的 `replayed_score_target` 从 `0.2133` 明显抬升到 `0.3207`
3. 它的总负贡献从 `0.2148` 降到 `0.1074`，而总正贡献保持 `0.4281` 不变，说明 penalty 权重确实是它的主矛盾之一
4. `300502` 只从 `0.0` 抬升到 `0.0792`，总负贡献从 `0.2254` 降到 `0.1127`，但总正贡献仍只有 `0.1919`
5. 这说明即便把 penalty 明显放松，`300502` 依然缺少足够的 breakout / volume / catalyst 正向结构

所以，下一轮优先级可以进一步收紧为：

1. `300394` 值得继续沿着 penalty weight 和 score construction 做第二轮实验，例如只对 avoid penalty 与 stale/extension 分开扫描，观察是否能把它推到 near-miss
2. `300502` 暂时不值得继续做 penalty 微调，应优先回到 candidate entry 和 short-trade 语义校准

围绕这两个方向，当前又补了一轮更细的真实拆分实验与 candidate entry 定点诊断：

1. 产物：`selection_target_penalty_split_variants.json`、`selection_target_penalty_split_variants.md`、`selection_target_candidate_entry_focus.json`、`selection_target_candidate_entry_focus.md`
2. `300394` 与 `300502` 的 focused diagnostics 已直接暴露 `candidate_source` 与 `candidate_reason_codes`，两者都不是来自 `layer_c_watchlist`，而是来自 `watchlist_filter_diagnostics`，原因码均为 `decision_avoid` 与 `score_final_below_watchlist_threshold`
3. 这说明 `300502` 的问题已经不只是“为什么移除 hard block 后仍没有分数”，还包括“为什么一个 Layer C avoid 且 score_final 不达 watchlist 线的样本会继续进入 short-trade replay 候选”

拆分 penalty 实验的结果也已经足够清楚：

1. `300394` 在 `no_bearish_conflict_block` 下的基线分数是 `0.2133`
2. 只降低 `layer_c_avoid_penalty` 到 `0.06` 后，`300394` 升到 `0.2733`，gap_to_near_miss 收窄到 `0.1867`，是单项收益最大的调节杆
3. 只降低 `stale_score_penalty_weight` 到 `0.06` 后，`300394` 升到 `0.2415`，只降低 `extension_score_penalty_weight` 到 `0.04` 后，升到 `0.2313`
4. 组合变体 `no_bearish_conflict_lower_avoid_plus_stale` 可把 `300394` 推到 `0.3015`，`no_bearish_conflict_penalty_triplet_relief` 可到 `0.3195`，与更激进的 `no_bearish_conflict_softer_penalty_weights=0.3207` 基本同量级
5. `300502` 在同一组拆分实验下只从 `0.0` 抬到 `0.0265`、`0.0595`、`0.0775` 这一级别，始终远低于 `near_miss=0.46`

因此，当前最稳妥的工程结论可以进一步收紧为：

1. `300394` 的 penalty 重构顺序应优先看 `layer_c_avoid_penalty`，其次 `stale_trend_repair_penalty`，最后 `extension_without_room_penalty`
2. `300502` 不应继续当作 penalty 调参样本，而应优先审查 `watchlist_filter_diagnostics -> short trade replay candidate` 这条入口是否过宽，尤其是 `decision_avoid` + `score_final_below_watchlist_threshold` 这一类边界样本是否应继续进入 short-trade 评估

围绕第 1 条，当前又补了一轮系统化 penalty frontier 与最小 rescue 搜索：

1. 新产物：`selection_target_penalty_frontier_grid_300394_300502.json` / `.md`、`selection_target_extreme_penalty_combination_grid.json` / `.md`、`selection_target_penalty_threshold_frontier_300394_300502.json` / `.md`
2. penalty frontier 先证明：在 `no_bearish_conflict_block` 下，即便把 `layer_c_avoid_penalty` 压到 `0.02`、`stale_score_penalty_weight` 压到 `0.02`、`extension_score_penalty_weight` 压到 `0.00`，`300394` 的最高 `replayed_score_target` 也只有 `0.3963`，距离 `near_miss=0.46` 仍差 `0.0637`
3. 同一最强 penalty relief 下，`300502` 最高也只有 `0.1575`，距离 near-miss 仍差 `0.3025`
4. 这说明 `300394` 虽然确定是 penalty 主导样本，但“只放松 penalty”仍不足以把它自然推进 near-miss；`300502` 更不可能走这条路径
5. 继续叠加 threshold 联动后，`300394` 的最早 `blocked -> near_miss` 发生在 `layer_c_avoid_penalty=0.02`、`stale_score_penalty_weight=0.02`、`extension_score_penalty_weight=0.08`、`near_miss_threshold=0.36`、`select_threshold` 保持 `0.58` 的组合，总 adjustment_cost=`0.30`
6. `300394` 的最早 `blocked -> selected` 则需要 `layer_c_avoid_penalty=0.02`、`stale_score_penalty_weight=0.02`、`extension_score_penalty_weight=0.02`、`select_threshold=0.38`、`near_miss_threshold=0.38`，总 adjustment_cost=`0.54`
7. `300502` 在同一 penalty+threshold 搜索空间里没有任何 near-miss/selected rescue row

所以，这一轮之后，围绕 `300394/300502` 的分工可以进一步明确成：

1. `300394` 已经不是“再多给几个 penalty 变体看看”的问题，而是需要 penalty relief 与 threshold 联动，或者直接回到 score construction 级重构
2. `300502` 依旧不值得沿 penalty/threshold 路线投入，应继续留在 candidate entry / breakout 语义路径

围绕第 2 条，当前又补了一轮真实 candidate entry 过滤实验：

1. 产物：`selection_target_candidate_entry_filter_variants.json` 与 `selection_target_candidate_entry_filter_variants.md`
2. 该 replay 变体会直接排除 `watchlist_filter_diagnostics` 中同时满足 `decision_avoid` 与 `score_final_below_watchlist_threshold` 的 entry
3. 在真实 `2026-03-26` 样本上，这条规则确实命中了 `300394` 与 `300502`，把它们从 replay 结果中直接移除，表现为 `blocked -> none`
4. 过滤后汇总从 `rejected=7, blocked=2` 变成 `rejected=7, none=2`；即便叠加 `no_bearish_conflict`，结果也仍然是这两个 ticker 被直接消除，而不是进入新的 score 竞争

这一步带来的结论很明确：

1. candidate entry 收紧方向本身是有效的，至少已经证明 `300502` 这类样本不需要继续靠 penalty 微调来“修救”
2. 但当前规则粒度过粗，因为它会把 `300394` 一起过滤掉
3. 所以下一轮入口规则不应直接采用“排除所有 avoid + 低分边界样本”，而应继续叠加 breakout / volume / catalyst 等正向结构条件，只过滤像 `300502` 这样几乎没有 short-trade 正向结构的 entry，尽量保留 `300394` 这类仍值得做 penalty/score construction 研究的样本

围绕第 3 条，当前已经补完一轮选择性弱结构过滤验证：

1. 产物：`selection_target_candidate_entry_selective_filter_variants.json` 与 `selection_target_candidate_entry_selective_filter_variants.md`
2. 新规则仍以 `watchlist_filter_diagnostics + decision_avoid + score_final_below_watchlist_threshold` 为入口，但额外要求 `breakout_freshness <= 0.05`、`volume_expansion_quality <= 0.05`、`catalyst_freshness <= 0.05`
3. 真实 `2026-03-26` 样本中，这条规则只命中 `300502`，不会再误伤 `300394`
4. baseline 下汇总从 `rejected=7, blocked=2` 变成 `rejected=7, blocked=1, none=1`；`300394` 仍保持 `blocked`，`300502` 变成 `none`
5. 叠加 `no_bearish_conflict_block` 后，`300394` 仍会按既有结论进入 `rejected` 并保留 `replayed_score_target=0.2133`，`300502` 则被直接剔除，不再参与后续 score 竞争

这一步把 candidate entry 方向从“只证明需要收紧”推进到了“已经拿到一个能区分 `300394` 与 `300502` 的原型规则”：

1. `300502` 可以开始从 replay-only 原型收紧规则继续外推，优先围绕弱 breakout / 弱 volume / 弱 catalyst 结构去定义更稳健的入口约束
2. `300394` 则应继续留在 penalty / score construction 路径里，避免因为入口规则过粗而提前丢失一个仍有研究价值的样本

围绕这条 replay-only 原型，当前又补了一轮 W1 长窗口方法学校验：

1. 产物：`data/reports/paper_trading_window_20260202_20260313_w1_frozen_replay_m2_7_dual_target_replay_input_validation_20260329/selection_target_candidate_entry_metric_grid_w1.json` 与 `selection_target_candidate_entry_metric_grid_w1.md`
2. 新增能力会对 `breakout_freshness_max`、`volume_expansion_quality_max`、`catalyst_freshness_max` 做 54 行网格扫描，验证弱结构 candidate entry 过滤是否能在更长窗口里稳定命中
3. 首轮 W1 实验先暴露了一个方法学问题：部分 frozen replay entry 缺少原生 `strategy_signals`，导致弱结构指标退化为零，从而把 27 个 blocked entry 误判成“弱结构可过滤”
4. 随后已补上保护逻辑，要求只有在 short-trade `gate_status.data == pass` 时，metric-based candidate entry 过滤才允许生效；对应回归测试也已补齐
5. 保护生效后重新跑完整个 W1 网格，54 行结果全部回到 `filtered={}`、`mismatches=0`、`replayed={'blocked': 50}`，`first_row_filtering_any=None`

围绕 `300502` 的 candidate-entry 路线，当前又补了一轮更贴近“breakout semantic 本身”的正向结构 frontier：

1. 新产物：`selection_target_candidate_entry_semantic_frontier_300502.json` / `.md` 与更细网格版 `selection_target_candidate_entry_semantic_frontier_300502_refined.json` / `.md`
2. `scripts/replay_selection_target_calibration.py` 现已支持在 candidate-entry metric grid 中额外扫描 `trend_acceleration_max` 与 `close_strength_max`，并通过 `focus_tickers` / `preserve_tickers` 直接汇总“过滤 focus ticker 且不误伤 preserve ticker”的最小行
3. 真实 `2026-03-26` 样本上，精细网格给出的最小 preserving row 是 `trend_acceleration <= 0.34` 且 `close_strength <= 0.69`
4. 这条规则会把 `300502` 直接过滤掉，表现为 `blocked -> none`，同时 `300394` 继续保留在 replay 里，不会被误伤
5. 对应的 filtered metrics 也进一步坐实了分流原因：`300502` 的 `trend_acceleration=0.3374`、`close_strength=0.6883`，而 `300394` 仍有 `trend_acceleration=0.7362`、`close_strength=0.942`

所以，到这一步，`300502` 的 candidate-entry 语义已经不再只停留在“弱 breakout / 弱 volume / 弱 catalyst”这一层，而是被进一步压实成：

1. 它既缺少 breakout / volume / catalyst 正向结构
2. 同时连短线趋势确认和收盘强度也停留在明显偏弱的位置
3. 这使得下一轮入口语义设计可以优先围绕 `trend_acceleration + close_strength` 与既有 weak-structure 指标做组合，而不需要再把 `300502` 拉回 penalty/threshold 路线
4. 在 subset frontier 中，最小 preserving row 甚至进一步收缩为单指标：`volume_expansion_quality <= 0.0` 就足以过滤 `300502` 且保留 `300394`

基于这一步，当前又补齐了 `300502` 的 candidate-entry subset frontier：

1. 新产物：`selection_target_candidate_entry_subset_frontier_300502.json` / `.md`
2. `scripts/replay_selection_target_calibration.py` 现已支持在 candidate-entry metric grid CLI 中使用 `none` 省略单个维度，直接搜索最小子集规则
3. 真实 `2026-03-26` 样本显示，真正的最小 preserving row 不是 5 维组合，也不是 `trend_acceleration + close_strength` 联动，而是单独要求 `volume_expansion_quality <= 0.0`
4. 这条规则会把 `300502` 过滤掉，表现为 `blocked -> none`，同时 `300394` 继续保留在 replay 里，不会被误伤
5. 这说明 `300502` 与 `300394` 当前最核心的 candidate-entry 分离面，首先落在“volume expansion quality 是否完全缺失”这一层；`trend_acceleration` 与 `close_strength` 更适合作为后续稳健化时再叠加的辅助条件
6. 增强后的 eligibility 统计还直接显示：整个窗口里共有 27 个 entry 命中了 `watchlist_filter_diagnostics + decision_avoid + score_final_below_watchlist_threshold` 这组入口预条件，但 27 个全部停在 `metric_data_fail_count`，没有任何一个进入弱结构阈值比较

这轮长窗口结果的正确解读不是“candidate entry 收紧方向失效”，而是：

1. 缺信号的 frozen replay 源不应再被误读成弱结构证据，这个方法学陷阱已经被修补掉
2. 当前这批 W1 高保真 replay 输入里，虽然有 27 个 entry 命中了 candidate entry 的入口预条件，但没有任何一个通过 short-trade data gate，因此网格扫描不会进入弱 breakout / 弱 volume / 弱 catalyst 的真实比较，更不会产生新的过滤命中
3. 所以这批 W1 结果当前更适合用来界定规则适用边界，而不是拿来反证 `300502` 型 candidate entry 收紧方向本身

为避免继续受旧 artifact 代际边界影响，当前又补了两件事：

1. `scripts/replay_selection_target_calibration.py` 已扩展为可直接读取 `selection_target_replay_input.json`、`selection_snapshot.json`、report 目录与 `selection_artifacts/` 目录，并新增 `selection_snapshot` 输入回归测试，保证在缺少专用 replay input 的历史窗口里仍能把高保真 snapshot 转成 replay payload
2. 随后对新鲜 dual-target 运行目录 `data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329/` 中已落盘的 `2026-03-23` 与 `2026-03-24` snapshot 继续复用 `volume_expansion_quality <= 0.0` 的 volume-only replay，专门检查这条 `2026-03-26` 单日最小 separating row 是否具有跨日稳定性

这两天给出的结果，已经足以把当前结论从“找到规则”收紧为“找到单日边界样本”：

1. `2026-03-23` 的高保真 replay 中，`300502` 与 `300394` 虽然都可重放，但 focus diagnostics 显示两者都处在 `layer_b_boundary` 路径；其中 `300502` 的 `volume_expansion_quality=0.25`，`300394=0.0`，所以 `volume_expansion_quality <= 0.0` 不会过滤 `300502`
2. `2026-03-24` 的高保真 replay 更进一步：当天汇总已经是 `rejected=7`、`blocked=0`，`300502` 与 `300394` 仍都落在 `layer_b_boundary` 且 eligibility 为空，volume-only 规则连可作用的 candidate-entry 样本都没有
3. 因而，`volume_expansion_quality <= 0.0` 当前应被解释为 `2026-03-26` 那个 candidate-entry 分支上的最小 separating row，而不是已经证明可以跨日复用的稳定入口规则

这一步把下一轮优化方向进一步收紧为：

1. `300724` 仍属于阈值路径，可继续作为 near-miss / selected 的边界标定样本
2. `300394`、`300502` 已经不适合作为“阈值共调”对象，而应转入 score construction、penalty 结构和 candidate entry 的重新设计

随后又在同一个高保真 4 日窗口上补做了一轮更高层的失败机制扫描，目的是判断“主线到底该先投哪里”，而不是继续盯单个样本：

1. 新产物：`short_trade_blocker_analysis_current_window.json` / `.md`
2. `scripts/analyze_short_trade_blockers.py` 现已增强为输出 `failure_mechanism_counts`、`candidate_source_breakdown` 与 `recommended_focus_areas`
3. 当前窗口共有 32 个 short-trade 样本，其中 23 个直接表现为 `rejected_layer_b_boundary_score_fail`，全部来自 `layer_b_boundary + near_fast_score_threshold`，均值分数只有 `0.1323`
4. 同一窗口还有 5 个样本被 `layer_c_bearish_conflict` 直接阻断，其中包含接近 near-miss 的 `300724` 和既有 penalty 主导样本 `300394`
5. 相比之下，`watchlist_filter_diagnostics` 路径在当前窗口只占 4 个样本，且全部已经被 `layer_c_bearish_conflict` 先行阻断；这意味着继续深挖 `300502` 的单样本 candidate-entry 外推，已经不是当前窗口最有杠杆的主线

因此，基于当前窗口级证据，主线优先级应调整为：

1. 先复盘 `layer_b_boundary` 的 score construction / threshold 设计，因为这是当前最大失败簇
2. 再审 `layer_c_bearish_conflict` 的结构性阻断边界，尤其是 `300724` 这类接近 near-miss 的高分 blocked 样本
3. `300502` 路线暂时保留为局部 case study，而不再作为当前最优先的主线优化入口

围绕这两个主线优先级，当前又各补了一份专用分析，目的是把“应该改哪里”从方向判断推进到具体机制：

1. `layer_b_boundary_failure_analysis_current_window.json` / `.md` 显示，这 23 个 `layer_b_boundary` score-fail 样本并不是简单“阈值差一点”：它们的 `score_b` 均值已有 `0.3428`，但 short-trade `score_target` 均值只有 `0.1323`，距 near-miss 的均值 gap 仍达 `0.3277`
2. 同一分析还显示其 strongest positive metrics 只有 `close_strength=0.0841`、`trend_acceleration=0.0568`、`layer_c_alignment=0.0475`，而 `catalyst_freshness=0.0006`、`volume_expansion_quality=0.0062`、`breakout_freshness=0.0134` 接近整体塌陷；这说明真正需要审的是 `layer_b_boundary` 候选为何会在进入 short-trade 评分前就缺乏 breakout / catalyst / volume 质量，而不是先放宽 short-trade 线
3. `structural_conflict_blocker_review_current_window.json` / `.md` 则把 `layer_c_bearish_conflict` 的窗口级 blocked 簇进一步缩小为“先看高分 blocked 样本”：`300724` 的 `score_target=0.3785`，距 near-miss 只差 `0.0815`，明显比 `300394` / `300502` 这类低分 blocked 更值得优先审查
4. 同时，这个 blocked 簇的平均 penalty 暴露集中在 `overhead_supply_penalty=0.4682`、`stale_trend_repair_penalty=0.4606`、`extension_without_room_penalty=0.4497`；因此下一轮 structural 审查不应只问“要不要保留 bearish conflict hard block”，还应检查它是否与这些 penalty 在高分样本上发生了重复惩罚

换句话说，当前主线已经进一步收敛为：

1. 先把 `layer_b_boundary` 当作一个候选质量问题来审，而不是阈值问题
2. 再把 `layer_c_bearish_conflict` 当作一个 hard block 与高 penalty 叠加问题来审，优先从 `300724` 入手

因此，这个 replay 样本当前更适合用来验证：

1. dual-target 链路是否打通
2. 候选入口与 blocker observability 是否正常
3. frozen current_plan 的数据契约是否足以支持 short trade

它暂时不适合直接作为 short trade 阈值标定基线。

结论：

1. 双目标链路、artifact、candidate source 可观测性都已经打通
2. 当前 4 日样本里，short trade 全 blocked 的首要原因是 frozen replay 输入缺少 strategy signals，而不是单纯 gate 或阈值过强
3. 下一轮最值得做的不是直接继续调 `SELECT_THRESHOLD`、`NEAR_MISS_THRESHOLD`，而是先区分“链路验证样本”和“可用于 short trade 标定的样本”

## 7. 本次结论

本次任务已经完成三个关键验证：

1. 真实 2026-03-26 数据可以成功跑出 dual_target 结果
2. 长期研究与次日买入两个目标都已经真实写入 artifacts
3. 当前 short trade 空集至少分成两类问题：真实 live 结果暴露的是“入口太窄 + gate 偏硬”，而 frozen current_plan replay 额外暴露了“历史 plan 数据契约缺少 short trade 所需 strategy signals”

因此，当前系统状态应定义为：

1. 双目标运行链路已打通
2. research 目标可用
3. short trade 目标可运行但尚未达到稳定产出阶段
4. 下一步应先补齐可用于 short trade 标定的 replay 输入契约，再进入受控调参和入口解耦阶段
