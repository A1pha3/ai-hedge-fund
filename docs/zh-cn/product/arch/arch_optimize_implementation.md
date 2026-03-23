# 选股优先优化方案实施设计文档

## 0. 当前落地状态

本文档已经不再只是实施提案。截至 2026-03-23，第一批代码骨架及其最小上层消费界面已落地，因此本文档需要同时承担两种职责：

1. 记录目标设计。
2. 记录当前已完成状态，避免文档与代码脱节。

当前已完成事项：

- 已新增 research artifact 模块：src/research/models.py、src/research/artifacts.py、src/research/review_renderer.py、src/research/feedback.py。
- 已在 src/backtesting/engine.py 中接入 selection_artifact_writer 注入点。
- 已在 src/paper_trading/runtime.py 中接入 FileSelectionArtifactWriter，并将产物写入 output_dir/selection_artifacts/。
- 已在 src/execution/models.py 中为 ExecutionPlan 增加 selection_artifacts 字段。
- 已在 src/execution/models.py 和 src/execution/layer_c_aggregator.py 中补通 Layer B strategy_signals 到 Layer C 结果的透传。
- 已补充 feedback 读取、聚合与标签治理骨架：支持受控标签校验、label_version 校验、JSONL 读取与汇总统计。
- 已新增最小 file-based feedback CLI：scripts/manage_research_feedback.py，支持 append 与 summarize 两个子命令。
- 已将 research_feedback_summary 自动接入 paper trading session_summary.json，并额外写出 selection_artifacts/research_feedback_summary.json。
- 已补齐 artifact 写入失败降级测试，并修正目录创建异常未进入 writer 降级路径的问题。
- 已补充基础测试，当前通过的文件包括：tests/research/test_selection_review_renderer.py、tests/research/test_selection_artifact_writer.py、tests/research/test_selection_artifact_engine.py、tests/research/test_feedback_schema.py、tests/research/test_manage_research_feedback_cli.py、tests/research/test_paper_trading_runtime_feedback_summary.py。
- 已补充轻量级运行级集成测试，覆盖现有 tests/backtesting/test_paper_trading_runtime.py 与 tests/backtesting/test_pipeline_mode.py 中 selection_artifacts 与 research_feedback_summary 的真实挂接断言。
- 已补充 watchlist 未承接 buy_order 时的执行阻塞原因透传，selection_snapshot.json 与 selection_review.md 现可展示 buy_order_blocker、reentry_review_until 等执行层约束信息。
- 已扩展现有 replay artifacts 后端/前端浏览面：后端可返回 selection_artifact_overview、按 trade_date 读取 selection snapshot/review，并支持以当前登录用户身份追加 research feedback；前端 Replay Artifacts 页面已可直接切换交易日查看 selection_review.md，结构化展示 selected/rejected、top_factors、Layer C analyst 共识、research prompts 与 execution blocker，并直接提交和筛选 research feedback，而无需手动翻 data/reports 目录或调用 CLI。
- 前端 Replay Artifacts 页面已进一步补齐 funnel_diagnostics 结构化 drilldown，可直接查看 layer_b、watchlist、buy_orders 三段过滤摘要、reason_counts 与代表性 ticker；feedback records 现按 created_at 倒序展示，并显式显示创建时间，便于研究员按时间线回看人工判断。
- Replay artifact 日级后端接口现已直接按 created_at 倒序返回 feedback_records，避免排序语义只存在于前端；localhost 环境下已完成一次真实登录、replay 列表、report/day detail、feedback append 与回读顺序校验的接口级冒烟验证。
- 已新增操作手册 [docs/zh-cn/manual/replay-artifacts-stock-selection-manual.md](docs/zh-cn/manual/replay-artifacts-stock-selection-manual.md)，面向已登录用户详细说明如何使用 Replay Artifacts 页面完成选股复核、执行阻塞分析、near-miss 排查与 research feedback 回写。
- 已补充配套文档 [docs/zh-cn/manual/replay-artifacts-stock-selection-quickstart.md](docs/zh-cn/manual/replay-artifacts-stock-selection-quickstart.md) 与 [docs/zh-cn/manual/replay-artifacts-case-study-20260311-300724.md](docs/zh-cn/manual/replay-artifacts-case-study-20260311-300724.md)，分别面向“快速上手”和“真实 blocker 样本判读”两类场景，降低从登录成功到形成稳定复核习惯之间的学习门槛。
- 已补充标签治理配套文档 [docs/zh-cn/manual/replay-artifacts-feedback-labeling-handbook.md](docs/zh-cn/manual/replay-artifacts-feedback-labeling-handbook.md)，统一说明 primary_tag、tags、review_status 与 research_verdict 的职责边界，以及 6 个受控标签在 selected、near-miss 和 execution blocker 场景中的使用口径，降低多人写 feedback 时的语义漂移风险。
- 已补充周度复盘工作流文档 [docs/zh-cn/manual/replay-artifacts-weekly-review-workflow.md](docs/zh-cn/manual/replay-artifacts-weekly-review-workflow.md)，将日常 `draft`、稳定 `final` 与争议样本 `adjudicated` 串成一套最小团队复盘节奏，便于将页面浏览、标签治理与后续系统优化 backlog 直接衔接。

当前尚未完成事项：

- research_feedback.jsonl 已具备最小读取、聚合、标签治理、CLI 操作、session 级 summary 接入以及 replay viewer 内最小可写 UI；但仍未接入数据库、批量标注工作台或更高层人工工作流编排。
- 轻量级 backtesting / paper trading 运行级集成测试已补齐，且更长窗口 frozen replay 验证已完成一次，但真实 live pipeline 与更高层人工工作流集成仍未完成。
- 历史 frozen replay 源的 Layer B 解释已补齐回退兼容，但回退摘要只能基于 plan.logic_scores 与 strategy_weights 或 adjusted_weights 近似重建，精度仍低于新源中的原生 strategy_signals。

### 0.1 已完成验收记录

2026-03-22 已完成一次最小真实落盘验收，验证方式为 2 天 frozen replay paper trading：

1. frozen_plan_source：data/reports/paper_trading_probe_20260224_20260225/daily_events.jsonl
2. output_dir：data/reports/paper_trading_probe_20260224_20260225_selection_artifact_validation_20260322
3. 成功生成 session_summary.json、daily_events.jsonl、pipeline_timings.jsonl 和 selection_artifacts/ 日期目录。
4. 2026-02-24 与 2026-02-25 两个交易日均成功生成 selection_snapshot.json、selection_review.md、research_feedback.jsonl。
5. session_summary.json 已记录 selection_artifact_root。
6. daily_events.jsonl 与 pipeline_timings.jsonl 中的 current_plan 均已包含 selection_artifacts 元信息。

这次验证的意义是确认“真实运行路径下 artifact 确实落盘且能回填事件流”，而不是验证选股效果本身。由于该样本窗口中 watchlist 为空，本次验收更偏向工程链路验收，而非研究可用性上限验收。

2026-03-22 还完成了一次“非空 watchlist 场景”验收，验证方式为 1 天 frozen replay paper trading：

1. frozen_plan_source：data/reports/logic_stop_threshold_scan_m0_20/daily_events.jsonl
2. output_dir：data/reports/logic_stop_threshold_scan_m0_20_selection_artifact_validation_20260322
3. 成功生成 2026-02-05 对应的 selection_snapshot.json、selection_review.md、research_feedback.jsonl。
4. selection_review.md 已正确展示 1 个入选股票、buy_order 桥接信息以及研究复核提示。
5. daily_events.jsonl 与 pipeline_timings.jsonl 中的 selection_artifacts 仍为 write_status=success。
6. 该窗口确认当前 artifact 已具备基本研究可读性，而不只是工程链路可用。

2026-03-22 随后完成了一次“历史 replay 兼容回退”验收，仍使用 1 天 frozen replay paper trading：

1. frozen_plan_source：data/reports/logic_stop_threshold_scan_m0_20/daily_events.jsonl
2. output_dir：data/reports/logic_stop_threshold_scan_m0_20_selection_artifact_fallback_validation_20260322
3. selection_snapshot.json 中的 layer_b_summary 已不再为空，而是使用 plan.logic_scores 与 market_state.adjusted_weights 回退生成 top_factors，并标记 explanation_source=legacy_plan_fields。
4. selection_review.md 已新增 Layer B 因子摘要区块，可直接看到 logic_score、fundamental、trend 等回退解释项。
5. session_summary.json、daily_events.jsonl、pipeline_timings.jsonl 中的 artifact 元信息仍保持 write_status=success。

这次验收说明：历史 frozen replay 源的 Layer B 解释不再是“空白”，但因为老源缺失原生 strategy_signals，回退摘要本质上仍是兼容解释而不是原始策略证据，研究员在复核时应优先将其视为辅助线索。

2026-03-22 同日还完成了 research_feedback.jsonl 的最小闭环实现：

1. 新增受控标签词表与 label_version=v1 校验。
2. 新增 review_status 受控枚举校验，当前支持 draft、final、adjudicated。
3. 新增 JSONL 读取函数与汇总聚合函数，可统计 primary_tag、tags、review_status、research_verdict、reviewer、symbol 等维度。
4. 新增 tests/research/test_feedback_schema.py，覆盖正常读写、聚合统计、非法标签拦截与 skip_invalid 路径。
5. 与 selection artifact 相关测试合并运行后已通过，共 7 个测试通过。

2026-03-22 同日还完成了最小 feedback CLI 集成：

1. 新增 scripts/manage_research_feedback.py，支持 append 与 summarize 子命令。
2. summarize 支持直接指定 feedback 文件，或基于 selection_artifacts 根目录加 trade_date 自动定位 research_feedback.jsonl。
3. append 支持从命令行直接录入 reviewer、primary_tag、tags、review_status、confidence、research_verdict、notes 等核心字段。
4. 新增 tests/research/test_manage_research_feedback_cli.py，覆盖路径解析与 append/summarize 命令闭环。
5. 与既有 research 测试合并运行后已通过，共 9 个测试通过；并已在现有 selection_artifacts 目录上完成一次 summarize 实际命令验证。

2026-03-22 同日还完成了 feedback summary 的运行时接入：

1. 新增目录级聚合能力，可扫描 selection_artifacts/*/research_feedback.jsonl 并生成按 trade_date 拆分的汇总。
2. paper trading 运行结束后会自动写出 selection_artifacts/research_feedback_summary.json。
3. session_summary.json 现已包含 research_feedback_summary 摘要内容，以及 artifacts.research_feedback_summary 文件路径。
4. 新增 tests/research/test_paper_trading_runtime_feedback_summary.py，覆盖 summary 文件写出路径。
5. 与既有 research 测试合并运行后已通过，共 11 个测试通过；并已通过 1 天 frozen replay 在真实 output_dir 中验证 summary 文件和 session_summary 挂接成功。

2026-03-22 同日还完成了 artifact 失败降级边界补强：

1. 修正 FileSelectionArtifactWriter 中目录创建位于 try 之外的问题，避免部分文件系统异常绕过降级返回。
2. 新增 partial_success 路径测试，覆盖 review 与 feedback 已生成但 snapshot 写入失败的场景。
3. 新增 failed 路径测试，覆盖目录创建失败导致三个 artifact 都未生成的场景。
4. 新增引擎级异常降级测试，覆盖 writer 抛出异常时 plan.selection_artifacts 仍能回填 write_status=failed 与 error_message。
5. 与既有 research 测试合并运行后已通过，共 15 个测试通过。

2026-03-22 同日继续补齐了轻量级运行级集成测试：

1. 在 tests/backtesting/test_paper_trading_runtime.py 中新增断言，验证 session_summary.json 中的 artifacts.selection_artifact_root、artifacts.research_feedback_summary 与内联 research_feedback_summary 已成功挂接。
2. 同一测试中新增对 daily_events.jsonl 与 pipeline_timings.jsonl 的校验，确认 current_plan.selection_artifacts.write_status=success 已进入真实 paper trading 运行输出。
3. 在 tests/backtesting/test_pipeline_mode.py 中新增 pipeline mode 运行级断言，确认 pipeline_event_recorder、checkpoint.timings.jsonl 与 selection_artifacts/日期目录之间保持一致。
4. 运行 tests/backtesting/test_paper_trading_runtime.py 与 tests/backtesting/test_pipeline_mode.py 后共 12 个测试通过。
5. 这轮测试说明最小 runtime 路径已经从“单元与引擎级可用”推进到“paper trading/backtesting 现有测试骨架下可观测输出一致”。

2026-03-23 已完成一次“更长窗口 frozen replay”验收，并顺带补强了 execution blocker 的研究可解释性：

1. frozen_plan_source：data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319/daily_events.jsonl。
2. output_dir：data/reports/paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323。
3. 共生成 24 个 trade_date 子目录和 1 个 selection_artifacts/research_feedback_summary.json，session_summary.json 中也同步记录了 selection_artifact_root 与 research_feedback_summary。
4. pipeline_timings.jsonl 与 daily_events.jsonl 中每个 trade_date 的 current_plan.selection_artifacts 均保持 write_status=success。
5. 这次长窗口验证说明 selection artifact 机制不仅在 1 到 2 天样本中可用，在 W1 级别多日 replay 中也能稳定落盘与回填。

2026-03-23 同日还补齐了 watchlist 未承接 buy_order 的执行阻塞原因透传：

1. selected[*].execution_bridge 新增 block_reason、blocked_until、reentry_review_until、exit_trade_date、trigger_reason 等字段。
2. selection_review.md 现会直接展示 buy_order_blocker 与 reentry_review_until，避免研究员只能看到“watchlist=1, buy_order=0”但不知道阻塞原因。
3. 已通过单日真实 frozen replay 验证 2026-03-11 场景：300724 因 blocked_by_reentry_score_confirmation 未生成 buy_order，同时 review 中已出现对应 blocker 提示。
4. tests/research 全量回归已重新运行通过，共 15 个测试通过。

2026-03-23 同日还完成了 replay viewer 的一轮前端可用性补强与构建验收：

1. Replay Artifacts 页面新增 Funnel Drilldown 区块，直接展示 selection_snapshot.funnel_diagnostics.filters.layer_b、watchlist、buy_orders 的 filtered_count、reason_counts 与代表性 ticker 行。
2. feedback records 表格改为按 created_at 倒序展示，并新增创建时间列，降低研究员按时间线回看反馈时对原始 JSONL 的依赖。
3. app/frontend 执行 npm run build 已通过，说明上述 viewer 增强未破坏现有 TypeScript 类型和生产构建链路。

2026-03-23 同日还完成了一轮本地接口级冒烟验收与服务层一致性补强：

1. 在 localhost 环境下完成了 auth/login、GET /replay-artifacts/、GET /replay-artifacts/{report_name}、GET /replay-artifacts/{report_name}/selection-artifacts/{trade_date} 与 POST /replay-artifacts/{report_name}/selection-artifacts/{trade_date}/feedback 的真实调用验证。
2. 已确认 selection artifact 日级接口可返回 funnel_diagnostics.filters.layer_b、watchlist、buy_orders，能支撑前端 Funnel Drilldown 区块直接消费。
3. 已将 feedback_records 的 created_at 倒序语义下沉到后端 ReplayArtifactService，避免只有前端页面能看到正确顺序。
4. tests/backend/test_replay_artifact_service.py 已新增对应断言并重新运行通过。

后续章节中，凡是“建议”“推荐”与“已实现”不一致时，以“已实现”说明为准，并在后续迭代中继续向目标态收敛。

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
  负责每日筛选与执行准备主流程，是 selection_snapshot 的事实来源，但当前首版实现并不在此文件直接写 artifact。
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

当前状态：上述 research 子包方案已经落地，后续应继续沿用，不再建议回退到 src/execution/selection_artifacts.py 的混合方案。

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

### 7.1 当前首版接口

```python
class SelectionArtifactWriter(Protocol):
  def write_for_plan(
    self,
    *,
    plan: ExecutionPlan,
    trade_date: str,
    pipeline: DailyPipeline | None,
    selected_analysts: list[str] | None,
  ) -> SelectionArtifactWriteResult:
        ...


def build_selection_snapshot(
    *,
  plan: ExecutionPlan,
  trade_date: str,
    run_id: str,
  pipeline: DailyPipeline | None,
  selected_analysts: list[str] | None,
  experiment_id: str | None = None,
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


def read_research_feedback(
  *,
  file_path: Path,
  skip_invalid: bool = False,
) -> list[ResearchFeedbackRecord]:
  ...


def summarize_research_feedback(
  *,
  records: list[ResearchFeedbackRecord] | None = None,
  file_path: Path | None = None,
  skip_invalid: bool = False,
) -> ResearchFeedbackSummary:
  ...


def summarize_research_feedback_directory(
  *,
  artifact_root: Path,
  skip_invalid: bool = False,
) -> ResearchFeedbackDirectorySummary:
  ...
```

说明：

1. 当前实现使用 write_for_plan，而不是先手工构造 snapshot 再调用 write_selection_artifacts。
2. 这是为了减少运行时层样板代码，并把 snapshot 构造和文件落盘集中在同一个 writer 编排模块中。
3. 后续如果要进一步解耦，可以再演进为“builder + writer”双对象模式，但第一版没有必要为了形式完整而增加复杂度。

### 7.2 推荐集成方式

推荐使用 writer 注入模式。

具体做法：

1. DailyPipeline 返回原有结果对象。
2. 运行时层在拿到结果后调用 writer，由 writer 内部完成 snapshot 构建与 review 渲染。
3. 写入结果回填到事件流或 current_plan 元信息中。

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
    selection_artifacts/
      2026-03-22/
        selection_snapshot.json
        selection_review.md
        research_feedback.jsonl
```

当前状态：首版代码已经按上述 selection_artifacts 子目录结构落地。

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

当前状态：

1. ExecutionPlan 已新增 selection_artifacts 字段。
2. backtesting timing payload 中的 current_plan 已包含 selection_artifacts 元信息。
3. daily_events.jsonl 中的 current_plan 会随 model_dump 一并带出 selection_artifacts。

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

当前状态：已完成。

### 10.2 第二步：从现有 pipeline result 提取快照

在运行时层接 DailyPipeline 结果后，将以下信息映射进 snapshot：

1. Layer B 分数与信号摘要。
2. Layer C 聚合结果。
3. watchlist。
4. buy_orders 与 sell_orders 的桥接信息。
5. funnel_diagnostics。
6. pipeline_config_snapshot。

当前状态：已完成首版。

当前实现说明：

1. 实际提取入口是运行时层持有的 ExecutionPlan，而不是单独定义一个 DailyPipelineResult。
2. Layer B 信号解释通过 LayerCResult.strategy_signals 透传获得。
3. near-miss rejected 样本当前来自 funnel_diagnostics.filters.watchlist。

### 10.3 第三步：写 snapshot 和 review

实现 SelectionArtifactWriter：

1. 先写 selection_snapshot.json。
2. 再从 snapshot 渲染 selection_review.md。
3. 如果 feedback 文件不存在，仅初始化空文件或延迟到首次写入时创建。

当前状态：已完成。

### 10.4 第四步：把路径回填事件流

将 artifact 元信息写入 current_plan 或 daily event，形成完整追溯链。

当前状态：已完成首版。

### 10.5 第五步：加入基础测试

至少增加：

1. snapshot schema 单测。
2. review 渲染快照测试。
3. writer 写入成功与失败降级测试。
4. 纸面交易集成测试。
5. 回测集成测试。

当前状态：部分完成。

已完成：

1. review 渲染测试。
2. writer 写入测试。
3. 引擎回填 selection_artifacts 测试。
4. feedback schema 读写与聚合测试。
5. feedback CLI 路径解析与 append or summarize 命令测试。
6. session 级 feedback summary 写出测试。
7. artifact 写入失败降级测试。
8. watchlist 已入选但 buy_order 被执行层规则阻塞时的 blocker 透传测试。

未完成：

1. 真实 live pipeline 集成测试。
2. 真实 backtesting 的更长窗口运行级集成测试。
3. feedback 与更高层人工工作流、标签平台或 UI 的集成测试。

---

## 11. 测试设计

### 11.1 单元测试

建议新增测试文件：

1. [tests](tests)/research/test_selection_snapshot_models.py
2. [tests](tests)/research/test_selection_review_renderer.py
3. [tests](tests)/research/test_feedback_schema.py
4. [tests](tests)/research/test_selection_artifact_writer.py
5. [tests](tests)/research/test_selection_artifact_engine.py

重点检查：

1. 必填字段校验。
2. artifact_version 一致性。
3. JSON 序列化稳定性。
4. Markdown 渲染包含必要 section。

### 11.2 集成测试

建议新增：

1. [tests](tests)/paper_trading/test_selection_artifacts_in_runtime.py
2. [tests](tests)/backtesting/test_selection_artifacts_in_engine.py

当前状态：

1. tests/research/test_selection_artifact_engine.py 已经覆盖了“引擎将 selection_artifacts 回填到 plan”的最小集成路径。
2. tests/backtesting/test_paper_trading_runtime.py 已补充 selection_artifacts 与 research_feedback_summary 的运行输出断言。
3. tests/backtesting/test_pipeline_mode.py 已补充 pipeline mode 下 event、timing log 与 artifact 落盘的一致性断言。
4. 上述两组 backtesting runtime 测试已在 2026-03-22 合并运行通过，共 12 个测试通过。
5. 真实 paper trading 短窗口 frozen replay 验证已完成一次。
6. 非空 watchlist 场景的 frozen replay 验证也已完成一次。
7. 更长窗口 frozen replay 验证已在 2026-03-23 完成一次，覆盖 W1 级别 24 个 trade_date 的 artifact 连续落盘与 summary 聚合。
8. 但这仍然不能替代真实 live pipeline 的运行级验收。

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

当前完成度：

1. 第 1、2、3、4 项已经具备基础代码、测试或最小真实运行验证支撑。
2. 第 5 项已具备失败降级实现与显式异常测试支撑，包括 partial_success、failed 和引擎级异常降级路径。

补充说明：当前第 3 项“selection_review.md 与 snapshot 内容一致”已经通过非空 watchlist 窗口与历史 replay 回退窗口得到更强验证；旧 frozen 源下虽然缺少原生 strategy_signals，但 review 已能显示兼容回退后的 Layer B 摘要。

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
