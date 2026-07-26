"""Portfolio-wide Revision 2 authorization candidates; never active by construction."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from .base import CanonicalModel, ExecutionMode, SchemaVersion, Sha256, UtcInstant
from .evidence import NonEmptyStr
from .governance import Fraction, LineageGrant, ProgramLossBudgetBinding, PositiveInt


class AuthorizationKind(StrEnum):
    EDGE = "EDGE"
    EXPLORATION = "EXPLORATION"
    RECOVERY = "RECOVERY"


class CapitalAuthorizationEnvelope(CanonicalModel):
    authorization_kind: AuthorizationKind
    authorization_id: NonEmptyStr
    authorization_version: PositiveInt
    mode: ExecutionMode
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None = None
    broker_account_fingerprint: Sha256 | None = None
    base_currency: NonEmptyStr
    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveInt
    policy_epoch: PositiveInt
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    research_program_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    baseline_portfolio_policy_fingerprint: Sha256
    target_portfolio_policy_fingerprint: Sha256
    lineage_grants: Annotated[tuple[LineageGrant, ...], Field(min_length=1)]
    evidence_as_of: UtcInstant
    evidence_set_merkle_root: Sha256
    issued_at: UtcInstant
    expires_at: UtcInstant
    activation_capital_snapshot_id: NonEmptyStr
    activation_capital_snapshot_hash: Sha256
    portfolio_gross_cap: Fraction
    exploration_aggregate_gross_cap: Fraction
    program_loss_budget_bindings: Annotated[tuple[ProgramLossBudgetBinding, ...], Field(min_length=1)]
    issuer_id: NonEmptyStr
    issuer_capability: NonEmptyStr
    portfolio_assessment_result_hash: Sha256
    global_attempt_ledger_checkpoint_hash: Sha256
    global_multiplicity_budget_consumption_id: NonEmptyStr
    recovery_inherited_risk_version: PositiveInt | None = None
    recovery_open_pending_risk_version: PositiveInt | None = None
    recovery_stage_program_loss_consumption_version: PositiveInt | None = None
    risk_epoch_started_hash: Sha256 | None = None
    recovery_manifest_hash: Sha256 | None = None
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research reconstruction cannot receive entry authorization")
        if self.mode is ExecutionMode.BROKER_CONFIRMED:
            if self.broker_account_id is None or self.broker_account_fingerprint is None:
                raise ValueError("broker-confirmed envelope requires broker account binding")
        elif self.mode is ExecutionMode.MANUAL_CONFIRMED:
            if self.broker_account_id is None or self.broker_account_fingerprint is not None:
                raise ValueError("manual-confirmed envelope requires account and no fingerprint")
        elif self.broker_account_id is not None or self.broker_account_fingerprint is not None:
            raise ValueError("proxy envelope cannot claim broker binding")
        if self.expires_at <= self.issued_at or self.evidence_as_of > self.issued_at:
            raise ValueError("authorization time order is invalid")
        if len(self.research_program_ids) != len(set(self.research_program_ids)):
            raise ValueError("research_program_ids must be unique")
        grant_ids = [grant.grant_id for grant in self.lineage_grants]
        if len(grant_ids) != len(set(grant_ids)):
            raise ValueError("lineage grants must be unique")
        budget_programs = [item.research_program_id for item in self.program_loss_budget_bindings]
        if len(budget_programs) != len(set(budget_programs)) or set(budget_programs) != set(self.research_program_ids):
            raise ValueError("program loss budgets must exactly bind research programs")
        if {grant.research_program_id for grant in self.lineage_grants} - set(self.research_program_ids):
            raise ValueError("all grants must belong to envelope research programs")
        exploration = [grant for grant in self.lineage_grants if grant.grant_kind.value == "EXPLORATION"]
        exploration_cap = sum((grant.lineage_gross_cap for grant in exploration), start=0)
        two_percent = Decimal("0.02")
        for grant in self.lineage_grants:
            if grant.lineage_gross_cap > self.portfolio_gross_cap:
                raise ValueError("lineage gross cap cannot exceed portfolio gross cap")
            if grant.lineage_gross_cap > Decimal(grant.capital_tier) / Decimal(100):
                raise ValueError("lineage gross cap cannot exceed capital tier")
        if self.exploration_aggregate_gross_cap > two_percent or exploration_cap > two_percent:
            raise ValueError("exploration aggregate gross cap cannot exceed 2%")
        if self.authorization_kind is AuthorizationKind.EDGE:
            if any(value is not None for value in (self.recovery_inherited_risk_version, self.recovery_open_pending_risk_version, self.recovery_stage_program_loss_consumption_version, self.risk_epoch_started_hash, self.recovery_manifest_hash)):
                raise ValueError("EDGE cannot carry recovery-only fields")
            if exploration or self.exploration_aggregate_gross_cap != Decimal("0") or self.issuer_capability != "authorizer.edge.envelope.v1":
                raise ValueError("EDGE envelope requires only edge grants and authorizer capability")
        elif self.authorization_kind is AuthorizationKind.EXPLORATION:
            if any(value is not None for value in (self.recovery_inherited_risk_version, self.recovery_open_pending_risk_version, self.recovery_stage_program_loss_consumption_version, self.risk_epoch_started_hash, self.recovery_manifest_hash)):
                raise ValueError("EXPLORATION cannot carry recovery-only fields")
            if self.mode is not ExecutionMode.BROKER_CONFIRMED or not exploration or self.issuer_capability != "governance.exploration.envelope.v1":
                raise ValueError("EXPLORATION requires broker mode, exploration grant, governance capability")
            if self.exploration_aggregate_gross_cap != exploration_cap:
                raise ValueError("exploration aggregate cap must equal exploration grants")
            if not any(grant.grant_kind.value == "EDGE" for grant in self.lineage_grants) and self.portfolio_gross_cap > two_percent:
                raise ValueError("first broker exploration portfolio cap cannot exceed 2%")
        else:
            if self.issuer_capability != "governance.recovery.envelope.v1" or any(g.grant_kind.value != "EDGE" for g in self.lineage_grants) or self.exploration_aggregate_gross_cap != Decimal("0"):
                raise ValueError("RECOVERY cannot create exploration grants")
            if self.portfolio_gross_cap > two_percent or None in (self.recovery_inherited_risk_version, self.recovery_open_pending_risk_version, self.recovery_stage_program_loss_consumption_version, self.risk_epoch_started_hash, self.recovery_manifest_hash):
                raise ValueError("RECOVERY requires 2% cap and inherited risk/loss versions")
        return self


__all__ = ["AuthorizationKind", "CapitalAuthorizationEnvelope"]
