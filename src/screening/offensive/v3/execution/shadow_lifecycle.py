"""Plan Task 10: the complete shadow capital lifecycle facade.

:class:`ShadowProxyLifecycle` is the per-trial orchestrator that drives one
trading session of a paired shadow trial through the fixed session ladder
for both arms. It composes four independent authorities without merging
their truths:

- the :class:`ShadowProxyAdapter` settles T+1 entries and T+10 exits
  through the shared :func:`settle_proxy_open` core;
- the durable :class:`ExitLane` derives, claims, and records exit mandates;
- the :class:`CheckpointService` advances the monotone session checkpoint
  ladder of each arm ledger (one checkpoint truth, never a second);
- the :class:`CapitalRepository` confirms close valuations and applies
  company actions / corrections.

The fixed session order is::

    CORPORATE_ACTIONS_APPLIED
    PREOPEN_RISK_LOCKED
    EXIT_OPEN_RECONCILED   (exit derive + claim + settle — internal)
    ENTRY_OPEN_RECONCILED  (target-session entry settle — internal)
    OPEN_RECONCILED        (exit + entry both complete)
    CLOSE_VALUED
    SESSION_FINALIZED

Exit and entry reconciliation both complete before the existing
``OPEN_RECONCILED`` checkpoint advance, so the checkpoint ladder gains no
second truth. Exits continue while entry, risk, or stage is halted: the
lane ignores halt states, and a crashed exit fill converges on exact replay
because the capital fill commits before the exit-lane ``FILLED`` fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Mapping

from src.screening.offensive.v3.capital.checkpoints import (
    CheckpointService,
    SessionCheckpointReceipt,
    SessionCheckpointRequest,
)
from src.screening.offensive.v3.capital.fills import FillAttribution
from src.screening.offensive.v3.capital.nav import (
    ValuationMarkInput,
    ValuationReceipt,
    ValuationRequest,
)
from src.screening.offensive.v3.capital.provenance import CapitalSourceBinding
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    ExecutionMode,
    ExitMandate,
    PositionState,
)
from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.evidence import EvidenceRecord
from src.screening.offensive.v3.contracts.execution import (
    PermitLineMechanicalBinding,
)
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.execution.lifecycle import DailyBar
from src.screening.offensive.v3.execution.proxy_core import ProxyCostScenario
from src.screening.offensive.v3.execution.shadow_proxy import (
    ShadowArmExecutionContext,
    ShadowExitResult,
    ShadowExitSettlementInput,
    ShadowProxyAdapter,
    ShadowProxyError,
)
from src.screening.offensive.v3.gateway.exits import (
    ClaimedExitWork,
    ExitAttemptOutcome,
    ExitDerivationContext,
    ExitLane,
    ExitLaneError,
    ExitLotTruth,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionStore,
    WriterLeaseToken,
)

#: The open-exit policy sells into the session open at any price; a sell limit
#: of zero means the open always satisfies it and adverse slippage degrades
#: the price downward toward (never past) zero.
_OPEN_EXIT_LIMIT_CENTS: int = 0

#: The T+1 entry ordinal baked into the trial policy (entry is one session
#: after the signal). The exit due date uses this together with the frozen
#: T+10 exit ordinal pinned inside the exit lane.
_ENTRY_SESSION_ORDINAL: int = 1

#: The shadow worker identity that owns every exit lease the lifecycle claims.
_SHADOW_WORKER_ID: str = "shadow-lifecycle"


@dataclass(frozen=True)
class ShadowArmLifecycleState:
    """Stable per-arm references the lifecycle drives across sessions.

    The writer lease is the only piece that may rotate (fencing); it is
    refreshed from the per-call arm contexts. Every other reference is bound
    for the trial's lifetime.
    """

    trial_id: str
    arm: TrialArm
    portfolio_id: str
    pair_key: tuple[str, str, str]
    base_currency: str
    broker_account_id: str | None
    fixed_exit_policy_fingerprint: str
    decision_store: TrialArmDecisionStore
    capital_repository: CapitalRepository
    exit_lane: ExitLane
    adapter: ShadowProxyAdapter
    writer_lease: WriterLeaseToken


@dataclass(frozen=True)
class ShadowSessionInput:
    """Everything one ``advance_session`` pass needs for one trading session."""

    session: date
    trading_sessions: tuple[date, ...]
    bars: Mapping[str, DailyBar]
    marks: Mapping[str, int]
    snapshot_evidence: EvidenceRecord
    scenario: ProxyCostScenario
    command_at: datetime
    send_deadline: datetime
    as_of: datetime
    mechanical_bindings: Mapping[str, PermitLineMechanicalBinding] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class ArmSessionReceipt:
    """The outcome of advancing one arm through one session."""

    arm: TrialArm
    session: date
    exits: tuple[ShadowExitResult, ...]
    valuation: ValuationReceipt | None
    finalized: SessionCheckpointReceipt | None


@dataclass(frozen=True)
class PairedLifecycleReceipt:
    """The outcome of advancing both arms through one session."""

    session: date
    arms: Mapping[TrialArm, ArmSessionReceipt]


class ShadowProxyLifecycle:
    """Drive the fixed shadow capital session ladder for both arms."""

    def __init__(
        self,
        states: Mapping[TrialArm, ShadowArmLifecycleState],
        *,
        clock: Callable[[], datetime],
        _fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._states = dict(states)
        self._clock = clock
        self._fault_hook = _fault_hook

    def _fault(self, phase: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(phase)

    # ===================================================================
    # full-session orchestration
    # ===================================================================

    def advance_session(
        self,
        session_input: ShadowSessionInput,
        arm_contexts: Mapping[TrialArm, ShadowArmExecutionContext],
    ) -> PairedLifecycleReceipt:
        """Run the fixed session ladder for both arms.

        Each arm independently: advance corporate-actions + preopen-risk
        checkpoints, reconcile exits then entries, advance the shared
        ``OPEN_RECONCILED`` checkpoint, close the valuation, and finalize.
        A crash after one arm finalizes must let replay finalize the other.
        """

        receipts: dict[TrialArm, ArmSessionReceipt] = {}
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
            state = self._states[arm]
            context = arm_contexts[arm]
            # Refresh the rotating writer lease from the per-call context.
            self._states[arm] = ShadowArmLifecycleState(
                trial_id=state.trial_id,
                arm=arm,
                portfolio_id=state.portfolio_id,
                pair_key=state.pair_key,
                base_currency=state.base_currency,
                broker_account_id=state.broker_account_id,
                fixed_exit_policy_fingerprint=(
                    state.fixed_exit_policy_fingerprint
                ),
                decision_store=state.decision_store,
                capital_repository=state.capital_repository,
                exit_lane=state.exit_lane,
                adapter=state.adapter,
                writer_lease=context.writer_lease,
            )
            receipts[arm] = self._advance_one_arm(arm, session_input)
        return PairedLifecycleReceipt(session=session_input.session, arms=receipts)

    def _advance_one_arm(
        self, arm: TrialArm, session_input: ShadowSessionInput
    ) -> ArmSessionReceipt:
        state = self._states[arm]
        session = session_input.session
        repository = state.capital_repository
        checkpoint = CheckpointService(repository)
        # Resume support: a session already finalized by a prior (crashed)
        # run converges as a no-op for this arm. Each checkpoint phase below
        # advances only if it is not yet committed for this session, so a
        # crash at any boundary replays cleanly (reconciliation is idempotent
        # and the capital kernel deduplicates every economic fact).
        committed = self._committed_phases(repository, session)
        if "SESSION_FINALIZED" in committed:
            return ArmSessionReceipt(
                arm=arm, session=session, exits=(), valuation=None, finalized=None
            )
        # 1-2. Corporate actions (applied out-of-band via capital primitives)
        # and the preopen risk lock advance first.
        self._advance_if_missing(
            repository, checkpoint, "CORPORATE_ACTIONS_APPLIED", session, committed
        )
        self._advance_if_missing(
            repository, checkpoint, "PREOPEN_RISK_LOCKED", session, committed
        )
        self._fault(f"lifecycle.after_preopen:{arm.value}")
        # 3. Exit reconciliation: derive, claim, settle due exits. Entry, risk,
        # or stage halts never block exits.
        self.derive_exits(arm, session_input.trading_sessions)
        exits = self.execute_due_exits(
            arm, session, session_input.bars, session_input.scenario
        )
        self._fault(f"lifecycle.after_exits:{arm.value}")
        # 4. Entry reconciliation: settle any entries targeting this session.
        self._settle_session_entries(arm, session_input)
        self._fault(f"lifecycle.after_entries:{arm.value}")
        # 5. Both reconciliations are complete: advance OPEN_RECONCILED.
        self._advance_if_missing(
            repository, checkpoint, "OPEN_RECONCILED", session, committed
        )
        # 6. Close valuation from the same-session snapshot evidence.
        valuation = self.close_valuation(
            arm, session_input.snapshot_evidence, session_input.marks
        )
        self._advance_if_missing(
            repository, checkpoint, "CLOSE_VALUED", session, committed
        )
        # 7. Finalize.
        finalized = self.finalize_session(arm, session)
        return ArmSessionReceipt(
            arm=arm,
            session=session,
            exits=tuple(exits),
            valuation=valuation,
            finalized=finalized,
        )

    # ===================================================================
    # exit derivation + settlement
    # ===================================================================

    def derive_exits(
        self, arm: TrialArm, trading_sessions: tuple[date, ...]
    ) -> tuple[ExitMandate, ...]:
        """Derive or refresh one exit mandate per open lot from capital truth.

        Each lot's truth is read from the live capital risk snapshot plus its
        originating ``ShadowDecision`` (signal session + entry evidence
        hash). Halt states are intentionally not consulted: exit obligations
        survive risk and stage halts unchanged.
        """

        state = self._states[arm]
        repository = state.capital_repository
        snapshot = repository.capital_risk_snapshot(self._clock())
        decision = self._read_arm_decision(arm)
        binding = self._shadow_binding(decision)
        reopened = {
            (lot.position_lineage_id, lot.economic_lot_id): lot
            for lot in repository.reopen_exit_obligations()
        }
        lots: list[ExitLotTruth] = []
        for position in snapshot.positions:
            reopen = reopened.get(
                (position.position_lineage_id, position.economic_lot_id)
            )
            successor = self._successor_security_id(
                repository, position.position_lineage_id, position.economic_lot_id
            )
            live_leaves = self._live_exit_leaves(
                state.exit_lane,
                position.position_lineage_id,
                position.economic_lot_id,
            )
            lots.append(
                ExitLotTruth(
                    position_lineage_id=position.position_lineage_id,
                    economic_lot_id=position.economic_lot_id,
                    security_id=position.security_id,
                    producer_namespace=position.producer_namespace,
                    research_program_id=position.research_program_id,
                    economic_lineage_id=position.economic_lineage_id,
                    stage_id=position.stage_id,
                    position_state=position.state,
                    signal_session=decision.counterfactual_key.signal_session,
                    entry_session_ordinal=_ENTRY_SESSION_ORDINAL,
                    entry_plan_evidence_artifact_hash=decision.artifact_hash(),
                    settled_quantity=int(position.settled_quantity),
                    tradable_quantity=int(position.tradable_quantity),
                    live_exit_leaves=live_leaves,
                    successor_security_id=successor,
                    reopen=reopen,
                )
            )
        if not lots:
            return ()
        context = ExitDerivationContext(
            portfolio_id=state.portfolio_id,
            broker_account_id=state.broker_account_id,
            base_currency=state.base_currency,
            mode=ExecutionMode.DAILY_BAR_PROXY,
            capital_version=int(snapshot.capital_version),
            writer_fencing_epoch=int(snapshot.writer_fencing_epoch),
            fixed_exit_policy_fingerprint=state.fixed_exit_policy_fingerprint,
            source_risk_snapshot_id=snapshot.risk_snapshot_id,
            source_risk_snapshot_hash=snapshot.content_hash(),
            trading_sessions=trading_sessions,
        )
        return state.exit_lane.derive_exit_mandates(tuple(lots), context=context)

    def execute_due_exits(
        self,
        arm: TrialArm,
        session: date,
        bars: Mapping[str, DailyBar],
        scenario: ProxyCostScenario,
    ) -> tuple[ShadowExitResult, ...]:
        """Claim, settle, and record every exit mandate due by this session.

        For each claim: record ``SUBMITTED`` against the lane, settle the
        EXIT intent through the shared core (capital fill commits first),
        then record cumulative ``FILLED`` or ``CANCELLED`` and release the
        lease. On ``UNKNOWN`` / ``NO_FILL`` the position and mandate are
        retained for a later session; on ``FILLED`` the shares leave capital
        truth before the lane declares them sold.
        """

        state = self._states[arm]
        lane = state.exit_lane
        decision = self._read_arm_decision(arm)
        binding = self._shadow_binding(decision)
        cycle = decision.counterfactual_key.counterfactual_cycle_id
        command_at = self._clock()
        claims = lane.claim_due_exit_work(
            as_of_session=session, worker_id=_SHADOW_WORKER_ID
        )
        results: list[ShadowExitResult] = []
        for claim in claims:
            result = self._settle_one_exit(
                state=state,
                claim=claim,
                decision=decision,
                binding=binding,
                cycle=cycle,
                bars=bars,
                scenario=scenario,
                command_at=command_at,
            )
            results.append(result)
            lane.release_lease(claim.lease_id, worker_id=_SHADOW_WORKER_ID)
            self._fault(f"lifecycle.after_exit_release:{arm.value}")
        return tuple(results)

    def _settle_one_exit(
        self,
        *,
        state: ShadowArmLifecycleState,
        claim: ClaimedExitWork,
        decision: ShadowDecision,
        binding: CapitalSourceBinding,
        cycle: str,
        bars: Mapping[str, DailyBar],
        scenario: ProxyCostScenario,
        command_at: datetime,
    ) -> ShadowExitResult:
        lane = state.exit_lane
        attempt_id = (
            f"attempt:{claim.exit_mandate_id}:{claim.lease_id.replace('lease:', '')}"
        )
        lane.record_exit_attempt(
            exit_mandate_id=claim.exit_mandate_id,
            attempt_id=attempt_id,
            client_order_id=claim.stable_client_order_id,
            outcome=ExitAttemptOutcome.SUBMITTED,
            submitted_leaves=claim.executable_quantity,
        )
        position = self._position_truth(
            state.capital_repository,
            claim.position_lineage_id,
            claim.economic_lot_id,
        )
        input = ShadowExitSettlementInput(
            trial_id=state.trial_id,
            arm=state.arm,
            cycle_id=cycle,
            attempt_id=attempt_id,
            client_order_id=claim.stable_client_order_id,
            mandate_hash=claim.exit_mandate_id,
            security_id=claim.security_id,
            limit_price_cents=_OPEN_EXIT_LIMIT_CENTS,
            quantity_units=claim.executable_quantity,
            lot_size_units=int(decision.counterfactual_lines[0].lot_size_units),
            position_lineage_id=claim.position_lineage_id,
            economic_lot_id=claim.economic_lot_id,
            attribution=FillAttribution(
                producer_namespace=position.producer_namespace,
                research_program_id=position.research_program_id,
                economic_lineage_id=position.economic_lineage_id,
                stage_id=position.stage_id,
            ),
            source_binding=binding,
        )
        result = state.adapter.settle_exit_line(
            input,
            repository=state.capital_repository,
            bars=bars,
            scenario=scenario,
            command_at=command_at,
            send_deadline=command_at,
        )
        if result.verdict.value == "FILLED":
            lane.record_exit_attempt(
                exit_mandate_id=claim.exit_mandate_id,
                attempt_id=attempt_id,
                client_order_id=claim.stable_client_order_id,
                outcome=ExitAttemptOutcome.FILLED,
                filled_quantity=result.sold_quantity,
            )
        else:
            lane.record_exit_attempt(
                exit_mandate_id=claim.exit_mandate_id,
                attempt_id=attempt_id,
                client_order_id=claim.stable_client_order_id,
                outcome=ExitAttemptOutcome.CANCELLED,
            )
        return result

    # ===================================================================
    # entry reconciliation within a session
    # ===================================================================

    def _settle_session_entries(
        self, arm: TrialArm, session_input: ShadowSessionInput
    ) -> None:
        state = self._states[arm]
        decision = self._read_arm_decision(arm)
        if decision.target_entry_session != session_input.session:
            return  # no entry targets this session
        context = ShadowArmExecutionContext(
            trial_id=state.trial_id,
            arm=arm,
            portfolio_id=state.portfolio_id,
            decision_store=state.decision_store,
            capital_repository=state.capital_repository,
            writer_lease=state.writer_lease,
        )
        state.adapter.execute_entries(
            state.pair_key,
            context,
            mechanical_bindings=session_input.mechanical_bindings,
            bars=session_input.bars,
            scenario=session_input.scenario,
            command_at=session_input.command_at,
            send_deadline=session_input.send_deadline,
            target_session=session_input.session,
        )

    # ===================================================================
    # close valuation
    # ===================================================================

    def close_valuation(
        self,
        arm: TrialArm,
        snapshot_evidence: EvidenceRecord,
        marks: Mapping[str, int],
    ) -> ValuationReceipt:
        """Confirm one close valuation bound to the same-session snapshot.

        Every mark carries a ``SNAPSHOT`` source binding (the valuation is
        evidence-derived); decision-derived fills and fees keep their own
        ``SHADOW_DECISION`` binding. Missing marks for an open position block
        finalization — no stale close is ever substituted.
        """

        state = self._states[arm]
        repository = state.capital_repository
        evidence = snapshot_evidence.evidence
        binding = CapitalSourceBinding(
            mode=ExecutionMode.DAILY_BAR_PROXY,
            artifact_kind=ArtifactKind.SNAPSHOT,
            artifact_id=evidence.evidence_id,
            artifact_hash=snapshot_evidence.artifact_hash(),
        )
        as_of = self._clock()
        request = ValuationRequest(
            idempotency_key=(
                f"shadow-close:{state.trial_id}:{arm.value}:{session_evidence_key(snapshot_evidence)}"
            ),
            source_authority="growth-kernel.shadow.v2",
            effective_at=as_of,
            as_of=as_of,
            expected_stream_version=repository.stream_version(),
            marks=tuple(
                ValuationMarkInput(security_id=sid, price_micros=price)
                for sid, price in marks.items()
            ),
            source_binding=binding,
        )
        receipt, _ = repository.close_valuation(request)
        return receipt

    # ===================================================================
    # session finalize
    # ===================================================================

    def finalize_session(
        self, arm: TrialArm, session: date
    ) -> SessionCheckpointReceipt:
        """Advance the ``SESSION_FINALIZED`` checkpoint and verify the ledger."""

        state = self._states[arm]
        repository = state.capital_repository
        checkpoint = CheckpointService(repository)
        receipt = self._advance_checkpoint(
            repository, checkpoint, "SESSION_FINALIZED", session
        )
        repository.assert_conservation()
        rebuilt, _errors = repository.rebuild_projections()
        if not rebuilt:
            raise ShadowProxyError(
                "shadow_projection_rebuild_failed",
                "capital projection rebuild failed after session finalize",
                arm=arm.value,
                session=session.isoformat(),
            )
        return receipt

    # ===================================================================
    # private helpers
    # ===================================================================

    def _advance_checkpoint(
        self,
        repository: CapitalRepository,
        checkpoint: CheckpointService,
        phase: str,
        session: date,
    ) -> SessionCheckpointReceipt:
        # The checkpoint ladder is the single monotone truth; the shadow
        # lifecycle never writes a second. ORDER_INTENTS_DURABLE is skipped
        # (the durable intent is the committed ShadowDecision pair), so the
        # ladder jumps from PREOPEN_RISK_LOCKED straight to OPEN_RECONCILED.
        return checkpoint.advance(
            SessionCheckpointRequest(
                session=session.isoformat(),
                phase=phase,
                as_of=self._clock(),
                expected_stream_version=repository.stream_version(),
            )
        )

    def _advance_if_missing(
        self,
        repository: CapitalRepository,
        checkpoint: CheckpointService,
        phase: str,
        session: date,
        committed: frozenset[str],
    ) -> None:
        # A phase already committed for this session is not re-advanced: the
        # checkpoint ladder is monotone, so a replay skips past phases and
        # resumes from the first uncommitted one.
        if phase in committed:
            return
        self._advance_checkpoint(repository, checkpoint, phase, session)

    @staticmethod
    def _committed_phases(
        repository: CapitalRepository, session: date
    ) -> frozenset[str]:
        import sqlalchemy as sa

        with repository.engine.connect() as conn:  # noqa: SLF001
            rows = conn.execute(
                sa.text(
                    "SELECT phase FROM session_checkpoints WHERE session = :s"
                ),
                {"s": session.isoformat()},
            ).fetchall()
        return frozenset(str(row.phase) for row in rows)

    def _read_arm_decision(self, arm: TrialArm) -> ShadowDecision:
        state = self._states[arm]
        records = state.decision_store.pair(state.pair_key)
        for record in records:
            if record.arm is arm and isinstance(record.decision, ShadowDecision):
                return record.decision
        raise ShadowProxyError(
            "not_a_shadow_decision",
            "the arm has no committed ShadowDecision to drive the lifecycle",
            arm=arm.value,
        )

    @staticmethod
    def _shadow_binding(decision: ShadowDecision) -> CapitalSourceBinding:
        return CapitalSourceBinding(
            mode=ExecutionMode.DAILY_BAR_PROXY,
            artifact_kind=ArtifactKind.SHADOW_DECISION,
            artifact_id=decision.shadow_decision_id,
            artifact_hash=decision.artifact_hash(),
        )

    @staticmethod
    def _successor_security_id(
        repository: CapitalRepository,
        position_lineage_id: str,
        economic_lot_id: str,
    ) -> str | None:
        for record in repository.corporate_action_records():
            if (
                record.position_lineage_id == position_lineage_id
                and record.economic_lot_id == economic_lot_id
                and record.successor_security_id is not None
            ):
                return record.successor_security_id
        return None

    @staticmethod
    def _live_exit_leaves(
        lane: ExitLane,
        position_lineage_id: str,
        economic_lot_id: str,
    ) -> int:
        projection = lane.exit_state(position_lineage_id, economic_lot_id)
        if projection is None:
            return 0
        return int(projection.live_exit_leaves)

    def _position_truth(
        self,
        repository: CapitalRepository,
        position_lineage_id: str,
        economic_lot_id: str,
    ):
        snapshot = repository.capital_risk_snapshot(self._clock())
        for position in snapshot.positions:
            if (
                position.position_lineage_id == position_lineage_id
                and position.economic_lot_id == economic_lot_id
            ):
                return position
        raise ShadowProxyError(
            "exit_position_missing",
            "a claimed exit mandate names no open capital position",
            position_lineage_id=position_lineage_id,
            economic_lot_id=economic_lot_id,
        )


def session_evidence_key(snapshot_evidence: EvidenceRecord) -> str:
    """A stable key identifying one snapshot evidence for valuation idempotency."""

    evidence = snapshot_evidence.evidence
    return f"{evidence.evidence_id}:r{snapshot_evidence.revision}"


__all__ = [
    "ArmSessionReceipt",
    "PairedLifecycleReceipt",
    "ShadowArmLifecycleState",
    "ShadowProxyLifecycle",
    "ShadowSessionInput",
]
