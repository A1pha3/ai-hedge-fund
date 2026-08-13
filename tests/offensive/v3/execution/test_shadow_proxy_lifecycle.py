"""Plan Task 10 RED: the complete shadow capital lifecycle facade.

``ShadowProxyLifecycle`` drives one trading session of a paired shadow trial
through the fixed ladder for both arms: corporate-actions + preopen-risk
checkpoints, exit reconciliation, entry reconciliation, the shared
``OPEN_RECONCILED`` advance, close valuation bound to the same-session
SnapshotEvidence, and session finalize. Both arms consume the same close
marks but produce arm-specific NAV; missing marks block close finalization
with no stale substitute; a crashed exit fill converges on exact replay.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(
    reason="future contract: requires capital-local shadow writer fencing"
)

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.base import content_hash
from src.screening.offensive.v3.contracts.decision import (
    CounterfactualDecisionKey,
    ShadowDecision,
    ShadowTradingScheduleBinding,
)
from src.screening.offensive.v3.contracts.evidence import (
    SUPPORTED_SCHEMA_MAJOR,
    EvidenceRecord,
    EvidenceScope,
    SnapshotEvidence,
)
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.execution.lifecycle import (
    DailyBar,
    OpenExecutionVerdict,
)
from src.screening.offensive.v3.execution.proxy_core import ProxyCostScenario
from src.screening.offensive.v3.execution.shadow_lifecycle import (  # RED target
    ShadowArmLifecycleState,
    ShadowProxyLifecycle,
    ShadowSessionInput,
)
from src.screening.offensive.v3.execution.shadow_proxy import ShadowProxyAdapter

_ENTRY_TEST_DIR = Path(__file__).resolve().parent
if str(_ENTRY_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_ENTRY_TEST_DIR))
from test_shadow_proxy_entry import (  # noqa: E402
    COMMAND_AT,
    HASH,
    NOW,
    PORTFOLIO,
    RECORDED_AT,
    SEND_DEADLINE,
    SIGNAL_DATE,
    TRIAL_ID,
    _Clock,
    _cost_scenario,
    _funded_repo,
    _mechanical_bindings,
    _pair_key,
    _paired_decisions,
    _record,
    _touching_bars,
)
from test_shadow_proxy_exit import (  # noqa: E402
    ENTRY_SESSION,
    EXIT_DUE_SESSION,
    TRADING_SESSIONS,
    _LifecycleWorld,
    _exit_bar,
)

UTC = timezone.utc
_EXIT_POLICY_FINGERPRINT = HASH
_SECURITY = "300001.SZ"
# 1000.0000 yuan per share in integer price micros (the valuation mark unit).
_MARK_PRICE_MICROS = 10_000_000


def _snapshot_record(evidence_id: str, observed: datetime) -> EvidenceRecord:
    """A minimal valid SnapshotEvidence wrapped in its store record."""

    available = observed + timedelta(minutes=1)
    evidence = SnapshotEvidence(
        evidence_id=evidence_id,
        subject_scope=EvidenceScope.GLOBAL,
        subject_producer="market.test",
        family_id=None,
        strategy_semver="3.0.0",
        behavior_fingerprint=HASH,
        policy_epoch=1,
        execution_version="readiness.v2",
        cost_version="cn-a-share-costs.v1",
        effective_at=observed,
        provider_published_at=observed,
        observed_at=observed,
        available_at=available,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority="market.publisher",
        payload_content_hash=HASH,
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="snapshot",
    )
    return EvidenceRecord[SnapshotEvidence](
        evidence=evidence,
        ingested_at=observed,
        commit_sequence=1,
        revision=1,
        supersedes_revision=None,
        active_revision=1,
    )


def _entry_session_input(
    world: _LifecycleWorld,
    *,
    marks: dict[str, int] | None = None,
    scenario: ProxyCostScenario | None = None,
) -> ShadowSessionInput:
    decision = world.decisions[TrialArm.CHAMPION]
    return ShadowSessionInput(
        session=ENTRY_SESSION,
        trading_sessions=TRADING_SESSIONS,
        bars=_touching_bars(decision),
        marks=marks if marks is not None else {_SECURITY: _MARK_PRICE_MICROS},
        snapshot_evidence=_snapshot_record(
            f"snap-{ENTRY_SESSION.isoformat()}", _session_close(ENTRY_SESSION)
        ),
        scenario=scenario or _cost_scenario(30),
        command_at=COMMAND_AT,
        send_deadline=SEND_DEADLINE,
        as_of=_session_close(ENTRY_SESSION),
        mechanical_bindings=_mechanical_bindings(decision),
    )


def _session_close(session: date) -> datetime:
    return datetime(session.year, session.month, session.day, 16, 0, tzinfo=UTC)


def _next_cycle_decision(decision: ShadowDecision) -> ShadowDecision:
    """A valid S2 decision reusing the same line id/security after S1."""

    signal = ENTRY_SESSION
    following = TRADING_SESSIONS[2:12]
    schedule_values = {
        "calendar_id": decision.trading_session_schedule_binding.calendar_id,
        "calendar_version": (
            decision.trading_session_schedule_binding.calendar_version
        ),
        "calendar_artifact_hash": (
            decision.trading_session_schedule_binding.calendar_artifact_hash
        ),
        "signal_session": signal,
        "following_sessions": following,
        "available_at": decision.trading_session_schedule_binding.available_at,
    }
    schedule = ShadowTradingScheduleBinding(
        **schedule_values,
        schedule_hash=content_hash(schedule_values),
    )
    cycle = f"daily-action-{signal.isoformat()}"
    lines = tuple(
        line.model_copy(update={"target_exit_session": following[9]})
        for line in decision.counterfactual_lines
    )
    candidate = decision.model_copy(
        update={
            "shadow_decision_id": f"{decision.shadow_decision_id}:s2",
            "counterfactual_key": CounterfactualDecisionKey(
                portfolio_id=PORTFOLIO,
                signal_session=signal,
                counterfactual_cycle_id=cycle,
            ),
            "target_entry_session": following[0],
            "trading_session_schedule_binding": schedule,
            "counterfactual_lines": lines,
        }
    )
    return ShadowDecision.model_validate(candidate.model_dump(mode="python"))


def _lifecycle_for_pair(world: _LifecycleWorld, pair_key):
    states = {}
    for arm, state in world._states().items():
        states[arm] = state.__class__(
            **{**state.__dict__, "pair_key": pair_key}
        )
    return ShadowProxyLifecycle(states, clock=world.clock)


def _commit_no_trade_pair(world: _LifecycleWorld):
    from src.screening.offensive.v3.kernel.models import (
        BlockReason,
        NoTradeDecision,
    )
    from src.screening.offensive.v3.orchestration.trial_store import (
        TrialArmDecisionRecord,
    )

    signal = ENTRY_SESSION
    cycle = f"no-trade-{signal.isoformat()}"
    rows = []
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        decision = NoTradeDecision(
            portfolio_id=PORTFOLIO,
            signal_session=signal,
            decision_cycle_id=cycle,
            reason=BlockReason.NO_SIGNAL,
        )
        rows.append(
            TrialArmDecisionRecord(
                trial_id=TRIAL_ID,
                signal_session=signal,
                decision_cycle_id=cycle,
                arm=arm,
                shared_input_hash=f"{signal.isoformat()}/{cycle}",
                arm_policy_fingerprint=None,
                arm_capital_checkpoint_hash=HASH,
                regime_observation_hash=HASH,
                decision=decision,
                created_at=NOW,
                artifact_hash=decision.content_hash(),
            )
        )
    world.store.commit_pair(rows[0], rows[1])
    return (TRIAL_ID, signal.isoformat(), cycle)


@pytest.fixture()
def world(tmp_path: Path) -> _LifecycleWorld:
    return _LifecycleWorld(tmp_path)


# =============================================================================
# Step 2: full entry-session advance (entries + valuation + checkpoints)
# =============================================================================


def test_advance_entry_session_settles_values_and_finalizes(world) -> None:
    arm = TrialArm.CHAMPION
    # Reserve both arms at T0 first (a paired trial reserves both before any
    # session; the entry settle requires a committed reserve per arm).
    world.clock._moment = COMMAND_AT  # noqa: SLF001
    from src.screening.offensive.v3.execution.shadow_proxy import (
        ShadowArmExecutionContext,
    )

    contexts = {
        arm: ShadowArmExecutionContext(
            trial_id=TRIAL_ID,
            arm=arm,
            portfolio_id=PORTFOLIO,
            decision_store=world.store,
            capital_repository=world.capital[arm],
            writer_lease=world.lease,
        )
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
    }
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        world.adapters[arm].reserve_committed_pair(world.pair_key, {arm: contexts[arm]})
    world.clock._moment = _session_close(ENTRY_SESSION)  # noqa: SLF001
    receipt = world.lifecycle.advance_session(
        _entry_session_input(world), world._states_to_contexts()
    )
    arm_receipt = receipt.arms[arm]
    assert arm_receipt.valuation is not None
    assert arm_receipt.valuation.nav_cents > 0
    assert arm_receipt.finalized is not None
    assert arm_receipt.finalized.phase == "SESSION_FINALIZED"
    # The entry settled inside the session: a position is now open.
    snap = world.capital[arm].capital_risk_snapshot(world.clock())
    assert len(snap.positions) == 1
    assert int(snap.positions[0].settled_quantity) > 0
    world.capital[arm].assert_conservation()


def test_both_arms_share_marks_but_keep_independent_nav(world) -> None:
    # Reserve both arms at T0.
    from src.screening.offensive.v3.execution.shadow_proxy import (
        ShadowArmExecutionContext,
    )

    world.clock._moment = COMMAND_AT  # noqa: SLF001
    contexts = {
        arm: ShadowArmExecutionContext(
            trial_id=TRIAL_ID,
            arm=arm,
            portfolio_id=PORTFOLIO,
            decision_store=world.store,
            capital_repository=world.capital[arm],
            writer_lease=world.lease,
        )
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
    }
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        world.adapters[arm].reserve_committed_pair(world.pair_key, {arm: contexts[arm]})
    world.clock._moment = _session_close(ENTRY_SESSION)  # noqa: SLF001
    receipt = world.lifecycle.advance_session(
        _entry_session_input(world), world._states_to_contexts()
    )
    champ_nav = receipt.arms[TrialArm.CHAMPION].valuation.nav_cents
    chall_nav = receipt.arms[TrialArm.CHALLENGER].valuation.nav_cents
    # Both arms consumed the same close marks and the same entry economics;
    # their NAV is observed independently per ledger but must agree here.
    assert champ_nav == chall_nav
    assert champ_nav > 0


def test_missing_mark_blocks_close_finalization(world) -> None:
    arm = TrialArm.CHAMPION
    from src.screening.offensive.v3.execution.shadow_proxy import (
        ShadowArmExecutionContext,
    )

    world.clock._moment = COMMAND_AT  # noqa: SLF001
    contexts = {
        arm: ShadowArmExecutionContext(
            trial_id=TRIAL_ID,
            arm=arm,
            portfolio_id=PORTFOLIO,
            decision_store=world.store,
            capital_repository=world.capital[arm],
            writer_lease=world.lease,
        )
    }
    world.adapters[arm].reserve_committed_pair(world.pair_key, contexts)
    world.clock._moment = _session_close(ENTRY_SESSION)  # noqa: SLF001
    # An open position with no mark must block close finalization; no stale
    # close is substituted.
    with pytest.raises(Exception, match="valuation_mark_missing"):
        world.lifecycle.advance_session(
            _entry_session_input(world, marks={}), world._states_to_contexts()
        )


# =============================================================================
# Step 2: exit-session advance closes the position
# =============================================================================


def test_advance_exit_session_closes_position(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    assert held > 0
    world.clock._moment = _session_close(EXIT_DUE_SESSION)  # noqa: SLF001
    session_input = ShadowSessionInput(
        session=EXIT_DUE_SESSION,
        trading_sessions=TRADING_SESSIONS,
        bars={_SECURITY: _exit_bar(EXIT_DUE_SESSION)},
        marks={},  # position closes inside the session -> liquid valuation
        snapshot_evidence=_snapshot_record(
            f"snap-{EXIT_DUE_SESSION.isoformat()}", _session_close(EXIT_DUE_SESSION)
        ),
        scenario=_cost_scenario(30),
        command_at=COMMAND_AT,
        send_deadline=SEND_DEADLINE,
        as_of=_session_close(EXIT_DUE_SESSION),
    )
    receipt = world.lifecycle.advance_session(
        session_input, world._states_to_contexts()
    )
    exits = receipt.arms[arm].exits
    assert len(exits) == 1
    assert exits[0].verdict is OpenExecutionVerdict.FILLED
    assert exits[0].sold_quantity == held
    assert world.position_quantity(arm) == 0
    world.capital[arm].assert_conservation()


def test_runout_session_after_entry_reconciles_without_duplicate_entry(world) -> None:
    """Task 12: one committed pair, many trading sessions.

    The replay engine drives every session of the fixed ladder through the
    same lifecycle; after the entry session, a later run-out session must
    reconcile the still-open position without settling the entry again
    (``target_entry_session`` guards the settle) and without refreshing the
    exit mandate (``_essentials_unchanged`` keeps the frozen due date).
    """

    arm = TrialArm.CHAMPION
    from src.screening.offensive.v3.execution.shadow_proxy import (
        ShadowArmExecutionContext,
    )

    # Full entry session: reserve at T0, advance the entry session.
    world.clock._moment = COMMAND_AT  # noqa: SLF001
    contexts = {
        arm: ShadowArmExecutionContext(
            trial_id=TRIAL_ID,
            arm=arm,
            portfolio_id=PORTFOLIO,
            decision_store=world.store,
            capital_repository=world.capital[arm],
            writer_lease=world.lease,
        )
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
    }
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        world.adapters[arm].reserve_committed_pair(world.pair_key, {arm: contexts[arm]})
    world.clock._moment = _session_close(ENTRY_SESSION)  # noqa: SLF001
    world.lifecycle.advance_session(
        _entry_session_input(world), world._states_to_contexts()
    )
    held = world.position_quantity(arm)
    assert held > 0
    # Derive the exit mandate once (its due date is frozen by the lane).
    (mandate,) = world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    assert mandate.due_session == EXIT_DUE_SESSION

    # One run-out session between entry and exit due (08-07): no entry settle
    # (the decision targets 08-06), no mandate refresh, position untouched.
    runout = date(2026, 8, 7)
    world.clock._moment = _session_close(runout)  # noqa: SLF001
    receipt = world.lifecycle.advance_session(
        ShadowSessionInput(
            session=runout,
            trading_sessions=TRADING_SESSIONS,
            bars={_SECURITY: _exit_bar(runout)},
            marks={_SECURITY: _MARK_PRICE_MICROS},
            snapshot_evidence=_snapshot_record(
                f"snap-{runout.isoformat()}", _session_close(runout)
            ),
            scenario=_cost_scenario(30),
            command_at=COMMAND_AT,
            send_deadline=SEND_DEADLINE,
            as_of=_session_close(runout),
        ),
        world._states_to_contexts(),
    )
    assert receipt.arms[arm].exits == ()
    assert world.position_quantity(arm) == held
    # Re-deriving exits on a later session keeps one mandate with the same
    # frozen due date and quantity (no revision churn on unchanged essentials).
    refreshed = world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    assert len(refreshed) == 1
    assert refreshed[0].due_session == EXIT_DUE_SESSION
    assert refreshed[0].tradable_quantity == held
    world.capital[arm].assert_conservation()


# =============================================================================
# Step 2: corporate action (split) preserves the exit obligation
# =============================================================================


def test_split_refreshes_exit_mandate_without_duplicate(world) -> None:
    from src.screening.offensive.v3.capital.corporate_actions import (
        CorporateActionKind,
        SourceAuthorityTier,
        SplitMergeRequest,
    )
    from src.screening.offensive.v3.contracts import RationalQuantity

    arm = TrialArm.CHAMPION
    world.open_position(arm)
    (mandate,) = world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    assert mandate.tradable_quantity == held
    lineage, lot = world.lot_key(arm)
    repository = world.capital[arm]
    # A 2:1 split applied through the existing capital primitive doubles the
    # position; mode and attribution are preserved.
    split_at = _session_close(ENTRY_SESSION) + timedelta(days=1)
    repository.apply_split_merge(
        SplitMergeRequest(
            action_id="split-2026-1",
            position_lineage_id=lineage,
            economic_lot_id=lot,
            security_id=_SECURITY,
            action_kind=CorporateActionKind.SPLIT,
            ratio=RationalQuantity(numerator=2, denominator=1),
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="exchange.test",
            effective_at=split_at,
            as_of=split_at + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert world.position_quantity(arm) == held * 2
    # Re-deriving exits refreshes the single mandate to the new quantity
    # (one active obligation, not a duplicate outcome).
    refreshed = world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    assert len(refreshed) == 1
    assert refreshed[0].tradable_quantity == held * 2
    assert refreshed[0].mandate_revision > mandate.mandate_revision
    repository.assert_conservation()


def test_overlapping_cycles_keep_independent_lot_origins_and_due_dates(
    world,
) -> None:
    """S2 must not merge, relabel, or postpone the still-open S1 lot."""

    from src.screening.offensive.v3.execution.shadow_proxy import (
        ShadowArmExecutionContext,
    )

    arm = TrialArm.CHAMPION
    world.open_position(arm)
    (s1_mandate,) = world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    assert s1_mandate.due_session == EXIT_DUE_SESSION

    s2_decisions = {
        candidate_arm: _next_cycle_decision(world.decisions[candidate_arm])
        for candidate_arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
    }
    world.store.commit_pair(
        _record(TrialArm.CHAMPION, s2_decisions[TrialArm.CHAMPION]),
        _record(TrialArm.CHALLENGER, s2_decisions[TrialArm.CHALLENGER]),
    )
    s2_pair_key = _pair_key(s2_decisions[arm])
    lifecycle = _lifecycle_for_pair(world, s2_pair_key)
    context = ShadowArmExecutionContext(
        trial_id=TRIAL_ID,
        arm=arm,
        portfolio_id=PORTFOLIO,
        decision_store=world.store,
        capital_repository=world.capital[arm],
        writer_lease=world.lease,
    )
    world.clock._moment = datetime(2026, 8, 6, 16, 0, tzinfo=UTC)  # noqa: SLF001
    world.adapters[arm].reserve_committed_pair(s2_pair_key, {arm: context})
    world.clock._moment = datetime(2026, 8, 7, 1, 25, tzinfo=UTC)  # noqa: SLF001
    world.adapters[arm].execute_entries(
        s2_pair_key,
        context,
        mechanical_bindings=_mechanical_bindings(s2_decisions[arm]),
        bars=_touching_bars(s2_decisions[arm]),
        scenario=_cost_scenario(30),
        command_at=datetime(2026, 8, 6, 16, 0, tzinfo=UTC),
        send_deadline=datetime(2026, 8, 7, 9, 25, tzinfo=UTC),
        target_session=date(2026, 8, 7),
    )

    positions = world.capital[arm].capital_risk_snapshot(world.clock()).positions
    assert len(positions) == 2
    assert {
        position.position_lineage_id for position in positions
    }.isdisjoint({position.economic_lineage_id for position in positions})
    assert {position.economic_lineage_id for position in positions} == {
        world.champion_decision.economic_lineage_id
    }
    assert len({position.economic_lot_id for position in positions}) == 2
    mandates = lifecycle.derive_exits(arm, TRADING_SESSIONS)
    assert {mandate.due_session for mandate in mandates} == {
        date(2026, 8, 19),
        date(2026, 8, 20),
    }
    assert {
        mandate.due_session: mandate.entry_plan_evidence_artifact_hash
        for mandate in mandates
    } == {
        date(2026, 8, 19): world.champion_decision.artifact_hash(),
        date(2026, 8, 20): s2_decisions[arm].artifact_hash(),
    }
    world.clock._moment = _session_close(date(2026, 8, 19))  # noqa: SLF001
    s1_exit = lifecycle.execute_due_exits(
        arm,
        date(2026, 8, 19),
        {_SECURITY: _exit_bar(date(2026, 8, 19))},
        _cost_scenario(30),
    )
    assert len(s1_exit) == 1
    assert s1_exit[0].sold_quantity == 100
    remaining = world.capital[arm].capital_risk_snapshot(world.clock()).positions
    assert len(remaining) == 1
    assert int(remaining[0].settled_quantity) == 100
    s2_state = world.exit_lanes[arm].exit_state(
        remaining[0].position_lineage_id,
        remaining[0].economic_lot_id,
    )
    assert s2_state is not None
    assert s2_state.due_session == date(2026, 8, 20)

    world.clock._moment = _session_close(date(2026, 8, 20))  # noqa: SLF001
    s2_exit = lifecycle.execute_due_exits(
        arm,
        date(2026, 8, 20),
        {_SECURITY: _exit_bar(date(2026, 8, 20))},
        _cost_scenario(30),
    )
    assert len(s2_exit) == 1
    assert s2_exit[0].sold_quantity == 100
    assert world.position_quantity(arm) == 0
    world.capital[arm].assert_conservation()


def test_no_trade_new_pair_cannot_block_old_lot_exit_or_valuation(world) -> None:
    """A current NoTrade pair has no entry work, but old exits stay live."""

    arm = TrialArm.CHAMPION
    world.open_position(arm)
    held = world.position_quantity(arm)
    pair_key = _commit_no_trade_pair(world)
    lifecycle = _lifecycle_for_pair(world, pair_key)
    world.clock._moment = _session_close(EXIT_DUE_SESSION)  # noqa: SLF001
    receipt = lifecycle.advance_session(
        ShadowSessionInput(
            session=EXIT_DUE_SESSION,
            trading_sessions=TRADING_SESSIONS,
            bars={_SECURITY: _exit_bar(EXIT_DUE_SESSION)},
            marks={},
            snapshot_evidence=_snapshot_record(
                f"snap-{EXIT_DUE_SESSION.isoformat()}",
                _session_close(EXIT_DUE_SESSION),
            ),
            scenario=_cost_scenario(30),
            command_at=datetime(
                EXIT_DUE_SESSION.year,
                EXIT_DUE_SESSION.month,
                EXIT_DUE_SESSION.day,
                9,
                20,
                tzinfo=UTC,
            ),
            send_deadline=datetime(
                EXIT_DUE_SESSION.year,
                EXIT_DUE_SESSION.month,
                EXIT_DUE_SESSION.day,
                9,
                25,
                tzinfo=UTC,
            ),
            as_of=_session_close(EXIT_DUE_SESSION),
        ),
        world._states_to_contexts(),
    )

    champion = receipt.arms[arm]
    assert len(champion.exits) == 1
    assert champion.exits[0].sold_quantity == held
    assert champion.valuation is not None
    assert champion.finalized is not None
    assert world.position_quantity(arm) == 0
    world.capital[arm].assert_conservation()


def test_exit_bust_reopens_same_origin_lot_without_oversell(world) -> None:
    from src.screening.offensive.v3.capital.execution_revisions import (
        ExecutionRevisionRequest,
    )
    from src.screening.offensive.v3.contracts import (
        ExecutionRevisionKind,
        ExecutionSide,
    )

    arm = TrialArm.CHAMPION
    world.open_position(arm)
    (initial,) = world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    world.clock._moment = _session_close(EXIT_DUE_SESSION)  # noqa: SLF001
    (settled,) = world.lifecycle.execute_due_exits(
        arm,
        EXIT_DUE_SESSION,
        {_SECURITY: _exit_bar(EXIT_DUE_SESSION)},
        _cost_scenario(30),
    )
    assert settled.fill_receipt is not None
    assert world.position_quantity(arm) == 0

    fill = settled.fill_receipt
    origin = world.adapters[arm].lot_origin(
        fill.position_lineage_id,
        fill.economic_lot_id,
    )
    bust_at = _session_close(date(2026, 8, 20))
    world.capital[arm].record_execution_revision(
        ExecutionRevisionRequest(
            execution_id=fill.execution_id,
            revision=2,
            revision_kind=ExecutionRevisionKind.BUSTED,
            order_id=fill.order_id,
            side=ExecutionSide.EXIT,
            security_id=fill.security_id,
            position_lineage_id=fill.position_lineage_id,
            economic_lot_id=fill.economic_lot_id,
            superseded_quantity=fill.quantity,
            source_authority="growth-kernel.shadow.v3",
            effective_at=bust_at,
            as_of=bust_at,
            expected_stream_version=world.capital[arm].stream_version(),
            source_binding=origin.source_binding,
        )
    )
    assert world.position_quantity(arm) == held
    (reopened,) = world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    assert reopened.economic_lot_id == initial.economic_lot_id
    assert reopened.due_session == initial.due_session
    assert reopened.mandate_revision > initial.mandate_revision

    world.clock._moment = _session_close(date(2026, 8, 20))  # noqa: SLF001
    (resettled,) = world.lifecycle.execute_due_exits(
        arm,
        date(2026, 8, 20),
        {_SECURITY: _exit_bar(date(2026, 8, 20))},
        _cost_scenario(30),
    )
    assert resettled.sold_quantity == held
    assert world.position_quantity(arm) == 0
    world.capital[arm].assert_conservation()


def test_lot_origin_extension_is_immutable_and_legacy_rows_fail_closed(
    world,
    tmp_path: Path,
) -> None:
    import sqlite3

    import sqlalchemy as sa

    from src.screening.offensive.v3.execution.shadow_proxy import (
        ShadowProxyError,
    )

    arm = TrialArm.CHAMPION
    world.open_position(arm)
    position = world.capital[arm].capital_risk_snapshot(world.clock()).positions[0]
    origin = world.adapters[arm].lot_origin(
        position.position_lineage_id,
        position.economic_lot_id,
    )
    assert origin.pair_key == world.pair_key
    assert origin.artifact_hash == world.champion_decision.artifact_hash()
    assert origin.target_exit_session == EXIT_DUE_SESSION
    with pytest.raises(sa.exc.DatabaseError, match="immutable table"):
        with world.adapters[arm]._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                sa.text(
                    "UPDATE shadow_lot_origins SET lot_size_units = 200"
                    " WHERE operation_id = :operation_id"
                ),
                {"operation_id": origin.operation_id},
            )

    legacy_path = tmp_path / "legacy-shadow-proxy.sqlite3"
    with sqlite3.connect(legacy_path) as conn:
        conn.execute(
            "CREATE TABLE shadow_proxy_operations"
            " (operation_id TEXT PRIMARY KEY)"
        )
        conn.execute(
            "INSERT INTO shadow_proxy_operations VALUES ('legacy-operation')"
        )
    with pytest.raises(ShadowProxyError) as rejected:
        ShadowProxyAdapter(database_path=str(legacy_path), clock=world.clock)
    assert rejected.value.code == "shadow_lot_origin_cutover_required"


# =============================================================================
# Step 2: crash recovery at phase boundaries
# =============================================================================


def test_crash_after_exit_fill_then_replay_converges(world, tmp_path: Path) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    world.clock._moment = _session_close(EXIT_DUE_SESSION)  # noqa: SLF001

    def fault(phase: str) -> None:
        if phase == "lifecycle.after_exit_release:CHAMPION":
            raise RuntimeError("simulated crash after exit fill, before release")

    crashing_lifecycle = ShadowProxyLifecycle(
        world._states(),
        clock=world.clock,
        _fault_hook=fault,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        crashing_lifecycle.execute_due_exits(
            arm, EXIT_DUE_SESSION, {_SECURITY: _exit_bar(EXIT_DUE_SESSION)}, _cost_scenario(30)
        )
    # The capital fill committed before the crash (the EXIT_SETTLED fact is
    # durable). Replay must converge without a second capital write and without
    # double-selling.
    cap_after_crash = world.capital[arm].capital_version()
    results = world.lifecycle.execute_due_exits(
        arm, EXIT_DUE_SESSION, {_SECURITY: _exit_bar(EXIT_DUE_SESSION)}, _cost_scenario(30)
    )
    assert results == ()  # nothing left to claim (already filled / lease state)
    assert world.capital[arm].capital_version() == cap_after_crash
    assert world.position_quantity(arm) == 0
    world.capital[arm].assert_conservation()


def test_advance_session_crash_after_one_arm_converges_on_replay(
    world, tmp_path: Path
) -> None:
    from src.screening.offensive.v3.execution.shadow_proxy import (
        ShadowArmExecutionContext,
    )

    # Reserve both arms at T0 (a paired trial reserves both before any session).
    world.clock._moment = COMMAND_AT  # noqa: SLF001
    contexts = {
        arm: ShadowArmExecutionContext(
            trial_id=TRIAL_ID,
            arm=arm,
            portfolio_id=PORTFOLIO,
            decision_store=world.store,
            capital_repository=world.capital[arm],
            writer_lease=world.lease,
        )
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
    }
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        world.adapters[arm].reserve_committed_pair(world.pair_key, {arm: contexts[arm]})
    world.clock._moment = _session_close(ENTRY_SESSION)  # noqa: SLF001

    # Crash inside the challenger's processing, after the champion has fully
    # finalized. Champion's session is durable; the process dies mid-challenger.
    def fault(phase: str) -> None:
        if phase == "lifecycle.after_entries:CHALLENGER":
            raise RuntimeError("simulated crash mid-challenger")

    crashing_lifecycle = ShadowProxyLifecycle(
        world._states(), clock=world.clock, _fault_hook=fault
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        crashing_lifecycle.advance_session(
            _entry_session_input(world), world._states_to_contexts()
        )
    # Champion finalized during the crashed run.
    champ_committed = world.lifecycle._committed_phases(  # noqa: SLF001
        world.capital[TrialArm.CHAMPION], ENTRY_SESSION
    )
    assert "SESSION_FINALIZED" in champ_committed

    # Replay with a clean lifecycle: champion converges as a no-op (its session
    # is already finalized), challenger resumes and completes. Both arms end
    # the session with SESSION_FINALIZED committed.
    receipt = world.lifecycle.advance_session(
        _entry_session_input(world), world._states_to_contexts()
    )
    # Champion already finalized -> its replay receipt is the converged no-op.
    assert receipt.arms[TrialArm.CHAMPION].finalized is None
    # Challenger resumed from its crash and finalized this run.
    assert receipt.arms[TrialArm.CHALLENGER].finalized is not None
    assert (
        receipt.arms[TrialArm.CHALLENGER].finalized.phase == "SESSION_FINALIZED"
    )
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        committed = world.lifecycle._committed_phases(  # noqa: SLF001
            world.capital[arm], ENTRY_SESSION
        )
        assert "SESSION_FINALIZED" in committed
        world.capital[arm].assert_conservation()
    # Both arms opened their entry position.
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        assert world.position_quantity(arm) > 0
