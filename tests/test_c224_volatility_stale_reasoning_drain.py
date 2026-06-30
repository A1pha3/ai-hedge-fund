"""C224 volatility stale-reasoning drain (autodev c263, 2026-06-30).

Owner keystone C224 (commit 9059a4cf 'fix(NS-3/M15): volatility factor label
flip — bullish/bearish were reversed vs T+1') swapped the volatility signal
labels in src/agents/technicals.py:calculate_volatility_signals:

    high-vol regime (regime>VOL_HIGH_THRESHOLD, vol_z>+1) → signal = "bullish"
        (C224 flip: high-vol = recent winners → momentum continuation)
    low-vol regime  (regime<VOL_LOW_THRESHOLD,  vol_z<-1) → signal = "bearish"
        (C224 flip: low-vol = stagnation)

Pre-C224 the labels were reversed (low-vol → bullish on a mean-reversion bet;
high-vol → bearish). C222 counterfactual (n=1587) + C223 (n=8922) showed
sep = T+1(bullish) - T+1(bearish) was -0.34~-0.94 (bullish 票实际 T+1 更低).

C236 (commit 2af98d88) further tightened the thresholds (B_narrow):
    VOL_LOW_THRESHOLD  0.8 → 0.9
    VOL_HIGH_THRESHOLD 1.2 → 1.1

DEFECT (this campaign): the user-facing reasoning helper
src/agents/technicals_reasoning_helpers.py:_build_volatility_lines was NOT
updated when C224 flipped the signal labels. Result: when signal is "bullish"
(which now means HIGH-VOL regime per C224), the helper still emits pre-C224
text "处于低波动区间，波动率有望扩张，可能伴随价格上涨" — i.e. the OPPOSITE of what
the signal now means. Same class for bearish. This is a stale-reasoning-after-
evidence-shift defect (same family as c259/c261): user-facing text contradicts
the actual signal semantics.

Additionally, the regime-scale comment on line 72 still references the pre-C236
thresholds (0.8/1.2) instead of the current 0.9/1.1.

Fix: align reasoning text + regime-scale comment with post-C224/C236 semantics.
  - bullish (high-vol per C224)   → text describes 高波动区间 + 动量延续看涨
  - bearish (low-vol per C224)    → text describes 低波动区间 + 动量延续看跌/停滞
  - regime-scale comment          → 0.9/1.1 (C236 B_narrow)
"""
from __future__ import annotations

from src.agents.technicals_reasoning_helpers import _build_volatility_lines


# ---------------------------------------------------------------------------
# _build_volatility_lines — post-C224 semantics
# ---------------------------------------------------------------------------

class TestC224VolatilityReasoningDirection:
    """_build_volatility_lines must align with C224 flip:

    bullish = high-vol regime (regime>VOL_HIGH_THRESHOLD, vol_z>+1) → momentum continuation
    bearish = low-vol regime  (regime<VOL_LOW_THRESHOLD,  vol_z<-1) → stagnation
    """

    def test_bullish_describes_high_vol_not_low_vol(self) -> None:
        """C224: bullish signal now means HIGH-VOL regime (momentum continuation).
        Reasoning 解读 line must describe 高波动 state, NOT 低波动 (pre-C224 bullish meaning).
        """
        metrics = {
            "historical_volatility": 0.35,
            "volatility_regime": 1.25,  # > VOL_HIGH_THRESHOLD (1.1)
            "atr_ratio": 0.025,
        }
        lines = _build_volatility_lines(metrics, signal="bullish")
        interp = _extract_interp(lines)
        # Post-C224: bullish = high-vol → 解读 must mention 高波动
        assert "高波动" in interp, (
            f"C224 flip: bullish=high-vol regime, 解读 must describe 高波动区间; "
            f"got interp: {interp!r}"
        )
        # Must NOT describe 低波动 (the pre-C224 bullish meaning)
        assert "低波动" not in interp, (
            f"C224 flip: bullish=high-vol regime, 解读 must NOT describe 低波动 (pre-C224 stale); "
            f"got interp: {interp!r}"
        )

    def test_bearish_describes_low_vol_not_high_vol(self) -> None:
        """C224: bearish signal now means LOW-VOL regime (stagnation).
        Reasoning 解读 line must describe 低波动 state, NOT 高波动 (pre-C224 bearish meaning).
        """
        metrics = {
            "historical_volatility": 0.08,
            "volatility_regime": 0.75,  # < VOL_LOW_THRESHOLD (0.9)
            "atr_ratio": 0.010,
        }
        lines = _build_volatility_lines(metrics, signal="bearish")
        interp = _extract_interp(lines)
        # Post-C224: bearish = low-vol → 解读 must mention 低波动
        assert "低波动" in interp, (
            f"C224 flip: bearish=low-vol regime, 解读 must describe 低波动区间; "
            f"got interp: {interp!r}"
        )
        # Must NOT describe 高波动 (the pre-C224 bearish meaning)
        assert "高波动" not in interp, (
            f"C224 flip: bearish=low-vol regime, 解读 must NOT describe 高波动 (pre-C224 stale); "
            f"got interp: {interp!r}"
        )

    def test_bullish_mentions_momentum_continuation(self) -> None:
        """C224 rationale: high-vol regime = recent winners → momentum continuation.
        解读 should mention 动量延续 (or momentum-related wording) for bullish.
        """
        metrics = {
            "historical_volatility": 0.35,
            "volatility_regime": 1.25,
            "atr_ratio": 0.025,
        }
        lines = _build_volatility_lines(metrics, signal="bullish")
        interp = _extract_interp(lines)
        assert "动量延续" in interp or "动量" in interp, (
            f"C224: bullish=high-vol=momentum continuation, 解读 should mention 动量延续; "
            f"got interp: {interp!r}"
        )

    def test_bearish_mentions_stagnation(self) -> None:
        """C224 rationale: low-vol regime = stagnation (no recent momentum).
        解读 should mention 停滞 (or stagnation-related wording) for bearish.
        Mirrors test_bullish_mentions_momentum_continuation for symmetry.
        """
        metrics = {
            "historical_volatility": 0.08,
            "volatility_regime": 0.75,
            "atr_ratio": 0.010,
        }
        lines = _build_volatility_lines(metrics, signal="bearish")
        interp = _extract_interp(lines)
        assert "停滞" in interp, (
            f"C224: bearish=low-vol=stagnation, 解读 should mention 停滞; "
            f"got interp: {interp!r}"
        )

    def test_regime_scale_comment_uses_c236_thresholds(self) -> None:
        """C236 B_narrow: VOL_LOW_THRESHOLD 0.8→0.9, VOL_HIGH_THRESHOLD 1.2→1.1.
        The regime-scale comment in _build_volatility_lines must reference 0.9/1.1,
        NOT the stale 0.8/1.2.
        """
        metrics = {
            "historical_volatility": 0.20,
            "volatility_regime": 1.0,
            "atr_ratio": 0.015,
        }
        lines = _build_volatility_lines(metrics, signal="neutral")
        # Find the regime-scale line (波动率区间)
        regime_line = next((ln for ln in lines if "波动率区间" in ln), "")
        assert "0.9" in regime_line and "1.1" in regime_line, (
            f"C236 B_narrow: regime-scale comment must reference 0.9/1.1 (was 0.8/1.2); "
            f"got regime_line: {regime_line!r}"
        )
        # Must NOT reference stale 0.8/1.2 thresholds
        assert "0.8" not in regime_line and "1.2" not in regime_line, (
            f"C236 B_narrow: regime-scale comment must NOT reference stale 0.8/1.2; "
            f"got regime_line: {regime_line!r}"
        )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _extract_interp(lines: list[str]) -> str:
    """Extract the 解读 line from _build_volatility_lines output."""
    for ln in lines:
        if "解读" in ln:
            return ln
    return ""
