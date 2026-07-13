# Fixed-Parameter Exit Shadow Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement one pre-registered T+10 exit challenger and produce an honest legacy sensitivity report without selecting parameters or changing production exits.

**Architecture:** A pure exit-policy state machine is shared by live shadow evaluation and the research replay. The research path builds an explicit common cohort, audits missingness and detector-version mismatch, then reports block-aware sensitivity statistics with a permanent `shadow_only` gate.

**Tech Stack:** Python 3.13, pandas, numpy, stdlib statistics/random, pytest, v2 ledger from phase one.

## Global Constraints

- Run only after the ledger and auto-data-integrity plans are complete.
- Fixed configuration: activation return +10%, ATR multiple 2.5, force-exit planned session 9 and executed session 10 open.
- No grid, optimizer, best-parameter selector, or production feature flag may exist in this phase.
- Legacy backtest data is labelled sensitivity-only and never pooled with current setup-version data.
- Baseline and challenger use the same eligibility mask and execution-cost configuration.
- Any shadow result leaves the production exit policy unchanged.

---

## File Structure

- Create `src/screening/offensive/exit_policy.py`: pure immutable shadow policy.
- Create `src/research/exit_shadow_research.py`: cohort, coverage, replay, block resampling, report model.
- Create `scripts/run_exit_shadow_research.py`: CLI that writes JSON and Markdown reports.
- Modify `src/screening/offensive/daily_action_service.py`: compute and display shadow recommendation without executing it.
- Add tests in `tests/offensive/test_exit_policy.py`, `tests/research/test_exit_shadow_research.py`, and `tests/scripts/test_run_exit_shadow_research.py`.

### Task 1: Pure fixed-parameter exit policy

**Files:**
- Create: `src/screening/offensive/exit_policy.py`
- Create: `tests/offensive/test_exit_policy.py`

**Interfaces:**
- Produces: `ExitPolicyState`, `ExitObservation`, `ExitDecision`, `evaluate_shadow_exit()`.

- [ ] **Step 1: Write failing policy tests**

```python
from datetime import date

from src.screening.offensive.exit_policy import (
    ExitObservation,
    ExitPolicyState,
    evaluate_shadow_exit,
)


def test_policy_arms_at_ten_percent_close_return() -> None:
    state = ExitPolicyState.unarmed(entry_price=10.0)
    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 14), holding_session=2, close=11.0, atr=0.4),
    )
    assert decision.state.armed_at == date(2026, 7, 14)
    assert decision.should_exit_next_open is False


def test_exit_line_never_moves_down_when_atr_expands() -> None:
    state = ExitPolicyState(entry_price=10.0, armed_at=date(2026, 7, 14), highest_close=12.0, exit_line=11.0)
    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 15), holding_session=3, close=12.1, atr=1.0),
    )
    assert decision.state.exit_line == 11.0


def test_close_below_line_requests_next_open_exit() -> None:
    state = ExitPolicyState(entry_price=10.0, armed_at=date(2026, 7, 14), highest_close=12.0, exit_line=11.0)
    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 15), holding_session=3, close=10.9, atr=0.4),
    )
    assert decision.should_exit_next_open is True
    assert decision.reason == "close_below_trailing_line"


def test_session_nine_forces_session_ten_open_plan() -> None:
    state = ExitPolicyState.unarmed(entry_price=10.0)
    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 23), holding_session=9, close=10.2, atr=0.3),
    )
    assert decision.should_exit_next_open is True
    assert decision.reason == "maximum_holding_session"
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/test_exit_policy.py -v`

Expected: module import fails.

- [ ] **Step 3: Implement the immutable policy**

Use module constants `ACTIVATION_RETURN = 0.10`, `ATR_MULTIPLE = 2.5`, `PLAN_EXIT_SESSION = 9`. Reject non-positive entry/close/ATR and holding sessions below 1. On the entry session return HOLD without arming an exit. Update `highest_close` with observed closes only; never inspect high/low or future rows.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/offensive/test_exit_policy.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/exit_policy.py tests/offensive/test_exit_policy.py
git commit -m "feat: add fixed shadow exit policy"
```

### Task 2: Legacy cohort builder and mismatch audit

**Files:**
- Create: `src/research/exit_shadow_research.py`
- Create: `tests/research/test_exit_shadow_research.py`

**Interfaces:**
- Produces: `LegacyTradePath`, `CoverageAudit`, `build_legacy_cohort()`, `audit_coverage()`.

- [ ] **Step 1: Write failing cohort tests**

```python
from pathlib import Path

import pandas as pd

from src.research.exit_shadow_research import audit_coverage, build_legacy_cohort


def test_builder_uses_only_paired_btst_exits_and_common_complete_paths(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        '\n'.join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+5.00%"}',
                '{"date":"20260105","ticker":"000002","setup":"oversold_bounce","action":"BUY"}',
            )
        ),
        encoding="utf-8",
    )
    prices = {
        "000001": pd.DataFrame(
            [{"date": f"2026-01-{day:02d}", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2} for day in range(5, 20)]
        )
    }
    cohort = build_legacy_cohort(journal, price_loader=prices.get)
    assert [trade.ticker for trade in cohort.included] == ["000001"]
    assert cohort.audit.total_paired_btst == 1


def test_coverage_audit_blocks_promotion_when_missing_group_differs() -> None:
    audit = audit_coverage(
        covered_legacy_returns=[0.10, 0.12, 0.08],
        missing_legacy_returns=[0.01, 0.02],
        total=5,
    )
    assert audit.coverage == 0.60
    assert audit.selection_bias_warning is True
    assert audit.production_eligible is False
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/research/test_exit_shadow_research.py -v`

Expected: research module is missing.

- [ ] **Step 3: Implement explicit cohort layers**

Build and count these layers separately: all journal rows, paired BTST natural keys, ticker price file present, signal date present, complete entry-to-session-10 window, execution-proxy eligible. Save excluded keys and exact reasons. Compute current-board-rule mismatch as a separate boolean; do not silently remove mismatches from the legacy sensitivity cohort.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/research/test_exit_shadow_research.py -v`

Expected: cohort tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/exit_shadow_research.py tests/research/test_exit_shadow_research.py
git commit -m "feat: audit legacy exit research cohort"
```

### Task 3: Common-mask replay and executable baseline

**Files:**
- Modify: `src/research/exit_shadow_research.py`
- Modify: `tests/research/test_exit_shadow_research.py`

**Interfaces:**
- Produces: `replay_fixed_baseline()`, `replay_shadow_challenger()`, `PairedExitResult`.

- [ ] **Step 1: Add failing replay tests**

```python
def test_baseline_and_challenger_share_exact_trade_keys(complete_trade_paths):
    result = replay_paired(complete_trade_paths, costs=FIXED_TEST_COSTS)
    assert [row.trade_id for row in result.baseline] == [row.trade_id for row in result.challenger]


def test_baseline_exits_session_ten_open_not_close(single_trade_path):
    result = replay_fixed_baseline(single_trade_path, costs=FIXED_TEST_COSTS)
    assert result.exit_date == single_trade_path.sessions[9].date
    assert result.raw_exit_price == single_trade_path.sessions[9].open


def test_challenger_uses_only_prior_close_information(single_trade_path):
    original = replay_shadow_challenger(single_trade_path, costs=FIXED_TEST_COSTS)
    mutated = single_trade_path.with_future_rows_changed(after=original.exit_trigger_date)
    assert replay_shadow_challenger(mutated, costs=FIXED_TEST_COSTS).exit_trigger_date == original.exit_trigger_date
```

Define `FIXED_TEST_COSTS` and fixtures in the same test module with deterministic 12-session OHLC rows.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/research/test_exit_shadow_research.py -v`

Expected: replay functions are missing.

- [ ] **Step 3: Implement replay through shared production functions**

Use `evaluate_shadow_exit()` and the v2 `apply_execution_costs()` function. Entry is session 1 open; no exit is legal on session 1. A close trigger schedules the next session open. Session 9 always schedules session 10 open. Queue-unknown or suspended exit is deferred and labelled; both baseline and challenger use the same common eligibility mask.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/research/test_exit_shadow_research.py -v`

Expected: all replay tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/exit_shadow_research.py tests/research/test_exit_shadow_research.py
git commit -m "feat: replay fixed exit challenger"
```

### Task 4: Time-block sensitivity statistics

**Files:**
- Modify: `src/research/exit_shadow_research.py`
- Modify: `tests/research/test_exit_shadow_research.py`

**Interfaces:**
- Produces: `moving_block_mean_difference(rows, block_sessions=10, draws=10_000, seed=0)`.

- [ ] **Step 1: Add failing deterministic block tests**

```python
def test_block_resampling_is_deterministic(paired_rows):
    first = moving_block_mean_difference(paired_rows, block_sessions=10, draws=1_000, seed=7)
    second = moving_block_mean_difference(paired_rows, block_sessions=10, draws=1_000, seed=7)
    assert first == second


def test_statistics_count_signal_days_and_nonoverlapping_blocks(paired_rows):
    stats = summarize_paired_results(paired_rows)
    assert stats.trade_count == len(paired_rows)
    assert stats.signal_day_count == len({row.signal_date for row in paired_rows})
    assert stats.nonoverlapping_window_count <= stats.signal_day_count


def test_report_is_never_production_eligible(paired_rows):
    stats = summarize_paired_results(paired_rows)
    assert stats.shadow_only is True
    assert stats.production_eligible is False
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/research/test_exit_shadow_research.py -v`

Expected: block-statistics functions are missing.

- [ ] **Step 3: Implement block-aware summaries**

Aggregate paired differences by signal date, construct consecutive trading-date blocks spanning at least 10 sessions, sample blocks with replacement, and report the distribution of the mean paired difference. Also report trade count, unique signal days, greedy non-overlapping windows, mean, median, worst decile, coverage, and missing-group legacy mean. Do not label `mean/std` as Sharpe.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/research/test_exit_shadow_research.py -v`

Expected: all statistical tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/exit_shadow_research.py tests/research/test_exit_shadow_research.py
git commit -m "feat: add block-aware exit sensitivity"
```

### Task 5: Research CLI and immutable report contract

**Files:**
- Create: `scripts/run_exit_shadow_research.py`
- Create: `tests/scripts/test_run_exit_shadow_research.py`

**Interfaces:**
- CLI reads legacy journal and price cache, writes `data/reports/exit_shadow/exit_shadow_YYYYMMDD.{json,md}`.

- [ ] **Step 1: Write failing CLI contract test**

```python
import json
from pathlib import Path

from scripts.run_exit_shadow_research import main


def test_cli_report_cannot_claim_production_readiness(tmp_path: Path, legacy_fixture_paths) -> None:
    output = tmp_path / "reports"
    rc = main(
        [
            "--journal", str(legacy_fixture_paths.journal),
            "--price-cache", str(legacy_fixture_paths.price_cache),
            "--output-dir", str(output),
            "--as-of", "20260713",
        ]
    )
    assert rc == 0
    payload = json.loads((output / "exit_shadow_20260713.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "legacy_sensitivity"
    assert payload["shadow_only"] is True
    assert payload["production_eligible"] is False
    assert payload["parameters"] == {"activation_return": 0.10, "atr_multiple": 2.5}
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/scripts/test_run_exit_shadow_research.py -v`

Expected: script import fails.

- [ ] **Step 3: Implement CLI with fixed arguments**

Accept only paths, as-of date, and bootstrap seed/draw count. Do not expose activation or ATR parameters as CLI arguments. JSON includes fingerprints, counts, exclusions, fixed parameters, paired summaries, and block sensitivity. Markdown begins with “Legacy sensitivity / shadow only” and lists why the cohort differs from current production.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/scripts/test_run_exit_shadow_research.py -v`

Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_exit_shadow_research.py tests/scripts/test_run_exit_shadow_research.py
git commit -m "feat: report exit shadow sensitivity"
```

### Task 6: Live shadow display with no execution side effect

**Files:**
- Modify: `src/screening/offensive/daily_action_service.py`
- Modify: `src/screening/offensive/daily_action.py`
- Create: `tests/offensive/test_exit_shadow_integration.py`

**Interfaces:**
- Open-position view adds `shadow_exit_line`, `shadow_would_exit_next_open`, and `shadow_reason`.
- No ledger state transition is caused by the shadow result.

- [ ] **Step 1: Write failing no-side-effect test**

```python
def test_shadow_exit_never_changes_trade_state(service, open_trade, rising_then_reversing_prices):
    before = service.repository.get_trade(open_trade.trade_id)
    run = service.run(open_trade.entry_date, candidates=(), shadow_prices=rising_then_reversing_prices)
    after = service.repository.get_trade(open_trade.trade_id)
    assert before.state == after.state
    assert run.open_positions[0].shadow_would_exit_next_open is True
    assert service.repository.count_events(open_trade.trade_id, "EXIT_REQUESTED") == 0


def test_render_labels_shadow_as_non_executable_advice(service, open_trade, rising_then_reversing_prices):
    text = service.render(service.run(open_trade.entry_date, candidates=(), shadow_prices=rising_then_reversing_prices))
    assert "shadow" in text.lower()
    assert "不改变默认退出" in text
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/test_exit_shadow_integration.py -v`

Expected: shadow view fields are missing.

- [ ] **Step 3: Add read-only shadow evaluation**

Evaluate the pure policy from reconstructed closes and stored entry price. Return view fields only; do not call any repository mutation. If ATR or path data is missing, show `shadow_reason="insufficient_data"`.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/offensive/test_exit_shadow_integration.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/daily_action_service.py src/screening/offensive/daily_action.py tests/offensive/test_exit_shadow_integration.py
git commit -m "feat: display exit challenger in shadow"
```

### Task 7: Phase-three verification

**Files:**
- No planned production changes.

- [ ] **Step 1: Prove there is no parameter-selection path**

Run: `rg -n 'grid|optimi[sz]e|best_param|activation.*arg|atr_multiple.*arg' src/research/exit_shadow_research.py scripts/run_exit_shadow_research.py`

Expected: no matches.

- [ ] **Step 2: Run focused suites**

```bash
uv run pytest tests/offensive/test_exit_policy.py tests/offensive/test_exit_shadow_integration.py -v
uv run pytest tests/research/test_exit_shadow_research.py tests/scripts/test_run_exit_shadow_research.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Run required regressions**

```bash
uv run pytest tests/offensive/ -v
uv run pytest tests/test_main_auto_cache_refresh.py -v
uv run pytest tests/offensive/test_daily_action_cache_refresh.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Generate the real legacy sensitivity artifact**

Run:

```bash
uv run python scripts/run_exit_shadow_research.py \
  --journal data/paper_trading_backtest/journal.jsonl \
  --price-cache data/price_cache \
  --output-dir data/reports/exit_shadow \
  --as-of 20260713
```

Expected: JSON and Markdown reports are generated, both state `shadow_only=true` / “shadow only”, and neither changes production configuration.
