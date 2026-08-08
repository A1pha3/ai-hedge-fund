"""Plan 06 迁移域模型 (Task 1): 只读盘点与批准验证共用的不可变值对象.

全部为 CanonicalModel (strict + frozen + extra="forbid"): 与 v3 契约层一致的
规范化序列化/哈希语义, Decimal 表示金额, 禁止 float 进入 canonical JSON.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    ExactInteger,
    Sha256,
    UtcInstant,
)


class LedgerMetaFact(CanonicalModel):
    """v2 ledger_meta 行的盘点快照."""

    ledger_id: str
    schema_version: ExactInteger
    initial_cash: Decimal
    created_at: str


class CashFact(CanonicalModel):
    """现金三节对照: 事件流导出余额必须等于独立重算."""

    initial_cash: Decimal
    event_cash_delta_sum: Decimal
    cash_balance: Decimal
    derivation: Literal["initial_cash+sum(trade_events.cash_delta)"] = (
        "initial_cash+sum(trade_events.cash_delta)"
    )


class PositionFact(CanonicalModel):
    """一个 open/exit_pending 仓位 lot (v2 无 tradable/receivable 拆分)."""

    trade_id: str
    ticker: str
    setup: str
    state: Literal["open", "exit_pending"]
    quantity: ExactInteger = Field(ge=0)
    entry_date: date | None
    raw_entry_price: Decimal | None


class PlanFact(CanonicalModel):
    """一个 planned 计划行 (v2 的隐含资本预留)."""

    trade_id: str
    ticker: str
    setup: str
    setup_version: str
    signal_date: date
    planned_entry_date: date
    planned_weight: Decimal
    priority: ExactInteger
    provenance_json: str


class PendingExitFact(CanonicalModel):
    """一个 exit_pending 仓位及其退出状态."""

    trade_id: str
    ticker: str
    state: Literal["exit_pending"] = "exit_pending"
    exit_trigger_date: date | None
    forced_exit_target_date: date | None
    defer_count: ExactInteger = Field(ge=0)


class ValuationFact(CanonicalModel):
    trade_date: date
    cash: Decimal
    market_value: Decimal
    nav: Decimal
    peak: Decimal
    drawdown: Decimal
    stale_tickers: tuple[str, ...]


class MarkFact(CanonicalModel):
    trade_id: str
    trade_date: date
    close_price: Decimal


class FeeTotalsFact(CanonicalModel):
    """六列费用合计 (entry/exit 各自的 commission/tax/slippage)."""

    entry_commission: Decimal
    entry_tax: Decimal
    entry_slippage: Decimal
    exit_commission: Decimal
    exit_tax: Decimal
    exit_slippage: Decimal


class OrderFact(CanonicalModel):
    """v3 侧 live/ambiguous/cancel-pending 订单的盘点行 (v2 恒为空)."""

    order_id: str
    classification: Literal["live", "ambiguous", "cancel_pending"]
    trade_id: str | None
    quantity: ExactInteger = Field(ge=0)


class SourceToken(CanonicalModel):
    """盘点输出的不可伪造引用: 绑定 ledger 身份与逐项 source root."""

    ledger_id: str
    schema_version: ExactInteger
    root: Sha256
    captured_at: UtcInstant

    @property
    def token_hash(self) -> str:
        import hashlib

        return hashlib.sha256(self.canonical_bytes()).hexdigest()
