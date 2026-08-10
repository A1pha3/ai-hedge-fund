"""Plan Task 9: ShadowDecision-only T0 reserve and T+1 entry adapter.

The shadow adapter is the counterfactual counterpart to the authorised
``DailyBarProxy``. It consumes schema-major-3 ``ShadowDecision`` artifacts
read from a complete committed pair in the durable
``TrialArmDecisionStore`` — never an ``ExecutionPermit`` or a
``PortfolioDecisionSeal`` — and turns them into mode-pure capital truth in
the arm's isolated ``DAILY_BAR_PROXY`` ledger:

- T0: after the pair commits, reserve the worst-case cash for every
  counterfactual line, atomically per arm, under deterministic reserve
  source ids bound to the ``ShadowDecision``;
- T+1: resolve each line through the shared frozen mechanical shrink (never
  exceeding the sealed target), map it to a ``NormalizedProxyOpenIntent``,
  and settle it through the shared :func:`settle_proxy_open` core under an
  explicit cost scenario. A fill consumes the reserve and books fees; an
  unknown / no-fill / zero-quantity line releases the full reserve and
  keeps the cash.

The two arm ledgers are not one transaction. Every phase a line passes
through (``RESERVE_COMMITTED``, ``MECHANICAL_RESOLVED``,
``CAPITAL_SETTLED``, ``RESERVE_RELEASED``) appends one immutable fact keyed
by ``(operation_id, phase)`` with a payload hash. Exact replay reads the
fact and converges quietly (the capital kernel deduplicates a fill/fee by
execution id and a reserve by source id); a divergent replay under the same
stable id raises :class:`ShadowProxyError` with code
``shadow_proxy_protocol_breach`` before any new capital write.

The adapter owns only its append-only operation/phase store; every economic
fact is written by the shared capital kernel and the shared settlement core,
so the shadow and authorised adapters can never disagree on economics.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Final, Mapping

import sqlalchemy as sa

from src.screening.offensive.v3.capital.fills import (
    FeeRevisionReceipt,
    FillAttribution,
    FillRevisionReceipt,
)
from src.screening.offensive.v3.capital.provenance import CapitalSourceBinding
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.capital.reserves import ReserveEntryRequest
from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    ExecutionMode,
    ExecutionSide,
)
from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.execution import (
    PermitLineMechanicalBinding,
    PermitReasonCode,
    resolve_mechanical_quantity,
)
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.execution.lifecycle import (
    REASON_PERMIT_QUANTITY_ZERO,
    DailyBar,
    OpenExecutionVerdict,
    resolve_open_execution,
)
from src.screening.offensive.v3.execution.proxy_core import (
    NormalizedProxyOpenIntent,
    ProxyCostScenario,
    adverse_fill_price_cents,
    settle_proxy_open,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionRecord,
    TrialArmDecisionStore,
    TrialStoreError,
    WriterLeaseToken,
)

#: The four phases one operation may pass through, in lifecycle order. Each
#: phase appends exactly one immutable fact keyed by (operation_id, phase).
PHASE_RESERVE_COMMITTED: Final[str] = "RESERVE_COMMITTED"
PHASE_MECHANICAL_RESOLVED: Final[str] = "MECHANICAL_RESOLVED"
PHASE_CAPITAL_SETTLED: Final[str] = "CAPITAL_SETTLED"
PHASE_RESERVE_RELEASED: Final[str] = "RESERVE_RELEASED"
_TERMINAL_PHASES: Final[tuple[str, ...]] = (PHASE_CAPITAL_SETTLED, PHASE_RESERVE_RELEASED)

#: The shadow decision carries literal absence of execution authority; the
#: adapter re-validates this defensively before any capital write.
_REQUIRED_EXECUTION_AUTHORITY: Final[str] = "NONE"
_SOURCE_AUTHORITY: Final[str] = "growth-kernel.shadow.v2"


class ShadowProxyError(Exception):
    """A shadow proxy lifecycle operation failed a frozen invariant."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def shadow_economic_id(
    trial_id: str,
    arm: TrialArm,
    cycle_id: str,
    line_id: str,
    event_kind: str,
) -> str:
    """Deterministic economic identity for one shadow event.

    The id is a pure function of the trial, arm, decision cycle, line, and
    event kind, so every replay of the same event derives the same id and the
    capital kernel can deduplicate it. No random or wall-clock component
    enters the id.
    """

    return f"shadow:{trial_id}:{arm.value}:{cycle_id}:{line_id}:{event_kind}"


def _payload_hash(*parts: object) -> str:
    joined = "|".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ShadowArmExecutionContext:
    """Injected per-arm truth for one shadow proxy pass.

    Each arm names its trial, arm, and portfolio identity, the durable
    decision store holding the committed pair, its isolated capital ledger,
    and the fenced single-writer lease that guards pair/capital mutation.
    """

    trial_id: str
    arm: TrialArm
    portfolio_id: str
    decision_store: TrialArmDecisionStore
    capital_repository: CapitalRepository
    writer_lease: WriterLeaseToken


@dataclass(frozen=True)
class ShadowReserveReceipt:
    """The outcome of reserving one arm's worst-case entry cash at T0."""

    arm: TrialArm
    portfolio_id: str
    shadow_decision_id: str
    artifact_hash: str
    reserve_source_ids: tuple[str, ...]
    reserved_cash_cents: int


@dataclass(frozen=True)
class ShadowEntryLineResult:
    """The resolved outcome of settling one counterfactual line at T+1."""

    shadow_line_id: str
    security_id: str
    permitted_quantity_units: int
    reason_code: PermitReasonCode
    verdict: OpenExecutionVerdict
    reason: str
    fill_price_cents: int | None
    fill_receipt: FillRevisionReceipt | None
    fee_receipt: FeeRevisionReceipt | None
    released_reserve_cents: int


@dataclass(frozen=True)
class ShadowEntryResult:
    """The full result of one arm's T+1 entry pass."""

    arm: TrialArm
    portfolio_id: str
    shadow_decision_id: str
    artifact_hash: str
    lines: tuple[ShadowEntryLineResult, ...]


_SCHEMA_DDL = (
    # One immutable operation row binds the decision hash, the line, the arm,
    # the portfolio, the target session, and the source binding. It is the
    # durable parent of every phase fact for that line.
    "CREATE TABLE IF NOT EXISTS shadow_proxy_operations ("
    " operation_id TEXT PRIMARY KEY,"
    " trial_id TEXT NOT NULL,"
    " signal_session TEXT NOT NULL,"
    " decision_cycle_id TEXT NOT NULL,"
    " arm TEXT NOT NULL,"
    " portfolio_id TEXT NOT NULL,"
    " shadow_decision_id TEXT NOT NULL,"
    " artifact_hash TEXT NOT NULL,"
    " shadow_line_id TEXT NOT NULL,"
    " security_id TEXT NOT NULL,"
    " target_entry_session TEXT NOT NULL,"
    " reserve_source_id TEXT NOT NULL,"
    " reserved_cash_cents INTEGER NOT NULL,"
    " source_binding_json TEXT NOT NULL,"
    " created_at TEXT NOT NULL,"
    " UNIQUE (trial_id, decision_cycle_id, arm, shadow_line_id)"
    ")",
    "CREATE TRIGGER IF NOT EXISTS shadow_proxy_operations_no_update"
    " BEFORE UPDATE ON shadow_proxy_operations"
    " BEGIN"
    "  SELECT RAISE(ABORT,"
    "   'immutable table: shadow_proxy_operations rejects UPDATE');"
    " END",
    "CREATE TRIGGER IF NOT EXISTS shadow_proxy_operations_no_delete"
    " BEFORE DELETE ON shadow_proxy_operations"
    " BEGIN"
    "  SELECT RAISE(ABORT,"
    "   'immutable table: shadow_proxy_operations rejects DELETE');"
    " END",
    # Each completed phase appends one fact with a unique (operation_id,
    # phase) key and a payload hash. Exact replay reads the fact; a divergent
    # replay under the same key is a protocol breach.
    "CREATE TABLE IF NOT EXISTS shadow_proxy_phase_facts ("
    " operation_id TEXT NOT NULL,"
    " phase TEXT NOT NULL,"
    " payload_hash TEXT NOT NULL,"
    " recorded_at TEXT NOT NULL,"
    " PRIMARY KEY (operation_id, phase)"
    ")",
)


class ShadowProxyAdapter:
    """Reserve and settle committed shadow entries into arm capital truth."""

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

    # ===================================================================
    # T0 reserve
    # ===================================================================

    def reserve_committed_pair(
        self,
        pair_key: tuple[str, str, str],
        contexts: Mapping[TrialArm, ShadowArmExecutionContext],
    ) -> Mapping[TrialArm, ShadowReserveReceipt]:
        """Reserve the worst-case entry cash for both arms of a committed pair.

        The writer lease and both decision records are revalidated before any
        capital write. Each arm's lines reserve in one atomic capital
        transaction; the two arms are independent transactions, so a crash
        after one arm commits lets replay commit the other without changing
        the first.
        """

        records = self._read_committed_pair(pair_key, contexts)
        receipts: dict[TrialArm, ShadowReserveReceipt] = {}
        for arm, ctx in contexts.items():
            record = records.get(arm)
            if record is None:
                raise ShadowProxyError(
                    "arm_not_in_pair",
                    "the committed pair has no decision for this arm",
                    arm=arm.value,
                )
            decision = record.decision
            if not isinstance(decision, ShadowDecision):
                # A NoTrade arm reserves nothing; it carries no shadow lines.
                receipts[arm] = ShadowReserveReceipt(
                    arm=arm,
                    portfolio_id=ctx.portfolio_id,
                    shadow_decision_id="",
                    artifact_hash="",
                    reserve_source_ids=(),
                    reserved_cash_cents=0,
                )
                continue
            self._validate_admission(decision, ctx)
            receipts[arm] = self._reserve_arm(pair_key, ctx, decision)
        return receipts

    def _reserve_arm(
        self,
        pair_key: tuple[str, str, str],
        ctx: ShadowArmExecutionContext,
        decision: ShadowDecision,
    ) -> ShadowReserveReceipt:
        arm = ctx.arm
        cycle = decision.counterfactual_key.counterfactual_cycle_id
        binding = self._source_binding(decision)
        source_ids: list[str] = []
        requests: list[ReserveEntryRequest] = []
        # Facts that may land only once the atomic reserve commits; kept local
        # so a crash before the reserve leaves no orphan phase facts.
        pending: list[tuple[str, str, str]] = []
        total_reserved = 0
        for line in decision.counterfactual_lines:
            operation_id = shadow_economic_id(
                decision.trial_id, arm, cycle, line.shadow_line_id, "entry-line"
            )
            reserve_source_id = shadow_economic_id(
                decision.trial_id, arm, cycle, line.shadow_line_id, "entry-reserve"
            )
            reserved_cents = int(line.estimated_cash_reserve_cents)
            self._record_operation(
                operation_id=operation_id,
                pair_key=pair_key,
                arm=arm,
                ctx=ctx,
                decision=decision,
                line=line,
                reserve_source_id=reserve_source_id,
                reserved_cents=reserved_cents,
                binding=binding,
            )
            source_ids.append(reserve_source_id)
            total_reserved += reserved_cents
            payload_hash = _payload_hash(
                PHASE_RESERVE_COMMITTED,
                reserve_source_id,
                reserved_cents,
                binding.model_dump_json(),
            )
            if self._has_matching_fact(
                operation_id, PHASE_RESERVE_COMMITTED, payload_hash
            ):
                # Already committed in a prior run; the reserve is durable.
                continue
            # A same-key/different-content fact is a divergent replay.
            self._require_no_fact(operation_id, PHASE_RESERVE_COMMITTED)
            requests.append(
                ReserveEntryRequest(
                    source_id=reserve_source_id,
                    research_program_id=line.research_program_id,
                    economic_lineage_id=line.economic_lineage_id,
                    stage_id=line.stage_id,
                    reserved_entry_gross_cents=reserved_cents,
                    expected_stream_version=(
                        ctx.capital_repository.stream_version()
                    ),
                    as_of=self._clock(),
                    source_binding=binding,
                )
            )
            pending.append((operation_id, PHASE_RESERVE_COMMITTED, payload_hash))
        if requests:
            ctx.capital_repository.reserve_entries_atomic(tuple(requests))
        for operation_id, phase, payload_hash in pending:
            self._record_fact(operation_id, phase, payload_hash)
        self._fault(f"shadow.after_arm_reserve:{arm.value}")
        return ShadowReserveReceipt(
            arm=arm,
            portfolio_id=ctx.portfolio_id,
            shadow_decision_id=decision.shadow_decision_id,
            artifact_hash=decision.artifact_hash(),
            reserve_source_ids=tuple(source_ids),
            reserved_cash_cents=total_reserved,
        )

    # ===================================================================
    # T+1 entry
    # ===================================================================

    def execute_entries(
        self,
        pair_key: tuple[str, str, str],
        context: ShadowArmExecutionContext,
        *,
        mechanical_bindings: Mapping[str, PermitLineMechanicalBinding],
        bars: Mapping[str, DailyBar],
        scenario: ProxyCostScenario,
        command_at: datetime,
        send_deadline: datetime,
        target_session: date | None = None,
    ) -> ShadowEntryResult:
        """Settle one arm's T+1 entries through the shared core.

        Every line is mechanically shrunk (never exceeding its sealed target),
        mapped to a normalized intent, and settled through
        :func:`settle_proxy_open`. A fill consumes the reserve and books the
        fee; an unknown / no-fill / zero-quantity line releases the full
        reserve. A divergent replay under the same stable id is a protocol
        breach raised before any new capital write.
        """

        arm = context.arm
        decision = self._read_arm_shadow_decision(pair_key, context)
        if target_session is not None and decision.target_entry_session != target_session:
            raise ShadowProxyError(
                "target_session_mismatch",
                "the decision targets a different entry session",
                expected=str(decision.target_entry_session),
                observed=str(target_session),
                arm=arm.value,
            )
        cycle = decision.counterfactual_key.counterfactual_cycle_id
        binding = self._source_binding(decision)
        results: list[ShadowEntryLineResult] = []
        for line in decision.counterfactual_lines:
            results.append(
                self._execute_line(
                    pair_key=pair_key,
                    ctx=context,
                    decision=decision,
                    line=line,
                    mechanical_bindings=mechanical_bindings,
                    bars=bars,
                    scenario=scenario,
                    command_at=command_at,
                    send_deadline=send_deadline,
                    cycle=cycle,
                    binding=binding,
                )
            )
        return ShadowEntryResult(
            arm=arm,
            portfolio_id=context.portfolio_id,
            shadow_decision_id=decision.shadow_decision_id,
            artifact_hash=decision.artifact_hash(),
            lines=tuple(results),
        )

    def _execute_line(
        self,
        *,
        pair_key: tuple[str, str, str],
        ctx: ShadowArmExecutionContext,
        decision: ShadowDecision,
        line,
        mechanical_bindings: Mapping[str, PermitLineMechanicalBinding],
        bars: Mapping[str, DailyBar],
        scenario: ProxyCostScenario,
        command_at: datetime,
        send_deadline: datetime,
        cycle: str,
        binding: CapitalSourceBinding,
    ) -> ShadowEntryLineResult:
        arm = ctx.arm
        operation_id = shadow_economic_id(
            decision.trial_id, arm, cycle, line.shadow_line_id, "entry-line"
        )
        # The entry may not settle until its T0 reserve is committed.
        if not self._has_fact(operation_id, PHASE_RESERVE_COMMITTED):
            raise ShadowProxyError(
                "reserve_not_committed",
                "an entry line may not settle before its T0 reserve commits",
                operation_id=operation_id,
                arm=arm.value,
            )
        mechanical = mechanical_bindings.get(line.shadow_line_id)
        if mechanical is None:
            raise ShadowProxyError(
                "mechanical_binding_missing",
                "every entry line needs a frozen mechanical binding",
                shadow_line_id=line.shadow_line_id,
            )
        shrink = resolve_mechanical_quantity(
            int(line.target_quantity_units),
            int(line.lot_size_units),
            mechanical,
        )
        quantity = shrink.permitted_quantity_units
        mech_hash = _payload_hash(
            PHASE_MECHANICAL_RESOLVED, quantity, shrink.reason_code.value
        )
        self._record_fact(operation_id, PHASE_MECHANICAL_RESOLVED, mech_hash)

        bar = bars.get(line.security_id)
        if quantity == 0:
            verdict = OpenExecutionVerdict.NO_FILL
            reason = REASON_PERMIT_QUANTITY_ZERO
            fill_price_cents: int | None = None
        else:
            resolution = resolve_open_execution(
                side=ExecutionSide.ENTRY,
                limit_price_cents=int(line.limit_price_cents),
                bar=bar,
                command_at=command_at,
                send_deadline=send_deadline,
            )
            verdict = resolution.verdict
            reason = resolution.reason
            fill_price_cents = (
                adverse_fill_price_cents(
                    resolution.fill_price_cents,
                    side=ExecutionSide.ENTRY,
                    limit_cents=int(line.limit_price_cents),
                    bps=scenario.entry_slippage_bps,
                )
                if verdict is OpenExecutionVerdict.FILLED
                else None
            )
        phase = (
            PHASE_CAPITAL_SETTLED if verdict is OpenExecutionVerdict.FILLED else PHASE_RESERVE_RELEASED
        )
        phase_hash = _payload_hash(phase, verdict.value, reason, fill_price_cents, quantity)
        # A line already resolved under a different terminal phase or a
        # different payload is a protocol breach — raised before any capital
        # write so the ledger never moves under a divergent replay.
        self._require_no_divergent_terminal(operation_id, phase, phase_hash)
        already_settled = self._has_matching_fact(operation_id, phase, phase_hash)

        intent = NormalizedProxyOpenIntent(
            side=ExecutionSide.ENTRY,
            security_id=line.security_id,
            limit_price_cents=int(line.limit_price_cents),
            quantity_units=quantity,
            lot_size_units=int(line.lot_size_units),
            execution_id=shadow_economic_id(
                decision.trial_id, arm, cycle, line.shadow_line_id, "entry-fill"
            ),
            order_id=shadow_economic_id(
                decision.trial_id, arm, cycle, line.shadow_line_id, "entry-order"
            ),
            reserve_source_id=shadow_economic_id(
                decision.trial_id, arm, cycle, line.shadow_line_id, "entry-reserve"
            ),
            reserve_remaining_cents=int(line.estimated_cash_reserve_cents),
            position_lineage_id=line.economic_lineage_id,
            economic_lot_id=f"shadow-lot:{line.shadow_line_id}",
            attribution=self._line_attribution(line),
            source_authority=_SOURCE_AUTHORITY,
            source_binding=binding,
            recorded_at=self._clock(),
        )
        # Settle once: the capital kernel deduplicates a fill/fee by execution
        # id and a reserve release by source id, so an exact replay is a
        # capital no-op. The durable fact records the terminal phase.
        settlement = settle_proxy_open(
            intent,
            bar=bar,
            repository=ctx.capital_repository,
            scenario=scenario,
            command_at=command_at,
            send_deadline=send_deadline,
        )
        self._fault("shadow.after_settle")
        if not already_settled:
            self._record_fact(operation_id, phase, phase_hash)
        return ShadowEntryLineResult(
            shadow_line_id=line.shadow_line_id,
            security_id=line.security_id,
            permitted_quantity_units=quantity,
            reason_code=shrink.reason_code,
            verdict=settlement.verdict,
            reason=settlement.reason,
            fill_price_cents=settlement.fill_price_cents,
            fill_receipt=settlement.fill_receipt,
            fee_receipt=settlement.fee_receipt,
            released_reserve_cents=settlement.released_reserve_cents,
        )

    # ===================================================================
    # admission + decision reads
    # ===================================================================

    def _read_committed_pair(
        self,
        pair_key: tuple[str, str, str],
        contexts: Mapping[TrialArm, ShadowArmExecutionContext],
    ) -> Mapping[TrialArm, TrialArmDecisionRecord]:
        # Revalidate every arm's writer lease before reading the pair: a
        # stale lease fails before any capital write.
        for ctx in contexts.values():
            try:
                ctx.decision_store.require_writer(ctx.writer_lease)
            except TrialStoreError as exc:
                raise ShadowProxyError(
                    "writer_lease_stale",
                    "the writer lease is stale or unknown",
                    arm=ctx.arm.value,
                ) from exc
        store = next(iter(contexts.values())).decision_store
        try:
            records = store.pair(pair_key)
        except TrialStoreError as exc:
            if exc.code == "pair_incomplete":
                raise ShadowProxyError(
                    "pair_not_committed",
                    "the pair is not committed for this key",
                    key=list(pair_key),
                ) from exc
            raise
        return {record.arm: record for record in records}

    def _read_arm_shadow_decision(
        self, pair_key: tuple[str, str, str], ctx: ShadowArmExecutionContext
    ) -> ShadowDecision:
        records = self._read_committed_pair(pair_key, {ctx.arm: ctx})
        record = records.get(ctx.arm)
        if record is None:
            raise ShadowProxyError(
                "arm_not_in_pair",
                "the committed pair has no decision for this arm",
                arm=ctx.arm.value,
            )
        decision = record.decision
        if not isinstance(decision, ShadowDecision):
            raise ShadowProxyError(
                "not_a_shadow_decision",
                "a no-trade arm has no entries to settle",
                arm=ctx.arm.value,
            )
        self._validate_admission(decision, ctx)
        return decision

    def _validate_admission(
        self, decision: ShadowDecision, ctx: ShadowArmExecutionContext
    ) -> None:
        if decision.schema_major != 3:
            raise ShadowProxyError(
                "shadow_schema_mismatch",
                "the adapter accepts only schema-major-3 ShadowDecision",
                observed_schema_major=decision.schema_major,
                arm=ctx.arm.value,
            )
        if decision.execution_authority != _REQUIRED_EXECUTION_AUTHORITY:
            raise ShadowProxyError(
                "execution_authority_not_none",
                "a shadow decision must carry literal absence of execution"
                " authority before any capital write",
                observed=decision.execution_authority,
                arm=ctx.arm.value,
            )
        if decision.trial_id != ctx.trial_id:
            raise ShadowProxyError(
                "trial_mismatch",
                "the decision binds a different trial than the context",
                expected=ctx.trial_id,
                observed=decision.trial_id,
                arm=ctx.arm.value,
            )
        if decision.portfolio_id != ctx.portfolio_id:
            raise ShadowProxyError(
                "portfolio_mismatch",
                "the decision binds a different portfolio than the context",
                expected=ctx.portfolio_id,
                observed=decision.portfolio_id,
                arm=ctx.arm.value,
            )

    # ===================================================================
    # provenance + attribution helpers
    # ===================================================================

    @staticmethod
    def _source_binding(decision: ShadowDecision) -> CapitalSourceBinding:
        return CapitalSourceBinding(
            mode=ExecutionMode.DAILY_BAR_PROXY,
            artifact_kind=ArtifactKind.SHADOW_DECISION,
            artifact_id=decision.shadow_decision_id,
            artifact_hash=decision.artifact_hash(),
        )

    @staticmethod
    def _line_attribution(line) -> FillAttribution:
        return FillAttribution(
            producer_namespace=line.producer_namespace,
            research_program_id=line.research_program_id,
            economic_lineage_id=line.economic_lineage_id,
            stage_id=line.stage_id,
        )

    # ===================================================================
    # append-only operation/phase storage
    # ===================================================================

    def _require_no_fact(self, operation_id: str, phase: str) -> None:
        """A fact for this phase must not already exist (divergent replay)."""

        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT 1 FROM shadow_proxy_phase_facts"
                    " WHERE operation_id = :oid AND phase = :phase"
                ),
                {"oid": operation_id, "phase": phase},
            ).first()
        if row is not None:
            raise ShadowProxyError(
                "shadow_proxy_protocol_breach",
                "a phase already completed with different content",
                operation_id=operation_id,
                phase=phase,
            )

    def _record_operation(
        self,
        *,
        operation_id: str,
        pair_key: tuple[str, str, str],
        arm: TrialArm,
        ctx: ShadowArmExecutionContext,
        decision: ShadowDecision,
        line,
        reserve_source_id: str,
        reserved_cents: int,
        binding: CapitalSourceBinding,
    ) -> None:
        binding_json = binding.model_dump_json()
        with self._engine.begin() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT shadow_decision_id, artifact_hash, shadow_line_id,"
                    " security_id, target_entry_session, reserve_source_id,"
                    " reserved_cash_cents, source_binding_json"
                    " FROM shadow_proxy_operations WHERE operation_id = :oid"
                ),
                {"oid": operation_id},
            ).first()
            values = {
                "oid": operation_id,
                "trial_id": decision.trial_id,
                "signal_session": pair_key[1],
                "cycle": pair_key[2],
                "arm": arm.value,
                "portfolio_id": ctx.portfolio_id,
                "shadow_decision_id": decision.shadow_decision_id,
                "artifact_hash": decision.artifact_hash(),
                "shadow_line_id": line.shadow_line_id,
                "security_id": line.security_id,
                "target_session": str(decision.target_entry_session),
                "reserve_source_id": reserve_source_id,
                "reserved_cents": reserved_cents,
                "source_binding_json": binding_json,
                "created_at": self._clock().isoformat(),
            }
            if existing is not None:
                stored = (
                    existing.shadow_decision_id,
                    existing.artifact_hash,
                    existing.shadow_line_id,
                    existing.security_id,
                    existing.target_entry_session,
                    existing.reserve_source_id,
                    int(existing.reserved_cash_cents),
                    existing.source_binding_json,
                )
                candidate = (
                    decision.shadow_decision_id,
                    decision.artifact_hash(),
                    line.shadow_line_id,
                    line.security_id,
                    str(decision.target_entry_session),
                    reserve_source_id,
                    reserved_cents,
                    binding_json,
                )
                if stored != candidate:
                    raise ShadowProxyError(
                        "shadow_proxy_protocol_breach",
                        "an operation already exists with different content",
                        operation_id=operation_id,
                    )
                return
            conn.execute(
                sa.text(
                    "INSERT INTO shadow_proxy_operations"
                    " (operation_id, trial_id, signal_session,"
                    " decision_cycle_id, arm, portfolio_id, shadow_decision_id,"
                    " artifact_hash, shadow_line_id, security_id,"
                    " target_entry_session, reserve_source_id,"
                    " reserved_cash_cents, source_binding_json, created_at)"
                    " VALUES (:oid, :trial_id, :signal_session, :cycle, :arm,"
                    " :portfolio_id, :shadow_decision_id, :artifact_hash,"
                    " :shadow_line_id, :security_id, :target_session,"
                    " :reserve_source_id, :reserved_cents,"
                    " :source_binding_json, :created_at)"
                ),
                values,
            )

    def _has_fact(self, operation_id: str, phase: str) -> bool:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT 1 FROM shadow_proxy_phase_facts"
                    " WHERE operation_id = :oid AND phase = :phase"
                ),
                {"oid": operation_id, "phase": phase},
            ).first()
        return row is not None

    def _has_matching_fact(
        self, operation_id: str, phase: str, payload_hash: str
    ) -> bool:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT payload_hash FROM shadow_proxy_phase_facts"
                    " WHERE operation_id = :oid AND phase = :phase"
                ),
                {"oid": operation_id, "phase": phase},
            ).first()
        return row is not None and row.payload_hash == payload_hash

    def _require_no_divergent_terminal(
        self, operation_id: str, phase: str, payload_hash: str
    ) -> None:
        # If the same terminal phase exists with a different payload, or a
        # different terminal phase exists at all, the line already resolved
        # differently: a replay must not silently re-settle it.
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT phase, payload_hash FROM shadow_proxy_phase_facts"
                    " WHERE operation_id = :oid AND phase IN :phases"
                ).bindparams(sa.bindparam("phases", expanding=True)),
                {"oid": operation_id, "phases": list(_TERMINAL_PHASES)},
            ).fetchall()
        for row in rows:
            if row.phase != phase or row.payload_hash != payload_hash:
                raise ShadowProxyError(
                    "shadow_proxy_protocol_breach",
                    "the line already resolved under a different terminal phase"
                    " or payload",
                    operation_id=operation_id,
                    observed_phase=row.phase,
                    expected_phase=phase,
                )

    def _record_fact(
        self, operation_id: str, phase: str, payload_hash: str
    ) -> None:
        # Idempotent on an exact payload match; a same-key/different-payload
        # replay is a protocol breach.
        with self._engine.begin() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT payload_hash FROM shadow_proxy_phase_facts"
                    " WHERE operation_id = :oid AND phase = :phase"
                ),
                {"oid": operation_id, "phase": phase},
            ).first()
            if existing is not None:
                if existing.payload_hash != payload_hash:
                    raise ShadowProxyError(
                        "shadow_proxy_protocol_breach",
                        "a phase already completed with different content",
                        operation_id=operation_id,
                        phase=phase,
                    )
                return
            conn.execute(
                sa.text(
                    "INSERT INTO shadow_proxy_phase_facts"
                    " (operation_id, phase, payload_hash, recorded_at)"
                    " VALUES (:oid, :phase, :hash, :at)"
                ),
                {
                    "oid": operation_id,
                    "phase": phase,
                    "hash": payload_hash,
                    "at": self._clock().isoformat(),
                },
            )


__all__ = [
    "PHASE_CAPITAL_SETTLED",
    "PHASE_MECHANICAL_RESOLVED",
    "PHASE_RESERVE_COMMITTED",
    "PHASE_RESERVE_RELEASED",
    "ShadowArmExecutionContext",
    "ShadowEntryLineResult",
    "ShadowEntryResult",
    "ShadowProxyAdapter",
    "ShadowProxyError",
    "ShadowReserveReceipt",
    "shadow_economic_id",
]
