# scripts/ 目录索引

> **本目录共 317 个文件** (309 个 `.py` + 8 个 `.sh` + 1 个 `__init__.py`)。绝大多数是 BTST (Buy Today Sell Tomorrow) 策略相关的分析、回测、实验脚本。
>
> **快速找到你需要的脚本**:
> 1. 想要**每天运行**的入口 → [§1 生产入口](#1-生产入口-日常使用)
> 2. 想要**回测/参数搜索** → [§2 回测与分析](#2-回测与分析)
> 3. 想要**管理数据/缓存** → [§3 数据维护](#3-数据维护)
> 4. 想要**查 LLM 路由/模型** → [§4 LLM 与工具](#4-llm-与工具)
> 5. 其他**实验性/归档**脚本 → [§5 BTST 实验/分析](#5-btst-实验分析-144-个)、[§6 工具/库模块](#6-工具库模块)

---

## 目录说明

`scripts/` 是项目的**实验、运维、批处理工作台**。

| 类别 | 数量 | 用途 | 是否每日运行 |
|------|------|------|--------------|
| 生产入口 | ~15 | 纸面交易、批跑分析、回测刷新 | ✅ 是 |
| 回测与分析 | ~10 | 因子 IC、网格搜索、profile 对比 | 按需 |
| 数据维护 | ~10 | 缓存管理、数据回填、校验 | 偶尔 |
| LLM 与工具 | ~10 | 模型选择、LLM 指标、路由 | 调试用 |
| BTST 实验/分析 | ~144 | 一次性诊断、专项分析、dossier | ⚠️ 大多已废弃 |
| BTST 生成器 | ~30 | 报告/卡/产物生成 | 由 `run_*` 编排 |
| 工具/库模块 | ~44 | `*_helpers.py` / `*_utils.py` | 由其他脚本 import |
| Backfill / Refresh / Validate | ~12 | 一次性数据回填、产物校验 | 一次性 |
| 一次性 / Quarantine | ~5 | `_*.py`、`tmp_*.py` | ⚠️ 已废弃 |
| Shell 脚本 | 8 | 启动前端/服务/批跑/测试 | 偶尔 |

> **总览图**: `run_*.py` (生产编排) → `generate_*.py` (报告生成) → `analyze_*.py` (诊断分析) → `*_helpers.py`/`*_utils.py` (共享库)。

---

## 1. 生产入口 (日常使用)

这些是日常/周期运行的入口脚本,其他脚本大多是被它们 import 或被它们生成的产物。

| 脚本 | 说明 | 典型用法 |
|------|------|----------|
| `run_paper_trading.py` | **核心入口**: 纸面交易主流程 (生成候选 → 风控 → 下单) | `python scripts/run_paper_trading.py --start-date 2026-06-01 --end-date 2026-06-05 --tickers 300724` |
| `run_paper_trading_gate_experiments.py` | 纸面交易 gate 实验 (A/B 测试通过率阈值) | 灰度发布前后对比 |
| `run_btst_next_day_package.py` | **次日包统一入口**: 编排 doc-bundle、profile compare、ONE-PAGER | `python scripts/run_btst_next_day_package.py` |
| `run_btst_nightly_control_tower.py` | **夜维控制塔**: 每日 23:00 自动跑产物生成 | cron / 手动触发 |
| `run_btst_carryover_close_loop_refresh.py` | Carryover 闭环刷新 (T+1 → T+2 跨日验证) | 每日盘后 |
| `run_btst_march_backtest_refresh.py` | 3 月窗口回测数据刷新 | 每月 |
| `run_btst_momentum_threshold_governance.py` | 动量阈值 governance 决策 | 阈值调整时 |
| `run_btst_profile_experiment.py` | 跑单 profile 实验 (新参数组合验证) | 实验性 |
| `run_btst_top3_experiments.py` | Top3 候选实验包 | 实验性 |
| `run_btst_recurring_shadow_close_bundle.py` | Recurring shadow 收尾包 | 迭代收尾 |
| `run_btst_candidate_pool_corridor_shadow_pack.py` | 候选池 corridor 阴影运行 | 评估 |
| `run_btst_candidate_pool_corridor_uplift_runbook.py` | 候选池 corridor 上线 runbook | 上线前 |
| `run_btst_candidate_pool_corridor_validation_pack.py` | 候选池 corridor 验证包 | 验证 |
| `run_btst_candidate_pool_lane_pair_board.py` | 候选池 lane 对比看板 | 对比 |
| `run_btst_candidate_pool_rebucket_comparison_bundle.py` | 候选池 rebucket 对比包 | 评估 |
| `run_btst_candidate_pool_rebucket_shadow_pack.py` | 候选池 rebucket 阴影包 | 评估 |
| `run_btst_candidate_pool_upstream_handoff_board.py` | 候选池上游交接看板 | 交接 |
| `run_short_trade_boundary_variant_validation.py` | 短交易边界变体验证 | 验证 |
| `run_targeted_short_trade_boundary_experiment_pack.py` | 定向短交易边界实验包 | 实验 |
| `run_lookback_audit.py` | Lookback 窗口审计 | 审计 |
| `aggregate_screening_daily_digest.py` | **筛选 Daily Digest** (Feature 2.2): 聚合 N 日候选池/评分,输出 CSV/JSON/MD | `python scripts/aggregate_screening_daily_digest.py --latest-30-days` |
| `batch_run_hedge_fund.py` | 批量跑 hedge fund 分析 (从 Markdown 读股票列表) | `python scripts/batch_run_hedge_fund.py` |

### Shell 入口

| 脚本 | 说明 |
|------|------|
| `run-hedge-fund.sh` | 跑 hedge fund CLI (包装 `src/main.py`) |
| `run-daily-gainers.sh` | 每日涨幅榜跑批 |
| `batch-run-hedge-fund.sh` | 批量跑 hedge fund (shell 版) |
| `start-frontend.sh` | 启动前端 dev server |
| `start-server.sh` | 启动后端 FastAPI |
| `run-tests.sh` | 跑测试套件 |
| `list-analysts.sh` | 列出所有可用 analyst agents |
| `run_live_replay_600519_p1.sh` | 600519 (贵州茅台) live replay P1 |

---

## 2. 回测与分析

| 脚本 | 说明 |
|------|------|
| `btst_20day_backtest.py` | **核心回测**: 20 天真实回测,比较多个 short-trade profile |
| `btst_daily_selection_report.py` | 每日选股分析报告 (基于最近交易日,输出 Top 候选) |
| `btst_daily_reconciliation.py` | 每日对账 (纸面交易 vs 实际执行) |
| `btst_full_report.py` | 完整分析报告 (候选池 + 因子 + 行业 + Top 候选) |
| `btst_factor_ic_analysis.py` | **因子 IC 分析**: 测量每个因子对次日收益的预测能力 |
| `btst_factor_deep_ic_analysis.py` | 因子 IC 深度分析 (分位 / 滚动 / 跨样本) |
| `btst_market_regime_analysis.py` | 市场状态分析 (区分 winner/loser days,找市场层过滤信号) |
| `btst_filter_analysis.py` | 过滤器分析 (涨停 / 趋势 / 流动性 过滤效果) |
| `btst_threshold_grid_search.py` | **网格搜索**: `select_threshold` × `near_miss_threshold` × `rank_cap_ratio` |
| `btst_profile_compare.py` | Profile 对比 (ic_v3 vs btst_precision_v2 等) |
| `btst_scoring_compare.py` | 评分对比 (各 profile 在指定日期的选股差异) |
| `btst_strategy_thresholds.py` | 策略阈值配置加载 (`config/btst_strategy_thresholds.json`) |
| `btst_strict_objective_gate.py` | 严格客观指标 gate (上线前必须通过的指标检查) |
| `optimize_profile.py` | **Profile 优化**: 网格搜索 + checkpoint + 多窗口评估 |

---

## 3. 数据维护

| 脚本 | 说明 |
|------|------|
| `manage_data_cache.py` | **数据缓存管理**: `python manage_data_cache.py stats / clear --yes` |
| `benchmark_data_cache_reuse.py` | 冷/热缓存复用率基准 (debug 缓存命中问题) |
| `validate_data_cache_reuse.py` | 缓存复用率验证 |
| `backfill_btst_5d_15pct_scoped_price_snapshots.py` | ⚠️ 一次性: 5d_15pct 范围的价格快照回填 |
| `backfill_btst_followup_artifacts.py` | ⚠️ 一次性: BTST 后续产物回填 |
| `backfill_btst_review_ledgers.py` | ⚠️ 一次性: BTST 复核 ledger 回填 |
| `refresh_btst_5d_15pct_priors.py` | ⚠️ 一次性: 5d_15pct 范围 priors 刷新 |
| `refresh_selection_artifacts_from_daily_events.py` | ⚠️ 一次性: 从 daily events 刷新选择产物 |
| `rebuild_catalyst_theme_diagnostics_from_frozen_reports.py` | ⚠️ 一次性: 从 frozen reports 重建 catalyst/theme 诊断 |
| `validate_btst_early_runner_history.py` | 验证 early runner 历史数据完整性 |
| `validate_btst_governance_consistency.py` | 验证 governance 一致性 (跨产物对账) |
| `validate_btst_governance_consistency_helpers.py` | governance 一致性验证的 helper |
| `validate_momentum_strength.py` | 动量强度校验 |
| `probe_execution_buy_orders.py` | 探查执行层 buy orders 状态 (debug 成交) |
| `audit_btst_outputs_month.py` | ⚠️ 一次性: 月度 BTST 产物审计 |
| `scan_historical_edge_samples.py` | ⚠️ 一次性: 扫描历史边缘样本 (找离群点) |

---

## 4. LLM 与工具

| 脚本 | 说明 |
|------|------|
| `list-models.py` | **列出所有可用 LLM 模型** (含 API key 检查) |
| `inspect_llm_routing.py` | 诊断 LLM 路由 (双 provider lane / 并发限流) |
| `model_selection.py` | 模型选择解析 (命令行 → 实际 provider/model) |
| `summarize_llm_metrics.py` | **LLM 指标汇总**: `python summarize_llm_metrics.py logs/<file>.jsonl` |
| `supervise_ab_compare.py` | A/B 对比监督 (后台跑 walk-forward, 写日志) |
| `supervise_batch_run.py` | 批量运行监督 (子进程监控 + 日志) |
| `manage_research_feedback.py` | 研究反馈管理 (添加 / 汇总 research feedback) |
| `generate_report_summary.py` | 报告摘要生成 (单报告 → markdown 摘要) |
| `generate_reports_manifest.py` | 报告 manifest 生成 (扫 reports/ 目录) |
| `fill_btst_decision_review_ledger.py` | ⚠️ 一次性: 填充 BTST 决策复核 ledger |
| `export_layer_b_review.py` | ⚠️ 一次性: 导出 Layer B 复核 |
| `export_layer_b_variant_added_review.py` | ⚠️ 一次性: 导出 Layer B 变体复核 |

---

## 5. BTST 实验/分析 (144 个)

> ⚠️ **绝大多数是一次性实验 / dossier / 诊断板**,已封存在 2026-03 ~ 2026-05 的多轮迭代中。日常不需要运行,只在新策略论证/复盘时翻阅。
>
> 命名规律:
> - `analyze_btst_*` — 分析/诊断
> - `analyze_btst_*_dossier.py` — 综合 dossier (定稿结论)
> - `analyze_btst_*_board.py` — 看板/评分卡
> - `analyze_btst_*_validation.py` — 验证脚本
> - `analyze_btst_*_diagnostics.py` — 诊断脚本
> - `analyze_btst_5d_15pct_*` — 5 日 15% 边界专项 (2026 Q1 主线)
> - `analyze_btst_carryover_*` — Carryover (T+1 → T+2 持续) 专项
> - `analyze_btst_candidate_entry_*` — 候选入场专项
> - `analyze_btst_candidate_pool_*` — 候选池专项
> - `analyze_btst_tplus2_*` — T+2 持续专项
> - `analyze_btst_shadow_*` / `*_shadow_*` — 阴影运行 (非生产)
> - `analyze_btst_*_gate_*` — Gate 决策脚本
> - `analyze_btst_*_frontier.py` — 边界/前沿扫描
> - `analyze_btst_*_replay.py` — 历史重放
> - `analyze_short_trade_*` — 短交易分析

### 完整列表 (按主题分组,字母序)

#### 5.1 5d_15pct 边界专项 (2026 Q1 主线)
- `analyze_btst_0422_baseline_freeze.py` — 0422 baseline 冻结
- `analyze_btst_5d_15pct_boundary_contract_fill_path.py` — 边界合约 fill 路径
- `analyze_btst_5d_15pct_boundary_contract_inspection.py` — 边界合约检查
- `analyze_btst_5d_15pct_boundary_missing_six_core_keys.py` — 缺失 6 个核心 key
- `analyze_btst_5d_15pct_boundary_quarantine.py` — 边界 quarantine 决策
- `analyze_btst_5d_15pct_factor_research_round1.py` — 因子研究 round 1
- `analyze_btst_5d_15pct_false_negative_diagnostic_board.py` — 假阴性诊断看板
- `analyze_btst_5d_15pct_false_negative_dossier.py` — 假阴性 dossier
- `analyze_btst_5d_15pct_missing_core_features_noise_compression.py` — 缺失核心特征 + 噪声压缩
- `analyze_btst_5d_15pct_near_trend_threshold_recovery.py` — 趋势阈值附近恢复
- `analyze_btst_5d_15pct_objective_monitor.py` — 客观指标监控
- `analyze_btst_5d_15pct_scoped_missing_price_manifest.py` — 范围缺失价格清单
- `analyze_btst_5d_15pct_trend_breakout_drilldown.py` — 趋势突破下钻
- `analyze_btst_5d_15pct_trend_gate_confirmation_grid.py` — 趋势 gate 确认网格
- `analyze_btst_5d_15pct_trend_gate_missing_price_manifest.py` — 趋势 gate 缺失价格清单
- `analyze_btst_5d_15pct_trend_gate_oos_validation.py` — 趋势 gate OOS 验证
- `analyze_btst_5d_15pct_trend_gate_sample_intake_board.py` — 趋势 gate 样本入口看板
- `analyze_btst_5d_15pct_trend_gate_threshold_grid.py` — 趋势 gate 阈值网格
- `analyze_btst_5d_15pct_trend_top20_gate_diagnostics.py` — 趋势 Top20 gate 诊断
- `analyze_btst_5d_15pct_unclassified_split_board.py` — 未分类拆分看板

#### 5.2 候选入场 (candidate entry)
- `analyze_btst_candidate_entry_frontier.py`
- `analyze_btst_candidate_entry_payoff_validation.py`
- `analyze_btst_candidate_entry_rollout_governance.py`
- `analyze_btst_candidate_entry_window_scan.py`

#### 5.3 候选池 (candidate pool)
- `analyze_btst_candidate_pool_branch_priority_board.py`
- `analyze_btst_candidate_pool_corridor_narrow_probe.py`
- `analyze_btst_candidate_pool_corridor_persistence_dossier.py`
- `analyze_btst_candidate_pool_corridor_proof_gate_outcomes.py`
- `analyze_btst_candidate_pool_corridor_window_command_board.py`
- `analyze_btst_candidate_pool_corridor_window_diagnostics.py`
- `analyze_btst_candidate_pool_lane_objective_support.py`
- `analyze_btst_candidate_pool_rebucket_objective_validation.py`
- `analyze_btst_candidate_pool_recall_dossier.py`

#### 5.4 Carryover (T+1 → T+2 跨日)
- `analyze_btst_carryover_aligned_peer_harvest.py`
- `analyze_btst_carryover_aligned_peer_proof_board.py`
- `analyze_btst_carryover_anchor_probe.py`
- `analyze_btst_carryover_false_negative_dossier.py`
- `analyze_btst_carryover_horizon_validation.py`
- `analyze_btst_carryover_multiday_continuation_audit.py`
- `analyze_btst_carryover_peer_board.py`
- `analyze_btst_carryover_peer_expansion.py`
- `analyze_btst_carryover_peer_promotion_gate.py`
- `analyze_btst_carryover_peer_quality_review.py`
- `analyze_btst_carryover_selected_cohort.py`

#### 5.5 T+2 持续 (continuation)
- `analyze_btst_tplus1_tplus2_objective_monitor.py`
- `analyze_btst_tplus2_continuation_clusters.py`
- `analyze_btst_tplus2_continuation_lane_validation.py`
- `analyze_btst_tplus2_continuation_peer_rollup.py`
- `analyze_btst_tplus2_continuation_peer_scan.py`
- `analyze_btst_tplus2_near_cluster_dossier.py`

#### 5.6 动量 (momentum) 专项
- `analyze_btst_momentum_rerun_rollout_cohort.py`
- `analyze_btst_momentum_rerun_rollout_pack.py`
- `analyze_btst_momentum_rerun_rollout_recommendation.py`
- `analyze_btst_momentum_rollout_blocker_dossier.py`
- `analyze_btst_momentum_rollout_recheck_comparison.py`
- `analyze_btst_momentum_rollout_recheck_decision.py`
- `analyze_btst_momentum_rollout_recheck_pack.py`
- `analyze_btst_momentum_rollout_triage_recommendation.py`
- `analyze_btst_momentum_rollout_window_attribution.py`
- `analyze_btst_momentum_stability_retune_decision.py`
- `analyze_btst_momentum_stability_retune_shortlist.py`
- `analyze_btst_momentum_stability_retune_surface.py`
- `analyze_btst_momentum_threshold_rollout_assessment.py`

#### 5.7 上游 shadow (upstream shadow)
- `analyze_btst_upstream_shadow_decision_impact.py`
- `analyze_btst_upstream_shadow_fnfp_dossier.py`
- `analyze_btst_upstream_shadow_repeat_saturation.py`
- `analyze_btst_upstream_shadow_unknown_prior_audit.py`
- `analyze_btst_watchlist_recall_dossier.py`

#### 5.8 早盘 runner / 执行
- `analyze_btst_early_runner_v1.py`
- `analyze_btst_execution_contract_eval.py`
- `analyze_btst_top3_post_execution_action_board.py`

#### 5.9 月度/榜单
- `analyze_btst_monthly_execution_blockers.py`
- `analyze_btst_monthly_execution_health.py`
- `analyze_btst_monthly_execution_scorecard.py`
- `analyze_btst_monthly_near_miss_gate_breakdown.py`
- `analyze_btst_monthly_scorecard.py`
- `analyze_btst_monthly_zero_pick_promotion_counterfactual.py`
- `analyze_btst_weekly_validation.py`

#### 5.10 治理 / 风控 / 评分
- `analyze_btst_governance_synthesis.py`
- `analyze_btst_historical_prior_quality.py`
- `analyze_btst_independent_window_monitor.py`
- `analyze_btst_latest_close_validation.py`
- `analyze_btst_layer_c_rollout_validation.py`
- `analyze_btst_low_sample_penalty_audit.py`
- `analyze_btst_micro_window_regression.py`
- `analyze_btst_multi_window_profile_validation.py`
- `analyze_btst_no_candidate_entry_action_board.py`
- `analyze_btst_no_candidate_entry_failure_dossier.py`
- `analyze_btst_no_candidate_entry_replay_bundle.py`
- `analyze_btst_penalty_frontier.py`
- `analyze_btst_prepared_breakout_cohort.py`
- `analyze_btst_prepared_breakout_relief_validation.py`
- `analyze_btst_prepared_breakout_residual_surface.py`
- `analyze_btst_primary_roll_forward.py`
- `analyze_btst_primary_window_gap.py`
- `analyze_btst_primary_window_validation_runbook.py`
- `analyze_btst_prior_shrinkage_eval.py`
- `analyze_btst_profile_frontier.py`
- `analyze_btst_recurring_shadow_runbook.py`
- `analyze_btst_regime_gate_effect.py`
- `analyze_btst_replay_cohort.py`
- `analyze_btst_risk_budget_overlay_eval.py`
- `analyze_btst_rollout_governance_board.py`
- `analyze_btst_runner_payoff_realignment.py`
- `analyze_btst_score_construction_frontier.py`
- `analyze_btst_selected_nearmiss_separation.py`
- `analyze_btst_selected_outcome_proof.py`
- `analyze_btst_selected_outcome_refresh_board.py`
- `analyze_btst_shadow_entry_expansion.py`
- `analyze_btst_shadow_lane_priority.py`
- `analyze_btst_shadow_peer_scan.py`
- `analyze_btst_shadow_profile_replay.py`
- `analyze_btst_structural_shadow_runbook.py`
- `analyze_btst_tradeable_opportunity_pool.py`

#### 5.11 多窗口 / Layer B / Layer C / catalyst / 短期交易
- `analyze_catalyst_theme_frontier_release_pair_comparison.py`
- `analyze_catalyst_theme_frontier_release_ticker_comparison.py`
- `analyze_catalyst_theme_frontier_release.py`
- `analyze_case_based_short_trade_entry_pair_comparison.py`
- `analyze_case_based_short_trade_entry_readiness.py`
- `analyze_case_based_short_trade_follow_through_runbook.py`
- `analyze_layer_b_backtest_variants.py`
- `analyze_layer_b_boundary_failures.py`
- `analyze_layer_b_cold_distribution.py`
- `analyze_layer_b_rule_variants.py`
- `analyze_layer_b_variant_layer_c_carryover.py`
- `analyze_layer_c_agent_contributor_alignment.py`
- `analyze_layer_c_agent_contributor_drift.py`
- `analyze_layer_c_agent_contributor_window.py`
- `analyze_layer_c_diagnostic_board.py`
- `analyze_layer_c_edge_tradeoff.py`
- `analyze_layer_c_sensitivity.py`
- `analyze_layer_c_threshold_frontier.py`
- `analyze_layer_c_threshold_window_diagnostic.py`
- `analyze_layer_c_window_outlier.py`
- `analyze_layer_c_window_pair.py`
- `analyze_layer_c_window_quad.py`
- `analyze_layer_c_window_quartet.py`
- `analyze_layer_c_window_release_outcomes.py`
- `analyze_layer_c_window_release.py`
- `analyze_layer_c_window_validation.py`
- `analyze_multi_window_short_trade_candidate_pool_branch.py`
- `analyze_multi_window_short_trade_candidate_pool.py`
- `analyze_multi_window_short_trade_frontier.py`
- `analyze_multi_window_short_trade_outlier.py`
- `analyze_multi_window_short_trade_pair_comparison.py`
- `analyze_multi_window_short_trade_payoff.py`
- `analyze_multi_window_short_trade_role_candidates.py`
- `analyze_multi_window_short_trade_ticker_dossier.py`
- `analyze_multi_window_short_trade_ticker_pair_comparison.py`
- `analyze_pre_layer_short_trade_outcomes.py`
- `analyze_profitability_subfactor_breakdown.py`
- `analyze_recurring_frontier_release_pair_comparison.py`
- `analyze_recurring_frontier_ticker_release_outcomes.py`
- `analyze_recurring_frontier_ticker_release.py`
- `analyze_recurring_frontier_transition_candidates.py`
- `analyze_short_trade_blockers.py`
- `analyze_short_trade_boundary_coverage_variants.py`
- `analyze_short_trade_boundary_expansion_cases.py`
- `analyze_short_trade_boundary_filtered_candidates.py`
- `analyze_short_trade_boundary_frontier_pair_comparison.py`
- `analyze_short_trade_boundary_frontier_ticker_dossier.py`
- `analyze_short_trade_boundary_recurring_frontier_cases.py`
- `analyze_short_trade_boundary_recurring_frontier_dossiers.py`
- `analyze_short_trade_boundary_score_failures_frontier.py`
- `analyze_short_trade_boundary_score_failures.py`
- `analyze_short_trade_release_priority_scoreboard.py`
- `analyze_short_trade_ticker_role_history.py`
- `analyze_structural_conflict_blockers.py`
- `analyze_structural_conflict_rescue_window.py`
- `analyze_structural_conflict_rescue.py`
- `analyze_targeted_release_outcomes.py`
- `analyze_targeted_short_trade_boundary_release_outcomes.py`
- `analyze_targeted_short_trade_boundary_release.py`
- `analyze_targeted_short_trade_near_miss_release_outcomes.py`
- `analyze_targeted_short_trade_near_miss_release_pair_comparison.py`
- `analyze_targeted_short_trade_near_miss_release.py`
- `analyze_targeted_structural_conflict_release.py`
- `analyze_watchlist_suppression.py`

#### 5.12 BTST 主流分析脚本
- `btst_admission_replay_validator.py` — 入场 replay 验证
- `btst_momentum_active_baseline_bridge.py` — 动量 active baseline 桥接
- `btst_momentum_active_baseline_snapshot.py` — 动量 active baseline 快照
- `btst_regime_gate_15pct_cross_analysis.py` — Regime gate 15% 跨分析
- `btst_round89_rollout_assessment.py` — Round 89 rollout 评估
- `btst_round89_tc_grid.py` — Round 89 trend continuation 网格
- `btst_round89_trend_continuation_grid.py` — Round 89 trend continuation 网格
- `btst_selected_focus.py` — 选中焦点 (候选排序)
- `btst_trend_continuation_activation_delta_calibration.py` — Trend continuation 激活 delta 校准
- `btst_trend_continuation_activation_delta_diagnostics.py` — Trend continuation 激活 delta 诊断
- `btst_trend_continuation_rollout_assessment.py` — Trend continuation rollout 评估

---

## 6. 工具/库模块

> 这些不是入口脚本,是被其他 `analyze_*` / `run_*` / `generate_*` import 的共享库。`import scripts.btst_xxx_helpers` 调用。

### 6.1 BTST 工具库 (44 个)
| 模块 | 用途 |
|------|------|
| `btst_analysis_utils.py` | BTST 通用分析工具 (counter, json, mean) |
| `btst_data_utils.py` | BTST 数据工具 (北京交易所 mask 等) |
| `btst_strategy_thresholds.py` | 策略阈值常量 |
| `btst_candidate_entry_utils.py` | 候选入场工具 |
| `btst_score_replay_utils.py` | 评分 replay 工具 (默认阈值解析) |
| `btst_report_utils.py` | 报告工具 (markdown 渲染) |
| `btst_profile_replay_utils.py` | Profile replay 工具 |
| `btst_top3_runbook_utils.py` | Top3 runbook 工具 |
| `btst_short_trade_boundary_*` (见 6.2) | 短交易边界工具 |
| `short_trade_boundary_analysis_utils.py` | 短交易边界分析工具 |
| `btst_*_helpers.py` (见 6.3) | 各专项 helpers (boundary / carryover / nightly / open_ready / round89 / 上游 shadow) |
| `btst_latest_*_utils.py` | 最新 followup / snapshot 工具 |
| `btst_optimized_profile_manifest_helpers.py` | 优化 profile manifest helpers |
| `btst_history_selection_helpers.py` | 历史选择 helpers |
| `btst_round1_*_helpers.py` | Round 1 因子挖掘 / 未分类拆分 helpers |
| `btst_dossier_summary_helpers.py` | Dossier 摘要 helpers |
| `btst_remaining_summary_helpers.py` | 剩余摘要 helpers |
| `btst_snapshot_section_helpers.py` | 快照段 helpers |
| `btst_boundary_*_helpers.py` | 边界 contract / fill / quarantine / missing keys helpers |
| `btst_carryover_*_helpers.py` | Carryover contract / summary helpers |
| `btst_control_tower_*_helpers.py` | 控制塔 snapshot / task helpers |
| `btst_nightly_*_helpers.py` | 夜维 artifact / dossier / markdown / payload / render helpers |
| `btst_open_ready_*_helpers.py` | Open ready context / delta / diff / focus helpers |
| `btst_near_trend_threshold_recovery_helpers.py` | 趋势阈值附近恢复 helpers |
| `btst_missing_core_features_noise_helpers.py` | 缺失核心特征噪声 helpers |
| `btst_trend_continuation_rollout_helpers.py` | Trend continuation rollout helpers |
| `btst_upstream_shadow_overlay_helpers.py` | 上游 shadow overlay helpers |
| `generate_reports_manifest_candidate_entry_shadow_helpers.py` | Manifest 候选入场 shadow helpers |
| `replay_selection_target_calibration_helpers.py` | Replay 选择目标校准 helpers |
| `validate_btst_governance_consistency_helpers.py` | Governance 一致性验证 helpers |

### 6.2 短交易边界工具
- `short_trade_boundary_analysis_utils.py`

### 6.3 BTST Helpers 完整列表 (按字母序)
- `btst_boundary_contract_fill_helpers.py`
- `btst_boundary_contract_helpers.py`
- `btst_boundary_missing_core_key_trace_helpers.py`
- `btst_boundary_quarantine_helpers.py`
- `btst_candidate_entry_utils.py`
- `btst_carryover_contract_helpers.py`
- `btst_carryover_summary_helpers.py`
- `btst_control_tower_snapshot_helpers.py`
- `btst_control_tower_task_helpers.py`
- `btst_dossier_summary_helpers.py`
- `btst_history_selection_helpers.py`
- `btst_latest_followup_utils.py`
- `btst_latest_snapshot_helpers.py`
- `btst_missing_core_features_noise_helpers.py`
- `btst_near_trend_threshold_recovery_helpers.py`
- `btst_nightly_artifact_helpers.py`
- `btst_nightly_dossier_markdown_helpers.py`
- `btst_nightly_markdown_core_helpers.py`
- `btst_nightly_markdown_tail_helpers.py`
- `btst_nightly_payload_helpers.py`
- `btst_nightly_render_helpers.py`
- `btst_open_ready_context_helpers.py`
- `btst_open_ready_delta_markdown_helpers.py`
- `btst_open_ready_delta_payload_helpers.py`
- `btst_open_ready_diff_helpers.py`
- `btst_open_ready_focus_helpers.py`
- `btst_optimized_profile_manifest_helpers.py`
- `btst_remaining_summary_helpers.py`
- `btst_round1_factor_mining_helpers.py`
- `btst_round1_unclassified_split_helpers.py`
- `btst_round89_rollout_helpers.py`
- `btst_snapshot_section_helpers.py`
- `btst_top3_runbook_utils.py`
- `btst_trend_continuation_rollout_helpers.py`
- `btst_upstream_shadow_overlay_helpers.py`

### 6.4 其他 utils
- `replay_selection_target_calibration_helpers.py`
- `validate_btst_governance_consistency_helpers.py`

---

## 7. BTST 生成器 (generate_*.py) (30 个)

> 由 `run_btst_next_day_package` 等编排脚本调用,生成具体产物 (报告/卡/榜单/ledger)。

| 脚本 | 产物 |
|------|------|
| `generate_btst_doc_bundle.py` | 文档 bundle (主入口) |
| `generate_btst_next_day_trade_brief.py` | 次日交易简报 |
| `generate_btst_next_day_priority_board.py` | 次日优先级看板 |
| `generate_btst_opening_watch_card.py` | 开盘观察卡 |
| `generate_btst_premarket_execution_card.py` | 盘前执行卡 |
| `generate_btst_early_runner_daily_tables.py` | 早盘 runner 每日表 |
| `generate_btst_realized_prices.py` | 已实现价格表 |
| `generate_btst_monthly_reconciliation_pack.py` | 月度对账包 |
| `generate_btst_decision_weekly_calibration.py` | 周度决策校准 |
| `generate_btst_default_merge_review.py` | 默认 merge 复核 |
| `generate_btst_default_merge_historical_counterfactual.py` | 默认 merge 历史反事实 |
| `generate_btst_default_merge_strict_counterfactual.py` | 默认 merge 严格反事实 |
| `generate_btst_merge_replay_validation.py` | Merge replay 验证 |
| `generate_btst_continuation_merge_candidate_ranking.py` | Continuation merge 候选排名 |
| `generate_btst_tplus2_continuation_eligible_execution.py` | T+2 持续可执行 |
| `generate_btst_tplus2_continuation_eligible_gate.py` | T+2 持续 gate |
| `generate_btst_tplus2_continuation_execution_gate.py` | T+2 持续执行 gate |
| `generate_btst_tplus2_continuation_execution_overlay.py` | T+2 持续执行 overlay |
| `generate_btst_tplus2_continuation_expansion_board.py` | T+2 持续扩张看板 |
| `generate_btst_tplus2_continuation_governance_board.py` | T+2 持续 governance 看板 |
| `generate_btst_tplus2_continuation_lane_rulepack.py` | T+2 持续 lane 规则包 |
| `generate_btst_tplus2_continuation_observation_pool.py` | T+2 持续观察池 |
| `generate_btst_tplus2_continuation_promotion_gate.py` | T+2 持续晋升 gate |
| `generate_btst_tplus2_continuation_promotion_review.py` | T+2 持续晋升复核 |
| `generate_btst_tplus2_continuation_validation_queue.py` | T+2 持续验证队列 |
| `generate_btst_tplus2_continuation_watchboard.py` | T+2 持续 watchboard |
| `generate_btst_tplus2_continuation_watchlist_execution.py` | T+2 持续 watchlist 执行 |
| `generate_report_summary.py` | 单报告摘要 |
| `generate_reports_manifest.py` | 报告 manifest |

---

## 8. 一次性 / Quarantine (已废弃)

> ⚠️ **不要运行这些**,只用于考古/回溯。

| 脚本 | 状态 | 说明 |
|------|------|------|
| `_btst_p1_p2_next_actions.py` | ⚠️ 已废弃 | 0330 P1/P2 follow-up (P0D 已落地) |
| `_p0_baseline_stats.py` | ⚠️ 已废弃 | 0330 P0 baseline freeze (已 frozen) |
| `tmp_momentum_analysis.py` | ⚠️ 一次性 | 早期动量因子调研 (已被 `btst_factor_ic_analysis` 替代) |
| `update_live_replay_doc_600519_p1.py` | ⚠️ 一次性 | 600519 P1 live replay 文档更新 |
| `summarize_live_replay_600519_p1.py` | ⚠️ 一次性 | 600519 P1 live replay 摘要 |

---

## 9. Replay / 重建

| 脚本 | 状态 | 说明 |
|------|------|------|
| `replay_layer_c_agent_contributors.py` | ⚠️ 一次性 | Layer C agent 贡献度 replay |
| `replay_selection_target_calibration.py` | ⚠️ 一次性 | 选择目标校准 replay |
| `rebuild_catalyst_theme_diagnostics_from_frozen_reports.py` | ⚠️ 一次性 | 从 frozen reports 重建 catalyst/theme 诊断 |

---

## 使用示例

### 例 1: 跑完整的纸面交易流程
```bash
# 加载 .env (必须)
source .env

# 跑纸面交易 (生成候选 + 风控 + 下单模拟)
.venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-06-01 \
  --end-date 2026-06-05 \
  --tickers 300724
```

### 例 2: 跑次日包 (doc bundle + 简报)
```bash
.venv/bin/python scripts/run_btst_next_day_package.py
# 产物: data/reports/btst_next_day_package_<timestamp>/
```

### 例 3: 跑夜维控制塔 (每日 23:00 cron)
```bash
.venv/bin/python scripts/run_btst_nightly_control_tower.py
# 产物: data/reports/nightly_control_tower_<date>/
```

### 例 4: 回测 + Profile 对比
```bash
# 20 天回测
.venv/bin/python scripts/btst_20day_backtest.py --ticker 000001

# 网格搜索阈值
.venv/bin/python scripts/btst_threshold_grid_search.py \
  --select-threshold-range 0.30,0.45,0.05 \
  --near-miss-range 0.20,0.30,0.05

# Profile 对比
.venv/bin/python scripts/btst_profile_compare.py \
  --profile-a ic_v3 --profile-b btst_precision_v2 --date 20260601
```

### 例 5: 数据缓存管理
```bash
# 查看缓存状态
.venv/bin/python scripts/manage_data_cache.py stats

# 清空缓存 (危险!)
.venv/bin/python scripts/manage_data_cache.py clear --yes
```

### 例 6: LLM 诊断
```bash
# 列出所有可用模型
.venv/bin/python scripts/list-models.py

# 检查 LLM 路由
.venv/bin/python scripts/inspect_llm_routing.py

# 汇总 LLM 指标
.venv/bin/python scripts/summarize_llm_metrics.py logs/<file>.jsonl
```

### 例 7: 因子分析
```bash
# 因子 IC
.venv/bin/python scripts/btst_factor_ic_analysis.py

# 深度 IC (分位 + 滚动)
.venv/bin/python scripts/btst_factor_deep_ic_analysis.py

# 市场状态分析
.venv/bin/python scripts/btst_market_regime_analysis.py
```

---

## 命名约定

| 前缀 | 含义 |
|------|------|
| `run_*` | 生产入口,直接 `python xxx.py` 跑 |
| `generate_*` | 由 `run_*` 调用,生成具体产物 |
| `analyze_*` | ⚠️ 一次性实验/分析/诊断 (已废弃) |
| `backfill_*` / `refresh_*` / `rebuild_*` | ⚠️ 一次性数据回填/重建 |
| `validate_*` | 验证脚本 (部分生产用) |
| `audit_*` / `scan_*` / `probe_*` | ⚠️ 一次性审计/扫描 |
| `summarize_*` / `export_*` | ⚠️ 一次性汇总/导出 |
| `supervise_*` | 后台监督 (A/B + 批跑) |
| `inspect_*` / `list-*` | 诊断/列出 |
| `manage_*` | 状态管理 (cache / research feedback) |
| `fill_*` / `update_*` | ⚠️ 一次性填充/更新 |
| `replay_*` | ⚠️ 一次性历史重放 |
| `_*.py` | ⚠️ 内部/废弃脚本 (下划线开头) |
| `tmp_*.py` | ⚠️ 临时脚本,不要运行 |
| `*_helpers.py` / `*_utils.py` | **库模块**,import 用,不能直接跑 |

---

## 相关文档

- [docs/zh-cn/product/feature-proposals.md §5.6](../docs/zh-cn/product/feature-proposals.md) — 原始提案
- [docs/zh-cn/product/arch/](../docs/zh-cn/product/arch/) — 架构文档
- [CLAUDE.md](../CLAUDE.md) — 项目入口

---

**最后更新**: 2026-06-06 (策略研究团队第二轮审计 + 2.2 摘要脚本 + 新增目录条目)
