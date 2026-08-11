# Runbook: BTST Regime Forward Paired Shadow Trial (v3)

Operating guide for the **forward paired shadow trial** that measures whether
regime-gating the BTST breakout entry (Champion `IGNORE` vs Challenger
`NORMAL_ONLY`) improves real P&L. This is a **measurement system only** — it
never issues a live order. Every artefact is content-addressed and the
assessment report is a deletable projection.

## What it is

Two arms of the same decision, run forward in shadow over the same exogenous
facts:

- **Champion** — current production policy: regime admission `IGNORE` (the
  BTST breakout fires regardless of regime).
- **Challenger** — regime-gated policy: regime admission `NORMAL_ONLY` (the
  entry is admitted only in `NORMAL` regime; other regimes block).

Both arms share one frozen trusted clock, one canonical regime observation
(before cutoff), one producer run, and one capital snapshot per session.
Each arm settles into its own isolated, conservation-checked `DAILY_BAR_PROXY`
ledger. The atomic pair commit is the side-effect boundary; a crashed run
replays by exact-validating the existing pair and never recomputes an
alternate proposal.

## The on-disk Trial root

A sealed Trial lives under one directory (`--root`):

```
{root}/
  decisions.sqlite3      # TrialArmDecisionStore: registration + committed pairs
  spine.sqlite3          # SessionSpine: enrolled sessions + terminal statuses
  evidence.sqlite3       # EvidenceRepository: regime + snapshot evidence
  archive/               # TrialGenesisArchive: equal-genesis manifests + arm ledgers
  blobs/                 # BlobStore: evidence payloads
```

The CLI **consumes** this layout; it never creates or seals a Trial. A
separate sealing flow (governance + genesis) populates it.

## The operator CLI

```
python scripts/v3_regime_trial.py <command> --root PATH --trial-id ID
```

| Command | Mutates? | What it does |
|---|---|---|
| `validate` | no | Loads the sealed bundle, genesis manifest, and spine; verifies mutual consistency. Strictly read-only. |
| `decide-session --signal-session YYYY-MM-DD` | yes | Delegates one enrolled signal session to the `ForwardPairedTrialRunner` (atomic pair commit). |
| `advance-session --market-session YYYY-MM-DD` | yes | Drives one market session of both arms through the replay lifecycle (entry/exit run-out). |
| `assess --output PATH` | report only | Renders the deletable assessment projection to `--output`. |

### Security boundary

- **Root guards.** The root must be a real directory. Path-traversal roots
  (`..`) and symlink roots are rejected before anything is loaded.
- **No override flags.** The CLI recognises **no** `--policy-mode`,
  `--runtime-mode`, `--admission-mode`, `--cap`, or `--evidence-cutoff`
  flag, and reads **no** environment switch. Every frozen value comes from
  the sealed artefacts.
- **No auto-create / auto-seal.** The CLI cannot create or seal a Trial.
- **No executable surface.** The trial path imports only the runner, replay
  engine, proxy adapter, lifecycle, decision store, genesis, and evaluator.
  It never reaches broker, gateway authority/decisions, activation, outbox,
  or `shadow_trust`. (Pinned by `test_regime_trial_import_boundary`.)

### Execution boundary (decide-session / advance-session)

`validate` and `assess` are self-contained over the sealed artefacts. The two
mutating commands load and verify the sealed trial, then **fail closed**:
the forward decision needs the BTST producer's Ed25519 trust chain and the
PIT capital baseline that the **privileged worker (Plan 06+)** injects. The
standalone CLI takes only `--root` and `--trial-id` and cannot synthesise
either without crossing the `shadow_trust` boundary the import guard forbids.
The commands exist as the operator-facing entrypoints and document that
boundary honestly. The green Task 11–13 suites prove the delegated execution.

## Fault tolerance (what the campaign proves)

Crashes converge. The append-only phase-fact store and the capital kernel's
execution-id / source-id dedup make every phase idempotent:

- a crash after one arm's reserve lets replay commit the other;
- a crash after an entry/exit fill does not duplicate the position or oversell;
- a crash at any session-ladder boundary resumes from the first uncommitted
  checkpoint;
- a down-limit lock or suspension retains the position and the exit mandate;
  the next tradable session fills it (no oversell across sessions);
- a writer-lease takeover fences future entry writes; exit obligations survive;
- a divergent re-commit of the pair under the same key is a permanent latch.

(Pinned by `test_regime_trial_fault_campaign` plus the Task 9/10 component
crash suites.)

## The assessment report

`assess` writes a deletable JSON projection to `--output`. It holds **only**
content-addressed hashes and computed eligibility gates — no NAV series, no
decision payload, no capital-event bytes. Deleting it loses no truth; the
same referenced artefacts deterministically reproduce it.

The headline is:

- `NOT_ELIGIBLE` when any gate fails (or cannot be proven green);
- at most `INACTIVE_PROMOTION_CANDIDATE` when all gates pass — a
  `DAILY_BAR_PROXY` evaluation can **never** promote to live capital.

`BROKER_CONFIRMED` requires a separate, non-reused real forward Trial.

## Tests

```
.venv/bin/python -m pytest tests/offensive/v3/ -q
```

The Task 14 trio:

- `tests/offensive/v3/test_v3_regime_trial_cli.py` — guards, no-write,
  no-override-flags, dispatch.
- `tests/offensive/v3/orchestration/test_regime_trial_fault_campaign.py` —
  adversarial input + crash convergence at the orchestration level.
- `tests/offensive/v3/orchestration/test_regime_trial_import_boundary.py` —
  the trial path imports no executable/authority/broker surface.
