# Task 5 Recovery Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `--auto` publication restart-safe, run-bound to the exact Layer-A candidate set, and exact-replacement safe for tracking history.

**Architecture:** The compute payload carries direct Layer-A evidence from the same call that produced scores; the pipeline finalizes immutable `AutoInputs` only after compute and binds that evidence to `run_id`. Healthy publication uses a durable pending state machine (`prepared → tracked → canonical → remove`) whose checksum-verified recovery runs under the existing outer flock before any new computation. Tracking is an atomic exact replacement for the run date and preserves labels only for identical recommendation identity.

**Tech Stack:** Python 3.13, pytest, dataclasses, flock, SHA-256, durable atomic JSON helpers.

## Global Constraints

- Use strict RED → GREEN TDD for every behavior change.
- Reconciliation runs before a new computation while the existing auto flock is held.
- Degraded/fatal runs produce no downstream side effects and never replace canonical.
- `src/screening/auto_pipeline.py` remains the only canonical writer.

---

### Task 1: Run-bound Layer-A input evidence

**Files:**
- Modify: `src/main.py`
- Modify: `src/screening/auto_pipeline.py`
- Test: `tests/screening/test_auto_pipeline_publication.py`

- [x] Add failing tests proving a same-run non-price-cache candidate is in the manifest, stale pre-existing snapshots cannot substitute, and the first run does not self-degrade.
- [x] Run focused tests and confirm failures arise from the price-cache/precompute proxy.
- [x] Add direct candidate evidence to the compute payload, validate the exact-date persisted snapshot against it, finalize immutable inputs after compute, and bind ticker-set fingerprint/trade-date/run-id into manifest publication.
- [x] Run focused tests to GREEN.

### Task 2: Exact, durable tracking replacement

**Files:**
- Modify: `src/screening/recommendation_tracker.py`
- Test: `tests/screening/test_tracking_from_payload.py`
- Test: `tests/test_recommendation_tracker.py`

- [x] Add failing tests for orphan removal, exact score/model replacement, `source_run_id`, preservation of other dates, conditional label preservation, file mode preservation, directory durability, and temp cleanup.
- [x] Run tests and confirm append/idempotent logic and non-durable save are the causes.
- [x] Replace same-date records from the exact payload, preserve realized labels only when recommendation identity matches, and save with `atomic_write_json` under the existing file flock.
- [x] Run tracker tests to GREEN.

### Task 3: Restart-safe publication state machine

**Files:**
- Modify: `src/screening/auto_pipeline.py`
- Modify: `src/main.py`
- Test: `tests/screening/test_auto_pipeline_publication.py`
- Test: `tests/test_main_auto_cache_refresh.py`

- [x] Add injected-crash tests after prepared persistence, tracking, tracked persistence, canonical replacement, canonical-phase persistence, and before unlink; restart each and assert exact same run/payload is resumed before any fresh compute.
- [x] Confirm current implementation creates a new run and leaves pending state unreconciled.
- [x] Persist schema/version, payload and input fingerprints, checksum and phase; reconcile checksum-valid pending files idempotently before preparation; persist every phase with fsync and surface recovery diagnostics.
- [x] Ensure `run_auto_screening` invokes recovery while holding the outer flock and before progress/new work.
- [x] Run publication/recovery/call-site tests to GREEN.

### Task 4: Strict fail-closed quality matrix

**Files:**
- Modify: `src/screening/auto_pipeline.py`
- Test: `tests/screening/test_auto_pipeline_publication.py`

- [x] Add matrix tests for truthy non-bool manifests, absent/bool/wrong provider failures, unsupported/missing cache status, and all real partial/missing counters.
- [x] Confirm current defaults and coercions fail open.
- [x] Require `manifest.is_healthy is True`, explicit evidence fields, exact supported success status, and exact integer-zero required counters.
- [x] Run quality tests to GREEN.

### Task 5: Regression verification and handoff

**Files:**
- Modify: `.superpowers/sdd/phase2-task-5-report.md`

- [x] Run publication/recovery/tracker/cache/call-site suites plus offensive baseline.
- [x] Run Ruff, py_compile, `git diff --check`, and canonical-writer search.
- [x] Append RED evidence, state-machine invariants, exact results, and remaining concerns to the Task 5 report.
- [x] Commit with an intentional Task 5 hardening message and report commit SHA.
