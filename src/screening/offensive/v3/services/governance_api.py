"""Plan 05 Task 2: GovernanceApi — thin trial-seal + EXPLORATION/RECOVERY adapter.

Wraps the Plan 03 ``GovernanceRepository`` (trial/SAP sealing, attempt
reservation, target-policy registration) and ``GovernanceIssuer``
(EXPLORATION/RECOVERY envelope candidates). The issuer never signs EDGE;
every candidate stays INACTIVE until a later Capital Gateway CAS.

``seal_trial`` requires an **explicit signed approval input**: the caller
must pass a ``SignedEnvelope`` whose ``namespace`` equals this service's
issuer namespace and whose ``artifact`` is a PLAN/TRUST-class approval
(``ArtifactKind.PLAN`` or ``ArtifactKind.TRIAL_MANIFEST``). Any missing,
mismatched or wrong-kind approval is rejected with ``GovernanceStoreError``
and there is **no environment-variable fallback**.

Import boundary: this module must NOT import ``capital``, ``gateway`` or
``execution`` modules (a capability-matrix test scans the source).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Final

from src.screening.offensive.v3.contracts import ArtifactKind, SignedEnvelope
from src.screening.offensive.v3.contracts.authorization import (
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.evidence.consumption import (
    AttemptLedger,
    EvidenceConsumptionLedger,
)
from src.screening.offensive.v3.governance.issuer import (
    ExplorationIssuanceRequest,
    GovernanceIssuer,
    RecoveryIssuanceRequest,
)
from src.screening.offensive.v3.governance.repository import (
    GovernanceRepository,
    GovernanceStoreError,
    TrialSealReceipt,
    TrialSealRequest,
)

APPROVAL_ARTIFACT_KINDS: Final = frozenset(
    {ArtifactKind.PLAN, ArtifactKind.TRIAL_MANIFEST}
)
"""PLAN/TRUST-class artifacts accepted as an explicit seal approval."""

SEAL_APPROVAL_REQUIRED: Final[str] = "seal_approval_required"
"""Stable error code: seal_trial called without a signed approval input."""

SEAL_APPROVAL_NAMESPACE_MISMATCH: Final[str] = "seal_approval_namespace_mismatch"
"""Stable error code: approval signed under a different issuer namespace."""

SEAL_APPROVAL_ARTIFACT_REJECTED: Final[str] = "seal_approval_artifact_rejected"
"""Stable error code: approval artifact is not a PLAN/TRUST-class approval."""


class GovernanceApi:
    """One governance namespace: trial seals + EXPLORATION/RECOVERY issuance."""

    def __init__(
        self,
        *,
        database_path: str,
        signer: Callable[[bytes], SignedEnvelope],
        clock: Callable[[], datetime],
        attempts: AttemptLedger,
        consumption: EvidenceConsumptionLedger,
        issuer_namespace: str,
    ) -> None:
        """Construct the service over one writable governance database.

        The service builds an internal ``GovernanceRepository`` and
        ``GovernanceIssuer`` over the same ``database_path``; ``issuer_namespace``
        is the namespace every approval must be signed under and every
        issued envelope is recorded for.
        """
        self._signer = signer
        self._issuer_namespace = issuer_namespace
        self._repository = GovernanceRepository(
            database_path=database_path,
            clock=clock,
        )
        self._issuer = GovernanceIssuer(
            database_path=database_path,
            signer=signer,
            clock=clock,
            attempts=attempts,
            consumption=consumption,
        )

    def seal_trial(
        self, request: TrialSealRequest, *, approval: SignedEnvelope
    ) -> TrialSealReceipt:
        """Seal one trial atomically, gated on an explicit signed approval.

        Fail-closed guards (in order):
        - ``approval`` must be provided (a missing or ``None`` approval is
          rejected with code ``SEAL_APPROVAL_REQUIRED``);
        - ``approval.namespace`` must equal this service's issuer namespace
          (code ``SEAL_APPROVAL_NAMESPACE_MISMATCH``);
        - ``approval.artifact`` must be PLAN/TRUST-class, i.e. in
          ``APPROVAL_ARTIFACT_KINDS`` (code ``SEAL_APPROVAL_ARTIFACT_REJECTED``).

        All rejections raise ``GovernanceStoreError``; there is no
        environment-variable fallback. On success the seal commits the
        attempt reservation, trial/SAP manifests and the non-executable
        target policy registration atomically.
        """
        if approval is None:
            raise GovernanceStoreError(
                SEAL_APPROVAL_REQUIRED,
                "seal_trial requires an explicit signed approval input",
            )
        if approval.namespace != self._issuer_namespace:
            raise GovernanceStoreError(
                SEAL_APPROVAL_NAMESPACE_MISMATCH,
                "approval is signed under a different issuer namespace",
                expected=self._issuer_namespace,
                observed=approval.namespace,
            )
        if approval.artifact not in APPROVAL_ARTIFACT_KINDS:
            raise GovernanceStoreError(
                SEAL_APPROVAL_ARTIFACT_REJECTED,
                "approval artifact is not a PLAN/TRUST-class approval",
                artifact=approval.artifact.value,
            )
        return self._repository.reserve_attempt_and_seal_trial(request)

    def issue_exploration(
        self, request: ExplorationIssuanceRequest
    ) -> tuple[CapitalAuthorizationEnvelope, SignedEnvelope]:
        """Issue one INACTIVE EXPLORATION candidate.

        Delegates to ``GovernanceIssuer.issue_exploration``; the candidate
        is BROKER_CONFIRMED-only and aggregate-capped at 2% of NAV.
        """
        return self._issuer.issue_exploration(request)

    def issue_recovery(
        self, request: RecoveryIssuanceRequest
    ) -> tuple[CapitalAuthorizationEnvelope, SignedEnvelope]:
        """Issue one INACTIVE RECOVERY candidate.

        Delegates to ``GovernanceIssuer.issue_recovery``; recovery cites
        the inherited authorization and ALL inherited risk/loss versions
        and never mints a new grant.
        """
        return self._issuer.issue_recovery(request)

    def sealed_trial(self, trial_id: str) -> dict[str, object]:
        """The immutable sealed trial row by trial id."""
        return self._repository.sealed_trial(trial_id)

    def target_policy(self, registration_hash: str) -> dict[str, object]:
        """The registered (explicitly non-executable) target policy row."""
        return self._repository.target_policy(registration_hash)

    def issued_status(self, authorization_id: str) -> str:
        """The recorded status of one issued envelope (INACTIVE until CAS)."""
        return self._issuer.issued_status(authorization_id)


__all__ = [
    "APPROVAL_ARTIFACT_KINDS",
    "GovernanceApi",
    "SEAL_APPROVAL_ARTIFACT_REJECTED",
    "SEAL_APPROVAL_NAMESPACE_MISMATCH",
    "SEAL_APPROVAL_REQUIRED",
]
