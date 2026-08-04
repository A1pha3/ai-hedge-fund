"""Plan 02 Task 5: complete CapitalRiskSnapshot, drawdown latch, and the
non-replenishable stage-loss budget.

Covered semantics:

- The risk snapshot is a DERIVED view over AccountCapitalTruth: it consumes
  only fill-verified position projections, reserves, live-order exposure and
  the current valid marks. Stale, unauthorized, missing or invalid marks are
  rejected fail-closed and never silently substituted.
- ``close_risk_snapshot`` seals the snapshot for one session as the frozen
  ``CapitalRiskSnapshot`` contract plus an append-only RISK_SNAPSHOT seal
  record carrying the content-hash fingerprint; identical closes converge,
  divergent closes conflict.
- Drawdown tiers follow the charter: <10% no scaling, 10-15% linear scaling
  of the unscaled multiplier to zero, >=15% latches ``RISK_HALTED``. The
  latch is one-way within the risk epoch and operates on the active-epoch
  operational baseline; only a new governance risk epoch clears it.
- Stage loss: the budget freezes at activation in integer cents; consumption
  is ``max(previous, instantaneous_charge)`` in the same capital transaction
  as fills/fees/marks/reserves; profit, rebound, relabel or epoch swap never
  refund consumed budget; per-lineage/stage and global consumption are
  tracked separately; ``STAGE_LOSS_HALTED`` is permanent.
- Unknown/ambiguous exposure is never under-reported: unattributed fills stay
  in the snapshot with a reconciliation halt, and SUBMISSION_AMBIGUOUS
  reserves keep their worst-case exposure live.
- Property test: generated sequences of fills/marks/reserves/stage-loss
  charges keep stage-loss monotonicity and conservation invariants.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from src.screening.offensive.v3.capital.fees import FeePolicy
from src.screening.offensive.v3.capital.fills import (
    FeeRevisionRequest,
    FillAttribution,
    FillRevisionRequest,
)
from src.screening.offensive.v3.capital.flows import (
    GenesisRequest,
    LifecycleState,
    RiskEpochRequest,
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
from src.screening.offensive.v3.capital.reserves import (
    ReserveEntryRequest,
    ReserveReleaseReason,
    ReserveReleaseRequest,
)
from src.screening.offensive.v3.capital.rounding import (
    MICROS_PER_CENT,
    round_half_even_div,
)
from src.screening.offensive.v3.capital.risk_snapshot import (
    BuildRiskSnapshotRequest,
    CloseRiskSnapshotRequest,
    StageLossBudgetActivationRequest,
    StageLossChargeRequest,
    entry_scaling_multiplier_ppm,
)
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    ExecutionSide,
    ExposureScope,
    ReconciliationLatchState,
    RiskLatchState,
    StageLossLatchState,
)
from src.screening.offensive.v3.storage.metadata import (
    DRAWDOWN_HALT_PPM,
    RISK_SNAPSHOT_VALIDITY,
)


T0 = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
ENVIRONMENT_FINGERPRINT = "ab" * 32

# Genesis terms: 10_000 units at 1_000 cents per unit quanta = 10_000_000
# cents of seed capital.
GENESIS_UNITS = 10_000
GENESIS_PRICE_NUMERATOR = 1_000
GENESIS_PRICE_DENOMINATOR = 1
GENESIS_CASH_CENTS = GENESIS_UNITS * GENESIS_PRICE_NUMERATOR

SECURITY = "600000.SH"

ATTRIBUTION = FillAttribution(
    producer_namespace="btst",
    research_program_id="prog-1",
    economic_lineage_id="eline-1",
    stage_id="stage-1",
)

MARK_AUTHORITY = "valuation.test"

POLICY_V1 = FeePolicy(
    fee_policy_version="fee-schedule-2026-v1",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=1_000,
    transfer_fee_rate_ppm=20,
)


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


def genesis(
    repository: CapitalRepository, *, step: int = 0, key: str = "genesis-1"
) -> None:
    repository.initialize_genesis(
        GenesisRequest(
            idempotency_key=key,
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


def entry_fill(
    repository: CapitalRepository,
    *,
    step: int,
    execution_id: str,
    price_micros: int = 100_000_000,
    quantity: int = 1_000,
    order_id: str | None = None,
    security_id: str = SECURITY,
    attribution: FillAttribution | None = ATTRIBUTION,
    position_lineage_id: str | None = None,
    economic_lot_id: str | None = None,
) -> object:
    # The snapshot contract requires every position lineage and economic lot
    # identity to be unique, so each execution defaults to its own pair.
    if attribution is None:
        lineage = None
        lot = None
    else:
        lineage = position_lineage_id or f"lin-{execution_id}"
        lot = economic_lot_id or f"lot-{execution_id}"
    request = FillRevisionRequest(
        execution_id=execution_id,
        revision=1,
        order_id=order_id or f"ord-{execution_id}",
        side=ExecutionSide.ENTRY,
        security_id=security_id,
        price_micros=price_micros,
        quantity=quantity,
        position_lineage_id=lineage,
        economic_lot_id=lot,
        attribution=attribution,
        source_authority="broker.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
    )
    return repository.record_fill_revision(request)


def valuation(
    repository: CapitalRepository,
    *,
    step: int,
    marks: dict[str, int],
    key: str | None = None,
    source_authority: str = MARK_AUTHORITY,
) -> object:
    request = ValuationRequest(
        idempotency_key=key or f"valuation-{step}",
        source_authority=source_authority,
        effective_at=_moment(step),
        as_of=_moment(step),
        expected_stream_version=repository.stream_version(),
        marks=tuple(
            ValuationMarkInput(security_id=security_id, price_micros=price_micros)
            for security_id, price_micros in sorted(marks.items())
        ),
    )
    return repository.close_valuation(request)


def build_request(
    as_of: datetime, authorities: tuple[str, ...] = (MARK_AUTHORITY,)
) -> BuildRiskSnapshotRequest:
    return BuildRiskSnapshotRequest(
        as_of=as_of, authorized_mark_authorities=authorities
    )


def activate_budget(
    repository: CapitalRepository,
    *,
    step: int,
    budget_id: str = "budget-1",
    frozen_budget_cents: int = 1_000_000,
    key: str | None = None,
    program: str = "prog-1",
    lineage: str = "eline-1",
    stage: str = "stage-1",
) -> object:
    return repository.activate_stage_loss_budget(
        StageLossBudgetActivationRequest(
            idempotency_key=key or f"activate-{budget_id}",
            research_program_id=program,
            economic_lineage_id=lineage,
            stage_id=stage,
            stage_loss_budget_id=budget_id,
            frozen_budget_cents=frozen_budget_cents,
            source_authority="governance.test",
            authorization_reference="gov-stage-budget-1",
            expected_stage_loss_state_version=(
                repository.capital_risk_snapshot(_moment(step))
                .stage_loss_state_version
            ),
            as_of=_moment(step),
        )
    )


def charge_loss(
    repository: CapitalRepository,
    *,
    step: int,
    key: str,
    realized: int = 0,
    fees: int = 0,
    unrealized_pnl: int = 0,
    stress: int = 0,
    program: str = "prog-1",
    lineage: str = "eline-1",
    stage: str = "stage-1",
) -> object:
    request = StageLossChargeRequest(
        idempotency_key=key,
        research_program_id=program,
        economic_lineage_id=lineage,
        stage_id=stage,
        source_authority="risk.test",
        realized_market_losses_ex_fees_cents=realized,
        cumulative_fees_and_taxes_cents=fees,
        marked_unrealized_pnl_cents=unrealized_pnl,
        incremental_pending_stress_beyond_mark_cents=stress,
        expected_stage_loss_state_version=(
            repository.capital_risk_snapshot(_moment(step)).stage_loss_state_version
        ),
        as_of=_moment(step),
    )
    return repository.record_stage_loss(request)


def stage_latch(
    repository: CapitalRepository, program: str, lineage: str, stage: str
):
    matches = [
        latch
        for latch in repository.stage_loss_latches()
        if latch.identity() == (program, lineage, stage)
    ]
    assert len(matches) == 1
    return matches[0]


# ---------------------------------------------------------------------------
# Derived snapshot view: marks are validated fail-closed
# ---------------------------------------------------------------------------


def test_build_snapshot_derives_complete_truth_at_one_capital_version(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1", quantity=1_000)
    valuation(repository, step=2, marks={SECURITY: 120_000_000})

    snapshot = repository.build_capital_risk_snapshot(
        build_request(_moment(3))
    )

    # The frozen contract shape: marked gross, NAV, HWM, exposure, latches.
    assert snapshot.portfolio_id == "pf-test"
    assert snapshot.capital_version == repository.capital_version()
    assert snapshot.positions[0].marked_gross_cents == 12_000_000
    assert snapshot.as_observed_nav_cents == (
        GENESIS_CASH_CENTS - 10_000_000 + 12_000_000
    )
    assert snapshot.lifetime_high_water_mark_cents == snapshot.as_observed_nav_cents
    assert snapshot.freshness.value == "FRESH"
    assert snapshot.completeness.value == "COMPLETE"
    assert snapshot.risk_latch is RiskLatchState.CLEAR
    assert snapshot.reconciliation_latch is ReconciliationLatchState.CLEAR
    assert snapshot.total_gross_exposure_cents == 12_000_000

    # Deterministic derived view: building twice at the same capital version
    # converges on an identical content-hash fingerprint.
    again = repository.build_capital_risk_snapshot(build_request(_moment(3)))
    assert again.content_hash() == snapshot.content_hash()
    assert again.risk_snapshot_id == snapshot.risk_snapshot_id


def test_build_snapshot_without_valuation_fails_closed(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1")
    with pytest.raises(CapitalConflict) as excinfo:
        repository.build_capital_risk_snapshot(build_request(_moment(2)))
    assert excinfo.value.code == "valuation_unknown"


def test_build_snapshot_rejects_stale_marks(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1")
    valuation(repository, step=2, marks={SECURITY: 100_000_000})
    stale_as_of = _moment(2) + RISK_SNAPSHOT_VALIDITY + timedelta(seconds=1)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.build_capital_risk_snapshot(build_request(stale_as_of))
    assert excinfo.value.code == "mark_stale"


def test_build_snapshot_rejects_marks_recorded_after_as_of(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1")
    valuation(repository, step=5, marks={SECURITY: 100_000_000})
    with pytest.raises(CapitalConflict) as excinfo:
        repository.build_capital_risk_snapshot(build_request(_moment(4)))
    assert excinfo.value.code == "mark_not_yet_recorded"


def test_build_snapshot_rejects_position_opened_after_last_valuation(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(
        repository, step=1, execution_id="exec-1", price_micros=10_000_000
    )
    valuation(repository, step=2, marks={SECURITY: 10_000_000})
    # A position in a NEW security opens AFTER the last valuation: that
    # security has no current mark, and the unknown mark must never be
    # silently substituted with zero.
    entry_fill(
        repository,
        step=3,
        execution_id="exec-2",
        security_id="000002.SZ",
        price_micros=10_000_000,
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.build_capital_risk_snapshot(build_request(_moment(4)))
    assert excinfo.value.code == "mark_missing"


def test_build_snapshot_rejects_unauthorized_mark_authority(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1")
    valuation(
        repository, step=2, marks={SECURITY: 100_000_000}, source_authority="rogue"
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.build_capital_risk_snapshot(build_request(_moment(3)))
    assert excinfo.value.code == "mark_unauthorized"


def test_valuation_ingest_rejects_non_positive_marks() -> None:
    with pytest.raises(ValidationError):
        ValuationMarkInput(security_id=SECURITY, price_micros=0)
    with pytest.raises(ValidationError):
        ValuationMarkInput(security_id=SECURITY, price_micros=-5)


def test_build_snapshot_requires_at_least_one_trusted_authority() -> None:
    with pytest.raises(ValidationError):
        BuildRiskSnapshotRequest(as_of=_moment(1), authorized_mark_authorities=())


# ---------------------------------------------------------------------------
# Drawdown tiers and the one-way RISK_HALTED latch
# ---------------------------------------------------------------------------


def test_entry_scaling_multiplier_follows_charter_tiers() -> None:
    # Below 10%: no scaling.
    assert entry_scaling_multiplier_ppm(0) == 1_000_000
    assert entry_scaling_multiplier_ppm(99_900) == 1_000_000  # 9.99%
    # 10% boundary is continuous: scaling starts at exactly 1.0.
    assert entry_scaling_multiplier_ppm(100_000) == 1_000_000
    # Linear to zero between 10% and 15%.
    assert entry_scaling_multiplier_ppm(125_000) == 500_000
    assert entry_scaling_multiplier_ppm(149_900) == 2_000  # 14.99%
    # 15% and beyond: zero multiplier (halt band).
    assert entry_scaling_multiplier_ppm(150_000) == 0
    assert entry_scaling_multiplier_ppm(1_000_000) == 0


def test_risk_latch_halts_at_fifteen_percent_and_is_one_way(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    # Invest the full capital so NAV tracks the mark one-for-one.
    entry_fill(repository, step=1, execution_id="exec-1", quantity=1_000)
    # Mark to 85% of cost: exactly the 15% drawdown halt threshold.
    valuation(repository, step=2, marks={SECURITY: 85_000_000})
    snapshot = repository.build_capital_risk_snapshot(build_request(_moment(3)))
    assert snapshot.active_epoch_drawdown_ppm == DRAWDOWN_HALT_PPM
    assert snapshot.risk_latch is RiskLatchState.RISK_HALTED

    # Full price recovery within the SAME epoch never clears the latch: it is
    # one-way until a new governance risk epoch.
    valuation(repository, step=4, marks={SECURITY: 100_000_000})
    recovered = repository.build_capital_risk_snapshot(build_request(_moment(5)))
    assert recovered.active_epoch_drawdown_ppm == 0
    assert recovered.risk_latch is RiskLatchState.RISK_HALTED


def test_risk_latch_tracks_active_epoch_baseline_after_recovery(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1", quantity=1_000)
    valuation(repository, step=2, marks={SECURITY: 85_000_000})
    halted = repository.build_capital_risk_snapshot(build_request(_moment(3)))
    assert halted.risk_latch is RiskLatchState.RISK_HALTED

    audited_nav = halted.as_observed_nav_cents
    _, epoch_snapshot = repository.start_risk_epoch(
        RiskEpochRequest(
            idempotency_key="epoch-2",
            risk_epoch=2,
            audited_nav_cents=audited_nav,
            source_authority="governance.test",
            authorization_reference="gov-recovery-1",
            effective_at=_moment(4),
            as_of=_moment(4),
        )
    )
    # The new risk epoch is the governance recovery act: the latch clears and
    # the operational baseline becomes the audited NAV.
    assert epoch_snapshot.risk_latch is RiskLatchState.CLEAR
    assert epoch_snapshot.active_epoch_high_water_mark_cents == audited_nav

    # Below 15% from the NEW baseline the account stays clear...
    valuation(repository, step=5, marks={SECURITY: 86_000_000})
    snapshot = repository.build_capital_risk_snapshot(build_request(_moment(6)))
    assert snapshot.active_epoch_drawdown_ppm < DRAWDOWN_HALT_PPM
    assert snapshot.risk_latch is RiskLatchState.CLEAR


def test_risk_latch_just_below_threshold_stays_clear(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1", quantity=1_000)
    # 14.99% drawdown: inside the scaling band, not halted.
    valuation(repository, step=2, marks={SECURITY: 85_010_000})
    snapshot = repository.build_capital_risk_snapshot(build_request(_moment(3)))
    assert snapshot.active_epoch_drawdown_ppm == 149_900
    assert snapshot.risk_latch is RiskLatchState.CLEAR


# ---------------------------------------------------------------------------
# Stage loss: frozen integer budget, monotone non-replenishable consumption
# ---------------------------------------------------------------------------


def test_activate_stage_loss_budget_freezes_integer_cents(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    capital_before = repository.capital_version()
    snapshot = activate_budget(
        repository, step=1, frozen_budget_cents=750_000
    )

    latch = stage_latch(repository, "prog-1", "eline-1", "stage-1")
    assert latch.frozen_budget_cents == 750_000
    assert latch.consumed_cents == 0
    assert latch.stage_loss_version == 1
    assert latch.state is StageLossLatchState.CLEAR
    assert latch.stage_loss_budget_id == "budget-1"

    # Activation is an authority-state fact: capital and stage-loss versions
    # advance atomically and the snapshot carries the latch.
    assert snapshot.capital_version == capital_before + 1
    assert snapshot.stage_loss_latches == (latch,)
    assert snapshot.stage_loss_state_version == 2


def test_activate_budget_idempotent_retry_and_conflicts(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    snapshot = activate_budget(repository, step=1, frozen_budget_cents=500_000)

    # Identical retry converges quietly (same content, no version growth).
    retry = activate_budget(repository, step=2, frozen_budget_cents=500_000)
    assert retry.capital_version == snapshot.capital_version
    assert retry.stage_loss_state_version == snapshot.stage_loss_state_version

    # Same idempotency key with different content conflicts.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.activate_stage_loss_budget(
            StageLossBudgetActivationRequest(
                idempotency_key="activate-budget-1",
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
                stage_id="stage-1",
                stage_loss_budget_id="budget-1",
                frozen_budget_cents=999_999,
                source_authority="governance.test",
                authorization_reference="gov-stage-budget-1",
                expected_stage_loss_state_version=(
                    repository.capital_risk_snapshot(_moment(2))
                    .stage_loss_state_version
                ),
                as_of=_moment(2),
            )
        )
    assert excinfo.value.code == "payload_conflict"

    # The stage identity already has a frozen budget: a second (relabelled or
    # re-authorized) budget for the same identity can never reset it.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.activate_stage_loss_budget(
            StageLossBudgetActivationRequest(
                idempotency_key="activate-budget-2",
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
                stage_id="stage-1",
                stage_loss_budget_id="budget-2",
                frozen_budget_cents=1_000_000,
                source_authority="governance.test",
                authorization_reference="gov-stage-budget-2",
                expected_stage_loss_state_version=(
                    repository.capital_risk_snapshot(_moment(2))
                    .stage_loss_state_version
                ),
                as_of=_moment(2),
            )
        )
    assert excinfo.value.code == "stage_loss_budget_conflict"


def test_record_stage_loss_consumes_monotone_max(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    activate_budget(repository, step=1, frozen_budget_cents=1_000)

    receipt, _ = charge_loss(repository, step=2, key="charge-1", realized=300)
    assert receipt.instantaneous_charge_cents == 300
    assert receipt.consumed_before_cents == 0
    assert receipt.consumed_after_cents == 300
    assert receipt.state is StageLossLatchState.CLEAR

    # A larger charge raises consumption...
    receipt, _ = charge_loss(repository, step=3, key="charge-2", realized=500)
    assert receipt.consumed_before_cents == 300
    assert receipt.consumed_after_cents == 500

    # ...a smaller one never refunds it: consumed = max(previous, charge).
    receipt, _ = charge_loss(repository, step=4, key="charge-3", realized=100)
    assert receipt.instantaneous_charge_cents == 100
    assert receipt.consumed_before_cents == 500
    assert receipt.consumed_after_cents == 500
    assert stage_latch(
        repository, "prog-1", "eline-1", "stage-1"
    ).consumed_cents == 500


def test_stage_loss_instantaneous_charge_follows_the_formula(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    activate_budget(repository, step=1, frozen_budget_cents=10_000)

    # Mutually exclusive components: realized loss ex fees + cumulative fees
    # + max(0, -unrealized) + pending stress beyond mark. An unrealized
    # PROFIT contributes zero, never a negative offset.
    receipt, _ = charge_loss(
        repository,
        step=2,
        key="charge-profit",
        realized=100,
        fees=50,
        unrealized_pnl=30,
        stress=25,
    )
    assert receipt.instantaneous_charge_cents == 175

    receipt, _ = charge_loss(
        repository,
        step=3,
        key="charge-loss",
        realized=0,
        fees=0,
        unrealized_pnl=-80,
        stress=0,
    )
    assert receipt.instantaneous_charge_cents == 80
    assert receipt.consumed_after_cents == 175


def test_stage_loss_charge_rejects_negative_components() -> None:
    base = dict(
        idempotency_key="charge-bad",
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        stage_id="stage-1",
        source_authority="risk.test",
        marked_unrealized_pnl_cents=0,
        expected_stage_loss_state_version=1,
        as_of=T0,
    )
    with pytest.raises(ValidationError):
        StageLossChargeRequest(
            realized_market_losses_ex_fees_cents=-1,
            cumulative_fees_and_taxes_cents=0,
            incremental_pending_stress_beyond_mark_cents=0,
            **base,
        )
    with pytest.raises(ValidationError):
        StageLossChargeRequest(
            realized_market_losses_ex_fees_cents=0,
            cumulative_fees_and_taxes_cents=-1,
            incremental_pending_stress_beyond_mark_cents=0,
            **base,
        )
    with pytest.raises(ValidationError):
        StageLossChargeRequest(
            realized_market_losses_ex_fees_cents=0,
            cumulative_fees_and_taxes_cents=0,
            incremental_pending_stress_beyond_mark_cents=-1,
            **base,
        )


def test_profit_and_rebound_never_replenish_consumed_budget(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1", quantity=1_000)
    activate_budget(repository, step=2, frozen_budget_cents=500_000)

    # Mark the position down 50%: 500_000 cents of unrealized loss.
    valuation(repository, step=3, marks={SECURITY: 50_000_000})
    receipt, _ = charge_loss(
        repository, step=4, key="charge-dd", unrealized_pnl=-500_000
    )
    assert receipt.consumed_after_cents == 500_000
    assert receipt.state is StageLossLatchState.STAGE_LOSS_HALTED

    # A full rebound: the unrealized profit produces a zero charge and the
    # consumed budget is never refunded; the halt is permanent.
    valuation(repository, step=5, marks={SECURITY: 120_000_000})
    receipt, snapshot = charge_loss(
        repository, step=6, key="charge-rebound", unrealized_pnl=200_000
    )
    assert receipt.instantaneous_charge_cents == 0
    assert receipt.consumed_after_cents == 500_000
    assert receipt.state is StageLossLatchState.STAGE_LOSS_HALTED
    latch = stage_latch(repository, "prog-1", "eline-1", "stage-1")
    assert latch.state is StageLossLatchState.STAGE_LOSS_HALTED
    assert snapshot.stage_loss_latches[0].state is (
        StageLossLatchState.STAGE_LOSS_HALTED
    )


def test_relabel_and_epoch_changes_never_reset_stage_loss(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1", quantity=1_000)
    activate_budget(repository, step=2, frozen_budget_cents=1_000_000)
    charge_loss(repository, step=3, key="charge-1", realized=400_000)
    before = stage_latch(repository, "prog-1", "eline-1", "stage-1")

    # A governance risk epoch never touches stage-loss consumption.
    audited = repository.capital_risk_snapshot(_moment(4)).as_observed_nav_cents
    repository.start_risk_epoch(
        RiskEpochRequest(
            idempotency_key="epoch-2",
            risk_epoch=2,
            audited_nav_cents=audited,
            source_authority="governance.test",
            effective_at=_moment(5),
            as_of=_moment(5),
        )
    )
    after = stage_latch(repository, "prog-1", "eline-1", "stage-1")
    assert after.consumed_cents == before.consumed_cents == 400_000
    assert after.frozen_budget_cents == before.frozen_budget_cents

    # Re-activating the same identity under a new budget id (a relabel) is
    # rejected; the original frozen budget is the only truth.
    with pytest.raises(CapitalConflict) as excinfo:
        activate_budget(
            repository,
            step=6,
            budget_id="budget-relabelled",
            key="activate-relabel",
            frozen_budget_cents=2_000_000,
        )
    assert excinfo.value.code == "stage_loss_budget_conflict"
    assert (
        stage_latch(repository, "prog-1", "eline-1", "stage-1").consumed_cents
        == 400_000
    )


def test_stage_loss_requires_a_frozen_budget(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    with pytest.raises(CapitalConflict) as excinfo:
        charge_loss(repository, step=1, key="charge-no-budget", realized=100)
    assert excinfo.value.code == "stage_loss_budget_unknown"


def test_stage_loss_cas_and_idempotency(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    activate_budget(repository, step=1, frozen_budget_cents=10_000)

    # A stale stage-loss version fails the compare-and-swap.
    stale_version = repository.capital_risk_snapshot(
        _moment(2)
    ).stage_loss_state_version
    charge_loss(repository, step=2, key="charge-1", realized=100)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_stage_loss(
            StageLossChargeRequest(
                idempotency_key="charge-2",
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
                stage_id="stage-1",
                source_authority="risk.test",
                realized_market_losses_ex_fees_cents=100,
                cumulative_fees_and_taxes_cents=0,
                marked_unrealized_pnl_cents=0,
                incremental_pending_stress_beyond_mark_cents=0,
                expected_stage_loss_state_version=stale_version,
                as_of=_moment(3),
            )
        )
    assert excinfo.value.code == "stage_loss_version_mismatch"

    # Identical retry of the committed charge converges without growth.
    snapshot_before = repository.capital_risk_snapshot(_moment(3))
    receipt, snapshot = charge_loss(
        repository, step=3, key="charge-1", realized=100
    )
    assert receipt.consumed_after_cents == 100
    assert snapshot.capital_version == snapshot_before.capital_version
    assert (
        snapshot.stage_loss_state_version == snapshot_before.stage_loss_state_version
    )

    # Same idempotency key with divergent content conflicts.
    with pytest.raises(CapitalConflict) as excinfo:
        charge_loss(repository, step=4, key="charge-1", realized=999)
    assert excinfo.value.code == "payload_conflict"


def test_stage_loss_halt_latches_at_the_budget_and_is_permanent(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    activate_budget(repository, step=1, frozen_budget_cents=1_000)
    receipt, _ = charge_loss(repository, step=2, key="charge-1", realized=1_000)
    assert receipt.consumed_after_cents == 1_000
    assert receipt.state is StageLossLatchState.STAGE_LOSS_HALTED

    # Further charges still record (audit) but the latch never clears and
    # consumption never retreats.
    receipt, _ = charge_loss(repository, step=3, key="charge-2", realized=1)
    assert receipt.consumed_after_cents == 1_000
    assert receipt.state is StageLossLatchState.STAGE_LOSS_HALTED
    assert (
        stage_latch(repository, "prog-1", "eline-1", "stage-1").state
        is StageLossLatchState.STAGE_LOSS_HALTED
    )

    # Overshooting the budget also halts at exactly the frozen ceiling.
    assert receipt.remaining_budget_cents == 0


def test_per_stage_and_global_consumption_tracked_separately(
    repository: CapitalRepository,
) -> None:
    from src.screening.offensive.v3.capital.risk_snapshot import (
        GLOBAL_STAGE_LOSS_IDENTITY,
    )

    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1", quantity=100)
    activate_budget(repository, step=2, frozen_budget_cents=100_000)
    activate_budget(
        repository,
        step=3,
        budget_id="budget-global",
        key="activate-global",
        program=GLOBAL_STAGE_LOSS_IDENTITY[0],
        lineage=GLOBAL_STAGE_LOSS_IDENTITY[1],
        stage=GLOBAL_STAGE_LOSS_IDENTITY[2],
        frozen_budget_cents=200_000,
    )

    # An attributed charge consumes only the stage budget.
    charge_loss(repository, step=4, key="charge-stage", realized=30_000)
    assert (
        stage_latch(repository, "prog-1", "eline-1", "stage-1").consumed_cents
        == 30_000
    )
    assert (
        stage_latch(repository, *GLOBAL_STAGE_LOSS_IDENTITY).consumed_cents == 0
    )

    # Unattributed portfolio facts (a fee) consume the global budget only:
    # the stage budget is untouched by facts it cannot be charged to.
    receipt, _ = repository.record_fee_revision(
        FeeRevisionRequest(
            fill_execution_id="exec-1",
            revision=1,
            fee_policy=POLICY_V1,
            source_authority="broker.test",
            effective_at=_moment(5),
            as_of=_moment(5) + timedelta(seconds=1),
            expected_stream_version=repository.stream_version(),
        )
    )
    assert receipt.total_cents > 0
    global_latch = stage_latch(repository, *GLOBAL_STAGE_LOSS_IDENTITY)
    assert global_latch.consumed_cents >= receipt.total_cents
    assert (
        stage_latch(repository, "prog-1", "eline-1", "stage-1").consumed_cents
        == 30_000
    )


def test_fees_and_marks_consume_global_budget_in_the_same_transaction(
    repository: CapitalRepository,
) -> None:
    from src.screening.offensive.v3.capital.risk_snapshot import (
        GLOBAL_STAGE_LOSS_IDENTITY,
    )

    genesis(repository)
    entry_fill(
        repository,
        step=1,
        execution_id="exec-1",
        price_micros=100_000_000,
        quantity=1_000,
    )
    activate_budget(
        repository,
        step=2,
        budget_id="budget-global",
        key="activate-global",
        program=GLOBAL_STAGE_LOSS_IDENTITY[0],
        lineage=GLOBAL_STAGE_LOSS_IDENTITY[1],
        stage=GLOBAL_STAGE_LOSS_IDENTITY[2],
        frozen_budget_cents=5_000_000,
    )

    # Mark the position down 400_000 cents: the recompute inside the
    # valuation transaction consumes the global budget in the SAME
    # transaction (no async catch-up).
    valuation(repository, step=3, marks={SECURITY: 60_000_000})
    latch = stage_latch(repository, *GLOBAL_STAGE_LOSS_IDENTITY)
    assert latch.consumed_cents == 4_000_000

    # A rebound never refunds the global budget either.
    valuation(repository, step=4, marks={SECURITY: 110_000_000})
    latch = stage_latch(repository, *GLOBAL_STAGE_LOSS_IDENTITY)
    assert latch.consumed_cents == 4_000_000


# ---------------------------------------------------------------------------
# Snapshot sealing: close_risk_snapshot
# ---------------------------------------------------------------------------


def test_close_risk_snapshot_seals_one_append_only_record(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1")
    valuation(repository, step=2, marks={SECURITY: 100_000_000})

    receipt, snapshot = repository.close_risk_snapshot(
        CloseRiskSnapshotRequest(
            session=date(2026, 8, 3),
            as_of=_moment(3),
            source_authority="gateway.test",
            authorized_mark_authorities=(MARK_AUTHORITY,),
        )
    )

    assert receipt.session == date(2026, 8, 3)
    assert receipt.risk_snapshot_id == snapshot.risk_snapshot_id
    assert receipt.snapshot_content_hash == snapshot.content_hash()
    assert receipt.capital_version == snapshot.capital_version
    assert receipt.entry_scaling_multiplier_ppm == 1_000_000
    assert receipt.already_sealed is False

    # The seal is an append-only record with the content-hash fingerprint.
    raw = sqlite3.connect(repository.database_path)
    try:
        rows = raw.execute(
            "SELECT portfolio_id, session, risk_snapshot_id,"
            " snapshot_content_hash, snapshot_json, capital_version"
            " FROM risk_snapshot_seals"
        ).fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute("DELETE FROM risk_snapshot_seals")
    finally:
        raw.close()
    assert len(rows) == 1
    portfolio, session, snapshot_id, content_hash, snapshot_json, version = rows[0]
    assert portfolio == "pf-test"
    assert session == "2026-08-03"
    assert snapshot_id == snapshot.risk_snapshot_id
    assert content_hash == snapshot.content_hash()
    assert version == snapshot.capital_version
    # The stored payload round-trips through the frozen contract.
    from src.screening.offensive.v3.contracts import CapitalRiskSnapshot

    assert (
        CapitalRiskSnapshot.model_validate_json(snapshot_json).content_hash()
        == content_hash
    )


def test_close_risk_snapshot_identical_retry_converges(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    valuation(repository, step=1, marks={})
    request = CloseRiskSnapshotRequest(
        session=date(2026, 8, 3),
        as_of=_moment(2),
        source_authority="gateway.test",
        authorized_mark_authorities=(MARK_AUTHORITY,),
    )
    receipt, snapshot = repository.close_risk_snapshot(request)
    retry_receipt, retry_snapshot = repository.close_risk_snapshot(request)
    assert retry_receipt.risk_snapshot_id == receipt.risk_snapshot_id
    assert retry_receipt.snapshot_content_hash == receipt.snapshot_content_hash
    assert retry_receipt.already_sealed is True
    assert retry_snapshot == snapshot
    assert retry_receipt.capital_version == repository.capital_version()

    raw = sqlite3.connect(repository.database_path)
    try:
        count = raw.execute(
            "SELECT COUNT(*) FROM risk_snapshot_seals"
        ).fetchone()[0]
    finally:
        raw.close()
    assert count == 1


def test_close_risk_snapshot_divergent_close_conflicts(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1")
    valuation(repository, step=2, marks={SECURITY: 100_000_000})
    repository.close_risk_snapshot(
        CloseRiskSnapshotRequest(
            session=date(2026, 8, 3),
            as_of=_moment(3),
            source_authority="gateway.test",
            authorized_mark_authorities=(MARK_AUTHORITY,),
        )
    )

    # Capital truth moved after the seal: closing the SAME session again is a
    # divergent close and must conflict, never overwrite.
    valuation(repository, step=4, marks={SECURITY: 101_000_000})
    with pytest.raises(CapitalConflict) as excinfo:
        repository.close_risk_snapshot(
            CloseRiskSnapshotRequest(
                session=date(2026, 8, 3),
                as_of=_moment(5),
                source_authority="gateway.test",
                authorized_mark_authorities=(MARK_AUTHORITY,),
            )
        )
    assert excinfo.value.code == "risk_snapshot_close_conflict"

    # A different session may seal its own snapshot.
    receipt, _ = repository.close_risk_snapshot(
        CloseRiskSnapshotRequest(
            session=date(2026, 8, 4),
            as_of=_moment(5),
            source_authority="gateway.test",
            authorized_mark_authorities=(MARK_AUTHORITY,),
        )
    )
    assert receipt.session == date(2026, 8, 4)


def test_close_risk_snapshot_rejects_invalid_marks(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1")
    with pytest.raises(CapitalConflict) as excinfo:
        repository.close_risk_snapshot(
            CloseRiskSnapshotRequest(
                session=date(2026, 8, 3),
                as_of=_moment(2),
                source_authority="gateway.test",
                authorized_mark_authorities=(MARK_AUTHORITY,),
            )
        )
    assert excinfo.value.code == "valuation_unknown"


def test_close_receipt_carries_drawdown_scaling_multiplier(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1, execution_id="exec-1", quantity=1_000)
    # 12.5% drawdown: multiplier halfway to zero.
    valuation(repository, step=2, marks={SECURITY: 87_500_000})
    receipt, snapshot = repository.close_risk_snapshot(
        CloseRiskSnapshotRequest(
            session=date(2026, 8, 3),
            as_of=_moment(3),
            source_authority="gateway.test",
            authorized_mark_authorities=(MARK_AUTHORITY,),
        )
    )
    assert snapshot.active_epoch_drawdown_ppm == 125_000
    assert receipt.entry_scaling_multiplier_ppm == 500_000


# ---------------------------------------------------------------------------
# Worst-case exposure: unknown/ambiguous risk is never under-reported
# ---------------------------------------------------------------------------


def test_unattributed_fill_exposure_is_preserved_and_flagged(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(
        repository,
        step=1,
        execution_id="exec-mystery",
        attribution=None,
        position_lineage_id=None,
        price_micros=100_000_000,
        quantity=100,
    )
    valuation(repository, step=2, marks={SECURITY: 100_000_000})
    snapshot = repository.build_capital_risk_snapshot(build_request(_moment(3)))

    # The unattributed lot stays in the snapshot at its only known
    # non-optimistic value (cost basis) and halts reconciliation.
    assert snapshot.unattributed_risk_cents == 1_000_000
    assert snapshot.reconciliation_latch is (
        ReconciliationLatchState.RECONCILIATION_HALT
    )
    # It counts toward global and portfolio gross exactly once.
    global_bucket = next(
        exposure
        for exposure in snapshot.exposures
        if exposure.scope is ExposureScope.GLOBAL
    )
    portfolio_bucket = next(
        exposure
        for exposure in snapshot.exposures
        if exposure.scope is ExposureScope.PORTFOLIO
    )
    assert global_bucket.unattributed_risk_cents == 1_000_000
    assert portfolio_bucket.unattributed_risk_cents == 1_000_000
    assert snapshot.total_gross_exposure_cents == (
        global_bucket.position_marked_gross_cents + 1_000_000
    )


def test_ambiguous_submission_keeps_worst_case_reserve_live(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    repository.reserve_entry(
        ReserveEntryRequest(
            source_id="src-ambiguous",
            research_program_id="prog-1",
            economic_lineage_id="eline-1",
            stage_id="stage-1",
            reserved_entry_gross_cents=2_000_000,
            expected_stream_version=repository.stream_version(),
            as_of=_moment(1),
        )
    )
    # The ambiguous submission cannot release the reserve...
    with pytest.raises(CapitalConflict) as excinfo:
        repository.release_reserve(
            ReserveReleaseRequest(
                source_id="src-ambiguous",
                reason=ReserveReleaseReason.SUBMISSION_AMBIGUOUS,
                expected_stream_version=repository.stream_version(),
                as_of=_moment(2),
            )
        )
    assert excinfo.value.code == "submission_ambiguous_worst_case_retained"

    # ...so the snapshot still carries the full worst-case reserved exposure.
    snapshot = repository.build_capital_risk_snapshot(build_request(_moment(3)))
    assert snapshot.reserved_cash_cents == 2_000_000
    assert snapshot.restricted_cash_cents == 2_000_000
    assert snapshot.entry_reserves[0].reserved_entry_gross_cents == 2_000_000
    assert snapshot.total_gross_exposure_cents == 2_000_000


def test_live_order_and_pending_stress_extension_points_are_empty_and_documented(
    repository: CapitalRepository,
) -> None:
    # Kernel revision 2 has no Plan 04 order registry or pending-stress
    # store yet; the derived snapshot must expose them as empty tuples (never
    # fabricated), while ambiguous submissions stay covered by worst-case
    # reserves (tested above).
    genesis(repository)
    valuation(repository, step=1, marks={})
    snapshot = repository.build_capital_risk_snapshot(build_request(_moment(2)))
    assert snapshot.live_orders == ()
    assert snapshot.pending_stress_components == ()
    assert snapshot.corporate_action_risk_components == ()


# ---------------------------------------------------------------------------
# Property test: generated fill/mark/reserve/charge sequences
# ---------------------------------------------------------------------------


GLOBAL_IDENTITY = ("__PORTFOLIO_GLOBAL__",) * 3
STAGE_IDENTITY = ("prog-1", "eline-1", "stage-1")

PROPERTY_STAGE_BUDGET_CENTS = 10_000_000
PROPERTY_GLOBAL_BUDGET_CENTS = 20_000_000


@dataclass
class StageLossModel:
    """Pure-python mirror of the Task 5 stage-loss projections."""

    fee_paid_cents: int = 0
    basis_cents: int = 0
    quantity: int = 0
    # The newest valuation's mark for SECURITY; None when the newest
    # valuation did not mark it (no valuation yet, or a liquid valuation).
    marked_price_micros: int | None = None
    consumed: dict = field(default_factory=dict)
    halted: dict = field(default_factory=dict)
    budgets: dict = field(
        default_factory=lambda: {
            STAGE_IDENTITY: PROPERTY_STAGE_BUDGET_CENTS,
            GLOBAL_IDENTITY: PROPERTY_GLOBAL_BUDGET_CENTS,
        }
    )
    # Genesis confirms the initial NAV observation and water mark.
    nav_history: list = field(default_factory=lambda: [GENESIS_CASH_CENTS])
    ever_risk_halted: bool = False

    def marked_gross_cents(self) -> int:
        if self.marked_price_micros is None or self.quantity == 0:
            return 0
        return round_half_even_div(
            self.quantity * self.marked_price_micros, MICROS_PER_CENT
        )

    def nav_cents(self, cash_cents: int) -> int:
        return cash_cents + self.marked_gross_cents()

    def floor_charge_cents(self) -> int:
        # Derived global floor: cumulative fees + max(0, -unrealized). The
        # unrealized component is measurable only while the newest valuation
        # marks SECURITY; unknown marks block via snapshot rejection, they do
        # not fabricate a loss charge.
        if self.quantity == 0 or self.marked_price_micros is None:
            return self.fee_paid_cents
        unrealized = self.marked_gross_cents() - self.basis_cents
        return self.fee_paid_cents + max(0, -unrealized)

    def apply_consumption(self, identity: tuple, charge_cents: int) -> None:
        budget = self.budgets[identity]
        consumed = max(self.consumed.get(identity, 0), charge_cents)
        self.consumed[identity] = consumed
        self.halted[identity] = consumed >= budget

    def confirm_nav(self, cash_cents: int) -> None:
        nav = self.nav_cents(cash_cents)
        self.nav_history.append(nav)
        hwm = max(self.nav_history)
        if hwm > 0 and (hwm - nav) * 1_000_000 // hwm >= DRAWDOWN_HALT_PPM:
            self.ever_risk_halted = True


def _model_check(repository: CapitalRepository, model: StageLossModel) -> None:
    for identity, budget in model.budgets.items():
        latch = stage_latch(repository, *identity)
        assert latch.frozen_budget_cents == budget
        expected_consumed = model.consumed.get(identity, 0)
        assert latch.consumed_cents == expected_consumed
        expected_state = (
            StageLossLatchState.STAGE_LOSS_HALTED
            if model.halted.get(identity, False)
            else StageLossLatchState.CLEAR
        )
        assert latch.state is expected_state

    snapshot = repository.capital_risk_snapshot(_moment(99))
    if model.ever_risk_halted:
        assert snapshot.risk_latch is RiskLatchState.RISK_HALTED
    else:
        assert snapshot.risk_latch is RiskLatchState.CLEAR


@st.composite
def risk_operation_sequences(draw):
    model = StageLossModel()
    cash_cents = GENESIS_CASH_CENTS
    ops: list[tuple[str, dict]] = []
    steps = draw(st.integers(min_value=4, max_value=12))

    for index in range(steps):
        actions: list[str] = ["charge_stage", "charge_global"]
        if cash_cents >= 2_000_000:
            actions.append("entry_fill")
        if model.quantity > 0 or index > 0:
            actions.append("valuation")
        if cash_cents >= 1_000_000:
            actions.append("reserve")

        name = draw(st.sampled_from(sorted(actions)))

        if name == "entry_fill":
            quantity = draw(st.integers(min_value=100, max_value=500))
            price_micros = draw(
                st.integers(min_value=1_000_000, max_value=100_000_000)
            )
            gross = round_half_even_div(
                quantity * price_micros, MICROS_PER_CENT
            )
            if gross > cash_cents:
                continue
            cash_cents -= gross
            model.quantity += quantity
            model.basis_cents += gross
            # A fill re-runs the same-transaction stage-loss recompute with
            # worst-case marks; then the global floor may only grow.
            model.apply_consumption(
                GLOBAL_IDENTITY, model.floor_charge_cents()
            )
            ops.append(
                (
                    "entry_fill",
                    {
                        "execution_id": f"exec-{index}",
                        "quantity": quantity,
                        "price_micros": price_micros,
                    },
                )
            )
        elif name == "valuation":
            price_micros = draw(
                st.integers(min_value=1_000_000, max_value=150_000_000)
            )
            # A valuation marks SECURITY only while the position is open; a
            # liquid valuation records no marks.
            model.marked_price_micros = (
                price_micros if model.quantity > 0 else None
            )
            model.apply_consumption(
                GLOBAL_IDENTITY, model.floor_charge_cents()
            )
            model.confirm_nav(cash_cents)
            ops.append(("valuation", {"price_micros": price_micros}))
        elif name == "reserve":
            cents = draw(
                st.integers(min_value=1, max_value=min(cash_cents, 1_000_000))
            )
            ops.append(("reserve", {"cents": cents, "index": index}))
        elif name == "charge_stage":
            charge = draw(st.integers(min_value=0, max_value=5_000_000))
            model.apply_consumption(STAGE_IDENTITY, charge)
            ops.append(("charge_stage", {"cents": charge, "index": index}))
        elif name == "charge_global":
            charge = draw(st.integers(min_value=0, max_value=5_000_000))
            model.apply_consumption(GLOBAL_IDENTITY, charge)
            ops.append(("charge_global", {"cents": charge, "index": index}))

    return model, cash_cents, ops


def _replay_risk_op(
    repository: CapitalRepository, name: str, params: dict, step: int
) -> None:
    if name == "entry_fill":
        entry_fill(
            repository,
            step=step,
            execution_id=params["execution_id"],
            price_micros=params["price_micros"],
            quantity=params["quantity"],
        )
    elif name == "valuation":
        marks = (
            {SECURITY: params["price_micros"]}
            if repository.capital_risk_snapshot(_moment(step)).positions
            else {}
        )
        valuation(repository, step=step, marks=marks)
    elif name == "reserve":
        source_id = f"src-prop-{params['index']}"
        repository.reserve_entry(
            ReserveEntryRequest(
                source_id=source_id,
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
                stage_id="stage-1",
                reserved_entry_gross_cents=params["cents"],
                expected_stream_version=repository.stream_version(),
                as_of=_moment(step),
            )
        )
        repository.release_reserve(
            ReserveReleaseRequest(
                source_id=source_id,
                reason=ReserveReleaseReason.CANCEL_CONFIRMED,
                expected_stream_version=repository.stream_version(),
                as_of=_moment(step) + timedelta(seconds=30),
            )
        )
    elif name in ("charge_stage", "charge_global"):
        identity = STAGE_IDENTITY if name == "charge_stage" else GLOBAL_IDENTITY
        charge_loss(
            repository,
            step=step,
            key=f"prop-{name}-{params['index']}",
            realized=params["cents"],
            program=identity[0],
            lineage=identity[1],
            stage=identity[2],
        )


@settings(
    deadline=None,
    max_examples=25,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(data=st.data())
def test_property_stage_loss_monotonicity_and_conservation(
    data, tmp_path: Path
) -> None:
    model, _cash_cents, ops = data.draw(risk_operation_sequences())
    repository = CapitalRepository.initialize(
        tmp_path / f"capital-{uuid.uuid4().hex}.sqlite3"
    )
    genesis(repository)
    activate_budget(
        repository,
        step=1,
        frozen_budget_cents=PROPERTY_STAGE_BUDGET_CENTS,
        key="activate-stage",
    )
    activate_budget(
        repository,
        step=2,
        budget_id="budget-global",
        key="activate-global",
        program=GLOBAL_IDENTITY[0],
        lineage=GLOBAL_IDENTITY[1],
        stage=GLOBAL_IDENTITY[2],
        frozen_budget_cents=PROPERTY_GLOBAL_BUDGET_CENTS,
    )

    consumed_history: dict[tuple, list[int]] = {
        STAGE_IDENTITY: [],
        GLOBAL_IDENTITY: [],
    }
    step = 2
    for name, params in ops:
        step += 1
        _replay_risk_op(repository, name, params, step)
        for identity in consumed_history:
            latch = stage_latch(repository, *identity)
            history = consumed_history[identity]
            # Monotone non-decreasing consumption at EVERY step.
            assert not history or latch.consumed_cents >= history[-1]
            history.append(latch.consumed_cents)
            assert (latch.consumed_cents >= latch.frozen_budget_cents) == (
                latch.state is StageLossLatchState.STAGE_LOSS_HALTED
            )

    _model_check(repository, model)
    # The Task 2 conservation identity still balances after every generated
    # stage-loss fact (stage loss never creates or destroys capital).
    repository.assert_conservation()
