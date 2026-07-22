"""Immutable plan, decision-seal, shadow-decision, and permit contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import CanonicalModel, EvidenceScope, ExecutionMode, Sha256, UtcInstant
from .capital import CapitalSnapshot
from .evidence import EvidenceEnvelope, NonEmptyStr


PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]


class DecisionLogicalKey(CanonicalModel):
    """The exact logical idempotency key mandated by design §10.1."""

    portfolio_id: NonEmptyStr
    signal_session: date
    authority_epoch: PositiveInt


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
            self.worst_case_price * self.sealed_quantity
            + self.worst_case_fee_reserve
        )
        if self.order_action == "entry" and self.worst_case_cash_reserve < required_cash:
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
            raise ValueError("capital authority epoch must match decision authority epoch")
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
            raise ValueError("research reconstruction cannot publish an executable decision")
        if binding.mode is not plan.mode:
            raise ValueError("authorization mode must match decision mode")
        if binding.economic_lineage_id != plan.economic_lineage_id:
            raise ValueError("authorization lineage must match decision lineage")
        if binding.family_id != plan.family_id:
            raise ValueError("authorization family must match plan family")
        if binding.evidence_set_merkle_root != self.decision.evidence_set_merkle_root:
            raise ValueError("authorization evidence root must match decision evidence root")
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
            raise ValueError("idempotency key must match portfolio/session/authority epoch")
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
            and self.command_binding.economic_lineage_id
            == self.economic_lineage_id
            and self.command_binding.capital_authorization_id
            == self.capital_authorization_id
            and self.command_binding.authorization_version
            == self.authorization_version
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
            capital_authorization_id=(
                authorization.capital_authorization_id
            ),
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
        if not (
            self.mode is self.sealed_mode is self.capital_authorization_mode
        ):
            raise ValueError(
                "permit mode must match sealed mode and capital authorization mode"
            )
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research reconstruction cannot receive an ExecutionPermit")
        return self


__all__ = [
    "CapitalAuthorizationBinding",
    "DecisionSealBinding",
    "DecisionInput",
    "DecisionLogicalKey",
    "DecisionSeal",
    "ExecutionPermit",
    "PlanEvidence",
    "PublishDecisionCommand",
    "SealedOrderLine",
    "ShadowDecision",
]
