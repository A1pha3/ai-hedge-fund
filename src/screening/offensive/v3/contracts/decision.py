"""Storage-free portfolio proposal and legacy Revision 1 decision contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, model_validator

from .authorization import CapitalAuthorizationEnvelope
from .base import (
    CanonicalModel,
    EvidenceScope,
    ExactInteger,
    ExecutionMode,
    MoneyCents,
    QuantityUnits,
    SchemaVersion,
    Sha256,
    UtcInstant,
    domain_hash,
)
from .capital import (
    CapitalRiskSnapshot,
    CapitalSnapshot,
    ReconciliationLatchState,
    RiskLatchState,
    RiskSnapshotCompleteness,
    RiskSnapshotFreshness,
    StageLossLatchState,
)
from .evidence import EvidenceEnvelope, NonEmptyStr
from .governance import AuthorizationLifecycle, AuthorizationStatus


PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
PositiveExactInt = Annotated[ExactInteger, Field(ge=1)]
NonNegativeExactInt = Annotated[ExactInteger, Field(ge=0)]
PositiveQuantity = Annotated[QuantityUnits, Field(gt=0)]
PositiveCents = Annotated[MoneyCents, Field(gt=0)]
NonNegativeCents = Annotated[MoneyCents, Field(ge=0)]


class DecisionLogicalKey(CanonicalModel):
    """Economic idempotency key shared by every authority/policy epoch."""

    portfolio_id: NonEmptyStr
    signal_session: date
    decision_cycle_id: NonEmptyStr


class SealedOrderLine(CanonicalModel):
    """One fully identified economic order inside an aggregate decision seal."""

    order_line_id: NonEmptyStr
    security_id: NonEmptyStr
    order_action: Literal["entry", "exit"]
    entry_session: date
    exit_session_ordinal: Literal[10]
    exit_policy_version: NonEmptyStr
    sealed_quantity: PositiveInt
    lot_rule_version: NonEmptyStr
    order_type: NonEmptyStr
    limit_price: PositiveDecimal
    worst_case_price: PositiveDecimal
    price_boundary_version: NonEmptyStr
    time_in_force: NonEmptyStr
    worst_case_fee_reserve: NonNegativeDecimal
    worst_case_cash_reserve: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_reserve(self) -> Self:
        required_cash = (
            self.worst_case_price * self.sealed_quantity + self.worst_case_fee_reserve
        )
        if (
            self.order_action == "entry"
            and self.worst_case_cash_reserve < required_cash
        ):
            raise ValueError("cash reserve must cover worst-case entry price and fees")
        return self


class PlanEvidence(EvidenceEnvelope):
    """Producer raw-target evidence; it carries no execution authority."""

    evidence_kind: Literal["plan"]
    portfolio_id: NonEmptyStr
    signal_session: date
    economic_lineage_id: NonEmptyStr
    snapshot_id: NonEmptyStr
    raw_target_fraction: Annotated[Decimal, Field(gt=0, le=1)]
    created_at: UtcInstant

    @model_validator(mode="after")
    def validate_plan_scope(self) -> Self:
        if self.subject_scope is not EvidenceScope.STRATEGY_LINEAGE:
            raise ValueError("plan evidence requires strategy-lineage scope")
        if self.family_id == self.economic_lineage_id:
            raise ValueError("family_id must remain distinct from economic_lineage_id")
        return self


class StageLossExpectedVersion(CanonicalModel):
    """One stage-loss CAS component used by the Capital Gateway."""

    stage_id: NonEmptyStr
    stage_loss_budget_id: NonEmptyStr
    stage_loss_version: PositiveExactInt
    stage_loss_latch: StageLossLatchState


class PortfolioOrderLine(CanonicalModel):
    """One fixed, entry-only order line in a complete portfolio proposal."""

    order_line_id: NonEmptyStr
    security_id: NonEmptyStr
    order_action: Literal["ENTRY"]
    producer_namespace: NonEmptyStr
    family_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    research_program_id: NonEmptyStr
    stage_id: NonEmptyStr
    stage_manifest_hash: Sha256
    grant_id: NonEmptyStr
    grant_certificate_hash: Sha256
    authorization_id: NonEmptyStr
    authorization_version: PositiveExactInt
    plan_evidence: PlanEvidence
    plan_evidence_artifact_hash: Sha256
    plan_payload_content_hash: Sha256
    mode: ExecutionMode
    target_entry_session: date
    exit_session_ordinal: Literal[10]
    sealed_quantity_units: PositiveQuantity
    lot_size_units: PositiveQuantity
    lot_rule_version: NonEmptyStr
    order_type: NonEmptyStr
    limit_price_cents: PositiveCents
    worst_case_price_cents: PositiveCents
    price_boundary_version: NonEmptyStr
    time_in_force: NonEmptyStr
    worst_case_fee_reserve_cents: NonNegativeCents
    worst_case_cash_reserve_cents: PositiveCents

    @model_validator(mode="after")
    def validate_entry_economics_and_provenance(self) -> Self:
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research execution cannot create a portfolio order line")
        if self.family_id == self.economic_lineage_id:
            raise ValueError("family_id must remain distinct from economic_lineage_id")
        if self.sealed_quantity_units % self.lot_size_units != 0:
            raise ValueError("sealed quantity must be an exact whole lot")
        if self.limit_price_cents > self.worst_case_price_cents:
            raise ValueError("limit price cannot exceed worst-case price")
        required_reserve = (
            self.worst_case_price_cents * self.sealed_quantity_units
            + self.worst_case_fee_reserve_cents
        )
        if self.worst_case_cash_reserve_cents != required_reserve:
            raise ValueError(
                "cash reserve must exactly equal worst-case price times quantity "
                "plus fee reserve"
            )

        plan = self.plan_evidence
        if plan.subject_producer != self.producer_namespace:
            raise ValueError("plan evidence producer must match order producer")
        if plan.family_id != self.family_id:
            raise ValueError("plan evidence family must match order family")
        if plan.economic_lineage_id != self.economic_lineage_id:
            raise ValueError("plan evidence lineage must match order lineage")
        if plan.mode is not self.mode:
            raise ValueError("plan evidence mode must match order mode")
        if plan.content_hash() != self.plan_evidence_artifact_hash:
            raise ValueError("plan evidence artifact hash does not match evidence")
        if plan.payload_content_hash != self.plan_payload_content_hash:
            raise ValueError("plan payload content hash does not match evidence")
        if self.target_entry_session <= plan.signal_session:
            raise ValueError("target entry session must follow the signal session")
        return self


class GatewayExpectedVersions(CanonicalModel):
    """Complete CAS precondition bundle for first publication or supersede."""

    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveExactInt
    policy_epoch: PositiveExactInt
    authority_epoch: PositiveExactInt
    risk_epoch: PositiveExactInt
    authorization_id: NonEmptyStr
    authorization_version: PositiveExactInt
    authorization_envelope_hash: Sha256
    authorization_status_version: PositiveExactInt
    authorization_status_hash: Sha256
    evidence_set_merkle_root: Sha256
    entry_fence_hash: Sha256
    entry_fence_version: NonNegativeExactInt
    risk_snapshot_id: NonEmptyStr
    risk_snapshot_payload_hash: Sha256
    capital_version: PositiveExactInt
    capital_stream_version: PositiveExactInt
    writer_fencing_epoch: PositiveExactInt
    stage_loss_expected_versions: Annotated[
        tuple[StageLossExpectedVersion, ...], Field(min_length=1)
    ]
    expected_active_seal_id: NonEmptyStr | None
    expected_active_seal_revision: PositiveExactInt | None
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_cas_bundle(self) -> Self:
        seal_pair = (
            self.expected_active_seal_id,
            self.expected_active_seal_revision,
        )
        if (seal_pair[0] is None) != (seal_pair[1] is None):
            raise ValueError(
                "expected active seal ID/revision must be an all-or-none pair"
            )

        identities = [
            (item.stage_id, item.stage_loss_budget_id)
            for item in self.stage_loss_expected_versions
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("stage loss expected versions must be unique")
        stage_ids = [identity[0] for identity in identities]
        budget_ids = [identity[1] for identity in identities]
        if len(stage_ids) != len(set(stage_ids)) or len(budget_ids) != len(
            set(budget_ids)
        ):
            raise ValueError("stage and stage-loss budget identities must be unique")
        if identities != sorted(identities):
            raise ValueError("stage loss expected versions must use canonical order")
        return self


class PortfolioDecision(CanonicalModel):
    """Complete pure Growth Kernel proposal; it grants no send authority."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.decision.portfolio-proposal.v1"

    logical_key: DecisionLogicalKey
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None
    broker_account_fingerprint: Sha256 | None
    base_currency: NonEmptyStr
    mode: ExecutionMode
    target_entry_session: date
    target_portfolio_policy_fingerprint: Sha256
    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveExactInt
    policy_epoch: PositiveExactInt
    authority_epoch: PositiveExactInt
    risk_epoch: PositiveExactInt
    capital_authorization: CapitalAuthorizationEnvelope
    capital_authorization_artifact_hash: Sha256
    authorization_status: AuthorizationStatus
    authorization_status_artifact_hash: Sha256
    evidence_set_merkle_root: Sha256
    capital_risk_snapshot: CapitalRiskSnapshot
    gateway_expected_versions: GatewayExpectedVersions
    order_lines: Annotated[tuple[PortfolioOrderLine, ...], Field(min_length=1)]
    total_worst_case_cash_reserve_cents: PositiveCents
    decision_cutoff: UtcInstant
    proposal_created_at: UtcInstant
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_portfolio_proposal(self) -> Self:
        self._validate_time_and_risk()
        self._validate_authorization_context()
        self._validate_gateway_versions()
        self._validate_lines_and_reserve()
        return self

    def _validate_time_and_risk(self) -> None:
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research execution cannot create PortfolioDecision")
        if self.decision_cutoff >= self.proposal_created_at:
            raise ValueError("decision cutoff must precede proposal creation")
        if self.logical_key.portfolio_id != self.portfolio_id:
            raise ValueError("logical key portfolio must match decision portfolio")
        if self.target_entry_session <= self.logical_key.signal_session:
            raise ValueError("target entry session must follow signal session")

        risk = self.capital_risk_snapshot
        if not risk.as_of <= self.proposal_created_at < risk.valid_until:
            raise ValueError("capital risk snapshot is not valid at proposal time")
        if risk.freshness is not RiskSnapshotFreshness.FRESH:
            raise ValueError("capital risk snapshot must be fresh")
        if risk.completeness is not RiskSnapshotCompleteness.COMPLETE:
            raise ValueError("capital risk snapshot must be complete")
        if risk.risk_latch is not RiskLatchState.CLEAR:
            raise ValueError("capital risk latch blocks entry")
        if risk.reconciliation_latch is not ReconciliationLatchState.CLEAR:
            raise ValueError("capital reconciliation latch blocks entry")
        if risk.unattributed_risk_cents != 0:
            raise ValueError("unattributed risk blocks entry")

    def _validate_authorization_context(self) -> None:
        authorization = self.capital_authorization
        status = self.authorization_status
        risk = self.capital_risk_snapshot

        if self.mode is ExecutionMode.BROKER_CONFIRMED:
            if (
                self.broker_account_id is None
                or self.broker_account_fingerprint is None
            ):
                raise ValueError("broker mode requires account ID and fingerprint")
        elif self.mode is ExecutionMode.MANUAL_CONFIRMED:
            if (
                self.broker_account_id is None
                or self.broker_account_fingerprint is not None
            ):
                raise ValueError("manual mode requires account ID without fingerprint")
        elif (
            self.broker_account_id is not None
            or self.broker_account_fingerprint is not None
        ):
            raise ValueError("proxy mode cannot bind a broker account")

        bindings = (
            ("portfolio", self.portfolio_id, authorization.portfolio_id),
            ("account", self.broker_account_id, authorization.broker_account_id),
            (
                "account fingerprint",
                self.broker_account_fingerprint,
                authorization.broker_account_fingerprint,
            ),
            ("currency", self.base_currency, authorization.base_currency),
            ("mode", self.mode, authorization.mode),
            (
                "target policy",
                self.target_portfolio_policy_fingerprint,
                authorization.target_portfolio_policy_fingerprint,
            ),
            (
                "policy activation",
                self.policy_activation_hash,
                authorization.policy_activation_hash,
            ),
            ("trust bundle", self.trust_bundle_hash, authorization.trust_bundle_hash),
            ("registry epoch", self.registry_epoch, authorization.registry_epoch),
            ("policy epoch", self.policy_epoch, authorization.policy_epoch),
            ("authority epoch", self.authority_epoch, authorization.authority_epoch),
            ("risk epoch", self.risk_epoch, authorization.risk_epoch),
            (
                "evidence root",
                self.evidence_set_merkle_root,
                authorization.evidence_set_merkle_root,
            ),
        )
        for label, actual, expected in bindings:
            if actual != expected:
                raise ValueError(f"decision {label} does not match authorization")

        if authorization.artifact_hash() != self.capital_authorization_artifact_hash:
            raise ValueError(
                "capital authorization artifact hash does not match envelope"
            )
        if status.artifact_hash() != self.authorization_status_artifact_hash:
            raise ValueError("authorization status artifact hash does not match status")
        if status.status is not AuthorizationLifecycle.ACTIVE:
            raise ValueError("authorization status must be ACTIVE")
        if (
            not status.as_of
            <= self.proposal_created_at
            < status.authorization_expires_at
        ):
            raise ValueError("authorization status is not current at proposal time")

        status_bindings = (
            ("portfolio", self.portfolio_id, status.portfolio_id),
            ("account", self.broker_account_id, status.broker_account_id),
            (
                "account fingerprint",
                self.broker_account_fingerprint,
                status.broker_account_fingerprint,
            ),
            ("mode", self.mode, status.mode),
            (
                "authorization ID",
                authorization.authorization_id,
                status.authorization_id,
            ),
            (
                "authorization version",
                authorization.authorization_version,
                status.authorization_version,
            ),
            (
                "authorization envelope hash",
                self.capital_authorization_artifact_hash,
                status.authorization_envelope_hash,
            ),
            (
                "evidence root",
                self.evidence_set_merkle_root,
                status.evidence_set_merkle_root,
            ),
            (
                "policy activation",
                self.policy_activation_hash,
                status.policy_activation_hash,
            ),
            ("trust bundle", self.trust_bundle_hash, status.trust_bundle_hash),
            ("registry epoch", self.registry_epoch, status.registry_epoch),
            ("policy epoch", self.policy_epoch, status.policy_epoch),
            ("authority epoch", self.authority_epoch, status.authority_epoch),
            ("risk epoch", self.risk_epoch, status.risk_epoch),
        )
        for label, actual, expected in status_bindings:
            if actual != expected:
                raise ValueError(
                    f"decision {label} does not match authorization status"
                )

        risk_bindings = (
            ("portfolio", self.portfolio_id, risk.portfolio_id),
            ("account", self.broker_account_id, risk.broker_account_id),
            ("currency", self.base_currency, risk.base_currency),
            ("mode", self.mode, risk.mode),
            (
                "policy activation",
                self.policy_activation_hash,
                risk.policy_activation_hash,
            ),
            ("registry epoch", self.registry_epoch, risk.registry_epoch),
            ("policy epoch", self.policy_epoch, risk.policy_epoch),
            ("authority epoch", self.authority_epoch, risk.authority_epoch),
            ("risk epoch", self.risk_epoch, risk.risk_epoch),
            ("authorization ID", authorization.authorization_id, risk.authorization_id),
            (
                "authorization version",
                authorization.authorization_version,
                risk.authorization_version,
            ),
        )
        for label, actual, expected in risk_bindings:
            if actual != expected:
                raise ValueError(
                    f"decision {label} does not match capital risk snapshot"
                )

    def _validate_gateway_versions(self) -> None:
        expected = self.gateway_expected_versions
        authorization = self.capital_authorization
        status = self.authorization_status
        risk = self.capital_risk_snapshot
        bindings = (
            ("policy", expected.policy_activation_hash, self.policy_activation_hash),
            ("trust", expected.trust_bundle_hash, self.trust_bundle_hash),
            ("registry", expected.registry_epoch, self.registry_epoch),
            ("policy", expected.policy_epoch, self.policy_epoch),
            ("authority", expected.authority_epoch, self.authority_epoch),
            ("risk", expected.risk_epoch, self.risk_epoch),
            (
                "authorization ID",
                expected.authorization_id,
                authorization.authorization_id,
            ),
            (
                "authorization version",
                expected.authorization_version,
                authorization.authorization_version,
            ),
            (
                "authorization envelope",
                expected.authorization_envelope_hash,
                self.capital_authorization_artifact_hash,
            ),
            (
                "status version",
                expected.authorization_status_version,
                status.status_version,
            ),
            (
                "status hash",
                expected.authorization_status_hash,
                self.authorization_status_artifact_hash,
            ),
            (
                "evidence",
                expected.evidence_set_merkle_root,
                self.evidence_set_merkle_root,
            ),
            ("fence", expected.entry_fence_version, status.entry_fence_version),
            ("risk snapshot", expected.risk_snapshot_id, risk.risk_snapshot_id),
            (
                "risk snapshot",
                expected.risk_snapshot_payload_hash,
                risk.payload_content_hash,
            ),
            ("capital", expected.capital_version, risk.capital_version),
            ("fencing", expected.writer_fencing_epoch, risk.writer_fencing_epoch),
        )
        for label, actual, required in bindings:
            if actual != required:
                raise ValueError(f"gateway {label} binding does not match proposal")

    def _validate_lines_and_reserve(self) -> None:
        authorization = self.capital_authorization
        line_ids = [line.order_line_id for line in self.order_lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("portfolio order line IDs must be unique")
        security_ids = [line.security_id for line in self.order_lines]
        if len(security_ids) != len(set(security_ids)):
            raise ValueError("portfolio order securities must be unique")
        canonical = sorted(
            self.order_lines,
            key=lambda line: (
                line.producer_namespace,
                line.research_program_id,
                line.economic_lineage_id,
                line.stage_id,
                line.security_id,
                line.order_line_id,
            ),
        )
        if list(self.order_lines) != canonical:
            raise ValueError("portfolio order lines must use canonical order")
        reserve = sum(line.worst_case_cash_reserve_cents for line in self.order_lines)
        if reserve != self.total_worst_case_cash_reserve_cents:
            raise ValueError("portfolio total reserve must exactly equal line reserves")

        grants = {grant.grant_id: grant for grant in authorization.lineage_grants}
        used_stage_ids: set[str] = set()
        for line in self.order_lines:
            if line.authorization_id != authorization.authorization_id:
                raise ValueError("order authorization ID does not match envelope")
            if line.authorization_version != authorization.authorization_version:
                raise ValueError("order authorization version does not match envelope")
            if line.mode is not self.mode:
                raise ValueError("order mode does not match decision mode")
            if line.target_entry_session != self.target_entry_session:
                raise ValueError("order target entry session does not match decision")
            plan = line.plan_evidence
            if plan.portfolio_id != self.portfolio_id:
                raise ValueError("plan portfolio does not match decision portfolio")
            if plan.signal_session != self.logical_key.signal_session:
                raise ValueError("plan signal session does not match logical key")
            if plan.policy_epoch != self.policy_epoch:
                raise ValueError("plan policy epoch does not match decision policy")
            if (
                plan.available_at > self.decision_cutoff
                or plan.created_at > self.decision_cutoff
            ):
                raise ValueError(
                    "plan evidence must be available by decision cutoff for PIT use"
                )

            grant = grants.get(line.grant_id)
            if grant is None:
                raise ValueError("order grant is not present in authorization envelope")
            grant_bindings = (
                (
                    "grant certificate",
                    line.grant_certificate_hash,
                    grant.grant_certificate_hash,
                ),
                ("producer", line.producer_namespace, grant.subject_producer),
                ("family", line.family_id, grant.family_id),
                ("lineage", line.economic_lineage_id, grant.economic_lineage_id),
                ("program", line.research_program_id, grant.research_program_id),
                ("stage", line.stage_id, grant.stage_id),
                ("stage manifest", line.stage_manifest_hash, grant.stage_manifest_hash),
                ("behavior", plan.behavior_fingerprint, grant.behavior_fingerprint),
                ("execution", plan.execution_version, grant.execution_version),
                ("cost", plan.cost_version, grant.cost_version),
            )
            for label, actual, required in grant_bindings:
                if actual != required:
                    raise ValueError(
                        f"order {label} does not match authorization grant"
                    )
            used_stage_ids.add(line.stage_id)

        expected_by_stage = {
            item.stage_id: item
            for item in self.gateway_expected_versions.stage_loss_expected_versions
        }
        if set(expected_by_stage) != used_stage_ids:
            raise ValueError(
                "gateway stage version set must exactly match order stages"
            )
        risk_latches = {
            latch.stage_id: latch
            for latch in self.capital_risk_snapshot.stage_loss_latches
        }
        for line in self.order_lines:
            grant = grants[line.grant_id]
            expected = expected_by_stage[line.stage_id]
            latch = risk_latches.get(line.stage_id)
            if latch is None:
                raise ValueError("capital risk snapshot lacks order stage loss latch")
            stage_bindings = (
                (
                    "stage loss budget",
                    expected.stage_loss_budget_id,
                    grant.stage_loss_budget_id,
                ),
                (
                    "stage loss version",
                    expected.stage_loss_version,
                    grant.stage_loss_version,
                ),
                (
                    "stage loss budget",
                    latch.stage_loss_budget_id,
                    grant.stage_loss_budget_id,
                ),
                (
                    "stage loss version",
                    latch.stage_loss_version,
                    grant.stage_loss_version,
                ),
                ("stage loss latch", expected.stage_loss_latch, latch.state),
            )
            for label, actual, required in stage_bindings:
                if actual != required:
                    raise ValueError(f"{label} does not match authorized order stage")
            if expected.stage_loss_latch is not StageLossLatchState.CLEAR:
                raise ValueError("stage loss latch blocks entry")

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, self.schema_major, self)


class DecisionInput(CanonicalModel):
    """Complete kernel output economics before writer-owned seal identity."""

    plan_evidence: PlanEvidence
    capital_snapshot: CapitalSnapshot
    target_portfolio_policy_fingerprint: Sha256
    evidence_set_merkle_root: Sha256
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    order_lines: Annotated[tuple[SealedOrderLine, ...], Field(min_length=1)]
    created_at: UtcInstant
    deadline: UtcInstant
    idempotency_key: DecisionLogicalKey

    @model_validator(mode="after")
    def validate_decision_input(self) -> Self:
        if self.created_at > self.deadline:
            raise ValueError("decision deadline must be at or after created_at")
        if self.plan_evidence.available_at > self.created_at:
            raise ValueError("plan evidence must be available before decision creation")
        if self.plan_evidence.created_at > self.created_at:
            raise ValueError("plan evidence cannot be created after the decision")
        capital = self.capital_snapshot
        if capital.as_of > self.created_at:
            raise ValueError("capital snapshot as_of cannot be after decision creation")
        if capital.portfolio_id != self.plan_evidence.portfolio_id:
            raise ValueError("capital portfolio must match plan portfolio")
        if capital.mode is not self.plan_evidence.mode:
            raise ValueError("capital mode must match plan mode")
        if capital.authority_epoch != self.authority_epoch:
            raise ValueError(
                "capital authority epoch must match decision authority epoch"
            )
        if capital.risk_epoch != self.risk_epoch:
            raise ValueError("capital risk epoch must match decision risk epoch")
        expected_key = (
            self.plan_evidence.portfolio_id,
            self.plan_evidence.signal_session,
            self.authority_epoch,
        )
        actual_key = (
            self.idempotency_key.portfolio_id,
            self.idempotency_key.signal_session,
            self.idempotency_key.authority_epoch,
        )
        if actual_key != expected_key:
            raise ValueError(
                "idempotency key must match plan portfolio/session and authority epoch"
            )
        order_line_ids = [line.order_line_id for line in self.order_lines]
        if len(order_line_ids) != len(set(order_line_ids)):
            raise ValueError("order line IDs must be unique within a decision input")
        return self


class CapitalAuthorizationBinding(CanonicalModel):
    """Minimal reference which a seal writer must re-fetch and re-verify."""

    capital_authorization_id: NonEmptyStr
    authorization_version: PositiveInt
    evidence_set_merkle_root: Sha256
    economic_lineage_id: NonEmptyStr
    family_id: NonEmptyStr
    mode: ExecutionMode
    target_portfolio_policy_fingerprint: Sha256

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.family_id == self.economic_lineage_id:
            raise ValueError("family_id must remain distinct from economic_lineage_id")
        return self


class PublishDecisionCommand(CanonicalModel):
    """Request seal publication without a seal identity or authority self-claim."""

    decision: DecisionInput
    authorization: CapitalAuthorizationBinding

    @model_validator(mode="after")
    def validate_authorization_binding(self) -> Self:
        plan = self.decision.plan_evidence
        binding = self.authorization
        if plan.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError(
                "research reconstruction cannot publish an executable decision"
            )
        if binding.mode is not plan.mode:
            raise ValueError("authorization mode must match decision mode")
        if binding.economic_lineage_id != plan.economic_lineage_id:
            raise ValueError("authorization lineage must match decision lineage")
        if binding.family_id != plan.family_id:
            raise ValueError("authorization family must match plan family")
        if binding.evidence_set_merkle_root != self.decision.evidence_set_merkle_root:
            raise ValueError(
                "authorization evidence root must match decision evidence root"
            )
        if (
            binding.target_portfolio_policy_fingerprint
            != self.decision.target_portfolio_policy_fingerprint
        ):
            raise ValueError(
                "authorization target policy fingerprint must match decision policy fingerprint"
            )
        return self


class DecisionSealBinding(CanonicalModel):
    """Exact capital, policy, and authorization truth consumed by a seal."""

    publish_command: PublishDecisionCommand
    publish_command_content_hash: Sha256
    portfolio_id: NonEmptyStr
    capital_snapshot_id: NonEmptyStr
    capital_version: PositiveInt
    capital_stream_version: PositiveInt
    capital_payload_content_hash: Sha256
    target_portfolio_policy_fingerprint: Sha256
    capital_authorization_id: NonEmptyStr
    authorization_version: PositiveInt
    evidence_set_merkle_root: Sha256
    family_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    mode: ExecutionMode
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.family_id == self.economic_lineage_id:
            raise ValueError("family_id must remain distinct from economic_lineage_id")

        command = self.publish_command
        decision = command.decision
        capital = decision.capital_snapshot
        authorization = command.authorization
        plan = decision.plan_evidence
        expected_fields = {
            "publish_command_content_hash": command.content_hash(),
            "portfolio_id": plan.portfolio_id,
            "capital_snapshot_id": capital.capital_snapshot_id,
            "capital_version": capital.capital_version,
            "capital_stream_version": capital.stream_version,
            "capital_payload_content_hash": capital.payload_content_hash,
            "target_portfolio_policy_fingerprint": (
                decision.target_portfolio_policy_fingerprint
            ),
            "capital_authorization_id": authorization.capital_authorization_id,
            "authorization_version": authorization.authorization_version,
            "evidence_set_merkle_root": authorization.evidence_set_merkle_root,
            "family_id": authorization.family_id,
            "economic_lineage_id": authorization.economic_lineage_id,
            "mode": authorization.mode,
            "authority_epoch": decision.authority_epoch,
            "risk_epoch": decision.risk_epoch,
        }
        for field_name, expected in expected_fields.items():
            if getattr(self, field_name) != expected:
                raise ValueError(
                    f"command binding {field_name} must match embedded publish command"
                )
        return self

    @classmethod
    def from_command(cls, command: PublishDecisionCommand) -> Self:
        """Derive one deterministic binding after strict recursive reconstruction."""

        validated = PublishDecisionCommand.model_validate(
            command.model_dump(mode="python", round_trip=True),
            strict=True,
        )
        decision = validated.decision
        capital = decision.capital_snapshot
        authorization = validated.authorization
        plan = decision.plan_evidence
        return cls(
            publish_command=validated,
            publish_command_content_hash=validated.content_hash(),
            portfolio_id=plan.portfolio_id,
            capital_snapshot_id=capital.capital_snapshot_id,
            capital_version=capital.capital_version,
            capital_stream_version=capital.stream_version,
            capital_payload_content_hash=capital.payload_content_hash,
            target_portfolio_policy_fingerprint=(
                decision.target_portfolio_policy_fingerprint
            ),
            capital_authorization_id=authorization.capital_authorization_id,
            authorization_version=authorization.authorization_version,
            evidence_set_merkle_root=authorization.evidence_set_merkle_root,
            family_id=authorization.family_id,
            economic_lineage_id=authorization.economic_lineage_id,
            mode=authorization.mode,
            authority_epoch=decision.authority_epoch,
            risk_epoch=decision.risk_epoch,
        )


class _DecisionProjection(EvidenceEnvelope):
    """Shared economics for live and gateway-ineligible decision projections."""

    portfolio_id: NonEmptyStr
    signal_session: date
    economic_lineage_id: NonEmptyStr
    snapshot_id: NonEmptyStr
    evidence_set_merkle_root: Sha256
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    order_lines: Annotated[tuple[SealedOrderLine, ...], Field(min_length=1)]
    created_at: UtcInstant
    deadline: UtcInstant
    idempotency_key: DecisionLogicalKey

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.subject_scope is not EvidenceScope.STRATEGY_LINEAGE:
            raise ValueError("decision projection requires strategy-lineage scope")
        if self.family_id == self.economic_lineage_id:
            raise ValueError("family_id must remain distinct from economic_lineage_id")
        if self.created_at > self.deadline:
            raise ValueError("decision deadline must be at or after created_at")
        if self.available_at > self.created_at:
            raise ValueError("available_at must be at or before created_at")
        expected_key = (
            self.portfolio_id,
            self.signal_session,
            self.authority_epoch,
        )
        actual_key = (
            self.idempotency_key.portfolio_id,
            self.idempotency_key.signal_session,
            self.idempotency_key.authority_epoch,
        )
        if actual_key != expected_key:
            raise ValueError(
                "idempotency key must match portfolio/session/authority epoch"
            )
        order_line_ids = [line.order_line_id for line in self.order_lines]
        if len(order_line_ids) != len(set(order_line_ids)):
            raise ValueError("order line IDs must be unique within a decision")
        return self


class DecisionSeal(_DecisionProjection):
    """Immutable active revision of an executable, authorization-bound plan."""

    decision_kind: Literal["decision_seal"]
    seal_id: NonEmptyStr
    active_seal_id: NonEmptyStr
    seal_revision: PositiveInt
    capital_authorization_id: NonEmptyStr
    authorization_version: PositiveInt
    command_binding: DecisionSealBinding

    @model_validator(mode="after")
    def validate_active_revision(self) -> Self:
        if self.active_seal_id != self.seal_id:
            raise ValueError("active_seal_id must identify this active seal revision")
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research reconstruction cannot create a DecisionSeal")
        binding_matches = (
            self.command_binding.portfolio_id == self.portfolio_id
            and self.command_binding.mode is self.mode
            and self.command_binding.authority_epoch == self.authority_epoch
            and self.command_binding.risk_epoch == self.risk_epoch
            and self.command_binding.family_id == self.family_id
            and self.command_binding.economic_lineage_id == self.economic_lineage_id
            and self.command_binding.capital_authorization_id
            == self.capital_authorization_id
            and self.command_binding.authorization_version == self.authorization_version
            and self.command_binding.evidence_set_merkle_root
            == self.evidence_set_merkle_root
        )
        if not binding_matches:
            raise ValueError("command binding must match the DecisionSeal projection")

        command = self.command_binding.publish_command
        decision = command.decision
        plan = decision.plan_evidence
        authorization = command.authorization
        expected_fields = {
            "subject_scope": plan.subject_scope,
            "subject_producer": plan.subject_producer,
            "family_id": plan.family_id,
            "strategy_semver": plan.strategy_semver,
            "behavior_fingerprint": plan.behavior_fingerprint,
            "policy_epoch": plan.policy_epoch,
            "execution_version": plan.execution_version,
            "cost_version": plan.cost_version,
            "effective_at": plan.effective_at,
            "observed_at": plan.observed_at,
            "available_at": plan.available_at,
            "mode": plan.mode,
            "schema_major": plan.schema_major,
            "portfolio_id": plan.portfolio_id,
            "signal_session": plan.signal_session,
            "economic_lineage_id": plan.economic_lineage_id,
            "snapshot_id": plan.snapshot_id,
            "evidence_set_merkle_root": decision.evidence_set_merkle_root,
            "authority_epoch": decision.authority_epoch,
            "risk_epoch": decision.risk_epoch,
            "order_lines": decision.order_lines,
            "created_at": decision.created_at,
            "deadline": decision.deadline,
            "idempotency_key": decision.idempotency_key,
            "capital_authorization_id": authorization.capital_authorization_id,
            "authorization_version": authorization.authorization_version,
        }
        for field_name, expected in expected_fields.items():
            if getattr(self, field_name) != expected:
                raise ValueError(
                    f"DecisionSeal {field_name} must match embedded publish command"
                )
        return self

    @classmethod
    def from_command(
        cls,
        command: PublishDecisionCommand,
        *,
        evidence_id: NonEmptyStr,
        seal_id: NonEmptyStr,
        seal_revision: int,
        source_authority: NonEmptyStr,
        payload_content_hash: Sha256,
    ) -> Self:
        """Build a projection only from one validated publish command."""

        validated = PublishDecisionCommand.model_validate(
            command.model_dump(mode="python", round_trip=True),
            strict=True,
        )
        decision = validated.decision
        plan = decision.plan_evidence
        authorization = validated.authorization
        return cls(
            evidence_id=evidence_id,
            subject_scope=plan.subject_scope,
            subject_producer=plan.subject_producer,
            family_id=plan.family_id,
            strategy_semver=plan.strategy_semver,
            behavior_fingerprint=plan.behavior_fingerprint,
            policy_epoch=plan.policy_epoch,
            execution_version=plan.execution_version,
            cost_version=plan.cost_version,
            effective_at=plan.effective_at,
            observed_at=plan.observed_at,
            available_at=plan.available_at,
            mode=plan.mode,
            source_authority=source_authority,
            payload_content_hash=payload_content_hash,
            schema_major=plan.schema_major,
            decision_kind="decision_seal",
            seal_id=seal_id,
            active_seal_id=seal_id,
            seal_revision=seal_revision,
            portfolio_id=plan.portfolio_id,
            signal_session=plan.signal_session,
            economic_lineage_id=plan.economic_lineage_id,
            snapshot_id=plan.snapshot_id,
            evidence_set_merkle_root=decision.evidence_set_merkle_root,
            authority_epoch=decision.authority_epoch,
            risk_epoch=decision.risk_epoch,
            order_lines=decision.order_lines,
            created_at=decision.created_at,
            deadline=decision.deadline,
            idempotency_key=decision.idempotency_key,
            capital_authorization_id=(authorization.capital_authorization_id),
            authorization_version=authorization.authorization_version,
            command_binding=DecisionSealBinding.from_command(validated),
        )


class ShadowDecision(_DecisionProjection):
    """Non-executable decision projection with a gateway-rejecting discriminator."""

    decision_kind: Literal["shadow_decision"]
    shadow_decision_id: NonEmptyStr
    gateway_acceptable: Literal[False]


class ExecutionPermit(CanonicalModel):
    """One bounded gateway permit which may only cancel or shrink a seal."""

    permit_id: NonEmptyStr
    active_seal_id: NonEmptyStr
    seal_revision: PositiveInt
    order_line_id: NonEmptyStr
    capital_authorization_id: NonEmptyStr
    authorization_version: PositiveInt
    evidence_set_merkle_root: Sha256
    mode: ExecutionMode
    sealed_mode: ExecutionMode
    capital_authorization_mode: ExecutionMode
    permitted_quantity: NonNegativeInt
    sealed_quantity: PositiveInt
    capital_version: PositiveInt
    risk_snapshot_id: NonEmptyStr
    fencing_epoch: PositiveInt
    permit_nonce: NonEmptyStr
    deadline: UtcInstant

    @model_validator(mode="after")
    def shrink_only(self) -> Self:
        if self.permitted_quantity > self.sealed_quantity:
            raise ValueError("permit may only shrink sealed quantity")
        if not (self.mode is self.sealed_mode is self.capital_authorization_mode):
            raise ValueError(
                "permit mode must match sealed mode and capital authorization mode"
            )
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError(
                "research reconstruction cannot receive an ExecutionPermit"
            )
        return self


__all__ = [
    "CapitalAuthorizationBinding",
    "DecisionSealBinding",
    "DecisionInput",
    "DecisionLogicalKey",
    "DecisionSeal",
    "ExecutionPermit",
    "GatewayExpectedVersions",
    "PlanEvidence",
    "PortfolioDecision",
    "PortfolioOrderLine",
    "PublishDecisionCommand",
    "SealedOrderLine",
    "ShadowDecision",
    "StageLossExpectedVersion",
]
