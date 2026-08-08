"""Plan 05 Task 2: OutcomeFinalizerService — thin finalizer adapter.

Wraps the Plan 03 ``OutcomeFinalizer`` with an identical construction
surface and passes every call straight through. The finalizer reads Plan 02
capital truth from the injected ``capital_engine`` (never imported from
``capital``), the enrolled ``SessionSpine`` and the evidence store, and
emits one mode-pure ``OutcomeFact`` per plan-line economic contract.

Import boundary: this module must NOT import ``capital``, ``gateway`` or
``execution`` modules (it only ever receives a ``capital_engine`` instance
as a constructor argument; a capability-matrix test scans the source).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

import sqlalchemy as sa

from src.screening.offensive.v3.contracts import SignedEnvelope
from src.screening.offensive.v3.evidence.outcomes import (
    OutcomeFact,
    OutcomeFinalizer,
    PlanLineDefinition,
)
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.evidence.session_spine import SessionSpine


class OutcomeFinalizerService:
    """Finalizes due plan lines into mode-pure outcome evidence."""

    def __init__(
        self,
        *,
        database_path: str,
        capital_engine: sa.engine.Engine,
        evidence_repository: EvidenceRepository,
        session_spine: SessionSpine,
        signer: Callable[[bytes], SignedEnvelope],
        clock: Callable[[], datetime],
        issuer_namespace: str,
        behavior_fingerprint: str,
        policy_epoch: int = 1,
    ) -> None:
        """Construct the service; parameters match ``OutcomeFinalizer`` exactly.

        The service delegates to an internally-constructed
        ``OutcomeFinalizer`` over the same arguments.
        """
        self._signer = signer
        self._finalizer = OutcomeFinalizer(
            database_path=database_path,
            capital_engine=capital_engine,
            evidence_repository=evidence_repository,
            session_spine=session_spine,
            signer=signer,
            clock=clock,
            issuer_namespace=issuer_namespace,
            behavior_fingerprint=behavior_fingerprint,
            policy_epoch=policy_epoch,
        )

    def register_plan_line(self, definition: PlanLineDefinition) -> None:
        """Register one pre-registered plan-line economic contract.

        Delegates to ``OutcomeFinalizer.register_plan_line``; the contract
        key is immutable once registered.
        """
        self._finalizer.register_plan_line(definition)

    def finalize_due(self, as_of: datetime, *, program: str) -> tuple[str, ...]:
        """Finalize every due plan line; returns finalized contract keys.

        Delegates to ``OutcomeFinalizer.finalize_due``.
        """
        return self._finalizer.finalize_due(as_of, program=program)

    def outcome_fact(self, contract_key: str) -> OutcomeFact:
        """The current committed outcome fact for one plan line.

        Delegates to ``OutcomeFinalizer.outcome_fact``.
        """
        return self._finalizer.outcome_fact(contract_key)


__all__ = ["OutcomeFinalizerService"]
