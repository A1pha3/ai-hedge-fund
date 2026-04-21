# BTST Loop ReAct Special Prompt

这个文档提供一段可直接复制投喂的超级启动词，专门用于在本仓库中持续、多轮、按 ReAct 方式推进 BTST 优化。

适用目标：

- 连续多轮优化 BTST 因子与规则
- 每轮都保留基线、实验、观察、结论与下一轮入口
- 尽量避免模型跑偏、跳步、伪优化和无法复验

推荐用法：

- 长时间连续优化时，优先使用下面的“长版超级启动词”。
- 新会话快速启动但仍要保留大部分护栏时，使用下面的“短版超级启动词”。
- 如果是直接在本仓库内跑，优先搭配 docs/prompt/btst_react_special_prompt.md 一起使用。

## 长版超级启动词

你现在在仓库 /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork 中工作。你的唯一主线目标是：基于本仓库现有 BTST 脚本、报告、回测工具和文档，持续提高“今日收盘选股、次日买入、后续 1 到 2 个交易日卖出”框架下的胜率、盈亏比和可执行性。你必须严格按 ReAct 方式工作，并且不是只做一轮，而是要连续推进多轮，直到触发停止条件为止。

你必须遵守以下总原则：

1. 不要重新设计一个新系统，优先在本仓库现有 BTST 工作流之内找到最小、最可归因、最可复验的改进。
2. 每轮只允许推进 1 个最高优先级问题，只允许修改 1 到 2 个参数或 1 个局部逻辑。
3. 每轮都必须先定义基线版本，再定义实验版本；基线和实验必须尽量使用同一脚本入口、同一命令骨架，只改变本轮验证所需的最小差异。
4. 基线和实验结果必须使用同一数据窗口、同一买卖定义、同一持有周期、同一交易成本假设、同一成交口径比较，否则该轮比较无效。
5. 除非本轮任务本身就是研究口径一致性或模型差异，否则不得擅自修改买入时点、卖出时点、持有天数、交易成本假设、成功判定标准、模型提供方、模型名称或样本窗口。
6. 每轮都必须保留基线输出目录、实验输出目录、关键指标差异、结论、是否回滚和下一轮入口。
7. 如果结果变差，优先回滚，不要强行解释。
8. 如果样本不足，先扩充验证窗口，再决定是否采用当前改动。
9. 如果连续 3 轮没有明确增益，或者问题根因已经不在因子层，而在数据质量、执行链路或标签口径，则停止当前方向并总结。
10. 如果本轮命令或脚本执行失败，优先分析失败原因并修复当前链路，不要直接换另一条完全不同的脚本链路来绕过问题。
11. 如果当前没有可用历史基线，就先建立一轮可复验的 baseline run，再进入 variant 对比。
12. 如果当前会话上下文接近上限，必须先输出一份可交接摘要，再结束当前会话，而不是在中途丢失状态。

你必须优先读取以下资源，并按这个顺序建立上下文：

1. docs/prompt/btst_react_prompt.md
2. docs/prompt/btst_react_special_prompt.md
3. docs/prompt/btst_optimize_prompt.md
4. docs/prompt/top_quant_prompt.md
5. docs/zh-cn/factors/BTST/README.md
6. docs/zh-cn/factors/BTST/05-btst-ai-optimization-runbook.md
7. docs/zh-cn/factors/BTST/09-btst-variant-acceptance-checklist.md
8. docs/zh-cn/factors/BTST/13-btst-command-cookbook.md
9. data/reports
10. outputs/202604
11. logs
12. /memories/repo 中和 BTST、selection target、short trade、carryover、corridor、frontier、replay 相关的仓库记忆

你必须优先复用本仓库已有脚本，而不是随意新建分析器。优先脚本包括但不限于：

- scripts/run_paper_trading.py
- scripts/run_btst_nightly_control_tower.py
- scripts/btst_20day_backtest.py
- scripts/analyze_btst_micro_window_regression.py
- scripts/analyze_btst_profile_frontier.py
- scripts/analyze_btst_penalty_frontier.py
- scripts/analyze_btst_score_construction_frontier.py
- scripts/analyze_short_trade_blockers.py
- scripts/analyze_layer_b_rule_variants.py
- scripts/analyze_layer_b_boundary_failures.py
- scripts/analyze_layer_c_sensitivity.py
- scripts/generate_btst_next_day_trade_brief.py
- scripts/generate_reports_manifest.py

脚本选择原则必须是：先判断问题类型，再选离问题最近的一个主分析器；如果主分析器不能回答问题，再补第二个分析器，不要一开始就并行跑很多无关脚本。

你必须始终遵守以下研究优先级，不得颠倒：

1. 先减少错误交易和左侧亏损
2. 再提高次日买入后的承接概率
3. 再提高单票上涨空间和盈亏比
4. 最后才考虑增加候选股票数量

如果某轮优化只是让票变多，但胜率、盈亏比或可执行性下降，则该优化视为失败。

从现在开始，先不要泛泛而谈，也不要直接给结论。请先输出当前最值得做的 3 个 BTST 优化任务，并说明排序依据。然后只选择第 1 个任务进入 Round 1，并严格按下面的结构执行：

### Round N

#### 推理
- 当前最高优先级瓶颈：
- 为什么优先：
- 关联的仓库证据：
- 本轮假设：
- 基线版本：
- 本轮最小动作：

#### 行动
- 读取了哪些文档：
- 查看了哪些报告目录：
- 运行了哪些仓库脚本：
- 基线命令：
- 实验命令：
- 基线输出目录：
- 实验输出目录：
- 修改了哪些仓库文件、参数或逻辑：

#### 观察
- 数据窗口：
- 报告目录：
- 样本数：
- 比较口径是否一致：
- 胜率变化：
- 平均收益变化：
- 盈亏比变化：
- 回撤或左侧亏损变化：
- 候选数量变化：
- 典型成功样本：
- 典型失败样本：
- 新副作用：

#### 再推理
- 结论：继续 / 回滚 / 暂存
- 原因：
- 下一轮是否继续当前方向：

每轮结束后，必须先判断是否满足停止条件。如果满足，则停止并给出总结；如果不满足，则不要停，不要等我提醒，直接进入下一轮。进入下一轮前，必须先明确：

- 下一轮要解决的单点问题是什么
- 下一轮的基线版本是什么
- 下一轮准备沿用还是回滚本轮改动
- 下一轮的基线命令、实验命令、基线输出目录和实验输出目录是什么

如果当前不存在可用基线目录，则下一轮前先补建基线，不允许直接拿实验结果当基线。

输出要求：

- 不要空喊“继续优化”“继续努力”。
- 不要跳过基线。
- 不要在没有观察结果前进入下一轮。
- 不要用不同模型、不同窗口、不同交易定义的结果做横向对比后声称优化有效。
- 不要只保存实验结果而不保存基线结果。
- 不要偏离 BTST 主线去做长期趋势、前端或无关重构。
- 不要在脚本失败后直接换赛道，必须先判断是参数错误、数据问题、环境问题还是逻辑问题。
- 不要让关键结论只留在对话里，必须同步沉淀到可复验目录或文档。

默认输出目录建议放在 data/reports 下，并使用可复验命名，例如：

- data/reports/btst_react_YYYYMMDD_topic_baseline
- data/reports/btst_react_YYYYMMDD_topic_variant

每轮结束后，至少额外沉淀一份简短结论，内容包括：本轮目标、基线目录、实验目录、关键指标变化、结论、是否回滚、下一轮入口。该结论优先写入 docs/zh-cn/factors/BTST 对应主题目录；如果本轮更偏实验产物，也可以写入 data/reports 下的同主题总结文件。

如果会话上下文接近上限，必须先输出一份交接摘要，至少包含：

- 已完成到第几轮
- 当前最优先问题是什么
- 当前生效的基线版本是什么
- 最近一轮的基线目录和实验目录是什么
- 最近一轮结论是继续、回滚还是暂存
- 下一轮推荐起手命令是什么

现在开始。

## 短版超级启动词

你现在在仓库 /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork 中工作，目标只有一个：基于现有 BTST 脚本、报告和回测工具，持续、多轮地提高“今日收盘选股、次日买入、后续 1 到 2 个交易日卖出”框架下的胜率、盈亏比和可执行性。严格使用 ReAct 循环，每轮都按“推理 -> 行动 -> 观察 -> 再推理”执行，并在未触发停止条件前自动进入下一轮。先读 docs/prompt/btst_react_prompt.md、docs/prompt/btst_react_special_prompt.md、docs/prompt/btst_optimize_prompt.md、docs/prompt/top_quant_prompt.md，以及 docs/zh-cn/factors/BTST/README.md、05-btst-ai-optimization-runbook.md、09-btst-variant-acceptance-checklist.md、13-btst-command-cookbook.md，并结合 data/reports、outputs/202604、logs 和相关仓库记忆建立上下文。先列出当前最值得做的 3 个优化任务，只选第 1 个进入 Round 1。每轮只允许改 1 到 2 个参数或 1 个局部逻辑，且必须先跑基线，再跑改动版本；如果当前没有可用基线，就先建立一轮 baseline run。基线和实验必须尽量用同一脚本入口和同一命令骨架，只改变本轮最小差异，结果必须使用同一数据窗口、同一买卖定义、同一持有周期、同一交易成本假设、同一成交口径比较，否则该轮无效。除非本轮任务明确研究口径问题或模型差异，否则不得擅自修改买入时点、卖出时点、持有天数、交易成本假设、成功判定标准、模型提供方、模型名称或样本窗口。优先复用 scripts/run_paper_trading.py、scripts/run_btst_nightly_control_tower.py、scripts/btst_20day_backtest.py、scripts/analyze_btst_micro_window_regression.py、scripts/analyze_short_trade_blockers.py、scripts/analyze_layer_b_rule_variants.py、scripts/analyze_layer_b_boundary_failures.py、scripts/analyze_layer_c_sensitivity.py 等已有脚本。脚本失败时先分析并修复当前链路，不要直接换赛道。每轮都要明确基线命令、实验命令、基线输出目录和实验输出目录，并给出真实证据，包括样本数、比较口径是否一致、胜率、平均收益、盈亏比、回撤、候选数量变化、成功样本、失败样本和新副作用。每轮结束后必须沉淀一份简短结论，包括本轮目标、基线目录、实验目录、关键指标变化、结论、是否回滚和下一轮入口。优先级固定为：先减少错误交易和左侧亏损，再提高次日承接，再提高单票空间，最后才考虑增加候选数量。若连续 3 轮无明确增益，或改动让质量下降，或根因已不在因子层，则停止当前方向并总结；否则直接进入下一轮，不要停。如果会话上下文接近上限，先输出交接摘要，再结束当前会话。

## 使用建议

- 需要高稳定性、准备跑很多轮时，用“长版超级启动词”。
- 需要快速开新会话、但仍要保留大部分护栏时，用“短版超级启动词”。
- 如果模型开始跑偏，优先重新投喂长版，而不是继续追加零散纠偏指令。
- 如果你希望后续复盘方便，每轮都要求它把关键结论同步沉淀到 docs/zh-cn/factors/BTST 对应主题目录。
