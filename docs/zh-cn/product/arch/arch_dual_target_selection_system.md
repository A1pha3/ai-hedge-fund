# 双目标选股系统架构设计文档

## 1. 文档目标

本文档回答一个明确的新需求：

在保留现有“研究型选股系统”的前提下，在同一套系统架构内新增一个“次日短线交易目标模块”，让系统既能输出：

1. 面向中期研究和趋势跟踪的研究型候选结果。
2. 面向 T 日收盘后选股、T+1 日买入的短线交易候选结果。

本文档的目标不是立即修改代码，而是先把需求、边界、架构方案、模块职责、数据模型、运行模式、产物形态和实施顺序定义清楚，供后续多轮评审使用。

本文档默认遵循以下原则：

1. 不推翻现有系统，不重新造一个独立系统。
2. 在当前 Layer A / Layer B / Layer C / Execution / Replay Artifacts 架构上演进。
3. 明确区分“研究型目标”和“次日交易目标”，避免继续把两类目标混在一个评分口径里。
4. 保持一次运行可双产出，也允许按目标类型单独运行。
5. 第一阶段优先做架构与接口设计，后续再分阶段落地实现。

---

## 2. 背景与问题定义

### 2.1 当前系统的真实定位

当前系统已经具备完整的日度决策链路：

1. Layer A 候选池构建
2. Layer B 四策略评分与融合
3. Layer C 多智能体聚合
4. Watchlist 生成
5. Buy order / sell order 生成
6. Replay Artifacts 落盘与复盘

这套系统在当前阶段更偏向以下目标：

1. 研究价值较高的候选识别
2. 中期趋势和结构性机会跟踪
3. 候选质量解释与复盘
4. T+1 执行桥接与风控

也就是说，它并不天然等价于“今天收盘后选出明天最可能快速上涨、且涨幅空间大的股票”。

### 2.2 新需求的本质

本轮新增的是一个新的优化目标，而不是小幅参数微调：

> 希望系统在 T 日收盘后，能够专门输出一组更偏向“趋势启动、趋势加速、突破扩张、次日胜率高、赔率高”的短线交易候选。

这个目标与原有研究型目标存在明显差异：

1. 研究型目标关注“结构是否成立、是否值得跟踪、是否具备中期质量”。
2. 次日交易目标关注“明天买入后是否大概率上涨、是否有较大短期弹性、是否处在启动或加速阶段”。

这两类目标会共享很多底层信息，但并不应该共享同一个最终目标函数。

### 2.3 当前痛点

如果继续只用一套 Layer B / Layer C 结果同时服务这两类目标，会出现以下问题：

1. 研究型优质票不一定是次日交易优质票。
2. 旧趋势修复票、回调震荡票可能通过研究型筛选，但 T+1 交易表现较差。
3. 参数优化时无法分辨“研究型表现变好”还是“短线交易表现变好”。
4. Replay Artifacts 中当前的复盘语义仍主要围绕 watchlist / execution bridge，而不是“短线启动边”。

因此，需要从系统结构上明确支持“双目标”。

---

## 3. 核心设计原则

### 3.1 一个系统，两个目标，不是两个孤岛系统

系统不应拆成两套完全独立的代码和工作流，而应采用：

1. 共享上游数据、共享候选池、共享基础评分和共享基础 artifacts。
2. 在目标层新增“目标模块”和“目标专属 gate / score / output”。

也就是说，应该是：

1. 一个基础选股平台。
2. 两个目标视图：研究型视图、次日交易视图。

### 3.2 目标解耦优先于评分混合

研究型与次日交易型可以共享基础特征，但不应该直接共享一个最终分数。

推荐原则：

1. 共享基础事实层
2. 分开目标评分层
3. 分开目标 gate 层
4. 分开目标输出层

避免继续出现：

1. 一个高分在研究上合理，但在交易上无用。
2. 一个参数优化改善了研究池，却恶化了次日胜率。

### 3.3 输出双轨，但运行链路尽量单轨复用

运行层应该支持三种模式：

1. 仅研究型目标
2. 仅次日交易目标
3. 双目标同时运行

但底层应尽量复用同一条日度 pipeline，避免维护两套独立主链路。

### 3.4 可复盘、可对照、可冻结

双目标架构必须天然支持：

1. 对比同一 trade_date 下两个目标的结果差异
2. 对比同一股票为何进入研究池但未进入短线池
3. 对比同一股票为何进入短线池但未进入研究池
4. 对两个目标分别做后验收益和赔率分析

这意味着 Replay Artifacts 和日度事件流都需要增加“目标维度”。

---

## 4. 目标定义

### 4.1 目标 A：研究型选股目标

研究型目标保持现有主语义：

1. 寻找结构较完整、基本面与技术面相互支撑、值得跟踪或配置的候选。
2. 允许包含趋势修复、中期改善、边界样本与待人工复核样本。
3. 更关注解释完整性和后续研究价值。

研究型目标适合回答：

1. 哪些票值得继续研究？
2. 哪些票值得进入 watchlist？
3. 哪些票是长期趋势或中期结构机会？

### 4.2 目标 B：次日短线交易目标

次日交易目标新增定义如下：

1. 在 T 日收盘后，从当日候选中筛出更偏向“趋势启动、趋势加速、突破确认、强主线扩张、次日高胜率高赔率”的股票。
2. 目标不是“中期看起来不错”，而是“明日买入后大概率快速获利，且涨幅空间较大”。
3. 对旧趋势修复、回调震荡、上方抛压大、催化不新鲜的票更严格。

次日交易目标适合回答：

1. 明天最值得优先买的股票是谁？
2. 哪些股票更像启动前夜或加速前夜？
3. 哪些股票更可能提供高胜率与高赔率的短期机会？

### 4.3 两个目标的共性与差异

共性：

1. 都依赖同一 trade_date 的候选池和策略事实。
2. 都依赖 trend / fundamental / mean_reversion / event_sentiment 等基础信号。
3. 都可使用 Layer C 的多智能体分析。

差异：

1. 研究型更看结构完整、解释一致性、长期质量。
2. 短线型更看启动新鲜度、扩张概率、次日动能、板块与催化同步性。
3. 研究型可容忍修复票；短线型应明显惩罚修复票。

---

## 5. 总体架构方案

### 5.1 推荐方案：共享基础层 + 目标模块层 + 双输出层

推荐采用三层结构：

1. 基础事实层
2. 目标模块层
3. 输出与执行层

#### 5.1.1 基础事实层

基础事实层负责统一生成不带目标偏见的原始事实，包括：

1. Layer A candidate pool
2. Layer B strategy signals
3. Layer B fused score 基础值
4. Layer C agent outputs 与 contribution summary
5. 市场状态、行业强度、事件新鲜度等通用特征

该层的职责是“生成事实”，而不是“决定最终属于哪个目标”。

#### 5.1.2 目标模块层

目标模块层是本次新增的核心。建议新增两个目标模块：

1. Research Target Module
2. T1 Short Trade Target Module

每个目标模块负责：

1. 目标专属评分
2. 目标专属 gate
3. 目标专属 rejection reason
4. 目标专属 explainability 标签

#### 5.1.3 输出与执行层

输出层负责产出两个结果：

1. research_watchlist / research_candidates
2. short_trade_watchlist / short_trade_candidates

执行层则根据运行模式决定：

1. 只对研究型目标继续生成原有 watchlist / buy_orders
2. 只对短线目标生成单独的 short_trade_plan
3. 双目标并行生成两套结果和 artifacts

---

## 6. 模块级设计

### 6.1 基础层保留不动的部分

以下模块应尽量保持为通用基础层，不在第一阶段做破坏性重构：

1. [src/screening/candidate_pool.py](src/screening/candidate_pool.py)
2. [src/screening/strategy_scorer.py](src/screening/strategy_scorer.py)
3. [src/screening/signal_fusion.py](src/screening/signal_fusion.py)
4. [src/execution/layer_c_aggregator.py](src/execution/layer_c_aggregator.py)
5. [src/execution/daily_pipeline.py](src/execution/daily_pipeline.py)

但它们会新增“为目标模块服务的可复用事实字段”。

### 6.2 新增目标模块包

建议新增一个专门的目标模块目录，例如：

1. src/targets/
2. 或 src/objectives/

推荐结构：

1. src/targets/models.py
2. src/targets/research_target.py
3. src/targets/short_trade_target.py
4. src/targets/router.py
5. src/targets/explainability.py

职责建议如下：

#### src/targets/models.py

定义目标层的统一数据模型，例如：

1. SelectionTargetType
2. TargetEvaluationInput
3. TargetEvaluationResult
4. DualTargetSelectionResult

#### src/targets/research_target.py

负责研究型目标的评分与 gate。

#### src/targets/short_trade_target.py

负责次日短线目标的评分与 gate。

#### src/targets/router.py

负责根据运行模式：

1. 只执行 research
2. 只执行 short_trade
3. 同时执行 dual_target

#### src/targets/explainability.py

负责统一生成目标级 explainability 标签和 rejection reason。

---

## 7. 双目标运行模式设计

### 7.1 运行模式枚举

建议定义统一运行模式：

1. research_only
2. short_trade_only
3. dual_target

默认建议：

1. 现有主线先保持 research_only 兼容模式
2. 新实验和新 report 默认支持 dual_target

### 7.2 一次运行的执行顺序

推荐顺序：

1. 构建 candidate pool
2. 计算策略 signals 与基础 Layer B 融合
3. 运行 Layer C 基础分析
4. 构造 TargetEvaluationInput
5. 分别交给 research target 与 short trade target
6. 产出双轨结果
7. 根据模式决定生成哪些 artifacts 与哪些 execution plan

### 7.3 CLI / runtime 参数设计

建议在现有 CLI 和 runtime 层增加以下参数：

1. --selection-target research_only|short_trade_only|dual_target
2. --enable-short-trade-target
3. --short-trade-profile profile_name

这样可以做到：

1. 同一条主命令兼容旧逻辑
2. 新逻辑通过显式参数启用

---

## 8. 短线目标模块的因子与 gate 设计方向

### 8.1 短线目标不等于“更激进的 Layer B”

短线目标模块不应只是简单把 Layer B 阈值调高或调低，而应引入一组新的目标语义：

1. 趋势启动新鲜度
2. 趋势加速度
3. 突破确认程度
4. 量价扩张质量
5. 板块与主线同步性
6. 事件或催化新鲜度
7. 旧趋势修复惩罚

### 8.2 短线目标建议新增的正向标签

建议短线目标模块显式识别如下正向标签：

1. fresh_breakout_setup
2. trend_acceleration_active
3. volume_expansion_confirmed
4. close_near_high
5. sector_relative_strength
6. fresh_event_catalyst
7. breakout_room_large

### 8.3 短线目标建议新增的负向标签

建议显式识别如下负向标签：

1. post_run_pullback_chop
2. stale_trend_repair
3. overhead_supply_risk
4. repeated_failed_breakout
5. event_not_fresh
6. weak_next_day_edge
7. late_stage_extension_without_room

### 8.4 Research 与 Short Trade 的边界

同一只票可能：

1. research target = pass
2. short trade target = reject

这是允许且必要的。

系统应显式支持这种结果，而不是试图强行统一。

---

## 9. 数据模型与产物设计

### 9.1 建议新增目标层结果模型

建议新增统一模型，例如：

```text
TargetEvaluationResult
- target_type
- score_target
- decision_target
- top_reasons
- rejection_reasons
- tags_positive
- tags_negative
- confidence
```

### 9.2 建议在 ExecutionPlan 中增加目标结果字段

当前 [src/execution/models.py](src/execution/models.py) 中的 ExecutionPlan 已经承载了 Layer B / Layer C / watchlist / selection_artifacts。

建议后续增加：

1. selection_targets
2. research_watchlist
3. short_trade_watchlist
4. short_trade_plan

但第一阶段不要求立刻改 ExecutionPlan 的最终 schema，可以先从 artifacts 层试运行。

### 9.3 建议在 selection artifacts 中增加双目标视图

现有 selection_snapshot / selection_review 体系建议后续扩展为：

1. research 视图
2. short trade 视图
3. dual comparison 视图

例如：

1. 为什么该票进入研究池但未进入短线池
2. 为什么该票进入短线池但未进入研究池
3. 两个目标各自的 top factors 和 blockers

### 9.4 建议在 daily_events / session_summary 中透传目标维度

建议后续在：

1. daily_events.jsonl
2. pipeline_timings.jsonl
3. session_summary.json

增加目标级 counts 和 artifact links，例如：

1. research_candidate_count
2. short_trade_candidate_count
3. research_watchlist_count
4. short_trade_watchlist_count

---

## 10. Replay Artifacts 与复盘工作台如何演进

### 10.1 工作台不应只展示单一选股结果

现有 Replay Artifacts 工作台已经具备很好的复盘基础，但默认只有单一结果链路。

双目标架构下，工作台后续应支持：

1. 切换 research target / short trade target / dual comparison
2. 查看每个目标的 selected / rejected / near-miss
3. 查看跨目标差异解释

### 10.2 建议新增的工作台视角

建议后续新增三个视角：

1. Research View
2. Short Trade View
3. Delta View

Delta View 重点回答：

1. 哪些票被研究池接受但被短线池拒绝
2. 哪些票被短线池接受但被研究池拒绝
3. 为什么不同

### 10.3 反馈体系也应增加目标维度

当前 research_feedback.jsonl 主要围绕 selected / near-miss / execution blocker。

后续建议增加：

1. target_type
2. target_verdict
3. next_day_outcome_review

这样研究员可以明确反馈：

1. 研究上我认为它是好票
2. 但短线交易上我认为它不是明日好票

---

## 11. 实施阶段建议

### 11.1 Phase 0：需求冻结与指标定义

目标：先把“短线目标到底追求什么”写清楚。

需要冻结的内容：

1. 次日胜率定义
2. 次日赔率定义
3. 次日空间定义
4. 评价窗口是 T+1 收盘、T+1 最高价，还是 T+1~T+3
5. 短线目标的首版 success metric

### 11.2 Phase 1：目标模块最小骨架

目标：不改现有主逻辑语义，先把目标模块接口接起来。

最小产物：

1. target models
2. target router
3. research target wrapper
4. short trade target skeleton
5. dual-target artifact 占位结构

### 11.3 Phase 2：短线目标最小因子集

目标：引入最小可用的短线目标规则，不一开始上太多复杂特征。

建议首批因子：

1. breakout freshness
2. volume expansion
3. close near high
4. old-run pullback penalty
5. event freshness

### 11.4 Phase 3：双目标 artifacts 与 replay 接入

目标：让工作台可以真实看双目标结果，而不是只在日志里看。

### 11.5 Phase 4：双目标后验评估框架

目标：新增专门脚本和报告，评估：

1. research target 的中期质量
2. short trade target 的 T+1 胜率和赔率

---

## 12. 风险与反模式

### 12.1 反模式：用一个分数同时代表两个目标

这会再次把研究价值和交易价值混起来，不建议。

### 12.2 反模式：为了短线目标破坏研究目标主链路

短线目标应是新增模块，不应直接把研究型主链路改成“全都只追启动板”。

### 12.3 反模式：一开始就做太复杂的模型

建议先从规则型和可解释型 short trade target 开始，再决定是否引入更复杂模型。

### 12.4 反模式：没有后验指标就开始调参

如果没有 T+1 胜率、赔率、空间指标，短线目标最终会再次退化成主观调参。

---

## 13. 本文档的评审问题

本轮评审建议重点围绕以下问题：

1. “研究型目标”和“次日交易目标”的边界是否定义清楚？
2. “一个系统、两个目标模块”的路线是否比“重做一个短线系统”更符合当前项目？
3. 目标模块放在 src/targets/ 是否合理？
4. 是否接受“一次运行双产出，也可单独运行某个目标”的运行模式？
5. Replay Artifacts 是否应在第二阶段就开始承载双目标视图？
6. 短线目标第一阶段是否应坚持规则型、可解释型实现，而不是立即模型化？
7. 研究型产出是否仍然保留原有 watchlist / buy_order 主链路兼容？

---

## 14. 当前建议结论

基于现有系统形态，最优路径不是重做一个系统，而是：

1. 保留现有研究型系统主线。
2. 在同一条 pipeline 之上增加目标模块层。
3. 新增一个 short trade target module，专门服务 T+1 短线目标。
4. 让系统支持 research_only / short_trade_only / dual_target 三种模式。
5. 后续再逐步把 Replay Artifacts、反馈与评估体系升级为双目标复盘平台。

这条路线的优点是：

1. 不破坏现有工程资产。
2. 能准确承接当前 Replay Artifacts 和 selection artifacts 能力。
3. 便于逐步验证短线目标，而不是一次性大改。
4. 允许研究型与短线型系统长期并存，并在同一运行框架中逐步演进。
