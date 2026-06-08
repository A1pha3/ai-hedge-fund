# 术语表

本术语表汇总本项目中出现的核心专业术语，覆盖金融投资、量化选股、多智能体工作流、A 股数据接入、BTST 短线策略、双目标评估、回放产物工作台（Replay Artifacts）与控制塔治理等主题。文档目标不是只解释孤立概念，而是帮助读者把术语放回系统上下文中理解。

---

## 使用说明

- 本文优先收录项目中真实出现、反复使用且会影响理解的术语。
- 通用金融术语与系统专有术语同时保留，便于跨章节查阅。
- 同一术语如果同时有英文名、代码字段名和中文业务说法，会尽量合并到一个词条说明。
- 中文正文优先使用统一译名，例如“仅研究模式”“仅短线模式”“双目标模式”“车道”“仅影子观察”；只有在明确指代码字段、CLI 参数或状态字面量时，才补充 `research_only`、`short_trade_only`、`lane_status`、`shadow_only_until_second_window` 等字面量。
- 如果需要把中文术语对回字段名、状态字面量或治理矩阵里的键值，请优先看“BTST 中文术语到字段/状态值对照”一节。
- 如果只关注近期新增能力，建议优先阅读“BTST 短线策略与双目标评估”“BTST 控制塔与治理”“数据、回放与工程术语”三节。

---

## 系统架构与智能体工作流

| 术语 | 中文 | 说明 |
| --- | --- | --- |
| Agent | 智能体 | 系统中的任务执行单元，在本项目里通常指扮演分析师、风控经理或投资组合经理的 AI 模块。 |
| Analyst Agent | 分析师智能体 | 负责输出单标的分析信号的智能体，如技术分析师、基本面分析师、估值分析师等。 |
| Agentic Workflow | 智能体工作流 | 多个智能体按既定流程协作、传递状态并形成最终决策的执行方式。 |
| Multi-Agent System | 多智能体系统 | 由多个角色化智能体共同组成的系统结构，本项目的核心架构。 |
| Agent State | 智能体状态 | LangGraph 中在节点之间传递的数据结构，通常包含消息、数据和元数据。 |
| AgentState | 智能体状态模型 | 本项目在 LangGraph 中定义的 TypedDict，用于承载消息、data、metadata 三层状态。 |
| State Graph | 状态图 | LangGraph 中用于描述节点、边和执行顺序的工作流模型。 |
| StateGraph | 状态图对象 | LangGraph 提供的工作流构造器，用于编排 analyst、risk manager、portfolio manager 等节点。 |
| Message Accumulation | 消息累积 | 工作流运行过程中消息不是覆盖而是持续追加，便于保留完整推理链。 |
| Annotated | 注解类型 | Python 类型系统中的注解机制，本项目用于给状态字段附加累积或合并规则。 |
| Operator.add | 累加操作符 | LangGraph 中用于把新消息追加到已有消息序列的状态更新操作。 |
| Merge Dicts | 字典合并 | 状态流转时把新旧字典字段合并而不是整体替换的策略。 |
| Analyst Signals | 分析师信号集合 | 所有 analyst agent 对各 ticker 输出的信号聚合结果。 |
| Signal Aggregation | 信号聚合 | 将多个智能体输出的观点、置信度和理由综合成更高层决策的过程。 |
| Confidence | 置信度 | 智能体或规则对当前判断的确定程度，通常映射到 0 到 100。 |
| Signal | 交易信号 | 对资产的操作建议或态度表达，如 bullish、bearish、neutral、buy、sell、hold。 |
| Consensus Score | 共识分数 | 不同分析角色之间意见一致程度的量化表示。 |
| Risk Manager Agent | 风险管理智能体 | 负责仓位上限、风险暴露、相关性约束等风险评估的智能体。 |
| Portfolio Manager Agent | 投资组合管理智能体 | 负责在多信号、多约束条件下输出最终交易动作与数量的智能体。 |
| Portfolio Decision | 组合决策 | 对单个 ticker 的最终动作决策，通常包括 action、quantity、confidence、reasoning。 |
| Progress Tracking | 进度跟踪 | 在 CLI 或前端中报告各 agent 当前执行阶段的机制。 |
| System Prompt | 系统提示词 | 定义模型角色、边界和输出风格的固定提示。 |
| User Prompt | 用户提示词 | 用户提供给系统的具体请求、问题或任务描述。 |
| Prompt Engineering | 提示词工程 | 通过设计和约束输入提示来稳定模型输出的实践。 |
| LLM | 大型语言模型 | 如 GPT、Claude、GLM 等可理解和生成自然语言的模型。 |
| LLM Integration | LLM 集成 | 将模型调用、结构化输出、重试、路由和上下文状态结合到系统中的方式。 |
| Token | 词元 | LLM 处理文本的基本单位，常用于计费、长度限制和采样控制。 |
| Top-k Sampling | Top-k 采样 | 生成时只在概率最高的 k 个 token 中采样的策略。 |

---

## 选股分层与执行流水线

| 术语 | 中文 | 说明 |
| --- | --- | --- |
| Pipeline | 流水线 | 系统把候选发现、打分、深度分析和执行拆成多个连续阶段的整体流程。 |
| Layer A | 第 A 层 | 全市场快筛层，负责从市场全量标的中产出候选池。 |
| Layer A Discovery | 第 A 层发现 | 在 Layer A 中识别初始候选的过程。 |
| Candidate Pool | 候选池 | 通过前置规则过滤后保留下来的股票集合。 |
| Candidate Stock | 候选标的 | 进入候选池的单个股票对象。 |
| Layer B | 第 B 层 | 规则化、多因子评分层，用于缩小候选范围并形成结构化分数。 |
| Layer B Ranking | 第 B 层排序 | 按 score_b 或因子融合结果对候选排序的过程。 |
| Strategy Signal | 策略信号 | 单一策略模块输出的标准化方向、置信度、完整度及子因子集合。 |
| SubFactor | 子因子 | 构成某一策略信号的细粒度因素，如 momentum、profitability、event_freshness。 |
| Fused Score | 融合得分 | 多策略信号加权聚合后的综合分数，在 Layer B 中对应 score_b。 |
| Arbitration | 冲突仲裁 | 当不同策略信号冲突时，对其进行降权、信任切换或补偿的机制。 |
| Market State | 市场状态 | 用于描述整体市场环境的状态，如 trend、range、mixed、crisis。 |
| Layer C | 第 C 层 | 多分析师深度分析与共识聚合层，用于形成研究或交易级决策。 |
| Layer C Decision | 第 C 层决策 | Layer C 聚合后对单个标的给出的最终研究态度或执行建议。 |
| Watchlist | 观察清单 | 通过多层筛选后进入重点跟踪或待执行列表的标的集合。 |
| Watch Candidate | 观察候选 | 尚未达到直接执行条件，但被列入重点观察的标的。 |
| Buy Order | 买入指令 | 执行层对通过筛选的标的产生的实际下单动作。 |
| Screen Only | 仅筛选模式 | 只运行 Layer A 与 Layer B，而不进入 Layer C 深度分析与执行层的模式。 |
| Research Mode | 研究模式 | 以研究、解释和验证为目标，不直接转为次日交易动作的运行模式。 |
| Shadow Mode | 影子模式 | 在不进入主流程或真实持仓的前提下，对策略进行旁路跟踪和验证的模式。 |
| Replay | 回放 | 对历史报告、计划或窗口重新执行或重新解释，以验证策略表现和产物一致性。 |
| Frozen Replay | 冻结回放 | 复用已存储 plan 或 current_plan 而不重跑上游模型与筛选层的回放方式。 |
| Current Plan | 当前计划 | 当日收盘后生成并持久化的选股与执行计划快照。 |
| Post-Market | 盘后 | 收盘后生成计划、报告和 followup 产物的阶段。 |
| Pre-Market | 盘前 | 次日开盘前整理执行卡、优先级、观察点和开盘动作的阶段。 |

---

## BTST 短线策略与双目标评估

| 术语 | 中文 | 说明 |
| --- | --- | --- |
| BTST | 今日买入次日卖出 | Buy Today Sell Tomorrow 的缩写，适用于 A 股 T+1 语境下的短线策略模拟与验证。 |
| Selection Target | 选股目标 | 针对同一候选从不同目标函数出发的评估结果，如 research 与 short_trade。 |
| Research Target | 研究目标 | 偏研究、偏质量确认的目标，用于判断标的是否值得进入研究或观察主线。 |
| Short Trade Target | 短线目标 | 面向 BTST 场景的目标，强调次日交易可操作性、突破质量和执行质量。 |
| Target Mode | 目标模式 | 选股目标（selection target）的运行模式，支持“仅研究模式（`research_only`）”“仅短线模式（`short_trade_only`）”“双目标模式（`dual_target`）”。 |
| Research Only | 仅研究模式 | `target_mode` 的一种字面量，表示只输出研究目标结果，不生成短线目标评估。 |
| Short Trade Only | 仅短线模式 | `target_mode` 的一种字面量，表示只输出短线目标评估，用于 BTST 专用回放、治理和统计。 |
| Dual Target | 双目标模式 | `target_mode` 的一种字面量，表示同时计算研究目标与短线目标两套评估结果。 |
| Candidate Entry | 候选入口 | 指样本进入短线候选层或进入候选入口治理视野的入口语义；中文正文优先写“候选入口”，只有在脚本名、字段名和报告名中才保留 `candidate_entry` 字面量。 |
| Candidate-Entry Frontier | 候选入口前沿 | 比较不同候选入口规则在 focus 样本与 preserve 样本上过滤效果的边界实验。 |
| Target Profile | 目标配置 | 定义阈值、权重、惩罚项与硬性 gate 的参数集合。 |
| Dual Target Evaluation | 双目标评估 | 同一 ticker 在研究目标与短线目标两条目标线上得到的联合评估结果。 |
| Dual Target Summary | 双目标摘要 | 对 selected、near_miss、blocked、rejected 等数量的汇总统计。 |
| Delta Classification | 差异分类 | research 与 short_trade 结果不一致时的分类标签，如 research_pass_short_reject。 |
| Delta Summary | 差异摘要 | 对双目标分歧原因的简明解释。 |
| Candidate Source | 候选来源 | 标记该 ticker 是来自 layer_c_watchlist、short_trade_boundary、watchlist_filter_diagnostics 等哪条来源路径。 |
| Candidate Reason Codes | 候选原因码 | 解释标的为何进入当前候选路径的结构化标签。 |
| Selected | 已选中 | 达到目标阈值并被认为可以继续执行或重点跟踪的状态。 |
| Near Miss | 接近通过 | 与通过阈值非常接近、具备跟踪价值但暂未正式通过的状态。 |
| Blocked | 被阻断 | 分数或方向上有机会，但被 gate、冲突或执行约束强制阻断的状态。 |
| Rejected | 已拒绝 | 未达到当前目标要求且不属于近距离可救范围的状态。 |
| Gate Status | 门禁状态 | 数据、结构、分数、执行等维度是否通过的状态汇总。 |
| Blocker | 阻塞原因 | 导致当前候选无法晋级或无法执行的直接原因。 |
| Breakout Freshness | 突破新鲜度 | 反映价格突破是否仍然处于“新鲜、未衰减”的阶段。 |
| Trend Acceleration | 趋势加速度 | 反映趋势强化速度和连续性的指标。 |
| Volume Expansion Quality | 放量质量 | 成交量放大是否健康、是否与价格趋势协同的质量度量。 |
| Close Strength | 收盘强度 | 收盘价相对日内结构的位置强弱，用于判断尾盘承接质量。 |
| Sector Resonance | 板块共鸣度 | 个股走势与板块、行业或主题是否形成协同共振。 |
| Catalyst Freshness | 催化剂新鲜度 | 影响股价的消息、事件或主题是否仍具备新鲜驱动力。 |
| Layer C Alignment | 第 C 层对齐度 | 短线目标与 Layer C 共识方向之间的一致程度。 |
| Breakout Stage | 突破阶段 | 对突破状态的阶段划分，如 confirmed_breakout、prepared_breakout、weak_breakout。 |
| Expected Holding Window | 预期持有窗口 | 该目标假设的持仓时长区间。 |
| Preferred Entry Mode | 偏好入场模式 | 对开盘、分时确认或条件触发等入场方式的偏好描述。 |
| Structural Conflict | 结构性冲突 | Layer B 与 Layer C，或 research 与 short trade 之间出现方向或质量冲突。 |
| B-C Conflict | B-C 冲突 | 常指 Layer B 偏积极而 Layer C 偏消极的结构性不一致。 |
| Layer C Avoid Penalty | 第 C 层回避惩罚 | 当 Layer C 决策为 avoid 时施加到短线目标上的惩罚。 |
| Stale Penalty | 陈旧惩罚 | 对趋势过老、修复过久或催化剂不再新鲜的候选进行扣分。 |
| Overhead Penalty | 上方压力惩罚 | 对上方套牢、供给压力或冲突型结构施加的扣分。 |
| Extension Penalty | 延伸过度惩罚 | 对已经运行过远、缺乏空间或离安全位置过远的候选进行扣分。 |
| Profitability Relief | 盈利约束缓解 | 在某些强趋势、强催化条件下，对盈利类硬性约束做有限软化的机制。 |
| Opportunity Pool | 机会池 | 尚未进入正式短线名单，但具备继续观察和条件升级价值的候选集合。 |
| Promotion Trigger | 晋级触发器 | 候选从机会池或 near_miss 升级为更高优先级时所需满足的触发条件。 |
| Research Upside Radar | 研究上行雷达 | 更偏研究线索的上行动能观察集合，不直接进入当日 BTST 交易名单。 |
| Next High Hit Rate | 次高点命中率 | 历史同类样本在后续窗口中触及预设涨幅或新高阈值的概率。 |
| Historical Prior | 历史先验 | 基于历史相似样本、同票或同来源样本提炼的经验性统计参考。 |
| Execution Quality | 执行质量 | 候选在真实开盘或次日执行层面可操作性的质量判断。 |
| Actionability | 可执行性 | 候选是否已经具备形成实际交易动作的条件。 |

---

## BTST 控制塔、治理与回放产物

| 术语 | 中文 | 说明 |
| --- | --- | --- |
| Control Tower | 控制塔 | 对 BTST 运行状态、治理结论、优先动作和回放队列进行汇总的自动化监控与报告模块。 |
| BTST Control Tower | BTST 控制塔 | 专门面向 BTST 策略的控制塔视图与产物集合。 |
| Nightly Control Tower | 夜间控制塔 | 在每日流程结束后自动生成的 BTST 治理与回放汇总产物。 |
| Governance | 治理 | 对 rollout、验证、边界开放、风险隔离和晋级条件进行系统性管理的过程。 |
| Governance Synthesis | 治理综合报告 | 将 rollout governance、candidate entry governance、latest followup 等信息综合到一份控制塔工件中的报告。 |
| Governance Validation | 治理验证报告 | 对当前治理规则、边界和状态是否满足约束进行验证的工件。 |
| Replay Cohort | 回放队列组 | 按 selection target、窗口或报告族群聚合后的历史回放样本集合。 |
| Open-Ready Delta | 开盘就绪差异报告 | 对比当前 nightly 快照与历史快照之间状态变化的差异工件。 |
| Archived Nightly Snapshot | 夜间归档快照 | 每次 nightly control tower 运行后归档保存的历史基线快照。 |
| Reading Order | 阅读顺序 | 控制塔为人工排查推荐的报告阅读路径。 |
| Followup | 后续产物 | 收盘后围绕次日动作生成的一组 brief、card、priority board 等工件。 |
| Next-Day Trade Brief | 次日交易简报 | 汇总 selected、near_miss、opportunity_pool、research_upside_radar 的核心盘前摘要。 |
| Premarket Execution Card | 盘前执行卡 | 给出主行动作、条件动作和观察动作的执行级卡片。 |
| Opening Watch Card | 开盘观察卡 | 开盘阶段重点监控的标的、阈值和关注点清单。 |
| Next-Day Priority Board | 次日优先级看板 | 对次日优先跟踪或优先执行的标的进行排序和解释的看板。 |
| Priority Row | 优先级行 | 优先级看板中的单条候选记录，通常包含车道字段 `lane`、`why_now`、`suggested_action` 等信息。 |
| Action Board | 动作板 | 汇总下一步高优先级任务、理由和 CLI 提示的治理产物。 |
| Lane | 车道 | 在治理语境下表示策略或样本当前所在的推进路径；中文正文优先写“车道”，只有在明确指字段名时才写 `lane`。 |
| Shadow Only | 仅影子观察 | 指规则或样本只保留影子验证，不进入默认推进或执行；明确指状态值时常见字面量如 `shadow_only_until_second_window`。 |
| Lane Status | 车道状态 | 当前车道是否处于“已就绪”“等待中”“仅影子观察”“仅维持观察”或“已阻塞”等状态；明确指字段名时常写成 `lane_status`。 |
| Lane Promotion | 车道晋级 | 从仅影子观察、仅研究模式等受限状态升级到更高验证或更高执行等级的过程。 |
| Governance Tier | 治理层级 | 描述某条车道当前所处的治理等级，如“主车道滚动推进专用”（`primary_roll_forward_only`）或“候选入口仅影子观察”（`candidate_entry_shadow_only`）。 |
| Action Tier | 动作层级 | 描述当前建议动作的强弱与性质，如 primary_entry、watch_only、conditional_watch_upgrade。 |
| Validation Verdict | 验证结论 | 对某条车道或某类规则当前是否达到上线、影子运行或继续观察条件的判断。 |
| Global Guardrail | 全局护栏 | 对所有优先候选都适用的全局约束条件。 |
| Frontier | 前沿/边界 | 已接近可开放区域、但尚未满足全量上线条件的一组参数点或候选集合。 |
| Frontier Constraint | 前沿约束 | 限制某个前沿继续开放、默认上线或晋级的条件集合。 |
| Closed Frontier | 已关闭前沿 | 当前已经确认不适合继续推进、或需保持关闭状态的前沿。 |
| Penalty Frontier | 惩罚前沿 | 在 penalty 参数空间内寻找通过 guardrail 的可行区域。 |
| Score Frontier | 分数前沿 | 围绕 near_miss threshold、penalty 权重和 score gap 进行边界释放的可行区域。 |
| Recurring Frontier | 复现前沿 | 在重复出现的相似样本上形成的前沿集合，用于判定是否值得持续推进。 |
| Targeted Release | 定向释放 | 只针对某类候选或某条边界进行小范围参数放松的实验策略。 |
| Case-Based Release | 个案释放 | 以个别边界样本为中心，验证是否值得局部放行的释放方式。 |
| Controlled Promotion | 受控推进 | 在满足护栏和验证条件后，按治理规则小步前进的推进方式。 |
| Blocking Reason | 阻塞原因 | 阻止车道晋级、前沿开放或默认上线的主因。 |
| Preserve Misfire | 保护误伤 | 本应被保留的关键样本在规则变体中被错误过滤掉的现象。 |
| Cross-Window Stability | 跨窗口稳定性 | 某规则或候选在多个独立窗口中都表现稳定、不是偶然命中的能力。 |
| Independent Window | 独立窗口 | 用于验证策略泛化能力的相互独立时间区间。 |
| Missing Window | 缺失窗口 | 某项验证应覆盖但尚未产出有效样本或结果的窗口。 |
| Primary Roll Forward | 主车道滚动推进 | 针对主车道样本进行持续验证和逐步推进的治理主线。 |
| Structural Shadow Hold | 结构性影子持有 | 对结构性冲突样本仅保留 shadow 跟踪而不进入默认推进的治理策略。 |
| Recurring Shadow Runbook | 复现影子运行手册 | 针对复现影子车道的验证、复核和下一步动作说明文档。 |
| Window Scan | 窗口扫描 | 在多个 trade date 或独立窗口内批量检查规则覆盖和命中质量的过程。 |
| Shadow Rollout Review | 影子推进复核 | 影子观察规则在默认推进前的复核阶段；当明确指状态字面量时，常见为 `shadow_rollout_review_ready`。 |
| Rollout Readiness | 推出就绪度 | 某规则是否已达到从仅影子观察或仅研究模式升级到默认受控推进（rollout）的成熟度。 |

---

## BTST 术语来源索引

下表按术语簇列出最常用的实现入口，方便从中文说明快速跳回脚本或模块。表中路径是主要实现位置，不代表唯一引用位置。

| BTST 术语类别 | 代表术语 | 主要实现入口 | 说明 |
| --- | --- | --- | --- |
| 双目标与目标模式 | 目标模式、仅研究模式、仅短线模式、双目标模式、双目标评估 | [src/targets/models.py](../../../src/targets/models.py)、[src/targets/router.py](../../../src/targets/router.py)、[src/targets/research_target.py](../../../src/targets/research_target.py)、[src/targets/short_trade_target.py](../../../src/targets/short_trade_target.py) | 定义 `target_mode`、组装 `selection_targets`，并计算研究目标与短线目标两条目标线。 |
| 目标配置与解释 | 目标配置、差异摘要、候选原因码、偏好入场模式 | [src/targets/profiles.py](../../../src/targets/profiles.py)、[src/targets/explainability.py](../../../src/targets/explainability.py) | 负责阈值、惩罚项、解释标签与盘前 followup 展示所需语义。 |
| 候选入口与弱结构治理 | 候选入口、候选入口前沿、窗口扫描、保护误伤、推出就绪度 | [scripts/analyze_btst_candidate_entry_frontier.py](../../../scripts/analyze_btst_candidate_entry_frontier.py)、[scripts/analyze_btst_candidate_entry_window_scan.py](../../../scripts/analyze_btst_candidate_entry_window_scan.py)、[scripts/analyze_btst_candidate_entry_rollout_governance.py](../../../scripts/analyze_btst_candidate_entry_rollout_governance.py) | 负责定义弱结构候选入口规则、跨窗口证据和 p9 治理结论。 |
| 推进车道与治理校验 | 车道、车道状态、车道晋级、治理层级、治理综合、治理验证 | [scripts/analyze_btst_rollout_governance_board.py](../../../scripts/analyze_btst_rollout_governance_board.py)、[scripts/analyze_btst_governance_synthesis.py](../../../scripts/analyze_btst_governance_synthesis.py)、[scripts/validate_btst_governance_consistency.py](../../../scripts/validate_btst_governance_consistency.py) | 汇总主车道、影子车道、复现车道与结构性车道，并校验状态是否一致。 |
| 控制塔与夜间差分 | BTST 控制塔、夜间控制塔、开盘就绪差异报告、阅读顺序 | [scripts/run_btst_nightly_control_tower.py](../../../scripts/run_btst_nightly_control_tower.py)、[scripts/generate_reports_manifest.py](../../../scripts/generate_reports_manifest.py) | 生成夜间汇总包、开盘就绪差分与 manifest 索引。 |
| 盘后后续产物与盘前工件 | 次日交易简报、盘前执行卡、开盘观察卡、次日优先级看板、机会池、研究上行雷达 | [src/paper_trading/btst_reporting.py](../../../src/paper_trading/btst_reporting.py) | 汇总 `selected`、`near_miss`、机会池与研究观察集合，生成盘前可消费工件。 |

---

## BTST 中文术语到字段/状态值对照

下表只收录最常用于读报告、看治理矩阵和对照脚本输出的字段。中文正文应优先写中文术语，只有在需要精确对字段、状态值或报告字面量时，才回落到右侧这些字面量。

| 中文术语 | 常见字段 | 典型状态值/键 | 主要实现入口 |
| --- | --- | --- | --- |
| 仅研究模式 | `target_mode` | `research_only` | [src/targets/models.py](../../../src/targets/models.py)、[src/targets/router.py](../../../src/targets/router.py) |
| 仅短线模式 | `target_mode` | `short_trade_only` | [src/targets/models.py](../../../src/targets/models.py)、[src/targets/router.py](../../../src/targets/router.py) |
| 双目标模式 | `target_mode` | `dual_target` | [src/targets/models.py](../../../src/targets/models.py)、[src/targets/router.py](../../../src/targets/router.py) |
| 跟进简报车道 | `lane` | `primary_entry`、`selected_backup`、`near_miss_watch`、`opportunity_pool`、`research_upside_radar` | [src/paper_trading/btst_reporting.py](../../../src/paper_trading/btst_reporting.py) |
| 治理车道标识 | `lane_id` | `primary_roll_forward`、`single_name_shadow`、`recurring_shadow_close_candidate`、`recurring_intraday_control`、`structural_shadow_hold`、`candidate_entry_shadow` | [scripts/analyze_btst_governance_synthesis.py](../../../scripts/analyze_btst_governance_synthesis.py) |
| 车道状态 | `lane_status` | `primary_controlled_follow_through`、`ready_for_shadow_validation`、`shadow_only_until_second_window`、`shadow_rollout_review_ready`、`structural_shadow_hold_only` | [scripts/analyze_btst_governance_synthesis.py](../../../scripts/analyze_btst_governance_synthesis.py)、[scripts/analyze_btst_candidate_entry_rollout_governance.py](../../../scripts/analyze_btst_candidate_entry_rollout_governance.py)、[scripts/analyze_btst_recurring_shadow_runbook.py](../../../scripts/analyze_btst_recurring_shadow_runbook.py) |
| 治理层级 | `governance_tier` | `primary_roll_forward_only`、`single_name_shadow_only`、`recurring_shadow_close_candidate`、`recurring_intraday_control`、`structural_shadow_hold_only`、`candidate_entry_shadow_only` | [scripts/analyze_btst_rollout_governance_board.py](../../../scripts/analyze_btst_rollout_governance_board.py)、[scripts/analyze_btst_governance_synthesis.py](../../../scripts/analyze_btst_governance_synthesis.py) |
| 动作层级 | `action_tier` | `primary_entry`、`watch_only`、`conditional_watch_upgrade`、`primary_promote`、`intraday_control_only`、`structural_shadow_hold`、`shadow_only` | [src/paper_trading/btst_reporting.py](../../../src/paper_trading/btst_reporting.py)、[scripts/analyze_btst_governance_synthesis.py](../../../scripts/analyze_btst_governance_synthesis.py) |
| 个案短线入口分层 | `readiness_tier` | `primary_controlled_follow_through`、`secondary_shadow_entry`、`control_only` | [scripts/analyze_case_based_short_trade_entry_readiness.py](../../../scripts/analyze_case_based_short_trade_entry_readiness.py)、[scripts/analyze_case_based_short_trade_follow_through_runbook.py](../../../scripts/analyze_case_based_short_trade_follow_through_runbook.py) |
| 推出就绪度 | `rollout_readiness` | `shadow_only_until_second_window`、`shadow_rollout_review_ready` | [scripts/analyze_btst_candidate_entry_window_scan.py](../../../scripts/analyze_btst_candidate_entry_window_scan.py)、[scripts/analyze_btst_candidate_entry_rollout_governance.py](../../../scripts/analyze_btst_candidate_entry_rollout_governance.py) |

---

## 数据、回放与工程术语

| 术语 | 中文 | 说明 |
| --- | --- | --- |
| A-share | A 股 | 中国大陆证券交易所上市、以人民币计价的股票，是本项目重点支持市场。 |
| Market Data Provider | 市场数据提供商 | 为系统提供价格、财务、新闻等数据的数据源接口。 |
| AkShare | A 股数据接口库 | 常用于获取 A 股行情、财务和统计数据的 Python 数据接口。 |
| Tushare | 图莎瑞数据接口 | 面向中国金融市场的数据接口服务，本项目支持其 Pro API。 |
| Financial Datasets API | 美股金融数据接口 | 项目中用于部分美股行情与财务数据的数据服务。 |
| Cache | 缓存 | 用于减少重复 IO 或重复 API 请求的中间存储层。 |
| Cache Hit | 缓存命中 | 请求的数据已在缓存中，无需重新拉取。 |
| Cache Miss | 缓存未命中 | 请求的数据不在缓存中，需要回源获取。 |
| In-Memory Cache | 内存缓存 | 基于 RAM 的缓存层，读取速度快但生命周期通常随进程结束。 |
| Memory Cache | 内存缓存 | In-Memory Cache 的同义说法。 |
| TTL | 生存时间 | 缓存条目在过期前可被复用的时间长度。 |
| LRU | 最近最少使用 | 常见缓存淘汰策略，优先移除最久未使用的数据。 |
| Redis | Redis | 常用作缓存、键值存储和消息中间层的内存数据库。 |
| API Rate Limiting | API 速率限制 | 数据供应商对请求频率的限制。 |
| Retry Strategy | 重试策略 | 调用失败后自动重试的规则。 |
| Exponential Backoff | 指数退避 | 每次重试逐渐拉长等待时间的策略。 |
| Circuit Breaker | 断路器 | 当外部依赖异常持续出现时暂时熔断请求的保护机制。 |
| Bulkhead Pattern | 隔舱模式 | 把不同故障域隔离开，避免异常扩散。 |
| Backpressure | 背压 | 当下游处理不过来时，对上游施加节流或排队压力的机制。 |
| Throttling | 节流 | 主动限制请求或处理速率的机制。 |
| Data Pre-fetching | 数据预取 | 在明确后续会使用时提前拉取数据，降低运行中等待时间。 |
| Lazy Loading | 延迟加载 | 只有真正需要时才去加载资源的策略。 |
| Deferred Execution | 延迟执行 | 把计算或动作推迟到实际消费时再执行。 |
| Eventual Consistency | 最终一致性 | 分布式或异步系统中数据可能暂时不一致，但最终会收敛一致。 |
| Idempotency | 幂等性 | 同一操作重复执行多次，结果与执行一次相同的性质。 |
| Race Condition | 竞态条件 | 多个执行路径竞争同一状态，导致结果不稳定的现象。 |
| Message Queue | 消息队列 | 在异步系统中传递任务或事件的中间件。 |
| Parallel Execution | 并行执行 | 同时执行多个任务以缩短总耗时。 |
| Soft Delete | 软删除 | 不直接物理删除数据，而是通过状态标记逻辑删除。 |
| Pydantic | 数据验证库 | Python 中常用于类型校验、模型解析与序列化的库。 |
| Generic | 泛型 | 不绑定单一类型、可复用于多种类型的编程能力。 |
| Replay Artifacts | 回放产物 | 针对历史执行过程生成的报告、摘要、反馈和诊断工件。 |
| Report Manifest | 报告清单 | 对当前所有关键报告的索引、刷新状态和阅读路径的汇总。 |
| SSE | 服务器发送事件 | 后端向前端持续推送流式执行结果的通信方式。 |

---

## 金融、风险与交易术语

| 术语 | 中文 | 说明 |
| --- | --- | --- |
| Alpha | 超额收益 | 超过市场基准的那部分收益。 |
| Beta | 贝塔 | 资产相对市场波动性的度量。 |
| Backtesting | 回测 | 用历史数据验证策略有效性的过程。 |
| Benchmark | 基准 | 用于比较策略表现的参考指数或资产。 |
| Black-Litterman Model | Black-Litterman 模型 | 将市场均衡收益与投资者主观看法结合的组合优化方法。 |
| CAGR | 复合年增长率 | 反映投资长期年化增速的指标。 |
| Correlation | 相关性 | 两个变量共同变化程度的统计量。 |
| Cycle | 周期 | 经济或市场从扩张到收缩的阶段性波动。 |
| DCF | 现金流折现 | 将未来现金流折算为现值的估值方法。 |
| NPV | 净现值 | 未来现金流现值减去初始投资后的净收益。 |
| Discount Rate | 折现率 | 用于折现未来现金流的利率。 |
| Dividend Yield | 股息率 | 年度股息相对于当前股价的比例。 |
| Drawdown | 回撤 | 从净值峰值到后续谷值的跌幅。 |
| Maximum Drawdown | 最大回撤 | 历史区间内出现过的最大回撤幅度。 |
| Efficient Frontier | 有效前沿 | 在既定风险水平下收益最优的一组投资组合集合。 |
| EPS | 每股收益 | 公司净利润除以流通股数。 |
| EMA | 指数移动平均 | 对近期价格赋予更高权重的移动平均方法。 |
| Free Cash Flow | 自由现金流 | 企业维持经营和资本开支后可自由支配的现金。 |
| Fibonacci Retracement | 斐波那契回调 | 技术分析中用来寻找回调支撑或阻力区域的方法。 |
| Fundamental Analysis | 基本面分析 | 通过财务、业务、行业和治理等因素判断价值的方法。 |
| Growth Investing | 成长投资 | 以高成长公司为主要对象的投资风格。 |
| Growth Rate | 增长率 | 收入、利润或指标随时间增长的速度。 |
| Gross Margin | 毛利率 | 收入扣除营业成本后的利润率。 |
| Hedge Ratio | 对冲比率 | 用于中和风险暴露的资产比例。 |
| High-Frequency Trading | 高频交易 | 借助极短时间价差进行高频买卖的交易方式。 |
| Intrinsic Value | 内在价值 | 基于基本面或现金流模型估算的理论价值。 |
| IPO | 首次公开募股 | 公司首次面向公众发行股票。 |
| Interest Rate | 利率 | 资金价格，也是宏观经济的重要变量。 |
| Liquidity | 流动性 | 资产以合理价格快速成交的能力。 |
| Long Position | 多头头寸 | 押注价格上涨的持仓方向。 |
| Short Position | 空头头寸 | 押注价格下跌的持仓方向。 |
| Margin of Safety | 安全边际 | 买入价格低于估算内在价值所留下的缓冲空间。 |
| Market Cap | 市值 | 总股本乘以股价所得的市场价值。 |
| MACD | 指数平滑异同移动平均 | 由快慢均线差值构成的趋势技术指标。 |
| NCAV | 净流动资产价值 | 流动资产减去总负债后的价值指标。 |
| Operating Margin | 营业利润率 | 营业利润占营业收入的比例。 |
| Open Interest | 持仓量 | 期货或期权市场未平仓合约的数量。 |
| P/B Ratio | 市净率 | 股价与每股净资产的比值。 |
| P/E Ratio | 市盈率 | 股价与每股收益的比值。 |
| PEG Ratio | 市盈率相对增长比率 | 市盈率与盈利增长率的比值。 |
| Portfolio | 投资组合 | 一组资产头寸的集合。 |
| Position Limit | 仓位限制 | 单个资产或组合允许持有的上限。 |
| Position Sizing | 仓位计算 | 按风险预算和策略要求确定头寸大小。 |
| Put-Call Ratio | 看跌看涨比率 | 看跌期权成交量与看涨期权成交量的比值。 |
| Recession | 衰退 | 宏观经济持续走弱的阶段。 |
| Resistance | 阻力位 | 价格上行时容易遇到抛压的区域。 |
| Support | 支撑位 | 价格下行时容易获得买盘承接的区域。 |
| ROE | 净资产收益率 | 净利润相对股东权益的收益效率。 |
| ROI | 投资回报率 | 投资收益相对投资成本的比例。 |
| RSI | 相对强弱指数 | 用于识别超买、超卖状态的动量指标。 |
| Sharpe Ratio | 夏普比率 | 超额收益相对总波动的风险调整收益指标。 |
| Sortino Ratio | 索提诺比率 | 只考虑下行波动的风险调整收益指标。 |
| Stop Loss | 止损 | 为限制亏损而设置的退出阈值。 |
| Systematic Risk | 系统性风险 | 无法通过分散化消除的整体市场风险。 |
| Systematic Trading | 系统化交易 | 按规则和模型而非主观临场判断执行的交易方式。 |
| Technical Analysis | 技术分析 | 通过价格、成交量和形态信息预测走势的方法。 |
| Time Horizon | 投资期限 | 计划持有资产的时间长度。 |
| Treasury Yield | 国债收益率 | 常被视作无风险利率的近似参照。 |
| Undervalued | 低估 | 市场价格低于估算价值的状态。 |
| VaR | 风险价值 | 在给定置信水平与持有期下可能遭受的最大损失估计。 |
| CVaR | 条件风险价值 | 超过 VaR 阈值后的平均尾部损失。 |
| Volatility | 波动率 | 价格或收益率的波动程度。 |
| Value Investing | 价值投资 | 以低估与安全边际为核心的投资风格。 |
| WACC | 加权平均资本成本 | 企业各类资本成本的加权平均。 |
| Whipsaw | 震荡打脸 | 价格快速来回波动、频繁触发错误信号的现象。 |
| 10-Bagger | 十倍股 | 价格上涨到初始价格 10 倍的股票。 |
| 50-Day Moving Average | 50 日均线 | 过去 50 个交易日价格平均值。 |
| 200-Day Moving Average | 200 日均线 | 过去 200 个交易日价格平均值。 |
| Alpha（α） | 阿尔法 | Alpha 的希腊字母写法。 |
| Beta（β） | 贝塔 | Beta 的希腊字母写法。 |
| Sigma（Σ） | 协方差矩阵符号 | 常用于统计、风险和优化问题中的数学符号。 |

---

## 常用缩写

| 缩写 | 全称 | 中文 |
| --- | --- | --- |
| AI | Artificial Intelligence | 人工智能 |
| API | Application Programming Interface | 应用程序接口 |
| BPS | Basis Points | 基点 |
| BTST | Buy Today Sell Tomorrow | 今日买入次日卖出 |
| CAGR | Compound Annual Growth Rate | 复合年增长率 |
| CVaR | Conditional Value at Risk | 条件风险价值 |
| DCF | Discounted Cash Flow | 现金流折现 |
| EMA | Exponential Moving Average | 指数移动平均 |
| EPS | Earnings Per Share | 每股收益 |
| ETF | Exchange Traded Fund | 交易所交易基金 |
| FCF | Free Cash Flow | 自由现金流 |
| GDP | Gross Domestic Product | 国内生产总值 |
| LLM | Large Language Model | 大型语言模型 |
| LRU | Least Recently Used | 最近最少使用 |
| MACD | Moving Average Convergence Divergence | 指数平滑异同移动平均 |
| NLP | Natural Language Processing | 自然语言处理 |
| NPV | Net Present Value | 净现值 |
| P/B | Price to Book | 市净率 |
| P/E | Price to Earnings | 市盈率 |
| PEG | Price/Earnings to Growth | 市盈率相对增长比率 |
| ROI | Return on Investment | 投资回报率 |
| ROE | Return on Equity | 净资产收益率 |
| RSI | Relative Strength Index | 相对强弱指数 |
| SSE | Server-Sent Events | 服务器发送事件 |
| TTL | Time To Live | 生存时间 |
| VaR | Value at Risk | 风险价值 |
| WACC | Weighted Average Cost of Capital | 加权平均资本成本 |

---

## 参考资源

- Investopedia：<https://www.investopedia.com/>
- CFA Institute Glossary：<https://www.cfainstitute.org/en/resources/cfa-program-glossary>
- OpenAI Glossary：<https://platform.openai.com/docs/glossary>
- LangGraph 文档：<https://langchain-ai.github.io/langgraph/>

---

## 版本信息

| 项目 | 信息 |
| --- | --- |
| 文档版本 | 1.5.0 |
| 最后更新 | 2026 年 4 月 1 日 |

### 更新日志

| 版本 | 日期 | 变更内容 |
| --- | --- | --- |
| v1.5.0 | 2026.04.01 | 新增“BTST 中文术语到字段/状态值对照”，并将第二轮 BTST 中文文档中的准入、前沿、释放、回放产物等正文写法继续统一为中文优先 |
| v1.4.0 | 2026.04.01 | 统一 BTST 相关中英文混用写法，新增 BTST 术语来源索引并补充候选入口、仅影子观察、影子推进复核等词条 |
| v1.3.0 | 2026.04.01 | 重构术语表结构，新增系统架构、双目标、BTST 控制塔、治理与回放产物术语，补全近期短线策略相关词汇 |
| v1.2.0 | 2026.02.13 | 全面扩充术语数量，增加分类和常用缩写表 |
| v1.0.0 | 2025.10 | 初始版本 |

---

## 反馈与贡献

如果您发现术语遗漏、定义不准确，或近期新增模块还未收录，欢迎继续补充和修订。

**返回文档体系总览**：[SUMMARY.md](../SUMMARY.md)
