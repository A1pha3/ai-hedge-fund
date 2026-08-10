"""Plan 04 Task 3: pure deterministic portfolio decision."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

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
    snapshot = _policy_snapshot()
    policy = _policy_activation(policy_snapshot_hash=snapshot.content_hash())
    values = {
        "portfolio_id": "paper-v3",
        "signal_session": NOW.date(),
        "decision_cycle_id": "cycle-1",
        "mode": policy.mode,
        "policy_activation": policy,
        "policy_snapshot": snapshot,
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


def _policy_snapshot():
    """A minimal PolicySnapshot whose content_hash matches the activation.

    The activation's ``policy_snapshot_hash`` must equal the snapshot's
    ``content_hash``; the builder derives the activation from the snapshot so
    the pair is internally consistent.
    """
    from src.screening.offensive.v3.policy.models import PolicySnapshot

    return PolicySnapshot.model_validate_json(
        json.dumps(
            {
                "schema_major": 2,
                "policy_id": "growth-kernel-v3",
                "policy_version": "policy-v2",
                "policy_epoch": 1,
                "authority_epoch": 1,
                "risk_epoch": 1,
                "runtime_mode": "shadow",
                "capital": {
                    "governed_tiers": [2, 5, 10],
                    "exploration_aggregate_gross_cap": "0.02",
                    "portfolio_gross_cap": "0.02",
                    "single_name_gross_cap": "0.01",
                    "industry_gross_cap": "0.02",
                    "daily_entry_gross_cap": "0.02",
                    "stage_loss_budget_cap": "0.02",
                },
                "risk": {
                    "drawdown_scale_start": "0.10",
                    "drawdown_halt": "0.15",
                    "halt_is_latched": True,
                    "inherited_risk_counts_on_restart": True,
                },
                "adv": {
                    "lookback_sessions": 20,
                    "max_participation_rate": "0.05",
                    "missing_data_behavior": "fail_closed",
                },
                "producers": {
                    "btst_enabled": True,
                    "oversold_bounce_enabled": False,
                    "btst_regime_admission_mode": "IGNORE",
                    "regime_sizing_enabled": False,
                    "streak_sizing_enabled": False,
                    "trigger_strength_sizing_enabled": False,
                    "composite_sizing_enabled": False,
                },
                "execution": {
                    "entry_session_ordinal": 1,
                    "exit_session_ordinal": 10,
                    "order_type": "opening_auction_limit",
                    "time_in_force": "opening_auction",
                    "seal_deadline_after_t0_close_minutes": 240,
                    "permit_deadline_before_auction_minutes": 20,
                    "gateway_send_deadline_before_auction_minutes": 10,
                    "broker_auction_submission_cutoff_cn": "09:20:00",
                    "worst_case_cost_multiplier": "2",
                },
                "versions": {
                    "execution_contract_version": "t0-close-t1-open-t10-open.v1",
                    "cost_version": "cn-a-share-costs.v1",
                    "board_rule_version": "ashare-board-prefix-v1",
                    "calendar_version": "sse-szse-official-sessions.v1",
                    "lot_rule_version": "cn-board-lot.v1",
                    "price_boundary_version": "sse-szse-price-limits.v1",
                    "setup_version": "daily-action-setups-v1",
                    "exit_policy_version": "t10-open.v1",
                    "governance_version": "growth-kernel-governance.v2",
                },
                "evidence_gates": {
                    "min_mature_outcomes": 150,
                    "min_decision_days": 60,
                    "min_effective_sample_size": "60",
                    "min_distinct_tickers": 80,
                    "min_forward_months": 12,
                    "adverse_window_required": True,
                    "chronological_fold_gate_required": True,
                    "capacity_stress_required": True,
                    "tail_risk_gate_required": True,
                    "fresh_evidence_per_tier_required": True,
                    "slippage_stress_multiple": "2",
                    "minimum_economic_effect": "0.001",
                    "incremental_minimum_economic_effect": "0.001",
                },
            }
        ),
        strict=True,
    )


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


def test_producer_claim_is_clamped_to_grant_lineage_cap() -> None:
    # spec line 759 (E-1 regression): the lineage sizing target is bounded by
    # grant.lineage_gross_cap * NAV, not by the producer's self-reported
    # unscaled_target. Portfolio cap is deliberately loose (0.10 => 1_000_000)
    # and every config cap is 9_000_000, so ONLY grant enforcement can bound
    # the size. grant cap=0.02, NAV=10_000_000 => lineage ceiling 200_000; a
    # 9_000_000 producer claim must still size <= 200_000.
    from decimal import Decimal

    from test_admission import _envelope

    nav = 10_000_000
    capital = _snapshot(
        as_of=NOW,
        valid_until=NOW + timedelta(hours=18),
        as_observed_nav_cents=nav,
        lifetime_high_water_mark_cents=nav,
        active_epoch_high_water_mark_cents=nav,
    )
    snapshot = _policy_snapshot()
    policy = _policy_activation(policy_snapshot_hash=snapshot.content_hash())
    loose_envelope = _envelope(policy, portfolio_gross_cap=Decimal("0.10"))
    greedy = _candidate(unscaled_target_gross_cents=9_000_000)
    big_config = _config(
        per_ticker_gross_cap_cents=9_000_000,
        per_industry_gross_cap_cents=9_000_000,
        per_day_gross_cap_cents=9_000_000,
        portfolio_gross_cap_cents=9_000_000,
    )
    decision = GrowthKernel(big_config).decide(
        _kernel_input(
            raw_candidates=(greedy,),
            capital=capital,
            policy_activation=policy,
            policy_snapshot=snapshot,
            envelope=loose_envelope,
        ),
        trusted_at=NOW,
    )
    assert isinstance(decision, PortfolioDecision)
    planned = [
        line for line in decision.lines if line.status == "ENTRY_PLANNED"
    ]
    assert len(planned) == 1
    gross = planned[0].quantity_units * 10_000_000 // 10_000
    # Bounded by grant cap * NAV = 0.02 * 10_000_000 = 200_000, not the claim.
    assert gross <= 200_000


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


def test_decide_passes_existing_gross_exposure_to_sizing(monkeypatch) -> None:
    # spec line 499 (F-1 regression): decide() must feed the frozen
    # snapshot's total_gross_exposure_cents into size_portfolio so inherited
    # exposure tightens the new-entry cap. Guards the wiring, which a pure
    # sizing unit test cannot: the whole defect was decide() never passing it.
    # The sizing call now lives in the shared core module.
    import src.screening.offensive.v3.kernel.core as core_mod

    captured: dict[str, int] = {}
    real_size_portfolio = core_mod.size_portfolio

    def _spy(**kwargs):
        captured["existing"] = kwargs.get("existing_portfolio_gross_cents")
        return real_size_portfolio(**kwargs)

    monkeypatch.setattr(core_mod, "size_portfolio", _spy)
    capital = _snapshot(
        as_of=NOW,
        valid_until=NOW + timedelta(hours=18),
        as_observed_nav_cents=10_000_000,
        lifetime_high_water_mark_cents=10_000_000,
        active_epoch_high_water_mark_cents=10_000_000,
    )
    GrowthKernel(_config()).decide(
        _kernel_input(capital=capital),
        trusted_at=NOW,
    )
    assert captured["existing"] == capital.total_gross_exposure_cents
