# Readiness Remediation A Report

## Scope

Production `--auto` now retains one exact `DailyActionRefreshResult`, waits for
the same-date Auto regime, builds immutable full-universe shared evidence, and
publishes Daily Action readiness from that same refresh object. Auto scoring
health remains independent. No setup, ranking, Kelly, exit, BSE, OB, or sizing
policy changed.

## RED

Command:

```bash
uv run pytest tests/offensive/test_auto_readiness_production.py -q
```

Observed before production changes: **8 failed**.

- refresh bridge still defaulted to `data/reports`;
- production shared-evidence builder was absent;
- invalid/unknown regimes had no production rejection path;
- default Auto dependencies did not retain the actual readiness publication;
- shared-evidence failures had no single completion path that guaranteed an
  attempt while preserving canonical.

The default orchestration test also captured the original symptom directly:
prepare-time publication emitted `shared_evidence_unavailable` before Auto had
computed the signal-date regime.

## GREEN implementation

- Made `reports_dir` mandatory in the Auto refresh bridge and passed the
  injected directory through panel backfill/health helpers.
- Deferred readiness publication until after Auto compute provides exact-date
  market regime evidence.
- Added a network-free repository evidence builder for exact frozen-universe
  security/ST, SW industry mapping, and exact-date industry return evidence.
- Added `SharedReadinessEvidence.as_of_date`; it is included in all shared
  fingerprints and must equal manifest `trade_date`.
- Restricted regime to `normal`, `risk_off`, or `crisis`; no fallback to
  `normal` remains in the readiness authorization chain.
- Converted every build/validation/publication failure into a unique attempt;
  canonical readiness is never replaced by a failed run.
- Captured the actual `DailyActionReadinessPublication` on `AutoRunResult` and
  serialized only its authoritative dynamic counts for CLI output.
- Removed price-refresh-counter inference from Daily Action readiness display.
  Default output uses clear Chinese `健康` / `未就绪` wording; raw reason codes
  are verbose-only.
- Added a real default-dependency orchestration test using the actual refresh
  bridge, actual shared builder, injected providers, and temporary paths. It
  proves a healthy canonical and preserves a ticker outside the Auto pool.

## Verification evidence

```text
uv run pytest tests/offensive/test_auto_readiness_production.py \
  tests/offensive/test_daily_readiness_v2_security.py -q
28 passed

uv run pytest tests/offensive/ -q
806 passed

uv run pytest tests/offensive/test_setup_data_contracts.py \
  tests/offensive/test_daily_action_readiness.py \
  tests/offensive/test_daily_readiness_v2_security.py \
  tests/offensive/test_daily_action_verified_snapshot.py \
  tests/offensive/test_daily_action_snapshot_scan.py \
  tests/offensive/test_daily_action_service_snapshot_gate.py \
  tests/offensive/test_daily_readiness_20260713_regression.py \
  tests/offensive/test_readiness_v2_migration.py \
  tests/offensive/test_auto_readiness_production.py \
  tests/test_main_auto_cache_refresh.py \
  tests/test_operator_output_domains.py \
  tests/screening/test_auto_pipeline_publication.py \
  tests/test_e2e_pipeline_smoke.py -q
233 passed
```

uv run pytest tests/test_main_auto_cache_refresh.py \
  tests/test_operator_output_domains.py \
  tests/screening/test_auto_pipeline_publication.py \
  tests/test_e2e_pipeline_smoke.py -q
126 passed

uv run ruff check <changed production/tests excluding main.py>
All checks passed

uv run ruff check --ignore F401 src/main.py
All checks passed (the five ignored TYPE_CHECKING F401 findings predate this task)

uv run python -m compileall -q <changed production modules>
exit 0

git diff --check
exit 0
