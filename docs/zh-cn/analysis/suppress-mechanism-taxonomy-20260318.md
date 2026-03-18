# 2026-03-18 Suppress / Mechanism Taxonomy

## 1. 目的

P1-3 的目标不是新增结论，而是把已经分散在补证文档、reading list 和 factor trap 文档里的语义压成统一分类。这样后续遇到新对象时，可以先用同一套语言归类，再决定是否需要专项补证。

这份 taxonomy 只服务三个判断：

1. 这个对象是 `benchmark`、`mechanism`、`conflict/suppression`，还是仅保留为 `observation`。
2. 如果它是 mechanism，它更接近哪一种已知形成模式。
3. 最低成本证据入口应该先看哪里，而不是重新发明解释语言。

## 2. 一级分类

| 一级分类 | 定义 | 当前对象 | 不该做什么 |
| --- | --- | --- | --- |
| `benchmark` | 稳定、可复用、能约束后续最小规则实验的硬边界样本 | `20260224/600519`、`20260226/600519`、`20260226/300724` | 不把 interesting case 混进 benchmark 池 |
| `mechanism` | 有研究价值，但主要解释形成链或聚合陷阱，不提供 clean 边界验收 | `603993`、`300065`、`688498`、`300724 lifecycle` | 不据此推进全局规则放松 |
| `conflict/suppression` | 高优先级解释已经稳定落在 Layer C conflict 或 watchlist suppression 上 | `600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308` | 不因 isolated watch 切片重开专项 |
| `observation` | 目前只有零散命中或高分切片，但不足以进入上述三类 | `601600` 等观察位 | 不提前升格为 benchmark 或 mechanism |

## 3. 二级机制类型

### 3.1 Mechanism A: Upstream Formation Jump

定义：上游只表现为 near-threshold 或 sub-threshold，但在某些 replay / context 中会跨层跳到 high-score watch、真实成交，随后快速失败。

代表对象：`603993`

判别信号：

1. baseline 或 scan 里主要停在 Layer B 下沿或 sub-threshold。
2. frozen replay 或特定 context 中被抬成 high-score watch。
3. 后续快速进入 logic stop、failure chain 或其他失败闭环。

主解释语义：这类对象有信息量，但信息量属于“形成机制为什么会跨层跳变”，不属于 clean edge 验收。

### 3.2 Mechanism B: Profitability Cliff + Layer C Bearish Veto

定义：对象在 Layer B fast threshold 附近持续压线，甚至偶尔过线，但 profitability 硬负项或 investor bearish 共识会把它直接打回 avoid / conflict。

代表对象：`300065`

判别信号：

1. `score_b` 连续贴在 `0.35 .. 0.38` 或略高于 fast gate。
2. factor trap 明确指向 profitability hard-negative semantics。
3. prepared plan 中出现 `bc_conflict = b_positive_c_strong_bearish`，最终 decision = avoid。

主解释语义：这类对象主要解释“为什么上游看起来快过线，但最终仍被强负向 Layer C 打回去”。

### 3.3 Mechanism C: Missing Third Leg + Neutral Dilution

定义：trend 和 fundamental 已经偏正，但缺少第三条稳定增量腿，且完整中性策略仍参与归一化，稀释了已有正分。

代表对象：`688498`

判别信号：

1. `trend + fundamental` 为正，但总分长期停在 fast gate 下方。
2. `event_sentiment` 多数时候直接缺席。
3. `mean_reversion` 为 `direction = 0` 但 `completeness > 0`，形成 neutral dilution。

主解释语义：这类对象解释的是聚合结构缺口，不是硬负项误杀。

### 3.4 Mechanism D: Weak Entry / Weak Re-entry Loss Source

定义：对象可以真实进入 execution，但主要亏损来自 edge score 开仓和弱确认回补，而不是仓位系统失控。

代表对象：`300724`

判别信号：

1. 可成交，但 entry / re-entry 分数长期贴近 watchlist edge。
2. 持有期最大浮盈很低，随后进入 hard stop 或其他硬退出。
3. 不回补版本优于弱确认回补版本。

主解释语义：这类对象是组合行为诊断样本，主要解释信号质量与 re-entry 质量，而不是 suppress/conflict。

## 4. Conflict / Suppression 统一语义

conflict/suppression 不再细拆成多个临时名称，统一按下面口径处理：

1. 一级语义固定为 `不是 clean near-threshold watch，而是被更高优先级 Layer C conflict 或 watchlist suppression 覆盖`。
2. 低成本主入口固定为 `layer_c_edge_tradeoff_20260315.json` 与 `watchlist_suppression_analysis_20260315.json`。
3. 如需逐日复核，统一先回到 `20260303` prepared-plan conflict 截面，而不是盲扫全窗口。

当前稳定覆盖对象：`600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308`。

## 5. 现象 -> 机制 -> 证据入口

| 现象 | 归类 | 机制解释 | 最低成本证据入口 |
| --- | --- | --- | --- |
| baseline 里 sub-threshold，特定 replay 里 high-score watch，随后 logic stop failure | `mechanism` | Upstream Formation Jump | [603993-mechanism-supplement-20260318.md](./603993-mechanism-supplement-20260318.md) |
| 连续压在 `0.373x`，偶尔 `score_b` 过线但 `score_final` 被强 bearish Layer C 打回 avoid | `mechanism` | Profitability Cliff + Layer C Bearish Veto | [300065-mechanism-supplement-20260318.md](./300065-mechanism-supplement-20260318.md) |
| `trend + fundamental` 为正，但缺第三条腿，neutral mean_reversion 稀释后停在 fast gate 下方 | `mechanism` | Missing Third Leg + Neutral Dilution | [688498-mechanism-supplement-20260318.md](./688498-mechanism-supplement-20260318.md) |
| 可成交但 entry / re-entry 分数贴边，回补后仍弱，baseline 不回补更优 | `mechanism` | Weak Entry / Weak Re-entry Loss Source | [300724-lifecycle-review-20260318.md](./300724-lifecycle-review-20260318.md) |
| near-threshold 或 isolated watch 看似有机会，但高优先级解释已是 `b_positive_c_strong_bearish` 或 suppression | `conflict/suppression` | Layer C Conflict / Watchlist Suppression | [historical-edge-conflict-suppression-reading-list-20260318.md](./historical-edge-conflict-suppression-reading-list-20260318.md) |
| `watch + bc_conflict = null + near-threshold`，且跨 artifact 稳定 | `benchmark candidate` | Clean Edge Boundary | [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md) |
| 只有零散高分或持仓结果，没有稳定一手 edge 证据 | `observation` | 暂不升格 | [historical-edge-refresh-protocol-20260318.md](./historical-edge-refresh-protocol-20260318.md) |

## 6. 最短归类顺序

新对象进入系统时，按下面顺序判断即可：

1. 先问它是否满足 `watch + bc_conflict = null + near-threshold` 且跨 artifact 稳定。如果满足，再考虑 benchmark 候选。
2. 如果 `bc_conflict != null`，或高优先级解释已在 tradeoff / suppression artifacts 中稳定出现，直接归到 `conflict/suppression`。
3. 如果它不属于 conflict，但证据主轴是跨层跳变、profitability cliff、第三条腿缺失、中性稀释、弱 re-entry 等形成问题，归到 `mechanism`。
4. 如果只有零散命中且没有稳定一手证据，先留在 `observation`。

这一步的目标不是追求完美分类，而是尽快避免“每来一个对象都重新发明一套解释”。

## 7. 边界约束

这份 taxonomy 固定三条约束：

1. benchmark 仍然只有三条：`20260224/600519`、`20260226/600519`、`20260226/300724`。
2. mechanism 样本可以继续补证，但不能自动推导出新的全局 Layer C / watchlist / avoid 放松实验。
3. conflict/suppression 的作用是解释为什么排除，不是为扩 benchmark 提供候选池。

## 8. 当前收口

截至 `2026-03-18`，当前 taxonomy 可以先视为稳定：

1. `603993`、`300065`、`688498` 已分别压实到三种不同的 mechanism 语义。
2. `300724` 的剩余问题已可单独落在 weak-entry / weak-reentry 行为类型，不再混入 suppress/conflict。
3. `600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308` 继续按 conflict/suppression 统一处理。
4. 新样本出现时，优先复用这份 taxonomy，而不是再扩散到多份临时补证文档。

## 9. 数据来源

1. [603993-mechanism-supplement-20260318.md](./603993-mechanism-supplement-20260318.md)
2. [300065-mechanism-supplement-20260318.md](./300065-mechanism-supplement-20260318.md)
3. [688498-mechanism-supplement-20260318.md](./688498-mechanism-supplement-20260318.md)
4. [300724-lifecycle-review-20260318.md](./300724-lifecycle-review-20260318.md)
5. [historical-edge-conflict-suppression-reading-list-20260318.md](./historical-edge-conflict-suppression-reading-list-20260318.md)
6. [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md)
7. [historical-edge-refresh-protocol-20260318.md](./historical-edge-refresh-protocol-20260318.md)
8. [layer-b-minimal-rule-change-proposal-20260312.md](./layer-b-minimal-rule-change-proposal-20260312.md)
9. [pipeline-funnel-scan-202602-window-20260312.md](./pipeline-funnel-scan-202602-window-20260312.md)
