# BTST 复现影子 Split 摘要 2026-04-01

文档日期：2026 年 4 月 1 日  
适用对象：需要快速确认 BTST 当前 recurring shadow 执行口径、治理分工和复跑入口的研究员、负责人、开发者、AI 助手。

## 1. 一句话结论

截至 2026-04-01，BTST 当前 recurring shadow 的正式 split 已固定为：`300113 = close-continuation shadow candidate`，`600821 = intraday control`。

这意味着：

1. 不能再把旧 `002015` 当成当前 close-candidate 口径。
2. 不能把 `600821` 的 intraday upside 误写成 close continuation 规则。
3. 若要继续推进 recurring shadow，应优先复用 `300113` close bundle，而不是手工拼 release / outcome / pair comparison 脚本链。

## 2. 当前证据边界

当前口径来自以下最新产物：

1. `data/reports/p4_shadow_lane_priority_board_20260401.json`
2. `data/reports/p6_recurring_shadow_runbook_20260401.json`
3. `data/reports/btst_recurring_shadow_close_bundle_300113_20260401.json`
4. `data/reports/p5_btst_rollout_governance_board_20260401.json`
5. `data/reports/btst_governance_synthesis_latest.json`
6. `data/reports/btst_governance_validation_latest.json`

当前严格结论是：

1. `300113` 已经表现出更强的 close continuation 倾向。
2. `600821` 更适合作为 intraday 主样本 / control 样本。
3. 这条 recurring shadow lane 仍然缺第二个独立窗口，因此当前状态仍是 shadow validation prep，而不是默认升级候选。

## 3. 为什么 close 候选已经从 002015 切到 300113

最新 close bundle 结果已经把角色分工重新收紧：

1. `300113` 的 2 个目标样本都可 `rejected -> near_miss`，且 `changed_non_target_case_count=0`。
2. `300113` 的 `next_high_return_mean=0.0527`、`next_close_return_mean=0.0214`、`next_close_positive_rate=1.0`。
3. `600821` 虽然也能 recurring release，但更像 intraday upside 样本，`next_close_positive_rate` 明显弱于 `300113`。

因此当前最合理的治理写法是：

1. `300113` 代表 close-candidate。
2. `600821` 代表 intraday-control。
3. 旧 `002015` 只保留为历史研究语境，不再作为当前执行口径。

## 4. 当前应该怎么执行

若只是要读当前结论：

1. 看 `p6_recurring_shadow_runbook_20260401`。
2. 看 `btst_recurring_shadow_close_bundle_300113_20260401`。
3. 看 `p5_btst_rollout_governance_board_20260401`。

若要复跑当前 close-candidate 车道：

```bash
./.venv/bin/python scripts/run_btst_recurring_shadow_close_bundle.py \
  --report-dir data/reports/<report_dir> \
  --recurring-frontier-report data/reports/short_trade_boundary_recurring_frontier_cases_<artifact>.json \
  --outcome-report data/reports/pre_layer_short_trade_outcomes_600821_300113_<artifact>.json \
  --intraday-control-outcomes-report data/reports/recurring_frontier_ticker_release_outcomes_600821_<artifact>.json \
  --close-candidate-ticker 300113 \
  --intraday-control-ticker 600821 \
  --summary-json data/reports/btst_recurring_shadow_close_bundle_300113_<date>.json \
  --summary-md data/reports/btst_recurring_shadow_close_bundle_300113_<date>.md
```

若要把结果回接治理链：

```bash
./.venv/bin/python scripts/analyze_btst_recurring_shadow_runbook.py \
  --candidate-report data/reports/multi_window_short_trade_role_candidates_<date>.json \
  --recurring-transition-report data/reports/recurring_frontier_transition_candidates_all_windows_<date>.json \
  --recurring-close-bundle data/reports/btst_recurring_shadow_close_bundle_300113_<date>.json \
  --output-json data/reports/p6_recurring_shadow_runbook_<date>.json \
  --output-md data/reports/p6_recurring_shadow_runbook_<date>.md

./.venv/bin/python scripts/analyze_btst_rollout_governance_board.py \
  --recurring-shadow-runbook data/reports/p6_recurring_shadow_runbook_<date>.json \
  --recurring-close-bundle data/reports/btst_recurring_shadow_close_bundle_300113_<date>.json \
  --output-json data/reports/p5_btst_rollout_governance_board_<date>.json \
  --output-md data/reports/p5_btst_rollout_governance_board_<date>.md
```

## 5. 当前不该怎么写

下面三种写法现在都应视为过时：

1. 把 `002015` 写成当前 recurring close-candidate。
2. 把 `600821` 和 `300113` 合写成同一条 recurring shadow 规则。
3. 继续用手工 release/outcome/pair comparison 拼接来替代 close bundle。

## 6. 当前最重要的未完成项

当前真正缺的不是新规则，而是新窗口证据：

1. `300113` 仍缺第二个独立窗口来确认 close continuation 稳定性。
2. `600821` 仍缺第二个独立窗口来确认 intraday control 稳定性。
3. 在新增独立窗口出现前，这条 recurring shadow lane 仍然只应停留在 shadow validation prep。
