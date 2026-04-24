# P6 BTST Risk Budget Overlay Eval

**Generated on:** 2026-04-24
**Snapshots analyzed:** 1

## 风险预算矩阵说明

| 条件 | 风险预算比率 | 说明 |
|---|---:|---|
| halt × any × any | 0.0 | 停止正式持仓；只保留观察或空仓。 |
| shadow_only × any × any | 0.0 | 仅 paper/shadow，正式仓位为 0。 |
| normal_trade × execution_ready × formal_full | 1.0 | 保持默认正式仓位。 |
| normal_trade × execution_ready × formal_capped | 0.6 | 执行合格但质量偏弱，降配而非满仓。 |
| aggressive_trade × execution_ready × formal_full | 1.15 | 强势窗口允许放大到上限。 |
| aggressive_trade × execution_ready × formal_capped | 0.75 | 强势窗口下仍保留折价风险预算。 |
| any × watch_only/reject/research_only × any | 0.0 | 观察层或不合格样本不进入正式持仓。 |

## Session Summary Overlay

- gate_distribution: {'normal_trade': 1, 'shadow_only': 1}
- formal_exposure_distribution: {'reduced': 1, 'zero_budget': 1}
- suppressed_position_summary: {'zero_budget_count': 1, 'reduced_budget_count': 1}

## 强势日正式暴露保留

- strong_day_retention_summary: {'strong_day_candidate_count': 1, 'retained_formal_exposure_count': 1, 'retained_formal_exposure_rate': 1.0}

## Comparison Samples

| ticker | gate | prior | contract | ratio | exposure_bucket |
|---|---|---|---|---:|---|
| 688313 | shadow_only | watch_only | watch_only | 0.0 | zero_budget |
| 300724 | normal_trade | execution_ready | formal_capped | 0.6 | reduced |
