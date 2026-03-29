# 前置短线 score frontier 下一轮先做什么：决策摘要

## 一句话结论

下一轮前置短线优化不需要再从 18 个 `short_trade_boundary` score-fail 样本里重新发散筛选。当前证据已经把优先级收敛成两层：统一 scorecard 下先做 `001309` 的 near-miss case-based promotion，再做 `2026-03-26 / 300383` 的 threshold-only case-based release；`600821` 与 `002015` 的 recurring frontier 审查继续后置为局部 baseline 验证。

## 为什么现在先做 001309

这轮新增的统一优先级 scorecard 与 case-based 直接对照，已经把“第一入口”从 `300383` 切换到 `001309`。关键原因有三点：

- `001309` 的 adjustment_cost 只有 `0.02`，低于 `300383` 的 `0.04`
- `001309` promotion 后 `next_close_return_mean=0.0414`，明显强于 `300383` 的 `0.0146`
- `001309` 有 `2` 个目标样本且 `next_close_positive_rate=1.0`，比 `300383` 的单样本证据更稳

对应的新落盘报告已经固定了这一点：

- `data/reports/short_trade_release_priority_scoreboard_20260329.{json,md}` 将 `001309` 排为 `priority_rank=1`，`300383` 排为 `priority_rank=2`
- `data/reports/case_based_short_trade_entry_pair_comparison_001309_vs_300383_20260329.{json,md}` 的 recommendation 明确为：`001309` 的 follow-through 更强，应优先继续推进
- `data/reports/case_based_short_trade_entry_readiness_20260329.{json,md}` 进一步把入口角色固定为：`001309=primary_controlled_follow_through`，`300383=secondary_shadow_entry`，`300620=control_only`
- `data/reports/case_based_short_trade_follow_through_runbook_20260329.{json,md}` 已把这三层进一步落成执行手册：`001309` 使用 `select_threshold=0.56` 作为主实验参数，并固定 `changed_non_target_case_count=0`、`next_close_return_mean>0`、`next_close_positive_rate>=0.75` 作为主 guardrails；`300383` 作为 `near_miss_threshold=0.42` 的 shadow entry；`300620` 保留为 intraday control

更重要的是，这个优先级切换并没有推翻 `300383` 的原有语义。它仍然是当前最干净的 threshold-only `rejected -> near_miss` release 样本，只是当 `001309` 的 near-miss promotion outcome 被正式纳入同一标尺后，`001309` 已经成为更低成本、close follow-through 更强的第一入口。

## 为什么 300383 仍然保留第二优先

这轮新补的定向 release 实验已经证明：

- 目标样本：`2026-03-26 / 300383`
- 调整方式：仅把 `near_miss_threshold` 从 `0.46 -> 0.42`
- 结果：`rejected -> near_miss`
- 变化范围：总共只改动 `1` 个样本，其余 `17` 个 rejected `short_trade_boundary` 样本完全不动

这使 `300383` 继续保持为当前前置短线 score frontier 路线上最干净的低成本 release 入口：它既不需要联动 penalty weight，也不会污染非目标样本。只是和 `001309` 相比，它当前仍是第二优先，而不是总优先级第一。

## 为什么下一层是 600821 和 002015

重复 ticker frontier 队列已经把 recurring score-fail 样本收敛到两只：

1. `600821`
   - 出现 `3` 次：`2026-03-23, 2026-03-25, 2026-03-26`
   - `baseline_score_mean = 0.3669`
   - `gap_to_near_miss_mean = 0.0931`
   - 最小 rescue cost = `0.10`
   - 模式：需要 `near_miss_threshold = 0.38`，并至少有一次要把 `stale_weight` 降到 `0.10`
2. `002015`
   - 出现 `3` 次：`2026-03-23, 2026-03-24, 2026-03-25`
   - `baseline_score_mean = 0.3615`
   - `gap_to_near_miss_mean = 0.0985`
   - 最小 rescue cost = `0.12`
   - 模式：同样需要 `near_miss_threshold = 0.38`，并把 `extension_weight` 降到 `0.04` 或 `0.02`

关键点是：它们都不是 threshold-only 样本。和 `300383` 不同，这两只票要进入 near-miss，必须开始碰 stale/extension penalty 联动，因此更适合作为第二层局部 frontier 审查，而不是第一步就进入默认 release。

不过，这层判断现在已经不再停留在“dossier 建议”上。新增的 ticker-level recurring release 实验已经证明：

- `600821` 的 3 个目标样本都可被各自 recurring row 推到 `near_miss`，且 `changed_non_target_case_count=0`
- `002015` 的 3 个目标样本也都可被各自 recurring row 推到 `near_miss`，且 `changed_non_target_case_count=0`

因此更精确的说法应是：`600821` 与 `002015` 现在都已经是可执行的 recurring release baseline，但仍然只是局部实验 baseline，而不是默认策略放行规则。

新补的 ticker role history 进一步把这个边界固定了下来：在更早的 `paper_trading_window_20260316_20260323_live_m2_7_20260323` 里，`600821` 与 `002015` 都还只是 `layer_b_pool_below_fast_score_threshold` 的旧 Layer B 池样本；它们只是在当前 `paper_trading_window_20260323_20260326_live_m2_7_dual_target_catalyst_floor_zero_validation_20260329` 窗口里，才首次连续变成 `short_trade_boundary_rejected` recurring ticker。

现在这层判断已经由正式 transition scanner 固化：`data/reports/recurring_frontier_transition_candidates_20260329.{json,md}` 把两只票都标成 `emergent_local_baseline`，而不是 `multi_window_stable`。随后又新增了从 `data/reports` 根目录自动发现历史窗口的能力，并在 `data/reports/recurring_frontier_transition_candidates_all_windows_20260329.md` 上对 `14` 个自动发现的 `paper_trading_window_*` 报告做了宽覆盖复核，结论仍然不变。更进一步的全局扫描 `data/reports/multi_window_short_trade_role_candidates_20260329.{json,md}` 还说明：当前自动发现窗口范围内一共只有 `4` 个满足“至少 2 个 short-trade trade_date”的候选，而且 `stable_candidate_count = 0`。其共同特征是：

- `previous_window_role = layer_b_pool_below_fast_score_threshold`
- `current_window_role_count = 3`
- `transition_locality = emergent_local_baseline`

换句话说，当前更准确的结论不是“它们已经跨窗口稳定”，而是“它们已在当前窗口内形成可执行 recurring baseline，但历史上尚未证明稳定复现”。即使把证据面扩到自动发现的 14 个历史窗口，这个判断也没有变化；而且从全局 ticker 扫描看，当前连一个 `multi_window_stable` short-trade ticker 都还不存在。下一步应继续扩大窗口验证，再决定是否升级成可复用 profile。

这轮全局扫描还有一个新增信息：除了 recurring frontier 里的 `600821` 与 `002015` 外，当前窗口里还出现了两个 near-miss 型 emergent baselines：`001309` 与 `300620`。它们都在 `20260323_20260326` 这一逻辑窗口内连续 3 次进入 `short_trade_boundary_near_miss`，但同样没有任何跨窗口稳定复现证据。

不过，这两只票现在已经不只是“旁证样本”。新补的 dossier 与 pair comparison 进一步把它们的当前窗口内部分工固定了下来：

- `001309`：`next_high_return_mean=0.0510`、`next_close_return_mean=0.0414`、`next_close_positive_rate=1.0`，应定义为 near-miss close-continuation 优先样本
- `300620`：`next_high_return_mean=0.0479`、`next_close_return_mean=-0.0014`、`next_close_positive_rate=0.5`，应定义为 near-miss intraday 对照样本

因此更准确的说法是：`001309` 与 `300620` 现在已经构成了一组 near-miss emergent baseline 对照，但仍然只是当前窗口内成立的局部模式，而不是新的默认 release profile。

这一层判断现在又向前推进了一步。新增的定向 near-miss release 实验已经证明：`001309` 的两个真实 near-miss 样本只需把 `select_threshold` 从 `0.58 -> 0.56`，就能实现 `2/2 near_miss -> selected`，且 `changed_non_target_case_count=0`；`300620` 若要达到同样结果，则需要把 `select_threshold` 进一步放到 `0.53`。随后补做的 promotion outcome 报告又进一步收紧了结论：`001309` promotion 后仍保持 `next_high_return_mean=0.0510`、`next_close_return_mean=0.0414`、`next_close_positive_rate=1.0`，而 `300620` promotion 后虽然 `next_high_return_mean=0.0479`，但 `next_close_return_mean=-0.0014`、`next_close_positive_rate=0.5`。这说明两者虽然都还是 current-window emergent baselines，但在 case-based near-miss promotion 这一更窄分支里，`001309` 已经不只是更低成本，而且也是 follow-through 更一致的第一优先受控 release 入口。

## 新补的次日 outcome 证据说明什么

这轮已经把 frontier 判断和真实次日表现绑到同一口径里：

- `300383` 只有 `1` 个样本，但结果干净且方向一致：`next_open_return=0.0246`、`next_high_return=0.0527`、`next_close_return=0.0146`，`next_high_hit_rate@2%=1.0`，`next_close_positive_rate=1.0`
- `600821` 与 `002015` 合并后的 `6` 个 recurring frontier 样本，`next_high_return_mean=0.0421`、`next_close_return_mean=-0.0039`，说明它们整体更像 intraday opportunity，而不是稳定的收盘延续簇
- 若拆开看，`600821` 的优势是上冲更强，三次样本的 `next_high_return_mean=0.0503`、`next_close_return_mean=-0.0020`，且仍保持当前最小 rescue cost=`0.10`；但其 `next_close_positive_rate` 只有 `0.3333`
- `002015` 的优势是收盘延续更稳，三次样本的 `next_high_return_mean=0.0339`、`next_close_return_mean=-0.0057`，`next_close_positive_rate=0.6667`，但最小 rescue cost 更高，为 `0.12`
- 新补的 release-outcome pair comparison 则把角色进一步固定为：`600821` 是 recurring release 的 intraday 主样本，`002015` 是 close-continuation 对照样本

这组证据原本把优先级收紧到 `300383 first`，但在本轮把 `001309` promotion outcome 正式纳入统一 scorecard 后，排序已经进一步更新为：`001309` 第一，`300383` 第二，`002015` 第三，`600821` 第四。也就是说，`300383` 仍然是最干净的 threshold-only release 样本，但它已经不再压过 `001309` 的低成本 close-continuation promotion 入口。至于 recurring frontier，中短期仍只应作为局部 baseline 审查：`002015` 的 close-positive rate 虽高于 `600821`，但两者 next-close mean 都仍为负，因此只能后置为 recurring release 对照，而不是下一轮第一入口。

对应的证据文件现在已经拆开落盘，可直接复查：

- `300383`：`data/reports/targeted_short_trade_boundary_release_outcomes_300383_20260329.{json,md}`
- `600821` / `002015`：`data/reports/short_trade_boundary_recurring_frontier_dossiers_catalyst_floor_zero_20260329.{json,md}`
- `600821` 单票 dossier：`data/reports/short_trade_boundary_frontier_ticker_dossier_600821_20260329.{json,md}`
- `002015` 单票 dossier：`data/reports/short_trade_boundary_frontier_ticker_dossier_002015_20260329.{json,md}`
- `600821 vs 002015` 对照：`data/reports/short_trade_boundary_frontier_pair_comparison_600821_vs_002015_20260329.{json,md}`
- `600821` recurring release：`data/reports/recurring_frontier_ticker_release_600821_20260329.{json,md}`
- `002015` recurring release：`data/reports/recurring_frontier_ticker_release_002015_20260329.{json,md}`
- `600821` release outcomes：`data/reports/recurring_frontier_ticker_release_outcomes_600821_20260329.{json,md}`
- `002015` release outcomes：`data/reports/recurring_frontier_ticker_release_outcomes_002015_20260329.{json,md}`
- `600821 vs 002015` release-outcome 对照：`data/reports/recurring_frontier_release_pair_comparison_600821_vs_002015_20260329.{json,md}`
- `600821` / `002015` 历史窗口角色迁移：`data/reports/short_trade_ticker_role_history_600821_002015_20260329.{json,md}`
- 宽覆盖 transition 复核：`data/reports/recurring_frontier_transition_candidates_all_windows_20260329.md`
- 全局 multi-window short-trade 扫描：`data/reports/multi_window_short_trade_role_candidates_20260329.{json,md}`
- `001309` 单票 dossier：`data/reports/multi_window_short_trade_ticker_dossier_001309_20260329.{json,md}`
- `300620` 单票 dossier：`data/reports/multi_window_short_trade_ticker_dossier_300620_20260329.{json,md}`
- `001309 vs 300620` 对照：`data/reports/multi_window_short_trade_ticker_pair_comparison_001309_vs_300620_20260329.{json,md}`
- `001309` near-miss promotion：`data/reports/targeted_short_trade_near_miss_release_001309_20260329.{json,md}`
- `300620` near-miss promotion：`data/reports/targeted_short_trade_near_miss_release_300620_20260329.{json,md}`
- `001309` promotion outcomes：`data/reports/targeted_short_trade_near_miss_release_outcomes_001309_20260329.{json,md}`
- `300620` promotion outcomes：`data/reports/targeted_short_trade_near_miss_release_outcomes_300620_20260329.{json,md}`
- `001309 vs 300620` promotion 对照：`data/reports/targeted_short_trade_near_miss_release_pair_comparison_001309_vs_300620_20260329.{json,md}`

## 这把主线收紧到了哪里

当前前置短线 score frontier 路线可以明确拆成两步：

1. 先验证最小成本、最小污染的 threshold-only 样本是否值得保留。
2. 再验证 recurring ticker 是否代表一类稳定可重复的 stale/extension frontier，而不是只在当前窗口成立的局部模式。

这也意味着 admission 层在当前阶段可以暂时冻结：`catalyst_freshness_min = 0.00` 已经足够，不需要继续扩 floor 试验面。

## 最终决策

如果下一轮继续优先推进 Layer C 之前的短线策略，那么建议顺序应固定为：

1. 先做 `001309` 的 near-miss case-based promotion follow-through。
2. 再做 `300383` 的 threshold-only case-based release。
3. 然后再看 `002015` 与 `600821` 的 recurring frontier baseline 是否值得继续保留为局部对照。

若进一步细化为受控实验角色分层，则当前口径应固定为：`001309` 是主实验入口，`300383` 是 shadow entry，`300620` 只保留为 intraday control。这一步的意义是把“优先级排序”推进成“下一轮具体怎么跑”的执行分层，而不再只是摘要层判断。

现在这一步又向前推进了一层：下一轮已经不只是“先跑 001309”，而是可以直接按 runbook 执行。也就是说，`001309` 的主实验 guardrails、`300383` 的 shadow 位置、`300620` 的 control 语义都已固定，后续不需要再先做一轮口头设计。

如果只看 recurring frontier 与 near-miss emergent baselines 的内部角色，当前可以更细地固定为：`001309` 是总优先级第一的 near-miss close-continuation promotion 样本，`300383` 是第二优先的 threshold-only release 样本；`600821` 是 recurring release 的 intraday 主样本，`002015` 是 recurring release 的 close continuation 对照样本；`300620` 仍是 near-miss intraday 对照样本，但要进入同级 promotion 需要更激进的 `select_threshold=0.53`，且 promotion 后 only `0.5` 的 close-positive rate。于是更精确的近端顺序应是：先继续 `001309`，再复核 `300383`，然后才是 recurring baseline 与 `300620` 对照。不过从跨窗口语义看，这五个入口都仍属于 current-window emergent baselines。
