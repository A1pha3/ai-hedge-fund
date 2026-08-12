# Runbook: BTST Regime Forward Paired Shadow Trial (v3)

Operating guide for the **forward paired shadow-trial primitives** intended to
measure whether regime-gating the BTST breakout entry (Champion `IGNORE` vs
Challenger `NORMAL_ONLY`) improves real P&L. This path never issues a live
order.

> **Current status (2026-08-12):** the contracts, stores, runner/replay/
> evaluator primitives, and fixture-driven adversarial tests are present, but
> the official forward Trial has **not started**. Real producer input,
> independent capital state for both arms, signed Stage/session cutoffs,
> exchange-calendar T+1/T+10 scheduling, and originating-lot lifecycle remain
> to be corrected and operationally wired. Replay/capital/consumption inputs
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
| `validate` | no | **Available.** Opens decision/spine SQLite with immutable read-only URIs (no repository constructors, migrations, journal changes, or sidecars), freezes the clock once, then verifies governance semantics, the complete registered/archive genesis binding and content roots, research-program enrollment, and current writer lease. |
| `decide-session --signal-session YYYY-MM-DD` | no | **Unavailable.** Verifies the sealed Trial, then fails closed with `privileged_context_required` until real producer and independent per-arm capital inputs are wired. |
| `advance-session --market-session YYYY-MM-DD` | no | **Unavailable.** Verifies the sealed Trial, then fails closed with `privileged_context_required` until calendar/cutoff, market, corporate-action, and lot-lifecycle inputs are wired. |
| `assess --output PATH` | no | **Unavailable.** Fails closed with `assessment_inputs_unavailable`; it does not create or replace `--output`. |

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

### Operational-context boundary

Only `validate` is self-contained over the sealed artefacts.
`decide-session`, `advance-session`, and `assess` load and verify the sealed
Trial, then **fail closed** because the standalone CLI cannot synthesize the
missing operational facts. In particular, the CLI does not bind a real BTST
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

All four commands share the same physically read-only loader. SQLite files
are opened with `mode=ro&immutable=1`; validation never constructs the
writer repositories because their initialization path performs schema/WAL
setup. A missing or malformed table, invalid governance bundle, any field
drift between the registered and archived genesis manifests, content-root
failure, absent program enrollment, or missing/stale writer epoch fails
closed without changing any Trial byte or creating a SQLite sidecar.

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
