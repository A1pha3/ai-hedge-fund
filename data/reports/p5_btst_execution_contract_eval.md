# P5 BTST Execution Contract Eval

**Generated on:** 2026-04-24
**Snapshots analyzed:** 1

## Contract Summary

- `target_count`: 3
- `execution_eligible_count`: 1
- `selected_count`: 1
- `near_miss_count`: 1
- `research_only_count`: 1

## selected / near_miss / research_only 语义对比

### selected
- formal_buy_flow: True
- definition: score passed + gate allowed + prior quality qualified + formal execution eligible

### near_miss
- formal_buy_flow: False
- definition: observation only; keeps visibility but never enters formal buy-order flow

### research_only
- formal_buy_flow: False
- definition: research or upgrade queue only; excluded from formal BTST performance stats

## Comparison Samples

| ticker | bucket | decision | execution_eligible | downgrade_reasons | gate | prior |
|---|---|---|---|---|---|---|
| 002028 | research_only | rejected | False | research_only_source_not_formal_execution, btst_regime_gate_not_tradeable | shadow_only | reject |
| 688313 | near_miss | near_miss | False | historical_prior_not_execution_ready | normal_trade | watch_only |
| 300724 | selected | selected | True | none | normal_trade | execution_ready |
