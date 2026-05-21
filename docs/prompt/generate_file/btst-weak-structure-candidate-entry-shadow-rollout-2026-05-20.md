# BTST 弱结构 candidate-entry 影子 rollout 治理 - 2026-05-20

## 因子 / 规则名称
- `weak_structure_triplet`
- 精修 shadow 候选：`weak_structure_triplet_trend_cap_037`
- 原始 structural variant：`exclude_watchlist_avoid_weak_structure_entries`
- 精修验证路径：`baseline + variant_structural_overrides`

## 规则原理
- 这条规则不是去放宽 `selected` 阈值，而是更早地清洗 `watchlist_filter_diagnostics` 里结构明显偏弱的 candidate-entry 名字。
- 当前最稳的语义是：`breakout_freshness <= 0.05`、`volume_expansion_quality <= 0.05`、`catalyst_freshness <= 0.05` 三个维度同时接近零时，把这类名字作为弱结构入口样本排除。
- 最新一轮窗口诊断说明，上面这条 triplet 语义仍然偏钝；更安全的 shadow 精修候选是在此基础上再加一层 `trend_acceleration <= 0.37`。
- 它的目标不是增加交易数量，而是减少“根本不该进入后续 target 决策”的弱样本，从而提升短线策略的胜率和盈亏比下限。

## 本次验证结论
- 当前窗口 frontier 产物：
  - `data/reports/btst_candidate_entry_frontier_20260323_20260326_baseline_refresh.json`
  - `data/reports/btst_candidate_entry_frontier_20260323_20260326_baseline_refresh.md`
- 在 `paper_trading_window_20260323_20260326_btst_baseline_refresh` 上，`weak_structure_triplet` 被选为 best variant：
  - 命中 focus ticker：`300502`
  - `filtered_candidate_entry_count = 1`
  - `filtered_next_high_hit_rate_at_threshold = 0.0`
  - `filtered_next_close_positive_rate = 0.0`
  - 主链校验里对应为 `blocked->none` 的单点释放，说明它更像“入口清洗”而不是“selected 放宽”
- 同窗口里 `300394` 没有被该规则误伤；它在治理里被当作 preserve anchor 使用。

## 多窗口治理结果
- 多窗口 scan 产物：
  - `data/reports/btst_candidate_entry_window_scan_20260520.json`
  - `data/reports/btst_candidate_entry_window_scan_20260520.md`
- rollout governance 产物：
  - `data/reports/p9_candidate_entry_rollout_governance_20260520.json`
  - `data/reports/p9_candidate_entry_rollout_governance_20260520.md`
- payoff validation 产物：
  - `data/reports/btst_candidate_entry_payoff_validation_20260520.json`
  - `data/reports/btst_candidate_entry_payoff_validation_20260520.md`
- refined payoff validation 产物：
  - `data/reports/btst_candidate_entry_payoff_validation_trend_cap_037_20260520.json`
  - `data/reports/btst_candidate_entry_payoff_validation_trend_cap_037_20260520.md`
- semantic-pair payoff validation 产物：
  - `data/reports/btst_candidate_entry_payoff_validation_semantic_pair_300502_20260520.json`
  - `data/reports/btst_candidate_entry_payoff_validation_semantic_pair_300502_20260520.md`
- 当前聚合结论：
  - `report_count = 29`
  - `filtered_report_count = 9`
  - `focus_hit_report_count = 8`
  - `preserve_misfire_report_count = 0`
  - `distinct_window_count_with_filtered_entries = 4`
  - `lane_status = shadow_rollout_review_ready`
  - `default_upgrade_status = blocked_pending_additional_shadow_execution_evidence`
  - `upgrade_gap = ready_for_shadow_rollout_review`
- shadow execution evidence 产物进一步给出：
  - `evidence_report_count = 2`
  - `candidate_entry_signal_report_count = 2`
  - `focus_negative_tickers = ['300502']`
  - `focus_positive_tickers = []`
  - `non_focus_positive_tickers = ['002028', '300308', '300394', '600989']`
  - `execution_verdict = focus_ticker_execution_support_with_separation`
- payoff validation 进一步给出：
  - `keep_baseline_count = 1`
  - `variant_supports_t1_count = 1`
  - `cleanup_only_count = 6`
  - `false_negative_relief_count = 1`
  - `mixed_count = 20`
  - recommendation：`Baseline should remain the default`
- refined `trend_cap = 0.37` payoff validation 进一步给出：
  - `keep_baseline_count = 0`
  - `variant_supports_t1_count = 0`
  - `cleanup_only_count = 6`
  - `false_negative_relief_count = 3`
  - `mixed_count = 20`
  - recommendation：`Weak-structure candidate-entry rule is currently behaving like entry cleanup rather than direct actionable payoff uplift`
- `semantic_pair_300502` payoff validation 进一步给出：
  - `keep_baseline_count = 0`
  - `variant_supports_t1_count = 0`
  - `cleanup_only_count = 5`
  - `false_negative_relief_count = 1`
  - `mixed_count = 23`
  - recommendation：仍然是 cleanup / shadow governance 语义，没有恢复 direct actionable uplift

## 提升效果与边界
- 这条规则已经不再只是单日猜想，而是**具备进入 shadow rollout review 的治理证据**：
  - 它在多个独立窗口里重复命中过弱的 candidate-entry 名字；
  - 当前没有出现 preserve 误伤；
  - 最典型的目标名 `300502` 被稳定识别为弱结构入口样本。
- 现在又多了一层 **shadow execution separation evidence**：
  - 目标弱样本 `300502` 在真实 BTST followup 里仍停留在 `opportunity / rejected`；
  - 同时其他非 focus 的 `watchlist_filter_diagnostics` 名字仍能进入 `selected / near_miss`；
  - 这说明弱结构规则并不是把整条 source lane 一刀切掉，而是在真实 followup 中出现了“目标弱样本被压制、非目标样本仍能晋级”的分离面。
- 但新增的 **payoff validation** 也把边界说得更清楚：
  - 有 `6` 个窗口表现为 `entry_cleanup_without_actionable_delta`，说明它经常只是在清洗弱样本，并没有改变 actionable surface；
  - 有 `1` 个窗口表现为 `entry_cleanup_reduces_false_negative_proxy`，说明它偶尔会减少 false-negative 压力；
  - 但同时已经出现 `1` 个 `keep_baseline_default` 窗口，说明这条规则并不是无条件安全；
  - 虽然也有 `1` 个窗口给出 `variant_supports_t1_actionable_edge`，但当前 aggregate verdict 仍是 **baseline 应保持默认**。
- 新一轮负面/正面窗口对照诊断之后，精修版 `trend_cap = 0.37` 给出更细的结论：
  - 原来最关键的负面窗口 `paper_trading_window_20260415_20260423_live_m2_7_independent_window_validation_20260518_rerun`，从 `keep_baseline_default` 变成了 `entry_cleanup_reduces_false_negative_proxy`；
  - 原来唯一的正面 actionable 窗口 `paper_trading_window_20260429_20260514_live_m2_7_001309_window_generation_20260518`，也从 `variant_supports_t1_actionable_edge` 收敛成了 `entry_cleanup_reduces_false_negative_proxy`；
  - 这说明 `trend_acceleration <= 0.37` 这层窄 trend cap 的主要价值不是“直接放大利润”，而是把过钝的 triplet 规则收窄成更安全的 shadow cleanup 旁路；
  - 代价也很明确：它消除了负面 actionable 窗口，但同时也把原来唯一的正面 actionable uplift 一并抹平了。
- 随后又验证了 `semantic_pair_300502`（`trend_acceleration <= 0.34` + `close_strength <= 0.69`）：
  - 聚合结果没有比 `trend_cap = 0.37` 更好；
  - 它在两个最关键的窗口里甚至没有触发过滤，说明这条 semantic pair 没有真正接住当前主问题；
  - 这进一步说明：**继续在现有 weak-structure family 里做微调，短期内更像是在优化 shadow cleanup 语义，而不是在逼近默认升级因子。**
- 但它**还不能写成默认升级版**：
  - 当前治理状态虽然已有 shadow execution separation evidence，但 payoff validation 已经显示出 mixed actionable result；
  - `score_frontier_all_zero = True`，说明它目前应被理解为“入口清洗语义”，而不是已经证明能直接带来默认 profile 提升的主升级因子；
  - 即使 refined `trend_cap = 0.37` 已把 `keep_baseline_count` 压到 `0`，它依旧没有拿到 `variant_supports_t1_count > 0` 的直接 payoff uplift 证据；
  - 因此现在最准确的表述只能是：**原始 triplet 过钝，`trend_cap = 0.37` 是更安全的 shadow refinement，但它还不是正式默认规则。**

## 如何验证
- 当前窗口 frontier：
  - `uv run python scripts/analyze_btst_candidate_entry_frontier.py data/reports/paper_trading_window_20260323_20260326_btst_baseline_refresh --baseline-profile trend_continuation_strength_v2 --focus-ticker 300394 --focus-ticker 300502 --output-json data/reports/btst_candidate_entry_frontier_20260323_20260326_baseline_refresh.json --output-md data/reports/btst_candidate_entry_frontier_20260323_20260326_baseline_refresh.md`
- 多窗口 scan：
  - `uv run python scripts/analyze_btst_candidate_entry_window_scan.py --report-root-dirs data/reports --report-name-contains paper_trading_window --structural-variant exclude_watchlist_avoid_weak_structure_entries --profile-name trend_continuation_strength_v2 --focus-tickers 300394,300502 --output-json data/reports/btst_candidate_entry_window_scan_20260520.json --output-md data/reports/btst_candidate_entry_window_scan_20260520.md`
- rollout governance：
  - `uv run python scripts/analyze_btst_candidate_entry_rollout_governance.py --frontier-report data/reports/btst_candidate_entry_frontier_20260323_20260326_baseline_refresh.json --window-scan-report data/reports/btst_candidate_entry_window_scan_20260520.json --evidence-btst-report-dirs data/reports/paper_trading_20260506_20260506_frozen_auto_profile_validation_fixrecompute_20260507,data/reports/paper_trading_2026-04-17_2026-04-17_live_m2_7_short_trade_only_20260417_plan --output-json data/reports/p9_candidate_entry_rollout_governance_20260520.json --output-md data/reports/p9_candidate_entry_rollout_governance_20260520.md`
- payoff validation：
  - `uv run python scripts/analyze_btst_candidate_entry_payoff_validation.py --reports-root data/reports --profile-name trend_continuation_strength_v2 --variant-structural-variant exclude_watchlist_avoid_weak_structure_entries --output-json data/reports/btst_candidate_entry_payoff_validation_20260520.json --output-md data/reports/btst_candidate_entry_payoff_validation_20260520.md`
- refined payoff validation：
  - `uv run python scripts/analyze_btst_candidate_entry_payoff_validation.py --reports-root data/reports --profile-name trend_continuation_strength_v2 --baseline-structural-variant baseline --variant-structural-variant baseline --variant-breakout-freshness-max 0.05 --variant-trend-acceleration-max 0.37 --variant-volume-expansion-quality-max 0.05 --variant-catalyst-freshness-max 0.05 --output-json data/reports/btst_candidate_entry_payoff_validation_trend_cap_037_20260520.json --output-md data/reports/btst_candidate_entry_payoff_validation_trend_cap_037_20260520.md`

## 如何让 ai-hedge-fund-btst skill 使用
- skill 在读取当前 BTST artifact 时，应该额外读取最新的：
  - `p9_candidate_entry_rollout_governance_*.json`
  - `btst_candidate_entry_window_scan_*.json`
- 如果看到：
  - `lane_status = shadow_rollout_review_ready`
  - `default_upgrade_status = blocked_pending_additional_shadow_execution_evidence`
  - `preserve_misfire_report_count = 0`
  - `execution_verdict = focus_ticker_execution_support_with_separation`
  - 但 `btst_candidate_entry_payoff_validation_*.json` 仍给出 `Baseline should remain the default`
- 那么最终中文报告可以把这条规则描述为：
  - **“弱结构 candidate-entry 清洗规则已具备进入 shadow rollout review 的条件”**
  - **“真实 shadow execution 也已出现分离证据：目标弱样本继续停留在 opportunity/rejected，而非目标名字仍能进入 selected/near_miss”**
- 但必须同时写清楚：
  - **“payoff validation 仍是 mixed，默认 profile 仍应保持 baseline”**
  - **“它还不是默认升级，不得直接表述为正式主链 profile 提升”**
  - **“300394 这类 preserve anchor 仍不得被误伤”**
- 如果最新 artifact 进一步显示 `variant_structural_overrides` 里包含 `trend_acceleration <= 0.37`，并且：
  - `keep_baseline_count = 0`
  - `variant_supports_t1_count = 0`
  - recommendation 仍是 cleanup / false-negative-relief 语义
- 那么最终中文报告可以额外补一句：
  - **“最新精修版把原来过钝的 triplet 收窄成更安全的 shadow cleanup 规则，已消除负面 actionable 窗口，但仍未拿到直接 payoff uplift，因此只能作为 shadow refinement 引用。”**

## 下一步建议
- 后续主线不该再围绕 `trend_continuation_strength_v3` 的 selected-only shrink 做盲调。
- 更值得继续推进的是：
  - 不再把原始 `exclude_watchlist_avoid_weak_structure_entries` triplet 直接当作唯一主候选；
  - 优先用 `trend_cap = 0.37` 这条更窄的 shadow refinement 继续做窗口累计；
  - 同时把 `semantic_pair_300502` 视为一次已验证但未通过的弱结构旁路尝试，不再继续在它上面加码；
  - 新增窗口后持续重跑 window scan；
  - 同时持续重跑 payoff validation，重点盯住它能否在保持 `keep_baseline_count = 0` 的前提下重新获得 `variant_supports_t1_count > 0`；
  - 只有在 preserve 误伤仍为 0、shadow execution evidence 继续增加、并且 refined payoff validation 开始出现稳定的直接 actionable uplift 时，才讨论是否从 shadow review 往更高治理层级移动。
