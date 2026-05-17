# win-rate-first-rollout-governance-2026-05-17

## 原理
- 这次改动不是把 `trend_continuation` / `trend_corrected` 直接推上生产，而是先把“是否值得升级”为 active BTST profile 的判断改成 win-rate-first 口径。
- `scripts/optimize_profile.py` 现在会显式构建 `win_rate_first_verdict` / `win_rate_first_verdict_detail`：要求 `next_close_positive_rate_delta` 与 `next_high_hit_rate_delta` 都有正向提升，同时 payoff / expectancy / coverage 只能承受有限退化。
- 一旦存在 strict-objective、structural guardrail 或 walk-forward rollout blockers，structured `rejection_reasons` 会以 `rollout_blocked` 为优先原因，阻止“局部改善”掩盖整体不可发布的事实。

## 提升效果
- 提升点在于**rollout 决策更可靠**：即使某个变体在局部窗口里看起来像有 T+1 或 T+2 改善，只要总体上不满足 win-rate-first 或仍被 blocker 卡住，就不会被误判为可推广 profile。
- 这让 BTST 团队能够更明确地区分三类情况：
  1. 真正满足 win-rate-first 的候选；
  2. 只在局部窗口改善、但仍不适合替代 baseline 的候选；
  3. 由于 objective-fit、execution-edge 或结构性问题必须继续 hold 的候选。
- 本轮最重要的结论不是“趋势修正版已经上线”，而是“它现在会被更严格、更透明地拦在 rollout gate 前”，从而优先保护胜率目标。

## 如何验证
- 回顾性证据显示 Round 89 的方向修正很重要，但还不能直接宣称已成为稳定 BTST 升级：
  - retrospective 明确指出 `trend_corrected_v1` 当时尚未成为 skill 报告使用的 active profile，现网仍是 `btst_precision_v2` 口径；
  - 同一份 retrospective 也指出，仓内证据仍不足以证明“整体、稳定、普遍地显著提高了 BTST 次日胜率”。
- 多窗口验证 `data/reports/btst_trend_continuation_strength_v2_multi_window_validation.md` 的汇总结论也是保守的：
  - `variant_supports_t1_count: 1`
  - `variant_improves_t2_only_count: 1`
  - `keep_baseline_count: 3`
  - `mixed_count: 12`
  - aggregate recommendation: `Variant behaves like a T+2 tradeoff rather than a strict BTST upgrade; keep the baseline default unless the objective changes.`
- 当前 rollout 侧的行为验证来自：
  - `tests/test_optimize_profile_script.py`：验证 rejected verdict 会把 action 变成 `hold`，并把 `rollout_blocked` 提升到 blocker-first 结构化原因；
  - `tests/backtesting/test_walk_forward.py`：验证 walk-forward summary 会暴露 `win_rate_first_verdict` / `win_rate_first_verdict_detail`，且 blockers 存在时优先给出 `rollout_blocked`。

## 观察到的权衡
- 这套治理会降低“看到一点局部改善就想切 profile”的冲动，代价是 profile 升级节奏更慢。
- 某些候选在 T+2 或局部窗口看起来更好，但如果 T+1 胜率、coverage 或 blocker 语境不干净，系统仍会保守地维持 baseline。
- 因此它更像是“防止错误升级”的治理增强，而不是“立刻提高收益曲线”的激进优化。

## 如何使用
- 当运行 `scripts/optimize_profile.py`、compare、walk-forward 或后续 profile rollout 评审时，应直接读取 `win_rate_first_verdict`、`win_rate_first_verdict_detail`、`blockers` 和 markdown 中的 verdict 段落，而不是只看单一 uplift 数字。
- 对 `ai-hedge-fund-btst` 的使用含义：
  - 如果当前 artifacts 仍然显示 `hold`、`default_fallback`、`rollout_blocked` 或 baseline-only recommendation，最终中文报告必须把这种保守状态写清楚；
  - 不能因为有这份文档，就把趋势修正版包装成已经验证通过、已经替代 baseline 的正式升级。
