# Migration: withdraw the unfenced shadow-capital mutation namespace

**Date:** 2026-08-13  
**Runtime status:** `INACTIVE / FORWARD_TRIAL_NOT_STARTED`  
**Authority impact:** none; no authority is activated or delegated

## Decision

The public mutation facades of the unstarted BTST paired Trial's temporary
`DAILY_BAR_PROXY` ledgers are withdrawn.  They now raise the typed error
`shadow_capital_fence_authority_unavailable` before reading a decision-store
lease, pair, bar, evidence record, exit lane, clock, or capital repository.
The boundary covers reserve, entry settlement, shadow exit settlement,
valuation, checkpoints, lifecycle advance, and the directly importable replay
write helpers (including temporary-ledger corporate-action and restatement
helpers).

This is a namespace withdrawal, not an entry kill switch.  The official Trial
never started and therefore has no authoritative shadow positions or exit
obligations.  Generic `AccountCapitalTruth` correction/company-action APIs and
the Gateway `ExitLane` are unchanged and remain outside this guard.  Real
economic exits, corrections, reconciliation, and company actions must continue
regardless of entry admission state.

## Why a decision-store lease is insufficient

The existing lease is stored with the pair decisions while the two arm capital
ledgers are separate SQLite databases.  Checking that lease and then writing a
capital database leaves a takeover window: the old writer can pass the check,
lose the lease, and still commit after the new writer.  Idempotency detects
same-key replays but cannot order different valid operation ids.  Mirroring the
lease into each database without an atomic ownership protocol would merely add
a second truth.

The smallest honest closure is therefore no shadow-capital writes.  Internal
pure resolvers, read-only lot-origin lookup, and the corrected originating-lot
model remain available as construction material; retained mutation bodies are
unreachable through public facades and are not runtime capability claims.

## Re-enable gate

Restoring this namespace requires a separately reviewed protocol that proves:

- a capital-local monotone fencing epoch in each arm database;
- atomic claim/renew/expiry/takeover semantics bound to writer identity;
- every capital mutation validates and consumes the current fence in the same
  local transaction as its economic event;
- stable operation ids and divergent replay latching across takeover;
- independent exit liveness, including crash recovery and correction/bust
  reopening, without relying on entry authority;
- deterministic two-arm orchestration without pretending the two databases
  form one transaction;
- a fresh forward namespace; no legacy unfenced rows are promoted or silently
  adopted.

Positive mutation tests are retained as explicit future-fence contract skips.
The active stopgap tests use poison inputs and an AST first-statement guard to
prove rejection precedes every external observation, while separately proving
the generic authoritative exit/correction APIs did not receive this guard.

