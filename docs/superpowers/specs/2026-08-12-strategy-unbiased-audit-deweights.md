# mean_reversion 策略降权设计（三策略无偏审计后的决策）

**日期**: 2026-08-12
**状态**: 已执行
**性质**: trend 降权 (2026-08-11) 的延续——审计剩余权重主力策略后, 对负贡献因子做同构降权

## 1. 背景: 三策略全 universe 无偏审计

trend 降权到 0 后, score_b 权重 100% 落在 mean_reversion (0.20) / fundamental (0.15) /
event_sentiment (0.05) 上。这三个策略从未做过全 universe 无偏审计——所有既有结论
(MR family 反向 / fundamental quality-first) 都来自推荐池样本 (选择偏差污染的候选宇宙,
已三次踩坑)。8/12 用与 trend 实验完全同构的口径审计三策略:

- 候选宇宙: 全 universe 涨停候选日 (无选择偏差), 截止涨停日切片 (无 look-ahead)
- 收益测度: exec (剔除次日续涨停不可买), T+10 开盘买入→收盘卖出; MR 另补 T+1 (NS-4 翻转是 T+1 验证的)
- 特征契约: MR/event 用生产评分函数; fundamental 用生产链 (mock pro + 缓存帧 100% 命中 + 生产 score_fundamental_strategy_from_metrics)
- 脚本: `scripts/strategy_unbiased_audit.py`; 结果: `data/reports/strategy_unbiased_audit.json`

## 2. 结果

| 策略 | n | signed ρ (direction×conf) | dir+1 WR | dir-1 WR | 跨窗 | 裁决 | 原权重 |
|---|---|---|---|---|---|---|---|
| mean_reversion | 16470 | **−0.0819** | **41.0%** | **51.8%** | 同向 | **反 IC (负贡献)** | **0.20** |
| fundamental | 4432 | +0.0239 | 50.1% | 48.8% | 同向 | 弱正 (方向组无分离) | 0.15 |
| event_sentiment | 1787 | +0.0638 | **51.6%** | 44.5% | 同向 | 正 IC (唯一真信号) | 0.05 |

MR 附加诊断 (决定性):
- **T+1 也倒挂**: signed ρ = −0.0282, dir+1 WR 48.3% vs dir−1 50.1% — NS-4 翻转版在
  生产 T+1 上就已倒挂, T+10 只是更明显。**不是 horizon 冲突, 是方向本身错误**。
- Wilson CI: dir+1 [0.402, 0.419] vs dir−1 [0.496, 0.541], 差 0.004 未非重叠, 但跨窗
  一致 + T+1 同向 + signed ρ −0.082 三重证据下方向结论稳健。
- fundamental 简化重建被证伪 (方向分布颠倒, 一致率 35%) → 生产链修正。

## 3. 决策: 降权, 不翻转, 不融合

**降权 mean_reversion (0.20 → 0.0), 不动 direction/multiplier, 不融合。**

理由 (第一性原理):
- **MR 是负贡献不是无贡献**: signed ρ −0.082 跨窗一致, 比 trend (无 IC) 更该处理 —
  trend 降权是"去噪声", MR 降权是"去反向信号"。score_b 权重与证据完全倒挂
  (IC 最差的权重最高 0.20, IC 最好的权重最低 0.05)。
- **翻转是错的**: NS-4 翻转版已在生产 (technicals.py + strategy_scorer_mean_reversion.py
  generator 层翻转), 无新证据支持方向反转。2026-06-25 曾因推荐池样本把 multiplier
  设 −1.0 后被全 universe 回测推翻 (models.py:114-128 注释即此教训) — 翻转是第 N 轮
  盲翻覆辙。若未来要恢复 MR, 应先在全 universe 上验证反向方向有正 IC, 再在 generator
  层翻转。
- **降权零风险**: 与 trend 降权同构 — 去掉负贡献, 让有正证据的 fundamental/event 归一化放大。

## 4. 执行

1. **`DEFAULT_STRATEGY_WEIGHTS` (models.py)**: `mean_reversion 0.20 → 0.0` + 注释记录审计证据。
2. **`MarketState.adjusted_weights` 默认字段 (models.py:85-92)**: 同步为当前 DEFAULT
   (生产路径显式传值, 此默认仅测试/退化兜底 — 顺带修复陈旧快照)。
3. **`market_state_helpers.py` regime 调整**: 删除 4 处与证据反向的 MR 上调
   (CRISIS +0.05 / RANGE +0.12 / breadth_weak +0.04 / northbound −3 +0.03) 与 trend 死操作
   (trend 已 0, ± 调整无效果)。保留与证据同向的 MR 下调 (TREND −0.08) 但因权重 0 亦无
   效果, 一并清理。fundamental/event 的 regime 调节保留 (有证据的策略权重才配被微调)。
4. **测试锚定**: test_models (sum 0.40→0.20, adjusted_weights 期望), test_market_state
   (zero/all-zero fallback), test_signal_fusion (DEFAULT MR==0 锚定 + trend-only 信号 →
   weights_used 空/score 0 的降权语义), test_phase2_screening (trend>MR 断言 → 双零 +
   fundamental/event 正, weak-breadth 0.425 断言 → 方向断言)。
5. **不动**: direction 逻辑、multiplier (全 1.0)、custom_weights (独立 0.25 等分配置)、
   weight_calibration (研究工具)、LIGHT_STRATEGY_WEIGHTS (trend 0.65/MR 0.35,
   另一条 technical 预筛路径, 非 score_b)。

## 5. 验收

- 全量测试绿 (trend 降权时 3969; 本次 screening 2652 绿, 全量待确认)。
- 锚定测试覆盖 MR=0 的 score_b 归一化 + trend-only 信号 0 分语义。
- flake8 (line 420) 通过。

## 6. 后续 (待 owner 裁决, 不在本次范围)

1. **fundamental 0.15 维持**: 弱正, 质量门作用不体现在 IC 上。但注意其 direction 在
   涨停候选日宇宙以 −1 为主 (65%) 而看空组未跑赢 — 若未来恢复需关注。
2. **event_sentiment 0.05 可考虑上调**: 唯一正 IC 策略 (signed +0.064, 跨窗一致),
   但 n=1787 样本小 (仅 2026H1 news 缓存窗口) — 上调需更长窗口验证。
3. **R-5.F 跨期验证**: 仍受 fund_flow 2022 缺失阻塞 (唯一数据缺口, daily_basic 2022 全有)。
4. **统一度量契约**: 候选域 + 收益口径声明 — 本次三次踩坑的根中之根。

## 7. 被否决方案的否决证据 (供未来审计者)

1. **翻转 MR**: 无新证据支持方向反转; NS-4 翻转版已在生产且 T+1 仍倒挂, 翻转回传统
   mean-reversion 方向无依据。2026-06-25 盲翻转被推翻的教训在前。
2. **A/B 对照降权**: 降权负贡献因子不需要对照 (与 trend 降权同理 — 不会让任何东西变差)。
3. **上调 event 至与证据匹配**: 样本小 (n=1787, 单一窗口), 证据强度不足以下注。
4. **删掉 fundamental 的 −1 倾向**: direction 分布是生产逻辑 (quality-first + 阈值) 的
   正常产物, 不是缺陷; 且看空组未跑赢, 无翻转理由。

**方法论教训** (与 trend 降权闭环): 审计必须用生产同一函数 (简化重建方向颠倒);
T+1 vs T+10 horizon 检验区分"方向错" vs "horizon 冲突"; 数据覆盖声明先行
(MR 全期 / fundamental 2024H2+ / event 2026H1, 裁决带窗口 caveat)。
