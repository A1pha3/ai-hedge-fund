# Targeted Structural Conflict Release Review

## Scope
- report_dir: /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329
- targets: ['2026-03-25:300724']
- profile_overrides: {'hard_block_bearish_conflicts': [], 'overhead_conflict_penalty_conflicts': [], 'near_miss_threshold': 0.42}
- total_case_count: 32
- matched_target_case_count: 1
- changed_case_count: 1

## Decision Counts
- before: {'rejected': 27, 'blocked': 5}
- after: {'rejected': 27, 'blocked': 4, 'near_miss': 1}
- transitions: {'rejected->rejected': 27, 'blocked->blocked': 4, 'blocked->near_miss': 1}

## Changed Cases
- 2026-03-25 300724: blocked -> near_miss, before_score=0.37845526762751325, after_score=0.4235, target_case=True, candidate_source=layer_c_watchlist

## Recommendation
- 当前 case-based 定向释放只改变目标样本。2026-03-25 / 300724 从 blocked -> near_miss，未污染其它 31 个样本，可作为 300724-only 受控实验入口。
