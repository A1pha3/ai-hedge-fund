# btst-trend-continuation-governed-rollout-2026-05-20

## 原理
- 这次工作的核心不是再发明一个新因子，而是把 Round 89 的**趋势延续修正分支**接上正式治理闭环：以 `trend_continuation_strength_v2` 作为基线，检查 `trend_continuation_strength_v3` 是否真的在多窗口 replay 中带来更强的 BTST T+1 优势。
- `trend_continuation_strength_v3` 当前的新增点主要是 `watchlist_filter_diagnostics_selected_only_shrink_*` 这一组收缩约束，理论目标是进一步清理正式 `selected` 交易面，让主交易候选更偏向高质量、可执行的趋势延续名字。
- 但治理口径要求它必须先在历史窗口里体现出**真实 runtime activation delta**，并拿到至少一部分正向 `execution_eligible` 证据，才允许进入更强的 rollout / skill 正式叙述。

## 本次验证结论
- 最新正式产物是 `data/reports/btst_trend_continuation_rollout_assessment.json` 与对应 Markdown，结论为 **`hold`**。
- 真实多窗口回放覆盖 `20` 个 `paper_trading_window` 报告目录，聚合结论为：
  - `keep_baseline_count = 0`
  - `variant_supports_t1_count = 0`
  - `mixed_count = 20`
  - `positive_window_count = 0`
  - `non_halt_execution_eligible_count = 0`
- 更关键的是，这次不是“v3 有轻微负贡献”，而是**20 个窗口都没有形成 runtime activation delta**：回放里反复出现 `profile_variant_without_runtime_activation_delta`，说明当前 v3 的新增约束没有在这些窗口里改变 `selected / near_miss / tradeable / execution_eligible` 的实际结果面。
- 这轮还额外确认并修复了一个 replay 证据偏差：部分 legacy `selection_target_replay_input.json` 的 top-level `rejected_entries` 会丢失 `candidate_source`，虽然同 ticker 的 stored selection target 仍保留了 `watchlist_filter_diagnostics`。修复后重刷验证，`watchlist_filter_diagnostics` 已重新进入 replay source 统计，但总体 verdict **仍然不变**，说明这次 `hold` 不是由 source 丢失误伤出来的。
- 修复后的窗口抽样也给出更具体的原因：例如 `paper_trading_window_20260323_20260326_btst_baseline_refresh` 中恢复出来的 `300394`、`300502` 两个 `watchlist_filter_diagnostics` 名字，在 `trend_continuation_strength_v2` 与 `v3` 下都仍是 `rejected`，而且 `selected_only_shrink_guard.applied = false`。其中 `300394` 的 `gap_to_near_miss` 仍约为 `0.0204`，`300502` 更远，说明它们根本没有进入 v3 这组 selected-only shrink 约束真正能改变结果的边界带。

## 提升效果与当前边界
- 本轮已经验证、并可以稳定复用的提升，是**治理质量提升**：
  - 现在仓库里有了 `trend_continuation_strength_v3` 的正式 rollout assessment；
  - `ai-hedge-fund-btst` skill 也会在描述优化 profile 是否可晋升时读取这份 assessment；
  - replay 分析现在会从 stored selection target 回填缺失的 top-level `candidate_source` / `candidate_reason_codes`，避免 legacy artifact 把 `watchlist_filter_diagnostics` 误记成 `unknown`；
  - 因此 skill 不会把一个“历史上看起来像增强版、但当前窗口里根本没有激活”的 profile 误写成已验证升级。
- 但就交易层面来说，本轮**没有得到可以支持 alpha 晋升的证据**：
  - 没有观察到 T+1 edge 支持窗口；
  - 没有观察到 execution-ready 的正向激活证据；
  - 即使在修复 replay source 偏差之后，真实 `watchlist_filter_diagnostics` 样本仍没有进入 shrink guard 的有效边界带；
  - 因此不能把 `trend_continuation_strength_v3` 写成已经提高了胜率或盈亏比的正式升级版。

## 如何验证
- 先运行多窗口回放验证：
  - `uv run python scripts/analyze_btst_multi_window_profile_validation.py --baseline-profile trend_continuation_strength_v2 --variant-profile trend_continuation_strength_v3 --output-json data/reports/btst_trend_continuation_strength_v3_multi_window_validation.json --output-md data/reports/btst_trend_continuation_strength_v3_multi_window_validation.md`
- 再运行治理 assessment：
  - `uv run python scripts/btst_trend_continuation_rollout_assessment.py --input-json data/reports/btst_trend_continuation_strength_v3_multi_window_validation.json --output-json data/reports/btst_trend_continuation_rollout_assessment.json --output-md data/reports/btst_trend_continuation_rollout_assessment.md`
- source 回填回归测试：
  - `uv run pytest tests/test_replay_selection_target_calibration_script.py::test_replay_selection_target_calibration_recovers_missing_rejected_entry_source_from_stored_target -q`
- 最新结论应能看到以下 blocker：
  - `no_window_supports_t1_edge`
  - `no_execution_eligible_activation_evidence`
  - `no_runtime_activation_delta`

## 如何使用
- 对运行时 / manifest 的含义：
  - 当前应继续把 `trend_continuation_strength_v2` 视为这条分支的默认基线；
  - 不应因为名字更“先进”就把 `trend_continuation_strength_v3` 发布为 ready manifest。
- 对 `ai-hedge-fund-btst` 的含义：
  - 当 skill 看到 `btst_trend_continuation_rollout_assessment.json` 为 `hold` 时，必须明确写出它仍处于治理阻塞态；
  - 如果当前 run artifacts 没有显示 `v3` 真正被采用，也不能把这份文档反推成“本次运行已经启用趋势延续升级版”。
- 对下一轮优化的启发：
  - 重点不该是继续包装 `v3` 的名字，而是找出为什么修复 source 以后，真实 `watchlist_filter_diagnostics` 样本仍然离 `selected` / `near_miss` 边界太远；
  - 更有价值的下一轮，不是继续给 `selected_only_shrink` 讲故事，而是研究：这批 watchlist-filter 名字是否应该改成 near-miss / rejected 边界治理，或者根本不该作为这条 profile 的主要优化对象；
  - 只有当新增收缩逻辑真的改变 tradeable / execution_eligible 结果面，并带来至少局部 T+1 提升窗口时，才值得进入下一轮 promotion 评审。
