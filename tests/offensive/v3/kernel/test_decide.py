"""Plan 04 Task 3: pure deterministic portfolio decision."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.screening.offensive.v3.contracts.risk import (
    RiskLatchState,
)
from src.screening.offensive.v3.kernel.decide import GrowthKernel, KernelError
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    DeadlineContract,
    KernelInput,
    NoTradeDecision,
    PortfolioDecision,
)
from src.screening.offensive.v3.kernel.sizing import SizingConfig

from test_admission import _candidate, _envelope, _policy_activation
from test_risk import _snapshot

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 15, 30, tzinfo=UTC)
CLOSE = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)


def _deadlines(**overrides) -> DeadlineContract:
    values = {
        "close_finalized_at": CLOSE,
        "seal_creation_deadline": CLOSE + timedelta(hours=1),
        "permit_issue_deadline": CLOSE + timedelta(hours=1, minutes=30),
        "permit_expires_at": CLOSE + timedelta(hours=18, minutes=25),
        "gateway_send_deadline": CLOSE + timedelta(hours=18, minutes=25),
        "broker_auction_cutoff": CLOSE + timedelta(hours=18, minutes=30),
    }
    values.update(overrides)
    return DeadlineContract(**values)


def _config(**overrides) -> SizingConfig:
    values = {
        "per_ticker_gross_cap_cents": 200_000,
        "per_industry_gross_cap_cents": 300_000,
        "per_day_gross_cap_cents": 500_000,
        "portfolio_gross_cap_cents": 400_000,
        "worst_case_fee_ppm": 3_000,
    }
    values.update(overrides)
    return SizingConfig(**values)


def _kernel_input(**overrides) -> KernelInput:
    policy = _policy_activation()
    values = {
        "portfolio_id": "paper-v3",
        "signal_session": NOW.date(),
        "decision_cycle_id": "cycle-1",
        "mode": policy.mode,
        "policy_activation": policy,
        "envelope": _envelope(policy),
        "capital": _snapshot(
            as_of=NOW,
            valid_until=NOW + timedelta(hours=18),
            as_observed_nav_cents=10_000_000,
            lifetime_high_water_mark_cents=10_000_000,
            active_epoch_high_water_mark_cents=10_000_000,
        ),
        "deadlines": _deadlines(),
        "trusted_evidence_cutoff": NOW - timedelta(minutes=5),
        "raw_candidates": (
            _candidate(unscaled_target_gross_cents=100_000),
        ),
        "price_micros_by_candidate": (("cand-1", 10_000_000),),
        "industry_by_candidate": (("cand-1", "electronics"),),
    }
    values.update(overrides)
    return KernelInput(**values)


def test_deadline_order_is_validated_fail_closed() -> None:
    broken = _deadlines(
        permit_issue_deadline=CLOSE + timedelta(minutes=30),
    )
    assert broken.ordering_valid() is False
    with pytest.raises(KernelError) as excinfo:
        GrowthKernel(_config()).decide(
            _kernel_input(deadlines=broken), trusted_at=NOW
        )
    assert excinfo.value.code == "deadline_order_invalid"


def test_seal_deadline_missed_is_no_trade() -> None:
    decision = GrowthKernel(_config()).decide(
        _kernel_input(),
        trusted_at=CLOSE + timedelta(hours=2),  # past seal deadline
    )
    assert isinstance(decision, NoTradeDecision)
    assert decision.reason is BlockReason.DEADLINE_MISSED


def test_stale_or_halted_capital_is_no_trade() -> None:
    from src.screening.offensive.v3.contracts.risk import (
        RiskSnapshotFreshness,
    )

    stale = GrowthKernel(_config()).decide(
        _kernel_input(
            capital=_snapshot(
                as_of=NOW,
                valid_until=NOW + timedelta(hours=18),
                freshness=RiskSnapshotFreshness.STALE,
            )
        ),
        trusted_at=NOW,
    )
    assert isinstance(stale, NoTradeDecision)
    assert stale.reason is BlockReason.STALE_CAPITAL

    halted = GrowthKernel(_config()).decide(
        _kernel_input(
            capital=_snapshot(
                as_of=NOW,
                valid_until=NOW + timedelta(hours=18),
                risk_latch=RiskLatchState.RISK_HALTED,
                as_observed_nav_cents=0,
                lifetime_drawdown_ppm=1_000_000,
                active_epoch_drawdown_ppm=1_000_000,
            )
        ),
        trusted_at=NOW,
    )
    assert isinstance(halted, NoTradeDecision)
    assert halted.reason in (
        BlockReason.NEGATIVE_NAV,
        BlockReason.RISK_HALTED,
    )


def test_no_candidates_is_no_signal() -> None:
    decision = GrowthKernel(_config()).decide(
        _kernel_input(raw_candidates=()), trusted_at=NOW
    )
    assert isinstance(decision, NoTradeDecision)
    assert decision.reason is BlockReason.NO_SIGNAL


def test_shadow_only_candidates_is_no_signal() -> None:
    decision = GrowthKernel(_config()).decide(
        _kernel_input(
            raw_candidates=(
                _candidate(producer_namespace="auto"),
            )
        ),
        trusted_at=NOW,
    )
    assert isinstance(decision, NoTradeDecision)
    assert decision.reason is BlockReason.NO_SIGNAL


def test_all_zero_lot_is_capacity_exhausted() -> None:
    decision = GrowthKernel(_config()).decide(
        _kernel_input(
            raw_candidates=(
                _candidate(unscaled_target_gross_cents=50_000),
            ),
            price_micros_by_candidate=(("cand-1", 100_000_000),),
        ),
        trusted_at=NOW,
    )
    assert isinstance(decision, NoTradeDecision)
    assert decision.reason is BlockReason.CAPACITY_EXHAUSTED


def test_decide_proposes_complete_portfolio_decision() -> None:
    decision = GrowthKernel(_config()).decide(
        _kernel_input(), trusted_at=NOW
    )
    assert isinstance(decision, PortfolioDecision)
    planned = [
        line for line in decision.lines if line.status == "ENTRY_PLANNED"
    ]
    assert len(planned) == 1
    assert planned[0].quantity_units % 100 == 0
    assert planned[0].worst_case_reserve_cents > 0
    assert decision.total_reserved_worst_case_cents == sum(
        line.worst_case_reserve_cents for line in planned
    )
    # Versions and hashes are copied from the frozen capital truth; the
    # kernel assigns no repository id, active status or signature.
    capital = _snapshot()
    assert decision.policy_epoch == capital.policy_epoch
    assert decision.authority_epoch == capital.authority_epoch
    assert decision.risk_epoch == capital.risk_epoch
    assert decision.capital_version == capital.capital_version
    assert decision.mode == capital.mode
    assert not hasattr(decision, "authorization_id")
    assert not hasattr(decision, "status")


def test_decide_is_deterministic_across_candidate_order() -> None:
    a = _candidate(
        "cand-a", security_id="600000.SH", unscaled_target_gross_cents=100_000
    )
    b = _candidate(
        "cand-b",
        security_id="600001.SH",
        unscaled_target_gross_cents=80_000,
    )
    prices = (("cand-a", 10_000_000), ("cand-b", 20_000_000))
    industries = (("cand-a", "electronics"), ("cand-b", "chemicals"))
    first = GrowthKernel(_config()).decide(
        _kernel_input(
            raw_candidates=(a, b),
            price_micros_by_candidate=prices,
            industry_by_candidate=industries,
        ),
        trusted_at=NOW,
    )
    second = GrowthKernel(_config()).decide(
        _kernel_input(
            raw_candidates=(b, a),
            price_micros_by_candidate=prices,
            industry_by_candidate=industries,
        ),
        trusted_at=NOW,
    )
    assert isinstance(first, PortfolioDecision)
    assert isinstance(second, PortfolioDecision)
    # Same canonical input semantics => same canonical output bytes/hash.
    assert first.canonical_bytes() == second.canonical_bytes()
    # Cross-process replay: re-deciding a reconstructed identical input
    # reproduces the exact bytes.
    replayed = GrowthKernel(_config()).decide(
        KernelInput.model_validate_json(
            _kernel_input(
                raw_candidates=(a, b),
                price_micros_by_candidate=prices,
                industry_by_candidate=industries,
            ).model_dump_json()
        ),
        trusted_at=NOW,
    )
    assert replayed.canonical_bytes() == first.canonical_bytes()


def test_drawdown_scaling_reduces_size_once() -> None:
    from decimal import Decimal

    from test_risk import _nav_for_drawdown

    hwm = 100_000_000  # 1M CNY NAV base
    nav = _nav_for_drawdown(hwm, 125_000)
    capital = _snapshot(
        as_of=NOW,
        valid_until=NOW + timedelta(hours=18),
        as_observed_nav_cents=nav,
        lifetime_high_water_mark_cents=hwm,
        active_epoch_high_water_mark_cents=hwm,
        lifetime_drawdown_ppm=125_000,
        active_epoch_drawdown_ppm=125_000,
    )
    big_config = _config(
        per_ticker_gross_cap_cents=5_000_000,
        per_industry_gross_cap_cents=5_000_000,
        per_day_gross_cap_cents=5_000_000,
        portfolio_gross_cap_cents=5_000_000,
    )
    big_candidate = (
        _candidate(unscaled_target_gross_cents=5_000_000),
    )
    baseline = GrowthKernel(big_config).decide(
        _kernel_input(
            raw_candidates=big_candidate,
            capital=_snapshot(
                as_of=NOW,
                valid_until=NOW + timedelta(hours=18),
                as_observed_nav_cents=hwm,
                lifetime_high_water_mark_cents=hwm,
                active_epoch_high_water_mark_cents=hwm,
            ),
        ),
        trusted_at=NOW,
    )
    scaled = GrowthKernel(big_config).decide(
        _kernel_input(raw_candidates=big_candidate, capital=capital),
        trusted_at=NOW,
    )
    assert isinstance(baseline, PortfolioDecision)
    assert isinstance(scaled, PortfolioDecision)
    base_qty = baseline.lines[0].quantity_units
    scaled_qty = scaled.lines[0].quantity_units
    # 12.5% drawdown => the SAME half multiplier scales the NAV-based
    # portfolio ceiling exactly once; the sized quantity shrinks with it.
    assert scaled_qty < base_qty
    assert scaled.portfolio_gross_cap_cents == (
        int(nav * Decimal("0.02")) * 500_000 // 1_000_000
    )
