"""Conservative continuous portfolio evaluation (Plan 03 Task 5).

Official metric: excess daily log growth of the complete portfolio unit
NAV against the benchmark. Single-name returns, win rates and IC are
diagnostics only and never enter promotion gates. All estimators are
transparent and deterministic; outer-fold data never tunes hyperparameters
(leakage guard: only evidence committed at or before the signal cutoff is
consumed). Minimum-evidence gates are DISTINCT predicates, never merged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import log, sqrt
from typing import Final, Sequence

from scipy import stats

from src.screening.offensive.v3.contracts.base import CanonicalModel

MINIMUM_MATURE_OUTCOMES: Final[int] = 150
MINIMUM_DECISION_DAYS: Final[int] = 60
MINIMUM_ESS: Final[int] = 60
MINIMUM_TICKERS: Final[int] = 80
MINIMUM_MONTHS: Final[int] = 12
CONFIDENCE_LEVEL: Final[float] = 0.95
CDAR_QUANTILE: Final[float] = 0.90
SLIPPAGE_MULTIPLIER: Final[float] = 2.0


class StatisticsError(RuntimeError):
    """Fail-closed rejection of an evaluation input."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def excess_daily_log_growth(
    unit_nav: Sequence[float],
    benchmark_nav: Sequence[float],
) -> tuple[float, ...]:
    """Excess daily log growth of unit NAV over the benchmark."""

    if len(unit_nav) != len(benchmark_nav):
        raise StatisticsError(
            "series_length_mismatch",
            "unit NAV and benchmark must align day by day",
        )
    if len(unit_nav) < 2:
        raise StatisticsError(
            "series_too_short", "at least two observations are required"
        )
    growth: list[float] = []
    for index in range(1, len(unit_nav)):
        if min(
            unit_nav[index],
            unit_nav[index - 1],
            benchmark_nav[index],
            benchmark_nav[index - 1],
        ) <= 0:
            raise StatisticsError(
                "non_positive_nav", "NAV series must stay strictly positive"
            )
        growth.append(
            log(unit_nav[index] / unit_nav[index - 1])
            - log(benchmark_nav[index] / benchmark_nav[index - 1])
        )
    return tuple(growth)


def apply_slippage_drag(
    daily_returns: Sequence[float],
    daily_slippage: float,
    *,
    multiplier: float = SLIPPAGE_MULTIPLIER,
) -> tuple[float, ...]:
    """Charge 2x the measured daily slippage against each day."""

    drag = multiplier * daily_slippage
    return tuple(value - drag for value in daily_returns)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    center = _mean(values)
    return sqrt(
        sum((value - center) ** 2 for value in values) / (len(values) - 1)
    )


def one_sided_lower_bound(
    values: Sequence[float],
    confidence: float = CONFIDENCE_LEVEL,
) -> float:
    """One-sided t lower confidence bound for the mean.

    Transparent estimator: mean minus the one-sided t critical value times
    the standard error. Deterministic for a fixed sample.
    """

    if len(values) < 2:
        raise StatisticsError(
            "sample_too_small",
            "at least two observations are required for a bound",
        )
    n = len(values)
    critical = float(stats.t.ppf(confidence, df=n - 1))
    return _mean(values) - critical * _std(values) / sqrt(n)


def maximum_drawdown(unit_nav: Sequence[float]) -> float:
    """MDD of the unit NAV path (a non-negative fraction)."""

    peak = unit_nav[0]
    mdd = 0.0
    for value in unit_nav:
        peak = max(peak, value)
        mdd = max(mdd, (peak - value) / peak)
    return mdd


def conditional_drawdown_at_risk(
    unit_nav: Sequence[float], quantile: float = CDAR_QUANTILE
) -> float:
    """CDaR: mean of drawdowns beyond the quantile (continuous replay).

    Stateful tail metric computed from the complete per-day drawdown path
    of ONE continuous replay - never stitched independent return blocks.
    """

    peak = unit_nav[0]
    drawdowns: list[float] = []
    for value in unit_nav:
        peak = max(peak, value)
        drawdowns.append((peak - value) / peak)
    drawdowns.sort()
    cutoff_index = int(len(drawdowns) * quantile)
    tail = drawdowns[cutoff_index:]
    if not tail:
        return drawdowns[-1]
    return sum(tail) / len(tail)


def effective_sample_size(weights: Sequence[float]) -> float:
    """Kish ESS of the position weight distribution."""

    total = sum(weights)
    if total <= 0:
        return 0.0
    normalized = [weight / total for weight in weights]
    sum_squares = sum(p * p for p in normalized)
    if sum_squares == 0:
        return 0.0
    return 1.0 / sum_squares


class MinimumEvidenceReport(CanonicalModel):
    """DISTINCT minimum-evidence predicates; every gate is separate."""

    mature_outcome_count: int
    decision_day_count: int
    effective_sample_size: float
    ticker_count: int
    month_count: int
    adverse_window_complete: bool

    def outcomes_sufficient(self) -> bool:
        return self.mature_outcome_count >= MINIMUM_MATURE_OUTCOMES

    def decision_days_sufficient(self) -> bool:
        return self.decision_day_count >= MINIMUM_DECISION_DAYS

    def ess_sufficient(self) -> bool:
        return self.effective_sample_size >= MINIMUM_ESS

    def tickers_sufficient(self) -> bool:
        return self.ticker_count >= MINIMUM_TICKERS

    def months_sufficient(self) -> bool:
        return self.month_count >= MINIMUM_MONTHS

    def all_satisfied(self) -> bool:
        return (
            self.outcomes_sufficient()
            and self.decision_days_sufficient()
            and self.ess_sufficient()
            and self.tickers_sufficient()
            and self.months_sufficient()
            and self.adverse_window_complete
        )


class PortfolioEvaluation(CanonicalModel):
    """One frozen-policy evaluation over committed evidence only."""

    excess_mean: float
    excess_lcb_95: float
    minimum_economic_effect: float
    lcb_above_mee: bool
    excess_mean_at_double_slippage: float
    adverse_window_excess_mean: float | None
    maximum_drawdown: float
    conditional_drawdown_at_risk: float
    observation_count: int
    evaluated_at: datetime
    evidence_cutoff: datetime

    def passes_economic_gate(self) -> bool:
        return self.lcb_above_mee


def evaluate_frozen_policy(
    *,
    excess_returns: Sequence[float],
    minimum_economic_effect: float,
    evaluated_at: datetime,
    evidence_cutoff: datetime,
    committed_at: Sequence[datetime] | None = None,
    adverse_window: tuple[int, int] | None = None,
    daily_slippage: float = 0.0,
    unit_nav: Sequence[float] | None = None,
) -> PortfolioEvaluation:
    """Evaluate one frozen policy with committed evidence only.

    Leakage guard: when ``committed_at`` is supplied, observations whose
    evidence committed after ``evidence_cutoff`` are excluded - official
    OOS never sees post-cutoff revisions.
    """

    returns = list(excess_returns)
    if committed_at is not None:
        if len(committed_at) != len(returns):
            raise StatisticsError(
                "commit_time_length_mismatch",
                "committed_at must align with observations",
            )
        returns = [
            value
            for value, committed in zip(returns, committed_at)
            if committed <= evidence_cutoff
        ]
    if len(returns) < 2:
        raise StatisticsError(
            "sample_too_small",
            "fewer than two committed observations before cutoff",
        )
    lcb = one_sided_lower_bound(returns)
    slipped = apply_slippage_drag(returns, daily_slippage)
    adverse_mean: float | None = None
    if adverse_window is not None:
        start, end = adverse_window
        if not (0 <= start <= end <= len(returns)):
            raise StatisticsError(
                "adverse_window_invalid",
                "adverse window must index the committed sample",
            )
        window = returns[start:end]
        adverse_mean = _mean(window) if window else None
    nav = unit_nav if unit_nav is not None else _nav_from_returns(returns)
    return PortfolioEvaluation(
        excess_mean=float(_mean(returns)),
        excess_lcb_95=float(lcb),
        minimum_economic_effect=float(minimum_economic_effect),
        lcb_above_mee=bool(lcb > minimum_economic_effect),
        excess_mean_at_double_slippage=float(_mean(slipped)),
        adverse_window_excess_mean=(
            None if adverse_mean is None else float(adverse_mean)
        ),
        maximum_drawdown=float(maximum_drawdown(nav)),
        conditional_drawdown_at_risk=float(
            conditional_drawdown_at_risk(nav)
        ),
        observation_count=len(returns),
        evaluated_at=evaluated_at,
        evidence_cutoff=evidence_cutoff,
    )


def _nav_from_returns(returns: Sequence[float]) -> tuple[float, ...]:
    nav = [1.0]
    for value in returns:
        nav.append(nav[-1] * (1.0 + value))
    return tuple(nav)


def check_minimum_evidence(report: MinimumEvidenceReport) -> dict[str, bool]:
    """Each predicate separately; never a merged gate."""

    return {
        "mature_outcomes": report.outcomes_sufficient(),
        "decision_days": report.decision_days_sufficient(),
        "ess": report.ess_sufficient(),
        "tickers": report.tickers_sufficient(),
        "months": report.months_sufficient(),
        "adverse_window": report.adverse_window_complete,
        "all": report.all_satisfied(),
    }


def check_tail_capacity(
    evaluation: PortfolioEvaluation,
    *,
    mdd_cap: float,
    cdar_cap: float,
) -> dict[str, bool]:
    return {
        "mdd_within_cap": evaluation.maximum_drawdown <= mdd_cap,
        "cdar_within_cap": (
            evaluation.conditional_drawdown_at_risk <= cdar_cap
        ),
        "passes": (
            evaluation.maximum_drawdown <= mdd_cap
            and evaluation.conditional_drawdown_at_risk <= cdar_cap
        ),
    }


__all__ = [
    "CONFIDENCE_LEVEL",
    "MINIMUM_DECISION_DAYS",
    "MINIMUM_ESS",
    "MINIMUM_MATURE_OUTCOMES",
    "MINIMUM_MONTHS",
    "MINIMUM_TICKERS",
    "MinimumEvidenceReport",
    "PortfolioEvaluation",
    "StatisticsError",
    "apply_slippage_drag",
    "check_minimum_evidence",
    "check_tail_capacity",
    "conditional_drawdown_at_risk",
    "effective_sample_size",
    "evaluate_frozen_policy",
    "excess_daily_log_growth",
    "maximum_drawdown",
    "one_sided_lower_bound",
]
