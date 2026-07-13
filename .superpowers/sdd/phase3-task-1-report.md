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
