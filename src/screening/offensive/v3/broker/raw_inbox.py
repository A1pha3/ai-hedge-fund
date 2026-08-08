"""Plan 07 Task 1: durable broker raw inbox.

Every authenticated raw broker response is appended here before any
normalization. The inbox is content-addressed (one row per
``payload_hash``) and per-source sequentially ordered, so that a crash
between the durable append and the normalization never loses a raw fact,
and a tampered/rolled-back broker sequence halts rather than silently
reorders.

Secret fields are redacted before durability: the caller-declared payload
may contain ``session_token``-style fields; the inbox strips them to a
``[REDACTED]`` sentinel in the stored envelope, never persisting the raw
secret. If a payload value cannot be redacted canonically (e.g. ``bytes``)
the append fails closed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterator

from src.screening.offensive.v3.broker.ports import BrokerRawEnvelope

_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_inbox_revisions (
    revision INTEGER PRIMARY KEY AUTOINCREMENT,
    envelope_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_sequence INTEGER NOT NULL,
    parser_version TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    normalized_revision TEXT,
    received_at TEXT NOT NULL,
    UNIQUE(envelope_id),
    UNIQUE(source, source_sequence)
);
CREATE INDEX IF NOT EXISTS ix_raw_inbox_source_seq
    ON raw_inbox_revisions(source, source_sequence);
"""

_SECRET_KEYS = frozenset(
    {
        "session_token",
        "auth_token",
        "api_key",
        "api_secret",
        "secret",
        "access_token",
        "refresh_token",
        "password",
        "signature",
        "cookie",
    }
)


class RawInboxError(ValueError):
    """Raw inbox failure carrying a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class RawInboxRecord:
    """One durable raw revision."""

    revision: int
    envelope_id: str
    source: str
    source_sequence: int
    parser_version: str
    payload_hash: str
    envelope: BrokerRawEnvelope
    normalized_revision: str | None


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` with known secret keys replaced.

    Non-string, non-int, non-float, non-None secret values (e.g. ``bytes``)
    cannot be redacted canonically and cause a structural failure rather
    than a silent drop.
    """

    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in _SECRET_KEYS:
            if not isinstance(value, (str, int, float, type(None), bool)):
                raise RawInboxError(
                    "UNREDACTABLE_SECRET",
                    f"secret field {key!r} has unsupported type"
                    f" {type(value).__name__}",
                )
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = _redact_payload(value)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_payload(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted


class BrokerRawInbox:
    """Append-only, content-addressed raw response store."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> BrokerRawInbox:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def append(
        self,
        envelope: BrokerRawEnvelope,
        *,
        envelope_id: str,
    ) -> RawInboxRecord:
        """Append one envelope, idempotent on identical replay.

        Raises ``RawInboxError`` with a stable code on:
        - ``PAYLOAD_CONFLICT``: same ``envelope_id`` but different content.
        - ``SEQUENCE_CONFLICT``: same ``source`` with a rolled-back or
          gapped ``source_sequence``.
        - ``UNREDACTABLE_SECRET``: a secret field cannot be redacted.
        """

        redacted_payload = _redact_payload(dict(envelope.payload))
        redacted = envelope.model_copy(update={"payload": redacted_payload})
        payload_hash = redacted.content_hash()
        payload_json = redacted.model_dump_json()

        existing = self._conn.execute(
            "SELECT revision, payload_hash FROM raw_inbox_revisions"
            " WHERE envelope_id = ?",
            (envelope_id,),
        ).fetchone()
        if existing is not None:
            if existing["payload_hash"] != payload_hash:
                raise RawInboxError(
                    "PAYLOAD_CONFLICT",
                    f"envelope {envelope_id} already stored with different"
                    f" content",
                )
            return self._record(self._fetch(existing["revision"]))

        last_seq = self._conn.execute(
            "SELECT MAX(source_sequence) AS last FROM raw_inbox_revisions"
            " WHERE source = ?",
            (envelope.source,),
        ).fetchone()["last"]
        if last_seq is not None and envelope.source_sequence <= int(last_seq):
            raise RawInboxError(
                "SEQUENCE_CONFLICT",
                f"source {envelope.source!r} sequence"
                f" {envelope.source_sequence} <= last {last_seq}",
            )
        if last_seq is not None and envelope.source_sequence != int(last_seq) + 1:
            raise RawInboxError(
                "SEQUENCE_CONFLICT",
                f"source {envelope.source!r} sequence"
                f" {envelope.source_sequence} gaps last {last_seq}",
            )

        cursor = self._conn.execute(
            "INSERT INTO raw_inbox_revisions"
            " (envelope_id, source, source_sequence, parser_version,"
            "  payload_hash, payload_json, normalized_revision, received_at)"
            " VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
            (
                envelope_id,
                envelope.source,
                envelope.source_sequence,
                envelope.parser_version,
                payload_hash,
                payload_json,
                envelope.received_at.isoformat(),
            ),
        )
        self._conn.commit()
        return self._record(self._fetch(int(cursor.lastrowid)))

    def get(self, revision: int) -> RawInboxRecord | None:
        return self._record(self._fetch(revision))

    def pending(self) -> tuple[int, ...]:
        rows = self._conn.execute(
            "SELECT revision FROM raw_inbox_revisions"
            " WHERE normalized_revision IS NULL ORDER BY revision"
        ).fetchall()
        return tuple(int(row["revision"]) for row in rows)

    def mark_normalized(self, revision: int, *, normalized_revision: str) -> None:
        row = self._fetch(revision)
        if row is None:
            raise RawInboxError("UNKNOWN_REVISION", f"no raw revision {revision}")
        current = row["normalized_revision"]
        if current is not None and current != normalized_revision:
            raise RawInboxError(
                "NORMALIZED_BINDING_CONFLICT",
                f"raw revision {revision} already bound to {current!r}",
            )
        self._conn.execute(
            "UPDATE raw_inbox_revisions SET normalized_revision = ?"
            " WHERE revision = ? AND (normalized_revision IS NULL"
            " OR normalized_revision = ?)",
            (normalized_revision, revision, normalized_revision),
        )
        self._conn.commit()

    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM raw_inbox_revisions"
        ).fetchone()
        return int(row["n"])

    def iter_all(self) -> Iterator[RawInboxRecord]:
        rows = self._conn.execute(
            "SELECT * FROM raw_inbox_revisions ORDER BY revision"
        ).fetchall()
        for row in rows:
            yield self._record(row)

    def _fetch(self, revision: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM raw_inbox_revisions WHERE revision = ?",
            (revision,),
        ).fetchone()

    def _record(self, row: sqlite3.Row | None) -> RawInboxRecord | None:
        if row is None:
            return None
        envelope = BrokerRawEnvelope.model_validate_json(row["payload_json"])
        return RawInboxRecord(
            revision=int(row["revision"]),
            envelope_id=str(row["envelope_id"]),
            source=str(row["source"]),
            source_sequence=int(row["source_sequence"]),
            parser_version=str(row["parser_version"]),
            payload_hash=str(row["payload_hash"]),
            envelope=envelope,
            normalized_revision=(
                None if row["normalized_revision"] is None
                else str(row["normalized_revision"])
            ),
        )
