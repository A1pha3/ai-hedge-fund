"""Transaction-kernel guarantees for the v3 AccountCapitalTruth store.

Plan 02 Task 1: account/environment/currency binding, stream-version CAS,
idempotent retries, payload conflicts, full rollback on projector failure,
two-process contention, and crash injection between event insert and
projection update.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalConflict,
    CapitalRepository,
)
from src.screening.offensive.v3.contracts import (
    CapitalRiskSnapshot,
    CashEconomicEventLeg,
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
    ExecutionMode,
    ExposureScope,
    PositionState,
    ReconciliationLatchState,
    RiskLatchState,
    SecurityEconomicEventLeg,
)
from src.screening.offensive.v3.storage import metadata


ROOT = Path(__file__).resolve().parents[4]
T0 = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
ENVIRONMENT_FINGERPRINT = "ab" * 32


def binding(**overrides) -> AccountBinding:
    kwargs = dict(
        portfolio_id="pf-test",
        mode=ExecutionMode.MANUAL_CONFIRMED,
        broker_account_id="acct-test",
        base_currency="CNY",
        environment_fingerprint=ENVIRONMENT_FINGERPRINT,
    )
    kwargs.update(overrides)
    return AccountBinding(**kwargs)


def receivable_command(
    key: str,
    expected_version: int,
    *,
    cents: int = 10_000,
    receivable_id: str = "rcv-1",
    as_of: datetime = T0,
    account: AccountBinding | None = None,
) -> CapitalCommand:
    amount = Decimal(cents) / 100
    payload = CapitalCommandPayload(
        event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
        effective_at=as_of,
        source_authority="test.manual",
        legs=(
            CashReceivableEconomicEventLeg(
                leg_id=f"{key}-r",
                direction=EconomicLegDirection.CREDIT,
                asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                receivable_id=receivable_id,
                security_id="600000.SH",
                cash_amount=amount,
            ),
        ),
    )
    return CapitalCommand(
        idempotency_key=key,
        account_binding=account or binding(),
        expected_stream_version=expected_version,
        as_of=as_of,
        payload=payload,
    )


def settle_command(
    key: str,
    expected_version: int,
    *,
    cents: int = 10_000,
    receivable_id: str = "rcv-1",
    as_of: datetime | None = None,
    account: AccountBinding | None = None,
) -> CapitalCommand:
    moment = as_of or (T0 + timedelta(hours=1))
    amount = Decimal(cents) / 100
    payload = CapitalCommandPayload(
        event_kind=EconomicEventKind.DIVIDEND_CASH_SETTLED,
        effective_at=moment,
        source_authority="test.manual",
        legs=(
            CashReceivableEconomicEventLeg(
                leg_id=f"{key}-r",
                direction=EconomicLegDirection.DEBIT,
                asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                receivable_id=receivable_id,
                security_id="600000.SH",
                cash_amount=amount,
            ),
            CashEconomicEventLeg(
                leg_id=f"{key}-c",
                direction=EconomicLegDirection.CREDIT,
                asset_kind=EconomicAssetKind.CASH,
                cash_amount=amount,
            ),
        ),
    )
    return CapitalCommand(
        idempotency_key=key,
        account_binding=account or binding(),
        expected_stream_version=expected_version,
        as_of=moment,
        payload=payload,
    )


def buy_command(
    key: str,
    expected_version: int,
    *,
    cents: int,
    quantity: int,
    as_of: datetime,
    account: AccountBinding | None = None,
) -> CapitalCommand:
    amount = Decimal(cents) / 100
    payload = CapitalCommandPayload(
        event_kind=EconomicEventKind.TRADE_EXECUTED,
        effective_at=as_of,
        source_authority="test.manual",
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        legs=(
            CashEconomicEventLeg(
                leg_id=f"{key}-c",
                direction=EconomicLegDirection.DEBIT,
                asset_kind=EconomicAssetKind.CASH,
                cash_amount=amount,
            ),
            SecurityEconomicEventLeg(
                leg_id=f"{key}-s",
                direction=EconomicLegDirection.CREDIT,
                asset_kind=EconomicAssetKind.SECURITY,
                security_id="600000.SH",
                quantity=quantity,
            ),
        ),
        producer_namespace="test.producer",
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        stage_id="stage-1",
    )
    return CapitalCommand(
        idempotency_key=key,
        account_binding=account or binding(),
        expected_stream_version=expected_version,
        as_of=as_of,
        payload=payload,
    )


def sell_command(
    key: str,
    expected_version: int,
    *,
    cents: int,
    quantity: int,
    as_of: datetime,
    account: AccountBinding | None = None,
) -> CapitalCommand:
    amount = Decimal(cents) / 100
    payload = CapitalCommandPayload(
        event_kind=EconomicEventKind.TRADE_EXECUTED,
        effective_at=as_of,
        source_authority="test.manual",
        position_lineage_id="lin-absent",
        economic_lot_id="lot-absent",
        legs=(
            CashEconomicEventLeg(
                leg_id=f"{key}-c",
                direction=EconomicLegDirection.CREDIT,
                asset_kind=EconomicAssetKind.CASH,
                cash_amount=amount,
            ),
            SecurityEconomicEventLeg(
                leg_id=f"{key}-s",
                direction=EconomicLegDirection.DEBIT,
                asset_kind=EconomicAssetKind.SECURITY,
                security_id="600000.SH",
                quantity=quantity,
            ),
        ),
        producer_namespace="test.producer",
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        stage_id="stage-1",
    )
    return CapitalCommand(
        idempotency_key=key,
        account_binding=account or binding(),
        expected_stream_version=expected_version,
        as_of=as_of,
        payload=payload,
    )


@pytest.fixture()
def repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


def test_initialize_yields_empty_state(repository: CapitalRepository) -> None:
    assert repository.stream_version() == 0
    assert repository.capital_version() == 0
    assert repository.events() == ()
    assert repository.schema_version() == metadata.LEDGER_SCHEMA_VERSION


def test_binding_requires_executable_mode() -> None:
    with pytest.raises(ValidationError):
        binding(mode=ExecutionMode.RESEARCH_RECONSTRUCTION)
    with pytest.raises(ValidationError):
        binding(mode=ExecutionMode.DAILY_BAR_PROXY)
    with pytest.raises(ValidationError):
        binding(broker_account_id=None)
    with pytest.raises(ValidationError):
        binding(environment_fingerprint=None)
    proxy = binding(
        mode=ExecutionMode.DAILY_BAR_PROXY,
        broker_account_id=None,
        environment_fingerprint=None,
    )
    assert proxy.broker_account_id is None


def test_first_append_binds_account_and_advances_versions(
    repository: CapitalRepository,
) -> None:
    snapshot = repository.append_atomic(receivable_command("k1", 0))

    assert isinstance(snapshot, CapitalRiskSnapshot)
    assert repository.stream_version() == 1
    assert repository.capital_version() == 1
    events = repository.events()
    assert len(events) == 1
    assert events[0].stream_version == 1
    assert events[0].event_kind is EconomicEventKind.DIVIDEND_RECEIVABLE
    assert snapshot.portfolio_id == "pf-test"
    assert snapshot.broker_account_id == "acct-test"
    assert snapshot.mode is ExecutionMode.MANUAL_CONFIRMED
    assert snapshot.base_currency == "CNY"
    assert snapshot.cash_receivable_cents == 10_000
    assert snapshot.available_cash_cents == 0
    assert snapshot.risk_latch is RiskLatchState.CLEAR
    assert snapshot.reconciliation_latch is ReconciliationLatchState.CLEAR

    with repository.engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT portfolio_id, broker_account_id, execution_mode,"
                " base_currency, environment_fingerprint"
                " FROM account_capital_truth"
            )
        ).one()
    assert row.portfolio_id == "pf-test"
    assert row.broker_account_id == "acct-test"
    assert row.execution_mode == "manual_confirmed"
    assert row.base_currency == "CNY"
    assert row.environment_fingerprint == ENVIRONMENT_FINGERPRINT


def test_binding_mismatch_is_rejected(repository: CapitalRepository) -> None:
    repository.append_atomic(receivable_command("k1", 0))
    for overrides in (
        {"base_currency": "USD"},
        {"broker_account_id": "acct-other"},
        {"environment_fingerprint": "cd" * 32},
        {"portfolio_id": "pf-other"},
    ):
        with pytest.raises(CapitalConflict) as excinfo:
            repository.append_atomic(
                receivable_command("k2", 1, account=binding(**overrides))
            )
        assert excinfo.value.code == "account_binding_mismatch"
    assert repository.stream_version() == 1


def test_stream_version_cas_conflict(repository: CapitalRepository) -> None:
    repository.append_atomic(receivable_command("k1", 0))
    with pytest.raises(CapitalConflict) as excinfo:
        repository.append_atomic(receivable_command("k2", 0, receivable_id="rcv-2"))
    assert excinfo.value.code == "stream_version_mismatch"
    assert excinfo.value.details["expected"] == 0
    assert excinfo.value.details["actual"] == 1
    assert repository.stream_version() == 1
    assert repository.capital_version() == 1


def test_idempotent_retry_returns_same_event(repository: CapitalRepository) -> None:
    command = receivable_command("k1", 0)
    first = repository.append_atomic(command)
    retry = repository.append_atomic(command)

    assert retry == first
    events = repository.events()
    assert len(events) == 1
    assert repository.stream_version() == 1
    assert repository.capital_version() == 1


def test_payload_conflict_on_same_idempotency_key(
    repository: CapitalRepository,
) -> None:
    repository.append_atomic(receivable_command("k1", 0, cents=10_000))
    with pytest.raises(CapitalConflict) as excinfo:
        repository.append_atomic(receivable_command("k1", 1, cents=20_000))
    assert excinfo.value.code == "payload_conflict"

    events = repository.events()
    assert len(events) == 1
    leg = events[0].legs[0]
    assert isinstance(leg, CashReceivableEconomicEventLeg)
    assert leg.cash_amount == Decimal("100.00")
    assert repository.capital_version() == 1


def test_contract_violation_rolls_back_with_zero_writes(
    repository: CapitalRepository,
) -> None:
    repository.append_atomic(receivable_command("k1", 0))
    amount = Decimal("50.00")
    payload = CapitalCommandPayload(
        event_kind=EconomicEventKind.TRADE_EXECUTED,
        effective_at=T0,
        source_authority="test.manual",
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        legs=(
            CashEconomicEventLeg(
                leg_id="bad-c",
                direction=EconomicLegDirection.CREDIT,
                asset_kind=EconomicAssetKind.CASH,
                cash_amount=amount,
            ),
            SecurityEconomicEventLeg(
                leg_id="bad-s",
                direction=EconomicLegDirection.CREDIT,
                asset_kind=EconomicAssetKind.SECURITY,
                security_id="600000.SH",
                quantity=10,
            ),
        ),
        producer_namespace="test.producer",
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        stage_id="stage-1",
    )
    command = CapitalCommand(
        idempotency_key="bad",
        account_binding=binding(),
        expected_stream_version=1,
        as_of=T0,
        payload=payload,
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.append_atomic(command)
    assert excinfo.value.code == "event_contract_rejected"
    assert repository.stream_version() == 1
    assert repository.capital_version() == 1


def test_projection_failure_rolls_back_with_zero_partial_writes(
    repository: CapitalRepository,
) -> None:
    repository.append_atomic(receivable_command("k1", 0))

    with pytest.raises(CapitalConflict) as excinfo:
        repository.append_atomic(
            settle_command("k2", 1, receivable_id="rcv-ghost")
        )
    assert excinfo.value.code == "projection_rejected"
    assert repository.stream_version() == 1
    assert repository.capital_version() == 1
    with repository.engine.connect() as conn:
        ghost = conn.execute(
            sa.text(
                "SELECT COUNT(*) AS n FROM economic_events"
                " WHERE idempotency_key = 'k2'"
            )
        ).scalar()
    assert ghost == 0

    # The CAS counter did not advance: the corrected command at the same
    # expected version succeeds.
    snapshot = repository.append_atomic(settle_command("k3", 1))
    assert snapshot.available_cash_cents == 10_000
    assert snapshot.cash_receivable_cents == 0


def test_projector_hook_failure_leaves_zero_partial_writes(
    repository: CapitalRepository,
) -> None:
    repository.append_atomic(receivable_command("k1", 0))

    def explode(context) -> None:
        raise RuntimeError("injected projector failure")

    with pytest.raises(RuntimeError, match="injected projector failure"):
        repository.append_atomic(
            settle_command("k2", 1),
            after_event_insert_hook=explode,
        )

    assert repository.stream_version() == 1
    assert repository.capital_version() == 1
    assert len(repository.events()) == 1
    with repository.engine.connect() as conn:
        unsettled = conn.execute(
            sa.text("SELECT settled FROM receivables WHERE receivable_id = 'rcv-1'")
        ).scalar()
        ghost = conn.execute(
            sa.text(
                "SELECT COUNT(*) AS n FROM economic_events"
                " WHERE idempotency_key = 'k2'"
            )
        ).scalar()
    assert unsettled == 0
    assert ghost == 0

    retry = repository.append_atomic(settle_command("k2", 1))
    assert retry.available_cash_cents == 10_000


def test_cash_receivable_projection_chain(repository: CapitalRepository) -> None:
    first = repository.append_atomic(receivable_command("k1", 0, cents=12_345))
    assert first.cash_receivable_cents == 12_345
    assert first.available_cash_cents == 0

    second = repository.append_atomic(settle_command("k2", 1, cents=12_345))
    assert second.cash_receivable_cents == 0
    assert second.available_cash_cents == 12_345
    assert second.capital_version == 2
    assert repository.stream_version() == 2


def test_double_settlement_of_receivable_is_rejected(
    repository: CapitalRepository,
) -> None:
    repository.append_atomic(receivable_command("k1", 0))
    repository.append_atomic(settle_command("k2", 1))
    with pytest.raises(CapitalConflict) as excinfo:
        repository.append_atomic(
            settle_command("k3", 2, receivable_id="rcv-1")
        )
    assert excinfo.value.code == "projection_rejected"
    assert repository.stream_version() == 2
    assert repository.capital_version() == 2


def test_trade_buy_creates_position_with_exposure_buckets(
    repository: CapitalRepository,
) -> None:
    repository.append_atomic(receivable_command("k1", 0, cents=10_000))
    repository.append_atomic(settle_command("k2", 1, cents=10_000))
    snapshot = repository.append_atomic(
        buy_command("k3", 2, cents=5_000, quantity=100, as_of=T0 + timedelta(hours=2))
    )

    assert snapshot.available_cash_cents == 5_000
    assert len(snapshot.positions) == 1
    position = snapshot.positions[0]
    assert position.position_lineage_id == "lin-1"
    assert position.economic_lot_id == "lot-1"
    assert position.security_id == "600000.SH"
    assert position.state is PositionState.OPEN
    assert position.settled_quantity == 100
    assert position.tradable_quantity == 100
    assert position.marked_gross_cents == 0
    assert position.research_program_id == "prog-1"

    scopes = [exposure.scope for exposure in snapshot.exposures]
    assert scopes == [
        ExposureScope.GLOBAL,
        ExposureScope.PORTFOLIO,
        ExposureScope.RESEARCH_PROGRAM,
        ExposureScope.ECONOMIC_LINEAGE,
        ExposureScope.STAGE,
    ]
    assert snapshot.total_gross_exposure_cents == 0

    with repository.engine.connect() as conn:
        cost_basis = conn.execute(
            sa.text("SELECT cost_basis_cents FROM positions")
        ).scalar()
    assert cost_basis == 5_000


def test_sell_without_position_is_rejected_and_rolled_back(
    repository: CapitalRepository,
) -> None:
    repository.append_atomic(receivable_command("k1", 0, cents=10_000))
    repository.append_atomic(settle_command("k2", 1, cents=10_000))
    with pytest.raises(CapitalConflict) as excinfo:
        repository.append_atomic(
            sell_command("k3", 2, cents=5_000, quantity=100, as_of=T0)
        )
    assert excinfo.value.code == "projection_rejected"
    assert repository.stream_version() == 2
    assert repository.capital_version() == 2


def test_cash_cannot_project_negative(repository: CapitalRepository) -> None:
    with pytest.raises(CapitalConflict):
        # FEE_CHARGED debits cash; the account holds zero cash in kernel
        # revision 1 because genesis units/flows land in Task 3.
        repository.append_atomic(
            CapitalCommand(
                idempotency_key="fee",
                account_binding=binding(),
                expected_stream_version=0,
                as_of=T0,
                payload=CapitalCommandPayload(
                    event_kind=EconomicEventKind.FEE_CHARGED,
                    effective_at=T0,
                    source_authority="test.manual",
                    legs=(
                        CashEconomicEventLeg(
                            leg_id="fee-c",
                            direction=EconomicLegDirection.DEBIT,
                            asset_kind=EconomicAssetKind.CASH,
                            cash_amount=Decimal("1.00"),
                        ),
                    ),
                ),
            )
        )
    assert repository.stream_version() == 0
    assert repository.capital_version() == 0


def test_snapshot_governance_fields_are_sentinels_until_activation(
    repository: CapitalRepository,
) -> None:
    snapshot = repository.append_atomic(receivable_command("k1", 0))
    assert snapshot.policy_activation_hash == metadata.UNACTIVATED_POLICY_ACTIVATION_HASH
    assert snapshot.policy_epoch == 1
    assert snapshot.authority_epoch == 1
    assert snapshot.risk_epoch == 1
    assert snapshot.registry_epoch == 1
    assert snapshot.authorization_id == metadata.UNACTIVATED_AUTHORIZATION_ID
    assert snapshot.authorization_version == 1
    assert snapshot.stage_loss_state_version == 1
    assert snapshot.writer_fencing_epoch == 1
    assert snapshot.schema_major == metadata.SCHEMA_MAJOR
    assert snapshot.freshness.value == "FRESH"
    assert snapshot.completeness.value == "COMPLETE"
    assert snapshot.valid_until > snapshot.as_of


def test_open_rejects_unknown_or_mismatched_schema(tmp_path: Path) -> None:
    database = tmp_path / "capital.sqlite3"
    CapitalRepository.initialize(database)
    with pytest.raises(FileNotFoundError):
        CapitalRepository.open(tmp_path / "missing.sqlite3")

    repo = CapitalRepository.open(database)
    assert repo.schema_version() == metadata.LEDGER_SCHEMA_VERSION

    with repo.engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE gateway_meta SET value = '999'"
                " WHERE key = 'schema_version'"
            )
        )
    with pytest.raises(CapitalConflict) as excinfo:
        CapitalRepository.open(database)
    assert excinfo.value.code == "schema_version_mismatch"


CONTENTION_WORKER = r"""
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalConflict,
    CapitalRepository,
)
from src.screening.offensive.v3.contracts import (
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
    ExecutionMode,
)

database = sys.argv[1]
worker = sys.argv[2]
marker = sys.argv[3]
sleep_seconds = float(sys.argv[4])
moment = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
account = AccountBinding(
    portfolio_id="pf-test",
    mode=ExecutionMode.MANUAL_CONFIRMED,
    broker_account_id="acct-test",
    base_currency="CNY",
    environment_fingerprint="ab" * 32,
)
payload = CapitalCommandPayload(
    event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
    effective_at=moment,
    source_authority="test.manual",
    legs=(
        CashReceivableEconomicEventLeg(
            leg_id="r",
            direction=EconomicLegDirection.CREDIT,
            asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
            receivable_id=f"rcv-{worker}",
            security_id="600000.SH",
            cash_amount=Decimal("100.00"),
        ),
    ),
)
command = CapitalCommand(
    idempotency_key=f"key-{worker}",
    account_binding=account,
    expected_stream_version=0,
    as_of=moment,
    payload=payload,
)
repository = CapitalRepository.open(database)


def hook(context):
    Path(marker).write_text(worker, encoding="utf-8")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)


try:
    repository.append_atomic(command, after_event_insert_hook=hook)
except CapitalConflict as conflict:
    print(f"CONFLICT:{conflict.code}", flush=True)
    sys.exit(7)
print("OK", flush=True)
"""


CRASH_WORKER = r"""
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalRepository,
)
from src.screening.offensive.v3.contracts import (
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
    ExecutionMode,
)

database = sys.argv[1]
moment = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
account = AccountBinding(
    portfolio_id="pf-test",
    mode=ExecutionMode.MANUAL_CONFIRMED,
    broker_account_id="acct-test",
    base_currency="CNY",
    environment_fingerprint="ab" * 32,
)
payload = CapitalCommandPayload(
    event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
    effective_at=moment,
    source_authority="test.manual",
    legs=(
        CashReceivableEconomicEventLeg(
            leg_id="r",
            direction=EconomicLegDirection.CREDIT,
            asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
            receivable_id="rcv-crash",
            security_id="600000.SH",
            cash_amount=Decimal("100.00"),
        ),
    ),
)
command = CapitalCommand(
    idempotency_key="crash-key",
    account_binding=account,
    expected_stream_version=0,
    as_of=moment,
    payload=payload,
)
repository = CapitalRepository.initialize(database)


def hook(context):
    # Simulate a hard crash after the event insert and before the
    # projection update commits.
    os._exit(3)


repository.append_atomic(command, after_event_insert_hook=hook)
print("UNREACHABLE", flush=True)
"""


def _worker_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(ROOT)}


def test_two_process_contention_has_exactly_one_winner(tmp_path: Path) -> None:
    database = tmp_path / "capital.sqlite3"
    CapitalRepository.initialize(database)
    marker = tmp_path / "worker_a.lock"

    env = _worker_env()
    worker_a = subprocess.Popen(
        [sys.executable, "-c", CONTENTION_WORKER, str(database), "A", str(marker), "1.2"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 15
    while not marker.exists():
        if time.monotonic() > deadline:
            worker_a.kill()
            raise AssertionError("worker A never reached the in-transaction hook")
        time.sleep(0.02)

    worker_b = subprocess.run(
        [sys.executable, "-c", CONTENTION_WORKER, str(database), "B", str(tmp_path / "b.lock"), "0"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    stdout_a, stderr_a = worker_a.communicate(timeout=60)

    assert worker_a.returncode == 0, stderr_a
    assert stdout_a.strip() == "OK"
    assert worker_b.returncode == 7, worker_b.stderr
    assert "CONFLICT:stream_version_mismatch" in worker_b.stdout

    repository = CapitalRepository.open(database)
    assert repository.stream_version() == 1
    events = repository.events()
    assert len(events) == 1
    assert events[0].economic_event_id.startswith("eco-")


def test_crash_between_event_insert_and_projection_leaves_zero_partial_writes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "capital.sqlite3"
    result = subprocess.run(
        [sys.executable, "-c", CRASH_WORKER, str(database)],
        env=_worker_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 3, result.stderr
    assert "UNREACHABLE" not in result.stdout

    repository = CapitalRepository.open(database)
    assert repository.stream_version() == 0
    assert repository.capital_version() == 0
    assert repository.events() == ()
    with repository.engine.connect() as conn:
        event_rows = conn.execute(
            sa.text("SELECT COUNT(*) AS n FROM economic_events")
        ).scalar()
        receivable_rows = conn.execute(
            sa.text("SELECT COUNT(*) AS n FROM receivables")
        ).scalar()
    assert event_rows == 0
    assert receivable_rows == 0

    # The crashed command can be retried cleanly: no ghost idempotency row.
    moment = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
    command = CapitalCommand(
        idempotency_key="crash-key",
        account_binding=binding(),
        expected_stream_version=0,
        as_of=moment,
        payload=CapitalCommandPayload(
            event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
            effective_at=moment,
            source_authority="test.manual",
            legs=(
                CashReceivableEconomicEventLeg(
                    leg_id="r",
                    direction=EconomicLegDirection.CREDIT,
                    asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                    receivable_id="rcv-crash",
                    security_id="600000.SH",
                    cash_amount=Decimal("100.00"),
                ),
            ),
        ),
    )
    snapshot = repository.append_atomic(command)
    assert repository.stream_version() == 1
    assert snapshot.cash_receivable_cents == 10_000
