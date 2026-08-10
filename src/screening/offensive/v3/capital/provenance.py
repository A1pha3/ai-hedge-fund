"""Causal provenance bindings for capital facts.

Plan 08 Task 7. Every capital fact derived from a Trial decision or a
market snapshot binds the exact artifact that caused it:

- decision-derived proxy reserves/fills/fees/corrections carry
  ``mode=DAILY_BAR_PROXY`` and ``artifact_kind=SHADOW_DECISION`` with the
  decision's current id and content hash;
- valuation/restatement marks bind the ``SnapshotEvidence`` that produced
  them (``artifact_kind=SNAPSHOT``).

Fingerprints prove identity, never permission: the binding is recorded
with the fact so a replay can verify the fact really derives from the
artifact it claims, but it grants no authority of its own.
"""

from __future__ import annotations

from pydantic import model_validator

from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    ExecutionMode,
    Sha256,
)
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr
from src.screening.offensive.v3.contracts.trust import ArtifactKind


class CapitalSourceBinding(CanonicalModel):
    """One durable causal link from a capital fact to its source artifact.

    ``artifact_id`` is the source artifact's stable identity (e.g. the
    ``shadow_decision_id`` or the SnapshotEvidence record id) and
    ``artifact_hash`` its current content fingerprint, so both identity
    and content are verifiable at replay time.
    """

    mode: ExecutionMode
    artifact_kind: ArtifactKind
    artifact_id: NonEmptyStr
    artifact_hash: Sha256

    @model_validator(mode="after")
    def validate_mode_kind(self) -> "CapitalSourceBinding":
        if self.mode is not ExecutionMode.DAILY_BAR_PROXY:
            if self.artifact_kind in (
                ArtifactKind.SHADOW_DECISION,
                ArtifactKind.SNAPSHOT,
            ):
                raise ValueError(
                    "shadow decision and snapshot bindings require"
                    " DAILY_BAR_PROXY ledger mode"
                )
        else:
            if self.artifact_kind not in (
                ArtifactKind.SHADOW_DECISION,
                ArtifactKind.SNAPSHOT,
            ):
                raise ValueError(
                    "proxy ledger facts bind only shadow decisions and"
                    " snapshot evidence"
                )
        return self


# Keep the field annotation readable at every request site.
OptionalSourceBinding = CapitalSourceBinding | None

__all__ = [
    "CapitalSourceBinding",
    "OptionalSourceBinding",
]
