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
