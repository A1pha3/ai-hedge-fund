# btst-5d15pct-round1-candidate-pack-2026-05-22

## 原理
- 本轮不是直接上线新因子，而是把 5 日内上涨 15%、命中率超过 55% 的研究目标，先落成真实可复核的 round1 排行榜。
- round1 只看三类事件原型、三类因子家族和两类二阶交互，并统一经过 alpha / beta / gamma 三道门。
- 结论只基于 `data/reports/btst_5d_15pct_factor_research_round1_latest.json` 与同名 Markdown 产物，不额外猜测未验证提升。

## 本轮候选
- 事件原型 Top 2：
  - `trend_continuation`：hit_rate_15pct=0.2587，mean_max_return=0.105，beta_tradeable_rate=0.903
  - `unclassified`：hit_rate_15pct=0.1344，mean_max_return=0.0709，beta_tradeable_rate=0.9251
- 因子家族 Top 3：
  - `trend_family`：hit_rate_15pct=0.2574，mean_max_return=0.1028，beta_tradeable_rate=0.9077
  - `breakout_family`：hit_rate_15pct=0.2574，mean_max_return=0.1028，beta_tradeable_rate=0.9077
  - `volume_quality_family`：hit_rate_15pct=0.1928，mean_max_return=0.0869，beta_tradeable_rate=0.9147
- 二阶交互 Top 2：
  - `trend_x_close_strength`：hit_rate_15pct=0.1928，mean_max_return=0.0869，beta_tradeable_rate=0.9147
  - `breakout_x_volume_quality`：hit_rate_15pct=0.1928，mean_max_return=0.0869，beta_tradeable_rate=0.9147

## alpha 结论
- 本轮总样本 `row_count=856`，但没有任何事件原型、因子家族或交互项达到 alpha 门槛。
- 当前最接近 alpha 门槛的是 `trend_continuation`、`trend_family`、`breakout_family`，但它们的 15% 命中率仍只有约 25.7%~25.9%，明显低于 55% 目标。
- 对应的 `mean_max_future_high_return_2_5d` 约为 10.28%~10.50%，也低于 15% 目标，因此本轮结论只能算“有方向”，不能算“有效因子”。

## beta 结论
- beta 侧整体并不差，本轮主要候选的 `beta_tradeable_rate` 都在 90% 左右，说明执行可交易性不是当前主矛盾。
- 也就是说，目前更大的问题不是“买不进去”，而是“即使能交易，5 日内冲到 +15% 的强度远远不够”。
- 因此下一轮不该优先放松交易门槛，而应该优先提高事件质量和收益爆发力。

## gamma 结论
- gamma 侧也基本通过：头部候选都覆盖多个 report dir，`unique_report_dir_count` 在 4 到 21 之间，不属于单一窗口偶然命中。
- 但 gamma 通过只代表样本分布还算稳定，不代表已经有足够强的收益优势。
- 因为 alpha 全部失败，所以当前仍然不能把任何 round1 候选升级为可推广因子。

## shortlist
- 本轮 `alpha_beta_gamma_shortlist` 为空。
- 这意味着当前结果只能作为“继续挖掘方向”，不能作为“验证通过的因子文档”接入 `docs/prompt/find_actor/` 或写入运行时策略。

## 下一轮动作
- 只围绕 `trend_continuation` / `trend_family` / `breakout_family` 做更细的分层，不扩大研究面。
- 优先拆分 `unclassified` 大样本，识别为什么大量样本缺少足够的结构特征，避免噪声稀释 round1 结果。
- 针对最接近目标的趋势/突破类候选，继续补更强的事件过滤、收益爆发标签和失败样本反证，再决定是否进入下一轮具体验证。
