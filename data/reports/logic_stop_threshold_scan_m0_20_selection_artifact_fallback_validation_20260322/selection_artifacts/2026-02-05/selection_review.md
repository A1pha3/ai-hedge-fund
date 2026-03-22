# 选股审查日报 - 2026-02-05

## 运行概览
- run_id: logic_stop_threshold_scan_m0_20_selection_artifact_fallback_validation_20260322
- universe: 200
- candidate_count: 200
- high_pool_count: 1
- watchlist_count: 1
- buy_order_count: 1

## 今日入选股票

### 1. 300724
- final_score: 0.2993
- buy_order: yes
- Layer B 因子摘要:
  - logic_score: value=0.2993 (plan.logic_scores)
  - fundamental: weight=0.4444 (market_state.adjusted_weights)
  - trend: weight=0.3232 (market_state.adjusted_weights)
- 入选原因:
  - Layer B 综合分数为 0.5629
  - Layer C 综合分数为 -0.0230
  - 最终得分为 0.2993
- 建议重点复核:
  - B/C 分歧是否意味着选股逻辑仍然不够稳定
  - 当前 Layer B 因子摘要来自历史回放兼容字段，需结合原始 plan 字段复核

## 接近入选但落选

- 无接近入选但落选的样本

## 当日漏斗观察
- Layer A -> candidate: 200 -> 200
- candidate -> high_pool: 200 -> 1
- high_pool -> watchlist: 1 -> 1
- watchlist -> buy_orders: 1 -> 1

## 研究员标注说明
- review_scope 以 watchlist 为主
- buy_orders 只作为下游承接参考

## 附加诊断
- funnel_diagnostics_keys: blocked_buy_tickers, counts, filters, sell_orders
