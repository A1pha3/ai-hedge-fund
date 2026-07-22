"""Stable structural ports between storage-free v3 domain layers."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .authorization import CapitalAuthorization
from .capital import CapitalSnapshot
from .decision import DecisionSeal, PublishDecisionCommand
from .evidence import SnapshotEvidence
from .trust import Capability, SignedEnvelope, VerifiedIssuer


@runtime_checkable
class CapitalViewPort(Protocol):
    def snapshot(self, portfolio_id: str, as_of: datetime) -> CapitalSnapshot: ...


@runtime_checkable
class EvidenceQueryPort(Protocol):
    def snapshot(self, evidence_id: str) -> SnapshotEvidence: ...

    def authorization(self, authorization_id: str) -> CapitalAuthorization: ...


@runtime_checkable
class SealWriterPort(Protocol):
    def publish(self, command: PublishDecisionCommand) -> DecisionSeal: ...


@runtime_checkable
class CapabilityVerifier(Protocol):
    def verify(
        self,
        signed: SignedEnvelope,
        required: Capability,
        *,
        verification_time: datetime,
    ) -> VerifiedIssuer: ...


__all__ = [
    "CapitalViewPort",
    "CapabilityVerifier",
    "EvidenceQueryPort",
    "SealWriterPort",
]
