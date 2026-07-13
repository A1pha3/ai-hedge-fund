# Phase 2 Task 6 Report — Manifest-gated daily action and full-pool shadow rank

## Outcome

Implemented the run-bound admission gate for `--daily-action`. The production
dispatcher loads only `auto_screening_YYYYMMDD.json` for the exact signal date,
requires a healthy top-level payload and embedded manifest with matching
`run_id`, date, health, candidate-set fingerprint, and candidate domain, then
reconstructs frozen `RunManifest` / `TickerReadiness` objects. It re-fingerprints
the current price, fund-flow, and bound-industry cache content before passing
each candidate to the service.

Missing, stale, malformed, mismatched, or degraded canonicals fail closed for
new plans. A ticker absent from the exact Layer-A manifest, marked non-ready, or
whose current cache fingerprint differs is blocked individually. Existing entry
settlement, exit handling, open-position valuation, and display continue. The
v2 ledger remains the only persistence path, and OversoldBounce remains rejected
by `PlanCandidate`.

`--auto` now also emits a research-only `shadow_rank_status` and `shadow_rank`
computed over the full fused pool. The canonical Top-30 preselection and Top-N
recommendation path are unchanged. The shadow computation is all-or-nothing:
every ticker must have finite explicit composite dimensions and explicit T+5 /
T+10 expected-return and win-rate evidence, otherwise the status is
`insufficient`. Shadow rows contain no weights, trade ids, plan fields, or
execution labels.

## TDD evidence

Observed RED before implementation for the missing service manifest/fingerprint
interfaces, missing canonical loader, missing full-pool ranker, and missing auto
payload fields. Added coverage for:

- missing/degraded/date-mismatched/run-mismatched/fingerprint-missing manifests;
- per-ticker fingerprint mismatch and nonrecommended Layer-A blocked tickers;
- immutable in-memory mappings and strict serialized canonical round-trip;
- corrupt identity/health/candidate fingerprint and stale canonical rejection;
- deterministic ties, candidate 35 winning a 40-name full-pool challenger, and
  unchanged canonical order;
- insufficient explicit dimensions and absence of executable shadow fields;
- actual dispatcher integration with an injected healthy run-bound manifest.

## Verification (2026-07-13)

- Focused Task 6 tests: **20 passed**.
- Daily-action service + v2 integration focused set: **56 passed**.
- Required offensive and dispatcher/cache baseline:
  `uv run pytest tests/offensive/ tests/test_main_auto_cache_refresh.py -q` —
  **426 passed in 3.81s**.
- Auto publication, manifest, strict-as-of, investability, and e2e regression
  set completed with exit 0.
- Ruff passed on all touched task files with pre-existing repository `F401` and
  `F541` codes explicitly ignored; `py_compile` and `git diff --check` passed.

## Self-review and residual concerns

The service defaults to `enforce_manifest_gate=True`; only lifecycle-only unit
fixtures opt out explicitly. The production dispatcher never opts out. Shadow
rank is serialized separately and is not consumed by daily-action or the ledger.

The full-pool shadow calculation intentionally performs a second explicit
composite/expected-return pass. This costs additional auto runtime but avoids
sharing or mutating the canonical Top-30 ranking inputs. No unresolved
correctness concern remains within Task 6 scope.

## Review-hardening addendum (2026-07-13)

Follow-up review findings were fixed test-first:

- Canonical loading now anchors the reports directory and exact filename with
  descriptor-relative `O_NOFOLLOW | O_CLOEXEC` opens. The file also uses
  `O_NONBLOCK` so a FIFO cannot hang the command. `fstat` requires a regular
  file, and pre/post-read no-follow stats must match the held device/inode;
  symlinks, FIFOs, directories, other nonregular entries, and replacement
  identity races fail closed.
- A purported healthy manifest must contain a nonempty, exactly matching
  candidate tuple and ticker mapping. Empty serialized or in-memory domains are
  visibly rejected as unavailable/invalid.
- `shadow_rank_status="complete"` now requires the original `score_b` and every
  explicit composite/expected metric to be a finite JSON numeric value, never a
  string or boolean. Complete shadow rows therefore cannot serialize a null
  score caused by NaN/Inf.
- Candidate rejection is preserved as structured `TickerGateBlock` data:
  absent manifest row, validator block reasons, missing manifest/current
  fingerprint, and expected/current fingerprint mismatch. Rendering exposes
  those audit reasons and fingerprints without cache content.
- Run-level warnings accumulate deterministically instead of overwriting one
  another. `block_reason` remains a stable semicolon-joined compatibility view,
  while `block_reasons` retains the structured ordered tuple. A due-plan calendar
  warning and a missing manifest now both survive and render.

Fresh verification after hardening:

- Task 6 manifest/shadow tests: **38 passed**.
- Task 6 + service + dispatcher integration: **79 passed**; dispatcher-focused
  suite: **52 passed**.
- Required offensive/cache baseline: **435 passed in 3.43s**.
- Broader investability/publication/manifest/as-of/e2e regression set completed
  with exit 0; Ruff, `py_compile`, and diff checks passed.
