"""Plan 02 Task 4: corporate actions and successor lot/exit continuity.

Coverage per the plan:

- ex-date / pay-date / tradable-date ordering and state gates;
- fractional rational entitlements (exact numerator/denominator, never
  float) and cash-in-lieu for fractional remainders;
- split/merge with exact basis transformation (aggregate basis preserved,
  per-share basis an exact rational);
- dividend correction: the revised entitlement supersedes the as-observed
  one without erasing it (append-only revision via ``event_revisions``);
- merger/conversion to a successor security, delisting, and a successor
  inheriting the economic lot AND the due exit obligation;
- the source-authority matrix: as-observed vs confirmed, where a
  confirmation changes only the unresolved delta and never rewrites
  settled legs/cash;
- stable economic fact/revision identities: re-recording the same action
  converges, different actions never collide;
- a property test keeping conservation before/after every generated
  corporate-action chain interleaved with fills and valuations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.screening.offensive.v3.capital.corporate_actions import (
    ConversionDestination,
    CorporateActionKind,
    CorporateActionState,
    SourceAuthorityTier,
    CashInLieuRequest,
    ConversionRequest,
    EntitlementRequest,
    SharesTradableRequest,
    SplitMergeRequest,
    TerminalCashRequest,
    WriteOffRequest,
    entitlement_idempotency_key,
    split_entitlement,
)
from src.screening.offensive.v3.capital.fills import (
    FillAttribution,
    FillRevisionRequest,
)
from src.screening.offensive.v3.capital.flows import (
    GenesisRequest,
    LifecycleState,
)
from src.screening.offensive.v3.capital.nav import (
    ValuationMarkInput,
    ValuationRequest,
)
from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalConflict,
    CapitalRepository,
)
from src.screening.offensive.v3.capital.rounding import fill_gross_cents
from src.screening.offensive.v3.contracts import (
    EconomicEventKind,
    ExecutionMode,
    ExecutionSide,
    PositionState,
    RationalQuantity,
)


T0 = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
ENVIRONMENT_FINGERPRINT = "ab" * 32

GENESIS_UNITS = 10_000
GENESIS_PRICE_NUMERATOR = 1_000
GENESIS_PRICE_DENOMINATOR = 1
GENESIS_CASH_CENTS = GENESIS_UNITS * GENESIS_PRICE_NUMERATOR

ATTRIBUTION = FillAttribution(
    producer_namespace="btst",
    research_program_id="prog-1",
    economic_lineage_id="eline-1",
    stage_id="stage-1",
)

SECURITY = "600000.SH"
SUCCESSOR = "600001.SH"


def binding() -> AccountBinding:
    return AccountBinding(
        portfolio_id="pf-test",
        mode=ExecutionMode.MANUAL_CONFIRMED,
        broker_account_id="acct-test",
        base_currency="CNY",
        environment_fingerprint=ENVIRONMENT_FINGERPRINT,
    )


def _moment(step: int) -> datetime:
    return T0 + timedelta(minutes=step)


@pytest.fixture()
def repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


def genesis(repository: CapitalRepository, *, step: int = 0) -> None:
    repository.initialize_genesis(
        GenesisRequest(
            idempotency_key=f"genesis-{step}",
            account_binding=binding(),
            unit_quanta=GENESIS_UNITS,
            unit_price_numerator=GENESIS_PRICE_NUMERATOR,
            unit_price_denominator=GENESIS_PRICE_DENOMINATOR,
            source_authority="governance.test",
            authorization_reference="gov-genesis-1",
            effective_at=_moment(step),
            as_of=_moment(step),
        )
    )


def entry(
    repository: CapitalRepository,
    *,
    step: int,
    execution_id: str = "exec-entry-1",
    security_id: str = SECURITY,
    price_micros: int = 10_000_000,
    quantity: int = 1_000,
    lineage: str = "lin-1",
    lot: str = "lot-1",
) -> None:
    repository.record_fill_revision(
        FillRevisionRequest(
            execution_id=execution_id,
            revision=1,
            order_id=f"ord-{execution_id}",
            side=ExecutionSide.ENTRY,
            security_id=security_id,
            price_micros=price_micros,
            quantity=quantity,
            position_lineage_id=lineage,
            economic_lot_id=lot,
            attribution=ATTRIBUTION,
            source_authority="broker.test",
            effective_at=_moment(step),
            as_of=_moment(step) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )


def exit_(
    repository: CapitalRepository,
    *,
    step: int,
    execution_id: str,
    quantity: int,
    security_id: str = SECURITY,
    price_micros: int = 10_000_000,
    lineage: str = "lin-1",
    lot: str = "lot-1",
) -> None:
    repository.record_fill_revision(
        FillRevisionRequest(
            execution_id=execution_id,
            revision=1,
            order_id=f"ord-{execution_id}",
            side=ExecutionSide.EXIT,
            security_id=security_id,
            price_micros=price_micros,
            quantity=quantity,
            position_lineage_id=lineage,
            economic_lot_id=lot,
            attribution=ATTRIBUTION,
            source_authority="broker.test",
            effective_at=_moment(step),
            as_of=_moment(step) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )


def mark(repository: CapitalRepository, *, step: int, marks: dict[str, int]) -> None:
    repository.close_valuation(
        ValuationRequest(
            idempotency_key=f"valuation-{step}",
            source_authority="valuation.test",
            effective_at=_moment(step),
            as_of=_moment(step),
            expected_stream_version=repository.stream_version(),
            marks=tuple(
                ValuationMarkInput(security_id=security_id, price_micros=micros)
                for security_id, micros in sorted(marks.items())
            ),
        )
    )


def entitlement_request(
    repository: CapitalRepository,
    *,
    action_id: str,
    revision: int = 1,
    kind: CorporateActionKind = CorporateActionKind.CASH_DIVIDEND,
    numerator: int = 13,
    denominator: int = 4,
    cash_in_lieu_cents: int | None = None,
    tier: SourceAuthorityTier = SourceAuthorityTier.AS_OBSERVED,
    security_id: str = SECURITY,
    lineage: str = "lin-1",
    lot: str = "lot-1",
    step: int = 1,
) -> EntitlementRequest:
    return EntitlementRequest(
        action_id=action_id,
        revision=revision,
        position_lineage_id=lineage,
        economic_lot_id=lot,
        security_id=security_id,
        action_kind=kind,
        entitlement=RationalQuantity(numerator=numerator, denominator=denominator),
        cash_in_lieu_cents=cash_in_lieu_cents,
        tier=tier,
        source_authority="vendor.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
    )


def position_row(repository: CapitalRepository, lot: str = "lot-1"):
    import sqlalchemy as sa

    with repository.engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT * FROM positions WHERE economic_lot_id = :lot"),
            {"lot": lot},
        ).one()


def receivable_rows(repository: CapitalRepository):
    import sqlalchemy as sa

    with repository.engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT * FROM receivables ORDER BY receivable_id")
        ).all()


# ---------------------------------------------------------------------------
# Exact rational entitlement math (integer only, never float)
# ---------------------------------------------------------------------------


def test_split_entitlement_is_exact_integer_arithmetic() -> None:
    whole, num, den = split_entitlement(100, 1, 3)
    assert (whole, num, den) == (33, 1, 3)
    whole, num, den = split_entitlement(100, 1, 4)
    assert (whole, num, den) == (25, 0, 1)
    whole, num, den = split_entitlement(2, 1, 3)
    assert (whole, num, den) == (0, 2, 3)
    whole, num, den = split_entitlement(1_000, 13, 4)
    assert (whole, num, den) == (3_250, 0, 1)
    # The remainder is always in lowest terms.
    whole, num, den = split_entitlement(10, 7, 12)
    assert (whole, num, den) == (5, 5, 6)
    with pytest.raises(ValueError):
        split_entitlement(0, 1, 2)
    with pytest.raises(ValueError):
        split_entitlement(10, 0, 2)
    with pytest.raises(ValueError):
        split_entitlement(10, 1, 0)


# ---------------------------------------------------------------------------
# Cash dividends: ex date, pay date, ordering gates
# ---------------------------------------------------------------------------


def test_cash_dividend_entitlement_books_exact_receivable_on_ex_date(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)

    receipt, snapshot = repository.record_entitlement(
        entitlement_request(
            repository, action_id="div-2026-001", numerator=13, denominator=4
        )
    )
    # 1000 shares x 13/4 cents = exactly 3250 cents. No float anywhere.
    assert receipt.cash_amount_cents == 3_250
    assert receipt.fractional_remainder_numerator == 0
    assert receipt.fractional_remainder_denominator == 1
    assert type(receipt.cash_amount_cents) is int
    assert snapshot.cash_receivable_cents == 3_250

    record = repository.corporate_action_record("div-2026-001", "lin-1", "lot-1")
    assert record is not None
    assert record.state is CorporateActionState.PENDING
    assert record.source_authority_tier is SourceAuthorityTier.AS_OBSERVED
    assert record.receivable_id == receipt.receivable_id
    assert record.entitlement == (13, 4)

    report = repository.assert_conservation()
    assert report.dividend_income_cents == 3_250


def test_cash_dividend_requires_exact_cents_fail_closed(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)
    stream = repository.stream_version()
    capital = repository.capital_version()

    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_entitlement(
            entitlement_request(
                repository, action_id="div-bad", numerator=1, denominator=3
            )
        )
    assert excinfo.value.code == "entitlement_not_exact"
    assert repository.stream_version() == stream
    assert repository.capital_version() == capital
    repository.assert_conservation()


def test_entitlement_gates_on_lot_identity_and_lifecycle(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)

    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_entitlement(
            entitlement_request(repository, action_id="div-x", lot="lot-ghost")
        )
    assert excinfo.value.code == "lot_unknown"

    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_entitlement(
            entitlement_request(
                repository, action_id="div-x", security_id="000001.SZ"
            )
        )
    assert excinfo.value.code == "security_mismatch"

    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_entitlement(
            entitlement_request(
                repository, action_id="div-x", numerator=0, denominator=4
            )
        )
    assert excinfo.value.code == "entitlement_must_be_positive"
    repository.assert_conservation()


def test_pay_date_settles_dividend_and_enforces_ordering(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)
    repository.record_entitlement(
        entitlement_request(repository, action_id="div-1", step=2)
    )

    # Pay date before the ex date violates the ex/pay ordering gate.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.settle_cash_in_lieu(
            CashInLieuRequest(
                action_id="div-1",
                position_lineage_id="lin-1",
                economic_lot_id="lot-1",
                tier=SourceAuthorityTier.CONFIRMED,
                source_authority="broker.test",
                effective_at=_moment(1),
                as_of=_moment(1) + timedelta(seconds=1),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "corporate_action_ordering_violation"
    repository.assert_conservation()

    receipt, snapshot = repository.settle_cash_in_lieu(
        CashInLieuRequest(
            action_id="div-1",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="broker.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.amount_cents == 3_250
    assert snapshot.available_cash_cents == GENESIS_CASH_CENTS - 1_000_000 + 3_250
    assert snapshot.cash_receivable_cents == 0

    record = repository.corporate_action_record("div-1", "lin-1", "lot-1")
    assert record.state is CorporateActionState.CASH_SETTLED
    assert record.pay_effective_at is not None
    rows = receivable_rows(repository)
    assert len(rows) == 1
    assert int(rows[0].settled) == 1
    assert rows[0].settled_by_event_id == receipt.event_id
    repository.assert_conservation()

    # Idempotent re-settlement converges without growing the stream.
    stream = repository.stream_version()
    retry, retry_snapshot = repository.settle_cash_in_lieu(
        CashInLieuRequest(
            action_id="div-1",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="broker.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert retry.event_id == receipt.event_id
    assert repository.stream_version() == stream
    assert retry_snapshot.available_cash_cents == snapshot.available_cash_cents


def test_settle_unknown_action_fails_closed(repository: CapitalRepository) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.settle_cash_in_lieu(
            CashInLieuRequest(
                action_id="div-ghost",
                position_lineage_id="lin-1",
                economic_lot_id="lot-1",
                tier=SourceAuthorityTier.CONFIRMED,
                source_authority="broker.test",
                effective_at=_moment(2),
                as_of=_moment(2),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "corporate_action_unknown"
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Share entitlements: fractional rationals, cash-in-lieu, tradable date
# ---------------------------------------------------------------------------


def test_share_entitlement_fractional_remainder_and_cash_in_lieu(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100)

    receipt, snapshot = repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="bonus-1",
            kind=CorporateActionKind.SHARE_ENTITLEMENT,
            numerator=1,
            denominator=3,
            cash_in_lieu_cents=500,
        )
    )
    # 100 x 1/3 = 33 whole shares + exact 1/3 remainder (never a float).
    assert receipt.share_quantity == 33
    assert receipt.fractional_remainder_numerator == 1
    assert receipt.fractional_remainder_denominator == 3
    assert receipt.cash_in_lieu_cents == 500

    position = next(
        item for item in snapshot.positions if item.economic_lot_id == "lot-1"
    )
    assert position.settled_quantity == 100
    assert position.tradable_quantity == 100
    assert position.share_receivable_quantity == 33
    # The cash-in-lieu for the fractional remainder is a cash receivable.
    assert snapshot.cash_receivable_cents == 500

    record = repository.corporate_action_record("bonus-1", "lin-1", "lot-1")
    assert record.fractional_remainder == (1, 3)
    assert record.cash_in_lieu_cents == 500
    assert record.receivable_id is not None
    assert record.cash_in_lieu_receivable_id is not None

    report = repository.assert_conservation()
    assert report.dividend_income_cents == 500


def test_share_entitlement_with_zero_whole_shares_books_only_cash_in_lieu(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=2)

    receipt, snapshot = repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="bonus-tiny",
            kind=CorporateActionKind.SHARE_ENTITLEMENT,
            numerator=1,
            denominator=3,
            cash_in_lieu_cents=40,
        )
    )
    assert receipt.share_quantity is None
    assert receipt.fractional_remainder_numerator == 2
    assert receipt.fractional_remainder_denominator == 3
    assert snapshot.cash_receivable_cents == 40
    position = next(
        item for item in snapshot.positions if item.economic_lot_id == "lot-1"
    )
    assert position.share_receivable_quantity == 0
    repository.assert_conservation()


def test_share_entitlement_without_cash_in_lieu_preserves_remainder(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100)
    receipt, snapshot = repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="bonus-open",
            kind=CorporateActionKind.SHARE_ENTITLEMENT,
            numerator=1,
            denominator=3,
        )
    )
    assert receipt.share_quantity == 33
    assert receipt.cash_in_lieu_cents is None
    # The unresolved fractional remainder stays an exact rational on the
    # action record: it is never clamped or silently dropped.
    record = repository.corporate_action_record("bonus-open", "lin-1", "lot-1")
    assert record.fractional_remainder == (1, 3)
    assert snapshot.cash_receivable_cents == 0
    repository.assert_conservation()


def test_make_shares_tradable_moves_receivable_into_settled(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100)
    repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="bonus-1",
            kind=CorporateActionKind.SHARE_ENTITLEMENT,
            numerator=1,
            denominator=1,
            step=2,
        )
    )

    # The tradable date cannot precede the ex date.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.make_shares_tradable(
            SharesTradableRequest(
                action_id="bonus-1",
                position_lineage_id="lin-1",
                economic_lot_id="lot-1",
                tier=SourceAuthorityTier.CONFIRMED,
                source_authority="exchange.test",
                effective_at=_moment(1),
                as_of=_moment(1) + timedelta(seconds=1),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "corporate_action_ordering_violation"

    receipt, snapshot = repository.make_shares_tradable(
        SharesTradableRequest(
            action_id="bonus-1",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="exchange.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.quantity == 100
    position = next(
        item for item in snapshot.positions if item.economic_lot_id == "lot-1"
    )
    assert position.settled_quantity == 200
    assert position.tradable_quantity == 200
    assert position.share_receivable_quantity == 0

    record = repository.corporate_action_record("bonus-1", "lin-1", "lot-1")
    assert record.state is CorporateActionState.SHARES_TRADABLE
    assert record.tradable_effective_at is not None
    # shares_became_tradable_at is a real timestamp, surfaced on receipt.
    assert receipt.shares_became_tradable_at == record.tradable_effective_at

    rows = receivable_rows(repository)
    share_rows = [row for row in rows if row.receivable_kind == "SHARE"]
    assert len(share_rows) == 1
    assert int(share_rows[0].settled) == 1
    assert int(share_rows[0].quantity_units) == 100
    repository.assert_conservation()

    # Re-recording the same tradable fact converges.
    stream = repository.stream_version()
    retry, _ = repository.make_shares_tradable(
        SharesTradableRequest(
            action_id="bonus-1",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="exchange.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert retry.event_id == receipt.event_id
    assert repository.stream_version() == stream


def test_tradable_date_works_when_bonus_exceeds_holding(
    repository: CapitalRepository,
) -> None:
    # 10-for-30 transfer on 1 share: the receivable (3) exceeds the
    # settled holding (1), so the representation-conversion path must not
    # consume settled shares.
    genesis(repository)
    entry(repository, step=1, quantity=1)
    repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="transfer-30",
            kind=CorporateActionKind.SHARE_ENTITLEMENT,
            numerator=3,
            denominator=1,
            step=2,
        )
    )
    receipt, snapshot = repository.make_shares_tradable(
        SharesTradableRequest(
            action_id="transfer-30",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="exchange.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.quantity == 3
    position = next(
        item for item in snapshot.positions if item.economic_lot_id == "lot-1"
    )
    assert position.settled_quantity == 4
    assert position.tradable_quantity == 4
    assert position.share_receivable_quantity == 0
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Split / merge: exact basis transformation
# ---------------------------------------------------------------------------


def test_split_preserves_aggregate_basis_with_rational_per_share(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    # 100 shares at 12.3456 yuan -> aggregate basis 123_456 cents exactly.
    entry(repository, step=1, quantity=100, price_micros=12_345_600)

    receipt, snapshot = repository.apply_split_merge(
        SplitMergeRequest(
            action_id="split-2026-1",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            security_id=SECURITY,
            action_kind=CorporateActionKind.SPLIT,
            ratio=RationalQuantity(numerator=2, denominator=1),
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="exchange.test",
            effective_at=_moment(2),
            as_of=_moment(2) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.prior_quantity == 100
    assert receipt.new_quantity == 200
    assert receipt.cost_basis_cents == 123_456
    # Per-share basis is an exact rational (lowest terms), never a float.
    assert receipt.per_share_basis_numerator == 15_432
    assert receipt.per_share_basis_denominator == 25
    assert (
        Fraction(receipt.per_share_basis_numerator, receipt.per_share_basis_denominator)
        == Fraction(123_456, 200)
    )

    position = next(
        item for item in snapshot.positions if item.economic_lot_id == "lot-1"
    )
    assert position.settled_quantity == 200
    assert position.tradable_quantity == 200
    row = position_row(repository)
    assert int(row.cost_basis_cents) == 123_456

    # The reverse merge restores the quantity and still preserves basis.
    merge_receipt, _ = repository.apply_split_merge(
        SplitMergeRequest(
            action_id="merge-2026-1",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            security_id=SECURITY,
            action_kind=CorporateActionKind.MERGE,
            ratio=RationalQuantity(numerator=1, denominator=2),
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="exchange.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert merge_receipt.new_quantity == 100
    assert merge_receipt.cost_basis_cents == 123_456
    repository.assert_conservation()


def test_split_requires_exact_new_quantity(repository: CapitalRepository) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100)
    stream = repository.stream_version()
    with pytest.raises(CapitalConflict) as excinfo:
        repository.apply_split_merge(
            SplitMergeRequest(
                action_id="split-bad",
                position_lineage_id="lin-1",
                economic_lot_id="lot-1",
                security_id=SECURITY,
                action_kind=CorporateActionKind.SPLIT,
                ratio=RationalQuantity(numerator=7, denominator=3),
                tier=SourceAuthorityTier.CONFIRMED,
                source_authority="exchange.test",
                effective_at=_moment(2),
                as_of=_moment(2),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "split_quantity_not_exact"
    assert repository.stream_version() == stream
    repository.assert_conservation()


def test_split_ratio_direction_must_match_kind(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.apply_split_merge(
            SplitMergeRequest(
                action_id="split-wrong",
                position_lineage_id="lin-1",
                economic_lot_id="lot-1",
                security_id=SECURITY,
                action_kind=CorporateActionKind.SPLIT,
                ratio=RationalQuantity(numerator=1, denominator=2),
                tier=SourceAuthorityTier.CONFIRMED,
                source_authority="exchange.test",
                effective_at=_moment(2),
                as_of=_moment(2),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "split_ratio_conflict"


def test_split_blocked_while_share_entitlement_pending(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100)
    repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="bonus-open",
            kind=CorporateActionKind.SHARE_ENTITLEMENT,
            numerator=1,
            denominator=2,
            step=2,
        )
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.apply_split_merge(
            SplitMergeRequest(
                action_id="split-blocked",
                position_lineage_id="lin-1",
                economic_lot_id="lot-1",
                security_id=SECURITY,
                action_kind=CorporateActionKind.SPLIT,
                ratio=RationalQuantity(numerator=2, denominator=1),
                tier=SourceAuthorityTier.CONFIRMED,
                source_authority="exchange.test",
                effective_at=_moment(3),
                as_of=_moment(3),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "entitlement_pending"
    repository.assert_conservation()


def test_split_keeps_due_exit_state(repository: CapitalRepository) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100)
    exit_(repository, step=2, execution_id="exec-exit-1", quantity=40)
    assert position_row(repository).state == PositionState.EXIT_PENDING.value

    receipt, _ = repository.apply_split_merge(
        SplitMergeRequest(
            action_id="split-exiting",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            security_id=SECURITY,
            action_kind=CorporateActionKind.SPLIT,
            ratio=RationalQuantity(numerator=2, denominator=1),
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="exchange.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.new_quantity == 120
    assert position_row(repository).state == PositionState.EXIT_PENDING.value
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Conversion / merger: successor lot and exit-obligation continuity
# ---------------------------------------------------------------------------


def test_conversion_successor_inherits_lot_basis_and_exit_obligation(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100, price_micros=10_000_000)
    # Make the exit obligation due: partial exit puts the lot EXIT_PENDING.
    exit_(repository, step=2, execution_id="exec-exit-1", quantity=40)
    row = position_row(repository)
    basis_before = int(row.cost_basis_cents)
    assert row.state == PositionState.EXIT_PENDING.value

    receipt, snapshot = repository.convert_security(
        ConversionRequest(
            action_id="merger-2026-1",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            source_security_id=SECURITY,
            successor_security_id=SUCCESSOR,
            ratio=RationalQuantity(numerator=1, denominator=2),
            destination=ConversionDestination.TRADABLE,
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="legal.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.prior_settled_quantity == 60
    assert receipt.successor_quantity == 30
    assert receipt.cost_basis_cents == basis_before
    # The successor inherits the economic lot identity, attribution, cost
    # basis AND the due exit obligation (state preserved).
    assert receipt.inherited_position_state is PositionState.EXIT_PENDING

    position = snapshot.positions[0]
    assert position.position_lineage_id == "lin-1"
    assert position.economic_lot_id == "lot-1"
    assert position.security_id == SUCCESSOR
    assert position.settled_quantity == 30
    assert position.tradable_quantity == 30
    assert position.state is PositionState.EXIT_PENDING
    assert position.producer_namespace == ATTRIBUTION.producer_namespace
    assert position.research_program_id == ATTRIBUTION.research_program_id

    row = position_row(repository)
    assert int(row.cost_basis_cents) == basis_before

    record = repository.corporate_action_record("merger-2026-1", "lin-1", "lot-1")
    assert record.state is CorporateActionState.CONVERTED
    assert record.successor_security_id == SUCCESSOR
    assert record.successor_quantity_units == 30
    assert record.inherited_position_state == PositionState.EXIT_PENDING.value
    repository.assert_conservation()

    # The due exit obligation remains executable against the successor.
    exit_(
        repository,
        step=4,
        execution_id="exec-exit-successor",
        quantity=30,
        security_id=SUCCESSOR,
    )
    assert position_row(repository).state == PositionState.CLOSED.value
    repository.assert_conservation()


def test_conversion_restricted_destination_stays_untradable(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=60)
    receipt, snapshot = repository.convert_security(
        ConversionRequest(
            action_id="merger-lockup",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            source_security_id=SECURITY,
            successor_security_id=SUCCESSOR,
            ratio=RationalQuantity(numerator=1, denominator=1),
            destination=ConversionDestination.RESTRICTED,
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="legal.test",
            effective_at=_moment(2),
            as_of=_moment(2) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.successor_quantity == 60
    assert receipt.successor_receivable_id is not None
    position = snapshot.positions[0]
    assert position.security_id == SUCCESSOR
    assert position.settled_quantity == 0
    assert position.tradable_quantity == 0
    assert position.share_receivable_quantity == 60
    repository.assert_conservation()

    # The lockup ends through the same tradable-date machinery.
    tradable_receipt, snapshot = repository.make_shares_tradable(
        SharesTradableRequest(
            action_id="merger-lockup",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="exchange.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert tradable_receipt.quantity == 60
    position = snapshot.positions[0]
    assert position.settled_quantity == 60
    assert position.tradable_quantity == 60
    repository.assert_conservation()


def test_conversion_sweeps_outstanding_share_receivable(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100)
    repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="bonus-pre-merger",
            kind=CorporateActionKind.SHARE_ENTITLEMENT,
            numerator=1,
            denominator=5,
            step=2,
        )
    )
    receipt, snapshot = repository.convert_security(
        ConversionRequest(
            action_id="merger-sweep",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            source_security_id=SECURITY,
            successor_security_id=SUCCESSOR,
            ratio=RationalQuantity(numerator=1, denominator=2),
            destination=ConversionDestination.TRADABLE,
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="legal.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    # (100 settled + 20 receivable) x 1/2 = 60 successor shares.
    assert receipt.prior_settled_quantity == 100
    assert receipt.prior_share_receivable_quantity == 20
    assert receipt.successor_quantity == 60
    position = snapshot.positions[0]
    assert position.settled_quantity == 60
    assert position.share_receivable_quantity == 0
    repository.assert_conservation()


def test_conversion_gates_fail_closed(repository: CapitalRepository) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=60)

    with pytest.raises(CapitalConflict) as excinfo:
        repository.convert_security(
            ConversionRequest(
                action_id="merger-self",
                position_lineage_id="lin-1",
                economic_lot_id="lot-1",
                source_security_id=SECURITY,
                successor_security_id=SECURITY,
                ratio=RationalQuantity(numerator=1, denominator=1),
                destination=ConversionDestination.TRADABLE,
                tier=SourceAuthorityTier.CONFIRMED,
                source_authority="legal.test",
                effective_at=_moment(2),
                as_of=_moment(2),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "conversion_identity_conflict"

    with pytest.raises(CapitalConflict) as excinfo:
        repository.convert_security(
            ConversionRequest(
                action_id="merger-fractional",
                position_lineage_id="lin-1",
                economic_lot_id="lot-1",
                source_security_id=SECURITY,
                successor_security_id=SUCCESSOR,
                ratio=RationalQuantity(numerator=1, denominator=7),
                destination=ConversionDestination.TRADABLE,
                tier=SourceAuthorityTier.CONFIRMED,
                source_authority="legal.test",
                effective_at=_moment(2),
                as_of=_moment(2),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "successor_quantity_not_exact"
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Delisting: terminal cash settlement and legal write-off
# ---------------------------------------------------------------------------


def test_terminal_cash_settlement_closes_lot_with_realized_pnl(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100, price_micros=10_000_000)
    basis = int(position_row(repository).cost_basis_cents)

    # A legal terminal settlement is a confirmed authority fact.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.settle_terminal_cash(
            TerminalCashRequest(
                action_id="delist-observed",
                position_lineage_id="lin-1",
                economic_lot_id="lot-1",
                security_id=SECURITY,
                proceeds_cents=150_000,
                tier=SourceAuthorityTier.AS_OBSERVED,
                source_authority="vendor.test",
                effective_at=_moment(2),
                as_of=_moment(2),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "source_authority_insufficient"

    receipt, snapshot = repository.settle_terminal_cash(
        TerminalCashRequest(
            action_id="delist-2026-1",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            security_id=SECURITY,
            proceeds_cents=150_000,
            tier=SourceAuthorityTier.CONFIRMED,
            legal_evidence_reference="delisting-notice-2026-001",
            source_authority="broker.test",
            effective_at=_moment(2),
            as_of=_moment(2) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.proceeds_cents == 150_000
    assert receipt.consumed_basis_cents == basis
    assert receipt.realized_pnl_cents == 150_000 - basis
    assert snapshot.positions == ()
    assert snapshot.available_cash_cents == GENESIS_CASH_CENTS - basis + 150_000

    row = position_row(repository)
    assert row.state == PositionState.LEGAL_TERMINAL.value
    assert int(row.settled_quantity_units) == 0

    report = repository.assert_conservation()
    assert report.exit_gross_cents == 150_000
    assert report.consumed_cost_basis_cents == basis
    # The disappearing ticker never erased the fact: the canonical event
    # remains in the append-only stream.
    kinds = [event.event_kind for event in repository.events()]
    assert EconomicEventKind.CORPORATE_CASH_SETTLED in kinds


def test_terminal_cash_settlement_sweeps_accrued_receivables(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100)
    entitlement_receipt, _ = repository.record_entitlement(
        entitlement_request(repository, action_id="div-accrued", step=2)
    )
    basis = int(position_row(repository).cost_basis_cents)

    receipt, snapshot = repository.settle_terminal_cash(
        TerminalCashRequest(
            action_id="delist-sweep",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            security_id=SECURITY,
            proceeds_cents=200_000,
            sweep_receivable_ids=(entitlement_receipt.receivable_id,),
            tier=SourceAuthorityTier.CONFIRMED,
            legal_evidence_reference="delisting-notice-2026-002",
            source_authority="broker.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.proceeds_cents == 200_000
    assert snapshot.cash_receivable_cents == 0
    assert snapshot.available_cash_cents == GENESIS_CASH_CENTS - basis + 200_000
    repository.assert_conservation()


def test_legal_write_off_consumes_basis_as_loss(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=100, price_micros=10_000_000)
    entitlement_receipt, _ = repository.record_entitlement(
        entitlement_request(repository, action_id="div-lost", step=2)
    )
    basis = int(position_row(repository).cost_basis_cents)
    stream = repository.stream_version()

    # Legal derecognition requires legal evidence and confirmed authority.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.legal_write_off(
            WriteOffRequest(
                action_id="writeoff-observed",
                position_lineage_id="lin-1",
                economic_lot_id="lot-1",
                security_id=SECURITY,
                tier=SourceAuthorityTier.AS_OBSERVED,
                legal_evidence_reference="court-ruling-2026-001",
                source_authority="vendor.test",
                effective_at=_moment(3),
                as_of=_moment(3),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "source_authority_insufficient"
    assert repository.stream_version() == stream

    receipt, snapshot = repository.legal_write_off(
        WriteOffRequest(
            action_id="writeoff-2026-1",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            security_id=SECURITY,
            sweep_receivable_ids=(entitlement_receipt.receivable_id,),
            tier=SourceAuthorityTier.CONFIRMED,
            legal_evidence_reference="court-ruling-2026-001",
            source_authority="legal.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.written_off_quantity == 100
    assert receipt.written_off_basis_cents == basis
    assert receipt.receivables_written_off == (
        entitlement_receipt.receivable_id,
    )
    assert snapshot.positions == ()
    assert snapshot.cash_receivable_cents == 0
    assert position_row(repository).state == PositionState.LEGAL_TERMINAL.value

    # The write-off balances: the basis leaves assets as a realized loss
    # and the never-paid dividend entitlement reverses its income.
    report = repository.assert_conservation()
    assert report.consumed_cost_basis_cents == basis
    assert report.dividend_income_cents == 0


# ---------------------------------------------------------------------------
# Dividend correction: supersedes as-observed without erasing it
# ---------------------------------------------------------------------------


def test_dividend_correction_supersedes_unsettled_as_observed(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)
    first, _ = repository.record_entitlement(
        entitlement_request(
            repository, action_id="div-fix", numerator=1, denominator=2, step=2
        )
    )
    assert first.cash_amount_cents == 500

    corrected, snapshot = repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="div-fix",
            revision=2,
            numerator=48,
            denominator=100,
            tier=SourceAuthorityTier.CONFIRMED,
            step=3,
        )
    )
    assert corrected.revision == 2
    assert corrected.correction is True
    assert corrected.cash_amount_cents == 480
    assert corrected.supersedes_event_id == first.event_id
    assert snapshot.cash_receivable_cents == 480

    # The as-observed fact is preserved, never rewritten.
    events = repository.events()
    first_event = next(
        event for event in events if event.economic_event_id == first.event_id
    )
    assert first_event.source_authority == "vendor.test"
    corrected_event = next(
        event for event in events if event.economic_event_id == corrected.event_id
    )
    assert corrected_event.correction_of_event_id == first.event_id

    # The append-only revision link connects the two facts.
    import sqlalchemy as sa

    with repository.engine.connect() as conn:
        links = conn.execute(
            sa.text(
                "SELECT canonical_event_id, revision_event_id, revision_kind"
                " FROM event_revisions"
            )
        ).all()
    assert len(links) == 1
    assert links[0].canonical_event_id == first.event_id
    assert links[0].revision_event_id == corrected.event_id
    assert links[0].revision_kind == "LATE_CORRECTION"

    rows = receivable_rows(repository)
    assert len(rows) == 2
    settled = [row for row in rows if int(row.settled) == 1]
    open_rows = [row for row in rows if int(row.settled) == 0]
    assert len(settled) == 1 and int(settled[0].amount_cents) == 500
    assert len(open_rows) == 1 and int(open_rows[0].amount_cents) == 480

    report = repository.assert_conservation()
    assert report.dividend_income_cents == 480

    # Pay date settles the corrected amount only.
    settle_receipt, snapshot = repository.settle_cash_in_lieu(
        CashInLieuRequest(
            action_id="div-fix",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="broker.test",
            effective_at=_moment(4),
            as_of=_moment(4) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert settle_receipt.amount_cents == 480
    assert snapshot.cash_receivable_cents == 0
    repository.assert_conservation()


def test_confirmation_after_settlement_books_delta_only(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)
    first, _ = repository.record_entitlement(
        entitlement_request(
            repository, action_id="div-late", numerator=1, denominator=2, step=2
        )
    )
    settle_receipt, snapshot = repository.settle_cash_in_lieu(
        CashInLieuRequest(
            action_id="div-late",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="broker.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    cash_after_settle = snapshot.available_cash_cents
    hashes_before = {
        event.economic_event_id: event.payload_content_hash
        for event in repository.events()
    }

    # The confirmation arrives after the cash moved: settled legs are
    # never rewritten; only the unresolved delta (600 - 500) is booked.
    corrected, snapshot = repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="div-late",
            revision=2,
            numerator=6,
            denominator=10,
            tier=SourceAuthorityTier.CONFIRMED,
            step=4,
        )
    )
    assert corrected.correction is True
    assert corrected.cash_amount_cents == 100
    assert snapshot.cash_receivable_cents == 100
    assert snapshot.available_cash_cents == cash_after_settle

    events = repository.events()
    hashes_after = {
        event.economic_event_id: event.payload_content_hash for event in events
    }
    # Neither the as-observed entitlement nor the settled cash leg changed:
    # every pre-confirmation event keeps its exact content hash.
    assert hashes_after.items() >= hashes_before.items()
    settle_event = next(
        event
        for event in events
        if event.economic_event_id == settle_receipt.event_id
    )
    assert settle_event.event_kind is EconomicEventKind.DIVIDEND_CASH_SETTLED

    report = repository.assert_conservation()
    assert report.dividend_income_cents == 600

    # The delta receivable settles through the same pay-date path.
    delta_receipt, snapshot = repository.settle_cash_in_lieu(
        CashInLieuRequest(
            action_id="div-late",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="broker.test",
            effective_at=_moment(5),
            as_of=_moment(5) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert delta_receipt.amount_cents == 100
    assert snapshot.cash_receivable_cents == 0
    repository.assert_conservation()


def test_confirmation_shortfall_after_settlement_fails_closed(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)
    repository.record_entitlement(
        entitlement_request(
            repository, action_id="div-short", numerator=1, denominator=2, step=2
        )
    )
    repository.settle_cash_in_lieu(
        CashInLieuRequest(
            action_id="div-short",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="broker.test",
            effective_at=_moment(3),
            as_of=_moment(3) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    # Confirmed less than already settled: a compensation obligation the
    # kernel cannot yet represent; preserve it fail-closed for Task 6.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_entitlement(
            entitlement_request(
                repository,
                action_id="div-short",
                revision=2,
                numerator=4,
                denominator=10,
                tier=SourceAuthorityTier.CONFIRMED,
                step=4,
            )
        )
    assert excinfo.value.code == "confirmation_delta_unsupported"
    repository.assert_conservation()


def test_identical_confirmation_upgrades_provenance_only(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)
    first, _ = repository.record_entitlement(
        entitlement_request(
            repository, action_id="div-confirm", numerator=1, denominator=2, step=2
        )
    )
    stream = repository.stream_version()
    capital = repository.capital_version()

    confirmed, snapshot = repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="div-confirm",
            revision=2,
            numerator=1,
            denominator=2,
            tier=SourceAuthorityTier.CONFIRMED,
            step=3,
        )
    )
    # No capital fact changed: the stream and capital version stay quiet.
    assert repository.stream_version() == stream
    assert repository.capital_version() == capital
    assert snapshot.cash_receivable_cents == 500
    record = repository.corporate_action_record("div-confirm", "lin-1", "lot-1")
    assert record.source_authority_tier is SourceAuthorityTier.CONFIRMED
    assert record.revision == 2
    # Idempotent retry converges identically.
    retry, _ = repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="div-confirm",
            revision=2,
            numerator=1,
            denominator=2,
            tier=SourceAuthorityTier.CONFIRMED,
            step=3,
        )
    )
    assert retry.event_id == confirmed.event_id
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Source-authority matrix and stable identities
# ---------------------------------------------------------------------------


def test_source_authority_matrix_rules(repository: CapitalRepository) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)
    repository.record_entitlement(
        entitlement_request(
            repository,
            action_id="div-matrix",
            numerator=1,
            denominator=2,
            tier=SourceAuthorityTier.CONFIRMED,
            step=2,
        )
    )

    # A confirmed fact cannot be downgraded by a later as-observed one.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_entitlement(
            entitlement_request(
                repository,
                action_id="div-matrix",
                revision=2,
                numerator=48,
                denominator=100,
                tier=SourceAuthorityTier.AS_OBSERVED,
                step=3,
            )
        )
    assert excinfo.value.code == "source_authority_downgrade"

    # Divergent content under the same revision identity conflicts.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_entitlement(
            entitlement_request(
                repository,
                action_id="div-matrix",
                revision=1,
                numerator=9,
                denominator=10,
                tier=SourceAuthorityTier.CONFIRMED,
                step=4,
            )
        )
    assert excinfo.value.code == "payload_conflict"

    # Revisions are monotonic: no gaps.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_entitlement(
            entitlement_request(
                repository,
                action_id="div-matrix",
                revision=3,
                numerator=48,
                denominator=100,
                tier=SourceAuthorityTier.CONFIRMED,
                step=5,
            )
        )
    assert excinfo.value.code == "revision_sequence_conflict"
    repository.assert_conservation()


def test_stable_fact_and_revision_identities(repository: CapitalRepository) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)

    first, _ = repository.record_entitlement(
        entitlement_request(repository, action_id="div-stable", step=2)
    )
    # Re-recording the same action with identical content converges on the
    # same canonical event identity.
    retry, _ = repository.record_entitlement(
        entitlement_request(repository, action_id="div-stable", step=2)
    )
    assert retry.event_id == first.event_id

    # The identity is derived deterministically from the fact coordinates.
    from src.screening.offensive.v3.storage.metadata import derive_event_id

    expected_key = entitlement_idempotency_key(
        "div-stable", "lin-1", "lot-1", revision=1
    )
    assert first.event_id == derive_event_id(expected_key)

    # Different actions never collide, even for the same lot.
    other, _ = repository.record_entitlement(
        entitlement_request(repository, action_id="div-other", step=3)
    )
    assert other.event_id != first.event_id
    # entry fill + div-stable + div-other: the converged retry added nothing.
    assert repository.stream_version() == 3
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Lifecycle continuity
# ---------------------------------------------------------------------------


def test_corporate_actions_continue_through_insolvency(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    # Spend the full capital on shares, then mark them to zero NAV.
    entry(
        repository,
        step=1,
        quantity=1_000,
        price_micros=100_000_000,
    )
    mark(repository, step=2, marks={SECURITY: 1})
    assert repository.lifecycle_state() is LifecycleState.INSOLVENT

    # Real corporate facts keep landing under insolvency: exits, corporate
    # actions, and reconciliation are never blocked by a risk halt.
    receipt, _ = repository.record_entitlement(
        entitlement_request(repository, action_id="div-insolvent", step=3)
    )
    assert receipt.cash_amount_cents == 3_250
    settle_receipt, snapshot = repository.settle_cash_in_lieu(
        CashInLieuRequest(
            action_id="div-insolvent",
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            tier=SourceAuthorityTier.CONFIRMED,
            source_authority="broker.test",
            effective_at=_moment(4),
            as_of=_moment(4) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert settle_receipt.amount_cents == 3_250
    assert snapshot.available_cash_cents == 3_250
    repository.assert_conservation()


def test_terminated_ledger_rejects_corporate_actions(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry(repository, step=1, quantity=1_000)
    # Full redemption to zero units terminates the ledger (Task 3 path).
    from src.screening.offensive.v3.capital.flows import (
        RedemptionPaymentRequest,
        RedemptionRequest,
        FlowSettleRequest,
    )

    mark(repository, step=2, marks={SECURITY: 10_000_000})
    repository.request_redemption(
        RedemptionRequest(
            request_id="red-all",
            unit_quanta=GENESIS_UNITS,
            source_authority="flows.test",
            as_of=_moment(3),
        )
    )
    # Liquidate first: full redemption refuses to erase units while the
    # economic obligation is still open.
    exit_(repository, step=4, execution_id="exec-exit-all", quantity=1_000)
    mark(repository, step=5, marks={})
    repository.settle_redemption(
        FlowSettleRequest(
            request_id="red-all",
            source_authority="flows.test",
            as_of=_moment(6),
            expected_flow_version=repository.flow_version(),
        )
    )
    repository.pay_redemption(
        RedemptionPaymentRequest(
            request_id="red-all",
            source_authority="flows.test",
            as_of=_moment(7),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert repository.lifecycle_state() is LifecycleState.TERMINATED

    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_entitlement(
            entitlement_request(repository, action_id="div-dead", step=7)
        )
    assert excinfo.value.code == "lifecycle_terminal"


# ---------------------------------------------------------------------------
# Property: conservation holds across generated corporate-action chains
# ---------------------------------------------------------------------------


def _property_repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(
        tmp_path / f"capital-{uuid.uuid4().hex}.sqlite3"
    )


@st.composite
def corporate_action_chains(draw) -> list[dict]:
    """Interleaved fill/valuation/corporate-action sequences.

    The model decides validity before each draw, so every generated chain
    is executable. Only exact-division ratios are offered, mirroring the
    kernel's fail-closed rounding policy.
    """

    ops: list[dict] = []
    lots: dict[str, dict] = {}
    cash = GENESIS_CASH_CENTS
    steps = draw(st.integers(min_value=3, max_value=9))

    for _ in range(steps):
        actions: list[tuple[str, dict]] = []
        if cash >= 100_000:
            actions.append(("entry", {}))
        live = {
            lot_id: lot
            for lot_id, lot in lots.items()
            if lot["qty"] > 0 and not lot["pending_shares"]
        }
        for lot_id, lot in sorted(live.items()):
            for num, den in ((1, 4), (1, 2), (1, 1), (3, 1), (2, 1)):
                if lot["qty"] * num % den == 0:
                    actions.append(
                        ("cash_dividend", {"lot_id": lot_id, "num": num, "den": den})
                    )
                    break
            for num, den in ((1, 2), (1, 5), (1, 1), (2, 1)):
                whole, rem_num, _ = split_entitlement(lot["qty"], num, den)
                if whole > 0:
                    actions.append(
                        (
                            "share_bonus",
                            {"lot_id": lot_id, "num": num, "den": den},
                        )
                    )
                    break
            if lot["state"] == "OPEN":
                for num, den in ((2, 1), (3, 1), (1, 2)):
                    if lot["qty"] * num % den == 0 and lot["qty"] * num // den > 0:
                        actions.append(
                            ("split", {"lot_id": lot_id, "num": num, "den": den})
                        )
                        break
                for num, den in ((1, 2), (1, 1), (2, 1)):
                    if lot["qty"] * num % den == 0 and lot["qty"] * num // den > 0:
                        actions.append(
                            (
                                "convert",
                                {"lot_id": lot_id, "num": num, "den": den},
                            )
                        )
                        break
                actions.append(("terminal_cash", {"lot_id": lot_id}))
        for lot_id, lot in sorted(lots.items()):
            if lot["pending_cash"]:
                actions.append(("settle_cash", {"lot_id": lot_id}))
            if lot["pending_shares"]:
                actions.append(("make_tradable", {"lot_id": lot_id}))
        if lots:
            actions.append(("valuation", {}))

        if not actions:
            break
        name, params = draw(st.sampled_from(actions))

        if name == "entry":
            lot_id = f"lot-{len(ops)}"
            quantity = draw(st.integers(min_value=10, max_value=200))
            price_micros = draw(st.integers(min_value=100_000, max_value=5_000_000))
            gross = fill_gross_cents(price_micros, quantity)
            if gross < 1 or gross > cash:
                continue
            cash -= gross
            lots[lot_id] = {
                "qty": quantity,
                "basis": gross,
                "security": f"sec-{lot_id}",
                "state": "OPEN",
                "pending_cash": [],
                "pending_shares": [],
            }
            ops.append(
                {
                    "op": "entry",
                    "lot_id": lot_id,
                    "price_micros": price_micros,
                    "quantity": quantity,
                    "gross": gross,
                }
            )
        elif name == "cash_dividend":
            lot = lots[params["lot_id"]]
            amount = lot["qty"] * params["num"] // params["den"]
            if amount < 1:
                continue
            lot["pending_cash"].append(amount)
            ops.append({"op": "cash_dividend", **params, "amount": amount})
        elif name == "share_bonus":
            lot = lots[params["lot_id"]]
            whole, rem_num, rem_den = split_entitlement(
                lot["qty"], params["num"], params["den"]
            )
            lot["pending_shares"].append(whole)
            ops.append(
                {
                    "op": "share_bonus",
                    **params,
                    "whole": whole,
                    "remainder": (rem_num, rem_den),
                }
            )
        elif name == "settle_cash":
            lot = lots[params["lot_id"]]
            # The kernel settles the newest pending entitlement of the lot.
            amount = lot["pending_cash"].pop()
            cash += amount
            ops.append({"op": "settle_cash", **params, "amount": amount})
        elif name == "make_tradable":
            lot = lots[params["lot_id"]]
            whole = lot["pending_shares"].pop()
            lot["qty"] += whole
            ops.append({"op": "make_tradable", **params, "whole": whole})
        elif name == "split":
            lot = lots[params["lot_id"]]
            lot["qty"] = lot["qty"] * params["num"] // params["den"]
            ops.append({"op": "split", **params})
        elif name == "convert":
            lot = lots[params["lot_id"]]
            new_qty = lot["qty"] * params["num"] // params["den"]
            lot["qty"] = new_qty
            # The replay names the successor after its 1-based step number
            # (len(ops) + 1 once this operation is appended).
            lot["security"] = f"succ-{params['lot_id']}-{len(ops) + 1}"
            ops.append({"op": "convert", **params, "new_qty": new_qty})
        elif name == "terminal_cash":
            lot = lots[params["lot_id"]]
            proceeds = draw(st.integers(min_value=1, max_value=5_000_000))
            cash += proceeds
            lot["state"] = "TERMINAL"
            lot["qty"] = 0
            ops.append({"op": "terminal_cash", **params, "proceeds": proceeds})
        elif name == "valuation":
            marks = {
                lot["security"]: draw(st.integers(min_value=1, max_value=20_000_000))
                for lot in lots.values()
                if lot["qty"] > 0 and lot["state"] != "TERMINAL"
            }
            ops.append({"op": "valuation", "marks": marks})

    return ops


def _replay_chain(repository: CapitalRepository, ops: list[dict]) -> None:
    step = 0
    for op in ops:
        step += 1
        kind = op["op"]
        if kind == "entry":
            entry(
                repository,
                step=step,
                execution_id=f"exec-{step}",
                security_id=f"sec-{op['lot_id']}",
                price_micros=op["price_micros"],
                quantity=op["quantity"],
                lineage=f"lin-{op['lot_id']}",
                lot=op["lot_id"],
            )
        elif kind == "cash_dividend":
            repository.record_entitlement(
                EntitlementRequest(
                    action_id=f"div-{step}",
                    position_lineage_id=f"lin-{op['lot_id']}",
                    economic_lot_id=op["lot_id"],
                    security_id=_security_of(repository, op["lot_id"]),
                    action_kind=CorporateActionKind.CASH_DIVIDEND,
                    entitlement=RationalQuantity(
                        numerator=op["num"], denominator=op["den"]
                    ),
                    tier=SourceAuthorityTier.AS_OBSERVED,
                    source_authority="vendor.test",
                    effective_at=_moment(step),
                    as_of=_moment(step) + timedelta(seconds=1),
                    expected_stream_version=repository.stream_version(),
                )
            )
            op["action_id"] = f"div-{step}"
        elif kind == "share_bonus":
            repository.record_entitlement(
                EntitlementRequest(
                    action_id=f"bonus-{step}",
                    position_lineage_id=f"lin-{op['lot_id']}",
                    economic_lot_id=op["lot_id"],
                    security_id=_security_of(repository, op["lot_id"]),
                    action_kind=CorporateActionKind.SHARE_ENTITLEMENT,
                    entitlement=RationalQuantity(
                        numerator=op["num"], denominator=op["den"]
                    ),
                    tier=SourceAuthorityTier.AS_OBSERVED,
                    source_authority="vendor.test",
                    effective_at=_moment(step),
                    as_of=_moment(step) + timedelta(seconds=1),
                    expected_stream_version=repository.stream_version(),
                )
            )
            op["action_id"] = f"bonus-{step}"
        elif kind == "settle_cash":
            action_id = _cash_action_of(repository, op["lot_id"])
            repository.settle_cash_in_lieu(
                CashInLieuRequest(
                    action_id=action_id,
                    position_lineage_id=f"lin-{op['lot_id']}",
                    economic_lot_id=op["lot_id"],
                    tier=SourceAuthorityTier.CONFIRMED,
                    source_authority="broker.test",
                    effective_at=_moment(step),
                    as_of=_moment(step) + timedelta(seconds=1),
                    expected_stream_version=repository.stream_version(),
                )
            )
        elif kind == "make_tradable":
            action_id = _share_action_of(repository, op["lot_id"])
            repository.make_shares_tradable(
                SharesTradableRequest(
                    action_id=action_id,
                    position_lineage_id=f"lin-{op['lot_id']}",
                    economic_lot_id=op["lot_id"],
                    tier=SourceAuthorityTier.CONFIRMED,
                    source_authority="exchange.test",
                    effective_at=_moment(step),
                    as_of=_moment(step) + timedelta(seconds=1),
                    expected_stream_version=repository.stream_version(),
                )
            )
        elif kind == "split":
            is_split = op["num"] > op["den"]
            repository.apply_split_merge(
                SplitMergeRequest(
                    action_id=f"split-{step}",
                    position_lineage_id=f"lin-{op['lot_id']}",
                    economic_lot_id=op["lot_id"],
                    security_id=_security_of(repository, op["lot_id"]),
                    action_kind=(
                        CorporateActionKind.SPLIT
                        if is_split
                        else CorporateActionKind.MERGE
                    ),
                    ratio=RationalQuantity(numerator=op["num"], denominator=op["den"]),
                    tier=SourceAuthorityTier.CONFIRMED,
                    source_authority="exchange.test",
                    effective_at=_moment(step),
                    as_of=_moment(step) + timedelta(seconds=1),
                    expected_stream_version=repository.stream_version(),
                )
            )
        elif kind == "convert":
            repository.convert_security(
                ConversionRequest(
                    action_id=f"merger-{step}",
                    position_lineage_id=f"lin-{op['lot_id']}",
                    economic_lot_id=op["lot_id"],
                    source_security_id=_security_of(repository, op["lot_id"]),
                    successor_security_id=f"succ-{op['lot_id']}-{step}",
                    ratio=RationalQuantity(numerator=op["num"], denominator=op["den"]),
                    destination=ConversionDestination.TRADABLE,
                    tier=SourceAuthorityTier.CONFIRMED,
                    source_authority="legal.test",
                    effective_at=_moment(step),
                    as_of=_moment(step) + timedelta(seconds=1),
                    expected_stream_version=repository.stream_version(),
                )
            )
        elif kind == "terminal_cash":
            repository.settle_terminal_cash(
                TerminalCashRequest(
                    action_id=f"delist-{step}",
                    position_lineage_id=f"lin-{op['lot_id']}",
                    economic_lot_id=op["lot_id"],
                    security_id=_security_of(repository, op["lot_id"]),
                    proceeds_cents=op["proceeds"],
                    tier=SourceAuthorityTier.CONFIRMED,
                    legal_evidence_reference=f"notice-{step}",
                    source_authority="broker.test",
                    effective_at=_moment(step),
                    as_of=_moment(step) + timedelta(seconds=1),
                    expected_stream_version=repository.stream_version(),
                )
            )
        elif kind == "valuation":
            mark(repository, step=step, marks=op["marks"])
        repository.assert_conservation()


def _security_of(repository: CapitalRepository, lot_id: str) -> str:
    import sqlalchemy as sa

    with repository.engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT security_id FROM positions WHERE economic_lot_id = :lot"),
            {"lot": lot_id},
        ).scalar()


def _cash_action_of(repository: CapitalRepository, lot_id: str) -> str:
    import sqlalchemy as sa

    with repository.engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT action_id FROM corporate_actions"
                " WHERE economic_lot_id = :lot AND action_kind = 'CASH_DIVIDEND'"
                " AND state = 'PENDING' ORDER BY rowid DESC LIMIT 1"
            ),
            {"lot": lot_id},
        ).scalar()


def _share_action_of(repository: CapitalRepository, lot_id: str) -> str:
    import sqlalchemy as sa

    with repository.engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT action_id FROM corporate_actions"
                " WHERE economic_lot_id = :lot"
                " AND state = 'PENDING'"
                " AND receivable_id IN ("
                "   SELECT receivable_id FROM receivables"
                "   WHERE receivable_kind = 'SHARE' AND settled = 0"
                " )"
                " ORDER BY rowid DESC LIMIT 1"
            ),
            {"lot": lot_id},
        ).scalar()


@settings(
    deadline=None,
    max_examples=25,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(data=st.data())
def test_property_corporate_action_chains_conserve(data, tmp_path: Path) -> None:
    ops = data.draw(corporate_action_chains())
    repository = _property_repository(tmp_path)
    genesis(repository)
    _replay_chain(repository, ops)
    repository.assert_conservation()
