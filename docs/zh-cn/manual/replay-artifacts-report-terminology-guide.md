# Replay Artifacts 分析报告术语解析手册

> 配套阅读：
>
> 1. [Replay Artifacts 新人培训讲义](./replay-artifacts-newcomer-training-guide.md)
> 2. [Replay Artifacts 值班速查卡](./replay-artifacts-duty-cheatsheet.md)
> 3. [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)
> 4. [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
> 5. [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)
> 6. [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)
> 7. [Replay Artifacts 案例手册：2026-03-11 的 300724 为什么入选但未买入](./replay-artifacts-case-study-20260311-300724.md)

## 1. 这份文档解决什么问题

Replay Artifacts 的页面和报告里有很多术语，它们大多不是“好看一点的字段名”，而是系统在不同层级做判断时留下的结构化证据。

如果只看字面，用户很容易出现四类误判：

1. 把研究层结论误当成执行层结论。
2. 把系统状态字段误当成投资观点。
3. 把调试诊断字段误当成正式决策规则。
4. 把人工反馈流程字段误当成看多或看空标签。

这份手册的目标不是做一张简单的“中英文字段对照表”，而是把下面四件事讲透：

1. 每个术语是什么。
2. 为什么系统要记录它。
3. 它应该和哪些相邻字段一起看。
4. 你应该如何用这些术语来解读一份 Replay Artifacts 报告。

如果你读完后还只能复述“这个字段代表什么”，那还不够。正确目标是：你看到一份报告时，能够根据这些术语判断问题更像出在选股、执行、阈值、流程，还是缓存与运行质量。

---

## 2. 先建立一张系统地图

理解术语之前，先理解 Replay Artifacts 的最小结构。

### 2.1 五层结构

一份可复核的 Replay Artifacts 报告，通常是下面五层：

1. Report 层
   表示一次完整运行的容器，例如一个 paper trading 窗口、一次 frozen replay，或者一次 validation run。
2. Trade Date 层
   表示这个 report 中某一个交易日的决策切片。
3. Selection Artifact 层
   表示这个交易日留下的选股快照、复核 Markdown 和人工反馈文件。
4. Candidate 层
   表示某一只股票在这个交易日的具体状态，例如 selected、near-miss、buy_order blocker。
5. Feedback / Workflow 层
   表示人工复核如何把结论写回系统，以及这些结论如何进入后续流转。

### 2.2 为什么必须按层理解

很多术语只有放回它所在层级，才有正确含义。

例如：

1. `score_final` 是 Candidate 层字段，不是 Report 层表现指标。
2. `review_status` 是 Feedback 工作流字段，不是选股质量字段。
3. `funnel_diagnostics` 是诊断字段，不是用户直接配置的正式规则名字。
4. `cache_benchmark_overview` 是运行与数据复用证据，不是收益质量结论。

所以正确阅读顺序应当是：

1. 先确认当前看到的是哪一层。
2. 再判断这个术语回答的是“结果”“原因”“流程状态”还是“运行证据”。

---

## 3. 一份报告应该怎么读

如果你想稳定地读懂一份报告，建议按下面顺序，而不是随机扫字段：

1. 先看 Report 层，确认窗口、模式、模型、总体产物是否完整。
2. 再看 `selection_artifact_overview`，确认这份 report 是否真的有可复核的日级产物。
3. 选定一个 `trade_date`，进入日级 snapshot。
4. 先看 `selected`，理解系统为什么把某些股票推入研究高优区。
5. 再看 `execution_bridge` 和 `buy_orders`，判断研究结果有没有被执行层承接。
6. 再看 `rejected` 和 `funnel_diagnostics`，理解被挡掉的候选为什么没能进入下一层。
7. 最后看 `research_feedback`、`recent activity`、`workflow queue`，确认人工复核怎样沉淀和流转。

这背后的原因很简单：

1. Report 层回答“运行上下文是什么”。
2. Selection 层回答“系统选了什么”。
3. Execution 层回答“为什么没买，或者为什么只执行一部分”。
4. Feedback 层回答“人怎么判断，以及团队怎么继续跟进”。

---

## 4. Report 层术语

这一层回答的是：这次运行是什么、范围多大、产物是否完整、是否有足够证据可供复核。

### 4.1 `report_dir` / `report_name`

含义：

1. 一次运行在 `data/reports` 下的目录名。
2. 也是前后端定位这次 replay 的唯一标识。

为什么存在：

1. Replay Artifacts 不直接操作“策略对象”，而是操作“已经落盘的运行产物”。
2. 所以 report 名称本质上是这份证据包的主键。

怎么解读：

1. 名字里通常会带时间窗口、运行模式、模型或实验标签。
2. 名称本身不是结论，但能帮助你快速区分 baseline、probe、validation、trial 等不同用途。

不要误解为：

1. report 名越长越复杂就一定越重要。
2. report 名本身能说明收益质量或选股好坏。

### 4.2 `window.start_date` / `window.end_date`

含义：

1. 这次运行覆盖的时间窗口。

为什么存在：

1. 同一套机制在不同窗口可能表现完全不同。
2. 如果不看时间窗口，很多术语会脱离市场背景，例如某个 blocker 在短窗口里是偶发，在长窗口里则可能反复出现。

怎么解读：

1. 短窗口更适合定位单一问题样本。
2. 长窗口更适合看稳定性、复发性 blocker、feedback 累积和 workflow 负荷。

### 4.3 `run_header.mode`

含义：

1. 运行模式，例如 `live_pipeline`、`frozen_replay`、`backtesting`。

为什么存在：

1. 这个字段决定你看到的是“真实运行产物”“冻结计划回放”，还是“回测环境下的演算结果”。
2. 不同模式下，同一个术语的解释力度不同。

怎么解读：

1. `live_pipeline` 更接近真实日常使用。
2. `frozen_replay` 更适合做可重复验证和机制比对。
3. `backtesting` 更偏策略历史推演，不能等同于真实研究工作台证据。

### 4.4 `run_header.plan_generation_mode`

含义：

1. 计划生成方式，例如当前计划是实时生成，还是来自冻结计划源。

为什么存在：

1. 它决定这次运行的决策链是“现场生成”，还是“拿已有计划重放”。
2. 这会影响你如何解释某些 selection / execution 结果的可重复性。

### 4.5 `model_provider` / `model_name`

含义：

1. 本次运行使用的基础模型提供方和模型名称。

为什么存在：

1. Replay Artifacts 不只看收益，也要能回溯“这次判断是谁做的”。
2. 当你比较不同窗口或不同 report 时，模型配置往往是最重要的上下文之一。

怎么解读：

1. 它是上下文变量，不是质量结论。
2. 只有在多个 report 同条件比较时，模型差异才适合被当作解释因素。

### 4.6 `headline_kpi`

含义：

1. 报告级基础绩效摘要，包括 `initial_capital`、`final_value`、`total_return_pct`、`sharpe_ratio`、`sortino_ratio`、`max_drawdown_pct`、`executed_trade_days`、`total_executed_orders` 等。

为什么存在：

1. 用户在进入日级细节前，需要知道这次运行总体上发生了什么。
2. 这组指标的作用是给 report 定位，不是替代日级诊断。

怎么解读：

1. `total_return_pct` 告诉你最终收益方向，但不告诉你收益是怎么来的。
2. `executed_trade_days` 和 `total_executed_orders` 可以帮助你区分“几乎没部署”与“有持续部署但质量一般”。
3. `max_drawdown_pct` 和 `max_drawdown_date` 有助于把后续 blocker、reentry、sell signals 放回到风险背景里理解。

不要误解为：

1. `headline_kpi` 好，就说明选股层没有问题。
2. `headline_kpi` 差，就一定是 Layer B 或 Layer C 的逻辑错了。

### 4.7 `deployment_funnel_runtime`

含义：

1. 报告级的部署、漏斗、运行耗时摘要。
2. 常见字段包括平均资金利用率、`avg_layer_b_count`、`avg_watchlist_count`、`avg_buy_order_count`、`top_buy_blockers`、`top_watchlist_blockers`、`avg_total_day_seconds`、`avg_post_market_seconds`。

为什么存在：

1. 它把“这次 run 为什么表现成这样”往前推进一步。
2. KPI 只告诉你结果；funnel 与 runtime 才告诉你结构是否健康。

怎么解读：

1. `avg_layer_b_count` 很大但 `avg_watchlist_count` 很小，通常说明筛选阈值或 Layer C 否决很强。
2. `avg_watchlist_count` 还行但 `avg_buy_order_count` 很小，通常说明执行层约束在起主要作用。
3. `top_buy_blockers` 是全窗口层面的主阻塞原因摘要，不是单只票的最终裁决。

### 4.8 `artifacts`

含义：

1. 这次 report 已产出的文件索引，例如 `session_summary.json`、`window_review.md`、`data_cache_benchmark_json` 等。

为什么存在：

1. 页面不是直接扫整个目录，而是需要知道哪些产物已经存在。

怎么解读：

1. 它回答的是“证据是否在”，不是“证据说明什么”。

---

## 5. Selection Artifact 总览术语

这一层回答的是：这份 report 是否具备可复核的日级选股产物，以及这些产物的覆盖范围和健康度如何。

### 5.1 `selection_artifact_overview.available`

含义：

1. 当前 report 是否存在完整或可用的 selection artifact 根目录。

为什么存在：

1. 不是所有 replay 都生成了日级 snapshot / review / feedback 产物。
2. 如果没有这个标志，用户很容易误以为页面“数据丢了”，实际上只是这次运行本来没有产出选股复核证据。

怎么解读：

1. `true` 说明这份 report 适合进入选股复核工作流。
2. `false` 说明它更适合看 report 级摘要，不适合看日级选股细节。

### 5.2 `artifact_root`

含义：

1. 这份 report 的 selection artifact 根目录。

为什么存在：

1. 便于从接口层和页面层回溯到底层产物位置。

怎么解读：

1. 这是证据位置，不是业务结论。
2. 主要用于定位、排查和人工核对。

### 5.3 `trade_date_count`

含义：

1. 当前 report 中可供切换查看的交易日数量。

为什么存在：

1. 它直接告诉你这份 report 的日级复核覆盖面有多大。

怎么解读：

1. 较小的 `trade_date_count` 更适合做单样本学习。
2. 较大的 `trade_date_count` 更适合做频率统计、重复 blocker 观察和 feedback workflow 负载评估。

### 5.4 `available_trade_dates`

含义：

1. 当前 report 中实际存在 `selection_snapshot.json` 的交易日列表。

为什么存在：

1. 日级分析的真正入口不是 ticker，而是 `trade_date`。

### 5.5 `write_status_counts`

含义：

1. 各交易日 selection artifacts 写入状态的聚合计数，例如 `success`、`failed`、`skipped`。

为什么存在：

1. 用户需要区分“没有样本”与“样本本来该有，但写入失败”。

怎么解读：

1. `success` 多，说明该 report 的日级产物完整度高。
2. `failed` 或 `skipped` 出现时，优先把它当成产物生成健康度问题，而不是研究结论问题。

### 5.6 `blocker_counts`

含义：

1. 从各交易日 `selected` 候选的 `execution_bridge.block_reason` 聚合出来的窗口级 blocker 计数。

为什么存在：

1. 用户经常不是想看某一只票为什么没买，而是想知道“这份报告整体最常被什么拦住”。

怎么解读：

1. 它适合做窗口级归因。
2. 它不应该代替单日、单票的 blocker 细读。

### 5.7 `feedback_summary`

含义：

1. 该 report 下人工研究反馈的总体摘要。

为什么存在：

1. Replay Artifacts 不是只读页面，它还承担研究结论沉淀。
2. `feedback_summary` 可以让你快速判断这份 report 是否已经被真实复核过。

怎么解读：

1. 没有 `feedback_summary`，不代表 report 没价值，只代表还没被人工沉淀。
2. 有 `feedback_summary`，说明这份 report 已经从“系统产物”变成“研究资产”。

---

## 6. Trade Date 与 Selection Artifact 文件术语

这一层回答的是：某个交易日到底留下了哪些证据，以及这些证据各自负责解释什么。

### 6.1 `trade_date`

含义：

1. 某个交易日的唯一标识。

为什么存在：

1. 同一只股票在不同日期的状态可能完全不同。
2. Replay Artifacts 的最小分析单位不是“股票长期画像”，而是“某一天这只股票的状态”。

### 6.2 `selection_snapshot.json`

含义：

1. 该交易日最核心的结构化快照。

为什么存在：

1. 页面中的大部分表格和 drilldown 都来自这份文件。
2. 它保存的是机器可读事实，不是为了写给人看的结论。

你应该把它理解为：

1. 这是“当日结构化证据底稿”。

### 6.3 `selection_review.md`

含义：

1. 该交易日的人类可读审查 Markdown。

为什么存在：

1. 有些信息适合结构化表格看，有些适合文字叙述看。
2. `selection_review.md` 负责降低阅读门槛，让人快速形成整体感知。

你应该把它理解为：

1. 这是“给人看的解释层”，不是底层事实主源。

### 6.4 `research_feedback.jsonl`

含义：

1. 某日人工反馈记录的追加式日志文件。

为什么存在：

1. 研究结论需要可追加、可回读、可聚合。
2. JSONL 让每一条反馈都保留时间顺序和独立上下文。

你应该把它理解为：

1. 这是“研究判断的历史账本”。

---

## 7. Selection Snapshot 顶层术语

这一层回答的是：在某个交易日，系统总体筛出了什么、留下了什么、当前快照属于什么配置背景。

### 7.1 `artifact_version`

含义：

1. 当前 snapshot 的产物版本号。

为什么存在：

1. 后续字段演进时，需要知道这份快照符合哪一版结构。

### 7.2 `run_id`

含义：

1. 该交易日所属运行的内部标识。

为什么存在：

1. 某天的 snapshot 必须能回挂到某次完整运行。

### 7.3 `experiment_id`

含义：

1. 可选的实验标识，用于实验性运行或特殊验证场景。

### 7.4 `market`

含义：

1. 当前市场区域，例如 `CN`。

为什么存在：

1. 不同市场环境下，价格、流动性、仓位和交易限制解释口径不同。

### 7.5 `decision_timestamp`

含义：

1. 系统形成该日决策快照的时间戳。

为什么存在：

1. 帮助区分“交易日”和“决策形成时间”。

### 7.6 `data_available_until`

含义：

1. 本次决策所依赖数据的可用截止时间。

为什么存在：

1. 防止用户误以为系统使用了当天收盘后尚未可用的数据。
2. 这个字段本质上是数据边界声明。

### 7.7 `pipeline_config_snapshot`

含义：

1. 该交易日决策时的关键配置快照。

常见内容：

1. `execution_version`
2. `analyst_roster_version`
3. `selected_analysts`
4. `model_provider`
5. `model_name`
6. `key_thresholds`
7. `environment.replay_mode`

为什么存在：

1. 选股结果不只取决于市场数据，还取决于当时跑的到底是哪套配置。

怎么解读：

1. 它不是为了让你去“手调参数”，而是为了让你知道这份证据形成时的前提条件。

### 7.8 `universe_summary`

含义：

1. 当日候选池从输入到最终 buy order 的数量概览。

常见字段：

1. `input_symbol_count`
2. `candidate_count`
3. `high_pool_count`
4. `watchlist_count`
5. `buy_order_count`
6. `sell_order_count`

为什么存在：

1. 在你看 individual candidate 之前，先知道当天整体筛选密度和承接程度。

怎么解读：

1. `high_pool_count` 较大而 `watchlist_count` 很小，意味着筛选很严格。
2. `watchlist_count` 不小但 `buy_order_count` 很低，意味着执行约束更紧。

---

## 8. Candidate 层术语：`selected`、`rejected`、`buy_orders`

这一层是最容易被误读的，因为很多人会下意识把它们理解成“买不买”，但系统实际是在区分多个层级。

### 8.1 `selected`

含义：

1. 当日进入研究高优候选集合的股票列表。

为什么存在：

1. 系统需要显式记录“哪些股票通过了研究层的重要门槛”。
2. 这让用户能把“值得研究”与“真的下单”分开。

怎么解读：

1. `selected` 更接近 watchlist 语义，而不是最终下单语义。
2. 进入 `selected` 说明它值得被认真复核，但不代表一定进入执行层。

最常见误解：

1. 把 `selected` 理解为“系统决定买入”。

正确理解：

1. `selected` 是研究通过，不是执行完成。

### 8.2 `rejected`

含义：

1. 当日被挡在更高层级之前的候选集合，当前主要用于 near-miss 诊断。

为什么存在：

1. 如果系统只记录“最终选中了谁”，你永远无法知道阈值是不是把好票误伤了。

怎么解读：

1. `rejected` 不是垃圾桶，而是最重要的阈值诊断区。
2. 这里经常能发现 `threshold_false_negative` 类型样本。

### 8.3 `buy_orders`

含义：

1. 研究高优候选进一步通过执行与仓位约束后，形成的待执行买单计划。

为什么存在：

1. 系统需要把“值得关注”与“可以部署”拆开。

怎么解读：

1. `buy_orders` 是执行层可承接的结果。
2. 它比 `selected` 更接近“系统准备怎么动手”，但也不等于真实成交。

最常见误解：

1. 把 `buy_orders` 理解为“已经成交的订单”。

正确理解：

1. `buy_orders` 是执行计划，不是交易结果本身。

---

## 9. 评分与研究逻辑术语

这一层回答的是：系统为什么把某只股票放进 `selected`，以及这个决定的把握度如何。

### 9.1 `score_b`

含义：

1. Layer B 选股层的综合分数。

为什么存在：

1. Layer B 负责更偏策略与规则面的候选判断。
2. 它提供第一层可解释的“为什么值得继续看”。

怎么解读：

1. `score_b` 高，说明这只票在基础选股逻辑上表现较强。
2. 但这并不保证它会进入 watchlist 或 buy order。

### 9.2 `score_c`

含义：

1. Layer C 多 Agent 共识整合后的分数。

为什么存在：

1. Layer C 负责把多位 analyst / investor agent 的观点整合进研究层判断。

怎么解读：

1. `score_c` 偏正，说明多 Agent 共识更偏支持。
2. `score_c` 偏负，说明存在分歧、保留或显著反对。

### 9.3 `score_final`

含义：

1. 综合 Layer B 与 Layer C 后的最终分数。

为什么存在：

1. 系统最终需要一个统一排序与阈值比较的分数。

怎么解读：

1. 这是 Candidate 层最重要的排序分。
2. 它更适合做同日候选比较，而不是跨窗口、跨市场、跨模式做绝对值崇拜。

最常见误解：

1. 把 `score_final=0.21` 理解为“质量一定比 0.20 高很多”。

正确理解：

1. `score_final` 更像排序与阈值工具，而不是精确到小数点后四位的投资真理。

### 9.4 `rank_in_watchlist`

含义：

1. 某只股票在当日 watchlist 中的排序位置。

为什么存在：

1. 即便同样进入 `selected`，不同候选的优先级仍然不同。

怎么解读：

1. 排名越靠前，说明它在研究层相对更优先。
2. 但这仍然不保证执行层最终承接比例更高。

### 9.5 `decision`

含义：

1. 候选的当前决策标签，例如 `watchlist` 或 `avoid`。

为什么存在：

1. 分数之外，系统还需要保留一个离散决策信号。

### 9.6 `layer_b_summary`

含义：

1. Layer B 解释摘要，常包含 `top_factors`、来源、回退情况等。

为什么存在：

1. 分数只说明强弱，不说明为什么强。
2. `layer_b_summary` 负责把底层策略因子提升到人能读懂的层面。

怎么解读：

1. `top_factors` 适合回答“它为什么被挑出来”。
2. 如果出现 `fallback_used`，要意识到这份解释可能来自兼容路径，而不是最原生信号。

### 9.7 `layer_c_summary`

含义：

1. Layer C 多 Agent 共识摘要。

常见内容：

1. `active_agent_count`
2. `positive_agent_count`
3. `negative_agent_count`
4. `neutral_agent_count`
5. `cohort_contributions`
6. `top_positive_agents`
7. `top_negative_agents`
8. `bc_conflict`

为什么存在：

1. 你需要知道系统不是“单分数黑箱”，而是多 Agent 共同作用的结果。

怎么解读：

1. `positive_agent_count` 和 `negative_agent_count` 帮助你判断共识强弱。
2. `cohort_contributions` 能帮助区分是 investor 视角在主导，还是 analyst 视角在主导。
3. `top_positive_agents` / `top_negative_agents` 有助于识别主支持者和主反对者。

### 9.8 `bc_conflict`

含义：

1. Layer B 与 Layer C 之间是否存在明显冲突信号。

为什么存在：

1. 某些候选的基础选股逻辑不错，但多 Agent 共识不买账，或者反过来。

怎么解读：

1. 它通常是一个“需要二次判断”的提醒，而不是立即否定该票。

---

## 10. Execution Bridge 术语

这一层回答的是：这只股票在研究层看起来不错，但执行层到底能不能接住，以及没接住时具体卡在哪。

### 10.1 为什么 `execution_bridge` 是最关键的区域

因为它直接解决一个高频误判：

1. “这只票没买，所以系统不会选股。”

实际上，很多样本不是“不会选”，而是“选出来了，但执行层根据再入场、仓位、流动性或日内约束没有承接”。

`execution_bridge` 就是用来拆开这两个问题的。

### 10.2 `included_in_buy_orders`

含义：

1. 该候选是否真正进入了 `buy_orders`。

为什么存在：

1. 它是研究层与执行层之间最直接的分界线。

怎么解读：

1. `true` 表示该票不仅值得研究，而且已通过当前执行约束。
2. `false` 表示研究层认可，但执行层未承接。

### 10.3 `planned_shares` / `planned_amount`

含义：

1. 该票在执行计划中的预计股数和金额。

为什么存在：

1. 执行层不是只有“买 / 不买”，还包括“买多少”。

怎么解读：

1. 即便进入 `buy_orders`，规模也可能很保守。
2. 金额很小往往意味着执行层虽然没完全否定，但信心或约束条件并不支持大仓位。

### 10.4 `target_weight`

含义：

1. 该票预计占组合净值的目标权重。

为什么存在：

1. 这帮助你从金额提升到仓位语义理解。

### 10.5 `block_reason`

含义：

1. 候选未进入 `buy_orders` 时的主要阻塞原因。

为什么存在：

1. 如果没有这个字段，用户只能看到“没买”，却不知道是再入场确认、冷静期、仓位约束还是其他执行规则导致。

怎么解读：

1. 它回答的是“为什么没进执行层”。
2. 它不是对研究质量的道德评判。

最常见的几类 blocker：

1. `blocked_by_reentry_score_confirmation`
   表示再入场确认期内，当前分数还没高到足以解除限制。
2. `blocked_by_exit_cooldown`
   表示刚经历退出后仍在冷静期内。
3. `position_blocked_*`
   表示仓位、流动性、单票或组合约束在起作用。
4. `filtered_by_daily_trade_limit`
   表示日度交易数量限制把它挡掉了。

### 10.6 `constraint_binding`

含义：

1. 触发阻塞时，当前真正绑定住该票的约束名称。

为什么存在：

1. 一个 blocker 常常不只是“没过”，还需要知道是哪个具体约束最先咬住了这只票。

### 10.7 `execution_ratio`

含义：

1. 在执行层估算中，该票最终能按多大比例承接。

为什么存在：

1. 有些票不是完全不能买，而是只能按较低比例配置。

怎么解读：

1. 比例很低时，说明系统虽然愿意保留该票，但并不愿意给足配置。

### 10.8 `blocked_until`

含义：

1. 当前完全阻塞期的截止日期。

为什么存在：

1. 用户需要知道这是暂时拦住，还是已经解除。

### 10.9 `reentry_review_until`

含义：

1. 再入场确认窗口的截止日期。

为什么存在：

1. 某些股票退出后不会立刻允许再入场，需要观察一段时间并满足更高确认标准。

怎么解读：

1. 在这个日期前，系统对该票会更苛刻。
2. 这通常意味着“不是永远否定”，而是“还没到重新信任的时候”。

### 10.10 `exit_trade_date` / `trigger_reason`

含义：

1. 上次退出发生在哪个交易日，以及是由什么原因触发。

为什么存在：

1. 再入场 blocker 只有放回上次退出背景里才有意义。

怎么解读：

1. 如果上次是强风控触发退出，那么当前的 reentry 审查更像保护性机制，而不是系统失误。

---

## 11. Rejected / Near-Miss 术语

这一层回答的是：哪些股票差一点就进来了，以及它们究竟是“应该被挡住”，还是“可能被阈值误伤”。

### 11.1 `rejection_stage`

含义：

1. 该候选被挡在哪一层，例如当前常见是 `watchlist`。

为什么存在：

1. 近似落选样本不只是“没选上”，而是“在哪一步被挡掉”。

### 11.2 `rejection_reason_codes`

含义：

1. 结构化拒绝原因列表。

常见示例：

1. `score_final_below_watchlist_threshold`
2. `decision_avoid`

为什么存在：

1. 用户需要把“差一点没过线”和“被明确否决”区别开来。

怎么解读：

1. 如果主要原因是 `score_final_below_watchlist_threshold`，它更像阈值边界问题。
2. 如果是 `decision_avoid`，则更像研究逻辑层明确不认同。

### 11.3 `rejection_reason_text`

含义：

1. 更人类可读的拒绝说明。

为什么存在：

1. 代码值适合统计，文字说明适合阅读。

### 11.4 `threshold_false_negative`

含义：

1. 这是人工反馈标签，不是 snapshot 原生评分字段。
2. 它表示“系统阈值可能误伤了一只本该进入更高层级的候选”。

为什么要特别强调：

1. 很多用户会把所有 near-miss 都贴上这个标签，这是错误的。

正确使用条件：

1. 它必须真的是“差一点被挡住”，而不是“逻辑本来就弱”。

---

## 12. Funnel Diagnostics 术语

这一层回答的是：候选池在哪一层大量流失，以及主要被什么原因过滤。

### 12.1 `funnel_diagnostics`

含义：

1. 从筛选漏斗视角组织的诊断结构。

为什么存在：

1. 单看 selected / rejected 只能看到结果样本。
2. 真正要定位系统问题，必须知道大多数候选是卡在 Layer B、watchlist，还是 buy_orders。

### 12.2 `filters`

含义：

1. 各层过滤结果的主容器，常见有 `layer_b`、`watchlist`、`buy_orders`、`sell_orders`。

为什么存在：

1. 它把“每层留下了谁、挡住了谁、主要原因是什么”收拢到一个统一结构中。

### 12.3 `layer_b`

含义：

1. 第一轮高池候选层的过滤摘要。

你应该怎么理解：

1. 这层更像“策略层高潜候选池”。
2. 通过这层不代表最终会进入研究高优区。

### 12.4 `watchlist`

含义：

1. 从 Layer B 进一步进入研究高优列表的过滤层。

为什么它重要：

1. 这是最能体现“阈值是不是太严、Layer C 共识是不是太苛刻”的层级。

### 12.5 `buy_orders`

含义：

1. 从 watchlist 进一步进入可执行买单计划的过滤层。

为什么它重要：

1. 这层最能体现“系统会选，但执行不接”的现象。

### 12.6 `filtered_count`

含义：

1. 当前层被过滤掉的数量或该层诊断统计的样本数。

为什么存在：

1. 用于让你快速判断“卡点密度”在哪。

### 12.7 `reason_counts`

含义：

1. 当前层按原因聚合后的计数。

为什么存在：

1. 它是最适合看整体趋势的字段之一。

怎么解读：

1. `reason_counts` 适合用来找“窗口里最常见的卡点”。
2. 它不适合替代 individual candidate 级别的详细判断。

### 12.8 `selected_tickers` / `selected_entries`

含义：

1. 当前层最终通过的样本集合或样本详情。

为什么存在：

1. 过滤诊断除了说明谁被挡掉，也要说明谁留下来了。

### 12.9 `blocked_buy_tickers`

含义：

1. 在 buy order 层被阻塞的 ticker 级详情映射。

为什么存在：

1. 这是 `execution_bridge` 生成的重要来源之一。

怎么解读：

1. 当你想知道某只票为何被 reentry 或 cooldown 卡住时，这是底层结构化证据之一。

最常见误解：

1. 把 Funnel Drilldown 看成“系统配置面板”。

正确理解：

1. 它是诊断镜子，不是配置面板。

---

## 13. Research Prompts 与 Review 文本术语

这一层回答的是：系统希望研究员重点验证什么，而不是只丢给你一个分数。

### 13.1 `research_prompts`

含义：

1. 给研究员的结构化复核提示。

常见子字段：

1. `why_selected`
2. `what_to_check`

为什么存在：

1. Replay Artifacts 的目标不是只展示结果，而是帮助人工研究形成下一步动作。

怎么解读：

1. `why_selected` 告诉你系统当前相信什么。
2. `what_to_check` 告诉你人工最该怀疑什么。

### 13.2 `why_selected`

含义：

1. 系统认为这只票值得进入研究视野的核心理由。

### 13.3 `what_to_check`

含义：

1. 系统建议人工重点验证的风险点、冲突点或 blocker。

为什么重要：

1. 高水平复核不是重复机器结论，而是针对机器最可能看错的地方做确认。

---

## 14. 人工反馈术语

这一层回答的是：研究员怎么看待这条样本，以及这个判断目前处于什么阶段。

### 14.1 `review_scope`

含义：

1. 这条反馈到底在评什么层级的对象，例如 `watchlist`、`near_miss`。

为什么存在：

1. 同一只股票可能同时出现在不同分析语义里。
2. 不写清 scope，反馈很容易混淆。

### 14.2 `reviewer`

含义：

1. 当前反馈记录的提交人。

为什么存在：

1. 多人协作时，需要知道结论来自谁。

### 14.3 `review_status`

含义：

1. 这条反馈当前处于什么评审阶段。

允许值：

1. `draft`
2. `final`
3. `adjudicated`

为什么存在：

1. 团队需要知道哪些是临时判断，哪些已经稳定，哪些已经裁决完成。

怎么解读：

1. `draft` 表示初步判断。
2. `final` 表示本轮复核已形成稳定结论。
3. `adjudicated` 表示争议或复核流程已经完成裁决。

最常见误解：

1. 把 `review_status` 理解成看多、看空或标签强弱。

正确理解：

1. 它是流程状态，不是投资立场。

### 14.4 `primary_tag`

含义：

1. 这条反馈的主结论标签。

当前受控值：

1. `high_quality_selection`
2. `thesis_clear`
3. `crowded_trade_risk`
4. `weak_edge`
5. `threshold_false_negative`
6. `event_noise_suspected`

为什么存在：

1. 需要一个能稳定聚合和统计的主结论字段。

怎么解读：

1. 一条反馈只能有一个主标签。
2. 它应该回答“这条样本最核心的判断是什么”。

### 14.5 `tags`

含义：

1. 补充标签集合。

为什么存在：

1. 一只票经常不止一个特点，但主结论必须唯一。

怎么解读：

1. `tags` 用来补充，不用来推翻 `primary_tag`。

### 14.6 `confidence`

含义：

1. 研究员对这条判断的主观置信度，范围为 0 到 1。

为什么存在：

1. 两条同样是 `weak_edge` 的记录，确定性可能完全不同。

### 14.7 `research_verdict`

含义：

1. 对当前判断的短语化、自然语言结论。

为什么存在：

1. 受控标签粒度有限，无法覆盖所有语义。

怎么解读：

1. 它用来补足表达，不用来替代主标签。

### 14.8 `notes`

含义：

1. 研究员对该条样本的自由文本补充说明。

为什么存在：

1. 系统需要保留上下文、例外情况和具体证据，而不是只保留分类结果。

### 14.9 `created_at`

含义：

1. 这条反馈创建的时间。

为什么存在：

1. 反馈记录按时间顺序回看时，它是最基础的排序字段。

---

## 15. 反馈聚合与 Activity 术语

这一层回答的是：一组反馈整体呈现出什么状态，以及最近谁在动哪些样本。

### 15.1 `feedback_count`

含义：

1. 当前范围内反馈记录的总数。

### 15.2 `final_feedback_count`

含义：

1. 其中已经推进到 `final` 的反馈数量。

为什么存在：

1. 它能快速区分“只是有人看过”与“已经形成稳定结论”。

### 15.3 `symbols`

含义：

1. 当前反馈覆盖的股票集合。

### 15.4 `reviewers`

含义：

1. 当前反馈涉及的复核人员集合。

### 15.5 `primary_tag_counts` / `tag_counts`

含义：

1. 主标签与补充标签的聚合计数。

为什么存在：

1. 帮助团队判断当前样本群最常见的问题类型或正面特征类型。

### 15.6 `review_status_counts`

含义：

1. 不同评审阶段的数量分布。

为什么存在：

1. 它更像“工作推进度”指标，而不是质量指标。

### 15.7 `latest_created_at`

含义：

1. 当前范围内最新一条反馈产生的时间。

为什么存在：

1. 帮助判断这份 report 是不是还在被活跃使用。

### 15.8 `recent activity`

含义：

1. 最近反馈活动的时间序视图，通常按 `created_at` 倒序展示。

为什么存在：

1. 研究员需要快速回看最近改过什么，而不是重新翻所有 JSONL。

---

## 16. Workflow Queue 术语

这一层回答的是：一条反馈记录在团队协作流里当前处于什么状态，以及谁应该跟进它。

### 16.1 `workflow_status`

含义：

1. 样本在 workflow queue 中的当前状态。

常见值：

1. `unassigned`
2. `assigned`
3. `in_review`
4. `ready_for_adjudication`
5. `closed`

为什么存在：

1. `review_status` 只能描述单条反馈记录的阶段。
2. `workflow_status` 则描述团队后续动作该怎么接。

怎么解读：

1. `unassigned` 说明还没人领。
2. `assigned` 说明已有人负责。
3. `ready_for_adjudication` 说明样本已经有足够稳定的信息，适合进入裁决或更高层复核。
4. `closed` 说明这个样本的协作流已经收口。

### 16.2 `assignee`

含义：

1. 当前样本的负责人。

### 16.3 `latest_review_status`

含义：

1. 该 workflow item 对应最新一条反馈的 `review_status`。

为什么存在：

1. queue 要基于“最新事实”来更新自身状态。

### 16.4 `latest_primary_tag` / `latest_tags` / `latest_research_verdict`

含义：

1. workflow item 当前最新反馈结论的镜像摘要。

为什么存在：

1. 你在 queue 里不需要每次都打开整份反馈明细，也能知道当前主结论。

最常见误解：

1. 认为 `ready_for_adjudication` 表示系统建议买入。

正确理解：

1. 它表示流程成熟度，不表示投资方向。

---

## 17. Cache Benchmark 与运行证据术语

这一层回答的是：这份 report 的数据缓存复用证据是否完整、是否成功，以及能否说明该运行的缓存路径真的被验证过。

### 17.1 `data_cache_benchmark`

含义：

1. 与当前 report 关联的数据缓存复用基准测试原始摘要。

为什么存在：

1. 系统不仅要会分析，也要知道这次运行的数据路径是否高效、是否复用成功。

### 17.2 `data_cache_benchmark_status`

含义：

1. benchmark 子流程的状态信息，例如是否请求、是否执行、写入状态和失败原因。

### 17.3 `cache_benchmark_overview`

含义：

1. 页面用于直接展示的 cache benchmark 摘要。

常见字段：

1. `requested`
2. `executed`
3. `write_status`
4. `reason`
5. `ticker`
6. `trade_date`
7. `reuse_confirmed`
8. `disk_hit_gain`
9. `miss_reduction`
10. `set_reduction`
11. `first_hit_rate`
12. `second_hit_rate`

为什么存在：

1. 用户不应为了看缓存复用结果再去翻原始 JSON 和 Markdown。

### 17.4 `requested` / `executed`

含义：

1. 这次 report 是否请求了 cache benchmark，以及是否真的执行了。

怎么解读：

1. `requested=true` 但 `executed=false` 说明它本来想跑，但没有实际完成。

### 17.5 `write_status`

含义：

1. benchmark 产物写入状态，常见有 `success`、`failed`、`skipped`。

为什么存在：

1. 它帮助区分 benchmark 没请求、请求了但失败、还是正常完成。

### 17.6 `reason`

含义：

1. benchmark 未成功时的主要原因说明。

### 17.7 `reuse_confirmed`

含义：

1. 是否确认这次 benchmark 的复用路径成立。

为什么存在：

1. 页面需要一个清晰的“是否复用成功”结论，而不是逼用户手算 hit rate 变化。

最常见误解：

1. `reuse_confirmed=true` 就表示这份 report 的所有数据路径都完美复用。

正确理解：

1. 它证明这次 benchmark 所覆盖的路径复用成立，不是对所有未来条件的永久担保。

### 17.8 `disk_hit_gain`

含义：

1. 由于缓存命中提升所带来的磁盘命中收益。

为什么存在：

1. 让“缓存更好”从抽象说法变成一个可感知的收益量。

### 17.9 `first_hit_rate` / `second_hit_rate`

含义：

1. 第一次与第二次运行时的缓存命中率。

怎么解读：

1. 第一轮低、第二轮高是正常 benchmark 预期。
2. 第二轮仍然很低，通常说明复用链路没有真正建立起来。

### 17.10 `artifacts.data_cache_benchmark_*`

含义：

1. benchmark 生成的 JSON、Markdown 和追加报告等文件路径索引。

为什么存在：

1. 页面展示的是摘要，但用户需要时仍可定位原始证据。

---

## 18. 最容易误解的 12 个术语

### 18.1 `selected`

常见误解：

1. 已入选就等于系统决定买入。

正确理解：

1. 它代表研究层高优候选，不代表执行完成。

### 18.2 `buy_orders`

常见误解：

1. 已经成交的订单。

正确理解：

1. 它是执行计划，不是实际成交记录。

### 18.3 `block_reason`

常见误解：

1. 只要有 blocker，就说明选股逻辑错了。

正确理解：

1. 它说明执行层当前不承接，不必然否定研究层判断。

### 18.4 `score_final`

常见误解：

1. 这是一个跨报告可直接横向比较的绝对质量指数。

正确理解：

1. 它更适合同日排序和阈值比较。

### 18.5 `watchlist`

常见误解：

1. watchlist 就是今天要买的名单。

正确理解：

1. 它是值得研究和继续观察的高优候选层。

### 18.6 `rejected`

常见误解：

1. 被拒绝的票没有研究价值。

正确理解：

1. near-miss 样本恰恰是诊断阈值与误伤的关键区域。

### 18.7 `review_status`

常见误解：

1. `draft` 说明这条反馈质量低。

正确理解：

1. 它只说明工作流阶段。

### 18.8 `primary_tag`

常见误解：

1. 可以随便多选几个，越全面越好。

正确理解：

1. 主标签必须唯一，用来表达主结论。

### 18.9 `ready_for_adjudication`

常见误解：

1. 这是系统建议加仓或建议执行。

正确理解：

1. 它只是说明样本在流程上已准备好进入裁决。

### 18.10 `funnel_diagnostics`

常见误解：

1. 这是系统正式策略配置页。

正确理解：

1. 它是结构化诊断视图。

### 18.11 `reuse_confirmed`

常见误解：

1. 这意味着以后所有运行都会自动命中缓存。

正确理解：

1. 它只证明当前 benchmark 条件下复用成立。

### 18.12 `selection_artifact_overview.available`

常见误解：

1. `false` 说明系统坏了或页面没读到数据。

正确理解：

1. 很多时候只是这份 report 本来没有生成日级选股产物。

---

## 19. 实际使用时，应该怎么用这些术语解读报告

### 19.1 如果你想判断“系统会不会选股”

优先看：

1. `selected`
2. `score_final`
3. `layer_b_summary`
4. `layer_c_summary`
5. `research_prompts.why_selected`

为什么这样看：

1. 这些字段回答的是研究层逻辑是否成立，而不是执行层是否允许下单。

### 19.2 如果你想判断“为什么选中了却没买”

优先看：

1. `execution_bridge.included_in_buy_orders`
2. `execution_bridge.block_reason`
3. `execution_bridge.reentry_review_until`
4. `execution_bridge.trigger_reason`
5. `funnel_diagnostics.filters.buy_orders`

为什么这样看：

1. 这组字段能把研究层与执行层剥离开。

### 19.3 如果你想判断“是不是阈值过严”

优先看：

1. `rejected`
2. `rejection_reason_codes`
3. `funnel_diagnostics.filters.watchlist.reason_counts`
4. `threshold_false_negative` 类反馈标签

为什么这样看：

1. 真正的阈值问题往往集中体现在 near-miss 与 watchlist 层的过滤原因上。

### 19.4 如果你想判断“团队是否已经复核过这份报告”

优先看：

1. `feedback_summary`
2. `final_feedback_count`
3. `recent activity`
4. `workflow_status`

为什么这样看：

1. 一份 report 只有被反馈和流转过，才真正进入团队知识沉淀链路。

### 19.5 如果你想判断“这份报告的运行证据是否扎实”

优先看：

1. `selection_artifact_overview.available`
2. `write_status_counts`
3. `cache_benchmark_overview`
4. `artifacts`

为什么这样看：

1. 这些字段回答的是“证据有没有、产物全不全、缓存复用验证过没有”。

---

## 20. 一张最实用的阅读决策表

### 20.1 想回答什么问题，就先看什么字段

| 你要回答的问题 | 先看哪些术语 | 再看哪些术语 |
| --- | --- | --- |
| 这份 report 值不值得复核 | `selection_artifact_overview.available`、`trade_date_count` | `feedback_summary`、`cache_benchmark_overview` |
| 这天系统选了谁 | `selected`、`score_final` | `layer_b_summary`、`layer_c_summary` |
| 为什么没买 | `included_in_buy_orders`、`block_reason` | `reentry_review_until`、`constraint_binding` |
| 是阈值问题还是逻辑问题 | `rejected`、`rejection_reason_codes` | `funnel_diagnostics.watchlist.reason_counts` |
| 当前反馈推进到哪里了 | `review_status`、`final_feedback_count` | `workflow_status`、`assignee` |
| 缓存复用是否真实成立 | `reuse_confirmed`、`write_status` | `disk_hit_gain`、`first_hit_rate`、`second_hit_rate` |

---

### 20.2 30 秒术语速查矩阵

如果你正在页面里看 report，不想重新读整篇手册，可以先用这张速查矩阵定位术语。

| 术语 | 它回答的问题 | 先把它理解成什么 | 最容易误判成什么 |
| --- | --- | --- | --- |
| `selection_artifact_overview.available` | 这份 report 能不能做日级复核 | 日级证据是否存在 | 页面是否坏了 |
| `trade_date` | 你现在在看哪一天 | 当日决策切片 | 某只股票的长期结论 |
| `selected` | 系统重点挑了谁 | 研究高优候选 | 已决定买入 |
| `rejected` | 谁差一点就进来了 | near-miss 诊断区 | 没价值的淘汰池 |
| `buy_orders` | 执行层准备承接谁 | 待执行买单计划 | 已成交订单 |
| `score_final` | 这只票在当日综合排位如何 | 排序与阈值分 | 跨报告绝对质量分 |
| `execution_bridge` | 为什么选中了却没买 | 研究到执行的桥接解释 | 单纯的错误提示 |
| `block_reason` | 没进 buy_orders 的主因是什么 | 执行阻塞原因 | 选股失败判决 |
| `funnel_diagnostics` | 大多数候选卡在哪一层 | 漏斗诊断镜子 | 正式配置面板 |
| `review_status` | 当前反馈推进到哪一步 | 工作流阶段 | 看多看空标签 |
| `primary_tag` | 这条反馈的主结论是什么 | 受控主标签 | 可随意多选的备注 |
| `workflow_status` | 后续谁该跟进、跟到哪 | 团队协作状态 | 投资决策建议 |
| `reuse_confirmed` | 缓存复用是否在本次 benchmark 中成立 | 本次数据路径证据 | 永久保证以后都命中 |

### 20.3 四个真实样本怎么读

下面四个样本分别对应四类最常见阅读场景：

1. 样本 A：选中了，但执行层没接住。
2. 样本 B：原本只是边缘 watch，重放后跨过 watchlist 门槛。
3. 样本 C：反馈从 `draft` 推进到 `final` 后，为什么 workflow 会进入 `ready_for_adjudication`。
4. 样本 D：cache benchmark 为什么能证明“这次 report 的缓存复用证据是实的”。

#### 样本 A：300724 为什么入选但未买入

样本上下文：

1. report：`paper_trading_20260311_selection_artifact_blocker_validation_20260323`
2. trade_date：`2026-03-11`

应该按这个顺序读：

1. 先看 `universe_summary`
   你会看到 `high_pool_count = 1`、`watchlist_count = 1`、`buy_order_count = 0`。
   这一步已经说明：当天不是没筛到东西，而是筛到了 1 只重点候选，但没进入 buy order。
2. 再看 `selected`
   你会看到 `300724` 的 `score_final = 0.2144`，而且它确实出现在 selected 中。
   这一步说明：问题不在“有没有被选中”，而在“选中之后发生了什么”。
3. 再看 `execution_bridge`
   关键字段是：
   1. `included_in_buy_orders = false`
   2. `block_reason = blocked_by_reentry_score_confirmation`
   3. `reentry_review_until = 20260312`
   4. `trigger_reason = hard_stop_loss`
   读到这里，结论已经可以成立：这是执行层再入场确认阻塞，不是选股层完全失效。
4. 最后看 `funnel_diagnostics.filters.buy_orders`
   你会再次看到 `300724` 出现在 buy order 过滤层里，并带着同样的 blocker 原因。
   这一步的意义是用第二份证据验证同一结论，避免只凭 candidate 详情页做单点归因。

这个样本最应该记住的术语组合是：

1. `selected + included_in_buy_orders = false`
2. `block_reason + reentry_review_until + trigger_reason`
3. `funnel_diagnostics.filters.buy_orders`

这组组合共同回答：

1. 研究层通过了。
2. 执行层暂不承接。
3. 原因是再入场保护规则，而不是“系统不会选股”。

如果你要给这个样本写一句最短结论，可以写成：

1. `300724` 属于“研究通过但执行层因 reentry 确认而暂不承接”的 blocker 样本。

#### 样本 B：600519 为什么从边缘 watch 变成跨过 watchlist 门槛

样本上下文：

1. 文件：`data/reports/live_replay_600519_20260224_p1.json`
2. trade_date：`20260224`
3. ticker：`600519`

这个样本没有完整工作台带读那么长，但非常适合训练你理解 `score_b`、`score_c`、`score_final`、`decision` 与 watchlist 门槛之间的关系。

应该按这个顺序读：

1. 先看 `logged`
   你会看到：
   1. `score_b = 0.4023`
   2. `score_c = -0.0043`
   3. `score_final = 0.1584`
   4. `reasons = [score_final_below_watchlist_threshold]`
   这说明旧记录里的关键问题不是 Layer B 不行，而是最终综合分没有过 watchlist 门槛。
2. 再看 `replay`
   你会看到：
   1. `score_b = 0.4023`
   2. `score_c = -0.0122`
   3. `score_final = 0.2158`
   4. `decision = watch`
   这里最关键的变化是：虽然 `score_c` 仍然偏负，但 `score_final` 已经从 0.1584 提升到 0.2158。
3. 再看 `delta`
   你会看到 `score_final` 增量为 `0.0574`。
   这一步的意义不是崇拜精确小数，而是确认它是否足够跨过门槛。
4. 最后看解释结论
   该样本的摘要直接指出：它已经跨过 0.20 watchlist 门槛。

这个样本最应该记住的术语组合是：

1. `score_b`
2. `score_c`
3. `score_final`
4. `score_final_below_watchlist_threshold`
5. `delta.score_final`

这组组合共同回答：

1. Layer B 基础强度其实不弱。
2. 真正决定是否跨线的是最终综合分是否越过 watchlist 门槛。
3. 即便 `score_c` 没有变成大幅正数，只要综合权重变化足够，`score_final` 仍可能从“边缘不过线”进入“值得研究”。

如果你要给这个样本写一句最短结论，可以写成：

1. `600519` 属于“Layer B 基础不差、综合分提升后跨过 watchlist 门槛”的边缘转正样本。

#### 样本 C：为什么 `draft -> final` 之后会进入 `ready_for_adjudication`

样本上下文：

1. report：`paper_trading_window_20260316_20260323_live_m2_7_20260323`
2. trade_date：`2026-03-20`
3. symbol：`300724`
4. 证据来源：试用窗口总结与问题回填中记录的真实推进样本

这个样本不再回答“这只票好不好”，而是回答“团队流程现在推进到了哪一步”。

应该按这个顺序读：

1. 先看单条 feedback 的 `review_status`
   这个样本最开始是 `draft`，后来被同一轮真实复核推进为 `final`。
   这一步只回答一件事：当前这条判断是不是还在草稿阶段。
2. 再看 report 级或目录级 `feedback_summary`
   你会看到：
   1. `feedback_count` 表示总共有多少条反馈
   2. `final_feedback_count` 表示其中多少条已经稳定下来
   3. `review_status_counts` 会从偏 `draft` 的分布，变成出现 `final=1, draft=1` 这样的结构
   这一步回答的是：不是只有单条记录变了，而是整个 report 的反馈成熟度在变化。
3. 再看 workflow item 的 `latest_review_status`
   当最新反馈变成 `final` 后，对应 workflow item 的 `latest_review_status` 也会同步变成 `final`。
   这一步的意义是：workflow queue 不是自己凭空判断状态，而是跟随最新反馈事实演化。
4. 最后看 `workflow_status`
   在这个真实样本中，对应 workflow item 从 `unassigned` 自动切换成 `ready_for_adjudication`。
   这一步回答的是：团队层面已经不再把它视为“没人处理的草稿样本”，而是“已经形成稳定结论，适合进入下一层裁决或汇总”。

这个样本最应该记住的术语组合是：

1. `review_status`
2. `feedback_summary.final_feedback_count`
3. `feedback_summary.review_status_counts`
4. `latest_review_status`
5. `workflow_status = ready_for_adjudication`

这组组合共同回答：

1. 单条反馈已经从初步判断升级成稳定判断。
2. 这种升级已经被 report 级聚合统计捕获到。
3. queue 状态的变化是基于最新反馈事实自动推导出来的。
4. `ready_for_adjudication` 不是投资建议，而是流程成熟度信号。

这个样本最容易出现的误判是：

1. 看到 `ready_for_adjudication`，就以为系统建议立刻执行或加仓。

正确理解应该是：

1. 研究判断已经从草稿走到稳定阶段。
2. 这个样本在团队流程上值得进入更高层复核、周度汇总或裁决。
3. 它说的是“谁该接着处理”，不是“市场下一步一定怎么走”。

如果你要给这个样本写一句最短结论，可以写成：

1. `2026-03-20 / 300724` 属于“研究结论已稳定、流程上已准备进入裁决”的样本，而不是“系统建议执行”的样本。

#### 样本 D：cache benchmark 怎么证明这份 report 的缓存证据是实的

样本上下文：

1. report：`paper_trading_probe_20260205_cache_benchmark_20260325`
2. trade_date：`20260205`
3. ticker：`300724`

这个样本不回答“选股好不好”，而是回答“这份 report 里展示的缓存指标，到底是不是基于真实运行得出来的”。

应该按这个顺序读：

1. 先看 `data_cache_benchmark_status`
   关键字段是：
   1. `requested = true`
   2. `executed = true`
   3. `write_status = success`
   4. `reason = null`
   这一步先回答最基础的问题：这次 benchmark 不是页面空想出来的，而是被真实请求、真实执行并且成功写出了结果。
2. 再看 `data_cache_benchmark.summary`
   关键字段是：
   1. `first_disk_hits = 0`
   2. `second_disk_hits = 6`
   3. `first_misses = 6`
   4. `second_misses = 0`
   5. `disk_hit_gain = 6`
   6. `first_hit_rate = 0.0`
   7. `second_hit_rate = 1.0`
   8. `reuse_confirmed = true`
   这一步回答的是：第一次运行完全没命中缓存，第二次运行则把 6 次磁盘命中全部吃到了，说明缓存复用在这条路径上真实成立。
3. 最后看 report 页的 `cache_benchmark_overview`
   页面实际聚合展示的就是：
   1. 当前 benchmark 是否请求与执行成功
   2. `write_status` 是 `success` 还是 `failed` / `skipped`
   3. `reuse_confirmed` 是否为真
   4. `disk_hit_gain` 和 hit rate 有没有明显改善
   这一步的意义是：你不必再回到原始 JSON 才能判断“缓存证据站不站得住”。

这个样本最应该记住的术语组合是：

1. `requested + executed + write_status`
2. `first_hit_rate + second_hit_rate`
3. `disk_hit_gain`
4. `reuse_confirmed`

这组组合共同回答：

1. 这次 benchmark 是否真的跑了。
2. 跑完之后缓存命中是否显著改善。
3. 页面上显示的“复用成立”是不是有真实样本支撑。

这个样本最容易出现的误判是：

1. 看到 `reuse_confirmed = true`，就以为以后所有 report、所有 trade_date、所有 ticker 都会自动同样命中缓存。

正确理解应该是：

1. 它证明的是这一次 benchmark 所覆盖的数据路径，在当前条件下复用成立。
2. 它是“当前证据成立”，不是“未来永远保证”。
3. 所以 `reuse_confirmed` 应该读成“本次验证通过”，而不是“系统从此不再需要观察缓存质量”。

如果你要给这个样本写一句最短结论，可以写成：

1. `paper_trading_probe_20260205_cache_benchmark_20260325` 属于“cache benchmark 已真实执行且复用证据成立”的 report 级运行证据样本。

### 20.4 用样本反推阅读动作

如果你以后再看到陌生 report，可以直接套用下面这个动作模板：

1. 先问：这是 `selected` 没进 `buy_orders`，还是 `rejected` 差一点进 `watchlist`。
2. 如果是前者，就优先查 `execution_bridge` 和 `funnel_diagnostics.filters.buy_orders`。
3. 如果是后者，就优先查 `rejection_reason_codes`、`reason_counts` 和 `score_final` 是否贴着门槛。
4. 如果你看到的是反馈流转问题，就优先查 `review_status`、`final_feedback_count`、`review_status_counts`、`latest_review_status` 和 `workflow_status`。
5. 如果你看到的是缓存或运行证据问题，就优先查 `requested`、`executed`、`write_status`、`reuse_confirmed`、`disk_hit_gain` 与 hit rate 变化。
6. 如果你看到的是 report 级 summary，而不是日级 detail，就先用 `selection_artifact_overview`、`blocker_counts`、`feedback_summary` 和 `cache_benchmark_overview` 判断这份 report 值不值得继续深挖。

换句话说：

1. 先识别场景。
2. 再挑术语。
3. 最后才下结论。

这样读报告，基本不会把流程状态、执行阻塞和研究结论混成一团。

### 20.5 按问题类型反查字段

如果你不是从头读 report，而是已经带着一个具体问题来找答案，更高效的办法不是重新通读全文，而是先定位你遇到的是哪一类问题。

下面这张表可以直接当作“排障索引”使用。

| 你现在的问题 | 第一眼先看什么 | 第二步再看什么 | 这组术语真正回答什么 | 最常见误判 |
| --- | --- | --- | --- | --- |
| 这天为什么几乎没有候选 | `selection_artifact_overview` | `funnel_diagnostics.filters.layer_b`、`reason_counts` | 候选 scarcity 是不是在 Layer B 就被大量过滤掉 | 把“候选少”误判成模型没跑或 report 异常 |
| 这只票为什么进了 selected 却没下单 | `selected[*].execution_bridge` | `funnel_diagnostics.filters.buy_orders`、`block_reason`、`reentry_review_until` | 研究层是否通过，但执行层是否因为仓位、再入场或风控规则没有承接 | 把执行 blocker 误判成选股失败 |
| 这只票为什么差一点进 watchlist 但最终落选 | `rejected[*].rejection_reason_codes` | `score_final`、`reason_counts`、门槛相关 reason text | 它是彻底不行，还是只是贴着阈值线的 near-miss | 把 near-miss 和明显弱样本混为一类 |
| 这次 report 到底值不值得继续深挖 | `selection_artifact_overview` | `blocker_counts`、`feedback_summary`、`cache_benchmark_overview` | 这份 report 有没有可读样本、可复核活动和运行证据 | 只看单只股票就对整份 report 下结论 |
| 这条 feedback 目前是草稿还是稳定结论 | `review_status` | `final_feedback_count`、`review_status_counts` | 反馈是在探索中，还是已经沉淀成稳定判断 | 把一条 draft 笔记当成团队结论 |
| workflow queue 里的条目为什么会出现在这里 | `latest_review_status` | `workflow_status`、`assignee`、`review_scope` | 这是流程分发问题，不是投资结论问题 | 把 workflow 状态当成买卖建议 |
| 为什么页面说 ready_for_adjudication | `workflow_status` | `latest_review_status`、`feedback_summary.final_feedback_count` | 这说明样本已具备进入更高层裁决或周度复盘的成熟度 | 把 ready_for_adjudication 误判成立刻执行信号 |
| cache benchmark 这次到底有没有真实跑出来 | `data_cache_benchmark_status` | `requested`、`executed`、`write_status`、`reason` | benchmark 请求是否发起、执行是否完成、结果是否成功落盘 | 只看页面摘要，不确认 benchmark 实际是否执行 |
| 缓存复用是否真的成立 | `reuse_confirmed` | `first_hit_rate`、`second_hit_rate`、`disk_hit_gain` | 第二次运行是否相对第一次显著提升缓存命中 | 把单次验证通过误判成未来永远命中 |
| 这只票的主要研究理由是什么 | `selected[*].top_factors` | `analyst consensus`、`research_prompts` | 系统为什么认为它值得研究员继续看 | 把展示型解释当成唯一因果证明 |

如果你想把这张表记成一个更短的工作口诀，可以记成下面五句：

1. 看候选稀缺，先查 `selection_artifact_overview` 和 `layer_b` 漏斗。
2. 看入选未下单，先查 `execution_bridge`。
3. 看差一点入选，先查 `rejected` 的 reason 和分数门槛。
4. 看流程推进，先查 `review_status` 和 `workflow_status`。
5. 看运行证据，先查 `write_status`、`reuse_confirmed` 和 hit rate 变化。

---

## 21. 新人最容易踩的 10 个误判

这一节不是再解释一遍术语定义，而是专门告诉你：哪些结论最容易下错，为什么会下错，以及应该改成什么读法。

### 21.1 误判一：`selected` 就等于已经会买入

错误读法：

1. 看到某只股票出现在 `selected`，就认为系统已经决定买它。

正确读法：

1. `selected` 代表研究层值得重点复核的对象，通常更接近 watchlist。
2. 是否真正进入 `buy_orders`，还要看 `execution_bridge` 和执行层过滤。

为什么危险：

1. 这会把研究优先级误判成执行结果，直接混淆“值得看”和“会下单”这两个层级。

### 21.2 误判二：没进 `buy_orders` 就说明选股失败

错误读法：

1. 看到 `watchlist_count > 0` 但 `buy_order_count = 0`，就断定当天模型没有选出好票。

正确读法：

1. 先查 `selected[*].execution_bridge`。
2. 再查 `funnel_diagnostics.filters.buy_orders`。
3. 很多时候真正原因是 `position_blocked_score`、`blocked_by_reentry_score_confirmation` 这类执行约束。

为什么危险：

1. 这会把执行规则造成的暂不承接，误判成研究层判断错误。

### 21.3 误判三：`rejected` 里的样本都不值得再看

错误读法：

1. 只要进入 `rejected`，就把它当成彻底淘汰对象。

正确读法：

1. Replay Artifacts 里的 `rejected` 很多是 near-miss，而不是全量弱样本。
2. 要结合 `rejection_reason_codes`、`reason_counts`、`score_final` 看它是远离门槛，还是只差一点点。

为什么危险：

1. 这会错过最有研究价值的“边界样本”。

### 21.4 误判四：`score_b` 高，就一定应该入选

错误读法：

1. 只看 Layer B 分数高，就认定这只票理应进入 watchlist。

正确读法：

1. `score_b` 只代表前一层的基础强度。
2. 最终是否入选，要看 `score_c`、`score_final` 和实际门槛。

为什么危险：

1. 这会忽略 Layer C 的分歧、风控和综合权重影响。

### 21.5 误判五：`review_status = final` 就等于团队已经拍板

错误读法：

1. 看到某条 feedback 是 `final`，就认为整个团队已经完成裁决。

正确读法：

1. `final` 表示该条反馈已经从草稿进入稳定判断。
2. 但是否进入更高层复核，还要看 `workflow_status`、`latest_review_status` 和队列归属。

为什么危险：

1. 这会把“个人或单条记录的稳定意见”误判成“团队层面已经关闭讨论”。

### 21.6 误判六：`ready_for_adjudication` 是交易信号

错误读法：

1. 页面出现 `ready_for_adjudication`，就认为系统建议立刻买入、卖出或加仓。

正确读法：

1. 这是工作流成熟度状态。
2. 它表达的是“这条样本适合进入更高层复核或裁决”，而不是“市场下一步一定怎么走”。

为什么危险：

1. 这会把流程管理术语误读成投资结论。

### 21.7 误判七：`feedback_summary` 只是一个可有可无的统计角落

错误读法：

1. 读 report 时只看单条 feedback，不看 summary 聚合。

正确读法：

1. `feedback_summary` 是判断这份 report 是否已经有稳定复核活动的最快入口。
2. 其中 `feedback_count`、`final_feedback_count`、`review_status_counts` 能快速告诉你当前成熟度。

为什么危险：

1. 只看单条记录，很容易把个别意见误当成整份 report 的状态。

### 21.8 误判八：页面有 cache benchmark 字段，就说明 benchmark 一定跑过了

错误读法：

1. 只要页面出现 cache benchmark 区块，就默认 benchmark 已经真实执行。

正确读法：

1. 先看 `data_cache_benchmark_status.requested`。
2. 再看 `executed`。
3. 最后看 `write_status` 和 `reason`。

为什么危险：

1. 页面有摘要，不等于后台这次运行真的成功生成了 benchmark 证据。

### 21.9 误判九：`reuse_confirmed = true` 说明以后都会命中缓存

错误读法：

1. 一次 benchmark 通过，就把它理解成缓存问题已经永久解决。

正确读法：

1. `reuse_confirmed` 证明的是这一次验证覆盖到的数据路径，在当前条件下复用成立。
2. 还要结合 `first_hit_rate`、`second_hit_rate`、`disk_hit_gain` 看改善幅度。

为什么危险：

1. 这会把一次性的运行证据误判成长期性质的系统保证。

### 21.10 误判十：看到一只股票，就能代表整份 report

错误读法：

1. 只读一只最显眼的股票，就对整份 report 的质量下结论。

正确读法：

1. 先看 `selection_artifact_overview`。
2. 再看 `blocker_counts`、`feedback_summary`、`cache_benchmark_overview`。
3. 最后才决定要不要深挖具体样本。

为什么危险：

1. 这会把局部样本的情绪放大成整份 report 的判断，尤其容易错过“整体很有价值但单只样本不显眼”的情况。

### 21.11 一个最短自测法

如果你读完一份 report，准备写一句结论，先用下面 3 个问题卡自己一下：

1. 我这句话说的是研究层，还是执行层，还是工作流层。
2. 我引用的字段，是单条样本字段，还是 report 级聚合字段。
3. 我现在下的是“事实结论”，还是“流程结论”，还是“投资结论”。

只要这三个问题答不清，这句结论大概率还不够稳。

---

## 22. 最后记住三条原则

### 22.1 先分层，再下结论

不要把 Report 层、Candidate 层、Feedback 层字段混在一起解释。

### 22.2 先看结构，再看单点

先看 `selection_artifact_overview` 和 `funnel_diagnostics` 这类结构字段，再去看某一只票的细节，误判会少很多。

### 22.3 先区分研究问题和执行问题

在 Replay Artifacts 里，最贵的一类误判就是：

1. 把执行层 blocker 误判成选股层失败。

只要你持续先看 `selected`，再看 `execution_bridge`，很多结论都会立刻清楚。

---

## 23. 从 report 到复盘结论的标准写法模板

前面的章节解决的是：

1. 术语是什么意思。
2. 应该先看哪些字段。
3. 最容易下错哪些结论。

但真正到了复盘或交接场景，很多人还是会卡在最后一步：

1. 我看懂了。
2. 但我不知道怎么把它写成一段稳的结论。

这一节给你的不是文学表达，而是最小可复用模板。

### 23.1 一个合格结论最少要包含什么

无论你写的是日级样本结论，还是 report 级复盘结论，最少都要交代四件事：

1. 你在说哪一层。
2. 你引用了哪组事实。
3. 这些事实共同说明什么。
4. 这句话不应该被误读成什么。

如果少了第 4 点，读者就很容易把流程结论读成投资结论，把执行结论读成研究结论。

### 23.2 report 级一句话模板

适用场景：

1. 你要先判断这份 report 值不值得深挖。
2. 你在周会、交接、日报里只允许写一句话。

模板：

1. 这份 report 属于“`[主要类型]`”样本，核心证据是 `[`字段 A` + `字段 B` + `字段 C`]`，因此当前更应该把它读成“`[正确结论]`”，而不是“`[常见误判]`”。

示例一：

1. 这份 report 属于“研究样本存在但执行承接偏紧”的窗口，核心证据是 `selection_artifact_overview`、`blocker_counts` 与 `execution_bridge`，因此当前更应该把它读成“研究层有信号但执行层较保守”，而不是“系统根本选不出票”。

示例二：

1. 这份 report 属于“运行证据扎实”的 report，核心证据是 `data_cache_benchmark_status.write_status`、`reuse_confirmed` 与 hit rate 变化，因此当前更应该把它读成“本次缓存复用验证成立”，而不是“以后所有运行都会自动同样命中缓存”。

### 23.3 单只样本的三段式模板

适用场景：

1. 你在写某只股票的判断。
2. 你要把 selected、near-miss 或 blocker 样本交给别人继续看。

推荐写成三段：

1. 样本事实
2. 正确解释
3. 结论边界

模板：

1. 样本事实：`[symbol / trade_date]` 在 `[`字段组合`]` 上表现为 `[`事实描述`]`。
2. 正确解释：这说明 `[`真正含义`]`。
3. 结论边界：因此它更接近“`[正确归类]`”，而不是“`[错误归类]`”。

示例：

1. 样本事实：`2026-03-11 / 300724` 在 `selected + execution_bridge + buy_order_blocker` 上表现为已进入研究重点样本，但 buy order 被 `blocked_by_reentry_score_confirmation` 拦住。
2. 正确解释：这说明研究层已经通过，执行层因为再入场确认规则暂不承接。
3. 结论边界：因此它更接近“执行 blocker 样本”，而不是“选股失败样本”。

### 23.4 周度复盘的四段式模板

适用场景：

1. 你要把一周观察沉淀成稳定结论。
2. 你要把结论交给周度复盘或后续 backlog 转换。

推荐按四段写：

1. 这周重复出现了什么。
2. 这些现象主要发生在哪一层。
3. 当前最稳的解释是什么。
4. 下一步应该进入复核、裁决还是 backlog 转换。

模板：

1. 本周重复出现的现象是 `[`重复模式`]`。
2. 主要证据来自 `[`聚合字段`]` 与 `[`代表样本字段`]`。
3. 当前更稳的解释是 `[`层级判断`]`。
4. 因此下一步建议 `[`final / ready_for_adjudication / backlog mapping`]`。

示例：

1. 本周重复出现的现象是多只样本在研究层进入 selected，但最终未被执行层承接。
2. 主要证据来自 `blocker_counts`、`funnel_diagnostics.filters.buy_orders` 与多个 `execution_bridge.block_reason`。
3. 当前更稳的解释是执行层承接偏紧，而不是 Layer B 大面积失真。
4. 因此下一步建议优先做 Execution 方向复盘，而不是直接修改选股阈值。

### 23.5 三类最不该写的句子

反例一：

1. `300724` 没买入，说明系统这天选股失败。

问题：

1. 它跳过了 `execution_bridge`，把执行结论写成了研究结论。

更稳的写法：

1. `300724` 已进入研究重点样本，但执行层因 reentry blocker 暂未承接，因此当前证据更支持“执行保护生效”，而不是“选股失败”。

反例二：

1. 这份 report 已经 ready_for_adjudication，所以建议重点关注这只票。

问题：

1. 它把 workflow 状态误写成投资建议。

更稳的写法：

1. 这份 report 中对应样本已进入 `ready_for_adjudication`，说明其反馈成熟度已足够进入更高层复核，但这不等同于交易建议本身。

反例三：

1. `reuse_confirmed = true`，说明缓存问题已经解决。

问题：

1. 它把单次验证写成了长期保证。

更稳的写法：

1. 当前 benchmark 样本中 `reuse_confirmed = true` 且 second hit rate 明显改善，说明本次验证覆盖到的数据路径已确认缓存复用成立，但后续仍应按运行条件持续观察。

### 23.6 一个最实用的落笔顺序

如果你每次写结论都容易飘，直接套下面这个落笔顺序：

1. 先写字段，不要先写观点。
2. 再写层级，不要先写建议。
3. 最后写边界，不要把一句话写成万能结论。

把它翻成一句最短口诀就是：

1. 先证据。
2. 再归层。
3. 最后才下判断。

---

## 24. 建议的继续阅读顺序

如果你已经理解术语，但还不熟悉实际操作，建议按下面顺序继续：

1. 先看 [Replay Artifacts 值班速查卡](./replay-artifacts-duty-cheatsheet.md)，快速建立“遇到问题先看哪些字段”的肌肉记忆。
2. 再看 [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)，快速建立页面操作顺序。
3. 然后看 [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)，把“怎么看页面”补完整。
4. 再看 [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)，解决“看懂以后怎么写 feedback”。
5. 最后看 [Replay Artifacts 案例手册：2026-03-11 的 300724 为什么入选但未买入](./replay-artifacts-case-study-20260311-300724.md)，用真实样本把这些术语串起来。
