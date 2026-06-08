# Replay Artifacts 试用窗口首日执行清单 2026-03-26 至 2026-04-02

> 关联文档：
>
> 1. [Replay Artifacts 试用窗口启动记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402.md)
> 2. [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md)
> 3. [本窗口已填观察记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-observations.md)
> 4. [本窗口问题台账 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-issue-log.md)
> 5. [本窗口总结草稿 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-summary.md)

## 1. 这份清单解决什么问题

这份文档不记录“是否已经试过”，而是把第一次真实工作台操作拆成可以直接执行的步骤。

目标是避免首日试用再次停留在“知道要做什么”，却没有真正进入 report 浏览、trade date 切换、review 阅读、feedback 写入和 queue 操作。

---

## 2. 首日执行目标

首日不追求覆盖所有能力，只覆盖最有信息量的三个观察点：

1. 一个典型 near-miss 样本
2. 一个成功生成 buy order 的边界样本
3. 一个继续进入 watchlist 但被执行层 blocker 拦下的样本

如果这三步都能顺利走完，首日就已经足以验证最小工作台闭环。

---

## 3. 推荐执行顺序

### 3.1 第一步：验证 near-miss 阅读链路

- report：`paper_trading_window_20260316_20260323_live_m2_7_20260323`
- trade_date：`2026-03-17`
- 重点样本：`002916`

预期应看到：

1. `high_pool_count=1`
2. `watchlist_count=0`
3. `buy_order_count=0`
4. `002916` 被归类为 near-miss
5. Layer C 否决信息可读，核心特征应接近：
   - `rejection_stage=watchlist`
   - `decision_avoid`
   - `score_final_below_watchlist_threshold`

本步要回答的问题：

1. 页面是否能快速定位 near-miss 样本。
2. near-miss 的 rejection reason 是否足够直观。
3. research 视角能否区分“Layer B 放行”与“Layer C 否决”。

建议记录：

1. 如果页面能顺畅读出上述信息，记录“阅读链路通过”。
2. 如果原因字段难懂、信息藏得太深，记为 B 类治理项。
3. 无论是否发现问题，都建议同步留一条观察记录，使用 [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md)。
4. 如果想确认回填粒度，可以直接参考 [本窗口已填观察记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-observations.md)。

---

### 3.2 第二步：验证 selected 与 feedback 写入链路

- report：`paper_trading_window_20260316_20260323_live_m2_7_20260323`
- trade_date：`2026-03-20`
- 重点样本：`300724`

预期应看到：

1. `high_pool_count=1`
2. `watchlist_count=1`
3. `buy_order_count=1`
4. `300724` 是唯一 selected 样本
5. Layer B 主因子可读，核心结构应接近：
   - `fundamental`
   - `trend`
   - `event_sentiment`

本步建议实际执行一次 feedback 写入：

1. review_scope：`watchlist`
2. review_status：`draft`
3. primary_tag：优先选择一个与“边界过线样本”一致的已有标签口径
4. notes：记录“300724 属于勉强但稳定过线样本，不是高共识强信号票”这类研究结论

本步要回答的问题：

1. selected 样本的阅读与定位是否顺手。
2. feedback 表单是否能完成最小写入。
3. 写入后 activity 面板与 detail 是否同步刷新。

建议记录：

1. 如果写入成功且刷新正常，记为“写入链路通过”。
2. 如果写入成功但回读滞后或语义不清，记为 B 类治理项。
3. 如果写入失败或数据异常，记为 A 类阻断缺陷。
4. 同时建议补一条观察记录，明确写入动作是否顺手、回读是否即时。
5. 如果需要一个现成样本，直接对照 [本窗口已填观察记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-observations.md) 中的 selected / feedback 记录。

---

### 3.3 第三步：验证 execution blocker 与 queue 操作链路

- report：`paper_trading_window_20260316_20260323_live_m2_7_20260323`
- trade_date：`2026-03-23`
- 重点样本：`300724`

预期应看到：

1. `high_pool_count=1`
2. `watchlist_count=1`
3. `buy_order_count=0`
4. `300724` 仍在 watchlist
5. execution blocker 应明确可见，核心字段应接近：
   - `buy_order_blocker=position_blocked_score`
   - `constraint_binding=score`

本步建议实际执行一次 queue 动作：

1. 打开 Cross-Report Workflow Queue
2. 找到对应条目
3. 执行一次 `Assign to me`
4. 如需验证回退动作，再执行一次 `Unassign`

本步要回答的问题：

1. 页面是否能清楚区分“研究层仍过线”和“执行层不给承接”。
2. queue 条目是否容易找到。
3. 认领与取消认领动作是否能形成最小闭环。

建议记录：

1. 如果 blocker 可读且 queue 动作可完成，记为“blocker 与 ownership 链路通过”。
2. 如果 queue 可用但筛选困难，记为 B 类治理项。
3. 如果认领动作失败或状态异常，记为 A 类阻断缺陷。
4. 同时建议补一条观察记录，明确 queue 是“可用”“勉强可用”还是“难以使用”。
5. 当前窗口已有 blocker + workflow 的真实样例，可直接参考 [本窗口已填观察记录 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-observations.md)。

---

## 4. 可选补充步骤

如果首日还有余量，再补两步：

1. 打开 `paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323`
2. 用长窗口样本观察 `300724` 的重复出现是否容易在工作台里形成“边界稳定样本”认知

这一步不要求当天完成，只是为了给周度复盘做心理预热。

---

## 5. 首日结束时至少要留下什么

首日结束前，至少留下下面三项中的两项：

1. 一条实际 feedback 记录
2. 一次 queue 认领或取消认领记录
3. 一条问题台账记录，哪怕结论是“无新问题，阅读与写入链路通过”

如果三项都没有留下，说明首日仍停留在准备阶段，而不是实际试用。

---

## 6. 首日完成后的建议回填位置

执行结束后，建议同步更新：

1. [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md)
2. [本窗口问题台账 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-issue-log.md)
3. [本窗口总结草稿 2026-03-26 至 2026-04-02](./replay-artifacts-trial-window-20260326-20260402-summary.md)
4. 优先回填观察记录，再决定是否需要新增正式问题编号

最小回填原则：

1. 是否完成了真实工作台操作
2. 是否成功写入 feedback
3. 是否成功完成 queue 动作
4. 是否出现 A 类或 B 类问题
