## Goal

为 ai-hedge-fund-fork 制定一份可评审、可执行、可继续 refinement 的机构化多策略验证计划，用于回答下面这个核心问题：

当前系统是否已经具备进入仿真盘验证阶段的条件，以及在什么前提下才有资格讨论真实资金验证。

## Current Position

先定性当前状态：ai-hedge-fund-fork 现在是“可评审、可继续验证”，不是“可直接以收益稳定为前提进入生产”。

原因如下：

1. P1 在 docs/zh-cn/analysis/layer-b-p1-pr-summary-20260316.md 中已经完成代码落地、执行层测试和最小 live replay。
2. 当前证据仍然偏集中在 Layer C + watchlist 的最小保守校准。
3. 样本覆盖、长窗口稳定性、外部数据稳定性和仿真盘执行闭环都还没有补齐。
4. 当前仓库有 pipeline/backtesting 骨架，但没有一个清晰、独立、可长期运行的纸面交易入口。

## Planning Principles

1. 不把反事实或边界实验结果直接当成上线依据。
2. 不把“可评审”误写成“可生产”。
3. 先补证据链，再谈收益稳定性。
4. 先做仿真盘，再讨论真实资金。
5. 尽量复用现有 pipeline、ExecutionPlan、backtesting 抽象，不重写核心策略逻辑。

## Inputs

制定和评审本计划时，优先以下列材料为基线：

1. docs/zh-cn/analysis/layer-b-p1-pr-summary-20260316.md
2. docs/zh-cn/analysis/layer-b-rule-variant-validation-20260312.md
3. docs/zh-cn/analysis/pipeline-funnel-scan-202602-window-20260312.md
4. docs/zh-cn/analysis/ab-walk-forward-runtime-analysis-20260308.md
5. src/execution/daily_pipeline.py
6. src/execution/models.py
7. src/execution/layer_c_aggregator.py
8. src/backtesting/engine.py
9. src/backtesting/compare.py
10. scripts/run_live_replay_600519_p1.sh
11. scripts/replay_layer_c_agent_contributors.py
12. tests/execution/test_phase4_execution.py
13. tests/backtesting/test_pipeline_mode.py
14. tests/backtesting/test_compare.py
15. tests/backtesting/test_rule_variant_compare.py

## Management Milestones

### M1 基线确认

目标：锁定当前默认参数、P1 改动、证据链和残余风险，统一团队口径。

通过标准：不是“确认能稳定盈利”，而是“确认现在验证到了哪里、哪里还没验证”。

输出物：一页状态摘要，明确 included scope、excluded scope、当前残余风险。

### M2 回归放行

目标：确认当前默认参数没有明显代码回归，也没有收益分布或交易漏斗的异常漂移。

通过标准：代码表现与既有研究结论一致，而不是收益已经足够高。

输出物：关键测试记录、核心指标表、异常项列表。

### M3 补证放行

目标：完成多样本 targeted replay 与外部数据健康检查。

通过标准：边缘样本与结构性负样本边界仍然稳定，AKShare、Tushare、LLM provider 可以支持连续运行。

输出物：replay 汇总文档、provider health 摘要。

### M4 仿真盘就绪

目标：补出纸面交易闭环，能够每天稳定地产生计划、仿真成交、组合快照、未成交原因和收益归因。

通过标准：不再依赖人工临时拼装验证链。

输出物：运行说明、产物清单、最小测试覆盖记录。

### M5 仿真盘放行

目标：完成 10 到 20 个交易日纸面交易观察。

通过标准：执行稳定、收益与回撤可解释、无阻断性故障。

输出物：观察期日报或周报、go/no-go 结论。

### M6 真实资金立项

目标：只有 M1-M5 全部通过后，才讨论小资金真实验证。

说明：这个里程碑不属于当前阶段执行范围。

## Engineering Work Plan

### Task Group A 基线锁定

整理上述分析文档的关键结论，冻结当前参数与评审口径。

依赖：无。

阻塞关系：阻塞全部后续工作。

### Task Group B 自动化回归

运行以下测试：

1. tests/execution/test_phase4_execution.py
2. tests/backtesting/test_pipeline_mode.py
3. tests/backtesting/test_compare.py
4. tests/backtesting/test_rule_variant_compare.py

失败分类：

1. 代码缺陷
2. 测试脆弱
3. 外部依赖波动

依赖：A。

### Task Group C 长窗口复验

基于 src/backtesting/compare.py 跑完整窗口 walk-forward / A-B 对比。

重点输出：收益、回撤、交易机会、漏斗分布、timings。

目标：验证当前参数仍然是“保守稳定”，而不是“偶然命中”。

依赖：B。

### Task Group D 样本补证

复用 scripts/run_live_replay_600519_p1.sh 和 scripts/replay_layer_c_agent_contributors.py，扩充至少三类样本：

1. 高置信通过
2. 边缘通过
3. 结构性负样本

每类至少两个交易日。

依赖：A。

### Task Group E 数据健康检查

对以下链路建立最小观测项：

1. AKShare
2. Tushare
3. LLM provider

最小指标：

1. 成功率
2. 平均时延
3. 超时
4. 重试
5. 结构化输出失败率

依赖：A。

### Task Group F 仿真盘运行面设计

直接复用：

1. src/execution/daily_pipeline.py
2. src/execution/models.py
3. src/backtesting/engine.py

要补的不是策略逻辑，而是：

1. 运行入口
2. 落盘产物
3. 组合快照
4. 未成交原因
5. 收益归因

依赖：B、C、D、E。

### Task Group G 仿真盘测试补齐

以 tests/backtesting/test_pipeline_mode.py 和 tests/execution/test_phase4_execution.py 为模板，补上仿真盘入口与日志留痕测试。

依赖：F。

### Task Group H 纸面交易观察

运行 10 到 20 个交易日，固定输出：

1. 候选池规模
2. fast/precise 进入数
3. watchlist 通过数
4. 仿真下单数
5. 未成交原因
6. 组合暴露
7. 单日收益
8. 累计收益
9. 最大回撤
10. 数据错误率
11. LLM 错误率

依赖：F、G。

### Task Group I 放行评审

合并 B、C、D、E、H 的结果，只给出两种结论：

1. 允许继续到下一阶段
2. 回到前序修正

不建议使用“基本可以上线”这种模糊口径。

依赖：H。

## Parallelization And Ownership

并行关系：

1. C、D、E 可以并行
2. F 必须等待 B、C、D、E
3. G 等待 F
4. H 等待 F、G
5. I 等待 H

角色建议：

1. 策略研究负责人：A、C、D
2. 平台或基础设施负责人：E、F
3. 测试负责人：B、G
4. 项目 owner：I 的 go/no-go 决策

## Review Gates

只有以下条件同时满足，才允许从“研究补证阶段”进入“仿真盘观察阶段”：

1. 关键自动化测试通过
2. 长窗口复验没有出现显著漂移
3. 多样本 replay 没有误放行结构性负样本
4. 数据链路不存在阻断性波动

只有以下条件同时满足，才允许从“仿真盘观察阶段”进入“真实资金讨论阶段”：

1. 10 到 20 个交易日纸面交易稳定运行
2. 收益与回撤可解释
3. 没有阻断性故障
4. 没有发现 watchlist 0.20 阈值导致的系统性误放大

## Recommended Review Statement

评审结论建议使用下面这句，不建议改写成“准备去生产测试收益”：

当前 ai-hedge-fund-fork 已完成 P1 保守校准与最小补证，具备进入仿真盘前验证阶段的条件，但尚不具备直接以真实资金验证稳定收益的放行依据。

## Expected Use

这份文档可用于三种场景：

1. 管理层评审当前是否继续推进
2. 工程团队拆分执行任务与依赖
3. 后续继续 refinement 为更正式的项目计划、评审稿或 agent prompt
