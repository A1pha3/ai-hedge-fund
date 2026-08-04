"""Stable, storage-free structural ports for later v3 plans."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypeAlias, TypeVar, runtime_checkable

from .authorization import CapitalAuthorizationEnvelope
from .base import CanonicalModel
from .capital import CapitalRiskSnapshot
from .decision import (
    GatewayExpectedVersions,
    PlanEvidence,
    PortfolioDecision,
    PortfolioDecisionSeal,
    ShadowDecision,
)
from .evidence import (
    EvidenceRecord,
    OutcomeEvidence,
    SignalEvidence,
    SnapshotEvidence,
)
from .governance import AuthorizationStatus
from .trust import (
    Capability,
    CurrentTrustHeadWitness,
    SignedEnvelope,
    VerifiedIssuer,
)


KernelInputT = TypeVar("KernelInputT", bound=CanonicalModel, contravariant=True)
NoTradeDecisionT = TypeVar("NoTradeDecisionT", bound=CanonicalModel, covariant=True)
ActiveEvidenceRecord: TypeAlias = (
    EvidenceRecord[SnapshotEvidence]
    | EvidenceRecord[SignalEvidence]
    | EvidenceRecord[OutcomeEvidence]
    | EvidenceRecord[PlanEvidence]
)


@runtime_checkable
class CapitalGatewayReadPort(Protocol):
    def risk_snapshot(
        self, portfolio_id: str, as_of: datetime
    ) -> CapitalRiskSnapshot: ...


@runtime_checkable
class EvidenceQueryPort(Protocol):
    def active_revision(
        self, evidence_id: str, cutoff: datetime
    ) -> ActiveEvidenceRecord: ...

    def outcome(
        self, outcome_id: str, revision: int
    ) -> EvidenceRecord[OutcomeEvidence]: ...


@runtime_checkable
class AuthorizationQueryPort(Protocol):
    def active_envelope(self, portfolio_id: str) -> CapitalAuthorizationEnvelope: ...

    def status(self, authorization_id: str) -> AuthorizationStatus: ...


@runtime_checkable
class GrowthKernelPort(Protocol[KernelInputT, NoTradeDecisionT]):
    def decide(
        self, frozen: KernelInputT
    ) -> NoTradeDecisionT | ShadowDecision | PortfolioDecision: ...


@runtime_checkable
class CapitalGatewayCommandPort(Protocol):
    def publish_entry(
        self,
        proposal: PortfolioDecision,
        expected: GatewayExpectedVersions,
    ) -> PortfolioDecisionSeal: ...


@runtime_checkable
class CapabilityVerifier(Protocol):
    def verify(
        self,
        signed: SignedEnvelope,
        required: Capability,
        *,
        current_head: CurrentTrustHeadWitness,
        trusted_at: datetime,
    ) -> VerifiedIssuer: ...


__all__ = [
    "ActiveEvidenceRecord",
    "AuthorizationQueryPort",
    "CapitalGatewayCommandPort",
    "CapitalGatewayReadPort",
    "CapabilityVerifier",
    "EvidenceQueryPort",
    "GrowthKernelPort",
]
