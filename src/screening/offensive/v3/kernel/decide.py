"""Pure growth-kernel decision orchestration (Plan 04 Task 3).

Deterministic and side-effect free: the kernel assigns no repository id,
active status or signature. Identical canonical input produces identical
canonical output bytes/hash across processes and candidate orderings.
"""

from __future__ import annotations

from datetime import datetime

from src.screening.offensive.v3.kernel.admission import admit_candidates
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    KernelInput,
    NoTradeDecision,
    PortfolioDecision,
    RawCandidate,
)
from src.screening.offensive.v3.kernel.risk import (
    apply_portfolio_risk_once,
    evaluate_portfolio_risk,
)
from src.screening.offensive.v3.kernel.sizing import (
    SizingConfig,
    decision_lines,
    rank_candidates,
    size_portfolio,
)


class KernelError(RuntimeError):
    """Fail-closed rejection of a kernel input."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class GrowthKernel:
    """The pure portfolio decision function."""

    def __init__(self, sizing_config: SizingConfig) -> None:
        self._config = sizing_config

    def decide(
        self,
        kernel_input: KernelInput,
        *,
        trusted_at: datetime,
    ) -> PortfolioDecision | NoTradeDecision:
        """One complete decision proposal or a typed no-trade decision."""

        def no_trade(reason: BlockReason, detail: str = "") -> NoTradeDecision:
            return NoTradeDecision(
                portfolio_id=kernel_input.portfolio_id,
                signal_session=kernel_input.signal_session,
                decision_cycle_id=kernel_input.decision_cycle_id,
                reason=reason,
                detail=detail,
            )

        deadlines = kernel_input.deadlines
        if not deadlines.ordering_valid():
            raise KernelError(
                "deadline_order_invalid",
                "deadline contract violates the frozen time-point order",
            )
        if trusted_at > deadlines.seal_creation_deadline:
            return no_trade(
                BlockReason.DEADLINE_MISSED,
                "trusted time passed the seal creation deadline",
            )
        # Complete portfolio risk, fail closed, applied exactly once below.
        risk = evaluate_portfolio_risk(
            capital=kernel_input.capital, trusted_at=trusted_at
        )
        if risk.block_reason is not None:
            return no_trade(risk.block_reason)
        # Admission against the complete frozen authority.
        statuses = admit_candidates(
            kernel_input.raw_candidates,
            envelope=kernel_input.envelope,
            policy_activation=kernel_input.policy_activation,
        )
        admitted: list[RawCandidate] = []
        shadow = 0
        for candidate, status in zip(kernel_input.raw_candidates, statuses):
            if status.status == "ADMITTED":
                admitted.append(candidate)
            elif status.status == "SHADOW":
                shadow += 1
        if not admitted:
            return no_trade(
                BlockReason.NO_SIGNAL,
                f"no executable admitted candidates (shadow={shadow})",
            )
        # One risk application: the same multiplier scales every unscaled
        # lineage target and the portfolio ceiling before sizing.
        unscaled_by_lineage: dict[str, int] = {}
        for candidate in admitted:
            unscaled_by_lineage[
                candidate.economic_lineage_id
            ] = max(
                unscaled_by_lineage.get(
                    candidate.economic_lineage_id, 0
                ),
                candidate.unscaled_target_gross_cents,
            )
        adjusted = apply_portfolio_risk_once(
            unscaled_lineage_targets=unscaled_by_lineage,
            unscaled_portfolio_gross_cap_cents=_portfolio_cap_cents(
                kernel_input
            ),
            risk_decision=risk,
        )
        ranked = rank_candidates(tuple(admitted))
        sized = size_portfolio(
            ranked_candidates=ranked,
            adjusted_target_gross_by_lineage={
                lineage: gross
                for lineage, gross in adjusted.adjusted_lineage_gross_cents
            },
            price_micros_by_candidate=dict(
                kernel_input.price_micros_by_candidate
            ),
            industry_by_candidate=dict(
                kernel_input.industry_by_candidate
            ),
            available_cash_cents=kernel_input.capital.available_cash_cents,
            config=self._config,
            adjusted_portfolio_gross_cap_cents=(
                adjusted.adjusted_portfolio_gross_cap_cents
            ),
        )
        lines = decision_lines(sized)
        total_reserved = sum(
            line.worst_case_reserve_cents
            for line in lines
            if line.status == "ENTRY_PLANNED"
        )
        if not any(line.status == "ENTRY_PLANNED" for line in lines):
            return no_trade(
                BlockReason.CAPACITY_EXHAUSTED,
                "no candidate survived capacity and lot sizing",
            )
        capital = kernel_input.capital
        return PortfolioDecision(
            portfolio_id=kernel_input.portfolio_id,
            signal_session=kernel_input.signal_session,
            decision_cycle_id=kernel_input.decision_cycle_id,
            mode=kernel_input.mode,
            policy_activation_hash=capital.policy_activation_hash,
            policy_epoch=capital.policy_epoch,
            authority_epoch=capital.authority_epoch,
            risk_epoch=capital.risk_epoch,
            capital_snapshot_hash=capital.content_hash(),
            capital_version=capital.capital_version,
            lines=lines,
            portfolio_gross_cap_cents=(
                adjusted.adjusted_portfolio_gross_cap_cents
            ),
            total_reserved_worst_case_cents=total_reserved,
        )


def _portfolio_cap_cents(kernel_input: KernelInput) -> int:
    """Integer cents ceiling: NAV times the envelope portfolio cap."""

    nav = kernel_input.capital.as_observed_nav_cents
    cap_fraction = kernel_input.envelope.portfolio_gross_cap
    return int(nav * cap_fraction)


__all__ = ["GrowthKernel", "KernelError"]
