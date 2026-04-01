# 双目标系统实施与代码改造计划

> 文档元信息
>
> - 首次创建日期：2026-03-28
> - 最近更新时间：2026-03-29 22:10:00 CST
> - 当前目录：docs/zh-cn/product/arch/dual_target_system/
> 当前状态
>
> - 状态：已从施工前计划升级为“实施计划 + 落地状态对照”文档
> - 核心判断：Phase 1-6 主链路已基本落地，但文档此前未同步回写，且仍存在少量后续整理项
> - 本次更新范围：修正错误链接、修正过期结论、重写测试矩阵、补充 Explainability 与 profile 抽象缺口审查

## 0. 文档定位

本文档最初是双目标文档包的施工图版本；截至本次更新，它同时承担“施工顺序记录 + 当前落地状态对照”的作用，承接以下文档：

1. [双目标选股与交易目标系统架构设计文档](./arch_dual_target_selection_system.md)
2. [次日短线目标指标与验证方案](./short_trade_target_metrics_and_validation.md)
3. [次日短线目标首版规则集规格](./short_trade_target_rule_spec.md)
4. [双目标系统数据结构与 Artifact Schema 规格](./dual_target_data_contract_and_artifact_schema.md)

本文档只回答实施问题：

1. 先改哪些文件
2. 每一步改动的目标是什么
3. 哪些改动必须增量兼容
4. 每一阶段的验证和回归要求是什么

本文档的用途不是替代代码实现，而是：

1. 记录双目标系统的原始施工顺序
2. 对照当前代码说明哪些阶段已经落地
3. 把剩余缺口收敛为有限优化项，避免后续继续基于过期认知发散

---

## 1. 实施总原则

### 1.1 先 artifacts，后 execution semantics

双目标系统的第一阶段不应该先改买卖逻辑，而应该先把目标层结果接入 artifacts、review 和 summary。

原因：

1. artifacts 是现有系统最稳的观察面
2. replay / review / feedback 已经具备真实闭环
3. 先在 artifacts 层看双目标差异，风险远低于直接动订单逻辑

### 1.2 仅研究模式（`research_only`）兼容必须零回归

在任何阶段，默认的仅研究模式（`research_only`）行为都不允许退化。

最小要求：

1. 现有 selection_artifacts 不丢字段
2. 现有 selection_review.md 不断链
3. 现有 session_summary / daily_events / pipeline_timings 不断链
4. 现有 Replay Artifacts 页面可继续消费旧字段

### 1.3 先冻结字段，再接业务规则

实现顺序必须是：

1. 目标模型
2. artifact 透传
3. renderer 扩展
4. summary 聚合
5. short trade 规则计算
6. 后续再考虑 entry plan 与执行层承接

### 1.4 每一阶段都必须可回滚

每一阶段都应做到：

1. feature flag 或运行模式可关闭
2. schema 为增量字段，不破坏旧消费方
3. 验证失败时可快速回退到仅研究模式（`research_only`）

---

## 2. 当前代码落点与改造责任区

### 2.1 流程主入口

#### [src/execution/daily_pipeline.py](src/execution/daily_pipeline.py)

职责：

1. 生成 Layer A / B / C 主链路结果
2. 形成 `ExecutionPlan`
3. 记录风险诊断和 funnel 信息

双目标阶段的责任：

1. 提供目标层所需基础事实
2. 在不破坏现有主逻辑的前提下接入 target router
3. 透传 `selection_targets` / `target_summary` 到 `ExecutionPlan`

#### [src/paper_trading/runtime.py](src/paper_trading/runtime.py)

职责：

1. 写出 `daily_events.jsonl`
2. 写出 `pipeline_timings.jsonl`
3. 写出 `session_summary.json`
4. 组织 `selection_artifacts`

双目标阶段的责任：

1. 把目标维度摘要接入 session summary
2. 把 dual-target artifacts 与 report 输出绑定

#### [src/backtesting/engine.py](src/backtesting/engine.py)

职责：

1. 统一驱动 pipeline/backtest 循环
2. 注入 `SelectionArtifactWriter`
3. 负责 checkpoint 与事件写出

双目标阶段的责任：

1. 把 `target_mode` 与 `selection_targets` 传入 artifact writer
2. 保证 frozen replay 与 live pipeline 都能稳定写出双目标 artifact

### 2.2 现有 research artifact 入口

#### [src/research/models.py](src/research/models.py)

双目标阶段的责任：

1. 增量扩展 `SelectionSnapshot`
2. 增量扩展 `SelectedCandidate` / `RejectedCandidate`
3. 在保持兼容的前提下承接 target context

#### [src/research/artifacts.py](src/research/artifacts.py)

双目标阶段的责任：

1. 在 `build_selection_snapshot()` 中接入双目标结果
2. 在 `FileSelectionArtifactWriter.write_for_plan()` 中透传新增 schema
3. 维持旧 snapshot / review 结构可读

#### [src/research/review_renderer.py](src/research/review_renderer.py)

双目标阶段的责任：

1. 增加 Research Target Summary
2. 增加 Short Trade Target Summary
3. 增加 Target Delta Highlights

### 2.3 执行模型

#### [src/execution/models.py](src/execution/models.py)

双目标阶段的责任：

1. 增量扩展 `ExecutionPlan`
2. 增加 `selection_targets`
3. 增加 `target_mode`
4. 增加 `dual_target_summary`

### 2.4 目标模块目录现状

当前已存在：

1. `src/targets/models.py`
2. `src/targets/research_target.py`
3. `src/targets/short_trade_target.py`
4. `src/targets/router.py`
5. `src/targets/explainability.py`

当前未独立落地：

1. `src/targets/profiles.py`

说明：

1. 双目标主施工区已经形成
2. short trade 首版规则已经在 `short_trade_target.py` 中实现
3. profile 抽象尚未拆成独立模块，这是当前最明确的结构整理缺口之一

---

## 3. 分阶段实施顺序

建议严格分为 6 个阶段。

### Phase 1：模型冻结与空壳接线

状态：已完成

目标：

1. 增加目标层模型
2. 不改变业务行为
3. 不增加真实 short trade 规则

改动文件建议：

1. 新增 `src/targets/models.py`
2. 新增 `src/targets/router.py`
3. 轻量修改 [src/execution/models.py](src/execution/models.py)

阶段产物：

1. `TargetEvaluationInput`
2. `TargetEvaluationResult`
3. `DualTargetEvaluation`
4. `ExecutionPlan` 能容纳 `selection_targets` 和 `target_mode`

验收标准：

1. 仅研究模式（`research_only`）默认行为完全不变
2. 新字段为空时不影响现有逻辑
3. 现有测试无回归

当前落地说明：

1. `src/targets/models.py` 已定义 `TargetEvaluationInput`、`TargetEvaluationResult`、`DualTargetEvaluation`、`DualTargetSummary`
2. `src/execution/models.py` 已为 `ExecutionPlan` 增加 `selection_targets`、`target_mode`、`dual_target_summary`
3. 新增字段均带默认值，旧 payload 可兼容反序列化

### Phase 2：artifact 透传

状态：已完成

目标：

1. 把目标层字段写入 `selection_snapshot.json`
2. 把目标摘要写入 `session_summary.json` / `daily_events.jsonl`

改动文件建议：

1. [src/research/models.py](src/research/models.py)
2. [src/research/artifacts.py](src/research/artifacts.py)
3. [src/paper_trading/runtime.py](src/paper_trading/runtime.py)
4. [src/backtesting/engine.py](src/backtesting/engine.py)

阶段产物：

1. `selection_targets`
2. `target_summary`
3. `dual_target_delta`

验收标准：

1. 双目标字段能稳定落盘
2. 旧 report 读取不受影响
3. live pipeline / frozen replay 都能写出新增字段

当前落地说明：

1. `SelectionSnapshot` 已承接 `selection_targets`、`target_summary`、`research_view`、`short_trade_view`、`dual_target_delta`
2. `FileSelectionArtifactWriter.write_for_plan()` 已将双目标字段写入 snapshot / review / replay input
3. `src/paper_trading/runtime.py` 已把 `dual_target_summary` 聚合进 `session_summary.json`
4. `daily_events.jsonl` 与 `pipeline_timings.jsonl` 已透传 `current_plan.target_mode` 与 `current_plan.dual_target_summary`

### Phase 3：review renderer 扩展

状态：已完成

目标：

1. 让研究员在 markdown 中直接看见 research 与 short trade 差异

改动文件建议：

1. [src/research/review_renderer.py](src/research/review_renderer.py)

阶段产物：

1. Research Target Summary
2. Short Trade Target Summary
3. Delta Highlights

验收标准：

1. 没有双目标字段时，旧 review 样式仍可正常渲染
2. 有双目标字段时，review 内容清晰且不膨胀

当前落地说明：

1. `src/research/review_renderer.py` 已渲染 Research Target Summary
2. 已渲染 Short Trade Target Summary
3. 已渲染 Target Delta Highlights
4. 现有渲染测试已覆盖双目标摘要与兼容场景

### Phase 4：research target wrapper 与 short trade skeleton

状态：已完成，但 short trade 已超过 skeleton 阶段

目标：

1. 正式接入目标模块层
2. 先实现 research wrapper
3. 再实现 short trade skeleton，但先不接复杂规则

改动文件建议：

1. 新增 `src/targets/research_target.py`
2. 新增 `src/targets/short_trade_target.py`
3. 新增 `src/targets/explainability.py`
4. 轻量修改 [src/execution/daily_pipeline.py](src/execution/daily_pipeline.py)

阶段产物：

1. 仅研究模式（`research_only`）
2. 仅短线模式（`short_trade_only`）
3. 双目标模式（`dual_target`）

验收标准：

1. research target 输出与旧研究主语义一致
2. short trade skeleton 可以输出占位结果
3. 双目标模式（`dual_target`）能稳定写出 artifacts

当前落地说明：

1. `src/targets/router.py` 已通过 `build_selection_targets()` 在“仅研究模式（`research_only`）”“仅短线模式（`short_trade_only`）”“双目标模式（`dual_target`）”三种模式下组装目标结果
2. `src/execution/daily_pipeline.py` 已在 live pipeline 和 frozen plan shell 两条路径挂接目标路由
3. 当前 short trade 实现已经不是纯占位 skeleton，而是具备真实分数、gate、blockers、tags 的首版规则实现

### Phase 5：short trade 首版规则接入

状态：已基本完成，剩余 profile 模块化与参数治理未完成

目标：

1. 接入规则规格文档中的首版因子、分数与 gate

改动文件建议：

1. `src/targets/short_trade_target.py`
2. `src/targets/profiles.py`
3. 必要时新增辅助特征提取模块

阶段产物：

1. default / conservative / aggressive profile
2. short trade target explainability
3. blockers / tags 输出

验收标准：

1. hard gate 与 soft gate 顺序符合文档
2. selected / rejected / blocked 行为可解释
3. 单测与 replay 验证通过

当前落地说明：

1. `src/targets/short_trade_target.py` 已实现首版分数、gate、blockers、tags、`metrics_payload`、`explainability_payload`
2. 目标行为已经进入 replay 校准与 diagnostics 阶段
3. 尚未独立实现 `src/targets/profiles.py`
4. `default / conservative / aggressive` 仍主要停留在文档规格与后续参数治理层面，不应再表述为当前已完成的代码交付物

### Phase 6：工作台消费与试运行

状态：已形成试运行基线

目标：

1. 让 Replay Artifacts 能消费双目标结构
2. 让研究员能真实评审 dual-target report

改动文件建议：

1. 后端 replay artifact service / routes
2. 前端 Replay Artifacts 工作台组件

阶段产物：

1. Research View
2. Short Trade View
3. Delta View

验收标准：

1. report 详情可展示双目标差异
2. feedback 能携带 target context
3. UI 不破坏现有研究工作流

当前落地说明：

1. 后端 Replay Artifact Service 已生成 `trade_date_target_index` 与 `dual_target_overview`
2. 前端 Replay Artifacts 工作台已支持 report 级与 trade-date 级 dual-target 过滤和详情展示
3. feedback workflow 已带上 `review_scope`，并能沿用现有研究反馈主线
4. 当前更准确的表述应为“进入试运行与增量优化阶段”，而不是“尚待开始接 UI 消费”

---

## 4. 测试矩阵（已覆盖 / 待补强）

### 4.1 Phase 1-2

已覆盖：

1. targets models 单元测试
2. selection_snapshot schema 扩展测试
3. session_summary / daily_events 双目标字段挂接测试

对应测试：

1. `tests/targets/test_target_models.py`
2. `tests/research/test_selection_artifact_writer.py`
3. `tests/backtesting/test_paper_trading_runtime.py`

### 4.2 Phase 3

已覆盖：

1. review renderer 双目标渲染测试
2. 旧 snapshot 向后兼容渲染测试

对应测试：

1. `tests/research/test_selection_review_renderer.py`

### 4.3 Phase 4-5

已覆盖：

1. research wrapper 一致性测试
2. short trade gate 顺序测试
3. explainability tags / blockers 输出测试
4. 双目标模式（`dual_target`）运行测试

对应测试：

1. `tests/targets/test_target_models.py`
2. `tests/execution/test_phase4_execution.py`
3. `tests/test_replay_selection_target_calibration_script.py`

待补强：

1. profile 抽象不存在时的参数治理测试
2. Explainability payload 的端到端消费测试
3. 规则参数切换与 CLI / workspace 接口联动测试

### 4.4 Phase 6

已覆盖：

1. replay artifact backend 路由测试
2. 前端 dual-target 视图测试
3. 必要的 smoke / workflow 回归

对应测试：

1. `tests/backend/test_replay_artifact_service.py`
2. `tests/backend/test_replay_artifact_routes.py`
3. `app/frontend/src/components/replay-artifacts/replay-artifacts-inspector.test.tsx`
4. `app/frontend/src/components/settings/replay-artifacts.test.tsx`

待补强：

1. Explainability 明细视图测试
2. profile 参数在工作台中的展示与切换测试
3. 更贴近真实报表样本的试运行 smoke 回归

---

## 5. 回归风险与控制点

### 5.1 最大风险

最大的不是 short trade 规则错，而是：

1. schema 扩展破坏现有 artifacts
2. review renderer 让旧 report 无法渲染
3. 双目标字段污染仅研究模式（`research_only`）默认流程

### 5.2 控制策略

建议每一阶段都遵守：

1. 新字段默认可空
2. 新模式默认关闭
3. 旧测试必须全绿
4. 先 frozen replay，再 live pipeline smoke

---

## 6. 与 arch_optimize_implementation 的关系

这份文档与 [arch_optimize_implementation.md](../arch_optimize_implementation.md) 的关系是：

1. `arch_optimize_implementation.md` 记录的是 research artifact 主线已经落地的实施经验
2. 本文档是在那个落地基线上，规划双目标系统的下一阶段施工顺序

也就是说，双目标实施不应绕开现有 research artifact 主线，而应复用它：

1. 复用 `src/research/models.py`
2. 复用 `src/research/artifacts.py`
3. 复用 Replay Artifacts 作为第一观察面

---

## 7. 当前实现状态与最近应做事项

截至本次更新，最初建议的“第一阶段开工小步”已经完成：

1. `src/targets/models.py` 已存在
2. `ExecutionPlan` 已完成增量扩展
3. `SelectionSnapshot` 已完成增量扩展
4. artifact writer 已能稳定写出 `selection_targets`

因此，当前不再建议把精力投入到重复搭建基础接线，而应优先做下面三类工作：

1. 把文档体系从“施工前叙事”修正为“状态化实施记录”
2. 把 profile 抽象与参数治理从规则实现中拆分出来
3. 把 Explainability 从数据契约层推进到真实工作台消费层

## 8. 当前建议结论

双目标系统现在已经具备：

1. 模型与 schema
2. artifacts / review / session summary 主链路
3. target router 与三种 target mode
4. short trade 首版规则
5. Replay Artifacts 前后端消费基线

当前最合理的动作不再是重新按 6 个阶段从头施工，而是进入“试运行 + 结构整理 + 可解释性补强”阶段：

1. 先修正文档与测试矩阵，防止后续继续基于过期认知讨论
2. 再收敛 profile 抽象、参数治理与 CLI / workspace 对齐
3. 再补 Explainability 工作台消费与真实报表反馈闭环

这条路线更符合当前仓库的真实状态，也能避免重复做已经完成的基础工作。

## 9. 第二轮审查：Explainability 与 profile 抽象缺口

### 9.1 Explainability 当前状态

已落地：

1. `TargetEvaluationResult` 已包含 `metrics_payload` 与 `explainability_payload`
2. `src/targets/short_trade_target.py` 已输出 short trade 分数构成、penalty、thresholds 等解释字段
3. 前端 API 类型已保留 `expected_holding_window`、`preferred_entry_mode`、`metrics_payload`、`explainability_payload`

未完全落地：

1. Replay Artifacts 工作台当前主要消费 summary / delta / representative cases
2. Explainability payload 还没有形成稳定的明细视图与交互入口
3. 缺少“研究员如何使用 explainability 进行反馈标注”的工作流说明

结论：

1. Explainability 已到“数据契约与后端输出就绪”阶段
2. 尚未达到“完整产品能力”阶段
3. 后续应把它视为工作台增强项，而不是继续归类为 Phase 5 基础实现

### 9.2 profile 抽象当前状态

已落地：

1. 文档规格中已定义 `default / conservative / aggressive` 的概念
2. 当前 replay 校准与 diagnostics 已在做参数探索

未落地：

1. `src/targets/profiles.py` 当前不存在
2. 参数档位尚未收敛为独立、可切换、可测试的 profile 配置层
3. `--short-trade-profile` 这一类面向运行入口的稳定接口尚未在当前实现中形成清晰主线

结论：

1. profile 抽象是当前最明确的结构整理缺口
2. 它不影响“short trade 首版规则已存在”这一事实
3. 但它会影响后续参数治理、可回放性和规则切换的一致性

### 9.3 建议的后续优先级

1. 先完成文档与测试矩阵校正
2. 再抽离 profile 配置层
3. 最后把 Explainability 做成工作台可消费的明细体验
