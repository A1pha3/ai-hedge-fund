"""Canonical valid exemplars for Task 2 artifact hash fixtures."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from src.screening.offensive.v3.contracts.authorization import (
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.contracts.governance import (
    ApprovalAttestationBinding,
    AuthorizationStatus,
    BrokerEnablementManifest,
    DisasterRecoveryManifest,
    EntryFenceAcknowledgement,
    EntryFenceRaised,
    LineageGrant,
    MigrationApprovalManifest,
    PolicyActivation,
    PrimaryMetric,
    ProgramLossBudgetBinding,
    RiskEpochStarted,
    StageManifest,
    StatisticalAnalysisPlan,
    TrialManifest,
    TrustBundle,
)

from test_authorization import _envelope, _grant
from test_governance import HASH, NOW, _trial
from test_governance_remediation_b import (
    _approval_attestations,
    _authorization_status,
    _broker_manifest,
    _dr_manifest,
    _entry_fence,
    _migration_manifest,
)


def task2_hash_exemplars() -> dict[str, object]:
    """Return one valid immutable exemplar for every Task 2 public artifact."""

    trust = TrustBundle.model_validate(
        {
            "registry_epoch": 2,
            "predecessor_bundle_hash": HASH,
            "root_hash": HASH,
            "root_key_id": "root-key",
            "trusted_issuer_registry_hash": HASH,
            "issued_at": NOW,
            "expires_at": NOW + timedelta(hours=1),
            "revoked_at": None,
            "issuer_id": "root",
            "issuer_capability": "root.trust.bundle.v1",
            "schema_major": 2,
        }
    )
    activation = PolicyActivation.model_validate(
        {
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
            "expires_at": NOW + timedelta(hours=1),
            "issuer_id": "governance",
            "issuer_capability": "governance.policy.activation.v1",
            "schema_major": 2,
        }
    )
    risk_epoch = RiskEpochStarted.model_validate(
        {
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
    )
    sap = StatisticalAnalysisPlan.model_validate(
        {
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
    )
    stage = StageManifest.model_validate(
        {
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
    )
    fence = EntryFenceRaised.model_validate(_entry_fence())
    acknowledgement = EntryFenceAcknowledgement.model_validate(
        {
            "acknowledgement_id": "fence-ack-1",
            "fence_id": fence.fence_id,
            "entry_fence_hash": fence.artifact_hash(),
            "fence_version": fence.fence_version,
            "portfolio_id": fence.portfolio_id,
            "broker_account_id": fence.broker_account_id,
            "broker_account_fingerprint": fence.broker_account_fingerprint,
            "mode": fence.mode,
            "authority_epoch": fence.authority_epoch,
            "risk_epoch": fence.risk_epoch,
            "authorization_status_hash": fence.predecessor_authorization_status_hash,
            "authorization_status_version": fence.authorization_status_version,
            "fence_raised_at": fence.raised_at,
            "durably_acknowledged_at": NOW + timedelta(seconds=1),
            "gateway_writer_id": "capital-gateway-writer",
            "gateway_writer_version": 7,
            "gateway_fencing_epoch": 9,
            "issuer_id": "capital-gateway",
            "issuer_capability": "capital-gateway.entry-fence.acknowledge.v1",
            "schema_major": 2,
        }
    )
    broker = BrokerEnablementManifest.model_validate(_broker_manifest())
    dr = DisasterRecoveryManifest.model_validate(_dr_manifest())
    envelope_payload = _envelope()
    return {
        "ApprovalAttestationBinding": ApprovalAttestationBinding.model_validate(
            _approval_attestations("MIGRATION_APPROVAL_MANIFEST")[0]
        ),
        "AuthorizationStatus": AuthorizationStatus.model_validate(
            _authorization_status()
        ),
        "BrokerEnablementManifest": broker,
        "CapitalAuthorizationEnvelope": CapitalAuthorizationEnvelope.model_validate(
            envelope_payload
        ),
        "DisasterRecoveryManifest": dr,
        "EntryFenceAcknowledgement": acknowledgement,
        "EntryFenceRaised": fence,
        "LineageGrant": LineageGrant.model_validate(_grant()),
        "MigrationApprovalManifest": MigrationApprovalManifest.model_validate(
            _migration_manifest()
        ),
        "PolicyActivation": activation,
        "ProgramLossBudgetBinding": ProgramLossBudgetBinding.model_validate(
            envelope_payload["program_loss_budget_bindings"][0]
        ),
        "RiskEpochStarted": risk_epoch,
        "StageManifest": stage,
        "StatisticalAnalysisPlan": sap,
        "TrialManifest": TrialManifest.model_validate(
            _trial(minimum_economic_effect=Decimal("0.0000001"))
        ),
        "TrustBundle": trust,
    }
