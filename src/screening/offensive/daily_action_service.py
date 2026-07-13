from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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
    simulation_label: str = "模拟盘"
    regime_size_factor: float = 1.0


@dataclass(frozen=True)
class ActionItem:
    trade_id: str
    ticker: str
    reason: str
    simulation_label: str = "模拟盘"


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
        self.repository = repository
        self.calendar = calendar
        self.prices = prices
        self.costs = costs
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
        reserved = 0.0
        for trade in self.repository.open_trades():
            reserved += self._position_weight(trade, as_of)
        for plan in self.repository.planned_trades(as_of):
            if reserved + plan.planned_weight > PORTFOLIO_CAP + 1e-12:
                self.repository.skip_plan(plan.trade_id, as_of, "portfolio_capacity")
                self._skipped.append(
                    ActionItem(plan.trade_id, plan.ticker, "portfolio_capacity")
                )
                continue
            bar = self.prices(plan.ticker, as_of)
            status = self._status(bar)
            if (
                status is not ExecutionStatus.EXECUTABLE_PROXY
                or bar is None
                or bar.open is None
            ):
                reserved += plan.planned_weight
                continue
            quantity = self._affordable_quantity(plan.planned_weight, bar.open)
            if quantity == 0:
                self.repository.skip_plan(plan.trade_id, as_of, "cash_capacity")
                self._skipped.append(
                    ActionItem(plan.trade_id, plan.ticker, "cash_capacity")
                )
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
            reserved += plan.planned_weight

    def _settle_due_exit_plans(self, as_of: date) -> tuple[ActionItem, ...]:
        settled: list[ActionItem] = []
        for trade in self.repository.open_trades():
            if trade.state is not TradeState.EXIT_PENDING:
                continue
            if (
                trade.forced_exit_target_date is not None
                and as_of < trade.forced_exit_target_date
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
                item = ActionItem(trade.trade_id, trade.ticker, reason)
                self._deferred.append(item)
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
            settled.append(ActionItem(trade.trade_id, trade.ticker, "exit_filled"))
        return tuple(settled)

    def _mark_to_market(self, as_of: date) -> DailyValuation:
        cash = self.repository.cash_balance()
        market_value = 0.0
        stale: list[str] = []
        previous = self.repository.latest_valuation()
        for trade in self.repository.open_trades():
            bar = self.prices(trade.ticker, as_of)
            if bar is None or bar.close is None or bar.close <= 0:
                stale.append(trade.ticker)
                price = trade.raw_entry_price or 0.0
            else:
                price = bar.close
            market_value += price * trade.quantity
        nav = cash + market_value
        peak = max(previous.peak if previous else self.repository.initial_cash, nav)
        drawdown = nav / peak - 1.0
        self.repository.record_valuation(
            as_of, cash, market_value, nav, peak, drawdown, stale
        )
        return DailyValuation(
            as_of, cash, market_value, nav, peak, drawdown, tuple(sorted(stale))
        )

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
                self._exit_plans.append(
                    ActionItem(trade.trade_id, trade.ticker, "maximum_holding_session")
                )

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
        open_weight = (
            self._open_market_value(as_of) / valuation.nav if valuation.nav else 0.0
        )
        reserved = sum(plan.planned_weight for plan in self.repository.planned_trades())
        created: list[ActionItem] = []
        for candidate in sorted(
            candidates, key=lambda item: (item.priority, item.ticker)
        ):
            normal_weight = min(max(candidate.target_weight, 0.0), NORMAL_STOCK_CAP)
            weight = min(
                normal_weight * max(candidate.regime_size_factor, 0.0), HARD_STOCK_CAP
            )
            if weight <= 0 or open_weight + reserved + weight > PORTFOLIO_CAP + 1e-12:
                continue
            trade = self.repository.create_plan(
                candidate.ticker,
                candidate.setup,
                candidate.setup_version,
                as_of,
                entry_date,
                weight,
                candidate.priority,
            )
            reserved += weight
            created.append(
                ActionItem(
                    trade.trade_id,
                    trade.ticker,
                    "entry_planned",
                    candidate.simulation_label,
                )
            )
        return tuple(created)

    def _build_view(
        self,
        as_of: date,
        valuation: DailyValuation,
        exits: tuple[ActionItem, ...],
        plans: tuple[ActionItem, ...],
    ) -> DailyActionRun:
        positions = tuple(self.repository.open_trades())
        open_exposure = (
            self._open_market_value(as_of) / valuation.nav if valuation.nav else 0.0
        )
        reserved = sum(plan.planned_weight for plan in self.repository.planned_trades())
        return DailyActionRun(
            as_of,
            valuation,
            positions,
            plans,
            tuple(self._skipped),
            tuple(self._exit_plans),
            tuple(self._deferred),
            open_exposure,
            reserved,
            self._block_reason,
        )

    def _affordable_quantity(self, weight: float, price: float) -> int:
        target = self.repository.initial_cash * weight
        cash = self.repository.cash_balance()
        quantity = int(min(target, cash) // (price * LOT_SIZE)) * LOT_SIZE
        while quantity > 0:
            fill = apply_execution_costs(price, quantity, "buy", self.costs)
            if -fill.net_cash_flow <= cash and -fill.net_cash_flow <= target:
                return quantity
            quantity -= LOT_SIZE
        return 0

    def _open_market_value(self, as_of: date) -> float:
        total = 0.0
        for trade in self.repository.open_trades():
            bar = self.prices(trade.ticker, as_of)
            price = (
                bar.close
                if bar is not None and bar.close is not None
                else trade.raw_entry_price
            )
            total += (price or 0.0) * trade.quantity
        return total

    def _position_weight(self, trade: LedgerTrade, as_of: date) -> float:
        return (
            self._open_market_value_for_trade(trade, as_of)
            / self.repository.initial_cash
        )

    def _open_market_value_for_trade(self, trade: LedgerTrade, as_of: date) -> float:
        bar = self.prices(trade.ticker, as_of)
        price = (
            bar.close
            if bar is not None and bar.close is not None
            else trade.raw_entry_price
        )
        return (price or 0.0) * trade.quantity

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
