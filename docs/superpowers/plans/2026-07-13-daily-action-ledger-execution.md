# Daily Action Ledger and Execution Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ambiguous v1 paper journal path with a transactional v2 ledger that distinguishes plans, synthetic fills, confirmed fills, holdings, and executable exits.

**Architecture:** SQLite is the only v2 trading truth. Pure lifecycle and execution functions feed a repository that commits each transition atomically; `daily_action_service.py` orchestrates settlement, valuation, exits, and new plans while the existing scanner and renderer remain compatibility boundaries.

**Tech Stack:** Python 3.13, stdlib `sqlite3`, pandas, pytest, existing SSE calendar helpers.

## Global Constraints

- Freeze all files under `data/paper_trading/` and `data/paper_trading_backtest/`; tests must prove they remain unchanged.
- Normal per-stock cap is 10%, regime-adjusted hard cap is 12%, portfolio cap is 60%.
- Entry day is holding session 1; force-exit is planned after session 9 close and executed at session 10 open.
- Calendar, security-status, or limit-price uncertainty fails closed for new fills.
- Paper fills and broker-confirmed fills never share an unlabelled field or performance cohort.
- OversoldBounce remains disabled.
- Execute this plan in an isolated worktree because the current main worktree contains unrelated uncommitted changes.

---

## File Structure

- Create `src/screening/offensive/trade_lifecycle.py`: enums, immutable commands, deterministic identity, legal transition validation.
- Create `src/screening/offensive/ledger_repository.py`: SQLite schema and transactional repository.
- Create `src/screening/offensive/daily_action_service.py`: v2 daily orchestration and view models.
- Modify `src/screening/offensive/execution_adjuster.py`: tri-state fill proxy, T+1 enforcement, separated fees.
- Modify `src/screening/offensive/daily_action.py`: scanner returns plans; v2 service integration; 10%/12% caps; incomplete signals fail closed.
- Modify `src/cli/dispatcher.py`: instantiate the v2 service and render simulation labels.
- Test in `tests/offensive/test_trade_lifecycle.py`, `test_ledger_repository.py`, `test_execution_adjuster.py`, `test_daily_action_service.py`, and existing daily-action regressions.

### Task 1: Pure lifecycle identity and transition contract

**Files:**
- Create: `src/screening/offensive/trade_lifecycle.py`
- Create: `tests/offensive/test_trade_lifecycle.py`

**Interfaces:**
- Produces: `TradeState`, `ExecutionMode`, `FillSource`, `TradeIdentity`, `deterministic_trade_id()`, `assert_transition()`.

- [ ] **Step 1: Write the failing lifecycle tests**

```python
from datetime import date

import pytest

from src.screening.offensive.trade_lifecycle import (
    ExecutionMode,
    FillSource,
    TradeIdentity,
    TradeState,
    assert_transition,
    deterministic_trade_id,
)


def test_trade_id_is_deterministic_and_versioned() -> None:
    identity = TradeIdentity(
        ledger_id="paper-v2",
        setup="btst_breakout",
        setup_version="sha:abc123",
        ticker="300001",
        signal_date=date(2026, 7, 10),
        planned_entry_date=date(2026, 7, 13),
    )
    assert deterministic_trade_id(identity) == deterministic_trade_id(identity)
    assert deterministic_trade_id(identity) != deterministic_trade_id(
        identity.__class__(**{**identity.__dict__, "setup_version": "sha:def456"})
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (TradeState.PLANNED, TradeState.OPEN),
        (TradeState.PLANNED, TradeState.SKIPPED),
        (TradeState.OPEN, TradeState.EXIT_PENDING),
        (TradeState.EXIT_PENDING, TradeState.CLOSED),
    ],
)
def test_legal_transitions(before: TradeState, after: TradeState) -> None:
    assert_transition(before, after)


def test_open_cannot_jump_directly_to_closed() -> None:
    with pytest.raises(ValueError, match="illegal transition"):
        assert_transition(TradeState.OPEN, TradeState.CLOSED)


def test_fill_source_matches_execution_mode() -> None:
    assert FillSource.SYNTHETIC_OPEN.allowed_mode is ExecutionMode.PAPER
    assert FillSource.MANUAL_CONFIRMATION.allowed_mode is ExecutionMode.BROKER_CONFIRMED
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/test_trade_lifecycle.py -v`

Expected: collection fails because `trade_lifecycle` does not exist.

- [ ] **Step 3: Implement the minimal lifecycle module**

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class TradeState(StrEnum):
    PLANNED = "planned"
    OPEN = "open"
    EXIT_PENDING = "exit_pending"
    CLOSED = "closed"
    SKIPPED = "skipped"


class ExecutionMode(StrEnum):
    PAPER = "paper"
    BROKER_CONFIRMED = "broker_confirmed"


class FillSource(StrEnum):
    SYNTHETIC_OPEN = "synthetic_open"
    MANUAL_CONFIRMATION = "manual_confirmation"
    BROKER_IMPORT = "broker_import"

    @property
    def allowed_mode(self) -> ExecutionMode:
        if self is FillSource.SYNTHETIC_OPEN:
            return ExecutionMode.PAPER
        return ExecutionMode.BROKER_CONFIRMED


@dataclass(frozen=True)
class TradeIdentity:
    ledger_id: str
    setup: str
    setup_version: str
    ticker: str
    signal_date: date
    planned_entry_date: date


def deterministic_trade_id(identity: TradeIdentity) -> str:
    raw = "|".join(
        (
            identity.ledger_id,
            identity.setup,
            identity.setup_version,
            identity.ticker,
            identity.signal_date.isoformat(),
            identity.planned_entry_date.isoformat(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


_LEGAL = {
    TradeState.PLANNED: {TradeState.OPEN, TradeState.SKIPPED},
    TradeState.OPEN: {TradeState.EXIT_PENDING},
    TradeState.EXIT_PENDING: {TradeState.CLOSED},
    TradeState.CLOSED: set(),
    TradeState.SKIPPED: set(),
}


def assert_transition(before: TradeState, after: TradeState) -> None:
    if after not in _LEGAL[before]:
        raise ValueError(f"illegal transition: {before} -> {after}")
```

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/offensive/test_trade_lifecycle.py -v`

Expected: all lifecycle tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/trade_lifecycle.py tests/offensive/test_trade_lifecycle.py
git commit -m "feat: define auditable trade lifecycle"
```

### Task 2: Transactional SQLite ledger

**Files:**
- Create: `src/screening/offensive/ledger_repository.py`
- Create: `tests/offensive/test_ledger_repository.py`

**Interfaces:**
- Consumes: lifecycle enums and deterministic trade ids from Task 1.
- Produces: `LedgerRepository.initialize()`, `create_plan()`, `fill_plan()`, `mark_exit_pending()`, `defer_exit()`, `close_trade()`, `open_trades()`, `record_valuation()`.

- [ ] **Step 1: Write failing repository tests**

```python
from datetime import date
from pathlib import Path

import pytest

from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.trade_lifecycle import ExecutionMode, FillSource, TradeState


def test_duplicate_plan_is_idempotent(tmp_path: Path) -> None:
    repo = LedgerRepository(tmp_path / "ledger.sqlite3", ledger_id="test", initial_cash=100_000)
    repo.initialize()
    first = repo.create_plan("000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.10, 1)
    second = repo.create_plan("000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.10, 1)
    assert first.trade_id == second.trade_id
    assert repo.count_events(first.trade_id, "PLAN_CREATED") == 1


def test_fill_and_event_commit_together(tmp_path: Path) -> None:
    repo = LedgerRepository(tmp_path / "ledger.sqlite3", ledger_id="test", initial_cash=100_000)
    repo.initialize()
    trade = repo.create_plan("000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.10, 1)
    opened = repo.fill_plan(
        trade.trade_id,
        execution_mode=ExecutionMode.PAPER,
        fill_source=FillSource.SYNTHETIC_OPEN,
        entry_date=date(2026, 7, 13),
        raw_fill_price=10.0,
        quantity=1_000,
        commission=5.0,
        tax=0.0,
        slippage_cost=30.0,
    )
    assert opened.state is TradeState.OPEN
    assert repo.cash_balance() == pytest.approx(89_965.0)
    assert repo.count_events(trade.trade_id, "ENTRY_FILLED") == 1


def test_failed_transition_rolls_back_trade_and_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = LedgerRepository(tmp_path / "ledger.sqlite3", ledger_id="test", initial_cash=100_000)
    repo.initialize()
    trade = repo.create_plan("000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.10, 1)
    monkeypatch.setattr(repo, "_insert_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        repo.fill_plan(trade.trade_id, ExecutionMode.PAPER, FillSource.SYNTHETIC_OPEN, date(2026, 7, 13), 10.0, 1_000, 5.0, 0.0, 30.0)
    assert repo.get_trade(trade.trade_id).state is TradeState.PLANNED
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/test_ledger_repository.py -v`

Expected: import fails because the repository does not exist.

- [ ] **Step 3: Create the schema and repository**

Use this schema verbatim inside `LedgerRepository.initialize()`:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS ledger_meta (
  ledger_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL,
  initial_cash REAL NOT NULL CHECK(initial_cash > 0),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
  trade_id TEXT PRIMARY KEY,
  ledger_id TEXT NOT NULL REFERENCES ledger_meta(ledger_id),
  ticker TEXT NOT NULL,
  setup TEXT NOT NULL,
  setup_version TEXT NOT NULL,
  signal_date TEXT NOT NULL,
  planned_entry_date TEXT NOT NULL,
  planned_weight REAL NOT NULL CHECK(planned_weight >= 0 AND planned_weight <= 0.12),
  priority INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('planned','open','exit_pending','closed','skipped')),
  execution_mode TEXT,
  fill_source TEXT,
  entry_date TEXT,
  raw_entry_price REAL,
  quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
  entry_commission REAL NOT NULL DEFAULT 0,
  entry_tax REAL NOT NULL DEFAULT 0,
  entry_slippage REAL NOT NULL DEFAULT 0,
  exit_trigger_date TEXT,
  exit_date TEXT,
  raw_exit_price REAL,
  exit_commission REAL NOT NULL DEFAULT 0,
  exit_tax REAL NOT NULL DEFAULT 0,
  exit_slippage REAL NOT NULL DEFAULT 0,
  armed_at TEXT,
  highest_close REAL,
  exit_line REAL,
  last_evaluated_date TEXT,
  forced_exit_target_date TEXT,
  UNIQUE(ledger_id, setup, setup_version, ticker, signal_date, planned_entry_date)
);
CREATE TABLE IF NOT EXISTS trade_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  trade_id TEXT NOT NULL REFERENCES trades(trade_id),
  event_type TEXT NOT NULL,
  effective_date TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  cash_delta REAL NOT NULL DEFAULT 0,
  position_delta INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_valuations (
  ledger_id TEXT NOT NULL REFERENCES ledger_meta(ledger_id),
  trade_date TEXT NOT NULL,
  cash REAL NOT NULL,
  market_value REAL NOT NULL,
  nav REAL NOT NULL CHECK(nav > 0),
  peak REAL NOT NULL CHECK(peak > 0),
  drawdown REAL NOT NULL,
  stale_tickers_json TEXT NOT NULL,
  PRIMARY KEY(ledger_id, trade_date)
);
```

Implement each public mutation with `with self._connect() as conn:` so SQLite commits trade and event together. Compute `event_id` and `idempotency_key` deterministically from trade id, transition, and attempt. Set `PRAGMA busy_timeout=5000` for every connection.

- [ ] **Step 4: Verify GREEN and concurrent idempotency**

Run: `uv run pytest tests/offensive/test_ledger_repository.py -v`

Expected: all repository tests pass, including an added `ThreadPoolExecutor` test that calls `create_plan()` eight times and observes one row and one event.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/ledger_repository.py tests/offensive/test_ledger_repository.py
git commit -m "feat: add transactional paper ledger"
```

### Task 3: Fail-closed calendar and holding-session semantics

**Files:**
- Modify: `src/paper_trading/btst_trade_calendar.py`
- Create: `tests/offensive/test_trade_session_semantics.py`

**Interfaces:**
- Produces: `next_session(date)`, `nth_holding_session(entry_date, n)`, `session_distance(start, end)`.

- [ ] **Step 1: Add failing tests with injected open sessions**

```python
from datetime import date

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar


def test_friday_entry_plan_resolves_to_monday() -> None:
    cal = TradingSessionCalendar.from_dates([date(2026, 7, 10), date(2026, 7, 13)])
    assert cal.next_session(date(2026, 7, 10)) == date(2026, 7, 13)


def test_tenth_holding_session_counts_entry_as_one() -> None:
    sessions = [date(2026, 9, d) for d in (21, 22, 23, 24, 25, 28, 29, 30)] + [date(2026, 10, d) for d in (9, 12)]
    cal = TradingSessionCalendar.from_dates(sessions)
    assert cal.nth_holding_session(date(2026, 9, 21), 10) == date(2026, 10, 12)


def test_calendar_failure_does_not_fall_back_to_weekdays() -> None:
    cal = TradingSessionCalendar.from_dates([])
    with pytest.raises(ValueError, match="open-session data unavailable"):
        cal.next_session(date(2026, 10, 1))
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/test_trade_session_semantics.py -v`

Expected: `TradingSessionCalendar` is missing.

- [ ] **Step 3: Implement the calendar value object**

Store a sorted tuple of unique open dates; use `bisect_right` for next session and exact index arithmetic for nth session. Reject `n < 1`, entry dates absent from the calendar, and insufficient future sessions. Keep the existing network resolver as the factory that supplies dates; remove weekday fallback from v2 call paths.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/offensive/test_trade_session_semantics.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/paper_trading/btst_trade_calendar.py tests/offensive/test_trade_session_semantics.py
git commit -m "fix: use exact holding-session calendar"
```

### Task 4: Tri-state execution proxy and separated costs

**Files:**
- Modify: `src/screening/offensive/execution_adjuster.py`
- Modify: `tests/offensive/test_execution_adjuster.py`

**Interfaces:**
- Produces: `ExecutionStatus`, `ExecutionCosts`, `FillResult`, `classify_open_fill()`, `apply_execution_costs()`.

- [ ] **Step 1: Add failing execution tests**

```python
def test_open_inside_limits_is_executable_proxy():
    result = classify_open_fill(open_price=10.5, limit_down=9.0, limit_up=11.0, suspended=False)
    assert result is ExecutionStatus.EXECUTABLE_PROXY


def test_open_on_limit_is_unknown_queue():
    assert classify_open_fill(11.0, 9.0, 11.0, False) is ExecutionStatus.UNKNOWN_QUEUE


def test_locked_board_is_conservative_unexecutable_proxy():
    assert classify_open_fill(11.0, 9.0, 11.0, False, high=11.0, low=11.0) is ExecutionStatus.UNEXECUTABLE_PROXY


def test_missing_limit_or_suspension_state_fails_closed():
    assert classify_open_fill(10.0, None, 11.0, False) is ExecutionStatus.UNKNOWN_QUEUE
    assert classify_open_fill(10.0, 9.0, 11.0, None) is ExecutionStatus.UNKNOWN_QUEUE


def test_costs_are_not_embedded_in_raw_fill_price():
    fill = apply_execution_costs(raw_fill_price=10.0, quantity=1_000, side="buy", costs=ExecutionCosts(commission=5.0, tax_rate=0.0, slippage_bps=30))
    assert fill.raw_fill_price == 10.0
    assert fill.gross_notional == 10_000.0
    assert fill.slippage_cost == 30.0
    assert fill.net_cash_flow == -10_035.0
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/test_execution_adjuster.py -v`

Expected: new execution types are missing.

- [ ] **Step 3: Implement minimal tri-state functions**

Keep legacy `adjust_returns()` for compatibility but route v2 through the new functions. Do not infer exact queue fills from volume. Enforce T+1 by rejecting an exit whose date is not strictly after entry date. Keep the cost configuration versioned and injectable; do not hard-code a new tax rate in strategy code.

- [ ] **Step 4: Verify GREEN and old regressions**

Run: `uv run pytest tests/offensive/test_execution_adjuster.py -v`

Expected: all old and new tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/execution_adjuster.py tests/offensive/test_execution_adjuster.py
git commit -m "fix: model execution uncertainty explicitly"
```

### Task 5: Daily valuation, exposure reservation, and forced-exit planning

**Files:**
- Create: `src/screening/offensive/daily_action_service.py`
- Create: `tests/offensive/test_daily_action_service.py`

**Interfaces:**
- Consumes: repository, calendar, price/limit providers, and scanner-produced candidates.
- Produces: `DailyActionService.run(as_of, candidates) -> DailyActionRun`.

- [ ] **Step 1: Write failing service tests**

Cover these exact behaviors in separate tests:

```python
def test_pending_plans_reserve_exposure_and_never_exceed_sixty_percent(service, signal_date, six_candidates):
    run = service.run(signal_date, six_candidates)
    assert run.open_exposure == 0.0
    assert run.reserved_exposure == pytest.approx(0.60)
    assert len(run.new_plans) == 6


def test_fill_rechecks_capacity_and_skips_lower_priority_plan(service, entry_date, seven_due_plans):
    run = service.run(entry_date, ())
    assert run.open_exposure <= 0.60
    assert run.skipped_plans[-1].reason == "portfolio_capacity"


def test_mark_to_market_updates_nav_and_drawdown_before_new_plans(service, next_session, losing_open_trade):
    run = service.run(next_session, ())
    assert run.valuation.nav < service.repository.initial_cash
    assert run.valuation.drawdown < 0
    assert run.valuation.trade_date == next_session


def test_session_nine_close_creates_exit_pending_for_session_ten_open(service, session_nine, mature_open_trade):
    run = service.run(session_nine, ())
    trade = service.repository.get_trade(mature_open_trade.trade_id)
    assert trade.state is TradeState.EXIT_PENDING
    assert trade.forced_exit_target_date == service.calendar.nth_holding_session(trade.entry_date, 10)
    assert run.exit_plans[0].reason == "maximum_holding_session"


def test_limit_down_unknown_queue_records_exit_deferred(service, session_ten, exit_pending_trade):
    run = service.run(session_ten, ())
    assert service.repository.get_trade(exit_pending_trade.trade_id).state is TradeState.EXIT_PENDING
    assert run.deferred_exits[0].reason == "unknown_queue"
    assert service.repository.count_events(exit_pending_trade.trade_id, "EXIT_DEFERRED") == 1


def test_missing_calendar_blocks_new_plan_but_still_lists_open_trade(service, signal_date, candidate, open_trade, monkeypatch):
    monkeypatch.setattr(service.calendar, "next_session", lambda value: (_ for _ in ()).throw(ValueError("open-session data unavailable")))
    run = service.run(signal_date, (candidate,))
    assert run.new_plans == ()
    assert run.open_positions[0].trade_id == open_trade.trade_id
    assert run.block_reason == "calendar_unavailable"
```

Each test uses an in-memory SQLite repository, a fixed 12-session calendar, and deterministic prices. Assert trade states, event counts, cash, NAV, open exposure, reserved exposure, and rendered simulation labels.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/test_daily_action_service.py -v`

Expected: service import fails.

- [ ] **Step 3: Implement the service in this fixed order**

```python
def run(self, as_of: date, candidates: Sequence[PlanCandidate]) -> DailyActionRun:
    self._settle_due_entry_plans(as_of)
    exits = self._settle_due_exit_plans(as_of)
    valuation = self._mark_to_market(as_of)
    self._evaluate_open_positions(as_of)
    plans = self._create_capacity_safe_plans(as_of, candidates, valuation)
    return self._build_view(as_of, valuation, exits, plans)
```

The service must calculate quantities in 100-share lots, preserve cash for fees, reserve pending weights, and never use stale valuation to increase available capacity. A queue-unknown exit remains pending and is retried next session.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/offensive/test_daily_action_service.py -v`

Expected: all service tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/daily_action_service.py tests/offensive/test_daily_action_service.py
git commit -m "feat: orchestrate auditable daily trade actions"
```

### Task 6: Integrate scanner, caps, and CLI without touching v1 artifacts

**Files:**
- Modify: `src/screening/offensive/daily_action.py`
- Modify: `src/cli/dispatcher.py`
- Modify: `tests/offensive/test_daily_action.py`
- Create: `tests/offensive/test_daily_action_v2_integration.py`

**Interfaces:**
- Scanner produces `PlanCandidate` only; v2 service persists plans.
- CLI defaults to `data/paper_trading_v2/ledger.sqlite3` and labels all synthetic fills.

- [ ] **Step 1: Add failing integration tests**

```python
def test_signal_date_creates_plan_not_open_position(v2_daily_run):
    assert len(v2_daily_run.plans) == 1
    assert v2_daily_run.open_positions == ()


def test_degraded_btst_is_displayed_but_never_planned(v2_degraded_run):
    assert v2_degraded_run.plans == ()
    assert v2_degraded_run.blocked_candidates[0].reason == "incomplete_setup_data"


def test_btst_normal_cap_is_ten_percent_and_crisis_cap_is_twelve(normal_run, crisis_run):
    assert normal_run.plans[0].planned_weight == pytest.approx(0.10)
    assert crisis_run.plans[0].planned_weight == pytest.approx(0.12)


def test_repeat_cli_run_is_idempotent(run_daily_action_twice):
    first, second, repository = run_daily_action_twice
    assert first.plans[0].trade_id == second.plans[0].trade_id
    assert repository.count_events(first.plans[0].trade_id, "PLAN_CREATED") == 1


def test_v1_files_are_byte_identical_after_v2_run(v1_artifact_bytes, run_v2_once):
    assert {path: path.read_bytes() for path in v1_artifact_bytes} == v1_artifact_bytes


def test_output_distinguishes_reference_synthetic_and_confirmed_prices(rendered_v2_output):
    assert "参考价" in rendered_v2_output
    assert "模拟成交" in rendered_v2_output
    assert "确认成交" in rendered_v2_output
```

Use existing fake setup seams from `tests/offensive/test_daily_action.py`; do not call external APIs.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/test_daily_action_v2_integration.py -v`

Expected: current code records BUY immediately and fails the first assertion.

- [ ] **Step 3: Make the minimal integration changes**

- Change `_MAX_POSITION_PCT_BY_SETUP["btst_breakout"]` to `0.10` and preserve `_REGIME_POSITION_CAP_MULTIPLE=1.2`.
- Convert ranked hits to `PlanCandidate`; do not call v1 `record_buy()`.
- Exclude every `degraded=True` hit from persisted plans while retaining its display reason.
- Instantiate `LedgerRepository` and `DailyActionService` in `_resolve_daily_action()`.
- Keep `PaperTracker` only behind an explicit legacy compatibility path used by old tests; production v2 must not write v1 files.
- Close all repository connections through context managers.

- [ ] **Step 4: Verify targeted and baseline suites**

Run:

```bash
uv run pytest tests/offensive/test_daily_action_v2_integration.py -v
uv run pytest tests/offensive/test_daily_action.py -v
uv run pytest tests/offensive/test_execution_adjuster.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/daily_action.py src/cli/dispatcher.py tests/offensive/test_daily_action.py tests/offensive/test_daily_action_v2_integration.py
git commit -m "feat: route daily action through v2 ledger"
```

### Task 7: Phase-one verification

**Files:**
- No production changes unless verification exposes a regression.

- [ ] **Step 1: Run the full offensive suite**

Run: `uv run pytest tests/offensive/ -v`

Expected: all tests pass.

- [ ] **Step 2: Run cache bridge regressions**

Run:

```bash
uv run pytest tests/test_main_auto_cache_refresh.py -v
uv run pytest tests/offensive/test_daily_action_cache_refresh.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Verify legacy artifacts and worktree scope**

Run:

```bash
git diff --exit-code -- data/paper_trading data/paper_trading_backtest
git status --short
```

Expected: no changes under either legacy data directory; only phase-one code/tests are listed.
