"""Single-pass complete portfolio risk for the growth kernel.

Pure and deterministic: no storage, no network, no clock, no I/O. The
drawdown multiplier applies EXACTLY ONCE to both each unscaled lineage
target and the unscaled portfolio gross ceiling; any unknown, stale or
halted component yields a typed block, never a zero/default exposure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Mapping

from src.screening.offensive.v3.contracts.capital import CapitalRiskSnapshot
from src.screening.offensive.v3.contracts.risk import (
    ReconciliationLatchState,
    RiskLatchState,
    RiskSnapshotCompleteness,
    RiskSnapshotFreshness,
    StageLossLatchState,
)
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    RiskAdjustedTargets,
    RiskDecision,
    RiskDecisionStatus,
)

MULTIPLIER_SCALE: Final[int] = 1_000_000
DRAWDDOWN_NO_SCALE_PPM: Final[int] = 100_000  # 10%
DRAWDDOWN_FULL_HALT_PPM: Final[int] = 150_000  # 15%


class KernelRiskError(RuntimeError):
    """Fail-closed rejection of a kernel risk evaluation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def drawdown_multiplier_ppm(drawdown_ppm: int) -> int:
    """Charter drawdown tiers on the active-epoch drawdown (ppm).

    <10%: no scaling (1.0); 10%–15%: linear to zero; >=15%: zero (the
    RISK_HALTED latch is enforced separately by the snapshot check).
    """

    if drawdown_ppm < 0:
        raise KernelRiskError(
            "negative_drawdown", "drawdown cannot be negative"
        )
    if drawdown_ppm <= DRAWDDOWN_NO_SCALE_PPM:
        return MULTIPLIER_SCALE
    if drawdown_ppm >= DRAWDDOWN_FULL_HALT_PPM:
        return 0
    remaining = DRAWDDOWN_FULL_HALT_PPM - drawdown_ppm
    band = DRAWDDOWN_FULL_HALT_PPM - DRAWDDOWN_NO_SCALE_PPM
    return remaining * MULTIPLIER_SCALE // band


def evaluate_portfolio_risk(
    *,
    capital: CapitalRiskSnapshot,
    trusted_at: datetime,
) -> RiskDecision:
    """Evaluate the complete capital risk state; fail closed on any gap."""

    def blocked(reason: BlockReason) -> RiskDecision:
        return RiskDecision(
            status=RiskDecisionStatus.BLOCKED,
            block_reason=reason,
            drawdown_multiplier_ppm=0,
            risk_adjustment_count=0,
        )

    if capital.freshness is RiskSnapshotFreshness.UNKNOWN:
        return blocked(BlockReason.UNKNOWN_CAPITAL_FRESHNESS)
    if capital.freshness is RiskSnapshotFreshness.STALE:
        return blocked(BlockReason.STALE_CAPITAL)
    if capital.valid_until < trusted_at:
        return blocked(BlockReason.STALE_CAPITAL)
    if capital.completeness is not RiskSnapshotCompleteness.COMPLETE:
        return blocked(BlockReason.UNKNOWN_EXPOSURE)
    if capital.as_observed_nav_cents <= 0:
        return blocked(BlockReason.NEGATIVE_NAV)
    if capital.risk_latch is RiskLatchState.RISK_HALTED:
        return blocked(BlockReason.RISK_HALTED)
    if (
        capital.reconciliation_latch
        is ReconciliationLatchState.RECONCILIATION_HALT
    ):
        return blocked(BlockReason.RECONCILIATION_HALTED)
    if any(
        latch.state is StageLossLatchState.STAGE_LOSS_HALTED
        for latch in capital.stage_loss_latches
    ):
        return blocked(BlockReason.STAGE_LOSS_HALTED)
    multiplier = drawdown_multiplier_ppm(capital.active_epoch_drawdown_ppm)
    return RiskDecision(
        status=RiskDecisionStatus.PASS,
        block_reason=None,
        drawdown_multiplier_ppm=multiplier,
        risk_adjustment_count=0,
    )


def apply_portfolio_risk_once(
    *,
    unscaled_lineage_targets: Mapping[str, int],
    unscaled_portfolio_gross_cap_cents: int,
    risk_decision: RiskDecision,
) -> RiskAdjustedTargets:
    """Apply the drawdown multiplier EXACTLY ONCE.

    The SAME multiplier scales every unscaled lineage target and the
    unscaled portfolio gross ceiling, before capacity or lot rounding.
    Double scaling is structurally excluded: this function consumes
    unscaled values and reports ``risk_adjustment_count == 1``.
    """

    if risk_decision.status is not RiskDecisionStatus.PASS:
        raise KernelRiskError(
            "risk_blocked",
            "risk adjustment requires a passing risk decision",
            block_reason=(
                risk_decision.block_reason.value
                if risk_decision.block_reason is not None
                else None
            ),
        )
    if unscaled_portfolio_gross_cap_cents < 0:
        raise KernelRiskError(
            "negative_gross_cap", "portfolio gross cap cannot be negative"
        )
    multiplier = risk_decision.drawdown_multiplier_ppm
    adjusted = tuple(
        (
            lineage_id,
            (
                _require_unscaled_target(lineage_id, gross_cents)
                * multiplier
                // MULTIPLIER_SCALE
            ),
        )
        for lineage_id, gross_cents in sorted(
            unscaled_lineage_targets.items()
        )
    )
    return RiskAdjustedTargets(
        adjusted_lineage_gross_cents=adjusted,
        adjusted_portfolio_gross_cap_cents=(
            unscaled_portfolio_gross_cap_cents
            * multiplier
            // MULTIPLIER_SCALE
        ),
        risk_adjustment_count=1,
    )


def _require_unscaled_target(lineage_id: str, gross_cents: int) -> int:
    if not lineage_id or not lineage_id.strip():
        raise KernelRiskError(
            "unknown_lineage", "lineage identity is required"
        )
    if gross_cents < 0:
        raise KernelRiskError(
            "unknown_lineage_target",
            "unscaled lineage target cannot be negative",
            lineage_id=lineage_id,
        )
    return gross_cents


__all__ = [
    "DRAWDDOWN_FULL_HALT_PPM",
    "DRAWDDOWN_NO_SCALE_PPM",
    "MULTIPLIER_SCALE",
    "KernelRiskError",
    "apply_portfolio_risk_once",
    "drawdown_multiplier_ppm",
    "evaluate_portfolio_risk",
]
