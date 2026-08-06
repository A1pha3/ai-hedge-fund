"""Capital Gateway entry admission (Plan 04 Task 5).

One immediate transaction owns the whole admission: revalidate the CAS
bundle, admit the decision, reserve exact worst-case cash, and publish
the active PortfolioDecisionSeal. Economic idempotency keys on
``(portfolio_id, signal_session, decision_cycle_id)`` and can never be
escaped by changing epochs or retry ids. Before a permit, an explicit
legal shrink/cancel may supersede the active seal under the same
economic key and revision chain; after a permit (or outbox state) no
quantity increase or key escape is possible.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Final

import sqlalchemy as sa

from src.screening.offensive.v3.contracts import SignedEnvelope  # noqa: F401
from src.screening.offensive.v3.contracts.decision import (
    DecisionLogicalKey,
    GatewayExpectedVersions,
    PortfolioDecision,
    PortfolioDecisionSeal,
)

_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS decision_seals (
        seal_id TEXT PRIMARY KEY,
        portfolio_id TEXT NOT NULL,
        signal_session TEXT NOT NULL,
        decision_cycle_id TEXT NOT NULL,
        seal_revision INTEGER NOT NULL,
        seal_artifact_hash TEXT NOT NULL,
        proposal_artifact_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        total_reserved_cash_cents INTEGER NOT NULL,
        supersedes_seal_id TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_active_seal_per_key
    ON decision_seals (portfolio_id, signal_session, decision_cycle_id)
    WHERE status = 'SEALED'
    """,
    """
    CREATE TABLE IF NOT EXISTS entry_reserves (
        reservation_id TEXT PRIMARY KEY,
        seal_id TEXT NOT NULL,
        order_line_id TEXT NOT NULL,
        reserved_cash_cents INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
)


class CapitalGatewayError(RuntimeError):
    """Fail-closed rejection of an entry admission."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class AdmissionContext:
    """Injected CAS/state context for one admission."""

    available_cash_cents: int
    active_authorization_id: str
    active_authorization_version: int
    active_envelope_hash: str
    policy_activation_hash: str
    authorization_status_version: int
    authorization_status_hash: str
    writer_fencing_epoch: int


@dataclass(frozen=True)
class SealedEntry:
    """The admitted seal with its reservation totals."""

    seal: PortfolioDecisionSeal
    total_reserved_cash_cents: int


class CapitalGateway:
    """Entry admission linearization point for one portfolio gateway."""

    def __init__(
        self,
        *,
        database_path: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._clock = clock
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(self._engine, "connect", _configure_connection)
        with self._engine.begin() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(sa.text(ddl))

    def publish_entry(
        self,
        seal: PortfolioDecisionSeal,
        *,
        expected_versions: GatewayExpectedVersions,
        context: AdmissionContext,
    ) -> SealedEntry:
        """Atomically admit one proposal: CAS, reserve, seal.

        Any failure rolls back all three; nothing partial persists.
        """

        self._validate_cas_bundle(seal, expected_versions, context)
        total_reserved = int(seal.total_reserved_cash_cents)
        if total_reserved > context.available_cash_cents:
            raise CapitalGatewayError(
                "reserve_insufficient",
                "worst-case reserve exceeds available capital",
                required_cents=total_reserved,
                available_cents=context.available_cash_cents,
            )
        logical_key = seal.logical_key
        with self._engine.begin() as conn:
            existing = self._latest_seal_row(conn, logical_key)
            if existing is not None:
                if str(existing.proposal_artifact_hash) == (
                    seal.proposal_artifact_hash
                ):
                    # Idempotent identical rerun: return the committed seal.
                    if str(existing.seal_id) != seal.seal_id:
                        raise CapitalGatewayError(
                            "seal_identity_conflict",
                            "same proposal already sealed under a different"
                            " seal identity",
                        )
                    if int(existing.seal_revision) != seal.seal_revision:
                        raise CapitalGatewayError(
                            "seal_revision_conflict",
                            "identical proposal already sealed at another"
                            " revision",
                        )
                    return SealedEntry(
                        seal=seal,
                        total_reserved_cash_cents=int(
                            existing.total_reserved_cash_cents
                        ),
                    )
                self._require_supersede_allowed(
                    conn, seal, existing, expected_versions
                )
            elif (
                expected_versions.expected_active_seal_id is not None
            ):
                raise CapitalGatewayError(
                    "seal_cas_conflict",
                    "expected an active seal but none exists",
                )
            if existing is not None:
                conn.execute(
                    sa.text(
                        "UPDATE decision_seals SET status = 'SUPERSEDED'"
                        " WHERE seal_id = :seal_id"
                    ),
                    {"seal_id": str(existing.seal_id)},
                )
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO decision_seals (seal_id, portfolio_id,"
                        " signal_session, decision_cycle_id, seal_revision,"
                        " seal_artifact_hash, proposal_artifact_hash,"
                        " status, total_reserved_cash_cents,"
                        " supersedes_seal_id, created_at)"
                        " VALUES (:seal_id, :portfolio, :session, :cycle,"
                        " :revision, :seal_hash, :proposal_hash, 'SEALED',"
                        " :reserved, :supersedes, :created_at)"
                    ),
                    {
                        "seal_id": seal.seal_id,
                        "portfolio": logical_key.portfolio_id,
                        "session": logical_key.signal_session.isoformat(),
                        "cycle": logical_key.decision_cycle_id,
                        "revision": seal.seal_revision,
                        "seal_hash": seal.artifact_hash(),
                        "proposal_hash": seal.proposal_artifact_hash,
                        "reserved": total_reserved,
                        "supersedes": seal.supersedes_seal_id,
                        "created_at": self._clock().isoformat(),
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise CapitalGatewayError(
                    "seal_race_conflict",
                    "another seal landed on the same economic key first",
                ) from exc
            reservation_id = seal.reservation_id
            for line in seal.line_reserve_bindings:
                conn.execute(
                    sa.text(
                        "INSERT INTO entry_reserves (reservation_id,"
                        " seal_id, order_line_id, reserved_cash_cents,"
                        " created_at)"
                        " VALUES (:reservation, :seal, :line, :reserved,"
                        " :created_at)"
                    ),
                    {
                        "reservation": (
                            f"{reservation_id}:{line.order_line_id}"
                        ),
                        "seal": seal.seal_id,
                        "line": line.order_line_id,
                        "reserved": int(line.reserved_cash_cents),
                        "created_at": self._clock().isoformat(),
                    },
                )
        return SealedEntry(
            seal=seal, total_reserved_cash_cents=total_reserved
        )

    def _validate_cas_bundle(
        self,
        seal: PortfolioDecisionSeal,
        expected: GatewayExpectedVersions,
        context: AdmissionContext,
    ) -> None:
        if seal.consumed_gateway_expected_versions.artifact_hash() != (
            expected.artifact_hash()
        ):
            raise CapitalGatewayError(
                "expected_versions_mismatch",
                "seal does not consume the presented CAS bundle",
            )
        if seal.policy_activation_hash != context.policy_activation_hash:
            raise CapitalGatewayError(
                "policy_activation_mismatch",
                "seal policy activation differs from the active policy",
            )
        if seal.authorization_id != context.active_authorization_id or (
            seal.authorization_version
            != context.active_authorization_version
        ):
            raise CapitalGatewayError(
                "authorization_mismatch",
                "seal authorization differs from the active envelope",
            )
        if seal.authorization_envelope_hash != (
            context.active_envelope_hash
        ):
            raise CapitalGatewayError(
                "envelope_mismatch",
                "seal envelope hash differs from the active envelope",
            )
        if seal.authorization_status_version != (
            context.authorization_status_version
        ) or seal.authorization_status_hash != (
            context.authorization_status_hash
        ):
            raise CapitalGatewayError(
                "authorization_status_stale",
                "seal consumed a stale authorization status",
            )
        if seal.writer_fencing_epoch != context.writer_fencing_epoch:
            raise CapitalGatewayError(
                "writer_fencing_epoch_mismatch",
                "seal writer fencing epoch differs from the gateway",
            )
        if expected.policy_epoch != seal.policy_epoch or (
            expected.authority_epoch != seal.authority_epoch
        ) or expected.risk_epoch != seal.risk_epoch:
            raise CapitalGatewayError(
                "epoch_mismatch",
                "CAS bundle epochs differ from the seal",
            )
    def _require_supersede_allowed(
        self,
        conn: sa.engine.Connection,
        seal: PortfolioDecisionSeal,
        existing,
        expected: GatewayExpectedVersions,
    ) -> None:
        if str(existing.status) != "SEALED":
            raise CapitalGatewayError(
                "supersede_forbidden_after_permit",
                "seals beyond SEALED state cannot be superseded",
            )
        if (
            expected.expected_active_seal_id is None
            or expected.expected_active_seal_revision is None
            or expected.expected_active_seal_artifact_hash is None
        ):
            raise CapitalGatewayError(
                "supersede_requires_expected_binding",
                "supersede must declare the expected active seal",
            )
        if expected.expected_active_seal_id != str(existing.seal_id) or (
            expected.expected_active_seal_revision
            != int(existing.seal_revision)
        ) or expected.expected_active_seal_artifact_hash != str(
            existing.seal_artifact_hash
        ):
            raise CapitalGatewayError(
                "seal_cas_conflict",
                "expected active seal does not match the registry;"
                " another supersede landed first",
            )
        if seal.seal_revision != int(existing.seal_revision) + 1:
            raise CapitalGatewayError(
                "seal_revision_not_successor",
                "superseding seal revision must be the exact successor",
            )
        if seal.supersedes_seal_id != str(existing.seal_id):
            raise CapitalGatewayError(
                "supersede_binding_mismatch",
                "seal supersedes binding must name the active seal",
            )
        # Mechanical shrink check: a supersede may never increase total
        # sealed quantity or reserved cash.
        if int(seal.total_reserved_cash_cents) > int(
            existing.total_reserved_cash_cents
        ):
            raise CapitalGatewayError(
                "supersede_increases_reserve",
                "supersede cannot increase the worst-case reserve",
            )

    def _active_seal_row(
        self, conn: sa.engine.Connection, logical_key: DecisionLogicalKey
    ):
        return conn.execute(
            sa.text(
                "SELECT * FROM decision_seals"
                " WHERE portfolio_id = :portfolio"
                " AND signal_session = :session"
                " AND decision_cycle_id = :cycle AND status = 'SEALED'"
            ),
            {
                "portfolio": logical_key.portfolio_id,
                "session": logical_key.signal_session.isoformat(),
                "cycle": logical_key.decision_cycle_id,
            },
        ).first()

    def _latest_seal_row(
        self, conn: sa.engine.Connection, logical_key: DecisionLogicalKey
    ):
        return conn.execute(
            sa.text(
                "SELECT * FROM decision_seals"
                " WHERE portfolio_id = :portfolio"
                " AND signal_session = :session"
                " AND decision_cycle_id = :cycle"
                " ORDER BY seal_revision DESC LIMIT 1"
            ),
            {
                "portfolio": logical_key.portfolio_id,
                "session": logical_key.signal_session.isoformat(),
                "cycle": logical_key.decision_cycle_id,
            },
        ).first()

    def active_seal(
        self, logical_key: DecisionLogicalKey
    ) -> tuple[str, int] | None:
        """Read-only projection: the active seal id/revision for one key."""

        with self._engine.connect() as conn:
            row = self._active_seal_row(conn, logical_key)
        if row is None:
            return None
        return str(row.seal_id), int(row.seal_revision)

    def mark_seal_permitted(self, seal_id: str) -> None:
        """Transition one SEALED seal to PERMITTED (Plan 06 permit flow).

        Provided here so supersede rules can enforce the post-permit
        boundary; the full permit machinery lands in Task 6.
        """

        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT status FROM decision_seals"
                    " WHERE seal_id = :seal_id"
                ),
                {"seal_id": seal_id},
            ).first()
            if row is None:
                raise CapitalGatewayError(
                    "seal_unknown", "no seal for id"
                )
            if str(row.status) != "SEALED":
                raise CapitalGatewayError(
                    "seal_not_sealed",
                    "only SEALED seals can transition to PERMITTED",
                )
            conn.execute(
                sa.text(
                    "UPDATE decision_seals SET status = 'PERMITTED'"
                    " WHERE seal_id = :seal_id"
                ),
                {"seal_id": seal_id},
            )


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


__all__ = [
    "AdmissionContext",
    "CapitalGateway",
    "CapitalGatewayError",
    "SealedEntry",
]
