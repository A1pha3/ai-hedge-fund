"""Typed validation for evidence envelopes that reference separate raw blobs."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from pydantic import ValidationError

from src.screening.offensive.v3.contracts.btst_candidate import (
    BtstRawCandidatePayload,
)
from src.screening.offensive.v3.contracts.evidence import SignalEvidence
from src.screening.offensive.v3.evidence.blob_store import BlobStoreError


class ReferencedPayloadValidationError(RuntimeError):
    """A typed evidence envelope does not bind valid durable raw bytes."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _qualify_security_id(symbol: str) -> str | None:
    """Validate the frozen six-digit identity without importing producer code."""

    if len(symbol) != 6 or not symbol.isdigit():
        return None
    if symbol.startswith(("6", "68", "51", "56", "58", "60")):
        return f"{symbol}.SH"
    if symbol.startswith(("0", "3", "15", "16", "18", "20")):
        return f"{symbol}.SZ"
    if symbol.startswith(("4", "8", "92")):
        return f"{symbol}.BJ"
    return None


def validate_referenced_payload(
    *,
    issuer_namespace: str,
    envelope: object,
    read_payload: Callable[[str], bytes],
) -> None:
    """Validate namespace-specific raw evidence before the envelope commits."""

    if issuer_namespace != "btst" or type(envelope) is not SignalEvidence:
        return

    signal = envelope
    try:
        raw = read_payload(signal.payload_content_hash)
    except BlobStoreError as exc:
        code = (
            "referenced_payload_missing"
            if exc.code == "blob_not_found"
            else "referenced_payload_unreadable"
        )
        raise ReferencedPayloadValidationError(
            code,
            "BTST signal referenced payload is not durable and readable",
            evidence_id=signal.evidence_id,
            reason=exc.code,
        ) from exc
    if hashlib.sha256(raw).hexdigest() != signal.payload_content_hash:
        raise ReferencedPayloadValidationError(
            "referenced_payload_hash_mismatch",
            "BTST signal referenced bytes do not match payload_content_hash",
            evidence_id=signal.evidence_id,
        )
    try:
        candidate = BtstRawCandidatePayload.model_validate_json(raw, strict=True)
    except (ValidationError, ValueError) as exc:
        raise ReferencedPayloadValidationError(
            "referenced_payload_invalid",
            "BTST signal referenced bytes are not a strict raw candidate",
            evidence_id=signal.evidence_id,
            reason=str(exc),
        ) from exc

    identity_parts = candidate.candidate_id.rsplit(":", 2)
    expected_family = f"btst:{candidate.snapshot_id}"
    identity_security_id = (
        _qualify_security_id(identity_parts[1])
        if len(identity_parts) == 3
        else None
    )
    if not (
        len(identity_parts) == 3
        and identity_parts[0] == expected_family
        and identity_parts[2] == candidate.setup
        and identity_security_id == candidate.security_id
        and signal.evidence_id
        == f"{candidate.candidate_id}:{candidate.signal_stage.value}"
        and signal.family_id == expected_family
        and signal.stage is candidate.signal_stage
        and candidate.producer_namespace == "btst"
        and signal.subject_producer == "btst"
        and signal.effective_at.date() == candidate.signal_session
        and candidate.strategy_semver == signal.strategy_semver
        and candidate.behavior_fingerprint == signal.behavior_fingerprint
        and candidate.execution_version == signal.execution_version
        and candidate.cost_version == signal.cost_version
    ):
        raise ReferencedPayloadValidationError(
            "referenced_payload_binding_mismatch",
            "BTST raw candidate does not match its signal envelope",
            evidence_id=signal.evidence_id,
        )


__all__ = [
    "ReferencedPayloadValidationError",
    "validate_referenced_payload",
]
