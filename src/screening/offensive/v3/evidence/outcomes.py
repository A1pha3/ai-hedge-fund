"""Outcome Finalizer: mode-pure matured outcomes (Plan 03 Task 3).

The finalizer reads Plan 02 capital truth (fill executions, fees, lots)
and the enrolled session spine, and emits one outcome per plan-line
economic contract when the exit horizon matures. Partial fills, fee
revisions and corrections of one plan-line contract count as ONE mature
outcome; decision-day evaluation units are a separate governance count
and are never produced here. Raw daily closes never enter outcome
economics: only executed fill legs do.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Final, Literal

import sqlalchemy as sa
from pydantic import ValidationError

from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    ExecutionMode,
    SignedEnvelope,
)
from src.screening.offensive.v3.contracts.base import (
    CanonicalModel,
    EvidenceScope,
)
from src.screening.offensive.v3.contracts.evidence import (
    OutcomeEvidence,
    ProviderPublicationState,
    SUPPORTED_SCHEMA_MAJOR,
)
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
)


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
        self._capital_engine = capital_engine
        self._evidence = evidence_repository
        self._spine = session_spine
        self._signer = signer
        self._clock = clock
        self._issuer_namespace = issuer_namespace
        self._behavior_fingerprint = behavior_fingerprint
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

    def _plan_lines(self, conn: sa.engine.Connection):
        return conn.execute(
            sa.text("SELECT * FROM plan_lines ORDER BY signal_session")
        ).all()

    def _finalized(self, conn: sa.engine.Connection, contract_key: str):
        return conn.execute(
            sa.text(
                "SELECT * FROM finalized_plan_lines"
                " WHERE plan_line_economic_contract_key = :key"
            ),
            {"key": contract_key},
        ).first()

    # -- session calendar ------------------------------------------------------

    def _sessions_after(
        self, program: str, signal_session: date
    ) -> list[date]:
        """Enrolled session dates strictly after the signal session."""

        with self._spine._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT signal_session FROM expected_sessions"
                    " WHERE research_program_id = :program"
                    " AND signal_session > :session"
                    " ORDER BY signal_session"
                ),
                {
                    "program": program,
                    "session": signal_session.isoformat(),
                },
            ).all()
        return [date.fromisoformat(str(row.signal_session)) for row in rows]

    def _entry_exit_sessions(
        self, program: str, definition: PlanLineDefinition
    ) -> tuple[date | None, date | None]:
        sessions = self._sessions_after(
            program, definition.signal_session
        )
        entry = (
            sessions[definition.entry_session_ordinal - 1]
            if len(sessions) >= definition.entry_session_ordinal
            else None
        )
        exit_index = (
            definition.entry_session_ordinal
            + definition.exit_session_ordinal
            - 1
        )
        exit_ = (
            sessions[exit_index - 1] if len(sessions) >= exit_index else None
        )
        return entry, exit_

    # -- capital read model ------------------------------------------------------

    def _lot_fills(self, lineage: str) -> dict[str, dict[str, object]]:
        """Lot -> fill facts for one lineage from the capital ledger."""

        with self._capital_engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT e.economic_event_id AS event_id,"
                    " e.payload_json AS payload_json,"
                    " e.execution_mode AS execution_mode,"
                    " e.effective_at AS effective_at,"
                    " e.position_lineage_id AS lineage,"
                    " e.economic_lot_id AS lot,"
                    " l.asset_kind AS asset_kind,"
                    " l.direction AS direction,"
                    " l.cash_amount_cents AS cash_amount_cents,"
                    " l.quantity_units AS quantity_units"
                    " FROM economic_events e"
                    " JOIN economic_event_legs l"
                    " ON l.economic_event_id = e.economic_event_id"
                    " WHERE e.position_lineage_id = :lineage"
                    " AND e.event_kind IN ('TRADE_EXECUTED',"
                    " 'LATE_CORRECTION', 'FEE_CHARGED')"
                ),
                {"lineage": lineage},
            ).all()
        lots: dict[str, dict[str, object]] = {}
        for row in rows:
            lot = lots.setdefault(
                str(row.lot),
                {
                    "entry_quantity": 0,
                    "exit_quantity": 0,
                    "entry_gross": 0,
                    "exit_gross": 0,
                    "fees": 0,
                    "entry_effective": None,
                    "entry_mode": None,
                },
            )
            payload = json.loads(str(row.payload_json))
            revision = payload.get("execution_revision") or {}
            fact_kind = revision.get("fact_kind")
            kind = revision.get("revision_kind")
            if fact_kind == "FEE":
                continue  # fees are measured per order, not per lot
            if kind == "BUSTED":
                # Busted fills leave no active contribution: remove what
                # the superseded fact booked.
                side = revision.get("side")
                quantity = int(revision.get("superseded_quantity") or 0)
                gross = int(revision.get("superseded_gross_cents") or 0)
                if side == "ENTRY":
                    lot["entry_quantity"] = int(lot["entry_quantity"]) - quantity
                    lot["entry_gross"] = int(lot["entry_gross"]) - gross
                else:
                    lot["exit_quantity"] = int(lot["exit_quantity"]) - quantity
                    lot["exit_gross"] = int(lot["exit_gross"]) - gross
                continue
            if kind == "CORRECTED":
                side = revision.get("side")
                superseded_quantity = int(
                    revision.get("superseded_quantity") or 0
                )
                superseded_gross = int(
                    revision.get("superseded_gross_cents") or 0
                )
                corrected_quantity = int(
                    revision.get("corrected_quantity") or 0
                )
                corrected_gross = int(
                    revision.get("corrected_gross_cents") or 0
                )
                if side == "ENTRY":
                    lot["entry_quantity"] = (
                        int(lot["entry_quantity"])
                        - superseded_quantity
                        + corrected_quantity
                    )
                    lot["entry_gross"] = (
                        int(lot["entry_gross"])
                        - superseded_gross
                        + corrected_gross
                    )
                else:
                    lot["exit_quantity"] = (
                        int(lot["exit_quantity"])
                        - superseded_quantity
                        + corrected_quantity
                    )
                    lot["exit_gross"] = (
                        int(lot["exit_gross"])
                        - superseded_gross
                        + corrected_gross
                    )
                continue
            asset_kind = str(row.asset_kind)
            direction = str(row.direction)
            if str(row.execution_mode) not in (
                ExecutionMode.RESEARCH_RECONSTRUCTION.value,
                ExecutionMode.DAILY_BAR_PROXY.value,
                ExecutionMode.MANUAL_CONFIRMED.value,
                ExecutionMode.BROKER_CONFIRMED.value,
            ):
                continue
            if asset_kind == "CASH":
                amount = int(row.cash_amount_cents or 0)
                if direction == "DEBIT":
                    lot["entry_gross"] = int(lot["entry_gross"]) + amount
                    if lot["entry_effective"] is None:
                        lot["entry_effective"] = str(row.effective_at)
                        lot["entry_mode"] = str(row.execution_mode)
                else:
                    lot["exit_gross"] = int(lot["exit_gross"]) + amount
            elif asset_kind == "SECURITY":
                quantity = int(row.quantity_units or 0)
                if direction == "CREDIT":
                    lot["entry_quantity"] = (
                        int(lot["entry_quantity"]) + quantity
                    )
                    if lot["entry_effective"] is None:
                        lot["entry_effective"] = str(row.effective_at)
                        lot["entry_mode"] = str(row.execution_mode)
                else:
                    lot["exit_quantity"] = (
                        int(lot["exit_quantity"]) + quantity
                    )
        return lots

    def _order_fees(self, order_ids: tuple[str, ...]) -> int:
        if not order_ids:
            return 0
        with self._capital_engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT er.order_id AS order_id,"
                    " e.payload_json AS payload_json,"
                    " l.asset_kind AS asset_kind,"
                    " l.direction AS direction,"
                    " l.cash_amount_cents AS cash_amount_cents"
                    " FROM execution_revisions er"
                    " JOIN economic_events e"
                    " ON e.payload_content_hash = er.payload_content_hash"
                    " JOIN economic_event_legs l"
                    " ON l.economic_event_id = e.economic_event_id"
                    " WHERE er.revision_kind IN ('FEE', 'FEE_BUST',"
                    " 'FEE_CORRECTION')"
                )
            ).all()
        fees = 0
        for row in rows:
            if str(row.order_id) not in order_ids:
                continue
            if str(row.asset_kind) != "CASH":
                continue
            amount = int(row.cash_amount_cents or 0)
            if str(row.direction) == "DEBIT":
                fees += amount
            else:
                fees -= amount
        return fees

    def _order_ids_for_lineage(self, lineage: str) -> tuple[str, ...]:
        with self._capital_engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT DISTINCT er.order_id AS order_id"
                    " FROM execution_revisions er"
                    " JOIN economic_events e"
                    " ON e.payload_content_hash = er.payload_content_hash"
                    " WHERE e.position_lineage_id = :lineage"
                    " AND er.order_id IS NOT NULL"
                ),
                {"lineage": lineage},
            ).all()
        return tuple(str(row.order_id) for row in rows)

    # -- finalization -----------------------------------------------------------

    def finalize_due(
        self, as_of: datetime, *, program: str
    ) -> tuple[str, ...]:
        """Finalize every due plan line; returns finalized contract keys."""

        finalized: list[str] = []
        with self._engine.connect() as conn:
            plan_lines = self._plan_lines(conn)
        for row in plan_lines:
            definition = PlanLineDefinition(
                plan_line_economic_contract_key=(
                    row.plan_line_economic_contract_key
                ),
                producer_namespace=row.producer_namespace,
                economic_lineage_id=row.economic_lineage_id,
                stage_id=row.stage_id,
                family_id=row.family_id,
                mode=ExecutionMode(row.mode),
                execution_version=row.execution_version,
                cost_version=row.cost_version,
                signal_session=date.fromisoformat(row.signal_session),
                entry_session_ordinal=int(row.entry_session_ordinal),
                exit_session_ordinal=int(row.exit_session_ordinal),
            )
            if self._finalize_plan_line(as_of, definition, program):
                finalized.append(
                    definition.plan_line_economic_contract_key
                )
        return tuple(finalized)

    def _finalize_plan_line(
        self,
        as_of: datetime,
        definition: PlanLineDefinition,
        program: str,
    ) -> bool:
        with self._engine.begin() as conn:
            existing = self._finalized(
                conn, definition.plan_line_economic_contract_key
            )
        if existing is not None:
            return False
        entry_session, exit_session = self._entry_exit_sessions(
            program, definition
        )
        if entry_session is None or exit_session is None:
            fact = self._build_fact(
                definition, entry_session, exit_session, "UNAVAILABLE"
            )
        elif exit_session > as_of.date():
            return False  # not due yet
        else:
            fact = self._measure(definition, entry_session, exit_session)
        if fact.classification == "EXIT_PENDING":
            # The exit may still land (late fills are legitimate): a
            # pending line stays unfinalized and is rechecked later. It
            # contributes no mature outcome until it resolves.
            return False
        evidence_id = (
            f"outcome:{definition.plan_line_economic_contract_key}"
        )
        record = self._publish_fact(
            fact, evidence_id, exit_session or definition.signal_session
        )
        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO finalized_plan_lines ("
                    " plan_line_economic_contract_key,"
                    " outcome_evidence_id, finality, revision,"
                    " finalized_at)"
                    " VALUES (:key, :evidence_id, :finality, 1, :at)"
                ),
                {
                    "key": (
                        definition.plan_line_economic_contract_key
                    ),
                    "evidence_id": evidence_id,
                    "finality": fact.classification,
                    "at": as_of.isoformat(),
                },
            )
        return True

    def _measure(
        self,
        definition: PlanLineDefinition,
        entry_session: date,
        exit_session: date,
    ) -> OutcomeFact:
        lots = self._lot_fills(definition.economic_lineage_id)
        entry_quantity = 0
        exit_quantity = 0
        entry_gross = 0
        exit_gross = 0
        for lot in lots.values():
            effective = lot.get("entry_effective")
            if effective is None:
                continue
            effective_date = datetime.fromisoformat(
                str(effective)
            ).date()
            if effective_date != entry_session:
                continue
            if lot.get("entry_mode") != definition.mode.value:
                continue  # mode-pure: other modes never enter this outcome
            entry_quantity += int(lot["entry_quantity"])  # type: ignore
            exit_quantity += int(lot["exit_quantity"])  # type: ignore
            entry_gross += int(lot["entry_gross"])  # type: ignore
            exit_gross += int(lot["exit_gross"])  # type: ignore
        fees = self._order_fees(
            self._order_ids_for_lineage(definition.economic_lineage_id)
        )
        if entry_quantity <= 0:
            classification = "NO_FILL"
            realized: int | None = None
        elif exit_quantity <= 0:
            classification = "EXIT_PENDING"
            realized = None
        elif exit_quantity < entry_quantity:
            classification = "PARTIAL_FILL"
            realized = exit_gross - entry_gross - fees
        else:
            classification = "FILLED"
            realized = exit_gross - entry_gross - fees
        return OutcomeFact(
            plan_line_economic_contract_key=(
                definition.plan_line_economic_contract_key
            ),
            producer_namespace=definition.producer_namespace,
            economic_lineage_id=definition.economic_lineage_id,
            stage_id=definition.stage_id,
            mode=definition.mode,
            execution_version=definition.execution_version,
            cost_version=definition.cost_version,
            signal_session=definition.signal_session,
            entry_session=entry_session,
            exit_session=exit_session,
            classification=classification,
            entry_quantity_units=entry_quantity,
            exit_quantity_units=exit_quantity,
            entry_gross_cents=entry_gross,
            exit_gross_cents=exit_gross,
            fees_cents=fees,
            realized_pnl_cents=realized,
        )

    def _build_fact(
        self,
        definition: PlanLineDefinition,
        entry_session: date | None,
        exit_session: date | None,
        classification: str,
    ) -> OutcomeFact:
        return OutcomeFact(
            plan_line_economic_contract_key=(
                definition.plan_line_economic_contract_key
            ),
            producer_namespace=definition.producer_namespace,
            economic_lineage_id=definition.economic_lineage_id,
            stage_id=definition.stage_id,
            mode=definition.mode,
            execution_version=definition.execution_version,
            cost_version=definition.cost_version,
            signal_session=definition.signal_session,
            entry_session=entry_session,
            exit_session=exit_session,
            classification=classification,  # type: ignore[arg-type]
            entry_quantity_units=0,
            exit_quantity_units=0,
            entry_gross_cents=0,
            exit_gross_cents=0,
            fees_cents=0,
            realized_pnl_cents=None,
        )

    def revise_outcome(
        self, contract_key: str, *, program: str
    ) -> int | None:
        """Re-measure a finalized plan line after capital revisions.

        A bust/correction that changes the economic facts appends an
        outcome revision (the original outcome is never rewritten).
        Returns the new revision, or None when nothing changed.
        """

        with self._engine.begin() as conn:
            finalized = self._finalized(conn, contract_key)
            if finalized is None:
                raise OutcomeFinalizerError(
                    "outcome_unknown", "plan line not finalized"
                )
            plan_row = conn.execute(
                sa.text(
                    "SELECT * FROM plan_lines"
                    " WHERE plan_line_economic_contract_key = :key"
                ),
                {"key": contract_key},
            ).one()
        definition = PlanLineDefinition(
            plan_line_economic_contract_key=(
                plan_row.plan_line_economic_contract_key
            ),
            producer_namespace=plan_row.producer_namespace,
            economic_lineage_id=plan_row.economic_lineage_id,
            stage_id=plan_row.stage_id,
            family_id=plan_row.family_id,
            mode=ExecutionMode(plan_row.mode),
            execution_version=plan_row.execution_version,
            cost_version=plan_row.cost_version,
            signal_session=date.fromisoformat(plan_row.signal_session),
            entry_session_ordinal=int(plan_row.entry_session_ordinal),
            exit_session_ordinal=int(plan_row.exit_session_ordinal),
        )
        entry_session, exit_session = self._entry_exit_sessions(
            program, definition
        )
        fact = self._measure(definition, entry_session, exit_session)
        record = self._evidence.get(
            str(finalized.outcome_evidence_id)
        )
        current_fact = self._read_fact(record)
        if current_fact == fact:
            return None
        signed, payload = self._envelope_for(
            fact,
            str(finalized.outcome_evidence_id),
            exit_session or definition.signal_session,
        )
        prepared = self._evidence.prepare_revision(signed, payload)
        self._evidence.activate_revision(
            str(prepared.evidence.evidence_id), prepared.revision
        )
        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE finalized_plan_lines SET finality = :finality,"
                    " revision = :revision"
                    " WHERE plan_line_economic_contract_key = :key"
                ),
                {
                    "finality": fact.classification,
                    "revision": prepared.revision,
                    "key": contract_key,
                },
            )
        return prepared.revision

    def _envelope_for(
        self,
        fact: OutcomeFact,
        evidence_id: str,
        effective_session: date,
    ) -> tuple[SignedEnvelope, bytes]:
        """Sign one outcome envelope binding the durable fact bytes."""

        import hashlib

        fact_bytes = fact.model_dump_json().encode("utf-8")
        fact_hash = self._evidence.persist_payload(fact_bytes)
        if hashlib.sha256(fact_bytes).hexdigest() != fact_hash:
            raise OutcomeFinalizerError(
                "fact_hash_mismatch", "fact bytes do not hash as expected"
            )
        as_of = self._clock()
        envelope = OutcomeEvidence(
            evidence_id=evidence_id,
            subject_scope=EvidenceScope.STRATEGY_LINEAGE,
            subject_producer=fact.producer_namespace,
            family_id=(
                fact.plan_line_economic_contract_key.split(":")[-1]
                if ":" in fact.plan_line_economic_contract_key
                else fact.economic_lineage_id
            ),
            strategy_semver="3.0.0",
            behavior_fingerprint=self._behavior_fingerprint,
            policy_epoch=self._policy_epoch,
            execution_version=fact.execution_version,
            cost_version=fact.cost_version,
            effective_at=datetime.combine(
                effective_session, datetime.min.time(), tzinfo=None
            ).replace(tzinfo=timezone.utc),
            provider_published_at=ProviderPublicationState.UNKNOWN,
            observed_at=as_of,
            available_at=as_of,
            mode=fact.mode,
            source_authority=self._issuer_namespace,
            payload_content_hash=fact_hash,
            schema_major=SUPPORTED_SCHEMA_MAJOR,
            evidence_kind="outcome",
        )
        payload = envelope.model_dump_json().encode("utf-8")
        return self._signer(payload), payload

    def _publish_fact(
        self,
        fact: OutcomeFact,
        evidence_id: str,
        effective_session: date,
    ):
        signed, payload = self._envelope_for(
            fact, evidence_id, effective_session
        )
        return self._evidence.publish(signed, payload)

    def _read_fact(self, record) -> OutcomeFact:
        fact_hash = record.evidence.payload_content_hash
        return OutcomeFact.model_validate_json(
            self._evidence.raw_payload(fact_hash)
        )

    def outcome_fact(self, contract_key: str) -> OutcomeFact:
        """The current committed outcome fact for one plan line."""

        with self._engine.connect() as conn:
            finalized = self._finalized(conn, contract_key)
        if finalized is None:
            raise OutcomeFinalizerError(
                "outcome_unknown", "plan line not finalized"
            )
        record = self._evidence.get(str(finalized.outcome_evidence_id))
        return self._read_fact(record)


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
