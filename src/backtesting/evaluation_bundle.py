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
    # Task 1 (Round 53, Alpha): conditional factor-synergy win-rate lift floor guardrail.
    # conditional_lift = high_signal_win_rate − low_signal_win_rate.
    # A negative lift means the scoring system does not differentiate high-signal from low-signal rows.
    "conditional_lift",
    # Task 1 (Round 54, Alpha): tail-risk asymmetry floor guardrail.
    # tail_asymmetry = right_tail_95 − abs(CVaR_5%); positive = right-skewed (good).
    # Floor ≥ 0.0 requires the right tail to be at least as large as the left tail in absolute terms.
    "tail_asymmetry",
    # Task 1 (Round 55, Alpha): multi-factor mean IC floor guardrail.
    # mean_ic = signed average Spearman IC across 7 core BTST factors vs next_day_return.
    # Floor ≥ 0.0 requires the factor set to have net positive predictive power.
    "mean_ic",
    # Task 1 (Round 56, Alpha): sector diversification score floor guardrail.
    # diversification_score = 1 − HHI; lower means candidate pool is sector-concentrated.
    # Floor ≥ 0.0 keeps the metric present; tighten once baseline distributions are known.
    "diversification_score",
    # Task 2 (Round 56, Beta): score rank IC floor guardrail.
    # rank_ic = Spearman IC between composite score and T+1 return.
    # Floor ≥ 0.0 requires the scoring system to have net positive predictive validity.
    "rank_ic",
    # Task 1 (Round 57, Alpha): market regime adaptability floor guardrail.
    # regime_adaptability = min(bull_win_rate, bear_win_rate); measures ability to profit in both regimes.
    # Floor ≥ 0.4 ensures the strategy has at least 40% win rate in the weaker market regime.
    "regime_adaptability",
    # Task 1 (Round 58, Alpha): optimal entry threshold win rate floor guardrail.
    # optimal_win_rate = best win rate achieved across P40–P80 score percentile thresholds.
    # Floor ≥ 0.5 requires the best score-filtered sub-pool to achieve at least 50% win rate.
    "optimal_win_rate",
    # Task 1 (Round 59, Alpha): return distribution skewness floor guardrail.
    # Skewness more negative than −2.0 indicates extreme left-tail risk in next_day_return.
    # Acts as a cap on distributional risk; consistent with next_close_return_skewness guardrail.
    "skewness",
    # Task 2 (Round 59, Beta): composite quality score floor guardrail.
    # composite_quality_score aggregates win_rate, profit_factor, IR, and optional dimensions.
    # Floor ≥ 40.0 (grade C) ensures the strategy passes a minimum multi-dimensional quality bar.
    "composite_quality_score",
    # Task 1 (Round 60, Alpha): multi-signal consistency win-rate lift floor guardrail.
    # signal_consistency_lift < 0.0 means high-consistency rows don't outperform low-consistency rows.
    "signal_consistency_lift",
    # Task 1 (Round 61, Alpha): concentration risk cap guardrail.
    # concentration_risk > 0.7 means P&L is concentrated in ≤5 top/bottom trades — high overfitting risk.
    "concentration_risk",
    # Task 2 (Round 61, Beta): extreme market resilience score floor guardrail.
    # resilience_score < 0.3 means the strategy wins less than 30% of the time under extreme down conditions.
    "resilience_score",
    # Task 1 (Round 62, Alpha): low-liquidity fraction cap guardrail.
    # low_liquidity_pct > 0.4 means >40% of candidates have float turnover < 2% — severe liquidity risk.
    "low_liquidity_pct",
    # Task 2 (Round 62, Beta): cost-adjusted profit factor floor guardrail.
    # cost_adjusted_profit_factor < 1.0 means net wins do not exceed net losses after cost.
    "cost_adjusted_profit_factor",
    # Task 1 (Round 63, Alpha): best stop-loss/take-profit profit factor floor guardrail.
    # best_profit_factor < 1.0 means even the optimal sl/tp combo fails to achieve positive edge.
    "best_profit_factor",
    # Task 2 (Round 63, Beta): best factor-combination win rate floor guardrail.
    # best_combo_win_rate < 0.5 means no factor subset achieves majority win rate.
    "best_combo_win_rate",
    # Task 2 (Round 64, Beta): factor validity window IC stability guardrail.
    # ic_stability > 0.2 means the IC across time segments is too volatile to trust factor signals.
    "ic_stability",
    # Task 1 (Round 65, Alpha): total return attribution floor guardrail.
    # total_attribution = sum of |partial contributions| across 7 factors vs next_day_return.
    # Floor ≥ 0.0 ensures the metric is present; positive values indicate factors explain some return variance.
    "total_attribution",
    # Task 2 (Round 65, Beta): multi-timeframe consistency score floor guardrail.
    # timeframe_consistency ∈ {0.0, 0.5, 1.0}; Floor ≥ 0.5 requires at least partial consistency.
    "timeframe_consistency",
    # Task 3 (Round 65, Gamma): IC stability trend slope cap guardrail.
    # ic_stability_trend_slope > 0.01 means factor validity is deteriorating across windows.
    "ic_stability_trend_slope",
    # Task 3 (Round 66, Gamma): cross-window attribution trend slope floor guardrail.
    # attribution_trend_slope < -0.02 means factor attribution explanatory power is declining across windows.
    "attribution_trend_slope",
    # Task 1 (Round 67, Alpha): score dispersion win-rate spread floor guardrail.
    "score_win_rate_spread",
    # Task 2 (Round 67, Beta): fund flow breakout synergy win rate floor guardrail.
    "flow_breakout_synergy",
    # Task 3 (Round 67, Gamma): cross-window nonlinear interaction trend slope floor guardrail.
    "interaction_trend_slope",
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
    # Task 1 (Round 44, Alpha): RS top-quartile win-rate premium floor.
    # rs_top_quartile_premium = win_rate(Q4) − win_rate(Q1) where Q4/Q1 are top/bottom RS quartiles.
    # A value < 0.0 means the highest-RS candidates do not outperform the lowest-RS candidates,
    # indicating the relative-strength factor provides no positive selection edge.
    # Floor ≥ 0.0 requires the RS factor to deliver at least a neutral (non-negative) premium.
    "rs_top_quartile_premium": 0.0,
    # Task 2 (Round 45, Beta): catalyst-theme top-quartile win-rate premium floor.
    # catalyst_top_quartile_premium = win_rate(Q4) − win_rate(Q1) stratified by catalyst_theme_score.
    # A value < 0.0 means the highest catalyst-scoring candidates do not outperform the lowest —
    # the catalyst_theme_score factor provides zero monotone discriminative power.
    # Floor ≥ 0.0 requires at least neutral positive premium for rollout eligibility.
    "catalyst_top_quartile_premium": 0.0,
    # Task 3 (Round 45, Gamma): top-candidate cross-window consistency rate floor.
    # top_candidate_consistency_rate = fraction of windows where top-quintile win rate ≥ 0.60.
    # A rate < 0.40 means fewer than 40 % of windows achieve the ≥ 60 % win-rate target for
    # top-scored candidates — the strategy is not reliably selecting high-conviction winners.
    # Floor ≥ 0.40 requires the top candidates to consistently beat 60 % win rate in ≥ 40 % of windows.
    "top_candidate_consistency_rate": 0.40,
    # Task 1 (Round 46, Alpha): volume-price divergence low-vs-high win-rate lift floor.
    # vpd_low_vs_high_lift = win_rate(low divergence) − win_rate(high divergence).
    # A value < 0.0 means low-divergence stocks do not outperform high-divergence stocks —
    # the volume-price-divergence signal has no discriminative power.
    # Floor ≥ 0.0 requires low-divergence candidates to be at least as good as high-divergence.
    "vpd_low_vs_high_lift": 0.0,
    # Task 2 (Round 46, Beta): score distribution skewness floor.
    # score_skewness < 0.0 indicates a left-skewed score distribution (more low-scoring candidates).
    # An ideal scoring system should produce right-skewed scores (more high-quality candidates selected).
    # Floor ≥ 0.0 requires the score distribution to be non-left-skewed.
    "score_skewness": 0.0,
    # Task 2 (Round 46, Beta): score positive fraction floor.
    # score_positive_pct < 0.50 means fewer than half of candidates receive a positive composite score,
    # indicating the scoring system is too conservative or the candidate pool quality is poor.
    # Floor ≥ 0.50 requires the majority of scored candidates to have a positive composite score.
    "score_positive_pct": 0.50,
    # Task 1 (Round 47, Alpha): momentum slope high-vs-low win-rate lift floor.
    # ms_high_vs_low_lift = win_rate(high momentum) − win_rate(low momentum).
    # A value < 0.0 means high-momentum stocks do not outperform low-momentum stocks —
    # the momentum_slope_20d factor has no discriminative power.
    # Floor ≥ 0.0 requires high-momentum candidates to be at least as good as low-momentum.
    "ms_high_vs_low_lift": 0.0,
    # Task 2 (Round 47, Beta): net inflow ratio high-vs-low win-rate lift floor.
    # inflow_high_vs_low_lift = win_rate(high inflow) − win_rate(low inflow).
    # A value < 0.0 means high net-inflow stocks do not outperform low net-inflow stocks —
    # the t0_estimated_net_inflow_ratio factor has no discriminative power.
    # Floor ≥ 0.0 requires high-inflow candidates to be at least as good as low-inflow.
    "inflow_high_vs_low_lift": 0.0,
    # Task 3 (Round 47, Gamma): cross-window factor IC positive consistency rate floor.
    # positive_ic_consistency_rate = fraction of (factor × window) pairs where IC > 0.
    # A rate < 0.50 means fewer than half the factor-window pairs show positive IC,
    # indicating most factors are unreliable or regime-dependent across windows.
    # Floor ≥ 0.50 requires the majority of factor predictions to be positively predictive.
    "positive_ic_consistency_rate": 0.50,
    # Task 1 (Round 48, Alpha): VEQ high-vs-low win-rate lift floor.
    # veq_high_vs_low_lift = win_rate(high VEQ) − win_rate(low VEQ).
    # Floor ≥ 0.0 requires high-VEQ candidates to be at least as good as low-VEQ.
    "veq_high_vs_low_lift": 0.0,
    # Task 2 (Round 48, Beta): sector resonance high-vs-low win-rate lift floor.
    # sr_high_vs_low_lift = win_rate(high resonance) − win_rate(low resonance).
    # Floor ≥ 0.0 requires high-resonance candidates to be at least as good as low-resonance.
    "sr_high_vs_low_lift": 0.0,
    # Task 3 (Round 48, Gamma): cross-window expected-value trend slope floor.
    # ev_trend_slope = OLS slope of expected_value_per_trade across replay windows.
    # Floor ≥ -0.05 prevents strategies whose EV is in severe decline from passing quality gates.
    "ev_trend_slope": -0.05,
    # Task 1 (Round 49, Alpha): multi-factor consensus win-rate lift floor.
    # consensus_lift = win_rate(high consensus) − win_rate(low consensus).
    # Floor ≥ 0.0 requires high-consensus candidates to be at least as good as low-consensus.
    "consensus_lift": 0.0,
    # Task 2 (Round 49, Beta): score decile top-vs-bottom premium floor.
    # top_decile_premium = win_rate(D10) − win_rate(D1).
    # Floor ≥ 0.0 requires the top decile to outperform the bottom decile.
    "top_decile_premium": 0.0,
    # Task 3 (Round 49, Gamma): cross-window Sortino trend slope floor.
    # sortino_trend_slope = OLS slope of sortino_ratio across replay windows.
    # Floor ≥ -0.10 prevents strategies with rapidly deteriorating Sortino from passing.
    "sortino_trend_slope": -0.10,
    # Task 3 (Round 50, Gamma): cross-window Sharpe trend slope floor.
    # sharpe_trend_slope = OLS slope of sharpe_ratio across replay windows.
    # Floor ≥ -0.02 prevents strategies with rapidly deteriorating Sharpe from passing (tightened in Round 76).
    "sharpe_trend_slope": -0.02,
    # Task 1 (Round 51, Alpha): win/loss magnitude ratio floor.
    # win_loss_magnitude_ratio = avg_win / avg_loss magnitude; floor ≥ 1.0 ensures wins
    # exceed losses on average — a necessary condition for positive expectancy.
    "win_loss_magnitude_ratio": 1.0,
    # Task 1 (Round 51, Alpha): Kelly fraction floor.
    # kelly_fraction = win_rate − (1 − win_rate) / ratio; floor ≥ 0.0 means the strategy
    # has enough edge to warrant a positive position size (negative Kelly = no bet).
    "kelly_fraction": 0.0,
    # Task 3 (Round 51, Gamma): cross-window profit-factor trend slope floor.
    # pf_trend_slope = OLS slope of profit_factor across replay windows.
    # Floor ≥ -0.10 prevents strategies with rapidly deteriorating PF from passing.
    "pf_trend_slope": -0.10,
    # Task 1 (Round 52, Alpha): annualised Information Ratio floor.
    # information_ratio = mean_return / std_return * sqrt(252).  Floor ≥ 0.0 requires
    # the strategy to have at least a neutral risk-adjusted return (IR ≥ 0).
    "information_ratio": 0.0,
    # Task 2 (Round 52, Beta): score concentration index floor.
    # score_concentration_index = high_score_pct − low_score_pct.  Floor ≥ 0.0 requires
    # the candidate pool to have at least as many high-score as low-score candidates.
    "score_concentration_index": 0.0,
    # Task 3 (Round 52, Gamma): cross-window Kelly fraction trend slope floor.
    # kelly_trend_slope = OLS slope of kelly_fraction across replay windows.
    # Floor ≥ -0.05 prevents strategies whose Kelly fraction is in severe decline from passing.
    "kelly_trend_slope": -0.05,
    # Task 1 (Round 53, Alpha): conditional factor-synergy win-rate lift floor.
    # conditional_lift = high_signal_win_rate − low_signal_win_rate.
    # Floor ≥ 0.0 requires the high-signal tier to win at least as often as the low-signal tier.
    "conditional_lift": 0.0,
    # Task 3 (Round 53, Gamma): cross-window Information Ratio trend slope floor.
    # ir_trend_slope = OLS slope of information_ratio across replay windows.
    # Floor ≥ -0.05 prevents strategies whose IR is in severe decline from passing.
    "ir_trend_slope": -0.05,
    # Task 1 (Round 54, Alpha): tail-risk asymmetry floor.
    # tail_asymmetry = right_tail_95 − abs(CVaR_5%); positive means the strategy profits more from the right tail than it loses from the left tail.
    # Floor ≥ 0.0 requires the right tail to at least match the left tail.
    "tail_asymmetry": 0.0,
    # Task 3 (Round 54, Gamma): conditional factor synergy cross-window trend slope floor.
    # conditional_lift_trend_slope = OLS slope of conditional_lift across replay windows.
    # Floor ≥ -0.01 prevents strategies whose factor synergy is deteriorating steeply from passing.
    "conditional_lift_trend_slope": -0.01,
    # Task 1 (Round 55, Alpha): multi-factor mean IC floor.
    # mean_ic = signed average Spearman IC across 7 core BTST factors vs next_day_return.
    # Floor ≥ 0.0 requires that the factor set has net positive predictive power on average.
    "mean_ic": 0.0,
    # Task 1 (Round 56, Alpha): sector diversification score floor.
    # diversification_score = 1 − HHI; positive = at least some cross-sector spread.
    # Floor ≥ 0.0 keeps the metric present; tighten to 0.30 once baselines are established.
    "diversification_score": 0.0,
    # Task 2 (Round 56, Beta): score rank IC floor.
    # rank_ic = Spearman IC between composite score and T+1 return.
    # Floor ≥ 0.0 requires the scoring system to have net positive predictive validity.
    "rank_ic": 0.0,
    # Task 1 (Round 57, Alpha): market regime adaptability floor.
    # regime_adaptability = min(bull_win_rate, bear_win_rate).
    # Floor ≥ 0.4 ensures the strategy retains at least 40% win rate in the weaker regime.
    "regime_adaptability": 0.4,
    # Task 1 (Round 58, Alpha): optimal entry threshold win rate floor.
    # optimal_win_rate = best win rate achieved by filtering on score percentile thresholds (P40–P80).
    # Floor ≥ 0.5 requires at least one threshold to yield a majority win rate.
    "optimal_win_rate": 0.5,
    # Task 3 (Round 57, Gamma): cross-window rank-IC OLS trend slope floor.
    # rank_ic_trend_slope < -0.02 signals rapid predictive-validity deterioration across windows.
    "rank_ic_trend_slope": -0.02,
    # Task 3 (Round 58, Gamma): cross-window regime adaptability OLS trend slope floor.
    # regime_trend_slope < -0.02 signals consistent deterioration of regime adaptability over time.
    "regime_trend_slope": -0.02,
    # Task 1 (Round 59, Alpha): return distribution skewness floor.
    # skewness < 0.0 indicates a left-skewed (negatively skewed) return distribution.
    # Positive skewness is desired — more right-tail opportunities than left-tail losses.
    "skewness": 0.0,
    # Task 2 (Round 59, Beta): composite quality score floor.
    # composite_quality_score < 40.0 (grade D) means the strategy fails most multi-dimensional
    # quality checks; floor ≥ 40.0 (grade C) ensures minimum multi-dimensional quality bar.
    "composite_quality_score": 40.0,
    # Task 3 (Round 59, Gamma): cross-window threshold win-rate trend slope floor.
    # threshold_win_rate_trend_slope < -0.02 signals consistent deterioration of optimal win-rate across windows.
    "threshold_win_rate_trend_slope": -0.02,
    # Task 1 (Round 60, Alpha): multi-signal consistency lift floor.
    # signal_consistency_lift < 0.0 means high-consistency rows underperform low-consistency rows.
    "signal_consistency_lift": 0.0,
    # Task 3 (Round 60, Gamma): cross-window quality score trend slope floor.
    # quality_score_trend_slope < -1.0 signals severe consistent deterioration of quality score.
    "quality_score_trend_slope": -1.0,
    # Task 2 (Round 61, Beta): extreme market resilience score floor.
    # resilience_score < 0.3 means the strategy fails to win under extreme down conditions.
    "resilience_score": 0.3,
    # Task 3 (Round 61, Gamma): signal consistency trend slope floor.
    # consistency_trend_slope < -0.01 means the signal consistency is deteriorating meaningfully.
    "consistency_trend_slope": -0.01,
    # Task 2 (Round 62, Beta): cost-adjusted profit factor floor.
    # cost_adjusted_profit_factor < 1.0 means net wins do not exceed net losses after 0.3% bilateral cost.
    "cost_adjusted_profit_factor": 1.0,
    # Task 3 (Round 62, Gamma): cross-window resilience trend slope floor.
    # resilience_trend_slope < -0.02 means extreme-market win rate is deteriorating across windows.
    "resilience_trend_slope": -0.02,
    # Task 1 (Round 63, Alpha): best stop-loss/take-profit profit factor floor.
    # best_profit_factor < 1.0 means no sl/tp combination achieves positive net edge.
    "best_profit_factor": 1.0,
    # Task 2 (Round 63, Beta): best factor-combination win rate floor.
    # best_combo_win_rate < 0.5 means no factor subset achieves majority win rate.
    "best_combo_win_rate": 0.5,
    # Task 3 (Round 63, Gamma): cross-window cost-adjusted PF trend slope floor.
    # cost_pf_trend_slope < -0.1 means cost-adjusted profit factor is deteriorating significantly across windows.
    "cost_pf_trend_slope": -0.1,
    # Task 3 (Round 64, Gamma): cross-window best combo win rate trend slope floor.
    # combo_win_rate_trend_slope < -0.02 means best combo win rate is declining meaningfully.
    "combo_win_rate_trend_slope": -0.02,
    # Task 1 (Round 65, Alpha): total return attribution floor.
    # total_attribution < 0.0 is impossible (sum of absolute values), floor = 0.0 ensures metric is present.
    "total_attribution": 0.0,
    # Task 2 (Round 65, Beta): multi-timeframe consistency score floor.
    # timeframe_consistency < 0.5 means score and win-rate trends are both deteriorating — signal degradation.
    "timeframe_consistency": 0.5,
    # Task 3 (Round 66, Gamma): cross-window total attribution trend slope floor.
    # attribution_trend_slope < -0.02 means factor attribution explanatory power is deteriorating significantly across windows.
    "attribution_trend_slope": -0.02,
    # Task 1 (Round 67, Alpha): score dispersion win-rate spread floor.
    # score_win_rate_spread < 0.0 means high-score group performs worse than low-score group — no discriminatory power.
    "score_win_rate_spread": 0.0,
    # Task 2 (Round 67, Beta): fund flow breakout synergy win rate floor.
    # flow_breakout_synergy < 0.5 means the high-flow+high-breakout quadrant fails to achieve baseline win rate.
    "flow_breakout_synergy": 0.5,
    # Task 3 (Round 67, Gamma): cross-window nonlinear interaction trend slope floor.
    # interaction_trend_slope < -0.01 means nonlinear interaction effect is declining across windows.
    "interaction_trend_slope": -0.01,
    # Task 1 (Round 68, Alpha): tail filter effect floor.
    # tail_filter_effect < -0.05 means filtering tail events sharply reduces win rate — alarming.
    "tail_filter_effect": -0.05,
    # Task 3 (Round 68, Gamma): cross-window score dispersion trend slope floor.
    # dispersion_trend_slope < -0.01 means score discrimination power is declining across windows.
    "dispersion_trend_slope": -0.01,
    # Task 1 (Round 69, Alpha): RS ranking spread floor.
    # rs_rank_spread < 0.0 means top RS stocks have no win-rate advantage over bottom RS stocks.
    "rs_rank_spread": 0.0,
    # Task 2 (Round 69, Beta): turnover filter effect floor.
    # turnover_filter_effect < -0.05 means normal-turnover stocks have much lower win rate than all — alarming.
    "turnover_filter_effect": -0.05,
    # Task 1 (Round 70, Alpha): price position win-rate spread floor.
    # cs_win_rate_spread < 0.0 means high close_strength stocks do not outperform low close_strength stocks.
    "cs_win_rate_spread": 0.0,
    # Task 3 (Round 70, Gamma): RS rank spread cross-window trend slope floor.
    # rs_rank_trend_slope < -0.01 means RS ranking discriminatory power is declining across windows.
    "rs_rank_trend_slope": -0.01,
    # Task 1 (Round 71, Alpha): sector momentum ranking win-rate spread floor.
    # momentum_win_spread < 0.0 means high-momentum stocks have no win-rate advantage over low-momentum stocks.
    "momentum_win_spread": 0.0,
    # Task 2 (Round 71, Beta): volume structure win-rate spread floor.
    # vol_structure_spread < 0.0 means high-volume-expansion stocks have no win-rate advantage over low-volume stocks.
    "vol_structure_spread": 0.0,
    # Task 3 (Round 71, Gamma): price position cross-window trend slope floor.
    # price_pos_trend_slope < -0.01 means price position discriminatory power is declining across windows.
    "price_pos_trend_slope": -0.01,
    # Task 1 (Round 72, Alpha): multi-factor composite Z-score win-rate spread floor.
    # zscore_win_spread < 0.0 means composite Z-score has no discriminatory power over next-day return.
    "zscore_win_spread": 0.0,
    # Task 2 (Round 72, Beta): return persistence score floor.
    # persistence_score < 0.4 means win-rate is highly unstable across rolling periods.
    "persistence_score": 0.4,
    # Task 3 (Round 72, Gamma): momentum rank trend slope floor.
    # momentum_rank_trend_slope < -0.01 means momentum discriminatory power is declining across windows.
    "momentum_rank_trend_slope": -0.01,
    # Task 1 (Round 73, Alpha): market breadth win rate floor.
    # breadth_win_rate < 0.45 means the candidate pool quality is very poor (fewer than 45% of stocks advance).
    "breadth_win_rate": 0.45,
    # Task 2 (Round 73, Beta): factor IC consistency ratio floor.
    # ic_consistency_ratio < 0.4 means fewer than 40% of the 7 core factors have positive predictive direction.
    "ic_consistency_ratio": 0.4,
    # Task 3 (Round 73, Gamma): Z-score win-spread cross-window trend slope floor.
    # zscore_trend_slope < -0.01 means multi-factor Z-score discriminatory power is declining across windows.
    "zscore_trend_slope": -0.01,
    # Task 1 (Round 74, Alpha): signal strength stratification spread floor.
    # stratification_spread < 0.0 means the highest-score quintile does NOT outperform the lowest-score quintile.
    "stratification_spread": 0.0,
    # Task 2 (Round 74, Beta): conditional momentum synergy edge floor.
    # conditional_momentum_edge < 0.0 means dual-strong (high momentum + high flow) fails to beat dual-weak.
    "conditional_momentum_edge": 0.0,
    # Task 3 (Round 74, Gamma): market breadth win-rate cross-window trend slope floor.
    # breadth_trend_slope < -0.01 means market breadth quality is declining across walk-forward windows.
    "breadth_trend_slope": -0.01,
    # Task 1 (Round 75, Alpha): simplified Sharpe ratio floor.
    # sharpe_ratio < 0.0 means mean return is negative — strategy loses money on average.
    "sharpe_ratio": 0.0,
    # Task 3 (Round 75, Gamma): stratification spread cross-window trend slope floor.
    # stratification_trend_slope < -0.01 means signal stratification discriminatory power is declining.
    "stratification_trend_slope": -0.01,
    # Task 1 (Round 76, Alpha): gain/loss ratio floor.
    # gain_loss_ratio < 1.0 means average losses exceed average gains — negative edge.
    "gain_loss_ratio": 1.0,
    # Task 1 (Round 76, Alpha): tail asymmetry score floor.
    # tail_asymmetry_score < -0.05 means left fat tail significantly dominates right tail — high tail risk.
    "tail_asymmetry_score": -0.05,
    # Task 2 (Round 76, Beta): factor orthogonality score floor.
    # orthogonality_score < 0.5 means mean factor correlation > 0.5 — highly redundant factor set.
    "orthogonality_score": 0.5,
    # Task 1 (Round 77, Alpha): adaptive threshold lift floor.
    # threshold_lift < 0.0 means higher-score subset performs worse than the full pool.
    "threshold_lift": 0.0,
    # Task 3 (Round 77, Gamma): skew quality cross-window trend slope floor.
    # skew_trend_slope < -0.02 means gain/loss ratio declining meaningfully across windows.
    "skew_trend_slope": -0.02,
    # Task 1 (Round 78, Alpha): hotstock win-rate edge floor.
    # hotstock_edge < 0.0 means high-score stocks do not outperform in win rate.
    "hotstock_edge": 0.0,
    # Task 2 (Round 78, Beta): factor robustness ratio floor.
    # robustness_ratio < 0.4 means fewer than 3 of 7 factors are sign-consistent across splits.
    "robustness_ratio": 0.4,
    # Task 3 (Round 78, Gamma): threshold lift cross-window trend slope floor.
    # threshold_lift_trend_slope < -0.01 means threshold lift is deteriorating across windows.
    "threshold_lift_trend_slope": -0.01,
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
    # Task 3 (Round 44, Gamma): cross-window win-rate coefficient of variation cap.
    # win_rate_cv = std(win_rate_across_windows) / mean(win_rate_across_windows).
    # A CV above 0.30 means the strategy's per-window win rate varies by more than 30 % relative
    # to its mean — a sign of high regime sensitivity; the strategy is not reliably repeatable.
    # Profiles with win_rate_cv > 0.30 carry high out-of-sample win-rate instability risk.
    "win_rate_cv": 0.30,
    # Task 3 (Round 46, Gamma): cross-window gate consistency CV cap.
    # gate_above_threshold_cv = std / mean of gate ≥ 60 fraction across replay windows.
    # A CV above 0.25 means the gate-pass fraction varies by more than 25 % relative to its mean
    # across windows — indicating the strategy's gate selectivity is highly regime-sensitive.
    # Profiles with gate_above_threshold_cv > 0.25 carry high gate instability risk.
    "gate_above_threshold_cv": 0.25,
    # Task 1 (Round 50, Alpha): average inter-factor Spearman correlation cap.
    # avg_inter_factor_correlation = mean |r| across all valid 7-factor pairs per window.
    # A value above 0.50 means the core factor set is on average highly correlated,
    # offering little independent signal diversity.  High redundancy inflates apparent
    # robustness because correlated signals agree by construction rather than real edge.
    "avg_inter_factor_correlation": 0.50,
    # Task 2 (Round 51, Beta): outlier dependency ratio cap.
    # outlier_dependency_ratio = (full_win_rate - win_rate_ex_top10) / full_win_rate.
    # A value above 0.30 means the strategy's win rate shrinks by more than 30 % once
    # the top-10% return outliers are removed — indicating the edge is highly dependent
    # on rare "black swan" surges that are unlikely to repeat in live trading.
    "outlier_dependency_ratio": 0.30,
    # Task 3 (Round 55, Gamma): cross-window max-drawdown OLS trend slope cap.
    # drawdown_trend_slope > 0.005 means drawdown is growing faster than 0.5 %/window — deteriorating risk.
    # Profiles above this cap carry unacceptable risk escalation and should be penalised.
    "drawdown_trend_slope": 0.005,
    # Task 1 (Round 61, Alpha): concentration risk cap.
    # concentration_risk > 0.7 means P&L is driven by ≤5 extreme trades — overfit risk.
    "concentration_risk": 0.7,
    # Task 1 (Round 62, Alpha): low-liquidity fraction cap.
    # low_liquidity_pct > 0.4 means >40% of candidates have float turnover < 2% — severe execution risk.
    "low_liquidity_pct": 0.4,
    # Task 2 (Round 64, Beta): factor validity IC stability cap.
    # ic_stability > 0.2 means IC variation across time segments is too large to trust factor signals.
    "ic_stability": 0.2,
    # Task 3 (Round 65, Gamma): IC stability trend slope cap.
    # ic_stability_trend_slope > 0.01 means factor validity is becoming less stable across windows — worsening.
    "ic_stability_trend_slope": 0.01,
    # Task 1 (Round 68, Alpha): tail risk score cap.
    # tail_risk_score > 3.0 means extreme losses are ≥3× more frequent than extreme gains — high downside risk.
    "tail_risk_score": 3.0,
    # Task 2 (Round 68, Beta): position concentration HHI cap.
    # sector_hhi > 0.5 means portfolio is highly concentrated in one sector — concentration risk too high.
    "sector_hhi": 0.5,
    # Task 3 (Round 69, Gamma): concentration HHI trend slope cap.
    # concentration_hhi_slope > 0.02 means HHI rising faster than 0.02/window — concentration worsening too fast.
    "concentration_hhi_slope": 0.02,
    # Task 2 (Round 75, Beta): maximum factor collinearity cap.
    # max_collinearity > 0.85 means at least one factor pair is highly collinear — effective factor count severely reduced.
    "max_collinearity": 0.85,
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
