from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

_OBJECTIVE_KEYS = (
    "next_close_positive_rate",
    "next_close_payoff_ratio",
    "next_close_expectancy",
    "next_high_hit_rate",
    "t_plus_2_close_positive_rate",
    "t_plus_2_close_payoff_ratio",
    "t_plus_3_close_positive_rate",
    "t_plus_3_close_expectancy",
    "t_plus_3_close_payoff_ratio",
    "sample_weight",
    "max_future_high_return_2_5d_hit_rate_at_20pct",
    "median_max_future_high_return_2_5d",
    "next_open_return",
    "next_open_to_close_return",
    "time_to_hit_20pct_median",
)
_GUARDRAIL_KEYS = (
    "downside_p10",
    "window_coverage",
    "incremental_theme_exposure",
    "avg_composite_score_escaped",
    # Task 1 (Round 12): T+1 intraday drawdown tail-risk guardrail.
    # A very negative P10 indicates the strategy routinely suffers large intraday adverse
    # excursions from the open even when the day closes higher — hurting real P&L.
    "t_plus_1_intraday_drawdown_p10",
    # Task 1 (Round 13): escape gap cost floor — average T+1 open return for escaped runners.
    # Very negative values indicate runners that systematically gap down on T+1 open (limit-up reversal).
    "avg_escape_gap_cost",
    # Task 2 (Round 13): excess kurtosis of T+1 next-close returns — fat-tail distributional cap guardrail.
    # Extremely fat-tailed returns inflate apparent win rate and payoff metrics; this key acts as a cap.
    "next_close_return_kurtosis",
    # Task 1 (Round 19): sector concentration Gini coefficient — portfolio diversification guardrail.
    # A Gini near 1 means nearly all candidates are from a single sector, creating correlated risk.
    "sector_concentration_gini",
    # Task 1 (Round 20, Beta): realized payoff ratio — win_avg_return / abs(loss_avg_return).
    # Floor ≥ 1.0: per-trade average win must exceed per-trade average loss (basic edge requirement).
    "realized_payoff_ratio",
    # Task 1 (Round 27, Alpha): T+1 return distribution skewness cap guardrail.
    # Skewness more negative than −2.0 indicates extreme left-tail risk; acts as a cap.
    "next_close_return_skewness",
    # Task 2 (Round 27, Gamma): composite score spread floor guardrail.
    # score_spread_p95_p5 < 0.10 means the scoring function barely differentiates candidates.
    "score_spread_p95_p5",
    # Task 1 (Round 29, Alpha): PCA effective factor rank floor guardrail.
    # effective_factor_rank < 3 means the 12 factors collapse into fewer than 3 independent signals.
    "effective_factor_rank",
    # Task 2 (Round 29, Gamma): IS/OOS overfit score cap guardrail.
    # overfit_score > 0.30 means IS performance is materially better than OOS — overfit risk.
    "overfit_score",
)
_CONTEXT_KEYS = (
    "projected_theme_exposure",
    "theme_direction_peer_count",
    "theme_direction_rank",
    "liquidity_capacity_raw_100",
    "crowding_risk_raw_100",
    "gap_risk_raw_100",
)
BTST_QUALITY_FLOORS: dict[str, float] = {
    "next_close_positive_rate": 0.54,
    "next_high_hit_rate": 0.56,
    "t_plus_2_close_positive_rate": 0.52,
    "t_plus_2_close_payoff_ratio": 1.0,
    "t_plus_3_close_positive_rate": 0.50,
    "t_plus_3_close_expectancy": 0.0,
    "t_plus_3_close_payoff_ratio": 1.0,
    "downside_p10": -0.06,
    "sample_weight": 0.60,
    "window_coverage": 0.60,
    "avg_composite_score_escaped": 0.45,
    # Task 1 (Round 12): T+1 intraday drawdown floor.
    # The worst 10% of intraday open-to-low dips must not exceed -7 %.
    # Positions that routinely suffer >7% intraday draws blow real-money P&L
    # even when the daily close return is positive.
    "t_plus_1_intraday_drawdown_p10": -0.07,
    # Task 1 (Round 13): escape gap cost floor.
    # Escaped runners must not average a T+1 open gap of worse than -3 % (vs T close).
    # Strategies where selected runners routinely gap down on T+1 open (e.g. limit-up reversal)
    # destroy real-money P&L even if the T+1 close is positive.
    "avg_escape_gap_cost": -0.03,
    # Task 1 (Round 20, Beta): realized payoff ratio floor.
    # The per-trade win/loss asymmetry must be ≥ 1.0: average wins must exceed average losses.
    # Strategies where avg_loss > avg_win destroy capital even at moderate win rates.
    "realized_payoff_ratio": 1.0,
    # Task 2 (Round 23, Alpha): half-Kelly position sizing floor.
    # half-Kelly ≥ 0.02 means the strategy has enough positive expected value to warrant
    # at least a 2 % position size per trade; values below 0.02 indicate insufficient edge.
    "kelly_fraction_half": 0.02,
    # Task 3 (Round 23, Beta): regime win-rate consistency score floor.
    # regime_consistency_score = 1 − regime_win_rate_range; a score ≥ 0.70 ensures the
    # three-regime win-rate spread does not exceed 30 %.  Strategies with a lower score
    # exhibit severe bull-market dependency and carry high out-of-sample regime risk.
    "regime_consistency_score": 0.70,
    # Task 2 (Round 24): drawdown-adjusted Kelly fraction floor.
    # A positive edge must survive the drawdown severity penalty; floor 0.01 ensures
    # the strategy retains at least 1 % recommended position size after adjustment.
    "kelly_fraction_drawdown_adjusted": 0.01,
    # Task 2 (Round 26, Gamma): benchmark-adjusted Alpha floor.
    # alpha_avg_return = mean(next_close_return − hs300_daily_return); floor ≥ 0.0 enforces
    # that the strategy produces genuine skill-based return above the HS300 benchmark on average.
    # Strategies with negative alpha are merely riding market Beta and provide no edge.
    "alpha_avg_return": 0.0,
    # Task 1 (Round 27, Alpha): T+1 return distribution skewness floor.
    # Skewness < −2.0 indicates an extremely left-skewed T+1 return distribution (fat left tail).
    # Even at 60%+ win rate, severe negative skewness implies catastrophic-loss risk in the tail.
    # Profiles more negative than −2.0 violate this floor and should be penalised.
    # (Note: this is a minimum bound — more negative than -2.0 is unacceptable.)
    "next_close_return_skewness": -2.0,
    # Task 2 (Round 27, Gamma): composite score spread floor.
    # score_spread_p95_p5 = P95 − P5 of runner_composite_score across all candidates.
    # A spread < 0.10 means the scoring function barely differentiates candidates — the
    # optimizer is making near-random selections.  Floor ≥ 0.10 requires the score to
    # meaningfully stratify candidates before a profile is considered rollout-ready.
    "score_spread_p95_p5": 0.10,
    # Task 2 (Round 28, Gamma): bear-market domain alpha floor.
    # bear_alpha_avg = mean alpha (BTST − HS300) on days where HS300 < −0.3 %.
    # Allowing a slight negative bear alpha (floor −0.005) tolerates minor underperformance
    # on extreme down-days while rejecting strategies that massively bleed on bear days.
    # Strategies below −0.005 bear alpha lack regime robustness and carry hidden Beta risk.
    "bear_alpha_avg": -0.005,
    # Task 1 (Round 29, Alpha): effective factor rank floor.
    # effective_factor_rank = number of PCA principal components needed to explain ≥ 80 % of
    # factor variance.  A rank of 1 or 2 means nearly all factors load on the same latent
    # dimension — the 12 scoring factors are essentially one signal wearing many costumes.
    # Floor ≥ 3 ensures the strategy relies on at least 3 genuinely independent signal dimensions.
    "effective_factor_rank": 3,
    # Task 1 (Round 32, Gamma): conditional tail-risk score separation floor.
    # score_tail_separation = P(return < −3 % | low-score) − P(return < −3 % | high-score).
    # A positive value means the scoring function successfully pushes deep losses away from
    # high-score candidates; a value ≤ 0 means the score has no tail-risk filtering power.
    "score_tail_separation": 0.0,
    # Task 2 (Round 32, Alpha): extreme volume win-rate premium floor.
    # extreme_volume_win_rate_premium = win_rate(high-volume group) − win_rate(low-volume group).
    # A negative premium means放量 (expansion) is associated with *worse* next-day outcomes
    # relative to縮量 (contraction), indicating the factor is inverted or uninformative.
    # Floor ≥ 0.0 requires volume expansion to be at least neutral for win rate.
    "extreme_volume_win_rate_premium": 0.0,
    # Task 3 (Round 32, Beta): composite gate score floor.
    # composite_gate_score aggregates six quality dimensions into a 0–100 tradability index.
    # A score < 50 (grade D) means fewer than half the quality checks pass adequately.
    # Floor ≥ 50 ensures the profile reaches at least C-grade tradability before rollout.
    "composite_gate_score": 50.0,
    # Task 1 (Round 33, Alpha): expected value per trade floor.
    # expected_value_per_trade = win_rate × avg_win + loss_rate × avg_loss (E[R] per trade).
    # A value ≤ 0 means the strategy is expected to lose money on average, making it unprofitable.
    # Floor ≥ 0.0 requires the strategy to have at least a neutral expected return per trade.
    "expected_value_per_trade": 0.0,
    # Task 1 (Round 34, Alpha): multi-factor conditional lift floor.
    # multi_factor_lift = win_rate(3+ high-score factors) − win_rate(0 high-score factors).
    # A value ≤ 0 means simultaneous high-factor ranks provide no additional win-rate benefit,
    # invalidating the multi-factor synergy thesis.  Floor ≥ 0.0 requires at least neutral lift.
    "multi_factor_lift": 0.0,
    # Task 2 (Round 34, Gamma): adaptive sizing score floor.
    # adaptive_sizing_score is a 0–100 composite index combining EV, Kelly, gate, and tail separation.
    # A score < 50 (grade D) means fewer than half the sizing dimensions pass their quality thresholds.
    # Floor ≥ 50 ensures at least C-grade sizing confidence before a profile is considered rollout-ready.
    "adaptive_sizing_score": 50.0,
    # Task 1 (Round 35, Alpha): Sortino ratio floor.
    # sortino_ratio ≤ 0 means the strategy has negative risk-adjusted returns when only
    # downside volatility is counted.  Even if the Sharpe is mildly positive, a negative
    # Sortino indicates the downside tail is disproportionately large relative to the mean return.
    # Floor ≥ 0.0 requires at least break-even risk-adjusted performance on a downside basis.
    "sortino_ratio": 0.0,
    # Task 3 (Round 35, Beta): candidate diversity score floor.
    # diversity_score = 1 − HHI; a value < 0.30 means the top-1 sector dominates the pool
    # to a degree that exposes the strategy to correlated sector-specific shocks.
    # Floor ≥ 0.30 ensures at least moderate cross-sector distribution in the candidate pool.
    "diversity_score": 0.30,
    # Task 1 (Round 36, Alpha): right-tail dominance floor.
    # right_tail_dominance = (P95−P50)/|P5−P50|; a value < 0.80 means the upside tail is
    # narrower than 80 % of the downside tail width, indicating unfavourable return asymmetry.
    # Floor ≥ 0.80 ensures the right tail is at least 80 % as wide as the left tail.
    "right_tail_dominance": 0.80,
    # Task 2 (Round 36, Beta): composite score IC floor.
    # composite_ic = Spearman rank correlation between composite score and T+1 return.
    # A value ≤ 0 means the scoring function has zero or negative predictive power —
    # candidates ranked higher by the score do not achieve better returns on average.
    # Floor ≥ 0.0 requires at least a neutral positive IC before rollout.
    "composite_ic": 0.0,
    # Task 2 (Round 37, Beta): loss trade signature strength floor.
    # loss_signature_strength = mean |factor divergence| between win and loss groups across 7 factors.
    # A value < 0.02 means the 7 canonical BTST factors cannot distinguish winners from losers —
    # losses appear structurally random and cannot be avoided with the current factor set.
    # Floor ≥ 0.02 requires at least a 2 % average factor divergence for rollout eligibility.
    "loss_signature_strength": 0.02,
    # Task 1 (Round 38, Alpha): market environment win-rate gap floor.
    # env_win_rate_gap = bull_env_win_rate − bear_env_win_rate.  A value < −0.10 means the strategy
    # performs more than 10 % worse (win-rate) in bear/low-resonance environments vs bull environments.
    # Such extreme environment dependency signals hidden bull-market beta and poses OOS regime risk.
    # Floor ≥ −0.10 ensures the strategy does not collapse in bear conditions.
    "env_win_rate_gap": -0.10,
    # Task 2 (Round 38, Beta): positive-IC factor count floor.
    # positive_ic_factor_count = number of factors (out of 13) with Spearman IC > 0 vs next_close_return.
    # A count < 6 means fewer than half the scoring factors contribute positively —
    # the composite score is essentially averaging noise with signal.
    # Floor ≥ 6 requires at least a majority of factors to carry predictive power.
    "positive_ic_factor_count": 6,
    # Task 3 (Round 38, Gamma): top-quintile win-rate premium floor.
    # top_quintile_premium = win_rate_q5 − win_rate_q1.  A value ≤ 0 means the highest-scored
    # candidates do not achieve a higher win rate than the lowest-scored candidates — the scoring
    # system has zero monotone discriminative power.
    # Floor ≥ 0.0 requires at least a neutral positive premium for rollout eligibility.
    "top_quintile_premium": 0.0,
    # Task 1 (Round 39, Alpha): recency vs history win-rate gap floor.
    # recency_win_rate_gap = recent_win_rate − historical_win_rate.  A value < −0.15 means the
    # strategy's recent win rate is more than 15 % below its historical baseline — a strong signal
    # of overfitting or regime change that invalidates historical performance claims.
    # Floor ≥ −0.15 ensures the strategy has not substantially decayed in recent periods.
    "recency_win_rate_gap": -0.15,
    # Task 2 (Round 39, Beta): optimal score threshold win-rate lift floor.
    # optimal_threshold_lift = above_win_rate − overall_win_rate at the best percentile cutoff.
    # A value ≤ 0 means no score threshold can improve over the baseline win rate — the score
    # has zero entry-filtering value.  Floor ≥ 0.0 requires at least neutral improvement.
    "optimal_threshold_lift": 0.0,
    # Task 3 (Round 39, Gamma): simulated equity curve recovery factor floor.
    # recovery_factor = total_return / max_drawdown.  A value ≤ 0 means the strategy ends
    # with a net loss after simulating all trades — total return is negative.
    # Floor ≥ 0.0 requires at least break-even cumulative performance.
    "recovery_factor": 0.0,
    # Task 1 (Round 40, Alpha): factor synergy matrix max lift floor.
    # max_synergy_lift = best pairwise win-rate lift when both factors are above P67.
    # A value < 0.0 means no factor pair produces a win-rate improvement when co-activated —
    # the 7 core factors show zero synergy, invalidating multi-factor combination rationale.
    # Floor ≥ 0.0 requires at least one factor pair to show a non-negative synergy lift.
    "max_synergy_lift": 0.0,
    # Task 1 (Round 41, Alpha): factor IC rank consistency score floor.
    # factor_rank_consistency_score = 1 − mean(CV of factor rank positions across windows).
    # A score < 0.30 means the factor hierarchy shuffles wildly between replay windows —
    # the factor system is unstable and cannot provide reliable signal ordering.
    # Floor ≥ 0.30 requires at least moderate consistency in factor ranking across windows.
    "factor_rank_consistency_score": 0.30,
    # Task 2 (Round 41, Beta): volume-price alignment rate floor.
    # vol_price_alignment_rate = fraction of rows where volume direction matches price direction.
    # A rate < 0.45 means volume expansion is more often misleading than confirming —
    # the volume signal is either inverted or uninformative for this strategy.
    # Floor ≥ 0.45 requires volume to align with price direction at least 45 % of the time.
    "vol_price_alignment_rate": 0.45,
    # Task 3 (Round 41, Gamma): combined statistical significance score floor.
    # combined_significance_score = mean of 4 binary significance flags (z90/z95/t90/t95).
    # A score < 0.25 means the strategy passes fewer than 1 of 4 significance tests —
    # it cannot be statistically distinguished from random chance at even 90 % confidence.
    # Floor ≥ 0.25 requires at least 1 of 4 significance tests to pass before rollout.
    "combined_significance_score": 0.25,
    # Task 1 (Round 42, Alpha): composite score calibration slope floor.
    # calibration_slope = OLS slope of bin win rate on bin avg score across 5 equal-freq bins.
    # A value ≤ 0 means higher composite scores do NOT correlate with higher win rates —
    # the scoring system provides no directional guidance and is purely decorative.
    # Floor ≥ 0.0 requires the calibration slope to be at least non-negative.
    "calibration_slope": 0.0,
    # Task 2 (Round 42, Beta): close-strength top-quartile win-rate premium floor.
    # cs_top_quartile_premium = win_rate(Q4) − win_rate(Q1) stratified by close_strength.
    # A value ≤ 0 means the top close-strength quartile does not achieve a higher win rate
    # than the bottom quartile — close_strength provides zero monotone discriminative power.
    # Floor ≥ 0.0 requires at least neutral positive premium for rollout eligibility.
    "cs_top_quartile_premium": 0.0,
    # Task 3 (Round 42, Gamma): cross-window consensus pass rate floor.
    # consensus_windows_pct = fraction of replay windows satisfying ≥ 3 of 4 quality conditions.
    # A rate < 0.40 means fewer than 40 % of windows pass multi-metric quality checks —
    # the strategy is not consistently tradeable across market regimes.
    # Floor ≥ 0.40 requires at least 40 % of windows to satisfy ≥ 3 quality conditions.
    "consensus_windows_pct": 0.40,
    # Task 1 (Round 43, Alpha): profit factor floor.
    # profit_factor = gross_profit / gross_loss (total wins / total losses in aggregate).
    # A value < 1.0 means the strategy loses more in aggregate than it earns —
    # total losses exceed total profits across all trades in the window.
    # Floor ≥ 1.0 requires total profits to at least match total losses before rollout.
    "profit_factor": 1.0,
    # Task 3 (Round 43, Gamma): score momentum trend normalized slope floor.
    # score_trend_normalized = OLS slope of candidate_pool_avg_composite_score / mean(score).
    # A value < −0.10 means the average pool quality score is declining at more than 10 %
    # of its mean value per window — the optimizer is degrading candidate quality.
    # Floor ≥ −0.10 requires the score trend not to collapse severely across replay windows.
    "score_trend_normalized": -0.10,
}

# ---------------------------------------------------------------------------
# Task 2 (Round 13) — Quality cap guardrails (max-bounded, complementary to floors)
# ---------------------------------------------------------------------------
# Some metrics are harmful when TOO HIGH rather than too low.  ``BTST_QUALITY_CAPS``
# maps metric keys to their maximum acceptable values; exceeding any cap triggers a
# blocker via :func:`build_btst_quality_cap_blockers`.
BTST_QUALITY_CAPS: dict[str, float] = {
    # Excess kurtosis of T+1 next-close returns.  A fat-tailed distribution (kurtosis > 5)
    # means extreme outlier returns dominate the apparent win rate / payoff ratio, severely
    # over-stating strategy robustness.  Profiles above this cap should be penalised.
    "next_close_return_kurtosis": 5.0,
    # Task 1 (Round 19): sector concentration Gini cap.
    # A Gini coefficient > 0.60 indicates the candidate pool is concentrated in too few
    # sectors.  When most selected runners come from the same sector, a single adverse
    # sector event can wipe out the entire BTST portfolio simultaneously — systemic risk.
    # Profiles with Gini > 0.60 are flagged; optimization should prefer more-diversified
    # parameter combinations.
    "sector_concentration_gini": 0.60,
    # Task 2 (Round 29, Gamma): IS/OOS overfit score cap.
    # overfit_score = normalised gap between in-sample and out-of-sample performance.
    # A score above 0.30 means the IS metrics are more than 30 % better than OOS metrics
    # (relative to IS), indicating the parameter set is over-tuned to historical data.
    # Profiles with overfit_score > 0.30 carry high out-of-sample degradation risk.
    "overfit_score": 0.30,
    # Task 1 (Round 30, Gamma): parameter drift score cap.
    # param_drift_score = median relative drift (std/range) across key surface metrics between windows.
    # A score above 0.50 means parameter metrics are highly unstable across walk-forward windows,
    # indicating serious over-fitting or regime sensitivity in the parameter set.
    "param_drift_score": 0.50,
    # Task 2 (Round 31, Gamma): score CV across windows cap.
    # score_cv_across_windows = std / mean of candidate_pool_avg_composite_score across replay windows.
    # A CV above 0.30 means the scoring system produces wildly inconsistent evaluations window-to-window,
    # indicating that factor weights are regime-sensitive and the composite score lacks generality.
    "score_cv_across_windows": 0.30,
    # Task 3 (Round 36, Gamma): win-rate bootstrap CI width cap.
    # win_rate_ci_width = P97.5 − P2.5 of bootstrap win-rate distribution (200 resamples, seed=42).
    # A CI width above 0.30 means the sample is too small to reliably estimate the strategy's
    # win rate — the observed win rate could plausibly range over a 30 %-point band.
    # Profiles above this cap carry high estimation uncertainty and should not be promoted.
    "win_rate_ci_width": 0.30,
    # Task 3 (Round 40, Gamma): cross-window factor exposure drift score cap.
    # factor_drift_score = mean CV (std/|mean|) of 4 core surface metrics across replay windows.
    # A score above 0.50 means the strategy's key metrics vary by more than 50 % relative to
    # their mean across walk-forward windows — a sign of serious regime sensitivity or over-fitting.
    # Profiles with factor_drift_score > 0.50 carry high out-of-sample instability risk.
    "factor_drift_score": 0.50,
}
BTST_EXECUTION_GUARDRAILS: dict[str, dict[str, float]] = {
    "liquidity_capacity_raw_100": {"min": 50.0},
    "crowding_risk_raw_100": {"max": 70.0},
    "gap_risk_raw_100": {"max": 60.0},
}


@dataclass(frozen=True)
class CanonicalBTSTEvaluationBundle:
    objective_metrics: dict[str, float | None]
    guardrail_metrics: dict[str, float | None]
    context_metrics: dict[str, float | None]

    def lookup(self, key: str) -> float | None:
        if key in self.objective_metrics:
            return self.objective_metrics[key]
        if key in self.guardrail_metrics:
            return self.guardrail_metrics[key]
        return self.context_metrics.get(key)

    def to_payload(self) -> dict[str, dict[str, float | None]]:
        return {
            "objective_metrics": dict(self.objective_metrics),
            "guardrail_metrics": dict(self.guardrail_metrics),
            "context_metrics": dict(self.context_metrics),
        }


def coerce_numeric_metric_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _collect_numeric_metrics(metrics: dict[str, Any], keys: Sequence[str]) -> dict[str, float | None]:
    collected: dict[str, float | None] = {}
    for key in keys:
        collected[key] = coerce_numeric_metric_value(metrics.get(key))
    return collected


def build_canonical_btst_evaluation_bundle(metrics: dict[str, Any] | None) -> CanonicalBTSTEvaluationBundle:
    payload = dict(metrics or {})
    return CanonicalBTSTEvaluationBundle(
        objective_metrics=_collect_numeric_metrics(payload, _OBJECTIVE_KEYS),
        guardrail_metrics=_collect_numeric_metrics(payload, _GUARDRAIL_KEYS),
        context_metrics=_collect_numeric_metrics(payload, _CONTEXT_KEYS),
    )


def build_btst_quality_floor_blockers(metrics: dict[str, Any] | None, *, prefix: str = "btst_quality") -> list[str]:
    bundle = build_canonical_btst_evaluation_bundle(metrics)
    blockers: list[str] = []
    for metric_key, floor in BTST_QUALITY_FLOORS.items():
        value = bundle.lookup(metric_key)
        if value is None:
            continue
        if float(value) < float(floor):
            blockers.append(f"{prefix}_{metric_key}_floor_breach")
    return blockers


def build_btst_quality_cap_blockers(metrics: dict[str, Any] | None, *, prefix: str = "btst_quality") -> list[str]:
    """Return blocker labels for metrics that exceed their maximum cap in :data:`BTST_QUALITY_CAPS`.

    Complements :func:`build_btst_quality_floor_blockers` for metrics where high values are
    harmful (e.g. excess kurtosis — a fat-tailed return distribution inflates apparent performance).

    Args:
        metrics: Evaluated metrics dict from the evaluator or walk-forward summary.
        prefix: Prefix for blocker label strings.

    Returns:
        List of cap-breach blocker labels (empty when all metrics are within bounds).
    """
    bundle = build_canonical_btst_evaluation_bundle(metrics)
    blockers: list[str] = []
    for metric_key, cap in BTST_QUALITY_CAPS.items():
        value = bundle.lookup(metric_key)
        if value is None:
            continue
        if float(value) > float(cap):
            blockers.append(f"{prefix}_{metric_key}_cap_breach")
    return blockers


def build_btst_execution_blockers(metrics: dict[str, Any] | None) -> list[str]:
    bundle = build_canonical_btst_evaluation_bundle(metrics)
    blockers: list[str] = []
    for metric_key, guardrail in BTST_EXECUTION_GUARDRAILS.items():
        value = bundle.lookup(metric_key)
        if value is None:
            continue
        min_floor = guardrail.get("min")
        max_cap = guardrail.get("max")
        if min_floor is not None and float(value) < float(min_floor):
            blockers.append(f"{metric_key.removesuffix('_raw_100')}_floor_breach")
        if max_cap is not None and float(value) > float(max_cap):
            blockers.append(f"{metric_key.removesuffix('_raw_100')}_cap_breach")
    return blockers
