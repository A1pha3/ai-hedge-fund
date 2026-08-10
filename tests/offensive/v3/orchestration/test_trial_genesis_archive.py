"""Plan Task 6 RED: equal-genesis seal for the two trial arms.

Two arm ledgers with identical normalized economic state must seal into one
immutable, content-addressed ``TrialGenesisArchive``; any economic difference
(cash, units, positions, reserves, pending exits, risk state, watermark,
versions) rejects before enrollment. The captured SQLite backups plus the
``TrialGenesisManifest`` are immutable and restorable, and restoring both arms
must reproduce the same normalized genesis hash.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

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
    ExecutionSide,
)
from src.screening.offensive.v3.contracts.capital import PositionState
from src.screening.offensive.v3.gateway.exits import (
    ExitDerivationContext,
    ExitLane,
    ExitLotTruth,
)
from src.screening.offensive.v3.orchestration.genesis import (
    NormalizedTrialArmState,
    TrialArmGenesisSource,
    TrialGenesisArchive,
    TrialGenesisError,
    TrialGenesisManifest,
)

UTC = timezone.utc
T0 = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
SIGNAL_SESSION = date(2026, 8, 3)
ENV_FINGERPRINT = "ab" * 32
HASH = "a" * 64
FINGERPRINT = "c" * 64


def _binding(portfolio_id: str) -> AccountBinding:
    return AccountBinding(
        portfolio_id=portfolio_id,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        broker_account_id=None,
        base_currency="CNY",
        environment_fingerprint=ENV_FINGERPRINT,
    )


def _moment(step: int) -> datetime:
    return T0 + timedelta(minutes=step)


def _genesis(repository: CapitalRepository, portfolio_id: str) -> None:
    from src.screening.offensive.v3.capital.flows import GenesisRequest

    repository.initialize_genesis(
        GenesisRequest(
            idempotency_key="genesis-1",
            account_binding=_binding(portfolio_id),
            unit_quanta=1_000_000,
            unit_price_numerator=1,
            unit_price_denominator=1,
            source_authority="governance.test",
            authorization_reference="gov-genesis-1",
            effective_at=T0,
            as_of=T0,
        )
    )


def _deposit(
    repository: CapitalRepository, portfolio_id: str, cents: int, sequence: int
) -> None:
    """Seed cash via the receivable/settle pair (the only inflow before fills)."""

    amount = Decimal(cents) / 100
    receivable_id = f"rcv-{sequence}"
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"declare-{sequence}",
            account_binding=_binding(portfolio_id),
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
            account_binding=_binding(portfolio_id),
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


ATTRIBUTION = FillAttribution(
    producer_namespace="btst",
    research_program_id="prog-1",
    economic_lineage_id="eline-1",
    stage_id="stage-1",
)


def _fill(
    repository: CapitalRepository,
    execution_id: str,
    *,
    security_id: str = "600000.SH",
    price_micros: int = 10_000_000,
    quantity: int = 100,
    step: int = 10,
) -> None:
    repository.record_fill_revision(
        FillRevisionRequest(
            execution_id=execution_id,
            revision=1,
            order_id="ord-1",
            side=ExecutionSide.ENTRY,
            security_id=security_id,
            price_micros=price_micros,
            quantity=quantity,
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            attribution=ATTRIBUTION,
            source_authority="broker.test",
            effective_at=_moment(step),
            as_of=_moment(step) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


def _exit_context(portfolio_id: str) -> ExitDerivationContext:
    sessions: list[date] = []
    day = SIGNAL_SESSION
    while len(sessions) < 15:
        day = day + timedelta(days=1)
        if day.weekday() < 5:
            sessions.append(day)
    return ExitDerivationContext(
        portfolio_id=portfolio_id,
        broker_account_id=None,
        base_currency="CNY",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        capital_version=1,
        writer_fencing_epoch=1,
        fixed_exit_policy_fingerprint=FINGERPRINT,
        source_risk_snapshot_id="risk-snap-exit-1",
        source_risk_snapshot_hash=HASH,
        trading_sessions=tuple(sessions),
    )


def _exit_lot(**overrides) -> ExitLotTruth:
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
        "settled_quantity": 100,
        "tradable_quantity": 100,
        "live_exit_leaves": 0,
        "successor_security_id": None,
        "reopen": None,
    }
    values.update(overrides)
    return ExitLotTruth(**values)


@pytest.fixture()
def arm_repositories(tmp_path: Path):
    """Two independent capital ledgers with identical normalized economics."""

    champion_path = tmp_path / "champion.sqlite3"
    challenger_path = tmp_path / "challenger.sqlite3"
    champion = CapitalRepository.initialize(champion_path)
    challenger = CapitalRepository.initialize(challenger_path)
    for repo, portfolio_id in (
        (champion, "portfolio-champion"),
        (challenger, "portfolio-challenger"),
    ):
        _genesis(repo, portfolio_id)
        _deposit(repo, portfolio_id, 100_000, sequence=1)
    return champion, challenger


@pytest.fixture()
def archive(tmp_path: Path) -> TrialGenesisArchive:
    return TrialGenesisArchive(root=tmp_path / "archive")


# ---------------------------------------------------------------------------
# normalized state equality
# ---------------------------------------------------------------------------


def test_identical_ledgers_normalize_equal(arm_repositories) -> None:
    champion, challenger = arm_repositories
    left = TrialArmGenesisSource(
        capital_repository=champion,
        exit_lane=None,
        proxy_state_reader=None,
        portfolio_id="portfolio-champion",
    ).normalized_state()
    right = TrialArmGenesisSource(
        capital_repository=challenger,
        exit_lane=None,
        proxy_state_reader=None,
        portfolio_id="portfolio-challenger",
    ).normalized_state()
    assert isinstance(left, NormalizedTrialArmState)
    assert left == right


def test_cash_difference_changes_normalized_hash(arm_repositories) -> None:
    champion, challenger = arm_repositories
    _deposit(challenger, "portfolio-challenger", 10_000, sequence=2)
    left = TrialArmGenesisSource(
        capital_repository=champion, exit_lane=None, proxy_state_reader=None
    ).normalized_state()
    right = TrialArmGenesisSource(
        capital_repository=challenger, exit_lane=None, proxy_state_reader=None
    ).normalized_state()
    assert left != right


def test_seal_binds_equal_manifest_and_content_addresses(arm_repositories, archive) -> None:
    champion, challenger = arm_repositories
    champion_source = TrialArmGenesisSource(
        capital_repository=champion,
        exit_lane=None,
        proxy_state_reader=None,
        portfolio_id="portfolio-champion",
    )
    challenger_source = TrialArmGenesisSource(
        capital_repository=challenger,
        exit_lane=None,
        proxy_state_reader=None,
        portfolio_id="portfolio-challenger",
    )
    manifest = archive.seal("trial-1", champion_source, challenger_source)
    assert isinstance(manifest, TrialGenesisManifest)
    # One equal normalized hash binds both arms.
    assert manifest.normalized_genesis_hash == manifest.champion_normalized_hash
    assert manifest.normalized_genesis_hash == manifest.challenger_normalized_hash
    # The manifest hashes the sealed backups.
    assert len(manifest.champion_backup_root) == 64
    assert len(manifest.challenger_backup_root) == 64
    assert manifest.champion_backup_root != manifest.challenger_backup_root


def test_seal_is_exact_idempotent(arm_repositories, archive) -> None:
    champion, challenger = arm_repositories
    champion_source = TrialArmGenesisSource(
        capital_repository=champion, exit_lane=None, proxy_state_reader=None
    )
    challenger_source = TrialArmGenesisSource(
        capital_repository=challenger, exit_lane=None, proxy_state_reader=None
    )
    first = archive.seal("trial-1", champion_source, challenger_source)
    second = archive.seal("trial-1", champion_source, challenger_source)
    assert second == first


def test_genesis_rejects_hidden_pending_exit_difference(
    arm_repositories, archive, tmp_path
) -> None:
    """A pending exit mandate in one arm changes the normalized state."""
    champion, challenger = arm_repositories
    # Champion has a position + exit obligation; challenger does not.
    _fill(champion, "fill-champion-1")
    lane = ExitLane(database_path=str(tmp_path / "exit-lane.sqlite3"), clock=_Clock(T0))
    lane.derive_exit_mandates(
        (_exit_lot(),), context=_exit_context("portfolio-champion")
    )
    champion_source = TrialArmGenesisSource(
        capital_repository=champion,
        exit_lane=lane,
        proxy_state_reader=None,
        portfolio_id="portfolio-champion",
    )
    challenger_source = TrialArmGenesisSource(
        capital_repository=challenger,
        exit_lane=None,
        proxy_state_reader=None,
        portfolio_id="portfolio-challenger",
    )
    with pytest.raises(TrialGenesisError, match="genesis_economic_state_mismatch"):
        archive.seal("trial-1", champion_source, challenger_source)


def test_genesis_rejects_reserve_difference(arm_repositories, archive) -> None:
    champion, challenger = arm_repositories
    from src.screening.offensive.v3.capital.reserves import ReserveEntryRequest

    challenger.reserve_entry(
        ReserveEntryRequest(
            source_id="rsv-1",
            research_program_id="prog-1",
            economic_lineage_id="eline-1",
            stage_id="stage-1",
            reserved_entry_gross_cents=50_000,
            expected_stream_version=challenger.stream_version(),
            as_of=_moment(20),
        )
    )
    champion_source = TrialArmGenesisSource(
        capital_repository=champion, exit_lane=None, proxy_state_reader=None
    )
    challenger_source = TrialArmGenesisSource(
        capital_repository=challenger, exit_lane=None, proxy_state_reader=None
    )
    with pytest.raises(TrialGenesisError, match="genesis_economic_state_mismatch"):
        archive.seal("trial-1", champion_source, challenger_source)


def test_genesis_rejects_version_watermark_difference(
    arm_repositories, archive
) -> None:
    champion, challenger = arm_repositories
    # The challenger advances one extra capital version via a reserve.
    from src.screening.offensive.v3.capital.reserves import ReserveEntryRequest

    champion.reserve_entry(
        ReserveEntryRequest(
            source_id="rsv-c",
            research_program_id="prog-1",
            economic_lineage_id="eline-1",
            stage_id="stage-1",
            reserved_entry_gross_cents=10_000,
            expected_stream_version=champion.stream_version(),
            as_of=_moment(20),
        )
    )
    challenger.reserve_entry(
        ReserveEntryRequest(
            source_id="rsv-c",
            research_program_id="prog-1",
            economic_lineage_id="eline-1",
            stage_id="stage-1",
            reserved_entry_gross_cents=10_000,
            expected_stream_version=challenger.stream_version(),
            as_of=_moment(20),
        )
    )
    challenger.reserve_entry(
        ReserveEntryRequest(
            source_id="rsv-x",
            research_program_id="prog-1",
            economic_lineage_id="eline-1",
            stage_id="stage-1",
            reserved_entry_gross_cents=10_000,
            expected_stream_version=challenger.stream_version(),
            as_of=_moment(21),
        )
    )
    champion_source = TrialArmGenesisSource(
        capital_repository=champion, exit_lane=None, proxy_state_reader=None
    )
    challenger_source = TrialArmGenesisSource(
        capital_repository=challenger, exit_lane=None, proxy_state_reader=None
    )
    with pytest.raises(TrialGenesisError, match="genesis_economic_state_mismatch"):
        archive.seal("trial-1", champion_source, challenger_source)


def test_sealed_backups_are_content_addressed_and_restorable(
    arm_repositories, archive, tmp_path
) -> None:
    champion, challenger = arm_repositories
    champion_source = TrialArmGenesisSource(
        capital_repository=champion, exit_lane=None, proxy_state_reader=None
    )
    challenger_source = TrialArmGenesisSource(
        capital_repository=challenger, exit_lane=None, proxy_state_reader=None
    )
    manifest = archive.seal("trial-1", champion_source, challenger_source)

    # The archive bytes are addressed by the manifest roots.
    champion_backup = (
        tmp_path / "archive" / manifest.trial_id / manifest.champion_backup_root
        / "capital.sqlite3"
    )
    assert champion_backup.is_file()
    import hashlib

    assert (
        hashlib.sha256(champion_backup.read_bytes()).hexdigest()
        == manifest.champion_backup_root
    )

    # Restoring both arms to fresh paths reproduces the same normalized hash.
    from src.screening.offensive.v3.orchestration.genesis import (
        restore_genesis_arm,
    )

    restored_champion = restore_genesis_arm(
        manifest,
        tmp_path / "archive",
        tmp_path / "restored" / "champion.sqlite3",
        arm="CHAMPION",
    )
    restored_challenger = restore_genesis_arm(
        manifest,
        tmp_path / "archive",
        tmp_path / "restored" / "challenger.sqlite3",
        arm="CHALLENGER",
    )
    left = TrialArmGenesisSource(
        capital_repository=restored_champion, exit_lane=None, proxy_state_reader=None
    ).normalized_state()
    right = TrialArmGenesisSource(
        capital_repository=restored_challenger,
        exit_lane=None,
        proxy_state_reader=None,
    ).normalized_state()
    assert left == right
    assert left.content_hash() == manifest.normalized_genesis_hash


def test_restore_rejects_tampered_backup_bytes(
    arm_repositories, archive, tmp_path
) -> None:
    champion, challenger = arm_repositories
    champion_source = TrialArmGenesisSource(
        capital_repository=champion, exit_lane=None, proxy_state_reader=None
    )
    challenger_source = TrialArmGenesisSource(
        capital_repository=challenger, exit_lane=None, proxy_state_reader=None
    )
    manifest = archive.seal("trial-1", champion_source, challenger_source)
    backup = (
        tmp_path
        / "archive"
        / manifest.trial_id
        / manifest.champion_backup_root
        / "capital.sqlite3"
    )
    backup.write_bytes(b"TAMPERED")
    from src.screening.offensive.v3.orchestration.genesis import (
        restore_genesis_arm,
    )

    with pytest.raises(TrialGenesisError, match="content_root"):
        restore_genesis_arm(
            manifest,
            tmp_path / "archive",
            tmp_path / "restored" / "champion.sqlite3",
            arm="CHAMPION",
        )


def test_restore_overwrites_existing_path_and_reconverges(
    arm_repositories, archive, tmp_path
) -> None:
    """Task 12: crash-rerun restore is idempotent over the ledger path.

    A replay run after a mid-run crash restores the genesis arm to the same
    lane path that already holds a ledger (possibly carrying committed replay
    state). Restore must re-seal that path from the verified backup bytes so
    the rerun starts from the same genesis, and the restored store must
    reproduce the sealed normalized hash.
    """

    champion, challenger = arm_repositories
    champion_source = TrialArmGenesisSource(
        capital_repository=champion, exit_lane=None, proxy_state_reader=None
    )
    challenger_source = TrialArmGenesisSource(
        capital_repository=challenger, exit_lane=None, proxy_state_reader=None
    )
    manifest = archive.seal("trial-1", champion_source, challenger_source)
    from src.screening.offensive.v3.orchestration.genesis import (
        restore_genesis_arm,
    )

    target = tmp_path / "lane" / "champion.sqlite3"
    # First restore leaves a live store at the target path.
    first = restore_genesis_arm(
        manifest, tmp_path / "archive", target, arm="CHAMPION"
    )
    first_normalized = TrialArmGenesisSource(
        capital_repository=first, exit_lane=None, proxy_state_reader=None
    ).normalized_state()
    # A crash-rerun restores the same arm over the existing path.
    second = restore_genesis_arm(
        manifest, tmp_path / "archive", target, arm="CHAMPION"
    )
    second_normalized = TrialArmGenesisSource(
        capital_repository=second, exit_lane=None, proxy_state_reader=None
    ).normalized_state()
    # The re-sealed ledger converges to the same genesis hash.
    assert second_normalized == first_normalized
    assert second_normalized.content_hash() == manifest.normalized_genesis_hash
