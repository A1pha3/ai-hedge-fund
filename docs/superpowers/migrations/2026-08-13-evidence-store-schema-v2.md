# Evidence Store schema v2 clean cutover

Status: implemented as an offline primitive. This migration does not activate
capital, authorize entry, or connect a broker.

## Why v2 exists

The pre-v2 BTST producer wrote a synthetic `payload_content_hash`; it did not
persist the replayable raw-candidate bytes under that hash. Therefore no
general, honest in-place backfill exists. Schema v2 is deliberately a new
database or new empty issuer-namespace cutover, not an automatic migration.

Schema v2 makes the Evidence Store transaction the authority for those
referenced bytes. `evidence_referenced_payloads` stores exact bytes keyed by
`(issuer_namespace, content_hash)`, while
`evidence_referenced_bindings` indexes every `(issuer_namespace, evidence_id,
revision)` to its raw hash. The filesystem blob is only an audit mirror. It is
never a fallback source for BTST v2 reads or repairs.

## Cutover preconditions

- Back up the legacy SQLite database with its WAL/SHM files and blob root.
- Stop and fence every legacy writer.
- Provision a new database or an issuer namespace with zero committed rows,
  zero prepared rows and `last_commit_sequence == 0`.
- Preserve the old database read-only as audit history. It is
  `LEGACY_UNREPLAYABLE` and cannot enter primary promotion evidence.

Opening any nonempty namespace without an `evidence_schema_meta` row fails
with `legacy_store_requires_offline_cutover`. There is no environment flag,
CLI flag or filesystem reconstruction path that bypasses this check.

## Transactional initialization

The repository acquires a physical SQLite `BEGIN IMMEDIATE` writer transaction
before its first schema read. For an empty namespace it atomically:

1. creates the v2 tables, indexes and triggers;
2. verifies every stored schema definition against the canonical definition;
3. writes the singleton `(issuer_namespace, schema_version=2)` row to
   `evidence_schema_meta`; and
4. creates the zero-sequence namespace head if absent.

Explicit `BEGIN IMMEDIATE` is required because Python's legacy sqlite3
transaction mode does not otherwise make DDL rollback-safe. Any failure rolls
back schema and metadata changes. Startup verifies table, index and trigger
definitions as well as every BTST signal's binding, raw row, content hash and
strict payload/envelope relationship.

New BTST publications and prepared corrections must pass raw bytes explicitly
to the repository. The repository validates those immutable ingress bytes,
then inserts raw bytes, the indexed binding and the evidence row in that order
inside one `BEGIN IMMEDIATE` transaction. Database triggers independently
reject a BTST signal row unless its exact revision binding and raw row already
exist. Concurrent identical publication uses insert-on-conflict plus an exact
byte re-read and converges idempotently.

Signature verification and external durable-blob I/O happen before the SQLite
writer transaction. They do not own `ingested_at` or `activated_at`. For every
new publish, prepared correction, and activation, the repository reads the
trusted clock again only after `BEGIN IMMEDIATE` has acquired the writer lock;
that second timestamp owns the store timeline. A rollback relative to the
earlier verification or already-stored trusted fact aborts with
`trusted_clock_rollback`. Idempotent retries return the existing record and do
not manufacture a later store timestamp. This prevents slow blob I/O or lock
waits from making a fact committed after an OOS cutoff appear visible before
that cutoff.

If an existing binding or raw row is missing, publication, correction, replay
and restart all fail closed. A retry never repairs it from the mirror.

## Immutability and correction compatibility

SQLite triggers reject `UPDATE` and `DELETE` of committed evidence records,
referenced raw bytes, indexed bindings, and schema metadata. Prepared records
reject `UPDATE`;
activation currently moves a prepared row into the committed table and then
deletes that prepared row in the same transaction, so prepared-row `DELETE`
cannot yet be globally forbidden.

Corrections remain append-only revisions. Within one `evidence_id`, every
revision freezes the concrete evidence kind, source authority, subject scope,
producer, family, strategy semver, behavior fingerprint, policy epoch,
execution version, cost version, execution mode, and schema major. A behavior
change requires a new evidence generation and ID; it cannot masquerade as a
correction. Activation advances exactly one revision, and retrying an older
already-activated revision cannot return a false active projection.

## Rollback and compatibility

V2 is not an in-place continuation of a nonempty legacy namespace. Rollback
means fence the v2 writer and restore the legacy database plus matching blob
backup as one read-only unit. Never run v1 and v2 writers against one database.
The BTST insert triggers prevent an unfenced old writer from appending a signal
without a v2 binding.

An empty non-BTST namespace also records schema v2 without manufacturing raw
payloads. Other evidence kinds retain their existing BlobStore read semantics;
only BTST signal evidence requires store-owned raw bytes and exact bindings.

## Deliberate remaining safety boundary

This migration does not solve dependency-fix activation fencing. The existing
`DependencyFixLedger` and `EvidenceRepository.activate_revision()` are
separate components; direct repository activation is not yet mechanically
conditioned on a durable `EntryFenceRaised` acknowledgement. Until that
integration is implemented and fault-tested, callers must not treat correction
activation as production-safe authorization state. The correct production
posture remains fail-closed/no-trade.
