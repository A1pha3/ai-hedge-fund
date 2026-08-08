"""Plan 05 Task 2: AuthorizerApi — thin EDGE authorizer adapter.

Wraps the Plan 03 ``Authorizer``. Every candidate envelope is a complete
portfolio policy and stays **INACTIVE**: activation is a later Capital
Gateway CAS and grants no authority here. All gates fail closed; a failed
external signature leaves no consumption and no issued envelope, and a
retry is deterministic.

Import boundary: this module must NOT import ``capital``, ``gateway`` or
``execution`` modules (a capability-matrix test scans the source).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from src.screening.offensive.v3.contracts import SignedEnvelope
from src.screening.offensive.v3.contracts.authorization import (
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.evidence.authorizer import (
    Authorizer,
    EdgeAssessmentRequest,
)
from src.screening.offensive.v3.evidence.consumption import (
    AttemptLedger,
    EvidenceConsumptionLedger,
)


class AuthorizerApi:
    """Assesses evidence and signs inactive EDGE envelope candidates only."""

    def __init__(
        self,
        *,
        database_path: str,
        signer: Callable[[bytes], SignedEnvelope],
        clock: Callable[[], datetime],
        attempts: AttemptLedger,
        consumption: EvidenceConsumptionLedger,
        expected_mode: ExecutionMode,
        expected_behavior_fingerprint: str,
        expected_cost_version: str,
        expected_execution_version: str,
        expected_broker_account_id: str | None,
    ) -> None:
        """Construct the service; parameters match ``Authorizer`` exactly.

        The service delegates to an internally-constructed ``Authorizer``
        over the same arguments.
        """
        self._signer = signer
        self._authorizer = Authorizer(
            database_path=database_path,
            signer=signer,
            clock=clock,
            attempts=attempts,
            consumption=consumption,
            expected_mode=expected_mode,
            expected_behavior_fingerprint=expected_behavior_fingerprint,
            expected_cost_version=expected_cost_version,
            expected_execution_version=expected_execution_version,
            expected_broker_account_id=expected_broker_account_id,
        )

    def assess_edge(
        self, request: EdgeAssessmentRequest
    ) -> tuple[CapitalAuthorizationEnvelope, SignedEnvelope]:
        """Run every gate fail-closed, then sign one INACTIVE candidate.

        Delegates to ``Authorizer.assess_and_issue_edge``; the produced
        envelope's status is guaranteed INACTIVE (the Authorizer itself
        never issues ACTIVE candidates).
        """
        return self._authorizer.assess_and_issue_edge(request)

    def issued_status(self, authorization_id: str) -> str:
        """The recorded status of one issued envelope (INACTIVE until CAS)."""
        return self._authorizer.issued_status(authorization_id)


__all__ = ["AuthorizerApi"]
