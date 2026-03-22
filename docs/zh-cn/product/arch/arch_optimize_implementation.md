# 选股优先优化方案实施设计文档

## 1. 文档目标

本文档是 [arch_optimize.md](docs/zh-cn/product/arch/arch_optimize.md) 的实施落地版本，目标不是再次解释为什么要这样设计，而是明确回答以下问题：

1. 改哪些模块。
2. 每个产物的 schema 是什么。
3. 产物在什么时机生成。
4. 上下游通过什么接口解耦。
5. 第一版最小实现应该按什么顺序完成。
6. 如何验证实现没有破坏现有回测与纸面交易流程。

本文档默认遵循如下实施约束：

1. 第一阶段只增强选股研究可观测性，不改变既有交易决策语义。
2. 除非明确需要，否则不重构 Layer A、Layer B、Layer C 主流程。
3. 所有新增字段优先以向后兼容方式扩展现有数据结构。
4. 所有 artifact 写入失败默认不得阻断主交易流程，但必须可见、可记录、可诊断。

---

## 2. 实施范围

### 2.1 本次纳入范围

1. 生成结构化选股事实快照 selection_snapshot.json。
2. 基于快照生成人类可读的 selection_review.md。
3. 定义并落地研究员反馈接口 research_feedback.jsonl。
4. 将 artifact 目录与运行目录建立清晰绑定关系。
5. 为后续统计分析和标签回灌保留稳定字段。
6. 为第一阶段实验建立最小验收标准和测试方案。

### 2.2 本次明确不做

1. 不在本轮引入新的选股 alpha 因子。
2. 不在本轮修改买卖点逻辑。
3. 不在本轮引入复杂数据库存储。
4. 不在本轮建设完整研究员标注平台。
5. 不在本轮把 feedback 直接闭环进实时策略参数更新。

---

## 3. 现有代码落点

### 3.1 主要流程入口

本次实施建议围绕以下现有模块扩展：

1. [src/execution/daily_pipeline.py](src/execution/daily_pipeline.py)
   负责每日筛选与执行准备主流程，是生成 selection_snapshot 的首选位置。
2. [src/paper_trading/runtime.py](src/paper_trading/runtime.py)
   负责纸面交易会话目录、daily_events.jsonl、session_summary.json 等产物落盘，是注入 artifact writer 的关键位置。
3. [src/backtesting/engine.py](src/backtesting/engine.py)
   负责回测运行目录与事件持久化，需要提供与纸面交易一致的 artifact 写入入口。
4. [src/execution/models.py](src/execution/models.py)
   当前承载 current_plan 相关模型，适合增加 artifact 元信息字段。
5. [src/screening/models.py](src/screening/models.py)
   当前承载 Layer B 产物类型，必要时扩展字段映射与序列化辅助逻辑。
6. [src/execution/layer_c_aggregator.py](src/execution/layer_c_aggregator.py)
   已有 analyst 汇总信息，可作为 selection_snapshot 的解释来源。

### 3.2 新增模块建议

为了避免把文档渲染和文件写入逻辑塞进主流程文件，建议新增以下模块：

1. src/research/artifacts.py
   负责 artifact 数据结构、序列化和写入编排。
2. src/research/review_renderer.py
   负责把 selection_snapshot 渲染为 selection_review.md。
3. src/research/feedback.py
   负责 research_feedback.jsonl 的 schema、校验和读写辅助。
4. src/research/models.py
   负责本次新增的 Pydantic 模型定义。

如果项目当前不希望新增 research 子包，也可以放入 src/execution/selection_artifacts.py，但从长期维护性看不如独立 research 模块清晰。

---

## 4. 实施原则

### 4.1 主流程只生产事实，不负责文档排版

DailyPipeline 应该输出结构化事实对象，Markdown 渲染属于下游展示层。

### 4.2 先有 snapshot，再有 review

selection_review.md 必须完全由 selection_snapshot.json 派生生成，避免两套逻辑各自拼接导致信息漂移。

### 4.3 writer 注入优先于路径硬编码

优先使用 callback 或 writer 对象注入，而不是让 DailyPipeline 直接依赖纸面交易目录结构。

### 4.4 失败降级而非失败中断

artifact 写入失败时：

1. 主交易流程继续。
2. 日志明确记录失败原因。
3. current_plan 或事件流中保留 artifact_write_status。

---

## 5. 核心数据模型

### 5.1 SelectionSnapshot

建议新增顶层模型 SelectionSnapshot，作为 selection_snapshot.json 的唯一源。

建议字段如下：

```json
{
  "artifact_version": "v1",
  "run_id": "paper_20260322_153000",
  "experiment_id": "w1_selection_freeze_v1",
  "trade_date": "2026-03-22",
  "market": "CN",
  "decision_timestamp": "2026-03-22T15:05:00+08:00",
  "data_available_until": "2026-03-22T15:00:00+08:00",
  "pipeline_config_snapshot": {
    "code_version": "git_sha",
    "execution_version": "paper_runtime_vX",
    "analyst_roster_version": "roster_v3",
    "model_provider": "MiniMax",
    "model_name": "MiniMax-M2.7",
    "key_thresholds": {
      "score_b_min": 0.62,
      "score_final_min": 0.55,
      "max_watchlist_size": 12
    },
    "environment": {
      "market_region": "CN",
      "replay_mode": false
    }
  },
  "universe_summary": {
    "input_symbol_count": 5231,
    "candidate_count": 322,
    "high_pool_count": 27,
    "watchlist_count": 8,
    "buy_order_count": 5
  },
  "selected": [],
  "rejected": [],
  "buy_orders": [],
  "sell_orders": [],
  "funnel_diagnostics": {},
  "artifact_status": {
    "snapshot_written": true,
    "review_written": true
  }
}
```

### 5.2 SelectedCandidate

selected 应表示研究视角下的重点审查对象，通常对应 watchlist，而不是 buy_orders。

```json
{
  "symbol": "000001",
  "name": "平安银行",
  "decision": "watchlist",
  "score_b": 0.71,
  "score_c": 0.66,
  "score_final": 0.69,
  "rank_in_watchlist": 2,
  "layer_b_summary": {
    "fusion_label": "bullish",
    "top_factors": [
      {"name": "earnings_revision", "value": 0.72},
      {"name": "volume_breakout", "value": 0.68}
    ]
  },
  "layer_c_summary": {
    "bullish_agents": 5,
    "bearish_agents": 1,
    "neutral_agents": 2,
    "agent_contribution_summary": [
      {"agent": "Warren Buffett", "signal": "bullish", "confidence": 79, "reason": "估值和资本回报率稳定"}
    ]
  },
  "execution_bridge": {
    "included_in_buy_orders": true,
    "target_weight": 0.12,
    "execution_notes": "通过仓位与风险约束"
  },
  "research_prompts": {
    "why_selected": [
      "Layer B 综合分数位于当日高位",
      "分析师聚合后观点偏一致",
      "未触发主要风险排除条件"
    ],
    "what_to_check": [
      "上涨理由是否依赖短期事件噪声",
      "是否存在隐含财务或监管风险"
    ]
  }
}
```

### 5.3 RejectedCandidate

rejected 不需要记录所有落选股票，第一版只需要保留“接近入选但最终落选”的 near-miss 样本，便于研究员识别阈值误伤。

```json
{
  "symbol": "300750",
  "name": "宁德时代",
  "rejection_stage": "layer_c",
  "score_b": 0.73,
  "score_c": 0.41,
  "score_final": 0.49,
  "rejection_reason_codes": ["analyst_divergence_high", "valuation_risk_flag"],
  "rejection_reason_text": "Layer B 得分较高，但 Layer C 分歧较大，最终未进入 watchlist"
}
```

### 5.4 ResearchFeedbackRecord

research_feedback.jsonl 每行一条记录，建议 schema 如下：

```json
{
  "feedback_version": "v1",
  "artifact_version": "v1",
  "run_id": "paper_20260322_153000",
  "trade_date": "2026-03-22",
  "symbol": "000001",
  "review_scope": "watchlist",
  "reviewer": "researcher_a",
  "review_status": "final",
  "primary_tag": "high_quality_selection",
  "tags": ["high_quality_selection", "thesis_clear"],
  "confidence": 0.84,
  "research_verdict": "selected_for_good_reason",
  "notes": "上涨逻辑清楚，且不是单一情绪驱动",
  "created_at": "2026-03-22T20:15:00+08:00"
}
```

字段规则：

1. primary_tag 必须来自受控词表。
2. tags 可多值，但必须属于标签字典。
3. review_status 至少区分 draft 和 final。
4. confidence 表示研究员主观把握度，不表示市场未来收益概率。

---

## 6. 文档产物模板

### 6.1 selection_review.md 目标

该文档不是日志转储，而是研究员每天真正愿意读的审查材料。因此第一版必须遵循短而硬的结构。

### 6.2 建议模板

```md
# 选股审查日报 - 2026-03-22

## 运行概览
- run_id: paper_20260322_153000
- universe: 5231
- candidate_count: 322
- high_pool_count: 27
- watchlist_count: 8
- buy_order_count: 5

## 今日入选股票

### 1. 000001 平安银行
- final_score: 0.69
- buy_order: yes
- 入选原因:
  - Layer B 分数高
  - 分析师分歧低
  - 风险标记少
- 建议重点复核:
  - 逻辑是否过度依赖短期交易量
  - 银行板块是否存在系统性压力

## 接近入选但落选

### 1. 300750 宁德时代
- rejection_stage: layer_c
- 原因: analyst_divergence_high, valuation_risk_flag

## 当日漏斗观察
- Layer A -> candidate: 5231 -> 322
- candidate -> high_pool: 322 -> 27
- high_pool -> watchlist: 27 -> 8
- watchlist -> buy_orders: 8 -> 5

## 研究员标注说明
- review_scope 以 watchlist 为主
- buy_orders 只作为下游承接参考
```

### 6.3 渲染要求

1. 所有内容必须从 snapshot 派生。
2. Markdown 中不得出现 snapshot 不存在的事实。
3. 每只股票最多展示 3 条主要入选原因和 2 条重点复核问题，防止文档膨胀。

---

## 7. 模块接口设计

### 7.1 建议接口一览

```python
class SelectionArtifactWriter(Protocol):
    def write_selection_artifacts(self, snapshot: SelectionSnapshot) -> SelectionArtifactWriteResult:
        ...


def build_selection_snapshot(
    *,
    trade_date: date,
    run_id: str,
    experiment_id: str | None,
    pipeline_result: DailyPipelineResult,
    pipeline_config_snapshot: PipelineConfigSnapshot,
    artifact_context: ArtifactContext,
) -> SelectionSnapshot:
    ...


def render_selection_review(snapshot: SelectionSnapshot) -> str:
    ...


def append_research_feedback(
    *,
    file_path: Path,
    record: ResearchFeedbackRecord,
) -> None:
    ...
```

### 7.2 推荐集成方式

推荐使用 writer 注入模式。

具体做法：

1. DailyPipeline 返回原有结果对象。
2. 运行时层在拿到结果后调用 build_selection_snapshot。
3. 运行时层再通过 SelectionArtifactWriter 写 snapshot 与 review。
4. 写入结果回填到事件流或 current_plan 元信息中。

这样 DailyPipeline 只承担“产出事实”的责任，不知道具体路径，也不关心 Markdown 格式。

### 7.3 不推荐的方案

不建议让 [src/execution/daily_pipeline.py](src/execution/daily_pipeline.py) 直接：

1. 拼接 report_dir。
2. 自己写 Markdown。
3. 感知 paper trading 和 backtesting 的目录差异。

这会把研究 artifact 与执行主链路耦合死，后续很难维护。

---

## 8. 运行目录与命名规范

### 8.1 目录优先级

1. 纸面交易运行时：写入对应 report_dir。
2. 回测运行时：写入对应 backtest report_dir。
3. 脱离运行时单独调用时：回退到 selection_artifacts/YYYY-MM-DD/run_id/。

### 8.2 建议文件布局

```text
reports/
  session_xxx/
    2026-03-22/
      selection_snapshot.json
      selection_review.md
      research_feedback.jsonl
```

### 8.3 命名规则

1. 所有 artifact 必须带 trade_date 维度。
2. run_id 必须全局唯一。
3. artifact_version 必须进入 snapshot 和 feedback。

---

## 9. 与现有事件流的衔接

### 9.1 current_plan / event 建议新增字段

为保证追溯性，建议在 current_plan 或 daily_events.jsonl 的对应事件中增加以下元信息：

```json
{
  "selection_artifacts": {
    "snapshot_path": ".../selection_snapshot.json",
    "review_path": ".../selection_review.md",
    "feedback_path": ".../research_feedback.jsonl",
    "artifact_version": "v1",
    "write_status": "success"
  }
}
```

### 9.2 写入失败状态

write_status 建议取值：

1. success
2. partial_success
3. failed

如果失败，必须同时附带 error_message，便于后续定位。

---

## 10. 具体改造步骤

### 10.1 第一步：定义模型与序列化

新增：

1. SelectionSnapshot
2. SelectedCandidate
3. RejectedCandidate
4. ResearchFeedbackRecord
5. SelectionArtifactWriteResult

目标：先把 schema 固化，不先动主流程。

### 10.2 第二步：从现有 pipeline result 提取快照

在运行时层接 DailyPipeline 结果后，将以下信息映射进 snapshot：

1. Layer B 分数与信号摘要。
2. Layer C 聚合结果。
3. watchlist。
4. buy_orders 与 sell_orders 的桥接信息。
5. funnel_diagnostics。
6. pipeline_config_snapshot。

### 10.3 第三步：写 snapshot 和 review

实现 SelectionArtifactWriter：

1. 先写 selection_snapshot.json。
2. 再从 snapshot 渲染 selection_review.md。
3. 如果 feedback 文件不存在，仅初始化空文件或延迟到首次写入时创建。

### 10.4 第四步：把路径回填事件流

将 artifact 元信息写入 current_plan 或 daily event，形成完整追溯链。

### 10.5 第五步：加入基础测试

至少增加：

1. snapshot schema 单测。
2. review 渲染快照测试。
3. writer 写入成功与失败降级测试。
4. 纸面交易集成测试。
5. 回测集成测试。

---

## 11. 测试设计

### 11.1 单元测试

建议新增测试文件：

1. [tests](tests)/research/test_selection_snapshot_models.py
2. [tests](tests)/research/test_selection_review_renderer.py
3. [tests](tests)/research/test_feedback_schema.py

重点检查：

1. 必填字段校验。
2. artifact_version 一致性。
3. JSON 序列化稳定性。
4. Markdown 渲染包含必要 section。

### 11.2 集成测试

建议新增：

1. [tests](tests)/paper_trading/test_selection_artifacts_in_runtime.py
2. [tests](tests)/backtesting/test_selection_artifacts_in_engine.py

重点检查：

1. 不影响原有 run 成功路径。
2. 运行后 artifact 文件确实落盘。
3. event / current_plan 中能找到对应路径。
4. writer 异常时主流程不被打断。

### 11.3 回归测试风险点

1. 大对象序列化导致 event 体积爆炸。
2. 路径生成与 report_dir 生命周期不一致。
3. 回测与纸面交易目录结构不同导致写入错位。
4. 同一天多次运行产生覆盖。

---

## 12. 标签治理设计

### 12.1 标签字典

建议同步新增一份受控标签字典文档，例如：

1. high_quality_selection
2. thesis_clear
3. crowded_trade_risk
4. weak_edge
5. threshold_false_negative
6. event_noise_suspected

### 12.2 治理规则

1. 新标签必须更新字典。
2. primary_tag 必须只有一个。
3. 标签语义变更必须提升 label_version。

---

## 13. 前瞻标签回灌预留位

虽然第一版不实现完整统计闭环，但 snapshot 必须预留后续挂接字段的能力。

建议后续统计脚本可补写 sidecar 或衍生文件，字段包括：

```json
{
  "symbol": "000001",
  "decision_timestamp": "2026-03-22T15:05:00+08:00",
  "forward_return_5d": 0.034,
  "forward_return_10d": 0.051,
  "benchmark_return_5d": 0.011,
  "alpha_5d": 0.023,
  "market_forward_label": "outperform_5d"
}
```

这里强调：

1. 收益窗口必须从 decision_timestamp 之后开始。
2. benchmark 定义必须固定。
3. 该标签与 research_verdict 严格分离。

---

## 14. 最小可交付版本

### 14.1 MVP 定义

如果目标是低复杂度高收益，第一版只需要满足：

1. 每日生成 snapshot。
2. 每日生成 review。
3. 可手工追加 feedback。
4. 可从 event 找回对应 artifact 路径。

### 14.2 不必等到第二版再做的内容

以下内容建议在第一版就做，因为成本低但收益高：

1. artifact_version。
2. pipeline_config_snapshot。
3. write_status。
4. near-miss rejected 样本记录。

---

## 15. 验收标准

本实施设计建议将验收拆成工程验收和研究可用性验收。

### 15.1 工程验收

1. 纸面交易和回测各完成至少一次成功落盘。
2. selection_snapshot.json 可以通过模型校验成功反序列化。
3. selection_review.md 与 snapshot 内容一致，没有额外杜撰字段。
4. event / current_plan 中存在 artifact 路径。
5. artifact 写入失败时主流程仍返回成功，但有清晰错误记录。

### 15.2 研究可用性验收

1. 研究员能在 5 分钟内完成当日 review 阅读。
2. 研究员能基于 feedback schema 完成结构化反馈。
3. 至少能够区分“入选质量问题”和“执行承接问题”。
4. 同一只股票的入选原因和落选原因具有可解释性。

---

## 16. 推荐实施顺序

1. 先落模型与 writer，不先碰复杂业务逻辑。
2. 先接 paper trading，再接 backtesting。
3. 先支持 watchlist review，再扩展 near-miss rejection review。
4. 先支持手工 feedback 文件，再考虑 UI 或数据库。

这个顺序的原因很直接：它能以最小风险把研究闭环跑起来，而不会把主交易系统卷进过度改造。

---

## 17. 最终建议

本方案的关键不是“再造一个报告系统”，而是在现有筛选与执行流水线之间插入一层稳定、低耦合、可追溯的研究 artifact 层。

第一版只要把以下三件事做对，后面就会越来越顺：

1. selection_snapshot.json 作为唯一事实源。
2. selection_review.md 作为统一人工审查视图。
3. research_feedback.jsonl 作为统一反馈入口。

只要这三个接口稳定下来，后续无论是统计回灌、标签学习、阈值复盘还是 UI 化审查，都会有清晰且可持续的演进路径。
