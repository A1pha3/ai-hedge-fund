"""Governance issuer for EXPLORATION/RECOVERY candidates (Plan 03 Task 6).

Governance alone signs EXPLORATION and RECOVERY envelopes; the Authorizer
cannot, and vice versa. EXPLORATION is BROKER_CONFIRMED-only and declares
restricted evidence collection, never a live edge; its aggregate gross cap
is 2% of NAV and renewals must reference the prior exploration. RECOVERY
cites existing grants/assessments and ALL inherited risk/loss versions and
never mints a new grant. Every candidate stays INACTIVE until the Plan 04
Capital Gateway activates it. A failed external signer leaves nothing
behind; retries are deterministic.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Callable, Final

import sqlalchemy as sa

from src.screening.offensive.v3.contracts import SignedEnvelope
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.evidence.consumption import (
    AttemptLedger,
    AttemptStatus,
    EvidenceConsumptionLedger,
    LedgerError,
)

EXPLORATION_AGGREGATE_CAP: Final = Fraction(Decimal("0.02"))

_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS governance_envelopes (
        authorization_id TEXT PRIMARY KEY,
        portfolio_id TEXT NOT NULL,
        authorization_kind TEXT NOT NULL,
        envelope_hash TEXT NOT NULL,
        signed_envelope_json TEXT NOT NULL,
        status TEXT NOT NULL,
        issued_at TEXT NOT NULL,
        predecessor_authorization_id TEXT
    )
    """,
)


class IssuerError(RuntimeError):
    """Fail-closed rejection of a governance issuance."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class ExplorationIssuanceRequest:
    envelope: CapitalAuthorizationEnvelope
    research_program_id: str
    attempt_id: str
    sample_evidence_id: str | None = None
    sample_evaluation_unit_id: str | None = None
    renewal_of_authorization_id: str | None = None


@dataclass(frozen=True)
class RecoveryIssuanceRequest:
    envelope: CapitalAuthorizationEnvelope
    research_program_id: str
    attempt_id: str
    inherited_authorization_id: str
    inherited_risk_epoch: int
    inherited_stage_loss_version: int
    sample_evidence_id: str | None = None
    sample_evaluation_unit_id: str | None = None


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


class GovernanceIssuer:
    """Signs EXPLORATION/RECOVERY envelope candidates; never EDGE."""

    def __init__(
        self,
        *,
        database_path: str,
        signer: Callable[[bytes], SignedEnvelope],
        clock: Callable[[], datetime],
        attempts: AttemptLedger,
        consumption: EvidenceConsumptionLedger,
    ) -> None:
        self._signer = signer
        self._clock = clock
        self._attempts = attempts
        self._consumption = consumption
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(self._engine, "connect", _configure_connection)
        with self._engine.begin() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(sa.text(ddl))

    def _consume_budgets(
        self,
        envelope: CapitalAuthorizationEnvelope,
        *,
        research_program_id: str,
        attempt_id: str,
        sample_evidence_id: str | None,
        sample_evaluation_unit_id: str | None,
    ) -> None:
        """Consume sample/attempt budgets after a successful signature.

        A failed signer leaves no consumption; a consumption failure
        discards the signed bytes and records no envelope.
        """

        try:
            self._consumption.consume_primary_promotion(
                research_program_id=research_program_id,
                attempt_id=attempt_id,
                payload_hash=envelope.artifact_hash(),
                evidence_id=sample_evidence_id,
                governance_minted_evaluation_unit_id=(
                    sample_evaluation_unit_id
                ),
            )
        except LedgerError as exc:
            raise IssuerError(
                "sample_reuse",
                "sample identity already consumed; issuance rejected",
                reason=exc.code,
            ) from exc
        self._attempts.close(attempt_id, AttemptStatus.CONSUMED)

    def _record(
        self,
        envelope: CapitalAuthorizationEnvelope,
        signed: SignedEnvelope,
        *,
        predecessor_authorization_id: str | None,
    ) -> None:
        now = self._clock()
        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO governance_envelopes (authorization_id,"
                    " portfolio_id, authorization_kind, envelope_hash,"
                    " signed_envelope_json, status, issued_at,"
                    " predecessor_authorization_id)"
                    " VALUES (:auth_id, :portfolio, :kind, :hash,"
                    " :signed_json, 'INACTIVE', :issued_at, :predecessor)"
                ),
                {
                    "auth_id": envelope.authorization_id,
                    "portfolio": envelope.portfolio_id,
                    "kind": envelope.authorization_kind.value,
                    "hash": envelope.artifact_hash(),
                    "signed_json": signed.model_dump_json(),
                    "issued_at": now.isoformat(),
                    "predecessor": predecessor_authorization_id,
                },
            )

    def issue_exploration(
        self, request: ExplorationIssuanceRequest
    ) -> tuple[CapitalAuthorizationEnvelope, SignedEnvelope]:
        """Issue one INACTIVE EXPLORATION candidate.

        EXPLORATION is BROKER_CONFIRMED-only, aggregate-capped at 2% of
        NAV, and declares restricted evidence collection - never a live
        edge. Renewals must cite the exploration they renew.
        """

        envelope = request.envelope
        now = self._clock()
        if envelope.authorization_kind is not (
            AuthorizationKind.EXPLORATION
        ):
            raise IssuerError(
                "envelope_kind_mismatch",
                "exploration issuance requires an EXPLORATION envelope",
            )
        if envelope.mode is not ExecutionMode.BROKER_CONFIRMED:
            raise IssuerError(
                "exploration_requires_broker_confirmed",
                "exploration envelopes are BROKER_CONFIRMED-only",
            )
        if envelope.expires_at <= now:
            raise IssuerError(
                "manifest_expired",
                "the envelope manifest is already expired",
            )
        if (
            envelope.exploration_aggregate_gross_cap
            > EXPLORATION_AGGREGATE_CAP
        ):
            raise IssuerError(
                "exploration_cap_exceeded",
                "exploration aggregate gross cap cannot exceed 2% of NAV",
            )
        if envelope.portfolio_gross_cap > EXPLORATION_AGGREGATE_CAP:
            raise IssuerError(
                "exploration_cap_exceeded",
                "first-broker exploration portfolio cap cannot exceed 2%",
            )
        if request.renewal_of_authorization_id is not None:
            with self._engine.connect() as conn:
                prior = conn.execute(
                    sa.text(
                        "SELECT authorization_kind FROM"
                        " governance_envelopes WHERE authorization_id ="
                        " :id"
                    ),
                    {"id": request.renewal_of_authorization_id},
                ).first()
            if prior is None or str(
                prior.authorization_kind
            ) != AuthorizationKind.EXPLORATION.value:
                raise IssuerError(
                    "renewal_requires_prior_exploration",
                    "exploration renewal must cite a prior exploration",
                )
        payload = envelope.model_dump_json().encode("utf-8")
        signed = self._signer(payload)
        self._consume_budgets(
            envelope,
            research_program_id=request.research_program_id,
            attempt_id=request.attempt_id,
            sample_evidence_id=request.sample_evidence_id,
            sample_evaluation_unit_id=(
                request.sample_evaluation_unit_id
            ),
        )
        self._record(
            envelope,
            signed,
            predecessor_authorization_id=(
                request.renewal_of_authorization_id
            ),
        )
        return envelope, signed

    def issue_recovery(
        self, request: RecoveryIssuanceRequest
    ) -> tuple[CapitalAuthorizationEnvelope, SignedEnvelope]:
        """Issue one INACTIVE RECOVERY candidate.

        Recovery cites the inherited authorization and ALL inherited
        risk/stage-loss versions; it never mints a new grant.
        """

        envelope = request.envelope
        now = self._clock()
        if envelope.authorization_kind is not AuthorizationKind.RECOVERY:
            raise IssuerError(
                "envelope_kind_mismatch",
                "recovery issuance requires a RECOVERY envelope",
            )
        if envelope.expires_at <= now:
            raise IssuerError(
                "manifest_expired",
                "the envelope manifest is already expired",
            )
        if not request.inherited_authorization_id:
            raise IssuerError(
                "recovery_requires_inherited_grant",
                "recovery must cite the inherited authorization",
            )
        if request.inherited_risk_epoch != envelope.risk_epoch:
            raise IssuerError(
                "recovery_risk_epoch_mismatch",
                "recovery must carry the inherited risk epoch",
            )
        inherited_loss = next(
            (
                binding
                for binding in envelope.program_loss_budget_bindings
            ),
            None,
        )
        if (
            inherited_loss is None
            or inherited_loss.version
            != request.inherited_stage_loss_version
        ):
            raise IssuerError(
                "recovery_loss_version_mismatch",
                "recovery must carry ALL inherited stage-loss versions",
            )
        predecessor_predecessor = (
            envelope.predecessor_active_authorization_id
        )
        if predecessor_predecessor != request.inherited_authorization_id:
            raise IssuerError(
                "recovery_predecessor_mismatch",
                "envelope predecessor must match the inherited"
                " authorization",
            )
        payload = envelope.model_dump_json().encode("utf-8")
        signed = self._signer(payload)
        self._consume_budgets(
            envelope,
            research_program_id=request.research_program_id,
            attempt_id=request.attempt_id,
            sample_evidence_id=request.sample_evidence_id,
            sample_evaluation_unit_id=(
                request.sample_evaluation_unit_id
            ),
        )
        self._record(
            envelope,
            signed,
            predecessor_authorization_id=(
                request.inherited_authorization_id
            ),
        )
        return envelope, signed

    def issued_status(self, authorization_id: str) -> str:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT status FROM governance_envelopes"
                    " WHERE authorization_id = :id"
                ),
                {"id": authorization_id},
            ).first()
        if row is None:
            raise IssuerError(
                "envelope_unknown", "no issued envelope for id"
            )
        return str(row.status)


__all__ = [
    "EXPLORATION_AGGREGATE_CAP",
    "ExplorationIssuanceRequest",
    "GovernanceIssuer",
    "IssuerError",
    "RecoveryIssuanceRequest",
]
