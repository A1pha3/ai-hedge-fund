# 双目标系统数据结构与 Artifact Schema 规格

> 文档元信息
>
> - 首次创建日期：2026-03-28
> - 最近更新时间：2026-03-28 09:45:53 CST
> - 当前目录：docs/zh-cn/product/arch/dual_target_system/

## 0. 文档定位

本文档是以下文档的字段级配套规格：

1. [双目标选股与交易目标系统架构设计文档](./arch_dual_target_selection_system.md)
2. [次日短线目标指标与验证方案](./short_trade_target_metrics_and_validation.md)
3. [次日短线目标首版规则集规格](./short_trade_target_rule_spec.md)

本文档只回答一个问题：

双目标系统在工程实现时，目标层输入、目标层输出、ExecutionPlan 承接方式、selection_artifacts 扩展方式，以及 replay / summary / feedback 的 schema 应该长什么样。

本文档目标是把后续实现前最容易反复争论的内容先冻结成字段级协议。

---

## 1. 设计原则

### 1.1 增量兼容优先

当前系统已经有：

1. [src/research/models.py](src/research/models.py) 中的 `SelectionSnapshot`
2. [src/research/models.py](src/research/models.py) 中的 `SelectedCandidate` / `RejectedCandidate`
3. [src/execution/models.py](src/execution/models.py) 中的 `ExecutionPlan`

因此双目标 schema 的第一原则不是重做，而是扩展：

1. 不破坏现有 research artifact 读取链路
2. 不破坏现有 Replay Artifacts 页面基本消费语义
3. 不要求一次性把所有字段顶到 ExecutionPlan 顶层

### 1.2 事实层与目标层分离

所有 target-specific 字段都应从基础事实层剥离出来，放入明确的目标层对象里。

原因：

1. research target 与 short trade target 不能再共享一个混合分数
2. frozen replay 需要固定 target input contract
3. artifacts 需要能独立展示 research 与 short trade 的差异

### 1.3 schema 优先服务 replay 与验证

字段设计的第一用途不是“代码好看”，而是：

1. 能支撑 frozen replay
2. 能支撑 selected / rejected / blockers 的复盘
3. 能支撑目标级指标统计
4. 能支撑后续前端工作台展示

---

## 2. 当前已有数据结构基线

### 2.1 现有 research artifact 基线

当前 [src/research/models.py](src/research/models.py) 已有：

1. `SelectionSnapshot`
2. `SelectedCandidate`
3. `RejectedCandidate`
4. `ResearchFeedbackRecord`
5. `SelectionArtifactWriteResult`

当前 `SelectionSnapshot` 的核心结构是：

1. 运行元信息
2. `selected`
3. `rejected`
4. `buy_orders`
5. `sell_orders`
6. `funnel_diagnostics`
7. `artifact_status`

它本质上仍是单目标 research 语义。

### 2.2 现有执行模型基线

当前 [src/execution/models.py](src/execution/models.py) 中的 `ExecutionPlan` 已有：

1. `logic_scores`
2. `buy_orders`
3. `sell_orders`
4. `watchlist`
5. `selection_artifacts`

这说明：

1. 当前执行层已经能承接 artifact 元信息
2. 但还没有明确的双目标对象

---

## 3. 双目标目标层对象

建议新增一组独立目标层模型，推荐放在未来的 `src/targets/models.py`。

### 3.1 SelectionTargetType

```text
SelectionTargetType
- research
- short_trade
```

### 3.2 TargetDecision

```text
TargetDecision
- selected
- near_miss
- rejected
- blocked
```

说明：

1. `selected` 表示通过该目标的核心 gate
2. `near_miss` 表示接近通过，适合复盘
3. `rejected` 表示未通过
4. `blocked` 表示理论上有交易价值，但被执行/风控 gate 阻断

### 3.3 TargetEvaluationInput

建议字段：

```text
TargetEvaluationInput
- trade_date: str
- ticker: str
- market: str
- market_state: dict | MarketState
- layer_a_metadata: dict
- strategy_signals: dict[str, StrategySignal]
- score_b: float
- score_c: float
- score_final: float
- layer_c_decision: str
- bc_conflict: str | None
- agent_contribution_summary: dict
- liquidity_features: dict
- volatility_features: dict
- event_features: dict
- sector_features: dict
- execution_constraints: dict
- replay_context: dict
```

设计意图：

1. 让 research / short trade 两类目标都使用同一份目标层输入
2. 让目标层与 daily pipeline、layer_c 聚合器解耦
3. 让 frozen replay 可以稳定序列化和复放

### 3.4 TargetEvaluationResult

建议字段：

```text
TargetEvaluationResult
- target_type: SelectionTargetType
- decision: TargetDecision
- score_target: float
- confidence: float
- rank_hint: int | None
- positive_tags: list[str]
- negative_tags: list[str]
- blockers: list[str]
- top_reasons: list[str]
- rejection_reasons: list[str]
- gate_status: dict[str, str]
- expected_holding_window: str | None
- preferred_entry_mode: str | None
- metrics_payload: dict
- explainability_payload: dict
```

说明：

1. `gate_status` 用来记录 data / execution / structural / score 等 gate 的通过情况
2. `metrics_payload` 用来承接目标专属数值，例如 short trade 的 breakout_freshness 等
3. `explainability_payload` 用来承接面向 UI / markdown 的细节解释

### 3.5 DualTargetEvaluation

建议新增聚合对象：

```text
DualTargetEvaluation
- ticker
- trade_date
- research: TargetEvaluationResult
- short_trade: TargetEvaluationResult
- delta_classification: str
- delta_summary: list[str]
```

这里的 `delta_classification` 建议复用文档中的四类：

1. `research_pass_short_reject`
2. `research_reject_short_pass`
3. `both_pass_but_rank_diverge`
4. `both_reject_but_reason_diverge`

---

## 4. ExecutionPlan 承接方式

### 4.1 第一阶段不建议破坏顶层结构

当前 `ExecutionPlan` 已经被多个运行链路消费，不建议第一阶段做大改。

建议第一阶段仅增加以下字段：

```text
ExecutionPlan
- selection_targets: dict[str, dict]
- target_mode: str
- dual_target_summary: dict
```

### 4.2 selection_targets 建议结构

```json
{
  "selection_targets": {
    "AAPL": {
      "research": {
        "decision": "selected",
        "score_target": 0.71,
        "confidence": 0.82,
        "positive_tags": ["structure_complete"],
        "negative_tags": [],
        "blockers": []
      },
      "short_trade": {
        "decision": "rejected",
        "score_target": 0.44,
        "confidence": 0.63,
        "positive_tags": ["trend_acceleration_active"],
        "negative_tags": ["stale_trend_repair"],
        "blockers": ["stale_structure"]
      },
      "delta_classification": "research_pass_short_reject"
    }
  }
}
```

这样做的优点：

1. 兼容当前以 ticker 为中心的 plan 结构
2. 不需要第一步就引入大量新顶层列表
3. 后续 UI 与 artifact 都能直接消费

### 4.3 dual_target_summary 建议结构

```text
dual_target_summary
- target_mode
- research_selected_count
- short_trade_selected_count
- research_near_miss_count
- short_trade_near_miss_count
- delta_counts
```

这个对象主要服务：

1. session_summary 聚合
2. daily_events 轻量展示
3. 工作台概览卡片

---

## 5. SelectionSnapshot 的双目标扩展

### 5.1 第一阶段建议保留 selected / rejected 语义不变

当前 `SelectionSnapshot.selected` 与 `rejected` 已被页面和研究工作流消费。

不建议第一阶段直接替换它们，而建议新增：

```text
SelectionSnapshot
- selection_targets: dict[str, DualTargetEvaluation]
- target_mode: str
- research_view: dict
- short_trade_view: dict
- dual_target_delta: dict
```

### 5.2 research_view 建议结构

```text
research_view
- selected_symbols
- near_miss_symbols
- rejected_symbols
- blocker_counts
```

### 5.3 short_trade_view 建议结构

```text
short_trade_view
- selected_symbols
- near_miss_symbols
- rejected_symbols
- blocked_symbols
- blocker_counts
```

### 5.4 dual_target_delta 建议结构

```text
dual_target_delta
- delta_counts
- representative_cases
- dominant_delta_reasons
```

这里的 `representative_cases` 用于工作台和 markdown 快速展示典型差异票。

---

## 6. selected / rejected 项的扩展方式

### 6.1 SelectedCandidate 建议增加 target_context

建议在未来扩展 [src/research/models.py](src/research/models.py) 中的 `SelectedCandidate`：

```text
SelectedCandidate
- target_context: dict
- target_decisions: dict[str, TargetEvaluationResult]
```

说明：

1. 这允许某只 research selected 股票同时展示其 short trade verdict
2. 不需要改变原有 selected 列表的主语义

### 6.2 RejectedCandidate 建议增加 target_context

同理建议给 `RejectedCandidate` 增加：

```text
RejectedCandidate
- target_context: dict
- target_decisions: dict[str, TargetEvaluationResult]
```

这样 near-miss 场景可以明确告诉研究员：

1. 它是 research near_miss
2. 还是 short_trade near_miss
3. 还是两者都 reject 但原因不同

---

## 7. Artifact 输出规范

### 7.1 selection_snapshot.json

建议第一阶段在原有 snapshot 基础上增加：

1. `target_mode`
2. `selection_targets`
3. `research_view`
4. `short_trade_view`
5. `dual_target_delta`

### 7.2 selection_review.md

建议在 review markdown 中增加三个新段落：

1. Research Target Summary
2. Short Trade Target Summary
3. Target Delta Highlights

目标不是把 markdown 写得更长，而是让研究员一眼看出：

1. 哪些票是研究通过但短线拒绝
2. 哪些票是短线通过但研究一般
3. 主阻断因素是什么

### 7.3 daily_events.jsonl

建议 current_plan 增加轻量 target 摘要，而不是塞入全部明细：

```text
current_plan.target_summary
- target_mode
- research_selected_count
- short_trade_selected_count
- delta_counts
```

### 7.4 session_summary.json

建议增加：

```text
session_summary.target_summary
- target_mode
- by_trade_date
- overall_research_stats
- overall_short_trade_stats
- overall_delta_stats
```

---

## 8. 反馈与工作流 schema 扩展

### 8.1 ResearchFeedbackRecord 不应被直接复用为全部目标反馈

当前 `ResearchFeedbackRecord` 更偏 research 语义。

建议第一阶段最小扩展为：

```text
ResearchFeedbackRecord
- target_type: str = "research"
- target_decision: str | None
- delta_classification: str | None
```

这样旧逻辑仍然兼容，但已经能承载双目标上下文。

### 8.2 后续建议新增统一 TargetFeedbackRecord

如果双目标试运行稳定后，可以再演进到：

```text
TargetFeedbackRecord
- feedback_version
- target_type
- trade_date
- symbol
- reviewer
- review_status
- verdict
- tags
- notes
- created_at
```

但这不建议在第一阶段立刻替换现有 feedback schema。

---

## 9. 命名与版本策略

建议所有新 target schema 都显式带版本：

1. `target_schema_version`
2. `short_trade_rule_version`
3. `target_profile`

原因：

1. frozen replay 必须知道它在复放哪一版规则
2. 默认档升级必须能追踪版本
3. 统计报告必须能按版本切片

---

## 10. 第一阶段最小落地顺序

建议严格按以下顺序落地：

1. 定义 `TargetEvaluationInput` / `TargetEvaluationResult`
2. 在 `selection_artifacts` 中增加 `selection_targets` 透传
3. 在 `ExecutionPlan.selection_artifacts` 或新增轻量字段中增加 `target_summary`
4. 更新 `selection_review.md` 渲染模板
5. 最后再评估是否需要升格更多字段到 `ExecutionPlan` 顶层

这样可以把改动主要限制在：

1. target models
2. artifact writer
3. review renderer
4. summary aggregation

而不是一开始就把整个运行模型打散重写。

---

## 11. 当前建议结论

双目标系统要真正进入可实现阶段，最关键的一步不是再补概念，而是冻结字段协议。

当前最合理的路线是：

1. 保持现有 `ExecutionPlan` 和 `SelectionSnapshot` 主体兼容
2. 通过 `selection_targets`、`target_summary`、`dual_target_delta` 等增量字段接入双目标结果
3. 先让 replay、review、summary、feedback 都能消费目标维度
4. 在 schema 稳定后，再决定是否做更大规模的数据模型重构

这会显著降低后续实现阶段的返工概率。
