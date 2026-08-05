"""Plan 03 Task 2: trial/SAP sealing, attempt reservation, target policy."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.governance import (
    PrimaryMetric,
    StatisticalAnalysisPlan,
    TrialManifest,
)
from src.screening.offensive.v3.governance.repository import (
    GovernanceRepository,
    GovernanceStoreError,
    TrialSealRequest,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
HASH = "a" * 64
TARGET_HASH = "b" * 64
PROGRAM = "prog-1"
LINEAGE = "eline-1"


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


def _trial_manifest(**overrides) -> TrialManifest:
    values = {
        "family_id": "btst.limit-up-breakout",
        "economic_lineage_id": LINEAGE,
        "research_program_id": PROGRAM,
        "trial_id": "trial-001",
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": TARGET_HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 1,
        "baseline_policy_activation_hash": HASH,
        "target_policy_snapshot_registration_hash": TARGET_HASH,
        "attempt_ledger_checkpoint_before_trial": HASH,
        "attempt_budget_reservation_id": "attempt-001",
        "statistical_governance_policy_version": "stat-gov.v1",
        "champion_behavior_fingerprint": HASH,
        "challenger_behavior_fingerprint": "c" * 64,
        "primary_metric": PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        "minimum_economic_effect": Decimal("0.001"),
        "weight_selection_rule": "fixed-50-50",
        "trial_manifest_sealed_at": NOW,
        "enrollment_start": NOW + timedelta(days=1),
        "enrollment_end": NOW + timedelta(days=30),
        "followup_finality_date": NOW + timedelta(days=60),
        "fixed_assessment_date": NOW + timedelta(days=90),
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "execution_mode": ExecutionMode.DAILY_BAR_PROXY,
        "benchmark_definition": "csi300-total-return",
        "capacity_policy": "capacity.v1",
        "tail_risk_policy": "tail.v1",
        "estimator": "wild-bootstrap",
        "one_sided_confidence_level": Decimal("0.95"),
        "bootstrap_method": "wild",
        "bootstrap_repetitions": 10_000,
        "bootstrap_seed": 42,
        "block_rule": "monthly",
        "ess_definition": "kish",
        "missing_censoring_itt_rule": "itt",
        "fold_boundaries": ("2026-09-01", "2026-10-01"),
        "purge_embargo": "purge-5d",
        "promotion_boolean_expression": "lcb > mee",
        "multiplicity_policy": "program-global",
        "broker_experiment_design": None,
        "canonical_outcome_counting_rule": "plan-line-contract",
        "stage_loss_measurement_basis": "stage-budget",
        "issuer_id": "governance.service",
        "issuer_capability": "governance.trial.manifest.v1",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(days=120),
        "schema_major": 2,
    }
    values.update(overrides)
    return TrialManifest(**values)


def _sap_manifest(trial: TrialManifest, **overrides) -> StatisticalAnalysisPlan:
    values = {
        "sap_id": trial.trial_id,
        "trial_manifest_hash": trial.artifact_hash(),
        "research_program_id": trial.research_program_id,
        "economic_lineage_id": trial.economic_lineage_id,
        "primary_metric": PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        "baseline_portfolio_policy_fingerprint": (
            trial.baseline_portfolio_policy_fingerprint
        ),
        "target_portfolio_policy_fingerprint": (
            trial.target_portfolio_policy_fingerprint
        ),
        "execution_mode": trial.execution_mode,
        "one_sided_confidence_level": Decimal("0.95"),
        "bootstrap_method": "wild",
        "repetitions": 10_000,
        "seed": 42,
        "block_rule": "monthly",
        "multiplicity_policy": "program-global",
        "alpha_or_evalue_budget_consumption_id": "budget-001",
        "issued_at": NOW,
        "sealed_at": NOW,
        "enrollment_start": trial.enrollment_start,
        "expires_at": NOW + timedelta(days=120),
        "issuer_id": "governance.service",
        "issuer_capability": "governance.sap.v1",
        "schema_major": 2,
    }
    values.update(overrides)
    return StatisticalAnalysisPlan(**values)


@pytest.fixture()
def repository(tmp_path: Path) -> GovernanceRepository:
    return GovernanceRepository(
        database_path=str(tmp_path / "governance.sqlite3"),
        clock=_Clock(NOW),
    )


def _seal_request(repository, **overrides) -> TrialSealRequest:
    trial = overrides.pop("trial_manifest", None) or _trial_manifest()
    sap = overrides.pop("sap_manifest", None) or _sap_manifest(trial)
    values = {
        "attempt_budget_reservation_id": trial.attempt_budget_reservation_id,
        "stage_id": "stage-1",
        "role": "champion",
        "trial_manifest": trial,
        "sap_manifest": sap,
        "policy_snapshot_json": '{"policy": "target"}',
        "policy_fingerprint": trial.target_portfolio_policy_fingerprint,
        "target_policy_snapshot_registration_hash": (
            trial.target_policy_snapshot_registration_hash
        ),
        "expected_signal_cutoff": NOW + timedelta(days=1),
    }
    values.update(overrides)
    return TrialSealRequest(**values)


def test_seal_commits_attempt_trial_and_target_atomically(
    repository: GovernanceRepository,
) -> None:
    receipt = repository.reserve_attempt_and_seal_trial(_seal_request(repository))
    assert receipt.trial_id == "trial-001"
    assert repository.attempt_reserved("attempt-001")
    trial_row = repository.sealed_trial("trial-001")
    assert trial_row["role"] == "champion"
    assert trial_row["research_program_id"] == PROGRAM
    assert trial_row["economic_lineage_id"] == LINEAGE
    target = repository.target_policy(TARGET_HASH)
    # The registered target policy is explicitly NON-executable.
    assert target["executable"] == 0


def test_seal_requires_sealed_before_signal_cutoff(
    repository: GovernanceRepository,
) -> None:
    request = _seal_request(
        repository, expected_signal_cutoff=NOW - timedelta(seconds=1)
    )
    with pytest.raises(GovernanceStoreError) as excinfo:
        repository.reserve_attempt_and_seal_trial(request)
    assert excinfo.value.code == "seal_after_signal_cutoff"
    assert not repository.attempt_reserved("attempt-001")


def test_second_champion_for_same_lineage_is_rejected_and_rolls_back(
    repository: GovernanceRepository,
) -> None:
    repository.reserve_attempt_and_seal_trial(_seal_request(repository))
    other_trial = _trial_manifest(
        trial_id="trial-002",
        attempt_budget_reservation_id="attempt-002",
    )
    request = _seal_request(
        repository,
        trial_manifest=other_trial,
        sap_manifest=_sap_manifest(other_trial),
    )
    with pytest.raises(GovernanceStoreError) as excinfo:
        repository.reserve_attempt_and_seal_trial(request)
    assert excinfo.value.code == "trial_seal_conflict"
    # Atomic rollback: the failed seal reserved nothing.
    assert not repository.attempt_reserved("attempt-002")
    with pytest.raises(GovernanceStoreError):
        repository.sealed_trial("trial-002")


def test_challenger_role_is_separate_from_champion(
    repository: GovernanceRepository,
) -> None:
    repository.reserve_attempt_and_seal_trial(_seal_request(repository))
    other_trial = _trial_manifest(
        trial_id="trial-002",
        attempt_budget_reservation_id="attempt-002",
        target_policy_snapshot_registration_hash="d" * 64,
    )
    request = _seal_request(
        repository,
        trial_manifest=other_trial,
        sap_manifest=_sap_manifest(other_trial),
        role="challenger",
        target_policy_snapshot_registration_hash="d" * 64,
    )
    receipt = repository.reserve_attempt_and_seal_trial(request)
    assert receipt.trial_id == "trial-002"


def test_sap_must_bind_the_trial_manifest(
    repository: GovernanceRepository,
) -> None:
    trial = _trial_manifest()
    wrong_sap = _sap_manifest(trial, trial_manifest_hash="f" * 64)
    request = _seal_request(
        repository, trial_manifest=trial, sap_manifest=wrong_sap
    )
    with pytest.raises(GovernanceStoreError) as excinfo:
        repository.reserve_attempt_and_seal_trial(request)
    assert excinfo.value.code == "sap_trial_mismatch"


def test_sealed_trial_rows_are_immutable(
    repository: GovernanceRepository,
) -> None:
    repository.reserve_attempt_and_seal_trial(_seal_request(repository))
    import sqlalchemy as sa

    with pytest.raises(sa.exc.SQLAlchemyError):
        with repository._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE sealed_trials SET role = 'challenger'"
                    " WHERE trial_id = 'trial-001'"
                )
            )
    with pytest.raises(sa.exc.SQLAlchemyError):
        with repository._engine.begin() as conn:
            conn.execute(
                sa.text("DELETE FROM sealed_trials")
            )
