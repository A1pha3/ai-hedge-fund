# P4 BTST Prior Shrinkage Eval

**Generated on:** 2026-04-24
**Snapshots analyzed:** 1

## Comparison Summary

- `prior_count`: 3
- `avg_sample_reliability`: 0.377778
- `avg_raw_high_hit_rate`: 0.923333
- `avg_shrunk_high_hit_rate`: 0.756667
- `avg_raw_close_positive_rate`: 0.886667
- `avg_shrunk_close_positive_rate`: 0.693333

## Raw vs Shrunk Comparison Samples

| ticker | decision | n | reliability | raw high | shrunk high | raw close+ | shrunk close+ |
|---|---|---:|---:|---:|---:|---:|---:|
| 300724 | selected | 2 | 0.200 | 1.000 | 0.720 | 1.000 | 0.660 |
| 300750 | near_miss | 4 | 0.333 | 0.950 | 0.770 | 0.900 | 0.700 |
| 002594 | near_miss | 12 | 0.600 | 0.820 | 0.780 | 0.760 | 0.720 |

---

**Flag:** `BTST_0422_P4_PRIOR_SHRINKAGE_MODE=enforce` switches selected/near_miss prior-sensitive logic to the shrunk prior surface.
