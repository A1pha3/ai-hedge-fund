"""Ledger-only exit-obligation derivation: re-enable gate clause ⑤.

The withdrawal migration
(``docs/superpowers/migrations/2026-08-13-shadow-capital-mutation-withdrawal.md``)
clause 5 requires "independent exit liveness, including crash recovery and
correction/bust reopening, without relying on entry authority". These tests
pin the derivation primitive against real SQLite ledgers: ledger-only
identity, the single-implementation schedule slice, typed fail-closed
shapes, advisory cross-check semantics, bust-reopen inheritance, and the
zero-write read discipline.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from src.screening.offensive.v3.capital.exit_liveness import (
    EXIT_LIMIT_PRICE_CENTS,
    ExitLivenessError,
    LineExpectation,
    cross_check_exit_identity,
    derive_exit_obligations,
    repository_exit_view,
)
from src.screening.offensive.v3.capital.execution_revisions import (
    ExecutionRevisionRequest,
)
from src.screening.offensive.v3.capital.fills import (
    FillAttribution,
    FillRevisionRequest,
)
from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalRepository,
)
from src.screening.offensive.v3.contracts import (
    CashEconomicEventLeg,
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
    ExecutionMode,
    ExecutionRevisionKind,
    ExecutionSide,
    PositionState,
)
from src.screening.offensive.v3.evidence.trading_schedule import (
    derive_trading_schedule,
)

T0 = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
ENTRY_SESSION = date(2026, 9, 9)
ENVIRONMENT_FINGERPRINT = "ab" * 32

# Weekday calendar around the entry session (2026-09-12/13 and 09-19/20 are
# weekends): signal 09-08 → following 09-09..09-22, exit = 2026-09-22.
CALENDAR = tuple(
    date(2026, 9, d)
    for d in (8, 9, 10, 11, 14, 15, 16, 17, 18, 21, 22, 23, 24, 25)
)


def _at(session: date) -> datetime:
    return datetime(session.year, session.month, session.day, 7, 0, tzinfo=timezone.utc)


def binding() -> AccountBinding:
    return AccountBinding(
        portfolio_id="pf-exit-live",
        mode=ExecutionMode.BROKER_CONFIRMED,
        broker_account_id="acct-exit-live",
        base_currency="CNY",
        environment_fingerprint=ENVIRONMENT_FINGERPRINT,
    )


ATTRIBUTION = FillAttribution(
    producer_namespace="btst",
    research_program_id="prog-exit-live",
    economic_lineage_id="eline-exit-live",
    stage_id="stage-exit-live",
)


@pytest.fixture()
def repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "exit-liveness.sqlite3")


def deposit(repository: CapitalRepository, cents: int, sequence: int) -> None:
    amount = Decimal(cents) / 100
    receivable_id = f"rcv-{sequence}"
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"declare-{sequence}",
            account_binding=binding(),
            expected_stream_version=repository.stream_version(),
            as_of=T0 + timedelta(minutes=sequence),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
                effective_at=T0 + timedelta(minutes=sequence),
                source_authority="test.seed",
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"declare-{sequence}-r",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id="000001.SZ",
                        cash_amount=amount,
                    ),
                ),
            ),
        )
    )
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"settle-{sequence}",
            account_binding=binding(),
            expected_stream_version=repository.stream_version(),
            as_of=T0 + timedelta(minutes=sequence, seconds=30),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_CASH_SETTLED,
                effective_at=T0 + timedelta(minutes=sequence, seconds=30),
                source_authority="test.seed",
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"settle-{sequence}-r",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id="000001.SZ",
                        cash_amount=amount,
                    ),
                    CashEconomicEventLeg(
                        leg_id=f"settle-{sequence}-c",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH,
                        cash_amount=amount,
                    ),
                ),
            ),
        )
    )


def fill_request(
    repository: CapitalRepository,
    execution_id: str,
    side: ExecutionSide,
    *,
    security_id: str = "600000.SH",
    quantity: int = 300,
    session: date = ENTRY_SESSION,
    price_micros: int = 5_500_000,
    lineage: str = "shadow:line-a",
    lot: str = "lot:line-a",
) -> FillRevisionRequest:
    return FillRevisionRequest(
        execution_id=execution_id,
        revision=1,
        order_id=f"ord-{execution_id}",
        side=side,
        security_id=security_id,
        price_micros=price_micros,
        quantity=quantity,
        position_lineage_id=lineage,
        economic_lot_id=lot,
        attribution=ATTRIBUTION,
        reserve_source_id=None,
        source_authority="broker.test",
        effective_at=_at(session),
        as_of=_at(session) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
    )


def entry_fill(repository: CapitalRepository, execution_id: str, **kwargs) -> None:
    repository.record_fill_revision(
        fill_request(repository, execution_id, ExecutionSide.ENTRY, **kwargs)
    )


def exit_fill(repository: CapitalRepository, execution_id: str, **kwargs) -> None:
    repository.record_fill_revision(
        fill_request(
            repository,
            execution_id,
            ExecutionSide.EXIT,
            session=date(2026, 9, 22),
            price_micros=6_000_000,
            **kwargs,
        )
    )


def bust_exit_fill(repository: CapitalRepository, execution_id: str, **kwargs) -> None:
    session = date(2026, 9, 23)
    repository.record_execution_revision(
        ExecutionRevisionRequest(
            execution_id=execution_id,
            revision=2,
            revision_kind=ExecutionRevisionKind.BUSTED,
            order_id=f"ord-{execution_id}",
            side=ExecutionSide.EXIT,
            security_id=kwargs.get("security_id", "600000.SH"),
            position_lineage_id=kwargs.get("lineage", "shadow:line-a"),
            economic_lot_id=kwargs.get("lot", "lot:line-a"),
            superseded_quantity=kwargs.get("quantity", 300),
            source_authority="broker.test",
            effective_at=_at(session),
            as_of=_at(session) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )


def official_slice_factory(calendar=CALENDAR):
    """Bind the single schedule implementation as the injected slice source.

    Official rule encoded here (not in the primitive): the signal session is
    the calendar session immediately before the entry settlement session.
    """

    def factory(entry_session: date):
        signal = max(d for d in calendar if d < entry_session)
        return derive_trading_schedule(
            signal_session=signal,
            calendar_dates=calendar,
            available_at=T0,
        )

    return factory


def _frozen_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row_counts(repository: CapitalRepository) -> dict[str, int]:
    with repository.engine.connect() as conn:
        return {
            table: int(
                conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            )
            for table in (
                "economic_events",
                "positions",
                "nav_observations",
                "economic_event_legs",
            )
        }


def _seeded_repository(repository: CapitalRepository) -> None:
    deposit(repository, 10_000_000, 1)
    entry_fill(repository, "exec-e")


# -- A1: ledger-only derivation, deterministic across fresh reads --------------


def test_derivation_is_ledger_only_and_deterministic(repository) -> None:
    _seeded_repository(repository)

    first = derive_exit_obligations(
        repository_exit_view(repository), official_slice_factory()
    )
    second = derive_exit_obligations(
        repository_exit_view(repository), official_slice_factory()
    )
    assert first == second
    assert len(first) == 1
    obligation = first[0]
    assert obligation.security_id == "600000.SH"
    assert obligation.position_lineage_id == "shadow:line-a"
    assert obligation.economic_lot_id == "lot:line-a"
    assert obligation.quantity_units == 300
    assert obligation.entry_settlement_session == ENTRY_SESSION
    assert obligation.signal_session == date(2026, 9, 8)
    assert obligation.target_exit_session == date(2026, 9, 22)
    assert obligation.exit_limit_price_cents == EXIT_LIMIT_PRICE_CENTS


def test_derivation_covers_each_open_lot(repository) -> None:
    deposit(repository, 10_000_000, 1)
    entry_fill(repository, "exec-a", lineage="shadow:line-a", lot="lot:line-a")
    entry_fill(
        repository,
        "exec-b",
        security_id="000002.SZ",
        session=date(2026, 9, 10),
        lineage="shadow:line-b",
        lot="lot:line-b",
    )
    obligations = derive_exit_obligations(
        repository_exit_view(repository), official_slice_factory()
    )
    assert [(o.security_id, o.entry_settlement_session) for o in obligations] == [
        ("000002.SZ", date(2026, 9, 10)),
        ("600000.SH", ENTRY_SESSION),
    ]
    assert obligations[0].target_exit_session == date(2026, 9, 23)
    assert obligations[1].target_exit_session == date(2026, 9, 22)


def test_no_open_positions_yields_no_obligations(repository) -> None:
    assert (
        derive_exit_obligations(
            repository_exit_view(repository), official_slice_factory()
        )
        == ()
    )


# -- A2: schedule slice validation and opening-event fail-closed shapes -------


def test_slice_entry_session_mismatch_is_typed(repository) -> None:
    _seeded_repository(repository)

    def wrong_slice(signal_session: date):
        slice_ = official_slice_factory()(signal_session)
        return SimpleNamespace(
            signal_session=slice_.signal_session,
            following_sessions=slice_.following_sessions[1:] + (date(2026, 9, 25),),
        )

    with pytest.raises(ExitLivenessError) as excinfo:
        derive_exit_obligations(repository_exit_view(repository), wrong_slice)
    assert excinfo.value.code == "exit_obligation_entry_session_mismatch"


def test_slice_shape_is_validated(repository) -> None:
    _seeded_repository(repository)
    base = official_slice_factory()(ENTRY_SESSION)
    short = SimpleNamespace(
        signal_session=base.signal_session,
        following_sessions=base.following_sessions[:9],
    )
    with pytest.raises(ExitLivenessError) as excinfo:
        derive_exit_obligations(repository_exit_view(repository), lambda _: short)
    assert excinfo.value.code == "exit_obligation_schedule_slice_invalid"

    unordered = SimpleNamespace(
        signal_session=base.signal_session,
        following_sessions=tuple(reversed(base.following_sessions)),
    )
    with pytest.raises(ExitLivenessError) as excinfo:
        derive_exit_obligations(repository_exit_view(repository), lambda _: unordered)
    assert excinfo.value.code == "exit_obligation_schedule_slice_invalid"


def test_missing_schedule_slice_is_typed(repository) -> None:
    _seeded_repository(repository)
    with pytest.raises(ExitLivenessError) as excinfo:
        derive_exit_obligations(repository_exit_view(repository), {})
    assert excinfo.value.code == "exit_obligation_schedule_unavailable"


_UNSET = object()


class _FilteringView:
    """Real quiet reads with one overridable opening-event answer."""

    def __init__(self, repository) -> None:
        self._view = repository_exit_view(repository)
        self.opening_override = _UNSET

    def open_position_rows(self):
        return self._view.open_position_rows()

    def opening_event_for(self, event_id):
        if self.opening_override is not _UNSET:
            return self.opening_override
        return self._view.opening_event_for(event_id)


def test_opening_event_shapes_fail_closed(repository) -> None:
    _seeded_repository(repository)
    rows = repository_exit_view(repository).open_position_rows()
    opened_by = str(rows[0].opened_by_event_id)

    def with_override(answer):
        view = _FilteringView(repository)
        view.opening_override = answer
        return view

    with pytest.raises(ExitLivenessError) as excinfo:
        derive_exit_obligations(with_override(None), official_slice_factory())
    assert excinfo.value.code == "exit_obligation_opening_event_missing"

    with pytest.raises(ExitLivenessError) as excinfo:
        derive_exit_obligations(
            with_override((opened_by, "FEE_CHARGED", "2026-09-09T07:00:00Z")),
            official_slice_factory(),
        )
    assert excinfo.value.code == "exit_obligation_opening_event_invalid"

    with pytest.raises(ExitLivenessError) as excinfo:
        derive_exit_obligations(
            with_override((opened_by, "TRADE_EXECUTED", "not-a-timestamp")),
            official_slice_factory(),
        )
    assert excinfo.value.code == "exit_obligation_opening_event_invalid"

    with pytest.raises(ExitLivenessError) as excinfo:
        derive_exit_obligations(
            with_override((opened_by, "TRADE_EXECUTED", "2026-09-09T07:00:00")),
            official_slice_factory(),
        )
    assert excinfo.value.code == "exit_obligation_opening_event_invalid"


def test_non_positive_quantity_fails_closed(repository) -> None:
    _seeded_repository(repository)
    real_view = repository_exit_view(repository)
    row = real_view.open_position_rows()[0]
    broken = SimpleNamespace(
        position_lineage_id=row.position_lineage_id,
        economic_lot_id=row.economic_lot_id,
        security_id=row.security_id,
        state=row.state,
        settled_quantity_units=0,
        opened_by_event_id=row.opened_by_event_id,
    )

    class _View:
        def open_position_rows(self):
            return (broken,)

        def opening_event_for(self, event_id):
            return real_view.opening_event_for(event_id)

    with pytest.raises(ExitLivenessError) as excinfo:
        derive_exit_obligations(_View(), official_slice_factory())
    assert excinfo.value.code == "exit_obligation_quantity_invalid"


# -- A3: advisory cross-check against committed line identities ----------------


def _expectation(obligation, **changes):
    fields = obligation.model_dump()
    fields.update(changes)
    return LineExpectation(
        economic_lot_id=fields["economic_lot_id"],
        security_id=fields["security_id"],
        quantity_units=fields["quantity_units"],
        target_exit_session=fields["target_exit_session"],
        exit_limit_price_cents=fields["exit_limit_price_cents"],
    )


def test_cross_check_skipped_without_expectations(repository) -> None:
    _seeded_repository(repository)
    obligations = derive_exit_obligations(
        repository_exit_view(repository), official_slice_factory()
    )
    assert cross_check_exit_identity(obligations, None) is None


def test_cross_check_matching_expectation_converges(repository) -> None:
    _seeded_repository(repository)
    obligations = derive_exit_obligations(
        repository_exit_view(repository), official_slice_factory()
    )
    expectations = {obligations[0].position_lineage_id: _expectation(obligations[0])}
    # Extra expectations without open lots (closed lots, no-fill lines) are
    # normal and never a breach.
    expectations["shadow:closed-line"] = _expectation(obligations[0])
    cross_check_exit_identity(obligations, expectations)


def test_cross_check_divergence_is_typed_per_field(repository) -> None:
    _seeded_repository(repository)
    obligations = derive_exit_obligations(
        repository_exit_view(repository), official_slice_factory()
    )
    obligation = obligations[0]
    mismatched = _expectation(obligation, quantity_units=299)
    with pytest.raises(ExitLivenessError) as excinfo:
        cross_check_exit_identity(
            obligations, {obligation.position_lineage_id: mismatched}
        )
    assert excinfo.value.code == "exit_obligation_identity_breach"
    assert list(excinfo.value.details["divergences"]) == ["quantity_units"]

    wrong_exit = _expectation(obligation, target_exit_session=date(2026, 9, 23))
    with pytest.raises(ExitLivenessError) as excinfo:
        cross_check_exit_identity(
            obligations, {obligation.position_lineage_id: wrong_exit}
        )
    assert list(excinfo.value.details["divergences"]) == ["target_exit_session"]

    wrong_limit = _expectation(obligation, exit_limit_price_cents=2)
    with pytest.raises(ExitLivenessError) as excinfo:
        cross_check_exit_identity(
            obligations, {obligation.position_lineage_id: wrong_limit}
        )
    assert list(excinfo.value.details["divergences"]) == ["exit_limit_price_cents"]


def test_cross_check_missing_expectation_is_typed(repository) -> None:
    _seeded_repository(repository)
    obligations = derive_exit_obligations(
        repository_exit_view(repository), official_slice_factory()
    )
    with pytest.raises(ExitLivenessError) as excinfo:
        cross_check_exit_identity(obligations, {})
    assert excinfo.value.code == "exit_obligation_expectation_missing"


# -- A4: correction/bust reopening inherits from ledger truth ------------------


def test_exit_bust_reopen_reenters_obligations(repository) -> None:
    deposit(repository, 10_000_000, 1)
    entry_fill(repository, "exec-e")
    exit_fill(repository, "exec-x")
    view = repository_exit_view(repository)
    assert derive_exit_obligations(view, official_slice_factory()) == ()

    bust_exit_fill(repository, "exec-x")
    row = view.open_position_rows()[0]
    assert row.state == PositionState.EXIT_PENDING.value

    obligations = derive_exit_obligations(view, official_slice_factory())
    assert len(obligations) == 1
    assert obligations[0].quantity_units == 300
    assert obligations[0].opening_event_id == str(row.opened_by_event_id)


# -- A5: zero-write read discipline -------------------------------------------


def test_derivation_leaves_ledger_byte_identical(repository) -> None:
    _seeded_repository(repository)
    db_path = Path(repository.engine.url.database)
    before_sha = _frozen_sha(db_path)
    before_counts = _row_counts(repository)

    derive_exit_obligations(repository_exit_view(repository), official_slice_factory())

    assert _frozen_sha(db_path) == before_sha
    assert _row_counts(repository) == before_counts


# -- A6: zero production disturbance ------------------------------------------


def test_exit_limit_constant_matches_orchestration_spelling() -> None:
    from src.screening.offensive.v3.orchestration.session_driver import (
        UNCONDITIONAL_EXIT_LIMIT_CENTS,
    )

    assert EXIT_LIMIT_PRICE_CENTS == UNCONDITIONAL_EXIT_LIMIT_CENTS


def test_derived_sessions_match_frozen_schedule_semantics(repository) -> None:
    """The injected-slice contract reproduces the frozen T+10 semantics on
    the single schedule implementation (zero formula fork)."""

    _seeded_repository(repository)
    obligations = derive_exit_obligations(
        repository_exit_view(repository), official_slice_factory()
    )
    schedule = derive_trading_schedule(
        signal_session=date(2026, 9, 8),
        calendar_dates=CALENDAR,
        available_at=T0,
    )
    assert obligations[0].target_exit_session == schedule.following_sessions[-1]
    assert obligations[0].entry_settlement_session == schedule.following_sessions[0]
