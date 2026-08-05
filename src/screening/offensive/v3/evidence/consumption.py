"""Attempt, evidence-consumption and multiplicity ledgers (Plan 03 Task 4).

Sample identity is unreusable: one evidence id or one governance-minted
evaluation unit contributes at most one PRIMARY_PROMOTION per research
program, enforced by two INDEPENDENT uniqueness constraints (never one
collapsed four-column key). Every attempt - including failed and
abandoned ones - consumes the governance-wide multiplicity budget, so a
new program/lineage/name cannot escape the global alpha/e-value budget.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Callable, Final

import sqlalchemy as sa


class PromotionRole(StrEnum):
    PRIMARY_PROMOTION = "PRIMARY_PROMOTION"
    DIAGNOSTIC = "DIAGNOSTIC"


class AttemptStatus(StrEnum):
    RESERVED = "RESERVED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"
    CONSUMED = "CONSUMED"


class MultiplicityBudgetKind(StrEnum):
    ALPHA = "ALPHA"
    E_VALUE = "E_VALUE"


_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS attempts (
        attempt_id TEXT PRIMARY KEY,
        research_program_id TEXT NOT NULL,
        economic_lineage_id TEXT NOT NULL,
        family_id TEXT NOT NULL,
        frozen_plan_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        reserved_at TEXT NOT NULL,
        closed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_consumptions (
        consumption_id TEXT PRIMARY KEY,
        research_program_id TEXT NOT NULL,
        evidence_id TEXT,
        governance_minted_evaluation_unit_id TEXT,
        promotion_role TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        consumed_at TEXT NOT NULL,
        payload_hash TEXT NOT NULL
    )
    """,
    # Two INDEPENDENT primary-promotion uniqueness constraints. They are
    # deliberately NOT one four-column key: evidence reuse and
    # evaluation-unit reuse are distinct sample-identity violations.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_consumption_evidence_promotion
    ON evidence_consumptions (
        research_program_id, evidence_id, promotion_role
    )
    WHERE evidence_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_consumption_unit_promotion
    ON evidence_consumptions (
        research_program_id,
        governance_minted_evaluation_unit_id,
        promotion_role
    )
    WHERE governance_minted_evaluation_unit_id IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS multiplicity_budgets (
        budget_kind TEXT PRIMARY KEY,
        total_budget INTEGER NOT NULL,
        consumed INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluation_units (
        governance_minted_evaluation_unit_id TEXT PRIMARY KEY,
        research_program_id TEXT NOT NULL,
        signal_session TEXT NOT NULL,
        minted_at TEXT NOT NULL
    )
    """,
)


class LedgerError(RuntimeError):
    """Fail-closed rejection of a consumption/attempt operation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class Consumption:
    consumption_id: str
    research_program_id: str
    evidence_id: str | None
    governance_minted_evaluation_unit_id: str | None
    promotion_role: PromotionRole
    attempt_id: str
    consumed_at: datetime


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


class _SharedStore:
    """Common SQLite setup for the three ledgers."""

    def __init__(self, database_path: str) -> None:
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(self._engine, "connect", _configure_connection)
        with self._engine.begin() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(sa.text(ddl))

    @property
    def engine(self) -> sa.engine.Engine:
        return self._engine


class GlobalMultiplicityBudgetLedger(_SharedStore):
    """The governance-wide alpha/e-value budget no program can escape."""

    def set_budget(self, kind: MultiplicityBudgetKind, total: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO multiplicity_budgets (budget_kind,"
                    " total_budget, consumed) VALUES (:kind, :total, 0)"
                    " ON CONFLICT(budget_kind) DO UPDATE SET"
                    " total_budget = excluded.total_budget"
                ),
                {"kind": kind.value, "total": total},
            )

    def reserve(self, kind: MultiplicityBudgetKind) -> None:
        """Consume one unit of the global budget; fails closed at cap."""

        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT total_budget, consumed FROM"
                    " multiplicity_budgets WHERE budget_kind = :kind"
                ),
                {"kind": kind.value},
            ).first()
            if row is None:
                raise LedgerError(
                    "budget_not_frozen",
                    "multiplicity budget must be frozen by governance",
                )
            if int(row.consumed) + 1 > int(row.total_budget):
                raise LedgerError(
                    "multiplicity_budget_exhausted",
                    "global budget cannot be exceeded by any program,"
                    " lineage or name",
                )
            conn.execute(
                sa.text(
                    "UPDATE multiplicity_budgets SET consumed = consumed + 1"
                    " WHERE budget_kind = :kind"
                ),
                {"kind": kind.value},
            )

    def consumed(self, kind: MultiplicityBudgetKind) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT consumed FROM multiplicity_budgets"
                    " WHERE budget_kind = :kind"
                ),
                {"kind": kind.value},
            ).first()
        return int(row.consumed) if row is not None else 0


class AttemptLedger(_SharedStore):
    """Attempt reservations; failed/abandoned attempts still consumed."""

    def __init__(
        self,
        database_path: str,
        *,
        budget: GlobalMultiplicityBudgetLedger,
        budget_kind: MultiplicityBudgetKind = MultiplicityBudgetKind.ALPHA,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(database_path)
        self._budget = budget
        self._budget_kind = budget_kind
        self._clock = clock

    def reserve(
        self,
        *,
        attempt_id: str,
        research_program_id: str,
        economic_lineage_id: str,
        family_id: str,
        frozen_plan_hash: str,
    ) -> None:
        """Reserve one attempt; the global budget is consumed in the same
        logical step and never refunded by failure or abandonment."""

        reserved_at = self._clock()
        # Budget first: if the global budget rejects, nothing is reserved.
        self._budget.reserve(self._budget_kind)
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO attempts (attempt_id,"
                        " research_program_id, economic_lineage_id,"
                        " family_id, frozen_plan_hash, status, reserved_at)"
                        " VALUES (:attempt, :program, :lineage, :family,"
                        " :plan, :status, :reserved_at)"
                    ),
                    {
                        "attempt": attempt_id,
                        "program": research_program_id,
                        "lineage": economic_lineage_id,
                        "family": family_id,
                        "plan": frozen_plan_hash,
                        "status": AttemptStatus.RESERVED.value,
                        "reserved_at": reserved_at.isoformat(),
                    },
                )
        except sa.exc.IntegrityError as exc:
            # The attempt row collided; the budget unit stays consumed
            # (failed reservations are not refunded either).
            raise LedgerError(
                "attempt_already_reserved",
                "attempt id already reserved; budget unit consumed",
            ) from exc

    def close(
        self, attempt_id: str, status: AttemptStatus
    ) -> None:
        if status not in (
            AttemptStatus.FAILED,
            AttemptStatus.ABANDONED,
            AttemptStatus.CONSUMED,
        ):
            raise LedgerError(
                "invalid_attempt_close", "attempt cannot close to RESERVED"
            )
        closed_at = self._clock()
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT status FROM attempts WHERE attempt_id = :id"
                ),
                {"id": attempt_id},
            ).first()
            if row is None:
                raise LedgerError(
                    "attempt_unknown", "unknown attempt id"
                )
            if row.status != AttemptStatus.RESERVED.value:
                raise LedgerError(
                    "attempt_already_closed",
                    "attempt status is terminal",
                )
            conn.execute(
                sa.text(
                    "UPDATE attempts SET status = :status,"
                    " closed_at = :closed_at WHERE attempt_id = :id"
                ),
                {
                    "status": status.value,
                    "closed_at": closed_at.isoformat(),
                    "id": attempt_id,
                },
            )

    def status(self, attempt_id: str) -> AttemptStatus:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT status FROM attempts WHERE attempt_id = :id"
                ),
                {"id": attempt_id},
            ).first()
        if row is None:
            raise LedgerError("attempt_unknown", "unknown attempt id")
        return AttemptStatus(row.status)


class EvidenceConsumptionLedger(_SharedStore):
    """Primary-promotion consumption with unreusable sample identity."""

    def __init__(
        self,
        database_path: str,
        *,
        attempts: AttemptLedger,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(database_path)
        self._attempts = attempts
        self._clock = clock

    def consume_primary_promotion(
        self,
        *,
        research_program_id: str,
        attempt_id: str,
        payload_hash: str,
        evidence_id: str | None = None,
        governance_minted_evaluation_unit_id: str | None = None,
    ) -> Consumption:
        """Consume one sample for PRIMARY_PROMOTION.

        Exactly one of evidence id / evaluation unit id must be given. An
        identical retry converges on the original consumption; a retry with
        different content under the same sample identity writes nothing.
        """

        if (evidence_id is None) == (
            governance_minted_evaluation_unit_id is None
        ):
            raise LedgerError(
                "consumption_identity_ambiguous",
                "exactly one sample identity is required",
            )
        if self._attempts.status(attempt_id) is not (
            AttemptStatus.RESERVED
        ):
            raise LedgerError(
                "attempt_not_reserved",
                "consumption requires a live reserved attempt",
            )
        consumed_at = self._clock()
        consumption_id = (
            f"consumption:{research_program_id}:"
            f"{evidence_id or governance_minted_evaluation_unit_id}:"
            f"{PromotionRole.PRIMARY_PROMOTION.value}"
        )
        with self._engine.begin() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT * FROM evidence_consumptions"
                    " WHERE consumption_id = :id"
                ),
                {"id": consumption_id},
            ).first()
            if existing is not None:
                if str(existing.payload_hash) != payload_hash:
                    raise LedgerError(
                        "sample_reuse_conflict",
                        "sample identity already consumed with different"
                        " content; nothing written",
                    )
                return Consumption(
                    consumption_id=str(existing.consumption_id),
                    research_program_id=str(
                        existing.research_program_id
                    ),
                    evidence_id=existing.evidence_id,
                    governance_minted_evaluation_unit_id=(
                        existing.governance_minted_evaluation_unit_id
                    ),
                    promotion_role=PromotionRole(
                        str(existing.promotion_role)
                    ),
                    attempt_id=str(existing.attempt_id),
                    consumed_at=datetime.fromisoformat(
                        str(existing.consumed_at)
                    ),
                )
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO evidence_consumptions ("
                        " consumption_id, research_program_id, evidence_id,"
                        " governance_minted_evaluation_unit_id,"
                        " promotion_role, attempt_id, consumed_at,"
                        " payload_hash)"
                        " VALUES (:id, :program, :evidence, :unit,"
                        " :role, :attempt, :consumed_at, :payload_hash)"
                    ),
                    {
                        "id": consumption_id,
                        "program": research_program_id,
                        "evidence": evidence_id,
                        "unit": governance_minted_evaluation_unit_id,
                        "role": PromotionRole.PRIMARY_PROMOTION.value,
                        "attempt": attempt_id,
                        "consumed_at": consumed_at.isoformat(),
                        "payload_hash": payload_hash,
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise LedgerError(
                    "sample_reuse_conflict",
                    "sample identity already consumed for this program and"
                    " promotion role; nothing written",
                ) from exc
        return Consumption(
            consumption_id=consumption_id,
            research_program_id=research_program_id,
            evidence_id=evidence_id,
            governance_minted_evaluation_unit_id=(
                governance_minted_evaluation_unit_id
            ),
            promotion_role=PromotionRole.PRIMARY_PROMOTION,
            attempt_id=attempt_id,
            consumed_at=consumed_at,
        )

    def reserve_evaluation_units(
        self,
        *,
        research_program_id: str,
        signal_session: str,
        count: int,
    ) -> tuple[str, ...]:
        """Mint governance evaluation units for one decision day.

        Units are minted by governance, never by producers; each call
        mints a fresh disjoint set (concurrent reservations never collide).
        """

        if count < 1:
            raise LedgerError(
                "unit_count_invalid", "at least one unit is required"
            )
        minted_at = self._clock()
        unit_ids: list[str] = []
        with self._engine.begin() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT COUNT(*) AS n FROM evaluation_units"
                )
            ).one().n
            for index in range(count):
                unit_id = (
                    f"unit:{research_program_id}:{signal_session}:"
                    f"{int(existing) + index + 1}"
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO evaluation_units ("
                        " governance_minted_evaluation_unit_id,"
                        " research_program_id, signal_session, minted_at)"
                        " VALUES (:unit, :program, :session, :minted_at)"
                    ),
                    {
                        "unit": unit_id,
                        "program": research_program_id,
                        "session": signal_session,
                        "minted_at": minted_at.isoformat(),
                    },
                )
                unit_ids.append(unit_id)
        return tuple(unit_ids)


__all__ = [
    "AttemptLedger",
    "AttemptStatus",
    "Consumption",
    "EvidenceConsumptionLedger",
    "GlobalMultiplicityBudgetLedger",
    "LedgerError",
    "MultiplicityBudgetKind",
    "PromotionRole",
]
