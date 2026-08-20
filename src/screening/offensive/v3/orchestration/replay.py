"""Disabled official replay entry point plus internal fixture helpers.

``ForwardTrialReplayEngine`` currently holds no capabilities and rejects
before inspecting inputs or resolving a target path. The remaining
module-level mutation helpers are also withdrawn: direct calls reject before
inspecting arguments or writing caller-supplied disposable repositories.
Being absent from ``__all__`` was never an authority boundary. They remain only
as unreachable future contract material and do not establish session-batch or
capital-writer authority.

Two scenarios share the same policy and market facts but differ only in the
cost model:

- ``CURRENT_COST`` reproduces the official pair decisions byte-for-byte (the
  replay store must hold identical rows under the same keys), then drives the
  same ``ShadowProxyLifecycle`` through entry, valuation, and exit sessions,
  and finally compares the restated-final NAV path against the official
  ledgers.
- ``DOUBLE_SLIPPAGE`` re-runs the entire path with 60bps adverse slippage
  from the open-resolution core. Its later decisions may legitimately diverge
  from the official bytes (capital/risk/capacity drift), so they are never
  compared to official; only the temporary replay ledgers and their content
  hashes are persisted, and the stress run appends no official
  EvidenceConsumption entries.

The engine never touches broker/gateway/activation/outbox paths: it is the
same thin boundary as the forward runner plus the capital lifecycle. The
official production driver and the replay engine share one module-level
:func:`drive_session_lifecycle`, so a current-cost replay reproduces the
official capital events, session checkpoints, and restated-final NAV path
byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable, Final, Mapping

from src.screening.offensive.v3.capital.corporate_actions import (
    CorporateActionKind,
    SourceAuthorityTier,
    SplitMergeRequest,
)
from src.screening.offensive.v3.capital.fees import FeePolicy
from src.screening.offensive.v3.capital.nav import (
    RestatementRequest,
    ValuationMarkInput,
)
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts import RationalQuantity
from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.evidence import EvidenceRecord
from src.screening.offensive.v3.contracts.execution import (
    PermitLineMechanicalBinding,
)
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.evidence.regime import (
    ActiveRegimeObservation,
)
from src.screening.offensive.v3.evidence.session_spine import (
    SessionSpine,
    SessionStatus,
)
from src.screening.offensive.v3.execution.lifecycle import DailyBar
from src.screening.offensive.v3.execution.proxy_core import ProxyCostScenario
from src.screening.offensive.v3.gateway.exits import ExitLane
from src.screening.offensive.v3.governance.regime_trial import RegimeTrialBundle
from src.screening.offensive.v3.orchestration.genesis import TrialGenesisManifest
from src.screening.offensive.v3.orchestration.paired_trial import (
    CommittedBtstCandidate,
    REGIME_EVIDENCE_ID,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionRecord,
    TrialArmDecisionStore,
)

#: One frozen fee schedule; both scenarios share it (only slippage differs).
REPLAY_FEE_POLICY: Final[FeePolicy] = FeePolicy(
    fee_policy_version="cn-a-share-30bps-tax.v2",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=1_000,
    transfer_fee_rate_ppm=20,
)

#: The shadow worker identity the lifecycle uses for exit leases.
_SHADOW_WORKER_ID: Final[str] = "shadow-lifecycle"


class ReplayScenario(StrEnum):
    CURRENT_COST = "CURRENT_COST"
    DOUBLE_SLIPPAGE = "DOUBLE_SLIPPAGE"


class TrialReplayError(RuntimeError):
    """Fail-closed rejection of a replay reconstruction."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _reject_shadow_capital_mutation() -> None:
    """Reject direct calls into withdrawn temporary-ledger write helpers."""

    # Lazy import preserves orchestration-package initialization order.
    from src.screening.offensive.v3.execution.shadow_proxy import (
        _reject_shadow_capital_mutation as reject,
    )

    reject()


@dataclass(frozen=True)
class TrialReplayInput:
    """Everything the replay engine may consume; nothing more."""

    trial_id: str
    research_program_id: str
    portfolio_id: str
    bundle: RegimeTrialBundle
    genesis_manifest: TrialGenesisManifest
    archive_root: str | Path
    spine: SessionSpine
    #: The official Evidence Store (read-only): the engine re-reads the
    #: active regime revision at each original cutoff and rejects a facts
    #: bundle that diverges from it (missing/late/revised-after-cutoff).
    evidence_store: object
    trading_sessions: tuple[date, ...]
    #: Per-session PIT facts: SELECTED signal records, same-session snapshot
    #: evidence, and same-session market bars/marks.
    sessions: tuple["ReplaySessionFacts", ...]
    #: The frozen exit-policy fingerprint the trial binds (T+10 open exit).
    fixed_exit_policy_fingerprint: str
    #: The official signal Evidence Store (read-only). It is mandatory for
    #: signal sessions: each SELECTED record and raw payload is independently
    #: re-read and verified at the original cutoff.
    signal_evidence_store: object | None = None
    #: The official decision store CURRENT_COST compares against; required
    #: for CURRENT_COST, ignored (and allowed to be absent) for
    #: DOUBLE_SLIPPAGE whose decisions legitimately diverge.
    official_store: TrialArmDecisionStore | None = None
    #: Optional corporate-action/correction facts applied before each session.
    corporate_actions: tuple["ReplayCorporateAction", ...] = ()
    #: Optional restatement facts applied after each session's close.
    restatements: tuple["ReplayRestatement", ...] = ()
    evidence_id: str = REGIME_EVIDENCE_ID


@dataclass(frozen=True)
class ReplaySessionFacts:
    """One trading session's PIT fact set (all frozen before its cutoff).

    Every trading day the lifecycle must drive carries a facts bundle; only
    signal sessions additionally carry a regime observation and SELECTED
    signal records.
    """

    session: date
    #: The same-session snapshot evidence the close valuation binds. Each
    #: session carries its own evidence id, so the close-valuation
    #: idempotency key is per-session and later sessions never deduplicate
    #: against the first.
    snapshot_evidence: EvidenceRecord
    #: Same-session market bars keyed by security id (entry and exit share
    #: one bar per security per trading session).
    bars: Mapping[str, DailyBar]
    #: Same-session close marks keyed by security id (price micros).
    marks: Mapping[str, int]
    #: The PIT regime observation of a signal session (None on run-out days).
    regime_observation: ActiveRegimeObservation | None = None
    #: Store-verified SELECTED signal records plus exact raw candidates.
    #: ``None`` means the evidence wiring is absent and fails closed for a
    #: signal session; ``()`` is a legitimate, observed empty candidate set.
    selected_candidates: tuple[CommittedBtstCandidate, ...] | None = None


@dataclass(frozen=True)
class ReplayCorporateAction:
    """One immutable corporate-action fact applied before a session's open."""

    session: date
    security_id: str
    position_lineage_id: str
    economic_lot_id: str
    kind: str  # "SPLIT" | "MERGE"
    numerator: int
    denominator: int


@dataclass(frozen=True)
class ReplayRestatement:
    """One corrected mark set restating a prior session's close."""

    session: date
    marks: Mapping[str, int]


@dataclass(frozen=True)
class PairedReplayResult:
    """The durable outcome of one full replay under one scenario."""

    scenario: ReplayScenario
    target_directory: str
    sessions_replayed: int
    #: Both verified capital reports (conservation + projection rebuild).
    champion_capital_report: str
    challenger_capital_report: str
    #: The restated-final NAV path of each arm.
    champion_nav_path_hash: str
    challenger_nav_path_hash: str
    #: Root hashes of the replay decision store and lifecycle checkpoint rows.
    decision_root: str
    lifecycle_root: str
    #: The committed decision pair keys per session (chronological order).
    decision_hashes: tuple[tuple[str, str, str], ...] = ()
    #: Content hashes of the temporary stress ledgers (DOUBLE_SLIPPAGE only).
    stress_ledger_hashes: tuple[str, str] = ()

    @property
    def pair_keys(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(self.decision_hashes)


@dataclass
class _ArmReplay:
    """One arm's disposable replay world (fresh paths, restored genesis).

    ``adapter`` is the execution adapter, typed with a string forward
    reference and imported lazily (see :func:`reserve_pair`).
    """

    repository: CapitalRepository
    adapter: object
    exit_lane: ExitLane


class _ReplayClock:
    """One mutable wall clock the replay drives through the session ladder.

    The adapter, exit lanes, and lifecycle all consume this single clock so
    every timestamp in one phase agrees; the engine advances it to each
    session's close before the lifecycle pass.
    """

    def __init__(self, start: datetime) -> None:
        self.moment = start

    def __call__(self) -> datetime:
        return self.moment


def _require_signal_facts(session: date, facts: ReplaySessionFacts) -> None:
    """Pure lower-layer validation retained while public replay is gated."""

    if facts.regime_observation is None:
        raise TrialReplayError(
            "signal_facts_missing",
            "an enrolled signal session lacks its regime fact",
            session=session.isoformat(),
        )


def _require_scenario_inputs(
    input: TrialReplayInput,
    scenario: ReplayScenario,
) -> None:
    """Pure scenario-shape validation retained behind the authority gate."""

    if scenario is ReplayScenario.CURRENT_COST and input.official_store is None:
        raise TrialReplayError(
            "official_store_required",
            "CURRENT_COST replay requires the official decision store",
        )


class ForwardTrialReplayEngine:
    """Disabled replay entry point with no ambient capabilities."""

    __slots__ = ()

    # ===================================================================
    # public entry point
    # ===================================================================

    def replay(
        self,
        input: TrialReplayInput,
        scenario: ReplayScenario,
        target_directory: str | Path,
    ) -> PairedReplayResult:
        """Reject before parsing inputs, resolving paths or restoring capital."""

        raise TrialReplayError(
            "forward_input_authority_unavailable",
            "authoritative forward session batch root is not implemented",
        )


# ===================================================================
# shared session driver (official production and replay consume the same
# lifecycle pass so a current-cost replay reproduces the official capital
# events, session checkpoints, and restated-final NAV path byte-for-byte)
# ===================================================================


def reserve_pair(
    *,
    input: TrialReplayInput,
    arms: Mapping[TrialArm, _ArmReplay],
    replay_store: TrialArmDecisionStore,
    lease,
    pair_key: tuple[str, str, str],
) -> None:
    """Reserve the worst-case entry cash of a freshly committed pair for both
    arms (the first capital write of the signal session)."""

    _reject_shadow_capital_mutation()

    from src.screening.offensive.v3.execution.shadow_proxy import (
        ShadowArmExecutionContext,
    )

    # Each arm's proxy store records its own reserve facts; the adapter is
    # per-arm, so both adapters must reserve (a single call would leave the
    # other arm's lines without their RESERVE_COMMITTED fact).  Build the
    # two-arm context map once, then drive each adapter over the same map.
    contexts = {
        context_arm: ShadowArmExecutionContext(
            trial_id=input.trial_id,
            arm=context_arm,
            portfolio_id=input.portfolio_id,
            decision_store=replay_store,
            capital_repository=arms[context_arm].repository,
            writer_lease=lease,
        )
        for context_arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
    }
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        arms[arm].adapter.reserve_committed_pair(pair_key, contexts)


def drive_session_lifecycle(
    *,
    input: TrialReplayInput,
    arms: Mapping[TrialArm, _ArmReplay],
    replay_store: TrialArmDecisionStore,
    lease,
    pair_key: tuple[str, str, str],
    session: date,
    facts: ReplaySessionFacts,
    scenario_cost: ProxyCostScenario,
    clock: Callable[[], datetime],
) -> None:
    """Drive one trading session's fixed ladder for both arms.

    The pair referenced by ``pair_key`` is the most recent committed pair
    carrying a ``ShadowDecision``; entry settlement is guarded by the
    decision's own ``target_entry_session`` and exit mandates keep their
    frozen due date.

    The lifecycle facade is imported here (not at module level) so the
    orchestration package can be imported while the execution package is
    still mid-initialization — ``execution.shadow_lifecycle`` imports
    ``orchestration.trial_store``, which triggers ``orchestration/__init__``.
    """

    _reject_shadow_capital_mutation()

    from src.screening.offensive.v3.execution.shadow_lifecycle import (
        ShadowArmLifecycleState,
        ShadowProxyLifecycle,
        ShadowSessionInput,
    )
    from src.screening.offensive.v3.execution.shadow_proxy import (
        ShadowArmExecutionContext,
    )

    contexts = {
        arm: ShadowArmExecutionContext(
            trial_id=input.trial_id,
            arm=arm,
            portfolio_id=input.portfolio_id,
            decision_store=replay_store,
            capital_repository=arms[arm].repository,
            writer_lease=lease,
        )
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
    }
    states = {
        arm: ShadowArmLifecycleState(
            trial_id=input.trial_id,
            arm=arm,
            portfolio_id=input.portfolio_id,
            pair_key=pair_key,
            base_currency="CNY",
            broker_account_id=None,
            fixed_exit_policy_fingerprint=input.fixed_exit_policy_fingerprint,
            decision_store=replay_store,
            capital_repository=arms[arm].repository,
            exit_lane=arms[arm].exit_lane,
            adapter=arms[arm].adapter,
            writer_lease=lease,
        )
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
    }
    lifecycle = ShadowProxyLifecycle(states, clock=clock)
    # Corporate actions land before the session's open.
    for action in (
        a for a in input.corporate_actions if a.session == session
    ):
        apply_corporate_action(
            arms=arms, action=action, as_of=_session_open(session)
        )
    lifecycle.advance_session(
        ShadowSessionInput(
            session=session,
            trading_sessions=input.trading_sessions,
            bars=dict(facts.bars),
            marks=dict(facts.marks),
            snapshot_evidence=facts.snapshot_evidence,
            scenario=scenario_cost,
            command_at=_session_open(session),
            send_deadline=_session_cutoff(session),
            as_of=_session_close(session),
            mechanical_bindings=_mechanical_bindings(
                replay_store=replay_store, pair_key=pair_key
            ),
        ),
        contexts,
    )


def apply_corporate_action(
    *,
    arms: Mapping[TrialArm, _ArmReplay],
    action: ReplayCorporateAction,
    as_of: datetime,
) -> None:
    """Apply one split/merge to both arm ledgers before a session's open."""

    _reject_shadow_capital_mutation()

    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        repo = arms[arm].repository
        repo.apply_split_merge(
            SplitMergeRequest(
                action_id=(
                    f"replay:{action.kind}:{action.session.isoformat()}"
                    f":{arm.value}"
                ),
                position_lineage_id=action.position_lineage_id,
                economic_lot_id=action.economic_lot_id,
                security_id=action.security_id,
                action_kind=(
                    CorporateActionKind.SPLIT
                    if action.kind == "SPLIT"
                    else CorporateActionKind.MERGE
                ),
                ratio=RationalQuantity(
                    numerator=action.numerator,
                    denominator=action.denominator,
                ),
                tier=SourceAuthorityTier.CONFIRMED,
                source_authority="replay.corporate-actions",
                effective_at=as_of,
                as_of=as_of,
                expected_stream_version=repo.stream_version(),
            )
        )


def apply_restatement(
    *,
    arms: Mapping[TrialArm, _ArmReplay],
    restatement: ReplayRestatement,
    clock: Callable[[], datetime],
) -> None:
    """Restate one session's close with corrected marks on both arm ledgers."""

    _reject_shadow_capital_mutation()

    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        repo = arms[arm].repository
        repo.restate_valuation(
            RestatementRequest(
                idempotency_key=(
                    f"replay:restate:{restatement.session.isoformat()}"
                    f":{arm.value}"
                ),
                restates_event_id=_as_observed_event_id(
                    repo, restatement.session
                ),
                source_authority="replay.restatements",
                effective_at=clock(),
                as_of=clock(),
                expected_stream_version=repo.stream_version(),
                marks=tuple(
                    ValuationMarkInput(
                        security_id=sid, price_micros=price
                    )
                    for sid, price in restatement.marks.items()
                ),
            )
        )


def _as_observed_event_id(
    repo: CapitalRepository, session: date
) -> str:
    """The as-observed valuation event id of one session's close."""

    path = repo.nav_projections()
    for observation in path.as_observed:
        if observation.as_of.date() == session:
            return observation.created_by_event_id
    raise TrialReplayError(
        "as_observed_valuation_missing",
        "no as-observed valuation for the restatement target session",
        session=session.isoformat(),
    )


# ===================================================================
# scenario helpers
# ===================================================================


def scenario_cost(scenario: ReplayScenario) -> ProxyCostScenario:
    if scenario is ReplayScenario.DOUBLE_SLIPPAGE:
        return ProxyCostScenario(
            scenario_id="double-slippage",
            entry_slippage_bps=60,
            exit_slippage_bps=60,
            fee_policy=REPLAY_FEE_POLICY,
        )
    return ProxyCostScenario(
        scenario_id="current-cost",
        entry_slippage_bps=30,
        exit_slippage_bps=30,
        fee_policy=REPLAY_FEE_POLICY,
    )


def _decision_cycle_id(session: date) -> str:
    return f"daily-action-{session.isoformat()}"


def _session_cutoff(session: date) -> datetime:
    # The post-close decision instant: the regime observation (observed
    # 14:00) and the BTST signals (observed 15:00) are both committed
    # strictly before it, so a PIT read at this instant sees exactly the
    # revisions the official driver consumed.
    return datetime(
        session.year, session.month, session.day, 15, 30, tzinfo=timezone.utc
    )


def _session_open(session: date) -> datetime:
    return datetime(
        session.year, session.month, session.day, 9, 30, tzinfo=timezone.utc
    )


def _session_close(session: date) -> datetime:
    return datetime(
        session.year, session.month, session.day, 16, 0, tzinfo=timezone.utc
    )


def _mechanical_bindings(
    *,
    replay_store: TrialArmDecisionStore,
    pair_key: tuple[str, str, str],
) -> dict[str, PermitLineMechanicalBinding]:
    """Unchanged-quantity frozen caps for every shadow line (no shrink)."""

    bindings: dict[str, PermitLineMechanicalBinding] = {}
    for record in replay_store.pair(pair_key):
        decision = record.decision
        if not isinstance(decision, ShadowDecision):
            continue
        for line in decision.counterfactual_lines:
            bindings[line.shadow_line_id] = PermitLineMechanicalBinding(
                order_line_id=line.shadow_line_id,
                predicate_policy_version=line.execution_assumption_version,
                preopen_fact_snapshot_id="preopen-facts-shadow-1",
                preopen_fact_snapshot_hash=line.evidence_artifact_hash,
                preopen_fact_as_of=_session_cutoff(
                    decision.counterfactual_key.signal_session
                ),
                availability_cap_units=line.target_quantity_units,
                price_cap_units=line.target_quantity_units,
                capacity_cap_units=line.target_quantity_units,
                cash_cap_units=line.target_quantity_units,
                capital_risk_cap_units=line.target_quantity_units,
            )
    return bindings


def _capital_report(repository: CapitalRepository) -> str:
    """The verified capital report: conservation + projection rebuild."""

    conservation = repository.assert_conservation()
    rebuilt, errors = repository.rebuild_projections()
    if not rebuilt:
        raise TrialReplayError(
            "projection_rebuild_failed",
            "replay ledger failed conservation/projection rebuild",
            errors=list(errors),
        )
    return f"{conservation}:{rebuilt}"


def _nav_path_hash(repository: CapitalRepository) -> str:
    """Content hash of the restated-final NAV path (as-observed + restated)."""

    import hashlib

    path = repository.nav_projections()
    return hashlib.sha256(
        path.model_dump_json().encode("utf-8")
    ).hexdigest()


def _decision_root(
    store: TrialArmDecisionStore,
    pair_keys: tuple[tuple[str, str, str], ...],
) -> str:
    """Deterministic content root of the replay decision store.

    The root is the sha256 of the canonical JSON of every committed pair in
    chronological order — never the raw SQLite file bytes, which depend on
    WAL/freelist state. A second replay of the same timeline reproduces the
    same root.
    """

    import hashlib

    parts: list[str] = []
    for key in pair_keys:
        rows = store.pair(key)
        by_arm = {row.arm: row for row in rows}
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
            parts.append(by_arm[arm].model_dump_json())
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _checkpoint_root(
    repositories: tuple[CapitalRepository, ...],
) -> str:
    """Deterministic root of both arms' session checkpoint rows."""

    import hashlib

    import sqlalchemy as sa

    rows: list[str] = []
    for repository in repositories:
        with repository.engine.connect() as conn:
            for row in conn.execute(
                sa.text(
                    "SELECT session, phase, stream_version, recorded_at"
                    " FROM session_checkpoints ORDER BY session, phase"
                )
            ).all():
                rows.append(
                    "|".join(str(value) for value in row)
                )
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _ledger_root(repository: CapitalRepository) -> str:
    """Deterministic content root of one temporary stress ledger.

    The root covers the economic event stream, the NAV path, and the session
    checkpoints of one arm — the full capital truth the stress run produced.
    """

    import hashlib

    import sqlalchemy as sa

    rows: list[str] = []
    with repository.engine.connect() as conn:
        for row in conn.execute(
            sa.text(
                "SELECT canonical_event_json FROM economic_events"
                " ORDER BY stream_version"
            )
        ).all():
            rows.append(str(row.canonical_event_json))
        for row in conn.execute(
            sa.text(
                "SELECT nav_observation_id, observation_kind,"
                " supersedes_observation_id, as_of, recorded_at,"
                " capital_version, created_by_event_id, nav_cents,"
                " issued_unit_quanta, live_unit_quanta,"
                " unit_price_numerator, unit_price_denominator,"
                " log_growth_kind, log_growth_nav_numerator,"
                " log_growth_nav_denominator FROM nav_observations"
                " ORDER BY rowid"
            )
        ).all():
            rows.append("|".join(str(value) for value in row))
        for row in conn.execute(
            sa.text(
                "SELECT session, phase, stream_version, recorded_at"
                " FROM session_checkpoints ORDER BY session, phase"
            )
        ).all():
            rows.append("|".join(str(value) for value in row))
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


__all__ = [
    "ForwardTrialReplayEngine",
    "PairedReplayResult",
    "REPLAY_FEE_POLICY",
    "ReplayCorporateAction",
    "ReplayRestatement",
    "ReplayScenario",
    "ReplaySessionFacts",
    "TrialReplayError",
    "TrialReplayInput",
]
