# 双目标选股与交易目标系统架构设计文档

## 0. 文档定位与边界

本文档是双目标系统的第一版系统规格草案，不是营销文案，也不是收益承诺书。

配套文档：

1. [次日短线目标指标与验证方案](./short_trade_target_metrics_and_validation.md)
2. [次日短线目标首版规则集规格](./short_trade_target_rule_spec.md)
3. [双目标系统数据结构与 Artifact Schema 规格](./dual_target_data_contract_and_artifact_schema.md)
4. [双目标系统实施与代码改造计划](./dual_target_implementation_plan.md)

本文档解决的问题是：

1. 如何在保留现有研究型选股主线的前提下，为系统增加一个面向 T+1 次日短线交易的目标模块。
2. 如何让同一套系统同时支持研究型目标与短线交易目标，而不是分裂成两套孤立系统。
3. 如何把双目标系统设计成可解释、可回测、可冻结、可复盘、可治理的工程体系。

本文档不做以下承诺：

1. 不承诺一个月超过 200% 的收益。
2. 不把极端收益目标作为架构验收标准。
3. 不把单窗口高收益视为系统级成功。

原因很简单：顶级交易系统的核心不是“承诺高收益”，而是“在真实约束下持续产生可验证的正期望，并避免在样本外快速失效”。

因此，本文档采用如下立场：

1. 可以把“月度高收益”视为探索型上限目标。
2. 不能把它作为系统设计的硬目标函数。
3. 系统设计必须优先服务于稳健性、可解释性、样本外可迁移性和风险控制。

---

## 1. 背景重定义

### 1.1 当前系统已经具备什么

当前系统已经具备完整的选股到执行链路：

1. Layer A 候选池构建
2. Layer B 策略评分与融合
3. Layer C 多智能体聚合
4. watchlist 生成
5. buy order / sell order 生成
6. Replay Artifacts 落盘与复盘

现有主线更偏向研究型与趋势型目标，其优势在于：

1. 能形成结构完整的候选解释
2. 能沉淀 Layer B / Layer C / execution 的分层证据
3. 能通过 Replay Artifacts 支持复盘和反馈治理

### 1.2 当前系统不擅长什么

当前系统不天然等价于“专门寻找明天最值得买、次日最有爆发力的股票”。

因为研究型目标与次日交易目标存在天然差异：

1. 研究型更关注结构是否成立、逻辑是否扎实、是否值得持续跟踪。
2. 次日交易型更关注启动新鲜度、次日胜率、次日赔率、可执行性和拥挤风险。

同一只股票可以是优秀的研究对象，但不是优秀的次日交易对象。

### 1.3 本轮需求的真正含义

本轮需求不是“再调一点阈值”，而是“增加一个新的目标函数”。

也就是说，当前不是：

1. 调一个更激进的 Layer B 规则
2. 用同一条分数曲线同时服务研究与短线

而应该是：

1. 保留现有研究目标
2. 新增短线交易目标
3. 让同一套系统对同一批候选生成两套不同的目标判断

---

## 2. 设计原则

### 2.1 一个系统，两个目标模块

推荐方案不是重做一套短线系统，而是：

1. 共用候选池、共用基础事实、共用运行框架
2. 在目标层增加 Research Target 与 Short Trade Target 两个模块
3. 在输出层生成两套结果与两套解释

### 2.2 目标解耦优先于分数混合

研究型分数与短线交易分数不能混成一个最终分数，否则会再次出现优化归因污染。

必须拆分：

1. 基础事实层
2. 目标评分层
3. 目标 gate 层
4. 目标输出层
5. 目标后验评估层

### 2.3 顶级系统优先追求稳健性而不是口号式收益

如果目标是接近业界顶级系统水平，架构应优先满足：

1. 数据约束真实
2. 回测口径严格
3. 执行假设保守
4. 指标定义可审计
5. 参数治理可冻结
6. 样本外验证可重复

### 2.4 保持现有主链路兼容

双目标系统的第一原则是增量演进，不破坏现有研究型主链路。

第一阶段应做到：

1. research_only 运行模式完全兼容现有逻辑
2. short_trade_only 和 dual_target 作为新增能力接入
3. Replay Artifacts 在第一阶段至少能透传目标维度，而不是强制一次重构全部 UI

---

## 3. 目标函数与验收标准

### 3.1 研究型目标函数

研究型目标不是追求次日涨幅最大化，而是追求：

1. 候选结构质量高
2. 多源证据一致性高
3. 中期跟踪价值高
4. 进入 watchlist 后具备较好的后续研究命中率

建议研究型目标的首版验收指标包括：

1. watchlist 后 10 日和 20 日超额收益分布
2. Layer C 与后验走势的一致性
3. near-miss 与 selected 的区分度
4. 人工复核通过率

### 3.2 短线交易目标函数

短线交易目标不是“主观感觉明天会涨”，而是最大化次日交易正期望。

建议显式定义为：

1. 优先优化 T+1 胜率
2. 同时优化 T+1 盈亏比
3. 在流动性、滑点、涨跌停与 T+1 制度约束下最大化风险调整后收益

建议短线目标首版核心指标：

1. T+1 close-to-close 胜率
2. T+1 open-to-high 赔率
3. T+1 open-to-close 赔率
4. T+3 持有窗口收益分布
5. hit rate、payoff ratio、expectancy
6. max drawdown、turnover、capacity stress

### 3.3 为什么不能把“月收益 200%”当验收标准

月收益 200% 可能是某些短窗口中的结果，但它不适合做系统架构的验收标准，因为：

1. 它极易被样本选择偏差和杠杆假设污染。
2. 它不能区分真实 alpha 与执行/容量幻觉。
3. 它鼓励系统在回测中走向过拟合和极端风险承担。

更合理的做法是：

1. 把 200% 月收益视为压力测试或上限观察项
2. 把首版验收标准建立在稳定性、可迁移性和回撤控制之上

---

## 4. 先验硬约束矩阵

短线目标模块必须继承并强化现有执行约束，不能旁路真实市场约束。

首版必须显式纳入以下硬约束：

1. T+1 交易制度
2. 涨跌停无法成交风险
3. 滑点与手续费
4. 流动性下限
5. 停牌与复牌异常
6. 单票仓位上限
7. 单行业暴露上限
8. 日内新开仓数量上限

建议把约束分成三类：

1. pre-trade gate
2. entry confirmation gate
3. portfolio risk gate

其中：

1. pre-trade gate 决定“是否有资格进入短线池”
2. entry confirmation gate 决定“明天是否执行买入”
3. portfolio risk gate 决定“即使信号通过，是否允许分配资金”

---

## 5. 双目标系统总体架构

### 5.1 总体结构

推荐采用五层结构：

1. 数据与事实层
2. 基础筛选与融合层
3. 目标模块层
4. 输出与执行层
5. 评估与治理层

### 5.2 数据与事实层

该层只负责生成与目标无关的基础事实，不负责最终决策。

基础事实包括：

1. Layer A candidate pool
2. Layer B strategy_signals
3. score_b 与相关解释字段
4. Layer C agent_signals、score_c、score_final、bc_conflict
5. 市场状态
6. 行业强弱
7. 事件新鲜度
8. 波动、流动性、量价结构

### 5.3 目标模块层

目标模块层是本轮新增核心，至少包含：

1. Research Target Module
2. Short Trade Target Module
3. Target Router
4. Target Explainability Layer

每个目标模块必须独立输出：

1. target_score
2. target_decision
3. confidence
4. positive_tags
5. negative_tags
6. blockers
7. top_reasons

### 5.4 输出与执行层

输出层负责形成：

1. research_candidates
2. research_watchlist
3. short_trade_candidates
4. short_trade_watchlist
5. short_trade_entry_plan
6. dual_target_comparison

执行层则根据运行模式决定是否继续推进到订单级结果。

### 5.5 评估与治理层

评估与治理层必须成为主架构的一部分，而不是事后补脚本。

该层应负责：

1. 回测与 frozen replay
2. 日度对照报告
3. 目标级反馈写入
4. 参数冻结与版本追踪
5. 样本外评估与漂移检测

---

## 6. 与现有代码结构的映射

### 6.1 可直接复用的基础模块

现有以下模块应保留为共享基础层：

1. [src/screening/candidate_pool.py](src/screening/candidate_pool.py)
2. [src/screening/strategy_scorer.py](src/screening/strategy_scorer.py)
3. [src/screening/signal_fusion.py](src/screening/signal_fusion.py)
4. [src/execution/layer_c_aggregator.py](src/execution/layer_c_aggregator.py)
5. [src/execution/daily_pipeline.py](src/execution/daily_pipeline.py)
6. [src/execution/models.py](src/execution/models.py)

### 6.2 建议新增的目标模块目录

建议新增：

1. src/targets/models.py
2. src/targets/research_target.py
3. src/targets/short_trade_target.py
4. src/targets/router.py
5. src/targets/explainability.py
6. src/targets/profiles.py

其中：

1. models.py 定义目标层数据契约
2. research_target.py 包装现有研究主语义
3. short_trade_target.py 承载短线打分与 gate
4. router.py 根据运行模式组织输出
5. explainability.py 统一输出标签与 blocker
6. profiles.py 管理短线模式的不同参数档位

### 6.3 运行模式

建议统一支持三种模式：

1. research_only
2. short_trade_only
3. dual_target

推荐 CLI 参数：

1. --selection-target research_only|short_trade_only|dual_target
2. --short-trade-profile default|aggressive|conservative
3. --emit-dual-target-artifacts

---

## 7. 数据契约设计

### 7.1 目标输入模型

建议新增 TargetEvaluationInput，用于把基础层与目标层隔离开。

建议字段：

```text
TargetEvaluationInput
- trade_date
- ticker
- market_state
- layer_a_metadata
- strategy_signals
- score_b
- layer_c_result
- liquidity_features
- volatility_features
- event_features
- sector_features
- execution_constraints
- replay_context
```

这样做的目的有两个：

1. 防止目标模块直接耦合底层实现细节
2. 为 frozen replay 和批量评估提供稳定输入契约

### 7.2 目标输出模型

建议输出统一模型：

```text
TargetEvaluationResult
- target_type
- score_target
- decision_target
- confidence
- positive_tags
- negative_tags
- blockers
- top_reasons
- expected_holding_window
- preferred_entry_mode
- artifact_payload
```

### 7.3 在现有 ExecutionPlan 中的承接方式

当前 [src/execution/models.py](src/execution/models.py) 中的 ExecutionPlan 已经承载 watchlist 与 selection_artifacts。

首版建议不直接推翻 schema，而是采用渐进接入：

1. 先在 selection_artifacts 中增加 selection_targets 区块
2. 再增加 research_watchlist 和 short_trade_watchlist
3. 最后再决定是否为 short_trade_entry_plan 单独升格为顶层字段

### 7.4 日志与 artifacts 透传

建议在以下产物中增加 target 维度：

1. daily_events.jsonl
2. pipeline_timings.jsonl
3. session_summary.json
4. selection_snapshot.json
5. selection_review.md

建议至少透传：

1. research_candidate_count
2. short_trade_candidate_count
3. research_selected_count
4. short_trade_selected_count
5. delta_selected_count

---

## 8. 双目标决策生命周期

建议把一次完整运行拆成九个阶段：

1. universe ingest
2. Layer A candidate screening
3. Layer B strategy scoring
4. Layer C analyst aggregation
5. target input materialization
6. research target evaluation
7. short trade target evaluation
8. dual comparison materialization
9. execution / replay / feedback writeback

这样可以让双目标系统具备三个重要性质：

1. 单目标模式与双目标模式共享前五个阶段
2. 目标层完全可冻结和复盘
3. 工作台可以直接展示阶段间差异

---

## 9. 短线交易目标算法框架

### 9.1 设计原则

短线交易目标不应理解为“把 Layer B 调得更激进”，而应理解为“建立一个专门针对 T+1 机会捕捉的目标函数”。

首版应坚持：

1. 规则型
2. 可解释型
3. 可冻结型
4. 可回测型

### 9.2 建议的短线目标因子簇

建议围绕六类正向因子和三类负向因子建立首版模型。

正向因子簇：

1. breakout_freshness
2. trend_acceleration
3. volume_expansion_quality
4. close_strength
5. sector_resonance
6. catalyst_freshness

负向因子簇：

1. stale_trend_repair_penalty
2. overhead_supply_penalty
3. extension_without_room_penalty

### 9.3 建议的首版打分框架

首版短线目标分数建议采用显式可解释公式，而不是立即引入黑箱模型。

示意公式：

```text
score_short =
  0.22 * breakout_freshness
  + 0.18 * trend_acceleration
  + 0.16 * volume_expansion_quality
  + 0.14 * close_strength
  + 0.12 * sector_resonance
  + 0.08 * catalyst_freshness
  + 0.10 * layer_c_alignment
  - 0.12 * stale_trend_repair_penalty
  - 0.10 * overhead_supply_penalty
  - 0.08 * extension_without_room_penalty
```

说明：

1. 这是研究起点，不是冻结参数。
2. 各因子需先标准化到统一量纲。
3. Layer C alignment 只作为加分项，不应让短线目标完全依赖 LLM。

### 9.4 首版 gate 设计

建议把 gate 与 score 分开。

硬 gate：

1. 流动性不达标直接拒绝
2. 涨停难成交风险过高直接拒绝
3. 当日已经大幅延伸且空间不足直接拒绝
4. 事件过旧、筹码过重、上方抛压过大直接拒绝

软 gate：

1. score_short 达到阈值才入短线池
2. 风险评分通过才允许进入 entry plan

### 9.5 推荐标签体系

建议新增以下正向标签：

1. fresh_breakout_setup
2. trend_acceleration_active
3. volume_expansion_confirmed
4. close_near_high
5. sector_relative_strength
6. fresh_event_catalyst
7. breakout_room_large

建议新增以下负向标签：

1. post_run_pullback_chop
2. stale_trend_repair
3. overhead_supply_risk
4. repeated_failed_breakout
5. event_not_fresh
6. weak_next_day_edge
7. late_stage_extension_without_room

---

## 10. 研究型目标算法框架

研究型目标不需要重写，应被重新包装成一个显式目标模块。

建议研究型目标继续保持以下优先级：

1. 结构完整性
2. 基本面与技术面的相互支撑
3. Layer B / Layer C 一致性
4. 可解释性与后续研究价值

研究型目标与短线目标的边界必须允许以下情况出现：

1. research = pass, short_trade = reject
2. research = reject, short_trade = pass

第二种情况虽然在首版中应较少出现，但架构必须允许它存在，因为短线爆发票未必具备强研究属性。

---

## 11. 目标冲突与仲裁规则

### 11.1 同一股票跨目标结果冲突是正常现象

双目标系统不追求把冲突抹平，而追求把冲突解释清楚。

### 11.2 建议的冲突分类

建议把跨目标差异至少分为四类：

1. research_pass_short_reject
2. research_reject_short_pass
3. both_pass_but_rank_diverge
4. both_reject_but_reason_diverge

### 11.3 Delta View 的核心用途

Delta View 不是 UI 点缀，而是架构必需能力，用于回答：

1. 哪些票是研究优质但交易不优质
2. 哪些票是交易优质但研究一般
3. 差异来自启动新鲜度、拥挤度、事件新鲜度、还是 Layer C 冲突

---

## 12. Replay Artifacts 与工作台演进

### 12.1 工作台必须从单结果复盘升级为双目标复盘

后续工作台至少应支持三个视角：

1. Research View
2. Short Trade View
3. Delta View

### 12.2 反馈模型也必须增加目标维度

建议 feedback 体系增加：

1. target_type
2. target_verdict
3. realized_outcome_window
4. outcome_label
5. reviewer_confidence

这样才能把“研究判断”和“交易判断”分开记录。

### 12.3 与现有工作台设计的一致性

这一方向与 [arch_replay_artifacts_workspace_redesign.md](./arch_replay_artifacts_workspace_redesign.md) 的主线一致，即：

1. 工作台承载研究与复盘，而不是只展示静态产物
2. 页面布局应服务于多视图对照，而不是单列表阅读

---

## 13. 验证与评估框架

### 13.1 顶级系统必须先解决验证纪律

如果没有严格验证纪律，任何“高收益”都不可信。

双目标系统至少应采用五类验证：

1. 单日 frozen replay
2. 连续窗口回放
3. walk-forward validation
4. regime-sliced validation
5. execution-realistic backtest

### 13.2 建议的评估窗口

研究型目标：

1. T+5
2. T+10
3. T+20

短线交易目标：

1. T+1 open-to-close
2. T+1 open-to-high
3. T+1 close-to-close
4. T+3 持有收益分布

### 13.3 必须纳入的风险与真实性检查

至少必须检查：

1. 滑点敏感性
2. 涨停买不到、跌停卖不出的极端情形
3. 低流动性样本剔除前后结果变化
4. 参数小扰动后的稳定性
5. 不同市场状态下的胜率漂移

### 13.4 防过拟合机制

建议把防过拟合机制写入系统治理，而不是靠自觉：

1. 每次参数变更必须标注版本与假设
2. 先在 in-sample 调参，再在 out-of-sample 验证
3. 未经新窗口验证的参数不得进入默认档
4. 月度仅允许有限次数阈值更新
5. 指标改善如果只在单一窗口成立，不得升级为默认策略

---

## 14. 资金管理与组合层设计

如果目标是向更高水平的交易系统靠拢，选股模块之外必须预留组合层接口。

短线目标至少需要输出给组合层以下信息：

1. conviction
2. liquidity_bucket
3. expected_holding_window
4. gap_risk_level
5. crowding_risk_level

组合层后续可据此做：

1. 仓位分级
2. 行业集中度控制
3. 新开仓上限控制
4. 风险事件降仓
5. 高相关票互斥控制

没有这一层，所谓高收益系统很容易退化成“高集中高回撤系统”。

---

## 15. 实施阶段建议

### 15.1 Phase 0：定义冻结

先冻结以下定义：

1. research target success metrics
2. short trade target success metrics
3. 各评估窗口定义
4. 真实执行口径
5. 参数变更与版本管理口径

### 15.2 Phase 1：目标层骨架接入

最小产物：

1. TargetEvaluationInput
2. TargetEvaluationResult
3. Target Router
4. Research Target Wrapper
5. Short Trade Target Skeleton

### 15.3 Phase 2：短线目标最小规则集

建议首批只实现：

1. breakout freshness
2. volume expansion quality
3. close strength
4. sector resonance
5. stale trend repair penalty

### 15.4 Phase 3：双目标 artifacts 接入

让 daily_events、session_summary、selection_artifacts 能写出双目标结果。

### 15.5 Phase 4：工作台双视图接入

增加 Research View、Short Trade View、Delta View。

### 15.6 Phase 5：后验评估与默认档治理

让短线目标从“实验档”升级到“默认档”前，必须通过多窗口验证与人工复核。

---

## 16. 反模式与失败模式

### 16.1 用一个最终分数同时代表两个目标

这是最需要避免的反模式。

### 16.2 为了短线收益幻觉破坏研究主线

短线目标应增量接入，不能把整个系统强行改成追涨板系统。

### 16.3 没有执行 realism 的回测

如果不纳入 T+1、涨跌停、滑点、流动性，短线策略几乎一定会被回测高估。

### 16.4 只用单窗口优胜样本做结论

这会把噪声误认为边际改进。

### 16.5 过早引入复杂模型

在没有建立干净验证框架之前，不建议直接上复杂机器学习模型或端到端黑箱模型。

---

## 17. 本轮评审清单

建议下一轮评审重点确认以下问题：

1. 是否认可“月收益 200% 不能作为架构验收标准”的边界？
2. 是否认可双目标拆分为研究型目标与次日交易目标？
3. 是否认可短线目标首版坚持规则型、可解释型、可冻结型？
4. 是否认可先在 artifacts 层承接，而不是第一阶段直接大改 ExecutionPlan？
5. 是否认可 Replay Artifacts 后续增加 Delta View 作为核心能力？
6. 是否认可短线目标的首版重点是次日正期望，而不是单纯追求胜率？
7. 是否认可默认策略升级必须经过多窗口样本外验证？

---

## 18. alpha-loop 十轮迭代记录

本轮文档按 alpha-loop 思路完成了 10 轮收敛，记录如下：

1. 第 1 轮：重定义问题，把需求从“调参数”升级为“增加目标函数”。
2. 第 2 轮：加入硬边界，明确不以月收益 200% 作为架构验收标准。
3. 第 3 轮：补充目标函数与验收指标，区分 research 与 short trade。
4. 第 4 轮：补先验硬约束矩阵，避免短线系统旁路真实执行约束。
5. 第 5 轮：将总体架构从三层扩展为五层，加入评估与治理层。
6. 第 6 轮：补齐与现有代码结构的映射，避免设计脱离当前仓库。
7. 第 7 轮：新增目标输入输出数据契约，支撑 frozen replay 与 artifacts。
8. 第 8 轮：把短线目标从抽象描述细化为可解释的因子簇、打分和 gate 框架。
9. 第 9 轮：加入验证纪律、防过拟合机制、组合层接口和失败模式。
10. 第 10 轮：整理为评审版结构，补充评审清单与实施阶段顺序。
11. 后续补充：拆出指标验证文档与规则规格文档，降低总纲与实施细节耦合。
12. 后续补充：新增数据结构与 artifact schema 规格，推进到字段级冻结层。
13. 后续补充：新增实施与代码改造计划，明确真实代码落点、阶段顺序与回归要求。

---

## 19. 当前建议结论

当前最优路径不是重做一个短线交易系统，而是：

1. 保留现有研究型系统主线。
2. 在共享事实层之上增加目标模块层。
3. 新增一个专门面向 T+1 次日交易的 Short Trade Target Module。
4. 让系统支持 research_only、short_trade_only、dual_target 三种运行模式。
5. 先建立目标级 artifacts 与评估体系，再决定默认档升级。

如果后续目标是接近更高水平的交易系统，真正需要优先做好的不是“喊出更激进的收益目标”，而是：

1. 目标函数清晰
2. 验证口径严格
3. 执行假设真实
4. 风险约束前置
5. 参数治理可冻结
6. 研究与交易两个目标长期并存且相互可对照

这才是这套系统走向更高水平的正确起点。
