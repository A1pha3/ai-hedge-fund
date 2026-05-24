# BTST 执行治理解堵方案 - 2026-05-24

## 学习目标
- 看清这周 BTST 真正卡住的位置，不把“没有正式主票”误判成“市场里没有机会”。
- 区分原始选股层、短线决策层和正式执行层，知道问题发生在哪一段。
- 明白为什么当前最该先修的是执行治理解堵，而不是继续上游找票或微调候选池截断。
- 给 alpha、beta、gamma 一条可以直接落地、能继续回测验证的分工路线。

## 先给结论

这周系统胜率和赔率的最大问题，不是原始 BTST 选不出股票，也不是市场里完全没有短线机会，而是 **候选到了短线执行层之后，被 `proxy_only`、`shadow_only`、`p2_execution_blocked` 这一组治理规则过度拦截**。结果是原始模型每天能给出大量 `SELECTED`，但正式 short-trade 执行名单连续多天是 `0`，组合净值也就没有真正进入验证阶段。

更直白一点说：系统现在更像“会找票，但不敢放票”。在“买入后 5 个交易日内，55% 以上概率涨超 15%”这个目标下，**连续把可交易候选压成观察层**，比“选错几只票”更伤胜率和赔率，因为它直接把赔率上限封死了。

## 本轮回测范围

本轮使用了仓库里已经落盘的本周 BTST 报告与 followup 产物，能稳定回填到真实价格的信号日是 `2026-05-19`、`2026-05-20`、`2026-05-21`。当前本地可复核的 forward price 只覆盖到 `2026-05-22`，所以 `2026-05-22 -> 2026-05-23` 这一跳没有纳入下面的定量统计。

这里的数字主要回答两件事：

| 指标 | 含义 | 不能单独推出什么 |
| --- | --- | --- |
| `next_high_return` | 信号日收盘后，下一交易日最高价相对信号日收盘的空间 | 不能直接当成可成交收益 |
| `next_close_return` | 下一交易日收盘相对信号日收盘的结果 | 不能单独代表 5 日赔率 |
| `max_high_return_5d_from_open` | 下一交易日开盘作为入场价时，后续可见窗口里的最高涨幅 | 目前是短窗口证据，不是长期稳定收益证明 |

所以，这份文档看的不是“这套系统已经稳定赚钱了没有”，而是 **这周候选有没有被错拦、错拦发生在哪一层、先修哪一刀最可能把机会重新放回正式执行面**。

## 系统地图：问题不是在找票层，而是在放票层

| 层级 | 本周表现 | 当前判断 |
| --- | --- | --- |
| 原始 BTST 全市场评分层 | `2026-05-19` 有 `1427` 个 `SELECTED`，`2026-05-20` 有 `1098` 个，`2026-05-21` 有 `644` 个 | 不像“市场完全没票” |
| short-trade 内部决策层 | `2026-05-20` 内部 short-trade 曾选出 `1` 只，`2026-05-21` 曾选出 `5` 只 | 候选并没有在这里消失 |
| 正式执行 / 对外 followup 层 | 三天正式 `short_trade_selected_count` 全是 `0` | 主问题发生在这里 |

也就是说，当前链路不是：

`市场太差 -> 模型没票 -> 无法交易`

而是：

`模型有票 -> short-trade 内部也能过初筛 -> 正式执行治理继续下压 -> 最后没有主票`

## 这周最关键的证据

### 1. 原始 BTST 层并不空

- `2026-05-19`：`SELECTED = 1427`  
  来源：`data/reports/btst_full_report_20260519.md`
- `2026-05-20`：`SELECTED = 1098`  
  来源：`data/reports/btst_full_report_20260520.md`
- `2026-05-21`：`SELECTED = 644`  
  来源：`data/reports/btst_full_report_20260521.md`

如果问题是“系统已经完全找不到强票”，这三个数字不会还是这个量级。

### 2. 正式执行层连续归零

| 信号日 | 正式 selected | near_miss | blocked | 说明 |
| --- | --- | --- | --- | --- |
| `2026-05-19` | `0` | `17` | `0` | 全部留在观察层 |
| `2026-05-20` | `0` | `14` | `3` | 已开始出现 `p2_execution_blocked` |
| `2026-05-21` | `0` | `9` | `6` | `p2_execution_blocked` 明显变重 |

来源：三个报告目录里的 `btst_next_day_trade_brief_latest.md`。

### 3. 内部 short-trade 结果被正式治理继续拦掉

- `2026-05-20`
  - `dual_target_summary.short_trade_selected_count = 1`
  - `reporting_target_summary.short_trade_selected_count = 0`
  - `short_trade_formal_blocked_selected_count = 1`
- `2026-05-21`
  - `dual_target_summary.short_trade_selected_count = 5`
  - `reporting_target_summary.short_trade_selected_count = 0`
  - `short_trade_formal_blocked_selected_count = 5`

这说明系统不是“没有候选”，而是 **候选在进入正式执行面之前又被治理层拦了一次**。

### 4. 近阈值观察层里，确实有被错过的高赔率样本

本轮把 `selection_snapshot.json` 里的 short-trade 决策，和真实次日 / 可见 5 日价格做了对照。结果最值得注意的不是 `selected`，而是 `near_miss`：

| 决策层级 | 样本数 | 次日最高 >= 2% | 次日收正 | 5 日内最高 >= 15%（按次日开盘计） | 5 日最高涨幅均值 |
| --- | --- | --- | --- | --- | --- |
| `selected` | `6` | `83.33%` | `83.33%` | `0%` | `4.21%` |
| `near_miss` | `44` | `86.36%` | `54.55%` | `13.64%` | `7.79%` |
| `rejected` | `16` | `93.75%` | `62.50%` | `6.25%` | `4.88%` |

这组数字的意思很明确：

- 当前正式执行面没吃到系统里最有赔率弹性的那一层。
- 被压在 `near_miss` 的样本，至少在这周里，并不比内部 `selected` 更差。
- 真正的短板不是“信号太弱”，而是 **正式放行条件把可用机会压成了观察票**。

### 5. 具体漏失案例

下面这些样本，本周都没有成为正式主票，但事后看给出了明显空间：

| 信号日 | 股票 | 当时决策 | 次日最高 | 次日收盘 | 可见窗口最高涨幅（按次日开盘计） |
| --- | --- | --- | --- | --- | --- |
| `2026-05-19` | `688347` | `near_miss` | `+19.41%` | `+18.74%` | `+24.83%` |
| `2026-05-19` | `688072` | `near_miss` | `+14.66%` | `+14.41%` | `+22.46%` |
| `2026-05-19` | `002371` | `near_miss` | `+6.50%` | `+5.86%` | `+16.76%` |
| `2026-05-19` | `603986` | `near_miss` | `+10.00%` | `+10.00%` | `+15.93%` |
| `2026-05-20` | `300408` | `near_miss` | `+9.42%` | `+2.62%` | `+19.20%` |

这些票不说明“near_miss 全该放”，但足够说明 **当前正式治理太保守，已经开始把一部分高赔率样本压在门外**。

## 为什么我认为主问题不是别的

### 不是“本周股票质量整体太差”

如果真是股票质量崩了，原始 BTST 层不会还持续给出数百到上千个 `SELECTED`，`near_miss` 里也不会反复出现次日高波动、短线强延续的样本。

### 不是“上游 candidate pool recall / truncation”这周最该先修

`candidate_pool_truncated_after_filters` 这条线当然是真的，而且 `300683`、`688796`、`688383` 这些票的确说明了上游漏票问题还没收干净。但这条线的主矛盾是 **长期漏召回和流动性走廊**，更像中期工程任务。

本周最伤实盘机会的，不是“上游没把所有潜在妖股捞进来”，而是 **已经进到 short-trade 观察层的票，仍然过不去正式执行门**。

## 最佳解决方案：先做一条受控的 near-miss 晋级车道

这次不建议先去扩大候选池，也不建议先去继续放松截断边界。最该先做的是：

> **把一部分已经证明有 close-continuation 特征的 near-miss，从纯观察层升级成受控执行层。**

### alpha：重写“什么样的 near-miss 值得晋级”

alpha 这边先做因子和标签定义，不直接放宽所有 near-miss，而是只提炼这类名字：

1. `preferred_entry_mode = confirm_then_hold_breakout`
2. `gate_structural = pass`
3. 历史先验更偏 `close_continuation`，而不是纯 `intraday_only`
4. 历史 `next_close_positive_rate >= 0.55`
5. 历史 `next_high>=2%` 命中率不低于 `0.60`
6. `score_target` 处在 near-miss 上沿，而不是远离边界的低分观察票

这一步的目标不是“多做交易”，而是先把 **观察层里真正更像主票的那一小段** 拆出来。

### beta：把“观察层”改成“受控晋级层”

beta 这边要做的不是再加一层人工判断，而是把它做成一条明确的运行规则：

1. 新增 `governed_near_miss_promote_lane`
2. 每天最多放行 `1` 到 `2` 只
3. 必须保留盘中确认，不允许无条件开盘追价
4. 仓位先缩到正式主票的 `0.25x` 到 `0.50x`
5. promotion 只允许发生在 `close_continuation` 倾向样本，不碰纯 `intraday_only`

beta 要解决的是 **执行面转化率**，不是继续在候选层堆规则。

### gamma：把 rollout 做成可停、可比、可回滚

gamma 这边负责把这条新车道变成可验证的实验，而不是新一轮主观放票：

1. 用最近 `20` 个 short-trade 报告窗口做滚动 A/B
2. A 组保留现状，B 组只增加 `governed_near_miss_promote_lane`
3. 重点看 4 个指标：
   - 正式可执行样本数是否从 `0` 抬起来
   - `next_close_positive_rate` 是否高于 `55%`
   - `5` 日内最高涨幅 >= `15%` 的命中率是否明显改善
   - 是否出现新的 preserve 误伤或治理污染
4. 如果 promotion 组没有明显改善，或者误伤上升，立即回滚

gamma 要守住的是：**把执行治理解堵，不能演变成无纪律放松。**

## 一条具体任务流，说明这次该怎么改

拿 `2026-05-19` 的 `688347` 来说，当前链路是这样的：

1. 原始 BTST 层看到它有不错的 breakout / close continuation 形态。
2. short-trade 层没有把它放成正式主票，只留在 `near_miss`。
3. 次日真实结果给出了 `+19.41%` 的盘中高点、`+18.74%` 的收盘结果。
4. 系统事后知道它是强票，但正式执行面当天是空的。

如果把这条票放进新的 `governed_near_miss_promote_lane`，它应该经历的是：

1. 先保留原来的盘中确认。
2. 确认后用小仓位进入。
3. 不按 `watch_only` 处理，而按受控主票处理。
4. 由 gamma 单独统计 promotion 组的真实 hit rate 和 payoff。

这比继续讨论“要不要把 top300 cutoff 再微调一点”更贴近本周主矛盾。

## 为什么这条路更接近 “5 日内 55% 概率涨超 15%” 的目标

因为当前系统最大的硬伤不是胜率不够高，而是 **连样本都放不出来**。

在“正式执行名单长期为 0”的状态下，目标概率实际上接近 `0`：不是票一定不行，而是系统根本不给自己去验证赔率的机会。先让最有把握的一小段 near-miss 进入受控执行层，才有可能把“有机会但没上车”的损失，变成可统计、可优化的真实样本。

这也是为什么当前优先级应该是：

1. **先修执行治理解堵**
2. 再看 promotion 组是否真的带来更高的 5 日赔率
3. 最后才回头继续处理 upstream recall / liquidity corridor

## 验证顺序

建议按下面顺序继续验证：

1. 回放最近 `20` 个 short-trade 报告目录，重建 `selected / near_miss / blocked / rejected` 的 forward outcome 面板。
2. 先只测试 `confirm_then_hold_breakout + close_continuation` 这一小段 near-miss。
3. 观察 promotion 组是否满足：
   - `next_close_positive_rate > 0.55`
   - `5` 日内最高涨幅 >= `15%` 的命中率明显高于当前正式执行面
4. 只有 promotion 组站稳以后，才考虑把规则写回默认 short-trade 治理链。

## 边界

- 这份结论不能推出“所有 near-miss 都值得放行”。
- 也不能推出“candidate pool truncation 已经不重要了”。
- 它只说明：**从本周已经落盘、能对上真实价格的样本看，执行治理过度保守，是当前最先该修的一刀。**

## 下一步建议

如果只允许做一件事，我建议先做：

> **把 `close_continuation` 倾向的 high-priority near-miss，做成一条小仓位、保盘中确认、可单独统计的受控晋级车道。**

这条路的优点是：

- 改动面比重写候选池小；
- 能最快把正式执行样本从 `0` 提起来；
- 最贴近这周已经暴露出来的真实问题；
- 失败了也容易回滚，不会把整条 short-trade 链一起打乱。

从 alpha / beta / gamma 的分工看，当前最合理的节奏是：

1. alpha 先定义晋级标签；
2. beta 把晋级车道接进执行链；
3. gamma 用滚动窗口验证它有没有真的把 `5 日 +15%` 命中率往上推。

在这三步之前，继续把大量候选压在 `watch_only` 或 `shadow_only`，系统很难真正提高胜率和赔率。

## 本轮代码落地后的回放结论

这篇文档写完以后，已经把第一版 **regime relief lane** 落到了代码里，逻辑上分成两档：

- `shadow_only`：高质量 `close_continuation` 候选允许走 `0.25` 的缩仓晋级；
- `halt`：条件更严格，只给 `0.10` 的更小仓位 relief。

把这套逻辑套回本周 `selection_target_replay_input.json` 后，能看到两个很重要的变化：

1. `2026-05-20` 的 formal short-trade selected 可以从 `0` 抬到 `2`。
2. `2026-05-21` 的 formal short-trade selected 可以从 `0` 抬到 `6`。

这说明前面那条判断是对的：**执行治理过度拦截** 确实是主问题之一，只要放开一条极窄的 relief 车道，正式主票数量立刻就能抬起来。

但回放也把新的瓶颈暴露得更清楚了：**promoted names 没进 buy-order 输入**。

### 新的第一堵墙已经前移到 watchlist / buy-order 输入

虽然 formal selected 已经被抬起来了，但最初这三天的最终 `buy_orders` 还是 `0`。原因不是 relief 没起作用，而是：

- 当前进入下单构造的 watchlist 太窄；
- `2026-05-20` 和 `2026-05-21` 的 watchlist 里主要还是 `300408`、`600487`；
- 真正被 relief 提升出来的票，例如 `002371`、`300395`，并不在这一步的 buy-order 输入里。

也就是说，当时的链路已经从：

`formal veto 把票压没`

变成了：

`formal veto 放开了一部分 -> 但 promoted names 没进 buy-order 输入 -> 实际仓位还是 0`

### 这一步后来已经落地成代码

针对上面这个断点，这一轮又继续往前推进了一步：已经把 **post-P5 buy-order backfill** 真正接进执行链。

当前实现的做法是：

1. P5 先把满足 relief 条件的 `near_miss` / `selected` 标成 `execution_eligible`；
2. 如果这些名字还不在现有 `buy_orders` 里，就从 `selection_target_shell_inputs` 里补一层 watchlist shell；
3. 然后用这层 shell 重新跑一次 buy-order 构造，而不是让它们永远停留在 selection target 层；
4. 如果原始 supplemental shell 的 `score_final` 太低，但 short-trade target 本身已经给出了更高的 `score_target`，则以后者作为 backfill 下单分值，避免像 `002371` 这种票再次被旧 boundary score 压成 `position_blocked_score`。

### 最新真实 replay 结果

把这版 backfill 先套回本周最关键的两天，第一轮结果是：

1. `2026-05-20`
   - formal short-trade selected：`0 -> 2`
   - execution eligible：`1`
   - final buy_orders：`0 -> 1`
   - backfilled ticker：`002371`
2. `2026-05-21`
   - formal short-trade selected：`0 -> 6`
   - execution eligible：`1`
   - final buy_orders：`0 -> 1`
   - backfilled ticker：`300395`

这说明当前链路已经不只是“把 formal selected 抬起来”，而是已经能把一部分高质量 relief 候选真正送进正式下单面。

### 第二轮迭代：把 carryover relief 接进 P2，并清理 replay 旧标记

继续往下追以后，又发现新的关键断点：

- `2026-05-20` 剩下那只没放出来的 `002222`，并不是 P5 拒绝，而是 **P2 还把它打成了 `p2_execution_blocked`**；
- `2026-05-21` 里像 `300054`、`688008`、`002222`、`600176` 这些票，也都一样；
- 更具体地说，不只是 P2 白名单太窄，还叠加了一个 replay 特有问题：artifact 里保留了旧的 `p2_execution_blocked=true` 标记，而当前放行逻辑以前只会 skip，不会把旧标记清掉。

这一步修完以后，当前链路又向前推进了一层：

1. `2026-05-20`
   - formal short-trade selected：`0 -> 2`
   - execution eligible：`0 -> 2`
   - final buy_orders：`0 -> 1`
   - final buy-order ticker：`002222`
2. `2026-05-21`
   - formal short-trade selected：`0 -> 6`
   - execution eligible：`0 -> 5`
   - final buy_orders：`0 -> 1`
   - final buy-order ticker：`300054`

这里可以看出一个很重要的事实：**当前已经不再是“票没被送进执行链”，而是“送进执行链的票变多了，但 relief 每天仍然只会正式落一张单”。**

### 第三轮迭代：把 `halt_relief` 从单槽放宽到双槽

继续回放以后，新的事实已经很明确：

- `2026-05-20`：`execution_eligible = [002222, 002371]`，此前只有 `002222` 能下单，`002371` 被 `filtered_by_daily_trade_limit` 挡掉；
- `2026-05-21`：`execution_eligible = [300054, 688008, 002222, 300395, 600176]`，此前只有 `300054` 能下单，其余都被 `filtered_by_daily_trade_limit` 挡掉。

而且从次日真实表现看，被挡掉的票里并不缺好票：

1. `002371 @ 2026-05-20`：次日最高约 `+10.0%`；
2. `688008 @ 2026-05-21`：次日最高约 `+5.56%`；
3. `300395 @ 2026-05-21`：次日最高约 `+10.5%`；
4. `600176 @ 2026-05-21`：次日最高/收盘约 `+7.97%`。

所以这一轮做了一个最小变更：不去重写排序逻辑，只把 `halt_relief` 的单日 `max_new_positions` 从 `1` 放到 `2`，其余 `limit_ratio=0.10`、`shadow_promotion` 单槽、P2/P5/P6 合同都保持不动。

把这版重新套回真实 artifact replay 后，结果变成：

1. `2026-05-20`
   - final buy_orders：`[002222, 002371]`
   - 之前的 `filtered_by_daily_trade_limit` 消失
2. `2026-05-21`
   - final buy_orders：`[300054, 688008]`
   - 之前的 `filtered_by_daily_trade_limit` 消失

这说明当前剩余主瓶颈里，**`halt_relief` 单槽限流确实过于保守**，而且它已经不是“风控上限保护”这么简单，而是在真实回放里直接压掉了本可以进入正式执行面的第二只票。

### 第四轮迭代：把 `halt_relief` 的排序键改成历史先验优先

双槽放开以后，新的问题就更清楚了：虽然 `2026-05-21` 已经不再被 daily limit 卡死，但前二仍然是按 `score_final / quality_score` 排出来的，结果是：

- 旧前二：`[300054, 688008]`
- 其中 `300054` 的次日收盘几乎持平；
- 但同一批 `execution_eligible` 里，`600176`、`002222`、`300395` 的历史先验更强，且次日实际表现也更不差。

所以这一轮没有继续加名额，而是改了 **`halt_relief` 车道内部的排序逻辑**：

1. 默认车道仍然按原来的 `score_final` 排；
2. 只有 `halt_relief` 会额外计算 `daily_limit_priority`；
3. 这个优先级不再只看即时 score，而是改成：
   - `0.6 * next_high_hit_rate_at_threshold`
   - `0.3 * next_close_positive_rate`
   - `0.1 * evidence_score`（`evaluable_count` capped at 50）

也就是说，beta 不去碰已有 position sizing / P2 / P5 / P6，只是在 daily-limit 排序处，优先让 **更接近“5 日内冲击 +15%”目标** 的 `halt_relief` 候选排到前面。

### 新排序下的真实 replay 结果

把这版重新回放本周最关键的两天后：

1. `2026-05-20`
   - final buy_orders：`[002222, 002371]`
   - 与双槽版本一致
2. `2026-05-21`
   - final buy_orders：从 `[`300054`, `688008`]` 改成 `[`600176`, `002222`]`
   - `300054` 被挤出前二
   - `filtered_by_daily_trade_limit` 仍然为 `0`

如果只看次日真实表现，这次替换方向是向好的：

- `600176` 次日最高/收盘约 `+7.97%`
- `002222` 次日收盘约 `+4.95%`
- 被替下去的 `300054` 次日收盘几乎持平

这说明当前剩余问题已经不是“能不能把票送进正式执行面”，而是：**送进来以后，排序键是否真的围绕最终目标。**

### 现在剩下的重点

到这一步，系统已经从“执行链断裂”推进到了“执行链接通、容量放宽、且 `halt_relief` 排序开始贴近 5 日 +15% 目标”。下一轮最值得继续追的是：

1. `300395` 这类仍未进入前二、但盘后观察里显得偏强的票，是否应该在排序里给更高权重；
2. 长窗口 A/B 已经跑了第一版：在 11 个 `2026-05` 的单日 `live_m2_7_short_trade_only` replay 里，**只有 `2026-05-14` 和 `2026-05-21` 两天** 的前二发生了变化，因此当前排序改动更像是“精修前二”，不是大面积重排；
3. 前一轮收益对比里真正的口径错误，也已经定位清楚：**BTST 的 entry 应该按 `T+1 open` 算，而不是信号日 open**。把口径改正以后：
   - `2026-05-21`：旧前二 `[`300054`, `688008`]` 的次日均值约为 `mean_next_close_return=-0.86%`、`mean_next_high_return=+1.69%`；新前二 `[`600176`, `002222`]` 提升到 `mean_next_close_return=+6.04%`、`mean_next_high_return=+6.75%`
   - `2026-05-14`：新前二的 `mean_next_high_return` 略强，但 `mean_next_close_return` 反而更弱，说明这套排序并不是每一天都单边占优；
4. 针对 `300395` 这类“收盘保持更强”的名字，这一轮还做过一次 **温和 close-heavy 调权** 的假设验证，但结果是否定的：它能通过合成测试，却**不能改变真实 `2026-05-21` replay**，因为实际样本里 `002222` 仍然会凭更强的 `next_high_hit_rate + evidence` 压过 `300395`。这意味着如果要把 `300395` 硬抬进前二，就需要更激进的 close-only 权重，而那已经很接近对少量 changed dates 的过拟合；
5. 也就是说，当前 evidence 已经从“口径不一致无法比较”升级成“在 changed dates 上，新排序 **总体偏向改善，但仍有反例**”，下一轮应该继续扩到更长窗口看胜率和赔率的稳定性，而不是继续做小幅人工调权；
6. `shadow_promotion` 的扩展优先级目前也基本看清了：在这批 `2026-05` 单日 replay 里，真正出现双候选 `shadow_promotion` candidate plan 的只有 `2026-05-11` 和 `2026-05-13` 两天；
   - `2026-05-11`：即便套用 `halt_relief` 同款历史先验 priority，最终仍会保留 `300054`，不会改票；
   - `2026-05-13`：历史先验 priority 会把 `300054` 换成 `000338`，而从 `T+1` 表现看，`000338` 的确略好于 `300054`，但它的 evidence 只有 `6`，样本太薄；
7. 因此，`shadow_promotion` 不是当前最值得马上动代码的面。和 `halt_relief` 相比，它的双候选样本太少、改善证据也太薄，更适合作为后续长窗口验证项，而不是下一刀主线。
8. 更关键的是，把 changed dates 的比较真正抬到 **BTST 的 5 日目标口径** 后，当前证据会变得更保守：
   - `2026-05-14` 是目前唯一已经走满 5 日窗口的 changed date；
   - 在这一天，旧排序组合的 `mean_max_high_return_5d_from_t1_open ≈ +9.01%`，新排序只有 `≈ +4.52%`；
   - 两组都没有达到 `5 日 +15%` 命中，但**旧排序反而更接近目标**；
   - `2026-05-21` 虽然在 `T+1` 上明显改善，但当前只有 1 个已观察交易日，还不能拿来替代完整 5 日结论。
9. 所以，截止当前这轮证据，`halt_relief` 历史先验排序可以被视为一个 **有希望但尚未被 5 日目标充分证明** 的方向；它值得继续观察，但还不应该被当成“已经确认提升 5 日 +15% 命中率”的最终解。 
10. 把视角再拉回到 **当前稳定逻辑真实落单的整周样本**，结论会更直接：在 `2026-05-06` 到 `2026-05-14` 这些已经能完整观察 `5` 个交易日后验窗口的正式买单里，只有 `6` 笔样本，其中：
    - `hit_15pct_count = 1`
    - `hit_15pct_rate ≈ 16.67%`
    - `mean_max_high_return_5d ≈ +7.60%`
    - `mean_close_return_day5 ≈ -2.21%`
11. 这组数和目标 `5 日 +15% 命中率 >= 55%` 的差距太大，意味着**当前最大问题已经重新回到上游因子质量 / 标签质量 / 候选筛选质量本身**。换句话说，beta 和 gamma 已经把“票送不进去”这类执行链问题拆掉了不少，但 alpha 侧的候选质量还没有稳定地产出足够多的 `5 日 +15%` 名字。下一刀如果还主要停留在 execution gating 或 relief 排序层，边际收益大概率会越来越小。 
12. 进一步把这些完整 `5` 日窗口日期里的 **execution-eligible 候选** 和 **最终正式买单** 对齐后，还能得到一个更重要的反证：这些日期里并不存在“本来更强、但被 daily-limit 或排序误杀掉”的隐藏赢家。换句话说，当前这批完整窗口样本上的问题，已经不是排序没排好，而是**真正买到手的候选池本身就不够强**。
13. 再按车道拆开看，弱点会更集中：
    - `shadow_promotion`：`0 / 3` 命中 `5 日 +15%`，`mean_max_high_return_5d ≈ +7.09%`
    - `halt_relief`：`1 / 3` 命中 `5 日 +15%`，`mean_max_high_return_5d ≈ +8.12%`
14. 其中 `shadow_promotion_lane` 相关样本一共出现 `4` 次，`5` 日 +15% 命中率是 `0%`。这说明当前如果还要继续往上游优化，最值得优先怀疑的不是 daily-limit 容量，而是 **shadow_promotion 这类边界晋级样本的 5 日扩张质量** 仍然太弱，至少还没有被当前证据证明值得继续扩容。
15. 因此，下一阶段更合理的主线，不是继续在 beta / gamma 侧微调执行排序，而是让 alpha 先重做一版更贴近 `5 日 +15%` 目标的候选定义：优先筛掉样本太薄、只有边界突破但缺少新鲜催化或 5 日扩张证据的 promotion 名字，把精力重新转回到更强的上游标签和因子上。

### 第五轮迭代：same-ticker recent formal buy cooldown 只是 hygiene guard，不是主升率引擎

在把 relief alpha quality gate 接进执行链以后，又暴露出一个很像“低垂果实”的现象：**短窗口重复正式买入同一只票的赔率明显变差**。

- 已完整观察 `5` 日窗口的 fresh formal entry：
  - `hit_15pct_rate = 50%`
  - `mean_max_high_return_5d ≈ +14.56%`
- 已完整观察 `5` 日窗口的 repeat formal entry（当前样本主要是 `002222 @ 2026-05-14`）：
  - `hit_15pct_rate = 0%`
  - `mean_max_high_return_5d ≈ +3.78%`

所以这一步做了一个最小实现：复用现有 `blocked_buy_tickers` / reentry filter，不重写执行链，而是在 `run_post_market()` 入口自动 merge 最近 `2` 个自然日内的 formal buy cooldown。

### 当前实现与验证结果

1. 新增了一个 loader，会扫描最近的 `selection_snapshot.json`，提取 `live_m2_7_short_trade_only` 的 recent formal buy，自动生成：
   - `trigger_reason = recent_formal_buy_cooldown`
   - `exit_trade_date = <最近正式买入日>`
   - `blocked_until = 当前 trade_date + 1 day`
2. 生产代码已经接到 `src/execution/daily_pipeline.py`，并配套补了 helper / integration tests。
3. focused regression 通过：包含 cooldown helper、phase4 execution、execution eligibility、risk budget 等一组回归现在是 `213 passed`。

### 但真实历史 artifact replay 暂时看不到明显效果

把这版逻辑直接套回当前仓库里的历史 `data/reports` 时，有一个很现实的限制：

- 很多历史 `selection_snapshot.json` 是旧参数或旧治理链跑出来的；
- 它们顶层 `buy_orders` 仍然是空的；
- 所以自动 cooldown loader 在历史 artifact 上读不到那笔“最近正式买入”，自然也就挡不住 `002222 @ 2026-05-14` 这种 repeat。

换句话说，这不是 cooldown 逻辑本身失效，而是 **历史 artifact 没把当下 replay 视角下的 formal buy 真正落盘**，所以 file-based cooldown 无法直接在旧报表上复原出这条约束。

### 顺序 replay 的结论：有轻微改善，但远不够解释主问题

为了避免被旧 artifact 误导，这一步又额外做了一个**顺序 replay**：按交易日顺序用当前稳定逻辑重新生成 formal buys，再把前 `2` 天新生成的 formal buy 当成 cooldown 来源。

结果是：

1. `2026-05-14`
   - 原本：`[002222, 300054]`
   - 加 cooldown 后：`[300054, 688498]`
   - 确实把 repeat 的 `002222` 压掉了
2. `2026-05-21`
   - 原本：`[600176, 002222]`
   - 加 cooldown 后：`[600176, 688008]`
   - 同样把 recent repeat 的 `002222` 压掉了
3. 已完整 `5` 日窗口的统计只出现**轻微改善**：
   - `hit_15pct_rate`：仍是 `33.33%`
   - `mean_max_high_return_5d`：大约从 `+10.97%` 升到 `+11.11%`

这组结果足够说明两件事：

1. **same-ticker recent formal buy cooldown 是合理的 hygiene guard**，它能去掉一类明显偏弱的短窗口重复入场；
2. 但它**不是当前胜率和赔率的主矛盾**，因为即便把 repeat weak entry 压掉，系统的 `5 日 +15%` 指标也只得到边际改善。

### 所以这条线当前的定位

截至这一轮，same-ticker cooldown 更适合作为：

- 一个低风险、行为合理的执行卫生规则；
- 一个有助于减少重复追同票的轻量补丁；
- 但不是应该继续重仓投入的主优化方向。

真正的大问题依然在上游：**能进 formal buy 的名字本身离 `5 日 +15% / 55%` 目标还差得很远**。因此，alpha / beta / gamma 的下一轮主线仍然应该回到：

1. 让 alpha 继续重做更贴近 `5 日扩张` 的候选定义和标签；
2. beta 只保留这类 hygiene 规则，不再把主要时间花在 execution 小修补上；
3. gamma 用更长窗口继续验证，防止把边际改善误判成主因子突破。

### 第六轮迭代：runtime historical_prior 的 5D 数据链已经接通，但还不能直接硬 gate

前面有一个长期 blocker：**运行时 `historical_prior` 没有任何 `5D/+15%` 字段**。这会导致 alpha / beta / gamma 明知道仓库里已经有不少 `5 日 +15%` 后验研究产物，却没法把这些证据带回 `daily_pipeline`。

这一轮先做了一个保守但关键的解法：**不等上游 schema 改造，先把现有研究产物 merge 回 runtime prior**。

当前接入的源有两类：

1. `btst_5d_15pct_boundary_contract_inspection_latest.json`
   - 提供 `boundary_rows`
   - 包含 `future_high_hit_15pct_2_5d`、`max_future_high_return_2_5d`、`time_to_hit_15pct`
   - 覆盖主要是 `short_trade_boundary / layer_b_boundary`
2. `btst_5d_15pct_trend_gate_oos_validation_latest.json`
   - 提供 `candidate_manifest`
   - 覆盖 `catalyst_theme / short_trade_boundary` 等 trend-continuation 子集
   - 同样有逐行 `future_high_hit_15pct_2_5d` 与 `max_future_high_return_2_5d`

### 现在 runtime prior 新带出的字段

合并后，已有 next-day `historical_prior` 的 ticker 会额外带出：

- `five_day_evaluable_count`
- `five_day_hit_rate_at_15pct`
- `five_day_mean_max_future_high_return_2_5d`
- `five_day_time_to_hit_15pct_median`（如果源里有）
- `five_day_prior_sources`

并且这些字段会继续跟着 `historical_prior` 被 attach 到 watchlist / selection target runtime 上，不再只能留在研究脚本或静态 JSON 里。

### 这一步已经在真实数据上验证可用

把 loader 套回当前 `data/reports` 后，已经能看到一些具体 ticker 带出 5D 先验：

1. `300054`
   - `five_day_evaluable_count = 9`
   - `five_day_hit_rate_at_15pct = 33.33%`
   - `five_day_mean_max_future_high_return_2_5d ≈ +10.03%`
   - `five_day_prior_sources = trend_gate_oos_validation`
2. `600176`
   - `five_day_evaluable_count = 1`
   - `five_day_hit_rate_at_15pct = 0%`
   - `five_day_mean_max_future_high_return_2_5d ≈ +5.96%`
   - `five_day_prior_sources = boundary_contract_inspection`

这说明“runtime 完全拿不到 5D evidence”这个 blocker 已经不是绝对成立了。

### 但为什么现在还不能直接把它写成 hard gate

虽然数据链通了，但覆盖和稳健性还不够：

1. **覆盖面是部分的，不是全量的**
   - 像 `300054` 这种能拿到趋势研究样本；
   - 但 `002222`、`300395` 这类当前票，并不一定已经有可用的 `five_day_*` 字段。
2. **不同来源的样本语义不完全一样**
   - boundary inspection 更偏边界样本；
   - trend gate validation 更偏 trend-continuation 子集。
3. **OOS 研究本身还没有 rollout-ready**
   - 例如 `trend_gate_oos_validation_latest.json` 的 candidate summary 虽然整体比 base 更好；
   - 但 `2026-05` 的 OOS 月度表现只有 `hit_rate_15pct ≈ 30.43%`、`mean_max_future_high_return_2_5d ≈ 9.97%`
   - 还远没有达到可以直接当默认 runtime gate 的强度。

### 所以这一步当前的正确定位

到这里，`five-day-prior-gate` 这条线已经从“数据源 blocked”推进到了“**runtime 可观测，但 gating policy 仍待设计**”。

这意味着下一阶段可以做的是：

1. 先把 `five_day_*` 字段作为 runtime diagnostics / ranking overlay 的候选输入；
2. 只在 coverage 足够、样本语义一致的子集上讨论 soft downgrade 或排序加权；
3. 暂时不要把它直接写成全局 hard gate，避免把“部分研究证据”误当成“全量稳定先验”。

换句话说，**5D prior 数据链已经接通，但 5D prior gate 还没有到可以一刀切上线的阶段**。这一步的价值，不是立刻提高收益，而是把后续真正贴近 `5 日 +15%` 目标的 runtime 优化，第一次变成了可执行任务。

### 第七轮迭代：最保守的 5D soft overlay 能安全落地，但当前 live replay 还打不动

既然 hard gate 还不安全，这一轮又试了一个**更保守的中间形态**：不在 P3 / selection target 上直接挡票，而是把 `five_day_*` 字段只作为 **committee retention support 的软惩罚**。

规则刻意收得很窄：

1. 只有在 `five_day_evaluable_count >= 8` 时才生效；
2. 只惩罚同时满足：
   - `five_day_hit_rate_at_15pct` 偏低
   - `five_day_mean_max_future_high_return_2_5d` 也偏低
3. 样本太薄时完全忽略，不把 `600176` 这种只有 `1` 条 5D 记录的 ticker 误伤。

### 这一步为什么先落在 committee retention

因为 committee retention 本来就在吃 `historical_continuation_prior_score` 和 prior payoff asymmetry：

- 它已经是一个软约束，不是硬 veto；
- 可以先验证“5D 弱先验是否值得让 support score 稍微降一点”；
- 就算错了，也不至于像 hard gate 那样直接把票压没。

### 测试与 replay 的结果

这轮已经补了明确的 TDD：

1. `5D` 样本足够、且 hit rate / mean return 都偏弱时，应出现 soft penalty；
2. `5D` 样本太薄时，不应触发这层 penalty。

相关 focused regression 已经通过。

但把这版重新套回当前关键日期 replay 后，结果也很明确：

- `2026-05-14` 仍然是 `[002222, 300054]`
- `2026-05-20` 仍然是 `[002222]`
- `2026-05-21` 仍然是 `[600176, 002222]`
- 已完整 `5` 日窗口的 `hit_15pct_rate` 与 `mean_max_high_return_5d` 也没有发生变化

### 这个结果反而进一步澄清了问题

它说明：

1. **这类 5D soft overlay 是安全的，但力度还不够成为当前主杠杆**；
2. 当前 live BTST 主通道里，更前面的候选定义 / 标签结构，依然比 runtime soft support 微调更重要；
3. 也就是说，即使把 runtime prior 往 `5 日 +15%` 目标方向轻轻推了一下，系统现在真正缺的仍然是**更强的上游样本本体**，而不是又一层 execution / committee 小修。

所以，截止当前这轮，最合理的判断是：

- `five_day_*` runtime prior：**值得保留，并继续作为 diagnostics 能力建设**
- `5D soft overlay`：**可以存在，但暂时不该被高估**
- 下一阶段主线：仍然回到 alpha 因子 / 标签重构，而不是继续叠 runtime 微惩罚

### 第八轮迭代：shadow_promotion 的 5D 质量软约束，已经能改变 shadow lane 排序，但还没证明能改变正式 buy_orders

既然 committee 那一层的 5D soft overlay 打不动 live replay，这一轮又把 `five_day_*` 更进一步地下沉到了 **`resolve_btst_shadow_promotion_payload()`** 本身，但仍然坚持三条边界：

1. **不做 hard gate**：没有 5D 数据时完全退化回原逻辑；
2. **只做 soft priority penalty**：不直接取消 `shadow_promotion` 资格；
3. **必须给显式 reason / tag**：避免后面看到“排序变了”，却不知道是被哪条 5D 证据压下去。

当前实现把 shadow lane 的 5D 证据分成三档：

1. `insufficient`
   - 没有 5D 字段，或者 `five_day_evaluable_count < 8`
   - `priority_penalty = 0`
2. `fragile`
   - `five_day_evaluable_count >= 8`
   - 但 `five_day_hit_rate_at_15pct` 和 `five_day_mean_max_future_high_return_2_5d` 只是勉强，不够稳
   - `priority_penalty = 0.08`
3. `weak`
   - 同样要求样本足够
   - 且 `five_day_hit_rate_at_15pct`、`five_day_mean_max_future_high_return_2_5d` 都明显偏弱
   - `priority_penalty = 0.18`

也就是说，这一步不是把 `shadow_promotion` 票直接挡掉，而是在 **single-slot daily limit 排序** 时，让 robust 但 5D 扩张证据偏弱的名字往后排。

### 这一步已经拿到的真实 artifact 证据

这次没有停留在合成测试，而是把真实 frozen replay artifact 重建到 `DailyPipeline(frozen_post_market_plans=...)` 上，专门检查 `shadow_promotion` lane 的候选顺序。

#### `2026-05-11`

- `shadow_promotion` 候选只有两只：
  - `603629`
    - `score_final ≈ 0.4234`
    - `five_day_quality_label = insufficient`
    - `priority_penalty = 0`
  - `300054`
    - `score_final ≈ 0.3335`
    - `five_day_quality_label = fragile`
    - `priority_penalty = 0.08`
- 排序前后都是：
  - before：`[603629, 300054]`
  - after：`[603629, 300054]`

这说明在 `2026-05-11`，5D fragile penalty 只是进一步拉大了已有差距，并没有真正改票。

#### `2026-05-13`

- `shadow_promotion` 候选有五只：
  - `603629`：`score_final ≈ 0.4253`，`five_day = insufficient`
  - `300054`：`score_final ≈ 0.3540`，`five_day = fragile`，`penalty = 0.08`
  - `002222`：`score_final ≈ 0.3406`，`five_day = insufficient`
  - `688008`：`score_final ≈ 0.3380`，`five_day = insufficient`
  - `601179`：`score_final ≈ 0.3023`，`five_day = insufficient`
- 排序在这一天下面发生了真实变化：
  - before：`[603629, 300054, 002222, 688008, 601179]`
  - after：`[603629, 002222, 688008, 601179, 300054]`

这里的关键不是 `300054` 被一刀切否掉，而是：

- 它依然保留 `shadow_promotion` 资格；
- 但因为 5D evidence 只有 `fragile`，在 single-slot 排序里被 `002222 / 688008 / 601179` 反超；
- 这证明 **shadow five-day soft penalty 已经不只是“理论上可用”，而是确实能在真实 artifact 上改变 shadow lane 的相对顺序**。

### 但为什么现在还不能把它写成“已验证有效”

这里仍然要保持克制，因为当前拿到的证据，只能证明：

1. **shadow lane 排序发生了真实变化**；
2. 这个变化来自 5D fragile penalty，而不是别的 incidental noise；
3. 缺失 5D 数据的名字仍然完全按原逻辑退化，没有被 blanket veto。

但还不能证明：

1. 这次改序已经稳定改变了最终正式 `buy_orders`；
2. 更不能证明它已经提高了 `5 日 +15% / 55%` 指标。

原因也很现实：

- 当前仓库里可直接复原的 `daily_events` / `selection_target_replay_input` artifact，更容易稳定还原 **shadow lane 排序**；
- 旧 `daily_events` 里的 `risk_metrics.funnel_diagnostics.filters.buy_orders` 还会夹带历史运行时留下的 `blocked_by_exit_cooldown` 摘要，容易把 source artifact 自带状态误看成“这轮 replay 新产生的 cooldown”；
- 现在跨日 frozen replay harness 已经在回放前主动清空这层旧 `buy_orders` filter summary，确保顺序回放只反映**当前逻辑 + 当前跨日 block 输入**；
- 但即便剥离了这层 artifact 污染，当前也还没直接复原出那条“按交易日顺序重生成 formal buys”的完整收益改善证据；
- 所以这一步目前是 **行为已改变、方向更贴近目标，但收益验证还没收口**。

### 这一步当前的正确定位

截止这一轮，`shadow_promotion` 的 5D 质量软约束可以被定性为：

1. **安全落地**
   - 缺失 5D 数据不误杀；
   - 只是 soft ranking，不是 hard veto；
   - payload 已经显式暴露：
     - `five_day_quality_label`
     - `five_day_quality_reason`
     - `five_day_priority_penalty`
2. **真实 artifact 可观测**
   - 至少在 `2026-05-13`，shadow lane 顺序已经被实际改动
3. **但仍属半验证状态**
   - 还不能宣称它已经改善正式 buy_orders 或 5D outcome

后面又补了一轮更干净的验证：在跨日 frozen replay harness 先剥离 source artifact 里陈旧的 `filters.buy_orders` 摘要后，再对 `20260518` 这批主线相关窗口做 `current vs penalty-disabled` A/B 顺序回放：

- `paper_trading_window_20260407_20260413_live_m2_7_001309_window_generation_20260518`
- `paper_trading_window_20260415_20260423_live_m2_7_independent_window_validation_20260518`
- `paper_trading_window_20260415_20260423_live_m2_7_independent_window_validation_20260518_rerun`
- `paper_trading_window_20260429_20260514_live_m2_7_001309_window_generation_20260518`

结果是：**4 个窗口里都没有出现 `final formal buy_orders` 的变化**。这意味着这条 shadow five-day soft penalty，至少在当前可复原的主线窗口上，已经可以暂时定性为：

1. 能改变 shadow lane 的局部排序；
2. 但还不足以翻动最终正式买单；
3. 因而暂时也没有新增的 `5D +15%` 收益改进证据。

所以，这一步可以作为当前 alpha 主线上的一个**低风险、可继续扩展的 runtime hook** 保留下来，但在现有主线窗口上，它更像“行为校正”而不是“已验证有效的胜率/赔率主杠杆”。
