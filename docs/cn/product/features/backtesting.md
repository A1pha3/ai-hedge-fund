# 3. 回测与验证

> 本节对应主文档 §3,包含回测引擎、性能指标。

## 3.1 回测引擎

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 连续回测引擎 | ✅ | `src/backtesting/engine.py` — 跨时间段的连续模拟 |
| 2 | 检查点保存/恢复 | ✅ | 断点续跑能力 |
| 3 | 待处理订单处理 | ✅ | 涨停排队模拟 |
| 4 | 基准对比 | ✅ | `src/backtesting/benchmarks.py` — 沪深 300 等基准对比 |
| 5 | Agent 模式回测 | ✅ | `src/backtesting/engine_agent_mode.py` — LLM Agent 参与的回测 |
| 6 | Walk-Forward 验证 | ✅ | `src/backtesting/walk_forward.py` — 滚动窗口前瞻验证 |
| 7 | 参数网格搜索 | ✅ | `src/backtesting/param_grid.py` |
| 8 | 策略变体对比 | ✅ | `src/backtesting/rule_variant_compare.py` |
| 9 | Profile 稳定性评估 | ✅ | 连续窗口非推广占比检测 |
| 10 | Promotion Gate | ✅ | `src/backtesting/promotion_gate.py` — 上线门槛控制 |

## 3.2 性能指标

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | Sharpe/Sortino 比率 | ✅ | `src/backtesting/metrics.py` |
| 2 | 最大回撤 | ✅ | 组合和单标的级别 |
| 3 | 胜率/盈亏比 | ✅ | 全面的交易统计 |
| 4 | 日度收益分析 | ✅ | 日频回报率计算 |

---

**相关章节**: [2. 执行系统](./execution-system.md) | [4. 模拟交易](./paper-trading.md) | [Web 端 P0-4 回测可视化](./web-app.md)
