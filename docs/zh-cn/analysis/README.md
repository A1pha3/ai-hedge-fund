# AI 对冲基金分析报告

## 分析概览

- **分析日期**: 2025年
- **分析股票**: AAPL (苹果), MSFT (微软), NVDA (英伟达)
- **使用模型**: MiniMax-M2.5
- **分析师数量**: 16位 AI 分析师

## 专题分析

1. [A/B Walk-Forward 测试流程、设计目的、运行耗时与优化过程记录](./ab-walk-forward-runtime-analysis-20260308.md)
2. [Pipeline Fast / Precise 两阶段执行与去重优化说明](./pipeline-fast-precise-routing-optimization-20260311.md)
3. [Analyst 批次 Barrier 优化方案说明](./analyst-batch-barrier-optimization-options-20260311.md)
4. [默认 Workflow Rolling Scheduler 设计文档](./default-workflow-rolling-scheduler-design-20260312.md)
5. [Layer B 最小规则变更提案](./layer-b-minimal-rule-change-proposal-20260312.md)
6. [M2.5 与 M2.7 的 benchmark / bridge 对照摘要](./m2-5-vs-m2-7-bridge-summary-20260319.md)
7. [W1 MiniMax-M2.7 live / frozen 验证纪要](./w1_minimax_m2_7_live_frozen_validation_20260319.md)

当前最新性能结论：在现有 batch/barrier 工作流下，已验证的最佳 5 日配置是 MiniMax=5 + Doubao=4，并通过 allowlist 将 Zhipu 排除出 analyst 并行波次；对应 5 日 wall-clock 为 933.64 秒。

## 目录

1. [分析师介绍](./analysts-overview.md)
2. [AAPL 分析详情](./aapl-analysis.md)
3. [MSFT 分析详情](./msft-analysis.md)
4. [NVDA 分析详情](./nvda-analysis.md)
5. [投资组合决策](./portfolio-decision.md)
6. [分析师推理详情](./reasoning/)

## 快速结果

| 股票 | 操作 | 置信度 | 看涨 | 看跌 | 中性 |
|------|------|--------|------|------|------|
| AAPL | HOLD | 100% | 1 | 5 | 10 |
| MSFT | HOLD | 100% | 1 | 5 | 10 |
| NVDA | HOLD | 100% | 4 | 3 | 9 |

**总体策略**: 由于数据限制（缺少完整的估值数据），系统建议 **HOLD（持有）**，暂不建议新买入或卖出。
