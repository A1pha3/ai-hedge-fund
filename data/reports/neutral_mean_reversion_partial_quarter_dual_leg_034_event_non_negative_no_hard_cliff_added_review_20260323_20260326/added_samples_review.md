# neutral_mean_reversion_partial_quarter_dual_leg_034_event_non_negative_no_hard_cliff 新增释放样本审核台账

- baseline passes: 9
- variant passes: 18
- delta: 9
- added_sample_count: 9

## 审核重点

1. 这些新增样本是否真的是你想释放的边缘健康票。
2. 它们是否高度集中在 neutral_mean_reversion_active + trend/fundamental dual-leg。
3. 是否混入了明显只是被规则放水带出来的噪声票。

## 新增样本

- 20260324 / 300274 | industry=电力设备 | baseline=0.3575 -> variant=0.4077 | delta=0.0502
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing
  - strategy_summary: {"trend": {"direction": 1, "confidence": 48.2673, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 45.3333, "completeness": 1.0}, "event_sentiment": {"direction": 0, "confidence": 26.6667, "completeness": 0.4133}}
  - profitability: {"direction": 1, "confidence": 66.66666666666667, "completeness": 1.0, "positive_count": 2, "available_count": 3}
- 20260324 / 300308 | industry=通信 | baseline=0.3701 -> variant=0.4288 | delta=0.0587
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing
  - strategy_summary: {"trend": {"direction": 1, "confidence": 22.1512, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 43.6632, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 58.7438, "completeness": 1.0}, "event_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 0.0}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
- 20260324 / 300394 | industry=通信 | baseline=0.3450 -> variant=0.3934 | delta=0.0484
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing
  - strategy_summary: {"trend": {"direction": 1, "confidence": 39.3017, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 49.0435, "completeness": 1.0}, "event_sentiment": {"direction": 0, "confidence": 26.6667, "completeness": 1.0}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
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
- 20260326 / 002463 | industry=电子 | baseline=0.3613 -> variant=0.4120 | delta=0.0507
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg
  - strategy_summary: {"trend": {"direction": 1, "confidence": 37.083, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 48.4356, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 47.2, "completeness": 1.0}, "event_sentiment": {"direction": 1, "confidence": 31.3513, "completeness": 1.0}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
- 20260326 / 600938 | industry=石油石化 | baseline=0.3559 -> variant=0.4124 | delta=0.0565
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing
  - strategy_summary: {"trend": {"direction": 1, "confidence": 24.7431, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 44.715, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 54.0, "completeness": 1.0}, "event_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 0.0}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
- 20260326 / 600989 | industry=基础化工 | baseline=0.3571 -> variant=0.4072 | delta=0.0501
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing
  - strategy_summary: {"trend": {"direction": 1, "confidence": 41.1711, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 50.4, "completeness": 1.0}, "event_sentiment": {"direction": 0, "confidence": 26.6667, "completeness": 0.4133}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
