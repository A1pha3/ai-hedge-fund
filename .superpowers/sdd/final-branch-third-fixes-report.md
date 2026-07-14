# Final branch third fix wave

## Closed findings

### I1 — repository-owned settlement policy

- `LedgerRepository` now owns the synthetic execution-cost policy supplied at
  construction. `DailyActionService` refuses a different policy object/value.
- Public synthetic settlement accepts raw OHLC/limit/suspension evidence only;
  the repository runs `classify_open_fill` itself. Callers can no longer pass an
  `execution_status`, `lot_size`, portfolio/ticker caps, requested quantity,
  execution mode/source, explicit costs, or cost version.
- The private transaction fixes A-share lots at 100 shares and portfolio
  capacity at 60%. Verified synthetic plans require the repository cost version
  to equal the persisted provenance version.
- `fill_plan` is now exclusively a broker-confirmed manual/import path. It
  rejects PAPER/SYNTHETIC_OPEN, validates actual confirmed quantity/costs, keeps
  the same cash/cap transaction, and labels costs `externally_confirmed` only on
  that distinct path.

### I2 — caller-forged 12% authorization

The current canonical auto manifest contains no regime authorization evidence,
so there is no honest repository-verifiable path to distinguish a real crisis
claim from an API caller's string. The safe policy is therefore fail-closed:

- verified provenance accepts only `authorization=normal`;
- public/production create and fill cap every ticker at 10%;
- caller-created `btst_crisis`/`btst_risk_off` provenance is rejected;
- scanner crisis/risk-off requests are downgraded to 10% and the run exposes
  `regime_authorization_evidence_unavailable`;
- `AGENTS.md`, source comments, and `docs/feature-flags.md` now state that the
  12% exception is paused and `DAILY_ACTION_REGIME_SIZING` does not currently
  create actual extra allocation.

Threat model: this prevents an ordinary repository/service API caller from
forging the 12% exception. It does not claim cryptographic resistance after an
attacker gains arbitrary local source/database/report write access. Restoring
12% requires the canonical manifest to carry regime evidence that the
repository can recompute and bind at both admission and fill.

### I3 — cross-session priority contamination

Higher-priority and reservation queries are scoped to the current
`planned_entry_date`. Future plans and overdue plans cannot block or reserve
capacity for today's exact-date settlement. The service continues to process
all `planned_entry_date <= as_of` rows and atomically expires overdue rows.

### I4 — historical bundle authentication

Historical CLI analysis and reuse are now completely prohibited. Even a
self-consistent previously committed bundle returns a non-zero CLI result when
`as_of` is not the current civil date. The unused ordinary-hash verifier was
removed because, without an authenticated trust root, it cannot prove that a
local bundle was not forged or bind it safely to a new invocation.

### M1 — cutoff file semantics

The audit now distinguishes:

- `future_price_affected_files`: every file containing at least one future row;
- `future_only_price_files`: files with no row remaining after the cutoff;
- `future_price_tickers`: tickers whose files contain future rows.

JSON and Markdown disclose all row/file/ticker counters. The regression fixture
contains both a mixed historical+future file and a future-only file.

## Verification

- Focused expanded set (ledger, service, manifest gate, v2 integration, exit
  shadow, research CLI): `194 passed in 3.72s`.
- Required branch coverage:
  `uv run pytest tests/offensive/ tests/utils/test_atomic_files.py tests/research/ tests/scripts/test_run_exit_shadow_research.py -q`
  — `878 passed in 19.58s`.
- Auto publication/manifest/cache refresh:
  `uv run pytest tests/test_main_auto_cache_refresh.py tests/screening/test_auto_pipeline_publication.py tests/screening/test_data_quality_manifest.py -q`
  — `185 passed in 0.90s`.
- `uv run python -m compileall -q ...` — passed.
- `git diff --check` — clean.

## Remaining explicit constraint

The data supports crisis sizing statistically, but the software no longer
claims that evidence is operational authorization. Actual 12% sizing remains
disabled until canonical regime evidence is designed, published, and
repository-verifiable. OversoldBounce remains disabled; exit challenger policy
remains shadow-only.
