"""Optimize short-trade target profile parameters via grid search.

Uses replay-based multi-window analysis to evaluate parameter combinations.
Supports checkpointing for long-running searches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from scripts.analyze_btst_weekly_validation import analyze_btst_weekly_validation
from scripts.btst_analysis_utils import (
    BTST_FACTOR_NAMES,
    compute_factor_ic_stability,
    compute_factor_ic_temporal_trend,
    compute_parameter_stability_metrics,
    compute_profile_health_score,
    compute_score_stability_across_windows,
    compute_selection_churn_metrics,
    compute_surface_metric_correlations,
    compute_verdict_calibration,
)
from scripts.btst_optimized_profile_manifest_helpers import (
    publish_btst_optimized_profile_manifest,
)
from scripts.btst_strict_objective_gate import (
    build_strict_btst_objective_gate,
    parse_objective_monitor_markdown,
)
from src.backtesting.evaluation_bundle import (
    BTST_EXECUTION_GUARDRAILS,
    BTST_QUALITY_FLOORS,
)
from src.backtesting.param_search import (
    format_search_report,
    GuardrailSpec,
    ParamSpace,
    run_param_search,
    save_search_payload,
    save_search_report,
    SearchObjective,
    SearchReport,
)
from src.targets import get_short_trade_target_profile
from src.utils.logging import get_logger

logger = get_logger(__name__)

REPORTS_DIR = Path("data/reports")
PARTIAL_HORIZON_WEIGHT_PENALTY = 0.85
PARTIAL_T3_HORIZON_WEIGHT_PENALTY = 0.92
# Task S (Round 9): Temporal recency decay — windows older than RECENCY_HALF_LIFE_DAYS receive
# exponentially decayed sample_weight so that recent data has proportionally more influence.
RECENCY_HALF_LIFE_DAYS: int = 90
RECENCY_DECAY_MIN_FACTOR: float = 0.20  # floor: oldest windows keep at least 20 % weight
# Task 4 (Round 10): candidate half-life values for grid search — optimizer selects the
# best value automatically; pre-computed maps avoid re-scanning paths on every trial.
RECENCY_HALF_LIFE_CANDIDATES: tuple[int, ...] = (60, 90, 120, 180)
# Task 4 (Round 10): params that are consumed by the optimizer framework itself and must NOT
# be forwarded to build_short_trade_target_profile as profile overrides.
_OPTIMIZER_ONLY_PARAMS: frozenset[str] = frozenset({"recency_half_life_days"})
LIQUIDITY_LOW_REGIME_FLOOR: float = 40.0    # below this → severe down-weight
LIQUIDITY_SOFT_REGIME_FLOOR: float = 50.0   # below this → mild down-weight
LIQUIDITY_LOW_REGIME_WEIGHT_PENALTY: float = 0.80
LIQUIDITY_SOFT_REGIME_WEIGHT_PENALTY: float = 0.90
# Task 1 (Round 11): factor IC guardrail — factors with avg Spearman IC below this threshold
# are considered uninformative.  ic_positive_factor_fraction < IC_FRACTION_FLOOR is used as
# an optional guardrail so param combos that deactivate predictive factors are penalised.
IC_SIGNAL_MIN: float = 0.02          # minimum IC for a factor to be considered active
IC_FRACTION_FLOOR: float = 0.50      # fraction of factors that must have IC >= IC_SIGNAL_MIN
IC_QUALITY_SAMPLE_WEIGHT_PENALTY: float = 0.90  # multiply sample_weight when IC quality is poor
DEFAULT_BTST_REPLAY_GUARDRAILS: dict[str, GuardrailSpec] = {
    # Relaxed floor relative to BTST_QUALITY_FLOORS (0.54) so the optimizer can search across
    # market regimes where the natural day-win-rate sits around 0.53.  Production promotion
    # still uses the stricter evaluation_bundle floor for final sign-off.
    "next_close_positive_rate": 0.52,
    "next_high_hit_rate": BTST_QUALITY_FLOORS["next_high_hit_rate"],
    "downside_p10": BTST_QUALITY_FLOORS["downside_p10"],
    "window_coverage": BTST_QUALITY_FLOORS["window_coverage"],
    "projected_theme_exposure": {"max": 0.35, "skip_if_null": True},
    "incremental_theme_exposure": {"max": 0.12, "skip_if_null": True},
    "liquidity_capacity_raw_100": dict(BTST_EXECUTION_GUARDRAILS["liquidity_capacity_raw_100"]),
    "crowding_risk_raw_100": dict(BTST_EXECUTION_GUARDRAILS["crowding_risk_raw_100"]),
    "gap_risk_raw_100": dict(BTST_EXECUTION_GUARDRAILS["gap_risk_raw_100"]),
}
DEFAULT_BTST_RUNNER_REPLAY_GUARDRAILS: dict[str, GuardrailSpec] = {
    "max_future_high_return_2_5d_hit_rate_at_20pct": {"min": 0.10},
    "next_close_positive_rate": BTST_QUALITY_FLOORS["next_close_positive_rate"],
    "downside_p10": BTST_QUALITY_FLOORS["downside_p10"],
    "window_coverage": BTST_QUALITY_FLOORS["window_coverage"],
    "gap_risk_raw_100": dict(BTST_EXECUTION_GUARDRAILS["gap_risk_raw_100"]),
    "runner_escape_rate": {"min": 0.03, "max": 0.60},
    "avg_composite_score_escaped": {"min": BTST_QUALITY_FLOORS["avg_composite_score_escaped"]},
    "t_plus_2_close_payoff_ratio": {"min": BTST_QUALITY_FLOORS["t_plus_2_close_payoff_ratio"]},
    "t_plus_3_close_payoff_ratio": {"min": BTST_QUALITY_FLOORS["t_plus_3_close_payoff_ratio"]},
    # Task 1 (Round 11): IC quality guard — at least half the tracked factors must show positive IC.
    # Optional: surfaces produced before Round 10 will not carry IC data, so this guardrail is
    # only enforced when ic_positive_factor_fraction is present in the evaluated metrics.
    "ic_positive_factor_fraction": {"min": IC_FRACTION_FLOOR},
}
MOMENTUM_OPTIMIZED_STAGE_PRESET_GRIDS: dict[str, dict[str, list[Any]]] = {
    "coarse": {
        "select_threshold": [0.46, 0.50, 0.54],
        "near_miss_threshold": [0.30, 0.34, 0.38],
        "breakout_freshness_weight": [0.12, 0.16],
        "trend_acceleration_weight": [0.18, 0.22],
        "volume_expansion_quality_weight": [0.16, 0.20],
        "close_strength_weight": [0.12, 0.16],
        "catalyst_freshness_weight": [0.10, 0.14],
        "momentum_strength_weight": [0.00, 0.06],
        "short_term_reversal_weight": [0.00, 0.04],
        # Task 4 (Round 10): coarse sweep includes the two extreme half-life candidates.
        "recency_half_life_days": [60, 180],
    },
    "focused": {
        "select_threshold": [0.46, 0.50, 0.54],
        "near_miss_threshold": [0.30, 0.34, 0.38],
        "breakout_freshness_weight": [0.12, 0.16],
        "trend_acceleration_weight": [0.18, 0.22],
        "volume_expansion_quality_weight": [0.16, 0.20],
        "close_strength_weight": [0.12, 0.16],
        "catalyst_freshness_weight": [0.10, 0.14],
        "momentum_strength_weight": [0.00, 0.06],
        "short_term_reversal_weight": [0.00, 0.04],
        # Task 4 (Round 10): focused sweep uses all four candidates.
        "recency_half_life_days": list(RECENCY_HALF_LIFE_CANDIDATES),
    },
}
COMPARISON_METRICS: tuple[str, ...] = (
    "next_close_positive_rate",
    "next_high_hit_rate",
    "next_close_expectancy",
    "downside_p10",
    "window_coverage",
    "liquidity_capacity_raw_100",
    "crowding_risk_raw_100",
    "gap_risk_raw_100",
    "projected_theme_exposure",
    "incremental_theme_exposure",
    "max_future_high_return_2_5d_hit_rate_at_20pct",
    "time_to_hit_20pct_median",
    "runner_capture_count",
    "runner_escape_rate",
    "avg_composite_score_escaped",
    "t_plus_2_close_positive_rate",
    "t_plus_2_close_payoff_ratio",
    "t_plus_3_close_positive_rate",
    "t_plus_3_close_expectancy",
    "t_plus_3_close_payoff_ratio",
    # Task 1 (Round 11): IC quality fraction
    "ic_positive_factor_fraction",
    "candidate_pool_avg_composite_score",
    # Task 1 (Round 12): T+1 intraday drawdown tail-risk metric
    "t_plus_1_intraday_drawdown_p10",
    # Task 4 (Round 15): stop-loss trigger rates — fraction of T+1 bars hitting each stop level.
    "stop_loss_trigger_rate_2pct",
    "stop_loss_trigger_rate_3pct",
    "stop_loss_trigger_rate_5pct",
    # Task 5 (Round 15): cross-day Spearman autocorrelation T+1↔T+2 and T+2↔T+3.
    "cross_day_autocorr_t1_vs_t2",
    "cross_day_autocorr_t2_vs_t3",
    # Task 2 (Round 15): opening-gap continuation rate.
    "gap_continuation_rate",
    # Task 2 (Round 16): volume-price divergence rate — fraction of false-breakout bars.
    "volume_price_divergence_rate",
    # Task 3 (Round 16): T0 predicted range p75 and high-volatility warning rate.
    "predicted_range_pct_p75",
    "high_volatility_warning_rate",
    # Task 1 (Round 20, Beta): realized payoff ratio — explicit win/loss asymmetry KPI.
    "realized_payoff_ratio",
    # Task 2 (Round 20, Alpha): score-conditioned selection quality metrics.
    "high_confidence_selection_rate",
    "score_weighted_win_rate",
    "score_win_rate_lift",
    "high_confidence_win_rate",
    # Task 3 (Round 20, Gamma): consecutive limit-up risk statistics.
    "consecutive_limit_up_rate",
    "limit_up_win_rate",
    "non_limit_up_win_rate",
    # Task 3 (Round 21, Beta): optimal execution timing signal — open vs wait strength.
    "open_entry_signal_strength",
    "execution_timing_confidence",
    # Task 2 (Round 22, Alpha): multi-day optimal hold period metrics.
    "t1_vs_t2_sharpe_diff",
    "hold_period_confidence",
    # Task 3 (Round 22, Beta): score percentile position-tier metrics.
    "tier_win_rate_spread",
    "tier_monotone_win_rate",
    # Task 2 (Round 23, Alpha): Kelly fraction position sizing — half-Kelly sizing recommendation.
    "kelly_fraction_half",
    "kelly_positive",
    # Task 3 (Round 23, Beta): regime win-rate consistency — stability across bull/bear/sideways.
    "regime_consistency_score",
    "regime_robustness_flag",
    # Task 1 (Round 24): IC temporal trend — decaying factor count across replay windows.
    "decaying_factor_count",
    # Task 2 (Round 24): drawdown-adjusted Kelly fraction and adjustment factor.
    "kelly_fraction_drawdown_adjusted",
    "drawdown_adjustment_factor",
    # Task 3 (Round 24): walk-forward verdict calibration score and monotone flag.
    "verdict_calibration_score",
    "verdict_monotone",
    # Task 1 (Round 25, Gamma): comprehensive profile health score.
    "profile_health_score",
    # Task 2 (Round 25, Beta): selection churn / window stability metrics.
    "win_rate_window_volatility",
    "win_rate_window_trend",
    # Task 2 (Round 26, Gamma): benchmark-adjusted Alpha vs HS300.
    "alpha_avg_return",
    "information_ratio",
    # Task 3 (Round 26, Beta): dynamic stop-loss suggestion.
    "suggested_stop_loss_pct",
    # Task 1 (Round 27, Alpha): return distribution skewness & win/loss std ratio.
    "next_close_return_skewness",
    "win_loss_std_ratio",
    # Task 2 (Round 27, Gamma): composite score discrimination power index.
    "score_discrimination_index",
    # Task 3 (Round 27, Beta): liquidity-aware position guidance.
    "recommended_max_positions",
    # Task 1 (Round 28, Alpha): factor cross-correlation — redundant-pair count.
    "high_correlation_pair_count",
    # Task 2 (Round 28, Gamma): regime-domain alpha consistency.
    "alpha_consistency_score",
    "all_regimes_positive_alpha",
    # Task 3 (Round 28, Beta): post-loss recovery T+2 positive rate.
    "post_loss_t2_positive_rate",
    # Task 1 (Round 29, Alpha): PCA factor diversity score — closer to 1 = more orthogonal factors.
    "pca_diversity_score",
    # Task 2 (Round 29, Gamma): IS/OOS overfit score — lower is better (cap ≤ 0.30).
    "overfit_score",
    # Task 3 (Round 29, Beta): weekday win-rate spread — captures A-share calendar effect magnitude.
    "weekday_win_rate_spread",
    # Task 1 (Round 30, Gamma): parameter drift score — cross-window metric stability (lower = more stable).
    "param_drift_score",
    # Task 2 (Round 30, Alpha): monthly win-rate spread — captures A-share seasonal / monthly calendar effect.
    "monthly_win_rate_spread",
    # Task 3 (Round 30, Beta): nonlinear factor count — number of factors with threshold/U-shape effects (lower = better).
    "nonlinear_factor_count",
    # Task 1 (Round 31, Alpha): return time-series autocorrelation lag-1 — regime persistence signal.
    "autocorr_lag1",
    # Task 2 (Round 31, Gamma): composite score CV across windows — scoring system stability (lower = better).
    "score_cv_across_windows",
    # Task 1 (Round 32, Gamma): tail-risk score separation — score's ability to filter deep losses.
    "score_tail_separation",
    # Task 1 (Round 32, Gamma): tail-risk asymmetry — |CVaR_5%| / upside_5% (lower = better).
    "tail_risk_asymmetry",
    # Task 1 (Round 32, Gamma): high-score group CVaR at worst 5% (lower magnitude = better).
    "high_score_cvar_5pct",
    # Task 2 (Round 32, Alpha): extreme volume win-rate premium —放量 effect on win rate.
    "extreme_volume_win_rate_premium",
    # Task 2 (Round 32, Alpha): net inflow win-rate premium — inflow effect on win rate.
    "inflow_win_rate_premium",
    # Task 3 (Round 32, Beta): composite gate score — overall 0–100 tradability index.
    "composite_gate_score",
    # Task 1 (Round 33, Alpha): expected value per trade — E[R] = wr×avg_win + lr×avg_loss.
    "expected_value_per_trade",
    # Task 2 (Round 33, Gamma): momentum decay half-life — days until amplitude halves (lower = faster decay = BTST-friendly).
    "momentum_half_life_days",
    # Task 3 (Round 33, Beta): IC trend stability across windows — fraction of factors NOT in IC decline.
    "ic_trend_stability",
    # Task 3 (Round 33, Beta): IC trend deteriorating flag — True when >50% of factors have declining IC.
    "factor_ic_trend_deteriorating",
    # Task 1 (Round 34, Alpha): multi-factor conditional lift — win rate gain at 3+ high-score factors.
    "multi_factor_lift",
    # Task 2 (Round 34, Gamma): adaptive sizing score — composite 0–100 position-size index.
    "adaptive_sizing_score",
    # Task 3 (Round 34, Beta): signal churn rate — fraction of candidate pool replaced between windows.
    "signal_churn_rate",
    # Task 3 (Round 34, Beta): signal persistence — average Jaccard similarity of top-stock sets.
    "avg_signal_persistence",
    # Task 1 (Round 35, Alpha): Sortino risk-adjusted return ratio — annualised Sortino clamped [-5, 5].
    "sortino_ratio",
    # Task 2 (Round 35, Gamma): quality trend score — fraction of quality metrics with positive OLS slope.
    "quality_trend_score",
    # Task 3 (Round 35, Beta): candidate diversity score — 1 − HHI sector concentration index.
    "diversity_score",
    # Task 1 (Round 36, Alpha): right-tail dominance — (P95−P50)/|P5−P50|, clamped [0, 5].
    "right_tail_dominance",
    # Task 2 (Round 36, Beta): composite score Spearman IC — direct predictive validity metric.
    "composite_ic",
    # Task 3 (Round 36, Gamma): win-rate bootstrap CI width — lower = more reliable estimate.
    "win_rate_ci_width",
    # Task 1 (Round 37, Alpha): optimal holding days — argmax EV across T+1/T+2/T+3.
    "optimal_holding_days",
    # Task 2 (Round 37, Beta): loss trade signature strength — mean |factor divergence| win vs loss.
    "loss_signature_strength",
    # Task 3 (Round 37, Gamma): score Gini coefficient — concentration of composite score distribution.
    "score_gini",
    # Task 1 (Round 38, Alpha): market environment sensitivity — bull vs bear win-rate gap.
    "env_win_rate_gap",
    # Task 2 (Round 38, Beta): factor importance ranking — count of factors with positive Spearman IC.
    "positive_ic_factor_count",
    # Task 3 (Round 38, Gamma): score bucket win rates — top-quintile vs bottom-quintile premium.
    "top_quintile_premium",
    # Task 1 (Round 39, Alpha): recency vs history — win-rate gap (near period minus historical).
    "recency_win_rate_gap",
    # Task 2 (Round 39, Beta): optimal score threshold — win-rate lift above optimal threshold.
    "optimal_threshold_lift",
    # Task 3 (Round 39, Gamma): simulated equity curve — recovery factor and max drawdown.
    "recovery_factor",
    "max_drawdown_simulated",
    # Task 1 (Round 40, Alpha): factor synergy matrix — max pairwise co-activation win-rate lift.
    "max_synergy_lift",
    # Task 2 (Round 40, Beta): float turnover analysis — high vs low turnover win-rate lift.
    "high_vs_low_lift",
    # Task 3 (Round 40, Gamma): cross-window factor exposure drift — mean CV (lower = more stable).
    "factor_drift_score",
    # Task 1 (Round 41, Alpha): factor IC rank consistency across replay windows.
    "factor_rank_consistency_score",
    # Task 2 (Round 41, Beta): volume-price direction alignment rate.
    "vol_price_alignment_rate",
    # Task 3 (Round 41, Gamma): combined statistical significance score.
    "combined_significance_score",
    # Task 1 (Round 42, Alpha): composite score calibration slope.
    "calibration_slope",
    # Task 2 (Round 42, Beta): close-strength top-quartile win-rate premium.
    "cs_top_quartile_premium",
    # Task 3 (Round 42, Gamma): cross-window consensus pass rate.
    "consensus_windows_pct",
    # Task 1 (Round 43, Alpha): profit factor — gross profit / gross loss.
    "profit_factor",
    # Task 2 (Round 43, Beta): high-vs-low news sentiment win-rate lift.
    "high_vs_low_sentiment_lift",
    # Task 3 (Round 43, Gamma): score momentum trend — normalized OLS slope.
    "score_trend_normalized",
    # Task 1 (Round 44, Alpha): RS top-quartile win-rate premium over bottom quartile.
    "rs_top_quartile_premium",
    # Task 2 (Round 44, Beta): breakout-quality high-vs-low win-rate lift.
    "bq_high_vs_low_lift",
    # Task 3 (Round 44, Gamma): cross-window win-rate coefficient of variation.
    "win_rate_cv",
    # Task 1 (Round 45, Alpha): market-cap high-vs-low win-rate lift (diagnostic).
    "mc_high_vs_low_lift",
    # Task 2 (Round 45, Beta): catalyst-theme top-quartile premium over bottom quartile.
    "catalyst_top_quartile_premium",
    # Task 3 (Round 45, Gamma): top-candidate cross-window win-rate consistency rate.
    "top_candidate_consistency_rate",
    # Task 1 (Round 46, Alpha): volume-price divergence low-vs-high win-rate lift.
    "vpd_low_vs_high_lift",
    # Task 2 (Round 46, Beta): score distribution skewness (right-skew is better).
    "score_skewness",
    # Task 2 (Round 46, Beta): fraction of scores > 0.
    "score_positive_pct",
    # Task 3 (Round 46, Gamma): cross-window gate consistency coefficient of variation.
    "gate_above_threshold_cv",
    # Task 1 (Round 47, Alpha): momentum slope high-vs-low win-rate lift.
    "ms_high_vs_low_lift",
    # Task 2 (Round 47, Beta): net inflow ratio high-vs-low win-rate lift.
    "inflow_high_vs_low_lift",
    # Task 3 (Round 47, Gamma): cross-window factor IC positive consistency rate.
    "positive_ic_consistency_rate",
    # Task 1 (Round 48, Alpha): VEQ high-vs-low win-rate lift.
    "veq_high_vs_low_lift",
    # Task 2 (Round 48, Beta): sector resonance high-vs-low win-rate lift.
    "sr_high_vs_low_lift",
    # Task 3 (Round 48, Gamma): cross-window expected-value trend slope.
    "ev_trend_slope",
    # Task 1 (Round 49, Alpha): multi-factor consensus win-rate lift.
    "consensus_lift",
    # Task 2 (Round 49, Beta): score decile top-vs-bottom premium.
    "top_decile_premium",
    # Task 3 (Round 49, Gamma): cross-window Sortino trend slope.
    "sortino_trend_slope",
    # Task 1 (Round 50, Alpha): factor inter-correlation (redundancy) average.
    "avg_inter_factor_correlation",
    # Task 2 (Round 50, Beta): T+2 relative to T+1 win-rate premium.
    "t2_vs_t1_premium",
    # Task 3 (Round 50, Gamma): cross-window Sharpe trend slope.
    "sharpe_trend_slope",
    # Task 1 (Round 51, Alpha): win/loss magnitude ratio — average win / average loss.
    "win_loss_magnitude_ratio",
    # Task 1 (Round 51, Alpha): Kelly criterion fraction — positive edge sizing.
    "kelly_fraction",
    # Task 2 (Round 51, Beta): outlier dependency ratio — sensitivity to top-10% returns.
    "outlier_dependency_ratio",
    # Task 3 (Round 51, Gamma): cross-window profit-factor OLS trend slope.
    "pf_trend_slope",
    # Task 1 (Round 52, Alpha): annualised Information Ratio (IR = mean/std * sqrt(252)).
    "information_ratio",
    # Task 2 (Round 52, Beta): score concentration index (high_pct − low_pct).
    "score_concentration_index",
    # Task 3 (Round 52, Gamma): cross-window Kelly fraction OLS trend slope.
    "kelly_trend_slope",
    # Task 1 (Round 53, Alpha): conditional factor-synergy win-rate lift (high − low signal tier).
    "conditional_lift",
    # Task 3 (Round 53, Gamma): cross-window Information Ratio OLS trend slope.
    "ir_trend_slope",
    # Task 1 (Round 54, Alpha): tail-risk asymmetry (right_tail_95 − abs(CVaR5%)).
    "tail_asymmetry",
    # Task 2 (Round 54, Beta): maximum drawdown of cumulative NAV (positive value).
    "drawdown_max_drawdown",
    # Task 3 (Round 54, Gamma): cross-window conditional factor synergy OLS trend slope.
    "conditional_lift_trend_slope",
    # Task 1 (Round 55, Alpha): multi-factor mean IC — signed average Spearman IC across 7 core factors.
    "decay_mean_ic",
    # Task 2 (Round 55, Beta): intraday session win-rate spread — max − min across early/mid/late.
    "time_seg_session_win_rate_spread",
    # Task 3 (Round 55, Gamma): cross-window max-drawdown OLS trend slope.
    "drawdown_trend_slope",
    # Task 1 (Round 56, Alpha): sector diversification score — 1 − HHI; higher = more diverse pool.
    "diversification_score",
    # Task 2 (Round 56, Beta): score rank IC — Spearman IC between composite score and T+1 return.
    "rank_ic",
    # Task 3 (Round 56, Gamma): cross-window mean-IC OLS trend slope.
    "ic_trend_slope",
    # Task 1 (Round 57, Alpha): market regime adaptability score — min(bull_win_rate, bear_win_rate).
    "regime_adaptability",
    # Task 2 (Round 57, Beta): turnover efficiency — high_turnover_win_rate − low_turnover_win_rate.
    "turnover_efficiency",
    # Task 3 (Round 57, Gamma): cross-window rank-IC OLS trend slope.
    "rank_ic_trend_slope",
    # Task 1 (Round 58, Alpha): optimal entry threshold win rate — best per-percentile win rate.
    "optimal_win_rate",
    # Task 2 (Round 58, Beta): total explained variance — sum of factor r² across 7 core factors.
    "total_explained_variance",
    # Task 3 (Round 58, Gamma): cross-window regime adaptability OLS trend slope.
    "regime_trend_slope",
    # Task 1 (Round 59, Alpha): return distribution skewness — average next_day_return skewness across windows.
    "skewness",
    # Task 2 (Round 59, Beta): composite quality score — weighted average across active quality dimensions.
    "composite_quality_score",
    # Task 3 (Round 59, Gamma): cross-window optimal-threshold win-rate OLS trend slope.
    "threshold_win_rate_trend_slope",
    # Task 1 (Round 60, Alpha): multi-signal consistency win-rate lift.
    "signal_consistency_lift",
    # Task 2 (Round 60, Beta): optimal holding period win rate.
    "t1_win_rate",
    # Task 3 (Round 60, Gamma): cross-window composite quality score trend slope.
    "quality_score_trend_slope",
    # Task 1 (Round 61, Alpha): concentration risk — fraction of P&L driven by top-5 wins or bottom-5 losses.
    "concentration_risk",
    # Task 2 (Round 61, Beta): extreme market resilience score — win rate under extreme down conditions.
    "resilience_score",
    # Task 3 (Round 61, Gamma): cross-window signal consistency OLS trend slope.
    "consistency_trend_slope",
    # Task 1 (Round 62, Alpha): low-liquidity candidate fraction — fraction of rows with turnover < 2%.
    "low_liquidity_pct",
    # Task 2 (Round 62, Beta): cost-adjusted profit factor after 0.3% bilateral transaction cost.
    "cost_adjusted_profit_factor",
    # Task 3 (Round 62, Gamma): cross-window extreme-market resilience OLS trend slope.
    "resilience_trend_slope",
    # Task 1 (Round 63, Alpha): best stop-loss/take-profit profit factor.
    "best_profit_factor",
    # Task 2 (Round 63, Beta): best factor-combination win rate.
    "best_combo_win_rate",
    # Task 3 (Round 63, Gamma): cross-window cost-adjusted PF OLS trend slope.
    "cost_pf_trend_slope",
    # Task 3 (Round 64, Gamma): cross-window best combo win rate OLS trend slope.
    "combo_win_rate_trend_slope",
    # Task 1 (Round 64, Alpha): adaptive weight effective factor count.
    "adaptive_weight_effective_factor_count",
    # Task 2 (Round 64, Beta): factor validity window IC stability.
    "ic_stability",
    # Task 1 (Round 65, Alpha): total factor return attribution explanatory power.
    "total_attribution",
    # Task 2 (Round 65, Beta): multi-timeframe consistency score.
    "timeframe_consistency",
    # Task 3 (Round 65, Gamma): cross-window IC stability OLS trend slope.
    "ic_stability_trend_slope",
    # Task 1 (Round 66, Alpha): volatility regime win-rate edge — low-vol win rate minus high-vol win rate.
    "vol_regime_edge",
    # Task 2 (Round 66, Beta): mean nonlinear factor interaction Pearson IC — mean |IC| across pairwise factor products.
    "interact_mean_interaction_effect",
    # Task 3 (Round 66, Gamma): cross-window total attribution OLS trend slope.
    "attribution_trend_slope",
    # Task 1 (Round 67, Alpha): score dispersion win-rate spread — high vs low score group win-rate gap.
    "score_win_rate_spread",
    # Task 2 (Round 67, Beta): fund flow / breakout synergy win rate — high-flow + high-breakout quadrant.
    "flow_breakout_synergy",
    # Task 3 (Round 67, Gamma): cross-window nonlinear interaction OLS trend slope.
    "interaction_trend_slope",
    # Task 1 (Round 68, Alpha): tail event filter effect — normal_win_rate minus full_win_rate.
    "tail_filter_effect",
    # Task 2 (Round 68, Beta): position concentration HHI — Herfindahl-Hirschman Index of sector distribution.
    "sector_hhi",
    # Task 3 (Round 68, Gamma): cross-window score dispersion OLS trend slope.
    "dispersion_trend_slope",
    # Task 1 (Round 69, Alpha): RS ranking strength spread — top-third minus bottom-third win rate.
    "rs_rank_spread",
    # Task 2 (Round 69, Beta): turnover behavior filter effect — normal-turnover minus full win rate.
    "turnover_filter_effect",
    # Task 3 (Round 69, Gamma): cross-window concentration HHI OLS trend slope.
    "concentration_hhi_slope",
    # Task 1 (Round 70, Alpha): price position win-rate spread — high CS minus low CS win rate.
    "cs_win_rate_spread",
    # Task 2 (Round 70, Beta): win/loss streak ratio — max_win_streak / (max_loss_streak + 1).
    "streak_ratio",
    # Task 3 (Round 70, Gamma): cross-window RS rank spread OLS trend slope.
    "rs_rank_trend_slope",
    # Task 1 (Round 71, Alpha): sector momentum ranking win-rate spread — top-momentum minus bottom-momentum win rate.
    "momentum_win_spread",
    # Task 2 (Round 71, Beta): volume structure win-rate spread — high volume expansion minus low win rate.
    "vol_structure_spread",
    # Task 3 (Round 71, Gamma): cross-window price position cs_win_rate_spread OLS trend slope.
    "price_pos_trend_slope",
    # Task 1 (Round 72, Alpha): multi-factor composite Z-score win-rate spread — top-Z minus bottom-Z win rate.
    "zscore_win_spread",
    # Task 2 (Round 72, Beta): return persistence stability score — rolling + block consistency combined.
    "persistence_score",
    # Task 3 (Round 72, Gamma): cross-window momentum rank win-spread OLS trend slope.
    "momentum_rank_trend_slope",
    # Task 1 (Round 73, Alpha): market breadth win rate — advance_count / total in candidate pool.
    "breadth_win_rate",
    # Task 2 (Round 73, Beta): factor IC consistency ratio — fraction of 7 core factors with positive half-IC.
    "ic_consistency_ratio",
    # Task 3 (Round 73, Gamma): cross-window Z-score win-spread OLS trend slope.
    "zscore_trend_slope",
    # Task 1 (Round 74, Alpha): signal strength stratification spread (Q5−Q1 win-rate).
    "stratification_spread",
    # Task 2 (Round 74, Beta): conditional momentum synergy edge (dual-strong vs dual-weak).
    "conditional_momentum_edge",
    # Task 3 (Round 74, Gamma): market breadth win-rate cross-window OLS trend slope.
    "breadth_trend_slope",
    # Task 1 (Round 75, Alpha): simplified per-window Sharpe ratio (return_mean / return_std).
    "sharpe_ratio",
    # Task 2 (Round 75, Beta): maximum absolute pairwise factor correlation (lower = more independent factors).
    "max_collinearity",
    # Task 3 (Round 75, Gamma): cross-window stratification spread OLS trend slope.
    "stratification_trend_slope",
    # Task 1 (Round 76, Alpha): gain/loss ratio of skew-quality analysis.
    "gain_loss_ratio",
    # Task 1 (Round 76, Alpha): tail asymmetry score (right_tail_pct − left_tail_pct).
    "tail_asymmetry_score",
    # Task 2 (Round 76, Beta): factor orthogonality score (1 − mean_abs_correlation).
    "orthogonality_score",
    # Task 1 (Round 77, Alpha): adaptive score threshold lift.
    "threshold_lift",
    # Task 2 (Round 77, Beta): sector win-rate dispersion across sectors.
    "sector_win_rate_dispersion",
    # Task 3 (Round 77, Gamma): cross-window skew quality OLS trend slope.
    "skew_trend_slope",
    # Task 3 (Round 78, Gamma): cross-window adaptive threshold lift OLS trend slope.
    "threshold_lift_trend_slope",
    # Task 1 (Round 78, Alpha): hotstock win-rate edge vs non-hotstock.
    "hotstock_edge",
    # Task 2 (Round 78, Beta): factor robustness ratio (jackknife sign-consistent fraction).
    "robustness_ratio",
    # Task 1 (Round 79, Alpha): score quintile monotonicity score and top-bottom spread.
    "sq_consist_quintile_monotonicity_score",
    "sq_consist_quintile_top_bottom_spread",
    # Task 2 (Round 79, Beta): high-quality entry win rate and edge.
    "entry_qual_high_quality_entry_win_rate",
    "entry_qual_quality_entry_edge",
    # Task 3 (Round 79, Gamma): cross-window factor robustness OLS trend slope.
    "robustness_trend_slope",
    # Task 1 (Round 80, Alpha): return quantile lift metrics.
    "ret_qlift_median_return_lift",
    "ret_qlift_top_median_return",
    # Task 2 (Round 80, Beta): near-high stock analysis metrics.
    "nh_near_high_win_rate",
    "nh_near_high_edge",
    # Task 3 (Round 80, Gamma): cross-window entry quality trend slope.
    "entry_quality_trend_slope",
    # Task 1 (Round 81, Alpha): expected value analysis metrics.
    "ev_top_ev",
    "ev_ev_spread",
    # Task 2 (Round 81, Beta): high inflow premium metrics.
    "hi_inflow_high_inflow_win_rate",
    "hi_inflow_high_inflow_edge",
    # Task 3 (Round 81, Gamma): cross-window near-high stock trend slope.
    "near_high_trend_slope",
    # Task 1 (Round 82, Alpha): score prediction accuracy metrics.
    "clf_high_score_precision",
    "clf_f1_score",
    # Task 2 (Round 82, Beta): volume-price divergence metrics.
    "vpd_full_confirm_win_rate",
    "vpd_divergence_penalty",
    # Task 3 (Round 82, Gamma): cross-window EV spread trend slope.
    "ev_spread_trend_slope",
    # Task 1 (Round 83, Alpha): Kelly criterion analysis metrics.
    "kelly_top_kelly",
    "kelly_kelly_spread",
    # Task 2 (Round 83, Beta): return percentile profile metrics.
    "rpp_top_return_p75",
    "rpp_upside_asymmetry",
    # Task 3 (Round 83, Gamma): cross-window precision trend slope.
    "precision_trend_slope",
    # Task 1 (Round 84, Alpha): momentum reversal analysis metrics.
    "mom_rev_extreme_momentum_win_rate",
    "mom_rev_momentum_breadth_effect",
    # Task 2 (Round 84, Beta): sector tailwind protection metrics.
    "tailwind_protected_win_rate",
    "tailwind_gap_protection_effect",
    # Task 3 (Round 84, Gamma): cross-window upside asymmetry trend slope.
    "upside_asymmetry_trend_slope",
    # Task 1 (Round 85, Alpha): batch consistency analysis metrics.
    "batch_batch_consistency_score",
    "batch_batch3_win_rate",
    # Task 2 (Round 85, Beta): liquidity weighted return analysis metrics.
    "liq_lw_win_rate",
    "liq_liquidity_bias",
    # Task 3 (Round 85, Gamma): cross-window momentum reversal trend slope.
    "momentum_reversal_trend_slope",
    # Task 1 (Round 86, Alpha): factor IC consistency ratio across 7 core factors.
    "frc_factor_ic_consistency_ratio",
    # Task 2 (Round 86, Beta): breakout quality P75 premium edge.
    "bq_breakout_premium_edge",
    # Task 3 (Round 86, Gamma): cross-window batch consistency OLS trend slope.
    "batch_consistency_trend_slope",
    # Task 1 (Round 87, Alpha): market regime adaptive win rate — regime spread.
    "regime_regime_spread",
    # Task 2 (Round 87, Beta): consecutive signal quality — signal persistence edge.
    "sig_signal_persistence_edge",
    # Task 3 (Round 87, Gamma): cross-window regime spread OLS trend slope.
    "regime_spread_trend_slope",
    # Task 1 (Round 88, Alpha): volume-price divergence score — volume premium edge.
    "vp_volume_premium_edge",
    # Task 2 (Round 88, Beta): entry timing quality — inflow timing edge.
    "et_inflow_timing_edge",
    # Task 3 (Round 88, Gamma): cross-window signal quality OLS trend slope.
    "signal_quality_trend_slope",
    # Task 1 (Round 89, Alpha): open-gap intraday persistence — gap win-rate premium.
    "ogp_gap_win_rate_premium",
    # Task 2 (Round 89, Beta): tail flow quality score — composite win-rate premium.
    "tf_composite_win_rate_premium",
    # Task 3 (Round 89, Gamma): cross-window momentum IC consistency score.
    "mc_ic_consistency_score",
)
COMPARISON_METRIC_LABELS: dict[str, str] = {
    "next_close_positive_rate": "Close+",
    "next_high_hit_rate": "High-hit",
    "next_close_expectancy": "Expectancy",
    "downside_p10": "Downside P10",
    "window_coverage": "Coverage",
    "liquidity_capacity_raw_100": "Liquidity",
    "crowding_risk_raw_100": "Crowding",
    "gap_risk_raw_100": "Gap Risk",
    "projected_theme_exposure": "Projected Exp",
    "incremental_theme_exposure": "Incremental Exp",
    "max_future_high_return_2_5d_hit_rate_at_20pct": "Runner 20% Hit",
    "time_to_hit_20pct_median": "Time-to-20% Med",
    "runner_capture_count": "Runner Count",
    "runner_escape_rate": "Runner Escape %",
    "avg_composite_score_escaped": "Avg Escaped Score",
    "t_plus_2_close_positive_rate": "T+2 Close+",
    "t_plus_2_close_payoff_ratio": "T+2 Payoff",
    "t_plus_3_close_positive_rate": "T+3 Close+",
    "t_plus_3_close_expectancy": "T+3 Expectancy",
    "t_plus_3_close_payoff_ratio": "T+3 Payoff",
    # Task 1 (Round 11)
    "ic_positive_factor_fraction": "IC Quality Frac",
    "candidate_pool_avg_composite_score": "Pool Avg Score",
    # Task 1 (Round 12)
    "t_plus_1_intraday_drawdown_p10": "Intraday DD P10",
    # Task 4 (Round 15): stop-loss trigger rates
    "stop_loss_trigger_rate_2pct": "SL-2% Rate",
    "stop_loss_trigger_rate_3pct": "SL-3% Rate",
    "stop_loss_trigger_rate_5pct": "SL-5% Rate",
    # Task 5 (Round 15): cross-day autocorrelation
    "cross_day_autocorr_t1_vs_t2": "T1→T2 Autocorr",
    "cross_day_autocorr_t2_vs_t3": "T2→T3 Autocorr",
    # Task 2 (Round 15): gap continuation rate
    "gap_continuation_rate": "Gap-Up Cont.",
    # Task 2 (Round 16): volume-price divergence rate
    "volume_price_divergence_rate": "Vol-Price Div%",
    # Task 3 (Round 16): predicted range percentile and warning rate
    "predicted_range_pct_p75": "Pred Range P75",
    "high_volatility_warning_rate": "HighVol Warn%",
    # Task 1 (Round 20, Beta): realized payoff ratio
    "realized_payoff_ratio": "Realized Payoff",
    # Task 2 (Round 20, Alpha): score-conditioned metrics
    "high_confidence_selection_rate": "HC Select%",
    "score_weighted_win_rate": "Score-Wtd WR",
    "score_win_rate_lift": "Score WR Lift",
    "high_confidence_win_rate": "HC WinRate",
    # Task 3 (Round 20, Gamma): limit-up risk statistics
    "consecutive_limit_up_rate": "Consec LU%",
    "limit_up_win_rate": "LU WinRate",
    "non_limit_up_win_rate": "Non-LU WR",
    # Task 3 (Round 21, Beta): optimal execution timing signal
    "open_entry_signal_strength": "Open Entry Sig",
    "execution_timing_confidence": "Timing Conf",
    # Task 2 (Round 22, Alpha): multi-day optimal hold period
    "t1_vs_t2_sharpe_diff": "T1-T2 Sharpe Δ",
    "hold_period_confidence": "Hold Conf",
    # Task 3 (Round 22, Beta): score position tiers
    "tier_win_rate_spread": "Tier WR Spread",
    "tier_monotone_win_rate": "Tier Mono WR",
    # Task 2 (Round 23, Alpha): Kelly fraction position sizing
    "kelly_fraction_half": "Half-Kelly Size",
    "kelly_positive": "Kelly Positive",
    # Task 3 (Round 23, Beta): regime win-rate consistency
    "regime_consistency_score": "Regime Consistency",
    "regime_robustness_flag": "Regime Robust",
    # Task 1 (Round 24): IC temporal trend
    "decaying_factor_count": "IC Decaying Factors",
    # Task 2 (Round 24): drawdown-adjusted Kelly fraction
    "kelly_fraction_drawdown_adjusted": "DD-Adj Kelly",
    "drawdown_adjustment_factor": "DD Adj Factor",
    # Task 3 (Round 24): walk-forward verdict calibration
    "verdict_calibration_score": "Verdict Calib",
    "verdict_monotone": "Verdict Monotone",
    # Task 1 (Round 25, Gamma): comprehensive profile health score
    "profile_health_score": "Health Score",
    # Task 2 (Round 25, Beta): selection churn / window stability
    "win_rate_window_volatility": "WR Window Vol",
    "win_rate_window_trend": "WR Window Trend",
    # Task 2 (Round 26, Gamma): benchmark-adjusted Alpha vs HS300
    "alpha_avg_return": "Alpha vs HS300",
    # Task 3 (Round 26, Beta): dynamic stop-loss suggestion
    "suggested_stop_loss_pct": "Suggested SL%",
    # Task 1 (Round 27, Alpha): return distribution shape
    "next_close_return_skewness": "Return Skewness",
    "win_loss_std_ratio": "Win/Loss Std Ratio",
    # Task 2 (Round 27, Gamma): score discrimination power
    "score_discrimination_index": "Score Discrim Index",
    # Task 3 (Round 27, Beta): liquidity position guidance
    "recommended_max_positions": "Max Positions",
    # Task 1 (Round 28, Alpha): factor cross-correlation
    "high_correlation_pair_count": "Factor Redund Pairs",
    # Task 2 (Round 28, Gamma): regime alpha consistency
    "alpha_consistency_score": "Alpha Regime Consist",
    "all_regimes_positive_alpha": "All Regimes Pos Alpha",
    # Task 3 (Round 28, Beta): post-loss recovery
    "post_loss_t2_positive_rate": "Post-Loss T2 Pos%",
    # Task 1 (Round 29, Alpha): PCA factor diversity score
    "pca_diversity_score": "PCA Diversity Score",
    # Task 2 (Round 29, Gamma): IS/OOS overfit score
    "overfit_score": "Overfit Score",
    # Task 3 (Round 29, Beta): weekday win-rate spread
    "weekday_win_rate_spread": "Weekday WR Spread",
    # Task 1 (Round 30, Gamma): parameter drift score
    "param_drift_score": "Param Drift Score",
    # Task 2 (Round 30, Alpha): monthly win-rate spread
    "monthly_win_rate_spread": "Monthly WR Spread",
    # Task 3 (Round 30, Beta): nonlinear factor count
    "nonlinear_factor_count": "Nonlinear Factor Count",
    # Task 1 (Round 31, Alpha): return autocorrelation lag-1
    "autocorr_lag1": "收益序列Lag1自相关",
    # Task 2 (Round 31, Gamma): score CV across windows
    "score_cv_across_windows": "Score CV Across Windows",
    # Task 1 (Round 32, Gamma): conditional tail-risk metrics
    "score_tail_separation": "Tail Separation",
    "tail_risk_asymmetry": "Tail Risk Asymmetry",
    "high_score_cvar_5pct": "HighScore CVaR 5%",
    # Task 2 (Round 32, Alpha): volume anomaly metrics
    "extreme_volume_win_rate_premium": "Volume WR Premium",
    "inflow_win_rate_premium": "Inflow WR Premium",
    # Task 3 (Round 32, Beta): composite gate score
    "composite_gate_score": "Composite Gate Score",
    # Task 1 (Round 33, Alpha): expected value per trade
    "expected_value_per_trade": "期望收益/笔",
    # Task 2 (Round 33, Gamma): momentum decay half-life
    "momentum_half_life_days": "Momentum Half-Life d",
    # Task 3 (Round 33, Beta): IC trend stability
    "ic_trend_stability": "IC Trend Stability",
    # Task 3 (Round 33, Beta): IC trend deteriorating
    "factor_ic_trend_deteriorating": "IC Trend Deteriorating",
    # Task 1 (Round 34, Alpha): multi-factor conditional lift
    "multi_factor_lift": "多因子联合提升",
    # Task 2 (Round 34, Gamma): adaptive sizing score
    "adaptive_sizing_score": "自适应仓位评分",
    # Task 3 (Round 34, Beta): signal churn rate
    "signal_churn_rate": "信号流失率",
    # Task 3 (Round 34, Beta): signal persistence
    "avg_signal_persistence": "信号持续率",
    # Task 1 (Round 35, Alpha): Sortino risk-adjusted return ratio
    "sortino_ratio": "Sortino风险收益比",
    # Task 2 (Round 35, Gamma): quality trend score
    "quality_trend_score": "质量趋势评分",
    # Task 3 (Round 35, Beta): candidate diversity score
    "diversity_score": "候选多样性评分",
    # Task 1 (Round 36, Alpha): right-tail dominance ratio
    "right_tail_dominance": "右尾优势比",
    # Task 2 (Round 36, Beta): composite score Spearman IC
    "composite_ic": "综合评分IC",
    # Task 3 (Round 36, Gamma): win-rate bootstrap CI width
    "win_rate_ci_width": "胜率置信区间宽度",
    # Task 1 (Round 37, Alpha): optimal holding days
    "optimal_holding_days": "最优持仓天数",
    # Task 2 (Round 37, Beta): loss trade signature strength
    "loss_signature_strength": "亏损特征区分度",
    # Task 3 (Round 37, Gamma): score Gini coefficient
    "score_gini": "评分基尼系数",
    # Task 1 (Round 38, Alpha): market environment sensitivity — bull vs bear win-rate gap
    "env_win_rate_gap": "多空环境胜率差",
    # Task 2 (Round 38, Beta): factor importance ranking — positive-IC factor count
    "positive_ic_factor_count": "正IC因子数",
    # Task 3 (Round 38, Gamma): score bucket win rates — top quintile premium
    "top_quintile_premium": "顶分位胜率溢价",
    # Task 1 (Round 39, Alpha): recency vs history — win-rate gap (recent minus historical)
    "recency_win_rate_gap": "近期vs历史胜率差",
    # Task 2 (Round 39, Beta): optimal score threshold — win-rate lift above optimal threshold
    "optimal_threshold_lift": "最优阈值胜率提升",
    # Task 3 (Round 39, Gamma): simulated equity curve — recovery factor
    "recovery_factor": "权益恢复系数",
    # Task 3 (Round 39, Gamma): simulated equity curve — max drawdown
    "max_drawdown_simulated": "最大回撤",
    # Task 1 (Round 40, Alpha): factor synergy matrix — max pairwise co-activation lift
    "max_synergy_lift": "最强因子对协同提升",
    # Task 2 (Round 40, Beta): float turnover analysis — high vs low turnover win-rate lift
    "high_vs_low_lift": "高低换手胜率差",
    # Task 3 (Round 40, Gamma): cross-window factor exposure drift score
    "factor_drift_score": "因子暴露漂移度",
    # Task 1 (Round 41, Alpha): factor IC rank consistency across replay windows
    "factor_rank_consistency_score": "因子排序一致性",
    # Task 2 (Round 41, Beta): volume-price direction alignment rate
    "vol_price_alignment_rate": "量价方向对齐率",
    # Task 3 (Round 41, Gamma): combined statistical significance score
    "combined_significance_score": "综合统计显著性",
    # Task 1 (Round 42, Alpha): composite score calibration slope
    "calibration_slope": "评分校准斜率",
    # Task 2 (Round 42, Beta): close-strength top-quartile premium
    "cs_top_quartile_premium": "收盘强度顶档溢价",
    # Task 3 (Round 42, Gamma): cross-window consensus pass rate
    "consensus_windows_pct": "跨窗共识通过率",
    # Task 1 (Round 43, Alpha): profit factor
    "profit_factor": "盈利因子PF",
    # Task 2 (Round 43, Beta): high-vs-low sentiment lift
    "high_vs_low_sentiment_lift": "高低情绪胜率差",
    # Task 3 (Round 43, Gamma): score momentum trend
    "score_trend_normalized": "评分动量趋势",
    # Task 1 (Round 44, Alpha): RS top-quartile premium
    "rs_top_quartile_premium": "RS高分位溢价",
    # Task 2 (Round 44, Beta): breakout quality high-vs-low lift
    "bq_high_vs_low_lift": "突破质量高低胜率差",
    # Task 3 (Round 44, Gamma): cross-window win-rate CV
    "win_rate_cv": "跨窗胜率变异系数",
    # Task 1 (Round 45, Alpha): market-cap high-vs-low win-rate lift
    "mc_high_vs_low_lift": "市值高低胜率差",
    # Task 2 (Round 45, Beta): catalyst-theme top-quartile premium
    "catalyst_top_quartile_premium": "催化主题高分位溢价",
    # Task 3 (Round 45, Gamma): top-candidate cross-window consistency rate
    "top_candidate_consistency_rate": "顶候选胜率一致性",
    # Task 1 (Round 46, Alpha): volume-price divergence low-vs-high win-rate lift
    "vpd_low_vs_high_lift": "量价低背离胜率溢价",
    # Task 2 (Round 46, Beta): score distribution skewness
    "score_skewness": "评分分布偏度",
    # Task 2 (Round 46, Beta): score positive-value fraction
    "score_positive_pct": "评分正值占比",
    # Task 3 (Round 46, Gamma): cross-window gate consistency coefficient of variation
    "gate_above_threshold_cv": "跨窗门控占比变异系数",
    # Task 1 (Round 47, Alpha): momentum slope high-vs-low win-rate lift
    "ms_high_vs_low_lift": "动量高低胜率差",
    # Task 2 (Round 47, Beta): net inflow ratio high-vs-low win-rate lift
    "inflow_high_vs_low_lift": "净流入高低胜率差",
    # Task 3 (Round 47, Gamma): cross-window factor IC positive consistency rate
    "positive_ic_consistency_rate": "因子IC跨窗正向一致率",
    # Task 1 (Round 48, Alpha): VEQ high-vs-low win-rate lift
    "veq_high_vs_low_lift": "成交量质量高低胜率差",
    # Task 2 (Round 48, Beta): sector resonance high-vs-low win-rate lift
    "sr_high_vs_low_lift": "板块共振高低胜率差",
    # Task 3 (Round 48, Gamma): cross-window expected-value trend slope
    "ev_trend_slope": "期望收益跨窗趋势斜率",
    # Task 1 (Round 49, Alpha): multi-factor consensus win-rate lift
    "consensus_lift": "多因子共识胜率溢价",
    # Task 2 (Round 49, Beta): score decile top-vs-bottom premium
    "top_decile_premium": "评分十分位溢价",
    # Task 3 (Round 49, Gamma): cross-window Sortino trend slope
    "sortino_trend_slope": "Sortino跨窗趋势斜率",
    # Task 1 (Round 50, Alpha): factor redundancy average correlation
    "avg_inter_factor_correlation": "因子平均冗余度",
    # Task 2 (Round 50, Beta): T+2 vs T+1 win-rate premium
    "t2_vs_t1_premium": "T+2相对T+1胜率差",
    # Task 3 (Round 50, Gamma): cross-window Sharpe trend slope
    "sharpe_trend_slope": "Sharpe跨窗趋势斜率",
    # Task 1 (Round 51, Alpha): win/loss magnitude ratio
    "win_loss_magnitude_ratio": "平均盈亏比",
    # Task 1 (Round 51, Alpha): Kelly criterion fraction
    "kelly_fraction": "Kelly分数",
    # Task 2 (Round 51, Beta): outlier dependency ratio
    "outlier_dependency_ratio": "离群收益依赖度",
    # Task 3 (Round 51, Gamma): cross-window profit-factor trend slope
    "pf_trend_slope": "盈利因子跨窗趋势",
    # Task 1 (Round 52, Alpha): annualised Information Ratio
    "information_ratio": "年化信息比率",
    # Task 2 (Round 52, Beta): score concentration index
    "score_concentration_index": "高分候选集中度",
    # Task 3 (Round 52, Gamma): cross-window Kelly fraction trend slope
    "kelly_trend_slope": "Kelly分数跨窗趋势",
    # Task 1 (Round 53, Alpha): conditional factor-synergy win-rate lift
    "conditional_lift": "条件因子高信号胜率提升",
    # Task 3 (Round 53, Gamma): cross-window Information Ratio trend slope
    "ir_trend_slope": "IR信号跨窗趋势斜率",
    # Task 1 (Round 54, Alpha): tail-risk asymmetry
    "tail_asymmetry": "尾部收益不对称度",
    # Task 2 (Round 54, Beta): maximum drawdown rate
    "drawdown_max_drawdown": "最大回撤率",
    # Task 3 (Round 54, Gamma): conditional factor synergy cross-window trend
    "conditional_lift_trend_slope": "条件因子协同跨窗趋势",
    # Task 1 (Round 55, Alpha): multi-factor mean IC
    "decay_mean_ic": "多因子平均IC",
    # Task 2 (Round 55, Beta): intraday session win-rate spread
    "time_seg_session_win_rate_spread": "最佳时段胜率差异",
    # Task 3 (Round 55, Gamma): cross-window max-drawdown OLS trend slope
    "drawdown_trend_slope": "最大回撤跨窗趋势",
    # Task 1 (Round 56, Alpha): sector diversification score — 1 − HHI
    "diversification_score": "行业多样化评分",
    # Task 2 (Round 56, Beta): score rank IC — Spearman IC of composite score vs T+1 return
    "rank_ic": "评分排名IC",
    # Task 3 (Round 56, Gamma): cross-window mean-IC OLS trend slope
    "ic_trend_slope": "多因子IC跨窗趋势",
    # Task 1 (Round 57, Alpha): market regime adaptability score
    "regime_adaptability": "市场状态适应性",
    # Task 2 (Round 57, Beta): turnover efficiency difference
    "turnover_efficiency": "换手率效率差异",
    # Task 3 (Round 57, Gamma): cross-window rank-IC OLS trend slope
    "rank_ic_trend_slope": "排名IC跨窗趋势",
    # Task 1 (Round 58, Alpha): optimal entry threshold win rate
    "optimal_win_rate": "最优阈值胜率",
    # Task 2 (Round 58, Beta): total factor explained variance
    "total_explained_variance": "因子总解释方差",
    # Task 3 (Round 58, Gamma): cross-window regime adaptability trend slope
    "regime_trend_slope": "市场适应性跨窗趋势",
    # Task 1 (Round 59, Alpha): return distribution skewness
    "skewness": "收益分布偏度",
    # Task 2 (Round 59, Beta): composite quality score
    "composite_quality_score": "综合质量评分",
    # Task 3 (Round 59, Gamma): cross-window threshold win-rate trend slope
    "threshold_win_rate_trend_slope": "阈值胜率跨窗趋势",
    # Task 1 (Round 60, Alpha): multi-signal high-consistency win-rate lift
    "signal_consistency_lift": "多信号高一致性胜率提升",
    # Task 2 (Round 60, Beta): T+1 win rate from holding period optimization
    "t1_win_rate": "最优持仓期胜率",
    # Task 3 (Round 60, Gamma): composite quality score cross-window trend slope
    "quality_score_trend_slope": "综合质量评分跨窗趋势",
    # Task 1 (Round 61, Alpha): concentration risk
    "concentration_risk": "收益集中风险度",
    # Task 2 (Round 61, Beta): extreme market resilience score
    "resilience_score": "极端行情韧性评分",
    # Task 3 (Round 61, Gamma): signal consistency cross-window trend slope
    "consistency_trend_slope": "信号一致性跨窗趋势",
    # Task 1 (Round 62, Alpha): low-liquidity candidate fraction
    "low_liquidity_pct": "低流动性标的占比",
    # Task 2 (Round 62, Beta): cost-adjusted profit factor
    "cost_adjusted_profit_factor": "成本调整后盈利因子",
    # Task 3 (Round 62, Gamma): cross-window extreme resilience trend slope
    "resilience_trend_slope": "极端韧性跨窗趋势",
    # Task 1 (Round 63, Alpha): best stop-loss/take-profit profit factor
    "best_profit_factor": "最优止损止盈盈利因子",
    # Task 2 (Round 63, Beta): best factor-combination win rate
    "best_combo_win_rate": "最优因子组合胜率",
    # Task 3 (Round 63, Gamma): cross-window cost-adjusted PF trend slope
    "cost_pf_trend_slope": "成本调整PF跨窗趋势",
    # Task 3 (Round 64, Gamma): cross-window best combo win rate trend slope
    "combo_win_rate_trend_slope": "最优组合胜率跨窗趋势",
    # Task 1 (Round 64, Alpha): adaptive weight effective factor count
    "adaptive_weight_effective_factor_count": "自适应权重有效因子数",
    # Task 2 (Round 64, Beta): factor validity window IC stability
    "ic_stability": "因子有效性稳定度",
    # Task 1 (Round 65, Alpha): total factor return attribution explanatory power
    "total_attribution": "因子归因总解释力",
    # Task 2 (Round 65, Beta): multi-timeframe consistency score
    "timeframe_consistency": "多时框一致性评分",
    # Task 3 (Round 65, Gamma): cross-window IC stability OLS trend slope
    "ic_stability_trend_slope": "因子有效稳定性跨窗趋势",
    # Task 1 (Round 66, Alpha): volatility regime win-rate edge
    "vol_regime_edge": "低波动环境胜率优势",
    # Task 2 (Round 66, Beta): mean nonlinear factor interaction effect
    "interact_mean_interaction_effect": "最强非线性交互效应",
    # Task 3 (Round 66, Gamma): cross-window total attribution trend slope
    "attribution_trend_slope": "因子归因力跨窗趋势",
    # Task 1 (Round 67, Alpha): score dispersion win-rate spread
    "score_win_rate_spread": "得分离散区分度",
    # Task 2 (Round 67, Beta): fund flow breakout synergy win rate
    "flow_breakout_synergy": "资金突破协同胜率",
    # Task 3 (Round 67, Gamma): cross-window nonlinear interaction trend slope
    "interaction_trend_slope": "非线性交互跨窗趋势",
    # Task 1 (Round 68, Alpha): tail event filter effect
    "tail_filter_effect": "尾部过滤净效果",
    # Task 2 (Round 68, Beta): position concentration HHI
    "sector_hhi": "持仓HHI集中度",
    # Task 3 (Round 68, Gamma): cross-window score dispersion trend slope
    "dispersion_trend_slope": "得分区分度跨窗趋势",
    # Task 1 (Round 69, Alpha): RS排名强弱胜率差
    "rs_rank_spread": "RS排名强弱胜率差",
    # Task 2 (Round 69, Beta): 正常换手胜率优势
    "turnover_filter_effect": "正常换手胜率优势",
    # Task 3 (Round 69, Gamma): 持仓集中度跨窗趋势
    "concentration_hhi_slope": "持仓集中度跨窗趋势",
    # Task 1 (Round 70, Alpha): 价格位置强弱胜率差
    "cs_win_rate_spread": "价格位置强弱胜率差",
    # Task 2 (Round 70, Beta): 连胜比率
    "streak_ratio": "连胜比率",
    # Task 3 (Round 70, Gamma): RS排名区分度跨窗趋势
    "rs_rank_trend_slope": "RS排名区分度跨窗趋势",
    # Task 1 (Round 71, Alpha): 动量强弱胜率差
    "momentum_win_spread": "动量强弱胜率差",
    # Task 2 (Round 71, Beta): 量能结构胜率差
    "vol_structure_spread": "量能结构胜率差",
    # Task 3 (Round 71, Gamma): 价格位置区分度跨窗趋势
    "price_pos_trend_slope": "价格位置区分度跨窗趋势",
    # Task 1 (Round 72, Alpha): 多因子Z综合胜率差
    "zscore_win_spread": "多因子Z综合胜率差",
    # Task 2 (Round 72, Beta): 收益持续稳定性
    "persistence_score": "收益持续稳定性",
    # Task 3 (Round 72, Gamma): 动量区分度跨窗趋势
    "momentum_rank_trend_slope": "动量区分度跨窗趋势",
    # Task 1 (Round 73, Alpha): 市场宽度胜率
    "breadth_win_rate": "市场宽度胜率",
    # Task 2 (Round 73, Beta): 因子IC一致性比
    "ic_consistency_ratio": "因子IC一致性比",
    # Task 3 (Round 73, Gamma): Z综合分组跨窗趋势
    "zscore_trend_slope": "Z综合分组跨窗趋势",
    # Task 1 (Round 74, Alpha): 信号强度分层胜率差
    "stratification_spread": "信号强度分层胜率差",
    # Task 2 (Round 74, Beta): 条件动量协同优势
    "conditional_momentum_edge": "条件动量协同优势",
    # Task 3 (Round 74, Gamma): 市场宽度跨窗趋势
    "breadth_trend_slope": "市场宽度跨窗趋势",
    # Task 1 (Round 75, Alpha): 风险调整收益Sharpe
    "sharpe_ratio": "风险调整收益Sharpe",
    # Task 2 (Round 75, Beta): 最大因子共线性
    "max_collinearity": "最大因子共线性",
    # Task 3 (Round 75, Gamma): 分层区分度跨窗趋势
    "stratification_trend_slope": "分层区分度跨窗趋势",
    # Task 1 (Round 76, Alpha): 收益偏斜质量增益损失比
    "gain_loss_ratio": "收益偏斜质量增益损失比",
    # Task 1 (Round 76, Alpha): 收益尾部不对称分数
    "tail_asymmetry_score": "收益尾部不对称分数",
    # Task 2 (Round 76, Beta): 因子正交性分数
    "orthogonality_score": "因子正交性分数",
    # Task 1 (Round 77, Alpha): 自适应阈值提升效果
    "threshold_lift": "自适应阈值提升效果",
    # Task 2 (Round 77, Beta): 板块轮动分散度
    "sector_win_rate_dispersion": "板块轮动分散度",
    # Task 3 (Round 77, Gamma): 偏斜质量跨窗趋势
    "skew_trend_slope": "偏斜质量跨窗趋势",
    # Task 3 (Round 78, Gamma): 阈值提升跨窗趋势
    "threshold_lift_trend_slope": "阈值提升跨窗趋势",
    # Task 1 (Round 78, Alpha): 热门股胜率优势
    "hotstock_edge": "热门股胜率优势",
    # Task 2 (Round 78, Beta): 因子稳健性比率
    "robustness_ratio": "因子稳健性比率",
    # Task 1 (Round 79, Alpha): 五分位单调性
    "sq_consist_quintile_monotonicity_score": "五分位单调性得分",
    "sq_consist_quintile_top_bottom_spread": "五分位Q5-Q1胜率差",
    # Task 2 (Round 79, Beta): 量价共振入场质量
    "entry_qual_high_quality_entry_win_rate": "高质量入场胜率",
    "entry_qual_quality_entry_edge": "入场质量胜率溢价",
    # Task 3 (Round 79, Gamma): 稳健性跨窗趋势
    "robustness_trend_slope": "稳健性跨窗趋势斜率",
    # Task 1 (Round 80, Alpha): 高低分组中位收益差
    "ret_qlift_median_return_lift": "高低分组中位收益差",
    "ret_qlift_top_median_return": "高分组中位收益",
    # Task 2 (Round 80, Beta): 近高位股胜率
    "nh_near_high_win_rate": "近高位股胜率",
    "nh_near_high_edge": "近高位股胜率溢价",
    # Task 3 (Round 80, Gamma): 入场质量跨窗趋势
    "entry_quality_trend_slope": "入场质量跨窗趋势斜率",
    # Task 1 (Round 81, Alpha): 高低分组期望收益
    "ev_top_ev": "高分组期望收益",
    "ev_ev_spread": "高低分组EV差",
    # Task 2 (Round 81, Beta): 高净流入胜率溢价
    "hi_inflow_high_inflow_win_rate": "高净流入胜率",
    "hi_inflow_high_inflow_edge": "高净流入胜率溢价",
    # Task 3 (Round 81, Gamma): 近高位股跨窗趋势
    "near_high_trend_slope": "近高位股跨窗趋势斜率",
    # Task 1 (Round 82, Alpha): score prediction accuracy labels.
    "clf_high_score_precision": "打分系统精确率",
    "clf_f1_score": "打分系统F1分数",
    # Task 2 (Round 82, Beta): volume-price divergence labels.
    "vpd_full_confirm_win_rate": "量价双高胜率",
    "vpd_divergence_penalty": "量价背离惩罚",
    # Task 3 (Round 82, Gamma): EV spread trend label.
    "ev_spread_trend_slope": "EV差跨窗趋势斜率",
    # Task 1 (Round 83, Alpha): Kelly criterion labels.
    "kelly_top_kelly": "高分组凯利仓位",
    "kelly_kelly_spread": "高低分组凯利差",
    # Task 2 (Round 83, Beta): return percentile profile labels.
    "rpp_top_return_p75": "高分组P75收益",
    "rpp_upside_asymmetry": "上下行不对称性",
    # Task 3 (Round 83, Gamma): precision trend label.
    "precision_trend_slope": "精确率跨窗趋势斜率",
    # Task 1 (Round 84, Alpha): momentum reversal labels.
    "mom_rev_extreme_momentum_win_rate": "极端动量胜率",
    "mom_rev_momentum_breadth_effect": "动量广度效应",
    # Task 2 (Round 84, Beta): sector tailwind protection labels.
    "tailwind_protected_win_rate": "顺风高强度胜率",
    "tailwind_gap_protection_effect": "板块保护效应",
    # Task 3 (Round 84, Gamma): upside asymmetry trend label.
    "upside_asymmetry_trend_slope": "上行不对称跨窗趋势斜率",
    # Task 1 (Round 85, Alpha): batch consistency analysis labels.
    "batch_batch_consistency_score": "批次时序一致性分数",
    "batch_batch3_win_rate": "最新批次胜率",
    # Task 2 (Round 85, Beta): liquidity weighted return analysis labels.
    "liq_lw_win_rate": "流动性加权胜率",
    "liq_liquidity_bias": "流动性执行偏差",
    # Task 3 (Round 85, Gamma): momentum reversal trend label.
    "momentum_reversal_trend_slope": "动量广度效应跨窗趋势",
    # Task 1 (Round 86, Alpha): factor IC consistency ratio label.
    "frc_factor_ic_consistency_ratio": "7核心因子IC一致性比率",
    # Task 2 (Round 86, Beta): breakout quality premium edge label.
    "bq_breakout_premium_edge": "突破质量P75胜率溢价",
    # Task 3 (Round 86, Gamma): batch consistency trend slope label.
    "batch_consistency_trend_slope": "批次一致性跨窗趋势斜率",
    # Task 1 (Round 87, Alpha): regime adaptive win rate spread label.
    "regime_regime_spread": "机制差值(高-低机制胜率)",
    # Task 2 (Round 87, Beta): signal persistence edge label.
    "sig_signal_persistence_edge": "信号持续质量边缘(Top-Bot胜率差)",
    # Task 3 (Round 87, Gamma): regime spread cross-window trend slope label.
    "regime_spread_trend_slope": "机制差跨窗趋势斜率",
    # Task 1 (Round 88, Alpha): volume-price divergence score labels.
    "vp_volume_premium_edge": "量价溢价优势",
    "vp_volume_return_alignment": "量价对齐相关系数",
    "vp_high_vol_win_rate": "高量区胜率",
    # Task 2 (Round 88, Beta): entry timing quality labels.
    "et_inflow_timing_edge": "入场时机优势",
    "et_high_inflow_win_rate": "高流入组胜率",
    "et_low_inflow_win_rate": "低流入组胜率",
    "et_high_inflow_avg_return": "高流入组平均回报",
    # Task 3 (Round 88, Gamma): signal quality cross-window trend slope label.
    "signal_quality_trend_slope": "信号质量趋势斜率",
    # Task 1 (Round 89, Alpha): open-gap intraday persistence labels.
    "ogp_gap_win_rate_premium": "开盘跳空延续性溢价(高隙-低隙胜率差)",
    "ogp_gap_vs_full_day_ic": "开盘跳空与全天收益IC",
    "ogp_high_gap_win_rate": "高跳空区胜率",
    # Task 2 (Round 89, Beta): tail flow quality score labels.
    "tf_composite_win_rate_premium": "尾盘资金质量溢价(高流量-低流量胜率差)",
    "tf_high_flow_win_rate": "高尾盘流量组胜率",
    "tf_low_flow_win_rate": "低尾盘流量组胜率",
    # Task 3 (Round 89, Gamma): momentum IC consistency labels.
    "mc_ic_consistency_score": "动量IC方向一致性(正IC窗口占比)",
    "mc_momentum_ic": "动量确认分数Spearman IC",
    "mc_momentum_win_rate_premium": "动量胜率溢价",
}
LOWER_IS_BETTER_COMPARISON_METRICS = {
    "crowding_risk_raw_100",
    "gap_risk_raw_100",
    "projected_theme_exposure",
    "incremental_theme_exposure",
    "time_to_hit_20pct_median",
    # Task 1 (Round 12): intraday drawdown — more negative is worse (lower is worse, but we
    # want higher/less-negative values to be preferred, so this metric is NOT in lower-is-better).
    # A floor guardrail enforces the minimum via BTST_QUALITY_FLOORS.
    # Task 4 (Round 15): stop-loss trigger rates — a *higher* rate means more bars hit the stop,
    # which is worse.  All three levels are lower-is-better.
    "stop_loss_trigger_rate_2pct",
    "stop_loss_trigger_rate_3pct",
    "stop_loss_trigger_rate_5pct",
    # Task 2 (Round 16): volume-price divergence rate — higher = more false-breakout bars = worse.
    "volume_price_divergence_rate",
    # Task 3 (Round 16): predicted range p75 — higher = more volatile regime = lower-is-better.
    "predicted_range_pct_p75",
    # Task 3 (Round 16): high-volatility warning rate — higher = more high-vol sessions = lower-is-better.
    "high_volatility_warning_rate",
    # Task 3 (Round 20, Gamma): consecutive limit-up rate — higher = more limit-up risk in pool = lower-is-better.
    "consecutive_limit_up_rate",
    # Task 1 (Round 24): decaying factor count — more decaying factors = worse predictive signal.
    "decaying_factor_count",
    # Task 2 (Round 25, Beta): window volatility — higher = more unstable selection = lower-is-better.
    "win_rate_window_volatility",
    # Task 1 (Round 28, Alpha): high correlation pair count — more redundant pairs = worse = lower-is-better.
    "high_correlation_pair_count",
    # Task 2 (Round 29, Gamma): IS/OOS overfit score — higher = more overfit = lower-is-better.
    "overfit_score",
    # Task 1 (Round 30, Gamma): parameter drift score — higher = more unstable parameters = lower-is-better.
    "param_drift_score",
    # Task 3 (Round 30, Beta): nonlinear factor count — more nonlinear factors = more linear-scoring bias = lower-is-better.
    "nonlinear_factor_count",
    # Task 2 (Round 31, Gamma): score CV across windows — higher CV = less stable scoring = lower-is-better.
    "score_cv_across_windows",
    # Task 1 (Round 32, Gamma): tail-risk asymmetry — higher = worse tail asymmetry = lower-is-better.
    "tail_risk_asymmetry",
    # Task 1 (Round 32, Gamma): high-score group CVaR — more negative = worse = lower-is-better (more negative).
    # NOTE: stored as a negative number; "lower" here means more negative (worse), so NOT in this set.
    # Instead score_tail_separation (higher = better) drives the direction.
    # Task 2 (Round 33, Gamma): momentum half-life — shorter = faster decay = more BTST-friendly = lower-is-better.
    "momentum_half_life_days",
    # Task 3 (Round 34, Beta): signal churn rate — higher = more pool turnover = less stable = lower-is-better.
    "signal_churn_rate",
    # Task 3 (Round 36, Gamma): win-rate CI width — wider = less reliable estimate = lower-is-better.
    "win_rate_ci_width",
    # Task 2 (Round 37, Beta): loss signature strength — higher = better factor discrimination = NOT lower-is-better.
    # (intentionally not added — higher strength is better, default higher-is-better)
    # Task 3 (Round 39, Gamma): max drawdown simulated — higher drawdown = worse = lower-is-better.
    "max_drawdown_simulated",
    # Task 3 (Round 40, Gamma): factor drift score — higher = more unstable factor exposure = lower-is-better.
    "factor_drift_score",
    # Task 3 (Round 44, Gamma): cross-window win-rate CV — higher = more unstable win rate = lower-is-better.
    "win_rate_cv",
    # Task 3 (Round 46, Gamma): cross-window gate consistency CV — higher = more gate instability = lower-is-better.
    "gate_above_threshold_cv",
    # Task 1 (Round 50, Alpha): avg inter-factor correlation — higher = more redundant signals = lower-is-better.
    "avg_inter_factor_correlation",
    # Task 2 (Round 51, Beta): outlier dependency ratio — higher = more reliance on outliers = lower-is-better.
    "outlier_dependency_ratio",
    # Task 2 (Round 54, Beta): maximum drawdown — higher = larger drawdown = lower-is-better.
    "drawdown_max_drawdown",
    # Task 3 (Round 55, Gamma): cross-window drawdown trend slope — negative slope = improving risk = lower is better.
    "drawdown_trend_slope",
    # Task 1 (Round 61, Alpha): concentration risk — higher = more P&L concentrated in few trades = lower-is-better.
    "concentration_risk",
    # Task 1 (Round 62, Alpha): low-liquidity fraction — higher = more low-turnover candidates = lower-is-better.
    "low_liquidity_pct",
    # Task 2 (Round 64, Beta): IC stability — higher std = more unstable factor validity = lower-is-better.
    "ic_stability",
    # Task 3 (Round 65, Gamma): IC stability trend slope — negative slope = validity becoming more stable = lower-is-better.
    "ic_stability_trend_slope",
    # Task 3 (Round 66, Gamma): attribution trend slope — more-negative slope = declining attribution = lower-is-better.
    "attribution_trend_slope",
    # Task 2 (Round 68, Beta): position concentration HHI — higher = more concentrated sector pool = lower-is-better.
    "sector_hhi",
    # Task 3 (Round 69, Gamma): concentration HHI trend slope — positive = HHI rising = concentration worsening = lower-is-better.
    "concentration_hhi_slope",
    # Task 2 (Round 75, Beta): max factor collinearity — higher = more redundant factors = lower-is-better.
    "max_collinearity",
}
# Runner metrics are optional — surfaces computed without the runner analysis pipeline
# will not have these fields, and their absence should not block rollout.
OPTIONAL_COMPARISON_METRICS: frozenset[str] = frozenset({
    "max_future_high_return_2_5d_hit_rate_at_20pct",
    "time_to_hit_20pct_median",
    "runner_capture_count",
    "runner_escape_rate",
    "avg_composite_score_escaped",
    "t_plus_2_close_positive_rate",
    "t_plus_2_close_payoff_ratio",
    "t_plus_3_close_positive_rate",
    "t_plus_3_close_expectancy",
    "t_plus_3_close_payoff_ratio",
    # Task 1 (Round 11): IC / pool quality metrics are optional because legacy surfaces
    # may not expose them.  Their absence must not block rollout.
    "ic_positive_factor_fraction",
    "candidate_pool_avg_composite_score",
    # Task 1 (Round 12): intraday drawdown is optional — surfaces produced before Round 12
    # will not carry this field; its absence must not block rollout.
    "t_plus_1_intraday_drawdown_p10",
    # Task 4 (Round 15): stop-loss trigger rates — optional since surfaces before Round 15
    # will not carry these fields; their absence must not block rollout.
    "stop_loss_trigger_rate_2pct",
    "stop_loss_trigger_rate_3pct",
    "stop_loss_trigger_rate_5pct",
    # Task 5 (Round 15): cross-day autocorrelation — optional; pre-Round-15 surfaces omit it.
    "cross_day_autocorr_t1_vs_t2",
    "cross_day_autocorr_t2_vs_t3",
    # Task 2 (Round 15): gap continuation rate — optional; pre-Round-15 surfaces omit it.
    "gap_continuation_rate",
    # Task 2 (Round 16): volume-price divergence rate — optional; pre-Round-16 surfaces omit it.
    "volume_price_divergence_rate",
    # Task 3 (Round 16): predicted range and high-volatility warning — optional; pre-Round-16 surfaces omit these.
    "predicted_range_pct_p75",
    "high_volatility_warning_rate",
    # Task 1 (Round 20, Beta): realized payoff ratio — optional; pre-Round-20 surfaces omit it.
    "realized_payoff_ratio",
    # Task 2 (Round 20, Alpha): score-conditioned metrics — optional; pre-Round-20 surfaces omit these.
    "high_confidence_selection_rate",
    "score_weighted_win_rate",
    "score_win_rate_lift",
    "high_confidence_win_rate",
    # Task 3 (Round 20, Gamma): limit-up risk statistics — optional; pre-Round-20 surfaces omit these.
    "consecutive_limit_up_rate",
    "limit_up_win_rate",
    "non_limit_up_win_rate",
    # Task 3 (Round 21, Beta): execution timing signal — optional; pre-Round-21 surfaces omit these.
    "open_entry_signal_strength",
    "execution_timing_confidence",
    # Task 2 (Round 22, Alpha): multi-day hold period — optional; pre-Round-22 surfaces omit these.
    "t1_vs_t2_sharpe_diff",
    "hold_period_confidence",
    # Task 3 (Round 22, Beta): score position tiers — optional; pre-Round-22 surfaces omit these.
    "tier_win_rate_spread",
    "tier_monotone_win_rate",
    # Task 2 (Round 23, Alpha): Kelly fraction — optional; pre-Round-23 surfaces omit these.
    "kelly_fraction_half",
    "kelly_positive",
    # Task 3 (Round 23, Beta): regime consistency — optional; pre-Round-23 surfaces omit these.
    "regime_consistency_score",
    "regime_robustness_flag",
    # Task 1 (Round 24): IC temporal trend — optional; pre-Round-24 outputs omit these.
    "decaying_factor_count",
    # Task 2 (Round 24): drawdown-adjusted Kelly — optional; pre-Round-24 surfaces omit these.
    "kelly_fraction_drawdown_adjusted",
    "drawdown_adjustment_factor",
    # Task 3 (Round 24): verdict calibration — optional; pre-Round-24 outputs omit these.
    "verdict_calibration_score",
    "verdict_monotone",
    # Task 1 (Round 25, Gamma): profile health score — optional; pre-Round-25 outputs omit it.
    "profile_health_score",
    # Task 2 (Round 25, Beta): selection churn metrics — optional; pre-Round-25 outputs omit these.
    "win_rate_window_volatility",
    "win_rate_window_trend",
    # Task 2 (Round 26, Gamma): benchmark-adjusted Alpha — optional; requires hs300_daily_return field.
    "alpha_avg_return",
    "information_ratio",
    # Task 3 (Round 26, Beta): dynamic stop-loss suggestion — optional; pre-Round-26 outputs omit it.
    "suggested_stop_loss_pct",
    # Task 1 (Round 27, Alpha): return distribution shape — optional; pre-Round-27 outputs omit these.
    "next_close_return_skewness",
    "win_loss_std_ratio",
    # Task 2 (Round 27, Gamma): score discrimination power — optional; pre-Round-27 outputs omit it.
    "score_discrimination_index",
    # Task 3 (Round 27, Beta): liquidity position guidance — optional; pre-Round-27 outputs omit it.
    "recommended_max_positions",
    # Task 1 (Round 28, Alpha): factor cross-correlation — optional; pre-Round-28 outputs omit it.
    "high_correlation_pair_count",
    # Task 2 (Round 28, Gamma): regime alpha consistency — optional; requires hs300_daily_return field.
    "alpha_consistency_score",
    "all_regimes_positive_alpha",
    # Task 3 (Round 28, Beta): post-loss recovery — optional; pre-Round-28 outputs omit it.
    "post_loss_t2_positive_rate",
    # Task 1 (Round 29, Alpha): PCA factor diversity score — optional; pre-Round-29 outputs omit it.
    "pca_diversity_score",
    # Task 2 (Round 29, Gamma): IS/OOS overfit score — optional; pre-Round-29 outputs omit it.
    "overfit_score",
    # Task 3 (Round 29, Beta): weekday win-rate spread — optional; pre-Round-29 outputs omit it.
    "weekday_win_rate_spread",
    # Task 1 (Round 30, Gamma): parameter drift score — optional; pre-Round-30 outputs omit it.
    "param_drift_score",
    # Task 2 (Round 30, Alpha): monthly win-rate spread — optional; pre-Round-30 outputs omit it.
    "monthly_win_rate_spread",
    # Task 3 (Round 30, Beta): nonlinear factor count — optional; pre-Round-30 outputs omit it.
    "nonlinear_factor_count",
    # Task 1 (Round 31, Alpha): return autocorrelation — optional; pre-Round-31 outputs omit it.
    "autocorr_lag1",
    # Task 2 (Round 31, Gamma): score CV across windows — optional; pre-Round-31 outputs omit it.
    "score_cv_across_windows",
    # Task 1 (Round 32, Gamma): conditional tail-risk metrics — optional; pre-Round-32 outputs omit these.
    "score_tail_separation",
    "tail_risk_asymmetry",
    "high_score_cvar_5pct",
    # Task 2 (Round 32, Alpha): volume anomaly metrics — optional; pre-Round-32 outputs omit these.
    "extreme_volume_win_rate_premium",
    "inflow_win_rate_premium",
    # Task 3 (Round 32, Beta): composite gate score — optional; pre-Round-32 outputs omit it.
    "composite_gate_score",
    # Task 1 (Round 33, Alpha): expected value per trade — optional; pre-Round-33 outputs omit it.
    "expected_value_per_trade",
    # Task 2 (Round 33, Gamma): momentum decay half-life — optional; pre-Round-33 outputs omit it.
    "momentum_half_life_days",
    # Task 3 (Round 33, Beta): IC trend metrics — optional; pre-Round-33 outputs omit these.
    "ic_trend_stability",
    "factor_ic_trend_deteriorating",
    # Task 1 (Round 34, Alpha): multi-factor conditional lift — optional; pre-Round-34 outputs omit it.
    "multi_factor_lift",
    # Task 2 (Round 34, Gamma): adaptive sizing score — optional; pre-Round-34 outputs omit it.
    "adaptive_sizing_score",
    # Task 3 (Round 34, Beta): signal churn metrics — optional; pre-Round-34 outputs omit these.
    "signal_churn_rate",
    "avg_signal_persistence",
    # Task 1 (Round 35, Alpha): Sortino ratio — optional; pre-Round-35 outputs omit it.
    "sortino_ratio",
    # Task 2 (Round 35, Gamma): quality trend score — optional; pre-Round-35 outputs omit it.
    "quality_trend_score",
    # Task 3 (Round 35, Beta): diversity score — optional; pre-Round-35 outputs omit it.
    "diversity_score",
    # Task 1 (Round 36, Alpha): right-tail dominance — optional; pre-Round-36 outputs omit it.
    "right_tail_dominance",
    # Task 2 (Round 36, Beta): composite score IC — optional; pre-Round-36 outputs omit it.
    "composite_ic",
    # Task 3 (Round 36, Gamma): win-rate CI width — optional; pre-Round-36 outputs omit it.
    "win_rate_ci_width",
    # Task 1 (Round 37, Alpha): optimal holding days — optional; pre-Round-37 outputs omit it.
    "optimal_holding_days",
    # Task 2 (Round 37, Beta): loss signature strength — optional; pre-Round-37 outputs omit it.
    "loss_signature_strength",
    # Task 3 (Round 37, Gamma): score Gini — optional; pre-Round-37 outputs omit it.
    "score_gini",
    # Task 1 (Round 38, Alpha): market environment sensitivity — optional; pre-Round-38 outputs omit it.
    "env_win_rate_gap",
    # Task 2 (Round 38, Beta): factor importance ranking — optional; pre-Round-38 outputs omit it.
    "positive_ic_factor_count",
    # Task 3 (Round 38, Gamma): score bucket win rates — optional; pre-Round-38 outputs omit it.
    "top_quintile_premium",
    # Task 1 (Round 39, Alpha): recency vs history win-rate gap — optional; pre-Round-39 outputs omit it.
    "recency_win_rate_gap",
    # Task 2 (Round 39, Beta): optimal threshold lift — optional; pre-Round-39 outputs omit it.
    "optimal_threshold_lift",
    # Task 3 (Round 39, Gamma): equity curve metrics — optional; pre-Round-39 outputs omit these.
    "recovery_factor",
    "max_drawdown_simulated",
    # Task 1 (Round 40, Alpha): factor synergy lift — optional; pre-Round-40 outputs omit it.
    "max_synergy_lift",
    # Task 2 (Round 40, Beta): float turnover lift — optional; pre-Round-40 outputs omit it.
    "high_vs_low_lift",
    # Task 3 (Round 40, Gamma): cross-window factor drift score — optional; pre-Round-40 outputs omit it.
    "factor_drift_score",
    # Task 1 (Round 41, Alpha): factor rank consistency score — optional; pre-Round-41 outputs omit it.
    "factor_rank_consistency_score",
    # Task 2 (Round 41, Beta): volume-price alignment rate — optional; pre-Round-41 outputs omit it.
    "vol_price_alignment_rate",
    # Task 3 (Round 41, Gamma): combined statistical significance score — optional; pre-Round-41 outputs omit it.
    "combined_significance_score",
    # Task 1 (Round 42, Alpha): calibration slope — optional; pre-Round-42 outputs omit it.
    "calibration_slope",
    # Task 2 (Round 42, Beta): close-strength top-quartile premium — optional; pre-Round-42 outputs omit it.
    "cs_top_quartile_premium",
    # Task 3 (Round 42, Gamma): cross-window consensus pass rate — optional; pre-Round-42 outputs omit it.
    "consensus_windows_pct",
    # Task 1 (Round 43, Alpha): profit factor — optional; pre-Round-43 outputs omit it.
    "profit_factor",
    # Task 2 (Round 43, Beta): high-vs-low sentiment lift — optional; field may be absent when news_sentiment_score is absent.
    "high_vs_low_sentiment_lift",
    # Task 3 (Round 43, Gamma): score momentum trend — optional; pre-Round-43 outputs omit it.
    "score_trend_normalized",
    # Task 1 (Round 44, Alpha): RS top-quartile premium — optional; pre-Round-44 outputs omit it.
    "rs_top_quartile_premium",
    # Task 2 (Round 44, Beta): breakout quality lift — optional; pre-Round-44 outputs omit it.
    "bq_high_vs_low_lift",
    # Task 3 (Round 44, Gamma): cross-window win-rate CV — optional; pre-Round-44 outputs omit it.
    "win_rate_cv",
    # Task 1 (Round 45, Alpha): market-cap high-vs-low lift — optional; pre-Round-45 outputs omit it.
    "mc_high_vs_low_lift",
    # Task 2 (Round 45, Beta): catalyst-theme top-quartile premium — optional; pre-Round-45 outputs omit it.
    "catalyst_top_quartile_premium",
    # Task 3 (Round 45, Gamma): top-candidate consistency rate — optional; pre-Round-45 outputs omit it.
    "top_candidate_consistency_rate",
    # Task 1 (Round 46, Alpha): volume-price divergence lift — optional; pre-Round-46 outputs omit it.
    "vpd_low_vs_high_lift",
    # Task 2 (Round 46, Beta): score skewness — optional; pre-Round-46 outputs omit it.
    "score_skewness",
    # Task 2 (Round 46, Beta): score positive fraction — optional; pre-Round-46 outputs omit it.
    "score_positive_pct",
    # Task 3 (Round 46, Gamma): gate consistency CV — optional; pre-Round-46 outputs omit it.
    "gate_above_threshold_cv",
    # Task 1 (Round 47, Alpha): momentum slope lift — optional; pre-Round-47 outputs omit it.
    "ms_high_vs_low_lift",
    # Task 2 (Round 47, Beta): inflow ratio lift — optional; pre-Round-47 outputs omit it.
    "inflow_high_vs_low_lift",
    # Task 3 (Round 47, Gamma): factor IC consistency rate — optional; pre-Round-47 outputs omit it.
    "positive_ic_consistency_rate",
    # Task 1 (Round 48, Alpha): VEQ lift — optional; pre-Round-48 outputs omit it.
    "veq_high_vs_low_lift",
    # Task 2 (Round 48, Beta): sector resonance lift — optional; pre-Round-48 outputs omit it.
    "sr_high_vs_low_lift",
    # Task 3 (Round 48, Gamma): EV trend slope — optional; pre-Round-48 outputs omit it.
    "ev_trend_slope",
    # Task 1 (Round 49, Alpha): multi-factor consensus lift — optional; pre-Round-49 outputs omit it.
    "consensus_lift",
    # Task 2 (Round 49, Beta): score decile top premium — optional; pre-Round-49 outputs omit it.
    "top_decile_premium",
    # Task 3 (Round 49, Gamma): Sortino trend slope — optional; pre-Round-49 outputs omit it.
    "sortino_trend_slope",
    # Task 1 (Round 50, Alpha): factor redundancy — optional; pre-Round-50 outputs omit it.
    "avg_inter_factor_correlation",
    # Task 2 (Round 50, Beta): extended holding T+2 premium — optional; pre-Round-50 outputs omit it.
    "t2_vs_t1_premium",
    # Task 3 (Round 50, Gamma): Sharpe trend slope — optional; pre-Round-50 outputs omit it.
    "sharpe_trend_slope",
    # Task 1 (Round 51, Alpha): win/loss magnitude ratio — optional; pre-Round-51 outputs omit it.
    "win_loss_magnitude_ratio",
    # Task 1 (Round 51, Alpha): Kelly fraction — optional; pre-Round-51 outputs omit it.
    "kelly_fraction",
    # Task 2 (Round 51, Beta): outlier dependency ratio — optional; pre-Round-51 outputs omit it.
    "outlier_dependency_ratio",
    # Task 3 (Round 51, Gamma): profit-factor trend slope — optional; pre-Round-51 outputs omit it.
    "pf_trend_slope",
    # Task 1 (Round 52, Alpha): Information Ratio — optional; pre-Round-52 outputs omit it.
    "information_ratio",
    # Task 2 (Round 52, Beta): score concentration index — optional; pre-Round-52 outputs omit it.
    "score_concentration_index",
    # Task 3 (Round 52, Gamma): Kelly trend slope — optional; pre-Round-52 outputs omit it.
    "kelly_trend_slope",
    # Task 1 (Round 53, Alpha): conditional lift — optional; pre-Round-53 outputs omit it.
    "conditional_lift",
    # Task 3 (Round 53, Gamma): IR trend slope — optional; pre-Round-53 outputs omit it.
    "ir_trend_slope",
    # Task 1 (Round 54, Alpha): tail-risk asymmetry — optional; pre-Round-54 outputs omit it.
    "tail_asymmetry",
    # Task 2 (Round 54, Beta): max drawdown — optional; pre-Round-54 outputs omit it.
    "drawdown_max_drawdown",
    # Task 3 (Round 54, Gamma): conditional lift trend slope — optional; pre-Round-54 outputs omit it.
    "conditional_lift_trend_slope",
    # Task 1 (Round 55, Alpha): multi-factor mean IC — optional; pre-Round-55 outputs omit it.
    "decay_mean_ic",
    # Task 2 (Round 55, Beta): intraday session win-rate spread — optional; pre-Round-55 outputs omit it.
    "time_seg_session_win_rate_spread",
    # Task 3 (Round 55, Gamma): cross-window drawdown trend slope — optional; pre-Round-55 outputs omit it.
    "drawdown_trend_slope",
    # Task 1 (Round 56, Alpha): sector diversification score — optional; pre-Round-56 outputs omit it.
    "diversification_score",
    # Task 2 (Round 56, Beta): score rank IC — optional; pre-Round-56 outputs omit it.
    "rank_ic",
    # Task 3 (Round 56, Gamma): cross-window mean-IC trend slope — optional; pre-Round-56 outputs omit it.
    "ic_trend_slope",
    # Task 1 (Round 57, Alpha): market regime adaptability — optional; pre-Round-57 outputs omit it.
    "regime_adaptability",
    # Task 2 (Round 57, Beta): turnover efficiency — optional; field absent when float_turnover_rate missing.
    "turnover_efficiency",
    # Task 3 (Round 57, Gamma): cross-window rank-IC trend slope — optional; pre-Round-57 outputs omit it.
    "rank_ic_trend_slope",
    # Task 1 (Round 58, Alpha): optimal entry threshold win rate — optional; pre-Round-58 outputs omit it.
    "optimal_win_rate",
    # Task 2 (Round 58, Beta): total factor explained variance — optional; pre-Round-58 outputs omit it.
    "total_explained_variance",
    # Task 3 (Round 58, Gamma): cross-window regime adaptability trend slope — optional; pre-Round-58 outputs omit it.
    "regime_trend_slope",
    # Task 1 (Round 59, Alpha): return distribution skewness — optional; pre-Round-59 outputs omit it.
    "skewness",
    # Task 2 (Round 59, Beta): composite quality score — optional; pre-Round-59 outputs omit it.
    "composite_quality_score",
    # Task 3 (Round 59, Gamma): cross-window threshold win-rate trend slope — optional; pre-Round-59 outputs omit it.
    "threshold_win_rate_trend_slope",
    # Task 1 (Round 60, Alpha): multi-signal consistency lift — optional; pre-Round-60 outputs omit it.
    "signal_consistency_lift",
    # Task 2 (Round 60, Beta): T+1 holding period win rate — optional; pre-Round-60 outputs omit it.
    "t1_win_rate",
    # Task 3 (Round 60, Gamma): composite quality score cross-window trend slope — optional; pre-Round-60 outputs omit it.
    "quality_score_trend_slope",
    # Task 1 (Round 61, Alpha): concentration risk — optional; pre-Round-61 surfaces omit it.
    "concentration_risk",
    # Task 2 (Round 61, Beta): extreme market resilience score — optional; pre-Round-61 surfaces omit it.
    "resilience_score",
    # Task 3 (Round 61, Gamma): signal consistency trend slope — optional; pre-Round-61 outputs omit it.
    "consistency_trend_slope",
    # Task 1 (Round 62, Alpha): low-liquidity fraction — optional; pre-Round-62 surfaces omit it.
    "low_liquidity_pct",
    # Task 2 (Round 62, Beta): cost-adjusted profit factor — optional; pre-Round-62 surfaces omit it.
    "cost_adjusted_profit_factor",
    # Task 3 (Round 62, Gamma): cross-window resilience trend slope — optional; pre-Round-62 outputs omit it.
    "resilience_trend_slope",
    # Task 1 (Round 63, Alpha): best sl/tp profit factor — optional; pre-Round-63 surfaces omit it.
    "best_profit_factor",
    # Task 2 (Round 63, Beta): best factor-combination win rate — optional; pre-Round-63 surfaces omit it.
    "best_combo_win_rate",
    # Task 3 (Round 63, Gamma): cross-window cost-adjusted PF trend slope — optional; pre-Round-63 outputs omit it.
    "cost_pf_trend_slope",
    # Task 3 (Round 64, Gamma): cross-window combo win rate trend slope — optional; pre-Round-64 outputs omit it.
    "combo_win_rate_trend_slope",
    # Task 1 (Round 64, Alpha): adaptive weight effective factor count — optional; pre-Round-64 outputs omit it.
    "adaptive_weight_effective_factor_count",
    # Task 2 (Round 64, Beta): IC stability — optional; pre-Round-64 outputs omit it.
    "ic_stability",
    # Task 1 (Round 65, Alpha): total return attribution — optional; pre-Round-65 outputs omit it.
    "total_attribution",
    # Task 2 (Round 65, Beta): multi-timeframe consistency score — optional; pre-Round-65 outputs omit it.
    "timeframe_consistency",
    # Task 3 (Round 65, Gamma): IC stability trend slope — optional; pre-Round-65 outputs omit it.
    "ic_stability_trend_slope",
    # Task 1 (Round 66, Alpha): volatility regime edge — optional; pre-Round-66 surfaces omit it.
    "vol_regime_edge",
    # Task 2 (Round 66, Beta): mean nonlinear interaction effect — optional; pre-Round-66 surfaces omit it.
    "interact_mean_interaction_effect",
    # Task 3 (Round 66, Gamma): attribution trend slope — optional; pre-Round-66 outputs omit it.
    "attribution_trend_slope",
    # Task 1 (Round 67, Alpha): score dispersion win-rate spread — optional; pre-Round-67 outputs omit it.
    "score_win_rate_spread",
    # Task 2 (Round 67, Beta): fund flow breakout synergy — optional; pre-Round-67 outputs omit it.
    "flow_breakout_synergy",
    # Task 3 (Round 67, Gamma): interaction trend slope — optional; pre-Round-67 outputs omit it.
    "interaction_trend_slope",
    # Task 1 (Round 68, Alpha): tail filter effect — optional; pre-Round-68 outputs omit it.
    "tail_filter_effect",
    # Task 2 (Round 68, Beta): position sector HHI — optional; pre-Round-68 outputs omit it.
    "sector_hhi",
    # Task 3 (Round 68, Gamma): score dispersion trend slope — optional; pre-Round-68 outputs omit it.
    "dispersion_trend_slope",
    # Task 1 (Round 69, Alpha): RS ranking spread — optional; pre-Round-69 outputs omit it.
    "rs_rank_spread",
    # Task 2 (Round 69, Beta): turnover filter effect — optional; pre-Round-69 outputs omit it.
    "turnover_filter_effect",
    # Task 3 (Round 69, Gamma): concentration HHI trend slope — optional; pre-Round-69 outputs omit it.
    "concentration_hhi_slope",
    # Task 1 (Round 70, Alpha): price position win-rate spread — optional; pre-Round-70 outputs omit it.
    "cs_win_rate_spread",
    # Task 2 (Round 70, Beta): win/loss streak ratio — optional; pre-Round-70 outputs omit it.
    "streak_ratio",
    # Task 3 (Round 70, Gamma): RS rank trend slope — optional; pre-Round-70 outputs omit it.
    "rs_rank_trend_slope",
    # Task 1 (Round 71, Alpha): momentum win spread — optional; pre-Round-71 outputs omit it.
    "momentum_win_spread",
    # Task 2 (Round 71, Beta): volume structure spread — optional; pre-Round-71 outputs omit it.
    "vol_structure_spread",
    # Task 3 (Round 71, Gamma): price position trend slope — optional; pre-Round-71 outputs omit it.
    "price_pos_trend_slope",
    # Task 1 (Round 72, Alpha): multi-factor Z-score win-rate spread — optional; pre-Round-72 outputs omit it.
    "zscore_win_spread",
    # Task 2 (Round 72, Beta): return persistence score — optional; pre-Round-72 outputs omit it.
    "persistence_score",
    # Task 3 (Round 72, Gamma): momentum rank trend slope — optional; pre-Round-72 outputs omit it.
    "momentum_rank_trend_slope",
    # Task 1 (Round 73, Alpha): market breadth win rate — optional; pre-Round-73 outputs omit it.
    "breadth_win_rate",
    # Task 2 (Round 73, Beta): factor IC consistency ratio — optional; pre-Round-73 outputs omit it.
    "ic_consistency_ratio",
    # Task 3 (Round 73, Gamma): Z-score win-spread cross-window trend slope — optional; pre-Round-73 outputs omit it.
    "zscore_trend_slope",
    # Task 1 (Round 74, Alpha): signal strength stratification spread — optional; pre-Round-74 outputs omit it.
    "stratification_spread",
    # Task 2 (Round 74, Beta): conditional momentum synergy edge — optional; pre-Round-74 outputs omit it.
    "conditional_momentum_edge",
    # Task 3 (Round 74, Gamma): market breadth win-rate cross-window trend slope — optional; pre-Round-74 outputs omit it.
    "breadth_trend_slope",
    # Task 1 (Round 75, Alpha): simplified Sharpe ratio — optional; pre-Round-75 outputs omit it.
    "sharpe_ratio",
    # Task 2 (Round 75, Beta): max factor collinearity — optional; pre-Round-75 outputs omit it.
    "max_collinearity",
    # Task 3 (Round 75, Gamma): stratification spread cross-window trend slope — optional; pre-Round-75 outputs omit it.
    "stratification_trend_slope",
    # Task 1 (Round 76, Alpha): gain/loss ratio — optional; pre-Round-76 outputs omit it.
    "gain_loss_ratio",
    # Task 1 (Round 76, Alpha): tail asymmetry score — optional; pre-Round-76 outputs omit it.
    "tail_asymmetry_score",
    # Task 2 (Round 76, Beta): factor orthogonality score — optional; pre-Round-76 outputs omit it.
    "orthogonality_score",
    # Task 1 (Round 77, Alpha): adaptive threshold lift — optional; pre-Round-77 outputs omit it.
    "threshold_lift",
    # Task 2 (Round 77, Beta): sector win-rate dispersion — optional; pre-Round-77 outputs omit it.
    "sector_win_rate_dispersion",
    # Task 3 (Round 77, Gamma): cross-window skew trend slope — optional; pre-Round-77 outputs omit it.
    "skew_trend_slope",
    # Task 3 (Round 78, Gamma): cross-window threshold lift trend slope — optional; pre-Round-78 outputs omit it.
    "threshold_lift_trend_slope",
    # Task 1 (Round 78, Alpha): hotstock win-rate edge — optional; pre-Round-78 outputs omit it.
    "hotstock_edge",
    # Task 2 (Round 78, Beta): factor robustness ratio — optional; pre-Round-78 outputs omit it.
    "robustness_ratio",
    # Task 1 (Round 79, Alpha): score quintile monotonicity — optional; pre-Round-79 outputs omit these.
    "sq_consist_quintile_monotonicity_score",
    "sq_consist_quintile_top_bottom_spread",
    # Task 2 (Round 79, Beta): entry quality filter — optional; pre-Round-79 outputs omit these.
    "entry_qual_high_quality_entry_win_rate",
    "entry_qual_quality_entry_edge",
    # Task 3 (Round 79, Gamma): cross-window robustness trend slope — optional; pre-Round-79 outputs omit it.
    "robustness_trend_slope",
    # Task 1 (Round 80, Alpha): return quantile lift — optional; pre-Round-80 outputs omit these.
    "ret_qlift_median_return_lift",
    "ret_qlift_top_median_return",
    # Task 2 (Round 80, Beta): near-high stock analysis — optional; pre-Round-80 outputs omit these.
    "nh_near_high_win_rate",
    "nh_near_high_edge",
    # Task 3 (Round 80, Gamma): cross-window entry quality trend slope — optional; pre-Round-80 outputs omit it.
    "entry_quality_trend_slope",
    # Task 1 (Round 81, Alpha): expected value analysis — optional; pre-Round-81 outputs omit these.
    "ev_top_ev",
    "ev_ev_spread",
    # Task 2 (Round 81, Beta): high inflow premium — optional; pre-Round-81 outputs omit these.
    "hi_inflow_high_inflow_win_rate",
    "hi_inflow_high_inflow_edge",
    # Task 3 (Round 81, Gamma): cross-window near-high trend slope — optional; pre-Round-81 outputs omit it.
    "near_high_trend_slope",
    # Task 1 (Round 82, Alpha): score prediction accuracy metrics — optional; pre-Round-82 surfaces omit these.
    "clf_high_score_precision",
    "clf_f1_score",
    # Task 2 (Round 82, Beta): volume-price divergence metrics — optional; pre-Round-82 surfaces omit these.
    "vpd_full_confirm_win_rate",
    "vpd_divergence_penalty",
    # Task 3 (Round 82, Gamma): EV spread trend slope — optional; pre-Round-82 outputs omit it.
    "ev_spread_trend_slope",
    # Task 1 (Round 83, Alpha): Kelly criterion metrics — optional; pre-Round-83 surfaces omit these.
    "kelly_top_kelly",
    "kelly_kelly_spread",
    # Task 2 (Round 83, Beta): return percentile profile metrics — optional; pre-Round-83 surfaces omit these.
    "rpp_top_return_p75",
    "rpp_upside_asymmetry",
    # Task 3 (Round 83, Gamma): precision trend slope — optional; pre-Round-83 outputs omit it.
    "precision_trend_slope",
    # Task 1 (Round 84, Alpha): momentum reversal metrics — optional; pre-Round-84 surfaces omit these.
    "mom_rev_extreme_momentum_win_rate",
    "mom_rev_momentum_breadth_effect",
    # Task 2 (Round 84, Beta): sector tailwind protection metrics — optional; pre-Round-84 surfaces omit these.
    "tailwind_protected_win_rate",
    "tailwind_gap_protection_effect",
    # Task 3 (Round 84, Gamma): upside asymmetry trend slope — optional; pre-Round-84 outputs omit it.
    "upside_asymmetry_trend_slope",
    # Task 1 (Round 85, Alpha): batch consistency metrics — optional; pre-Round-85 surfaces omit these.
    "batch_batch_consistency_score",
    "batch_batch3_win_rate",
    # Task 2 (Round 85, Beta): liquidity weighted return metrics — optional; pre-Round-85 surfaces omit these.
    "liq_lw_win_rate",
    "liq_liquidity_bias",
    # Task 3 (Round 85, Gamma): momentum reversal trend slope — optional; pre-Round-85 outputs omit it.
    "momentum_reversal_trend_slope",
    # Task 1 (Round 86, Alpha): factor IC consistency metrics — optional; pre-Round-86 surfaces omit these.
    "frc_positive_ic_count",
    "frc_mean_factor_ic",
    "frc_factor_ic_consistency_ratio",
    # Task 2 (Round 86, Beta): breakout quality premium metrics — optional; pre-Round-86 surfaces omit these.
    "bq_high_breakout_win_rate",
    "bq_breakout_premium_edge",
    "bq_high_breakout_avg_return",
    # Task 3 (Round 86, Gamma): batch consistency trend slope — optional; pre-Round-86 outputs omit it.
    "batch_consistency_trend_slope",
    # Task 1 (Round 87, Alpha): regime adaptive win rate metrics — optional; pre-Round-87 surfaces omit these.
    "regime_high_regime_win_rate",
    "regime_low_regime_win_rate",
    "regime_regime_spread",
    "regime_regime_stability",
    # Task 2 (Round 87, Beta): consecutive signal quality metrics — optional; pre-Round-87 surfaces omit these.
    "sig_top_signal_win_rate",
    "sig_bot_signal_win_rate",
    "sig_signal_persistence_edge",
    "sig_top_signal_count",
    # Task 3 (Round 87, Gamma): regime spread cross-window trend slope — optional; pre-Round-87 outputs omit it.
    "regime_spread_trend_slope",
    # Task 1 (Round 88, Alpha): volume-price divergence metrics — optional; pre-Round-88 surfaces omit these.
    "vp_volume_return_alignment",
    "vp_high_vol_win_rate",
    "vp_volume_premium_edge",
    "vp_high_vol_count",
    # Task 2 (Round 88, Beta): entry timing quality metrics — optional; pre-Round-88 surfaces omit these.
    "et_high_inflow_win_rate",
    "et_low_inflow_win_rate",
    "et_inflow_timing_edge",
    "et_high_inflow_avg_return",
    # Task 3 (Round 88, Gamma): signal quality cross-window trend — optional; pre-Round-88 outputs omit these.
    "signal_quality_trend_slope",
    "signal_quality_trend_grade",
    "signal_quality_trend_n",
    # Task 1 (Round 89, Alpha): open-gap intraday persistence metrics — optional; pre-Round-89 surfaces omit these.
    "ogp_gap_vs_full_day_ic",
    "ogp_high_gap_win_rate",
    "ogp_low_gap_win_rate",
    "ogp_gap_win_rate_premium",
    "ogp_high_gap_avg_return",
    "ogp_high_gap_count",
    # Task 2 (Round 89, Beta): tail flow quality metrics — optional; pre-Round-89 surfaces omit these.
    "tf_composite_win_rate_premium",
    "tf_high_flow_win_rate",
    "tf_low_flow_win_rate",
    "tf_high_flow_avg_return",
    "tf_high_flow_count",
    # Task 3 (Round 89, Gamma): momentum IC consistency cross-window metrics — optional; pre-Round-89 outputs omit these.
    "mc_momentum_ic",
    "mc_high_mom_win_rate",
    "mc_low_mom_win_rate",
    "mc_momentum_win_rate_premium",
    "mc_high_mom_avg_return",
    "mc_sample_count",
    "mc_ic_consistency_score",
    "mc_ic_positive_window_count",
    "mc_ic_total_window_count",
    "mc_ic_gate_passed",
    "mc_ic_mean",
    "ogp_trend_slope",
    "ogp_trend_grade",
    "ogp_trend_n",
    "tf_trend_slope",
    "tf_trend_grade",
    "tf_trend_n",
})
COMPARISON_METRIC_EPSILON: dict[str, float] = {
    "next_close_positive_rate": 0.0,
    "next_high_hit_rate": 0.0,
    "next_close_expectancy": 0.0,
    "downside_p10": 0.002,
    "window_coverage": 0.002,
    "projected_theme_exposure": 0.005,
    "incremental_theme_exposure": 0.005,
    "liquidity_capacity_raw_100": 1.0,
    "crowding_risk_raw_100": 1.0,
    "gap_risk_raw_100": 1.0,
    "max_future_high_return_2_5d_hit_rate_at_20pct": 0.01,
    "time_to_hit_20pct_median": 0.1,
    "runner_capture_count": 1.0,
    "runner_escape_rate": 0.01,
    "avg_composite_score_escaped": 0.01,
    "t_plus_2_close_positive_rate": 0.0,
    "t_plus_2_close_payoff_ratio": 0.01,
    "t_plus_3_close_positive_rate": 0.0,
    "t_plus_3_close_expectancy": 0.0,
    "t_plus_3_close_payoff_ratio": 0.01,
    # Task 1 (Round 11)
    "ic_positive_factor_fraction": 0.01,
    "candidate_pool_avg_composite_score": 0.01,
    # Task 1 (Round 12)
    "t_plus_1_intraday_drawdown_p10": 0.002,
    # Task 4 (Round 15): stop-loss trigger rates — 0.5 % tolerance
    "stop_loss_trigger_rate_2pct": 0.005,
    "stop_loss_trigger_rate_3pct": 0.005,
    "stop_loss_trigger_rate_5pct": 0.005,
    # Task 5 (Round 15): cross-day autocorrelation — 1 % tolerance
    "cross_day_autocorr_t1_vs_t2": 0.01,
    "cross_day_autocorr_t2_vs_t3": 0.01,
    # Task 2 (Round 15): gap continuation rate — 1 % tolerance
    "gap_continuation_rate": 0.01,
    # Task 2 (Round 16): volume-price divergence rate — 1 % tolerance
    "volume_price_divergence_rate": 0.01,
    # Task 3 (Round 16): predicted range p75 — 0.5 % tolerance
    "predicted_range_pct_p75": 0.005,
    # Task 3 (Round 16): high-volatility warning rate — 1 % tolerance
    "high_volatility_warning_rate": 0.01,
    # Task 1 (Round 20, Beta): realized payoff ratio — 1 % tolerance
    "realized_payoff_ratio": 0.01,
    # Task 2 (Round 20, Alpha): score-conditioned metrics — 0.5 % tolerance each
    "high_confidence_selection_rate": 0.005,
    "score_weighted_win_rate": 0.005,
    "score_win_rate_lift": 0.005,
    "high_confidence_win_rate": 0.005,
    # Task 3 (Round 20, Gamma): limit-up risk statistics — 1 % tolerance each
    "consecutive_limit_up_rate": 0.01,
    "limit_up_win_rate": 0.01,
    "non_limit_up_win_rate": 0.01,
    # Task 3 (Round 21, Beta): execution timing signal — 1 % tolerance each
    "open_entry_signal_strength": 0.01,
    "execution_timing_confidence": 0.01,
    # Task 2 (Round 22, Alpha): multi-day hold period metrics — 1 % tolerance
    "t1_vs_t2_sharpe_diff": 0.01,
    "hold_period_confidence": 0.01,
    # Task 3 (Round 22, Beta): score position tier metrics — 0.5 % tolerance
    "tier_win_rate_spread": 0.005,
    "tier_monotone_win_rate": 0.0,
    # Task 2 (Round 23, Alpha): Kelly fraction — 0.5 % tolerance
    "kelly_fraction_half": 0.005,
    "kelly_positive": 0.0,
    # Task 3 (Round 23, Beta): regime consistency — 0.5 % tolerance
    "regime_consistency_score": 0.005,
    "regime_robustness_flag": 0.0,
    # Task 1 (Round 24): IC temporal trend — tolerance of 1 decaying factor
    "decaying_factor_count": 1.0,
    # Task 2 (Round 24): drawdown-adjusted Kelly — 0.5 % tolerance
    "kelly_fraction_drawdown_adjusted": 0.005,
    "drawdown_adjustment_factor": 0.005,
    # Task 3 (Round 24): verdict calibration score — 1 % tolerance; monotone flag is exact
    "verdict_calibration_score": 0.01,
    "verdict_monotone": 0.0,
    # Task 1 (Round 25, Gamma): profile health score — 1.0 point tolerance
    "profile_health_score": 1.0,
    # Task 2 (Round 25, Beta): window volatility / trend — 0.5 % tolerance
    "win_rate_window_volatility": 0.005,
    "win_rate_window_trend": 0.005,
    # Task 1 (Round 27, Alpha): return distribution shape — 1 % tolerance for skewness, 0.5 % for ratio
    "next_close_return_skewness": 0.01,
    "win_loss_std_ratio": 0.005,
    # Task 2 (Round 27, Gamma): score discrimination index — 0.5 % tolerance
    "score_discrimination_index": 0.005,
    # Task 3 (Round 27, Beta): max positions — exact integer comparison; 0 tolerance
    "recommended_max_positions": 0.0,
    # Task 1 (Round 31, Alpha): return autocorrelation — 1 % tolerance
    "autocorr_lag1": 0.01,
    # Task 2 (Round 31, Gamma): score CV across windows — 0.5 % tolerance
    "score_cv_across_windows": 0.005,
    # Task 1 (Round 32, Gamma): conditional tail-risk metrics
    "score_tail_separation": 0.005,
    "tail_risk_asymmetry": 0.01,
    "high_score_cvar_5pct": 0.002,
    # Task 2 (Round 32, Alpha): volume anomaly metrics — 0.5 % tolerance
    "extreme_volume_win_rate_premium": 0.005,
    "inflow_win_rate_premium": 0.005,
    # Task 3 (Round 32, Beta): composite gate score — 1.0 point tolerance
    "composite_gate_score": 1.0,
}


def resolve_replay_input_paths(
    *,
    input_paths: list[str] | None,
    reports_root: str | Path | None,
    weekly_start_date: str | None,
    weekly_end_date: str | None,
) -> list[Path]:
    if input_paths:
        return [Path(path).expanduser().resolve() for path in input_paths]
    if not reports_root or not weekly_start_date or not weekly_end_date:
        raise ValueError("Provide --input or --reports-root with --weekly-start-date and --weekly-end-date")

    analysis = analyze_btst_weekly_validation(
        reports_root,
        start_date=weekly_start_date,
        end_date=weekly_end_date,
    )
    missing_trade_dates = list(analysis.get("missing_trade_dates") or [])
    if missing_trade_dates:
        raise ValueError(f"missing_trade_dates={missing_trade_dates}")

    replay_input_paths: list[Path] = []
    for row in list(analysis.get("selected_reports") or []):
        replay_input_path = Path(str(row["report_dir"])) / "selection_artifacts" / str(row["trade_date"]) / "selection_target_replay_input.json"
        if replay_input_path.exists():
            replay_input_paths.append(replay_input_path.resolve())
    if not replay_input_paths:
        raise FileNotFoundError("No replay inputs found for the requested weekly window")
    return replay_input_paths


def _build_default_checkpoint_path(
    *,
    profile: str,
    objective: str,
    replay_input_paths: list[Path] | None = None,
    walk_forward_descriptor: str | None = None,
) -> str:
    descriptor_parts = [f"profile={profile}", f"objective={objective}"]
    if replay_input_paths:
        resolved_paths = sorted(str(path.expanduser().resolve()) for path in replay_input_paths)
        descriptor_parts.append("mode=replay")
        descriptor_parts.extend(resolved_paths)
    else:
        descriptor_parts.append("mode=walk_forward")
        descriptor_parts.append(walk_forward_descriptor or "")
    digest = hashlib.sha1("||".join(descriptor_parts).encode("utf-8")).hexdigest()[:12]
    return str(REPORTS_DIR / f"param_search_{profile}_{digest}_checkpoint.json")


def _parse_grid_params(raw: list[str]) -> dict[str, list[Any]]:
    def _parse_scalar(value: str) -> Any:
        stripped = value.strip()
        lowered = stripped.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if "." in stripped:
            try:
                return float(stripped)
            except ValueError:
                return stripped
        if stripped.isdigit():
            return int(stripped)
        return stripped

    grid: dict[str, list[Any]] = {}
    for item in raw:
        if "=" in item:
            key, values_str = item.split("=", 1)
            values = [_parse_scalar(v) for v in values_str.split(",")]
            grid[key.strip()] = values
        else:
            try:
                with open(item) as f:
                    grid = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                logger.error("Cannot parse grid param: %s (use key=val1,val2 or path/to.json)", item)
                sys.exit(1)
    return grid


def _normalize_guardrail_spec(spec: GuardrailSpec) -> dict[str, float]:
    if isinstance(spec, dict):
        normalized: dict[str, float] = {}
        if spec.get("min") is not None:
            normalized["min"] = float(spec["min"])
        if spec.get("max") is not None:
            normalized["max"] = float(spec["max"])
        if not normalized:
            raise ValueError("Guardrail spec dict must contain min and/or max")
        return normalized
    return {"min": float(spec)}


def _parse_guardrails(raw: list[str]) -> dict[str, GuardrailSpec]:
    guardrails: dict[str, GuardrailSpec] = {}
    for item in raw:
        operator = None
        if "<=" in item:
            key, raw_value = item.split("<=", 1)
            operator = "max"
        elif ">=" in item:
            key, raw_value = item.split(">=", 1)
            operator = "min"
        elif "=" in item:
            key, raw_value = item.split("=", 1)
            operator = "legacy_min"
        else:
            raise ValueError(f"Invalid guardrail {item!r}; expected metric=floor, metric>=floor, or metric<=cap")
        value = _safe_float(raw_value)
        if value is None:
            raise ValueError(f"Invalid guardrail floor for {key!r}: {raw_value!r}")
        normalized_key = key.strip()
        if operator == "legacy_min":
            guardrails[normalized_key] = float(value)
            continue
        existing = guardrails.get(normalized_key)
        merged = _normalize_guardrail_spec(existing) if existing is not None else {}
        merged[operator] = float(value)
        guardrails[normalized_key] = merged
    return guardrails


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_recency_decay(window_date_str: str, reference_date_str: str, half_life_days: int = RECENCY_HALF_LIFE_DAYS) -> float:
    """Return an exponential recency decay factor in [RECENCY_DECAY_MIN_FACTOR, 1.0].

    Windows dated close to ``reference_date_str`` receive a factor near 1.0; windows
    dated ``half_life_days`` before the reference receive ~0.5; older windows are
    floored at ``RECENCY_DECAY_MIN_FACTOR`` so they are never fully discarded.

    Args:
        window_date_str: ISO-format date string for this window (YYYY-MM-DD).
        reference_date_str: ISO-format date string for the most-recent window.
        half_life_days: Number of calendar days that halves the decay factor.

    Returns:
        Decay factor in [RECENCY_DECAY_MIN_FACTOR, 1.0].
    """
    try:
        window_dt = datetime.strptime(window_date_str, "%Y-%m-%d")
        reference_dt = datetime.strptime(reference_date_str, "%Y-%m-%d")
        days_lag = max(0, (reference_dt - window_dt).days)
    except (ValueError, TypeError):
        return 1.0
    decay = math.exp(-math.log(2.0) * days_lag / max(1, half_life_days))
    return max(RECENCY_DECAY_MIN_FACTOR, round(decay, 6))


def _build_recency_decay_map(input_paths: list[Path], half_life_days: int = RECENCY_HALF_LIFE_DAYS) -> dict[str, float]:
    """Pre-scan ``input_paths`` to derive per-window recency decay factors.

    The date is extracted from ``path.parent.name`` which follows the naming
    convention ``…/selection_artifacts/YYYY-MM-DD/selection_target_replay_input.json``.
    Paths whose parent name cannot be parsed as a date receive factor 1.0.

    Args:
        input_paths: List of replay input file paths.
        half_life_days: Number of calendar days after which the decay factor reaches ~0.5.
            Defaults to ``RECENCY_HALF_LIFE_DAYS``.  Exposed as a parameter so the optimizer
            can pre-compute maps for all ``RECENCY_HALF_LIFE_CANDIDATES`` simultaneously
            (Task 4, Round 10).

    Returns:
        Dict mapping ``str(input_path)`` to the recency decay factor in
        [RECENCY_DECAY_MIN_FACTOR, 1.0].
    """
    date_by_path: dict[str, str] = {}
    for p in input_paths:
        candidate = p.parent.name  # expected "YYYY-MM-DD"
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
            date_by_path[str(p)] = candidate
        except ValueError:
            date_by_path[str(p)] = ""
    valid_dates = [d for d in date_by_path.values() if d]
    if not valid_dates:
        return {str(p): 1.0 for p in input_paths}
    reference_date = max(valid_dates)
    return {str(p): (_compute_recency_decay(date_by_path[str(p)], reference_date, half_life_days=half_life_days) if date_by_path[str(p)] else 1.0) for p in input_paths}


def _format_guardrail_spec(spec: GuardrailSpec) -> str:
    if isinstance(spec, dict):
        parts: list[str] = []
        if spec.get("min") is not None:
            parts.append(f"min={float(spec['min'])}")
        if spec.get("max") is not None:
            parts.append(f"max={float(spec['max'])}")
        return ", ".join(parts)
    return str(float(spec))


def resolve_guardrails(
    *,
    profile_name: str,
    objective: str,
    replay_mode: bool,
    raw_guardrails: list[str],
) -> dict[str, GuardrailSpec]:
    resolved: dict[str, GuardrailSpec] = {}
    if replay_mode and profile_name == "momentum_optimized" and objective == SearchObjective.BTST.value:
        resolved.update(DEFAULT_BTST_REPLAY_GUARDRAILS)
    if replay_mode and profile_name == "momentum_optimized" and objective == SearchObjective.BTST_RUNNER.value:
        resolved.update(DEFAULT_BTST_RUNNER_REPLAY_GUARDRAILS)
    resolved.update(_parse_guardrails(raw_guardrails))
    return resolved


def _resolve_distribution_stat(surface: dict[str, Any], distribution_key: str, stat_key: str) -> float | None:
    distribution = dict(surface.get(distribution_key) or {})
    return _safe_float(distribution.get(stat_key))


def _extract_committee_component_metric(row: dict[str, Any], metric_key: str) -> float | None:
    metrics_payload = dict(row.get("metrics_payload") or {})
    committee_payload = dict(metrics_payload.get("committee") or {})
    committee_components = dict(committee_payload.get("components") or {})
    component_value = _safe_float(committee_components.get(metric_key))
    if component_value is not None:
        return component_value
    return _safe_float(metrics_payload.get(metric_key))


def _resolve_scope_rows(rows: list[dict[str, Any]], *, primary_scope: str) -> list[dict[str, Any]]:
    allowed_decisions = {"selected"} if primary_scope == "selected" else {"selected", "near_miss"}
    return [dict(row or {}) for row in rows if str(row.get("decision") or "").strip() in allowed_decisions]


def _average_scope_metric(rows: list[dict[str, Any]], metric_key: str) -> float | None:
    numeric_values = [
        float(value)
        for value in (_extract_committee_component_metric(row, metric_key) for row in rows)
        if value is not None
    ]
    if not numeric_values:
        return None
    return sum(numeric_values) / len(numeric_values)


def _resolve_primary_surface(
    *,
    selected_surface: dict[str, Any],
    tradeable_surface: dict[str, Any],
    min_selected_next_day_count: int = 6,
    min_selected_closed_cycle_count: int = 3,
) -> tuple[dict[str, Any], str]:
    selected_next_day_count = int(selected_surface.get("next_day_available_count") or 0)
    selected_closed_cycle_count = int(selected_surface.get("closed_cycle_count") or 0)
    if selected_next_day_count >= min_selected_next_day_count and selected_closed_cycle_count >= min_selected_closed_cycle_count:
        return selected_surface, "selected"
    return tradeable_surface, "tradeable_fallback"


def _compute_source_coverage_pass_ratio(source_coverage_summaries: list[dict[str, Any]]) -> float:
    """Compute high-quality (exact_tick) source fraction across tracked source fields.

    Args:
        source_coverage_summaries: List of source_coverage_summary dicts from replay windows.

    Returns:
        Fraction of tracked source slots covered by exact_tick (0.0 if no data).
    """
    _TRACKED_FIELDS = [
        "flow_60_source_counts",
        "persist_120_source_counts",
        "close_support_30_source_counts",
        "committee_component_sources_counts",
    ]
    _STRONG_SOURCE = "exact_tick"
    strong_total = 0
    grand_total = 0
    for summary in source_coverage_summaries:
        for field in _TRACKED_FIELDS:
            field_counts = dict(summary.get(field) or {})
            for source, count in field_counts.items():
                grand_total += int(count)
                if source == _STRONG_SOURCE:
                    strong_total += int(count)
    if grand_total == 0:
        return 0.0
    return float(strong_total) / float(grand_total)


# ---------------------------------------------------------------------------
# Round 33, Task 3 (Beta): Factor IC trend — cross-window analysis
# ---------------------------------------------------------------------------
# Tracks the OLS slope of each factor's IC series across replay windows to
# detect systematic IC decay.  A high fraction of declining ICs signals that
# the scoring factors are losing predictive power over time.


def compute_factor_ic_trend(all_windows_summaries: list[dict]) -> dict:
    """Compute per-factor IC trend slopes across replay windows.

    Accepts the list of per-window surface summaries collected during an
    evaluator run.  For each factor whose IC appears in ≥ 3 windows the
    function fits a linear (OLS) slope of IC vs window index, normalised by
    the maximum absolute IC value so that slopes from different factors are
    comparable.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts (one
            per replay window, as appended to ``all_primary_surfaces``).  Each
            dict may contain ``factor_ic_mean`` **or** ``factor_ic_next_close``
            (the production key written by ``build_surface_summary``).

    Returns:
        Dict with keys:

        - ``ic_trend_stability``: float | None — fraction of factors NOT in IC
          decline; 1.0 = all stable, 0.0 = all declining.
        - ``factor_ic_trend_deteriorating``: bool | None — True when > 50 % of
          factors have a declining IC trend.
        - ``declining_factors``: list[str] — names of factors with slope < −0.05.
        - ``ic_trend_slopes``: dict[str, float] — per-factor normalised OLS slope.

        Returns ``{"ic_trend_stability": None, "factor_ic_trend_deteriorating": None}``
        when fewer than 3 windows are available or no IC data is found.
    """
    _EMPTY_IC_TREND: dict[str, Any] = {"ic_trend_stability": None, "factor_ic_trend_deteriorating": None}
    if len(all_windows_summaries) < 3:
        return _EMPTY_IC_TREND

    # Collect (window_index, ic_value) per factor across all windows.
    factor_series: dict[str, list[tuple[int, float]]] = {}
    for idx, surf in enumerate(all_windows_summaries):
        ic_mean: dict = surf.get("factor_ic_mean") or surf.get("factor_ic_next_close") or {}
        for factor, val in ic_mean.items():
            if val is None:
                continue
            try:
                factor_series.setdefault(factor, []).append((idx, float(val)))
            except (TypeError, ValueError):
                pass

    if not factor_series:
        return _EMPTY_IC_TREND

    ic_trend_slopes: dict[str, float] = {}
    for factor, data_pts in factor_series.items():
        if len(data_pts) < 3:
            continue
        xs = [x for x, _ in data_pts]
        ys = [y for _, y in data_pts]
        n = len(xs)
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        ss_xx = sum((x - x_mean) ** 2 for x in xs)
        if ss_xx == 0.0:
            continue
        raw_slope = ss_xy / ss_xx
        max_abs = max(abs(y) for y in ys)
        normalised_slope = raw_slope / max(max_abs, 1e-6)
        ic_trend_slopes[factor] = round(normalised_slope, 6)

    if not ic_trend_slopes:
        return _EMPTY_IC_TREND

    total_factors = len(ic_trend_slopes)
    declining_factors = [f for f, s in ic_trend_slopes.items() if s < -0.05]
    ic_trend_stability = round(1.0 - len(declining_factors) / total_factors, 4)
    factor_ic_trend_deteriorating = len(declining_factors) / total_factors > 0.5

    return {
        "ic_trend_stability": ic_trend_stability,
        "factor_ic_trend_deteriorating": factor_ic_trend_deteriorating,
        "declining_factors": declining_factors,
        "ic_trend_slopes": ic_trend_slopes,
    }


# ---------------------------------------------------------------------------
# Round 34, Task 3 (Beta): Signal churn metrics — cross-window candidate-pool stability
# ---------------------------------------------------------------------------
# Tracks how much the candidate pool changes between consecutive replay windows.
# High churn rate signals an unstable selection system with high real-money friction.


def compute_quality_trend_analysis(all_windows_summaries: list[dict]) -> dict:
    """Track quality-metric improvement trends across replay windows.

    Fits an OLS slope to each of four quality indicators across window indices
    and reports what fraction of those slopes are positive (improving).  A score
    ≥ 0.5 means at least half the tracked metrics have been getting better over
    time, which supports confidence in the strategy's continuing improvement.

    Args:
        all_windows_summaries: List of per-window surface summary dicts (output of
            ``build_surface_summary``).  Each dict may optionally contain
            ``win_rate``, ``expected_value_per_trade``, ``composite_gate_score``,
            and ``sortino_ratio``.

    Returns:
        Dict with keys:

        - ``quality_trend_improving``: bool|None — True when ≥ 50 % of tracked
          metrics show a positive OLS slope; None when fewer than 3 windows.
        - ``quality_trend_score``: float|None — fraction of improving slopes ∈
          [0, 1]; None when data insufficient.
        - ``quality_trend_grade``: str|None — 'A'(≥0.75)/'B'(≥0.50)/'C'(≥0.25)/'D'(<0.25).
    """
    _null: dict = {"quality_trend_improving": None, "quality_trend_score": None, "quality_trend_grade": None}
    if len(all_windows_summaries) < 3:
        return _null

    _metric_keys = ["win_rate", "expected_value_per_trade", "composite_gate_score", "sortino_ratio"]
    slopes: list[float] = []
    for key in _metric_keys:
        raw_vals = [s.get(key) for s in all_windows_summaries]
        pairs: list[tuple[int, float]] = [(i, float(v)) for i, v in enumerate(raw_vals) if v is not None]
        if len(pairs) < 3:
            continue
        xs = [float(i) for i, _ in pairs]
        ys = [v for _, v in pairs]
        n = len(xs)
        mx = sum(xs) / n
        my = sum(ys) / n
        var_x = sum((x - mx) ** 2 for x in xs)
        cov_xy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        slope = cov_xy / max(var_x, 1e-8)
        normalized_slope = slope / max(abs(my), 1e-8)
        slopes.append(normalized_slope)

    if not slopes:
        return _null

    improving_count = sum(1 for s in slopes if s > 0)
    quality_trend_score = round(improving_count / len(slopes), 4)
    quality_trend_improving = quality_trend_score >= 0.5

    if quality_trend_score >= 0.75:
        quality_trend_grade = "A"
    elif quality_trend_score >= 0.50:
        quality_trend_grade = "B"
    elif quality_trend_score >= 0.25:
        quality_trend_grade = "C"
    else:
        quality_trend_grade = "D"

    return {"quality_trend_improving": quality_trend_improving, "quality_trend_score": quality_trend_score, "quality_trend_grade": quality_trend_grade}


def compute_signal_churn_metrics(all_windows_summaries: list[dict]) -> dict:
    """Compute candidate-pool turnover and top-stock persistence across windows.

    Measures stability of the BTST candidate pool over time by comparing
    consecutive window snapshots.  Two complementary metrics are computed:

    1. **Pool-size churn**: mean absolute fractional change in ``candidate_pool_size``
       between adjacent windows.
    2. **Signal persistence (Jaccard)**: mean Jaccard similarity of ``top_stocks``
       sets between adjacent windows.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts, one entry
            per replay window in chronological order.

    Returns:
        Dict with keys:

        - ``signal_churn_rate``: float|None — 1 − avg Jaccard similarity.
        - ``avg_signal_persistence``: float|None — mean Jaccard similarity.
        - ``avg_pool_size_churn``: float|None — mean fractional pool-size change.
        - ``pool_stable``: bool|None — True when pool is reliably stable.

        Returns all-None dict when fewer than 3 windows are provided.
    """
    _EMPTY: dict[str, Any] = {
        "signal_churn_rate": None,
        "avg_signal_persistence": None,
        "avg_pool_size_churn": None,
        "pool_stable": None,
    }

    if len(all_windows_summaries) < 3:
        return _EMPTY

    # Pool-size churn.
    size_changes: list[float] = []
    for i in range(1, len(all_windows_summaries)):
        prev_size = all_windows_summaries[i - 1].get("candidate_pool_size")
        curr_size = all_windows_summaries[i].get("candidate_pool_size")
        if prev_size is None or curr_size is None:
            continue
        try:
            change = abs(float(curr_size) - float(prev_size)) / max(float(prev_size), 1.0)
            size_changes.append(change)
        except (TypeError, ValueError):
            continue

    avg_pool_size_churn: float | None = round(sum(size_changes) / len(size_changes), 4) if size_changes else None

    # Jaccard similarity of top-stocks sets.
    jaccard_vals: list[float] = []
    for i in range(1, len(all_windows_summaries)):
        prev_stocks = all_windows_summaries[i - 1].get("top_stocks")
        curr_stocks = all_windows_summaries[i].get("top_stocks")
        if not prev_stocks or not curr_stocks:
            continue
        try:
            set_prev = set(prev_stocks)
            set_curr = set(curr_stocks)
            union_size = len(set_prev | set_curr)
            if union_size == 0:
                continue
            jaccard_vals.append(len(set_prev & set_curr) / union_size)
        except (TypeError, ValueError):
            continue

    avg_signal_persistence: float | None = round(sum(jaccard_vals) / len(jaccard_vals), 4) if len(jaccard_vals) >= 1 else None
    signal_churn_rate: float | None = round(1.0 - avg_signal_persistence, 4) if avg_signal_persistence is not None else None

    pool_stable: bool | None
    if avg_pool_size_churn is None:
        pool_stable = None
    else:
        pool_stable = avg_pool_size_churn < 0.30 and (avg_signal_persistence is None or avg_signal_persistence > 0.40)

    return {
        "signal_churn_rate": signal_churn_rate,
        "avg_signal_persistence": avg_signal_persistence,
        "avg_pool_size_churn": avg_pool_size_churn,
        "pool_stable": pool_stable,
    }


# ---------------------------------------------------------------------------
# Round 40, Task 3 (Gamma): Cross-window factor exposure drift analysis
# ---------------------------------------------------------------------------
# Tracks how much the key per-window metrics drift across replay windows.
# A high mean coefficient-of-variation (CV) signals regime-sensitive factors or
# an unstable strategy surface.  Registers factor_drift_score with a cap of 0.50.


def compute_cross_window_factor_exposure(all_windows_summaries: list[dict]) -> dict:
    """Measure cross-window stability of key surface metrics via mean coefficient-of-variation.

    Extracts 4 core metrics (win_rate / composite_gate_score / sortino_ratio /
    expected_value_per_trade) from each per-window summary and computes the CV
    (std / |mean|) for each series across windows.  The mean CV is reported as
    ``factor_drift_score`` — lower is more stable.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts (one per
            replay window, as appended to ``all_primary_surfaces``).

    Returns:
        Dict with keys:

        - ``factor_exposure_stable`` (bool | None): True when mean CV < 0.30.
        - ``factor_drift_score`` (float | None): mean CV across valid metric series.
        - ``most_drifting_metric`` (str | None): metric with highest CV.
        - ``least_drifting_metric`` (str | None): metric with lowest CV.
        - ``metric_cv_map`` (dict[str, float]): per-metric CV values.

        Returns ``{"factor_exposure_stable": None, "factor_drift_score": None}``
        when fewer than 3 windows are available.
    """
    _null: dict = {"factor_exposure_stable": None, "factor_drift_score": None, "most_drifting_metric": None, "least_drifting_metric": None, "metric_cv_map": {}}
    if len(all_windows_summaries) < 3:
        return _null

    _TRACKED_METRICS = ["win_rate", "composite_gate_score", "sortino_ratio", "expected_value_per_trade"]

    metric_cv_map: dict[str, float] = {}
    for key in _TRACKED_METRICS:
        vals = [float(s[key]) for s in all_windows_summaries if s.get(key) is not None]
        if len(vals) < 3:
            continue
        n = len(vals)
        mean_val = sum(vals) / n
        variance = sum((v - mean_val) ** 2 for v in vals) / max(n - 1, 1)
        std_val = variance ** 0.5
        cv = std_val / max(abs(mean_val), 1e-8)
        metric_cv_map[key] = round(cv, 6)

    if not metric_cv_map:
        return _null

    factor_drift_score = round(sum(metric_cv_map.values()) / max(len(metric_cv_map), 1), 6)
    factor_exposure_stable = factor_drift_score < 0.30
    most_drifting_metric = max(metric_cv_map, key=lambda k: metric_cv_map[k])
    least_drifting_metric = min(metric_cv_map, key=lambda k: metric_cv_map[k])

    return {
        "factor_exposure_stable": factor_exposure_stable,
        "factor_drift_score": factor_drift_score,
        "most_drifting_metric": most_drifting_metric,
        "least_drifting_metric": least_drifting_metric,
        "metric_cv_map": metric_cv_map,
    }


# ---------------------------------------------------------------------------
# Round 41, Task 1 (Alpha): Factor IC rank consistency across replay windows
# ---------------------------------------------------------------------------
# Tracks whether the same factors persistently rank at the top across windows —
# a healthy factor system shows stable factor rankings over time.


def compute_factor_rank_consistency(all_windows_summaries: list[dict]) -> dict:
    """Measure how consistently the same factors rank at the top across replay windows.

    Extracts the ``factor_ic_ranking`` field from each window summary and computes
    the coefficient of variation (CV) of each factor's rank position across windows.
    A low mean CV indicates the factor hierarchy is stable; persistent top-3 occupants
    signal a healthy, non-degenerate factor system.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts (one per
            replay window, as appended to ``all_primary_surfaces``).  Each dict may
            contain ``factor_ic_ranking``: list of (factor_name, ic_value) pairs,
            sorted highest-IC first.

    Returns:
        Dict with keys:

        - ``factor_rank_consistency_score`` (float | None): 1 − mean(CV) clamped [0, 1];
          higher = more consistent ranking.
        - ``top_factor_stable`` (bool | None): True when ≥ 2 factors appear in the top-3
          in more than 50 % of valid windows.
        - ``most_consistent_factor`` (str | None): factor with lowest rank CV.
        - ``most_volatile_rank_factor`` (str | None): factor with highest rank CV.

        Returns all-None when fewer than 3 windows have valid ``factor_ic_ranking`` data.
    """
    _null: dict = {
        "factor_rank_consistency_score": None,
        "top_factor_stable": None,
        "most_consistent_factor": None,
        "most_volatile_rank_factor": None,
    }
    if len(all_windows_summaries) < 3:
        return _null

    # Collect per-factor rank lists across valid windows
    factor_ranks: dict[str, list[int]] = {}
    top3_window_counts: dict[str, int] = {}
    valid_window_count = 0

    for surf in all_windows_summaries:
        ranking_raw = surf.get("factor_ic_ranking")
        if not ranking_raw:
            continue
        # Accept both list-of-list and list-of-tuple
        ranking: list[tuple[str, float]] = [(str(item[0]), float(item[1])) for item in ranking_raw if len(item) >= 2]
        if not ranking:
            continue
        valid_window_count += 1
        for rank_pos, (factor, _ic) in enumerate(ranking):
            if factor not in factor_ranks:
                factor_ranks[factor] = []
            factor_ranks[factor].append(rank_pos)  # 0-indexed; lower = better
            if rank_pos < 3:
                top3_window_counts[factor] = top3_window_counts.get(factor, 0) + 1

    if valid_window_count < 3:
        return _null

    # Compute rank CV for each factor seen in ≥ 2 windows
    factor_rank_cv: dict[str, float] = {}
    for factor, ranks in factor_ranks.items():
        if len(ranks) < 2:
            continue
        n_r = len(ranks)
        mean_r = sum(ranks) / n_r
        std_r = (sum((r - mean_r) ** 2 for r in ranks) / max(n_r - 1, 1)) ** 0.5
        factor_rank_cv[factor] = std_r / max(mean_r, 1e-8)

    if not factor_rank_cv:
        return _null

    mean_cv = sum(factor_rank_cv.values()) / max(len(factor_rank_cv), 1)
    score = max(0.0, min(1.0, 1.0 - mean_cv))

    # Top-3 stable factors: appear in top-3 in >50% of valid windows
    top_factor_set = {f for f, cnt in top3_window_counts.items() if cnt > valid_window_count * 0.5}
    top_factor_stable = len(top_factor_set) >= 2

    most_consistent = min(factor_rank_cv, key=lambda f: factor_rank_cv[f])
    most_volatile = max(factor_rank_cv, key=lambda f: factor_rank_cv[f])

    return {
        "factor_rank_consistency_score": round(score, 6),
        "top_factor_stable": top_factor_stable,
        "most_consistent_factor": most_consistent,
        "most_volatile_rank_factor": most_volatile,
    }


# ---------------------------------------------------------------------------
# Round 42, Task 3 (Gamma): Cross-window consensus score
# ---------------------------------------------------------------------------
# Counts the fraction of replay windows that simultaneously satisfy ≥ 3 of 4
# core quality conditions.  Multi-window consensus is the strongest signal of
# strategy robustness: a strategy that looks good only in isolated windows is
# likely overfitting.


def compute_window_consensus_score(all_windows_summaries: list[dict]) -> dict:
    """Compute what fraction of replay windows satisfy ≥ 3 of 4 quality conditions.

    For each window checks:

    1. ``win_rate >= 0.55``
    2. ``composite_gate_score >= 60.0``
    3. ``expected_value_per_trade >= 0.005``
    4. ``combined_significance_score >= 0.25``

    A window *passes* when it meets at least 3 of these 4 conditions.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts (one per
            replay window, as appended to ``all_primary_surfaces``).

    Returns:
        Dict with keys:

        - ``consensus_windows_pct`` (float | None): Fraction of windows that pass
          [0, 1].  None when fewer than 3 windows are available.
        - ``strategy_consistently_valid`` (bool | None): True when pct ≥ 0.60.
        - ``consensus_grade`` (str | None): 'A'(≥0.80)/'B'(≥0.60)/'C'(≥0.40)/'D'(<0.40).
        - ``best_consensus_window_idx`` (int | None): Index of the window satisfying
          the most conditions (ties broken by first occurrence).
    """
    _null: dict = {"consensus_windows_pct": None, "strategy_consistently_valid": None, "consensus_grade": None, "best_consensus_window_idx": None}
    if len(all_windows_summaries) < 3:
        return _null

    window_passes: list[bool] = []
    window_condition_counts: list[int] = []
    for surf in all_windows_summaries:
        wr = surf.get("next_close_positive_rate")
        gate = surf.get("composite_gate_score")
        ev = surf.get("expected_value_per_trade")
        sig = surf.get("combined_significance_score")
        cond_wr = (wr is not None and float(wr) >= 0.55)
        cond_gate = (gate is not None and float(gate) >= 60.0)
        cond_ev = (ev is not None and float(ev) >= 0.005)
        cond_sig = (sig is not None and float(sig) >= 0.25)
        count = int(cond_wr) + int(cond_gate) + int(cond_ev) + int(cond_sig)
        window_passes.append(count >= 3)
        window_condition_counts.append(count)

    total = len(window_passes)
    pct = round(sum(window_passes) / max(total, 1), 6)
    valid = pct >= 0.60
    if pct >= 0.80:
        grade = "A"
    elif pct >= 0.60:
        grade = "B"
    elif pct >= 0.40:
        grade = "C"
    else:
        grade = "D"
    best_idx = window_condition_counts.index(max(window_condition_counts))

    return {
        "consensus_windows_pct": pct,
        "strategy_consistently_valid": valid,
        "consensus_grade": grade,
        "best_consensus_window_idx": best_idx,
    }


# ---------------------------------------------------------------------------
# Round 43, Task 3 (Gamma): Score Momentum Trend — 评分动量跨窗趋势
# ---------------------------------------------------------------------------
# Tracks whether candidate_pool_avg_composite_score is trending upward across
# replay windows.  An upward trend indicates the optimizer converges toward
# profiles that surface higher-quality candidates over time.


def compute_score_momentum_trend(all_windows_summaries: list[dict]) -> dict:
    """Compute OLS slope of candidate pool avg composite score across replay windows.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts ordered by
            window index (oldest → newest).

    Returns:
        Dict with keys:

        - ``score_trend_slope`` (float | None): Raw OLS slope of score vs window index.
        - ``score_trend_normalized`` (float | None): Slope / max(|mean(scores)|, 1e-8).
        - ``score_momentum_positive`` (bool | None): True when score_trend_slope > 0.
        - ``score_trend_acceleration`` (float | None): Last score − first score.
        - ``score_trend_grade`` (str | None): 'A'(norm>0.05)/'B'(norm>0)/'C'(norm>-0.05)/'D'.
    """
    _null: dict = {
        "score_trend_slope": None,
        "score_trend_normalized": None,
        "score_momentum_positive": None,
        "score_trend_acceleration": None,
        "score_trend_grade": None,
    }
    if len(all_windows_summaries) < 3:
        return _null

    score_series: list[float] = []
    for surf in all_windows_summaries:
        val = surf.get("candidate_pool_avg_composite_score")
        if val is None:
            continue
        try:
            score_series.append(float(val))
        except (TypeError, ValueError):
            continue

    if len(score_series) < 3:
        return _null

    n = len(score_series)
    x = list(range(n))
    mean_x = sum(x) / n
    mean_y = sum(score_series) / n
    cov_xy = sum((x[i] - mean_x) * (score_series[i] - mean_y) for i in range(n)) / max(n, 1)
    var_x = sum((xi - mean_x) ** 2 for xi in x) / max(n, 1)
    slope = cov_xy / max(var_x, 1e-8)

    norm = slope / max(abs(mean_y), 1e-8)
    accel = score_series[-1] - score_series[0]

    if norm > 0.05:
        grade = "A"
    elif norm > 0.0:
        grade = "B"
    elif norm > -0.05:
        grade = "C"
    else:
        grade = "D"

    return {
        "score_trend_slope": round(slope, 8),
        "score_trend_normalized": round(norm, 6),
        "score_momentum_positive": slope > 0,
        "score_trend_acceleration": round(accel, 6),
        "score_trend_grade": grade,
    }


# Round 44, Task 3 (Gamma): Win-Rate Stability Analysis — 跨窗胜率稳定性
# ---------------------------------------------------------------------------
# Tracks how stable the per-window win rate (next_close_positive_rate) is
# across all replay windows.  High CV indicates the strategy is regime-sensitive
# and the observed win rate may not persist out-of-sample.


def compute_win_rate_stability_analysis(all_windows_summaries: list[dict]) -> dict:
    """Compute descriptive statistics of next_close_positive_rate across replay windows.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts ordered by
            window index (oldest → newest).

    Returns:
        Dict with keys:

        - ``win_rate_mean`` (float | None): Mean win rate across valid windows.
        - ``win_rate_std`` (float | None): Sample std dev (N-1 denominator, N≥2).
        - ``win_rate_cv`` (float | None): Coefficient of variation = std / max(mean, 1e-8).
        - ``win_rate_min`` (float | None): Minimum win rate across windows.
        - ``win_rate_max`` (float | None): Maximum win rate across windows.
        - ``win_rate_range`` (float | None): max − min win rate.
        - ``win_rate_stability_grade`` (str | None): A(cv<0.10)/B(cv<0.20)/C(cv<0.30)/D(cv≥0.30).
        - ``win_rate_stability_valid`` (bool): True when ≥ 3 valid windows.
    """
    _null: dict = {
        "win_rate_mean": None,
        "win_rate_std": None,
        "win_rate_cv": None,
        "win_rate_min": None,
        "win_rate_max": None,
        "win_rate_range": None,
        "win_rate_stability_grade": None,
        "win_rate_stability_valid": False,
    }
    if not all_windows_summaries:
        return _null

    wr_series: list[float] = []
    for surf in all_windows_summaries:
        val = surf.get("win_rate")
        if val is None:
            continue
        try:
            wr_series.append(float(val))
        except (TypeError, ValueError):
            continue

    if len(wr_series) < 3:
        return _null

    n = len(wr_series)
    mean_wr = sum(wr_series) / n
    if n >= 2:
        variance = sum((v - mean_wr) ** 2 for v in wr_series) / (n - 1)
        std_wr: float | None = variance ** 0.5
    else:
        std_wr = None

    cv: float | None = None
    if std_wr is not None:
        cv = round(std_wr / max(mean_wr, 1e-8), 6)

    min_wr = min(wr_series)
    max_wr = max(wr_series)
    range_wr = round(max_wr - min_wr, 6)

    grade: str | None = None
    if cv is not None:
        if cv < 0.10:
            grade = "A"
        elif cv < 0.20:
            grade = "B"
        elif cv < 0.30:
            grade = "C"
        else:
            grade = "D"

    return {
        "win_rate_mean": round(mean_wr, 6),
        "win_rate_std": round(std_wr, 6) if std_wr is not None else None,
        "win_rate_cv": cv,
        "win_rate_min": round(min_wr, 6),
        "win_rate_max": round(max_wr, 6),
        "win_rate_range": range_wr,
        "win_rate_stability_grade": grade,
        "win_rate_stability_valid": True,
    }


# ---------------------------------------------------------------------------
# Task 3 (Round 45, Gamma): Top-Candidate Cross-Window Consistency
# ---------------------------------------------------------------------------
# Measures how consistently the top-quintile (highest-score) candidates achieve
# a win rate ≥ 60 % across all replay windows.  A high consistency rate indicates
# the strategy reliably selects high-conviction winners regardless of market regime.


def compute_top_candidate_consistency(all_windows_summaries: list[dict]) -> dict:
    """Compute cross-window consistency of top-quintile candidate win rates.

    For each window summary, the top-quintile win rate is resolved in priority order:
    1. ``score_bucket_win_rates["Q5"]`` — highest score bucket win rate (preferred).
    2. ``win_rate`` — overall window win rate (fallback).
    Windows providing neither field are skipped.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts ordered by
            window index (oldest → newest).

    Returns:
        Dict with keys:

        - ``top_candidate_consistency_rate`` (float | None): Fraction of windows
          where top win rate ≥ 0.60.  None when < 3 valid windows.
        - ``top_candidate_mean_win_rate`` (float | None): Mean top win rate across windows.
        - ``top_candidate_best_win_rate`` (float | None): Best (max) top win rate seen.
        - ``top_candidate_consistency_grade`` (str | None):
          A(≥0.70) / B(≥0.50) / C(≥0.40) / D(<0.40).  None when < 3 valid windows.
    """
    _null: dict = {
        "top_candidate_consistency_rate": None,
        "top_candidate_mean_win_rate": None,
        "top_candidate_best_win_rate": None,
        "top_candidate_consistency_grade": None,
    }
    if not all_windows_summaries:
        return _null

    top_win_rates: list[float] = []
    for summary in all_windows_summaries:
        sbwr = summary.get("score_bucket_win_rates")
        if isinstance(sbwr, dict) and sbwr.get("Q5") is not None:
            try:
                top_win_rates.append(float(sbwr["Q5"]))
                continue
            except (TypeError, ValueError):
                pass
        wr = summary.get("win_rate")
        if wr is not None:
            try:
                top_win_rates.append(float(wr))
            except (TypeError, ValueError):
                pass

    if len(top_win_rates) < 3:
        return _null

    threshold = 0.60
    above = sum(1 for v in top_win_rates if v >= threshold)
    consistency_rate = round(above / len(top_win_rates), 6)
    mean_wr = round(sum(top_win_rates) / len(top_win_rates), 6)
    best_wr = round(max(top_win_rates), 6)

    if consistency_rate >= 0.70:
        grade = "A"
    elif consistency_rate >= 0.50:
        grade = "B"
    elif consistency_rate >= 0.40:
        grade = "C"
    else:
        grade = "D"

    return {
        "top_candidate_consistency_rate": consistency_rate,
        "top_candidate_mean_win_rate": mean_wr,
        "top_candidate_best_win_rate": best_wr,
        "top_candidate_consistency_grade": grade,
    }


# ---------------------------------------------------------------------------
# Task 3 (Round 46, Gamma): Cross-Window Gate Consistency
# ---------------------------------------------------------------------------
# Measures how stable the fraction of candidates with composite_gate_score ≥ 60
# is across replay windows.  High CV = gate is regime-sensitive.


def compute_cross_window_gate_consistency(all_windows_summaries: list[dict]) -> dict:
    """Compute cross-window stability of gate ≥ 60 candidate fraction.

    For each window summary, the gate-above-threshold fraction is resolved:
    1. ``gate_high_pct`` — preferred if present.
    2. ``composite_gate_score`` — used directly as the gate fraction if present.
    Windows providing neither are skipped.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts.

    Returns:
        Dict with keys:

        - ``gate_above_threshold_mean`` (float | None): Mean across windows.
        - ``gate_above_threshold_std`` (float | None): Std dev (N-1) across windows.
        - ``gate_above_threshold_cv`` (float | None): CV = std / max(mean, 1e-8).
        - ``gate_above_threshold_min`` (float | None): Min across windows.
        - ``gate_above_threshold_max`` (float | None): Max across windows.
        - ``gate_consistency_grade`` (str | None): A(cv<0.10)/B(cv<0.20)/C(cv<0.25)/D(cv≥0.25).
    """
    _null: dict = {
        "gate_above_threshold_mean": None,
        "gate_above_threshold_std": None,
        "gate_above_threshold_cv": None,
        "gate_above_threshold_min": None,
        "gate_above_threshold_max": None,
        "gate_consistency_grade": None,
    }
    if not all_windows_summaries:
        return _null

    gate_vals: list[float] = []
    for summary in all_windows_summaries:
        raw = summary.get("gate_high_pct")
        if raw is None:
            raw = summary.get("composite_gate_score")
        if raw is None:
            continue
        try:
            gate_vals.append(float(raw))
        except (TypeError, ValueError):
            continue

    if len(gate_vals) < 3:
        return _null

    n = len(gate_vals)
    mean_v = sum(gate_vals) / n
    var_v = sum((x - mean_v) ** 2 for x in gate_vals) / (n - 1) if n > 1 else 0.0
    std_v = var_v ** 0.5
    cv_v = std_v / max(mean_v, 1e-8)

    if cv_v < 0.10:
        grade = "A"
    elif cv_v < 0.20:
        grade = "B"
    elif cv_v < 0.25:
        grade = "C"
    else:
        grade = "D"

    return {
        "gate_above_threshold_mean": round(mean_v, 6),
        "gate_above_threshold_std": round(std_v, 6),
        "gate_above_threshold_cv": round(cv_v, 6),
        "gate_above_threshold_min": round(min(gate_vals), 6),
        "gate_above_threshold_max": round(max(gate_vals), 6),
        "gate_consistency_grade": grade,
    }


# ---------------------------------------------------------------------------
# Task 3 (Round 47, Gamma): Cross-Window Factor IC Positive Consistency
# ---------------------------------------------------------------------------
# Aggregates ``factor_ic_values`` dicts across replay windows to compute the
# global positive-IC rate, per-factor mean IC, and consistency statistics.


def compute_factor_ic_consistency(all_windows_summaries: list[dict]) -> dict:
    """Compute cross-window factor IC positive consistency rate.

    For each window summary that contains a ``factor_ic_values`` dict, collect
    per-factor IC values.  Compute the fraction of (factor × window) pairs
    where IC > 0 as the global ``positive_ic_consistency_rate``.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts.  Each
            entry may contain a ``factor_ic_values`` key mapping factor names to
            IC floats.  Windows missing this key are skipped.

    Returns:
        Dict containing:

        - ``positive_ic_consistency_rate`` (float | None): Fraction of all
          (factor × window) pairs where IC > 0.  None if < 3 valid windows.
        - ``consistent_factor_count`` (int | None): Number of factors with
          per-factor positive-IC rate ≥ 0.60.  None if degraded.
        - ``best_factor_name`` (str | None): Factor with the highest mean IC.
        - ``worst_factor_name`` (str | None): Factor with the lowest mean IC.
        - ``factor_ic_consistency_valid`` (bool): True when ≥ 3 valid windows.
    """
    _null: dict = {
        "positive_ic_consistency_rate": None,
        "consistent_factor_count": None,
        "best_factor_name": None,
        "worst_factor_name": None,
        "factor_ic_consistency_valid": False,
    }
    if not all_windows_summaries:
        return _null

    # Collect per-factor IC values across windows that have factor_ic_values.
    factor_ic_map: dict[str, list[float]] = {}
    valid_window_count = 0
    for surf in all_windows_summaries:
        ic_dict = surf.get("factor_ic_values")
        if not isinstance(ic_dict, dict) or not ic_dict:
            continue
        valid_window_count += 1
        for factor_name, ic_val in ic_dict.items():
            if ic_val is None:
                continue
            try:
                fv = float(ic_val)
            except (TypeError, ValueError):
                continue
            if factor_name not in factor_ic_map:
                factor_ic_map[factor_name] = []
            factor_ic_map[factor_name].append(fv)

    if valid_window_count < 3 or not factor_ic_map:
        return _null

    # Global positive-IC rate: count all IC > 0 across every factor × window pair.
    total_pairs = 0
    positive_pairs = 0
    for ic_list in factor_ic_map.values():
        total_pairs += len(ic_list)
        positive_pairs += sum(1 for v in ic_list if v > 0)

    positive_ic_consistency_rate: float | None = None
    if total_pairs > 0:
        positive_ic_consistency_rate = round(positive_pairs / total_pairs, 6)

    # Per-factor mean IC and positive-IC rate.
    factor_mean_ic: dict[str, float] = {}
    factor_positive_ic_rate: dict[str, float] = {}
    for factor_name, ic_list in factor_ic_map.items():
        mean_ic = sum(ic_list) / len(ic_list)
        factor_mean_ic[factor_name] = mean_ic
        factor_positive_ic_rate[factor_name] = sum(1 for v in ic_list if v > 0) / len(ic_list)

    consistent_factor_count = sum(1 for r in factor_positive_ic_rate.values() if r >= 0.60)

    best_factor_name: str | None = None
    worst_factor_name: str | None = None
    if factor_mean_ic:
        best_factor_name = max(factor_mean_ic, key=lambda k: factor_mean_ic[k])
        worst_factor_name = min(factor_mean_ic, key=lambda k: factor_mean_ic[k])

    return {
        "positive_ic_consistency_rate": positive_ic_consistency_rate,
        "consistent_factor_count": consistent_factor_count,
        "best_factor_name": best_factor_name,
        "worst_factor_name": worst_factor_name,
        "factor_ic_consistency_valid": True,
    }


# ---------------------------------------------------------------------------
# Round 48, Task 3 (Gamma): Cross-window Expected-Value Trend
# ---------------------------------------------------------------------------
def compute_cross_window_ev_trend(all_windows_summaries: list[dict]) -> dict:
    """Compute OLS trend of ``expected_value_per_trade`` across replay windows.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts ordered
            by time.  Each entry may contain ``expected_value_per_trade``.

    Returns:
        Dict containing:

        - ``ev_trend_slope`` (float | None): OLS slope; positive = improving.
        - ``ev_trend_normalized`` (float | None): slope / max(abs(mean), 1e-8).
        - ``ev_mean`` (float | None): mean of the EV series.
        - ``ev_std`` (float | None): std (N-1) of the EV series.
        - ``ev_min`` (float | None): minimum EV value.
        - ``ev_max`` (float | None): maximum EV value.
        - ``ev_trend_grade`` (str | None): A/B/C/D grade.
    """
    _null: dict = {
        "ev_trend_slope": None,
        "ev_trend_normalized": None,
        "ev_mean": None,
        "ev_std": None,
        "ev_min": None,
        "ev_max": None,
        "ev_trend_grade": None,
    }
    if not all_windows_summaries:
        return _null

    ev_series: list[float] = []
    for surf in all_windows_summaries:
        val = surf.get("expected_value_per_trade")
        if val is None:
            continue
        try:
            ev_series.append(float(val))
        except (TypeError, ValueError):
            continue

    if len(ev_series) < 3:
        return _null

    n = len(ev_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(ev_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, ev_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0

    mean_y = sum_y / n
    ev_trend_normalized = slope / max(abs(mean_y), 1e-8)

    variance = sum((yi - mean_y) ** 2 for yi in ev_series) / (n - 1) if n > 1 else 0.0
    std_y = variance ** 0.5

    if slope > 0.001:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.05:
        grade = "C"
    else:
        grade = "D"

    return {
        "ev_trend_slope": round(slope, 8),
        "ev_trend_normalized": round(ev_trend_normalized, 8),
        "ev_mean": round(mean_y, 8),
        "ev_std": round(std_y, 8),
        "ev_min": round(min(ev_series), 8),
        "ev_max": round(max(ev_series), 8),
        "ev_trend_grade": grade,
    }


# ---------------------------------------------------------------------------
# Round 49, Task 3 (Gamma): Cross-Window Sortino Trend
# ---------------------------------------------------------------------------
def compute_cross_window_sortino_trend(all_windows_summaries: list[dict]) -> dict:
    """Compute OLS trend slope of ``sortino_ratio`` across replay windows.

    A declining Sortino trend (negative slope) indicates the strategy's
    risk-adjusted returns are deteriorating over time.

    Args:
        all_windows_summaries: List of per-window surface summary dicts, each
            expected to contain a ``sortino_ratio`` key.

    Returns:
        Dict with keys: ``sortino_trend_slope``, ``sortino_mean``, ``sortino_std``,
        ``sortino_trend_grade`` (A/B/C/D), ``sortino_positive_windows_pct``,
        ``sortino_trend_valid``.
    """
    _null: dict = {
        "sortino_trend_slope": None,
        "sortino_mean": None,
        "sortino_std": None,
        "sortino_trend_grade": None,
        "sortino_positive_windows_pct": None,
        "sortino_trend_valid": False,
    }
    if not all_windows_summaries:
        return _null

    sortino_series: list[float] = []
    for s in all_windows_summaries:
        v = s.get("sortino_ratio")
        if v is not None:
            try:
                sortino_series.append(float(v))
            except (TypeError, ValueError):
                pass

    if len(sortino_series) < 3:
        return _null

    n = len(sortino_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(sortino_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, sortino_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0

    mean_val = sum_y / n
    variance = sum((v - mean_val) ** 2 for v in sortino_series) / (n - 1) if n > 1 else 0.0
    std_val = variance ** 0.5

    if slope > 0.10:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.10:
        grade = "C"
    else:
        grade = "D"

    positive_pct = sum(1 for v in sortino_series if v > 0) / n

    return {
        "sortino_trend_slope": round(slope, 8),
        "sortino_mean": round(mean_val, 6),
        "sortino_std": round(std_val, 6),
        "sortino_trend_grade": grade,
        "sortino_positive_windows_pct": round(positive_pct, 6),
        "sortino_trend_valid": True,
    }


# ---------------------------------------------------------------------------
# Round 50, Task 3 (Gamma): Cross-window Sharpe Trend
# ---------------------------------------------------------------------------

def compute_cross_window_sharpe_trend(all_windows_summaries: list[dict]) -> dict:
    """Compute OLS trend slope of ``sharpe_ratio`` across replay windows.

    Complements :func:`compute_cross_window_sortino_trend` — Sharpe includes upside
    volatility while Sortino only penalises downside.  A declining Sharpe trend
    (negative slope) indicates total risk-adjusted returns are deteriorating.

    Round 76 update: collects ``sharpe_sharpe_ratio`` (R75 T1 output) first, then
    falls back to ``sharpe_ratio`` for backward compatibility.

    Args:
        all_windows_summaries: List of per-window surface summary dicts, each
            expected to contain a ``sharpe_sharpe_ratio`` or ``sharpe_ratio`` key.

    Returns:
        Dict with keys: ``sharpe_trend_slope``, ``sharpe_trend_mean``, ``sharpe_mean``,
        ``sharpe_std``, ``sharpe_min``, ``sharpe_max``, ``sharpe_trend_grade`` (A/B/C/D),
        ``sharpe_positive_windows_pct``, ``sharpe_trend_valid``.
    """
    _null: dict = {
        "sharpe_trend_slope": None,
        "sharpe_trend_mean": None,
        "sharpe_mean": None,
        "sharpe_std": None,
        "sharpe_min": None,
        "sharpe_max": None,
        "sharpe_trend_grade": None,
        "sharpe_positive_windows_pct": None,
        "sharpe_trend_valid": False,
    }
    if not all_windows_summaries:
        return _null

    sharpe_series: list[float] = []
    for s in all_windows_summaries:
        v = s.get("sharpe_sharpe_ratio")
        if v is None:
            v = s.get("sharpe_ratio")
        if v is not None:
            try:
                sharpe_series.append(float(v))
            except (TypeError, ValueError):
                pass

    if len(sharpe_series) < 3:
        return _null

    n = len(sharpe_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(sharpe_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, sharpe_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0

    mean_val = sum_y / n
    variance = sum((v - mean_val) ** 2 for v in sharpe_series) / (n - 1) if n > 1 else 0.0
    std_val = variance ** 0.5

    if slope > 0.01:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.02:
        grade = "C"
    else:
        grade = "D"

    positive_pct = sum(1 for v in sharpe_series if v > 0) / n

    return {
        "sharpe_trend_slope": round(slope, 8),
        "sharpe_trend_mean": round(mean_val, 6),
        "sharpe_mean": round(mean_val, 6),
        "sharpe_std": round(std_val, 6),
        "sharpe_min": round(min(sharpe_series), 6),
        "sharpe_max": round(max(sharpe_series), 6),
        "sharpe_trend_grade": grade,
        "sharpe_positive_windows_pct": round(positive_pct, 6),
        "sharpe_trend_valid": True,
    }


# ---------------------------------------------------------------------------
# Round 77, Task 3 (Gamma): Cross-window skew quality gain/loss ratio trend
# ---------------------------------------------------------------------------


def compute_cross_window_skew_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪收益偏斜质量得分（gain_loss_ratio）趋势。"""
    _null: dict = {"skew_trend_valid": False, "skew_trend_slope": None, "skew_trend_mean": None, "skew_favorable_windows_pct": None, "skew_trend_grade": "D"}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("skew_qual_gain_loss_ratio")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    mean_x = (n - 1) / 2.0
    mean_y = sum(vals) / n
    ss_xx = sum((i - mean_x) ** 2 for i in range(n))
    ss_xy = sum((i - mean_x) * (vals[i] - mean_y) for i in range(n))
    slope = ss_xy / ss_xx if ss_xx != 0.0 else 0.0
    skew_favorable_windows_pct = round(sum(1 for v in vals if v > 1.0) / n, 8)
    if slope > 0.01:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.02:
        grade = "C"
    else:
        grade = "D"
    return {"skew_trend_valid": True, "skew_trend_slope": round(slope, 8), "skew_trend_mean": round(mean_y, 6), "skew_favorable_windows_pct": skew_favorable_windows_pct, "skew_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 78, Task 3 (Gamma): Cross-window adaptive threshold lift trend
# ---------------------------------------------------------------------------


def compute_cross_window_threshold_lift_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪自适应阈值提升效果（threshold_lift）趋势。"""
    _null: dict = {"threshold_lift_trend_valid": False, "threshold_lift_trend_slope": None, "threshold_lift_trend_mean": None, "threshold_lift_positive_windows_pct": None, "threshold_lift_trend_grade": "D"}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("adapt_thr_threshold_lift")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    mean_x = (n - 1) / 2.0
    mean_y = sum(vals) / n
    ss_xx = sum((i - mean_x) ** 2 for i in range(n))
    ss_xy = sum((i - mean_x) * (vals[i] - mean_y) for i in range(n))
    slope = ss_xy / ss_xx if ss_xx != 0.0 else 0.0
    threshold_lift_positive_windows_pct = round(sum(1 for v in vals if v > 0) / n, 8)
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"threshold_lift_trend_valid": True, "threshold_lift_trend_slope": round(slope, 8), "threshold_lift_trend_mean": round(mean_y, 6), "threshold_lift_positive_windows_pct": threshold_lift_positive_windows_pct, "threshold_lift_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 79, Task 3 (Gamma): Cross-window factor robustness OLS trend
# ---------------------------------------------------------------------------


def compute_cross_window_robustness_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口因子稳健性趋势：robustness_ratio 的 OLS 时序斜率。"""
    _null: dict = {"valid": False, "robustness_trend_slope": None, "robustness_trend_grade": None, "robustness_window_count": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("robust_robustness_ratio")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    sum_x = n * (n - 1) // 2
    sum_y = sum(vals)
    sum_xy = sum(i * vals[i] for i in range(n))
    sum_x2 = sum(i * i for i in range(n))
    denom = n * sum_x2 - sum_x * sum_x
    slope = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    if slope > 0.01:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"valid": True, "robustness_trend_slope": round(slope, 8), "robustness_trend_grade": grade, "robustness_window_count": n}


# ---------------------------------------------------------------------------
# Round 80, Task 3 (Gamma): Cross-window Entry Quality Trend (入场质量跨窗趋势)
# ---------------------------------------------------------------------------


def compute_cross_window_entry_quality_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口量价共振入场质量趋势：quality_entry_edge 的 OLS 时序斜率。"""
    _null: dict = {"valid": False, "entry_quality_trend_slope": None, "entry_quality_trend_grade": None, "entry_quality_window_count": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("entry_qual_quality_entry_edge")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    sum_x = n * (n - 1) // 2
    sum_y = sum(vals)
    sum_xy = sum(i * vals[i] for i in range(n))
    sum_x2 = sum(i * i for i in range(n))
    denom = n * sum_x2 - sum_x * sum_x
    slope = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"valid": True, "entry_quality_trend_slope": round(slope, 8), "entry_quality_trend_grade": grade, "entry_quality_window_count": n}


# ---------------------------------------------------------------------------
# Round 81, Task 3 (Gamma): Cross-window Near-High Stock Premium Trend
# ---------------------------------------------------------------------------
def compute_cross_window_near_high_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口近高位股溢价趋势：nh_near_high_edge 的 OLS 时序斜率。"""
    _null: dict = {"valid": False, "near_high_trend_slope": None, "near_high_trend_grade": None, "near_high_trend_window_count": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("nh_near_high_edge")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n: int = len(vals)
    sum_x: int = n * (n - 1) // 2
    sum_y: float = sum(vals)
    sum_xy: float = sum(i * vals[i] for i in range(n))
    sum_x2: int = sum(i * i for i in range(n))
    denom: int = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    if slope > 0.005:
        grade: str = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"valid": True, "near_high_trend_slope": round(slope, 8), "near_high_trend_grade": grade, "near_high_trend_window_count": n}


# ---------------------------------------------------------------------------
# Round 82, Task 3 (Gamma): cross-window EV spread trend
# ---------------------------------------------------------------------------
def compute_cross_window_ev_spread_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口高低分组EV差趋势：ev_ev_spread 的 OLS 时序斜率。"""
    EMPTY: dict = {"valid": False, "ev_spread_trend_slope": None, "ev_spread_trend_grade": None, "ev_spread_window_count": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("ev_ev_spread")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
    n: int = len(vals)
    if n < 3:
        return EMPTY
    xs: list[float] = list(range(n))
    sum_x: float = sum(xs)
    sum_y: float = sum(vals)
    sum_xy: float = sum(xs[i] * vals[i] for i in range(n))
    sum_xx: float = sum(x * x for x in xs)
    denom: float = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return EMPTY
    slope: float = (n * sum_xy - sum_x * sum_y) / denom
    grade: str = "A" if slope > 0.005 else ("B" if slope > 0 else ("C" if slope > -0.01 else "D"))
    return {"valid": True, "ev_spread_trend_slope": round(slope, 8), "ev_spread_trend_grade": grade, "ev_spread_window_count": n}


# ---------------------------------------------------------------------------
# Round 83, Task 3 (Gamma): Cross-window Precision Trend
# ---------------------------------------------------------------------------


def compute_cross_window_precision_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口打分精确率趋势：clf_high_score_precision 的 OLS 时序斜率。"""
    EMPTY: dict = {"valid": False, "precision_trend_slope": None, "precision_trend_grade": None, "precision_trend_window_count": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("clf_high_score_precision")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
    n: int = len(vals)
    if n < 3:
        return EMPTY
    xs: list[float] = list(range(n))
    sum_x: float = sum(xs)
    sum_y: float = sum(vals)
    sum_xy: float = sum(xs[i] * vals[i] for i in range(n))
    sum_xx: float = sum(x * x for x in xs)
    denom: float = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return EMPTY
    slope: float = (n * sum_xy - sum_x * sum_y) / denom
    grade: str = "A" if slope > 0.005 else ("B" if slope > 0 else ("C" if slope > -0.01 else "D"))
    return {"valid": True, "precision_trend_slope": round(slope, 8), "precision_trend_grade": grade, "precision_trend_window_count": n}


# ---------------------------------------------------------------------------
# Round 84, Task 3 (Gamma): Cross-window Upside Asymmetry Trend
# ---------------------------------------------------------------------------


def compute_cross_window_upside_asymmetry_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口上行不对称性趋势：rpp_upside_asymmetry 的 OLS 时序斜率。"""
    EMPTY: dict = {"valid": False, "upside_asymmetry_trend_slope": None, "upside_asymmetry_trend_grade": None, "upside_asymmetry_window_count": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("rpp_upside_asymmetry")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
    n: int = len(vals)
    if n < 3:
        return EMPTY
    xs: list[float] = list(range(n))
    sum_x: float = sum(xs)
    sum_y: float = sum(vals)
    sum_xy: float = sum(xs[i] * vals[i] for i in range(n))
    sum_xx: float = sum(x * x for x in xs)
    denom: float = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return EMPTY
    slope: float = (n * sum_xy - sum_x * sum_y) / denom
    grade: str = "A" if slope > 0.005 else ("B" if slope > 0 else ("C" if slope > -0.01 else "D"))
    return {"valid": True, "upside_asymmetry_trend_slope": round(slope, 8), "upside_asymmetry_trend_grade": grade, "upside_asymmetry_window_count": n}


# ---------------------------------------------------------------------------
# Round 85, Task 3 (Gamma): Cross-window momentum reversal trend
# ---------------------------------------------------------------------------


def compute_cross_window_momentum_reversal_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口动量广度效应趋势：mom_rev_momentum_breadth_effect 的 OLS 时序斜率。"""
    EMPTY: dict = {"valid": False, "momentum_reversal_trend_slope": None, "momentum_reversal_trend_grade": None, "momentum_reversal_window_count": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("mom_rev_momentum_breadth_effect")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
    n: int = len(vals)
    if n < 3:
        return EMPTY
    xs: list[float] = list(range(n))
    sum_x: float = sum(xs)
    sum_y: float = sum(vals)
    sum_xy: float = sum(xs[i] * vals[i] for i in range(n))
    sum_xx: float = sum(x * x for x in xs)
    denom: float = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return EMPTY
    slope: float = (n * sum_xy - sum_x * sum_y) / denom
    grade: str = "A" if slope > 0.005 else ("B" if slope > 0 else ("C" if slope > -0.01 else "D"))
    return {"valid": True, "momentum_reversal_trend_slope": round(slope, 8), "momentum_reversal_trend_grade": grade, "momentum_reversal_window_count": n}
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Round 87, Task 3 (Gamma): Cross-window regime spread trend
# ---------------------------------------------------------------------------


def compute_cross_window_regime_spread_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口机制差值趋势：regime_regime_spread 的 OLS 时序斜率。"""
    EMPTY: dict = {"valid": False, "regime_spread_trend_slope": None, "regime_spread_trend_grade": None, "regime_spread_trend_window_count": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("regime_regime_spread")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
    n: int = len(vals)
    if n < 3:
        return EMPTY
    xs: list[float] = list(range(n))
    sum_x: float = sum(xs)
    sum_y: float = sum(vals)
    sum_xy: float = sum(xs[i] * vals[i] for i in range(n))
    sum_xx: float = sum(x * x for x in xs)
    denom: float = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return EMPTY
    slope: float = (n * sum_xy - sum_x * sum_y) / denom
    grade: str = "A" if slope > 0.005 else ("B" if slope > 0 else ("C" if slope > -0.01 else "D"))
    return {"valid": True, "regime_spread_trend_slope": round(slope, 8), "regime_spread_trend_grade": grade, "regime_spread_trend_window_count": n}


# ---------------------------------------------------------------------------
# Round 88, Task 3 (Gamma): Cross-window signal quality trend
# ---------------------------------------------------------------------------


def compute_cross_window_signal_quality_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口信号质量趋势：sig_signal_persistence_edge 的 OLS 时序斜率。"""
    EMPTY: dict = {"valid": False, "signal_quality_trend_slope": None, "signal_quality_trend_grade": None, "signal_quality_trend_n": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("sig_signal_persistence_edge")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
    n: int = len(vals)
    if n < 3:
        return EMPTY
    xs: list[float] = list(range(n))
    sum_x: float = sum(xs)
    sum_y: float = sum(vals)
    sum_xy: float = sum(xs[i] * vals[i] for i in range(n))
    sum_xx: float = sum(x * x for x in xs)
    denom: float = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return EMPTY
    slope: float = (n * sum_xy - sum_x * sum_y) / denom
    grade: str = "A" if slope > 0.005 else ("B" if slope > 0 else ("C" if slope > -0.01 else "D"))
    return {"valid": True, "signal_quality_trend_slope": round(slope, 8), "signal_quality_trend_grade": grade, "signal_quality_trend_n": n}


# ---------------------------------------------------------------------------
# Round 89, Task 1 (Alpha): Cross-window open-gap persistence OLS trend
# ---------------------------------------------------------------------------


def compute_cross_window_open_gap_persistence_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口开盘跳空延续性趋势：ogp_gap_win_rate_premium 的 OLS 时序斜率。

    Tracks the OLS slope of ``ogp_gap_win_rate_premium`` across replay windows.
    A positive slope indicates the gap-up → full-day-continuation premium is
    widening over time; a negative slope signals deterioration.

    Args:
        all_windows_summaries: List of per-window surface dicts ordered
            chronologically.  Each dict should carry ``ogp_gap_win_rate_premium``
            produced by ``compute_open_gap_intraday_persistence``.

    Returns:
        Dict with keys ``valid``, ``ogp_trend_slope``, ``ogp_trend_grade``,
        ``ogp_trend_n``.
    """
    EMPTY: dict = {"valid": False, "ogp_trend_slope": None, "ogp_trend_grade": None, "ogp_trend_n": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("ogp_gap_win_rate_premium")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
    n: int = len(vals)
    if n < 3:
        return EMPTY
    xs: list[float] = list(range(n))
    sum_x: float = sum(xs)
    sum_y: float = sum(vals)
    sum_xy: float = sum(xs[i] * vals[i] for i in range(n))
    sum_xx: float = sum(x * x for x in xs)
    denom: float = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return EMPTY
    slope: float = (n * sum_xy - sum_x * sum_y) / denom
    grade: str = "A" if slope > 0.005 else ("B" if slope > 0 else ("C" if slope > -0.01 else "D"))
    return {"valid": True, "ogp_trend_slope": round(slope, 8), "ogp_trend_grade": grade, "ogp_trend_n": n}


# ---------------------------------------------------------------------------
# Round 89, Task 2 (Beta): Cross-window tail flow quality OLS trend
# ---------------------------------------------------------------------------


def compute_cross_window_tail_flow_quality_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口尾盘资金质量趋势：tf_composite_win_rate_premium 的 OLS 时序斜率。

    Tracks the OLS slope of ``tf_composite_win_rate_premium`` across replay
    windows.  A positive slope means the tail-flow composite signal is gaining
    predictive power over time; negative slope signals degradation.

    Args:
        all_windows_summaries: List of per-window surface dicts ordered
            chronologically.  Each dict should carry
            ``tf_composite_win_rate_premium`` produced by
            ``compute_tail_flow_quality_score``.

    Returns:
        Dict with keys ``valid``, ``tf_trend_slope``, ``tf_trend_grade``,
        ``tf_trend_n``.
    """
    EMPTY: dict = {"valid": False, "tf_trend_slope": None, "tf_trend_grade": None, "tf_trend_n": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("tf_composite_win_rate_premium")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
    n: int = len(vals)
    if n < 3:
        return EMPTY
    xs: list[float] = list(range(n))
    sum_x: float = sum(xs)
    sum_y: float = sum(vals)
    sum_xy: float = sum(xs[i] * vals[i] for i in range(n))
    sum_xx: float = sum(x * x for x in xs)
    denom: float = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return EMPTY
    slope: float = (n * sum_xy - sum_x * sum_y) / denom
    grade: str = "A" if slope > 0.005 else ("B" if slope > 0 else ("C" if slope > -0.01 else "D"))
    return {"valid": True, "tf_trend_slope": round(slope, 8), "tf_trend_grade": grade, "tf_trend_n": n}


# ---------------------------------------------------------------------------
# Round 89, Task 3 (Gamma): Cross-window momentum IC direction consistency
# ---------------------------------------------------------------------------


def compute_cross_window_momentum_ic_consistency(all_windows_summaries: list[dict]) -> dict:
    """跨窗口动量IC方向一致性：检验mc_momentum_ic在多个窗口的方向稳定性。

    Counts how many of the available windows have a positive
    ``mc_momentum_ic`` (Spearman IC of ``momentum_confirmation_score`` vs
    T+1 return > 0).  A consistency rate ≥ 0.60 (i.e. ≥ 3 of 5 windows
    positive) indicates the momentum factor provides a reliably directional
    signal.

    The ``mc_ic_consistency_score`` is a 0–1 metric equal to the fraction of
    windows with positive IC; ``mc_ic_gate_passed`` is True when ≥ 3 of the
    last 5 windows (or ≥ 60 % overall) are positive.

    Args:
        all_windows_summaries: List of per-window surface dicts ordered
            chronologically.

    Returns:
        Dict with keys ``valid``, ``mc_ic_consistency_score``,
        ``mc_ic_positive_window_count``, ``mc_ic_total_window_count``,
        ``mc_ic_gate_passed``, ``mc_ic_mean``.
    """
    EMPTY: dict = {
        "valid": False,
        "mc_ic_consistency_score": None,
        "mc_ic_positive_window_count": None,
        "mc_ic_total_window_count": None,
        "mc_ic_gate_passed": None,
        "mc_ic_mean": None,
    }
    ic_vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("mc_momentum_ic")
        if v is not None:
            try:
                ic_vals.append(float(v))
            except (TypeError, ValueError):
                continue
    n: int = len(ic_vals)
    if n < 3:
        return EMPTY
    positive_count: int = sum(1 for v in ic_vals if v > 0)
    consistency_score: float = round(positive_count / n, 8)
    ic_mean: float = round(sum(ic_vals) / n, 8)
    # Gate: ≥ 60 % of windows OR ≥ 3 of last 5 have positive IC
    last5: list[float] = ic_vals[-5:]
    last5_positive: int = sum(1 for v in last5 if v > 0)
    gate_passed: bool = (consistency_score >= 0.60) or (len(last5) >= 5 and last5_positive >= 3)
    return {
        "valid": True,
        "mc_ic_consistency_score": consistency_score,
        "mc_ic_positive_window_count": positive_count,
        "mc_ic_total_window_count": n,
        "mc_ic_gate_passed": gate_passed,
        "mc_ic_mean": ic_mean,
    }


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Round 86, Task 3 (Gamma): Cross-window batch consistency trend
# ---------------------------------------------------------------------------


def compute_cross_window_batch_consistency_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口批次一致性趋势：batch_batch_consistency_score 的 OLS 时序斜率。"""
    EMPTY: dict = {"valid": False, "batch_consistency_trend_slope": None, "batch_consistency_trend_grade": None, "batch_consistency_trend_window_count": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("batch_batch_consistency_score")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
    n: int = len(vals)
    if n < 3:
        return EMPTY
    xs: list[float] = list(range(n))
    sum_x: float = sum(xs)
    sum_y: float = sum(vals)
    sum_xy: float = sum(xs[i] * vals[i] for i in range(n))
    sum_xx: float = sum(x * x for x in xs)
    denom: float = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return EMPTY
    slope: float = (n * sum_xy - sum_x * sum_y) / denom
    grade: str = "A" if slope > 0.005 else ("B" if slope > 0 else ("C" if slope > -0.01 else "D"))
    return {"valid": True, "batch_consistency_trend_slope": round(slope, 8), "batch_consistency_trend_grade": grade, "batch_consistency_trend_window_count": n}


# ---------------------------------------------------------------------------
# Round 52, Task 3 (Gamma): Cross-window Kelly Fraction Trend (跨窗Kelly趋势)
# ---------------------------------------------------------------------------


def compute_cross_window_kelly_trend(all_windows_summaries: list[dict]) -> dict:
    """Track OLS trend of ``kelly_fraction`` across replay windows.

    A positive slope means the strategy's Kelly fraction (positive-edge bet size)
    is improving over time; a negative slope signals deterioration.  A stable
    positive Kelly means the strategy maintains positive expected value consistently.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts (one per
            replay window, ordered chronologically).  Each dict should carry a
            ``kelly_fraction`` value produced by ``compute_win_loss_magnitude_analysis``.

    Returns:
        Dict with keys: ``kelly_trend_slope``, ``kelly_mean``, ``kelly_std``,
        ``kelly_min``, ``kelly_max``, ``kelly_trend_grade``,
        ``kelly_positive_windows_pct``, ``kelly_trend_valid``.
    """
    _null: dict = {
        "kelly_trend_slope": None,
        "kelly_mean": None,
        "kelly_std": None,
        "kelly_min": None,
        "kelly_max": None,
        "kelly_trend_grade": None,
        "kelly_positive_windows_pct": None,
        "kelly_trend_valid": False,
    }
    if not all_windows_summaries:
        return _null

    kelly_series: list[float] = []
    for surf in all_windows_summaries:
        v = surf.get("kelly_fraction")
        if v is not None:
            try:
                kelly_series.append(float(v))
            except (TypeError, ValueError):
                pass

    if len(kelly_series) < 3:
        return _null

    n = len(kelly_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(kelly_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, kelly_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0

    mean_val = sum_y / n
    variance = sum((v - mean_val) ** 2 for v in kelly_series) / (n - 1) if n > 1 else 0.0
    std_val = variance ** 0.5

    if slope > 0.01:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.05:
        grade = "C"
    else:
        grade = "D"

    kelly_positive_pct = round(sum(1 for v in kelly_series if v > 0) / n, 6)

    return {
        "kelly_trend_slope": round(slope, 8),
        "kelly_mean": round(mean_val, 6),
        "kelly_std": round(std_val, 6),
        "kelly_min": round(min(kelly_series), 6),
        "kelly_max": round(max(kelly_series), 6),
        "kelly_trend_grade": grade,
        "kelly_positive_windows_pct": kelly_positive_pct,
        "kelly_trend_valid": True,
    }


# ---------------------------------------------------------------------------
# Round 53, Task 3 (Gamma): cross-window Information Ratio trend
# ---------------------------------------------------------------------------


def compute_cross_window_ir_trend(all_windows_summaries: list[dict]) -> dict:
    """Track OLS trend of ``information_ratio`` across replay windows.

    A positive slope means the strategy's annualised IR is improving over successive
    replay windows; a negative slope signals regime deterioration.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts (one per
            replay window, ordered chronologically).  Each dict should carry an
            ``information_ratio`` value produced by ``compute_information_ratio_analysis``.

    Returns:
        Dict with keys: ``ir_trend_slope``, ``ir_trend_mean``, ``ir_trend_std``,
        ``ir_trend_min``, ``ir_trend_max``, ``ir_trend_grade``,
        ``ir_positive_windows_pct``, ``ir_trend_valid``.
    """
    _null: dict = {
        "ir_trend_slope": None,
        "ir_trend_mean": None,
        "ir_trend_std": None,
        "ir_trend_min": None,
        "ir_trend_max": None,
        "ir_trend_grade": None,
        "ir_positive_windows_pct": None,
        "ir_trend_valid": False,
    }
    if not all_windows_summaries:
        return _null

    ir_series: list[float] = []
    for surf in all_windows_summaries:
        v = surf.get("information_ratio")
        if v is not None:
            try:
                ir_series.append(float(v))
            except (TypeError, ValueError):
                pass

    if len(ir_series) < 3:
        return _null

    n = len(ir_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(ir_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, ir_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0

    mean_val = sum_y / n
    variance = sum((v - mean_val) ** 2 for v in ir_series) / (n - 1) if n > 1 else 0.0
    std_val = variance ** 0.5

    if slope > 0.01:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.05:
        grade = "C"
    else:
        grade = "D"

    ir_positive_pct = round(sum(1 for v in ir_series if v > 0) / n, 6)

    return {
        "ir_trend_slope": round(slope, 8),
        "ir_trend_mean": round(mean_val, 6),
        "ir_trend_std": round(std_val, 6),
        "ir_trend_min": round(min(ir_series), 6),
        "ir_trend_max": round(max(ir_series), 6),
        "ir_trend_grade": grade,
        "ir_positive_windows_pct": ir_positive_pct,
        "ir_trend_valid": True,
    }


# ---------------------------------------------------------------------------
# Round 54, Task 3 (Gamma): Cross-window conditional factor synergy trend
# ---------------------------------------------------------------------------


def compute_cross_window_conditional_trend(all_windows_summaries: list[dict]) -> dict:
    """Track OLS trend of ``conditional_lift`` (conditional factor-synergy) across replay windows.

    A positive slope means the strategy's high-signal vs low-signal win-rate delta is improving; a negative slope signals regime deterioration of factor synergy.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts ordered chronologically.  Each dict should carry a ``conditional_conditional_lift`` value produced by ``compute_conditional_factor_performance``.

    Returns:
        Dict with keys: ``conditional_lift_trend_slope``, ``conditional_lift_trend_mean``, ``conditional_lift_trend_min``, ``conditional_lift_trend_max``, ``conditional_positive_windows_pct``, ``conditional_trend_grade``, ``conditional_lift_trend_valid``.
    """
    _null: dict = {"conditional_lift_trend_slope": None, "conditional_lift_trend_mean": None, "conditional_lift_trend_min": None, "conditional_lift_trend_max": None, "conditional_positive_windows_pct": None, "conditional_trend_grade": None, "conditional_lift_trend_valid": False}
    if not all_windows_summaries:
        return _null
    cl_series: list[float] = []
    for surf in all_windows_summaries:
        v = surf.get("conditional_conditional_lift")
        if v is not None:
            try:
                cl_series.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(cl_series) < 3:
        return _null
    n = len(cl_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(cl_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, cl_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    mean_val = sum_y / n
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    positive_pct = round(sum(1 for v in cl_series if v > 0) / n, 6)
    return {"conditional_lift_trend_slope": round(slope, 8), "conditional_lift_trend_mean": round(mean_val, 6), "conditional_lift_trend_min": round(min(cl_series), 6), "conditional_lift_trend_max": round(max(cl_series), 6), "conditional_positive_windows_pct": positive_pct, "conditional_trend_grade": grade, "conditional_lift_trend_valid": True}


# ---------------------------------------------------------------------------
# Round 55, Task 3 (Gamma): cross-window max-drawdown trend — is drawdown risk improving?
# ---------------------------------------------------------------------------


def compute_cross_window_drawdown_trend(all_windows_summaries: list[dict]) -> dict:
    """Track OLS trend of ``max_drawdown`` across replay windows to assess whether risk is improving.

    A negative slope means drawdown is shrinking over time (improving); a positive slope signals deterioration.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts ordered chronologically.  Each dict should carry a ``drawdown_max_drawdown`` key produced by ``compute_max_drawdown_analysis`` (positive float; 0.05 = 5%).

    Returns:
        Dict with keys: ``drawdown_trend_slope``, ``drawdown_trend_mean``, ``drawdown_trend_min``, ``drawdown_trend_max``, ``drawdown_improving_windows_pct``, ``drawdown_trend_grade``, ``drawdown_trend_valid``.
    """
    _null: dict = {"drawdown_trend_slope": None, "drawdown_trend_mean": None, "drawdown_trend_min": None, "drawdown_trend_max": None, "drawdown_improving_windows_pct": None, "drawdown_trend_grade": None, "drawdown_trend_valid": False}
    if not all_windows_summaries:
        return _null
    dd_series: list[float] = []
    for surf in all_windows_summaries:
        v = surf.get("drawdown_max_drawdown")
        if v is not None:
            try:
                dd_series.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(dd_series) < 3:
        return _null
    n = len(dd_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(dd_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, dd_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    mean_val = sum_y / n
    if n < 2:
        improving_pct = 0.5
    else:
        half = n // 2
        first_half_mean = sum(dd_series[:half]) / half if half > 0 else 0.0
        second_half_mean = sum(dd_series[n - half:]) / half if half > 0 else 0.0
        improving_pct = 1.0 if second_half_mean < first_half_mean else 0.0
    if slope < -0.005:
        grade = "A"
    elif slope < 0:
        grade = "B"
    elif slope < 0.005:
        grade = "C"
    else:
        grade = "D"
    return {"drawdown_trend_slope": round(slope, 8), "drawdown_trend_mean": round(mean_val, 6), "drawdown_trend_min": round(min(dd_series), 6), "drawdown_trend_max": round(max(dd_series), 6), "drawdown_improving_windows_pct": improving_pct, "drawdown_trend_grade": grade, "drawdown_trend_valid": True}


# ---------------------------------------------------------------------------
# Round 56, Task 3 (Gamma): Cross-window mean-IC OLS trend
# ---------------------------------------------------------------------------


def compute_cross_window_ic_trend(all_windows_summaries: list[dict]) -> dict:
    """Track OLS trend of ``decay_mean_ic`` across replay windows.

    A positive slope means the factor set's average Information Coefficient is improving over time;
    a negative slope signals factor predictive-power decay.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts (ordered chronologically).
            Each dict should carry a ``decay_mean_ic`` value produced by ``compute_factor_decay_analysis``
            via ``build_surface_summary``.

    Returns:
        Dict with keys: ``ic_trend_slope``, ``ic_trend_mean``, ``ic_trend_min``,
        ``ic_trend_max``, ``ic_positive_windows_pct``, ``ic_trend_grade``, ``ic_trend_valid``.
    """
    _null: dict = {"ic_trend_slope": None, "ic_trend_mean": None, "ic_trend_min": None, "ic_trend_max": None, "ic_positive_windows_pct": None, "ic_trend_grade": None, "ic_trend_valid": False}
    if not all_windows_summaries:
        return _null
    ic_series: list[float] = []
    for surf in all_windows_summaries:
        v = surf.get("decay_mean_ic")
        if v is not None:
            try:
                ic_series.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(ic_series) < 3:
        return _null
    n = len(ic_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(ic_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, ic_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    mean_val = sum_y / n
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.005:
        grade = "C"
    else:
        grade = "D"
    ic_positive_windows_pct = round(sum(1 for v in ic_series if v > 0) / n, 6)
    return {"ic_trend_slope": round(slope, 8), "ic_trend_mean": round(mean_val, 6), "ic_trend_min": round(min(ic_series), 6), "ic_trend_max": round(max(ic_series), 6), "ic_positive_windows_pct": ic_positive_windows_pct, "ic_trend_grade": grade, "ic_trend_valid": True}


# ---------------------------------------------------------------------------
# Round 57, Task 3 (Gamma): Cross-window rank-IC trend
# ---------------------------------------------------------------------------
# Tracks OLS trend of ``rank_ic`` (Spearman IC between composite score and
# T+1 return) across replay windows.  A positive slope indicates the scoring
# system's predictive validity is improving over time.
# ---------------------------------------------------------------------------


def compute_cross_window_rank_ic_trend(all_windows_summaries: list[dict]) -> dict:
    """Track OLS trend of ``rnkstab_rank_ic`` (rank IC) across replay windows.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts (ordered chronologically).
            Each dict should carry a ``rnkstab_rank_ic`` value produced by ``compute_score_rank_stability``
            via ``build_surface_summary``.

    Returns:
        Dict with keys: ``rank_ic_trend_slope``, ``rank_ic_trend_mean``, ``rank_ic_trend_min``,
        ``rank_ic_trend_max``, ``rank_ic_positive_windows_pct``, ``rank_ic_trend_grade``, ``rank_ic_trend_valid``.
    """
    _null: dict = {"rank_ic_trend_slope": None, "rank_ic_trend_mean": None, "rank_ic_trend_min": None, "rank_ic_trend_max": None, "rank_ic_positive_windows_pct": None, "rank_ic_trend_grade": None, "rank_ic_trend_valid": False}
    if not all_windows_summaries:
        return _null
    rank_ic_series: list[float] = []
    for surf in all_windows_summaries:
        v = surf.get("rnkstab_rank_ic")
        if v is None:
            v = surf.get("rank_rank_ic")
        if v is not None:
            try:
                rank_ic_series.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(rank_ic_series) < 3:
        return _null
    n = len(rank_ic_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(rank_ic_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, rank_ic_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    mean_val = sum_y / n
    if slope > 0.01:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.02:
        grade = "C"
    else:
        grade = "D"
    rank_ic_positive_windows_pct = round(sum(1 for v in rank_ic_series if v > 0) / n, 6)
    return {"rank_ic_trend_slope": round(slope, 8), "rank_ic_trend_mean": round(mean_val, 6), "rank_ic_trend_min": round(min(rank_ic_series), 6), "rank_ic_trend_max": round(max(rank_ic_series), 6), "rank_ic_positive_windows_pct": rank_ic_positive_windows_pct, "rank_ic_trend_grade": grade, "rank_ic_trend_valid": True}


# ---------------------------------------------------------------------------
# Round 58, Task 3 (Gamma): Cross-window regime adaptability trend
# ---------------------------------------------------------------------------
# Tracks OLS trend of ``regime_adaptability`` (min of bull/bear win rates) across
# replay windows.  A positive slope indicates the strategy is becoming more robust
# across market regimes over time.
# ---------------------------------------------------------------------------


def compute_cross_window_regime_trend(all_windows_summaries: list[dict]) -> dict:
    """Track OLS trend of ``regime_adaptability`` across replay windows.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts (ordered chronologically).
            Each dict should carry a ``regime_regime_adaptability`` value produced by
            ``compute_market_regime_adaptation`` via ``build_surface_summary``.

    Returns:
        Dict with keys: ``regime_trend_slope``, ``regime_trend_mean``, ``regime_trend_min``,
        ``regime_trend_max``, ``regime_above_floor_pct``, ``regime_trend_grade``, ``regime_trend_valid``.
    """
    _null: dict = {"regime_trend_slope": None, "regime_trend_mean": None, "regime_trend_min": None, "regime_trend_max": None, "regime_above_floor_pct": None, "regime_trend_grade": None, "regime_trend_valid": False}
    if not all_windows_summaries:
        return _null
    regime_series: list[float] = []
    for surf in all_windows_summaries:
        v = surf.get("regime_regime_adaptability")
        if v is not None:
            try:
                regime_series.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(regime_series) < 3:
        return _null
    n = len(regime_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(regime_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, regime_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    mean_val = sum_y / n
    if slope > 0.01:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.02:
        grade = "C"
    else:
        grade = "D"
    regime_above_floor_pct: float = round(sum(1 for v in regime_series if v >= 0.4) / n, 6)
    return {"regime_trend_slope": round(slope, 8), "regime_trend_mean": round(mean_val, 6), "regime_trend_min": round(min(regime_series), 6), "regime_trend_max": round(max(regime_series), 6), "regime_above_floor_pct": regime_above_floor_pct, "regime_trend_grade": grade, "regime_trend_valid": True}


# ---------------------------------------------------------------------------
# Round 59, Task 3 (Gamma): Cross-window optimal-threshold win-rate trend
# ---------------------------------------------------------------------------
# Tracks OLS trend of ``dyn_thresh_optimal_win_rate`` (best per-percentile entry
# threshold win rate) across replay windows.  A positive slope indicates the
# strategy's entry filter is becoming more effective over time.
# ---------------------------------------------------------------------------


def compute_cross_window_threshold_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪最优阈值胜率趋势"""
    invalid = {"threshold_trend_valid": False, "threshold_win_rate_trend_slope": None, "threshold_win_rate_trend_mean": None, "threshold_win_rate_trend_min": None, "threshold_win_rate_trend_max": None, "threshold_above_floor_pct": None, "threshold_trend_grade": None}
    values = [s.get("dyn_thresh_optimal_win_rate") for s in all_windows_summaries if s.get("dyn_thresh_optimal_win_rate") is not None]
    if len(values) < 3:
        return invalid
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0.0
    above_floor = sum(1 for v in values if v >= 0.5) / n
    if slope > 0.01:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.02:
        grade = "C"
    else:
        grade = "D"
    return {"threshold_trend_valid": True, "threshold_win_rate_trend_slope": slope, "threshold_win_rate_trend_mean": mean_y, "threshold_win_rate_trend_min": min(values), "threshold_win_rate_trend_max": max(values), "threshold_above_floor_pct": above_floor, "threshold_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 60, Task 3 (Gamma): Cross-window composite quality score trend
# ---------------------------------------------------------------------------

def compute_cross_window_quality_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪综合质量评分（composite_quality_score）趋势"""
    invalid = {"quality_trend_valid": False, "quality_score_trend_slope": None, "quality_score_trend_mean": None, "quality_score_trend_min": None, "quality_score_trend_max": None, "quality_above_floor_pct": None, "quality_trend_grade": None}
    values = [float(s["quality_composite_quality_score"]) for s in all_windows_summaries if s.get("quality_composite_quality_score") is not None]
    if len(values) < 3:
        return invalid
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_xy = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    slope = round(ss_xy / ss_xx, 6) if ss_xx > 0 else 0.0
    quality_floor = 40.0
    above_floor = round(sum(1 for v in values if v >= quality_floor) / n, 6)
    if slope > 0.5:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -1.0:
        grade = "C"
    else:
        grade = "D"
    return {"quality_trend_valid": True, "quality_score_trend_slope": slope, "quality_score_trend_mean": round(mean_y, 6), "quality_score_trend_min": min(values), "quality_score_trend_max": max(values), "quality_above_floor_pct": above_floor, "quality_trend_grade": grade}


# ---------------------------------------------------------------------------


def compute_cross_window_profit_factor_trend(all_windows_summaries: list[dict]) -> dict:
    """Track OLS trend of ``profit_factor`` across replay windows.

    A positive slope means the strategy's gross-profit / gross-loss ratio is
    improving over time; a negative slope signals deterioration.

    Args:
        all_windows_summaries: List of per-window surface-summary dicts (one per
            replay window, ordered chronologically).  Each dict should carry a
            ``profit_factor`` value produced by ``compute_profit_factor_analysis``.

    Returns:
        Dict with keys: ``pf_trend_slope``, ``pf_mean``, ``pf_std``, ``pf_min``,
        ``pf_max``, ``pf_trend_grade``, ``pf_above_one_pct``, ``pf_trend_valid``.
    """
    _null: dict = {
        "pf_trend_slope": None,
        "pf_mean": None,
        "pf_std": None,
        "pf_min": None,
        "pf_max": None,
        "pf_trend_grade": None,
        "pf_above_one_pct": None,
        "pf_trend_valid": False,
    }
    if not all_windows_summaries:
        return _null

    pf_series: list[float] = []
    for surf in all_windows_summaries:
        v = surf.get("profit_factor")
        if v is not None:
            try:
                pf_series.append(float(v))
            except (TypeError, ValueError):
                pass

    if len(pf_series) < 3:
        return _null

    n = len(pf_series)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(pf_series)
    sum_xy = sum(xi * yi for xi, yi in zip(x, pf_series))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    slope: float = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0

    mean_val = sum_y / n
    variance = sum((v - mean_val) ** 2 for v in pf_series) / (n - 1) if n > 1 else 0.0
    std_val = variance ** 0.5

    if slope > 0.10:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.10:
        grade = "C"
    else:
        grade = "D"

    pf_above_one_pct = round(sum(1 for v in pf_series if v >= 1.0) / n, 6)

    return {
        "pf_trend_slope": round(slope, 8),
        "pf_mean": round(mean_val, 6),
        "pf_std": round(std_val, 6),
        "pf_min": round(min(pf_series), 6),
        "pf_max": round(max(pf_series), 6),
        "pf_trend_grade": grade,
        "pf_above_one_pct": pf_above_one_pct,
        "pf_trend_valid": True,
    }


def compute_cross_window_consistency_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪多信号一致性提升（signal_consistency_lift）趋势"""
    invalid = {"consistency_trend_valid": False, "consistency_trend_slope": None, "consistency_trend_mean": None, "consistency_trend_min": None, "consistency_trend_max": None, "consistency_positive_windows_pct": None, "consistency_trend_grade": None}
    if not all_windows_summaries:
        return invalid
    values: list[float] = []
    for s in all_windows_summaries:
        v = s.get("sig_consist_signal_consistency_lift")
        if v is not None:
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(values) < 3:
        return invalid
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_xy = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    slope = round(ss_xy / ss_xx, 8) if ss_xx > 0 else 0.0
    positive_pct = round(sum(1 for v in values if v > 0) / n, 6)
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"consistency_trend_valid": True, "consistency_trend_slope": slope, "consistency_trend_mean": round(mean_y, 6), "consistency_trend_min": round(min(values), 6), "consistency_trend_max": round(max(values), 6), "consistency_positive_windows_pct": positive_pct, "consistency_trend_grade": grade}


def compute_cross_window_resilience_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪极端行情韧性（resilience_score）趋势"""
    invalid = {"resilience_trend_valid": False, "resilience_trend_slope": None, "resilience_trend_mean": None, "resilience_trend_min": None, "resilience_trend_max": None, "resilience_above_floor_pct": None, "resilience_trend_grade": None}
    if not all_windows_summaries:
        return invalid
    values: list[float] = []
    for s in all_windows_summaries:
        v = s.get("extreme_resilience_score")
        if v is not None:
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(values) < 3:
        return invalid
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_xy = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    slope = round(ss_xy / ss_xx, 8) if ss_xx > 0 else 0.0
    above_floor_pct = round(sum(1 for v in values if v >= 0.3) / n, 6)
    if slope > 0.01:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.02:
        grade = "C"
    else:
        grade = "D"
    return {"resilience_trend_valid": True, "resilience_trend_slope": slope, "resilience_trend_mean": round(mean_y, 6), "resilience_trend_min": round(min(values), 6), "resilience_trend_max": round(max(values), 6), "resilience_above_floor_pct": above_floor_pct, "resilience_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 63, Task 3 (Gamma): Cross-window cost-adjusted profit factor trend
# ---------------------------------------------------------------------------

def compute_cross_window_cost_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪成本调整盈利因子（cost_adjusted_profit_factor）趋势"""
    invalid = {"cost_pf_trend_valid": False, "cost_pf_trend_slope": None, "cost_pf_trend_mean": None, "cost_pf_trend_min": None, "cost_pf_trend_max": None, "cost_pf_above_floor_pct": None, "cost_pf_trend_grade": None}
    if not all_windows_summaries:
        return invalid
    values: list[float] = []
    for s in all_windows_summaries:
        v = s.get("cost_cost_adjusted_profit_factor")
        if v is not None:
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(values) < 3:
        return invalid
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_xy = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    slope = round(ss_xy / ss_xx, 8) if ss_xx > 0 else 0.0
    above_floor_pct = round(sum(1 for v in values if v >= 1.0) / n, 6)
    if slope > 0.05:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.1:
        grade = "C"
    else:
        grade = "D"
    return {"cost_pf_trend_valid": True, "cost_pf_trend_slope": slope, "cost_pf_trend_mean": round(mean_y, 6), "cost_pf_trend_min": round(min(values), 6), "cost_pf_trend_max": round(max(values), 6), "cost_pf_above_floor_pct": above_floor_pct, "cost_pf_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 64, Task 3 (Gamma): Cross-window best combo win rate trend
# ---------------------------------------------------------------------------

def compute_cross_window_combo_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪最优因子组合胜率（combo_best_combo_win_rate）趋势"""
    vals = [s.get("combo_best_combo_win_rate") for s in all_windows_summaries if s.get("combo_best_combo_win_rate") is not None]
    if len(vals) < 3:
        return {"combo_trend_valid": False, "combo_win_rate_trend_slope": None, "combo_win_rate_trend_mean": None, "combo_win_rate_trend_min": None, "combo_win_rate_trend_max": None, "combo_above_floor_pct": None, "combo_trend_grade": None}
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    min_v = min(vals)
    max_v = max(vals)
    above_floor_pct = sum(1 for v in vals if v >= 0.5) / n
    if slope > 0.01:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.02:
        grade = "C"
    else:
        grade = "D"
    return {"combo_trend_valid": True, "combo_win_rate_trend_slope": slope, "combo_win_rate_trend_mean": mean_v, "combo_win_rate_trend_min": min_v, "combo_win_rate_trend_max": max_v, "combo_above_floor_pct": above_floor_pct, "combo_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 65, Task 3 (Gamma): IC stability validity trend across windows
# ---------------------------------------------------------------------------

def compute_cross_window_validity_trend(all_windows_summaries: list[dict]) -> dict:
    """Track factor validity stability (ic_stability) trend across replay windows.

    Collects ``validity_ic_stability`` from each window summary and fits an OLS slope.
    A more-negative slope indicates ic_stability is *decreasing* over time, meaning the
    factor validity is becoming more stable — which is good (hence LOWER_IS_BETTER).
    """
    vals = [s.get("validity_ic_stability") for s in all_windows_summaries if s.get("validity_ic_stability") is not None]
    if len(vals) < 3:
        return {"ic_stability_trend_valid": False, "ic_stability_trend_slope": None, "ic_stability_trend_mean": None, "ic_stability_trend_min": None, "ic_stability_trend_max": None, "ic_stability_below_cap_pct": None, "ic_stability_trend_grade": None}
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    min_v = min(vals)
    max_v = max(vals)
    ic_stability_below_cap_pct = sum(1 for v in vals if v <= 0.2) / n
    if slope < -0.005:
        grade = "A"
    elif slope < 0:
        grade = "B"
    elif slope < 0.01:
        grade = "C"
    else:
        grade = "D"
    return {"ic_stability_trend_valid": True, "ic_stability_trend_slope": slope, "ic_stability_trend_mean": mean_v, "ic_stability_trend_min": min_v, "ic_stability_trend_max": max_v, "ic_stability_below_cap_pct": ic_stability_below_cap_pct, "ic_stability_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 66, Task 3 (Gamma): Cross-window total attribution trend
# ---------------------------------------------------------------------------

def compute_cross_window_attribution_trend(all_windows_summaries: list[dict]) -> dict:
    """Track OLS trend of ``attr_total_attribution`` (sum of absolute factor ICs) across replay windows.

    A positive slope indicates factor attribution explanatory power is growing over time.
    A strongly negative slope indicates attribution is deteriorating — lower-is-better guardrail
    triggers when slope < -0.02.
    """
    _null: dict = {"attribution_trend_valid": False, "attribution_trend_slope": None, "attribution_trend_mean": None, "attribution_trend_min": None, "attribution_trend_max": None, "attribution_above_floor_pct": None, "attribution_trend_grade": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("attr_total_attribution")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    min_v = min(vals)
    max_v = max(vals)
    attribution_above_floor_pct = round(sum(1 for v in vals if v >= 0.0) / n, 6)
    if slope > 0.02:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.02:
        grade = "C"
    else:
        grade = "D"
    return {"attribution_trend_valid": True, "attribution_trend_slope": round(slope, 8), "attribution_trend_mean": round(mean_v, 6), "attribution_trend_min": round(min_v, 6), "attribution_trend_max": round(max_v, 6), "attribution_above_floor_pct": attribution_above_floor_pct, "attribution_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 67, Task 3 (Gamma): Cross-window nonlinear interaction trend
# ---------------------------------------------------------------------------


def compute_cross_window_interaction_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪非线性因子交互效应（mean_interaction_effect）OLS趋势。

    从各窗口 summary 收集 ``interact_mean_interaction_effect``（Round 66 T2 输出），需≥3个有效值。
    Returns:
        - ``interaction_trend_slope``: OLS 斜率
        - ``interaction_trend_mean``: 均值
        - ``interaction_positive_windows_pct``: mean_interaction_effect > 0 的窗口占比
        - ``interaction_trend_grade``: A/B/C/D
        - ``interaction_trend_valid``: bool
    """
    _null: dict = {"interaction_trend_valid": False, "interaction_trend_slope": None, "interaction_trend_mean": None, "interaction_positive_windows_pct": None, "interaction_trend_grade": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("interact_mean_interaction_effect")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    interaction_positive_windows_pct = round(sum(1 for v in vals if v > 0) / n, 6)
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"interaction_trend_valid": True, "interaction_trend_slope": round(slope, 8), "interaction_trend_mean": round(mean_v, 6), "interaction_positive_windows_pct": interaction_positive_windows_pct, "interaction_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 68, Task 3 (Gamma): Cross-window score dispersion trend
# ---------------------------------------------------------------------------


def compute_cross_window_dispersion_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪得分离散区分度（score_win_rate_spread）趋势。

    从各窗口 summary 收集 ``dispersion_score_win_rate_spread``（Round 67 T1 的输出），需≥3个有效值。
    Returns:
        - ``dispersion_trend_slope``: OLS 斜率
        - ``dispersion_trend_mean``: 均值
        - ``dispersion_positive_windows_pct``: score_win_rate_spread > 0 的窗口占比
        - ``dispersion_trend_grade``: A/B/C/D
        - ``dispersion_trend_valid``: bool
    """
    _null: dict = {"dispersion_trend_valid": False, "dispersion_trend_slope": None, "dispersion_trend_mean": None, "dispersion_positive_windows_pct": None, "dispersion_trend_grade": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("dispersion_score_win_rate_spread")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    dispersion_positive_windows_pct = round(sum(1 for v in vals if v > 0) / n, 6)
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"dispersion_trend_valid": True, "dispersion_trend_slope": round(slope, 8), "dispersion_trend_mean": round(mean_v, 6), "dispersion_positive_windows_pct": dispersion_positive_windows_pct, "dispersion_trend_grade": grade}


def compute_cross_window_concentration_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪持仓集中度（sector_hhi）趋势，HHI 越低越好。

    从各窗口 summary 收集 ``conc_sector_hhi``（Round 68 T2 的输出），需≥3个有效值。
    Returns:
        - ``concentration_hhi_slope``: OLS 斜率（LOWER_IS_BETTER，正=集中度上升=变差）
        - ``concentration_hhi_mean``: 均值
        - ``concentration_dispersed_windows_pct``: sector_hhi < 0.35 的窗口占比
        - ``concentration_trend_grade``: A/B/C/D
        - ``concentration_trend_valid``: bool
    """
    _null: dict = {"concentration_trend_valid": False, "concentration_hhi_slope": None, "concentration_hhi_mean": None, "concentration_dispersed_windows_pct": None, "concentration_trend_grade": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("conc_sector_hhi")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    concentration_dispersed_windows_pct = round(sum(1 for v in vals if v < 0.35) / n, 6)
    if slope < -0.01:
        grade = "A"
    elif slope < 0:
        grade = "B"
    elif slope < 0.01:
        grade = "C"
    else:
        grade = "D"
    return {"concentration_trend_valid": True, "concentration_hhi_slope": round(slope, 8), "concentration_hhi_mean": round(mean_v, 6), "concentration_dispersed_windows_pct": concentration_dispersed_windows_pct, "concentration_trend_grade": grade}


def compute_cross_window_rs_rank_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪 RS 排名区分度（rs_rank_spread）趋势。

    从各窗口 summary 收集 ``rs_rank_rs_rank_spread``（Round 69 T1 的输出），需≥3个有效值。
    Returns:
        - ``rs_rank_trend_slope``: OLS 斜率（正=区分度提升=越来越好）
        - ``rs_rank_trend_mean``: 均值
        - ``rs_rank_positive_windows_pct``: rs_rank_spread > 0 的窗口占比
        - ``rs_rank_trend_grade``: A/B/C/D
        - ``rs_rank_trend_valid``: bool
    """
    _null: dict = {"rs_rank_trend_valid": False, "rs_rank_trend_slope": None, "rs_rank_trend_mean": None, "rs_rank_positive_windows_pct": None, "rs_rank_trend_grade": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("rs_rank_rs_rank_spread")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    rs_rank_positive_windows_pct = round(sum(1 for v in vals if v > 0) / n, 6)
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"rs_rank_trend_valid": True, "rs_rank_trend_slope": round(slope, 8), "rs_rank_trend_mean": round(mean_v, 6), "rs_rank_positive_windows_pct": rs_rank_positive_windows_pct, "rs_rank_trend_grade": grade}


def compute_cross_window_price_pos_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪价格位置强弱胜率差（cs_win_rate_spread）趋势。

    从各窗口 summary 收集 ``price_pos_cs_win_rate_spread``（Round 70 T1 的输出），需≥3个有效值。

    Returns:
        - ``price_pos_trend_slope``: OLS 斜率（正=区分度提升=越来越好）
        - ``price_pos_trend_mean``: 均值
        - ``price_pos_positive_windows_pct``: cs_win_rate_spread > 0 的窗口占比
        - ``price_pos_trend_grade``: A/B/C/D
        - ``price_pos_trend_valid``: bool
    """
    _null: dict = {"price_pos_trend_valid": False, "price_pos_trend_slope": None, "price_pos_trend_mean": None, "price_pos_positive_windows_pct": None, "price_pos_trend_grade": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("price_pos_cs_win_rate_spread")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    price_pos_positive_windows_pct = round(sum(1 for v in vals if v > 0) / n, 6)
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"price_pos_trend_valid": True, "price_pos_trend_slope": round(slope, 8), "price_pos_trend_mean": round(mean_v, 6), "price_pos_positive_windows_pct": price_pos_positive_windows_pct, "price_pos_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 72, Task 3 (Gamma): Cross-window momentum rank win-spread trend
# ---------------------------------------------------------------------------

def compute_cross_window_momentum_rank_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪动量强弱胜率差（momentum_win_spread）趋势。

    从各窗口 summary 收集 ``mom_rank_momentum_win_spread``（Round 71 T1 的输出），需≥3个有效值（非None）。

    Returns:
        - ``momentum_rank_trend_slope``: OLS 斜率（正=区分度提升=越来越好）
        - ``momentum_rank_trend_mean``: 均值
        - ``momentum_rank_positive_windows_pct``: momentum_win_spread > 0 的窗口占比
        - ``momentum_rank_trend_grade``: A/B/C/D
        - ``momentum_rank_trend_valid``: bool
    """
    _null: dict = {"momentum_rank_trend_valid": False, "momentum_rank_trend_slope": None, "momentum_rank_trend_mean": None, "momentum_rank_positive_windows_pct": None, "momentum_rank_trend_grade": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("mom_rank_momentum_win_spread")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    momentum_rank_positive_windows_pct = round(sum(1 for v in vals if v > 0) / n, 6)
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"momentum_rank_trend_valid": True, "momentum_rank_trend_slope": round(slope, 8), "momentum_rank_trend_mean": round(mean_v, 6), "momentum_rank_positive_windows_pct": momentum_rank_positive_windows_pct, "momentum_rank_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 73, Task 3 (Gamma): Cross-window Z-score win-spread trend
# ---------------------------------------------------------------------------


def compute_cross_window_zscore_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪多因子Z综合胜率差（zscore_win_spread）趋势。

    从各窗口 summary 收集 ``mfz_zscore_win_spread``（Round 72 T1 的输出），需≥3个有效值（非None）。

    Returns:
        - ``zscore_trend_slope``: OLS 斜率（正=Z分组区分度提升）
        - ``zscore_trend_mean``: 均值
        - ``zscore_positive_windows_pct``: zscore_win_spread > 0 的窗口占比
        - ``zscore_trend_grade``: A/B/C/D
        - ``zscore_trend_valid``: bool
    """
    _null: dict = {"zscore_trend_valid": False, "zscore_trend_slope": None, "zscore_trend_mean": None, "zscore_positive_windows_pct": None, "zscore_trend_grade": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("mfz_zscore_win_spread")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    zscore_positive_windows_pct = round(sum(1 for v in vals if v > 0) / n, 6)
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"zscore_trend_valid": True, "zscore_trend_slope": round(slope, 8), "zscore_trend_mean": round(mean_v, 6), "zscore_positive_windows_pct": zscore_positive_windows_pct, "zscore_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 74, Task 3 (Gamma): Cross-window market breadth win-rate trend
# ---------------------------------------------------------------------------


def compute_cross_window_breadth_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪市场宽度胜率（breadth_win_rate）趋势。

    从各窗口 summary 收集 ``breadth_breadth_win_rate``（Round 73 T1 的输出），需≥3个有效值（非None）。

    Returns:
        - ``breadth_trend_slope``: OLS 斜率
        - ``breadth_trend_mean``: 均值
        - ``breadth_above_threshold_pct``: breadth_win_rate > 0.5 的窗口占比
        - ``breadth_trend_grade``: A/B/C/D
        - ``breadth_trend_valid``: bool
    """
    _null: dict = {"breadth_trend_valid": False, "breadth_trend_slope": None, "breadth_trend_mean": None, "breadth_above_threshold_pct": None, "breadth_trend_grade": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("breadth_breadth_win_rate")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    breadth_above_threshold_pct = round(sum(1 for v in vals if v > 0.5) / n, 6)
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"breadth_trend_valid": True, "breadth_trend_slope": round(slope, 8), "breadth_trend_mean": round(mean_v, 6), "breadth_above_threshold_pct": breadth_above_threshold_pct, "breadth_trend_grade": grade}


# ---------------------------------------------------------------------------
# Round 75, Task 3 (Gamma): cross-window stratification spread trend
# ---------------------------------------------------------------------------


def compute_cross_window_stratification_trend(all_windows_summaries: list[dict]) -> dict:
    """跨窗口追踪信号强度分层胜率差（stratification_spread）趋势。

    从各窗口 summary 收集 ``strat_stratification_spread``（Round 74 T1 的输出），需≥3个有效值（非None）。

    Returns:
        - ``stratification_trend_slope``: OLS 斜率
        - ``stratification_trend_mean``: 均值
        - ``stratification_trend_valid``: bool
        - ``stratification_positive_windows_pct``: stratification_spread > 0 的窗口占比
        - ``stratification_trend_grade``: A(slope>0.005)/B(slope>0)/C(slope>-0.01)/D(slope≤-0.01)
    """
    _null: dict = {"stratification_trend_valid": False, "stratification_trend_slope": None, "stratification_trend_mean": None, "stratification_positive_windows_pct": None, "stratification_trend_grade": None}
    vals: list[float] = []
    for s in all_windows_summaries:
        v = s.get("strat_stratification_spread")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 3:
        return _null
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(vals) / n
    num = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    denom = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    mean_v = sum(vals) / n
    stratification_positive_windows_pct = round(sum(1 for v in vals if v > 0) / n, 6)
    if slope > 0.005:
        grade = "A"
    elif slope > 0:
        grade = "B"
    elif slope > -0.01:
        grade = "C"
    else:
        grade = "D"
    return {"stratification_trend_valid": True, "stratification_trend_slope": round(slope, 8), "stratification_trend_mean": round(mean_v, 6), "stratification_positive_windows_pct": stratification_positive_windows_pct, "stratification_trend_grade": grade}


def _build_replay_evaluator(
    input_paths: list[Path],
    *,
    base_profile: str,
    next_high_hit_threshold: float = 0.02,
) -> Callable:
    from scripts.btst_profile_replay_utils import analyze_btst_profile_replay_window

    # Task S (Round 9): pre-compute temporal recency decay map so that older windows
    # receive proportionally less weight, preventing stale regime data from dominating.
    # Task 4 (Round 10): pre-compute one decay map per candidate half-life so the inner
    # evaluator can select the correct map based on the trial's recency_half_life_days param
    # without re-scanning input_paths on every trial.
    recency_decay_maps: dict[int, dict[str, float]] = {hl: _build_recency_decay_map(input_paths, half_life_days=hl) for hl in RECENCY_HALF_LIFE_CANDIDATES}
    recency_decay_map: dict[str, float] = recency_decay_maps[RECENCY_HALF_LIFE_DAYS]

    def evaluator(params: dict[str, Any]) -> dict[str, float | None]:
        from src.targets.profiles import build_short_trade_target_profile

        # Task 4 (Round 10): select per-trial decay map based on the recency_half_life_days
        # search parameter; fall back to the default map when the param is absent.
        trial_half_life = int(params.get("recency_half_life_days") or RECENCY_HALF_LIFE_DAYS)
        active_recency_decay_map = recency_decay_maps.get(trial_half_life, recency_decay_map)
        # Strip optimizer-only params before forwarding to the profile builder.
        profile_params = {k: v for k, v in params.items() if k not in _OPTIMIZER_ONLY_PARAMS}

        try:
            build_short_trade_target_profile(base_profile, overrides=profile_params)
        except Exception as e:
            logger.warning("Invalid params %s: %s", params, e)
            return {
                "sharpe_ratio": None,
                "sortino_ratio": None,
                "max_drawdown": None,
                "next_close_positive_rate": None,
                "next_close_payoff_ratio": None,
                "next_close_expectancy": None,
                "next_high_hit_rate": None,
                "t_plus_2_close_positive_rate": None,
                "t_plus_2_close_payoff_ratio": None,
                "t_plus_3_close_positive_rate": None,
                "t_plus_3_close_expectancy": None,
                "t_plus_3_close_payoff_ratio": None,
                "downside_p10": None,
                "sample_weight": None,
                "window_coverage": 0.0,
                "window_count": 0,
                "source_coverage_pass_ratio": 0.0,
            }

        total_metrics: dict[str, list[float]] = {
            "sharpe": [],
            "sortino": [],
            "max_dd": [],
            "next_close_positive_rate": [],
            "next_close_payoff_ratio": [],
            "next_close_expectancy": [],
            "next_high_hit_rate": [],
            "t_plus_2_close_positive_rate": [],
            "t_plus_2_close_payoff_ratio": [],
            "t_plus_3_close_positive_rate": [],
            "t_plus_3_close_expectancy": [],
            "t_plus_3_close_payoff_ratio": [],
            "downside_p10": [],
            "sample_weight": [],
            "projected_theme_exposure": [],
            "incremental_theme_exposure": [],
            "liquidity_capacity_raw_100": [],
            "crowding_risk_raw_100": [],
            "gap_risk_raw_100": [],
            "max_future_high_return_2_5d_hit_rate_at_15pct": [],
            "max_future_high_return_2_5d_hit_rate_at_20pct": [],
            "runner_capture_count": [],
            "time_to_hit_15pct_median": [],
            "time_to_hit_20pct_median": [],
            "runner_escape_rate": [],
            "avg_composite_score_escaped": [],
            # Task 3 (Round 11): candidate pool quality
            "candidate_pool_avg_composite_score": [],
            # Task 1 (Round 12): T+1 intraday drawdown tail-risk metric
            "t_plus_1_intraday_drawdown_p10": [],
            # Task 1 (Round 20, Beta): realized payoff ratio — sample-weighted quality guardrail.
            "realized_payoff_ratio": [],
            # Task 2 (Round 24): drawdown-adjusted Kelly fraction — sample-weighted across windows.
            "kelly_fraction_drawdown_adjusted": [],
            # Task 3 (Round 27, Beta): recommended_max_positions from liquidity position guidance.
            "recommended_max_positions": [],
        }
        # Task 1 (Round 11): per-factor IC accumulator across replay windows
        total_factor_ics: dict[str, list[float]] = {f: [] for f in BTST_FACTOR_NAMES}
        # Task 3 (Round 12): IC weight suggestions accumulator across replay windows (mode vote)
        total_ic_weight_suggestions: dict[str, list[str]] = {f: [] for f in BTST_FACTOR_NAMES}

        # For metrics that should be sample-weighted, keep a parallel list of weights
        total_metric_weights: dict[str, list[float]] = {
            "next_close_positive_rate": [],
            "next_close_payoff_ratio": [],
            "next_close_expectancy": [],
            "next_high_hit_rate": [],
            "t_plus_2_close_positive_rate": [],
            "t_plus_2_close_payoff_ratio": [],
            "t_plus_3_close_positive_rate": [],
            "t_plus_3_close_expectancy": [],
            "t_plus_3_close_payoff_ratio": [],
            "downside_p10": [],
            "max_future_high_return_2_5d_hit_rate_at_15pct": [],
            "max_future_high_return_2_5d_hit_rate_at_20pct": [],
            "time_to_hit_15pct_median": [],
            "time_to_hit_20pct_median": [],
            # Task 1 (Round 12): intraday drawdown is also sample-weighted
            "t_plus_1_intraday_drawdown_p10": [],
            # Task 1 (Round 20, Beta): realized payoff ratio is also sample-weighted
            "realized_payoff_ratio": [],
            # Task 2 (Round 24): drawdown-adjusted Kelly is also sample-weighted
            "kelly_fraction_drawdown_adjusted": [],
        }

        # Track selected surfaces for runner median distribution aggregation
        selected_surfaces: list[dict[str, Any]] = []
        # Task 1 & 2 (Round 21): collect ALL primary surfaces (regardless of scope) for
        # cross-window correlation and IC stability analysis.
        all_primary_surfaces: list[dict[str, Any]] = []

        window_count = 0
        source_coverage_summaries: list[dict[str, Any]] = []

        for input_path in input_paths:
            try:
                result = analyze_btst_profile_replay_window(
                    input_path,
                    profile_name=base_profile,
                    label=f"trial_{json.dumps(params, sort_keys=True, default=str)}",
                    next_high_hit_threshold=next_high_hit_threshold,
                    profile_overrides=profile_params,
                )
                surfaces = dict(result.get("surface_summaries", {}) or {})
                selected_surface = dict(surfaces.get("selected") or {})
                tradeable_surface = dict(surfaces.get("tradeable") or {})
                primary_surface, primary_scope = _resolve_primary_surface(
                    selected_surface=selected_surface,
                    tradeable_surface=tradeable_surface,
                )

                next_close_positive_rate = _safe_float(primary_surface.get("next_close_positive_rate"))
                next_high_hit_rate = _safe_float(primary_surface.get("next_high_hit_rate_at_threshold"))
                t_plus_2_median = _resolve_distribution_stat(primary_surface, "t_plus_2_close_return_distribution", "median")
                t_plus_3_median = _resolve_distribution_stat(primary_surface, "t_plus_3_close_return_distribution", "median")
                max_dd_proxy = _resolve_distribution_stat(primary_surface, "next_close_return_distribution", "p10")
                next_close_payoff_ratio = _safe_float(primary_surface.get("next_close_payoff_ratio"))
                next_close_expectancy = _safe_float(primary_surface.get("next_close_expectancy"))
                t_plus_2_close_positive_rate = _safe_float(primary_surface.get("t_plus_2_close_positive_rate"))
                t_plus_2_close_payoff_ratio = _safe_float(primary_surface.get("t_plus_2_close_payoff_ratio"))
                t_plus_3_close_positive_rate = _safe_float(primary_surface.get("t_plus_3_close_positive_rate"))
                t_plus_3_close_expectancy = _safe_float(primary_surface.get("t_plus_3_close_expectancy"))
                t_plus_3_close_payoff_ratio = _safe_float(primary_surface.get("t_plus_3_close_payoff_ratio"))
                has_t_plus_2_horizon = t_plus_2_median is not None and t_plus_2_close_positive_rate is not None
                has_t_plus_3_horizon = t_plus_3_median is not None and t_plus_3_close_positive_rate is not None and t_plus_3_close_expectancy is not None

                if t_plus_2_median is None:
                    t_plus_2_median = _resolve_distribution_stat(primary_surface, "next_close_return_distribution", "median")
                if t_plus_2_close_positive_rate is None:
                    t_plus_2_close_positive_rate = next_close_positive_rate
                if t_plus_2_close_payoff_ratio is None:
                    t_plus_2_close_payoff_ratio = next_close_payoff_ratio
                if t_plus_3_median is None:
                    t_plus_3_median = t_plus_2_median
                if t_plus_3_close_positive_rate is None:
                    t_plus_3_close_positive_rate = t_plus_2_close_positive_rate
                if t_plus_3_close_expectancy is None:
                    t_plus_3_close_expectancy = _safe_float(primary_surface.get("t_plus_2_close_expectancy"))
                if t_plus_3_close_expectancy is None:
                    t_plus_3_close_expectancy = next_close_expectancy
                if t_plus_3_close_payoff_ratio is None:
                    t_plus_3_close_payoff_ratio = t_plus_2_close_payoff_ratio

                if next_close_positive_rate is None or next_high_hit_rate is None or t_plus_2_median is None or t_plus_3_median is None or max_dd_proxy is None or next_close_expectancy is None or t_plus_2_close_positive_rate is None or t_plus_3_close_positive_rate is None or t_plus_3_close_expectancy is None:
                    logger.warning("Trial skipped due missing metrics for %s scope=%s", input_path, primary_scope)
                    continue

                scoped_rows = _resolve_scope_rows(list(result.get("rows") or []), primary_scope=primary_scope)
                next_day_count = int(primary_surface.get("next_day_available_count") or 0)
                closed_cycle_count = int(primary_surface.get("closed_cycle_count") or 0)
                next_day_weight = min(1.0, max(0.0, next_day_count / 10.0))
                closed_cycle_weight = min(1.0, max(0.0, closed_cycle_count / 6.0))
                sample_weight = min(next_day_weight, closed_cycle_weight)
                if not has_t_plus_2_horizon:
                    sample_weight *= PARTIAL_HORIZON_WEIGHT_PENALTY
                elif not has_t_plus_3_horizon:
                    sample_weight *= PARTIAL_T3_HORIZON_WEIGHT_PENALTY
                # Task S (Round 9): apply temporal recency decay so that older windows contribute
                # proportionally less.  Task 4 (Round 10): use the trial-specific decay map so
                # different half_life candidates receive correctly scaled weights.
                sample_weight *= active_recency_decay_map.get(str(input_path), 1.0)
                # Task U (Round 9): dynamic liquidity regime — extract per-window average liquidity
                # and down-weight windows that fall in a low-volume market regime.
                window_liquidity = _average_scope_metric(scoped_rows, "liquidity_capacity_raw_100")
                if window_liquidity is not None:
                    if window_liquidity < LIQUIDITY_LOW_REGIME_FLOOR:
                        sample_weight *= LIQUIDITY_LOW_REGIME_WEIGHT_PENALTY
                    elif window_liquidity < LIQUIDITY_SOFT_REGIME_FLOOR:
                        sample_weight *= LIQUIDITY_SOFT_REGIME_WEIGHT_PENALTY
                # t_plus_3_cycle_count is only present when build_surface_summary is new enough;
                # fall back to sample_weight when absent to preserve backward compatibility.
                # Must be computed AFTER all penalty adjustments so t_plus_3_sample_weight reflects
                # the fully-adjusted weight (recency + liquidity + horizon penalties).
                t_plus_3_cycle_count_raw = primary_surface.get("t_plus_3_cycle_count")
                if t_plus_3_cycle_count_raw is not None:
                    t_plus_3_cycle_count = int(t_plus_3_cycle_count_raw)
                    t_plus_3_cycle_weight = min(1.0, max(0.0, t_plus_3_cycle_count / 4.0))
                    t_plus_3_sample_weight = min(sample_weight, t_plus_3_cycle_weight)
                else:
                    t_plus_3_sample_weight = sample_weight
                sharpe_proxy = (next_close_positive_rate + next_high_hit_rate) * sample_weight
                sortino_proxy = t_plus_2_median * sample_weight
                total_metrics["sharpe"].append(sharpe_proxy)
                total_metrics["sortino"].append(sortino_proxy)
                total_metrics["max_dd"].append(max_dd_proxy)
                # Primary quality metrics: append values and corresponding sample_weight for later weighted averaging
                total_metrics["next_close_positive_rate"].append(next_close_positive_rate)
                total_metric_weights["next_close_positive_rate"].append(sample_weight)
                if next_close_payoff_ratio is not None:
                    total_metrics["next_close_payoff_ratio"].append(next_close_payoff_ratio)
                    total_metric_weights["next_close_payoff_ratio"].append(sample_weight)
                total_metrics["next_close_expectancy"].append(next_close_expectancy)
                total_metric_weights["next_close_expectancy"].append(sample_weight)
                total_metrics["next_high_hit_rate"].append(next_high_hit_rate)
                total_metric_weights["next_high_hit_rate"].append(sample_weight)
                total_metrics["t_plus_2_close_positive_rate"].append(t_plus_2_close_positive_rate)
                total_metric_weights["t_plus_2_close_positive_rate"].append(sample_weight)
                if t_plus_2_close_payoff_ratio is not None:
                    total_metrics["t_plus_2_close_payoff_ratio"].append(t_plus_2_close_payoff_ratio)
                    total_metric_weights["t_plus_2_close_payoff_ratio"].append(sample_weight)
                total_metrics["t_plus_3_close_positive_rate"].append(t_plus_3_close_positive_rate)
                total_metric_weights["t_plus_3_close_positive_rate"].append(t_plus_3_sample_weight)
                total_metrics["t_plus_3_close_expectancy"].append(t_plus_3_close_expectancy)
                total_metric_weights["t_plus_3_close_expectancy"].append(t_plus_3_sample_weight)
                if t_plus_3_close_payoff_ratio is not None:
                    total_metrics["t_plus_3_close_payoff_ratio"].append(t_plus_3_close_payoff_ratio)
                    total_metric_weights["t_plus_3_close_payoff_ratio"].append(t_plus_3_sample_weight)
                total_metrics["downside_p10"].append(max_dd_proxy)
                total_metric_weights["downside_p10"].append(sample_weight)
                # Still track raw sample_weight list for reporting
                total_metrics["sample_weight"].append(sample_weight)

                # Runner horizon metrics
                runner_tail_hit_rate_15pct = _safe_float(primary_surface.get("max_future_high_return_2_5d_hit_rate_at_15pct"))
                runner_tail_hit_rate = _safe_float(primary_surface.get("max_future_high_return_2_5d_hit_rate_at_20pct"))
                runner_capture_count = primary_surface.get("runner_capture_count", 0)
                time_to_hit_15pct = _safe_float(primary_surface.get("time_to_hit_15pct_median"))
                time_to_hit_20pct = _safe_float(primary_surface.get("time_to_hit_20pct_median"))
                if runner_tail_hit_rate_15pct is not None:
                    total_metrics["max_future_high_return_2_5d_hit_rate_at_15pct"].append(runner_tail_hit_rate_15pct)
                    total_metric_weights["max_future_high_return_2_5d_hit_rate_at_15pct"].append(sample_weight)
                if runner_tail_hit_rate is not None:
                    total_metrics["max_future_high_return_2_5d_hit_rate_at_20pct"].append(runner_tail_hit_rate)
                    total_metric_weights["max_future_high_return_2_5d_hit_rate_at_20pct"].append(sample_weight)
                if isinstance(runner_capture_count, (int, float)):
                    total_metrics["runner_capture_count"].append(float(runner_capture_count))
                if time_to_hit_15pct is not None:
                    total_metrics["time_to_hit_15pct_median"].append(time_to_hit_15pct)
                    total_metric_weights["time_to_hit_15pct_median"].append(sample_weight)
                if time_to_hit_20pct is not None:
                    total_metrics["time_to_hit_20pct_median"].append(time_to_hit_20pct)
                    total_metric_weights["time_to_hit_20pct_median"].append(sample_weight)
                escape_rate = _safe_float(primary_surface.get("runner_escape_rate"))
                if escape_rate is not None:
                    total_metrics["runner_escape_rate"].append(escape_rate)
                avg_escaped_score = _safe_float(primary_surface.get("avg_composite_score_escaped"))
                if avg_escaped_score is not None:
                    total_metrics["avg_composite_score_escaped"].append(avg_escaped_score)
                # Task 1 (Round 11): accumulate per-factor Spearman IC from surface summary.
                # The IC dict was written by build_surface_summary (Task 1, Round 10).
                surface_factor_ic_next_close = dict(primary_surface.get("factor_ic_next_close") or {})
                for _factor_name in BTST_FACTOR_NAMES:
                    _ic_val = _safe_float(surface_factor_ic_next_close.get(_factor_name))
                    if _ic_val is not None:
                        total_factor_ics[_factor_name].append(_ic_val)
                # Task 3 (Round 12): accumulate per-factor IC weight suggestions (mode-vote across windows).
                surface_ic_suggestions = dict(primary_surface.get("ic_weight_suggestions") or {})
                for _factor_name in BTST_FACTOR_NAMES:
                    _suggestion = surface_ic_suggestions.get(_factor_name)
                    if _suggestion is not None:
                        total_ic_weight_suggestions[_factor_name].append(str(_suggestion))
                # Task 3 (Round 11): candidate pool average composite score for quality gate.
                pool_avg_score = _safe_float(primary_surface.get("candidate_pool_avg_composite_score"))
                if pool_avg_score is not None:
                    total_metrics["candidate_pool_avg_composite_score"].append(pool_avg_score)
                # Task 1 (Round 12): T+1 intraday drawdown P10 — sample-weighted like other BTST quality metrics.
                intraday_dd_p10 = _safe_float(primary_surface.get("t_plus_1_intraday_drawdown_p10"))
                if intraday_dd_p10 is not None:
                    total_metrics["t_plus_1_intraday_drawdown_p10"].append(intraday_dd_p10)
                    total_metric_weights["t_plus_1_intraday_drawdown_p10"].append(sample_weight)
                # Task 1 (Round 20, Beta): realized payoff ratio — sample-weighted quality guardrail.
                realized_payoff_ratio_val = _safe_float(primary_surface.get("realized_payoff_ratio"))
                if realized_payoff_ratio_val is not None:
                    total_metrics["realized_payoff_ratio"].append(realized_payoff_ratio_val)
                    total_metric_weights["realized_payoff_ratio"].append(sample_weight)
                # Task 2 (Round 24): drawdown-adjusted Kelly fraction — sample-weighted across windows.
                kelly_dd_adjusted_val = _safe_float(primary_surface.get("kelly_fraction_drawdown_adjusted"))
                if kelly_dd_adjusted_val is not None:
                    total_metrics["kelly_fraction_drawdown_adjusted"].append(kelly_dd_adjusted_val)
                    total_metric_weights["kelly_fraction_drawdown_adjusted"].append(sample_weight)
                # Task 3 (Round 27, Beta): recommended_max_positions from liquidity guidance.
                rec_max_pos = _safe_float(primary_surface.get("recommended_max_positions"))
                if rec_max_pos is not None:
                    total_metrics["recommended_max_positions"].append(rec_max_pos)
                if primary_scope == "selected":
                    selected_surfaces.append(primary_surface)
                # Task 1 & 2 (Round 21): collect every primary surface for cross-window analytics.
                all_primary_surfaces.append(primary_surface)

                for metric_key in (
                    "projected_theme_exposure",
                    "incremental_theme_exposure",
                    "crowding_risk_raw_100",
                    "gap_risk_raw_100",
                ):
                    metric_value = _average_scope_metric(scoped_rows, metric_key)
                    if metric_value is not None:
                        total_metrics[metric_key].append(metric_value)
                # Task U (Round 9): reuse already-computed window_liquidity to avoid a second scan.
                if window_liquidity is not None:
                    total_metrics["liquidity_capacity_raw_100"].append(window_liquidity)
                window_count += 1
                coverage_summary = dict(result.get("source_coverage_summary") or {})
                if coverage_summary:
                    source_coverage_summaries.append(coverage_summary)
            except Exception as e:
                logger.warning("Trial failed for %s: %s", input_path, e)
                continue

        if window_count == 0:
            return {
                "sharpe_ratio": None,
                "sortino_ratio": None,
                "max_drawdown": None,
                "next_close_positive_rate": None,
                "next_close_payoff_ratio": None,
                "next_close_expectancy": None,
                "next_high_hit_rate": None,
                "t_plus_2_close_positive_rate": None,
                "t_plus_2_close_payoff_ratio": None,
                "t_plus_3_close_positive_rate": None,
                "t_plus_3_close_expectancy": None,
                "t_plus_3_close_payoff_ratio": None,
                "downside_p10": None,
                "sample_weight": None,
                "window_coverage": 0.0,
                "window_count": 0,
                "source_coverage_pass_ratio": 0.0,
            }

        avg_sharpe = sum(total_metrics["sharpe"]) / len(total_metrics["sharpe"]) if total_metrics["sharpe"] else None
        avg_sortino = sum(total_metrics["sortino"]) / len(total_metrics["sortino"]) if total_metrics["sortino"] else None
        avg_max_dd = sum(total_metrics["max_dd"]) / len(total_metrics["max_dd"]) if total_metrics["max_dd"] else None

        def _weighted_avg(values: list[float], weights: list[float]) -> float | None:
            if not values:
                return None
            total_w = sum(weights) if weights else 0.0
            if total_w <= 0.0:
                return None
            return sum(v * w for v, w in zip(values, weights)) / total_w

        # Primary quality metrics use sample-weighted averages
        avg_next_close_positive_rate = _weighted_avg(total_metrics["next_close_positive_rate"], total_metric_weights["next_close_positive_rate"])
        avg_next_close_payoff_ratio = _weighted_avg(total_metrics["next_close_payoff_ratio"], total_metric_weights["next_close_payoff_ratio"])
        avg_next_close_expectancy = _weighted_avg(total_metrics["next_close_expectancy"], total_metric_weights["next_close_expectancy"])
        avg_next_high_hit_rate = _weighted_avg(total_metrics["next_high_hit_rate"], total_metric_weights["next_high_hit_rate"])
        avg_t_plus_2_close_positive_rate = _weighted_avg(total_metrics["t_plus_2_close_positive_rate"], total_metric_weights["t_plus_2_close_positive_rate"])
        avg_t_plus_2_close_payoff_ratio = _weighted_avg(total_metrics["t_plus_2_close_payoff_ratio"], total_metric_weights["t_plus_2_close_payoff_ratio"])
        avg_t_plus_3_close_positive_rate = _weighted_avg(total_metrics["t_plus_3_close_positive_rate"], total_metric_weights["t_plus_3_close_positive_rate"])
        avg_t_plus_3_close_expectancy = _weighted_avg(total_metrics["t_plus_3_close_expectancy"], total_metric_weights["t_plus_3_close_expectancy"])
        avg_t_plus_3_close_payoff_ratio = _weighted_avg(total_metrics["t_plus_3_close_payoff_ratio"], total_metric_weights["t_plus_3_close_payoff_ratio"])
        avg_downside_p10 = _weighted_avg(total_metrics["downside_p10"], total_metric_weights["downside_p10"])

        # Runner horizon metrics
        avg_runner_tail_hit_rate_15pct = _weighted_avg(total_metrics["max_future_high_return_2_5d_hit_rate_at_15pct"], total_metric_weights["max_future_high_return_2_5d_hit_rate_at_15pct"])
        avg_runner_tail_hit_rate = _weighted_avg(total_metrics["max_future_high_return_2_5d_hit_rate_at_20pct"], total_metric_weights["max_future_high_return_2_5d_hit_rate_at_20pct"])
        total_runner_capture_count = int(sum(total_metrics["runner_capture_count"])) if total_metrics["runner_capture_count"] else 0
        avg_time_to_hit_15pct = _weighted_avg(total_metrics["time_to_hit_15pct_median"], total_metric_weights["time_to_hit_15pct_median"])
        avg_time_to_hit_20pct = _weighted_avg(total_metrics["time_to_hit_20pct_median"], total_metric_weights["time_to_hit_20pct_median"])
        avg_runner_escape_rate = sum(total_metrics["runner_escape_rate"]) / len(total_metrics["runner_escape_rate"]) if total_metrics["runner_escape_rate"] else None
        avg_composite_score_escaped = sum(total_metrics["avg_composite_score_escaped"]) / len(total_metrics["avg_composite_score_escaped"]) if total_metrics["avg_composite_score_escaped"] else None

        # Task 1 (Round 11): aggregate IC per factor; compute ic_positive_factor_fraction.
        avg_factor_ics: dict[str, float | None] = {
            f: (sum(vals) / len(vals) if vals else None) for f, vals in total_factor_ics.items()
        }
        ic_factors_with_data = [f for f, v in avg_factor_ics.items() if v is not None]
        ic_positive_count = sum(1 for f in ic_factors_with_data if (avg_factor_ics[f] or 0.0) >= IC_SIGNAL_MIN)
        ic_positive_factor_fraction: float | None = (float(ic_positive_count) / float(len(ic_factors_with_data))) if ic_factors_with_data else None

        # Task 3 (Round 12): aggregate IC weight suggestions via majority-vote across windows.
        # For each factor, pick the suggestion that appears most frequently across replay windows;
        # ties are broken in the conservative direction: "reduce" > "maintain" > "increase".
        from collections import Counter as _Counter

        def _mode_suggestion(suggestions: list[str]) -> str | None:
            if not suggestions:
                return None
            counts = _Counter(suggestions)
            # Tie-breaking priority: reduce > maintain > increase
            for preferred in ("reduce", "maintain", "increase"):
                if counts[preferred] == max(counts.values()):
                    return preferred
            return counts.most_common(1)[0][0]

        aggregated_ic_weight_suggestions: dict[str, str] = {
            f: _mode_suggestion(total_ic_weight_suggestions[f])  # type: ignore[misc]
            for f in BTST_FACTOR_NAMES
            if total_ic_weight_suggestions[f]
        }

        # Task 3 (Round 11): aggregate candidate pool quality across windows.
        avg_candidate_pool_composite_score = (sum(total_metrics["candidate_pool_avg_composite_score"]) / len(total_metrics["candidate_pool_avg_composite_score"])) if total_metrics["candidate_pool_avg_composite_score"] else None

        # Task 1 (Round 12): sample-weighted average T+1 intraday drawdown P10.
        avg_t_plus_1_intraday_drawdown_p10 = _weighted_avg(total_metrics["t_plus_1_intraday_drawdown_p10"], total_metric_weights["t_plus_1_intraday_drawdown_p10"])
        # Task 1 (Round 20, Beta): sample-weighted average realized payoff ratio.
        avg_realized_payoff_ratio = _weighted_avg(total_metrics["realized_payoff_ratio"], total_metric_weights["realized_payoff_ratio"])
        # Task 2 (Round 24): sample-weighted average drawdown-adjusted Kelly fraction.
        avg_kelly_fraction_drawdown_adjusted = _weighted_avg(total_metrics["kelly_fraction_drawdown_adjusted"], total_metric_weights["kelly_fraction_drawdown_adjusted"])
        # Task 3 (Round 27, Beta): average recommended max positions across replay windows.
        _rec_max_pos_vals = total_metrics["recommended_max_positions"]
        avg_recommended_max_positions: int | None = round(sum(_rec_max_pos_vals) / len(_rec_max_pos_vals)) if _rec_max_pos_vals else None
        # Derive concentration_risk_level from avg pool size proxy via avg_recommended_max_positions.
        if avg_recommended_max_positions is None:
            _concentration_risk_level: str | None = None
        elif avg_recommended_max_positions >= 10:
            _concentration_risk_level = "low"
        elif avg_recommended_max_positions >= 5:
            _concentration_risk_level = "medium"
        elif avg_recommended_max_positions >= 2:
            _concentration_risk_level = "high"
        else:
            _concentration_risk_level = "extreme"

        def _weighted_average_distribution_median(surfaces: list[dict[str, Any]], dist_key: str) -> float | None:
            """Compute sample-weighted average of distribution medians from selected surfaces."""
            medians_and_weights: list[tuple[float, float]] = []
            for surf in surfaces:
                dist = dict(surf.get(dist_key) or {})
                median_val = _safe_float(dist.get("median"))
                next_day = surf.get("next_day_available_count", 0)
                closed = surf.get("closed_cycle_count", 0)
                if median_val is not None and next_day > 0 and closed > 0:
                    w = min(1.0, min(next_day / 10.0, closed / 6.0))
                    medians_and_weights.append((median_val, w))
            if not medians_and_weights:
                return None
            total_w = sum(w for _, w in medians_and_weights)
            if total_w <= 0.0:
                return None
            return sum(m * w for m, w in medians_and_weights) / total_w

        median_max_future_high_return_2_5d = _weighted_average_distribution_median(selected_surfaces, "max_future_high_return_2_5d_distribution")

        # Execution/exposure and other metrics remain simple unweighted means
        avg_sample_weight = sum(total_metrics["sample_weight"]) / len(total_metrics["sample_weight"]) if total_metrics["sample_weight"] else None
        avg_projected_theme_exposure = sum(total_metrics["projected_theme_exposure"]) / len(total_metrics["projected_theme_exposure"]) if total_metrics["projected_theme_exposure"] else None
        avg_incremental_theme_exposure = sum(total_metrics["incremental_theme_exposure"]) / len(total_metrics["incremental_theme_exposure"]) if total_metrics["incremental_theme_exposure"] else None
        avg_liquidity_capacity_raw_100 = sum(total_metrics["liquidity_capacity_raw_100"]) / len(total_metrics["liquidity_capacity_raw_100"]) if total_metrics["liquidity_capacity_raw_100"] else None
        avg_crowding_risk_raw_100 = sum(total_metrics["crowding_risk_raw_100"]) / len(total_metrics["crowding_risk_raw_100"]) if total_metrics["crowding_risk_raw_100"] else None
        avg_gap_risk_raw_100 = sum(total_metrics["gap_risk_raw_100"]) / len(total_metrics["gap_risk_raw_100"]) if total_metrics["gap_risk_raw_100"] else None
        window_coverage = float(window_count) / float(len(input_paths) or 1)
        effective_sample_weight = max(0.0, min(1.0, avg_sample_weight * window_coverage)) if avg_sample_weight is not None else None
        source_coverage_pass_ratio = _compute_source_coverage_pass_ratio(source_coverage_summaries)

        # Task 1 (Round 21, Gamma): cross-window surface metric win-rate correlations.
        # Computes Spearman correlation between each numeric surface metric and the
        # per-window next_close_positive_rate.  Requires ≥ 5 windows; returns {} otherwise.
        surface_metric_correlations: dict[str, Any] = compute_surface_metric_correlations(all_primary_surfaces)
        # Task 2 (Round 21, Alpha): factor IC stability (IR = mean_IC / std_IC) across windows.
        # Identifies consistently predictive factors vs noisy / regime-dependent ones.
        factor_ic_stability: dict[str, Any] = compute_factor_ic_stability(all_primary_surfaces)
        # Task 1 (Round 22, Gamma): low-impact PROBE_GRID axis identification.
        # Bridges surface correlations and IC stability to flag weak probe axes (advisory only).
        low_impact_probe_axes: dict[str, Any] = compute_low_impact_probe_axes(surface_metric_correlations, factor_ic_stability)
        # Task 1 (Round 24): IC temporal trend — detect IC decay across replay windows.
        # Splits windows into early vs late halves and flags factors whose IC is declining.
        factor_ic_temporal_trend: dict[str, Any] = compute_factor_ic_temporal_trend(all_primary_surfaces)
        # Task 3 (Round 24): walk-forward verdict calibration — check verdict ↔ win-rate alignment.
        # Uses window-level verdict or win-rate quartiles to verify that verdict categories
        # correspond to meaningfully different T+1 win rates.
        verdict_calibration: dict[str, Any] = compute_verdict_calibration(all_primary_surfaces)
        # Task 2 (Round 25, Beta): selection churn / window-stability metrics.
        # Measures how much the win-rate and payoff ratio fluctuate between adjacent replay windows.
        selection_churn: dict[str, Any] = compute_selection_churn_metrics(all_primary_surfaces)
        # Task 1 (Round 30, Gamma): parameter stability metrics — cross-window drift of key surface metrics.
        # Requires ≥ 3 windows; returns param_drift_score = median relative drift across tracked keys.
        param_stability: dict[str, Any] = compute_parameter_stability_metrics(all_primary_surfaces)
        # Task 1 (Round 25, Gamma): profile health score computed from aggregated evaluator metrics.
        # Build a lightweight proxy dict from the averaged metrics so ic_positive_factor_fraction
        # is available (unlike the per-surface call inside build_surface_summary).
        _health_proxy: dict[str, Any] = {
            "next_close_positive_rate": avg_next_close_positive_rate,
            "realized_payoff_ratio": avg_realized_payoff_ratio,
            "kelly_positive": None,  # aggregated kelly_positive not collected per-window above
            "kelly_fraction_half": None,
            "regime_consistency_score": None,
            "tier_monotone_win_rate": None,
            "tier_win_rate_spread": None,
            "ic_positive_factor_fraction": ic_positive_factor_fraction,
            "regime_robustness_flag": None,
            "bear_market_win_rate_deficit": None,
            "t_plus_1_intraday_drawdown_p10": avg_t_plus_1_intraday_drawdown_p10,
            "hold_period_confidence": None,
            "execution_timing_confidence": None,
        }
        # Enrich proxy with per-window averages where we have them
        for _surf_key in ("kelly_positive", "kelly_fraction_half", "regime_consistency_score", "tier_monotone_win_rate", "tier_win_rate_spread", "regime_robustness_flag", "bear_market_win_rate_deficit", "hold_period_confidence", "execution_timing_confidence"):
            _vals = [float(s[_surf_key]) for s in all_primary_surfaces if s.get(_surf_key) is not None and isinstance(s.get(_surf_key), (int, float, bool))]
            if _vals:
                _health_proxy[_surf_key] = sum(_vals) / len(_vals)
        evaluator_health: dict[str, Any] = compute_profile_health_score(_health_proxy)
        # Task 3 (Round 25, Alpha): auto-calibrated floor suggestions across replay windows.
        floor_suggestions_result: dict[str, Any] = compute_auto_calibrated_floor_suggestions(all_primary_surfaces)
        floor_suggestions_summary: dict[str, list[str]] = {
            "overly_easy_floors": floor_suggestions_result.get("overly_easy_floors", []),
            "overly_strict_floors": floor_suggestions_result.get("overly_strict_floors", []),
        }

        # Task 2 (Round 30, Alpha): average monthly_win_rate_spread across replay windows.
        _monthly_spread_vals = [float(s["monthly_win_rate_spread"]) for s in all_primary_surfaces if s.get("monthly_win_rate_spread") is not None]
        avg_monthly_win_rate_spread: float | None = round(sum(_monthly_spread_vals) / len(_monthly_spread_vals), 4) if _monthly_spread_vals else None
        # Task 3 (Round 30, Beta): average nonlinear_factor_count and avg_nonlinearity_ratio across replay windows.
        _nonlinear_count_vals = [float(s["nonlinear_factor_count"]) for s in all_primary_surfaces if s.get("nonlinear_factor_count") is not None]
        avg_nonlinear_factor_count: float | None = round(sum(_nonlinear_count_vals) / len(_nonlinear_count_vals), 2) if _nonlinear_count_vals else None
        _nonlinear_ratio_vals = [float(s["avg_nonlinearity_ratio"]) for s in all_primary_surfaces if s.get("avg_nonlinearity_ratio") is not None]
        avg_nonlinearity_ratio: float | None = round(sum(_nonlinear_ratio_vals) / len(_nonlinear_ratio_vals), 4) if _nonlinear_ratio_vals else None
        # Task 2 (Round 31, Gamma): composite score stability across windows.
        _score_stability: dict[str, Any] = compute_score_stability_across_windows(all_primary_surfaces)
        # Task 1 (Round 31, Alpha): average autocorr_lag1 across replay windows.
        _autocorr_lag1_vals = [float(s["autocorr_lag1"]) for s in all_primary_surfaces if s.get("autocorr_lag1") is not None]
        avg_autocorr_lag1: float | None = round(sum(_autocorr_lag1_vals) / len(_autocorr_lag1_vals), 4) if _autocorr_lag1_vals else None
        # Task 3 (Round 33, Beta): IC trend across replay windows — OLS slope of IC vs window index per factor.
        _ic_trend: dict[str, Any] = compute_factor_ic_trend(all_primary_surfaces)
        # Task 1 (Round 33, Alpha): average expected_value_per_trade across replay windows.
        _ev_vals = [float(s["expected_value_per_trade"]) for s in all_primary_surfaces if s.get("expected_value_per_trade") is not None]
        avg_expected_value_per_trade: float | None = round(sum(_ev_vals) / len(_ev_vals), 6) if _ev_vals else None
        # Task 2 (Round 33, Gamma): average momentum_half_life_days across replay windows.
        _hl_vals = [float(s["momentum_half_life_days"]) for s in all_primary_surfaces if s.get("momentum_half_life_days") is not None]
        avg_momentum_half_life_days: float | None = round(sum(_hl_vals) / len(_hl_vals), 4) if _hl_vals else None
        # Task 1 (Round 34, Alpha): average multi_factor_lift across replay windows.
        _mfl_vals = [float(s["multi_factor_lift"]) for s in all_primary_surfaces if s.get("multi_factor_lift") is not None]
        avg_multi_factor_lift: float | None = round(sum(_mfl_vals) / len(_mfl_vals), 4) if _mfl_vals else None
        # Task 2 (Round 34, Gamma): average adaptive_sizing_score across replay windows.
        _asz_vals = [float(s["adaptive_sizing_score"]) for s in all_primary_surfaces if s.get("adaptive_sizing_score") is not None]
        avg_adaptive_sizing_score: float | None = round(sum(_asz_vals) / len(_asz_vals), 2) if _asz_vals else None
        # Task 3 (Round 34, Beta): signal churn metrics — cross-window candidate pool stability.
        _signal_churn: dict[str, Any] = compute_signal_churn_metrics(all_primary_surfaces)
        # Task 1 (Round 35, Alpha): average sortino_ratio from T1 per-window Sortino analysis.
        _sortino_r35_vals = [float(s["sortino_ratio"]) for s in all_primary_surfaces if s.get("sortino_ratio") is not None]
        avg_sortino_r35: float | None = round(sum(_sortino_r35_vals) / len(_sortino_r35_vals), 4) if _sortino_r35_vals else None
        # Task 2 (Round 35, Gamma): quality trend analysis — tracks improvement across windows.
        _quality_trend: dict[str, Any] = compute_quality_trend_analysis(all_primary_surfaces)
        # Task 3 (Round 35, Beta): average diversity_score across replay windows.
        _div_vals = [float(s["diversity_score"]) for s in all_primary_surfaces if s.get("diversity_score") is not None]
        avg_diversity_score: float | None = round(sum(_div_vals) / len(_div_vals), 4) if _div_vals else None
        # Task 1 (Round 36, Alpha): average right_tail_dominance across replay windows.
        _rtd_vals = [float(s["right_tail_dominance"]) for s in all_primary_surfaces if s.get("right_tail_dominance") is not None]
        avg_right_tail_dominance: float | None = round(sum(_rtd_vals) / len(_rtd_vals), 4) if _rtd_vals else None
        # Task 2 (Round 36, Beta): average composite_ic across replay windows.
        _cic_vals = [float(s["composite_ic"]) for s in all_primary_surfaces if s.get("composite_ic") is not None]
        avg_composite_ic: float | None = round(sum(_cic_vals) / len(_cic_vals), 6) if _cic_vals else None
        # Task 3 (Round 36, Gamma): average win_rate_ci_width across replay windows.
        _wrci_vals = [float(s["win_rate_ci_width"]) for s in all_primary_surfaces if s.get("win_rate_ci_width") is not None]
        avg_win_rate_ci_width: float | None = round(sum(_wrci_vals) / len(_wrci_vals), 4) if _wrci_vals else None
        # Task 1 (Round 37, Alpha): mode of optimal_holding_days across replay windows.
        _ohd_vals = [int(s["optimal_holding_days"]) for s in all_primary_surfaces if s.get("optimal_holding_days") is not None]
        if _ohd_vals:
            _ohd_mode = _Counter(_ohd_vals).most_common(1)[0][0]
            avg_optimal_holding_days: int | None = _ohd_mode
        else:
            avg_optimal_holding_days = None
        # Task 2 (Round 37, Beta): average loss_signature_strength across replay windows.
        _lss_vals = [float(s["loss_signature_strength"]) for s in all_primary_surfaces if s.get("loss_signature_strength") is not None]
        avg_loss_signature_strength: float | None = round(sum(_lss_vals) / len(_lss_vals), 6) if _lss_vals else None
        # Task 3 (Round 37, Gamma): average score_gini across replay windows.
        _sgini_vals = [float(s["score_gini"]) for s in all_primary_surfaces if s.get("score_gini") is not None]
        avg_score_gini: float | None = round(sum(_sgini_vals) / len(_sgini_vals), 4) if _sgini_vals else None
        # Task 1 (Round 38, Alpha): average env_win_rate_gap across replay windows.
        _ewg_vals = [float(s["env_win_rate_gap"]) for s in all_primary_surfaces if s.get("env_win_rate_gap") is not None]
        avg_env_win_rate_gap: float | None = round(sum(_ewg_vals) / len(_ewg_vals), 4) if _ewg_vals else None
        # Task 2 (Round 38, Beta): average positive_ic_factor_count across replay windows.
        _pif_vals = [int(s["positive_ic_factor_count"]) for s in all_primary_surfaces if s.get("positive_ic_factor_count") is not None]
        avg_positive_ic_factor_count: int | None = round(sum(_pif_vals) / len(_pif_vals)) if _pif_vals else None
        # Task 3 (Round 38, Gamma): average top_quintile_premium across replay windows.
        _tqp_vals = [float(s["top_quintile_premium"]) for s in all_primary_surfaces if s.get("top_quintile_premium") is not None]
        avg_top_quintile_premium: float | None = round(sum(_tqp_vals) / len(_tqp_vals), 4) if _tqp_vals else None
        # Task 1 (Round 39, Alpha): average recency_win_rate_gap across replay windows.
        _rwg_vals = [float(s["recency_win_rate_gap"]) for s in all_primary_surfaces if s.get("recency_win_rate_gap") is not None]
        avg_recency_win_rate_gap: float | None = round(sum(_rwg_vals) / len(_rwg_vals), 4) if _rwg_vals else None
        # Task 2 (Round 39, Beta): average optimal_threshold_lift across replay windows.
        _otl_vals = [float(s["optimal_threshold_lift"]) for s in all_primary_surfaces if s.get("optimal_threshold_lift") is not None]
        avg_optimal_threshold_lift: float | None = round(sum(_otl_vals) / len(_otl_vals), 4) if _otl_vals else None
        # Task 3 (Round 39, Gamma): average recovery_factor and max_drawdown_simulated across replay windows.
        _rf_vals = [float(s["recovery_factor"]) for s in all_primary_surfaces if s.get("recovery_factor") is not None]
        avg_recovery_factor: float | None = round(sum(_rf_vals) / len(_rf_vals), 4) if _rf_vals else None
        _mds_vals = [float(s["max_drawdown_simulated"]) for s in all_primary_surfaces if s.get("max_drawdown_simulated") is not None]
        avg_max_drawdown_simulated: float | None = round(sum(_mds_vals) / len(_mds_vals), 4) if _mds_vals else None
        # Task 1 (Round 40, Alpha): average max_synergy_lift across replay windows.
        _msl_vals = [float(s["max_synergy_lift"]) for s in all_primary_surfaces if s.get("max_synergy_lift") is not None]
        avg_max_synergy_lift: float | None = round(sum(_msl_vals) / len(_msl_vals), 6) if _msl_vals else None
        # Task 2 (Round 40, Beta): average high_vs_low_lift across replay windows.
        _hvl_vals = [float(s["high_vs_low_lift"]) for s in all_primary_surfaces if s.get("high_vs_low_lift") is not None]
        avg_high_vs_low_lift: float | None = round(sum(_hvl_vals) / len(_hvl_vals), 6) if _hvl_vals else None
        # Task 3 (Round 40, Gamma): cross-window factor exposure drift — computed over all window summaries.
        _cfe: dict[str, Any] = compute_cross_window_factor_exposure(all_primary_surfaces)
        avg_factor_drift_score: float | None = _cfe.get("factor_drift_score")
        # Task 1 (Round 41, Alpha): factor IC rank consistency across replay windows.
        _frc: dict[str, Any] = compute_factor_rank_consistency(all_primary_surfaces)
        avg_factor_rank_consistency_score: float | None = _frc.get("factor_rank_consistency_score")
        # Task 2 (Round 41, Beta): average vol_price_alignment_rate across replay windows.
        _vpa_vals = [float(s["vol_price_alignment_rate"]) for s in all_primary_surfaces if s.get("vol_price_alignment_rate") is not None]
        avg_vol_price_alignment_rate: float | None = round(sum(_vpa_vals) / len(_vpa_vals), 6) if _vpa_vals else None
        # Task 3 (Round 41, Gamma): average combined_significance_score across replay windows.
        _css_vals = [float(s["combined_significance_score"]) for s in all_primary_surfaces if s.get("combined_significance_score") is not None]
        avg_combined_significance_score: float | None = round(sum(_css_vals) / len(_css_vals), 6) if _css_vals else None
        # Task 1 (Round 42, Alpha): average calibration_slope across replay windows.
        _csl_vals = [float(s["calibration_slope"]) for s in all_primary_surfaces if s.get("calibration_slope") is not None]
        avg_calibration_slope: float | None = round(sum(_csl_vals) / len(_csl_vals), 6) if _csl_vals else None
        # Task 2 (Round 42, Beta): average cs_top_quartile_premium across replay windows.
        _csp_vals = [float(s["cs_top_quartile_premium"]) for s in all_primary_surfaces if s.get("cs_top_quartile_premium") is not None]
        avg_cs_top_quartile_premium: float | None = round(sum(_csp_vals) / len(_csp_vals), 6) if _csp_vals else None
        # Task 3 (Round 42, Gamma): cross-window consensus score — computed over all window summaries.
        _wconsensus: dict[str, Any] = compute_window_consensus_score(all_primary_surfaces)
        # Task 1 (Round 43, Alpha): average profit_factor across replay windows.
        _pf_vals = [float(s["profit_factor"]) for s in all_primary_surfaces if s.get("profit_factor") is not None]
        avg_profit_factor: float | None = round(sum(_pf_vals) / len(_pf_vals), 6) if _pf_vals else None
        # Task 2 (Round 43, Beta): average high_vs_low_sentiment_lift across replay windows.
        _hsl_vals = [float(s["high_vs_low_sentiment_lift"]) for s in all_primary_surfaces if s.get("high_vs_low_sentiment_lift") is not None]
        avg_high_vs_low_sentiment_lift: float | None = round(sum(_hsl_vals) / len(_hsl_vals), 6) if _hsl_vals else None
        # Task 1 (Round 51, Alpha): average win_loss_magnitude_ratio and kelly_fraction.
        _wlmr_vals = [float(s["win_loss_magnitude_ratio"]) for s in all_primary_surfaces if s.get("win_loss_magnitude_ratio") is not None]
        avg_win_loss_magnitude_ratio: "float | None" = round(sum(_wlmr_vals) / len(_wlmr_vals), 6) if _wlmr_vals else None
        _kf_vals = [float(s["kelly_fraction"]) for s in all_primary_surfaces if s.get("kelly_fraction") is not None]
        avg_kelly_fraction: "float | None" = round(sum(_kf_vals) / len(_kf_vals), 6) if _kf_vals else None
        # Task 2 (Round 51, Beta): average outlier_dependency_ratio.
        _odr_vals = [float(s["outlier_dependency_ratio"]) for s in all_primary_surfaces if s.get("outlier_dependency_ratio") is not None]
        avg_outlier_dependency_ratio: "float | None" = round(sum(_odr_vals) / len(_odr_vals), 6) if _odr_vals else None
        # Task 3 (Round 43, Gamma): score momentum trend — OLS slope of avg composite score.
        _smt: dict[str, Any] = compute_score_momentum_trend(all_primary_surfaces)
        # Task 3 (Round 44, Gamma): win-rate stability across replay windows.
        _wrst: dict[str, Any] = compute_win_rate_stability_analysis(all_primary_surfaces)
        # Task 3 (Round 45, Gamma): top-candidate cross-window win-rate consistency.
        _tccs: dict[str, Any] = compute_top_candidate_consistency(all_primary_surfaces)
        # Task 3 (Round 46, Gamma): cross-window gate consistency.
        _cgc: dict[str, Any] = compute_cross_window_gate_consistency(all_primary_surfaces)
        # Task 3 (Round 47, Gamma): cross-window factor IC positive consistency.
        _fic: dict[str, Any] = compute_factor_ic_consistency(all_primary_surfaces)
        # Task 3 (Round 48, Gamma): cross-window expected-value trend.
        _ev_trend: dict[str, Any] = compute_cross_window_ev_trend(all_primary_surfaces)
        # Task 3 (Round 49, Gamma): cross-window Sortino trend.
        _sortino_trend: dict[str, Any] = compute_cross_window_sortino_trend(all_primary_surfaces)
        # Task 3 (Round 50, Gamma): cross-window Sharpe trend.
        _sharpe_trend: dict[str, Any] = compute_cross_window_sharpe_trend(all_primary_surfaces)
        # Task 3 (Round 77, Gamma): cross-window skew quality gain/loss ratio trend.
        _skew_trend: dict[str, Any] = compute_cross_window_skew_trend(all_primary_surfaces)
        # Task 3 (Round 78, Gamma): cross-window adaptive threshold lift trend.
        _tlt: dict[str, Any] = compute_cross_window_threshold_lift_trend(all_primary_surfaces)
        # Task 3 (Round 79, Gamma): cross-window factor robustness OLS trend.
        _rbt: dict[str, Any] = compute_cross_window_robustness_trend(all_primary_surfaces)
        # Task 3 (Round 80, Gamma): cross-window entry quality OLS trend.
        _eqt: dict[str, Any] = compute_cross_window_entry_quality_trend(all_primary_surfaces)
        # Task 3 (Round 81, Gamma): cross-window near-high stock premium OLS trend.
        _nht: dict[str, Any] = compute_cross_window_near_high_trend(all_primary_surfaces)
        # Task 3 (Round 82, Gamma): cross-window EV spread OLS trend.
        _evst: dict[str, Any] = compute_cross_window_ev_spread_trend(all_primary_surfaces)
        # Task 3 (Round 83, Gamma): cross-window precision trend OLS.
        _pct83: dict[str, Any] = compute_cross_window_precision_trend(all_primary_surfaces)
        # Task 3 (Round 84, Gamma): cross-window upside asymmetry OLS trend.
        _uat84: dict[str, Any] = compute_cross_window_upside_asymmetry_trend(all_primary_surfaces)
        # Task 3 (Round 85, Gamma): cross-window momentum reversal OLS trend.
        _mrt85: dict[str, Any] = compute_cross_window_momentum_reversal_trend(all_primary_surfaces)
        # Task 3 (Round 86, Gamma): cross-window batch consistency OLS trend.
        _bct86: dict[str, Any] = compute_cross_window_batch_consistency_trend(all_primary_surfaces)
        # Task 3 (Round 87, Gamma): cross-window regime spread OLS trend.
        _rsp87: dict[str, Any] = compute_cross_window_regime_spread_trend(all_primary_surfaces)
        # Task 3 (Round 88, Gamma): cross-window signal quality OLS trend.
        _sqt88: dict[str, Any] = compute_cross_window_signal_quality_trend(all_primary_surfaces)
        # Task 1 (Round 89, Alpha): cross-window open-gap persistence OLS trend.
        _ogp89: dict[str, Any] = compute_cross_window_open_gap_persistence_trend(all_primary_surfaces)
        # Task 2 (Round 89, Beta): cross-window tail flow quality OLS trend.
        _tf89: dict[str, Any] = compute_cross_window_tail_flow_quality_trend(all_primary_surfaces)
        # Task 3 (Round 89, Gamma): cross-window momentum IC direction consistency.
        _mc89: dict[str, Any] = compute_cross_window_momentum_ic_consistency(all_primary_surfaces)
        # Task 3 (Round 51, Gamma): cross-window profit-factor trend.
        _pf_trend: dict[str, Any] = compute_cross_window_profit_factor_trend(all_primary_surfaces)

        # Task 3 (Round 52, Gamma): cross-window Kelly fraction trend.
        _kelly_trend: dict[str, Any] = compute_cross_window_kelly_trend(all_primary_surfaces)

        # Task 3 (Round 53, Gamma): cross-window Information Ratio trend.
        _ir_trend: dict[str, Any] = compute_cross_window_ir_trend(all_primary_surfaces)

        # Task 3 (Round 54, Gamma): cross-window conditional factor synergy trend.
        _clt: dict[str, Any] = compute_cross_window_conditional_trend(all_primary_surfaces)
        # Task 3 (Round 55, Gamma): cross-window max-drawdown trend.
        _ddt: dict[str, Any] = compute_cross_window_drawdown_trend(all_primary_surfaces)
        # Task 1 (Round 55, Alpha): average decay_mean_ic across replay windows.
        _dmi_vals = [float(s["decay_mean_ic"]) for s in all_primary_surfaces if s.get("decay_mean_ic") is not None]
        avg_decay_mean_ic: "float | None" = round(sum(_dmi_vals) / len(_dmi_vals), 8) if _dmi_vals else None
        # Task 2 (Round 55, Beta): average time_seg_session_win_rate_spread across replay windows.
        _tsws_vals = [float(s["time_seg_session_win_rate_spread"]) for s in all_primary_surfaces if s.get("time_seg_session_win_rate_spread") is not None]
        avg_time_seg_session_win_rate_spread: "float | None" = round(sum(_tsws_vals) / len(_tsws_vals), 6) if _tsws_vals else None
        # Task 1 (Round 56, Alpha): average sdiv_diversification_score across replay windows.
        _ds_vals = [float(s["sdiv_diversification_score"]) for s in all_primary_surfaces if s.get("sdiv_diversification_score") is not None]
        avg_diversification_score: "float | None" = round(sum(_ds_vals) / len(_ds_vals), 6) if _ds_vals else None
        # Task 2 (Round 56, Beta): average rnkstab_rank_ic across replay windows.
        _ri_vals = [float(s["rnkstab_rank_ic"]) for s in all_primary_surfaces if s.get("rnkstab_rank_ic") is not None]
        avg_rank_ic: "float | None" = round(sum(_ri_vals) / len(_ri_vals), 8) if _ri_vals else None
        # Task 3 (Round 56, Gamma): cross-window mean-IC trend.
        _ict: dict[str, Any] = compute_cross_window_ic_trend(all_primary_surfaces)
        # Task 3 (Round 57, Gamma): cross-window rank-IC trend.
        _rict: dict[str, Any] = compute_cross_window_rank_ic_trend(all_primary_surfaces)
        # Task 3 (Round 58, Gamma): cross-window regime adaptability trend.
        _rat: dict[str, Any] = compute_cross_window_regime_trend(all_primary_surfaces)
        # Task 1 (Round 59, Alpha): average retdist_skewness across replay windows.
        _sk_vals = [float(s["retdist_skewness"]) for s in all_primary_surfaces if s.get("retdist_skewness") is not None]
        avg_skewness: "float | None" = round(sum(_sk_vals) / len(_sk_vals), 8) if _sk_vals else None
        # Task 2 (Round 59, Beta): average compq_composite_quality_score across replay windows.
        _cqs_vals = [float(s["compq_composite_quality_score"]) for s in all_primary_surfaces if s.get("compq_composite_quality_score") is not None]
        avg_composite_quality_score: "float | None" = round(sum(_cqs_vals) / len(_cqs_vals), 6) if _cqs_vals else None
        # Task 3 (Round 59, Gamma): cross-window optimal-threshold win-rate trend.
        _ttt: dict[str, Any] = compute_cross_window_threshold_trend(all_primary_surfaces)
        # Task 3 (Round 60, Gamma): cross-window composite quality score trend.
        _cqt: dict[str, Any] = compute_cross_window_quality_trend(all_primary_surfaces)
        # Task 3 (Round 61, Gamma): cross-window signal consistency trend.
        _ccst: dict[str, Any] = compute_cross_window_consistency_trend(all_primary_surfaces)
        # Task 3 (Round 62, Gamma): cross-window extreme market resilience trend.
        _crt: dict[str, Any] = compute_cross_window_resilience_trend(all_primary_surfaces)
        # Task 1 (Round 61, Alpha): average overfit_concentration_risk across replay windows.
        _ocr_vals = [float(s["overfit_concentration_risk"]) for s in all_primary_surfaces if s.get("overfit_concentration_risk") is not None]
        avg_concentration_risk: "float | None" = round(sum(_ocr_vals) / len(_ocr_vals), 6) if _ocr_vals else None
        # Task 2 (Round 61, Beta): average extreme_resilience_score across replay windows.
        _ers_vals = [float(s["extreme_resilience_score"]) for s in all_primary_surfaces if s.get("extreme_resilience_score") is not None]
        avg_resilience_score: "float | None" = round(sum(_ers_vals) / len(_ers_vals), 6) if _ers_vals else None
        # Task 1 (Round 62, Alpha): average liq_low_liquidity_pct across replay windows.
        _llp_vals = [float(s["liq_low_liquidity_pct"]) for s in all_primary_surfaces if s.get("liq_low_liquidity_pct") is not None]
        avg_low_liquidity_pct: "float | None" = round(sum(_llp_vals) / len(_llp_vals), 8) if _llp_vals else None
        # Task 2 (Round 62, Beta): average cost_cost_adjusted_profit_factor across replay windows.
        _capf_vals = [float(s["cost_cost_adjusted_profit_factor"]) for s in all_primary_surfaces if s.get("cost_cost_adjusted_profit_factor") is not None]
        avg_cost_adjusted_profit_factor: "float | None" = round(sum(_capf_vals) / len(_capf_vals), 8) if _capf_vals else None
        # Task 3 (Round 63, Gamma): cross-window cost-adjusted profit factor trend.
        _cpft: dict[str, Any] = compute_cross_window_cost_trend(all_primary_surfaces)
        # Task 1 (Round 63, Alpha): average sltp_best_profit_factor across replay windows.
        _sltp_bpf_vals = [float(s["sltp_best_profit_factor"]) for s in all_primary_surfaces if s.get("sltp_best_profit_factor") is not None]
        avg_best_profit_factor: "float | None" = round(sum(_sltp_bpf_vals) / len(_sltp_bpf_vals), 8) if _sltp_bpf_vals else None
        # Task 2 (Round 63, Beta): average combo_best_combo_win_rate across replay windows.
        _combo_bcwr_vals = [float(s["combo_best_combo_win_rate"]) for s in all_primary_surfaces if s.get("combo_best_combo_win_rate") is not None]
        avg_best_combo_win_rate: "float | None" = round(sum(_combo_bcwr_vals) / len(_combo_bcwr_vals), 8) if _combo_bcwr_vals else None
        # Task 3 (Round 64, Gamma): cross-window best combo win rate trend.
        _ccwt: dict[str, Any] = compute_cross_window_combo_trend(all_primary_surfaces)
        # Task 1 (Round 64, Alpha): average adaptive weight effective factor count across replay windows.
        _awef_vals = [float(s["weight_effective_factor_count"]) for s in all_primary_surfaces if s.get("weight_effective_factor_count") is not None]
        avg_adaptive_weight_effective_factor_count: "float | None" = round(sum(_awef_vals) / len(_awef_vals), 8) if _awef_vals else None
        # Task 2 (Round 64, Beta): average ic_stability across replay windows.
        _ics_vals = [float(s["validity_ic_stability"]) for s in all_primary_surfaces if s.get("validity_ic_stability") is not None]
        avg_ic_stability: "float | None" = round(sum(_ics_vals) / len(_ics_vals), 8) if _ics_vals else None
        # Task 3 (Round 65, Gamma): cross-window IC stability validity trend.
        _cvt: dict[str, Any] = compute_cross_window_validity_trend(all_primary_surfaces)
        # Task 1 (Round 65, Alpha): average attr_total_attribution across replay windows.
        _ata_vals = [float(s["attr_total_attribution"]) for s in all_primary_surfaces if s.get("attr_total_attribution") is not None]
        avg_total_attribution: "float | None" = round(sum(_ata_vals) / len(_ata_vals), 8) if _ata_vals else None
        # Task 2 (Round 65, Beta): average mtf_timeframe_consistency across replay windows.
        _mtfc_vals = [float(s["mtf_timeframe_consistency"]) for s in all_primary_surfaces if s.get("mtf_timeframe_consistency") is not None]
        avg_timeframe_consistency: "float | None" = round(sum(_mtfc_vals) / len(_mtfc_vals), 8) if _mtfc_vals else None
        # Task 1 (Round 66, Alpha): average vol_regime_edge across replay windows.
        _vre_vals = [float(s["vol_regime_edge"]) for s in all_primary_surfaces if s.get("vol_regime_edge") is not None]
        avg_vol_regime_edge: "float | None" = round(sum(_vre_vals) / len(_vre_vals), 8) if _vre_vals else None
        # Task 2 (Round 66, Beta): average interact_mean_interaction_effect across replay windows.
        _imie_vals = [float(s["interact_mean_interaction_effect"]) for s in all_primary_surfaces if s.get("interact_mean_interaction_effect") is not None]
        avg_interact_mean_interaction_effect: "float | None" = round(sum(_imie_vals) / len(_imie_vals), 8) if _imie_vals else None
        # Task 3 (Round 66, Gamma): cross-window total attribution trend.
        _cat: dict[str, Any] = compute_cross_window_attribution_trend(all_primary_surfaces)
        # Task 3 (Round 67, Gamma): cross-window nonlinear interaction trend.
        _cwit: dict[str, Any] = compute_cross_window_interaction_trend(all_primary_surfaces)
        # Task 3 (Round 68, Gamma): cross-window score dispersion trend.
        _cwdt: dict[str, Any] = compute_cross_window_dispersion_trend(all_primary_surfaces)
        # Task 3 (Round 69, Gamma): cross-window position concentration HHI trend.
        _cwcht: dict[str, Any] = compute_cross_window_concentration_trend(all_primary_surfaces)
        # Task 3 (Round 70, Gamma): cross-window RS rank spread trend.
        _cwrrt: dict[str, Any] = compute_cross_window_rs_rank_trend(all_primary_surfaces)
        # Task 3 (Round 71, Gamma): cross-window price position cs_win_rate_spread trend.
        _cwppt: dict[str, Any] = compute_cross_window_price_pos_trend(all_primary_surfaces)
        # Task 1 (Round 70, Alpha): average price_pos_cs_win_rate_spread across replay windows.
        _ppa_cwr_vals = [float(s["price_pos_cs_win_rate_spread"]) for s in all_primary_surfaces if s.get("price_pos_cs_win_rate_spread") is not None]
        avg_cs_win_rate_spread: "float | None" = round(sum(_ppa_cwr_vals) / len(_ppa_cwr_vals), 6) if _ppa_cwr_vals else None
        # Task 2 (Round 70, Beta): average streak_streak_ratio across replay windows.
        _wlsa_sr_vals = [float(s["streak_streak_ratio"]) for s in all_primary_surfaces if s.get("streak_streak_ratio") is not None]
        avg_streak_ratio: "float | None" = round(sum(_wlsa_sr_vals) / len(_wlsa_sr_vals), 6) if _wlsa_sr_vals else None
        # Task 1 (Round 71, Alpha): average mom_rank_momentum_win_spread across replay windows.
        _smr_mws_vals = [float(s["mom_rank_momentum_win_spread"]) for s in all_primary_surfaces if s.get("mom_rank_momentum_win_spread") is not None]
        avg_momentum_win_spread: "float | None" = round(sum(_smr_mws_vals) / len(_smr_mws_vals), 6) if _smr_mws_vals else None
        # Task 2 (Round 71, Beta): average vol_struct_vol_structure_spread across replay windows.
        _vsa_vss_vals = [float(s["vol_struct_vol_structure_spread"]) for s in all_primary_surfaces if s.get("vol_struct_vol_structure_spread") is not None]
        avg_vol_structure_spread: "float | None" = round(sum(_vsa_vss_vals) / len(_vsa_vss_vals), 6) if _vsa_vss_vals else None
        # Task 1 (Round 72, Alpha): average mfz_zscore_win_spread across replay windows.
        _mfz_zws_vals = [float(s["mfz_zscore_win_spread"]) for s in all_primary_surfaces if s.get("mfz_zscore_win_spread") is not None]
        avg_zscore_win_spread: "float | None" = round(sum(_mfz_zws_vals) / len(_mfz_zws_vals), 6) if _mfz_zws_vals else None
        # Task 2 (Round 72, Beta): average persist_persistence_score across replay windows.
        _persist_ps_vals = [float(s["persist_persistence_score"]) for s in all_primary_surfaces if s.get("persist_persistence_score") is not None]
        avg_persistence_score: "float | None" = round(sum(_persist_ps_vals) / len(_persist_ps_vals), 6) if _persist_ps_vals else None
        # Task 3 (Round 72, Gamma): cross-window momentum rank win-spread trend.
        _cwmrt: dict[str, Any] = compute_cross_window_momentum_rank_trend(all_primary_surfaces)
        # Task 1 (Round 73, Alpha): average breadth_breadth_win_rate across replay windows.
        _breadth_wr_vals = [float(s["breadth_breadth_win_rate"]) for s in all_primary_surfaces if s.get("breadth_breadth_win_rate") is not None]
        avg_breadth_win_rate: "float | None" = round(sum(_breadth_wr_vals) / len(_breadth_wr_vals), 6) if _breadth_wr_vals else None
        # Task 2 (Round 73, Beta): average ic_stab_ic_consistency_ratio across replay windows.
        _ic_stab_cr_vals = [float(s["ic_stab_ic_consistency_ratio"]) for s in all_primary_surfaces if s.get("ic_stab_ic_consistency_ratio") is not None]
        avg_ic_consistency_ratio: "float | None" = round(sum(_ic_stab_cr_vals) / len(_ic_stab_cr_vals), 6) if _ic_stab_cr_vals else None
        # Task 3 (Round 73, Gamma): cross-window Z-score win-spread trend.
        _cwzt: dict[str, Any] = compute_cross_window_zscore_trend(all_primary_surfaces)
        # Task 3 (Round 74, Gamma): cross-window market breadth win-rate trend.
        _cwbt: dict[str, Any] = compute_cross_window_breadth_trend(all_primary_surfaces)
        # Task 1 (Round 74, Alpha): average strat_stratification_spread across replay windows.
        _strat_ss_vals = [float(s["strat_stratification_spread"]) for s in all_primary_surfaces if s.get("strat_stratification_spread") is not None]
        avg_stratification_spread: "float | None" = round(sum(_strat_ss_vals) / len(_strat_ss_vals), 6) if _strat_ss_vals else None
        # Task 2 (Round 74, Beta): average cond_mom_conditional_momentum_edge across replay windows.
        _cme_vals = [float(s["cond_mom_conditional_momentum_edge"]) for s in all_primary_surfaces if s.get("cond_mom_conditional_momentum_edge") is not None]
        avg_conditional_momentum_edge: "float | None" = round(sum(_cme_vals) / len(_cme_vals), 6) if _cme_vals else None
        # Task 1 (Round 75, Alpha): average sharpe_sharpe_ratio across replay windows.
        _sharpe_r75_vals = [float(s["sharpe_sharpe_ratio"]) for s in all_primary_surfaces if s.get("sharpe_sharpe_ratio") is not None]
        avg_sharpe_r75: "float | None" = round(sum(_sharpe_r75_vals) / len(_sharpe_r75_vals), 6) if _sharpe_r75_vals else None
        # Task 2 (Round 75, Beta): average colin_max_collinearity across replay windows.
        _colin_mc_vals = [float(s["colin_max_collinearity"]) for s in all_primary_surfaces if s.get("colin_max_collinearity") is not None]
        avg_max_collinearity: "float | None" = round(sum(_colin_mc_vals) / len(_colin_mc_vals), 6) if _colin_mc_vals else None
        # Task 3 (Round 75, Gamma): cross-window stratification spread trend.
        _cwsst: dict[str, Any] = compute_cross_window_stratification_trend(all_primary_surfaces)
        # Task 1 (Round 76, Alpha): average skew_qual_gain_loss_ratio across replay windows.
        _skq_glr_vals = [float(s["skew_qual_gain_loss_ratio"]) for s in all_primary_surfaces if s.get("skew_qual_gain_loss_ratio") is not None]
        avg_gain_loss_ratio: "float | None" = round(sum(_skq_glr_vals) / len(_skq_glr_vals), 6) if _skq_glr_vals else None
        # Task 1 (Round 76, Alpha): average skew_qual_tail_asymmetry_score across replay windows.
        _skq_tas_vals = [float(s["skew_qual_tail_asymmetry_score"]) for s in all_primary_surfaces if s.get("skew_qual_tail_asymmetry_score") is not None]
        avg_tail_asymmetry_score: "float | None" = round(sum(_skq_tas_vals) / len(_skq_tas_vals), 6) if _skq_tas_vals else None
        # Task 2 (Round 76, Beta): average ortho_orthogonality_score across replay windows.
        _ortho_os_vals = [float(s["ortho_orthogonality_score"]) for s in all_primary_surfaces if s.get("ortho_orthogonality_score") is not None]
        avg_orthogonality_score: "float | None" = round(sum(_ortho_os_vals) / len(_ortho_os_vals), 6) if _ortho_os_vals else None
        # Task 3 (Round 76, Gamma): cross-window Sharpe trend (updated to use sharpe_sharpe_ratio from R75 T1 output).
        # Task 1 (Round 77, Alpha): average adapt_thr_threshold_lift across replay windows.
        _adapt_thr_lift_vals = [float(s["adapt_thr_threshold_lift"]) for s in all_primary_surfaces if s.get("adapt_thr_threshold_lift") is not None]
        avg_threshold_lift: "float | None" = round(sum(_adapt_thr_lift_vals) / len(_adapt_thr_lift_vals), 6) if _adapt_thr_lift_vals else None
        # Task 2 (Round 77, Beta): average sec_rot_sector_win_rate_dispersion across replay windows.
        _sec_rot_disp_vals = [float(s["sec_rot_sector_win_rate_dispersion"]) for s in all_primary_surfaces if s.get("sec_rot_sector_win_rate_dispersion") is not None]
        avg_sector_win_rate_dispersion: "float | None" = round(sum(_sec_rot_disp_vals) / len(_sec_rot_disp_vals), 6) if _sec_rot_disp_vals else None
        # Task 1 (Round 78, Alpha): average hotstock_hotstock_edge across replay windows.
        _hotstock_edge_vals = [float(s["hotstock_hotstock_edge"]) for s in all_primary_surfaces if s.get("hotstock_hotstock_edge") is not None]
        avg_hotstock_edge: "float | None" = round(sum(_hotstock_edge_vals) / len(_hotstock_edge_vals), 6) if _hotstock_edge_vals else None
        # Task 2 (Round 78, Beta): average robust_robustness_ratio across replay windows.
        _robustness_ratio_vals = [float(s["robust_robustness_ratio"]) for s in all_primary_surfaces if s.get("robust_robustness_ratio") is not None]
        avg_robustness_ratio: "float | None" = round(sum(_robustness_ratio_vals) / len(_robustness_ratio_vals), 6) if _robustness_ratio_vals else None
        # Task 1 (Round 79, Alpha): average sq_consist_quintile_monotonicity_score across replay windows.
        _sq_mono_vals = [float(s["sq_consist_quintile_monotonicity_score"]) for s in all_primary_surfaces if s.get("sq_consist_quintile_monotonicity_score") is not None]
        avg_sq_quintile_monotonicity_score: "float | None" = round(sum(_sq_mono_vals) / len(_sq_mono_vals), 6) if _sq_mono_vals else None
        # Task 1 (Round 79, Alpha): average sq_consist_quintile_top_bottom_spread across replay windows.
        _sq_tbs_vals = [float(s["sq_consist_quintile_top_bottom_spread"]) for s in all_primary_surfaces if s.get("sq_consist_quintile_top_bottom_spread") is not None]
        avg_sq_quintile_top_bottom_spread: "float | None" = round(sum(_sq_tbs_vals) / len(_sq_tbs_vals), 6) if _sq_tbs_vals else None
        # Task 2 (Round 79, Beta): average entry_qual_high_quality_entry_win_rate across replay windows.
        _eq_hqewr_vals = [float(s["entry_qual_high_quality_entry_win_rate"]) for s in all_primary_surfaces if s.get("entry_qual_high_quality_entry_win_rate") is not None]
        avg_entry_qual_high_quality_entry_win_rate: "float | None" = round(sum(_eq_hqewr_vals) / len(_eq_hqewr_vals), 6) if _eq_hqewr_vals else None
        # Task 2 (Round 79, Beta): average entry_qual_quality_entry_edge across replay windows.
        _eq_qee_vals = [float(s["entry_qual_quality_entry_edge"]) for s in all_primary_surfaces if s.get("entry_qual_quality_entry_edge") is not None]
        avg_entry_qual_quality_entry_edge: "float | None" = round(sum(_eq_qee_vals) / len(_eq_qee_vals), 6) if _eq_qee_vals else None

        return {
            "sharpe_ratio": avg_sharpe_r75 if avg_sharpe_r75 is not None else avg_sharpe,
            "sortino_ratio": avg_sortino_r35 if avg_sortino_r35 is not None else avg_sortino,
            "max_drawdown": avg_max_dd,
            "next_close_positive_rate": avg_next_close_positive_rate,
            "next_close_payoff_ratio": avg_next_close_payoff_ratio,
            "next_close_expectancy": avg_next_close_expectancy,
            "next_high_hit_rate": avg_next_high_hit_rate,
            "t_plus_2_close_positive_rate": avg_t_plus_2_close_positive_rate,
            "t_plus_2_close_payoff_ratio": avg_t_plus_2_close_payoff_ratio,
            "t_plus_3_close_positive_rate": avg_t_plus_3_close_positive_rate,
            "t_plus_3_close_expectancy": avg_t_plus_3_close_expectancy,
            "t_plus_3_close_payoff_ratio": avg_t_plus_3_close_payoff_ratio,
            "downside_p10": avg_downside_p10,
            "sample_weight": effective_sample_weight,
            "window_coverage": window_coverage,
            "window_count": window_count,
            "source_coverage_pass_ratio": source_coverage_pass_ratio,
            "projected_theme_exposure": avg_projected_theme_exposure,
            "incremental_theme_exposure": avg_incremental_theme_exposure,
            "liquidity_capacity_raw_100": avg_liquidity_capacity_raw_100,
            "crowding_risk_raw_100": avg_crowding_risk_raw_100,
            "gap_risk_raw_100": avg_gap_risk_raw_100,
            "max_future_high_return_2_5d_hit_rate_at_15pct": avg_runner_tail_hit_rate_15pct,
            "max_future_high_return_2_5d_hit_rate_at_20pct": avg_runner_tail_hit_rate,
            "runner_capture_count": total_runner_capture_count,
            "median_max_future_high_return_2_5d": median_max_future_high_return_2_5d,
            "time_to_hit_15pct_median": avg_time_to_hit_15pct,
            "time_to_hit_20pct_median": avg_time_to_hit_20pct,
            "runner_escape_rate": avg_runner_escape_rate,
            "avg_composite_score_escaped": avg_composite_score_escaped,
            # Task 1 (Round 11): per-factor IC and quality fraction
            "ic_positive_factor_fraction": ic_positive_factor_fraction,
            **{f"avg_factor_ic_{f}": avg_factor_ics.get(f) for f in BTST_FACTOR_NAMES},
            # Task 3 (Round 11): candidate pool quality
            "candidate_pool_avg_composite_score": avg_candidate_pool_composite_score,
            # Task 1 (Round 12): T+1 intraday drawdown tail-risk metric
            "t_plus_1_intraday_drawdown_p10": avg_t_plus_1_intraday_drawdown_p10,
            # Task 3 (Round 12): IC weight suggestions (majority-vote across replay windows)
            "ic_weight_suggestions": aggregated_ic_weight_suggestions,
            # Task 1 (Round 20, Beta): realized payoff ratio — win/loss asymmetry quality guardrail.
            "realized_payoff_ratio": avg_realized_payoff_ratio,
            # Task 1 (Round 21, Gamma): surface metric / win-rate Spearman correlations.
            # surface_metric_correlations: {metric_name: corr} for all numeric scalar surface metrics.
            # top_5_correlated_metrics / bottom_5_correlated_metrics embedded inside the dict.
            "surface_metric_correlations": surface_metric_correlations,
            "top_5_surface_correlated_metrics": surface_metric_correlations.get("top_5_correlated_metrics"),
            "bottom_5_surface_correlated_metrics": surface_metric_correlations.get("bottom_5_correlated_metrics"),
            # Task 2 (Round 21, Alpha): factor IC stability across replay windows.
            # factor_ic_stability: per-factor mean_IC, std_IC, IR, positive_fraction + summary keys.
            "factor_ic_stability": factor_ic_stability,
            "most_stable_factor": factor_ic_stability.get("most_stable_factor"),
            "least_stable_factor": factor_ic_stability.get("least_stable_factor"),
            # Task 1 (Round 22, Gamma): low-impact PROBE_GRID axis identification.
            # low_impact_axes: probe-grid keys with |surface_corr| < threshold.
            # low_ir_factors: factor names with IC IR < threshold.
            # pruning_candidates: axes satisfying BOTH criteria (strongest pruning signal).
            "low_impact_probe_axes": low_impact_probe_axes,
            "pruning_candidates": low_impact_probe_axes.get("pruning_candidates"),
            "low_ir_factors": low_impact_probe_axes.get("low_ir_factors"),
            # Task 1 (Round 24): IC temporal trend across replay windows.
            # decaying_factor_count: number of factors whose IC declined significantly (trend < −0.02).
            # most_decaying_factor / most_improving_factor: summary extremes for advisory display.
            "factor_ic_temporal_trend": factor_ic_temporal_trend,
            "decaying_factor_count": factor_ic_temporal_trend.get("decaying_factor_count"),
            "decaying_factors": factor_ic_temporal_trend.get("decaying_factors"),
            "most_decaying_factor": factor_ic_temporal_trend.get("most_decaying_factor"),
            "most_improving_factor": factor_ic_temporal_trend.get("most_improving_factor"),
            # Task 2 (Round 24): sample-weighted average drawdown-adjusted Kelly fraction.
            # kelly_fraction_drawdown_adjusted: half-Kelly reduced by T+1 intraday drawdown risk.
            "kelly_fraction_drawdown_adjusted": avg_kelly_fraction_drawdown_adjusted,
            # Task 3 (Round 24): walk-forward verdict calibration.
            # verdict_calibration_score: normalised spread between promotable and probation win rates.
            # verdict_monotone: True when promotable_wr > watch_wr > probation_wr.
            "verdict_calibration": verdict_calibration,
            "verdict_calibration_score": verdict_calibration.get("verdict_calibration_score"),
            "verdict_monotone": verdict_calibration.get("verdict_monotone"),
            # Task 1 (Round 25, Gamma): comprehensive profile health score (0-100).
            # profile_health_score: aggregated quality score across 10 sub-dimensions.
            # profile_health_grade: "A"(≥80) | "B"(≥60) | "C"(≥40) | "D"(<40).
            "profile_health_score": evaluator_health.get("profile_health_score"),
            "profile_health_grade": evaluator_health.get("profile_health_grade"),
            "evaluator_health_subscores": evaluator_health.get("health_subscores"),
            # Task 2 (Round 25, Beta): selection churn / window-stability metrics.
            # win_rate_window_volatility: mean absolute difference between consecutive window win rates.
            # win_rate_window_trend: linear regression slope (% pts per window; positive = improving).
            "selection_churn": selection_churn,
            "win_rate_window_volatility": selection_churn.get("win_rate_window_volatility"),
            "win_rate_window_trend": selection_churn.get("win_rate_window_trend"),
            "estimated_cost_drag_bps": selection_churn.get("estimated_cost_drag_bps"),
            # Task 3 (Round 25, Alpha): auto-calibrated quality floor suggestions.
            # floor_suggestions_summary: compact advisory listing only the easy / strict metrics.
            "floor_suggestions": floor_suggestions_result.get("floor_suggestions"),
            "floor_suggestions_summary": floor_suggestions_summary,
            # Task 3 (Round 27, Beta): liquidity-aware position guidance aggregated across windows.
            # recommended_max_positions: integer average of per-window position sizing recommendations.
            # concentration_risk_level: derived from avg pool → avg recommended_max_positions.
            "recommended_max_positions": avg_recommended_max_positions,
            "concentration_risk_level": _concentration_risk_level,
            # Task 1 (Round 30, Gamma): parameter stability metrics — cross-window drift of surface metrics.
            # param_drift_score: median relative drift (std / range); lower = more stable parameters.
            # parameter_stability_grade: A(<0.15) / B(<0.30) / C(<0.50) / D(≥0.50).
            "param_stability_metrics": param_stability,
            "param_drift_score": param_stability.get("param_drift_score"),
            "parameter_stability_grade": param_stability.get("parameter_stability_grade"),
            "most_stable_param": param_stability.get("most_stable_param"),
            "most_unstable_param": param_stability.get("most_unstable_param"),
            # Task 2 (Round 30, Alpha): monthly win-rate spread — captures seasonal calendar effects.
            "monthly_win_rate_spread": avg_monthly_win_rate_spread,
            # Task 3 (Round 30, Beta): nonlinear factor count — number of factors with U-shape/threshold effects.
            "nonlinear_factor_count": avg_nonlinear_factor_count,
            "avg_nonlinearity_ratio": avg_nonlinearity_ratio,
            # Task 1 (Round 31, Alpha): return autocorrelation lag-1 — average across replay windows.
            "autocorr_lag1": avg_autocorr_lag1,
            # Task 2 (Round 31, Gamma): composite score stability across windows.
            "score_stability_across_windows": _score_stability,
            "score_cv_across_windows": _score_stability.get("score_cv_across_windows"),
            "score_mean_across_windows": _score_stability.get("score_mean_across_windows"),
            "score_trend_across_windows": _score_stability.get("score_trend_across_windows"),
            "score_system_stable": _score_stability.get("score_system_stable"),
            # Task 1 (Round 33, Alpha): expected value per trade — average across replay windows.
            "expected_value_per_trade": avg_expected_value_per_trade,
            # Task 2 (Round 33, Gamma): momentum decay half-life — average across replay windows.
            "momentum_half_life_days": avg_momentum_half_life_days,
            # Task 3 (Round 33, Beta): IC trend across replay windows.
            "factor_ic_trend": _ic_trend,
            "ic_trend_stability": _ic_trend.get("ic_trend_stability"),
            "factor_ic_trend_deteriorating": _ic_trend.get("factor_ic_trend_deteriorating"),
            "declining_ic_factors": _ic_trend.get("declining_factors"),
            # Task 1 (Round 34, Alpha): multi-factor conditional lift — average across replay windows.
            "multi_factor_lift": avg_multi_factor_lift,
            # Task 2 (Round 34, Gamma): adaptive sizing score — average across replay windows.
            "adaptive_sizing_score": avg_adaptive_sizing_score,
            # Task 3 (Round 34, Beta): signal churn metrics — cross-window candidate pool stability.
            "signal_churn_metrics": _signal_churn,
            "signal_churn_rate": _signal_churn.get("signal_churn_rate"),
            "avg_signal_persistence": _signal_churn.get("avg_signal_persistence"),
            "avg_pool_size_churn": _signal_churn.get("avg_pool_size_churn"),
            "pool_stable": _signal_churn.get("pool_stable"),
            # Task 1 (Round 35, Alpha): Sortino ratio is now returned via avg_sortino_r35 above.
            # Task 2 (Round 35, Gamma): quality trend analysis — fraction of quality metrics improving.
            "quality_trend_analysis": _quality_trend,
            "quality_trend_score": _quality_trend.get("quality_trend_score"),
            "quality_trend_improving": _quality_trend.get("quality_trend_improving"),
            "quality_trend_grade": _quality_trend.get("quality_trend_grade"),
            # Task 3 (Round 35, Beta): average candidate diversity score across replay windows.
            "diversity_score": avg_diversity_score,
            # Task 1 (Round 36, Alpha): average right-tail dominance across replay windows.
            "right_tail_dominance": avg_right_tail_dominance,
            # Task 2 (Round 36, Beta): average composite score Spearman IC across replay windows.
            "composite_ic": avg_composite_ic,
            # Task 3 (Round 36, Gamma): average win-rate bootstrap CI width across replay windows.
            "win_rate_ci_width": avg_win_rate_ci_width,
            # Task 1 (Round 37, Alpha): mode optimal holding days across replay windows.
            "optimal_holding_days": avg_optimal_holding_days,
            # Task 2 (Round 37, Beta): average loss signature strength across replay windows.
            "loss_signature_strength": avg_loss_signature_strength,
            # Task 3 (Round 37, Gamma): average score Gini coefficient across replay windows.
            "score_gini": avg_score_gini,
            # Task 1 (Round 38, Alpha): average market environment win-rate gap across replay windows.
            "env_win_rate_gap": avg_env_win_rate_gap,
            # Task 2 (Round 38, Beta): average positive-IC factor count across replay windows.
            "positive_ic_factor_count": avg_positive_ic_factor_count,
            # Task 3 (Round 38, Gamma): average top quintile premium across replay windows.
            "top_quintile_premium": avg_top_quintile_premium,
            # Task 1 (Round 39, Alpha): average recency win-rate gap across replay windows.
            "recency_win_rate_gap": avg_recency_win_rate_gap,
            # Task 2 (Round 39, Beta): average optimal threshold lift across replay windows.
            "optimal_threshold_lift": avg_optimal_threshold_lift,
            # Task 3 (Round 39, Gamma): average recovery factor across replay windows.
            "recovery_factor": avg_recovery_factor,
            # Task 3 (Round 39, Gamma): average max drawdown simulated across replay windows.
            "max_drawdown_simulated": avg_max_drawdown_simulated,
            # Task 1 (Round 40, Alpha): average max_synergy_lift across replay windows.
            "max_synergy_lift": avg_max_synergy_lift,
            # Task 2 (Round 40, Beta): average high_vs_low_lift across replay windows.
            "high_vs_low_lift": avg_high_vs_low_lift,
            # Task 3 (Round 40, Gamma): cross-window factor drift score.
            "factor_drift_score": avg_factor_drift_score,
            "factor_exposure_stable": _cfe.get("factor_exposure_stable"),
            "most_drifting_metric": _cfe.get("most_drifting_metric"),
            "least_drifting_metric": _cfe.get("least_drifting_metric"),
            # Task 1 (Round 41, Alpha): factor IC rank consistency score across windows.
            "factor_rank_consistency_score": avg_factor_rank_consistency_score,
            "top_factor_stable": _frc.get("top_factor_stable"),
            "most_consistent_factor": _frc.get("most_consistent_factor"),
            "most_volatile_rank_factor": _frc.get("most_volatile_rank_factor"),
            # Task 2 (Round 41, Beta): average vol_price_alignment_rate across replay windows.
            "vol_price_alignment_rate": avg_vol_price_alignment_rate,
            # Task 3 (Round 41, Gamma): average combined_significance_score across replay windows.
            "combined_significance_score": avg_combined_significance_score,
            # Task 1 (Round 42, Alpha): average calibration slope across replay windows.
            "calibration_slope": avg_calibration_slope,
            # Task 2 (Round 42, Beta): average close-strength top-quartile premium across replay windows.
            "cs_top_quartile_premium": avg_cs_top_quartile_premium,
            # Task 3 (Round 42, Gamma): cross-window consensus score.
            "consensus_windows_pct": _wconsensus.get("consensus_windows_pct"),
            "strategy_consistently_valid": _wconsensus.get("strategy_consistently_valid"),
            "consensus_grade": _wconsensus.get("consensus_grade"),
            "best_consensus_window_idx": _wconsensus.get("best_consensus_window_idx"),
            # Task 1 (Round 43, Alpha): average profit factor across replay windows.
            "profit_factor": avg_profit_factor,
            # Task 2 (Round 43, Beta): average high-vs-low sentiment lift across replay windows.
            "high_vs_low_sentiment_lift": avg_high_vs_low_sentiment_lift,
            # Task 3 (Round 43, Gamma): score momentum trend across replay windows.
            "score_trend_normalized": _smt.get("score_trend_normalized"),
            "score_trend_slope": _smt.get("score_trend_slope"),
            "score_momentum_positive": _smt.get("score_momentum_positive"),
            "score_trend_acceleration": _smt.get("score_trend_acceleration"),
            "score_trend_grade": _smt.get("score_trend_grade"),
            # Task 3 (Round 44, Gamma): win-rate stability across replay windows.
            "win_rate_cv": _wrst.get("win_rate_cv"),
            "win_rate_mean": _wrst.get("win_rate_mean"),
            "win_rate_std": _wrst.get("win_rate_std"),
            "win_rate_min": _wrst.get("win_rate_min"),
            "win_rate_max": _wrst.get("win_rate_max"),
            "win_rate_range": _wrst.get("win_rate_range"),
            "win_rate_stability_grade": _wrst.get("win_rate_stability_grade"),
            "win_rate_stability_valid": _wrst.get("win_rate_stability_valid"),
            # Task 3 (Round 45, Gamma): top-candidate cross-window consistency.
            "top_candidate_consistency_rate": _tccs.get("top_candidate_consistency_rate"),
            "top_candidate_mean_win_rate": _tccs.get("top_candidate_mean_win_rate"),
            "top_candidate_best_win_rate": _tccs.get("top_candidate_best_win_rate"),
            "top_candidate_consistency_grade": _tccs.get("top_candidate_consistency_grade"),
            # Task 3 (Round 46, Gamma): cross-window gate consistency.
            "gate_above_threshold_mean": _cgc.get("gate_above_threshold_mean"),
            "gate_above_threshold_std": _cgc.get("gate_above_threshold_std"),
            "gate_above_threshold_cv": _cgc.get("gate_above_threshold_cv"),
            "gate_above_threshold_min": _cgc.get("gate_above_threshold_min"),
            "gate_above_threshold_max": _cgc.get("gate_above_threshold_max"),
            "gate_consistency_grade": _cgc.get("gate_consistency_grade"),
            # Task 3 (Round 47, Gamma): cross-window factor IC positive consistency.
            "positive_ic_consistency_rate": _fic.get("positive_ic_consistency_rate"),
            "consistent_factor_count": _fic.get("consistent_factor_count"),
            "best_factor_name": _fic.get("best_factor_name"),
            "worst_factor_name": _fic.get("worst_factor_name"),
            "factor_ic_consistency_valid": _fic.get("factor_ic_consistency_valid"),
            # Task 3 (Round 48, Gamma): cross-window expected-value trend.
            "ev_trend_slope": _ev_trend.get("ev_trend_slope"),
            "ev_trend_normalized": _ev_trend.get("ev_trend_normalized"),
            "ev_mean": _ev_trend.get("ev_mean"),
            "ev_std": _ev_trend.get("ev_std"),
            "ev_min": _ev_trend.get("ev_min"),
            "ev_max": _ev_trend.get("ev_max"),
            "ev_trend_grade": _ev_trend.get("ev_trend_grade"),
            # Task 3 (Round 49, Gamma): cross-window Sortino trend.
            "sortino_trend_slope": _sortino_trend.get("sortino_trend_slope"),
            "sortino_mean": _sortino_trend.get("sortino_mean"),
            "sortino_std": _sortino_trend.get("sortino_std"),
            "sortino_trend_grade": _sortino_trend.get("sortino_trend_grade"),
            "sortino_positive_windows_pct": _sortino_trend.get("sortino_positive_windows_pct"),
            "sortino_trend_valid": _sortino_trend.get("sortino_trend_valid"),
            # Task 3 (Round 50, Gamma): cross-window Sharpe trend.
            "sharpe_trend_slope": _sharpe_trend.get("sharpe_trend_slope"),
            "sharpe_mean": _sharpe_trend.get("sharpe_mean"),
            "sharpe_std": _sharpe_trend.get("sharpe_std"),
            "sharpe_min": _sharpe_trend.get("sharpe_min"),
            "sharpe_max": _sharpe_trend.get("sharpe_max"),
            "sharpe_trend_grade": _sharpe_trend.get("sharpe_trend_grade"),
            "sharpe_positive_windows_pct": _sharpe_trend.get("sharpe_positive_windows_pct"),
            "sharpe_trend_valid": _sharpe_trend.get("sharpe_trend_valid"),
            # Task 1 (Round 51, Alpha): win/loss magnitude ratio and Kelly fraction.
            "win_loss_magnitude_ratio": avg_win_loss_magnitude_ratio,
            "kelly_fraction": avg_kelly_fraction,
            # Task 2 (Round 51, Beta): outlier dependency ratio.
            "outlier_dependency_ratio": avg_outlier_dependency_ratio,
            # Task 3 (Round 51, Gamma): cross-window profit-factor trend.
            "pf_trend_slope": _pf_trend.get("pf_trend_slope"),
            "pf_mean": _pf_trend.get("pf_mean"),
            "pf_std": _pf_trend.get("pf_std"),
            "pf_min": _pf_trend.get("pf_min"),
            "pf_max": _pf_trend.get("pf_max"),
            "pf_trend_grade": _pf_trend.get("pf_trend_grade"),
            "pf_above_one_pct": _pf_trend.get("pf_above_one_pct"),
            "pf_trend_valid": _pf_trend.get("pf_trend_valid"),
            # Task 3 (Round 52, Gamma): cross-window Kelly fraction trend.
            "kelly_trend_slope": _kelly_trend.get("kelly_trend_slope"),
            "kelly_mean": _kelly_trend.get("kelly_mean"),
            "kelly_std": _kelly_trend.get("kelly_std"),
            "kelly_min": _kelly_trend.get("kelly_min"),
            "kelly_max": _kelly_trend.get("kelly_max"),
            "kelly_trend_grade": _kelly_trend.get("kelly_trend_grade"),
            "kelly_positive_windows_pct": _kelly_trend.get("kelly_positive_windows_pct"),
            "kelly_trend_valid": _kelly_trend.get("kelly_trend_valid"),
            # Task 3 (Round 53, Gamma): cross-window Information Ratio trend.
            "ir_trend_slope": _ir_trend.get("ir_trend_slope"),
            "ir_trend_mean": _ir_trend.get("ir_trend_mean"),
            "ir_trend_std": _ir_trend.get("ir_trend_std"),
            "ir_trend_min": _ir_trend.get("ir_trend_min"),
            "ir_trend_max": _ir_trend.get("ir_trend_max"),
            "ir_trend_grade": _ir_trend.get("ir_trend_grade"),
            "ir_positive_windows_pct": _ir_trend.get("ir_positive_windows_pct"),
            "ir_trend_valid": _ir_trend.get("ir_trend_valid"),
            # Task 3 (Round 54, Gamma): cross-window conditional factor synergy trend.
            "conditional_lift_trend_slope": _clt.get("conditional_lift_trend_slope"),
            "conditional_lift_trend_mean": _clt.get("conditional_lift_trend_mean"),
            "conditional_lift_trend_min": _clt.get("conditional_lift_trend_min"),
            "conditional_lift_trend_max": _clt.get("conditional_lift_trend_max"),
            "conditional_positive_windows_pct": _clt.get("conditional_positive_windows_pct"),
            "conditional_trend_grade": _clt.get("conditional_trend_grade"),
            "conditional_lift_trend_valid": _clt.get("conditional_lift_trend_valid"),
            # Task 3 (Round 55, Gamma): cross-window max-drawdown trend.
            "drawdown_trend_slope": _ddt.get("drawdown_trend_slope"),
            "drawdown_trend_mean": _ddt.get("drawdown_trend_mean"),
            "drawdown_trend_min": _ddt.get("drawdown_trend_min"),
            "drawdown_trend_max": _ddt.get("drawdown_trend_max"),
            "drawdown_improving_windows_pct": _ddt.get("drawdown_improving_windows_pct"),
            "drawdown_trend_grade": _ddt.get("drawdown_trend_grade"),
            "drawdown_trend_valid": _ddt.get("drawdown_trend_valid"),
            # Task 1 (Round 55, Alpha): multi-factor mean IC averaged across windows.
            "decay_mean_ic": avg_decay_mean_ic,
            "mean_ic": avg_decay_mean_ic,
            # Task 2 (Round 55, Beta): intraday session win-rate spread averaged across windows.
            "time_seg_session_win_rate_spread": avg_time_seg_session_win_rate_spread,
            # Task 1 (Round 56, Alpha): sector diversification score averaged across windows.
            "diversification_score": avg_diversification_score,
            # Task 2 (Round 56, Beta): score rank IC averaged across windows.
            "rank_ic": avg_rank_ic,
            # Task 3 (Round 56, Gamma): cross-window mean-IC trend.
            "ic_trend_slope": _ict.get("ic_trend_slope"),
            "ic_trend_mean": _ict.get("ic_trend_mean"),
            "ic_trend_min": _ict.get("ic_trend_min"),
            "ic_trend_max": _ict.get("ic_trend_max"),
            "ic_positive_windows_pct": _ict.get("ic_positive_windows_pct"),
            "ic_trend_grade": _ict.get("ic_trend_grade"),
            "ic_trend_valid": _ict.get("ic_trend_valid"),
            # Task 3 (Round 57, Gamma): cross-window rank-IC trend.
            "rank_ic_trend_slope": _rict.get("rank_ic_trend_slope"),
            "rank_ic_trend_mean": _rict.get("rank_ic_trend_mean"),
            "rank_ic_trend_min": _rict.get("rank_ic_trend_min"),
            "rank_ic_trend_max": _rict.get("rank_ic_trend_max"),
            "rank_ic_positive_windows_pct": _rict.get("rank_ic_positive_windows_pct"),
            "rank_ic_trend_grade": _rict.get("rank_ic_trend_grade"),
            "rank_ic_trend_valid": _rict.get("rank_ic_trend_valid"),
            # Task 3 (Round 58, Gamma): cross-window regime adaptability trend.
            "regime_trend_slope": _rat.get("regime_trend_slope"),
            "regime_trend_mean": _rat.get("regime_trend_mean"),
            "regime_trend_min": _rat.get("regime_trend_min"),
            "regime_trend_max": _rat.get("regime_trend_max"),
            "regime_above_floor_pct": _rat.get("regime_above_floor_pct"),
            "regime_trend_grade": _rat.get("regime_trend_grade"),
            "regime_trend_valid": _rat.get("regime_trend_valid"),
            # Task 1 (Round 59, Alpha): return distribution skewness averaged across windows.
            "skewness": avg_skewness,
            # Task 2 (Round 59, Beta): composite quality score averaged across windows.
            "composite_quality_score": avg_composite_quality_score,
            # Task 3 (Round 59, Gamma): cross-window optimal-threshold win-rate trend.
            "threshold_win_rate_trend_slope": _ttt.get("threshold_win_rate_trend_slope"),
            "threshold_win_rate_trend_mean": _ttt.get("threshold_win_rate_trend_mean"),
            "threshold_win_rate_trend_min": _ttt.get("threshold_win_rate_trend_min"),
            "threshold_win_rate_trend_max": _ttt.get("threshold_win_rate_trend_max"),
            "threshold_above_floor_pct": _ttt.get("threshold_above_floor_pct"),
            "threshold_trend_grade": _ttt.get("threshold_trend_grade"),
            "threshold_trend_valid": _ttt.get("threshold_trend_valid"),
            # Task 3 (Round 60, Gamma): cross-window composite quality score trend.
            "quality_score_trend_slope": _cqt.get("quality_score_trend_slope"),
            "quality_score_trend_mean": _cqt.get("quality_score_trend_mean"),
            "quality_score_trend_min": _cqt.get("quality_score_trend_min"),
            "quality_score_trend_max": _cqt.get("quality_score_trend_max"),
            "quality_above_floor_pct": _cqt.get("quality_above_floor_pct"),
            "composite_quality_trend_grade": _cqt.get("quality_trend_grade"),
            "quality_trend_valid": _cqt.get("quality_trend_valid"),
            # Task 1 (Round 61, Alpha): concentration_risk averaged across windows.
            "concentration_risk": avg_concentration_risk,
            # Task 2 (Round 61, Beta): resilience_score averaged across windows.
            "resilience_score": avg_resilience_score,
            # Task 3 (Round 61, Gamma): cross-window signal consistency trend.
            "consistency_trend_slope": _ccst.get("consistency_trend_slope"),
            "consistency_trend_mean": _ccst.get("consistency_trend_mean"),
            "consistency_trend_min": _ccst.get("consistency_trend_min"),
            "consistency_trend_max": _ccst.get("consistency_trend_max"),
            "consistency_positive_windows_pct": _ccst.get("consistency_positive_windows_pct"),
            "consistency_trend_grade": _ccst.get("consistency_trend_grade"),
            "consistency_trend_valid": _ccst.get("consistency_trend_valid"),
            # Task 1 (Round 62, Alpha): low-liquidity fraction averaged across windows.
            "low_liquidity_pct": avg_low_liquidity_pct,
            # Task 2 (Round 62, Beta): cost-adjusted profit factor averaged across windows.
            "cost_adjusted_profit_factor": avg_cost_adjusted_profit_factor,
            # Task 3 (Round 62, Gamma): cross-window extreme market resilience trend.
            "resilience_trend_slope": _crt.get("resilience_trend_slope"),
            "resilience_trend_mean": _crt.get("resilience_trend_mean"),
            "resilience_trend_min": _crt.get("resilience_trend_min"),
            "resilience_trend_max": _crt.get("resilience_trend_max"),
            "resilience_above_floor_pct": _crt.get("resilience_above_floor_pct"),
            "resilience_trend_grade": _crt.get("resilience_trend_grade"),
            "resilience_trend_valid": _crt.get("resilience_trend_valid"),
            # Task 1 (Round 63, Alpha): best stop-loss/take-profit profit factor averaged across windows.
                "best_profit_factor": avg_best_profit_factor,
                # Task 2 (Round 63, Beta): best factor-combination win rate averaged across windows.
                "best_combo_win_rate": avg_best_combo_win_rate,
                # Task 3 (Round 63, Gamma): cross-window cost-adjusted profit factor trend.
                "cost_pf_trend_slope": _cpft.get("cost_pf_trend_slope"),
                "cost_pf_trend_mean": _cpft.get("cost_pf_trend_mean"),
                "cost_pf_trend_min": _cpft.get("cost_pf_trend_min"),
                "cost_pf_trend_max": _cpft.get("cost_pf_trend_max"),
                "cost_pf_above_floor_pct": _cpft.get("cost_pf_above_floor_pct"),
                "cost_pf_trend_grade": _cpft.get("cost_pf_trend_grade"),
                "cost_pf_trend_valid": _cpft.get("cost_pf_trend_valid"),
                # Task 3 (Round 64, Gamma): cross-window best combo win rate trend.
                "combo_win_rate_trend_slope": _ccwt.get("combo_win_rate_trend_slope"),
                "combo_win_rate_trend_mean": _ccwt.get("combo_win_rate_trend_mean"),
                "combo_win_rate_trend_min": _ccwt.get("combo_win_rate_trend_min"),
                "combo_win_rate_trend_max": _ccwt.get("combo_win_rate_trend_max"),
                "combo_above_floor_pct": _ccwt.get("combo_above_floor_pct"),
                "combo_trend_grade": _ccwt.get("combo_trend_grade"),
                "combo_trend_valid": _ccwt.get("combo_trend_valid"),
                # Task 1 (Round 64, Alpha): adaptive weight effective factor count averaged across windows.
                "adaptive_weight_effective_factor_count": avg_adaptive_weight_effective_factor_count,
                # Task 2 (Round 64, Beta): IC stability averaged across windows.
                "ic_stability": avg_ic_stability,
                # Task 1 (Round 65, Alpha): total attribution averaged across windows.
                "total_attribution": avg_total_attribution,
                # Task 2 (Round 65, Beta): multi-timeframe consistency averaged across windows.
                "timeframe_consistency": avg_timeframe_consistency,
                # Task 3 (Round 65, Gamma): cross-window IC stability trend.
                "ic_stability_trend_slope": _cvt.get("ic_stability_trend_slope"),
                "ic_stability_trend_mean": _cvt.get("ic_stability_trend_mean"),
                "ic_stability_trend_min": _cvt.get("ic_stability_trend_min"),
                "ic_stability_trend_max": _cvt.get("ic_stability_trend_max"),
                "ic_stability_below_cap_pct": _cvt.get("ic_stability_below_cap_pct"),
                "ic_stability_trend_grade": _cvt.get("ic_stability_trend_grade"),
                "ic_stability_trend_valid": _cvt.get("ic_stability_trend_valid"),
                # Task 1 (Round 66, Alpha): volatility regime edge averaged across windows.
                "vol_regime_edge": avg_vol_regime_edge,
                # Task 2 (Round 66, Beta): mean nonlinear interaction effect averaged across windows.
                "interact_mean_interaction_effect": avg_interact_mean_interaction_effect,
                # Task 3 (Round 66, Gamma): cross-window total attribution trend.
                "attribution_trend_slope": _cat.get("attribution_trend_slope"),
                "attribution_trend_mean": _cat.get("attribution_trend_mean"),
                "attribution_trend_min": _cat.get("attribution_trend_min"),
                "attribution_trend_max": _cat.get("attribution_trend_max"),
                "attribution_above_floor_pct": _cat.get("attribution_above_floor_pct"),
                "attribution_trend_grade": _cat.get("attribution_trend_grade"),
                "attribution_trend_valid": _cat.get("attribution_trend_valid"),
                # Task 3 (Round 67, Gamma): cross-window nonlinear interaction trend.
                "interaction_trend_slope": _cwit.get("interaction_trend_slope"),
                "interaction_trend_mean": _cwit.get("interaction_trend_mean"),
                "interaction_positive_windows_pct": _cwit.get("interaction_positive_windows_pct"),
                "interaction_trend_grade": _cwit.get("interaction_trend_grade"),
                "interaction_trend_valid": _cwit.get("interaction_trend_valid"),
                # Task 3 (Round 68, Gamma): cross-window score dispersion trend.
                "dispersion_trend_slope": _cwdt.get("dispersion_trend_slope"),
                "dispersion_trend_mean": _cwdt.get("dispersion_trend_mean"),
                "dispersion_positive_windows_pct": _cwdt.get("dispersion_positive_windows_pct"),
                "dispersion_trend_grade": _cwdt.get("dispersion_trend_grade"),
                "dispersion_trend_valid": _cwdt.get("dispersion_trend_valid"),
                # Task 3 (Round 69, Gamma): cross-window position concentration HHI trend.
                "concentration_hhi_slope": _cwcht.get("concentration_hhi_slope"),
                "concentration_hhi_mean": _cwcht.get("concentration_hhi_mean"),
                "concentration_dispersed_windows_pct": _cwcht.get("concentration_dispersed_windows_pct"),
                "concentration_trend_grade": _cwcht.get("concentration_trend_grade"),
                "concentration_trend_valid": _cwcht.get("concentration_trend_valid"),
                # Task 3 (Round 70, Gamma): cross-window RS rank spread trend.
                "rs_rank_trend_slope": _cwrrt.get("rs_rank_trend_slope"),
                "rs_rank_trend_mean": _cwrrt.get("rs_rank_trend_mean"),
                "rs_rank_positive_windows_pct": _cwrrt.get("rs_rank_positive_windows_pct"),
                "rs_rank_trend_grade": _cwrrt.get("rs_rank_trend_grade"),
                "rs_rank_trend_valid": _cwrrt.get("rs_rank_trend_valid"),
                # Task 1 (Round 70, Alpha): price position win-rate spread averaged across windows.
                "cs_win_rate_spread": avg_cs_win_rate_spread,
                # Task 2 (Round 70, Beta): win/loss streak ratio averaged across windows.
                "streak_ratio": avg_streak_ratio,
                # Task 1 (Round 71, Alpha): sector momentum ranking win-rate spread averaged across windows.
                "momentum_win_spread": avg_momentum_win_spread,
                # Task 2 (Round 71, Beta): volume structure win-rate spread averaged across windows.
                "vol_structure_spread": avg_vol_structure_spread,
                # Task 3 (Round 71, Gamma): cross-window price position cs_win_rate_spread trend.
                "price_pos_trend_slope": _cwppt.get("price_pos_trend_slope"),
                "price_pos_trend_mean": _cwppt.get("price_pos_trend_mean"),
                "price_pos_positive_windows_pct": _cwppt.get("price_pos_positive_windows_pct"),
                "price_pos_trend_grade": _cwppt.get("price_pos_trend_grade"),
                "price_pos_trend_valid": _cwppt.get("price_pos_trend_valid"),
                # Task 1 (Round 72, Alpha): multi-factor composite Z-score win-rate spread averaged across windows.
                "zscore_win_spread": avg_zscore_win_spread,
                # Task 2 (Round 72, Beta): return persistence score averaged across windows.
                "persistence_score": avg_persistence_score,
                # Task 3 (Round 72, Gamma): cross-window momentum rank win-spread trend.
                "momentum_rank_trend_slope": _cwmrt.get("momentum_rank_trend_slope"),
                "momentum_rank_trend_mean": _cwmrt.get("momentum_rank_trend_mean"),
                "momentum_rank_positive_windows_pct": _cwmrt.get("momentum_rank_positive_windows_pct"),
                "momentum_rank_trend_grade": _cwmrt.get("momentum_rank_trend_grade"),
                "momentum_rank_trend_valid": _cwmrt.get("momentum_rank_trend_valid"),
                # Task 1 (Round 73, Alpha): market breadth win rate averaged across windows.
                "breadth_win_rate": avg_breadth_win_rate,
                # Task 2 (Round 73, Beta): factor IC consistency ratio averaged across windows.
                "ic_consistency_ratio": avg_ic_consistency_ratio,
                # Task 3 (Round 73, Gamma): cross-window Z-score win-spread trend.
                "zscore_trend_slope": _cwzt.get("zscore_trend_slope"),
                "zscore_trend_mean": _cwzt.get("zscore_trend_mean"),
                "zscore_positive_windows_pct": _cwzt.get("zscore_positive_windows_pct"),
                "zscore_trend_grade": _cwzt.get("zscore_trend_grade"),
                "zscore_trend_valid": _cwzt.get("zscore_trend_valid"),
                # Task 1 (Round 74, Alpha): signal strength stratification spread averaged across windows.
                "stratification_spread": avg_stratification_spread,
                # Task 2 (Round 74, Beta): conditional momentum edge averaged across windows.
                "conditional_momentum_edge": avg_conditional_momentum_edge,
                # Task 3 (Round 74, Gamma): cross-window market breadth win-rate trend.
                "breadth_trend_slope": _cwbt.get("breadth_trend_slope"),
                "breadth_trend_mean": _cwbt.get("breadth_trend_mean"),
                "breadth_above_threshold_pct": _cwbt.get("breadth_above_threshold_pct"),
                "breadth_trend_grade": _cwbt.get("breadth_trend_grade"),
                "breadth_trend_valid": _cwbt.get("breadth_trend_valid"),
                # Task 1 (Round 75, Alpha): simplified Sharpe ratio averaged across windows.
                "max_collinearity": avg_max_collinearity,
                # Task 3 (Round 75, Gamma): cross-window stratification spread trend.
                "stratification_trend_slope": _cwsst.get("stratification_trend_slope"),
                "stratification_trend_mean": _cwsst.get("stratification_trend_mean"),
                "stratification_positive_windows_pct": _cwsst.get("stratification_positive_windows_pct"),
                "stratification_trend_grade": _cwsst.get("stratification_trend_grade"),
                "stratification_trend_valid": _cwsst.get("stratification_trend_valid"),
                # Task 1 (Round 76, Alpha): gain/loss ratio averaged across windows.
                "gain_loss_ratio": avg_gain_loss_ratio,
                # Task 1 (Round 76, Alpha): tail asymmetry score averaged across windows.
                "tail_asymmetry_score": avg_tail_asymmetry_score,
                # Task 2 (Round 76, Beta): factor orthogonality score averaged across windows.
                "orthogonality_score": avg_orthogonality_score,
                # Task 1 (Round 77, Alpha): adaptive threshold lift averaged across windows.
                "threshold_lift": avg_threshold_lift,
                # Task 2 (Round 77, Beta): sector win-rate dispersion averaged across windows.
                "sector_win_rate_dispersion": avg_sector_win_rate_dispersion,
                # Task 3 (Round 77, Gamma): cross-window skew quality trend.
                "skew_trend_slope": _skew_trend.get("skew_trend_slope"),
                "skew_trend_mean": _skew_trend.get("skew_trend_mean"),
                "skew_favorable_windows_pct": _skew_trend.get("skew_favorable_windows_pct"),
                "skew_trend_grade": _skew_trend.get("skew_trend_grade"),
                "skew_trend_valid": _skew_trend.get("skew_trend_valid"),
                # Task 3 (Round 78, Gamma): cross-window adaptive threshold lift trend.
                "threshold_lift_trend_slope": _tlt.get("threshold_lift_trend_slope"),
                "threshold_lift_trend_mean": _tlt.get("threshold_lift_trend_mean"),
                "threshold_lift_positive_windows_pct": _tlt.get("threshold_lift_positive_windows_pct"),
                "threshold_lift_trend_grade": _tlt.get("threshold_lift_trend_grade"),
                "threshold_lift_trend_valid": _tlt.get("threshold_lift_trend_valid"),
                # Task 1 (Round 78, Alpha): hotstock win-rate edge averaged across windows.
                "hotstock_edge": avg_hotstock_edge,
                # Task 2 (Round 78, Beta): factor robustness ratio averaged across windows.
                "robustness_ratio": avg_robustness_ratio,
                # Task 1 (Round 79, Alpha): score quintile monotonicity score averaged across windows.
                "sq_consist_quintile_monotonicity_score": avg_sq_quintile_monotonicity_score,
                # Task 1 (Round 79, Alpha): score quintile top-bottom spread averaged across windows.
                "sq_consist_quintile_top_bottom_spread": avg_sq_quintile_top_bottom_spread,
                # Task 2 (Round 79, Beta): high-quality entry win rate averaged across windows.
                "entry_qual_high_quality_entry_win_rate": avg_entry_qual_high_quality_entry_win_rate,
                # Task 2 (Round 79, Beta): quality entry edge averaged across windows.
                "entry_qual_quality_entry_edge": avg_entry_qual_quality_entry_edge,
                # Task 3 (Round 79, Gamma): cross-window factor robustness OLS trend slope.
                "robustness_trend_slope": _rbt.get("robustness_trend_slope"),
                "robustness_trend_grade": _rbt.get("robustness_trend_grade"),
                "robustness_trend_window_count": _rbt.get("robustness_window_count"),
                # Task 3 (Round 80, Gamma): cross-window entry quality OLS trend slope.
                "entry_quality_trend_slope": _eqt.get("entry_quality_trend_slope"),
                "entry_quality_trend_grade": _eqt.get("entry_quality_trend_grade"),
                "entry_quality_trend_window_count": _eqt.get("entry_quality_window_count"),
                # Task 3 (Round 81, Gamma): cross-window near-high stock premium OLS trend slope.
                "near_high_trend_slope": _nht.get("near_high_trend_slope"),
                "near_high_trend_grade": _nht.get("near_high_trend_grade"),
                "near_high_trend_window_count": _nht.get("near_high_trend_window_count"),
                # Task 3 (Round 82, Gamma): cross-window EV spread OLS trend slope.
                "ev_spread_trend_slope": _evst.get("ev_spread_trend_slope"),
                "ev_spread_trend_grade": _evst.get("ev_spread_trend_grade"),
                "ev_spread_trend_window_count": _evst.get("ev_spread_window_count"),
                # Task 3 (Round 83, Gamma): cross-window precision trend OLS slope.
                "precision_trend_slope": _pct83.get("precision_trend_slope"),
                "precision_trend_grade": _pct83.get("precision_trend_grade"),
                "precision_trend_window_count": _pct83.get("precision_trend_window_count"),
                # Task 3 (Round 84, Gamma): cross-window upside asymmetry OLS trend slope.
                "upside_asymmetry_trend_slope": _uat84.get("upside_asymmetry_trend_slope"),
                "upside_asymmetry_trend_grade": _uat84.get("upside_asymmetry_trend_grade"),
                "upside_asymmetry_trend_window_count": _uat84.get("upside_asymmetry_window_count"),
                # Task 3 (Round 85, Gamma): cross-window momentum reversal OLS trend slope.
                "momentum_reversal_trend_slope": _mrt85.get("momentum_reversal_trend_slope"),
                "momentum_reversal_trend_grade": _mrt85.get("momentum_reversal_trend_grade"),
                "momentum_reversal_trend_window_count": _mrt85.get("momentum_reversal_window_count"),
                # Task 3 (Round 86, Gamma): cross-window batch consistency OLS trend slope.
                "batch_consistency_trend_slope": _bct86.get("batch_consistency_trend_slope"),
                "batch_consistency_trend_grade": _bct86.get("batch_consistency_trend_grade"),
                "batch_consistency_trend_window_count": _bct86.get("batch_consistency_trend_window_count"),
                # Task 3 (Round 87, Gamma): cross-window regime spread OLS trend slope.
                "regime_spread_trend_slope": _rsp87.get("regime_spread_trend_slope"),
                "regime_spread_trend_grade": _rsp87.get("regime_spread_trend_grade"),
                "regime_spread_trend_window_count": _rsp87.get("regime_spread_trend_window_count"),
                # Task 3 (Round 88, Gamma): cross-window signal quality OLS trend slope.
                "signal_quality_trend_slope": _sqt88.get("signal_quality_trend_slope"),
                "signal_quality_trend_grade": _sqt88.get("signal_quality_trend_grade"),
                "signal_quality_trend_n": _sqt88.get("signal_quality_trend_n"),
                # Task 1 (Round 89, Alpha): cross-window open-gap persistence OLS trend.
                "ogp_trend_slope": _ogp89.get("ogp_trend_slope"),
                "ogp_trend_grade": _ogp89.get("ogp_trend_grade"),
                "ogp_trend_n": _ogp89.get("ogp_trend_n"),
                # Task 2 (Round 89, Beta): cross-window tail flow quality OLS trend.
                "tf_trend_slope": _tf89.get("tf_trend_slope"),
                "tf_trend_grade": _tf89.get("tf_trend_grade"),
                "tf_trend_n": _tf89.get("tf_trend_n"),
                # Task 3 (Round 89, Gamma): cross-window momentum IC direction consistency.
                "mc_ic_consistency_score": _mc89.get("mc_ic_consistency_score"),
                "mc_ic_positive_window_count": _mc89.get("mc_ic_positive_window_count"),
                "mc_ic_total_window_count": _mc89.get("mc_ic_total_window_count"),
                "mc_ic_gate_passed": _mc89.get("mc_ic_gate_passed"),
                "mc_ic_mean": _mc89.get("mc_ic_mean"),
        }

    return evaluator


# Minimum fraction of exact_tick sources required to pass the source-coverage guardrail.
_IGNITION_SOURCE_COVERAGE_MIN_RATIO = 0.5


def _build_staged_ignition_evaluator(
    input_paths: list[Path],
    *,
    base_profile: str,
    next_high_hit_threshold: float = 0.02,
) -> Callable:
    """Build a staged evaluator that injects baseline-awareness and guardrail metrics.

    Pre-computes ignition_breakout (no overrides) and default profile baselines once,
    then wraps each candidate evaluation to inject:
    - baseline_next_close_positive_rate_delta
    - baseline_next_close_expectancy_delta
    - promotion_guardrail_pass
    - source_coverage_pass_ratio

    Args:
        input_paths: Replay window input paths.
        base_profile: Must be "ignition_breakout" for stage1.
        next_high_hit_threshold: Threshold for next-high hit rate computation.

    Returns:
        Callable evaluator that returns metrics with baseline-aware fields injected.
    """
    assert base_profile == "ignition_breakout", (
        f"_build_staged_ignition_evaluator requires 'ignition_breakout', got '{base_profile}'"
    )

    _ignition_evaluator = _build_replay_evaluator(
        input_paths, base_profile="ignition_breakout", next_high_hit_threshold=next_high_hit_threshold
    )
    _default_evaluator = _build_replay_evaluator(
        input_paths, base_profile="default", next_high_hit_threshold=next_high_hit_threshold
    )

    logger.info("Staged ignition evaluator: pre-computing ignition_breakout baseline…")
    ignition_baseline = _ignition_evaluator({})
    logger.info("Staged ignition evaluator: pre-computing default baseline…")
    default_baseline = _default_evaluator({})

    ignition_win_rate = ignition_baseline.get("next_close_positive_rate")
    ignition_expectancy = ignition_baseline.get("next_close_expectancy")
    default_win_rate = default_baseline.get("next_close_positive_rate")

    if ignition_win_rate is None:
        raise RuntimeError(
            "Staged ignition evaluator: ignition_breakout baseline missing 'next_close_positive_rate'. "
            "Cannot run stage1 promotion guardrail without a valid baseline."
        )
    if ignition_expectancy is None:
        raise RuntimeError(
            "Staged ignition evaluator: ignition_breakout baseline missing 'next_close_expectancy'. "
            "Cannot run stage1 promotion guardrail without a valid baseline."
        )
    if default_win_rate is None:
        raise RuntimeError(
            "Staged ignition evaluator: default profile baseline missing 'next_close_positive_rate'. "
            "Cannot run stage1 promotion guardrail without a valid baseline."
        )

    logger.info(
        "Baselines — ignition_breakout: win_rate=%.4f expectancy=%.4f | default: win_rate=%.4f",
        ignition_win_rate,
        ignition_expectancy,
        default_win_rate,
    )

    _candidate_evaluator = _build_replay_evaluator(
        input_paths, base_profile=base_profile, next_high_hit_threshold=next_high_hit_threshold
    )

    def staged_evaluator(params: dict[str, Any]) -> dict[str, float | None]:
        metrics: dict[str, Any] = dict(_candidate_evaluator(params))

        cand_win_rate = metrics.get("next_close_positive_rate")
        cand_expectancy = metrics.get("next_close_expectancy")

        metrics["baseline_next_close_positive_rate_delta"] = (
            (float(cand_win_rate) - float(ignition_win_rate)) if cand_win_rate is not None else None
        )
        metrics["baseline_next_close_expectancy_delta"] = (
            (float(cand_expectancy) - float(ignition_expectancy)) if cand_expectancy is not None else None
        )

        source_coverage_pass_ratio = float(metrics.get("source_coverage_pass_ratio") or 0.0)
        if cand_win_rate is None or cand_expectancy is None:
            promotion_guardrail_pass = False
        else:
            promotion_guardrail_pass = (
                float(cand_win_rate) >= float(ignition_win_rate)
                and float(cand_expectancy) >= float(ignition_expectancy)
                and float(cand_win_rate) >= float(default_win_rate)
                and source_coverage_pass_ratio >= _IGNITION_SOURCE_COVERAGE_MIN_RATIO
            )
        metrics["promotion_guardrail_pass"] = promotion_guardrail_pass

        return metrics

    return staged_evaluator


def _build_staged_ignition_shortlist(report: SearchReport, *, top_n: int = 5) -> list[dict[str, Any]]:
    """Extract top-N candidates from a stage1 search report and annotate each with a promotion verdict.

    Rows with a valid score are ranked first (descending); guardrail-failed rows (score=None) follow.
    Each row's verdict is derived from the ``promotion_guardrail_pass`` flag injected by the staged
    evaluator.  Row-level context (baseline deltas, source coverage) is surfaced so callers can
    understand *why* a row is or is not promotable.

    Args:
        report: Completed ``SearchReport`` from a stage1 ignition search.
        top_n: Maximum number of shortlist rows to return.

    Returns:
        List of dicts, each containing ``params``, ``score``, ``promotion_verdict``,
        ``baseline_next_close_positive_rate_delta``, ``baseline_next_close_expectancy_delta``,
        and ``source_coverage_pass_ratio``.
    """
    scored = sorted(
        (r for r in report.results if r.score is not None),
        key=lambda r: r.score or 0.0,
        reverse=True,
    )
    unscored = [r for r in report.results if r.score is None]
    candidates = (scored + unscored)[:top_n]

    shortlist: list[dict[str, Any]] = []
    for row in candidates:
        metrics: dict[str, Any] = row.metrics or {}
        guardrail_pass = bool(metrics.get("promotion_guardrail_pass", False))
        shortlist.append(
            {
                "params": row.params,
                "score": row.score,
                "promotion_verdict": "promotable" if guardrail_pass else "not_promotable",
                "baseline_next_close_positive_rate_delta": metrics.get("baseline_next_close_positive_rate_delta"),
                "baseline_next_close_expectancy_delta": metrics.get("baseline_next_close_expectancy_delta"),
                "source_coverage_pass_ratio": metrics.get("source_coverage_pass_ratio"),
            }
        )
    return shortlist


def _format_staged_ignition_summary(report: SearchReport) -> str:
    """Format a human-readable stage1 calibration summary with shortlist and overall verdict.

    Args:
        report: Completed ``SearchReport`` from a stage1 ignition search.

    Returns:
        Markdown-formatted summary string.
    """
    shortlist = _build_staged_ignition_shortlist(report)
    lines: list[str] = ["## Stage 1 Ignition Calibration Summary", ""]

    # Overall verdict is derived from the *full* report.results, not just the displayed shortlist,
    # so that a promotable candidate outside the top-N cap doesn't get silently hidden.
    any_promotable_in_full_report = any(
        bool((r.metrics or {}).get("promotion_guardrail_pass", False)) for r in report.results
    )
    if any_promotable_in_full_report:
        lines.append("**Overall verdict: PROMOTION AVAILABLE** — at least one candidate clears all guardrails.")
    else:
        lines.append("**Overall verdict: KEEP CURRENT IGNITION PROFILE** — no promotable candidates found.")
    lines.append("")

    if not shortlist:
        lines.append("*(no candidates evaluated)*")
        return "\n".join(lines)

    lines.append("### Top Candidates")
    lines.append("")
    for rank, row in enumerate(shortlist, 1):
        score_str = f"{row['score']:.4f}" if row["score"] is not None else "n/a"
        verdict = row.get("promotion_verdict", "n/a")
        marker = "✓" if verdict == "promotable" else "✗"
        lines.append(f"**#{rank}** {marker} score={score_str} | verdict={verdict}")

        delta_wr = row.get("baseline_next_close_positive_rate_delta")
        delta_ex = row.get("baseline_next_close_expectancy_delta")
        cov = row.get("source_coverage_pass_ratio")
        if delta_wr is not None:
            lines.append(f"  - win_rate_delta_vs_baseline: {delta_wr:+.4f}")
        if delta_ex is not None:
            lines.append(f"  - expectancy_delta_vs_baseline: {delta_ex:+.4f}")
        if cov is not None:
            lines.append(f"  - source_coverage_pass_ratio: {cov:.4f}")

        params = row.get("params") or {}
        for k, v in sorted(params.items()):
            lines.append(f"  - {k}={v}")
        lines.append("")

    return "\n".join(lines)


def _build_walk_forward_evaluator(
    *,
    tickers: list[str],
    start_date: str,
    end_date: str,
    initial_capital: float,
    model_name: str,
    model_provider: str,
    selected_analysts: list[str] | None,
    train_months: int = 2,
    test_months: int = 2,
    step_months: int = 1,
    base_profile: str,
) -> Callable:
    from src.backtesting.engine import BacktestEngine
    from src.backtesting.walk_forward import (
        build_walk_forward_windows,
        run_walk_forward,
        summarize_walk_forward,
        WindowMode,
    )
    from src.main import run_hedge_fund
    from src.targets.profiles import use_short_trade_target_profile

    def evaluator(params: dict[str, Any]) -> dict[str, float | None]:
        windows = build_walk_forward_windows(
            start_date,
            end_date,
            train_months=train_months,
            test_months=test_months,
            step_months=step_months,
            window_mode=WindowMode.ROLLING,
        )
        with use_short_trade_target_profile(profile_name=base_profile, overrides=params):
            results = run_walk_forward(
                windows,
                lambda w: BacktestEngine(
                    agent=run_hedge_fund,
                    tickers=tickers,
                    start_date=w.test_start,
                    end_date=w.test_end,
                    initial_capital=initial_capital,
                    model_name=model_name,
                    model_provider=model_provider,
                    selected_analysts=selected_analysts,
                    initial_margin_requirement=0.0,
                    backtest_mode="pipeline",
                ),
            )
        summary = summarize_walk_forward(results)
        return {
            "sharpe_ratio": summary.get("avg_sharpe"),
            "sortino_ratio": summary.get("avg_sortino"),
            "max_drawdown": summary.get("avg_max_drawdown"),
            "window_count": summary.get("window_count", 0),
        }

    return evaluator


MOMENTUM_OPTIMIZED_GRID: dict[str, list[Any]] = {
    "select_threshold": [0.46, 0.50, 0.54],
    "near_miss_threshold": [0.30, 0.34, 0.38],
    "breakout_freshness_weight": [0.12, 0.16],
    "trend_acceleration_weight": [0.18, 0.22],
    "volume_expansion_quality_weight": [0.16, 0.20],
    "close_strength_weight": [0.12, 0.16],
    "catalyst_freshness_weight": [0.10, 0.14],
    "momentum_strength_weight": [0.00, 0.06],
    "short_term_reversal_weight": [0.00, 0.04],
    "stale_penalty_block_threshold": [0.78, 0.82],
    "overhead_penalty_block_threshold": [0.74, 0.78],
    "extension_penalty_block_threshold": [0.80, 0.84],
    # Task 4 (Round 10): recency half-life grid — optimizer selects the best decay speed.
    "recency_half_life_days": list(RECENCY_HALF_LIFE_CANDIDATES),
}

EVENT_CATALYST_GRID: dict[str, list[Any]] = {
    "event_catalyst_selected_uplift": [0.02, 0.03],
    "event_catalyst_near_miss_threshold_relief": [0.01, 0.02],
    "event_catalyst_min_score_for_selected_uplift": [0.68, 0.72],
    "event_catalyst_min_score_for_near_miss_retain": [0.54, 0.58],
    "event_catalyst_sector_resonance_weight": [0.18, 0.22],
}

ROUTED_BTST_COMMITTEE_GRID: dict[str, list[Any]] = {
    "committee_alpha_min_aggressive_trade": [66.0, 68.0, 70.0],
    "committee_beta_min_aggressive_trade": [56.0, 58.0, 60.0],
    "committee_gamma_min_aggressive_trade": [54.0, 56.0, 58.0],
    "committee_score_min_aggressive_trade": [64.0, 66.0, 68.0],
    "committee_alpha_min_normal_trade": [64.0, 66.0, 68.0],
    "committee_beta_min_normal_trade": [60.0, 62.0, 64.0],
    "committee_gamma_min_normal_trade": [56.0, 58.0, 60.0],
    "committee_score_min_normal_trade": [62.0, 64.0, 66.0],
    "committee_fragile_breakout_alpha_weight": [0.08, 0.10, 0.12],
    "committee_fragile_breakout_activation_floor": [56.0, 60.0, 64.0],
    "committee_fragile_breakout_fragility_floor": [52.0, 55.0, 58.0],
    "committee_fragile_breakout_risk_cap": [75.0, 85.0],
}

ROUTED_BTST_COMMITTEE_PROFILES = {
    "ignition_breakout",
    "retention_follow",
    "shadow_research",
}

# Runner escape threshold and composite weight calibration grid for btst_runner_probe.
# Run with --preset-grid --profile btst_runner_probe --objective btst_runner to search over
# escape gate tightness and composite score weight emphasis simultaneously.
BTST_RUNNER_PROBE_GRID: dict[str, list[Any]] = {
    "runner_escape_breakout_freshness_min": [0.25, 0.30, 0.35, 0.40],
    "runner_escape_trend_acceleration_min": [0.45, 0.50, 0.55, 0.60],
    "runner_escape_volume_expansion_quality_min": [0.30, 0.35, 0.40],
    "runner_composite_score_breakout_weight": [0.35, 0.40, 0.45],
    "runner_composite_score_trend_weight": [0.25, 0.30, 0.35],
    "runner_composite_score_volume_weight": [0.15, 0.20, 0.25],
    "runner_composite_score_catalyst_weight": [0.05, 0.10, 0.15],
    "runner_composite_score_close_strength_weight": [0.05, 0.10, 0.15],
    "historical_continuation_score_weight": [0.0, 0.05, 0.10],
    "runner_composite_score_volatility_regime_weight": [0.0, 0.05, 0.10],
    "runner_composite_score_sector_resonance_weight": [0.0, 0.05, 0.10],
    # Task 5 (Round 10): quiet breakout cross-factor weight.
    "runner_composite_score_quiet_breakout_weight": [0.0, 0.05, 0.10, 0.15],
    # Task 1 (Round 18): R16/R17 new-factor weights — net inflow, volume-price divergence quality, t0 tail strength.
    "runner_composite_score_net_inflow_weight": [0.0, 0.05, 0.10, 0.15],
    "runner_composite_score_volume_price_divergence_weight": [0.0, 0.05, 0.10, 0.15],
    "runner_composite_score_t0_tail_weight": [0.0, 0.05, 0.10, 0.15],
    # Task 2 (Round 19): multi-period momentum alignment weight — T+1/T+2/T+3 continuation score.
    "runner_composite_score_momentum_alignment_weight": [0.0, 0.05, 0.10, 0.15],
    # Task 1 (Round 26, Alpha): cross-factor F11/F12 weights — momentum confirmation and volume momentum.
    "runner_composite_score_momentum_confirmation_weight": [0.0, 0.05, 0.10],
    "runner_composite_score_volume_momentum_weight": [0.0, 0.05, 0.10],
    "runner_escape_gap_risk_raw_100_max": [40.0, 45.0, 52.0],
    "runner_escape_projected_theme_exposure_max": [0.24, 0.28, 0.32],
    "runner_escape_candidate_pool_avg_amount_share_of_cutoff_min": [0.85, 1.0, 1.15],
    "runner_escape_composite_score_min": [0.0, 0.40, 0.45, 0.50],
    # Task 4 (Round 10): recency half-life grid.
    "recency_half_life_days": list(RECENCY_HALF_LIFE_CANDIDATES),
    # Task 3 (Round 31, Beta): F13 relative sector strength rank weight.
    "runner_composite_score_rs_sector_rank_weight": [0.0, 0.05, 0.10, 0.15, 0.20],
}

# ---------------------------------------------------------------------------
# Task 1 (Round 23, Gamma): Lean PROBE_GRID — reduced axis set for fast search and lower overfitting risk.
# ---------------------------------------------------------------------------
# BTST_RUNNER_LEAN_PROBE_GRID retains the ~11 highest-importance axes from the full grid,
# selected on the basis of: (a) theoretical factor centrality, (b) R21 IC/IR stability,
# and (c) surface-metric correlation results (R22 advisory output).  All other axes are
# left out of the grid so the optimizer uses the profile's static default values.
# Lean mode halves the search space compared to the full 21-axis grid, reducing both
# compute cost and the risk of spurious in-sample overfitting on short replay windows.
#
# Selection rationale per axis:
#   runner_composite_score_breakout_weight   — highest-IC factor; theoretically dominant
#   runner_escape_breakout_freshness_min     — direct escape gate tied to the same factor
#   runner_composite_score_catalyst_weight   — event-driven premium; R21 positive IC
#   runner_composite_score_close_strength_weight — late-session bid persistence signal
#   runner_composite_score_t0_tail_weight    — R17 factor; close/high proxy for overnight hold
#   runner_composite_score_net_inflow_weight — R16 buying-pressure factor with positive IC
#   runner_composite_score_trend_weight      — trend acceleration; traditionally important
#   runner_composite_score_volatility_regime_weight — regime-adaptive risk weight
#   recency_half_life_days                   — temporal decay hyper-parameter; drives weighting
#   runner_escape_composite_score_min        — quality gate; controls precision vs recall
#   runner_escape_gap_risk_raw_100_max       — overnight gap-risk guard; prevents blow-ups
BTST_RUNNER_LEAN_PROBE_GRID: dict[str, list[Any]] = {
    # Core factor weight — highest IC; theoretically dominant in composite score.
    "runner_composite_score_breakout_weight": [0.35, 0.40, 0.45],
    # Escape-gate threshold tied to the core breakout factor.
    "runner_escape_breakout_freshness_min": [0.25, 0.30, 0.35, 0.40],
    # Event-driven momentum premium (催化剂新鲜度).
    "runner_composite_score_catalyst_weight": [0.05, 0.10, 0.15],
    # Late-session bid strength (收盘强度): close-relative-to-high proxy for overnight continuation.
    "runner_composite_score_close_strength_weight": [0.05, 0.10, 0.15],
    # T0 tail-session strength (R17): close/high ratio — late buying pressure.
    "runner_composite_score_t0_tail_weight": [0.0, 0.05, 0.10, 0.15],
    # T0 net inflow ratio (R16): buying-pressure signal with positive IC.
    "runner_composite_score_net_inflow_weight": [0.0, 0.05, 0.10, 0.15],
    # Trend acceleration — traditionally high-importance across backtesting rounds.
    "runner_composite_score_trend_weight": [0.25, 0.30, 0.35],
    # Volatility regime weight — adjusts composite score for high-vol environments.
    "runner_composite_score_volatility_regime_weight": [0.0, 0.05, 0.10],
    # Temporal decay hyper-parameter — how fast older windows lose influence.
    "recency_half_life_days": list(RECENCY_HALF_LIFE_CANDIDATES),
    # Minimum composite score gate for runner escape (quality floor).
    "runner_escape_composite_score_min": [0.0, 0.40, 0.45, 0.50],
    # Overnight gap-risk cap: prevents selecting runners with excessive T+1 gap exposure.
    "runner_escape_gap_risk_raw_100_max": [40.0, 45.0, 52.0],
}

# Axis counts — used in tests and logging to verify grid dimensions without re-counting.
FULL_GRID_AXIS_COUNT: int = len(BTST_RUNNER_PROBE_GRID)
LEAN_GRID_AXIS_COUNT: int = len(BTST_RUNNER_LEAN_PROBE_GRID)

# ---------------------------------------------------------------------------
# Task 3 (Round 13) — IC weight feedback loop: factor → probe grid weight key mapping
# ---------------------------------------------------------------------------
# Maps each BTST factor name (as returned by compute_ic_weight_suggestions) to its
# corresponding composite score weight key in BTST_RUNNER_PROBE_GRID.  Used by
# apply_ic_feedback_to_probe_grid to automatically tighten or relax the grid search
# bounds based on IC feedback from previous evaluation rounds.
BTST_FACTOR_TO_PROBE_WEIGHT_KEY: dict[str, str] = {
    "breakout_freshness": "runner_composite_score_breakout_weight",
    "trend_acceleration": "runner_composite_score_trend_weight",
    "volume_expansion_quality": "runner_composite_score_volume_weight",
    "catalyst_freshness": "runner_composite_score_catalyst_weight",
    "close_strength": "runner_composite_score_close_strength_weight",
    "volatility_regime": "runner_composite_score_volatility_regime_weight",
    "sector_resonance": "runner_composite_score_sector_resonance_weight",
    # Task 1 (Round 18): R16/R17 new factors now have grid weight axes.
    "t0_estimated_net_inflow_ratio": "runner_composite_score_net_inflow_weight",
    "volume_price_divergence_score": "runner_composite_score_volume_price_divergence_weight",
    "t0_tail_strength": "runner_composite_score_t0_tail_weight",
    # Task 1 (Round 26, Alpha): cross-factor F11/F12 mappings.
    "momentum_confirmation_score": "runner_composite_score_momentum_confirmation_weight",
    "volume_momentum_score": "runner_composite_score_volume_momentum_weight",
    # Task 3 (Round 31, Beta): F13 relative sector strength rank mapping.
    "rs_sector_rank": "runner_composite_score_rs_sector_rank_weight",
}

# Standard step size for weight candidates in BTST_RUNNER_PROBE_GRID.
# Used when computing expanded upper bounds for "increase" suggestions.
IC_WEIGHT_GRID_STEP: float = 0.05
# Hard upper bound for any single factor's composite score weight to prevent a single
# factor from dominating the composite score after repeated "increase" suggestions.
IC_WEIGHT_GRID_MAX_UPPER_BOUND: float = 0.55


# ---------------------------------------------------------------------------
# Task 1 (Round 22, Gamma): Low-impact PROBE_GRID axis identification
# ---------------------------------------------------------------------------
# Bridges surface_metric_correlations and factor IC stability (both from R21)
# to identify which PROBE_GRID weight axes correspond to weak/noisy factors.
# Output is advisory only — no automatic axis removal.


def compute_low_impact_probe_axes(
    surface_metric_correlations: dict[str, float],
    ic_stability: dict[str, float],
    ic_corr_threshold: float = 0.05,
    ir_threshold: float = 0.20,
) -> dict[str, Any]:
    """Identify low-contribution PROBE_GRID weight axes based on surface correlation and IC stability.

    For each factor in :data:`BTST_FACTOR_TO_PROBE_WEIGHT_KEY` the function checks two signals:

    1. **Surface metric correlation** (``|corr| < ic_corr_threshold``): whether the factor's
       proxy metric (looked up from *surface_metric_correlations* using the factor name or
       ``avg_factor_ic_{factor}``) has near-zero correlation with the window win-rate.
    2. **IC Information Ratio** (``IR < ir_threshold``): whether the factor shows low
       cross-window IC stability in *ic_stability* (``{factor}_ic_ir`` key).

    A probe axis is a **pruning candidate** only when *both* conditions hold.  The output
    is purely advisory — no axes are removed automatically.

    Args:
        surface_metric_correlations: Spearman-correlation dict from
            :func:`~scripts.btst_analysis_utils.compute_surface_metric_correlations`.
            Maps metric name → float correlation with ``next_close_positive_rate``.
        ic_stability: Factor IC stability dict from
            :func:`~scripts.btst_analysis_utils.compute_factor_ic_stability`.
            Expected to contain ``{factor}_ic_ir`` keys for each BTST factor.
        ic_corr_threshold: |correlation| below this value flags the factor as low-corr.
            Defaults to 0.05.
        ir_threshold: IC Information Ratio below this value flags the factor as low-IR.
            Defaults to 0.20.

    Returns:
        Dict containing:

        - ``low_impact_axes`` (list[str])    — probe-grid keys where ``|corr| < threshold``.
        - ``low_ir_factors``  (list[str])    — factor names where ``IR < ir_threshold``.
        - ``pruning_candidates`` (list[str]) — probe-grid keys satisfying *both* criteria.
        - ``pruning_summary`` (str)          — human-readable advisory summary.
    """
    low_impact_axes: list[str] = []
    low_ir_factors: list[str] = []
    pruning_candidates: list[str] = []

    for factor, probe_key in BTST_FACTOR_TO_PROBE_WEIGHT_KEY.items():
        # Resolve surface metric correlation: try the factor name directly, then the avg_factor_ic_ prefix.
        corr: float | None = None
        for candidate_key in (factor, f"avg_factor_ic_{factor}"):
            cval = surface_metric_correlations.get(candidate_key)
            if isinstance(cval, (int, float)) and not isinstance(cval, bool):
                corr = float(cval)
                break

        # Resolve IC Information Ratio from ic_stability dict.
        ir: float | None = None
        ir_raw = ic_stability.get(f"{factor}_ic_ir")
        if isinstance(ir_raw, (int, float)) and not isinstance(ir_raw, bool):
            ir = float(ir_raw)

        is_low_corr: bool = (corr is not None) and (abs(corr) < ic_corr_threshold)
        is_low_ir: bool = (ir is not None) and (ir < ir_threshold)

        if is_low_corr:
            low_impact_axes.append(probe_key)
        if is_low_ir:
            low_ir_factors.append(factor)
        if is_low_corr and is_low_ir:
            pruning_candidates.append(probe_key)

    n_cand: int = len(pruning_candidates)
    n_axes: int = len(low_impact_axes)
    n_ir: int = len(low_ir_factors)
    pruning_summary: str = (
        f"{n_cand} probe axis(es) are pruning candidates (low surface corr AND low IC IR): {pruning_candidates}. "
        f"{n_axes} axis(es) flagged by low surface correlation; {n_ir} factor(s) flagged by low IC IR."
    )

    return {
        "low_impact_axes": low_impact_axes,
        "low_ir_factors": low_ir_factors,
        "pruning_candidates": pruning_candidates,
        "pruning_summary": pruning_summary,
    }


# ---------------------------------------------------------------------------
# Round 25, Task 3 (Alpha): Auto-calibrated quality floor suggestions
# ---------------------------------------------------------------------------
# Analyses the distribution of each BTST_QUALITY_FLOORS metric across all
# replay windows and suggests whether each floor should be tightened or
# relaxed.  A floor that is trivially easy to pass (current value ≤ P25×0.80)
# should be raised; one that almost no parameter set can pass (current value
# > P75×1.20) should be lowered.  Output is advisory only — no constants are
# modified automatically.


def compute_auto_calibrated_floor_suggestions(all_window_metrics: list[dict[str, Any]], target_pass_rate: float = 0.50) -> dict[str, Any]:
    """基于历史窗口分布，建议更合理的质量门槛.

    遍历 BTST_QUALITY_FLOORS 的每个指标，计算其在所有窗口中的分布（P25/P50/P75）。
    - 当前门槛 ≤ P25 × 0.80 → "too_easy"（建议提高到P25）
    - 当前门槛 > P75 × 1.20 → "too_strict"（建议降低到P50）
    - 否则 → "calibrated"

    输出是 advisory（建议），不自动修改常量。

    Args:
        all_window_metrics: List of per-window surface summary dicts (each produced by
            ``build_surface_summary`` or the aggregated evaluator output).
        target_pass_rate: Target fraction of windows that should pass each floor (advisory
            context only; not used in the threshold computation logic).

    Returns:
        Dict with keys:
        - ``floor_suggestions``: mapping from metric key to sub-dict
          {current, suggested, p25, p50, p75, action}.
        - ``overly_easy_floors``: list of metric keys that are too easy to pass.
        - ``overly_strict_floors``: list of metric keys that are too strict.
        - ``well_calibrated_floors``: list of metric keys that are well-calibrated.
    """
    _null: dict[str, Any] = {"floor_suggestions": {}, "overly_easy_floors": [], "overly_strict_floors": [], "well_calibrated_floors": []}
    if not all_window_metrics:
        return _null

    floor_suggestions: dict[str, dict[str, Any]] = {}
    overly_easy: list[str] = []
    overly_strict: list[str] = []
    well_calibrated: list[str] = []

    for metric_key, current_floor in BTST_QUALITY_FLOORS.items():
        values: list[float] = []
        for w in all_window_metrics:
            v = w.get(metric_key)
            if v is None:
                continue
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                continue

        if not values:
            floor_suggestions[metric_key] = {"current": current_floor, "suggested": current_floor, "p25": None, "p50": None, "p75": None, "action": "no_data"}
            continue

        values_sorted = sorted(values)
        n = len(values_sorted)

        def _pct(p: float, _vs: list[float] = values_sorted, _n: int = n) -> float:
            idx = (_n - 1) * p
            lo = int(idx)
            hi = lo + 1 if lo < _n - 1 else lo
            return _vs[lo] + (idx - lo) * (_vs[hi] - _vs[lo])

        p25 = _pct(0.25)
        p50 = _pct(0.50)
        p75 = _pct(0.75)

        # Determine calibration action using asymmetric thresholds.
        # Note: for lower-is-better metrics (negative floors like drawdown) the direction
        # of "easy" / "strict" is inverted.  We detect this by checking if current_floor < 0.
        if current_floor < 0.0:
            # Negative-floor metrics (e.g. t_plus_1_intraday_drawdown_p10 = -0.07):
            # "too easy" means the floor is very permissive (very negative) compared to actual data.
            # P25 is the 25th-percentile of the DISTRIBUTION (most negative end).
            # current_floor ≤ p25 × 0.80 in the negative sense: |current| ≤ |p25| × 0.80.
            if current_floor <= p25 * 0.80:
                action = "too_easy"
                suggested = p25
                overly_easy.append(metric_key)
            elif current_floor > p75 * 1.20:
                action = "too_strict"
                suggested = p50
                overly_strict.append(metric_key)
            else:
                action = "calibrated"
                suggested = current_floor
                well_calibrated.append(metric_key)
        else:
            if current_floor <= p25 * 0.80:
                action = "too_easy"
                suggested = p25
                overly_easy.append(metric_key)
            elif current_floor > p75 * 1.20:
                action = "too_strict"
                suggested = p50
                overly_strict.append(metric_key)
            else:
                action = "calibrated"
                suggested = current_floor
                well_calibrated.append(metric_key)

        floor_suggestions[metric_key] = {
            "current": current_floor,
            "suggested": round(float(suggested), 6),
            "p25": round(p25, 6),
            "p50": round(p50, 6),
            "p75": round(p75, 6),
            "action": action,
        }

    return {
        "floor_suggestions": floor_suggestions,
        "overly_easy_floors": overly_easy,
        "overly_strict_floors": overly_strict,
        "well_calibrated_floors": well_calibrated,
    }


def apply_ic_feedback_to_probe_grid(
    ic_weight_suggestions: dict[str, str],
    base_grid: dict[str, list[Any]],
) -> dict[str, list[Any]]:
    """Return a copy of *base_grid* with weight candidates pruned / expanded based on IC feedback.

    This implements the IC weight feedback loop (Task 3, Round 13).  For each BTST factor that
    has an IC weight suggestion from :func:`~scripts.btst_analysis_utils.compute_ic_weight_suggestions`,
    the corresponding probe-grid candidate list in :data:`BTST_RUNNER_PROBE_GRID` is modified:

    - ``"reduce"``: the highest candidate value is dropped (upper bound tightened) to prevent
      the search from promoting high weights for a weakly predictive factor.
    - ``"increase"``: a candidate one step above the current maximum is added (bounded by
      :data:`IC_WEIGHT_GRID_MAX_UPPER_BOUND`) so strong predictors can reach higher weights.
    - ``"maintain"``: no change.

    At least one candidate is always retained even for repeated ``reduce`` suggestions —
    the pruning never empties a candidate list.

    Args:
        ic_weight_suggestions: Mapping of factor name → suggestion string (``"reduce"``,
            ``"increase"``, or ``"maintain"``).  Factors with no mapping are unmodified.
        base_grid: Base probe grid dict (typically :data:`BTST_RUNNER_PROBE_GRID`).

    Returns:
        New grid dict with modified candidate lists (same key set as *base_grid*).
    """
    result: dict[str, list[Any]] = {k: list(v) for k, v in base_grid.items()}
    for factor, suggestion in ic_weight_suggestions.items():
        grid_key = BTST_FACTOR_TO_PROBE_WEIGHT_KEY.get(factor)
        if grid_key is None or grid_key not in result:
            continue
        candidates: list[Any] = result[grid_key]
        if not candidates:
            continue
        sorted_candidates = sorted(float(c) for c in candidates)
        if suggestion == "reduce":
            # Drop the top candidate if more than one remains to avoid emptying the list.
            if len(sorted_candidates) > 1:
                sorted_candidates = sorted_candidates[:-1]
        elif suggestion == "increase":
            # Add one step above the current maximum, bounded by IC_WEIGHT_GRID_MAX_UPPER_BOUND.
            new_max = round(sorted_candidates[-1] + IC_WEIGHT_GRID_STEP, 4)
            if new_max <= IC_WEIGHT_GRID_MAX_UPPER_BOUND and new_max not in sorted_candidates:
                sorted_candidates = sorted_candidates + [new_max]
        result[grid_key] = sorted_candidates
    return result

IGNITION_STAGE1_GRID: dict[str, list[Any]] = {
    "committee_alpha_min_aggressive_trade": [66.0, 68.0],
    "committee_beta_min_aggressive_trade": [56.0, 58.0],
    "committee_gamma_min_aggressive_trade": [54.0, 56.0],
    "committee_score_min_aggressive_trade": [64.0, 66.0],
    "committee_alpha_min_normal_trade": [64.0, 66.0],
    "committee_beta_min_normal_trade": [60.0, 62.0],
    "committee_gamma_min_normal_trade": [56.0, 58.0],
    "committee_score_min_normal_trade": [62.0, 64.0],
    "committee_fragile_breakout_alpha_weight": [0.08, 0.10],
    "committee_fragile_breakout_activation_floor": [56.0, 60.0],
    "committee_fragile_breakout_fragility_floor": [52.0, 55.0],
    "committee_fragile_breakout_risk_cap": [75.0, 80.0],
}

def resolve_grid_params(
    *,
    grid_params: list[str],
    preset_grid: bool,
    profile_name: str,
    search_stage: str = "full",
    staged_mode: str | None = None,
    ic_weight_suggestions: dict[str, str] | None = None,
    lean_mode: bool = False,
) -> dict[str, list[Any]]:
    """Resolve grid parameters with optional preset and profile-specific extensions.

    Args:
        grid_params: Raw grid parameter strings to parse
        preset_grid: Whether to include base preset grid
        profile_name: Profile name for profile-specific grid extensions
        search_stage: Optional stage-aware preset variant
        staged_mode: Optional staged calibration mode (e.g. "ignition_stage1")
        ic_weight_suggestions: Optional IC-based weight suggestions dict (from
            :func:`~scripts.btst_analysis_utils.compute_ic_weight_suggestions`).
            When provided and the profile is ``btst_runner_probe``, the probe grid
            search bounds are automatically tightened / expanded via
            :func:`apply_ic_feedback_to_probe_grid` (Task 3, Round 13).
        lean_mode: When ``True`` and profile is ``btst_runner_probe``, use
            :data:`BTST_RUNNER_LEAN_PROBE_GRID` (≈11 high-importance axes) instead of
            the full 21-axis :data:`BTST_RUNNER_PROBE_GRID`.  Lean mode reduces search
            cost and overfitting risk at the expense of exploring fewer hyperparameter
            combinations.  Ignored for all other profiles.  (Task 1, Round 23, Gamma.)

    Returns:
        Merged grid dictionary with parsed params taking precedence
    """
    resolved = _parse_grid_params(grid_params)
    if staged_mode == "ignition_stage1":
        if profile_name != "ignition_breakout":
            raise ValueError(
                f"--staged-mode ignition_stage1 is only valid for profile 'ignition_breakout', got '{profile_name}'"
            )
        return {**IGNITION_STAGE1_GRID, **resolved}
    base_momentum_grid = MOMENTUM_OPTIMIZED_STAGE_PRESET_GRIDS.get(search_stage, MOMENTUM_OPTIMIZED_GRID)
    if preset_grid and profile_name == "event_catalyst_guarded":
        return {**base_momentum_grid, **EVENT_CATALYST_GRID, **resolved}
    if preset_grid and profile_name in ROUTED_BTST_COMMITTEE_PROFILES:
        return {**ROUTED_BTST_COMMITTEE_GRID, **resolved}
    if preset_grid and profile_name == "btst_runner_probe":
        # Task 1 (Round 23, Gamma): select lean vs full probe grid based on lean_mode flag.
        # Task 3 (Round 13): apply IC feedback to prune / expand weight candidates before search.
        base_probe_grid: dict[str, list[Any]] = BTST_RUNNER_LEAN_PROBE_GRID if lean_mode else BTST_RUNNER_PROBE_GRID
        base_runner_grid = apply_ic_feedback_to_probe_grid(ic_weight_suggestions, base_probe_grid) if ic_weight_suggestions else dict(base_probe_grid)
        return {**base_runner_grid, **resolved}
    if preset_grid:
        return {**base_momentum_grid, **resolved}
    return resolved


def _build_search_metadata(
    *,
    search_stage: str,
    guardrails: dict[str, GuardrailSpec],
    focus_json: str | None,
    checkpoint_path: str,
    stage_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "search_stage": search_stage,
        "guardrails": guardrails,
        "focus_source": focus_json,
        "checkpoint_path": checkpoint_path,
    }
    if stage_results is not None:
        payload["stage_results"] = stage_results
    return payload


def _build_comparison_entry(*, candidate_metrics: dict[str, Any], baseline_metrics: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "candidate": candidate_metrics,
        "baseline": baseline_metrics,
    }
    for metric in COMPARISON_METRICS:
        candidate_value = _safe_float(candidate_metrics.get(metric))
        baseline_value = _safe_float(baseline_metrics.get(metric))
        entry[f"{metric}_delta"] = None if candidate_value is None or baseline_value is None else candidate_value - baseline_value
    return entry


def _build_replay_comparison_summary(
    *,
    replay_input_paths: list[Path],
    base_profile: str,
    best_params: dict[str, Any],
    next_high_hit_threshold: float,
) -> dict[str, dict[str, Any]]:
    candidate_metrics = _build_replay_evaluator(
        replay_input_paths,
        base_profile=base_profile,
        next_high_hit_threshold=next_high_hit_threshold,
    )(best_params)
    baseline_names = [base_profile]
    if base_profile != "default":
        baseline_names.append("default")

    summary: dict[str, dict[str, Any]] = {}
    for baseline_name in baseline_names:
        baseline_metrics = _build_replay_evaluator(
            replay_input_paths,
            base_profile=baseline_name,
            next_high_hit_threshold=next_high_hit_threshold,
        )({})
        summary[baseline_name] = _build_comparison_entry(
            candidate_metrics=candidate_metrics,
            baseline_metrics=baseline_metrics,
        )
    return summary


# Task B (Round btst-winrate-design-20260517): win-rate-first acceptance gate
WIN_RATE_FIRST_MIN_POSITIVE_DELTA: float = 0.005  # 0.5% minimum positive win-rate signal beyond noise
WIN_RATE_FIRST_MAX_PAYOFF_DEGRADATION: float = 0.10  # 10% max payoff ratio degradation
WIN_RATE_FIRST_MAX_EXPECTANCY_DEGRADATION: float = 0.005  # 0.5% max expectancy degradation
WIN_RATE_FIRST_MAX_COVERAGE_DEGRADATION: float = 0.03  # 3% max coverage degradation


def _build_win_rate_first_decision(comparison_summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Evaluate win-rate-first acceptance using existing comparison metrics.

    Task B (Round btst-winrate-design-20260517): re-validate trend-corrected promotion under
    win-rate-first gates. Uses existing comparison metrics as acceptance surface:
    - Primary win-rate signals: next_close_positive_rate_delta, next_high_hit_rate_delta
    - Bounded tradeoff constraints: realized_payoff_ratio_delta (or next_close_expectancy_delta fallback), window_coverage_delta

    Args:
        comparison_summary: Dict mapping baseline names to comparison entries with {metric}_delta keys.

    Returns:
        Dict with keys:
        - verdict: "accepted" | "rejected"
        - win_rate_signals: Dict of primary win-rate deltas
        - bounded_tradeoffs: Dict of payoff/coverage deltas
        - rejection_reasons: List of rejection reason codes (empty if accepted)
    """
    if not comparison_summary:
        return {
            "verdict": "rejected",
            "win_rate_signals": {},
            "bounded_tradeoffs": {},
            "rejection_reasons": ["missing_comparison_summary"],
            "verdict_reason": "missing_comparison_summary",
        }

    # Aggregate win-rate signals and bounded tradeoffs across all baselines
    # For multi-baseline comparison, use the minimum (most conservative) win-rate delta
    # and maximum (worst) degradation delta
    all_close_positive_deltas: list[float] = []
    all_high_hit_deltas: list[float] = []
    all_payoff_ratio_deltas: list[float] = []
    all_expectancy_deltas: list[float] = []
    all_coverage_deltas: list[float] = []

    for baseline_name, entry in comparison_summary.items():
        close_positive_delta = _safe_float(entry.get("next_close_positive_rate_delta"))
        high_hit_delta = _safe_float(entry.get("next_high_hit_rate_delta"))
        payoff_ratio_delta = _safe_float(entry.get("realized_payoff_ratio_delta"))
        expectancy_delta = _safe_float(entry.get("next_close_expectancy_delta"))
        coverage_delta = _safe_float(entry.get("window_coverage_delta"))

        if close_positive_delta is not None:
            all_close_positive_deltas.append(close_positive_delta)
        if high_hit_delta is not None:
            all_high_hit_deltas.append(high_hit_delta)
        if payoff_ratio_delta is not None:
            all_payoff_ratio_deltas.append(payoff_ratio_delta)
        if expectancy_delta is not None:
            all_expectancy_deltas.append(expectancy_delta)
        if coverage_delta is not None:
            all_coverage_deltas.append(coverage_delta)

    min_close_positive_delta = min(all_close_positive_deltas) if all_close_positive_deltas else None
    min_high_hit_delta = min(all_high_hit_deltas) if all_high_hit_deltas else None
    min_payoff_ratio_delta = min(all_payoff_ratio_deltas) if all_payoff_ratio_deltas else None
    min_expectancy_delta = min(all_expectancy_deltas) if all_expectancy_deltas else None
    min_coverage_delta = min(all_coverage_deltas) if all_coverage_deltas else None

    rejection_reasons: list[str] = []

    # Check primary win-rate signals — both must be positive beyond noise
    if min_close_positive_delta is None or min_close_positive_delta < WIN_RATE_FIRST_MIN_POSITIVE_DELTA:
        rejection_reasons.append("win_rate_uplift_missing")
    if min_high_hit_delta is None or min_high_hit_delta < WIN_RATE_FIRST_MIN_POSITIVE_DELTA:
        rejection_reasons.append("win_rate_uplift_missing")

    # Check bounded tradeoff constraints
    # Use realized_payoff_ratio_delta if available, otherwise fall back to next_close_expectancy_delta
    if min_payoff_ratio_delta is not None and min_payoff_ratio_delta < -WIN_RATE_FIRST_MAX_PAYOFF_DEGRADATION:
        rejection_reasons.append("payoff_degradation_too_large")
    elif min_payoff_ratio_delta is None and min_expectancy_delta is not None and min_expectancy_delta < -WIN_RATE_FIRST_MAX_EXPECTANCY_DEGRADATION:
        rejection_reasons.append("payoff_degradation_too_large")
    if min_coverage_delta is not None and min_coverage_delta < -WIN_RATE_FIRST_MAX_COVERAGE_DEGRADATION:
        rejection_reasons.append("coverage_degradation_too_large")

    # Build win_rate_signals and bounded_tradeoffs dicts
    win_rate_signals: dict[str, float | None] = {
        "next_close_positive_rate_delta": min_close_positive_delta,
        "next_high_hit_rate_delta": min_high_hit_delta,
    }

    bounded_tradeoffs: dict[str, float | None] = {
        "window_coverage_delta": min_coverage_delta,
    }
    if min_payoff_ratio_delta is not None:
        bounded_tradeoffs["realized_payoff_ratio_delta"] = min_payoff_ratio_delta
    elif min_expectancy_delta is not None:
        bounded_tradeoffs["next_close_expectancy_delta"] = min_expectancy_delta

    # Remove rejection_reasons duplicates while preserving order
    rejection_reasons = list(dict.fromkeys(rejection_reasons))

    if not rejection_reasons:
        verdict_reason = "meets_win_rate_first_criteria"
    elif rejection_reasons == ["win_rate_uplift_missing"]:
        verdict_reason = "win_rate_uplift_missing"
    else:
        verdict_reason = "bounded_tradeoff_check_failed"

    return {
        "verdict": "accepted" if not rejection_reasons else "rejected",
        "win_rate_signals": win_rate_signals,
        "bounded_tradeoffs": bounded_tradeoffs,
        "rejection_reasons": rejection_reasons,
        "verdict_reason": verdict_reason,
    }


def _build_rollout_recommendation_payload(comparison_summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not comparison_summary:
        return {
            "action": "hold",
            "blockers": ["missing_comparison_summary"],
            "baseline_verdicts": {},
        }

    blockers: list[str] = []
    baseline_verdicts: dict[str, dict[str, Any]] = {}
    for baseline_name, entry in comparison_summary.items():
        baseline_blockers: list[str] = []
        for metric in COMPARISON_METRICS:
            delta = _safe_float(entry.get(f"{metric}_delta"))
            if delta is None:
                if metric not in OPTIONAL_COMPARISON_METRICS:
                    baseline_blockers.append(f"missing_{metric}_delta_vs_{baseline_name}")
                continue
            epsilon = float(COMPARISON_METRIC_EPSILON.get(metric, 0.0) or 0.0)
            metric_regressed = delta > epsilon if metric in LOWER_IS_BETTER_COMPARISON_METRICS else delta < -epsilon
            if metric_regressed:
                baseline_blockers.append(f"{metric}_regressed_vs_{baseline_name}")
        blockers.extend(baseline_blockers)
        baseline_verdicts[baseline_name] = {
            "status": "pass" if not baseline_blockers else "blocked",
            "blockers": baseline_blockers,
        }

    deduped_blockers = list(dict.fromkeys(blockers))
    strict_objective_gate = _load_strict_btst_objective_gate()
    execution_eligible_evidence = None
    if strict_objective_gate and strict_objective_gate.get("execution_eligible_evidence") is not None:
        execution_eligible_evidence = dict(strict_objective_gate.get("execution_eligible_evidence") or {})
    if strict_objective_gate:
        strict_gate_blockers = list(strict_objective_gate.get("blockers") or [])
        if strict_gate_blockers:
            deduped_blockers.extend([blocker for blocker in strict_gate_blockers if blocker not in deduped_blockers])

    # Task B (Round btst-winrate-design-20260517): add win-rate-first acceptance verdict
    win_rate_first_decision = _build_win_rate_first_decision(comparison_summary)

    # Task B (Round btst-winrate-design-20260517): win-rate-first rejection blocks promotion
    if win_rate_first_decision["verdict"] == "rejected":
        if "win_rate_first_rejected" not in deduped_blockers:
            deduped_blockers.append("win_rate_first_rejected")

    # Task B consistency fix: if strict/structural/baseline blockers are present,
    # win_rate_first_verdict_detail must surface "rollout_blocked" as dominant reason
    win_rate_first_verdict_detail = dict(win_rate_first_decision)
    non_win_rate_blockers = [b for b in deduped_blockers if b != "win_rate_first_rejected"]
    if non_win_rate_blockers and win_rate_first_decision["verdict"] == "rejected":
        # Override verdict_reason to prioritize rollout blockers
        win_rate_first_verdict_detail["verdict_reason"] = "rollout_blocked"
        # Task B output-surface fix: also prepend "rollout_blocked" to rejection_reasons
        # so that structured rejection reasons reflect blocker-first dominance
        existing_reasons = list(win_rate_first_verdict_detail.get("rejection_reasons") or [])
        if "rollout_blocked" not in existing_reasons:
            win_rate_first_verdict_detail["rejection_reasons"] = ["rollout_blocked"] + existing_reasons

    return {
        "action": "promote" if not deduped_blockers else "hold",  # action now respects win-rate-first blocker
        "blockers": deduped_blockers,
        "baseline_verdicts": baseline_verdicts,
        "strict_btst_objective_gate": strict_objective_gate,
        "execution_eligible_evidence": execution_eligible_evidence,
        "win_rate_first_decision": win_rate_first_decision,
        "win_rate_first_verdict": win_rate_first_decision["verdict"],
        "win_rate_first_verdict_detail": win_rate_first_verdict_detail,
    }


def _recommend_rollout_action(comparison_summary: dict[str, dict[str, Any]]) -> str:
    return str(_build_rollout_recommendation_payload(comparison_summary).get("action") or "hold")


def _load_strict_btst_objective_gate() -> dict[str, Any] | None:
    objective_monitor_path = REPORTS_DIR / "btst_tplus1_tplus2_objective_monitor_latest.md"
    structural_validation_path = REPORTS_DIR / "btst_admission_edge_replay_validation.json"
    if not objective_monitor_path.exists():
        return None
    structural_guardrail = None
    if structural_validation_path.exists():
        try:
            structural_payload = json.loads(structural_validation_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to load BTST structural guardrail sidecar from %s: %s", structural_validation_path, exc)
        else:
            if isinstance(structural_payload, Mapping):
                raw_structural_guardrail = structural_payload.get("structural_guardrail")
                if raw_structural_guardrail is None:
                    structural_guardrail = None
                elif isinstance(raw_structural_guardrail, Mapping):
                    structural_guardrail = dict(raw_structural_guardrail)
                else:
                    logger.warning("Ignoring non-mapping BTST structural guardrail payload from %s", structural_validation_path)
            else:
                logger.warning("Ignoring non-mapping BTST structural guardrail sidecar from %s", structural_validation_path)
    return build_strict_btst_objective_gate(
        parse_objective_monitor_markdown(objective_monitor_path),
        structural_guardrail=structural_guardrail,
    )


def _build_optimized_profile_manifest_publication(
    *,
    objective: SearchObjective,
    replay_mode: bool,
    replay_input_paths: list[Path] | None,
    best_params: dict[str, Any] | None,
    rollout_recommendation: str | None,
    profile_name: str,
    source_path: str | Path,
    manifest_path: str | Path,
) -> dict[str, Any]:
    resolved_manifest_path = Path(manifest_path).expanduser().resolve()
    if objective != SearchObjective.BTST:
        return {
            "status": "skipped",
            "reason": "non_btst_objective",
            "manifest_path": str(resolved_manifest_path),
        }
    if not replay_mode or not replay_input_paths:
        return {
            "status": "skipped",
            "reason": "non_replay_run",
            "manifest_path": str(resolved_manifest_path),
        }
    if best_params is None:
        return {
            "status": "skipped",
            "reason": "missing_best_params",
            "manifest_path": str(resolved_manifest_path),
        }
    return publish_btst_optimized_profile_manifest(
        manifest_path=resolved_manifest_path,
        rollout_recommendation=rollout_recommendation or "hold",
        profile_name=profile_name,
        profile_overrides=best_params,
        source_path=source_path,
        replay_input_paths=replay_input_paths,
    )


def _persist_search_metadata(
    *,
    md_path: Path,
    json_path: Path,
    metadata: dict[str, Any],
    comparison_summary: dict[str, dict[str, Any]] | None = None,
    rollout_recommendation: str | None = None,
    rollout_recommendation_details: dict[str, Any] | None = None,
    optimized_profile_manifest_publication: dict[str, Any] | None = None,
) -> None:
    md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else "# Parameter Search Report\n"
    metadata_lines = [
        "## Search Metadata",
        "",
        f"Search Stage: **{metadata['search_stage']}**",
        f"Checkpoint: `{metadata['checkpoint_path']}`",
    ]
    if metadata.get("focus_source"):
        metadata_lines.append(f"Focus Source: `{metadata['focus_source']}`")
    if metadata.get("guardrails"):
        metadata_lines.append("")
        metadata_lines.append("Guardrails:")
        for key, value in sorted(dict(metadata["guardrails"]).items()):
            metadata_lines.append(f"- `{key}`: {_format_guardrail_spec(value)}")
    md_block = "\n".join(metadata_lines)
    base_md_text = md_text.split("## Search Metadata", 1)[0].rstrip() if "## Search Metadata" in md_text else md_text.rstrip()
    md_sections = [base_md_text, md_block]
    if comparison_summary:
        metric_headers = [COMPARISON_METRIC_LABELS[metric] for metric in COMPARISON_METRICS]
        comparison_lines = [
            "## Baseline Comparison",
            "",
            "| Baseline | " + " | ".join(f"{label} Δ" for label in metric_headers) + " |",
            "| --- | " + " | ".join("---" for _ in metric_headers) + " |",
        ]
        for baseline_name, entry in comparison_summary.items():
            comparison_lines.append(
                "| "
                + baseline_name
                + " | "
                + " | ".join(
                    f"{float(entry[f'{metric}_delta']):.4f}" if _safe_float(entry.get(f"{metric}_delta")) is not None else "N/A"
                    for metric in COMPARISON_METRICS
                )
                + " |"
            )
        md_sections.append("\n".join(comparison_lines))
    if rollout_recommendation:
        rollout_lines = [f"Rollout Recommendation: **{rollout_recommendation}**"]
        # Task B output-surface fix: explicitly render win-rate-first verdict detail
        win_rate_first_verdict_detail = (rollout_recommendation_details or {}).get("win_rate_first_verdict_detail")
        if win_rate_first_verdict_detail:
            verdict = win_rate_first_verdict_detail.get("verdict", "unknown")
            verdict_reason = win_rate_first_verdict_detail.get("verdict_reason", "unknown")
            rejection_reasons = win_rate_first_verdict_detail.get("rejection_reasons", [])
            rollout_lines.append("")
            rollout_lines.append(f"**Win-Rate-First Verdict**: {verdict}")
            rollout_lines.append(f"- Verdict Reason: `{verdict_reason}`")
            if rejection_reasons:
                rollout_lines.append(f"- Rejection Reasons: {', '.join(f'`{r}`' for r in rejection_reasons)}")
            win_rate_signals = win_rate_first_verdict_detail.get("win_rate_signals", {})
            if win_rate_signals:
                rollout_lines.append(f"- Win-Rate Signals: {', '.join(f'{k}={v:.4f}' if v is not None else f'{k}=N/A' for k, v in win_rate_signals.items())}")
            bounded_tradeoffs = win_rate_first_verdict_detail.get("bounded_tradeoffs", {})
            if bounded_tradeoffs:
                rollout_lines.append(f"- Bounded Tradeoffs: {', '.join(f'{k}={v:.4f}' if v is not None else f'{k}=N/A' for k, v in bounded_tradeoffs.items())}")
        blockers = list((rollout_recommendation_details or {}).get("blockers") or [])
        if blockers:
            rollout_lines.append("")
            rollout_lines.append("Rollout Blockers:")
            rollout_lines.extend(f"- `{blocker}`" for blocker in blockers)
        md_sections.append("\n".join(rollout_lines))
    if optimized_profile_manifest_publication:
        publication_lines = [f"Optimized Profile Manifest Publication: **{optimized_profile_manifest_publication['status']}**"]
        manifest_path = optimized_profile_manifest_publication.get("manifest_path")
        if manifest_path:
            publication_lines.append(f"- manifest_path: `{manifest_path}`")
        reason = optimized_profile_manifest_publication.get("reason")
        if reason:
            publication_lines.append(f"- reason: `{reason}`")
        md_sections.append("\n".join(publication_lines))
    md_text = "\n\n".join(section for section in md_sections if section) + "\n"
    md_path.write_text(md_text, encoding="utf-8")

    payload = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else {}
    payload["metadata"] = metadata
    if comparison_summary is not None:
        payload["comparison_summary"] = comparison_summary
    if rollout_recommendation is not None:
        payload["rollout_recommendation"] = rollout_recommendation
    if rollout_recommendation_details is not None:
        payload["rollout_recommendation_details"] = rollout_recommendation_details
    if optimized_profile_manifest_publication is not None:
        payload["optimized_profile_manifest_publication"] = optimized_profile_manifest_publication
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _load_focus_params(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    best_params = payload.get("best_params")
    if isinstance(best_params, dict):
        return best_params
    completed_trials = [trial for trial in list(payload.get("completed_trials") or []) if isinstance(trial.get("params"), dict)]
    if completed_trials:
        completed_trials.sort(key=lambda trial: float(trial.get("score") or float("-inf")), reverse=True)
        return dict(completed_trials[0]["params"])
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"Could not load best_params from {path}")


def _resolve_focus_params_source(*, focus_json: str | None, checkpoint_path: str | None) -> tuple[dict[str, Any], str]:
    if focus_json:
        return _load_focus_params(focus_json), str(focus_json)
    if checkpoint_path and Path(checkpoint_path).exists():
        return _load_focus_params(checkpoint_path), str(checkpoint_path)
    raise ValueError("focused search stage requires --focus-json or an existing --checkpoint")


def _stage_checkpoint_path(checkpoint_path: str, stage_name: str) -> str:
    path = Path(checkpoint_path)
    if path.suffix:
        return str(path.with_name(f"{path.stem}_{stage_name}{path.suffix}"))
    return f"{checkpoint_path}_{stage_name}"


def _report_best_params(report: Any) -> dict[str, Any] | None:
    if isinstance(report, dict):
        params = report.get("best_params")
        return dict(params) if isinstance(params, dict) else None
    params = getattr(report, "best_params", None)
    return dict(params) if isinstance(params, dict) else None


def _report_best_score(report: Any) -> float | None:
    if isinstance(report, dict):
        return _safe_float(report.get("best_score"))
    return _safe_float(getattr(report, "best_score", None))


def _enforce_max_combinations(space: ParamSpace, max_combinations: int | None) -> None:
    if max_combinations is None:
        return
    size = space.size()
    if size > max_combinations:
        raise ValueError(f"max_combinations exceeded: grid has {size} combinations, limit={max_combinations}")


def build_stage_grid(
    *,
    base_grid: dict[str, list[Any]],
    search_stage: str,
    focus_params: dict[str, Any] | None = None,
) -> dict[str, list[Any]]:
    if search_stage != "focused":
        return base_grid
    if not focus_params:
        raise ValueError("focused search stage requires focus_params")

    focused_grid: dict[str, list[Any]] = {}
    for key, values in base_grid.items():
        focus_value = focus_params.get(key)
        if focus_value is None:
            focused_grid[key] = values
            continue
        if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            if len(values) <= 3:
                focused_grid[key] = values
                continue
            if focus_value in values:
                focus_index = values.index(focus_value)
            else:
                focus_index = min(range(len(values)), key=lambda idx: abs(float(values[idx]) - float(focus_value)))
            start = max(0, focus_index - 1)
            end = min(len(values), start + 3)
            start = max(0, end - 3)
            focused_grid[key] = values[start:end]
            continue
        focused_grid[key] = [focus_value] if focus_value in values else values
    return focused_grid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optimize short-trade target profile parameters")
    parser.add_argument("--profile", default="momentum_optimized", help="Base profile name")
    parser.add_argument("--objective", choices=[o.value for o in SearchObjective], default="edge")
    parser.add_argument("--input", nargs="+", help="Replay input JSON paths (replay mode)")
    parser.add_argument("--reports-root", default=None, help="Reports root for weekly replay-input auto-discovery")
    parser.add_argument("--weekly-start-date", default=None, help="Weekly replay-input discovery start date")
    parser.add_argument("--weekly-end-date", default=None, help="Weekly replay-input discovery end date")
    parser.add_argument("--grid-params", nargs="+", help="Grid params as key=val1,val2 or path/to.json")
    parser.add_argument("--preset-grid", action="store_true", help="Use built-in momentum_optimized grid")
    parser.add_argument(
        "--staged-mode",
        choices=["ignition_stage1"],
        default=None,
        help="Run a narrow staged calibration workflow for a routed BTST profile.",
    )
    parser.add_argument("--output-json", default=None, help="Output JSON path")
    parser.add_argument("--output-md", default=None, help="Output Markdown path")
    parser.add_argument("--checkpoint", default=None, help="Checkpoint file for resume")
    parser.add_argument("--guardrail", action="append", default=None, help="Guardrail bound as metric=floor, metric>=floor, or metric<=cap; may be repeated")
    parser.add_argument("--search-stage", choices=["full", "coarse", "focused", "staged"], default="full", help="Search stage strategy")
    parser.add_argument("--focus-json", default=None, help="JSON file with best_params for focused stage")
    parser.add_argument("--max-combinations", type=int, default=None, help="Fail fast when grid size exceeds this budget")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    # Walk-forward mode args
    parser.add_argument("--tickers", default=None, help="Tickers for walk-forward mode")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--model-provider", default=None)
    parser.add_argument("--train-months", type=int, default=2)
    parser.add_argument("--test-months", type=int, default=2)
    parser.add_argument("--step-months", type=int, default=1)
    args = parser.parse_args(argv)

    get_short_trade_target_profile(args.profile)

    if args.preset_grid or args.grid_params or args.staged_mode:
        try:
            grid = resolve_grid_params(
                grid_params=args.grid_params or [],
                preset_grid=args.preset_grid,
                profile_name=args.profile,
                search_stage=args.search_stage,
                staged_mode=args.staged_mode,
            )
        except ValueError as exc:
            parser.error(str(exc))
    else:
        parser.error("Specify --preset-grid or --grid-params")

    focus_source = args.focus_json
    if args.search_stage == "focused":
        focus_params, focus_source = _resolve_focus_params_source(
            focus_json=args.focus_json,
            checkpoint_path=args.checkpoint,
        )
        grid = build_stage_grid(
            base_grid=grid,
            search_stage=args.search_stage,
            focus_params=focus_params,
        )

    space = ParamSpace(grid=grid)
    _enforce_max_combinations(space, args.max_combinations)
    logger.info("Grid size: %d combinations", space.size())

    objective = SearchObjective(args.objective)

    replay_input_paths: list[Path] | None = None
    walk_forward_descriptor: str | None = None
    replay_mode = False
    if args.input or (args.reports_root and args.weekly_start_date and args.weekly_end_date):
        replay_mode = True
        replay_input_paths = resolve_replay_input_paths(
            input_paths=args.input,
            reports_root=args.reports_root,
            weekly_start_date=args.weekly_start_date,
            weekly_end_date=args.weekly_end_date,
        )
        if args.staged_mode == "ignition_stage1":
            evaluator = _build_staged_ignition_evaluator(
                replay_input_paths,
                base_profile=args.profile,
                next_high_hit_threshold=args.next_high_hit_threshold,
            )
        else:
            evaluator = _build_replay_evaluator(
                replay_input_paths,
                base_profile=args.profile,
                next_high_hit_threshold=args.next_high_hit_threshold,
            )
    elif args.tickers and args.start_date and args.end_date:
        if args.staged_mode == "ignition_stage1":
            parser.error(
                "--staged-mode ignition_stage1 requires replay inputs (--input or --reports-root). "
                "Walk-forward mode does not support staged evaluation."
            )
        walk_forward_descriptor = "|".join(
            [
                str(args.tickers),
                str(args.start_date),
                str(args.end_date),
                str(args.initial_capital),
                str(args.model_name),
                str(args.model_provider),
                str(args.train_months),
                str(args.test_months),
                str(args.step_months),
            ]
        )
        evaluator = _build_walk_forward_evaluator(
            tickers=args.tickers.split(","),
            start_date=args.start_date,
            end_date=args.end_date,
            initial_capital=args.initial_capital,
            model_name=args.model_name,
            model_provider=args.model_provider,
            selected_analysts=None,
            train_months=args.train_months,
            test_months=args.test_months,
            step_months=args.step_months,
            base_profile=args.profile,
        )
    else:
        parser.error("Specify --input, or --reports-root with --weekly-start-date and --weekly-end-date, or --tickers --start-date --end-date for walk-forward mode")

    checkpoint = args.checkpoint or _build_default_checkpoint_path(
        profile=args.profile,
        objective=args.objective,
        replay_input_paths=replay_input_paths,
        walk_forward_descriptor=walk_forward_descriptor,
    )
    guardrails = resolve_guardrails(
        profile_name=args.profile,
        objective=args.objective,
        replay_mode=replay_mode,
        raw_guardrails=args.guardrail or [],
    )
    stage_results = None
    if args.search_stage == "staged":
        coarse_grid = resolve_grid_params(
            grid_params=args.grid_params or [],
            preset_grid=args.preset_grid,
            profile_name=args.profile,
            search_stage="coarse",
        )
        coarse_space = ParamSpace(grid=coarse_grid)
        _enforce_max_combinations(coarse_space, args.max_combinations)
        coarse_checkpoint = _stage_checkpoint_path(checkpoint, "coarse")
        coarse_report = run_param_search(
            space=coarse_space,
            objective=objective,
            evaluator=evaluator,
            checkpoint_path=coarse_checkpoint,
            guardrails=guardrails or None,
        )
        coarse_best_params = _report_best_params(coarse_report)

        focused_grid = resolve_grid_params(
            grid_params=args.grid_params or [],
            preset_grid=args.preset_grid,
            profile_name=args.profile,
            search_stage="focused",
        )
        focused_grid = build_stage_grid(
            base_grid=focused_grid,
            search_stage="focused",
            focus_params=coarse_best_params,
        )
        space = ParamSpace(grid=focused_grid)
        _enforce_max_combinations(space, args.max_combinations)
        checkpoint = _stage_checkpoint_path(checkpoint, "focused")
        report = run_param_search(
            space=space,
            objective=objective,
            evaluator=evaluator,
            checkpoint_path=checkpoint,
            guardrails=guardrails or None,
        )
        stage_results = {
            "coarse": {
                "best_params": coarse_best_params,
                "best_score": _report_best_score(coarse_report),
                "checkpoint_path": coarse_checkpoint,
            },
            "focused": {
                "best_params": _report_best_params(report),
                "best_score": _report_best_score(report),
                "checkpoint_path": checkpoint,
            },
        }
        focus_source = coarse_checkpoint
    else:
        report = run_param_search(
            space=space,
            objective=objective,
            evaluator=evaluator,
            checkpoint_path=checkpoint,
            guardrails=guardrails or None,
        )

    md_path = save_search_report(report, args.output_md)
    json_path = save_search_payload(report, args.output_json)
    metadata = _build_search_metadata(
        search_stage=args.search_stage,
        guardrails=guardrails,
        focus_json=focus_source,
        checkpoint_path=checkpoint,
        stage_results=stage_results,
    )
    comparison_summary = None
    rollout_recommendation = None
    rollout_recommendation_details = None
    best_params = _report_best_params(report)
    if replay_mode and replay_input_paths and best_params is not None:
        comparison_summary = _build_replay_comparison_summary(
            replay_input_paths=replay_input_paths,
            base_profile=args.profile,
            best_params=best_params,
            next_high_hit_threshold=args.next_high_hit_threshold,
        )
        rollout_recommendation_details = _build_rollout_recommendation_payload(comparison_summary)
        rollout_recommendation = str(rollout_recommendation_details.get("action") or "hold")
    optimized_profile_manifest_publication = _build_optimized_profile_manifest_publication(
        objective=objective,
        replay_mode=replay_mode,
        replay_input_paths=replay_input_paths,
        best_params=best_params,
        rollout_recommendation=rollout_recommendation,
        profile_name=args.profile,
        source_path=json_path,
        manifest_path=REPORTS_DIR / "btst_latest_optimized_profile.json",
    )
    _persist_search_metadata(
        md_path=md_path,
        json_path=json_path,
        metadata=metadata,
        comparison_summary=comparison_summary,
        rollout_recommendation=rollout_recommendation,
        rollout_recommendation_details=rollout_recommendation_details,
        optimized_profile_manifest_publication=optimized_profile_manifest_publication,
    )
    print(format_search_report(report))
    if args.staged_mode == "ignition_stage1":
        print(_format_staged_ignition_summary(report))
    print(f"\nReport: {md_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
