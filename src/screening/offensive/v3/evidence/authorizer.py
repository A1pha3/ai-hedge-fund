"""EDGE Authorizer (Plan 03 Task 6).

The Authorizer alone signs EDGE envelopes. Every candidate envelope is a
complete portfolio policy and stays INACTIVE: activation is a later
Capital Gateway CAS (Plan 04) and grants no authority here. All gates are
fail-closed; a failed external signature leaves no consumption and no
issued envelope, and a retry is deterministic.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Final

import sqlalchemy as sa

from src.screening.offensive.v3.contracts import SignedEnvelope
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.evidence.statistics import (
    PortfolioEvaluation,
)

_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS issued_envelopes (
        authorization_id TEXT PRIMARY KEY,
        portfolio_id TEXT NOT NULL,
        authorization_kind TEXT NOT NULL,
        envelope_hash TEXT NOT NULL,
        signed_envelope_json TEXT NOT NULL,
        status TEXT NOT NULL,
        issued_at TEXT NOT NULL,
        consumed_payload_hash TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_active_envelope_per_portfolio
    ON issued_envelopes (portfolio_id)
    WHERE status = 'ACTIVE'
    """,
)

BENCHMARK_STALENESS_TOLERANCE: Final = timedelta(days=1)


class AuthorizerError(RuntimeError):
    """Fail-closed rejection of an authorization assessment."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class EdgeAssessmentRequest:
    """One EDGE assessment over a frozen evaluation."""

    portfolio_id: str
    broker_account_id: str | None
    mode: ExecutionMode
    behavior_fingerprint: str
    cost_version: str
    execution_version: str
    benchmark_as_of: datetime | None
    baseline_excess_mean: float
    evaluation: PortfolioEvaluation
    mdd_cap: float
    cdar_cap: float
    envelope: CapitalAuthorizationEnvelope
    consumption_payload_hash: str


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


class Authorizer:
    """Assesses evidence and signs inactive EDGE envelope candidates."""

    def __init__(
        self,
        *,
        database_path: str,
        signer: Callable[[bytes], SignedEnvelope],
        clock: Callable[[], datetime],
        expected_mode: ExecutionMode,
        expected_behavior_fingerprint: str,
        expected_cost_version: str,
        expected_execution_version: str,
        expected_broker_account_id: str | None,
    ) -> None:
        self._signer = signer
        self._clock = clock
        self._expected_mode = expected_mode
        self._expected_behavior = expected_behavior_fingerprint
        self._expected_cost = expected_cost_version
        self._expected_execution = expected_execution_version
        self._expected_broker = expected_broker_account_id
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(self._engine, "connect", _configure_connection)
        with self._engine.begin() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(sa.text(ddl))

    def _active_envelope(self, conn, portfolio_id: str):
        return conn.execute(
            sa.text(
                "SELECT authorization_id FROM issued_envelopes"
                " WHERE portfolio_id = :portfolio AND status = 'ACTIVE'"
            ),
            {"portfolio": portfolio_id},
        ).first()

    def assess_and_issue_edge(
        self, request: EdgeAssessmentRequest
    ) -> tuple[CapitalAuthorizationEnvelope, SignedEnvelope]:
        """Run every gate fail-closed, then sign one INACTIVE candidate.

        Signature ordering: all gates pass first; the registry write
        happens only AFTER the external signer succeeds, so a signer
        failure leaves no consumption and no envelope behind.
        """

        evaluation = request.evaluation
        now = self._clock()
        # Stale or missing benchmark.
        if request.benchmark_as_of is None:
            raise AuthorizerError(
                "benchmark_missing", "assessment requires a benchmark"
            )
        if request.benchmark_as_of < (
            evaluation.evidence_cutoff - BENCHMARK_STALENESS_TOLERANCE
        ):
            raise AuthorizerError(
                "benchmark_stale",
                "benchmark observation is stale relative to the evidence"
                " cutoff",
            )
        # Context mismatches fail closed.
        if request.mode is not self._expected_mode:
            raise AuthorizerError(
                "mode_mismatch",
                "assessment mode differs from the authorizer context",
            )
        if request.broker_account_id != self._expected_broker:
            raise AuthorizerError(
                "account_mismatch",
                "broker account differs from the authorizer context",
            )
        if (
            request.behavior_fingerprint
            != self._expected_behavior
        ):
            raise AuthorizerError(
                "behavior_mismatch",
                "behavior fingerprint differs from the authorizer context",
            )
        if request.cost_version != self._expected_cost:
            raise AuthorizerError(
                "cost_mismatch",
                "cost version differs from the authorizer context",
            )
        if request.execution_version != self._expected_execution:
            raise AuthorizerError(
                "execution_mismatch",
                "execution version differs from the authorizer context",
            )
        # Economic gates: LCB above MEE, target better than baseline.
        if not evaluation.passes_economic_gate():
            raise AuthorizerError(
                "lcb_below_mee",
                "one-sided LCB does not clear the minimum economic effect",
            )
        if evaluation.excess_mean <= request.baseline_excess_mean:
            raise AuthorizerError(
                "target_not_better_than_baseline",
                "target policy does not beat the baseline",
            )
        # Tail gates.
        if evaluation.maximum_drawdown > request.mdd_cap:
            raise AuthorizerError(
                "tail_breach", "maximum drawdown breaches the cap"
            )
        if evaluation.conditional_drawdown_at_risk > request.cdar_cap:
            raise AuthorizerError(
                "tail_breach", "CDaR breaches the cap"
            )
        # Envelope completeness and kind.
        envelope = request.envelope
        if envelope.authorization_kind is not AuthorizationKind.EDGE:
            raise AuthorizerError(
                "envelope_kind_mismatch",
                "the Authorizer only signs EDGE envelopes",
            )
        if envelope.portfolio_id != request.portfolio_id:
            raise AuthorizerError(
                "envelope_portfolio_mismatch",
                "envelope portfolio differs from the assessment",
            )
        with self._engine.begin() as conn:
            if self._active_envelope(conn, request.portfolio_id) is not None:
                raise AuthorizerError(
                    "envelope_already_active",
                    "one portfolio holds at most one active envelope;"
                    " multiple independent envelopes are rejected",
                )
            # Sign AFTER every gate; a signer failure writes nothing.
            payload = envelope.model_dump_json().encode("utf-8")
            signed = self._signer(payload)
            conn.execute(
                sa.text(
                    "INSERT INTO issued_envelopes (authorization_id,"
                    " portfolio_id, authorization_kind, envelope_hash,"
                    " signed_envelope_json, status, issued_at,"
                    " consumed_payload_hash)"
                    " VALUES (:auth_id, :portfolio, :kind, :hash,"
                    " :signed_json, 'INACTIVE', :issued_at, :payload_hash)"
                ),
                {
                    "auth_id": envelope.authorization_id,
                    "portfolio": request.portfolio_id,
                    "kind": AuthorizationKind.EDGE.value,
                    "hash": envelope.artifact_hash(),
                    "signed_json": signed.model_dump_json(),
                    "issued_at": now.isoformat(),
                    "payload_hash": request.consumption_payload_hash,
                },
            )
        return envelope, signed

    def issued_status(self, authorization_id: str) -> str:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT status FROM issued_envelopes"
                    " WHERE authorization_id = :id"
                ),
                {"id": authorization_id},
            ).first()
        if row is None:
            raise AuthorizerError(
                "envelope_unknown", "no issued envelope for id"
            )
        return str(row.status)


__all__ = [
    "Authorizer",
    "AuthorizerError",
    "EdgeAssessmentRequest",
]
