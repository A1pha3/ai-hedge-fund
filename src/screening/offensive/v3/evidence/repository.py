"""Issuer-scoped PIT Evidence Store (Plan 03 Task 1).

One writable namespace per issuer. The store alone owns `ingested_at`,
`commit_sequence`, revision/supersedes chains and the active-revision
projection; producer payloads cannot set store-controlled fields. A
payload becomes durable in the blob store before its envelope commits,
and every publish verifies the signed envelope against the injected
capability verifier and the Authority Store current trust head.

Reads decode every record through
``TypeAdapter(ActiveEvidenceRecord).validate_json(..., strict=True)`` so
the concrete variant, full value and ``artifact_hash()`` round-trip
exactly; a bare generic record or a bypassing construction path is
forbidden. Prepared revisions are durable staging facts; activation is a
separate monotone store fact, so a crash between prepare and activate
never loses the prepared revision. Schema version 2 adds a store-owned,
immutable copy of separately referenced raw payloads. Schema v2 is a clean
namespace/database cutover: an empty legacy namespace may initialize v2,
but a nonempty unversioned namespace must be migrated by an offline,
independently verified tool. Missing or invalid v2 raw truth fails closed
and is never reconstructed from a filesystem mirror.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Final, Iterator, Protocol

import sqlalchemy as sa
from pydantic import TypeAdapter, ValidationError

from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    Capability,
    CurrentTrustHeadWitness,
    SignedEnvelope,
)
from src.screening.offensive.v3.contracts.decision import PlanEvidence
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    OutcomeEvidence,
    SignalEvidence,
    SnapshotEvidence,
)
from src.screening.offensive.v3.contracts.ports import ActiveEvidenceRecord
from src.screening.offensive.v3.evidence.blob_store import BlobStore, BlobStoreError
from src.screening.offensive.v3.evidence.referenced_payloads import (
    ReferencedPayloadValidationError,
    validate_referenced_payload,
)

GENESIS_DEPENDENCY_ROOT: Final[str] = "0" * 64
EVIDENCE_STORE_SCHEMA_VERSION: Final[int] = 2

_PAYLOAD_ADAPTER: Final = TypeAdapter(
    SnapshotEvidence | SignalEvidence | OutcomeEvidence | PlanEvidence
)
_RECORD_ADAPTER: Final = TypeAdapter(ActiveEvidenceRecord)

_ARTIFACT_BY_KIND: Final = {
    "snapshot": ArtifactKind.SNAPSHOT,
    "signal": ArtifactKind.SIGNAL,
    "outcome": ArtifactKind.OUTCOME,
    "plan": ArtifactKind.PLAN,
}

_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS evidence_schema_meta (
        issuer_namespace TEXT PRIMARY KEY,
        schema_version BIGINT NOT NULL,
        CHECK (schema_version >= 1)
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_schema_meta_no_update
    BEFORE UPDATE ON evidence_schema_meta
    BEGIN SELECT RAISE(ABORT,
        'immutable table: evidence_schema_meta update'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_schema_meta_no_delete
    BEFORE DELETE ON evidence_schema_meta
    BEGIN SELECT RAISE(ABORT,
        'immutable table: evidence_schema_meta delete'); END
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_head (
        issuer_namespace TEXT PRIMARY KEY,
        last_commit_sequence BIGINT NOT NULL,
        dependency_root TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_records (
        issuer_namespace TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        revision BIGINT NOT NULL,
        evidence_kind TEXT NOT NULL,
        record_json TEXT NOT NULL,
        payload_content_hash TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        activated_at TEXT NOT NULL,
        commit_sequence BIGINT NOT NULL,
        supersedes_revision BIGINT,
        dependency_root TEXT NOT NULL,
        PRIMARY KEY (issuer_namespace, evidence_id, revision)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_commit_sequence
    ON evidence_records (issuer_namespace, commit_sequence)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_records_no_update
    BEFORE UPDATE ON evidence_records
    BEGIN SELECT RAISE(ABORT,
        'immutable table: evidence_records update'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_records_no_delete
    BEFORE DELETE ON evidence_records
    BEGIN SELECT RAISE(ABORT,
        'immutable table: evidence_records delete'); END
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_prepared (
        issuer_namespace TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        revision BIGINT NOT NULL,
        evidence_kind TEXT NOT NULL,
        record_json TEXT NOT NULL,
        payload_content_hash TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        commit_sequence BIGINT NOT NULL,
        supersedes_revision BIGINT NOT NULL,
        dependency_root TEXT NOT NULL,
        PRIMARY KEY (issuer_namespace, evidence_id, revision)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_prepared_sequence
    ON evidence_prepared (issuer_namespace, commit_sequence)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_prepared_no_update
    BEFORE UPDATE ON evidence_prepared
    BEGIN SELECT RAISE(ABORT,
        'immutable table: evidence_prepared update'); END
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_referenced_payloads (
        issuer_namespace TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        payload BLOB NOT NULL,
        PRIMARY KEY (issuer_namespace, content_hash)
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_referenced_payloads_no_update
    BEFORE UPDATE ON evidence_referenced_payloads
    BEGIN SELECT RAISE(ABORT,
        'immutable table: evidence_referenced_payloads update'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_referenced_payloads_no_delete
    BEFORE DELETE ON evidence_referenced_payloads
    BEGIN SELECT RAISE(ABORT,
        'immutable table: evidence_referenced_payloads delete'); END
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_referenced_bindings (
        issuer_namespace TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        revision BIGINT NOT NULL,
        content_hash TEXT NOT NULL,
        PRIMARY KEY (issuer_namespace, evidence_id, revision),
        FOREIGN KEY (issuer_namespace, content_hash)
            REFERENCES evidence_referenced_payloads
                (issuer_namespace, content_hash)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_evidence_referenced_bindings_hash
    ON evidence_referenced_bindings (issuer_namespace, content_hash)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_referenced_bindings_no_update
    BEFORE UPDATE ON evidence_referenced_bindings
    BEGIN SELECT RAISE(ABORT,
        'immutable table: evidence_referenced_bindings update'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_referenced_bindings_no_delete
    BEFORE DELETE ON evidence_referenced_bindings
    BEGIN SELECT RAISE(ABORT,
        'immutable table: evidence_referenced_bindings delete'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_records_require_referenced_binding
    BEFORE INSERT ON evidence_records
    WHEN NEW.issuer_namespace = 'btst' AND NEW.evidence_kind = 'signal'
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM evidence_referenced_bindings AS binding
            JOIN evidence_referenced_payloads AS payload
              ON payload.issuer_namespace = binding.issuer_namespace
             AND payload.content_hash = binding.content_hash
            WHERE binding.issuer_namespace = NEW.issuer_namespace
              AND binding.evidence_id = NEW.evidence_id
              AND binding.revision = NEW.revision
              AND binding.content_hash = json_extract(
                  NEW.record_json, '$.evidence.payload_content_hash'
              )
        ) THEN RAISE(ABORT, 'missing referenced payload binding') END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_prepared_require_referenced_binding
    BEFORE INSERT ON evidence_prepared
    WHEN NEW.issuer_namespace = 'btst' AND NEW.evidence_kind = 'signal'
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM evidence_referenced_bindings AS binding
            JOIN evidence_referenced_payloads AS payload
              ON payload.issuer_namespace = binding.issuer_namespace
             AND payload.content_hash = binding.content_hash
            WHERE binding.issuer_namespace = NEW.issuer_namespace
              AND binding.evidence_id = NEW.evidence_id
              AND binding.revision = NEW.revision
              AND binding.content_hash = json_extract(
                  NEW.record_json, '$.evidence.payload_content_hash'
              )
        ) THEN RAISE(ABORT, 'missing referenced payload binding') END;
    END
    """,
)


class EvidenceStoreError(RuntimeError):
    """Fail-closed rejection of an evidence store operation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class TrustHeadProvider(Protocol):
    def current_trust_head(
        self, trusted_at: datetime
    ) -> CurrentTrustHeadWitness: ...


class VerifierProtocol(Protocol):
    def verify(
        self,
        signed: SignedEnvelope,
        required: Capability,
        *,
        current_head: CurrentTrustHeadWitness,
        trusted_at: datetime,
    ) -> object: ...


def required_capability(signed: SignedEnvelope) -> Capability:
    """The caller-required capability matching the envelope's claims.

    The verifier compares context fields only; the registry grant decides
    lifecycle truth. The fixed window merely satisfies the DTO invariant
    and keeps the requirement deterministic.
    """

    return Capability(
        artifact=signed.artifact,
        namespace=signed.namespace,
        mode=signed.mode,
        schema_major=signed.schema_major,
        capability_version=signed.capability_version,
        scope=signed.capability_scope,
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2100, 1, 1, tzinfo=timezone.utc),
        revoked_at=None,
    )


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _chain_root(previous_root: str, record_hash: str) -> str:
    return hashlib.sha256(
        f"{previous_root}:{record_hash}".encode("utf-8")
    ).hexdigest()


class EvidenceRepository:
    """One issuer namespace's PIT evidence timeline and query surface.

    Implements the final ``EvidenceQueryPort`` (``active_revision`` and
    ``outcome``) over strict store records.
    """

    def __init__(
        self,
        *,
        database_path: str,
        blob_store: BlobStore,
        verifier: VerifierProtocol,
        trust_head_provider: TrustHeadProvider,
        issuer_namespace: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._database_path = database_path
        self._blobs = blob_store
        self._verifier = verifier
        self._trust_head_provider = trust_head_provider
        self._issuer_namespace = issuer_namespace
        self._clock = clock
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(self._engine, "connect", _configure_connection)
        with self._writer_transaction() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(sa.text(ddl))
            self._initialize_or_verify_schema(conn)
            conn.execute(
                sa.text(
                    "INSERT OR IGNORE INTO evidence_head (issuer_namespace,"
                    " last_commit_sequence, dependency_root)"
                    " VALUES (:ns, 0, :root)"
                ),
                {
                    "ns": issuer_namespace,
                    "root": GENESIS_DEPENDENCY_ROOT,
                },
            )

    # -- internals ---------------------------------------------------------

    @contextmanager
    def _writer_transaction(self) -> Iterator[sa.engine.Connection]:
        """Serialize writers before their first read and make SQLite DDL atomic."""

        with self._engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()

    def _validate_authoritative_payload(
        self,
        envelope: SignalEvidence,
        payload: bytes,
    ) -> None:
        try:
            validate_referenced_payload(
                issuer_namespace=self._issuer_namespace,
                envelope=envelope,
                read_payload=lambda _content_hash: payload,
            )
        except ReferencedPayloadValidationError as exc:
            raise EvidenceStoreError(
                exc.code,
                "authoritative referenced payload failed schema validation",
                **exc.details,
            ) from exc

    def _store_timestamp(
        self,
        *,
        not_before: datetime,
        operation: str,
    ) -> datetime:
        """Read trusted time only after the SQLite writer lock is held.

        Signature verification deliberately happens before external durable
        blob I/O.  Its timestamp proves when verification occurred, not when
        the store fact linearized.  A second clock read under ``BEGIN
        IMMEDIATE`` owns the evidence timeline and may never move backwards
        relative to that earlier trusted fact.
        """

        timestamp = self._clock()
        try:
            rolled_back = timestamp < not_before
        except (TypeError, ValueError) as exc:
            raise EvidenceStoreError(
                "trusted_clock_invalid",
                "trusted clock returned an incomparable store timestamp",
                operation=operation,
            ) from exc
        if rolled_back:
            raise EvidenceStoreError(
                "trusted_clock_rollback",
                "store timestamp precedes an already observed trusted time",
                operation=operation,
                observed_at=_iso(timestamp),
                not_before=_iso(not_before),
            )
        return timestamp

    @staticmethod
    def _normalized_schema_sql(value: str) -> str:
        normalized = " ".join(value.strip().rstrip(";").split()).lower()
        normalized = normalized.replace(" if not exists ", " ")
        return re.sub(r"\s*([(),;=])\s*", r"\1", normalized)

    def _verify_schema_definitions(self, conn: sa.engine.Connection) -> None:
        for ddl in _SCHEMA_DDL:
            normalized = self._normalized_schema_sql(ddl)
            match = re.match(
                r"create (?:(unique) )?(table|trigger|index) ([a-z0-9_]+)",
                normalized,
            )
            if match is None:
                continue
            object_type = match.group(2)
            object_name = match.group(3)
            row = conn.execute(
                sa.text(
                    "SELECT sql FROM sqlite_schema"
                    " WHERE type = :object_type AND name = :name"
                ),
                {"object_type": object_type, "name": object_name},
            ).first()
            if row is None or self._normalized_schema_sql(str(row.sql)) != normalized:
                raise EvidenceStoreError(
                    "evidence_schema_definition_mismatch",
                    "evidence store schema definition is missing or unexpected",
                    object_type=object_type,
                    object_name=object_name,
                    expected_hash=hashlib.sha256(normalized.encode()).hexdigest(),
                    found_hash=(
                        hashlib.sha256(
                            self._normalized_schema_sql(str(row.sql)).encode()
                        ).hexdigest()
                        if row is not None
                        else None
                    ),
                )

    def _legacy_namespace_nonempty(self, conn: sa.engine.Connection) -> bool:
        for table in ("evidence_records", "evidence_prepared"):
            row = conn.execute(
                sa.text(
                    f"SELECT 1 FROM {table}"
                    " WHERE issuer_namespace = :ns LIMIT 1"
                ),
                {"ns": self._issuer_namespace},
            ).first()
            if row is not None:
                return True
        head = conn.execute(
            sa.text(
                "SELECT last_commit_sequence FROM evidence_head"
                " WHERE issuer_namespace = :ns"
            ),
            {"ns": self._issuer_namespace},
        ).first()
        return head is not None and int(head.last_commit_sequence) != 0

    def _verify_v2_referenced_truth(self, conn: sa.engine.Connection) -> None:
        if self._issuer_namespace != "btst":
            return
        for table in ("evidence_records", "evidence_prepared"):
            rows = conn.execute(
                sa.text(
                    f"SELECT evidence.record_json, binding.content_hash, raw.payload"
                    f" FROM {table} AS evidence"
                    " LEFT JOIN evidence_referenced_bindings AS binding"
                    " ON binding.issuer_namespace = evidence.issuer_namespace"
                    " AND binding.evidence_id = evidence.evidence_id"
                    " AND binding.revision = evidence.revision"
                    " LEFT JOIN evidence_referenced_payloads AS raw"
                    " ON raw.issuer_namespace = binding.issuer_namespace"
                    " AND raw.content_hash = binding.content_hash"
                    " WHERE evidence.issuer_namespace = :ns"
                    " AND evidence.evidence_kind = 'signal'"
                ),
                {"ns": self._issuer_namespace},
            )
            for row in rows:
                record = self._decode_stored(str(row.record_json))
                envelope = record.evidence
                if type(envelope) is not SignalEvidence:
                    raise EvidenceStoreError(
                        "referenced_payload_binding_invalid",
                        "BTST signal row does not decode to exact SignalEvidence",
                    )
                if row.content_hash is None or row.payload is None:
                    raise EvidenceStoreError(
                        "referenced_payload_missing",
                        "versioned evidence lost its indexed authoritative bytes",
                        evidence_id=envelope.evidence_id,
                        content_hash=envelope.payload_content_hash,
                    )
                if str(row.content_hash) != envelope.payload_content_hash:
                    raise EvidenceStoreError(
                        "referenced_payload_binding_mismatch",
                        "indexed raw hash differs from its evidence envelope",
                        evidence_id=envelope.evidence_id,
                    )
                self._validate_authoritative_payload(envelope, bytes(row.payload))

    def _initialize_or_verify_schema(self, conn: sa.engine.Connection) -> None:
        self._verify_schema_definitions(conn)
        version_row = conn.execute(
            sa.text(
                "SELECT schema_version FROM evidence_schema_meta"
                " WHERE issuer_namespace = :ns"
            ),
            {"ns": self._issuer_namespace},
        ).first()
        if version_row is None:
            if self._legacy_namespace_nonempty(conn):
                raise EvidenceStoreError(
                    "legacy_store_requires_offline_cutover",
                    "nonempty unversioned evidence cannot be upgraded in process",
                    issuer_namespace=self._issuer_namespace,
                )
            conn.execute(
                sa.text(
                    "INSERT INTO evidence_schema_meta"
                    " (issuer_namespace, schema_version) VALUES (:ns, :version)"
                ),
                {
                    "ns": self._issuer_namespace,
                    "version": EVIDENCE_STORE_SCHEMA_VERSION,
                },
            )
        elif int(version_row.schema_version) != EVIDENCE_STORE_SCHEMA_VERSION:
            raise EvidenceStoreError(
                "evidence_schema_version_unsupported",
                "evidence store schema version is not supported",
                found=int(version_row.schema_version),
                expected=EVIDENCE_STORE_SCHEMA_VERSION,
            )
        self._verify_v2_referenced_truth(conn)

    def _head(self, conn: sa.engine.Connection) -> sa.engine.Row:
        row = conn.execute(
            sa.text(
                "SELECT last_commit_sequence, dependency_root"
                " FROM evidence_head WHERE issuer_namespace = :ns"
            ),
            {"ns": self._issuer_namespace},
        ).first()
        if row is None:
            raise EvidenceStoreError(
                "store_uninitialized", "evidence head row missing"
            )
        return row

    def _advance_head(
        self,
        conn: sa.engine.Connection,
        record_hash: str,
    ) -> tuple[int, str]:
        head = self._head(conn)
        sequence = int(head.last_commit_sequence) + 1
        root = _chain_root(str(head.dependency_root), record_hash)
        conn.execute(
            sa.text(
                "UPDATE evidence_head SET last_commit_sequence = :seq,"
                " dependency_root = :root WHERE issuer_namespace = :ns"
            ),
            {
                "seq": sequence,
                "root": root,
                "ns": self._issuer_namespace,
            },
        )
        return sequence, root

    def _verify_signed(
        self, signed: SignedEnvelope, payload: bytes
    ) -> tuple[datetime, object]:
        trusted_at = self._clock()
        current_head = self._trust_head_provider.current_trust_head(trusted_at)
        try:
            verified = self._verifier.verify(
                signed,
                required_capability(signed),
                current_head=current_head,
                trusted_at=trusted_at,
            )
        except Exception as exc:
            raise EvidenceStoreError(
                "trust_verification_failed",
                "signed envelope failed capability verification",
                reason=str(exc),
            ) from exc
        if hashlib.sha256(payload).hexdigest() != signed.payload_hash:
            raise EvidenceStoreError(
                "payload_hash_mismatch",
                "payload bytes do not hash to the signed payload hash",
            )
        if signed.namespace != self._issuer_namespace:
            raise EvidenceStoreError(
                "namespace_mismatch",
                "envelope namespace differs from this store's issuer"
                " namespace",
            )
        return trusted_at, verified

    def _decode_envelope(self, signed: SignedEnvelope, payload: bytes):
        try:
            envelope = _PAYLOAD_ADAPTER.validate_json(payload, strict=True)
        except ValidationError as exc:
            raise EvidenceStoreError(
                "payload_decode_failed",
                "payload is not one strict concrete evidence variant",
                reason=str(exc),
            ) from exc
        expected_artifact = _ARTIFACT_BY_KIND.get(envelope.evidence_kind)
        if expected_artifact is not signed.artifact:
            raise EvidenceStoreError(
                "artifact_kind_mismatch",
                "signed artifact does not match the payload evidence kind",
            )
        if (
            envelope.schema_major != signed.schema_major
            or envelope.mode is not signed.mode
        ):
            raise EvidenceStoreError(
                "envelope_context_mismatch",
                "signed schema/mode context does not match evidence payload",
            )
        return envelope

    def _verify_referenced_payload(
        self,
        envelope: object,
        referenced_payload: bytes | None,
    ) -> bytes | None:
        if self._issuer_namespace != "btst" or type(envelope) is not SignalEvidence:
            return None
        if type(referenced_payload) is not bytes:
            raise EvidenceStoreError(
                "referenced_payload_ingress_required",
                "BTST signal publication requires explicit immutable raw bytes",
                evidence_id=envelope.evidence_id,
            )

        try:
            validate_referenced_payload(
                issuer_namespace=self._issuer_namespace,
                envelope=envelope,
                read_payload=lambda _content_hash: referenced_payload,
            )
        except ReferencedPayloadValidationError as exc:
            raise EvidenceStoreError(
                exc.code,
                "evidence envelope failed referenced-payload validation",
                **exc.details,
            ) from exc
        return referenced_payload

    def _persist_referenced_payload(
        self,
        conn: sa.engine.Connection,
        *,
        envelope: object,
        payload: bytes | None,
    ) -> None:
        if payload is None:
            return
        content_hash = getattr(envelope, "payload_content_hash", None)
        if (
            not isinstance(content_hash, str)
            or hashlib.sha256(payload).hexdigest() != content_hash
        ):
            raise EvidenceStoreError(
                "referenced_payload_hash_mismatch",
                "captured referenced bytes do not match their content hash",
            )
        conn.execute(
            sa.text(
                "INSERT OR IGNORE INTO evidence_referenced_payloads"
                " (issuer_namespace, content_hash, payload)"
                " VALUES (:ns, :hash, :payload)"
            ),
            {
                "ns": self._issuer_namespace,
                "hash": content_hash,
                "payload": payload,
            },
        )
        existing = conn.execute(
            sa.text(
                "SELECT payload FROM evidence_referenced_payloads"
                " WHERE issuer_namespace = :ns AND content_hash = :hash"
            ),
            {"ns": self._issuer_namespace, "hash": content_hash},
        ).first()
        if existing is None or bytes(existing.payload) != payload:
            raise EvidenceStoreError(
                "referenced_payload_hash_collision",
                "content hash already binds different authoritative bytes",
                content_hash=content_hash,
            )

    def _persist_referenced_binding(
        self,
        conn: sa.engine.Connection,
        *,
        envelope: object,
        revision: int,
    ) -> None:
        if self._issuer_namespace != "btst" or type(envelope) is not SignalEvidence:
            return
        conn.execute(
            sa.text(
                "INSERT OR IGNORE INTO evidence_referenced_bindings"
                " (issuer_namespace, evidence_id, revision, content_hash)"
                " VALUES (:ns, :evidence_id, :revision, :content_hash)"
            ),
            {
                "ns": self._issuer_namespace,
                "evidence_id": envelope.evidence_id,
                "revision": revision,
                "content_hash": envelope.payload_content_hash,
            },
        )
        row = conn.execute(
            sa.text(
                "SELECT content_hash FROM evidence_referenced_bindings"
                " WHERE issuer_namespace = :ns AND evidence_id = :evidence_id"
                " AND revision = :revision"
            ),
            {
                "ns": self._issuer_namespace,
                "evidence_id": envelope.evidence_id,
                "revision": revision,
            },
        ).first()
        if row is None or str(row.content_hash) != envelope.payload_content_hash:
            raise EvidenceStoreError(
                "referenced_payload_binding_conflict",
                "evidence revision already binds different raw bytes",
                evidence_id=envelope.evidence_id,
                revision=revision,
            )

    def _verify_existing_referenced_binding(
        self,
        conn: sa.engine.Connection,
        *,
        envelope: object,
        revision: int,
        ingress_payload: bytes | None,
    ) -> None:
        if self._issuer_namespace != "btst" or type(envelope) is not SignalEvidence:
            return
        row = conn.execute(
            sa.text(
                "SELECT binding.content_hash, raw.payload"
                " FROM evidence_referenced_bindings AS binding"
                " LEFT JOIN evidence_referenced_payloads AS raw"
                " ON raw.issuer_namespace = binding.issuer_namespace"
                " AND raw.content_hash = binding.content_hash"
                " WHERE binding.issuer_namespace = :ns"
                " AND binding.evidence_id = :evidence_id"
                " AND binding.revision = :revision"
            ),
            {
                "ns": self._issuer_namespace,
                "evidence_id": envelope.evidence_id,
                "revision": revision,
            },
        ).first()
        if row is None or row.payload is None:
            raise EvidenceStoreError(
                "referenced_payload_missing",
                "existing evidence revision lost authoritative raw bytes",
                evidence_id=envelope.evidence_id,
                revision=revision,
            )
        authoritative = bytes(row.payload)
        if (
            str(row.content_hash) != envelope.payload_content_hash
            or hashlib.sha256(authoritative).hexdigest()
            != envelope.payload_content_hash
        ):
            raise EvidenceStoreError(
                "referenced_payload_binding_mismatch",
                "existing indexed raw binding does not match its envelope",
                evidence_id=envelope.evidence_id,
                revision=revision,
            )
        if ingress_payload is not None and authoritative != ingress_payload:
            raise EvidenceStoreError(
                "referenced_payload_hash_collision",
                "ingress bytes differ from existing authoritative bytes",
                evidence_id=envelope.evidence_id,
                revision=revision,
            )

    @staticmethod
    def _revision_binding(envelope: object) -> tuple[object, ...]:
        return (
            type(envelope),
            getattr(envelope, "source_authority", None),
            getattr(envelope, "subject_scope", None),
            getattr(envelope, "subject_producer", None),
            getattr(envelope, "family_id", None),
            getattr(envelope, "strategy_semver", None),
            getattr(envelope, "behavior_fingerprint", None),
            getattr(envelope, "policy_epoch", None),
            getattr(envelope, "execution_version", None),
            getattr(envelope, "cost_version", None),
            getattr(envelope, "mode", None),
            getattr(envelope, "schema_major", None),
        )

    def _materialize(
        self,
        *,
        envelope,
        ingested_at: datetime,
        commit_sequence: int,
        revision: int,
        supersedes_revision: int | None,
        active_revision: int,
    ) -> ActiveEvidenceRecord:
        try:
            return EvidenceRecord[type(envelope)](
                evidence=envelope,
                ingested_at=ingested_at,
                commit_sequence=commit_sequence,
                revision=revision,
                supersedes_revision=supersedes_revision,
                active_revision=active_revision,
            )
        except ValidationError as exc:
            raise EvidenceStoreError(
                "store_timeline_rejected",
                "store-controlled timeline failed the frozen contract",
                reason=str(exc),
            ) from exc

    def _decode_stored(
        self, record_json: str, *, active_revision: int | None = None
    ) -> ActiveEvidenceRecord:
        record = _RECORD_ADAPTER.validate_json(record_json, strict=True)
        if active_revision is None:
            return record
        return type(record).model_validate(
            {**record.model_dump(mode="python"), "active_revision": active_revision}
        )

    def _rows(self, conn: sa.engine.Connection, evidence_id: str, table: str):
        return conn.execute(
            sa.text(
                f"SELECT * FROM {table} WHERE issuer_namespace = :ns"
                " AND evidence_id = :evidence_id ORDER BY revision"
            ),
            {"ns": self._issuer_namespace, "evidence_id": evidence_id},
        ).all()

    def _active_revision_at(
        self,
        conn: sa.engine.Connection,
        evidence_id: str,
        cutoff: datetime | None,
    ) -> tuple[int, datetime] | None:
        query = (
            "SELECT revision, activated_at FROM evidence_records"
            " WHERE issuer_namespace = :ns AND evidence_id = :evidence_id"
        )
        params: dict[str, object] = {
            "ns": self._issuer_namespace,
            "evidence_id": evidence_id,
        }
        if cutoff is not None:
            # Official OOS consumes what was committed strictly BEFORE the
            # cutoff; an activation landing exactly on the cutoff instant
            # is still late for that cutoff.
            query += " AND activated_at < :cutoff"
            params["cutoff"] = _iso(cutoff)
        query += " ORDER BY revision DESC LIMIT 1"
        row = conn.execute(sa.text(query), params).first()
        if row is None:
            return None
        return int(row.revision), row.activated_at

    # -- publication -------------------------------------------------------

    def publish(
        self,
        signed: SignedEnvelope,
        payload: bytes,
        *,
        referenced_payload: bytes | None = None,
    ) -> ActiveEvidenceRecord:
        """Verify, persist durably, and commit revision 1 of one evidence."""

        verified_at, _ = self._verify_signed(signed, payload)
        envelope = self._decode_envelope(signed, payload)
        referenced_payload = self._verify_referenced_payload(
            envelope,
            referenced_payload,
        )
        self._blobs.put_durable(payload)
        with self._writer_transaction() as conn:
            existing = self._rows(conn, envelope.evidence_id, "evidence_records")
            if existing:
                first = existing[0]
                if str(first.payload_content_hash) == signed.payload_hash:
                    self._verify_existing_referenced_binding(
                        conn,
                        envelope=envelope,
                        revision=int(first.revision),
                        ingress_payload=referenced_payload,
                    )
                    active = self._active_revision_at(
                        conn, envelope.evidence_id, None
                    )
                    return self._decode_stored(
                        str(first.record_json),
                        active_revision=(
                            active[0] if active is not None else 1
                        ),
                    )
                raise EvidenceStoreError(
                    "evidence_id_conflict",
                    "evidence id already committed with different content",
                    evidence_id=envelope.evidence_id,
                )
            ingested_at = self._store_timestamp(
                not_before=verified_at,
                operation="publish",
            )
            self._persist_referenced_payload(
                conn,
                envelope=envelope,
                payload=referenced_payload,
            )
            self._persist_referenced_binding(
                conn,
                envelope=envelope,
                revision=1,
            )
            head = self._head(conn)
            sequence = int(head.last_commit_sequence) + 1
            record = self._materialize(
                envelope=envelope,
                ingested_at=ingested_at,
                commit_sequence=sequence,
                revision=1,
                supersedes_revision=None,
                active_revision=1,
            )
            record_hash = record.artifact_hash()
            sequence, root = self._advance_head(conn, record_hash)
            if sequence != record.commit_sequence:
                raise EvidenceStoreError(
                    "commit_sequence_conflict",
                    "store commit sequence advanced during publication",
                )
            conn.execute(
                sa.text(
                    "INSERT INTO evidence_records (issuer_namespace,"
                    " evidence_id, revision, evidence_kind, record_json,"
                    " payload_content_hash, ingested_at, activated_at,"
                    " commit_sequence, supersedes_revision, dependency_root)"
                    " VALUES (:ns, :evidence_id, 1, :kind, :record_json,"
                    " :payload_hash, :ingested_at, :activated_at, :seq,"
                    " NULL, :root)"
                ),
                {
                    "ns": self._issuer_namespace,
                    "evidence_id": envelope.evidence_id,
                    "kind": envelope.evidence_kind,
                    "record_json": record.model_dump_json(),
                    "payload_hash": signed.payload_hash,
                    "ingested_at": _iso(ingested_at),
                    "activated_at": _iso(ingested_at),
                    "seq": sequence,
                    "root": root,
                },
            )
        return self._decode_stored(record.model_dump_json())

    def prepare_revision(
        self,
        signed: SignedEnvelope,
        payload: bytes,
        *,
        referenced_payload: bytes | None = None,
    ) -> ActiveEvidenceRecord:
        """Stage the next revision; it becomes durable store truth but is
        not the active projection until ``activate_revision``."""

        verified_at, _ = self._verify_signed(signed, payload)
        envelope = self._decode_envelope(signed, payload)
        referenced_payload = self._verify_referenced_payload(
            envelope,
            referenced_payload,
        )
        self._blobs.put_durable(payload)
        with self._writer_transaction() as conn:
            committed = self._rows(
                conn, envelope.evidence_id, "evidence_records"
            )
            prepared = self._rows(
                conn, envelope.evidence_id, "evidence_prepared"
            )
            if not committed:
                raise EvidenceStoreError(
                    "revision_requires_published_evidence",
                    "cannot prepare a revision before revision 1",
                    evidence_id=envelope.evidence_id,
                )
            original = self._decode_stored(str(committed[0].record_json)).evidence
            if self._revision_binding(envelope) != self._revision_binding(
                original
            ):
                raise EvidenceStoreError(
                    "revision_lineage_mismatch",
                    "a correction cannot change source lineage or behavior"
                    " generation bindings",
                    evidence_id=envelope.evidence_id,
                )
            active = self._active_revision_at(
                conn, envelope.evidence_id, None
            )
            for row in committed:
                if str(row.payload_content_hash) == signed.payload_hash:
                    self._verify_existing_referenced_binding(
                        conn,
                        envelope=envelope,
                        revision=int(row.revision),
                        ingress_payload=referenced_payload,
                    )
                    return self._decode_stored(
                        str(row.record_json),
                        active_revision=(
                            int(active[0])
                            if active is not None
                            else int(row.revision)
                        ),
                    )
            next_revision = (
                int(committed[-1].revision)
                + 1
                + len(prepared)
            )
            for row in prepared:
                if str(row.payload_content_hash) == signed.payload_hash:
                    self._verify_existing_referenced_binding(
                        conn,
                        envelope=envelope,
                        revision=int(row.revision),
                        ingress_payload=referenced_payload,
                    )
                    return self._decode_stored(str(row.record_json))
            ingested_at = self._store_timestamp(
                not_before=verified_at,
                operation="prepare_revision",
            )
            self._persist_referenced_payload(
                conn,
                envelope=envelope,
                payload=referenced_payload,
            )
            self._persist_referenced_binding(
                conn,
                envelope=envelope,
                revision=next_revision,
            )
            record = self._materialize(
                envelope=envelope,
                ingested_at=ingested_at,
                commit_sequence=int(self._head(conn).last_commit_sequence) + 1,
                revision=next_revision,
                supersedes_revision=next_revision - 1,
                active_revision=next_revision,
            )
            record_hash = record.artifact_hash()
            sequence, root = self._advance_head(conn, record_hash)
            conn.execute(
                sa.text(
                    "INSERT INTO evidence_prepared (issuer_namespace,"
                    " evidence_id, revision, evidence_kind, record_json,"
                    " payload_content_hash, ingested_at, commit_sequence,"
                    " supersedes_revision, dependency_root)"
                    " VALUES (:ns, :evidence_id, :revision, :kind,"
                    " :record_json, :payload_hash, :ingested_at, :seq,"
                    " :supersedes, :root)"
                ),
                {
                    "ns": self._issuer_namespace,
                    "evidence_id": envelope.evidence_id,
                    "revision": next_revision,
                    "kind": envelope.evidence_kind,
                    "record_json": record.model_dump_json(),
                    "payload_hash": signed.payload_hash,
                    "ingested_at": _iso(ingested_at),
                    "seq": sequence,
                    "supersedes": next_revision - 1,
                    "root": root,
                },
            )
        return self._decode_stored(record.model_dump_json())

    def activate_revision(
        self, evidence_id: str, revision: int
    ) -> ActiveEvidenceRecord:
        """Make one prepared revision the active projection (monotone)."""

        with self._writer_transaction() as conn:
            active = self._active_revision_at(conn, evidence_id, None)
            already = conn.execute(
                sa.text(
                    "SELECT record_json FROM evidence_records"
                    " WHERE issuer_namespace = :ns"
                    " AND evidence_id = :evidence_id"
                    " AND revision = :revision"
                ),
                {
                    "ns": self._issuer_namespace,
                    "evidence_id": evidence_id,
                    "revision": revision,
                },
            ).first()
            if already is not None:
                if active is None or int(active[0]) != revision:
                    raise EvidenceStoreError(
                        "activation_not_current",
                        "an older activated revision cannot be returned as active",
                        evidence_id=evidence_id,
                        revision=revision,
                        active_revision=(
                            int(active[0]) if active is not None else None
                        ),
                    )
                # Idempotent retry of the current active revision.
                return self._decode_stored(
                    str(already.record_json), active_revision=int(active[0])
                )
            prepared = conn.execute(
                sa.text(
                    "SELECT * FROM evidence_prepared"
                    " WHERE issuer_namespace = :ns"
                    " AND evidence_id = :evidence_id"
                    " AND revision = :revision"
                ),
                {
                    "ns": self._issuer_namespace,
                    "evidence_id": evidence_id,
                    "revision": revision,
                },
            ).first()
            if prepared is None:
                raise EvidenceStoreError(
                    "prepared_revision_unknown",
                    "no prepared revision exists for activation",
                    evidence_id=evidence_id,
                    revision=revision,
                )
            current_revision = int(active[0]) if active is not None else 0
            if (
                revision != current_revision + 1
                or int(prepared.supersedes_revision) != current_revision
            ):
                raise EvidenceStoreError(
                    "activation_revision_gap",
                    "activation must advance exactly one revision",
                    evidence_id=evidence_id,
                    revision=revision,
                    active_revision=current_revision,
                    supersedes_revision=int(prepared.supersedes_revision),
                )
            trusted_floor = datetime.fromisoformat(str(prepared.ingested_at))
            if active is not None:
                active_time = datetime.fromisoformat(str(active[1]))
                trusted_floor = max(trusted_floor, active_time)
            activated_at = self._store_timestamp(
                not_before=trusted_floor,
                operation="activate_revision",
            )
            conn.execute(
                sa.text(
                    "INSERT INTO evidence_records (issuer_namespace,"
                    " evidence_id, revision, evidence_kind, record_json,"
                    " payload_content_hash, ingested_at, activated_at,"
                    " commit_sequence, supersedes_revision, dependency_root)"
                    " VALUES (:ns, :evidence_id, :revision, :kind,"
                    " :record_json, :payload_hash, :ingested_at,"
                    " :activated_at, :seq, :supersedes, :root)"
                ),
                {
                    "ns": self._issuer_namespace,
                    "evidence_id": evidence_id,
                    "revision": revision,
                    "kind": str(prepared.evidence_kind),
                    "record_json": str(prepared.record_json),
                    "payload_hash": str(prepared.payload_content_hash),
                    "ingested_at": str(prepared.ingested_at),
                    "activated_at": _iso(activated_at),
                    "seq": int(prepared.commit_sequence),
                    "supersedes": int(prepared.supersedes_revision),
                    "root": str(prepared.dependency_root),
                },
            )
            conn.execute(
                sa.text(
                    "DELETE FROM evidence_prepared"
                    " WHERE issuer_namespace = :ns"
                    " AND evidence_id = :evidence_id"
                    " AND revision = :revision"
                ),
                {
                    "ns": self._issuer_namespace,
                    "evidence_id": evidence_id,
                    "revision": revision,
                },
            )
        return self._decode_stored(
            str(prepared.record_json), active_revision=revision
        )

    # -- EvidenceQueryPort ---------------------------------------------------

    def active_revision(
        self, evidence_id: str, cutoff: datetime
    ) -> ActiveEvidenceRecord:
        """The active record committed at or before the cutoff instant.

        Official OOS consumption sees exactly the revision that was active
        at the signal cutoff; later ingestions or activations are invisible.
        """

        with self._engine.connect() as conn:
            active = self._active_revision_at(conn, evidence_id, cutoff)
            if active is None:
                raise EvidenceStoreError(
                    "evidence_not_committed_before_cutoff",
                    "no active revision was committed at the cutoff",
                    evidence_id=evidence_id,
                    cutoff=_iso(cutoff),
                )
            revision, _activated = active
            row = conn.execute(
                sa.text(
                    "SELECT record_json FROM evidence_records"
                    " WHERE issuer_namespace = :ns"
                    " AND evidence_id = :evidence_id"
                    " AND revision = :revision"
                ),
                {
                    "ns": self._issuer_namespace,
                    "evidence_id": evidence_id,
                    "revision": revision,
                },
            ).first()
            if row is None:
                raise EvidenceStoreError(
                    "active_record_missing",
                    "active revision row missing from the store",
                    evidence_id=evidence_id,
                    revision=revision,
                )
            return self._decode_stored(
                str(row.record_json), active_revision=revision
            )

    def outcome(
        self, outcome_id: str, revision: int
    ) -> EvidenceRecord[OutcomeEvidence]:
        """One committed outcome record by exact revision."""

        record = self.get(outcome_id, revision=revision)
        if not isinstance(record.evidence, OutcomeEvidence):
            raise EvidenceStoreError(
                "evidence_kind_mismatch",
                "requested record is not an outcome record",
                evidence_id=outcome_id,
            )
        return record  # type: ignore[return-value]

    def get(
        self, evidence_id: str, *, revision: int | None = None
    ) -> ActiveEvidenceRecord:
        with self._engine.connect() as conn:
            active = self._active_revision_at(conn, evidence_id, None)
            if revision is None:
                if active is None:
                    raise EvidenceStoreError(
                        "evidence_unknown",
                        "no committed revision for evidence id",
                        evidence_id=evidence_id,
                    )
                target = int(active[0])
            else:
                target = revision
            row = conn.execute(
                sa.text(
                    "SELECT record_json FROM evidence_records"
                    " WHERE issuer_namespace = :ns"
                    " AND evidence_id = :evidence_id"
                    " AND revision = :revision"
                ),
                {
                    "ns": self._issuer_namespace,
                    "evidence_id": evidence_id,
                    "revision": target,
                },
            ).first()
            if row is None:
                raise EvidenceStoreError(
                    "evidence_unknown",
                    "no committed revision for evidence id",
                    evidence_id=evidence_id,
                    revision=target,
                )
            return self._decode_stored(
                str(row.record_json),
                active_revision=(active[0] if active is not None else target),
            )

    # -- store metadata ------------------------------------------------------

    def persist_payload(self, payload: bytes) -> str:
        """Durably store raw producer payload bytes; returns the hash.

        Orphan blobs are safe; envelopes without durable payloads are
        impossible.
        """

        return self._blobs.put_durable(payload)

    def raw_payload(
        self,
        content_hash: str,
        *,
        evidence_id: str | None = None,
        revision: int | None = None,
    ) -> bytes:
        """Raw producer payload bytes by content hash."""
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT payload FROM evidence_referenced_payloads"
                    " WHERE issuer_namespace = :ns AND content_hash = :hash"
                ),
                {"ns": self._issuer_namespace, "hash": content_hash},
            ).first()
            binding_query = (
                "SELECT 1 FROM evidence_referenced_bindings"
                " WHERE issuer_namespace = :ns AND content_hash = :hash"
            )
            binding_params: dict[str, object] = {
                "ns": self._issuer_namespace,
                "hash": content_hash,
            }
            if evidence_id is not None or revision is not None:
                if not isinstance(evidence_id, str) or type(revision) is not int:
                    raise EvidenceStoreError(
                        "referenced_payload_identity_incomplete",
                        "exact raw lookup requires evidence_id and revision together",
                    )
                binding_query += (
                    " AND evidence_id = :evidence_id AND revision = :revision"
                )
                binding_params.update(
                    {"evidence_id": evidence_id, "revision": revision}
                )
            binding_query += " LIMIT 1"
            authoritative_reference = conn.execute(
                sa.text(binding_query),
                binding_params,
            ).first()
        if self._issuer_namespace == "btst" and authoritative_reference is None:
            raise EvidenceStoreError(
                "referenced_payload_binding_missing",
                "BTST raw bytes require an indexed authoritative binding",
                content_hash=content_hash,
                evidence_id=evidence_id,
                revision=revision,
            )
        if row is not None:
            payload = bytes(row.payload)
            if hashlib.sha256(payload).hexdigest() != content_hash:
                raise EvidenceStoreError(
                    "referenced_payload_corrupt",
                    "authoritative referenced bytes fail their content hash",
                    content_hash=content_hash,
                )
            return payload
        if authoritative_reference:
            raise EvidenceStoreError(
                "referenced_payload_missing",
                "committed evidence has no authoritative referenced bytes",
                content_hash=content_hash,
            )
        return self._blobs.get(content_hash)

    def payload_bytes(self, record: ActiveEvidenceRecord) -> bytes:
        """The durable producer payload of one committed record."""

        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT payload_content_hash FROM evidence_records"
                    " WHERE issuer_namespace = :ns"
                    " AND evidence_id = :evidence_id"
                    " AND revision = :revision"
                ),
                {
                    "ns": self._issuer_namespace,
                    "evidence_id": record.evidence.evidence_id,
                    "revision": record.revision,
                },
            ).first()
        if row is None:
            raise EvidenceStoreError(
                "record_unknown", "no committed row for record"
            )
        return self._blobs.get(str(row.payload_content_hash))

    def commit_sequence(self) -> int:
        with self._engine.connect() as conn:
            return int(self._head(conn).last_commit_sequence)

    def dependency_root(self) -> str:
        with self._engine.connect() as conn:
            return str(self._head(conn).dependency_root)

    @property
    def issuer_namespace(self) -> str:
        return self._issuer_namespace


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


__all__ = [
    "EVIDENCE_STORE_SCHEMA_VERSION",
    "EvidenceRepository",
    "EvidenceStoreError",
    "GENESIS_DEPENDENCY_ROOT",
    "required_capability",
]
