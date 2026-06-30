"""NS-4 stale-reasoning drain (autodev c261, 2026-06-30).

Owner keystone NS-4 (commit 023acd74 'fix(mean-reversion): 完成NS-4因子方向翻转适配')
flipped 4 mean-reversion sub-factor signal directions in src/agents/technicals.py +
src/screening/strategy_scorer_mean_reversion.py:

    calculate_mean_reversion_signals:  oversold → bearish, overbought → bullish (FLIPPED)
    calculate_stat_arb_signals:         pos-skew → bearish, neg-skew → bullish (FLIPPED)
    _resolve_rsi_extreme_signal:        oversold → -1, overbought → +1 (FLIPPED)
    _resolve_hurst_regime_signal:       mean-reverting branch FLIPPED

Rationale (autodev C225 n=1193/sub-factor): all 4 MR sub-factors were REVERSED vs T+1
(sep<0, IC=-0.128) — short-term momentum dominates T+1, so oversold 票 keep falling.

DEFECT (this campaign): the user-facing reasoning helpers in
src/agents/technicals_reasoning_helpers.py were NOT updated when NS-4 flipped the
signal generators. Result: when the signal is "bullish" (which now means OVERBOUGHT
per NS-4), `_build_mean_reversion_lines` still emits the pre-NS-4 text "价格显著低于
均值(Z<-2)且接近布林带下轨，存在反弹机会" — i.e. the OPPOSITE of what the signal now
means. Same class for `_build_stat_arb_lines`. This is a stale-reasoning-after-
evidence-shift defect (same family as c259 stale-code-after-evidence-shift): user-
facing text contradicts the actual signal semantics.

Fix: align reasoning text with post-NS-4 signal semantics.
  - bullish (overbought per NS-4)  → text describes overbought state + 动量延续看涨
  - bearish (oversold per NS-4)     → text describes oversold state + 动量延续看跌
  - stat_arb bullish (neg-skew)     → text describes 左偏 + 动量延续看涨
  - stat_arb bearish (pos-skew)     → text describes 右偏 + 动量延续看跌
"""
from __future__ import annotations

from src.agents.technicals_reasoning_helpers import (
    _build_mean_reversion_lines,
    _build_stat_arb_lines,
)


# ---------------------------------------------------------------------------
# _build_mean_reversion_lines — post-NS-4 semantics
# ---------------------------------------------------------------------------

class TestNS4MeanReversionReasoningDirection:
    """_build_mean_reversion_lines must align with NS-4 flip:
    bullish = overbought (Z>+2, near upper band); bearish = oversold (Z<-2, near lower band).
    """

    def test_bullish_describes_overbought_not_oversold(self) -> None:
        """NS-4: bullish signal now means OVERBOUGHT (z>+2, price_vs_bb>0.8).
        Reasoning 解读 line must describe overbought state (高于均值/上轨), NOT oversold (低于均值/下轨).
        """
        metrics = {"z_score": 2.4, "price_vs_bb": 0.92, "rsi_14": 73.0, "rsi_28": 68.0}
        lines = _build_mean_reversion_lines(metrics, signal="bullish")
        interp = _extract_interp(lines)
        # Post-NS-4: bullish = overbought → 解读 must mention 高于均值/上轨 (overbought)
        assert "高于均值" in interp or "上轨" in interp, (
            f"NS-4 flip: bullish=overbought, 解读 must describe overbought state (高于均值/上轨); "
            f"got interp: {interp!r}"
        )
        # Must NOT describe oversold state (the pre-NS-4 bullish meaning)
        assert "低于均值" not in interp and "下轨" not in interp, (
            f"NS-4 flip: bullish=overbought, 解读 must NOT describe oversold (低于均值/下轨); "
            f"got interp: {interp!r}"
        )

    def test_bearish_describes_oversold_not_overbought(self) -> None:
        """NS-4: bearish signal now means OVERSOLD (z<-2, price_vs_bb<0.2).
        Reasoning 解读 line must describe oversold state (低于均值/下轨), NOT overbought.
        """
        metrics = {"z_score": -2.4, "price_vs_bb": 0.08, "rsi_14": 25.0, "rsi_28": 35.0}
        lines = _build_mean_reversion_lines(metrics, signal="bearish")
        interp = _extract_interp(lines)
        # Post-NS-4: bearish = oversold → 解读 must mention 低于均值/下轨
        assert "低于均值" in interp or "下轨" in interp, (
            f"NS-4 flip: bearish=oversold, 解读 must describe oversold state (低于均值/下轨); "
            f"got interp: {interp!r}"
        )
        # Must NOT describe overbought state (the pre-NS-4 bearish meaning)
        assert "高于均值" not in interp and "上轨" not in interp, (
            f"NS-4 flip: bearish=oversold, 解读 must NOT describe overbought (高于均值/上轨); "
            f"got interp: {interp!r}"
        )

    def test_neutral_unchanged(self) -> None:
        """Neutral branch is unaffected by NS-4 (no direction semantics)."""
        metrics = {"z_score": 0.1, "price_vs_bb": 0.5, "rsi_14": 50.0, "rsi_28": 50.0}
        lines = _build_mean_reversion_lines(metrics, signal="neutral")
        joined = "".join(lines)
        # Neutral should still mention 正常波动区间 (unchanged)
        assert "正常波动" in joined, f"neutral branch unchanged; got: {joined!r}"


# ---------------------------------------------------------------------------
# _build_stat_arb_lines — post-NS-4 semantics
# ---------------------------------------------------------------------------

class TestNS4StatArbReasoningDirection:
    """_build_stat_arb_lines must align with NS-4 flip:
    bullish = negative skew (左偏); bearish = positive skew (右偏).
    """

    def test_bullish_describes_left_skew_not_right(self) -> None:
        """NS-4: bullish signal now means NEGATIVE skew (左偏).
        Reasoning 解读 line must describe 左偏, NOT 右偏.
        """
        metrics = {"hurst_exponent": 0.35, "skewness": -1.5, "kurtosis": 2.0}
        lines = _build_stat_arb_lines(metrics, signal="bullish")
        interp = _extract_interp(lines)
        assert "左偏" in interp, (
            f"NS-4 flip: bullish=neg-skew (左偏), 解读 must describe 左偏; got interp: {interp!r}"
        )
        assert "右偏" not in interp, (
            f"NS-4 flip: bullish=neg-skew, 解读 must NOT describe 右偏; got interp: {interp!r}"
        )

    def test_bearish_describes_right_skew_not_left(self) -> None:
        """NS-4: bearish signal now means POSITIVE skew (右偏).
        Reasoning 解读 line must describe 右偏, NOT 左偏.
        """
        metrics = {"hurst_exponent": 0.35, "skewness": 1.5, "kurtosis": 2.0}
        lines = _build_stat_arb_lines(metrics, signal="bearish")
        interp = _extract_interp(lines)
        assert "右偏" in interp, (
            f"NS-4 flip: bearish=pos-skew (右偏), 解读 must describe 右偏; got interp: {interp!r}"
        )
        assert "左偏" not in interp, (
            f"NS-4 flip: bearish=pos-skew, 解读 must NOT describe 左偏; got interp: {interp!r}"
        )

    def test_neutral_unchanged(self) -> None:
        """Neutral branch is unaffected by NS-4."""
        metrics = {"hurst_exponent": 0.52, "skewness": 0.1, "kurtosis": 1.0}
        lines = _build_stat_arb_lines(metrics, signal="neutral")
        joined = "".join(lines)
        # Neutral should still mention 随机游走 or 统计特征 (unchanged)
        assert "随机游走" in joined or "统计特征" in joined, f"neutral branch unchanged; got: {joined!r}"


def _extract_interp(lines: list[str]) -> str:
    """Extract the '解读' (interpretation) line from reasoning output.

    The metrics legend lines (e.g. '偏度: -1.50 (>0右偏, <0左偏)') contain BOTH
    direction words as part of the legend, which would pollute direction-word
    assertions. The 解读 line carries the actual semantic claim.
    """
    for line in lines:
        if "解读" in line:
            return line
    return ""
