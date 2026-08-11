"""Frozen regime admission contracts for the paired shadow trial.

These primitives make the regime a typed, point-in-time policy fact rather than an
ambient label. A canonical ``RegimeObservation(state=UNKNOWN)`` is a valid shared
fact: the Champion (``IGNORE``) may keep taking BTST risk while the Challenger
(``NORMAL_ONLY``) blocks. The *absence* of a canonical observation by cutoff is an
operational ``NO_RUN`` and must never be back-filled as ``UNKNOWN`` or ``NORMAL``.

Only ``ProducerPolicy.btst_regime_admission_mode`` may differ between the two
arms of a paired trial; every other behavioural delta rejects trial enrolment.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from .base import (
    CanonicalModel,
    ExactInteger,
    Sha256,
    UtcInstant,
    content_hash,
)

#: Identifier for one piece of trusted source evidence backing an observation.
_RegimeEvidenceId = Annotated[
    str,
    StringConstraints(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]

#: Frozen classifier version that produced an observation.
_RegimeClassifierSemver = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
    ),
]

#: A strictly positive exact integer (revision counters are never zero).
PositiveExactInt = Annotated[ExactInteger, Field(ge=1)]


class RegimeState(StrEnum):
    """Canonical, frozen market-regime states admitted by the trial."""

    NORMAL = "NORMAL"
    RISK_OFF = "RISK_OFF"
    CRISIS = "CRISIS"
    UNKNOWN = "UNKNOWN"


class RegimeObservationReason(StrEnum):
    """Typed reason a ``RegimeObservation`` carries its state."""

    CLASSIFIED = "CLASSIFIED"
    MISSING_REQUIRED_INPUT = "MISSING_REQUIRED_INPUT"
    STALE_REQUIRED_INPUT = "STALE_REQUIRED_INPUT"
    UNRECOGNIZED_RAW_STATE = "UNRECOGNIZED_RAW_STATE"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"


class RegimeAdmissionMode(StrEnum):
    """The only pre-registered arm policy delta admitted by a paired trial."""

    IGNORE = "IGNORE"
    NORMAL_ONLY = "NORMAL_ONLY"


class RegimeSourceRevision(CanonicalModel):
    """One immutable reference to a trusted source evidence revision."""

    evidence_id: _RegimeEvidenceId
    revision: PositiveExactInt
    artifact_hash: Sha256


def normalize_regime_state(
    raw_state: str | None,
    *,
    reason_if_missing: RegimeObservationReason,
) -> tuple[RegimeState, RegimeObservationReason]:
    """Map an upstream raw regime label to a canonical state and typed reason.

    A recognized canonical label (``normal``/``risk_off``/``crisis``, case- and
    separator-insensitive) yields the matching non-unknown state with reason
    ``CLASSIFIED``. ``None`` yields ``UNKNOWN`` with the caller-supplied reason.
    Any other value yields ``UNKNOWN`` with ``UNRECOGNIZED_RAW_STATE``. The
    ``UNKNOWN`` token is never treated as a classified input: it is always a
    failure mode, produced by the classifier rather than read off the wire.
    """

    if reason_if_missing not in RegimeObservationReason:
        raise TypeError("reason_if_missing must be a RegimeObservationReason")
    if raw_state is None:
        return RegimeState.UNKNOWN, reason_if_missing
    token = raw_state.strip().upper().replace("-", "_")
    classified = {
        "NORMAL": RegimeState.NORMAL,
        "RISK_OFF": RegimeState.RISK_OFF,
        "CRISIS": RegimeState.CRISIS,
    }.get(token)
    if classified is not None:
        return classified, RegimeObservationReason.CLASSIFIED
    return RegimeState.UNKNOWN, RegimeObservationReason.UNRECOGNIZED_RAW_STATE


class RegimeObservation(CanonicalModel):
    """A canonical, point-in-time regime observation bound to trusted evidence.

    The observation is the versioned payload of an existing ``SnapshotEvidence``
    envelope, not a fifth evidence kind. Store-owned timestamps
    (``ingested_at``/``available_at``) live on the envelope; this model carries
    only the typed, classifier-bound fact and its source lineage.
    """

    signal_session: date
    state: RegimeState
    reason: RegimeObservationReason
    raw_state: str | None
    source_revisions: tuple[RegimeSourceRevision, ...]
    effective_at: UtcInstant
    provider_published_at: UtcInstant | None
    observed_at: UtcInstant
    classifier_semver: _RegimeClassifierSemver
    behavior_fingerprint: Sha256
    input_schema_hash: Sha256

    @model_validator(mode="after")
    def _validate_state_reason_pairing(self) -> Self:
        classified = self.reason is RegimeObservationReason.CLASSIFIED
        if self.state is RegimeState.UNKNOWN:
            if classified:
                raise ValueError(
                    "an unknown regime state must not carry the classified reason"
                )
        elif not classified:
            raise ValueError(
                "a canonical non-unknown regime state requires the classified reason"
            )
        return self

    @model_validator(mode="after")
    def _validate_source_lineage(self) -> Self:
        if not self.source_revisions:
            raise ValueError("source_revisions must bind at least one evidence")
        evidence_ids = [revision.evidence_id for revision in self.source_revisions]
        for earlier, later in zip(evidence_ids, evidence_ids[1:]):
            if not earlier < later:
                raise ValueError(
                    "source_revisions must be ordered by evidence_id with no duplicates"
                )
        return self

    @model_validator(mode="after")
    def _validate_observation_recency(self) -> Self:
        if self.effective_at > self.observed_at:
            raise ValueError("observed_at must not precede effective_at")
        if (
            self.provider_published_at is not None
            and self.provider_published_at > self.observed_at
        ):
            raise ValueError("observed_at must not precede provider_published_at")
        return self

    @field_validator("raw_state")
    @classmethod
    def _raw_state_cannot_be_unknown_token(cls, value: str | None) -> str | None:
        if value is not None and value.strip().upper().replace("-", "_") == "UNKNOWN":
            raise ValueError(
                "raw_state may not carry the UNKNOWN token; UNKNOWN is produced, not read"
            )
        return value

    @property
    def source_evidence_root(self) -> str:
        """Content hash of the canonically sorted source artifact hashes.

        Sorting by artifact hash (not by evidence id) makes the root independent
        of the source enumeration order while remaining a pure projection of the
        observation. It is a property, never a stored field, so it cannot appear
        in the observation's own canonical preimage.
        """

        return content_hash(
            tuple(sorted(rev.artifact_hash for rev in self.source_revisions))
        )


__all__ = [
    "PositiveExactInt",
    "RegimeAdmissionMode",
    "RegimeObservation",
    "RegimeObservationReason",
    "RegimeSourceRevision",
    "RegimeState",
    "normalize_regime_state",
]
