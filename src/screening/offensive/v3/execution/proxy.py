"""Plan 04 Task 8: DAILY_BAR_PROXY open execution against daily bars.

The proxy is the deterministic adapter that turns a pre-sealed, permitted
entry plan into capital truth by resolving every ALLOW permit line against
its target-session daily bar. It never calls a broker and never invents a
fill: under the locked decision table, a missing bar, a suspension, a late
command, or a one-price limit lock on the locked side resolve UNKNOWN and
keep the cash, while an ordinary limit touch fills at the better of the
open and the limit. No known executable open ever means a stale-close fill.

Each FILLED line lands in the capital kernel as an attributed,
reserve-consuming fill revision plus its versioned fee revision; the
worst-case surplus returns to available cash because the reserve is
released in full and only the real gross is spent. Each UNKNOWN / NO_FILL
line releases its remaining reserve back to available cash. Resolutions
are durable, idempotent under replay, conflicting on divergent replay, and
replayable to a complete state after crashes - the proxy persists one
execution record per permit line and guards every state transition with a
rowcount check inside one immediate transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Final, Mapping

import sqlalchemy as sa

from src.screening.offensive.v3.capital.fills import (
    FeeRevisionReceipt,
    FillAttribution,
    FillRevisionReceipt,
)
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    ExecutionSide,
)
from src.screening.offensive.v3.execution.lifecycle import (
    REASON_PERMIT_QUANTITY_ZERO,
    DailyBar,
    ExecutionError,
    OpenExecutionResolution,
    OpenExecutionVerdict,
    resolve_open_execution,
)
from src.screening.offensive.v3.execution.proxy_core import (
    NormalizedProxyOpenIntent,
    ProxyCostScenario,
    adverse_fill_price_cents,
    settle_proxy_open,
)

# Fixed execution-policy + cost versions baked into the proxy mode. The
# slippage semantics live inside the execution_version (open-vs-limit fill
# price), so no separate slippage field exists: the worst-case price is the
# only upper bound the reserve needs. ``v1`` remains a named compatibility/
# research constant; the active proxy gates on the v2 official Trial version.
PROXY_EXECUTION_POLICY_VERSION: Final[str] = "t1-open-t10-open-slippage.v2"
PROXY_COST_VERSION: Final[str] = "cn-a-share-30bps-tax.v2"
LEGACY_PROXY_EXECUTION_POLICY_VERSION: Final[str] = "t1-open-t10-open.v1"
LEGACY_PROXY_COST_VERSION: Final[str] = "cn-a-share.v1"


_SCHEMA_DDL = (
    "CREATE TABLE IF NOT EXISTS execution_records ("
    " execution_id TEXT PRIMARY KEY,"
    " permit_id TEXT NOT NULL,"
    " order_line_id TEXT NOT NULL,"
    " client_order_id TEXT,"  # NULL on a zero-quantity line (no sendable order)
    " security_id TEXT NOT NULL,"
    " verdict TEXT NOT NULL,"
    " reason TEXT NOT NULL,"
    " fill_price_cents INTEGER,"
    " fill_quantity INTEGER,"
    " fill_gross_cents INTEGER,"
    " fee_total_cents INTEGER,"
    " released_reserve_cents INTEGER NOT NULL,"
    " resolution_artifact TEXT NOT NULL,"
    " recorded_at TEXT NOT NULL,"
    " UNIQUE (permit_id, order_line_id)"
    ")",
)


@dataclass(frozen=True)
class ProxyExecutionContext:
    """Injected capital truth for one proxy execution pass.

    The proxy never opens the repository itself: the caller binds the live
    capital ledger, the command timestamp (must sit inside the T0 evening
    execution window), and the source authority that signs the proxy
    revision into the capital kernel.
    """

    repository: CapitalRepository
    command_at: datetime
    source_authority: str


@dataclass(frozen=True)
class ProxyLineResult:
    """The resolved outcome of one permit line."""

    order_line_id: str
    client_order_id: str | None  # None on a zero-quantity line (no sendable order)
    verdict: OpenExecutionVerdict
    reason: str
    fill_price_cents: int | None
    fill_receipt: FillRevisionReceipt | None
    fee_receipt: FeeRevisionReceipt | None
    released_reserve_cents: int


@dataclass(frozen=True)
class ProxyExecutionRecord:
    """The durable resolution of one permit line, read back from storage."""

    execution_id: str
    permit_id: str
    order_line_id: str
    client_order_id: str | None  # None on a zero-quantity line (no sendable order)
    security_id: str
    verdict: OpenExecutionVerdict
    reason: str
    fill_price_cents: int | None
    fill_quantity: int | None
    fill_gross_cents: int | None
    fee_total_cents: int | None
    released_reserve_cents: int


@dataclass(frozen=True)
class ProxyExecutionResult:
    """The full result of one ``execute_open`` pass."""

    seal_id: str
    permit_id: str
    lines: tuple[ProxyLineResult, ...]
    execution_records: tuple[ProxyExecutionRecord, ...]


# ---------------------------------------------------------------------------
# DailyBarProxy
# ---------------------------------------------------------------------------


class DailyBarProxy:
    """Resolve one permitted entry plan against daily bars into capital truth."""

    def __init__(
        self,
        *,
        database_path: str,
        clock: Callable[[], datetime],
        _fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._database_path = database_path
        self._clock = clock
        self._fault_hook = _fault_hook
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        self._configure_connection(self._engine)
        with self._engine.begin() as conn:
            for statement in _SCHEMA_DDL:
                conn.execute(sa.text(statement))

    @staticmethod
    def _configure_connection(engine: sa.engine.Engine) -> None:
        @sa.event.listens_for(engine, "connect")
        def _set_pragma(  # noqa: ANN001
            dbapi_connection, connection_record
        ) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

    def _fault(self, phase: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(phase)

    # -- public API --------------------------------------------------------

    def execute_open(
        self,
        *,
        seal,
        permit,
        bars: Mapping[str, DailyBar],
        scenario: ProxyCostScenario,
        context: ProxyExecutionContext,
    ) -> ProxyExecutionResult:
        """Resolve every ALLOW permit line against its daily bar.

        Pre-checks (mode + execution version) run before any capital write,
        so a mismatched permit leaves the ledger untouched. Each line is
        normalized into a :class:`NormalizedProxyOpenIntent`, settled through
        the shared :func:`settle_proxy_open` core, and - when filled -
        recorded durably. The core owns the fill/fee/release economics; the
        proxy owns permit validation and the durable execution records.
        """

        self._require_proxy_mode(permit)
        self._require_execution_policy_version(permit)
        repository = context.repository
        line_results: list[ProxyLineResult] = []
        records: list[ProxyExecutionRecord] = []
        reserve_by_line = {
            binding.order_line_id: binding for binding in seal.line_reserve_bindings
        }
        proposal_line_by_id = {
            line.order_line_id: line for line in permit.seal.proposal.order_lines
        }
        send_deadline = permit.execution_window.gateway_send_deadline
        permit_id = str(permit.permit_id)
        for permit_line in permit.permit_lines:
            if permit_line.order_line_id not in proposal_line_by_id:
                raise ExecutionError(
                    "proxy_proposal_line_missing",
                    "permit line references no sealed order line",
                    order_line_id=permit_line.order_line_id,
                )
            if permit_line.order_line_id not in reserve_by_line:
                raise ExecutionError(
                    "proxy_reserve_binding_missing",
                    "permit line has no sealed reserve binding",
                    order_line_id=permit_line.order_line_id,
                )
            proposal_line = proposal_line_by_id[permit_line.order_line_id]
            result = self._resolve_one_line(
                permit_id=permit_id,
                permit_line=permit_line,
                proposal_line=proposal_line,
                bars=bars,
                scenario=scenario,
                context=context,
                reserve_binding=reserve_by_line.get(permit_line.order_line_id),
                send_deadline=send_deadline,
            )
            line_results.append(result)
            record = self._record_resolution(
                permit_id=permit_id,
                permit_line=permit_line,
                result=result,
            )
            records.append(record)
        return ProxyExecutionResult(
            seal_id=str(permit.seal.seal_id),
            permit_id=str(permit.permit_id),
            lines=tuple(line_results),
            execution_records=tuple(records),
        )

    def execution_records(
        self, permit_id: str
    ) -> tuple[ProxyExecutionRecord, ...]:
        """Read the durable resolutions of one permit, in line order."""

        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT * FROM execution_records WHERE permit_id = :pid"
                    " ORDER BY order_line_id"
                ),
                {"pid": permit_id},
            ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    # -- pre-checks --------------------------------------------------------

    def _require_proxy_mode(self, permit) -> None:
        mode = permit.seal.mode
        if mode is not ExecutionMode.DAILY_BAR_PROXY:
            raise ExecutionError(
                "proxy_mode_mismatch",
                "the proxy only executes DAILY_BAR_PROXY permits",
                permit_mode=str(mode),
            )

    def _require_execution_policy_version(self, permit) -> None:
        # The execution-policy version is pinned on the trusted execution
        # window (the bar decision table is part of that policy); a
        # divergent version means the proxy's decision table no longer
        # describes this order.
        version = permit.execution_window.execution_policy_version
        if version != PROXY_EXECUTION_POLICY_VERSION:
            raise ExecutionError(
                "proxy_execution_version_mismatch",
                "the proxy only executes the pinned execution-policy version",
                expected=PROXY_EXECUTION_POLICY_VERSION,
                observed=version,
            )

    # -- per-line resolution ----------------------------------------------

    def _resolve_one_line(
        self,
        *,
        permit_id: str,
        permit_line,
        proposal_line,
        bars: Mapping[str, DailyBar],
        scenario: ProxyCostScenario,
        context: ProxyExecutionContext,
        reserve_binding,
        send_deadline: datetime,
    ) -> ProxyLineResult:
        # Normalize the permit/proposal line into the authority-neutral intent
        # the shared core consumes, settle it through the core, then gate the
        # durable record on a consistent replay. The core owns fill/fee/
        # release economics; the proxy owns permit validation + durable records.
        bar = self._usable_bar_for(proposal_line, bars)
        if int(permit_line.permitted_quantity_units) == 0:
            # A permit line the gateway zeroed carries no executable quantity,
            # so it is already determined unexecutable: the daily bar is
            # irrelevant and it must never reach the fill table. The core
            # settles the same resolution, so the replay check sees the same
            # artifact the durable record stores.
            resolution = OpenExecutionResolution(
                OpenExecutionVerdict.NO_FILL, None, REASON_PERMIT_QUANTITY_ZERO
            )
        else:
            resolution = resolve_open_execution(
                side=ExecutionSide.ENTRY,
                limit_price_cents=int(permit_line.limit_price_cents),
                bar=bar,
                command_at=context.command_at,
                send_deadline=send_deadline,
            )
        # Reject a divergent replay before any capital write: once a line is
        # durably resolved, the proxy never re-judges it against a new bar.
        self._require_consistent_replay(permit_id, permit_line, resolution, scenario)
        intent = self._intent_for_line(
            permit_line=permit_line,
            proposal_line=proposal_line,
            reserve_binding=reserve_binding,
            context=context,
        )
        settlement = settle_proxy_open(
            intent,
            bar=bar,
            repository=context.repository,
            scenario=scenario,
            command_at=context.command_at,
            send_deadline=send_deadline,
            _fault_hook=self._fault,
        )
        self._fault("proxy.after_settle")
        return ProxyLineResult(
            order_line_id=permit_line.order_line_id,
            client_order_id=permit_line.client_order_id,
            verdict=settlement.verdict,
            reason=settlement.reason,
            fill_price_cents=settlement.fill_price_cents,
            fill_receipt=settlement.fill_receipt,
            fee_receipt=settlement.fee_receipt,
            released_reserve_cents=settlement.released_reserve_cents,
        )

    def _intent_for_line(
        self,
        *,
        permit_line,
        proposal_line,
        reserve_binding,
        context: ProxyExecutionContext,
    ) -> NormalizedProxyOpenIntent:
        return NormalizedProxyOpenIntent(
            side=ExecutionSide.ENTRY,
            security_id=permit_line.security_id,
            limit_price_cents=int(permit_line.limit_price_cents),
            quantity_units=int(permit_line.permitted_quantity_units),
            lot_size_units=int(proposal_line.lot_size_units),
            execution_id=self._execution_id(permit_line),
            order_id=permit_line.client_order_id or permit_line.order_line_id,
            reserve_source_id=(
                reserve_binding.reservation_allocation_id
                if reserve_binding is not None
                else None
            ),
            reserve_remaining_cents=int(permit_line.remaining_reserve_cents),
            position_lineage_id=proposal_line.economic_lineage_id,
            economic_lot_id=self._economic_lot_id(permit_line, proposal_line),
            attribution=self._line_attribution(proposal_line),
            source_authority=context.source_authority,
            source_binding=None,
            recorded_at=self._clock(),
        )

    def _require_consistent_replay(
        self,
        permit_id: str,
        permit_line,
        resolution: OpenExecutionResolution,
        scenario: ProxyCostScenario,
    ) -> None:
        # The durable artifact folds the scenario into the resolution: the
        # stored fill price is the post-slippage price, so a replay compares
        # against the resolution degraded under the same scenario. A replay
        # under a different cost scenario is a conflict, not a silent
        # re-settlement.
        expected_price = resolution.fill_price_cents
        if expected_price is not None:
            expected_price = adverse_fill_price_cents(
                int(expected_price),
                side=ExecutionSide.ENTRY,
                limit_cents=int(permit_line.limit_price_cents),
                bps=scenario.entry_slippage_bps,
            )
        with self._engine.connect() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT verdict, reason, fill_price_cents FROM"
                    " execution_records WHERE permit_id = :pid AND"
                    " order_line_id = :lid"
                ),
                {"pid": permit_id, "lid": permit_line.order_line_id},
            ).first()
        if existing is None:
            return
        if (
            str(existing.verdict) != resolution.verdict.value
            or str(existing.reason) != resolution.reason
            or (
                (existing.fill_price_cents is None)
                != (expected_price is None)
            )
            or (
                existing.fill_price_cents is not None
                and int(existing.fill_price_cents) != expected_price
            )
        ):
            raise ExecutionError(
                "proxy_resolution_conflict",
                "permit line already resolved with different content",
                permit_id=permit_id,
                order_line_id=permit_line.order_line_id,
            )

    def _usable_bar_for(self, proposal_line, bars: Mapping[str, DailyBar]):
        bar = bars.get(proposal_line.security_id)
        if bar is None:
            return None
        if bar.session != proposal_line.target_entry_session:
            # A bar outside the target entry session is not a usable bar:
            # it cannot prove this order's opening auction.
            return None
        return bar

    # -- provenance helpers ------------------------------------------------

    def _line_attribution(self, proposal_line) -> FillAttribution:
        return FillAttribution(
            producer_namespace=proposal_line.producer_namespace,
            research_program_id=proposal_line.research_program_id,
            economic_lineage_id=proposal_line.economic_lineage_id,
            stage_id=proposal_line.stage_id,
        )

    def _economic_lot_id(self, permit_line, proposal_line) -> str:
        # The entry lot identity is the sealed order line; the permit line
        # carries the same order_line_id as the proposal line it shrinks.
        return f"lot:{proposal_line.order_line_id}"

    def _execution_id(self, permit_line) -> str:
        # A zero-quantity line carries no client order id; fall back to its
        # sealed order line id so every permit line gets a stable execution id.
        identity = permit_line.client_order_id or permit_line.order_line_id
        return f"proxy:{identity}"

    # -- durable resolution ------------------------------------------------

    def _record_resolution(
        self,
        *,
        permit_id: str,
        permit_line,
        result: ProxyLineResult,
    ) -> ProxyExecutionRecord:
        fill_price = result.fill_price_cents
        fill_receipt = result.fill_receipt
        fee_receipt = result.fee_receipt
        artifact = self._resolution_artifact(permit_line, result)
        with self._engine.begin() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT resolution_artifact FROM execution_records"
                    " WHERE permit_id = :pid AND order_line_id = :lid"
                ),
                {"pid": permit_id, "lid": permit_line.order_line_id},
            ).first()
            if existing is not None:
                if existing.resolution_artifact != artifact:
                    raise ExecutionError(
                        "proxy_resolution_conflict",
                        "permit line already resolved with different content",
                        permit_id=permit_id,
                        order_line_id=permit_line.order_line_id,
                    )
                # Idempotent replay: the prior resolution is authoritative.
            else:
                conn.execute(
                    sa.text(
                        "INSERT INTO execution_records"
                        " (execution_id, permit_id, order_line_id,"
                        " client_order_id, security_id, verdict, reason,"
                        " fill_price_cents, fill_quantity, fill_gross_cents,"
                        " fee_total_cents, released_reserve_cents,"
                        " resolution_artifact, recorded_at)"
                        " VALUES (:eid, :pid, :lid, :cid, :sec, :verdict,"
                        " :reason, :price, :qty, :gross, :fee, :released,"
                        " :artifact, :at)"
                    ),
                    {
                        "eid": self._execution_id(permit_line),
                        "pid": permit_id,
                        "lid": permit_line.order_line_id,
                        "cid": permit_line.client_order_id,
                        "sec": permit_line.security_id,
                        "verdict": result.verdict.value,
                        "reason": result.reason,
                        "price": fill_price,
                        "qty": (
                            fill_receipt.quantity if fill_receipt is not None else None
                        ),
                        "gross": (
                            fill_receipt.gross_cents
                            if fill_receipt is not None
                            else None
                        ),
                        "fee": (
                            fee_receipt.total_cents if fee_receipt is not None else None
                        ),
                        "released": result.released_reserve_cents,
                        "artifact": artifact,
                        "at": self._clock().isoformat(),
                    },
                )
        self._fault("proxy.after_record")
        return self._execution_record_from_result(permit_id, permit_line, result)

    def _resolution_artifact(self, permit_line, result: ProxyLineResult) -> str:
        # client_order_id is None on a zero-quantity line (the gateway emits no
        # sendable order for it); coerce it so the artifact stays a stable,
        # deterministic string for every line.
        parts = [
            str(permit_line.client_order_id),
            result.verdict.value,
            result.reason,
            str(result.fill_price_cents),
            str(result.released_reserve_cents),
        ]
        return "|".join(parts)

    def _execution_record_from_result(
        self, permit_id: str, permit_line, result: ProxyLineResult
    ) -> ProxyExecutionRecord:
        fill_receipt = result.fill_receipt
        fee_receipt = result.fee_receipt
        return ProxyExecutionRecord(
            execution_id=self._execution_id(permit_line),
            permit_id=permit_id,
            order_line_id=permit_line.order_line_id,
            client_order_id=permit_line.client_order_id,
            security_id=permit_line.security_id,
            verdict=result.verdict,
            reason=result.reason,
            fill_price_cents=result.fill_price_cents,
            fill_quantity=fill_receipt.quantity if fill_receipt is not None else None,
            fill_gross_cents=(
                fill_receipt.gross_cents if fill_receipt is not None else None
            ),
            fee_total_cents=fee_receipt.total_cents if fee_receipt is not None else None,
            released_reserve_cents=result.released_reserve_cents,
        )

    def _record_from_row(self, row) -> ProxyExecutionRecord:
        verdict = OpenExecutionVerdict(str(row.verdict))
        return ProxyExecutionRecord(
            execution_id=str(row.execution_id),
            permit_id=str(row.permit_id),
            order_line_id=str(row.order_line_id),
            client_order_id=(
                str(row.client_order_id) if row.client_order_id is not None else None
            ),
            security_id=str(row.security_id),
            verdict=verdict,
            reason=str(row.reason),
            fill_price_cents=(
                int(row.fill_price_cents) if row.fill_price_cents is not None else None
            ),
            fill_quantity=(
                int(row.fill_quantity) if row.fill_quantity is not None else None
            ),
            fill_gross_cents=(
                int(row.fill_gross_cents) if row.fill_gross_cents is not None else None
            ),
            fee_total_cents=(
                int(row.fee_total_cents) if row.fee_total_cents is not None else None
            ),
            released_reserve_cents=int(row.released_reserve_cents),
        )


__all__ = [
    "PROXY_COST_VERSION",
    "PROXY_EXECUTION_POLICY_VERSION",
    "DailyBarProxy",
    "ProxyExecutionContext",
    "ProxyExecutionRecord",
    "ProxyExecutionResult",
    "ProxyLineResult",
]
