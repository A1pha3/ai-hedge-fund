# Replay Artifacts 试用问题台账 2026-03-26 至 2026-04-02

> 关联文档：
>
> 1. [Replay Artifacts 试用验收计划](./replay-artifacts-trial-acceptance-plan.md)
> 2. [Replay Artifacts 试用窗口启动记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402.md)
> 3. [Replay Artifacts 试用问题记录模板](./replay-artifacts-trial-issue-log-template.md)
> 4. [本窗口首日执行清单](./replay-artifacts-trial-window-20260326-20260402-day1-checklist.md)

## 1. 台账用途

这份文件是当前试用窗口的实际问题台账，不是空模板。

本窗口内出现的问题统一记录在这里，避免问题散落在聊天、周会记录或临时笔记中。

编号规则建议固定为：`RA-TRIAL-20260326-XX`。

---

## 2. 本窗口固定信息

- 试用窗口：2026-03-26 ~ 2026-04-02
- 默认记录人：einstein
- 主观察 report：`paper_trading_window_20260316_20260323_live_m2_7_20260323`
- 长窗口补充 report：`paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323`
- cache benchmark 补充 report：`paper_trading_probe_20260205_cache_benchmark_20260325`

---

## 3. 问题清单索引

当前状态：暂无已登记问题；2026-03-26 已完成窗口建档、样本锁定与第一次真实后端/API 试用，当前未发现需要单独立项归档的问题。

录入规则：

1. A 类问题单独优先记录，并在当天判断是否需要立即修复。
2. B 类问题记录后不在窗口中途扩实现，先累积证据。
3. C 类问题只做归档，不纳入本轮成败判断。

### 3.1 2026-03-26 日收口记录

- 当日状态：已建档，且已完成首轮真实工作台操作与证据回填
- 当日完成事项：
	1. 窗口启动记录已落盘。
	2. 主观察 report、长窗口补充 report 与 cache benchmark 补充 report 已固定。
	3. 问题台账与总结草稿已创建并建立互链。
- 当日问题结论：当日未发现新问题。
- 备注：今天的动作仍属于试用建档与执行准备，不应被误判为已经完成一次真实工作台日常使用。

下一步建议直接按下面文档开始第一次真实工作台操作：

1. [本窗口首日执行清单](./replay-artifacts-trial-window-20260326-20260402-day1-checklist.md)

---

## 4. 首日执行记录

这一节用于记录“已经实际操作，但未必有问题”的事实，避免台账只剩缺陷而没有通过证据。

### 4.1 首日执行回填卡

- 执行日期：2026-03-26
- 执行人：einstein
- 是否完成真实工作台操作：是
- 使用清单：[本窗口首日执行清单](./replay-artifacts-trial-window-20260326-20260402-day1-checklist.md)

执行方式说明：

1. 本次首轮真实试用以本地后端/API 实测方式完成。
2. 已实际启动 FastAPI 服务并调用 replay-artifacts 相关接口。
3. 本次已覆盖真实数据读取、feedback 写入、activity 回读和 workflow queue 认领/取消认领。
4. 前端点击流仍可在后续补充，但本次不影响“首轮真实调用已完成”的事实记录。

步骤回填：

1. near-miss 阅读链路
	- trade_date：`2026-03-17`
	- 样本：`002916`
	- 执行结果：已通过。真实接口返回 `rejection_stage=watchlist`、`decision_avoid` 与 `score_final_below_watchlist_threshold`，near-miss 阅读链路完整可读。
	- 是否发现问题：否
	- 如有问题，对应编号：无

2. selected 与 feedback 写入链路
	- trade_date：`2026-03-20`
	- 样本：`300724`
	- 执行结果：已通过。真实接口成功读取 selected 样本，并追加 1 条 `draft` feedback，reviewer 为 `einstein`。
	- 是否成功写入 feedback：是
	- 是否发现问题：否
	- 如有问题，对应编号：无

3. execution blocker 与 queue ownership 链路
	- trade_date：`2026-03-23`
	- 样本：`300724`
	- 执行结果：已通过。真实接口返回 `buy_order_blocker=position_blocked_score`；随后成功追加对应 feedback，并对该 trade_date 的 workflow item 完成 `Assign to me` 与 `Unassign`。
	- 是否成功完成 queue 动作：是
	- 是否发现问题：否
	- 如有问题，对应编号：无

首日最小结论：2026-03-26 已完成第一次真实后端/API 试用。三条核心链路均通过，当前未发现 A 类阻断缺陷或 B 类治理摩擦项，因此本轮暂不新增正式问题编号。

### 4.2 前端补充验证回填卡

- 执行日期：2026-03-26
- 执行人：einstein
- 是否完成前端真实可达性验证：是
- 是否完成前端回归测试验证：是

执行方式说明：

1. 已实际启动本地 Vite 前端服务，并验证 http://127.0.0.1:5173/ 可访问。
2. 已抓取前端首屏可见文本，确认登录页真实渲染出 `AI Hedge Fund`、`QUANTITATIVE INTELLIGENCE PLATFORM`、用户名、密码、登录、创建新账户等元素。
3. 已运行 Replay Artifacts 直接相关前端测试：`src/components/settings/replay-artifacts.test.tsx` 与 `src/components/replay-artifacts/replay-artifacts-inspector.test.tsx`。
4. 测试结果为 2 个测试文件、5 个测试全部通过，可作为前端侧回归证据。
5. 同日已继续补齐“已登录态下进入 Replay Artifacts 页面并完成真实点击流”的浏览器级证据，说明前端入口不只是在未登录态可达，而且已能在真实会话下打开工作台主体。

结果回填：

1. 前端页面可达性
	- 验证地址：`http://127.0.0.1:5173/`
	- 执行结果：已通过。登录页首屏文本可读，说明前端应用已成功启动并完成未登录态渲染。
	- 是否发现问题：否
	- 如有问题，对应编号：无

2. Replay Artifacts 前端回归测试
	- 验证范围：settings 提交 feedback、batch feedback、inspector 渲染
	- 执行结果：已通过。`2 passed / 5 passed`。
	- 是否发现问题：否
	- 如有问题，对应编号：无

前端补充最小结论：2026-03-26 已补充前端登录页加载级证据、Replay Artifacts 相关回归测试证据，以及已登录态真实点击流证据；当前未发现新的 A 类或 B 类问题。

### 4.3 Batch Label 对应批量反馈回填卡

- 执行日期：2026-03-26
- 执行人：einstein
- 是否完成真实批量反馈写入：是

执行方式说明：

1. 本次验证使用真实管理员登录而非测试桩，先通过 `/auth/login` 获取 token，再调用 replay-artifacts 批量反馈接口。
2. 选用真实样本 `paper_trading_probe_20260224_20260225_selection_artifact_validation_20260322 / 2026-02-24`，该 trade_date 下存在两个 near-miss 样本：`300724` 与 `000960`。
3. 在写入前，该 trade_date 的 `feedback_records` 数量为 0；执行批量追加后，`feedback_records` 数量变为 2。
4. 批量写入后，recent activity 与 workflow queue 均立即可见两条新记录，说明 Batch Label 对应的后端/API 链路已真实成立。
5. 本次尚未补齐 Batch Label Workspace 的浏览器点击流证据，但已经确认其后端能力与数据落盘链路在真实样本下可用。

结果回填：

1. 批量 feedback 写入
	- 目标 report / trade_date：`paper_trading_probe_20260224_20260225_selection_artifact_validation_20260322 / 2026-02-24`
	- 目标样本：`300724`、`000960`
	- 执行结果：已通过。批量接口返回 `appended_count=2`，两条记录的 `review_scope` 均为 `near_miss`。
	- 是否发现问题：否
	- 如有问题，对应编号：无

2. activity 与 queue 回读
	- 执行结果：已通过。recent activity 中已出现 `300724` 与 `000960`，workflow_status_counts 为 `draft=2`，workflow queue 中对应条目数量为 2。
	- 是否发现问题：否
	- 如有问题，对应编号：无

Batch Label 最小结论：2026-03-26 已完成一次真实批量反馈写入，Batch Label 对应的批量链路、activity 聚合与 queue 同步均已通过；当前未发现新的 A 类或 B 类问题。

### 4.4 周度复盘闭环回填卡

- 执行日期：2026-03-26
- 执行人：einstein
- 是否完成 `draft -> final` 推进：是

执行方式说明：

1. 本次验证直接针对主观察 report 中已存在的 `draft` 样本执行，避免用额外样本替代真实周度复盘对象。
2. 选用 `paper_trading_window_20260316_20260323_live_m2_7_20260323 / 2026-03-20 / 300724`，该样本此前已存在 1 条 `draft` feedback。
3. 本次以真实管理员登录后追加 1 条 `final` feedback，作为最小周度复盘推进动作。
4. 追加前，该样本在 workflow queue 中的最新状态为 `draft / unassigned`；追加后切换为 `final / ready_for_adjudication`。
5. report 级 recent activity 的 `workflow_status_counts` 也从 `draft=2` 变为 `final=1, draft=1`，说明周度复盘推进已真实影响队列状态。

结果回填：

1. `draft -> final` 推进
	- 目标 report / trade_date / symbol：`paper_trading_window_20260316_20260323_live_m2_7_20260323 / 2026-03-20 / 300724`
	- 执行结果：已通过。新追加记录的 `review_status=final`，`review_scope=watchlist`。
	- 是否发现问题：否
	- 如有问题，对应编号：无

2. queue 与 activity 同步
	- 执行结果：已通过。对应 workflow item 的最新状态由 `draft / unassigned` 切换为 `final / ready_for_adjudication`；report 级 `workflow_status_counts` 同步更新为 `final=1, draft=1`。
	- 是否发现问题：否
	- 如有问题，对应编号：无

周度复盘最小结论：2026-03-26 已完成一次真实 `draft -> final` 推进，说明当前工作台已经具备最小周度复盘闭环能力；当前未发现新的 A 类或 B 类问题。

### 4.5 已登录态前端点击流回填卡

- 执行日期：2026-03-26
- 执行人：einstein
- 是否完成真实浏览器点击流：是

执行方式说明：

1. 本次验证通过真实浏览器自动化执行，而非仅依赖接口调用或页面文本抓取。
2. 已在本地打开 `http://127.0.0.1:5173/`，使用真实管理员账户 `einstein` 登录，并确认 `hedge_fund_token` 已写入 localStorage。
3. 登录后通过顶部 `Replay` 入口完成真实点击，成功进入 Replay Artifacts 工作台。
4. 页面已真实渲染 `Replay Artifacts`、`Cross-Report Workflow Queue`、`Report Rail`，且主观察 report `paper_trading_window_20260316_20260323_live_m2_7_20260323` 已在工作台中可见。
5. 这说明当前前端主入口、认证态保持与 Replay 工作台装载链路均已通过浏览器级验证。

结果回填：

1. 登录态建立
	- 验证地址：`http://127.0.0.1:5173/`
	- 执行结果：已通过。真实登录后 `hedge_fund_token` 已存在，说明前端认证态已成功建立。
	- 是否发现问题：否
	- 如有问题，对应编号：无

2. Replay 工作台进入
	- 执行结果：已通过。点击顶部 `Replay` 后，页面已显示 `Replay Artifacts`、`Cross-Report Workflow Queue`、`Report Rail` 与主观察 report。
	- 是否发现问题：否
	- 如有问题，对应编号：无

已登录态点击流最小结论：2026-03-26 已完成一次真实前端登录与 Replay 工作台进入验证，Replay Artifacts 的前端主入口证据已补齐；当前未发现新的 A 类或 B 类问题。

---

## 5. 问题记录

### RA-TRIAL-20260326-01

- 当前状态：预留
- 记录日期：待填写
- 记录人：待填写
- 分类级别：待填写
- 对应 report_name：待填写
- 对应 trade_date：待填写
- 影响动作：待填写
- 现象：待填写
- 处理建议：待填写
- 证据路径：待填写
- 最终结论：待填写

### RA-TRIAL-20260326-02

- 当前状态：预留
- 记录日期：待填写
- 记录人：待填写
- 分类级别：待填写
- 对应 report_name：待填写
- 对应 trade_date：待填写
- 影响动作：待填写
- 现象：待填写
- 处理建议：待填写
- 证据路径：待填写
- 最终结论：待填写

---

## 6. 每日收口要求

每天结束前，至少补齐下面三件事：

1. 是否出现新的 A 类阻断问题。
2. 是否出现可复现的 B 类治理摩擦。
3. 当天新增问题是否已经挂到对应 report 与 trade_date。

如果当天没有问题，也建议追加一句“当日未发现新问题”，避免后续回看时无法区分“没人记录”还是“确实无问题”。

当前已记录：2026-03-26 当日已完成第一次真实后端/API 试用、一次真实批量反馈写入、一次最小周度复盘闭环，并补充前端登录页加载、Replay Artifacts 前端测试以及已登录态前端点击流证据；未发现新问题，正式问题编号仍为 0。