"""Plan 08 Task 7 RED: causal capital source bindings + atomic batch reserves.

Provenance: every decision-derived proxy reserve/fill/fee/correction must
carry ``mode=DAILY_BAR_PROXY`` and ``artifact_kind=SHADOW_DECISION`` with
the exact decision id and content hash; every valuation/restatement must
bind its ``SnapshotEvidence`` (``artifact_kind=SNAPSHOT``). The binding is
persisted with the fact (reserves keep ``source_binding_json``, economic
events keep it inside their canonical payload JSON).

Batch: ``reserve_entries_atomic`` books multiple lines in ONE capital
transaction; insufficient cash or one conflicting source rolls back ALL
lines and versions; an exact batch replay is quiet; input order
canonicalizes by ``source_id``.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

from src.screening.offensive.v3.capital.fills import FillRevisionRequest
from src.screening.offensive.v3.capital.provenance import CapitalSourceBinding
from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalConflict,
    CapitalRepository,
)
from src.screening.offensive.v3.capital.reserves import (
    ReserveEntryRequest,
)
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    ExecutionSide,
)
from src.screening.offensive.v3.contracts.trust import ArtifactKind

T0 = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
ENVIRONMENT_FINGERPRINT = "ab" * 32

DECISION_ID = "shadow-2026-08-03-champion"
DECISION_HASH = "cd" * 32
EVIDENCE_ID = "evidence-snapshot-2026-08-03-001"
EVIDENCE_HASH = "ef" * 32


def _moment(step: int) -> datetime:
    return T0 + timedelta(minutes=step)


def shadow_binding() -> CapitalSourceBinding:
    return CapitalSourceBinding(
        mode=ExecutionMode.DAILY_BAR_PROXY,
        artifact_kind=ArtifactKind.SHADOW_DECISION,
        artifact_id=DECISION_ID,
        artifact_hash=DECISION_HASH,
    )


def snapshot_binding() -> CapitalSourceBinding:
    return CapitalSourceBinding(
        mode=ExecutionMode.DAILY_BAR_PROXY,
        artifact_kind=ArtifactKind.SNAPSHOT,
        artifact_id=EVIDENCE_ID,
        artifact_hash=EVIDENCE_HASH,
    )


def proxy_binding() -> AccountBinding:
    return AccountBinding(
        portfolio_id="pf-shadow",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        broker_account_id=None,
        base_currency="CNY",
        environment_fingerprint=ENVIRONMENT_FINGERPRINT,
    )


def deposit(
    repository: CapitalRepository, cents: int, sequence: int
) -> None:
    """Seed cash for a proxy ledger through a plain append."""

    from decimal import Decimal

    from src.screening.offensive.v3.capital.repository import (
        CapitalCommand,
        CapitalCommandPayload,
    )
    from src.screening.offensive.v3.contracts import (
        CashEconomicEventLeg,
        CashReceivableEconomicEventLeg,
        EconomicAssetKind,
        EconomicEventKind,
        EconomicLegDirection,
    )

    receivable_id = f"rcv-{sequence}"
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"declare-{sequence}",
            account_binding=proxy_binding(),
            expected_stream_version=repository.stream_version(),
            as_of=_moment(sequence),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
                effective_at=_moment(sequence),
                source_authority="test.seed",
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"declare-{sequence}-r",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id="000001.SZ",
                        cash_amount=Decimal(cents) / 100,
                    ),
                ),
            ),
        )
    )
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"settle-{sequence}",
            account_binding=proxy_binding(),
            expected_stream_version=repository.stream_version(),
            as_of=_moment(sequence) + timedelta(seconds=30),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_CASH_SETTLED,
                effective_at=_moment(sequence) + timedelta(seconds=30),
                source_authority="test.seed",
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"settle-{sequence}-r",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id="000001.SZ",
                        cash_amount=Decimal(cents) / 100,
                    ),
                    CashEconomicEventLeg(
                        leg_id=f"settle-{sequence}-c",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH,
                        cash_amount=Decimal(cents) / 100,
                    ),
                ),
            ),
        )
    )


@pytest.fixture()
def repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


def _genesis(repository: CapitalRepository) -> None:
    """Seed NAV through the Task 3 genesis flow (close valuation requires it)."""

    from src.screening.offensive.v3.capital.flows import GenesisRequest

    repository.initialize_genesis(
        GenesisRequest(
            idempotency_key="genesis-1",
            account_binding=proxy_binding(),
            unit_quanta=10_000,
            unit_price_numerator=100,
            unit_price_denominator=1,
            source_authority="shadow.proxy",
            authorization_reference="gov-genesis-1",
            effective_at=_moment(1),
            as_of=_moment(1),
        )
    )


def _reserve(
    source_id: str,
    cents: int,
    *,
    binding: CapitalSourceBinding | None = shadow_binding(),
    step: int = 1,
    repository: CapitalRepository | None = None,
) -> ReserveEntryRequest:
    return ReserveEntryRequest(
        source_id=source_id,
        research_program_id="trial-1",
        economic_lineage_id="line-1",
        stage_id="stage-1",
        reserved_entry_gross_cents=cents,
        expected_stream_version=repository.stream_version(),
        as_of=_moment(step),
        source_binding=binding,
    )


def _fill(
    execution_id: str,
    *,
    price_micros: int = 10_000_000,
    quantity: int = 100,
    reserve_source_id: str | None = None,
    binding: CapitalSourceBinding | None = shadow_binding(),
    step: int = 1,
    repository: CapitalRepository | None = None,
) -> FillRevisionRequest:
    from src.screening.offensive.v3.capital.fills import FillAttribution

    return FillRevisionRequest(
        execution_id=execution_id,
        revision=1,
        order_id=f"ord-{execution_id}",
        side=ExecutionSide.ENTRY,
        security_id="600000.SH",
        price_micros=price_micros,
        quantity=quantity,
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        attribution=FillAttribution(
            producer_namespace="trial-1",
            research_program_id="trial-1",
            economic_lineage_id="line-1",
            stage_id="stage-1",
        ),
        reserve_source_id=reserve_source_id,
        source_authority="shadow.proxy",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
        source_binding=binding,
    )


def _reserve_row(repository: CapitalRepository, source_id: str) -> tuple:
    with repository.engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT source_binding_json, reserved_entry_gross_cents"
                " FROM reserves WHERE source_id = :source_id"
            ),
            {"source_id": source_id},
        ).one()
    return (row[0], int(row[1]))


# ---------------------------------------------------------------------------
# Step 1: provenance persistence and rejection
# ---------------------------------------------------------------------------


def test_shadow_fill_persists_decision_source_binding(repository) -> None:
    deposit(repository, 1_000_000, 1)
    receipt, _ = repository.record_fill_revision(
        _fill("exec-1", repository=repository)
    )
    event = next(
        e
        for e in repository.events()
        if e.economic_event_id == receipt.event_id
    )
    assert event.payload_content_hash
    payload = next(
        e
        for e in repository.events()
        if e.economic_event_id == receipt.event_id
    ).payload_content_hash
    # The plan's exact assertion surface: the persisted payload carries the
    # exact binding the request carried.
    from src.screening.offensive.v3.capital.repository import (
        CapitalCommandPayload,
    )

    stored = CapitalCommandPayload.model_validate_json(
        _payload_json(repository, receipt.event_id)
    )
    assert stored.source_binding == CapitalSourceBinding(
        mode=ExecutionMode.DAILY_BAR_PROXY,
        artifact_kind=ArtifactKind.SHADOW_DECISION,
        artifact_id=DECISION_ID,
        artifact_hash=DECISION_HASH,
    )
    assert payload == stored.content_hash()


def test_shadow_reserve_persists_source_binding(repository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(
        _reserve("src-1", 400_000, repository=repository)
    )
    binding_json, cents = _reserve_row(repository, "src-1")
    assert cents == 400_000
    assert CapitalSourceBinding.model_validate_json(binding_json) == (
        shadow_binding()
    )


def test_shadow_fee_persists_decision_source_binding(repository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(_fill("exec-1", repository=repository))
    from src.screening.offensive.v3.capital.fees import FeePolicy
    from src.screening.offensive.v3.capital.fills import FeeRevisionRequest

    fee_request = FeeRevisionRequest(
        fill_execution_id="exec-1",
        revision=1,
        fee_policy=FeePolicy(
            fee_policy_version="fee-shadow-v1",
            commission_rate_ppm=3_000,
            min_commission_cents=500,
            stamp_tax_rate_ppm=1_000,
            transfer_fee_rate_ppm=20,
        ),
        source_authority="shadow.proxy",
        effective_at=_moment(2),
        as_of=_moment(2) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
        source_binding=shadow_binding(),
    )
    receipt, _ = repository.record_fee_revision(fee_request)
    stored = _stored_payload(repository, receipt.event_id)
    assert stored.source_binding == shadow_binding()


def test_shadow_correction_persists_decision_source_binding(repository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(_fill("exec-1", repository=repository))
    from src.screening.offensive.v3.capital.execution_revisions import (
        ExecutionRevisionRequest,
    )
    from src.screening.offensive.v3.contracts import ExecutionRevisionKind

    receipt, _ = repository.record_execution_correction(
        ExecutionRevisionRequest(
            execution_id="exec-1",
            revision=2,
            revision_kind=ExecutionRevisionKind.CORRECTED,
            order_id="ord-exec-1",
            side=ExecutionSide.ENTRY,
            security_id="600000.SH",
            corrected_price_micros=9_000_000,
            corrected_quantity=90,
            source_authority="shadow.proxy",
            effective_at=_moment(2),
            as_of=_moment(2) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
            source_binding=shadow_binding(),
        )
    )
    stored = _stored_payload(repository, receipt.event_id)
    assert stored.source_binding == shadow_binding()


def test_valuation_binds_snapshot_evidence(repository) -> None:
    _genesis(repository)
    repository.record_fill_revision(_fill("exec-1", repository=repository))
    from src.screening.offensive.v3.capital.nav import (
        ValuationMarkInput,
        ValuationRequest,
    )

    receipt, _ = repository.close_valuation(
        ValuationRequest(
            idempotency_key="valuation-1",
            source_authority="shadow.proxy",
            effective_at=_moment(2),
            as_of=_moment(2),
            expected_stream_version=repository.stream_version(),
            marks=(
                ValuationMarkInput(
                    security_id="600000.SH", price_micros=100_000_000
                ),
            ),
            source_binding=snapshot_binding(),
        )
    )
    stored = _stored_payload(repository, receipt.event_id)
    assert stored.source_binding == snapshot_binding()


def test_restatement_binds_snapshot_evidence(repository) -> None:
    _genesis(repository)
    repository.record_fill_revision(_fill("exec-1", repository=repository))
    from src.screening.offensive.v3.capital.nav import (
        RestatementRequest,
        ValuationMarkInput,
        ValuationRequest,
    )

    original, _ = repository.close_valuation(
        ValuationRequest(
            idempotency_key="valuation-1",
            source_authority="shadow.proxy",
            effective_at=_moment(2),
            as_of=_moment(2),
            expected_stream_version=repository.stream_version(),
            marks=(
                ValuationMarkInput(
                    security_id="600000.SH", price_micros=100_000_000
                ),
            ),
            source_binding=snapshot_binding(),
        )
    )
    restated, _ = repository.restate_valuation(
        RestatementRequest(
            idempotency_key="restatement-1",
            restates_event_id=original.event_id,
            source_authority="shadow.proxy",
            effective_at=_moment(3),
            as_of=_moment(3),
            expected_stream_version=repository.stream_version(),
            marks=(
                ValuationMarkInput(
                    security_id="600000.SH", price_micros=90_000_000
                ),
            ),
            source_binding=snapshot_binding(),
        )
    )
    stored = _stored_payload(repository, restated.event_id)
    assert stored.source_binding == snapshot_binding()


def test_shadow_binding_rejected_on_wrong_ledger_mode() -> None:
    with pytest.raises(ValueError, match="DAILY_BAR_PROXY"):
        CapitalSourceBinding(
            mode=ExecutionMode.BROKER_CONFIRMED,
            artifact_kind=ArtifactKind.SHADOW_DECISION,
            artifact_id=DECISION_ID,
            artifact_hash=DECISION_HASH,
        )


def test_non_proxy_artifact_rejected_on_proxy_ledger() -> None:
    with pytest.raises(ValueError, match="proxy ledger"):
        CapitalSourceBinding(
            mode=ExecutionMode.DAILY_BAR_PROXY,
            artifact_kind=ArtifactKind.PLAN,
            artifact_id="plan-1",
            artifact_hash=DECISION_HASH,
        )


def test_fill_wrong_artifact_hash_conflicts_and_moves_nothing(
    repository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(_fill("exec-1", repository=repository))
    stream = repository.stream_version()
    capital_version = repository.capital_version()
    with pytest.raises(CapitalConflict, match="payload_conflict"):
        repository.record_fill_revision(
            _fill(
                "exec-1",
                binding=CapitalSourceBinding(
                    mode=ExecutionMode.DAILY_BAR_PROXY,
                    artifact_kind=ArtifactKind.SHADOW_DECISION,
                    artifact_id=DECISION_ID,
                    artifact_hash="0" * 64,
                ),
                repository=repository,
            )
        )
    assert repository.stream_version() == stream
    assert repository.capital_version() == capital_version


def test_reserve_conflicting_source_binding_conflicts(repository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(
        _reserve("src-1", 400_000, repository=repository)
    )
    capital_version = repository.capital_version()
    with pytest.raises(CapitalConflict, match="reserve_source_conflict"):
        repository.reserve_entry(
            _reserve(
                "src-1",
                400_000,
                binding=CapitalSourceBinding(
                    mode=ExecutionMode.DAILY_BAR_PROXY,
                    artifact_kind=ArtifactKind.SHADOW_DECISION,
                    artifact_id="shadow-other",
                    artifact_hash=DECISION_HASH,
                ),
                repository=repository,
            )
        )
    assert repository.capital_version() == capital_version


def test_reserve_without_binding_still_quiet_for_legacy_callers(
    repository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(_reserve("src-1", 400_000, binding=None, repository=repository))
    binding_json, _ = _reserve_row(repository, "src-1")
    assert binding_json is None


# ---------------------------------------------------------------------------
# Step 2: atomic multi-line reserve batch
# ---------------------------------------------------------------------------


def test_reserve_entries_atomic_books_all_lines_in_one_transaction(
    repository,
) -> None:
    deposit(repository, 1_000_000, 1)
    snapshot = repository.reserve_entries_atomic(
        (
            _reserve("src-1", 100_000, step=2, repository=repository),
            _reserve("src-2", 200_000, step=2, repository=repository),
            _reserve("src-3", 300_000, step=2, repository=repository),
        )
    )
    assert snapshot.available_cash_cents == 400_000
    assert snapshot.restricted_cash_cents == 600_000
    assert len(snapshot.entry_reserves) == 3
    assert {r.source_id for r in snapshot.entry_reserves} == {
        "src-1",
        "src-2",
        "src-3",
    }
    assert repository.stream_version() == 2  # seed deposits only
    # Seed deposits bump the projection twice; the batch bumps it once per
    # committed line (the batch is one transaction, not one version).
    assert snapshot.capital_version == 5
    repository.assert_conservation()


def test_batch_insufficient_cash_rolls_back_all_lines(repository) -> None:
    deposit(repository, 500_000, 1)
    capital_version = repository.capital_version()
    with pytest.raises(CapitalConflict, match="insufficient_available_cash"):
        repository.reserve_entries_atomic(
            (
                _reserve("src-1", 300_000, step=2, repository=repository),
                _reserve("src-2", 300_000, step=2, repository=repository),
            )
        )
    snapshot = repository.capital_risk_snapshot(_moment(3))
    assert snapshot.available_cash_cents == 500_000
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.entry_reserves == ()
    assert repository.capital_version() == capital_version
    repository.assert_conservation()


def test_batch_one_conflicting_source_rolls_back_all_lines(repository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(
        _reserve("src-existing", 100_000, step=1, repository=repository)
    )
    capital_version = repository.capital_version()
    with pytest.raises(CapitalConflict, match="reserve_source_conflict"):
        repository.reserve_entries_atomic(
            (
                _reserve("src-new-1", 100_000, step=2, repository=repository),
                _reserve(
                    "src-existing",
                    200_000,
                    step=2,
                    repository=repository,
                ),
                _reserve("src-new-2", 100_000, step=2, repository=repository),
            )
        )
    snapshot = repository.capital_risk_snapshot(_moment(3))
    assert {r.source_id for r in snapshot.entry_reserves} == {
        "src-existing"
    }
    assert snapshot.reserved_cash_cents == 100_000
    assert snapshot.available_cash_cents == 900_000
    assert repository.capital_version() == capital_version
    repository.assert_conservation()


def test_batch_exact_replay_is_quiet_and_order_canonicalizes(
    repository,
) -> None:
    deposit(repository, 1_000_000, 1)
    first = repository.reserve_entries_atomic(
        (
            _reserve("src-z", 100_000, step=2, repository=repository),
            _reserve("src-a", 200_000, step=2, repository=repository),
        )
    )
    capital_version = repository.capital_version()
    # Reverse input order: the batch must canonicalize by source_id, so the
    # replay converges on the identical state without a new bump.
    replay = repository.reserve_entries_atomic(
        (
            _reserve("src-a", 200_000, step=2, repository=repository),
            _reserve("src-z", 100_000, step=2, repository=repository),
        )
    )
    assert replay.capital_version == first.capital_version
    assert replay.capital_version == capital_version
    assert {r.source_id for r in replay.entry_reserves} == {
        "src-a",
        "src-z",
    }
    assert replay.restricted_cash_cents == 300_000
    repository.assert_conservation()


def test_batch_cash_shortfall_after_prior_lines_still_rolls_back_all(
    repository,
) -> None:
    deposit(repository, 1_000_000, 1)
    with pytest.raises(CapitalConflict, match="insufficient_available_cash"):
        repository.reserve_entries_atomic(
            (
                _reserve("src-1", 800_000, step=2, repository=repository),
                _reserve("src-2", 300_000, step=2, repository=repository),
            )
        )
    snapshot = repository.capital_risk_snapshot(_moment(3))
    assert snapshot.entry_reserves == ()
    assert snapshot.available_cash_cents == 1_000_000
    repository.assert_conservation()


def test_two_process_batch_conflict_rolls_back_entirely(tmp_path) -> None:
    """Concurrent batches over one ledger: the loser leaves zero rows."""
    repository = CapitalRepository.initialize(tmp_path / "capital.sqlite3")
    deposit(repository, 1_000_000, 1)
    script = """
import sys
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.capital.reserves import ReserveEntryRequest
from datetime import datetime, timedelta, timezone

path = sys.argv[1]
repo = CapitalRepository.open(path)
as_of = datetime(2026, 8, 3, 9, 2, tzinfo=timezone.utc)
requests = tuple(
    ReserveEntryRequest(
        source_id=f"p{pid}-{i}",
        research_program_id="trial-1",
        economic_lineage_id="line-1",
        stage_id="stage-1",
        reserved_entry_gross_cents=300_000,
        expected_stream_version=repo.stream_version(),
        as_of=as_of + timedelta(seconds=pid),
    )
    for pid in (1, 2)
    for i in range(1)
)
try:
    repo.reserve_entries_atomic(requests)
    snapshot = repo.capital_risk_snapshot(as_of + timedelta(minutes=1))
    print("WINNER", snapshot.reserved_cash_cents)
except Exception as exc:
    print("LOSER", type(exc).__name__, str(exc)[:60])
"""
    repo_root = Path(__file__).resolve().parents[5]
    first = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "capital.sqlite3")],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert first.returncode == 0, first.stderr
    first_line = first.stdout.strip().splitlines()[0]
    assert first_line.split()[0] == "WINNER"
    # The second process either wins with the remaining cash or loses with
    # zero partial rows; both are legal, partial writes never are.
    second = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "capital.sqlite3")],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert second.returncode == 0, second.stderr
    second_line = second.stdout.strip().splitlines()[0]
    assert second_line.split()[0] in {"WINNER", "LOSER"}
    snapshot = repository.capital_risk_snapshot(_moment(9))
    rows = len(snapshot.entry_reserves)
    assert rows in (0, 2)
    # Whatever the outcome, cash never went negative and conservation holds.
    assert snapshot.available_cash_cents >= 0
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _payload_json(repository: CapitalRepository, event_id: str) -> str:
    with repository.engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT payload_json FROM economic_events"
                " WHERE economic_event_id = :event_id"
            ),
            {"event_id": event_id},
        ).one()
    return row[0]


def _stored_payload(repository: CapitalRepository, event_id: str):
    from src.screening.offensive.v3.capital.repository import (
        CapitalCommandPayload,
    )

    return CapitalCommandPayload.model_validate_json(
        _payload_json(repository, event_id)
    )
