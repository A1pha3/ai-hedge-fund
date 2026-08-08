"""Plan 07 Task 4 (RED): push/poll normalization + execution revisions.

锁定约束:
1. apply_cumulative_execution: delta = new_cum - last_cum; 严格递增 = fill;
   相等 = 幂等 no-op; 递减 (无显式 bust) = UNEXPLAINED_CUMULATIVE_ROLLBACK
   halt, 绝不静默 clamp/reverse.
2. apply_bust: 显式 bust = 逆经济 (负 delta), cumulative 降到 busted 级.
3. apply_correction: bust 旧 cumulative 到 0 + apply 新 corrected, 递增
   revision 序号 (一对 revision: CORRECTION_BUST + CORRECTION_APPLY).
4. normalize_batch 收敛性: 同一组 source revisions 任意排列 (push/poll,
   duplicate/late/out-of-order) 经 observed-at 规范排序后产生 identical
   revisions + final_state + event count.
5. 负 impossible share (corrected_qty < 0) = halt, 不 clamp.
6. bust/correction 无 active fact = halt.
7. 幂等: 同 source_envelope_hash 重复 apply = no-op, 不重复入账.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import itertools

import pytest

from src.screening.offensive.v3.broker.normalizer import (
    CumulativeObservation,
    ExecutionNormalizer,
    NormalizationHaltCode,
    RevisionKind,
)

T0 = datetime(2026, 8, 7, 1, 0, 0, tzinfo=timezone.utc)


def _obs(
    *,
    seq: int,
    qty: int,
    notional: int,
    fee: int,
    client: str = "client-line-1",
    kind: str = "execution",
    observed_at: datetime | None = None,
    corrected_qty: int | None = None,
    corrected_notional: int | None = None,
    corrected_fee: int | None = None,
) -> CumulativeObservation:
    return CumulativeObservation(
        client_order_id=client,
        cumulative_quantity_units=qty,
        cumulative_notional_cents=notional,
        cumulative_fee_cents=fee,
        observed_at=observed_at or (T0 + timedelta(seconds=seq)),
        source_envelope_hash=f"hash-{seq}",
        kind=kind,  # type: ignore[arg-type]
        corrected_quantity_units=corrected_qty,
        corrected_notional_cents=corrected_notional,
        corrected_fee_cents=corrected_fee,
    )


# -- increasing cumulative fills -------------------------------------------


def test_increasing_cumulative_books_positive_deltas() -> None:
    norm = ExecutionNormalizer()
    r1 = norm.apply(_obs(seq=1, qty=100, notional=100_000, fee=5))
    r2 = norm.apply(_obs(seq=2, qty=250, notional=250_000, fee=12))
    r3 = norm.apply(_obs(seq=3, qty=500, notional=500_000, fee=25))
    deltas = [
        (r1.revisions[0].delta_quantity_units, r1.revisions[0].delta_notional_cents),
        (r2.revisions[0].delta_quantity_units, r2.revisions[0].delta_notional_cents),
        (r3.revisions[0].delta_quantity_units, r3.revisions[0].delta_notional_cents),
    ]
    assert deltas == [(100, 100_000), (150, 150_000), (250, 250_000)]
    state = norm.state_for("client-line-1")
    assert state is not None
    assert state.cumulative_quantity_units == 500
    assert state.revision_ordinal == 3
    assert r3.revisions[0].revision_ordinal == 3


def test_equal_cumulative_is_idempotent_noop() -> None:
    norm = ExecutionNormalizer()
    norm.apply(_obs(seq=1, qty=100, notional=100_000, fee=5))
    result = norm.apply(_obs(seq=2, qty=100, notional=100_000, fee=5))
    assert result.revisions == ()
    assert result.halts == ()
    assert norm.state_for("client-line-1").revision_ordinal == 1


def test_duplicate_source_envelope_hash_is_noop() -> None:
    norm = ExecutionNormalizer()
    obs = _obs(seq=1, qty=100, notional=100_000, fee=5)
    first = norm.apply(obs)
    second = norm.apply(obs)
    assert len(first.revisions) == 1
    assert second.revisions == ()
    assert norm.state_for("client-line-1").revision_ordinal == 1


# -- unexplained rollback halts --------------------------------------------


def test_decreasing_cumulative_without_bust_halts() -> None:
    norm = ExecutionNormalizer()
    norm.apply(_obs(seq=1, qty=500, notional=500_000, fee=25))
    result = norm.apply(_obs(seq=2, qty=250, notional=250_000, fee=12))
    assert len(result.halts) == 1
    assert result.halts[0].code is NormalizationHaltCode.UNEXPLAINED_CUMULATIVE_ROLLBACK
    assert result.revisions == ()
    # State is unchanged by the halt (no clamp).
    state = norm.state_for("client-line-1")
    assert state.cumulative_quantity_units == 500


# -- explicit bust appends inverse economics -------------------------------


def test_explicit_bust_appends_inverse_delta() -> None:
    norm = ExecutionNormalizer()
    norm.apply(_obs(seq=1, qty=500, notional=500_000, fee=25))
    result = norm.apply(
        _obs(seq=2, qty=0, notional=0, fee=0, kind="bust")
    )
    assert len(result.revisions) == 1
    rev = result.revisions[0]
    assert rev.kind is RevisionKind.BUST
    assert rev.delta_quantity_units == -500
    assert rev.delta_notional_cents == -500_000
    assert rev.delta_fee_cents == -25
    assert rev.cumulative_quantity_units == 0
    state = norm.state_for("client-line-1")
    assert state.cumulative_quantity_units == 0
    assert state.revision_ordinal == 2


def test_bust_without_active_fact_halts() -> None:
    norm = ExecutionNormalizer()
    result = norm.apply(_obs(seq=1, qty=0, notional=0, fee=0, kind="bust"))
    assert len(result.halts) == 1
    assert result.halts[0].code is NormalizationHaltCode.BUST_WITHOUT_ACTIVE_FACT


# -- correction: bust-old then apply-new -----------------------------------


def test_correction_busts_old_and_applies_new() -> None:
    norm = ExecutionNormalizer()
    norm.apply(_obs(seq=1, qty=500, notional=500_000, fee=25))
    result = norm.apply(
        _obs(
            seq=2,
            qty=500,  # ignored once corrected fields present
            notional=500_000,
            fee=25,
            kind="correction",
            corrected_qty=400,
            corrected_notional=400_000,
            corrected_fee=20,
        )
    )
    assert len(result.revisions) == 2
    bust, apply_rev = result.revisions
    assert bust.kind is RevisionKind.CORRECTION_BUST
    assert bust.delta_quantity_units == -500
    assert bust.cumulative_quantity_units == 0
    assert apply_rev.kind is RevisionKind.CORRECTION_APPLY
    assert apply_rev.delta_quantity_units == 400
    assert apply_rev.cumulative_quantity_units == 400
    # Revisions share one source hash but advance the ordinal twice.
    assert apply_rev.revision_ordinal == bust.revision_ordinal + 1
    state = norm.state_for("client-line-1")
    assert state.cumulative_quantity_units == 400
    assert state.revision_ordinal == 3


def test_correction_without_active_fact_halts() -> None:
    norm = ExecutionNormalizer()
    result = norm.apply(
        _obs(seq=1, qty=0, notional=0, fee=0, kind="correction", corrected_qty=100,
             corrected_notional=100_000, corrected_fee=5)
    )
    assert len(result.halts) == 1
    assert result.halts[0].code is NormalizationHaltCode.CORRECTION_WITHOUT_ACTIVE_FACT


def test_negative_impossible_share_halts_not_clamps() -> None:
    norm = ExecutionNormalizer()
    norm.apply(_obs(seq=1, qty=500, notional=500_000, fee=25))
    result = norm.apply(
        _obs(seq=2, qty=500, notional=500_000, fee=25, kind="correction",
             corrected_qty=-10, corrected_notional=0, corrected_fee=0)
    )
    assert len(result.halts) == 1
    assert result.halts[0].code is NormalizationHaltCode.CORRECTION_REDUCES_BELOW_ZERO


# -- convergence: any permutation of the same set converges ----------------


def _fill_set() -> tuple[CumulativeObservation, ...]:
    return (
        _obs(seq=1, qty=100, notional=100_000, fee=5),
        _obs(seq=2, qty=250, notional=250_000, fee=12),
        _obs(seq=3, qty=500, notional=500_000, fee=25),
    )


def test_normalize_batch_converges_across_permutations() -> None:
    fills = _fill_set()
    reference = ExecutionNormalizer().normalize_batch(fills)
    for perm in itertools.permutations(fills):
        result = ExecutionNormalizer().normalize_batch(perm)
        assert len(result.revisions) == len(reference.revisions)
        assert result.final_state == reference.final_state
        # Same delta totals and cumulative endpoints regardless of order.
        assert (
            sum(r.delta_quantity_units for r in result.revisions)
            == sum(r.delta_quantity_units for r in reference.revisions)
            == 500
        )
        assert (
            sum(r.delta_notional_cents for r in result.revisions)
            == sum(r.delta_notional_cents for r in reference.revisions)
            == 500_000
        )


def test_normalize_batch_dedups_duplicate_late_push_and_poll() -> None:
    fills = _fill_set()
    # Duplicate one fill (push + poll both deliver it) and add a late fill.
    dup = _obs(seq=2, qty=250, notional=250_000, fee=12)  # same source hash-2
    late = _obs(seq=4, qty=600, notional=600_000, fee=30)
    batch = fills + (dup, late)
    result = ExecutionNormalizer().normalize_batch(batch)
    # 4 unique fills (100, 250, 500, 600); the duplicate hash-2 is a no-op.
    assert len(result.revisions) == 4
    assert result.final_state.cumulative_quantity_units == 600
    assert sum(r.delta_quantity_units for r in result.revisions) == 600


def test_normalize_batch_halts_on_first_unexplained_rollback() -> None:
    fills = _fill_set()
    # A rollback that is NOT a bust, arriving after the high-water mark.
    rollback = _obs(seq=4, qty=200, notional=200_000, fee=10)
    result = ExecutionNormalizer().normalize_batch(fills + (rollback,))
    assert len(result.halts) == 1
    assert result.halts[0].code is NormalizationHaltCode.UNEXPLAINED_CUMULATIVE_ROLLBACK
    # The three valid fills booked before the halt.
    assert len(result.revisions) == 3


# -- partial fee delta ------------------------------------------------------


def test_partial_fee_delta_books_independently() -> None:
    norm = ExecutionNormalizer()
    norm.apply(_obs(seq=1, qty=100, notional=100_000, fee=5))
    result = norm.apply(_obs(seq=2, qty=200, notional=200_000, fee=5))
    rev = result.revisions[0]
    assert rev.delta_quantity_units == 100
    assert rev.delta_notional_cents == 100_000
    assert rev.delta_fee_cents == 0  # fee did not advance this observation
