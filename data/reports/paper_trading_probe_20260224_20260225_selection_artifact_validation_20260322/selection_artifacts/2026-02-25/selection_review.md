# 选股审查日报 - 2026-02-25

## 运行概览
- run_id: paper_trading_probe_20260224_20260225_selection_artifact_validation_20260322
- universe: 200
- candidate_count: 200
- high_pool_count: 2
- watchlist_count: 0
- buy_order_count: 0

## 今日入选股票

- 无入选股票

## 接近入选但落选

### 1. 300724
- rejection_stage: watchlist
- 原因: score_final_below_watchlist_threshold

### 2. 600988
- rejection_stage: watchlist
- 原因: decision_avoid

## 当日漏斗观察
- Layer A -> candidate: 200 -> 200
- candidate -> high_pool: 200 -> 2
- high_pool -> watchlist: 2 -> 0
- watchlist -> buy_orders: 0 -> 0

## 研究员标注说明
- review_scope 以 watchlist 为主
- buy_orders 只作为下游承接参考

## 附加诊断
- funnel_diagnostics_keys: counts, filters, sell_orders
