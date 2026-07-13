# Phase 3 Task 1 Report — Pure fixed-parameter exit policy

## Status

**DONE** — implemented the immutable research/shadow-only policy with the
pre-registered constants `+10%`, `2.5 ATR`, and session-9 close planning for a
session-10 open exit. No production execution path imports or calls the policy.

## Scope and behavior

- Added frozen `ExitPolicyState`, `ExitObservation`, and `ExitDecision` values.
- Added pure `evaluate_shadow_exit()` evaluation with no I/O or side effects.
- The entry session records only its observed close and always returns HOLD;
  it cannot arm or request an exit.
- Later sessions arm when the observed close return reaches +10%.
- Armed state tracks only observed closes. Its trailing line is
  `max(previous_line, highest_close - 2.5 * current_ATR)` and cannot fall.
- A close strictly below the line requests the next trading session's open;
  equality holds. Session 9 always requests the session 10 open with reason
  `maximum_holding_session`.
- Missing, nonnumeric, nonfinite, or non-positive entry/close/ATR inputs and
  holding sessions below 1 are rejected. Inconsistent armed state is also
  rejected rather than guessed.
- There is no parameter argument, search, optimizer, environment switch, market
  data loader, high/low access, future-row access, or production execution hook.

## TDD evidence

1. Baseline before edits:
   `uv run pytest tests/offensive/ -q` — **420 passed in 3.65s**, exit 0.
2. Required RED:
   `uv run pytest tests/offensive/test_exit_policy.py -v` — collection failed
   with the expected `ModuleNotFoundError` for the not-yet-created
   `src.screening.offensive.exit_policy`, exit 2.
3. Initial GREEN:
   the focused file passed **20 tests in 0.47s**, exit 0.
4. Self-review RED:
   a newly added observed-close history case failed because activation-day line
   crossing was incorrectly delayed, **1 failed in 0.63s**, exit 1.
5. Self-review GREEN:
   the complete focused file passed **21 tests in 0.38s**, exit 0.
6. Full offensive regression:
   `uv run pytest tests/offensive/ -q` — **441 passed in 3.25s**, exit 0.
7. Static and whitespace checks:
   `uv run ruff check src/screening/offensive/exit_policy.py tests/offensive/test_exit_policy.py`
   and `git diff --check` — both exit 0.

## Self-review

The review checked the implementation line by line against the brief and the
phase-three design. The only issue found was an extra activation-day delay when
an earlier observed close made the newly created line exceed the current close.
A dedicated failing test reproduced it, and the evaluator now correctly plans
the next-session open without violating the entry-session prohibition.

An `rg` audit found no `exit_policy` import or `evaluate_shadow_exit` call in
any other production source file. Production exit behavior is therefore
unchanged by this task.

## Concerns

None blocking. This task intentionally provides only pure policy logic. Later
phase-three tasks must preserve the shadow-only boundary when wiring replay and
display code, and must supply trading-session observations rather than infer
sessions from calendar-day arithmetic.

## Review follow-up

Task 1 review findings were resolved in a second strict TDD cycle:

- Review baseline: `uv run pytest tests/offensive/ -q` — **441 passed in
  3.28s**, exit 0.
- RED: expanded focused suite — **10 failed, 27 passed in 0.80s**. Failures
  demonstrated entry-session armed-state normalization, absent `trade_date`
  naming, non-positive/nonfinite exit lines, line/peak ordering violations, and
  future `armed_at` acceptance.
- A separate date-type RED demonstrated that a `datetime` armed value leaked a
  `TypeError` instead of a controlled `ValueError` — **1 failed in 0.46s**.
- Final GREEN: focused policy suite — **38 passed in 0.38s**, exit 0.
- Final full offensive regression — **458 passed in 3.24s**, exit 0.
- Ruff and `git diff --check` both passed.

The policy now rejects an armed state on holding session 1 rather than silently
disarming it. Armed state requires pure `date` chronology, finite positive
`highest_close` and `exit_line`, a line strictly below the peak, and
`armed_at <= observation.trade_date`. Newly armed states are also prevented
from emitting a non-positive line. Session 9 retains precedence over an
otherwise simultaneous trailing-line reason.

Neither `ExitPolicyState` nor `ExitObservation` carries an entry-date field, so
an `armed_at >= entry_date` comparison is not expressible in the Task 1 API.
The evaluator does not invent or infer an entry date from calendar arithmetic;
the existing holding-session constraint remains the available entry boundary.

## Second review follow-up

The second Task 1 review was resolved with another test-first cycle:

- Review baseline: complete offensive suite — **458 passed in 3.71s**.
- RED: focused policy suite — **6 failed, 40 passed in 0.46s**. The failures
  proved that session 9/10 attempted activation before forced exit, an armed
  session-9 observation moved its trailing line, decimal +10% could miss the
  exact boundary, and an armed peak below activation was accepted.
- GREEN: focused policy suite — **46 passed in 0.76s**.
- Full offensive regression — **466 passed in 3.25s**.
- Ruff, `git diff --check`, and the no-production-import audit passed.

For valid inputs, evaluation now validates the incoming state first, records
the observed close in `highest_close`, and handles every holding session at or
above 9 before any activation or trailing-line construction. The forced result
keeps the previous armed/line fields and only advances the observed peak. An
invalid incoming armed state is still rejected before the forced decision.

Armed state now also requires `highest_close` to meet the fixed +10% activation
threshold. The exact threshold is shared with ordinary activation through a
single `Decimal(str(...))` comparison; no tolerance, tuning value, or search
parameter was added. Tests cover a just-below peak, `10.0 -> 11.0`, and the
floating-sensitive decimal boundary `0.1 -> 0.11`.
