"""Pure growth-kernel decision orchestration (Plan 04 Task 3).

Deterministic and side-effect free: the kernel assigns no repository id,
active status or signature. Identical canonical input produces identical
canonical output bytes/hash across processes and candidate orderings.
"""

from __future__ import annotations

from datetime import datetime

from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.kernel.admission import admit_candidates
from src.screening.offensive.v3.kernel.core import (
    CoreNoTrade,
    DecisionConstraints,
    decide_core,
)
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    KernelInput,
    NoTradeDecision,
    PortfolioDecision,
    RawCandidate,
    ShadowKernelInput,
)
from src.screening.offensive.v3.kernel.risk import evaluate_portfolio_risk
from src.screening.offensive.v3.kernel.shadow import decide_shadow
from src.screening.offensive.v3.kernel.sizing import SizingConfig


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
        """One complete decision proposal or a typed no-trade decision.

        The executable admission maps the policy activation + envelope +
        grants into ``DecisionConstraints``; the shared pure ``decide_core``
        then runs risk-once, rank, capacity, lot and reserve exactly like the
        shadow path — one decision core, two authority boundaries.
        """

        def no_trade(reason: BlockReason, detail: str = "") -> NoTradeDecision:
            return NoTradeDecision(
                portfolio_id=kernel_input.portfolio_id,
                signal_session=kernel_input.signal_session,
                decision_cycle_id=kernel_input.decision_cycle_id,
                reason=reason,
                detail=detail,
            )

        policy = kernel_input.policy_snapshot
        if policy.content_hash() != kernel_input.policy_activation.policy_snapshot_hash:
            return no_trade(
                BlockReason.POLICY_ENVELOPE_MISMATCH,
                "policy snapshot does not match the activation binding",
            )
        # The deadline order contract is validated fail-closed before
        # anything else (the shared core re-checks it as its own gate).
        if not kernel_input.deadlines.ordering_valid():
            raise KernelError(
                "deadline_order_invalid",
                "deadline contract violates the frozen time-point order",
            )
        # Complete portfolio risk, fail closed. The risk gate runs BEFORE
        # admission — a stale or halted capital truth is reported regardless
        # of candidates — and the shared core applies the multiplier exactly
        # once after admission.
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
        # One risk application happens inside the shared core; here we only
        # map the frozen authority into integer constraints.
        #
        # spec line 759 (E-1): the unscaled lineage target is the grant's
        # lineage_gross_cap * NAV, and the producer's self-reported
        # unscaled_target can only clamp it DOWN, never lift it above the
        # granted cap. A producer cannot size beyond its authorized lineage
        # ceiling by claiming a larger target.
        nav = kernel_input.capital.as_observed_nav_cents
        grant_cap_by_lineage = {
            grant.economic_lineage_id: int(nav * grant.lineage_gross_cap)
            for grant in kernel_input.envelope.lineage_grants
        }
        unscaled_by_lineage: dict[str, int] = {}
        for candidate in admitted:
            lineage = candidate.economic_lineage_id
            # The granted ceiling bounds the producer claim from above.
            bounded_target = min(
                candidate.unscaled_target_gross_cents,
                grant_cap_by_lineage.get(lineage, 0),
            )
            unscaled_by_lineage[lineage] = max(
                unscaled_by_lineage.get(lineage, 0),
                bounded_target,
            )
        # The policy's capital caps are an additional ceiling: the envelope
        # caps never lift a tighter policy cap, and vice versa — the tighter
        # of the two bounds the executable path.
        policy_portfolio_cap = int(nav * policy.capital.portfolio_gross_cap)
        policy_lineage_cap = int(nav * policy.capital.portfolio_gross_cap)
        for lineage in unscaled_by_lineage:
            unscaled_by_lineage[lineage] = min(
                unscaled_by_lineage[lineage], policy_lineage_cap
            )
        envelope_portfolio_cap = int(nav * kernel_input.envelope.portfolio_gross_cap)
        portfolio_cap = min(policy_portfolio_cap, envelope_portfolio_cap)
        result = decide_core(
            candidates=tuple(admitted),
            constraints=DecisionConstraints(
                lineage_gross_cap_cents=unscaled_by_lineage,
                sizing_config=self._config,
                portfolio_gross_cap_cents=portfolio_cap,
                policy_epoch=policy.policy_epoch,
            ),
            capital=kernel_input.capital,
            prices=dict(kernel_input.price_micros_by_candidate),
            industries=dict(kernel_input.industry_by_candidate),
            deadlines=kernel_input.deadlines,
            trusted_at=trusted_at,
        )
        if isinstance(result, CoreNoTrade):
            return no_trade(result.reason)
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
            lines=result.lines,
            portfolio_gross_cap_cents=result.portfolio_gross_cap_cents,
            total_reserved_worst_case_cents=result.total_reserved_worst_case_cents,
        )

    def decide_shadow(
        self,
        shadow_input: ShadowKernelInput,
    ) -> ShadowDecision | NoTradeDecision:
        """One arm decision through the shared decision core.

        No ``trusted_at`` argument: the frozen trusted time lives inside
        ``ShadowSharedInput``, so both arm calls consume exactly one
        observation. The shadow admission never manufactures a grant; it maps
        the Trial-bound ``PolicySnapshot`` into the same ``DecisionConstraints``
        and the same ``decide_core`` as the executable path.
        """

        return decide_shadow(shadow_input)


def _portfolio_cap_cents(kernel_input: KernelInput) -> int:
    """Integer cents ceiling: NAV times the envelope portfolio cap."""

    nav = kernel_input.capital.as_observed_nav_cents
    cap_fraction = kernel_input.envelope.portfolio_gross_cap
    return int(nav * cap_fraction)


__all__ = ["GrowthKernel", "KernelError"]
