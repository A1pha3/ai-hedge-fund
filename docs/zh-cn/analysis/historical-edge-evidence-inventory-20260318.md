# 2026-03-18 历史 edge evidence inventory

## 1. 文档目的

这份清单只做一件事：把当前历史 edge 样本库里已经完成收口的 `ticker / date / artifact` 对齐成稳定入口，避免后续重复盲扫 reports。

使用原则：

1. 先看一手 artifact，再看中文分析文档。
2. 只要某个对象已经能被更高优先级 evidence 明确归类为 benchmark、机制样本或冲突样本，就不再把它当作新候选。
3. 这份 inventory 只服务只读扩库，不服务 runtime 改动。

## 2. 固定 benchmark 的 evidence 覆盖

### 2.1 20260224 / 600519

已覆盖的一手 evidence：

1. [data/reports/live_replay_600519_20260224_p1.json](../../data/reports/live_replay_600519_20260224_p1.json)
2. [data/reports/live_replay_600519_p1_summary.md](../../data/reports/live_replay_600519_p1_summary.md)

覆盖结论：

1. 这是明确的 `watch + bc_conflict = null` 历史阈值边缘样本。
2. 它是“应当放出”的基准边界，不应在后续分析里被重新压回去。

### 2.2 20260226 / 600519

已覆盖的一手 evidence：

1. [data/reports/live_replay_600519_20260226_p1.json](../../data/reports/live_replay_600519_20260226_p1.json)
2. [data/reports/live_replay_600519_p1_summary.md](../../data/reports/live_replay_600519_p1_summary.md)

覆盖结论：

1. 这是明确的 `watch + bc_conflict = null` 但仍保持 near-threshold 不过线的边界样本。
2. 它是“不能被放大成明显通过”的基准边界。

### 2.3 20260226 / 300724

已覆盖的一手 evidence：

1. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)
2. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/pipeline_timings.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/pipeline_timings.jsonl)
3. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json)

覆盖结论：

1. 这是当前长窗口里唯一稳定的 clean near-threshold non-conflict 样本族。
2. 其关键业务角色不是“再证明它能买”，而是约束 re-entry 保护不能被破坏。

## 3. 已收口机制样本的 evidence 覆盖

### 3.1 603993

已覆盖的一手 evidence：

1. [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl)
2. [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/pipeline_timings.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/pipeline_timings.jsonl)
3. [data/reports/paper_trading_20260202_20260205_logic_scores_logic_stop_source_m018/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_scores_logic_stop_source_m018/daily_events.jsonl)
4. [603993-mechanism-supplement-20260318.md](./603993-mechanism-supplement-20260318.md)

覆盖结论：

1. 关键日期绑定已经足够支撑“baseline sub-threshold -> frozen replay high-score watch -> logic stop exit”这条机制链。
2. 它保留研究价值，但不再作为第四个 benchmark 候选。

### 3.2 300065

已覆盖的一手 evidence：

1. [data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl](../../data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl)
2. [pipeline-funnel-scan-202602-window-20260312.md](./pipeline-funnel-scan-202602-window-20260312.md)
3. [300065-mechanism-supplement-20260318.md](./300065-mechanism-supplement-20260318.md)
4. [../factors/01-aggregation-semantics-and-factor-traps.md](../factors/01-aggregation-semantics-and-factor-traps.md)

覆盖结论：

1. 关键区间是 `20260223` 到 `20260225` 的 Layer B 连续压线。
2. 高优先级解释已经稳定指向“Layer B 压线 + Layer C 强 bearish avoid”，不再是 clean 样本问题。

### 3.3 688498

已覆盖的一手 evidence：

1. [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl)
2. [pipeline-funnel-scan-202602-window-20260312.md](./pipeline-funnel-scan-202602-window-20260312.md)
3. [688498-mechanism-supplement-20260318.md](./688498-mechanism-supplement-20260318.md)
4. [../factors/01-aggregation-semantics-and-factor-traps.md](../factors/01-aggregation-semantics-and-factor-traps.md)

覆盖结论：

1. 当前证据已经足够支撑“第三条腿缺失 + 中性稀释”的机制归类。
2. 它也不再具备 benchmark 候选资格。

## 4. 冲突与抑制样本的 evidence 覆盖

### 4.1 Layer C conflict 主入口

高优先级一手 evidence：

1. [data/reports/layer_c_edge_tradeoff_20260315.json](../../data/reports/layer_c_edge_tradeoff_20260315.json)
2. [data/reports/watchlist_suppression_analysis_20260315.json](../../data/reports/watchlist_suppression_analysis_20260315.json)

已稳定落在这组 evidence 里的对象：

1. `600988`
2. `000426`
3. `000960`
4. `300251`
5. `300775`
6. `600111`
7. `300308`

覆盖结论：

1. 这组对象的主语义不是 near-threshold clean watch，而是 `b_positive_c_strong_bearish` 或更广义的 watchlist suppression。
2. 一旦在这组 artifacts 里已经出现高优先级 conflict 解释，就不应因为 isolated watch 切片重新开专项。

### 4.2 20260303 prepared plan 截面

补充 evidence：

1. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)

当前可直接从该截面回看的对象：

1. `300775`
2. `600111`
3. `000426`
4. `300308`
5. `300251`

覆盖结论：

1. 这五个对象在同一 prepared plan 截面里已经能看到统一的 conflict/avoid 形态。
2. 后续如果只想复核抑制链，不必再全量翻历史窗口，可先回到这个截面。

## 5. 低优先级观察对象的 evidence 覆盖

### 5.1 601600

已覆盖的一手 evidence：

1. [data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/daily_events.jsonl)
2. [data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/pipeline_timings.jsonl](../../data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/pipeline_timings.jsonl)
3. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)
4. [data/reports/rule_variant_backtests/baseline.timings.jsonl](../../data/reports/rule_variant_backtests/baseline.timings.jsonl)
5. [historical-edge-followup-scan-20260318.md](./historical-edge-followup-scan-20260318.md)

覆盖结论：

1. 日期主要集中在 `20260202`、`20260203`。
2. 正向记录主要来自特定 exit-fix 实验产物。
3. baseline 与其他产物里它更常表现为 `below_fast_score_threshold + neutral` 残留。
4. 因此它只保留观察价值，不进入补证池。

## 6. 当前仍然缺失的不是证据，而是新 clean 样本

本轮交叉盘点后，当前缺口并不是“老对象没有 evidence 入口”，而是：

1. 现有 evidence 已足够把 benchmark、机制样本、冲突样本和低优先级观察对象区分开。
2. 现有 reports 范围内仍没有新的 `watch + bc_conflict = null + near-threshold` 一手样本进入空白区。
3. 所以当前低风险工作重点仍应是维护索引，而不是重新设计规则或重新打开旧对象的资格讨论。

## 7. 建议的后续读取顺序

如果后续还要继续只读扩库，建议按这个顺序：

1. 先看 [data/reports/historical_edge_sample_scan_20260318.json](../../data/reports/historical_edge_sample_scan_20260318.json) 确认是否出现新 ticker/date。
2. 再看 [historical-edge-artifact-index-20260318.md](./historical-edge-artifact-index-20260318.md) 和本文，判断该对象是否已经被既有 evidence 覆盖。
3. 只有当对象不在现有 inventory 里，且一手 evidence 先满足 clean 准入条件，才值得新开专项补证文档。

## 8. 当前状态

截至 `2026-03-18`：

1. 固定 benchmark 仍只有三条。
2. 603993、300065、688498 的机制样本归类已经有稳定 evidence 入口。
3. 600988、000426、000960、300251、300775、600111、300308 已有稳定 conflict/suppression 入口。
4. 601600 只保留低优先级观察位。
5. 当前没有新的 clean near-threshold non-conflict 空白样本等待补证。