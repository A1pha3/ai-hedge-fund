"""Portfolio-wide Revision 2 authorization candidates; never active by construction."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from .base import CanonicalModel, ExecutionMode, SchemaVersion, Sha256, UtcInstant
from .evidence import NonEmptyStr
from .governance import (
    Fraction,
    LineageGrant,
    NonNegativeInt,
    PositiveCents,
    PositiveInt,
    ProgramLossBudgetBinding,
)


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
    program_loss_budget_bindings: Annotated[
        tuple[ProgramLossBudgetBinding, ...], Field(min_length=1)
    ]
    issuer_id: NonEmptyStr
    issuer_capability: NonEmptyStr
    portfolio_assessment_result_hash: Sha256
    global_attempt_ledger_checkpoint_hash: Sha256
    global_multiplicity_budget_consumption_id: NonEmptyStr
    predecessor_active_authorization_id: NonEmptyStr | None = None
    predecessor_active_authorization_version: PositiveInt | None = None
    predecessor_active_authorization_hash: Sha256 | None = None
    predecessor_active_authorization_status_hash: Sha256 | None = None
    predecessor_target_policy_fingerprint: Sha256 | None = None
    predecessor_active_edge_grant_certificate_hashes: tuple[Sha256, ...] | None = None
    exploration_shared_stress_loss_budget_id: NonEmptyStr | None = None
    exploration_shared_stress_loss_budget_cents: PositiveCents | None = None
    exploration_shared_stress_loss_consumed_cents: NonNegativeInt | None = None
    exploration_shared_stress_loss_version: PositiveInt | None = None
    exploration_one_shot_reservation_id: NonEmptyStr | None = None
    exploration_one_shot_consumption_id: NonEmptyStr | None = None
    exploration_trial_id: NonEmptyStr | None = None
    exploration_fixed_assessment_at: UtcInstant | None = None
    recovery_inherited_risk_version: PositiveInt | None = None
    recovery_open_pending_risk_version: PositiveInt | None = None
    recovery_stage_program_loss_consumption_version: PositiveInt | None = None
    risk_epoch_started_hash: Sha256 | None = None
    recovery_manifest_hash: Sha256 | None = None
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError(
                "research reconstruction cannot receive entry authorization"
            )
        if self.mode is ExecutionMode.BROKER_CONFIRMED:
            if (
                self.broker_account_id is None
                or self.broker_account_fingerprint is None
            ):
                raise ValueError(
                    "broker-confirmed envelope requires broker account binding"
                )
        elif self.mode is ExecutionMode.MANUAL_CONFIRMED:
            if (
                self.broker_account_id is None
                or self.broker_account_fingerprint is not None
            ):
                raise ValueError(
                    "manual-confirmed envelope requires account and no fingerprint"
                )
        elif (
            self.broker_account_id is not None
            or self.broker_account_fingerprint is not None
        ):
            raise ValueError("proxy envelope cannot claim broker binding")
        if self.expires_at <= self.issued_at or self.evidence_as_of > self.issued_at:
            raise ValueError("authorization time order is invalid")
        if len(self.research_program_ids) != len(
            set(self.research_program_ids)
        ) or self.research_program_ids != tuple(sorted(self.research_program_ids)):
            raise ValueError("research_program_ids must be unique")
        expected_grant_order = tuple(
            sorted(
                self.lineage_grants,
                key=lambda grant: (
                    grant.research_program_id,
                    grant.economic_lineage_id,
                    grant.grant_id,
                ),
            )
        )
        if self.lineage_grants != expected_grant_order:
            raise ValueError("lineage grants must use canonical order")
        unique_grant_fields = (
            "grant_id",
            "economic_lineage_id",
            "grant_certificate_hash",
            "assessment_result_hash",
            "stage_id",
            "stage_sample_reservation_id",
            "stage_loss_budget_id",
            "attempt_ledger_checkpoint_hash",
            "alpha_or_evalue_budget_consumption_id",
            "alpha_sample_consumption_id",
        )
        for field_name in unique_grant_fields:
            values = [getattr(grant, field_name) for grant in self.lineage_grants]
            if len(values) != len(set(values)):
                raise ValueError(f"lineage grants require unique {field_name}")
        budget_programs = [
            item.research_program_id for item in self.program_loss_budget_bindings
        ]
        budget_ids = [item.budget_id for item in self.program_loss_budget_bindings]
        expected_budget_order = tuple(
            sorted(
                self.program_loss_budget_bindings,
                key=lambda budget: (budget.research_program_id, budget.budget_id),
            )
        )
        if self.program_loss_budget_bindings != expected_budget_order:
            raise ValueError("program loss budgets must use canonical order")
        if (
            len(budget_programs) != len(set(budget_programs))
            or len(budget_ids) != len(set(budget_ids))
            or set(budget_programs) != set(self.research_program_ids)
        ):
            raise ValueError("program loss budgets must exactly bind research programs")
        grant_programs = {grant.research_program_id for grant in self.lineage_grants}
        if grant_programs != set(self.research_program_ids):
            raise ValueError("grant programs must exactly bind research programs")
        exploration = [
            grant
            for grant in self.lineage_grants
            if grant.grant_kind.value == "EXPLORATION"
        ]
        exploration_cap = sum(
            (grant.lineage_gross_cap for grant in exploration), start=Decimal("0")
        )
        two_percent = Decimal("0.02")
        for grant in self.lineage_grants:
            if grant.lineage_gross_cap > self.portfolio_gross_cap:
                raise ValueError("lineage gross cap cannot exceed portfolio gross cap")
            if grant.lineage_gross_cap > Decimal(grant.capital_tier) / Decimal(100):
                raise ValueError("lineage gross cap cannot exceed capital tier")
        predecessor_values = (
            self.predecessor_active_authorization_id,
            self.predecessor_active_authorization_version,
            self.predecessor_active_authorization_hash,
            self.predecessor_active_authorization_status_hash,
            self.predecessor_target_policy_fingerprint,
            self.predecessor_active_edge_grant_certificate_hashes,
        )
        predecessor_present = all(value is not None for value in predecessor_values)
        if (
            any(value is not None for value in predecessor_values)
            and not predecessor_present
        ):
            raise ValueError("predecessor authorization fields must be all-or-none")
        if predecessor_present:
            certificates = self.predecessor_active_edge_grant_certificate_hashes
            if certificates is None:
                raise ValueError("predecessor EDGE certificates are required")
            if not certificates or certificates != tuple(sorted(set(certificates))):
                raise ValueError(
                    "predecessor EDGE certificates must be unique and ordered"
                )
        exploration_only_values = (
            self.exploration_shared_stress_loss_budget_id,
            self.exploration_shared_stress_loss_budget_cents,
            self.exploration_shared_stress_loss_consumed_cents,
            self.exploration_shared_stress_loss_version,
            self.exploration_one_shot_reservation_id,
            self.exploration_one_shot_consumption_id,
            self.exploration_trial_id,
            self.exploration_fixed_assessment_at,
        )
        exploration_only_present = all(
            value is not None for value in exploration_only_values
        )
        if (
            any(value is not None for value in exploration_only_values)
            and not exploration_only_present
        ):
            raise ValueError("exploration-only fields must be all-or-none")
        if (
            self.exploration_aggregate_gross_cap > two_percent
            or exploration_cap > two_percent
        ):
            raise ValueError("exploration aggregate gross cap cannot exceed 2%")
        if self.authorization_kind is AuthorizationKind.EDGE:
            if exploration_only_present:
                raise ValueError("EDGE cannot carry exploration-only fields")
            if any(
                value is not None
                for value in (
                    self.recovery_inherited_risk_version,
                    self.recovery_open_pending_risk_version,
                    self.recovery_stage_program_loss_consumption_version,
                    self.risk_epoch_started_hash,
                    self.recovery_manifest_hash,
                )
            ):
                raise ValueError("EDGE cannot carry recovery-only fields")
            if (
                exploration
                or self.exploration_aggregate_gross_cap != Decimal("0")
                or self.issuer_capability != "authorizer.edge.envelope.v1"
            ):
                raise ValueError(
                    "EDGE envelope requires only edge grants and authorizer capability"
                )
        elif self.authorization_kind is AuthorizationKind.EXPLORATION:
            if any(
                value is not None
                for value in (
                    self.recovery_inherited_risk_version,
                    self.recovery_open_pending_risk_version,
                    self.recovery_stage_program_loss_consumption_version,
                    self.risk_epoch_started_hash,
                    self.recovery_manifest_hash,
                )
            ):
                raise ValueError("EXPLORATION cannot carry recovery-only fields")
            if (
                self.mode is not ExecutionMode.BROKER_CONFIRMED
                or not exploration
                or self.issuer_capability != "governance.exploration.envelope.v1"
            ):
                raise ValueError(
                    "EXPLORATION requires broker mode, exploration grant, governance capability"
                )
            if not exploration_only_present:
                raise ValueError("EXPLORATION requires shared one-shot loss budget")
            if (
                self.exploration_shared_stress_loss_budget_cents is None
                or self.exploration_shared_stress_loss_consumed_cents is None
                or self.exploration_shared_stress_loss_budget_id is None
                or self.exploration_fixed_assessment_at is None
            ):
                raise ValueError("EXPLORATION requires complete shared loss controls")
            if (
                self.exploration_shared_stress_loss_consumed_cents
                > self.exploration_shared_stress_loss_budget_cents
            ):
                raise ValueError("exploration loss consumption exceeds budget")
            if self.exploration_fixed_assessment_at <= self.issued_at:
                raise ValueError(
                    "exploration assessment must follow authorization issue"
                )
            if any(
                grant.shared_exploration_loss_budget_id
                != self.exploration_shared_stress_loss_budget_id
                for grant in exploration
            ):
                raise ValueError("exploration grants must share envelope loss budget")
            edge_grants = [
                grant
                for grant in self.lineage_grants
                if grant.grant_kind.value == "EDGE"
            ]
            if edge_grants:
                if not predecessor_present:
                    raise ValueError("existing EDGE exploration requires predecessor")
                expected_certificates = tuple(
                    sorted(grant.grant_certificate_hash for grant in edge_grants)
                )
                if (
                    self.predecessor_active_edge_grant_certificate_hashes
                    != expected_certificates
                    or self.predecessor_target_policy_fingerprint
                    != self.baseline_portfolio_policy_fingerprint
                ):
                    raise ValueError("predecessor EDGE policy/certificates must match")
            elif predecessor_present:
                raise ValueError("first exploration cannot claim a predecessor EDGE")
            if self.exploration_aggregate_gross_cap != exploration_cap:
                raise ValueError(
                    "exploration aggregate cap must equal exploration grants"
                )
            if (
                not any(
                    grant.grant_kind.value == "EDGE" for grant in self.lineage_grants
                )
                and self.portfolio_gross_cap > two_percent
            ):
                raise ValueError(
                    "first broker exploration portfolio cap cannot exceed 2%"
                )
        else:
            if exploration_only_present or not predecessor_present:
                raise ValueError(
                    "RECOVERY requires predecessor and no exploration fields"
                )
            if (
                self.issuer_capability != "governance.recovery.envelope.v1"
                or any(g.grant_kind.value != "EDGE" for g in self.lineage_grants)
                or self.exploration_aggregate_gross_cap != Decimal("0")
            ):
                raise ValueError("RECOVERY cannot create exploration grants")
            if self.portfolio_gross_cap > two_percent or None in (
                self.recovery_inherited_risk_version,
                self.recovery_open_pending_risk_version,
                self.recovery_stage_program_loss_consumption_version,
                self.risk_epoch_started_hash,
                self.recovery_manifest_hash,
            ):
                raise ValueError(
                    "RECOVERY requires 2% cap and inherited risk/loss versions"
                )
            if (
                self.target_portfolio_policy_fingerprint
                != self.predecessor_target_policy_fingerprint
            ):
                raise ValueError("RECOVERY target policy must equal predecessor target")
            expected_certificates = tuple(
                sorted(grant.grant_certificate_hash for grant in self.lineage_grants)
            )
            if (
                self.predecessor_active_edge_grant_certificate_hashes
                != expected_certificates
            ):
                raise ValueError("RECOVERY predecessor certificates must match grants")
        return self


__all__ = ["AuthorizationKind", "CapitalAuthorizationEnvelope"]
