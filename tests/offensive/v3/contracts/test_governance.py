"""Adversarial Revision 2 Governance Control Plane contract tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from test_authorization import HASH, _envelope, _grant

UTC = timezone.utc
NOW = datetime(2026, 7, 19, 8, tzinfo=UTC)


def _governance():
    from src.screening.offensive.v3.contracts import governance

    return governance


def _trial(**overrides):
    from src.screening.offensive.v3.contracts.base import ExecutionMode
    from src.screening.offensive.v3.contracts.governance import PrimaryMetric

    payload = {
        "family_id": "btst-family",
        "economic_lineage_id": "btst-lineage",
        "research_program_id": "program-1",
        "trial_id": "trial-1",
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 2,
        "baseline_policy_activation_hash": HASH,
        "target_policy_snapshot_registration_hash": HASH,
        "attempt_ledger_checkpoint_before_trial": HASH,
        "attempt_budget_reservation_id": "attempt-1",
        "statistical_governance_policy_version": "gov-v1",
        "champion_behavior_fingerprint": HASH,
        "challenger_behavior_fingerprint": HASH,
        "primary_metric": PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        "minimum_economic_effect": Decimal("0.001"),
        "weight_selection_rule": "frozen",
        "trial_manifest_sealed_at": NOW,
        "enrollment_start": NOW + timedelta(days=1),
        "enrollment_end": NOW + timedelta(days=10),
        "followup_finality_date": NOW + timedelta(days=20),
        "fixed_assessment_date": NOW + timedelta(days=21),
        "execution_version": "t1-open",
        "cost_version": "cost-v1",
        "execution_mode": ExecutionMode.BROKER_CONFIRMED,
        "benchmark_definition": "cash",
        "capacity_policy": "cap-v1",
        "tail_risk_policy": "tail-v1",
        "estimator": "frozen",
        "one_sided_confidence_level": Decimal("0.95"),
        "bootstrap_method": "moving",
        "bootstrap_repetitions": 1000,
        "bootstrap_seed": 7,
        "block_rule": "max-40",
        "ess_definition": "decision-day",
        "missing_censoring_itt_rule": "include",
        "fold_boundaries": ("2026-Q3",),
        "purge_embargo": "t+10",
        "promotion_boolean_expression": "all_gates",
        "multiplicity_policy": "alpha-spending",
        "broker_experiment_design": "clustered",
        "canonical_outcome_counting_rule": "plan-line",
        "stage_loss_measurement_basis": "mark-to-market",
        "issuer_id": "governance",
        "issuer_capability": "governance.trial.manifest.v1",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(days=30),
        "schema_major": 2,
    }
    return payload | overrides


def _predecessor(**overrides):
    payload = {
        "predecessor_active_authorization_id": "previous-1",
        "predecessor_active_authorization_version": 1,
        "predecessor_active_authorization_hash": HASH,
        "predecessor_active_authorization_status_hash": HASH,
        "predecessor_target_policy_fingerprint": HASH,
        "predecessor_active_edge_grant_certificate_hashes": (HASH,),
    }
    return payload | overrides


def _exploration_controls(**overrides):
    payload = {
        "exploration_shared_stress_loss_budget_id": "exploration-loss-1",
        "exploration_shared_stress_loss_budget_cents": 100,
        "exploration_shared_stress_loss_consumed_cents": 0,
        "exploration_shared_stress_loss_version": 1,
        "exploration_one_shot_reservation_id": "one-shot-reservation",
        "exploration_one_shot_consumption_id": "one-shot-consumption",
        "exploration_trial_id": "explore-trial",
        "exploration_fixed_assessment_at": NOW + timedelta(days=10),
    }
    return payload | overrides


def _exploration_grant(**overrides):
    from src.screening.offensive.v3.contracts.governance import GrantKind

    payload = _grant(
        grant_id="explore",
        grant_kind=GrantKind.EXPLORATION,
        grant_certificate_hash="b" * 64,
        economic_lineage_id="explore-lineage",
        stage_id="explore-stage",
        stage_sample_reservation_id="explore-reservation",
        stage_loss_budget_id="exploration-loss-1",
        shared_exploration_loss_budget_id="exploration-loss-1",
        assessment_result_hash="c" * 64,
        attempt_ledger_checkpoint_hash="d" * 64,
        alpha_or_evalue_budget_consumption_id="explore-alpha",
        alpha_sample_consumption_id="explore-sample",
        trial_id="explore-trial",
    )
    return payload | overrides


def test_trust_activation_and_recovery_are_candidates_with_epochs_and_predecessors():
    g = _governance()
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    bundle = g.TrustBundle.model_validate(
        {
            "registry_epoch": 2,
            "predecessor_bundle_hash": HASH,
            "root_hash": HASH,
            "root_key_id": "root-1",
            "trusted_issuer_registry_hash": HASH,
            "issued_at": NOW,
            "expires_at": NOW + timedelta(days=1),
            "revoked_at": None,
            "issuer_id": "root",
            "issuer_capability": "root.trust.bundle.v1",
            "schema_major": 2,
        }
    )
    assert bundle.registry_epoch == 2
    with pytest.raises(ValidationError):
        g.TrustBundle.model_validate(bundle.model_dump() | {"registry_epoch": 0})
    activation = {
        "portfolio_id": "portfolio-1",
        "broker_account_id": "account-1",
        "broker_account_fingerprint": HASH,
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "policy_snapshot_hash": HASH,
        "predecessor_policy_activation_hash": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 2,
        "policy_epoch": 2,
        "authority_epoch": 2,
        "risk_epoch": 2,
        "effective_from": NOW,
        "expires_at": NOW + timedelta(days=1),
        "issuer_id": "governance",
        "issuer_capability": "governance.policy.activation.v1",
        "schema_major": 2,
    }
    assert g.PolicyActivation.model_validate(activation).portfolio_id == "portfolio-1"
    with pytest.raises(ValidationError):
        g.PolicyActivation.model_validate({"policy_version": 1})
    recovery = {
        "portfolio_id": "portfolio-1",
        "broker_account_id": "account-1",
        "broker_account_fingerprint": HASH,
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "predecessor_risk_epoch_hash": HASH,
        "predecessor_authority_epoch_hash": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 2,
        "policy_activation_hash": HASH,
        "policy_epoch": 2,
        "risk_epoch": 3,
        "authority_epoch": 3,
        "predecessor_active_authorization_id": "auth-1",
        "predecessor_active_authorization_version": 2,
        "predecessor_active_authorization_hash": HASH,
        "predecessor_authorization_status_hash": HASH,
        "predecessor_authorization_status_version": 4,
        "predecessor_entry_fence_version": 5,
        "predecessor_entry_fence_hash": HASH,
        "audited_capital_snapshot_id": "capital-1",
        "audited_capital_snapshot_hash": HASH,
        "inherited_risk_hash": HASH,
        "issued_at": NOW,
        "issuer_id": "governance",
        "issuer_capability": "governance.risk.epoch.start.v1",
        "schema_major": 2,
    }
    assert g.RiskEpochStarted.model_validate(recovery).risk_epoch == 3
    with pytest.raises(ValidationError):
        g.PolicyActivation.model_validate(activation | {"expires_at": NOW})
    with pytest.raises(ValidationError):
        g.RiskEpochStarted.model_validate(recovery | {"risk_epoch": False})


def test_trial_sap_and_stage_are_frozen_pre_signal_content():
    g = _governance()
    from src.screening.offensive.v3.contracts.base import ExecutionMode
    from src.screening.offensive.v3.contracts.governance import PrimaryMetric

    trial = g.TrialManifest.model_validate(_trial())
    assert trial.trial_manifest_sealed_at < trial.enrollment_start
    with pytest.raises(ValidationError):
        g.TrialManifest.model_validate(_trial(enrollment_start=NOW))
    sap = {
        "sap_id": "sap-1",
        "trial_manifest_hash": HASH,
        "research_program_id": "program-1",
        "economic_lineage_id": "btst-lineage",
        "primary_metric": PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": HASH,
        "execution_mode": ExecutionMode.BROKER_CONFIRMED,
        "one_sided_confidence_level": Decimal("0.95"),
        "bootstrap_method": "moving",
        "repetitions": 1000,
        "seed": 7,
        "block_rule": "40",
        "multiplicity_policy": "alpha",
        "alpha_or_evalue_budget_consumption_id": "alpha-1",
        "issued_at": NOW,
        "sealed_at": NOW,
        "enrollment_start": NOW + timedelta(days=1),
        "expires_at": NOW + timedelta(days=2),
        "issuer_id": "governance",
        "issuer_capability": "governance.sap.v1",
        "schema_major": 2,
    }
    assert g.StatisticalAnalysisPlan.model_validate(sap).sap_id == "sap-1"
    stage = {
        "stage_id": "stage-1",
        "trial_manifest_hash": HASH,
        "statistical_analysis_plan_hash": HASH,
        "research_program_id": "program-1",
        "economic_lineage_id": "btst-lineage",
        "primary_metric": PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": HASH,
        "execution_version": "t1-open",
        "cost_version": "cost-v1",
        "governance_policy_version": "gov-v1",
        "execution_mode": ExecutionMode.BROKER_CONFIRMED,
        "stage_sample_reservation_id": "reserve-1",
        "alpha_sample_consumption_id": "alpha-1",
        "alpha_or_evalue_budget_consumption_id": "alpha-e-1",
        "attempt_ledger_checkpoint_hash": HASH,
        "stage_loss_budget_id": "stage-loss-1",
        "stage_loss_version": 1,
        "enrollment_start": NOW + timedelta(days=1),
        "followup_finality_date": NOW + timedelta(days=20),
        "fixed_assessment_date": NOW + timedelta(days=21),
        "maximum_loss_budget_cents": 100,
        "promotion_boolean_expression": "all",
        "issued_at": NOW,
        "issuer_id": "governance",
        "issuer_capability": "governance.stage.manifest.v1",
        "schema_major": 2,
    }
    assert g.StageManifest.model_validate(stage).maximum_loss_budget_cents == 100


def test_exploration_recovery_and_budget_cross_constraints_fail_closed():
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )
    from src.screening.offensive.v3.contracts.authorization import AuthorizationKind

    exploration = _envelope(
        authorization_kind=AuthorizationKind.EXPLORATION,
        issuer_capability="governance.exploration.envelope.v1",
        lineage_grants=(
            _exploration_grant(grant_id="grant-1", economic_lineage_id="btst-lineage"),
        ),
        exploration_aggregate_gross_cap=Decimal("0.02"),
        portfolio_gross_cap=Decimal("0.02"),
        **_exploration_controls(),
    )
    assert (
        CapitalAuthorizationEnvelope.model_validate(
            exploration
        ).authorization_kind.value
        == "EXPLORATION"
    )
    for override in (
        {"mode": "manual_confirmed"},
        {"exploration_aggregate_gross_cap": Decimal("0.021")},
        {"portfolio_gross_cap": Decimal("0.03")},
    ):
        with pytest.raises(ValidationError):
            CapitalAuthorizationEnvelope.model_validate(exploration | override)
    recovery = _envelope(
        authorization_kind=AuthorizationKind.RECOVERY,
        issuer_capability="governance.recovery.envelope.v1",
        portfolio_gross_cap=Decimal("0.02"),
        recovery_inherited_risk_version=2,
        recovery_open_pending_risk_version=2,
        recovery_stage_program_loss_consumption_version=2,
        risk_epoch_started_hash=HASH,
        recovery_manifest_hash=HASH,
        **_predecessor(),
    )
    assert (
        CapitalAuthorizationEnvelope.model_validate(recovery).authorization_kind.value
        == "RECOVERY"
    )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            recovery | {"lineage_grants": (_exploration_grant(),)}
        )


def test_exploration_caps_include_existing_edge_and_recovery_requires_edge_only_grants():
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )
    from src.screening.offensive.v3.contracts.authorization import AuthorizationKind

    edge = _grant(grant_id="edge", lineage_gross_cap=Decimal("0.02"))
    exploration = _exploration_grant(lineage_gross_cap=Decimal("0.01"))
    payload = _envelope(
        authorization_kind=AuthorizationKind.EXPLORATION,
        issuer_capability="governance.exploration.envelope.v1",
        lineage_grants=(edge, exploration),
        exploration_aggregate_gross_cap=Decimal("0.01"),
        portfolio_gross_cap=Decimal("0.02"),
        **_predecessor(),
        **_exploration_controls(),
    )
    assert (
        CapitalAuthorizationEnvelope.model_validate(payload)
        .lineage_grants[0]
        .grant_kind.value
        == "EDGE"
    )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            payload | {"exploration_aggregate_gross_cap": Decimal("0.005")}
        )
    recovery = _envelope(
        authorization_kind=AuthorizationKind.RECOVERY,
        issuer_capability="governance.recovery.envelope.v1",
        portfolio_gross_cap=Decimal("0.02"),
        recovery_inherited_risk_version=2,
        recovery_open_pending_risk_version=2,
        recovery_stage_program_loss_consumption_version=2,
        risk_epoch_started_hash=HASH,
        recovery_manifest_hash=HASH,
        **_predecessor(),
    )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            recovery | {"recovery_inherited_risk_version": None}
        )


def test_envelope_cross_caps_are_fail_closed_without_overconstraining_existing_edge():
    from src.screening.offensive.v3.contracts.authorization import (
        AuthorizationKind,
        CapitalAuthorizationEnvelope,
    )

    edge = _grant(grant_id="edge", lineage_gross_cap=Decimal("0.05"), capital_tier=5)
    exploration = _exploration_grant(lineage_gross_cap=Decimal("0.02"))
    payload = _envelope(
        authorization_kind=AuthorizationKind.EXPLORATION,
        issuer_capability="governance.exploration.envelope.v1",
        lineage_grants=(edge, exploration),
        portfolio_gross_cap=Decimal("0.07"),
        exploration_aggregate_gross_cap=Decimal("0.02"),
        **_predecessor(),
        **_exploration_controls(),
    )
    assert CapitalAuthorizationEnvelope.model_validate(
        payload
    ).portfolio_gross_cap == Decimal("0.07")
    for override in (
        {"exploration_aggregate_gross_cap": Decimal("0.01")},
        {"lineage_grants": (_grant(lineage_gross_cap=Decimal("0.03")),)},
        {
            "authorization_kind": AuthorizationKind.EDGE,
            "exploration_aggregate_gross_cap": Decimal("0.01"),
        },
    ):
        with pytest.raises(ValidationError):
            CapitalAuthorizationEnvelope.model_validate(payload | override)


def test_real_capital_modes_have_exact_account_binding_rules():
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    payload = _envelope()
    assert (
        CapitalAuthorizationEnvelope.model_validate(
            payload
            | {
                "mode": ExecutionMode.MANUAL_CONFIRMED,
                "broker_account_fingerprint": None,
            }
        ).broker_account_id
        == "account-1"
    )
    for override in (
        {
            "mode": ExecutionMode.DAILY_BAR_PROXY,
            "broker_account_id": "account-1",
            "broker_account_fingerprint": None,
        },
        {
            "mode": ExecutionMode.MANUAL_CONFIRMED,
            "broker_account_id": None,
            "broker_account_fingerprint": None,
        },
        {"mode": ExecutionMode.MANUAL_CONFIRMED, "broker_account_fingerprint": HASH},
    ):
        with pytest.raises(ValidationError):
            CapitalAuthorizationEnvelope.model_validate(payload | override)


def test_recovery_fields_are_required_only_for_recovery():
    from src.screening.offensive.v3.contracts.authorization import (
        AuthorizationKind,
        CapitalAuthorizationEnvelope,
    )

    recovery = _envelope(
        authorization_kind=AuthorizationKind.RECOVERY,
        issuer_capability="governance.recovery.envelope.v1",
        portfolio_gross_cap=Decimal("0.02"),
        recovery_inherited_risk_version=2,
        recovery_open_pending_risk_version=2,
        recovery_stage_program_loss_consumption_version=2,
        risk_epoch_started_hash=HASH,
        recovery_manifest_hash=HASH,
        **_predecessor(),
    )
    assert (
        CapitalAuthorizationEnvelope.model_validate(recovery).risk_epoch_started_hash
        == HASH
    )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            _envelope(risk_epoch_started_hash=HASH)
        )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            recovery | {"risk_epoch_started_hash": None}
        )


def test_authorization_status_and_entry_fence_are_strict_monotonic_candidates():
    g = _governance()
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    status = g.AuthorizationStatus.model_validate(
        {
            "portfolio_id": "portfolio-1",
            "broker_account_id": "account-1",
            "broker_account_fingerprint": HASH,
            "mode": ExecutionMode.BROKER_CONFIRMED,
            "authorization_id": "a-1",
            "authorization_version": 2,
            "authorization_envelope_hash": HASH,
            "evidence_set_merkle_root": HASH,
            "authorization_issued_at": NOW - timedelta(minutes=3),
            "authorization_expires_at": NOW + timedelta(hours=1),
            "policy_activation_hash": HASH,
            "trust_bundle_hash": HASH,
            "registry_epoch": 2,
            "policy_epoch": 2,
            "authority_epoch": 2,
            "risk_epoch": 2,
            "status_version": 3,
            "predecessor_status_hash": HASH,
            "status": g.AuthorizationLifecycle.REVALIDATION_REQUIRED,
            "entry_fence_version": 4,
            "activated_at": NOW - timedelta(minutes=2),
            "status_effective_at": NOW - timedelta(minutes=1),
            "status_reason": "evidence revision",
            "status_cause_hash": HASH,
            "as_of": NOW,
            "issuer_id": "authority-store",
            "issuer_capability": (
                "gateway.authority-store.authorization-status.publish.v1"
            ),
            "schema_major": 2,
        }
    )
    assert status.entry_fence_version == 4
    fence = g.EntryFenceRaised.model_validate(
        {
            "fence_id": "fence-1",
            "portfolio_id": "portfolio-1",
            "broker_account_id": "account-1",
            "broker_account_fingerprint": HASH,
            "mode": ExecutionMode.BROKER_CONFIRMED,
            "fence_version": 4,
            "predecessor_fence_hash": HASH,
            "trust_bundle_hash": HASH,
            "registry_epoch": 2,
            "policy_activation_hash": HASH,
            "policy_epoch": 2,
            "authority_epoch": 2,
            "risk_epoch": 2,
            "predecessor_authorization_status_hash": HASH,
            "authorization_status_version": 3,
            "reason": "evidence-revision",
            "cause_revision_id": "revision-1",
            "cause_revision_hash": HASH,
            "raised_at": NOW,
            "affected_authorization_id": "a-1",
            "affected_authorization_version": 2,
            "affected_authorization_envelope_hash": HASH,
            "affected_evidence_set_merkle_root": HASH,
            "issuer_id": "dependency-tracker",
            "issuer_capability": "dependency-tracker.entry-fence.raise.v1",
            "schema_major": 2,
        }
    )
    assert fence.fence_version == 4
    with pytest.raises(ValidationError):
        g.EntryFenceRaised.model_validate(fence.model_dump() | {"unexpected": "field"})
    with pytest.raises(ValidationError):
        g.EntryFenceRaised.model_validate(
            fence.model_dump()
            | {"issuer_capability": "governance.policy.activation.v1"}
        )


def test_trust_bundle_rejects_bad_time_revocation_and_non_native_epoch():
    g = _governance()
    payload = {
        "registry_epoch": 2,
        "predecessor_bundle_hash": HASH,
        "root_hash": HASH,
        "root_key_id": "root-1",
        "trusted_issuer_registry_hash": HASH,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(days=1),
        "revoked_at": None,
        "issuer_id": "root",
        "issuer_capability": "root.trust.bundle.v1",
        "schema_major": 2,
    }
    for override in (
        {"expires_at": NOW},
        {"revoked_at": NOW - timedelta(seconds=1)},
        {"registry_epoch": True},
        {"registry_epoch": 2.0},
    ):
        with pytest.raises(ValidationError):
            g.TrustBundle.model_validate(payload | override)


@pytest.mark.parametrize(
    ("name", "capability"),
    [
        ("MigrationApprovalManifest", "governance.migration.approval.v1"),
        ("BrokerEnablementManifest", "governance.broker.enablement.v1"),
        ("DisasterRecoveryManifest", "governance.disaster.recovery.v1"),
    ],
)
def test_sensitive_manifests_require_distinct_capability_and_two_attestations(
    name, capability
):
    g = _governance()
    from test_governance_remediation_b import (
        _broker_manifest,
        _dr_manifest,
        _migration_manifest,
    )

    cls = getattr(g, name)
    if name == "MigrationApprovalManifest":
        payload = _migration_manifest()
    elif name == "BrokerEnablementManifest":
        payload = _broker_manifest()
    else:
        payload = _dr_manifest()
    assert cls.model_validate(payload).issuer_capability == capability
    with pytest.raises(ValidationError):
        cls.model_validate(payload | {"issuer_capability": "governance.other.v1"})
    with pytest.raises(ValidationError):
        cls.model_validate(payload | {"approval_attestations": ()})
    for override in (
        {"expires_at": NOW},
        {"one_shot": False},
        {"extra_field": True},
    ):
        with pytest.raises(ValidationError):
            cls.model_validate(payload | override)
