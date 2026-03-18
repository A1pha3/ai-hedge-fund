# 2026-03-18 历史 edge 补证 artifacts 索引

## 1. 文档目的

这份索引只服务一个目标：在不改 runtime 的前提下，把后续历史 edge sample 补证要优先查看的 artifacts 收成一个稳定入口。

如果只想先知道不同场景应该跳哪份文档，可以先看 [historical-edge-overview-home-20260318.md](./historical-edge-overview-home-20260318.md)。

如果只需要最低成本复核当前边界，可以先看 [historical-edge-minimal-acceptance-reading-list-20260318.md](./historical-edge-minimal-acceptance-reading-list-20260318.md)。
如果只需要快速复核三个已收口机制样本，可以看 [historical-edge-mechanism-samples-reading-list-20260318.md](./historical-edge-mechanism-samples-reading-list-20260318.md)。
如果只需要快速确认 conflict/suppression 样本为什么应排除，可以看 [historical-edge-conflict-suppression-reading-list-20260318.md](./historical-edge-conflict-suppression-reading-list-20260318.md)。
如果要判断一个新 ticker/date 是否值得开专项补证，可以先看 [historical-edge-new-candidate-triage-checklist-20260318.md](./historical-edge-new-candidate-triage-checklist-20260318.md)。
如果只想用单页流程完成初筛，可以看 [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md)。

使用原则：

1. 先看一手 evidence files，再看中文分析文档。
2. 只有当一手 evidence 先满足 `watch + bc_conflict = null + near-threshold`，才值得新开专项补证。
3. 已经收口为 benchmark、机制样本或排除样本的对象，不再重复作为新候选启动。

## 2. 一级入口：固定 benchmark 样本

这组 artifacts 是当前最重要的硬基线，后续所有只读扩库或最小实验都要以它们为准。

### 2.1 600519

一手 evidence：

1. [data/reports/live_replay_600519_20260224_p1.json](../../data/reports/live_replay_600519_20260224_p1.json)
2. [data/reports/live_replay_600519_20260226_p1.json](../../data/reports/live_replay_600519_20260226_p1.json)
3. [data/reports/live_replay_600519_p1_summary.md](../../data/reports/live_replay_600519_p1_summary.md)

对应文档：

1. [edge-sample-benchmark-20260318.md](./edge-sample-benchmark-20260318.md)

### 2.2 300724

一手 evidence：

1. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)
2. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/pipeline_timings.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/pipeline_timings.jsonl)
3. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json)

对应文档：

1. [edge-sample-benchmark-20260318.md](./edge-sample-benchmark-20260318.md)
2. [paper-trading-edge-candidate-list-20260318.md](./paper-trading-edge-candidate-list-20260318.md)

## 3. 二级入口：历史扫描总表

这组 artifacts 用于判断“还有没有未关闭的新候选”，是每次补证前必须先看的汇总层。

核心文件：

1. [data/reports/historical_edge_sample_scan_20260318.json](../../data/reports/historical_edge_sample_scan_20260318.json)
2. [historical-edge-sample-library-expansion-20260318.md](./historical-edge-sample-library-expansion-20260318.md)
3. [historical-edge-followup-scan-20260318.md](./historical-edge-followup-scan-20260318.md)
4. [paper-trading-edge-candidate-list-20260318.md](./paper-trading-edge-candidate-list-20260318.md)
5. [historical-edge-candidate-closure-summary-20260318.md](./historical-edge-candidate-closure-summary-20260318.md)

当前用法：

1. 先从 `historical_edge_sample_scan_20260318.json` 看 ticker 是否出现在 `near_threshold_watch` 或 `sub_threshold_watch`
2. 如果只出现在 `high_score_watch`，默认不进入新一轮补证优先池
3. 如果中文收口文档已经明确否决，直接停止追踪

## 4. 三级入口：已完成收口的机制样本

这组 artifacts 保留研究价值，但不再作为新的 benchmark 候选。

### 4.1 603993

优先看：

1. [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl)
2. [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/pipeline_timings.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/pipeline_timings.jsonl)
3. [data/reports/paper_trading_20260202_20260205_logic_scores_logic_stop_source_m018/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_scores_logic_stop_source_m018/daily_events.jsonl)
4. [603993-mechanism-supplement-20260318.md](./603993-mechanism-supplement-20260318.md)

定位：上游形成机制样本，不是 benchmark。

### 4.2 300065

优先看：

1. [data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl](../../data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl)
2. [pipeline-funnel-scan-202602-window-20260312.md](./pipeline-funnel-scan-202602-window-20260312.md)
3. [300065-mechanism-supplement-20260318.md](./300065-mechanism-supplement-20260318.md)
4. [../factors/01-aggregation-semantics-and-factor-traps.md](../factors/01-aggregation-semantics-and-factor-traps.md)

定位：Layer B 压线 + 强 bearish Layer C avoid 机制样本。

### 4.3 688498

优先看：

1. [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl)
2. [pipeline-funnel-scan-202602-window-20260312.md](./pipeline-funnel-scan-202602-window-20260312.md)
3. [688498-mechanism-supplement-20260318.md](./688498-mechanism-supplement-20260318.md)
4. [../factors/01-aggregation-semantics-and-factor-traps.md](../factors/01-aggregation-semantics-and-factor-traps.md)

定位：第三条腿缺失 + 中性稀释机制样本。

## 5. 四级入口：冲突与抑制证据

这组 artifacts 的作用不是找新 benchmark，而是确认某个候选为什么应该被排除。

核心文件：

1. [data/reports/layer_c_edge_tradeoff_20260315.json](../../data/reports/layer_c_edge_tradeoff_20260315.json)
2. [data/reports/watchlist_suppression_analysis_20260315.json](../../data/reports/watchlist_suppression_analysis_20260315.json)
3. [paper-trading-edge-candidate-list-20260318.md](./paper-trading-edge-candidate-list-20260318.md)

适用对象：

1. `600988`
2. `000426`
3. `000960`
4. `300251`
5. `300775`
6. `600111`
7. `300308`

用法：

1. 如果扫描里出现 isolated watch 切片，先回到这组 artifacts 检查是否存在更高优先级的 conflict/avoid 证据
2. 一旦确认 `b_positive_c_strong_bearish` 是主状态，就不要再把该票送入 clean edge 候选池

## 6. 低优先级观察对象

这部分只保留记录，不建议优先投入专项补证时间。

### 6.1 601600

相关 artifacts：

1. [data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/daily_events.jsonl)
2. [data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/pipeline_timings.jsonl](../../data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/pipeline_timings.jsonl)
3. [data/reports/rule_variant_backtests/baseline.timings.jsonl](../../data/reports/rule_variant_backtests/baseline.timings.jsonl)
4. [historical-edge-followup-scan-20260318.md](./historical-edge-followup-scan-20260318.md)

当前结论：

1. 只出现在 `high_score_watch`
2. 正向记录主要来自特定 exit-fix 实验产物
3. baseline 视角下又退回普通 below-fast-threshold neutral 残留
4. 不进入当前补证池

## 7. 后续补证推荐顺序

后续如果继续做只读扩库，建议固定按下面顺序推进：

1. 先查 [data/reports/historical_edge_sample_scan_20260318.json](../../data/reports/historical_edge_sample_scan_20260318.json)
2. 再查对应 ticker/date 是否已出现在 [historical-edge-candidate-closure-summary-20260318.md](./historical-edge-candidate-closure-summary-20260318.md) 或专项补证文档中
3. 如果没有，再去原始 `daily_events.jsonl` / `pipeline_timings.jsonl` 取一手证据
4. 只有满足 clean 准入条件，才新建专项补证文档

## 8. 当前状态

截至 `2026-03-18`：

1. 补证入口已经收敛
2. 当前历史样本库只有三条 benchmark
3. 现有 artifacts 范围内没有新的 clean near-threshold non-conflict 候选被遗漏
4. 下一步继续做只读索引和一手证据复核即可，不需要触碰 runtime
