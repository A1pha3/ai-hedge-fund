# Runbook: BTST Regime Forward Paired Shadow Trial (v3)

Operating guide for the **forward paired shadow-trial primitives** intended to
measure whether regime-gating the BTST breakout entry (Champion `IGNORE` vs
Challenger `NORMAL_ONLY`) improves real P&L. This path never issues a live
order.

> **Current status (2026-08-13):** the contracts, stores, runner/replay/
> evaluator primitives, and fixture-driven adversarial tests are present, but
> the official forward Trial has **not started**. Typed candidate construction
> is replay-verifiable, but the official runner
> itself is disabled with `forward_input_authority_unavailable`: there is no
> store-owned committed snapshot receipt, complete ordered session-batch root,
> or sealed exchange decision window. Official CLI producer wiring,
> independent arm capital, signed Stage/session cutoffs,
> exchange-calendar T+1/T+10 scheduling, and originating-lot lifecycle remain
> unavailable. Replay/capital/consumption inputs
> are therefore unavailable to the CLI assessment. No official result can yet
> be evaluated or considered for promotion.

## What it is

The target design runs two arms of the same decision forward in shadow over
the same exogenous facts:

- **Champion** — current production policy: regime admission `IGNORE` (the
  BTST breakout fires regardless of regime).
- **Challenger** — regime-gated policy: regime admission `NORMAL_ONLY` (the
  entry is admitted only in `NORMAL` regime; other regimes block).

Both arms share one frozen trusted clock, one canonical regime observation
(before cutoff), and one immutable producer input. Each arm must use the
pre-decision capital snapshot derived from its own isolated,
conservation-checked `DAILY_BAR_PROXY` ledger; a shared capital snapshot would
erase the economic divergence between arms. The primitives model an atomic
pair-commit boundary and exact-validation on replay, but the standalone CLI
does not yet assemble the real producer and per-arm capital inputs required to
exercise that path officially.

The same safety gate covers current-cost and 2×-slippage replay before it
creates a target directory or restores capital. Individually committed
candidate records cannot prove that the candidate set is complete. The gate
must not be replaced by a caller-provided boolean, DTO, or synthetic witness.
The disabled runner and replay engine hold no injected producer, kernel,
capital, clock or store capability. Decision, advance, missed-session
finalization and replay reject before reading even an existing pair or target
path. Therefore legacy pair/status rows cannot trigger reserve resumption and
the unavailable path cannot write `NO_RUN`.

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
| `validate` | no | **Unavailable.** Checks only root/layout/trial-id path shape without following symlinks, then fails closed with `validation_inputs_unavailable`. A complete proof still needs a signed Stage, immutable store-seal receipt, hash-bound complete SessionSpine, and cold immutable snapshot. |
| `decide-session --signal-session YYYY-MM-DD` | no | **Unavailable.** Checks only path shape, then fails closed with `privileged_context_required` until real producer and independent per-arm capital inputs are wired. |
| `advance-session --market-session YYYY-MM-DD` | no | **Unavailable.** Checks only path shape, then fails closed with `privileged_context_required` until calendar/cutoff, market, corporate-action, and lot-lifecycle inputs are wired. |
| `assess --output PATH` | no | **Unavailable.** Fails closed with `assessment_inputs_unavailable`; it does not create or replace `--output`. |

### Security boundary

- **Root guards.** The root must be a real directory. Path-traversal roots
  (`..`) and symlink roots are rejected before anything is loaded.
- **No override flags.** The CLI recognises **no** `--policy-mode`,
  `--runtime-mode`, `--admission-mode`, `--cap`, or `--evidence-cutoff`
  flag, and reads **no** environment switch. The current unavailable commands
  read no frozen values at all; a future enabled command may consume them
  only from canonically rooted sealed artefacts.
- **No auto-create / auto-seal.** The CLI cannot create or seal a Trial.
- **No executable surface.** The trial path imports only the runner, replay
  engine, proxy adapter, lifecycle, decision store, genesis, and evaluator.
  It never reaches broker, gateway authority/decisions, activation, outbox,
  or `shadow_trust`. (Pinned by `test_regime_trial_import_boundary`.)

### Operational-context boundary

None of the four commands is self-contained over the current root. They check
only the fixed path layout with no-follow metadata reads, then **fail closed**
without opening SQLite or Trial content. Consequently, none of the four
commands currently reads frozen policy/Stage/session values or proves a
canonical Trial root; path-shape validation must never be described as such a
proof. In particular, the CLI does not bind a real BTST
producer payload to both policy arms, derive each arm's own PIT capital state,
enforce a signed Stage and per-session evidence cutoff, resolve T+1/T+10 from
the exchange calendar, or carry the originating lot through exit and company
actions. The Task 11–13 tests prove properties of the delegated primitives
under controlled fixtures; they do not prove an end-to-end official Trial.

## Fault tolerance (scope of the test campaign)

Under the campaign's synthetic fixtures, the append-only phase-fact store and
the capital kernel's execution-id / source-id dedup exercise these convergence
properties:

- a crash after one arm's reserve lets replay commit the other;
- a crash after an entry/exit fill does not duplicate the position or oversell;
- a crash at any session-ladder boundary resumes from the first uncommitted
  checkpoint;
- a down-limit lock or suspension retains the position and the exit mandate;
  the next tradable session fills it (no oversell across sessions);
- a writer-lease takeover fences future entry writes; exit obligations survive;
- a divergent re-commit of the pair under the same key is a permanent latch.

(Pinned by `test_regime_trial_fault_campaign` plus the Task 9/10 component
crash suites.) These tests do not supply the missing real producer, calendar,
per-arm capital, Stage/cutoff, or originating-lot lifecycle context.

All four commands share only a path-shape guard. It uses `lstat` to require
real fixed-name files/directories and rejects root/layout symlinks plus path-like
Trial ids; it never opens the SQLite files. The prior `mode=ro&immutable=1`
approach was removed because SQLite immutable mode ignores committed WAL pages
and therefore cannot witness current truth while a writer is active. A real
validator must consume a governance-signed Stage, an immutable store-seal
receipt, a hash-bound complete SessionSpine, and a cold immutable snapshot.
Until that design exists, returning success would overstate the evidence.

## The assessment report

`assess` currently writes **no report**. A sealed registration alone cannot
prove the official current-cost and 2×-slippage replay hashes, independent
Champion/Challenger capital reports, or evidence-consumption ledger. It raises
`assessment_inputs_unavailable` and leaves `--output` absent or unchanged
rather than substituting zero hashes and all-false gates.

Once those inputs are operationally wired and verified, the intended output
is a deletable JSON projection containing only content-addressed hashes and
computed eligibility gates — no NAV series, decision payload, or capital-event
bytes. That future projection must be reproducible from its referenced facts.

The future headline contract is:

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
