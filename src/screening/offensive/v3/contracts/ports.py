"""Stable structural ports between storage-free v3 domain layers."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .authorization import CapitalAuthorizationEnvelope
from .capital import CapitalSnapshot
from .evidence import SnapshotEvidence
from .trust import Capability, SignedEnvelope, VerifiedIssuer


@runtime_checkable
class CapitalViewPort(Protocol):
    def snapshot(self, portfolio_id: str, as_of: datetime) -> CapitalSnapshot: ...


@runtime_checkable
class EvidenceQueryPort(Protocol):
    def snapshot(self, evidence_id: str) -> SnapshotEvidence: ...

    def authorization(self, authorization_id: str) -> CapitalAuthorizationEnvelope: ...


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
]
