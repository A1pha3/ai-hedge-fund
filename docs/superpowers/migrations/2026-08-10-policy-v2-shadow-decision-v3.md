# Migration: Policy schema-major 2 + ShadowDecision schema-major 3

**Date:** 2026-08-10
**Scope:** BTST regime forward paired shadow trial (Plan Tasks 1–14)
**Status:** shadow-only. No live migration, no authority flip, no canary.

This documents the two contract cutovers the paired trial rests on, so a
future operator who must re-derive the system from its artefacts can see
*why* the schema versions moved and *what* is invariant across them.

## 1. Policy snapshot → schema-major 2

`PolicySnapshot.schema_major` moved to **2**. What changed:

- **`runtime_mode`** is now a first-class, typed field (`OFF | SHADOW |
  BTST_CANARY | AUTHORITATIVE`). The paired trial runs only under `SHADOW`;
  the CLI and the daily-action hook both gate on it.
- **`btst_regime_admission_mode`** is a typed producer field
  (`IGNORE | NORMAL_ONLY | …`). The paired trial binds Champion to `IGNORE`
  (current production) and Challenger to `NORMAL_ONLY` (the regime gate
  under test). The two arms must bind **distinct** policy fingerprints; the
  decision store rejects a pair whose two arms carry the same fingerprint
  (`policy_binding_duplicate`).
- **Capital/risk/ADV/execution/evidence-gate sections** are structured
  sub-objects. All caps are `Decimal` strings.

The shipped production snapshot is `config/policies/v3/policy-v2.json`:
`runtime_mode "off"`, `btst_regime_admission_mode "IGNORE"`, all caps `0`.
This is the **fail-closed** baseline — no live capital, no admission. The
trial's sealed baseline/target policies are distinct snapshots over the same
schema.

**Invariant:** a `schema_major != 2` policy cannot load
(`load_policy_snapshot` rejects); the shadow proxy adapter re-validates the
schema on every admission.

## 2. ShadowDecision → schema-major 3

`ShadowDecision.schema_major` moved to **3** and now carries **literal
absence of execution authority**:

- `execution_authority: Literal["NONE"]` — a frozen field. The shadow proxy
  adapter re-validates `== "NONE"` before **any** capital write
  (`execution_authority_not_none`). The contract pins it, and the content
  hash re-validates it, so the store can never hold a non-`NONE` decision.
- `shadow_policy_binding` — provenance for *which* sealed policy this
  counterfactual arm binds (baseline activation hash for the Champion;
  target policy registration hash for the Challenger). This is the
  policy-provenance cutover: the decision names its policy by hash, not by
  ambient activation.
- `domain_hash` envelope accepts `{2, 3}` — `LegacyShadowDecisionV2` is kept
  **read-only** to preserve historical bytes; nothing writes schema-2
  decisions anymore.

**Why:** the paired trial's two arms must be economically identical except
for the one policy knob under test. Binding policy by hash inside the
decision makes that single difference auditable and makes a divergent replay
under the same stable economic id a permanent protocol breach
(`shadow_proxy_protocol_breach`), not a silent re-settlement.

## 3. What did NOT change

- The **economic algorithm** is unchanged. Reserve, mechanical shrink, fill,
  fee, and exit settlement all live in the shared `settle_proxy_open` core
  and the capital kernel; the shadow adapter and the authorised proxy use
  the *same* economics. The cutover is purely about *provenance and
  authority*, not about money.
- The **capital ledger** schema is unchanged. Genesis issuance, reserves,
  fills, fees, valuations, checkpoints, and conservation are the same
  primitives Plan 04–06 built.
- The **statistical evaluator** is unchanged (Plan 03). The paired trial
  feeds it the same excess-growth / paired-difference machinery.

## 4. Rollback

There is no rollback path because there is no live state to roll back. This
is a shadow measurement system: `runtime_mode "off"`, zero caps, no broker,
no activation. If the schema proves wrong, the trial's conclusions are
voided and the sealed artefacts are discarded; production is untouched.

## 5. Verification

- `uv run flake8` (line length 420) on the trial path and CLI.
- `.venv/bin/python -m pytest tests/offensive/v3/ -q` — the full v3 suite,
  including the Task 14 trio (CLI guards, fault campaign, import boundary).
- `scripts/v3_refresh_contract_snapshots.py --check` — the deterministic
  contract fixtures regenerate byte-identically.
