from __future__ import annotations

import json
import math
import os
import stat
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from numbers import Real
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Callable, Mapping, Sequence

import pandas as pd

if TYPE_CHECKING:
    from src.screening.offensive.daily_action_snapshot import (
        VerifiedDailyActionSnapshot,
    )

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.data_quality_manifest import (
    RunManifest,
    TickerReadiness,
    validate_ticker_readiness,
)
from src.screening.offensive.atr_utils import compute_atr
from src.screening.offensive.execution_adjuster import (
    ExecutionCosts,
    ExecutionStatus,
    apply_execution_costs,
    classify_open_fill,
)
from src.screening.offensive.exit_policy import (
    ExitObservation,
    ExitPolicyState,
    evaluate_shadow_exit,
)
from src.screening.offensive.ledger_repository import (
    DailyValuation,
    LedgerRepository,
    LedgerTrade,
    PlanProvenance,
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
        return NORMAL_STOCK_CAP


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
    signal_date: date
    target_weight: float
    priority: int
    snapshot_id: str
    setup_consumed_fingerprint: str
    detector_degraded: bool = False
    authorization: RegimeAuthorization = RegimeAuthorization.NORMAL

    def __post_init__(self) -> None:
        if self.setup != "btst_breakout":
            raise ValueError("only btst_breakout candidates are enabled")
        if not self.ticker or not self.setup_version:
            raise ValueError("ticker and setup_version must be nonempty")
        if type(self.signal_date) is not date:
            raise ValueError("signal_date must be a date")
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise ValueError("snapshot_id must be nonempty")
        if not isinstance(self.setup_consumed_fingerprint, str) or not self.setup_consumed_fingerprint:
            raise ValueError("setup_consumed_fingerprint must be nonempty")
        if type(self.detector_degraded) is not bool:
            raise ValueError("detector_degraded must be bool")
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
class OpenPositionView(LedgerTrade):
    """Read-only ledger projection with fixed-policy shadow observations."""

    shadow_exit_line: float | None
    shadow_would_exit_next_open: bool
    shadow_reason: str


@dataclass(frozen=True)
class TickerGateBlock:
    ticker: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DailyActionRun:
    trade_date: date
    valuation: DailyValuation
    open_positions: tuple[OpenPositionView, ...]
    new_plans: tuple[ActionItem, ...]
    skipped_plans: tuple[ActionItem, ...]
    exit_plans: tuple[ActionItem, ...]
    deferred_exits: tuple[ActionItem, ...]
    completed_exits: tuple[ActionItem, ...]
    open_exposure: float
    reserved_exposure: float
    block_reason: str | None = None
    blocked_tickers: tuple[str, ...] = ()
    block_reasons: tuple[str, ...] = ()
    ticker_gate_blocks: tuple[TickerGateBlock, ...] = ()


@dataclass(frozen=True)
class LifecycleContext:
    """Settled ledger lifecycle output produced before any new-entry work.

    Settlement, valuation, and open-position evaluation run in
    ``advance_lifecycle`` so due exits always complete even when readiness,
    snapshot loading, or scanning fails. ``complete_run`` consumes this to build
    the final view without re-touching the ledger lifecycle.
    """

    as_of: date
    valuation: DailyValuation
    completed_exits: tuple[ActionItem, ...]


PriceProvider = Callable[[str, date], MarketBar | None]
CacheFingerprintProvider = Callable[[str, date], str | None]
ShadowPriceSource = PriceProvider | Mapping[object, object] | pd.DataFrame
ShadowHistoryProvider = Callable[[str], pd.DataFrame | None]


def _read_exact_regular_json(reports_dir: Path, filename: str) -> object:
    """Read one stable regular file without following filesystem indirection."""
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(
            reports_dir,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        file_fd = os.open(
            filename,
            os.O_RDONLY
            | os.O_NONBLOCK
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        held = os.fstat(file_fd)
        if not stat.S_ISREG(held.st_mode):
            raise ValueError("canonical target must be a regular file")

        def entry_matches() -> bool:
            entry = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
            return stat.S_ISREG(entry.st_mode) and (
                entry.st_dev,
                entry.st_ino,
            ) == (held.st_dev, held.st_ino)

        if not entry_matches():
            raise ValueError("canonical target identity changed before read")
        chunks: list[bytes] = []
        while chunk := os.read(file_fd, 65536):
            chunks.append(chunk)
        if not entry_matches():
            raise ValueError("canonical target identity changed during read")
        return json.loads(b"".join(chunks).decode("utf-8"))
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


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
        or not candidate_tickers
        or any(type(ticker) is not str or not ticker for ticker in candidate_tickers)
        or len(set(candidate_tickers)) != len(candidate_tickers)
        or not isinstance(ticker_values, Mapping)
        or not ticker_values
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
        payload = _read_exact_regular_json(
            reports_dir,
            f"auto_screening_{as_of:%Y%m%d}.json",
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
        shadow_history: ShadowHistoryProvider | None = None,
    ) -> None:
        self.repository, self.calendar, self.prices, self.costs = (
            repository,
            calendar,
            prices,
            costs,
        )
        if costs != repository.execution_costs:
            raise ValueError("service execution costs must match repository-owned policy")
        self.cache_fingerprints = cache_fingerprints
        self.enforce_manifest_gate = enforce_manifest_gate
        self._active_manifest: RunManifest | None = None
        self.shadow_history = shadow_history
        self._skipped: list[ActionItem] = []
        self._exit_plans: list[ActionItem] = []
        self._deferred: list[ActionItem] = []
        self._block_reason: str | None = None
        self._block_reasons: list[str] = []
        self._blocked_tickers: tuple[str, ...] = ()
        self._ticker_gate_blocks: tuple[TickerGateBlock, ...] = ()
        self._active_snapshot: VerifiedDailyActionSnapshot | None = None

    def run(
        self,
        as_of: date,
        candidates: Sequence[PlanCandidate],
        manifest: RunManifest | None = None,
        *,
        shadow_prices: ShadowPriceSource | None = None,
        verified_snapshot: "VerifiedDailyActionSnapshot | None" = None,
    ) -> DailyActionRun:
        """Compatibility wrapper: advance the lifecycle, then complete the run."""
        context = self.advance_lifecycle(as_of)
        if verified_snapshot is not None:
            return self.complete_run(
                context,
                snapshot=verified_snapshot,
                candidates=candidates,
                shadow_prices=shadow_prices,
            )
        return self.complete_run(
            context,
            snapshot=None,
            candidates=candidates,
            manifest=manifest,
            shadow_prices=shadow_prices,
        )

    def advance_lifecycle(self, as_of: date) -> LifecycleContext:
        """Settle due entries/exits, mark to market, and evaluate open positions.

        This runs BEFORE any readiness/snapshot/scanner work so due exits always
        complete, even when new-entry evidence is missing or fails to load.
        """
        self._skipped, self._exit_plans, self._deferred, self._block_reason = (
            [],
            [],
            [],
            None,
        )
        self._blocked_tickers = ()
        self._block_reasons = []
        self._ticker_gate_blocks = ()
        self._active_manifest = None
        self._active_snapshot = None
        self._settle_due_entry_plans(as_of)
        exits = self._settle_due_exit_plans(as_of)
        valuation = self._mark_to_market(as_of)
        self._evaluate_open_positions(as_of)
        return LifecycleContext(
            as_of=as_of, valuation=valuation, completed_exits=exits
        )

    def complete_run(
        self,
        context: LifecycleContext,
        *,
        snapshot: "VerifiedDailyActionSnapshot | None" = None,
        candidates: Sequence[PlanCandidate] = (),
        new_entry_block: str | None = None,
        manifest: RunManifest | None = None,
        shadow_prices: ShadowPriceSource | None = None,
    ) -> DailyActionRun:
        """Gate candidates and build the view from an already-advanced lifecycle.

        ``new_entry_block`` records a fail-closed reason (e.g. an invalid readiness
        manifest or a scanner failure); when set, no new plans are created but the
        settled lifecycle (exits, valuation, open positions) is still rendered.
        """
        as_of = context.as_of
        valuation = context.valuation
        if new_entry_block is not None:
            self._add_block_reason(new_entry_block)
            self._active_manifest = None
            self._active_snapshot = None
            plans: tuple[ActionItem, ...] = ()
        elif snapshot is not None:
            eligible = self._snapshot_eligible_candidates(as_of, candidates, snapshot)
            self._active_manifest = None
            self._active_snapshot = snapshot
            plans = self._create_capacity_safe_plans(as_of, eligible, valuation)
        else:
            eligible = self._manifest_eligible_candidates(as_of, candidates, manifest)
            self._active_manifest = manifest if self.enforce_manifest_gate else None
            self._active_snapshot = None
            if self.enforce_manifest_gate and not eligible:
                plans = ()
            else:
                plans = self._create_capacity_safe_plans(as_of, eligible, valuation)
        return self._build_view(
            as_of,
            valuation,
            context.completed_exits,
            plans,
            shadow_prices=shadow_prices,
        )

    def run_from_snapshot(
        self,
        snapshot: "VerifiedDailyActionSnapshot",
        candidates: Sequence[PlanCandidate],
        *,
        shadow_prices: ShadowPriceSource | None = None,
    ) -> DailyActionRun:
        return self.run(
            snapshot.signal_date,
            candidates,
            verified_snapshot=snapshot,
            shadow_prices=shadow_prices,
        )

    @staticmethod
    def render(run: DailyActionRun) -> str:
        """Render the same operator view used by the daily-action dispatcher."""
        from src.screening.offensive.daily_action import (
            DailyActionV2Run,
            render_daily_action_v2,
        )

        return render_daily_action_v2(
            DailyActionV2Run(run, (), run.open_positions, (), ())
        )

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
            self._block_all_candidates(candidate_tickers, "healthy_manifest_missing")
            return ()
        if (
            manifest.trade_date != as_of
            or not manifest.run_id
            or not manifest.input_fingerprint
        ):
            self._block_all_candidates(candidate_tickers, "manifest_identity_mismatch")
            return ()
        if (
            not manifest.candidate_tickers
            or not manifest.tickers
            or set(manifest.candidate_tickers) != set(manifest.tickers)
        ):
            self._block_all_candidates(candidate_tickers, "manifest_invalid")
            return ()

        eligible: list[PlanCandidate] = []
        blocked: list[TickerGateBlock] = []
        for candidate in candidates:
            readiness = manifest.tickers.get(candidate.ticker)
            reasons: list[str] = []
            if readiness is None:
                reasons.append("manifest_ticker_absent")
            else:
                if readiness.ticker != candidate.ticker:
                    reasons.append("manifest_ticker_identity_mismatch")
                if readiness.trade_date != as_of:
                    reasons.append("manifest_ticker_date_mismatch")
                if readiness.trade_ready is not True:
                    reasons.extend(
                        readiness.block_reasons or ("readiness_not_trade_ready",)
                    )
                expected_fingerprint = readiness.cache_fingerprint
                if not expected_fingerprint:
                    reasons.append("manifest_fingerprint_missing")
                current_fingerprint = (
                    self.cache_fingerprints(candidate.ticker, as_of)
                    if self.cache_fingerprints is not None
                    else None
                )
                if not current_fingerprint:
                    reasons.append("current_fingerprint_missing")
                elif expected_fingerprint and current_fingerprint != expected_fingerprint:
                    reasons.append(
                        "fingerprint_mismatch:"
                        f"expected={expected_fingerprint},current={current_fingerprint}"
                    )
            if reasons:
                blocked.append(TickerGateBlock(candidate.ticker, tuple(dict.fromkeys(reasons))))
                continue
            eligible.append(candidate)
        self._ticker_gate_blocks = tuple(blocked)
        self._blocked_tickers = tuple(item.ticker for item in blocked)
        return tuple(eligible)

    def _snapshot_eligible_candidates(
        self,
        as_of: date,
        candidates: Sequence[PlanCandidate],
        snapshot: "VerifiedDailyActionSnapshot",
    ) -> tuple[PlanCandidate, ...]:
        """Gate candidates on the verified Daily Action snapshot itself.

        The verified snapshot is the readiness authority for Daily Action.
        Unlike the Auto data-quality manifest it is NOT scoped to Auto's 300
        scoring candidates, so a valid BTST ticker outside that pool is admitted
        here. Each candidate is re-verified for correspondence with the snapshot
        (exact signal date, snapshot identity, a plan-eligible capability, and a
        consumed fingerprint) as TOCTOU protection against any candidate that
        does not belong to the verified input.
        """
        if not self.enforce_manifest_gate:
            return tuple(candidates)
        candidate_tickers = tuple(dict.fromkeys(item.ticker for item in candidates))
        if snapshot.signal_date != as_of:
            self._block_all_candidates(candidate_tickers, "snapshot_date_mismatch")
            return ()
        if not snapshot.snapshot_id:
            self._block_all_candidates(candidate_tickers, "snapshot_identity_missing")
            return ()

        eligible: list[PlanCandidate] = []
        blocked: list[TickerGateBlock] = []
        for candidate in candidates:
            context = snapshot.setup_context(candidate.ticker, candidate.setup)
            reasons: list[str] = []
            if candidate.signal_date != snapshot.signal_date:
                reasons.append("candidate_date_mismatch")
            if candidate.snapshot_id != snapshot.snapshot_id:
                reasons.append("candidate_snapshot_mismatch")
            if context is None:
                default_context = snapshot.setup_context(candidate.ticker)
                if default_context is not None and candidate.setup != default_context.setup_name:
                    reasons.append("candidate_setup_mismatch")
                else:
                    reasons.append("candidate_not_plan_eligible")
            else:
                capability = context.capability
                if candidate.setup != context.setup_name:
                    reasons.append("candidate_setup_mismatch")
                if candidate.setup_consumed_fingerprint != context.consumed_fingerprint:
                    reasons.append("candidate_consumed_fingerprint_mismatch")
                if candidate.detector_degraded or not capability.plan_eligible:
                    reasons.append("candidate_not_plan_eligible")
            if reasons:
                blocked.append(
                    TickerGateBlock(candidate.ticker, tuple(dict.fromkeys(reasons)))
                )
                continue
            eligible.append(candidate)
        self._ticker_gate_blocks = tuple(blocked)
        self._blocked_tickers = tuple(item.ticker for item in blocked)
        return tuple(eligible)

    def _block_all_candidates(self, tickers: Sequence[str], reason: str) -> None:
        self._add_block_reason(reason)
        self._blocked_tickers = tuple(tickers)
        self._ticker_gate_blocks = tuple(
            TickerGateBlock(ticker, (reason,)) for ticker in tickers
        )

    def _add_block_reason(self, reason: str) -> None:
        if reason not in self._block_reasons:
            self._block_reasons.append(reason)
        self._block_reason = ";".join(self._block_reasons) or None

    def _settle_due_entry_plans(self, as_of: date) -> None:
        for plan in self.repository.planned_trades(as_of):
            current = self.repository.get_trade(plan.trade_id)
            if current.state is not TradeState.PLANNED:
                continue
            if as_of != plan.planned_entry_date:
                settled, reason = self.repository.settle_plan_at_open(
                    plan.trade_id, as_of, None, None, None, None, None, None
                )
                if settled.state is TradeState.SKIPPED:
                    self._skipped.append(self._item(settled, reason))
                continue
            if not self.calendar.contains_session(as_of):
                self._skip(plan, as_of, "entry_calendar_unavailable")
                self._add_block_reason("calendar_unavailable")
                continue
            if not self._has_holding_horizon(plan.setup, plan.planned_entry_date):
                self._add_block_reason("calendar_unavailable")
                self._skip(plan, as_of, "entry_calendar_unavailable")
                continue
            self._snapshot(as_of)
            bar = self.prices(plan.ticker, as_of)
            settled, reason = self.repository.settle_plan_at_open(
                plan.trade_id,
                as_of,
                bar.open if bar is not None else None,
                bar.limit_down if bar is not None else None,
                bar.limit_up if bar is not None else None,
                bar.suspended if bar is not None else None,
                bar.high if bar is not None else None,
                bar.low if bar is not None else None,
            )
            if settled.state is TradeState.SKIPPED:
                self._skipped.append(self._item(settled, reason))

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
                self._add_block_reason("calendar_unavailable")
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
            self._add_block_reason("calendar_unavailable")
            return ()
        required_setups = {candidate.setup for candidate in candidates}
        if any(
            not self._has_holding_horizon(setup, entry_date)
            for setup in required_setups
        ):
            self._add_block_reason("calendar_unavailable")
            return ()
        _, values, _ = self._snapshot(as_of)
        reserved = [
            plan
            for plan in self.repository.planned_trades()
            if plan.planned_entry_date == entry_date
        ]
        seen: set[str] = set()
        created_items: list[ActionItem] = []
        for candidate in sorted(
            candidates, key=lambda item: (item.priority, item.ticker)
        ):
            if candidate.ticker in seen:
                continue
            seen.add(candidate.ticker)
            if candidate.authorization is not RegimeAuthorization.NORMAL:
                self._add_block_reason("regime_authorization_evidence_unavailable")
            provenance = self._plan_provenance(candidate, as_of, entry_date)
            weight = min(
                candidate.target_weight,
                candidate.authorization.ticker_cap,
                provenance.ticker_cap(candidate.setup),
            )
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
                provenance=provenance,
            )
            if created:
                reserved.append(trade)
                created_items.append(self._item(trade, "entry_planned"))
        return tuple(created_items)

    def _plan_provenance(
        self, candidate: PlanCandidate, signal_date: date, entry_date: date
    ) -> PlanProvenance:
        manifest = self._active_manifest
        snapshot = self._active_snapshot
        if snapshot is not None:
            return PlanProvenance(
                verification_status="verified",
                source_run_id=snapshot.manifest.run_id,
                manifest_fingerprint=snapshot.manifest.content_fingerprint,
                input_fingerprint=snapshot.manifest.input_fingerprint,
                ticker_cache_fingerprint=candidate.setup_consumed_fingerprint,
                snapshot_id=snapshot.snapshot_id,
                setup_consumed_fingerprint=candidate.setup_consumed_fingerprint,
                reference_price=snapshot.reference_price(candidate.ticker),
                order_type="next_session_open_proxy",
                board_rule_version=snapshot.board_rule_version,
                valid_on=entry_date,
                execution_cost_version=self.costs.version,
                authorization=RegimeAuthorization.NORMAL.value,
            )
        if manifest is None:
            return PlanProvenance.legacy_unverified()
        readiness = manifest.tickers.get(candidate.ticker)
        reference = self.prices(candidate.ticker, signal_date)
        if readiness is None or reference is None or reference.close is None:
            raise ValueError("verified plan provenance is incomplete")
        manifest_identity = json.dumps(
            {
                "run_id": manifest.run_id,
                "trade_date": manifest.trade_date.isoformat(),
                "input_fingerprint": manifest.input_fingerprint,
                "candidate_set_fingerprint": manifest.candidate_set_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        import hashlib
        return PlanProvenance(
            verification_status="verified",
            source_run_id=manifest.run_id,
            manifest_fingerprint=hashlib.sha256(manifest_identity.encode()).hexdigest(),
            input_fingerprint=manifest.input_fingerprint,
            ticker_cache_fingerprint=readiness.cache_fingerprint,
            reference_price=float(reference.close),
            order_type="next_session_open_proxy",
            board_rule_version=readiness.board_rule_version,
            valid_on=entry_date,
            execution_cost_version=self.costs.version,
            # The canonical auto manifest does not yet carry regime evidence.
            # Fail closed at 10% instead of persisting a caller-derived label.
            authorization=RegimeAuthorization.NORMAL.value,
        )

    def _build_view(
        self,
        as_of: date,
        valuation: DailyValuation,
        exits: tuple[ActionItem, ...],
        plans: tuple[ActionItem, ...],
        *,
        shadow_prices: ShadowPriceSource | None,
    ) -> DailyActionRun:
        open_trades = tuple(self.repository.open_trades())
        _, values, _ = self._snapshot(as_of)
        positions = tuple(
            self._shadow_position_view(trade, as_of, shadow_prices)
            for trade in open_trades
            if trade.state is TradeState.OPEN
        )
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
            tuple(self._block_reasons),
            self._ticker_gate_blocks,
        )

    def _shadow_position_view(
        self,
        trade: LedgerTrade,
        as_of: date,
        prices: ShadowPriceSource | None,
    ) -> OpenPositionView:
        """Project one trade through the challenger without writing ledger state."""
        try:
            result = self._evaluate_shadow_path(trade, as_of, prices)
        except Exception:
            result = (None, False, "insufficient_data")
        return OpenPositionView(
            **vars(trade),
            shadow_exit_line=result[0],
            shadow_would_exit_next_open=result[1],
            shadow_reason=result[2],
        )

    def _evaluate_shadow_path(
        self,
        trade: LedgerTrade,
        as_of: date,
        prices: ShadowPriceSource | None,
    ) -> tuple[float | None, bool, str]:
        if (
            trade.state is not TradeState.OPEN
            or trade.entry_date is None
            or trade.raw_entry_price is None
            or not math.isfinite(trade.raw_entry_price)
            or trade.raw_entry_price <= 0
        ):
            return None, False, "insufficient_data"

        if prices is None and self.shadow_history is not None:
            history = self.shadow_history(trade.ticker)
            frame = (
                self._normalize_shadow_frame(history, as_of)
                if isinstance(history, pd.DataFrame)
                else None
            )
        else:
            frame = self._shadow_history(
                self.prices if prices is None else prices,
                trade.ticker,
                as_of,
            )
        if frame is None:
            return None, False, "insufficient_data"
        dates = tuple(frame["date"])
        try:
            entry_index = dates.index(trade.entry_date)
            as_of_index = dates.index(as_of)
        except ValueError:
            return None, False, "insufficient_data"
        # Fourteen causal true ranges require a real prior-close context.
        if entry_index < 14 or as_of_index < entry_index:
            return None, False, "insufficient_data"

        state = ExitPolicyState.unarmed(entry_price=trade.raw_entry_price)
        decision_reason = "hold"
        should_exit = False
        for index in range(entry_index, as_of_index + 1):
            session = dates[index]
            atr = compute_atr(frame, period=14, at_idx=index + 1)
            if atr is None:
                return None, False, "insufficient_data"
            close = float(frame.iloc[index]["close"])
            decision = evaluate_shadow_exit(
                state,
                ExitObservation(
                    trade_date=session,
                    holding_session=index - entry_index + 1,
                    close=close,
                    atr=atr,
                ),
            )
            state = decision.state
            decision_reason = decision.reason
            should_exit = decision.should_exit_next_open
            if should_exit:
                break
        return state.exit_line, should_exit, decision_reason

    def _shadow_history(
        self,
        prices: ShadowPriceSource,
        ticker: str,
        as_of: date,
    ) -> pd.DataFrame | None:
        if isinstance(prices, pd.DataFrame):
            return self._normalize_shadow_frame(prices, as_of)
        if callable(prices):
            rows: list[dict[str, object]] = []
            found_history = False
            for session in self.calendar.open_sessions:
                if session > as_of:
                    break
                bar = prices(ticker, session)
                if bar is None:
                    if found_history:
                        return None
                    continue
                found_history = True
                row = self._shadow_bar_row(session, bar)
                if row is None:
                    return None
                rows.append(row)
            return self._normalize_shadow_frame(pd.DataFrame(rows), as_of)

        nested = prices.get(ticker)
        if isinstance(nested, pd.DataFrame):
            return self._normalize_shadow_frame(nested, as_of)
        rows = []
        if isinstance(nested, Mapping):
            items = nested.items()
        else:
            keyed = [
                (key[1], value)
                for key, value in prices.items()
                if isinstance(key, tuple) and len(key) == 2 and key[0] == ticker
            ]
            items = keyed or prices.items()
        for raw_session, bar in items:
            session = self._shadow_civil_date(raw_session)
            if session is None:
                return None
            if session > as_of:
                continue
            if not isinstance(bar, MarketBar):
                return None
            row = self._shadow_bar_row(session, bar)
            if row is None:
                return None
            rows.append(row)
        rows.sort(key=lambda row: row["date"])
        return self._normalize_shadow_frame(pd.DataFrame(rows), as_of)

    @staticmethod
    def _shadow_bar_row(session: date, bar: MarketBar) -> dict[str, object] | None:
        if not DailyActionService._valid_shadow_bar(bar):
            return None
        return {
            "date": session,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
        }

    def _normalize_shadow_frame(
        self, frame: pd.DataFrame, as_of: date
    ) -> pd.DataFrame | None:
        if frame.empty or not {"date", "high", "low", "close"}.issubset(frame.columns):
            return None
        civil_dates: list[date] = []
        previous: date | None = None
        for raw_date in frame["date"]:
            civil_date = self._shadow_civil_date(raw_date)
            if civil_date is None:
                return None
            if civil_date > as_of:
                break
            if previous is not None and civil_date <= previous:
                return None
            civil_dates.append(civil_date)
            previous = civil_date
        prefix = frame.iloc[: len(civil_dates)][["high", "low", "close"]].copy()
        prefix.insert(0, "date", civil_dates)
        if prefix.empty:
            return None
        dates = tuple(prefix["date"])
        calendar_prefix = tuple(
            session
            for session in self.calendar.open_sessions
            if dates[0] <= session <= as_of
        )
        if dates != calendar_prefix:
            return None
        for column in ("high", "low", "close"):
            prefix[column] = pd.to_numeric(prefix[column], errors="coerce")
        values = prefix[["high", "low", "close"]]
        if values.isna().any().any():
            return None
        if not values.map(
            lambda value: isinstance(value, Real)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > 0
        ).all().all():
            return None
        if not (
            (prefix["high"] >= prefix["close"])
            & (prefix["close"] >= prefix["low"])
        ).all():
            return None
        return prefix.reset_index(drop=True)

    @staticmethod
    def _shadow_civil_date(value: object) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if type(value) is date:
            return value
        if not isinstance(value, str) or not value.strip():
            return None
        parsed = pd.to_datetime(value, format="mixed", errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()

    @staticmethod
    def _valid_shadow_bar(bar: MarketBar | None) -> bool:
        if bar is None or bar.close is None or bar.high is None or bar.low is None:
            return False
        values = (bar.close, bar.high, bar.low)
        return (
            all(math.isfinite(value) and value > 0 for value in values)
            and bar.high >= bar.low
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
