# BTST 5D/+15% runner 与 payoff 目标重对齐方案（2026-05-28）

## 结论先说

当前主矛盾不是票太少，而是正式 `selected` 层仍在优化短 continuation。下一轮应先做 formal-source 收缩，再做 payoff-first runner recall 复审。

## 最新 artifact 化验证

这轮已经把 analyzer 的输出正式固化成两个 JSON artifact：

- `data/reports/btst_runner_payoff_realignment_20260518_20260522.json`
- `data/reports/btst_runner_payoff_realignment_20260506_20260522.json`

对应结论没有变化，反而更稳了：

1. **周度窗口 `2026-05-18 ~ 2026-05-22`**
   - `primary_problem = formal_selected_target_misalignment`
   - `selected_hit_rate_15pct = 0.2000`
   - `near_miss_hit_rate_15pct = 0.4507`
   - `watchlist_filter_diagnostics_false_negatives = 6`
   - `formal_source_drag_count = 2`
   - `recommendation = staged_formal_shrink_plus_runner_recall`
2. **扩窗 `2026-05-06 ~ 2026-05-22`**
   - `primary_problem = formal_selected_target_misalignment`
   - `selected_hit_rate_15pct = 0.3077`
   - `near_miss_hit_rate_15pct = 0.3564`
   - `watchlist_filter_diagnostics_false_negatives = 13`
   - `formal_source_drag_count = 1`
   - `recommendation = staged_formal_shrink_plus_runner_recall`

这组 artifact 化结果说明两件事：

- 这不是单周偶发噪音，扩窗后主矛盾仍然没变；
- 下一阶段最值得做的，仍然是 **先收紧 formal-source，再把 diagnostics delayed-runner 放进 payoff-first recall 复审层**。

再往前走一步，基于上面这两组窗口结果送进 `compare_btst_runner_payoff_realignment_windows()` 之后，当前 source-lane verdict 也已经清楚了：

- `layer_c_watchlist_policy = stable_formal_shrink_lane`
- `short_trade_boundary_policy = conditional_only`

也就是说，下一阶段不应该把 `short_trade_boundary` 直接写成全局收紧，而应该先把 **`layer_c_watchlist` 作为稳定 formal shrink lane** 固定下来，再观察 `short_trade_boundary` 是否只在局部窗口里需要收紧。
