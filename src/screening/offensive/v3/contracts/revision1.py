"""Explicit compatibility surface for frozen Revision 1 decision contracts.

These names are intentionally absent from the current contracts package surface.
They remain available only so Revision 1 artifacts can be reconstructed and
verified without changing their authority-epoch idempotency semantics.
"""

from __future__ import annotations

from base64 import b64decode, b64encode
import binascii
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self, runtime_checkable

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    model_validator,
)

from .revision1_primitives import (
    CanonicalModel,
    EvidenceScope,
    ExecutionMode,
    Sha256,
    UtcInstant,
    canonical_json_bytes,
    content_hash,
)


PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]


class ArtifactKind(StrEnum):
    """Exact Revision 1 signed-artifact discriminators from ``dccb76c5``."""

    SNAPSHOT = "snapshot"
    SIGNAL = "signal"
    OUTCOME = "outcome"
    PLAN = "plan"
    EDGE_AUTHORIZATION = "edge"
    EXPLORATION_AUTHORIZATION = "exploration"
    DECISION_SEAL = "decision_seal"
    SHADOW_DECISION = "shadow_decision"
    EXECUTION_PERMIT = "execution_permit"


def _decode_canonical_base64(
    value: str,
    *,
    expected_length: int,
    label: str,
) -> bytes:
    try:
        decoded = b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{label} must be canonical base64") from exc
    if len(decoded) != expected_length:
        raise ValueError(f"{label} must decode to {expected_length} bytes")
    if b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{label} must be canonical base64")
    return decoded


def _validate_signature(value: str) -> str:
    _decode_canonical_base64(value, expected_length=64, label="signature")
    return value


Signature = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_validate_signature),
]


class Capability(CanonicalModel):
    """Frozen Revision 1 capability request and registry-grant shape."""

    artifact: ArtifactKind
    namespace: NonEmptyStr
    mode: ExecutionMode
    schema_major: Annotated[int, Field(ge=1)]
    capability_version: NonEmptyStr
    scope: NonEmptyStr
    valid_from: UtcInstant
    valid_until: UtcInstant
    revoked_at: UtcInstant | None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.schema_major != 1:
            raise ValueError("unsupported Revision 1 capability schema major")
        if self.valid_until <= self.valid_from:
            raise ValueError("capability valid_until must be after valid_from")
        return self

    def context(self) -> tuple[ArtifactKind, str, ExecutionMode, int, str, str]:
        return (
            self.artifact,
            self.namespace,
            self.mode,
            self.schema_major,
            self.capability_version,
            self.scope,
        )


class SignedEnvelope(BaseModel):
    """Frozen Revision 1 protected wire; later majors and artifacts are invalid."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    issuer_id: NonEmptyStr
    key_id: NonEmptyStr
    schema_major: Annotated[int, Field(ge=1)]
    artifact: ArtifactKind
    namespace: NonEmptyStr
    mode: ExecutionMode
    capability_version: NonEmptyStr
    capability_scope: NonEmptyStr
    payload_hash: Sha256
    payload: bytes
    signature: Signature

    @model_validator(mode="after")
    def validate_schema_major(self) -> Self:
        if self.schema_major != 1:
            raise ValueError("unsupported Revision 1 signed-envelope schema major")
        return self

    def _protected_signing_input(self) -> bytes:
        return canonical_json_bytes(
            {
                "artifact": self.artifact,
                "capability_scope": self.capability_scope,
                "capability_version": self.capability_version,
                "issuer_id": self.issuer_id,
                "key_id": self.key_id,
                "mode": self.mode,
                "namespace": self.namespace,
                "payload": b64encode(self.payload).decode("ascii"),
                "payload_hash": self.payload_hash,
                "schema_major": self.schema_major,
            }
        )


class VerifiedIssuer(CanonicalModel):
    """Exact minimal Revision 1 verifier result."""

    issuer_id: NonEmptyStr
    capability: Capability


@runtime_checkable
class CapabilityVerifier(Protocol):
    """Frozen Revision 1 verification port."""

    def verify(
        self,
        signed: SignedEnvelope,
        required: Capability,
        *,
        verification_time: datetime,
    ) -> VerifiedIssuer: ...


class EvidenceEnvelope(CanonicalModel):
    """Frozen Revision 1 evidence shape, before provider release was added."""

    evidence_id: NonEmptyStr
    subject_scope: EvidenceScope
    subject_producer: NonEmptyStr
    family_id: NonEmptyStr | None
    strategy_semver: NonEmptyStr
    behavior_fingerprint: Sha256
    policy_epoch: PositiveInt
    execution_version: NonEmptyStr
    cost_version: NonEmptyStr
    effective_at: UtcInstant
    observed_at: UtcInstant
    available_at: UtcInstant
    mode: ExecutionMode
    source_authority: NonEmptyStr
    payload_content_hash: Sha256
    schema_major: int

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.schema_major != 1:
            raise ValueError("unsupported Revision 1 evidence schema major")
        if self.observed_at > self.available_at:
            raise ValueError("observed_at must be at or before available_at")
        if self.subject_scope is EvidenceScope.GLOBAL and self.family_id is not None:
            raise ValueError("GLOBAL evidence requires family_id=None")
        if (
            self.subject_scope is EvidenceScope.STRATEGY_LINEAGE
            and self.family_id is None
        ):
            raise ValueError("STRATEGY_LINEAGE evidence requires a nonempty family_id")
        return self


class SnapshotEvidence(EvidenceEnvelope):
    evidence_kind: Literal["snapshot"]


class PlanEvidence(EvidenceEnvelope):
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


AllowedCapitalTier = Literal[2, 5, 10]


class EdgeAuthorization(EvidenceEnvelope):
    """Frozen Revision 1 independent edge authorization."""

    authorization_kind: Literal["edge"]
    authorization_version: PositiveInt
    economic_lineage_id: NonEmptyStr
    research_program_id: NonEmptyStr
    baseline_portfolio_policy_fingerprint: Sha256
    target_portfolio_policy_fingerprint: Sha256
    evidence_as_of: UtcInstant
    evidence_set_merkle_root: Sha256
    issued_at: UtcInstant
    expires_at: UtcInstant
    max_capital_tier: AllowedCapitalTier
    issuer_id: NonEmptyStr
    issuer_capability: NonEmptyStr
    trial_id: NonEmptyStr
    trial_manifest_hash: Sha256
    statistical_analysis_plan_hash: Sha256
    assessment_result_hash: Sha256
    attempt_ledger_checkpoint_hash: Sha256
    alpha_sample_consumption_id: NonEmptyStr
    authorization_payload_hash: Sha256

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError(
                "research reconstruction cannot receive capital authorization"
            )
        if self.available_at > self.evidence_as_of:
            raise ValueError("available_at must be at or before evidence_as_of")
        if self.evidence_as_of > self.issued_at:
            raise ValueError("evidence_as_of must be at or before issued_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if self.subject_scope is not EvidenceScope.STRATEGY_LINEAGE:
            raise ValueError("edge authorization requires strategy-lineage scope")
        if self.family_id == self.economic_lineage_id:
            raise ValueError("family_id must remain distinct from economic_lineage_id")
        return self


class ExplorationAuthorization(EvidenceEnvelope):
    """Frozen Revision 1 one-shot broker exploration authorization."""

    authorization_kind: Literal["exploration"]
    authorization_version: PositiveInt
    economic_lineage_id: NonEmptyStr
    research_program_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    evidence_set_merkle_root: Sha256
    issued_at: UtcInstant
    expires_at: UtcInstant
    max_capital_tier: Literal[2]
    portfolio_gross_risk_cap: Annotated[Decimal, Field(gt=0, le=Decimal("0.02"))]
    stress_loss_budget: PositiveDecimal
    issuer_id: NonEmptyStr
    issuer_capability: NonEmptyStr
    trial_id: NonEmptyStr
    trial_manifest_hash: Sha256
    one_shot: Literal[True]

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        if self.mode is not ExecutionMode.BROKER_CONFIRMED:
            raise ValueError("exploration authorization requires broker-confirmed mode")
        if self.available_at > self.issued_at:
            raise ValueError("available_at must be at or before issued_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if self.subject_scope is not EvidenceScope.STRATEGY_LINEAGE:
            raise ValueError(
                "exploration authorization requires strategy-lineage scope"
            )
        if self.family_id == self.economic_lineage_id:
            raise ValueError("family_id must remain distinct from economic_lineage_id")
        return self


AuthorizationUnion = Annotated[
    EdgeAuthorization | ExplorationAuthorization,
    Field(discriminator="authorization_kind"),
]


class CapitalAuthorization(RootModel[AuthorizationUnion]):
    """Frozen Revision 1 discriminated authorization read-port payload."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        revalidate_instances="always",
    )


class PositionState(StrEnum):
    """Frozen Revision 1 position states."""

    OPEN = "OPEN"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    LEGAL_TERMINAL = "LEGAL_TERMINAL"


class PositionSnapshot(CanonicalModel):
    """Frozen Revision 1 capital position dependency."""

    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    security_id: NonEmptyStr
    state: PositionState
    settled_quantity: NonNegativeInt
    tradable_quantity: NonNegativeInt
    share_receivable_quantity: NonNegativeInt
    cost_basis: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_quantities(self) -> Self:
        if self.tradable_quantity > self.settled_quantity:
            raise ValueError("tradable quantity cannot exceed settled quantity")
        return self


class CapitalSnapshot(CanonicalModel):
    """Frozen Revision 1 capital snapshot dependency."""

    capital_snapshot_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    capital_version: PositiveInt
    stream_version: PositiveInt
    mode: ExecutionMode
    as_of: UtcInstant
    cash: Decimal
    nav: NonNegativeDecimal
    gross_exposure: NonNegativeDecimal
    high_water_mark: NonNegativeDecimal
    positions: tuple[PositionSnapshot, ...]
    payload_content_hash: Sha256


@runtime_checkable
class CapitalViewPort(Protocol):
    """Frozen Revision 1 capital read port."""

    def snapshot(self, portfolio_id: str, as_of: datetime) -> CapitalSnapshot: ...


@runtime_checkable
class EvidenceQueryPort(Protocol):
    """Frozen Revision 1 read-port annotations."""

    def snapshot(self, evidence_id: str) -> SnapshotEvidence: ...

    def authorization(
        self,
        authorization_id: str,
    ) -> CapitalAuthorization: ...


class DecisionLogicalKey(CanonicalModel):
    """Frozen Revision 1 idempotency key, including its authority epoch."""

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
            self.worst_case_price * self.sealed_quantity + self.worst_case_fee_reserve
        )
        if (
            self.order_action == "entry"
            and self.worst_case_cash_reserve < required_cash
        ):
            raise ValueError("cash reserve must cover worst-case entry price and fees")
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
            capital_authorization_id=authorization.capital_authorization_id,
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


@runtime_checkable
class SealWriterPort(Protocol):
    def publish(self, command: PublishDecisionCommand) -> DecisionSeal: ...


__all__ = [
    "AllowedCapitalTier",
    "ArtifactKind",
    "AuthorizationUnion",
    "CapitalAuthorizationBinding",
    "CapitalAuthorization",
    "CapitalSnapshot",
    "CapitalViewPort",
    "Capability",
    "CapabilityVerifier",
    "DecisionInput",
    "DecisionLogicalKey",
    "DecisionSeal",
    "DecisionSealBinding",
    "EvidenceQueryPort",
    "EvidenceScope",
    "ExecutionMode",
    "ExecutionPermit",
    "ExplorationAuthorization",
    "EdgeAuthorization",
    "PlanEvidence",
    "PositionSnapshot",
    "PositionState",
    "PublishDecisionCommand",
    "SealWriterPort",
    "SealedOrderLine",
    "ShadowDecision",
    "SignedEnvelope",
    "SnapshotEvidence",
    "canonical_json_bytes",
    "content_hash",
    "VerifiedIssuer",
]
