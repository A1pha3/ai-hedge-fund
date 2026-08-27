"""Plan Task 13 RED: frozen paired evaluator over exact UnitNAV rationals.

The evaluator aligns the two verified restated-final UnitNAV checkpoint
paths session by session (every non-cancelled expected market day — cash,
no-signal, blocked, equal and disagreement days all stay in the series) and
computes Challenger-minus-Champion daily log growth from the exact integer
``nav / prior_nav`` rationals. Inference is conservative and pre-registered:
block bootstrap (moving | stationary | circular only, frozen
repetitions/seed/confidence from the SAP), HAC and chronological-fold
lower bounds all come from the complete continuous-path deltas, and the
gate is ``lcb >= minimum_economic_effect`` (threshold equality passes).
Tail/state metrics come from each continuous replay, never from stitched
blocks. Samples too short for any required method are ``NOT_ELIGIBLE`` and
are never silently downgraded to an IID t-test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts.governance import (
    StatisticalAnalysisPlan,
)
from src.screening.offensive.v3.contracts.trial import TrialArm


from tests.offensive.v3.orchestration._batch_authority_rigs import (
    FENCE_REASON,
)
_REQUIRES_SHADOW_CAPITAL_FENCE = pytest.mark.skip(
    reason=FENCE_REASON,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
EPOCH = datetime(2026, 8, 5, 0, 0, tzinfo=UTC)
TRIAL_ID = "trial-regime-001"
PROGRAM = "research.btst.regime"
#: Exact rationals: point t carries nav_t / nav_{t-1} in lowest terms.
#: Champion drifts 0.10% per session, challenger 0.20% -> d_t = +0.10%.
_CHAMPION_RATIO = (1_000, 999)  # log(1000/999) ~ +0.0010005
_CHALLENGER_RATIO = (1_001, 999)  # log(1001/999) ~ +0.0020005


@dataclass(frozen=True)
class _Point:
    """Test-side duplicate of the PairedNavPoint shape (RED: no import)."""

    session: date
    champion_nav_numerator: int
    champion_nav_denominator: int
    challenger_nav_numerator: int
    challenger_nav_denominator: int
    checkpoint_hashes: tuple[str, ...] = ()

    def swap_arms(self) -> "_Point":
        return _Point(
            session=self.session,
            champion_nav_numerator=self.challenger_nav_numerator,
            champion_nav_denominator=self.challenger_nav_denominator,
            challenger_nav_numerator=self.champion_nav_numerator,
            challenger_nav_denominator=self.champion_nav_denominator,
            checkpoint_hashes=self.checkpoint_hashes,
        )


def _session(day: int) -> date:
    return date(2026, 8, day)


def _points(
    count: int = 5,
    *,
    champion: tuple[int, int] = _CHAMPION_RATIO,
    challenger: tuple[int, int] = _CHALLENGER_RATIO,
    start_day: int = 3,
) -> tuple[_Point, ...]:
    return tuple(
        _Point(
            session=_session(start_day + index),
            champion_nav_numerator=champion[0],
            champion_nav_denominator=champion[1],
            challenger_nav_numerator=challenger[0],
            challenger_nav_denominator=challenger[1],
            checkpoint_hashes=(
                f"champ-checkpoint-{index:02d}",
                f"chall-checkpoint-{index:02d}",
            ),
        )
        for index in range(count)
    )


def _sap(
    *,
    bootstrap_method: str = "moving",
    repetitions: int = 200,
    seed: int = 7,
    confidence: Decimal = Decimal("0.95"),
    block_rule: str = "10/20/40",
) -> StatisticalAnalysisPlan:
    from src.screening.offensive.v3.contracts import ExecutionMode
    from src.screening.offensive.v3.contracts.governance import PrimaryMetric

    return StatisticalAnalysisPlan(
        sap_id=TRIAL_ID,
        trial_manifest_hash="a" * 64,
        research_program_id=PROGRAM,
        economic_lineage_id="lineage-1",
        primary_metric=PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        baseline_portfolio_policy_fingerprint="b" * 64,
        target_portfolio_policy_fingerprint="c" * 64,
        execution_mode=ExecutionMode.DAILY_BAR_PROXY,
        one_sided_confidence_level=confidence,
        bootstrap_method=bootstrap_method,
        repetitions=repetitions,
        seed=seed,
        block_rule=block_rule,
        multiplicity_policy="program-global",
        alpha_or_evalue_budget_consumption_id="budget-001",
        issued_at=EPOCH - timedelta(days=1),
        sealed_at=EPOCH - timedelta(days=1),
        enrollment_start=EPOCH,
        expires_at=EPOCH + timedelta(days=120),
        issuer_id="governance.service",
        issuer_capability="governance.sap.v1",
        schema_major=2,
    )


# =============================================================================
# Step 1: sign/alignment of the paired daily log growth
# =============================================================================


def test_delta_sign_is_challenger_minus_champion() -> None:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        paired_daily_log_growth,
    )

    points = _points()
    delta = paired_daily_log_growth(points)
    swapped = paired_daily_log_growth(
        tuple(point.swap_arms() for point in points)
    )
    # A target-only gain is positive and swapping arms negates every d_t
    # and the mean exactly.
    assert all(value > 0 for value in delta)
    assert swapped == tuple(-value for value in delta)
    assert sum(delta) / len(delta) > 0


def test_delta_values_derive_from_exact_rationals() -> None:
    from math import log

    from src.screening.offensive.v3.evidence.paired_statistics import (
        paired_daily_log_growth,
    )

    points = _points(count=3)
    delta = paired_daily_log_growth(points)
    expected = log(1_001 / 999) - log(1_000 / 999)
    assert len(delta) == 3
    for value in delta:
        assert value == pytest.approx(expected, abs=1e-12)


def test_growth_rejects_missing_duplicate_reordered_or_nonpositive_points() -> None:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        PairedStatisticsError,
        paired_daily_log_growth,
    )

    # Missing a session in the middle of the fixed ladder.
    with pytest.raises(PairedStatisticsError, match="session_alignment"):
        paired_daily_log_growth(
            (_Point(_session(3), 1, 1, 1, 1), _Point(_session(5), 1, 1, 1, 1))
        )
    # Duplicate session.
    with pytest.raises(PairedStatisticsError, match="session_alignment"):
        paired_daily_log_growth(
            (_Point(_session(3), 1, 1, 1, 1), _Point(_session(3), 1, 1, 1, 1))
        )
    # Reordered sessions (not strictly increasing).
    with pytest.raises(PairedStatisticsError, match="session_alignment"):
        paired_daily_log_growth(
            (_Point(_session(5), 1, 1, 1, 1), _Point(_session(3), 1, 1, 1, 1))
        )
    # Non-positive rational (zero NAV) must fail closed.
    with pytest.raises(PairedStatisticsError, match="non_positive"):
        paired_daily_log_growth(
            (_Point(_session(3), 0, 1, 1, 1), _Point(_session(4), 1, 1, 1, 1))
        )
    # A single point has no growth step.
    with pytest.raises(PairedStatisticsError, match="too_short"):
        paired_daily_log_growth((_Point(_session(3), 1, 1, 1, 1),))


def test_delta_rejects_mixed_scenario_or_mismatched_sessions() -> None:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        PairedStatisticsError,
        paired_daily_log_growth,
    )

    # A gap in the fixed ladder (08-03, 08-04) is a missing-session
    # alignment failure.
    with pytest.raises(PairedStatisticsError, match="session_alignment"):
        paired_daily_log_growth(
            (
                _Point(_session(3), 1, 1, 1, 1),
                _Point(_session(4), 1, 1, 1, 1),
                _Point(_session(6), 1, 1, 1, 1),  # 08-05 is a trading day
            )
        )


# =============================================================================
# Step 2: conservative frozen inference
# =============================================================================


def test_block_bootstrap_supports_only_registered_methods() -> None:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        PairedStatisticsError,
        block_bootstrap_lcb,
    )

    values = tuple(0.001 + 0.0005 * (index % 3) for index in range(30))
    for method in ("moving", "stationary", "circular"):
        first = block_bootstrap_lcb(
            values,
            method=method,
            block_length=5,
            repetitions=100,
            seed=11,
            confidence=0.95,
        )
        second = block_bootstrap_lcb(
            values,
            method=method,
            block_length=5,
            repetitions=100,
            seed=11,
            confidence=0.95,
        )
        assert first == pytest.approx(second)  # deterministic under a seed
        assert first < sum(values) / len(values)
    with pytest.raises(PairedStatisticsError, match="unregistered_method"):
        block_bootstrap_lcb(
            values,
            method="wild",
            block_length=5,
            repetitions=100,
            seed=11,
            confidence=0.95,
        )


def test_block_bootstrap_sensitivity_and_seed_reproducibility() -> None:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        block_bootstrap_lcb,
    )

    # The 10/20/40 sensitivity grid: each registered block length yields
    # its own conservative bound (never above the sample mean), and the
    # grid spans a spread of values on this autocorrelated series.
    values = tuple(0.001 + 0.001 * (index % 4) for index in range(80))
    mean = sum(values) / len(values)
    bounds = {}
    for block_length in (10, 20, 40):
        bounds[block_length] = block_bootstrap_lcb(
            values, method="moving", block_length=block_length, repetitions=150, seed=5, confidence=0.95
        )
        assert bounds[block_length] <= mean + 1e-12
    assert len(set(bounds.values())) >= 2  # the grid is not degenerate
    # A different seed produces a different resampling path (verified on a
    # non-degenerate series; the exact-zero series above saturates the
    # percentile at the mean regardless of the seed).
    noisy = tuple(
        0.001 + 0.001 * (index % 4) + 0.0003 * (index % 7) for index in range(80)
    )
    first = block_bootstrap_lcb(
        noisy, method="moving", block_length=20, repetitions=150, seed=5, confidence=0.95
    )
    other = block_bootstrap_lcb(
        noisy, method="moving", block_length=20, repetitions=150, seed=6, confidence=0.95
    )
    assert first != other


def test_block_bootstrap_requires_complete_path() -> None:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        PairedStatisticsError,
        block_bootstrap_lcb,
    )

    with pytest.raises(PairedStatisticsError, match="too_short"):
        block_bootstrap_lcb(
            (0.001,) * 2,
            method="moving",
            block_length=5,
            repetitions=100,
            seed=1,
            confidence=0.95,
        )


def test_newey_west_lcb_is_deterministic_and_conservative() -> None:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        newey_west_lcb,
    )

    # Positive autocorrelation (slow 12-day cycle): the HAC standard error
    # is larger than the IID one, so the HAC bound is below the IID t bound.
    values = tuple(0.001 + 0.001 * (index % 12) for index in range(48))
    first = newey_west_lcb(values, lag=4, confidence=0.95)
    second = newey_west_lcb(values, lag=4, confidence=0.95)
    assert first == pytest.approx(second)
    from src.screening.offensive.v3.evidence.statistics import (
        one_sided_lower_bound,
    )

    iid_bound = one_sided_lower_bound(values)
    assert first <= iid_bound + 1e-12


# =============================================================================
# Step 3: eligibility + frozen evaluation (real replay ledgers)
# =============================================================================

# These tests drive the official paired trial world (``rig.run_official``),
# rewritten live against the capital-checkpoint-v2 API in R44. The fixture
# is ``test_forward_trial_replay._Rig``; see that module's disposition note
# for the batch-authority scope boundary (manual facts, no store-owned
# session-batch seal in this world).


@pytest.fixture()
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> object:
    """The real paired-trial world: official drive + replay engine.

    Mirrors the replay test's rig fixture (BTST detector pinned to a hit,
    producer clock re-anchored before the first signal day) so the
    evaluator consumes genuinely replayed capital ledgers.
    """

    from src.screening.offensive.setups.btst_breakout import (
        BtstBreakoutSetup,
    )
    from tests.offensive.v3.orchestration.test_forward_trial_replay import (
        _Rig,
    )
    from tests.offensive.v3.services.test_btst_producer_api import (
        _hit_result,
    )

    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: _hit_result(ticker),
    )
    import tests.offensive.v3.services.test_btst_producer_api as producer_test

    monkeypatch.setattr(
        producer_test,
        "NOW",
        datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
    )
    return _Rig(tmp_path)


def _run_pair(rig: object, tmp_path: Path) -> tuple[object, object]:
    """Run the official timeline once, then replay both scenarios."""

    from src.screening.offensive.v3.orchestration.replay import (
        ReplayScenario,
    )

    rig.run_official()
    current = rig.replayer.replay(
        rig.replay_input(), ReplayScenario.CURRENT_COST, tmp_path / "current"
    )
    stress = rig.replayer.replay(
        rig.replay_input(), ReplayScenario.DOUBLE_SLIPPAGE, tmp_path / "stress"
    )
    return current, stress














@_REQUIRES_SHADOW_CAPITAL_FENCE
def test_evaluation_requires_both_scenarios_and_rejects_mismatch(
    rig: object, tmp_path: Path
) -> None:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        PairedStatisticsError,
    )

    from src.screening.offensive.v3.orchestration.replay import (
        ReplayScenario,
    )

    current, stress = _run_pair(rig, tmp_path)
    plan = _plan()
    coverage = _coverage()
    # A full current+stress evaluation over real ledgers succeeds.
    result = _evaluate(current, stress, plan, coverage)
    assert result.current.observation_count > 0
    assert result.stress.observation_count > 0
    # Missing the stress replay fails closed.
    with pytest.raises(PairedStatisticsError, match="missing_scenario"):
        _evaluate(current, None, plan, coverage)
    # Mixed scenarios (two currents) fail closed.
    with pytest.raises(PairedStatisticsError, match="missing_scenario"):
        _evaluate(current, _replay_result(ReplayScenario.CURRENT_COST), plan, coverage)

@_REQUIRES_SHADOW_CAPITAL_FENCE
def test_incremental_gate_is_lcb_greater_or_equal_mee(
    rig: object, tmp_path: Path
) -> None:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        ScenarioAssessment,
    )

    current, stress = _run_pair(rig, tmp_path)
    # The synthetic trial drives both arms through identical economics
    # (same entries, same marks), so the paired deltas are exactly zero
    # and the LCB equals the mean at zero. A zero-delta trial honestly
    # fails any positive MEE (``lcb >= mee``); the ``>=`` equality boundary
    # is exercised by the unit assessment below.
    boundary_plan = _plan(mee=Decimal("0.000001"))
    result = _evaluate(current, stress, boundary_plan, _coverage())
    assert result.current.incremental_growth_mean == pytest.approx(0.0)
    assert result.current.passes_growth_gate() is False
    assert result.stress.passes_growth_gate() is False
    # Threshold equality passes: an LCB exactly at the MEE is eligible.
    boundary = ScenarioAssessment(
        scenario="CURRENT_COST",
        champion_absolute_growth=0.001,
        challenger_absolute_growth=0.001,
        incremental_growth_mean=0.001,
        incremental_growth_lcb=0.001,
        minimum_economic_effect=0.001,
        lcb_above_mee=True,
        maximum_drawdown=0.0,
        conditional_drawdown_at_risk=0.0,
        observation_count=10,
        conservation_passed=True,
        rebuild_passed=True,
        lcb_method="block-bootstrap:moving:10",
        nav_path_finality="AS_OBSERVED",
    )
    assert boundary.passes_growth_gate() is True

@_REQUIRES_SHADOW_CAPITAL_FENCE
def test_absolute_growth_uses_sealed_benchmark_and_each_continuous_replay(
    rig: object, tmp_path: Path
) -> None:
    current, stress = _run_pair(rig, tmp_path)
    plan = _plan(mee=Decimal("0.000001"))
    result = _evaluate(current, stress, plan, _coverage())
    # Absolute growth is per-arm, per-scenario, from each continuous path.
    assert result.current.champion_absolute_growth is not None
    assert result.current.challenger_absolute_growth is not None
    assert result.stress.champion_absolute_growth is not None
    assert result.stress.challenger_absolute_growth is not None
    # Both scenarios share the full non-cancelled ladder (13 sessions ->
    # at least 12 growth steps; the first confirmed session carries no
    # prior-NAV ratio).
    assert result.current.observation_count == result.stress.observation_count
    assert result.current.observation_count >= 12

@_REQUIRES_SHADOW_CAPITAL_FENCE
def test_tail_metrics_come_from_continuous_replay_not_stitched_blocks(
    rig: object, tmp_path: Path
) -> None:
    current, stress = _run_pair(rig, tmp_path)
    plan = _plan(mee=Decimal("0.000001"))
    result = _evaluate(current, stress, plan, _coverage())
    # MDD/CDaR are computed from each continuous replay path (the exact
    # UnitNAV series), never from resampled blocks.
    for scenario in (result.current, result.stress):
        assert 0.0 <= scenario.maximum_drawdown <= 1.0
        assert 0.0 <= scenario.conditional_drawdown_at_risk <= 1.0
    # The double-slippage scenario is a full alternative replay: its NAV
    # path differs from the current-cost one (never a return drag).
    assert result.current.maximum_drawdown != pytest.approx(
        result.stress.maximum_drawdown
    )
    assert result.stress.maximum_drawdown > result.current.maximum_drawdown

@_REQUIRES_SHADOW_CAPITAL_FENCE
def test_eligibility_gates_are_distinct_booleans(
    rig: object, tmp_path: Path
) -> None:
    current, stress = _run_pair(rig, tmp_path)
    plan = _plan(mee=Decimal("0.000001"))
    result = _evaluate(current, stress, plan, _coverage())
    # Every §13.5 gate is its own boolean; none may be merged.
    assert result.coverage.mature_outcomes_sufficient is True
    assert result.coverage.decision_days_sufficient is True
    assert result.coverage.ess_sufficient is True
    assert result.coverage.tickers_sufficient is True
    assert result.coverage.months_sufficient is True
    assert result.coverage.adverse_window_complete is True
    assert result.current.conservation_passed is True
    assert result.current.rebuild_passed is True
    assert result.stress.conservation_passed is True
    assert result.stress.rebuild_passed is True
    assert result.itt_finality_complete is True
    assert result.unresolved_breach_count == 0
    # The zero-delta synthetic trial honestly fails the positive MEE gate,
    # and the eligibility flag follows every gate conjunctively.
    assert result.eligible is False

@_REQUIRES_SHADOW_CAPITAL_FENCE
def test_not_eligible_when_any_gate_fails(
    rig: object, tmp_path: Path
) -> None:
    current, stress = _run_pair(rig, tmp_path)
    plan = _plan(mee=Decimal("0.000001"))
    # A too-short coverage declares the trial NOT_ELIGIBLE.
    short = _coverage(
        mature_outcomes=10,
        decision_days=5,
        ess=5.0,
        tickers=3,
        months=1,
    )
    result = _evaluate(current, stress, plan, short)
    assert result.eligible is False
    assert result.coverage.mature_outcomes_sufficient is False
    assert result.coverage.decision_days_sufficient is False
    # A broken conservation report also fails the gate.
    from dataclasses import replace

    broken = replace(current, champion_capital_report="failed:False")
    result = _evaluate(broken, stress, plan, _coverage())
    assert result.eligible is False
    assert result.current.conservation_passed is False


def test_samples_too_short_for_required_method_are_not_eligible() -> None:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        PairedStatisticsError,
        block_bootstrap_lcb,
    )

    # One block cannot even be formed from two observations.
    with pytest.raises(PairedStatisticsError, match="too_short"):
        block_bootstrap_lcb(
            (0.001, 0.001),
            method="circular",
            block_length=3,
            repetitions=100,
            seed=1,
            confidence=0.95,
        )


# =============================================================================
# helpers: replay results, plan, coverage (test-side shapes; RED)
# =============================================================================


def _replay_result(
    scenario: str,
    *,
    dir_name: str | None = None,
    report: str = "ok:True",
):
    from src.screening.offensive.v3.orchestration.replay import (
        PairedReplayResult,
    )

    return PairedReplayResult(
        scenario=scenario,
        target_directory=f"/tmp/{dir_name or scenario.lower()}",
        sessions_replayed=1,
        champion_capital_report=report,
        challenger_capital_report=report,
        champion_nav_path_hash="a" * 64,
        challenger_nav_path_hash="b" * 64,
        decision_root="c" * 64,
        lifecycle_root="d" * 64,
    )


def _plan(mee: Decimal = Decimal("0.001")) -> object:
    """A minimal frozen plan object carrying the SAP statistics fields."""

    import json

    from src.screening.offensive.v3.governance.regime_trial import (
        ValidatedRegimeTrialBundle,
    )
    from tests.offensive.v3.governance.test_regime_trial_governance import (
        _trial_policy,
    )
    from src.screening.offensive.v3.contracts.regime import (
        RegimeAdmissionMode,
    )

    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    return ValidatedRegimeTrialBundle(
        champion_policy=baseline,
        challenger_policy=target,
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=_trial_manifest(mee),
        sap_manifest=_sap(),
        admission_delta=(),
    )


def _trial_manifest(mee: Decimal) -> object:
    from src.screening.offensive.v3.contracts import ExecutionMode
    from src.screening.offensive.v3.contracts.governance import (
        PrimaryMetric,
        TrialManifest,
    )

    return TrialManifest(
        family_id="btst.limit-up-breakout",
        economic_lineage_id="lineage-1",
        research_program_id=PROGRAM,
        trial_id=TRIAL_ID,
        baseline_portfolio_policy_fingerprint="b" * 64,
        target_portfolio_policy_fingerprint="c" * 64,
        trust_bundle_hash="d" * 64,
        registry_epoch=1,
        baseline_policy_activation_hash="e" * 64,
        target_policy_snapshot_registration_hash="f" * 64,
        attempt_ledger_checkpoint_before_trial="7" * 64,
        attempt_budget_reservation_id="attempt-regime-001",
        statistical_governance_policy_version="stat-gov.v1",
        champion_behavior_fingerprint="8" * 64,
        challenger_behavior_fingerprint="9" * 64,
        primary_metric=PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        minimum_economic_effect=mee,
        weight_selection_rule="fixed-50-50",
        trial_manifest_sealed_at=EPOCH - timedelta(days=1),
        enrollment_start=EPOCH,
        enrollment_end=EPOCH + timedelta(days=30),
        followup_finality_date=EPOCH + timedelta(days=60),
        fixed_assessment_date=EPOCH + timedelta(days=90),
        execution_version="t0-close-t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        execution_mode=ExecutionMode.DAILY_BAR_PROXY,
        benchmark_definition="csi300-total-return",
        capacity_policy="capacity.v1",
        tail_risk_policy="tail.v1",
        estimator="block-bootstrap",
        one_sided_confidence_level=Decimal("0.95"),
        bootstrap_method="moving",
        bootstrap_repetitions=200,
        bootstrap_seed=7,
        block_rule="10/20/40",
        ess_definition="kish",
        missing_censoring_itt_rule="itt",
        fold_boundaries=("2026-09-01", "2026-10-01"),
        purge_embargo="purge-5d",
        promotion_boolean_expression="lcb >= mee",
        multiplicity_policy="program-global",
        broker_experiment_design=None,
        canonical_outcome_counting_rule="plan-line-contract",
        stage_loss_measurement_basis="stage-budget",
        issuer_id="governance.service",
        issuer_capability="governance.trial.manifest.v1",
        issued_at=EPOCH - timedelta(days=1),
        expires_at=EPOCH + timedelta(days=120),
        schema_major=2,
    )


def _coverage(
    mature_outcomes: int = 150,
    decision_days: int = 60,
    ess: float = 60.0,
    tickers: int = 80,
    months: int = 12,
) -> object:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        PairedCoverage,
    )

    return PairedCoverage(
        mature_outcomes=mature_outcomes,
        decision_days=decision_days,
        effective_sample_size=ess,
        tickers=tickers,
        months=months,
        adverse_window_complete=True,
        itt_finality_complete=True,
        consumption_and_multiplicity_complete=True,
        unresolved_breach_count=0,
    )


def _evaluate(current, stress, plan, coverage) -> object:
    from src.screening.offensive.v3.evidence.paired_statistics import (
        evaluate_frozen_paired_portfolios,
    )

    return evaluate_frozen_paired_portfolios(current, stress, plan, coverage)
