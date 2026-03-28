# 双目标系统实施与代码改造计划

## 0. 文档定位

本文档是双目标文档包的施工图版本，承接以下文档：

1. [双目标选股与交易目标系统架构设计文档](./arch_dual_target_selection_system.md)
2. [次日短线目标指标与验证方案](./short_trade_target_metrics_and_validation.md)
3. [次日短线目标首版规则集规格](./short_trade_target_rule_spec.md)
4. [双目标系统数据结构与 Artifact Schema 规格](./dual_target_data_contract_and_artifact_schema.md)

本文档只回答实施问题：

1. 先改哪些文件
2. 每一步改动的目标是什么
3. 哪些改动必须增量兼容
4. 每一阶段的验证和回归要求是什么

本文档的用途不是替代代码实现，而是防止在真正开始改代码时重新发散。

---

## 1. 实施总原则

### 1.1 先 artifacts，后 execution semantics

双目标系统的第一阶段不应该先改买卖逻辑，而应该先把目标层结果接入 artifacts、review 和 summary。

原因：

1. artifacts 是现有系统最稳的观察面
2. replay / review / feedback 已经具备真实闭环
3. 先在 artifacts 层看双目标差异，风险远低于直接动订单逻辑

### 1.2 research_only 兼容必须零回归

在任何阶段，默认 research_only 行为都不允许退化。

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
3. 验证失败时可快速回退到 research_only

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

### 2.4 新增目标模块目录

建议新增：

1. `src/targets/models.py`
2. `src/targets/research_target.py`
3. `src/targets/short_trade_target.py`
4. `src/targets/router.py`
5. `src/targets/explainability.py`
6. `src/targets/profiles.py`

这是双目标代码主施工区。

---

## 3. 分阶段实施顺序

建议严格分为 6 个阶段。

### Phase 1：模型冻结与空壳接线

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

1. research_only 默认行为完全不变
2. 新字段为空时不影响现有逻辑
3. 现有测试无回归

### Phase 2：artifact 透传

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

### Phase 3：review renderer 扩展

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

### Phase 4：research target wrapper 与 short trade skeleton

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

1. `research_only`
2. `short_trade_only`
3. `dual_target` 三种模式可运行

验收标准：

1. research target 输出与旧研究主语义一致
2. short trade skeleton 可以输出占位结果
3. dual_target 能稳定写出 artifacts

### Phase 5：short trade 首版规则接入

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

### Phase 6：工作台消费与试运行

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

---

## 4. 每阶段测试要求

### 4.1 Phase 1-2

必须增加：

1. targets models 单元测试
2. selection_snapshot schema 扩展测试
3. session_summary / daily_events 双目标字段挂接测试

### 4.2 Phase 3

必须增加：

1. review renderer 双目标渲染测试
2. 旧 snapshot 向后兼容渲染测试

### 4.3 Phase 4-5

必须增加：

1. research wrapper 一致性测试
2. short trade gate 顺序测试
3. explainability tags / blockers 输出测试
4. dual_target mode 运行测试

### 4.4 Phase 6

必须增加：

1. replay artifact backend 路由测试
2. 前端 dual-target 视图测试
3. 必要的 smoke / workflow 回归

---

## 5. 回归风险与控制点

### 5.1 最大风险

最大的不是 short trade 规则错，而是：

1. schema 扩展破坏现有 artifacts
2. review renderer 让旧 report 无法渲染
3. dual_target 字段污染 research_only 默认流程

### 5.2 控制策略

建议每一阶段都遵守：

1. 新字段默认可空
2. 新模式默认关闭
3. 旧测试必须全绿
4. 先 frozen replay，再 live pipeline smoke

---

## 6. 与 arch_optimize_implementation 的关系

这份文档与 [arch_optimize_implementation.md](./arch_optimize_implementation.md) 的关系是：

1. `arch_optimize_implementation.md` 记录的是 research artifact 主线已经落地的实施经验
2. 本文档是在那个落地基线上，规划双目标系统的下一阶段施工顺序

也就是说，双目标实施不应绕开现有 research artifact 主线，而应复用它：

1. 复用 `src/research/models.py`
2. 复用 `src/research/artifacts.py`
3. 复用 Replay Artifacts 作为第一观察面

---

## 7. 第一阶段开工建议

如果明天开始真正改代码，建议只做下面这一小步：

1. 新增 `src/targets/models.py`
2. 增量扩展 `ExecutionPlan`
3. 增量扩展 `SelectionSnapshot`
4. 让 artifact writer 先能写出空壳 `selection_targets`

不要一上来就做：

1. 复杂 short trade 规则
2. 前端大改
3. entry plan 改造

因为那会让排错与归因同时失控。

---

## 8. 当前建议结论

双目标系统现在已经具备：

1. 架构总纲
2. 指标验证口径
3. 规则规格
4. 数据结构协议

下一步正确动作不是继续抽象讨论，而是按这份文档的 6 个阶段开始增量施工。

最合理的起点是：

1. 先接模型与 schema
2. 再接 artifacts
3. 再接 renderer
4. 再接目标路由
5. 最后才接首版 short trade 规则和前端视图

这条路线风险最低，也最符合当前仓库已经形成的 research artifact 主线。
