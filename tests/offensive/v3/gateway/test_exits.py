"""Plan 04 Task 7: independent ExitMandate lane.

Exits derive only from injected capital truth: never from entry
authorization, policy envelopes, or the permit/outbox machinery. Risk and
stage halts do not block exits; dependency outages on the entry side do
not block exits. Unknown tradable quantity schedules reconciliation and
exposes zero orderable quantity - the lane never guesses or oversells.
Mandates and leases survive crashes and restarts.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta, timezone

import pytest

from src.screening.offensive.v3.capital.execution_revisions import (
    MANDATE_REVISION_FLOOR,
    ReopenedEconomicLot,
)
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    ExitQuantityKnowledge,
    PositionState,
    RiskLatchState,
    StageLossLatchState,
)
from src.screening.offensive.v3.gateway.exits import (
    ClaimedExitWork,
    ExitAttemptOutcome,
    ExitDerivationContext,
    ExitDependencies,
    ExitLane,
    ExitLaneError,
    ExitLotTruth,
)

UTC = timezone.utc
NOW = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)
SIGNAL_SESSION = date(2026, 7, 16)  # Thursday
HASH = "a" * 64
FINGERPRINT = "c" * 64


def _sessions_after_signal(count: int) -> tuple[date, ...]:
    sessions: list[date] = []
    day = SIGNAL_SESSION
    while len(sessions) < count:
        day = day + timedelta(days=1)
        if day.weekday() < 5:
            sessions.append(day)
    return tuple(sessions)


ALL_SESSIONS = _sessions_after_signal(15)
DUE_SESSION = ALL_SESSIONS[9]  # 10th session after signal (entry ordinal 1)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


@pytest.fixture()
def clock() -> _Clock:
    return _Clock(NOW)


@pytest.fixture()
def lane(tmp_path, clock) -> ExitLane:
    return ExitLane(
        database_path=str(tmp_path / "exit-lane.sqlite3"),
        clock=clock,
    )


def _lot(**overrides) -> ExitLotTruth:
    values = {
        "position_lineage_id": "lin-1",
        "economic_lot_id": "lot-1",
        "security_id": "600000.SH",
        "producer_namespace": "btst",
        "research_program_id": "prog-1",
        "economic_lineage_id": "eline-1",
        "stage_id": "stage-1",
        "position_state": PositionState.OPEN,
        "signal_session": SIGNAL_SESSION,
        "entry_session_ordinal": 1,
        "entry_plan_evidence_artifact_hash": HASH,
        "settled_quantity": 200,
        "tradable_quantity": 200,
        "live_exit_leaves": 0,
        "successor_security_id": None,
        "reopen": None,
    }
    values.update(overrides)
    return ExitLotTruth(**values)


def _context(**overrides) -> ExitDerivationContext:
    values = {
        "portfolio_id": "paper-v3",
        "broker_account_id": None,
        "base_currency": "CNY",
        "mode": ExecutionMode.DAILY_BAR_PROXY,
        "capital_version": 1,
        "writer_fencing_epoch": 1,
        "fixed_exit_policy_fingerprint": FINGERPRINT,
        "source_risk_snapshot_id": "risk-snap-exit-1",
        "source_risk_snapshot_hash": HASH,
        "trading_sessions": ALL_SESSIONS,
    }
    values.update(overrides)
    return ExitDerivationContext(**values)


def _reopen(**overrides) -> ReopenedEconomicLot:
    values = {
        "reopen_id": "reopen-1",
        "position_lineage_id": "lin-1",
        "economic_lot_id": "lot-1",
        "security_id": "600000.SH",
        "producer_namespace": "btst",
        "research_program_id": "prog-1",
        "economic_lineage_id": "eline-1",
        "stage_id": "stage-1",
        "reopened_quantity_units": 100,
        "position_state": PositionState.EXIT_PENDING,
        "reopen_reason": "exit bust restored positive holding",
        "mandate_revision_floor": MANDATE_REVISION_FLOOR,
        "reopened_by_execution_revision_id": "fill:exec-x:2",
        "reopened_by_event_id": "event-1",
        "capital_version": 2,
        "stream_version": 2,
    }
    values.update(overrides)
    return ReopenedEconomicLot(**values)


def _derive(lane: ExitLane, lots=None, *, context=None):
    if lots is None:
        lots = (_lot(),)
    if context is None:
        context = _context()
    return lane.derive_exit_mandates(lots, context=context)


# -- derivation: T+10 obligations from capital truth ------------------------


def test_derive_creates_initial_known_mandate(lane) -> None:
    (mandate,) = _derive(lane)
    assert mandate.mandate_revision == 1
    assert mandate.exit_session_ordinal == 10
    assert mandate.due_session == DUE_SESSION
    assert mandate.quantity_knowledge is ExitQuantityKnowledge.KNOWN
    assert mandate.tradable_quantity == 200
    assert mandate.executable_quantity == 200
    assert mandate.stable_client_order_id == "exit-client-lin-1:lot-1"
    state = lane.exit_state("lin-1", "lot-1")
    assert state.status == "PENDING"
    assert state.executable_quantity == 200


def test_due_session_is_tenth_session_after_signal(lane) -> None:
    (mandate,) = _derive(lane)
    # Sessions strictly after the 2026-07-16 signal: 7/17, 7/20, ...
    assert DUE_SESSION == date(2026, 7, 30)
    assert mandate.due_session == DUE_SESSION


def test_insufficient_calendar_fails_closed(lane) -> None:
    context = _context(trading_sessions=ALL_SESSIONS[:5])
    with pytest.raises(ExitLaneError) as excinfo:
        lane.derive_exit_mandates((_lot(),), context=context)
    assert excinfo.value.code == "exit_calendar_insufficient"
    assert lane.exit_state("lin-1", "lot-1") is None


def test_derive_is_idempotent_without_revision_bump(lane) -> None:
    (first,) = _derive(lane)
    (second,) = _derive(lane)
    assert second.exit_mandate_id == first.exit_mandate_id
    assert second.mandate_revision == 1
    assert lane.exit_state("lin-1", "lot-1").mandate_revision == 1


def test_quantity_refresh_supersedes_prior_mandate(lane) -> None:
    (first,) = _derive(lane)
    (refreshed,) = _derive(lane, lots=(_lot(tradable_quantity=100),))
    assert refreshed.mandate_revision == 2
    assert refreshed.supersedes_mandate_hash == first.artifact_hash()
    assert refreshed.stable_client_order_id == first.stable_client_order_id
    assert refreshed.executable_quantity == 100
    state = lane.exit_state("lin-1", "lot-1")
    assert state.mandate_revision == 2
    assert state.executable_quantity == 100


def test_terminal_legal_event_is_never_claimable(lane) -> None:
    (mandate,) = _derive(
        lane, lots=(_lot(position_state=PositionState.LEGAL_TERMINAL),)
    )
    state = lane.exit_state("lin-1", "lot-1")
    assert state.status == "TERMINAL_LEGAL"
    claimed = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-1"
    )
    assert claimed == ()
    del mandate


def test_successor_security_keeps_obligation_alive(lane) -> None:
    (first,) = _derive(lane)
    assert first.security_id == "600000.SH"
    (converted,) = _derive(
        lane,
        lots=(
            _lot(
                security_id="600000.SH",
                successor_security_id="600001.SH",
                tradable_quantity=200,
            ),
        ),
    )
    assert converted.security_id == "600001.SH"
    assert converted.mandate_revision == 2
    state = lane.exit_state("lin-1", "lot-1")
    assert state.security_id == "600001.SH"
    assert state.status == "PENDING"


# -- unknown quantity: reconcile, never guess --------------------------------


def test_unknown_quantity_never_orderable_and_schedules_reconciliation(
    lane,
) -> None:
    (mandate,) = _derive(lane, lots=(_lot(tradable_quantity=None),))
    assert mandate.quantity_knowledge is ExitQuantityKnowledge.UNKNOWN
    assert mandate.reconciliation_pending is True
    assert mandate.tradable_quantity == 0
    assert mandate.executable_quantity == 0
    claimed = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-1"
    )
    assert claimed == ()
    state = lane.exit_state("lin-1", "lot-1")
    assert state.reconciliation_pending is True
    assert state.outstanding_query_count == 1


def test_reconcile_exit_resolves_unknown_to_known(lane) -> None:
    _derive(lane, lots=(_lot(tradable_quantity=None),))
    resolved = lane.reconcile_exit(
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        reason="broker statement confirms holding",
        verified_tradable_quantity=150,
        live_exit_leaves=50,
    )
    assert resolved is not None
    assert resolved.quantity_knowledge is ExitQuantityKnowledge.KNOWN
    assert resolved.tradable_quantity == 150
    assert resolved.live_exit_leaves_quantity == 50
    assert resolved.executable_quantity == 100
    assert resolved.mandate_revision == 2
    state = lane.exit_state("lin-1", "lot-1")
    assert state.reconciliation_pending is False
    assert state.executable_quantity == 100


def test_reconcile_exit_without_verification_schedules_query(lane) -> None:
    _derive(lane, lots=(_lot(tradable_quantity=None),))
    # Derivation already opened exactly one query; the open-query guard
    # keeps a redundant reconcile from stacking a second one.
    assert lane.exit_state("lin-1", "lot-1").outstanding_query_count == 1
    resolved = lane.reconcile_exit(
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        reason="broker query in flight",
    )
    assert resolved is None
    state = lane.exit_state("lin-1", "lot-1")
    assert state.status == "PENDING"
    assert state.reconciliation_pending is True
    assert state.outstanding_query_count == 1
    # Still never orderable.
    assert (
        lane.claim_due_exit_work(as_of_session=DUE_SESSION, worker_id="w")
        == ()
    )
    # A verified reconcile resolves the open query.
    lane.reconcile_exit(
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        reason="broker statement confirms holding",
        verified_tradable_quantity=150,
        live_exit_leaves=50,
    )
    assert lane.exit_state("lin-1", "lot-1").outstanding_query_count == 0
    # With no query open, a further unverified reconcile schedules a new one.
    lane.reconcile_exit(
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        reason="follow-up broker query",
    )
    assert lane.exit_state("lin-1", "lot-1").outstanding_query_count == 1


def test_live_exit_leaves_reduce_executable(lane) -> None:
    (mandate,) = _derive(lane, lots=(_lot(live_exit_leaves=50),))
    assert mandate.live_exit_leaves_quantity == 50
    assert mandate.executable_quantity == 150


def test_live_exit_leaves_cannot_exceed_tradable(lane) -> None:
    with pytest.raises(ExitLaneError) as excinfo:
        _derive(lane, lots=(_lot(live_exit_leaves=250),))
    assert excinfo.value.code == "exit_leaves_exceed_tradable"


# -- fill bust / correction reopen -------------------------------------------


def test_fill_bust_reopen_revives_closed_lot(lane) -> None:
    (first,) = _derive(lane)
    # Lot exits fully: truth goes flat, mandate closes.
    (closed,) = _derive(lane, lots=(_lot(tradable_quantity=0, settled_quantity=0),))
    assert closed.executable_quantity == 0
    assert lane.exit_state("lin-1", "lot-1").status == "CLOSED"

    reopened_fact = _reopen()
    (reopened,) = _derive(
        lane,
        lots=(
            _lot(
                position_state=PositionState.EXIT_PENDING,
                settled_quantity=100,
                tradable_quantity=100,
                reopen=reopened_fact,
            ),
        ),
    )
    assert reopened.mandate_revision == 3
    assert reopened.revision_kind.value == "REOPENED_BY_CORRECTION"
    assert reopened.reopened_by_execution_revision_id == "fill:exec-x:2"
    assert reopened.supersedes_mandate_hash == closed.artifact_hash()
    assert reopened.executable_quantity == 100
    state = lane.exit_state("lin-1", "lot-1")
    assert state.status == "PENDING"
    del first


def test_reopen_on_never_mandated_lot_chains_initial_then_reopened(
    lane,
) -> None:
    reopened_fact = _reopen()
    mandates = _derive(
        lane,
        lots=(
            _lot(
                position_state=PositionState.EXIT_PENDING,
                settled_quantity=100,
                tradable_quantity=100,
                reopen=reopened_fact,
            ),
        ),
    )
    (mandate,) = mandates
    assert mandate.revision_kind.value == "REOPENED_BY_CORRECTION"
    assert mandate.mandate_revision >= MANDATE_REVISION_FLOOR
    assert mandate.reopened_by_execution_revision_id == "fill:exec-x:2"
    state = lane.exit_state("lin-1", "lot-1")
    assert state.status == "PENDING"


def test_reconcile_cannot_reopen_closed_lot(lane) -> None:
    _derive(lane)
    # Lot exits fully: truth goes flat, mandate closes.
    _derive(lane, lots=(_lot(tradable_quantity=0, settled_quantity=0),))
    assert lane.exit_state("lin-1", "lot-1").status == "CLOSED"
    with pytest.raises(ExitLaneError) as excinfo:
        lane.reconcile_exit(
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            reason="statement shows residual holding",
            verified_tradable_quantity=25,
        )
    assert excinfo.value.code == "exit_mandate_state_conflict"
    # Closed state is untouched; reopening is a correction-fact path only.
    state = lane.exit_state("lin-1", "lot-1")
    assert state.status == "CLOSED"
    assert state.mandate_revision == 2


# -- leasing and due work ------------------------------------------------------


def test_claim_excludes_work_before_due_session(lane) -> None:
    _derive(lane)
    claimed = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION - timedelta(days=1), worker_id="worker-1"
    )
    assert claimed == ()


def test_claim_due_work_returns_one_lease_per_mandate(lane) -> None:
    _derive(lane)
    (work,) = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-1"
    )
    assert work.exit_mandate_id
    assert work.lease_id
    assert work.security_id == "600000.SH"
    assert work.executable_quantity == 200
    assert work.stable_client_order_id == "exit-client-lin-1:lot-1"
    assert work.due_session == DUE_SESSION
    # Second claim by another worker finds nothing while leased.
    assert (
        lane.claim_due_exit_work(as_of_session=DUE_SESSION, worker_id="w2")
        == ()
    )


def test_release_lease_frees_mandate_for_another_worker(lane) -> None:
    _derive(lane)
    (work,) = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-1"
    )
    # A second worker is still blocked while the lease is held.
    assert (
        lane.claim_due_exit_work(as_of_session=DUE_SESSION, worker_id="worker-2")
        == ()
    )
    # The owning worker explicitly releases the lease.
    lane.release_lease(work.lease_id, worker_id="worker-1")
    # Releasing is idempotent: a second release is a quiet no-op.
    lane.release_lease(work.lease_id, worker_id="worker-1")
    # Now another worker may claim the same obligation.
    (reclaimed,) = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-2"
    )
    assert reclaimed.exit_mandate_id == work.exit_mandate_id
    assert reclaimed.lease_id != work.lease_id


def test_release_lease_rejects_unknown_and_wrong_owner(lane) -> None:
    _derive(lane)
    (work,) = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-1"
    )
    with pytest.raises(ExitLaneError, match="exit_lease_unknown"):
        lane.release_lease("lease:missing", worker_id="worker-1")
    with pytest.raises(ExitLaneError, match="exit_lease_owner_mismatch"):
        lane.release_lease(work.lease_id, worker_id="worker-imposter")


def test_expired_lease_is_reclaimable_by_another_worker(
    tmp_path, clock
) -> None:
    lane = ExitLane(
        database_path=str(tmp_path / "lease-expiry.sqlite3"),
        clock=clock,
        lease_ttl=timedelta(minutes=30),
    )
    _derive(lane)
    (work,) = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-crashy"
    )
    # The worker dies with the lease; after the TTL another worker may
    # take over the same obligation.
    clock.now_value = NOW + timedelta(minutes=31)
    (reclaimed,) = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-2"
    )
    assert reclaimed.exit_mandate_id == work.exit_mandate_id
    assert reclaimed.lease_id != work.lease_id
    state = lane.exit_state("lin-1", "lot-1")
    assert state.leased is True
    assert state.status == "PENDING"


def test_blocked_securities_skip_claim_but_keep_mandate(lane) -> None:
    _derive(lane)
    claimed = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION,
        worker_id="worker-1",
        blocked_securities=frozenset({"600000.SH"}),
    )
    assert claimed == ()
    state = lane.exit_state("lin-1", "lot-1")
    assert state.status == "PENDING"
    assert state.leased is False
    # Suspension lifts the next day: the same obligation is claimable.
    (work,) = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION + timedelta(days=1), worker_id="worker-1"
    )
    assert work.executable_quantity == 200


# -- exit attempts: partial exit, cancel-late-fill, oversell ------------------


def _claim_one(lane: ExitLane, *, worker_id="worker-1") -> ClaimedExitWork:
    (work,) = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id=worker_id
    )
    return work


def test_partial_exit_attempts_track_leaves(lane) -> None:
    _derive(lane)
    work = _claim_one(lane)
    lane.record_exit_attempt(
        exit_mandate_id=work.exit_mandate_id,
        attempt_id="attempt-1",
        client_order_id=work.stable_client_order_id,
        outcome=ExitAttemptOutcome.SUBMITTED,
        submitted_leaves=100,
    )
    state = lane.exit_state("lin-1", "lot-1")
    assert state.outstanding_attempt_leaves == 100
    assert state.claimable_quantity == 100  # 200 executable - 100 on book
    lane.record_exit_attempt(
        exit_mandate_id=work.exit_mandate_id,
        attempt_id="attempt-1",
        client_order_id=work.stable_client_order_id,
        outcome=ExitAttemptOutcome.FILLED,
        filled_quantity=100,
    )
    state = lane.exit_state("lin-1", "lot-1")
    assert state.outstanding_attempt_leaves == 0
    # The filled shares left the book: claimable quantity shrinks until
    # the next capital-truth refresh.
    assert state.claimable_quantity == 100


def test_oversell_is_blocked(lane) -> None:
    _derive(lane)
    work = _claim_one(lane)
    with pytest.raises(ExitLaneError) as excinfo:
        lane.record_exit_attempt(
            exit_mandate_id=work.exit_mandate_id,
            attempt_id="attempt-1",
            client_order_id=work.stable_client_order_id,
            outcome=ExitAttemptOutcome.SUBMITTED,
            submitted_leaves=250,
        )
    assert excinfo.value.code == "exit_oversell_blocked"
    assert lane.exit_state("lin-1", "lot-1").outstanding_attempt_leaves == 0


def test_second_submission_respects_outstanding_leaves(lane) -> None:
    _derive(lane)
    work = _claim_one(lane)
    lane.record_exit_attempt(
        exit_mandate_id=work.exit_mandate_id,
        attempt_id="attempt-1",
        client_order_id=work.stable_client_order_id,
        outcome=ExitAttemptOutcome.SUBMITTED,
        submitted_leaves=150,
    )
    with pytest.raises(ExitLaneError) as excinfo:
        lane.record_exit_attempt(
            exit_mandate_id=work.exit_mandate_id,
            attempt_id="attempt-2",
            client_order_id=work.stable_client_order_id,
            outcome=ExitAttemptOutcome.SUBMITTED,
            submitted_leaves=100,
        )
    assert excinfo.value.code == "exit_oversell_blocked"


def test_cancel_then_late_fill_counts_and_cannot_exceed_book(lane) -> None:
    _derive(lane)
    work = _claim_one(lane)
    submit = {
        "exit_mandate_id": work.exit_mandate_id,
        "attempt_id": "attempt-1",
        "client_order_id": work.stable_client_order_id,
    }
    lane.record_exit_attempt(
        outcome=ExitAttemptOutcome.SUBMITTED, submitted_leaves=100, **submit
    )
    lane.record_exit_attempt(
        outcome=ExitAttemptOutcome.CANCELLED, **submit
    )
    state = lane.exit_state("lin-1", "lot-1")
    assert state.outstanding_attempt_leaves == 0
    # The cancel raced a fill: 100 shares really left the book.
    lane.record_exit_attempt(
        outcome=ExitAttemptOutcome.LATE_FILL, filled_quantity=100, **submit
    )
    # Cumulative late fills can never exceed what was ever on the book.
    with pytest.raises(ExitLaneError) as excinfo:
        lane.record_exit_attempt(
            outcome=ExitAttemptOutcome.LATE_FILL,
            filled_quantity=101,
            **submit,
        )
    assert excinfo.value.code == "exit_late_fill_exceeds_book"


def test_fill_cannot_exceed_submission(lane) -> None:
    _derive(lane)
    work = _claim_one(lane)
    submit = {
        "exit_mandate_id": work.exit_mandate_id,
        "attempt_id": "attempt-1",
        "client_order_id": work.stable_client_order_id,
    }
    lane.record_exit_attempt(
        outcome=ExitAttemptOutcome.SUBMITTED, submitted_leaves=100, **submit
    )
    with pytest.raises(ExitLaneError) as excinfo:
        lane.record_exit_attempt(
            outcome=ExitAttemptOutcome.FILLED, filled_quantity=150, **submit
        )
    assert excinfo.value.code == "exit_fill_exceeds_submission"


def test_attempt_requires_stable_client_order_id(lane) -> None:
    _derive(lane)
    work = _claim_one(lane)
    with pytest.raises(ExitLaneError) as excinfo:
        lane.record_exit_attempt(
            exit_mandate_id=work.exit_mandate_id,
            attempt_id="attempt-1",
            client_order_id="guessed-new-id",
            outcome=ExitAttemptOutcome.SUBMITTED,
            submitted_leaves=100,
        )
    assert excinfo.value.code == "client_order_id_mismatch"


def test_attempt_on_terminal_or_unknown_mandate_is_rejected(lane) -> None:
    _derive(lane, lots=(_lot(position_state=PositionState.LEGAL_TERMINAL),))
    state = lane.exit_state("lin-1", "lot-1")
    with pytest.raises(ExitLaneError) as excinfo:
        lane.record_exit_attempt(
            exit_mandate_id=state.exit_mandate_id,
            attempt_id="attempt-1",
            client_order_id=state.stable_client_order_id,
            outcome=ExitAttemptOutcome.SUBMITTED,
            submitted_leaves=100,
        )
    assert excinfo.value.code == "exit_attempt_state_conflict"


def test_attempt_replay_is_idempotent_but_divergence_conflicts(
    lane,
) -> None:
    _derive(lane)
    work = _claim_one(lane)
    attempt = {
        "exit_mandate_id": work.exit_mandate_id,
        "attempt_id": "attempt-1",
        "client_order_id": work.stable_client_order_id,
        "outcome": ExitAttemptOutcome.SUBMITTED,
        "submitted_leaves": 100,
    }
    lane.record_exit_attempt(**attempt)
    lane.record_exit_attempt(**attempt)  # identical replay
    assert lane.exit_state("lin-1", "lot-1").outstanding_attempt_leaves == 100
    with pytest.raises(ExitLaneError) as excinfo:
        lane.record_exit_attempt(**{**attempt, "submitted_leaves": 150})
    assert excinfo.value.code == "exit_attempt_conflict"


# -- dependency outage and halt independence ----------------------------------


def _broken_dependency() -> ExitDependencies:
    def explode(name: str):
        def probe() -> object:
            raise RuntimeError(f"{name} endpoint unavailable")

        return probe

    return ExitDependencies(
        policy_probe=explode("policy"),
        envelope_probe=explode("envelope"),
        authorizer_probe=explode("authorizer"),
        publisher_probe=explode("publisher"),
        entry_probe=explode("entry"),
    )


def test_dependency_outage_does_not_block_exits(tmp_path, clock) -> None:
    lane = ExitLane(
        database_path=str(tmp_path / "outage.sqlite3"),
        clock=clock,
        dependencies=_broken_dependency(),
    )
    (mandate,) = _derive(lane)
    (work,) = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-1"
    )
    lane.record_exit_attempt(
        exit_mandate_id=work.exit_mandate_id,
        attempt_id="attempt-1",
        client_order_id=work.stable_client_order_id,
        outcome=ExitAttemptOutcome.SUBMITTED,
        submitted_leaves=100,
    )
    resolved = lane.reconcile_exit(
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        reason="outage-proof reconciliation",
        verified_tradable_quantity=100,
    )
    assert resolved is not None
    del mandate


def test_risk_and_stage_halts_do_not_block_exits(lane) -> None:
    context = _context(
        risk_latch=RiskLatchState.RISK_HALTED,
        stage_loss_latches=(StageLossLatchState.STAGE_LOSS_HALTED,),
    )
    (mandate,) = lane.derive_exit_mandates((_lot(),), context=context)
    assert mandate.executable_quantity == 200
    (work,) = lane.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-1"
    )
    assert work.executable_quantity == 200


# -- crash matrix ---------------------------------------------------------------


def _crashing_lane(tmp_path, clock, phase: str) -> ExitLane:
    def hook(name: str) -> None:
        if name == phase:
            raise RuntimeError(f"simulated crash at {name}")

    return ExitLane(
        database_path=str(tmp_path / "crash.sqlite3"),
        clock=clock,
        _fault_hook=hook,
    )


@pytest.mark.parametrize(
    "phase",
    [
        "derive.after_insert",
        "derive.after_supersede",
        "claim.after_lease",
        "attempt.after_insert",
        "attempt.after_update",
        "reconcile.after_supersede",
        "reconcile.after_insert",
    ],
)
def test_crash_mid_transition_leaves_prior_state_intact(
    tmp_path, clock, phase
) -> None:
    crashing = _crashing_lane(tmp_path, clock, phase)

    def drive(lane: ExitLane) -> None:
        lane.derive_exit_mandates((_lot(),), context=_context())
        lane.derive_exit_mandates(
            (_lot(tradable_quantity=150),), context=_context()
        )
        lane.claim_due_exit_work(as_of_session=DUE_SESSION, worker_id="w")
        state = lane.exit_state("lin-1", "lot-1")
        if state.outstanding_attempt_leaves == 0:
            lane.record_exit_attempt(
                exit_mandate_id=state.exit_mandate_id,
                attempt_id="attempt-1",
                client_order_id=state.stable_client_order_id,
                outcome=ExitAttemptOutcome.SUBMITTED,
                submitted_leaves=100,
            )
            lane.record_exit_attempt(
                exit_mandate_id=state.exit_mandate_id,
                attempt_id="attempt-1",
                client_order_id=state.stable_client_order_id,
                outcome=ExitAttemptOutcome.FILLED,
                filled_quantity=100,
            )
        lane.reconcile_exit(
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            reason="crash matrix reconciliation",
            verified_tradable_quantity=100,
        )

    crashed = False
    try:
        drive(crashing)
    except ExitLaneError:
        raise
    except RuntimeError as exc:
        assert "simulated crash" in str(exc)
        crashed = True
    assert crashed

    recovered = ExitLane(
        database_path=str(tmp_path / "crash.sqlite3"), clock=clock
    )
    # Whatever the crash interrupted, the lane is replayable to the full
    # post-state with no partial rows. Replayed truth refreshes bump the
    # revision lawfully, so the exact revision depends on the crash point.
    drive(recovered)
    final = recovered.exit_state("lin-1", "lot-1")
    assert final.status == "PENDING"
    expected_revision = {
        "derive.after_insert": 3,
        "derive.after_supersede": 3,
        "claim.after_lease": 5,
        "attempt.after_insert": 5,
        "attempt.after_update": 5,
        "reconcile.after_supersede": 5,
        "reconcile.after_insert": 5,
    }[phase]
    assert final.mandate_revision == expected_revision
    assert final.tradable_quantity == 100
    assert final.executable_quantity == 100


def test_crashed_unknown_mandate_still_reconciles(tmp_path, clock) -> None:
    lane = ExitLane(
        database_path=str(tmp_path / "unknown.sqlite3"), clock=clock
    )
    _derive(lane, lots=(_lot(tradable_quantity=None),))
    resolved = lane.reconcile_exit(
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        reason="restart reconciliation",
        verified_tradable_quantity=200,
    )
    assert resolved is not None
    assert resolved.executable_quantity == 200
