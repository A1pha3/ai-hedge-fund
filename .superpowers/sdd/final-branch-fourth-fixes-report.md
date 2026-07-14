# Final branch fourth fix wave

## Findings closed

### Entry-date scoped plan creation capacity

`DailyActionService._create_capacity_safe_plans()` previously loaded every
planned row into `reserved`, even though the batch being created targets one
specific next-session `entry_date`. Portfolio and ticker reservation sums could
therefore be contaminated by future or overdue sessions.

The service now filters persisted reservations to
`plan.planned_entry_date == entry_date` before either portfolio or ticker
capacity is calculated. Plans created during the loop are appended to that same
session-scoped list, so candidates in one batch still accumulate against the
60% portfolio cap and 10% ticker cap.

Regression coverage proves:

- six future-session 10% plans do not block a current signal's next-session
  plan;
- one future reservation uses the same ticker as the current candidate, so the
  ticker-reservation path is also proven isolated;
- six reservations for the same target entry session still block a seventh and
  remain exactly 60%.

### Canonical legacy provenance

`PlanProvenance.validate()` returned early for any object labelled
`legacy_unverified`, allowing arbitrary fields such as
`authorization=btst_crisis` to be persisted even though the cap remained 10%.

Legacy provenance must now equal `PlanProvenance.legacy_unverified()` exactly:
all evidence and authorization fields are `None`, with only
`verification_status=legacy_unverified`. Caller-created legacy provenance with
`normal`, `btst_crisis`, or `btst_risk_off` authorization is rejected before
plan/event persistence. Migrated and default legacy rows continue to use the
canonical form and retain the 10% cap.

## Verification

- New focused regressions: `5 passed`.
- Required full branch coverage:
  `uv run pytest tests/offensive/ tests/utils/test_atomic_files.py tests/research/ tests/scripts/test_run_exit_shadow_research.py -q`
  — `883 passed in 15.87s`.
- Auto publication/manifest/cache refresh:
  `uv run pytest tests/test_main_auto_cache_refresh.py tests/screening/test_auto_pipeline_publication.py tests/screening/test_data_quality_manifest.py -q`
  — `185 passed in 0.84s`.
- `uv run python -m compileall -q src/screening/offensive/daily_action_service.py src/screening/offensive/ledger_repository.py` — passed.
- `git diff --check` — clean.

No policy constants, exit behavior, research statistics, or unrelated files
were changed in this wave.
