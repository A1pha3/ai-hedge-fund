## 管理视角里程碑版

当前结论先定性：ai-hedge-fund-fork 现在是“可评审、可继续验证”，不是“可直接以收益稳定为前提进入生产”。原因很明确：P1 在 docs/zh-cn/analysis/layer-b-p1-pr-summary-20260316.md 里已经完成代码落地、执行层测试和最小 live replay，但样本覆盖、长窗口稳定性、外部数据稳定性和仿真盘执行闭环都还没补齐。

1. M1 基线确认。锁定当前默认参数、P1 改动、证据链和残余风险，统一团队口径。通过标准不是“确认能稳定盈利”，而是“确认现在到底验证到了哪里、哪里还没验证”。输入以 docs/zh-cn/analysis/layer-b-p1-pr-summary-20260316.md、docs/zh-cn/analysis/layer-b-rule-variant-validation-20260312.md、docs/zh-cn/analysis/pipeline-funnel-scan-202602-window-20260312.md 为准。
2. M2 回归放行。关键自动化测试和长窗口复验通过，确认当前默认参数没有明显回归、没有收益分布或交易漏斗的异常漂移。通过标准是“代码与研究结论一致”，不是“收益已经足够高”。
3. M3 补证放行。完成多样本 targeted replay 与外部数据健康检查，确认边缘样本和结构性负样本的边界仍然稳定，确认 AKShare、Tushare、LLM provider 足以支持连续运行。
4. M4 仿真盘就绪。补出纸面交易闭环，能够每天稳定地产生计划、仿真成交、组合快照、未成交原因和收益归因，而不是依赖人工临时拼装。
5. M5 仿真盘放行。运行 10 到 20 个交易日纸面交易，确认执行稳定、收益与回撤可解释、没有阻断性故障，再决定是否进入下一阶段。
6. M6 真实资金立项。只有 M1-M5 全部通过，才讨论小资金真实验证。这个不属于当前阶段执行范围。

这套管理版计划的核心是把“是否继续推进”拆成可评审门槛，而不是提前给出“已经可以上线”的结论。

## 工程执行版

工程执行上，推荐按依赖顺序拆成 9 个任务组，只有其中 3 组可以并行。

1. Task Group A，基线锁定。先整理 docs/zh-cn/analysis/layer-b-p1-pr-summary-20260316.md、docs/zh-cn/analysis/layer-b-rule-variant-validation-20260312.md、docs/zh-cn/analysis/pipeline-funnel-scan-202602-window-20260312.md、docs/zh-cn/analysis/ab-walk-forward-runtime-analysis-20260308.md 的关键结论，冻结当前参数与评审口径。这个任务阻塞全部后续工作。
2. Task Group B，自动化回归。跑 tests/execution/test_phase4_execution.py、tests/backtesting/test_pipeline_mode.py、tests/backtesting/test_compare.py、tests/backtesting/test_rule_variant_compare.py。如果失败，要把问题归类成代码缺陷、测试脆弱、外部依赖波动三类。
3. Task Group C，长窗口复验。基于 src/backtesting/compare.py 跑完整窗口 walk-forward / A-B 对比，输出收益、回撤、交易机会、漏斗分布和 timings，验证当前参数是否仍然是“保守稳定”而非“偶然命中”。
4. Task Group D，样本补证。复用 scripts/run_live_replay_600519_p1.sh 和 scripts/replay_layer_c_agent_contributors.py，扩充至少三类样本：高置信通过、边缘通过、结构性负样本，每类至少两个交易日。
5. Task Group E，数据健康检查。对 AKShare、Tushare、LLM provider 建立最小观测项：成功率、平均时延、超时、重试、结构化输出失败率。这个结果必须在进入仿真盘前完成。
6. Task Group F，仿真盘运行面设计。不要重写策略逻辑，直接复用 src/execution/daily_pipeline.py、src/execution/models.py、src/backtesting/engine.py。要补的是运行入口、落盘产物、组合快照、未成交原因和收益归因。
7. Task Group G，仿真盘测试补齐。以 tests/backtesting/test_pipeline_mode.py 和 tests/execution/test_phase4_execution.py 为模板，补上仿真盘入口与日志留痕测试。
8. Task Group H，纸面交易观察。跑 10 到 20 个交易日，固定输出候选池规模、fast/precise 进入数、watchlist 通过数、仿真下单数、未成交原因、组合暴露、单日收益、累计收益、最大回撤、数据错误率、LLM 错误率。
9. Task Group I，放行评审。合并 B/C/D/E/H 的结果，只给出两种结论：允许继续到下一阶段，或回到前序修正。不建议使用“基本可以上线”这种模糊口径。

并行关系很清楚：C、D、E 可以并行；F 必须等 B/C/D/E；G 等 F；H 等 F/G；I 等 H。角色分工上，策略研究更适合负责 A/C/D，平台或基础设施更适合负责 E/F，测试负责人负责 B/G，项目 owner 最终做 I 的 go/no-go 决策。

## 评审结论

如果你现在要开评审会，我建议会议结论不要写“准备去生产测试收益”，而写成下面这句更准确：

当前 ai-hedge-fund-fork 已完成 P1 保守校准与最小补证，具备进入仿真盘前验证阶段的条件，但尚不具备直接以真实资金验证稳定收益的放行依据。
