# Replay Artifacts 试用窗口启动记录 2026-03-26 至 2026-04-02

> 关联文档：
>
> 1. [Replay Artifacts 试用验收计划](./replay-artifacts-trial-acceptance-plan.md)
> 2. [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md)
> 3. [本窗口已填观察记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-observations.md)
> 4. [Replay Artifacts 试用问题记录模板](./replay-artifacts-trial-issue-log-template.md)
> 5. [Replay Artifacts 试用总结报告模板](./replay-artifacts-trial-summary-template.md)
> 6. [本窗口首日执行清单](./replay-artifacts-trial-window-20260326-20260402-day1-checklist.md)

## 1. 启动目的

这份文档不是模板，而是当前这一轮 Replay Artifacts 试用的实际启动记录。

目标是把“已经建议进入试用验收”进一步落成可执行基线，避免后续继续停留在抽象计划层。

本轮试用的核心问题只有一个：

当前版本是否已经足够支持真实研究使用，还是必须立即启动第二阶段治理开发。

---

## 2. 试用窗口信息

- 试用窗口：2026-03-26 ~ 2026-04-02
- 启动日期：2026-03-26
- 当前状态：已启动；已完成第一次真实后端/API 试用、Batch Label 对应批量反馈链路验证、一次最小周度复盘闭环、前端登录页加载冒烟验证、Replay Artifacts 相关前端测试，以及已登录态前端真实点击流验证；当前未发现阻断性主流程问题，可继续按窗口节奏做常规使用
- 试用基线版本：当前工作区已完成版本
- 结论输出目标：在窗口结束后形成一份正式试用总结报告

---

## 3. 本轮试用范围

本轮只验证已经落地的工作台能力，不主动追加新功能。

验证范围：

1. report 列表浏览。
2. trade date 切换。
3. selection_review.md、execution blocker、funnel diagnostics 阅读。
4. 单条 feedback 写入。
5. Batch Label Workspace。
6. recent activity 与 pending draft queue。
7. Cross-Report Workflow Queue 的认领与取消认领。
8. 周度复盘把 `draft` 推进到 `final` 或 `adjudicated`。

本轮明确不作为通过前提：

1. SLA 自动提醒。
2. 通知系统。
3. 权限分层。
4. 更复杂的任务系统。

---

## 4. 推荐参与角色

本轮窗口按“单人先跑通，必要时再扩多人协作”执行，因此先给出默认责任落点，避免继续停留在空白占位。

- 日常复核人：einstein
- 周度汇总人：einstein
- 裁决人：einstein 暂代；如窗口内出现高争议样本，再转交策略负责人做最终裁决

如果后续转为多人试用，再把这三项替换成真实用户名即可；在此之前，默认由 einstein 兼任三项职责，但仍按三种责任口径分别记录。

---

## 5. 推荐观察样本

建议优先选择具备连续 trade date、且同时包含 selected、near-miss、execution blocker 的 report。

候选样本：

1. `paper_trading_window_recent`
2. `paper_trading_window_20260316_20260323_live_m2_7_20260323`
3. 如需历史长窗口观察，可补充 `paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323`

本轮实际选用 report：

1. 主观察 report：`paper_trading_window_20260316_20260323_live_m2_7_20260323`
2. 长窗口补充 report：`paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323`
3. cache benchmark 补充 report：`paper_trading_probe_20260205_cache_benchmark_20260325`

选择原因：

1. 主观察 report 覆盖真实 live pipeline、selected、near-miss 与 execution blocker，最适合日常试用主线。
2. 长窗口补充 report 覆盖 24 个 trade_date，更适合观察 queue、周度复盘和跨日连续性。
3. cache benchmark 补充 report 用于顺手验证 report 级摘要信息在工作台中的可读性，但不作为本轮通过门槛。

---

## 6. 日常执行要求

试用期间，建议每天至少完成下面动作：

1. 打开一个 report。
2. 切换到目标 trade date。
3. 阅读 review 与 funnel diagnostics。
4. 对至少一个样本写 feedback。
5. 如出现同类样本，至少尝试一次 Batch Label Workspace。
6. 如需后续跟进，至少尝试一次 Queue 认领或取消认领。

每次发现问题时，不直接在这份文件里零散记录，而是另开一份问题记录，使用：

1. [Replay Artifacts 试用问题记录模板](./replay-artifacts-trial-issue-log-template.md)
2. [本窗口问题台账 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-issue-log.md)
3. [本窗口首日执行清单](./replay-artifacts-trial-window-20260326-20260402-day1-checklist.md)

如果当天没有问题，但有真实使用证据，同样应至少留一条观察记录，使用 [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md) 回填“做了什么、是否成功、哪里仍有摩擦”。

当前窗口已根据 2026-03-26 的真实试用证据补齐一版样例，见 [本窗口已填观察记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-observations.md)。后续追加时，建议沿用同一粒度继续往后写。

---

## 7. 周度执行要求

本轮窗口结束前，至少完成一次完整周度复盘：

1. 查看 pending draft queue。
2. 查看 Cross-Report Workflow Queue 中的 `my queue` 与 `unassigned`。
3. 认领本周要推进的样本。
4. 将至少一批 `draft` 推进成 `final`。
5. 如存在高争议样本，推进到 `adjudicated` 候选。
6. 输出至少 1 条 backlog 映射结论。

如果这一动作无法完成，通常意味着第二阶段治理开发已经有真实必要。

---

## 8. 问题归档规则

本轮试用中的问题统一分三类：

1. A 类：阻断缺陷，回到主线修复。
2. B 类：高摩擦治理项，进入第二阶段 backlog。
3. C 类：长期增强项，不纳入当前试用成败判断。

问题记录清单：

1. [本窗口问题台账 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-issue-log.md)

---

## 9. 通过标准

本轮窗口默认按以下标准判断是否通过：

1. 至少一个真实窗口内，研究员能稳定完成 report 浏览、review 阅读与 feedback 写入。
2. 至少一次周度复盘成功把 `draft` 推进成 `final`。
3. Batch Label Workspace 至少在一个真实场景里节省了重复操作。
4. Cross-Report Workflow Queue 至少支撑了一次真实认领与取消认领。
5. 试用中未暴露新的阻断性主流程缺陷。

---

## 10. 窗口结束后的输出要求

窗口结束后，必须产出：

1. 阻断缺陷清单。
2. 第二阶段治理 backlog 补充清单。
3. 一份试用总结报告。

建议在形成总结前，先把观察记录按下面三类各自过一遍：

1. 明确通过的链路。
2. 可用但有摩擦的链路。
3. 必须转问题台账的链路。

推荐直接使用：

1. [Replay Artifacts 试用总结报告模板](./replay-artifacts-trial-summary-template.md)
2. [本窗口总结草稿 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-summary.md)

---

## 11. 当前启动结论

截至 2026-03-26，这一轮 Replay Artifacts 工作已经不再处于“继续扩实现”的合适阶段，而是进入“试用验收 + 收集证据”的合适阶段。

同日已补齐最后一项浏览器级证据：使用真实登录用户 `einstein` 在本地前端完成登录，确认 `hedge_fund_token` 已落入 localStorage，并通过顶部 `Replay` 入口成功打开 Replay Artifacts 工作台；页面已真实渲染 `Replay Artifacts`、`Cross-Report Workflow Queue`、`Report Rail` 及主观察 report `paper_trading_window_20260316_20260323_live_m2_7_20260323`。

这份文件的存在，意味着后续如果要继续推进，应优先围绕真实试用记录做决策，而不是重新回到主线是否完成的争论。
