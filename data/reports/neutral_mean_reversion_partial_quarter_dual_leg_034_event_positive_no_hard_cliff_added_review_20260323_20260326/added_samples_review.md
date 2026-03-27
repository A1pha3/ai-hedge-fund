# neutral_mean_reversion_partial_quarter_dual_leg_034_event_positive_no_hard_cliff 新增释放样本审核台账

- baseline passes: 1
- variant passes: 4
- delta: 3
- added_sample_count: 3

## 审核重点

1. 这些新增样本是否真的是你想释放的边缘健康票。
2. 它们是否高度集中在 neutral_mean_reversion_active + trend/fundamental dual-leg。
3. 是否混入了明显只是被规则放水带出来的噪声票。

## 新增样本

- 20260323 / 300724 | industry=电力设备 | baseline=0.3522 -> variant=0.4335 | delta=0.0813
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg
  - strategy_summary: {"trend": {"direction": 1, "confidence": 43.1834, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 60.1961, "completeness": 1.0}, "event_sentiment": {"direction": 1, "confidence": 21.0553, "completeness": 1.0}}
  - profitability: {"direction": 1, "confidence": 66.66666666666667, "completeness": 1.0, "positive_count": 2, "available_count": 3}
- 20260324 / 600988 | industry=有色金属 | baseline=0.3786 -> variant=0.4659 | delta=0.0873
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg
  - strategy_summary: {"trend": {"direction": 1, "confidence": 40.4526, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 47.9137, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 52.9412, "completeness": 1.0}, "event_sentiment": {"direction": 1, "confidence": 49.1892, "completeness": 1.0}}
  - profitability: {"direction": 1, "confidence": 100.0, "completeness": 1.0, "positive_count": 3, "available_count": 3}
- 20260326 / 300724 | industry=电力设备 | baseline=0.3478 -> variant=0.4281 | delta=0.0803
  - tags: neutral_mean_reversion_active, trend_fundamental_dual_leg
  - strategy_summary: {"trend": {"direction": 1, "confidence": 43.632, "completeness": 1.0}, "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0}, "fundamental": {"direction": 1, "confidence": 60.1961, "completeness": 1.0}, "event_sentiment": {"direction": 1, "confidence": 18.1596, "completeness": 1.0}}
  - profitability: {"direction": 1, "confidence": 66.66666666666667, "completeness": 1.0, "positive_count": 2, "available_count": 3}
