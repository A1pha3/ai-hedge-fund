from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.screening.offensive.trade_lifecycle import (
    ExecutionMode,
    FillSource,
    TradeIdentity,
    TradeState,
    assert_transition,
    deterministic_trade_id,
)


@dataclass(frozen=True)
class LedgerTrade:
    trade_id: str
    ticker: str
    setup: str
    setup_version: str
    signal_date: date
    planned_entry_date: date
    planned_weight: float
    priority: int
    state: TradeState
    execution_mode: ExecutionMode | None
    fill_source: FillSource | None
    entry_date: date | None
    raw_entry_price: float | None
    quantity: int
    exit_trigger_date: date | None
    exit_date: date | None
    raw_exit_price: float | None


class LedgerRepository:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path | str, ledger_id: str, initial_cash: float) -> None:
        self.path = Path(path)
        self.ledger_id = ledger_id
        self.initial_cash = initial_cash

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
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
"""
            )
            conn.execute(
                "INSERT OR IGNORE INTO ledger_meta VALUES (?, ?, ?, ?)",
                (self.ledger_id, self.SCHEMA_VERSION, self.initial_cash, self._now()),
            )

    def create_plan(
        self,
        ticker: str,
        setup: str,
        setup_version: str,
        signal_date: date,
        planned_entry_date: date,
        planned_weight: float,
        priority: int,
    ) -> LedgerTrade:
        identity = TradeIdentity(
            self.ledger_id, setup, setup_version, ticker, signal_date, planned_entry_date
        )
        trade_id = deterministic_trade_id(identity)
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO trades
                   (trade_id, ledger_id, ticker, setup, setup_version, signal_date,
                    planned_entry_date, planned_weight, priority, state)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade_id,
                    self.ledger_id,
                    ticker,
                    setup,
                    setup_version,
                    signal_date.isoformat(),
                    planned_entry_date.isoformat(),
                    planned_weight,
                    priority,
                    TradeState.PLANNED.value,
                ),
            )
            if cursor.rowcount:
                self._insert_event(
                    conn, trade_id, "PLAN_CREATED", signal_date, payload={"priority": priority}
                )
            return self._get_trade(conn, trade_id)

    def fill_plan(
        self,
        trade_id: str,
        execution_mode: ExecutionMode,
        fill_source: FillSource,
        entry_date: date,
        raw_fill_price: float,
        quantity: int,
        commission: float,
        tax: float,
        slippage_cost: float,
    ) -> LedgerTrade:
        execution_mode = ExecutionMode(execution_mode)
        fill_source = FillSource(fill_source)
        if fill_source.allowed_mode is not execution_mode:
            raise ValueError(f"{fill_source} is not allowed for {execution_mode}")
        with self._connect() as conn:
            current = self._get_trade(conn, trade_id)
            if current.state is TradeState.OPEN:
                return current
            assert_transition(current.state, TradeState.OPEN)
            conn.execute(
                """UPDATE trades SET state=?, execution_mode=?, fill_source=?, entry_date=?,
                   raw_entry_price=?, quantity=?, entry_commission=?, entry_tax=?, entry_slippage=?
                   WHERE trade_id=?""",
                (
                    TradeState.OPEN.value,
                    execution_mode.value,
                    fill_source.value,
                    entry_date.isoformat(),
                    raw_fill_price,
                    quantity,
                    commission,
                    tax,
                    slippage_cost,
                    trade_id,
                ),
            )
            cash_delta = -(raw_fill_price * quantity + commission + tax + slippage_cost)
            self._insert_event(
                conn,
                trade_id,
                "ENTRY_FILLED",
                entry_date,
                cash_delta=cash_delta,
                position_delta=quantity,
                payload={"raw_fill_price": raw_fill_price, "fill_source": fill_source.value},
            )
            return self._get_trade(conn, trade_id)

    def mark_exit_pending(
        self,
        trade_id: str,
        exit_trigger_date: date,
        *,
        armed_at: datetime | None = None,
        highest_close: float | None = None,
        exit_line: float | None = None,
        forced_exit_target_date: date | None = None,
    ) -> LedgerTrade:
        with self._connect() as conn:
            current = self._get_trade(conn, trade_id)
            if current.state is TradeState.EXIT_PENDING:
                return current
            assert_transition(current.state, TradeState.EXIT_PENDING)
            conn.execute(
                """UPDATE trades SET state=?, exit_trigger_date=?, armed_at=?, highest_close=?,
                   exit_line=?, forced_exit_target_date=? WHERE trade_id=?""",
                (
                    TradeState.EXIT_PENDING.value,
                    exit_trigger_date.isoformat(),
                    armed_at.isoformat() if armed_at else None,
                    highest_close,
                    exit_line,
                    forced_exit_target_date.isoformat() if forced_exit_target_date else None,
                    trade_id,
                ),
            )
            self._insert_event(conn, trade_id, "EXIT_PENDING", exit_trigger_date)
            return self._get_trade(conn, trade_id)

    def defer_exit(
        self,
        trade_id: str,
        evaluation_date: date,
        *,
        highest_close: float | None = None,
        exit_line: float | None = None,
        forced_exit_target_date: date | None = None,
    ) -> LedgerTrade:
        with self._connect() as conn:
            current = self._get_trade(conn, trade_id)
            if current.state is not TradeState.EXIT_PENDING:
                raise ValueError(f"cannot defer exit for trade in state {current.state}")
            conn.execute(
                """UPDATE trades SET last_evaluated_date=?, highest_close=COALESCE(?, highest_close),
                   exit_line=COALESCE(?, exit_line),
                   forced_exit_target_date=COALESCE(?, forced_exit_target_date) WHERE trade_id=?""",
                (
                    evaluation_date.isoformat(),
                    highest_close,
                    exit_line,
                    forced_exit_target_date.isoformat() if forced_exit_target_date else None,
                    trade_id,
                ),
            )
            self._insert_event(
                conn, trade_id, "EXIT_DEFERRED", evaluation_date, attempt=evaluation_date.isoformat()
            )
            return self._get_trade(conn, trade_id)

    def close_trade(
        self,
        trade_id: str,
        exit_date: date,
        raw_fill_price: float,
        commission: float,
        tax: float,
        slippage_cost: float,
    ) -> LedgerTrade:
        with self._connect() as conn:
            current = self._get_trade(conn, trade_id)
            if current.state is TradeState.CLOSED:
                return current
            assert_transition(current.state, TradeState.CLOSED)
            conn.execute(
                """UPDATE trades SET state=?, exit_date=?, raw_exit_price=?, exit_commission=?,
                   exit_tax=?, exit_slippage=? WHERE trade_id=?""",
                (
                    TradeState.CLOSED.value,
                    exit_date.isoformat(),
                    raw_fill_price,
                    commission,
                    tax,
                    slippage_cost,
                    trade_id,
                ),
            )
            cash_delta = raw_fill_price * current.quantity - commission - tax - slippage_cost
            self._insert_event(
                conn,
                trade_id,
                "EXIT_FILLED",
                exit_date,
                cash_delta=cash_delta,
                position_delta=-current.quantity,
                payload={"raw_fill_price": raw_fill_price},
            )
            return self._get_trade(conn, trade_id)

    def open_trades(self) -> list[LedgerTrade]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE ledger_id=? AND state IN (?, ?) ORDER BY priority, trade_id",
                (self.ledger_id, TradeState.OPEN.value, TradeState.EXIT_PENDING.value),
            ).fetchall()
            return [self._row_to_trade(row) for row in rows]

    def record_valuation(
        self,
        trade_date: date,
        cash: float,
        market_value: float,
        nav: float,
        peak: float,
        drawdown: float,
        stale_tickers: list[str] | tuple[str, ...],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO daily_valuations VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ledger_id, trade_date) DO UPDATE SET cash=excluded.cash,
                   market_value=excluded.market_value, nav=excluded.nav, peak=excluded.peak,
                   drawdown=excluded.drawdown, stale_tickers_json=excluded.stale_tickers_json""",
                (
                    self.ledger_id,
                    trade_date.isoformat(),
                    cash,
                    market_value,
                    nav,
                    peak,
                    drawdown,
                    json.dumps(sorted(stale_tickers), separators=(",", ":")),
                ),
            )

    def get_trade(self, trade_id: str) -> LedgerTrade:
        with self._connect() as conn:
            return self._get_trade(conn, trade_id)

    def cash_balance(self) -> float:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT m.initial_cash + COALESCE(SUM(e.cash_delta), 0) AS cash
                   FROM ledger_meta m LEFT JOIN trades t ON t.ledger_id=m.ledger_id
                   LEFT JOIN trade_events e ON e.trade_id=t.trade_id WHERE m.ledger_id=?""",
                (self.ledger_id,),
            ).fetchone()
            return float(row["cash"])

    def count_events(self, trade_id: str, event_type: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM trade_events WHERE trade_id=? AND event_type=?",
                (trade_id, event_type),
            ).fetchone()
            return int(row["count"])

    def count_trades(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM trades WHERE ledger_id=?", (self.ledger_id,)
            ).fetchone()
            return int(row["count"])

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        trade_id: str,
        event_type: str,
        effective_date: date,
        *,
        attempt: str = "1",
        cash_delta: float = 0,
        position_delta: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> None:
        key = f"{trade_id}|{event_type}|{attempt}"
        event_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        conn.execute(
            """INSERT OR IGNORE INTO trade_events
               (event_id, idempotency_key, trade_id, event_type, effective_date, occurred_at,
                cash_delta, position_delta, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                key,
                trade_id,
                event_type,
                effective_date.isoformat(),
                self._now(),
                cash_delta,
                position_delta,
                json.dumps(payload or {}, sort_keys=True, separators=(",", ":")),
            ),
        )

    def _get_trade(self, conn: sqlite3.Connection, trade_id: str) -> LedgerTrade:
        row = conn.execute(
            "SELECT * FROM trades WHERE trade_id=? AND ledger_id=?", (trade_id, self.ledger_id)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown trade: {trade_id}")
        return self._row_to_trade(row)

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> LedgerTrade:
        as_date = lambda value: date.fromisoformat(value) if value else None
        return LedgerTrade(
            trade_id=row["trade_id"],
            ticker=row["ticker"],
            setup=row["setup"],
            setup_version=row["setup_version"],
            signal_date=date.fromisoformat(row["signal_date"]),
            planned_entry_date=date.fromisoformat(row["planned_entry_date"]),
            planned_weight=row["planned_weight"],
            priority=row["priority"],
            state=TradeState(row["state"]),
            execution_mode=ExecutionMode(row["execution_mode"]) if row["execution_mode"] else None,
            fill_source=FillSource(row["fill_source"]) if row["fill_source"] else None,
            entry_date=as_date(row["entry_date"]),
            raw_entry_price=row["raw_entry_price"],
            quantity=row["quantity"],
            exit_trigger_date=as_date(row["exit_trigger_date"]),
            exit_date=as_date(row["exit_date"]),
            raw_exit_price=row["raw_exit_price"],
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
