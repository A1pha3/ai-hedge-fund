"""Candidate admission for the growth kernel (Plan 04 Task 2).

Pure and fail-closed: producers never apply portfolio risk multipliers
and producer-supplied weights/labels cannot bypass central limits.
BTST is the only executable family; OversoldBounce stays disabled;
shadow producers are admitted as SHADOW only and can never produce an
executable line. Auto executable admission is zero.
"""

from __future__ import annotations

from typing import Final

from src.screening.offensive.v3.contracts.authorization import (
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.governance import PolicyActivation
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    RawCandidate,
)
from src.screening.offensive.v3.contracts.base import CanonicalModel
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr

BTST_FAMILY: Final[str] = "btst.limit-up-breakout"
OVERSOLD_BOUNCE_FAMILY: Final[str] = "oversold-bounce"
SHADOW_PRODUCER_NAMESPACES: Final[tuple[str, ...]] = ("auto",)
EXECUTABLE_FAMILIES: Final[tuple[str, ...]] = (BTST_FAMILY,)
DISABLED_FAMILIES: Final[tuple[str, ...]] = (OVERSOLD_BOUNCE_FAMILY,)


class AdmissionStatus(CanonicalModel):
    """One admission outcome for one raw candidate."""

    candidate_id: NonEmptyStr
    status: NonEmptyStr  # ADMITTED | SHADOW | BLOCKED
    block_reason: BlockReason | None = None


class AdmissionError(RuntimeError):
    """Fail-closed rejection of the admission context itself."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def admit_candidates(
    candidates: tuple[RawCandidate, ...],
    *,
    envelope: CapitalAuthorizationEnvelope,
    policy_activation: PolicyActivation,
) -> tuple[AdmissionStatus, ...]:
    """Admit raw candidates against the complete frozen authority.

    Every mismatch is a typed block; unknown producers/families never
    fall through to zero/default admission.
    """

    if envelope.policy_activation_hash != policy_activation.artifact_hash():
        raise AdmissionError(
            "policy_envelope_mismatch",
            "policy activation hash differs from the envelope binding",
        )
    grants = {
        grant.economic_lineage_id: grant for grant in envelope.lineage_grants
    }
    results: list[AdmissionStatus] = []
    for candidate in candidates:
        results.append(
            _admit_one(candidate, envelope=envelope, grants=grants)
        )
    return tuple(results)


def _admit_one(
    candidate: RawCandidate,
    *,
    envelope: CapitalAuthorizationEnvelope,
    grants: dict,
) -> AdmissionStatus:
    def blocked(reason: BlockReason) -> AdmissionStatus:
        return AdmissionStatus(
            candidate_id=candidate.candidate_id,
            status="BLOCKED",
            block_reason=reason,
        )

    # Shadow producers are never executable.
    if candidate.producer_namespace in SHADOW_PRODUCER_NAMESPACES:
        return AdmissionStatus(
            candidate_id=candidate.candidate_id,
            status="SHADOW",
            block_reason=None,
        )
    # Disabled families never trade.
    if candidate.family_id in DISABLED_FAMILIES:
        return blocked(BlockReason.NO_SIGNAL)
    # Only allowlisted executable families admit.
    if candidate.family_id not in EXECUTABLE_FAMILIES:
        return blocked(BlockReason.NO_AUTHORIZED_ENVELOPE)
    grant = grants.get(candidate.economic_lineage_id)
    if grant is None:
        return blocked(BlockReason.NO_AUTHORIZED_ENVELOPE)
    # Behavior/cost/execution/stage must match the lineage grant exactly.
    if candidate.behavior_fingerprint != grant.behavior_fingerprint:
        return blocked(BlockReason.POLICY_ENVELOPE_MISMATCH)
    if candidate.execution_version != grant.execution_version:
        return blocked(BlockReason.CAPITAL_VERSION_MISMATCH)
    if candidate.cost_version != grant.cost_version:
        return blocked(BlockReason.CAPITAL_VERSION_MISMATCH)
    if candidate.stage_id != grant.stage_id:
        return blocked(BlockReason.CAPITAL_VERSION_MISMATCH)
    if candidate.research_program_id != grant.research_program_id:
        return blocked(BlockReason.MODE_MISMATCH)
    return AdmissionStatus(
        candidate_id=candidate.candidate_id,
        status="ADMITTED",
        block_reason=None,
    )


__all__ = [
    "BTST_FAMILY",
    "DISABLED_FAMILIES",
    "EXECUTABLE_FAMILIES",
    "OVERSOLD_BOUNCE_FAMILY",
    "SHADOW_PRODUCER_NAMESPACES",
    "AdmissionError",
    "AdmissionStatus",
    "admit_candidates",
]
