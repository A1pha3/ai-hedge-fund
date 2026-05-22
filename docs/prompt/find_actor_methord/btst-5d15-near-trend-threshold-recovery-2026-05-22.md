# btst-5d15-near-trend-threshold-recovery-2026-05-22

## 原理
- 本轮不是推广新因子，而是验证 `near_trend_threshold` 这条极窄恢复线是否值得继续投入研究资源。
- 结论仅基于 `data/reports/btst_5d_15pct_near_trend_threshold_recovery_latest.json` 与同名 Markdown 产物，不将这次恢复验证直接视为运行时推广依据。

## 恢复样本组
- 当前真实语料中仅恢复出 1 行，ticker 为 `600392`。
- 这 1 行虽然 `beta_tradeable_rate=1.0`，但 `hit_rate_15pct=0.0`，`mean_max_future_high_return_2_5d=0.0688`，距离“5 天内超过 15%，且命中概率大于 55%”的目标仍然很远。

## 未恢复基线
- 当前 `near_trend_threshold` 桶内没有保留下可比较的未恢复基线，`row_count=0`。
- 这意味着本轮没有形成“恢复前 vs 恢复后”的同桶对照，gamma 不能将这条线视为已验证结构。

## 趋势延续基线
- 当前 `trend_continuation` 基线共有 402 行，`hit_rate_15pct=0.2587`，`mean_max_future_high_return_2_5d=0.105`，`beta_tradeable_rate=0.903`。
- 即使与并未达标的 `trend_continuation` 基线相比，恢复样本的收益强度也没有优势。

## alpha 结论
- 从 alpha 侧看，这条恢复线暂时没有展示出可重复的正向证据。
- 仅有 1 个样本，既不足以说明阈值恢复有效，也不足以支持后续因子推广。

## beta 结论
- 从 beta 侧看，恢复样本的可交易性不是主问题，真正的问题是样本量过小且收益表现偏弱。
- 因此，不应为了制造更多恢复样本而主动放松执行门槛。

## gamma 结论
- 本轮治理结论为 `hold_recovery_too_small_or_noisy`。
- gamma 不批准将这条恢复线升级为新规则，也不批准接入 `ai-hedge-fund-btst`。

## 下一轮动作
- 继续保持默认不放行（fail-closed）：先观察后续语料中是否还能出现更多 `near_trend_threshold` 真实样本。
- 如果后续依然无法形成“已恢复 vs 未恢复”的同桶对照，应将这条恢复线降级为低优先级，而不是强行推进。
- 暂不推进任何内容到 `docs/prompt/find_actor/`，也不做 BTST 运行时技能集成。
