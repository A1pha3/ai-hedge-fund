# btst-5d15pct-unclassified-split-board-2026-05-22

## 原理
- 本轮不是升级新因子，而是拆开 round1 里的 `unclassified` 大样本，判断到底是噪声太多，还是存在少量可恢复的近阈值结构。
- 这份结论只基于 `data/reports/btst_5d_15pct_unclassified_split_board_latest.json` 与同名 Markdown，不把分析结果当成推广结论。

## 主要桶
- `missing_all_core_features`：347 行，是最大的噪声桶，主要来自 `layer_c_watchlist`、`short_trade_boundary`、`watchlist_filter_diagnostics` 和 `layer_b_boundary`，`hit_rate_15pct=0.098`，当前不值得优先恢复。
- `other_unclassified`：54 行，虽然 `hit_rate_15pct=0.3704`、`mean_max_future_high_return_2_5d=0.1226`，但结构仍然不够稳定，现阶段更像“待继续拆分”的混合桶，不适合直接推广。
- `watchlist_only_low_signal`：52 行，全部来自 `layer_c_watchlist`，`hit_rate_15pct=0.1346`，更接近低信号观察样本。
- `near_trend_threshold`：只有 1 行，但这是当前 split board 唯一给出 `recover_threshold_near_miss` 的桶，说明真正值得继续跟的不是大面积放松规则，而是非常窄的近趋势阈值恢复。

## alpha 结论
- split board 没有把 round1 直接变成可推广 alpha，但它回答了一个关键问题：当前 alpha 失败主要不是执行问题，而是 `unclassified` 噪声过大。
- 347 行 `missing_all_core_features` 明确说明，大量样本连 round1 所需的核心结构都没有，直接参与排行榜只会稀释真正有价值的结构。
- 唯一被判为 `recover_threshold_near_miss` 的是 `near_trend_threshold`，说明下一轮 alpha 研究应该先做极窄的趋势近阈值恢复，而不是全面扩研究面。

## beta 结论
- beta 仍然不是当前主矛盾。本轮 split board 的主任务是解释结构，不是处理成交和执行可行性。
- 从当前板块看，更需要的是减少无结构样本进入研究面，而不是为了覆盖率去放松执行门槛。

## gamma 结论
- gamma 视角下，下一轮最合理的动作是：保持推广姿态为 hold，先做 `near_trend_threshold` 的结构恢复验证。
- 对于 `missing_all_core_features`、`watchlist_only_low_signal` 这类桶，当前更适合当作噪声样本管理，而不是继续给它们更高优先级。

## 下一轮动作
- 主动作：围绕 `near_trend_threshold` 做一轮极窄的结构恢复验证。
- 次动作：把 `missing_all_core_features` 视为噪声主桶，优先减少其对 round1 surface 的稀释，而不是试图整体救回。
- 暂不推进任何因子到 `docs/prompt/find_actor/`，也不接入 `ai-hedge-fund-btst`。
