"""The one shared pure decision core (Plan Task 5).

``decide_core`` consumes only normalized candidates, integer
``DecisionConstraints``, risk state, prices, industries, deadlines and the
frozen trusted time. It runs portfolio risk exactly once, ranks, sizes,
projects lines and reserves — the executable admission and the shadow
admission both map their own authority into ``DecisionConstraints`` and call
this same function, so a regime block or a grant mismatch can never change
the shared economics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from src.screening.offensive.v3.contracts.capital import CapitalRiskSnapshot
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    CoreNoTrade,
    CorePortfolioDecision,
    DeadlineContract,
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


@dataclass(frozen=True)
class DecisionConstraints:
    """The integer decision constraints both admissions map their authority into."""

    lineage_gross_cap_cents: Mapping[str, int]
    sizing_config: SizingConfig
    portfolio_gross_cap_cents: int
    policy_epoch: int


class CoreError(RuntimeError):
    """Fail-closed rejection of a core decision call."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def decide_core(
    *,
    candidates: tuple[RawCandidate, ...],
    constraints: DecisionConstraints,
    capital: CapitalRiskSnapshot,
    prices: Mapping[str, int],
    industries: Mapping[str, str],
    deadlines: DeadlineContract,
    trusted_at: datetime,
) -> CorePortfolioDecision | CoreNoTrade:
    """The one shared decision core; pure and deterministic.

    The deadline order is validated fail-closed before anything else, matching
    the executable path. Risk runs exactly once; a regime block or a grant
    mismatch must never change the shared economics, so neither is computed
    here — both admissions map their authority into ``DecisionConstraints``
    before this function is called.
    """

    if not deadlines.ordering_valid():
        raise CoreError(
            "deadline_order_invalid",
            "deadline contract violates the frozen time-point order",
        )
    if trusted_at > deadlines.seal_creation_deadline:
        return CoreNoTrade(reason=BlockReason.DEADLINE_MISSED)
    risk = evaluate_portfolio_risk(capital=capital, trusted_at=trusted_at)
    if risk.block_reason is not None:
        return CoreNoTrade(reason=risk.block_reason)
    adjusted = apply_portfolio_risk_once(
        unscaled_lineage_targets=constraints.lineage_gross_cap_cents,
        unscaled_portfolio_gross_cap_cents=constraints.portfolio_gross_cap_cents,
        risk_decision=risk,
    )
    sized = size_portfolio(
        ranked_candidates=rank_candidates(candidates),
        adjusted_target_gross_by_lineage=dict(adjusted.adjusted_lineage_gross_cents),
        price_micros_by_candidate=prices,
        industry_by_candidate=industries,
        available_cash_cents=capital.available_cash_cents,
        config=constraints.sizing_config,
        adjusted_portfolio_gross_cap_cents=adjusted.adjusted_portfolio_gross_cap_cents,
        existing_portfolio_gross_cents=capital.total_gross_exposure_cents,
    )
    lines = decision_lines(sized)
    if not any(line.status == "ENTRY_PLANNED" for line in lines):
        return CoreNoTrade(reason=BlockReason.CAPACITY_EXHAUSTED)
    return CorePortfolioDecision(
        lines=lines,
        portfolio_gross_cap_cents=adjusted.adjusted_portfolio_gross_cap_cents,
        total_reserved_worst_case_cents=sum(
            line.worst_case_reserve_cents
            for line in lines
            if line.status == "ENTRY_PLANNED"
        ),
    )


__all__ = [
    "CoreError",
    "DecisionConstraints",
    "decide_core",
]
