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