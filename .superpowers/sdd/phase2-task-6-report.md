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
