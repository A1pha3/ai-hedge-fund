from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Callable, Sequence

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.execution_adjuster import (
    ExecutionCosts,
    ExecutionStatus,
    apply_execution_costs,
    classify_open_fill,
)
from src.screening.offensive.ledger_repository import (
    DailyValuation,
    LedgerRepository,
    LedgerTrade,
)
from src.screening.offensive.trade_lifecycle import (
    ExecutionMode,
    FillSource,
    TradeState,
)

PORTFOLIO_CAP = 0.60
NORMAL_STOCK_CAP = 0.10
HARD_STOCK_CAP = 0.12
LOT_SIZE = 100


class RegimeAuthorization(StrEnum):
    NORMAL = "normal"
    BTST_CRISIS = "btst_crisis"
    BTST_RISK_OFF = "btst_risk_off"

    @property
    def ticker_cap(self) -> float:
        return (
            NORMAL_STOCK_CAP if self is RegimeAuthorization.NORMAL else HARD_STOCK_CAP
        )


@dataclass(frozen=True)
class MarketBar:
    open: float | None
    close: float | None
    limit_down: float | None
    limit_up: float | None
    suspended: bool | None
    high: float | None = None
    low: float | None = None


@dataclass(frozen=True)
class PlanCandidate:
    ticker: str
    setup: str
    setup_version: str
    target_weight: float
    priority: int
    authorization: RegimeAuthorization = RegimeAuthorization.NORMAL

    def __post_init__(self) -> None:
        if self.setup != "btst_breakout":
            raise ValueError("only btst_breakout candidates are enabled")
        if not self.ticker or not self.setup_version:
            raise ValueError("ticker and setup_version must be nonempty")
        if not math.isfinite(self.target_weight) or self.target_weight <= 0:
            raise ValueError("target_weight must be finite and positive")
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or self.priority <= 0
        ):
            raise ValueError("priority must be a positive integer")
        if not isinstance(self.authorization, RegimeAuthorization):
            raise ValueError("authorization must be a RegimeAuthorization")


@dataclass(frozen=True)
class ActionItem:
    trade_id: str
    ticker: str
    reason: str
    execution_label: str
    source_label: str


@dataclass(frozen=True)
class DailyActionRun:
    trade_date: date
    valuation: DailyValuation
    open_positions: tuple[LedgerTrade, ...]
    new_plans: tuple[ActionItem, ...]
    skipped_plans: tuple[ActionItem, ...]
    exit_plans: tuple[ActionItem, ...]
    deferred_exits: tuple[ActionItem, ...]
    open_exposure: float
    reserved_exposure: float
    block_reason: str | None = None


PriceProvider = Callable[[str, date], MarketBar | None]


class DailyActionService:
    def __init__(
        self,
        repository: LedgerRepository,
        calendar: TradingSessionCalendar,
        prices: PriceProvider,
        costs: ExecutionCosts,
    ) -> None:
        self.repository, self.calendar, self.prices, self.costs = (
            repository,
            calendar,
            prices,
            costs,
        )
        self._skipped: list[ActionItem] = []
        self._exit_plans: list[ActionItem] = []
        self._deferred: list[ActionItem] = []
        self._block_reason: str | None = None

    def run(self, as_of: date, candidates: Sequence[PlanCandidate]) -> DailyActionRun:
        self._skipped, self._exit_plans, self._deferred, self._block_reason = (
            [],
            [],
            [],
            None,
        )
        self._settle_due_entry_plans(as_of)
        exits = self._settle_due_exit_plans(as_of)
        valuation = self._mark_to_market(as_of)
        self._evaluate_open_positions(as_of)
        plans = self._create_capacity_safe_plans(as_of, candidates, valuation)
        return self._build_view(as_of, valuation, exits, plans)

    def _settle_due_entry_plans(self, as_of: date) -> None:
        for plan in self.repository.planned_trades(as_of):
            current = self.repository.get_trade(plan.trade_id)
            if current.state is not TradeState.PLANNED:
                continue
            nav, values, _ = self._snapshot(as_of)
            higher = [
                p
                for p in self.repository.planned_trades()
                if (p.priority, p.trade_id) <= (plan.priority, plan.trade_id)
            ]
            reserved_through = sum(p.planned_weight for p in higher)
            ticker_reserved = sum(
                p.planned_weight for p in higher if p.ticker == plan.ticker
            )
            open_weight = sum(values.values()) / nav
            ticker_weight = values.get(plan.ticker, 0.0) / nav
            if open_weight + reserved_through > PORTFOLIO_CAP + 1e-12:
                self._skip(plan, as_of, "portfolio_capacity")
                continue
            ticker_cap = (
                HARD_STOCK_CAP
                if any(
                    p.ticker == plan.ticker and p.planned_weight > NORMAL_STOCK_CAP
                    for p in higher
                )
                else NORMAL_STOCK_CAP
            )
            if ticker_weight + ticker_reserved > ticker_cap + 1e-12:
                self._skip(plan, as_of, "ticker_capacity")
                continue
            bar = self.prices(plan.ticker, as_of)
            if (
                self._status(bar) is not ExecutionStatus.EXECUTABLE_PROXY
                or bar is None
                or bar.open is None
            ):
                continue
            quantity = self._affordable_quantity(plan.planned_weight, bar.open, nav)
            if quantity == 0:
                self._skip(plan, as_of, "cash_capacity")
                continue
            fill = apply_execution_costs(bar.open, quantity, "buy", self.costs)
            self.repository.fill_plan(
                plan.trade_id,
                ExecutionMode.PAPER,
                FillSource.SYNTHETIC_OPEN,
                as_of,
                fill.raw_fill_price,
                quantity,
                fill.commission + fill.other_fee,
                fill.tax,
                fill.slippage_cost,
            )

    def _settle_due_exit_plans(self, as_of: date) -> tuple[ActionItem, ...]:
        settled: list[ActionItem] = []
        for trade in self.repository.open_trades():
            if trade.state is not TradeState.EXIT_PENDING or (
                trade.forced_exit_target_date and as_of < trade.forced_exit_target_date
            ):
                continue
            bar = self.prices(trade.ticker, as_of)
            status = self._status(bar)
            if (
                status is not ExecutionStatus.EXECUTABLE_PROXY
                or bar is None
                or bar.open is None
            ):
                reason = (
                    "unknown_queue"
                    if status is ExecutionStatus.UNKNOWN_QUEUE
                    else "unexecutable_proxy"
                )
                self.repository.defer_exit(
                    trade.trade_id,
                    as_of,
                    forced_exit_target_date=trade.forced_exit_target_date,
                )
                self._deferred.append(self._item(trade, reason))
                continue
            fill = apply_execution_costs(
                bar.open,
                trade.quantity,
                "sell",
                self.costs,
                entry_date=trade.entry_date,
                exit_date=as_of,
            )
            self.repository.close_trade(
                trade.trade_id,
                as_of,
                fill.raw_fill_price,
                fill.commission + fill.other_fee,
                fill.tax,
                fill.slippage_cost,
            )
            settled.append(self._item(trade, "exit_filled"))
        return tuple(settled)

    def _mark_to_market(self, as_of: date) -> DailyValuation:
        nav, values, stale = self._snapshot(as_of)
        cash = self.repository.cash_balance()
        previous = self.repository.latest_valuation()
        peak = max(previous.peak if previous else self.repository.initial_cash, nav)
        valuation = DailyValuation(
            as_of,
            cash,
            sum(values.values()),
            nav,
            peak,
            nav / peak - 1.0,
            tuple(sorted(stale)),
        )
        self.repository.record_valuation(
            as_of,
            valuation.cash,
            valuation.market_value,
            valuation.nav,
            valuation.peak,
            valuation.drawdown,
            valuation.stale_tickers,
        )
        return valuation

    def _evaluate_open_positions(self, as_of: date) -> None:
        for trade in self.repository.open_trades():
            if trade.state is not TradeState.OPEN or trade.entry_date is None:
                continue
            try:
                session_nine = self.calendar.nth_holding_session(trade.entry_date, 9)
                target = self.calendar.nth_holding_session(trade.entry_date, 10)
            except ValueError:
                continue
            if as_of >= session_nine:
                self.repository.mark_exit_pending(
                    trade.trade_id, as_of, forced_exit_target_date=target
                )
                self._exit_plans.append(self._item(trade, "maximum_holding_session"))

    def _create_capacity_safe_plans(
        self,
        as_of: date,
        candidates: Sequence[PlanCandidate],
        valuation: DailyValuation,
    ) -> tuple[ActionItem, ...]:
        try:
            entry_date = self.calendar.next_session(as_of)
        except ValueError:
            self._block_reason = "calendar_unavailable"
            return ()
        _, values, _ = self._snapshot(as_of)
        reserved = list(self.repository.planned_trades())
        seen: set[str] = set()
        created_items: list[ActionItem] = []
        for candidate in sorted(
            candidates, key=lambda item: (item.priority, item.ticker)
        ):
            if candidate.ticker in seen:
                continue
            seen.add(candidate.ticker)
            weight = min(candidate.target_weight, candidate.authorization.ticker_cap)
            open_weight = sum(values.values()) / valuation.nav
            ticker_weight = values.get(candidate.ticker, 0.0) / valuation.nav
            ticker_reserved = sum(
                p.planned_weight for p in reserved if p.ticker == candidate.ticker
            )
            if (
                open_weight + sum(p.planned_weight for p in reserved) + weight
                > PORTFOLIO_CAP + 1e-12
            ):
                continue
            if (
                ticker_weight + ticker_reserved + weight
                > candidate.authorization.ticker_cap + 1e-12
            ):
                continue
            trade, created = self.repository.create_plan_if_absent(
                candidate.ticker,
                candidate.setup,
                candidate.setup_version,
                as_of,
                entry_date,
                weight,
                candidate.priority,
            )
            if created:
                reserved.append(trade)
                created_items.append(self._item(trade, "entry_planned"))
        return tuple(created_items)

    def _build_view(
        self,
        as_of: date,
        valuation: DailyValuation,
        exits: tuple[ActionItem, ...],
        plans: tuple[ActionItem, ...],
    ) -> DailyActionRun:
        positions = tuple(self.repository.open_trades())
        _, values, _ = self._snapshot(as_of)
        return DailyActionRun(
            as_of,
            valuation,
            positions,
            plans,
            tuple(self._skipped),
            tuple(self._exit_plans),
            tuple(self._deferred),
            sum(values.values()) / valuation.nav,
            sum(p.planned_weight for p in self.repository.planned_trades()),
            self._block_reason,
        )

    def _snapshot(self, as_of: date) -> tuple[float, dict[str, float], list[str]]:
        values: dict[str, float] = {}
        stale: list[str] = []
        for trade in self.repository.open_trades():
            bar = self.prices(trade.ticker, as_of)
            if (
                bar is not None
                and bar.close is not None
                and math.isfinite(bar.close)
                and bar.close > 0
            ):
                price = bar.close
                self.repository.record_position_mark(trade.ticker, as_of, price)
            else:
                stale.append(trade.ticker)
                price = (
                    self.repository.latest_position_mark(trade.ticker, as_of)
                    or trade.raw_entry_price
                    or 0.0
                )
            values[trade.ticker] = (
                values.get(trade.ticker, 0.0) + price * trade.quantity
            )
        nav = self.repository.cash_balance() + sum(values.values())
        return nav, values, stale

    def _affordable_quantity(self, weight: float, price: float, nav: float) -> int:
        target, cash = nav * weight, self.repository.cash_balance()
        quantity = int(min(target, cash) // (price * LOT_SIZE)) * LOT_SIZE
        while quantity > 0:
            fill = apply_execution_costs(price, quantity, "buy", self.costs)
            if -fill.net_cash_flow <= cash and -fill.net_cash_flow <= target:
                return quantity
            quantity -= LOT_SIZE
        return 0

    def _skip(self, plan: LedgerTrade, as_of: date, reason: str) -> None:
        self.repository.skip_plan(plan.trade_id, as_of, reason)
        self._skipped.append(self._item(plan, reason))

    @staticmethod
    def _item(trade: LedgerTrade, reason: str) -> ActionItem:
        execution = trade.execution_mode.value if trade.execution_mode else "pending"
        source = trade.fill_source.value if trade.fill_source else "pending"
        return ActionItem(trade.trade_id, trade.ticker, reason, execution, source)

    @staticmethod
    def _status(bar: MarketBar | None) -> ExecutionStatus:
        if bar is None:
            return ExecutionStatus.UNKNOWN_QUEUE
        return classify_open_fill(
            bar.open,
            bar.limit_down,
            bar.limit_up,
            bar.suspended,
            high=bar.high,
            low=bar.low,
        )
