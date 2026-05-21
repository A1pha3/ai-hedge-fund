from src.targets import get_short_trade_target_profile


def test_momentum_threshold_governed_profile_inherits_momentum_optimized_shape() -> None:
    baseline = get_short_trade_target_profile("momentum_optimized")
    candidate = get_short_trade_target_profile("momentum_tuned_governed_v1")

    assert candidate.name == "momentum_tuned_governed_v1"
    assert candidate.select_threshold == 0.38
    assert candidate.near_miss_threshold == 0.24
    assert candidate.selected_rank_cap_ratio == 0.50
    assert candidate.breakout_freshness_weight == baseline.breakout_freshness_weight
    assert candidate.trend_acceleration_weight == baseline.trend_acceleration_weight
    assert candidate.catalyst_freshness_weight == baseline.catalyst_freshness_weight
