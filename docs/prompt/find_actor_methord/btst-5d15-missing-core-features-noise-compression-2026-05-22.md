# btst-5d15-missing-core-features-noise-compression-2026-05-22

## 原理
- 本轮不是挖新因子，而是拆开 `missing_all_core_features` 这 347 行空核心因子样本，判断它们到底是观察噪声、边界合约污染，还是需要单独隔离的上游来源。
- 这份结论只基于 `data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.json` 与同名 Markdown，不把噪声压缩结果当成 runtime 升级结论。

## 主要 root cause
- `watchlist_empty_payload`：146 行，全部来自 `layer_c_watchlist`，`hit_rate_15pct=0.1438`，`mean_max_future_high_return_2_5d=0.0637`。虽然 explainability payload 里有元数据，但核心因子键仍然是 0，更像观察面噪声，不适合继续进入因子研究面。
- `boundary_without_explainability`：121 行，来自 `short_trade_boundary` 和 `layer_b_boundary`，`hit_rate_15pct=0.0661`，`mean_max_future_high_return_2_5d=0.0735`。这不是“有 alpha 但没被识别”，而是边界流程给了元数据，却没有给 round1 核心结构，应优先检查 candidate-source contract。
- `diagnostic_probe_without_core_features`：71 行，全部来自 `watchlist_filter_diagnostics`，`hit_rate_15pct=0.0704`，`mean_max_future_high_return_2_5d=0.0541`。更适合作为诊断面样本，而不是继续留在因子面。
- `unknown_missing_core_contract`：9 行，全部来自 `upstream_liquidity_corridor_shadow`，`hit_rate_15pct=0.0`，当前需要单独隔离研究，不适合与主研究面混放。

## alpha 结论
- alpha 视角下，这 347 行样本的主问题不是“遗漏了一个强因子”，而是核心结构根本没有进入 round1 因子面。
- 压缩这部分噪声的价值，在于让下一轮 round1/round2 因子搜索面对更干净的样本，而不是直接提高胜率。

## beta 结论
- beta 视角下，最需要追的是 `boundary_without_explainability`，因为它说明边界来源把元数据带进来了，但没有把核心因子键带进来。
- `layer_c_watchlist` 与 `watchlist_filter_diagnostics` 这两类样本则更适合从因子研究面隔离出去，避免继续污染统计面。

## gamma 结论
- gamma 当前批准的治理动作是三段式：
- `watchlist_empty_payload` -> `ignore_observation_noise`
- `boundary_without_explainability` -> `inspect_candidate_source_contract`
- `diagnostic_probe_without_core_features` -> `exclude_from_factor_surface`
- `unknown_missing_core_contract` -> `split_into_separate_research_surface`

## 下一轮动作
- 先围绕 `boundary_without_explainability` 做 candidate-source contract 检查，因为这是当前最像“系统面可修复污染”的主桶。
- 把 `layer_c_watchlist` 和 `watchlist_filter_diagnostics` 的 metadata-only 样本从后续因子研究面里隔离，不再把它们混进 alpha surface。
- 暂不推进任何内容到 `docs/prompt/find_actor/`，也不接入 `ai-hedge-fund-btst`。
