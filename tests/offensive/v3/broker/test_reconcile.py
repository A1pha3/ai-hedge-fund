"""Plan 07 Task 5 (RED): complete paginated reconciliation.

锁定约束:
1. completeness proof: 缺页/重复页/cursor 回退/留存过短/陈旧快照 = BLOCKING
   break, 在逐项比对前阻断.
2. exact match (multi-page) => matched_orders, 无 break.
3. material/unknown break: 锁定 no-entry 但 external_fact 先持久化 (不丢弃).
4. confirmation 只 link 已有 canonical fact 或 post delta, 不重复资本
   (此处表现为 matched 不重复入账).
5. tolerance 按 fact 类型版本化: qty/notional/cash BLOCKING, fee ADVISORY;
   无通用货币 epsilon.
6. unexplained cash/share 超容差 = BLOCKING.
7. unknown order / missing execution = BLOCKING 且 external_fact 保留.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.screening.offensive.v3.broker.normalizer import (
    CumulativeObservation,
    ExecutionNormalizer,
)
from src.screening.offensive.v3.broker.reconcile import (
    BreakKind,
    BreakSeverity,
    BrokerAccountFact,
    BrokerOrderFact,
    CompletenessProof,
    FactTolerances,
    QueryPage,
    Reconciler,
)

T0 = datetime(2026, 8, 7, 2, 0, 0, tzinfo=timezone.utc)


def _pages(n: int, *, rollback_at: int | None = None) -> tuple[QueryPage, ...]:
    out: list[QueryPage] = []
    cursor = "cursor-0"
    for i in range(1, n + 1):
        before = cursor
        after = f"cursor-{i}"
        if rollback_at is not None and i == rollback_at:
            before = "cursor-x"  # discontinuity
        out.append(
            QueryPage(
                page_ordinal=i,
                cursor_before=before,
                cursor_after=after,
                envelope_root=f"root-{i}",
                received_at=T0 + timedelta(seconds=i),
            )
        )
        cursor = after
    return tuple(out)


def _proof(
    *,
    page_count: int = 2,
    pages: tuple[QueryPage, ...] | None = None,
    retention_days: int = 30,
    horizon_days: int = 30,
    received_at: datetime | None = None,
) -> CompletenessProof:
    return CompletenessProof(
        query_parameters_hash="qp-hash",
        expected_page_count=page_count,
        pages=pages if pages is not None else _pages(page_count),
        broker_as_of=T0,
        received_at=received_at or T0,
        retention_calendar_days=retention_days,
        retention_horizon_days=horizon_days,
    )


def _normalize(client_id: str, qty: int, notional: int, fee: int) -> ExecutionNormalizer:
    norm = ExecutionNormalizer()
    norm.apply(
        CumulativeObservation(
            client_order_id=client_id,
            cumulative_quantity_units=qty,
            cumulative_notional_cents=notional,
            cumulative_fee_cents=fee,
            observed_at=T0,
            source_envelope_hash="h1",
            kind="execution",
        )
    )
    return norm


# -- completeness proof gating ----------------------------------------------


def test_missing_page_blocks_before_comparison() -> None:
    norm = ExecutionNormalizer()
    rec = Reconciler(norm)
    snapshot = rec.capture_complete_snapshot(
        _proof(page_count=3, pages=_pages(2)),
        orders=(),
        account=BrokerAccountFact(cash_cents=0),
    )
    result = rec.compare(snapshot, local_cash_cents=0)
    assert len(result.breaks) == 1
    assert result.breaks[0].kind is BreakKind.MISSING_PAGE
    assert result.breaks[0].severity is BreakSeverity.BLOCKING


def test_repeated_page_blocks() -> None:
    norm = ExecutionNormalizer()
    rec = Reconciler(norm)
    pages = _pages(2) + (QueryPage(2, "cursor-1", "cursor-2", "root-2b", T0),)
    snapshot = rec.capture_complete_snapshot(
        _proof(page_count=3, pages=pages),
        orders=(),
        account=BrokerAccountFact(cash_cents=0),
    )
    result = rec.compare(snapshot, local_cash_cents=0)
    assert result.breaks[0].kind is BreakKind.REPEATED_PAGE


def test_cursor_rollback_blocks() -> None:
    norm = ExecutionNormalizer()
    rec = Reconciler(norm)
    pages = _pages(3, rollback_at=2)
    snapshot = rec.capture_complete_snapshot(
        _proof(page_count=3, pages=pages),
        orders=(),
        account=BrokerAccountFact(cash_cents=0),
    )
    result = rec.compare(snapshot, local_cash_cents=0)
    assert result.breaks[0].kind is BreakKind.CURSOR_ROLLBACK


def test_retention_too_short_blocks() -> None:
    norm = ExecutionNormalizer()
    rec = Reconciler(norm)
    snapshot = rec.capture_complete_snapshot(
        _proof(retention_days=10, horizon_days=30),
        orders=(),
        account=BrokerAccountFact(cash_cents=0),
    )
    result = rec.compare(snapshot, local_cash_cents=0)
    assert result.breaks[0].kind is BreakKind.RETENTION_TOO_SHORT


def test_stale_snapshot_blocks() -> None:
    norm = ExecutionNormalizer()
    rec = Reconciler(
        norm,
        tolerances=FactTolerances(snapshot_max_age_seconds=60),
        now=T0 + timedelta(seconds=120),
    )
    snapshot = rec.capture_complete_snapshot(
        _proof(received_at=T0),
        orders=(),
        account=BrokerAccountFact(cash_cents=0),
    )
    result = rec.compare(snapshot, local_cash_cents=0)
    assert result.breaks[0].kind is BreakKind.STALE_SNAPSHOT


# -- exact multi-page match -------------------------------------------------


def test_multi_page_exact_match_no_breaks() -> None:
    norm = _normalize("client-1", 500, 500_000, 25)
    rec = Reconciler(norm)
    orders = (
        BrokerOrderFact("client-1", 500, 500_000, 25),
    )
    snapshot = rec.capture_complete_snapshot(
        _proof(page_count=3),
        orders=orders,
        account=BrokerAccountFact(cash_cents=99_975),
    )
    result = rec.compare(
        snapshot,
        local_cash_cents=99_975,
        expected_client_order_ids=("client-1",),
    )
    assert result.breaks == ()
    assert result.matched_orders == ("client-1",)
    assert not result.has_blocking


# -- material / unknown breaks preserve external fact ----------------------


def test_quantity_mismatch_blocks_and_preserves_external_fact() -> None:
    norm = _normalize("client-1", 500, 500_000, 25)
    rec = Reconciler(norm)
    broker_fact = BrokerOrderFact("client-1", 400, 500_000, 25)
    snapshot = rec.capture_complete_snapshot(
        _proof(),
        orders=(broker_fact,),
        account=BrokerAccountFact(cash_cents=0),
    )
    result = rec.compare(snapshot, local_cash_cents=0)
    kinds = {b.kind for b in result.breaks}
    assert BreakKind.QUANTITY_MISMATCH in kinds
    qty_break = next(b for b in result.breaks if b.kind is BreakKind.QUANTITY_MISMATCH)
    assert qty_break.external_fact is broker_fact
    assert result.has_blocking
    assert "client-1" not in result.matched_orders


def test_unknown_order_blocks_and_persists_external_fact() -> None:
    norm = ExecutionNormalizer()  # no local state for client-x
    rec = Reconciler(norm)
    broker_fact = BrokerOrderFact("client-x", 100, 100_000, 5)
    snapshot = rec.capture_complete_snapshot(
        _proof(),
        orders=(broker_fact,),
        account=BrokerAccountFact(cash_cents=0),
    )
    result = rec.compare(
        snapshot,
        local_cash_cents=0,
        expected_client_order_ids=("client-x",),
    )
    unknown = next(b for b in result.breaks if b.kind is BreakKind.UNKNOWN_ORDER)
    assert unknown.external_fact is broker_fact
    assert unknown.severity is BreakSeverity.BLOCKING


def test_missing_execution_blocks() -> None:
    norm = _normalize("client-1", 500, 500_000, 25)
    rec = Reconciler(norm)
    snapshot = rec.capture_complete_snapshot(
        _proof(),
        orders=(),  # broker snapshot omits client-1
        account=BrokerAccountFact(cash_cents=0),
    )
    result = rec.compare(
        snapshot,
        local_cash_cents=0,
        expected_client_order_ids=("client-1",),
    )
    assert any(b.kind is BreakKind.MISSING_EXECUTION for b in result.breaks)


def test_unexplained_cash_blocks() -> None:
    norm = _normalize("client-1", 500, 500_000, 25)
    rec = Reconciler(norm)
    snapshot = rec.capture_complete_snapshot(
        _proof(),
        orders=(BrokerOrderFact("client-1", 500, 500_000, 25),),
        account=BrokerAccountFact(cash_cents=99_000),  # 975 off
    )
    result = rec.compare(snapshot, local_cash_cents=99_975)
    assert any(b.kind is BreakKind.UNEXPLAINED_CASH for b in result.breaks)
    assert result.has_blocking


# -- versioned per-fact tolerance -------------------------------------------


def test_fee_mismatch_is_advisory_not_blocking() -> None:
    norm = _normalize("client-1", 500, 500_000, 25)
    rec = Reconciler(norm)
    snapshot = rec.capture_complete_snapshot(
        _proof(),
        orders=(BrokerOrderFact("client-1", 500, 500_000, 30),),  # +5 fee
        account=BrokerAccountFact(cash_cents=99_975),
    )
    result = rec.compare(snapshot, local_cash_cents=99_975)
    fee_breaks = [b for b in result.breaks if b.kind is BreakKind.FEE_MISMATCH]
    assert len(fee_breaks) == 1
    assert fee_breaks[0].severity is BreakSeverity.ADVISORY
    assert not result.has_blocking


def test_quantity_within_tolerance_matches() -> None:
    norm = _normalize("client-1", 500, 500_000, 25)
    rec = Reconciler(norm, tolerances=FactTolerances(quantity_units=2))
    snapshot = rec.capture_complete_snapshot(
        _proof(),
        orders=(BrokerOrderFact("client-1", 501, 500_000, 25),),
        account=BrokerAccountFact(cash_cents=99_975),
    )
    result = rec.compare(snapshot, local_cash_cents=99_975)
    assert not result.has_blocking
    assert result.matched_orders == ("client-1",)


def test_confirmation_does_not_duplicate_capital() -> None:
    # A confirmation that links an existing canonical fact matches without
    # producing any new revision or break.
    norm = _normalize("client-1", 500, 500_000, 25)
    rec = Reconciler(norm)
    snapshot = rec.capture_complete_snapshot(
        _proof(),
        orders=(BrokerOrderFact("client-1", 500, 500_000, 25),),
        account=BrokerAccountFact(cash_cents=99_975),
    )
    result = rec.compare(
        snapshot,
        local_cash_cents=99_975,
        expected_client_order_ids=("client-1",),
    )
    assert result.breaks == ()
    # No new normalization revisions were emitted by reconciliation.
    state = norm.state_for("client-1")
    assert state.revision_ordinal == 1
