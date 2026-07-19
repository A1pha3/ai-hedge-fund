"""Immutable plan, decision-seal, shadow-decision, and permit contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import CanonicalModel, ExecutionMode, Sha256, UtcInstant
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
        if self.created_at > self.deadline:
            raise ValueError("decision deadline must be at or after created_at")
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

    @model_validator(mode="after")
    def validate_active_revision(self) -> Self:
        if self.active_seal_id != self.seal_id:
            raise ValueError("active_seal_id must identify this active seal revision")
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research reconstruction cannot create a DecisionSeal")
        return self


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
    "DecisionLogicalKey",
    "DecisionSeal",
    "ExecutionPermit",
    "PlanEvidence",
    "SealedOrderLine",
    "ShadowDecision",
]
