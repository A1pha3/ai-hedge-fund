# Phase 3 Task 5 Report — Auditable exit-shadow report contract

## Status

The research-only exit-shadow CLI now publishes a deterministic, immutable, auditable
JSON/Markdown/commit-marker bundle. It analyzes a stable private snapshot of explicitly
validated inputs, detects source mutation (including ABA-style cache membership changes), and
fails closed before publication. It does not alter production policy, journals, caches, or
runtime paper-trading state.

## Delivered

- `scripts/run_exit_shadow_research.py` accepts only journal/cache/output paths, report `as_of`,
  bootstrap seed, and bootstrap draws. Seed must be nonnegative, draws positive, and the fixed
  10% activation / Wilder ATR(14) 2.5x policy cannot be changed from the CLI.
- Journal and cache paths are opened without following symlinks and must be a regular file and
  directory respectively. Every cache entry must be a nofollow regular file; FIFOs, devices,
  directories, and symlinks are rejected without blocking.
- Output must be lexically disjoint from the journal, cache, runtime/backtest data, price cache,
  and source tree. Existing symlink ancestors are rejected. Output traversal, staging,
  publication, validation, cleanup, and fsync use directory descriptors.
- Each run captures the journal and all 626 cache files once into a private read-only temporary
  snapshot. Analysis receives only snapshot paths. Exact before/snapshot/after manifests contain
  content hashes, sizes, and source identities; stable descriptor reads, directory identity, and
  a final pre-commit recapture detect torn reads, replacement, mutation, and cache membership ABA.
  The snapshot is always cleaned up.
- Publication creates `exit_shadow_DATE.json`, `exit_shadow_DATE.md`, then
  `exit_shadow_DATE.commit.json` last. Data files and marker are staged, fsynced, exclusively
  published, and followed by directory fsyncs. Hard-link publication has a safe `O_EXCL`
  fallback. Existing identical bundles are idempotent; partial identical bundles recover;
  mismatches conflict; concurrent identical completion is accepted. Only owned temporary names
  are cleaned after injected failures.
- The marker binds exact filenames, byte sizes, JSON/Markdown SHA-256 hashes, contract identity,
  report ID, and canonical semantic-payload hash. The JSON repeats contract identity, marker
  filename, semantic hash, and Markdown hash.
- JSON and Markdown carry the full fixed execution identity: activation and ATR method/period/
  multiple, session-1-open entry with no same-session exit, session-9-close baseline trigger,
  session-10 next-executable-open execution, next-open close-trigger execution, queue/suspension
  deferral, execution classifier, T+1, and the exact zero-cost `daily-action-v2` assumptions.
- Markdown separates reconstruction coverage from the common executable mask and reports each
  layer's covered/missing legacy means and exclusion reasons. It also includes paired mean,
  median, worst/downside-decile differences; per-arm returns, tails, holding periods, exit
  reasons, MFE diagnostics; candidate/usable/empty blocks; interval, draws, and seed.
- Permanent gates remain `mode=legacy_sensitivity`, `shadow_only=true`, and
  `production_eligible=false`. No network calls, production actions, or legacy writes were added.

## TDD and fault-injection evidence

The hardening work was driven by failing regressions before implementation. The focused suite
now has **49 tests**, including:

- CLI/path validation: symlink ancestors, source/output overlap, protected runtime/backtest/src
  paths, negative seed, nonpositive draws, symlink/FIFO/nonregular journal and cache entries;
- stable snapshots: analysis reads only the snapshot, before/snapshot/after fingerprints,
  mid-read replacement, cache membership ABA, final pre-commit mutation, and cleanup;
- bundle protocol: injected failure at every staging boundary, every data/marker publication
  boundary, both directory-fsync boundaries, hard-link fallback, partial recovery, idempotency,
  corruption/mismatch refusal, and identical concurrent completion;
- report contract: identity and semantic hash binding, complete fixed policy/cost disclosure,
  separate coverage layers, complete paired/per-arm/block/MFE statistics, and immutable
  shadow-only gates.

## Real-data read-only smoke

The actual script entry point ran with seed 42 and 10,000 bootstrap draws against the parent
workspace's `data/paper_trading_backtest/journal.jsonl` and 626-file `data/price_cache`. Output
went only to `/private/tmp/exit-shadow-final.BHVuFX`; `/tmp` was intentionally rejected because
it is a symlink on macOS. Complete source SHA-256 manifests were identical before and after.

- paired BTST denominator: **133**;
- reconstructable paths: **94** (**70.6767%**);
- common executable mask: **79** (**59.3985%** of paired denominator);
- unique signal days: **36**;
- bootstrap draws: **10,000**;
- semantic payload SHA-256:
  `ac23a5064751fe67aed3aa0c54dbd25f142d7e10ecb4d8f3115e31719ce35caa`;
- exactly three mode-`0644` artifacts, no staging residue;
- marker byte hashes and sizes matched both data artifacts, and its semantic hash recomputed from
  canonical JSON;
- before and after embedded input fingerprints matched exactly.

No repository report artifact was generated by the smoke run.

## Verification

- Focused report contract: **49 passed**.
- Research + offensive + focused regression suite: **785 passed**.
- Ruff lint, Ruff format check, and `git diff --check`: clean.
- Real-data entry-point smoke and independent marker/source-manifest assertions: exit 0.

## Limitations retained in every report

- This remains selected, retrospective, six-month legacy sensitivity evidence, not forward
  shadow evidence or a production-readiness gate.
- Reconstruction and common-mask missingness can introduce selection bias and remain disclosed
  next to the paired result.
- MFE uses non-executable daily highs as a diagnostic only.
- No parameter search, Sharpe label, portfolio drawdown claim, or production configuration was
  added.
