# Migration: arm-specific shadow capital checkpoint v2

Date: 2026-08-13

Status: offline pure-contract remediation only. Official forward runner and
replay remain disabled with `forward_input_authority_unavailable`.

## Change

`ShadowCapitalCheckpoint` hash domain advances to v2 and now binds the full
source provenance of one arm's capital truth:

- trial id and exact `CHAMPION | CHALLENGER` arm;
- isolated portfolio id and `DAILY_BAR_PROXY` mode;
- capital store identity;
- sealed Trial genesis-manifest hash and the arm's capital-backup genesis root;
- exact embedded `CapitalRiskSnapshot` and its content hash.

`ShadowKernelInput` rejects checkpoint/shared mismatches in trial, arm,
portfolio or mode. A proxy checkpoint cannot name a broker account.

The pure `build_arm_kernel_inputs` API deletes the single `capital_snapshot`
shortcut. It accepts two already-verified `ShadowCapitalCheckpoint` values,
plus explicit deadline and sizing inputs, and builds each arm's NAV-derived
targets from that arm's snapshot. It does not synthesize a receipt. The pure
`build_pair_records` API accepts both full checkpoints and computes each row's
`arm_capital_checkpoint_hash` internally; caller-supplied naked hashes are no
longer accepted.

## Compatibility and evidence consequence

Old v1 checkpoints and decision rows do not prove an arm/store/genesis
binding. They are historical observations only and cannot be renamed,
upgraded, crash-resumed or consumed by a future official Trial. Any eventual
activation requires store-owned checkpoint receipts for both arms and exact
verification against the sealed genesis manifest.

This change grants no authority, creates no Trial, performs no capital write
and connects no broker. Correct runtime status remains
`INACTIVE / FORWARD_TRIAL_NOT_STARTED`.
