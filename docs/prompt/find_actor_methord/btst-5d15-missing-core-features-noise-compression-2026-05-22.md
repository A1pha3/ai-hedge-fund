# btst-5d15-missing-core-features-noise-compression-2026-05-22

## 原理
- 本轮不是挖掘新因子，而是拆解 `missing_all_core_features` 这 347 行“核心特征全缺失”样本，判断它们究竟属于观察噪声、边界合约污染，还是应单独隔离的上游来源。
- 结论仅基于 `data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.json` 与同名 Markdown 产物，不将这次噪声压缩结果直接视为运行时策略升级依据。

## 主要根因
- `watchlist_empty_payload`：146 行，全部来自 `layer_c_watchlist`，`hit_rate_15pct=0.1438`，`mean_max_future_high_return_2_5d=0.0637`。虽然可解释性载荷（explainability payload）中带有元数据，但核心因子键仍全部为 0，更接近观察层噪声，不宜继续留在因子研究面。
- `boundary_without_explainability`：121 行，来自 `short_trade_boundary` 与 `layer_b_boundary`，`hit_rate_15pct=0.0661`，`mean_max_future_high_return_2_5d=0.0735`。这不是“有 alpha 但未被识别”，而是边界流程带入了元数据，却没有补齐 round1 核心结构；应优先检查候选来源契约（candidate-source contract）。
- `diagnostic_probe_without_core_features`：71 行，全部来自 `watchlist_filter_diagnostics`，`hit_rate_15pct=0.0704`，`mean_max_future_high_return_2_5d=0.0541`。这类样本更适合作为诊断层语料，不应继续混入因子研究面。
- `unknown_missing_core_contract`：9 行，全部来自 `upstream_liquidity_corridor_shadow`，`hit_rate_15pct=0.0`。当前应将其单独隔离并继续研究，不适合与主研究面混放。

## alpha 结论
- 从 alpha 侧看，这 347 行样本的主问题不是“遗漏了一个强因子”，而是核心结构根本没有进入 round1 因子研究面。
- 压缩这部分噪声的价值，在于让下一轮 round1 / round2 因子搜索面对更干净的样本，而不是直接提高当前胜率。

## beta 结论
- 从 beta 侧看，最值得优先追查的是 `boundary_without_explainability`，因为它明确暴露出“元数据进入了流程，但核心因子键没有进入流程”的合约缺口。
- `layer_c_watchlist` 与 `watchlist_filter_diagnostics` 这两类样本更适合从因子研究面中隔离出去，避免继续污染统计面。

## gamma 结论
- gamma 当前批准的治理动作分为三段：
  - `watchlist_empty_payload` -> `ignore_observation_noise`
  - `boundary_without_explainability` -> `inspect_candidate_source_contract`
  - `diagnostic_probe_without_core_features` -> `exclude_from_factor_surface`
  - `unknown_missing_core_contract` -> `split_into_separate_research_surface`

## 下一轮动作
- 优先围绕 `boundary_without_explainability` 做候选来源契约检查，因为这是当前最像“系统层可修复污染”的主桶。
- 将 `layer_c_watchlist` 与 `watchlist_filter_diagnostics` 的“仅含元数据”样本从后续因子研究面中隔离，不再混入 alpha 研究面。
- 暂不推进任何内容到 `docs/prompt/find_actor/`，也不接入 `ai-hedge-fund-btst`。
