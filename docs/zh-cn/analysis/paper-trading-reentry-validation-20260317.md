# 2026-03-17 纸面交易验证结论：300724 防御性退出后回补拦截

## 结论摘要

- 本轮验证确认：`logic_stop_loss` 不是当前长窗口纸面交易劣化的主要根因。
- 真正的主要问题是：`300724` 在 `hard_stop_loss` 防御性退出后，于冷却结束不久以边缘分数再次回补，随后继续走弱。
- 已实现并验证的修复是：对防御性退出后的再入场增加确认窗口，在该窗口内要求更高的 `score_final` 才允许回补。
- 修复后的长窗口冻结回放已证明该规则实际命中目标路径：`300724` 在 `20260226` 的回补被成功拦下。

## 背景

验证窗口：`2026-02-02 .. 2026-03-04`

关键既有参数：

- `LOGIC_STOP_LOSS_SCORE_THRESHOLD = -0.20`
- `WATCHLIST_MIN_SCORE = 0.225`
- `STANDARD_EXECUTION_SCORE = 0.25`
- `HARD_STOP_LOSS_PCT = -0.06`

关键观察：

- `300724` 首次买入：`20260206`
- `300724` 首次卖出：`20260213`，原因为 `hard_stop_loss`
- 冷却结束后在 `20260226` 以 `score_final = 0.2250` 再次买入
- 后续持仓继续恶化，到窗口结束时仍拖累组合

因此，本轮没有继续下调 `logic_stop_loss` 阈值，而是优先处理“防御性退出后的低质量回补”。

## 实现内容

代码修改点：

- [ai-hedge-fund-fork/src/backtesting/engine.py](ai-hedge-fund-fork/src/backtesting/engine.py)
- [ai-hedge-fund-fork/src/execution/daily_pipeline.py](ai-hedge-fund-fork/src/execution/daily_pipeline.py)
- [ai-hedge-fund-fork/tests/execution/test_phase4_execution.py](ai-hedge-fund-fork/tests/execution/test_phase4_execution.py)
- [ai-hedge-fund-fork/tests/backtesting/test_pipeline_mode.py](ai-hedge-fund-fork/tests/backtesting/test_pipeline_mode.py)

本轮规则：

- 防御性退出后保留 `reentry_review_until`
- 在 `reentry_review_until` 之前，如果 `score_final < 0.25`，则阻止重新买入
- 失败原因记录为 `blocked_by_reentry_score_confirmation`

额外修复：

- 冻结回放最初直接复用历史 `current_plan.buy_orders`，会绕过新加的再入场过滤
- 已在 [ai-hedge-fund-fork/src/execution/daily_pipeline.py](ai-hedge-fund-fork/src/execution/daily_pipeline.py) 中修正：冻结回放仍复用历史 `watchlist` 与分数，但返回前会重新应用当前版本的买单过滤逻辑

## 验证结果

目标测试通过：

- `pytest tests/execution/test_phase4_execution.py tests/backtesting/test_pipeline_mode.py tests/backtesting/test_paper_trading_runtime.py -q`
- 结果：`58 passed, 2 warnings`

长窗口冻结回放产物：

- [ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_prod_validation_20260317/daily_events.jsonl](ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_prod_validation_20260317/daily_events.jsonl)
- [ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)
- [ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json](ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json)

目标路径验证：

- 原始基线中，`300724` 于 `20260226` 执行买入 `100` 股
- 修复后回放中，`20260226` 无买入动作
- 阻断原因：`blocked_by_reentry_score_confirmation`
- 当日分数：`0.2250`
- 要求分数：`0.25`

核心结果对比：

- 终值：`98747.4891 -> 99447.9922`
- Sharpe：`-3.0307 -> -1.7564`
- 最大回撤：`-1.8893% -> -1.8893%`，基本不变
- 执行订单数：`7 -> 6`
- 有成交交易日：`6 -> 5`
- 终盘持仓：去除 `300724`，仅保留 `601600`

## 对利用率与集中度的补充判断

本轮修复提升了结果质量，但没有同时解决组合利用率问题。

关键事实：

- `20260226` 原方案利用率约 `24.72%`，修复后约 `12.43%`
- `20260303` 原方案利用率约 `17.39%`，修复后约 `5.63%`
- `20260304` 原方案利用率约 `17.49%`，修复后约 `5.81%`

这说明修复的收益来自“去掉错误回补”，不是来自“找到更好的替代仓位”。

进一步排查 `prepared_plan.risk_metrics.funnel_diagnostics` 后可见：

- `20260225`、`20260226`、`20260302` 的 watchlist 基本只有 `300724`
- `300724` 被拦下之后，并没有第二个健康候选补位
- 近端落选者多数不是简单分数略低，而是 `decision_avoid`，且伴随 `bc_conflict = b_positive_c_strong_bearish`

代表性近端落选者：

- `20260225`：`000960`，`score_final = 0.1964`，`decision_avoid`
- `20260226`：`000960`，`score_final = 0.1893`，`decision_avoid`
- `20260303`：`300251`，`score_final = 0.1735`，`decision_avoid`
- `20260304`：`300775`，`score_final = 0.2215`，`decision_avoid`
- `20260304`：`600111`，`score_final = 0.2145`，`decision_avoid`

因此，下一阶段如果只放宽仓位计算、单票上限、日交易额上限，效果预期有限，因为根本问题发生在更前面的 `Layer C / watchlist / avoid` 抑制阶段。

## 当前建议

建议立即保留当前 re-entry 确认规则作为纸面交易基线，不再继续下调 `logic_stop_loss` 阈值。

后续优化优先级应为：

1. 优先研究 `Layer C + watchlist + avoid` 的候选供给问题，而不是先改仓位计算器
2. 在替代候选供给改善之前，不要把“利用率下降”误判为单纯仓位参数过紧
3. 后续任何利用率优化都应以“不重新引入 300724 这类低质量回补”为前提

## 当前基线结论

截至 `2026-03-17`，更稳妥的纸面交易默认基线应为：

- 保持 `LOGIC_STOP_LOSS_SCORE_THRESHOLD = -0.20`
- 保持本轮新增的防御性退出后再入场确认窗口
- 将后续研究重点转向候选供给与 `decision_avoid` 抑制，而不是继续争论是否要把 `logic_stop_loss` 改得更敏感