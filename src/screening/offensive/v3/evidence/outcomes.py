"""Fail-closed Outcome Finalizer boundary (Plan 03 Task 3).

Outcome publication is unavailable until a store-owned plan-line execution
binding, cancellation-aware exchange calendar, exact capital revision reducer,
and mechanically fenced single writer exist.  Registration remains a local,
immutable candidate-input operation. Historical reads are unavailable until an
approved migration manifest can distinguish trustworthy evidence generations.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Final, Literal

import sqlalchemy as sa

from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    Capability,
    ExecutionMode,
    SignedEnvelope,
)
from src.screening.offensive.v3.contracts.base import CanonicalModel
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
)
from src.screening.offensive.v3.evidence.session_spine import SessionSpine

_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS plan_lines (
        plan_line_economic_contract_key TEXT PRIMARY KEY,
        producer_namespace TEXT NOT NULL,
        economic_lineage_id TEXT NOT NULL,
        stage_id TEXT NOT NULL,
        family_id TEXT NOT NULL,
        mode TEXT NOT NULL,
        execution_version TEXT NOT NULL,
        cost_version TEXT NOT NULL,
        signal_session TEXT NOT NULL,
        entry_session_ordinal INTEGER NOT NULL,
        exit_session_ordinal INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS finalized_plan_lines (
        plan_line_economic_contract_key TEXT PRIMARY KEY,
        outcome_evidence_id TEXT NOT NULL,
        finality TEXT NOT NULL,
        revision INTEGER NOT NULL,
        finalized_at TEXT NOT NULL
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS outcome_plan_lines_no_update
    BEFORE UPDATE ON plan_lines
    BEGIN
        SELECT RAISE(ABORT, 'outcome plan lines are immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS outcome_plan_lines_no_delete
    BEFORE DELETE ON plan_lines
    BEGIN
        SELECT RAISE(ABORT, 'outcome plan lines are immutable');
    END
    """,
)

_AUTHORITY_UNAVAILABLE = "outcome_input_authority_unavailable"


class OutcomeFinalizerError(RuntimeError):
    """Fail-closed rejection of an outcome finalization."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class OutcomeFact(CanonicalModel):
    """One matured plan-line outcome under a fixed mode/behavior version."""

    HASH_DOMAIN: str = "ai-hedge-fund.v3.evidence.outcome-fact.v1"

    plan_line_economic_contract_key: str
    producer_namespace: str
    economic_lineage_id: str
    stage_id: str
    mode: ExecutionMode
    execution_version: str
    cost_version: str
    signal_session: date
    entry_session: date | None
    exit_session: date | None
    classification: Literal[
        "FILLED", "PARTIAL_FILL", "NO_FILL", "EXIT_PENDING", "UNAVAILABLE"
    ]
    entry_quantity_units: int
    exit_quantity_units: int
    entry_gross_cents: int
    exit_gross_cents: int
    fees_cents: int
    realized_pnl_cents: int | None


@dataclass(frozen=True)
class PlanLineDefinition:
    """One pre-registered plan-line economic contract."""

    plan_line_economic_contract_key: str
    producer_namespace: str
    economic_lineage_id: str
    stage_id: str
    family_id: str
    mode: ExecutionMode
    execution_version: str
    cost_version: str
    signal_session: date
    entry_session_ordinal: int = 1
    exit_session_ordinal: int = 10


class OutcomeFinalizer:
    """Mode-bound local preregistration with all evidence commands disabled."""

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
        if not isinstance(execution_mode, ExecutionMode):
            raise OutcomeFinalizerError(
                "execution_mode_invalid",
                "finalizer execution mode must be one exact ExecutionMode",
                actual_mode=repr(execution_mode),
            )
        if (
            signer_capability.artifact is not ArtifactKind.OUTCOME
            or signer_capability.mode is not execution_mode
            or signer_capability.namespace
            != evidence_repository.issuer_namespace
        ):
            raise OutcomeFinalizerError(
                "signer_context_mismatch",
                "signer capability does not match this outcome finalizer",
                expected_artifact=ArtifactKind.OUTCOME.value,
                capability_artifact=signer_capability.artifact.value,
                expected_mode=execution_mode.value,
                capability_mode=signer_capability.mode.value,
                expected_namespace=evidence_repository.issuer_namespace,
                capability_namespace=signer_capability.namespace,
            )
        self._capital_engine = capital_engine
        self._evidence = evidence_repository
        self._spine = session_spine
        self._signer = signer
        self._signer_capability = signer_capability
        self._clock = clock
        self._issuer_namespace = issuer_namespace
        self._behavior_fingerprint = behavior_fingerprint
        self._execution_mode = execution_mode
        self._policy_epoch = policy_epoch
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(self._engine, "connect", _configure_connection)
        with self._engine.begin() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(sa.text(ddl))

    # -- plan lines ----------------------------------------------------------

    def register_plan_line(self, definition: PlanLineDefinition) -> None:
        self._require_execution_mode(definition.mode)
        with self._engine.begin() as conn:
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO plan_lines ("
                        " plan_line_economic_contract_key,"
                        " producer_namespace, economic_lineage_id,"
                        " stage_id, family_id, mode, execution_version,"
                        " cost_version, signal_session,"
                        " entry_session_ordinal, exit_session_ordinal)"
                        " VALUES (:key, :producer, :lineage, :stage,"
                        " :family, :mode, :execution_version,"
                        " :cost_version, :signal_session, :entry_ordinal,"
                        " :exit_ordinal)"
                    ),
                    {
                        "key": (
                            definition.plan_line_economic_contract_key
                        ),
                        "producer": definition.producer_namespace,
                        "lineage": definition.economic_lineage_id,
                        "stage": definition.stage_id,
                        "family": definition.family_id,
                        "mode": definition.mode.value,
                        "execution_version": definition.execution_version,
                        "cost_version": definition.cost_version,
                        "signal_session": (
                            definition.signal_session.isoformat()
                        ),
                        "entry_ordinal": (
                            definition.entry_session_ordinal
                        ),
                        "exit_ordinal": definition.exit_session_ordinal,
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise OutcomeFinalizerError(
                    "plan_line_already_registered",
                    "plan-line contract key is immutable once registered",
                ) from exc

    def _require_execution_mode(self, actual_mode: ExecutionMode) -> None:
        if type(actual_mode) is not ExecutionMode:
            raise OutcomeFinalizerError(
                "execution_mode_invalid",
                "plan-line mode must be one exact ExecutionMode",
                actual_mode=repr(actual_mode),
            )
        if actual_mode is self._execution_mode:
            return
        raise OutcomeFinalizerError(
            "execution_mode_mismatch",
            "plan-line mode is outside this finalizer capability",
            expected_mode=self._execution_mode.value,
            actual_mode=actual_mode.value,
        )

    # -- finalization -----------------------------------------------------------

    def finalize_due(
        self, as_of: datetime, *, program: str
    ) -> tuple[str, ...]:
        """Reject publication before observing any injected dependency."""

        del as_of, program
        raise OutcomeFinalizerError(
            _AUTHORITY_UNAVAILABLE,
            "outcome publication requires authoritative plan-line, calendar,"
            " capital-reducer, and single-writer bindings",
        )

    def revise_outcome(
        self,
        contract_key: str,
        *,
        program: str,
        activation_gate: "ActivationGate",
        fence_manifest_id: str,
    ) -> int | None:
        """Reject revisions before observing the fence or any dependency."""

        del contract_key, program, activation_gate, fence_manifest_id
        raise OutcomeFinalizerError(
            _AUTHORITY_UNAVAILABLE,
            "outcome revision requires authoritative plan-line, calendar,"
            " capital-reducer, and single-writer bindings",
        )

    def outcome_fact(self, contract_key: str) -> OutcomeFact:
        """Reject historical reads before observing any dependency."""

        del contract_key
        raise OutcomeFinalizerError(
            _AUTHORITY_UNAVAILABLE,
            "historical outcomes require an approved migration manifest and"
            " authoritative plan-line input bindings",
        )


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


__all__ = [
    "OutcomeFact",
    "OutcomeFinalizer",
    "OutcomeFinalizerError",
    "PlanLineDefinition",
]
