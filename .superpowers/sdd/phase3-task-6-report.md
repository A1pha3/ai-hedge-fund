# Phase 3 Task 6 Report — Live exit challenger shadow display

## Outcome

`--daily-action` now displays the fixed exit challenger for each ledger OPEN position as
read-only `SHADOW ONLY` evidence. The view exposes `shadow_exit_line`,
`shadow_would_exit_next_open`, and `shadow_reason`, while the operator text permanently says
`不改变默认退出` and that the result does not trigger trades, sizing, or portfolio caps.

## Implementation

- `DailyActionService.run(..., shadow_prices=...)` accepts either the production cached-bar
  provider, a keyed bar mapping, a per-ticker mapping/DataFrame, or a direct price-history
  DataFrame. Without an override it uses the existing read-only production price provider.
- Each OPEN trade is reconstructed only through `as_of`. The evaluator requires 13 prior
  sessions for the first causal Wilder ATR(14), then feeds each completed holding session into
  the already-fixed `exit_policy.evaluate_shadow_exit` state machine.
- Missing calendar coverage, entry price, OHLC path, or ATR is visible as
  `shadow_reason=insufficient_data`, with no inferred exit.
- The shadow projection is created after production entry settlement, exit settlement,
  mark-to-market, default session-9 exit evaluation, manifest admission, and capacity planning.
  It therefore cannot influence production transitions, exits, cash, plan creation, ticker
  caps, or portfolio caps.
- No environment variable, command-line switch, policy parameter, persistence method, or
  promotion path was added.

## TDD evidence

The first focused run failed all five original tests because `DailyActionService.run` did not
accept `shadow_prices`. After the minimal implementation, the focused contract passed. A sixth
RED test then proved the project-standard price-history DataFrame was initially treated as
missing; the read-only adapter made it GREEN.

The focused suite asserts:

- a rising-then-reversing causal path requests a next-open shadow exit;
- future observations after `as_of` are ignored;
- missing path/ATR data is explicitly visible;
- repeated runs return identical shadow results;
- canonical trade-row and event-row bytes, trade state, cash, exit-event counts, and production
  exit plans are unchanged by a shadow trigger;
- the exact `render_daily_action_v2` function used by the dispatcher labels the section
  `SHADOW ONLY` and `不改变默认退出`.

## Verification

- Focused shadow integration: **6 passed**.
- Daily-action service/v2/manifest/shadow regression: **70 passed**.
- Full offensive baseline: **476 passed**.
- Main auto-cache refresh regression: **15 passed**.
- Ruff check on the new service/test surface: clean.
- Ruff check on `daily_action.py` with its pre-existing `F401`/`F541` findings excluded: clean.
- `git diff --check`: clean.

The repository-wide `daily_action.py` format check still reports that the pre-existing file
would be reformatted; this task intentionally did not mechanically rewrite unrelated legacy
content.
