# Replay Artifacts 选股复核页面使用手册

> 配套阅读：
>
> 1. [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)
> 2. [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)
> 3. [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)
> 4. [Replay Artifacts 案例手册：2026-03-11 的 300724 为什么入选但未买入](./replay-artifacts-case-study-20260311-300724.md)
> 5. [研究结论到优化 Backlog 的转换手册](./research-conclusion-to-optimization-backlog-handbook.md)

## 1. 文档目的

本文档面向已经能够登录 Web 界面的用户，目标不是解释系统架构如何实现，而是把以下问题讲清楚：

1. 这个页面到底是干什么的。
2. 它和“直接跑策略”“直接下单”是什么关系。
3. 应该按什么顺序使用这个页面来做选股复核。
4. 页面上每个区域分别看什么、为什么看、怎么看。
5. 如何把页面里的结构化信息转成一个可执行的人工研究流程。
6. 什么现象代表“选股质量问题”，什么现象代表“执行承接问题”。
7. 如何通过 feedback 把主观判断沉淀为后续可以复盘的结构化数据。

这份手册刻意写得非常细，是因为这个页面虽然看起来像一个结果浏览器，但它在当前系统中的真实定位更接近“研究复核工作台”。如果不明确它的定位，用户很容易把它当成一个“自动告诉你今天买什么”的页面，从而误读页面中的 watchlist、buy_orders、blocker 和 feedback 的含义。

---

## 2. 页面定位

### 2.1 这个页面不是干什么的

先把边界说清楚。

Replay Artifacts 页面不是：

1. 一个实时行情终端。
2. 一个自动生成当天新选股结果的页面。
3. 一个直接替代人工判断的“买入按钮”。
4. 一个保证收益的策略终端。

如果你希望“今天马上再跑一轮新选股”，你需要先运行 paper trading、frozen replay、回测或主流程分析任务，先生成新的 report。Replay Artifacts 页面只消费已经存在的 report 产物，不负责生成新的 report。

### 2.2 这个页面是干什么的

它的核心用途是三件事：

1. 读取某次运行已经产出的结构化选股结果。
2. 帮助你区分选股层和执行层的问题来源。
3. 让你把人工判断沉淀为 research feedback，形成后续可以复盘的证据。

换句话说，这个页面不是“选股引擎”，而是“选股结果复核器”。

### 2.3 为什么要先复核，再谈优化

量化和系统化研究里，一个常见误区是直接根据最终收益去调整策略。但如果你不先拆开“选股质量”和“执行承接”，你会不知道问题到底出在哪一层。

例如某只股票：

1. 被系统认为值得关注，所以进入 watchlist。
2. 但因为再入场规则、风险约束或止损后的观察期，没有变成 buy_order。

如果你只看最终没有买入，就会误以为是“系统不会选股”。实际上可能是“系统会选股，但执行层在当前时点不允许承接”。这两种结论对应完全不同的优化方向。

Replay Artifacts 页面就是为了解决这个分层解释问题。

---

## 3. 使用前提

### 3.1 你需要先具备什么

开始之前，你需要满足以下条件：

1. 你已经能够登录 Web 界面。
2. 系统中已经存在至少一个带 selection artifacts 的 report。
3. 你知道自己当前是在做哪一类工作：
   研究复盘
   选股质量检查
   执行阻塞诊断
   人工反馈沉淀

### 3.2 什么样的 report 才值得看

不是所有 report 都同样适合做选股复核。

优先选择满足以下条件的 report：

1. `selection_artifact_overview.available = true`
2. 有可切换的 trade date
3. 有 selected 或 near-miss 数据
4. 最好包含 buy_order blocker 或 feedback summary

当前比较典型的验证样本包括：

1. `paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323`
2. `paper_trading_20260311_selection_artifact_blocker_validation_20260323`
3. `logic_stop_threshold_scan_m0_20_selection_artifact_validation_20260322`
4. `logic_stop_threshold_scan_m0_20_selection_artifact_fallback_validation_20260322`

这些报告之所以适合看，是因为它们不只是有 summary，还有按 trade date 展开的 selection snapshot、review markdown、feedback 文件和 funnel 诊断信息。

---

## 4. 使用总流程

如果你只记一条主线，请记下面这个流程：

1. 选 report。
2. 选 trade date。
3. 先看运行概览和 selection artifact overview。
4. 再看 selected candidates。
5. 再看 execution bridge。
6. 再看 rejected near misses。
7. 再看 Funnel Drilldown。
8. 再看 Layer C Analyst View。
9. 再看 Research Prompts 和 selection review markdown。
10. 最后写 feedback。

这个顺序不是随便排的，而是从“结果概览”逐层深入到“原因解释”和“人工结论”，可以最大限度减少误判。

---

## 5. 页面结构总览

虽然具体排版会随着前端迭代调整，但页面信息大致可以分成以下几个层级：

1. Report 选择区
2. 报告级 KPI 和 artifact overview
3. Trade date 选择区
4. 当日 selection artifact 详情
5. Selected Candidates 表
6. Rejected Near Misses 表
7. Funnel Drilldown
8. Layer C Analyst View
9. Research Prompts
10. Feedback 提交表单
11. Feedback Records 表
12. selection_review.md 预览区

你可以把它理解成：

1. 报告级区域负责回答“这次运行大体发生了什么”。
2. 日级区域负责回答“某一天具体选了谁、为什么选、为什么没承接”。
3. Feedback 区域负责回答“我看完以后怎么把结论写回系统”。

---

## 6. 第一步：选择 report

### 6.1 如何操作

1. 登录后进入 `Settings -> Replay Artifacts`。
2. 在 report 列表或 report selector 中选一个报告。
3. 优先挑带 selection artifacts 的报告，不要先从没有 selection artifacts 的报告开始。

### 6.2 为什么先选 report，而不是先看个股

因为这个页面的最小分析单位不是“股票”，而是“某次运行中的某个交易日”。

一个股票是否值得看，必须放在具体运行和具体日期里判断，否则你会失去上下文：

1. 当时的筛选阈值是什么。
2. 当时的模型是什么。
3. 当时的 trade date 是什么。
4. 当时的执行层是否存在阻塞。

所以正确顺序一定是先确定运行上下文，再看股票。

### 6.3 选择 report 时该看什么

选 report 时建议先看几个总体指标：

1. 时间窗口是否合理。
2. model_provider 和 model_name 是什么。
3. selection_artifact_overview 是否 available。
4. trade_date_count 是否足够。
5. blocker_counts 是否非空。
6. feedback_summary 是否已有人工记录。

### 6.4 建议的选择策略

如果你是第一次使用，建议按下面顺序入手：

1. 先看单日、结构简单、问题明显的报告。
   例如只有 1 个 trade date 且存在 blocker 的报告。
2. 再看多日窗口报告。
3. 最后再看带历史兼容回退的报告。

原因是：

1. 单日报告更容易建立“页面字段和业务语义”的映射。
2. 多日报告适合做稳定性观察。
3. 回退报告虽然有价值，但解释粒度会比原生 strategy signals 粗一些，不适合作为第一眼学习样本。

---

## 7. 第二步：选择 trade date

### 7.1 如何操作

1. 选中 report 后，找到 trade date 下拉或切换器。
2. 选择你要复核的具体日期。
3. 等页面加载当日 selection artifact detail。

### 7.2 为什么 trade date 是核心分析粒度

这个系统是按交易日形成观察和决策的。哪怕是同一只股票，在不同 trade date 的状态也可能完全不同：

1. 前一天可能在 near-miss 区。
2. 第二天可能进入 watchlist。
3. 第三天可能进入 buy_orders。
4. 第四天可能因为 reentry 规则被阻塞。

如果你不按 trade date 切开，就无法理解“系统是在什么时间点、基于什么证据、做出了什么层级的决策”。

### 7.3 初次使用推荐的日期

如果你想快速理解页面字段之间的关系，推荐优先看：

1. `paper_trading_20260311_selection_artifact_blocker_validation_20260323`
2. trade date: `2026-03-11`

因为这个样本里有一只 selected 股票，但没有变成 buy_order，并且 blocker 信息清晰，最适合学习“研究通过但执行不承接”的场景。

---

## 8. 第三步：先看运行概览和 selection artifact overview

### 8.1 这里回答什么问题

进入某个 report 和 trade date 之后，不要立刻盯着单只股票。先看总体概览，先回答：

1. 这次运行是 paper trading、回测还是 frozen replay。
2. 时间窗口是什么。
3. 模型是什么。
4. 这个 report 是否真的有 selection artifacts。
5. 这个 report 下有多少个 trade date 可复核。

### 8.2 为什么这一步不能跳过

很多误判都来自“直接看单只股票，但忘了上下文”。

比如：

1. 同样是没有 buy_order，单日 blocker 报告和多日 replay 中的含义不同。
2. 不同模型产生的分歧强弱也可能不同。
3. 不同 plan_generation_mode 的数据完整度也可能不同。

所以先看 overview，本质上是在建立“分析坐标系”。

### 8.3 建议重点看哪些字段

建议你重点关注：

1. `window.start_date`
2. `window.end_date`
3. `run_header.mode`
4. `run_header.plan_generation_mode`
5. `run_header.model_provider`
6. `run_header.model_name`
7. `selection_artifact_overview.trade_date_count`
8. `selection_artifact_overview.available_trade_dates`
9. `selection_artifact_overview.blocker_counts`
10. `selection_artifact_overview.feedback_summary`

这些字段决定了你后续看页面时，应该用什么问题框架来解读内容。

---

## 9. 第四步：用 Selected Candidates 做第一轮选股筛选

### 9.1 Selected Candidates 是什么

`Selected Candidates` 不是“系统最终下了买单的股票列表”，而是“研究视角下值得重点审查的候选对象”。在当前设计里，它更接近 watchlist 视角，而不是 buy_orders 视角。

这点非常关键。

### 9.2 为什么 selected 不等于可买入股票

系统把流程拆成至少两层：

1. 研究层
   这个层级关心的是“值不值得关注”。
2. 执行层
   这个层级关心的是“此刻能不能承接为交易动作”。

所以：

1. selected 代表研究候选。
2. buy_orders 代表执行候选。

如果你把这两者混为一谈，会误把执行层的阻塞解释为选股层的失败。

### 9.3 实际操作方法

进入 `Selected Candidates` 表后，建议每只股票至少按下面顺序看一遍：

1. symbol
2. score_final
3. layer_b_summary
4. layer_c_summary
5. execution_bridge
6. research_prompts

### 9.4 第一个判断：这只股票是否值得继续看

你可以先做一个非常粗的筛选：

1. `score_final` 是否在当日相对靠前。
2. Layer B 因子是否说得清楚。
3. Layer C 共识是否极度分裂。
4. execution_bridge 是否显示明显阻塞。

如果满足下面条件，通常值得继续深入：

1. 分数不低。
2. top factors 比较清晰。
3. Layer C 不是完全对冲。
4. 即使没进 buy_orders，也能明确解释为什么没进。

### 9.5 第二个判断：这是“研究优先股”还是“执行优先股”

把候选股分成两类：

1. 研究优先股
   值得你继续分析，但不一定今天能买。
2. 执行优先股
   今天已经满足执行条件，值得重点跟踪。

最直接的判断字段就是：

1. `execution_bridge.included_in_buy_orders`

如果为 true，说明它不仅研究上通过，而且执行上也承接了。

如果为 false，说明研究层觉得它值得看，但执行层当前不接。

---

## 10. 第五步：看 Layer B Summary，理解“为什么被选出来”

### 10.1 Layer B 在这里代表什么

Layer B 可以粗略理解为“规则化、多因子、预筛选后的综合打分层”。它负责把大量候选股票收缩成一个更小、更可分析的候选池。

### 10.2 页面里应该看什么

在 selected candidate 里，你通常会看到：

1. `top_factors`
2. `explanation_source`
3. `fallback_used`

### 10.3 为什么必须看 top_factors

如果你不看 top factors，就只知道“它分高”，但不知道“它为什么分高”。

一个可复核的选股理由，至少要回答：

1. 是基本面拉高了分数。
2. 是趋势拉高了分数。
3. 是估值、情绪、动量还是逻辑分。

当你能够把分数拆成因子来源时，才有可能判断：

1. 这是结构性优势。
2. 还是一次性噪声。

### 10.4 fallback_used 的意义

有些历史 frozen replay 没有原生 strategy_signals，这时页面展示的 Layer B 摘要可能来自回退构造。

如果看到：

1. `explanation_source = legacy_plan_fields`
2. `fallback_used = true`

意味着当前解释是“兼容性解释”，而不是最原始的策略证据。

这并不等于没价值，但你在做结论时要更保守：

1. 它更适合做方向性辅助判断。
2. 不适合当成精细策略证据做过度推理。

### 10.5 实际分析方法

分析 top factors 时，建议问自己三个问题：

1. 主导因子是否逻辑一致。
2. 主导因子是否容易受短期噪声污染。
3. 主导因子是否和你对这只股票的基本认知相符。

如果一个股票分数很高，但 top factors 全是你无法解释、或者明显过度依赖短期波动的信号，就不应直接把它视为高质量候选。

---

## 11. 第六步：看 Layer C Summary，判断“共识质量”

### 11.1 Layer C 代表什么

Layer C 是多分析师聚合层。它不只是看单个因子，而是看多个分析角色在这只股票上的综合态度和分歧程度。

### 11.2 为什么 Layer C 很重要

Layer B 告诉你“它在规则层面看起来不错”。
Layer C 告诉你“不同分析角色是否真的大体认同这个结论”。

如果只看 Layer B，很容易把某些因子驱动的高分票误当成高质量票。
Layer C 的价值在于给你一个“共识强度”和“分歧结构”的视角。

### 11.3 重点字段

你应重点看：

1. `active_agent_count`
2. `positive_agent_count`
3. `negative_agent_count`
4. `neutral_agent_count`
5. `cohort_contributions`
6. `top_positive_agents`
7. `top_negative_agents`

### 11.4 如何判断共识质量

可以按下面方式判断：

1. 正向多、负向少、cohort 方向一致
   说明共识较强。
2. 正负接近、贡献相互抵消
   说明共识偏弱，属于高分歧对象。
3. 负向 agent 数量不多，但理由极强
   仍然需要警惕，不能只用人数决定结论。

### 11.5 推荐的分析动作

对每只 selected 股票，建议至少回答：

1. 支持它的角色主要是谁。
2. 反对它的角色主要是谁。
3. 反对理由是结构性问题，还是短期担忧。

如果负向意见聚焦在估值过高、事件噪声、监管不确定性等关键风险上，即使 final score 不低，也不应轻易给出“高质量入选”的正面 verdict。

---

## 12. 第七步：看 Execution Bridge，区分“会选”还是“会买”

### 12.1 Execution Bridge 的作用

Execution Bridge 是这个页面最重要的桥接信息之一。它把研究层的选股结果和执行层的实际承接状态连起来。

### 12.2 为什么这个区块最容易被误读

很多用户看见一只股票在 selected 里，就下意识认为“系统建议买”。这其实不准确。

正确理解应该是：

1. selected 说明它通过了研究侧的主要筛选。
2. execution_bridge 才告诉你它有没有被执行层真正接纳。

### 12.3 重点字段

1. `included_in_buy_orders`
2. `planned_shares`
3. `planned_amount`
4. `target_weight`
5. `block_reason`
6. `blocked_until`
7. `reentry_review_until`
8. `exit_trade_date`
9. `trigger_reason`

### 12.4 如何分析

#### 情况 A：included_in_buy_orders = true

说明：

1. 研究层通过。
2. 执行层也通过。
3. 这类票最接近“实际可交易候选”。

这时你要做的是：

1. 看目标权重是否过高。
2. 看 planned_amount 是否与整体仓位逻辑匹配。
3. 看它是否在当日属于少数高确信度执行对象。

#### 情况 B：included_in_buy_orders = false

说明：

1. 研究层不一定有问题。
2. 更可能是执行层有阻塞。

这时你要立即看：

1. `block_reason`
2. `reentry_review_until`
3. `trigger_reason`
4. `exit_trade_date`

### 12.5 为什么 blocker 信息这么重要

因为它让你能明确回答：

1. 这只股票是不是选得不好。
2. 还是选得不差，但当前不能承接。

这两者对应完全不同的策略改进方向：

1. 选股不好，要改 Layer B 或 Layer C。
2. 执行不承接，要改 reentry、risk gating 或仓位逻辑。

### 12.6 一个典型例子

在 blocker 验证样本中，`300724`：

1. 进入了 watchlist。
2. 没有进入 buy_orders。
3. 阻塞原因为 `blocked_by_reentry_score_confirmation`。

正确结论不是“系统不会选 300724”，而是“系统认为 300724 值得继续看，但在当前 reentry 规则下不允许立即承接成买单”。

---

## 13. 第八步：看 Rejected Near Misses，识别阈值误伤

### 13.1 Rejected Near Misses 是什么

这块展示的不是所有落选股票，而是“接近入选但最终落选”的 near-miss 样本。

### 13.2 为什么 near-miss 比普通落选更重要

因为它最能帮助你发现：

1. 阈值是否过严。
2. 某些优秀候选是否被误伤。
3. 某种 rejection stage 是否经常淘汰原本值得研究的票。

### 13.3 应该看什么

1. `rejection_stage`
2. `score_final`
3. `rejection_reason_codes`
4. `rejection_reason_text`

### 13.4 实际分析方法

建议把 near-miss 和 selected 放在一起比较：

1. 它和 selected 相比差在哪个阶段。
2. 是 Layer B 差一点，还是 Layer C 共识不够。
3. 落选原因是硬性风险，还是可以讨论的阈值边界。

### 13.5 什么时候可以怀疑“阈值误伤”

如果你看到 near-miss 同时满足：

1. 分数只略低于 selected。
2. 原因码集中在少量可调阈值上。
3. 人工看来它的基本逻辑并不弱。

那么这类样本就值得后续做阈值复盘，而不是直接忽略。

---

## 14. 第九步：看 Funnel Drilldown，定位卡在哪一层

### 14.1 Funnel Drilldown 的定位

这是当前页面最适合做“分层诊断”的区块。它直接把 selection snapshot 中的 funnel_diagnostics.filters 展开给你看。

当前重点看三层：

1. `layer_b`
2. `watchlist`
3. `buy_orders`

### 14.2 为什么这个区块非常关键

如果没有 Funnel Drilldown，你只能知道最后剩了几只股票，却不知道大多数股票是在什么阶段被过滤掉的。这样你只能得到“结果”，得不到“路径”。

有了 Funnel Drilldown，你可以回答：

1. 是不是在 Layer B 就过滤得太狠。
2. 是不是进入 watchlist 后被研究层否掉。
3. 是不是进入研究候选后，被执行层规则拦住。

### 14.3 每一层应该怎么看

#### Layer B Filters

这层主要看：

1. `filtered_count`
2. `reason_counts`
3. 代表性 ticker

如果这里过滤量极大，通常说明：

1. 预筛阈值严格。
2. 大多数股票在规则化因子层就不具备进一步研究价值。

#### Watchlist Filters

这层表示通过 Layer B 后，哪些候选没有进入更高优先级的研究名单。

如果这层过滤量大，说明问题更可能出在：

1. 人工解释层不够强。
2. Layer C 分歧较大。
3. 研究层要求较严。

#### Buy Order Filters

这层最适合识别执行承接问题。

如果一只股票出现在这里，说明：

1. 它已经很接近执行层。
2. 但仍然被某个交易规则拦住。

这时一定要重点看：

1. reason
2. required_score
3. reentry_review_until
4. trigger_reason
5. exit_trade_date

### 14.4 如何用它指导后续优化

1. Layer B 过滤过多
   优先检查因子阈值、候选池压缩逻辑。
2. Watchlist 过滤过多
   优先检查 Layer C 聚合或研究阈值。
3. Buy Orders 过滤过多
   优先检查执行约束、reentry 机制、风险规则。

这就是这个区块最核心的价值：它把“问题属于哪一层”这件事做了显式暴露。

---

## 15. 第十步：看 Research Prompts 和 selection_review.md，完成人工解释闭环

### 15.1 Research Prompts 是什么

Research Prompts 是系统为研究员准备的人工复核提示，通常包含两类问题：

1. `why_selected`
2. `what_to_check`

### 15.2 为什么这一步很重要

前面的表格字段帮你快速定位“哪里值得看”。Research Prompts 则帮你把这种定位转成“具体该看什么问题”。

也就是说：

1. 表格提供结构化事实。
2. Prompts 提供人工复核提纲。

### 15.3 推荐使用方式

看每只重点股票时，建议做两步：

1. 先看 `why_selected`
   明确系统给出的正向理由。
2. 再看 `what_to_check`
   明确自己应该重点质疑什么。

这种顺序可以避免两种极端：

1. 只看好，不看风险。
2. 一开始就质疑，导致忽略系统真正看到的结构性理由。

### 15.4 selection_review.md 有什么价值

selection_review.md 是从 snapshot 派生出来的人类可读日审查稿。它的作用不是替代结构化数据，而是给你一个“日报视角”的串联摘要。

适合用来做：

1. 快速扫读当日核心结论。
2. 检查 selected、rejected、buy_order blocker 的叙述是否连贯。
3. 帮助你在写 feedback 之前形成一个完整的人工印象。

---

## 16. 第十一步：如何真正“用这个页面选股”

这里要非常明确。

“用这个页面选股”不是指页面替你做出最终交易决策，而是指你利用这个页面的结构化信息，把系统给出的候选对象分成不同优先级。

### 16.1 一个实用的人工筛选框架

你可以把候选对象分成三档：

#### A 档：高优先级执行候选

同时满足：

1. 在 selected 中。
2. `score_final` 靠前。
3. Layer B 解释清楚。
4. Layer C 共识偏强。
5. `included_in_buy_orders = true`。
6. 没有明显 blocker。

这类票最适合进入“重点跟踪或重点讨论”清单。

#### B 档：高优先级研究候选

满足：

1. 在 selected 中。
2. 分数不低。
3. 逻辑清楚。
4. 但 `included_in_buy_orders = false`。
5. blocker 是执行层规则，而不是研究层逻辑崩塌。

这类票适合进入“继续观察、等待承接条件成熟”的清单。

#### C 档：需要谨慎或淘汰

满足任一情况：

1. Layer C 极度分裂。
2. top factors 不清楚。
3. blocker 指向强风险。
4. near-miss 落选原因看起来合理且不可争辩。

这类票不应占用太多研究精力。

### 16.2 你最终要输出什么

使用完页面之后，建议你不要只停在“我看懂了”，而是输出一个自己的人工结果：

1. 今日执行优先股
2. 今日研究优先股
3. 今日 near-miss 值得复核样本
4. 今日明显属于执行阻塞而非选股失败的样本

这样你就把页面的浏览行为，变成了一个可复用的研究流程。

---

## 17. 第十二步：如何写 feedback

### 17.1 为什么一定要写 feedback

如果你只是看页面，不写 feedback，那么这次人工判断对系统未来几乎没有结构化价值。写 feedback 的意义是：

1. 把主观研究判断变成可记录、可汇总、可复盘的数据。
2. 为后续统计“哪些标签经常对应高质量候选”提供原始材料。
3. 让团队多人协作时，不需要每次重新口头解释为什么这只票质量高或质量弱。

### 17.2 表单如何填写

#### Symbol

选择你正在复核的股票代码。

#### Primary Tag

主标签代表你对该记录的最核心判断。示例包括：

1. `high_quality_selection`
2. `thesis_clear`
3. `crowded_trade_risk`
4. `weak_edge`
5. `threshold_false_negative`
6. `event_noise_suspected`

#### Additional Tags

用于补充侧面判断。主标签只能有一个，但补充标签可以有多个。

#### Review Status

常见取值：

1. `draft`
2. `final`
3. `adjudicated`

推荐用法：

1. 第一次快速浏览先写 `draft`。
2. 复核确认后再改 `final`。
3. 如果经过团队讨论或更高层判断，再标 `adjudicated`。

#### Research Verdict

这里用一句短语概括你的结论，例如：

1. `selected_for_good_reason`
2. `selection_quality_uncertain`
3. `blocked_by_execution_not_selection`
4. `likely_threshold_false_negative`

#### Confidence

表示你对这条人工判断的主观把握，不代表未来收益概率。

#### Notes

这里是最重要的自由文本区。建议写：

1. 你为什么给这个标签。
2. 你认为它更像选股问题还是执行问题。
3. 有哪些证据支持你的结论。

### 17.3 建议的写法模板

你可以参考这样的格式：

1. 结论
2. 证据
3. 风险
4. 下一步建议

例如：

`300724 进入 watchlist 的逻辑可以解释，但当前未承接成 buy_order 主要由 reentry 规则触发，不应简单归因于选股失败。建议标记为 weak_edge 或 blocked_by_execution_not_selection，并继续观察 reentry_review_until 后的行为。`

---

## 18. 推荐的日常使用节奏

### 18.1 快速版，10 分钟流程

适合每天快速扫一遍：

1. 选 report。
2. 选 trade date。
3. 看 Selected Candidates。
4. 看 Execution Bridge。
5. 看 Funnel Drilldown。
6. 对重点票写 draft feedback。

### 18.2 标准版，20 到 30 分钟流程

适合做正式复核：

1. 看 report overview。
2. 看当日 selected。
3. 看 Layer B 和 Layer C。
4. 看 Execution Bridge。
5. 看 Rejected Near Misses。
6. 看 Funnel Drilldown。
7. 看 Research Prompts。
8. 看 selection_review.md。
9. 写 final feedback。

### 18.3 复盘版，跨多日流程

适合做策略层分析：

1. 选多日窗口 report。
2. 按日期切换，记录每天 selected 和 blocker 的变化。
3. 统计哪些 blocker 最常出现。
4. 对比 near-miss 是否反复出现相似 rejection reason。
5. 汇总 feedback 中最常见的弱点标签。

这种方式最适合帮助后续做阈值、规则和解释质量的优化。

如果你准备把这套跨多日流程变成团队固定节奏，而不是个人临时回看，建议继续阅读 [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)。

---

## 19. 常见误区

### 误区 1：selected 就等于建议买入

不对。

selected 更偏研究候选。是否能买，必须再看 execution_bridge。

### 误区 2：没进 buy_orders 就说明系统选股失败

不对。

很多情况下是执行层 blocker，而不是选股层失败。

### 误区 3：只看分数，不看因子和共识

不对。

高分如果没有清晰因子来源和共识支持，可能只是表面信号。

### 误区 4：不看 near-miss

不对。

near-miss 往往最能暴露阈值误伤和可调边界。

### 误区 5：只看页面，不写 feedback

不对。

不写 feedback，就没有结构化人工结论，后续无法累计经验。

---

## 20. 一个完整示例：如何复核 2026-03-11 的 blocker 场景

下面给出一个完整的操作思路。

### 20.1 操作步骤

1. 进入 `Settings -> Replay Artifacts`。
2. 选择 report：`paper_trading_20260311_selection_artifact_blocker_validation_20260323`。
3. 选择 trade date：`2026-03-11`。
4. 看 Selected Candidates，定位到 `300724`。
5. 查看它的 Layer B summary，确认它确实是被筛出来的候选，而不是空白数据。
6. 查看 Layer C summary，确认它不是完全无共识的噪声对象。
7. 查看 Execution Bridge，发现 `included_in_buy_orders = false`。
8. 继续查看 blocker 字段，发现 `block_reason = blocked_by_reentry_score_confirmation`。
9. 查看 Funnel Drilldown，在 `buy_orders` 过滤层中再次看到 `300724` 和相同原因。
10. 得出结论：这不是“没被选中”，而是“被选中了，但被执行层阻塞”。
11. 在 feedback 表单里补一条 draft 或 final 记录，写清楚这次判断。

### 20.2 为什么这个例子重要

因为它完整演示了页面最核心的价值：

1. 不只是展示结果。
2. 还能解释路径。
3. 最后还能把人工判断写回系统。

这正是研究复核工作台和普通结果页面的本质区别。

---

## 21. 页面使用后的建议输出

每次复核完一个 trade date，建议你至少形成以下四类结论：

1. 今日最值得继续执行跟踪的股票
2. 今日最值得继续研究但暂不执行的股票
3. 今日最值得复核的 near-miss 样本
4. 今日最值得优化的系统层问题归因

其中第 4 类尤其重要。你应该明确写成：

1. Layer B 问题
2. Layer C 问题
3. Execution 问题
4. Threshold 问题
5. Explainability 问题

这样后续优化才不会混在一起。

如果你已经能把问题归到这五类，但还不确定应该如何变成后续策略或工程动作，请继续阅读 [研究结论到优化 Backlog 的转换手册](./research-conclusion-to-optimization-backlog-handbook.md)。

---

## 22. 故障排查

### 22.1 登录后看不到 report

先检查：

1. 后端是否正常启动。
2. 当前账号是否拿到了有效 token。
3. `data/reports` 下是否确实存在 session_summary.json。

### 22.2 看得到 report，但没有 selection artifacts

说明该报告只具备 replay summary，不具备 selection artifact detail。应改选 `selection_artifact_overview.available = true` 的报告。

### 22.3 trade date 切换后没有 selected candidates

这不一定是 bug，可能是该日确实没有 selected 或 watchlist 为空。此时应看：

1. `universe_summary`
2. Funnel Drilldown
3. selection_review.md

### 22.4 feedback 提交后没有看到记录

先检查：

1. 当前 trade date 是否正确。
2. symbol 是否属于当日 snapshot 中的 known symbols。
3. 是否被 filter 条件隐藏。
4. 页面是否已刷新 day detail。

### 22.5 明明有 feedback，但顺序看起来不对

当前实现中，后端日级接口已经按 `created_at` 倒序返回，前端也会按时间倒序展示。如果顺序异常，优先怀疑：

1. 记录时间本身写得不对。
2. 本地服务未重启到最新版本。
3. 浏览器仍在使用旧缓存。

---

## 23. 最终建议

如果你把这页当成一个“今天该买什么”的页面，它的价值会被大幅低估。

如果你把它当成一个“研究证据整理和问题归因页面”，它的价值会非常高，因为它能够把以下几件事放到同一个界面里：

1. 选股事实
2. 因子解释
3. 分析师共识
4. 执行阻塞
5. near-miss 样本
6. 人工判断沉淀

最推荐的使用心法只有一句：

先判断它是不是值得研究，再判断它是不是值得执行，最后把你的判断写回去。

只要按照这个顺序操作，你就能稳定地区分：

1. 选股问题
2. 执行问题
3. 阈值问题
4. 解释问题

而这正是后续系统优化最需要的高质量输入。
