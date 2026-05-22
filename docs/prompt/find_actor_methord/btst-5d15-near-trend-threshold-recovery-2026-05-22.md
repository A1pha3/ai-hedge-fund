# btst-5d15-near-trend-threshold-recovery-2026-05-22

## 原理
- 本轮不是推广新因子，而是验证 `near_trend_threshold` 这条极窄恢复线，看看它是否值得继续投入研究资源。
- 结论只基于 `data/reports/btst_5d_15pct_near_trend_threshold_recovery_latest.json` 与同名 Markdown，不把这次恢复验证当成 runtime 推广依据。

## recovered cohort
- 当前真实语料里只恢复出 1 行，ticker 是 `600392`。
- 这 1 行虽然 `beta_tradeable_rate=1.0`，但 `hit_rate_15pct=0.0`，`mean_max_future_high_return_2_5d=0.0688`，离“5天内超过15%且概率大于55%”的目标很远。

## unrecovered baseline
- 当前 `near_trend_threshold` 桶里没有留下可比较的 unrecovered baseline，`row_count=0`。
- 这意味着本轮没有形成“恢复前后同桶对照”，gamma 不能把这条线当成已验证结构。

## trend baseline
- 当前 `trend_continuation` 基线有 402 行，`hit_rate_15pct=0.2587`，`mean_max_future_high_return_2_5d=0.105`，`beta_tradeable_rate=0.903`。
- 即使和并不达标的 trend baseline 比，恢复样本的收益强度也没有优势。

## alpha 结论
- alpha 视角下，这条恢复线暂时没有展示可重复的正向证据。
- 1 个样本既不足以说明阈值恢复有效，也不足以支持后续因子推广。

## beta 结论
- beta 视角下，恢复样本的交易性不是主问题，主问题是样本太少且收益表现弱。
- 因此不应该为了制造更多恢复样本去主动放松执行门槛。

## gamma 结论
- 本轮治理结论是 `hold_recovery_too_small_or_noisy`。
- gamma 不批准把这条恢复线升级为新规则，也不批准接入 `ai-hedge-fund-btst`。

## 下一轮动作
- 继续保持 fail-closed：先观察后续语料里是否还能出现更多 `near_trend_threshold` 真实样本。
- 如果后续依然无法形成 recovered vs unrecovered 的同桶对照，应把这条恢复线降级为低优先级，而不是强行推进。
- 暂不推进任何内容到 `docs/prompt/find_actor/`，也不做 BTST runtime skill 集成。
