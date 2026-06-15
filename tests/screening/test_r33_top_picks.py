"""Tests for R33 (portfolio expected return summary) in top_picks.

R33 adds a one-line ``组合 T+30 预期: +X.XX% (加权) | 平均胜率: XX% | BUY 数: N``
summary to the front door, reusing per-pick T+30 edge and win-rate data.
"""
from __future__ import annotations

import pytest

from src.screening import top_picks
from src.screening.top_picks import (
    _PORTFOLIO_SUMMARY_MIN_BUYS,
    _render_portfolio_expected_return,
)
from src.utils.display import Fore, Style


def _pick(
    *,
    ticker: str = "000001",
    t30: float = 3.0,
    t30_wr: float = 0.58,
    sample_count: int = 30,
    composite_score: float = 0.6,
) -> dict:
    """Build a pick dict with the fields R33 reads."""
    return {
        "ticker": ticker,
        "name": ticker,
        "composite_score": composite_score,
        "expected_returns": {"t30": t30},
        "win_rates": {"t30": t30_wr},
        "bucket_sample_count": sample_count,
    }


@pytest.fixture
def all_buy(monkeypatch):
    """Force every pick to be classified BUY regardless of edge/winrate."""
    def _always_buy(recommendation, *, market_regime):
        return {"action": "BUY", "market_regime": market_regime, "invalidation_reason": ""}
    monkeypatch.setattr(top_picks, "build_front_door_verdict", _always_buy)


@pytest.fixture
def all_avoid(monkeypatch):
    """Force every pick to be classified AVOID (no BUY)."""
    def _always_avoid(recommendation, *, market_regime):
        return {"action": "AVOID", "market_regime": market_regime, "invalidation_reason": ""}
    monkeypatch.setattr(top_picks, "build_front_door_verdict", _always_avoid)


class TestRenderPortfolioExpectedReturn:
    def test_empty_picks(self) -> None:
        assert _render_portfolio_expected_return([], "normal") == ""

    def test_single_buy_returns_empty(self, all_buy) -> None:
        """< 2 BUY picks → no portfolio summary."""
        result = _render_portfolio_expected_return([_pick()], "normal")
        assert result == ""

    def test_no_buys_returns_empty(self, all_avoid) -> None:
        picks = [_pick(), _pick(ticker="000002")]
        assert _render_portfolio_expected_return(picks, "normal") == ""

    def test_two_buys_shows_summary(self, all_buy) -> None:
        picks = [_pick(ticker="000001", t30=3.0), _pick(ticker="000002", t30=5.0)]
        result = _render_portfolio_expected_return(picks, "normal")
        assert "组合 T+30 预期" in result
        assert "BUY 数" in result
        assert "2" in result
        assert "+4.00%" in result  # mean(3.0, 5.0)

    def test_negative_edge_uses_red(self, all_buy) -> None:
        picks = [_pick(ticker="000001", t30=-2.0), _pick(ticker="000002", t30=-1.0)]
        result = _render_portfolio_expected_return(picks, "normal")
        assert result != ""
        assert Fore.RED in result

    def test_positive_edge_uses_green(self, all_buy) -> None:
        picks = [_pick(t30=3.0), _pick(t30=4.0)]
        result = _render_portfolio_expected_return(picks, "normal")
        assert Fore.GREEN in result

    def test_high_winrate_uses_green(self, all_buy) -> None:
        picks = [_pick(t30_wr=0.60), _pick(t30_wr=0.62)]
        result = _render_portfolio_expected_return(picks, "normal")
        assert Fore.GREEN in result

    def test_low_winrate_uses_red(self, all_buy) -> None:
        """Win rate < 45% → red."""
        picks = [_pick(ticker="000001", t30_wr=0.40), _pick(ticker="000002", t30_wr=0.42)]
        result = _render_portfolio_expected_return(picks, "normal")
        assert result != ""
        assert Fore.RED in result

    def test_buy_picks_are_equal_weighted(self, all_buy) -> None:
        """BUY picks are equal-weighted in the portfolio average.

        The portfolio summary aggregates the T+30 edge over BUY picks only.
        A ``sample_count < 20`` halving scheme was removed because it was
        unreachable: :func:`build_front_door_verdict` already requires
        ``sample_count >= 20`` for any BUY classification (see
        ``test_low_sample_pick_can_never_be_buy``), so a low-sample pick can
        never enter the BUY aggregate and the halving safeguard could never
        trigger. Equal weighting now matches the spec's documented
        "等权或 composite_score 归一化" alternative.
        """
        high_sample = _pick(ticker="000001", t30=10.0, sample_count=100)
        low_sample = _pick(ticker="000002", t30=0.0, sample_count=5)
        result = _render_portfolio_expected_return([high_sample, low_sample], "normal")
        # Equal weight: mean(10.0, 0.0) = 5.00%
        assert "+5.00%" in result

    def test_all_buys_missing_t30_returns_empty(self, all_buy) -> None:
        """When no picks have valid T+30 data → empty."""
        picks = [
            {"ticker": "000001", "expected_returns": {}, "win_rates": {}, "bucket_sample_count": 30},
            {"ticker": "000002", "expected_returns": {}, "win_rates": {}, "bucket_sample_count": 30},
        ]
        result = _render_portfolio_expected_return(picks, "normal")
        assert result == ""

    def test_partial_winrate_not_diluted_by_missing(self, all_buy) -> None:
        """Regression: a BUY with T+30 edge but no T+30 win-rate must not
        inflate the win-rate denominator.

        Before the fix, ``total_weight`` accumulated for every pick with a
        valid ``t30`` edge, but ``weighted_winrate`` only accumulated for
        picks that *also* had ``t30_wr``.  Dividing the partial sum by the
        full weight showed a misleadingly low average win-rate (29% instead
        of 58%), undermining the "更高确信" front-door goal.
        """
        picks = [
            _pick(ticker="000001", t30=3.0, t30_wr=0.58, sample_count=30),
            _pick(ticker="000002", t30=5.0, t30_wr=None, sample_count=30),
        ]
        result = _render_portfolio_expected_return(picks, "normal")
        assert result != ""
        # Correct: only pick 000001 has win-rate → average is 58%, not 29%.
        assert "58%" in result
        assert "29%" not in result

    def test_thresholds_are_sane(self) -> None:
        assert _PORTFOLIO_SUMMARY_MIN_BUYS >= 2


class TestLowSampleNeverBuyGuard:
    """Finance-quant guard: a pick with sample_count < 20 can never be BUY.

    The front-door verdict gate (``build_front_door_verdict``) requires
    ``sample_count >= 20`` for BUY in any market regime. This is the safety
    property that makes any per-BUY low-sample weighting scheme
    unreachable — and the reason the R33 halving branch was dead code.
    Pinning it here protects the equal-weighting assumption of
    ``_render_portfolio_expected_return`` from a future verdict-gate change
    that silently reintroduces low-sample BUY picks.
    """

    @pytest.mark.parametrize("regime", ["normal", "cautious", "range", "risk_off", "crisis"])
    @pytest.mark.parametrize("sample_count", [0, 1, 5, 15, 19])
    def test_low_sample_pick_can_never_be_buy(self, regime: str, sample_count: int) -> None:
        from src.screening.investability import build_front_door_verdict

        # Maximal quality everywhere else — only sample_count is low.
        pick = {
            "ticker": "000001",
            "decision": "bullish",
            "composite_score": 0.99,
            "expected_returns": {"t30": 10.0},
            "win_rates": {"t30": 0.9},
            "bucket_sample_count": sample_count,
        }
        verdict = build_front_door_verdict(pick, market_regime=regime)
        assert verdict["action"] != "BUY", (
            f"low-sample pick (sample={sample_count}, regime={regime}) became BUY — "
            "the R33 equal-weighting assumption is broken; a low-sample weighting "
            "scheme would be needed again"
        )

