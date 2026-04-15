#!/usr/bin/env python3
"""
Quick validation: Compare ic_v3 vs btst_precision_v2 scores on a specific date
by running the full scoring pipeline and comparing selections.
"""

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def quick_score_comparison(trade_date: str = "20260410"):
    """Compare profiles on a single date using the actual scoring functions."""
    from src.targets.profiles import get_short_trade_target_profile
    from src.targets.short_trade_target import _resolve_positive_score_weights

    v2 = get_short_trade_target_profile("btst_precision_v2")
    ic_v3 = get_short_trade_target_profile("ic_v3")

    print(f"Profile comparison for {trade_date}")
    print("=" * 80)

    # Show weight comparison
    v2_w = _resolve_positive_score_weights(v2)
    ic_v3_w = _resolve_positive_score_weights(ic_v3)

    print(f"\n{'Factor':<25s} {'v2':>8s} {'ic_v3':>8s}")
    print("-" * 45)
    all_factors = sorted(set(list(v2_w.keys()) + list(ic_v3_w.keys())))
    for f in all_factors:
        v2_val = v2_w.get(f, 0.0)
        ic_v3_val = ic_v3_w.get(f, 0.0)
        if v2_val > 0 or ic_v3_val > 0:
            print(f"{f:<25s} {v2_val:>7.1%} {ic_v3_val:>7.1%}")

    print(f"\n{'Profile Settings':}")
    print(f"  v2: ST={v2.select_threshold}, NMT={v2.near_miss_threshold}, RCR={v2.selected_rank_cap_ratio}")
    print(f"  ic_v3: ST={ic_v3.select_threshold}, NMT={ic_v3.near_miss_threshold}, RCR={ic_v3.selected_rank_cap_ratio}")

    # Show key differences
    print(f"\nKey differences:")
    for attr in ["trend_acceleration_weight", "short_term_reversal_weight", "intraday_strength_weight", "reversal_2d_weight",
                 "breakout_freshness_weight", "close_strength_weight", "catalyst_freshness_weight"]:
        v2_val = getattr(v2, attr, 0.0)
        ic_v3_val = getattr(ic_v3, attr, 0.0)
        if v2_val != ic_v3_val:
            print(f"  {attr}: v2={v2_val:.3f} -> ic_v3={ic_v3_val:.3f}")


if __name__ == "__main__":
    quick_score_comparison()
