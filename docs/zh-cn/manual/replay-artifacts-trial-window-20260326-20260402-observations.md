# Replay Artifacts 试用观察记录 2026-03-26 至 2026-04-02

> 关联文档：
>
> 1. [Replay Artifacts 试用验收计划](./replay-artifacts-trial-acceptance-plan.md)
> 2. [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md)
> 3. [Replay Artifacts 试用窗口启动记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402.md)
> 4. [本窗口问题台账 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-issue-log.md)
> 5. [本窗口总结草稿 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-summary.md)

## 1. 这份文档怎么用

这份文件不是模板，而是当前试用窗口的已填写样例。

它的价值在于两点：

1. 证明“观察记录表”不是纸面格式，而是已经能承接真实试用证据。
2. 给后续试用者一个可直接照着写的样板，避免每次都从空白开始。

记录原则：

1. 一条记录只回答一次真实动作。
2. 能说明通过，就不要硬写成问题。
3. 真正需要升级的现象，再转入问题台账。

---

## 2. 观察记录

### 观察记录 01

- 日期：2026-03-26
- 观察人：einstein
- report：paper_trading_window_20260316_20260323_live_m2_7_20260323
- trade_date：2026-03-17
- 场景类型：near-miss
- 目标动作：验证 near-miss 阅读链路是否顺畅，并确认 Layer B 放行、Layer C 否决的样本是否易读
- 结果：成功
- 是否留下系统内证据：是
- 关键证据：
  - `002916` 可被定位为 near-miss 样本
  - 真实接口返回 `rejection_stage=watchlist`
  - `decision_avoid` 与 `score_final_below_watchlist_threshold` 可读
- 主要摩擦：
  - 无明显功能摩擦
  - 字段语义仍更适合配合术语手册一起看
- 问题归类：无
- 是否需要转问题台账：否
- 最小评分：
  - 可找到性：3
  - 可理解性：2
  - 可操作性：3
  - 可沉淀性：3
- 一句话结论：
  - near-miss 阅读链路通过，当前更像“需要文档辅助理解 Layer C 否决语义”，而不是页面能力缺失。

### 观察记录 02

- 日期：2026-03-26
- 观察人：einstein
- report：paper_trading_window_20260316_20260323_live_m2_7_20260323
- trade_date：2026-03-20
- 场景类型：selected + feedback
- 目标动作：读取 selected 样本 `300724`，并写入 1 条 `draft` feedback
- 结果：成功
- 是否留下系统内证据：是
- 关键证据：
  - `300724` 是该日唯一 selected 样本
  - 成功写入 1 条 `draft` feedback
  - day detail 与 recent activity 均完成回读
- 主要摩擦：
  - 标签与状态本身可用，但如果没有标签规范文档，首次使用仍会有轻微理解成本
- 问题归类：无
- 是否需要转问题台账：否
- 最小评分：
  - 可找到性：3
  - 可理解性：2
  - 可操作性：3
  - 可沉淀性：3
- 一句话结论：
  - selected 阅读与单条 feedback 写入链路通过，当前主要依赖文档确保标签口径一致，而不是功能补强。

### 观察记录 03

- 日期：2026-03-26
- 观察人：einstein
- report：paper_trading_window_20260316_20260323_live_m2_7_20260323
- trade_date：2026-03-23
- 场景类型：blocker + workflow
- 目标动作：确认 `300724` 的 execution blocker，并完成一次 `Assign to me` / `Unassign`
- 结果：成功
- 是否留下系统内证据：是
- 关键证据：
  - `buy_order_blocker = position_blocked_score` 可读
  - workflow item 可定位
  - `Assign to me` 与 `Unassign` 均成功
- 主要摩擦：
  - `workflow_status` 的语义仍更适合结合术语手册理解
- 问题归类：无
- 是否需要转问题台账：否
- 最小评分：
  - 可找到性：3
  - 可理解性：2
  - 可操作性：3
  - 可沉淀性：3
- 一句话结论：
  - blocker 阅读与 ownership 操作链路通过，当前更像工作流语义需要文档辅助，而不是工作台交互失败。

### 观察记录 04

- 日期：2026-03-26
- 观察人：einstein
- report：paper_trading_probe_20260224_20260225_selection_artifact_validation_20260322
- trade_date：2026-02-24
- 场景类型：batch label
- 目标动作：对 `300724` 与 `000960` 执行一次真实批量反馈写入，并确认 activity / workflow queue 同步
- 结果：成功
- 是否留下系统内证据：是
- 关键证据：
  - 批量接口返回 `appended_count=2`
  - `feedback_records` 数量从 0 变为 2
  - recent activity 与 workflow queue 均出现对应条目
- 主要摩擦：
  - 当前已验证的是后端/API 真实样本链路，前端批量工作台的真实点击流证据仍可后续继续补强
- 问题归类：无
- 是否需要转问题台账：否
- 最小评分：
  - 可找到性：3
  - 可理解性：3
  - 可操作性：3
  - 可沉淀性：3
- 一句话结论：
  - Batch Label 对应的批量链路已在真实样本中成立，当前更适合继续积累前端使用证据，而不是认定其能力缺失。

### 观察记录 05

- 日期：2026-03-26
- 观察人：einstein
- report：paper_trading_window_20260316_20260323_live_m2_7_20260323
- trade_date：2026-03-20
- 场景类型：weekly review + workflow
- 目标动作：将 `300724` 从 `draft` 推进到 `final`，观察 workflow 状态是否同步变化
- 结果：成功
- 是否留下系统内证据：是
- 关键证据：
  - 新增 1 条 `review_status=final` 的 feedback
  - workflow item 从 `unassigned` 切换为 `ready_for_adjudication`
  - report 级 `workflow_status_counts` 同步更新为 `final=1, draft=1`
- 主要摩擦：
  - 需要清楚区分 `final` 与 `ready_for_adjudication` 的边界，否则容易把流程结论误读成投资结论
- 问题归类：无
- 是否需要转问题台账：否
- 最小评分：
  - 可找到性：3
  - 可理解性：2
  - 可操作性：3
  - 可沉淀性：3
- 一句话结论：
  - 最小周度复盘闭环已形成，当前真正需要的是稳定复盘习惯与语义训练，而不是再补一套新状态机。

### 观察记录 06

- 日期：2026-03-26
- 观察人：einstein
- report：paper_trading_probe_20260205_cache_benchmark_20260325
- trade_date：20260205
- 场景类型：cache benchmark
- 目标动作：确认 report 级 cache benchmark 是否有真实运行证据，且页面摘要是否足够支撑阅读结论
- 结果：成功
- 是否留下系统内证据：是
- 关键证据：
  - `data_cache_benchmark_status.write_status = success`
  - `reuse_confirmed = true`
  - `first_hit_rate = 0.0`，`second_hit_rate = 1.0`
  - `disk_hit_gain = 6`
- 主要摩擦：
  - 如果没有术语手册，用户仍可能把 `reuse_confirmed` 误判成长期保证
- 问题归类：无
- 是否需要转问题台账：否
- 最小评分：
  - 可找到性：3
  - 可理解性：2
  - 可操作性：3
  - 可沉淀性：3
- 一句话结论：
  - cache benchmark 的运行证据链已成立，当前主要挑战是避免语义误读，而不是补更多技术字段。

### 观察记录 07

- 日期：2026-03-26
- 观察人：einstein
- report：paper_trading_window_20260316_20260323_live_m2_7_20260323
- trade_date：不适用
- 场景类型：前端入口 + workspace reachability
- 目标动作：在真实登录态下从前端顶部 `Replay` 入口进入工作台，并确认工作台主体可见
- 结果：成功
- 是否留下系统内证据：是
- 关键证据：
  - 真实登录后 `hedge_fund_token` 已落盘
  - 顶部 `Replay` 入口可点击
  - 页面已渲染 `Replay Artifacts`、`Cross-Report Workflow Queue`、`Report Rail` 与主观察 report
- 主要摩擦：
  - 无新的阻断性问题
- 问题归类：无
- 是否需要转问题台账：否
- 最小评分：
  - 可找到性：3
  - 可理解性：3
  - 可操作性：3
  - 可沉淀性：3
- 一句话结论：
  - 已登录态前端入口链路通过，说明当前试用证据已不只停留在接口层，而是已经闭合到真实工作台入口。

---

## 3. 阶段性观察结论

基于当前已填写记录，可以先得到三个阶段性判断：

1. 核心链路已经通过：near-miss 阅读、selected 写入、blocker 阅读、queue ownership、batch feedback、`draft -> final` 推进、cache benchmark 阅读与前端入口都已有真实证据。
2. 当前主要摩擦集中在语义理解，而不是功能失败：`workflow_status`、`ready_for_adjudication`、`reuse_confirmed` 这类字段仍需要文档辅助，但尚未表现为 A 类或 B 类问题。
3. 当前更适合继续积累常规使用观察，而不是立刻回到主线扩功能：因为观察记录里暂时没有形成重复性高摩擦，更没有阻断链路失败。

## 4. 下一步怎么继续填

建议后续每次真实试用，都优先按这份文件的粒度继续追加记录，而不是只在出现问题时才写问题单。

追加原则：

1. 有通过证据就记通过。
2. 有摩擦但未复现，先记观察。
3. 只有当摩擦重复出现或动作失败，再转入问题台账。

这样到窗口结束时，试用总结就能同时拥有：

1. 明确的通过证据。
2. 清晰的摩擦分布。
3. 真实而不过度膨胀的问题清单。
