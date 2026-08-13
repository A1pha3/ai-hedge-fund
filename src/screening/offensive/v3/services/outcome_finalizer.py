"""Plan 05 Task 2: OutcomeFinalizerService — thin finalizer adapter.

Wraps the Plan 03 ``OutcomeFinalizer`` with an identical construction
surface and passes every call straight through. Publication is currently
fail-closed before any injected dependency is observed. Only immutable local
plan-line preregistration remains; it grants no publication authority.

Import boundary: this module must NOT import ``capital``, ``gateway`` or
``execution`` modules (it only ever receives a ``capital_engine`` instance
as a constructor argument; a capability-matrix test scans the source).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

import sqlalchemy as sa

from src.screening.offensive.v3.contracts import (
    Capability,
    ExecutionMode,
    SignedEnvelope,
)
from src.screening.offensive.v3.evidence.outcomes import (
    OutcomeFact,
    OutcomeFinalizer,
    PlanLineDefinition,
)
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.evidence.session_spine import SessionSpine


class OutcomeFinalizerService:
    """Disabled outcome boundary plus immutable local preregistration."""

    def __init__(
        self,
        *,
        database_path: str,
        capital_engine: sa.engine.Engine,
        evidence_repository: EvidenceRepository,
        session_spine: SessionSpine,
        signer: Callable[[bytes], SignedEnvelope],
        signer_capability: Capability,
        clock: Callable[[], datetime],
        issuer_namespace: str,
        behavior_fingerprint: str,
        execution_mode: ExecutionMode,
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
            signer_capability=signer_capability,
            clock=clock,
            issuer_namespace=issuer_namespace,
            behavior_fingerprint=behavior_fingerprint,
            execution_mode=execution_mode,
            policy_epoch=policy_epoch,
        )

    def register_plan_line(self, definition: PlanLineDefinition) -> None:
        """Register one pre-registered plan-line economic contract.

        Delegates to ``OutcomeFinalizer.register_plan_line``; the contract
        key is immutable once registered.
        """
        self._finalizer.register_plan_line(definition)

    def finalize_due(self, as_of: datetime, *, program: str) -> tuple[str, ...]:
        """Fail closed before observing any injected dependency."""
        return self._finalizer.finalize_due(as_of, program=program)

    def outcome_fact(self, contract_key: str) -> OutcomeFact:
        """Fail closed before observing local or Evidence Store state."""
        return self._finalizer.outcome_fact(contract_key)


__all__ = ["OutcomeFinalizerService"]
