# neutral_mean_reversion_partial_quarter_dual_leg_034_event_non_negative_no_hard_cliff 新增样本 Layer C 承接对照

- trade_dates: 20260323, 20260324, 20260325, 20260326
- model: MiniMax / MiniMax-M2.7
- added_sample_count: 9
- would_enter_watchlist: 5
- rejected_after_layer_c: 4
- avoid_conflicts: 4
- watchlist_threshold: 0.2000
- layer_c_blend: B=0.5500, C=0.4500
- layer_c_avoid_score_c_threshold: -0.3000

## 核心判断

1. 先看新增样本里有多少能被 Layer C 真正承接进 watchlist。
2. 再看被否决的样本是因为强 bearish 冲突，还是只是差一点点。
3. 最后看哪些标签组合更容易被承接。

## 汇总

- accepted_tag_counts: {"neutral_mean_reversion_active": 5, "trend_fundamental_dual_leg": 5, "event_sentiment_missing": 5}
- rejected_tag_counts: {"neutral_mean_reversion_active": 4, "trend_fundamental_dual_leg": 4, "event_sentiment_missing": 3}
- bc_conflict_counts: {"b_positive_c_strong_bearish": 4}
- daily_status_counts: {"20260324": {"accepted": 1, "rejected": 3}, "20260325": {"accepted": 2, "rejected": 0}, "20260326": {"accepted": 2, "rejected": 1}}

## 样本明细

- 20260324 / 300274 | industry=电力设备 | tags=neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing | score_b=0.4077 | score_c=-0.0656 | required_c=-0.0539 | gap=-0.0117 | final=0.1947 | decision=avoid | watchlist=no
  - bc_conflict: b_positive_c_strong_bearish
  - top_positive_agents: [{"agent_id": "fundamentals_analyst_agent", "contribution": 0.0397, "direction": 1, "confidence": 75.0, "completeness": 1.0}, {"agent_id": "technical_analyst_agent", "contribution": 0.0265, "direction": 1, "confidence": 50.0, "completeness": 1.0}, {"agent_id": "growth_analyst_agent", "contribution": 0.0159, "direction": 1, "confidence": 30.0, "completeness": 1.0}]
  - top_negative_agents: [{"agent_id": "valuation_analyst_agent", "contribution": -0.053, "direction": -1, "confidence": 100.0, "completeness": 1.0}, {"agent_id": "sentiment_analyst_agent", "contribution": -0.0444, "direction": -1, "confidence": 83.9, "completeness": 1.0}, {"agent_id": "michael_burry_agent", "contribution": -0.0085, "direction": -1, "confidence": 92.0, "completeness": 1.0}]
- 20260324 / 300308 | industry=通信 | tags=neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing | score_b=0.4288 | score_c=-0.1007 | required_c=-0.0796 | gap=-0.0211 | final=0.1905 | decision=avoid | watchlist=no
  - bc_conflict: b_positive_c_strong_bearish
  - top_positive_agents: [{"agent_id": "fundamentals_analyst_agent", "contribution": 0.0397, "direction": 1, "confidence": 75.0, "completeness": 1.0}]
  - top_negative_agents: [{"agent_id": "valuation_analyst_agent", "contribution": -0.053, "direction": -1, "confidence": 100.0, "completeness": 1.0}, {"agent_id": "sentiment_analyst_agent", "contribution": -0.0388, "direction": -1, "confidence": 73.21, "completeness": 1.0}, {"agent_id": "bill_ackman_agent", "contribution": -0.0085, "direction": -1, "confidence": 92.5, "completeness": 1.0}]
- 20260324 / 300394 | industry=通信 | tags=neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing | score_b=0.3934 | score_c=-0.1030 | required_c=-0.0364 | gap=-0.0666 | final=0.1700 | decision=avoid | watchlist=no
  - bc_conflict: b_positive_c_strong_bearish
  - top_positive_agents: [{"agent_id": "fundamentals_analyst_agent", "contribution": 0.0419, "direction": 1, "confidence": 75.0, "completeness": 1.0}]
  - top_negative_agents: [{"agent_id": "valuation_analyst_agent", "contribution": -0.0559, "direction": -1, "confidence": 100.0, "completeness": 1.0}, {"agent_id": "sentiment_analyst_agent", "contribution": -0.0483, "direction": -1, "confidence": 86.36, "completeness": 1.0}, {"agent_id": "bill_ackman_agent", "contribution": -0.008, "direction": -1, "confidence": 82.5, "completeness": 1.0}]
- 20260324 / 600989 | industry=基础化工 | tags=neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing | score_b=0.4092 | score_c=0.0651 | required_c=-0.0557 | gap=0.1208 | final=0.2544 | decision=watch | watchlist=yes
  - top_positive_agents: [{"agent_id": "stanley_druckenmiller_agent", "contribution": 0.0478, "direction": 1, "confidence": 78.0, "completeness": 1.0}, {"agent_id": "cathie_wood_agent", "contribution": 0.0441, "direction": 1, "confidence": 72.0, "completeness": 1.0}, {"agent_id": "sentiment_analyst_agent", "contribution": 0.0334, "direction": 1, "confidence": 63.16, "completeness": 1.0}]
  - top_negative_agents: [{"agent_id": "valuation_analyst_agent", "contribution": -0.053, "direction": -1, "confidence": 100.0, "completeness": 1.0}, {"agent_id": "michael_burry_agent", "contribution": -0.0078, "direction": -1, "confidence": 85.0, "completeness": 1.0}, {"agent_id": "warren_buffett_agent", "contribution": -0.0078, "direction": -1, "confidence": 85.0, "completeness": 1.0}]
- 20260325 / 600938 | industry=石油石化 | tags=neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing | score_b=0.4137 | score_c=0.0881 | required_c=-0.0612 | gap=0.1493 | final=0.2672 | decision=watch | watchlist=yes
  - top_positive_agents: [{"agent_id": "sentiment_analyst_agent", "contribution": 0.053, "direction": 1, "confidence": 100.0, "completeness": 1.0}, {"agent_id": "rakesh_jhunjhunwala_agent", "contribution": 0.049, "direction": 1, "confidence": 80.0, "completeness": 1.0}, {"agent_id": "stanley_druckenmiller_agent", "contribution": 0.049, "direction": 1, "confidence": 80.0, "completeness": 1.0}]
  - top_negative_agents: [{"agent_id": "valuation_analyst_agent", "contribution": -0.053, "direction": -1, "confidence": 100.0, "completeness": 1.0}, {"agent_id": "growth_analyst_agent", "contribution": -0.0191, "direction": -1, "confidence": 36.0, "completeness": 1.0}, {"agent_id": "mohnish_pabrai_agent", "contribution": -0.0078, "direction": -1, "confidence": 85.0, "completeness": 1.0}]
- 20260325 / 600989 | industry=基础化工 | tags=neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing | score_b=0.4085 | score_c=0.0743 | required_c=-0.0548 | gap=0.1291 | final=0.2581 | decision=watch | watchlist=yes
  - top_positive_agents: [{"agent_id": "peter_lynch_agent", "contribution": 0.0478, "direction": 1, "confidence": 78.0, "completeness": 1.0}, {"agent_id": "stanley_druckenmiller_agent", "contribution": 0.0441, "direction": 1, "confidence": 72.0, "completeness": 1.0}, {"agent_id": "sentiment_analyst_agent", "contribution": 0.0334, "direction": 1, "confidence": 63.16, "completeness": 1.0}]
  - top_negative_agents: [{"agent_id": "valuation_analyst_agent", "contribution": -0.053, "direction": -1, "confidence": 100.0, "completeness": 1.0}, {"agent_id": "mohnish_pabrai_agent", "contribution": -0.008, "direction": -1, "confidence": 87.5, "completeness": 1.0}, {"agent_id": "michael_burry_agent", "contribution": -0.0078, "direction": -1, "confidence": 85.0, "completeness": 1.0}]
- 20260326 / 002463 | industry=电子 | tags=neutral_mean_reversion_active, trend_fundamental_dual_leg | score_b=0.4120 | score_c=-0.1493 | required_c=-0.0591 | gap=-0.0901 | final=0.1594 | decision=avoid | watchlist=no
  - bc_conflict: b_positive_c_strong_bearish
  - top_negative_agents: [{"agent_id": "valuation_analyst_agent", "contribution": -0.053, "direction": -1, "confidence": 100.0, "completeness": 1.0}, {"agent_id": "sentiment_analyst_agent", "contribution": -0.0479, "direction": -1, "confidence": 90.55, "completeness": 1.0}, {"agent_id": "michael_burry_agent", "contribution": -0.0084, "direction": -1, "confidence": 91.67, "completeness": 1.0}]
- 20260326 / 600938 | industry=石油石化 | tags=neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing | score_b=0.4124 | score_c=0.1198 | required_c=-0.0596 | gap=0.1794 | final=0.2807 | decision=watch | watchlist=yes
  - top_positive_agents: [{"agent_id": "stanley_druckenmiller_agent", "contribution": 0.049, "direction": 1, "confidence": 80.0, "completeness": 1.0}, {"agent_id": "sentiment_analyst_agent", "contribution": 0.0447, "direction": 1, "confidence": 84.44, "completeness": 1.0}, {"agent_id": "cathie_wood_agent", "contribution": 0.0417, "direction": 1, "confidence": 68.0, "completeness": 1.0}]
  - top_negative_agents: [{"agent_id": "valuation_analyst_agent", "contribution": -0.053, "direction": -1, "confidence": 100.0, "completeness": 1.0}, {"agent_id": "growth_analyst_agent", "contribution": -0.0191, "direction": -1, "confidence": 36.0, "completeness": 1.0}, {"agent_id": "mohnish_pabrai_agent", "contribution": -0.0072, "direction": -1, "confidence": 78.5, "completeness": 1.0}]
- 20260326 / 600989 | industry=基础化工 | tags=neutral_mean_reversion_active, trend_fundamental_dual_leg, event_sentiment_missing | score_b=0.4072 | score_c=0.0679 | required_c=-0.0532 | gap=0.1212 | final=0.2545 | decision=watch | watchlist=yes
  - top_positive_agents: [{"agent_id": "stanley_druckenmiller_agent", "contribution": 0.0478, "direction": 1, "confidence": 78.0, "completeness": 1.0}, {"agent_id": "peter_lynch_agent", "contribution": 0.0472, "direction": 1, "confidence": 77.0, "completeness": 1.0}, {"agent_id": "sentiment_analyst_agent", "contribution": 0.0334, "direction": 1, "confidence": 63.16, "completeness": 1.0}]
  - top_negative_agents: [{"agent_id": "valuation_analyst_agent", "contribution": -0.053, "direction": -1, "confidence": 100.0, "completeness": 1.0}, {"agent_id": "michael_burry_agent", "contribution": -0.0083, "direction": -1, "confidence": 90.0, "completeness": 1.0}, {"agent_id": "bill_ackman_agent", "contribution": -0.0078, "direction": -1, "confidence": 85.0, "completeness": 1.0}]
