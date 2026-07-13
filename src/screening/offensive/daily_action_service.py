from __future__ import annotations

import math
import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.data_quality_manifest import (
    RunManifest,
    TickerReadiness,
    validate_ticker_readiness,
)
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
SETUP_HOLDING_SESSIONS = {"btst_breakout": 10}


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
    completed_exits: tuple[ActionItem, ...]
    open_exposure: float
    reserved_exposure: float
    block_reason: str | None = None
    blocked_tickers: tuple[str, ...] = ()


PriceProvider = Callable[[str, date], MarketBar | None]
CacheFingerprintProvider = Callable[[str, date], str | None]


def _plain_date(value: object) -> date:
    if type(value) is not str:
        raise ValueError("manifest date must be a string")
    return datetime.strptime(value, "%Y-%m-%d").date()


def _deserialize_readiness(ticker: str, value: object) -> TickerReadiness:
    if not isinstance(value, Mapping) or value.get("ticker") != ticker:
        raise ValueError("manifest ticker mapping is invalid")
    history_days = value.get("fund_flow_history_days")
    trade_ready = value.get("trade_ready")
    block_reasons = value.get("block_reasons")
    if (
        type(history_days) is not int
        or type(trade_ready) is not bool
        or not isinstance(block_reasons, list)
        or any(type(reason) is not str for reason in block_reasons)
    ):
        raise ValueError("manifest readiness types are invalid")

    def optional_date(field: str) -> date | None:
        raw = value.get(field)
        return None if raw is None else _plain_date(raw)

    readiness = TickerReadiness(
        ticker=ticker,
        trade_date=_plain_date(value.get("trade_date")),
        ohlcv_date=optional_date("ohlcv_date"),
        ohlcv_finite=value.get("ohlcv_finite"),
        fund_flow_date=optional_date("fund_flow_date"),
        fund_flow_history_days=history_days,
        industry_date=optional_date("industry_date"),
        security_status=value.get("security_status"),
        st_status=value.get("st_status"),
        board_rule_version=value.get("board_rule_version"),
        cache_fingerprint=value.get("cache_fingerprint"),
        trade_ready=trade_ready,
        block_reasons=tuple(block_reasons),
    )
    validated = validate_ticker_readiness(
        ticker=readiness.ticker,
        trade_date=readiness.trade_date,
        ohlcv_date=readiness.ohlcv_date,
        ohlcv_finite=readiness.ohlcv_finite,
        fund_flow_date=readiness.fund_flow_date,
        fund_flow_history_days=readiness.fund_flow_history_days,
        industry_date=readiness.industry_date,
        security_status=readiness.security_status,
        st_status=readiness.st_status,
        board_rule_version=readiness.board_rule_version,
        cache_fingerprint=readiness.cache_fingerprint,
    )
    if (
        readiness.trade_ready != validated.trade_ready
        or readiness.block_reasons != validated.block_reasons
    ):
        raise ValueError("serialized readiness does not match validator")
    return readiness


def _deserialize_canonical_manifest(payload: object, as_of: date) -> RunManifest:
    from src.screening.auto_pipeline import _canonical_fingerprint

    if not isinstance(payload, Mapping):
        raise ValueError("canonical payload must be an object")
    compact_date = as_of.strftime("%Y%m%d")
    embedded = payload.get("manifest")
    if (
        payload.get("date") != compact_date
        or payload.get("status") != "healthy"
        or type(payload.get("run_id")) is not str
        or not isinstance(embedded, Mapping)
        or embedded.get("run_id") != payload.get("run_id")
        or embedded.get("trade_date") != compact_date
        or embedded.get("status") != "healthy"
        or embedded.get("is_healthy") is not True
        or type(embedded.get("input_fingerprint")) is not str
        or not embedded.get("input_fingerprint")
    ):
        raise ValueError("canonical manifest identity mismatch")
    created_at = datetime.fromisoformat(str(embedded.get("created_at") or ""))
    if created_at.tzinfo is None:
        raise ValueError("manifest created_at must be timezone-aware")
    candidate_tickers = embedded.get("candidate_tickers")
    ticker_values = embedded.get("tickers")
    if (
        not isinstance(candidate_tickers, list)
        or any(type(ticker) is not str or not ticker for ticker in candidate_tickers)
        or len(set(candidate_tickers)) != len(candidate_tickers)
        or not isinstance(ticker_values, Mapping)
        or set(candidate_tickers) != set(ticker_values)
        or embedded.get("candidate_set_fingerprint")
        != _canonical_fingerprint(list(candidate_tickers))
    ):
        raise ValueError("canonical candidate identity mismatch")
    pool = payload.get("candidate_pool_run")
    if (
        not isinstance(pool, Mapping)
        or pool.get("trade_date") != compact_date
        or pool.get("tickers") != candidate_tickers
    ):
        raise ValueError("canonical candidate pool mismatch")
    tickers = {
        ticker: _deserialize_readiness(ticker, ticker_values[ticker])
        for ticker in candidate_tickers
    }
    if any(readiness.trade_date != as_of for readiness in tickers.values()):
        raise ValueError("ticker readiness date mismatch")
    return RunManifest(
        run_id=str(embedded["run_id"]),
        trade_date=as_of,
        status="healthy",
        created_at=created_at,
        tickers=tickers,
        candidate_tickers=tuple(candidate_tickers),
        candidate_set_fingerprint=str(embedded["candidate_set_fingerprint"]),
        candidate_snapshot_fingerprint=embedded.get("candidate_snapshot_fingerprint"),
        admission_projection_fingerprint=embedded.get("admission_projection_fingerprint"),
        baseline_fingerprint=embedded.get("baseline_fingerprint"),
        industry_content_fingerprint=embedded.get("industry_content_fingerprint"),
        input_fingerprint=str(embedded["input_fingerprint"]),
    )


def load_daily_action_manifest_gate(
    as_of: date,
    *,
    reports_dir: Path = Path("data/reports"),
) -> tuple[RunManifest | None, Mapping[str, str | None]]:
    """Load only the exact-date healthy canonical and re-fingerprint its caches."""
    try:
        payload = json.loads(
            (reports_dir / f"auto_screening_{as_of:%Y%m%d}.json").read_text(
                encoding="utf-8"
            )
        )
        manifest = _deserialize_canonical_manifest(payload, as_of)
        pool = payload["candidate_pool_run"]
        candidates = pool.get("candidates")
        if (
            not isinstance(candidates, list)
            or any(not isinstance(row, Mapping) for row in candidates)
            or [row.get("ticker") for row in candidates]
            != list(manifest.candidate_tickers)
        ):
            raise ValueError("candidate rows missing")
        industries = {
            str(row.get("ticker") or ""): str(
                row.get("industry_sw") or row.get("industry") or ""
            ).strip()
            for row in candidates
            if isinstance(row, Mapping)
        }
        from src.screening.auto_pipeline import (
            _capture_input_snapshot,
            _combined_fingerprint,
        )

        snapshot = _capture_input_snapshot(
            as_of.strftime("%Y%m%d"),
            reports_dir=reports_dir,
            cache_refresh_summary={},
            candidate_tickers=manifest.candidate_tickers,
            ticker_industries=industries,
        )
        fingerprints: dict[str, str | None] = {}
        for ticker in manifest.candidate_tickers:
            ticker_snapshot = snapshot.tickers.get(ticker)
            industry_snapshot = snapshot.industries.get(industries.get(ticker, ""))
            fingerprints[ticker] = _combined_fingerprint(
                ticker_snapshot.price_fingerprint if ticker_snapshot else None,
                ticker_snapshot.fund_flow_fingerprint if ticker_snapshot else None,
                industry_snapshot.fingerprint if industry_snapshot else None,
            )
        return manifest, MappingProxyType(fingerprints)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None, {}


class DailyActionService:
    def __init__(
        self,
        repository: LedgerRepository,
        calendar: TradingSessionCalendar,
        prices: PriceProvider,
        costs: ExecutionCosts,
        cache_fingerprints: CacheFingerprintProvider | None = None,
        *,
        enforce_manifest_gate: bool = True,
    ) -> None:
        self.repository, self.calendar, self.prices, self.costs = (
            repository,
            calendar,
            prices,
            costs,
        )
        self.cache_fingerprints = cache_fingerprints
        self.enforce_manifest_gate = enforce_manifest_gate
        self._skipped: list[ActionItem] = []
        self._exit_plans: list[ActionItem] = []
        self._deferred: list[ActionItem] = []
        self._block_reason: str | None = None
        self._blocked_tickers: tuple[str, ...] = ()

    def run(
        self,
        as_of: date,
        candidates: Sequence[PlanCandidate],
        manifest: RunManifest | None = None,
    ) -> DailyActionRun:
        self._skipped, self._exit_plans, self._deferred, self._block_reason = (
            [],
            [],
            [],
            None,
        )
        self._blocked_tickers = ()
        self._settle_due_entry_plans(as_of)
        exits = self._settle_due_exit_plans(as_of)
        valuation = self._mark_to_market(as_of)
        self._evaluate_open_positions(as_of)
        eligible = self._manifest_eligible_candidates(as_of, candidates, manifest)
        if self.enforce_manifest_gate and not eligible:
            plans = ()
        else:
            plans = self._create_capacity_safe_plans(as_of, eligible, valuation)
        return self._build_view(as_of, valuation, exits, plans)

    def _manifest_eligible_candidates(
        self,
        as_of: date,
        candidates: Sequence[PlanCandidate],
        manifest: RunManifest | None,
    ) -> tuple[PlanCandidate, ...]:
        # Lifecycle-only tests may disable admission enforcement explicitly;
        # production defaults to the fail-closed path.
        if not self.enforce_manifest_gate:
            return tuple(candidates)
        candidate_tickers = tuple(dict.fromkeys(item.ticker for item in candidates))
        if not isinstance(manifest, RunManifest) or not manifest.is_healthy:
            self._block_reason = "healthy_manifest_missing"
            self._blocked_tickers = candidate_tickers
            return ()
        if (
            manifest.trade_date != as_of
            or not manifest.run_id
            or not manifest.input_fingerprint
        ):
            self._block_reason = "manifest_identity_mismatch"
            self._blocked_tickers = candidate_tickers
            return ()

        eligible: list[PlanCandidate] = []
        blocked: list[str] = []
        for candidate in candidates:
            readiness = manifest.tickers.get(candidate.ticker)
            current_fingerprint = (
                self.cache_fingerprints(candidate.ticker, as_of)
                if self.cache_fingerprints is not None
                else None
            )
            if (
                readiness is None
                or readiness.ticker != candidate.ticker
                or readiness.trade_date != as_of
                or readiness.trade_ready is not True
                or not readiness.cache_fingerprint
                or current_fingerprint != readiness.cache_fingerprint
            ):
                if candidate.ticker not in blocked:
                    blocked.append(candidate.ticker)
                continue
            eligible.append(candidate)
        self._blocked_tickers = tuple(blocked)
        return tuple(eligible)

    def _settle_due_entry_plans(self, as_of: date) -> None:
        if not self.calendar.contains_session(as_of):
            return
        for plan in self.repository.planned_trades(as_of):
            current = self.repository.get_trade(plan.trade_id)
            if current.state is not TradeState.PLANNED:
                continue
            if not self._has_holding_horizon(plan.setup, plan.planned_entry_date):
                self._block_reason = "calendar_unavailable"
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
                self._block_reason = "calendar_unavailable"
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
        required_setups = {candidate.setup for candidate in candidates}
        if any(
            not self._has_holding_horizon(setup, entry_date)
            for setup in required_setups
        ):
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
            exits,
            sum(values.values()) / valuation.nav,
            sum(p.planned_weight for p in self.repository.planned_trades()),
            self._block_reason,
            self._blocked_tickers,
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
                self.repository.record_position_mark(trade.trade_id, as_of, price)
            else:
                stale.append(trade.ticker)
                price = (
                    self.repository.latest_position_mark(trade.trade_id, as_of)
                    or trade.raw_entry_price
                    or 0.0
                )
            values[trade.ticker] = (
                values.get(trade.ticker, 0.0) + price * trade.quantity
            )
        nav = self.repository.cash_balance() + sum(values.values())
        return nav, values, stale

    def _has_holding_horizon(self, setup: str, entry_date: date) -> bool:
        required = SETUP_HOLDING_SESSIONS.get(setup)
        if required is None:
            raise ValueError(f"missing holding-session policy for setup={setup}")
        try:
            self.calendar.nth_holding_session(entry_date, required)
            return True
        except ValueError:
            return False

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
