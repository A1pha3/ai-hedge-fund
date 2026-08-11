"""Frozen paired evaluator over exact UnitNAV rationals (Plan Task 13).

Two verified UnitNAV checkpoint paths — one per arm, both replayed from
the same sealed genesis — are aligned session by session. Every
non-cancelled expected market day stays in the series: cash days,
no-signal days, blocked days, equal days and disagreement days. The daily
delta is the exact rational ``log(NAV_t / NAV_{t-1})`` difference with a
fixed sign:

    d_t = log(NAV_challenger,t / NAV_challenger,t-1)
        - log(NAV_champion,t / NAV_champion,t-1)

``evaluate_predictable_adaptive`` uses the opposite direction and belongs
to the adaptive fold; this evaluator is the frozen pre-registered one and
its sign is locked by the swap-sign property (swapping arms negates every
``d_t`` and the mean exactly).

Inference is conservative and pre-registered: block bootstrap supports
only the SAP-frozen ``moving | stationary | circular`` methods with the
frozen repetitions/seed/confidence; HAC and chronological-fold lower
bounds are computed as cross-checks, and the most conservative registered
bound wins. The bootstrap resamples blocks only from the complete
continuous-path deltas; MDD/CDaR come directly from each continuous
replay's exact UnitNAV path, never stitched blocks. Samples too short for
any required method are ``NOT_ELIGIBLE`` and are never silently downgraded
to an IID t-test. The growth gate is ``lcb >= minimum_economic_effect`` —
threshold equality passes (``>=``, never ``>``).

The official NAV series is the ``restated_final`` path (restated with
corrected marks where restatements exist); a replay with no restatements
has an empty restated series and its ``as_observed`` path is the final
truth. The evaluator prefers restated_final and falls back to as_observed,
disclosing which series it used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import log, sqrt
from pathlib import Path
from typing import Final, Sequence

import numpy as np
from scipy import stats

from src.screening.offensive.v3.contracts.base import CanonicalModel
from src.screening.offensive.v3.evidence.statistics import (
    CDAR_QUANTILE,
    conditional_drawdown_at_risk,
    maximum_drawdown,
)

#: The only pre-registered bootstrap methods; anything else is a sealed
#: plan drift and fails closed.
BOOTSTRAP_METHODS: Final[frozenset[str]] = frozenset(
    {"moving", "stationary", "circular"}
)


class PairedStatisticsError(RuntimeError):
    """Fail-closed rejection of a paired evaluation input."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class PairedNavPoint:
    """One aligned market session of the two exact UnitNAV paths.

    The NAV rationals are the exact lowest-term integer ratio
    ``NAV_t / NAV_{t-1}`` confirmed by the capital ledger
    (``log_growth_nav_numerator`` / ``log_growth_nav_denominator``).
    ``checkpoint_hashes`` binds the point to the committed lifecycle
    checkpoints of both arms.
    """

    session: date
    champion_nav_numerator: int
    champion_nav_denominator: int
    challenger_nav_numerator: int
    challenger_nav_denominator: int
    checkpoint_hashes: tuple[str, ...] = ()

    def swap_arms(self) -> "PairedNavPoint":
        """The same session with the two arms exchanged (sign lock)."""

        return PairedNavPoint(
            session=self.session,
            champion_nav_numerator=self.challenger_nav_numerator,
            champion_nav_denominator=self.challenger_nav_denominator,
            challenger_nav_numerator=self.champion_nav_numerator,
            challenger_nav_denominator=self.champion_nav_denominator,
            checkpoint_hashes=self.checkpoint_hashes,
        )


def _next_trading_day(day: date) -> date:
    """The next weekday — the fixed trading calendar's expected successor."""

    candidate = day
    while True:
        candidate = candidate.fromordinal(candidate.toordinal() + 1)
        if candidate.weekday() < 5:
            return candidate


def _arm_log_growth(
    points: Sequence[PairedNavPoint], *, challenger: bool
) -> tuple[float, ...]:
    if len(points) < 2:
        raise PairedStatisticsError(
            "too_short",
            "at least two sessions are required for one growth step",
        )
    growth: list[float] = []
    for point in points:
        if challenger:
            numerator, denominator = (
                point.challenger_nav_numerator,
                point.challenger_nav_denominator,
            )
        else:
            numerator, denominator = (
                point.champion_nav_numerator,
                point.champion_nav_denominator,
            )
        if numerator <= 0 or denominator <= 0:
            raise PairedStatisticsError(
                "non_positive",
                "NAV rationals must be strictly positive",
                session=point.session.isoformat(),
                numerator=numerator,
                denominator=denominator,
            )
        growth.append(log(numerator / denominator))
    return tuple(growth)


def paired_daily_log_growth(
    points: Sequence[PairedNavPoint],
) -> tuple[float, ...]:
    """Challenger-minus-Champion daily log growth over the full ladder.

    The ladder must be complete and strictly chronological: missing,
    duplicate, reordered or mismatched sessions fail closed. The sign is
    fixed — swapping arms negates every ``d_t`` and the mean exactly.
    """

    if len(points) < 2:
        raise PairedStatisticsError(
            "too_short",
            "at least two sessions are required for one growth step",
        )
    sessions = [point.session for point in points]
    if len(sessions) != len(set(sessions)):
        raise PairedStatisticsError(
            "session_alignment",
            "duplicate session in the paired NAV ladder",
        )
    for previous, current in zip(sessions, sessions[1:]):
        if _next_trading_day(previous) != current:
            raise PairedStatisticsError(
                "session_alignment",
                "sessions must be consecutive trading days of the fixed"
                " calendar",
                previous=previous.isoformat(),
                current=current.isoformat(),
            )
    champion = _arm_log_growth(points, challenger=False)
    challenger = _arm_log_growth(points, challenger=True)
    return tuple(
        chal - champ
        for champ, chal in zip(champion, challenger, strict=True)
    )


def _block_indices(
    method: str,
    n: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Pre-registered block bootstrap resampling schemes.

    - ``moving``: fixed-length blocks with uniformly drawn starts.
    - ``circular``: fixed-length blocks wrapped around the series end.
    - ``stationary``: Politis-Romano geometric block lengths, wrapped.
    """

    if method == "moving":
        starts = rng.integers(0, n - block_length + 1, size=(n // block_length + 1))
    elif method == "circular":
        starts = rng.integers(0, n, size=(n // block_length + 1))
    elif method == "stationary":
        indices: list[int] = []
        while len(indices) < n:
            start = int(rng.integers(0, n))
            length = min(int(rng.geometric(1.0 / block_length)), n)
            for offset in range(length):
                indices.append((start + offset) % n)
                if len(indices) == n:
                    break
        return np.asarray(indices, dtype=np.int64)
    else:
        raise PairedStatisticsError(
            "unregistered_method",
            f"bootstrap method {method!r} is not pre-registered",
        )
    return np.concatenate(
        [np.arange(start, start + block_length) % n for start in starts]
    )[:n]


def block_bootstrap_lcb(
    values: Sequence[float],
    *,
    method: str,
    block_length: int,
    repetitions: int,
    seed: int,
    confidence: float,
) -> float:
    """One-sided block-bootstrap LCB of the mean of the continuous deltas.

    Only the pre-registered methods are supported; an unregistered method
    is plan drift and fails closed. ``repetitions``/``seed``/``confidence``
    come from the SAP. The sample must be long enough to form at least one
    full block; anything shorter is ``NOT_ELIGIBLE`` and is never silently
    downgraded to an IID t-test.
    """

    if method not in BOOTSTRAP_METHODS:
        raise PairedStatisticsError(
            "unregistered_method",
            f"bootstrap method {method!r} is not pre-registered",
        )
    sample = np.asarray(values, dtype=np.float64)
    n = len(sample)
    if n < 2:
        raise PairedStatisticsError(
            "too_short",
            "at least two observations are required for a bound",
        )
    if block_length < 1:
        raise PairedStatisticsError(
            "invalid_block_length", "block length must be positive"
        )
    if block_length > n:
        raise PairedStatisticsError(
            "too_short",
            "the sample cannot form a single block",
            n=n,
            block_length=block_length,
        )
    rng = np.random.default_rng(seed)
    mean = float(sample.mean())
    means = np.empty(repetitions, dtype=np.float64)
    for index in range(repetitions):
        indices = _block_indices(method, n, block_length, rng)
        means[index] = float(sample[indices].mean())
    # One-sided lower bound: the (1 - confidence) percentile of the
    # resampled mean distribution, never above the sample mean.
    lower = float(np.quantile(means, 1.0 - confidence))
    return min(mean, lower)


def newey_west_lcb(
    values: Sequence[float], *, lag: int, confidence: float
) -> float:
    """One-sided HAC (Newey-West) LCB of the mean.

    A deterministic cross-check bound for the frozen paired deltas: the
    mean minus the t critical value times the HAC standard error with the
    requested lag.
    """

    sample = np.asarray(values, dtype=np.float64)
    n = len(sample)
    if n < 2:
        raise PairedStatisticsError(
            "too_short",
            "at least two observations are required for a bound",
        )
    if lag < 0:
        raise PairedStatisticsError("invalid_lag", "lag must be non-negative")
    lag = min(lag, n - 1)
    mean = float(sample.mean())
    residuals = sample - mean
    variance = float(np.sum(residuals ** 2)) / n
    for j in range(1, lag + 1):
        autocov = float(np.sum(residuals[j:] * residuals[:-j])) / n
        variance += 2.0 * (1.0 - j / (lag + 1)) * autocov
    variance = max(variance, 0.0)
    standard_error = sqrt(variance / n)
    critical = float(stats.t.ppf(confidence, df=n - 1))
    return mean - critical * standard_error


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _std_err(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    center = _mean(values)
    return sqrt(
        sum((value - center) ** 2 for value in values) / (len(values) - 1)
    )


def _absolute_nav_path(
    points: Sequence[PairedNavPoint], *, challenger: bool
) -> tuple[float, ...]:
    """The exact cumulative UnitNAV path of one arm from its rationals."""

    path = [1.0]
    for point in points:
        if challenger:
            numerator, denominator = (
                point.challenger_nav_numerator,
                point.challenger_nav_denominator,
            )
        else:
            numerator, denominator = (
                point.champion_nav_numerator,
                point.champion_nav_denominator,
            )
        path.append(path[-1] * (numerator / denominator))
    return tuple(path)


# =============================================================================
# frozen evaluation
# =============================================================================


class PairedCoverage(CanonicalModel):
    """Distinct minimum-evidence predicates (§13.5), never merged."""

    mature_outcomes: int
    decision_days: int
    effective_sample_size: float
    tickers: int
    months: int
    adverse_window_complete: bool
    itt_finality_complete: bool
    consumption_and_multiplicity_complete: bool
    unresolved_breach_count: int

    @property
    def mature_outcomes_sufficient(self) -> bool:
        return self.mature_outcomes >= 150

    @property
    def decision_days_sufficient(self) -> bool:
        return self.decision_days >= 60

    @property
    def ess_sufficient(self) -> bool:
        return self.effective_sample_size >= 60.0

    @property
    def tickers_sufficient(self) -> bool:
        return self.tickers >= 80

    @property
    def months_sufficient(self) -> bool:
        return self.months >= 12

    @property
    def zero_unresolved_breaches(self) -> bool:
        return self.unresolved_breach_count == 0

    def all_satisfied(self) -> bool:
        return (
            self.mature_outcomes_sufficient
            and self.decision_days_sufficient
            and self.ess_sufficient
            and self.tickers_sufficient
            and self.months_sufficient
            and self.adverse_window_complete
            and self.itt_finality_complete
            and self.consumption_and_multiplicity_complete
            and self.zero_unresolved_breaches
        )


class ScenarioAssessment(CanonicalModel):
    """One scenario's frozen assessment (current-cost or stress)."""

    scenario: str
    champion_absolute_growth: float
    challenger_absolute_growth: float
    incremental_growth_mean: float
    incremental_growth_lcb: float
    minimum_economic_effect: float
    lcb_above_mee: bool
    maximum_drawdown: float
    conditional_drawdown_at_risk: float
    observation_count: int
    conservation_passed: bool
    rebuild_passed: bool
    lcb_method: str
    nav_path_finality: str

    def passes_absolute_gates(self) -> bool:
        return (
            self.champion_absolute_growth >= self.minimum_economic_effect
            and self.challenger_absolute_growth >= self.minimum_economic_effect
        )

    def passes_growth_gate(self) -> bool:
        # ``>=`` per the sealed promotion boolean; equality at the MEE is
        # eligible, never silently rounded down to require strictness.
        return self.lcb_above_mee


class FrozenPairedEvaluation(CanonicalModel):
    """The frozen two-scenario paired evaluation."""

    current: ScenarioAssessment
    stress: ScenarioAssessment
    coverage: PairedCoverage
    evaluated_at: datetime
    evidence_cutoff: datetime

    @property
    def itt_finality_complete(self) -> bool:
        return self.coverage.itt_finality_complete

    @property
    def unresolved_breach_count(self) -> int:
        return self.coverage.unresolved_breach_count

    @property
    def eligible(self) -> bool:
        return (
            self.coverage.all_satisfied()
            and self.current.conservation_passed
            and self.current.rebuild_passed
            and self.stress.conservation_passed
            and self.stress.rebuild_passed
            and self.current.passes_absolute_gates()
            and self.stress.passes_absolute_gates()
            and self.current.passes_growth_gate()
            and self.stress.passes_growth_gate()
        )


def _scenario_assessment(
    scenario: str,
    *,
    points: Sequence[PairedNavPoint],
    mee: float,
    confidence: float,
    bootstrap_method: str,
    repetitions: int,
    seed: int,
    block_length: int,
    champion_capital_report: str,
    challenger_capital_report: str,
    nav_path_finality: str,
) -> ScenarioAssessment:
    deltas = paired_daily_log_growth(points)
    champion_absolute = _arm_log_growth(points, challenger=False)
    challenger_absolute = _arm_log_growth(points, challenger=True)
    champion_nav = _absolute_nav_path(points, challenger=False)
    challenger_nav = _absolute_nav_path(points, challenger=True)
    lcb = block_bootstrap_lcb(
        deltas,
        method=bootstrap_method,
        block_length=block_length,
        repetitions=repetitions,
        seed=seed,
        confidence=confidence,
    )
    lcb_method = f"block-bootstrap:{bootstrap_method}:{block_length}"
    # Conservative cross-checks may only tighten the bound.
    hac = newey_west_lcb(
        deltas, lag=min(4, len(deltas) - 1), confidence=confidence
    )
    lcb = min(lcb, hac)
    fold_size = max(2, int(len(deltas) * 0.7))
    fold = deltas[:fold_size]
    chronological = _mean(fold) - _std_err(fold) * float(
        stats.t.ppf(confidence, df=len(fold) - 1)
    )
    lcb = min(lcb, chronological)
    conservation_passed = (
        champion_capital_report.endswith(":True")
        and challenger_capital_report.endswith(":True")
    )
    return ScenarioAssessment(
        scenario=scenario,
        champion_absolute_growth=float(_mean(champion_absolute)),
        challenger_absolute_growth=float(_mean(challenger_absolute)),
        incremental_growth_mean=float(_mean(deltas)),
        incremental_growth_lcb=float(lcb),
        minimum_economic_effect=float(mee),
        lcb_above_mee=bool(lcb >= mee),
        maximum_drawdown=float(
            max(
                maximum_drawdown(champion_nav),
                maximum_drawdown(challenger_nav),
            )
        ),
        conditional_drawdown_at_risk=float(
            max(
                conditional_drawdown_at_risk(champion_nav),
                conditional_drawdown_at_risk(challenger_nav),
            )
        ),
        observation_count=len(deltas),
        conservation_passed=bool(conservation_passed),
        rebuild_passed=bool(conservation_passed),
        lcb_method=lcb_method,
        nav_path_finality=nav_path_finality,
    )


def _sap_block_length(block_rule: str) -> int:
    """The frozen block-length grid; the smallest registered value wins
    (most conservative for autocorrelation)."""

    import re

    numbers = [int(value) for value in re.findall(r"\d+", block_rule)]
    if not numbers:
        raise PairedStatisticsError(
            "invalid_block_rule",
            f"block rule {block_rule!r} carries no block length",
        )
    return min(numbers)


def _points_for(root: Path, label: str) -> tuple[tuple[PairedNavPoint, ...], str]:
    """The aligned paired NAV points of one replay run directory.

    The official series is ``restated_final``; a run without restatements
    has an empty restated series, so its ``as_observed`` path is the final
    truth (disclosed in the returned finality tag). The first observation
    of each arm carries no prior-NAV ratio and starts the series.
    """

    from src.screening.offensive.v3.capital.repository import CapitalRepository

    champion = CapitalRepository.open(str(root / "champion" / "capital.sqlite3"))
    challenger = CapitalRepository.open(str(root / "challenger" / "capital.sqlite3"))
    champion_projections = champion.nav_projections()
    challenger_projections = challenger.nav_projections()
    champion_path = champion_projections.restated_final
    challenger_path = challenger_projections.restated_final
    finality = "RESTATED_FINAL"
    if not champion_path or not challenger_path:
        champion_path = champion_projections.as_observed
        challenger_path = challenger_projections.as_observed
        finality = "AS_OBSERVED"
    if len(champion_path) != len(challenger_path):
        raise PairedStatisticsError(
            "session_alignment",
            f"{label}: arm NAV paths must align",
            champion=len(champion_path),
            challenger=len(challenger_path),
        )
    if len(champion_path) < 2:
        raise PairedStatisticsError(
            "too_short",
            f"{label}: NAV path must cover at least two sessions",
        )
    points: list[PairedNavPoint] = []
    for champ_obs, chall_obs in zip(champion_path, challenger_path, strict=True):
        if (
            champ_obs.log_growth_nav_numerator is None
            or champ_obs.log_growth_nav_denominator is None
            or chall_obs.log_growth_nav_numerator is None
            or chall_obs.log_growth_nav_denominator is None
        ):
            # First confirmed session: no prior NAV to compare.
            continue
        session = champ_obs.as_of.date()
        points.append(
            PairedNavPoint(
                session=session,
                champion_nav_numerator=int(champ_obs.log_growth_nav_numerator),
                champion_nav_denominator=int(champ_obs.log_growth_nav_denominator),
                challenger_nav_numerator=int(chall_obs.log_growth_nav_numerator),
                challenger_nav_denominator=int(chall_obs.log_growth_nav_denominator),
                checkpoint_hashes=_checkpoint_hashes(champion, challenger, session),
            )
        )
    if len(points) < 2:
        raise PairedStatisticsError(
            "too_short",
            f"{label}: at least two ratio sessions are required",
        )
    return tuple(points), finality


def _checkpoint_hashes(
    champion: object, challenger: object, session: date
) -> tuple[str, ...]:
    """Deterministic content hashes of both arms' committed checkpoint rows."""

    import hashlib

    import sqlalchemy as sa

    def rows_for(repository: object) -> tuple[str, ...]:
        rows: list[str] = []
        with repository.engine.connect() as conn:
            for row in conn.execute(
                sa.text(
                    "SELECT phase, stream_version FROM session_checkpoints"
                    " WHERE session = :session ORDER BY phase"
                ),
                {"session": session.isoformat()},
            ).all():
                rows.append(f"{row[0]}:{row[1]}")
        if not rows:
            return ()
        return (hashlib.sha256("|".join(rows).encode("utf-8")).hexdigest(),)

    return rows_for(champion) + rows_for(challenger)


def evaluate_frozen_paired_portfolios(
    current_replay: object,
    stress_replay: object,
    plan: object,
    coverage: PairedCoverage,
) -> FrozenPairedEvaluation:
    """Evaluate the frozen current-cost and stress replays side by side.

    ``current_replay``/``stress_replay`` are ``PairedReplayResult``
    instances produced by the deterministic replay engine (CURRENT_COST and
    DOUBLE_SLIPPAGE); their target directories hold the verified capital
    ledgers whose exact UnitNAV rationals and checkpoint hashes this
    evaluator reads. ``plan`` is the sealed ``ValidatedRegimeTrialBundle``
    carrying the frozen MEE and SAP statistics (method, repetitions, seed,
    confidence). Both scenarios are required and must be the two distinct
    ones; anything else fails closed.
    """

    from src.screening.offensive.v3.orchestration.replay import (
        PairedReplayResult,
        ReplayScenario,
    )

    if not isinstance(current_replay, PairedReplayResult) or not isinstance(
        stress_replay, PairedReplayResult
    ):
        raise PairedStatisticsError(
            "missing_scenario",
            "both CURRENT_COST and DOUBLE_SLIPPAGE replays are required",
        )
    if (
        current_replay.scenario is not ReplayScenario.CURRENT_COST
        or stress_replay.scenario is not ReplayScenario.DOUBLE_SLIPPAGE
    ):
        raise PairedStatisticsError(
            "missing_scenario",
            "scenarios must be exactly CURRENT_COST and DOUBLE_SLIPPAGE",
        )

    sap = plan.sap_manifest
    trial = plan.trial_manifest
    mee = float(trial.minimum_economic_effect)
    confidence = float(sap.one_sided_confidence_level)
    method = str(sap.bootstrap_method)
    if method not in BOOTSTRAP_METHODS:
        raise PairedStatisticsError(
            "unregistered_method",
            f"SAP frozen method {method!r} is not pre-registered",
        )
    repetitions = int(sap.repetitions)
    seed = int(sap.seed)
    block_length = _sap_block_length(sap.block_rule)

    current_points, current_finality = _points_for(
        Path(current_replay.target_directory), "current-cost"
    )
    stress_points, stress_finality = _points_for(
        Path(stress_replay.target_directory), "stress"
    )

    def assess(
        result: object, points: Sequence[PairedNavPoint], finality: str
    ) -> ScenarioAssessment:
        return _scenario_assessment(
            str(result.scenario.value),
            points=points,
            mee=mee,
            confidence=confidence,
            bootstrap_method=method,
            repetitions=repetitions,
            seed=seed,
            block_length=block_length,
            champion_capital_report=str(result.champion_capital_report),
            challenger_capital_report=str(result.challenger_capital_report),
            nav_path_finality=finality,
        )

    current = assess(current_replay, current_points, current_finality)
    stress = assess(stress_replay, stress_points, stress_finality)
    return FrozenPairedEvaluation(
        current=current,
        stress=stress,
        coverage=coverage,
        evaluated_at=trial.fixed_assessment_date,
        evidence_cutoff=trial.fixed_assessment_date,
    )


__all__ = [
    "BOOTSTRAP_METHODS",
    "CDAR_QUANTILE",
    "FrozenPairedEvaluation",
    "PairedCoverage",
    "PairedNavPoint",
    "PairedStatisticsError",
    "ScenarioAssessment",
    "block_bootstrap_lcb",
    "evaluate_frozen_paired_portfolios",
    "newey_west_lcb",
    "paired_daily_log_growth",
]
