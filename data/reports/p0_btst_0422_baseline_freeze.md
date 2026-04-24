# P0 BTST 0422 Baseline Freeze

- evidence_doc: docs/zh-cn/factors/BTST/optimize0422/01-0422-实盘复盘与数据证据.md
- selected_close_win_rate: 47.27
- selected_expectation: -0.0448
- post_fee_expectation_range: -0.16 ~ -0.12

## Field Inventory

- selection_snapshot_fields: artifact_status, artifact_version, btst_regime_gate, buy_orders, catalyst_theme_candidates, catalyst_theme_shadow_candidates, data_available_until, decision_timestamp, dual_target_delta, experiment_id, funnel_diagnostics, market, market_state, pipeline_config_snapshot, rejected, research_view, run_id, selected, selection_targets, sell_orders, short_trade_view, target_mode, target_summary, trade_date, universe_summary
- session_summary_fields: artifacts, btst_0422_flags, daily_event_stats, data_cache, data_cache_benchmark, data_cache_benchmark_status, dual_target_summary, end_date, execution_plan_provenance, fast_selected_analysts, final_portfolio_snapshot, initial_capital, llm_error_digest, llm_observability_summary, llm_route_provenance, mode, model_name, model_provider, performance_metrics, plan_generation, portfolio_values, research_feedback_summary, selected_analysts, short_trade_target_profile_name, short_trade_target_profile_overrides, start_date, tickers

## Feature Flags

- p1_regime_gate_shadow: BTST_0422_P1_REGIME_GATE_MODE @ src/execution/daily_pipeline.py::run_post_market (default=off)
- p2_regime_gate_enforce: BTST_0422_P2_REGIME_GATE_MODE @ src/execution/daily_pipeline.py::run_post_market (default=off)
- p3_prior_quality_hard_gate: BTST_0422_P3_PRIOR_QUALITY_MODE @ src/targets/router.py::build_selection_targets (default=off)
- p4_prior_shrinkage: BTST_0422_P4_PRIOR_SHRINKAGE_MODE @ src/targets/profiles.py::ShortTradeTargetProfile (default=off)
- p5_execution_contract: BTST_0422_P5_EXECUTION_CONTRACT_MODE @ src/targets/router.py::build_selection_targets (default=off)
- p6_risk_budget_overlay: BTST_0422_P6_RISK_BUDGET_MODE @ src/execution/daily_pipeline.py::build_buy_orders_with_diagnostics (default=off)
