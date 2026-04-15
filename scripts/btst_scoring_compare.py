#!/usr/bin/env python3
"""
Quick comparison of v2 vs ic_v3 scoring on synthetic inputs.
Tests how the scoring formula differs between the two profiles.
"""
import sys
sys.path.insert(0, ".")

from src.targets.profiles import get_short_trade_target_profile
from src.targets.short_trade_target import _resolve_positive_score_weights


def compare_profiles():
    v2 = get_short_trade_target_profile("btst_precision_v2")
    ic_v3 = get_short_trade_target_profile("ic_v3")

    v2_w = _resolve_positive_score_weights(v2)
    ic_v3_w = _resolve_positive_score_weights(ic_v3)

    # Test scenarios with different factor combinations
    scenarios = {
        "Strong momentum+reversal (classic v2 win)": {
            "breakout_freshness": 0.15, "trend_acceleration": 0.7,
            "volume_expansion_quality": 0.3, "close_strength": 0.5,
            "sector_resonance": 0.4, "catalyst_freshness": 0.3,
            "layer_c_alignment": 0.3, "momentum_strength": 0.8,
            "short_term_reversal": 0.9,
            "intraday_strength": 0.7, "reversal_2d": 0.8,
        },
        "Weak reversal, strong trend": {
            "breakout_freshness": 0.3, "trend_acceleration": 0.9,
            "volume_expansion_quality": 0.5, "close_strength": 0.6,
            "sector_resonance": 0.5, "catalyst_freshness": 0.4,
            "layer_c_alignment": 0.4, "momentum_strength": 0.6,
            "short_term_reversal": 0.2,
            "intraday_strength": 0.8, "reversal_2d": 0.3,
        },
        "Balanced average": {
            "breakout_freshness": 0.4, "trend_acceleration": 0.5,
            "volume_expansion_quality": 0.4, "close_strength": 0.5,
            "sector_resonance": 0.4, "catalyst_freshness": 0.4,
            "layer_c_alignment": 0.4, "momentum_strength": 0.4,
            "short_term_reversal": 0.5,
            "intraday_strength": 0.5, "reversal_2d": 0.5,
        },
        "Pure reversal play": {
            "breakout_freshness": 0.1, "trend_acceleration": 0.2,
            "volume_expansion_quality": 0.2, "close_strength": 0.3,
            "sector_resonance": 0.2, "catalyst_freshness": 0.1,
            "layer_c_alignment": 0.2, "momentum_strength": 0.1,
            "short_term_reversal": 0.95,
            "intraday_strength": 0.2, "reversal_2d": 0.9,
        },
        "Intraday strength star": {
            "breakout_freshness": 0.3, "trend_acceleration": 0.6,
            "volume_expansion_quality": 0.5, "close_strength": 0.7,
            "sector_resonance": 0.5, "catalyst_freshness": 0.5,
            "layer_c_alignment": 0.5, "momentum_strength": 0.7,
            "short_term_reversal": 0.3,
            "intraday_strength": 0.95, "reversal_2d": 0.4,
        },
    }

    print(f"{'Scenario':<35s} {'v2':>8s} {'ic_v3':>8s} {'Diff':>8s} {'Winner':>8s}")
    print("-" * 75)

    v2_wins = 0
    ic_v3_wins = 0

    for name, factors in scenarios.items():
        v2_score = sum(v2_w.get(k, 0) * v for k, v in factors.items())
        ic_v3_score = sum(ic_v3_w.get(k, 0) * v for k, v in factors.items())
        diff = ic_v3_score - v2_score
        winner = "ic_v3" if diff > 0.005 else "v2" if diff < -0.005 else "tie"
        if winner == "ic_v3":
            ic_v3_wins += 1
        elif winner == "v2":
            v2_wins += 1

        print(f"{name:<35s} {v2_score:>7.3f} {ic_v3_score:>7.3f} {diff:>+7.3f} {winner:>8s}")

    print(f"\nv2 wins: {v2_wins}, ic_v3 wins: {ic_v3_wins}")

    # Show what ic_v3 values more
    print(f"\n--- What ic_v3 values more than v2 ---")
    for factor in sorted(set(list(v2_w.keys()) + list(ic_v3_w.keys()))):
        diff = ic_v3_w.get(factor, 0) - v2_w.get(factor, 0)
        if abs(diff) > 0.01:
            direction = "MORE" if diff > 0 else "LESS"
            print(f"  {factor:<30s}: {v2_w.get(factor,0):.3f} -> {ic_v3_w.get(factor,0):.3f} ({direction})")


if __name__ == "__main__":
    compare_profiles()
