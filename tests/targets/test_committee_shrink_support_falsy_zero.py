"""TDD red test: falsy-zero `or 50.0` bug in _shrink_support_score_for_evidence.

R68/R69/R96/R107/R108 falsy-zero `or` family residue on the short-trade target
committee support-score shrink helper. The sibling functions in the same module
(_apply_prior_payoff_asymmetry_to_support_score lines 110/161/172) correctly use
`or 0.0` (treat 0 as the natural minimum score), but
_shrink_support_score_for_evidence (line 104) uses `or 50.0`, which silently
promotes an explicit base_support_score_100=0.0 to the neutral 50.0 center
before the regression-toward-50 computation.

Result: an explicit low/bearish support score of 0.0 is silently erased —
`50.0 + (50.0 - 50.0) * multiplier == 50.0` — instead of the intended shrink of
the 0.0 toward center (`50.0 + (0.0 - 50.0) * multiplier`, which is below 50
for any multiplier in [0.7, 1.0], preserving the bearish tilt).

R85/R78 precedent: this is a latent defensive guard fix (current sole caller
passes _support_score_100 which floors at 20.0, so 0.0 is currently unreachable),
but the function is a public-enough helper whose boundary contract must not
silently corrupt an explicit 0.0 input.
"""

from __future__ import annotations

import math

from src.targets.short_trade_target_committee_helpers import (
    _shrink_support_score_for_evidence,
)


def test_explicit_zero_support_score_is_shrunk_not_promoted_to_neutral_50() -> None:
    """Explicit base_support_score_100=0.0 must shrink toward 50 (yield <50), not become exactly 50.

    With multiplier in [0.70, 1.0], 50 + (0 - 50) * mult = 50 - 50*mult, which is
    in [0, 15] — strictly below 50 (preserves the bearish tilt). The buggy
    `or 50.0` makes it exactly 50 (erases the signal).
    """
    # evidence_weight=0 -> multiplier=0.70 (max shrink)
    result = _shrink_support_score_for_evidence(0.0, 0.0)
    assert result < 50.0, f"explicit base_support_score_100=0.0 must shrink below 50 (preserve bearish tilt), " f"got {result!r} — falsy-zero `or 50.0` silently promoted 0.0 to neutral 50.0"
    # The mathematically correct value: 50 + (0-50)*0.70 = 50 - 35 = 15.0
    assert math.isclose(result, 15.0), f"expected 15.0 (50 + (0-50)*0.70), got {result!r}"


def test_explicit_zero_with_full_evidence_still_shrinks_below_50() -> None:
    """With full evidence (multiplier=1.0), explicit 0.0 still yields <50, never 50."""
    result = _shrink_support_score_for_evidence(0.0, 1.0)
    # 50 + (0-50)*1.0 = 0.0
    assert math.isclose(result, 0.0), f"expected 0.0 (50 + (0-50)*1.0), got {result!r}"


def test_normal_nonzero_score_still_regresses_toward_50() -> None:
    """Non-zero scores still regress toward 50 (behavior preserved)."""
    # score=80, evidence_weight=0 -> 50 + (80-50)*0.70 = 50 + 21 = 71.0
    result = _shrink_support_score_for_evidence(80.0, 0.0)
    assert math.isclose(result, 71.0)


def test_explicit_low_score_20_still_shrinks_below_50() -> None:
    """A floor-level score of 20 (_support_score_100 minimum) shrinks below 50."""
    # 50 + (20-50)*0.70 = 50 - 21 = 29.0
    result = _shrink_support_score_for_evidence(20.0, 0.0)
    assert math.isclose(result, 29.0)
