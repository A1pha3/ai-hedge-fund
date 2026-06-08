# 4. 模拟交易 (Paper Trading)

> 本节对应主文档 §4,包含运行时系统、报告系统。

## 4.1 运行时系统

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 日度自动运行 | ✅ | `src/paper_trading/runtime.py` — 完整的日度运行框架 |
| 2 | JSONL 记录器 | ✅ | 所有决策和结果持久化 |
| 3 | 优化 Profile 解析 | ✅ | `src/paper_trading/optimized_profile_resolution.py` |
| 4 | 冻结回放 | ✅ | `src/paper_trading/frozen_replay.py` — 历史执行计划回放 |
| 5 | LLM 可观测性 | ✅ | 模型调用链路追踪和性能统计 |

## 4.2 报告系统

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 日度交易简报 | ✅ | `src/paper_trading/_btst_reporting/` — 完整的日报系统 |
| 2 | 盘前执行卡 | ✅ | `btst_premarket_markdown_helpers.py` |
| 3 | 开盘观察卡 | ✅ | `btst_opening_watch_markdown_helpers.py` |
| 4 | 优先级看板 | ✅ | `btst_priority_board_markdown_helpers.py` |
| 5 | 催化剂主题报告 | ✅ | `catalyst_render_helpers.py` |
| 6 | Shadow 影子池报告 | ✅ | `btst_trade_brief_shadow_markdown_helpers.py` |
| 7 | 收益复盘 (Payoff Review) | ✅ | `payoff_review_lane.py` |
| 8 | 历史先验报告 | ✅ | `historical_prior.py` |

---

**相关章节**: [2. 执行系统](./execution-system.md) | [3. 回测与验证](./backtesting.md)
