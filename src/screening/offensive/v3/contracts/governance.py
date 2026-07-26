"""Storage-free, fail-closed Governance Control Plane candidates.

These are immutable candidate documents.  Constructing one never activates a
policy, trust registry, broker, writer, or authorization.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, Strict, field_validator, model_validator

from .base import CanonicalModel, ExecutionMode, MoneyCents, SchemaVersion, Sha256, UtcInstant
from .evidence import NonEmptyStr

PositiveInt = Annotated[MoneyCents, Field(ge=1)]
NonNegativeInt = Annotated[MoneyCents, Field(ge=0)]
PositiveCents = Annotated[MoneyCents, Field(gt=0)]
Fraction = Annotated[Decimal, Strict(), Field(ge=Decimal("0"), le=Decimal("1"))]
PositiveDecimal = Annotated[Decimal, Strict(), Field(gt=Decimal("0"))]


def _capability(value: str, expected: str) -> None:
    if value != expected:
        raise ValueError(f"issuer_capability must be {expected}")


def _unique(values: tuple[str, ...], label: str) -> None:
    if not values or len(values) != len(set(values)):
        raise ValueError(f"{label} must be nonempty and unique")


def _validate_account_mode(
    mode: ExecutionMode,
    account_id: str | None,
    account_fingerprint: str | None,
) -> None:
    if mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
        raise ValueError("research mode cannot activate capital governance")
    if mode is ExecutionMode.DAILY_BAR_PROXY:
        if account_id is not None or account_fingerprint is not None:
            raise ValueError("proxy mode cannot bind a real broker account")
    elif mode is ExecutionMode.MANUAL_CONFIRMED:
        if account_id is None or account_fingerprint is not None:
            raise ValueError("manual mode requires account and no broker fingerprint")
    elif account_id is None or account_fingerprint is None:
        raise ValueError("broker mode requires account and fingerprint")


class TrustBundle(CanonicalModel):
    registry_epoch: PositiveInt
    predecessor_bundle_hash: Sha256
    root_hash: Sha256
    root_key_id: NonEmptyStr
    trusted_issuer_registry_hash: Sha256
    issued_at: UtcInstant
    expires_at: UtcInstant
    revoked_at: UtcInstant | None
    issuer_id: NonEmptyStr
    issuer_capability: NonEmptyStr
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        _capability(self.issuer_capability, "root.trust.bundle.v1")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise ValueError("revoked_at cannot precede issued_at")
        return self


class PolicyActivation(CanonicalModel):
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None = None
    broker_account_fingerprint: Sha256 | None = None
    mode: ExecutionMode
    policy_snapshot_hash: Sha256
    predecessor_policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveInt
    policy_epoch: PositiveInt
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    effective_from: UtcInstant
    expires_at: UtcInstant
    issuer_id: NonEmptyStr
    issuer_capability: NonEmptyStr
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        _capability(self.issuer_capability, "governance.policy.activation.v1")
        _validate_account_mode(self.mode, self.broker_account_id, self.broker_account_fingerprint)
        if self.expires_at <= self.effective_from:
            raise ValueError("expires_at must be after effective_from")
        return self


class RiskEpochStarted(CanonicalModel):
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None = None
    broker_account_fingerprint: Sha256 | None = None
    mode: ExecutionMode
    predecessor_risk_epoch_hash: Sha256
    predecessor_authority_epoch_hash: Sha256
    risk_epoch: PositiveInt
    authority_epoch: PositiveInt
    audited_capital_snapshot_id: NonEmptyStr
    audited_capital_snapshot_hash: Sha256
    inherited_risk_hash: Sha256
    issued_at: UtcInstant
    issuer_id: NonEmptyStr
    issuer_capability: NonEmptyStr
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        _capability(self.issuer_capability, "governance.risk.epoch.start.v1")
        _validate_account_mode(self.mode, self.broker_account_id, self.broker_account_fingerprint)
        return self


class TrialManifest(CanonicalModel):
    family_id: NonEmptyStr; economic_lineage_id: NonEmptyStr; research_program_id: NonEmptyStr; trial_id: NonEmptyStr
    baseline_portfolio_policy_fingerprint: Sha256; target_portfolio_policy_fingerprint: Sha256
    trust_bundle_hash: Sha256; registry_epoch: PositiveInt; baseline_policy_activation_hash: Sha256; target_policy_snapshot_registration_hash: Sha256
    attempt_ledger_checkpoint_before_trial: Sha256; attempt_budget_reservation_id: NonEmptyStr; statistical_governance_policy_version: NonEmptyStr
    champion_behavior_fingerprint: Sha256; challenger_behavior_fingerprint: Sha256; primary_metric: NonEmptyStr; minimum_economic_effect: PositiveDecimal; weight_selection_rule: NonEmptyStr
    trial_manifest_sealed_at: UtcInstant; enrollment_start: UtcInstant; enrollment_end: UtcInstant; followup_finality_date: UtcInstant; fixed_assessment_date: UtcInstant
    execution_version: NonEmptyStr; cost_version: NonEmptyStr; execution_mode: ExecutionMode; benchmark_definition: NonEmptyStr; capacity_policy: NonEmptyStr; tail_risk_policy: NonEmptyStr; estimator: NonEmptyStr
    one_sided_confidence_level: Fraction; bootstrap_method: NonEmptyStr; bootstrap_repetitions: PositiveInt; bootstrap_seed: NonNegativeInt; block_rule: NonEmptyStr; ess_definition: NonEmptyStr; missing_censoring_itt_rule: NonEmptyStr
    fold_boundaries: tuple[NonEmptyStr, ...]; purge_embargo: NonEmptyStr; promotion_boolean_expression: NonEmptyStr; multiplicity_policy: NonEmptyStr; broker_experiment_design: NonEmptyStr | None
    canonical_outcome_counting_rule: NonEmptyStr; stage_loss_measurement_basis: NonEmptyStr
    issuer_id: NonEmptyStr; issuer_capability: NonEmptyStr; issued_at: UtcInstant; expires_at: UtcInstant; schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_trial(self) -> Self:
        _capability(self.issuer_capability, "governance.trial.manifest.v1")
        _unique(self.fold_boundaries, "fold_boundaries")
        if not (self.trial_manifest_sealed_at < self.enrollment_start <= self.enrollment_end < self.followup_finality_date <= self.fixed_assessment_date):
            raise ValueError("trial dates must be sealed before enrollment and assessment")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if self.execution_mode is ExecutionMode.BROKER_CONFIRMED and self.broker_experiment_design is None:
            raise ValueError("broker trial requires broker_experiment_design")
        return self


class StatisticalAnalysisPlan(CanonicalModel):
    sap_id: NonEmptyStr; trial_manifest_hash: Sha256; research_program_id: NonEmptyStr; economic_lineage_id: NonEmptyStr; primary_metric: NonEmptyStr
    one_sided_confidence_level: Fraction; bootstrap_method: NonEmptyStr; repetitions: PositiveInt; seed: NonNegativeInt; block_rule: NonEmptyStr; multiplicity_policy: NonEmptyStr; alpha_or_evalue_budget_consumption_id: NonEmptyStr
    sealed_at: UtcInstant; issuer_id: NonEmptyStr; issuer_capability: NonEmptyStr; schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_sap(self) -> Self:
        _capability(self.issuer_capability, "governance.sap.v1")
        return self


class StageManifest(CanonicalModel):
    stage_id: NonEmptyStr; trial_manifest_hash: Sha256; statistical_analysis_plan_hash: Sha256; research_program_id: NonEmptyStr; economic_lineage_id: NonEmptyStr
    baseline_portfolio_policy_fingerprint: Sha256; target_portfolio_policy_fingerprint: Sha256; execution_version: NonEmptyStr; cost_version: NonEmptyStr; governance_policy_version: NonEmptyStr; execution_mode: ExecutionMode
    stage_sample_reservation_id: NonEmptyStr; alpha_sample_consumption_id: NonEmptyStr; alpha_or_evalue_budget_consumption_id: NonEmptyStr; attempt_ledger_checkpoint_hash: Sha256
    stage_loss_budget_id: NonEmptyStr; stage_loss_version: PositiveInt; enrollment_start: UtcInstant; followup_finality_date: UtcInstant; fixed_assessment_date: UtcInstant
    maximum_loss_budget_cents: PositiveCents; promotion_boolean_expression: NonEmptyStr; issued_at: UtcInstant; issuer_id: NonEmptyStr; issuer_capability: NonEmptyStr; schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_stage(self) -> Self:
        _capability(self.issuer_capability, "governance.stage.manifest.v1")
        if not self.enrollment_start < self.followup_finality_date <= self.fixed_assessment_date:
            raise ValueError("stage dates must be in forward order")
        return self


class GrantKind(StrEnum):
    EDGE = "EDGE"
    EXPLORATION = "EXPLORATION"


class LineageGrant(CanonicalModel):
    grant_id: NonEmptyStr; grant_kind: GrantKind; grant_certificate_hash: Sha256; grant_issuer_id: NonEmptyStr
    subject_producer: NonEmptyStr; family_id: NonEmptyStr; economic_lineage_id: NonEmptyStr; research_program_id: NonEmptyStr
    behavior_fingerprint: Sha256; execution_version: NonEmptyStr; cost_version: NonEmptyStr; capital_tier: Literal[2, 5, 10]; lineage_gross_cap: Fraction
    trial_id: NonEmptyStr; trial_manifest_hash: Sha256; statistical_analysis_plan_hash: Sha256; stage_id: NonEmptyStr; stage_manifest_hash: Sha256; stage_sample_reservation_id: NonEmptyStr
    stage_loss_budget_id: NonEmptyStr; stage_loss_budget_cents: PositiveCents; stage_loss_version: PositiveInt; assessment_result_hash: Sha256; grant_evidence_set_merkle_root: Sha256
    attempt_ledger_checkpoint_hash: Sha256; alpha_or_evalue_budget_consumption_id: NonEmptyStr; alpha_sample_consumption_id: NonEmptyStr; schema_major: SchemaVersion


class ProgramLossBudgetBinding(CanonicalModel):
    research_program_id: NonEmptyStr; budget_id: NonEmptyStr; budget_cents: PositiveCents; consumed_cents: NonNegativeInt; version: PositiveInt; schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_budget(self) -> Self:
        if self.consumed_cents > self.budget_cents:
            raise ValueError("consumed_cents cannot exceed budget_cents")
        return self


class AuthorizationLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AuthorizationStatus(CanonicalModel):
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None = None
    broker_account_fingerprint: Sha256 | None = None
    mode: ExecutionMode
    authorization_id: NonEmptyStr
    authorization_version: PositiveInt
    authorization_envelope_hash: Sha256
    evidence_set_merkle_root: Sha256
    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveInt
    policy_epoch: PositiveInt
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    status_version: PositiveInt
    predecessor_status_hash: Sha256
    status: AuthorizationLifecycle
    entry_fence_version: NonNegativeInt
    as_of: UtcInstant
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        _validate_account_mode(self.mode, self.broker_account_id, self.broker_account_fingerprint)
        return self


class EntryFenceRaised(CanonicalModel):
    fence_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None = None
    broker_account_fingerprint: Sha256 | None = None
    mode: ExecutionMode
    fence_version: PositiveInt
    predecessor_fence_hash: Sha256
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    authorization_status_version: PositiveInt
    reason: NonEmptyStr
    cause_revision_id: NonEmptyStr
    cause_revision_hash: Sha256
    raised_at: UtcInstant
    affected_authorization_id: NonEmptyStr | None
    affected_authorization_version: PositiveInt | None
    affected_authorization_envelope_hash: Sha256 | None
    affected_evidence_set_merkle_root: Sha256 | None
    issuer_id: NonEmptyStr
    issuer_capability: NonEmptyStr
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_fence(self) -> Self:
        _capability(self.issuer_capability, "gateway.entry.fence.raise.v1")
        _validate_account_mode(self.mode, self.broker_account_id, self.broker_account_fingerprint)
        affected = (self.affected_authorization_id, self.affected_authorization_version, self.affected_authorization_envelope_hash, self.affected_evidence_set_merkle_root)
        if any(value is None for value in affected) and any(value is not None for value in affected):
            raise ValueError("affected authorization fields must be all-or-none")
        return self


class _TwoPersonOneShotManifest(CanonicalModel):
    manifest_id: NonEmptyStr; portfolio_id: NonEmptyStr; broker_account_id: NonEmptyStr; issued_at: UtcInstant; expires_at: UtcInstant; one_shot: Literal[True]
    approver_ids: tuple[NonEmptyStr, ...]; issuer_id: NonEmptyStr; issuer_capability: NonEmptyStr; schema_major: SchemaVersion

    def _validate_common(self, expected: str) -> None:
        _capability(self.issuer_capability, expected)
        if not self.one_shot or len(self.approver_ids) != 2 or len(set(self.approver_ids)) != 2:
            raise ValueError("manifest requires exactly two distinct approvers and one_shot")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")


class MigrationApprovalManifest(_TwoPersonOneShotManifest):
    source_portfolio_id: NonEmptyStr; target_portfolio_id: NonEmptyStr; source_writer_id: NonEmptyStr; target_writer_id: NonEmptyStr
    migration_program_hash: Sha256; conservation_formula_hash: Sha256; live_order_adoption_hash: Sha256; credential_fencing_hash: Sha256; rollback_dr_hash: Sha256

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        self._validate_common("governance.migration.approval.v1")
        if self.target_portfolio_id != self.portfolio_id:
            raise ValueError("target portfolio must match portfolio_id")
        return self


class BrokerEnablementManifest(_TwoPersonOneShotManifest):
    broker_account_fingerprint: Sha256; trusted_clock_hash: Sha256; raw_envelope_policy_hash: Sha256; pagination_cursor_retention_hash: Sha256
    client_order_idempotency_hash: Sha256; auction_tif_cutoff_hash: Sha256; exit_rate_limit_hash: Sha256; credential_session_network_fencing_hash: Sha256

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        self._validate_common("governance.broker.enablement.v1")
        return self


class DisasterRecoveryManifest(_TwoPersonOneShotManifest):
    backup_root_hash: Sha256; durable_cursor: NonEmptyStr; target_writer_id: NonEmptyStr; recovery_epoch: PositiveInt; fencing_epoch: PositiveInt; reconcile_before_entry: bool

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        self._validate_common("governance.disaster.recovery.v1")
        if not self.reconcile_before_entry:
            raise ValueError("disaster recovery must reconcile before entry")
        return self


__all__ = ["AuthorizationStatus", "BrokerEnablementManifest", "DisasterRecoveryManifest", "EntryFenceRaised", "Fraction", "GrantKind", "LineageGrant", "MigrationApprovalManifest", "PolicyActivation", "ProgramLossBudgetBinding", "RiskEpochStarted", "StageManifest", "StatisticalAnalysisPlan", "TrialManifest", "TrustBundle"]
