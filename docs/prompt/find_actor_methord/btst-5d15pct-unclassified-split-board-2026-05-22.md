# btst-5d15pct-unclassified-split-board-2026-05-22

## 原理
- 本轮不是升级新因子，而是拆开 round1 中 `unclassified` 这一大样本，判断其主要是噪声过多，还是包含少量值得恢复的近阈值结构。
- 结论仅基于 `data/reports/btst_5d_15pct_unclassified_split_board_latest.json` 与同名 Markdown 产物，不将本次分析结果直接视为推广依据。

## 主要样本桶
- `missing_all_core_features`：347 行，是最大的噪声桶，主要来自 `layer_c_watchlist`、`short_trade_boundary`、`watchlist_filter_diagnostics` 与 `layer_b_boundary`，`hit_rate_15pct=0.098`。当前不值得优先恢复。
- `other_unclassified`：54 行，虽然 `hit_rate_15pct=0.3704`、`mean_max_future_high_return_2_5d=0.1226`，但结构仍不够稳定，现阶段更像“待继续拆分”的混合桶，不适合直接推广。
- `watchlist_only_low_signal`：52 行，全部来自 `layer_c_watchlist`，`hit_rate_15pct=0.1346`，更接近低信号观察样本。
- `near_trend_threshold`：仅 1 行，但这是当前拆板结果中唯一给出 `recover_threshold_near_miss` 的桶，说明真正值得继续跟进的不是大面积放松规则，而是极窄的近趋势阈值恢复。

## alpha 结论
- 拆板分析没有把 round1 直接变成可推广 alpha，但回答了一个关键问题：当前 alpha 失效的主因不是执行，而是 `unclassified` 噪声过大。
- 347 行 `missing_all_core_features` 明确说明，大量样本连 round1 所需的核心结构都没有；如果直接参与排行榜，只会稀释真正有价值的结构。
- 唯一被判为 `recover_threshold_near_miss` 的是 `near_trend_threshold`，说明下一轮 alpha 研究应先做极窄的趋势近阈值恢复，而不是全面扩张研究面。

## beta 结论
- beta 仍不是当前主矛盾。本轮拆板的任务是解释结构，而不是验证成交与执行可行性。
- 就当前分桶结果看，更需要减少无结构样本进入研究面，而不是为了提高覆盖率去放松执行门槛。

## gamma 结论
- 从 gamma 侧看，下一轮最合理的动作是继续保持 `hold`，先做 `near_trend_threshold` 的结构恢复验证。
- 对于 `missing_all_core_features`、`watchlist_only_low_signal` 这类样本桶，当前更适合作为噪声样本管理，而不是继续提高优先级。

## 下一轮动作
- 主动作：围绕 `near_trend_threshold` 做一轮极窄的结构恢复验证。
- 次动作：将 `missing_all_core_features` 视为噪声主桶，优先减少其对 round1 研究面的稀释，而不是试图整体救回。
- 暂不推进任何因子到 `docs/prompt/find_actor/`，也不接入 `ai-hedge-fund-btst`。
