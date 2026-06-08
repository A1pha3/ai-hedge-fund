# 2026-03-18 历史 edge 机制样本最小复核读单

## 1. 文档目的

这份读单只服务一个场景：后续如果需要快速确认 603993、300065、688498 为什么已经被收口为机制样本，而不是新的 clean benchmark，最少应该看哪些文件、分别确认什么。

它不新增结论，只把三份专项补证文档和对应一手 artifact 压成最低成本入口。

## 2. 最短复核顺序

### 第一步：先确认三者都已退出 benchmark 池

必读文件：

1. [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md)

读完应确认的事实：

1. `603993`、`300065`、`688498` 都已经归入机制样本，不再是第四个 benchmark 候选。
2. 当前 benchmark 合同仍固定为三条，不因这三者而改变。

### 第二步：按对象回看最关键的一手 evidence

#### 603993

必读文件：

1. [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl)
2. [603993-mechanism-supplement-20260318.md](./603993-mechanism-supplement-20260318.md)

读完应确认的事实：

1. `20260203` 实际买入，`20260204` 加仓，`20260205` 触发 `logic_stop_loss` 卖出。
2. 它的核心语义是“上游 near-threshold/sub-threshold -> frozen replay high-score watch -> logic stop failure”。
3. 这是一条形成机制链，不是稳定边界样本。

#### 300065

必读文件：

1. [data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl](../../data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl)
2. [300065-mechanism-supplement-20260318.md](./300065-mechanism-supplement-20260318.md)

读完应确认的事实：

1. 关键窗口是 `20260223` 到 `20260225`。
2. 它的核心语义不是 clean watch，而是“Layer B 压线后在 Layer C 被强 bearish investor 共识打回 avoid”。
3. 这是 conflict/aggregation 机制样本，不是 benchmark。

#### 688498

必读文件：

1. [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl)
2. [688498-mechanism-supplement-20260318.md](./688498-mechanism-supplement-20260318.md)

读完应确认的事实：

1. 它最接近阈值时也仍停在 `below_fast_score_threshold`。
2. 核心问题不是 hard negative，而是“第三条腿缺失 + 中性 mean_reversion 稀释”。
3. 它只能作为低优先级机制线索保留。

### 第三步：只在需要时回到统一解释层

可选补充文件：

1. [pipeline-funnel-scan-202602-window-20260312.md](./pipeline-funnel-scan-202602-window-20260312.md)
2. [../factors/01-aggregation-semantics-and-factor-traps.md](../factors/01-aggregation-semantics-and-factor-traps.md)

使用方式：

1. 如果只是确认归类，前两步已经够用。
2. 只有当需要解释“为什么是这个机制”时，再回到 funnel 与 factor 文档。

## 3. 一页式复核口径

如果只保留一页结论，应该记住下面三条：

1. `603993` 是上游形成机制样本，关键词是“frozen replay 抬升后 logic stop failure”。
2. `300065` 是 Layer B 压线并被 Layer C 强 bearish 打回的冲突机制样本。
3. `688498` 是第三条腿缺失并被中性策略稀释的低优先级机制样本。

## 4. 当前状态

截至 `2026-03-18`：

1. 三个已收口对象都已经有最低成本复核入口。
2. 它们的作用是解释机制，不是扩 benchmark。
3. 当前样本库仍然只有三条固定 benchmark。