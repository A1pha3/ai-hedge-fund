"""Plan 06 Task 1: v2 资本状态只读盘点.

`capture_v2_inventory()` 以 immutable 只读 URI 打开 v2 ledger SQLite, 逐项捕获
守恒所需全部字段并合成 source root. 安全性质:

- 源文件 byte-identical: 不 checkpoint、不恢复 WAL、不以可写方式打开.
- 禁止默认/取整: 任何 NULL/未知/不可表示字段直接 InventoryError
  (UNREPRESENTABLE_FACT), 不产生 ``0.0`` 之类的静默默认.
- v2 schema 之外的可写表 (如外部注入的 live_orders) 视为不可归因风险,
  阻断盘点而非丢弃.
- 逐项 section root: 任一守恒节变化只翻转对应节根, source root 由节根
  规范化合成, 供迁移 CAS preimage 绑定.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    content_hash,
    domain_hash,
)

from src.screening.offensive.v3.migration.models import (
    CashFact,
    FeeTotalsFact,
    LedgerMetaFact,
    MarkFact,
    OrderFact,
    PendingExitFact,
    PlanFact,
    PositionFact,
    SourceToken,
    ValuationFact,
)

LEDGER_MISMATCH = "LEDGER_MISMATCH"
SYMLINK_SOURCE = "SYMLINK_SOURCE"
NON_REGULAR_SOURCE = "NON_REGULAR_SOURCE"
UNREPRESENTABLE_FACT = "UNREPRESENTABLE_FACT"
UNATTRIBUTED_RISK = UNREPRESENTABLE_FACT  # 不可归因风险以同一阻断码呈现

_SOURCE_ROOT_DOMAIN = "ai-hedge-fund.v3.migration.v2-source-root.v1"

# v2 ledger schema (SCHEMA_VERSION=2) 的全部可写表; 其余出现即不可归因.
_KNOWN_TABLES = frozenset(
    {
        "ledger_meta",
        "trades",
        "trade_events",
        "daily_valuations",
        "position_marks",
        "sqlite_sequence",
    }
)

_TRADE_STATES = frozenset(
    {"planned", "open", "exit_pending", "closed", "skipped"}
)

_COST_FIELDS = (
    "entry_commission",
    "entry_tax",
    "entry_slippage",
    "exit_commission",
    "exit_tax",
    "exit_slippage",
)


class InventoryError(ValueError):
    """盘点失败: 携带稳定 ``code`` 供 runbook/调用方机器可读分支."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class V2Inventory(CanonicalModel):
    """一次只读盘点的完整结果; ``source_root`` 绑定全部守恒节."""

    meta: LedgerMetaFact
    cash: CashFact
    positions: tuple[PositionFact, ...]
    plans: tuple[PlanFact, ...]
    pending_exits: tuple[PendingExitFact, ...]
    valuations: tuple[ValuationFact, ...]
    marks: tuple[MarkFact, ...]
    fees: FeeTotalsFact
    orders: tuple[OrderFact, ...]
    event_count: int
    trade_count: int
    source_token: SourceToken
    source_root: str
    section_roots: Mapping[str, str]


def _sidecar_digest(path: Path, name: str) -> str:
    sidecar = path.parent / f"{path.name}{name}"
    if not sidecar.exists():
        return "0" * 64
    import hashlib

    return hashlib.sha256(sidecar.read_bytes()).hexdigest()


def capture_v2_inventory(
    path: Path | str,
    *,
    ledger_id: str,
    captured_at: datetime | None = None,
) -> V2Inventory:
    """只读捕获 v2 ledger 全部资本状态; 任何不可表示事实即阻断.

    只读性质: 源库以 ``mode=ro&immutable=1`` 打开; 若仍有 WAL/SHM sidecar
    存在, 内容哈希绑定 sidecar 摘要并要求捕获期间恒定 — 永不以可写方式
    checkpoint 源库.
    """

    source = Path(path)
    _require_regular_source(source)
    captured = captured_at or datetime.now(timezone.utc)
    if captured.tzinfo is not timezone.utc:
        raise InventoryError(
            UNREPRESENTABLE_FACT, "captured_at must be exactly UTC"
        )

    main_bytes = source.read_bytes()
    wal_before = _sidecar_digest(source, "-wal")
    shm_before = _sidecar_digest(source, "-shm")

    uri = f"file:{source.resolve()}?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        raise InventoryError(NON_REGULAR_SOURCE, str(exc)) from exc
    try:
        conn.row_factory = sqlite3.Row
        _require_known_tables(conn)
        meta = _read_meta(conn, ledger_id)
        facts = {
            "cash": _read_cash(conn, meta),
            "positions": _read_positions(conn),
            "plans": _read_plans(conn),
            "pending_exits": _read_pending_exits(conn),
            "valuations": _read_valuations(conn),
            "marks": _read_marks(conn),
            "fees": _read_fees(conn),
            "orders": (),
        }
        event_count = _scalar(conn, "SELECT COUNT(*) FROM trade_events")
        trade_count = _scalar(conn, "SELECT COUNT(*) FROM trades")
    finally:
        conn.close()

    if source.read_bytes() != main_bytes:
        raise InventoryError(
            UNREPRESENTABLE_FACT,
            "source ledger changed during read-only capture",
        )
    if (
        _sidecar_digest(source, "-wal") != wal_before
        or _sidecar_digest(source, "-shm") != shm_before
    ):
        raise InventoryError(
            UNREPRESENTABLE_FACT,
            "source ledger WAL/SHM changed during read-only capture",
        )

    import hashlib

    section_roots = {
        name: content_hash(_section_payload(name, value))
        for name, value in facts.items()
    }
    section_roots["meta"] = content_hash(
        {
            "ledger_id": meta.ledger_id,
            "schema_version": meta.schema_version,
            "initial_cash": meta.initial_cash,
        }
    )
    section_roots["counts"] = content_hash(
        {"event_count": event_count, "trade_count": trade_count}
    )
    source_root = domain_hash(
        _SOURCE_ROOT_DOMAIN, 2, dict(sorted(section_roots.items()))
    )
    token = SourceToken(
        ledger_id=meta.ledger_id,
        schema_version=meta.schema_version,
        root=source_root,
        captured_at=captured,
    )
    return V2Inventory(
        meta=meta,
        cash=facts["cash"],
        positions=facts["positions"],
        plans=facts["plans"],
        pending_exits=facts["pending_exits"],
        valuations=facts["valuations"],
        marks=facts["marks"],
        fees=facts["fees"],
        orders=facts["orders"],
        event_count=event_count,
        trade_count=trade_count,
        source_token=token,
        source_root=source_root,
        section_roots=dict(sorted(section_roots.items())),
    )


# ---------------------------------------------------------------------------
# 源文件守卫
# ---------------------------------------------------------------------------


def _require_regular_source(source: Path) -> None:
    if source.is_symlink() or os.path.islink(source):
        raise InventoryError(SYMLINK_SOURCE, f"{source} is a symlink")
    if not source.exists() or not source.is_file():
        raise InventoryError(NON_REGULAR_SOURCE, f"{source} is not a regular file")


def _require_known_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    unknown = sorted({row[0] for row in rows} - _KNOWN_TABLES)
    if unknown:
        raise InventoryError(
            UNREPRESENTABLE_FACT,
            f"unattributed writable tables outside v2 schema: {unknown}",
        )


# ---------------------------------------------------------------------------
# 逐项读取 (禁止默认/取整)
# ---------------------------------------------------------------------------


def _require(value: Any, field: str) -> Any:
    if value is None:
        raise InventoryError(UNREPRESENTABLE_FACT, f"NULL {field}")
    return value


def _price(value: Any, field: str) -> Decimal | None:
    """可空价格: None 合法 (未发生), 其余必须有限可表示."""

    if value is None:
        return None
    return _money(value, field)


def _money(value: Any, field: str) -> Decimal:
    import math

    raw = _require(value, field)
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise InventoryError(
            UNREPRESENTABLE_FACT, f"{field} not numeric: {raw!r}"
        )
    if isinstance(raw, float) and not math.isfinite(raw):
        raise InventoryError(UNREPRESENTABLE_FACT, f"{field} not finite")
    return Decimal(str(raw))


def _int(value: Any, field: str) -> int:
    raw = _require(value, field)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise InventoryError(
            UNREPRESENTABLE_FACT, f"{field} not an integer: {raw!r}"
        )
    return raw


def _text(value: Any, field: str) -> str:
    raw = _require(value, field)
    if not isinstance(raw, str):
        raise InventoryError(UNREPRESENTABLE_FACT, f"{field} not text")
    return raw


def _day(value: Any, field: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InventoryError(UNREPRESENTABLE_FACT, f"{field} not text date")
    return date.fromisoformat(value)


def _state(value: Any, trade_id: str) -> str:
    state = _text(value, f"trades.state[{trade_id}]")
    if state not in _TRADE_STATES:
        raise InventoryError(
            UNREPRESENTABLE_FACT,
            f"trades.state[{trade_id}] unknown state {state!r}",
        )
    return state


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def _read_meta(conn: sqlite3.Connection, ledger_id: str) -> LedgerMetaFact:
    row = conn.execute(
        "SELECT ledger_id, schema_version, initial_cash, created_at "
        "FROM ledger_meta"
    ).fetchone()
    if row is None:
        raise InventoryError(UNREPRESENTABLE_FACT, "ledger_meta is empty")
    actual = _text(row["ledger_id"], "ledger_meta.ledger_id")
    if actual != ledger_id:
        raise InventoryError(
            LEDGER_MISMATCH, f"expected ledger {ledger_id!r}, found {actual!r}"
        )
    return LedgerMetaFact(
        ledger_id=actual,
        schema_version=_int(row["schema_version"], "ledger_meta.schema_version"),
        initial_cash=_money(row["initial_cash"], "ledger_meta.initial_cash"),
        created_at=_text(row["created_at"], "ledger_meta.created_at"),
    )


def _read_cash(conn: sqlite3.Connection, meta: LedgerMetaFact) -> CashFact:
    delta_sum = _money(
        conn.execute(
            "SELECT COALESCE(SUM(cash_delta), 0) FROM trade_events"
        ).fetchone()[0],
        "sum(trade_events.cash_delta)",
    )
    return CashFact(
        initial_cash=meta.initial_cash,
        event_cash_delta_sum=delta_sum,
        cash_balance=meta.initial_cash + delta_sum,
    )


def _trade_rows(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM trades ORDER BY trade_id"
    ).fetchall()


def _read_positions(conn: sqlite3.Connection) -> tuple[PositionFact, ...]:
    facts: list[PositionFact] = []
    for row in _trade_rows(conn):
        trade_id = _text(row["trade_id"], "trades.trade_id")
        state = _state(row["state"], trade_id)
        if state not in ("open", "exit_pending"):
            continue
        facts.append(
            PositionFact(
                trade_id=trade_id,
                ticker=_text(row["ticker"], f"ticker[{trade_id}]"),
                setup=_text(row["setup"], f"setup[{trade_id}]"),
                state=state,  # type: ignore[arg-type]
                quantity=_int(row["quantity"], f"quantity[{trade_id}]"),
                entry_date=_day(row["entry_date"], f"entry_date[{trade_id}]"),
                raw_entry_price=_price(
                    row["raw_entry_price"], f"raw_entry_price[{trade_id}]"
                ),
            )
        )
    return tuple(facts)


def _read_plans(conn: sqlite3.Connection) -> tuple[PlanFact, ...]:
    facts: list[PlanFact] = []
    for row in _trade_rows(conn):
        trade_id = _text(row["trade_id"], "trades.trade_id")
        if _state(row["state"], trade_id) != "planned":
            continue
        provenance = _text(
            row["provenance_json"], f"provenance_json[{trade_id}]"
        )
        try:
            json.loads(provenance)
        except json.JSONDecodeError as exc:
            raise InventoryError(
                UNREPRESENTABLE_FACT,
                f"provenance_json[{trade_id}] not JSON: {exc}",
            ) from exc
        facts.append(
            PlanFact(
                trade_id=trade_id,
                ticker=_text(row["ticker"], f"ticker[{trade_id}]"),
                setup=_text(row["setup"], f"setup[{trade_id}]"),
                setup_version=_text(
                    row["setup_version"], f"setup_version[{trade_id}]"
                ),
                signal_date=_day(
                    row["signal_date"], f"signal_date[{trade_id}]"
                ),  # type: ignore[arg-type]
                planned_entry_date=_day(
                    row["planned_entry_date"], f"planned_entry_date[{trade_id}]"
                ),  # type: ignore[arg-type]
                planned_weight=_money(
                    row["planned_weight"], f"planned_weight[{trade_id}]"
                ),
                priority=_int(row["priority"], f"priority[{trade_id}]"),
                provenance_json=provenance,
            )
        )
    return tuple(facts)


def _read_pending_exits(conn: sqlite3.Connection) -> tuple[PendingExitFact, ...]:
    facts: list[PendingExitFact] = []
    for row in _trade_rows(conn):
        trade_id = _text(row["trade_id"], "trades.trade_id")
        if _state(row["state"], trade_id) != "exit_pending":
            continue
        defer_count = _scalar(
            conn,
            "SELECT COUNT(*) FROM trade_events WHERE trade_id='"
            + trade_id.replace("'", "''")
            + "' AND event_type='EXIT_DEFERRED'",
        )
        facts.append(
            PendingExitFact(
                trade_id=trade_id,
                ticker=_text(row["ticker"], f"ticker[{trade_id}]"),
                exit_trigger_date=_day(
                    row["exit_trigger_date"], f"exit_trigger_date[{trade_id}]"
                ),
                forced_exit_target_date=_day(
                    row["forced_exit_target_date"],
                    f"forced_exit_target_date[{trade_id}]",
                ),
                defer_count=defer_count,
            )
        )
    return tuple(facts)


def _read_valuations(conn: sqlite3.Connection) -> tuple[ValuationFact, ...]:
    rows = conn.execute(
        "SELECT * FROM daily_valuations ORDER BY trade_date"
    ).fetchall()
    facts: list[ValuationFact] = []
    for row in rows:
        trade_date = _day(row["trade_date"], "daily_valuations.trade_date")
        stale_raw = _require(
            row["stale_tickers_json"], f"stale_tickers_json[{trade_date}]"
        )
        try:
            stale = tuple(sorted(json.loads(stale_raw)))
        except json.JSONDecodeError as exc:
            raise InventoryError(
                UNREPRESENTABLE_FACT, f"stale_tickers not JSON: {exc}"
            ) from exc
        facts.append(
            ValuationFact(
                trade_date=trade_date,  # type: ignore[arg-type]
                cash=_money(row["cash"], f"cash[{trade_date}]"),
                market_value=_money(
                    row["market_value"], f"market_value[{trade_date}]"
                ),
                nav=_money(row["nav"], f"nav[{trade_date}]"),
                peak=_money(row["peak"], f"peak[{trade_date}]"),
                drawdown=_money(row["drawdown"], f"drawdown[{trade_date}]"),
                stale_tickers=stale,
            )
        )
    return tuple(facts)


def _read_marks(conn: sqlite3.Connection) -> tuple[MarkFact, ...]:
    rows = conn.execute(
        "SELECT trade_id, trade_date, close_price FROM position_marks "
        "ORDER BY trade_id, trade_date"
    ).fetchall()
    return tuple(
        MarkFact(
            trade_id=_text(row["trade_id"], "position_marks.trade_id"),
            trade_date=_day(
                row["trade_date"], "position_marks.trade_date"
            ),  # type: ignore[arg-type]
            close_price=_money(row["close_price"], "position_marks.close_price"),
        )
        for row in rows
    )


def _read_fees(conn: sqlite3.Connection) -> FeeTotalsFact:
    totals: dict[str, Decimal] = {}
    for field in _COST_FIELDS:
        value = conn.execute(
            f"SELECT COALESCE(SUM({field}), 0) FROM trades"
        ).fetchone()[0]
        totals[field] = _money(value, f"sum(trades.{field})")
    for row in _trade_rows(conn):
        trade_id = _text(row["trade_id"], "trades.trade_id")
        for field in _COST_FIELDS:
            if row[field] is None:
                raise InventoryError(
                    UNREPRESENTABLE_FACT, f"NULL {field} on trade {trade_id}"
                )
    return FeeTotalsFact(**totals)


def _section_payload(name: str, value: Any) -> Any:
    if name == "cash":
        return {"cash": value}
    return {name: list(value) if isinstance(value, tuple) else value}
