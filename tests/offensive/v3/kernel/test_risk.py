"""Plan 04 Task 1: single-pass complete portfolio risk."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.capital import (
    CapitalRiskSnapshot,
    ExposureScope,
    RiskExposureBucket,
    StageLossLatchSnapshot,
)
from src.screening.offensive.v3.contracts.risk import (
    ReconciliationLatchState,
    RiskLatchState,
    RiskSnapshotCompleteness,
    RiskSnapshotFreshness,
    StageLossLatchState,
)
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    RiskDecision,
    RiskDecisionStatus,
)
from src.screening.offensive.v3.kernel.risk import (
    MULTIPLIER_SCALE,
    KernelRiskError,
    apply_portfolio_risk_once,
    drawdown_multiplier_ppm,
    evaluate_portfolio_risk,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)


def _bucket(scope: ExposureScope, **identities) -> RiskExposureBucket:
    return RiskExposureBucket(
        scope=scope,
        portfolio_id=identities.get("portfolio_id"),
        research_program_id=identities.get("research_program_id"),
        economic_lineage_id=identities.get("economic_lineage_id"),
        stage_id=identities.get("stage_id"),
        position_marked_gross_cents=0,
        live_order_leaves_gross_cents=0,
        reserved_entry_gross_cents=0,
        pending_stress_cents=0,
        corporate_action_pending_risk_cents=0,
        unattributed_risk_cents=0,
        total_gross_cents=0,
    )


def _stage_latch(
    state: StageLossLatchState = StageLossLatchState.CLEAR,
    consumed: int = 1_000,
) -> StageLossLatchSnapshot:
    return StageLossLatchSnapshot(
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        stage_id="stage-1",
        stage_loss_budget_id="budget-1",
        frozen_budget_cents=100_000,
        consumed_cents=consumed,
        stage_loss_version=1,
        state=state,
    )


def _snapshot(**overrides) -> CapitalRiskSnapshot:
    values = {
        "risk_snapshot_id": "snap-1",
        "portfolio_id": "paper-v3",
        "broker_account_id": None,
        "base_currency": "CNY",
        "mode": ExecutionMode.DAILY_BAR_PROXY,
        "as_of": NOW,
        "valid_until": NOW + timedelta(hours=1),
        "freshness": RiskSnapshotFreshness.FRESH,
        "completeness": RiskSnapshotCompleteness.COMPLETE,
        "available_cash_cents": 1_000_000,
        "restricted_cash_cents": 0,
        "unsettled_cash_cents": 0,
        "cash_receivable_cents": 0,
        "cash_payable_cents": 0,
        "subscription_suspense_cents": 0,
        "redemption_suspense_cents": 0,
        "reserved_cash_cents": 0,
        "issued_unit_quanta": 1_000_000,
        "pending_redeemed_unit_quanta": 0,
        "positions": (),
        "live_orders": (),
        "entry_reserves": (),
        "pending_stress_components": (),
        "corporate_action_risk_components": (),
        "unattributed_risk_cents": 0,
        "exposures": (
            _bucket(ExposureScope.GLOBAL),
            _bucket(
                ExposureScope.PORTFOLIO, portfolio_id="paper-v3"
            ),
        ),
        "total_gross_exposure_cents": 0,
        "as_observed_nav_cents": 1_000_000,
        "lifetime_high_water_mark_cents": 1_000_000,
        "active_epoch_high_water_mark_cents": 1_000_000,
        "lifetime_drawdown_ppm": 0,
        "active_epoch_drawdown_ppm": 0,
        "risk_latch": RiskLatchState.CLEAR,
        "stage_loss_latches": (_stage_latch(),),
        "reconciliation_latch": ReconciliationLatchState.CLEAR,
        "policy_activation_hash": "a" * 64,
        "policy_epoch": 1,
        "authority_epoch": 1,
        "risk_epoch": 1,
        "registry_epoch": 1,
        "authorization_id": "auth-1",
        "authorization_version": 1,
        "stage_loss_state_version": 1,
        "writer_fencing_epoch": 1,
        "capital_version": 1,
        "schema_major": 2,
    }
    values.update(overrides)
    return CapitalRiskSnapshot(**values)


def _nav_for_drawdown(high_water_mark_cents: int, ppm: int) -> int:
    return high_water_mark_cents - (high_water_mark_cents * ppm) // 1_000_000


@pytest.mark.parametrize(
    ("drawdown_ppm", "expected"),
    [
        (0, MULTIPLIER_SCALE),
        (99_900, MULTIPLIER_SCALE),  # 9.99%: no scaling
        (100_000, MULTIPLIER_SCALE),  # exactly 10%: boundary, no scaling
        (125_000, 500_000),  # 12.5%: half
        (149_900, 2_000),  # 14.99%: almost zero
        (150_000, 0),  # 15%: fully scaled out
        (300_000, 0),
    ],
)
def test_drawdown_multiplier_tiers(drawdown_ppm: int, expected: int) -> None:
    assert drawdown_multiplier_ppm(drawdown_ppm) == expected


def test_negative_drawdown_is_typed_rejected() -> None:
    with pytest.raises(KernelRiskError) as excinfo:
        drawdown_multiplier_ppm(-1)
    assert excinfo.value.code == "negative_drawdown"


def test_complete_fresh_capital_passes() -> None:
    nav = _nav_for_drawdown(1_000_000, 125_000)
    decision = evaluate_portfolio_risk(
        capital=_snapshot(
            as_observed_nav_cents=nav,
            lifetime_high_water_mark_cents=1_000_000,
            active_epoch_high_water_mark_cents=1_000_000,
            lifetime_drawdown_ppm=125_000,
            active_epoch_drawdown_ppm=125_000,
        ),
        trusted_at=NOW + timedelta(minutes=5),
    )
    assert decision.status is RiskDecisionStatus.PASS
    assert decision.block_reason is None
    assert decision.drawdown_multiplier_ppm == 500_000


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"freshness": RiskSnapshotFreshness.STALE}, BlockReason.STALE_CAPITAL),
        (
            {"freshness": RiskSnapshotFreshness.UNKNOWN},
            BlockReason.UNKNOWN_CAPITAL_FRESHNESS,
        ),
        (
            {"completeness": RiskSnapshotCompleteness.INCOMPLETE},
            BlockReason.UNKNOWN_EXPOSURE,
        ),
        (
            {"completeness": RiskSnapshotCompleteness.UNKNOWN},
            BlockReason.UNKNOWN_EXPOSURE,
        ),
        (
            {
                "as_observed_nav_cents": 0,
                "lifetime_drawdown_ppm": 1_000_000,
                "active_epoch_drawdown_ppm": 1_000_000,
                "risk_latch": RiskLatchState.RISK_HALTED,
            },
            BlockReason.NEGATIVE_NAV,
        ),
        (
            {"risk_latch": RiskLatchState.RISK_HALTED},
            BlockReason.RISK_HALTED,
        ),
        (
            {
                "reconciliation_latch": (
                    ReconciliationLatchState.RECONCILIATION_HALT
                )
            },
            BlockReason.RECONCILIATION_HALTED,
        ),
        (
            {
                "stage_loss_latches": (
                    _stage_latch(
                        state=StageLossLatchState.STAGE_LOSS_HALTED,
                        consumed=100_000,
                    ),
                )
            },
            BlockReason.STAGE_LOSS_HALTED,
        ),
    ],
)
def test_risk_blocks_are_typed_and_never_default(
    overrides: dict, reason: BlockReason
) -> None:
    decision = evaluate_portfolio_risk(
        capital=_snapshot(**overrides),
        trusted_at=NOW + timedelta(minutes=5),
    )
    assert decision.status is RiskDecisionStatus.BLOCKED
    assert decision.block_reason is reason
    assert decision.drawdown_multiplier_ppm == 0


def test_expired_valid_until_blocks_as_stale_capital() -> None:
    decision = evaluate_portfolio_risk(
        capital=_snapshot(),
        trusted_at=NOW + timedelta(hours=2),  # beyond valid_until
    )
    assert decision.status is RiskDecisionStatus.BLOCKED
    assert decision.block_reason is BlockReason.STALE_CAPITAL


def test_same_multiplier_scales_targets_and_ceiling_once() -> None:
    decision = RiskDecision(
        status=RiskDecisionStatus.PASS,
        block_reason=None,
        drawdown_multiplier_ppm=500_000,
        risk_adjustment_count=0,
    )
    adjusted = apply_portfolio_risk_once(
        unscaled_lineage_targets={
            "eline-b": 50_000,
            "eline-a": 100_000,
        },
        unscaled_portfolio_gross_cap_cents=200_000,
        risk_decision=decision,
    )
    # One application, one count; both lineage targets and the portfolio
    # ceiling are scaled by the SAME multiplier before capacity/lot
    # rounding. Canonical lineage order is deterministic.
    assert adjusted.risk_adjustment_count == 1
    assert adjusted.adjusted_lineage_gross_cents == (
        ("eline-a", 50_000),
        ("eline-b", 25_000),
    )
    assert adjusted.adjusted_portfolio_gross_cap_cents == 100_000


def test_full_halt_multiplier_zeroes_everything_once() -> None:
    decision = RiskDecision(
        status=RiskDecisionStatus.PASS,
        block_reason=None,
        drawdown_multiplier_ppm=0,
        risk_adjustment_count=0,
    )
    adjusted = apply_portfolio_risk_once(
        unscaled_lineage_targets={"eline-a": 100_000},
        unscaled_portfolio_gross_cap_cents=200_000,
        risk_decision=decision,
    )
    assert adjusted.adjusted_lineage_gross_cents == (("eline-a", 0),)
    assert adjusted.adjusted_portfolio_gross_cap_cents == 0
    assert adjusted.risk_adjustment_count == 1


def test_blocked_decision_cannot_be_applied() -> None:
    blocked = RiskDecision(
        status=RiskDecisionStatus.BLOCKED,
        block_reason=BlockReason.RISK_HALTED,
        drawdown_multiplier_ppm=0,
        risk_adjustment_count=0,
    )
    with pytest.raises(KernelRiskError) as excinfo:
        apply_portfolio_risk_once(
            unscaled_lineage_targets={"eline-a": 100_000},
            unscaled_portfolio_gross_cap_cents=200_000,
            risk_decision=blocked,
        )
    assert excinfo.value.code == "risk_blocked"


def test_double_scaling_is_structurally_excluded() -> None:
    """Applying risk to ALREADY-ADJUSTED values is a caller bug; the API
    only consumes unscaled inputs, and every result reports exactly one
    adjustment. Re-running on the same unscaled input is byte-identical."""

    decision = RiskDecision(
        status=RiskDecisionStatus.PASS,
        block_reason=None,
        drawdown_multiplier_ppm=500_000,
        risk_adjustment_count=0,
    )
    first = apply_portfolio_risk_once(
        unscaled_lineage_targets={"eline-a": 100_000},
        unscaled_portfolio_gross_cap_cents=200_000,
        risk_decision=decision,
    )
    second = apply_portfolio_risk_once(
        unscaled_lineage_targets={"eline-a": 100_000},
        unscaled_portfolio_gross_cap_cents=200_000,
        risk_decision=decision,
    )
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.risk_adjustment_count == second.risk_adjustment_count == 1
    # The adjusted output never feeds back as an unscaled input: feeding
    # the ADJUSTED value through again is a different (wrong) computation
    # producing different canonical bytes, which the gateway's replay
    # check would reject.
    wrong = apply_portfolio_risk_once(
        unscaled_lineage_targets={
            "eline-a": first.adjusted_lineage_gross_cents[0][1]
        },
        unscaled_portfolio_gross_cap_cents=(
            first.adjusted_portfolio_gross_cap_cents
        ),
        risk_decision=decision,
    )
    assert wrong.canonical_bytes() != first.canonical_bytes()
    assert wrong.risk_adjustment_count == 1


def test_unknown_or_negative_targets_fail_closed() -> None:
    decision = RiskDecision(
        status=RiskDecisionStatus.PASS,
        block_reason=None,
        drawdown_multiplier_ppm=MULTIPLIER_SCALE,
        risk_adjustment_count=0,
    )
    with pytest.raises(KernelRiskError) as excinfo:
        apply_portfolio_risk_once(
            unscaled_lineage_targets={"eline-a": -1},
            unscaled_portfolio_gross_cap_cents=100_000,
            risk_decision=decision,
        )
    assert excinfo.value.code == "unknown_lineage_target"
    with pytest.raises(KernelRiskError):
        apply_portfolio_risk_once(
            unscaled_lineage_targets={"eline-a": 100_000},
            unscaled_portfolio_gross_cap_cents=-1,
            risk_decision=decision,
        )
