"""Tests for R33 (portfolio expected return summary) in top_picks.

C222 (2026-06-28 horizon 一致性): R33 now aggregates the BUY-gate decision
horizon (max of T+5/T+10) instead of T+30. The one-line summary reads
``组合 T+5/T+10 决策预期: +X.XX% (等权) | 平均胜率: XX% | BUY 数: N`` and
reuses per-pick ``expected_returns.t5`` / ``t10`` and ``win_rates.t5`` /
``t10`` already attached by :func:`rank_recommendations_by_investability`.
T+30 is retained only as the long-term invalidation horizon (see
``_extract_t30_metrics`` docstring).
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
    """Build a pick dict with the fields R33 reads.

    C222: BUY gate decision horizon (max of t5/t10) — defaults mirror the
    T+30 values so existing tests asserting on t30 numbers also exercise
    the decision horizon (max(t5,t10) == t30 by construction). Tests that
    need decision-horizon data *missing* (e.g. partial winrate regression)
    can pass ``t30_wr=None`` — that drops ``t5`` from ``win_rates``, leaving
    only the T+30 invalidation field, so ``_extract_decision_horizon_metrics``
    returns ``(edge, None)`` and the winrate is excluded from the average
    (denominator undiluted).
    """
    # Decision horizon mirrors t30 by default. Use t5 as the carrier so
    # max(t5, t10) == t5 == t30 when t10 is absent.
    expected = {"t5": t30, "t30": t30}
    win: dict = {"t30": t30_wr}
    if t30_wr is not None:
        win["t5"] = t30_wr
    return {
        "ticker": ticker,
        "name": ticker,
        "composite_score": composite_score,
        "expected_returns": expected,
        "win_rates": win,
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
        # C222: header changed to "组合 T+5/T+10 决策预期" (decision horizon).
        assert "组合 T+5/T+10 决策预期" in result
        assert "BUY 数" in result
        assert "2" in result
        assert "+4.00%" in result  # mean(max(t5,t10)=3.0, max(t5,t10)=5.0)

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

    def test_winrate_below_half_uses_red_not_yellow(self, all_buy) -> None:
        """BH-003: win rate in [0.45, 0.50) must be RED, not YELLOW.

        The portfolio-summary win-rate color previously used a 0.45 yellow
        threshold that was inconsistent with every other win-rate display in
        the front door (the hit-rate panel at line ~183 and the BUY verdict
        gate both use 0.50 for yellow / 0.55 for green). A 47% portfolio
        win-rate would have rendered yellow here while failing the BUY bar
        elsewhere. Aligned to 0.50 so the front door speaks with one voice.
        """
        picks = [_pick(ticker="000001", t30_wr=0.46), _pick(ticker="000002", t30_wr=0.48)]
        result = _render_portfolio_expected_return(picks, "normal")
        assert result != ""
        assert Fore.RED in result
        assert Fore.YELLOW not in result

    def test_buy_picks_are_equal_weighted(self, all_buy) -> None:
        """BUY picks are equal-weighted in the portfolio average.

        The portfolio summary aggregates the decision-horizon (max t5/t10)
        edge over BUY picks only. A ``sample_count < 20`` halving scheme was
        removed because it was unreachable: :func:`build_front_door_verdict`
        already requires ``sample_count >= 20`` for any BUY classification
        (see ``test_low_sample_pick_can_never_be_buy``), so a low-sample pick
        can never enter the BUY aggregate and the halving safeguard could
        never trigger. Equal weighting now matches the spec's documented
        "等权或 composite_score 归一化" alternative.
        """
        high_sample = _pick(ticker="000001", t30=10.0, sample_count=100)
        low_sample = _pick(ticker="000002", t30=0.0, sample_count=5)
        result = _render_portfolio_expected_return([high_sample, low_sample], "normal")
        # Equal weight: mean(10.0, 0.0) = 5.00%
        assert "+5.00%" in result

    def test_all_buys_missing_decision_horizon_returns_empty(self, all_buy) -> None:
        """C222: when no picks have valid decision-horizon (T+5/T+10) data → empty.

        Previously asserted on missing T+30; now both t5 and t30 are absent
        so neither the decision-horizon aggregator nor the (retained)
        invalidation-horizon helper can produce a number.
        """
        picks = [
            {"ticker": "000001", "expected_returns": {}, "win_rates": {}, "bucket_sample_count": 30},
            {"ticker": "000002", "expected_returns": {}, "win_rates": {}, "bucket_sample_count": 30},
        ]
        result = _render_portfolio_expected_return(picks, "normal")
        assert result == ""

    def test_partial_winrate_not_diluted_by_missing(self, all_buy) -> None:
        """Regression: a BUY with decision-horizon edge but no decision-horizon
        win-rate must not inflate the win-rate denominator.

        Before the fix (carried over from T+30 to decision-horizon), the
        aggregator accumulated for every pick with a valid edge, but the
        win-rate sum only accumulated for picks that *also* had a matching
        win-rate.  Dividing the partial sum by the full count showed a
        misleadingly low average win-rate (29% instead of 58%), undermining
        the "更高确信" front-door goal.

        C222: previously used ``t30_wr=None`` to express "no winrate"; now
        uses the same ``t30_wr=None`` (which drops ``t5`` from win_rates via
        :func:`_pick`), so ``_extract_decision_horizon_metrics`` returns
        ``(edge, None)`` and the winrate is excluded from the average.
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
        # C222: BUY gate is now T+5 OR T+10 horizon, so provide both
        # t5 and t10 (decision-horizon) AND t30 (invalidation) fields so
        # the test exercises the "high-quality on every horizon, only
        # sample_count is low" contract.
        pick = {
            "ticker": "000001",
            "decision": "bullish",
            "composite_score": 0.99,
            "expected_returns": {"t5": 10.0, "t10": 10.0, "t30": 10.0},
            "win_rates": {"t5": 0.9, "t10": 0.9, "t30": 0.9},
            "bucket_sample_count": sample_count,
        }
        verdict = build_front_door_verdict(pick, market_regime=regime)
        assert verdict["action"] != "BUY", (
            f"low-sample pick (sample={sample_count}, regime={regime}) became BUY — "
            "the R33 equal-weighting assumption is broken; a low-sample weighting "
            "scheme would be needed again"
        )
