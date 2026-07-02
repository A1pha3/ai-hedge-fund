"""c308 (loop 42) — unit tests for the c307 universe price-IC diagnostic helpers.

The c307 conclusion (within-pool price-IC +0.176 is selection-bias-amplified,
universe +0.049; not an actionable within-pool signal) rests on
`classify_price_effect` + `amplification_ratio` in
`scripts/_diag_universe_price_ic.py`. Extracted from inline in c308; this test
pins the thresholds so a future change can't silently flip the verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._diag_universe_price_ic import (  # noqa: E402
    amplification_ratio,
    classify_price_effect,
)


def test_classify_bias_amplified_when_universe_weak():
    # c307 real-data: universe +0.049 (< 0.05) → bias_amplified
    assert classify_price_effect(0.049) == "bias_amplified"


def test_classify_real_factor_when_universe_strong_positive():
    assert classify_price_effect(0.15) == "real_factor"


def test_classify_mixed_in_middle_band():
    # 0.05 .. 0.10 → mixed
    assert classify_price_effect(0.07) == "mixed"


def test_classify_boundaries():
    assert classify_price_effect(0.05) == "mixed"  # exactly 0.05 → not < 0.05 → mixed
    assert classify_price_effect(0.10) == "mixed"  # exactly 0.10 → not > 0.10 → mixed
    assert classify_price_effect(0.0499) == "bias_amplified"
    assert classify_price_effect(0.101) == "real_factor"


def test_classify_negative_universe_is_bias_amplified():
    # classic small-cap premium: universe price-IC negative → pool positive = bias
    assert classify_price_effect(-0.08) == "bias_amplified"


def test_amplification_ratio_c307_real_data():
    # c307: pool +0.176 / universe +0.049 = 3.59×
    r = amplification_ratio(universe_ic=0.049, pool_ic=0.176)
    assert r is not None
    assert 3.5 < r < 3.7


def test_amplification_ratio_zero_universe_returns_none():
    # avoid divide-by-zero
    assert amplification_ratio(universe_ic=0.0, pool_ic=0.5) is None
