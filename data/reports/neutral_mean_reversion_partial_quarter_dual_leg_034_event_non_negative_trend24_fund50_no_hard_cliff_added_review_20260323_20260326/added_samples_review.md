# neutral_mean_reversion_partial_quarter_dual_leg_034_event_non_negative_trend24_fund50_no_hard_cliff 新增释放样本审核台账

- baseline passes: 9
- variant passes: 14
- delta: 5
- added_sample_count: 5

## 审核重点

1. 这些新增样本是否真的是你想释放的边缘健康票。
2. 它们是否高度集中在 neutral_mean_reversion_active + trend/fundamental dual-leg。
3. 是否混入了明显只是被规则放水带出来的噪声票。

## 新增样本

- 20260324 / 600989 | industry=基础化工 | baseline=0.3588 -> variant=0.4092 | delta=0.0504
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing
  - strategy_summary: {"trend": {"direction": 1, "confidence": 41.7099, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 50.4, "completeness": 1.0}, "event_sentiment": {"direction": 0, "confidence": 26.6667, "completeness": 0.4133}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
- 20260325 / 600938 | industry=石油石化 | baseline=0.3570 -> variant=0.4137 | delta=0.0567
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing
  - strategy_summary: {"trend": {"direction": 1, "confidence": 25.0499, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 44.6942, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 54.0, "completeness": 1.0}, "event_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 0.0}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
- 20260325 / 600989 | industry=基础化工 | baseline=0.3582 -> variant=0.4085 | delta=0.0503
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing
  - strategy_summary: {"trend": {"direction": 1, "confidence": 41.5154, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 50.4, "completeness": 1.0}, "event_sentiment": {"direction": 0, "confidence": 26.6667, "completeness": 0.4133}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
- 20260326 / 600938 | industry=石油石化 | baseline=0.3559 -> variant=0.4124 | delta=0.0565
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing
  - strategy_summary: {"trend": {"direction": 1, "confidence": 24.7431, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 44.715, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 54.0, "completeness": 1.0}, "event_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 0.0}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
- 20260326 / 600989 | industry=基础化工 | baseline=0.3571 -> variant=0.4072 | delta=0.0501
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing
  - strategy_summary: {"trend": {"direction": 1, "confidence": 41.1711, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 50.4, "completeness": 1.0}, "event_sentiment": {"direction": 0, "confidence": 26.6667, "completeness": 0.4133}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
