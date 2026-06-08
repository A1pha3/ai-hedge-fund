# Replay Artifacts 试用验收计划

> 配套阅读：
>
> 1. [Replay Artifacts 新人培训讲义](./replay-artifacts-newcomer-training-guide.md)
> 2. [Replay Artifacts 新人上手验收评分表](./replay-artifacts-onboarding-readiness-scorecard.md)
> 3. [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)
> 4. [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
> 5. [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)
> 6. [研究结论到优化 Backlog 的转换手册](./research-conclusion-to-optimization-backlog-handbook.md)
> 7. [Replay Artifacts 试用问题记录模板](./replay-artifacts-trial-issue-log-template.md)
> 8. [Replay Artifacts 试用总结报告模板](./replay-artifacts-trial-summary-template.md)
> 9. [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md)
> 10. [Replay Artifacts 试用窗口启动记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402.md)
> 11. [本窗口已填观察记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-observations.md)
> 12. [本窗口问题台账 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-issue-log.md)
> 13. [本窗口总结草稿 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-summary.md)

## 1. 这份计划解决什么问题

当前 Replay Artifacts 已经不缺“能不能继续做”的设计说明，缺的是一份可以直接执行的试用验收计划。

这份文档的目标只有三个：

1. 把当前版本定义为试用基线。
2. 规定试用窗口里团队具体该怎么用。
3. 把试用期间的问题分成“立即修复的缺陷”和“第二阶段治理 backlog”。

这份计划不讨论长期产品愿景，也不预设必须继续做 SLA、通知、权限或复杂任务系统。先用，再决定。

如果当前参与试用的人还是第一次接触 Replay Artifacts，建议先用 [Replay Artifacts 新人培训讲义](./replay-artifacts-newcomer-training-guide.md) 做一次 30 分钟带教，再补一份 [Replay Artifacts 新人上手验收评分表](./replay-artifacts-onboarding-readiness-scorecard.md)，确认其已经达到最小独立使用线后，再开始执行本计划。这样可以减少把研究结论、执行结论和流程结论混写到 issue 或 summary 里的噪音。

---

## 2. 试用验收的目标

试用验收不是为了证明系统完美，而是为了回答下面四个问题：

1. 研究员能否稳定完成 report 浏览、trade date 切换、review 阅读与 feedback 回写。
2. Batch Label Workspace 是否能真实减少重复录入成本。
3. Cross-Report Workflow Queue 是否足以支撑最小认领与流转，而不需要立即补复杂治理系统。
4. 周度复盘是否真的能把 `draft` 推进到 `final` / `adjudicated`，并形成后续 backlog 输入。

如果这四个问题的答案大体为“能”，当前阶段就不应继续扩实现范围。

---

## 3. 试用范围

建议本轮试用只覆盖已经落地的能力：

1. report 列表浏览。
2. trade date 切换与 selection_review.md 阅读。
3. selected / rejected / execution blocker / funnel diagnostics 查看。
4. 单条 feedback 写入。
5. Batch Label Workspace 批量写入。
6. report 级 recent activity 与 pending draft queue。
7. Cross-Report Workflow Queue 的认领与取消认领。
8. 周度复盘中把 `draft` 推进成 `final` 或 `adjudicated`。

本轮试用明确不要求：

1. SLA 自动提醒。
2. 通知系统。
3. 权限分层。
4. 复杂审计后台。

这些都应视作只有试用后证据充分时才进入第二阶段的内容。

---

## 4. 试用角色与分工

建议至少有以下三类角色。一个人可以兼任，但职责要分清。

### 4.1 日常复核人

职责：

1. 每天浏览当日或最近 report。
2. 对重点 watchlist / near-miss 样本写 `draft`。
3. 遇到同类样本时优先使用 Batch Label Workspace。

### 4.2 周度汇总人

职责：

1. 每周查看 pending draft queue 与 Cross-Report Workflow Queue。
2. 认领本周要推进的样本。
3. 把稳定结论升级成 `final`。

### 4.3 裁决人

职责：

1. 处理 `ready_for_adjudication` 或高争议样本。
2. 统一标签与研究口径。
3. 输出需要进入优化 backlog 的结论。

---

## 5. 推荐试用窗口

建议使用 1 到 2 周的真实窗口，原因如下：

1. 少于 1 周，通常看不出周度复盘是否能真正发生。
2. 长于 2 周，如果没有中间 checkpoint，问题容易继续堆积。

推荐节奏：

1. 第 1 周：按日使用，重点观察浏览、写入、批量标注、认领动作是否顺手。
2. 周末或周会前：做一次完整周度复盘。
3. 第 2 周前半段：只修复阻断性缺陷，不主动加新功能。
4. 第 2 周末：形成是否进入第二阶段治理开发的结论。

如果需要直接开始执行，而不是从空白文档手工创建窗口记录，可直接使用：

1. [Replay Artifacts 试用窗口启动记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402.md)
2. [本窗口问题台账 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-issue-log.md)
3. [本窗口总结草稿 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-summary.md)

---

## 6. 日常试用清单

每次使用时，至少完成下面动作中的前四项：

1. 打开一个 report。
2. 切换到目标 trade date。
3. 阅读 selection_review.md 与 funnel diagnostics。
4. 对至少一个样本写入 feedback。
5. 如果出现 2 个以上同类样本，尝试用 Batch Label Workspace。
6. 如果当前样本需要后续跟进，确认是否需要在 Cross-Report Workflow Queue 中认领。

建议记录两类体验：

1. 阻断问题：无法完成核心动作。
2. 低效问题：虽然能完成，但步骤明显过多或信息不够清楚。

如果当天没有明确问题，也建议至少留一条“顺利完成”的观察记录，使用 [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md) 统一记录口径，避免窗口结束时只剩下问题、没有通过证据。

如果你不想从空白开始填，当前窗口已经有一份可直接参考的样例： [本窗口已填观察记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-observations.md)。

---

## 7. 周度试用清单

每周至少完成一次下面流程：

1. 查看 report 级 pending draft queue。
2. 查看 Cross-Report Workflow Queue 中的 `my queue` 与 `unassigned`。
3. 认领本周需要推进的样本。
4. 将一批 `draft` 推进成 `final`。
5. 将少量高争议样本推进成 `adjudicated` 候选。
6. 把本周至少 1 条结论写入优化 backlog 映射。

如果这一流程无法顺利完成，才说明第二阶段治理开发有真实必要。

建议周度复盘时同步回看观察记录，而不是只看问题台账。这样才能区分“系统真的不好用”和“系统其实能用，只是需要更稳定的使用习惯”。

---

## 8. 问题分级规则

试用期间发现的问题，统一按下面规则分类。

### 8.1 A 类：阻断缺陷

满足任一情况即可归入 A 类：

1. 页面打不开或关键接口失败。
2. 无法读取 report / trade date。
3. feedback 无法成功写入或回读。
4. Batch Label Workspace 或 Queue 造成数据错误。

处理原则：

1. 回到主线直接修复。
2. 不等待试用结束。

### 8.2 B 类：高摩擦但不阻断

例如：

1. 可以完成认领，但队列不易筛选。
2. 可以复盘，但状态流转不够清晰。
3. 可以关闭样本，但缺少审计或责任信息。

处理原则：

1. 记录到第二阶段治理 backlog。
2. 不在试用窗口中途扩实现，除非影响范围迅速扩大。

### 8.3 C 类：长期增强项

例如：

1. 通知系统。
2. 权限细分。
3. 更复杂的任务看板。

处理原则：

1. 不纳入当前试用成败判断。
2. 单独放入更长期产品路线图。

---

## 9. 试用结束时要输出什么

试用结束后，建议至少产出下面三样东西：

1. 一份阻断缺陷清单。
2. 一份第二阶段治理 backlog 补充清单。
3. 一个明确结论：
   1. 继续维持当前版本并进入常规使用。
   2. 启动 P0 治理开发。
   3. 暂停推广，先修复阻断问题。

如果没有这三样结果，试用就容易退化成“大家都看过，但没有形成决策”。

建议执行时直接配合 [Replay Artifacts 试用问题记录模板](./replay-artifacts-trial-issue-log-template.md)，避免试用过程中不同人记录口径不一致。

试用窗口结束后，建议直接使用 [Replay Artifacts 试用总结报告模板](./replay-artifacts-trial-summary-template.md) 形成统一结论，避免只留下零散问题而没有最终决策。

总结报告前，建议先把 [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md) 里的“成功链路”“高频摩擦”和“是否转问题台账”三列过一遍，再决定结论口径。

---

## 10. 最小通过标准

可以把下面条件作为“当前版本通过试用验收”的最低标准：

1. 至少一个真实窗口内，研究员能稳定完成 report 浏览、review 阅读与 feedback 写入。
2. 至少一次周度复盘成功把 `draft` 推进成 `final`。
3. Batch Label Workspace 至少在一个真实场景里节省了重复操作。
4. Cross-Report Workflow Queue 至少支撑了一次真实认领与取消认领。
5. 试用中未暴露新的阻断性主流程缺陷。

满足这五条，就应优先认为当前版本已经达到“可用”，后续工作进入治理优化，而不是继续把迁移主线无限延长。

---

## 11. 简化结论

当前最重要的不是继续做更多功能，而是用一段有限时间的真实使用，把“是否真的还需要第二阶段治理开发”这件事用证据说清楚。

如果试用证明当前版本已经够用，就应停止继续扩范围。

如果试用证明治理问题已经成为真实瓶颈，再回到第二阶段 backlog，按 P0 到 P3 顺序恢复即可。
