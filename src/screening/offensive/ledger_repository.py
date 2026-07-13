from __future__ import annotations

import hashlib
import json
import math
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
    highest_close: float | None
    exit_line: float | None
    last_evaluated_date: date | None
    forced_exit_target_date: date | None


@dataclass(frozen=True)
class DailyValuation:
    trade_date: date
    cash: float
    market_value: float
    nav: float
    peak: float
    drawdown: float
    stale_tickers: tuple[str, ...]


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
CREATE TABLE IF NOT EXISTS position_marks (
  ledger_id TEXT NOT NULL REFERENCES ledger_meta(ledger_id),
  ticker TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  close_price REAL NOT NULL CHECK(close_price > 0),
  PRIMARY KEY(ledger_id, ticker, trade_date)
);
"""
            )
            conn.execute(
                "INSERT OR IGNORE INTO ledger_meta VALUES (?, ?, ?, ?)",
                (self.ledger_id, self.SCHEMA_VERSION, self.initial_cash, self._now()),
            )
            meta = conn.execute(
                "SELECT schema_version, initial_cash FROM ledger_meta WHERE ledger_id=?",
                (self.ledger_id,),
            ).fetchone()
            if meta["schema_version"] != self.SCHEMA_VERSION:
                raise ValueError(
                    f"unsupported schema version: {meta['schema_version']} "
                    f"(expected {self.SCHEMA_VERSION})"
                )
            if meta["initial_cash"] != self.initial_cash:
                raise ValueError(
                    f"initial_cash mismatch: stored {meta['initial_cash']}, "
                    f"requested {self.initial_cash}"
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
        return self.create_plan_if_absent(
            ticker,
            setup,
            setup_version,
            signal_date,
            planned_entry_date,
            planned_weight,
            priority,
        )[0]

    def create_plan_if_absent(
        self,
        ticker: str,
        setup: str,
        setup_version: str,
        signal_date: date,
        planned_entry_date: date,
        planned_weight: float,
        priority: int,
    ) -> tuple[LedgerTrade, bool]:
        identity = TradeIdentity(
            self.ledger_id,
            setup,
            setup_version,
            ticker,
            signal_date,
            planned_entry_date,
        )
        trade_id = deterministic_trade_id(identity)
        with self._connect() as conn:
            self._begin_write(conn)
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
            created = bool(cursor.rowcount)
            if created:
                self._insert_event(
                    conn,
                    trade_id,
                    "PLAN_CREATED",
                    signal_date,
                    payload={"priority": priority},
                )
            return self._get_trade(conn, trade_id), created

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
        self._validate_fill(raw_fill_price, quantity, commission, tax, slippage_cost)
        if fill_source.allowed_mode is not execution_mode:
            raise ValueError(f"{fill_source} is not allowed for {execution_mode}")
        payload = {
            "raw_fill_price": raw_fill_price,
            "execution_mode": execution_mode.value,
            "fill_source": fill_source.value,
            "quantity": quantity,
            "commission": commission,
            "tax": tax,
            "slippage_cost": slippage_cost,
        }
        cash_delta = -(raw_fill_price * quantity + commission + tax + slippage_cost)
        with self._connect() as conn:
            self._begin_write(conn)
            current = self._get_trade(conn, trade_id)
            if current.state is TradeState.OPEN:
                self._insert_event(
                    conn,
                    trade_id,
                    "ENTRY_FILLED",
                    entry_date,
                    cash_delta=cash_delta,
                    position_delta=quantity,
                    payload=payload,
                )
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
            self._insert_event(
                conn,
                trade_id,
                "ENTRY_FILLED",
                entry_date,
                cash_delta=cash_delta,
                position_delta=quantity,
                payload=payload,
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
        payload = {
            "armed_at": armed_at.isoformat() if armed_at else None,
            "highest_close": highest_close,
            "exit_line": exit_line,
            "forced_exit_target_date": (
                forced_exit_target_date.isoformat() if forced_exit_target_date else None
            ),
        }
        with self._connect() as conn:
            self._begin_write(conn)
            current = self._get_trade(conn, trade_id)
            if current.state is TradeState.EXIT_PENDING:
                self._insert_event(
                    conn, trade_id, "EXIT_PENDING", exit_trigger_date, payload=payload
                )
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
                    forced_exit_target_date.isoformat()
                    if forced_exit_target_date
                    else None,
                    trade_id,
                ),
            )
            self._insert_event(
                conn, trade_id, "EXIT_PENDING", exit_trigger_date, payload=payload
            )
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
        payload = {
            "highest_close": highest_close,
            "exit_line": exit_line,
            "forced_exit_target_date": (
                forced_exit_target_date.isoformat() if forced_exit_target_date else None
            ),
        }
        with self._connect() as conn:
            self._begin_write(conn)
            current = self._get_trade(conn, trade_id)
            if current.state is not TradeState.EXIT_PENDING:
                raise ValueError(
                    f"cannot defer exit for trade in state {current.state}"
                )
            conn.execute(
                """UPDATE trades SET last_evaluated_date=?, highest_close=COALESCE(?, highest_close),
                   exit_line=COALESCE(?, exit_line),
                   forced_exit_target_date=COALESCE(?, forced_exit_target_date) WHERE trade_id=?""",
                (
                    evaluation_date.isoformat(),
                    highest_close,
                    exit_line,
                    forced_exit_target_date.isoformat()
                    if forced_exit_target_date
                    else None,
                    trade_id,
                ),
            )
            self._insert_event(
                conn,
                trade_id,
                "EXIT_DEFERRED",
                evaluation_date,
                attempt=evaluation_date.isoformat(),
                payload=payload,
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
        self._validate_price_and_costs(raw_fill_price, commission, tax, slippage_cost)
        payload = {
            "raw_fill_price": raw_fill_price,
            "commission": commission,
            "tax": tax,
            "slippage_cost": slippage_cost,
        }
        with self._connect() as conn:
            self._begin_write(conn)
            current = self._get_trade(conn, trade_id)
            cash_delta = (
                raw_fill_price * current.quantity - commission - tax - slippage_cost
            )
            if current.state is TradeState.CLOSED:
                self._insert_event(
                    conn,
                    trade_id,
                    "EXIT_FILLED",
                    exit_date,
                    cash_delta=cash_delta,
                    position_delta=-current.quantity,
                    payload=payload,
                )
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
            self._insert_event(
                conn,
                trade_id,
                "EXIT_FILLED",
                exit_date,
                cash_delta=cash_delta,
                position_delta=-current.quantity,
                payload=payload,
            )
            return self._get_trade(conn, trade_id)

    def open_trades(self) -> list[LedgerTrade]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE ledger_id=? AND state IN (?, ?) ORDER BY priority, trade_id",
                (self.ledger_id, TradeState.OPEN.value, TradeState.EXIT_PENDING.value),
            ).fetchall()
            return [self._row_to_trade(row) for row in rows]

    def planned_trades(self, due_on_or_before: date | None = None) -> list[LedgerTrade]:
        with self._connect() as conn:
            sql = "SELECT * FROM trades WHERE ledger_id=? AND state=?"
            params: list[Any] = [self.ledger_id, TradeState.PLANNED.value]
            if due_on_or_before is not None:
                sql += " AND planned_entry_date<=?"
                params.append(due_on_or_before.isoformat())
            sql += " ORDER BY priority, trade_id"
            return [
                self._row_to_trade(row) for row in conn.execute(sql, params).fetchall()
            ]

    def skip_plan(
        self, trade_id: str, effective_date: date, reason: str
    ) -> LedgerTrade:
        if not reason:
            raise ValueError("reason must be nonempty")
        with self._connect() as conn:
            self._begin_write(conn)
            current = self._get_trade(conn, trade_id)
            payload = {"reason": reason}
            if current.state is TradeState.SKIPPED:
                self._insert_event(
                    conn, trade_id, "PLAN_SKIPPED", effective_date, payload=payload
                )
                return current
            assert_transition(current.state, TradeState.SKIPPED)
            conn.execute(
                "UPDATE trades SET state=? WHERE trade_id=?",
                (TradeState.SKIPPED.value, trade_id),
            )
            self._insert_event(
                conn, trade_id, "PLAN_SKIPPED", effective_date, payload=payload
            )
            return self._get_trade(conn, trade_id)

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
            self._begin_write(conn)
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

    def latest_valuation(self) -> DailyValuation | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_valuations WHERE ledger_id=? ORDER BY trade_date DESC LIMIT 1",
                (self.ledger_id,),
            ).fetchone()
            if row is None:
                return None
            return DailyValuation(
                trade_date=date.fromisoformat(row["trade_date"]),
                cash=float(row["cash"]),
                market_value=float(row["market_value"]),
                nav=float(row["nav"]),
                peak=float(row["peak"]),
                drawdown=float(row["drawdown"]),
                stale_tickers=tuple(json.loads(row["stale_tickers_json"])),
            )

    def record_position_mark(
        self, ticker: str, trade_date: date, close_price: float
    ) -> None:
        if not math.isfinite(close_price) or close_price <= 0:
            raise ValueError("close_price must be finite and positive")
        with self._connect() as conn:
            self._begin_write(conn)
            conn.execute(
                "INSERT INTO position_marks VALUES (?, ?, ?, ?) "
                "ON CONFLICT(ledger_id, ticker, trade_date) DO UPDATE SET close_price=excluded.close_price",
                (self.ledger_id, ticker, trade_date.isoformat(), close_price),
            )

    def latest_position_mark(self, ticker: str, on_or_before: date) -> float | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT close_price FROM position_marks WHERE ledger_id=? AND ticker=? "
                "AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",
                (self.ledger_id, ticker, on_or_before.isoformat()),
            ).fetchone()
            return float(row["close_price"]) if row else None

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
                "SELECT COUNT(*) AS count FROM trades WHERE ledger_id=?",
                (self.ledger_id,),
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
        values = (
            event_id,
            key,
            trade_id,
            event_type,
            effective_date.isoformat(),
            self._now(),
            cash_delta,
            position_delta,
            json.dumps(payload or {}, sort_keys=True, separators=(",", ":")),
        )
        try:
            conn.execute(
                """INSERT INTO trade_events
               (event_id, idempotency_key, trade_id, event_type, effective_date, occurred_at,
                cash_delta, position_delta, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
        except sqlite3.IntegrityError:
            existing = conn.execute(
                """SELECT event_id, idempotency_key, trade_id, event_type, effective_date,
                   cash_delta, position_delta, payload_json FROM trade_events
                   WHERE idempotency_key=?""",
                (key,),
            ).fetchone()
            expected = values[:5] + values[6:]
            if existing is None or tuple(existing) != expected:
                raise ValueError(f"conflicting idempotent event: {key}") from None

    def _get_trade(self, conn: sqlite3.Connection, trade_id: str) -> LedgerTrade:
        row = conn.execute(
            "SELECT * FROM trades WHERE trade_id=? AND ledger_id=?",
            (trade_id, self.ledger_id),
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
            execution_mode=ExecutionMode(row["execution_mode"])
            if row["execution_mode"]
            else None,
            fill_source=FillSource(row["fill_source"]) if row["fill_source"] else None,
            entry_date=as_date(row["entry_date"]),
            raw_entry_price=row["raw_entry_price"],
            quantity=row["quantity"],
            exit_trigger_date=as_date(row["exit_trigger_date"]),
            exit_date=as_date(row["exit_date"]),
            raw_exit_price=row["raw_exit_price"],
            highest_close=row["highest_close"],
            exit_line=row["exit_line"],
            last_evaluated_date=as_date(row["last_evaluated_date"]),
            forced_exit_target_date=as_date(row["forced_exit_target_date"]),
        )

    @staticmethod
    def _begin_write(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")

    @classmethod
    def _validate_fill(
        cls,
        price: float,
        quantity: int,
        commission: float,
        tax: float,
        slippage: float,
    ) -> None:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        cls._validate_price_and_costs(price, commission, tax, slippage)

    @staticmethod
    def _validate_price_and_costs(
        price: float, commission: float, tax: float, slippage: float
    ) -> None:
        if not math.isfinite(price) or price <= 0:
            raise ValueError("fill price must be finite and positive")
        for name, value in (
            ("commission", commission),
            ("tax", tax),
            ("slippage", slippage),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
