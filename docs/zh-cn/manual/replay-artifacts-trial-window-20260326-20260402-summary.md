# Replay Artifacts 试用总结草稿 2026-03-26 至 2026-04-02

> 关联文档：
>
> 1. [Replay Artifacts 试用验收计划](./replay-artifacts-trial-acceptance-plan.md)
> 2. [Replay Artifacts 试用窗口启动记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402.md)
> 3. [本窗口已填观察记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-observations.md)
> 4. [Replay Artifacts 试用问题台账 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-issue-log.md)
> 5. [Replay Artifacts 试用总结报告模板](./replay-artifacts-trial-summary-template.md)
> 6. [本窗口首日执行清单](./replay-artifacts-trial-window-20260326-20260402-day1-checklist.md)

## 1. 基本信息

- 试用窗口：2026-03-26 ~ 2026-04-02
- 总结日期：2026-03-26（阶段性回填）
- 总结人：einstein
- 参与角色：日常复核人、周度汇总人、裁决人（当前由 einstein 兼任）
- 覆盖 report 范围：`paper_trading_window_20260316_20260323_live_m2_7_20260323`、`paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323`、`paper_trading_probe_20260205_cache_benchmark_20260325`
- 覆盖 trade_date 范围：`2026-02-24`、`2026-03-17`、`2026-03-20`、`2026-03-23`

---

## 2. 试用目标回顾

本轮试用原始目标：

1. 验证 report 浏览、trade date 切换、review 阅读与 feedback 回写是否稳定可用。
2. 验证 Batch Label Workspace 是否在真实场景中节省重复操作。
3. 验证 Cross-Report Workflow Queue 是否足以支持最小认领与流转。
4. 验证周度复盘是否能把 `draft` 推进到 `final` 或 `adjudicated`，并形成 backlog 输入。

本轮试用是否覆盖上述四项：是

如果否，缺失项是：无

---

## 3. 试用执行摘要

- 实际试用时长：2026-03-26 当前累计为 1 次真实后端/API 试用、1 次真实批量反馈写入、1 次最小周度复盘闭环，并已补充 1 次前端登录页加载冒烟验证、1 轮 Replay Artifacts 相关前端回归测试，以及 1 次已登录态前端真实点击流验证
- 实际使用人数：1（当前默认）
- 是否完成日常使用：是
- 是否完成至少一次周度复盘：是
- 是否使用了 Batch Label Workspace：已满足最小验证，对应批量反馈真实样本写入已完成，且已登录态前端工作台进入证据已补齐
- 是否使用了 Cross-Report Workflow Queue：是

补充说明：2026-03-26 已完成第一次真实后端/API 试用，覆盖 near-miss 阅读、selected 样本 feedback 写入、activity 回读，以及 execution blocker 对应的 queue 认领/取消认领；同日还完成一次真实批量反馈写入，确认两个 near-miss 样本可通过 batch 接口同时写入并同步进入 activity 与 workflow queue；此外，已针对主观察 report 中的 `2026-03-20 / 300724` 执行一次真实 `draft -> final` 推进，确认 workflow item 可从 `unassigned` 自动进入 `ready_for_adjudication`；同时补充完成前端登录页加载冒烟验证、Replay Artifacts 相关前端测试 5/5 通过，以及已登录态下从前端真实登录并点击进入 Replay Artifacts 工作台的浏览器级证据。当前已具备前后端两侧与最小周度复盘的完整运行证据。

这些证据目前也已经整理成逐条观察记录，见 [本窗口已填观察记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-observations.md)，后续总结可直接按该文件做归纳，而不需要只依赖问题台账反推试用过程。

### 3.1 首日执行回填速记

用于在第一次真实工作台操作完成后，先快速回填最小事实，再决定是否需要写正式问题单。

#### near-miss 阅读链路

- 目标样本：`2026-03-17 / 002916`
- 是否完成：是
- 最小结论：真实接口返回 near-miss 关键信息完整，阅读链路通过。

#### selected 与 feedback 写入链路

- 目标样本：`2026-03-20 / 300724`
- 是否完成：是
- 是否成功写入 feedback：是
- 最小结论：成功写入 1 条 `draft` feedback，并完成 detail/activity 回读验证。

#### execution blocker 与 queue ownership 链路

- 目标样本：`2026-03-23 / 300724`
- 是否完成：是
- 是否成功完成 queue 动作：是
- 最小结论：`position_blocked_score` blocker 可读，且对应 workflow item 已成功认领并取消认领。

#### Batch Label 对应批量反馈链路

- 目标样本：`2026-02-24 / 300724, 000960`
- 是否完成：是
- 是否成功完成批量写入：是
- 最小结论：批量接口一次写入 2 条 near-miss feedback，并同步进入 activity 与 workflow queue。

#### 周度复盘 `draft -> final` 推进链路

- 目标样本：`2026-03-20 / 300724`
- 是否完成：是
- 是否成功完成状态推进：是
- 最小结论：同一样本已从 `draft` 推进为 `final`，workflow item 同步切换为 `ready_for_adjudication`。

#### 已登录态前端点击流

- 目标入口：`http://127.0.0.1:5173/` 顶部 `Replay`
- 是否完成：是
- 是否成功进入工作台：是
- 最小结论：真实登录后 token 已落盘，且点击 `Replay` 后已成功渲染 `Replay Artifacts`、`Cross-Report Workflow Queue`、`Report Rail` 与主观察 report。

#### 首日总体判断

- 是否已完成第一次真实试用：是
- 是否出现 A 类问题：否
- 是否出现 B 类问题：否
- 对后续试用的影响：可以继续按当前窗口推进真实日常使用，无需因首轮试用结果中断。

---

## 4. 试用结果汇总

### 4.1 正向结果

本轮确认可用的能力：

1. near-miss 样本的阅读链路已通过首次真实接口验证。
2. selected 样本的 feedback 写入、day detail 回读与 recent activity 回读已通过首次真实接口验证。
3. execution blocker 可读，且对应 workflow item 的 `Assign to me` / `Unassign` 已通过首次真实接口验证。
4. 前端未登录态登录页可正常加载，说明本地工作台基础入口可达。
5. Replay Artifacts 相关前端测试 5/5 通过，覆盖 feedback 提交、batch feedback 与 inspector 关键渲染路径。
6. Batch Label 对应批量反馈后端/API 链路已通过真实样本验证，2 条 near-miss 记录可在一次写入后同步进入 activity 与 workflow queue。
7. 周度复盘最小闭环已通过真实样本验证，`2026-03-20 / 300724` 已从 `draft` 推进到 `final`，并带动 workflow item 进入 `ready_for_adjudication`。
8. 已登录态前端真实点击流已通过浏览器级验证，真实登录后可从顶部入口进入 Replay Artifacts 工作台，并看到 workflow queue、report rail 与主观察 report。

### 4.2 阻断缺陷汇总

- 阻断缺陷数量：当前累计 0
- 代表性问题编号：无
- 共同模式：无

### 4.3 治理摩擦项汇总

- 治理项数量：当前累计 0
- 代表性问题编号：无
- 共同模式：无

### 4.4 长期增强项汇总

- 长期项数量：当前累计 0
- 代表性问题编号：无
- 是否影响当前推广：否

---

## 5. 最小通过标准核对

1. 研究员能稳定完成 report 浏览、review 阅读与 feedback 写入：已满足，后端/API 链路与已登录态前端点击流均已完成真实验证
2. 至少一次周度复盘成功把 `draft` 推进成 `final`：已满足，2026-03-20 / 300724 已完成真实 `draft -> final` 推进
3. Batch Label Workspace 至少在一个真实场景里节省了重复操作：已满足，对应 batch feedback 能力已在真实双样本 near-miss 场景中完成一次写入，且前端工作台已完成真实登录与进入验证
4. Cross-Report Workflow Queue 至少支撑了一次真实认领与取消认领：已满足，2026-03-23 / 300724 已完成真实认领与取消认领
5. 试用中未暴露新的阻断性主流程缺陷：已满足，截至 2026-03-26 当前累计为 0

未通过项补充说明：当前最小通过标准已全部满足；后续窗口主要任务从“补齐证据”转为“继续积累常规使用样本并观察是否出现治理类问题”。

---

## 6. 结论建议

本轮建议三选一：

- A. 继续维持当前版本并进入常规使用
- B. 启动 P0 治理开发
- C. 暂停推广，先修复阻断问题

最终建议：A. 继续维持当前版本并进入常规使用（当前建议）

建议原因：

1. 当前最小通过标准已全部满足，且首轮真实试用未暴露新的阻断性主流程缺陷，现阶段没有证据支持立即回到主线修复或暂停推广。
2. report 浏览、feedback 写入、batch feedback、workflow queue 认领流转、`draft -> final` 推进，以及已登录态前端点击流都已取得真实证据，说明现有版本已经具备最小研究闭环能力。
3. 仍未完成的事项主要集中在 SLA、升级路径、团队协作与生产条件下的治理能力，这些都属于第二阶段 backlog，是否启动应继续由常规使用中的真实摩擦决定，而不是在当前证据已闭合时提前扩实现。

---

## 7. 后续动作

如果选择 A：

1. 以 2026-03-27 作为常规使用起始日，继续沿用当前窗口文档记录每日样本与问题。
2. 每日至少补 1 次真实工作台操作回填，优先覆盖主观察 report 的 report 浏览、trade date 切换、feedback 写入和 queue 动作。
3. 仅保留缺陷修复，不主动扩功能；如出现稳定复现的治理摩擦，再登记到问题台账并映射到第二阶段 backlog。

如果选择 B：

1. 从 P0 backlog 中挑选最小必要项启动。
2. 明确不同时打开 P1、P2、P3。

如果选择 C：

1. 列出必须先修复的阻断问题。
2. 说明恢复试用的前置条件。

---

## 8. 附件与证据

- 关联问题记录：[Replay Artifacts 试用问题台账 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-issue-log.md)
- 关联 report：`paper_trading_window_20260316_20260323_live_m2_7_20260323`、`paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323`、`paper_trading_probe_20260205_cache_benchmark_20260325`
- 关联截图 / 日志 / 接口证据：2026-03-26 已补充首轮真实后端/API 试用证据，包括 2026-03-17 day detail 读取、2026-03-20 feedback 写入与 activity 回读、2026-03-23 blocker 读取与 workflow item 认领/取消认领；同日已补充一轮真实 batch feedback 写入，确认 `2026-02-24 / 300724, 000960` 可批量进入 activity 与 workflow queue；并已完成 `2026-03-20 / 300724` 的真实 `draft -> final` 推进，确认 workflow item 自动切换为 `ready_for_adjudication`；同时已补充前端登录页页面加载证据、Replay Artifacts 相关前端测试 `2 files / 5 tests passed`，以及真实登录后从顶部 `Replay` 入口进入工作台的浏览器级点击流证据
- 关联周度复盘结论：2026-03-26 已完成一次最小周度复盘闭环，主观察 report 中的 `2026-03-20 / 300724` 已从 `draft` 推进为 `final`

---

## 9. 当前状态

当前状态：窗口已启动，且已完成第一次真实后端/API 试用、Batch Label 对应批量反馈链路验证、一次最小周度复盘闭环、前端登录页加载冒烟验证、Replay Artifacts 相关前端测试，以及已登录态前端点击流验证；当前最小通过标准已全部满足，可以继续进入窗口内常规使用与后续观察。
