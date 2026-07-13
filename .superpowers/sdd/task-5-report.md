# Task 5 report

## Status

Complete. `DailyActionService.run()` executes due-entry settlement, due-exit settlement,
mark-to-market, open-position evaluation, and capacity-safe planning in the fixed order.

## TDD evidence

- RED (service): `uv run pytest tests/offensive/test_daily_action_service.py -v` collected
  zero tests and failed with `ModuleNotFoundError: ...daily_action_service`.
- RED (repository repair): `uv run pytest tests/offensive/test_ledger_repository.py -q`
  produced 3 expected failures for missing `planned_trades`, `skip_plan`, and
  `latest_valuation` (21 passed).
- Regression RED: removing unknown-queue reservation made
  `test_unknown_higher_priority_entry_keeps_its_capacity_reserved` fail because the
  seventh plan incorrectly became OPEN; restoring the reservation made it pass.
- GREEN: `uv run pytest tests/offensive/test_daily_action_service.py -v` — 7 passed.
- Baseline: `uv run pytest tests/offensive/ tests/test_main_auto_cache_refresh.py -q`
  — 359 passed in 3.52s.
- Quality: focused Ruff check passed, all four changed files are Ruff-formatted,
  `git diff --check` passed, and changed production modules compiled successfully.

## Files and behavior

- `src/screening/offensive/daily_action_service.py`: v2 orchestration, 100-share lots,
  fee-aware cash sizing, tri-state fills, MTM/peak/drawdown, session-9 exit arming,
  session-10 execution, pending exposure reservation, 10% normal/12% hard/60%
  portfolio caps, simulation labels, and calendar-unavailable blocking of new plans only.
- `tests/offensive/test_daily_action_service.py`: six required scenarios plus unknown-entry
  reservation coverage; uses in-memory SQLite, fixed 12-session calendar, fixed prices.
- `src/screening/offensive/ledger_repository.py` and its tests: authorized narrow repair
  adding deterministic ledger-scoped planned queries, atomic idempotent PLAN_SKIPPED,
  and ledger-scoped latest valuation reads. This deviates from the brief's original
  two-file list because service-to-raw-SQL coupling was explicitly rejected.

## Self-review and concerns

- Confirmed no access to either legacy paper-trading artifact directory.
- Unknown queues retain pending state and are retryable; unknown pending entries reserve
  priority capacity. Valuation precedes new planning, so capacity never grows from stale NAV.
- The frozen calendar required class-level monkeypatching in the unavailable-calendar test.
- No unresolved correctness concern within Task 5 scope; scanner/CLI integration remains a
  later task, and OversoldBounce stays outside this service boundary.

## Blocking-finding repair (2026-07-13)

- RED: focused collection failed because `RegimeAuthorization` was absent; repository
  regressions also specified missing creation-status and position-mark APIs. During GREEN,
  the stale-mark regression initially failed (`60000 != 54000`), exposing an incorrect test
  expectation for five manually seeded 1,000-share positions; the production mark was right.
- GREEN: `uv run pytest tests/offensive/test_daily_action_service.py
  tests/offensive/test_ledger_repository.py -v` — **46 passed in 1.13s**.
- Baseline: `uv run pytest tests/offensive/ tests/test_main_auto_cache_refresh.py -q`
  — **374 passed in 4.20s**.
- Quality: focused Ruff check, Ruff format check for all changed files, compileall, and
  `git diff --check` passed.
- Capacity now uses one current-NAV snapshot and rechecks after each fill; a drawdown
  regression proves open plus reserved exposure remains at or below 60%.
- Last-known per-ticker marks are ledger-scoped and persisted; missing closes retain the
  profitable prior mark, disclose stale tickers, and cannot invent plan headroom.
- Ticker exposure aggregates OPEN/EXIT_PENDING/PLANNED; candidates are deterministically
  deduplicated. Normal authorization caps at 10%; explicit BTST crisis/risk-off authorization
  alone permits up to 12%.
- Candidate construction rejects non-finite/non-positive values, forged authorization,
  OversoldBounce, and unknown setups. Render labels come from persisted lifecycle fields,
  with `pending` used when no execution/fill source exists.
- `create_plan_if_absent` makes same-day reruns omit `new_plans` and retain one event.
- Concern: additive `position_marks` uses schema version 1 intentionally so existing v1
  ledgers acquire the backward-compatible table through `CREATE TABLE IF NOT EXISTS`.
