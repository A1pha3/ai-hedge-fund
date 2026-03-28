# 选股优先优化方案实施设计文档

> 文档状态：选股优先主线的实施与收口记录
> 最近补充导航时间：2026-03-28 09:59:08 CST
> 相关专题：双目标系统的后续设计与分阶段改造方案已单独沉淀到 [dual_target_system/README.md](./dual_target_system/README.md)。

## 0. 专题导航

本文档记录的是“选股优先优化方案”主线的实施落地、Replay Artifacts 工作台建设与试用验收收口状态。

如果你现在要继续推进的是以下问题：

1. 如何在保留现有研究型选股主线的同时新增 short trade target。
2. 如何定义双目标的字段级协议、artifact 承接与 replay 扩展结构。
3. 如何按阶段改造代码而不是继续在本实施文档里追加新分支。

那么应改为从双目标专题目录进入，而不是继续把这份文档当作总入口：

1. [双目标系统专题目录](./dual_target_system/README.md)
2. [双目标选股与交易目标系统架构设计文档](./dual_target_system/arch_dual_target_selection_system.md)
3. [双目标系统数据结构与 Artifact Schema 规格](./dual_target_system/dual_target_data_contract_and_artifact_schema.md)
4. [双目标系统实施与代码改造计划](./dual_target_system/dual_target_implementation_plan.md)

## 1. 当前落地状态

本文档已经不再只是实施提案。截至 2026-03-26，第一批代码骨架、最小上层消费界面以及首轮试用验收记录已落地，因此本文档需要同时承担两种职责：

1. 记录目标设计。
2. 记录当前已完成状态，避免文档与代码脱节。

为避免继续把“主线迁移”和“后续增强”混在一起，当前收口状态先明确分成三层：

### 1.1 收口状态总览

#### 1.1.1 主线任务：已完成

这里的主线特指：把 Replay Artifacts 从零散的 artifact/CLI 能力，推进到一个可直接使用的研究工作台。

当前可以认为主线已经完成，判断标准如下：

1. selection_artifacts 已在 backtesting / paper trading / live pipeline 的真实输出链路中稳定落盘，并能回填到 session_summary.json、daily_events.jsonl 与 pipeline_timings.jsonl。
2. Replay Artifacts 已从“只可读文件/CLI”推进为“后端接口 + 前端工作台”闭环，用户可直接浏览 report、切换 trade_date、查看 selection_review、execution blocker、funnel diagnostics，并回写 research feedback。
3. 前端工作台迁移已经完成，当前实现不再依赖手工翻 data/reports 或只停留在 settings 内嵌块才能完成最小研究闭环。
4. 自动化验证已经覆盖 research、runtime、backend routes/services、frontend regression 与生产构建，说明这不是仅停留在演示层的迁移。

试用验收执行入口见 [docs/zh-cn/manual/replay-artifacts-trial-acceptance-plan.md](docs/zh-cn/manual/replay-artifacts-trial-acceptance-plan.md)。

#### 1.1.2 增强项：已完成首轮可用版本

下列能力已经超出“迁移成功”本身，但现已具备首轮可用版本：

1. feedback 标签治理、CLI、summary 聚合与 SQLite-backed ledger。
2. Replay Artifacts inspector 中的 recent activity、review_status/tag/reviewer 聚合。
3. Batch Label Workspace，用于多只 watchlist / near-miss 样本的批量反馈写入。
4. report 级 workflow queue 与 pending draft queue。
5. 跨 report 的 workflow ownership queue，以及 `Assign to me` / `Unassign` 归属入口。
6. cache benchmark 摘要透传与页面可视化。
7. 配套操作手册、标签规范、周度复盘与 backlog 映射文档。

这些增强项说明当前系统已经不只是“迁移完成”，而是已经具备了最小可持续使用的研究工作台形态。

#### 1.1.3 治理项：明确留待后续

以下内容不再视为“本轮主线是否完成”的判断条件，而是后续是否继续投入的治理项：

1. SLA、超时、升级路径、团队级人工工作流编排。
2. 更高层真实生产条件下的人工作流验收。
3. 历史 frozen replay 源在缺失原生 strategy_signals 时的 Layer B 解释精度继续提升。

后续如果确实需要继续投入，应优先把这些项目视为第二阶段治理工程，而不是继续混入“工作台迁移是否成功”的判断。

#### 1.1.4 第二阶段治理 Backlog：待按需启动

如果后续确认需要继续推进，建议按下面顺序恢复，而不是再次从“是否还要继续做工作台”开始发散。

P0：流程治理最小闭环

1. 为 workflow item 增加 SLA 字段，例如 due_at、age_bucket、last_transition_at。
2. 定义最小升级路径，例如 `unassigned -> assigned -> in_review -> ready_for_adjudication -> closed`，并明确谁可以推动状态迁移。
3. 在 Cross-Report Workflow Queue 中增加逾期、即将到期、长时间无人认领等过滤能力。
4. 输出最小审计轨迹，至少保留 assignee、workflow_status 的变更时间与操作者。

P1：团队级运转能力

1. 增加团队视角的队列摘要，例如按 assignee、status、report_name 的工作量分布。
2. 增加周度复盘入口，把 `ready_for_adjudication` 样本稳定沉淀成固定 review 节奏。
3. 明确 adjudication 结果如何映射回优化 backlog，避免停留在“有人看过”而不是“形成后续动作”。

P2：生产条件验收

1. 选一段真实使用窗口，验证多人协作下的 research feedback、batch label、queue ownership 与 adjudication 流程是否顺畅。
2. 补充生产条件下的操作手册或 SOP，尤其是交接、认领、复核、关闭四类动作。
3. 记录真实卡点，再决定是否要继续投入通知、提醒、权限或更复杂的任务系统。

P3：历史解释精度补强

1. 继续提高历史 frozen replay 源在缺失 strategy_signals 时的 Layer B 解释精度。
2. 如果无法获得更高保真原始信号，则应明确区分“兼容解释”和“原始证据”，避免研究员误判其可信度。

#### 1.1.5 当前建议动作：暂停新增开发，转入试用验收

基于当前已实现状态，本文档建议当前阶段不要继续把 Replay Artifacts 当作“主线开发中”项目推进，而是先转入试用验收。

建议原因如下：

1. 主线迁移已经完成，继续新增功能的收益边际明显下降。
2. 第一轮增强项已经足够支撑真实研究闭环，当前更缺的是使用证据，而不是更多界面或接口。
3. 第二阶段 backlog 中的大部分事项都属于治理问题，是否值得继续投入，必须依赖真实使用反馈，而不是继续从设计侧预判。

建议执行方式如下：

1. 以当前版本作为试用基线，不再主动追加新功能。
2. 组织一段有限窗口的真实使用，重点观察 report 浏览、feedback 写入、batch label、queue ownership 与周度复盘是否顺畅。
3. 把试用期间出现的问题分成两类：
   1. 阻断当前使用的缺陷，回到主线修复。
   2. 不阻断当前使用但影响团队效率的治理问题，纳入第二阶段 Backlog。
4. 只有当试用证据表明 SLA、升级流、通知、权限或更复杂协作机制已经成为主矛盾时，再启动第二阶段治理开发。

简化结论：截至当前版本，Replay Artifacts 更适合进入“试用验收 + 收集证据”阶段，而不是继续无边界扩展实现范围。

2026-03-26 补充状态：当前试用窗口已经不是停留在纸面计划。

1. 已建立 2026-03-26 至 2026-04-02 的专用试用窗口启动记录、问题台账、总结草稿与首日执行清单。
2. 已完成第一次真实后端/API 试用，验证 near-miss 阅读、selected 样本 feedback 写入、recent activity 回读，以及 Cross-Report Workflow Queue 的认领与取消认领。
3. 已补充前端侧证据：本地登录页可真实加载，且 Replay Artifacts 相关前端测试通过 2 个文件、5 个测试。
4. 同日已补齐已登录态前端真实点击流证据：真实登录后 `hedge_fund_token` 已成功落盘，并可通过顶部 `Replay` 入口打开 Replay Artifacts 工作台，看到 `Cross-Report Workflow Queue`、`Report Rail` 与主观察 report；当前最小试用证据链已经闭合。

### 1.2 已完成事项（详细清单）

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
- 已补充多交易日 live pipeline 自动化集成测试，验证 paper trading runtime 在连续 trade_date 下可稳定生成 selection_artifacts、写入 daily_events/current_plan.selection_artifacts，并把 research_feedback_summary 与 execution_plan_provenance 聚合进 session_summary.json。
- 已补充 watchlist 未承接 buy_order 时的执行阻塞原因透传，selection_snapshot.json 与 selection_review.md 现可展示 buy_order_blocker、reentry_review_until 等执行层约束信息。
- 已扩展现有 replay artifacts 后端/前端浏览面：后端可返回 selection_artifact_overview、按 trade_date 读取 selection snapshot/review，并支持以当前登录用户身份追加 research feedback；前端 Replay Artifacts 页面已可直接切换交易日查看 selection_review.md，结构化展示 selected/rejected、top_factors、Layer C analyst 共识、research prompts 与 execution blocker，并直接提交和筛选 research feedback，而无需手动翻 data/reports 目录或调用 CLI。
- 前端 Replay Artifacts 页面已进一步补齐 funnel_diagnostics 结构化 drilldown，可直接查看 layer_b、watchlist、buy_orders 三段过滤摘要、reason_counts 与代表性 ticker；feedback records 现按 created_at 倒序展示，并显式显示创建时间，便于研究员按时间线回看人工判断。
- Replay Artifacts 报告级摘要现已额外聚合并展示 `data_cache_benchmark` / `data_cache_benchmark_status`，页面可直接看到 post-session cache benchmark 的 success、failed、skipped 状态，以及 reuse_confirmed、disk_hit_gain、hit rate 变化和失败原因，无需手工打开 session_summary.json。
- 2026-03-25 已完成一次带 `--cache-benchmark` 的真实 frozen replay paper trading 验收：`data/reports/paper_trading_probe_20260205_cache_benchmark_20260325` 成功生成 `data_cache_benchmark.json`、`data_cache_benchmark.md` 与追加摘要后的 `window_review.md`，并确认 `reuse_confirmed=true`、`disk_hit_gain=6`、`first_hit_rate=0.0`、`second_hit_rate=1.0`，说明 report 级 cache benchmark 不只是 UI 字段可见，而是已经有真实运行样本支撑。
- Replay artifact 日级后端接口现已直接按 created_at 倒序返回 feedback_records，避免排序语义只存在于前端；localhost 环境下已完成一次真实登录、replay 列表、report/day detail、feedback append 与回读顺序校验的接口级冒烟验证。
- 已补充 Replay Artifacts feedback UI 自动化回归测试，覆盖填写表单、调用 appendSelectionFeedback、刷新 report/day detail，以及 feedback records 按 created_at 倒序展示的前端工作流，前端全量测试与生产构建已重新通过。
- 已补充 SQLite-backed replay feedback ledger：后端现会在读取 selection artifact 日详情或追加 feedback 时把 JSONL 记录同步入库，并新增 recent feedback activity 查询接口，供更高层复盘工作流按 report_name、reviewer 与时间序消费。
- Replay Artifacts workspace 右侧 inspector 现已直接消费 recent feedback activity 接口，按当前 report 展示 recent records、review_status/tag/reviewer 聚合与最新复核时间线；提交 feedback 后 activity 面板会同步刷新，前端定向回归、全量测试与生产构建均已通过。
- Replay Artifacts 页面现已补充 Batch Label Workspace，可在当前 trade date 下对多只 watchlist / near-miss 样本一次写入同一组 research feedback；后端已提供 batch append 接口，前端提交后会同步刷新 report detail、trade date detail 与 activity 面板。
- recent feedback activity 现已进一步扩展为 report 级 workflow queue：后端会按每个 symbol/review_scope 的最新记录生成 draft/final/adjudicated 队列，前端 inspector 可直接看到 pending draft queue 与 workflow status 分布，作为周度复盘和集中裁决的最小工作流入口。
- 2026-03-26 已继续补齐跨 report 的 workflow ownership：后端新增持久化 workflow item 表与跨 report 查询/更新接口，前端 Replay Artifacts workspace 已新增 Cross-Report Workflow Queue，可按 my queue / unassigned / all 查看待办，并直接执行 Assign to me / Unassign。
- 已新增操作手册 [docs/zh-cn/manual/replay-artifacts-stock-selection-manual.md](docs/zh-cn/manual/replay-artifacts-stock-selection-manual.md)，面向已登录用户详细说明如何使用 Replay Artifacts 页面完成选股复核、执行阻塞分析、near-miss 排查与 research feedback 回写。
- 已补充配套文档 [docs/zh-cn/manual/replay-artifacts-stock-selection-quickstart.md](docs/zh-cn/manual/replay-artifacts-stock-selection-quickstart.md) 与 [docs/zh-cn/manual/replay-artifacts-case-study-20260311-300724.md](docs/zh-cn/manual/replay-artifacts-case-study-20260311-300724.md)，分别面向“快速上手”和“真实 blocker 样本判读”两类场景，降低从登录成功到形成稳定复核习惯之间的学习门槛。
- 已补充 [docs/zh-cn/manual/replay-artifacts-newcomer-training-guide.md](docs/zh-cn/manual/replay-artifacts-newcomer-training-guide.md)，把 quickstart、值班卡、术语手册、长手册、试用计划串成一条新人可执行的培训与带教路径，降低“文档很多但不知道先看什么、学到什么程度才算上手”的接入摩擦。
- 已补充 [docs/zh-cn/manual/replay-artifacts-onboarding-readiness-scorecard.md](docs/zh-cn/manual/replay-artifacts-onboarding-readiness-scorecard.md)，把新人培训后的“是否已经可独立使用”收敛成统一评分维度、最低通过线与验收模板，避免带教过程只凭主观印象判断是否可以进入常规试用。
- 已补充术语解析文档 [docs/zh-cn/manual/replay-artifacts-report-terminology-guide.md](docs/zh-cn/manual/replay-artifacts-report-terminology-guide.md)，系统解释 Replay Artifacts 分析报告中的 report、selection、funnel、execution、feedback、workflow 与 cache benchmark 等核心术语，降低研究员把执行阻塞误判为选股失败、把流程状态误判为投资结论的风险。
- 已补充标签治理配套文档 [docs/zh-cn/manual/replay-artifacts-feedback-labeling-handbook.md](docs/zh-cn/manual/replay-artifacts-feedback-labeling-handbook.md)，统一说明 primary_tag、tags、review_status 与 research_verdict 的职责边界，以及 6 个受控标签在 selected、near-miss 和 execution blocker 场景中的使用口径，降低多人写 feedback 时的语义漂移风险。
- 已补充周度复盘工作流文档 [docs/zh-cn/manual/replay-artifacts-weekly-review-workflow.md](docs/zh-cn/manual/replay-artifacts-weekly-review-workflow.md)，将日常 `draft`、稳定 `final` 与争议样本 `adjudicated` 串成一套最小团队复盘节奏，便于将页面浏览、标签治理与后续系统优化 backlog 直接衔接。
- 已补充试用验收手册 [docs/zh-cn/manual/replay-artifacts-trial-acceptance-plan.md](docs/zh-cn/manual/replay-artifacts-trial-acceptance-plan.md)，用于在暂停新增开发后按统一窗口验证 report 浏览、feedback 写入、batch label、queue ownership 与周度复盘是否已足够支撑真实使用。
- 2026-03-26 已将试用验收从模板推进到窗口级实操：新增 [docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402.md](docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402.md)、[docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402-issue-log.md](docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402-issue-log.md)、[docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402-summary.md](docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402-summary.md) 与 [docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402-day1-checklist.md](docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402-day1-checklist.md)，使试用窗口具备独立的证据沉淀载体。
- 同日已进一步补齐试用证据沉淀层：新增 [docs/zh-cn/manual/replay-artifacts-trial-observation-sheet.md](docs/zh-cn/manual/replay-artifacts-trial-observation-sheet.md) 与 [docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402-observations.md](docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402-observations.md)，使试用流程不只记录问题和总结，也能结构化沉淀“链路通过但仍有语义摩擦”的真实使用观察。
- 已补充 [docs/zh-cn/manual/research-conclusion-to-optimization-backlog-handbook.md](docs/zh-cn/manual/research-conclusion-to-optimization-backlog-handbook.md)，把周度复盘中形成的研究结论进一步标准化映射到 Layer B、Layer C、Execution、Threshold、Explainability 五类优化动作，降低“能复盘但不会落任务”的交付断层。
- 已完成一次真实 live pipeline 纸面交易窗口验收：2026-03-16 至 2026-03-23 使用 MiniMax-M2.7 运行后成功生成 selection_artifacts、daily_events.jsonl、pipeline_timings.jsonl 与 session_summary.json，并形成窗口复盘文档 data/reports/paper_trading_window_20260316_20260323_live_m2_7_20260323/window_review_20260316_20260323.md；该窗口确认当前 artifact 机制在真实 live pipeline 下也能稳定解释“前置筛选无候选”“Layer C 否决 near-miss”与“T 日生成计划、T+1 执行”的实际执行链路。
- 2026-03-26 已完成一轮试用窗口内的真实使用证据回填：本地后端/API 已验证 2026-03-17 的 near-miss `002916`、2026-03-20 的 selected `300724` feedback 写入，以及 2026-03-23 的 execution blocker 与 workflow item 认领/取消认领；同日还确认本地 Vite 登录页可达，补充 Replay Artifacts 相关前端测试通过 5/5，完成一次真实 batch feedback 写入，验证 `2026-02-24 / 300724, 000960` 可同步进入 activity 与 workflow queue，并完成一次真实 `draft -> final` 推进，验证 `2026-03-20 / 300724` 可进入 `ready_for_adjudication`；随后又补齐真实浏览器登录与顶部 `Replay` 入口点击流，确认认证态前端可直接进入 Replay Artifacts 工作台。

### 1.3 未完成事项（治理项）

- research_feedback.jsonl 已具备最小读取、聚合、标签治理、CLI 操作、session 级 summary 接入、replay viewer 内最小可写 UI、对应前端自动化回归，以及 SQLite-backed ledger、recent activity 查询接口、report 级 activity 面板、批量标注工作台、基于最新状态的 workflow queue 与跨 report 的指派/归属入口；当前剩余缺口主要收敛为 SLA 级别的人工作流编排与真实生产条件下的流程验收。
- 轻量级 backtesting / paper trading 运行级集成测试已补齐，更长窗口 frozen replay 验证已完成一次，且现已补充对应的 W1 级别 frozen replay 自动化集成测试；真实 live pipeline 的最小运行级窗口验收也已完成一次，且其最小自动化集成测试亦已补齐，但更高层人工工作流集成仍未完成。当前已补上首轮试用窗口内的真实后端/API 使用证据、真实 batch feedback 样本证据、真实 `draft -> final` 推进证据，以及前端页面加载、定向前端回归和已登录态点击流证据；剩余未完成项已收敛为团队级 SLA、升级路径与更长期的真实生产协作治理。
- 历史 frozen replay 源的 Layer B 解释已补齐回退兼容，但回退摘要只能基于 plan.logic_scores 与 strategy_weights 或 adjusted_weights 近似重建，精度仍低于新源中的原生 strategy_signals。

建议理解方式：以上未完成项默认全部归入“第二阶段治理 Backlog”，除非后续有新的使用证据证明这些项已经成为当前主矛盾，否则不建议再把它们并回本轮主线。

### 1.4 已完成验收记录

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

2026-03-25 继续补齐了多交易日 live pipeline 自动化集成测试：

1. 在 tests/backtesting/test_paper_trading_runtime.py 中新增多 trade_date live pipeline 测试，覆盖 2024-03-01 与 2024-03-04 两个交易日的连续 post-market 计划生成与 T+1 执行衔接。
2. 该测试自动验证两个 trade_date 对应的 selection_snapshot.json、selection_review.md、research_feedback.jsonl 均成功落盘。
3. daily_events.jsonl 中两个交易日的 current_plan.selection_artifacts 均保持 write_status=success，且 snapshot_path 会落到各自 trade_date 目录。
4. session_summary.json 中的 research_feedback_summary 已正确聚合为 feedback_file_count=2、trade_date_count=2，同时 execution_plan_provenance 也会按两天观测汇总。
5. 这轮补强意味着“live pipeline 自动化集成测试缺位”这一工程缺口已被最小可维护测试覆盖掉，不再只依赖手工窗口验收。

2026-03-25 继续补齐了更长窗口 frozen replay 自动化集成测试：

1. 在 tests/backtesting/test_paper_trading_runtime.py 中新增 W1 级别 frozen replay 长窗口测试，覆盖 2024-03-01 至 2024-03-07 共 5 个 trade_date 的连续 current_plan 回放。
2. 该测试自动验证 5 个 trade_date 对应的 selection_snapshot.json、selection_review.md、research_feedback.jsonl 全部成功落盘。
3. daily_events.jsonl 与 pipeline_timings.jsonl 中 5 个 trade_date 的 current_plan.selection_artifacts 均保持 write_status=success，且 snapshot_path 会落到各自 trade_date 目录。
4. session_summary.json 中的 daily_event_stats.day_count、research_feedback_summary.feedback_file_count 与 trade_date_count 会稳定聚合到 5 天窗口，不再只依赖 2026-03-23 的手工 W1 验收样本。
5. 这轮补强意味着“更长窗口 frozen replay 只做过手工验收”这一缺口也已经转为可回归的自动化覆盖。

2026-03-25 继续补齐了 Replay Artifacts feedback UI 自动化回归测试：

1. 在 app/frontend/src/components/settings/replay-artifacts.test.tsx 中新增 feedback workflow 测试，覆盖表单填写、appendSelectionFeedback 调用、提交后 detail/day detail 刷新，以及 feedback records 倒序展示。
2. 该测试会验证 review_scope 会跟随 symbolOptions 推导为 watchlist，额外 tags 会按逗号切分，并把 confidence、review_status、research_verdict、notes 一并提交给前端 API 层。
3. 新增回归后 app/frontend 执行 npm test -- --run 与 npm run build 已重新通过，前端测试集现为 4 个文件、6 个测试全部通过。
4. 这轮补强意味着 feedback 的最小 UI 写入闭环不再只依赖手工点击与 localhost 冒烟，而是有可回归的自动化保护。

2026-03-25 继续补齐了 Replay feedback 的数据库接入与 activity 查询：

1. 在 app/backend/database/models.py 中新增 replay_research_feedback_ledger 表，并补充对应 Alembic migration，用于把 JSONL feedback 规范化同步到 SQLite。
2. ReplayArtifactService 现会在读取 selection artifact 日详情和追加 feedback 后自动同步对应 trade_date 的 feedback ledger，保持数据库视图与 research_feedback.jsonl 一致。
3. 后端新增 recent feedback activity 查询接口，可按 report_name、reviewer 与 limit 检索最近反馈记录，并返回 review_status、tag、reviewer、report 维度的聚合统计。
4. tests/backend/test_replay_artifact_service.py 与 tests/backend/test_replay_artifact_routes.py 已补充对应断言，验证历史 JSONL 同步入库、append 后 activity 可见以及 activity 路由返回语义；本轮后端相关测试共 9 个通过。
5. 这轮补强意味着“feedback 完全不接数据库”这一工程缺口已被最小可维护实现覆盖，后续剩余重点转向批量标注与更高层人工工作流编排。

2026-03-25 同日继续补齐了 Replay feedback activity 的前端消费闭环：

1. app/frontend/src/services/replay-artifact-api.ts 已补充 getFeedbackActivity API，并为 recent records、status/tag/reviewer 聚合定义稳定前端类型。
2. Replay Artifacts workspace 的右侧 inspector 已新增 Feedback Activity 卡片，按当前 report 展示 recent records、review_status 汇总、top tags 与 recent reviewers，避免研究员切换到数据库或接口层手工查活动轨迹。
3. 在追加 feedback 成功后，前端现会同步刷新 report detail、trade date detail 与 report 级 feedback activity，确保工作台内的最近复核时间线不会滞后于 research_feedback.jsonl 与 SQLite ledger。
4. app/frontend/src/components/replay-artifacts/replay-artifacts-inspector.test.tsx 与 app/frontend/src/components/settings/replay-artifacts.test.tsx 已补充对应断言；本轮执行 npm test -- --run 与 npm run build 均通过，随后前端全量测试仍保持 4 个文件、6 个测试全部通过。
5. 这轮补强意味着 recent activity 不再只是“后端可查但页面不可见”的隐式能力，而是已经成为 Replay Artifacts 工作台的一部分；当前剩余重点仍是批量标注工作台与更高层人工工作流编排。

2026-03-25 同日继续补齐了 Replay feedback 的批量标注工作台与最小 workflow queue：

1. 后端新增 batch append 接口，可在单次请求内为当前 trade_date 的多只 selected / near-miss 样本追加同一组 research feedback，并只重算一次目录级 summary 与 SQLite ledger 同步。
2. Replay Artifacts 主工作台已新增 Batch Label Workspace，可勾选多只 watchlist / near-miss 样本，统一写入 primary_tag、tags、review_status、research_verdict、confidence 与 notes。
3. recent feedback activity 现已补充 workflow_status_counts 与按 symbol/review_scope 最新记录归档的 workflow_queue，前端 inspector 可直接展示 pending draft queue，减少周度复盘时手工筛 JSONL 或数据库的成本。
4. tests/backend/test_replay_artifact_service.py、tests/backend/test_replay_artifact_routes.py、app/frontend/src/components/settings/replay-artifacts.test.tsx 与 app/frontend/src/components/replay-artifacts/replay-artifacts-inspector.test.tsx 已补充对应断言；本轮执行 backend pytest、前端定向回归、前端全量测试与 npm run build 均通过。
5. 这轮补强意味着“批量标注工作台或更高层人工工作流编排完全缺位”的状态已被最小可维护实现替代；当前更高层剩余缺口主要收敛为跨 report 的任务指派/归属、团队级 SLA 与真实生产条件下的流程验收。

2026-03-26 已继续补齐跨 report 的 replay feedback ownership workflow：

1. 后端新增 ReplayResearchFeedbackWorkflowItem 表与对应 Alembic migration，用于持久化每个 report/trade_date/symbol/review_scope 的最新 workflow ownership 状态，而不是把 assignee 语义硬塞进 append-only ledger。
2. replay_artifact_service 新增跨 report 的 list_workflow_queue / update_workflow_item，并在单条或批量 feedback append 后自动同步 workflow item，确保 report 内 activity 面板与全局 queue 使用同一份最新状态。
3. Replay Artifacts 主工作台已新增 Cross-Report Workflow Queue，可切换 my queue、unassigned、all，并直接对条目执行 Assign to me / Unassign。
4. tests/backend/test_replay_artifact_service.py、tests/backend/test_replay_artifact_routes.py 与 app/frontend/src/components/settings/replay-artifacts.test.tsx 已补充对应断言；本轮 backend pytest、前端定向回归与 npm run build 均通过。
5. 这意味着“跨 report 指派/归属完全缺位”的状态已被最小可操作实现替代；当前高层剩余缺口进一步收敛为团队级 SLA、升级路径与真实生产条件下的流程验收。

2026-03-23 已完成一次“更长窗口 frozen replay”验收，并顺带补强了 execution blocker 的研究可解释性：

1. frozen_plan_source：data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319/daily_events.jsonl。
2. output_dir：data/reports/paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323。
3. 共生成 24 个 trade_date 子目录和 1 个 selection_artifacts/research_feedback_summary.json，session_summary.json 中也同步记录了 selection_artifact_root 与 research_feedback_summary。
4. pipeline_timings.jsonl 与 daily_events.jsonl 中每个 trade_date 的 current_plan.selection_artifacts 均保持 write_status=success。
5. 这次长窗口验证说明 selection artifact 机制不仅在 1 到 2 天样本中可用，在 W1 级别多日 replay 中也能稳定落盘与回填。
6. 基于该窗口已补充统计复盘文档 data/reports/paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323/gating_summary_20260202_20260313.md；其中汇总显示 24 个 trade_date 共 4800 个 candidate 中有 4750 个直接被 Layer B `below_fast_score_threshold` 过滤，进一步支持“候选 scarcity 主因在 Layer B、near-miss 否决主因在 Layer C、300724 属于稳定边界样本”的分层判断。

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

2026-03-23 同日还完成了一次“真实 live pipeline 窗口复盘”验收，验证方式为 2026-03-16 至 2026-03-23 的纸面交易运行：

1. output_dir：data/reports/paper_trading_window_20260316_20260323_live_m2_7_20260323。
2. 运行模式为 live_pipeline，模型路由为 MiniMax:MiniMax-M2.7，成功生成 session_summary.json、daily_events.jsonl、pipeline_timings.jsonl 与 selection_artifacts/ 日期目录。
3. 该窗口共覆盖 6 个交易日，其中 3 个交易日因为 Layer B `below_fast_score_threshold` 未产生任何 high_pool 样本，1 个交易日出现 near-miss `002916` 并被 Layer C 否决，2 个交易日出现 `300724` 进入 watchlist。
4. `300724` 在 2026-03-20 生成 buy_order，并在 2026-03-23 通过 daily_events.jsonl 中的 `executed_trades.300724=100` 得到实际执行确认，同时 2026-03-23 当天新的 post-market plan 又因 `position_blocked_score` 未继续生成新的 buy_order。
5. 这次窗口补强了一个此前只在代码层推断、未在真实样本中明确写下的结论：当前 paper trading pipeline 的执行时序是“T 日 post-market 生成计划，T+1 交易日执行 pending plan”，而 event 持久化中的实际成交字段名为 `executed_trades`，不是 `executed_orders`。
6. 该次验收产出了专门的窗口复盘文档 data/reports/paper_trading_window_20260316_20260323_live_m2_7_20260323/window_review_20260316_20260323.md，可作为后续 live pipeline 复盘样板。

2026-03-25 还完成了一次“report 级 cache benchmark 真实样本”验收，验证方式为 1 天 frozen replay paper trading 并启用 post-session benchmark：

1. frozen_plan_source：data/reports/logic_stop_threshold_scan_m0_20/daily_events.jsonl。
2. output_dir：data/reports/paper_trading_probe_20260205_cache_benchmark_20260325。
3. 成功生成 session_summary.json、daily_events.jsonl、pipeline_timings.jsonl、selection_artifacts/ 以及 `data_cache_benchmark.json`、`data_cache_benchmark.md`、追加摘要后的 `window_review.md`。
4. session_summary.json 中的 `data_cache_benchmark_status.write_status=success`，且 artifacts 已回填 benchmark JSON、Markdown 和 appended report 路径。
5. benchmark 汇总确认 `reuse_confirmed=true`、`disk_hit_gain=6`、`miss_reduction=6`、`set_reduction=6`、`first_hit_rate=0.0`、`second_hit_rate=1.0`。
6. 该次样本进一步证明：Replay Artifacts 页面中展示的 cache benchmark 指标已经有真实 report 支撑，而不是仅靠 mock、单测或静态 session_summary 字段推断。

2026-03-26 还完成了一次“试用窗口内的首轮真实使用”验收，验证方式为本地后端/API 实测加前端可达性与定向回归补证：

1. 试用窗口文档：docs/zh-cn/manual/replay-artifacts-trial-window-20260326-20260402.md。
2. 已在本地启动 FastAPI，并以真实管理员用户 einstein 完成 `/auth/me`、`/replay-artifacts/`、report detail、day detail、feedback append、feedback activity 与 workflow queue 的调用验证。
3. 2026-03-17 的 near-miss `002916` 已确认可读，2026-03-20 的 `300724` 已成功写入 `draft` feedback 并在 activity 中回读，2026-03-23 的 `300724` 已确认 `position_blocked_score` blocker 可读且支持 `Assign to me` / `Unassign`。
4. 已实际启动本地 Vite 前端服务，并确认 `http://127.0.0.1:5173/` 可渲染登录页，首屏可见 `AI Hedge Fund`、`QUANTITATIVE INTELLIGENCE PLATFORM`、用户名、密码、登录与创建新账户等元素。
5. 已运行 Replay Artifacts 相关前端测试 `app/frontend/src/components/settings/replay-artifacts.test.tsx` 与 `app/frontend/src/components/replay-artifacts/replay-artifacts-inspector.test.tsx`，结果为 2 个测试文件、5 个测试全部通过。
6. 同日还完成了一次真实 batch feedback 写入：针对 `paper_trading_probe_20260224_20260225_selection_artifact_validation_20260322 / 2026-02-24` 的两个 near-miss 样本 `300724` 与 `000960`，批量接口返回 `appended_count=2`，且 recent activity 与 workflow queue 均立即出现对应条目。
7. 同日还完成了一次真实 `draft -> final` 推进：主观察 report 中的 `2026-03-20 / 300724` 在追加 `final` feedback 后，workflow item 由 `unassigned` 自动切换为 `ready_for_adjudication`，report 级 workflow_status_counts 也从 `draft=2` 变为 `final=1, draft=1`。
8. 这次窗口内验收说明：当前系统已经具备首轮前后端两侧、batch 能力、最小周度复盘闭环以及已登录态前端点击流的真实试用证据；后续工作已转为继续积累常规使用样本，并观察是否出现需要纳入第二阶段治理 Backlog 的真实摩擦。

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

1. feedback 与更高层人工工作流、标签平台或批量标注工作台的集成测试。

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
8. 2026-03-25 已补充多交易日 live pipeline 自动化集成测试，用于覆盖连续 trade_date 下的 selection_artifacts 与 session_summary 聚合一致性。
9. 2026-03-25 已补充对应的 W1 级别 frozen replay 自动化集成测试，用于覆盖长窗口 current_plan 回放下的 selection_artifacts 连续落盘、daily_events/pipeline_timings 一致性以及 research_feedback_summary 聚合稳定性。
10. 2026-03-25 已补充 Replay Artifacts feedback UI 自动化回归测试，用于覆盖前端最小写入闭环与 feedback records 时间序排序语义。
11. 2026-03-25 已补充 Replay feedback 的 SQLite ledger 与 recent activity 查询接口，并通过 backend service/route 测试验证历史 JSONL 同步与追加后可查询语义。
12. 2026-03-25 已补充 Replay Artifacts workspace 对 recent activity 的前端消费与自动刷新，并通过前端定向回归、全量测试与生产构建验证。
13. 2026-03-25 已补充 Batch Label Workspace 与基于最新 review_status 的 workflow queue，使批量标注和 pending draft 排队首次进入 Replay Artifacts 工作台。
14. 2026-03-26 已补充跨 report 的 workflow ownership queue 与 Assign to me / Unassign 入口，使“我的待办”和“未归属待办”首次进入同一工作台。
15. 但这仍然不能完全替代真实生产参数、真实外部依赖条件下的更高层人工工作流验收。

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
