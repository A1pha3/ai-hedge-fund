# Pipeline 业务漏斗可观测性补充说明

文档日期：2026 年 3 月 12 日  
文档状态：已实现并通过聚焦回归  
适用范围：默认 CLI / backtester pipeline 路径  
不包含范围：Web / API 自定义图路径

## 1. 为什么这一步优先

当前阶段的主问题不是继续压缩 provider wall-clock，而是解释为什么稳定 20 日回测里交易覆盖度很低。

已有事实说明：

1. rolling scheduler 的 5 日试验通过，但 20 日试验失败，代码已经回退。
2. 当前仓库已恢复到稳定 batch workflow，应以稳定版本为准继续推进。
3. 稳定结果没有明显收益退化，但交易非常少，说明主矛盾转到业务漏斗收缩，而不是执行结构本身。

因此，本轮工作目标是给默认 pipeline 增加最小侵入的业务漏斗诊断，先回答“股票在哪一层被筛掉、主要因为何种原因被筛掉”，再决定是否要做阈值、权重或策略层面的业务调整。

## 2. 本次新增的诊断输出

本次实现把结构化漏斗诊断挂在每日 ExecutionPlan 的 risk_metrics.funnel_diagnostics 下，并同步写入 backtester timing log 的 current_plan / previous_plan。

当前输出包含：

1. Layer A 候选数
2. Layer B 通过数
3. Layer C 通过数
4. watchlist 数
5. buy order 数
6. sell order 数
7. 分阶段过滤原因分类与逐票结构化明细

其中重点过滤分类包括：

1. Layer B
原因码：below_fast_score_threshold、high_pool_truncated_by_max_size

2. watchlist
原因码：decision_avoid、score_final_below_watchlist_score_threshold

3. buy orders
原因码：no_available_cash、position_blocked_cash、position_blocked_liquidity、position_blocked_industry、position_blocked_single_name、position_blocked_vol、filtered_by_daily_trade_limit

4. sell orders
按 trigger_reason / level 聚合实际卖出信号来源，便于后续和退出链路联动排查

## 3. 实现边界

本次改动遵守以下边界：

1. 不修改默认 batch workflow 的结构。
2. 不重新尝试 lane-chain。
3. 不继续扩展 rolling scheduler。
4. 不触碰 Web / API 路径。
5. 临时运行态信息只进入 risk_metrics / timing log，不写入长期业务状态。

## 4. 业务价值

这一步不是直接提高收益，而是为后续业务判断建立观测基础。

有了这份漏斗诊断后，下一轮可以更准确地回答：

1. 交易少，主要是 Layer B 过严，还是 Layer C 冲突太多。
2. watchlist 能生成，但是否因为现金、行业额度、单日交易上限等执行约束被截断。
3. 卖单是否根本没有触发，还是触发后又在别的阶段被延后。

在没有这些漏斗证据之前，不建议直接调权重、调阈值或改 workflow 结构。

## 5. 验证结果

本次改动已完成聚焦回归：

1. execution 相关测试通过
2. pipeline mode 回测路径测试通过
3. 新增测试覆盖了结构化漏斗诊断输出、Layer C 计数透传，以及 timing log 中的诊断透出

回归命令：

使用项目虚拟环境执行 pytest tests/execution/test_phase4_execution.py tests/backtesting/test_pipeline_mode.py -q

结果：27 passed

## 6. 下一步建议

下一轮优先工作不是改调度，而是读取实际 20 日 timing log / execution plan 中的 funnel_diagnostics，按交易日汇总：

1. 哪个原因码出现频率最高
2. 哪些 ticker 反复卡在同一层
3. 601600 之外的候选票主要死在哪一层

完成这一步后，再决定是收紧还是放宽具体业务规则。