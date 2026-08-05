"""Plan 02 Task 7: checkpoints, backups, rebuild, and full verification.

Session checkpoints are monotone per session (spec 12.2); restart converges
idempotently; late corrections append without reopening old checkpoints.
Backups bind the account, schema, versions and content root; restore to a
new path verifies before use. ``verify_ledger()`` recomputes the projection
identity from the append-only history and fails closed on tampering,
unknown events, or conservation drift.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

from src.screening.offensive.v3.capital.checkpoints import (
    SESSION_PHASES,
    CheckpointService,
    SessionCheckpointRequest,
)
from src.screening.offensive.v3.capital.fills import (
    FillAttribution,
    FillRevisionRequest,
)
from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalConflict,
    CapitalRepository,
)
from src.screening.offensive.v3.capital.verify import VerificationStatus
from src.screening.offensive.v3.contracts import (
    CashEconomicEventLeg,
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
    ExecutionMode,
    ExecutionRevisionKind,
    ExecutionSide,
)

T0 = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
ENVIRONMENT_FINGERPRINT = "ab" * 32
SECURITY = "600000.SH"
ATTRIBUTION = FillAttribution(
    producer_namespace="btst",
    research_program_id="prog-1",
    economic_lineage_id="eline-1",
    stage_id="stage-1",
)


def _moment(step: int) -> datetime:
    return T0 + timedelta(minutes=step)


def binding() -> AccountBinding:
    return AccountBinding(
        portfolio_id="pf-check",
        mode=ExecutionMode.BROKER_CONFIRMED,
        broker_account_id="acct-check",
        base_currency="CNY",
        environment_fingerprint=ENVIRONMENT_FINGERPRINT,
    )


@pytest.fixture()
def repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


def deposit(repository: CapitalRepository, cents: int, sequence: int) -> None:
    """Seed cash with the pre-genesis receivable/settlement pair."""

    amount = Decimal(cents) / 100
    receivable_id = f"rcv-{sequence}"
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"declare-{sequence}",
            account_binding=binding(),
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
    execution_id: str,
    repository: CapitalRepository,
    *,
    side: ExecutionSide = ExecutionSide.ENTRY,
    price_micros: int = 10_000_000,
    quantity: int = 100,
    revision: int = 1,
    revision_kind: str | None = None,
    step: int = 0,
) -> FillRevisionRequest:
    kwargs: dict = {}
    if revision_kind is not None:
        kwargs["revision_kind"] = ExecutionRevisionKind(revision_kind)
    return FillRevisionRequest(
        execution_id=execution_id,
        revision=revision,
        order_id=f"ord-{execution_id}",
        side=side,
        security_id=SECURITY,
        price_micros=price_micros,
        quantity=quantity,
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        attribution=ATTRIBUTION,
        source_authority="broker.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
        **kwargs,
    )


def test_checkpoint_phases_advance_monotonically(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    service = CheckpointService(repository)
    session = "2026-08-03"
    receipt = service.advance(
        SessionCheckpointRequest(
            session=session,
            phase=SESSION_PHASES[0],
            as_of=_moment(2),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.phase == SESSION_PHASES[0]
    receipt = service.advance(
        SessionCheckpointRequest(
            session=session,
            phase=SESSION_PHASES[2],
            as_of=_moment(3),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.phase == SESSION_PHASES[2]
    # A phase behind the session watermark is rejected fail-closed.
    with pytest.raises(CapitalConflict) as excinfo:
        service.advance(
            SessionCheckpointRequest(
                session=session,
                phase=SESSION_PHASES[1],
                as_of=_moment(4),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "checkpoint_order_conflict"
    assert service.watermark(session) == repository.stream_version()


def test_checkpoint_restart_converges_idempotently(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    service = CheckpointService(repository)
    session = "2026-08-03"
    request = SessionCheckpointRequest(
        session=session,
        phase=SESSION_PHASES[1],
        as_of=_moment(2),
        expected_stream_version=repository.stream_version(),
    )
    first = service.advance(request)
    again = service.advance(request)
    assert again.stream_version == first.stream_version
    assert again.capital_version == first.capital_version
    assert again.recorded_at == first.recorded_at
    assert service.watermark(session) == first.stream_version


def test_checkpoint_rejects_earlier_as_of(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    service = CheckpointService(repository)
    session = "2026-08-03"
    service.advance(
        SessionCheckpointRequest(
            session=session,
            phase=SESSION_PHASES[1],
            as_of=_moment(5),
            expected_stream_version=repository.stream_version(),
        )
    )
    with pytest.raises(CapitalConflict) as excinfo:
        service.advance(
            SessionCheckpointRequest(
                session=session,
                phase=SESSION_PHASES[2],
                as_of=_moment(4),
                expected_stream_version=repository.stream_version(),
            )
        )
    assert excinfo.value.code == "checkpoint_time_conflict"


def test_late_correction_after_checkpoint_appends_without_reopening(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-1", repository, step=2))
    service = CheckpointService(repository)
    session = "2026-08-03"
    checkpoint = service.advance(
        SessionCheckpointRequest(
            session=session,
            phase=SESSION_PHASES[1],
            as_of=_moment(3),
            expected_stream_version=repository.stream_version(),
        )
    )
    # A late correction appends at the CURRENT recorded instant and an
    # advancing stream; the committed checkpoint is never reopened.
    repository.record_fill_revision(
        fill_request(
            "exec-1",
            repository,
            revision=2,
            revision_kind="CORRECTED",
            price_micros=10_500_000,
            step=6,
        )
    )
    assert repository.stream_version() > checkpoint.stream_version
    assert service.watermark(session) == checkpoint.stream_version
    repository.assert_conservation()


def test_backup_manifest_binds_versions_and_restore_verifies(
    repository: CapitalRepository, tmp_path: Path
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-1", repository, step=2))
    backup_path = tmp_path / "backup" / "capital-backup.sqlite3"
    manifest = repository.backup_consistent(backup_path)
    stored_binding = repository.engine.connect().execute(
        sa.text(
            "SELECT binding_content_hash FROM account_capital_truth"
        )
    ).one()
    assert manifest.binding_content_hash == stored_binding[0]
    assert manifest.schema_major == 2
    assert manifest.stream_version == repository.stream_version()
    assert manifest.capital_version == repository.capital_version()
    assert manifest.durable_inbox_cursor is None
    assert manifest.durable_outbox_cursor is None
    assert len(manifest.content_root) == 64

    restored = CapitalRepository.restore_backup(
        manifest, backup_path, tmp_path / "restored.sqlite3"
    )
    assert restored.stream_version() == repository.stream_version()
    assert restored.capital_version() == repository.capital_version()
    report = restored.verify_ledger()
    assert report.capital_conservation is VerificationStatus.PASS
    assert report.projection_rebuild is VerificationStatus.PASS


def test_backup_failure_leaves_no_partial_state(
    repository: CapitalRepository, tmp_path: Path
) -> None:
    deposit(repository, 1_000_000, 1)
    service = CheckpointService(repository)
    checkpoint = service.advance(
        SessionCheckpointRequest(
            session="2026-08-03",
            phase=SESSION_PHASES[0],
            as_of=_moment(2),
            expected_stream_version=repository.stream_version(),
        )
    )
    blocked = tmp_path / "backup.sqlite3"
    blocked.write_bytes(b"not a directory")
    with pytest.raises((OSError, CapitalConflict)):
        repository.backup_consistent(blocked / "inner.sqlite3")
    assert not (blocked / "inner.sqlite3").exists()
    assert service.watermark("2026-08-03") == checkpoint.stream_version


def test_restore_rejects_tampered_backup_content(
    repository: CapitalRepository, tmp_path: Path
) -> None:
    deposit(repository, 1_000_000, 1)
    backup_path = tmp_path / "backup.sqlite3"
    manifest = repository.backup_consistent(backup_path)
    data = backup_path.read_bytes()
    backup_path.write_bytes(data[:-64] + b"\x00" * 64)
    with pytest.raises(CapitalConflict) as excinfo:
        CapitalRepository.restore_backup(
            manifest, backup_path, tmp_path / "restored.sqlite3"
        )
    assert excinfo.value.code == "backup_content_root_mismatch"


def test_verify_detects_projection_tampering(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-1", repository, step=2))
    clean = repository.verify_ledger()
    assert clean.capital_conservation is VerificationStatus.PASS
    assert clean.projection_rebuild is VerificationStatus.PASS

    with repository.engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE capital_projection"
                " SET available_cash_cents = available_cash_cents + 1"
            )
        )
    tampered = repository.verify_ledger()
    assert tampered.capital_conservation is VerificationStatus.FAIL
    assert tampered.projection_rebuild is VerificationStatus.FAIL
    assert any("conservation" in detail for detail in tampered.details)


def test_verify_detects_unknown_event_kind(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    with repository.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO economic_events ("
                " economic_event_id, idempotency_key, stream_version,"
                " event_kind, portfolio_id, position_lineage_id,"
                " economic_lot_id, execution_mode, source_authority,"
                " effective_at, recorded_at, correction_of_event_id,"
                " payload_json, payload_content_hash, canonical_event_json"
                ") VALUES ('eco-evil', 'evil-key',"
                " (SELECT MAX(stream_version) + 1 FROM economic_events),"
                " 'NOT_A_KIND', 'pf-check', NULL, NULL,"
                " 'broker_confirmed', 'evil',"
                " '2026-08-03T09:00:00+00:00',"
                " '2026-08-03T09:00:00+00:00', NULL, '{}',"
                " 'deadbeef' || printf('%056x', 1), '{}')"
            )
        )
    report = repository.verify_ledger()
    assert report.capital_conservation is VerificationStatus.FAIL


def test_verify_ledger_passes_on_clean_history(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 2_000_000, 1)
    repository.record_fill_revision(fill_request("exec-1", repository, step=2))
    report = repository.verify_ledger()
    assert report.capital_conservation is VerificationStatus.PASS
    assert report.projection_rebuild is VerificationStatus.PASS


def test_verify_cli_help_and_report(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-1", repository, step=2))
    help_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.screening.offensive.v3.capital.verify",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert help_result.returncode == 0
    assert "--db" in help_result.stdout

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.screening.offensive.v3.capital.verify",
            "--db",
            str(repository.db_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0
    assert "capital_conservation=PASS" in result.stdout
    assert "projection_rebuild=PASS" in result.stdout
