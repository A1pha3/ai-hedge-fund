# 2026-03-18 系统级后续工作路线图

如果要把这份路线图直接拆成可执行任务，可以先看 [系统执行任务清单-20260318.md](./系统执行任务清单-20260318.md)。

## 1. 当前系统状态

从整个系统看，当前仓库已经完成了三件重要的底层工作：

1. 主运行链路已经打通，paper trading 能稳定产出 daily_events、pipeline_timings 和 session_summary。
2. 主要执行层失真已经基本修掉，包括假价格 sizing、流动性单位错误、最小手数兼容、existing position 透传，以及默认 exit path 缺失。
3. 历史 edge 样本侧已经完成一轮收口，当前 benchmark 固定为三条，机制样本、conflict 样本和观察位也已分层清楚。

但系统级瓶颈也已经很明确：

1. 新的 clean edge 样本仍然稀缺。
2. 真实 paper-trading 仍存在低利用率、低多样性和单票质量不稳的问题。
3. 当前工作的主矛盾已经从“执行链路是否可信”转为“信号质量、持仓生命周期和组合构造是否可信”。

## 2. 总体目标

后续工作不应再以“让系统跑起来”为目标，而应转向下面三个系统级目标：

1. 建立可信的研究闭环：新样本、新规则、新结果都能被稳定归档、比较和复核。
2. 提高策略有效性：不是单纯增加成交，而是提升候选质量、持仓质量和组合质量。
3. 准备中期验证基础：为更长窗口、更高频率的 paper trading 验证打基础，而不是立刻转向实盘部署。

## 3. 优先级最高的四条主线

### 主线 A：研究治理与证据系统

这是当前最应该继续推进的主线，因为它决定后续所有改动是否可比较。

要做的事：

1. 把现有历史 edge 体系固定为一套正式研究协议，核心入口是 [docs/zh-cn/analysis/historical-edge-overview-home-20260318.md](docs/zh-cn/analysis/historical-edge-overview-home-20260318.md)、[docs/zh-cn/analysis/historical-edge-handoff-note-20260318.md](docs/zh-cn/analysis/historical-edge-handoff-note-20260318.md) 和 [docs/zh-cn/analysis/historical-edge-refresh-protocol-20260318.md](docs/zh-cn/analysis/historical-edge-refresh-protocol-20260318.md)。
2. 给后续每一次长窗口 replay 固定输出同一组比较字段，至少包含收益、回撤、利用率、单票集中度、Layer B 到成交的漏斗、主要 blocker 和主要负向 agent。
3. 建立一份统一的 validation scoreboard，把 benchmark 守住情况、样本扩库情况和 paper-trading 长窗口结果放在同一张表里。

完成标志：

1. 新一轮结果出来后，不再需要临时拼接文档才能判断好坏。
2. 任意一次规则改动都能和前一基线做同口径比较。

### 主线 B：候选生成与 edge 库扩展

这条线仍然重要，但要继续坚持“只读优先、证据先行”。

要做的事：

1. 继续按 [docs/zh-cn/analysis/historical-edge-triage-decision-tree-20260318.md](docs/zh-cn/analysis/historical-edge-triage-decision-tree-20260318.md) 和 [docs/zh-cn/analysis/historical-edge-new-candidate-triage-checklist-20260318.md](docs/zh-cn/analysis/historical-edge-new-candidate-triage-checklist-20260318.md) 被动吸收新样本。
2. 扩大观察窗口时，优先做历史 reports 扫描、targeted replay 对照和 fixed-artifact counterfactual，不做无证据的全局规则放松。
3. 重点研究为什么系统长期只有少数 ticker 能穿透到 watchlist 或 execution，尤其是 300724、603993 和被 suppress 的近端样本之间的结构差异。

完成标志：

1. 出现新的 clean near-threshold non-conflict 样本，或者明确确认当前阶段确实没有。
2. 对现有机制样本和 conflict 样本的分类不再频繁反复。

### 主线 C：持仓生命周期与组合构造

这是当前系统最可能带来真实提升的主线。

要做的事：

1. 继续研究 re-entry 质量，而不是单独研究 re-entry 是否触发。重点是 stop 后多久重进、重进时信号是否改善、重进后收益质量是否更好。
2. 继续审查 exit 体系，尤其是 300724 这类剩余主要亏损源，确认 hard stop、profit retrace、time stop、cooldown 的组合是否合理。
3. 单独建立 capital deployment 与 concentration 诊断，把平均利用率、峰值利用率、单票占比、重复加仓频率和持仓静态化问题放进同一份分析里。
4. 在不放松全局风控的前提下，优先研究组合构造层的小步改进，例如更稳的分层执行比例、重复加仓限制、持仓衰减逻辑，而不是直接改 Layer C 总闸门。

完成标志：

1. 长窗口验证里不再只依赖一两只票解释结果。
2. 利用率、集中度和收益质量能同时被观察，而不是只追求成交数。

### 主线 D：数据、因子与 agent 解释层

这条线的目标不是再加 agent，而是让当前 agent 输出更可解释、更可对照。

要做的事：

1. 持续核对 A 股数据链路中的单位、价格、成交额、流动性和交易约束字段，避免再次出现执行层假信号。
2. 针对长期主导 suppress 的负向 agent，建立更稳定的 attribution 视图，回答“谁在压制候选、为什么压制、在什么场景下压制是正确的”。
3. 补强因子语义的研究文档，把 profitability cliff、mean-reversion 中性稀释、investor bearish veto 这些已知模式整理成统一 taxonomy。
4. 对 LLM 输出漂移继续保持警惕，后续小规则 AB 验证优先依赖 fixed-artifact 分析，不轻易用 fresh replay 直接比较因果。

完成标志：

1. 负向 veto 的来源更透明。
2. 新样本被归类为机制、conflict 或 benchmark 时，有更短的解释路径。

## 4. 第二优先级的两条支撑线

### 支撑线 E：运行与观测

要做的事：

1. 固定长窗口 replay 的运行计划和产物归档方式。
2. 统一 session_summary 的关键指标定义，减少人工二次计算。
3. 如有必要，再补一层可视化或汇总脚本，把 funnel、PnL、utilization、blocker 合成单页摘要。

这条线的意义是降低每次验证的人工成本，而不是改变策略本身。

### 支撑线 F：Web 与产品表面

当前不应把它当作主战场，但也不应完全忽略。

要做的事：

1. 让前端或后端至少能消费核心 paper-trading artifacts。
2. 优先展示研究和验证结果，而不是做实盘风格的展示层。
3. 如果后续要支持团队协作，先做 artifacts 浏览、运行记录和对比视图，而不是做复杂交互。

## 5. 当前阶段的明确非目标

下面这些事短期内都不应成为主线：

1. 不做实盘部署准备。
2. 不做无新证据支撑的全局 Layer C、watchlist、avoid 放松实验。
3. 不把 UI 美化或工程重构放到策略验证前面。
4. 不为了增加成交数而牺牲 benchmark 边界和现有样本口径。

## 6. 建议的阶段顺序

### 阶段 1：把验证协议彻底固定

目标：先让每一次 replay 都变成同口径、可比较的研究事件。

建议输出：

1. validation scoreboard
2. 统一长窗口 replay 摘要模板
3. 历史 edge refresh protocol 的第一次实战使用记录

### 阶段 2：集中攻克组合质量问题

目标：从“能交易”走向“交易质量可解释”。

建议输出：

1. re-entry 质量分析
2. capital deployment 与 concentration 分析
3. 剩余主要亏损票的 lifecycle 复盘

### 阶段 3：等待或制造更高质量研究样本

这里的“制造”不是放松规则，而是扩大观测与对照维度。

建议输出：

1. 新的历史 edge 候选补证
2. suppress 样本与 mechanism 样本的统一 taxonomy
3. 更长窗口 paper-trading 验证结论

## 7. 如果现在只做三件事

如果要把后续工作压到最少，我建议只做这三件：

1. 先做 validation scoreboard，把系统结果统一成一个比较面板。
2. 再做 capital deployment 与 concentration 专项，确认系统当前到底是“没机会”还是“有机会但配错仓”。
3. 最后继续被动扩 historical edge 库，等待新的 clean 一手证据，而不是提前改全局规则。

## 8. 一句话路线判断

从整个系统看，下一阶段不该再围绕“把链路跑通”做工作，而该围绕“让研究结果可信、让组合行为可解释、让新样本进入有纪律”来推进。
