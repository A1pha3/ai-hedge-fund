# Migration: BTST raw-candidate payload v1

**Date:** 2026-08-12

**Scope:** BTST producer evidence only

**Status:** shadow evidence; no runner, capital, gateway, CLI, or broker change

## Cutover

Each BTST `SignalEvidence` now binds a separate strict/frozen
`BtstRawCandidatePayload` through `payload_content_hash`. The content-addressed
raw bytes are made durable before the signed signal envelope is published.
The existing `SignalEvidence` schema remains major 2; the independent raw
payload starts at schema major 1.

The payload freezes candidate identity, exchange-qualified security id,
integer entry-price micros, producer target-weight ppm, trigger-strength ppm,
typed industry presence, PIT snapshot/setup fingerprints, signal session, and
producer/version provenance. Producer target weight remains raw evidence;
downstream arms may clamp it but this cutover does not derive a fixed NAV
allocation.

Unknown or contradictory exchange identities fail closed. Missing industry is
encoded as `industry_state="UNKNOWN"` with `industry=null`; no exchange or
industry is guessed.

## Evidence generation

This evidence behavior opens a new generation:

- `BTST_STRATEGY_SEMVER`: `0.1.0` → `0.2.0`
- `BTST_BEHAVIOR_BASELINE`: `sha256("btst-v1")` →
  `sha256("btst-raw-candidate-payload-v1")`
- execution and cost semantics remain `btst.funnel.v1` and
  `cn-a-share-costs.v1`

Historical signal envelopes whose payload hash was only a synthetic candidate
digest do not acquire raw bytes by backfill. The new reader therefore rejects
them as missing raw candidate evidence; they cannot be used as official input
to the new forward evidence generation. Existing evidence ids remain stable,
so a same-session correction must use the repository revision protocol rather
than overwrite revision 1.

## Failure and rollback semantics

A crash after the raw blob fsync may leave an orphan blob. It cannot leave a
committed signal envelope pointing to absent bytes because signing/publication
occurs only after the durable blob hash has been compared with
`SignalEvidence.payload_content_hash`. Missing, tampered, cross-session,
cross-candidate, or version-divergent payloads fail closed on read.

There is no live-capital rollback: this cutover changes only shadow producer
evidence. Reverting code does not delete blobs or rewrite append-only evidence.
