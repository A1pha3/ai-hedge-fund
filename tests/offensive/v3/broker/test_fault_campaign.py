"""Plan 07 Task 8 (Step 3): production-readiness fault campaign.

The per-task suites prove each subsystem in isolation. This campaign drives
the plan's enumerated production faults across subsystem boundaries and
asserts the cross-cutting invariant: every ambiguity halts entry while
exit/reconcile survives, and no fault duplicates, hides, or re-authorizes
capital.

Faults exercised:
- process kill / restart resume (scheduler exit duty survives)
- duplicate webhook (normalizer idempotent on source hash)
- delayed / truncated poll (reconcile blocks, never clamps)
- out-of-order / late push (normalizer converges across permutations)
- clock skew beyond tolerance (capability certification rejects)
- key rotation / untrusted issuer (DR manifest cannot be re-authorized)
- handoff then DR (fencing epoch monotonic across both; old writer fenced)
- broker throttle (scheduler refunds and defers)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.v3.broker.capabilities import (
    BrokerEnablementError,
    certify_trusted_clock,
)
from src.screening.offensive.v3.broker.disaster_recovery import (
    DisasterRecoveryCoordinator,
    DisasterRecoveryError,
    RecoveredStores,
    RecoveryFenceProof,
    RecoveryState,
)
from src.screening.offensive.v3.broker.handoff import (
    CursorCheckpoint,
    FenceProof,
    HandoffError,
    WriterHandoff,
)
from src.screening.offensive.v3.broker.normalizer import (
    CumulativeObservation,
    ExecutionNormalizer,
)
from src.screening.offensive.v3.broker.reconcile import (
    BreakKind,
    BrokerAccountFact,
    CompletenessProof,
    QueryPage,
    Reconciler,
)
from src.screening.offensive.v3.broker.scheduler import (
    BrokerLifecycleScheduler,
    ExecutionOutcome,
    WorkItem,
    WorkKind,
)
from src.screening.offensive.v3.trust import TrustVerificationError

from tests.offensive.v3.broker.test_disaster_recovery import (
    FINGERPRINT,
    _dr_manifest,
    _fabric_and_key,
    _signed_envelope,
)
from tests.offensive.v3.migration.helpers import HASH_E, NOW


UTC = timezone.utc


# -- process kill / restart resume -------------------------------------------


def test_process_kill_then_restart_resumes_exit_duty() -> None:
    """A process kill releases the process lease but exit duty survives."""

    cutoff = NOW + timedelta(minutes=30)

    class _Clock:
        def __init__(self, t: datetime) -> None:
            self.t = t

        def __call__(self) -> datetime:
            return self.t

    sched = BrokerLifecycleScheduler(
        entry_budget=2,
        exit_budget=2,
        query_budget=2,
        reconcile_budget=2,
        cutoff=cutoff,
        clock=_Clock(NOW),
    )
    sched.acquire_lease(owner="worker-A")
    sched.enqueue(WorkItem(WorkKind.EXIT, "x1"))

    class _Throttle:
        def execute(self, item, *, now):
            from src.screening.offensive.v3.broker.scheduler import ExecutionResult

            return ExecutionResult(
                outcome=ExecutionOutcome.THROTTLED,
                item=item,
            )

    sched.run_cycle(_Throttle())  # exit deferred by broker throttle
    sched.release_lease(owner="worker-A")  # process killed
    assert sched.queue_depth(WorkKind.EXIT) == 1  # exit duty survived
    # Restart re-acquires and still owns the pending exit.
    sched.acquire_lease(owner="worker-A")
    assert sched.has_process_lease()


# -- duplicate webhook -------------------------------------------------------


def test_duplicate_webhook_does_not_duplicate_capital() -> None:
    """The same authenticated envelope replayed as a duplicate webhook is idempotent."""

    norm = ExecutionNormalizer()
    obs = CumulativeObservation(
        client_order_id="client-1",
        cumulative_quantity_units=500,
        cumulative_notional_cents=500_000,
        cumulative_fee_cents=25,
        observed_at=NOW,
        source_envelope_hash="env-1",
    )
    first = norm.apply(obs)
    second = norm.apply(obs)  # duplicate webhook
    assert len(first.revisions) == 1
    assert second.revisions == ()  # no duplicate capital revision
    state = norm.state_for("client-1")
    assert state is not None
    assert state.revision_ordinal == 1


# -- delayed / truncated poll ------------------------------------------------


def test_truncated_poll_blocks_and_never_clamps() -> None:
    """A truncated poll (missing page) is a BLOCKING break, never a clamp."""

    norm = ExecutionNormalizer()
    rec = Reconciler(norm)

    def _pages(n: int) -> tuple[QueryPage, ...]:
        out = []
        cursor = "cursor-0"
        for i in range(1, n + 1):
            before = cursor
            after = f"cursor-{i}"
            out.append(
                QueryPage(
                    page_ordinal=i,
                    cursor_before=before,
                    cursor_after=after,
                    envelope_root=f"root-{i}",
                    received_at=NOW + timedelta(seconds=i),
                )
            )
            cursor = after
        return tuple(out)

    proof = CompletenessProof(
        query_parameters_hash="qp",
        expected_page_count=3,
        pages=_pages(2),  # truncated: only 2 of 3 pages
        broker_as_of=NOW,
        received_at=NOW,
        retention_calendar_days=30,
        retention_horizon_days=30,
    )
    snapshot = rec.capture_complete_snapshot(
        proof, orders=(), account=BrokerAccountFact(cash_cents=0)
    )
    result = rec.compare(snapshot, local_cash_cents=0)
    assert result.breaks[0].kind is BreakKind.MISSING_PAGE
    assert result.has_blocking


# -- out-of-order / late push ------------------------------------------------


def test_out_of_order_push_converges_across_permutations() -> None:
    """``normalize_batch`` canonicalizes order, so any permutation converges.

    Raw ``apply()`` halts on an arrival-order cumulative rollback; the
    convergence guarantee belongs to ``normalize_batch``, which sorts by
    ``observed_at`` before applying.
    """

    def _obs(step: int, env: str, qty: int, notional: int) -> CumulativeObservation:
        return CumulativeObservation(
            client_order_id="client-1",
            cumulative_quantity_units=qty,
            cumulative_notional_cents=notional,
            cumulative_fee_cents=25,
            observed_at=NOW + timedelta(seconds=step),
            source_envelope_hash=env,
        )

    base = (
        _obs(1, "env-a", 100, 100_000),
        _obs(2, "env-b", 300, 300_000),
        _obs(3, "env-c", 500, 500_000),
    )
    for perm in ((0, 1, 2), (2, 1, 0), (1, 2, 0)):
        norm = ExecutionNormalizer()
        result = norm.normalize_batch(tuple(base[i] for i in perm))
        assert result.halts == ()
        assert result.final_state is not None
        assert result.final_state.cumulative_quantity_units == 500
        assert result.final_state.revision_ordinal == 3


# -- clock skew --------------------------------------------------------------


def test_clock_skew_beyond_tolerance_rejects_certification() -> None:
    """Observed skew beyond tolerance is fail-closed at certification time."""

    with pytest.raises(BrokerEnablementError) as excinfo:
        certify_trusted_clock(
            max_observed_skew_ms=2000, tolerance_ms=500, proven_at=NOW
        )
    assert excinfo.value.code == "CLOCK_SKEW_EXCEEDS_TOLERANCE"


# -- key rotation / untrusted issuer -----------------------------------------


def test_rotated_out_credential_cannot_reauthorize_recovery() -> None:
    """A DR manifest signed by a key absent from the trust registry is rejected.

    This is the key-rotation fault: once the governance-recovery credential is
    rotated out of the registry, a manifest signed by the old (now untrusted)
    key can no longer authorize disaster recovery.
    """

    registered_fabric, registered_key, cap = _fabric_and_key()
    manifest = _dr_manifest()
    # Sign with a key that is NOT in the trust registry (the rotated-out key).
    rogue_key = Ed25519PrivateKey.generate()
    rogue_envelope = _signed_envelope(None, rogue_key, cap, manifest)
    coordinator = DisasterRecoveryCoordinator()
    with pytest.raises(TrustVerificationError):
        coordinator.verify_backup(
            rogue_envelope,
            verifier=registered_fabric.verifier,
            current_head=registered_fabric.head,
            required_capability=cap,
            trusted_at=NOW,
            recovered_backup_root_hash=HASH_E,
            current_recovery_epoch=1,
            current_fencing_epoch=2,
            expected_account_fingerprint=FINGERPRINT,
        )
    # The still-registered key authorizes recovery.
    good_envelope = _signed_envelope(None, registered_key, cap, manifest)
    coordinator.verify_backup(
        good_envelope,
        verifier=registered_fabric.verifier,
        current_head=registered_fabric.head,
        required_capability=cap,
        trusted_at=NOW,
        recovered_backup_root_hash=HASH_E,
        current_recovery_epoch=1,
        current_fencing_epoch=2,
        expected_account_fingerprint=FINGERPRINT,
    )
    assert coordinator.state is RecoveryState.BACKUP_VERIFIED


# -- handoff then DR ---------------------------------------------------------


def test_handoff_then_disaster_recovery_advances_epoch_monotonically() -> None:
    """A clean handoff raises the fencing epoch; a later DR must raise it further."""

    # Clean handoff: writer-1 -> writer-2 at fencing epoch 2.
    handoff = WriterHandoff()
    handoff.begin_drain(live_orders=0, ambiguous_orders=0)
    handoff.report_drained(remaining_live=0, remaining_ambiguous=0)
    handoff.mark_reconciled()
    handoff.present_fence_proof(
        FenceProof(
            credential_revoked=True,
            session_revoked=True,
            network_egress_removed=True,
            proven_at=NOW,
        )
    )
    handoff.complete(
        new_writer_id="writer-2",
        checkpoint=CursorCheckpoint(
            inbox_cursor="inbox-1",
            outbox_cursor="outbox-1",
            broker_cursor="broker-1",
            fencing_epoch=1,
        ),
    )
    handoff.activate_new_writer(writer_id="writer-2", epoch=2)
    # writer-1 is already fenced by the handoff.
    with pytest.raises(HandoffError):
        handoff.fence_send(writer_id="writer-1", epoch=1)

    # A subsequent disaster must declare a fencing epoch past the handoff's.
    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest(fencing_epoch=3)  # past handoff epoch 2
    envelope = _signed_envelope(fabric, key, cap, manifest)
    recovery = DisasterRecoveryCoordinator()
    recovery.verify_backup(
        envelope,
        verifier=fabric.verifier,
        current_head=fabric.head,
        required_capability=cap,
        trusted_at=NOW,
        recovered_backup_root_hash=HASH_E,
        current_recovery_epoch=1,
        current_fencing_epoch=2,  # the live handoff epoch
        expected_account_fingerprint=FINGERPRINT,
    )
    recovery.restore_stores(
        RecoveredStores(
            backup_root_hash=HASH_E,
            inbox_cursor="inbox-1",
            outbox_cursor="outbox-1",
            broker_cursor="broker-1",
        )
    )
    recovery.reconcile(live_orders=0, ambiguous_orders=0, conservation_proven=True)
    recovery.present_fence_proof(
        RecoveryFenceProof(
            credential_re_bound=True,
            session_re_severed=True,
            network_egress_re_fenced=True,
            proven_at=NOW,
        )
    )
    new_epoch = recovery.complete(new_writer_id="writer-3")
    assert new_epoch == 3
    # The handoff-era writer-2 is not the recovered authority (writer-3), so
    # any send under it is fenced before the epoch is even consulted.
    with pytest.raises(DisasterRecoveryError) as excinfo:
        recovery.fence_send(writer_id="writer-2", epoch=2)
    assert excinfo.value.code == "WRITER_NOT_AUTHORITY"
    # Even the new authority presenting the stale handoff epoch is rejected.
    with pytest.raises(DisasterRecoveryError) as excinfo:
        recovery.fence_send(writer_id="writer-3", epoch=2)
    assert excinfo.value.code == "EPOCH_SUPERSEDED"


def test_disaster_recovery_cannot_replay_handoff_epoch() -> None:
    """A DR manifest declaring a fencing epoch at or below the live one is a race."""

    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest(fencing_epoch=2)  # not past live fencing epoch 2
    envelope = _signed_envelope(fabric, key, cap, manifest)
    recovery = DisasterRecoveryCoordinator()
    with pytest.raises(DisasterRecoveryError) as excinfo:
        recovery.verify_backup(
            envelope,
            verifier=fabric.verifier,
            current_head=fabric.head,
            required_capability=cap,
            trusted_at=NOW,
            recovered_backup_root_hash=HASH_E,
            current_recovery_epoch=1,
            current_fencing_epoch=2,
            expected_account_fingerprint=FINGERPRINT,
        )
    assert excinfo.value.code == "FENCING_EPOCH_NOT_ADVANCED"


# -- broker throttle ---------------------------------------------------------


def test_broker_throttle_refunds_and_defers_without_failure() -> None:
    cutoff = NOW + timedelta(minutes=30)

    class _Clock:
        def __init__(self, t: datetime) -> None:
            self.t = t

        def __call__(self) -> datetime:
            return self.t

    sched = BrokerLifecycleScheduler(
        entry_budget=2,
        exit_budget=2,
        query_budget=2,
        reconcile_budget=2,
        cutoff=cutoff,
        clock=_Clock(NOW),
    )
    sched.enqueue(WorkItem(WorkKind.ENTRY, "e1"))

    class _Throttle:
        def execute(self, item, *, now):
            from src.screening.offensive.v3.broker.scheduler import ExecutionResult

            return ExecutionResult(outcome=ExecutionOutcome.THROTTLED, item=item)

    result = sched.run_cycle(_Throttle())
    assert result.submitted == ()
    assert any(i.item_id == "e1" for i in result.deferred)
    # Budget refunded, not consumed by the throttled attempt.
    assert result.budget_remaining["entry"] == 2
