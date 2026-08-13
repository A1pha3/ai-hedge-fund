"""Deterministic ranking, capacity, and integer sizing (Plan 04 Task 2).

Pure and deterministic: producer-supplied weights or risk labels cannot
bypass the central limits, and input permutation never changes the
selected orders. Sizing floors quantities to 100-share lots, blocks
high-price zero lots, reserves worst-case cash including worst-case
fees, and never reallocates leftover cash after observed T+1 fills.
"""

from __future__ import annotations

from typing import Mapping

from src.screening.offensive.v3.contracts.base import CanonicalModel
from src.screening.offensive.v3.kernel.config import SizingConfig
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    PortfolioDecisionLine,
    RawCandidate,
)

MICROS_PER_CENT: int = 10_000
LOT_UNITS: int = 100
FEE_PPM_SCALE: int = 1_000_000


class SizedCandidate(CanonicalModel):
    """One sized entry line with its reserve, or a typed block."""

    candidate_id: str
    security_id: str
    economic_lineage_id: str
    research_program_id: str
    stage_id: str
    status: str  # ENTRY_PLANNED | BLOCKED
    quantity_units: int = 0
    limit_price_micros: int = 0
    worst_case_fee_reserve_cents: int = 0
    worst_case_reserve_cents: int = 0
    block_reason: BlockReason | None = None


class SizingError(RuntimeError):
    """Fail-closed rejection of the sizing input."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def rank_candidates(
    candidates: tuple[RawCandidate, ...],
) -> tuple[RawCandidate, ...]:
    """Deterministic rank: larger risk-adjusted target first; ties break
    on candidate identity only (never on input order)."""

    return tuple(
        sorted(
            candidates,
            key=lambda c: (-c.unscaled_target_gross_cents, c.candidate_id),
        )
    )


def capacity_limit(
    *,
    target_gross_cents: int,
    ticker_used_cents: int,
    industry_used_cents: int,
    day_used_cents: int,
    portfolio_used_cents: int,
    config: SizingConfig,
) -> int:
    """The remaining gross this candidate may consume (never negative)."""

    remaining = (
        target_gross_cents,
        config.per_ticker_gross_cap_cents - ticker_used_cents,
        config.per_industry_gross_cap_cents - industry_used_cents,
        config.per_day_gross_cap_cents - day_used_cents,
        config.portfolio_gross_cap_cents - portfolio_used_cents,
    )
    return max(0, min(remaining))


def worst_case_fee_cents(gross_cents: int, fee_ppm: int) -> int:
    """Ceiling-rounded worst-case fee for reserve purposes."""

    return -(-gross_cents * fee_ppm // FEE_PPM_SCALE)


def size_portfolio(
    *,
    ranked_candidates: tuple[RawCandidate, ...],
    adjusted_target_gross_by_lineage: Mapping[str, int],
    price_micros_by_candidate: Mapping[str, int],
    industry_by_candidate: Mapping[str, str],
    available_cash_cents: int,
    config: SizingConfig,
    adjusted_portfolio_gross_cap_cents: int | None = None,
    existing_portfolio_gross_cents: int = 0,
) -> tuple[SizedCandidate, ...]:
    """Size admitted candidates into integer-lot entry lines.

    Deterministic: the same canonical input produces the same lines in
    the same order regardless of input permutation. When the risk-adjusted
    portfolio ceiling is supplied, it bounds the portfolio gross instead
    of the static config cap.

    ``existing_portfolio_gross_cents`` is the inherited gross exposure
    already held by the portfolio (open/pending/live/reserved/unattributed,
    aggregated once by the caller). Per spec line 499 it counts toward the
    portfolio gross cap, so new entries may only consume the remaining
    headroom - never a fresh full cap on top of existing exposure.
    """

    if available_cash_cents < 0:
        raise SizingError(
            "negative_available_cash", "available cash cannot be negative"
        )
    if existing_portfolio_gross_cents < 0:
        raise SizingError(
            "negative_existing_gross",
            "existing portfolio gross cannot be negative",
        )
    effective_config = config
    if adjusted_portfolio_gross_cap_cents is not None:
        if adjusted_portfolio_gross_cap_cents < 0:
            raise SizingError(
                "negative_portfolio_cap",
                "adjusted portfolio cap cannot be negative",
            )
        effective_config = SizingConfig(
            per_ticker_gross_cap_cents=config.per_ticker_gross_cap_cents,
            per_industry_gross_cap_cents=(
                config.per_industry_gross_cap_cents
            ),
            per_day_gross_cap_cents=config.per_day_gross_cap_cents,
            portfolio_gross_cap_cents=(
                adjusted_portfolio_gross_cap_cents
            ),
            worst_case_fee_ppm=config.worst_case_fee_ppm,
            min_lot_units=config.min_lot_units,
        )
    cash_remaining = available_cash_cents
    ticker_used: dict[str, int] = {}
    industry_used: dict[str, int] = {}
    day_used = 0
    portfolio_used = existing_portfolio_gross_cents
    lines: list[SizedCandidate] = []
    for candidate in ranked_candidates:
        lineage_target = adjusted_target_gross_by_lineage.get(
            candidate.economic_lineage_id
        )
        if lineage_target is None:
            lines.append(
                _blocked(candidate, BlockReason.CAPACITY_EXHAUSTED)
            )
            continue
        price = price_micros_by_candidate.get(candidate.candidate_id)
        if price is None or price <= 0:
            lines.append(_blocked(candidate, BlockReason.MISSING_ADV))
            continue
        if price > 2_000_000_000:  # board sanity boundary: 200_000.00 CNY
            lines.append(
                _blocked(candidate, BlockReason.PRICE_BOUNDARY_INVALID)
            )
            continue
        if price % MICROS_PER_CENT != 0:
            lines.append(
                _blocked(candidate, BlockReason.PRICE_BOUNDARY_INVALID)
            )
            continue
        ticker = candidate.security_id
        industry = industry_by_candidate.get(candidate.candidate_id, "")
        allowed = capacity_limit(
            target_gross_cents=min(
                candidate.unscaled_target_gross_cents, lineage_target
            ),
            ticker_used_cents=ticker_used.get(ticker, 0),
            industry_used_cents=industry_used.get(industry, 0),
            day_used_cents=day_used,
            portfolio_used_cents=portfolio_used,
            config=effective_config,
        )
        if allowed <= 0:
            lines.append(
                _blocked(candidate, BlockReason.CAPACITY_EXHAUSTED)
            )
            continue
        gross_micros = allowed * MICROS_PER_CENT * MICROS_PER_CENT // 10_000
        # units = gross_cents * micros_per_cent / price_micros
        raw_units = allowed * MICROS_PER_CENT // price
        quantity = raw_units // config.min_lot_units * config.min_lot_units
        while quantity > 0:
            gross_cents = quantity * price // MICROS_PER_CENT
            reserve = gross_cents + worst_case_fee_cents(
                gross_cents, config.worst_case_fee_ppm
            )
            if reserve <= cash_remaining:
                break
            quantity -= config.min_lot_units
        if quantity <= 0:
            lines.append(_blocked(candidate, BlockReason.LOT_FLOOR_ZERO))
            continue
        gross_cents = quantity * price // MICROS_PER_CENT
        fee_reserve = worst_case_fee_cents(
            gross_cents, config.worst_case_fee_ppm
        )
        reserve = gross_cents + fee_reserve
        cash_remaining -= reserve
        ticker_used[ticker] = ticker_used.get(ticker, 0) + gross_cents
        industry_used[industry] = (
            industry_used.get(industry, 0) + gross_cents
        )
        day_used += gross_cents
        portfolio_used += gross_cents
        lines.append(
            SizedCandidate(
                candidate_id=candidate.candidate_id,
                security_id=candidate.security_id,
                economic_lineage_id=candidate.economic_lineage_id,
                research_program_id=candidate.research_program_id,
                stage_id=candidate.stage_id,
                status="ENTRY_PLANNED",
                quantity_units=quantity,
                limit_price_micros=price,
                worst_case_fee_reserve_cents=fee_reserve,
                worst_case_reserve_cents=reserve,
                block_reason=None,
            )
        )
    return tuple(lines)


def _blocked(
    candidate: RawCandidate, reason: BlockReason
) -> SizedCandidate:
    return SizedCandidate(
        candidate_id=candidate.candidate_id,
        security_id=candidate.security_id,
        economic_lineage_id=candidate.economic_lineage_id,
        research_program_id=candidate.research_program_id,
        stage_id=candidate.stage_id,
        status="BLOCKED",
        block_reason=reason,
    )


def decision_lines(sized: tuple[SizedCandidate, ...]) -> tuple[PortfolioDecisionLine, ...]:
    """Project sized candidates into decision lines (planned and blocked
    lines stay separately visible)."""

    lines: list[PortfolioDecisionLine] = []
    for line in sized:
        lines.append(
            PortfolioDecisionLine(
                candidate_id=line.candidate_id,
                security_id=line.security_id,
                economic_lineage_id=line.economic_lineage_id,
                research_program_id=line.research_program_id,
                stage_id=line.stage_id,
                direction="ENTRY",
                quantity_units=line.quantity_units,
                limit_price_micros=line.limit_price_micros,
                worst_case_fee_reserve_cents=line.worst_case_fee_reserve_cents,
                worst_case_reserve_cents=line.worst_case_reserve_cents,
                status=line.status,
                block_reason=line.block_reason,
            )
        )
    return tuple(lines)


__all__ = [
    "FEE_PPM_SCALE",
    "LOT_UNITS",
    "MICROS_PER_CENT",
    "SizedCandidate",
    "SizingConfig",
    "SizingError",
    "capacity_limit",
    "decision_lines",
    "rank_candidates",
    "size_portfolio",
    "worst_case_fee_cents",
]
