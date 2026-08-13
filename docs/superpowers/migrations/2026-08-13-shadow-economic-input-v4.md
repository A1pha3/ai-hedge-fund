# Migration: Shadow economic input closure and ShadowDecision v4

Date: 2026-08-13

Status: offline primitive only; official forward runner and replay remain
disabled with `forward_input_authority_unavailable`.

## Change

`ShadowKernelInput` now contains every pure economic input that may change a
decision:

- a cutoff-visible `FrozenTradingSessionSchedule` with exactly the next ten
  ordered exchange sessions;
- the complete `SizingConfig` used by `decide_shadow`.

The kernel maps T+1 and T+10 from the frozen exchange-session tuple. It no
longer adds natural calendar days. Prices that are not exact cent ticks fail
closed as `PRICE_BOUNDARY_INVALID`.

Sizing now carries `worst_case_fee_reserve_cents` separately from the total
reserve. `ShadowOrderLine` copies quantity, price, fee reserve and total
reserve verbatim from the shared sizing result; it never applies floors,
fallbacks or a zero-fee reconstruction.

`ShadowDecision` advances from schema major 3 to 4, namespace
`growth-kernel.shadow.v3`, hash domain
`ai-hedge-fund.v3.decision.shadow-decision.v3`, and capability version
`growth-kernel-shadow.v3`. Schema-major-3 bytes remain read-only through
`LegacyShadowDecisionV3`; there is no upgrader and old observations are never
eligible for the future official Trial.

Every v4 decision now embeds a strict `ShadowTradingScheduleBinding`: calendar
identity/version/artifact hash, signal session, the exact next ten exchange
sessions, cutoff availability, and a hash of that complete schedule. The
decision validator requires header T+1 and every line's T+10 to match the
binding. Dates alone are not accepted as proof.

The shadow proxy capital writer accepts exactly the current schema-major-4
model. `LegacyShadowDecisionV3` remains audit-readable only and cannot enter
the store/proxy write type.

The Plan 05 `DailyActionFlow` direct projection has been removed. In SHADOW
mode it now returns `economic_input_authority_unavailable` before evidence,
producer, kernel or persister calls. It cannot synthesize natural-day dates or
publish a v4 decision while authoritative schedule/`decide_shadow` wiring is
absent.

## Evidence-generation consequence

This is a behavioral generation change: session selection, cost projection,
decision bytes and artifact hashes can change. No prior decision, assessment,
outcome or evidence-consumption row may be renamed or reused as v4 evidence.
The future runner must receive a store-owned calendar receipt and separately
verified arm capital checkpoints before it can be enabled.

## Non-goals

This migration does not implement calendar publication authority, arm-specific
capital checkpoint provenance, trial activation, broker authority, or any real
order path. Correct runtime status remains `INACTIVE / FORWARD_TRIAL_NOT_STARTED`.
