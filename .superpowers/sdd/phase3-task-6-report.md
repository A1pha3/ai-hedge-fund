# Phase 3 Task 6 Report — Live exit challenger shadow display

## Outcome

`--daily-action` now displays the fixed exit challenger for each ledger OPEN position as
read-only `SHADOW ONLY` evidence. The view exposes `shadow_exit_line`,
`shadow_would_exit_next_open`, and `shadow_reason`, while the operator text permanently says
`不改变默认退出` and that the result does not trigger trades, sizing, or portfolio caps.

## Implementation

- `DailyActionService.run(..., shadow_prices=...)` accepts either a cached-bar
  provider, a keyed bar mapping, a per-ticker mapping/DataFrame, or a direct price-history
  DataFrame. The real dispatcher supplies a read-once, local-only complete CSV history loader;
  callers without one fall back to the existing read-only bar provider.
- Each OPEN trade is reconstructed only through `as_of`, using the full available contiguous
  ticker history rather than an entry-relative slice. The evaluator requires 14 prior bars so
  the 14 true ranges have real prior-close context, calls the shared causal Wilder ATR(14) on
  each full prefix, then feeds the observation into the fixed `exit_policy` state machine.
- Missing calendar coverage, entry price, OHLC path, or ATR is visible as
  `shadow_reason=insufficient_data`, with no inferred exit.
- The shadow projection is created after production entry settlement, exit settlement,
  mark-to-market, default session-9 exit evaluation, manifest admission, and capacity planning.
  It therefore cannot influence production transitions, exits, cash, plan creation, ticker
  caps, or portfolio caps.
- No environment variable, command-line switch, policy parameter, persistence method, or
  promotion path was added.
- Duplicate normalized civil dates, malformed/out-of-order paths, invalid OHLC, gaps, and
  insufficient prior-close context fail closed. The production cached-bar adapter also rejects
  exact and timestamp-normalized duplicate dates instead of choosing a row.
- Every history adapter establishes the causal prefix before validating market data. Direct and
  nested mappings classify dates first and discard known-future values without touching them.
  DataFrame and local-loader inputs require chronological source order, but stop at the first
  known date after `as_of`; invalid OHLC and malformed dates in that suffix cannot change the
  prefix result. A malformed date before that boundary remains fail-closed because it cannot be
  proven future.
- Each OPEN trade has its own ordinary-`Exception` boundary after production orchestration.
  Provider, parser, ATR, and policy failures become a visible `insufficient_data` row; Python
  `BaseException` subclasses are deliberately not swallowed. EXIT_PENDING trades are omitted.

## TDD evidence

The first focused run failed all five original tests because `DailyActionService.run` did not
accept `shadow_prices`. After the minimal implementation, the focused contract passed. A sixth
RED test then proved the project-standard price-history DataFrame was initially treated as
missing; the read-only adapter made it GREEN.

The findings-hardening cycle was also RED first: provider/parser/policy exceptions escaped the
command, entry-relative ATR disagreed with a hand-calculated/research-normalized Wilder replay,
session-9 EXIT_PENDING remained in the shadow list, the CSV provider selected a duplicate row,
and the complete-history constructor seam was absent. Each failure was observed before its
corresponding implementation change.

The focused suite asserts:

- a rising-then-reversing causal path requests a next-open shadow exit;
- future observations after `as_of` are ignored;
- missing path/ATR data is explicitly visible;
- repeated runs return identical shadow results;
- canonical trade-row and event-row bytes, trade state, cash, exit-event counts, and production
  exit plans are unchanged by a shadow trigger;
- two identically seeded ledgers produce byte-identical rows in `ledger_meta`, `trades`,
  `trade_events`, `daily_valuations`, and `position_marks`, plus identical cash, valuation,
  plans, exits, caps, exposures, and non-shadow view fields under triggering versus insufficient
  shadow inputs, including repeated runs;
- hand-calculated Wilder RMA, shared `compute_atr`, and research-normalized full prefixes agree,
  including a prior-close gap and future-prefix invariance;
- malformed provider/parser/ATR/policy inputs are isolated per trade, while `KeyboardInterrupt`
  propagates;
- direct mappings, nested mappings, DataFrames, and the local CSV-history loader return an
  identical shadow result when invalid future OHLC or a malformed post-boundary suffix is added;
  malformed pre-boundary dates still return `insufficient_data`;
- the exact `render_daily_action_v2` function used by the dispatcher labels the section
  `SHADOW ONLY` and `不改变默认退出`.

## Verification

- Focused shadow + dispatcher integration: **41 passed**.
- Daily-action service/v2/manifest/shadow regression: **86 passed**.
- Full offensive baseline: **496 passed**.
- Main auto-cache refresh regression: **15 passed**.
- Ruff check on the new service/test surface: clean.
- Ruff check on `daily_action.py` with its pre-existing `F401`/`F541` findings excluded: clean.
- `git diff --check`: clean.

The repository-wide `daily_action.py` format check still reports that the pre-existing file
would be reformatted; this task intentionally did not mechanically rewrite unrelated legacy
content.
