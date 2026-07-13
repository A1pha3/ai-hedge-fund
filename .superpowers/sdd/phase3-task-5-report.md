# Phase 3 Task 5 Report — Research CLI and immutable report contract

## Status

Implemented a research-only CLI over the approved legacy cohort, paired replay, and
time-block statistics. It writes a deterministic JSON/Markdown report pair and permanently
identifies every result as shadow-only and ineligible for production. No production execution
path, legacy journal, price cache, or policy parameter was changed.

## Delivered

- `scripts/run_exit_shadow_research.py` reads the legacy backtest journal and a price-cache
  directory, then runs `build_legacy_cohort()`, `replay_paired()`, and
  `summarize_paired_results()` without duplicating their eligibility logic.
- The only configurable values are input/output paths, report `as_of`, bootstrap seed, and
  bootstrap draw count. Activation return and ATR multiple are imported fixed constants;
  policy-search arguments are rejected by the parser.
- JSON records deterministic SHA-256 input fingerprints, including a sorted per-file cache
  manifest; fixed policy and execution-cost identity; all cohort layer counts; paired
  denominator; cohort and replay exclusions; coverage and missing-group bias; common executable
  mask; paired/time-block statistics; and per-arm holding, exit-reason, tail, and MFE diagnostics.
- Journal and cache fingerprints are computed both before and after the analysis. If either
  source changes while the report is running, publication fails closed instead of attaching
  stale provenance to new statistics.
- Top-level `mode=legacy_sensitivity`, `shadow_only=true`, and
  `production_eligible=false` cannot be selected through CLI arguments. The same immutable gate
  remains present in the underlying statistics object.
- Markdown begins `Legacy sensitivity / shadow only`, repeats the non-production gate, and
  explicitly explains the retrospective six-month sample, paired-BTST-only scope, selected
  common executable mask, board-rule audit difference, and fixed-policy limitation.
- The report pair is staged and fsynced in the destination directory, then each artifact is
  published atomically without overwrite via hard links. Re-running identical content is
  idempotent. A same-ID file with mismatched content always raises an immutable-report conflict;
  an interrupted one-file publication can only be completed when the surviving content exactly
  matches. Identical concurrent completion is never rolled back.
- The CLI performs no network calls and writes only the requested report directory. It never
  writes the journal, price cache, runtime paper-trading directory, or other legacy outputs.

## TDD evidence

1. Required RED: focused test collection failed with
   `ModuleNotFoundError: scripts.run_exit_shadow_research` before the script existed.
2. Initial implementation reached the parser test but the real fixture failed closed with an
   empty paired mask. Structured cohort evidence identified `invalid_ohlc_bar`: the fixture had
   changed a prior close below its unchanged low. Correcting that source OHLC bar, without
   weakening production validation, produced GREEN.
3. Initial focused CLI contract: **4 passed**. It covered the permanent shadow-only gate and fixed
   parameters, required report fields and disclosures, rejection of policy-search arguments,
   same-ID mismatched-content refusal, preservation of both existing files, and identical-input
   idempotency.
4. Independent code review found four Important gaps. Four RED cycles covered a non-denominator
   unmatched return, partial-report recovery, source mutation during analysis, and missing
   day-9/next-open policy identity. A second review found two remaining edge cases; dedicated RED
   cycles then covered a paired holding-period exclusion with only one recorded line and an
   identical concurrent publisher completing the second artifact.
5. Final focused CLI contract: **9 passed**.
6. Research + offensive + focused CLI baseline: **745 passed**.

## Real-data read-only smoke

Ran the actual script entry point with default 10,000 bootstrap draws against the parent
workspace's `data/paper_trading_backtest/journal.jsonl` and 626-file `data/price_cache`, writing
only to a new `/tmp/exit-shadow-task5.*` directory. A complete SHA-256 manifest of both sources
was identical before and after the run.

- paired BTST denominator: **133**;
- reconstructable Task 2 paths: **94**;
- executable common mask: **79** (**59.3985%** of paired denominator);
- unique signal days: **36**;
- bootstrap draws: **10,000**;
- report mode: `legacy_sensitivity`;
- `shadow_only=true` and `production_eligible=false`.

These values match the independently established Phase 3 Task 4 real-data audit. The smoke did
not use `data/paper_trading/` and did not generate a repository report artifact.

## Verification

- `uv run pytest tests/scripts/test_run_exit_shadow_research.py -v` — **9 passed**.
- `uv run pytest tests/research/ tests/offensive/ tests/scripts/test_run_exit_shadow_research.py -v`
  — **745 passed**.
- `uv run python scripts/run_exit_shadow_research.py ... --as-of 20260713` against real read-only
  sources — exit 0; report contract and source-manifest equality checked.

## Limitations retained in every report

- This is selected, retrospective, six-month legacy sensitivity evidence, not forward shadow
  evidence and not a production-readiness gate.
- Coverage is materially below the paired denominator; common-mask selection and missing-group
  statistics remain adjacent to the paired result.
- MFE uses non-executable daily highs only as a diagnostic.
- No parameter search, Sharpe label, portfolio drawdown claim, or production configuration was
  added.
